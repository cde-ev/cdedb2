#!/usr/bin/env python3

"""SQL field names of all entities."""

from typing import Dict, Set, Tuple

import cdedb.database.constants as const
from cdedb.common.n_ import n_

# A set of roles a user may have.
Role = str

# A set of realms a persona belongs to.
Realm = str


META_INFO_FIELDS = (
    n_("Finanzvorstand_Name"), n_("Finanzvorstand_Vorname"), n_("Finanzvorstand_Ort"),
    n_("Finanzvorstand_Adresse_Einzeiler"), n_("Finanzvorstand_Adresse_Zeile2"),
    n_("Finanzvorstand_Adresse_Zeile3"), n_("Finanzvorstand_Adresse_Zeile4"),
    n_("CdE_Konto_Inhaber"), n_("CdE_Konto_IBAN"), n_("CdE_Konto_BIC"),
    n_("CdE_Konto_Institut"), n_("Vorstand"),
    n_("banner_before_login"), n_("banner_after_login"), n_("banner_genesis"),
    n_("cde_misc")
)

#: All columns deciding on the current status of a persona
PERSONA_STATUS_FIELDS = (
    "is_active", "is_meta_admin", "is_core_admin", "is_cde_admin",
    "is_finance_admin", "is_event_admin", "is_ml_admin", "is_assembly_admin",
    "is_cde_realm", "is_event_realm", "is_ml_realm", "is_assembly_realm",
    "is_cdelokal_admin", "is_auditor", "is_member", "is_searchable", "is_archived",
    "is_purged",
)

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_CORE_FIELDS = PERSONA_STATUS_FIELDS + (
    "id", "username", "display_name", "family_name", "given_names",
    "title", "name_supplement")

#: Names of columns associated to a cde (former)member
PERSONA_CDE_FIELDS = PERSONA_CORE_FIELDS + (
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country", "birth_name",
    "address_supplement2", "address2", "postal_code2", "location2",
    "country2", "weblink", "specialisation", "affiliation", "timeline",
    "interests", "free_form", "balance", "decided_search", "trial_member",
    "bub_search", "foto", "paper_expuls")

