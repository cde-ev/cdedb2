from typing import Optional, Union

import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import zope.interface
from ldaptor import attributeset, entry
from ldaptor.protocols.ldap import distinguishedname, ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from twisted.internet import defer, error
from twisted.python import failure


def get_duas():
    query = "SELECT cn FROM ldap.duas"
    dua_rdns = ...
    return dua_rdns


def get_assembly_presider_groups():
    pass


def get_event_orga_groups():
    pass


def get_ml_moderator_groups():
    pass


def get_ml_subscriber_groups():
    pass


def get_users():
    pass


LDAP_TREE = {
    "dc=de": {
        "dc=cde-ev": {
            "ou=dua": get_duas,
            "ou=groups": {
                "ou=assembly-presiders": get_assembly_presider_groups,
                "ou=event-orgas": get_event_orga_groups,
                "ou=ml-moderators": get_ml_moderator_groups,
                "ou=ml-subscribers": get_ml_subscriber_groups,
                "ou=status": [
                    "cn=is_active",
                    "cn=is_assembly_admin",
                    "cn=is_assembly_realm",
                    "cn=is_cdelokal_admin",
                    "cn=is_core_admin",
                    "cn=is_event_admin",
                    "cn=is_event_realm",
                    "cn=is_finance_admin",
                    "cn=is_member",
                    "cn=is_ml_admin",
                    "cn=is_ml_realm",
                    "cn=is_searchable"
                ],
            },
            "ou=users": get_users,
        }
    }
}


# mimik the implementation of LDAPTreeEntry
@zope.interface.implementer(ldaptor.interfaces.IConnectedLDAPEntry)
class LDAPsqlEntry(
    # use BaseLDAPEntry, since the entries are not modifiable
    ldaptor.entry.BaseLDAPEntry,
    ldaptor.entryhelpers.DiffTreeMixin,
    ldaptor.entryhelpers.SubtreeFromChildrenMixin,
    ldaptor.entryhelpers.MatchMixin,
    ldaptor.entryhelpers.SearchByTreeWalkingMixin
):
    # here, implement the methods promised by the interface
    # TODO maybe we need to implement the IEditableLDAPEntry interface too, since the
    #  default ldapserver does not take this into account properly. However, we can
    #  probably simply rise an exception if those methods are used.
    def __init__(self, dn: Optional[Union[DistinguishedName,str]], *a, **kw):
        # root entry
        if dn is None:
            dn = ""
        entry.BaseLDAPEntry.__init__(self, dn, *a, **kw)
        if self.dn != "":
            self._load()

    def _load(self):
        # TODO load entry's attributes from the database from only knowing its dn
        attributes = ...
        for k, v in attributes.items():
            self._attributes[k] = attributeset.LDAPAttributeSet(k, v)

    def parent(self):
        # root entry
        if self.dn == "":
            return None
        else:
            return self.__class__(self.dn.up())

    def _children(self, callback=None):
        dn_str = self.dn.getText()
        subtree = LDAP_TREE
        # loop backwards through the DN
        for rdn in dn_str.split(",")[::-1]:
            # we reached a leaf in the ldap tree
            if not isinstance(subtree, dict):
                return None
            # this can only happen if the dn is not in the ldap tree
            if rdn not in subtree:
                return None
            subtree = subtree[rdn]

        # get the children from the subtree
        if isinstance(subtree, dict):
            children_rdns = list(subtree.keys())
        elif isinstance(subtree, list):
            children_rdns = list(*subtree)
        elif callable(subtree):
            children_rdns = subtree()
        else:
            raise RuntimeError("Impossible")

        children = [self.__class__(f"{rdn},{dn_str}") for rdn in children_rdns]
        if callback is None:
            return children
        else:
            for c in children:
                callback(c)
            return None

    def children(self, callback=None):
        return defer.maybeDeferred(self._children, callback=callback)

    def lookup(self, dn):
        dn = distinguishedname.DistinguishedName(dn)
        if not self.dn.contains(dn):
            return defer.fail(ldaperrors.LDAPNoSuchObject(dn.getText()))
        if dn == self.dn:
            return defer.succeed(self)

        # TODO make more understandable
        it = dn.split()
        me = self.dn.split()
        assert len(it) > len(me)
        assert (len(me) == 0) or (it[-len(me):] == me)
        rdn = it[-len(me) - 1]
        childDN = distinguishedname.DistinguishedName(listOfRDNs=(rdn,) + me)
        c = self.__class__(childDN)
        return c.lookup(dn)

    def addChild(self, rdn, attributes):
        # TODO fail upon call
        d = self._addChild(rdn, attributes)
        return d

    def delete(self):
        # TODO fail upon call
        return defer.maybeDeferred(self._delete)

    def deleteChild(self, rdn):
        # TODO fail upon call
        return defer.maybeDeferred(self._deleteChild, rdn)

    # TODO where is this used?
    def __lt__(self, other):
        if not isinstance(other, LDAPsqlEntry):
            return NotImplemented
        return self.dn < other.dn

    def __gt__(self, other):
        if not isinstance(other, LDAPsqlEntry):
            return NotImplemented
        return self.dn > other.dn

    def commit(self):
        # TODO fail upon call
        return None

    def move(self, newDN):
        # TODO fail upon call
        return defer.maybeDeferred(self._move, newDN)
