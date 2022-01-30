import logging
from typing import Callable, Dict, List, TypedDict

from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, RelativeDistinguishedName as RDN,
)

from cdedb.common import unwrap
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import ConnectionContainer, connection_pool_factory
from cdedb.database.query import QueryMixin

##############
# Attributes #
##############

Attributes = Dict[str, List[str]]


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
    def db_key(dn: DN):
        rdn = dn.split()[0]
        attribute_value = unwrap(rdn.split())
        return attribute_value.value

    def get_entities(self, query: str, dns: List[DN]) -> Dict[DN, Attributes]:
        """Retrieve all dns with the specified query and format them accordingly.

        Each query result is converted in an attributes' dict, where the name of the
        attribute is the column name of the query.
        The attribute selecting the entities in the WHERE clause must be the same
        attribute used in the DN of the entry.
        """
        # TODO check that this is equal for all dns
        attribute_key = dns[0].split()[0].split()[0].attributeType
        dn_to_key = {dn: self.db_key(dn) for dn in dns}
        data = self.query_all(self.rs, query, (dn_to_key.values(),))
        # the attributes of each entry have to be a list of strings
        entries = {
            e[attribute_key]: {
                key: [str(value)] for key, value in e.items()
            } for e in data
        }
        return {dn: entries.get(dn_to_key.get(dn)) for dn in dns}

    def get_duas(self, dns: List[DN]) -> Dict[DN, Attributes]:
        query = "SELECT cn, password_hash FROM ldap.duas WHERE cn = ANY(%s)"
        entities = self.get_entities(query, dns)
        # add the object class to the entities
        entities = {dn: dict(**entity, objectclass=["person"])
                    for dn, entity in entities.items()}
        return entities


tree = LDAPsqlTree()


#
# duas
#


def get_duas(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


#
# users
#


def get_users(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


#
# groups
#


def get_status_groups(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


def get_assembly_presider_groups(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


def get_event_orga_groups(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


def get_ml_moderator_groups(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


def get_ml_subscriber_groups(dns: List[DN]) -> Dict[DN, Attributes]:
    pass


#################
# List Entities #
#################

#
# duas
#


def list_duas() -> List[RDN]:
    query = "SELECT cn FROM ldap.duas"
    dua_rdns = ...
    return dua_rdns


#
# users
#


def list_users() -> List[RDN]:
    pass


#
# groups
#


def list_assembly_presider_groups() -> List[RDN]:
    pass


def list_event_orga_groups() -> List[RDN]:
    pass


def list_ml_moderator_groups() -> List[RDN]:
    pass


def list_ml_subscriber_groups() -> List[RDN]:
    pass


def list_status_groups() -> List[RDN]:
    pass


#############
# LDAP Tree #
#############

# contains all non-leaf ldap entries, mapping their DN to their attributes
LDAP_BRANCHES: Dict[str, Attributes] = {
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


class LdapLeaf(TypedDict):
    get_entities: Callable[[List[DN]], Dict[DN, Attributes]]
    list_entities: Callable[[], List[RDN]]


# contains information about all ldap leaf entries. Maps their _parent_ DN to functions
# for getting the attributes of a given list of entities and listing all entities.
LDAP_LEAFS: Dict[str, LdapLeaf] = {
    "ou=duas,dc=cde-ev,dc=de": {
        "get_entities": tree.get_duas,
        "list_entities": list_duas,
    },
    "ou=users,dc=cde-ev,dc=de": {
        "get_entities": get_users,
        "list_entities": list_users,
    },
    "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de": {
        "get_entities": get_assembly_presider_groups,
        "list_entities": list_assembly_presider_groups,
    },
    "ou=event-orgas,ou=groups,dc=cde-ev,dc=de": {
        "get_entities": get_event_orga_groups,
        "list_entities": list_event_orga_groups,
    },
    "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de": {
        "get_entities": get_ml_moderator_groups,
        "list_entities": list_ml_moderator_groups,
    },
    "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de": {
        "get_entities": get_ml_subscriber_groups,
        "list_entities": list_ml_subscriber_groups,
    },
    "ou=status,ou=groups,dc=cde-ev,dc=de": {
        "get_entities": get_status_groups,
        "list_entities": list_status_groups,
    }
}
