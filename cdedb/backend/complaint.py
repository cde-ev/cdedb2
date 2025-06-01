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
from cdedb.common.sorting import mixed_existence_sorter, xsorted
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
        return super().is_admin(rs)

    def complaint_log(
        self,
        *,
        rs: RequestState,
        code: const.ComplaintLogCodes,
        case_id: int | None,
        persona_id: int | None = None,
        companion_id: int | None = None,
        change_note: str | None = None,
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
            "companion_id": companion_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "complaint.log", data)

    @access("complaint_admin")
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

    @access("complaint_admin")
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

    @access("complaint_admin")
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

    @access("complaint_admin")
    def create_case(self, rs: RequestState, data: CdEDBObject) -> models.Case:
        """Create a new complaint case. Only includes the metadata and not entries."""
        data = cast(CdEDBObject, affirm(models.Case, data, creation=True))

        with Atomizer(rs):
            new_id = self.sql_insert(rs, models.Case.database_table, data)
            new_case = models.Case(
                id=cast(vtypes.ID, new_id),
                **data,
                entries={},
                involved={},
                informed_involved=set(),
                companions={},
                withdrawn_companions={},
            )
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

    def _delete_entry(
        self, rs: RequestState, entry_id: int, dreason: str | None
    ) -> DefaultReturnCode:
        """Process the deletion of the active version of an existing entry.

        :returns: 1 if the entry had an active version that was "deleted". 0 otherwise.
        """
        self.affirm_atomized_context(rs)
        case_id = self._get_case_id(rs, entry_id)
        case = self.get_case(rs, case_id)
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
            return self.sql_update(
                rs, models.ComplaintEntryVersion.database_table, update
            )
        return 0

    def _get_case_id(self, rs: RequestState, entry_id: int) -> int:
        case_data = self.sql_select_one(
            rs, models.ComplaintEntry.database_table, ["case_id"], entry_id
        )
        if not case_data:
            raise KeyError(n_("Unknown entry."))
        return case_data["case_id"]

    @access("complaint_admin")
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_data: CdEDBObject,
        version_data: CdEDBObject,
    ) -> DefaultReturnCode:
        """Add a new entry to an existing complaint case."""
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            case = self.get_case(rs, case_id)

            entry_data = cast(
                CdEDBObject,
                affirm(
                    models.ComplaintEntry,
                    entry_data,
                    creation=True,
                    passthrough=True,
                    entries=case.entries,
                ),
            )
            version_data = cast(
                CdEDBObject,
                affirm(
                    models.ComplaintEntryVersion,
                    version_data,
                    creation=True,
                    passthrough=True,
                    entry_type=entry_data['entry_type'],
                ),
            )

            entry_data["case_id"] = case_id
            new_entry_id = self.sql_insert(
                rs, models.ComplaintEntry.database_table, entry_data
            )
            self._insert_entry_version(rs, new_entry_id, version_data)
        return new_entry_id

    @access("complaint_admin")
    def replace_entry_version(
        self,
        rs: RequestState,
        entry_id: int,
        data: CdEDBObject,
        dreason: str | None,
    ) -> DefaultReturnCode:
        """Add a new version of an existing complaint entry."""
        entry_id = affirm(vtypes.ID, entry_id)
        entry = self.get_case(rs, self._get_case_id(rs, entry_id)).entries[entry_id]
        data = cast(
            CdEDBObject,
            affirm(
                models.ComplaintEntryVersion,
                data,
                creation=False,
                passthrough=True,
                entry_type=entry.entry_type,
            ),
        )
        dreason = affirm_optional(str, dreason)

        with Atomizer(rs):
            self._delete_entry(rs, entry_id=entry_id, dreason=dreason)
            return self._insert_entry_version(rs, entry_id=entry_id, data=data)

    @access("complaint_admin")
    def delete_entry(
        self, rs: RequestState, entry_id: int, dreason: str | None
    ) -> DefaultReturnCode:
        """Delete an existing entry version."""
        entry_id = affirm(vtypes.ID, entry_id)
        dreason = affirm_optional(str, dreason)
        with Atomizer(rs):
            return self._delete_entry(rs, entry_id=entry_id, dreason=dreason)

    @access("complaint_admin")
    def revoke_entry(
        self, rs: RequestState, entry_id: int, version_data: CdEDBObject
    ) -> DefaultReturnCode:
        """Revoke an existing entry. If that entry is a revocation, unrevoke the parent."""
        entry_id = affirm(vtypes.ID, entry_id)

        revocation_type = const.ComplaintEntryType.revocation_explanation

        version_data = cast(
            CdEDBObject,
            affirm(
                models.ComplaintEntryVersion,
                version_data,
                creation=True,
                passthrough=True,
                entry_type=revocation_type,
            ),
        )
        with Atomizer(rs):
            code = self.sql_update(
                rs,
                models.ComplaintEntry.database_table,
                {'id': entry_id, 'is_revoked': True},
            )
            if not code:
                raise RuntimeError

            case_id = self._get_case_id(rs, entry_id)
            case = self.get_case(rs, case_id)
            entry = case.entries[entry_id]

            if entry.entry_type == revocation_type:
                if entry.parent and entry.parent.is_revoked:
                    code = self.sql_update(
                        rs,
                        models.ComplaintEntry.database_table,
                        {'id': entry.parent_id, 'is_revoked': False},
                    )
                    if not code:
                        raise RuntimeError

            new_entry = {
                'entry_type': revocation_type,
                'parent_id': entry_id,
                'concerned_id': None,
            }
            return self.add_entry(rs, case_id, new_entry, version_data)

    @access("complaint_admin")
    def add_involved(
        self,
        rs: RequestState,
        case_id: int,
        involved_type: const.ComplaintInvolvementType,
        persona_ids: Collection[int],
        is_informed: bool | None = None,
    ) -> DefaultReturnCode:
        """Add the given personas as involved people of the given type to a case.

        :returns:
            0 if no persona ids were given or if something went wrong.
            -1 if no one was added (because they were already involved).
            The number of newly added personas otherwise.
        """
        case_id = affirm(vtypes.ID, case_id)
        involved_type = affirm(const.ComplaintInvolvementType, involved_type)
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        is_informed = affirm_optional(bool, is_informed)

        if not persona_ids:
            return 0

        if involved_type == const.ComplaintInvolvementType.appellant:
            if is_informed is False:
                raise ValueError(n_("Appellant cannot be uninformed."))
            is_informed = True
        elif is_informed is None:
            is_informed = False

        with Atomizer(rs):
            if not self.core.verify_ids(rs, persona_ids):
                raise ValueError(n_("Unknown users."))

            case = self.get_case(rs, case_id)

            if any(
                persona_ids & involved
                for inv_type, involved in case.involved.items()
                if inv_type != involved_type
            ):
                raise ValueError(n_("Already involved otherwise."))
            if persona_ids & case.active_companions.keys():
                raise ValueError(n_("Already active companions."))

            newly_involved = persona_ids - case.involved.get(involved_type, set())
            if not newly_involved:
                return -1
            ret = self.sql_insert_many(
                rs,
                models.ComplaintInvolved.database_table,
                [
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "involved_type": involved_type,
                        "is_informed": is_informed,
                    }
                    for persona_id in newly_involved
                ],
            )
            for persona_id in mixed_existence_sorter(newly_involved):
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.involved_added,
                    case_id=case_id,
                    persona_id=persona_id,
                    change_note=rs.log_gettext(str(involved_type)),
                )
                if is_informed:
                    ret *= self.complaint_log(
                        rs=rs,
                        code=const.ComplaintLogCodes.involved_informed,
                        case_id=case_id,
                        persona_id=persona_id,
                    )
        return ret

    @access("complaint_admin")
    def remove_involved(
        self,
        rs: RequestState,
        case_id: int,
        persona_ids: Collection[int],
    ) -> DefaultReturnCode:
        """Remove some users as involved with a case.

        :returns:
            0 if no persona ids were given or if something went wrong.
            -1 if no one was removed (because they weren't involved).
            The number of removed personas otherwise.
        """
        case_id = affirm(vtypes.ID, case_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        if not persona_ids:
            return 0

        with Atomizer(rs):
            if not self.core.verify_ids(rs, persona_ids):
                raise ValueError(n_("Unknown users."))

            case = self.get_case(rs, case_id)
            removed = persona_ids & case.all_involved.keys()
            if not removed:
                return -1
            query = f"""
                DELETE FROM {models.ComplaintInvolved.database_table}
                WHERE case_id = %(case_id)s AND persona_id = ANY(%(persona_ids)s)
            """
            ret = self.query_exec(
                rs,
                query,
                {
                    "case_id": case_id,
                    "persona_ids": persona_ids,
                },
            )
            for persona_id in mixed_existence_sorter(removed):
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.involved_removed,
                    case_id=case_id,
                    persona_id=persona_id,
                    change_note=rs.log_gettext(str(case.all_involved[persona_id])),
                )
                for companion_id in mixed_existence_sorter(
                    case.companions_by_involved.get(persona_id, set())
                ):
                    ret *= self.complaint_log(
                        rs=rs,
                        code=const.ComplaintLogCodes.companion_removed,
                        case_id=case_id,
                        persona_id=persona_id,
                        companion_id=companion_id,
                    )
        return ret

    @access("complaint_admin")
    def set_involved_informed(
        self, rs: RequestState, case_id: int, persona_id: int, is_informed: bool
    ) -> DefaultReturnCode:
        """Set the informed status of an involved person."""
        case_id = affirm(vtypes.ID, case_id)
        persona_id = affirm(vtypes.ID, persona_id)
        is_informed = affirm(bool, is_informed)

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if persona_id not in case.all_involved:
                raise ValueError(n_("Uninvolved user."))
            if is_informed == (persona_id in case.informed_involved):
                return -1
            query = f"""
                UPDATE {models.ComplaintInvolved.database_table}
                SET is_informed = %(is_informed)s
                WHERE case_id = %(case_id)s AND persona_id = %(persona_id)s
            """
            params = {
                "case_id": case_id,
                "persona_id": persona_id,
                "is_informed": is_informed,
            }
            ret = self.query_exec(rs, query, params)
            if is_informed:
                code = const.ComplaintLogCodes.involved_informed
            else:
                code = const.ComplaintLogCodes.involved_uninformed
            ret *= self.complaint_log(
                rs=rs, code=code, case_id=case_id, persona_id=persona_id
            )
        return ret

    @access("complaint_admin")
    def add_companions(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_ids: Collection[int],
    ) -> DefaultReturnCode:
        """Add companions to a person involved in a case."""
        case_id = affirm(vtypes.ID, case_id)
        persona_id = affirm(vtypes.ID, persona_id)
        companion_ids = affirm_set(vtypes.ID, companion_ids)

        if not companion_ids:
            return 0

        with Atomizer(rs):
            if not self.core.verify_ids(rs, companion_ids):
                raise ValueError(n_("Unknown companions."))

            case = self.get_case(rs, case_id)
            companion_ids -= case.companions_by_involved.get(persona_id, set())
            if not companion_ids:
                return -1

            # Retrieve id of the involvement table.
            query = f"""
                SELECT id, involved_type
                FROM {models.ComplaintInvolved.database_table}
                WHERE case_id = %(case_id)s AND persona_id = %(persona_id)s
            """
            params = {"case_id": case_id, "persona_id": persona_id}
            if not (involved := self.query_one(rs, query, params)):
                raise ValueError(n_("Uninvolved user."))
            involved_id = involved["id"]
            involved_type = const.ComplaintInvolvementType(involved["involved_type"])

            if any(
                companion_ids & case.companions_by_involved_type.get(type_, set())
                for type_ in involved_type.adverse()
            ):
                raise ValueError(n_("Adverse companion."))
            if companion_ids & case.all_involved.keys():
                raise ValueError(n_("Involved companion."))

            values = [
                {
                    "case_id": case_id,
                    "involved_persona_id": persona_id,
                    "involved_id": involved_id,
                    "companion_persona_id": companion_id,
                }
                for companion_id in companion_ids
            ]
            ret = self.sql_insert_many(
                rs, models.ComplaintCompanion.database_table, values
            )
            for companion_id in mixed_existence_sorter(companion_ids):
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.companion_added,
                    case_id=case_id,
                    persona_id=persona_id,
                    companion_id=companion_id,
                )
        return ret

    @access("complaint_admin")
    def remove_companions(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_ids: Collection[int],
    ) -> DefaultReturnCode:
        """Remove companions from a person involved in a case."""
        case_id = affirm(vtypes.ID, case_id)
        persona_id = affirm(vtypes.ID, persona_id)
        companion_ids = affirm_set(vtypes.ID, companion_ids)
        if not companion_ids:
            return 0
        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            companion_ids &= case.companions_by_involved.get(persona_id, set())
            if not companion_ids:
                return -1

            query = f"""
                DELETE FROM {models.ComplaintCompanion.database_table}
                WHERE case_id = %(case_id)s
                    AND involved_persona_id = %(persona_id)s
                    AND companion_persona_id = ANY(%(companion_ids)s)
            """
            params: dict[str, DatabaseValue_s] = {
                "case_id": case_id,
                "persona_id": persona_id,
                "companion_ids": companion_ids,
            }
            ret = self.query_exec(rs, query, params)

            for companion_id in mixed_existence_sorter(companion_ids):
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.companion_removed,
                    case_id=case_id,
                    persona_id=persona_id,
                    companion_id=companion_id,
                )
        return ret

    @access("complaint_admin")
    def set_companion_withdrawn(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_id: int,
        is_withdrawn: bool,
    ) -> DefaultReturnCode:
        """Set the informed status of an involved person."""
        case_id = affirm(vtypes.ID, case_id)
        persona_id = affirm(vtypes.ID, persona_id)
        companion_id = affirm(vtypes.ID, companion_id)
        is_withdrawn = affirm(bool, is_withdrawn)

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if persona_id not in case.all_involved:
                raise ValueError(n_("Uninvolved user."))
            if companion_id not in case.companions_by_involved.get(persona_id, set()):
                raise ValueError(n_("Not a companion."))
            if is_withdrawn == (
                persona_id in case.withdrawn_companions.get(companion_id, set())
            ):
                return -1
            query = f"""
                UPDATE {models.ComplaintCompanion.database_table}
                SET is_withdrawn = %(is_withdrawn)s
                WHERE case_id = %(case_id)s
                    AND involved_persona_id = %(persona_id)s
                    AND companion_persona_id = %(companion_id)s
            """
            params = {
                "case_id": case_id,
                "persona_id": persona_id,
                "companion_id": companion_id,
                "is_withdrawn": is_withdrawn,
            }
            ret = self.query_exec(rs, query, params)
            if is_withdrawn:
                code = const.ComplaintLogCodes.companion_withdrawn
            else:
                code = const.ComplaintLogCodes.companion_reinstated
            ret *= self.complaint_log(
                rs=rs,
                code=code,
                case_id=case_id,
                persona_id=persona_id,
                companion_id=companion_id,
            )
        return ret

    def _get_descriptions(
        self,
        rs: RequestState,
        *,
        case_id: int,
        entry_id: int | None = None,
        visible: bool | None,
        deleted: bool | None = False,
    ) -> dict[int, str]:
        query = f"""
            SELECT versions.id, versions.description
            FROM
                {models.ComplaintEntryVersion.database_table} AS versions
                LEFT JOIN {models.ComplaintEntry.database_table} AS entries
                    ON versions.entry_id = entries.id
            WHERE
                entries.case_id = %(case_id)s
        """
        params: dict[str, DatabaseValue_s] = {
            "case_id": case_id,
        }

        if visible is not None:
            query += " AND entries.entry_type = ANY(%(entry_types)s)"
            if visible:
                params["entry_types"] = const.ComplaintEntryType.visible_types()
            else:
                params["entry_types"] = const.ComplaintEntryType.hidden_types()

        if deleted is not None:
            if deleted:
                query += " AND versions.dtime IS NOT NULL"
            else:
                query += " AND versions.dtime IS NULL"

        if entry_id is not None:
            query += " AND entry_id = %(entry_id)s"
            params['entry_id'] = entry_id

        decrypt = lambda x: x
        return {
            e["id"]: decrypt(e["description"])
            for e in self.query_all(rs, query, params)
        }

    @access("complaint_admin")
    def get_visible_descriptions(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int | None = None,
        deleted: bool | None = False,
    ) -> dict[int, str]:
        """List all descriptions that are visible without unlock.

        :returns: Mapping of entry *version* ids to descriptions.
        """
        case_id = affirm(int, case_id)
        entry_id = affirm_optional(int, entry_id)
        deleted = affirm_optional(bool, deleted)
        return self._get_descriptions(
            rs, case_id=case_id, entry_id=entry_id, visible=True, deleted=deleted
        )

    def _log_unlock(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        self.affirm_atomized_context(rs)
        ret = self.complaint_log(
            rs=rs, code=const.ComplaintLogCodes.case_unlocked, case_id=case_id
        )
        query = f"""
            INSERT INTO {models.AccessLog.database_table} (case_id, persona_id)
            VALUES (%(case_id)s, %(persona_id)s)
            ON CONFLICT (case_id, persona_id) DO UPDATE
                SET ctime = excluded.ctime, atime = excluded.atime
        """
        ret *= self.query_exec(
            rs, query, {"case_id": case_id, "persona_id": rs.user.persona_id}
        )
        return ret

    @access("complaint_admin")
    def is_unlocked(self, rs: RequestState, case_id: int) -> bool | None:
        """Determine whether a case is currently unlocked for the active user.

        :returns: 'True' if the case is unlocked. 'False' if the unlock has timed out.
            'None' if the case has not been unlocked.
        """
        case_id = affirm(int, case_id)

        query = f"""
            SELECT id, ctime
            FROM {models.AccessLog.database_table}
            WHERE case_id = %(case_id)s AND persona_id = %(persona_id)s
        """
        timestamp = now()

        data = self.query_one(
            rs, query, {"case_id": case_id, "persona_id": rs.user.persona_id}
        )
        if data is None:
            # Case has not been unlocked.
            return None
        if (data["ctime"] + self.conf["COMPLAINT_UNLOCK_TIMEOUT"]) >= timestamp:
            # Case is unlocked.
            return True
        # Unlock has timed out.
        return False

    def _unlock_case(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        self.affirm_atomized_context(rs)

        if not self.is_unlocked(rs, case_id):
            ret = self._log_unlock(rs, case_id=case_id)
        else:
            # Update last access time.
            query = f"""
                UPDATE {models.AccessLog.database_table}
                SET atime = now()
                WHERE case_id = %(case_id)s AND persona_id = %(persona_id)s
            """
            ret = self.query_exec(
                rs, query, {"case_id": case_id, "persona_id": rs.user.persona_id}
            )
        return ret

    @access("complaint_admin")
    def unlock_case(self, rs: RequestState, case_id: int) -> dict[int, str]:
        """Log access to locked data, decrypt the descriptions and return them.

        :returns: Mapping of entry *version* ids to descriptions.
        """
        case_id = affirm(int, case_id)
        with Atomizer(rs):
            if not self._unlock_case(rs, case_id):
                raise RuntimeError
            return self._get_descriptions(rs, case_id=case_id, visible=False)

    @access("complaint_admin")
    def get_all_descriptions(self, rs: RequestState, case_id: int) -> dict[int, str]:
        """Return all descriptions if case already unlocked.

        :returns: Mapping of entry *version* ids to descriptions.
        """
        case_id = affirm(int, case_id)
        if not self.is_unlocked(rs, case_id):
            raise PrivilegeError
        return self._get_descriptions(rs, case_id=case_id, visible=False, deleted=None)

    @access("complaint_admin")
    def lock_case(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        case_id = affirm(int, case_id)
        with Atomizer(rs):
            if not self.is_unlocked(rs, case_id):
                return -1
            query = f"""
                DELETE FROM {models.AccessLog.database_table}
                WHERE case_id = %(case_id)s AND persona_id = %(persona_id)s
            """
            return self.query_exec(
                rs, query, {"case_id": case_id, "persona_id": rs.user.persona_id}
            )

    @access("complaint_admin")
    def submit_general_query(
        self, rs: RequestState, query: Query
    ) -> tuple[CdEDBObject, ...]:
        query = affirm(Query, query)

        if query.scope != QueryScope.complaint_case:
            raise RuntimeError(n_("Bad scope."), query.scope)

        access_timeout = now() - self.conf["COMPLAINT_UNLOCK_TIMEOUT"]
        # "SELECT * FROM" for syntax highlighting only
        view = f"""
            SELECT * FROM
                {models.Case.database_table} AS cases
                LEFT JOIN (
                    SELECT id AS case_id, EXISTS(
                        SELECT case_id
                        FROM {models.AccessLog.database_table}
                        WHERE
                            persona_id = {rs.user.persona_id}
                            AND case_id = cases.id
                            AND ctime > '{access_timeout.isoformat()}'
                    ) AS is_unlocked
                    FROM {models.Case.database_table}
                ) AS access ON access.case_id = cases.id
                LEFT JOIN {models.ComplaintEntry.database_table}
                    AS entries ON entries.case_id = cases.id
                LEFT JOIN {models.ComplaintEntryVersion.database_table}
                    AS versions ON versions.entry_id = entries.id
                LEFT JOIN {models.ComplaintAuthors.database_table}
                    AS authors ON authors.entry_version_id = versions.id
                LEFT JOIN {models.ComplaintInvolved.database_table}
                    AS involved ON involved.case_id = cases.id
                LEFT JOIN {models.ComplaintCompanion.database_table}
                    AS companion ON companion.involved_id = involved.id
        """.strip().removeprefix("SELECT * FROM")

        return self.general_query(rs, query, view=view)

    @access("complaint_admin")
    def get_measures(
        self, rs: RequestState, concerned_id: int, is_active: bool | None = True
    ) -> dict[int, models.ComplaintEntryVersion]:
        query = f"""
            SELECT versions.id
            FROM {models.ComplaintEntryVersion.database_table} AS versions
                LEFT JOIN {models.ComplaintEntry.database_table} AS entries
                    ON entries.id = versions.entry_id
            WHERE
                entries.concerned_id = %(concerned_id)s
                AND entries.entry_type = ANY(%(entry_types)s)
                AND versions.dtime IS NULL
        """
        params: dict[str, DatabaseValue_s] = {
            "concerned_id": concerned_id,
            "entry_types": const.ComplaintEntryType.measure_types(),
        }

        if is_active is not None:
            query += """
                AND (
                    NOT entries.is_revoked
                    AND versions.etime IS NULL
                ) = %(is_active)s
            """
            params["is_active"] = is_active

        entry_version_ids = [e['id'] for e in self.query_all(rs, query, params)]
        entry_version_data = self.query_all(
            rs,
            *models.ComplaintEntryVersion.get_select_query(
                entry_version_ids, entity_key="id"
            ),
        )
        return models.ComplaintEntryVersion.many_from_database(entry_version_data)
