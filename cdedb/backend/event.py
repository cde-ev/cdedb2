#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy
from typing import Any, Collection, Dict, Mapping, Set, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    Silencer, access, affirm_set_validation as affirm_set,
    affirm_validation_typed as affirm,
)
from cdedb.backend.event_base import EventBaseBackend
from cdedb.backend.event_course import EventCourseBackend
from cdedb.backend.event_lowlevel import EventLowLevelBackend
from cdedb.backend.event_lodgement import EventLodgementBackend
from cdedb.backend.event_query import EventQueryBackend
from cdedb.backend.event_registration import EventRegistrationBackend
from cdedb.common import (
    CdEDBObject, CdEDBOptionalMap, DefaultReturnCode,
    EVENT_SCHEMA_VERSION, PartialImportError, PrivilegeError, RequestState, get_hash,
    json_serialize, mixed_existence_sorter, n_, unwrap,
)
from cdedb.common import (DeletionBlockers)
from cdedb.database.connection import Atomizer


class EventBackend(EventCourseBackend, EventLodgementBackend, EventQueryBackend,
                   EventRegistrationBackend, EventBaseBackend, EventLowLevelBackend):
    @access("event_admin")
    def delete_event_blockers(self, rs: RequestState,
                              event_id: int) -> DeletionBlockers:
        """Determine what keeps an event from being deleted.

        Possible blockers:

        * field_definitions: A custom datafield associated with the event.
        * courses: A course associated with the event. This can have it's own
                   blockers.
        * course_tracks: A course track of the event.
        * orgas: An orga of the event.
        * lodgement_groups: A lodgement group associated with the event.
                            This can have it's own blockers.
        * lodgements: A lodgement associated with the event. This can have
                      it's own blockers.
        * registrations: A registration associated with the event. This can
                         have it's own blockers.
        * questionnaire: A questionnaire row configured for the event.
        * stored_queries: A stored query for the event.
        * log: A log entry for the event.
        * mailinglists: A mailinglist associated with the event. This
                        reference will be removed but the mailinglist will
                        not be deleted.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        event_id = affirm(vtypes.ID, event_id)
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

        lodgement_groups = self.sql_select(
            rs, "event.lodgement_groups", ("id",), (event_id,),
            entity_key="event_id")
        if lodgement_groups:
            blockers["lodgement_groups"] = [e["id"] for e in lodgement_groups]

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

        stored_queries = self.sql_select(
            rs, "event.stored_queries", ("id",), (event_id,), entity_key="event_id")
        if stored_queries:
            blockers["stored_queries"] = [e["id"] for e in stored_queries]

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
    def delete_event(self, rs: RequestState, event_id: int,
                     cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove event.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        event_id = affirm(vtypes.ID, event_id)
        blockers = self.delete_event_blockers(rs, event_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
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
                if "lodgement_groups" in cascade:
                    ret *= self.sql_delete(rs, "event.lodgement_groups",
                                           blockers["lodgement_groups"])
                if "event_parts" in cascade:
                    part_cascade = ({"course_tracks"} & cascade) \
                                   | {"fee_modifiers"}
                    with Silencer(rs):
                        for anid in blockers["event_parts"]:
                            self._delete_event_part(rs, anid, part_cascade)
                if "questionnaire" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.questionnaire_rows",
                        blockers["questionnaire"])
                if "field_definitions" in cascade:
                    deletor: CdEDBObject = {
                        'id': event_id,
                        'course_room_field': None,
                        'lodge_field': None,
                        'camping_mat_field': None,
                    }
                    ret *= self.sql_update(rs, "event.events", deletor)
                    field_cascade = {"fee_modifiers"} & cascade
                    with Silencer(rs):
                        for anid in blockers["field_definitions"]:
                            ret *= self._delete_event_field(
                                rs, anid, field_cascade)
                if "orgas" in cascade:
                    ret *= self.sql_delete(rs, "event.orgas", blockers["orgas"])
                if "stored_queries" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.stored_queries", blockers["stored_queries"])
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
                               event_id=None, change_note=event["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "event", "block": blockers.keys()})
        return ret

    @access("event")
    def unlock_import_event(self, rs: RequestState,
                            data: CdEDBObject) -> DefaultReturnCode:
        """Unlock an event after offline usage and import changes.

        This is a combined action so that we stay consistent.
        """
        data = affirm(vtypes.SerializedEvent, data)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        if self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            raise RuntimeError(n_("Imports into an offline instance must"
                                  " happen via shell scripts."))
        if not self.is_offline_locked(rs, event_id=data['id']):
            raise RuntimeError(n_("Not locked."))
        if data["EVENT_SCHEMA_VERSION"] != EVENT_SCHEMA_VERSION:
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
            translations: Dict[str, Dict[int, int]]
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
                      ('event.fee_modifiers', None),
                      ('event.lodgement_groups', 'group_id'),
                      ('event.lodgements', 'lodgement_id'),
                      ('event.registrations', 'registration_id'),
                      ('event.registration_parts', None),
                      ('event.registration_tracks', None),
                      ('event.course_choices', None),
                      ('event.questionnaire_rows', None),
                      ('event.log', None))
            for table, entity in tables:
                ret *= self._synchronize_table(
                    rs, table, data[table], current[table], translations,
                    entity=entity, extra_translations=extra_translations)
            # Third fix the amounts owed for all registrations.
            reg_ids = self.list_registrations(rs, event_id=data['id'])
            fees_owed = self.calculate_fees(rs, reg_ids)
            for reg_id, fee in fees_owed.items():
                update = {
                    'id': reg_id,
                    'amount_owed': fee,
                }
                ret *= self.sql_update(rs, "event.registrations", update)

            # Forth unlock the event
            update = {
                'id': data['id'],
                'offline_lock': False,
            }
            ret *= self.sql_update(rs, "event.events", update)
            self.event_log(rs, const.EventLogCodes.event_unlocked, data['id'])
        return ret

    @access("event")
    def partial_import_event(self, rs: RequestState, data: CdEDBObject,
                             dryrun: bool, token: str = None
                             ) -> Tuple[str, CdEDBObject]:
        """Incorporate changes into an event.

        In contrast to the full import in this case the data describes a
        delta to be applied to the current online state.

        :param dryrun: If True we do not modify any state.
        :param token: Expected transaction token. If the transaction would
          generate a different token a PartialImportError is raised.
        :returns: A tuple of a transaction token and the datasets that
          are changed by the operation (in the state after the change). The
          transaction token describes the change and can be submitted to
          guarantee a certain effect.
        """
        data = affirm(vtypes.SerializedPartialEvent, data)
        dryrun = affirm(bool, dryrun)
        if not self.is_orga(rs, event_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['id'])
        if not ((EVENT_SCHEMA_VERSION[0], 0) <= data["EVENT_SCHEMA_VERSION"]
                <= EVENT_SCHEMA_VERSION):
            raise ValueError(n_("Version mismatch – aborting."))

        def dict_diff(old: Mapping[Any, Any], new: Mapping[Any, Any]
                      ) -> Tuple[Dict[Any, Any], Dict[Any, Any]]:
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

            used_lodgement_group_ids = {
                lodgement.get('group_id')
                for lodgement in data.get('lodgements', {}).values()
                if lodgement}
            used_lodgement_group_ids -= {None}
            available_lodgement_group_ids = set(
                all_current_data['lodgement_groups'])
            available_lodgement_group_ids |= set(
                key for key in data.get('lodgement_groups', {}) if key < 0)
            available_lodgement_group_ids -= set(
                k for k, v in data.get('lodgement_groups', {}).items()
                if v is None)
            if not used_lodgement_group_ids <= available_lodgement_group_ids:
                raise ValueError(
                    n_("Referential integrity of lodgement groups violated."))

            used_lodgement_ids = {
                part.get('lodgement_id')
                for registration in data.get('registrations', {}).values()
                if registration
                for part in registration.get('parts', {}).values()}
            used_lodgement_ids -= {None}
            available_lodgement_ids = set(all_current_data['lodgements']) | set(
                key for key in data.get('lodgements', {}) if key < 0)
            available_lodgement_ids -= set(
                k for k, v in data.get('lodgements', {}).items() if v is None)
            if not used_lodgement_ids <= available_lodgement_ids:
                raise ValueError(
                    "Referential integrity of lodgements violated.")

            used_course_ids: Set[int] = set()
            for registration in data.get('registrations', {}).values():
                if registration:
                    for track in registration.get('tracks', {}).values():
                        if track:
                            used_course_ids |= set(track.get('choices', []))
                            used_course_ids.add(track.get('course_id'))
                            used_course_ids.add(track.get('course_instructor'))
            used_course_ids -= {None}
            available_course_ids = set(all_current_data['courses']) | set(
                key for key in data.get('courses', {}) if key < 0)
            available_course_ids -= set(
                k for k, v in data.get('courses', {}).items() if v is None)
            if not used_course_ids <= available_course_ids:
                raise ValueError(
                    "Referential integrity of courses violated.")

            # go to work
            total_delta = {}
            total_previous = {}

            # This needs to be processed in the following order:
            # lodgement groups -> lodgements -> courses -> registrations.

            # We handle these in the specific order of mixed_existence_sorter
            mes = mixed_existence_sorter
            # noinspection PyPep8Naming
            IDMap = Dict[int, int]

            gmap: IDMap = {}
            gdelta: CdEDBOptionalMap = {}
            gprevious: CdEDBOptionalMap = {}
            for group_id in mes(data.get('lodgement_groups', {}).keys()):
                new_group = data['lodgement_groups'][group_id]
                current = all_current_data['lodgement_groups'].get(group_id)
                if group_id > 0 and current is None:
                    # group was deleted online in the meantime
                    gdelta[group_id] = None
                    gprevious[group_id] = None
                elif new_group is None:
                    gdelta[group_id] = None
                    gprevious[group_id] = current
                    if not dryrun:
                        self.delete_lodgement_group(
                            rs, group_id, ("lodgements",))
                elif group_id < 0:
                    gdelta[group_id] = new_group
                    gprevious[group_id] = None
                    if not dryrun:
                        new = copy.deepcopy(new_group)
                        new['event_id'] = data['id']
                        new_id = self.create_lodgement_group(rs, new)
                        gmap[group_id] = new_id
                else:
                    delta, previous = dict_diff(current, new_group)
                    if delta:
                        gdelta[group_id] = delta
                        gprevious[group_id] = previous
                        if not dryrun:
                            todo = copy.deepcopy(delta)
                            todo['id'] = group_id
                            self.set_lodgement_group(rs, todo)
            if gdelta:
                total_delta['lodgement_groups'] = gdelta
                total_previous['lodgement_groups'] = gprevious

            lmap: IDMap = {}
            ldelta: CdEDBOptionalMap = {}
            lprevious: CdEDBOptionalMap = {}
            for lodgement_id in mes(data.get('lodgements', {}).keys()):
                new_lodgement = data['lodgements'][lodgement_id]
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
                        if new['group_id'] in gmap:
                            old_id = new['group_id']
                            new['group_id'] = gmap[old_id]
                        new_id = self.create_lodgement(rs, new)
                        lmap[lodgement_id] = new_id
                else:
                    delta, previous = dict_diff(current, new_lodgement)
                    if delta:
                        ldelta[lodgement_id] = delta
                        lprevious[lodgement_id] = previous
                        if not dryrun:
                            changed_lodgement = copy.deepcopy(delta)
                            changed_lodgement['id'] = lodgement_id
                            if 'group_id' in changed_lodgement:
                                old_id = changed_lodgement['group_id']
                                if old_id in gmap:
                                    changed_lodgement['group_id'] = gmap[old_id]
                            self.set_lodgement(rs, changed_lodgement)
            if ldelta:
                total_delta['lodgements'] = ldelta
                total_previous['lodgements'] = lprevious

            cmap: IDMap = {}
            cdelta: CdEDBOptionalMap = {}
            cprevious: CdEDBOptionalMap = {}

            def check_seg(track_id, delta, original) -> bool:  # type: ignore
                return ((track_id in delta and delta[track_id] is not None)
                        or (track_id not in delta and track_id in original))

            for course_id in mes(data.get('courses', {}).keys()):
                new_course = data['courses'][course_id]
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
                        new_id = self.create_course(rs, new)
                        cmap[course_id] = new_id
                else:
                    delta, previous = dict_diff(current, new_course)
                    if delta:
                        cdelta[course_id] = delta
                        cprevious[course_id] = previous
                        if not dryrun:
                            changed_course = copy.deepcopy(delta)
                            segments = changed_course.pop('segments', None)
                            if segments:
                                orig_seg = current['segments']
                                new_segments = [
                                    x for x in event['tracks']
                                    if check_seg(x, segments, orig_seg)]
                                changed_course['segments'] = new_segments
                                orig_active = [
                                    s for s, a in current['segments'].items()
                                    if a]
                                new_active = [
                                    x for x in event['tracks']
                                    if segments.get(x, x in orig_active)]
                                changed_course['active_segments'] = new_active
                            changed_course['id'] = course_id
                            self.set_course(rs, changed_course)
            if cdelta:
                total_delta['courses'] = cdelta
                total_previous['courses'] = cprevious

            rmap: IDMap = {}
            rdelta: CdEDBOptionalMap = {}
            rprevious: CdEDBOptionalMap = {}

            dup = {
                old_reg['persona_id']: old_reg['id']
                for old_reg in old_registrations.values()
                }

            data_regs = data.get('registrations', {})
            for registration_id in mes(data_regs.keys()):
                new_registration = data_regs[registration_id]
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
                        for track in new['tracks'].values():
                            keys = {'course_id', 'course_instructor'}
                            for key in keys:
                                if track[key] in cmap:
                                    tmp_id = track[key]
                                    track[key] = cmap[tmp_id]
                            new_choices = [
                                cmap.get(course_id, course_id)
                                for course_id in track['choices']
                            ]
                            track['choices'] = new_choices
                        for part in new['parts'].values():
                            if part['lodgement_id'] in lmap:
                                tmp_id = part['lodgement_id']
                                part['lodgement_id'] = lmap[tmp_id]
                        new_id = self.create_registration(rs, new)
                        rmap[registration_id] = new_id
                else:
                    delta, previous = dict_diff(current, new_registration)
                    if delta:
                        rdelta[registration_id] = delta
                        rprevious[registration_id] = previous
                        if not dryrun:
                            changed_reg = copy.deepcopy(delta)
                            if 'tracks' in changed_reg:
                                for track in changed_reg['tracks'].values():
                                    keys = {'course_id', 'course_instructor'}
                                    for key in keys:
                                        if key in track:
                                            if track[key] in cmap:
                                                tmp_id = track[key]
                                                track[key] = cmap[tmp_id]
                                    if 'choices' in track:
                                        new_choices = [
                                            cmap.get(course_id, course_id)
                                            for course_id in track['choices']
                                        ]
                                        track['choices'] = new_choices
                            if 'parts' in changed_reg:
                                for part in changed_reg['parts'].values():
                                    if 'lodgement_id' in part:
                                        if part['lodgement_id'] in lmap:
                                            tmp_id = part['lodgement_id']
                                            part['lodgement_id'] = lmap[tmp_id]
                            changed_reg['id'] = registration_id
                            # change_note for log entry for registrations
                            change_note = "Partieller Import."
                            if data.get('summary'):
                                change_note = ("Partieller Import: "
                                               + data['summary'])
                            self.set_registration(rs, changed_reg, change_note)
            if rdelta:
                total_delta['registrations'] = rdelta
                total_previous['registrations'] = rprevious

            result = get_hash(
                json_serialize(total_delta, sort_keys=True).encode('utf-8'),
                json_serialize(total_previous, sort_keys=True).encode('utf-8')
            )
            if token is not None and result != token:
                raise PartialImportError("The delta changed.")
            if not dryrun:
                self.event_log(rs, const.EventLogCodes.event_partial_import,
                               data['id'], change_note=data.get('summary'))
        return result, total_delta
