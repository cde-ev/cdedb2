#!/usr/bin/env python3

"""Translation of numeric constants to semantic values.

This file takes care of encoding mostly enum-like things into the
correct numeric values. The raw values should never be used, instead
their symbolic names provided by this module should be used.
"""

import builtins
import collections
import enum
from functools import cached_property
from typing import TYPE_CHECKING

from cdedb.uncommon.intenum import CdEIntEnum

# these are stored in the database, so provide them here for consistency
from cdedb.uncommon.submanshim import (  # noqa: F401
    SubscriptionAction,
    SubscriptionState,
)

if TYPE_CHECKING:
    from cdedb.models.event.questionnaire import QuestionnaireRow


def n_(x: str) -> str:  # pragma: no cover
    """Clone of :py:func:`cdedb.common.n_` for marking translatable strings."""
    return x


@enum.unique
class Genders(CdEIntEnum):
    """Spec for field gender of core.personas."""

    female = 1  #:
    male = 2  #:
    #: this is a catch-all for complicated reality
    other = 10
    not_specified = 20  #:


@enum.unique
class PersonaChangeStati(CdEIntEnum):
    """Spec for field code of core.changelog."""

    pending = 1  #:
    committed = 2  #:
    superseded = 10  #:
    nacked = 11  #:
    #: replaced by a change which could not wait
    displaced = 12


@enum.unique
class EmailStatus(CdEIntEnum):
    """Spec for status of core.email_status.

    This is intended to be extended in future revisions. Potential further
    states are: whitelist, unconfirmed, mailinglists_disabled, all_disabled,
    removed, unsuccessful_transmission.
    """

    normal = 1
    defect = 10

    @classmethod
    def defect_states(cls) -> tuple["EmailStatus", ...]:
        return (cls.defect,)

    @classmethod
    def notable_states(cls) -> tuple["EmailStatus", ...]:
        """States which should cause a notification.

        In some locations annotating every state could get really noisy.
        """
        return (cls.defect,)


@enum.unique
class RegistrationPartStati(CdEIntEnum):
    """Spec for field status of event.registration_parts."""

    not_applied = -1  #:
    applied = 1  #:
    participant = 2  #:
    waitlist = 3  #:
    guest = 4  #:
    cancelled = 5  #:
    rejected = 6  #:

    @classmethod
    def involved_states(cls) -> tuple["RegistrationPartStati", ...]:
        return (
            RegistrationPartStati.applied,
            RegistrationPartStati.participant,
            RegistrationPartStati.waitlist,
            RegistrationPartStati.guest,
        )

    def is_involved(self) -> bool:
        """Any status which warrants further attention by the orgas."""
        return self in self.involved_states()

    def is_present(self) -> bool:
        """Any status which will be on site for the event."""
        return self in {RegistrationPartStati.participant, RegistrationPartStati.guest}

    def has_to_pay(self) -> bool:
        """Any status which should pay the participation fee."""
        return self in {
            RegistrationPartStati.applied,
            RegistrationPartStati.participant,
            RegistrationPartStati.waitlist,
        }


@enum.unique
class FieldAssociations(CdEIntEnum):
    """Coordinates fields to the entities they are attached to."""

    registration = 1  #:
    course = 2  #:
    lodgement = 3  #:

    @cached_property
    def database_table(self) -> str:
        import cdedb.models.event as models_event  # noqa: PLC0415

        return {
            FieldAssociations.registration: models_event.Registration.database_table,
            FieldAssociations.course: models_event.Course.database_table,
            FieldAssociations.lodgement: models_event.Lodgement.database_table,
        }[self]

    def get_icon(self) -> str:
        icons = {
            FieldAssociations.registration: "user",
            FieldAssociations.course: "book",
            FieldAssociations.lodgement: "home",
        }
        return icons.get(self, repr(self))


@enum.unique
class FieldDatatypes(CdEIntEnum):
    """Spec for the datatypes available as custom data fields."""

    str = 1  #:
    str_multiline = 50  #:
    str_monospace = 55  #:
    bool = 2  #:
    int = 3  #:
    float = 4  #:
    date = 5  #:
    datetime = 6  #:
    non_negative_int = 10  #:
    non_negative_float = 12  #:
    phone = 20  #:
    iban = 30  #:

    @property
    def spec_type(self) -> builtins.str:
        if self == FieldDatatypes.non_negative_float:
            return 'float'
        if self == FieldDatatypes.non_negative_int:
            return 'int'
        if self in {FieldDatatypes.str_multiline, FieldDatatypes.str_monospace}:
            return 'str'
        return self.name

    @property
    def is_str(self) -> builtins.bool:
        return self in {
            FieldDatatypes.str,
            FieldDatatypes.str_multiline,
            FieldDatatypes.str_monospace,
        }

    @property
    def text_rows(self) -> builtins.int:
        if self in {FieldDatatypes.str_multiline, FieldDatatypes.str_monospace}:
            return 5
        return 0


@enum.unique
class QuestionnaireUsages(CdEIntEnum):
    """Where a questionnaire row will be displayed."""

    registration = 1
    additional = 2

    def allow_readonly(self) -> bool:
        """Whether or not rows with this usage are allowed to be readonly."""
        return self == QuestionnaireUsages.additional

    def allow_fee_condition(self) -> bool:
        """Whether or not rows with this usage may use fee condition fields."""
        return self == QuestionnaireUsages.registration

    @property
    def title_level(self) -> int:
        """Heading-level for custom titles in this kind of questionnaire."""
        return 3


@enum.unique
class QuestionnaireRowRole(CdEIntEnum):
    text_only = 1
    event_field = 5
    course_choices = 10
    part_selection = 20
    fee_preview = 30
    list_consent = 40
    mixed_lodging = 50
    foto_notice = 60
    registration_notes = 70
    table_of_contents = 80

    def get_class(self) -> type["QuestionnaireRow"]:
        from cdedb.models.event.questionnaire import (  # noqa: PLC0415
            QuestionnaireRow,
        )

        return QuestionnaireRow.get_class(self)


