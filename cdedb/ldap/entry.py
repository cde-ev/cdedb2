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
    # TODO is this needed?
    ldaptor.entryhelpers.DiffTreeMixin,
    ldaptor.entryhelpers.SubtreeFromChildrenMixin,
    ldaptor.entryhelpers.MatchMixin,
    ldaptor.entryhelpers.SearchByTreeWalkingMixin,
    metaclass=abc.ABCMeta
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
    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend, attributes: LDAPObject) -> None:
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
        raise NotImplementedError

    def fetch(self, *attributes) -> Deferred:
        return succeed(self._fetch(attributes))

    # implemented in ldaptor.entryhelpers.SearchByTreeWalkingMixin
    # def search(...):

    @abc.abstractmethod
    async def _children(self, callback=None) -> Optional[List["CdEDBBaseLDAPEntry"]]:
        raise NotImplementedError

    def children(self, callback=None) -> Deferred:
        return Deferred.fromCoroutine(self._children(callback))

    # implemented by ldaptor.entryhelpers.SubtreeFromChildrenMixin
    # def subtree(self, callback=None):

    @abc.abstractmethod
    async def _lookup(self, dn_str: str) -> "CdEDBBaseLDAPEntry":
        raise NotImplementedError

    def lookup(self, dn: str) -> Deferred:
        return Deferred.fromCoroutine(self._lookup(dn))

    # implemented by ldaptor.entryhelpers.MatchMixin
    # def match(self, filter):

    def bind(self, password: Union[str, bytes]) -> Deferred:
        return fail(LDAPUnwillingToPerform("This entry does not support binding."))

    @abc.abstractmethod
    def _parent(self) -> "CdEDBBaseLDAPEntry":
        raise NotImplementedError

    def parent(self) -> Deferred:
        return succeed(self._parent())

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
    def __init__(self, dn: DistinguishedName, backend: LDAPsqlBackend) -> None:
        self.backend = backend
        attributes = self._fetch()
        super().__init__(dn, backend, attributes)


class CdEDBBindableEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    def _bind(self, password: Union[str, bytes]) -> "CdEDBBaseLDAPEntry":
        """Overwrite the default method to use the encryption algorithm used in CdEDB

        This is must be the same as used in CoreBackend.verify_password.
        """
        for key in self._user_password_keys:
            for digest in self.get(key, ()):
                if sha512_crypt.verify(password, digest):
                    return self
        raise LDAPInvalidCredentials("Invalid Credentials")

    def bind(self, password: Union[str, bytes]) -> Deferred:
        return succeed(self._bind(password))


class CdEPreLeafEntry(CdEDBStaticEntry, metaclass=abc.ABCMeta):

    ChildGroup: "CdEDBLeafEntry"

    @abc.abstractmethod
    async def children_lister(self) -> List[RelativeDistinguishedName]:
        raise NotImplementedError

    @abc.abstractmethod
    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        raise NotImplementedError

    @abc.abstractmethod
    def is_children_dn(self, dn: DistinguishedName) -> bool:
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
    def _fetch(self, *attributes) -> LDAPObject:
        if not self._attributes:
            raise RuntimeError
        return {k: self._attributes[k] for k in
                attributes} if attributes else self._attributes

    async def _children(self, callback=None) -> Optional[List["CdEDBBaseLDAPEntry"]]:
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


class DuaEntry(CdEDBLeafEntry, CdEDBBindableEntry):
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


class UserEntry(CdEDBLeafEntry, CdEDBBindableEntry):
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
