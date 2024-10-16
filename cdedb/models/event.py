"""
event realm tables:
  - event.events
  - event.event_fees
  - event.event_parts
  - event.part_groups
  * event.part_group_parts
  - event.course_tracks
  - event.track_groups
  * event.track_group_tracks
  - event.field_definitions
  - event.courses
  * event.course_segments
  * event.orgas
  + event.orga_apitokens
  - event.lodgement_groups
  - event.lodgements
  - event.registrations
  - event.registration_parts
  - event.registration_tracks
  * event.course_choices
  - event.questionnaire_rows
  + event.stored_queries
  * event.log
"""
import abc
import collections
import dataclasses
import datetime
import decimal
import functools
import logging
import sys
from collections.abc import Collection, Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    ForwardRef,
    Optional,
    get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
from cdedb.common import User, cast_fields, now
from cdedb.common.query import (
    QueryScope,
    QuerySpec,
    QuerySpecEntry,
    make_course_query_spec,
    make_registration_query_spec,
)
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.models.common import CdEDataclass, CdEDataclassMap

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing_extensions import Self  # pylint: disable=ungrouped-imports

    from cdedb.common import CdEDBObject
    from cdedb.database.query import (  # pylint: disable=ungrouped-imports
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
            cls, entity_key: Optional[str] = None,
    ) -> tuple[str, str, tuple[str, ...]]:
        return (
            cls.database_table,
            entity_key or cls.entity_key,
            tuple(cls.database_fields()),
        )


#
# get_event
#


