#!/usr/bin/env python3

"""
The `EventLowLevelBackend` class provides a collection of internal low-level helpers
used by the `EventBaseBackend` and its subclasses.
"""

import abc
import collections
import copy
import dataclasses
from collections.abc import Collection
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import phonenumbers

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
import cdedb.models.event as models
import cdedb.models.ml as models_ml
from cdedb.backend.common import (
    AbstractBackend,
    access,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    internal,
)
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    CdEDBOptionalMap,
    DefaultReturnCode,
    DeletionBlockers,
    PsycoJson,
    RequestState,
    now,
    parse_date,
    parse_datetime,
    parse_phone,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import (
    EVENT_PART_FIELDS,
    REGISTRATION_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.privileges import (
    EventPrivileges,
    is_privileged_event as is_privileged,
)
from cdedb.common.sorting import mixed_existence_sorter
from cdedb.database.query import DatabaseValue_s, ParamDict
from cdedb.fee_condition_parser.evaluation import get_referenced_names


@dataclasses.dataclass
class EventFeesPerEntity:
    """Simple container for data on event fee references.

    Each member is a map of entities to a set of fees that reference that entity.
    """

    fields: dict[int, set[int]]
    parts: dict[int, set[int]]


class EventLowLevelBackend(AbstractBackend):
    realm = "event"

    def __init__(self) -> None:
        super().__init__()
        self.minor_form_dir: Path = self.conf['STORAGE_DIR'] / 'minor_form'

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @internal
    def event_log(
        self,
        rs: RequestState,
        code: const.EventLogCodes,
        event_id: Optional[int],
        persona_id: Optional[int] = None,
        change_note: Optional[str] = None,
        atomized: bool = True,
    ) -> DefaultReturnCode:
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
            "ctime": now(),
        }
        return self.sql_insert(rs, "event.log", data)

    @internal
    def _get_event_fields(
        self,
        rs: RequestState,
        event_id: int,
        field_ids: Collection[int] | None = None,
    ) -> models.CdEDataclassMap[models.EventField]:
        """Helper function to retrieve the custom field definitions for some events.

        This is used by multiple backend functions.

        :param field_ids: If given, only include fields with these ids.
        :return: A dict of (all or some) of one events fields.
            Note that these dataclass instances **do not** have their event field set
            and are thus not save to use in all circumstances.
        """
        data = self.query_all(rs, *models.EventField.get_select_query([event_id]))
        if field_ids is not None:
            data = tuple(e for e in data if e["id"] in field_ids)
        return models.EventField.many_from_database(data)

    @internal
    def _get_event_field(
        self, rs: RequestState, field_id: int, *, event_id: int
    ) -> models.EventField:
        fields = self._get_event_fields(rs, event_id, [field_id])
        if field_id not in fields:
            raise KeyError(n_("Unknown field for this event."))
        return fields[field_id]

    @internal
    def _delete_course_track_blockers(
        self, rs: RequestState, track_id: int
    ) -> DeletionBlockers:
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
            rs, "event.course_segments", ("id",), (track_id,), entity_key="track_id"
        )
        if course_segments:
            blockers["course_segments"] = [e["id"] for e in course_segments]

        reg_tracks = self.sql_select(
            rs, "event.registration_tracks", ("id",), (track_id,), entity_key="track_id"
        )
        if reg_tracks:
            blockers["registration_tracks"] = [e["id"] for e in reg_tracks]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (track_id,), entity_key="track_id"
        )
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        track_group_tracks = self.sql_select(
            rs, "event.track_group_tracks", ("id",), (track_id,), entity_key="track_id"
        )
        if track_group_tracks:
            blockers["track_group_tracks"] = [e["id"] for e in track_group_tracks]

        return blockers

    @internal
    def _delete_course_track(
        self,
        rs: RequestState,
        track_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Helper to remove a course track.

        This is used by `_set_tracks` and `_delete_event_part`.

        :note: This has to be called inside an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        track_id = affirm(vtypes.ID, track_id)
        blockers = self._delete_course_track_blockers(rs, track_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "course track",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        # implicit atomized context.
        self.affirm_atomized_context(rs)
        if cascade:
            if "course_segments" in cascade:
                ret *= self.sql_delete(
                    rs, "event.course_segments", blockers["course_segments"]
                )
            if "registration_tracks" in cascade:
                ret *= self.sql_delete(
                    rs, "event.registration_tracks", blockers["registration_tracks"]
                )
            if "course_choices" in cascade:
                ret *= self.sql_delete(
                    rs, "event.course_choices", blockers["course_choices"]
                )
            if "track_group_tracks" in cascade:
                ret *= self.sql_delete(
                    rs, "event.track_group_tracks", blockers["track_group_tracks"]
                )

            blockers = self._delete_course_track_blockers(rs, track_id)

        if not blockers:
            track = unwrap(
                self.sql_select(
                    rs, "event.course_tracks", ("part_id", "title"), (track_id,)
                )
            )
            part = unwrap(
                self.sql_select(
                    rs, "event.event_parts", ("event_id",), (track["part_id"],)
                )
            )
            ret *= self.sql_delete_one(rs, "event.course_tracks", track_id)
            self.event_log(
                rs,
                const.EventLogCodes.track_removed,
                event_id=part["event_id"],
                change_note=track["title"],
            )
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "course track", "block": blockers.keys()},
            )
        return ret

    @internal
    def _set_tracks(
        self, rs: RequestState, event_id: int, part_id: int, data: CdEDBOptionalMap
    ) -> DefaultReturnCode:
        """Helper for creating, updating and/or deleting of tracks for one event part.

        This is used by `_set_event_parts`.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not data:
            return ret
        # implicit atomized context.
        self.affirm_atomized_context(rs)
        current = self.sql_select(
            rs,
            "event.course_tracks",
            models.CourseTrack.database_fields(),
            (part_id,),
            entity_key="part_id",
        )
        current = {e['id']: e for e in current}
        existing = set(current)
        if not (existing >= {x for x in data if x > 0}):
            raise ValueError(n_("Non-existing tracks specified."))
        new = {x for x in data if x < 0}
        updated = {x for x in data if x > 0 and data[x] is not None}
        deleted = {x for x in data if x > 0 and data[x] is None}

        # new
        for x in mixed_existence_sorter(new):
            new_track = copy.copy(data[x])
            assert new_track is not None
            new_track['part_id'] = part_id
            new_track_id = self.sql_insert(rs, "event.course_tracks", new_track)
            ret *= new_track_id
            self.event_log(
                rs,
                const.EventLogCodes.track_added,
                event_id,
                change_note=new_track['title'],
            )
            reg_data = self.sql_select(
                rs, "event.registrations", ("id",), (event_id,), entity_key="event_id"
            )
            reg_ids = tuple(e['id'] for e in reg_data)
            for reg_id in reg_ids:
                reg_track = {
                    'registration_id': reg_id,
                    'track_id': new_track_id,
                    'course_id': None,
                    'course_instructor': None,
                }
                ret *= self.sql_insert(rs, "event.registration_tracks", reg_track)

        # updated
        for x in mixed_existence_sorter(updated):
            updated_track = copy.copy(data[x])
            assert updated_track is not None
            if any(updated_track[k] != current[x][k] for k in updated_track):
                updated_track['id'] = x
                updated_track['part_id'] = part_id
                ret *= self.sql_update(rs, "event.course_tracks", updated_track)
                self.event_log(
                    rs,
                    const.EventLogCodes.track_updated,
                    event_id,
                    change_note=updated_track.get('title', current[x]['title']),
                )

        # deleted
        if deleted:
            cascade = ("course_segments", "registration_tracks", "course_choices")
            for track_id in mixed_existence_sorter(deleted):
                self._delete_course_track(rs, track_id, cascade=cascade)
        return ret

    @internal
    def _delete_field_values(self, rs: RequestState, field: models.EventField) -> None:
        """Helper function for deleting the data stored in a custom data field.

        This is used by `_delete_event_field`, when successfully deleting a field
        definition.

        :param field: The field whose values are to be deleted
        """

        query = f"""
            UPDATE {field.association.database_table}
            SET fields = fields - %(field_name)s
            WHERE event_id = %(event_id)s
        """
        params: ParamDict = {"field_name": field.field_name, "event_id": field.event_id}
        self.query_exec(rs, query, params)

    @internal
    def _cast_field_values(self, rs: RequestState, field: models.EventField) -> None:
        """Helper to cast existing field data to a new type.

        This is used by `_set_event_fields`, if the datatype of an existing field is
        changed.

        If casting fails, the value will be set to `None`, causing data to be lost.

        :note: This has to be called inside an atomized context.

        :param field: The field whose values are to be updated
        """

        casters: dict[const.FieldDatatypes, Callable[[Any], Any]] = {
            const.FieldDatatypes.int: int,
            const.FieldDatatypes.str: str,
            const.FieldDatatypes.float: float,
            const.FieldDatatypes.date: parse_date,
            const.FieldDatatypes.datetime: parse_datetime,
            const.FieldDatatypes.bool: bool,
            const.FieldDatatypes.non_negative_int: (
                lambda x: affirm(vtypes.NonNegativeInt, x)
            ),
            const.FieldDatatypes.non_negative_float: (
                lambda x: affirm(vtypes.NonNegativeFloat, x)
            ),
            # normalized string: normalize on write
            const.FieldDatatypes.phone: parse_phone,
            const.FieldDatatypes.iban: lambda x: affirm(vtypes.IBAN, x),
        }

        self.affirm_atomized_context(rs)
        data = self.sql_select(
            rs,
            field.association.database_table,
            ("id", "fields"),
            [field.event_id],
            entity_key='event_id',
        )
        for entry in data:
            fdata = entry['fields']
            value = fdata.get(field.field_name, None)
            if value is None:
                continue
            try:
                new_value = casters[field.kind](value)
            except (ValueError, TypeError, phonenumbers.NumberParseException):
                new_value = None
            fdata[field.field_name] = new_value
            new = {
                'id': entry['id'],
                'fields': PsycoJson(fdata),
            }
            self.sql_update(rs, field.association.database_table, new)

    class _NewGetEventProtocol(Protocol):
        def __call__(self, rs: RequestState, event_id: int) -> models.Event: ...

    get_event: _NewGetEventProtocol

    @access("event")
    def get_event_fees_per_entity(
        self, rs: RequestState, event_id: int
    ) -> EventFeesPerEntity:
        """Retrieve maps of entites to all event fees, referencing that entity."""
        event = self.get_event(rs, event_id)
        field_names_to_id: dict[str, int] = {
            e.field_name: e.id for e in event.fields.values()
        }
        part_names_to_id: dict[str, int] = {
            e.shortname: e.id for e in event.parts.values()
        }

        event_fee_references = {
            e.id: get_referenced_names(
                fcp_parsing.parse(e.condition) if e.condition else None
            )
            for e in event.fees.values()
        }

        fields: dict[int, set[int]] = {
            field_id: set() for field_id in field_names_to_id.values()
        }
        parts: dict[int, set[int]] = {
            part_id: set() for part_id in part_names_to_id.values()
        }
        for fee_id, rn in event_fee_references.items():
            for fn in rn.field_names:
                fields[field_names_to_id[fn]].add(fee_id)
            for pn in rn.part_names:
                parts[part_names_to_id[pn]].add(fee_id)

        return EventFeesPerEntity(
            fields=fields,
            parts=parts,
        )

    @abc.abstractmethod
    def delete_event_fee(self, rs: RequestState, fee_id: int) -> DefaultReturnCode: ...

    @internal
    def _delete_event_part_blockers(
        self, rs: RequestState, part_id: int
    ) -> DeletionBlockers:
        """Determine what keeps an event part from being deleted.

        Possible blockers:

        * event_fees:        An event fee referencing this part.
        * course_tracks:     A course track in this part.
        * registration_part: A registration part for this part.
        * part_group_parts:  A link to a part group.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        part_id = affirm(vtypes.ID, part_id)
        blockers = {}

        part = self.sql_select_one(
            rs, "event.event_parts", ("event_id", "title"), part_id
        )
        assert part is not None

        event_fees_per_part = self.get_event_fees_per_entity(rs, part['event_id']).parts
        if fee_ids := event_fees_per_part[part_id]:
            blockers["event_fees"] = list(fee_ids)

        course_tracks = self.sql_select(
            rs, "event.course_tracks", ("id",), (part_id,), entity_key="part_id"
        )
        if course_tracks:
            blockers["course_tracks"] = [e["id"] for e in course_tracks]

        registration_parts = self.sql_select(
            rs, "event.registration_parts", ("id",), (part_id,), entity_key="part_id"
        )
        if registration_parts:
            blockers["registration_parts"] = [e["id"] for e in registration_parts]

        part_group_parts = self.sql_select(
            rs, "event.part_group_parts", ("id",), (part_id,), entity_key="part_id"
        )
        if part_group_parts:
            blockers["part_group_parts"] = [e["id"] for e in part_group_parts]

        return blockers

    @internal
    def _delete_event_part(
        self, rs: RequestState, part_id: int, cascade: Optional[Collection[str]] = None
    ) -> DefaultReturnCode:
        """Helper to remove one event part.

        Used by `delete_event` and `_set_event_parts`.

        :note: This has to be called inside an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        part_id = affirm(vtypes.ID, part_id)
        blockers = self._delete_event_part_blockers(rs, part_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "event part",
                    "block": blockers.keys() - cascade,
                },
            )

        part = self.sql_select_one(
            rs, "event.event_parts", ("event_id", "title"), part_id
        )
        assert part is not None

        ret = 1
        # Implicit atomized context.
        self.affirm_atomized_context(rs)
        if cascade:
            if "course_tracks" in cascade:
                track_cascade = (
                    "course_segments",
                    "registration_tracks",
                    "course_choices",
                    "track_group_tracks",
                )
                for anid in blockers["course_tracks"]:
                    ret *= self._delete_course_track(rs, anid, track_cascade)
            if "registration_parts" in cascade:
                ret *= self.sql_delete(
                    rs, "event.registration_parts", blockers["registration_parts"]
                )
            if "part_group_parts" in cascade:
                ret *= self.sql_delete(
                    rs, "event.part_group_parts", blockers["part_group_parts"]
                )
            if "event_fees" in cascade:
                for fee_id in blockers["event_fees"]:
                    ret *= self.delete_event_fee(rs, fee_id)
            blockers = self._delete_event_part_blockers(rs, part_id)

        if not blockers:
            ret *= self.sql_delete_one(rs, "event.event_parts", part_id)
            self.event_log(
                rs,
                const.EventLogCodes.part_deleted,
                event_id=part["event_id"],
                change_note=part["title"],
            )
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "event part", "block": blockers.keys()},
            )
        return ret

    @internal
    def _set_event_parts(
        self, rs: RequestState, event_id: int, parts: CdEDBOptionalMap
    ) -> DefaultReturnCode:
        """Helper for handling the setting of event parts.

        Used by `set_event`.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not parts:
            return ret
        self.affirm_atomized_context(rs)

        existing_parts = {
            unwrap(e)
            for e in self.sql_select(
                rs, "event.event_parts", ("id",), (event_id,), entity_key="event_id"
            )
        }
        new_parts = {x for x in parts if x < 0}
        updated_parts = {x for x in parts if x > 0 and parts[x] is not None}
        deleted_parts = {x for x in parts if x > 0 and parts[x] is None}
        if self.has_registrations(rs, event_id) and deleted_parts:
            raise ValueError(n_("Registrations exist, cannot delete event parts."))
        if deleted_parts >= existing_parts | new_parts:
            raise ValueError(n_("At least one event part required."))

        self.sql_defer_constraints(rs, "event.event_parts_event_id_shortname_key")

        for x in mixed_existence_sorter(new_parts):
            new_part = copy.deepcopy(parts[x])
            assert new_part is not None
            new_part['event_id'] = event_id
            tracks = new_part.pop('tracks', {})
            new_id = self.sql_insert(rs, "event.event_parts", new_part)
            ret *= new_id
            self.event_log(
                rs,
                const.EventLogCodes.part_created,
                event_id,
                change_note=new_part['title'],
            )
            ret *= self._set_tracks(rs, event_id, new_id, tracks)
            reg_data = self.sql_select(
                rs, "event.registrations", ("id",), (event_id,), entity_key="event_id"
            )
            reg_ids = tuple(e['id'] for e in reg_data)
            for reg_id in reg_ids:
                reg_part = {
                    'registration_id': reg_id,
                    'part_id': new_id,
                    'status': const.RegistrationPartStati.not_applied,
                }
                ret *= self.sql_insert(rs, "event.registration_parts", reg_part)

        if updated_parts:
            # Retrieve current data, so we can check if anything actually changed.
            current_part_data = {
                e['id']: e
                for e in self.sql_select(
                    rs, "event.event_parts", EVENT_PART_FIELDS, updated_parts
                )
            }

            for x in mixed_existence_sorter(updated_parts):
                updated = copy.deepcopy(parts[x])
                assert updated is not None
                tracks = updated.pop('tracks', {})
                updated = {
                    k: v for k, v in updated.items() if v != current_part_data[x][k]
                }
                if updated:
                    updated['id'] = x
                    ret *= self.sql_update(rs, "event.event_parts", updated)
                    self.event_log(
                        rs,
                        const.EventLogCodes.part_changed,
                        event_id,
                        change_note=updated.get('title', current_part_data[x]['title']),
                    )
                ret *= self._set_tracks(rs, event_id, x, tracks)

            # Construct a dict of part shortname changes.
            new_part_data = {
                e['id']: e
                for e in self.sql_select(
                    rs, "event.event_parts", EVENT_PART_FIELDS, updated_parts
                )
            }
            changed_shortnames = {
                old_shortname: new_shortname
                for part_id, part in new_part_data.items()
                if (old_shortname := current_part_data[part_id]['shortname'])
                != (new_shortname := part['shortname'])
            }
            if changed_shortnames:
                # Substitute changed shortnames in existing fee conditions.
                q = """SELECT id, condition FROM event.event_fees WHERE event_id = %s"""
                fee_conditions: dict[int, str] = {
                    e['id']: e['condition']
                    for e in self.query_all(rs, q, (event_id,))
                    if e['condition']
                }

                # Update any fee conditions that changed
                #  (i.e. those referencing a part which got a new shortname).
                for fee_id, condition in fee_conditions.items():
                    parse_result = fcp_parsing.parse(condition)
                    new_condition = fcp_roundtrip.serialize(
                        parse_result, part_substitutions=changed_shortnames
                    )
                    if new_condition != condition:
                        log_msg = (
                            f"Replacing fee ({fee_id}): '{condition}' with"
                            f" '{new_condition}' due to part shortname changes."
                        )
                        self.logger.debug(log_msg)
                        self.sql_update(
                            rs,
                            "event.event_fees",
                            {'id': fee_id, 'condition': new_condition},
                        )

        if deleted_parts:
            # Recursively delete fee modifiers and tracks, but not registrations, since
            # this is only allowed if no registrations exist anyway.
            cascade = ("course_tracks", "part_group_parts", "event_fees")
            for x in mixed_existence_sorter(deleted_parts):
                ret *= self._delete_event_part(rs, part_id=x, cascade=cascade)

        self._track_groups_sanity_check(rs, event_id)

        return ret

    @internal
    def _delete_part_group_blockers(
        self, rs: RequestState, part_group_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a part group from being deleted.

        Possible blockers:

        * part_group_parts: A link between an event part and the part group.
        * mailinglists: A mailinglist limited by this part group.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        part_group_id = affirm(vtypes.ID, part_group_id)
        blockers = {}

        part_group_parts = self.sql_select(
            rs,
            "event.part_group_parts",
            ("id",),
            (part_group_id,),
            entity_key="part_group_id",
        )
        if part_group_parts:
            blockers["part_group_parts"] = [e["id"] for e in part_group_parts]

        mailinglists = self.sql_select(
            rs,
            models_ml.Mailinglist.database_table,
            ("id",),
            (part_group_id,),
            entity_key="event_part_group_id",
        )
        if mailinglists:
            blockers["mailinglists"] = [e["id"] for e in mailinglists]

        return blockers

    @internal
    def _delete_part_group(
        self,
        rs: RequestState,
        part_group_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Helper to delete one part group.

        :note: This has to be called inside an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        part_group_id = affirm(vtypes.ID, part_group_id)
        blockers = self._delete_part_group_blockers(rs, part_group_id)
        cascade = affirm_set(str, cascade or set()) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),  # pragma: no cover
                {
                    "type": "part group",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        self.affirm_atomized_context(rs)
        if cascade:
            if "part_group_parts" in cascade:
                ret *= self.sql_delete(
                    rs, "event.part_group_parts", blockers["part_group_parts"]
                )
            if "mailinglists" in cascade:
                for anid in blockers["mailinglists"]:
                    deletor = {
                        'id': anid,
                        'is_active': False,
                        'event_part_group_id': None,
                    }
                    ret *= self.sql_update(
                        rs,
                        models_ml.Mailinglist.database_table,
                        deletor,
                    )

            blockers = self._delete_part_group_blockers(rs, part_group_id)

        if not blockers:
            data = self.query_one(
                rs,
                *models.PartGroup.get_select_query((part_group_id,), entity_key="id"),
            )
            if data is None:  # pragma: no cover
                return 0
            part_group = models.PartGroup.from_database(data)
            ret *= self.sql_delete_one(
                rs, models.PartGroup.database_table, part_group_id
            )
            self.event_log(
                rs,
                const.EventLogCodes.part_group_deleted,
                event_id=part_group.event_id,
                change_note=f"{part_group.title} ({part_group.constraint_type.name})",
            )
        else:
            raise ValueError(  # pragma: no cover
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "part group", "block": blockers.keys()},
            )
        return ret

    @internal
    def _delete_track_group_blockers(
        self, rs: RequestState, track_group_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a track group from being deleted.

        Possible blockers:

        * track_group_tracks: A link between an course track and the track group.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        track_group_id = affirm(vtypes.ID, track_group_id)
        blockers = {}

        track_group_tracks = self.sql_select(
            rs,
            "event.track_group_tracks",
            ("id",),
            (track_group_id,),
            entity_key="track_group_id",
        )
        if track_group_tracks:
            blockers["track_group_tracks"] = [e["id"] for e in track_group_tracks]

        return blockers

    @internal
    def _delete_track_group(
        self,
        rs: RequestState,
        track_group_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Helper to delete one track group.

        :note: This has to be called inside an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        track_group_id = affirm(vtypes.ID, track_group_id)
        blockers = self._delete_track_group_blockers(rs, track_group_id)
        cascade = affirm_set(str, cascade or set()) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),  # pragma: no cover
                {
                    "type": "track group",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        self.affirm_atomized_context(rs)
        if cascade:
            if "track_group_tracks" in cascade:
                ret *= self.sql_delete(
                    rs, "event.track_group_tracks", blockers["track_group_tracks"]
                )

            blockers = self._delete_track_group_blockers(rs, track_group_id)

        if not blockers:
            track_group = self.sql_select_one(
                rs,
                models.TrackGroup.database_table,
                models.TrackGroup.database_fields(),
                track_group_id,
            )
            if track_group is None:  # pragma: no cover
                return 0
            type_ = const.CourseTrackGroupType(track_group['constraint_type'])
            ret *= self.sql_delete_one(
                rs, models.TrackGroup.database_table, track_group_id
            )
            self.event_log(
                rs,
                const.EventLogCodes.track_group_deleted,
                event_id=track_group["event_id"],
                change_note=f"{track_group['title']} ({type_.name})",
            )
        else:
            raise ValueError(  # pragma: no cover
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "track group", "block": blockers.keys()},
            )
        return ret

    def _track_groups_sanity_check(self, rs: RequestState, event_id: int) -> None:
        """Perform checks on the sanity of all track groups."""

        #######################
        # CCS specific checks #
        #######################

        # Check that all tracks belonging to CCS groups have the same number of choices.
        query = """
            SELECT id
            FROM (
                -- Inner SELECT will have one row per different configuration per group.
                SELECT tg.id, ct.num_choices, ct.min_choices
                FROM event.track_groups AS tg
                    LEFT JOIN event.track_group_tracks AS tgt on tg.id = tgt.track_group_id
                    LEFT JOIN event.course_tracks AS ct on ct.id = tgt.track_id
                WHERE tg.event_id = %s AND tg.constraint_type = %s
                GROUP BY tg.id, ct.num_choices, ct.min_choices
            ) AS tmp
            GROUP BY id
            -- Filter for ids occurring multiple times.
            HAVING COUNT(id) > 1
        """
        params = (event_id, const.CourseTrackGroupType.course_choice_sync)
        if self.query_all(rs, query, params):
            raise ValueError(n_("Synced tracks must have same number of choices."))

        # Check that no track is linked to more than one CCS group.
        query = """
            SELECT track_id
            FROM event.track_group_tracks AS tgt
                JOIN event.track_groups AS tg ON tg.id = tgt.track_group_id
            WHERE tg.event_id = %s AND tg.constraint_type = %s
            GROUP BY tgt.track_id
            -- Filter for tracks with more than one CCS group.
            HAVING COUNT(tgt.track_group_id) > 1
        """
        params = (event_id, const.CourseTrackGroupType.course_choice_sync)
        if self.query_all(rs, query, params):
            raise ValueError(n_("Track synced to more than one ccs track group."))

        # Check that course choices are consistently synced across CCS groups.
        query = """
            SELECT track_group_id, registration_id, COUNT(*)
            FROM (
                -- Per reg_track gather ordered choices, eliminating duplicates.
                SELECT DISTINCT rt.registration_id, tg.id AS track_group_id, rt.course_instructor,
                    ARRAY_REMOVE(ARRAY_AGG(cc.course_id ORDER BY cc.rank ASC), NULL) AS choices
                FROM event.registration_tracks AS rt
                    LEFT JOIN event.track_group_tracks AS tgt ON rt.track_id = tgt.track_id
                    LEFT JOIN event.track_groups AS tg ON tgt.track_group_id = tg.id
                    LEFT JOIN event.course_choices AS cc ON rt.track_id = cc.track_id AND rt.registration_id = cc.registration_id
                WHERE tg.event_id = %s AND tg.constraint_type = %s
                GROUP BY rt.registration_id, rt.track_id, rt.course_instructor, tg.id
            ) AS tmp
            GROUP BY registration_id, track_group_id
            -- Filter for non-unique combinations.
            HAVING COUNT(*) > 1
        """
        params = (event_id, const.CourseTrackGroupType.course_choice_sync)
        if self.query_all(rs, query, params):
            raise ValueError(n_("Incompatible course choices present."))

    @access("event")
    def may_create_ccs_group(
        self,
        rs: RequestState,
        track_ids: Collection[int],
    ) -> bool:
        """Determine whether a CCS group with the given tracks may be created.

        Performs more involved checks which can not be done in the validation due to
        missing data, like registrations.
        """
        track_ids = affirm_set(vtypes.ID, track_ids)

        # Check that course choices and course instructors are compatible.
        query = """
            SELECT registration_id, COUNT(*)
            FROM (
                SELECT DISTINCT rt.registration_id, rt.course_instructor,
                    ARRAY_REMOVE(ARRAY_AGG(cc.course_id ORDER BY cc.rank ASC), NULL) AS choices
                FROM event.registration_tracks AS rt
                    LEFT JOIN event.course_choices AS cc ON rt.track_id = cc.track_id AND rt.registration_id = cc.registration_id
                WHERE rt.track_id = ANY(%s)
                GROUP BY rt.registration_id, rt.course_instructor, rt.track_id
            ) AS tmp
            GROUP BY registration_id
            HAVING COUNT(*) > 1
        """
        params = (track_ids,)
        if self.query_all(rs, query, params):
            return False

        return True

    def _delete_event_field_blockers(
        self, rs: RequestState, field_id: int, *, event_id: int
    ) -> DeletionBlockers:
        """Determine what keeps an event part from being deleted.

        Possible blockers:

        * event_fees:         An event fee referencing this field.
        * questionnaire_rows: A questionnaire row that uses this field.
        * lodge_fields:       An event that uses this field for lodging wishes.
        * camping_mat_fields: An event_part that uses this field for camping mat
                              wishes.
        * course_room_fields: A course_track that uses this field for course room
                              assignment.
        * waitlist_fields:    An event_part that uses this field for waitlist
                              management.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        field_id = affirm(vtypes.ID, field_id)
        event_id = affirm(vtypes.ID, event_id)
        blockers = {}

        # This also ensures the field belongs to this event.
        current = self._get_event_field(rs, field_id, event_id=event_id)

        event_fees_per_field = self.get_event_fees_per_entity(
            rs, current.event_id
        ).fields
        if fee_ids := event_fees_per_field[field_id]:
            blockers["event_fees"] = list(fee_ids)

        questionnaire_rows = self.sql_select(
            rs, "event.questionnaire_rows", ("id",), (field_id,), entity_key="field_id"
        )
        if questionnaire_rows:
            blockers["questionnaire_rows"] = [e["id"] for e in questionnaire_rows]

        lodge_fields = self.sql_select(
            rs, "event.events", ("id",), (field_id,), entity_key="lodge_field_id"
        )
        if lodge_fields:
            blockers["lodge_fields"] = [e["id"] for e in lodge_fields]

        camping_mat_fields = self.sql_select(
            rs,
            "event.event_parts",
            ("id",),
            (field_id,),
            entity_key="camping_mat_field_id",
        )
        if camping_mat_fields:
            blockers["camping_mat_fields"] = [e["id"] for e in camping_mat_fields]

        course_room_fields = self.sql_select(
            rs,
            "event.course_tracks",
            ("id",),
            (field_id,),
            entity_key="course_room_field_id",
        )
        if course_room_fields:
            blockers["course_room_fields"] = [e["id"] for e in course_room_fields]

        waitlist_fields = self.sql_select(
            rs,
            "event.event_parts",
            ("id",),
            (field_id,),
            entity_key="waitlist_field_id",
        )
        if waitlist_fields:
            blockers["waitlist_fields"] = [e["id"] for e in waitlist_fields]

        return blockers

    def _delete_event_field(
        self,
        rs: RequestState,
        field_id: int,
        cascade: Optional[Collection[str]] = None,
        *,
        event_id: int,
    ) -> DefaultReturnCode:
        """Helper to remove an event field.

        Used by `delete_event` and `_set_event_fields`.

        :note: This has to be called inside an atomized context.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.

        """
        field_id = affirm(vtypes.ID, field_id)
        event_id = affirm(vtypes.ID, event_id)
        blockers = self._delete_event_field_blockers(rs, field_id, event_id=event_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "event field",
                    "block": blockers.keys() - cascade,
                },
            )

        current = self._get_event_field(rs, field_id, event_id=event_id)

        ret = 1
        # implicit atomized context.
        self.affirm_atomized_context(rs)
        if cascade:
            if "questionnaire_rows" in cascade:
                ret *= self.sql_delete(
                    rs, "event.questionnaire_rows", blockers["questionnaire_rows"]
                )
            if "lodge_fields" in cascade:
                for anid in blockers["lodge_fields"]:
                    deletor = {
                        'id': anid,
                        'lodge_field_id': None,
                    }
                    ret *= self.sql_update(rs, "event.events", deletor)
            if "camping_mat_fields" in cascade:
                for anid in blockers["camping_mat_fields"]:
                    deletor = {
                        'id': anid,
                        'camping_mat_field_id': None,
                    }
                    ret *= self.sql_update(rs, "event.events", deletor)
            if "course_room_fields" in cascade:
                for anid in blockers["course_room_fields"]:
                    deletor = {
                        'id': anid,
                        'course_room_field_id': None,
                    }
                    ret *= self.sql_update(rs, "event.events", deletor)
            if "waitlist_fields" in cascade:
                for anid in blockers["waitlist_fields"]:
                    deletor = {
                        'id': anid,
                        'waitlist_field_id': None,
                    }
                    ret *= self.sql_update(rs, "event.event_parts", deletor)
            if "event_fees" in cascade:
                for fee_id in blockers["event_fees"]:
                    ret *= self.delete_event_fee(rs, fee_id)
            blockers = self._delete_event_field_blockers(
                rs, field_id, event_id=event_id
            )

        if not blockers:
            ret *= self.sql_delete_one(rs, models.EventField.database_table, field_id)
            self._delete_field_values(rs, current)
            self.event_log(
                rs,
                const.EventLogCodes.field_removed,
                current.event_id,
                change_note=current.field_name,
            )
        else:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {"type": "event part", "block": blockers.keys()},
            )

        return ret

    @internal
    def _set_event_fields(
        self, rs: RequestState, event_id: int, fields: CdEDBOptionalMap
    ) -> DefaultReturnCode:
        """Helper for creating, updating or deleting custom event fields.

        Used by `set_event`.

        :note: This has to be called inside an atomized context.
        """
        ret = 1
        if not fields:
            return ret
        self.affirm_atomized_context(rs)

        current_field_data = self._get_event_fields(rs, event_id)
        existing_fields = current_field_data.keys()
        new_fields = {x for x in fields if x < 0}
        updated_fields = {x for x in fields if x > 0 and fields[x] is not None}
        deleted_fields = {x for x in fields if x > 0 and fields[x] is None}
        if not updated_fields | deleted_fields <= existing_fields:
            raise ValueError(n_("Non-existing fields specified."))

        event_fees_per_field = self.get_event_fees_per_entity(rs, event_id).fields

        # Do deletion first to avoid error due to duplicate field names.
        for x in mixed_existence_sorter(deleted_fields):
            # Only allow deletion of unused fields.
            self._delete_event_field(rs, x, cascade=None, event_id=event_id)

        for x in mixed_existence_sorter(new_fields):
            new_field = copy.deepcopy(fields[x])
            assert new_field is not None
            new_field['event_id'] = event_id
            ret *= self.sql_insert(rs, models.EventField.database_table, new_field)
            self.event_log(
                rs,
                const.EventLogCodes.field_added,
                event_id,
                change_note=new_field['field_name'],
            )

        if updated_fields:
            for x in mixed_existence_sorter(updated_fields):
                updated_field = copy.deepcopy(fields[x])
                assert updated_field is not None
                updated_field['id'] = x
                updated_field['event_id'] = event_id
                current = current_field_data[x]
                current_data = current.to_database()
                if any(updated_field[k] != current_data[k] for k in updated_field):
                    if event_fees_per_field[x]:
                        # Fields used in event fees may not have their kind
                        #  or association changed.
                        if not all(
                            updated_field[k] == current_data[k]
                            for k in ('kind', 'association')
                            if k in updated_field
                        ):
                            raise ValueError(
                                n_(
                                    "Cannot change association or kind of a field"
                                    " referenced by an event fee."
                                )
                            )
                    if updated_field.get('kind', current.kind) != current.kind:
                        current.kind = updated_field['kind']
                        self._cast_field_values(rs, current)
                    ret *= self.sql_update(
                        rs, models.EventField.database_table, updated_field
                    )
                    self.event_log(
                        rs,
                        const.EventLogCodes.field_updated,
                        event_id,
                        change_note=current.field_name,
                    )

        return ret

    @access("event")
    def has_registrations(self, rs: RequestState, event_id: int) -> bool:
        """Determine whether there exist registrations for an event.

        This is very low-level but also rather useful, so it is published contrary to
        the other methods in this class which are mostly internal.
        """
        event_id = affirm(vtypes.ID, event_id)
        if not is_privileged(
            rs, EventPrivileges.registrations_stats, event_id=event_id
        ):
            raise PrivilegeError(n_("Not privileged."))
        query = "SELECT COUNT(*) FROM event.registrations WHERE event_id = %s LIMIT 1"
        return bool(unwrap(self.query_one(rs, query, (event_id,))))

    @internal
    def _get_registration_data(
        self,
        rs: RequestState,
        event_id: int,
        registration_ids: Optional[Collection[int]] = None,
    ) -> CdEDBObjectMap:
        """Retrieve basic registration data."""
        query = f"""
            SELECT {", ".join(REGISTRATION_FIELDS)}, ctime, mtime
            FROM event.registrations
            LEFT OUTER JOIN (
                SELECT persona_id AS log_persona_id, MAX(ctime) AS ctime
                FROM event.log WHERE code = %(ctime_code)s AND event_id = %(event_id)s
                GROUP BY log_persona_id
            ) AS ctime
            ON event.registrations.persona_id = ctime.log_persona_id
            LEFT OUTER JOIN (
                SELECT persona_id AS log_persona_id, MAX(ctime) AS mtime
                FROM event.log WHERE code = %(mtime_code)s AND event_id = %(event_id)s
                GROUP BY log_persona_id
            ) AS mtime
            ON event.registrations.persona_id = mtime.log_persona_id
            WHERE event.registrations.event_id = %(event_id)s"""
        params: dict[str, DatabaseValue_s] = {
            "event_id": event_id,
            "ctime_code": const.EventLogCodes.registration_created,
            "mtime_code": const.EventLogCodes.registration_changed,
        }
        if registration_ids is not None:
            query += " AND event.registrations.id = ANY(%(reg_ids)s)"
            params["reg_ids"] = registration_ids
        rdata = self.query_all(rs, query, params)
        return {reg['id']: reg for reg in rdata}

    @classmethod
    def _translate(
        cls,
        data: CdEDBObject,
        translations: dict[str, dict[int, int]],
        extra_translations: Optional[dict[str, str]] = None,
    ) -> CdEDBObject:
        """Helper to do the actual translation of IDs which got out of sync.

        This does some additional sanitizing besides applying the
        translation.

        Used during the full import.
        """
        extra_translations = extra_translations or {}
        ret = copy.deepcopy(data)
        for x in ret:
            if x in translations or x in extra_translations:
                target = extra_translations.get(x, x)
                ret[x] = translations[target].get(ret[x], ret[x])
            if isinstance(ret[x], collections.abc.Mapping):
                # All mappings have to be JSON columns in the database
                # (nothing else should be possible).
                ret[x] = PsycoJson(
                    cls._translate(ret[x], translations, extra_translations)
                )
        if ret.get('real_persona_id'):
            ret['real_persona_id'] = None
        if ret.get('amount_owed'):
            del ret['amount_owed']
        return ret

    def _synchronize_table(
        self,
        rs: RequestState,
        table: str,
        data: CdEDBObjectMap,
        current: CdEDBObjectMap,
        translations: dict[str, dict[int, int]],
        entity: Optional[str] = None,
        extra_translations: Optional[dict[str, str]] = None,
    ) -> DefaultReturnCode:
        """Replace one data set in a table with another.

        This is a bit involved, since both DB instances may have been
        modified, so that conflicting primary keys were created. Thus we
        have a snapshot ``current`` of the state at locking time and
        apply the diff to the imported state in ``data``. Any IDs which
        were not previously present in the DB into which we import have
        to be kept track of -- this is done in ``translations``.

        Used during the full import.

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
