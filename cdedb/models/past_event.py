import dataclasses
import datetime
from collections import defaultdict
from typing import Any, Self

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.models.common import CdEDataclass, CdEDataclassMap, MetaFlag as Meta


@dataclasses.dataclass
class PastEvent(CdEDataclass):
    database_table = "past_event.events"

    id: vtypes.ID = dataclasses.field(metadata=(Meta.input_exclude).as_dict)
    title: str
    shortname: str
    institution: const.PastInstitutions
    tempus: datetime.date
    description: str | None
    participant_info: str | None

    @classmethod
    def from_event(cls, event: cdedb.models.event.Event, part_id: int) -> Self:
        if part_id not in event.parts:
            raise ValueError
        part = event.parts[part_id]
        title = event.title
        shortname = event.shortname
        if len(event.parts) > 1:
            title = f"{event.title} ({part.title})"
            shortname = f"{event.shortname} ({part.shortname})"
        return cls(
            id=vtypes.ID(-1),
            title=title,
            shortname=shortname,
            institution=event.institution,
            tempus=part.part_begin,
            description=event.description,
            # The event field 'participant_info' usually contains information
            # no longer relevant, so we do not keep it here
            participant_info=None,
        )

    def get_sortkey(self) -> Sortkey:
        return (-self.tempus.toordinal(), self.title)

    def get_entries_sortkey(self) -> Sortkey:
        return (-self.tempus.year, self.title, self.id)

    @classmethod
    def get_entries(cls, pevents: CdEDataclassMap[Self]) -> list[tuple[int, str]]:
        """Used for better UX in _very_ long select inputs.

        Groups the events by year descending, and then orders them by title.
        """
        return [
            (pevent.id, pevent.title)
            for pevent in xsorted(pevents.values(), key=cls.get_entries_sortkey)
        ]


@dataclasses.dataclass
class PastCourse(CdEDataclass):
    database_table = "past_event.courses"

    pevent_id: vtypes.ID = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)
    pevent: PastEvent = dataclasses.field(init=False, compare=False, repr=False)
    nr: str
    title: str
    description: str | None

    @classmethod
    def from_course(cls, course: cdedb.models.event.Course, pevent_id: int) -> Self:
        return cls(
            id=vtypes.ID(-1),
            pevent_id=vtypes.ID(pevent_id),
            nr=course.nr,
            title=course.title,
            description=course.description,
        )

    def get_sortkey(self) -> Sortkey:
        return (self.nr, self.title)

    @classmethod
    def get_entries(cls, pcourses: CdEDataclassMap[Self]) -> list[tuple[int, str]]:
        return [
            (pcourse.id, f"{pcourse.nr}. {pcourse.title}")
            for pcourse in xsorted(pcourses.values())
        ]

    @classmethod
    def get_combined_entries(
        cls,
        pcourses: CdEDataclassMap[Self],
    ) -> dict[int, list[dict[str, str | int]]]:
        pcourses_by_event: dict[int, CdEDataclassMap[Self]] = defaultdict(dict)
        for pcourse in pcourses.values():
            pcourses_by_event[pcourse.pevent_id][pcourse.id] = pcourse

        return {
            pevent_id: [
                {'id': pcourse_id, 'title': label}
                for pcourse_id, label in cls.get_entries(pevent_pcourses)
            ]
            for pevent_id, pevent_pcourses in pcourses_by_event.items()
        }


@dataclasses.dataclass
class PastEventParticipant(CdEDataclass):
    database_table = "past_event.participants"

    persona_id: vtypes.ID
    persona: dict[str, Any] = dataclasses.field(
        compare=False, repr=False, metadata=Meta.exclude.as_dict
    )

    pevent_id: vtypes.ID
    pevent: PastEvent = dataclasses.field(compare=False, repr=False)

    orga_status: const.PastOrgaKind
    music_status: const.PastMusicKind

    course_assignments: list["PastCourseAssignment"] = dataclasses.field(
        init=False, compare=False, repr=False, default_factory=list
    )

    def get_sortkey(self) -> Sortkey:
        return (
            self.persona["family_name"],
            self.persona["given_names"],
            self.persona_id,
            *self.pevent.get_sortkey(),
        )


@dataclasses.dataclass
class PastCourseAssignment(CdEDataclass):
    database_table = "past_event.course_participants"

    persona_id: vtypes.ID
    participant_id: vtypes.ID
    pcourse_id: vtypes.ID
    pcourse: PastCourse = dataclasses.field(compare=False, repr=False)

    instructor_status: const.PastInstructorKind

    def get_sortkey(self) -> Sortkey:
        return self.pcourse.get_sortkey()