#: Names of columns associated to an event user. This should be a subset of
#: :py:data:`PERSONA_CDE_FIELDS` to facilitate upgrading of event users to
#: members.
PERSONA_EVENT_FIELDS = PERSONA_CORE_FIELDS + (
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country")

#: Names of columns associated to a ml user.
PERSONA_ML_FIELDS = PERSONA_CORE_FIELDS

#: Names of columns associated to an assembly user.
PERSONA_ASSEMBLY_FIELDS = PERSONA_CORE_FIELDS

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_ALL_FIELDS = PERSONA_CDE_FIELDS + ("notes",)

#: Fields of a persona creation case.
GENESIS_CASE_FIELDS = (
    "id", "ctime", "username", "given_names", "family_name",
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country", "birth_name", "attachment_hash",
    "realm", "notes", "case_status", "reviewer", "pevent_id", "pcourse_id")

# The following dict defines, which additional fields are required for genesis
# request for distinct realms. Additionally, it is used to define for which
# realms genesis requrests are allowed
REALM_SPECIFIC_GENESIS_FIELDS: Dict[Realm, Tuple[str, ...]] = {
    "ml": tuple(),
    "event": ("gender", "birthday", "telephone", "mobile",
              "address_supplement", "address", "postal_code", "location",
              "country"),
    "cde": ("gender", "birthday", "telephone", "mobile",
            "address_supplement", "address", "postal_code", "location",
            "country", "birth_name", "attachment_hash", "pevent_id", "pcourse_id"),
}

# This defines which fields are available for which realm. They are cumulative.
PERSONA_FIELDS_BY_REALM: Dict[Role, Set[str]] = {
    'persona': {
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "notes"
    },
    'ml': set(),
    'assembly': set(),
    'event': {
        "gender", "birthday", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country"
    },
    'cde': {
        "birth_name", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "is_searchable", "paper_expuls",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2",
    }
}

# Some of the above fields cannot be edited by the users themselves.
# These are defined here.
RESTRICTED_FIELDS_BY_REALM: Dict[Role, Set[str]] = {
    'persona': {
        "notes",
    },
    'ml': set(),
    'assembly': set(),
    'event': {
        "gender", "birthday",
    },
    'cde': {
        "is_searchable",
    }
}


def get_persona_fields_by_realm(roles: Set[Role], restricted: bool = True
                                ) -> Set[str]:
    """Helper to retrieve the appropriate fields for a user.

    :param restricted: If True, only return fields the user may change
        themselves, i.e. remove the restricted fields."""
    ret: Set[str] = set()
    for role, fields in PERSONA_FIELDS_BY_REALM.items():
        if role in roles:
            ret |= fields
            if restricted:
                ret -= RESTRICTED_FIELDS_BY_REALM[role]
    return ret


#: Fields of a pending privilege change.
PRIVILEGE_CHANGE_FIELDS = (
    "id", "ctime", "ftime", "persona_id", "submitted_by", "status", "is_meta_admin",
    "is_core_admin", "is_cde_admin", "is_finance_admin", "is_event_admin",
    "is_ml_admin", "is_assembly_admin", "is_cdelokal_admin", "is_auditor", "notes",
    "reviewer",
)

#: Fields for institutions of events
INSTITUTION_FIELDS = ("id", "title", "shortname")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "shortname", "institution", "description",
                     "tempus", "participant_info")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "institution", "description", "shortname", "registration_start",
    "registration_soft_limit", "registration_hard_limit", "iban", "nonmember_surcharge",
    "orga_address", "registration_text", "mail_text", "use_additional_questionnaire",
    "notes", "participant_info", "offline_lock", "is_visible",
    "is_course_list_visible", "is_course_state_visible", "is_participant_list_visible",
    "is_course_assignment_visible", "is_cancelled", "is_archived", "lodge_field",
    "camping_mat_field", "course_room_field")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "shortname", "part_begin",
                     "part_end", "fee", "waitlist_field")

PART_GROUP_FIELDS = ("id", "event_id", "title", "shortname", "notes", "constraint_type")

#: Fields of a track where courses can happen
COURSE_TRACK_FIELDS = ("id", "part_id", "title", "shortname", "num_choices",
                       "min_choices", "sortkey")

#: Fields of an extended attribute associated to an event entity
FIELD_DEFINITION_FIELDS = (
    "id", "event_id", "field_name", "title", "sortkey", "kind", "association",
    "checkin", "entries",
)

#: Fields of a modifier for an event_parts fee.
FEE_MODIFIER_FIELDS = ("id", "part_id", "modifier_name", "amount", "field_id")

#: Fields of a concluded course
PAST_COURSE_FIELDS = ("id", "pevent_id", "nr", "title", "description")

#: Fields of a course associated to an event organized via the CdEDB
COURSE_FIELDS = ("id", "event_id", "title", "description", "nr", "shortname",
                 "instructors", "max_size", "min_size", "notes", "fields")

#: Fields specifying in which part a course is available
COURSE_SEGMENT_FIELDS = ("id", "course_id", "track_id", "is_active")

#: Fields of a registration to an event organized via the CdEDB
REGISTRATION_FIELDS = (
    "id", "persona_id", "event_id", "notes", "orga_notes", "payment",
    "parental_agreement", "mixed_lodging", "checkin", "list_consent", "fields",
    "real_persona_id", "amount_paid", "amount_owed")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "status",
                            "lodgement_id", "is_camping_mat")

#: Fields of a registration which are specific for each course track
REGISTRATION_TRACK_FIELDS = ("registration_id", "track_id", "course_id",
                             "course_instructor")

#: Fields of a lodgement group
LODGEMENT_GROUP_FIELDS = ("id", "event_id", "title")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "title", "regular_capacity",
                    "camping_mat_capacity", "notes", "group_id", "fields")

