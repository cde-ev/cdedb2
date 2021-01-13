import enum
from collections import OrderedDict
from typing import Optional, TYPE_CHECKING, Collection, Dict, List, Set, Tuple, Type, Union

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import CdEDBObject, RequestState, User, extract_roles, n_
from cdedb.database.constants import (
    MailinglistDomain, MailinglistInteractionPolicy, MailinglistTypes,
)
from cdedb.query import Query, QueryOperators

MIPol = Union[MailinglistInteractionPolicy, None]
MIPolMap = Dict[int, MIPol]


class BackendContainer:
    """Helper class to pass multiple backends into the ml_type methods at once."""
    def __init__(self, *, core=None, event=None, assembly=None):  # type: ignore
        self.core = core
        self.event = event
        self.assembly = assembly


def get_full_address(val: CdEDBObject) -> str:
    """Construct the full address of a mailinglist."""
    if isinstance(val, dict):
        return val['local_part'] + '@' + str(MailinglistDomain(val['domain']))
    else:
        raise ValueError(n_("Cannot determine full address for %(input)s."),
                         {'input': val})


class MailinglistGroup(enum.IntEnum):
    """To be used in `MlType.sortkey` to group similar mailinglists together."""
    cde = 2
    team = 3
    event = 10
    assembly = 20
    cdelokal = 30
    other = 1


