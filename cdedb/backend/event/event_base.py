#!/usr/bin/env python3

"""
The `EventBaseBackend` provides backend functionality related to events in general.

There are several subclasses in separate files which provide additional functionality
related to more specific aspects of event management.

This subclasses `EventBackendHelpers`, which provides a collection of internal
low-level helpers which are used here and in the subclasses.

All parts are combined together in the `EventBackend` class via multiple inheritance,
together with a handful of high-level methods, that use functionalities of multiple
backend parts.
"""

import collections
import copy
import datetime
from typing import Any, Collection, Dict, Iterable, List, Optional, Protocol, Set, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    Silencer, access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, cast_fields, internal, singularize,
)
from cdedb.backend.event.event_lowlevel import EventLowLevelBackend
from cdedb.common import (
    COURSE_FIELDS, COURSE_TRACK_FIELDS, EVENT_FIELDS, EVENT_PART_FIELDS,
    EVENT_SCHEMA_VERSION, FEE_MODIFIER_FIELDS, FIELD_DEFINITION_FIELDS,
    LODGEMENT_FIELDS, LODGEMENT_GROUP_FIELDS, PERSONA_EVENT_FIELDS,
    QUESTIONNAIRE_ROW_FIELDS, REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS,
    REGISTRATION_TRACK_FIELDS, CdEDBLog, CdEDBObject, CdEDBObjectMap, DefaultReturnCode,
    PrivilegeError, RequestState, glue, n_, now, unwrap, xsorted,
)
from cdedb.database.connection import Atomizer

# type alias for questionnaire specification.
CdEDBQuestionnaire = Dict[const.QuestionnaireUsages, List[CdEDBObject]]


class EventBaseBackend(EventLowLevelBackend):
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
            for event_id, fields in self._get_events_fields(rs, event_ids).items():
                ret[event_id]['fields'] = fields
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
                part['status'] = const.RegistrationPartStati(part['status'])
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
