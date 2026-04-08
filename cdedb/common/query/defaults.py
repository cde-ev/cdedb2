#!/usr/bin/env python3

"""Provide all default queries used for "speed dialing".

All query-scopes are keys of the DEFAULT_QUERIES dict, mapping to a dict of their
default query names mapping to the query definition.

Only exception are the per-event-queries, since they need some dynamic information
about the event to be created. They can be obtained by calling the respective functions.
"""

import functools

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.common as models_common
import cdedb.models.event as models_event
from cdedb.common.n_ import n_
from cdedb.common.query import (
    Query,
    QueryConstraint,
    QueryOperators,
    QueryOrder,
    QueryScope,
)
from cdedb.common.roles import ADMIN_KEYS
from cdedb.common.sorting import xsorted


def _make_stored_query(
    scope: QueryScope,
    name: str,
    *,
    fields_of_interest: list[str],
    constraints: list[QueryConstraint],
    order: list[QueryOrder],
    event: models_event.Event | None = None,
) -> models_common.StoredQuery:

    return models_common.StoredQuery(
        id=vtypes.ID(-1),
        query_name=name,
        scope=scope,
        serialized_query=Query(
            scope=scope,
            spec={},
            fields_of_interest=fields_of_interest,
            constraints=constraints,
            order=order,
        ).serialize(),  # type: ignore[arg-type]
    )


def _make_stored_event_queries(
    queries: list[models_common.StoredQuery], event: models_event.Event
) -> list[models_event.StoredEventQuery]:
    return [
        models_event.StoredEventQuery(**vars(query), event_id=event.id, event=event)
        for query in queries
    ]


def generate_event_registration_default_queries(
    event: models_event.Event,
) -> list[models_event.StoredEventQuery]:
    """
    Generate default queries for registration_query.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The Event for which to generate the queries
    """
    scope = QueryScope.registration
    make_stored_query = functools.partial(_make_stored_query, scope)

    default_fields_of_interest = [
        "persona.family_name",
        "persona.given_names",
        "persona.username",
    ]

    default_sort = [
        ("persona.family_name", True),
        ("persona.given_names", True),
        ("reg.id", True),
    ]

    all_part_stati_column = ",".join(
        f"part{part_id}.status" for part_id in xsorted(event.parts)
    )
    any_part_participant_constraint = (
        all_part_stati_column,
        QueryOperators.equal,
        const.RegistrationPartStati.participant.value,
    )

    dokuteam_course_picture_fields_of_interest = [
        "persona.id",
        "persona.given_names",
        "persona.family_name",
    ]
    for track_id in event.tracks:
        dokuteam_course_picture_fields_of_interest.extend([
            f"course{track_id}.nr",
            f"track{track_id}.is_course_instructor",
        ])

    dokuteam_dokuforge_fields_of_interest = [
        "persona.id",
        "persona.given_names",
        "persona.family_name",
        "persona.username",
    ]
    for track_id in event.tracks:
        dokuteam_dokuforge_fields_of_interest.extend([
            f"course{track_id}.nr",
            f"track{track_id}.is_course_instructor",
        ])

    dokuteam_address_fields_of_interest = [
        "persona.given_names",
        "persona.family_name",
        "persona.address",
        "persona.address_supplement",
        "persona.postal_code",
        "persona.location",
        "persona.country",
    ]

    queries = [
        make_stored_query(
            n_("00_query_event_registration_all"),
            fields_of_interest=default_fields_of_interest,
            constraints=[],
            order=default_sort,
        ),
        make_stored_query(
            n_("02_query_event_registration_orgas"),
            fields_of_interest=default_fields_of_interest,
            constraints=[
                ("reg.is_orga", QueryOperators.equal, True),
            ],
            order=default_sort,
        ),
        make_stored_query(
            n_("30_query_event_registration_orga_notes"),
            fields_of_interest=default_fields_of_interest + ["reg.orga_notes"],
            constraints=[
                ("reg.orga_notes", QueryOperators.nonempty, None),
            ],
            order=default_sort,
        ),
        make_stored_query(
            n_("32_query_event_registration_notes"),
            fields_of_interest=default_fields_of_interest + ["reg.notes"],
            constraints=[
                ("reg.notes", QueryOperators.nonempty, None),
            ],
            order=default_sort,
        ),
        make_stored_query(
            n_("60_query_dokuteam_course_picture"),
            fields_of_interest=dokuteam_course_picture_fields_of_interest,
            constraints=[any_part_participant_constraint],
            order=default_sort,
        ),
        make_stored_query(
            n_("61_query_dokuteam_dokuforge"),
            fields_of_interest=dokuteam_dokuforge_fields_of_interest,
            constraints=[
                any_part_participant_constraint,
                ("reg.list_consent", QueryOperators.equal, True),  # TODO: why?
            ],
            order=default_sort,
        ),
        make_stored_query(
            n_("62_query_dokuteam_address_export"),
            fields_of_interest=dokuteam_address_fields_of_interest,
            constraints=[any_part_participant_constraint],
            order=default_sort,
        ),
    ]

    return _make_stored_event_queries(queries, event)


