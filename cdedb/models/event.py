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
import copy
import dataclasses
import datetime
import decimal
from typing import (
    TYPE_CHECKING, Any, Callable, ClassVar, Collection, Mapping, Optional, TypeVar,
    get_args, get_origin,
)

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, User, cast_fields, now
from cdedb.common.sorting import EntitySorter, Sortkey
from cdedb.models.common import CdEDataclass
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.database.query import (  # pylint: disable=ungrouped-imports
        DatabaseValue_s,
    )


#
# meta
#

T = TypeVar('T')
# Should actually be a vtypes.ProtoID instead of an int
CdEDataclassMap = dict[int, T]


@dataclasses.dataclass
class EventDataclass(CdEDataclass):
    entity_key: ClassVar[str] = "event_id"
    sorter: ClassVar[Callable[[CdEDBObject], Sortkey]] = lambda x: (x['id'],)

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s"]]:
        query = f"""
            SELECT {','.join(cls.database_fields())}
            FROM {cls.database_table}
            WHERE {entity_key or cls.entity_key} = ANY(%s)
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
    def many_from_database(cls, list_of_data: Collection[CdEDBObject]
                           ) -> CdEDataclassMap["Self"]:
        return {
            obj.id: obj for obj in map(cls.from_database, list_of_data)
        }

    def as_dict(self) -> dict[str, Any]:
        """Return the fields of a dataclass instance as a new dictionary mapping
        field names to field values.

        This is an almost 1:1 copy of dataclasses.asdict. However, we need to exclude
        the backward references to avoid infinit recursion, so we need to dig into
        the implementation details here...
        """
        return self._asdict_inner(self, dict)

    def _asdict_inner(self, obj: Any, dict_factory: Any):  # type: ignore[no-untyped-def]
        if dataclasses._is_dataclass_instance(obj):  # type: ignore[attr-defined]  # pylint: disable=protected-access
            result = []
            for f in dataclasses.fields(obj):
                #######################################################
                # the following two lines are the only differences to #
                # dataclasses._as_dict_inner                          #
                #######################################################
                if not self._include_in_dict(f):
                    continue
                value = self._asdict_inner(getattr(obj, f.name), dict_factory)
                result.append((f.name, value))
            return dict_factory(result)
        elif isinstance(obj, tuple) and hasattr(obj, '_fields'):
            # obj is a namedtuple.  Recurse into it, but the returned
            # object is another namedtuple of the same type.  This is
            # similar to how other list- or tuple-derived classes are
            # treated (see below), but we just need to create them
            # differently because a namedtuple's __init__ needs to be
            # called differently (see bpo-34363).

            # I'm not using namedtuple's _asdict()
            # method, because:
            # - it does not recurse in to the namedtuple fields and
            #   convert them to dicts (using dict_factory).
            # - I don't actually want to return a dict here.  The main
            #   use case here is json.dumps, and it handles converting
            #   namedtuples to lists.  Admittedly we're losing some
            #   information here when we produce a json list instead of a
            #   dict.  Note that if we returned dicts here instead of
            #   namedtuples, we could no longer call asdict() on a data
            #   structure where a namedtuple was used as a dict key.

            return type(obj)(*[self._asdict_inner(v, dict_factory) for v in obj])
        elif isinstance(obj, (list, tuple)):
            # Assume we can create an object of this type by passing in a
            # generator (which is not true for namedtuples, handled
            # above).
            return type(obj)(self._asdict_inner(v, dict_factory) for v in obj)
        elif isinstance(obj, dict):
            return type(obj)((self._asdict_inner(k, dict_factory),
                              self._asdict_inner(v, dict_factory))
                             for k, v in obj.items())
        else:
            return copy.deepcopy(obj)

    @staticmethod
    def _include_in_dict(field: dataclasses.Field[Any]) -> bool:
        """Should this field be part of the dict representation of this object?"""
        return field.repr

    def __lt__(self, other: "EventDataclass") -> bool:
        if not isinstance(other, self.__class__) and not (
                isinstance(self, CourseChoiceObject)
                and isinstance(other, CourseChoiceObject)
        ):
            return NotImplemented
        return self.__class__.sorter(
            self.as_dict()) < other.__class__.sorter(other.as_dict())


#
# get_event
#

@dataclasses.dataclass
class Event(EventDataclass):
    database_table = "event.events"
    entity_key = "id"
    sorter = EntitySorter.event

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

    lodge_field_id: Optional[vtypes.ID]

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
            WHERE {entity_key or cls.entity_key} = ANY(%s)
            """
        params = (entities,)
        return query, params

    @property
    def begin(self) -> datetime.date:
        return min(p.part_begin for p in self.parts.values())

    @property
    def end(self) -> datetime.date:
        return max(p.part_end for p in self.parts.values())

    @property
    def is_open(self) -> bool:
        reference_time = now()
        return bool(
            self.registration_start
            and self.registration_start <= reference_time
            and (self.registration_hard_limit is None
                 or self.registration_hard_limit >= reference_time))

    @property
    def lodge_field(self) -> Optional["EventField"]:
        if self.lodge_field_id is None:
            return None
        return self.fields[self.lodge_field_id]

    def is_visible_for(self, user: User) -> bool:
        return ("event_admin" in user.roles or user.persona_id in self.orgas
                or self.is_visible)

    def __lt__(self, other: "EventDataclass") -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (self.begin, self.end, self.title, self.id) < (
            other.begin, other.end, other.title, other.id)


@dataclasses.dataclass
class EventPart(EventDataclass):
    database_table = "event.event_parts"
    sorter = EntitySorter.event_part

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


@dataclasses.dataclass
class CourseChoiceObject(abc.ABC):
    id: vtypes.ProtoID
    sorter: ClassVar[Callable[[CdEDBObject], Sortkey]]

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


@dataclasses.dataclass
class CourseTrack(EventDataclass, CourseChoiceObject):
    database_table = "event.course_tracks"
    entity_key = "part_id"
    sorter = EntitySorter.course_choice_object

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


@dataclasses.dataclass
class EventFee(EventDataclass):
    database_table = "event.event_fees"
    sorter = EntitySorter.event_fee

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
    sorter = EntitySorter.event_field

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
    sorter = EntitySorter.event_part_group

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


@dataclasses.dataclass
class TrackGroup(EventDataclass):
    database_table = "event.track_groups"
    sorter = EntitySorter.course_choice_object

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
    sorter = EntitySorter.course

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

#
# get_lodgement_group + get_lodgement
#


@dataclasses.dataclass
class LodgementGroup(EventDataclass):
    database_table = "event.lodgement_groups"
    sorter = EntitySorter.lodgement_group

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


@dataclasses.dataclass
class Lodgement(EventDataclass):
    database_table = "event.lodgements"
    entity_key = "id"
    sorter = lambda x: (x['group']['title'], x['group']['id'], x['title'], x['id'])

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


#
# get_registration
#

@dataclasses.dataclass
class Registration(EventDataclass):
    database_table = "event.registrations"
    sorter = EntitySorter.persona

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