class AllMembersImplicitMeta:
    """Metaclass for all mailinglists with members as implicit subscribers."""
    maxsize_default = 64

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Return a set of all current members."""
        check_appropriate_type(mailinglist, cls)  # type: ignore
        return bc.core.list_current_members(rs, is_active=False)


class EventAssociatedMeta:
    """Metaclass for all event associated mailinglists."""
    # Allow empty event_id to mark legacy event-lists.
    mandatory_validation_fields = {
        ("event_id", Optional[vtypes.ID]),
    }

    @classmethod
    def periodic_cleanup(cls, rs: RequestState, mailinglist: CdEDBObject,
                         ) -> bool:
        """Disable periodic cleanup to freeze legacy event-lists."""
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        return mailinglist["event_id"] is not None


class TeamMeta:
    """Metaclass for all team lists."""
    sortkey = MailinglistGroup.team
    viewer_roles = {"persona"}
    domains = [MailinglistDomain.lists, MailinglistDomain.dokuforge]
    maxsize_default = 4096


class GeneralMailinglist:
    """Base class for all mailinglist types.

    Class attributes:

    * `sortkey`: Determines where mailinglists of this type are grouped.
    * `domains`: Determines the available domains for mailinglists of this type.
    * `max_size_default`: A default value for `max_size` when creating a new
        mailinglist of this type.
    * `allow_unsub`: Whether or not to allow unsubscribing from a mailinglist
        of this type.
    * `mandatory_validation_fields`: A Set of additional (mandatory) fields to be
        checked during validation for mailinglists of this type.
    * `optional_validation_fields`: Like `madatory_validation_fields` but optional
        instead.
    * `viewer_roles`: Determines who may view the mailinglist.
        See `may_view()` for details.
    * `relevant_admins`: Determines who may administrate the mailinglist. See
        `is_relevant_admin()` for details.
    * `role_map`: An ordered Dict to determine mailinglist interactions in a
        hierarchical way for trivial mailinglist types.

    """
    def __init__(self) -> None:
        raise RuntimeError()

    sortkey: MailinglistGroup = MailinglistGroup.other

    domains: List[MailinglistDomain] = [MailinglistDomain.lists]

    # default value for maxsize in KB
    maxsize_default = 2048

    allow_unsub: bool = True

    # Additional fields for validation. See docstring for details.
    mandatory_validation_fields: Set[Tuple[str, str]] = set()
    optional_validation_fields: Set[Tuple[str, str]] = set()

    @classmethod
    def get_additional_fields(cls) -> Set[Tuple[str, str]]:
        ret = set()
        for field, argtype in (cls.mandatory_validation_fields
                               | cls.optional_validation_fields):
            if (
                isinstance(argtype, str)
                and argtype.startswith('[')
                and argtype.endswith(']')
            ):
                ret.add((field, "[str]"))
            else:
                ret.add((field, str))
        return ret

    viewer_roles: Set[str] = {"ml"}

    @classmethod
    def may_view(cls, rs: RequestState) -> bool:
        """Determine whether the user may view a mailinglist.

        Instead of overriding this, you should set the `viewer_roles`
        attribute, so that `ml_admin` may always view all mailinglists.

        Relevant class attributes:

        - `viewer_roles`: A set of roles other than `ml_admin` which allows
          a user to view a mailinglist. The semantics are similar to `@access`.
        """
        return bool((cls.viewer_roles | {"ml_admin"}) & rs.user.roles)

    @classmethod
    def is_privileged_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
        """Check if the user is a privileged moderator.

        Everyone with ml realm may be moderator of any mailinglist. But for some
        lists, you must have additional privileges to make subscription-state
        related changes to a mailinglist (like being an orga or presider).

        This includes
            * Changing subscription states as a moderator.
            * Changing properties of a ml influencing implicit subscribers.

        Per default, every moderator is privileged.

        This returns a filter which allows the caller to check ids as desired.
        """
        return mailinglist['id'] in rs.user.moderator

    relevant_admins: Set[str] = set()

    @classmethod
    def is_relevant_admin(cls, user: User) -> bool:
        """Determine if the user is allowed to administrate a mailinglist.

        Instead of overriding this, you should set the `relevant_admins`
        attribute, so that `ml_admin` may always administrate all mailinglists.

        Relevant class attributes:

        - `relevant_admins`: A set of roles other than `ml_admin` which allows
          a user to administrate a mailinglist. The semantics are similar to
          `@access`.
        """
        return bool((cls.relevant_admins | {"ml_admin"}) & user.roles)

    if TYPE_CHECKING:
        role_map: OrderedDict[str, MailinglistInteractionPolicy]
    role_map = OrderedDict()

    @classmethod
    def moderator_admin_views(cls) -> Set[str]:
        """All admin views which toggle the moderator view for this mailinglist.

        This is must be only used for cosmetic changes, similar to
        core.is_relative_admin_view.
        """
        return {"ml_mod_" + admin.replace("_admin", "")
                for admin in cls.relevant_admins} | {"ml_mod"}

    @classmethod
    def management_admin_views(cls) -> Set[str]:
        """All admin views which toggle the management view for this mailinglist.

        This is must be only used for cosmetic changes, similar to
        core.is_relative_admin_view.
        """
        return {"ml_mgmt_" + admin.replace("_admin", "")
                for admin in cls.relevant_admins} | {"ml_mgmt"}

    @classmethod
    def has_moderator_view(cls, user: User) -> bool:
        """Checks admin privileges and if a appropriated admin view is enabled.

        This is must be only used for cosmetic changes, similar to
        core.is_relative_admin_view.
        """
        return (cls.is_relevant_admin(user)
                and bool(cls.moderator_admin_views() & user.admin_views))

    @classmethod
    def has_management_view(cls, user: User) -> bool:
        """Checks admin privileges and if a appropriated admin view is enabled.

        This is must be only used for cosmetic changes, similar to
        core.is_relative_admin_view.
        """
        return (cls.is_relevant_admin(user)
                and bool(cls.management_admin_views() & user.admin_views))

    @classmethod
    def get_interaction_policy(cls, rs: RequestState, bc: BackendContainer,
                               mailinglist: CdEDBObject, persona_id: int,
                               ) -> MIPol:
        """Singularized wrapper for `get_interaction_policies`."""
        return cls.get_interaction_policies(
            rs, bc, mailinglist, (persona_id,))[persona_id]

    @classmethod
    def get_interaction_policies(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject,
                                 persona_ids: Collection[int]
                                 ) -> MIPolMap:
        """Determine the MIPol of the user or a persona with a mailinglist.

        Instead of overriding this, you can set the `role_map` attribute,
        which will automatically take care of the work for trivial mailinglists.

        For more involved interactions, override this method instead.

        This does not do a permission check, because it is not exposed to the
        frontend and does not currently have a way of accessing the relevant
        methods of the MailinglistBackend.
        """
        # TODO check for access to the ml? Needs ml_backend.
        personas = bc.core.get_personas(rs, persona_ids)
        ret: MIPolMap = {}
        for persona_id, persona in personas.items():
            roles = extract_roles(persona, introspection_only=True)
            for role, pol in cls.role_map.items():
                if role in roles:
                    ret[persona_id] = pol
                    break
            else:
                ret[persona_id] = None
        return ret

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Retrieve a set of personas, which should be subscribers."""
        return set()

    @classmethod
    def periodic_cleanup(cls, rs: RequestState, mailinglist: CdEDBObject,
                         ) -> bool:
        """Whether or not to do periodic subscription cleanup on this list."""
        return True


class CdEMailinglist(GeneralMailinglist):
    """Base class for CdE-Mailinglists."""

    sortkey = MailinglistGroup.cde
    domains = [MailinglistDomain.lists, MailinglistDomain.testmail]
    viewer_roles = {"cde"}
    relevant_admins = {"cde_admin"}


class EventMailinglist(GeneralMailinglist):
    """Base class for Event-Mailinglists."""

    sortkey = MailinglistGroup.event
    domains = [MailinglistDomain.aka]
    viewer_roles = {"event"}
    relevant_admins = {"event_admin"}


class AssemblyMailinglist(GeneralMailinglist):
    """Base class for Assembly-Mailinglists."""

    sortkey = MailinglistGroup.assembly
    viewer_roles = {"assembly"}
    relevant_admins = {"assembly_admin"}


class MemberMailinglist(CdEMailinglist):
    viewer_roles = {"member"}


class MemberMandatoryMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.mandatory)
    ])
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False
    # Disallow management by cde admins.
    relevant_admins: Set[str] = set()


class MemberOptOutMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.opt_out)
    ])


class MemberOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.opt_in)
    ])


class MemberModeratedOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.moderated_opt_in)
    ])


class MemberInvitationOnlyMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.invitation_only)
    ])


class TeamMailinglist(TeamMeta, MemberModeratedOptInMailinglist):
    pass


class RestrictedTeamMailinglist(TeamMeta, MemberInvitationOnlyMailinglist):
    pass


