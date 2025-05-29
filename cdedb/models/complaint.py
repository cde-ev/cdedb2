"""Dataclass definitions for the complaint realm."""
import dataclasses
import datetime
import functools

from typing import Self

import cdedb.database.constants as const
import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject, now
from cdedb.common.sorting import Sortkey
from cdedb.models.common import CdEDataclass, CdEDataclassMap


@dataclasses.dataclass(kw_only=True)
class Case(CdEDataclass):
    database_table = "complaint.cases"

    kind: const.ComplaintKind
    is_grave: bool
    summary: str | None

    start_date: datetime.datetime | None
    end_date: datetime.datetime | None

    entries: CdEDataclassMap["ComplaintEntry"]

    def get_sortkey(self) -> Sortkey:
        today = now().date()
        return (self.kind, self.end_date or today, self.start_date or today)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["entries"] = ComplaintEntry.from_database(data["entries"])
        ret = super().from_database(data)
        for entry in data["entries"]:
            entry.case = ret
        return ret


@dataclasses.dataclass(kw_only=True)
class ComplaintEntry(CdEDataclass):
    database_table = "complaint.entries"

    case: Case = dataclasses.field(init=False, compare=False, repr=False)
    case_id: vtypes.ID
    entry_type: const.ComplaintEntryType

    root_entry: vtypes.ID | None

    concerned_id: vtypes.ID

    all_versions: CdEDataclassMap["ComplaintEntryVersion"]

    @functools.cached_property
    def active_version(self) -> "ComplaintEntryVersion | None":
        for version in self.all_versions.values():
            if version.dtime is None:
                return version
        return None

    @functools.cached_property
    def deleted_versions(self) -> CdEDataclassMap["ComplaintEntryVersion"]:
        return {
            version.id: version
            for version in self.all_versions.values()
            if version.dtime
        }

    def get_sortkey(self) -> Sortkey:
        return ()

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["all_versions"] = ComplaintEntryVersion.from_database(data["all_versions"])
        return super().from_database(data)


@dataclasses.dataclass(kw_only=True)
class ComplaintEntryVersion(CdEDataclass):
    database_table = "complaint.entry_versions"

    entry_id: vtypes.ID

    # description: str | None
    length: int | None
    timestamp: datetime.datetime

    ctime: datetime.datetime
    submitted_by: vtypes.ID

    dtime: datetime.datetime
    deleted_by: vtypes.ID | None
    dreason: str | None

    def get_sortkey(self) -> Sortkey:
        return (self.ctime,)
