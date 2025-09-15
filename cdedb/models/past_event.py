"""Contains only some helpers for now, that might become dataclass methods later."""
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
