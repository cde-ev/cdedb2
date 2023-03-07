"""Dataclass definitions of mailinglist realm."""

import dataclasses
import enum
import itertools
from dataclasses import dataclass, fields
from typing import (
    TYPE_CHECKING, Any, ClassVar, Collection, Dict, List, Literal, Mapping, Optional,
    OrderedDict, Set, Tuple, Type, Union, cast, get_origin,
)

from subman.machine import SubscriptionPolicy

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.roles import extract_roles
from cdedb.common.validation.types import TypeMapping
from cdedb.database.constants import MailinglistDomain, MailinglistTypes
from cdedb.models.common import CdEDataclass

if TYPE_CHECKING:
    from cdedb.backend.assembly import AssemblyBackend
    from cdedb.backend.core import CoreBackend
    from cdedb.backend.event import EventBackend
    from cdedb.common import RequestState, User
else:
    CdEDBObject = RequestState = User = None

SubscriptionPolicyMap = Dict[int, SubscriptionPolicy]

CdEDBObject = Dict[str, Any]


class BackendContainer:
    """Helper class to pass multiple backends into the ml_type methods at once."""
    def __init__(self, *, core: "CoreBackend" = None, event: "EventBackend" = None,
                 assembly: "AssemblyBackend" = None):
        self.core = cast("CoreBackend", core)
        self.event = cast("EventBackend", event)
        self.assembly = cast("AssemblyBackend", assembly)


class MailinglistGroup(enum.IntEnum):
    """To be used in `MlType.sortkey` to group similar mailinglists together."""
    public = 1
    cde = 2
    team = 3
    event = 10
    assembly = 20
    cdelokal = 30


