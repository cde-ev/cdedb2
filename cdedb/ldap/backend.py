"""The ldaptor backend, mediating all queries to the database."""

import asyncio
import logging
import pkgutil
import re
from collections import defaultdict
from typing import (
    TYPE_CHECKING, Any, AsyncIterator, Callable, Collection, Dict, List, Optional,
    Sequence, Type, TypedDict, Union, cast, overload,
)

from ldaptor.protocols.ldap.distinguishedname import DistinguishedName as DN
from ldaptor.protocols.pureber import int2ber
from passlib.hash import sha512_crypt
from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow

from cdedb.config import SecretsConfig
from cdedb.database.constants import SubscriptionState
from cdedb.database.conversions import from_db_output, to_db_input
from cdedb.ldap.schema import SchemaDescription

if TYPE_CHECKING:
    # Lazy import saves many dependecies for standalone mode
    from cdedb.common import CdEDBObject, CdEDBObjectMap
    from cdedb.database.query import DatabaseValue_s
    from cdedb.ldap.entry import CdEDBBaseLDAPEntry

LDAPObject = Dict[bytes, List[bytes]]
LDAPObjectMap = Dict[DN, LDAPObject]
TO_BYTES_RETURN = Any  # Placeholder because of very annoying recursive return type.


logger = logging.getLogger(__name__)


class classproperty:
    """
    Wrapper class to turn instance-methods into @property like pseudo class-methods.

    class A:
        @classproperty
        def x(self) -> int:
            return 5

    A.x == 5
    A().x == 5
    """
    def __init__(self, getter: Callable[..., Any]):
        self.getter = getter

    def __get__(self, instance: Any, owner: Type[Any]) -> Any:
        return self.getter(owner)


@overload
def _to_bytes(data: Dict[Any, Any]) -> Dict[bytes, Any]: ...


@overload
def _to_bytes(data: Union[None, str, int, bytes]) -> bytes: ...


@overload
def _to_bytes(data: List[Any]) -> List[Any]: ...


