#!/usr/bin/env python3

"""Everything regarding the role model of the CdEDB."""

import collections
from typing import TYPE_CHECKING, Any, Self

from cdedb.common._roles_meta import _Realms, _Roles
from cdedb.common.fields import REALM_SPECIFIC_GENESIS_FIELDS, Role
from cdedb.common.n_ import n_
from cdedb.config import Config

_CONF = Config()

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = dict[str, Any]

# Admin views a user may activate/deactivate.
AdminView = str


class Roles(_Roles):
    anonymous = ()

    persona = ()

    cde = "is_cde_realm"
    event = "is_event_realm"
    ml = "is_ml_realm"
    assembly = "is_assembly_realm"

    meta_admin = "is_meta_admin", "cde"
    core_admin = "is_core_admin", "cde"
    cde_admin = "is_cde_admin", "cde"
    event_admin = "is_event_admin", "event"
    ml_admin = "is_ml_admin", "ml"
    assembly_admin = "is_assembly_admin", "assembly"

    auditor = "is_auditor", "cde"
    complaint_admin = "is_complaint_admin", "event"
    cdelokal_admin = "is_cdelokal_admin", "ml"
    finance_admin = "is_finance_admin", "cde_admin"

    member = "is_member", "cde"
    searchable = "is_searchable", "member"

    cron = ()

    droid = ()
    droid_infra = ()
    droid_orga = ()
    droid_resolve = ()
    droid_quick_partial_export = ()

    @classmethod
    def all_droid_roles(cls) -> Self:
        return (
            cls.droid
            | cls.droid_infra
            | cls.droid_orga
            | cls.droid_resolve
            | cls.droid_quick_partial_export
        )

    @classmethod
    def all_persona_roles(cls) -> Self:
        return ~cls.all_droid_roles() & ~cls.cron

    @classmethod
    def all_admin_roles(cls) -> Self:
        return (
            cls.meta_admin
            | cls.core_admin
            | cls.cde_admin
            | cls.event_admin
            | cls.ml_admin
            | cls.assembly_admin
            | cls.auditor
            | cls.complaint_admin
            | cls.cdelokal_admin
            | cls.finance_admin
        )

    def is_any_admin(self) -> bool:
        """Whether there is any admin role in this set of roles."""
        return bool(self & self.all_admin_roles())

    def get_user_realms(self) -> "Realms":
        """Determine the realms of a user with these roles."""
        return Realms.from_user_roles(self)

    def get_admin_realms(self) -> "Realms":
        """See 'Realms.from_admin_roles'."""
        return Realms.from_admin_roles(self)


