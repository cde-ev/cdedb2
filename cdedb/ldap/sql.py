from typing import Optional, Tuple, Union

import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import zope.interface
from ldaptor import attributeset, entry
from ldaptor.protocols.ldap import distinguishedname, ldaperrors
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from twisted.internet import defer, error
from twisted.python import failure

from cdedb.common import unwrap
from cdedb.ldap.tree import LDAP_TREE, Attributes, Children, LDAPTreeLeaf


class LDAPTreeNoSuchEntry(Exception):
    """The ldap tree does not contain such an object."""


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
        # TODO where do we catch the error if the dn is invalid?
        if self.dn != "":
            # this checks also if the given dn is valid for the ldap tree
            self._load()

    @staticmethod
    def _get_entry(dn: DistinguishedName) -> Tuple[Optional[Children], Optional[Attributes]]:
        """Get all infos about an entry from the ldap tree.

        This is done by traversing the ldap tree from the root to the entry described
        by the given dn.

        If no such entry is found, an `LDAPTreeNoSuchEntry` exception is raised.
        """
        # TODO maybe make this more performant by querying only those attributes which
        #  we are asked for?
        subtree = LDAP_TREE
        attributes = None
        # iterate backwards over all rdns of the dn
        for iteration, rdns in enumerate(reversed(dn.split()), start=1):
            # all rdn's in our ldap tree consist of only one attribute-value pair
            if rdns.count() != 1:
                raise LDAPTreeNoSuchEntry
            rdn = unwrap(rdns.split())
            # we reached a leaf of the ldap tree
            if isinstance(subtree, LDAPTreeLeaf):
                # the dn contains to many elements and is therefore not valid
                if iteration != len(dn.split()):
                    raise LDAPTreeNoSuchEntry
                return None, subtree.attributes(rdn)
            # this happens only if the dn is not valid for our tree
            if rdn.getText() not in subtree:
                raise LDAPTreeNoSuchEntry
            # walk down one level in the ldap tree
            attributes, subtree = subtree[rdn.getText()]
        if isinstance(subtree, dict):
            children = subtree.keys()
        elif isinstance(subtree, LDAPTreeLeaf):
            children = subtree.entities()
        else:
            raise RuntimeError("Impossible")
        return children, attributes

    def _load(self):
        _, attributes = self._get_entry(self.dn)
        if attributes is None:
            return None
        for k, v in attributes.items():
            self._attributes[k] = attributeset.LDAPAttributeSet(k, v)

    def parent(self):
        # root entry
        if self.dn == "":
            return None
        else:
            return self.__class__(self.dn.up())

    def _children(self, callback=None):
        _, children_rdns = self._get_entry(self.dn)
        if children_rdns is None:
            return None

        # TODO do we really need them to be instantiated, since this can be expensive?
        children = [self.__class__(f"{rdn},{self.dn.getText()}") for rdn in children_rdns]
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
