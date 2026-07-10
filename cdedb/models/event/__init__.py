import abc
import collections
import dataclasses
import datetime
import decimal
import functools
import logging
import sys
from collections.abc import Callable, Collection
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    ForwardRef,
    Literal,
    Optional,
    Self,
    cast,
    get_args,
    get_origin,
    overload,
)

from typing_extensions import TypeForm

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
from cdedb.common import (
    CdEDBObject,
    User,
    cast_field_entries,
    cast_fields,
    n_,
    normalize_field_entries,
    now,
)
from cdedb.common.parse.util import Accounts
from cdedb.common.privileges import EventPrivileges, is_privileged_event_user
from cdedb.common.query import (
    QueryScope,
    QuerySpec,
    QuerySpecEntry,
    make_course_query_spec,
    make_registration_query_spec,
)
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.config import Config
from cdedb.fee_condition_parser.evaluation import get_referenced_names
from cdedb.filter import datetime_filter
from cdedb.models.common import (
    AbstractMetaData,
    CdEDataclass,
    CdEDataclassMap,
    MetaFlag as Meta,
    StoredQuery as _StoredQuery,
)

_LOGGER = logging.getLogger(__name__)
CONF = Config()

if TYPE_CHECKING:
    from cdedb.database.query import (
        DatabaseValue_s,
    )


#
# meta
#

EventDataclassMap = CdEDataclassMap["Event"]


@dataclasses.dataclass
class EventDataclass(CdEDataclass, abc.ABC):
    entity_key: ClassVar[str] = "event_id"

    @classmethod
    def full_export_spec(
        cls, entity_key: str | None = None
    ) -> tuple[str, str, tuple[str, ...]]:
        return (
            cls.database_table,
            entity_key or cls.entity_key,
            tuple(cls.database_fields()),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class EventFieldSpec(AbstractMetaData):
    """Stores the accepted associations and kinds for a special purpose event field."""

    legal_associations: set[const.FieldAssociations]
    legal_kinds: set[const.FieldDatatypes]

    @classmethod
    def get_specs(cls, entity: type[EventDataclass]) -> dict[str, Self]:
        return {
            field.name: spec
            for field in entity.dataclass_fields()
            if (spec := field.metadata.get(cls.get_metadata_name()))
        }

    @classmethod
    def _get_spec(cls, entity: type[EventDataclass], field_name: str) -> Self:
        field_name = f"{field_name}_field_id"
        if field_name not in (specs := cls.get_specs(entity)):
            raise KeyError(
                f"Entity {entity.__qualname__!r} has no field {field_name!r}."
            )
        if spec := specs.get(field_name):
            return spec
        raise TypeError(
            f"Field '{entity.__qualname__}.{field_name}' has no metadata {cls.get_metadata_name()!r}."
        )

    def _accepts_association(self, association: const.FieldAssociations) -> bool:
        return association in self.legal_associations

    @classmethod
    def field_accepts_association(
        cls, entity: type[EventDataclass], fn: str, association: const.FieldAssociations
    ) -> bool:
        return cls._get_spec(entity, fn)._accepts_association(association)

    def _accepts_kind(self, kind: const.FieldDatatypes) -> bool:
        return kind in self.legal_kinds

    @classmethod
    def field_accepts_kind(
        cls, entity: type[EventDataclass], fn: str, kind: const.FieldDatatypes
    ) -> bool:
        return cls._get_spec(entity, fn)._accepts_kind(kind)

    def accepts(self, event_field: "EventField") -> bool:
        return (
            self._accepts_association(event_field.association)
            and self._accepts_kind(event_field.kind)
        )  # fmt: skip


class OtherDatabaseTables:
    orgas = "event.orgas"
    caretakers = "event.caretakers"
    checkin_helpers = "event.checkin_helpers"
    part_group_parts = "event.part_group_parts"
    track_group_tracks = "event.track_group_tracks"
    course_choices = "event.course_choices"


#
# get_event
#


@dataclasses.dataclass(kw_only=True)
class _EventConfigurationMixin(CdEDataclass):
    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)

    title: str
    shortname: str

    institution: const.PastInstitutions

    registration_start: datetime.datetime | None
    registration_soft_limit: datetime.datetime | None
    registration_hard_limit: datetime.datetime | None

    iban: Accounts | None
    orga_address: vtypes.Email | None
    website_url: str | None

    is_cancelled: bool = False
    is_visible: bool = False
    is_course_list_visible: bool = False
    is_course_state_visible: bool = False
    is_participant_list_visible: bool = False
    is_course_assignment_visible: bool = False
    use_additional_questionnaire: bool = False
    notify_on_registration: const.NotifyOnRegistration = (
        const.NotifyOnRegistration.never
    )

    lodge_field_id: vtypes.ID | None = dataclasses.field(
        default=None,
        metadata=EventFieldSpec(
            legal_associations={const.FieldAssociations.registration},
            legal_kinds={
                const.FieldDatatypes.str,
                const.FieldDatatypes.str_multiline,
                const.FieldDatatypes.str_monospace,
            },
        ).as_dict,
    )
    reimbursement_iban_field_id: vtypes.ID | None = dataclasses.field(
        default=None,
        metadata=EventFieldSpec(
            legal_associations={const.FieldAssociations.registration},
            legal_kinds={const.FieldDatatypes.iban},
        ).as_dict,
    )


