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

    Searchability (see statusses 0 and 1) means the user has given
    (at any point in time) permission for his data to be accessible
    to other users. This permission is revoked upon leaving the CdE
    and has to be granted again in case of reentry.
    """
    search_member = 0 #:
    member = 1 #:
    former_member = 2 #:
    archived_member = 10 #:
    event_user = 20 #:
    assembly_user = 30 #:

#: These personas are eligible for using the member search.
SEARCHMEMBER_STATI = {PersonaStati.search_member}
#: These personas are currently members.
MEMBER_STATI = SEARCHMEMBER_STATI | {PersonaStati.member}
#: These personas where at some point members.
CDE_STATI = MEMBER_STATI | {PersonaStati.former_member}
#: These personas where at some point members (and may be archived).
#: This is somewhat special and should not be used often, since archived
#: members have only a restricted data set available.
ALL_CDE_STATI = CDE_STATI | {PersonaStati.archived_member}
#: These personas may register for an event.
EVENT_STATI = {PersonaStati.search_member, PersonaStati.member,
                  PersonaStati.former_member, PersonaStati.event_user}
#: These personas may participate in an assembly.
ASSEMBLY_STATI = {PersonaStati.search_member, PersonaStati.member,
                     PersonaStati.assembly_user}

@enum.unique
class PrivilegeBits(enum.IntEnum):
    """Spec for field db_privileges of core.personas.

    If db_privileges is 0 no privileges are granted.
    """
    #: global admin privileges (implies all other privileges granted here)
    admin = 1
    core_admin = 2 #:
    cde_admin = 4 #:
    event_admin = 8 #:
    ml_admin = 16 #:
    assembly_admin = 32 #:
    files_admin = 64 #:
    i25p_admin = 128 #:

@enum.unique
class Genders(enum.IntEnum):
    """Spec for field gender of cde.member_data and event.user_data."""
    female = 0 #:
    male = 1 #:
    #: this is a catch-all for complicated reality
    unknown = 2

@enum.unique
class MemberChangeStati(enum.IntEnum):
    """Spec for field change_status of cde.changelog."""
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

@enum.unique
class PersonaCreationStati(enum.IntEnum):
    """Spec for field challenge_status of core.persona_creation_challenges."""
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