@dataclass
class Mailinglist(CdEDataclass):
    """Base class for all mailinglist types.

        In addition ot the instance variables representing the individual mailinglist,
        this has class attributes which are determined by the mailinglist type.

        Class attributes:

        * `sortkey`: Determines where mailinglists of this type are grouped.
        * `domains`: Determines the available domains for mailinglists of this type.
        * `max_size_default`: A default value for `max_size` when creating a new
            mailinglist of this type.
        * `allow_unsub`: Whether or not to allow unsubscribing from a mailinglist
            of this type.
        * `viewer_roles`: Determines who may view the mailinglist.
            See `may_view()` for details.
        * `relevant_admins`: Determines who may administrate the mailinglist. See
            `is_relevant_admin()` for details.
        * `role_map`: An ordered Dict to determine mailinglist interactions in a
            hierarchical way for trivial mailinglist types.

        """
    title: str
    local_part: vtypes.EmailLocalPart
    domain: const.MailinglistDomain
    mod_policy: const.ModerationPolicy
    attachment_policy: const.AttachmentPolicy
    convert_html: bool
    is_active: bool

    moderators: Set[vtypes.ID]
    whitelist: Set[vtypes.Email]

    description: Optional[str]
    subject_prefix: Optional[str]
    maxsize: Optional[vtypes.PositiveInt]
    notes: Optional[str]

    # some mailinglist types define additional fields

    sortkey: ClassVar[MailinglistGroup] = MailinglistGroup.public
    available_domains: ClassVar[List[MailinglistDomain]] = [MailinglistDomain.lists]
    # default value for maxsize in KB
    maxsize_default: ClassVar = vtypes.PositiveInt(2048)
    allow_unsub: ClassVar[bool] = True

    def __post_init__(self) -> None:
        if self.__class__ == Mailinglist:
            raise TypeError("Cannot instantiate abstract class.")

    @property
    def ml_type(self) -> MailinglistTypes:
        if self.__class__ not in ML_TYPE_MAP_INV:
            raise NotImplementedError
        return ML_TYPE_MAP_INV[self.__class__]

    @property
    def address(self) -> vtypes.Email:
        """Build the address of the Mailinglist.

        We know that this is a valid Email since it passed the validation.
        """
        return vtypes.Email(self.get_address(vars(self)))

    @classmethod
    def get_address(cls, data: CdEDBObject) -> str:
        """Create an address from the given proto-mailinglist dict.

        We can not ensure that the returned string is a valid Email, since we do not
        know if it would pass the respective validator.
        """
        domain = const.MailinglistDomain(data["domain"]).get_domain()
        return f"{data['local_part']}@{domain}"

    @property
    def domain_str(self) -> str:
        return self.domain.get_domain()

    @classmethod
    def database_fields(cls) -> List[str]:
        return [field.name for field in fields(cls)
                if field.name not in {"moderators", "whitelist"}]

    @classmethod
    def validation_fields(cls, *, creation: bool) -> Tuple[TypeMapping, TypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        # make whitelist optional during Mailinglist creation
        if "whitelist" in mandatory:
            optional["whitelist"] = mandatory["whitelist"]
            del mandatory["whitelist"]
        return mandatory, optional

    @classmethod
    def get_additional_fields(cls) -> Mapping[
        str, Union[Literal["str"], Literal["[str]"]]
    ]:
        ret: Dict[str, Union[Literal["str"], Literal["[str]"]]] = {}
        for field in (set(fields(cls)) - set(fields(Mailinglist))):  # pylint: disable=superfluous-parens
            if get_origin(field.type) is list:
                ret[field.name] = "[str]"
            else:
                ret[field.name] = "str"
        return ret

    viewer_roles: ClassVar[Set[str]] = {"ml"}

    @classmethod
    def may_view(cls, rs: RequestState) -> bool:
        """Determine whether the user may view a mailinglist.

        Instead of overriding this, you should set the `viewer_roles`
        attribute, so that `ml_admin` may always view all mailinglists.

        Relevant class attributes:

        - `viewer_roles`: A set of roles other than `ml_admin` which allows
          a user to view a mailinglist. The semantics are similar to `@access`.
        """
        return (bool((cls.viewer_roles | {"ml_admin"}) & rs.user.roles)
                or cls.is_relevant_admin(rs.user))

    def is_restricted_moderator(self, rs: RequestState, bc: BackendContainer) -> bool:  # pylint: disable=no-self-use
        """Check if the user is a restricted moderator.

        Everyone with ml realm may be moderator of any mailinglist. But for some
        lists, you must have additional privileges to make subscription-state
        related changes to a mailinglist (like being an orga or presider).

        This includes
            * Changing subscription states as a moderator.
            * Changing properties of a ml influencing implicit subscribers.

        Per default, no moderator is restricted.

        This returns a filter which allows the caller to check ids as desired.
        """
        return False

    relevant_admins: ClassVar[Set[str]] = set()

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
        # pylint: disable=unsubscriptable-object
        role_map: ClassVar[OrderedDict[str, SubscriptionPolicy]]
    role_map: ClassVar = OrderedDict()  # type: ignore[no-redef]

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

    def get_subscription_policy(self, rs: RequestState, bc: BackendContainer,
                                persona_id: int) -> SubscriptionPolicy:
        """Singularized wrapper for `get_subscription_policies`."""
        return self.get_subscription_policies(
            rs, bc, (persona_id,))[persona_id]

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int]
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        Instead of overriding this, you can set the `role_map` attribute,
        which will automatically take care of the work for trivial mailinglists.

        For more involved interactions, override this method instead.

        This does not do a permission check, because it is not exposed to the
        frontend and does not currently have a way of accessing the relevant
        methods of the MailinglistBackend.
        """
        # TODO check for access to the ml? Needs ml_backend.
        personas = bc.core.get_personas(rs, persona_ids)

        ret = {}
        for persona_id, persona in personas.items():
            roles = extract_roles(persona, introspection_only=True)
            for role, pol in self.role_map.items():
                if role in roles:
                    ret[persona_id] = pol
                    break
            else:
                ret[persona_id] = SubscriptionPolicy.none
        return ret

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer  # pylint: disable=no-self-use
                                 ) -> Set[int]:
        """Retrieve a set of personas, which should be subscribers."""
        return set()

    def periodic_cleanup(self, rs: RequestState) -> bool:  # pylint: disable=no-self-use
        """Whether or not to do periodic subscription cleanup on this list."""
        return True


@dataclass
class GeneralMailinglist(Mailinglist):
    pass


@dataclass
class AllUsersImplicitMeta(GeneralMailinglist):
    """Metaclass for all mailinglists with all users as implicit subscribers."""
    maxsize_default: ClassVar = vtypes.PositiveInt(64)

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer
                                 ) -> Set[int]:
        """Return a set of all personas.

        Leave out personas which are archived or have no valid email set.."""
        return bc.core.list_all_personas(rs, is_active=False)


@dataclass
class AllMembersImplicitMeta(GeneralMailinglist):
    """Metaclass for all mailinglists with members as implicit subscribers."""
    maxsize_default = vtypes.PositiveInt(64)

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer,
                                 ) -> Set[int]:
        """Return a set of all current members."""
        return bc.core.list_current_members(rs, is_active=False)


@dataclass
class EventAssociatedMeta(GeneralMailinglist):
    """Metaclass for all event associated mailinglists."""
    # Allow empty event_id to mark legacy event-lists.
    event_id: Optional[vtypes.ID] = None

    def periodic_cleanup(self, rs: RequestState) -> bool:
        """Disable periodic cleanup to freeze legacy event-lists."""
        return self.event_id is not None


@dataclass
class TeamMeta(GeneralMailinglist):
    """Metaclass for all team lists."""
    sortkey = MailinglistGroup.team
    viewer_roles = {"persona"}
    available_domains = [MailinglistDomain.lists]
    maxsize_default = vtypes.PositiveInt(4096)


@dataclass
class ImplicitsSubscribableMeta(GeneralMailinglist):
    """
    Metaclass for all mailinglists where exactly implicit subscribers may subscribe,
    """

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Return subscribable for all given implicit subscribers, none otherwise.

        To avoid unneeded privilege escalation while avoiding backend errors, this
        infers non-eligibity for mailinglists if a user raises a privilege error while
        checking whether they are privileged.
        """
        ret = {pid: SubscriptionPolicy.none for pid in persona_ids}
        try:
            implicits = self.get_implicit_subscribers(rs, bc)
        except PrivilegeError:
            if {rs.user.persona_id} == set(persona_ids):
                return ret
            else:
                raise
        ret.update({pid: SubscriptionPolicy.subscribable
                    for pid in implicits.intersection(persona_ids)})
        return ret