@dataclasses.dataclass
class Event(EventDataclass):
    database_table = "event.events"
    entity_key = "id"

    title: str
    shortname: str

    institution: const.PastInstitutions
    description: Optional[str]

    registration_start: Optional[datetime.datetime]
    registration_soft_limit: Optional[datetime.datetime]
    registration_hard_limit: Optional[datetime.datetime]

    iban: Optional[str]
    orga_address: Optional[vtypes.Email]
    website_url: Optional[str]

    registration_text: Optional[str]
    mail_text: Optional[str]
    participant_info: Optional[str]
    notes: Optional[str]
    field_definition_notes: Optional[str]

    offline_lock: bool
    is_archived: bool
    is_cancelled: bool
    is_visible: bool
    is_course_list_visible: bool
    is_course_state_visible: bool
    is_participant_list_visible: bool
    is_course_assignment_visible: bool
    use_additional_questionnaire: bool
    notify_on_registration: const.NotifyOnRegistration

    lodge_field_id: Optional[vtypes.ID]

    parts: CdEDataclassMap["EventPart"]
    tracks: CdEDataclassMap["CourseTrack"]

    fields: CdEDataclassMap["EventField"]
    custom_query_filters: CdEDataclassMap["CustomQueryFilter"]
    fees: CdEDataclassMap["EventFee"]

    part_groups: CdEDataclassMap["PartGroup"]
    track_groups: CdEDataclassMap["TrackGroup"]

    orgas: set[vtypes.ID] = dataclasses.field(default_factory=set)

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['orgas'] = set(data['orgas'])
        data['parts'] = EventPart.many_from_database(data['parts'])
        data['tracks'] = CourseTrack.many_from_database(data['tracks'])
        data['fields'] = EventField.many_from_database(data['fields'])
        data['custom_query_filters'] = CustomQueryFilter.many_from_database(
            data['custom_query_filters'])
        data['fees'] = EventFee.many_from_database(data['fees'])
        data['part_groups'] = PartGroup.many_from_database(data['part_groups'])
        data['track_groups'] = TrackGroup.many_from_database(data['track_groups'])
        return super().from_database(data)

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            if get_origin(field.type) is dict:
                value_kind = get_args(field.type)[1]
                if isinstance(value_kind, ForwardRef):
                    value_kind = value_kind.__forward_arg__
                value_class = globals()[value_kind]
                if issubclass(value_class, EventDataclass):
                    for obj in getattr(self, field.name).values():
                        obj.event = self

        for part in self.parts.values():
            part.tracks = {
                track_id: self.tracks[track_id]
                for track_id in part.tracks
            }
            for track in part.tracks.values():
                track.part = part
        for part_group in self.part_groups.values():
            part_group.parts = {
                part_id: self.parts[part_id]
                for part_id in part_group.parts
            }
            for part in part_group.parts.values():
                part.part_groups[part_group.id] = part_group
                part.part_group_ids.add(part_group.id)
        for track_group in self.track_groups.values():
            track_group.tracks = {
                track_id: self.tracks[track_id]
                for track_id in track_group.tracks
            }
            for track in track_group.tracks.values():
                track.track_groups[track_group.id] = track_group
                track.track_group_ids.add(track_group.id)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT persona_id
                    FROM event.orgas
                    WHERE event_id = events.id
                ) AS orgas
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
            and (self.registration_hard_limit is None
                 or self.registration_hard_limit >= reference_time))

    def is_visible_for(self, user: User, is_registered: bool, *,
                       privileged: bool) -> bool:
        """Whether an event is visible dependent on your own registration status.

         :param privileged: If access in a privileged capacity is to be considered."""

        return is_registered or self.is_visible or (privileged and (
            "event_admin" in user.roles or user.persona_id in self.orgas))

    @functools.cached_property
    def lodge_field(self) -> Optional["EventField"]:
        if self.lodge_field_id is None:
            return None
        return self.fields[self.lodge_field_id]

    @functools.cached_property
    def personalized_fees(self) -> CdEDataclassMap["EventFee"]:
        return {fee.id: fee for fee in self.fees.values() if fee.is_personalized()}

    @functools.cached_property
    def conditional_fees(self) -> CdEDataclassMap["EventFee"]:
        return {fee.id: fee for fee in self.fees.values() if fee.is_conditional()}

    @functools.cached_property
    def grouped_fields(self) -> dict[
        const.FieldAssociations,
        dict[str, list["EventField"]],
    ]:
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

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ProtoID

    title: str
    shortname: str

    part_begin: datetime.date
    part_end: datetime.date

    waitlist_field_id: Optional[vtypes.ID]
    camping_mat_field_id: Optional[vtypes.ID]

    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(default_factory=dict)

    part_groups: CdEDataclassMap["PartGroup"] = dataclasses.field(
        default_factory=dict, compare=False, repr=False)
    part_group_ids: set[int] = dataclasses.field(default_factory=set)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
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
    id: vtypes.ProtoID

    title: str
    shortname: str
    sortkey: int

    num_choices: int
    min_choices: int

    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(
        init=False, compare=False, repr=False)

    @abc.abstractmethod
    def is_complex(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def reference_track(self) -> "CourseTrack":
        ...

    @abc.abstractmethod
    def as_dict(self) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def _lt_inner(self, other: Any) -> bool:
        ...

    @abc.abstractmethod
    def get_sortkey(self) -> Sortkey:
        ...

    def __lt__(self, other: Any) -> bool:
        # pylint: disable=line-too-long
        if isinstance(self, CourseChoiceObject) and isinstance(other, CourseChoiceObject):
            return self._lt_inner(other)
        return NotImplemented


@dataclasses.dataclass
class CourseTrack(EventDataclass, CourseChoiceObject):
    database_table = "event.course_tracks"
    entity_key = "part_id"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    part: EventPart = dataclasses.field(init=False, compare=False, repr=False)
    part_id: vtypes.ProtoID

    course_room_field_id: Optional[vtypes.ID]

    track_groups: CdEDataclassMap["TrackGroup"] = dataclasses.field(
        default_factory=dict, compare=False, repr=False)
    track_group_ids: set[int] = dataclasses.field(default_factory=set)

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
    def tracks(self, value: CdEDataclassMap["CourseTrack"]) -> None:  # pylint: disable=no-self-use
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

    id: vtypes.ProtoID = dataclasses.field(metadata={'validation_exclude': True})

    event: Event = dataclasses.field(
        init=False, compare=False, repr=False, metadata={'validation_exclude': True},
    )
    # Exclude during creation, update and request.
    event_id: vtypes.ID = dataclasses.field(
        metadata={'validation_exclude': True, 'request_exclude': True},
    )

    kind: const.EventFeeType
    title: str
    notes: Optional[str]

    condition: Optional[vtypes.EventFeeCondition]
    amount: Optional[decimal.Decimal]
    amount_min: Optional[decimal.Decimal] = dataclasses.field(
        default=None, metadata={'validation_exclude': True, 'database_exclude': True})
    amount_max: Optional[decimal.Decimal] = dataclasses.field(
        default=None, metadata={'validation_exclude': True, 'database_exclude': True})

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
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
            parse_result, {}, {}, {}, condition_only=True)[1]

    def get_sortkey(self) -> Sortkey:
        return self.kind, self.title, self.amount or decimal.Decimal(0)


