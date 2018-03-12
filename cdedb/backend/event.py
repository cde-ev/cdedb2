#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy

from cdedb.backend.common import (
    access, affirm_validation as affirm, AbstractBackend, Silencer,
    affirm_set_validation as affirm_set, singularize, PYTHON_TO_SQL_MAP,
    cast_fields)
from cdedb.backend.cde import CdEBackend
from cdedb.common import (
    _, glue, PrivilegeError, EVENT_PART_FIELDS, EVENT_FIELDS, COURSE_FIELDS,
    REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS, LODGEMENT_FIELDS,
    COURSE_SEGMENT_FIELDS, unwrap, now, ProxyShim, PERSONA_EVENT_FIELDS,
    CourseFilterPositions, FIELD_DEFINITION_FIELDS, COURSE_TRACK_FIELDS,
    REGISTRATION_TRACK_FIELDS, event_gather_tracks, PsycoJson)
from cdedb.database.connection import Atomizer
from cdedb.query import QueryOperators
import cdedb.database.constants as const

#: This is used for generating the table for general queries for
#: registrations. We moved this rather huge blob here, so it doesn't
#: disfigure the query code.
#:
#: The end result may look something like the following::
#:
#:    event.registrations AS reg
#:    JOIN core.personas AS persona ON reg.persona_id = persona.id
#:    LEFT OUTER JOIN (SELECT registration_id, status AS status1, lodgement_id AS lodgement_id1, is_reserve AS is_reserve1
#:                     FROM event.registration_parts WHERE part_id = 1)
#:        AS part1 ON reg.id = part1.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.lodgements WHERE event_id=1)))
#:                     AS X(lodgement_id1 integer, contamination1 varchar))
#:        AS lodge_fields1 ON part1.lodgement_id1 = lodge_fields1.lodgement_id1
#:    LEFT OUTER JOIN (SELECT registration_id, status AS status2, lodgement_id AS lodgement_id2, is_reserve AS is_reserve2
#:                     FROM event.registration_parts WHERE part_id = 2)
#:        AS part2 ON reg.id = part2.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.lodgements WHERE event_id=1)))
#:                     AS X(lodgement_id2 integer, contamination2 varchar))
#:        AS lodge_fields2 ON part2.lodgement_id2 = lodge_fields2.lodgement_id2
#:    LEFT OUTER JOIN (SELECT registration_id, status AS status3, lodgement_id AS lodgement_id3, is_reserve AS is_reserve3
#:                     FROM event.registration_parts WHERE part_id = 3)
#:        AS part3 ON reg.id = part3.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.lodgements WHERE event_id=1)))
#:                     AS X(lodgement_id3 integer, contamination3 varchar))
#:        AS lodge_fields3 ON part3.lodgement_id3 = lodge_fields3.lodgement_id3
#:    LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id1, course_instructor AS course_instructor1
#:                     FROM event.registration_tracks WHERE track_id = 1)
#:        AS track1 ON reg.id = track1.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.courses WHERE event_id=1)))
#:                     AS X(course_id1 integer, room1 varchar))
#:        AS course_fields1 ON track1.course_id1 = course_fields1.course_id1
#:    LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id2, course_instructor AS course_instructor2
#:                     FROM event.registration_tracks WHERE track_id = 2)
#:        AS track2 ON reg.id = track2.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.courses WHERE event_id=1)))
#:                     AS X(course_id2 integer, room2 varchar))
#:        AS course_fields2 ON track2.course_id2 = course_fields2.course_id2
#:    LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id3, course_instructor AS course_instructor3
#:                     FROM event.registration_tracks WHERE track_id = 3)
#:        AS track3 ON reg.id = track3.registration_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.courses WHERE event_id=1)))
#:                     AS X(course_id3 integer, room3 varchar))
#:        AS course_fields3 ON track3.course_id3 = course_fields3.course_id3
#:    LEFT OUTER JOIN (SELECT persona_id, ctime AS creation_time
#:                     FROM event.log WHERE event_id = 1 AND code = 50)
#:        AS ctime ON ctime.persona_id = reg.persona_id
#:    LEFT OUTER JOIN (SELECT persona_id, MAX(ctime) AS modification_time
#:                     FROM event.log WHERE event_id = 1 AND code = 51 GROUP BY persona_id)
#:        AS mtime ON mtime.persona_id = reg.persona_id
#:    LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(
#:                         SELECT fields FROM event.registrations WHERE event_id=1)))
#:                     AS X(may_reserve boolean, lodge varchar, transportation varchar, brings_balls boolean, registration_id integer))
#:        AS reg_fields ON reg.id = reg_fields.registration_id 
_REGISTRATION_VIEW_TEMPLATE = glue(
    "event.registrations AS reg",
    "JOIN core.personas AS persona ON reg.persona_id = persona.id",
    "{part_tables}", ## per part details will be filled in here
    "{track_tables}", ## per track details will be filled in here
    "{creation_date}",
    "{modification_date}",
    "LEFT OUTER JOIN (SELECT * FROM",
        "json_to_recordset(to_json(array(",
            "SELECT fields FROM event.registrations WHERE event_id={event_id})))",
        "AS X({json_reg_fields})) AS reg_fields ON reg.id = reg_fields.registration_id",)

