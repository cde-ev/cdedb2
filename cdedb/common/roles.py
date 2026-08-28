#!/usr/bin/env python3

"""Everything regarding the role model of the CdEDB."""

from collections.abc import Collection
from typing import Any, Self

from cdedb.common._roles_meta import _AdminViews, _Realms, _Roles
from cdedb.common.n_ import n_
from cdedb.config import Config
from cdedb.database.connection import DBRole
from cdedb.uncommon.intenum import FlagSet

_CONF = Config()

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = dict[str, Any]

# Admin views a user may activate/deactivate.
AdminView = str


class Roles(_Roles):
    """
    Roles a user (persona or droid) can have, that determine their privileges.

    This is an 'IntEnumFlag' with some custom behaviour.

    Members are defined as a tuple of:
        - An implicit 'enum.auto()' to generate the numerical value.
        - Optionally a "marker", that is a boolean column in the 'core.personas' table
            which if True, results in the user being granted that role.
        - Optionally any number of other roles (given as their name as a string), which
            are required in order for the user to be granted that role.
            This restriction applies both for extracting the roles during session
            creation, and (for the admin privileges) during privilege change operations.

            See 'extract_roles' below for further remarks, most notably that roles
            should only require roles that are come earlier in the definition order.

    A role that has no marker, may not require any other roles. It is created with an
    empty tuple as the value.
    """

    # Special role, that is granted to everyone.
    anonymous = ()

    # Special treatment in 'extraxt_roles'.
    persona = ()

    # "Regular" roles, that are granted automatically based on these definitions.
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

    # Realm roles, granted manually, not dependent on the 'core.personas' table.
    complaint_enforcer = ()
    event_helper = ()

    # Special cron role.
    cron = ()

    # Roles for droids. All other roles are meant for personas.
    droid = ()
    droid_infra = ()
    droid_orga = ()
    droid_resolve = ()
    droid_quick_partial_export = ()

    @classmethod
    def all_droid_roles(cls) -> "RoleSet":
        return RoleSet({
            cls.droid,
            cls.droid_infra,
            cls.droid_orga,
            cls.droid_resolve,
            cls.droid_quick_partial_export,
        })

    @classmethod
    def all_persona_roles(cls) -> "RoleSet":
        return ~cls.all_droid_roles() & ~cls.cron

    @classmethod
    def all_admin_roles(cls) -> "RoleSet":
        return RoleSet({
            cls.meta_admin,
            cls.core_admin,
            cls.cde_admin,
            cls.event_admin,
            cls.ml_admin,
            cls.assembly_admin,
            cls.auditor,
            cls.complaint_admin,
            cls.cdelokal_admin,
            cls.finance_admin,
        })

    @classmethod
    def all_realm_admin_roles(cls) -> "RoleSet":
        """All roles of admins responsible for any realm."""
        return Realms.all_realm_admins()

    @classmethod
    def all_user_admin_roles(cls) -> "RoleSet":
        """All roles of admins responsible for any users."""
        return cls.core_admin | cls.all_realm_admin_roles()

    @classmethod
    def all_genesis_realm_roles(cls) -> tuple["RoleSet", ...]:
        return (
            RoleSet({cls.core_admin}),
            *(
                RoleSet({realm.admin_role})
                for realm in Realms.get_available_genesis_realms()
            ),
        )

    def is_any_admin(self) -> bool:
        """Whether there is any admin role in this set of roles."""
        return self.all_admin_roles().has(self)

    def get_db_role(self) -> "DBRole":
        return RoleSet({self}).get_db_role()

    @classmethod
    def _translated_members(cls) -> "RoleSet":
        """Mark subset of members that need translations.

        This is automatically handled by the i18n automation.
        """
        return cls.all_admin_roles()

    def __or__(self, other: Self) -> "RoleSet":
        """Alllows combining 'Roles' into a 'RoleSet' using 'Roles.a | Roles.b'."""
        if not isinstance(other, self.__class__):
            return NotImplemented
        return RoleSet({self, other})

    def __invert__(self) -> "RoleSet":
        """Shortcut to get a 'RoleSet' with "all roles except this one"."""
        return ~RoleSet({self})

    @classmethod
    def all(cls) -> "RoleSet":
        """Shortcut to get a 'RoleSet' of all roles."""
        return RoleSet(cls)

    @classmethod
    def none(cls) -> "RoleSet":
        """Shortcut to get an empty 'RoleSet'."""
        return RoleSet({})


