"""Dataclass definitions for the complaint realm."""

import dataclasses
import datetime
import functools
from typing import Self

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, now
from cdedb.common.sorting import Sortkey
from cdedb.models.common import CdEDataclass, CdEDataclassMap


@dataclasses.dataclass(kw_only=True)
class Case(CdEDataclass):
    database_table = "complaint.cases"

    id: vtypes.ProtoID = dataclasses.field(metadata={"validation_exclude": True})

    kind: const.ComplaintKind
    is_grave: bool = False
    summary: str

    start_date: datetime.date | None = None
    end_date: datetime.date | None = None

    entries: CdEDataclassMap["ComplaintEntry"] = dataclasses.field(
        metadata={"validation_exclude": True}
    )

    def get_persona_ids(self) -> set[int]:
        ret = set()
        # TODO add more people here
        for entry in self.entries.values():
            if entry.concerned_id:
                ret.add(entry.concerned_id)
            update = {version.submitted_by for version in entry.all_versions}
            ret.update(update)
        return ret

    def get_sortkey(self) -> Sortkey:
        today = now().date()
        return (self.kind, self.end_date or today, self.start_date or today)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["entries"] = ComplaintEntry.many_from_database(data["entries"])
        ret = super().from_database(data)
        for entry in data["entries"].values():
            entry.case = ret
        return ret


@dataclasses.dataclass(kw_only=True)
class ComplaintEntry(CdEDataclass):
    database_table = "complaint.entries"
    entity_key = "case_id"

    case: Case = dataclasses.field(init=False, compare=False, repr=False)
    case_id: vtypes.ID
    entry_type: const.ComplaintEntryType

    root_entry_id: vtypes.ID | None

    concerned_id: vtypes.ID | None

    all_versions: list["ComplaintEntryVersion"] = dataclasses.field(
        metadata={"database_exclude": True},
    )

    @functools.cached_property
    def active_version(self) -> "ComplaintEntryVersion | None":
        for version in self.all_versions:
            if version.dtime is None:
                return version
        return None

    @functools.cached_property
    def deleted_versions(self) -> list["ComplaintEntryVersion"]:
        return [version for version in self.all_versions if version.dtime]

    @property
    def root_entry(self) -> Self:
        if self.root_entry_id is None:
            return None
        return self.case.entries[self.root_entry_id]

    @functools.cached_property
    def children(self) -> list["ComplaintEntry"]:
        return [
            entry
            for entry in self.case.entries.values()
            if entry.root_entry_id == self.id
        ]

    def get_sortkey(self) -> Sortkey:
        return ()

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["all_versions"] = list(
            ComplaintEntryVersion.many_from_database(data["all_versions"]).values()
        )
        return super().from_database(data)


@dataclasses.dataclass(kw_only=True)
class ComplaintEntryVersion(CdEDataclass):
    database_table = "complaint.entry_versions"
    entity_key = "entry_id"

    entry_id: vtypes.ID

    # description: str | None
    length: int | None
    timestamp: datetime.datetime

    ctime: datetime.datetime
    submitted_by: vtypes.ID

    dtime: datetime.datetime | None
    deleted_by: vtypes.ID | None
    dreason: str | None

    def get_sortkey(self) -> Sortkey:
        return (self.ctime,)
