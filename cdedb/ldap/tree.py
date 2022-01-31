import logging
from typing import Callable, Dict, List, TypedDict

from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, RelativeDistinguishedName as RDN,
)

from cdedb.common import unwrap
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import ConnectionContainer, connection_pool_factory
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
    def _db_key(dn: DN):
        rdn = dn.split()[0]
        attribute_value = unwrap(rdn.split())
        return attribute_value.value

    def _get_entities(self, query: str, dns: List[DN]) -> LDAPObjectMap:
        """Retrieve all dns with the specified query and format them accordingly.

        Each query result is converted in an attributes' dict, where the name of the
        attribute is the column name of the query.
        The attribute selecting the entities in the WHERE clause must be the same
        attribute used in the DN of the entry.
        """
        # TODO check that this is equal for all dns
        attribute_key = dns[0].split()[0].split()[0].attributeType
        dn_to_key = {dn: self._db_key(dn) for dn in dns}
        data = self.query_all(self.rs, query, (dn_to_key.values(),))
        # the attributes of each entry have to be a list of strings
        entries = {
            e[attribute_key]: {
                key: [str(value)] for key, value in e.items()
            } for e in data
        }
        return {dn: entries.get(dn_to_key.get(dn)) for dn in dns}

    def get_duas(self, dns: List[DN]) -> LDAPObjectMap:
        query = "SELECT cn, password_hash FROM ldap.duas WHERE cn = ANY(%s)"
        entities = self._get_entities(query, dns)
        # add the object class to the entities
        entities = {dn: dict(**entity, objectclass=["person"])
                    for dn, entity in entities.items()}
        return entities

    def get_users(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def get_status_groups(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def get_assembly_presider_groups(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def get_event_orga_groups(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def get_ml_moderator_groups(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def get_ml_subscriber_groups(self, dns: List[DN]) -> LDAPObjectMap:
        pass

    def list_duas(self) -> List[RDN]:
        query = "SELECT cn FROM ldap.duas"
        dua_rdns = ...
        return dua_rdns

    def list_users(self) -> List[RDN]:
        pass

    def list_assembly_presider_groups(self) -> List[RDN]:
        pass

    def list_event_orga_groups(self) -> List[RDN]:
        pass

    def list_ml_moderator_groups(self) -> List[RDN]:
        pass

    def list_ml_subscriber_groups(self) -> List[RDN]:
        pass

    def list_status_groups(self) -> List[RDN]:
        pass

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
