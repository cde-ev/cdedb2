#!/usr/bin/env python3

"""Provide all default queries used for "speed dialing".

All query-scopes are keys of the DEFAULT_QUERIES dict, mapping to a dict of their
default query names mapping to the query definition.

Only exception are the per-event-queries, since they need some dynamic information
about the event to be created. They can be obtained by calling the respective functions.
"""

from typing import Dict

import cdedb.database.constants as const
from cdedb.common import ADMIN_KEYS, CdEDBObject, deduct_years, n_, now
from cdedb.query import Query, QueryOperators, QueryScope, QuerySpec


def generate_event_registration_default_queries(
        event: CdEDBObject, spec: QuerySpec) -> Dict[str, Query]:
    """
    Generate default queries for registration_query.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The Event for which to generate the queries
    :param spec: The Query Spec, dynamically generated for the event
    :return: Dict of default queries
    """
    default_sort = (("persona.family_name", True),
                    ("persona.given_names", True),
                    ("reg.id", True))

    all_part_stati_column = ",".join(
        f"part{part_id}.status" for part_id in event['parts'])

    dokuteam_course_picture_fields_of_interest = [
        "persona.id", "persona.given_names", "persona.family_name"]
    for track_id in event['tracks']:
        dokuteam_course_picture_fields_of_interest.append(f"course{track_id}.nr")
        dokuteam_course_picture_fields_of_interest.append(
            f"track{track_id}.is_course_instructor")

    dokuteam_dokuforge_fields_of_interest = [
        "persona.id", "persona.given_names", "persona.family_name", "persona.username"]
    for track_id in event['tracks']:
        dokuteam_dokuforge_fields_of_interest.append(f"course{track_id}.nr")
        dokuteam_dokuforge_fields_of_interest.append(
            f"track{track_id}.is_course_instructor")

    dokuteam_address_fields_of_interest = [
        "persona.given_names", "persona.family_name", "persona.address",
        "persona.address_supplement", "persona.postal_code", "persona.location",
        "persona.country"]

    queries = {
        n_("00_query_event_registration_all"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name"),
            tuple(),
            (("reg.id", True),)),
        n_("02_query_event_registration_orgas"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name"),
            (("persona.id", QueryOperators.oneof, event['orgas']),),
            default_sort),
        n_("10_query_event_registration_not_paid"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name"),
            (("reg.payment", QueryOperators.empty, None),),
            default_sort),
        n_("12_query_event_registration_paid"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "reg.payment"),
            (("reg.payment", QueryOperators.nonempty, None),),
            (("reg.payment", False), ("persona.family_name", True),
             ("persona.given_names", True),)),
        n_("14_query_event_registration_participants"): Query(
            QueryScope.registration, spec,
            all_part_stati_column.split(",") +
            ["persona.given_names", "persona.family_name"],
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),),
            default_sort),
        n_("20_query_event_registration_non_members"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name"),
            (("persona.is_member", QueryOperators.equal, False),),
            default_sort),
        n_("30_query_event_registration_orga_notes"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "reg.orga_notes"),
            (("reg.orga_notes", QueryOperators.nonempty, None),),
            default_sort),
        n_("40_query_event_registration_u18"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 18)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True),)),
        n_("42_query_event_registration_u16"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 16)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("44_query_event_registration_u14"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 14)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("50_query_event_registration_minors_no_consent"): Query(
            QueryScope.registration, spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 18)),
             ("reg.parental_agreement", QueryOperators.equal, False)),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("60_query_dokuteam_course_picture"): Query(
            QueryScope.registration, spec, dokuteam_course_picture_fields_of_interest,
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),), default_sort),
        n_("61_query_dokuteam_dokuforge"): Query(
            QueryScope.registration, spec, dokuteam_dokuforge_fields_of_interest,
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),
             ("reg.list_consent", QueryOperators.equal, True),), default_sort),
        n_("62_query_dokuteam_address_export"): Query(
            QueryScope.registration, spec, dokuteam_address_fields_of_interest,
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),), default_sort),
    }

    if len(event['parts']) > 1:
        queries.update({
            n_("16_query_event_registration_waitlist"): Query(
                QueryScope.registration, spec,
                all_part_stati_column.split(",") +
                ["persona.given_names", "persona.family_name",
                 "ctime.creation_time", "reg.payment"],
                ((all_part_stati_column, QueryOperators.equal,
                  const.RegistrationPartStati.waitlist.value),),
                (("ctime.creation_time", True),)),
        })

    return queries


