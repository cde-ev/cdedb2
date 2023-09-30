"""
event realm tables:
  - event.events
  - event.event_fees
  - event.event_parts
  - event.part_groups
  * event.part_group_parts
  - event.course_tracks
  * event.track_groups
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
import dataclasses
import datetime
import decimal
from typing import (
    TYPE_CHECKING, Any, ClassVar, Collection, Mapping, Optional, TypeVar, get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import cast_fields
from cdedb.common import CdEDBObject, now
from cdedb.models.common import CdEDataclass
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.database.query import DatabaseValue_s


#
# meta
#

T = TypeVar('T')
CdEDataclassMap = dict[vtypes.ProtoID, T]


@dataclasses.dataclass
class EventDataclass(CdEDataclass):
    entity_key: ClassVar[str] = "event_id"

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT {','.join(cls.database_fields())}
            FROM {cls.database_table}
            WHERE {cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    @classmethod
    def database_fields(cls) -> list[str]:
        return [
            field.name for field in dataclasses.fields(cls)
            if field.init
                and get_origin(field.type) is not dict
                and get_origin(field.type) is not set
                and not field.metadata.get('database_exclude')
        ]

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        for field in dataclasses.fields(cls):
            if isinstance(field.type, type) and issubclass(field.type, CdEIntEnum):
                if field.name in data:
                    data[field.name] = field.type(data[field.name])
        return super().from_database(data)

    @classmethod
    def many_from_database(cls, list_of_data: Collection["CdEDBObject"]
                           ) -> CdEDataclassMap["Self"]:
        return {
            obj.id: obj for obj in map(cls.from_database, list_of_data)
        }


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

    lodge_field: Optional["EventField"]

    parts: CdEDataclassMap["EventPart"]
    tracks: CdEDataclassMap["CourseTrack"]

    fields: CdEDataclassMap["EventField"]
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
        data['fees'] = EventFee.many_from_database(data['fees'])
        data['part_groups'] = PartGroup.many_from_database(data['part_groups'])
        data['track_groups'] = TrackGroup.many_from_database(data['track_groups'])
        return super().from_database(data)

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            if get_origin(field.type) is dict:
                value_class = globals()[(get_args(field.type)[1])]
                if issubclass(value_class, EventDataclass):
                    for obj in getattr(self, field.name).values():
                        obj.event = self

        for part in self.parts.values():
            part.waitlist_field = self.fields.get(
                part.waitlist_field)  # type: ignore[call-overload]
            part.camping_mat_field = self.fields.get(
                part.camping_mat_field)  # type: ignore[call-overload]
            part.tracks = {
                track_id: self.tracks[track_id]
                for track_id in part.tracks
            }
            for track in part.tracks.values():
                track.part = part
        for track in self.tracks.values():
            track.course_room_field = self.fields.get(
                track.course_room_field)  # type: ignore[call-overload]
        for part_group in self.part_groups.values():
            part_group.parts = {
                part_id: self.parts[part_id]
                for part_id in part_group.parts
            }
        for track_group in self.track_groups.values():
            track_group.tracks = {
                track_id: self.tracks[track_id]
                for track_id in track_group.tracks
            }
        self.lodge_field = self.fields.get(
            self.lodge_field)  # type: ignore[call-overload]

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
                array(
                    SELECT persona_id
                    FROM event.orgas
                    WHERE event_id = events.id
                ) AS orgas
            FROM {cls.database_table}
            WHERE {cls.entity_key} = ANY(%s)
            """
        params = (entities,)
        return query, params

    @property
    def begin(self) -> datetime.date:
        return min(p.part_begin for p in self.parts.values())

    def end(self) -> datetime.date:
        return min(p.part_end for p in self.parts.values())

    def is_open(self) -> bool:
        reference_time = now()
        return bool(
            self.registration_start
            and self.registration_start <= reference_time
            and (self.registration_hard_limit is None
                 or self.registration_hard_limit >= reference_time))