def generate_event_course_default_queries(
    event: models_event.Event,
) -> list[models_event.StoredEventQuery]:
    """
    Generate default queries for course_queries.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The event for which to generate the queries.
    """
    scope = QueryScope.event_course
    make_stored_query = functools.partial(_make_stored_query, scope)

    takes_place = ",".join(f"track{anid}.takes_place" for anid in event.tracks)

    queries = [
        make_stored_query(
            n_("50_query_dokuteam_courselist"),
            fields_of_interest=["course.nr", "course.shortname", "course.title"],
            constraints=[
                (takes_place, QueryOperators.equal, True),
            ],
            order=[
                ("course.nr", True),
            ],
        )
    ]

    return _make_stored_event_queries(queries, event)


_default_fields_of_interest = [
    "personas.id",
    "given_names",
    "family_name",
]

_default_sort = [
    ("family_name", True),
    ("given_names", True),
    ("personas.id", True),
]

_not_archived_constraint = ("is_archived", QueryOperators.equal, False)

DEFAULT_QUERIES = {
    QueryScope.all_cde_users: [
        _make_stored_query(
            QueryScope.all_cde_users,
            n_("00_query_cde_user_all"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[_not_archived_constraint],
            order=_default_sort,
        ),
        _make_stored_query(
            QueryScope.all_cde_users,
            n_("02_query_cde_members"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[
                _not_archived_constraint,
                ("is_member", QueryOperators.equal, True),
            ],
            order=_default_sort,
        ),
        _make_stored_query(
            QueryScope.all_cde_users,
            n_("10_query_cde_user_trial_members"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[
                _not_archived_constraint,
                ("trial_member", QueryOperators.equal, True),
            ],
            order=_default_sort,
        ),
        _make_stored_query(
            QueryScope.all_cde_users,
            n_("20_query_cde_user_expuls"),
            fields_of_interest=[
                "personas.id",
                "given_names",
                "family_name",
                "address",
                "address_supplement",
                "postal_code",
                "location",
                "country",
            ],
            constraints=[
                _not_archived_constraint,
                ("is_member", QueryOperators.equal, True),
                ("paper_expuls", QueryOperators.equal, True),
                ("address", QueryOperators.nonempty, None),
            ],
            order=_default_sort,
        ),
    ],
    QueryScope.all_event_users: [
        _make_stored_query(
            QueryScope.all_event_users,
            n_("00_query_event_user_all"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[_not_archived_constraint],
            order=_default_sort,
        ),
    ],
    QueryScope.all_core_users: [
        _make_stored_query(
            QueryScope.all_core_users,
            n_("00_query_core_user_all"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[_not_archived_constraint],
            order=_default_sort,
        ),
        _make_stored_query(
            QueryScope.all_core_users,
            n_("10_query_core_any_admin"),
            fields_of_interest=_default_fields_of_interest + list(ADMIN_KEYS),
            constraints=[
                _not_archived_constraint,
                (",".join(ADMIN_KEYS), QueryOperators.equal, True),
            ],
            order=_default_sort,
        ),
    ],
    QueryScope.all_assembly_users: [
        _make_stored_query(
            QueryScope.all_assembly_users,
            n_("00_query_assembly_user_all"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[_not_archived_constraint],
            order=_default_sort,
        ),
    ],
    QueryScope.all_ml_users: [
        _make_stored_query(
            QueryScope.all_ml_users,
            n_("00_query_ml_user_all"),
            fields_of_interest=_default_fields_of_interest,
            constraints=[_not_archived_constraint],
            order=_default_sort,
        ),
    ],
}