class RoleSet(FlagSet[Roles]):
    def is_any_admin(self) -> bool:
        """Whether there is any admin role in this set of roles."""
        return self.has_any(*Roles.all_admin_roles())

    def is_anonymous(self) -> bool:
        """Whether this 'RoleSet' contains _only_ the anonymous role."""
        return self == self.__class__({Roles.anonymous})

    def get_user_realms(self) -> "RealmSet":
        """Determine the realms of a user with these roles."""
        return Realms.from_user_roles(self)

    def get_genesis_realms(self) -> "RealmSet":
        """See 'Realms.genesis_realms_from_admin_roles'."""
        return Realms.genesis_realms_from_admin_roles(self)

    def get_db_role(self) -> "DBRole":
        if self.is_any_admin():
            return DBRole.admin
        if self.has_any(Roles.cde, Roles.assembly):
            return DBRole.member
        if self.has_any(Roles.persona, Roles.droid):
            return DBRole.persona
        return DBRole.anonymous

    def markers(self) -> list[str]:
        """Return a stably sorted list of markers in this 'RoleSet'."""
        return sorted(role.marker for role in self)


class Realms(_Realms):
    """
    This class defines the realm hierarchy and maps realms to (realm admin) roles.

    Each realm is associated with (in this order):
        - a role, that signifies that a user belongs to the realm.
        - a role, that signifies that a user may administrate the realm.
        - optionally, a list of implied realms.
            This signifies that a user of this realm must also have these other realms.

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
    [RealmSet.cde, RealmSet.ml, RealmSet.event|assembly]

    >>> user_realms = Realms.cde | Realms.event | Realms.ml | Realms.assembly
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [RealmSet.None, RealmSet.event|ml|assembly, RealmSet.cde]

    >>> user_realms = Realms.event | Realms.ml
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [RealmSet.cde, RealmSet.ml, RealmSet.event]

    >>> user_realms = Realms.assembly | Realms.ml
    >>> [user_realms.implying_realms, user_realms.implied_realms, user_realms.highest_realms]
    [RealmSet.cde, RealmSet.ml, RealmSet.assembly]
    """

    cde = 1, Roles.cde, Roles.cde_admin
    event = 2, Roles.event, Roles.event_admin
    ml = 4, Roles.ml, Roles.ml_admin
    assembly = 8, Roles.assembly, Roles.assembly_admin

    @property
    def implied_realms(self) -> "RealmSet":
        return {
            self.cde: self.ml | self.assembly | self.event,
            self.event: RealmSet({self.ml}),
            self.assembly: RealmSet({self.ml}),
        }.get(self, self.none())

    @classmethod
    def from_user_roles(cls, roles: RoleSet) -> "RealmSet":
        """Determine the realms of a user with the given roles."""
        return RealmSet(realm for realm in cls if roles.has(realm.role))

    @property
    def implying_realms(self) -> "RealmSet":
        """Determine all realms which would imply this realm.

        >>> Realms.ml.implied_realms
        RealmSet.None
        >>> Realms.event.implied_realms
        RealmSet.ml
        >>> Realms.assembly.implied_realms
        RealmSet.ml
        >>> Realms.cde.implied_realms
        RealmSet.event|ml|assembly

        >>> Realms.ml.implying_realms
        RealmSet.cde|event|assembly
        >>> Realms.event.implying_realms
        RealmSet.cde
        >>> Realms.assembly.implying_realms
        RealmSet.cde
        >>> Realms.cde.implying_realms
        RealmSet.None
        """
        return RealmSet(
            realm for realm in self.__class__ if realm.implied_realms.has(self)
        )

    @classmethod
    def get_available_genesis_realms(cls) -> dict[Self, str]:
        return {
            cls.cde: n_("CdE membership & events"),
            cls.event: n_("CdE events"),
            cls.ml: n_("CdE mailinglist"),
        }

    @classmethod
    def genesis_realms_from_admin_roles(cls, roles: RoleSet | Roles) -> "RealmSet":
        """
        Determine all genesis realms which may be handled by a user with the given roles.

        Note that core admins may handle all genesis realms and that you may not handle
        genesis for implied realms..

        >>> Realms.genesis_realms_from_admin_roles(Roles.core_admin)
        RealmSet.cde|event|ml|assembly
        >>> Realms.genesis_realms_from_admin_roles(Roles.cde_admin)
        RealmSet.cde
        >>> Realms.genesis_realms_from_admin_roles(Roles.event_admin | Roles.assembly_admin)
        RealmSet.event|assembly
        >>> Realms.genesis_realms_from_admin_roles(Roles.event_admin)
        RealmSet.event
        >>> Realms.genesis_realms_from_admin_roles(Roles.assembly_admin)
        RealmSet.assembly
        >>> Realms.genesis_realms_from_admin_roles(Roles.ml_admin)
        RealmSet.ml
        """
        if isinstance(roles, Roles):
            roles = RoleSet({roles})

        if roles.has(Roles.core_admin):
            return RealmSet(cls)

        return RealmSet(realm for realm in cls if roles.has(realm.admin_role))

    def get_required_user_views(
        self, conjunctive: bool = False
    ) -> list["AdminViewSet"]:
        return RealmSet([self]).get_required_user_views(conjunctive=conjunctive)

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
    def all_realm_admins(cls) -> RoleSet:
        """
        >>> Realms.all_realm_admins()
        RoleSet.cde_admin|event_admin|ml_admin|assembly_admin
        """
        return RoleSet(realm.admin_role for realm in cls)

    def __or__(self, other: Self) -> "RealmSet":
        """Alllows combining 'Realms' into a 'RealmSet' using 'Realms.a | Realms.b'."""
        if not isinstance(other, self.__class__):
            return NotImplemented
        return RealmSet({self, other})

    def __invert__(self) -> "RealmSet":
        """Shortcut to get a 'RealmSet' with "all realms except this one"."""
        return ~RealmSet({self})

    @classmethod
    def all(cls) -> "RealmSet":
        """Shortcut to get a 'RealmSet' of all realms."""
        return RealmSet(cls)

    @classmethod
    def none(cls) -> "RealmSet":
        """Shortcut to get an empty 'RoleSet'."""
        return RealmSet({})


