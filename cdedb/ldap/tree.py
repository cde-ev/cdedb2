import logging
import pathlib
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict, Union

from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, LDAPAttributeTypeAndValue as ATV,
    RelativeDistinguishedName as RDN,
)

from cdedb.common import unwrap
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import ConnectionContainer, connection_pool_factory
from cdedb.database.constants import SubscriptionState
from cdedb.database.query import QueryMixin
from cdedb.ldap.schema import SchemaDescription

LDAPObject = Dict[bytes, List[bytes]]
LDAPObjectMap = Dict[DN, LDAPObject]


class LdapLeaf(TypedDict):
    get_entities: Callable[[List[DN]], LDAPObjectMap]
    list_entities: Callable[[], List[RDN]]


class LDAPsqlTree(QueryMixin):
    """Provide the interface between ldap and database."""
    def __init__(self) -> None:
        self.conf = Config()
        secrets = SecretsConfig()
        self.connection_pool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], ["cdb_admin"],
            secrets, self.conf["DB_HOST"], self.conf["DB_PORT"])
        self.logger = logging.getLogger(__name__)
        # load the ldap schemas which are supported
        self.schema = self.load_schemas("core", "cosine", "inetorgperson")
        super().__init__(self.logger)

    @property
    def rs(self) -> ConnectionContainer:
        conn = self.connection_pool["cdb_admin"]
        rs = ConnectionContainer()
        rs.conn = rs._conn = conn
        return rs

    @staticmethod
    def _dn_value(dn: DN, attribute: str) -> Optional[str]:
        """Retrieve the value of the RDN matching the given attribute type."""
        rdn = dn.split()[0]
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
    def _to_bytes(self, object: Union[Dict[Any, Any], List[Any], str, int, bytes]
                  ) -> Union[Dict[bytes, Any], List[Any], bytes]:
        if isinstance(object, dict):
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
            with open(pathlib.Path(f"/cdedb2/cdedb/ldap/schema/{schema}.schema")) as f:
                data.append(f.read())

        # punch all files together to create a single schema object
        file = "\n\n\n".join(data)
        return SchemaDescription(file)

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
        query = "SELECT cn FROM ldap.duas"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=self.dua_cn(e["cn"]))
                ]
            ) for e in data
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

        query = "SELECT cn, password_hash FROM ldap.duas WHERE cn = ANY(%s)"
        data = self.query_all(self.rs, query, (dn_to_name.values(),))
        duas = {e["cn"]: e for e in data}

        ret = dict()
        for dn, name in dn_to_name.items():
            if name not in duas:
                continue
            dua = {
                b"objectClass": ["person", "simpleSecurityObject"],
                b"cn": [self.dua_cn(name)],
                b"userPassword": [duas[name]["password_hash"]]
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

    async def list_users(self) -> List[RDN]:
        query = "SELECT id FROM core.personas"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="uid", value=self.user_uid(e["id"]))
                ]
            ) for e in data
        ]

    async def get_users(self, dns: List[DN]) -> LDAPObjectMap:
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
            " FROM core.personas WHERE id = ANY(%s)")
        data = self.query_all(self.rs, query, (dn_to_persona_id.values(),))
        users = {e["id"]: e for e in data}

        ret = dict()
        for dn, persona_id in dn_to_persona_id.items():
            if persona_id not in users:
                continue
            user = users[persona_id]
            # mimik the implementation of frontend.common.make_persona_name
            if user["display_name"] and user["display_name"] in user["given_names"]:
                display_name = user["display_name"]
            else:
                display_name = user["given_names"]
            ldap_user = {
                b"objectClass": ["inetOrgPerson"],
                b"cn": [f"{user['given_names']} {user['family_name']}"],
                b"sn": [user['family_name'] or ""],
                b"displayName": [f"{display_name} {user['family_name']}"],
                b"givenName": [user['given_names'] or ""],
                b"mail": [user['username'] or ""],
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
            members = self.query_all(self.rs, query, [])
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
        data = self.query_all(self.rs, query, [])
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
        data = self.query_all(self.rs, query, (dn_to_assembly_id.values(),))
        presiders = defaultdict(list)
        for e in data:
            presiders[e["assembly_id"]].append(e["persona_id"])
        query = "SELECT id, title, shortname FROM assembly.assemblies WHERE id = ANY(%s)"
        data = self.query_all(self.rs, query, (dn_to_assembly_id.values(),))
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
        data = self.query_all(self.rs, query, [])
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
        data = self.query_all(self.rs, query, (dn_to_event_id.values(),))
        orgas = defaultdict(list)
        for e in data:
            orgas[e["event_id"]].append(e["persona_id"])
        query = "SELECT id, title, shortname FROM event.events WHERE id = ANY(%s)"
        data = self.query_all(self.rs, query, (dn_to_event_id.values(),))
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
        data = self.query_all(self.rs, query, [])
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
        data = self.query_all(self.rs, query, (dn_to_address.values(),))
        moderators = defaultdict(list)
        for e in data:
            moderators[e["address"]].append(e["persona_id"])
        query = ("SELECT address, title FROM ml.mailinglists WHERE address = ANY(%s)")
        data = self.query_all(self.rs, query, (dn_to_address.values(),))
        mls = {e["address"]: e for e in data}

        ret = dict()
        for dn, address in dn_to_address.items():
            if address not in mls:
                continue
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
        data = self.query_all(self.rs, query, [])
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
        data = self.query_all(self.rs, query, (states, dn_to_address.values(),))
        subscribers = defaultdict(list)
        for e in data:
            subscribers[e["address"]].append(e["persona_id"])
        query = ("SELECT address, title FROM ml.mailinglists WHERE address = ANY(%s)")
        data = self.query_all(self.rs, query, (dn_to_address.values(),))
        mls = {e["address"]: e for e in data}

        ret = dict()
        for dn, address in dn_to_address.items():
            if address not in mls:
                continue
            group = {
                b"objectClass": ["groupOfUniqueNames"],
                b"cn": [self.subscriber_group_cn(address)],
                b"description": [f"{mls[address]['title']} <{address}>"],
                b"uniqueMember": [self.user_dn(e) for e in subscribers[address]]
            }
            ret[dn] = self._to_bytes(group)
        return ret