def generate_event_course_default_queries(
        event: CdEDBObject, spec: QuerySpec) -> Dict[str, Query]:
    """
    Generate default queries for course_queries.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The event for which to generate the queries
    :param spec: The Query Spec, dynamically generated for the event
    :return: Dict of default queries
    """

    takes_place = ",".join(f"track{anid}.takes_place" for anid in event["tracks"])

    queries = {
        n_("50_query_dokuteam_courselist"): Query(
            QueryScope.event_course, spec,
            ("course.nr", "course.shortname", "course.title"),
            ((takes_place, QueryOperators.equal, True),),
            (("course.nr", True),)),
    }

    return queries


DEFAULT_QUERIES = {
        QueryScope.cde_user: {
            n_("00_query_cde_user_all"): Query(
                QueryScope.cde_user, QueryScope.cde_user.get_spec(),
                ("personas.id", "given_names", "family_name"),
                (),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("02_query_cde_members"): Query(
                QueryScope.cde_user, QueryScope.cde_user.get_spec(),
                ("personas.id", "given_names", "family_name"),
                (("is_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("10_query_cde_user_trial_members"): Query(
                QueryScope.cde_user, QueryScope.cde_user.get_spec(),
                ("personas.id", "given_names", "family_name"),
                (("trial_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("20_query_cde_user_expuls"): Query(
                QueryScope.cde_user, QueryScope.cde_user.get_spec(),
                ("personas.id", "given_names", "family_name", "address",
                 "address_supplement", "postal_code", "location", "country"),
                (("is_member", QueryOperators.equal, True),
                 ("paper_expuls", QueryOperators.equal, True),
                 ("address", QueryOperators.nonempty, None)),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        QueryScope.archived_persona: {
            n_("00_query_archived_persona_all"): Query(
                QueryScope.archived_persona,
                QueryScope.archived_persona.get_spec(),
                ("personas.id", "given_names", "family_name", "notes"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        QueryScope.event_user: {
            n_("00_query_event_user_all"): Query(
                QueryScope.event_user, QueryScope.event_user.get_spec(),
                ("personas.id", "given_names", "family_name", "birth_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("10_query_event_user_minors"): Query(
                QueryScope.event_user, QueryScope.event_user.get_spec(),
                ("personas.id", "given_names", "family_name",
                 "birthday"),
                (("birthday", QueryOperators.greater,
                  deduct_years(now().date(), 18)),),
                (("birthday", True), ("family_name", True),
                 ("given_names", True))),
        },
        QueryScope.core_user: {
            n_("00_query_core_user_all"): Query(
                QueryScope.core_user, QueryScope.core_user.get_spec(),
                ("personas.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True), ("personas.id", True))),
            n_("10_query_core_any_admin"): Query(
                QueryScope.core_user, QueryScope.core_user.get_spec(),
                ("personas.id", "given_names", "family_name", *ADMIN_KEYS),
                ((",".join(ADMIN_KEYS), QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True), ("personas.id", True))),
        },
        QueryScope.assembly_user: {
            n_("00_query_assembly_user_all"): Query(
                QueryScope.persona, QueryScope.persona.get_spec(),
                ("personas.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        QueryScope.ml_user: {
            n_("00_query_ml_user_all"): Query(
                QueryScope.persona, QueryScope.persona.get_spec(),
                ("personas.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
}