class RealmSet(FlagSet[Realms]):
    @property
    def implied_realms(self) -> Self:
        return self.__class__(x for realm in self for x in realm.implied_realms)

    @property
    def implying_realms(self) -> Self:
        """Determine all realms which would (each) imply all realms in a given set."""
        return self.__class__(
            realm for realm in Realms if realm.implied_realms.has_all(self)
        )

    @property
    def highest_realms(self) -> Self:
        """Determine the highest realms in a given set of realms.

        I.e. all realms which are not implied by other realms in the set.
        """
        return self - self.implied_realms

    @property
    def realm_markers(self) -> list[str]:
        return [realm.realm_marker for realm in self]

    def get_required_admin_roles(self, conjunctive: bool = False) -> list[RoleSet]:
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

        Note that core admins are always allowed access.

        :returns: List admin role flags. Any of these "sets" is sufficient.

        >>> RealmSet({Realms.ml}).get_required_admin_roles()
        [RoleSet.core_admin, RoleSet.ml_admin]
        >>> (Realms.event|Realms.ml).get_required_admin_roles()
        [RoleSet.core_admin, RoleSet.event_admin]
        >>> (Realms.ml|Realms.assembly).get_required_admin_roles()
        [RoleSet.core_admin, RoleSet.assembly_admin]
        >>> (Realms.event|Realms.ml|Realms.assembly).get_required_admin_roles()
        [RoleSet.core_admin, RoleSet.event_admin, RoleSet.assembly_admin]
        >>> (Realms.cde|Realms.event|Realms.ml|Realms.assembly).get_required_admin_roles()
        [RoleSet.core_admin, RoleSet.cde_admin]

        >>> RealmSet({Realms.ml}).get_required_admin_roles(conjunctive=True)
        [RoleSet.core_admin, RoleSet.ml_admin]
        >>> (Realms.event|Realms.ml).get_required_admin_roles(conjunctive=True)
        [RoleSet.core_admin, RoleSet.event_admin]
        >>> (Realms.ml|Realms.assembly).get_required_admin_roles(conjunctive=True)
        [RoleSet.core_admin, RoleSet.assembly_admin]
        >>> (Realms.event|Realms.ml|Realms.assembly).get_required_admin_roles(conjunctive=True)
        [RoleSet.core_admin, RoleSet.event_admin|assembly_admin]
        >>> (Realms.cde|Realms.event|Realms.ml|Realms.assembly).get_required_admin_roles(conjunctive=True)
        [RoleSet.core_admin, RoleSet.cde_admin]
        """
        ret = [RoleSet({Roles.core_admin})]
        relevant = self.highest_realms
        if conjunctive:
            ret.append(RoleSet(realm.admin_role for realm in relevant))
        else:
            for realm in sorted(relevant):
                ret.append(RoleSet({realm.admin_role}))
        return ret

    def get_required_user_views(
        self, conjunctive: bool = False
    ) -> list["AdminViewSet"]:
        """
        What user views do you need to be acting as a relative admin to a user?

        >>> (Realms.ml).get_required_user_views()
        [AdminViewSet.core_user, AdminViewSet.ml_user]
        >>> (Realms.event|Realms.ml).get_required_user_views()
        [AdminViewSet.core_user, AdminViewSet.event_user]
        >>> (Realms.assembly|Realms.ml).get_required_user_views()
        [AdminViewSet.core_user, AdminViewSet.assembly_user]
        >>> (Realms.event|Realms.ml|Realms.assembly).get_required_user_views()
        [AdminViewSet.core_user, AdminViewSet.event_user, AdminViewSet.assembly_user]
        >>> (Realms.cde|Realms.event|Realms.ml|Realms.assembly).get_required_user_views()
        [AdminViewSet.core_user, AdminViewSet.cde_user]

        >>> (Realms.ml).get_required_user_views(conjunctive=True)
        [AdminViewSet.core_user, AdminViewSet.ml_user]
        >>> (Realms.event|Realms.ml).get_required_user_views(conjunctive=True)
        [AdminViewSet.core_user, AdminViewSet.event_user]
        >>> (Realms.assembly|Realms.ml).get_required_user_views(conjunctive=True)
        [AdminViewSet.core_user, AdminViewSet.assembly_user]
        >>> (Realms.event|Realms.ml|Realms.assembly).get_required_user_views(conjunctive=True)
        [AdminViewSet.core_user, AdminViewSet.event_user|assembly_user]
        >>> (Realms.cde|Realms.event|Realms.ml|Realms.assembly).get_required_user_views(conjunctive=True)
        [AdminViewSet.core_user, AdminViewSet.cde_user]
        """
        return [
            AdminViews.user_views_from_admin_roles(roles)
            for roles in self.get_required_admin_roles(conjunctive)
        ]


def extract_roles(session: CdEDBObject, introspection_only: bool = False) -> RoleSet:
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
    RoleSet.anonymous
    >>> extract_roles(user_data, introspection_only=True)
    RoleSet.anonymous|persona|ml|ml_admin
    >>> user_data["is_active"] = True
    >>> extract_roles(user_data)
    RoleSet.anonymous|persona|ml|ml_admin
    >>> user_data[Realms.cde.realm_marker] = True
    >>> extract_roles(user_data)
    RoleSet.anonymous|persona|cde|ml|core_admin|ml_admin
    """
    ret = RoleSet({Roles.anonymous})
    if session['is_active'] or introspection_only:
        ret |= Roles.persona
    elif not introspection_only:
        return ret

    # Iterate manually to be able to subsequently apply the 'required roles' checks.
    for possible_role in Roles:
        if possible_role.marker is None:
            continue  # type: ignore[unreachable]
        if session.get(possible_role.marker) and ret.has_all(
            *possible_role.required_roles
        ):
            ret |= possible_role

    return ret


