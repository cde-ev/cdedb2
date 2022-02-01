import logging
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, TypedDict

from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, LDAPAttributeTypeAndValue as ATV,
    RelativeDistinguishedName as RDN,
)

from cdedb.common import unwrap
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import ConnectionContainer, connection_pool_factory
from cdedb.database.constants import SubscriptionState
from cdedb.database.query import QueryMixin

LDAPObject = Dict[str, List[str]]
LDAPObjectMap = Dict[DN, LDAPObject]


class LdapLeaf(TypedDict):
    get_entities: Callable[[List[DN]], LDAPObjectMap]
    list_entities: Callable[[], List[RDN]]


class LDAPsqlTree(QueryMixin):
    """Provide the interface between ldap and database."""
    def __init__(self):
        self.conf = Config()
        secrets = SecretsConfig()
        self.rs = ConnectionContainer()
        conn = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], ["cdb_admin"],
            secrets, self.conf["DB_HOST"], self.conf["DB_PORT"])["cdb_admin"]
        self.rs.conn = self.rs._conn = conn
        self.logger = logging.getLogger(__name__)
        super().__init__(self.logger)

    @staticmethod
    def _user_dn(persona_id: int) -> str:
        """Central point to create the user dn from a given user id."""
        return f"uid={persona_id},ou=users,dc=cde-ev,dc=de"

    @staticmethod
    def _dn_value(dn: DN, attribute: str) -> Optional[str]:
        """Retrieve the value of the RDN matching the given attribute type."""
        rdn = dn.split()[0]
        attribute_value = unwrap(rdn.split())
        if attribute_value.attributeType == attribute:
            return attribute_value.value
        else:
            return None

    def get_duas(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_cn = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            dn_to_cn[dn] = cn

        query = "SELECT cn, password_hash FROM ldap.duas WHERE cn = ANY(%s)"
        data = self.query_all(self.rs, query, (dn_to_cn.values(),))
        duas = {e["cn"]: e for e in data}

        ret = dict()
        for dn, cn in dn_to_cn.items():
            if cn not in duas:
                continue
            dua = {
                "objectclass": ["person"],
                "cn": [cn],
                "userPassword": [duas[cn]["password_hash"]]
            }
            ret[dn] = dua
        return ret

    def get_users(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_persona_id = dict()
        for dn in dns:
            uid = self._dn_value(dn, attribute="uid")
            if uid is None:
                continue
            # mainly to check that the uid is a base 10 integer
            persona_id = self.extract_id(uid, prefix="")
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
                "objectclass": ["inetOrgPerson"],
                "cn": [f"{user['given_names']} {user['family_name']}"],
                "sn": [user['family_name'] or ""],
                "displayName": [f"{display_name} {user['family_name']}"],
                "givenNames": [user['given_names'] or ""],
                "mail": [user['username'] or ""],
                "uid": [persona_id],
                "userPassword": [user['password_hash']],
                "memberOf": []  # TODO
            }
            ret[dn] = ldap_user
        return ret

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

    def get_status_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_cn = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            dn_to_cn[dn] = cn

        # since we have only a small group of status groups, we query them one by one
        ret = dict()
        for dn, cn in dn_to_cn.items():
            if cn not in self.STATUS_GROUPS:
                continue
            if cn == "is_searchable":
                condition = "is_member AND is_searchable"
            else:
                condition = cn
            query = f"SELECT id FROM core.personas WHERE {condition}"
            members = self.query_all(self.rs, query, [])
            group = {
                "cn": [cn],
                "objectclass": ["groupOfUniqueNames"],
                "description": [self.STATUS_GROUPS[cn]],
                "uniqueMember": [self._user_dn(e["id"]) for e in members]
            }
            ret[dn] = group
        return ret

    @staticmethod
    def extract_id(cn: str, prefix: str) -> Optional[int]:
        """Extract the id from a cn by stripping the prefix.

        This especially checks that the id is a valid base 10 integer.
        """
        if match := re.match(f"^{prefix}(?P<id>\d+)$", cn):
            return int(match.group("id"))
        else:
            return None

    def get_assembly_presider_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_assembly_id = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            assembly_id = self.extract_id(cn, prefix="presiders-")
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
            if assembly_id not in presiders:
                continue
            group = {
                "objectclass": ["groupOfUniqueNames"],
                "cn": [f"presiders-{assembly_id}"],
                "description": [f"{assemblies[assembly_id]['title']} ({assemblies[assembly_id]['shortname']})"],
                "uniqueMember": [self._user_dn(e) for e in presiders[assembly_id]]
            }
            ret[dn] = group
        return ret

    def get_event_orga_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_event_id = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            event_id = self.extract_id(cn, prefix="orgas-")
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
            if event_id not in orgas:
                continue
            group = {
                "objectclass": ["groupOfUniqueNames"],
                "cn": [f"orgas-{event_id}"],
                "description": [f"{events[event_id]['title']} ({events[event_id]['shortname']})"],
                "uniqueMember": [self._user_dn(e) for e in orgas[event_id]]
            }
            ret[dn] = group
        return ret

    @staticmethod
    def extract_address(owner_address: str) -> Optional[str]:
        expression = r"(?P<local_part>[\w.-]*)-owner@(?P<domain>[\w.-]*)"
        if match := re.match(expression, owner_address):
            return f"{match.group('local_part')}@{match.group('domain')}"
        else:
            return None

    def get_ml_moderator_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            address = self.extract_address(cn)
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
            if address not in moderators:
                continue
            group = {
                "objectclass": ["groupOfUniqueNames"],
                "cn": [address.replace("@", "-owner@")],
                "description": [f"{mls[address]['title']} <{address.replace('@', '-owner@')}>"],
                "uniqueMember": [self._user_dn(e) for e in moderators[address]]
            }
            ret[dn] = group
        return ret

    def get_ml_subscriber_groups(self, dns: List[DN]) -> LDAPObjectMap:
        dn_to_address = dict()
        for dn in dns:
            cn = self._dn_value(dn, attribute="cn")
            if cn is None:
                continue
            dn_to_address[dn] = cn

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
            if address not in subscribers:
                continue
            group = {
                "objectclass": ["groupOfUniqueNames"],
                "cn": [address],
                "description": [f"{mls[address]['title']} <{address}>"],
                "uniqueMember": [self._user_dn(e) for e in subscribers[address]]
            }
            ret[dn] = group
        return ret

    def list_duas(self) -> List[RDN]:
        query = "SELECT cn FROM ldap.duas"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=e["cn"])
                ]
            ) for e in data
        ]

    def list_users(self) -> List[RDN]:
        query = "SELECT id FROM core.personas"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="uid", value=str(e["id"]))
                ]
            ) for e in data
        ]

    def list_assembly_presider_groups(self) -> List[RDN]:
        query = "SELECT assembly_id FROM assembly.presiders"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=f"presiders-{e['assembly_id']}")
                ]
            ) for e in data
        ]

    def list_event_orga_groups(self) -> List[RDN]:
        query = "SELECT event_id FROM event.orgas"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=f"orgas-{e['event_id']}")
                ]
            ) for e in data
        ]

    def list_ml_moderator_groups(self) -> List[RDN]:
        query = "SELECT address FROM ml.mailinglists"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=e["address"])
                ]
            ) for e in data
        ]

    def list_ml_subscriber_groups(self) -> List[RDN]:
        query = "SELECT address FROM ml.mailinglists"
        data = self.query_all(self.rs, query, [])
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=e["address"].replace("@", "-owner@"))
                ]
            ) for e in data
        ]

    def list_status_groups(self) -> List[RDN]:
        return [
            RDN(
                attributeTypesAndValues=[
                    ATV(attributeType="cn", value=group)
                ]
            ) for group in self.STATUS_GROUPS
        ]

    @property
    def branches(self) -> Dict[str, LDAPObject]:
        """All non-leaf ldap entries, mapping their DN to their attributes."""
        return {
            "dc=de": {
                "objectClass": ["dcObject", "top"],
            },
            "dc=cde-ev,dc=de": {
                "objectClass": ["dcObject", "organization"],
                "o": ["CdE e.V."],
            },
            "ou=duas,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Directory User Agents"]
            },
            "ou=users,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Users"]
            },
            "ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Groups"]
            },
            "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Assembly Presiders"]
            },
            "ou=event-orgas,ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Event Orgas"]
            },
            "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Mailinglists Moderators"]
            },
            "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Mailinglists Subscribers"]
            },
            "ou=status,ou=groups,dc=cde-ev,dc=de": {
                "objectClass": ["organizationalUnit"],
                "o": ["Status"]
            }
        }

    @property
    def leafs(self) -> Dict[str, LdapLeaf]:
        """All information about the leaf entries.

        Maps their _parent_ DN to functions for getting the attributes of a given list
        of entities and listing all entities.
        """
        return {
            "ou=duas,dc=cde-ev,dc=de": {
                "get_entities": self.get_duas,
                "list_entities": self.list_duas,
            },
            "ou=users,dc=cde-ev,dc=de": {
                "get_entities": self.get_users,
                "list_entities": self.list_users,
            },
            "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de": {
                "get_entities": self.get_assembly_presider_groups,
                "list_entities": self.list_assembly_presider_groups,
            },
            "ou=event-orgas,ou=groups,dc=cde-ev,dc=de": {
                "get_entities": self.get_event_orga_groups,
                "list_entities": self.list_event_orga_groups,
            },
            "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de": {
                "get_entities": self.get_ml_moderator_groups,
                "list_entities": self.list_ml_moderator_groups,
            },
            "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de": {
                "get_entities": self.get_ml_subscriber_groups,
                "list_entities": self.list_ml_subscriber_groups,
            },
            "ou=status,ou=groups,dc=cde-ev,dc=de": {
                "get_entities": self.get_status_groups,
                "list_entities": self.list_status_groups,
            }
        }
