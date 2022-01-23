from typing import Dict, List, Optional, Tuple, Union

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
from cdedb.ldap.tree import LDAP_BRANCHES, LDAP_LEAFS, Attributes


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
    def __init__(self, dn: Union[DistinguishedName, str], attributes: Attributes = None, *a, **kw):
        entry.BaseLDAPEntry.__init__(self, dn, *a, **kw)
        # root entry
        if self.dn == "":
            return
        # TODO where do we catch the error if the dn is invalid?
        self._load(attributes=attributes)

    @staticmethod
    def _get_entities(dns: List[DistinguishedName]) -> Dict[DistinguishedName, Optional[Attributes]]:
        """Get all attributes of the given entities."""
        ret = dict()
        # get all attributes of non-leaf ldap entries
        for dn in dns:
            if dn.getText() in LDAP_BRANCHES:
                ret[dn] = LDAP_BRANCHES[dn.getText()]
        # get all attributes of leaf ldap entries
        parents = set(dn.up() for dn in dns)
        for parent in parents:
            if parent.getText() in LDAP_LEAFS:
                siblings = [dn for dn in dns if dn.split()[1:] == parent.split()]
                getter = LDAP_LEAFS[parent.getText()]["get_entities"]
                ret.update(getter(siblings))
        # TODO what should we do if some entries are not found?
        if set(dns) > set(ret):
            missing_dns = set(dns) - set(ret)
            for dn in missing_dns:
                ret[dn] = None
        return ret

    def _get_entity(self, dn: DistinguishedName) -> Optional[Attributes]:
        return unwrap(self._get_entities([dn]))

    def _load(self, attributes: Attributes = None):
        """Load own attributes.

        This accepts a set of Attributes to be used instead of fetching them from the
        database, since this reduces the number of queries when instantiating children
        entries significantly.
        """
        attributes = attributes or self._get_entity(self.dn)
        if attributes is None:
            raise LDAPTreeNoSuchEntry
        for k, v in attributes.items():
            self._attributes[k] = attributeset.LDAPAttributeSet(k, v)

    def parent(self):
        # root entry
        if self.dn == "":
            return None
        else:
            return self.__class__(self.dn.up())

    @staticmethod
    def _get_children(parent_dn: DistinguishedName) -> Optional[List[DistinguishedName]]:
        """Return the children of the given entry."""
        ret = list()
        # get all branch children
        for dn_str in LDAP_BRANCHES:
            dn = DistinguishedName(dn_str)
            # here, we compare if the given dn is the parent of the branch dn
            if dn.up() == parent_dn:
                ret.append(dn)
        # get all leaf children
        for dn_str in LDAP_LEAFS:
            dn = DistinguishedName(dn_str)
            # attention, since LDAP_LEAFS maps already the _parent_ dn to its children
            if dn == parent_dn:
                children_rdns = LDAP_LEAFS[dn_str]["list_entities"]()
                children_dns = [DistinguishedName(listOfRDNs=[rdn, *dn.listOfRDNs])
                                for rdn in children_rdns]
                ret.extend(children_dns)
        return ret or None

    def _children(self, callback=None):
        dns = self._get_children(self.dn)
        if dns is None:
            return None
        attributes = self._get_entities(dns)

        children = [self.__class__(dn, attributes=attributes[dn]) for dn in dns]
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
