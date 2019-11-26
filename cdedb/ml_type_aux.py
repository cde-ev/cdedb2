import enum
from collections import OrderedDict

from cdedb.common import extract_roles, PrivilegeError, n_, unwrap
from cdedb.query import Query, QueryOperators, QUERY_SPECS
import cdedb.validation as validate
import cdedb.database.constants as const
from cdedb.database.constants import (
    MailinglistTypes, MailinglistInteractionPolicy)


class Domain(enum.IntEnum):
    lists = 1
    aka = 2

    def __str__(self):
        domain_map = {
            Domain.lists: "lists.cde-ev.de",
            Domain.aka: "aka.cde-ev.de",
        }
        if self not in domain_map:
            raise NotImplementedError(n_("This domain is not supported."))
        return domain_map[self]


class MailinglistGroup(enum.IntEnum):
    other = enum.auto()
    cde = enum.auto()
    event = enum.auto()
    assembly = enum.auto()
    team = enum.auto()
    event_associated = enum.auto()
    orga = enum.auto()
    cdelokal = enum.auto()


class AllMembersImplicitMeta:
    """Metaclass for all mailinglists with members as implicit subscribers."""
    @classmethod
    def get_implicit_subscribers(cls, rs, mailinglist):
        query = "SELECT id from core.personas WHERE is_member = True"
        data = cls.core.query_all(rs, query, params=tuple())
        return {e["id"] for e in data}


class AssemblyAssociatedMeta:
    """Metaclass for all assembly associated mailinglists."""
    validation_fields = {
        "assembly_id": validate._id,
    }


class EventAssociatedMeta:
    """Metaclass for all event associated mailinglists."""
    validation_fields = {
        "event_id": validate._id,
    }


class LegacyMeta:
    """Metaclass for all legacy event mailinglists."""
    role_map = OrderedDict([
        ("event", MailinglistInteractionPolicy.invitation_only)
    ])


class TeamMeta:
    """Metaclass for all team lists."""
    sortkey = MailinglistGroup.team
    viewer_roles = {"persona"}


class GeneralMailinglist:
    """Base class for all mailinglist types.

    Class attributes:

    * `core`: A reference to the Core Backend needed to extract user information.
    * `sortkey`: Determines where mailinglists of this type are grouped.
    * `domain`: Determines the domain of the mailinglist.
    * `viewer_roles`: Determines who may view the mailinglist.
      See `may_view()` for details.
    * `relevant_admins`: Determines who may administrate the mailinglist. See
      `is_relevant_admin()` for details.
    * `role_map`: An ordered Dict to determines mailinglist interactions in a
      hierarchical way for trivial mailinglist types.
    * `validation_fields`: A dict of additional fields to be considered
      during validation for mailinglists of this type.

    """
    def __init__(self):
        raise RuntimeError()

    # This will be set later.
    core = None

    sortkey = MailinglistGroup.other

    domain = Domain.lists

    viewer_roles = {"ml"}

    @classmethod
    def may_view(cls, rs):
        """Determine whether the user may view a mailinglist.

        Instead of overriding this, you should set the `viwer_roles`
        attribute, so that `ml_admin` may always view all mailinglists.

        Relevant class attributes:

        - `viewer_roles`: A set of roles other than `ml_admin` which allows
          a user to view a mailinglist. The semantics are similar to `@access`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: bool
        """
        return bool((cls.viewer_roles | {"ml_admin"}) & rs.user.roles)

    relevant_admins = set()

    @classmethod
    def is_relevant_admin(cls, rs):
        """Determine if the user is a allowed to administrate a mailinglist.

        Instead of overriding this, you should set the `relevant_admins`
        attribute, so that `ml_admin` may always administrate all mailinglists.

        Relevant class attributes:

        - `relevant_admin`: A set of roles other than `ml_admin` which allows
          a user to administrate a mailinglist. The semantics are similar to
          `@access`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: bool
        """
        return bool((cls.relevant_admins | {"ml_admin"}) & rs.user.roles)

    role_map = OrderedDict()

    @classmethod
    def get_interaction_policy(cls, rs, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        Instead of overriding this, you can set the `role_map` attribute,
        which will automatically take care of the work for trivial mailinglists.

        For more involved interactions, override this method instead.

        This does not do a permission check, because it is not exposed to the
        frontend and does not currently have a way of accessing the relevant
        methods of the MailinglistBackend.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist: {str: object}
        :type persona_id: int
        :rtype: :py:class`const.MailinglistInteractionPolicy` or None
        """
        if not persona_id:
            roles = rs.user.roles

        # No permission check here.

        persona = unwrap(cls.core.get_personas(rs, (persona_id,)))
        roles = extract_roles(persona, introspection_only=True)
        for role, pol in role_map.items():
            if role in roles:
                return rolemap[role]
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, mailinglist):
        """Retrieve a set of personas, which should be subscribers.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist: {str: object}
        :rtype: {int}
        """
        return set()

    # Additional fields for validation. See docstring for details.
    validation_fields = {}


class CdEMailinglist(GeneralMailinglist):
    """Base class for CdE-Mailinglists.

    Relevant Attributes:

    * `cde`: A reference to the CdE-Backend which could at some point be needed
      to retrieve relevant information.

    """
    # cde = None

    sortkey = MailinglistGroup.cde
    viewer_roles = {"cde"}
    relevant_admins = {"cde_admin"}


class EventMailinglist(GeneralMailinglist):
    """Base class for Event-Mailinglists.

    Relevant Attributes:

    * `event`: A reference to the Event-Backend needed to check registration and
      orga information.

    """
    # This will be set later
    event = None

    sortkey = MailinglistGroup.event
    domain = Domain.aka
    viewer_roles = {"event"}
    relevant_admins = {"event_admin"}


class AssemblyMailinglist(GeneralMailinglist):
    """Base class for Assembly-Mailinglists.

    Relevant Attributes:

    * `assembly`: A reference to the Assembly-Backend needed to retrieve attendee
      information.

    """
    # This will be set later
    assembly = None

    sortkey = MailinglistGroup.assembly
    viewer_roles = {"assembly"}
    relevant_admins = {"assembly_admin"}


class MemberMailinglist(CdEMailinglist):
    viewer_roles = {"member"}


class MemberMandatoryMailinglist(AllMembersImplicitMeta, MemberMailinglist):
    role_map = OrderedDict([
        ("member", MailinglistInteractionPolicy.mandatory)
    ])


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
    sortkey = MailinglistGroup.event

    @classmethod
    def get_interaction_policy(cls, rs, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this basically means opt-in for all
        implicit subscribers. See `get_impicit_subscribers`.
        """
        assert type_map[mailinglist["type"]] == cls

        if not persona_id:
            persona_id = rs.user.persona_id

        if cls.event.check_registration_status(
                rs, persona_id, mailinglist['event_id'],
                mailinglist['registration_stati']):
            return MailinglistInteractionPolicy.implicits_only
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, mailinglist):
        """Get a list of people that should be on this mailinglist.

        For the `EventAssociatedMailinglist` this means registrations with
        one of the configured stati in any part.
        """
        assert type_map[mailinglist["type"]] == cls

        event = unwrap(cls.event.get_events(rs, (mailinglist["event_id"],)))

        status_column = ",".join(
            "part{}.status".format(part_id) for part_id in event["parts"])
        query = Query(
            scope="qview_registrations",
            spec=QUERY_SPECS["qview_registration"],
            fields_of_interest=("persona.id",),
            constraints=((status_column, QueryOperators.oneof,
                          ml["registration_stati"]),),
            order=tuple())
        data = cls.event.submit_general_query(
            rs, query, event_id=event["id"])

        return {e["persona.id"] for e in data}


