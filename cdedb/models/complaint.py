"""Dataclass definitions for the complaint realm."""

import dataclasses
import datetime
import functools
from collections.abc import Collection
from typing import Optional, Self

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, now
from cdedb.common.sorting import Sortkey
from cdedb.database.query import DatabaseValue_s
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
        ret: set[int] = set()
        # TODO add more people here
        for entry in self.entries.values():
            if entry.concerned_id:
                ret.add(entry.concerned_id)
            ret.update(version.submitted_by for version in entry.all_versions)
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

    id: vtypes.ProtoID = dataclasses.field(metadata={"validation_exclude": True})

    case: Case = dataclasses.field(init=False, compare=False, repr=False)
    case_id: vtypes.ID = dataclasses.field(metadata={"validation_exclude": True})
    entry_type: const.ComplaintEntryType

    root_entry_id: vtypes.ID | None = None

    concerned_id: vtypes.ID | None = None

    all_versions: list["ComplaintEntryVersion"] = dataclasses.field(
        metadata={"validation_exclude": True, "database_exclude": True},
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
    def parent(self) -> "ComplaintEntry | None":
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

    id: vtypes.ProtoID = dataclasses.field(metadata={"validation_exclude": True})

    entry_id: vtypes.ID = dataclasses.field(metadata={"validation_exclude": True})

    description: str | None = dataclasses.field(
        init=False, default=None, metadata={"database_exclude": True}
    )
    length: int | None = dataclasses.field(
        default=None, metadata={"validation_exclude": True}
    )
    timestamp: datetime.datetime

    ctime: datetime.datetime = dataclasses.field(metadata={"validation_exclude": True})
    submitted_by: vtypes.ID = dataclasses.field(metadata={"validation_exclude": True})

    dtime: datetime.datetime | None = dataclasses.field(
        default=None, metadata={"validation_exclude": True}
    )
    deleted_by: vtypes.ID | None = dataclasses.field(
        default=None, metadata={"validation_exclude": True}
    )
    dreason: str | None = dataclasses.field(
        default=None, metadata={"validation_exclude": True}
    )

    authors: list[vtypes.ID] = dataclasses.field(
        metadata={"validation_exclude": True, "database_exclude": True}
    )

    def get_sortkey(self) -> Sortkey:
        return (self.ctime,)

    @classmethod
    def get_select_query(
        cls,
        entities: Collection[int],
        entity_key: Optional[str] = None,
    ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT
                {','.join(cls.database_fields())},
                array(
                    SELECT persona_id
                    FROM {ComplaintAuthors.database_table} AS authors
                    WHERE authors.{ComplaintAuthors.entity_key} = versions.id
                ) AS authors
            FROM
                {cls.database_table} AS versions
            WHERE {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    @classmethod
    def validation_fields(
        cls,
        *,
        creation: bool,
    ) -> tuple[vtypes.MutableTypeMapping, vtypes.MutableTypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        if creation:
            mandatory["authors"] = set[vtypes.ID]
        return mandatory, optional


class ComplaintAuthors:
    database_table = "complaint.authors"
    entity_key = "entry_version_id"
