"""Custom ldaptor server."""

import asyncio
import logging
from asyncio.transports import BaseTransport, Transport
from typing import Any, Callable, Coroutine, List, Optional, Tuple

from ldaptor.protocols import pureber, pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldaperrors import (
    LDAPException, LDAPProtocolError, LDAPUnwillingToPerform,
)
from ldaptor.protocols.pureldap import (
    LDAPCompareRequest, LDAPControls, LDAPMessage, LDAPProtocolRequest,
    LDAPProtocolResponse, LDAPSearchRequest,
)

from cdedb.ldap.entry import CdEDBBaseLDAPEntry

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
        self.transport: Transport = None  # type: ignore[assignment]
        self.root = root
        self.bound_user: Optional[CdEDBBaseLDAPEntry] = None

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
        assert isinstance(transport, Transport)
        self.transport = transport

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called once this instance of LdapServer lost the connection to its client."""
        # TODO maybe handle the exception or proper close the connection
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

    @staticmethod
    def unsolicited_notification(msg: LDAPProtocolRequest) -> None:
        """Special kind of ldap request which might be ignored by the server."""
        logger.error(f"Got unsolicited notification: f{repr(msg)}")

    @staticmethod
    def check_controls(controls: Optional[Tuple[Any, Any, Any]]) -> None:
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
        if controls is None:
            return

        for controlType, criticality, controlValue in controls:
            if criticality:
                raise ldaperrors.LDAPUnavailableCriticalExtension(
                    b"Unknown control %s" % controlType)

    @staticmethod
    async def handle_unknown(
        request: pureldap.LDAPProtocolRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Fallback handler if the current request to the server is not known."""
        logger.error(f"Unknown request: {repr(request)}")
        msg = pureldap.LDAPExtendedResponse(
            resultCode=ldaperrors.LDAPProtocolError.resultCode,
            responseName="1.3.6.1.4.1.1466.20036",
            errorMessage="Unknown request",
        )
        reply(msg)

    @staticmethod
    def fail_default(
        resultCode: int, errorMessage: str
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
        logger.debug(f"S<-C {repr(msg)}")

        def reply(response: pureldap.LDAPProtocolResponse) -> None:
            """Send a message back to the client."""
            response_msg = pureldap.LDAPMessage(response, id=msg.id)
            logger.debug(f"S->C {repr(response_msg)}")
            self.transport.write(response_msg.toWire())

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
            await handler(msg.value, msg.controls, reply)
        except LDAPException as e:
            logger.error(f"During handling of {name} (msg.id {msg.id}): {repr(e)}")
            reply(error_handler(e.resultCode, e.message))
        except Exception as e:
            logger.error(f"During handling of {name} (msg.id {msg.id}): {repr(e)}")
            reply(error_handler(LDAPProtocolError.resultCode, str(e)))
        return

    #
    # Below this follows the real stuff.
    #

    fail_LDAPBindRequest = pureldap.LDAPBindResponse

    async def handle_LDAPBindRequest(
        self,
        request: pureldap.LDAPBindRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Bind with a specific ldap entry to the server.

        The client may use this to get elevated access to the server. Otherwise, the
        connected server gets access level 'anonymous', with bound_user = None.
        """
        if request.version != 3:
            raise ldaperrors.LDAPProtocolError(
                "Version %u not supported" % request.version
            )

        self.check_controls(controls)

        if request.dn == b"":
            # anonymous bind
            self.bound_user = None
            reply(pureldap.LDAPBindResponse(resultCode=ldaperrors.Success.resultCode))
            return

        dn = DistinguishedName(request.dn)

        # masquerade the NoSuchObject as InvalidCredentials error, to not leak
        # information about the existence of ldap entries to non-privileged users
        try:
            entry = await self.root.lookup(dn)
        except ldaperrors.LDAPNoSuchObject:  # pylint: disable=raise-missing-from
            raise ldaperrors.LDAPInvalidCredentials

        self.bound_user = entry.bind(request.auth)

        msg = pureldap.LDAPBindResponse(
            resultCode=ldaperrors.Success.resultCode, matchedDN=entry.dn.getText()
        )
        reply(msg)

    async def handle_LDAPUnbindRequest(
        self,
        request: pureldap.LDAPUnbindRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Notification to close the connection to the client."""
        # explicitly do not check unsupported critical controls -- we
        # have no way to return an error, anyway.
        self.connection_lost(None)

    fail_LDAPCompareRequest = pureldap.LDAPCompareResponse

    async def handle_LDAPCompareRequest(
        self,
        request: LDAPCompareRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Check if a given ldap entry matches a given filter."""
        if self.bound_user is None:
            raise LDAPUnwillingToPerform("Anonymous compare is forbidden.")

        self.check_controls(controls)
        dn = DistinguishedName(request.entry)
        base = await self.root.lookup(dn)

        # base.search only works with Filter Objects, and not with
        # AttributeValueAssertion objects. Here we convert the AVA to an
        # equivalent Filter, so we can re-use the existing search
        # functionality we require.
        search_filter = pureldap.LDAPFilter_equalityMatch(
            attributeDesc=request.ava.attributeDesc,
            assertionValue=request.ava.assertionValue,
        )
        search_results = await base.search(
            filterObject=search_filter,
            scope=pureldap.LDAP_SCOPE_baseObject,
            derefAliases=pureldap.LDAP_DEREF_neverDerefAliases,
            bound_dn=self.bound_user.dn if self.bound_user else None,
        )
        if search_results:
            reply(pureldap.LDAPCompareResponse(ldaperrors.LDAPCompareTrue.resultCode))
        else:
            reply(pureldap.LDAPCompareResponse(ldaperrors.LDAPCompareFalse.resultCode))
        return None

    fail_LDAPSearchRequest = pureldap.LDAPSearchResultDone

    async def handle_LDAPSearchRequest(
        self,
        request: LDAPSearchRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Perform a search in the ldap tree."""
        self.check_controls(controls)
        base_dn = DistinguishedName(request.baseObject)

        # short-circuit if the requested entry is the root entry
        if (
            request.baseObject == b""
            and request.scope == pureldap.LDAP_SCOPE_baseObject
            and request.filter == pureldap.LDAPFilter_present("objectClass")
        ):
            msg = pureldap.LDAPSearchResultEntry(
                objectName=self.root.dn.getText(), attributes=list(self.root.items())
            )
            reply(msg)
            msg = pureldap.LDAPSearchResultDone(
                resultCode=ldaperrors.Success.resultCode
            )
            reply(msg)
            return None

        base = await self.root.lookup(base_dn)
        search_results = await base.search(
            filterObject=request.filter,
            # attributes=request.attributes,
            scope=request.scope,
            derefAliases=request.derefAliases,
            # sizeLimit=request.sizeLimit,
            # timeLimit=request.timeLimit,
            # typesOnly=request.typesOnly,
            bound_dn=self.bound_user.dn if self.bound_user else None,
        )

        def filter_entry(entry: CdEDBBaseLDAPEntry) -> Optional[List[Any]]:
            """Filter an entry before sending it to the client.

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

            # Return nothing if requesting user (self.bound_user) is not privileged.
            # anonymous users have only very limited access
            if self.bound_user is None:
                if entry.dn in entry.backend.anonymous_accessible_dns:
                    pass
                else:
                    return None
            # TODO do we need an admin dn?
            elif self.bound_user.dn == admin_dn:
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
                elif self.bound_user.dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.bound_user.dn):
                    if entry.backend.may_dua_access_user(self.bound_user.dn, entry):
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
                elif duas_dn.contains(self.bound_user.dn):
                    if entry.backend.may_dua_access_group(self.bound_user.dn, entry):
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
                elif duas_dn.contains(self.bound_user.dn):
                    # the dua is requesting its own data
                    if self.bound_user.dn == entry.dn:
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
                return list(attributes.items())
            else:
                return [
                    (key, attributes.get(key)) for key in request.attributes
                    if key in attributes]

        for result in search_results:
            filtered_attributes = filter_entry(result)
            if filtered_attributes is not None:
                reply(pureldap.LDAPSearchResultEntry(
                    objectName=result.dn.getText(), attributes=filtered_attributes))

        reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode))

        return None
