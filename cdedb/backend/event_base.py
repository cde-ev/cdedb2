#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy
import datetime
import decimal
from typing import (
    Any, Collection, Dict, Iterable, List, Optional, Protocol, Set, Tuple,
)

import psycopg2.extensions

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    PYTHON_TO_SQL_MAP, Silencer, DatabaseValue_s, access,
    affirm_set_validation as affirm_set, affirm_validation_typed as affirm,
    affirm_validation_typed_optional as affirm_optional, cast_fields, internal,
    singularize, affirm_array_validation as affirm_array,
)
from cdedb.backend.event_helpers import EventBackendHelpers
from cdedb.common import (
    COURSE_FIELDS, COURSE_SEGMENT_FIELDS,
    COURSE_TRACK_FIELDS, EVENT_FIELDS, EVENT_PART_FIELDS,
    EVENT_SCHEMA_VERSION, FEE_MODIFIER_FIELDS, FIELD_DEFINITION_FIELDS,
    LODGEMENT_FIELDS, LODGEMENT_GROUP_FIELDS, PERSONA_EVENT_FIELDS,
    QUESTIONNAIRE_ROW_FIELDS, REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS,
    REGISTRATION_TRACK_FIELDS, CdEDBObject, CdEDBObjectMap, CourseFilterPositions,
    DefaultReturnCode, DeletionBlockers, InfiniteEnum,
    PrivilegeError, PsycoJson, RequestState, glue, implying_realms, json_serialize, n_,
    now, unwrap, xsorted, STORED_EVENT_QUERY_FIELDS, CdEDBLog,
)
from cdedb.database.connection import Atomizer
from cdedb.filter import money_filter, date_filter
from cdedb.query import Query, QueryOperators, QueryScope

# type alias for questionnaire specification.
CdEDBQuestionnaire = Dict[const.QuestionnaireUsages, List[CdEDBObject]]


