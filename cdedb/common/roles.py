#!/usr/bin/env python3

"""Everything regarding the role model of the CdEDB."""

import collections
from typing import TYPE_CHECKING, Any, Dict, List, Set

from cdedb.common.fields import REALM_SPECIFIC_GENESIS_FIELDS
from cdedb.common.n_ import n_

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = Dict[str, Any]

# A set of roles a user may have.
Role = str

# A set of realms a persona belongs to.
Realm = str

# Admin views a user may activate/deactivate.
AdminView = str


def extract_roles(session: CdEDBObject, introspection_only: bool = False
                  ) -> Set[Role]:
    """Associate some roles to a data set.

    The data contains the relevant portion of attributes from the
    core.personas table. We have some more logic than simply grabbing
    the flags from the dict like only allowing admin privileges in a
    realm if access to the realm is already granted.

    Note that this also works on non-personas (i.e. dicts of is_* flags).

    :param introspection_only: If True the result should only be used to
      take an extrinsic look on a persona and not the determine the privilege
      level of the data set passed.
    """
    ret = {"anonymous"}
    if session['is_active'] or introspection_only:
        ret.add("persona")
    elif not introspection_only:
        return ret
    realms = {"cde", "event", "ml", "assembly"}
    for realm in realms:
        if session["is_{}_realm".format(realm)]:
            ret.add(realm)
            if session.get("is_{}_admin".format(realm)):
                ret.add("{}_admin".format(realm))
    if "cde" in ret:
        if session.get("is_core_admin"):
            ret.add("core_admin")
        if session.get("is_meta_admin"):
            ret.add("meta_admin")
        if session["is_member"]:
            ret.add("member")
            if session.get("is_searchable"):
                ret.add("searchable")
        if session.get("is_auditor"):
            ret.add("auditor")
    if "ml" in ret:
        if session.get("is_cdelokal_admin"):
            ret.add("cdelokal_admin")
    if "cde_admin" in ret:
        if session.get("is_finance_admin"):
            ret.add("finance_admin")
    return ret


# The following droids are exempt from lockdown to keep our infrastructure
# working
INFRASTRUCTURE_DROIDS: Set[str] = {'resolve'}


def droid_roles(identity: str) -> Set[Role]:
    """Resolve droid identity to a complete set of roles.

    Currently this is rather trivial, but could be more involved in the
    future if more API capabilities are added to the DB.

    :param identity: The name for the API functionality, e.g. ``resolve``.
    """
    ret = {'anonymous', 'droid', f'droid_{identity}'}
    if identity in INFRASTRUCTURE_DROIDS:
        ret.add('droid_infra')
    return ret


# The following dict defines the hierarchy of realms. This has direct impact on
# the admin privileges: An admin of a specific realm can only query and edit
# members of that realm, who are not member of another realm implying that
# realm.
#
# This defines an ordering on the realms making the realms a partially
# ordered set. Later we will use the notion of maximal elements of subsets,
# which are those which have nothing above them. To clarify this two examples:
#
# * in the set {'assembly', 'event', 'ml'} the elements 'assembly' and
#   'event' are maximal
#
# * in the set {'cde', 'assembly', 'event'} only 'cde' is maximal
#
# This dict is not evaluated recursively, so recursively implied realms must
# be added manually to make the implication transitive.
REALM_INHERITANCE: Dict[Realm, Set[Role]] = {
    'cde': {'event', 'assembly', 'ml'},
    'event': {'ml'},
    'assembly': {'ml'},
    'ml': set(),
}


def extract_realms(roles: Set[Role]) -> Set[Realm]:
    """Get the set of realms from a set of user roles.

    When checking admin privileges, we must often check, if the user's realms
    are a subset of some other set of realms. To help with this, this function
    helps with this task, by extracting only the actual realms from a user's
    set of roles.

    :param roles: All roles of a user
    :return: The realms the user is member of
    """
    return roles & REALM_INHERITANCE.keys()


def implied_realms(realm: Realm) -> Set[Realm]:
    """Get additional realms implied by membership in one realm

    :param realm: The name of the realm to check
    :return: A set of the names of all implied realms
    """
    return REALM_INHERITANCE.get(realm, set())


def implying_realms(realm: Realm) -> Set[Realm]:
    """Get all realms where membership implies the given realm.

    This can be used to determine the realms in which a user must *not* be to be
    listed in a specific realm or be edited by its admins.

    :param realm: The realm to search implying realms for
    :return: A set of all realms implying
    """
    return set(r for r, implied in REALM_INHERITANCE.items()
               if realm in implied)


