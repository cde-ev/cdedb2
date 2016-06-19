#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy
import datetime

import psycopg2.extras

from cdedb.backend.common import (
    access, internal_access, affirm_validation as affirm, Silencer,
    affirm_array_validation as affirm_array, singularize, PYTHON_TO_SQL_MAP,
    AbstractBackend)
from cdedb.backend.cde import CdEBackend
from cdedb.common import (
    glue, PrivilegeError,
    EVENT_PART_FIELDS, EVENT_FIELDS, COURSE_FIELDS, REGISTRATION_FIELDS,
    REGISTRATION_PART_FIELDS, LODGEMENT_FIELDS, unwrap, now, ProxyShim,
    PERSONA_EVENT_FIELDS, INSTITUTION_FIELDS)
from cdedb.database.connection import Atomizer
from cdedb.query import QueryOperators
import cdedb.database.constants as const

#: This is used for generating the table for general queries for
#: registrations. We moved this rather huge blob here, so it doesn't
#: disfigure the query code.
#:
#: The end result may look something like the following::
#:
#:     event.registrations AS reg
#:     JOIN core.personas AS persona ON reg.persona_id = persona.id
#:     LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id1, status AS status1, lodgement_id AS lodgement_id1,
#:                             course_instructor AS course_instructor1 FROM event.registration_parts WHERE part_id = 1)
#:          AS part1 ON reg.id = part1.registration_id
#:     LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id2, status AS status2, lodgement_id AS lodgement_id2,
#:                             course_instructor AS course_instructor2 FROM event.registration_parts WHERE part_id = 2)
#:          AS part2 ON reg.id = part2.registration_id
#:     LEFT OUTER JOIN (SELECT registration_id, course_id AS course_id3, status AS status3, lodgement_id AS lodgement_id3,
#:                             course_instructor AS course_instructor3 FROM event.registration_parts WHERE part_id = 3)
#:          AS part3 ON reg.id = part3.registration_id
#:     LEFT OUTER JOIN (SELECT * FROM json_to_recordset(to_json(array(SELECT field_data FROM event.registrations)))
#:          AS X(registration_id int, brings_balls bool, transportation varchar)) AS fields ON reg.id = fields.registration_id
_REGISTRATION_VIEW_TEMPLATE = glue(
    "event.registrations AS reg",
    "JOIN core.personas AS persona ON reg.persona_id = persona.id",
    "{part_tables}", ## registration part details will be filled in here
    "LEFT OUTER JOIN (SELECT * FROM",
        "json_to_recordset(to_json(array(",
            "SELECT field_data FROM event.registrations)))",
        "AS X({json_fields})) AS fields ON reg.id = fields.registration_id")

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
            raise ValueError("No input specified.")
        if event_id is not None and course_id is not None:
            raise ValueError("Too many inputs specified.")
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
            raise ValueError("No input specified.")
        if event_id is not None and course_id is not None:
            raise ValueError("Too many inputs specified.")
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
            raise RuntimeError("Event offline lock error.")

    @access("persona")
    @singularize("orga_info")
    def orga_infos(self, rs, ids):
        """List events organized by specific personas.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_array("id", ids)
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
            raise PrivilegeError("Not privileged.")
        return self.generic_retrieve_log(
            rs, "enum_eventlogcodes", "event", "event.log", codes, event_id,
            start, stop)

    @access("persona")
    def list_db_events(self, rs):
        """List all events organized via DB.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM event.events"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("persona")
    def list_open_events(self, rs):
        """List all events which are open.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: {str: object}}
        :returns: Mapping of event ids to infos (title and registration status).
        """
        with Atomizer(rs):
            query = glue(
                "SELECT e.id, e.registration_start, e.title,",
                "MAX(p.part_end) AS event_end",
                "FROM event.events AS e JOIN event.event_parts AS p",
                "ON p.event_id = e.id WHERE registration_start IS NOT NULL",
                "GROUP BY e.id")
            data = self.query_all(rs, query, tuple())
            today = now().date()
            ret = {e['id']: e['title']
                   for e in data if (e['registration_start'] <= today
                                         and e['event_end'] is not None
                                         and e['event_end'] >= today)}
            return ret

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
                raise PrivilegeError("Not privileged.")
            event_data = self.get_event_data_one(rs, event_id)
            part_table_template = glue(
                "LEFT OUTER JOIN (SELECT registration_id, {part_data}",
                "FROM event.registration_parts WHERE part_id = {part_id})",
                "AS part{part_id} ON reg.id = part{part_id}.registration_id")
            part_data_columns = ("course_id", "status", "lodgement_id",
                                 "course_instructor",)
            part_data_gen = lambda part_id: ", ".join(
                "{col} AS {col}{part_id}".format(col=col, part_id=part_id)
                for col in part_data_columns)
            view = _REGISTRATION_VIEW_TEMPLATE.format(
                part_tables=" ".join(
                    part_table_template.format(
                        part_data=part_data_gen(part_id), part_id=part_id)
                    for part_id in event_data['parts']),
                json_fields=", ".join(("registration_id int", ", ".join(
                    "{} {}".format(e['field_name'],
                                   PYTHON_TO_SQL_MAP[e['kind']])
                    for e in event_data['fields'].values()))))
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "id"
        elif query.scope == "qview_event_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(("is_event_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_archived"] = "bool"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query, view=view)

    @access("event")
    @singularize("get_event_data_one")
    def get_event_data(self, rs, ids):
        """Retrieve data for some events organized via DB.

        This queries quite a lot of additional tables since there is quite
        some data attached to such an event. Namely we have additional data on:

        * parts,
        * orgas,
        * fields.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.events", EVENT_FIELDS, ids)
            ret = {e['id']: e for e in data}
            data = self.sql_select(rs, "event.event_parts", EVENT_PART_FIELDS,
                                   ids, entity_key="event_id")
            for anid in ids:
                parts = {d['id']: d for d in data if d['event_id'] == anid}
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = parts
            data = self.sql_select(
                rs, "event.orgas", ("persona_id", "event_id"), ids,
                entity_key="event_id")
            for anid in ids:
                orgas = {d['persona_id'] for d in data if d['event_id'] == anid}
                assert('orgas' not in ret[anid])
                ret[anid]['orgas'] = orgas
            data = self.sql_select(
                rs, "event.field_definitions",
                ("id", "event_id", "field_name", "kind", "entries"), ids,
                entity_key="event_id")
            for anid in ids:
                fields = {d['id']: d for d in data if d['event_id'] == anid}
                assert('fields' not in ret[anid])
                ret[anid]['fields'] = fields
        return ret

    @access("event")
    def set_event_data(self, rs, data):
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("event_data", data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['id'])
        ret = 1
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            if len(edata) > 1:
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
                current = self.sql_select(rs, "event.event_parts", ("id",),
                                          (data['id'],), entity_key="event_id")
                existing = {unwrap(e) for e in current}
                if not(existing >= {x for x in parts if x > 0}):
                    raise ValueError("Non-existing parts specified.")
                new = {x for x in parts if x < 0}
                updated = {x for x in parts
                           if x > 0 and parts[x] is not None}
                deleted = {x for x in parts
                           if x > 0 and parts[x] is None}
                for x in new:
                    new_part = copy.deepcopy(parts[x])
                    new_part['event_id'] = data['id']
                    ret *= self.sql_insert(rs, "event.event_parts", new_part)
                    self.event_log(
                        rs, const.EventLogCodes.part_created, data['id'],
                        additional_info=new_part['title'])
                current = self.sql_select(
                    rs, "event.event_parts", ("id", "title"), updated | deleted)
                titles = {e['id']: e['title'] for e in current}
                for x in updated:
                    update = copy.deepcopy(parts[x])
                    update['id'] = x
                    ret *= self.sql_update(rs, "event.event_parts", update)
                    self.event_log(
                        rs, const.EventLogCodes.part_changed, data['id'],
                        additional_info=titles[x])
                if deleted:
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
                    raise ValueError("Non-existing fields specified.")
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
        data = affirm("event_data", data, creation=True)
        with Atomizer(rs):
            edata = {k: v for k, v in data.items() if k in EVENT_FIELDS}
            new_id = self.sql_insert(rs, "event.events", edata)
            for aspect in ('parts', 'orgas', 'fields'):
                if aspect in data:
                    adata = {
                        'id': new_id,
                        aspect: data[aspect],
                    }
                    self.set_event_data(rs, adata)
        self.event_log(rs, const.EventLogCodes.event_created, new_id)
        return new_id

    @access("event")
    @singularize("get_course_data_one")
    def get_course_data(self, rs, ids):
        """Retrieve data for some courses organized via DB.

        They do not need to be associated to the same event. This contains
        additional information on the parts in which the course takes place.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.courses", COURSE_FIELDS, ids)
            ret = {e['id']: e for e in data}
            data = self.sql_select(
                rs, "event.course_parts", ("part_id", "course_id"), ids,
                entity_key="course_id")
            for anid in ids:
                parts = {p['part_id'] for p in data if p['course_id'] == anid}
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = parts
        return ret

    @access("event")
    def set_course_data(self, rs, data):
        """Update some keys of a course linked to an event organized via DB.

        If the 'parts' key is present you have to pass the complete list
        of part IDs, which will superseed the current list of parts.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("course_data", data)
        if not self.is_orga(rs, course_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            current = self.sql_select_one(rs, "event.courses",
                                          ("title", "event_id"), data['id'])
            cdata = {k: v for k, v in data.items() if k in COURSE_FIELDS}
            if len(cdata) > 1:
                ret *= self.sql_update(rs, "event.courses", cdata)
                self.event_log(
                    rs, const.EventLogCodes.course_changed, current['event_id'],
                    additional_info=current['title'])
            if 'parts' in data:
                current_parts = self.sql_select(
                    rs, "event.course_parts", ("part_id",), (data['id'],),
                    entity_key="course_id")
                existing = {e['part_id'] for e in current_parts}
                new = data['parts'] - existing
                deleted = existing - data['parts']
                if new:
                    ## check, that all new parts belong to the event of the
                    ## course
                    associated_events = self.sql_select(
                        rs, "event.event_parts", ("event_id",), new)
                    event_ids = {e['event_id'] for e in associated_events}
                    if {current['event_id']} != event_ids:
                        raise ValueError("Non-associated parts found.")

                    for anid in new:
                        new_data = {
                            'course_id': data['id'],
                            'part_id': anid,
                        }
                        ret *= self.sql_insert(rs, "event.course_parts",
                                               new_data)
                if deleted:
                    query = glue("DELETE FROM event.course_parts",
                                 "WHERE course_id = %s AND part_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deleted))
                if new or deleted:
                    self.event_log(
                        rs, const.EventLogCodes.course_parts_changed,
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
        data = affirm("course_data", data, creation=True)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            cdata = {k: v for k, v in data.items() if k in COURSE_FIELDS}
            new_id = self.sql_insert(rs, "event.courses", cdata)
            if 'parts' in data:
                pdata = {
                    'id': new_id,
                    'parts': data['parts'],
                }
                self.set_course_data(rs, pdata)
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
        :rtype: {int: {str: object}}
        """
        event_id = affirm("id", event_id)
        persona_id = affirm("id_or_None", persona_id)
        if (persona_id != rs.user.persona_id
                and not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        query = glue("SELECT id, persona_id FROM event.registrations",
                     "WHERE event_id = %s")
        params = (event_id,)
        if persona_id:
            query = glue(query, "AND persona_id = %s")
            params += (persona_id,)
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
        * choices: course choices, also per part.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        if not ids:
            return {}
        with Atomizer(rs):
            associated = self.sql_select(rs, "event.registrations",
                                         ("persona_id", "event_id"), ids)
            events = {e['event_id'] for e in associated}
            personas = {e['persona_id'] for e in associated}
            if len(events) != 1:
                raise ValueError(
                    "Only registrations from exactly one event allowed!")
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)
                    and not {rs.user.persona_id} >= personas):
                raise PrivilegeError("Not privileged.")

            ret = {e['id']: e for e in self.sql_select(
                rs, "event.registrations", REGISTRATION_FIELDS, ids)}
            data = self.sql_select(
                rs, "event.registration_parts", REGISTRATION_PART_FIELDS, ids,
                entity_key="registration_id")
            for anid in ret:
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = {e['part_id']: e for e in data
                                      if e['registration_id'] == anid}
            data = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "part_id", "course_id", "rank"), ids,
                entity_key="registration_id")
            parts = {e['part_id'] for e in data}
            for anid in ret:
                assert('choices' not in ret[anid])
                choices = {}
                for part_id in parts:
                    ranks = {e['course_id']: e['rank'] for e in data
                             if (e['registration_id'] == anid
                                 and e['part_id'] == part_id)}
                    choices[part_id] = sorted(ranks.keys(), key=ranks.get)
                ret[anid]['choices'] = choices
        return ret

    @access("event")
    def set_registration(self, rs, data):
        """Update some keys of a registration.

        The syntax for updating the non-trivial keys field_data, parts and
        choices is as follows:

        * If the key 'field_data' is present it must be a dict and is used to
          updated the stored value (in a python dict.update sense).
        * If the key 'parts' is present, the associated dict mapping the
          part ids to the respective data sets can contain an arbitrary
          number of entities, absent entities are not modified. Entries are
          created/updated as applicable.
        * If the key 'choices' is present the associated dict mapping the
          part ids to the choice lists can contain an arbitrary number of
          entries. Each supplied lists superseeds the current choice list
          for that part.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("registration_data", data)
        current = self.sql_select_one(
            rs, "event.registrations", ("persona_id", "event_id"), data['id'])
        persona_id, event_id = current['persona_id'], current['event_id']
        with Atomizer(rs):
            self.assert_offline_lock(rs, event_id=event_id)
            if (persona_id != rs.user.persona_id
                    and not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
            event_data = self.get_event_data_one(rs, event_id)
            if 'field_data' in data:
                data['field_data'] = affirm(
                    "registration_field_data", data['field_data'],
                    fields=event_data['fields'])

            ## now we get to do the actual work
            rdata = {k: v for k, v in data.items()
                     if k in REGISTRATION_FIELDS and k != "field_data"}
            ret = 1
            if len(rdata) > 1:
                ret *= self.sql_update(rs, "event.registrations", rdata)
            if 'field_data' in data:
                fdata = unwrap(self.sql_select_one(rs, "event.registrations",
                                                   ("field_data",), data['id']))
                fdata.update(data['field_data'])
                new_data = {
                    'id': data['id'],
                    'field_data': psycopg2.extras.Json(fdata),
                }
                ret *= self.sql_update(rs, "event.registrations", new_data)
            if 'parts' in data:
                parts = data['parts']
                if not(set(event_data['parts'].keys()) >= {x for x in parts}):
                    raise ValueError("Non-existing parts specified.")
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
                    raise NotImplementedError("This is not useful.")
            if 'choices' in data:
                choices = data['choices']
                if not(set(event_data['parts'].keys()) >= {x for x in choices}):
                    raise ValueError("Non-existing parts specified in choices.")
                all_courses = {x for l in choices.values() for x in l}
                course_data = self.get_course_data(rs, all_courses)
                for part_id in choices:
                    for course_id in choices[part_id]:
                        if part_id not in course_data[course_id]['parts']:
                            raise ValueError("Wrong part for course.")
                    query = glue("DELETE FROM event.course_choices",
                                 "WHERE registration_id = %s AND part_id = %s")
                    self.query_exec(rs, query, (data['id'], part_id))
                    for rank, course_id in enumerate(choices[part_id]):
                        new_choice = {
                            "registration_id": data['id'],
                            "part_id": part_id,
                            "course_id": course_id,
                            "rank": rank,
                        }
                        ret *= self.sql_insert(rs, "event.course_choices",
                                               new_choice)
        self.event_log(
            rs, const.EventLogCodes.registration_changed, event_id,
            persona_id=persona_id)
        return ret

    @access("event")
    def create_registration(self, rs, data):
        """Make a new registration.

        The data must contain a dataset for each part and may not contain a
        value for 'field_data', which is initialized to a default value.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new registration
        """
        data = affirm("registration_data", data, creation=True)
        if (data['persona_id'] != rs.user.persona_id
                and not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            part_ids = {e['id'] for e in self.sql_select(
                rs, "event.event_parts", ("id",), (data['event_id'],),
                entity_key="event_id")}
            if part_ids != set(data['parts'].keys()):
                raise ValueError("Missing part dataset.")
            rdata = {k: v for k, v in data.items() if k in REGISTRATION_FIELDS}
            new_id = self.sql_insert(rs, "event.registrations", rdata)
            for aspect in ('parts', 'choices'):
                if aspect in data:
                    new_data = {
                        'id': new_id,
                        aspect: data[aspect]
                    }
                    self.set_registration(rs, new_data)
            ## fix field_data to contain registration id
            fdata = {
                'id': new_id,
                'field_data': psycopg2.extras.Json({'registration_id': new_id})
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
            raise PrivilegeError("Not privileged.")
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
        ids = affirm_array("id", ids)
        if not ids:
            return {}
        with Atomizer(rs):
            data = self.sql_select(rs, "event.lodgements", LODGEMENT_FIELDS,
                                   ids)
            events = {e['event_id'] for e in data}
            if len(events) != 1:
                raise ValueError(
                    "Only lodgements from exactly one event allowed!")
            event_id = unwrap(events)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
        return {e['id']: e for e in data}

    @access("event")
    def set_lodgement(self, rs, data):
        """Update some keys of a lodgement.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("lodgement_data", data)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "event.lodgements", ("event_id", "moniker"), data['id'])
            event_id, moniker = current['event_id'], current['moniker']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
            self.assert_offline_lock(rs, event_id=event_id)
            ret = self.sql_update(rs, "event.lodgements", data)
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
        data = affirm("lodgement_data", data, creation=True)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['event_id'])
        ret = self.sql_insert(rs, "event.lodgements", data)
        self.event_log(
            rs, const.EventLogCodes.lodgement_created, data['event_id'],
            additional_info=data['moniker'])
        return ret

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
                raise PrivilegeError("Not privileged.")
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
        data = affirm("questionnaire_data", data)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
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
            raise PrivilegeError("Not privileged.")
        if self.conf.CDEDB_OFFLINE_DEPLOYMENT:
            raise RuntimeError("It makes no sense to offline lock an event.")
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: dict
        :returns: dict holding all data of the exported event
        """
        event_id = affirm("id", event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        with Atomizer(rs):
            ret = {
                "CDEDB_EXPORT_EVENT_VERSION": _CDEDB_EXPORT_EVENT_VERSION,
                'id': event_id,
                'event.events': self.sql_select(
                        rs, "event.events", EVENT_FIELDS, (event_id,)),
                'timestamp': now(),
            }
            ret['event.event_parts'] = self.sql_select(
                rs, 'event.event_parts', EVENT_PART_FIELDS, (event_id,),
                entity_key="event_id")
            parts = set(e['id'] for e in ret['event.event_parts'])
            tables = (
                ('event.courses', "event_id", COURSE_FIELDS),
                ('event.course_parts', "part_id", (
                    'id', 'course_id', 'part_id',)),
                ('event.orgas', "event_id", (
                    'id', 'persona_id', 'event_id',)),
                ('event.field_definitions', "event_id", (
                    'id', 'event_id', 'field_name', 'kind', 'entries',)),
                ('event.lodgements', "event_id", LODGEMENT_FIELDS),
                ('event.registrations', "event_id", REGISTRATION_FIELDS),
                ('event.registration_parts', "part_id",
                 REGISTRATION_PART_FIELDS),
                ('event.course_choices', "part_id", (
                    'id', 'registration_id', 'part_id', 'course_id', 'rank',)),
                ('event.questionnaire_rows', "event_id", (
                    'id', 'event_id', 'field_id', 'pos', 'title', 'info',
                    'input_size', 'readonly',)),
            )
            personas = set()
            for table, id_name, columns in tables:
                id_range = {event_id} if id_name == "event_id" else parts
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
                ret[x] = psycopg2.extras.Json(
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
            raise RuntimeError("It makes no sense to do this.")
        if not self.is_offline_locked(rs, event_id=data['id']):
            raise RuntimeError("Not locked.")
        if data["CDEDB_EXPORT_EVENT_VERSION"] != _CDEDB_EXPORT_EVENT_VERSION:
            raise ValueError("Version mismatch -- aborting.")

        with Atomizer(rs):
            current = self.export_event(rs, data['id'])
            ## First check that all newly created personas have been
            ## transferred to the online DB
            claimed = {e['persona_id'] for e in data['event.registrations']
                       if not e['real_persona_id']}
            if claimed - {e['id'] for e in current['core.personas']}:
                raise ValueError("Non-transferred persona found")

            ret = 1
            ## Second synchronize the data sets
            translations = collections.defaultdict(dict)
            for reg in data['event.registrations']:
                if reg['real_persona_id']:
                    translations['persona_id'][reg['persona_id']] = \
                      reg['real_persona_id']
            extra_translations = {'course_instructor': 'course_id'}
            tables = (('event.events', None),
                      ('event.event_parts', 'part_id'),
                      ('event.courses', 'course_id'),
                      ('event.course_parts', None),
                      ('event.orgas', None),
                      ('event.field_definitions', 'field_id'),
                      ('event.lodgements', 'lodgement_id'),
                      ('event.registrations', 'registration_id'),
                      ('event.registration_parts', None),
                      ('event.course_choices', None),
                      ('event.questionnaire_rows', None))
            for table, entity in tables:
                ret *= self.synchronize_table(
                    rs, table, data[table], current[table], translations,
                    entity=entity, extra_translations=extra_translations)
            ## Third fix the ids embedded in json
            for reg_id in translations['registration_id'].values():
                json = self.sql_select_one(
                    rs, 'event.registrations', ('id', 'field_data'), reg_id)
                if json['field_data']['registration_id'] != reg_id:
                    json['field_data']['registration_id'] = reg_id
                    json['field_data'] = psycopg2.extras.Json(json['field_data'])
                    self.sql_update(rs, 'event.registrations', json)
            ## Fourth unlock the event
            update = {
                'id': data['id'],
                'offline_lock': False,
            }
            ret *= self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_unlocked, data['id'])
            return ret
