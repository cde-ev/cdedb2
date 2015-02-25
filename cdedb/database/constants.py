#!/usr/bin/env python3

"""Translation of numeric constants to semantic values.

This file takes care of encoding mostly enum-like things into the
correct numeric values. The raw values should never be used, instead
their symbolic names provided by this module should be used.
"""

import enum

@enum.unique
class PersonaStati(enum.IntEnum):
    """Spec for field status of core.personas.

    The different statuses have different additional data attached.

    * 0/1/2 ... a matching entry cde.member_data
    * 10 ...  a matching entry cde.member_data which is mostly NULL or
      default values (most queries will need to filter for status in (0, 1))
      archived members may not login, thus is_active must be False
    * 20 ... a matching entry event.user_data
    * 30 ... a matching entry assembly.user_data
    * 40 ... a matching entry ml.user_data

    Searchability (see statusses 0 and 1) means the user has given
    (at any point in time) permission for his data to be accessible
    to other users. This permission is revoked upon leaving the CdE
    and has to be granted again in case of reentry.
    """
    searchmember = 0 #:
    member = 1 #:
    formermember = 2 #:
    archived_member = 10 #:
    event_user = 20 #:
    assembly_user = 30 #:
    ml_user = 40 #:

#: These personas are eligible for using the member search.
SEARCHMEMBER_STATI = {PersonaStati.searchmember}
#: These personas are currently members.
MEMBER_STATI = SEARCHMEMBER_STATI | {PersonaStati.member}
#: These personas where at some point members.
CDE_STATI = MEMBER_STATI | {PersonaStati.formermember}
#: These personas where at some point members (and may be archived).
#: This is somewhat special and should not be used often, since archived
#: members have only a restricted data set available.
ALL_CDE_STATI = CDE_STATI | {PersonaStati.archived_member}
#: These personas may register for an event.
EVENT_STATI = {PersonaStati.searchmember, PersonaStati.member,
               PersonaStati.formermember, PersonaStati.event_user}
#: These personas may participate in an assembly.
ASSEMBLY_STATI = {PersonaStati.searchmember, PersonaStati.member,
                  PersonaStati.assembly_user}
#: These personas may use the mailing lists
ML_STATI = {PersonaStati.searchmember, PersonaStati.member,
            PersonaStati.formermember, PersonaStati.assembly_user,
            PersonaStati.event_user, PersonaStati.ml_user}

@enum.unique
class PrivilegeBits(enum.IntEnum):
    """Spec for field db_privileges of core.personas.

    If db_privileges is 0 no privileges are granted.
    """
    #: global admin privileges (implies all other privileges granted here)
    admin = 2**0
    core_admin = 2**1 #:
    cde_admin = 2**2 #:
    event_admin = 2**3 #:
    ml_admin = 2**4 #:
    assembly_admin = 2**5 #:
    # files_admin = 2**6 #:
    # i25p_admin = 2**7 #:

@enum.unique
class Genders(enum.IntEnum):
    """Spec for field gender of cde.member_data and event.user_data."""
    female = 0 #:
    male = 1 #:
    #: this is a catch-all for complicated reality
    unknown = 2

@enum.unique
class MemberChangeStati(enum.IntEnum):
    """Spec for field change_status of core.changelog."""
    pending = 0 #:
    committed = 1 #:
    superseded = 10 #:
    nacked = 11 #:
    #: replaced by a change which could not wait
    displaced = 12

@enum.unique
class RegistrationPartStati(enum.IntEnum):
    """Spec for field status of event.registration_parts."""
    not_applied = -1 #:
    applied = 0 #:
    participant = 1 #:
    waitlist = 2 #:
    guest = 3 #:
    cancelled = 4 #:
    rejected = 5 #:

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
    unconfirmed = 0
    #: email confirmed, awaiting review
    to_review = 1
    #: reviewed and approved, awaiting persona creation
    approved = 2
    #: finished (persona created, challenge archived)
    finished = 3
    #: reviewed and rejected (also a final state)
    rejected = 10
    #: abandoned and archived (also final)
    timeout = 11

@enum.unique
class SubscriptionPolicy(enum.IntEnum):
    """Regulate (un)subscriptions to mailinglists."""
    #: everybody is subscribed (think CdE-all)
    mandatory = 0
    opt_out = 1 #:
    opt_in = 2 #:
    #: everybody may subscribe, but only after approval
    moderated_opt_in = 3
    #: nobody may subscribe by themselves
    invitation_only = 4

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
    unmoderated = 0 #:
    #: subscribers may post without moderation, but external mail is reviewed
    non_subscribers = 1
    fully_moderated = 2 #:

@enum.unique
class AttachementPolicy(enum.IntEnum):
    """Regulate allowed payloads for mails to lists.

    This is currently only a tri-state, so we implement it as an enum.
    """
    allow = 0 #:
    #: allow the mime-type application/pdf but nothing else
    pdf_only = 1
    forbid = 2 #:

@enum.unique
class MlLogCodes(enum.IntEnum):
    """Available log messages."""
    list_created = 0 #:
    list_changed = 1 #:
    list_deleted = 2 #:
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
