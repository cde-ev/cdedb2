"""Classes to represent ldap entries."""

import abc
import asyncio
import logging
from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from typing import Any, Callable, Optional, Union

import ldaptor.entryhelpers
import ldaptor.ldapfilter as ldapfilter
import ldaptor.ldiftree
import ldaptor.protocols.pureldap as pureldap
from ldaptor.attributeset import LDAPAttributeSet
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName
from ldaptor.protocols.ldap.ldaperrors import (
    LDAPInvalidCredentials, LDAPNoSuchObject, LDAPProtocolError, LDAPUnwillingToPerform,
)
from twisted.python.util import InsensitiveDict

from cdedb.ldap.backend import LDAPObject, LDAPObjectMap, LDAPsqlBackend

Callback = Callable[[Any], None]
LDAPEntries = list["CdEDBBaseLDAPEntry"]
BoundDn = Optional[DistinguishedName]


logger = logging.getLogger(__name__)


class CdEDBBaseLDAPEntry(
    # use BaseLDAPEntry, since the entries are not modifiable
    # ldaptor.entry.BaseLDAPEntry,
    # ldaptor.entryhelpers.DiffTreeMixin,  # TODO is this needed?
    # ldaptor.entryhelpers.SubtreeFromChildrenMixin,
    ldaptor.entryhelpers.MatchMixin,
    # ldaptor.entryhelpers.SearchByTreeWalkingMixin,
    metaclass=abc.ABCMeta
):
    """Implement a custom LDAPEntry class for the CdEDB.

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
    accordingly.

    Currently, we support just a read-only ldap tree.
    """

    dn: DistinguishedName
    attributes: dict[bytes, LDAPAttributeSet]

    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend,
                 attributes: LDAPObject) -> None:
        """Create a new entry object.

        Note that this gets an instance of the LDAPsqlBackend and the attributes of the
        new entry. The latter is done to increase performance: Instead of 1000 separate
        database queries to get all attributes of f.e. user objects individually,
        they can be retrieved in a single query.

        Therefor, querying the attributes of an entry is done in its parent entry!
        """
        self.dn = dn

        # TODO this is no nice solution. One may thing about normalizing the attributes
        #  instead, but this is somewhat tricky.
        self.attributes = InsensitiveDict()  # type: ignore[assignment]
        for attribute, values in attributes.items():
            self.attributes[attribute] = LDAPAttributeSet(attribute, values)

        self.backend = backend

    def __getitem__(self, key: bytes) -> LDAPAttributeSet:
        return self.attributes[key]

    def get(self, key: bytes, default: Optional[LDAPAttributeSet] = None,
            ) -> LDAPAttributeSet:
        if key in self:
            return self[key]
        return default

    def __contains__(self, key: bytes) -> bool:
        return key in self.attributes

    def __iter__(self) -> Iterator[bytes]:
        return iter(self.attributes)

    def keys(self) -> KeysView[bytes]:
        return self.attributes.keys()

    def values(self) -> ValuesView[LDAPAttributeSet]:
        return self.attributes.values()

    def items(self) -> ItemsView[bytes, LDAPAttributeSet]:
        return self.attributes.items()

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, CdEDBBaseLDAPEntry):
            return NotImplemented
        if self.dn != other.dn:
            return False
        return self.attributes == other.attributes

    def __ne__(self, other: Any) -> bool:
        return not self == other

    def __len__(self) -> int:
        return len(self.attributes)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.dn.getText()})"

    @abc.abstractmethod
    def fetch(self, *attributes: bytes) -> LDAPObject:
        """Fetch the given attributes of the current entry.

        Attribute _loading_ is done before the entry is instantiated (see __init__).
        During creation, the attributes are stored in the private attributes variable.
        """
        raise NotImplementedError

    async def search(
        self,
        filterText: Optional[Any] = None,
        filterObject: Optional[Any] = None,
        # attributes: Any = (),
        scope: Optional[Any] = None,
        derefAliases: Optional[Any] = None,
        # sizeLimit: Any = 0,
        # timeLimit: Any = 0,
        # typesOnly: Any = 0,
        bound_dn: Optional[BoundDn] = None,
    ) -> list["CdEDBBaseLDAPEntry"]:
        """Asyncio analogon to ldaptor.entryhelpers.SearchByTreeWalkingMixin.

        Note that our search accepted an additional kwarg "bound_dn". This should be
        used to prevent ddos attacks: Instead of performing all database searches for
        all searches and strip the results away during determining the returns, we
        prevent the query in the first place.

        :param bound_dn: Either the DN of the user performing the search, or None if
            an anonymous search is performed.
        """
        if filterObject is None and filterText is None:
            filterObject = pureldap.LDAPFilterMatchAll
        elif filterObject is None and filterText is not None:
            filterObject = ldapfilter.parseFilter(filterText)
        elif filterObject is not None and filterText is None:
            pass
        elif filterObject is not None and filterText is not None:
            f = ldapfilter.parseFilter(filterText)
            filterObject = pureldap.LDAPFilter_and((f, filterObject))

        if scope is None:
            scope = pureldap.LDAP_SCOPE_wholeSubtree
        if derefAliases is None:
            derefAliases = pureldap.LDAP_DEREF_neverDerefAliases

        # choose iterator: base/children/subtree
        if scope == pureldap.LDAP_SCOPE_wholeSubtree:
            entries = await self.subtree(bound_dn)
        elif scope == pureldap.LDAP_SCOPE_singleLevel:
            entries = await self.children(bound_dn)
        elif scope == pureldap.LDAP_SCOPE_baseObject:
            entries = [self]
        else:
            raise LDAPProtocolError("unknown search scope: %r" % scope)

        matched = [entry for entry in entries if entry.match(filterObject)]
        return matched

    @abc.abstractmethod
    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        """List children entries of this entry.

        Note that the children are already instantiated.

        :param bound_dn: Either the DN of the user performing the request, or None if
            an anonymous search is performed, or -1 if it shall be ignored.
        """
        raise NotImplementedError

    async def subtree(self, bound_dn: Optional[BoundDn] = None,
                      ) -> list["CdEDBBaseLDAPEntry"]:
        """List the subtree rooted at this entry, including this entry."""
        result = [self]
        children = await self.children(bound_dn=bound_dn)
        subtrees = await asyncio.gather(
            *[child.subtree(bound_dn=bound_dn) for child in children])
        for tree in subtrees:
            result.extend(tree)
        return result

    @abc.abstractmethod
    async def lookup(self, dn: DistinguishedName) -> "CdEDBBaseLDAPEntry":
        """Lookup the given DN.

        This is used to find a specific entry in the ldap tree:
        Each entry has to decide if the given DN ...
        - ... is itself (then return itself).
        - ... lays underneath it (then decide under which children and call its lookup).
        - ... is not inside its part of the tree (then return an error).
        """
        raise NotImplementedError

    # implemented by ldaptor.entryhelpers.MatchMixin
    # def match(self, filter):

    def bind(self, password: Union[str, bytes]) -> "CdEDBBaseLDAPEntry":  # pylint: disable=no-self-use
        """Bind with this entry and the given password.

        In general, this is forbidden for all entries. Exceptions from this rule
        may implement the CdEDBBindableEntryMixing.
        """
        raise LDAPUnwillingToPerform("This entry does not support binding.")

    @abc.abstractmethod
    def parent(self) -> Optional["CdEDBBaseLDAPEntry"]:
        """Return the parent entry of this entry.

        Only the root entry may return None instead.
        """
        raise NotImplementedError


class CdEDBStaticEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Base class for all static ldap entries."""

    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend) -> None:
        """Initialize a new entry.

        Static ldap entries should store their attributes inside the _fetch method.
        Therefore, this wraps the creation and inserts the attributes accordingly.
        """
        self.backend = backend
        attributes = self.fetch()
        super().__init__(dn, backend, attributes)


class CdEDBBindableEntryMixing(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Mixin to allow binding with an entry."""

    def bind(self, password: Union[str, bytes]) -> CdEDBBaseLDAPEntry:
        """Overwrite the default method to use the encryption algorithm used in CdEDB

        This must be the same as used in CoreBackend.verify_password. Note that the
        entry must have one of the password attributes specified in _user_password_keys.
        """
        if isinstance(password, bytes):
            password = password.decode("utf-8")
        if b"userPassword" in self:
            for digest in self[b"userPassword"]:
                if self.backend.verify_password(password, digest):
                    return self
        raise LDAPInvalidCredentials("Invalid Credentials")


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
    ChildGroup: type["CdEDBLeafEntry"]

    @abc.abstractmethod
    async def children_lister(
            self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        """List all children of this entry.

        The real work is done in the backend, this is only used to link the correct
        function in place.

        :param bound_dn: Either the DN of the user performing the search, or None if
            an anonymous search is performed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
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

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        dns = await self.children_lister(bound_dn=bound_dn)
        children = await self.children_getter(dns)
        ret = [self.ChildGroup(dn, backend=self.backend, attributes=attributes) for
               dn, attributes in children.items()]
        return ret

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif self.is_children_dn(dn):
            child_attributes = await self.children_getter([dn])
            if not child_attributes:
                raise LDAPNoSuchObject(dn.getText())
            [attributes] = child_attributes.values()
            child = self.ChildGroup(dn, backend=self.backend,
                                    attributes=attributes)
            return await child.lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())


class CdEDBLeafEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Base class for all dynamic entries.

    Since all dynamic entries do not have any children, they are leafs of the ldap tree.
    Note however that the opposite is not true.
    """

    def fetch(self, *attributes: bytes) -> LDAPObject:
        """Use the attributes attribute to return the requested attributes."""
        if not self.attributes:
            raise RuntimeError
        return {k: self[k] for k in attributes} if attributes else self.attributes

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        """All dynamic entries do not have any children by design."""
        return []

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn.getText())


class RootEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.root_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs: dict[bytes, list[bytes]] = self.backend._to_bytes({  # pylint: disable=protected-access
            b"supportedLDAPVersion": [b"3"],
            # TODO right? Or is this rather dc=cde-ev,dc=de?
            b"namingContexts": [self.backend.root_dn],
            b"subschemaSubentry": [self.backend.subschema_dn],
        })
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        de = DeEntry(self.backend)
        subschema = SubschemaEntry(self.backend)
        return [de, subschema]

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            self.fetch()
            return self
        elif self.backend.de_dn.contains(dn):
            de = DeEntry(self.backend)
            return await de.lookup(dn)
        elif self.backend.subschema_dn.contains(dn):
            subschema = SubschemaEntry(self.backend)
            return await subschema.lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def parent(self) -> Optional["CdEDBBaseLDAPEntry"]:
        return None


class SubschemaEntry(CdEDBStaticEntry):
    """Provide some information about the ldap specifications.

    Note that this is a static leaf entry!
    """

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.subschema_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"top", b"subschema"],
            b"attributeTypes": self.backend.schema.attribute_types,
            b"objectClasses": self.backend.schema.object_classes,
            # TODO find out which syntaxes and matching rules we support
            b"ldapSyntaxes": self.backend.schema.syntaxes,
            b"matchingRules": self.backend.schema.matching_rules,
            b"matchingRuleUse": [],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs  # type: ignore[misc, return-value]

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        return []

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn.getText())

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class DeEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.de_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"top"],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        cde = CdeEvEntry(self.backend)
        return [cde]

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif self.backend.cde_dn.contains(dn):
            cde = CdeEvEntry(self.backend)
            return await cde.lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class CdeEvEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.cde_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"organization"],
            b"o": [b"CdE e.V."],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        duas = DuasEntry(self.backend)
        users = UsersEntry(self.backend)
        groups = GroupsEntry(self.backend)
        return [duas, users, groups]

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif self.backend.duas_dn.contains(dn):
            duas = DuasEntry(self.backend)
            return await duas.lookup(dn)
        elif self.backend.users_dn.contains(dn):
            users = UsersEntry(self.backend)
            return await users.lookup(dn)
        elif self.backend.groups_dn.contains(dn):
            groups = GroupsEntry(self.backend)
            return await groups.lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return DeEntry(self.backend)


class DuaEntry(CdEDBLeafEntry, CdEDBBindableEntryMixing):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return DuasEntry(self.backend)


