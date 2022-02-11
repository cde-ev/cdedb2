import abc
from typing import List, Optional, Union

import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import ldaptor.ldiftree
import zope.interface
from ldaptor import entry
from ldaptor.protocols.ldap import distinguishedname
from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName, RelativeDistinguishedName,
)
from ldaptor.protocols.ldap.ldaperrors import (
    LDAPInvalidCredentials, LDAPNoSuchObject, LDAPUnwillingToPerform,
)
from passlib.hash import sha512_crypt
from twisted.internet.defer import Deferred, fail, succeed

from cdedb.common import unwrap
from cdedb.ldap.backend import LDAPObject, LDAPObjectMap, LDAPsqlBackend


class LDAPTreeNoSuchEntry(Exception):
    """The ldap tree does not contain such an object."""


@zope.interface.implementer(ldaptor.interfaces.IConnectedLDAPEntry)
class CdEDBBaseLDAPEntry(
    # use BaseLDAPEntry, since the entries are not modifiable
    ldaptor.entry.BaseLDAPEntry,
    ldaptor.entryhelpers.DiffTreeMixin,  # TODO is this needed?
    ldaptor.entryhelpers.SubtreeFromChildrenMixin,
    ldaptor.entryhelpers.MatchMixin,
    ldaptor.entryhelpers.SearchByTreeWalkingMixin,
    metaclass=abc.ABCMeta
):
    """Implement a custom LDAPEntry class for the CdEDB.

    This provides the interface between the LDAPsqlBackend and ldaptor by implementing
    the IConnectedLDAPEntry interface of ldaptor.

    In general, we have two different kinds of entries in our LDAP:
    - Static entries which do not depend on the postgres database.
    - Dynamic entries which are retrieved from the postgres database.

    Both kind of entries look and behave identically from an ldap (and even ldaptor)
    point of view. On the other hand, the LDAPsqlBackend has very limited structural
    knowledge about the ldap tree (there are just individual functions listing and
    retrieving the dynamic entries from postgres).

    So, this is the place where the ldap tree get its form by determining ...
    - ... the attributes of static entries.
    - ... static children of static entries.
    - ... which backend function retrieves the attributes of a dynamic entry.
    - ... which backend function retrieves the dynamic children of a static entry.

    This is done by subclassing this base class and overwriting the abstract methods
    accordingly. The abstract methods are asyncio directives, the conversion to twisteds
    Deferred is already done in this class.

    Currently, we support just a read-only ldap tree. Therefore, all methods specified
    by ldaptor's interface to add, modify or delete an entry are overwritten to error
    out immediatly. They may not be overwritten in the child classes.
    """

    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend, attributes: LDAPObject) -> None:
        """Create a new entry object.

        Note that this gets an instance of the LDAPsqlBackend and the attributes of the
        new entry. The latter is done to increase performance: Instead of 1000 separate
        database queries to get all attributes of f.e. user objects individually,
        they can be retrieved in a single query.

        Therefor, querying the attributes of an entry is done in its parent entry!
        """
        self.backend = backend
        if not attributes:
            raise RuntimeError
        # initialize the entry
        entry.BaseLDAPEntry.__init__(self, dn, attributes=attributes)

    # TODO this is specified in the interface, but what is this?
    # def namingContext(self):
    #     raise NotImplementedError

    @abc.abstractmethod
    def _fetch(self, *attributes) -> LDAPObject:
        """Fetch the given attributes of the current entry.

        Attribute _loading_ is done before the entry is instantiated (see __init__).
        During creation, the attributes are stored in the private _attributes variable.
        """
        raise NotImplementedError

    def fetch(self, *attributes) -> Deferred:
        return succeed(self._fetch(attributes))

    # implemented in ldaptor.entryhelpers.SearchByTreeWalkingMixin
    # def search(...):

    @abc.abstractmethod
    async def _children(self, callback=None) -> Optional[List["CdEDBBaseLDAPEntry"]]:
        """List children entries of this entry.

        Note that the children are already instantiated.
        """
        raise NotImplementedError

    def children(self, callback=None) -> Deferred:
        return Deferred.fromCoroutine(self._children(callback))

    # implemented by ldaptor.entryhelpers.SubtreeFromChildrenMixin
    # def subtree(self, callback=None):

    @abc.abstractmethod
    async def _lookup(self, dn_str: str) -> "CdEDBBaseLDAPEntry":
        """Lookup the given DN.

        This is used to find a specific entry in the ldap tree:
        Each entry has to decide if the given DN ...
        - ... is itself (then return itself).
        - ... lays underneath it (then decide under which children and call its lookup).
        - ... is not inside its part of the tree (then return an error).
        """
        raise NotImplementedError

    def lookup(self, dn: str) -> Deferred:
        return Deferred.fromCoroutine(self._lookup(dn))

    # implemented by ldaptor.entryhelpers.MatchMixin
    # def match(self, filter):

    def bind(self, password: Union[str, bytes]) -> Deferred:
        """Bind with this entry and the given password.

        In general, this is forbidden for all entries. Exceptions from this rule
        may implement the CdEDBBindableEntryMixing.
        """
        return fail(LDAPUnwillingToPerform("This entry does not support binding."))

    @abc.abstractmethod
    def _parent(self) -> Optional["CdEDBBaseLDAPEntry"]:
        """Return the parent entry of this entry.

        Only the root entry may return None instead.
        """
        raise NotImplementedError

    def parent(self) -> Deferred:
        return succeed(self._parent())

    # TODO where is this used?
    def hasMember(self, dn: DistinguishedName) -> bool:
        # TODO replace by 'if memberDN in self.get("uniqueMember", [])'?
        for memberDN in self.get("uniqueMember", []):
            if memberDN == dn:
                return True
        return False

    def addChild(self, rdn, attributes) -> Deferred:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def delete(self) -> Deferred:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def deleteChild(self, rdn) -> Deferred:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    # TODO where is this used?
    def __lt__(self, other) -> bool:
        if not isinstance(other, CdEDBBaseLDAPEntry):
            return NotImplemented
        return self.dn < other.dn

    def __gt__(self, other) -> bool:
        if not isinstance(other, CdEDBBaseLDAPEntry):
            return NotImplemented
        return self.dn > other.dn

    def commit(self) -> Deferred:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def move(self, newDN) -> Deferred:
        return fail(LDAPUnwillingToPerform("Not implemented."))


class CdEDBStaticEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Base class for all static ldap entries."""

    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend) -> None:
        """Initialize a new entry.

        Static ldap entries should store their attributes inside the _fetch method.
        Therefore, this wraps the creation and inserts the attributes accordingly.
        """
        self.backend = backend
        attributes = self._fetch()
        super().__init__(dn, backend, attributes)


class CdEDBBindableEntryMixing(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Mixin to allow binding with an entry."""

    def _bind(self, password: Union[str, bytes]) -> CdEDBBaseLDAPEntry:
        """Overwrite the default method to use the encryption algorithm used in CdEDB

        This must be the same as used in CoreBackend.verify_password. Note that the
        entry must have one of the password attributes specified in _user_password_keys.
        """
        for key in self._user_password_keys:
            for digest in self.get(key, ()):
                if sha512_crypt.verify(password, digest):
                    return self
        raise LDAPInvalidCredentials("Invalid Credentials")

    def bind(self, password: Union[str, bytes]) -> Deferred:
        return succeed(self._bind(password))


class CdEPreLeafEntry(CdEDBStaticEntry, metaclass=abc.ABCMeta):
    """Base class for all entries which have dynamic _children_.

    Since dynamic entries do not have any children by design, dynamic entries are leafs
    of the ldap tree. Therefore, entries with dynamic children are pre-leaf entries.

    Loading attributes of dynamic entries is done in their parent entry for reasons of
    performance. This class implements the (always equal) procedure of instantiating
    the children and performing lookup of dns. The subclass does only need to specify
    the (backend) function which should be used to list the children and retrieve
    their attributes.
    """

    # class which is used to instantiate the children
    ChildGroup: "CdEDBLeafEntry"

    @abc.abstractmethod
    async def children_lister(self) -> List[RelativeDistinguishedName]:
        """List all children of this entry.

        The real work is done in the backend, this is only used to link the correct
        function in place.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        """Get the attributes of those DNs which are children of this entry.

        The real work is done in the backend, this is only used to link the correct
        function in place.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def is_children_dn(self, dn: DistinguishedName) -> bool:
        """Decide whether a DN is a child of this entry or not.

        The real work is done in the backend, this is only used to link the correct
        function in place.
        """
        raise NotImplementedError

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        child_list = await self.children_lister()
        dns = [DistinguishedName(f"{child.getText()},{self.dn.getText()}") for child in
               child_list]
        children = await self.children_getter(dns)
        ret = [self.ChildGroup(dn, backend=self.backend, attributes=attributes) for
               dn, attributes in children.items()]

        if callback:
            for child in ret:
                callback(child)
            return None
        else:
            return ret

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        elif self.is_children_dn(dn):
            child_attributes = await self.children_getter([dn])
            if not child_attributes:
                raise LDAPNoSuchObject(dn_str)
            child = self.ChildGroup(dn, backend=self.backend, attributes=unwrap(child_attributes))
            return await child._lookup(dn_str)
        else:
            raise LDAPNoSuchObject(dn_str)


class CdEDBLeafEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Base class for all dynamic entries.

    Since all dynamic entries do not have any children, they are leafs of the ldap tree.
    Note however that the opposite is not true.
    """

    def _fetch(self, *attributes) -> LDAPObject:
        """Use the _attributes attribute to return the requested attributes."""
        if not self._attributes:
            raise RuntimeError
        return {k: self._attributes[k] for k in
                attributes} if attributes else self._attributes

    async def _children(self, callback=None) -> Optional[List["CdEDBBaseLDAPEntry"]]:
        """All dynamic entries do not have any children by design."""
        return None

    async def _lookup(self, dn_str: str) -> "CdEDBBaseLDAPEntry":
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn_str)


class RootEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.root_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"supportedLDAPVersion": [b"3"],
            # TODO right? Or is this rather dc=cde-ev,dc=de?
            b"namingContexts": [self.backend._to_bytes(self.backend.root_dn)],
            b"subschemaSubentry": [self.backend._to_bytes(self.backend.subschema_dn)],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        de = DeEntry(self.backend)
        subschema = SubschemaEntry(self.backend)
        if callback:
            callback(de)
            callback(subschema)
            return None
        else:
            return [de, subschema]

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            self._fetch()
            return self
        elif DistinguishedName(self.backend.de_dn).contains(dn):
            de = DeEntry(self.backend)
            return await de._lookup(dn_str)
        elif DistinguishedName(self.backend.subschema_dn).contains(dn):
            subschema = SubschemaEntry(self.backend)
            return await subschema._lookup(dn_str)
        else:
            raise LDAPNoSuchObject(dn_str)

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return None


class SubschemaEntry(CdEDBStaticEntry):
    """Provide some information about the ldap specifications.

    Note that this is a static leaf entry!
    """

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.subschema_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"top", b"subschema"],
            b"attributeTypes": self.backend.schema.attribute_types,
            b"objectClasses": self.backend.schema.object_classes,
            # TODO find out which syntaxes and matching rules we support
            b"ldapSyntaxes": self.backend.schema.syntaxes,
            b"matchingRules": self.backend.schema.matching_rules,
            b"matchingRuleUse": [],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        return None

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn_str)

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class DeEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.de_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"top"],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        cde = CdeEvEntry(self.backend)
        if callback:
            callback(cde)
            return None
        else:
            return [cde]

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.cde_dn).contains(dn):
            cde = CdeEvEntry(self.backend)
            return await cde._lookup(dn_str)
        else:
            raise LDAPNoSuchObject(dn_str)

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class CdeEvEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.cde_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"organization"],
            b"o": [b"CdE e.V."],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        duas = DuasEntry(self.backend)
        users = UsersEntry(self.backend)
        groups = GroupsEntry(self.backend)

        if callback:
            callback(duas)
            callback(users)
            callback(groups)
            return None
        else:
            return [duas, users, groups]

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.duas_dn).contains(dn):
            duas = DuasEntry(self.backend)
            return await duas._lookup(dn_str)
        elif DistinguishedName(self.backend.users_dn).contains(dn):
            users = UsersEntry(self.backend)
            return await users.lookup(dn_str)
        elif DistinguishedName(self.backend.groups_dn).contains(dn):
            groups = GroupsEntry(self.backend)
            return await groups.lookup(dn_str)
        else:
            raise LDAPNoSuchObject(dn_str)

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return DeEntry(self.backend)


class DuaEntry(CdEDBLeafEntry, CdEDBBindableEntryMixing):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return DuasEntry(self.backend)


class DuasEntry(CdEPreLeafEntry):
    ChildGroup = DuaEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.duas_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Directory User Agents"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_duas()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_duas(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_dua_dn(dn)


class UserEntry(CdEDBLeafEntry, CdEDBBindableEntryMixing):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return UsersEntry(self.backend)


class UsersEntry(CdEPreLeafEntry):
    ChildGroup = UserEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.users_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Users"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_users()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_users(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_user_dn(dn)


class GroupsEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Groups"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback=None) -> Optional[List[CdEDBBaseLDAPEntry]]:
        status = StatusGroupsEntry(self.backend)
        presiders = PresiderGroupsEntry(self.backend)
        orgas = OrgaGroupsEntry(self.backend)
        moderators = ModeratorGroupsEntry(self.backend)
        subscribers = SubscriberGroupsEntry(self.backend)

        if callback:
            callback(status)
            callback(presiders)
            callback(orgas)
            callback(moderators)
            callback(subscribers)
            return None
        else:
            return [status, presiders, orgas, moderators, subscribers]

    async def _lookup(self, dn_str: str) -> CdEDBBaseLDAPEntry:
        dn = distinguishedname.DistinguishedName(dn_str)
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.status_groups_dn).contains(dn):
            status = StatusGroupsEntry(self.backend)
            return await status._lookup(dn_str)
        elif DistinguishedName(self.backend.presider_groups_dn).contains(dn):
            presiders = PresiderGroupsEntry(self.backend)
            return await presiders.lookup(dn_str)
        elif DistinguishedName(self.backend.orga_groups_dn).contains(dn):
            orgas = OrgaGroupsEntry(self.backend)
            return await orgas.lookup(dn_str)
        elif DistinguishedName(self.backend.moderator_groups_dn).contains(dn):
            moderators = ModeratorGroupsEntry(self.backend)
            return await moderators.lookup(dn_str)
        elif DistinguishedName(self.backend.subscriber_groups_dn).contains(dn):
            subscribers = SubscriberGroupsEntry(self.backend)
            return await subscribers.lookup(dn_str)
        else:
            raise LDAPNoSuchObject(dn_str)

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)


class StatusGroupEntry(CdEDBLeafEntry):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return StatusGroupsEntry(self.backend)


class StatusGroupsEntry(CdEPreLeafEntry):
    ChildGroup = StatusGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.status_groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Status"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_status_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_status_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_status_group_dn(dn)


class PresiderGroupEntry(CdEDBLeafEntry):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return PresiderGroupsEntry(self.backend)


class PresiderGroupsEntry(CdEPreLeafEntry):
    ChildGroup = PresiderGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.presider_groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Assembly Presiders"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_assembly_presider_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_assembly_presider_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_presider_group_dn(dn)


class OrgaGroupEntry(CdEDBLeafEntry):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return OrgaGroupsEntry(self.backend)


class OrgaGroupsEntry(CdEPreLeafEntry):
    ChildGroup = OrgaGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.orga_groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Event Orgas"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_event_orga_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_event_orga_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_orga_group_dn(dn)


class ModeratorGroupEntry(CdEDBLeafEntry):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return ModeratorGroupsEntry(self.backend)


class ModeratorGroupsEntry(CdEPreLeafEntry):
    ChildGroup = ModeratorGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.moderator_groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Moderators"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_ml_moderator_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_ml_moderator_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_moderator_group_dn(dn)


class SubscriberGroupEntry(CdEDBLeafEntry):
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return SubscriberGroupsEntry(self.backend)


class SubscriberGroupsEntry(CdEPreLeafEntry):
    ChildGroup = SubscriberGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.subscriber_groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Subscribers"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self) -> List[RelativeDistinguishedName]:
        return await self.backend.list_ml_subscriber_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_ml_subscriber_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_subscriber_group_dn(dn)