@dataclass
class CdEMailinglist(GeneralMailinglist):
    """Base class for CdE-Mailinglists."""

    sortkey = MailinglistGroup.cde
    available_domains = [MailinglistDomain.lists, MailinglistDomain.testmail]
    viewer_roles = {"cde"}
    relevant_admins = {"cde_admin"}


@dataclass
class EventMailinglist(GeneralMailinglist):
    """Base class for Event-Mailinglists."""

    sortkey = MailinglistGroup.event
    available_domains = [MailinglistDomain.aka]
    viewer_roles = {"event"}
    relevant_admins = {"event_admin"}


@dataclass
class AssemblyMailinglist(GeneralMailinglist):
    """Base class for Assembly-Mailinglists."""

    sortkey = MailinglistGroup.assembly
    viewer_roles = {"assembly"}
    relevant_admins = {"assembly_admin"}


@dataclass
class MemberMailinglist(CdEMailinglist):
    viewer_roles = {"member"}


@dataclass
class MemberMandatoryMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable)
    ])
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False
    # Disallow management by cde admins.
    relevant_admins: ClassVar[Set[str]] = set()


@dataclass
class MemberOptOutMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable)
    ])


@dataclass
class MemberOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable)
    ])


@dataclass
class MemberModeratedOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.moderated_opt_in)
    ])


@dataclass
class MemberInvitationOnlyMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.invitation_only)
    ])


@dataclass
class TeamMailinglist(TeamMeta, MemberModeratedOptInMailinglist):
    pass