@dataclasses.dataclass
class EventField(EventDataclass):
    database_table = "event.field_definitions"

    id: vtypes.ProtoID = dataclasses.field(metadata={'validation_exclude': True})

    event: Event = dataclasses.field(
        init=False, compare=False, repr=False, metadata={'validation_exclude': True},
    )
    # Exclude during creation, update and request.
    event_id: vtypes.ID = dataclasses.field(
        metadata={'validation_exclude': True, 'request_exclude': True},
    )

    # Internal metadata.
    field_name: vtypes.RestrictiveIdentifier = dataclasses.field(
        metadata={'update_exclude': True})
    kind: const.FieldDatatypes
    association: const.FieldAssociations = dataclasses.field(
        metadata={'update_exclude': True})

    # Userfacing metadata. Purely for UI.
    title: str  # Userfacing label.
    sort_group: Optional[str] = None  # Used to group multiple fields together.
    sortkey: int = 0  # Sortkey of the field (within it's group).
    description: Optional[str] = None  # Shown as hovertext of the label.

    # Usage configuration, i.e. where is this field used.
    checkin: bool = False

    entries: Optional[dict[str, str]] = None

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['entries'] = dict(data['entries'] or []) or None
        return super().from_database(data)

    def get_sortkey(self) -> Sortkey:
        return (
            self.event,
            self.sort_group or chr(sys.maxunicode),  # Sort empty group last.
            self.sortkey,
            self.title,
            self.field_name,
        )


@dataclasses.dataclass
class CustomQueryFilter(EventDataclass):
    database_table = "event.custom_query_filters"

    event: Event = dataclasses.field(
        init=False, compare=False, repr=False, metadata={'validation_exclude': True},
    )
    event_id: vtypes.ProtoID = dataclasses.field(metadata={'update_exlude': True})

    scope: QueryScope = dataclasses.field(metadata={'update_exlude': True})
    title: str
    notes: Optional[str]
    fields: set[str] = dataclasses.field(metadata={'database_include': True})

    def __post_init__(self) -> None:
        if isinstance(self.fields, str):  # type: ignore[unreachable]
            self.fields = set(self.fields.split(','))  # type: ignore[unreachable]

    def to_database(self) -> "CdEDBObject":
        ret = super().to_database()
        ret['fields'] = self.get_field_string()
        return ret

    def get_sortkey(self) -> Sortkey:
        return (self.event_id, self.scope, self.title)

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
        spec[self.get_field_string()] = QuerySpecEntry(type_, self.title)

    def is_valid(self, spec: QuerySpec) -> bool:
        """Check whether all fields are in the spec and of the same type."""
        return all(f in spec for f in self.fields) and len(
            {spec[f].type for f in self.fields}) == 1

    def get_field_titles(self, spec: QuerySpec, g: Callable[[str], str],
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
    event_id: vtypes.ProtoID

    title: str
    shortname: str
    notes: Optional[str]
    constraint_type: const.EventPartGroupType

    parts: CdEDataclassMap[EventPart] = dataclasses.field(default_factory=dict)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT part_id
                    FROM event.part_group_parts
                    WHERE part_group_id = part_groups.id
                ) AS parts
            FROM
                event.part_groups
            WHERE
                {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    def get_sortkey(self) -> Sortkey:
        # TODO maybe sort by constraint_type first?
        return (self.title, )


@dataclasses.dataclass
class TrackGroup(EventDataclass):
    database_table = "event.track_groups"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ProtoID

    title: str
    shortname: str
    notes: Optional[str]
    sortkey: int
    constraint_type: const.CourseTrackGroupType

    tracks: CdEDataclassMap[CourseTrack] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "TrackGroup":
        if data['constraint_type'] == const.CourseTrackGroupType.course_choice_sync:
            return super(cls, SyncTrackGroup).from_database(data)
        return super().from_database(data)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT track_id
                    FROM event.track_group_tracks
                    WHERE track_group_id = track_groups.id
                ) AS tracks
            FROM
                event.track_groups
            WHERE
                {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    def get_sortkey(self) -> Sortkey:
        return self.sortkey, self.constraint_type, self.title


class SyncTrackGroup(TrackGroup, CourseChoiceObject):
    constraint_type = const.CourseTrackGroupType.course_choice_sync

    def is_complex(self) -> bool:
        return True

    @property
    def reference_track(self) -> CourseTrack:
        return list(self.tracks.values())[0]

    @property
    def num_choices(self) -> int:
        return self.reference_track.num_choices

    @num_choices.setter
    def num_choices(self, value: int) -> None:
        for track in self.tracks.values():
            track.num_choices = value

    @property
    def min_choices(self) -> int:
        return self.reference_track.min_choices

    @min_choices.setter
    def min_choices(self, value: int) -> None:
        for track in self.tracks.values():
            track.min_choices = value

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, CourseChoiceObject):
            return CourseChoiceObject.__lt__(self, other)
        return super().__lt__(other)