def _to_bytes(
        data: Union[None, str, int, bytes, DN, Dict[Any, Any], List[Any]]
) -> TO_BYTES_RETURN:
    """This takes a python data structure and convert all of its entries into bytes.

    This is needed to send the ldap responses over the wire and ensure proper
    encoding, especially of strings.
    """
    if data is None:
        return b""
    elif isinstance(data, dict):
        return {_to_bytes(k): _to_bytes(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_to_bytes(entry) for entry in data]
    elif isinstance(data, DN):
        return _to_bytes(data.getText())
    elif isinstance(data, str):
        return data.encode("utf-8")
    elif isinstance(data, int):
        return int2ber(data)
    elif isinstance(data, bytes):
        return data
    else:
        raise NotImplementedError(data)


class LdapLeaf(TypedDict):
    get_entities: Callable[[List[DN]], LDAPObjectMap]
    list_entities: Callable[[], List[DN]]


class LDAPsqlBackend:
    """Provide the interface between ldap and database."""
    def __init__(self, conn: AsyncConnection[DictRow]) -> None:
        self.conn = conn
        # load the ldap schemas (and overlays) which are supported
        self.schema = self.load_schemas(
            "core.schema", "cosine.schema", "inetorgperson.schema", "memberof.overlay")
        # encrypting dua passwords once at startup, to increase runtime performance
        self._dua_pwds = {name: self.encrypt_password(pwd)
                          for name, pwd in SecretsConfig()["LDAP_DUA_PW"].items()}

    @staticmethod
    async def execute_db_query(cur: AsyncCursor[DictRow], query: str,
                               params: Sequence["DatabaseValue_s"]) -> None:
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`to_db_input`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.
        """
        sanitized_params = tuple(to_db_input(p) for p in params)
        # psycopg3 does server-side parameter substitution. Sadly, cur.mogrify is
        # therefore no longer available ...
        # logger.debug(f"Execute PostgreSQL query"
        #              f" {cur.mogrify(query, sanitized_params)}.")
        await cur.execute(query, sanitized_params)

    async def query_exec(self, query: str, params: Sequence["DatabaseValue_s"]) -> int:
        """Execute a query in a safe way (inside a transaction)."""
        async with self.conn.cursor() as cur:
            await self.execute_db_query(cur, query, params)
            return cur.rowcount

    async def query_one(self, query: str, params: Sequence["DatabaseValue_s"]
                        ) -> Optional["CdEDBObject"]:
        """Execute a query in a safe way (inside a transaction).

        :returns: First result of query or None if there is none
        """
        async with self.conn.cursor() as cur:
            await self.execute_db_query(cur, query, params)
            return from_db_output(await cur.fetchone())

    async def query_all(self, query: str, params: Sequence["DatabaseValue_s"]
                        ) -> AsyncIterator["CdEDBObject"]:
        """Execute a query in a safe way (inside a transaction).

        :returns: all results of query
        """
        async with self.conn.cursor() as cur:
            await self.execute_db_query(cur, query, params)
            async for x in cur:
                yield cast("CdEDBObject", from_db_output(x))

    @staticmethod
    def _dn_value(dn: DN, attribute: str) -> Optional[str]:
        """Retrieve the value of the RDN matching the given attribute type."""
        rdn = dn.split()[0]
        [attribute_value] = rdn.split()
        if attribute_value.attributeType == attribute:
            return attribute_value.value
        else:
            return None

    @staticmethod
    def _extract_id(cn: str, prefix: str) -> Optional[int]:
        """Extract the id from a cn by stripping the prefix.

        This especially checks that the id is a valid integer.
        """
        if match := re.match(rf"^{prefix}(?P<id>\d+)$", cn):
            return int(match.group("id"))
        else:
            return None

    @staticmethod
    def _is_entry_dn(dn: DN, parent_dn: DN, attribute_type: str) -> bool:
        """Validate a given dn inside the ldap tree.

        We have different types of dynamic generated ldap entries. So, we need dynamic
        validation to check if a presented dn may be of a specific kind.

        To check this, we compare the parent dn of the given dn (all dynamic entries
        have static parents) and check that the rdn of the entry has the expected
        unique attribute type.
        """
        if dn.up() != parent_dn:
            return False
        rdn = dn.split()[0]
        if len(rdn.split()) != 1 or rdn.split()[0].attributeType != attribute_type:
            return False
        return True

    _to_bytes = staticmethod(_to_bytes)

    @staticmethod
    def load_schemas(*schemas: str) -> SchemaDescription:
        """Load the provided ldap schemas and parse their content from file."""
        data = []
        for schema in schemas:
            datum = pkgutil.get_data("cdedb.ldap", f"schema/{schema}")
            if datum is None:
                logger.error(f"Schema {schema} could not be loaded.")
                continue
            data.append(datum.decode("utf-8"))

        # punch all files together to create a single schema object
        file = "\n\n\n".join(data)
        return SchemaDescription(file)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Mimic backend.core.base.verify_password"""
        # TODO move into common and use it here
        return sha512_crypt.verify(password, password_hash)

    @staticmethod
    def encrypt_password(password: str) -> str:
        """Mimic backend.core.base.encrypt_password"""
        # TODO move into common and use it here
        return sha512_crypt.hash(password)

    #######################
    # Access restrictions #
    #######################

    @classproperty
    def anonymous_accessible_dns(self) -> List[DN]:
        """A closed list of all dns which may be accessed by anonymous binds."""
        return [self.subschema_dn]

    @classmethod
    def may_dua_access_user(cls, dua: DN, user: "CdEDBBaseLDAPEntry") -> bool:
        """Decide if the given dua may access the data of the given user."""
        if not cls.users_dn.contains(user.dn):
            raise ValueError("The given LDAPEntry is no user!")
        if not (cls.duas_dn.contains(dua) and cls.duas_dn != dua):
            raise ValueError("The given DN is no dua!")

        # TODO we may restrict access of duas to users by f.e. group membership.
        return True

    @classmethod
    def may_dua_access_group(cls, dua: DN, group: "CdEDBBaseLDAPEntry") -> bool:
        """Decide if the given dua may access the data of the given group."""
        if not cls.groups_dn.contains(group.dn):
            raise ValueError("The given LDAPEntry is no group!")
        if not (cls.duas_dn.contains(dua) and cls.duas_dn != dua):
            raise ValueError("The given DN is no dua!")

        # TODO we may restrict access of duas to type of groups
        if dua in {cls.dua_dn("apache"), cls.dua_dn("cloud")}:
            return True
        return False

    ###############
    # operational #
    ###############

    @classproperty
    def root_dn(self) -> DN:  # pylint: disable=no-self-use
        """The root entry of the ldap tree."""
        return DN("")

    @classproperty
    def subschema_dn(self) -> DN:  # pylint: disable=no-self-use
        """The DN containing information about the supported schemas.

        This is needed by f.e. Apache Directory Studio to determine which
        attributeTypes, objectClasses etc are supported.
        """
        return DN("cn=subschema")

    @classproperty
    def de_dn(self) -> DN:  # pylint: disable=no-self-use
        return DN("dc=de")

    @classproperty
    def cde_dn(self) -> DN:
        return DN(f"dc=cde-ev,{self.de_dn.getText()}")

    ########
    # duas #
    ########

    @classproperty
    def duas_dn(self) -> DN:
        return DN(f"ou=duas,{self.cde_dn.getText()}")

    @staticmethod
    def dua_cn(name: str) -> str:
        """Construct the CN of a dua from its (database) 'name'."""
        return name

    @classmethod
    def dua_name(cls, dn: DN) -> Optional[str]:
        """Extract the 'name' attribute from a duas dn. Counterpart of 'dua_dn'."""
        cn = cls._dn_value(dn, attribute="cn")
        return cn or None

    @classmethod
    def dua_dn(cls, name: str) -> DN:
        """Construct a duas dn from its 'name' attribute. Counterpart of 'dua_name'."""
        return DN(f"cn={cls.dua_cn(name)},{cls.duas_dn.getText()}")

    @classmethod
    def is_dua_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.duas_dn, "cn")

    async def list_duas(self) -> List[DN]:
        """List all duas.

        The abstraction layer of entry.py expects a coroutine to return the lists of
        dynamic entries. Therefore, this is a coroutine, even if we do not do anything
        async here.
        """
        duas = self._dua_pwds
        return [self.dua_dn(cn) for cn in duas]

    async def get_duas(self, dns: List[DN]) -> LDAPObjectMap:
        """Get the data for the given duas.

        The abstraction layer of entry.py expects a coroutine to return the data for
        dynamic entries. Therefore, this is a coroutine, even if we do not do anything
        async here.
        """
        dn_to_name = dict()
        for dn in dns:
            name = self.dua_name(dn)
            if name is None:
                continue
            dn_to_name[dn] = name

        ret = dict()
        for dn, name in dn_to_name.items():
            if name not in self._dua_pwds:
                continue
            dua = {
                # TODO find a better objectClass for duas then 'person'
                b"objectClass": ["person", "simpleSecurityObject"],
                b"cn": [self.dua_cn(name)],
                b"userPassword": [self._dua_pwds[name]]
            }
            ret[dn] = self._to_bytes(dua)
        return ret

    #########
    # users #
    #########

    @classproperty
    def users_dn(self) -> DN:
        return DN(f"ou=users,{self.cde_dn.getText()}")

    @staticmethod
    def user_uid(persona_id: int) -> str:
        """Construct the 'uid' of a user from its (database) id."""
        return str(persona_id)

    @classmethod
    def user_id(cls, dn: DN) -> Optional[int]:
        """Extract the id of a user from its dn. Counterpart of 'user_dn'."""
        uid = cls._dn_value(dn, attribute="uid")
        if uid is None:
            return None
        return cls._extract_id(uid, prefix="")

    @classmethod
    def user_dn(cls, persona_id: int) -> DN:
        """Construct a users dn from its id. Counterpart of 'user_id'."""
        return DN(f"uid={cls.user_uid(persona_id)},{cls.users_dn.getText()}")

    @classmethod
    def is_user_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.users_dn, "uid")

    @staticmethod
    def make_persona_name(persona: "CdEDBObject",
                          only_given_names: bool = False,
                          only_display_name: bool = False,
                          given_and_display_names: bool = False,
                          with_family_name: bool = True,
                          with_titles: bool = False) -> str:
        """Mimic the implementation of frontend.common.make_persona_name.

        Since we do not want to have cross-dependencies between the web and ldap code
        base, we need this small logic duplication.
        """
        # TODO move into common and use it here
        display_name: str = persona.get('display_name', "")
        given_names: str = persona['given_names']
        ret = []
        if with_titles and persona.get('title'):
            ret.append(persona['title'])
        if only_given_names:
            ret.append(given_names)
        elif only_display_name:
            ret.append(display_name)
        elif given_and_display_names:
            if not display_name or display_name == given_names:
                ret.append(given_names)
            else:
                ret.append(f"{given_names} ({display_name})")
        elif display_name and display_name in given_names:
            ret.append(display_name)
        else:
            ret.append(given_names)
        if with_family_name:
            ret.append(persona['family_name'])
        if with_titles and persona.get('name_supplement'):
            ret.append(persona['name_supplement'])
        return " ".join(ret)

    @classmethod
    def list_single_user(cls, persona_id: int) -> DN:
        """Uninlined code from list_users.

        This is needed in entry.py for preventing ddos attacs, so we uninline it here.
        """
        return cls.user_dn(persona_id)

    async def list_users(self) -> List[DN]:
        query = "SELECT id FROM core.personas WHERE NOT is_archived"
        return [self.list_single_user(e["id"]) async for e in self.query_all(query, [])]

    async def get_users_groups(self, persona_ids: Collection[int]
                               ) -> Dict[int, List[str]]:
        """Collect all groups of each given user.

        This is completely redundant information – we could get the same information by
        querying all groups for a given persona's membership. However, it is more
        convenient to have this additional view on the privileges. Therefore, care has
        to be taken that this produces always the same group memberships than the group
        entries below!

        Returns a dict, mapping persona_id to a list of their group dn strings.
        """
        ret: Dict[int, List[str]] = {anid: [] for anid in persona_ids}

        # TODO: This could each be turned into it's own coroutine to then be
        #  executed concurrently. Maybe this could even be combined with the other
        #  helpers, ensuring equivalency.

        # Status groups
        query = """
                SELECT id,
                    is_active, is_member, is_searchable AND is_member AS is_searchable,
                    is_ml_realm, is_event_realm, is_assembly_realm, is_cde_realm,
                    is_ml_admin, is_event_admin, is_assembly_admin, is_cde_admin,
                    is_core_admin, is_finance_admin, is_cdelokal_admin
                FROM core.personas WHERE personas.id = ANY(%s)
                """
        async for e in self.query_all(query, (persona_ids,)):
            ret[e["id"]].extend(self.status_group_dn(flag)
                                for flag in e.keys() if e[flag] and flag != "id")

        # Presider groups
        query = """
                SELECT persona_id, ARRAY_AGG(assembly_id) AS assembly_ids
                FROM assembly.presiders
                WHERE persona_id = ANY(%s)
                GROUP BY persona_id
                """
        async for e in self.query_all(query, (persona_ids,)):
            ret[e["persona_id"]].extend(self.presider_group_dn(assembly_id)
                                        for assembly_id in e["assembly_ids"])

        # Orga groups
        query = """
                SELECT persona_id, ARRAY_AGG(event_id) AS event_ids
                FROM event.orgas
                WHERE persona_id = ANY(%s)
                GROUP BY persona_id"""
        async for e in self.query_all(query, (persona_ids,)):
            ret[e["persona_id"]].extend(self.orga_group_dn(event_id)
                                        for event_id in e["event_ids"])

        # Subscriber groups
        query = """
                SELECT persona_id, ARRAY_AGG(address) AS addresses
                FROM ml.subscription_states, ml.mailinglists
                WHERE ml.mailinglists.id = ml.subscription_states.mailinglist_id
                    AND subscription_state = ANY(%s)
                    AND persona_id = ANY(%s)
                GROUP BY persona_id
                """
        states = SubscriptionState.subscribing_states()
        async for e in self.query_all(query, (states, persona_ids,)):
            ret[e["persona_id"]].extend(self.subscriber_group_dn(address)
                                        for address in e["addresses"])

        # Moderator groups
        query = """
                SELECT persona_id, ARRAY_AGG(address) AS addresses
                FROM ml.moderators, ml.mailinglists
                WHERE ml.mailinglists.id = ml.moderators.mailinglist_id
                    AND persona_id = ANY(%s)
                GROUP BY persona_id
                """
        async for e in self.query_all(query, (persona_ids,)):
            ret[e["persona_id"]].extend(self.moderator_group_dn(address)
                                        for address in e["addresses"])

        return ret

    async def get_users_data(self, user_ids: Collection[int]) -> "CdEDBObjectMap":
        """Helper function to get basic data about users from core.personas."""
        query = (
            "SELECT id, username, display_name, given_names, family_name, password_hash"
            " FROM core.personas WHERE id = ANY(%s) AND NOT is_archived")
        return {
            e["id"]: e async for e in self.query_all(query, (user_ids,))
        }

    async def get_users(self, dns: List[DN]) -> LDAPObjectMap:
        """Get the users specified by dn.

        The relevant RFCs are
        https://datatracker.ietf.org/doc/html/rfc2798 (defining inetOrgPerson)
        https://datatracker.ietf.org/doc/html/rfc4519 (defining additional attributes)
        """
        dn_to_persona_id = dict()
        for dn in dns:
            persona_id = self.user_id(dn)
            if persona_id is None:
                continue
            dn_to_persona_id[dn] = persona_id

        users, groups = await asyncio.gather(
            self.get_users_data(dn_to_persona_id.values()),
            self.get_users_groups(dn_to_persona_id.values()),
        )

        ret = dict()
        for dn, persona_id in dn_to_persona_id.items():
            if persona_id not in users:
                continue
            user = users[persona_id]
            ldap_user = {
                b"objectClass": ["inetOrgPerson"],
                b"cn": [f"{user['given_names']} {user['family_name']}"],
                b"sn": [user['family_name']],
                b"displayName": [self.make_persona_name(user)],
                b"givenName": [user['given_names']],
                b"mail": [user['username']],
                b"uid": [self.user_uid(persona_id)],
                b"userPassword": [user['password_hash']],
                b"memberOf": groups[persona_id],
            }
            ret[dn] = self._to_bytes(ldap_user)
        return ret

    ##########
    # groups #
    ##########

    @classproperty
    def groups_dn(self) -> DN:
        return DN(f"ou=groups,{self.cde_dn.getText()}")

    #
    # status
    #

    @classproperty
    def status_groups_dn(self) -> DN:
        return DN(f"ou=status,{self.groups_dn.getText()}")

    @staticmethod
    def status_group_cn(name: str) -> str:
        """Construct the 'cn' of a status group from its (database) field name."""
        return name

    @classmethod
    def status_group_name(cls, dn: DN) -> Optional[str]:
        """Extract the name of a status group from its dn.

        Counterpart of 'status_group_dn'.
        """
        cn = cls._dn_value(dn, attribute="cn")
        return cn if cn in cls.STATUS_GROUPS else None

    @classmethod
    def status_group_dn(cls, name: str) -> DN:
        """Construct the dn of a status group form its name.

        Counterpart of 'status_group_name'.
        """
        return DN(f"cn={cls.status_group_cn(name)},{cls.status_groups_dn.getText()}")

    @classmethod
    def is_status_group_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.status_groups_dn, "cn")

    STATUS_GROUPS = {
        "is_active": "Aktive Nutzer.",
        "is_member": "Nutzer, die aktuell Mitglied im CdE sind.",
        "is_searchable": ("Nutzer, die aktuell Mitglied im CdE und und in der Datenbank"
                          " suchbar sind."),
        "is_ml_realm": "Nutzer, die auf Mailinglisten stehen dürfen.",
        "is_event_realm": "Nutzer, die an Veranstaltungen teilnehmen dürfen.",
        "is_assembly_realm": "Nutzer, die an Versammlungen teilnehmen dürfen.",
        "is_cde_realm": "Nutzer, die jemals Mitglied im CdE waren oder sind.",
        "is_ml_admin": "Mailinglisten-Administratoren",
        "is_event_admin": "Veranstaltungs-Administratoren",
        "is_assembly_admin": "Versammlungs-Administratoren",
        "is_cde_admin": "CdE-Administratoren",
        "is_core_admin": "Core-Administratoren",
        "is_finance_admin": "Finanz-Administratoren",
        "is_cdelokal_admin": "CdELokal-Administratoren",
    }

    async def list_status_groups(self) -> List[DN]:
        return [self.status_group_dn(name) for name in self.STATUS_GROUPS]

    async def _get_status_group(self, dn: DN, name: str) -> tuple[DN, LDAPObject]:
        """Uninlined code from get_status_groups."""
        if name == "is_searchable":
            condition = "is_member AND is_searchable"
        else:
            condition = name
        query = f"SELECT id FROM core.personas WHERE {condition}"
        return dn, self._to_bytes({
            b"cn": [self.status_group_cn(name)],
            b"objectClass": ["groupOfUniqueNames"],
            b"description": [self.STATUS_GROUPS[name]],
            b"uniqueMember": [
                self.user_dn(e["id"]) async for e in self.query_all(query, ())
            ]
        })

    async def get_status_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_name = dict()
        for dn in dns:
            name = self.status_group_name(dn)
            if name is None:
                continue
            dn_to_name[dn] = name

        # Schedule all tasks at the same time and wait for them all to complete.
        # For convenience, the `_get_status_group` helper returns the dn as the key.
        # For some reason the generator expression needs to be unpacked explicitly.
        return dict(await asyncio.gather(*(
            self._get_status_group(dn, name)
            for dn, name in dn_to_name.items()
            if name in self.STATUS_GROUPS
        )))

    #
    # presiders
    #

    @classproperty
    def presider_groups_dn(self) -> DN:
        return DN(f"ou=assembly-presiders,{self.groups_dn.getText()}")

    @staticmethod
    def presider_group_cn(assembly_id: int) -> str:
        """Construct the 'cn' of a presider group from its (database) id."""
        return f"presiders-{assembly_id}"

    @classmethod
    def presider_group_id(cls, dn: DN) -> Optional[int]:
        """Extract the id of a presider group from its dn.

        Counterpart to 'presider_group_dn'.
        """
        cn = cls._dn_value(dn, attribute="cn")
        if cn is None:
            return None
        return cls._extract_id(cn, prefix="presiders-")

    @classmethod
    def presider_group_dn(cls, assembly_id: int) -> DN:
        """Construct a presider groups dn from its id.

        Counterpart to 'presider_group_id'.
        """
        return DN(f"cn={cls.presider_group_cn(assembly_id)},"
                  f"{cls.presider_groups_dn.getText()}")

    @classmethod
    def is_presider_group_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.presider_groups_dn, "cn")

    async def list_assembly_presider_groups(self) -> List[DN]:
        query = "SELECT id FROM assembly.assemblies"
        return [
            self.presider_group_dn(e['id'])
            async for e in self.query_all(query, [])
        ]

    async def get_presiders(self, assembly_ids: Collection[int]
                            ) -> Dict[int, List[int]]:
        """Helper function to get the presiders of the given assemblies."""
        query = ("SELECT persona_id, assembly_id FROM assembly.presiders"
                 " WHERE assembly_id = ANY(%s)")
        presiders = defaultdict(list)
        async for e in self.query_all(query, (assembly_ids,)):
            presiders[e["assembly_id"]].append(e["persona_id"])
        return presiders

    async def get_assemblies(self, assembly_ids: Collection[int]) -> "CdEDBObjectMap":
        """Helper function to get some information about the given assemblies."""
        query = ("SELECT id, title, shortname FROM assembly.assemblies"
                 " WHERE id = ANY(%s)")
        return {
            e["id"]: e
            async for e in self.query_all(query, (assembly_ids,))
        }

    async def get_assembly_presider_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_assembly_id = dict()
        for dn in dns:
            assembly_id = self.presider_group_id(dn)
            if assembly_id is None:
                continue
            dn_to_assembly_id[dn] = assembly_id

        assemblies, presiders = await asyncio.gather(
            self.get_assemblies(dn_to_assembly_id.values()),
            self.get_presiders(dn_to_assembly_id.values()),
        )

        ret = dict()
        for dn, assembly_id in dn_to_assembly_id.items():
            if assembly_id not in assemblies:
                continue
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [self.presider_group_cn(assembly_id)],
                b"description": [f"{assemblies[assembly_id]['title']}"
                                 f" ({assemblies[assembly_id]['shortname']})"],
                b"uniqueMember": [self.user_dn(e) for e in presiders[assembly_id]]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # orgas
    #

    @classproperty
    def orga_groups_dn(self) -> DN:
        return DN(f"ou=event-orgas,{self.groups_dn.getText()}")

    @staticmethod
    def orga_group_cn(event_id: int) -> str:
        """Construct the 'cn' of an orga group from its (database) id."""
        return f"orgas-{event_id}"

    @classmethod
    def orga_group_id(cls, dn: DN) -> Optional[int]:
        """Extract the id of an orga group from its dn.

        Counterpart to 'orga_group_dn'.
        """
        cn = cls._dn_value(dn, attribute="cn")
        if cn is None:
            return None
        return cls._extract_id(cn, prefix="orgas-")

    @classmethod
    def orga_group_dn(cls, event_id: int) -> DN:
        """Construct the dn of an orga group from its id.

        Counterpart of 'orga_group_id'.
        """
        return DN(f"cn={cls.orga_group_cn(event_id)},{cls.orga_groups_dn.getText()}")

    @classmethod
    def is_orga_group_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.orga_groups_dn, "cn")

    async def list_event_orga_groups(self) -> List[DN]:
        query = "SELECT id FROM event.events"
        return [self.orga_group_dn(e['id']) async for e in self.query_all(query, [])]

    async def get_orgas(self, event_ids: Collection[int]) -> Dict[int, List[int]]:
        """Helper functions to get the orgas of the given events."""
        query = "SELECT persona_id, event_id FROM event.orgas WHERE event_id = ANY(%s)"
        orgas = defaultdict(list)
        async for e in self.query_all(query, (event_ids,)):
            orgas[e["event_id"]].append(e["persona_id"])
        return orgas

    async def get_events(self, event_ids: Collection[int]) -> "CdEDBObjectMap":
        """Helper function to get some information about the given events."""
        query = "SELECT id, title, shortname FROM event.events WHERE id = ANY(%s)"
        return {
            e["id"]: e async for e in self.query_all(query, (event_ids,))
        }

    async def get_event_orga_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_event_id = dict()
        for dn in dns:
            event_id = self.orga_group_id(dn)
            if event_id is None:
                continue
            dn_to_event_id[dn] = event_id

        events, orgas = await asyncio.gather(
            self.get_events(dn_to_event_id.values()),
            self.get_orgas(dn_to_event_id.values()),
        )

        ret = dict()
        for dn, event_id in dn_to_event_id.items():
            if event_id not in events:
                continue
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [self.orga_group_cn(event_id)],
                b"description": [f"{events[event_id]['title']}"
                                 f" ({events[event_id]['shortname']})"],
                b"uniqueMember": [self.user_dn(e) for e in orgas[event_id]]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # moderators
    #

    @classproperty
    def moderator_groups_dn(self) -> DN:
        return DN(f"ou=ml-moderators,{self.groups_dn.getText()}")

    @staticmethod
    def moderator_group_cn(address: str) -> str:
        """Construct the 'cn' of an orga group from its address."""
        return address.replace("@", "-owner@")

    @classmethod
    def moderator_group_address(cls, dn: DN) -> Optional[str]:
        """Extract the address from a moderator group from its dn.

        Note that this returns the regular address of the mailinglist, not the
        owner address.
        Counterpart of 'moderator_group_dn'.
        """
        cn = cls._dn_value(dn, attribute="cn")
        if cn is None:
            return None
        if match := re.match(r"(?P<local_part>[\w.-]*)-owner@(?P<domain>[\w.-]*)", cn):
            return f"{match.group('local_part')}@{match.group('domain')}"
        else:
            return None

    @classmethod
    def moderator_group_dn(cls, address: str) -> DN:
        """Construct the dn of a moderator group from its address.

        Counterpart of 'moderator_group_address'.
        """
        return DN(f"cn={cls.moderator_group_cn(address)},"
                  f"{cls.moderator_groups_dn.getText()}")

    @classmethod
    def is_moderator_group_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.moderator_groups_dn, "cn")

    async def list_ml_moderator_groups(self) -> List[DN]:
        query = "SELECT address FROM ml.mailinglists"
        return [
            self.moderator_group_dn(e['address'])
            async for e in self.query_all(query, [])
        ]

    async def get_moderators(self, ml_ids: Collection[str]) -> Dict[str, List[int]]:
        """Helper function to get the moderators of the given mailinglists."""
        query = ("SELECT persona_id, address FROM ml.moderators, ml.mailinglists"
                 " WHERE ml.mailinglists.id = ml.moderators.mailinglist_id"
                 " AND address = ANY(%s)")
        moderators = defaultdict(list)
        async for e in self.query_all(query, (ml_ids,)):
            moderators[e["address"]].append(e["persona_id"])
        return moderators

    async def get_mailinglists(self, ml_ids: Collection[str]
                               ) -> Dict[str, "CdEDBObject"]:
        """Helper function to get some information about the given mailinglists."""
        query = ("SELECT address, title FROM ml.mailinglists WHERE address = ANY(%s)")
        return {
            e["address"]: e
            async for e in self.query_all(query, (ml_ids,))
        }

    async def get_ml_moderator_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            address = self.moderator_group_address(dn)
            if address is None:
                continue
            dn_to_address[dn] = address

        mls, moderators = await asyncio.gather(
            self.get_mailinglists(dn_to_address.values()),
            self.get_moderators(dn_to_address.values()),
        )

        ret = dict()
        for dn, address in dn_to_address.items():
            if address not in mls:
                continue
            # mail addresses seem to be valid cns
            # https://datatracker.ietf.org/doc/html/rfc4512#section-2.3.2
            cn = self.moderator_group_cn(address)
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [cn],
                b"description": [f"{mls[address]['title']} <{cn}>"],
                b"uniqueMember": [self.user_dn(e) for e in moderators[address]]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # subscribers
    #

    @classproperty
    def subscriber_groups_dn(self) -> DN:
        return DN(f"ou=ml-subscribers,{self.groups_dn.getText()}")

    @staticmethod
    def subscriber_group_cn(address: str) -> str:
        """Construct the 'cn' of an subscriber group from its address."""
        return address

    @classmethod
    def subscriber_group_address(cls, dn: DN) -> Optional[str]:
        """Extract the address of a subscriber group from its dn.

        Counterpart of 'subscriber_group_dn'.
        """
        return cls._dn_value(dn, attribute="cn")

    @classmethod
    def subscriber_group_dn(cls, address: str) -> DN:
        """Construct a subscriber groups dn from its address.

        Counterpart of 'subscriber_group_address'.
        """
        return DN(f"cn={cls.subscriber_group_cn(address)},"
                  f"{cls.subscriber_groups_dn.getText()}")

    @classmethod
    def is_subscriber_group_dn(cls, dn: DN) -> bool:
        return cls._is_entry_dn(dn, cls.subscriber_groups_dn, "cn")

    async def list_ml_subscriber_groups(self) -> List[DN]:
        query = "SELECT address FROM ml.mailinglists"
        return [
            self.subscriber_group_dn(e['address'])
            async for e in self.query_all(query, [])
        ]

    async def get_subscribers(self, ml_ids: Collection[str]) -> Dict[str, List[int]]:
        """Helper function to get the subscribers of the given mailinglists."""
        query = ("SELECT persona_id, address"
                 " FROM ml.subscription_states, ml.mailinglists"
                 " WHERE ml.mailinglists.id = ml.subscription_states.mailinglist_id"
                 " AND subscription_state = ANY(%s) AND address = ANY(%s)")
        states = SubscriptionState.subscribing_states()
        subscribers = defaultdict(list)
        async for e in self.query_all(query, (states, ml_ids,)):
            subscribers[e["address"]].append(e["persona_id"])
        return subscribers

    async def get_ml_subscriber_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            address = self.subscriber_group_address(dn)
            if address is None:
                continue
            dn_to_address[dn] = address

        mls, subscribers = await asyncio.gather(
            self.get_mailinglists(dn_to_address.values()),
            self.get_subscribers(dn_to_address.values()),
        )

        ret = dict()
        for dn, address in dn_to_address.items():
            if address not in mls:
                continue
            # mail addresses seem to be valid cns
            # https://datatracker.ietf.org/doc/html/rfc4512#section-2.3.2
            cn = self.subscriber_group_cn(address)
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [cn],
                b"description": [f"{mls[address]['title']} <{cn}>"],
                b"uniqueMember": [self.user_dn(e) for e in subscribers[address]]
            }
            ret[dn] = self._to_bytes(group)
        return ret
