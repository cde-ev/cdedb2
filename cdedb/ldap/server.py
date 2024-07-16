"""Custom ldaptor server."""

import asyncio
import logging
import sys
from asyncio import StreamReader, StreamWriter
from collections.abc import Coroutine
from typing import Any, Callable, Optional, Protocol

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

# see RFC 2696
PagedResultsControlType = b"1.2.840.113556.1.4.319"

KNOWN_CONTROL_TYPES = [PagedResultsControlType]

logger = logging.getLogger(__name__)


class ReplyCallback(Protocol):
    def __call__(self, response: pureldap.LDAPProtocolResponse,
                 controls: Optional[list[Any]] = None) -> None:
        ...


class LdapHandler():
    """Implementation of the ldap protocol via asyncio.

    Each time a new client connects to the server, a new instance of this class will
    be spawned. This instance is then associated to the whole communication with this
    client, and this client alone.
    """

    def __init__(
        self,
        root: CdEDBBaseLDAPEntry,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        self.root = root
        self.writer = writer
        self.reader = reader
        self.bound_user: Optional[CdEDBBaseLDAPEntry] = None

    berdecoder = pureldap.LDAPBERDecoderContext_TopLevel(
        inherit=pureldap.LDAPBERDecoderContext_LDAPMessage(
            fallback=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext(),
            ),
            inherit=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext(),
            ),
        ),
    )

    async def connection_callback(self) -> None:
        """Called for each new client connection."""
        while not self.reader.at_eof():
            try:
                # We need to read two bytes,
                # the sequence start tag and the length field.
                buffer = await self.reader.readexactly(2)
            except asyncio.IncompleteReadError as e:
                if e.partial:
                    logger.exception("Client disconnected with unhandled data")
                return

            length = pureber.ber2int(buffer[1:2], signed=0)
            if length & 0x80:
                # We have long-form encoded length.
                # Therefore this field contains the size of the the length.
                buffer += await self.reader.readexactly(length & ~0x80)
                length = pureber.ber2int(buffer[2:], signed=0)

            buffer += await self.reader.readexactly(length)

            # We already did some parsing which this function would also perform
            # but for the sake of simplicitly we only inlined the code necessary
            # to parse how many bytes we have to read from the network.
            msg, _ = pureber.berDecodeObject(self.berdecoder, buffer)

            # this is some very obscure code path, related to the construction of the
            # berdecoder object, but always guaranteed ...
            assert isinstance(msg, LDAPMessage)
            asyncio.create_task(self.handle(msg))

    @staticmethod
    def unsolicited_notification(msg: LDAPProtocolRequest) -> None:
        """Special kind of ldap request which might be ignored by the server."""
        logger.error(f"Got unsolicited notification: f{repr(msg)}")

    @staticmethod
    def check_controls(controls: Optional[tuple[Any, Any, Any]]) -> None:
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
            if criticality and controlType not in KNOWN_CONTROL_TYPES:
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
        resultCode: int, errorMessage: str,
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

        def reply(response: pureldap.LDAPProtocolResponse,
                  controls: Optional[list[Any]] = None) -> None:
            """Send a message back to the client."""
            response_msg = pureldap.LDAPMessage(response, controls=controls, id=msg.id)
            logger.debug(f"S->C {repr(response_msg)}")
            self.writer.write(response_msg.toWire())

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
                "Version %u not supported" % request.version,
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
        except ldaperrors.LDAPNoSuchObject:
            raise ldaperrors.LDAPInvalidCredentials  # pylint: disable=raise-missing-from

        self.bound_user = entry.bind(request.auth)

        msg = pureldap.LDAPBindResponse(
            resultCode=ldaperrors.Success.resultCode, matchedDN=entry.dn.getText(),
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
        self.writer.close()
        await self.writer.wait_closed()

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

    # see RFC 2696
    # pagedResultsControl ::= SEQUENCE {
    #         controlType     1.2.840.113556.1.4.319,
    #         criticality     BOOLEAN DEFAULT FALSE,
    #         controlValue    searchControlValue
    # }
    #
    # realSearchControlValue ::= SEQUENCE {
    #         size            INTEGER (0..maxInt),
    #                                 -- requested page size from client
    #                                 -- result set size estimate from server
    #         cookie          OCTET STRING
    # }
    #
    # We decided to store the offset of the last page (the ordinal of the last entry
    # which was already returned) in the cookie.
    async def handle_LDAPSearchRequest(
        self,
        request: LDAPSearchRequest,
        controls: Optional[pureldap.LDAPControls],
        reply: ReplyCallback,
    ) -> None:
        """Perform a search in the ldap tree."""
        self.check_controls(controls)
        base_dn = DistinguishedName(request.baseObject)

        is_paged = False
        paged_size = 0
        paged_cookie = 0
        for controlType, _, controlValue in (controls or []):
            if controlType != PagedResultsControlType:
                continue
            control_values = pureber.BERSequence.fromBER(
                pureber.CLASS_CONTEXT, controlValue, pureber.BERDecoderContext(),
            ).data[0]
            logger.debug(f"Control values: {control_values.data}")
            paged_size = control_values[0].value
            # Signaling we should return the first page.
            if control_values[1].value != b"":
                paged_cookie = int.from_bytes(control_values[1].value, sys.byteorder)
            is_paged = (paged_size != 0)
            logger.debug(f"Received Paged size: {paged_size}")
            logger.debug(f"Received Paged cookie: {paged_cookie}")

        # short-circuit if the requested entry is the root entry
        # ignore the paged_search request, since its only one entry
        if (
            request.baseObject == b""
            and request.scope == pureldap.LDAP_SCOPE_baseObject
            and request.filter == pureldap.LDAPFilter_present("objectClass")
        ):
            msg = pureldap.LDAPSearchResultEntry(
                objectName=self.root.dn.getText(), attributes=list(self.root.items()),
            )
            reply(msg)
            msg = pureldap.LDAPSearchResultDone(
                resultCode=ldaperrors.Success.resultCode,
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

        def filter_entry(entry: CdEDBBaseLDAPEntry) -> Optional[list[Any]]:
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

        results = [(result.dn, filter_entry(result)) for result in search_results
                   if filter_entry(result) is not None]

        total_size = 0
        new_cookie = None
        enc_new_cookie = b""
        if is_paged:
            total_size = len(results)
            results = results[paged_cookie:][:paged_size]
            # indicates this is the last page
            if paged_size + paged_cookie >= total_size:
                enc_new_cookie = b""
            else:
                new_cookie = paged_cookie + paged_size
                # determine the number of bytes we need to encode the cookie
                enc_new_cookie = new_cookie.to_bytes(
                    (new_cookie.bit_length() + 7) // 8, sys.byteorder)

        for result_dn, attributes in results:
            reply(pureldap.LDAPSearchResultEntry(
                objectName=result_dn.getText(), attributes=attributes))

        controls = None
        if is_paged:
            control_value = pureber.BERSequence([
                pureber.BERInteger(total_size), pureber.BEROctetString(enc_new_cookie),
            ])
            controls = [(PagedResultsControlType, None, control_value)]
            logger.debug(f"Returned Paged size: {total_size}")
            logger.debug(f"Retruned Paged cookie: {new_cookie}")

        reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode),
              controls=controls)

        return None