@enum.unique
class EventPartGroupType(CdEIntEnum):
    # Weak constraints that only produce warnings:
    mutually_exclusive_participants = 1

    # Removed, do not reuse:
    mutually_exclusive_courses = 2

    # Special type that imposes no constraints:
    Statistic = 100

    # Special type for link to mailinglist with limited scope.
    mailinglist_link = 200

    def get_icon(self) -> str:
        return {
            EventPartGroupType.Statistic: "chart-bar",
            EventPartGroupType.mutually_exclusive_participants: "user-lock",
            EventPartGroupType.mailinglist_link: "envelope",
        }[self]

    def is_stats(self) -> bool:
        return self == EventPartGroupType.Statistic


@enum.unique
class CourseTrackGroupType(CdEIntEnum):
    course_choice_sync = 1
    mutually_exclusive_courses = 2

    def get_icon(self) -> str:
        return {
            CourseTrackGroupType.course_choice_sync: "bezier-curve",
            CourseTrackGroupType.mutually_exclusive_courses: "comment-slash",
        }[self]

    def is_sync(self) -> bool:
        return self == CourseTrackGroupType.course_choice_sync


@enum.unique
class EventFeeType(CdEIntEnum):
    """Different kinds of event fees, to be displayed and/or treated differently."""

    # Participation Fee
    common = 1
    solidary_reduction = 10
    solidary_increase = 12
    external = 3

    # Donation
    solidary_donation = 11
    instructor_donation = 6
    followup_donation = 21
    other_donation = 20

    # Reimbursement
    instructor_refund = 5
    crisis_refund = 30
    other_refund = 31

    # Storno
    storno = 2

    def get_icon(self) -> str:
        return {
            EventFeeType.common: "coins",
            EventFeeType.storno: "ban",
            EventFeeType.external: "external-link-alt",
            EventFeeType.instructor_refund: "book",
            EventFeeType.instructor_donation: "book-medical",
            EventFeeType.solidary_reduction: "hand-holding-medical",
            EventFeeType.solidary_donation: "handshake",
            EventFeeType.solidary_increase: "hands-helping",
            EventFeeType.other_donation: "donate",
            EventFeeType.followup_donation: "forward-fast",
            EventFeeType.crisis_refund: "fire-extinguisher",
            EventFeeType.other_refund: "person-military-to-person",
        }[self]

    @property
    def category(self) -> "EventFeeCategory":
        return {
            EventFeeType.common: EventFeeCategory.participation_fee,
            EventFeeType.storno: EventFeeCategory.storno,
            EventFeeType.external: EventFeeCategory.participation_fee,
            EventFeeType.instructor_refund: EventFeeCategory.reimbursement,
            EventFeeType.instructor_donation: EventFeeCategory.donation,
            EventFeeType.solidary_reduction: EventFeeCategory.participation_fee,
            EventFeeType.solidary_donation: EventFeeCategory.donation,
            EventFeeType.solidary_increase: EventFeeCategory.participation_fee,
            EventFeeType.other_donation: EventFeeCategory.donation,
            EventFeeType.followup_donation: EventFeeCategory.donation,
            EventFeeType.crisis_refund: EventFeeCategory.reimbursement,
            EventFeeType.other_refund: EventFeeCategory.reimbursement,
        }[self]

    @property
    def budget(self) -> "EventFeeBudget":
        return {
            EventFeeType.common: EventFeeBudget.expenses,
            EventFeeType.storno: EventFeeBudget.expenses,
            EventFeeType.external: EventFeeBudget.cde,
            EventFeeType.instructor_refund: EventFeeBudget.expenses,
            EventFeeType.instructor_donation: EventFeeBudget.followup,
            EventFeeType.solidary_reduction: EventFeeBudget.solidarity,
            EventFeeType.solidary_donation: EventFeeBudget.solidarity,
            EventFeeType.solidary_increase: EventFeeBudget.solidarity,
            EventFeeType.other_donation: EventFeeBudget.cde,
            EventFeeType.followup_donation: EventFeeBudget.followup,
            EventFeeType.crisis_refund: EventFeeBudget.expenses,
            EventFeeType.other_refund: EventFeeBudget.expenses,
        }[self]

    def optgroup_label(self) -> str:
        return str(self.category)

    def label_addon(self) -> str:
        return str(self.budget)

    def __lt__(self, other: int) -> bool:
        if isinstance(other, self.__class__):
            return self._get_sortkey() < other._get_sortkey()
        return super().__lt__(other)

    def _get_sortkey(self) -> tuple[int, ...]:
        return (self.category, self.budget, self.value)


@enum.unique
class EventFeeCategory(CdEIntEnum):
    participation_fee = 1
    donation = 2
    reimbursement = 3
    storno = 10

    def get_icon(self) -> str:
        return {
            EventFeeCategory.participation_fee: "coins",
            EventFeeCategory.storno: "ban",
            EventFeeCategory.donation: "donate",
            EventFeeCategory.reimbursement: "undo-alt",
        }[self]


@enum.unique
class EventFeeBudget(CdEIntEnum):
    expenses = 1
    solidarity = 2
    followup = 3
    cde = 10
    # other = 20

    def get_icon(self) -> str:
        return {
            EventFeeBudget.expenses: "file-invoice-dollar",
            EventFeeBudget.solidarity: "hands-helping",
            EventFeeBudget.followup: "fast-forward",
            EventFeeBudget.cde: "building-columns",
            # EventFeeBudget.other: "random",
        }[self]


@enum.unique
class NotifyOnRegistration(CdEIntEnum):
    """Options for how often orgas want to be notified about new registrations."""

    # Values > 0 are multiple of the periodic cycle (usually 15 minutes).
    everytime = -1
    never = 0
    hourly = 4
    daily = 4 * 24
    weekly = 4 * 24 * 7

    def send_on_register(self) -> bool:
        return self == NotifyOnRegistration.everytime

    def send_periodically(self) -> bool:
        return self.value > 0