@dataclasses.dataclass(kw_only=True)
class _EventFreetextMixin(CdEDataclass):
    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)

    # Exclude from request to avoid unsetting when submitting `change_event_form`.
    description: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )
    registration_text: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )
    mail_text: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )
    participant_info: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )
    notes: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )
    field_definition_notes: str | None = dataclasses.field(
        default=None, metadata=Meta.request_update_exclude.as_dict
    )


@dataclasses.dataclass(kw_only=True)
class Event(EventDataclass, _EventConfigurationMixin, _EventFreetextMixin):
    database_table = "event.events"
    entity_key = "id"

    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)

    # Disallow setting via request altogether.
    is_locked: bool = dataclasses.field(
        default=False, metadata=Meta.request_exclude.as_dict
    )
    is_archived: bool = dataclasses.field(
        default=False, metadata=Meta.request_exclude.as_dict
    )
    is_balanced: bool = dataclasses.field(
        default=False, metadata=Meta.request_exclude.as_dict
    )
    is_registration_approved: bool = dataclasses.field(
        default=False, metadata=Meta.request_exclude.as_dict
    )

    parts: CdEDataclassMap["EventPart"] = dataclasses.field(
        default_factory=dict,
        metadata=(
            Meta.validate_include | Meta.validate_skip | Meta.asdict_include
        ).as_dict,
    )
    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(
        default_factory=dict, metadata=Meta.asdict_include.as_dict
    )

    fields: CdEDataclassMap["EventField"] = dataclasses.field(
        default_factory=dict,
        metadata=(
            Meta.validate_include | Meta.validate_skip | Meta.asdict_include
        ).as_dict,
    )
    custom_query_filters: CdEDataclassMap["CustomQueryFilter"] = dataclasses.field(
        default_factory=dict, metadata=Meta.asdict_include.as_dict
    )
    fees: CdEDataclassMap["EventFee"] = dataclasses.field(
        default_factory=dict, metadata=Meta.asdict_include.as_dict
    )

    part_groups: CdEDataclassMap["PartGroup"] = dataclasses.field(
        default_factory=dict, metadata=Meta.asdict_include.as_dict
    )
    track_groups: CdEDataclassMap["TrackGroup"] = dataclasses.field(
        default_factory=dict, metadata=Meta.asdict_include.as_dict
    )

    orgas: set[vtypes.ID] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )
    caretakers: set[vtypes.ID] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )
    checkin_helpers: set[vtypes.ID] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['orgas'] = set(data['orgas'])
        data['caretakers'] = set(data['caretakers'])
        data['checkin_helpers'] = set(data['checkin_helpers'])
        data['parts'] = EventPart.many_from_database(data['parts'])
        data['tracks'] = CourseTrack.many_from_database(data['tracks'])
        data['fields'] = EventField.many_from_database(data['fields'])
        data['custom_query_filters'] = CustomQueryFilter.many_from_database(
            data['custom_query_filters']
        )
        data['fees'] = EventFee.many_from_database(data['fees'])
        data['part_groups'] = PartGroup.many_from_database(data['part_groups'])
        data['track_groups'] = TrackGroup.many_from_database(data['track_groups'])
        return super().from_database(data)

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            if get_origin(field.type) is CdEDataclassMap:
                value_kind = get_args(field.type)[0]
                if isinstance(value_kind, ForwardRef):
                    value_kind = value_kind.__forward_arg__
                value_class = globals()[value_kind]
                if issubclass(value_class, EventDataclass):
                    for obj in getattr(self, field.name).values():
                        obj.event = self

        for part in self.parts.values():
            part.tracks = {
                track.id: track
                for track in self.tracks.values()
                if track.id in part.tracks
            }
            for track in part.tracks.values():
                track.part = part
        for part_group in self.part_groups.values():
            part_group.parts = {
                part.id: part
                for part in self.parts.values()
                if part.id in part_group.part_ids
            }
            for part in part_group.parts.values():
                part.part_groups[part_group.id] = part_group
                part.part_group_ids.add(part_group.id)
        for track_group in self.track_groups.values():
            track_group.tracks = {
                track.id: track
                for track in self.tracks.values()
                if track.id in track_group.track_ids
            }
            for track in track_group.tracks.values():
                track.track_groups[track_group.id] = track_group
                track.track_group_ids.add(track_group.id)

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT persona_id
                    FROM {OtherDatabaseTables.orgas}
                    WHERE event_id = events.id
                ) AS orgas,
                array(
                    SELECT persona_id
                    FROM {OtherDatabaseTables.caretakers}
                    WHERE event_id = events.id
                ) AS caretakers,
                array(
                    SELECT persona_id
                    FROM {OtherDatabaseTables.checkin_helpers}
                    WHERE event_id = events.id
                ) AS checkin_helpers
            FROM {cls.database_table}
            WHERE {entity_key or cls.entity_key} = ANY(%s)
            """
        params = (entities,)
        return query, params

    @functools.cached_property
    def begin(self) -> datetime.date:
        return min(p.part_begin for p in self.parts.values())

    @functools.cached_property
    def end(self) -> datetime.date:
        return max(p.part_end for p in self.parts.values())

    @functools.cached_property
    def is_open(self) -> bool:
        reference_time = now()
        return bool(
            self.registration_start
            and self.registration_start <= reference_time
            and (
                self.registration_hard_limit is None
                or self.registration_hard_limit >= reference_time
            )
            and self.is_registration_approved
        )

    def is_visible_for(
        self, user: User, is_registered: bool, *, privileged: bool
    ) -> bool:
        """Whether an event is visible dependent on your own registration status.

        :param privileged: If access in a privileged capacity is to be considered."""

        return (
            is_registered
            or self.is_visible
            or (
                privileged
                and is_privileged_event_user(user, EventPrivileges.basic_read, self.id)
            )
        )

    def is_current_for_orga(self) -> bool:
        return self.begin > (now().date() - datetime.timedelta(days=365 * 2))

    @functools.cached_property
    def registration_fields(self) -> CdEDataclassMap["RegistrationField"]:
        return {
            k: v for k, v in self.fields.items() if isinstance(v, RegistrationField)
        }

    @functools.cached_property
    def course_fields(self) -> CdEDataclassMap["CourseField"]:
        return {k: v for k, v in self.fields.items() if isinstance(v, CourseField)}

    @functools.cached_property
    def lodgement_fields(self) -> CdEDataclassMap["LodgementField"]:
        return {k: v for k, v in self.fields.items() if isinstance(v, LodgementField)}

    @functools.cached_property
    def lodge_field(self) -> Optional["EventField"]:
        if self.lodge_field_id is None:
            return None
        return self.fields[self.lodge_field_id]

    @functools.cached_property
    def reimbursement_iban_field(self) -> Optional["EventField"]:
        if self.reimbursement_iban_field_id is None:
            return None
        return self.fields[self.reimbursement_iban_field_id]

    @functools.cached_property
    def personalized_fees(self) -> CdEDataclassMap["EventFee"]:
        return {fee.id: fee for fee in self.fees.values() if fee.is_personalized()}

    @functools.cached_property
    def conditional_fees(self) -> CdEDataclassMap["EventFee"]:
        return {fee.id: fee for fee in self.fees.values() if fee.is_conditional()}

    @functools.cached_property
    def grouped_fields(
        self,
    ) -> dict[const.FieldAssociations, dict[str, list["EventField"]]]:
        ret: dict[const.FieldAssociations, dict[str, list[EventField]]]
        ret = collections.defaultdict(dict)
        for field in xsorted(self.fields.values()):
            ret[field.association].setdefault(field.sort_group or "", []).append(field)
        return ret

    def get_sortkey(self) -> Sortkey:
        return self.begin, self.end, self.title

    @functools.cached_property
    def basic_registration_query_spec(self) -> QuerySpec:
        return make_registration_query_spec(self)

    @functools.cached_property
    def basic_course_query_spec(self) -> QuerySpec:
        return make_course_query_spec(self)


@dataclasses.dataclass
class EventPart(EventDataclass):
    database_table = "event.event_parts"

    id: vtypes.ID = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict
    )

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    title: str
    shortname: vtypes.Identifier

    part_begin: datetime.date
    part_end: datetime.date

    waitlist_field_id: vtypes.ID | None = dataclasses.field(
        metadata=EventFieldSpec(
            legal_associations={const.FieldAssociations.registration},
            legal_kinds={const.FieldDatatypes.int},
        ).as_dict
    )
    camping_mat_field_id: vtypes.ID | None = dataclasses.field(
        metadata=EventFieldSpec(
            legal_associations={const.FieldAssociations.registration},
            legal_kinds={const.FieldDatatypes.bool},
        ).as_dict
    )

    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(
        default_factory=dict,
        metadata=(
            Meta.asdict_include | Meta.validate_include | Meta.validate_skip
        ).as_dict,
    )

    part_groups: CdEDataclassMap["PartGroup"] = dataclasses.field(
        default_factory=dict, compare=False, repr=False
    )
    part_group_ids: set[int] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT id
                    FROM event.course_tracks
                    WHERE part_id = event_parts.id
                ) AS tracks
            FROM
                event.event_parts
            WHERE
                {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    @property
    def waitlist_field(self) -> Optional["EventField"]:
        if self.event is None:
            raise RuntimeError
        if self.waitlist_field_id is None:
            return None
        return self.event.fields[self.waitlist_field_id]

    @property
    def camping_mat_field(self) -> Optional["EventField"]:
        if self.event is None:
            raise RuntimeError
        if self.camping_mat_field_id is None:
            return None
        return self.event.fields[self.camping_mat_field_id]

    def get_sortkey(self) -> Sortkey:
        return self.part_begin, self.part_end, self.shortname


@dataclasses.dataclass
class CourseChoiceObject(abc.ABC):
    id: vtypes.ID

    title: str
    shortname: str
    sortkey: int

    num_choices: vtypes.NonNegativeInt
    min_choices: vtypes.NonNegativeInt

    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(
        init=False, compare=False, repr=False
    )

    @abc.abstractmethod
    def is_complex(self) -> bool: ...

    @property
    @abc.abstractmethod
    def reference_track(self) -> "CourseTrack": ...

    @abc.abstractmethod
    def as_dict(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def _lt_inner(self, other: Any) -> bool: ...

    @abc.abstractmethod
    def get_sortkey(self) -> Sortkey: ...

    def __lt__(self, other: Any) -> bool:
        if isinstance(self, CourseChoiceObject) and isinstance(
            other, CourseChoiceObject
        ):
            return self._lt_inner(other)
        return NotImplemented


@dataclasses.dataclass
class CourseTrack(EventDataclass, CourseChoiceObject):
    database_table = "event.course_tracks"
    entity_key = "part_id"

    id: vtypes.ID = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict
    )

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    part: EventPart = dataclasses.field(init=False, compare=False, repr=False)
    part_id: vtypes.ID = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict
    )

    course_room_field_id: vtypes.ID | None = dataclasses.field(
        metadata=EventFieldSpec(
            legal_associations={const.FieldAssociations.course},
            legal_kinds={
                const.FieldDatatypes.str,
                const.FieldDatatypes.str_multiline,
                const.FieldDatatypes.str_monospace,
            },
        ).as_dict
    )

    track_groups: CdEDataclassMap["TrackGroup"] = dataclasses.field(
        default_factory=dict, compare=False, repr=False
    )
    track_group_ids: set[int] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )

    def is_complex(self) -> bool:
        return False

    @property
    def reference_track(self) -> "CourseTrack":
        if any(tg.constraint_type.is_sync() for tg in self.track_groups.values()):
            _LOGGER.warning(f"Recursive use of .reference_track detected: {self}.")
        return self

    @property  # type: ignore[misc]
    def tracks(self) -> CdEDataclassMap["CourseTrack"]:
        return {self.id: self}

    @tracks.setter
    def tracks(self, value: CdEDataclassMap["CourseTrack"]) -> None:
        raise KeyError

    @property
    def course_room_field(self) -> Optional["EventField"]:
        if self.event is None:
            raise RuntimeError
        if self.course_room_field_id is None:
            return None
        return self.event.fields[self.course_room_field_id]

    def get_sortkey(self) -> Sortkey:
        return self.sortkey, 0, self.title

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, CourseChoiceObject):
            return CourseChoiceObject.__lt__(self, other)
        return super().__lt__(other)


@dataclasses.dataclass
class EventFee(EventDataclass):
    database_table = "event.event_fees"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    # Exclude during creation, update and request.
    event_id: vtypes.ID = dataclasses.field(
        metadata=Meta.input_exclude.as_dict,
    )

    kind: const.EventFeeType
    title: str
    notes: str | None

    condition: vtypes.EventFeeCondition | None
    amount: decimal.Decimal | None
    amount_min: decimal.Decimal | None = dataclasses.field(
        default=None, metadata=Meta.exclude.as_dict
    )
    amount_max: decimal.Decimal | None = dataclasses.field(
        default=None, metadata=Meta.exclude.as_dict
    )

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT {','.join(cls.database_fields())}, amount_min, amount_max
            FROM {cls.database_table} AS fee
            LEFT OUTER JOIN (
                SELECT fee_id, MIN(amount) AS amount_min, MAX(amount) AS amount_max
                FROM {PersonalizedFee.database_table}
                GROUP BY fee_id
            ) AS personalized ON personalized.fee_id = fee.id
            WHERE {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    def is_conditional(self) -> bool:
        return self.amount is not None and self.condition is not None

    def is_personalized(self) -> bool:
        return self.amount is None and self.condition is None

    @functools.cached_property
    def visual_debug(self) -> str:
        if not self.is_conditional():
            return ""
        parse_result = fcp_parsing.parse(self.condition)
        return fcp_roundtrip.visual_debug(
            parse_result,
            data={},  # type: ignore[typeddict-item]
            condition_only=True,
        )

    def get_sortkey(self) -> Sortkey:
        return self.kind, self.title, self.amount or decimal.Decimal(0)

    @staticmethod
    def get_fees_per_entity(event: Event) -> "EventFeesPerEntity":
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


@dataclasses.dataclass
class EventField(EventDataclass):
    database_table = "event.field_definitions"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    # Exclude during creation, update and request.
    event_id: vtypes.ID = dataclasses.field(
        metadata=Meta.input_exclude.as_dict,
    )

    # Internal metadata.
    field_name: vtypes.RestrictiveIdentifier = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict
    )
    kind: const.FieldDatatypes
    association: const.FieldAssociations = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict
    )
    _association: ClassVar[const.FieldAssociations]

    # Userfacing metadata. Purely for UI.
    title: str  # Userfacing label.
    sort_group: str | None = None  # Used to group multiple fields together.
    sortkey: int = 0  # Sortkey of the field (within it's group).
    description: str | None = None  # Shown as hovertext of the label.

    # Usage configuration, i.e. where is this field used.
    # TODO Shift this to RegistrationField
    checkin: bool = False

    # Need to postpone validation of entries until kind is known.
    # Also need to account for this accepting string and sequence input.
    entries: dict[Any, str] | None = dataclasses.field(
        default=None, metadata=Meta.validate_skip.as_dict
    )

    def __post_init__(self) -> None:
        if self.association != self._association:
            raise RuntimeError("Inconsistent field association")

    @property
    def request_name(self) -> str:
        return f"fields.{self.field_name}"

    @staticmethod
    def get_class(association: const.FieldAssociations) -> type["EventField"]:
        for cls in EventField.__subclasses__():
            if cls._association == association:
                return cls
        raise KeyError

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "EventField":
        data['entries'] = cast_field_entries(data['entries'], data['kind'])
        association = const.FieldAssociations(data['association'])
        return cls.get_class(association).from_database(data)

    def to_database(self) -> CdEDBObject:
        ret = super().to_database()
        ret['entries'] = normalize_field_entries(ret['entries'], self.kind)
        return ret

    def as_dict(self) -> dict[str, Any]:
        ret = super().as_dict()
        ret['entries'] = normalize_field_entries(ret['entries'], self.kind)
        return ret

    @classmethod
    def _get_validator(cls, kind: const.FieldDatatypes) -> TypeForm[Any]:
        type_ = {
            const.FieldDatatypes.str: str,
            const.FieldDatatypes.str_multiline: str,
            const.FieldDatatypes.str_monospace: str,
            const.FieldDatatypes.bool: bool,
            const.FieldDatatypes.int: int,
            const.FieldDatatypes.float: float,
            const.FieldDatatypes.date: datetime.date,
            const.FieldDatatypes.datetime: datetime.datetime,
            const.FieldDatatypes.non_negative_int: vtypes.NonNegativeInt,
            const.FieldDatatypes.non_negative_float: vtypes.NonNegativeFloat,
            const.FieldDatatypes.phone: vtypes.Phone,
            const.FieldDatatypes.iban: vtypes.IBAN,
        }[kind] | None
        return cast(TypeForm[Any], type_)

    def get_validator(self) -> TypeForm[Any]:
        return self._get_validator(self.kind)

    def get_sortkey(self) -> Sortkey:
        return (
            self.sort_group or chr(sys.maxunicode),  # Sort empty group last.
            self.sortkey,
            self.title,
            self.field_name,
        )

    def __lt__(self, other: "CdEDataclass") -> bool:
        # enable sorting of all event field sub classes
        if not isinstance(other, EventField):
            return NotImplemented
        return self._lt_inner(other)


@dataclasses.dataclass
class RegistrationField(EventField):
    _association = const.FieldAssociations.registration
    association: Literal[const.FieldAssociations.registration]

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        return super(EventField, cls).from_database(data)


@dataclasses.dataclass
class CourseField(EventField):
    _association = const.FieldAssociations.course
    association: Literal[const.FieldAssociations.course]

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        return super(EventField, cls).from_database(data)


@dataclasses.dataclass
class LodgementField(EventField):
    _association = const.FieldAssociations.lodgement
    association: Literal[const.FieldAssociations.lodgement]

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        return super(EventField, cls).from_database(data)


@dataclasses.dataclass
class CustomQueryFilter(EventDataclass):
    database_table = "event.custom_query_filters"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)

    scope: QueryScope = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)
    title: str
    notes: str | None
    fields: set[str] = dataclasses.field(metadata=Meta.request_exclude.as_dict)

    def __post_init__(self) -> None:
        if isinstance(self.fields, str):  # type: ignore[unreachable]
            self.fields = set(self.fields.split(','))  # type: ignore[unreachable]

    def to_database(self) -> "CdEDBObject":
        ret = super().to_database()
        ret['fields'] = self.get_field_string()
        return ret

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        if data.get("fields") and isinstance(data["fields"], str):
            data["fields"] = set(data["fields"].split(','))
        return super().from_database(data)

    def get_sortkey(self) -> Sortkey:
        return self.scope, self.title

    @staticmethod
    def _get_field_string(fields: Collection[str]) -> str:
        return ",".join(xsorted(fields))

    def get_field_string(self) -> str:
        return self._get_field_string(self.fields)

    def add_to_spec(self, spec: QuerySpec, scope: QueryScope) -> None:
        """If this filter is valid for this spec add it to the spec."""
        if self.scope != scope or not self.is_valid(spec):
            return
        type_ = spec[next(iter(self.fields))].type
        spec[self.get_field_string()] = QuerySpecEntry(
            type_, self.title, group_base=n_("Custom Filters")
        )

    def is_valid(self, spec: QuerySpec) -> bool:
        """Check whether all fields are in the spec and of the same type."""
        return (
            all(f in spec for f in self.fields)
            and len({spec[f].type for f in self.fields}) == 1
        )

    def get_field_titles(
        self, spec: QuerySpec, g: Callable[[str], str]
    ) -> tuple[list[str], list[str]]:
        """
        Return a sorted list of titles of existing fields and potentially names
        of deleted fields.
        """
        valid, invalid = [], []
        for f in self.fields:
            if f in spec:
                valid.append(spec[f].get_title(g))
            else:
                invalid.append(f.removeprefix("reg_fields.xfield_"))
        return xsorted(valid), xsorted(invalid)


@dataclasses.dataclass
class PartGroup(EventDataclass):
    database_table = "event.part_groups"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    title: str
    shortname: str
    notes: str | None
    constraint_type: const.EventPartGroupType = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict
    )

    parts: CdEDataclassMap[EventPart] = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        default_factory=dict,
        metadata=Meta.asdict_include.as_dict,
    )
    part_ids: set[int] = dataclasses.field(
        default_factory=set,
        metadata=(Meta.input_update_exclude | Meta.database_exclude).as_dict,
    )

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT part_id
                    FROM {OtherDatabaseTables.part_group_parts}
                    WHERE part_group_id = part_groups.id
                ) AS part_ids
            FROM
                event.part_groups
            WHERE
                {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    def get_sortkey(self) -> Sortkey:
        return self.constraint_type, self.title


@dataclasses.dataclass
class TrackGroup(EventDataclass):
    database_table = "event.track_groups"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    title: str
    shortname: str
    notes: str | None
    sortkey: int
    constraint_type: const.CourseTrackGroupType = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict
    )

    tracks: CdEDataclassMap[CourseTrack] = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        default_factory=dict,
        metadata=Meta.asdict_include.as_dict,
    )
    track_ids: set[int] = dataclasses.field(
        default_factory=set,
        metadata=(Meta.input_update_exclude | Meta.database_exclude).as_dict,
    )

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "TrackGroup":
        if data['constraint_type'] == const.CourseTrackGroupType.course_choice_sync:
            return super(cls, SyncTrackGroup).from_database(data)
        return super().from_database(data)

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT track_id
                    FROM {OtherDatabaseTables.track_group_tracks}
                    WHERE track_group_id = track_groups.id
                ) AS track_ids
            FROM
                event.track_groups
            WHERE
                {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    def get_sortkey(self) -> Sortkey:
        return self.constraint_type, self.sortkey, self.title


class SyncTrackGroup(TrackGroup, CourseChoiceObject):  # type: ignore[misc]
    constraint_type = const.CourseTrackGroupType.course_choice_sync

    def is_complex(self) -> bool:
        return True

    @property
    def reference_track(self) -> CourseTrack:
        return list(self.tracks.values())[0]

    @property
    def num_choices(self) -> vtypes.NonNegativeInt:
        return self.reference_track.num_choices

    @num_choices.setter
    def num_choices(self, value: vtypes.NonNegativeInt) -> None:
        for track in self.tracks.values():
            track.num_choices = value

    @property
    def min_choices(self) -> vtypes.NonNegativeInt:
        return self.reference_track.min_choices

    @min_choices.setter
    def min_choices(self, value: vtypes.NonNegativeInt) -> None:
        for track in self.tracks.values():
            track.min_choices = value

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, CourseChoiceObject):
            return CourseChoiceObject.__lt__(self, other)
        if isinstance(other, self.__class__):
            return super().__lt__(other)
        return not other < self


@dataclasses.dataclass
class StoredEventQuery(EventDataclass, _StoredQuery):
    database_table = "event.stored_queries"

    event_id: vtypes.ID = dataclasses.field(
        default=vtypes.ID(-1), metadata=Meta.request_exclude.as_dict
    )
    event: Event = dataclasses.field(
        compare=False,
        repr=False,
        default=cast(Event, None),
        metadata=Meta.input_exclude.as_dict,
    )

    def _get_spec(self) -> QuerySpec:
        return self.scope.get_spec(event=self.event)


#
# get_course
#


@dataclasses.dataclass
class Course(EventDataclass):
    database_table = "event.courses"
    entity_key = "id"

    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)

    # Give event a default, so automatic sorting of course segments is less horrible.
    event: Event = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        default=cast(Event, None),
        metadata=Meta.input_exclude.as_dict,
    )
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    segments: CdEDataclassMap["CourseSegment"] = dataclasses.field(
        metadata=(Meta.validate_include | Meta.asdict_include).as_dict
    )

    @property
    def active_segments(self) -> set[int]:
        return {
            segment.track_id for segment in self.segments.values() if segment.is_active
        }

    nr: str
    title: str
    shortname: str
    description: str | None

    instructors: str | None

    min_size: vtypes.NonNegativeInt | None
    max_size: vtypes.NonNegativeInt | None

    is_visible: bool

    notes: str | None

    fields: vtypes.EventAssociatedFields = dataclasses.field(
        default_factory=cast(type[vtypes.EventAssociatedFields], dict),
        metadata=Meta.request_exclude.as_dict,
    )

    @property
    def label(self) -> str:
        return f"{self.nr}. {self.title}"

    @property
    def shortlabel(self) -> str:
        return f"{self.nr}. {self.shortname}"

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        event = data.pop("event")
        data['fields'] = cast_fields(data['fields'], event.fields)
        data['segments'] = CourseSegment.many_from_database(
            data['segments'], sort=False
        )
        ret = super().from_database(data)
        ret.event = event
        return ret

    def __post_init__(self) -> None:
        for segment in self.segments.values():
            segment.course = self
        self.segments = {
            segment.track_id: segment for segment in xsorted(self.segments.values())
        }

    def get_sortkey(self) -> Sortkey:
        return self.nr, self.shortname

    @classmethod
    def validation_fields(
        cls, *, creation: bool
    ) -> tuple[vtypes.MutableTypeMapping, vtypes.MutableTypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        for ret in (mandatory, optional):
            if "segments" in ret:
                # During validation we also accept None, meaning to delete the segment,
                #  i.e. it is not (or no longer) offered.
                ret["segments"] = CdEDataclassMap[CourseSegment | None]
        return mandatory, optional


@dataclasses.dataclass
class CourseSegment(EventDataclass):
    database_table = "event.course_segments"
    entity_key = "course_id"

    id: vtypes.ID = dataclasses.field(
        compare=False,
        repr=False,
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict,
    )

    course: Course = dataclasses.field(init=False, compare=False, repr=False)
    course_id: vtypes.ID = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict
    )

    track_id: vtypes.ID = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.asdict_exclude).as_dict
    )

    is_active: bool

    def get_sortkey(self) -> Sortkey:
        ret = self.course.get_sortkey()
        if self.course.event:
            ret += self.course.event.tracks[self.track_id].get_sortkey()
        return ret


# @dataclasses.dataclass
# class CourseInstructors:
#     database_table = "event.course_instructors"


#
# get_lodgement_group + get_lodgement
#


@dataclasses.dataclass
class LodgementGroup(EventDataclass):
    database_table = "event.lodgement_groups"

    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)

    # event: Event
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)
    title: str

    lodgement_ids: set[int] = dataclasses.field(
        default_factory=set, metadata=Meta.io_exclude.as_dict
    )
    regular_capacity: int = dataclasses.field(
        default=0, metadata=Meta.database_exclude.as_dict
    )
    camping_mat_capacity: int = dataclasses.field(
        default=0, metadata=Meta.database_exclude.as_dict
    )

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(f'lodgement_groups.{f}' for f in cls.database_fields())},
                ARRAY_REMOVE(ARRAY_AGG(lodgements.id), NULL) AS lodgement_ids,
                COALESCE(SUM(lodgements.regular_capacity), 0) AS regular_capacity,
                COALESCE(SUM(lodgements.camping_mat_capacity), 0) AS camping_mat_capacity
            FROM event.lodgement_groups
                LEFT JOIN event.lodgements ON lodgement_groups.id = lodgements.group_id
            WHERE
                lodgement_groups.{entity_key or cls.entity_key} = ANY(%s)
            GROUP BY
                lodgement_groups.id
        """
        params = (entities,)
        return query, params

    @classmethod
    def entries(cls, groups: CdEDataclassMap[Self]) -> list[tuple[vtypes.ID, str]]:
        return [(group.id, group.title) for group in groups.values()]

    def get_sortkey(self) -> Sortkey:
        return (self.title,)


