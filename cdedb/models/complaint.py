"""Dataclass definitions for the complaint realm."""

import dataclasses
import datetime
import enum
import functools
import itertools
from collections.abc import Collection
from itertools import chain
from typing import Self, Union

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, User, now
from cdedb.common.n_ import n_
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.database.query import DatabaseValue_s
from cdedb.models.common import CdEDataclass, CdEDataclassMap, MetaFlag as Meta


class ComplaintEntryStatus(enum.Enum):
    deleted = enum.auto()
    # TODO: purged
    revoked = enum.auto()
    pending_measure = enum.auto()
    active_measure = enum.auto()
    expired_measure = enum.auto()
    other = enum.auto()

    def get_label(self) -> str:
        if self == self.deleted:
            return n_("deleted")
        if self == self.revoked:
            return n_("revoked")
        if self == self.expired_measure:
            return n_("expired")
        if self == self.pending_measure:
            return n_("not yet active")
        return ""

    def heading_styles(self) -> str:
        ret = []
        if self in {
            self.deleted,
            self.expired_measure,
            self.revoked,
        }:
            ret.append("strikethrough")
        if self == self.pending_measure:
            ret.extend(["text-muted", "text-italic"])
        return " ".join(ret)

    def label_styles(self) -> str:
        ret = []
        if self in {
            self.deleted,
            self.expired_measure,
            self.revoked,
        }:
            ret.append("text-unmuted")
        if self == self.pending_measure:
            ret.append("text-info")
        return " ".join(ret)

    def timespan_styles(self) -> str:
        ret = []
        if self == self.pending_measure:
            ret.extend(["text-info", "text-italic"])
        return " ".join(ret)

    def list_group_item_styles(self) -> str:
        ret = []
        if self in {
            self.deleted,
            self.revoked,
            self.expired_measure,
        }:
            ret.append("list-group-item-muted")
        return " ".join(ret)


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

    entries: CdEDataclassMap["ComplaintEntry"] = dataclasses.field(
        metadata=Meta.asdict_include.as_dict
    )
    involved: CdEDataclassMap["ComplaintInvolved"] = dataclasses.field(
        metadata=Meta.exclude.as_dict,
    )

    @functools.cached_property
    def properly_involved(self) -> dict[int, "ComplaintInvolved"]:
        """This ignores the withheld type."""
        return {
            involved_id: involved
            for involved_id, involved in self.involved.items()
            if involved.type_ != const.ComplaintInvolvementType.withheld
        }

    @functools.cached_property
    def involved_persona_ids(self) -> set[int]:
        return {
            involved.persona_id
            for involved in self.involved.values()
            if involved.persona_id is not None
        }

    @functools.cached_property
    def properly_involved_persona_ids(self) -> set[int]:
        return {
            involved.persona_id
            for involved in self.properly_involved.values()
            if involved.persona_id is not None
        }

    @functools.cached_property
    def involved_by_type(self) -> dict[const.ComplaintInvolvementType, list[int]]:
        # TODO: return involved class instead.
        ret = {it: [] for it in const.ComplaintInvolvementType}
        for involved in self.involved.values():
            ret[involved.type_].append(involved.id)
        return ret

    @functools.cached_property
    def involved_by_persona_id(self) -> CdEDataclassMap["ComplaintInvolved"]:
        return {
            involved.persona_id: involved
            for involved in self.involved.values()
            if involved.persona_id
        }

    def involved_persona_ids_by_type(
        self, it: const.ComplaintInvolvementType
    ) -> set[int]:
        return {
            involved.persona_id
            for involved in self.involved.values()
            if involved.persona_id is not None and involved.type_ == it
        }

    def companions(self, is_active: bool | None) -> dict[int, set[int]]:
        """Maps all companions to a set of involved_ids."""
        ret: dict[int, set[int]] = {}
        for involved_id, involved in self.involved.items():
            for companion_id in involved.companions(is_active):
                ret.setdefault(companion_id, set()).add(involved_id)
        return ret

    def companions_by_involved_type(
        self, is_active: bool | None
    ) -> dict[const.ComplaintInvolvementType, set[int]]:
        ret: dict[const.ComplaintInvolvementType, set[int]] = {}
        for involved_id, involved in self.involved.items():
            ret.setdefault(involved.type_, set()).update(involved.companions(is_active))
        return ret

    def adverse_companions(
        self, involved_type: const.ComplaintInvolvementType
    ) -> set[int]:
        return set(
            chain.from_iterable(
                self.companions_by_involved_type(is_active=True).get(type_, set())
                for type_ in involved_type.adverse()
            )
        )

    def is_strongly_related(self, case: Self) -> bool:
        """Return whether another case features involved people who are adverse here.

        Beware that his is not symmetric."""
        it = const.ComplaintInvolvementType
        return bool(
            case.properly_involved_persona_ids
            & self.involved_persona_ids_by_type(it.target)
        ) and bool(
            case.properly_involved_persona_ids
            & (
                self.involved_persona_ids_by_type(it.affected)
                | self.involved_persona_ids_by_type(it.appellant)
            )
        )

    def is_visible_for(self, user: User) -> bool:
        """Whether a user can see a case in principle.

        For now, assumes the user is at least complaint admin."""
        return user.persona_id not in self.involved_persona_ids

    def get_persona_ids(self, log_entries: tuple[CdEDBObject, ...]) -> set[int]:
        ret: set[int] = set(self.involved_persona_ids)
        ret.update(self.companions(is_active=None).keys())
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
        # TODO Fix companions
        data["involved"] = {
            involved_datum[0]: ComplaintInvolved(
                id=involved_datum[0],
                persona_id=involved_datum[1],
                type_=const.ComplaintInvolvementType(involved_datum[2]),
                is_informed=bool(involved_datum[3]),
                _companions={},
            )
            for involved_datum in data["involved"]
        }

        for companion in data.pop("companions"):
            data["involved"][companion[0]]._companions[companion[1]] = not companion[2]

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
                            involved.id,
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
                            companion.involved_id,
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

    _now: datetime.datetime = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        default_factory=now,
        metadata=(Meta.exclude | Meta.asdict_exclude).as_dict,
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

    @functools.cached_property
    def versions_by_id(self) -> CdEDataclassMap["ComplaintEntryVersion"]:
        return {version.id: version for version in self.all_versions}

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
        return (
            self.all_versions[-1].timestamp
            or datetime.datetime.max.replace(tzinfo=datetime.UTC),
        )

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["all_versions"] = list(
            ComplaintEntryVersion.many_from_database(data["all_versions"]).values()
        )
        ret = super().from_database(data)
        for version in data["all_versions"]:
            version.entry = ret
        return ret

    @classmethod
    def mandatory_form_fields(cls, *, creation: bool) -> set[str]:
        # This includes field which must be set for each version.
        ret = {'entry_type', 'concerned_id', 'authors', 'description', 'timestamp'}
        if not creation:
            ret.add('dreason')
        return ret

    @property
    def is_measure(self) -> bool:
        return self.entry_type.is_measure

    @property
    def is_provisional(self) -> bool:
        return self.entry_type.is_provisional

    @functools.cached_property
    def is_active_measure(self) -> bool:
        av = self.active_version
        if self.is_revoked or not self.is_measure or not av or not av.timestamp:
            # Only purged versions do not have a timestamp.
            #  This tells mypy that the timestamp cannot be None below.
            return False
        return self._now > av.timestamp and not self.is_expired_measure

    @functools.cached_property
    def is_expired_measure(self) -> bool:
        av = self.active_version
        if self.is_revoked or not self.is_measure or not av or not av.timestamp:
            # Only purged versions do not have a timestamp.
            #  This tells mypy that the timestamp cannot be None below.
            return False
        return bool(av.etime and self._now > av.etime)

    @functools.cached_property
    def status(self) -> ComplaintEntryStatus:
        if self.is_revoked:
            return ComplaintEntryStatus.revoked
        if not self.active_version:
            return ComplaintEntryStatus.deleted
        if not self.is_measure:
            return ComplaintEntryStatus.other
        if self.is_expired_measure:
            return ComplaintEntryStatus.expired_measure
        if self.is_active_measure:
            return ComplaintEntryStatus.active_measure
        return ComplaintEntryStatus.pending_measure