@enum.unique
class GenesisStati(CdEIntEnum):
    """Spec for field status of core.genesis_cases."""

    #: created, data logged, email unconfirmed
    unconfirmed = 1
    #: email confirmed, awaiting review
    to_review = 2
    #: acked by reviewer, but not yet created
    approved = 3
    #: finished (persona created, challenge archived)
    successful = 4
    #: finished (existing persona updated, challenge archived)
    existing_updated = 5
    #: reviewed and rejected (also a final state)
    rejected = 10

    @classmethod
    def finalized_stati(cls) -> set["GenesisStati"]:
        return {cls.successful, cls.existing_updated, cls.rejected}

    def is_finalized(self) -> bool:
        return self in self.finalized_stati()

    def get_icon(self) -> str | None:
        return {
            GenesisStati.unconfirmed: "hourglass-start",
            GenesisStati.to_review: "user-clock",
            GenesisStati.successful: "check",
            GenesisStati.existing_updated: "user-check",
            GenesisStati.rejected: "ban",
        }.get(self)


@enum.unique
class PrivilegeChangeStati(CdEIntEnum):
    """Spec for field status of core.privilege_changes."""

    #: initialized, pending for review
    pending = 1
    #: approved by another admin
    approved = 2
    #: successfully applied
    successful = 3
    #: rejected by another admin
    rejected = 10


@enum.unique
class MailinglistTypes(CdEIntEnum):
    member_mandatory = 1
    member_opt_out = 2
    member_opt_in = 3
    member_moderated_opt_in = 4
    member_invitation_only = 5

    team = 10
    restricted_team = 11

    event_associated = 20
    event_orga = 21
    # The following types used to exist. To avoid conflicts, do not reuse:
    # event_associated_legacy = 22
    # event_orga_legacy = 23
    event_associated_exclusive = 25

    assembly_associated = 30
    assembly_opt_in = 31
    assembly_presider = 32

    general_mandatory = 38
    general_opt_in = 40
    general_moderated_opt_in = 41
    general_invitation_only = 42

    general_moderators = 45
    cdelokal_moderators = 46

    semi_public = 50

    cdelokal = 60

    public_member_implicit = 70

    complaint_admin_implicit = 80
    complaint_enforcer_implicit = 85

    def optgroup_label(self) -> str:
        from cdedb.models.ml import ML_TYPE_MAP  # noqa: PLC0415

        if self in ML_TYPE_MAP:
            return str(ML_TYPE_MAP[self].sortkey)
        return ""


@enum.unique
class MailinglistDomain(CdEIntEnum):
    lists = 1
    aka = 2
    general = 3
    cdelokal = 4

    # The domains are not supported. To avoid conflicts, do not reuse:
    # cdemuenchen = 10
    # dokuforge = 11

    testmail = 100

    def get_domain(self) -> str:
        """Return the actual domain for this enum member."""
        if self not in _DOMAIN_STR_MAP:  # pragma: no cover
            raise NotImplementedError(n_("This domain is not supported."))
        return _DOMAIN_STR_MAP[self]

    def display_str(self) -> str:
        """Return a readable string representation to be displayed in the UI."""
        return self.get_domain()

    def get_acceptable_aliases(self) -> set[str]:
        """Return alias domains which might exist for a given type.

        This is only used to allow emails to <local_part>@alias to be sent to the list
        members without moderation."""
        if self == MailinglistDomain.aka:
            return {"tickets.cde-ev.de"}
        if self == MailinglistDomain.lists:
            return {"cde-ev.de", "lists.schuelerakademie.de", "tickets.cde-ev.de"}
        if self == MailinglistDomain.cdelokal:
            return {"cdelokal.schuelerakademie.de"}
        return set()


# Instead of importing this, call str() on a MailinglistDomain.
_DOMAIN_STR_MAP: dict[MailinglistDomain, str] = {
    MailinglistDomain.lists: "lists.cde-ev.de",
    MailinglistDomain.aka: "aka.cde-ev.de",
    MailinglistDomain.general: "cde-ev.de",
    MailinglistDomain.cdelokal: "cdelokal.cde-ev.de",
    MailinglistDomain.testmail: "testmail.cde-ev.de",
}


@enum.unique
class MailinglistRosterVisibility(CdEIntEnum):
    """Visibility of the subscriber list to non-moderators or admins.

    Roster of inactive mailinglists are always hidden.
    """

    none = 1
    subscribable = 10
    viewers = 20


@enum.unique
class ModerationPolicy(CdEIntEnum):
    """Regulate posting of mail to a list."""

    unmoderated = 1  #:
    #: subscribers may post without moderation, but external mail is reviewed
    non_subscribers = 2
    fully_moderated = 3  #:


@enum.unique
class AttachmentPolicy(CdEIntEnum):
    """Regulate allowed payloads for mails to lists.

    This is currently only a tri-state, so we implement it as an enum.
    """

    allow = 1  #:
    #: allow the mime-type application/pdf but nothing else
    pdf_only = 2
    forbid = 3  #:


@enum.unique
class LastschriftTransactionStati(CdEIntEnum):
    """Basically store the outcome (if it exists) of a transaction."""

    issued = 1  #:
    skipped = 2  #:
    success = 10  #:
    failure = 11  #:
    cancelled = 12  #:
    rollback = 20  #:

    def is_finalized(self) -> bool:
        """Whether the transaction was already tallied."""
        return self in {
            LastschriftTransactionStati.success,
            LastschriftTransactionStati.failure,
            LastschriftTransactionStati.cancelled,
            LastschriftTransactionStati.rollback,
        }