# ID to be given when validating a lodgement for a yet to be created group.
LODGEMENT_GROUP_PLACEHOLDER_ID = vtypes.ID(1)


@dataclasses.dataclass
class Lodgement(EventDataclass):
    database_table = "event.lodgements"
    entity_key = "id"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    event: Event = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        default=cast(Event, None),
        metadata=Meta.input_exclude.as_dict,
    )
    event_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)
    group: LodgementGroup
    group_id: vtypes.ID

    title: str
    regular_capacity: vtypes.NonNegativeInt
    camping_mat_capacity: vtypes.NonNegativeInt
    notes: str | None

    fields: vtypes.EventAssociatedFields = dataclasses.field(
        default_factory=cast(type[vtypes.EventAssociatedFields], dict)
    )

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        event = data.pop("event")
        data['fields'] = cast_fields(data['fields'], event.fields)
        ret = super().from_database(data)
        ret.event = event
        return ret

    def get_sortkey(self) -> Sortkey:
        return self.group.title, self.group.id, self.title


#
# get_registration
#


@dataclasses.dataclass
class Registration(EventDataclass):
    database_table = "event.registrations"

    # event: Event

    parts: dict[EventPart, "RegistrationPart"]
    tracks: dict[CourseTrack, "RegistrationTrack"]

    def get_sortkey(self) -> Sortkey:
        return (0,)


