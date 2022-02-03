from typing import Any, Dict, List, Optional, Union

import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import zope.interface
from ldaptor import attributeset, entry
from ldaptor.protocols.ldap import distinguishedname
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldaperrors import (
    LDAPInvalidCredentials, LDAPNoSuchObject, LDAPUnwillingToPerform,
)
from passlib.hash import sha512_crypt
from twisted.internet import defer, error
from twisted.python import failure

from cdedb.common import unwrap
from cdedb.ldap.tree import LDAPObject, LDAPObjectMap, LDAPsqlTree


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
    """Implement a custom LDAPEntry class.

    This can be used for static ldap entries (which are hardcoded in python) and dynamic
    ldap entries (which are retrieved from a sql database).

    The layout of the ldap tree, the definition of the static entries and the retrieval
    procedures for the dynamic ldap entries are stored in `tree.py`. This class is
    mostly a wrapper, to translate our custom ldap schema so ldaptor can understand
    and serve it.

    Note that this provides just a read-only view on the ldap tree. Each attempt to
    add, delete or modify an entry will fail immediately. Those endpoints are only
    contained because the default LDAPServer of ldaptor assumes they are implemented.
    """
    def __init__(self, dn: Union[DistinguishedName, str], tree: LDAPsqlTree,
                 attributes: LDAPObject = None, *a: Any, **kw: Any) -> None:
        entry.BaseLDAPEntry.__init__(self, dn, *a, **kw)
        # this is our interface to the database
        self.tree = tree
        # root entry
        if self.dn == "":
            return
        # this also checks whether the given dn corresponds to a valid entry
        self._load(attributes=attributes)

    def _bind(self, password: Union[str, bytes]) -> "LDAPsqlEntry":
        """Overwrite the default method to use the encryption algorithm used in CdEDB

        This is must be the same as used in CoreBackend.verify_password.
        """
        for key in self._user_password_keys:
            for digest in self.get(key, ()):
                if sha512_crypt.verify(password, digest):
                    return self
        raise LDAPInvalidCredentials("Invalid Credentials")

    def _get_entities(self, dns: List[DistinguishedName]) -> Dict[DistinguishedName, Optional[LDAPObject]]:
        """Get all attributes of the given entities."""
        ret: Dict[DistinguishedName, Optional[LDAPObject]] = dict()
        # get all attributes of non-leaf ldap entries
        for dn in dns:
            if dn.getText() in self.tree.branches:
                ret[dn] = self.tree.branches[dn.getText()]
        # get all attributes of leaf ldap entries
        parents = set(dn.up() for dn in dns)
        for parent in parents:
            if parent.getText() in self.tree.leafs:
                siblings = [dn for dn in dns if dn.split()[1:] == parent.split()]
                getter = self.tree.leafs[parent.getText()]["get_entities"]
                ret.update(getter(siblings))
        # initialize all dns which are not found with None, so they don't pass the
        # validity check inside _load during initialization
        if set(dns) > set(ret):
            missing_dns = set(dns) - set(ret)
            for dn in missing_dns:
                ret[dn] = None
        return ret

    def _get_entity(self, dn: DistinguishedName) -> Optional[LDAPObject]:
        return unwrap(self._get_entities([dn]))

    def _load(self, attributes: LDAPObject = None) -> None:
        """Load own attributes.

        This accepts a set of Attributes to be used instead of fetching them from the
        database, since this reduces the number of queries when instantiating children
        entries significantly.
        """
        attributes = attributes or self._get_entity(self.dn)
        if attributes is None:
            # TODO or do nothing?
            raise failure.Failure(LDAPTreeNoSuchEntry())
        for k, v in attributes.items():
            self._attributes[k] = attributeset.LDAPAttributeSet(k, v)

    def parent(self) -> Optional["LDAPsqlEntry"]:
        # root entry
        if self.dn == "":
            return None
        else:
            return self.__class__(self.dn.up(), tree=self.tree)

    def _get_children(self, parent_dn: DistinguishedName) -> Optional[List[DistinguishedName]]:
        """Return the children of the given entry."""
        ret = list()
        # get all branch children
        for dn_str in self.tree.branches:
            dn = DistinguishedName(dn_str)
            # here, we compare if the given dn is the parent of the branch dn
            if dn.up() == parent_dn:
                ret.append(dn)
        # get all leaf children
        for dn_str in self.tree.leafs:
            dn = DistinguishedName(dn_str)
            # attention, since LDAP_LEAFS maps already the _parent_ dn to its children
            if dn == parent_dn:
                children_rdns = self.tree.leafs[dn_str]["list_entities"]()
                children_dns = [DistinguishedName(listOfRDNs=[rdn, *dn.listOfRDNs])
                                for rdn in children_rdns]
                ret.extend(children_dns)
        return ret or None

    def _children(self, callback: defer.DeferredCallback = None) -> Optional[List["LDAPsqlEntry"]]:
        dns = self._get_children(self.dn)
        if dns is None:
            return None
        attributes = self._get_entities(dns)

        children = [self.__class__(dn, attributes=attributes[dn], tree=self.tree) for dn in dns]
        if callback is None:
            return children
        else:
            for c in children:
                callback(c)
            return None

    def children(self, callback: defer.DeferredCallback = None) -> defer.Deferred:
        return defer.maybeDeferred(self._children, callback=callback)

    def hasMember(self, dn: DistinguishedName) -> bool:
        # TODO replace by 'if memberDN in self.get("uniqueMember", [])'?
        for memberDN in self.get("uniqueMember", []):
            if memberDN == dn:
                return True
        return False

    def lookup(self, dn: DistinguishedName) -> defer.Deferred:
        dn = distinguishedname.DistinguishedName(dn)
        if not self.dn.contains(dn):
            return defer.fail(LDAPNoSuchObject(dn.getText()))
        if dn == self.dn:
            return defer.succeed(self)

        # TODO make more understandable
        it = dn.split()
        me = self.dn.split()
        assert len(it) > len(me)
        assert (len(me) == 0) or (it[-len(me):] == me)
        rdn = it[-len(me) - 1]
        childDN = distinguishedname.DistinguishedName(listOfRDNs=(rdn,) + me)
        c = self.__class__(childDN, tree=self.tree)
        return c.lookup(dn)

    # TODO LDIFTreeEntry states that this returns the child instance...
    def addChild(self, rdn, attributes) -> "LDAPsqlTree":
        return defer.fail(LDAPUnwillingToPerform("Not implemented."))

    def delete(self) -> defer.Deferred:
        return defer.fail(LDAPUnwillingToPerform("Not implemented."))

    def deleteChild(self, rdn) -> defer.Deferred:
        return defer.fail(LDAPUnwillingToPerform("Not implemented."))

    # TODO where is this used?
    def __lt__(self, other) -> bool:
        if not isinstance(other, LDAPsqlEntry):
            return NotImplemented
        return self.dn < other.dn

    def __gt__(self, other) -> bool:
        if not isinstance(other, LDAPsqlEntry):
            return NotImplemented
        return self.dn > other.dn

    def commit(self) -> defer.Deferred:
        return defer.fail(LDAPUnwillingToPerform("Not implemented."))

    def move(self, newDN) -> defer.Deferred:
        return defer.fail(LDAPUnwillingToPerform("Not implemented."))