@enum.unique
class PastInstitutions(CdEIntEnum):
    """Insitutions for (primarily past) events, used for sorting into categories."""

    cde = 1  #:
    dsa = 20  #:
    dja = 40  #:
    jgw = 60  #:
    bub = 70  #:
    basf = 80  #:
    van = 200  #:
    eisenberg = 400  #:
    other = 1000  #:
    private = 2000  #:

    @classmethod
    def main_insitution(cls) -> "PastInstitutions":
        return PastInstitutions.cde

    @property
    def shortname(self) -> str:
        shortnames = {
            self.cde: "CdE",
            self.dsa: "DSA",
            self.dja: "DJA",
            self.jgw: "JGW",
            self.bub: "BuB",
            self.basf: "BASF",
            self.van: "VAN",
            self.eisenberg: "FV Eisenberg",
            self.other: "Sonst.",
            self.private: "Privat",
        }
        return shortnames.get(self, str(self))


@enum.unique
class PastOrgaKind(CdEIntEnum):
    """CdE, DSA, JGW etc have different notions of 'Orgas'."""

    none = 0
    orga = 1  # of CdE events
    al = 2  # of DSAs etc,
    co_al = 4

    @property
    def shortname(self) -> str | None:
        return {
            self.none: None,
            self.orga: None,  # we use "Orga" as longname and shortname
            self.al: "AL",
            self.co_al: "Co-AL",
        }[self]


@enum.unique
class PastMusicKind(CdEIntEnum):
    """Kinds of 'Kursübergreifende Musik' organizers."""

    none = 0
    ensemble = 1
    kuemu = 2
    kueak = 4

    @property
    def shortname(self) -> str | None:
        return {
            self.none: None,
            self.ensemble: "EL",
            self.kuemu: "KüMu",
            self.kueak: "KüAK",
        }[self]


@enum.unique
class PastInstructorKind(CdEIntEnum):
    none = 0
    kl = 1
    co_kl = 2

    @property
    def shortname(self) -> str | None:
        return {
            self.none: None,
            self.kl: "KL",
            self.co_kl: "Co-KL",
        }[self]


@enum.unique
class ComplaintKind(CdEIntEnum):
    """Rough kinds a complaint may have"""

    physical_sexual_transgression = 1
    physical_nonsexual_violence = 2
    nonphysical_sexual_transgression = 3
    verbal_abuse = 4
    volunteer_harassment = 11
    other_harassment = 15
    mobbing = 21
    bad_administration = 31
    other = 1001


@enum.unique
class ComplaintInvolvementType(CdEIntEnum):
    """Types of involvements in a complaint case."""

    affected = 1
    appellant = 11  #: presumed not to be primarily affected. Always informed
    target = 21  #: whom a complaint is "against"
    other = 51  #: especially for cases which are no actual complaints
    withheld = 100  #: hides complaint even if otherwise visible to user

    def adverse(self) -> set["ComplaintInvolvementType"]:
        t = ComplaintInvolvementType
        return {
            t.affected: {t.target},
            t.appellant: {t.target},
            t.target: {t.affected, t.appellant},
        }.get(self, set())

    def get_icon(self) -> str:
        return {
            ComplaintInvolvementType.affected: "user-injured",
            ComplaintInvolvementType.appellant: "comment",
            ComplaintInvolvementType.target: "crosshairs",
            ComplaintInvolvementType.other: "question",
            ComplaintInvolvementType.withheld: "eye-slash",
        }[self]

    @property
    def shortname(self) -> str:
        return {
            ComplaintInvolvementType.affected: "Bt",
            ComplaintInvolvementType.appellant: "Bf",
            ComplaintInvolvementType.target: "Zp",
            ComplaintInvolvementType.other: "Sonst",
            ComplaintInvolvementType.withheld: "Pst",
        }[self]


