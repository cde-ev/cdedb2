"""Custom ldaptor server."""

import logging
from asyncio import get_running_loop

from ldaptor import interfaces
from ldaptor.protocols import pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldaperrors import LDAPException
from ldaptor.protocols.ldap.ldapserver import LDAPServer
from ldaptor.protocols.pureldap import LDAPCompareRequest, LDAPSearchRequest
from twisted.internet import defer
from twisted.internet.protocol import ServerFactory
from twisted.python import log

from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import CdEDBBaseLDAPEntry, RootEntry

logger = logging.getLogger(__name__)


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
