import enum
import itertools
from collections import OrderedDict
from typing import (
    TYPE_CHECKING, Any, Collection, Dict, List, Mapping, Optional, Set, Type, Union,
)

from typing_extensions import Literal

import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, PrivilegeError, RequestState, User, extract_roles, n_,
)
from cdedb.database.constants import (
    MailinglistDomain, MailinglistTypes, RegistrationPartStati,
)
from cdedb.subman.machine import SubscriptionPolicy
from cdedb.query import Query, QueryOperators

SubscriptionPolicyMap = Dict[int, SubscriptionPolicy]
TypeMapping = Mapping[str, Type[Any]]


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
    public = 1
    cde = 2
    team = 3
    event = 10
    assembly = 20
    cdelokal = 30


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

    sortkey: MailinglistGroup = MailinglistGroup.public

    domains: List[MailinglistDomain] = [MailinglistDomain.lists]

    # default value for maxsize in KB
    maxsize_default = 2048

    allow_unsub: bool = True

    # Additional fields for validation. See docstring for details.
    mandatory_validation_fields: TypeMapping = {}
    optional_validation_fields: TypeMapping = {}

    @classmethod
    def get_additional_fields(cls) -> Mapping[
        str, Union[Literal["str"], Literal["[str]"]]
    ]:
        ret: Dict[str, Union[Literal["str"], Literal["[str]"]]] = {}
        for field, argtype in {
            **cls.mandatory_validation_fields,
            **cls.optional_validation_fields,
        }.items():
            if getattr(argtype, "__origin__", None) is list:
                ret[field] = "[str]"
            else:
                ret[field] = "str"
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
    def is_restricted_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
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
        # pylint: disable=unsubscriptable-object
        role_map: OrderedDict[str, SubscriptionPolicy]
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
    def get_subscription_policy(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject, persona_id: int,
                                ) -> SubscriptionPolicy:
        """Singularized wrapper for `get_subscription_policies`."""
        return cls.get_subscription_policies(
            rs, bc, mailinglist, (persona_id,))[persona_id]

    @classmethod
    def get_subscription_policies(cls, rs: RequestState, bc: BackendContainer,
                                  mailinglist: CdEDBObject,
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
            for role, pol in cls.role_map.items():
                if role in roles:
                    ret[persona_id] = pol
                    break
            else:
                ret[persona_id] = SubscriptionPolicy.none
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


class AllUsersImplicitMeta(GeneralMailinglist):
    """Metaclass for all mailinglists with all users as implicit subscribers."""
    maxsize_default = 64

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Return a set of all personas.

        Leave out personas which are archived or have no valid email set.."""
        check_appropriate_type(mailinglist, cls)
        return bc.core.list_all_personas(rs, is_active=False, valid_email=True)


class AllMembersImplicitMeta(GeneralMailinglist):
    """Metaclass for all mailinglists with members as implicit subscribers."""
    maxsize_default = 64

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Return a set of all current members."""
        check_appropriate_type(mailinglist, cls)
        return bc.core.list_current_members(rs, is_active=False, valid_email=True)


class EventAssociatedMeta(GeneralMailinglist):
    """Metaclass for all event associated mailinglists."""
    # Allow empty event_id to mark legacy event-lists.
    mandatory_validation_fields: TypeMapping = {
        "event_id": Optional[vtypes.ID]  # type: ignore
    }

    @classmethod
    def periodic_cleanup(cls, rs: RequestState, mailinglist: CdEDBObject) -> bool:
        """Disable periodic cleanup to freeze legacy event-lists."""
        check_appropriate_type(mailinglist, cls)
        return mailinglist["event_id"] is not None


class TeamMeta(GeneralMailinglist):
    """Metaclass for all team lists."""
    sortkey = MailinglistGroup.team
    viewer_roles = {"persona"}
    domains = [MailinglistDomain.lists]
    maxsize_default = 4096


class ImplicitsSubscribableMeta(GeneralMailinglist):
    """
    Metaclass for all mailinglists where exactly implicit subscribers may subscribe,
    """

    @classmethod
    def get_subscription_policies(cls, rs: RequestState, bc: BackendContainer,
                                  mailinglist: CdEDBObject,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Return subscribable for all given implicit subscribers, none otherwise.

        To avoid unneeded privilege escalation while avoiding backend errors, this
        infers non-eligibity for mailinglists if a user raises a privilege error while
        checking whether they are privileged.
        """
        check_appropriate_type(mailinglist, cls)

        ret = {pid: SubscriptionPolicy.none for pid in persona_ids}
        try:
            implicits = cls.get_implicit_subscribers(rs, bc, mailinglist)
        except PrivilegeError:
            if {rs.user.persona_id} == set(persona_ids):
                return ret
            else:
                raise
        ret.update({pid: SubscriptionPolicy.subscribable
                    for pid in implicits.intersection(persona_ids)})
        return ret


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
        ("member", SubscriptionPolicy.subscribable)
    ])
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False
    # Disallow management by cde admins.
    relevant_admins: Set[str] = set()


class MemberOptOutMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable)
    ])


class MemberOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable)
    ])


class MemberModeratedOptInMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.moderated_opt_in)
    ])


class MemberInvitationOnlyMailinglist(MemberMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.invitation_only)
    ])


class TeamMailinglist(TeamMeta, MemberModeratedOptInMailinglist):
    pass


class RestrictedTeamMailinglist(TeamMeta, MemberInvitationOnlyMailinglist):
    pass


class EventAssociatedMailinglist(EventAssociatedMeta, EventMailinglist):
    mandatory_validation_fields: TypeMapping = {
            **EventAssociatedMeta.mandatory_validation_fields,
            "registration_stati": List[RegistrationPartStati],
    }

    @classmethod
    def is_restricted_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
        """Check if the user is a restricted moderator.

        For EventAssociatedMailinglists, this are all moderators except for the orgas
        of the event and event admins.
        """
        check_appropriate_type(mailinglist, cls)

        basic_restriction = super().is_restricted_moderator(rs, bc, mailinglist)
        if mailinglist['event_id'] is None:
            return basic_restriction
        additional_restriction = (mailinglist['event_id'] not in rs.user.orga
                                  and "event_admin" not in rs.user.roles)
        return basic_restriction or additional_restriction

    @classmethod
    def get_subscription_policies(cls, rs: RequestState, bc: BackendContainer,
                                  mailinglist: CdEDBObject,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `EventAssociatedMailinglist` this means invitation-only for legacy
        lists without a linked event and subscribable for all event participants with
        the appropriate registration stati.

        We cannot do this using `get_implicit_subscribers` because that requires
        additional privileges.
        """
        check_appropriate_type(mailinglist, cls)

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        ret = {}
        for persona_id in persona_ids:
            if bc.event.check_registration_status(
                    rs, persona_id, mailinglist['event_id'],
                    mailinglist['registration_stati']):
                ret[persona_id] = SubscriptionPolicy.subscribable
            else:
                ret[persona_id] = SubscriptionPolicy.none

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
            return set()

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


class EventOrgaMailinglist(EventAssociatedMeta, ImplicitsSubscribableMeta,
                           EventMailinglist):
    maxsize_default = 8192

    @classmethod
    def get_subscription_policies(cls, rs: RequestState, bc: BackendContainer,
                                  mailinglist: CdEDBObject,
                                  persona_ids: Collection[int],
                                  ) -> SubscriptionPolicyMap:
        """Determine the SubscriptionPolicy for each given persona with the mailinglist.

        For the `EventOrgaMailinglist` this means subscribable for orgas only.

        See `get_implicit_subscribers`.
        """
        check_appropriate_type(mailinglist, cls)

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return {anid: SubscriptionPolicy.invitation_only for anid in persona_ids}

        return super().get_subscription_policies(rs, bc, mailinglist, persona_ids)

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `EventOrgaMailinglist` this means the event's orgas.
        """
        check_appropriate_type(mailinglist, cls)

        if mailinglist["event_id"] is None:
            return set()

        event = bc.event.get_event(rs, mailinglist["event_id"])
        return event["orgas"]


class AssemblyAssociatedMailinglist(ImplicitsSubscribableMeta, AssemblyMailinglist):
    mandatory_validation_fields = {"assembly_id": vtypes.ID}

    @classmethod
    def is_restricted_moderator(cls, rs: RequestState, bc: BackendContainer,
                                mailinglist: CdEDBObject
                                ) -> bool:
        """Check if the user is a restricted moderator.

        For AssemblyAssociatedMailinglists this is the case if the moderator may
        interact with the associated assembly.
        """
        check_appropriate_type(mailinglist, cls)

        basic_restriction = super().is_restricted_moderator(rs, bc, mailinglist)
        additional_restriction = not bc.assembly.may_assemble(
            rs, assembly_id=mailinglist['assembly_id'])
        return basic_restriction or additional_restriction

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
        ("assembly", SubscriptionPolicy.subscribable)
    ])


class GeneralMandatoryMailinglist(AllUsersImplicitMeta, GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.subscribable)
    ])
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False


class GeneralOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.subscribable)
    ])


class GeneralModeratedOptInMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.moderated_opt_in)
    ])


class GeneralInvitationOnlyMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("ml", SubscriptionPolicy.invitation_only)
    ])


class GeneralModeratorMailinglist(ImplicitsSubscribableMeta, GeneralMailinglist):
    # For mandatory lists, ignore all unsubscriptions.
    allow_unsub = False

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `GeneralModeratorMailinglist` this means mandatory for all users who
        are moderators of any mailinglist.
        """
        check_appropriate_type(mailinglist, cls)
        return bc.core.list_all_moderators(rs)


class CdELokalModeratorMailinglist(GeneralModeratorMailinglist):
    relevant_admins = {"cdelokal_admin"}

    @classmethod
    def get_implicit_subscribers(cls, rs: RequestState, bc: BackendContainer,
                                 mailinglist: CdEDBObject) -> Set[int]:
        """Get a list of people that should be on this mailinglist.

        For the `CdELokalModeratorMailinglist` this means mandatory for all users who
        are moderators of any cdelokal mailinglist.
        """
        check_appropriate_type(mailinglist, cls)
        return bc.core.list_all_moderators(rs, ml_types={MailinglistTypes.cdelokal})


class SemiPublicMailinglist(GeneralMailinglist):
    role_map = OrderedDict([
        ("member", SubscriptionPolicy.subscribable),
        ("ml", SubscriptionPolicy.moderated_opt_in)
    ])


class CdeLokalMailinglist(SemiPublicMailinglist):
    sortkey = MailinglistGroup.cdelokal
    domains = [MailinglistDomain.cdelokal]
    relevant_admins = {"cdelokal_admin"}


MLTypeLike = Union[MailinglistTypes, Type[GeneralMailinglist]]
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
    MailinglistTypes.general_mandatory: GeneralMandatoryMailinglist,
    MailinglistTypes.general_opt_in: GeneralOptInMailinglist,
    MailinglistTypes.general_moderators: GeneralModeratorMailinglist,
    MailinglistTypes.cdelokal_moderators: CdELokalModeratorMailinglist,
    MailinglistTypes.semi_public: SemiPublicMailinglist,
    MailinglistTypes.cdelokal: CdeLokalMailinglist,
}

ADDITIONAL_TYPE_FIELDS = dict(itertools.chain.from_iterable(
    atype.get_additional_fields().items()
    for atype in TYPE_MAP.values()
))