def privilege_tier(roles: Set[Role], conjunctive: bool = False
                   ) -> List[Set[Role]]:
    """Required admin privilege relative to a persona (signified by its roles)

    Basically this answers the question: If a user has access to the passed
    realms, what kind of admin privilege does one need to perform an
    operation on the user?

    First we determine the relevant subset of the passed roles. These are
    the maximal elements according to the realm inheritance. These apex
    roles regulate the access.

    The answer now depends on whether the operation pertains to some
    specific realm (editing a user is the prime example here) or affects all
    realms (creating a user is the corresponding example). This distinction
    is controlled by the conjunctive parameter, if it is True the operation
    lies in the intersection of all realms.

    Note that core admins and meta admins are always allowed access.

    :returns: List of sets of admin roles. Any of these sets is sufficient.
    """
    # Get primary user realms (those, that don't imply other realms)
    relevant = roles & REALM_INHERITANCE.keys()
    if relevant:
        implied_roles = set.union(*(
            REALM_INHERITANCE.get(k, set()) for k in relevant))
        relevant -= implied_roles
    if conjunctive:
        ret = [{realm + "_admin" for realm in relevant},
               {"core_admin"}]
    else:
        ret = list({realm + "_admin"} for realm in relevant)
        ret += [{"core_admin"}]
    return ret


#: Creating a persona requires one to supply values for nearly all fields,
#: although in some realms they are meaningless. Here we provide a base skeleton
#: which can be used, so that these realms do not need to have any knowledge of
#: these fields.
PERSONA_DEFAULTS = {
    'is_cde_realm': False,
    'is_event_realm': False,
    'is_ml_realm': False,
    'is_assembly_realm': False,
    'is_member': False,
    'is_searchable': False,
    'is_active': True,
    'title': None,
    'name_supplement': None,
    'gender': None,
    'birthday': None,
    'telephone': None,
    'mobile': None,
    'address_supplement': None,
    'address': None,
    'postal_code': None,
    'location': None,
    'country': None,
    'birth_name': None,
    'address_supplement2': None,
    'address2': None,
    'postal_code2': None,
    'location2': None,
    'country2': None,
    'weblink': None,
    'specialisation': None,
    'affiliation': None,
    'timeline': None,
    'interests': None,
    'free_form': None,
    'trial_member': None,
    'decided_search': None,
    'bub_search': None,
    'foto': None,
    'paper_expuls': None,
}

#: Map of available privilege levels to those present in the SQL database
#: (where we have less differentiation for the sake of simplicity).
#:
#: This is an ordered dict, so that we can select the highest privilege
#: level.
if TYPE_CHECKING:
    role_map_type = collections.OrderedDict[Role, str]
else:
    role_map_type = collections.OrderedDict

#: List of all roles we consider admin roles. Changes in these roles must be
#: approved by two meta admins in total. Values are required roles.
#: Translation of keys is needed for the privilege change page.
ADMIN_KEYS = {
    n_("is_meta_admin"): "is_cde_realm",
    n_("is_core_admin"): "is_cde_realm",
    n_("is_cde_admin"): "is_cde_realm",
    n_("is_finance_admin"): "is_cde_admin",
    n_("is_event_admin"): "is_event_realm",
    n_("is_ml_admin"): "is_ml_realm",
    n_("is_assembly_admin"): "is_assembly_realm",
    n_("is_cdelokal_admin"): "is_ml_realm",
    n_("is_auditor"): "is_cde_realm",
}

#: List of all admin roles who actually have a corresponding realm with a user role.
REALM_ADMINS = {"core_admin", "cde_admin", "event_admin", "ml_admin", "assembly_admin"}

DB_ROLE_MAPPING: role_map_type = collections.OrderedDict((
    ("meta_admin", "cdb_admin"),
    ("core_admin", "cdb_admin"),
    ("cde_admin", "cdb_admin"),
    ("ml_admin", "cdb_admin"),
    ("assembly_admin", "cdb_admin"),
    ("event_admin", "cdb_admin"),
    ("finance_admin", "cdb_admin"),
    ("cdelokal_admin", "cdb_admin"),

    ("searchable", "cdb_member"),
    ("member", "cdb_member"),
    ("cde", "cdb_member"),
    ("assembly", "cdb_member"),
    ("auditor", "cdb_member"),

    ("event", "cdb_persona"),
    ("ml", "cdb_persona"),
    ("persona", "cdb_persona"),
    ("droid", "cdb_persona"),

    ("anonymous", "cdb_anonymous"),
))


