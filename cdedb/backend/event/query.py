#!/usr/bin/env python3

"""
The `EventQueryBackend` subclasses the `EventBaseBackend` and provides functionality
for querying information about an event aswell as storing and retrieving such queries.
"""
from typing import Collection, Dict, List, Optional, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    PYTHON_TO_SQL_MAP, DatabaseValue_s, access, affirm_set_validation as affirm_set,
    affirm_validation as affirm,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    COURSE_FIELDS, LODGEMENT_FIELDS, LODGEMENT_GROUP_FIELDS, REGISTRATION_FIELDS,
    REGISTRATION_PART_FIELDS, STORED_EVENT_QUERY_FIELDS, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, PrivilegeError, RequestState, implying_realms, json_serialize,
    n_,
)
from cdedb.database.connection import Atomizer
from cdedb.query import Query, QueryOperators, QueryScope


def _get_field_select_columns(fields: CdEDBObjectMap,
                              association: const.FieldAssociations) -> Tuple[str, ...]:
    """Construct SELECT column entries for the given fields of the given association."""
    colum_template = '''(fields->>'{name}')::{kind} AS "xfield_{name}"'''
    return tuple(
        colum_template.format(name=e['field_name'], kind=PYTHON_TO_SQL_MAP[e['kind']])
        for e in fields.values() if e['association'] == association
    )