@dataclass
class RestrictedTeamMailinglist(TeamMeta, MemberInvitationOnlyMailinglist):
    pass


@dataclass
class EventAssociatedMailinglist(EventAssociatedMeta, EventMailinglist):
    registration_stati: List[const.RegistrationPartStati] = dataclasses.field(
        default_factory=list)

    def is_restricted_moderator(self, rs: RequestState, bc: BackendContainer) -> bool:
        """Check if the user is a restricted moderator.

        For EventAssociatedMailinglists, this are all moderators except for the orgas
        of the event and event admins.
        """
        basic_restriction = super().is_restricted_moderator(rs, bc)
        if self.event_id is None:
            return basic_restriction
        additional_restriction = (self.event_id not in rs.user.orga
                                  and "event_admin" not in rs.user.roles)
        return basic_restriction or additional_restriction

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `EventAssociatedMailinglist` this means invitation-only for legacy
        lists without a linked event and subscribable for all event participants with
        the appropriate registration stati.

        We cannot do this using `get_implicit_subscribers` because that requires
        additional privileges.
        """
        # Make event-lists without event link static.
        if self.event_id is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        data = bc.event.check_registrations_status(
            rs, persona_ids, self.event_id, self.registration_stati)
        return {
            k: SubscriptionPolicy.subscribable if v else SubscriptionPolicy.none
            for k, v in data.items()
        }

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `EventAssociatedMailinglist` this means registrations with
        one of the configured stati in any part.
        """
        if self.event_id is None:
            return set()

        event = bc.event.get_event(rs, self.event_id)

        spec = QueryScope.registration.get_spec(event=event)
        target = {f"part{part_id}.status" for part_id in event['parts']}
        for column in spec:
            if set(column.split(',')) == target:
                status_column = column
                break
        else:
            status_column = ",".join(
                f"part{part_id}.status" for part_id in event['parts'])
        query = Query(
            scope=QueryScope.registration,
            spec=spec,
            fields_of_interest=("persona.id",),
            constraints=[
                (status_column, QueryOperators.oneof, self.registration_stati),
            ],
            order=tuple())
        data = bc.event.submit_general_query(rs, query, event_id=event["id"])

        return {e["persona.id"] for e in data}


@dataclass
class EventOrgaMailinglist(EventAssociatedMeta, ImplicitsSubscribableMeta,
                           EventMailinglist):
    maxsize_default: ClassVar = vtypes.PositiveInt(8192)

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `EventOrgaMailinglist` this means subscribable for orgas only.

        See `get_implicit_subscribers`.
        """
        # Make event-lists without event link static.
        if self.event_id is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        return super().get_subscription_policies(rs, bc, persona_ids)

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `EventOrgaMailinglist` this means the event's orgas.
        """
        if self.event_id is None:
            return set()

        event = bc.event.get_event(rs, self.event_id)
        return event["orgas"]


@dataclass
class AssemblyAssociatedMailinglist(ImplicitsSubscribableMeta, AssemblyMailinglist):
    # Allow empty assembly_id to mark legacy assembly-lists.
    assembly_id: Optional[vtypes.ID] = None

    def periodic_cleanup(self, rs: RequestState) -> bool:
        """Disable periodic cleanup to freeze legacy assembly-lists."""
        return self.assembly_id is not None

    def is_restricted_moderator(self, rs: RequestState, bc: BackendContainer) -> bool:
        """Check if the user is a restricted moderator.

        For AssemblyAssociatedMailinglists this is the case if the moderator may
        interact with the associated assembly.
        """
        basic_restriction = super().is_restricted_moderator(rs, bc)
        if self.assembly_id is None:
            return basic_restriction
        additional_restriction = not bc.assembly.may_assemble(
            rs, assembly_id=self.assembly_id)
        return basic_restriction or additional_restriction

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `AssemblyAssociatedMailinglist` this means subscribable for attendees.

        See `get_implicit_subscribers`.
        """
        # Make assembly-lists without assembly link static.
        if self.assembly_id is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        return super().get_subscription_policies(rs, bc, persona_ids)

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer,
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyAssociatedMailinglist` this means the attendees of the
        linked assembly.
        """
        if self.assembly_id is None:
            return set()

        return bc.assembly.list_attendees(rs, self.assembly_id)