#
# get_questionnaire
#

@dataclasses.dataclass
class Questionnaire:
    registration: list["QuestionnaireRow"]
    additional: list["QuestionnaireRow"]


@dataclasses.dataclass
class QuestionnaireRow(EventDataclass):
    database_table = "event.questionnaire_rows"

    event: Event
    field: Optional[EventField]

    def get_sortkey(self) -> Sortkey:
        return (0, )


#
# get_course
#

@dataclasses.dataclass
class Course(EventDataclass):
    database_table = "event.courses"
    entity_key = "id"

    # event: Event
    event_id: vtypes.ID

    segments: set[vtypes.ID]
    active_segments: set[vtypes.ID]

    nr: str
    title: str
    shortname: str
    description: str

    instructors: Optional[str]

    min_size: int
    max_size: int

    is_visible: bool

    notes: Optional[str]

    fields: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
                SELECT
                    {', '.join(cls.database_fields())},
                    array(
                        SELECT track_id
                        FROM event.course_segments
                        WHERE course_id = event.courses.id
                    ) AS segments,
                    array(
                        SELECT track_id
                        FROM event.course_segments
                        WHERE course_id = event.courses.id AND is_active = True
                    ) AS active_segments
                FROM
                    event.courses
                WHERE
                    {entity_key or cls.entity_key} = ANY(%s)
            """
        params = (entities,)
        return query, params

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['fields'] = cast_fields(
            data['fields'], EventField.many_from_database(data.pop('event_fields')))
        data['segments'] = set(data['segments'])
        data['active_segments'] = set(data['active_segments'])
        return super().from_database(data)

    def get_sortkey(self) -> Sortkey:
        return self.nr, self.shortname

#
# get_lodgement_group + get_lodgement
#


@dataclasses.dataclass
class LodgementGroup(EventDataclass):
    database_table = "event.lodgement_groups"

    # event: Event
    event_id: vtypes.ID
    title: str

    lodgement_ids: set[int] = dataclasses.field(default_factory=set,
                                                metadata={'database_exclude': True})
    regular_capacity: int = dataclasses.field(default=0,
                                              metadata={'database_exclude': True})
    camping_mat_capacity: int = dataclasses.field(default=0,
                                                  metadata={'database_exclude': True})

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
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
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['lodgement_ids'] = set(data['lodgement_ids'])
        return super().from_database(data)

    def get_sortkey(self) -> Sortkey:
        return (self.title, )


@dataclasses.dataclass
class Lodgement(EventDataclass):
    database_table = "event.lodgements"
    entity_key = "id"

    # event: Event
    event_id: vtypes.ID
    group: LodgementGroup = dataclasses.field(metadata={'database_exclude': True})
    group_id: vtypes.ID

    title: str
    regular_capacity: int
    camping_mat_capacity: int
    notes: Optional[str]

    fields: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['fields'] = cast_fields(data['fields'], data.pop('event_fields'))
        if 'group_data' in data:
            data['group'] = LodgementGroup.from_database(data.pop('group_data'))
        return super().from_database(data)

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
        return (0, )


@dataclasses.dataclass
class RegistrationPart(EventDataclass):
    database_table = "event.registration_parts"

    registration: Registration
    tracks: dict[CourseTrack, "RegistrationTrack"]

    lodgement: Optional[Lodgement]

    def get_sortkey(self) -> Sortkey:
        return (0, )


@dataclasses.dataclass
class RegistrationTrack(EventDataclass):
    database_table = "event.registration_tracks"

    registration: Registration
    registration_part: RegistrationPart

    course: Optional[Course]
    instructed: Optional[Course]

    choices: list[Course]

    def get_sortkey(self) -> Sortkey:
        return (0, )


@dataclasses.dataclass
class PersonalizedFee(EventDataclass):
    database_table = "event.personalized_fees"
    entity_key = "registration_id"

    registration_id: vtypes.ID
    fee_id: vtypes.ID

    amount: Optional[decimal.Decimal]

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
            params: tuple[DatabaseValue_s, ...] = (  # pylint: disable=used-before-assignment
                self.registration_id, self.fee_id, self.amount,
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
        return (0, )
