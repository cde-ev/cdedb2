#!/usr/bin/env python3

"""This collection of helpers contains mainly low-level helper functions that are
used internally in the event backend."""

import collections
import copy
from pathlib import Path
from typing import (
    Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence, )

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    AbstractBackend, affirm_set_validation as affirm_set,
    affirm_validation_typed as affirm,
    internal, access,
)
from cdedb.common import (
    COURSE_TRACK_FIELDS, EVENT_FIELD_SPEC, EVENT_PART_FIELDS,
    FEE_MODIFIER_FIELDS, FIELD_DEFINITION_FIELDS,
    CdEDBObject, CdEDBObjectMap, CdEDBOptionalMap,
    DefaultReturnCode, DeletionBlockers, PathLike, PsycoJson,
    RequestState, mixed_existence_sorter, n_, unwrap, PrivilegeError,
)
from cdedb.validation import parse_date, parse_datetime


class EventBackendHelpers(AbstractBackend):
    """This collection of helpers contains mainly low-level helper functions that are
    used internally in the event backend."""
    realm = "event"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)
        self.minor_form_dir: Path
        self.minor_form_dir = self.conf['STORAGE_DIR'] / 'minor_form'

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def is_orga(self, rs: RequestState, *, event_id: int = None,
                course_id: int = None, registration_id: int = None) -> bool:
        """Check for orga privileges as specified in the event.orgas table.

        Exactly one of the inputs has to be provided.
        """
        num_inputs = sum(1 for anid in (event_id, course_id, registration_id)
                         if anid is not None)
        if num_inputs < 1:
            raise ValueError(n_("No input specified."))
        if num_inputs > 1:
            raise ValueError(n_("Too many inputs specified."))
        if course_id is not None:
            event_id = unwrap(self.sql_select_one(
                rs, "event.courses", ("event_id",), course_id))
        elif registration_id is not None:
            event_id = unwrap(self.sql_select_one(
                rs, "event.registrations", ("event_id",), registration_id))
        return event_id in rs.user.orga

    def event_log(self, rs: RequestState, code: const.EventLogCodes,
                  event_id: Optional[int], persona_id: int = None,
                  change_note: str = None, atomized: bool = True) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param atomized: Whether this function should enforce an atomized context
            to be present.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization by default.
        if atomized:
            self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "event_id": event_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "event.log", data)

    def _get_event_fields(self, rs: RequestState, event_id: int) -> CdEDBObjectMap:
        """
        Helper function to retrieve the custom field definitions of an event.
        This is required by multiple backend functions.

        :return: A dict mapping each event id to the dict of its fields
        """
        data = self.sql_select(
            rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
            [event_id], entity_key="event_id")
        return {d['id']: d for d in data}

    def _delete_course_track_blockers(self, rs: RequestState,
                                      track_id: int) -> DeletionBlockers:
        """Determine what keeps a course track from being deleted.

        Possible blockers:

        * course_segments: Courses that are offered in this track.
        * registration_tracks: Registration information for this track.
            This includes course_assignment and possible course instructors.
        * course_choices: Course choices for this track.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        track_id = affirm(vtypes.ID, track_id)
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

    def _delete_course_track(self, rs: RequestState, track_id: int,
                             cascade: Collection[str] = None
                             ) -> DefaultReturnCode:
        """Remove course track.

        This has to be called from an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        track_id = affirm(vtypes.ID, track_id)
        blockers = self._delete_course_track_blockers(rs, track_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "course track",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        # implicit atomized context.
        self.affirm_atomized_context(rs)
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
                           change_note=track["title"])
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "course track", "block": blockers.keys()})
        return ret

    def _set_tracks(self, rs: RequestState, event_id: int, part_id: int,
                    data: CdEDBOptionalMap) -> DefaultReturnCode:
        """Helper for handling of course tracks.

        This is basically uninlined code from ``set_event()``.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not data:
            return ret
        # implicit atomized context.
        self.affirm_atomized_context(rs)
        current = self.sql_select(rs, "event.course_tracks", COURSE_TRACK_FIELDS,
                                  (part_id,), entity_key="part_id")
        current = {e['id']: {k: v for k, v in e.items()if k not in {'id', 'part_id'}}
                   for e in current}
        existing = set(current)
        if not (existing >= {x for x in data if x > 0}):
            raise ValueError(n_("Non-existing tracks specified."))
        new = {x for x in data if x < 0}
        updated = {x for x in data if x > 0 and data[x] is not None}
        deleted = {x for x in data if x > 0 and data[x] is None}
        # new
        for x in mixed_existence_sorter(new):
            track_data = data[x]
            assert track_data is not None
            new_track = {
                "part_id": part_id,
                **track_data
            }
            new_track_id = self.sql_insert(rs, "event.course_tracks", new_track)
            ret *= new_track_id
            self.event_log(
                rs, const.EventLogCodes.track_added, event_id,
                change_note=track_data['title'])
            reg_data = self.sql_select(
                rs, "event.registrations", ("id",), (event_id,), "event_id")
            reg_ids = tuple(e['id'] for e in reg_data)
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
        for x in mixed_existence_sorter(updated):
            track_data = data[x]
            assert track_data is not None
            if current[x] != track_data:
                update = {
                    'id': x,
                    **track_data
                }
                ret *= self.sql_update(rs, "event.course_tracks", update)
                self.event_log(rs, const.EventLogCodes.track_updated, event_id,
                               change_note=track_data['title'])

        # deleted
        if deleted:
            cascade = ("course_segments", "registration_tracks",
                       "course_choices")
            for track_id in mixed_existence_sorter(deleted):
                self._delete_course_track(rs, track_id, cascade=cascade)
        return ret

    def _delete_field_values(self, rs: RequestState,
                             field_data: CdEDBObject) -> None:
        """
        Helper function for ``set_event()`` to clean up all the JSON data, when
        removing a field definition.

        :param field_data: The data of the field definition to be deleted
        """
        if field_data['association'] == const.FieldAssociations.registration:
            table = 'event.registrations'
        elif field_data['association'] == const.FieldAssociations.course:
            table = 'event.courses'
        elif field_data['association'] == const.FieldAssociations.lodgement:
            table = 'event.lodgements'
        else:
            raise RuntimeError(n_("This should not happen."))

        query = f"UPDATE {table} SET fields = fields - %s WHERE event_id = %s"
        self.query_exec(rs, query, (field_data['field_name'],
                                    field_data['event_id']))

    def _cast_field_values(self, rs: RequestState, field_data: CdEDBObject,
                           new_kind: const.FieldDatatypes) -> None:
        """
        Helper function for ``set_event()`` to cast the existing JSON data to
        a new datatype (or set it to None, if casting fails), when a field
        defintion is updated with a new datatype.

        :param field_data: The data of the field definition to be updated
        :param new_kind: The new kind/datatype of the field.
        """
        if field_data['association'] == const.FieldAssociations.registration:
            table = 'event.registrations'
        elif field_data['association'] == const.FieldAssociations.course:
            table = 'event.courses'
        elif field_data['association'] == const.FieldAssociations.lodgement:
            table = 'event.lodgements'
        else:
            raise RuntimeError(n_("This should not happen."))

        casters: Dict[const.FieldDatatypes, Callable[[Any], Any]] = {
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

    def _delete_event_part_blockers(self, rs: RequestState,
                                    part_id: int) -> DeletionBlockers:
        """Determine what keeps an event part from being deleted.

        Possible blockers:

        * fee_modifiers: A modification to the fee for this part depending on
                         registration fields.
        * course_tracks: A course track in this part.
        * registration_part: A registration part for this part.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        part_id = affirm(vtypes.ID, part_id)
        blockers = {}

        fee_modifiers = self.sql_select(
            rs, "event.fee_modifiers", ("id",), (part_id,),
            entity_key="part_id")
        if fee_modifiers:
            blockers["fee_modifiers"] = [e["id"] for e in fee_modifiers]

        course_tracks = self.sql_select(
            rs, "event.course_tracks", ("id",), (part_id,),
            entity_key="part_id")
        if course_tracks:
            blockers["course_tracks"] = [e["id"] for e in course_tracks]

        registration_parts = self.sql_select(
            rs, "event.registration_parts", ("id",), (part_id,),
            entity_key="part_id")
        if registration_parts:
            blockers["registration_parts"] = [
                e["id"] for e in registration_parts]

        return blockers

    def _delete_event_part(self, rs: RequestState, part_id: int,
                           cascade: Collection[str] = None
                           ) -> DefaultReturnCode:
        """Remove event part.

        This has to be called from an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        part_id = affirm(vtypes.ID, part_id)
        blockers = self._delete_event_part_blockers(rs, part_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "event part",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        # Implicit atomized context.
        self.affirm_atomized_context(rs)
        if cascade:
            if "fee_modifiers" in cascade:
                ret *= self.sql_delete(rs, "event.fee_modifiers",
                                       blockers["fee_modifiers"])
            if "course_tracks" in cascade:
                track_cascade = ("course_segments", "registration_tracks",
                                 "course_choices")
                for anid in blockers["course_tracks"]:
                    ret *= self._delete_course_track(rs, anid, track_cascade)
            if "registration_parts" in cascade:
                ret *= self.sql_delete(rs, "event.registration_parts",
                                       blockers["registration_parts"])
            blockers = self._delete_event_part_blockers(rs, part_id)

        if not blockers:
            part = self.sql_select_one(rs, "event.event_parts",
                                       ("event_id", "title"), part_id)
            assert part is not None
            ret *= self.sql_delete_one(rs, "event.event_parts", part_id)
            self.event_log(rs, const.EventLogCodes.part_deleted,
                           event_id=part["event_id"],
                           change_note=part["title"])
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "event part", "block": blockers.keys()})
        return ret

    @internal
    def _set_event_parts(self, rs: RequestState, event_id: int,
                         parts: CdEDBOptionalMap) -> DefaultReturnCode:
        """Helper for handling the setting of event parts..

        This is basically uninlined code from ``set_event()``.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not parts:
            return ret
        self.affirm_atomized_context(rs)
        has_registrations = self.has_registrations(rs, event_id)

        existing_parts = {unwrap(e) for e in self.sql_select(
            rs, "event.event_parts", ("id",), (event_id,), entity_key="event_id")}
        new_parts = {x for x in parts if x < 0}
        updated_parts = {x for x in parts if x > 0 and parts[x] is not None}
        deleted_parts = {x for x in parts if x > 0 and parts[x] is None}
        if has_registrations and (deleted_parts or new_parts):
            raise ValueError(
                n_("Registrations exist, modifications only."))
        if deleted_parts >= existing_parts | new_parts:
            raise ValueError(n_("At least one event part required."))

        # Do some additional validation for any given waitlist fields.
        waitlist_fields = {p['waitlist_field'] for p in parts.values()
                           if p and 'waitlist_field' in p} - {None}
        waitlist_field_data = self.sql_select(
            rs, "event.field_definitions", ("id", "event_id", "kind", "association"),
            waitlist_fields)
        if len(waitlist_fields) != len(waitlist_field_data):
            raise ValueError(n_("Unknown field."))
        for field in waitlist_field_data:
            self._validate_special_event_field(rs, event_id, "waitlist", field)

        for x in mixed_existence_sorter(new_parts):
            new_part = copy.deepcopy(parts[x])
            assert new_part is not None
            new_part['event_id'] = event_id
            tracks = new_part.pop('tracks', {})
            fee_modifiers = new_part.pop('fee_modifiers', {})
            new_id = self.sql_insert(rs, "event.event_parts", new_part)
            ret *= new_id
            self.event_log(rs, const.EventLogCodes.part_created, event_id,
                           change_note=new_part['title'])
            ret *= self._set_tracks(rs, event_id, new_id, tracks)
            ret *= self._set_event_fee_modifiers(rs, event_id, new_id, fee_modifiers)

        if updated_parts:
            # Retrieve current data, so we can check if anything actually changed.
            current_part_data = {e['id']: e for e in self.sql_select(
                rs, "event.event_parts", EVENT_PART_FIELDS, updated_parts)}
            for x in mixed_existence_sorter(updated_parts):
                updated = copy.deepcopy(parts[x])
                assert updated is not None
                updated['id'] = x
                tracks = updated.pop('tracks', {})
                fee_modifiers = updated.pop('fee_modifiers', {})
                if any(updated[k] != current_part_data[x][k] for k in updated):
                    ret *= self.sql_update(rs, "event.event_parts", updated)
                    self.event_log(rs, const.EventLogCodes.part_changed, event_id,
                                   change_note=current_part_data[x]['title'])
                ret *= self._set_tracks(rs, event_id, x, tracks)
                ret *= self._set_event_fee_modifiers(rs, event_id, x, fee_modifiers)

        if deleted_parts:
            # Recursively delete fee modifiers and tracks, but not registrations, since
            # this is only allowed if no registrations exist anyway.
            cascade = ("fee_modifiers", "course_tracks")
            for x in mixed_existence_sorter(deleted_parts):
                ret *= self._delete_event_part(rs, part_id=x, cascade=cascade)

        return ret

    def _delete_event_field_blockers(self, rs: RequestState,
                                     field_id: int) -> DeletionBlockers:
        """Determine what keeps an event part from being deleted.

        Possible blockers:

        * fee_modifiers:      A modification to the fee for a part depending on
                              this event field.
        * questionnaire_rows: A questionnaire row that uses this field.
        * lodge_fields:       An event that uses this field for lodging wishes.
        * camping_mat_fields: An event that uses this field for camping mat
                              wishes.
        * course_room_fields: An event that uses this field for course room
                              assignment.
        * waitlist_fields:    An event_part that uses this field for waitlist
                              management.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        field_id = affirm(vtypes.ID, field_id)
        blockers = {}

        fee_modifiers = self.sql_select(
            rs, "event.fee_modifiers", ("id",), (field_id,),
            entity_key="field_id")
        if fee_modifiers:
            blockers["fee_modifiers"] = [e["id"] for e in fee_modifiers]

        questionnaire_rows = self.sql_select(
            rs, "event.questionnaire_rows", ("id",), (field_id,),
            entity_key="field_id")
        if questionnaire_rows:
            blockers["questionnaire_rows"] = [
                e["id"] for e in questionnaire_rows]

        lodge_fields = self.sql_select(
            rs, "event.events", ("id",), (field_id,),
            entity_key="lodge_field")
        if lodge_fields:
            blockers["lodge_fields"] = [e["id"] for e in lodge_fields]

        camping_mat_fields = self.sql_select(
            rs, "event.events", ("id",), (field_id,),
            entity_key="camping_mat_field")
        if camping_mat_fields:
            blockers["camping_mat_fields"] = [
                e["id"] for e in camping_mat_fields]

        course_room_fields = self.sql_select(
            rs, "event.events", ("id",), (field_id,),
            entity_key="course_room_field")
        if course_room_fields:
            blockers["course_room_fields"] = [
                e["id"] for e in course_room_fields]

        waitlist_fields = self.sql_select(
            rs, "event.event_parts", ("id",), (field_id,),
            entity_key="waitlist_field")
        if waitlist_fields:
            blockers["waitlist_fields"] = [
                e["id"] for e in waitlist_fields]

        return blockers

    def _delete_event_field(self, rs: RequestState, field_id: int,
                            cascade: Collection[str] = None
                            ) -> DefaultReturnCode:
        """Remove an event field.

        This needs to be called from an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.

        """
        field_id = affirm(vtypes.ID, field_id)
        blockers = self._delete_event_field_blockers(rs, field_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "event field",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        # implicit atomized context.
        self.affirm_atomized_context(rs)
        if cascade:
            if "fee_modifiers" in cascade:
                ret *= self.sql_delete(rs, "event.fee_modifiers",
                                       blockers["fee_modifiers"])
            if "questionnaire_rows" in cascade:
                ret *= self.sql_delete(rs, "event.questionnaire_rows",
                                       blockers["fee_modifiers"])
            if "lodge_fields" in cascade:
                for anid in blockers["lodge_fields"]:
                    deletor = {
                        'id': anid,
                        'lodge_field': None,
                    }
                    ret += self.sql_update(rs, "event.events", deletor)
            if "camping_mat_fields" in cascade:
                for anid in blockers["camping_mat_fields"]:
                    deletor = {
                        'id': anid,
                        'camping_mat_field': None,
                    }
                    ret += self.sql_update(rs, "event.events", deletor)
            if "course_room_fields" in cascade:
                for anid in blockers["course_room_fields"]:
                    deletor = {
                        'id': anid,
                        'course_room_field': None,
                    }
                    ret += self.sql_update(rs, "event.events", deletor)
            if "waitlist_fields" in cascade:
                for anid in blockers["waitlist_fields"]:
                    deletor = {
                        'id': anid,
                        'waitlist_field': None,
                    }
                    ret += self.sql_update(rs, "event.event_parts", deletor)
            blockers = self._delete_event_field_blockers(rs, field_id)

        if not blockers:
            current = self.sql_select_one(
                rs, "event.field_definitions", FIELD_DEFINITION_FIELDS,
                field_id)
            assert current is not None
            ret *= self.sql_delete_one(rs, "event.field_definitions", field_id)
            self._delete_field_values(rs, current)
            self.event_log(
                rs, const.EventLogCodes.field_removed, current["event_id"],
                change_note=current["field_name"])
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "event part", "block": blockers.keys()})

        return ret

    @internal
    def _set_event_fields(self, rs: RequestState, event_id: int,
                          fields: CdEDBOptionalMap) -> DefaultReturnCode:

        """Helper for creating, updating or deleting custom event fields.

        This is basically uninlined code from ``set_event()``.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not fields:
            return ret
        self.affirm_atomized_context(rs)

        existing_fields = {unwrap(e) for e in self.sql_select(
            rs, "event.field_definitions", ("id",), (event_id,), entity_key="event_id")}
        new_fields = {x for x in fields if x < 0}
        updated_fields = {x for x in fields if x > 0 and fields[x] is not None}
        deleted_fields = {x for x in fields if x > 0 and fields[x] is None}
        if not updated_fields | deleted_fields <= existing_fields:
            raise ValueError(n_("Non-existing fields specified."))

        for x in mixed_existence_sorter(new_fields):
            new_field = copy.deepcopy(fields[x])
            assert new_field is not None
            new_field['event_id'] = event_id
            ret *= self.sql_insert(rs, "event.field_definitions", new_field)
            self.event_log(rs, const.EventLogCodes.field_added, event_id,
                           change_note=new_field['field_name'])

        if updated_fields:
            fee_modifier_fields = {unwrap(e) for e in self.sql_select(
                rs, "event.fee_modifiers", ("field_id",),
                updated_fields | deleted_fields,
                entity_key="field_id")}
            current_field_data = {e['id']: e for e in self.sql_select(
                rs, "event.field_definitions", FIELD_DEFINITION_FIELDS, updated_fields)}
            for x in mixed_existence_sorter(updated_fields):
                updated_field = copy.deepcopy(fields[x])
                assert updated_field is not None
                updated_field['id'] = x
                updated_field['event_id'] = event_id
                current = current_field_data[x]
                if any(updated_field[k] != current[k] for k in updated_field):
                    if x in fee_modifier_fields:
                        raise ValueError(n_("Cannot change field that is "
                                            "associated with a fee modifier."))
                    kind = current_field_data[x]['kind']
                    if updated_field.get('kind', kind) != kind:
                        self._cast_field_values(rs, current, updated_field['kind'])
                    ret *= self.sql_update(rs, "event.field_definitions", updated_field)
                    self.event_log(rs, const.EventLogCodes.field_updated, event_id,
                                   change_note=current_field_data[x]['field_name'])

        for x in mixed_existence_sorter(deleted_fields):
            # Only allow deletion of unused fields.
            self._delete_event_field(rs, x, cascade=None)

        return ret

    @internal
    def _set_event_fee_modifiers(self, rs: RequestState, event_id: int, part_id: int,
                                 modifiers: CdEDBOptionalMap) -> DefaultReturnCode:
        ret = 1
        if not modifiers:
            return ret
        self.affirm_atomized_context(rs)
        has_registrations = self.has_registrations(rs, event_id)

        existing_modifiers = {unwrap(e) for e in self.sql_select(
            rs, "event.fee_modifiers", ("id",), (part_id,), entity_key="part_id")}
        new_modifiers = {x for x in modifiers if x < 0}
        updated_modifiers = {x for x in modifiers if x > 0 and modifiers[x] is not None}
        deleted_modifiers = {x for x in modifiers if x > 0 and modifiers[x] is None}
        if not updated_modifiers | deleted_modifiers <= existing_modifiers:
            raise ValueError(n_("Non-existing fee modifier specified."))
        if has_registrations and (new_modifiers or deleted_modifiers):
            raise ValueError(n_("Cannot alter fee modifier once registrations exist."))

        # Do some additional validation of the linked fields.
        field_ids = {fm['field_id'] for fm in modifiers.values() if fm}
        field_data = self.sql_select(
            rs, "event.field_definitions", ("id", "event_id", "kind", "association"),
            field_ids)
        if len(field_ids) != len(field_data):
            raise ValueError(n_("Unknown field."))
        for field in field_data:
            self._validate_special_event_field(rs, event_id, "fee_modifier", field)

        # the order of deleting, updating and creating matters: The field of a deleted
        # modifier may be used in another existing or new modifier at the same request.
        if updated_modifiers or deleted_modifiers:
            current_modifier_data = {e['id']: e for e in self.sql_select(
                rs, "event.fee_modifiers", FEE_MODIFIER_FIELDS,
                updated_modifiers | deleted_modifiers)}

            if deleted_modifiers:
                ret *= self.sql_delete(rs, "event.fee_modifiers", deleted_modifiers)
                for x in mixed_existence_sorter(deleted_modifiers):
                    current = current_modifier_data[x]
                    self.event_log(rs, const.EventLogCodes.fee_modifier_deleted,
                                   event_id, change_note=current['modifier_name'])

            for x in mixed_existence_sorter(updated_modifiers):
                updated_modifier = copy.deepcopy(modifiers[x])
                assert updated_modifier is not None
                updated_modifier['id'] = x
                updated_modifier['part_id'] = part_id
                current = current_modifier_data[x]
                if any(updated_modifier[k] != current[k] for k in updated_modifier):
                    if has_registrations:
                        raise ValueError(n_(
                            "Cannot alter fee modifier once registrations exist."))
                    ret *= self.sql_update(rs, "event.fee_modifiers", updated_modifier)
                    self.event_log(rs, const.EventLogCodes.fee_modifier_changed,
                                   event_id, change_note=current['modifier_name'])

        for x in mixed_existence_sorter(new_modifiers):
            new_modifier = copy.deepcopy(modifiers[x])
            assert new_modifier is not None
            new_modifier['part_id'] = part_id
            ret *= self.sql_insert(rs, "event.fee_modifiers", new_modifier)
            self.event_log(rs, const.EventLogCodes.fee_modifier_created, event_id,
                           change_note=new_modifier['modifier_name'])

        return ret

    @internal
    def _validate_special_event_field(self, rs: RequestState, event_id: int,
                                      field_name: str, field_data: CdEDBObject) -> None:
        """Uninlined and deduplicated validation for special event fields.

        This will raise an error if the field is unfit.

        Valid values for `field_name` are "lodge_field", "camping_mat_field",
        "course_room_field", "waitlist" and "fee_modifier".
        """
        self.affirm_atomized_context(rs)
        legal_field_kinds, legal_field_associations = EVENT_FIELD_SPEC[field_name]
        if (field_data["event_id"] != event_id
                or field_data["kind"] not in legal_field_kinds
                or field_data["association"] not in legal_field_associations):
            raise ValueError(n_("Unfit field for %(field)s."), {'field': field_name})

    @access("event")
    def has_registrations(self, rs: RequestState, event_id: int) -> bool:
        """Determine whether there exist registrations for an event."""
        event_id = affirm(vtypes.ID, event_id)
        if not self.is_orga(rs, event_id=event_id) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        query = "SELECT COUNT(*) FROM event.registrations WHERE event_id = %s LIMIT 1"
        return bool(unwrap(self.query_one(rs, query, (event_id,))))

    def _get_event_course_segments(self, rs: RequestState,
                                   event_id: int) -> Dict[int, List[int]]:
        """
        Helper function to get course segments of all courses of an event.

        Required for _set_course_choices().

        :returns: A dict mapping each course id (of the event) to a list of
            track ids (which correspond to its segments)
        """
        query = """
            SELECT courses.id, array_agg(segments.track_id) AS segments
            FROM (
                event.courses AS courses
                LEFT OUTER JOIN event.course_segments AS segments
                ON courses.id = segments.course_id
            )
            WHERE courses.event_id = %s
            GROUP BY courses.id"""
        return {row['id']: row['segments']
                for row in self.query_all(rs, query, (event_id,))}

    def _set_course_choices(self, rs: RequestState, registration_id: int,
                            track_id: int, choices: Optional[Sequence[int]],
                            course_segments: Mapping[int, Collection[int]],
                            new_registration: bool = False
                            ) -> DefaultReturnCode:
        """Helper for handling of course choices.

        This is basically uninlined code from ``set_registration()``.

        :note: This has to be called inside an atomized context.

        :param course_segments: Dict, course segments, as returned by
            _get_event_course_segments()
        :param new_registration: Performance optimization for creating
            registrations: If true, the deletion of existing choices is skipped.
        """
        ret = 1
        self.affirm_atomized_context(rs)
        if choices is None:
            # Nothing specified, hence nothing to do
            return ret
        for course_id in choices:
            if track_id not in course_segments[course_id]:
                raise ValueError(n_("Wrong track for course."))
        if not new_registration:
            query = ("DELETE FROM event.course_choices"
                     " WHERE registration_id = %s AND track_id = %s")
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

    def _get_registration_info(self, rs: RequestState,
                               reg_id: int) -> Optional[CdEDBObject]:
        """Helper to retrieve basic registration information."""
        return self.sql_select_one(
            rs, "event.registrations", ("persona_id", "event_id"), reg_id)

    @classmethod
    def _translate(cls, data: CdEDBObject,
                   translations: Dict[str, Dict[int, int]],
                   extra_translations: Dict[str, str] = None
                   ) -> CdEDBObject:
        """Helper to do the actual translation of IDs which got out of sync.

        This does some additional sanitizing besides applying the
        translation.
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
                    cls._translate(ret[x], translations, extra_translations))
        if ret.get('real_persona_id'):
            ret['real_persona_id'] = None
        if ret.get('amount_owed'):
            del ret['amount_owed']
        return ret

    def _synchronize_table(self, rs: RequestState, table: str,
                           data: CdEDBObjectMap, current: CdEDBObjectMap,
                           translations: Dict[str, Dict[int, int]],
                           entity: str = None,
                           extra_translations: Dict[str, str] = None
                           ) -> DefaultReturnCode:
        """Replace one data set in a table with another.

        This is a bit involved, since both DB instances may have been
        modified, so that conflicting primary keys were created. Thus we
        have a snapshot ``current`` of the state at locking time and
        apply the diff to the imported state in ``data``. Any IDs which
        were not previously present in the DB into which we import have
        to be kept track of -- this is done in ``translations``.

        :param data: Data set to put in.
        :param current: Current state.
        :param translations: IDs which got out of sync during offline usage.
        :param entity: Name of IDs this table is referenced as. Any of the
          primary keys which are processed here, that got out of sync are
          added to the corresponding entry in ``translations``
        :param extra_translations: Additional references which do not use a
          standard name.
        """
        extra_translations = extra_translations or {}
        ret = 1
        for anid in set(current) - set(data):
            # we do not delete additional log messages; this can mainly
            # happen if somebody gets the order of downloading an export and
            # locking the event wrong
            if table != 'event.log':
                ret *= self.sql_delete_one(rs, table, anid)
        for e in data.values():
            if e != current.get(e['id']):
                new_e = self._translate(e, translations, extra_translations)
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