@enum.unique
class ComplaintEntryType(CdEIntEnum):
    """Type of entries in the history of a complaint.

    Some things are shown in the entries, even though they are pulled in
    from the logs instead. Those can not be replaced later on.
    """

    # Initial
    generic_information = 101  #:

    # Statements
    provisional_statement_given = 201  #:
    statement_signed = 211  #:
    # statement_withdrawn = 221  #:
    statement_cleared = 231  #: there has been consent to use this for further cases
    statement_sent = 241  #: statement has been printed and sent to Vereinsarchiv
    statement_received = 246  #: statement has been received at Vereinsarchiv

    # Agreements
    agreement = 301  #: the factions reached a formal agreement as a partial resolution
    agreement_measure = 311  #:

    # Provisional arbitration
    provisional_to_arbcom = 401  #:
    provisional_measure = 411  #:

    # Definite arbitration
    definite_to_arbcom = 501  #:
    definite_measure = 511  #:

    # Measure details
    measure_explanation = 601
    measure_comment = 611

    # Conclusion
    faction_summary = 1001  #: of some companions for a faction
    synthesis = 1011  #:

    # Special
    revocation_explanation = 10001  #: Can be child of everything

    @classmethod
    def measure_types(cls) -> set["ComplaintEntryType"]:
        return {cls.agreement_measure, cls.provisional_measure, cls.definite_measure}

    @property
    def is_measure(self) -> bool:
        return self in self.measure_types()

    @classmethod
    def visible_types(cls) -> set["ComplaintEntryType"]:
        return cls.measure_types()

    @classmethod
    def hidden_types(cls) -> set["ComplaintEntryType"]:
        return set(cls) - cls.visible_types()

    @property
    def _is_hidden(self) -> bool:
        return self not in self.visible_types()

    @classmethod
    def _get_children_map(cls) -> dict["ComplaintEntryType", set["ComplaintEntryType"]]:
        et = ComplaintEntryType
        children: dict[ComplaintEntryType, set[ComplaintEntryType]]
        children = collections.defaultdict(set)
        children.update({
            et.provisional_statement_given: {
                et.statement_signed,
                et.statement_cleared,
                et.statement_sent,
                et.statement_received,
            },
            et.agreement: {et.agreement_measure},
            et.agreement_measure: {
                et.measure_explanation,
                et.measure_comment,
            },
            et.provisional_to_arbcom: {et.provisional_measure},
            et.provisional_measure: {
                et.measure_explanation,
                et.measure_comment,
            },
            et.definite_to_arbcom: {et.definite_measure},
            et.definite_measure: {
                et.measure_explanation,
                et.measure_comment,
            },
        })
        for t in et:
            children[t].add(et.revocation_explanation)
        return children

    @classmethod
    def all_children(cls) -> set["ComplaintEntryType"]:
        ret = set()
        for children in cls._get_children_map().values():
            ret.update(children)
        return ret

    @property
    def possible_children(self) -> set["ComplaintEntryType"]:
        return self._get_children_map().get(self, set())

    @property
    def has_description(self) -> bool:
        et = ComplaintEntryType
        return self not in {
            et.statement_signed,
            et.statement_sent,
            et.statement_received,
        }

    @property
    def is_hidden(self) -> bool:
        return self.has_description and self._is_hidden

    @property
    def is_provisional(self) -> bool:
        return self in {
            # TODO: Clarify why no privisional statement.
            ComplaintEntryType.provisional_measure,
            ComplaintEntryType.provisional_to_arbcom,
        }

    @property
    def has_concerned(self) -> bool:
        return self in {
            ComplaintEntryType.provisional_statement_given,
            ComplaintEntryType.provisional_measure,
            ComplaintEntryType.definite_measure,
            ComplaintEntryType.agreement_measure,
        }

    @property
    def allows_attachment(self) -> bool:
        return self in {
            ComplaintEntryType.generic_information,
            ComplaintEntryType.provisional_statement_given,
        }

    def get_icon(self) -> str:
        et = ComplaintEntryType
        return {
            et.generic_information: "info",
            et.provisional_statement_given: "file-lines",
            et.statement_signed: "file-signature",
            et.statement_cleared: "file-export",
            et.statement_sent: "envelope-open-text",
            et.statement_received: "box-archive",
            et.agreement: "handshake",
            et.agreement_measure: "shield-heart",
            et.provisional_to_arbcom: "scale-unbalanced",
            et.provisional_measure: "bandage",
            et.definite_to_arbcom: "scale-unbalanced",
            et.definite_measure: "shield-halved",
            et.measure_explanation: "scale-balanced",
            et.measure_comment: "file-shield",
            et.faction_summary: "clipboard-user",
            et.synthesis: "clipboard-check",
            et.revocation_explanation: "rotate-left",
        }[self]

    @property
    def right_shortname(self) -> str:
        et = ComplaintEntryType
        return {
            et.statement_signed: n_("signed"),
            et.statement_cleared: n_("cleared"),
            et.statement_sent: n_("sent"),
            et.statement_received: n_("received"),
            et.agreement_measure: n_("measure"),
            et.provisional_measure: n_("measure"),
            et.definite_measure: n_("measure"),
            et.measure_explanation: n_("explanation"),
            et.measure_comment: n_("comment"),
            et.revocation_explanation: n_("revoked"),
        }.get(self, str(self))

    @property
    def left_shortname(self) -> str:
        et = ComplaintEntryType
        return {
            et.provisional_statement_given: n_("Statement_[[in a case]]"),
            et.agreement: n_("Agreement"),
            et.agreement_measure: n_("Measure"),
            et.provisional_to_arbcom: n_("Provisional Arbcom"),
            et.provisional_measure: n_("Provisional measure"),
            et.definite_to_arbcom: n_("Arbcom"),
            et.definite_measure: n_("Measure"),
            et.revocation_explanation: n_("Revocation"),
        }.get(self, str(self))


@enum.unique
class CoreLogCodes(CdEIntEnum):
    """Available log messages core.log."""

    # Persona
    persona_creation = 1  #:
    persona_change = 2  #:
    persona_archived = 3  #:
    persona_dearchived = 4  #:
    persona_purged = 5  #:
    realm_change = 40  #:
    username_change = 50  #:

    # Password
    password_change = 10  #:
    password_reset_cookie = 11  #:
    password_reset = 12  #:
    password_invalidated = 13  #:

    # Genesis
    genesis_request = 20  #:
    genesis_approved = 21  #:
    genesis_rejected = 22  #:
    genesis_deleted = 23  #:
    genesis_verified = 24  #:
    genesis_merged = 25  #:
    genesis_change = 28  #:

    # Privilege Change
    privilege_change_pending = 30  #:
    privilege_change_approved = 31  #:
    privilege_change_rejected = 32  #:

    # Other
    quota_violation = 60  #:
    modify_email_status = 70  #:
    delete_email_status = 71  #:
    send_anonymous_message = 100  #:
    reply_to_anonymous_message = 101  #:
    rotate_anonymous_message = 102  #:

    def optgroup_label(self) -> str:
        return {
            self.persona_creation: n_("Persona"),
            self.persona_change: n_("Persona"),
            self.persona_archived: n_("Persona"),
            self.persona_dearchived: n_("Persona"),
            self.persona_purged: n_("Persona"),
            self.realm_change: n_("Persona"),
            self.username_change: n_("Persona"),
            self.password_change: n_("Password"),
            self.password_reset_cookie: n_("Password"),
            self.password_reset: n_("Password"),
            self.password_invalidated: n_("Password"),
            self.genesis_request: n_("Genesis"),
            self.genesis_approved: n_("Genesis"),
            self.genesis_rejected: n_("Genesis"),
            self.genesis_deleted: n_("Genesis"),
            self.genesis_verified: n_("Genesis"),
            self.genesis_merged: n_("Genesis"),
            self.genesis_change: n_("Genesis"),
            self.privilege_change_pending: n_("Privilege Change"),
            self.privilege_change_approved: n_("Privilege Change"),
            self.privilege_change_rejected: n_("Privilege Change"),
            self.quota_violation: n_("Other"),
            self.modify_email_status: n_("Other"),
            self.delete_email_status: n_("Other"),
            self.send_anonymous_message: n_("Other"),
            self.reply_to_anonymous_message: n_("Other"),
            self.rotate_anonymous_message: n_("Other"),
        }.get(self, n_("Other"))


