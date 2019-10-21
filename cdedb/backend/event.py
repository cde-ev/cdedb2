#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy
import hashlib

from cdedb.backend.common import (
    access, affirm_validation as affirm, AbstractBackend, Silencer,
    affirm_set_validation as affirm_set, singularize, PYTHON_TO_SQL_MAP,
    cast_fields, internal_access)
from cdedb.backend.cde import CdEBackend
from cdedb.common import (
    n_, glue, PrivilegeError, EVENT_PART_FIELDS, EVENT_FIELDS, COURSE_FIELDS,
    REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS, LODGEMENT_FIELDS,
    COURSE_SEGMENT_FIELDS, unwrap, now, ProxyShim, PERSONA_EVENT_FIELDS,
    CourseFilterPositions, FIELD_DEFINITION_FIELDS, COURSE_TRACK_FIELDS,
    REGISTRATION_TRACK_FIELDS, PsycoJson, implying_realms, json_serialize,
    PartialImportError, CDEDB_EXPORT_EVENT_VERSION)
from cdedb.database.connection import Atomizer
from cdedb.query import QueryOperators
import cdedb.database.constants as const
from cdedb.validation import parse_date, parse_datetime


# This is used for generating the table for general queries for
# registrations. We moved this rather huge blob here, so it doesn't
# disfigure the query code.
#
# The end result may look something like the following::
"""
event.registrations AS reg
JOIN core.personas AS persona ON reg.persona_id = persona.id
LEFT OUTER JOIN (SELECT registration_id, status, lodgement_id, is_reserve
                 FROM event.registration_parts WHERE part_id = 1)
    AS part1 ON reg.id = part1.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'contamination\')::varchar
                    AS "xfield_contamination",
                 id, moniker, notes
                 FROM event.lodgements WHERE event_id=1)
    AS lodgement1 ON part1.lodgement_id = lodgement1.id
LEFT OUTER JOIN (SELECT registration_id, status, lodgement_id, is_reserve
                 FROM event.registration_parts WHERE part_id = 2)
    AS part2 ON reg.id = part2.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'contamination\')::varchar
                     AS "xfield_contamination",
                 id, moniker, notes
                 FROM event.lodgements WHERE event_id=1)
    AS lodgement2 ON part2.lodgement_id = lodgement2.id
LEFT OUTER JOIN (SELECT registration_id, status, lodgement_id, is_reserve
                 FROM event.registration_parts WHERE part_id = 3)
    AS part3 ON reg.id = part3.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'contamination\')::varchar
                     AS "xfield_contamination",
                 id, moniker, notes
                 FROM event.lodgements WHERE event_id=1)
    AS lodgement3 ON part3.lodgement_id = lodgement3.id
LEFT OUTER JOIN (SELECT registration_id, course_id, course_instructor,
                 (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
                  AND course_id = course_instructor) AS is_course_instructor
                 FROM event.registration_tracks WHERE track_id = 1)
    AS track1 ON reg.id = track1.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course1 ON track1.course_id = course1.id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course_instructor1 ON track1.course_instructor = course_instructor1.id
LEFT OUTER JOIN (SELECT registration_id, course_id, course_instructor,
                 (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
                  AND course_id = course_instructor) AS is_course_instructor
                 FROM event.registration_tracks WHERE track_id = 2)
    AS track2 ON reg.id = track2.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course2 ON track2.course_id = course2.id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course_instructor2 ON track2.course_instructor = course_instructor2.id
LEFT OUTER JOIN (SELECT registration_id, course_id, course_instructor,
                 (NOT(course_id IS NULL AND course_instructor IS NOT NULL)
                  AND course_id = course_instructor) AS is_course_instructor
                 FROM event.registration_tracks WHERE track_id = 3)
    AS track3 ON reg.id = track3.registration_id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course3 ON track3.course_id = course3.id
LEFT OUTER JOIN (SELECT (fields->>\'room\')::varchar AS "xfield_room",
                 id, nr, title, shortname, notes
                 FROM event.courses WHERE event_id=1)
    AS course_instructor3 ON track3.course_instructor = course_instructor3.id
LEFT OUTER JOIN (SELECT persona_id, MAX(ctime) AS creation_time
                 FROM event.log WHERE event_id = 1 AND code = 50
                 GROUP BY persona_id)
    AS ctime ON ctime.persona_id = reg.persona_id
LEFT OUTER JOIN (SELECT persona_id, MAX(ctime) AS modification_time
                 FROM event.log WHERE event_id = 1 AND code = 51
                 GROUP BY persona_id)
    AS mtime ON mtime.persona_id = reg.persona_id
LEFT OUTER JOIN (SELECT (fields->>\'brings_balls\')::boolean
                    AS "xfield_brings_balls",
                 (fields->>\'transportation\')::varchar
                    AS "xfield_transportation",
                 (fields->>\'lodge\')::varchar AS "xfield_lodge",
                 (fields->>\'may_reserve\')::boolean AS "xfield_may_reserve",
                 id AS reg_id
                 FROM event.registrations WHERE event_id=1)
    AS reg_fields ON reg.id = reg_fields.reg_id
"""

_REGISTRATION_VIEW_TEMPLATE = glue(
    "event.registrations AS reg",
    "JOIN core.personas AS persona ON reg.persona_id = persona.id",
    "{part_tables}",  # per part details will be filled in here
    "{track_tables}",  # per track details will be filled in here
    "{creation_date}",
    "{modification_date}",
    "LEFT OUTER JOIN (SELECT {reg_columns} FROM",
    "event.registrations WHERE event_id={event_id}) AS reg_fields",
    "ON reg.id = reg_fields.reg_id",
)

