#!/usr/bin/env python3

"""
The `EventQueryBackend` subclasses the `EventBaseBackend` and provides functionality
for querying information about an event aswell as storing and retrieving such queries.
"""

from typing import Collection, Dict, List, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    PYTHON_TO_SQL_MAP, DatabaseValue_s, access, affirm_set_validation as affirm_set,
    affirm_validation as affirm,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    STORED_EVENT_QUERY_FIELDS, CdEDBObject, CdEDBObjectMap, DefaultReturnCode,
    PrivilegeError, RequestState, implying_realms, json_serialize, n_,
)
from cdedb.database.connection import Atomizer
from cdedb.query import Query, QueryOperators, QueryScope


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

            # For more details about this see `doc/Registration_Query`.
            # The template for the final view.
            registration_table = \
            """event.registrations AS reg
            LEFT OUTER JOIN
                core.personas AS persona ON reg.persona_id = persona.id
            {registration_fields_table}
            {part_tables}
            {track_tables}
            {creation_date_table}
            {modification_date_table}"""

            # Dynamically construct columns for custom registration datafields.
            # noinspection PyArgumentList
            reg_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.registration
            }
            reg_field_columns = ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                    for name, kind in reg_fields.items()])

            if reg_field_columns:
                reg_field_columns += ", "
            registration_fields_table = \
                """LEFT OUTER JOIN (
                    SELECT
                        {reg_field_columns}
                        id
                    FROM
                        event.registrations
                    WHERE
                        event_id = {event_id}
                ) AS reg_fields ON reg.id = reg_fields.id""".format(
                    event_id=event_id, reg_field_columns=reg_field_columns)

            # Dynamically construct the columns for custom lodgement fields.
            # noinspection PyArgumentList
            lodgement_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.lodgement
            }
            lodge_field_columns = ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in lodgement_fields.items()]
            )
            if lodge_field_columns:
                lodge_field_columns += ", "
            lodgement_view = f"""SELECT
                {lodge_field_columns}
                title, notes, id, group_id
            FROM
                event.lodgements
            WHERE
                event_id = {event_id}"""
            lodgement_group_view = (f"SELECT title, id"
                                    f" FROM event.lodgement_groups"
                                    f" WHERE event_id = {event_id}")
            # The template for registration part and lodgement information.
            part_table = lambda part_id: \
                f"""LEFT OUTER JOIN (
                    SELECT
                        registration_id, status, lodgement_id, is_camping_mat
                    FROM
                        event.registration_parts
                    WHERE
                        part_id = {part_id}
                ) AS part{part_id} ON reg.id = part{part_id}.registration_id
                LEFT OUTER JOIN (
                    {lodgement_view}
                ) AS lodgement{part_id}
                ON part{part_id}.lodgement_id = lodgement{part_id}.id
                LEFT OUTER JOIN (
                    {lodgement_group_view}
                ) AS lodgement_group{part_id}
                ON lodgement{part_id}.group_id = lodgement_group{part_id}.id
                """

            part_tables = " ".join(
                part_table(part['id'])
                for part in event['parts'].values()
            )
            # Dynamically construct columns for custom course fields.
            # noinspection PyArgumentList
            course_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.course
            }
            course_field_columns = ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in course_fields.items()]
            )
            if course_field_columns:
                course_field_columns += ", "
            course_view = \
            """SELECT
                {course_field_columns}
                id, nr, title, shortname, notes, instructors
            FROM
                event.courses
            WHERE
                event_id = {event_id}""".format(
                event_id=event_id, course_field_columns=course_field_columns)

            course_choices_template = """
            LEFT OUTER JOIN (
                SELECT
                    {columns}
                FROM (
                    (
                        SELECT
                            id as base_id
                        FROM
                            event.registrations
                        WHERE
                            event_id = {event_id}
                    ) AS base
                    {rank_tables}
                )
            ) AS course_choices{t_id} ON reg.id = course_choices{t_id}.base_id
            """
            rank_template = \
            """LEFT OUTER JOIN (
                SELECT
                    registration_id, track_id, course_id as rank{rank}
                FROM
                    event.course_choices
                WHERE
                    track_id = {track_id} AND rank = {rank}
            ) AS rank{rank} ON base.base_id = rank{rank}.registration_id"""

            def course_choices_table(t_id: int, ranks: int) -> str:
                # Trying to join these tables fails if there are no choices.
                if ranks < 1:
                    return ""
                rank_tables = "\n".join(
                    rank_template.format(rank=i, track_id=t_id)
                    for i in range(ranks))
                columns = ", ".join(["base_id"] +
                                    [f"rank{i}" for i in range(ranks)])
                return course_choices_template.format(
                    columns=columns, event_id=event_id, rank_tables=rank_tables,
                    t_id=t_id)

            track_table = lambda track: \
                f"""LEFT OUTER JOIN (
                    SELECT
                        registration_id, course_id, course_instructor,
                        (NOT(course_id IS NULL
                             AND course_instructor IS NOT NULL)
                         AND course_id = course_instructor)
                        AS is_course_instructor
                    FROM
                        event.registration_tracks
                    WHERE
                        track_id = {track['id']}
                ) AS track{track['id']}
                    ON reg.id = track{track['id']}.registration_id
                LEFT OUTER JOIN (
                    {course_view}
                ) AS course{track['id']}
                    ON track{track['id']}.course_id = course{track['id']}.id
                LEFT OUTER JOIN (
                    {course_view}
                ) AS course_instructor{track['id']}
                    ON track{track['id']}.course_instructor =
                    course_instructor{track['id']}.id
                {course_choices_table(track['id'], track['num_choices'])}"""

            track_tables = " ".join(
                track_table(track) for track in event['tracks'].values()
            )

            # Retrieve creation and modification timestamps from log.
            creation_date_table = \
            """LEFT OUTER JOIN (
                SELECT
                    persona_id, MAX(ctime) AS creation_time
                FROM
                    event.log
                WHERE
                    event_id = {event_id} AND code = {reg_create_code}
                GROUP BY
                    persona_id
            ) AS ctime ON reg.persona_id = ctime.persona_id""".format(
                event_id=event_id,
                reg_create_code=const.EventLogCodes.registration_created.value)
            modification_date_table = \
            """LEFT OUTER JOIN (
                SELECT
                    persona_id, MAX(ctime) AS modification_time
                FROM
                    event.log
                WHERE
                    event_id = {event_id} AND code = {reg_changed_code}
                GROUP BY
                    persona_id
            ) AS mtime ON reg.persona_id = mtime.persona_id""".format(
                event_id=event_id,
                reg_changed_code=const.EventLogCodes.registration_changed.value)

            view = registration_table.format(
                registration_fields_table=registration_fields_table,
                part_tables=part_tables,
                track_tables=track_tables,
                creation_date_table=creation_date_table,
                modification_date_table=modification_date_table,
            )

            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope == QueryScope.quick_registration:
            event_id = affirm(vtypes.ID, event_id)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope in {QueryScope.event_user,
                             QueryScope.archived_past_event_user}:
            if not self.is_admin(rs) and "core_admin" not in rs.user.roles:
                raise PrivilegeError(n_("Admin only."))
            # Include only un-archived event-users
            query.constraints.append(("is_event_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(
                ("is_archived", QueryOperators.equal,
                 query.scope == QueryScope.archived_past_event_user))
            query.spec["is_event_realm"] = "bool"
            query.spec["is_archived"] = "bool"
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('event'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = "bool"
        elif query.scope == QueryScope.event_course:
            event_id = affirm(vtypes.ID, event_id)
            assert event_id is not None
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)

            # Template for the final view.
            # For more in depth information see `doc/Course_Query`.
            # We retrieve general course, custom field and track specific info.
            template = """
            (
                {course_table}
            ) AS course
            LEFT OUTER JOIN (
                {course_fields_table}
            ) AS course_fields ON course.id = course_fields.id
            {track_tables}
            """

            course_table = """
            SELECT
                id, id AS course_id, event_id,
                nr, title, description, shortname, instructors, min_size,
                max_size, notes
            FROM event.courses"""

            # Dynamically construct the custom field view.
            # noinspection PyArgumentList
            course_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.course
            }
            course_field_columns = ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in course_fields.items()]
            )
            if course_field_columns:
                course_field_columns += ", "
            course_fields_table = \
            """SELECT
                {course_field_columns}
                id
            FROM
                event.courses
            WHERE
                event_id = {event_id}""".format(
                course_field_columns=course_field_columns, event_id=event_id)

            # Template for retrieving course information for one specific track.
            # We don't use the {base} table from below, because we need
            # the id to be distinct.
            def track_table(track: CdEDBObject) -> str:
                track_id = track['id']
                choices = ""
                if track['num_choices'] > 0:
                    choices = f"""
                    LEFT OUTER JOIN (
                        {choices_tables(track)}
                    ) AS choices{track_id} ON base_id = choices{track_id}.id"""
                return f"""LEFT OUTER JOIN (
                    (
                        SELECT
                            id AS base_id
                        FROM
                            event.courses
                        WHERE
                            event_id = {event_id}
                    ) AS base
                    LEFT OUTER JOIN (
                        {segment_table(track_id)}
                    ) AS segment{track_id} ON base_id = segment{track_id}.id
                    LEFT OUTER JOIN (
                        {attendees_table(track_id)}
                    ) AS attendees{track_id} ON base_id = attendees{track_id}.id
                    LEFT OUTER JOIN (
                        {instructors_table(track_id)}
                    ) AS instructors{track_id}
                        ON base_id = instructors{track_id}.id
                    {choices}
                ) AS track{track_id}
                    ON course.id = track{track_id}.base_id"""

            # A base table with all course ids we need in the following tables.
            base = "(SELECT id FROM event.courses WHERE event_id = {}) AS c".\
                format(event_id)

            # General course information specific to a track.
            segment_table = lambda t_id: \
            """SELECT
                id, COALESCE(is_active, False) AS takes_place,
                is_active IS NOT NULL AS is_offered
            FROM (
                {base}
                LEFT OUTER JOIN (
                    SELECT
                        is_active, course_id
                    FROM
                        event.course_segments
                    WHERE track_id = {track_id}
                ) AS segment ON c.id = segment.course_id
            ) AS segment""".format(
                base=base,
                track_id=t_id,
            )

            # Retrieve attendee count.
            attendees_table = lambda t_id: \
                """SELECT
                    id, COUNT(registration_id) AS attendees
                FROM (
                    {base}
                    LEFT OUTER JOIN (
                        SELECT
                            registration_id, course_id
                        FROM
                            event.registration_tracks
                        WHERE track_id = {track_id}
                    ) AS rt ON c.id = rt.course_id
                ) AS attendee_count
                GROUP BY
                    id""".format(
                    base=base,
                    track_id=t_id,
                )

            # Retrieve instructor count.
            instructors_table = lambda t_id: \
                """SELECT
                    id, COUNT(registration_id) as instructors
                FROM (
                    {base}
                    LEFT OUTER JOIN (
                        SELECT
                            registration_id, course_instructor
                        FROM
                            event.registration_tracks
                        WHERE
                            track_id = {track_id}
                        ) as rt on c.id = rt.course_instructor
                ) AS instructor_count
                GROUP BY
                    id""".format(
                    base=base,
                    track_id=t_id,
                )

            # Retrieve course choice count. Limit to regs with relevant stati.
            stati = {
                const.RegistrationPartStati.participant,
                const.RegistrationPartStati.guest,
                const.RegistrationPartStati.waitlist,
                const.RegistrationPartStati.applied,
            }
            # Template for a specific course choice in a specific track.
            choices_table = lambda t_id, p_id, rank: \
                """SELECT
                    id AS course_id, COUNT(registration_id) AS num_choices{rank}
                FROM (
                    {base}
                    LEFT OUTER JOIN (
                        SELECT
                            registration_id, course_id AS c_id
                        FROM (
                            (
                                SELECT registration_id, course_id
                                FROM event.course_choices
                                WHERE rank = {rank} AND track_id = {track_id}
                            ) AS choices
                            LEFT OUTER JOIN (
                                SELECT
                                    registration_id AS reg_id, status
                                FROM
                                    event.registration_parts
                                WHERE
                                    part_id = {part_id}
                            ) AS reg_part
                            ON choices.registration_id = reg_part.reg_id
                        ) AS choices
                        WHERE
                            status = ANY({stati})
                    ) AS status ON c.id = status.c_id
                ) AS choices_count
                GROUP BY
                    course_id""".format(
                    base=base, track_id=t_id, rank=rank, part_id=p_id,
                    stati="ARRAY[{}]".format(
                        ",".join(str(x.value) for x in stati)),
                )
            # Combine all the choices for a specific track.
            choices_tables = lambda track: \
                base + "\n" + " ".join(
                    """LEFT OUTER JOIN (
                        {choices_table}
                    ) AS choices{track_id}_{rank}
                        ON c.id = choices{track_id}_{rank}.course_id""".format(
                        choices_table=choices_table(
                            track['id'], track['part_id'], rank),
                        track_id=track['id'],
                        rank=rank,
                    )
                    for rank in range(track['num_choices'])
                )

            view = template.format(
                course_table=course_table,
                course_fields_table=course_fields_table,
                track_tables=" ".join(
                    track_table(track)
                    for track in event['tracks'].values()),
            )

            query.constraints.append(
                ("event_id", QueryOperators.equal, event_id))
            query.spec['event_id'] = "id"
        elif query.scope == QueryScope.lodgement:
            event_id = affirm(vtypes.ID, event_id)
            assert event_id is not None
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)

            # Template for the final view.
            # For more detailed information see `doc/Lodgement_Query`.
            # We retrieve general lodgement, event-field and part specific info.
            template = """
            (
                {lodgement_table}
            ) AS lodgement
            LEFT OUTER JOIN (
                SELECT
                    -- replace NULL ids with temp value so we can join.
                    id, COALESCE(group_id, -1) AS tmp_group_id
                FROM
                    event.lodgements
                WHERE
                    event_id = {event_id}
            ) AS tmp_group ON lodgement.id = tmp_group.id
            LEFT OUTER JOIN (
                {lodgement_fields_table}
            ) AS lodgement_fields ON lodgement.id = lodgement_fields.id
            LEFT OUTER JOIN (
                {lodgement_group_table}
            ) AS lodgement_group
                ON tmp_group.tmp_group_id = lodgement_group.tmp_id
            {part_tables}
            """

            lodgement_table = """
            SELECT
                id, id as lodgement_id, event_id,
                title, regular_capacity, camping_mat_capacity, notes, group_id
            FROM
                event.lodgements"""

            # Dynamically construct the view for custom event-fields:
            # noinspection PyArgumentList
            lodgement_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.lodgement
            }
            lodgement_fields_columns = ", ".join(
                '''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                for name, kind in lodgement_fields.items()
            )
            if lodgement_fields_columns:
                lodgement_fields_columns += ", "
            lodgement_fields_table = \
            """SELECT
                {lodgement_fields_columns}
                id
            FROM
                event.lodgements
            WHERE
                event_id = {event_id}""".format(
                lodgement_fields_columns=lodgement_fields_columns,
                event_id=event_id)

            # Retrieve generic lodgemnt group information.
            lodgement_group_table = \
            """SELECT
                tmp_id, title, regular_capacity, camping_mat_capacity
            FROM (
                (
                    (
                        SELECT
                            id AS tmp_id, title
                        FROM
                            event.lodgement_groups
                        WHERE
                            event_id = {event_id}
                    )
                    UNION
                    (
                        SELECT
                            -1, ''
                    )
                ) AS group_base
                LEFT OUTER JOIN (
                    SELECT
                        COALESCE(group_id, -1) as tmp_group_id,
                        SUM(regular_capacity) as regular_capacity,
                        SUM(camping_mat_capacity) as camping_mat_capacity
                    FROM
                        event.lodgements
                    WHERE
                        event_id = {event_id}
                    GROUP BY
                        tmp_group_id
                ) AS group_totals
                    ON group_base.tmp_id = group_totals.tmp_group_id
            )""".format(event_id=event_id)

            # Template for retrieveing lodgement information for one
            # specific part. We don't youse the {base} table from below, because
            # we need the id to be distinct.
            part_table_template = \
                """(
                    SELECT
                        id as base_id, COALESCE(group_id, -1) AS tmp_group_id
                    FROM
                        event.lodgements
                    WHERE
                        event_id = {event_id}
                ) AS base
                LEFT OUTER JOIN (
                    {inhabitants_view}
                ) AS inhabitants_view{part_id}
                    ON base.base_id = inhabitants_view{part_id}.id
                LEFT OUTER JOIN (
                    {group_inhabitants_view}
                ) AS group_inhabitants_view{part_id}
                    ON base.tmp_group_id =
                    group_inhabitants_view{part_id}.tmp_group_id"""

            def part_table(p_id: int) -> str:
                ptable = part_table_template.format(
                    event_id=event_id, part_id=p_id,
                    inhabitants_view=inhabitants_view(p_id),
                    group_inhabitants_view=group_inhabitants_view(p_id),
                )
                ret = f"""LEFT OUTER JOIN (
                    {ptable}
                ) AS part{p_id} ON lodgement.id = part{p_id}.base_id"""
                return ret

            inhabitants_counter = lambda p_id, rc: \
            """SELECT
                lodgement_id, COUNT(registration_id) AS inhabitants
            FROM
                event.registration_parts
            WHERE
                part_id = {part_id}
                {rc}
            GROUP BY
                lodgement_id""".format(part_id=p_id, rc=rc)

            inhabitants_view = lambda p_id: \
            """SELECT
                id, tmp_group_id,
                COALESCE(rp_regular.inhabitants, 0) AS regular_inhabitants,
                COALESCE(rp_camping_mat.inhabitants, 0)
                    AS camping_mat_inhabitants,
                COALESCE(rp_total.inhabitants, 0) AS total_inhabitants
            FROM
                (
                    SELECT id, COALESCE(group_id, -1) as tmp_group_id
                    FROM event.lodgements
                    WHERE event_id = {event_id}
                ) AS l
                LEFT OUTER JOIN (
                    {rp_regular}
                ) AS rp_regular ON l.id = rp_regular.lodgement_id
                LEFT OUTER JOIN (
                    {rp_camping_mat}
                ) AS rp_camping_mat ON l.id = rp_camping_mat.lodgement_id
                LEFT OUTER JOIN (
                    {rp_total}
                ) AS rp_total ON l.id = rp_total.lodgement_id""".format(
                    event_id=event_id,
                    rp_regular=inhabitants_counter(
                        p_id, "AND is_camping_mat = False"),
                    rp_camping_mat=inhabitants_counter(
                        p_id, "AND is_camping_mat = True"),
                    rp_total=inhabitants_counter(p_id, ""),
            )

            group_inhabitants_view = lambda p_id: \
            """SELECT
                tmp_group_id,
                COALESCE(SUM(regular_inhabitants)::bigint, 0)
                    AS group_regular_inhabitants,
                COALESCE(SUM(camping_mat_inhabitants)::bigint, 0)
                    AS group_camping_mat_inhabitants,
                COALESCE(SUM(total_inhabitants)::bigint, 0)
                    AS group_total_inhabitants
            FROM (
                {inhabitants_view}
            ) AS inhabitants_view{part_id}
            GROUP BY
                tmp_group_id""".format(
                inhabitants_view=inhabitants_view(p_id), part_id=p_id,
            )

            view = template.format(
                lodgement_table=lodgement_table,
                lodgement_fields_table=lodgement_fields_table,
                lodgement_group_table=lodgement_group_table,
                part_tables=" ".join(part_table(p_id)
                                     for p_id in event['parts']),
                event_id=event_id,
            )

            query.constraints.append(
                ("event_id", QueryOperators.equal, event_id))
            query.spec['event_id'] = "id"
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