class Realms(_Realms):
    """
    This class defines the realm hierarchy and maps realms to (realm admin) roles.

    Each realm is associated with (in this order):
        - a role, that signifies that a user belongs to the realm.
        - a role, that signifies that a user may administrate the realm.
        - optionnally, a list of implied realms.
            This signifies that a user of this reals must also have these other realms.

            For technical reasons, these realms need to be given as a sequence of
            strings. It is possible to refer to a realms further below in the definition
            order.

            These realms are not evaluated transitively. Transitive implications need to
            be explicitely listed.

            It is technically possible to create circular implications, but tbis is
            likely to result in unexpected behavior. Similarly a realm should not imply
            itself.

    The hierarchy defines some realms as implying, implied or maximal for each realm set..
    These can be retrieved via the 'implying_realms', 'implied_realms' and 'highest_realms'
    properties respectively.

    >>> user_realms = Realms.event | Realms.ml | Realms.assembly
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [Realms.cde, Realms.ml, Realms.event|assembly]

    >>> user_realms = Realms.cde | Realms.event | Realms.ml | Realms.assembly
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [Realms.None, Realms.event|ml|assembly, Realms.cde]

    >>> user_realms = Realms.event | Realms.ml
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [Realms.cde, Realms.ml, Realms.event]

    >>> user_realms = Realms.assembly | Realms.ml
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [Realms.cde, Realms.ml, Realms.assembly]
    """

    cde = Roles.cde, Roles.cde_admin, "ml", "assembly", "event"
    event = Roles.event, Roles.event_admin, "ml"
    ml = Roles.ml, Roles.ml_admin
    assembly = Roles.assembly, Roles.assembly_admin, "ml"

    @classmethod
    def from_user_roles(cls, roles: Roles) -> Self:
        """Determine the realms of a user with the given roles."""
        return cls.union(realm for realm in cls if realm.role in roles)

    @classmethod
    def from_admin_roles(cls, roles: Roles) -> Self:
        """
        Determine all realms which may be administrated by a user with the given roles.

        Note that core admins may administrate all realms.

        >>> Realms.from_admin_roles(Roles.core_admin)
        Realms.cde|event|ml|assembly
        >>> Realms.from_admin_roles(Roles.cde_admin)
        Realms.cde|event|ml|assembly
        >>> Realms.from_admin_roles(Roles.event_admin | Roles.assembly_admin)
        Realms.event|ml|assembly
        >>> Realms.from_admin_roles(Roles.event_admin)
        Realms.event|ml
        >>> Realms.from_admin_roles(Roles.assembly_admin)
        Realms.ml|assembly
        >>> Realms.from_admin_roles(Roles.ml_admin)
        Realms.ml
        """
        if Roles.core_admin in roles:
            return cls.all()

        return cls.union(
            realm | realm.implied_realms for realm in cls if realm.admin_role in roles
        )

    @property
    def implying_realms(self) -> Self:
        """Determine all realms which would (each) imply all realms in a given set."""
        return self.__class__.union(
            realm for realm in ~self if self in realm.implied_realms
        )

    @property
    def highest_realms(self) -> Self:
        """Determine the highest realms in a given set of realms.

        I.e. all realms which are not implied by other realms in the set.
        """
        return self & ~self.implied_realms

    def get_required_admin_roles(self, conjunctive: bool = False) -> list[Roles]:
        """Required admin privilege relative to a persona (signified by its roles)

        Basically this answers the question: If a user has access to the given
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

        Note that core admins and are always allowed access.

        :returns: List admin role flags. Any of these "sets" is sufficient.
        """
        ret = [Roles.core_admin]
        relevant = self.highest_realms
        if conjunctive:
            ret.append(Roles.union(realm.admin_role for realm in relevant))
        else:
            for realm in relevant:
                ret.append(realm.admin_role)
        return ret

    @property
    def realm_marker(self) -> str:
        """Shortcut to the marker of the associated role for better type inference."""
        assert self.role.marker is not None
        return self.role.marker

    @property
    def admin_marker(self) -> str:
        """Shortcut to the marker of the associated admin for better type inference."""
        assert self.admin_role.marker is not None
        return self.admin_role.marker


# TODO move to PersonaStatus datclass
def extract_roles(session: CdEDBObject, introspection_only: bool = False) -> Roles:
    """Determine user roles from a persona data set.

    The data contains the relevant portion of attributes from the core.personas table.

    Each role is granted based on the value of the associated 'marker' key.

    Each role can also have a list of required roles, without _all_ of which the role
    is not granted.
    Because this iterates the members 'Roles' class in definition order, a role may
    only require preceding roles.
    Transitively required roles are implicitly checked because of iteration order.

    Note that the required roles _do not_ enforce the realm hierarchy defined by 'Realms'.

    Note that this also works on non-personas (i.e. dicts of is_* flags).

    :param introspection_only:
        If 'False' (the default) the result will reflect the roles (think "privileges")
        the user aquires upon login. In particular an unset 'is_active' prevents them
        from aquiring any non-trivial roles.
        If 'True' the result will reflect the status of the user, while being acted
        upon. This does not take 'is_active' into account.
        This is relevant for e.g. adding the user as participant, moderator, presider,
        admin, etc.

    >>> user_data = {
    ...     "is_active": False,
    ...     "is_core_admin": True,
    ...     "is_event_admin": True,
    ...     "is_ml_admin": True,
    ...     "is_ml_realm": True,
    ... }
    >>> extract_roles(user_data)
    Roles.anonymous
    >>> extract_roles(user_data, introspection_only=True)
    Roles.anonymous|persona|ml|ml_admin
    >>> user_data["is_active"] = True
    >>> extract_roles(user_data)
    Roles.anonymous|persona|ml|ml_admin
    >>> user_data[Realms.cde.realm_marker] = True
    >>> extract_roles(user_data)
    Roles.anonymous|persona|cde|ml|core_admin|ml_admin
    """
    ret = Roles.anonymous
    if session['is_active'] or introspection_only:
        ret |= Roles.persona
    elif not introspection_only:
        return ret

    # Iterate manually to be able to subsequently apply the 'required roles' checks.
    for possible_role in Roles:
        if possible_role.marker is None:
            continue
        if session.get(possible_role.marker) and possible_role.required_roles in ret:
            ret |= possible_role

    return ret


