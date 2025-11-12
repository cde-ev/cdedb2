"""Dataclass definitions for the complaint realm."""

import dataclasses
import datetime
import functools
import itertools
from collections.abc import Collection
from itertools import chain
from typing import Self, Union

from cryptography.fernet import Fernet

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, User, now
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.database.query import DatabaseValue_s
from cdedb.models.common import CdEDataclass, CdEDataclassMap, MetaFlag as Meta


@dataclasses.dataclass(kw_only=True)
class Case(CdEDataclass):
    database_table = "complaint.cases"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    kind: const.ComplaintKind
    is_grave: bool = False
    summary: str
    notes: str | None = None

    start_date: datetime.date | None = None
    end_date: datetime.date | None = None

    entries: CdEDataclassMap["ComplaintEntry"]
    involved: dict[const.ComplaintInvolvementType, set[int]] = dataclasses.field(
        metadata=Meta.exclude.as_dict,
    )
    informed_involved: set[int] = dataclasses.field(metadata=Meta.exclude.as_dict)

    @functools.cached_property
    def all_involved(self) -> dict[int, const.ComplaintInvolvementType]:
        return {
            persona_id: involved_type
            for involved_type, involved in self.involved.items()
            for persona_id in involved
        }

    @functools.cached_property
    def all_properly_involved(self) -> dict[int, const.ComplaintInvolvementType]:
        """This ignores the withheld type."""
        return {
            persona_id: involved_type
            for involved_type, involved in self.involved.items()
            if involved_type != const.ComplaintInvolvementType.withheld
            for persona_id in involved
        }

    # Companions to set of involved personas they accompany
    companions: dict[int, set[int]] = dataclasses.field(
        metadata=Meta.exclude.as_dict,
    )

    @functools.cached_property
    def companions_by_involved(self) -> dict[int, set[int]]:
        ret: dict[int, set[int]] = {}
        for companion, accompanied in self.companions.items():
            for persona_id in accompanied:
                ret.setdefault(persona_id, set()).add(companion)
        return ret

    @functools.cached_property
    def companions_by_involved_type(
        self,
    ) -> dict[const.ComplaintInvolvementType, set[int]]:
        ret: dict[const.ComplaintInvolvementType, set[int]] = {}
        for involvement_type, involved_personas in self.involved.items():
            for persona_id in involved_personas:
                companions = self.companions_by_involved.get(persona_id, set())
                ret.setdefault(involvement_type, set()).update(companions)
        return ret

    withdrawn_companions: dict[int, set[int]] = dataclasses.field(
        metadata=Meta.exclude.as_dict,
    )

    @functools.cached_property
    def withdrawn_companions_by_involved(self) -> dict[int, set[int]]:
        ret: dict[int, set[int]] = {}
        for companion, accompanied in self.withdrawn_companions.items():
            for persona_id in accompanied:
                ret.setdefault(persona_id, set()).add(companion)
        return ret

    @functools.cached_property
    def active_companions(self) -> dict[int, set[int]]:
        ret: dict[int, set[int]] = {}
        for companion, accompanied in self.companions.items():
            withdrawn = self.withdrawn_companions.get(companion, set())
            if active_accompanied := (accompanied - withdrawn):
                ret[companion] = active_accompanied
        return ret

    def adverse_companions(
        self, involved_type: const.ComplaintInvolvementType
    ) -> set[int]:
        return set(
            chain.from_iterable(
                self.companions_by_involved_type.get(type_, set())
                for type_ in involved_type.adverse()
            )
        )

    def is_strongly_related(self, case: Self) -> bool:
        """Return whether another case features involved people who are adverse here.

        Beware that his is not symmetric."""
        it = const.ComplaintInvolvementType
        return bool(
            case.all_properly_involved.keys() & self.involved.get(it.target, set())
        ) and bool(
            case.all_properly_involved.keys()
            & (
                self.involved.get(it.affected, set())
                | self.involved.get(it.appellant, set())
            )
        )

    def is_visible_for(self, user: User) -> bool:
        """Whether a user can see a case in principle.

        For now, assumes the user is at least complaint admin."""
        return user.persona_id not in self.all_involved

    def get_persona_ids(self, log_entries: tuple[CdEDBObject, ...]) -> set[int]:
        ret: set[int] = set(self.all_involved)
        ret.update(self.companions)
        if log_entries:
            ret.update(e['submitted_by'] for e in log_entries if e['submitted_by'])
            ret.update(e['persona_id'] for e in log_entries if e['persona_id'])
            ret.update(e['companion_id'] for e in log_entries if e['companion_id'])
        for entry in self.entries.values():
            if entry.concerned_id:
                ret.add(entry.concerned_id)
            ret.update(version.submitted_by for version in entry.all_versions)
            ret.update(
                itertools.chain.from_iterable(
                    version.authors for version in entry.all_versions
                )
            )
        return ret

    @property
    def is_active(self) -> bool:
        return not any(
            entry.entry_type == const.ComplaintEntryType.synthesis
            and entry.active_version
            and not entry.is_revoked
            for entry in self.entries.values()
        )

    @property
    def is_confirmed(self) -> bool:
        return any(
            entry.entry_type == const.ComplaintEntryType.statement_signed
            and entry.active_version
            and not entry.is_revoked
            for entry in self.entries.values()
        )

    def list_entries(
        self, log_entries: tuple[CdEDBObject, ...], include_deleted: bool = False
    ) -> list[Union[CdEDBObject, "ComplaintEntry"]]:
        mutable_entries = [
            e for e in self.entries.values() if e.active_version or include_deleted
        ]
        all_entries = list(log_entries) + mutable_entries
        all_entries = xsorted(
            all_entries,
            key=lambda e: (
                e.get_sortkey() if isinstance(e, ComplaintEntry) else (e['ctime'],)
            ),
        )
        return all_entries

    def get_sortkey(self) -> Sortkey:
        today = now().date()
        return (
            self.end_date or today,
            self.start_date or today,
            self.kind,
            not self.is_grave,
            self.summary,
        )

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["informed_involved"] = set()
        new_involved: dict[const.ComplaintInvolvementType, set[int]] = {}
        for involved in data["involved"]:
            involved_type = const.ComplaintInvolvementType(involved[1])
            if involved_type not in new_involved:
                new_involved[involved_type] = set()
            new_involved[involved_type].add(involved[0])
            if involved[2]:
                data["informed_involved"].add(involved[0])
        data["involved"] = dict(sorted(new_involved.items()))

        new_companions: dict[int, set[int]] = {}
        withdrawn_companions: dict[int, set[int]] = {}
        for companion in data["companions"]:
            new_companions.setdefault(companion[1], set()).add(companion[0])
            if companion[2]:
                withdrawn_companions.setdefault(companion[1], set()).add(companion[0])
        data["companions"] = new_companions
        data["withdrawn_companions"] = withdrawn_companions

        data["entries"] = ComplaintEntry.many_from_database(data["entries"])
        ret = super().from_database(data)
        for entry in data["entries"].values():
            entry.case = ret
        return ret

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT
                {", ".join(cls.database_fields())},
                array(
                    SELECT
                        ARRAY[
                            involved.persona_id,
                            involved.involved_type,
                            involved.is_informed::int
                        ]
                    FROM {ComplaintInvolved.database_table} AS involved
                    WHERE involved.case_id = cases.id
                ) AS involved,
                array(
                    SELECT
                        ARRAY[
                            companion.involved_persona_id,
                            companion.companion_persona_id,
                            companion.is_withdrawn::int
                        ]
                    FROM {ComplaintCompanion.database_table} AS companion
                    WHERE companion.case_id = cases.id
                ) as companions
            FROM
                {cls.database_table} AS cases
            WHERE {entity_key or cls.entity_key} = ANY(%s)
        """
        return query, (entities,)


@dataclasses.dataclass(kw_only=True)
class ComplaintEntry(CdEDataclass):
    database_table = "complaint.entries"
    entity_key = "case_id"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    case: Case = dataclasses.field(init=False, compare=False, repr=False)
    case_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)
    entry_type: const.ComplaintEntryType

    parent_id: vtypes.ID | None = None

    concerned_id: vtypes.CdedbID | None = None

    is_revoked: bool = dataclasses.field(
        default=False,
        metadata=Meta.input_exclude.as_dict,
    )

    all_versions: list["ComplaintEntryVersion"] = dataclasses.field(
        metadata=(Meta.validate_exclude | Meta.database_exclude).as_dict,
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
        if self.parent_id is None:
            return None
        return self.case.entries[self.parent_id]

    @functools.cached_property
    def children(self) -> list["ComplaintEntry"]:
        return [
            entry for entry in self.case.entries.values() if entry.parent_id == self.id
        ]

    @functools.cached_property
    def active_children(self) -> list["ComplaintEntry"]:
        return [entry for entry in self.children if entry.active_version]

    def get_sortkey(self) -> Sortkey:
        return (self.all_versions[-1].timestamp,)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["all_versions"] = list(
            ComplaintEntryVersion.many_from_database(data["all_versions"]).values()
        )
        return super().from_database(data)

    @classmethod
    def mandatory_form_fields(cls, *, creation: bool) -> set[str]:
        # This includes field which must be set for each version.
        ret = {'entry_type', 'concerned_id', 'authors', 'description', 'timestamp'}
        if not creation:
            ret.add('dreason')
        return ret


@dataclasses.dataclass(kw_only=True)
class ComplaintEntryVersion(CdEDataclass):
    database_table = "complaint.entry_versions"
    entity_key = "entry_id"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    entry_id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    description: str | None = dataclasses.field(
        init=False,
        default=None,
        metadata=Meta.database_exclude.as_dict,
    )
    length: int | None = dataclasses.field(
        default=None,
        metadata=Meta.input_exclude.as_dict,
    )
    timestamp: datetime.datetime
    etime: datetime.datetime | None = None

    attachment_title: str | None = None
    attachment_filehash: str | None = None
    attachment_filename: str | None = None

    ctime: datetime.datetime = dataclasses.field(metadata=Meta.input_exclude.as_dict)
    submitted_by: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    dtime: datetime.datetime | None = dataclasses.field(
        default=None,
        metadata=Meta.input_exclude.as_dict,
    )
    deleted_by: vtypes.ID | None = dataclasses.field(
        default=None,
        metadata=Meta.input_exclude.as_dict,
    )
    dreason: str | None = dataclasses.field(
        default=None,
        metadata=Meta.input_exclude.as_dict,
    )

    authors: vtypes.CdedbIDList = dataclasses.field(
        metadata=Meta.database_exclude.as_dict,
    )

    @staticmethod
    def encrypt(data: str | bytes, key: bytes) -> bytes:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return Fernet(key).encrypt(data)

    @staticmethod
    def decrypt(data: bytes, key: bytes) -> bytes:
        return Fernet(key).decrypt(data)

    def get_sortkey(self) -> Sortkey:
        return (self.entry_id, self.ctime)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["authors"] = set(data["authors"])
        return super().from_database(data)

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT
                {', '.join(cls.database_fields())},
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


class AccessLog:
    database_table = "complaint.access_log"


class ComplaintAuthors:
    database_table = "complaint.authors"
    entity_key = "entry_version_id"


class ComplaintInvolved:
    database_table = "complaint.involved"
    entity_key = "case_id"


class ComplaintCompanion:
    database_table = "complaint.companions"
