import dataclasses
import datetime
from collections import defaultdict

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event
from cdedb.common import CdEDBObjectMap
from cdedb.common.sorting import EntitySorter, Sortkey, xsorted
from cdedb.models.common import CdEDataclass, CdEDataclassMap


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


def past_course_entries(pcourses: CdEDBObjectMap) -> list[tuple[int, str]]:
    sortkey = EntitySorter.past_course

    pcourse_entries = [
        (pcourse["id"], f"{pcourse['nr']}. {pcourse['title']}")
        for pcourse in xsorted(pcourses.values(), key=sortkey)
    ]
    return pcourse_entries


def past_course_by_past_event_selectize_options(
    pcourses: CdEDBObjectMap,
) -> dict[int, list[dict[str, str | int]]]:
    pcourses_by_event: dict[int, CdEDBObjectMap] = defaultdict(dict)
    for pcourse_id, pcourse in pcourses.items():
        pcourses_by_event[pcourse['pevent_id']][pcourse_id] = pcourse

    return {
        pevent_id: [
            {'id': pcourse_id, 'title': label}
            for pcourse_id, label in past_course_entries(pevent_pcourses)
        ]
        for pevent_id, pevent_pcourses in pcourses_by_event.items()
    }
