#!/usr/bin/env python3

"""Provide all default queries used for "speed dialing".

All query-scopes are keys of the DEFAULT_QUERIES dict, mapping to a dict of their
default query names mapping to the query definition.

Only exception are the per-event-queries, since they need some dynamic information
about the event to be created. They can be obtained by calling the respective functions.
"""


import cdedb.database.constants as const
import cdedb.models.event as models_event
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope, QuerySpec
from cdedb.common.roles import ADMIN_KEYS
from cdedb.common.sorting import xsorted


def generate_event_registration_default_queries(
        event: models_event.Event, spec: QuerySpec,
) -> dict[str, Query]:
    """
    Generate default queries for registration_query.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The Event for which to generate the queries
    :param spec: The Query Spec, dynamically generated for the event
    :return: Dict of default queries
    """
    scope = QueryScope.registration

    default_fields_of_interest = (
        "persona.family_name", "persona.given_names", "persona.username",
    )
    payment_fields_of_interest = (
        "reg.payment", "reg.amount_paid", "reg.amount_owed", "reg.remaining_owed",
    )

    default_sort = (
        ("persona.family_name", True),
        ("persona.given_names", True),
        ("reg.id", True),
    )
    payment_sort = (
        ("reg.payment", True),
    )

    all_part_stati_column = ",".join(
        f"part{part_id}.status" for part_id in xsorted(event.parts))
    any_part_participant_constraint = (
        all_part_stati_column, QueryOperators.equal,
        const.RegistrationPartStati.participant.value,
    )

    dokuteam_course_picture_fields_of_interest = [
        "persona.id", "persona.given_names", "persona.family_name"]
    for track_id in event.tracks:
        dokuteam_course_picture_fields_of_interest.append(f"course{track_id}.nr")
        dokuteam_course_picture_fields_of_interest.append(
            f"track{track_id}.is_course_instructor")

    dokuteam_dokuforge_fields_of_interest = [
        "persona.id", "persona.given_names", "persona.family_name", "persona.username"]
    for track_id in event.tracks:
        dokuteam_dokuforge_fields_of_interest.append(f"course{track_id}.nr")
        dokuteam_dokuforge_fields_of_interest.append(
            f"track{track_id}.is_course_instructor")

    dokuteam_address_fields_of_interest = [
        "persona.given_names", "persona.family_name", "persona.address",
        "persona.address_supplement", "persona.postal_code", "persona.location",
        "persona.country"]

    queries = {
        n_("00_query_event_registration_all"): Query(
            scope, spec,
            default_fields_of_interest,
            (),
            default_sort,
        ),
        n_("02_query_event_registration_orgas"): Query(
            scope, spec,
            default_fields_of_interest,
            (
                ("reg.is_orga", QueryOperators.equal, True),
            ),
            default_sort,
        ),
        n_("10_query_event_registration_not_paid"): Query(
            scope, spec,
            default_fields_of_interest + payment_fields_of_interest,
            (
                ("reg.remaining_owed", QueryOperators.greater, 0),
            ),
            payment_sort + default_sort,
        ),
        n_("12_query_event_registration_paid"): Query(
            scope, spec,
            default_fields_of_interest + payment_fields_of_interest,
            (
                ("reg.remaining_owed", QueryOperators.lessequal, 0),
            ),
            payment_sort + default_sort,
        ),
        n_("14_query_event_registration_participants"): Query(
            scope, spec,
            tuple(all_part_stati_column.split(",")) + default_fields_of_interest,
            (
                any_part_participant_constraint,
            ),
            default_sort,
        ),
        n_("20_query_event_registration_non_members"): Query(
            scope, spec,
            default_fields_of_interest + ("reg.is_member",),
            (
                ("reg.is_member", QueryOperators.equal, False),
            ),
            default_sort,
        ),
        n_("30_query_event_registration_orga_notes"): Query(
            scope, spec,
            default_fields_of_interest + ("reg.orga_notes",),
            (
                ("reg.orga_notes", QueryOperators.nonempty, None),
            ),
            default_sort,
        ),
        n_("32_query_event_registration_notes"): Query(
            scope, spec,
            default_fields_of_interest + ("reg.notes",),
            (
                ("reg.notes", QueryOperators.nonempty, None),
            ),
            default_sort,
        ),
        n_("60_query_dokuteam_course_picture"): Query(
            scope, spec,
            dokuteam_course_picture_fields_of_interest,
            (
                any_part_participant_constraint,
            ),
            default_sort,
        ),
        n_("61_query_dokuteam_dokuforge"): Query(
            scope, spec,
            dokuteam_dokuforge_fields_of_interest,
            (
                any_part_participant_constraint,
                ("reg.list_consent", QueryOperators.equal, True),  # TODO: why?
            ),
            default_sort,
        ),
        n_("62_query_dokuteam_address_export"): Query(
            scope, spec,
            dokuteam_address_fields_of_interest,
            (
                any_part_participant_constraint,
            ),
            default_sort,
        ),
    }

    return queries


