from typing import Callable, Dict, List, TypedDict

from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, RelativeDistinguishedName as RDN,
)

##############
# Attributes #
##############

Attributes = Dict[str, List[str]]

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
        "get_entities": get_duas,
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