def droid_roles(identity: str) -> RoleSet:
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
    genesis = tuple(Roles.all_genesis_realm_roles())

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
    def all_user_views(cls) -> "AdminViewSet":
        return AdminViewSet({
            cls.core_user,
            cls.cde_user,
            cls.event_user,
            cls.ml_user,
            cls.assembly_user,
        })

    @classmethod
    def all_mod_views(cls) -> "AdminViewSet":
        return AdminViewSet({
            cls.ml_mod,
            cls.ml_mod_core,
            cls.ml_mod_cde,
            cls.ml_mod_event,
            cls.ml_mod_cdelokal,
            cls.ml_mod_assembly,
        })

    @classmethod
    def all_mgmt_views(cls) -> "AdminViewSet":
        return AdminViewSet({
            cls.ml_mgmt,
            cls.ml_mgmt_core,
            cls.ml_mgmt_cde,
            cls.ml_mgmt_event,
            cls.ml_mgmt_cdelokal,
            cls.ml_mgmt_assembly,
        })

    def _is_available_to(self, roles: RoleSet) -> bool:
        return roles.has_any(*self.required_roles)

    @classmethod
    def from_roles(cls, roles: RoleSet) -> "AdminViewSet":
        return AdminViewSet({
            admin_view for admin_view in cls if admin_view._is_available_to(roles)
        })

    @classmethod
    def user_views_from_admin_roles(cls, roles: RoleSet) -> "AdminViewSet":
        if roles.has(Roles.core_admin):
            return AdminViewSet({cls.core_user})
        return cls.from_roles(roles) & cls.all_user_views()

    @classmethod
    def serialize(cls, admin_views: Collection[Self] | Self) -> str:
        if isinstance(admin_views, cls):
            return str(admin_views)
        return ",".join(map(str, admin_views))  # type: ignore[arg-type] # mypy bug

    @classmethod
    def deserialize(cls, cookie: str) -> "AdminViewSet":
        try:
            return AdminViewSet({
                cls[admin_view.removeprefix(f"{cls.__name__}.")]
                for admin_view in cookie.split(",")
            })
        except (ValueError, KeyError):
            return AdminViewSet()

    def or_(self, other: Self) -> "AdminViewSet":
        return AdminViewSet({self, other})

    def __or__(self, other: Self) -> "AdminViewSet":
        return self.or_(other)


class AdminViewSet(FlagSet[AdminViews]):
    def has_any_mod(self) -> bool:
        return self.has_any(*AdminViews.all_mod_views())

    def has_any_mgmt(self) -> bool:
        return self.has_any(*AdminViews.all_mgmt_views())