def extract_user_realms(user: CdEDBObject) -> Realms:
    """Extract the Realms the user belongs to from the user dataset.

    This can be used to determine the admin privileges required to
    create and/or edit such a user.
    """
    return extract_roles(user, introspection_only=True).get_user_realms()


def droid_roles(identity: str) -> Roles:
    """Resolve droid identity to a complete set of roles.

    Currently this is rather trivial, but could be more involved in the
    future if more API capabilities are added to the DB.

    :param identity: The name for the API functionality, e.g. ``resolve``.
    """
    ret = Roles.anonymous | Roles.droid | Roles[f"droid_{identity}"]
    if identity in _CONF["INFRASTRUCTURE_DROIDS"]:
        ret |= Roles.droid_infra

    return ret


#: Creating a persona requires one to supply values for nearly all fields,
#: although in some realms they are meaningless. Here we provide a base skeleton
#: which can be used, so that these realms do not need to have any knowledge of
#: these fields.
# TODO move to Persona dataclass
PERSONA_DEFAULTS = {
    'is_cde_realm': False,
    'is_event_realm': False,
    'is_ml_realm': False,
    'is_assembly_realm': False,
    'is_member': False,
    'is_searchable': False,
    'is_active': True,
    'title': None,
    'nickname': None,
    'legal_given_names': None,
    'show_legal_given_names': False,
    'name_supplement': None,
    'gender': None,
    'pronouns': None,
    'pronouns_nametag': False,
    'pronouns_profile': False,
    'birthday': None,
    'telephone': None,
    'mobile': None,
    'address_supplement': None,
    'address': None,
    'show_address': True,
    'postal_code': None,
    'location': None,
    'country': None,
    'birth_name': None,
    'address_supplement2': None,
    'address2': None,
    'show_address2': True,
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
    'honorary_member': None,
    'decided_search': None,
    'bub_search': None,
    'foto': None,
    'paper_expuls': None,
    'donation': None,
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
# TODO move to PersonaStatus dataclass
ADMIN_KEYS = {
    n_("is_meta_admin"): "is_cde_realm",
    n_("is_core_admin"): "is_cde_realm",
    n_("is_cde_admin"): "is_cde_realm",
    n_("is_finance_admin"): "is_cde_admin",
    n_("is_event_admin"): "is_event_realm",
    n_("is_ml_admin"): "is_ml_realm",
    n_("is_assembly_admin"): "is_assembly_realm",
    n_("is_cdelokal_admin"): "is_ml_realm",
    n_("is_complaint_admin"): "is_event_realm",
    n_("is_auditor"): "is_cde_realm",
}

#: List of all admin roles who actually have a corresponding realm with a user role.
# TODO move to PersonaStatus dataclass
REALM_ADMINS = {"core_admin", "cde_admin", "event_admin", "ml_admin", "assembly_admin"}

#: All admin roles. Have privileged access to user data.
# TODO move to PersonaStatus dataclass
ALL_ADMINS = {
    *REALM_ADMINS,
    "meta_admin",
    "finance_admin",
    "cdelokal_admin",
    "complaint_admin",
    "auditor",
}

# TODO move to PersonaStatus dataclass
DB_ROLE_MAPPING: role_map_type = collections.OrderedDict((
    # admin
    ("meta_admin", "cdb_admin"),
    ("core_admin", "cdb_admin"),
    ("cde_admin", "cdb_admin"),
    ("ml_admin", "cdb_admin"),
    ("assembly_admin", "cdb_admin"),
    ("event_admin", "cdb_admin"),
    ("finance_admin", "cdb_admin"),
    ("cdelokal_admin", "cdb_admin"),
    ("complaint_admin", "cdb_admin"),
    # member
    ("searchable", "cdb_member"),
    ("member", "cdb_member"),
    ("cde", "cdb_member"),
    ("assembly", "cdb_member"),
    ("auditor", "cdb_member"),
    # persona
    ("event", "cdb_persona"),
    ("ml", "cdb_persona"),
    ("persona", "cdb_persona"),
    ("droid", "cdb_persona"),
    # anonymous
    ("anonymous", "cdb_anonymous"),
))


# TODO move to PersonaStatus dataclass
def roles_to_db_role(roles: set[Role]) -> str:
    """Convert a set of application level roles into a database level role."""
    for role in DB_ROLE_MAPPING:
        if role in roles:
            return DB_ROLE_MAPPING[role]

    raise RuntimeError(n_("Could not determine any db role."))


ADMIN_VIEWS_COOKIE_NAME = "enabled_admin_views"

#: every admin view with one admin role per row (except of genesis)
# TODO move to PersonaStatus dataclass
ALL_ADMIN_VIEWS: set[AdminView] = {
    "meta_admin",
    "core_user", "core", "user_review", "ml_mgmt_core", "ml_mod_core",
    "complaint",
    "cde_user", "past_event", "ml_mgmt_cde", "ml_mod_cde",
    "finance",
    "event_user", "event_mgmt", "event_list", "event_orga",
    "ml_mgmt_event", "ml_mod_event",
    "ml_user", "ml_mgmt", "ml_mod",
    "ml_mgmt_cdelokal", "ml_mod_cdelokal",
    "assembly_user", "assembly_mgmt", "assembly_presider",
    "ml_mgmt_assembly", "ml_mod_assembly",
    "auditor",
    "genesis",
}  # fmt: skip

# TODO move to PersonaStatus dataclass
ALL_MOD_ADMIN_VIEWS: set[AdminView] = {
    "ml_mod",
    "ml_mod_core",
    "ml_mod_cde",
    "ml_mod_event",
    "ml_mod_cdelokal",
    "ml_mod_assembly",
}

# TODO move to PersonaStatus dataclass
ALL_MGMT_ADMIN_VIEWS: set[AdminView] = {
    "ml_mgmt",
    "ml_mgmt_core",
    "ml_mgmt_cde",
    "ml_mgmt_event",
    "ml_mgmt_cdelokal",
    "ml_mgmt_assembly",
}


# TODO move to PersonaStatus dataclass
def roles_to_admin_views(roles: set[Role]) -> set[AdminView]:
    """Get the set of available admin views for a user with given roles."""
    result: set[Role] = set()
    if "meta_admin" in roles:
        result |= {"meta_admin"}
    if "core_admin" in roles:
        result |= {
            "core",
            "core_user",
            "cde_user",
            "event_user",
            "assembly_user",
            "ml_user",
            "user_review",
            "ml_mgmt_core",
            "ml_mod_core",
        }
    if {"complaint_admin", "complaint.enforcer"} & roles:
        result |= {"complaint"}
    if "cde_admin" in roles:
        result |= {"cde_user", "user_review", "past_event", "ml_mgmt_cde", "ml_mod_cde"}
    if "finance_admin" in roles:
        result |= {"finance", "event_orga"}
    if "event_admin" in roles:
        result |= {
            "event_user",
            "user_review",
            "event_mgmt",
            "event_list",
            "event_orga",
            "ml_mgmt_event",
            "ml_mod_event",
        }
    if "event.event_helper" in roles:
        result |= {"event_orga", "event_list"}
    if "ml_admin" in roles:
        result |= {"ml_user", "ml_mgmt", "ml_mod"}
    if "cdelokal_admin" in roles:
        result |= {"ml_mgmt_cdelokal", "ml_mod_cdelokal"}
    if "assembly_admin" in roles:
        result |= {
            "assembly_user",
            "assembly_mgmt",
            "assembly_presider",
            "ml_mgmt_assembly",
            "ml_mod_assembly",
        }
    if "auditor" in roles:
        result |= {"auditor", "event_orga"}
    if roles & (
        {'core_admin'}
        | set(f"{realm}_admin" for realm in REALM_SPECIFIC_GENESIS_FIELDS)
    ):
        result |= {"genesis"}
    return result
