import logging
import pathlib
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, TypedDict, Union, cast

import aiopg.connection
from aiopg.pool import Pool, create_pool
from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, LDAPAttributeTypeAndValue as ATV,
    RelativeDistinguishedName as RDN,
)
from passlib.hash import sha512_crypt

from cdedb.common import CdEDBObject, unwrap
from cdedb.config import SecretsConfig
from cdedb.database.constants import SubscriptionState
from cdedb.database.query import DatabaseValue_s, SqlQueryBackend
from cdedb.ldap.schema import SchemaDescription

LDAPObject = Dict[bytes, List[bytes]]
LDAPObjectMap = Dict[DN, LDAPObject]

logger = logging.getLogger(__name__)


class LdapLeaf(TypedDict):
    get_entities: Callable[[List[DN]], LDAPObjectMap]
    list_entities: Callable[[], List[RDN]]


class LDAPsqlBackend:
    """Provide the interface between ldap and database."""
    def __init__(self, pool: Pool) -> None:
        self.secrets = SecretsConfig()
        self.pool = pool
        # load the ldap schemas which are supported
        self.schema = self.load_schemas("core", "cosine", "inetorgperson")

    @staticmethod
    async def execute_db_query(cur: aiopg.connection.Cursor, query: str,
                               params: Sequence[DatabaseValue_s]) -> None:
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`_sanitize_db_input`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.
        """
        # TODO extract _sanitize_db_input() etc. from SqlQueryBackend
        sanitized_params = tuple(
            SqlQueryBackend._sanitize_db_input(p) for p in params)
        logger.debug(f"Execute PostgreSQL query"
                     f" {cur.mogrify(query, sanitized_params)}.")
        await cur.execute(query, sanitized_params)

    async def query_exec(self, query: str, params: Sequence[DatabaseValue_s]) -> int:
        """Execute a query in a safe way (inside a transaction)."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await self.execute_db_query(cur, query, params)
                return cur.rowcount

    async def query_one(self, query: str, params: Sequence[DatabaseValue_s]
                        ) -> Optional[CdEDBObject]:
        """Execute a query in a safe way (inside a transaction).

        :returns: First result of query or None if there is none
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await self.execute_db_query(cur, query, params)
                return SqlQueryBackend._sanitize_db_output(await cur.fetchone())

    async def query_all(self, query: str, params: Sequence[DatabaseValue_s]
                        ) -> List[CdEDBObject]:
        """Execute a query in a safe way (inside a transaction).

        :returns: all results of query
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await self.execute_db_query(cur, query, params)
                return [cast(CdEDBObject, SqlQueryBackend._sanitize_db_output(x))
                        for x in await cur.fetchall()]

    @staticmethod
    def _dn_value(dn: DN, attribute: str) -> Optional[str]:
        """Retrieve the value of the RDN matching the given attribute type."""
        rdn = dn.split()[0]
        # TODO unwrap() seems to be overkill here
        attribute_value = unwrap(rdn.split())
        if attribute_value.attributeType == attribute:
            return attribute_value.value
        else:
            return None

    @staticmethod
    def _extract_id(cn: str, prefix: str) -> Optional[int]:
        """Extract the id from a cn by stripping the prefix.

        This especially checks that the id is a valid base 10 integer.
        """
        if match := re.match(f"^{prefix}(?P<id>\d+)$", cn):
            return int(match.group("id"))
        else:
            return None

    @staticmethod
    def _is_entry_dn(dn: DN, parent_dn: str, attribute_type: str) -> bool:
        if dn.up().getText() != parent_dn:
            return False
        rdn = dn.split()[0]
        if len(rdn.split()) != 1 or rdn.split()[0].attributeType != attribute_type:
            return False
        return True

    # TODO more fancy type annotations
    def _to_bytes(self, object: Union[Dict[Any, Any], List[Any], str, int, bytes, None]
                  ) -> Union[Dict[bytes, Any], List[Any], bytes]:
        """This takes a python data structure and convert all of its entries into bytes.

        This is needed to send the ldap responses over the wire and ensure proper
        encoding, especially of strings.
        """
        if object is None:
            return b""
        elif isinstance(object, dict):
            return {self._to_bytes(k): self._to_bytes(v) for k, v in object.items()}
        elif isinstance(object, list):
            return [self._to_bytes(entry) for entry in object]
        elif isinstance(object, str):
            return object.encode("utf-8")
        elif isinstance(object, int):
            return bytes(object)
        elif isinstance(object, bytes):
            return object
        else:
            raise NotImplementedError(object)

    @property
    def anonymous_accessible_dns(self) -> List[DN]:
        """A closed list of all dns which may be accessed by anonymous binds."""
        return [DN(stringValue=self.subschema_dn)]

    @staticmethod
    def load_schemas(*schemas: str) -> SchemaDescription:
        """Load the provided ldap schemas and parse their content from file."""
        data = []
        for schema in schemas:
            # TODO replace with pkgutil.get_data()
            with (pathlib.Path(__file__).parent / "schema" / f"{schema}.schema").open() as f:
                data.append(f.read())

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

    ###############
    # operational #
    ###############

    @property
    def root_dn(self) -> str:
        """The root entry of the ldap tree."""
        return ""

    @property
    def subschema_dn(self) -> str:
        """The DN containing information about the supported schemas.

        This is needed by f.e. Apache Directory Studio to determine which
        attributeTypes, objectClasses etc are supported.
        """
        return "cn=subschema"

    @property
    def de_dn(self) -> str:
        return "dc=de"

    @property
    def cde_dn(self) -> str:
        return f"dc=cde-ev,{self.de_dn}"

    ########
    # duas #
    ########

    @property
    def duas_dn(self) -> str:
        return f"ou=duas,{self.cde_dn}"

    @staticmethod
    def dua_cn(name: str) -> str:
        return name

    @staticmethod
    def dua_name(cn: str) -> Optional[str]:
        return cn or None

    def dua_dn(self, name: str) -> str:
        return f"cn={self.dua_cn(name)},{self.duas_dn}"

    def is_dua_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.duas_dn, "cn")

    async def list_duas(self) -> List[RDN]:
        duas = self.secrets["LDAP_DUA_PW"]
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.dua_cn(cn))
                ]
            ) for cn in duas
        ]

    async def get_duas(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_name = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            name = self.dua_name(cn)
            if name is None:
                continue
            dn_to_name[dn] = name

        data = self.secrets["LDAP_DUA_PW"]
        duas = {name: self.encrypt_password(pwd) for name, pwd in data.items()}

        ret = dict()
        for dn, name in dn_to_name.items():
            if name not in duas:
                continue
            dua = {
                # TODO find a better objectClass for duas then 'person'
                b"objectClass": ["person", "simpleSecurityObject"],
                b"cn": [self.dua_cn(name)],
                b"userPassword": [duas[name]]
            }
            ret[dn] = self._to_bytes(dua)
        return ret

    #########
    # users #
    #########

    @property
    def users_dn(self) -> str:
        return f"ou=users,{self.cde_dn}"

    @staticmethod
    def user_uid(persona_id: int) -> str:
        return str(persona_id)

    def user_id(self, uid: str) -> Optional[int]:
        return self._extract_id(uid, prefix="")

    def user_dn(self, persona_id: int) -> str:
        return f"uid={self.user_uid(persona_id)},{self.users_dn}"

    def is_user_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.users_dn, "uid")

    @staticmethod
    def make_persona_name(persona: CdEDBObject,
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

    async def list_users(self) -> List[RDN]:
        query = "SELECT id FROM core.personas WHERE NOT is_archived"
        data = await self.query_all(query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="uid", value=self.user_uid(e["id"]))
                ]
            ) for e in data
        ]

    async def get_users(self, dns: List[DN]) -> LDAPObjectMap:
        """Get the users specified by dn.

        The relevant RFCs are
        https://datatracker.ietf.org/doc/html/rfc2798 (defining inetOrgPerson)
        https://datatracker.ietf.org/doc/html/rfc4519 (defining additional attributes)
        """
        dn_to_persona_id = dict()
        for dn in dns:
            uid = self._dn_value(dn, attribute="uid")
            if uid is None:
                continue
            persona_id = self.user_id(uid)
            if persona_id is None:
                continue
            dn_to_persona_id[dn] = persona_id

        query = (
            "SELECT id, username, display_name, given_names, family_name, password_hash"
            " FROM core.personas WHERE id = ANY(%s) AND NOT is_archived")
        data = await self.query_all(query, (dn_to_persona_id.values(),))
        users = {e["id"]: e for e in data}

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
                #"memberOf": []  # TODO
            }
            ret[dn] = self._to_bytes(ldap_user)
        return ret

    ##########
    # groups #
    ##########

    @property
    def groups_dn(self) -> str:
        return f"ou=groups,{self.cde_dn}"

    #
    # status
    #

    @property
    def status_groups_dn(self) -> str:
        return f"ou=status,{self.groups_dn}"

    @staticmethod
    def status_group_cn(name: str) -> str:
        return name

    def status_group_name(self, cn: str) -> Optional[str]:
        return cn if cn in self.STATUS_GROUPS else None

    def status_group_dn(self, name: str) -> str:
        return f"cn={self.status_group_cn(name)},{self.status_groups_dn}"

    def is_status_group_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.status_groups_dn, "cn")

    STATUS_GROUPS = {
        "is_active": "Aktive Nutzer.",
        "is_member": "Nutzer, die aktuell Mitglied im CdE sind.",
        "is_searchable": "Nutzer, die aktuell Mitglied im CdE und und in der Datenbank suchbar sind.",
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

    async def list_status_groups(self) -> List[RDN]:
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.status_group_cn(name))
                ]
            ) for name in self.STATUS_GROUPS
        ]

    async def get_status_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_name = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            name = self.status_group_name(cn)
            if name is None:
                continue
            dn_to_name[dn] = name

        # since we have only a small group of status groups, we query them one by one
        ret = dict()
        for dn, name in dn_to_name.items():
            if name not in self.STATUS_GROUPS:
                continue
            if name == "is_searchable":
                condition = "is_member AND is_searchable"
            else:
                condition = name
            query = f"SELECT id FROM core.personas WHERE {condition}"
            members = await self.query_all(query, [])
            group = {
                b"cn": [self.status_group_cn(name)],
                b"objectClass": ["groupOfUniqueNames"],
                b"description": [self.STATUS_GROUPS[name]],
                b"uniqueMember": [self.user_dn(e["id"]) for e in members]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # presiders
    #

    @property
    def presider_groups_dn(self) -> str:
        return f"ou=assembly-presiders,{self.groups_dn}"

    @staticmethod
    def presider_group_cn(assembly_id: int) -> str:
        return f"presiders-{assembly_id}"

    def presider_group_id(self, cn: str) -> Optional[int]:
        return self._extract_id(cn, prefix="presiders-")

    def presider_group_dn(self, assembly_id: int) -> str:
        return f"cn={self.presider_group_cn(assembly_id)},{self.presider_groups_dn}"

    def is_presider_group_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.presider_groups_dn, "cn")

    async def list_assembly_presider_groups(self) -> List[RDN]:
        query = "SELECT id FROM assembly.assemblies"
        data = await self.query_all(query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.presider_group_cn(e["id"]))
                ]
            ) for e in data
        ]

    async def get_assembly_presider_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_assembly_id = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            assembly_id = self.presider_group_id(cn)
            if assembly_id is None:
                continue
            dn_to_assembly_id[dn] = assembly_id

        query = ("SELECT persona_id, assembly_id FROM assembly.presiders"
                 " WHERE assembly_id = ANY(%s)")
        data = await self.query_all(query, (dn_to_assembly_id.values(),))
        presiders = defaultdict(list)
        for e in data:
            presiders[e["assembly_id"]].append(e["persona_id"])
        query = "SELECT id, title, shortname FROM assembly.assemblies WHERE id = ANY(%s)"
        data = await self.query_all(query, (dn_to_assembly_id.values(),))
        assemblies = {e["id"]: e for e in data}

        ret = dict()
        for dn, assembly_id in dn_to_assembly_id.items():
            if assembly_id not in assemblies:
                continue
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [self.presider_group_cn(assembly_id)],
                b"description": [f"{assemblies[assembly_id]['title']} ({assemblies[assembly_id]['shortname']})"],
                b"uniqueMember": [self.user_dn(e) for e in presiders[assembly_id]]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # orgas
    #

    @property
    def orga_groups_dn(self) -> str:
        return f"ou=event-orgas,{self.groups_dn}"

    @staticmethod
    def orga_group_cn(event_id: int) -> str:
        return f"orgas-{event_id}"

    def orga_group_id(self, cn: str) -> Optional[int]:
        return self._extract_id(cn, prefix="orgas-")

    def orga_group_dn(self, event_id: int) -> str:
        return f"cn={self.orga_group_cn(event_id)},{self.orga_groups_dn}"

    def is_orga_group_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.orga_groups_dn, "cn")

    async def list_event_orga_groups(self) -> List[RDN]:
        query = "SELECT id FROM event.events"
        data = await self.query_all(query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.orga_group_cn(e["id"]))
                ]
            ) for e in data
        ]

    async def get_event_orga_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_event_id = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            event_id = self.orga_group_id(cn)
            if event_id is None:
                continue
            dn_to_event_id[dn] = event_id

        query = "SELECT persona_id, event_id FROM event.orgas WHERE event_id = ANY(%s)"
        data = await self.query_all(query, (dn_to_event_id.values(),))
        orgas = defaultdict(list)
        for e in data:
            orgas[e["event_id"]].append(e["persona_id"])
        query = "SELECT id, title, shortname FROM event.events WHERE id = ANY(%s)"
        data = await self.query_all(query, (dn_to_event_id.values(),))
        events = {e["id"]: e for e in data}

        ret = dict()
        for dn, event_id in dn_to_event_id.items():
            if event_id not in events:
                continue
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [self.orga_group_cn(event_id)],
                b"description": [f"{events[event_id]['title']} ({events[event_id]['shortname']})"],
                b"uniqueMember": [self.user_dn(e) for e in orgas[event_id]]
            }
            ret[dn] = self._to_bytes(group)
        return ret

    #
    # moderators
    #

    @property
    def moderator_groups_dn(self) -> str:
        return f"ou=ml-moderators,{self.groups_dn}"

    @staticmethod
    def moderator_group_cn(address: str) -> str:
        return address.replace("@", "-owner@")

    @staticmethod
    def moderator_group_address(cn: str) -> Optional[str]:
        """Parse the regular address from an owner mailinglist address."""
        if match := re.match(r"(?P<local_part>[\w.-]*)-owner@(?P<domain>[\w.-]*)", cn):
            return f"{match.group('local_part')}@{match.group('domain')}"
        else:
            return None

    def moderator_group_dn(self, address: str) -> str:
        return f"cn={self.moderator_group_cn(address)},{self.moderator_groups_dn}"

    def is_moderator_group_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.moderator_groups_dn, "cn")

    async def list_ml_moderator_groups(self) -> List[RDN]:
        query = "SELECT address FROM ml.mailinglists"
        data = await self.query_all(query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.moderator_group_cn(e["address"]))
                ]
            ) for e in data
        ]

    async def get_ml_moderator_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            address = self.moderator_group_address(cn)
            if address is None:
                continue
            dn_to_address[dn] = address

        query = ("SELECT persona_id, address FROM ml.moderators, ml.mailinglists"
                 " WHERE ml.mailinglists.id = ml.moderators.mailinglist_id"
                 " AND address = ANY(%s)")
        data = await self.query_all(query, (dn_to_address.values(),))
        moderators = defaultdict(list)
        for e in data:
            moderators[e["address"]].append(e["persona_id"])
        query = ("SELECT address, title FROM ml.mailinglists WHERE address = ANY(%s)")
        data = await self.query_all(query, (dn_to_address.values(),))
        mls = {e["address"]: e for e in data}

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

    @property
    def subscriber_groups_dn(self) -> str:
        return f"ou=ml-subscribers,{self.groups_dn}"

    @staticmethod
    def subscriber_group_cn(address: str) -> str:
        return address

    @staticmethod
    def subscriber_group_address(cn: str) -> Optional[str]:
        return cn

    def subscriber_group_dn(self, address: str) -> str:
        return f"cn={self.subscriber_group_cn(address)},{self.subscriber_groups_dn}"

    def is_subscriber_group_dn(self, dn: DN) -> bool:
        return self._is_entry_dn(dn, self.subscriber_groups_dn, "cn")

    async def list_ml_subscriber_groups(self) -> List[RDN]:
        query = "SELECT address FROM ml.mailinglists"
        data = await self.query_all(query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.subscriber_group_cn(e["address"]))
                ]
            ) for e in data
        ]

    async def get_ml_subscriber_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            address = self.subscriber_group_address(cn)
            if address is None:
                continue
            dn_to_address[dn] = address

        query = ("SELECT persona_id, address FROM ml.subscription_states, ml.mailinglists"
                 " WHERE ml.mailinglists.id = ml.subscription_states.mailinglist_id"
                 " AND subscription_state = ANY(%s) AND address = ANY(%s)")
        states = SubscriptionState.subscribing_states()
        data = await self.query_all(query, (states, dn_to_address.values(),))
        subscribers = defaultdict(list)
        for e in data:
            subscribers[e["address"]].append(e["persona_id"])
        query = ("SELECT address, title FROM ml.mailinglists WHERE address = ANY(%s)")
        data = await self.query_all(query, (dn_to_address.values(),))
        mls = {e["address"]: e for e in data}

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