class EventAssociatedMailinglist(EventAssociatedMeta, EventMailinglist):
    mandatory_validation_fields = (
            EventAssociatedMeta.mandatory_validation_fields
            | {("registration_stati", "[enum_registrationpartstati]")})

    @classmethod
    def is_privileged_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
        """Check if the user is a privileged moderator.

        For EventAssociatedMailinglists, this are the orgas of the event.
        """
        check_appropriate_type(mailinglist, cls)

        basic_privilege = super().is_privileged_moderator(rs, bc, mailinglist)
        if mailinglist['event_id'] is None:
            return basic_privilege
        additional_privilege = (mailinglist['event_id'] in rs.user.orga
                                or "event_admin" in rs.user.roles)
        return basic_privilege and additional_privilege

    @classmethod
    def get_interaction_policies(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject,
                                 persona_ids: Collection[int],
                                 ) -> MIPolMap:
        """Determine the MIPol of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this basically means opt-in for all
        implicit subscribers. See `get_impicit_subscribers`.
        """
        check_appropriate_type(mailinglist, cls)

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return {anid: MailinglistInteractionPolicy.invitation_only
                    for anid in persona_ids}

        ret: MIPolMap = {}
        for persona_id in persona_ids:
            if bc.event.check_registration_status(
                    rs, persona_id, mailinglist['event_id'],
                    mailinglist['registration_stati']):
                ret[persona_id] = MailinglistInteractionPolicy.opt_out
            else:
                ret[persona_id] = None

        return ret

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `EventAssociatedMailinglist` this means registrations with
        one of the configured stati in any part.
        """
        check_appropriate_type(mailinglist, cls)

        if mailinglist["event_id"] is None:
            raise ValueError(n_("No implicit subscribers possible for "
                                "legacy event list."))

        event = bc.event.get_event(rs, mailinglist["event_id"])

        status_column = ",".join(
            "part{}.status".format(part_id) for part_id in event["parts"])
        spec = {
            'reg.id': 'id',
            'persona.id': 'id',
            status_column: 'int',
        }
        query = Query(
            scope="qview_registration",
            spec=spec,
            fields_of_interest=("persona.id",),
            constraints=[
                (status_column, QueryOperators.oneof,
                 mailinglist["registration_stati"]),
            ],
            order=tuple())
        data = bc.event.submit_general_query(rs, query, event_id=event["id"])

        return {e["persona.id"] for e in data}


class EventOrgaMailinglist(EventAssociatedMeta, EventMailinglist):
    maxsize_default = 8192

    @classmethod
    def get_interaction_policies(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject,
                                 persona_ids: Collection[int],
                                 ) -> MIPolMap:
        """Determine the MIPol of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this means opt-out for orgas only.
        """
        check_appropriate_type(mailinglist, cls)

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return {anid: MailinglistInteractionPolicy.invitation_only
                    for anid in persona_ids}

        ret: MIPolMap = {}
        event = bc.event.get_event(rs, mailinglist["event_id"])
        for persona_id in persona_ids:
            if persona_id in event["orgas"]:
                ret[persona_id] = const.MailinglistInteractionPolicy.opt_out
            else:
                ret[persona_id] = None
        return ret

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of personas that should be on this mailinglist.

        For the `EventOrgaMailinglist` this means the event's orgas.
        """
        check_appropriate_type(mailinglist, cls)

        if mailinglist["event_id"] is None:
            raise ValueError(n_("No implicit subscribers possible for "
                                "legacy event list."))

        event = bc.event.get_event(rs, mailinglist["event_id"])
        return event["orgas"]