class DuasEntry(CdEPreLeafEntry):
    ChildGroup = DuaEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.duas_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Directory User Agents"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access duas
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_duas()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_duas(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_dua_dn(dn)


class UserEntry(CdEDBLeafEntry, CdEDBBindableEntryMixing):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return UsersEntry(self.backend)


class UsersEntry(CdEPreLeafEntry):
    ChildGroup = UserEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.users_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Users"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests may access no user
        if bound_dn is None:
            return []
        # Users may access only their own data
        elif self.backend.is_user_dn(bound_dn):
            user_id = self.backend.user_id(bound_dn)
            assert user_id is not None
            return [self.backend.list_single_user(user_id)]
        return await self.backend.list_users()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_users(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_user_dn(dn)


class GroupsEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Groups"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def children(self, bound_dn: Optional[BoundDn] = None) -> LDAPEntries:
        status = StatusGroupsEntry(self.backend)
        presiders = PresiderGroupsEntry(self.backend)
        orgas = OrgaGroupsEntry(self.backend)
        moderators = ModeratorGroupsEntry(self.backend)
        subscribers = SubscriberGroupsEntry(self.backend)
        return [status, presiders, orgas, moderators, subscribers]

    async def lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif self.backend.status_groups_dn.contains(dn):
            status = StatusGroupsEntry(self.backend)
            return await status.lookup(dn)
        elif self.backend.presider_groups_dn.contains(dn):
            presiders = PresiderGroupsEntry(self.backend)
            return await presiders.lookup(dn)
        elif self.backend.orga_groups_dn.contains(dn):
            orgas = OrgaGroupsEntry(self.backend)
            return await orgas.lookup(dn)
        elif self.backend.moderator_groups_dn.contains(dn):
            moderators = ModeratorGroupsEntry(self.backend)
            return await moderators.lookup(dn)
        elif self.backend.subscriber_groups_dn.contains(dn):
            subscribers = SubscriberGroupsEntry(self.backend)
            return await subscribers.lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)


class StatusGroupEntry(CdEDBLeafEntry):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return StatusGroupsEntry(self.backend)


class StatusGroupsEntry(CdEPreLeafEntry):
    ChildGroup = StatusGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.status_groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Status"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access groups
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_status_groups()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_status_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_status_group_dn(dn)


class PresiderGroupEntry(CdEDBLeafEntry):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return PresiderGroupsEntry(self.backend)


class PresiderGroupsEntry(CdEPreLeafEntry):
    ChildGroup = PresiderGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.presider_groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Assembly Presiders"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access groups
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_assembly_presider_groups()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_assembly_presider_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_presider_group_dn(dn)


class OrgaGroupEntry(CdEDBLeafEntry):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return OrgaGroupsEntry(self.backend)


class OrgaGroupsEntry(CdEPreLeafEntry):
    ChildGroup = OrgaGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.orga_groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Event Orgas"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access groups
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_event_orga_groups()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_event_orga_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_orga_group_dn(dn)


class ModeratorGroupEntry(CdEDBLeafEntry):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return ModeratorGroupsEntry(self.backend)


class ModeratorGroupsEntry(CdEPreLeafEntry):
    ChildGroup = ModeratorGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.moderator_groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Moderators"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access groups
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_ml_moderator_groups()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_ml_moderator_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_moderator_group_dn(dn)


class SubscriberGroupEntry(CdEDBLeafEntry):
    def parent(self) -> "CdEDBBaseLDAPEntry":
        return SubscriberGroupsEntry(self.backend)


class SubscriberGroupsEntry(CdEPreLeafEntry):
    ChildGroup = SubscriberGroupEntry

    def __init__(self, backend: LDAPsqlBackend) -> None:
        super().__init__(backend.subscriber_groups_dn, backend)

    def fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Subscribers"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(
        self, bound_dn: Optional[BoundDn] = None
    ) -> list[DistinguishedName]:
        # Anonymous requests or personas may not access groups
        if bound_dn is None or self.backend.is_user_dn(bound_dn):
            return []
        return await self.backend.list_ml_subscriber_groups()

    async def children_getter(self, dns: list[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_ml_subscriber_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_subscriber_group_dn(dn)