@dataclasses.dataclass
class RegistrationPart(EventDataclass):
    database_table = "event.registration_parts"

    registration: Registration
    tracks: dict[CourseTrack, "RegistrationTrack"]

    lodgement: Lodgement | None

    def get_sortkey(self) -> Sortkey:
        return (0,)


@dataclasses.dataclass
class RegistrationTrack(EventDataclass):
    database_table = "event.registration_tracks"

    registration: Registration
    registration_part: RegistrationPart

    course: Course | None
    instructed: Course | None

    choices: list[Course]

    def get_sortkey(self) -> Sortkey:
        return (0,)


@dataclasses.dataclass
class PersonalizedFee(EventDataclass):
    database_table = "event.personalized_fees"
    entity_key = "registration_id"

    registration_id: vtypes.ID
    fee_id: vtypes.ID

    amount: decimal.Decimal | None

    def get_query(self) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        if self.amount is not None:
            query = f"""
                INSERT INTO {self.database_table}
                (registration_id, fee_id, amount)
                VALUES (%s, %s, %s)
                ON CONFLICT(registration_id, fee_id)
                DO UPDATE SET amount = EXCLUDED.amount
                RETURNING id
            """
            params: tuple[DatabaseValue_s, ...] = (
                self.registration_id,
                self.fee_id,
                self.amount,
            )
            return query, params
        else:
            query = f"""
                DELETE FROM {self.database_table}
                WHERE registration_id = %s AND fee_id = %s
            """
            params = (self.registration_id, self.fee_id)
            return query, params

    def get_sortkey(self) -> Sortkey:
        return (0,)