@enum.unique
class ComplaintLogCodes(CdEIntEnum):
    case_created = 1  #:
    case_changed_kind = 2  #:
    case_changed_grave = 3  #:
    case_changed_summary = 4  #:
    case_changed_start_date = 5  #:
    case_changed_end_date = 6  #:

    # case_deleted = 21  #:
    # case_concluded = 22  #:
    # case_aborted = 23  #:

    involved_added = 41  #:
    involved_removed = 42  #:
    involved_informed = 46  #:
    involved_uninformed = 47  #:

    companion_added = 51  #:
    companion_withdrawn = 52  #:
    companion_reinstated = 53  #:
    companion_removed = 54  #:

    enforcer_added = 101  #:
    enforcer_removed = 102  #:

    case_unlocked = 201  #:
    concealed_case_detected = 202  #:

    @property
    def is_historic(self) -> bool:
        """List log codes which are relevant to display on a case history"""
        return 1 < self.value < 100

    def optgroup_label(self) -> str:
        if self.name.startswith("case"):
            return n_("Case")
        if self.name.startswith("involved"):
            return n_("Involved")
        if self.name.startswith("companion"):
            return n_("Companion")
        if self.name.startswith("enforcer"):
            return n_("Enforcer")
        return n_("Other")


@enum.unique
class CdeLogCodes(CdEIntEnum):
    """Available log messages cde.log."""

    semester_bill = 10
    semester_bill_with_addresscheck = 11
    semester_ejection = 12
    semester_balance_update = 13
    semester_exmember_balance = 16
    semester_advance = 1
    expuls_addresscheck = 20
    expuls_addresscheck_skipped = 21
    expuls_advance = 2
    automated_archival_notification_done = 30
    automated_archival_done = 31


@enum.unique
class FinanceLogCodes(CdEIntEnum):
    """Available log messages cde.finance_log."""

    # Do not reuse:
    # new_member = 1  #:

    # Membership
    gain_membership = 2  #:
    lose_membership = 3  #:
    end_trial_membership = 12  #:
    start_trial_membership = 15  #:
    honorary_membership_granted = 51  #:
    honorary_membership_revoked = 52  #:

    # Balance
    increase_balance = 10  #:
    deduct_membership_fee = 11  #:
    manual_balance_correction = 13  #:
    remove_balance_on_archival = 14  #:
    remove_exmember_balance = 17  #:

    # Lastschrift
    grant_lastschrift = 20  #:
    revoke_lastschrift = 21  #:
    modify_lastschrift = 22  #:
    lastschrift_deleted = 23  #:

    # Lastschrift Transaction
    lastschrift_transaction_issue = 30  #:
    lastschrift_transaction_success = 31  #:
    lastschrift_transaction_failure = 32  #:
    lastschrift_transaction_skip = 33  #:
    lastschrift_transaction_cancelled = 34  #:
    lastschrift_transaction_revoked = 35  #:

    # Other
    #: Fallback for strange cases
    other = 99

    def optgroup_label(self) -> str:
        return {
            self.gain_membership: n_("Membership"),
            self.lose_membership: n_("Membership"),
            self.end_trial_membership: n_("Membership"),
            self.start_trial_membership: n_("Membership"),
            self.honorary_membership_granted: n_("Membership"),
            self.honorary_membership_revoked: n_("Membership"),
            self.increase_balance: n_("Balance"),
            self.deduct_membership_fee: n_("Balance"),
            self.manual_balance_correction: n_("Balance"),
            self.remove_balance_on_archival: n_("Balance"),
            self.remove_exmember_balance: n_("Balance"),
            self.grant_lastschrift: n_("Lastschrift"),
            self.revoke_lastschrift: n_("Lastschrift"),
            self.modify_lastschrift: n_("Lastschrift"),
            self.lastschrift_deleted: n_("Lastschrift"),
            self.lastschrift_transaction_issue: n_("Lastschrift Transaction"),
            self.lastschrift_transaction_success: n_("Lastschrift Transaction"),
            self.lastschrift_transaction_failure: n_("Lastschrift Transaction"),
            self.lastschrift_transaction_skip: n_("Lastschrift Transaction"),
            self.lastschrift_transaction_cancelled: n_("Lastschrift Transaction"),
            self.lastschrift_transaction_revoked: n_("Lastschrift Transaction"),
        }.get(self, n_("Other"))