class EventQueryBackend(EventBaseBackend):
    @access("event", "core_admin", "ml_admin")
    def submit_general_query(self, rs: RequestState, query: Query,
                             event_id: int = None) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :param event_id: For registration queries, specify the event.
        """
        query = affirm(Query, query)
        view = None
        if query.scope == QueryScope.registration:
            event_id = affirm(vtypes.ID, event_id)
            assert event_id is not None
            # ml_admins are allowed to do this to be able to manage
            # subscribers of event mailinglists.
            if not (self.is_orga(rs, event_id=event_id)
                    or self.is_admin(rs)
                    or "ml_admin" in rs.user.roles):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)

            # Step 1: Prepare view template.
            # For more details about this see `doc/Registration_Query`.
            def registration_view_template() -> str:
                reg_part_tables = {
                    part['id']: registration_part_table(part['id'])
                    for part in event['parts'].values()
                }
                lodgement_view = registration_lodgement_view()
                lodgement_groups_view = registration_lodgement_group_view()
                full_part_tables = "\n".join(f"""
                    LEFT OUTER JOIN ({reg_part_table}) AS part{part_id}
                        ON reg.id = part{part_id}.registration_id
                    LEFT OUTER JOIN ({lodgement_view}) AS lodgement{part_id}
                        ON part{part_id}.lodgement_id = lodgement{part_id}.id
                    LEFT OUTER JOIN ({lodgement_groups_view})
                        AS lodgement_group{part_id}
                        ON lodgement{part_id}.group_id = lodgement_group{part_id}.id
                    """ for part_id, reg_part_table in reg_part_tables.items())
                reg_track_tables = {
                    track['id']: registration_track_table(track['id'])
                    for track in event['tracks'].values()
                }
                course_view = registration_course_view()
                full_track_tables = "\n".join(f"""
                    LEFT OUTER JOIN ({reg_track_table}) AS track{t_id}
                        ON reg.id = track{t_id}.registration_id
                    LEFT OUTER JOIN ({course_view}) AS course{t_id}
                        ON track{t_id}.course_id = course{t_id}.id
                    LEFT OUTER JOIN ({course_view}) AS course_instructor{t_id}
                        ON track{t_id}.course_instructor = course_instructor{t_id}.id
                    """ for t_id, reg_track_table in reg_track_tables.items())
                course_choices_track_tables = {
                    track['id']: course_choices_track_table(track)
                    for track in event['tracks'].values()
                }
                course_choices_tables = "\n".join(
                    f"LEFT OUTER JOIN ({choices_table}) AS course_choices{t_id}"
                    f" ON reg.id = course_choices{t_id}.base_id"
                    for t_id, choices_table in course_choices_track_tables.items()
                    if choices_table is not None
                )
                return f"""
                    (
                        SELECT {', '.join(REGISTRATION_FIELDS)}
                        FROM event.registrations
                        WHERE event_id = {event_id}
                    ) AS reg
                    LEFT OUTER JOIN
                        core.personas AS persona ON reg.persona_id = persona.id
                    LEFT OUTER JOIN (
                        {registration_fields_table()}
                    ) AS reg_fields on reg.id = reg_fields.id
                    LEFT OUTER JOIN (
                        {timestamp_table(creation=True)}
                    ) AS ctime ON reg.persona_id = ctime.persona_id
                    LEFT OUTER JOIN (
                        {timestamp_table(creation=False)}
                    ) AS mtime ON reg.persona_id = mtime.persona_id
                    {full_part_tables}
                    {full_track_tables}
                    {course_choices_tables}
                """

            # Step 2: Dynamically construct custom datafield table.
            def registration_fields_table() -> str:
                reg_field_columns = _get_field_select_columns(
                    event['fields'], const.FieldAssociations.registration)
                return f"""
                    SELECT {', '.join(reg_field_columns + ('id',))}
                    FROM event.registrations
                    WHERE event_id = {event_id}
                """

            # Step 3: Prepare templates for registration parts.

            # Since every registration part can have a lodgement, the lodgement views
            # (3.2 and 3.3) are independent of the part and appear once for every part.

            # Step 3.1: Prepare template for registration part information.
            def registration_part_table(part_id: int) -> str:
                return f"""
                    SELECT {', '. join(REGISTRATION_PART_FIELDS)}
                    FROM event.registration_parts
                    WHERE part_id = {part_id}
                """

            # Step 3.2: Prepare view for lodgement information.
            def registration_lodgement_view() -> str:
                lodge_field_columns = _get_field_select_columns(
                    event['fields'], const.FieldAssociations.lodgement)
                columns = LODGEMENT_FIELDS + lodge_field_columns
                return f"""
                    SELECT {', '.join(columns)}
                    FROM event.lodgements
                    WHERE event_id = {event_id}
                """

            # Step 3.3: Prepare view for lodgement group information.
            def registration_lodgement_group_view() -> str:
                return f"""
                    SELECT {', '.join(LODGEMENT_GROUP_FIELDS)}
                    FROM event.lodgement_groups
                    WHERE event_id = {event_id}
                """

            # Step 4: Prepare template for the course choices table per track.

            # Since every track can have any number of possible course choices,
            # including zero, this template will need to be filled for every track and
            # the result might vary for each track.

            # Step 4.1: Template for selecting a single course choice of a given rank
            # for a given track.
            def single_choice_table(track: CdEDBObject, rank: int) -> str:
                return f"""
                    SELECT registration_id, track_id, course_id as rank{rank}
                    FROM event.course_choices
                    WHERE track_id = {track['id']} AND rank = {rank}
                """

            # Step 4.2: Template for the final course choices table for a track.
            def course_choices_track_table(track: CdEDBObject) -> Optional[str]:
                if track['num_choices'] <= 0:
                    return None
                # noinspection PyUnboundLocalVariable
                single_choice_tables = {
                    rank: single_choice_table(track, rank)
                    for rank in range(track['num_choices'])
                }
                course_choices_tables = "\n".join(
                    f"LEFT OUTER JOIN ({single_choice_table}) AS cc{rank}"
                    f" ON base.base_id = cc{rank}.registration_id"
                    for rank, single_choice_table in single_choice_tables.items()
                )
                return f"""
                    (
                        SELECT id as base_id
                        FROM event.registrations
                        WHERE event_id = {event_id}
                    ) AS base
                    {course_choices_tables}
                """

            # Step 5: Prepare template for registration track information.

            # Since every registration track can have two courses, the course view (5.2)
            # is independent of the track and appears twice for every track.

            # Step 5.1 Prepare template for registration track information.
            def registration_track_table(track_id: int) -> str:
                return f"""
                    SELECT
                        registration_id, course_id, course_instructor,
                        (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
                         AND course_id = course_instructor) AS is_course_instructor
                    FROM event.registration_tracks
                    WHERE track_id = {track_id}
                """

            # Step 5.2: Prepare view for course information.
            def registration_course_view() -> str:
                course_field_columns = _get_field_select_columns(
                    event['fields'], const.FieldAssociations.course)
                columns = COURSE_FIELDS + course_field_columns
                return f"""
                    SELECT {', '.join(columns)}
                    FROM event.courses
                    WHERE event_id = {event_id}
                """

            # Step 6: Prepare template for timestamp information.
            def timestamp_table(creation: bool) -> str:
                if creation:
                    param_name = 'creation_time'
                    log_code = const.EventLogCodes.registration_created
                else:
                    param_name = 'modification_time'
                    log_code = const.EventLogCodes.registration_changed
                return f"""
                    SELECT persona_id, MAX(ctime) AS {param_name}
                    FROM event.log
                    WHERE event_id = {event_id} AND code = {log_code}
                    GROUP BY persona_id
                """

            # Step 7: Construct the final view.
            view = registration_view_template()
        elif query.scope == QueryScope.quick_registration:
            event_id = affirm(vtypes.ID, event_id)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            query.constraints.append(("event_id", QueryOperators.equal, event_id))
            query.spec['event_id'] = "id"
        elif query.scope in {QueryScope.event_user,
                             QueryScope.archived_past_event_user}:
            if not self.is_admin(rs) and "core_admin" not in rs.user.roles:
                raise PrivilegeError(n_("Admin only."))

            # Include only event-users
            query.constraints.append(("is_event_realm", QueryOperators.equal, True))
            query.spec["is_event_realm"] = "bool"

            # Include only (un)archived users, depending on query scope.
            is_archived = query.scope == QueryScope.archived_past_event_user
            query.constraints.append(("is_archived", QueryOperators.equal, is_archived))
            query.spec["is_archived"] = "bool"

            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('event'):
                query.constraints.append(
                    (f"is_{realm}_realm", QueryOperators.equal, False))
                query.spec[f"is_{realm}_realm"] = "bool"
        elif query.scope == QueryScope.event_course:
            event_id = affirm(vtypes.ID, event_id)
            assert event_id is not None
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)

            # Step 1: Prepare template for the final view.
            # For more in depth information see `doc/Course_Query`.
            def course_view() -> str:
                course_track_tables = {
                    track['id']: course_track_table(track)
                    for track in event['tracks'].values()
                }
                track_tables = "\n".join(
                    f"LEFT OUTER JOIN ({ctt}) AS track{t} ON course.id = track{t}.id"
                    for t, ctt in course_track_tables.items()
                )
                return f"""
                    (
                        SELECT {', '.join(COURSE_FIELDS)}
                        FROM event.courses
                        WHERE event_id = {event_id}
                    ) AS course
                    LEFT OUTER JOIN (
                        {course_fields_table}
                    ) AS course_fields ON course.id = course_fields.id
                    {track_tables}
                """

            # Step 2: Dynamically construct custom datafield table.
            course_field_columns = _get_field_select_columns(
                event['fields'], const.FieldAssociations.course)
            course_fields_table = f"""
                SELECT {', '.join(course_field_columns + ('id',))}
                FROM event.courses
                WHERE event_id = {event_id}
            """

            # Step 3: Prepare a dynamic template for course track information.
            # This will include attendee and instructor counts, course choice counts by
            # rank and information on whether the course is offered and taking place.

            # A base table with all course ids we need in the following tables.
            base = f"(SELECT id FROM event.courses WHERE event_id = {event_id}) AS c"

            # Step 3.1: Template for combining all course track information.
            def course_track_table(track: CdEDBObject) -> str:
                track_id = track['id']
                single_choice_tables = {
                    rank: single_choice_table(track, rank)
                    for rank in range(track['num_choices'])
                }
                course_choices_tables = "\n".join(
                    f"LEFT OUTER JOIN ({sct}) AS cc{r} ON c.id = cc{r}.base_id"
                    for r, sct in single_choice_tables.items()
                )
                return f"""
                    {base}
                    LEFT OUTER JOIN (
                        SELECT
                            c.id AS base_id, is_active IS NOT NULL AS is_offered,
                            COALESCE(is_active, False) AS takes_place
                        FROM (
                            {base}
                            LEFT OUTER JOIN (
                                SELECT *
                                FROM event.course_segments
                                WHERE track_id = {track_id}
                            ) AS segment ON c.id = segment.course_id
                        )
                    ) AS segment ON c.id = segment.base_id
                    LEFT OUTER JOIN (
                        {registration_track_count_table(
                            track_id, instructor=False, strict=False)}
                    ) AS attendees ON c.id = attendees.base_id
                    LEFT OUTER JOIN (
                        {registration_track_count_table(
                            track_id, instructor=True, strict=False)}
                    ) AS instructors ON c.id = instructors.base_id
                    LEFT OUTER JOIN (
                        {registration_track_count_table(
                            track_id, instructor=True, strict=True)}
                    ) AS assigned_instructors
                        ON c.id = assigned_instructors.base_id
                    {course_choices_tables}
                """

            # Step 3.2: Template for counting instructors and attendees.
            def registration_track_count_table(t_id: int, instructor: bool,
                                               strict: bool) -> str:
                """
                Construct a table to gather registration track information.

                :param instructor: If True, count instrcutors, otherwise attendees.
                :param strict: If True, only count instructors that are assigned to
                    their course.
                """
                col = 'course_instructor' if instructor else 'course_id'
                param_name = 'assigned_instructors' if strict else (
                    'instructors' if instructor else 'attendees')
                constraint = 'AND course_id = course_instructor' if strict else ''
                return f"""
                    SELECT id AS base_id, COUNT(registration_id) AS {param_name}
                    FROM (
                        {base}
                        LEFT OUTER JOIN (
                            SELECT registration_id, {col}
                            FROM event.registration_tracks
                            WHERE track_id = {t_id} {constraint}
                        ) AS reg_track ON c.id = reg_track.{col}
                    )
                    GROUP BY id
                """

            # Step 3.3: Prepare template for constructing table with course choices.

            # Limit to registrations with these stati.
            stati = {
                const.RegistrationPartStati.participant,
                const.RegistrationPartStati.guest,
                const.RegistrationPartStati.waitlist,
                const.RegistrationPartStati.applied,
            }
            stati_array = ', '.join(str(x.value) for x in stati)

            # Template for a specific course choice in a specific track.
            def single_choice_table(track: CdEDBObject, rank: int) -> str:
                return f"""
                    SELECT id AS base_id, COUNT(registration_id) AS num_choices{rank}
                    FROM (
                        (SELECT id FROM event.courses WHERE event_id = {event_id}) AS c
                        LEFT OUTER JOIN (
                            SELECT cc.registration_id, course_id
                            FROM event.course_choices AS cc
                            LEFT OUTER JOIN event.registration_parts AS rp
                                ON cc.registration_id = rp.registration_id
                            WHERE cc.rank = {rank} AND cc.track_id = {track['id']}
                                AND rp.part_id = {track['part_id']}
                                AND rp.status = ANY(ARRAY[{stati_array}])
                        ) AS choices ON c.id = choices.course_id
                    )
                    GROUP BY base_id
                """

            view = course_view()
        elif query.scope == QueryScope.lodgement:
            event_id = affirm(vtypes.ID, event_id)
            assert event_id is not None
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)

            # Step 1: Prepare template for the final view.
            # For more detailed information see `doc/Lodgement_Query`.
            def lodgement_view() -> str:
                tmp_group_id = 'COALESCE(group_id, -1) AS tmp_group_id'
                event_part_tables = {
                    part['id']: event_part_table(part)
                    for part in event['parts'].values()
                }
                part_tables = "\n".join(
                    f"LEFT OUTER JOIN ({ept}) AS part{p} ON lodgement.id = part{p}.id"
                    for p, ept in event_part_tables.items()
                )
                return f"""
                    (
                        SELECT {', '.join(LODGEMENT_FIELDS + (tmp_group_id,))}
                        FROM event.lodgements
                        WHERE event_id = {event_id}
                    ) AS lodgement
                    LEFT OUTER JOIN (
                        {lodgement_fields_table}
                    ) AS lodgement_fields ON lodgement.id = lodgement_fields.id
                    LEFT OUTER JOIN (
                        {lodgement_group_view()}
                    ) AS lodgement_group
                        ON lodgement.tmp_group_id = lodgement_group.tmp_id
                    {part_tables}
                """

            # Step 2: Dynamically construct custom datafield table.
            lodgement_field_columns = _get_field_select_columns(
                event['fields'], const.FieldAssociations.lodgement)
            lodgement_fields_table = f"""
                SELECT {', '.join(lodgement_field_columns + ('id',))}
                FROM event.lodgements
                WHERE event_id = {event_id}
            """

            # Step 3: Create table containing general lodgement group information.
            def lodgement_group_view() -> str:
                # Group lodgements without a lodgement group using -1 instead of NULL,
                # so we can join via the temporary group id.
                return f"""
                    SELECT
                        id, tmp_id, title, regular_capacity, camping_mat_capacity
                    FROM (
                        (
                            (
                                SELECT id, id AS tmp_id, title
                                FROM event.lodgement_groups
                                WHERE event_id = {event_id}
                            )
                            UNION (SELECT NULL, -1, '')
                        ) AS group_base
                        LEFT OUTER JOIN (
                            SELECT
                                COALESCE(group_id, -1) as tmp_group_id,
                                SUM(regular_capacity) as regular_capacity,
                                SUM(camping_mat_capacity) as camping_mat_capacity
                            FROM event.lodgements
                            WHERE event_id = {event_id}
                            GROUP BY tmp_group_id
                        ) AS group_totals
                            ON group_base.tmp_id = group_totals.tmp_group_id
                    )
                """

            # Step 4: Prepare a dynamic template for event part information.
            # This will include inhabitant and group inhabitant counts.

            # A base table with all lodgement ids and temporary group ids we need in
            # the following tables.
            base = (f"(SELECT id, COALESCE(group_id, -1) AS tmp_group_id"
                    f" FROM event.lodgements WHERE event_id = {event_id}) AS base")

            # Step 4.1: Template for combining all event part information.
            def event_part_table(part: CdEDBObject) -> str:
                return f"""
                    {base}
                    LEFT OUTER JOIN (
                        {lodgement_inhabitants_view(part['id'])}
                    ) AS inhabitants ON base.id = inhabitants.base_id
                    LEFT OUTER JOIN (
                        {group_inhabitants_view(part['id'])}
                    ) AS group_inhabitants
                        ON base.tmp_group_id = group_inhabitants.tmp_group_id
                """

            # Step 4.2: Template for counting inhabitants.
            def registration_part_count_table(p_id: int, is_camping_mat: Optional[bool]
                                              ) -> str:
                if is_camping_mat is None:
                    param_name = 'total_inhabitants'
                    constraint = ''
                elif is_camping_mat:
                    param_name = 'camping_mat_inhabitants'
                    constraint = 'AND is_camping_mat = True'
                else:
                    param_name = 'regular_inhabitants'
                    constraint = 'AND is_camping_mat = False'
                return f"""
                    SELECT id as base_id, COUNT(registration_id) AS {param_name}
                    FROM (
                        {base}
                        LEFT OUTER JOIN (
                            SELECT registration_id, lodgement_id
                            FROM event.registration_parts
                            WHERE part_id = {p_id} {constraint}
                        ) AS reg_part ON base.id = reg_part.lodgement_id
                    )
                    GROUP BY id
                """

            # Step 4.3: Template for lodgement inhabitant counts.
            lodgement_inhabitants_view = lambda part_id: f"""
                SELECT
                    base.id AS base_id, tmp_group_id,
                    regular_inhabitants, camping_mat_inhabitants, total_inhabitants
                FROM (
                    {base}
                    LEFT OUTER JOiN (
                        {registration_part_count_table(part_id, is_camping_mat=False)}
                    ) AS regular_inhabitants ON base.id = regular_inhabitants.base_id
                    LEFT OUTER JOiN (
                        {registration_part_count_table(part_id, is_camping_mat=True)}
                    ) AS camping_inhabitants ON base.id = camping_inhabitants.base_id
                    LEFT OUTER JOiN (
                        {registration_part_count_table(part_id, is_camping_mat=None)}
                    ) AS total_inhabitants ON base.id = total_inhabitants.base_id
                )
            """

            # Step 4.4: Template for lodgement group inhabitant counts.
            group_inhabitants_view = lambda part_id: f"""
                SELECT
                    tmp_group_id,
                    COALESCE(SUM(regular_inhabitants)::bigint, 0)
                        AS group_regular_inhabitants,
                    COALESCE(SUM(camping_mat_inhabitants)::bigint, 0)
                        AS group_camping_mat_inhabitants,
                    COALESCE(SUM(total_inhabitants)::bigint, 0)
                        AS group_total_inhabitants
                FROM (
                    {lodgement_inhabitants_view(part_id)}
                ) AS inhabitants
                GROUP BY tmp_group_id
            """

            view = lodgement_view()
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query, view=view)

    @access("event")
    def get_event_queries(self, rs: RequestState, event_id: int,
                          scopes: Collection[QueryScope] = None,
                          query_ids: Collection[int] = None,
                          ) -> Dict[str, Query]:
        """Retrieve all stored queries for the given event and scope.

        If no scopes are given, all queries are returned instead.

        If a stored query references a custom datafield, that has been deleted, it can
        still be retrieved, and the reference to the field remains, it will just be
        omitted, so if the field is added again, it will appear in the query again.
        """
        event_id = affirm(vtypes.ID, event_id)
        scopes = affirm_set(QueryScope, scopes or set())
        query_ids = affirm_set(vtypes.ID, query_ids or set())
        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Must be orga to retrieve stored queries."))
        try:
            with Atomizer(rs):
                event = self.get_event(rs, event_id)
                select = (f"SELECT {', '.join(STORED_EVENT_QUERY_FIELDS)}"
                          f" FROM event.stored_queries"
                          f" WHERE event_id = %s")
                params: List[DatabaseValue_s] = [event_id]
                if scopes:
                    select += " AND scope = ANY(%s)"
                    params.append(scopes)
                if query_ids:
                    select += " AND id = ANY(%s)"
                    params.append(query_ids)
                query_data = self.query_all(rs, select, params)
                ret = {}
                count = fail_count = 0
                for qd in query_data:
                    qd["serialized_query"]["query_id"] = qd["id"]
                    scope = affirm(QueryScope, qd["scope"])
                    spec = scope.get_spec(event=event)
                    try:
                        # The QueryInput takes care of deserialization.
                        q: Query = affirm(vtypes.QueryInput, qd["serialized_query"],
                                          spec=spec, allow_empty=False)
                        assert q.name is not None and q.query_id is not None
                    except (ValueError, TypeError):
                        fail_count += 1
                        continue
                    ret[q.name] = q
                    count += 1
        except PrivilegeError:
            raise
        # Failsafe in case something very unexpected goes wrong, so we don't break
        # the query pages.
        except Exception:
            self.logger.exception(
                f"Fatal error during retrieval of stored event queries for"
                f" event_id={event_id} and scopes={scopes}.")
            return {}
        if fail_count:
            rs.notify(
                "info", n_("%(count)s stored queries could not be retrieved."),
                {'count': fail_count})
        return ret

    @access("event")
    def delete_event_query(self, rs: RequestState, query_id: int) -> DefaultReturnCode:
        """Delete the stored query with the given query id."""
        query_id = affirm(vtypes.ID, query_id)
        with Atomizer(rs):
            q = self.sql_select_one(
                rs, "event.stored_queries", ("event_id", "query_name"), query_id)
            if q is None:
                return 0
            if not (self.is_admin(rs) or self.is_orga(rs, event_id=q['event_id'])):
                raise PrivilegeError(n_(
                    "Must be orga to delete queries for an event."))

            ret = self.sql_delete_one(rs, "event.stored_queries", query_id)
            if ret:
                self.event_log(rs, const.EventLogCodes.query_deleted,
                               event_id=q['event_id'], change_note=q['query_name'])
            return ret

    @access("event")
    def store_event_query(self, rs: RequestState, event_id: int,
                          query: Query) -> DefaultReturnCode:
        """Store a single event query in the database."""
        event_id = affirm(vtypes.ID, event_id)
        query = affirm(Query, query)

        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_(
                "Must be orga to store queries for an event."))
        if not query.scope.supports_storing():
            raise ValueError(n_("Cannot store this kind of query."))
        if not query.name:
            rs.notify("error", n_("Query must have a name"))
            return 0
        data = {
            'event_id': event_id,
            'query_name': query.name,
            'scope': query.scope,
            'serialized_query': json_serialize(query.serialize()),
        }
        with Atomizer(rs):
            new_id = self.sql_insert(
                rs, "event.stored_queries", data, drop_on_conflict=True)
            if not new_id:
                rs.notify("error", n_("Query with name '%(query)s' already exists"
                                      " for this event."), {"query": query.name})
                return 0
            self.event_log(rs, const.EventLogCodes.query_stored,
                           event_id=event_id, change_note=query.name)
        return new_id

    @access("event_admin")
    def get_invalid_stored_event_queries(self, rs: RequestState, event_id: int
                                         ) -> CdEDBObjectMap:
        """Retrieve raw data for stored event queries that cannot be deserialized."""
        q = (f"SELECT {', '.join(STORED_EVENT_QUERY_FIELDS)}"
             f" FROM event.stored_queries WHERE event_id = %s AND NOT(id = ANY(%s))")
        with Atomizer(rs):
            retrievable_queries = self.get_event_queries(rs, event_id)
            params = (event_id, [q.query_id for q in retrievable_queries.values()])
            data = self.query_all(rs, q, params)
            return {e["id"]: e for e in data}
