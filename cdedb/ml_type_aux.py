import enum
from collections import OrderedDict

from cdedb.common import extract_roles, PrivilegeError, n_, unwrap
from cdedb.query import Query, QueryOperators, QUERY_SPECS
import cdedb.validation as validate
import cdedb.database.constants as const
from cdedb.database.constants import (
    MailinglistTypes, MailinglistInteractionPolicy)


class BackendContainer:
    def __init__(self, *, core=None, event=None, assembly=None):
        self.core = core
        self.event = event
        self.assembly = assembly


class Domain(enum.IntEnum):
    lists = 1
    aka = 2

    def __str__(self):
        if self not in _DOMAIN_STR_MAP:
            raise NotImplementedError(n_("This domain is not supported."))
        return domain_map[self]


# Instead of importing this, call str() on a Domain.
_DOMAIN_STR_MAP = {
    Domain.lists: "lists.cde-ev.de",
    Domain.aka: "aka.cde-ev.de",
}


class MailinglistGroup(enum.IntEnum):
    cde = 2
    team = 3
    event = 10
    assembly = 20
    cdelokal = 30
    other = 1


class AllMembersImplicitMeta:
    """Metaclass for all mailinglists with members as implicit subscribers."""
    @classmethod
    def get_implicit_subscribers(cls, rs, bc, mailinglist):
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        return bc.core.list_current_members(rs, is_active=True)


class AssemblyAssociatedMeta:
    """Metaclass for all assembly associated mailinglists."""
    validation_fields = {
        "assembly_id": validate._id,
    }


class EventAssociatedMeta:
    """Metaclass for all event associated mailinglists."""
    # Allow empty event_id to mark legacy event-lists.
    validation_fields = {
        "event_id": validate._id_or_None,
    }

    @classmethod
    def periodic_cleanup(cls, rs, mailinglist):
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        return mailinglist["event_id"] is not None


class TeamMeta:
    """Metaclass for all team lists."""
    sortkey = MailinglistGroup.team
    viewer_roles = {"persona"}


class GeneralMailinglist:
    """Base class for all mailinglist types.

    Class attributes:

    * `sortkey`: Determines where mailinglists of this type are grouped.
    * `domain`: Determines the domain of the mailinglist.
    * `viewer_roles`: Determines who may view the mailinglist.
      See `may_view()` for details.
    * `relevant_admins`: Determines who may administrate the mailinglist. See
      `is_relevant_admin()` for details.
    * `role_map`: An ordered Dict to determine mailinglist interactions in a
      hierarchical way for trivial mailinglist types.
    * `validation_fields`: A dict of additional fields to be considered
      during validation for mailinglists of this type.

    """
    def __init__(self):
        raise RuntimeError()

    sortkey = MailinglistGroup.other

    domain = Domain.lists

    viewer_roles = {"ml"}

    @classmethod
    def may_view(cls, rs):
        """Determine whether the user may view a mailinglist.

        Instead of overriding this, you should set the `viewer_roles`
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
        """Determine if the user is allowed to administrate a mailinglist.

        Instead of overriding this, you should set the `relevant_admins`
        attribute, so that `ml_admin` may always administrate all mailinglists.

        Relevant class attributes:

        - `relevant_admins`: A set of roles other than `ml_admin` which allows
          a user to administrate a mailinglist. The semantics are similar to
          `@access`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: bool
        """
        return bool((cls.relevant_admins | {"ml_admin"}) & rs.user.roles)

    role_map = OrderedDict()

    @classmethod
    def get_interaction_policy(cls, rs, bc, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        Instead of overriding this, you can set the `role_map` attribute,
        which will automatically take care of the work for trivial mailinglists.

        For more involved interactions, override this method instead.

        This does not do a permission check, because it is not exposed to the
        frontend and does not currently have a way of accessing the relevant
        methods of the MailinglistBackend.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type bc: :py:class:`BackendContainer`
        :type mailinglist: {str: object}
        :type persona_id: int
        :rtype: :py:class`const.MailinglistInteractionPolicy` or None
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls

        if not persona_id:
            roles = rs.user.roles
        else:
            # TODO check for access to the ml? Needs ml_backend.
            persona = bc.core.get_persona(rs, persona_id)
            roles = extract_roles(persona, introspection_only=True)

        for role, pol in cls.role_map.items():
            if role in roles:
                return cls.role_map[role]
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, bc, mailinglist):
        """Retrieve a set of personas, which should be subscribers.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type bc: :py:class:`BackendContainer`
        :type mailinglist: {str: object}
        :rtype: {int}
        """
        return set()

    # Which states not to touch during periodic subscription cleanup.
    protected_states = {const.SubscriptionStates.subscription_override,
                        const.SubscriptionStates.unsubscription_override,
                        const.SubscriptionStates.unsubscribed}

    @classmethod
    def periodic_cleanup(cls, rs, mailinglist):
        """Whether or not to do periodic subscription cleanup on this list.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type mailinglist: {str: object}
        :rtype: bool
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        return True

    # Additional fields for validation. See docstring for details.
    validation_fields = {}


