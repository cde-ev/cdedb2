#!/usr/bin/env python3

"""Translation of numeric constants to semantic values.

This file takes care of encoding mostly enum-like things into the
correct numeric values. The raw values should never be used, instead
their symbolic names provided by this module should be used.
"""

import enum

from cdedb.common import _

@enum.unique
class Genders(enum.IntEnum):
    """Spec for field gender of core.personas."""
    female = 1 #:
    male = 2 #:
    #: this is a catch-all for complicated reality
    unknown = 10

@enum.unique
class MemberChangeStati(enum.IntEnum):
    """Spec for field change_status of core.changelog."""
    pending = 1 #:
    committed = 2 #:
    superseded = 10 #:
    nacked = 11 #:
    #: replaced by a change which could not wait
    displaced = 12

@enum.unique
class RegistrationPartStati(enum.IntEnum):
    """Spec for field status of event.registration_parts."""
    not_applied = -1 #:
    applied = 1 #:
    participant = 2 #:
    waitlist = 3 #:
    guest = 4 #:
    cancelled = 5 #:
    rejected = 6 #:

    def is_involved(self):
        """Any status which warrants further attention by the orgas.

        :rtype: bool
        """
        return self in (RegistrationPartStati.applied,
                        RegistrationPartStati.participant,
                        RegistrationPartStati.waitlist,
                        RegistrationPartStati.guest,)

    def is_present(self):
        """Any status which will be on site for the event.

        :rtype: bool
        """
        return self in (RegistrationPartStati.participant,
                        RegistrationPartStati.guest,)

@enum.unique
class GenesisStati(enum.IntEnum):
    """Spec for field case_status of core.genesis_cases."""
    #: created, email unconfirmed
    unconfirmed = 1
    #: email confirmed, awaiting review
    to_review = 2
    #: reviewed and approved, awaiting persona creation
    approved = 3
    #: finished (persona created, challenge archived)
    finished = 4
    #: reviewed and rejected (also a final state)
    rejected = 10
    #: abandoned and archived (also final)
    timeout = 11

@enum.unique
class SubscriptionPolicy(enum.IntEnum):
    """Regulate (un)subscriptions to mailinglists."""
    #: everybody is subscribed (think CdE-all)
    mandatory = 1
    opt_out = 2 #:
    opt_in = 3 #:
    #: everybody may subscribe, but only after approval
    moderated_opt_in = 4
    #: nobody may subscribe by themselves
    invitation_only = 5

    def is_additive(self):
        """Differentiate between additive and subtractive mailing lists.

        Additive means, that only explicit subscriptions are on the list,
        while subtractive means, that only explicit unsubscriptions are not
        on the list.

        :rtype: bool
        """
        return self in (SubscriptionPolicy.opt_in,
                        SubscriptionPolicy.moderated_opt_in,
                        SubscriptionPolicy.invitation_only)

    def privileged_transition(self, new_state):
        """Most of the time subscribing or unsubscribing is simply allowed,
        but in some cases you must be privileged to do it.

        :rtype: bool
        """
        if new_state:
            return self == SubscriptionPolicy.invitation_only
        else:
            return self == SubscriptionPolicy.mandatory

@enum.unique
class ModerationPolicy(enum.IntEnum):
    """Regulate posting of mail to a list."""
    unmoderated = 1 #:
    #: subscribers may post without moderation, but external mail is reviewed
    non_subscribers = 2
    fully_moderated = 3 #:

@enum.unique
class AttachmentPolicy(enum.IntEnum):
    """Regulate allowed payloads for mails to lists.

    This is currently only a tri-state, so we implement it as an enum.
    """
    allow = 1 #:
    #: allow the mime-type application/pdf but nothing else
    pdf_only = 2
    forbid = 3 #:

@enum.unique
class AudiencePolicy(enum.IntEnum):
    """Regulate who may subscribe to a mailing list by status."""
    everybody = 1 #:
    require_assembly = 2 #:
    require_event = 3 #:
    require_cde = 4 #:
    require_member = 5 #:

    @staticmethod
    def applicable(roles):
        """Which audience policies apply to a user with the passed roles?

        :type roles: [str]
        :rtype: [AudiencePolicy]
        """
        ret = []
        if "ml" in roles:
            ret.append(AudiencePolicy.everybody)
        if "assembly" in roles:
            ret.append(AudiencePolicy.require_assembly)
        if "event" in roles:
            ret.append(AudiencePolicy.require_event)
        if "cde" in roles:
            ret.append(AudiencePolicy.require_cde)
        if "member" in roles:
            ret.append(AudiencePolicy.require_member)
        return ret

    def check(self, roles):
        """Test if the status is enough to satisfy this policy.

        :type roles: [str]
        :rtype: bool
        """
        if self == AudiencePolicy.everybody:
            return "ml" in roles
        elif self == AudiencePolicy.require_assembly:
            return "assembly" in roles
        elif self == AudiencePolicy.require_event:
            return "event" in roles
        elif self == AudiencePolicy.require_cde:
            return "cde" in roles
        elif self == AudiencePolicy.require_member:
            return "member" in roles
        else:
            raise RuntimeError(_("Impossible."))

    def sql_test(self):
        """Provide SQL query to check this policy.

        :rtype: str
        """
        if self == AudiencePolicy.everybody:
            return "is_ml_realm = True"
        elif self == AudiencePolicy.require_assembly:
            return "is_assembly_realm = True"
        elif self == AudiencePolicy.require_event:
            return "is_event_realm = True"
        elif self == AudiencePolicy.require_cde:
            return "is_cde_realm = True"
        elif self == AudiencePolicy.require_member:
            return "is_member = True"
        else:
            raise RuntimeError(_("Impossible."))

