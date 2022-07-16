"""Custom ldaptor server."""

import asyncio
import logging
from asyncio.transports import BaseTransport, Transport
from typing import Any, Callable, Coroutine, List, Optional, Tuple

from ldaptor import interfaces
from ldaptor.protocols import pureber, pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldaperrors import LDAPException, LDAPProtocolError
from ldaptor.protocols.ldap.ldapserver import (
    LDAPServer, LDAPServerConnectionLostException,
)
from ldaptor.protocols.pureldap import (
    LDAPCompareRequest, LDAPControls, LDAPMessage, LDAPProtocolRequest,
    LDAPProtocolResponse, LDAPSearchRequest,
)
from twisted.internet import defer
from twisted.internet.protocol import ServerFactory
from twisted.python import log

from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import CdEDBBaseLDAPEntry, RootEntry

ReplyCallback = Callable[[pureldap.LDAPProtocolResponse], None]

logger = logging.getLogger(__name__)


class LdapServer(asyncio.Protocol):
    """Implementation of the ldap protocol via asyncio.

    Each time a new client connects to the server, a new instance of this class will
    be spawned. This instance is then associated to the whole communication with this
    client, and this client alone.
    """

    def __init__(self, root: CdEDBBaseLDAPEntry):
        self.buffer = b""
        self.connected = False
        self.transport: Transport = None  # type: ignore[assignment]
        self.root = root

    berdecoder = pureldap.LDAPBERDecoderContext_TopLevel(
        inherit=pureldap.LDAPBERDecoderContext_LDAPMessage(
            fallback=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext()
            ),
            inherit=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext()
            ),
        )
    )

    def connection_made(self, transport: BaseTransport) -> None:
        """Called once this instance of LdapServer was connected to its client."""
        self.connected = True
        assert isinstance(transport, Transport)
        self.transport = transport

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called once this instance of LdapServer lost the connection to its client."""
        # TODO maybe handle the exception or proper close the connection
        self.connected = False
        self.transport.close()

    def data_received(self, data: bytes) -> None:
        """Called each time the server received binary data from its client.

        Note that this makes no guarantee about receiving semantic messages in one part.
        So, buffering the received data and decoding it manually is mandatory.
        """
        self.buffer += data
        while 1:
            try:
                msg, len_decoded = pureber.berDecodeObject(self.berdecoder, self.buffer)
            except pureber.BERExceptionInsufficientData:
                msg, len_decoded = None, 0
            self.buffer = self.buffer[len_decoded:]
            if msg is None:
                break
            # this is some very obscure code path, related to the construction of the
            # berdecoder object, but always guaranteed ...
            assert isinstance(msg, LDAPMessage)
            asyncio.create_task(self.handle(msg))

    def queue(self, msg_id: int, op: pureldap.LDAPProtocolResponse) -> None:
        """Queuing messages which shall be sent to the client.

        Note that order of messages is important.
        """
        if not self.connected:
            raise LDAPServerConnectionLostException()
        msg = pureldap.LDAPMessage(op, id=msg_id)
        logger.debug("S->C %s" % repr(msg))
        self.transport.write(msg.toWire())

    def unsolicited_notification(self, msg: LDAPProtocolRequest) -> None:
        """Special kind of ldap request which might be ignored by the server."""
        logger.error("Got unsolicited notification: %s" % repr(msg))

    def check_controls(self, controls: Optional[Tuple[Any, Any, Any]]) -> None:
        """Check controls which are sent together with the current request.

        Controls are an ldap mechanism to give additional parameters or information
        to requests. For example, a search request may contain a control to tell the
        client if the server knows a different ldap server which might know the
        requested entry.

        Controls have a 'criticality' property. If this is set to true, the server must
        abort the current request if the control is unknown to the server. Otherwise,
        it must ignore unknown controls.

        Currently, no controls are supported by this ldap server.
        """
        if controls is not None:
            for controlType, criticality, controlValue in controls:
                if criticality:
                    raise ldaperrors.LDAPUnavailableCriticalExtension(
                        b"Unknown control %s" % controlType
                    )

    async def handle_unknown(
        self,
        request: pureldap.LDAPProtocolRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Fallback handler if the current request to the server is not known."""
        logger.error("Unknown request: %r" % request)
        msg = pureldap.LDAPExtendedResponse(
            resultCode=ldaperrors.LDAPProtocolError.resultCode,
            responseName="1.3.6.1.4.1.1466.20036",
            errorMessage="Unknown request",
        )
        reply(msg)

    def fail_default(
        self, resultCode: int, errorMessage: str
    ) -> pureldap.LDAPProtocolResponse:
        """Fallback error handler."""
        return pureldap.LDAPExtendedResponse(
            resultCode=resultCode,
            responseName="1.3.6.1.4.1.1466.20036",
            errorMessage=errorMessage,
        )

    async def handle(self, msg: LDAPMessage) -> None:
        """Handle one request to the ldap server.

        A request is always contained in an LDAPMessage object. For further information,
        please consult the specific RFCs or the implementation details of ldaptor.
        """
        assert isinstance(msg.value, pureldap.LDAPProtocolRequest)
        logger.debug("S<-C %s" % repr(msg))

        # exactly unsolicited notifications have a message id of 0
        if msg.id == 0:
            self.unsolicited_notification(msg.value)
            return

        name = msg.value.__class__.__name__
        handler: Callable[
            [LDAPProtocolRequest, Optional[LDAPControls], ReplyCallback],
            Coroutine[None, None, None],
        ]
        handler = getattr(self, "handle_" + name, self.handle_unknown)
        error_handler: Callable[[int, str], LDAPProtocolResponse]
        error_handler = getattr(self, "fail_" + name, self.fail_default)
        try:
            await handler(
                msg.value,
                msg.controls,
                lambda response_msg: self.queue(msg.id, response_msg),
            )
        except LDAPException as e:
            logger.error(f"During handling of {name} (msg.id {msg.id}): {repr(e)}")
            response = error_handler(e.resultCode, e.message)
            self.queue(msg.id, response)
        except Exception as e:
            logger.error(f"During handling of {name} (msg.id {msg.id}): {repr(e)}")
            response = error_handler(LDAPProtocolError.resultCode, str(e))
            self.queue(msg.id, response)


