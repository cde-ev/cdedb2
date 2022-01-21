#!/usr/bin/env python3

"""Translation of numeric constants to semantic values.

This file takes care of encoding mostly enum-like things into the
correct numeric values. The raw values should never be used, instead
their symbolic names provided by this module should be used.
"""

import enum
from typing import Dict, Set

from cdedb.subman.machine import (  # pylint: disable=unused-import # noqa: F401
    SubscriptionAction, SubscriptionState,
)


def n_(x: str) -> str:  # pragma: no cover
    """Clone of :py:func:`cdedb.common.n_` for marking translatable strings."""
    return x


@enum.unique
class Genders(enum.IntEnum):
    """Spec for field gender of core.personas."""
    female = 1  #:
    male = 2  #:
    #: this is a catch-all for complicated reality
    other = 10
    not_specified = 20  #:


@enum.unique
class MemberChangeStati(enum.IntEnum):
    """Spec for field code of core.changelog."""
    pending = 1  #:
    committed = 2  #:
    superseded = 10  #:
    nacked = 11  #:
    #: replaced by a change which could not wait
    displaced = 12


@enum.unique
class RegistrationPartStati(enum.IntEnum):
    """Spec for field status of event.registration_parts."""
    not_applied = -1  #:
    applied = 1  #:
    participant = 2  #:
    waitlist = 3  #:
    guest = 4  #:
    cancelled = 5  #:
    rejected = 6  #:

    def is_involved(self) -> bool:
        """Any status which warrants further attention by the orgas."""
        return self in (RegistrationPartStati.applied,
                        RegistrationPartStati.participant,
                        RegistrationPartStati.waitlist,
                        RegistrationPartStati.guest,)

    def is_present(self) -> bool:
        """Any status which will be on site for the event."""
        return self in (RegistrationPartStati.participant,
                        RegistrationPartStati.guest,)


@enum.unique
class FieldAssociations(enum.IntEnum):
    """Coordinates fields to the entities they are attached to."""
    registration = 1  #:
    course = 2  #:
    lodgement = 3  #:

    def get_icon(self) -> str:
        icons = {
            FieldAssociations.registration: "user",
            FieldAssociations.course: "book",
            FieldAssociations.lodgement: "home",
        }
        return icons.get(self, repr(self))


@enum.unique
class FieldDatatypes(enum.IntEnum):
    """Spec for the datatypes available as custom data fields."""
    str = 1  #:
    bool = 2  #:
    int = 3  #:
    float = 4  #:
    date = 5  #:
    datetime = 6  #:


@enum.unique
class QuestionnaireUsages(enum.IntEnum):
    """Where a questionnaire row will be displayed."""
    registration = 1
    additional = 2

    def allow_readonly(self) -> bool:
        """Whether or not rows with this usage are allowed to be readonly."""
        return self == QuestionnaireUsages.additional

    def allow_fee_modifier(self) -> bool:
        """Whether or not rows with this usage may use fee modifier fields."""
        return self == QuestionnaireUsages.registration


@enum.unique
class EventPartGroupType(enum.IntEnum):
    Statistic = 100

    def get_icon(self) -> str:
        return {
            EventPartGroupType.Statistic: "chart-bar",
        }[self]


@enum.unique
class GenesisStati(enum.IntEnum):
    """Spec for field case_status of core.genesis_cases."""
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
    def finalized_stati(cls) -> Set["GenesisStati"]:
        return {cls.successful, cls.existing_updated, cls.rejected}

    def is_finalized(self) -> bool:
        return self in self.finalized_stati()


@enum.unique
class PrivilegeChangeStati(enum.IntEnum):
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
class MailinglistTypes(enum.IntEnum):
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

    assembly_associated = 30
    assembly_opt_in = 31
    assembly_presider = 32

    general_mandatory = 38
    general_opt_in = 40

    general_moderators = 45
    cdelokal_moderators = 46

    semi_public = 50

    cdelokal = 60


@enum.unique
class MailinglistDomain(enum.IntEnum):
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


# Instead of importing this, call str() on a MailinglistDomain.
_DOMAIN_STR_MAP: Dict[MailinglistDomain, str] = {
    MailinglistDomain.lists: "lists.cde-ev.de",
    MailinglistDomain.aka: "aka.cde-ev.de",
    MailinglistDomain.general: "cde-ev.de",
    MailinglistDomain.cdelokal: "cdelokal.cde-ev.de",
    MailinglistDomain.testmail: "testmail.cde-ev.de",
}


@enum.unique
class ModerationPolicy(enum.IntEnum):
    """Regulate posting of mail to a list."""
    unmoderated = 1  #:
    #: subscribers may post without moderation, but external mail is reviewed
    non_subscribers = 2
    fully_moderated = 3  #:


@enum.unique
class AttachmentPolicy(enum.IntEnum):
    """Regulate allowed payloads for mails to lists.

    This is currently only a tri-state, so we implement it as an enum.
    """
    allow = 1  #:
    #: allow the mime-type application/pdf but nothing else
    pdf_only = 2
    forbid = 3  #:


@enum.unique
class LastschriftTransactionStati(enum.IntEnum):
    """Basically store the outcome (if it exists) of a transaction."""
    issued = 1  #:
    skipped = 2  #:
    success = 10  #:
    failure = 11  #:
    cancelled = 12  #:
    rollback = 20  #:

    def is_finalized(self) -> bool:
        """Whether the transaction was already tallied."""
        return self in {LastschriftTransactionStati.success,
                        LastschriftTransactionStati.failure,
                        LastschriftTransactionStati.cancelled,
                        LastschriftTransactionStati.rollback}


@enum.unique
class CoreLogCodes(enum.IntEnum):
    """Available log messages core.log."""
    persona_creation = 1  #:
    persona_change = 2  #:
    persona_archived = 3  #:
    persona_dearchived = 4  #:
    persona_purged = 5  #:
    password_change = 10  #:
    password_reset_cookie = 11  #:
    password_reset = 12  #:
    password_invalidated = 13  #:
    genesis_request = 20  #:
    genesis_approved = 21  #:
    genesis_rejected = 22  #:
    genesis_deleted = 23  #:
    genesis_verified = 24  #:
    genesis_merged = 25  #:
    privilege_change_pending = 30  #:
    privilege_change_approved = 31  #:
    privilege_change_rejected = 32  #:
    realm_change = 40  #:
    username_change = 50  #:
    quota_violation = 60  #:


@enum.unique
class CdeLogCodes(enum.IntEnum):
    """Available log messages cde.log."""
    semester_bill = 10
    semester_bill_with_addresscheck = 11
    semester_ejection = 12
    semester_balance_update = 13
    semester_advance = 1
    expuls_addresscheck = 20
    expuls_addresscheck_skipped = 21
    expuls_advance = 2
    automated_archival_notification_done = 30
    automated_archival_done = 31


@enum.unique
class FinanceLogCodes(enum.IntEnum):
    """Available log messages cde.finance_log."""
    new_member = 1  #:
    gain_membership = 2  #:
    lose_membership = 3  #:
    increase_balance = 10  #:
    deduct_membership_fee = 11  #:
    end_trial_membership = 12  #:
    manual_balance_correction = 13  #:
    grant_lastschrift = 20  #:
    revoke_lastschrift = 21  #:
    modify_lastschrift = 22  #:
    lastschrift_deleted = 23  #:
    lastschrift_transaction_issue = 30  #:
    lastschrift_transaction_success = 31  #:
    lastschrift_transaction_failure = 32  #:
    lastschrift_transaction_skip = 33  #:
    lastschrift_transaction_cancelled = 34  #:
    lastschrift_transaction_revoked = 35  #:
    #: Fallback for strange cases
    other = 99