@enum.unique
class LastschriftTransactionStati(enum.IntEnum):
    """Basically store the outcome (if it exists) of a transaction."""
    issued = 1 #:
    skipped = 2 #:
    success = 10 #:
    failure = 11 #:
    cancelled = 12 #:
    rollback = 20 #:

    def is_finalized(self):
        """Whether the transaction was already tallied.

        :rtype: bool
        """
        return self in (LastschriftTransactionStati.success,
                        LastschriftTransactionStati.failure,
                        LastschriftTransactionStati.cancelled,
                        LastschriftTransactionStati.rollback)
@enum.unique
class CoreLogCodes(enum.IntEnum):
    """Available log messages core.log."""
    persona_creation = 1 #:
    persona_change = 2 #:
    password_change = 10 #:
    password_reset_cookie = 11 #:
    password_reset = 12 #:
    password_generated = 13 #:
    genesis_request = 20 #:
    genesis_approved = 21 #:
    genesis_rejected = 22 #:

@enum.unique
class CdeLogCodes(enum.IntEnum):
    """Available log messages cde.log."""
    advance_semester = 1 #:
    advance_expuls = 2 #:

@enum.unique
class FinanceLogCodes(enum.IntEnum):
    """Available log messages cde.finance_log."""
    new_member = 1 #:
    gain_membership = 2 #:
    lose_membership = 3 #:
    increase_balance = 10 #:
    deduct_membership_fee = 11 #:
    end_trial_membership = 12 #:
    grant_lastschrift = 20 #:
    revoke_lastschrift = 21 #:
    modify_lastschrift = 22 #:
    lastschrift_transaction_issue = 30 #:
    lastschrift_transaction_success = 31 #:
    lastschrift_transaction_failure = 32 #:
    lastschrift_transaction_skip = 33 #:
    lastschrift_transaction_cancelled = 34 #:
    lastschrift_transaction_revoked = 35 #:
    #: Fallback for strange cases
    other = 99

@enum.unique
class EventLogCodes(enum.IntEnum):
    """Available log messages event.log."""
    event_created = 1 #:
    event_changed = 2 #:
    orga_added = 10 #:
    orga_removed = 11 #:
    part_created = 15 #:
    part_changed = 16 #:
    part_deleted = 17 #:
    field_added = 20 #:
    field_updated = 21 #:
    field_removed = 22 #:
    lodgement_changed = 25 #:
    lodgement_created = 26 #:
    lodgement_deleted = 27 #:
    questionnaire_changed = 30 #:
    course_created = 40 #:
    course_changed = 41 #:
    course_parts_changed = 42 #:
    course_part_activity_changed = 43 #:
    registration_created = 50 #:
    registration_changed = 51 #:
    event_locked = 60 #:
    event_unlocked = 61 #:

@enum.unique
class PastEventLogCodes(enum.IntEnum):
    """Available log messages past_event.log."""
    event_created = 1 #:
    event_changed = 2 #:
    course_created = 10 #:
    course_changed = 11 #:
    course_deleted = 12 #:
    participant_added = 20 #:
    participant_removed = 21 #:
    institution_created = 30 #:
    institution_changed = 31 #:
    institution_deleted = 32 #:

@enum.unique
class AssemblyLogCodes(enum.IntEnum):
    """Available log messages core.log."""
    assembly_created = 1 #:
    assembly_changed = 2 #:
    assembly_concluded = 3 #:
    ballot_created = 10 #:
    ballot_changed = 11 #:
    ballot_deleted = 12 #:
    ballot_extended = 13 #:
    ballot_tallied = 14 #:
    candidate_added = 20 #:
    candidate_updated = 21 #:
    candidate_removed = 22 #:
    new_attendee = 30 #:
    attachment_added = 40 #:
    attachment_removed = 41 #:

@enum.unique
class MlLogCodes(enum.IntEnum):
    """Available log messages for ml.log."""
    list_created = 1 #:
    list_changed = 2 #:
    list_deleted = 3 #:
    moderator_added = 10 #:
    moderator_removed = 11 #:
    whitelist_added = 12 #:
    whitelist_removed = 13 #:
    subscription_requested = 20 #:
    subscribed = 21 #:
    subscription_changed = 22 #:
    unsubscribed = 23 #:
    request_approved = 30 #:
    request_denied = 31 #:
    request_cancelled = 32 #:
