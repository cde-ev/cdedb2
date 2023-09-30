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
from typing import TYPE_CHECKING, ClassVar, Collection, Optional, get_args, get_origin

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject
from cdedb.models.common import CdEDataclass
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.database.query import DatabaseValue_s


#
# meta
#

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
                           ) -> dict[vtypes.ID, "Self"]:
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

    parts: dict[vtypes.ID, "EventPart"]
    tracks: dict[vtypes.ID, "CourseTrack"]

    fields: dict[vtypes.ID, "EventField"]
    fees: dict[vtypes.ID, "EventFee"]

    part_groups: dict[vtypes.ID, "PartGroup"]
    track_groups: dict[vtypes.ID, "TrackGroup"]

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
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


@dataclasses.dataclass
class EventPart(EventDataclass):
    database_table = "event.event_parts"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)

    title: str
    shortname: str

    part_begin: datetime.date
    part_end: datetime.date

    waitlist_field: Optional["EventField"]
    camping_mat_field: Optional["EventField"]

    tracks: dict[vtypes.ID, "CourseTrack"] = dataclasses.field(default_factory=dict)

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

    kind: const.EventFeeType
    title: str
    amount: decimal.Decimal
    condition: vtypes.EventFeeCondition
    notes: Optional[str]


@dataclasses.dataclass
class EventField(EventDataclass):
    database_table = "event.field_definitions"

    event: Event = dataclasses.field(init=False, compare=False, repr=False)

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

    title: str
    shortname: str
    notes: Optional[str]
    constraint_type: const.EventPartGroupType

    parts: dict[vtypes.ID, EventPart] = dataclasses.field(default_factory=dict)

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

    title: str
    shortname: str
    notes: Optional[str]
    sortkey: int
    constraint_type: const.CourseTrackGroupType

    tracks: dict[vtypes.ID, CourseTrack] = dataclasses.field(default_factory=dict)

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

    # event: Event
    segments: dict[CourseTrack, bool]

#
# get_lodgement_group + get_lodgement
#


@dataclasses.dataclass
class LodgementGroup(EventDataclass):
    database_table = "event.lodgement_groups"

    # event: Event


@dataclasses.dataclass
class Lodgement(EventDataclass):
    database_table = "event.lodgements"

    # event: Event
    group: LodgementGroup


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