@enum.unique
class EventLogCodes(enum.IntEnum):
    """Available log messages event.log."""
    event_created = 1  #:
    event_changed = 2  #:
    event_deleted = 3  #:
    event_archived = 4  #:
    orga_added = 10  #:
    orga_removed = 11  #:
    part_created = 15  #:
    part_changed = 16  #:
    part_deleted = 17  #:
    field_added = 20  #:
    field_updated = 21  #:
    field_removed = 22  #:
    lodgement_changed = 25  #:
    lodgement_created = 26  #:
    lodgement_deleted = 27  #:
    questionnaire_changed = 30  #:
    track_added = 35  #:
    track_updated = 36  #:
    track_removed = 37  #:
    course_created = 40  #:
    course_changed = 41  #:
    course_segments_changed = 42  #:
    course_segment_activity_changed = 43  #:
    course_deleted = 44  #:
    registration_created = 50  #:
    registration_changed = 51  #:
    registration_deleted = 52  #:
    event_locked = 60  #:
    event_unlocked = 61  #:
    event_partial_import = 62  #:
    lodgement_group_created = 70  #:
    lodgement_group_changed = 71  #:
    lodgement_group_deleted = 72  #:
    fee_modifier_created = 80  #:
    fee_modifier_changed = 81  #:
    fee_modifier_deleted = 82  #:
    minor_form_updated = 85  #:
    minor_form_removed = 86  #:
    query_stored = 90  #:
    query_deleted = 91  #:
    part_group_created = 100  #:
    part_group_changed = 101  #:
    part_group_deleted = 102  #:
    part_group_link_created = 105  #:
    part_group_link_deleted = 106  #:


@enum.unique
class PastEventLogCodes(enum.IntEnum):
    """Available log messages past_event.log."""
    event_created = 1  #:
    event_changed = 2  #:
    event_deleted = 3  #:
    course_created = 10  #:
    course_changed = 11  #:
    course_deleted = 12  #:
    participant_added = 20  #:
    participant_removed = 21  #:
    institution_created = 30  #:
    institution_changed = 31  #:
    institution_deleted = 32  #:


@enum.unique
class AssemblyLogCodes(enum.IntEnum):
    """Available log messages core.log."""
    assembly_created = 1  #:
    assembly_changed = 2  #:
    assembly_concluded = 3  #:
    assembly_deleted = 4  #:
    ballot_created = 10  #:
    ballot_changed = 11  #:
    ballot_deleted = 12  #:
    ballot_extended = 13  #:
    ballot_tallied = 14  #:
    candidate_added = 20  #:
    candidate_updated = 21  #:
    candidate_removed = 22  #:
    new_attendee = 30  #:
    assembly_presider_added = 35  #:
    assembly_presider_removed = 36  #:
    attachment_added = 40  #:
    attachment_removed = 41  #:
    attachment_changed = 42  #:
    attachment_ballot_link_created = 43  #:
    attachment_ballot_link_deleted = 44  #:
    attachment_version_added = 50  #:
    attachment_version_removed = 51  #:
    attachment_version_changed = 52  #:


@enum.unique
class MlLogCodes(enum.IntEnum):
    """Available log messages for ml.log."""
    list_created = 1  #:
    list_changed = 2  #:
    list_deleted = 3  #:
    moderator_added = 10  #:
    moderator_removed = 11  #:
    whitelist_added = 12  #:
    whitelist_removed = 13  #:
    subscription_requested = 20  #: SubscriptionState.subscription_requested
    subscribed = 21  #: SubscriptionState.subscribed
    subscription_changed = 22  #: This is now used for address changes.
    unsubscribed = 23  #: SubscriptionState.unsubscribed
    marked_override = 24  #: SubscriptionState.subscription_override
    marked_blocked = 25  #: SubscriptionState.unsubscription_override
    reset = 27  #:
    automatically_removed = 28  #:
    request_approved = 30  #:
    request_denied = 31  #:
    request_cancelled = 32  #:
    request_blocked = 33  #:
    email_trouble = 40  #:
    moderate_accept = 50  #:
    moderate_reject = 51  #:
    moderate_discard = 52  #:

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