# Fields of a row in a questionnaire.
# (This can be displayed in different places according to `kind`).
QUESTIONNAIRE_ROW_FIELDS = ("event_id", "field_id", "pos", "title", "info",
                            "input_size", "readonly", "default_value", "kind")

#: Fields for a stored event query.
STORED_EVENT_QUERY_FIELDS = (
    "id", "event_id", "query_name", "scope", "serialized_query")

#: Fields of a mailing list entry (that is one mailinglist)
MAILINGLIST_FIELDS = (
    "id", "title", "address", "local_part", "domain", "description",
    "mod_policy", "notes", "attachment_policy", "ml_type",
    "subject_prefix", "maxsize", "is_active", "event_id", "registration_stati",
    "assembly_id")

#: Fields of a mailinglist which may be changed by all moderators, even restricted ones
RESTRICTED_MOD_ALLOWED_FIELDS = {
    "description", "mod_policy", "notes", "attachment_policy", "subject_prefix",
    "maxsize"}

#: Fields of a mailinglist which require full moderator access to be changed
FULL_MOD_REQUIRING_FIELDS = {
    'registration_stati'}

#: Fields of a mailinglist which may be changed by (full) moderators
MOD_ALLOWED_FIELDS = RESTRICTED_MOD_ALLOWED_FIELDS | FULL_MOD_REQUIRING_FIELDS

#: Fields of an assembly
ASSEMBLY_FIELDS = ("id", "title", "shortname", "description", "presider_address",
                   "signup_end", "is_active", "notes")

#: Fields of a ballot
BALLOT_FIELDS = (
    "id", "assembly_id", "title", "description", "vote_begin", "vote_end",
    "vote_extension_end", "extended", "use_bar", "abs_quorum", "rel_quorum", "quorum",
    "votes", "is_tallied", "notes")

#: Fields of an attachment in the assembly realm (attached either to an
#: assembly or a ballot)
ASSEMBLY_ATTACHMENT_FIELDS = ("id", "assembly_id")

ASSEMBLY_ATTACHMENT_VERSION_FIELDS = ("attachment_id", "version_nr", "title",
                                      "authors", "filename", "ctime", "dtime",
                                      "file_hash")

#: Fields of a semester
ORG_PERIOD_FIELDS = (
    "id", "billing_state", "billing_done", "billing_count",
    "ejection_state", "ejection_done", "ejection_count", "ejection_balance",
    "balance_state", "balance_done", "balance_trialmembers", "balance_total",
    "archival_notification_state", "archival_notification_count",
    "archival_notification_done", "archival_state", "archival_count", "archival_done",
    "semester_done")

#: Fielsd of an expuls
EXPULS_PERIOD_FIELDS = (
    "id", "addresscheck_state", "addresscheck_done", "addresscheck_count")

#: Fields of one direct debit permit
LASTSCHRIFT_FIELDS = (
    "id", "submitted_by", "persona_id", "amount", "iban",
    "account_owner", "account_address", "granted_at", "revoked_at", "notes")

#: Fields of one interaction on behalf of a direct debit permit
LASTSCHRIFT_TRANSACTION_FIELDS = (
    "id", "submitted_by", "lastschrift_id", "period_id", "status", "amount",
    "issued_at", "processed_at", "tally")

#: Datatype and Association of special purpose event fields
EVENT_FIELD_SPEC: Dict[
    str, Tuple[Set[const.FieldDatatypes], Set[const.FieldAssociations]]] = {
    'lodge_field': ({const.FieldDatatypes.str}, {const.FieldAssociations.registration}),
    'camping_mat_field': (
        {const.FieldDatatypes.bool}, {const.FieldAssociations.registration}),
    'course_room_field': ({const.FieldDatatypes.str}, {const.FieldAssociations.course}),
    'waitlist': ({const.FieldDatatypes.int}, {const.FieldAssociations.registration}),
    'fee_modifier': (
        {const.FieldDatatypes.bool}, {const.FieldAssociations.registration}),
}

LOG_FIELDS_COMMON = ("codes", "persona_id", "submitted_by", "change_note", "offset",
                     "length", "time_start", "time_stop")
