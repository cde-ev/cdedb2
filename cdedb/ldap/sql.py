import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import zope.interface
from ldaptor import attributeset, entry
from ldaptor.protocols.ldap import distinguishedname, ldaperrors
from twisted.internet import defer, error
from twisted.python import failure


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
    def __init__(self, dn, *a, **kw):
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
        # TODO select direct childrens from database and instantiate them
        children = list()
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
