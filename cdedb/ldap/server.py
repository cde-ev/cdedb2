from ldaptor.protocols import pureldap
from ldaptor.protocols.ldap import ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldapserver import LDAPServer
from ldaptor.protocols.pureldap import LDAPSearchRequest

from cdedb.ldap.entry import LDAPsqlEntry


class CdEDBLDAPServer(LDAPServer):
    """Subclass the LDAPServer to add some security restrictions."""

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
