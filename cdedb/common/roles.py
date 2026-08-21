#!/usr/bin/env python3

"""Everything regarding the role model of the CdEDB."""

from typing import Any, Self

from cdedb.common._roles_meta import _AdminViews, _Realms, _Roles
from cdedb.config import Config
from cdedb.database.connection import DBRole

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

    finance_admin = "is_finance_admin", "cde_admin"
    auditor = "is_auditor", "cde"
    complaint_admin = "is_complaint_admin", "event"
    cdelokal_admin = "is_cdelokal_admin", "ml"

    member = "is_member", "cde"
    searchable = "is_searchable", "member"

    # realm roles, granted manually.
    complaint_enforcer = ()
    event_helper = ()

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

    @classmethod
    def all_realm_admin_roles(cls) -> Self:
        """All roles of admins responsible for any realm."""
        return Realms.all_realm_admins()

    @classmethod
    def all_user_admin_roles(cls) -> Self:
        """All roles of admins responsible for any users."""
        return cls.core_admin | cls.all_realm_admin_roles()

    @classmethod
    def all_genesis_roles(cls) -> Self:
        return cls.core_admin | cls.cde_admin | cls.event_admin | cls.ml_admin

    def is_any_admin(self) -> bool:
        """Whether there is any admin role in this set of roles."""
        return bool(self & self.all_admin_roles())

    def get_user_realms(self) -> "Realms":
        """Determine the realms of a user with these roles."""
        return Realms.from_user_roles(self)

    def get_admin_realms(self) -> "Realms":
        """See 'Realms.from_admin_roles'."""
        return Realms.from_admin_roles(self)

    def get_db_role(self) -> "DBRole":
        if self.is_any_admin():
            return DBRole.admin
        if (self.cde | self.assembly) & self:
            return DBRole.member
        if (self.persona | self.droid) & self:
            return DBRole.persona
        return DBRole.anonymous


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

    @classmethod
    def all_realm_admins(cls) -> Roles:
        """
        >>> Realms.all_realm_admins()
        Roles.cde_admin|event_admin|ml_admin|assembly_admin
        """
        return Roles.union(realm.admin_role for realm in cls)


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
            continue  # type: ignore[unreachable]
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


class AdminViews(_AdminViews):
    @classmethod
    def cookie_name(cls) -> str:
        return "enabled_admin_views"

    user_review = Roles.core_admin, Roles.cde_admin, Roles.event_admin
    genesis = tuple(Roles.all_genesis_roles())

    core_user = Roles.core_admin
    cde_user = Roles.cde_admin, Roles.core_admin
    event_user = Roles.event_admin, Roles.core_admin
    ml_user = Roles.ml_admin, Roles.core_admin
    assembly_user = Roles.assembly_admin, Roles.core_admin

    meta_admin = Roles.meta_admin

    core = Roles.core_admin
    ml_mgmt_core = Roles.core_admin
    ml_mod_core = Roles.core_admin

    complaint = Roles.complaint_admin, Roles.complaint_enforcer

    past_event = Roles.cde_admin
    ml_mgmt_cde = Roles.cde_admin
    ml_mod_cde = Roles.cde_admin

    finance = Roles.finance_admin

    event_mgmt = Roles.event_admin
    event_list = Roles.event_admin, Roles.event_helper
    event_orga = (
        Roles.event_admin,
        Roles.finance_admin,
        Roles.auditor,
        Roles.event_helper,
    )
    ml_mgmt_event = Roles.event_admin
    ml_mod_event = Roles.event_admin

    ml_mgmt = Roles.ml_admin
    ml_mod = Roles.ml_admin

    ml_mgmt_cdelokal = Roles.cdelokal_admin
    ml_mod_cdelokal = Roles.cdelokal_admin

    assembly_mgmt = Roles.assembly_admin
    assembly_presider = Roles.assembly_admin
    ml_mgmt_assembly = Roles.assembly_admin
    ml_mod_assembly = Roles.assembly_admin

    auditor = Roles.auditor

    @classmethod
    def all_user_views(cls) -> Self:
        return (
            cls.core_user
            | cls.cde_user
            | cls.event_user
            | cls.ml_user
            | cls.assembly_user
        )

    @classmethod
    def all_mod_views(cls) -> Self:
        return (
            cls.ml_mod
            | cls.ml_mod_core
            | cls.ml_mod_cde
            | cls.ml_mod_event
            | cls.ml_mod_cdelokal
            | cls.ml_mod_assembly
        )

    @classmethod
    def all_mgmt_views(cls) -> Self:
        return (
            cls.ml_mgmt
            | cls.ml_mgmt_core
            | cls.ml_mgmt_cde
            | cls.ml_mgmt_event
            | cls.ml_mgmt_cdelokal
            | cls.ml_mgmt_assembly
        )

    def is_any_mod(self) -> bool:
        return bool(self & self.all_mod_views())

    def is_any_mgmt(self) -> bool:
        return bool(self & self.all_mgmt_views())

    @classmethod
    def from_roles(cls, roles: Roles) -> Self:
        return cls.union(
            admin_view
            for admin_view in cls
            if any(role in roles for role in admin_view.required_roles)
        )

    @classmethod
    def from_cookie(cls, cookie: str) -> Self:
        try:
            return cls(int(cookie))  # type: ignore[arg-type]
        except ValueError:
            return cls.none()
