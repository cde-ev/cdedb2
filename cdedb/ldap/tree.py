from typing import Callable, Dict, List, NewType, Tuple, Union

DN = NewType("DN", str)
RDN = NewType("RDN", str)


##############
# Attributes #
##############

Attributes = Dict[str, List[str]]
AttributesCallback = Callable[[RDN], Attributes]

#
# domain components
#

DC_DE: Attributes = {
    "objectClass": ["dcObject", "top"],
}

DC_CDE: Attributes = {
    "objectClass": ["dcObject", "organization"],
    "o": ["CdE e.V."],
}

#
# organizational units
#

OU_DUA: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Directory User Agents"]
}

OU_GROUPS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Groups"]
}

OU_USERS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Users"]
}

OU_STATUS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Status"]
}

OU_ASSEMBLY_PRESIDERS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Assembly Presiders"]
}

OU_EVENT_ORGAS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Event Orgas"]
}

OU_ML_MODERATORS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Mailinglists Moderators"]
}

OU_ML_SUBSCRIBERS: Attributes = {
    "objectClass": ["organizationalUnit"],
    "o": ["Mailinglists Subscribers"]
}

#
# groups
#


def get_status_group_attributes(rdn: RDN) -> Attributes:
    pass


def get_assembly_presider_group_attributes(rdn: RDN) -> Attributes:
    pass


def get_event_orga_group_attributes(rdn: RDN) -> Attributes:
    pass


def get_ml_moderator_group_attributes(rdn: RDN) -> Attributes:
    pass


def get_ml_subscriber_group_attributes(rdn: RDN) -> Attributes:
    pass

#
# duas
#


def get_dua_attributes(rdn: RDN) -> Attributes:
    pass

#
# users
#


def get_user_attributes(rdn: RDN) -> Attributes:
    pass


############
# Children #
############

Children = List[RDN]
ChildrenCallback = Callable[[], Children]


def get_duas() -> List[RDN]:
    query = "SELECT cn FROM ldap.duas"
    dua_rdns = ...
    return dua_rdns


def get_assembly_presider_groups() -> List[RDN]:
    pass


def get_event_orga_groups() -> List[RDN]:
    pass


def get_ml_moderator_groups() -> List[RDN]:
    pass


def get_ml_subscriber_groups() -> List[RDN]:
    pass


def get_status_groups() -> List[RDN]:
    pass


def get_users() -> List[RDN]:
    pass


#############
# LDAP Tree #
#############

class LDAPTreeLeaf:
    """A class to store the functions to handle leafs of the LDAP Tree.

    Since there are n leafs of the same kind, this is a bit complicated.
    """
    def __init__(self, entities: ChildrenCallback, attributes: AttributesCallback):
        """Create a new LDAPTreeLeaf.

        :param entities: A callback returning _all_ entities of this kind of leaf.
        :param attributes: A callback returning all attributes of _one_ given entity.
        """
        self.attributes = attributes
        self.entities = entities


DUAS = LDAPTreeLeaf(get_duas, get_dua_attributes)
ASSEMBLY_PRESIDER_GROUPS = LDAPTreeLeaf(
    get_assembly_presider_groups, get_assembly_presider_group_attributes)
EVENT_ORGA_GROUPS = LDAPTreeLeaf(get_event_orga_groups, get_event_orga_group_attributes)
ML_MODERATOR_GROUPS = LDAPTreeLeaf(
    get_ml_moderator_groups, get_ml_moderator_group_attributes)
ML_SUBSCRIBER_GROUPS = LDAPTreeLeaf(
    get_ml_subscriber_groups, get_ml_subscriber_group_attributes)
STATUS_GROUPS = LDAPTreeLeaf(get_status_groups, get_status_group_attributes)
USERS = LDAPTreeLeaf(get_users, get_user_attributes)


# The actual ldap tree, holding all structural information. This includes:
# - What is the parent and are the children of an entry (from root to leaf)?
# - What are the attributes of an entry (from root to leaf)?
#
# The Tree can be read per level:
# Each level is a Dict, mapping the entry's RDN to a Tuple, containing
# - the Attributes of the entry
# - the next tree level (which is either another Tree, or a LDAPTreeLeaf)
Tree = Dict[str, Tuple[Attributes, Union["Tree", LDAPTreeLeaf]]]

LDAP_TREE: Tree = {
    "dc=de": (DC_DE, {
        "dc=cde-ev": (DC_CDE, {
            "ou=dua": (OU_DUA, DUAS),
            "ou=groups": (OU_GROUPS, {
                "ou=assembly-presiders": (OU_ASSEMBLY_PRESIDERS, ASSEMBLY_PRESIDER_GROUPS),
                "ou=event-orgas": (OU_EVENT_ORGAS, EVENT_ORGA_GROUPS),
                "ou=ml-moderators": (OU_ML_MODERATORS, ML_MODERATOR_GROUPS),
                "ou=ml-subscribers": (OU_ML_SUBSCRIBERS, ML_SUBSCRIBER_GROUPS),
                "ou=status": (OU_STATUS, STATUS_GROUPS),
            }),
            "ou=users": (OU_USERS, USERS),
        })
    })
}
