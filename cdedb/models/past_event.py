"""Contains only some helpers for now, that might become dataclass methods later."""

from collections import defaultdict

from cdedb.common import CdEDBObjectMap
from cdedb.common.sorting import EntitySorter, xsorted


def past_event_entries(pevents: CdEDBObjectMap) -> list[tuple[int, str]]:
    sortkey = EntitySorter.past_event_select_entries

    pevent_entries = [
        (pevent['id'], pevent['title'])
        for pevent in xsorted(pevents.values(), key=sortkey)
    ]
    return pevent_entries


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