# All roles available to non-driod users. Can be used to create dummy users
# with all roles, like for `cdedb.script` or `cdedb.frontend.cron`.
ALL_ROLES: Set[Role] = set(DB_ROLE_MAPPING) - {"droid"}


def roles_to_db_role(roles: Set[Role]) -> str:
    """Convert a set of application level roles into a database level role."""
    for role in DB_ROLE_MAPPING:
        if role in roles:
            return DB_ROLE_MAPPING[role]

    raise RuntimeError(n_("Could not determine any db role."))


ADMIN_VIEWS_COOKIE_NAME = "enabled_admin_views"

#: every admin view with one admin role per row (except of genesis)
ALL_ADMIN_VIEWS: Set[AdminView] = {
    "meta_admin",
    "core_user", "core",
    "cde_user", "past_event", "ml_mgmt_cde", "ml_mod_cde",
    "finance",
    "event_user", "event_mgmt", "event_orga", "ml_mgmt_event", "ml_mod_event",
    "ml_user", "ml_mgmt", "ml_mod",
    "ml_mgmt_cdelokal", "ml_mod_cdelokal",
    "assembly_user", "assembly_mgmt", "assembly_presider",
    "ml_mgmt_assembly", "ml_mod_assembly",
    "auditor",
    "genesis",
}

ALL_MOD_ADMIN_VIEWS: Set[AdminView] = {
    "ml_mod", "ml_mod_cde", "ml_mod_event", "ml_mod_cdelokal",
    "ml_mod_assembly"}

ALL_MGMT_ADMIN_VIEWS: Set[AdminView] = {
    "ml_mgmt", "ml_mgmt_cde", "ml_mgmt_event", "ml_mgmt_cdelokal",
    "ml_mgmt_assembly"}


def roles_to_admin_views(roles: Set[Role]) -> Set[AdminView]:
    """ Get the set of available admin views for a user with given roles."""
    result: Set[Role] = set()
    if "meta_admin" in roles:
        result |= {"meta_admin"}
    if "core_admin" in roles:
        result |= {"core", "core_user", "cde_user", "event_user",
                   "assembly_user", "ml_user"}
    if "cde_admin" in roles:
        result |= {"cde_user", "past_event", "ml_mgmt_cde", "ml_mod_cde"}
    if "finance_admin" in roles:
        result |= {"finance"}
    if "event_admin" in roles:
        result |= {"event_user", "event_mgmt", "event_orga", "ml_mgmt_event",
                   "ml_mod_event"}
    if "ml_admin" in roles:
        result |= {"ml_user", "ml_mgmt", "ml_mod"}
    if "cdelokal_admin" in roles:
        result |= {"ml_mgmt_cdelokal", "ml_mod_cdelokal"}
    if "assembly_admin" in roles:
        result |= {"assembly_user", "assembly_mgmt", "assembly_presider",
                   "ml_mgmt_assembly", "ml_mod_assembly"}
    if "auditor" in roles:
        result |= {"auditor"}
    if roles & ({'core_admin'} | set(
            "{}_admin".format(realm)
            for realm in REALM_SPECIFIC_GENESIS_FIELDS)):
        result |= {"genesis"}
    return result


# This overrides the more general PERSONA_DEFAULTS dict with some realm-specific
# defaults for genesis account creation.
GENESIS_REALM_OVERRIDE = {
    'event': {
        'is_cde_realm': False,
        'is_event_realm': True,
        'is_assembly_realm': False,
        'is_ml_realm': True,
        'is_member': False,
        'is_searchable': False,
    },
    'ml': {
        'is_cde_realm': False,
        'is_event_realm': False,
        'is_assembly_realm': False,
        'is_ml_realm': True,
        'is_member': False,
        'is_searchable': False,
    },
    'cde': {
        'is_cde_realm': True,
        'is_event_realm': True,
        'is_assembly_realm': True,
        'is_ml_realm': True,
        'is_member': True,
        'is_searchable': False,
        'trial_member': True,
        'decided_search': False,
        'bub_search': False,
        'paper_expuls': True,
    }
}