@dataclasses.dataclass
class ReducedCheckinPeriod:
    checkin_time: datetime.datetime
    checkout_time: datetime.datetime | None

    def pretty(self) -> str:
        formatstr = "%Y-%m-%d %H:%M"
        if self.checkout_time:
            return (
                f"{datetime_filter(self.checkin_time, formatstr)} – "
                f"{datetime_filter(self.checkout_time, formatstr)}"
            )
        else:
            return f"{datetime_filter(self.checkin_time, formatstr)} – "


@dataclasses.dataclass
class CheckinPeriod(EventDataclass, ReducedCheckinPeriod):
    database_table = "event.checkin_periods"
    entity_key = "registration_id"

    registration_id: vtypes.ID

    def get_sortkey(self) -> Sortkey:
        if self.checkout_time is not None:
            return (self.checkin_time, True, self.checkout_time, self.registration_id)
        return (self.checkin_time, False, self.registration_id)

    def get_duration(self) -> datetime.timedelta:
        if self.checkout_time is not None:
            return self.checkout_time - self.checkin_time
        return now() - self.checkin_time


@dataclasses.dataclass(frozen=True)
class ChoiceCounts:
    """
    Wrapper around a mapping of course, track and rank to number of choices.

    For convenience this can be indexed by either only the course id,
    course id and track id or course id, track id and rank.
    """

    # dict mapping (course_id, track_id) to list of choice counts.
    _choice_counts: dict[int, dict[int, list[int]]]

    @overload
    def get(self, course_id: int) -> dict[int, list[int]]: ...

    @overload
    def get(self, course_id: int, track_id: int) -> list[int]: ...

    @overload
    def get(self, course_id: int, track_id: int, rank: int) -> int: ...

    def get(
        self,
        course_id: int,
        track_id: int | None = None,
        rank: int | None = None,
    ) -> dict[int, list[int]] | list[int] | int:
        by_track = self._choice_counts.get(course_id, {})
        if track_id is None:
            return by_track
        counts = by_track.get(track_id, [])
        if rank is None:
            return counts
        return counts[rank] if rank < len(counts) else 0

    def __getitem__(
        self,
        item: tuple[int] | tuple[int, int] | tuple[int, int, int],
    ) -> dict[int, list[int]] | list[int] | int:
        return self.get(*item)


