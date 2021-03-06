"""Custom ldaptor server."""

from typing import Any

from ldaptor import interfaces
from ldaptor.protocols import pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldapserver import LDAPServer
from ldaptor.protocols.pureldap import LDAPSearchRequest
from twisted.internet import defer
from twisted.internet.protocol import ServerFactory

from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import CdEDBBaseLDAPEntry, RootEntry


class CdEDBLDAPServer(LDAPServer):
    """Subclass the LDAPServer to add some security restrictions.

    This mainly involve searches. Note that some handlers performing actions which
    modify the ldap tree are overwritten since we currently do not support them.
    """

    def getRootDSE(self, request, reply):  # type: ignore[no-untyped-def]
        """Shortcut to retrieve the root entry."""
        root: CdEDBBaseLDAPEntry = interfaces.IConnectedLDAPEntry(self.factory)
        # prepare the attributes of the root entry as they are expected by the Result
        attributes = list(root._fetch().items())  # pylint: disable=protected-access

        reply(
            pureldap.LDAPSearchResultEntry(
                objectName=root.dn.getText(), attributes=attributes
            )
        )
        return pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode)

    def _cbSearchGotBase(
            self, base: CdEDBBaseLDAPEntry, dn: DistinguishedName,
            request: LDAPSearchRequest, reply: Any
    ) -> defer.Deferred[None]:
        """Callback which is invoked after a search was performed."""

        def _sendEntryToClient(entry: CdEDBBaseLDAPEntry) -> None:
            """The callback function which sends the entry after it was found.

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

        bound_dn = self.boundUser.dn if self.boundUser else None

        d = base.search(
            filterObject=request.filter,
            attributes=request.attributes,
            scope=request.scope,
            derefAliases=request.derefAliases,
            sizeLimit=request.sizeLimit,
            timeLimit=request.timeLimit,
            typesOnly=request.typesOnly,
            callback=_sendEntryToClient,
            bound_dn=bound_dn,  # derivates from the interface specification!
        )

        def _done(_: Any) -> pureldap.LDAPSearchResultDone:
            return pureldap.LDAPSearchResultDone(
                resultCode=ldaperrors.Success.resultCode
            )

        d.addCallback(_done)
        return d

    def handle_LDAPCompareRequest(self, request, controls, reply) -> defer.Deferred:  # type: ignore[no-untyped-def, type-arg]
        if self.boundUser is None:
            return defer.fail(ldaperrors.LDAPUnwillingToPerform("No anonymous compare"))
        return super().handle_LDAPCompareRequest(request, controls, reply)

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