@dataclass
class AssemblyPresiderMailinglist(AssemblyAssociatedMailinglist):
    maxsize_default = vtypes.PositiveInt(8192)

    def get_subscription_policies(self, rs: RequestState, bc: BackendContainer,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `AssemblyPresiderMailinglist` this means subscribable for presiders.

        See `get_implicit_subscribers`.
        """

        # Make assembly-lists without assembly link static.
        if self.assembly_id is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        return super().get_subscription_policies(rs, bc, persona_ids)

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyPresiderMailignlist` this means the presiders of the
        linked assembly.
        """
        assert self.assembly_id is not None
        return bc.assembly.list_assembly_presiders(rs, self.assembly_id)


@dataclass
class AssemblyOptInMailinglist(AssemblyMailinglist):
    role_map = OrderedDict([
        ("assembly", SubscriptionPolicy.subscribable)
    ])


@dataclass
class GeneralMandatoryMailinglist(AllUsersImplicitMeta, Mailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.subscribable)
    ])
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False


@dataclass
class GeneralOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.subscribable)
    ])


@dataclass
class GeneralModeratedOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.moderated_opt_in)
    ])


@dataclass
class GeneralInvitationOnlyMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.invitation_only)
    ])


@dataclass
class GeneralModeratorMailinglist(ImplicitsSubscribableMeta, Mailinglist):
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `GeneralModeratorMailinglist` this means mandatory for all users who
        are moderators of any mailinglist.
        """
        return bc.core.list_all_moderators(rs)


@dataclass
class CdELokalModeratorMailinglist(GeneralModeratorMailinglist):
    relevant_admins = {"cdelokal_admin"}

    def get_implicit_subscribers(self, rs: RequestState, bc: BackendContainer,
                                 ) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `CdELokalModeratorMailinglist` this means mandatory for all users who
        are moderators of any cdelokal mailinglist.
        """
        return bc.core.list_all_moderators(rs, ml_types={MailinglistTypes.cdelokal})


@dataclass
class SemiPublicMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable),
        ("ml", SubscriptionPolicy.moderated_opt_in)
    ])


@dataclass
class CdeLokalMailinglist(SemiPublicMailinglist):
    sortkey = MailinglistGroup.cdelokal
    available_domains = [MailinglistDomain.cdelokal]
    relevant_admins = {"cdelokal_admin"}


@dataclass
class PublicMemberImplicitMailinglist(AllMembersImplicitMeta, GeneralOptInMailinglist):
    pass


MLType = Type[Mailinglist]


def get_ml_type(val: MailinglistTypes) -> MLType:
    return ML_TYPE_MAP[val]


ML_TYPE_MAP: Mapping[MailinglistTypes, Type[Mailinglist]] = {
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
    MailinglistTypes.general_mandatory: GeneralMandatoryMailinglist,
    MailinglistTypes.general_opt_in: GeneralOptInMailinglist,
    MailinglistTypes.general_moderated_opt_in: GeneralModeratedOptInMailinglist,
    MailinglistTypes.general_invitation_only: GeneralInvitationOnlyMailinglist,
    MailinglistTypes.general_moderators: GeneralModeratorMailinglist,
    MailinglistTypes.cdelokal_moderators: CdELokalModeratorMailinglist,
    MailinglistTypes.semi_public: SemiPublicMailinglist,
    MailinglistTypes.public_member_implicit: PublicMemberImplicitMailinglist,
    MailinglistTypes.cdelokal: CdeLokalMailinglist,
}

ML_TYPE_MAP_INV = {v: k for k, v in ML_TYPE_MAP.items()}

ADDITIONAL_TYPE_FIELDS = dict(itertools.chain.from_iterable(
    atype.get_additional_fields().items()
    for atype in ML_TYPE_MAP.values()
))