@dataclasses.dataclass
class EventPart(EventDataclass):
    database_table = "event.event_parts"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ProtoID

    title: str
    shortname: str

    part_begin: datetime.date
    part_end: datetime.date

    waitlist_field: Optional["EventField"]
    camping_mat_field: Optional["EventField"]

    tracks: CdEDataclassMap["CourseTrack"] = dataclasses.field(default_factory=dict)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
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
                event_id = ANY(%s)
        """
        params = (entities,)
        return query, params


@dataclasses.dataclass
class CourseTrack(EventDataclass):
    database_table = "event.course_tracks"
    entity_key = "part_id"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    part: EventPart = dataclasses.field(init=False, compare=False, repr=False)
    part_id: vtypes.ProtoID

    title: str
    shortname: str
    num_choices: int
    min_choices: int
    sortkey: int

    course_room_field: Optional["EventField"]


@dataclasses.dataclass
class EventFee(EventDataclass):
    database_table = "event.event_fees"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ProtoID

    kind: const.EventFeeType
    title: str
    amount: decimal.Decimal
    condition: vtypes.EventFeeCondition
    notes: Optional[str]


@dataclasses.dataclass
class EventField(EventDataclass):
    database_table = "event.field_definitions"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)
    event_id: vtypes.ProtoID

    field_name: vtypes.RestrictiveIdentifier
    title: str
    kind: const.FieldDatatypes
    association: const.FieldAssociations
    checkin: bool
    sortkey: int

    entries: Optional[dict[str, str]]

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['entries'] = dict(data['entries'] or []) or None
        return super().from_database(data)


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
                event_id = ANY(%s)
        """
        params = (entities,)
        return query, params


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
    def get_select_query(cls, entities: Collection[int],
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
                event_id = ANY(%s)
        """
        params = (entities,)
        return query, params


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

    notes: Optional[str]

    fields: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
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
                    id = ANY(%s)
            """
        params = (entities,)
        return query, params

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['fields'] = cast_fields(data['fields'], data.pop('event_fields'))
        data['segments'] = set(data['segments'])
        data['active_segments'] = set(data['active_segments'])
        return super().from_database(data)

#
# get_lodgement_group + get_lodgement
#


@dataclasses.dataclass
class LodgementGroup(EventDataclass):
    database_table = "event.lodgement_groups"

    # event: Event
    event_id: int
    title: str

    lodgement_ids: set[int] = dataclasses.field(default_factory=set, metadata={'database_exclude': True})
    regular_capacity: int = dataclasses.field(default=0, metadata={'database_exclude': True})
    camping_mat_capacity: int = dataclasses.field(default=0, metadata={'database_exclude': True})

    @classmethod
    def get_select_query(cls, entities: Collection[int],
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
                lodgement_groups.{cls.entity_key} = ANY(%s)
            GROUP BY
                lodgement_groups.id
        """
        params = [entities]
        return query, params


@dataclasses.dataclass
class Lodgement(EventDataclass):
    database_table = "event.lodgements"
    entity_key = "id"

    # event: Event
    event_id: int
    group: LodgementGroup = dataclasses.field(
        compare=False, repr=False, metadata={'database_exclude': True})
    group_id: int

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


#
# get_registration
#

@dataclasses.dataclass
class Registration(EventDataclass):
    database_table = "event.registrations"

    # event: Event

    parts: dict[EventPart, "RegistrationPart"]
    tracks: dict[CourseTrack, "RegistrationTrack"]


@dataclasses.dataclass
class RegistrationPart(EventDataclass):
    database_table = "event.registration_parts"

    registration: Registration
    tracks: dict[CourseTrack, "RegistrationTrack"]

    lodgement: Optional[Lodgement]


@dataclasses.dataclass
class RegistrationTrack(EventDataclass):
    database_table = "event.registration_tracks"

    registration: Registration
    registration_part: RegistrationPart

    course: Optional[Course]
    instructed: Optional[Course]

    choices: list[Course]
