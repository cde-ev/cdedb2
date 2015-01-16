#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize, AuthShim, PYTHON_TO_SQL_MAP)
from cdedb.backend.cde import CdEBackend
from cdedb.common import (
    glue, EVENT_USER_DATA_FIELDS, PAST_EVENT_FIELDS, PAST_COURSE_FIELDS,
    PERSONA_DATA_FIELDS, PrivilegeError, EVENT_PART_FIELDS, EVENT_FIELDS,
    COURSE_FIELDS, COURSE_FIELDS, REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS,
    LODGMENT_FIELDS)
from cdedb.config import Config
from cdedb.database.connection import Atomizer
from cdedb.query import QueryOperators
import cdedb.database.constants as const
import argparse
import datetime
import psycopg2.extras

#: This is used for generating the table for general queries for
#: registrations. We moved this rather huge blob here, so it doesn't
#: disfigure the query code.
#:
#: The end result may look something like the following::
#:
#:     event.registrations AS reg
#:     JOIN core.personas AS persona ON reg.persona_id = persona.id
#:     JOIN (
#:           (SELECT persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile,
#:                   address_supplement, address, postal_code, location, country FROM cde.member_data)
#:           UNION
#:           (SELECT persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile,
#:                   address_supplement, address, postal_code, location, country FROM event.user_data)
#:          ) AS user_data ON reg.persona_id = user_data.persona_id
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
    "JOIN ((SELECT {user_data} FROM cde.member_data)",
        "UNION (SELECT {user_data} FROM event.user_data))",
        "AS user_data ON reg.persona_id = user_data.persona_id",
    "{part_tables}", ## registration part details will be filled in here
    "LEFT OUTER JOIN (SELECT * FROM",
        "json_to_recordset(to_json(array(",
            "SELECT field_data FROM event.registrations)))",
        "AS X({json_fields})) AS fields ON reg.id = fields.registration_id")

class EventBackend(AbstractUserBackend):
    """Take note of the fact that some personas are orgas and thus have
    additional actions available."""
    realm = "event"
    user_management = {
        "data_table": "event.user_data",
        "data_fields": EVENT_USER_DATA_FIELDS,
        "validator": "event_user_data",
        "user_status": const.PersonaStati.event_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cde = AuthShim(CdEBackend(configpath))

    def establish(self, sessionkey, method, allow_internal=False):
        ret = super().establish(sessionkey, method,
                                allow_internal=allow_internal)
        if ret and ret.user.is_persona:
            ret.user.orga = self.orga_infos(
                ret, (ret.user.persona_id,))[ret.user.persona_id]
        return ret

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def is_orga(self, rs, *, event_id=None, course_id=None):
        """Check for orga privileges as specified in the event.orgas table.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int or None
        :type course_id: int or None
        :rtype: bool
        """
        if event_id is None and course_id is None:
            raise ValueError("No input specified.")
        if event_id is not None and course_id is not None:
            raise ValueError("Too many inputs specified.")
        if course_id is not None:
            query = "SELECT event_id FROM event.courses WHERE id = %s"
            event_id = self.query_one(rs, query, (course_id,))['event_id']
        return event_id in rs.user.orga

    @access("event_user")
    def is_offline_locked(self, rs, *, event_id=None, course_id=None):
        """Helper to determine if an event or course is locked for offline
        usage.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int or None
        :type course_id: int or None
        :rtype: bool
        """
        if event_id is None and course_id is None:
            raise ValueError("No input specified.")
        if event_id is not None and course_id is not None:
            raise ValueError("Too many inputs specified.")
        if event_id is not None:
            anid = affirm("int", event_id)
            query = "SELECT offline_lock FROM event.events WHERE id = %s"
        if course_id is not None:
            anid = affirm("int", course_id)
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_array("int", ids)
        query = glue("SELECT persona_id, event_id FROM event.orgas",
                     "WHERE persona_id = ANY(%s)")
        data = self.query_all(rs, query, (ids,))
        ret = {}
        for anid in ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    @access("event_user")
    @singularize("participation_info")
    def participation_infos(self, rs, ids):
        """List concluded events visited by specific personas.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: [dict]}
        :returns: Keys are the ids and items are the event lists.
        """
        ids = affirm_array("int", ids)
        query = glue(
            "SELECT p.persona_id, p.event_id, e.title AS event_name,",
            "p.course_id, c.title AS course_name, p.is_instructor, p.is_orga",
            "FROM past_event.participants AS p",
            "INNER JOIN past_event.events AS e ON (p.event_id = e.id)",
            "LEFT OUTER JOIN past_event.courses AS c ON (p.course_id = c.id)",
            "WHERE p.persona_id = ANY(%s) ORDER BY p.event_id")
        event_data = self.query_all(rs, query, (ids,))
        ret = {}
        for anid in ids:
            ret[anid] = tuple(x for x in event_data if x['persona_id'] == anid)
        return ret

    @access("event_user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("event_user")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        return super().get_data(rs, ids)

    @access("event_admin")
    def create_user(self, rs, data):
        return super().create_user(rs, data)

    @access("anonymous")
    def genesis_check(self, rs, case_id, secret, username=None):
        return super().genesis_check(rs, case_id, secret, username=username)

    @access("anonymous")
    def genesis(self, rs, case_id, secret, data):
        return super().genesis(rs, case_id, secret, data)

    @access("event_user")
    @singularize("acquire_data_one")
    def acquire_data(self, rs, ids):
        """Return user data sets.

        This is somewhat like :py:meth:`get_data`, but more general in
        that it allows ids from event and cde realm and dispatches the
        request to the correct place. Thus this is the default way to
        obtain persona data pertaining to a registration.

        This has the special behaviour that it can retrieve cde member
        datasets without interacting with the quota mechanism. Thus
        usage should be limited privileged users (basically orgas).

        .. warning:: It is impossible to atomize this operation. Since this
          allows a non-member to retrieve member data we have to escalate
          privileges (which happens in
          :py:meth:`cdedb.backend.cde.CdEBackend.get_data_no_quota`) thus
          breaking any attempt at atomizing.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        realms = self.core.get_realms(rs, ids)
        ret = {}
        ids_event = tuple(anid for anid in realms if realms[anid] == "event")
        if ids_event:
            ret.update(self.get_data(rs, ids_event))
        ids_cde = tuple(anid for anid in realms if realms[anid] == "cde")
        if ids_cde:
            ## filter fields, so that we do not leak cde internal stuff
            tmp = self.cde.get_data_no_quota(rs, ids_cde)
            temp = {key: {k: v for k, v in value.items()
                          if k in PERSONA_DATA_FIELDS + EVENT_USER_DATA_FIELDS}
                    for key, value in tmp.items()}
            ret.update(temp)
        return ret

    @access("persona")
    def list_events(self, rs, past):
        """List all events, either concluded or organized via DB.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type past: bool
        :param past: Select whether to list past events or those organized via
          DB.
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        if past:
            schema = "past_event"
        else:
            schema = "event"
        query = "SELECT id, title FROM {}.events".format(schema)
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("persona")
    def sidebar_events(self, rs):
        """List all events which appear in the sidebar.

        That is all which are currently under way and furthermore all which
        are orga'd by this persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :rtype: {int: {str: object}}
        :returns: Mapping of event ids to infos (title and registration status).
        """
        with Atomizer(rs):
            ## outer join, so we catch all events orga'd
            query = glue(
                "SELECT e.id, e.registration_start, e.use_questionnaire,",
                "e.title, MAX(p.part_end) AS event_end FROM event.events AS e",
                "LEFT OUTER JOIN event.event_parts AS p ON p.event_id = e.id",
                "WHERE registration_start IS NOT NULL GROUP BY e.id")
            data = self.query_all(rs, query, tuple())
            today = datetime.datetime.now().date()
            ret = {e['id']: {"title": e['title'],
                             "use_questionnaire": e["use_questionnaire"]}
                   for e in data if (e['id'] in rs.user.orga
                                     or (e['registration_start'] <= today
                                         and e['event_end'] is not None
                                         and e['event_end'] >= today))}
            query = glue("SELECT event_id FROM event.registrations",
                         "WHERE event_id = ANY(%s)")
            data = self.query_all(rs, query, (tuple(ret.keys()),))
            registered = {e['event_id'] for e in data}
            for event_id in ret:
                ret[event_id]["registered"] = (event_id in registered)
            return ret

    @access("persona")
    def list_courses(self, rs, event_id, past):
        """List all courses of an event either concluded or organized via DB.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :type past: bool
        :param past: Select whether to list past events or those organized via
          DB.
        :rtype: {int: str}
        :returns: Mapping of course ids to titles.
        """
        event_id = affirm("int", event_id)
        if past:
            schema = "past_event"
        else:
            schema = "event"
        query = "SELECT id, title FROM {}.courses WHERE event_id = %s"
        query = query.format(schema)
        data = self.query_all(rs, query, (event_id,))
        return {e['id']: e['title'] for e in data}

    @access("event_user")
    def submit_general_query(self, rs, query, event_id=None):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :type event_id: int or None
        :param event_id: For registration queries, specify the event.
        :rtype: [{str: object}]
        """
        query = affirm("serialized_query", query)
        view = None
        if query.scope == "qview_registration":
            event_id = affirm("int", event_id)
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
            event_data = self.get_event_data_one(rs, event_id)
            user_data_columns = (
                "persona_id", "family_name", "given_names", "title",
                "name_supplement", "gender", "birthday", "telephone",
                "mobile", "address_supplement", "address", "postal_code",
                "location", "country",)
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
                user_data=", ".join(user_data_columns),
                part_tables=" ".join(part_table_template.format(
                    part_data=part_data_gen(part_id), part_id=part_id)
                    for part_id in event_data['parts']),
                json_fields=", ".join(("registration_id int", ", ".join(
                    "{} {}".format(e['field_name'],
                                   PYTHON_TO_SQL_MAP[e['kind']])
                    for e in event_data['fields'].values()))))
            query.constraints.append(("event_id", QueryOperators.equal,
                                      event_id))
            query.spec['event_id'] = "int"
        elif query.scope == "qview_event_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(("status", QueryOperators.equal,
                                      const.PersonaStati.event_user))
            query.spec['status'] = "int"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query, view=view)

    @access("event_user")
    @singularize("get_past_event_data_one")
    def get_past_event_data(self, rs, ids):
        """Retrieve data for some concluded events.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        query = "SELECT {} FROM past_event.events WHERE id = ANY(%s)".format(
            ", ".join(PAST_EVENT_FIELDS))
        data = self.query_all(rs, query, (ids,))
        return {e['id']: e for e in data}

    @access("event_user")
    @singularize("get_event_data_one")
    def get_event_data(self, rs, ids):
        """Retrieve data for some events organized via DB.

        This queries quite a lot of additional tables since there is quite
        some data attached to such an event. Namely we have additional data on:

        * parts,
        * orgas,
        * fields.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        with Atomizer(rs):
            query = "SELECT {} FROM event.events WHERE id = ANY(%s)"
            query = query.format(", ".join(EVENT_FIELDS))
            data = self.query_all(rs, query, (ids,))
            ret = {e['id']: e for e in data}
            query = "SELECT {} FROM event.event_parts WHERE event_id = ANY(%s)"
            query = query.format(", ".join(EVENT_PART_FIELDS))
            data = self.query_all(rs, query, (ids,))
            for anid in ids:
                parts = {d['id']: d for d in data if d['event_id'] == anid}
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = parts
            query = glue("SELECT persona_id, event_id FROM event.orgas",
                         "WHERE event_id = ANY(%s)")
            data = self.query_all(rs, query, (ids,))
            for anid in ids:
                orgas = {d['persona_id'] for d in data if d['event_id'] == anid}
                assert('orgas' not in ret[anid])
                ret[anid]['orgas'] = orgas
            query = glue(
                "SELECT id, event_id, field_name, kind, entries",
                "FROM event.field_definitions WHERE event_id = ANY(%s)")
            data = self.query_all(rs, query, (ids,))
            for anid in ids:
                fields = {d['id']: d for d in data if d['event_id'] == anid}
                assert('fields' not in ret[anid])
                ret[anid]['fields'] = fields
        return ret

    @access("event_admin")
    def set_past_event_data(self, rs, data):
        """Update some keys of a concluded event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: number of changed entries
        """
        data = affirm("past_event_data", data)
        keys = tuple(data.keys())
        query = "UPDATE past_event.events SET ({}) = ({}) WHERE id = %s".format(
            ", ".join(keys), ", ".join(("%s",) * len(keys)))
        params = tuple(data[key] for key in keys) + (data['id'],)
        return self.query_exec(rs, query, params)

    @access("event_user")
    def set_event_data(self, rs, data):
        """Update some keys of an event organized via DB.

        The syntax for updating the associated data on orgas, parts and
        fields is as follows:

        * If the key 'orgas' is present you have to pass the complete list
          of orga IDs, which will superseed the current list of orgas.
        * If the keys 'parts' or 'fields' are present, the associated dict
          mapping the part or field ids to the respective data sets can
          contain an arbitrary number of entities, absent entities are not
          modified.

          Any valid entity id that is present has to map to a (partial or
          complete) data set or ``None``. In the first case the entity is
          updated, in the second case it is deleted.

          Any invalid entity id (that is negative integer) has to map to a
          complete data set which will be used to create a new entity.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: A positive number if all operations succeded and zero
          otherwise.
        """
        data = affirm("event_data", data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['id'])
        ret = 1
        with Atomizer(rs):
            keys = tuple(key for key in data if key in EVENT_FIELDS)
            if keys:
                query = "UPDATE event.events SET ({}) = ({}) WHERE id = %s"
                query = query.format(", ".join(keys),
                                     ", ".join(("%s",) * len(keys)))
                params = tuple(data[key] for key in keys) + (data['id'],)
                ret *= self.query_exec(rs, query, params)
            if 'orgas' in data:
                query = glue("SELECT persona_id FROM event.orgas",
                             "WHERE event_id = %s")
                existing = {e['persona_id']
                            for e in self.query_all(rs, query, (data['id'],))}
                new = data['orgas'] - existing
                deleted = existing - data['orgas']
                if new:
                    query = glue("INSERT INTO event.orgas",
                                 "(persona_id, event_id) VALUES (%s, %s)")
                    for anid in new:
                        ret *= self.query_exec(rs, query, (anid, data['id']))
                if deleted:
                    query = glue("DELETE FROM event.orgas",
                                 "WHERE persona_id = ANY(%s) AND event_id = %s")
                    ret *= self.query_exec(rs, query, (deleted, data['id']))
            if 'parts' in data:
                parts = data['parts']
                query = glue("SELECT id FROM event.event_parts",
                             "WHERE event_id = %s")
                existing = {e['id'] for e in self.query_all(rs, query,
                                                            (data['id'],))}
                if not(existing >= {x for x in parts if x > 0}):
                    raise ValueError("Non-existing parts specified.")
                new = {x for x in parts if x < 0}
                updated = {x for x in parts
                           if x > 0 and parts[x] is not None}
                deleted = {x for x in parts
                           if x > 0 and parts[x] is None}
                for x in new:
                    query = "INSERT INTO event.event_parts ({}) VALUES ({})"
                    keys = tuple(parts[x].keys())
                    query = query.format(", ".join(keys + ("event_id",)),
                                         ", ".join(("%s",) * (len(keys)+1)))
                    params = tuple(parts[x][key] for key in keys)
                    params += (data['id'],)
                    ret *= self.query_exec(rs, query, params)
                for x in updated:
                    query = glue("UPDATE event.event_parts SET ({}) = ({})",
                                 "WHERE id = %s")
                    keys = tuple(parts[x].keys())
                    query = query.format(", ".join(keys),
                                         ", ".join(("%s",) * len(keys)))
                    params = tuple(parts[x][key] for key in keys) + (x,)
                    ret *= self.query_exec(rs, query, params)
                if deleted:
                    query = "DELETE FROM event.event_parts WHERE id = ANY(%s)"
                    ret *= self.query_exec(rs, query, (deleted,))
            if 'fields' in data:
                fields = data['fields']
                query = glue("SELECT id FROM event.field_definitions",
                             "WHERE event_id = %s")
                existing = {e['id'] for e in self.query_all(rs, query,
                                                            (data['id'],))}
                if not(existing >= {x for x in fields if x > 0}):
                    raise ValueError("Non-existing fields specified.")
                new = {x for x in fields if x < 0}
                updated = {x for x in fields
                           if x > 0 and fields[x] is not None}
                deleted = {x for x in fields
                           if x > 0 and fields[x] is None}
                ## new
                query = glue("INSERT INTO event.field_definitions ({})",
                             "VALUES ({})")
                keys = ("field_name", "kind", "entries")
                query = query.format(", ".join(("event_id",) + keys),
                                     ", ".join(("%s",) * (len(keys)+1)))
                for x in new:
                    params = (data['id'],) + tuple(fields[x][key]
                                                   for key in keys)
                    ret *= self.query_exec(rs, query, params)
                ## updated
                query = glue("UPDATE event.field_definitions",
                             "SET ({}) = ({}) WHERE id = %s")
                keys = ("field_name", "kind", "entries")
                query = query.format(", ".join(keys),
                                     ", ".join(("%s",) * len(keys)))
                for x in updated:
                    params = tuple(fields[x][key] for key in keys) + (x,)
                    ret *= self.query_exec(rs, query, params)

                if deleted:
                    query = glue("DELETE FROM event.field_definitions",
                                 "WHERE id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (deleted,))
        return ret

    @access("event_admin")
    def create_past_event(self, rs, data):
        """Make a new concluded event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("past_event_data", data, creation=True)
        keys = tuple(data.keys())
        query = "INSERT INTO past_event.events ({}) VALUES ({}) RETURNING id"
        query = query.format(", ".join(keys),
                             ", ".join(("%s",) * len(keys)))
        params = tuple(data[key] for key in keys)
        return self.query_one(rs, query, params)['id']

    @access("event_admin")
    def create_event(self, rs, data):
        """Make a new event organized via DB.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("event_data", data, creation=True)
        with Atomizer(rs):
            keys = tuple(key for key in data if key in EVENT_FIELDS)
            query = "INSERT INTO event.events ({}) VALUES ({}) RETURNING id"
            query = query.format(", ".join(keys),
                                 ", ".join(("%s",) * len(keys)))
            params = tuple(data[key] for key in keys)

            new_id = self.query_one(rs, query, params)['id']
            for aspect in ('parts', 'orgas', 'fields'):
                if aspect in data:
                    adata = {
                        'id': new_id,
                        aspect: data[aspect],
                    }
                    self.set_event_data(rs, adata)
        return new_id

    @access("event_user")
    @singularize("get_past_course_data_one")
    def get_past_course_data(self, rs, ids):
        """Retrieve data for some concluded courses.

        They do not need to be associated to the same event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        query = "SELECT {} FROM past_event.courses WHERE id = ANY(%s)".format(
            ", ".join(PAST_COURSE_FIELDS))
        data = self.query_all(rs, query, (ids,))
        return {e['id']: e for e in data}

    @access("event_user")
    @singularize("get_course_data_one")
    def get_course_data(self, rs, ids):
        """Retrieve data for some courses organized via DB.

        They do not need to be associated to the same event. This contains
        additional information on the parts in which the course takes place.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        with Atomizer(rs):
            query = "SELECT {} FROM event.courses WHERE id = ANY(%s)".format(
                ", ".join(COURSE_FIELDS))
            data = self.query_all(rs, query, (ids,))
            ret = {e['id']: e for e in data}
            query = glue("SELECT part_id, course_id FROM event.course_parts",
                         "WHERE course_id = ANY(%s)")
            data = self.query_all(rs, query, (ids,))
            for anid in ids:
                parts = {p['part_id'] for p in data if p['course_id'] == anid}
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = parts
        return ret

    @access("event_admin")
    def set_past_course_data(self, rs, data):
        """Update some keys of a concluded course.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: number of changed entries
        """
        data = affirm("past_course_data", data)
        keys = tuple(data.keys())
        query = "UPDATE past_event.courses SET ({}) = ({}) WHERE id = %s"
        query = query.format(", ".join(keys), ", ".join(("%s",) * len(keys)))
        params = tuple(data[key] for key in keys) + (data['id'],)
        return self.query_exec(rs, query, params)

    @access("event_user")
    def set_course_data(self, rs, data):
        """Update some keys of a course linked to an event organized via DB.

        If the 'parts' key is present you have to pass the complete list
        of part IDs, which will superseed the current list of parts.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: A positive number if all operations succeded and zero
          otherwise.
        """
        data = affirm("course_data", data)
        if not self.is_orga(rs, course_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            keys = tuple(key for key in data if key in COURSE_FIELDS)
            if keys:
                query = "UPDATE event.courses SET ({}) = ({}) WHERE id = %s"
                query = query.format(", ".join(keys),
                                     ", ".join(("%s",) * len(keys)))
                params = tuple(data[key] for key in keys) + (data['id'],)
                ret *= self.query_exec(rs, query, params)
            if 'parts' in data:
                query = glue("SELECT part_id FROM event.course_parts",
                             "WHERE course_id = %s")
                existing = {e['part_id']
                            for e in self.query_all(rs, query, (data['id'],))}
                new = data['parts'] - existing
                deleted = existing - data['parts']
                if new:
                    ## check, that all new parts belong to the event of the
                    ## course
                    query = glue("SELECT event_id FROM event.event_parts",
                                 "WHERE id = ANY(%s)")
                    event_ids = {e['event_id']
                                 for e in self.query_all(rs, query, (new,))}
                    query = glue("SELECT event_id FROM event.courses",
                                 "WHERE id = %s")
                    event_id = self.query_one(rs, query, (data['id'],))[
                        'event_id']
                    if {event_id} != event_ids:
                        raise ValueError("Non-associated parts found.")

                    query = glue("INSERT INTO event.course_parts",
                                 "(course_id, part_id) VALUES (%s, %s)")
                    for anid in new:
                        ret *= self.query_exec(rs, query, (data['id'], anid))
                if deleted:
                    query = glue("DELETE FROM event.course_parts",
                                 "WHERE course_id = %s AND part_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deleted))
        return ret

    @access("event_admin")
    def create_past_course(self, rs, data):
        """Make a new concluded course.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new course
        """
        data = affirm("past_course_data", data, creation=True)
        keys = tuple(data.keys())
        query = "INSERT INTO past_event.courses ({}) VALUES ({}) RETURNING id"
        query = query.format(", ".join(keys), ", ".join(("%s",) * len(keys)))
        params = tuple(data[key] for key in keys)
        return self.query_one(rs, query, params)['id']

    @access("event_user")
    def create_course(self, rs, data):
        """Make a new course organized via DB.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
            keys = tuple(key for key in data if key in COURSE_FIELDS)
            query = "INSERT INTO event.courses ({}) VALUES ({}) RETURNING id"
            query = query.format(", ".join(keys),
                                 ", ".join(("%s",) * len(keys)))
            params = tuple(data[key] for key in keys)
            new_id = self.query_one(rs, query, params)['id']
            if 'parts' in data:
                pdata = {
                    'id': new_id,
                    'parts': data['parts'],
                }
                self.set_course_data(rs, pdata)
        return new_id

    @access("event_admin")
    def delete_past_course(self, rs, course_id, cascade=False):
        """Remove a concluded course.

        Because of referrential integrity only courses with no
        participants can be removed. This function can first remove all
        participants and then remove the course.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type course_id: int
        :type cascade: bool
        :param cascade: If True participants are removed first, if False the
          operation fails if participants exist.
        :rtype: int
        :returns: the number of removed entries
        """
        course_id = affirm("int", course_id)
        with Atomizer(rs):
            participants = self.list_participants(rs, course_id=course_id)
            if not cascade and participants:
                raise RuntimeError("Participants remaining and not cascading.")
            else:
                cdata = self.get_past_course_data_one(rs, course_id)
                for pid in participants:
                    self.delete_participant(rs, cdata['event_id'], course_id,
                                            pid)
            query = "DELETE FROM past_event.courses WHERE id = %s"
            return self.query_exec(rs, query, (course_id,))

    @access("event_admin")
    def create_participant(self, rs, event_id, course_id, persona_id,
                           is_instructor, is_orga):
        """Add a participant to a concluded event.

        A persona can participate multiple times in a single event. For
        example if she took several courses in different parts of the event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :type course_id: int or None
        :param course_id: If None the persona participated in the event, but
          not in a course (this should be common for orgas).
        :type persona_id: int
        :type is_instructor: bool
        :type is_orga: bool
        :rtype: int
        :returns: number of affected entries
        """
        persona_id = affirm("int", persona_id)
        event_id = affirm("int", event_id)
        course_id = affirm("int_or_None", course_id)
        is_instructor = affirm("bool", is_instructor)
        is_orga = affirm("bool", is_orga)
        query = glue(
            "INSERT INTO past_event.participants",
            "(persona_id, event_id, course_id, is_instructor, is_orga)",
            "VALUES (%s, %s, %s, %s, %s)")
        return self.query_exec(rs, query, (persona_id, event_id, course_id,
                                           is_instructor, is_orga))

    @access("event_admin")
    def delete_participant(self, rs, event_id, course_id, persona_id):
        """Remove a participant from a concluded event.

        All attributes have to match exactly, so that if someone
        participated multiple times (for example in different courses) we
        are able to delete an exact instance.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :type course_id: int or None
        :type persona_id: int
        :rtype: int
        :returns: number of affected entries
        """
        event_id = affirm("int", event_id)
        course_id = affirm("int_or_None", course_id)
        persona_id = affirm("int", persona_id)
        query = glue("DELETE FROM past_event.participants WHERE event_id = %s",
                     "AND persona_id = %s AND course_id {} %s")
        query = query.format("IS" if course_id is None else "=")
        return self.query_exec(rs, query, (event_id, persona_id, course_id))

    @access("event_user")
    def list_participants(self, rs, *, event_id=None, course_id=None):
        """List all participants of a concluded event or course.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int or None
        :type course_id: int or None
        :rtype: {int: {str: object}}
        """
        if event_id is None and course_id is None:
            raise ValueError("No input specified.")
        if event_id is not None and course_id is not None:
            raise ValueError("Too many inputs specified.")
        if event_id is not None:
            anid = affirm("int", event_id)
            field = "event_id"
        if course_id is not None:
            anid = affirm("int", course_id)
            field = "course_id"

        query = glue("SELECT persona_id, course_id, is_instructor, is_orga",
                     "FROM past_event.participants WHERE {} = %s")
        query = query.format(field)
        data = self.query_all(rs, query, (anid,))
        return {e['persona_id']: e for e in data}

    @access("event_user")
    def list_registrations(self, rs, event_id):
        """List all registrations of an event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :rtype: {int: {str: object}}
        """
        event_id = affirm("int", event_id)
        if (not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        query = glue("SELECT id, persona_id FROM event.registrations",
                     "WHERE event_id = %s")
        data = self.query_all(rs, query, (event_id,))
        return {e['id']: e['persona_id'] for e in data}

    @access("event_user")
    @singularize("get_registration")
    def get_registrations(self, rs, ids):
        """Retrieve data for some registrations.

        All have to be from the same event. You must be orga to access
        registrations which are not your own. This includes the following
        additional data:

        * parts: per part data (like lodgement),
        * choices: course choices, also per part.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        if not ids:
            return {}
        with Atomizer(rs):
            query = glue("SELECT persona_id, event_id FROM event.registrations",
                         "WHERE id = ANY(%s)")
            tmp = self.query_all(rs, query, (ids,))
            events = {e['event_id'] for e in tmp}
            personas = {e['persona_id'] for e in tmp}
            if len(events) != 1:
                raise ValueError(
                    "Only registrations from exactly one event allowed!")
            event_id = events.pop()
            if (not self.is_orga(rs, event_id=event_id)
                   and not self.is_admin(rs)
                   and not ({rs.user.persona_id} >= personas)):
                raise PrivilegeError("Not privileged.")

            query = "SELECT {} FROM event.registrations WHERE id = ANY(%s)"
            query = query.format(", ".join(REGISTRATION_FIELDS))
            ret = {e['id']: e for e in self.query_all(rs, query, (ids,))}
            query = glue("SELECT {} FROM event.registration_parts",
                         "WHERE registration_id = ANY(%s)")
            query = query.format(", ".join(REGISTRATION_PART_FIELDS))
            data = self.query_all(rs, query, (ids,))
            for anid in ret:
                assert('parts' not in ret[anid])
                ret[anid]['parts'] = {e['part_id']: e for e in data
                                      if e['registration_id'] == anid}
            query = glue("SELECT registration_id, part_id, course_id, rank",
                         "FROM event.course_choices",
                         "WHERE registration_id = ANY(%s)")
            data = self.query_all(rs, query, (ids,))
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

    @access("event_user")
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: A positive number if all operations succeded and zero
          otherwise.
        """
        data = affirm("registration_data", data)
        with Atomizer(rs):
            query = "SELECT persona_id FROM event.registrations WHERE id = %s"
            persona_id = self.query_one(rs, query, (data['id'],))['persona_id']
            query = "SELECT event_id FROM event.registrations WHERE id = %s"
            event_id = self.query_one(rs, query, (data['id'],))['event_id']
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
            keys = tuple(key for key in data
                         if key in REGISTRATION_FIELDS and key != "field_data")
            ret = 1
            if keys:
                query = glue("UPDATE event.registrations SET ({}) = ({})",
                             "WHERE id = %s")
                query = query.format(", ".join(keys), ", ".join(("%s",)* len(keys)))
                params = tuple(data[key] for key in keys) + (data['id'],)
                ret *= self.query_exec(rs, query, params)
            if 'field_data' in data:
                query = glue("SELECT field_data FROM event.registrations",
                             "WHERE id = %s")
                fdata = self.query_one(rs, query, (data['id'],))['field_data']
                fdata.update(data['field_data'])
                query = glue("UPDATE event.registrations SET field_data = %s",
                             "WHERE id = %s")
                ret *= self.query_exec(rs, query, (psycopg2.extras.Json(fdata),
                                                   data['id']))
            if 'parts' in data:
                parts = data['parts']
                if not(set(event_data['parts'].keys()) >= {x for x in parts}):
                    raise ValueError("Non-existing parts specified.")
                query = glue("SELECT id, part_id FROM event.registration_parts",
                             "WHERE registration_id = %s")
                existing = {e['part_id']: e['id'] for e in self.query_all(
                    rs, query, (data['id'],))}
                new = {x for x in parts if x not in existing}
                updated = {x for x in parts
                           if x in existing and parts[x] is not None}
                deleted = {x for x in parts
                           if x in existing and parts[x] is None}
                for x in new:
                    query = glue("INSERT INTO event.registration_parts ({})",
                                 "VALUES ({})")
                    keys = tuple(key for key in parts[x])
                    query = query.format(
                        ", ".join(keys + ("registration_id", "part_id")),
                        ", ".join(("%s",) * (len(keys)+2)))
                    params = tuple(parts[x][key] for key in keys)
                    params += (data['id'], x)
                    ret *= self.query_exec(rs, query, params)
                for x in updated:
                    query = glue("UPDATE event.registration_parts",
                                 "SET ({}) = ({}) WHERE id = %s")
                    keys = tuple(key for key in parts[x])
                    query = query.format(", ".join(keys),
                                         ", ".join(("%s",) * len(keys)))
                    params = tuple(parts[x][key] for key in keys)
                    params += (existing[x],)
                    ret *= self.query_exec(rs, query, params)
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
                    query = glue(
                        "INSERT INTO event.course_choices",
                        "(registration_id, part_id, course_id, rank)",
                        "VALUES (%s, %s, %s, %s)")
                    for rank, course_id in enumerate(choices[part_id]):
                        ret *= self.query_exec(
                            rs, query, (data['id'], part_id, course_id, rank))
        return ret

    @access("event_user")
    def create_registration(self, rs, data):
        """Make a new registration.

        The data may not contain a value for 'field_data', which is
        initialized to a default value.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
            keys = tuple(key for key in data if key in REGISTRATION_FIELDS)
            query = glue("INSERT INTO event.registrations ({})",
                         "VALUES ({}) RETURNING id")
            query = query.format(", ".join(keys),
                                 ", ".join(("%s",) * len(keys)))
            params = tuple(data[key] for key in keys)
            new_id = self.query_one(rs, query, params)['id']
            for aspect in ('parts', 'choices'):
                if aspect in data:
                    new_data = {
                        'id': new_id,
                        aspect: data[aspect]
                    }
                    self.set_registration(rs, new_data)
            ## fix field_data to contain registration id
            query = glue("UPDATE event.registrations SET field_data = %s",
                         "WHERE id = %s")
            self.query_exec(rs, query, (
                psycopg2.extras.Json({'registration_id': new_id}), new_id))
        return new_id

    @access("event_user")
    def list_lodgements(self, rs, event_id):
        """List all lodgements for an event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :rtype: {int: str}
        :returns: dict mapping ids to names
        """
        event_id = affirm("int", event_id)
        if (not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        query = "SELECT id, moniker FROM event.lodgements WHERE event_id = %s"
        data = self.query_all(rs, query, (event_id,))
        return {e['id']: e['moniker'] for e in data}

    @access("event_user")
    @singularize("get_lodgement")
    def get_lodgements(self, rs, ids):
        """Retrieve data for some lodgements.

        All have to be from the same event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        if not ids:
            return {}
        with Atomizer(rs):
            query = "SELECT {} FROM event.lodgements WHERE id = ANY(%s)"
            query = query.format(", ".join(LODGMENT_FIELDS))
            data = self.query_all(rs, query, (ids,))
            events = {e['event_id'] for e in data}
            if len(events) != 1:
                raise ValueError(
                    "Only lodgements from exactly one event allowed!")
            event_id = events.pop()
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
        return {e['id']: e for e in data}

    @access("event_user")
    def set_lodgement(self, rs, data):
        """Update some keys of a lodgement.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: number of affected entries.
        """
        data = affirm("lodgement_data", data)
        with Atomizer(rs):
            query = "SELECT event_id FROM event.lodgements WHERE id = %s"
            event_id = self.query_one(rs, query, (data['id'],))['event_id']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
            self.assert_offline_lock(rs, event_id=event_id)
            keys = tuple(data.keys())
            query = "UPDATE event.lodgements SET ({}) = ({}) WHERE id = %s"
            query = query.format(", ".join(keys), ", ".join(("%s",)* len(keys)))
            params = tuple(data[key] for key in keys) + (data['id'],)
            return self.query_exec(rs, query, params)

    @access("event_user")
    def create_lodgement(self, rs, data):
        """Make a new lodgement.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new lodgement
        """
        data = affirm("lodgement_data", data, creation=True)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=data['event_id'])
        keys = tuple(data.keys())
        query = "INSERT INTO event.lodgements ({}) VALUES ({}) RETURNING id"
        query = query.format(", ".join(keys), ", ".join(("%s",)* len(keys)))
        params = tuple(data[key] for key in keys)
        return self.query_one(rs, query, params)['id']

    @access("event_user")
    def delete_lodgement(self, rs, lodgement_id):
        """Make a new lodgement.

        The lodgement has to be empty otherwise there will be an
        integrity exception.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type lodgement_id: int
        :rtype: int
        :returns: number of affected entries
        """
        lodgement_id = affirm("int", lodgement_id)
        with Atomizer(rs):
            query = "SELECT event_id FROM event.lodgements WHERE id = %s"
            event_id = self.query_one(rs, query, (lodgement_id,))['event_id']
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError("Not privileged.")
            self.assert_offline_lock(rs, event_id=event_id)
            query = "DELETE FROM event.lodgements WHERE id = %s"
            return self.query_exec(rs, query, (lodgement_id,))

    @access("event_user")
    def get_questionnaire(self, rs, event_id):
        """Retrieve the questionnaire rows for a specific event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :rtype: [{str: object}]
        :returns: list of questionnaire row entries
        """
        event_id = affirm("int", event_id)
        query = glue("SELECT field_id, pos, title, info, readonly",
                     "FROM event.questionnaire_rows WHERE event_id = %s")
        data = self.query_all(rs, query, (event_id,))
        return sorted(data, key=lambda x: x['pos'])

    @access("event_user")
    def set_questionnaire(self, rs, event_id, data):
        """Replace current questionnaire rows for a specific event.

        This superseeds the current questionnaire.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :type data: [{str: object}]
        :rtype: int
        :returns: A positive number if all operations succeded and zero
          otherwise.
        """
        event_id = affirm("int", event_id)
        data = affirm("questionnaire_data", data)
        if (not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs)):
            raise PrivilegeError("Not privileged.")
        self.assert_offline_lock(rs, event_id=event_id)
        with Atomizer(rs):
            query = "DELETE FROM event.questionnaire_rows WHERE event_id = %s"
            self.query_exec(rs, query, (event_id,))
            query = glue(
                "INSERT INTO event.questionnaire_rows",
                "(event_id, field_id, pos, title, info, readonly)",
                "VALUES (%s, %s, %s, %s, %s, %s)")
            ret = 1
            for pos, row in enumerate(data):
                ret *= self.query_exec(
                    rs, query, (event_id, row['field_id'], pos, row['title'],
                                row['info'], row['readonly']))
        return ret

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for event services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    event_backend = EventBackend(args.configpath)
    conf = Config(args.configpath)
    event_server = make_RPCDaemon(event_backend, conf.EVENT_SOCKET,
                                  access_log=conf.EVENT_ACCESS_LOG)
    run_RPCDaemon(event_server, conf.EVENT_STATE_FILE)