class AssemblyAssociatedMailinglist(AssemblyMailinglist):
    mandatory_validation_fields = {
        ("assembly_id", vtypes.ID),
    }

    @classmethod
    def is_privileged_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
        """Check if a moderator is privileged.

        For AssemblyAssociatedMailinglists this is the case if the moderator may
        interact with the associated assembly.
        """
        check_appropriate_type(mailinglist, cls)

        basic_privilege = super().is_privileged_moderator(rs, bc, mailinglist)
        additional_privilege = bc.assembly.may_assemble(
            rs, assembly_id=mailinglist['assembly_id'])
        return basic_privilege and additional_privilege

    @classmethod
    def get_interaction_policies(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject,
                                 persona_ids: Collection[int],
                                 ) -> MIPolMap:
        """Determine the MIPol of the user or a persona with a mailinglist.

        For the `AssemblyAssociatedMailinglist` this means opt-out for
        attendees of the associated assembly.
        """
        check_appropriate_type(mailinglist, cls)

        ret: MIPolMap = {}
        for persona_id in persona_ids:
            attending = bc.assembly.check_attendance(
                rs, persona_id=persona_id,
                assembly_id=mailinglist["assembly_id"])
            if attending:
                ret[persona_id] = const.MailinglistInteractionPolicy.opt_out
            else:
                ret[persona_id] = None
        return ret

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyAssociatedMailinglist` this means the attendees of the
        linked assembly.
        """
        check_appropriate_type(mailinglist, cls)
        return bc.assembly.list_attendees(rs, mailinglist["assembly_id"])


class AssemblyPresiderMailinglist(AssemblyAssociatedMailinglist):
    maxsize_default = 8192

    @classmethod
    def get_interaction_policies(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject,
                                 persona_ids: Collection[int],
                                 ) -> MIPolMap:
        """Determine the MIPol of some personas with a mailinglist.

        For the `AssemblyPresiderMailinglist` this means opt-out for presiders only.
        """
        check_appropriate_type(mailinglist, cls)

        presiders = bc.assembly.list_assembly_presiders(rs, mailinglist["assembly_id"])
        ret: MIPolMap = {}
        for persona_id in persona_ids:
            if persona_id in presiders:
                ret[persona_id] = MailinglistInteractionPolicy.opt_out
            else:
                ret[persona_id] = None
        return ret

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyPresiderMailignlist` this means the presiders of the
        linked assembly.
        """
        check_appropriate_type(mailinglist, cls)
        return bc.assembly.list_assembly_presiders(rs, mailinglist["assembly_id"])


class AssemblyOptInMailinglist(AssemblyMailinglist):
    role_map = OrderedDict([
        ("assembly", MailinglistInteractionPolicy.opt_in)
    ])


class GeneralOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", MailinglistInteractionPolicy.opt_in)
    ])


class GeneralModeratedOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", MailinglistInteractionPolicy.moderated_opt_in)
    ])


class GeneralInvitationOnlyMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", MailinglistInteractionPolicy.invitation_only)
    ])


class SemiPublicMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.opt_in),
        ("ml", MailinglistInteractionPolicy.moderated_opt_in)
    ])


class CdeLokalMailinglist(SemiPublicMailinglist):
    sortkey = MailinglistGroup.cdelokal
    domains = [MailinglistDomain.cdelokal, MailinglistDomain.cdemuenchen]
    relevant_admins = {"cdelokal_admin"}


MLTypeLike = Union[const.MailinglistTypes, Type[GeneralMailinglist]]
MLType = Type[GeneralMailinglist]


def get_type(val: Union[str, int, MLTypeLike]) -> MLType:
    if isinstance(val, str):
        val = int(val)
    if isinstance(val, int):
        val = MailinglistTypes(val)
    if isinstance(val, MailinglistTypes):
        return TYPE_MAP[val]
    if issubclass(val, GeneralMailinglist):
        return val
    raise ValueError(n_("Cannot determine ml_type from {}".format(val)))


def check_appropriate_type(mailinglist: CdEDBObject, ml_type: MLType) -> None:
    """Make sure that a method is not used on a mailinglist with a non-child class.

    Note, that if child class C does not override classmethod `foo` of parent class `P`
    the actual call will be:

    `P.foo(<class C>, ...)` rather than `P.foo(<class P>, ...)`.

    Perform this check inside methods that override `GeneralMailinglist`'s methods.
    """
    if not get_type(mailinglist["ml_type"]) is ml_type:
        raise RuntimeError(n_("%(ml_type)s is not an appropriate type for this"
                              " mailinglist."), {"ml_type": ml_type})


TYPE_MAP = {
    MailinglistTypes.member_mandatory: MemberMandatoryMailinglist,
    MailinglistTypes.member_opt_out: MemberOptOutMailinglist,
    MailinglistTypes.member_opt_in: MemberOptInMailinglist,
    MailinglistTypes.member_moderated_opt_in: MemberModeratedOptInMailinglist,
    MailinglistTypes.member_invitation_only: MemberInvitationOnlyMailinglist,
    MailinglistTypes.team: TeamMailinglist,
    MailinglistTypes.restricted_team: RestrictedTeamMailinglist,
    MailinglistTypes.event_associated: EventAssociatedMailinglist,
    MailinglistTypes.event_orga: EventOrgaMailinglist,
    MailinglistTypes.assembly_associated: AssemblyAssociatedMailinglist,
    MailinglistTypes.assembly_opt_in: AssemblyOptInMailinglist,
    MailinglistTypes.assembly_presider: AssemblyPresiderMailinglist,
    MailinglistTypes.general_opt_in: GeneralOptInMailinglist,
    MailinglistTypes.semi_public: SemiPublicMailinglist,
    MailinglistTypes.cdelokal: CdeLokalMailinglist,
}

ADDITIONAL_TYPE_FIELDS = set.union(*(atype.get_additional_fields()
                                     for atype in TYPE_MAP.values()))