@dataclasses.dataclass(kw_only=True)
class ComplaintEntryVersion(CdEDataclass):
    database_table = "complaint.entry_versions"
    entity_key = "entry_id"

    id: vtypes.ID = dataclasses.field(metadata=Meta.input_exclude.as_dict)

    entry: ComplaintEntry = dataclasses.field(init=False, compare=False, repr=False)
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
    timestamp: datetime.datetime | None
    etime: datetime.datetime | None = None

    # filehas and filename are retrieved from the request manually to feed to the
    #  attachment store.
    attachment_title: str | None = None
    attachment_hash: str | None = dataclasses.field(
        default=None, metadata=Meta.request_exclude.as_dict
    )
    attachment_filename: str | None = dataclasses.field(
        default=None, metadata=Meta.request_exclude.as_dict
    )

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

    marked_for_purge: datetime.datetime | None = dataclasses.field(
        default=None, metadata=Meta.input_exclude.as_dict
    )
    purged_by: vtypes.ID | None = dataclasses.field(
        default=None, metadata=Meta.input_exclude.as_dict
    )
    is_purged: bool = dataclasses.field(
        default=False, metadata=Meta.input_exclude.as_dict
    )

    authors: vtypes.CdedbIDList = dataclasses.field(
        metadata=Meta.database_exclude.as_dict,
    )

    def get_sortkey(self) -> Sortkey:
        return (self.entry_id, self.ctime)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        data["authors"] = set(data["authors"])
        if data["attachment_hash"]:
            data["attachment_hash"] = f"REDACTED:{data['attachment_hash'][:12]}"
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


@dataclasses.dataclass()
class ComplaintInvolved:
    database_table = "complaint.involved"
    entity_key = "case_id"

    id: int
    persona_id: int | None
    type_: const.ComplaintInvolvementType
    is_informed: bool
    _companions: dict[int, bool]

    def companions(self, is_active: bool | None) -> set[int]:
        if is_active is None:
            return set(self._companions.keys())
        else:
            return {
                companion
                for companion, is_active_ in self._companions.items()
                if is_active == is_active_
            }


class ComplaintCompanion:
    database_table = "complaint.companions"