def generate_event_course_default_queries(
        event: models_event.Event, spec: QuerySpec) -> dict[str, Query]:
    """
    Generate default queries for course_queries.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The event for which to generate the queries
    :param spec: The Query Spec, dynamically generated for the event
    :return: Dict of default queries
    """

    takes_place = ",".join(f"track{anid}.takes_place" for anid in event.tracks)

    queries = {
        n_("50_query_dokuteam_courselist"): Query(
            QueryScope.event_course, spec,
            ("course.nr", "course.shortname", "course.title"),
            (
                (takes_place, QueryOperators.equal, True),
            ),
            (
                ("course.nr", True),
            ),
        ),
    }

    return queries


_default_fields_of_interest = (
    "personas.id", "given_names", "family_name",
)

_default_sort = (
    ("family_name", True),
    ("given_names", True),
    ("personas.id", True),
)

_not_archived_constraint = ("is_archived", QueryOperators.equal, False)

DEFAULT_QUERIES = {
    QueryScope.all_cde_users: {
        n_("00_query_cde_user_all"): Query(
            QueryScope.cde_user, QueryScope.cde_user.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
            ),
            _default_sort,
        ),
        n_("02_query_cde_members"): Query(
            QueryScope.cde_user, QueryScope.cde_user.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
                ("is_member", QueryOperators.equal, True),
            ),
            _default_sort,
        ),
        n_("10_query_cde_user_trial_members"): Query(
            QueryScope.cde_user, QueryScope.cde_user.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
                ("trial_member", QueryOperators.equal, True),
            ),
            _default_sort,
        ),
        n_("20_query_cde_user_expuls"): Query(
            QueryScope.cde_user, QueryScope.cde_user.get_spec(),
            (
                "personas.id", "given_names", "family_name", "address",
                "address_supplement", "postal_code", "location", "country",
            ),
            (
                _not_archived_constraint,
                ("is_member", QueryOperators.equal, True),
                ("paper_expuls", QueryOperators.equal, True),
                ("address", QueryOperators.nonempty, None),
            ),
            _default_sort,
        ),
    },
    QueryScope.all_event_users: {
        n_("00_query_event_user_all"): Query(
            QueryScope.event_user, QueryScope.event_user.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
            ),
            _default_sort,
        ),
    },
    QueryScope.all_core_users: {
        n_("00_query_core_user_all"): Query(
            QueryScope.core_user, QueryScope.core_user.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
            ),
            _default_sort,
        ),
        n_("10_query_core_any_admin"): Query(
            QueryScope.core_user, QueryScope.core_user.get_spec(),
            _default_fields_of_interest + tuple(ADMIN_KEYS),
            (
                _not_archived_constraint,
                (",".join(ADMIN_KEYS), QueryOperators.equal, True),
            ),
            _default_sort,
        ),
    },
    QueryScope.all_assembly_users: {
        n_("00_query_assembly_user_all"): Query(
            QueryScope.persona, QueryScope.persona.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
            ),
            _default_sort,
        ),
    },
    QueryScope.all_ml_users: {
        n_("00_query_ml_user_all"): Query(
            QueryScope.persona, QueryScope.persona.get_spec(),
            _default_fields_of_interest,
            (
                _not_archived_constraint,
            ),
            _default_sort,
        ),
    },
}