@dataclasses.dataclass(frozen=True)
class ChoiceStats:
    """
    Collection helper class, holding two instances of `ChoiceCounts`.

    `participant` only includes choices by participants, `involved`
    includes the stati defined by `const.RegisrationPartStati.is_involved()`.
    """

    participant: ChoiceCounts
    involved: ChoiceCounts


@dataclasses.dataclass(frozen=True)
class CourseSegmentAttendees:
    """
    Wrapper to store the assigned attendees of one course in one track.
    """

    learners: list[CdEDBObject]
    instructors: list[CdEDBObject]

    @functools.cached_property
    def all(self) -> list[CdEDBObject]:
        return self.learners + self.instructors

    @functools.cached_property
    def num_learners(self) -> int:
        return len(self.learners)

    @functools.cached_property
    def num_instructors(self) -> int:
        return len(self.instructors)

    @functools.cached_property
    def num(self) -> int:
        return len(self.all)


class CourseAttendees(dict[int, CourseSegmentAttendees]):
    pass


@dataclasses.dataclass(frozen=True)
class Attendees:
    """Wrapper around a mapping of course and track to lists of attendees."""

    _course_attendee_counts: dict[int, CourseAttendees]

    @overload
    def get(self, course_id: int) -> CourseAttendees: ...

    @overload
    def get(self, course_id: int, track_id: int) -> CourseSegmentAttendees: ...

    def get(
        self,
        course_id: int,
        track_id: int | None = None,
    ) -> CourseAttendees | CourseSegmentAttendees:
        by_track = self._course_attendee_counts.get(course_id, CourseAttendees({}))
        if track_id is None:
            return by_track
        return by_track.get(track_id, CourseSegmentAttendees([], []))

    def __getitem__(
        self,
        item: tuple[int] | tuple[int, int],
    ) -> CourseAttendees | CourseSegmentAttendees:
        return self.get(*item)


@dataclasses.dataclass(frozen=True)
class AttendeeStats:
    """
    Collection helper class, holding two instances of `Attendees`.

    `involved` are the stati defined by `const.RegisrationPartStati.is_involved()`.
    `uninvolved` is the rest.
    """

    involved: Attendees
    uninvolved: Attendees


@dataclasses.dataclass
class EventFeesPerEntity:
    """Simple container for data on event fee references.

    Each member is a map of entities to a set of fees that reference that entity.
    """

    fields: dict[int, set[int]]
    parts: dict[int, set[int]]


# Import here to avoid cyclic import.
from cdedb.models.event import questionnaire  # noqa: E402, F401
