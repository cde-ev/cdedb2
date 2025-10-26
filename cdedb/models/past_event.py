import dataclasses
import datetime
from collections import defaultdict

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.models.common import CdEDataclass, CdEDataclassMap, MetaFlag as Meta


@dataclasses.dataclass
class PastEvent(CdEDataclass):
    database_table = "past_event.events"

    title: str
    shortname: str
    institution: const.PastInstitutions
    tempus: datetime.date
    description: str | None
    participant_info: str | None

    @classmethod
    def from_event(cls, event: cdedb.models.event.Event, part_id: int) -> "PastEvent":
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
            participant_info=None,
        )

    def get_sortkey(self) -> Sortkey:
        return (self.tempus,)

    @staticmethod
    def get_entries(pevents: CdEDataclassMap["PastEvent"]) -> list[tuple[int, str]]:
        # This groups the events by year descending, and then orders them by title for
        #  better UX in _very_ long select inputs.
        return [
            (pevent.id, pevent.title)
            for pevent in xsorted(
                pevents.values(), key=lambda x: (-x.tempus.year, x.title, x.id)
            )
        ]


@dataclasses.dataclass
class PastCourse(CdEDataclass):
    database_table = "past_event.courses"

    pevent_id: vtypes.ID = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)
    nr: str
    title: str
    description: str | None

    @classmethod
    def from_event(
        cls, course: cdedb.models.event.Course, pevent_id: int
    ) -> "PastCourse":
        return cls(
            id=vtypes.ID(-1),
            pevent_id=vtypes.ID(pevent_id),
            nr=course.nr,
            title=course.title,
            description=course.description,
        )

    def get_sortkey(self) -> Sortkey:
        return (self.nr, self.title)


def past_course_entries(pcourses: CdEDataclassMap[PastCourse]) -> list[tuple[int, str]]:
    return [
        (pcourse.id, f"{pcourse.nr}. {pcourse.title}")
        for pcourse in xsorted(pcourses.values())
    ]


def past_course_by_past_event_selectize_options(
    pcourses: CdEDataclassMap[PastCourse],
) -> dict[int, list[dict[str, str | int]]]:
    pcourses_by_event: dict[int, CdEDataclassMap[PastCourse]] = defaultdict(dict)
    for pcourse in pcourses.values():
        pcourses_by_event[pcourse.pevent_id][pcourse.id] = pcourse

    return {
        pevent_id: [
            {'id': pcourse_id, 'title': label}
            for pcourse_id, label in past_course_entries(pevent_pcourses)
        ]
        for pevent_id, pevent_pcourses in pcourses_by_event.items()
    }