class CdEDBLDAPServer(LDAPServer):
    """Subclass the LDAPServer to add some security restrictions.

    This mainly involve searches. Note that some handlers performing actions which
    modify the ldap tree are overwritten since we currently do not support them.
    """

    def getRootDSE(self, request, reply):  # type: ignore[no-untyped-def]
        """Helper function which should never be called from outside."""
        raise NotImplementedError

    def _cbSearchLDAPError(self, reason):  # type: ignore[no-untyped-def]
        """Helper function which should never be called from outside."""
        raise NotImplementedError

    def _cbSearchOtherError(self, reason):  # type: ignore[no-untyped-def]
        """Helper function which should never be called from outside."""
        raise NotImplementedError

    fail_LDAPSearchRequest = pureldap.LDAPSearchResultDone

    async def _handle_search_request(self, request: LDAPSearchRequest, controls,  # type: ignore[no-untyped-def]
                                     reply) -> None:
        self.checkControls(controls)

        root: CdEDBBaseLDAPEntry = interfaces.IConnectedLDAPEntry(self.factory)
        base_dn = DistinguishedName(request.baseObject)

        # short-circuit if the requested entry is the root entry
        if (
            request.baseObject == b""
            and request.scope == pureldap.LDAP_SCOPE_baseObject
            and request.filter == pureldap.LDAPFilter_present("objectClass")
        ):
            # prepare the attributes of the root entry as they are expected
            attributes = list(root._fetch().items())  # pylint: disable=protected-access
            reply(pureldap.LDAPSearchResultEntry(
                objectName=root.dn.getText(), attributes=attributes))
            reply(pureldap.LDAPSearchResultDone(
                resultCode=ldaperrors.Success.resultCode))
            return None

        try:
            base = await root._lookup(base_dn)
        except LDAPException as e:
            logger.error(f"Search: Encountered {e}.")
            reply(pureldap.LDAPSearchResultDone(resultCode=e.resultCode))
            return None
        except Exception as e:
            logger.error(
                f"Search: Encountered {e} during compare of {base_dn.getText()}.")
            reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.other))
            return None

        bound_dn = self.boundUser.dn if self.boundUser else None
        search_results = await base._search(
            filterObject=request.filter,
            # attributes=request.attributes,
            scope=request.scope,
            derefAliases=request.derefAliases,
            # sizeLimit=request.sizeLimit,
            # timeLimit=request.timeLimit,
            # typesOnly=request.typesOnly,
            bound_dn=bound_dn,  # derivates from the interface specification!
        )

        def send_entry_to_client(entry: CdEDBBaseLDAPEntry) -> None:
            """Sent an entry to the client.

            This is the main place where our security restrictions are implemented.
            We currently restrict:
            - anonymous access (without binding to an ldap entry previously)
            - which entries may access other entries
            - which attributes may be accessed by which entries
            """
            attributes = {key: value for key, value in entry.items()}  # pylint: disable=unnecessary-comprehension
            # never ever return an userPassword in a search result
            if b"userPassword" in attributes:
                del attributes[b"userPassword"]

            users_dn = entry.backend.users_dn
            groups_dn = entry.backend.groups_dn
            duas_dn = entry.backend.duas_dn
            admin_dn = entry.backend.dua_dn("admin")

            # Return nothing if requesting user (self.boundUser) is not privileged.
            # anonymous users have only very limited access
            if self.boundUser is None:
                if entry.dn in entry.backend.anonymous_accessible_dns:
                    pass
                else:
                    return None
            # TODO do we need an admin dn?
            elif self.boundUser.dn == admin_dn:
                pass
            # handle requests to not-restricted entries
            elif entry.dn in {entry.backend.subschema_dn, entry.backend.de_dn,
                              entry.backend.cde_dn}:
                pass
            # the requested entry is a user
            elif users_dn.contains(entry.dn):
                # the contains check succeeds also on equality
                if users_dn == entry.dn:
                    pass
                # the user is requesting his own data
                elif self.boundUser.dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.boundUser.dn):
                    if entry.backend.may_dua_access_user(self.boundUser.dn, entry):
                        pass
                    else:
                        return None
                # disallow other requests
                else:
                    return None
            # the requested entry is a group
            elif groups_dn.contains(entry.dn):
                # the contains check succeeds also on equality
                if groups_dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.boundUser.dn):
                    if entry.backend.may_dua_access_group(self.boundUser.dn, entry):
                        pass
                    else:
                        return None
                # disallow other requests
                else:
                    return None
            # the requested entry is a dua
            elif duas_dn.contains(entry.dn):
                # the contains check succeeds also on equality
                if duas_dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.boundUser.dn):
                    # the dua is requesting its own data
                    if self.boundUser.dn == entry.dn:
                        pass
                    else:
                        return None
                # disallow other requests
                else:
                    return None
            else:
                raise RuntimeError("Impossible.")

            # filter the attributes requested in the search
            # TODO maybe restrict some attributes depending on the requesting entity
            if b"*" in request.attributes or len(request.attributes) == 0:
                filtered_attributes = list(attributes.items())
            else:
                filtered_attributes = [
                    (key, attributes.get(key)) for key in request.attributes
                    if key in attributes]

            # Sent a reply then return.
            reply(pureldap.LDAPSearchResultEntry(objectName=entry.dn.getText(),
                                                 attributes=filtered_attributes))
            return None

        for result in search_results:
            send_entry_to_client(result)
        reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode))

        return None

    def handle_LDAPSearchRequest(self, request: LDAPSearchRequest, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        d = defer.Deferred.fromFuture(get_running_loop().create_task(
            self._handle_search_request(request, controls, reply)))
        d.addErrback(log.err)
        return d

    async def _handle_compare_request(self, request: LDAPCompareRequest, controls,  # type: ignore[no-untyped-def]
                                      reply) -> None:
        self.checkControls(controls)
        base_dn = DistinguishedName(request.entry)
        root: CdEDBBaseLDAPEntry = interfaces.IConnectedLDAPEntry(self.factory)

        try:
            base = await root._lookup(base_dn)
        except LDAPException as e:
            logger.error(f"Compare: Encountered {e}.")
            reply(pureldap.LDAPCompareResponse(resultCode=e.resultCode))
            return None
        except Exception as e:
            logger.error(
                f"Compare: Encountered {e} during compare of {base_dn.getText()}.")
            reply(pureldap.LDAPCompareResponse(resultCode=ldaperrors.other))
            return None

        bound_dn = self.boundUser.dn if self.boundUser else None
        # base.search only works with Filter Objects, and not with
        # AttributeValueAssertion objects. Here we convert the AVA to an
        # equivalent Filter so we can re-use the existing search
        # functionality we require.
        search_filter = pureldap.LDAPFilter_equalityMatch(
            attributeDesc=request.ava.attributeDesc,
            assertionValue=request.ava.assertionValue
        )
        search_results = await base._search(
            filterObject=search_filter,
            scope=pureldap.LDAP_SCOPE_baseObject,
            derefAliases=pureldap.LDAP_DEREF_neverDerefAliases,
            bound_dn=bound_dn,  # derivates from the interface specification!
        )

        if search_results:
            reply(pureldap.LDAPCompareResponse(ldaperrors.LDAPCompareTrue.resultCode))
        else:
            reply(pureldap.LDAPCompareResponse(ldaperrors.LDAPCompareFalse.resultCode))

        return None

    def handle_LDAPCompareRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        if self.boundUser is None:
            return defer.fail(ldaperrors.LDAPUnwillingToPerform("No anonymous compare"))
        d = defer.Deferred.fromFuture(get_running_loop().create_task(
            self._handle_compare_request(request, controls, reply)))
        d.addErrback(log.err)
        return d

    def handle_LDAPDelRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))

    def handle_LDAPAddRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))

    def handle_LDAPModifyDNRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))

    def handle_LDAPModifyRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))

    def handle_LDAPExtendedRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))

    def extendedRequest_LDAPPasswordModifyRequest(self, data, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        return defer.fail(ldaperrors.LDAPUnwillingToPerform("Not implemented"))


class CdEDBLDAPServerFactory(ServerFactory):
    """Factory to provide a CdEDBLDAPServer instance per connection."""

    protocol = CdEDBLDAPServer
    root: RootEntry
    debug: bool

    def __init__(self, backend: LDAPsqlBackend, debug: bool = False) -> None:
        self.root = RootEntry(backend)
        self.debug = debug

    def buildProtocol(self, addr) -> CdEDBLDAPServer:  # type: ignore[no-untyped-def]
        proto = self.protocol()
        proto.debug = self.debug
        proto.factory = self
        return proto