#: Version tag, so we know that we don't run out of sync with exported event
#: data
_CDEDB_EXPORT_EVENT_VERSION = 1

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
            raise ValueError(_("No input specified."))
        if event_id is not None and course_id is not None:
            raise ValueError(_("Too many inputs specified."))
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
        if event_id is None and course_id is None:
            raise ValueError(_("No input specified."))
        if event_id is not None and course_id is not None:
            raise ValueError(_("Too many inputs specified."))
        if event_id is not None:
            anid = affirm("id", event_id)
            query = "SELECT offline_lock FROM event.events WHERE id = %s"
        if course_id is not None:
            anid = affirm("id", course_id)
            query = glue(
                "SELECT offline_lock FROM event.events AS e",
                "LEFT OUTER JOIN event.courses AS c ON c.event_id = e.id",
                "WHERE c.id = %s")
        data = self.query_one(rs, query, (anid,))
        return data['offline_lock']

    def assert_offline_lock(self, rs, *, event_id=None, course_id=None):
        """Helper to check locking state of an event or course.

        This raises an exception in case of the wrong locking state Exactly
        one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int or None
        :type course_id: int or None
        """
        ## the following does the argument checking
        is_locked = self.is_offline_locked(rs, event_id=event_id,
                                           course_id=course_id)
        if is_locked != self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError(_("Event offline lock error."))

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
                     stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type event_id: int or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        event_id = affirm("id_or_None", event_id)
        if (not (event_id and self.is_orga(rs, event_id=event_id))
                and not self.is_admin(rs)):
            raise PrivilegeError(_("Not privileged."))
        return self.generic_retrieve_log(
            rs, "enum_eventlogcodes", "event", "event.log", codes, event_id,
            start, stop)

    @access("persona")
    def list_db_events(self, rs, visible_only=False):
        """List all events organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type visible_only: bool
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM event.events"
        if visible_only:
            query = glue(query, "WHERE is_visible = True")
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("persona")
    def list_visible_events(self, rs):
        """List all events which are visible and not archived.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: {str: object}}
        :returns: Mapping of event ids to infos (title and registration status).
        """
        with Atomizer(rs):
            query = glue(
                "SELECT e.id, e.registration_start, e.title, e.is_visible,",
                "MAX(p.part_end) AS event_end",
                "FROM event.events AS e JOIN event.event_parts AS p",
                "ON p.event_id = e.id",
                "WHERE e.is_visible AND NOT e.is_archived",
                "GROUP BY e.id")
            data = self.query_all(rs, query, tuple())
            return {e['id']: e['title'] for e in data}

    @access("persona")
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
                raise PrivilegeError(_("Not privileged."))
            event = self.get_event(rs, event_id)
            lodgement_fields = {
                e['field_name']: PYTHON_TO_SQL_MAP[e['kind']]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.lodgement
            }
            lodgement_fields['lodgement_id'] = PYTHON_TO_SQL_MAP["int"]
            json_lodge_fields_gen = lambda part_id: ", ".join(
                "{}{} {}".format(name, part_id, kind)
                for name, kind in lodgement_fields.items())
            part_table_template = glue(
                ## first the per part table
                "LEFT OUTER JOIN (SELECT registration_id, {part_columns}",
                "FROM event.registration_parts WHERE part_id = {part_id})",
                "AS part{part_id} ON reg.id = part{part_id}.registration_id",
                ## second the associated lodgement fields
                "LEFT OUTER JOIN (SELECT * FROM",
                "json_to_recordset(to_json(array(",
                "SELECT fields FROM event.lodgements WHERE event_id={event_id})))",
                "AS X({json_lodge_fields})) AS lodge_fields{part_id}",
                "ON part{part_id}.lodgement_id{part_id} = lodge_fields{part_id}.lodgement_id{part_id}",
            )
            part_atoms = ("status", "lodgement_id", "is_reserve")
            part_columns_gen = lambda part_id: ", ".join(
                "{col} AS {col}{part_id}".format(col=col, part_id=part_id)
                for col in part_atoms)
            course_fields = {
                e['field_name']: PYTHON_TO_SQL_MAP[e['kind']]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.course
            }
            course_fields['course_id'] = PYTHON_TO_SQL_MAP["int"]
            json_course_fields_gen = lambda track_id: ", ".join(
                "{}{} {}".format(name, track_id, kind)
                for name, kind in course_fields.items())
            track_table_template = glue(
                ## first the per track table
                "LEFT OUTER JOIN (SELECT registration_id, {track_columns}",
                "FROM event.registration_tracks WHERE track_id = {track_id})",
                "AS track{track_id} ON reg.id = track{track_id}.registration_id",
                ## second the associated course fields
                "LEFT OUTER JOIN (SELECT * FROM",
                "json_to_recordset(to_json(array(",
                "SELECT fields FROM event.courses WHERE event_id={event_id})))",
                "AS X({json_course_fields})) AS course_fields{track_id}",
                "ON track{track_id}.course_id{track_id} = course_fields{track_id}.course_id{track_id}",
            )
            track_atoms = ("course_id", "course_instructor",)
            track_columns_gen = lambda track_id: ", ".join(
                "{col} AS {col}{track_id}".format(col=col, track_id=track_id)
                for col in track_atoms)
            creation_date = glue(
                "LEFT OUTER JOIN (SELECT persona_id, ctime AS creation_time",
                "FROM event.log",
                "WHERE event_id = {event_id} AND code = {reg_create_code})",
                "AS ctime ON ctime.persona_id = reg.persona_id").format(
                    event_id=event_id,
                    reg_create_code=const.EventLogCodes.registration_created)
            modification_date = glue(
                "LEFT OUTER JOIN (SELECT persona_id, MAX(ctime) AS modification_time",
                "FROM event.log",
                "WHERE event_id = {event_id} AND code = {reg_mod_code}",
                "GROUP BY persona_id)",
                "AS mtime ON mtime.persona_id = reg.persona_id").format(
                    event_id=event_id,
                    reg_mod_code=const.EventLogCodes.registration_changed)
            reg_fields = {
                e['field_name']: PYTHON_TO_SQL_MAP[e['kind']]
                for e in event['fields'].values()
                if e['association'] == const.FieldAssociations.registration
            }
            reg_fields['registration_id'] = PYTHON_TO_SQL_MAP["int"]
            view = _REGISTRATION_VIEW_TEMPLATE.format(
                event_id=event_id,
                part_tables=" ".join(
                    part_table_template.format(
                        part_columns=part_columns_gen(part_id), part_id=part_id,
                        json_lodge_fields=json_lodge_fields_gen(part_id),
                        event_id=event_id)
                    for part_id in event['parts']),
                track_tables=" ".join(
                    track_table_template.format(
                        track_columns=track_columns_gen(track_id),
                        json_course_fields=json_course_fields_gen(track_id),
                        track_id=track_id, event_id=event_id)
                    for part in event['parts'].values()
                    for track_id in part['tracks']),
                creation_date=creation_date, modification_date=modification_date,
                json_reg_fields=", ".join(
                    "{} {}".format(name, kind) for name, kind in reg_fields.items()),
            )
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope == "qview_event_user":
            if not self.is_admin(rs):
                raise PrivilegeError(_("Admin only."))
            query.constraints.append(("is_event_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_event_realm"] = "bool"
            query.spec["is_archived"] = "bool"
        else:
            raise RuntimeError(_("Bad scope."))
        return self.general_query(rs, query, view=view)

    @access("event")
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
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = parts
            data = self.sql_select(rs, "event.course_tracks", COURSE_TRACK_FIELDS,
                                   all_parts, entity_key="part_id")
            for anid in ids:
                for part_id in ret[anid]['parts']:
                    tracks = {d['id']: d['title'] for d in data
                              if d['part_id'] == part_id}
                    assert('tracks' not in ret[anid]['parts'][part_id])
                    ret[anid]['parts'][part_id]['tracks'] = tracks
            data = self.sql_select(
                rs, "event.orgas", ("persona_id", "event_id"), ids,
                entity_key="event_id")
            for anid in ids:
                orgas = {d['persona_id'] for d in data if d['event_id'] == anid}
                assert('orgas' not in ret[anid])
                ret[anid]['orgas'] = orgas
            data = self.sql_select(
                rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
                ids, entity_key="event_id")
            for anid in ids:
                fields = {d['id']: d for d in data if d['event_id'] == anid}
                assert('fields' not in ret[anid])
                ret[anid]['fields'] = fields
        return ret

    def _set_tracks(self, rs, event_id, part_id, data, cautious=False):
        """Helper for handling of course tracks.

        This is basically uninlined code from ``set_event()``.

        :note: This has to be called inside an atomized context.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type part_id: int
        :type data: {int: str}
        :type cautious: bool
        :param cautious: If True only modification of existing tracks is
          allowed. That is creation and deletion of tracks is disallowed.
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
        current = {e['id']: e['title'] for e in current}
        existing = set(current)
        if not(existing >= {x for x in data if x > 0}):
            raise ValueError(_("Non-existing tracks specified."))
        new = {x for x in data if x < 0}
        updated = {x for x in data
                   if x > 0 and data[x] is not None}
        deleted = {x for x in data
                   if x > 0 and data[x] is None}
        if cautious and (new or deleted):
            raise ValueError(_("Registrations exist, only modifications."))
        ## new
        for x in reversed(sorted(new)):
            new_track = {
                "part_id": part_id,
                "title": data[x],
            }
            ret *= self.sql_insert(rs, "event.course_tracks", new_track)
            self.event_log(
                rs, const.EventLogCodes.track_added, event_id,
                additional_info=data[x])
        ## updated
        for x in updated:
            if current[x] != data[x]:
                update = {
                    'id': x,
                    'title': data[x],
                }
                ret *= self.sql_update(rs, "event.course_tracks", update)
                self.event_log(
                    rs, const.EventLogCodes.track_updated, event_id,
                    additional_info=data[x])

        ## deleted
        if deleted:
            ret *= self.sql_delete(rs, "event.course_tracks",
                                   deleted)
            for x in deleted:
                self.event_log(
                    rs, const.EventLogCodes.track_removed, event_id,
                    additional_info=data[x])
        return ret

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
            raise PrivilegeError(_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])
        ret = 1
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            if len(edata) > 1:
                indirect_fields = filter(
                    lambda x: x,
                    [edata.get('lodge_field'), edata.get('reserve_field')])
                if indirect_fields:
                    indirect_data = self.sql_select(
                        rs, "event.field_definitions",
                        ("id", "event_id", "kind", "association"),
                        indirect_fields)
                    correct_assoc = const.FieldAssociations.registration
                    if edata.get('lodge_field'):
                        lodge_data = unwrap(
                            [x for x in indirect_data
                             if x['id'] == edata['lodge_field']])
                        if (lodge_data['event_id'] != data['id']
                               or lodge_data['kind'] != "str"
                               or lodge_data['association'] != correct_assoc):
                            raise ValueError(_("Unfit field for lodge_field"))
                    if edata.get('reserve_field'):
                        reserve_data = unwrap(
                            [x for x in indirect_data
                             if x['id'] == edata['reserve_field']])
                        if (reserve_data['event_id'] != data['id']
                               or reserve_data['kind'] != "bool"
                               or reserve_data['association'] != correct_assoc):
                            raise ValueError(_("Unfit field for reserve_field"))
                ret *= self.sql_update(rs, "event.events", edata)
                self.event_log(rs, const.EventLogCodes.event_changed,
                               data['id'])
            if 'orgas' in data:
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
                if not(existing >= {x for x in parts if x > 0}):
                    raise ValueError(_("Non-existing parts specified."))
                new = {x for x in parts if x < 0}
                updated = {x for x in parts
                           if x > 0 and parts[x] is not None}
                deleted = {x for x in parts
                           if x > 0 and parts[x] is None}
                if has_registrations and (deleted or new):
                    raise ValueError(
                        _("Registrations exist, modifications only."))
                if deleted >= existing | new:
                    raise ValueError(_("At least one event part required."))
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
                    ret *= self._set_tracks(rs, data['id'], x, tracks,
                                            cautious=has_registrations)
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
                if not(existing >= {x for x in fields if x > 0}):
                    raise ValueError(_("Non-existing fields specified."))
                new = {x for x in fields if x < 0}
                updated = {x for x in fields
                           if x > 0 and fields[x] is not None}
                deleted = {x for x in fields
                           if x > 0 and fields[x] is None}
                current = self.sql_select(
                    rs, "event.field_definitions", ("id", "field_name"),
                    updated | deleted)
                field_names = {e['id']: e['field_name'] for e in current}
                ## new
                for x in new:
                    new_field = copy.deepcopy(fields[x])
                    new_field['event_id'] = data['id']
                    ret *= self.sql_insert(rs, "event.field_definitions",
                                           new_field)
                    self.event_log(
                        rs, const.EventLogCodes.field_added, data['id'],
                        additional_info=fields[x]['field_name'])
                ## updated
                for x in updated:
                    update = copy.deepcopy(fields[x])
                    update['id'] = x
                    ret *= self.sql_update(rs, "event.field_definitions",
                                           update)
                    self.event_log(
                        rs, const.EventLogCodes.field_updated, data['id'],
                        additional_info=field_names[x])

                ## deleted
                if deleted:
                    ret *= self.sql_delete(rs, "event.field_definitions",
                                           deleted)
                    for x in deleted:
                        self.event_log(
                            rs, const.EventLogCodes.field_removed, data['id'],
                            additional_info=field_names[x])
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
            raise ValueError(_("At least one event part required."))
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            new_id = self.sql_insert(rs, "event.events", edata)
            for aspect in ('parts', 'orgas', 'fields'):
                if aspect in data:
                    adata = {
                        'id': new_id,
                        aspect: data[aspect],
                    }
                    self.set_event(rs, adata)
        self.event_log(rs, const.EventLogCodes.event_created, new_id)
        return new_id

    @access("event")
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
            ret = {e['id']: e for e in data}
            event = None
            if ret:
                events = {e['event_id'] for e in data}
                if len(events) != 1:
                    raise ValueError(_(
                        "Only courses from exactly one event allowed!"))
                event = self.get_event(rs, unwrap(events))
            data = self.sql_select(
                rs, "event.course_segments", COURSE_SEGMENT_FIELDS, ids,
                entity_key="course_id")
            for anid in ids:
                segments = {p['track_id'] for p in data if p['course_id'] == anid}
                assert('segments' not in ret[anid])
                ret[anid]['segments'] = segments
                active_segments = {p['track_id'] for p in data
                                if p['course_id'] == anid and p['is_active']}
                assert('active_segments' not in ret[anid])
                ret[anid]['active_segments'] = active_segments
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'],
                                                  event['fields'])
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
            raise PrivilegeError(_("Not privileged."))
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            current = self.sql_select_one(rs, "event.courses",
                                          ("title", "event_id"), data['id'])
            event = self.get_event(rs, current['event_id'])
            if 'fields' in data:
                data['fields'] = affirm(
                    "event_associated_fields", data['fields'],
                    fields=event['fields'],
                    association=const.FieldAssociations.course)

            cdata = {k: v for k, v in data.items()
                     if k in COURSE_FIELDS and k != "fields"}
            changed = False
            if len(cdata) > 1:
                ret *= self.sql_update(rs, "event.courses", cdata)
                changed = True
            if 'fields' in data:
                fdata = unwrap(self.sql_select_one(rs, "event.courses",
                                                   ("fields",), data['id']))
                fdata.update(data['fields'])
                new = {
                    'id': data['id'],
                    'fields': PsycoJson(fdata),
                }
                ret *= self.sql_update(rs, "event.courses", new)
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
                    ## check, that all new tracks belong to the event of the
                    ## course
                    tracks = self.sql_select(
                        rs, "event.course_tracks", ("part_id",), new)
                    associated_parts = map(unwrap, tracks)
                    associated_events = self.sql_select(
                        rs, "event.event_parts", ("event_id",), associated_parts)
                    event_ids = {e['event_id'] for e in associated_events}
                    if {current['event_id']} != event_ids:
                        raise ValueError(_("Non-associated tracks found."))

                    for anid in new:
                        insert = {
                            'course_id': data['id'],
                            'track_id': anid,
                            'is_active': True,
                        }
                        ret *= self.sql_insert(rs, "event.course_segments", insert)
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
                ## check that all active segments are actual segments of this
                ## course
                if not existing >= data['active_segments']:
                    raise ValueError(_("Wrong-associated segments found."))
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
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            ## Check for existence of course tracks
            event = self.get_event(rs, data['event_id'])
            if not event_gather_tracks(event):
                raise RuntimeError(_("Event without tracks forbids courses"))

            cdata = {k: v for k, v in data.items() if k in COURSE_FIELDS}
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
            ## fix fields to contain course id
            fdata = {
                'id': new_id,
                'fields': PsycoJson({'course_id': new_id})
            }
            self.sql_update(rs, "event.courses", fdata)
        self.event_log(rs, const.EventLogCodes.course_created,
                       data['event_id'], additional_info=data['title'])
        return new_id

    @access("event")
    def list_registrations(self, rs, event_id, persona_id=None):
        """List all registrations of an event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type persona_id: int or None
        :param persona_id: If passed restrict to registrations by this persona.
        :rtype: {int: int}
        """
        event_id = affirm("id", event_id)
        persona_id = affirm("id_or_None", persona_id)
        if (persona_id != rs.user.persona_id
                and not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(_("Not privileged."))
        query = glue("SELECT id, persona_id FROM event.registrations",
                     "WHERE event_id = %s")
        params = (event_id,)
        if persona_id:
            query = glue(query, "AND persona_id = %s")
            params += (persona_id,)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event")
    def registrations_by_course(self, rs, event_id, course_id=None,
                                track_id=None, position=None, reg_ids=None):
        """List registrations of an event pertaining to a certain course.

        This is a filter function, mainly for the course assignment tool.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :type track_id: int or None
        :type course_id: int or None
        :type position: :py:class:`cdedb.common.CourseFilterPositions`
        :param reg_ids: List of registration ids to filter for
        :type reg_ids: [int] or None
        :rtype: {int: int}
        """
        event_id = affirm("id", event_id)
        track_id = affirm("id_or_None", track_id)
        course_id = affirm("id_or_None", course_id)
        position = affirm("enum_coursefilterpositions_or_None", position)
        reg_ids = reg_ids or set()
        reg_ids = affirm_set("id", reg_ids)
        if (not self.is_admin(rs)
                and not self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(_("Not privileged."))
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
            "WHERE regs.event_id = %s AND rparts.status = %s")
        params = (event_id, const.RegistrationPartStati.participant)
        if track_id:
            query = glue(query, "AND course_tracks.id = %s")
            params += (track_id,)
        if course_id:
            cfp = CourseFilterPositions
            if position is None:
                position = cfp.anywhere
            conditions = []
            if position in (cfp.instructor, cfp.anywhere):
                conditions.append("rtracks.course_instructor = %s")
                params += (course_id,)
            if position in (cfp.any_choice, cfp.anywhere):
                conditions.append("choices.course_id = %s")
                params += (course_id,)
            elif position in (cfp.first_choice, cfp.second_choice,
                              cfp.third_choice):
                conditions.append(
                    "(choices.course_id = %s AND choices.rank = %s)")
                if position == cfp.first_choice:
                    params += (course_id, 0)
                elif position == cfp.second_choice:
                    params += (course_id, 1)
                elif position == cfp.third_choice:
                    params += (course_id, 2)
            if position in (cfp.assigned, cfp.anywhere):
                conditions.append("rtracks.course_id = %s")
                params += (course_id,)
            condition = " OR ".join(conditions)
            query = glue(query, "AND (", condition, ")")
        if reg_ids:
            query = glue(query, "AND regs.id = ANY(%s)")
            params += (reg_ids,)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event")
    @singularize("get_registration")
    def get_registrations(self, rs, ids):
        """Retrieve data for some registrations.

        All have to be from the same event. You must be orga to access
        registrations which are not your own. This includes the following
        additional data:

        * parts: per part data (like lodgement),
        * tracks: per track data (like course choices)

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        if not ids:
            return {}
        with Atomizer(rs):
            associated = self.sql_select(rs, "event.registrations",
                                         ("persona_id", "event_id"), ids)
            events = {e['event_id'] for e in associated}
            personas = {e['persona_id'] for e in associated}
            if len(events) != 1:
                raise ValueError(_(
                    "Only registrations from exactly one event allowed!"))
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)
                    and not {rs.user.persona_id} >= personas):
                raise PrivilegeError(_("Not privileged."))

            ret = {e['id']: e for e in self.sql_select(
                rs, "event.registrations", REGISTRATION_FIELDS, ids)}
            event = self.get_event(rs, event_id)
            pdata = self.sql_select(
                rs, "event.registration_parts", REGISTRATION_PART_FIELDS, ids,
                entity_key="registration_id")
            for anid in ret:
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = {e['part_id']: e for e in pdata
                                      if e['registration_id'] == anid}
            tdata = self.sql_select(
                rs, "event.registration_tracks", REGISTRATION_TRACK_FIELDS, ids,
                entity_key="registration_id")
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"), ids,
                entity_key="registration_id")
            for anid in ret:
                assert('tracks' not in ret[anid])
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
                                                  event['fields'])
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
            raise PrivilegeError(_("Not privileged."))
        with Atomizer(rs):
            query = glue("SELECT COUNT(*) FROM event.registrations",
                         "WHERE event_id = %s LIMIT 1")
            return bool(unwrap(self.query_one(rs, query, (event_id,))))

    def _set_course_choices(self, rs, registration_id, track_id, choices,
                            courses):
        """Helper for handling of course choices.

        This is basically uninlined code from ``set_registration()``.

        :note: This has to be called inside an atomized context.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type registration_id: int
        :type track_id: int
        :type choices: [int]
        :type courses: {str: object}
        :rtype: int
        :returns: default return code
        """
        ret = 1
        if choices is None:
            ## Nothing specified, hence nothing to do
            return ret
        for course_id in choices:
            if track_id not in courses[course_id]['segments']:
                raise ValueError(_("Wrong track for course."))
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
                raise PrivilegeError(_("Not privileged."))
            event = self.get_event(rs, event_id)
            courses = self.get_courses(rs, self.list_db_courses(rs, event_id))

            if 'fields' in data:
                data['fields'] = affirm(
                    "event_associated_fields", data['fields'],
                    fields=event['fields'],
                    association=const.FieldAssociations.registration)

            ## now we get to do the actual work
            rdata = {k: v for k, v in data.items()
                     if k in REGISTRATION_FIELDS and k != "fields"}
            ret = 1
            if len(rdata) > 1:
                ret *= self.sql_update(rs, "event.registrations", rdata)
            if 'fields' in data:
                fdata = unwrap(self.sql_select_one(rs, "event.registrations",
                                                   ("fields",), data['id']))
                fdata.update(data['fields'])
                new = {
                    'id': data['id'],
                    'fields': PsycoJson(fdata),
                }
                ret *= self.sql_update(rs, "event.registrations", new)
            if 'parts' in data:
                parts = data['parts']
                if not(set(event['parts'].keys()) >= {x for x in parts}):
                    raise ValueError(_("Non-existing parts specified."))
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
                    raise NotImplementedError(_("This is not useful."))
            if 'tracks' in data:
                tracks = data['tracks']
                all_tracks = set(event_gather_tracks(event))
                if not(all_tracks >= set(tracks)):
                    raise ValueError(_("Non-existing tracks specified."))
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
                    self._set_course_choices(rs, data['id'], x, choices, courses)
                    new_track['registration_id'] = data['id']
                    new_track['track_id'] = x
                    ret *= self.sql_insert(rs, "event.registration_tracks",
                                           new_track)
                for x in updated:
                    update = copy.deepcopy(tracks[x])
                    choices = update.pop('choices', None)
                    self._set_course_choices(rs, data['id'], x, choices, courses)
                    update['id'] = existing[x]
                    ret *= self.sql_update(rs, "event.registration_tracks",
                                           update)
                if deleted:
                    raise NotImplementedError(_("This is not useful."))
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
        if (data['persona_id'] != rs.user.persona_id
                and not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            part_ids = {e['id'] for e in self.sql_select(
                rs, "event.event_parts", ("id",), (data['event_id'],),
                entity_key="event_id")}
            if part_ids != set(data['parts'].keys()):
                raise ValueError(_("Missing part dataset."))
            track_ids = {e['id'] for e in self.sql_select(
                rs, "event.course_tracks", ("id",), part_ids,
                entity_key="part_id")}
            if track_ids != set(data['tracks'].keys()):
                raise ValueError(_("Missing track dataset."))
            rdata = {k: v for k, v in data.items() if k in REGISTRATION_FIELDS}
            new_id = self.sql_insert(rs, "event.registrations", rdata)
            with Silencer(rs):
                for aspect in ('parts', 'tracks'):
                    if aspect in data:
                        adata = {
                            'id': new_id,
                            aspect: data[aspect]
                        }
                        self.set_registration(rs, adata)
            ## fix fields to contain registration id
            fdata = {
                'id': new_id,
                'fields': PsycoJson({'registration_id': new_id})
            }
            self.sql_update(rs, "event.registrations", fdata)
        self.event_log(
            rs, const.EventLogCodes.registration_created, data['event_id'],
            persona_id=data['persona_id'])
        return new_id

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
            raise PrivilegeError(_("Not privileged."))
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
        if not ids:
            return {}
        with Atomizer(rs):
            data = self.sql_select(rs, "event.lodgements", LODGEMENT_FIELDS,
                                   ids)
            events = {e['event_id'] for e in data}
            if len(events) != 1:
                raise ValueError(_(
                    "Only lodgements from exactly one event allowed!"))
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(_("Not privileged."))
            event = self.get_event(rs, event_id)
            ret = {e['id']: e for e in data}
            for entry in ret.values():
                entry['fields'] = cast_fields(entry['fields'], event['fields'])
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
                raise PrivilegeError(_("Not privileged."))
            self.assert_offline_lock(rs, event_id=event_id)
            event = self.get_event(rs, event_id)
            if 'fields' in data:
                data['fields'] = affirm(
                    "event_associated_fields", data['fields'],
                    fields=event['fields'],
                    association=const.FieldAssociations.lodgement)

            ## now we get to do the actual work
            ret = 1
            ldata = {k: v for k, v in data.items()
                     if k in LODGEMENT_FIELDS and k != "fields"}
            if len(ldata) > 1:
                ret *= self.sql_update(rs, "event.lodgements", ldata)
            if 'fields' in data:
                fdata = unwrap(self.sql_select_one(rs, "event.lodgements",
                                                   ("fields",), data['id']))
                fdata.update(data['fields'])
                new = {
                    'id': data['id'],
                    'fields': PsycoJson(fdata),
                }
                ret *= self.sql_update(rs, "event.lodgements", new)
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
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "event.lodgements", data)
            ## fix fields to contain lodgement id
            fdata = {
                'id': new_id,
                'fields': PsycoJson({'lodgement_id': new_id})
            }
            self.sql_update(rs, "event.lodgements", fdata)
            self.event_log(
                rs, const.EventLogCodes.lodgement_created, data['event_id'],
                additional_info=data['moniker'])
        return new_id

    @access("event")
    def delete_lodgement(self, rs, lodgement_id, cascade=False):
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
        cascade = affirm("bool", cascade)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "event.lodgements", ("event_id", "moniker"), lodgement_id)
            event_id, moniker = current['event_id'], current['moniker']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(_("Not privileged."))
            self.assert_offline_lock(rs, event_id=event_id)
            if cascade:
                reg_ids = self.list_registrations(rs, event_id)
                registrations = self.get_registrations(rs, reg_ids)
                for registration_id, registration in registrations.items():
                    update = {}
                    for part_id, part in registration['parts'].items():
                        if part['lodgement_id'] == lodgement_id:
                            update[part_id] = {'lodgement_id': None}
                    if update:
                        new_registration = {
                            'id': registration_id,
                            'parts': update
                        }
                        self.set_registration(rs, new_registration)
            ret = self.sql_delete_one(rs, "event.lodgements", lodgement_id)
            self.event_log(
                rs, const.EventLogCodes.lodgement_deleted, event_id,
                additional_info=moniker)
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
            ("field_id", "pos", "title", "info", "input_size", "readonly"),
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
        data = affirm("questionnaire", data)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(_("Not privileged."))
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
            raise PrivilegeError(_("Not privileged."))
        if self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError(_("It makes no sense to offline lock an event."))
        self.assert_offline_lock(rs, event_id=event_id)
        update = {
            'id': event_id,
            'offline_lock': True,
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
            raise PrivilegeError(_("Not privileged."))
        with Atomizer(rs):
            ret = {
                "CDEDB_EXPORT_EVENT_VERSION": _CDEDB_EXPORT_EVENT_VERSION,
                'id': event_id,
                'event.events': self.sql_select(
                    rs, "event.events", EVENT_FIELDS, (event_id,)),
                'timestamp': now(),
            }
            ## Table name; column to scan; fields to extract
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
            )
            personas = set()
            for table, id_name, columns in tables:
                if id_name == "event_id":
                    id_range = {event_id}
                elif id_name == "part_id":
                    id_range = set(e['id'] for e in ret['event.event_parts'])
                elif id_name == "track_id":
                    id_range = set(e['id'] for e in ret['event.course_tracks'])
                else:
                    id_range = None
                if 'id' not in columns:
                    columns += ('id',)
                ret[table] = self.sql_select(rs, table, columns, id_range,
                                             entity_key=id_name)
                ## Note the personas present to export them further on
                for e in ret[table]:
                    if e.get('persona_id'):
                        personas.add(e['persona_id'])
            ret['core.personas'] = self.sql_select(
                rs, "core.personas", PERSONA_EVENT_FIELDS, personas)
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
                ## All mappings have to be JSON columns in the database
                ## (nothing else should be possible).
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
        :type data: [{str: object}]
        :param data: Data set to put in.
        :type current: [{str: object}]
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
        dlookup = {e['id'] for e in data}
        for e in current:
            if e['id'] not in dlookup:
                ret *= self.sql_delete_one(rs, table, e['id'])
        clookup = {e['id']: e for e in current}
        for e in data:
            if e != clookup.get(e['id']):
                new_e = self.translate(e, translations, extra_translations)
                if e['id'] in clookup:
                    ret *= self.sql_update(rs, table, new_e)
                else:
                    if 'id' in new_e:
                        del new_e['id']
                    new_id = self.sql_insert(rs, table, new_e)
                    ret *= new_id
                    if entity:
                        translations[entity][e['id']] = new_id
        return ret

    @access("event_admin")
    def unlock_import_event(self, rs, data):
        """Unlock an event after offline usage and import changes.

        This is a combined action so that we stay consistent.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: dict
        :rtype: int
        :returns: standard return code
        """
        data = affirm("serialized_event", data)
        if self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError(_("It makes no sense to do this."))
        if not self.is_offline_locked(rs, event_id=data['id']):
            raise RuntimeError(_("Not locked."))
        if data["CDEDB_EXPORT_EVENT_VERSION"] != _CDEDB_EXPORT_EVENT_VERSION:
            raise ValueError(_("Version mismatch -- aborting."))

        with Atomizer(rs):
            current = self.export_event(rs, data['id'])
            ## First check that all newly created personas have been
            ## transferred to the online DB
            claimed = {e['persona_id'] for e in data['event.registrations']
                       if not e['real_persona_id']}
            if claimed - {e['id'] for e in current['core.personas']}:
                raise ValueError(_("Non-transferred persona found"))

            ret = 1
            ## Second synchronize the data sets
            translations = collections.defaultdict(dict)
            for reg in data['event.registrations']:
                if reg['real_persona_id']:
                    translations['persona_id'][reg['persona_id']] = \
                      reg['real_persona_id']
            extra_translations = {'course_instructor': 'course_id'}
            ## Table name; name of foreign keys referencing this table
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
                      ('event.questionnaire_rows', None))
            for table, entity in tables:
                ret *= self.synchronize_table(
                    rs, table, data[table], current[table], translations,
                    entity=entity, extra_translations=extra_translations)
            ## Third fix the ids embedded in json
            for entity in ('registration', 'lodgement', 'course'):
                id_string = '{}_id'.format(entity)
                table_string = 'event.{}s'.format(entity)
                for entity_id in translations[id_string].values():
                    json = self.sql_select_one(
                        rs, table_string, ('id', 'fields'), entity_id)
                    if json['fields'][id_string] != entity_id:
                        json['fields'][id_string] = entity_id
                        json['fields'] = PsycoJson(json['fields'])
                        self.sql_update(rs, table_string, json)
            ## Fourth unlock the event
            update = {
                'id': data['id'],
                'offline_lock': False,
            }
            ret *= self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_unlocked, data['id'])
            return ret
