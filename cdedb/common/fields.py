#!/usr/bin/env python3

"""SQL field names of all entities."""

# A set of roles a user may have.
Role = str

# A set of realms a persona belongs to.
Realm = str


# The following dict defines, which additional fields are required for genesis
# request for distinct realms. Additionally, it is used to define for which
# realms genesis requrests are allowed
REALM_SPECIFIC_GENESIS_FIELDS: dict[Realm, tuple[str, ...]] = {
    "ml": tuple(),
    "event": (
        "gender",
        "birthday",
        "telephone",
        "mobile",
        "address_supplement",
        "address",
        "postal_code",
        "location",
        "country",
    ),
    "cde": (
        "gender",
        "birthday",
        "telephone",
        "mobile",
        "address_supplement",
        "address",
        "postal_code",
        "location",
        "country",
        "birth_name",
        "attachment_hash",
        "pevent_id",
        "pcourse_id",
    ),
}

#: Fields of a pending privilege change.
PRIVILEGE_CHANGE_FIELDS = (
    "id",
    "ctime",
    "ftime",
    "persona_id",
    "submitted_by",
    "status",
    "is_meta_admin",
    "is_core_admin",
    "is_cde_admin",
    "is_finance_admin",
    "is_event_admin",
    "is_ml_admin",
    "is_assembly_admin",
    "is_cdelokal_admin",
    "is_complaint_admin",
    "is_auditor",
    "notes",
    "reviewer",
)

#: Fields of an event-specific role
EVENT_ROLE_FIELDS = ('id', 'persona_id', 'event_id')

#: Fields of a registration to an event organized via the CdEDB
REGISTRATION_FIELDS = (
    "id",
    "persona_id",
    "event_id",
    "notes",
    "orga_notes",
    "payment",
    "parental_agreement",
    "mixed_lodging",
    "list_consent",
    "fields",
    "real_persona_id",
    "amount_paid",
    "amount_owed",
    "is_member",
    "amount_owed_by_kind",
    "amount_owed_by_category",
    "amount_owed_by_budget",
)

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = (
    "registration_id",
    "part_id",
    "status",
    "lodgement_id",
    "is_camping_mat",
)

#: Fields of a registration which are specific for each course track
REGISTRATION_TRACK_FIELDS = (
    "registration_id",
    "track_id",
    "course_id",
    "course_instructor",
)

#: Fields of an assembly
ASSEMBLY_FIELDS = (
    "id",
    "title",
    "shortname",
    "description",
    "presider_address",
    "signup_end",
    "is_active",
    "notes",
)

#: Fields of a ballot
BALLOT_FIELDS = (
    "id",
    "assembly_id",
    "title",
    "description",
    "vote_begin",
    "vote_end",
    "vote_extension_end",
    "extended",
    "use_bar",
    "abs_quorum",
    "rel_quorum",
    "quorum",
    "votes",
    "is_tallied",
    "notes",
)

#: Fields of an attachment in the assembly realm (attached either to an
#: assembly or a ballot)
ASSEMBLY_ATTACHMENT_FIELDS = (
    "id",
    "assembly_id",
)

ASSEMBLY_ATTACHMENT_VERSION_FIELDS = (
    "attachment_id",
    "version_nr",
    "title",
    "authors",
    "filename",
    "changenotes",
    "ctime",
    "dtime",
    "file_hash",
)

#: Fields of a semester
ORG_PERIOD_FIELDS = (
    "id",
    "billing_state",
    "billing_done",
    "billing_count",
    "ejection_state",
    "ejection_done",
    "ejection_count",
    "ejection_balance",
    "balance_state",
    "balance_done",
    "balance_trialmembers",
    "balance_total",
    "exmember_balance",
    "exmember_count",
    "exmember_state",
    "exmember_done",
    "archival_notification_state",
    "archival_notification_count",
    "archival_notification_done",
    "archival_state",
    "archival_count",
    "archival_done",
    "semester_done",
)

#: Fielsd of an expuls
EXPULS_PERIOD_FIELDS = (
    "id",
    "addresscheck_state",
    "addresscheck_done",
    "addresscheck_count",
)

#: Fields of one direct debit permit
LASTSCHRIFT_FIELDS = (
    "id",
    "submitted_by",
    "persona_id",
    "iban",
    "account_owner",
    "account_address",
    "granted_at",
    "revoked_at",
    "notes",
)

#: Fields of one interaction on behalf of a direct debit permit
LASTSCHRIFT_TRANSACTION_FIELDS = (
    "id",
    "submitted_by",
    "lastschrift_id",
    "period_id",
    "status",
    "amount",
    "issued_at",
    "payment_date",
    "processed_at",
    "tally",
)
