#!/usr/bin/env python3
import datetime
from collections.abc import Collection
from typing import Any, Optional, Protocol, cast

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.backend.common import (
    AbstractBackend,
    Silencer,
    access,
    affirm_dataclass,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    affirm_validation_optional as affirm_optional,
    singularize,
)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    RequestState,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryScope
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.database.query import DatabaseValue_s

DATE_FORMAT = "%d.%m.%Y"


def _format_date_change_note(
    current_date: datetime.date | None, new_date: datetime.date | None
) -> str:
    if current_date and new_date:
        msg = (
            f"{current_date.strftime(DATE_FORMAT)} -> {new_date.strftime(DATE_FORMAT)}"
        )
    elif current_date:
        msg = f"Entfernt ({current_date.strftime(DATE_FORMAT)})"
    elif new_date:
        msg = f"Hinzugefügt ({new_date.strftime(DATE_FORMAT)})"
    else:
        return ""
    return msg


class ComplaintBackend(AbstractBackend):
    realm = "complaint"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        # Temporary for now
        return "core_admin" in rs.user.roles
        # return super().is_admin(rs)

    def complaint_log(
        self,
        *,
        rs: RequestState,
        code: const.ComplaintLogCodes,
        case_id: Optional[int],
        persona_id: Optional[int] = None,
        change_note: Optional[str] = None,
    ) -> int:
        """Make an entry in the log for complaint cases."""
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "case_id": case_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "complaint.log", data)

    @access("core_admin")
    def retrieve_log(
        self,
        rs: RequestState,
        log_filter: ComplaintLogFilter,
    ) -> CdEDBLog:
        """Retrieve log entries related to complaint cases.

        The full history of a case consists of both log entries and complaint entries.
        """
        log_filter = affirm_dataclass(ComplaintLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @access("core_admin")
    def get_cases(
        self, rs: RequestState, case_ids: Collection[int]
    ) -> models.CdEDataclassMap[models.Case]:
        """Retrieve metadata and a list of complaint entries for some complaint cases."""
        case_ids = affirm_set(vtypes.ID, case_ids)
        with Atomizer(rs):
            case_data = self.query_all(rs, *models.Case.get_select_query(case_ids))
            if not case_data:
                return {}
            all_cases = {e['id']: e for e in case_data}
            entry_data = self.query_all(
                rs, *models.ComplaintEntry.get_select_query(case_ids)
            )
            all_entries = {e['id']: e for e in entry_data}
            version_data = self.query_all(
                rs, *models.ComplaintEntryVersion.get_select_query(all_entries.keys())
            )

            for case in case_data:
                case["entries"] = []
            for entry in entry_data:
                entry["all_versions"] = []
                all_cases[entry["case_id"]]["entries"].append(entry)
            for entry_version in version_data:
                all_entries[entry_version["entry_id"]]["all_versions"].append(
                    entry_version
                )

            return models.Case.many_from_database(case_data)

    class _GetCaseProtocol(Protocol):
        def __call__(self, rs: RequestState, case_id: int) -> CdEDBObject: ...

    get_case = singularize(get_cases, 'case_ids', 'case_id')

    @access("core_admin")
    def set_case(
        self, rs: RequestState, case_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Alter metadata of a complaint case."""
        case_id = affirm(vtypes.ID, case_id)
        data = cast(CdEDBObject, affirm(models.Case, data))

        with Atomizer(rs):
            current = self.get_case(rs, case_id)
            data['id'] = case_id
            ret = self.sql_update(rs, models.Case.database_table, data)

            log_entries = []
            if "kind" in data and (new_kind := data["kind"]) != current.kind:
                msg = (
                    f"{rs.log_gettext(str(current.kind))!r}"
                    f" -> {rs.log_gettext(str(new_kind))!r}"
                )
                code = const.ComplaintLogCodes.case_changed_kind
                log_entries.append((msg, code))
            if (
                "is_grave" in data
                and (new_is_grave := data["is_grave"]) != current.is_grave
            ):
                if new_is_grave:
                    msg = "Ist jetzt schwerwiegend."
                else:
                    msg = "Ist nicht mehr schwerwiegend."
                code = const.ComplaintLogCodes.case_changed_grave
                log_entries.append((msg, code))
            if (
                "summary" in data
                and (new_summary := data["summary"]) != current.summary
            ):
                msg = f"{current.summary} -> {new_summary}"
                code = const.ComplaintLogCodes.case_changed_summary
                log_entries.append((msg, code))
            if (
                "start_date" in data
                and (new_start_date := data["start_date"]) != current.start_date
            ):
                msg = _format_date_change_note(current.start_date, new_start_date)
                code = const.ComplaintLogCodes.case_changed_start_date
                log_entries.append((msg, code))
            if (
                "end_date" in data
                and (new_end_date := data["end_date"]) != current.end_date
            ):
                code = const.ComplaintLogCodes.case_changed_end_date
                msg = _format_date_change_note(current.end_date, new_end_date)
                log_entries.append((msg, code))
            for msg, code in log_entries:
                self.complaint_log(rs=rs, code=code, case_id=case_id, change_note=msg)

            return ret

    @access("core_admin")
    def create_case(self, rs: RequestState, data: CdEDBObject) -> models.Case:
        """Create a new complaint case. Only includes the metadata and not entries."""
        data = cast(CdEDBObject, affirm(models.Case, data, creation=True))

        with Atomizer(rs):
            new_id = self.sql_insert(rs, models.Case.database_table, data)
            new_case = models.Case(id=cast(vtypes.ID, new_id), **data, entries={})
            self.complaint_log(
                rs=rs, code=const.ComplaintLogCodes.case_created, case_id=new_id
            )
        return new_case

    def _insert_entry_version(
        self, rs: RequestState, entry_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Process data for a new entry version and insert it."""
        self.affirm_atomized_context(rs)
        if data.get("description"):
            data["length"] = len(data["description"])
        else:
            data["length"] = None
        authors = data.pop("authors")
        if not authors:
            raise ValueError(n_("No authors specified."))
        if not self.core.verify_ids(rs, authors):
            raise ValueError(n_("Unknown authors."))
        data.update(
            entry_id=entry_id,
            submitted_by=rs.user.persona_id,
        )
        new_version_id = self.sql_insert(
            rs, models.ComplaintEntryVersion.database_table, data
        )
        self.sql_insert_many(
            rs,
            "complaint.authors",
            [
                {'entry_version_id': new_version_id, 'persona_id': persona_id}
                for persona_id in authors
            ],
        )
        return new_version_id

    @access("core_admin")
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_data: CdEDBObject,
        version_data: CdEDBObject,
    ) -> DefaultReturnCode:
        """Add a new entry to an existing complaint case."""
        case_id = affirm(vtypes.ID, case_id)
        entry_data = cast(
            CdEDBObject, affirm(models.ComplaintEntry, entry_data, creation=True)
        )
        version_data = cast(
            CdEDBObject,
            affirm(models.ComplaintEntryVersion, version_data, creation=True),
        )

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if root_entry_id := entry_data.get("root_entry_id"):
                if root_entry_id not in case.entries:
                    raise KeyError(n_("Unknown root entry for this case."))
            entry_data["case_id"] = case_id
            new_entry_id = self.sql_insert(
                rs, models.ComplaintEntry.database_table, entry_data
            )
            self._insert_entry_version(rs, new_entry_id, version_data)
        return new_entry_id

    @access("core_admin")
    def replace_entry_version(
        self,
        rs: RequestState,
        entry_id: int,
        data: CdEDBObject,
        dreason: str | None,
    ) -> DefaultReturnCode:
        """Add a new version of an existing complaint entry."""
        entry_id = affirm(vtypes.ID, entry_id)
        data = cast(
            CdEDBObject, affirm(models.ComplaintEntryVersion, data, creation=True)
        )
        dreason = affirm_optional(str, dreason)

        with Atomizer(rs):
            case_data = self.sql_select_one(
                rs, models.ComplaintEntry.database_table, ["case_id"], entry_id
            )
            if not case_data:
                raise KeyError(n_("Unknown entry."))
            case = self.get_case(rs, case_data["case_id"])
            entry = case.entries[entry_id]
            if bool(entry.active_version) != bool(dreason):
                raise ValueError(
                    n_("Deletion reason given, but entry has no active version.")
                )
            if dreason and entry.active_version:
                update = {
                    'id': entry.active_version.id,
                    'dreason': dreason,
                    'dtime': "now()",
                    'deleted_by': rs.user.persona_id,
                }
                self.sql_update(rs, models.ComplaintEntryVersion.database_table, update)
            return self._insert_entry_version(rs, entry_id, data)

    @access("core_admin")
    def get_visible_descriptions(
        self, rs: RequestState, case_id: int
    ) -> dict[int, str]:
        """List all descriptions that are visible without unlock.

        :returns: Mapping of entry *version* ids to descriptions..
        """
        case_id = affirm(int, case_id)
        query = """
            SELECT ev.id, ev.description
            FROM complaint.entry_versions AS ev
                LEFT JOIN complaint.entries AS e on ev.entry_id = e.id
            WHERE e.case_id = %s AND e.entry_type = ANY(%s)
        """
        params: list[DatabaseValue_s] = [
            case_id,
            const.ComplaintEntryType.visible_types(),
        ]
        # TODO Add encryption in database and decryption here.
        return {e['id']: e['description'] for e in self.query_all(rs, query, params)}
