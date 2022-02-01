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
        if request.dn == b"":
            # anonymous bind
            raise ldaperrors.LDAPAuthMethodNotSupported("Anonymous bind not supported.")
        return super().handle_LDAPBindRequest(request, controls, reply)

    def _cbSearchGotBase(self, base: LDAPsqlEntry, dn: DistinguishedName, request: LDAPSearchRequest, reply):
        def _sendEntryToClient(entry):
            requested_attribs = request.attributes
            if len(requested_attribs) > 0 and b"*" not in requested_attribs:
                filtered_attribs = [
                    (k, entry.get(k)) for k in requested_attribs if k in entry
                ]
            else:
                filtered_attribs = entry.items()
            reply(
                pureldap.LDAPSearchResultEntry(
                    objectName=entry.dn.getText(),
                    attributes=filtered_attribs,
                )
            )

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
