import abc
import asyncio
import logging
from asyncio import ensure_future
from typing import Any, Callable, List, Optional, Sequence, Type, Union

import ldaptor.entry
import ldaptor.entryhelpers
import ldaptor.interfaces
import ldaptor.ldapfilter as ldapfilter
import ldaptor.ldiftree
import ldaptor.protocols.pureldap as pureldap
import zope.interface
from ldaptor import entry
from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName, RelativeDistinguishedName,
)
from ldaptor.protocols.ldap.ldaperrors import (
    LDAPException, LDAPInvalidCredentials, LDAPNoSuchObject, LDAPProtocolError,
    LDAPUnwillingToPerform,
)
from twisted.internet.defer import Deferred, fail, succeed
from twisted.python import log

from cdedb.common import unwrap
from cdedb.ldap.backend import LDAPObject, LDAPObjectMap, LDAPsqlBackend

Callback = Callable
LDAPEntries = List["CdEDBBaseLDAPEntry"]
BoundDn = Optional[Union[int, DistinguishedName]]


# TODO where is the right place to catch (this) error if raised in an async function?
class LDAPTreeNoSuchEntry(LDAPException):
    """The ldap tree does not contain such an object."""


logger = logging.getLogger(__name__)


@zope.interface.implementer(ldaptor.interfaces.IConnectedLDAPEntry)
class CdEDBBaseLDAPEntry(
    # use BaseLDAPEntry, since the entries are not modifiable
    ldaptor.entry.BaseLDAPEntry,
    ldaptor.entryhelpers.DiffTreeMixin,  # TODO is this needed?
    # ldaptor.entryhelpers.SubtreeFromChildrenMixin,
    ldaptor.entryhelpers.MatchMixin,
    # ldaptor.entryhelpers.SearchByTreeWalkingMixin,
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
    def _fetch(self, *attributes: bytes) -> LDAPObject:
        """Fetch the given attributes of the current entry.

        Attribute _loading_ is done before the entry is instantiated (see __init__).
        During creation, the attributes are stored in the private _attributes variable.
        """
        raise NotImplementedError

    def fetch(self, *attributes: bytes) -> Deferred[LDAPObject]:
        d = succeed(self._fetch(*attributes))
        d.addErrback(log.err)
        return d

    def search(
        self,
        filterText=None,
        filterObject=None,
        attributes=(),
        scope=None,
        derefAliases=None,
        sizeLimit=0,
        timeLimit=0,
        typesOnly=0,
        callback=None,
        bound_dn: BoundDn = -1,
    ):
        """Slightly modified version of ldaptor.entryhelpers.SearchByTreeWalkingMixin

        The original function does not respect the correct execution order in
        combination with the async _children function: It sends the 'SearchResultDone'
        message before we have time to send the search results.

        This function made the assumption that the given callback is never None (in
        contrast to the original function) – until now, this seems a valid assumption.

        Note that our search accepted an additional kwarg "bound_dn". This should be
        used to prevent ddos attacks: Instead of performing all database searches for
        all searches and strip the results away during determining the returns, we
        prevent the query in the first place.
        Note that this is a derivation from the interface description, so this parameter
        has a default value -1 signaling it should be ignored (since bound_dn can be
        None for anonymous access).

        :param bound_dn: Either the DN of the user performing the search, or None if
            an anonymous search is performed, or -1 if it shall be ignored.
        """
        if callback is None:
            logger.error("No 'callback' in Search provided!")

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
            # in the special case of subtree search, the base object shall be included
            if self.match(filterObject):
                callback(self)
            iterator = self._subtree
        elif scope == pureldap.LDAP_SCOPE_singleLevel:
            iterator = self._children
        elif scope == pureldap.LDAP_SCOPE_baseObject:

            async def iterate_self(callback, bound_dn: BoundDn = -1):
                callback(self)
                return None

            iterator = iterate_self
        else:
            raise LDAPProtocolError("unknown search scope: %r" % scope)

        # gather results, send them
        def _tryMatch(entry):
            if entry.match(filterObject):
                callback(entry)

        return Deferred.fromFuture(
            ensure_future(iterator(_tryMatch, bound_dn=bound_dn)))

    @abc.abstractmethod
    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        """List children entries of this entry.

        Note that the children are already instantiated.

        :param bound_dn: Either the DN of the user performing the request, or None if
            an anonymous search is performed, or -1 if it shall be ignored.
        """
        raise NotImplementedError

    def children(self, callback: Callback = None) -> Deferred[Optional[LDAPEntries]]:
        d = Deferred.fromFuture(ensure_future(self._children(callback)))
        d.addErrback(log.err)
        return d

    async def _subtree(self, callback, bound_dn: BoundDn = -1) -> None:
        """Apply a callback function to every entry of the current ones subtree.

        This is especially needed in subtree searches.

        :param bound_dn: Either the DN of the user performing the search, or None if
            an anonymous search is performed, or -1 if it shall be ignored.
        """
        if callback is None:
            logger.error("No 'callback' in Subtree provided!")
        children = await self._children(callback, bound_dn=bound_dn)
        if children:
            for child in children:
                await child._subtree(callback, bound_dn=bound_dn)
        return None

    def subtree(self, callback=None):
        d = Deferred.fromFuture(ensure_future(self._subtree(callback)))
        d.addErrback(log.err)
        return d

    @abc.abstractmethod
    async def _lookup(self, dn: DistinguishedName) -> "CdEDBBaseLDAPEntry":
        """Lookup the given DN.

        This is used to find a specific entry in the ldap tree:
        Each entry has to decide if the given DN ...
        - ... is itself (then return itself).
        - ... lays underneath it (then decide under which children and call its lookup).
        - ... is not inside its part of the tree (then return an error).
        """
        raise NotImplementedError

    def lookup(self, dn: DistinguishedName) -> Deferred["CdEDBBaseLDAPEntry"]:
        d = Deferred.fromFuture(ensure_future(self._lookup(dn)))
        d.addErrback(log.err)
        return d

    # implemented by ldaptor.entryhelpers.MatchMixin
    # def match(self, filter):

    def bind(self, password: Union[str, bytes]) -> Deferred["CdEDBBaseLDAPEntry"]:
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

    def parent(self) -> Deferred[Optional["CdEDBBaseLDAPEntry"]]:
        d = succeed(self._parent())
        d.addErrback(log.err)
        return d

    # TODO where is this used?
    def hasMember(self, dn: DistinguishedName) -> bool:
        # TODO replace by 'if memberDN in self.get("uniqueMember", [])'?
        for memberDN in self.get("uniqueMember", []):
            if memberDN == dn:
                return True
        return False

    def addChild(self, rdn: RelativeDistinguishedName, attributes: Sequence[bytes]
                 ) -> Deferred[LDAPUnwillingToPerform]:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def delete(self) -> Deferred[LDAPUnwillingToPerform]:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def deleteChild(self, rdn: RelativeDistinguishedName
                    ) -> Deferred[LDAPUnwillingToPerform]:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    # TODO where is this used?
    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, CdEDBBaseLDAPEntry):
            return NotImplemented
        return self.dn < other.dn

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, CdEDBBaseLDAPEntry):
            return NotImplemented
        return self.dn > other.dn

    def commit(self) -> Deferred[LDAPUnwillingToPerform]:
        return fail(LDAPUnwillingToPerform("Not implemented."))

    def move(self, newDN: DistinguishedName) -> Deferred[LDAPUnwillingToPerform]:
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
        if isinstance(password, bytes):
            password = password.decode("utf-8")
        for key in self._user_password_keys:
            for digest in self.get(key, ()):
                if self.backend.verify_password(password, digest):
                    return self
        raise LDAPInvalidCredentials("Invalid Credentials")

    def bind(self, password: Union[str, bytes]) -> Deferred[CdEDBBaseLDAPEntry]:
        d = succeed(self._bind(password))
        d.addErrback(log.err)
        return d


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
    ChildGroup: Type["CdEDBLeafEntry"]

    @abc.abstractmethod
    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        """List all children of this entry.

        The real work is done in the backend, this is only used to link the correct
        function in place.

        :param bound_dn: Either the DN of the user performing the search, or None if
            an anonymous search is performed, or -1 if it shall be ignored.
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

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        child_list = await self.children_lister(bound_dn=bound_dn)
        dns = [DistinguishedName(f"{child.getText()},{self.dn.getText()}") for child in
               child_list]
        children = await self.children_getter(dns)
        ret = [self.ChildGroup(dn, backend=self.backend, attributes=attributes) for
               dn, attributes in children.items()]

        if callback:
            for child in ret:
                callback(child)
        return ret

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif self.is_children_dn(dn):
            child_attributes = await self.children_getter([dn])
            if not child_attributes:
                raise LDAPNoSuchObject(dn.getText())
            child = self.ChildGroup(dn, backend=self.backend,
                                    attributes=unwrap(child_attributes))
            return await child._lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())


class CdEDBLeafEntry(CdEDBBaseLDAPEntry, metaclass=abc.ABCMeta):
    """Base class for all dynamic entries.

    Since all dynamic entries do not have any children, they are leafs of the ldap tree.
    Note however that the opposite is not true.
    """

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        """Use the _attributes attribute to return the requested attributes."""
        if not self._attributes:
            raise RuntimeError
        return {k: self._attributes[k] for k in
                attributes} if attributes else self._attributes

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        """All dynamic entries do not have any children by design."""
        return None

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn.getText())


class RootEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.root_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"supportedLDAPVersion": [b"3"],
            # TODO right? Or is this rather dc=cde-ev,dc=de?
            b"namingContexts": [self.backend._to_bytes(self.backend.root_dn)],
            b"subschemaSubentry": [self.backend._to_bytes(self.backend.subschema_dn)],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        de = DeEntry(self.backend)
        subschema = SubschemaEntry(self.backend)
        if callback:
            callback(de)
            callback(subschema)
        return [de, subschema]

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            self._fetch()
            return self
        elif DistinguishedName(self.backend.de_dn).contains(dn):
            de = DeEntry(self.backend)
            return await de._lookup(dn)
        elif DistinguishedName(self.backend.subschema_dn).contains(dn):
            subschema = SubschemaEntry(self.backend)
            return await subschema._lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def _parent(self) -> Optional["CdEDBBaseLDAPEntry"]:
        return None


class SubschemaEntry(CdEDBStaticEntry):
    """Provide some information about the ldap specifications.

    Note that this is a static leaf entry!
    """

    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.subschema_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes: bytes) -> LDAPObject:
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

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        return None

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        else:
            raise LDAPNoSuchObject(dn.getText())

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class DeEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.de_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"top"],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        cde = CdeEvEntry(self.backend)
        if callback:
            callback(cde)
        return [cde]

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.cde_dn).contains(dn):
            cde = CdeEvEntry(self.backend)
            return await cde._lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return RootEntry(self.backend)


class CdeEvEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.cde_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"dcObject", b"organization"],
            b"o": [b"CdE e.V."],
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
        duas = DuasEntry(self.backend)
        users = UsersEntry(self.backend)
        groups = GroupsEntry(self.backend)

        if callback:
            callback(duas)
            callback(users)
            callback(groups)
        return [duas, users, groups]

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.duas_dn).contains(dn):
            duas = DuasEntry(self.backend)
            return await duas._lookup(dn)
        elif DistinguishedName(self.backend.users_dn).contains(dn):
            users = UsersEntry(self.backend)
            return await users._lookup(dn)
        elif DistinguishedName(self.backend.groups_dn).contains(dn):
            groups = GroupsEntry(self.backend)
            return await groups._lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Directory User Agents"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access duas
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Users"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return CdeEvEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests may access no user
            if bound_dn is None:
                return []
            # Users may access only their own data
            elif self.backend.is_user_dn(bound_dn):
                return [self.backend.list_single_user(self.backend.user_id(bound_dn))]
        return await self.backend.list_users()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_users(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_user_dn(dn)


class GroupsEntry(CdEDBStaticEntry):
    def __init__(self, backend: LDAPsqlBackend) -> None:
        dn = DistinguishedName(backend.groups_dn)
        super().__init__(dn, backend)

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Groups"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    async def _children(self, callback: Callback = None, bound_dn: BoundDn = -1
                        ) -> Optional[LDAPEntries]:
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
        return [status, presiders, orgas, moderators, subscribers]

    async def _lookup(self, dn: DistinguishedName) -> CdEDBBaseLDAPEntry:
        if dn == self.dn:
            return self
        elif DistinguishedName(self.backend.status_groups_dn).contains(dn):
            status = StatusGroupsEntry(self.backend)
            return await status._lookup(dn)
        elif DistinguishedName(self.backend.presider_groups_dn).contains(dn):
            presiders = PresiderGroupsEntry(self.backend)
            return await presiders._lookup(dn)
        elif DistinguishedName(self.backend.orga_groups_dn).contains(dn):
            orgas = OrgaGroupsEntry(self.backend)
            return await orgas._lookup(dn)
        elif DistinguishedName(self.backend.moderator_groups_dn).contains(dn):
            moderators = ModeratorGroupsEntry(self.backend)
            return await moderators._lookup(dn)
        elif DistinguishedName(self.backend.subscriber_groups_dn).contains(dn):
            subscribers = SubscriberGroupsEntry(self.backend)
            return await subscribers._lookup(dn)
        else:
            raise LDAPNoSuchObject(dn.getText())

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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Status"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access groups
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Assembly Presiders"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access groups
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Event Orgas"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access groups
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Moderators"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access groups
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
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

    def _fetch(self, *attributes: bytes) -> LDAPObject:
        attrs = {
            b"objectClass": [b"organizationalUnit"],
            b"o": [b"Mailinglists Subscribers"]
        }
        return {k: attrs[k] for k in attributes} if attributes else attrs

    def _parent(self) -> "CdEDBBaseLDAPEntry":
        return GroupsEntry(self.backend)

    async def children_lister(self, bound_dn: BoundDn = -1
                              ) -> List[RelativeDistinguishedName]:
        if bound_dn != -1:
            # Anonymous requests or personas may not access groups
            if bound_dn is None or self.backend.is_user_dn(bound_dn):
                return []
        return await self.backend.list_ml_subscriber_groups()

    async def children_getter(self, dns: List[DistinguishedName]) -> LDAPObjectMap:
        return await self.backend.get_ml_subscriber_groups(dns)

    def is_children_dn(self, dn: DistinguishedName) -> bool:
        return self.backend.is_subscriber_group_dn(dn)