class EventBackend(AbstractBackend):
    """Take note of the fact that some personas are orgas and thus have
    additional actions available."""
    realm = "event"

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cde = ProxyShim(CdEBackend(configpath), internal=True)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def is_orga(self, rs, *, event_id=None, course_id=None):
        """Check for orga privileges as specified in the event.orgas table.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int or None
        :type course_id: int or None
        :rtype: bool
        """
        if event_id is None and course_id is None:
            raise ValueError(n_("No input specified."))
        if event_id is not None and course_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        if course_id is not None:
            event_id = unwrap(self.sql_select_one(rs, "event.courses",
                                                  ("event_id",), course_id))
        return event_id in rs.user.orga

    @access("event")
    def is_offline_locked(self, rs, *, event_id=None, course_id=None):
        """Helper to determine if an event or course is locked for offline
        usage.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int or None
        :type course_id: int or None
        :rtype: bool
        """
        if event_id is not None and course_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        elif event_id is not None:
            anid = affirm("id", event_id)
            query = "SELECT offline_lock FROM event.events WHERE id = %s"
        elif course_id is not None:
            anid = affirm("id", course_id)
            query = glue(
                "SELECT offline_lock FROM event.events AS e",
                "LEFT OUTER JOIN event.courses AS c ON c.event_id = e.id",
                "WHERE c.id = %s")
        else:  # event_id is None and course_id is None:
            raise ValueError(n_("No input specified."))

        data = self.query_one(rs, query, (anid,))
        return data['offline_lock']

    def assert_offline_lock(self, rs, *, event_id=None, course_id=None):
        """Helper to check locking state of an event or course.

        This raises an exception in case of the wrong locking state. Exactly
        one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int or None
        :type course_id: int or None
        """
        # the following does the argument checking
        is_locked = self.is_offline_locked(rs, event_id=event_id,
                                           course_id=course_id)
        if is_locked != self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError(n_("Event offline lock error."))

    @access("persona")
    @singularize("orga_info")
    def orga_infos(self, rs, ids):
        """List events organized by specific personas.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "event.orgas", ("persona_id", "event_id"),
                               ids, entity_key="persona_id")
        ret = {}
        for anid in ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    def event_log(self, rs, code, event_id, persona_id=None,
                  additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.EventLogCodes`.
        :type event_id: int or None
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        if rs.is_quiet:
            return 0
        data = {
            "code": code,
            "event_id": event_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,
        }
        return self.sql_insert(rs, "event.log", data)

    @access("event")
    def retrieve_log(self, rs, codes=None, event_id=None, start=None,
                     stop=None, persona_id=None, submitted_by=None,
                     additional_info=None, time_start=None, time_stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type event_id: int or None
        :type start: int or None
        :type stop: int or None
        :type persona_id: int or None
        :type submitted_by: int or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :rtype: [{str: object}]
        """
        event_id = affirm("id_or_None", event_id)
        if (not (event_id and self.is_orga(rs, event_id=event_id))
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        return self.generic_retrieve_log(
            rs, "enum_eventlogcodes", "event", "event.log", codes,
            entity_id=event_id, start=start, stop=stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)

    @access("anonymous")
    def list_db_events(self, rs, visible=None, current=None, archived=None):
        """List all events organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type visible: bool or None
        :type current: bool or None
        :type archived: bool or None
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        subquery = glue(
            "SELECT e.id, e.registration_start, e.title, e.is_visible,",
            "e.is_archived, MAX(p.part_end) AS event_end",
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
            else:
                constraints.append("e.event_end <= now()")
        if archived is not None:
            constraints.append("is_archived = %s")
            params.append(archived)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)

        data = self.query_all(rs, query, params)
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def list_db_courses(self, rs, event_id):
        """List all courses organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: {int: str}
        :returns: Mapping of course ids to titles.
        """
        event_id = affirm("id", event_id)
        data = self.sql_select(rs, "event.courses", ("id", "title"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

    @access("event")
    def submit_general_query(self, rs, query, event_id=None):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :type event_id: int or None
        :param event_id: For registration queries, specify the event.
        :rtype: [{str: object}]
        """
        query = affirm("query", query)
        view = None
        if query.scope == "qview_registration":
            event_id = affirm("id", event_id)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            # Fix for custom fields with uppercase letters so they do not
            # get misinterpreted by postgres
            query.fields_of_interest = [
                ",".join(
                    ".".join(atom if atom.islower() else '"{}"'.format(atom)
                             for atom in moniker.split("."))
                    for moniker in column.split(","))
                for column in query.fields_of_interest]
            query.constraints = [
                (",".join(
                    ".".join(atom if atom.islower() else '"{}"'.format(atom)
                             for atom in moniker.split("."))
                    for moniker in column.split(",")),
                 operator, value)
                for column, operator, value in query.constraints
            ]
            query.order = [
                (".".join(atom if atom.islower() else '"{}"'.format(atom)
                          for atom in entry.split(".")),
                 ascending)
                for entry, ascending in query.order]
            for field, _, _ in query.constraints:
                if '"' in field:
                    query.spec[field] = query.spec[field.replace('"', '')]
                    del query.spec[field.replace('"', '')]

            lodgement_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.lodgement
            }
            lodge_columns_gen = lambda part_id: ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in lodgement_fields.items()]
                + [col for col in ("id", "moniker", "notes")]
            )
            part_table_template = glue(
                # first the per part table
                "LEFT OUTER JOIN (SELECT registration_id, status,",
                "lodgement_id, is_reserve",
                "FROM event.registration_parts WHERE part_id = {part_id})",
                "AS part{part_id} ON reg.id = part{part_id}.registration_id",
                # second the associated lodgement fields
                "LEFT OUTER JOIN (SELECT {lodge_columns} FROM",
                "event.lodgements WHERE event_id={event_id})",
                "AS lodgement{part_id}",
                "ON part{part_id}.lodgement_id",
                "= lodgement{part_id}.id",
            )
            course_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.course
            }
            course_columns_gen = lambda track_id, identifier: ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in course_fields.items()]
                + [col for col in ("id", "nr", "title", "shortname", "notes")]
            )
            track_table_template = glue(
                # first the per track table
                "LEFT OUTER JOIN (SELECT registration_id, course_id,",
                "course_instructor, ",
                "(NOT(course_id IS NULL AND course_instructor IS NOT NULL)",
                "AND course_id = course_instructor)",
                "AS is_course_instructor",
                "FROM event.registration_tracks WHERE track_id = {track_id})",
                "AS track{track_id} ON",
                "reg.id = track{track_id}.registration_id",
                # second the associated course fields
                "LEFT OUTER JOIN (SELECT {course_columns} FROM",
                "event.courses WHERE event_id={event_id})",
                "AS course{track_id}",
                "ON track{track_id}.course_id",
                "= course{track_id}.id",
                # third the fields for the instructed course
                "LEFT OUTER JOIN (SELECT {course_instructor_columns} FROM",
                "event.courses WHERE event_id={event_id})",
                "AS course_instructor{track_id}",
                "ON track{track_id}.course_instructor",
                "= course_instructor{track_id}.id",
            )
            creation_date = glue(
                "LEFT OUTER JOIN",
                "(SELECT persona_id, MAX(ctime) AS creation_time",
                "FROM event.log",
                "WHERE event_id = {event_id} AND code = {reg_create_code}",
                "GROUP BY persona_id)",
                "AS ctime ON ctime.persona_id = reg.persona_id").format(
                event_id=event_id,
                reg_create_code=const.EventLogCodes.registration_created)
            modification_date = glue(
                "LEFT OUTER JOIN",
                "(SELECT persona_id, MAX(ctime) AS modification_time",
                "FROM event.log",
                "WHERE event_id = {event_id} AND code = {reg_mod_code}",
                "GROUP BY persona_id)",
                "AS mtime ON mtime.persona_id = reg.persona_id").format(
                event_id=event_id,
                reg_mod_code=const.EventLogCodes.registration_changed)
            reg_fields = {
                e['field_name']:
                    PYTHON_TO_SQL_MAP[const.FieldDatatypes(e['kind']).name]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.registration
            }
            reg_columns = ", ".join(
                ['''(fields->>'{0}')::{1} AS "xfield_{0}"'''.format(
                    name, kind)
                 for name, kind in reg_fields.items()]
                + ["id AS reg_id"])
            part_table_gen = lambda part_id: part_table_template.format(
                part_id=part_id,
                lodge_columns=lodge_columns_gen(part_id),
                event_id=event_id)
            track_table_gen = lambda track_id: track_table_template.format(
                course_columns=course_columns_gen(track_id, "course"),
                course_instructor_columns=course_columns_gen(
                    track_id, "course_instructor"),
                track_id=track_id, event_id=event_id)
            view = _REGISTRATION_VIEW_TEMPLATE.format(
                event_id=event_id,
                part_tables=" ".join(part_table_gen(part_id)
                                     for part_id in event['parts']),
                track_tables=" ".join(track_table_gen(track_id)
                                      for part in event['parts'].values()
                                      for track_id in part['tracks']),
                creation_date=creation_date,
                modification_date=modification_date,
                reg_columns=reg_columns,
            )
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope == "qview_quick_registration":
            event_id = affirm("id", event_id)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope == "qview_event_user":
            if not self.is_admin(rs):
                raise PrivilegeError(n_("Admin only."))
            # Include only un-archived event-users
            query.constraints.append(("is_event_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_event_realm"] = "bool"
            query.spec["is_archived"] = "bool"
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('event'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = "bool"
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query, view=view)

    @access("anonymous")
    @singularize("get_event")
    def get_events(self, rs, ids):
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}

        """
        ids = affirm_set("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.events", EVENT_FIELDS, ids)
            ret = {e['id']: e for e in data}
            data = self.sql_select(rs, "event.event_parts", EVENT_PART_FIELDS,
                                   ids, entity_key="event_id")
            all_parts = tuple(e['id'] for e in data)
            for anid in ids:
                parts = {d['id']: d for d in data if d['event_id'] == anid}
                assert ('parts' not in ret[anid])
                ret[anid]['parts'] = parts
            data = self.sql_select(rs, "event.course_tracks",
                                   COURSE_TRACK_FIELDS,
                                   all_parts, entity_key="part_id")
            for anid in ids:
                for part_id in ret[anid]['parts']:
                    tracks = {d['id']: d for d in data
                              if d['part_id'] == part_id}
                    assert ('tracks' not in ret[anid]['parts'][part_id])
                    ret[anid]['parts'][part_id]['tracks'] = tracks
                ret[anid]['tracks'] = {d['id']: d for d in data
                                       if d['part_id'] in ret[anid]['parts']}
            data = self.sql_select(
                rs, "event.orgas", ("persona_id", "event_id"), ids,
                entity_key="event_id")
            for anid in ids:
                orgas = {d['persona_id'] for d in data if d['event_id'] == anid}
                assert ('orgas' not in ret[anid])
                ret[anid]['orgas'] = orgas
            data = self.sql_select(
                rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
                ids, entity_key="event_id")
            for anid in ids:
                fields = {d['id']: d for d in data if d['event_id'] == anid}
                assert ('fields' not in ret[anid])
                ret[anid]['fields'] = fields
        for anid in ids:
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

    def _get_event_fields(self, rs, event_id):
        """
        Helper function to retrieve the custom field definitions of an event.
        This is required by multiple backend functions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :return: A dict mapping each event id to the dict of its fields
        :rtype: {int: {str: object}}
        """
        data = self.sql_select(
            rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
            [event_id], entity_key="event_id")
        return {d['id']: d for d in data}

    def _delete_course_track_blockers(self, rs, track_id):
        """Determine what keeps a course track from being deleted.

        Possible blockers:

        * course_segments: Courses that are offered in this track.
        * registration_tracks: Registration information for this track.
            This includes course_assignment and possible course instructors.
        * course_choices: Course choices for this track.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type track_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        track_id = affirm("id", track_id)
        blockers = {}

        course_segments = self.sql_select(
            rs, "event.course_segments", ("id",), (track_id,),
            entity_key="track_id")
        if course_segments:
            blockers["course_segments"] = [e["id"] for e in course_segments]

        reg_tracks = self.sql_select(
            rs, "event.registration_tracks", ("id",), (track_id,),
            entity_key="track_id")
        if reg_tracks:
            blockers["registration_tracks"] = [e["id"] for e in reg_tracks]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (track_id,),
            entity_key="track_id")
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        return blockers

    def _delete_course_track(self, rs, track_id, cascade=None):
        """Remove course track.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type track_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
        """
        track_id = affirm("id", track_id)
        blockers = self._delete_course_track_blockers(rs, track_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "course track",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "course_segments" in cascade:
                    ret *= self.sql_delete(rs, "event.course_segments",
                                           blockers["course_segments"])
                if "registration_tracks" in cascade:
                    ret *= self.sql_delete(rs, "event.registration_tracks",
                                           blockers["registration_tracks"])
                if "course_choices" in cascade:
                    ret *= self.sql_delete(rs, "event.course_choices",
                                           blockers["course_choices"])

                blockers = self._delete_course_track_blockers(rs, track_id)

            if not blockers:
                track = unwrap(self.sql_select(rs, "event.course_tracks",
                                               ("part_id", "title",),
                                               (track_id,)))
                part = unwrap(self.sql_select(rs, "event.event_parts",
                                              ("event_id",),
                                              (track["part_id"],)))
                ret *= self.sql_delete_one(
                    rs, "event.course_tracks", track_id)
                self.event_log(rs, const.EventLogCodes.track_removed,
                               event_id=part["event_id"],
                               additional_info=track["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "course track", "block": blockers.keys()})
        return ret

    def _set_tracks(self, rs, event_id, part_id, data):
        """Helper for handling of course tracks.

        This is basically uninlined code from ``set_event()``.

        :note: This has to be called inside an atomized context.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type part_id: int
        :type data: {int: {str: object} or None}
        :rtype: int
        :returns: default return code
        """
        ret = 1
        if not data:
            return ret
        # implicit Atomizer by caller
        current = self.sql_select(
            rs, "event.course_tracks", COURSE_TRACK_FIELDS, (part_id,),
            entity_key="part_id")
        current = {e['id']: e for e in current}
        existing = set(current)
        if not (existing >= {x for x in data if x > 0}):
            raise ValueError(n_("Non-existing tracks specified."))
        new = {x for x in data if x < 0}
        updated = {x for x in data
                   if x > 0 and data[x] is not None}
        deleted = {x for x in data
                   if x > 0 and data[x] is None}
        # new
        for x in reversed(sorted(new)):
            new_track = {
                "part_id": part_id,
                **data[x]
            }
            new_track_id = self.sql_insert(rs, "event.course_tracks", new_track)
            ret *= new_track_id
            self.event_log(
                rs, const.EventLogCodes.track_added, event_id,
                additional_info=data[x]['title'])
            reg_ids = self.list_registrations(rs, event_id)
            for reg_id in reg_ids:
                reg_track = {
                    'registration_id': reg_id,
                    'track_id': new_track_id,
                    'course_id': None,
                    'course_instructor': None,
                }
                ret *= self.sql_insert(
                    rs, "event.registration_tracks", reg_track)
        # updated
        for x in updated:
            if current[x] != data[x]:
                update = {
                    'id': x,
                    **data[x]
                }
                ret *= self.sql_update(rs, "event.course_tracks", update)
                self.event_log(
                    rs, const.EventLogCodes.track_updated, event_id,
                    additional_info=data[x]['title'])

        # deleted
        if deleted:
            cascade = ("course_segments", "registration_tracks",
                       "course_choices")
            for track_id in deleted:
                self._delete_course_track(rs, track_id, cascade=cascade)
        return ret

    def _delete_field_values(self, rs, field_data):
        """
        Helper function for ``set_event()`` to clean up all the JSON data, when
        removing a field definition.

        :param field_data: The data of the field definition to be deleted
        :type field_data: dict
        """
        if field_data['association'] == const.FieldAssociations.registration:
            table = 'event.registrations'
        elif field_data['association'] == const.FieldAssociations.course:
            table = 'event.courses'
        elif field_data['association'] == const.FieldAssociations.lodgement:
            table = 'event.lodgements'
        else:
            raise RuntimeError(n_("This should not happen."))

        query = glue("UPDATE {table}",
                     "SET fields = fields - %s",
                     "WHERE event_id = %s").format(table=table)
        self.query_exec(rs, query, (field_data['field_name'],
                                    field_data['event_id']))

    def _cast_field_values(self, rs, field_data, new_kind):
        """
        Helper function for ``set_event()`` to cast the existing JSON data to
        a new datatype (or set it to None, if casting fails), when a field
        defintion is updated with a new datatype.

        :param field_data: The data of the field definition to be updated
        :type field_data: dict
        :param new_kind: The new kind/datatype of the field.
        :type new_kind: const.FieldDatatypes
        """
        if field_data['association'] == const.FieldAssociations.registration:
            table = 'event.registrations'
        elif field_data['association'] == const.FieldAssociations.course:
            table = 'event.courses'
        elif field_data['association'] == const.FieldAssociations.lodgement:
            table = 'event.lodgements'
        else:
            raise RuntimeError(n_("This should not happen."))

        casters = {
            const.FieldDatatypes.int: int,
            const.FieldDatatypes.str: str,
            const.FieldDatatypes.float: float,
            const.FieldDatatypes.date: parse_date,
            const.FieldDatatypes.datetime: parse_datetime,
            const.FieldDatatypes.bool: bool,
        }

        data = self.sql_select(rs, table, ("id", "fields",),
                               (field_data['event_id'],), entity_key='event_id')
        for entry in data:
            fdata = entry['fields']
            value = fdata.get(field_data['field_name'], None)
            if value is None:
                continue
            try:
                new_value = casters[new_kind](value)
            except (ValueError, TypeError):
                new_value = None
            fdata[field_data['field_name']] = new_value
            new = {
                'id': entry['id'],
                'fields': PsycoJson(fdata),
            }
            self.sql_update(rs, table, new)

    @internal_access("event")
    def set_event_archived(self, rs, data):
        """Wrapper around ``set_event()`` for archiving an event.
        
        This exists to emit the correct log message. It delegates
        everything else (like validation) to the wrapped method.
        """
        with Atomizer(rs):
            with Silencer(rs):
                self.set_event(rs, data)
            self.event_log(rs, const.EventLogCodes.event_archived,
                           data['id'])
        
    @access("event")
    def set_event(self, rs, data):
        """Update some keys of an event organized via DB.

        The syntax for updating the associated data on orgas, parts and
        fields is as follows:

        * If the key 'orgas' is present you have to pass the complete set
          of orga IDs, which will superseed the current list of orgas.
        * If the keys 'parts' or 'fields' are present, the associated dict
          mapping the part or field ids to the respective data sets can
          contain an arbitrary number of entities, absent entities are not
          modified.

          Any valid entity id that is present has to map to a (partial or
          complete) data set or ``None``. In the first case the entity is
          updated, in the second case it is deleted. Deletion depends on
          the entity being nowhere referenced, otherwise an error is
          raised.

          Any invalid entity id (that is negative integer) has to map to a
          complete data set which will be used to create a new entity.

          The same logic applies to the 'tracks' dicts inside the
          'parts'. Deletion of parts implicitly deletes the dependent
          tracks.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code

        """
        data = affirm("event", data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])
        ret = 1
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            if len(edata) > 1:
                indirect_fields = filter(
                    lambda x: x,
                    [edata.get('lodge_field'), edata.get('reserve_field'),
                     edata.get('course_room_field')])
                if indirect_fields:
                    indirect_data = self.sql_select(
                        rs, "event.field_definitions",
                        ("id", "event_id", "kind", "association"),
                        indirect_fields)
                    correct_assoc = const.FieldAssociations.registration
                    correct_datatype = const.FieldDatatypes.str
                    if edata.get('lodge_field'):
                        lodge_data = unwrap(
                            [x for x in indirect_data
                             if x['id'] == edata['lodge_field']])
                        if (lodge_data['event_id'] != data['id']
                                or lodge_data['kind'] != correct_datatype
                                or lodge_data['association'] != correct_assoc):
                            raise ValueError(n_("Unfit field for %(field)s"),
                                             {'field': 'lodge_field'})
                    correct_datatype = const.FieldDatatypes.bool
                    if edata.get('reserve_field'):
                        reserve_data = unwrap(
                            [x for x in indirect_data
                             if x['id'] == edata['reserve_field']])
                        if (reserve_data['event_id'] != data['id']
                                or reserve_data['kind'] != correct_datatype
                                or reserve_data[
                                    'association'] != correct_assoc):
                            raise ValueError(n_("Unfit field for %(field)s"),
                                             {'field': 'reserve_field'})
                    correct_assoc = const.FieldAssociations.course
                    # TODO make this include lodgement datatype per Issue #71
                    correct_datatypes = {const.FieldDatatypes.str}
                    if edata.get('course_room_field'):
                        course_room_data = unwrap(
                            [x for x in indirect_data
                             if x['id'] == edata['course_room_field']])
                        if (course_room_data['event_id'] != data['id']
                                or course_room_data[
                                    'kind'] not in correct_datatypes
                                or course_room_data[
                                    'association'] != correct_assoc):
                            raise ValueError(n_("Unfit field for %(field)s"),
                                             {'field': 'course_room_field'})
                ret *= self.sql_update(rs, "event.events", edata)
                self.event_log(rs, const.EventLogCodes.event_changed,
                               data['id'])
            if 'orgas' in data:
                if not self.is_admin(rs):
                    raise PrivilegeError(n_("Not privileged."))
                current = self.sql_select(rs, "event.orgas", ("persona_id",),
                                          (data['id'],), entity_key="event_id")
                existing = {unwrap(e) for e in current}
                new = data['orgas'] - existing
                deleted = existing - data['orgas']
                if new:
                    for anid in new:
                        new_orga = {
                            'persona_id': anid,
                            'event_id': data['id'],
                        }
                        ret *= self.sql_insert(rs, "event.orgas", new_orga)
                        self.event_log(rs, const.EventLogCodes.orga_added,
                                       data['id'], persona_id=anid)
                if deleted:
                    query = glue("DELETE FROM event.orgas",
                                 "WHERE persona_id = ANY(%s) AND event_id = %s")
                    ret *= self.query_exec(rs, query, (deleted, data['id']))
                    for anid in deleted:
                        self.event_log(rs, const.EventLogCodes.orga_removed,
                                       data['id'], persona_id=anid)
            if 'parts' in data:
                parts = data['parts']
                has_registrations = self.has_registrations(rs, data['id'])
                current = self.sql_select(rs, "event.event_parts", ("id",),
                                          (data['id'],), entity_key="event_id")
                existing = {unwrap(e) for e in current}
                if not (existing >= {x for x in parts if x > 0}):
                    raise ValueError(n_("Non-existing parts specified."))
                new = {x for x in parts if x < 0}
                updated = {x for x in parts
                           if x > 0 and parts[x] is not None}
                deleted = {x for x in parts
                           if x > 0 and parts[x] is None}
                if has_registrations and (deleted or new):
                    raise ValueError(
                        n_("Registrations exist, modifications only."))
                if deleted >= existing | new:
                    raise ValueError(n_("At least one event part required."))
                for x in new:
                    new_part = copy.deepcopy(parts[x])
                    new_part['event_id'] = data['id']
                    tracks = new_part.pop('tracks', {})
                    new_id = self.sql_insert(rs, "event.event_parts", new_part)
                    ret *= new_id
                    ret *= self._set_tracks(rs, data['id'], new_id, tracks)
                    self.event_log(
                        rs, const.EventLogCodes.part_created, data['id'],
                        additional_info=new_part['title'])
                current = self.sql_select(
                    rs, "event.event_parts", ("id", "title"), updated | deleted)
                titles = {e['id']: e['title'] for e in current}
                for x in updated:
                    update = copy.deepcopy(parts[x])
                    update['id'] = x
                    tracks = update.pop('tracks', {})
                    ret *= self.sql_update(rs, "event.event_parts", update)
                    ret *= self._set_tracks(rs, data['id'], x, tracks)
                    self.event_log(
                        rs, const.EventLogCodes.part_changed, data['id'],
                        additional_info=titles[x])
                if deleted:
                    # First delete dependent course tracks
                    all_tracks = self.sql_select(
                        rs, "event.course_tracks", ('id', 'part_id'), deleted,
                        entity_key="part_id")
                    for x in deleted:
                        tracks = {e['id']: None for e in all_tracks
                                  if e['part_id'] == x}
                        self._set_tracks(rs, data['id'], x, tracks)
                    # Second go for the parts
                    ret *= self.sql_delete(rs, "event.event_parts", deleted)
                    for x in deleted:
                        self.event_log(
                            rs, const.EventLogCodes.part_deleted, data['id'],
                            additional_info=titles[x])
            if 'fields' in data:
                fields = data['fields']
                current = self.sql_select(
                    rs, "event.field_definitions", ("id",), (data['id'],),
                    entity_key="event_id")
                existing = {e['id'] for e in current}
                if not (existing >= {x for x in fields if x > 0}):
                    raise ValueError(n_("Non-existing fields specified."))
                new = {x for x in fields if x < 0}
                updated = {x for x in fields
                           if x > 0 and fields[x] is not None}
                deleted = {x for x in fields
                           if x > 0 and fields[x] is None}
                current = self.sql_select(
                    rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
                    updated | deleted)
                field_data = {e['id']: e for e in current}
                # new
                for x in new:
                    new_field = copy.deepcopy(fields[x])
                    new_field['event_id'] = data['id']
                    ret *= self.sql_insert(rs, "event.field_definitions",
                                           new_field)
                    self.event_log(
                        rs, const.EventLogCodes.field_added, data['id'],
                        additional_info=fields[x]['field_name'])
                # updated
                for x in updated:
                    update = copy.deepcopy(fields[x])
                    update['id'] = x
                    if ('kind' in update
                            and update['kind'] != field_data[x]['kind']):
                        self._cast_field_values(rs, field_data[x],
                                                update['kind'])
                    ret *= self.sql_update(rs, "event.field_definitions",
                                           update)
                    self.event_log(
                        rs, const.EventLogCodes.field_updated, data['id'],
                        additional_info=field_data[x]['field_name'])

                # deleted
                if deleted:
                    ret *= self.sql_delete(rs, "event.field_definitions",
                                           deleted)
                    for x in deleted:
                        self._delete_field_values(rs, field_data[x])
                        self.event_log(
                            rs, const.EventLogCodes.field_removed, data['id'],
                            additional_info=field_data[x]['field_name'])
        return ret

    @access("event_admin")
    def create_event(self, rs, data):
        """Make a new event organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("event", data, creation=True)
        if 'parts' not in data:
            raise ValueError(n_("At least one event part required."))
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            new_id = self.sql_insert(rs, "event.events", edata)
            update_data = {aspect: data[aspect]
                           for aspect in ('parts', 'orgas', 'fields')
                           if aspect in data}
            if update_data:
                update_data['id'] = new_id
                self.set_event(rs, update_data)
        self.event_log(rs, const.EventLogCodes.event_created, new_id)
        return new_id

    @access("event_admin")
    def delete_event_blockers(self, rs, event_id):
        """Determine what keeps an event from being deleted.

        Possible blockers:

        * field_definitions: A custom datafield associated with the event.
        * courses: A course associated with the event. This can have it's own
                   blockers.
        * course_tracks: A course track of the event.
        * orgas: An orga of the event.
        * lodgements: A lodgement associated with the event. This can have
                      it's own blockers.
        * registrations: A registration associated with the event. This can
                         have it's own blockers.
        * questionnaire: A questionnaire row configured for the event.
        * log: A log entry for the event.
        * mailinglists: A mailinglist associated with the event. This
                        reference will be removed but the mailinglist will
                        not be deleted.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        event_id = affirm("id", event_id)
        blockers = {}

        field_definitions = self.sql_select(
            rs, "event.field_definitions", ("id",), (event_id,),
            entity_key="event_id")
        if field_definitions:
            blockers["field_definitions"] = [e["id"] for e in field_definitions]

        courses = self.sql_select(
            rs, "event.courses", ("id",), (event_id,), entity_key="event_id")
        if courses:
            blockers["courses"] = [e["id"] for e in courses]

        event_parts = self.sql_select(rs, "event.event_parts", ("id",),
                                      (event_id,), entity_key="event_id")
        if event_parts:
            blockers["event_parts"] = [e["id"] for e in event_parts]
            course_tracks = self.sql_select(
                rs, "event.course_tracks", ("id",), blockers["event_parts"],
                entity_key="part_id")
            if course_tracks:
                blockers["course_tracks"] = [e["id"] for e in course_tracks]

        orgas = self.sql_select(
            rs, "event.orgas", ("id",), (event_id,), entity_key="event_id")
        if orgas:
            blockers["orgas"] = [e["id"] for e in orgas]

        lodgements = self.sql_select(
            rs, "event.lodgements", ("id",), (event_id,), entity_key="event_id")
        if lodgements:
            blockers["lodgements"] = [e["id"] for e in lodgements]

        registrations = self.sql_select(
            rs, "event.registrations", ("id",), (event_id,),
            entity_key="event_id")
        if registrations:
            blockers["registrations"] = [e["id"] for e in registrations]

        questionnaire_rows = self.sql_select(
            rs, "event.questionnaire_rows", ("id",), (event_id,),
            entity_key="event_id")
        if questionnaire_rows:
            blockers["questionnaire"] = [e["id"] for e in questionnaire_rows]

        log = self.sql_select(
            rs, "event.log", ("id",), (event_id,), entity_key="event_id")
        if log:
            blockers["log"] = [e["id"] for e in log]

        mailinglists = self.sql_select(
            rs, "ml.mailinglists", ("id",), (event_id,), entity_key="event_id")
        if mailinglists:
            blockers["mailinglists"] = [e["id"] for e in mailinglists]

        return blockers

    @access("event_admin")
    def delete_event(self, rs, event_id, cascade=None):
        """Remove event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
        """
        event_id = affirm("id", event_id)
        blockers = self.delete_event_blockers(rs, event_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "event",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            if cascade:
                if "registrations" in cascade:
                    with Silencer(rs):
                        for reg_id in blockers["registrations"]:
                            ret *= self.delete_registration(
                                rs, reg_id,
                                ("registration_parts", "course_choices",
                                 "registration_tracks"))
                if "courses" in cascade:
                    with Silencer(rs):
                        for course_id in blockers["courses"]:
                            ret *= self.delete_course(
                                rs, course_id,
                                ("attendees", "course_choices",
                                 "course_segments", "instructors"))
                if "lodgements" in cascade:
                    ret *= self.sql_delete(rs, "event.lodgements",
                                           blockers["lodgements"])
                if "questionnaire" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.questionnaire_rows",
                        blockers["questionnaire"])
                if "field_definitions" in cascade:
                    deletor = {
                        'id': event_id,
                        'course_room_field': None,
                        'lodge_field': None,
                        'reserve_field': None,
                    }
                    ret *= self.sql_update(rs, "event.events", deletor)
                    ret *= self.sql_delete(
                        rs, "event.field_definitions",
                        blockers["field_definitions"])
                if "course_tracks" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.course_tracks", blockers["course_tracks"])
                if "event_parts" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.event_parts", blockers["event_parts"])
                if "orgas" in cascade:
                    ret *= self.sql_delete(rs, "event.orgas", blockers["orgas"])
                if "log" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.log", blockers["log"])
                if "mailinglists" in cascade:
                    for anid in blockers["mailinglists"]:
                        deletor = {
                            'event_id': None,
                            'id': anid,
                            'is_active': False,
                        }
                        ret *= self.sql_update(rs, "ml.mailinglists", deletor)

                blockers = self.delete_event_blockers(rs, event_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "event.events", event_id)
                self.event_log(rs, const.EventLogCodes.event_deleted,
                               event_id=None, additional_info=event["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "event", "block": blockers.keys()})
        return ret

    @access("anonymous")
    @singularize("get_course")
    def get_courses(self, rs, ids):
        """Retrieve data for some courses organized via DB.

        They must be associated to the same event. This contains additional
        information on the parts in which the course takes place.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.courses", COURSE_FIELDS, ids)
            if not data:
                return {}
            ret = {e['id']: e for e in data}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only courses from one event allowed."))
            event_fields = self._get_event_fields(rs, unwrap(events))
            data = self.sql_select(
                rs, "event.course_segments", COURSE_SEGMENT_FIELDS, ids,
                entity_key="course_id")
            for anid in ids:
                segments = {p['track_id'] for p in data if
                            p['course_id'] == anid}
                assert ('segments' not in ret[anid])
                ret[anid]['segments'] = segments
                active_segments = {p['track_id'] for p in data
                                   if p['course_id'] == anid and p['is_active']}
                assert ('active_segments' not in ret[anid])
                ret[anid]['active_segments'] = active_segments
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'],
                                                  event_fields)
        return ret

    @access("event")
    def set_course(self, rs, data):
        """Update some keys of a course linked to an event organized via DB.

        If the 'segments' key is present you have to pass the complete list
        of track IDs, which will superseed the current list of tracks.

        If the 'active_segments' key is present you have to pass the
        complete list of active track IDs, which will superseed the current
        list of active tracks. This has to be a subset of the segments of
        the course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code

        """
        data = affirm("course", data)
        if not self.is_orga(rs, course_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            current = self.sql_select_one(rs, "event.courses",
                                          ("title", "event_id"), data['id'])

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
                    "event_associated_fields", data['fields'],
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
                    additional_info=current['title'])
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
                    associated_parts = map(unwrap, tracks)
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
                    query = glue("DELETE FROM event.course_segments",
                                 "WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deleted))
                if new or deleted:
                    self.event_log(
                        rs, const.EventLogCodes.course_segments_changed,
                        current['event_id'], additional_info=current['title'])
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
                        current['event_id'], additional_info=current['title'])
        return ret

    @access("event")
    def create_course(self, rs, data):
        """Make a new course organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new course
        """
        data = affirm("course", data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            "event_associated_fields", fdata, fields=event_fields,
            association=const.FieldAssociations.course)
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
                       data['event_id'], additional_info=data['title'])
        return new_id

    @access("event")
    def delete_course_blockers(self, rs, course_id):
        """Determine what keeps a course from beeing deleted.

        Possible blockers:

        * attendees: A registration track that assigns a registration to
                     the course as an attendee.
        * instructors: A registration track that references the course meaning
                       the participant is (potentially) the course's instructor.
        * course_choices: A course choice of the course.
        * course_segments: The course segments of the course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type course_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        course_id = affirm("id", course_id)
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
    def delete_course(self, rs, course_id, cascade=None):
        """Remove a course organized via DB from the DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type course_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: standard return code
        """
        course_id = affirm("id", course_id)
        if (not self.is_orga(rs, course_id=course_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=course_id)

        blockers = self.delete_course_blockers(rs, course_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
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
                    ret *= self.sql_delete(rs, "event.course_choices",
                                           blockers["course_choices"])
                if "course_segments" in cascade:
                    ret *= self.sql_delete(rs, "event.course_segments",
                                           blockers["course_segments"])

                # check if course is deletable after cascading
                blockers = self.delete_course_blockers(rs, course_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.courses", course_id)
                self.event_log(rs, const.EventLogCodes.course_deleted,
                               course['event_id'],
                               additional_info=course['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "course", "block": blockers.keys()})
        return ret

    @access("event")
    def list_registrations(self, rs, event_id, persona_id=None):
        """List all registrations of an event.

        If an ordinary event_user is requesting this, just participants of this
        event are returned and he himself must have the status 'participant'.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type persona_id: int or None
        :param persona_id: If passed restrict to registrations by this persona.
        :rtype: {int: int}
        """
        event_id = affirm("id", event_id)
        persona_id = affirm("id_or_None", persona_id)
        query = glue("SELECT id, persona_id FROM event.registrations",
                     "WHERE event_id = %s")
        params = (event_id,)
        # condition for limited access, f. e. for the online participant list
        is_limited = (persona_id != rs.user.persona_id
                      and not self.is_orga(rs, event_id=event_id)
                      and not self.is_admin(rs))
        if is_limited:
            query = ("SELECT DISTINCT regs.id, regs.persona_id "
                     "FROM event.registrations AS regs "
                     "LEFT OUTER JOIN event.registration_parts AS rparts "
                     "ON rparts.registration_id = regs.id "
                     "WHERE regs.event_id = %s AND rparts.status = %s")
            params += (const.RegistrationPartStati.participant,)
        if persona_id and not is_limited:
            query = glue(query, "AND persona_id = %s")
            params += (persona_id,)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e['persona_id'] for e in data}
        if is_limited and rs.user.persona_id not in ret.values():
            raise PrivilegeError(n_("Not privileged."))
        return ret

    @access("event")
    def get_registration_map(self, rs, event_ids):
        """Retrieve a map of personas to their registrations.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_ids: [int]
        :rtype {(int, int): int}
        """
        event_ids = affirm_set("id", event_ids)
        if (not all(self.is_orga(rs, event_id=anid) for anid in event_ids) and
                not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))

        data = self.sql_select(
            rs, "event.registrations", ("id", "persona_id", "event_id"),
            event_ids, entity_key="event_id")
        ret = {(e["event_id"], e["persona_id"]): e["id"] for e in data}

        return ret


    @access("event")
    def registrations_by_course(self, rs, event_id, course_id=None,
            track_id=None, position=None, reg_ids=None,
            reg_states=(const.RegistrationPartStati.participant,)):
        """List registrations of an event pertaining to a certain course.

        This is a filter function, mainly for the course assignment tool.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type track_id: int or None
        :type course_id: int or None
        :param position: A :py:class:`cdedb.common.CourseFilterPositions`
        :type position: :py:class:`cdedb.common.InfiniteEnum`
        :param reg_ids: List of registration ids to filter for
        :type reg_ids: [int] or None
        :param reg_ids: List of registration states (in any part) to filter for
        :type reg_ids: [const.RegistrationPartStati]
        :rtype: {int: int}
        """
        event_id = affirm("id", event_id)
        track_id = affirm("id_or_None", track_id)
        course_id = affirm("id_or_None", course_id)
        position = affirm("infinite_enum_coursefilterpositions_or_None",
                          position)
        reg_ids = reg_ids or set()
        reg_ids = affirm_set("id", reg_ids)
        reg_states = affirm_set("enum_registrationpartstati", reg_states)
        if (not self.is_admin(rs)
                and not self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))
        query = glue(
            "SELECT DISTINCT regs.id, regs.persona_id",
            "FROM event.registrations AS regs",
            "LEFT OUTER JOIN event.registration_parts AS rparts",
            "ON rparts.registration_id = regs.id",
            "LEFT OUTER JOIN event.course_tracks AS course_tracks",
            "ON course_tracks.part_id = rparts.part_id",
            "LEFT OUTER JOIN event.registration_tracks AS rtracks",
            "ON rtracks.registration_id = regs.id",
            "AND rtracks.track_id = course_tracks.id",
            "LEFT OUTER JOIN event.course_choices AS choices",
            "ON choices.registration_id = regs.id",
            "AND choices.track_id = course_tracks.id",
            "WHERE regs.event_id = %s AND rparts.status = ANY(%s)")
        params = (event_id, reg_states)
        if track_id:
            query = glue(query, "AND course_tracks.id = %s")
            params += (track_id,)
        if position is not None:
            cfp = CourseFilterPositions
            conditions = []
            if position.enum in (cfp.instructor, cfp.anywhere):
                if course_id:
                    conditions.append("rtracks.course_instructor = %s")
                    params += (course_id,)
                else:
                    conditions.append("rtracks.course_instructor IS NULL")
            if position.enum in (cfp.any_choice, cfp.anywhere) and course_id:
                conditions.append(
                    "(choices.course_id = %s AND "
                    " choices.rank < course_tracks.num_choices)")
                params += (course_id,)
            if position.enum == cfp.specific_rank and course_id:
                conditions.append(
                    "(choices.course_id = %s AND choices.rank = %s)")
                params += (course_id, position.int)
            if position.enum in (cfp.assigned, cfp.anywhere):
                if course_id:
                    conditions.append("rtracks.course_id = %s")
                    params += (course_id,)
                else:
                    conditions.append("rtracks.course_id IS NULL")
            if conditions:
                query = glue(query, "AND (", " OR ".join(conditions), ")")
        if reg_ids:
            query = glue(query, "AND regs.id = ANY(%s)")
            params += (reg_ids,)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event")
    @singularize("get_registration")
    def get_registrations(self, rs, ids):
        """Retrieve data for some registrations.

        All have to be from the same event.
        You must be orga to get additional access to all registrations which are
        not your own. If you are participant of the event, you get access to
        data from other users, being also participant in the same event (this is
        important for the online participant list).
        This includes the following additional data:

        * parts: per part data (like lodgement),
        * tracks: per track data (like course choices)

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        ret = {}
        with Atomizer(rs):
            # Check associations.
            associated = self.sql_select(rs, "event.registrations",
                                         ("persona_id", "event_id"), ids)
            if not associated:
                return {}
            events = {e['event_id'] for e in associated}
            personas = {e['persona_id'] for e in associated}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))
            event_id = unwrap(events)
            # Select appropriate stati filter.
            stati = set(const.RegistrationPartStati)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                if rs.user.persona_id not in personas:
                    raise PrivilegeError(n_("Not privileged."))
                elif not personas <= {rs.user.persona_id}:
                    # Permission check is done later when we know more
                    stati = {const.RegistrationPartStati.participant}

            ret = {e['id']: e for e in self.sql_select(
                rs, "event.registrations", REGISTRATION_FIELDS, ids)}
            event_fields = self._get_event_fields(rs, event_id)
            pdata = self.sql_select(
                rs, "event.registration_parts", REGISTRATION_PART_FIELDS, ids,
                entity_key="registration_id")
            for anid in tuple(ret):
                assert ('parts' not in ret[anid])
                ret[anid]['parts'] = {
                    e['part_id']: e
                    for e in pdata if e['registration_id'] == anid
                }
                # Limit to registrations matching stati filter in any part.
                if not any(e['status'] in stati
                           for e in ret[anid]['parts'].values()):
                    del ret[anid]
            # Here comes the promised permission check
            if all(reg['persona_id'] != rs.user.persona_id
                   for reg in ret.values()):
                raise PrivilegeError(n_("No participant of event."))

            tdata = self.sql_select(
                rs, "event.registration_tracks", REGISTRATION_TRACK_FIELDS, ids,
                entity_key="registration_id")
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"), ids,
                entity_key="registration_id")
            for anid in ret:
                assert ('tracks' not in ret[anid])
                tracks = {e['track_id']: e for e in tdata
                          if e['registration_id'] == anid}
                for track_id in tracks:
                    tmp = {e['course_id']: e['rank'] for e in choices
                           if (e['registration_id'] == anid
                               and e['track_id'] == track_id)}
                    tracks[track_id]['choices'] = sorted(tmp.keys(),
                                                         key=tmp.get)
                ret[anid]['tracks'] = tracks
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'],
                                                  event_fields)
        return ret

    @access("event")
    def has_registrations(self, rs, event_id):
        """Determine whether there exist registrations for an event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: bool
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        with Atomizer(rs):
            query = glue("SELECT COUNT(*) FROM event.registrations",
                         "WHERE event_id = %s LIMIT 1")
            return bool(unwrap(self.query_one(rs, query, (event_id,))))

    def _get_event_course_segments(self, rs, event_id):
        """
        Helper function to get course segments of all courses of an event.

        Required for _set_course_choices().

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :returns: A dict mapping each course id (of the event) to a list of
            track ids (which correspond to its segments)
        :rtype {int: [int]}
        """
        query = glue("SELECT courses.id,",
                     "    array_agg(segments.track_id) AS segments",
                     "FROM event.courses as courses",
                     "    LEFT JOIN event.course_segments AS segments",
                     "    ON courses.id = segments.course_id",
                     "WHERE courses.event_id = %s",
                     "GROUP BY courses.id")
        return {row['id']: row['segments']
                for row in self.query_all(rs, query, (event_id,))}

    def _set_course_choices(self, rs, registration_id, track_id, choices,
                            course_segments, new_registration=False):
        """Helper for handling of course choices.

        This is basically uninlined code from ``set_registration()``.

        :note: This has to be called inside an atomized context.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type registration_id: int
        :type track_id: int
        :type choices: [int]
        :param course_segments: Dict, course segments, as returned by
            _get_event_course_segments()
        :type course_segments: {int: [int]}
        :param new_registration: Performance optimization for creating
            registrations: If true, the delition of existing choices is skipped.
        :rtype: int
        :returns: default return code
        """
        ret = 1
        if choices is None:
            # Nothing specified, hence nothing to do
            return ret
        for course_id in choices:
            if track_id not in course_segments[course_id]:
                raise ValueError(n_("Wrong track for course."))
        if not new_registration:
            query = glue("DELETE FROM event.course_choices",
                         "WHERE registration_id = %s AND track_id = %s")
            self.query_exec(rs, query, (registration_id, track_id))
        for rank, course_id in enumerate(choices):
            new_choice = {
                "registration_id": registration_id,
                "track_id": track_id,
                "course_id": course_id,
                "rank": rank,
            }
            ret *= self.sql_insert(rs, "event.course_choices",
                                   new_choice)
        return ret

    @access("event")
    def set_registration(self, rs, data):
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("registration", data)
        current = self.sql_select_one(
            rs, "event.registrations", ("persona_id", "event_id"), data['id'])
        persona_id, event_id = current['persona_id'], current['event_id']
        with Atomizer(rs):
            self.assert_offline_lock(rs, event_id=event_id)
            if (persona_id != rs.user.persona_id
                    and not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            course_segments = self._get_event_course_segments(rs, event_id)

            # now we get to do the actual work
            rdata = {k: v for k, v in data.items()
                     if k in REGISTRATION_FIELDS and k != "fields"}
            ret = 1
            if len(rdata) > 1:
                ret *= self.sql_update(rs, "event.registrations", rdata)
            if 'fields' in data:
                # delayed validation since we need additional info
                fdata = affirm(
                    "event_associated_fields", data['fields'],
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
                if not (set(event['parts'].keys()) >= {x for x in parts}):
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
                all_tracks = set(event['tracks'])
                if not (all_tracks >= set(tracks)):
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
        self.event_log(
            rs, const.EventLogCodes.registration_changed, event_id,
            persona_id=persona_id)
        return ret

    @access("event")
    def create_registration(self, rs, data):
        """Make a new registration.

        The data must contain a dataset for each part and each track
        and may not contain a value for 'fields', which is initialized
        to a default value.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new registration
        """
        data = affirm("registration", data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            "event_associated_fields", fdata, fields=event_fields,
            association=const.FieldAssociations.registration)
        data['fields'] = PsycoJson(fdata)
        if (data['persona_id'] != rs.user.persona_id
                and not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
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
    def delete_registration_blockers(self, rs, registration_id):
        """Determine what keeps a registration from being deleted.

        Possible blockers:

        * registration_parts: The registration's registration parts.
        * registration_tracks: The registration's registration tracks.
        * course_choices: The registrations course choices.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type registration_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        registration_id = affirm("id", registration_id)
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
    def delete_registration(self, rs, registration_id, cascade=None):
        """Remove a registration.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type registration_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: standard return code
        """
        registration_id = affirm("id", registration_id)
        reg = self.get_registration(rs, registration_id)
        if (not self.is_orga(rs, event_id=reg['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=reg['event_id'])

        blockers = self.delete_registration_blockers(rs, registration_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
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

    @access("event")
    def check_orga_addition_limit(self, rs, event_id):
        """Implement a rate limiting check for orgas adding persons.

        Since adding somebody as participant or orga to an event gives all
        orgas basically full access to their data, we rate limit this
        operation.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: bool
        :returns: True if limit has not been reached.
        """
        event_id = affirm("id", event_id)
        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        if self.is_admin(rs):
            # Admins are exempt
            return True
        with Atomizer(rs):
            query = glue(
                "SELECT COUNT(*) AS num FROM event.log WHERE event_id = %s",
                "AND code = %s AND submitted_by != persona_id",
                "AND ctime >= now() - interval '24 hours'")
            params = (event_id, const.EventLogCodes.registration_created)
            num = unwrap(self.query_one(rs, query, params))
        return num < self.conf.ORGA_ADD_LIMIT

    @access("event")
    def list_lodgements(self, rs, event_id):
        """List all lodgements for an event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: {int: str}
        :returns: dict mapping ids to names
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "event.lodgements", ("id", "moniker"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['moniker'] for e in data}

    @access("event")
    @singularize("get_lodgement")
    def get_lodgements(self, rs, ids):
        """Retrieve data for some lodgements.

        All have to be from the same event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.lodgements", LODGEMENT_FIELDS,
                                   ids)
            if not data:
                return {}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only lodgements from exactly one event allowed!"))
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event_fields = self._get_event_fields(rs, event_id)
            ret = {e['id']: e for e in data}
            for entry in ret.values():
                entry['fields'] = cast_fields(entry['fields'], event_fields)
        return {e['id']: e for e in data}

    @access("event")
    def set_lodgement(self, rs, data):
        """Update some keys of a lodgement.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("lodgement", data)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "event.lodgements", ("event_id", "moniker"), data['id'])
            event_id, moniker = current['event_id'], current['moniker']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            self.assert_offline_lock(rs, event_id=event_id)

            # now we get to do the actual work
            ret = 1
            ldata = {k: v for k, v in data.items()
                     if k in LODGEMENT_FIELDS and k != "fields"}
            if len(ldata) > 1:
                ret *= self.sql_update(rs, "event.lodgements", ldata)
            if 'fields' in data:
                # delayed validation since we need more info
                event_fields = self._get_event_fields(rs, event_id)
                fdata = affirm(
                    "event_associated_fields", data['fields'],
                    fields=event_fields,
                    association=const.FieldAssociations.lodgement)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.lodgements",
                                                    fupdate)
            self.event_log(
                rs, const.EventLogCodes.lodgement_changed, event_id,
                additional_info=moniker)
            return ret

    @access("event")
    def create_lodgement(self, rs, data):
        """Make a new lodgement.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new lodgement
        """
        data = affirm("lodgement", data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            "event_associated_fields", fdata, fields=event_fields,
            association=const.FieldAssociations.lodgement)
        data['fields'] = PsycoJson(fdata)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "event.lodgements", data)
            self.event_log(
                rs, const.EventLogCodes.lodgement_created, data['event_id'],
                additional_info=data['moniker'])
        return new_id

    @access("event")
    def delete_lodgement_blockers(self, rs, lodgement_id):
        """Determine what keeps a lodgement from beeing deleted.

        Possible blockers:

        * inhabitants: A registration part that assigns a registration to the
                       lodgement as an inhabitant.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lodgement_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        lodgement_id = affirm("id", lodgement_id)
        blockers = {}

        inhabitants = self.sql_select(
            rs, "event.registration_parts", ("id",), (lodgement_id,),
            entity_key="lodgement_id")
        if inhabitants:
            blockers["inhabitants"] = [e["id"] for e in inhabitants]

        return blockers

    @access("event")
    def delete_lodgement(self, rs, lodgement_id, cascade=None):
        """Make a new lodgement.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lodgement_id: int
        :type cascade: bool
        :param cascade: If False this function has the precondition, that no
          dependent entities exist. If True these dependent entities are
          excised as well.
        :rtype: int
        :returns: default return code
        """
        lodgement_id = affirm("id", lodgement_id)
        lodgement = self.get_lodgement(rs, lodgement_id)
        event_id = lodgement["event_id"]
        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        blockers = self.delete_lodgement_blockers(rs, lodgement_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "lodgement",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "inhabitants" in cascade:
                    for anid in blockers["inhabitants"]:
                        deletor = {
                            'lodgement_id': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(
                            rs, "event.registration_parts", deletor)

                blockers = self.delete_lodgement_blockers(rs, lodgement_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.lodgements", lodgement_id)
                self.event_log(rs, const.EventLogCodes.lodgement_deleted,
                               event_id, additional_info=lodgement["moniker"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lodgement", "block": blockers.keys()})
        return ret

    @access("event")
    def get_questionnaire(self, rs, event_id):
        """Retrieve the questionnaire rows for a specific event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: [{str: object}]
        :returns: list of questionnaire row entries
        """
        event_id = affirm("id", event_id)
        data = self.sql_select(
            rs, "event.questionnaire_rows",
            ("field_id", "pos", "title", "info", "input_size", "readonly",
             "default_value"),
            (event_id,), entity_key="event_id")
        return sorted(data, key=lambda x: x['pos'])

    @access("event")
    def set_questionnaire(self, rs, event_id, data):
        """Replace current questionnaire rows for a specific event.

        This superseeds the current questionnaire.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type data: [{str: object}]
        :rtype: int
        :returns: default return code
        """
        event_id = affirm("id", event_id)
        event = self.get_event(rs, event_id)
        data = affirm("questionnaire", data, field_definitions=event['fields'])
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        with Atomizer(rs):
            self.sql_delete(rs, "event.questionnaire_rows", (event_id,),
                            entity_key="event_id")
            ret = 1
            for pos, row in enumerate(data):
                new_row = copy.deepcopy(row)
                new_row['pos'] = pos
                new_row['event_id'] = event_id
                ret *= self.sql_insert(rs, "event.questionnaire_rows", new_row)
        self.event_log(rs, const.EventLogCodes.questionnaire_changed, event_id)
        return ret

    @access("event")
    def lock_event(self, rs, event_id):
        """Lock an event for offline usage.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: int
        :returns: standard return code
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)
        # An event in the main instance is considered as locked if offline_lock
        # is true, in the offline instance it is the other way around
        update = {
            'id': event_id,
            'offline_lock': not self.conf.CDEDB_OFFLINE_DEPLOYMENT,
        }
        ret = self.sql_update(rs, "event.events", update)
        self.event_log(rs, const.EventLogCodes.event_locked, event_id)
        return ret

    @access("event")
    def export_event(self, rs, event_id):
        """Export an event for offline usage or after offline usage.

        This provides a more general export functionality which could
        also be used without locking.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: dict
        :returns: dict holding all data of the exported event
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist):
            return {e['id']: e for e in alist}

        with Atomizer(rs):
            ret = {
                'CDEDB_EXPORT_EVENT_VERSION': CDEDB_EXPORT_EVENT_VERSION,
                'kind': "full",  # could also be "partial"
                'id': event_id,
                'event.events': list_to_dict(self.sql_select(
                    rs, "event.events", EVENT_FIELDS, (event_id,))),
                'timestamp': now(),
            }
            # Table name; column to scan; fields to extract
            tables = (
                ('event.event_parts', "event_id", EVENT_PART_FIELDS),
                ('event.course_tracks', "part_id", COURSE_TRACK_FIELDS),
                ('event.courses', "event_id", COURSE_FIELDS),
                ('event.course_segments', "track_id", (
                    'id', 'course_id', 'track_id', 'is_active')),
                ('event.orgas', "event_id", (
                    'id', 'persona_id', 'event_id',)),
                ('event.field_definitions', "event_id",
                 FIELD_DEFINITION_FIELDS),
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
                    'input_size', 'readonly',)),
                ('event.log', "event_id", (
                    'id', 'ctime', 'code', 'submitted_by', 'event_id',
                    'persona_id', 'additional_info')),
            )
            personas = set()
            for table, id_name, columns in tables:
                if id_name == "event_id":
                    id_range = {event_id}
                elif id_name == "part_id":
                    id_range = set(ret['event.event_parts'])
                elif id_name == "track_id":
                    id_range = set(ret['event.course_tracks'])
                else:
                    id_range = None
                if 'id' not in columns:
                    columns += ('id',)
                ret[table] = list_to_dict(self.sql_select(
                    rs, table, columns, id_range, entity_key=id_name))
                # Note the personas present to export them further on
                for e in ret[table].values():
                    if e.get('persona_id'):
                        personas.add(e['persona_id'])
            ret['core.personas'] = list_to_dict(self.sql_select(
                rs, "core.personas", PERSONA_EVENT_FIELDS, personas))
            return ret

    @classmethod
    def translate(cls, data, translations, extra_translations=None):
        """Helper to do the actual translation of IDs which got out of sync.

        This does some additional sanitizing besides applying the
        translation.

        :type data: [{str: object}]
        :type translations: {str: {int: int}}
        :type extra_translations: {str: str}
        :rtype: [{str: object}]
        """
        extra_translations = extra_translations or {}
        ret = copy.deepcopy(data)
        for x in ret:
            if x in translations or x in extra_translations:
                target = extra_translations.get(x, x)
                ret[x] = translations[target].get(ret[x], ret[x])
            if isinstance(ret[x], collections.Mapping):
                # All mappings have to be JSON columns in the database
                # (nothing else should be possible).
                ret[x] = PsycoJson(
                    cls.translate(ret[x], translations, extra_translations))
        if ret.get('real_persona_id'):
            ret['real_persona_id'] = None
        return ret

    def synchronize_table(self, rs, table, data, current, translations,
                          entity=None, extra_translations=None):
        """Replace one data set in a table with another.

        This is a bit involved, since both DB instances may have been
        modified, so that conflicting primary keys were created. Thus we
        have a snapshot ``current`` of the state at locking time and
        apply the diff to the imported state in ``data``. Any IDs which
        were not previously present in the DB into which we import have
        to be kept track of -- this is done in ``translations``.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type table: str
        :type data: {int: {str: object}}
        :param data: Data set to put in.
        :type current: {int: {str: object}}
        :param current: Current state.
        :type translations: {str: {int: int}}
        :param translations: IDs which got out of sync during offline usage.
        :type entity: str
        :param entity: Name of IDs this table is referenced as. Any of the
          primary keys which are processed here, that got out of sync are
          added to the corresponding entry in ``translations``
        :type extra_translations: {str: str}
        :param extra_translations: Additional references which do not use a
          standard name.
        :rtype: int
        :returns: standard return code
        """
        extra_translations = extra_translations or {}
        ret = 1
        for anid in set(current) - set(data):
            ret *= self.sql_delete_one(rs, table, anid)
        for e in data.values():
            if e != current.get(e['id']):
                new_e = self.translate(e, translations, extra_translations)
                if new_e['id'] in current:
                    ret *= self.sql_update(rs, table, new_e)
                else:
                    if 'id' in new_e:
                        del new_e['id']
                    new_id = self.sql_insert(rs, table, new_e)
                    ret *= new_id
                    if entity:
                        translations[entity][e['id']] = new_id
        return ret

    @access("event")
    def unlock_import_event(self, rs, data):
        """Unlock an event after offline usage and import changes.

        This is a combined action so that we stay consistent.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: dict
        :rtype: int
        :returns: standard return code
        """
        data = affirm("serialized_event", data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        if self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError(n_(glue("Imports into an offline instance must",
                                       "happen via shell scripts.")))
        if not self.is_offline_locked(rs, event_id=data['id']):
            raise RuntimeError(n_("Not locked."))
        if data["CDEDB_EXPORT_EVENT_VERSION"] != CDEDB_EXPORT_EVENT_VERSION:
            raise ValueError(n_("Version mismatch – aborting."))

        with Atomizer(rs):
            current = self.export_event(rs, data['id'])
            # First check that all newly created personas have been
            # transferred to the online DB
            claimed = {e['persona_id']
                       for e in data['event.registrations'].values()
                       if not e['real_persona_id']}
            if claimed - set(current['core.personas']):
                raise ValueError(n_("Non-transferred persona found"))

            ret = 1
            # Second synchronize the data sets
            translations = collections.defaultdict(dict)
            for reg in data['event.registrations'].values():
                if reg['real_persona_id']:
                    translations['persona_id'][reg['persona_id']] = \
                        reg['real_persona_id']
            extra_translations = {'course_instructor': 'course_id'}
            # Table name; name of foreign keys referencing this table
            tables = (('event.events', None),
                      ('event.event_parts', 'part_id'),
                      ('event.course_tracks', 'track_id'),
                      ('event.courses', 'course_id'),
                      ('event.course_segments', None),
                      ('event.orgas', None),
                      ('event.field_definitions', 'field_id'),
                      ('event.lodgements', 'lodgement_id'),
                      ('event.registrations', 'registration_id'),
                      ('event.registration_parts', None),
                      ('event.registration_tracks', None),
                      ('event.course_choices', None),
                      ('event.questionnaire_rows', None),
                      ('event.log', None))
            for table, entity in tables:
                ret *= self.synchronize_table(
                    rs, table, data[table], current[table], translations,
                    entity=entity, extra_translations=extra_translations)
            # Third unlock the event
            update = {
                'id': data['id'],
                'offline_lock': False,
            }
            ret *= self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_unlocked, data['id'])
            return ret

    @access("event")
    def partial_export_event(self, rs, event_id):
        """Export an event for third-party applications.

        This provides a consumer-friendly package of event data which can
        later on be reintegrated with the partial import facility.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: dict
        :returns: dict holding all data of the exported event
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))

        def list_to_dict(alist):
            return {e['id']: e for e in alist}

        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            # basics
            ret = {
                'CDEDB_EXPORT_EVENT_VERSION': CDEDB_EXPORT_EVENT_VERSION,
                'kind': "partial",  # could also be "full"
                'id': event_id,
                'timestamp': now(),
            }
            # courses
            courses = list_to_dict(self.sql_select(
                rs, 'event.courses', COURSE_FIELDS, (event_id,),
                entity_key='event_id'))
            temp = self.sql_select(
                rs, 'event.course_segments',
                ('course_id', 'track_id', 'is_active'), courses.keys(),
                entity_key='course_id')
            lookup = collections.defaultdict(dict)
            for e in temp:
                lookup[e['course_id']][e['track_id']] = e['is_active']
            for course_id, course in courses.items():
                del course['id']
                del course['event_id']
                course['segments'] = lookup[course_id]
                course['fields'] = cast_fields(course['fields'], event['fields'])
            ret['courses'] = courses
            # lodgements
            lodgements = list_to_dict(self.sql_select(
                rs, 'event.lodgements', LODGEMENT_FIELDS, (event_id,),
                entity_key='event_id'))
            for lodgement in lodgements.values():
                del lodgement['id']
                del lodgement['event_id']
                lodgement['fields'] = cast_fields(lodgement['fields'],
                                                  event['fields'])
            ret['lodgements'] = lodgements
            # registrations
            registrations = list_to_dict(self.sql_select(
                rs, 'event.registrations', REGISTRATION_FIELDS, (event_id,),
                entity_key='event_id'))
            backup_registrations = copy.deepcopy(registrations)
            temp = self.sql_select(
                rs, 'event.registration_parts',
                REGISTRATION_PART_FIELDS, registrations.keys(),
                entity_key='registration_id')
            part_lookup = collections.defaultdict(dict)
            for e in temp:
                part_lookup[e['registration_id']][e['part_id']] = e
            temp = self.sql_select(
                rs, 'event.registration_tracks',
                REGISTRATION_TRACK_FIELDS, registrations.keys(),
                entity_key='registration_id')
            track_lookup = collections.defaultdict(dict)
            for e in temp:
                track_lookup[e['registration_id']][e['track_id']] = e
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"),
                registrations.keys(), entity_key="registration_id")
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
                    track['choices'] = sorted(tmp.keys(), key=tmp.get)
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
            for part in export_event['parts'].values():
                del part['id']
                del part['event_id']
                for track in part['tracks'].values():
                    del track['id']
                    del track['part_id']
            for f in ('lodge_field', 'reserve_field', 'course_room_field'):
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
            ret['event'] = export_event
            # personas
            persona_ids = tuple(reg['persona_id']
                                for reg in backup_registrations.values())
            personas = self.core.get_event_users(rs, persona_ids)
            for reg_id, registration in ret['registrations'].items():
                persona = personas[backup_registrations[reg_id]['persona_id']]
                persona['is_orga'] = persona['id'] in event['orgas']
                for attr in ('is_active', 'is_meta_admin', 'is_archived',
                             'is_assembly_admin', 'is_assembly_realm',
                             'is_cde_admin', 'is_finance_admin', 'is_cde_realm',
                             'is_core_admin', 'is_event_admin',
                             'is_event_realm', 'is_ml_admin', 'is_ml_realm',
                             'is_searchable'):
                    del persona[attr]
                registration['persona'] = persona
            return ret

    @access("event")
    def partial_import_event(self, rs, data, dryrun, token=None):
        """Incorporate changes into an event.

        In contrast to the full import in this case the data describes a
        delta to be applied to the current online state.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: dict
        :type dryrun: bool
        :param dryrun: If True we do not modify any state.
        :type token: str
        :param token: Expected transaction token. If the transaction would
          generate a different token a PartialImportError is raised.
        :rtype: (str, dict)
        :returns: A tuple of a transaction token and the datasets that
          are changed by the operation (in the state after the change). The
          transaction token describes the change and can be submitted to
          guarantee a certain effect.
        """
        data = affirm("serialized_partial_event", data)
        dryrun = affirm("bool", dryrun)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])
        if data["CDEDB_EXPORT_EVENT_VERSION"] != CDEDB_EXPORT_EVENT_VERSION:
            raise ValueError(n_("Version mismatch – aborting."))

        def dict_diff(old, new):
            delta = {}
            previous = {}
            # keys missing in the new dict are simply ignored
            for key, value in new.items():
                if key not in old:
                    delta[key] = value
                else:
                    if value == old[key]:
                        pass
                    elif isinstance(value, collections.abc.Mapping):
                        d, p = dict_diff(old[key], value)
                        if d:
                            delta[key], previous[key] = d, p
                    else:
                        delta[key] = value
                        previous[key] = old[key]
            return delta, previous

        with Atomizer(rs):
            event = unwrap(self.get_events(rs, (data['id'],)))
            all_current_data = self.partial_export_event(rs, data['id'])
            oregistration_ids = self.list_registrations(rs, data['id'])
            old_registrations = self.get_registrations(rs, oregistration_ids)

            # check referential integrity
            all_track_ids = {key for course in data.get('courses', {}).values()
                             if course
                             for key in course.get('segments', {})}
            all_track_ids |= {
                key for registration in data.get('registrations', {}).values()
                if registration
                for key in registration.get('tracks', {})}
            if not all_track_ids <= set(event['tracks']):
                raise ValueError("Referential integrity of tracks violated.")

            all_part_ids = {
                key for registration in data.get('registrations', {}).values()
                if registration
                for key in registration.get('parts', {})}
            if not all_part_ids <= set(event['parts']):
                raise ValueError("Referential integrity of parts violated.")

            all_lodgement_ids = {
                part.get('lodgement_id')
                for registration in data.get('registrations', {}).values()
                if registration
                for part in registration.get('parts', {}).values()}
            all_lodgement_ids -= {None}
            if not all_lodgement_ids <= set(all_current_data['lodgements']):
                raise ValueError(
                    "Referential integrity of lodgements violated.")

            all_course_ids = set()
            for attribute in ('course_id', 'course_choices',
                              'course_instructor'):
                all_course_ids |= {
                    track.get(attribute)
                    for registration in data.get('registrations', {}).values()
                    if registration
                    for track in registration.get('tracks', {}).values()}
            all_course_ids -= {None}
            if not all_course_ids <= set(all_current_data['courses']):
                raise ValueError(
                    "Referential integrity of courses violated.")

            # go to work
            total_delta = {}
            total_previous = {}
            rdelta = {}
            rprevious = {}

            dup = {
                old_reg['persona_id']: old_reg['id']
                for old_reg in old_registrations.values()
            }

            data_regs = data.get('registrations', {})
            for registration_id, new_registration in data_regs.items():
                if (registration_id < 0
                        and dup.get(new_registration.get('persona_id'))):
                    # the process got out of sync and the registration was
                    # already created, so we fix this
                    registration_id = dup[new_registration.get('persona_id')]
                    del new_registration['persona_id']

                current = all_current_data['registrations'].get(
                    registration_id)
                if registration_id > 0 and current is None:
                    # registration was deleted online in the meantime
                    rdelta[registration_id] = None
                    rprevious[registration_id] = None
                elif new_registration is None:
                    rdelta[registration_id] = None
                    rprevious[registration_id] = current
                    if not dryrun:
                        self.delete_registration(
                            rs, registration_id, ("registration_parts",
                                                  "registration_tracks",
                                                  "course_choices"))
                elif registration_id < 0:
                    rdelta[registration_id] = new_registration
                    rprevious[registration_id] = None
                    if not dryrun:
                        new = copy.deepcopy(new_registration)
                        new['event_id'] = data['id']
                        self.create_registration(rs, new)
                else:
                    delta, previous = dict_diff(current, new_registration)
                    if delta:
                        rdelta[registration_id] = delta
                        rprevious[registration_id] = previous
                        if not dryrun:
                            todo = copy.deepcopy(delta)
                            todo['id'] = registration_id
                            self.set_registration(rs, todo)
            if rdelta:
                total_delta['registrations'] = rdelta
                total_previous['registrations'] = rprevious
            ldelta = {}
            lprevious = {}
            for lodgement_id, new_lodgement in data.get('lodgements',
                                                        {}).items():
                current = all_current_data['lodgements'].get(lodgement_id)
                if lodgement_id > 0 and current is None:
                    # lodgement was deleted online in the meantime
                    ldelta[lodgement_id] = None
                    lprevious[lodgement_id] = None
                elif new_lodgement is None:
                    ldelta[lodgement_id] = None
                    lprevious[lodgement_id] = current
                    if not dryrun:
                        self.delete_lodgement(
                            rs, lodgement_id, ("inhabitants",))
                elif lodgement_id < 0:
                    ldelta[lodgement_id] = new_lodgement
                    lprevious[lodgement_id] = None
                    if not dryrun:
                        new = copy.deepcopy(new_lodgement)
                        new['event_id'] = data['id']
                        self.create_lodgement(rs, new)
                else:
                    delta, previous = dict_diff(current, new_lodgement)
                    if delta:
                        ldelta[lodgement_id] = delta
                        lprevious[lodgement_id] = previous
                        if not dryrun:
                            todo = copy.deepcopy(delta)
                            todo['id'] = lodgement_id
                            self.set_lodgement(rs, todo)
            if ldelta:
                total_delta['lodgements'] = ldelta
                total_previous['lodgements'] = lprevious
            cdelta = {}
            cprevious = {}
            check_seg = lambda track_id, delta, original: (
                 (track_id in delta and delta[track_id] is not None)
                 or (track_id not in delta and track_id in original))
            for course_id, new_course in data.get('courses', {}).items():
                current = all_current_data['courses'].get(course_id)
                if course_id > 0 and current is None:
                    # course was deleted online in the meantime
                    cdelta[course_id] = None
                    cprevious[course_id] = None
                elif new_course is None:
                    cdelta[course_id] = None
                    cprevious[course_id] = current
                    if not dryrun:
                        # this will fail to delete a course with attendees
                        self.delete_course(
                            rs, course_id, ("instructors", "course_choices",
                                            "course_segments"))
                elif course_id < 0:
                    cdelta[course_id] = new_course
                    cprevious[course_id] = None
                    if not dryrun:
                        new = copy.deepcopy(new_course)
                        new['event_id'] = data['id']
                        segments = new.pop('segments')
                        new['segments'] = list(segments.keys())
                        new['active_segments'] = [key for key in segments
                                                  if segments[key]]
                        self.create_course(rs, new)
                else:
                    delta, previous = dict_diff(current, new_course)
                    if delta:
                        cdelta[course_id] = delta
                        cprevious[course_id] = previous
                        if not dryrun:
                            todo = copy.deepcopy(delta)
                            segments = todo.pop('segments', None)
                            if segments:
                                orig_seg = current['segments']
                                new_segments = [
                                    x for x in event['tracks']
                                    if check_seg(x, segments, orig_seg)]
                                todo['segments'] = new_segments
                                orig_active = [
                                    s for s, a in current['segments'].items()
                                    if a]
                                new_active = [
                                    x for x in event['tracks']
                                    if segments.get(x, x in orig_active)]
                                todo['active_segments'] = new_active
                            todo['id'] = course_id
                            self.set_course(rs, todo)
            if cdelta:
                total_delta['courses'] = cdelta
                total_previous['courses'] = cprevious

            m = hashlib.sha512()
            m.update(json_serialize(total_previous, sort_keys=True).encode(
                'utf-8'))
            m.update(json_serialize(total_delta, sort_keys=True).encode(
                'utf-8'))
            result = m.hexdigest()
            if token is not None and result != token:
                raise PartialImportError("The delta changed.")
            if not dryrun:
                self.event_log(rs, const.EventLogCodes.event_partial_import,
                               data['id'])
            return result, total_delta
