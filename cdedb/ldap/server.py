from ldaptor.protocols import pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldapserver import LDAPServer
from ldaptor.protocols.pureldap import LDAPSearchRequest
from twisted.internet.protocol import ServerFactory

from cdedb.ldap.entry import LDAPsqlEntry


class CdEDBLDAPServer(LDAPServer):
    """Subclass the LDAPServer to add some security restrictions."""

    def handle_LDAPBindRequest(self, request, controls, reply):
        # anonymous bind
        if request.dn == b"":
            # TODO close connection more gracefully by using ldaptors errors
            self.transport.loseConnection()
            return
        return super().handle_LDAPBindRequest(request, controls, reply)

    def _cbSearchGotBase(self, base: LDAPsqlEntry, dn: DistinguishedName, request: LDAPSearchRequest, reply):

        def _sendEntryToClient(entry: LDAPsqlEntry):
            """The callback function which sends the entry after it was found."""
            attributes = {key: value for key, value in entry.items()}
            # never ever return an userPassword in a search result
            if b"userPassword" in attributes:
                del attributes[b"userPassword"]

            tree = entry.tree
            users_dn = DistinguishedName(stringValue=tree.users_dn)
            groups_dn = DistinguishedName(stringValue=tree.groups_dn)
            duas_dn = DistinguishedName(stringValue=tree.duas_dn)
            admin_dn = DistinguishedName(tree.dua_dn("admin"))
            cloud_dn = DistinguishedName(tree.dua_dn("cloud"))

            return_result = True
            # the requested entry is a user
            if users_dn.contains(entry.dn):
                # the contains check succeeds also on equality
                if users_dn == entry.dn:
                    pass
                # the user is requesting his own data
                elif self.boundUser.dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.boundUser.dn):
                    pass
                # disallow other requests
                else:
                    return_result = False
            # the requested entry is a group
            elif groups_dn.contains(entry.dn):
                # the contains check succeeds also on equality
                if groups_dn == entry.dn:
                    pass
                # the request comes from a dua
                elif duas_dn.contains(self.boundUser.dn):
                    if self.boundUser.dn == cloud_dn:
                        pass
                    else:
                        return_result = False
                # disallow other requests
                else:
                    return_result = False
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
                        return_result = False
                # disallow other requests
                else:
                    return_result = False

            # TODO do we need an admin dn?
            if self.boundUser.dn == admin_dn:
                return_result = True

            # filter the attributes requested in the search
            if b"*" in request.attributes or len(request.attributes) == 0:
                filtered_attributes = attributes.items()
            else:
                filtered_attributes = [
                    (key, attributes.get(key)) for key in request.attributes
                    if key in attributes]

            # return a result only if the boundUser is allowed to access it
            if return_result:
                reply(pureldap.LDAPSearchResultEntry(objectName=entry.dn.getText(),
                                                     attributes=filtered_attributes))
            # otherwise, return nothing

        d = base.search(
            filterObject=request.filter,
            attributes=request.attributes,
            scope=request.scope,
            derefAliases=request.derefAliases,
            sizeLimit=request.sizeLimit,
            timeLimit=request.timeLimit,
            typesOnly=request.typesOnly,
            callback=_sendEntryToClient,
        )

        def _done(_):
            return pureldap.LDAPSearchResultDone(
                resultCode=ldaperrors.Success.resultCode
            )

        d.addCallback(_done)
        return d


class LDAPServerFactory(ServerFactory):
    """
    Our Factory is meant to persistently store the ldap tree
    """

    protocol = CdEDBLDAPServer

    def __init__(self, root):
        self.root = root

    def buildProtocol(self, addr):
        proto = self.protocol()
        proto.debug = self.debug
        proto.factory = self
        return proto