class EventOrgaMailinglist(EventAssociatedMeta, EventMailinglist):
    sortkey = MailinglistGroup.orga

    @classmethod
    def get_interaction_policy(cls, rs, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this means opt-in for orgas only.
        """
        assert type_map[mailinglist["ml_type"]] == cls

        if not persona_id:
            persona_id = rs.user.persona_id

        event = unwrap(cls.event.get_events(rs, (mailinglist["event_id"],)))
        if persona_id in event["orgas"]:
            return const.MailinglistInteractionPolicy.opt_in
        else:
            return None


class EventAssociatedLegacyMailinglist(EventAssociatedMailinglist):
    pass


class EventOrgaLegacyMailinglist(EventOrgaMailinglist):
    pass


class AssemblyAssociatedMailinglist(AssemblyAssociatedMeta,
                                    AssemblyMailinglist):
    @classmethod
    def get_implicit_subscribers(cls, rs, mailinglist):
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyAssociatedMailinglist` this means the attendees of the
        linked assembly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist: {str: object}
        """
        assert type_map[mailinglist["type"]] == cls
        return cls.assembly.list_attendees(rs, ml["assembly_id"])


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


class CdeLokalMailinglist(GeneralOptInMailinglist):
    sortkey = MailinglistGroup.cdelokal


type_map = {
    MailinglistTypes.member_mandatory: MemberMandatoryMailinglist,
    MailinglistTypes.member_opt_out: MemberOptOutMailinglist,
    MailinglistTypes.member_opt_in: MemberOptInMailinglist,
    MailinglistTypes.member_moderated_opt_in: MemberModeratedOptInMailinglist,
    MailinglistTypes.member_invitation_only: MemberInvitationOnlyMailinglist,
    MailinglistTypes.team: TeamMailinglist,
    MailinglistTypes.restricted_team: RestrictedTeamMailinglist,
    MailinglistTypes.event_associated: EventAssociatedMailinglist,
    MailinglistTypes.event_orga: EventOrgaMailinglist,
    MailinglistTypes.event_associated_legacy: EventAssociatedLegacyMailinglist,
    MailinglistTypes.event_orga_legacy: EventOrgaLegacyMailinglist,
    MailinglistTypes.assembly_associated: AssemblyAssociatedMailinglist,
    MailinglistTypes.assembly_opt_in: AssemblyOptInMailinglist,
    MailinglistTypes.general_opt_in: GeneralOptInMailinglist,
    MailinglistTypes.semi_public: SemiPublicMailinglist,
    MailinglistTypes.cdelokal: CdeLokalMailinglist,
}


def initialize_backends(core, event, assembly):
    """Helper to initialize the appropriate backends for Mailinglisttypes."""
    GeneralMailinglist.core = core
    EventMailinglist.event = event
    AssemblyMailinglist.assembly = assembly