class EventBaseBackend(EventBackendHelpers):
    @access("event")
    def is_offline_locked(self, rs: RequestState, *, event_id: int = None,
                          course_id: int = None) -> bool:
        """Helper to determine if an event or course is locked for offline
        usage.

        Exactly one of the inputs has to be provided.
        """
        if event_id is not None and course_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        elif event_id is not None:
            anid = affirm(vtypes.ID, event_id)
            query = "SELECT offline_lock FROM event.events WHERE id = %s"
        elif course_id is not None:
            anid = affirm(vtypes.ID, course_id)
            query = glue(
                "SELECT offline_lock FROM event.events AS e",
                "LEFT OUTER JOIN event.courses AS c ON c.event_id = e.id",
                "WHERE c.id = %s")
        else:  # event_id is None and course_id is None:
            raise ValueError(n_("No input specified."))

        data = self.query_one(rs, query, (anid,))
        if data is None:
            raise ValueError(n_("Event does not exist"))
        return data['offline_lock']

    def assert_offline_lock(self, rs: RequestState, *, event_id: int = None,
                            course_id: int = None) -> None:
        """Helper to check locking state of an event or course.

        This raises an exception in case of the wrong locking state. Exactly
        one of the inputs has to be provided.
        """
        # the following does the argument checking
        is_locked = self.is_offline_locked(rs, event_id=event_id,
                                           course_id=course_id)
        if is_locked != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            raise RuntimeError(n_("Event offline lock error."))

    @access("persona")
    def orga_infos(self, rs: RequestState, persona_ids: Collection[int]
                   ) -> Dict[int, Set[int]]:
        """List events organized by specific personas."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        data = self.sql_select(rs, "event.orgas", ("persona_id", "event_id"),
                               persona_ids, entity_key="persona_id")
        ret = {}
        for anid in persona_ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    class _OrgaInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int) -> Set[int]: ...
    orga_info: _OrgaInfoProtocol = singularize(orga_infos, "persona_ids", "persona_id")

    @access("event")
    def retrieve_log(self, rs: RequestState,
                     codes: Collection[const.EventLogCodes] = None,
                     event_id: int = None, offset: int = None,
                     length: int = None, persona_id: int = None,
                     submitted_by: int = None, change_note: str = None,
                     time_start: datetime.datetime = None,
                     time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        event_id = affirm_optional(vtypes.ID, event_id)
        if (not (event_id and self.is_orga(rs, event_id=event_id))
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        event_ids = [event_id] if event_id else None
        return self.generic_retrieve_log(
            rs, const.EventLogCodes, "event", "event.log", codes=codes,
            entity_ids=event_ids, offset=offset, length=length,
            persona_id=persona_id, submitted_by=submitted_by,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    @access("anonymous")
    def list_events(self, rs: RequestState, visible: bool = None,
                       current: bool = None,
                       archived: bool = None) -> CdEDBObjectMap:
        """List all events organized via DB.

        :returns: Mapping of event ids to titles.
        """
        subquery = glue(
            "SELECT e.id, e.registration_start, e.title, e.is_visible,",
            "e.is_archived, e.is_cancelled, MAX(p.part_end) AS event_end",
            "FROM event.events AS e JOIN event.event_parts AS p",
            "ON p.event_id = e.id",
            "GROUP BY e.id")
        query = "SELECT e.* from ({}) as e".format(subquery)
        constraints = []
        params = []
        if visible is not None:
            constraints.append("is_visible = %s")
            params.append(visible)
        if current is not None:
            if current:
                constraints.append("e.event_end > now()")
                constraints.append("e.is_cancelled = False")
            else:
                constraints.append(
                    "(e.event_end <= now() OR e.is_cancelled = True)")
        if archived is not None:
            constraints.append("is_archived = %s")
            params.append(archived)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def list_courses(self, rs: RequestState,
                        event_id: int) -> CdEDBObjectMap:
        """List all courses organized via DB.

        :returns: Mapping of course ids to titles.
        """
        event_id = affirm(vtypes.ID, event_id)
        data = self.sql_select(rs, "event.courses", ("id", "title"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

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

    @access("anonymous")
    def get_events(self, rs: RequestState, event_ids: Collection[int]
                   ) -> CdEDBObjectMap:
        """Retrieve data for some events organized via DB.

        This queries quite a lot of additional tables since there is quite
        some data attached to such an event. Namely we have additional data on:

        * parts,
        * orgas,
        * fields.

        The tracks are inside the parts entry. This allows to create tracks
        during event creation.

        Furthermore we have the following derived keys:

        * tracks,
        * begin,
        * end,
        * is_open.
        """
        event_ids = affirm_set(vtypes.ID, event_ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.events", EVENT_FIELDS, event_ids)
            ret = {e['id']: e for e in data}
            data = self.sql_select(rs, "event.event_parts", EVENT_PART_FIELDS,
                                   event_ids, entity_key="event_id")
            all_parts = tuple(e['id'] for e in data)
            for anid in event_ids:
                parts = {d['id']: d for d in data if d['event_id'] == anid}
                if 'parts' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['parts'] = parts
            track_data = self.sql_select(
                rs, "event.course_tracks", COURSE_TRACK_FIELDS,
                all_parts, entity_key="part_id")
            fee_modifier_data = self.sql_select(
                rs, "event.fee_modifiers", FEE_MODIFIER_FIELDS,
                all_parts, entity_key="part_id")
            for anid in event_ids:
                for part_id in ret[anid]['parts']:
                    tracks = {d['id']: d for d in track_data if d['part_id'] == part_id}
                    if 'tracks' in ret[anid]['parts'][part_id]:
                        raise RuntimeError()
                    ret[anid]['parts'][part_id]['tracks'] = tracks
                    fee_modifiers = {d['id']: d for d in fee_modifier_data
                                     if d['part_id'] == part_id}
                    if 'fee_modifiers' in ret[anid]['parts'][part_id]:
                        raise RuntimeError()
                    ret[anid]['parts'][part_id]['fee_modifiers'] = fee_modifiers
                ret[anid]['tracks'] = {d['id']: d for d in track_data
                                       if d['part_id'] in ret[anid]['parts']}
                ret[anid]['fee_modifiers'] = {
                    d['id']: d for d in fee_modifier_data
                    if d['part_id'] in ret[anid]['parts']}
            data = self.sql_select(
                rs, "event.orgas", ("persona_id", "event_id"), event_ids,
                entity_key="event_id")
            for anid in event_ids:
                orgas = {d['persona_id'] for d in data if d['event_id'] == anid}
                if 'orgas' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['orgas'] = orgas
            data = self.sql_select(
                rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
                event_ids, entity_key="event_id")
            for anid in event_ids:
                fields = {d['id']: d for d in data if d['event_id'] == anid}
                if 'fields' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['fields'] = fields
        for anid in event_ids:
            ret[anid]['begin'] = min((p['part_begin']
                                      for p in ret[anid]['parts'].values()))
            ret[anid]['end'] = max((p['part_end']
                                    for p in ret[anid]['parts'].values()))
            ret[anid]['is_open'] = (
                    ret[anid]['registration_start']
                    and ret[anid]['registration_start'] <= now()
                    and (ret[anid]['registration_hard_limit'] is None
                         or ret[anid]['registration_hard_limit'] >= now()))
        return ret

    class _GetEventProtocol(Protocol):
        def __call__(self, rs: RequestState, event_id: int) -> CdEDBObject: ...
    get_event: _GetEventProtocol = singularize(get_events, "event_ids", "event_id")

    @access("event")
    def change_minor_form(self, rs: RequestState, event_id: int,
                          minor_form: Optional[bytes]) -> DefaultReturnCode:
        """Change or remove an event's minor form.

        Return 1 on successful change, -1 on successful deletion, 0 otherwise."""
        event_id = affirm(vtypes.ID, event_id)
        minor_form = affirm_optional(
            vtypes.PDFFile, minor_form, file_storage=False)
        if not (self.is_orga(rs, event_id=event_id) or self.is_admin(rs)):
            raise PrivilegeError(n_("Must be orga or admin to change the"
                                    " minor form."))
        path = self.minor_form_dir / str(event_id)
        if minor_form is None:
            if path.exists():
                path.unlink()
                # Since this is not acting on our database, do not demand an atomized
                # context.
                self.event_log(rs, const.EventLogCodes.minor_form_removed, event_id,
                               atomized=False)
                return -1
            else:
                return 0
        else:
            with open(path, "wb") as f:
                f.write(minor_form)
            # Since this is not acting on our database, do not demand an atomized
            # context.
            self.event_log(rs, const.EventLogCodes.minor_form_updated, event_id,
                           atomized=False)
            return 1

    @access("event")
    def get_minor_form(self, rs: RequestState,
                       event_id: int) -> Optional[bytes]:
        """Retrieve the minor form for an event.

        Returns None if no minor form exists for the given event."""
        event_id = affirm(vtypes.ID, event_id)
        # TODO accesscheck?
        path = self.minor_form_dir / str(event_id)
        ret = None
        if path.exists():
            with open(path, "rb") as f:
                ret = f.read()
        return ret

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

    @internal
    @access("event")
    def set_event_archived(self, rs: RequestState, data: CdEDBObject) -> None:
        """Wrapper around ``set_event()`` for archiving an event.

        This exists to emit the correct log message. It delegates
        everything else (like validation) to the wrapped method.
        """
        with Atomizer(rs):
            with Silencer(rs):
                self.set_event(rs, data)
            self.event_log(rs, const.EventLogCodes.event_archived,
                           data['id'])

    @access("event_admin")
    def add_event_orgas(self, rs: RequestState, event_id: int,
                        persona_ids: Collection[int]) -> DefaultReturnCode:
        """Add orgas to an event.

        This is basically un-inlined code from `set_event`, but may also be
        called separately.

        Note that this is only available to admins in contrast to `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        ret = 1
        with Atomizer(rs):
            if not self.core.verify_ids(rs, persona_ids, is_archived=False):
                raise ValueError(n_(
                    "Some of these orgas do not exist or are archived."))
            if not self.core.verify_personas(rs, persona_ids, {"event"}):
                raise ValueError(n_("Some of these orgas are not event users."))
            self.assert_offline_lock(rs, event_id=event_id)

            for anid in xsorted(persona_ids):
                new_orga = {
                    'persona_id': anid,
                    'event_id': event_id,
                }
                # on conflict do nothing
                r = self.sql_insert(rs, "event.orgas", new_orga,
                                    drop_on_conflict=True)
                if r:
                    self.event_log(rs, const.EventLogCodes.orga_added, event_id,
                                   persona_id=anid)
                ret *= r
        return ret

    @access("event_admin")
    def remove_event_orga(self, rs: RequestState, event_id: int,
                          persona_id: int) -> DefaultReturnCode:
        """Remove a single orga of an event.

        Note that this is only available to admins in contrast to `set_event`.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_id = affirm(vtypes.ID, persona_id)
        self.assert_offline_lock(rs, event_id=event_id)

        query = ("DELETE FROM event.orgas"
                 " WHERE persona_id = %s AND event_id = %s")
        with Atomizer(rs):
            ret = self.query_exec(rs, query, (persona_id, event_id))
            if ret:
                self.event_log(rs, const.EventLogCodes.orga_removed,
                               event_id, persona_id=persona_id)
        return ret

    @access("event")
    def set_event(self, rs: RequestState,
                  data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of an event organized via DB.

        The syntax for updating the associated data on orgas, parts and
        fields is as follows:

        * If the keys 'parts', 'fee_modifiers' or 'fields' are present,
          the associated dict mapping the part, fee_modifier or field ids to
          the respective data sets can contain an arbitrary number of entities,
          absent entities are not modified.

          Any valid entity id that is present has to map to a (partial or
          complete) data set or ``None``. In the first case the entity is
          updated, in the second case it is deleted. Deletion depends on
          the entity being nowhere referenced, otherwise an error is
          raised.

          Any invalid entity id (that is negative integer) has to map to a
          complete data set which will be used to create a new entity.

          The same logic applies to the 'tracks' dicts inside the
          'parts'. Deletion of parts implicitly deletes the dependent
          tracks and fee modifiers.

          Note that due to allowing only subsets of the existing fields,
          fee modifiers, parts and tracks to be given, there are some invalid
          combinations that cannot currently be detected at this point,
          e.g. trying to create a field with a `field_name` that already
          exists for this event. See Issue #1140.
        """
        data = affirm(vtypes.Event, data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])

        ret = 1
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            # Set top-level event fields.
            if len(edata) > 1:
                # Do additional validation for these references to custom datafields.
                indirect_fields = set(
                    edata[f] for f in ("lodge_field", "camping_mat_field",
                                       "course_room_field") if f in edata)
                if indirect_fields:
                    indirect_data = {e['id']: e for e in self.sql_select(
                        rs, "event.field_definitions",
                        ("id", "event_id", "kind", "association"), indirect_fields)}
                    if edata.get('lodge_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "lodge_field",
                            indirect_data[edata['lodge_field']])
                    if edata.get('camping_mat_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "camping_mat_field",
                            indirect_data[edata['camping_mat_field']])
                    if edata.get('course_room_field'):
                        self._validate_special_event_field(
                            rs, data['id'], "course_room_field",
                            indirect_data[edata['course_room_field']])
                ret *= self.sql_update(rs, "event.events", edata)
                self.event_log(rs, const.EventLogCodes.event_changed,
                               data['id'])

            if 'orgas' in data:
                ret *= self.add_event_orgas(rs, data['id'], data['orgas'])
            if 'fields' in data:
                ret *= self._set_event_fields(rs, data['id'], data['fields'])
            # This also includes taking care of course tracks and fee modifiers, since
            # they are each linked to a single event part.
            if 'parts' in data:
                ret *= self._set_event_parts(rs, data['id'], data['parts'])

        return ret

    @access("event_admin")
    def create_event(self, rs: RequestState,
                     data: CdEDBObject) -> DefaultReturnCode:
        """Make a new event organized via DB."""
        data = affirm(vtypes.Event, data, creation=True)
        if 'parts' not in data:
            raise ValueError(n_("At least one event part required."))
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            new_id = self.sql_insert(rs, "event.events", edata)
            self.event_log(rs, const.EventLogCodes.event_created, new_id)
            update_data = {aspect: data[aspect]
                           for aspect in ('parts', 'orgas', 'fields',
                                          'fee_modifiers')
                           if aspect in data}
            if update_data:
                update_data['id'] = new_id
                self.set_event(rs, update_data)
        return new_id

    @access("anonymous")
    def get_courses(self, rs: RequestState, course_ids: Collection[int]
                    ) -> CdEDBObjectMap:
        """Retrieve data for some courses organized via DB.

        They must be associated to the same event. This contains additional
        information on the parts in which the course takes place.
        """
        course_ids = affirm_set(vtypes.ID, course_ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.courses", COURSE_FIELDS, course_ids)
            if not data:
                return {}
            ret = {e['id']: e for e in data}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_("Only courses from one event allowed."))
            event_fields = self._get_event_fields(rs, unwrap(events))
            data = self.sql_select(
                rs, "event.course_segments", COURSE_SEGMENT_FIELDS, course_ids,
                entity_key="course_id")
            for anid in course_ids:
                segments = {p['track_id'] for p in data if p['course_id'] == anid}
                if 'segments' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['segments'] = segments
                active_segments = {p['track_id'] for p in data
                                   if p['course_id'] == anid and p['is_active']}
                if 'active_segments' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['active_segments'] = active_segments
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'], event_fields)
        return ret

    class _GetCourseProtocol(Protocol):
        def __call__(self, rs: RequestState, course_id: int) -> CdEDBObject: ...
    get_course: _GetCourseProtocol = singularize(get_courses, "course_ids", "course_id")

    @access("event")
    def set_course(self, rs: RequestState,
                   data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a course linked to an event organized via DB.

        If the 'segments' key is present you have to pass the complete list
        of track IDs, which will superseed the current list of tracks.

        If the 'active_segments' key is present you have to pass the
        complete list of active track IDs, which will superseed the current
        list of active tracks. This has to be a subset of the segments of
        the course.
        """
        data = affirm(vtypes.Course, data)
        if not self.is_orga(rs, course_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            current = self.sql_select_one(rs, "event.courses",
                                          ("title", "event_id"), data['id'])
            assert current is not None

            cdata = {k: v for k, v in data.items()
                     if k in COURSE_FIELDS and k != "fields"}
            changed = False
            if len(cdata) > 1:
                ret *= self.sql_update(rs, "event.courses", cdata)
                changed = True
            if 'fields' in data:
                # delayed validation since we need additional info
                event_fields = self._get_event_fields(rs, current['event_id'])
                fdata = affirm(
                    vtypes.EventAssociatedFields, data['fields'],
                    fields=event_fields,
                    association=const.FieldAssociations.course)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.courses",
                                                    fupdate)
                changed = True
            if changed:
                self.event_log(
                    rs, const.EventLogCodes.course_changed, current['event_id'],
                    change_note=current['title'])
            if 'segments' in data:
                current_segments = self.sql_select(
                    rs, "event.course_segments", ("track_id",),
                    (data['id'],), entity_key="course_id")
                existing = {e['track_id'] for e in current_segments}
                new = data['segments'] - existing
                deleted = existing - data['segments']
                if new:
                    # check, that all new tracks belong to the event of the
                    # course
                    tracks = self.sql_select(
                        rs, "event.course_tracks", ("part_id",), new)
                    associated_parts = list(unwrap(e) for e in tracks)
                    associated_events = self.sql_select(
                        rs, "event.event_parts", ("event_id",),
                        associated_parts)
                    event_ids = {e['event_id'] for e in associated_events}
                    if {current['event_id']} != event_ids:
                        raise ValueError(n_("Non-associated tracks found."))

                    for anid in new:
                        insert = {
                            'course_id': data['id'],
                            'track_id': anid,
                            'is_active': True,
                        }
                        ret *= self.sql_insert(rs, "event.course_segments",
                                               insert)
                if deleted:
                    query = ("DELETE FROM event.course_segments"
                             " WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deleted))
                if new or deleted:
                    self.event_log(
                        rs, const.EventLogCodes.course_segments_changed,
                        current['event_id'], change_note=current['title'])
            if 'active_segments' in data:
                current_segments = self.sql_select(
                    rs, "event.course_segments", ("track_id", "is_active"),
                    (data['id'],), entity_key="course_id")
                existing = {e['track_id'] for e in current_segments}
                # check that all active segments are actual segments of this
                # course
                if not existing >= data['active_segments']:
                    raise ValueError(n_("Wrong-associated segments found."))
                active = {e['track_id'] for e in current_segments
                          if e['is_active']}
                activated = data['active_segments'] - active
                deactivated = active - data['active_segments']
                if activated:
                    query = glue(
                        "UPDATE event.course_segments SET is_active = True",
                        "WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], activated))
                if deactivated:
                    query = glue(
                        "UPDATE event.course_segments SET is_active = False",
                        "WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deactivated))
                if activated or deactivated:
                    self.event_log(
                        rs, const.EventLogCodes.course_segment_activity_changed,
                        current['event_id'], change_note=current['title'])
        return ret

    @access("event")
    def create_course(self, rs: RequestState,
                      data: CdEDBObject) -> DefaultReturnCode:
        """Make a new course organized via DB."""
        data = affirm(vtypes.Course, data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata,
            fields=event_fields, association=const.FieldAssociations.course)
        data['fields'] = PsycoJson(fdata)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            # Check for existence of course tracks
            event = self.get_event(rs, data['event_id'])
            if not event['tracks']:
                raise RuntimeError(n_("Event without tracks forbids courses."))

            cdata = {k: v for k, v in data.items()
                     if k in COURSE_FIELDS}
            new_id = self.sql_insert(rs, "event.courses", cdata)
            if 'segments' in data or 'active_segments' in data:
                pdata = {
                    'id': new_id,
                }
                if 'segments' in data:
                    pdata['segments'] = data['segments']
                if 'active_segments' in data:
                    pdata['active_segments'] = data['active_segments']
                self.set_course(rs, pdata)
            self.event_log(rs, const.EventLogCodes.course_created,
                           data['event_id'], change_note=data['title'])
        return new_id

    @access("event")
    def delete_course_blockers(self, rs: RequestState,
                               course_id: int) -> DeletionBlockers:
        """Determine what keeps a course from beeing deleted.

        Possible blockers:

        * attendees: A registration track that assigns a registration to
                     the course as an attendee.
        * instructors: A registration track that references the course meaning
                       the participant is (potentially) the course's instructor.
        * course_choices: A course choice of the course.
        * course_segments: The course segments of the course.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        course_id = affirm(vtypes.ID, course_id)
        blockers = {}

        attendees = self.sql_select(
            rs, "event.registration_tracks", ("id",), (course_id,),
            entity_key="course_id")
        if attendees:
            blockers["attendees"] = [e["id"] for e in attendees]

        instructors = self.sql_select(
            rs, "event.registration_tracks", ("id",), (course_id,),
            entity_key="course_instructor")
        if instructors:
            blockers["instructors"] = [e["id"] for e in instructors]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (course_id,),
            entity_key="course_id")
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        course_segments = self.sql_select(
            rs, "event.course_segments", ("id",), (course_id,),
            entity_key="course_id")
        if course_segments:
            blockers["course_segments"] = [e["id"] for e in course_segments]

        return blockers

    @access("event")
    def delete_course(self, rs: RequestState, course_id: int,
                      cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove a course organized via DB from the DB.

        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        """
        course_id = affirm(vtypes.ID, course_id)
        if (not self.is_orga(rs, course_id=course_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=course_id)

        blockers = self.delete_course_blockers(rs, course_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "course",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            course = self.get_course(rs, course_id)
            # cascade specified blockers
            if cascade:
                if "attendees" in cascade:
                    for anid in blockers["attendees"]:
                        deletor = {
                            'course_id': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(
                            rs, "event.registration_tracks", deletor)
                if "instructors" in cascade:
                    for anid in blockers["instructors"]:
                        deletor = {
                            'course_instructor': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(
                            rs, "event.registration_tracks", deletor)
                if "course_choices" in cascade:
                    # Get the data of the affected choices grouped by track.
                    data = self.sql_select(
                        rs, "event.course_choices",
                        ("track_id", "registration_id"),
                        blockers["course_choices"])
                    data_by_tracks = {
                        track_id: [e["registration_id"] for e in data
                                   if e["track_id"] == track_id]
                        for track_id in set(e["track_id"] for e in data)
                    }

                    # Delete choices of the deletable course.
                    ret *= self.sql_delete(
                        rs, "event.course_choices", blockers["course_choices"])

                    # Construct list of inserts.
                    choices: List[CdEDBObject] = []
                    for track_id, reg_ids in data_by_tracks.items():
                        query = (
                            "SELECT id, course_id, track_id, registration_id"
                            " FROM event.course_choices"
                            " WHERE track_id = {} AND registration_id = ANY(%s)"
                            " ORDER BY registration_id, rank").format(track_id)
                        choices.extend(self.query_all(rs, query, (reg_ids,)))

                    deletion_ids = {e['id'] for e in choices}

                    # Update the ranks and remove the ids from the insert data.
                    i = 0
                    current_id = None
                    for row in choices:
                        if current_id != row['registration_id']:
                            current_id = row['registration_id']
                            i = 0
                        row['rank'] = i
                        del row['id']
                        i += 1

                    self.sql_delete(rs, "event.course_choices", deletion_ids)
                    self.sql_insert_many(rs, "event.course_choices", choices)

                if "course_segments" in cascade:
                    ret *= self.sql_delete(rs, "event.course_segments",
                                           blockers["course_segments"])

                # check if course is deletable after cascading
                blockers = self.delete_course_blockers(rs, course_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.courses", course_id)
                self.event_log(rs, const.EventLogCodes.course_deleted,
                               course['event_id'],
                               change_note=course['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "course", "block": blockers.keys()})
        return ret

    @access("event")
    def list_persona_registrations(
        self, rs: RequestState, persona_id: int
    ) -> Dict[int, Dict[int, Dict[int, const.RegistrationPartStati]]]:
        """List all events a given user has a registration for.

        :returns: Mapping of event ids to
            (registration id to (part id to registration status))
        """
        if not (self.is_admin(rs) or self.core.is_relative_admin(rs, persona_id)
                or rs.user.persona_id == persona_id):
            raise PrivilegeError(n_("Not privileged."))
        persona_id = affirm(vtypes.ID, persona_id)

        query = ("SELECT event_id, registration_id, part_id, status"
                 " FROM event.registrations"
                 " LEFT JOIN event.registration_parts"
                 " ON registrations.id = registration_parts.registration_id"
                 " WHERE persona_id = %s")
        data = self.query_all(rs, query, (persona_id,))
        ret: Dict[int, Dict[int, Dict[int, const.RegistrationPartStati]]] = {}
        for e in data:
            ret.setdefault(
                e['event_id'], {}
            ).setdefault(
                e['registration_id'], {}
            )[e['part_id']] = const.RegistrationPartStati(e['status'])
        return ret

    @access("event", "ml_admin")
    def list_registrations_personas(self, rs: RequestState, event_id: int,
                                    persona_ids: Collection[int] = None
                                    ) -> Dict[int, int]:
        """List all registrations of an event.

        :param persona_ids: If passed restrict to registrations by these personas.
        :returns: Mapping of registration ids to persona_ids.
        """
        if not persona_ids:
            persona_ids = set()
        event_id = affirm(vtypes.ID, event_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        # ml_admins are allowed to do this to be able to manage
        # subscribers of event mailinglists.
        if (persona_ids != {rs.user.persona_id}
                and not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)
                and "ml_admin" not in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))

        query = "SELECT id, persona_id FROM event.registrations"
        conditions = ["event_id = %s"]
        params: List[Any] = [event_id]
        if persona_ids:
            conditions.append("persona_id = ANY(%s)")
            params.append(persona_ids)
        query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event", "ml_admin")
    def list_registrations(self, rs: RequestState, event_id: int, persona_id: int = None
                           ) -> Dict[int, int]:
        """Manual singularization of list_registrations_personas

        Handles default values properly.
        """
        if persona_id:
            return self.list_registrations_personas(rs, event_id, {persona_id})
        else:
            return self.list_registrations_personas(rs, event_id)

    @access("event")
    def list_participants(self, rs: RequestState, event_id: int) -> Dict[int, int]:
        """List all participants of an event.

        Just participants of this event are returned and the requester himself must
        have the status 'participant'.

        :returns: Mapping of registration ids to persona_ids.
        """
        event_id = affirm(vtypes.ID, event_id)

        # In this case, privilege check is performed afterwards since it depends on
        # the result of the query.
        query = """SELECT DISTINCT
            regs.id, regs.persona_id
        FROM
            event.registrations AS regs
            LEFT OUTER JOIN
                event.registration_parts AS rparts
            ON rparts.registration_id = regs.id"""
        conditions = ["regs.event_id = %s", "rparts.status = %s"]
        params = [event_id, const.RegistrationPartStati.participant]
        query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e['persona_id'] for e in data}

        if not (rs.user.persona_id in ret.values()
                or self.is_orga(rs, event_id=event_id)
                or self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        return ret

    @access("persona")
    def check_registrations_status(
            self, rs: RequestState, persona_ids: Collection[int], event_id: int,
            stati: Collection[const.RegistrationPartStati]) -> Dict[int, bool]:
        """Check if any status for a given event matches one of the given stati.

        This is mostly used to determine mailinglist eligibility. Thus,
        ml_admins are allowed to do this to manage subscribers.

        A user may do this for themselves, an orga for their event and an
        event or ml admin for every user.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        event_id = affirm(vtypes.ID, event_id)
        stati = affirm_set(const.RegistrationPartStati, stati)

        # By default, assume no participation.
        ret = {anid: False for anid in persona_ids}

        # First, rule out people who can not participate at any event.
        if (persona_ids == {rs.user.persona_id} and
                "event" not in rs.user.roles):
            return ret

        # Check if eligible to check registration status for other users.
        if not (persona_ids == {rs.user.persona_id}
                or self.is_orga(rs, event_id=event_id)
                or self.is_admin(rs)
                or "ml_admin" in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))

        registration_ids = self.list_registrations_personas(rs, event_id, persona_ids)
        if not registration_ids:
            return {anid: False for anid in persona_ids}

        registrations = self.get_registrations(rs, registration_ids)
        ret.update({reg['persona_id']:
                        any(part['status'] in stati for part in reg['parts'].values())
                    for reg in registrations.values()})
        return ret

    class _GetRegistrationStatusProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int, event_id: int,
                     stati: Collection[const.RegistrationPartStati]) -> bool: ...
    check_registration_status: _GetRegistrationStatusProtocol = singularize(
        check_registrations_status, "persona_ids", "persona_id")

    @access("event")
    def get_registration_map(self, rs: RequestState, event_ids: Collection[int]
                             ) -> Dict[Tuple[int, int], int]:
        """Retrieve a map of personas to their registrations."""
        event_ids = affirm_set(vtypes.ID, event_ids)
        if (not all(self.is_orga(rs, event_id=anid) for anid in event_ids) and
                not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))

        data = self.sql_select(
            rs, "event.registrations", ("id", "persona_id", "event_id"),
            event_ids, entity_key="event_id")
        ret = {(e["event_id"], e["persona_id"]): e["id"] for e in data}

        return ret

    @internal
    @access("event")
    def _get_waitlist(self, rs: RequestState, event_id: int,
                      part_ids: Collection[int] = None
                      ) -> Dict[int, Optional[List[int]]]:
        """Compute the waitlist in order for the given parts.

        :returns: Part id maping to None, if no waitlist ordering is defined
            or a list of registration ids otherwise.
        """
        event_id = affirm(vtypes.ID, event_id)
        part_ids = affirm_set(vtypes.ID, part_ids or set())
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            if not part_ids:
                part_ids = event['parts'].keys()
            elif not part_ids <= event['parts'].keys():
                raise ValueError(n_("Unknown part for the given event."))
            ret: Dict[int, Optional[List[int]]] = {}
            waitlist = const.RegistrationPartStati.waitlist
            query = ("SELECT id, fields FROM event.registrations"
                     " WHERE event_id = %s")
            fields_by_id = {
                reg['id']: cast_fields(reg['fields'], event['fields'])
                for reg in self.query_all(rs, query, (event_id,))}
            for part_id in part_ids:
                part = event['parts'][part_id]
                if not part['waitlist_field']:
                    ret[part_id] = None
                    continue
                field_name = event['fields'][part['waitlist_field']]['field_name']
                query = ("SELECT reg.id, rparts.status"
                         " FROM event.registrations AS reg"
                         " LEFT OUTER JOIN event.registration_parts AS rparts"
                         " ON reg.id = rparts.registration_id"
                         " WHERE rparts.part_id = %s AND rparts.status = %s")
                data = self.query_all(rs, query, (part_id, waitlist))
                ret[part_id] = xsorted(
                    (reg['id'] for reg in data),
                    key=lambda r_id: (fields_by_id[r_id].get(field_name, 0) or 0, r_id))  # pylint: disable=cell-var-from-loop
            return ret

    @access("event")
    def get_waitlist(self, rs: RequestState, event_id: int,
                     part_ids: Collection[int] = None
                     ) -> Dict[int, Optional[List[int]]]:
        """Public wrapper around _get_waitlist. Adds privilege check."""
        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Must be orga to access full waitlist."))
        return self._get_waitlist(rs, event_id, part_ids)

    @access("event")
    def get_waitlist_position(self, rs: RequestState, event_id: int,
                              part_ids: Collection[int] = None,
                              persona_id: int = None
                              ) -> Dict[int, Optional[int]]:
        """Compute the waitlist position of a user for the given parts.

        :returns: Mapping of part id to position on waitlist or None if user is
            not on the waitlist in that part.
        """
        full_waitlist = self._get_waitlist(rs, event_id, part_ids)
        if persona_id is None:
            persona_id = rs.user.persona_id
        if persona_id != rs.user.persona_id:
            if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
                raise PrivilegeError(
                    n_("Must be orga to access full waitlist."))
        reg_ids = self.list_registrations(rs, event_id, persona_id)
        if not reg_ids:
            raise ValueError(n_("Not registered for this event."))
        reg_id = unwrap(reg_ids.keys())
        ret: Dict[int, Optional[int]] = {}
        for part_id, waitlist in full_waitlist.items():
            try:
                # If `reg_id` is not in the list, a ValueError will be raised.
                # Offset the index by one.
                ret[part_id] = (waitlist or []).index(reg_id) + 1
            except ValueError:
                ret[part_id] = None
        return ret

    @access("event")
    def registrations_by_course(
            self, rs: RequestState, event_id: int, course_id: int = None,
            track_id: int = None, position: InfiniteEnum[CourseFilterPositions] = None,
            reg_ids: Collection[int] = None,
            reg_states: Collection[const.RegistrationPartStati] =
            (const.RegistrationPartStati.participant,)) -> Dict[int, int]:
        """List registrations of an event pertaining to a certain course.

        This is a filter function, mainly for the course assignment tool.

        :param position: A :py:class:`cdedb.common.CourseFilterPositions`
        :param reg_ids: List of registration states (in any part) to filter for
        """
        event_id = affirm(vtypes.ID, event_id)
        track_id = affirm_optional(vtypes.ID, track_id)
        course_id = affirm_optional(vtypes.ID, course_id)
        position = affirm_optional(InfiniteEnum[CourseFilterPositions], position)
        reg_ids = reg_ids or set()
        reg_ids = affirm_set(vtypes.ID, reg_ids)
        reg_states = affirm_set(const.RegistrationPartStati, reg_states)
        if (not self.is_admin(rs)
                and not self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))
        query = """SELECT DISTINCT
            regs.id, regs.persona_id
        FROM
            event.registrations AS regs
            LEFT OUTER JOIN
                event.registration_parts
            AS rparts ON rparts.registration_id = regs.id
            LEFT OUTER JOIN
                event.course_tracks
            AS course_tracks ON course_tracks.part_id = rparts.part_id
            LEFT OUTER JOIN
                event.registration_tracks
            AS rtracks ON rtracks.registration_id = regs.id
                AND rtracks.track_id = course_tracks.id
            LEFT OUTER JOIN
                event.course_choices
            AS choices ON choices.registration_id = regs.id
                AND choices.track_id = course_tracks.id"""
        conditions = ["regs.event_id = %s", "rparts.status = ANY(%s)"]
        params: List[Any] = [event_id, reg_states]
        if track_id:
            conditions.append("course_tracks.id = %s")
            params.append(track_id)
        if position is not None:
            cfp = CourseFilterPositions
            sub_conditions = []
            if position.enum in (cfp.instructor, cfp.anywhere):
                if course_id:
                    sub_conditions.append("rtracks.course_instructor = %s")
                    params.append(course_id)
                else:
                    sub_conditions.append("rtracks.course_instructor IS NULL")
            if position.enum in (cfp.any_choice, cfp.anywhere) and course_id:
                sub_conditions.append(
                    "(choices.course_id = %s AND "
                    " choices.rank < course_tracks.num_choices)")
                params.append(course_id)
            if position.enum == cfp.specific_rank and course_id:
                sub_conditions.append(
                    "(choices.course_id = %s AND choices.rank = %s)")
                params.extend((course_id, position.int))
            if position.enum in (cfp.assigned, cfp.anywhere):
                if course_id:
                    sub_conditions.append("rtracks.course_id = %s")
                    params.append(course_id)
                else:
                    sub_conditions.append("rtracks.course_id IS NULL")
            if sub_conditions:
                conditions.append(f"( {' OR '.join(sub_conditions)} )")
        if reg_ids:
            conditions.append("regs.id = ANY(%s)")
            params.append(reg_ids)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event", "ml_admin")
    def get_registrations(self, rs: RequestState, registration_ids: Collection[int]
                          ) -> CdEDBObjectMap:
        """Retrieve data for some registrations.

        All have to be from the same event.
        You must be orga to get additional access to all registrations which are
        not your own. If you are participant of the event, you get access to
        data from other users, being also participant in the same event (this is
        important for the online participant list).
        This includes the following additional data:

        * parts: per part data (like lodgement),
        * tracks: per track data (like course choices)

        ml_admins are allowed to do this to be able to manage
        subscribers of event mailinglists.
        """
        registration_ids = affirm_set(vtypes.ID, registration_ids)
        with Atomizer(rs):
            # Check associations.
            associated = self.sql_select(rs, "event.registrations",
                                         ("persona_id", "event_id"), registration_ids)
            if not associated:
                return {}
            events = {e['event_id'] for e in associated}
            personas = {e['persona_id'] for e in associated}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))
            event_id = unwrap(events)
            # Select appropriate stati filter.
            stati = set(m for m in const.RegistrationPartStati)
            # orgas and admins have full access to all data
            # ml_admins are allowed to do this to be able to manage
            # subscribers of event mailinglists.
            is_privileged = (self.is_orga(rs, event_id=event_id)
                             or self.is_admin(rs)
                             or "ml_admin" in rs.user.roles)
            if not is_privileged:
                if rs.user.persona_id not in personas:
                    raise PrivilegeError(n_("Not privileged."))
                elif not personas <= {rs.user.persona_id}:
                    # Permission check is done later when we know more
                    stati = {const.RegistrationPartStati.participant}

            query = f"""
                SELECT {", ".join(REGISTRATION_FIELDS)}, ctime, mtime
                FROM event.registrations
                LEFT OUTER JOIN (
                    SELECT persona_id AS log_persona_id, MAX(ctime) AS ctime
                    FROM event.log WHERE code = %s GROUP BY log_persona_id
                ) AS ctime
                ON event.registrations.persona_id = ctime.log_persona_id
                LEFT OUTER JOIN (
                    SELECT persona_id AS log_persona_id, MAX(ctime) AS mtime
                    FROM event.log WHERE code = %s GROUP BY log_persona_id
                ) AS mtime
                ON event.registrations.persona_id = mtime.log_persona_id
                WHERE event.registrations.id = ANY(%s)
                """
            params = (const.EventLogCodes.registration_created,
                      const.EventLogCodes.registration_changed, registration_ids)
            rdata = self.query_all(rs, query, params)
            ret = {reg['id']: reg for reg in rdata}

            pdata = self.sql_select(
                rs, "event.registration_parts", REGISTRATION_PART_FIELDS,
                registration_ids, entity_key="registration_id")
            for anid in tuple(ret):
                if 'parts' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['parts'] = {
                    e['part_id']: e for e in pdata if e['registration_id'] == anid
                }
                # Limit to registrations matching stati filter in any part.
                if not any(e['status'] in stati for e in ret[anid]['parts'].values()):
                    del ret[anid]

            # Here comes the promised permission check
            if not is_privileged and all(reg['persona_id'] != rs.user.persona_id
                                         for reg in ret.values()):
                raise PrivilegeError(n_("No participant of event."))

            tdata = self.sql_select(
                rs, "event.registration_tracks", REGISTRATION_TRACK_FIELDS,
                registration_ids, entity_key="registration_id")
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"), registration_ids,
                entity_key="registration_id")
            event_fields = self._get_event_fields(rs, event_id)
            for anid in ret:
                if 'tracks' in ret[anid]:
                    raise RuntimeError()
                tracks = {e['track_id']: e for e in tdata
                          if e['registration_id'] == anid}
                for track_id in tracks:
                    tmp = {e['course_id']: e['rank'] for e in choices
                           if (e['registration_id'] == anid
                               and e['track_id'] == track_id)}
                    tracks[track_id]['choices'] = xsorted(tmp.keys(), key=tmp.get)
                ret[anid]['tracks'] = tracks
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'], event_fields)

        return ret

    class _GetRegistrationProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int) -> CdEDBObject: ...
    get_registration: _GetRegistrationProtocol = singularize(
        get_registrations, "registration_ids", "registration_id")

    @access("event")
    def set_registration(self, rs: RequestState, data: CdEDBObject,
                         change_note: str = None) -> DefaultReturnCode:
        """Update some keys of a registration.

        The syntax for updating the non-trivial keys fields, parts and
        choices is as follows:

        * If the key 'fields' is present it must be a dict and is used to
          updated the stored value (in a python dict.update sense).
        * If the key 'parts' is present, the associated dict mapping the
          part ids to the respective data sets can contain an arbitrary
          number of entities, absent entities are not modified. Entries are
          created/updated as applicable.
        * If the key 'tracks' is present, the associated dict mapping the
          track ids to the respective data sets can contain an arbitrary
          number of entities, absent entities are not
          modified. Entries are created/updated as applicable. The
          'choices' key is handled separately and if present replaces
          the current list of course choices.
        """
        data = affirm(vtypes.Registration, data)
        change_note = affirm_optional(str, change_note)
        with Atomizer(rs):
            # Retrieve some basic data about the registration.
            current = self._get_registration_info(rs, reg_id=data['id'])
            if current is None:
                raise ValueError(n_("Registration does not exist."))
            persona_id, event_id = current['persona_id'], current['event_id']
            self.assert_offline_lock(rs, event_id=event_id)
            if (persona_id != rs.user.persona_id
                    and not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            course_segments = self._get_event_course_segments(rs, event_id)
            if "amount_owed" in data:
                del data["amount_owed"]

            # now we get to do the actual work
            rdata = {k: v for k, v in data.items()
                     if k in REGISTRATION_FIELDS and k != "fields"}
            ret = 1
            if len(rdata) > 1:
                ret *= self.sql_update(rs, "event.registrations", rdata)
            if 'fields' in data:
                # delayed validation since we need additional info
                fdata = affirm(
                    vtypes.EventAssociatedFields, data['fields'],
                    fields=event['fields'],
                    association=const.FieldAssociations.registration)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.registrations",
                                                    fupdate)
            if 'parts' in data:
                parts = data['parts']
                if not event['parts'].keys() >= parts.keys():
                    raise ValueError(n_("Non-existing parts specified."))
                existing = {e['part_id']: e['id'] for e in self.sql_select(
                    rs, "event.registration_parts", ("id", "part_id"),
                    (data['id'],), entity_key="registration_id")}
                new = {x for x in parts if x not in existing}
                updated = {x for x in parts
                           if x in existing and parts[x] is not None}
                deleted = {x for x in parts
                           if x in existing and parts[x] is None}
                for x in new:
                    new_part = copy.deepcopy(parts[x])
                    new_part['registration_id'] = data['id']
                    new_part['part_id'] = x
                    ret *= self.sql_insert(rs, "event.registration_parts",
                                           new_part)
                for x in updated:
                    update = copy.deepcopy(parts[x])
                    update['id'] = existing[x]
                    ret *= self.sql_update(rs, "event.registration_parts",
                                           update)
                if deleted:
                    raise NotImplementedError(n_("This is not useful."))
            if 'tracks' in data:
                tracks = data['tracks']
                if not set(tracks).issubset(event['tracks']):
                    raise ValueError(n_("Non-existing tracks specified."))
                existing = {e['track_id']: e['id'] for e in self.sql_select(
                    rs, "event.registration_tracks", ("id", "track_id"),
                    (data['id'],), entity_key="registration_id")}
                new = {x for x in tracks if x not in existing}
                updated = {x for x in tracks
                           if x in existing and tracks[x] is not None}
                deleted = {x for x in tracks
                           if x in existing and tracks[x] is None}
                for x in new:
                    new_track = copy.deepcopy(tracks[x])
                    choices = new_track.pop('choices', None)
                    self._set_course_choices(rs, data['id'], x, choices,
                                             course_segments)
                    new_track['registration_id'] = data['id']
                    new_track['track_id'] = x
                    ret *= self.sql_insert(rs, "event.registration_tracks",
                                           new_track)
                for x in updated:
                    update = copy.deepcopy(tracks[x])
                    choices = update.pop('choices', None)
                    self._set_course_choices(rs, data['id'], x, choices,
                                             course_segments)
                    update['id'] = existing[x]
                    ret *= self.sql_update(rs, "event.registration_tracks",
                                           update)
                if deleted:
                    raise NotImplementedError(n_("This is not useful."))

            # Recalculate the amount owed after all changes have been applied.
            current = self.get_registration(rs, data['id'])
            update = {
                'id': data['id'],
                'amount_owed': self._calculate_single_fee(
                    rs, current, event=event)
            }
            ret *= self.sql_update(rs, "event.registrations", update)
            self.event_log(
                rs, const.EventLogCodes.registration_changed, event_id,
                persona_id=persona_id, change_note=change_note)
        return ret

    @access("event")
    def create_registration(self, rs: RequestState,
                            data: CdEDBObject) -> DefaultReturnCode:
        """Make a new registration.

        The data must contain a dataset for each part and each track
        and may not contain a value for 'fields', which is initialized
        to a default value.
        """
        data = affirm(vtypes.Registration, data, creation=True)
        event = self.get_event(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata, fields=event['fields'],
            association=const.FieldAssociations.registration)
        if (data['persona_id'] != rs.user.persona_id
                and not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        with Atomizer(rs):
            if not self.core.verify_id(rs, data['persona_id'], is_archived=False):
                raise ValueError(n_("This user does not exist or is archived."))
            if not self.core.verify_persona(rs, data['persona_id'], {"event"}):
                raise ValueError(n_("This user is not an event user."))
            self.assert_offline_lock(rs, event_id=data['event_id'])
            data['fields'] = fdata
            data['amount_owed'] = self._calculate_single_fee(
                rs, data, event=event)
            data['fields'] = PsycoJson(fdata)
            course_segments = self._get_event_course_segments(rs,
                                                              data['event_id'])
            part_ids = {e['id'] for e in self.sql_select(
                rs, "event.event_parts", ("id",), (data['event_id'],),
                entity_key="event_id")}
            if part_ids != set(data['parts'].keys()):
                raise ValueError(n_("Missing part dataset."))
            track_ids = {e['id'] for e in self.sql_select(
                rs, "event.course_tracks", ("id",), part_ids,
                entity_key="part_id")}
            if track_ids != set(data['tracks'].keys()):
                raise ValueError(n_("Missing track dataset."))
            rdata = {k: v for k, v in data.items() if k in REGISTRATION_FIELDS}
            new_id = self.sql_insert(rs, "event.registrations", rdata)

            # Uninlined code from set_registration to make this more
            # performant.
            #
            # insert parts
            for part_id, part in data['parts'].items():
                new_part = copy.deepcopy(part)
                new_part['registration_id'] = new_id
                new_part['part_id'] = part_id
                self.sql_insert(rs, "event.registration_parts", new_part)
            # insert tracks
            for track_id, track in data['tracks'].items():
                new_track = copy.deepcopy(track)
                choices = new_track.pop('choices', None)
                self._set_course_choices(rs, new_id, track_id, choices,
                                         course_segments, new_registration=True)
                new_track['registration_id'] = new_id
                new_track['track_id'] = track_id
                self.sql_insert(rs, "event.registration_tracks", new_track)
            self.event_log(
                rs, const.EventLogCodes.registration_created, data['event_id'],
                persona_id=data['persona_id'])
        return new_id

    @access("event")
    def delete_registration_blockers(self, rs: RequestState,
                                     registration_id: int) -> DeletionBlockers:
        """Determine what keeps a registration from being deleted.

        Possible blockers:

        * registration_parts: The registration's registration parts.
        * registration_tracks: The registration's registration tracks.
        * course_choices: The registrations course choices.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        registration_id = affirm(vtypes.ID, registration_id)
        blockers = {}

        reg_parts = self.sql_select(
            rs, "event.registration_parts", ("id",), (registration_id,),
            entity_key="registration_id")
        if reg_parts:
            blockers["registration_parts"] = [e["id"] for e in reg_parts]

        reg_tracks = self.sql_select(
            rs, "event.registration_tracks", ("id",), (registration_id,),
            entity_key="registration_id")
        if reg_tracks:
            blockers["registration_tracks"] = [e["id"] for e in reg_tracks]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (registration_id,),
            entity_key="registration_id")
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        return blockers

    @access("event")
    def delete_registration(self, rs: RequestState, registration_id: int,
                            cascade: Collection[str] = None
                            ) -> DefaultReturnCode:
        """Remove a registration.

        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        """
        registration_id = affirm(vtypes.ID, registration_id)
        reg = self.get_registration(rs, registration_id)
        if (not self.is_orga(rs, event_id=reg['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=reg['event_id'])

        blockers = self.delete_registration_blockers(rs, registration_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "registration",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            # cascade specified blockers
            if cascade:
                if "registration_parts" in cascade:
                    ret *= self.sql_delete(rs, "event.registration_parts",
                                           blockers["registration_parts"])
                if "registration_tracks" in cascade:
                    ret *= self.sql_delete(rs, "event.registration_tracks",
                                           blockers["registration_tracks"])
                if "course_choices" in cascade:
                    ret *= self.sql_delete(rs, "event.course_choices",
                                           blockers["course_choices"])

                # check if registration is deletable after cascading
                blockers = self.delete_registration_blockers(
                    rs, registration_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "event.registrations", registration_id)
                self.event_log(rs, const.EventLogCodes.registration_deleted,
                               reg['event_id'], persona_id=reg['persona_id'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "registration", "block": blockers.keys()})
        return ret

    def _calculate_single_fee(self, rs: RequestState, reg: CdEDBObject, *,
                              event: CdEDBObject = None, event_id: int = None,
                              is_member: bool = None) -> decimal.Decimal:
        """Helper function to calculate the fee for one registration.

        This is used inside `create_registration` and `set_registration`,
        so we take the full registration and event as input instead of
        retrieving them via id.

        :param is_member: If this is None, retrieve membership status here.
        """
        fee = decimal.Decimal(0)
        rps = const.RegistrationPartStati

        if event is None and event_id is None:
            raise ValueError("No input given.")
        elif event is not None and event_id is not None:
            raise ValueError("Only one input for event allowed.")
        elif event_id is not None:
            event = self.get_event(rs, event_id)
        assert event is not None
        for part_id, rpart in reg['parts'].items():
            part = event['parts'][part_id]
            if rps(rpart['status']).is_involved():
                fee += part['fee']

        for fee_modifier in event['fee_modifiers'].values():
            field = event['fields'][fee_modifier['field_id']]
            status = rps(reg['parts'][fee_modifier['part_id']]['status'])
            if status.is_involved():
                if reg['fields'].get(field['field_name']):
                    fee += fee_modifier['amount']

        if is_member is None:
            is_member = self.core.get_persona(
                rs, reg['persona_id'])['is_member']
        if not is_member:
            fee += event['nonmember_surcharge']

        return fee

    @access("event")
    def calculate_fees(self, rs: RequestState, registration_ids: Collection[int]
                       ) -> Dict[int, decimal.Decimal]:
        """Calculate the total fees for some registrations.

        This should be called once for multiple registrations, as it would be
        somewhat expensive if called per registration.

        All registrations need to belong to the same event.

        The caller must have priviliged acces to that event.
        """
        registration_ids = affirm_set(vtypes.ID, registration_ids)

        with Atomizer(rs):
            associated = self.sql_select(rs, "event.registrations",
                                         ("event_id",), registration_ids)
            if not associated:
                return {}
            events = {e['event_id'] for e in associated}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))

            event_id = unwrap(events)
            regs = self.get_registrations(rs, registration_ids)
            user_id = rs.user.persona_id
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)
                    and {r['persona_id'] for r in regs.values()} != {user_id}):
                raise PrivilegeError(n_("Not privileged."))

            persona_ids = {e['persona_id'] for e in regs.values()}
            personas = self.core.get_personas(rs, persona_ids)

            event = self.get_event(rs, event_id)
            ret: Dict[int, decimal.Decimal] = {}
            for reg_id, reg in regs.items():
                is_member = personas[reg['persona_id']]['is_member']
                ret[reg_id] = self._calculate_single_fee(
                    rs, reg, event=event, is_member=is_member)
        return ret

    class _CalculateFeeProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int
                     ) -> decimal.Decimal: ...
    calculate_fee: _CalculateFeeProtocol = singularize(
        calculate_fees, "registration_ids", "registration_id")

    @access("event")
    def book_fees(self, rs: RequestState, event_id: int, data: Collection[CdEDBObject],
                  ) -> Tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        data = affirm_array(vtypes.FeeBookingEntry, data)

        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        index = 0
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                all_reg_ids = {datum['registration_id'] for datum in data}
                all_regs = self.get_registrations(rs, all_reg_ids)
                if any(reg['event_id'] != event_id for reg in all_regs.values()):
                    raise ValueError(n_("Mismatched registrations,"
                                        " not associated with the event."))
                for index, datum in enumerate(data):
                    reg_id = datum['registration_id']
                    update = {
                        'id': reg_id,
                        'payment': datum['date'],
                        'amount_paid': all_regs[reg_id]['amount_paid']
                                       + datum['amount'],
                    }
                    change_note = "{} am {} gezahlt.".format(
                        money_filter(datum['amount']),
                        date_filter(datum['original_date'], lang="de"))
                    count += self.set_registration(rs, update, change_note)
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None
        except Exception:
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during fee transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index
        return True, count

    @access("event")
    def check_orga_addition_limit(self, rs: RequestState,
                                  event_id: int) -> bool:
        """Implement a rate limiting check for orgas adding persons.

        Since adding somebody as participant or orga to an event gives all
        orgas basically full access to their data, we rate limit this
        operation.

        :returns: True if limit has not been reached.
        """
        event_id = affirm(vtypes.ID, event_id)
        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        if self.is_admin(rs):
            # Admins are exempt
            return True
        query = ("SELECT COUNT(*) AS num FROM event.log"
                 " WHERE event_id = %s AND code = %s "
                 " AND submitted_by != persona_id "
                 " AND ctime >= now() - interval '24 hours'")
        params = (event_id, const.EventLogCodes.registration_created)
        num = unwrap(self.query_one(rs, query, params))
        return num < self.conf["ORGA_ADD_LIMIT"]

    @access("event", "droid_quick_partial_export")
    def get_questionnaire(self, rs: RequestState, event_id: int,
                          kinds: Collection[const.QuestionnaireUsages] = None
                          ) -> CdEDBQuestionnaire:
        """Retrieve the questionnaire rows for a specific event.

        Rows are seperated by kind. Specifying a kinds will get you only rows
        of those kinds, otherwise you get them all.
        """
        event_id = affirm(vtypes.ID, event_id)
        kinds = kinds or []
        affirm_set(const.QuestionnaireUsages, kinds)
        query = "SELECT {fields} FROM event.questionnaire_rows".format(
            fields=", ".join(QUESTIONNAIRE_ROW_FIELDS))
        constraints = ["event_id = %s"]
        params: List[Any] = [event_id]
        if kinds:
            constraints.append("kind = ANY(%s)")
            params.append(kinds)
        query += " WHERE " + " AND ".join(c for c in constraints)
        d = self.query_all(rs, query, params)
        for row in d:
            # noinspection PyArgumentList
            row['kind'] = const.QuestionnaireUsages(row['kind'])
        ret = {
            k: xsorted([e for e in d if e['kind'] == k], key=lambda x: x['pos'])
            for k in kinds or const.QuestionnaireUsages
        }
        return ret

    @access("event")
    def set_questionnaire(self, rs: RequestState, event_id: int,
                          data: Optional[CdEDBQuestionnaire]) -> DefaultReturnCode:
        """Replace current questionnaire rows for a specific event, by kind.

        This superseeds the current questionnaire for all given kinds.
        Kinds that are not present in data, will not be touched.

        To delete all questionnaire rows, you can specify data as None.
        """
        event_id = affirm(vtypes.ID, event_id)
        event = self.get_event(rs, event_id)
        if data is not None:
            current = self.get_questionnaire(rs, event_id)
            current.update(data)
            for v in current.values():
                for e in v:
                    if 'pos' in e:
                        del e['pos']
            # FIXME what is the correct type here?
            data = affirm(vtypes.Questionnaire, current,  # type: ignore[assignment]
                          field_definitions=event['fields'],
                          fee_modifiers=event['fee_modifiers'])
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        with Atomizer(rs):
            ret = 1
            # Allow deletion of enitre questionnaire by specifying None.
            if data is None:
                self.sql_delete(rs, "event.questionnaire_rows", (event_id,),
                                entity_key="event_id")
                return 1
            # Otherwise replace rows for all given kinds.
            for kind, rows in data.items():
                query = ("DELETE FROM event.questionnaire_rows"
                         " WHERE event_id = %s AND kind = %s")
                params = (event_id, kind)
                self.query_exec(rs, query, params)
                for pos, row in enumerate(rows):
                    new_row = copy.deepcopy(row)
                    new_row['pos'] = pos
                    new_row['event_id'] = event_id
                    new_row['kind'] = kind
                    ret *= self.sql_insert(
                        rs, "event.questionnaire_rows", new_row)
            self.event_log(
                rs, const.EventLogCodes.questionnaire_changed, event_id)
        return ret

    @access("event")
    def lock_event(self, rs: RequestState, event_id: int) -> DefaultReturnCode:
        """Lock an event for offline usage."""
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        # An event in the main instance is considered as locked if offline_lock
        # is true, in the offline instance it is the other way around
        update = {
            'id': event_id,
            'offline_lock': not self.conf["CDEDB_OFFLINE_DEPLOYMENT"],
        }
        with Atomizer(rs):
            ret = self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_locked, event_id)
        return ret

    @access("event")
    def export_event(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Export an event for offline usage or after offline usage.

        This provides a more general export functionality which could
        also be used without locking.

        :returns: dict holding all data of the exported event
        """
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Iterable[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        with Atomizer(rs):
            ret: CdEDBObject = {
                'EVENT_SCHEMA_VERSION': EVENT_SCHEMA_VERSION,
                'kind': "full",  # could also be "partial"
                'id': event_id,
                'event.events': list_to_dict(self.sql_select(
                    rs, "event.events", EVENT_FIELDS, (event_id,))),
                'timestamp': now(),
            }
            # Table name; column to scan; fields to extract
            tables: List[Tuple[str, str, Tuple[str, ...]]] = [
                ('event.event_parts', "event_id", EVENT_PART_FIELDS),
                ('event.course_tracks', "part_id", COURSE_TRACK_FIELDS),
                ('event.courses', "event_id", COURSE_FIELDS),
                ('event.course_segments', "track_id", (
                    'id', 'course_id', 'track_id', 'is_active')),
                ('event.orgas', "event_id", (
                    'id', 'persona_id', 'event_id',)),
                ('event.field_definitions', "event_id",
                 FIELD_DEFINITION_FIELDS),
                ('event.fee_modifiers', "part_id", FEE_MODIFIER_FIELDS),
                ('event.lodgement_groups', "event_id", LODGEMENT_GROUP_FIELDS),
                ('event.lodgements', "event_id", LODGEMENT_FIELDS),
                ('event.registrations', "event_id", REGISTRATION_FIELDS),
                ('event.registration_parts', "part_id",
                 REGISTRATION_PART_FIELDS),
                ('event.registration_tracks', "track_id",
                 REGISTRATION_TRACK_FIELDS),
                ('event.course_choices', "track_id", (
                    'id', 'registration_id', 'track_id', 'course_id', 'rank',)),
                ('event.questionnaire_rows', "event_id", (
                    'id', 'event_id', 'field_id', 'pos', 'title', 'info',
                    'input_size', 'readonly', 'kind')),
                ('event.log', "event_id", (
                    'id', 'ctime', 'code', 'submitted_by', 'event_id',
                    'persona_id', 'change_note')),
            ]
            personas = set()
            for table, id_name, columns in tables:
                if id_name == "event_id":
                    id_range = {event_id}
                elif id_name == "part_id":
                    id_range = set(ret['event.event_parts'])
                elif id_name == "track_id":
                    id_range = set(ret['event.course_tracks'])
                else:
                    raise RuntimeError("Impossible.")
                if 'id' not in columns:
                    columns += ('id',)
                ret[table] = list_to_dict(self.sql_select(
                    rs, table, columns, id_range, entity_key=id_name))
                # Note the personas present to export them further on
                for e in ret[table].values():
                    if e.get('persona_id'):
                        personas.add(e['persona_id'])
                    if e.get('submitted_by'):  # for log entries
                        personas.add(e['submitted_by'])
            ret['core.personas'] = list_to_dict(self.sql_select(
                rs, "core.personas", PERSONA_EVENT_FIELDS, personas))
        return ret

    @access("event", "droid_quick_partial_export")
    def partial_export_event(self, rs: RequestState,
                             event_id: int) -> CdEDBObject:
        """Export an event for third-party applications.

        This provides a consumer-friendly package of event data which can
        later on be reintegrated with the partial import facility.
        """
        event_id = affirm(vtypes.ID, event_id)
        access_ok = (
            (self.conf["CDEDB_OFFLINE_DEPLOYMENT"]  # this grants access for
             and "droid_quick_partial_export" in rs.user.roles)  # the droid
            or self.is_orga(rs, event_id=event_id)
            or self.is_admin(rs))
        if not access_ok:
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist: Collection[CdEDBObject]) -> CdEDBObjectMap:
            return {e['id']: e for e in alist}

        # First gather all the data and give up the database lock afterwards.
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            courses = list_to_dict(self.sql_select(
                rs, 'event.courses', COURSE_FIELDS, (event_id,),
                entity_key='event_id'))
            course_segments = self.sql_select(
                rs, 'event.course_segments',
                ('course_id', 'track_id', 'is_active'), courses.keys(),
                entity_key='course_id')
            lodgement_groups = list_to_dict(self.sql_select(
                rs, 'event.lodgement_groups', LODGEMENT_GROUP_FIELDS,
                (event_id,), entity_key='event_id'))
            lodgements = list_to_dict(self.sql_select(
                rs, 'event.lodgements', LODGEMENT_FIELDS, (event_id,),
                entity_key='event_id'))
            registrations = list_to_dict(self.sql_select(
                rs, 'event.registrations', REGISTRATION_FIELDS, (event_id,),
                entity_key='event_id'))
            registration_parts = self.sql_select(
                rs, 'event.registration_parts',
                REGISTRATION_PART_FIELDS, registrations.keys(),
                entity_key='registration_id')
            registration_tracks = self.sql_select(
                rs, 'event.registration_tracks',
                REGISTRATION_TRACK_FIELDS, registrations.keys(),
                entity_key='registration_id')
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"),
                registrations.keys(), entity_key="registration_id")
            questionnaire = self.get_questionnaire(rs, event_id)
            persona_ids = tuple(reg['persona_id']
                                for reg in registrations.values())
            personas = self.core.get_event_users(rs, persona_ids, event_id)

        # Now process all the data.
        # basics
        ret: CdEDBObject = {
            'EVENT_SCHEMA_VERSION': EVENT_SCHEMA_VERSION,
            'kind': "partial",  # could also be "full"
            'id': event_id,
            'timestamp': now(),
        }
        # courses
        lookup: Dict[int, Dict[int, bool]] = collections.defaultdict(dict)
        for e in course_segments:
            lookup[e['course_id']][e['track_id']] = e['is_active']
        for course_id, course in courses.items():
            del course['id']
            del course['event_id']
            course['segments'] = lookup[course_id]
            course['fields'] = cast_fields(
                course['fields'], event['fields'])
        ret['courses'] = courses
        # lodgement groups
        for lodgement_group in lodgement_groups.values():
            del lodgement_group['id']
            del lodgement_group['event_id']
        ret['lodgement_groups'] = lodgement_groups
        # lodgements
        for lodgement in lodgements.values():
            del lodgement['id']
            del lodgement['event_id']
            lodgement['fields'] = cast_fields(lodgement['fields'],
                                              event['fields'])
        ret['lodgements'] = lodgements
        # registrations
        backup_registrations = copy.deepcopy(registrations)
        part_lookup: Dict[int, Dict[int, CdEDBObject]]
        part_lookup = collections.defaultdict(dict)
        for e in registration_parts:
            part_lookup[e['registration_id']][e['part_id']] = e
        track_lookup: Dict[int, Dict[int, CdEDBObject]]
        track_lookup = collections.defaultdict(dict)
        for e in registration_tracks:
            track_lookup[e['registration_id']][e['track_id']] = e
        for registration_id, registration in registrations.items():
            del registration['id']
            del registration['event_id']
            del registration['persona_id']
            del registration['real_persona_id']
            parts = part_lookup[registration_id]
            for part in parts.values():
                del part['registration_id']
                del part['part_id']
            registration['parts'] = parts
            tracks = track_lookup[registration_id]
            for track_id, track in tracks.items():
                tmp = {e['course_id']: e['rank'] for e in choices
                       if (e['registration_id'] == track['registration_id']
                           and e['track_id'] == track_id)}
                track['choices'] = xsorted(tmp.keys(), key=tmp.get)
                del track['registration_id']
                del track['track_id']
            registration['tracks'] = tracks
            registration['fields'] = cast_fields(registration['fields'],
                                                 event['fields'])
        ret['registrations'] = registrations
        # now we add additional information that is only auxillary and
        # does not correspond to changeable entries
        #
        # event
        export_event = copy.deepcopy(event)
        del export_event['id']
        del export_event['begin']
        del export_event['end']
        del export_event['is_open']
        del export_event['orgas']
        del export_event['tracks']
        del export_event['fee_modifiers']
        for part in export_event['parts'].values():
            del part['id']
            del part['event_id']
            for f in ('waitlist_field',):
                if part[f]:
                    part[f] = event['fields'][part[f]]['field_name']
            for track in part['tracks'].values():
                del track['id']
                del track['part_id']
            part['fee_modifiers'] = {fm['modifier_name']: fm
                                     for fm in part['fee_modifiers'].values()}
            for fm in part['fee_modifiers'].values():
                del fm['id']
                del fm['modifier_name']
                del fm['part_id']
                fm['field_name'] = event['fields'][fm['field_id']]['field_name']
                del fm['field_id']
        for f in ('lodge_field', 'camping_mat_field', 'course_room_field'):
            if export_event[f]:
                export_event[f] = event['fields'][event[f]]['field_name']
        new_fields = {
            field['field_name']: field
            for field in export_event['fields'].values()
        }
        for field in new_fields.values():
            del field['field_name']
            del field['event_id']
            del field['id']
        export_event['fields'] = new_fields
        new_questionnaire = {
            str(usage): rows
            for usage, rows in questionnaire.items()
        }
        for usage, rows in new_questionnaire.items():
            for q in rows:
                if q['field_id']:
                    q['field_name'] = event['fields'][q['field_id']]['field_name']
                else:
                    q['field_name'] = None
                del q['pos']
                del q['kind']
                del q['field_id']
        export_event['questionnaire'] = new_questionnaire
        ret['event'] = export_event
        # personas
        for reg_id, registration in ret['registrations'].items():
            persona = personas[backup_registrations[reg_id]['persona_id']]
            persona['is_orga'] = persona['id'] in event['orgas']
            for attr in ('is_active', 'is_meta_admin', 'is_archived',
                         'is_assembly_admin', 'is_assembly_realm',
                         'is_cde_admin', 'is_finance_admin', 'is_cde_realm',
                         'is_core_admin', 'is_event_admin',
                         'is_event_realm', 'is_ml_admin', 'is_ml_realm',
                         'is_searchable', 'is_cdelokal_admin', 'is_purged'):
                del persona[attr]
            registration['persona'] = persona
        return ret

    @access("event")
    def questionnaire_import(self, rs: RequestState, event_id: int,
                             fields: CdEDBObjectMap, questionnaire: CdEDBQuestionnaire,
                             ) -> DefaultReturnCode:
        """Special import for custom datafields and questionnaire rows."""
        event_id = affirm(vtypes.ID, event_id)
        # validation of input is delegated to the setters, because it is rather
        # involved and dependent on each other.
        # Do not allow special use of `set_questionnaire` for deleting everything.
        if questionnaire is None:
            raise ValueError(n_(
                "Cannot use questionnaire import to delete questionnaire."))
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        with Atomizer(rs):
            ret = self.set_event(rs, {'id': event_id, 'fields': fields})
            ret *= self.set_questionnaire(rs, event_id, questionnaire)
        return ret