class CdEMailinglist(GeneralMailinglist):
    """Base class for CdE-Mailinglists."""

    sortkey = MailinglistGroup.cde
    viewer_roles = {"cde"}
    relevant_admins = {"cde_admin"}


class EventMailinglist(GeneralMailinglist):
    """Base class for Event-Mailinglists."""

    sortkey = MailinglistGroup.event
    domain = Domain.aka
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
    protected_states = {const.SubscriptionStates.subscription_override}


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
    def get_interaction_policy(cls, rs, bc, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this basically means opt-in for all
        implicit subscribers. See `get_impicit_subscribers`.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return MailinglistInteractionPolicy.invitation_only

        if not persona_id:
            persona_id = rs.user.persona_id

        if bc.event.check_registration_status(
                rs, persona_id, mailinglist['event_id'],
                mailinglist['registration_stati']):
            return MailinglistInteractionPolicy.opt_out
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, bc, mailinglist):
        """Get a list of people that should be on this mailinglist.

        For the `EventAssociatedMailinglist` this means registrations with
        one of the configured stati in any part.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls

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
            constraints=((status_column, QueryOperators.oneof,
                          mailinglist["registration_stati"]),),
            order=tuple())
        data = bc.event.submit_general_query(rs, query, event_id=event["id"])

        return {e["persona.id"] for e in data}


class EventOrgaMailinglist(EventAssociatedMeta, EventMailinglist):
    sortkey = MailinglistGroup.event

    @classmethod
    def get_interaction_policy(cls, rs, bc, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        For the `EventOrgaMailinglist` this means opt-out for orgas only.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls

        # Make event-lists without event link static.
        if mailinglist["event_id"] is None:
            return const.MailinglistInteractionPolicy.invitation_only

        if not persona_id:
            persona_id = rs.user.persona_id

        event = bc.event.get_event(rs, mailinglist["event_id"])
        if persona_id in event["orgas"]:
            return const.MailinglistInteractionPolicy.opt_out
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, bc, mailinglist):
        """Get a list of personas that should be on this mailinglist.

        For the `EventOrgaMailinglist` this means the event's orgas.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls

        if mailinglist["event_id"] is None:
            raise ValueError(n_("No implicit subscribers possible for "
                                "legacy event list."))

        event = unwrap(bc.event.get_events(rs, (mailinglist["event_id"],)))
        return event["orgas"]


class AssemblyAssociatedMailinglist(AssemblyAssociatedMeta, AssemblyMailinglist):
    @classmethod
    def get_interaction_policy(cls, rs, bc, mailinglist, persona_id=None):
        """Determine the MIP of the user or a persona with a mailinglist.

        For the `AssemblyAssociatedMailinglist` this means opt-out for attendees
        of the associated assembly.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        attending = bc.assembly.check_attendance(
            rs, persona_id=persona_id, assembly_id=mailinglist["assembly_id"])

        if attending:
            return const.MailinglistInteractionPolicy.opt_out
        else:
            return None

    @classmethod
    def get_implicit_subscribers(cls, rs, bc, mailinglist):
        """Get a list of people that should be on this mailinglist.

        For the `AssemblyAssociatedMailinglist` this means the attendees of the
        linked assembly.
        """
        assert TYPE_MAP[mailinglist["ml_type"]] == cls
        return bc.assembly.list_attendees(rs, mailinglist["assembly_id"])


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
    MailinglistTypes.general_opt_in: GeneralOptInMailinglist,
    MailinglistTypes.semi_public: SemiPublicMailinglist,
    MailinglistTypes.cdelokal: CdeLokalMailinglist,
}