@enum.unique
class EventLogCodes(CdEIntEnum):
    """Available log messages event.log."""

    # Event (new codes should start at 1000)
    event_created = 1  #:
    event_changed = 2  #:
    event_deleted = 3  #:
    event_archived = 4  #:
    event_locked = 60  #:
    event_unlocked = 61  #:

    # Registrations (2000)
    registration_created = 50  #:
    registration_changed = 51  #:
    registration_deleted = 52  #:
    registration_status_changed = 300  #:
    registration_payment_received = 55  #:
    registration_payment_reimbursed = 56  #:
    registration_payment_received_orga = 57  #:
    registration_payment_reimbursed_orga = 58  #:

    # Courses (3000)
    course_created = 40  #:
    course_changed = 41  #:
    course_segment_deleted = 420  #:
    course_segment_created = 421  #:
    course_segment_deactivated = 430  #:
    course_segment_activated = 431  #:
    course_deleted = 44  #:

    # Lodgements (4000)
    lodgement_changed = 25  #:
    lodgement_created = 26  #:
    lodgement_deleted = 27  #:
    lodgement_group_created = 70  #:
    lodgement_group_changed = 71  #:
    lodgement_group_deleted = 72  #:

    # Parts & Tracks (5000)
    part_created = 15  #:
    part_changed = 16  #:
    part_deleted = 17  #:
    track_added = 35  #:
    track_updated = 36  #:
    track_removed = 37  #:

    # Fields (6000)
    field_added = 20  #:
    field_updated = 21  #:
    field_removed = 22  #:
    questionnaire_changed = 30  #:

    # Fees (7000)
    event_fee_created = 80  #:
    event_fee_modified = 81  #:
    event_fee_deleted = 82  #:
    personalized_fee_amount_set = 400  #:
    personalized_fee_amount_deleted = 401  #:

    # Queries (8000)
    query_stored = 90  #:
    query_deleted = 91  #:
    custom_filter_created = 95  #:
    custom_filter_changed = 96  #:
    custom_filter_deleted = 97  #:

    # Checkin (9000)
    checkin_added = 500  #:
    checkout_added = 505  #:
    checkin_changed = 510  #:
    checkout_changed = 515  #:
    checkin_period_deleted = 530  #:

    # Part Groups (10_000)
    part_group_created = 100  #:
    part_group_changed = 101  #:
    part_group_deleted = 102  #:
    part_group_link_created = 105  #:
    part_group_link_deleted = 106  #:

    # Track Groups (11_000)
    track_group_created = 110  #:
    track_group_changed = 111  #:
    track_group_deleted = 112  #:
    track_group_link_created = 113  #:
    track_group_link_deleted = 114  #:

    # Orga Tokens (12_000)
    orga_token_created = 200  #:
    orga_token_changed = 201  #:
    orga_token_revoked = 202  #:
    orga_token_deleted = 203  #:

    # Event Roles (13_000)
    helper_added = 7  #:
    helper_removed = 8  #:
    orga_added = 10  #:
    orga_removed = 11  #:
    caretaker_added = 12  #:
    caretaker_removed = 13  #:

    # Other (100_000)
    event_partial_import = 62  #:
    minor_form_updated = 85  #:
    minor_form_removed = 86  #:
    event_balanced = 600  #:
    event_unbalanced = 610  #:
    registration_approved = 700  #:
    registration_unapproved = 710  #:
    checkin_helper_added = 800  #:
    checkin_helper_removed = 810  #:

    def optgroup_label(self) -> str:
        return {
            self.event_created: n_("Event"),
            self.event_changed: n_("Event"),
            self.event_deleted: n_("Event"),
            self.event_archived: n_("Event"),
            self.event_locked: n_("Event"),
            self.event_unlocked: n_("Event"),
            self.registration_created: n_("Registrations"),
            self.registration_changed: n_("Registrations"),
            self.registration_deleted: n_("Registrations"),
            self.registration_payment_received: n_("Registrations"),
            self.registration_payment_reimbursed: n_("Registrations"),
            self.registration_payment_received_orga: n_("Registrations"),
            self.registration_payment_reimbursed_orga: n_("Registrations"),
            self.registration_status_changed: n_("Registrations"),
            self.course_created: n_("Courses"),
            self.course_changed: n_("Courses"),
            self.course_deleted: n_("Courses"),
            self.course_segment_deleted: n_("Courses"),
            self.course_segment_created: n_("Courses"),
            self.course_segment_deactivated: n_("Courses"),
            self.course_segment_activated: n_("Courses"),
            self.lodgement_changed: n_("Lodgements"),
            self.lodgement_deleted: n_("Lodgements"),
            self.lodgement_created: n_("Lodgements"),
            self.lodgement_group_created: n_("Lodgements"),
            self.lodgement_group_changed: n_("Lodgements"),
            self.lodgement_group_deleted: n_("Lodgements"),
            self.part_created: n_("Event Parts & Course Tracks"),
            self.part_changed: n_("Event Parts & Course Tracks"),
            self.part_deleted: n_("Event Parts & Course Tracks"),
            self.track_added: n_("Event Parts & Course Tracks"),
            self.track_updated: n_("Event Parts & Course Tracks"),
            self.track_removed: n_("Event Parts & Course Tracks"),
            self.field_added: n_("Custom Fields"),
            self.field_updated: n_("Custom Fields"),
            self.field_removed: n_("Custom Fields"),
            self.questionnaire_changed: n_("Custom Fields"),
            self.event_fee_created: n_("Fees"),
            self.event_fee_modified: n_("Fees"),
            self.event_fee_deleted: n_("Fees"),
            self.personalized_fee_amount_set: n_("Fees"),
            self.personalized_fee_amount_deleted: n_("Fees"),
            self.query_stored: n_("Queries"),
            self.query_deleted: n_("Queries"),
            self.custom_filter_created: n_("Queries"),
            self.custom_filter_changed: n_("Queries"),
            self.custom_filter_deleted: n_("Queries"),
            self.checkin_added: n_("Checkin"),
            self.checkout_added: n_("Checkin"),
            self.checkin_changed: n_("Checkin"),
            self.checkout_changed: n_("Checkin"),
            self.checkin_period_deleted: n_("Checkin"),
            self.part_group_created: n_("Part & Track Groups"),
            self.part_group_changed: n_("Part & Track Groups"),
            self.part_group_deleted: n_("Part & Track Groups"),
            self.part_group_link_created: n_("Part & Track Groups"),
            self.part_group_link_deleted: n_("Part & Track Groups"),
            self.track_group_created: n_("Part & Track Groups"),
            self.track_group_changed: n_("Part & Track Groups"),
            self.track_group_deleted: n_("Part & Track Groups"),
            self.track_group_link_created: n_("Part & Track Groups"),
            self.track_group_link_deleted: n_("Part & Track Groups"),
            self.orga_token_created: n_("Orga Tokens"),
            self.orga_token_changed: n_("Orga Tokens"),
            self.orga_token_revoked: n_("Orga Tokens"),
            self.orga_token_deleted: n_("Orga Tokens"),
            self.helper_added: n_("Event Roles"),
            self.helper_removed: n_("Event Roles"),
            self.orga_added: n_("Event Roles"),
            self.orga_removed: n_("Event Roles"),
            self.caretaker_added: n_("Event Roles"),
            self.caretaker_removed: n_("Event Roles"),
        }.get(self, n_("Other"))


@enum.unique
class PastEventLogCodes(CdEIntEnum):
    """Available log messages past_event.log."""

    event_created = 1  #:
    event_changed = 2  #:
    event_deleted = 3  #:
    course_created = 10  #:
    course_changed = 11  #:
    course_deleted = 12  #:
    participant_set = 20  #:
    participant_removed = 21  #:
    course_assignment_set = 25  #:
    course_assignment_removed = 26  #:
    # The following log codes used to exist. To avoid conflicts, do not reuse:
    # institution_created = 30  #:
    # institution_changed = 31  #:
    # institution_deleted = 32  #:


@enum.unique
class AssemblyLogCodes(CdEIntEnum):
    """Available log messages core.log."""

    # Assembly
    assembly_created = 1  #:
    assembly_changed = 2  #:
    assembly_concluded = 3  #:
    assembly_deleted = 4  #:
    assembly_presider_added = 35  #:
    assembly_presider_removed = 36  #:

    # Ballot
    ballot_created = 10  #:
    ballot_changed = 11  #:
    ballot_deleted = 12  #:
    ballot_extended = 13  #:
    ballot_tallied = 14  #:
    candidate_added = 20  #:
    candidate_updated = 21  #:
    candidate_removed = 22  #:

    # Attachment
    attachment_added = 40  #:
    attachment_removed = 41  #:
    attachment_changed = 42  #:
    attachment_version_added = 50  #:
    attachment_version_removed = 51  #:
    attachment_version_changed = 52  #:
    attachment_ballot_link_created = 43  #:
    attachment_ballot_link_deleted = 44  #:

    # Other
    new_attendee = 30  #:

    def optgroup_label(self) -> str:
        return {
            self.assembly_created: n_("Assembly"),
            self.assembly_changed: n_("Assembly"),
            self.assembly_concluded: n_("Assembly"),
            self.assembly_deleted: n_("Assembly"),
            self.assembly_presider_added: n_("Assembly"),
            self.assembly_presider_removed: n_("Assembly"),
            self.ballot_created: n_("Ballot"),
            self.ballot_changed: n_("Ballot"),
            self.ballot_deleted: n_("Ballot"),
            self.ballot_extended: n_("Ballot"),
            self.ballot_tallied: n_("Ballot"),
            self.candidate_added: n_("Ballot"),
            self.candidate_updated: n_("Ballot"),
            self.candidate_removed: n_("Ballot"),
            self.attachment_added: n_("Attachment"),
            self.attachment_removed: n_("Attachment"),
            self.attachment_changed: n_("Attachment"),
            self.attachment_version_added: n_("Attachment"),
            self.attachment_version_removed: n_("Attachment"),
            self.attachment_version_changed: n_("Attachment"),
            self.attachment_ballot_link_created: n_("Attachment"),
            self.attachment_ballot_link_deleted: n_("Attachment"),
        }.get(self, n_("Other"))


@enum.unique
class MlLogCodes(CdEIntEnum):
    """Available log messages for ml.log."""

    # Mailinglist
    list_created = 1  #:
    list_changed = 2  #:
    list_deleted = 3  #:
    moderator_added = 10  #:
    moderator_removed = 11  #:

    # Subscribers
    subscribed = 21  #: SubscriptionState.subscribed
    unsubscribed = 23  #: SubscriptionState.unsubscribed
    marked_override = 24  #: SubscriptionState.subscription_override
    marked_blocked = 25  #: SubscriptionState.unsubscription_override
    subscription_changed = 22  #: This is now used for address changes.
    automatically_removed = 28  #:

    # Subscription requests
    subscription_requested = 20  #: SubscriptionState.subscription_requested
    request_approved = 30  #:
    request_denied = 31  #:
    request_cancelled = 32  #:
    request_blocked = 33  #:

    # Message Moderation
    moderate_accept = 50  #:
    moderate_reject = 51  #:
    moderate_discard = 52  #:
    whitelist_added = 12  #:
    whitelist_removed = 13  #:

    # Other
    email_trouble = 40  #:
    reset = 27  #:

    @classmethod
    def from_subman(cls, action: SubscriptionAction) -> "MlLogCodes":
        log_code_map = {
            SubscriptionAction.subscribe: cls.subscribed,
            SubscriptionAction.unsubscribe: cls.unsubscribed,
            SubscriptionAction.request_subscription: cls.subscription_requested,
            SubscriptionAction.cancel_request: cls.request_cancelled,
            SubscriptionAction.approve_request: cls.request_approved,
            SubscriptionAction.deny_request: cls.request_denied,
            SubscriptionAction.block_request: cls.request_blocked,
            SubscriptionAction.add_subscriber: cls.subscribed,
            SubscriptionAction.add_subscription_override: cls.marked_override,
            SubscriptionAction.add_unsubscription_override: cls.marked_blocked,
            SubscriptionAction.remove_subscriber: cls.unsubscribed,
            SubscriptionAction.remove_subscription_override: cls.subscribed,
            SubscriptionAction.remove_unsubscription_override: cls.unsubscribed,
            SubscriptionAction.reset: cls.reset,
        }
        return log_code_map[action]

    def optgroup_label(self) -> str:
        return {
            self.list_created: n_("Mailinglist"),
            self.list_changed: n_("Mailinglist"),
            self.list_deleted: n_("Mailinglist"),
            self.moderator_added: n_("Mailinglist"),
            self.moderator_removed: n_("Mailinglist"),
            self.subscribed: n_("Subscribers"),
            self.unsubscribed: n_("Subscribers"),
            self.marked_override: n_("Subscribers"),
            self.marked_blocked: n_("Subscribers"),
            self.subscription_changed: n_("Subscribers"),
            self.automatically_removed: n_("Subscribers"),
            self.subscription_requested: n_("Subscription Requests"),
            self.request_approved: n_("Subscription Requests"),
            self.request_denied: n_("Subscription Requests"),
            self.request_cancelled: n_("Subscription Requests"),
            self.request_blocked: n_("Subscription Requests"),
            self.moderate_accept: n_("Message Moderation"),
            self.moderate_reject: n_("Message Moderation"),
            self.moderate_discard: n_("Message Moderation"),
            self.whitelist_added: n_("Message Moderation"),
            self.whitelist_removed: n_("Message Moderation"),
        }.get(self, n_("Other"))


@enum.unique
class LockType(CdEIntEnum):
    """Types of Locks."""

    mailman = 1  #:
