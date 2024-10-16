#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

import collections
import copy
import decimal
from collections.abc import Collection, Mapping
from typing import Any, Optional

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
import cdedb.models.ml as models_ml
from cdedb.backend.common import (
    Silencer,
    access,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.backend.event.course import EventCourseBackend
from cdedb.backend.event.lodgement import EventLodgementBackend
from cdedb.backend.event.lowlevel import EventLowLevelBackend
from cdedb.backend.event.query import EventQueryBackend
from cdedb.backend.event.registration import EventRegistrationBackend
from cdedb.common import (
    EVENT_SCHEMA_VERSION,
    CdEDBObject,
    CdEDBObjectMap,
    CdEDBOptionalMap,
    DefaultReturnCode,
    DeletionBlockers,
    RequestState,
    build_msg,
    get_hash,
    json_serialize,
    unwrap,
)
from cdedb.common.exceptions import PartialImportError, PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.sorting import mixed_existence_sorter
from cdedb.database.connection import Atomizer
from cdedb.models.droid import OrgaToken

__all__ = ['EventBackend']


class EventBackend(EventCourseBackend, EventLodgementBackend, EventQueryBackend,
                   EventRegistrationBackend, EventBaseBackend, EventLowLevelBackend):
    @access("event_admin")
    def delete_event_blockers(self, rs: RequestState,
                              event_id: int) -> DeletionBlockers:
        """Determine what keeps an event from being deleted.

        Possible blockers:

        * orga_tokens: An orga token granting API access to the event.
        * field_definitions: A custom datafield associated with the event.
        * custom_query_filters: A custom filter for queries associated with the event.
        * courses: A course associated with the event. This can have it's own
                   blockers.
        * event_fees: A fee of the event.
        * event_parts: An event part.
        * course_tracks: A course track of the event, belonging to an event part.
        * part_groups: A group of event parts.
        * part_group_parts: A link between an event part and a part group.
        * track_groups: A group of course tracks.
        * track_group_tracks: A link between a course track and a track group.
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

        orga_tokens = self.sql_select(
            rs, OrgaToken.database_table, ("id",), (event_id,), entity_key="event_id")
        if orga_tokens:
            blockers["orga_tokens"] = [e["id"] for e in orga_tokens]

        field_definitions = self.sql_select(
            rs, models.EventField.database_table, ("id",),
            (event_id,), entity_key=models.EventField.entity_key)
        if field_definitions:
            blockers["field_definitions"] = [e["id"] for e in field_definitions]

        custom_query_filters = self.sql_select(
            rs, models.CustomQueryFilter.database_table, ("id",),
            (event_id,), entity_key=models.CustomQueryFilter.entity_key)
        if custom_query_filters:
            blockers["custom_query_filters"] = [e["id"] for e in custom_query_filters]

        courses = self.sql_select(
            rs, models.Course.database_table, ("id",),
            (event_id,), entity_key="event_id")
        if courses:
            blockers["courses"] = [e["id"] for e in courses]

        event_fees = self.sql_select(
            rs, models.EventFee.database_table, ("id",),
            (event_id,), entity_key=models.EventFee.entity_key)
        if event_fees:
            blockers["event_fees"] = [e["id"] for e in event_fees]

        event_parts = self.sql_select(
            rs, models.EventPart.database_table, ("id",),
            (event_id,), entity_key=models.EventPart.entity_key)
        if event_parts:
            blockers["event_parts"] = [e["id"] for e in event_parts]
            course_tracks = self.sql_select(
                rs, models.CourseTrack.database_table, ("id",),
                blockers["event_parts"], entity_key=models.CourseTrack.entity_key)
            if course_tracks:
                blockers["course_tracks"] = [e["id"] for e in course_tracks]

        part_groups = self.sql_select(
            rs, models.PartGroup.database_table, ("id",),
            (event_id,), entity_key=models.PartGroup.entity_key)
        if part_groups:
            blockers["part_groups"] = [e["id"] for e in part_groups]
            part_group_parts = self.sql_select(
                rs, "event.part_group_parts", ("id",), blockers["part_groups"],
                entity_key="part_group_id")
            if part_group_parts:
                blockers["part_group_parts"] = [e["id"] for e in part_group_parts]

        track_groups = self.sql_select(
            rs, models.TrackGroup.database_table, ("id",),
            (event_id,), entity_key=models.TrackGroup.entity_key)
        if track_groups:
            blockers["track_groups"] = [e["id"] for e in track_groups]
            track_group_tracks = self.sql_select(
                rs, "event.track_group_tracks", ("id",), blockers["track_groups"],
                entity_key="track_group_id")
            if track_group_tracks:
                blockers["track_group_tracks"] = [e["id"] for e in track_group_tracks]

        orgas = self.sql_select(
            rs, "event.orgas", ("id",), (event_id,), entity_key="event_id")
        if orgas:
            blockers["orgas"] = [e["id"] for e in orgas]

        lodgement_groups = self.sql_select(
            rs, models.LodgementGroup.database_table, ("id",),
            (event_id,), entity_key=models.LodgementGroup.entity_key)
        if lodgement_groups:
            blockers["lodgement_groups"] = [e["id"] for e in lodgement_groups]

        lodgements = self.sql_select(
            rs, models.Lodgement.database_table, ("id",),
            (event_id,), entity_key="event_id")
        if lodgements:
            blockers["lodgements"] = [e["id"] for e in lodgements]

        registrations = self.sql_select(
            rs, models.Registration.database_table, ("id",),
            (event_id,), entity_key=models.Registration.entity_key)
        if registrations:
            blockers["registrations"] = [e["id"] for e in registrations]

        questionnaire_rows = self.sql_select(
            rs, models.QuestionnaireRow.database_table, ("id",),
            (event_id,), entity_key=models.QuestionnaireRow.entity_key)
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

        ml_blockers: set[int] = set()
        mailinglists = self.sql_select(
            rs, models_ml.Mailinglist.database_table, ("id",),
            (event_id,), entity_key="event_id")
        if mailinglists:
            ml_blockers.update(e["id"] for e in mailinglists)

        mailinglists_part_group_id = self.sql_select(
            rs, models_ml.Mailinglist.database_table, ("id",),
            blockers.get("event_part_groups", []), entity_key="event_part_group_id")
        if mailinglists_part_group_id:
            ml_blockers.update(e["id"] for e in mailinglists_part_group_id)

        if ml_blockers:
            blockers["mailinglists"] = list(ml_blockers)

        return blockers

    @access("event_admin")
    def delete_event(self, rs: RequestState, event_id: int,
                     cascade: Optional[Collection[str]] = None) -> DefaultReturnCode:
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
                                 "registration_tracks", "amount_paid"))
                if "courses" in cascade:
                    with Silencer(rs):
                        for course_id in blockers["courses"]:
                            ret *= self.delete_course(
                                rs, course_id,
                                ("attendees", "course_choices",
                                 "course_segments", "instructors"))
                if "lodgements" in cascade:
                    ret *= self.sql_delete(
                        rs, models.Lodgement.database_table, blockers["lodgements"])
                if "lodgement_groups" in cascade:
                    ret *= self.sql_delete(
                        rs, models.LodgementGroup.database_table,
                        blockers["lodgement_groups"],
                    )
                if "part_groups" in cascade:
                    with Silencer(rs):
                        part_group_cascade = {
                             "part_group_parts", "mailinglists",
                        } & cascade
                        for anid in blockers["part_groups"]:
                            self._delete_part_group(rs, anid, part_group_cascade)
                if "event_fees" in cascade:
                    ret *= self.sql_delete(
                        rs, models.EventFee.database_table, blockers["event_fees"])
                if "event_parts" in cascade:
                    part_cascade = {"course_tracks"} & cascade
                    with Silencer(rs):
                        for anid in blockers["event_parts"]:
                            self._delete_event_part(rs, anid, part_cascade)
                if "track_groups" in cascade:
                    with Silencer(rs):
                        track_group_cascade = {"track_group_parts"} & cascade
                        for anid in blockers["track_groups"]:
                            self._delete_track_group(rs, anid, track_group_cascade)
                if "questionnaire" in cascade:
                    ret *= self.sql_delete(
                        rs, models.QuestionnaireRow.database_table,
                        blockers["questionnaire"],
                    )
                if "field_definitions" in cascade:
                    deletor: CdEDBObject = {
                        'id': event_id,
                        'lodge_field_id': None,
                    }
                    ret *= self.sql_update(rs, models.Event.database_table, deletor)
                    with Silencer(rs):
                        for anid in blockers["field_definitions"]:
                            ret *= self._delete_event_field(rs, anid)
                if "custom_query_filters" in cascade:
                    with Silencer(rs):
                        for anid in blockers["custom_query_filters"]:
                            ret *= self.delete_custom_query_filter(rs, anid)
                if "orgas" in cascade:
                    ret *= self.sql_delete(rs, "event.orgas", blockers["orgas"])
                if "orga_tokens" in cascade:
                    orga_token_cascade = ("atime", "log")
                    with Silencer(rs):
                        for anid in blockers["orga_tokens"]:
                            ret *= self.delete_orga_token(rs, anid, orga_token_cascade)
                if "stored_queries" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.stored_queries", blockers["stored_queries"])
                if "log" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.log", blockers["log"])
                if "mailinglists" in cascade:
                    for anid in blockers["mailinglists"]:
                        deletor = {
                            'id': anid,
                            'is_active': False,
                            'event_id': None,
                            'event_part_group_id': None,
                        }
                        ret *= self.sql_update(
                            rs, models_ml.Mailinglist.database_table, deletor,
                        )

                blockers = self.delete_event_blockers(rs, event_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "event.events", event_id)
                self.event_log(rs, const.EventLogCodes.event_deleted,
                               event_id=None, change_note=event.title)
                # Delete non-pseudonymized event keeper only after internal work has
                # been concluded successfully. This is inside the Atomizer to
                # guarantee event keeper deletion if the deletion goes through.
                self.event_keeper_drop(rs, event_id)
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
            translations: dict[str, dict[int, int]]
            translations = collections.defaultdict(dict)
            for reg in data['event.registrations'].values():
                if reg['real_persona_id']:
                    translations['persona_id'][reg['persona_id']] = \
                        reg['real_persona_id']
            for field in data['event.field_definitions'].values():
                if field.get('entries'):
                    field['entries'] = list(field['entries'].items())
            extra_translations = {'course_instructor': 'course_id'}
            # Table name; name of foreign keys referencing this table
            tables = (('event.events', None),
                      ('event.event_parts', 'part_id'),
                      ('event.course_tracks', 'track_id'),
                      ('event.part_groups', 'part_group_id'),
                      ('event.part_group_parts', None),
                      ('event.track_groups', 'track_group_id'),
                      ('event.track_group_tracks', None),
                      ('event.courses', 'course_id'),
                      ('event.course_segments', None),
                      ('event.orgas', None),
                      ('event.field_definitions', 'field_id'),
                      ('event.event_fees', None),
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

            # Third fix the amounts owed for all registrations and check that
            # amount paid and payment were not changed.
            self._update_registrations_amount_owed(rs, data['id'])
            reg_ids = self.list_registrations(rs, data['id'])
            regs = self.get_registrations(rs, reg_ids)
            old_regs = current['event.registrations']
            if any(reg['amount_paid'] != old_regs[reg['id']]['amount_paid']
                   for reg in regs.values() if reg['id'] in old_regs):
                raise ValueError(n_("Change of amount_paid detected."))
            if any(reg['payment'] != old_regs[reg['id']]['payment']
                   for reg in regs.values() if reg['id'] in old_regs):
                raise ValueError(n_("Change of payment detected."))
            # check that amount_paid and payment of new registrations are default vals
            if any(reg['amount_paid'] != decimal.Decimal("0.00")
                   for reg in regs.values() if reg['id'] not in old_regs):
                raise ValueError(n_("Change of amount_paid detected."))
            if any(reg['payment'] is not None
                   for reg in regs.values() if reg['id'] not in old_regs):
                raise ValueError(n_("Change of payment detected."))

            # Forth unlock the event
            update = {
                'id': data['id'],
                'offline_lock': False,
            }
            ret *= self.sql_update(rs, "event.events", update)
            # TODO: Find a way to do this before everything is saved into the database
            self.delete_invalid_stored_event_queries(rs, data['id'])
            self._track_groups_sanity_check(rs, data['id'])
            self.event_log(rs, const.EventLogCodes.event_unlocked, data['id'])
            self.event_keeper_commit(
                rs, data['id'], "Entsperre Veranstaltung", after_change=True)
        return ret

    @access("event")
    def partial_import_event(self, rs: RequestState, data: CdEDBObject,
                             dryrun: bool, token: Optional[str] = None,
                             ) -> tuple[str, CdEDBObject]:
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

        def dict_diff(old: Mapping[Any, Any], new: Mapping[Any, Any],
                      ) -> tuple[dict[Any, Any], dict[Any, Any]]:
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
            all_current_data = self.event_keeper_commit(
                rs, data['id'], "Snapshot vor partiellem Import.")
            if all_current_data is None:
                all_current_data = self.partial_export_event(rs, data["id"])
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
            if not all_track_ids <= set(event.tracks):
                raise ValueError("Referential integrity of tracks violated.")

            all_part_ids = {
                key for registration in data.get('registrations', {}).values()
                if registration
                for key in registration.get('parts', {})}
            if not all_part_ids <= set(event.parts):
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

            used_course_ids: set[int] = set()
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
            IDMap = dict[int, int]

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

            def check_seg(track_id: int, delta: CdEDBOptionalMap,
                          original: CdEDBObjectMap) -> bool:
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
                                    x for x in event.tracks
                                    if check_seg(x, segments, orig_seg)]
                                changed_course['segments'] = new_segments
                                orig_active = [
                                    s for s, a in current['segments'].items()
                                    if a]
                                new_active = [
                                    x for x in event.tracks
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
                        personalized_fees = new.pop('personalized_fees', {})
                        new_id = self.create_registration(rs, new)
                        rmap[registration_id] = new_id
                        for fee_id, amount in personalized_fees.items():
                            self.set_personalized_fee_amount(rs, new_id, fee_id, amount)
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
                            personalized_fees = changed_reg.pop('personalized_fees', {})
                            self.set_registration(rs, changed_reg, change_note)
                            for fee_id, amount in personalized_fees.items():
                                self.set_personalized_fee_amount(
                                    rs, registration_id, fee_id, amount)
            if rdelta:
                total_delta['registrations'] = rdelta
                total_previous['registrations'] = rprevious

            result = get_hash(
                json_serialize(total_delta, sort_keys=True).encode('utf-8'),
                json_serialize(total_previous, sort_keys=True).encode('utf-8'),
            )
            if token is not None and result != token:
                raise PartialImportError("The delta changed.")
            if not dryrun:
                self._update_registrations_amount_owed(rs, data['id'])
                self.event_log(rs, const.EventLogCodes.event_partial_import,
                               data['id'], change_note=data.get('summary'))
                msg = build_msg("Importiere partiell", data.get('summary'))
                self.event_keeper_commit(rs, data['id'], msg, after_change=True)
        return result, total_delta
