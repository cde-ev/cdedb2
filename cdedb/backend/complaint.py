#!/usr/bin/env python3
import datetime
from collections.abc import Collection
from typing import Protocol, cast

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.backend.common import (
    AbstractBackend,
    access,
    affirm_validation as affirm,
    singularize,
)
from cdedb.common import (
    CdEDBLog,
    CdEDBObject,
    DefaultReturnCode,
    RequestState,
    now,
    unwrap,
)
from cdedb.common.attachment import EncryptedAttachmentStore
from cdedb.common.crypt import get_decrypt, get_decrypt_decode, get_encrypt
from cdedb.common.exceptions import AdverseCompanionError, PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryScope
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.common.sorting import mixed_existence_sorter, xsorted
from cdedb.config import SecretsConfig
from cdedb.database.connection import Atomizer
from cdedb.database.constants import ComplaintLogCodes
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

    def __init__(self) -> None:
        super().__init__()
        secrets = SecretsConfig()
        complaint_secret = secrets["COMPLAINT_SECRET"]

        self.encrypt = get_encrypt(complaint_secret)

        self.decrypt = get_decrypt(complaint_secret)
        self.decrypt_decode = get_decrypt_decode(complaint_secret)

        self._attachment_store = EncryptedAttachmentStore(
            self.conf['STORAGE_DIR'] / "complaint_attachment",
            secret=complaint_secret,
        )

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("complaint_admin")
    def get_attachment_store(self, rs: RequestState) -> EncryptedAttachmentStore:
        return self._attachment_store

    @access("complaint_admin")
    def retrieve_attachment(
        self, rs: RequestState, entry_id: int, version_nr: int
    ) -> bytes | None:
        entry_id = affirm(vtypes.ID, entry_id)
        version_nr = affirm(vtypes.ID, version_nr)
        case_id = self._get_case_id(rs, entry_id)
        entry = self.get_case(rs, case_id).entries[entry_id]
        entry_version = entry.all_versions[version_nr - 1]

        if not entry_version.attachment_hash:
            raise ValueError("Entry version has no attachment.")

        if entry.entry_type.is_hidden and not self.is_unlocked(rs, case_id):
            raise PrivilegeError

        # attachment hash is obscured upon retrieval.
        attachment_hash = cast(
            str,
            unwrap(
                self.sql_select_one(
                    rs,
                    models.ComplaintEntryVersion.database_table,
                    ["attachment_hash"],
                    entry_version.id,
                )
            ),
        )

        return self.get_attachment_store(rs).get(attachment_hash)

    @access("complaint_admin")
    def get_attachment_usage(self, rs: RequestState, attachment_hash: str) -> bool:
        attachment_hash = affirm(vtypes.Identifier, attachment_hash)
        query = f"""
            SELECT COUNT(*)
            FROM {models.ComplaintEntryVersion.database_table}
            WHERE attachment_hash = %(attachment_hash)s
        """
        return bool(
            unwrap(self.query_one(rs, query, {"attachment_hash": attachment_hash}))
        )

    @access("persona")
    def list_enforcers(self, rs: RequestState) -> set[vtypes.ID]:
        """List all enforcers."""
        data = self.query_all(rs, "SELECT persona_id FROM complaint.enforcers", [])
        return {e['persona_id'] for e in data}

    @access("complaint_admin")
    def add_enforcer(
        self, rs: RequestState, persona_id: vtypes.ID
    ) -> DefaultReturnCode:
        """Add a new enforcer."""
        persona_id = affirm(vtypes.ID, persona_id)
        if not self.core.verify_id(rs, persona_id, is_archived=False):
            raise ValueError(n_("This user does not exist or is archived."))

        with Atomizer(rs):
            if persona_id in self.list_enforcers(rs):
                return -1
            ret = self.sql_insert(rs, "complaint.enforcers", {'persona_id': persona_id})
            if ret:
                self.complaint_log(
                    rs=rs,
                    code=ComplaintLogCodes.enforcer_added,
                    case_id=None,
                    persona_id=persona_id,
                )
        return ret

    @access("complaint_admin")
    def remove_enforcer(
        self, rs: RequestState, persona_id: vtypes.ID
    ) -> DefaultReturnCode:
        """Remove enforcer privileges for a persona."""
        persona_id = affirm(vtypes.ID, persona_id)
        if not self.core.verify_id(rs, persona_id, is_archived=False):
            raise ValueError(n_("This user does not exist or is archived."))

        with Atomizer(rs):
            if persona_id not in self.list_enforcers(rs):
                return -1
            ret = self.sql_delete(
                rs, "complaint.enforcers", {persona_id}, entity_key="persona_id"
            )
            if ret:
                self.complaint_log(
                    rs=rs,
                    code=ComplaintLogCodes.enforcer_removed,
                    case_id=None,
                    persona_id=persona_id,
                )
        return ret

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
        if rs.is_quiet:
            return 0
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
    def complaint_log_case_detected(
        self, rs: RequestState, *, case_id: int, persona_id: int
    ) -> int:
        with Atomizer(rs):
            return self.complaint_log(
                rs=rs,
                code=const.ComplaintLogCodes.concealed_case_detected,
                case_id=case_id,
                persona_id=persona_id,
            )

    @access("complaint_admin")
    def retrieve_log(
        self,
        rs: RequestState,
        log_filter: ComplaintLogFilter,
    ) -> CdEDBLog:
        """Retrieve log entries related to complaint cases.

        The full history of a case consists of both log entries and complaint entries.
        """
        log_filter = affirm(ComplaintLogFilter, log_filter)
        case_ids = set(log_filter.case_ids())

        visible_case_ids = self.get_visible_case_ids(rs)

        if case_ids:
            case_ids &= visible_case_ids
        elif visible_case_ids:
            case_ids = visible_case_ids
        log_filter.case_id = None
        log_filter._case_ids = list(case_ids)

        return self.generic_retrieve_log(rs, log_filter)

    @access("complaint_admin")
    def get_visible_case_ids(self, rs: RequestState) -> set[int]:
        query = f"SELECT id FROM {models.Case.database_table}"
        case_ids = self.query_all(rs, query, ())
        cases = self.get_cases(rs, [e["id"] for e in case_ids])
        return {case.id for case in cases.values() if case.is_visible_for(rs.user)}

    @access("complaint_admin")
    def get_cases(
        self, rs: RequestState, case_ids: Collection[int]
    ) -> models.CdEDataclassMap[models.Case]:
        """Retrieve metadata and a list of complaint entries for some complaint cases."""
        case_ids = affirm(set[vtypes.ID], case_ids)
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

            ret = models.Case.many_from_database(case_data)
            for case in ret.values():
                _, log_entries = self.generic_retrieve_log(
                    rs, ComplaintLogFilter(case_id=case.id)
                )
                case.personas = self.core.get_personas(
                    rs, case.get_persona_ids(log_entries)
                )
                case.involved = {
                    involved.id: involved
                    for involved in xsorted(case.involved.values())
                }
            return ret

    class _GetCaseProtocol(Protocol):
        def __call__(self, rs: RequestState, case_id: int) -> models.Case: ...

    get_case = singularize(get_cases, 'case_ids', 'case_id')

    @access("complaint_admin")
    def get_related_cases(
        self, rs: RequestState, case_id: int
    ) -> dict[int, models.Case | None]:
        """Collect related cases."""
        case_id = affirm(vtypes.ID, case_id)
        query = f"SELECT id FROM {models.Case.database_table}"
        case_ids = self.query_all(rs, query, ())
        _cases = self.get_cases(rs, [e["id"] for e in case_ids])
        _related_cases = {
            maybe_related_case_id: case
            for maybe_related_case_id, case in _cases.items()
            if _cases[case_id].properly_involved_persona_ids
            & case.properly_involved_persona_ids
        }
        del _related_cases[case_id]

        # Show no information on invisible cases
        related_cases: dict[int, models.Case | None] = {}
        for case_id_, case_ in _related_cases.items():
            related_cases[case_id_] = case_ if case_.is_visible_for(rs.user) else None

        return related_cases

    @access("complaint_admin")
    def set_case(
        self, rs: RequestState, case_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Alter metadata of a complaint case."""
        case_id = affirm(vtypes.ID, case_id)
        data = affirm(models.Case, data)

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
        data = affirm(models.Case, data, creation=True)

        with Atomizer(rs):
            new_id = self.sql_insert(rs, models.Case.database_table, data)
            new_case = models.Case(
                id=cast(vtypes.ID, new_id),
                **data,
                entries={},
                involved={},
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
            data["description"] = self.encrypt(data["description"])
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
        if filehash := data.get("attachment_hash"):
            if not self.get_attachment_store(rs).is_available(filehash):
                raise RuntimeError(n_("File has been lost."))
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

            entry_data = affirm(
                models.ComplaintEntry,
                entry_data,
                creation=True,
                entries=case.entries,
            )
            version_data = affirm(
                models.ComplaintEntryVersion,
                version_data,
                creation=True,
                entry_type=entry_data['entry_type'],
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
        data = affirm(
            models.ComplaintEntryVersion,
            data,
            creation=False,
            entry_type=entry.entry_type,
        )
        dreason = affirm(str | None, dreason)

        with Atomizer(rs):
            self._delete_entry(rs, entry_id=entry_id, dreason=dreason)
            return self._insert_entry_version(rs, entry_id=entry_id, data=data)

    @access("complaint_admin")
    def delete_entry(
        self, rs: RequestState, entry_id: int, dreason: str | None
    ) -> DefaultReturnCode:
        """Delete an existing entry version."""
        entry_id = affirm(vtypes.ID, entry_id)
        dreason = affirm(str | None, dreason)
        with Atomizer(rs):
            case_id = self._get_case_id(rs, entry_id)
            entry = self.get_case(rs, case_id).entries[entry_id]
            if entry.active_children:
                raise ValueError("Cannot delete entry with active children.")
            if entry.entry_type == const.ComplaintEntryType.revocation_explanation:
                self.sql_update(
                    rs,
                    models.ComplaintEntry.database_table,
                    {'id': entry.parent_id, 'is_revoked': False},
                )
                if (
                    entry.parent
                    and entry.parent.entry_type
                    == const.ComplaintEntryType.revocation_explanation
                ):
                    self.sql_update(
                        rs,
                        models.ComplaintEntry.database_table,
                        {'id': entry.parent.parent_id, 'is_revoked': True},
                    )
            return self._delete_entry(rs, entry_id=entry_id, dreason=dreason)

    @access("complaint_admin")
    def revoke_entry(
        self, rs: RequestState, entry_id: int, version_data: CdEDBObject
    ) -> DefaultReturnCode:
        """Revoke an existing entry. If that entry is a revocation, unrevoke the parent."""
        entry_id = affirm(vtypes.ID, entry_id)

        revocation_type = const.ComplaintEntryType.revocation_explanation

        version_data = affirm(
            models.ComplaintEntryVersion,
            version_data,
            creation=True,
            entry_type=revocation_type,
        )
        with Atomizer(rs):
            case_id = self._get_case_id(rs, entry_id)
            case = self.get_case(rs, case_id)
            entry = case.entries[entry_id]

            if entry.is_revoked:
                raise ValueError(n_("Entry already revoked."))
            if not entry.active_version:
                raise ValueError(n_("Entry has no active version."))

            code = self.sql_update(
                rs,
                models.ComplaintEntry.database_table,
                {'id': entry_id, 'is_revoked': True},
            )
            if not code:
                raise RuntimeError

            if entry.entry_type == revocation_type:
                if not entry.parent:
                    raise RuntimeError(n_("Revocation entry without parent."))
                if entry.parent.entry_type == revocation_type:
                    raise ValueError(n_("Cannot chain revoke."))

                if entry.parent.is_revoked:
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
    def mark_entry_version_for_purge(
        self, rs: RequestState, entry_id: int, entry_version_id: int
    ) -> DefaultReturnCode:
        entry_id = affirm(vtypes.ID, entry_id)
        entry_version_id = affirm(vtypes.ID, entry_version_id)

        with Atomizer(rs):
            case_id = self._get_case_id(rs, entry_id)
            case = self.get_case(rs, case_id)
            entry = case.entries[entry_id]

            if not (entry_version := entry.versions_by_id.get(entry_version_id)):
                raise ValueError(n_("Unknown entry version."))
            if entry_version.marked_for_purge:
                raise ValueError(n_("Entry version already marked for purge."))

            code = self.sql_update(
                rs,
                models.ComplaintEntryVersion.database_table,
                {
                    'id': entry_version_id,
                    'marked_for_purge': now(),
                    'purged_by': rs.user.persona_id,
                },
            )
        return code

    @access("complaint_admin")
    def unmark_entry_version_for_purge(
        self, rs: RequestState, entry_id: int, entry_version_id: int
    ) -> DefaultReturnCode:
        entry_id = affirm(vtypes.ID, entry_id)
        entry_version_id = affirm(vtypes.ID, entry_version_id)

        with Atomizer(rs):
            case_id = self._get_case_id(rs, entry_id)
            case = self.get_case(rs, case_id)
            entry = case.entries[entry_id]

            if not (entry_version := entry.versions_by_id.get(entry_version_id)):
                raise ValueError(n_("Unknown entry version."))
            if not entry_version.marked_for_purge:
                raise ValueError(n_("Entry version not marked for purge."))

            code = self.sql_update(
                rs,
                models.ComplaintEntryVersion.database_table,
                {
                    'id': entry_version_id,
                    'marked_for_purge': None,
                    'purged_by': None,
                },
            )
        return code

    @access("cron")
    def purge_entry_version(
        self, rs: RequestState, entry_id: int, entry_version_id: int
    ) -> DefaultReturnCode:
        entry_id = affirm(vtypes.ID, entry_id)
        entry_version_id = affirm(vtypes.ID, entry_version_id)

        with Atomizer(rs):
            case_id = self._get_case_id(rs, entry_id)
            case = self.get_case(rs, case_id)
            entry = case.entries[entry_id]

            if not (entry_version := entry.versions_by_id[entry_version_id]):
                raise ValueError(n_("Unknown entry version."))

            purge_delay = self.conf["COMPLAINT_ENTRY_VERSION_PURGE_DELAY"]
            if not entry_version.marked_for_purge:
                raise ValueError(n_("Entry version not marked for purge."))
            if now() - entry_version.marked_for_purge < purge_delay:
                raise ValueError(n_("Not yet ready for purge."))

            code = self.sql_update(
                rs,
                models.ComplaintEntryVersion.database_table,
                {
                    'id': entry_version_id,
                    'is_purged': True,
                    'description': None,
                    'length': None,
                    'timestamp': None,
                    'dreason': None,
                    'attachment_hash': None,
                    'attachment_title': None,
                    'attachment_filename': None,
                },
            )
            self.sql_delete(
                rs,
                models.ComplaintAuthors.database_table,
                [entry_version_id],
                entity_key="entry_version_id",
            )
        return code

    @access("complaint_admin")
    def list_entry_versions_marked_for_purge(
        self, rs: RequestState
    ) -> list[models.ComplaintEntryVersion]:
        with Atomizer(rs):
            marked_for_purge = self.query_all(
                rs,
                f"""
                    SELECT cev.id AS entry_version_id, ce.id AS entry_id, ce.case_id
                    FROM {models.ComplaintEntryVersion.database_table} cev
                        JOIN {models.ComplaintEntry.database_table} ce ON cev.entry_id = ce.id
                    WHERE NOT is_purged AND marked_for_purge IS NOT NULL
                """,
                [],
            )
            cases: models.CdEDataclassMap[models.Case] = {}

            ret = []
            for datum in marked_for_purge:
                case_id = datum["case_id"]
                entry_id = datum["entry_id"]
                entry_version_id = datum["entry_version_id"]

                case = cases.get(case_id)
                if not case:
                    cases[case_id] = case = self.get_case(rs, case_id)
                entry = case.entries[entry_id]
                ret.append(entry.versions_by_id[entry_version_id])

            return ret

    @access("complaint_admin")
    def add_involved(
        self,
        rs: RequestState,
        case_id: int,
        involvement_type: const.ComplaintInvolvementType,
        persona_ids: Collection[vtypes.PersonaID],
    ) -> DefaultReturnCode:
        """Add the given personas as involved people of the given type to a case.

        :returns:
            0 if no persona ids were given or if something went wrong.
            -1 if no one was added (because they were already involved).
            The number of newly added personas otherwise.
        """
        case_id = affirm(vtypes.ID, case_id)
        involvement_type = affirm(const.ComplaintInvolvementType, involvement_type)
        persona_ids = affirm(set[vtypes.PersonaID], persona_ids)

        if not persona_ids:
            return 0

        if involvement_type == const.ComplaintInvolvementType.appellant:
            is_informed = True
        else:
            is_informed = False

        if not self.core.verify_ids(rs, persona_ids):
            raise ValueError(n_("Unknown users."))

        ret = 1
        with Atomizer(rs):
            case = self.get_case(rs, case_id)

            if persona_ids & case.get_companions(is_active=True).keys():
                raise ValueError(n_("Already active companions."))

            # If some of these users are involved already, update them instead.
            # We will log this as remove + add.
            already_involved_ids = {
                involved_id
                for involved_id, involved in case.involved.items()
                if involved.persona_id in set(persona_ids) & case.involved_persona_ids
            }

            # If they are updated to a state requiring is_informed, log this later
            newly_informed = set()  # of persona_ids
            for involved_id in mixed_existence_sorter(already_involved_ids):
                involved = case.involved[involved_id]
                data: CdEDBObject = {
                    "id": involved_id,
                    "involvement_type": involvement_type,
                }
                if is_informed and not involved.is_informed:
                    data['is_informed'] = True
                    newly_informed.add(involved.persona_id)
                ret = self.sql_update(rs, models.ComplaintInvolved.database_table, data)
                ret *= -1
                self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.involved_removed,
                    case_id=case_id,
                    persona_id=involved.persona_id,
                    change_note=rs.log_gettext(str(involved.involvement_type)),
                )

            newly_involved = set(persona_ids) - case.involved_persona_ids
            if newly_involved:
                ret *= self.sql_insert_many(
                    rs,
                    models.ComplaintInvolved.database_table,
                    [
                        {
                            "case_id": case_id,
                            "persona_id": persona_id,
                            "involvement_type": involvement_type,
                            "is_informed": is_informed,
                        }
                        for persona_id in newly_involved
                    ],
                )

            for persona_id in sorted(persona_ids):
                self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.involved_added,
                    case_id=case_id,
                    persona_id=persona_id,
                    change_note=rs.log_gettext(str(involvement_type)),
                )

            if is_informed:
                for persona_id in sorted(newly_involved & newly_informed):
                    self.complaint_log(
                        rs=rs,
                        code=const.ComplaintLogCodes.involved_informed,
                        case_id=case_id,
                        persona_id=persona_id,
                    )

            # Finally check, if any companions are now adverse.
            new_case = self.get_case(rs, case_id)
            for involvement_type in const.ComplaintInvolvementType:
                companions = new_case.companions_by_involved_type(is_active=True).get(
                    involvement_type, set()
                )
                adverse_companions = new_case.adverse_companions(involvement_type)
                if companions & adverse_companions:
                    raise AdverseCompanionError

        return ret

    @access("complaint_admin")
    def remove_involved(
        self,
        rs: RequestState,
        case_id: int,
        involved_ids: Collection[vtypes.InvolvedID],
    ) -> DefaultReturnCode:
        """Remove some users as involved with a case.

        :returns:
            0 if no persona ids were given or if something went wrong.
            -1 if no one was removed (because they weren't involved).
            The number of removed personas otherwise.
        """
        case_id = affirm(vtypes.ID, case_id)
        involved_ids = affirm(set[vtypes.InvolvedID], involved_ids)

        if not involved_ids:
            return 0

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            removed = involved_ids & case.involved.keys()
            if not removed:
                return -1
            ret = self.sql_delete(
                rs, models.ComplaintInvolved.database_table, involved_ids
            )
            for involved_id in mixed_existence_sorter(removed):
                involved = case.involved[involved_id]
                companions = involved.get_companions(is_active=None)
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.involved_removed,
                    case_id=case_id,
                    persona_id=involved.persona_id,
                    change_note=rs.log_gettext(str(involved.involvement_type)),
                )
                for companion_id in mixed_existence_sorter(companions):
                    ret *= self.complaint_log(
                        rs=rs,
                        code=const.ComplaintLogCodes.companion_removed,
                        case_id=case_id,
                        persona_id=involved.persona_id,
                        companion_id=companion_id,
                    )
        return ret

    @access("complaint_admin")
    def set_involved_informed(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        is_informed: bool,
    ) -> DefaultReturnCode:
        """Set the informed status of an involved person."""
        case_id = affirm(vtypes.ID, case_id)
        involved_id = affirm(vtypes.InvolvedID, involved_id)
        is_informed = affirm(bool, is_informed)

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if involved_id not in case.involved:
                raise ValueError(n_("Uninvolved user."))
            if is_informed == case.involved[involved_id].is_informed:
                return -1
            query = f"""
                UPDATE {models.ComplaintInvolved.database_table}
                SET is_informed = %(is_informed)s
                WHERE id = %(involved_id)s
            """
            params = {
                "involved_id": involved_id,
                "is_informed": is_informed,
            }
            ret = self.query_exec(rs, query, params)
            if is_informed:
                code = const.ComplaintLogCodes.involved_informed
            else:
                code = const.ComplaintLogCodes.involved_uninformed
            persona_id = case.involved[involved_id].persona_id
            ret *= self.complaint_log(
                rs=rs, code=code, case_id=case_id, persona_id=persona_id
            )
        return ret

    @access("complaint_admin")
    def add_companions(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_ids: Collection[vtypes.PersonaID],
    ) -> DefaultReturnCode:
        """Add companions to a person involved in a case."""
        case_id = affirm(vtypes.ID, case_id)
        involved_id = affirm(vtypes.InvolvedID, involved_id)
        companion_ids = affirm(set[vtypes.PersonaID], companion_ids)

        if not companion_ids:
            return 0

        with Atomizer(rs):
            if not self.core.verify_ids(rs, companion_ids):
                raise ValueError(n_("Unknown companions."))

            case = self.get_case(rs, case_id)
            if involved_id not in case.involved:
                raise ValueError(n_("Uninvolved user."))
            involved = case.involved[involved_id]
            companion_ids -= involved.get_companions(is_active=None).keys()
            if not companion_ids:
                return -1

            if companion_ids & case.adverse_companions(involved.involvement_type):
                raise AdverseCompanionError
            if companion_ids & case.involved_persona_ids:
                raise ValueError(n_("Involved companion."))

            values = [
                {
                    "case_id": case_id,
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
                    persona_id=involved.persona_id,
                    companion_id=companion_id,
                )
        return ret

    @access("complaint_admin")
    def remove_companions(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_ids: Collection[vtypes.PersonaID],
    ) -> DefaultReturnCode:
        """Remove companions from a person involved in a case."""
        case_id = affirm(vtypes.ID, case_id)
        involved_id = affirm(vtypes.InvolvedID, involved_id)
        companion_ids = affirm(set[vtypes.PersonaID], companion_ids)
        if not companion_ids:
            return 0
        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if involved_id not in case.involved:
                raise ValueError(n_("Uninvolved user."))
            involved = case.involved[involved_id]
            companion_ids &= involved.get_companions(is_active=None).keys()
            if not companion_ids:
                return -1

            query = f"""
                DELETE FROM {models.ComplaintCompanion.database_table}
                    WHERE involved_id = %(involved_id)s
                    AND companion_persona_id = ANY(%(companion_ids)s)
            """
            params: dict[str, DatabaseValue_s] = {
                "involved_id": involved_id,
                "companion_ids": companion_ids,
            }
            ret = self.query_exec(rs, query, params)

            for companion_id in mixed_existence_sorter(companion_ids):
                ret *= self.complaint_log(
                    rs=rs,
                    code=const.ComplaintLogCodes.companion_removed,
                    case_id=case_id,
                    persona_id=involved.persona_id,
                    companion_id=companion_id,
                )
        return ret

    @access("complaint_admin")
    def set_companion_withdrawn(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_id: vtypes.PersonaID,
        is_withdrawn: bool,
    ) -> DefaultReturnCode:
        """Set the withdrawn status of a companion."""
        case_id = affirm(vtypes.ID, case_id)
        involved_id = affirm(vtypes.InvolvedID, involved_id)
        companion_id = affirm(vtypes.PersonaID, companion_id)
        is_withdrawn = affirm(bool, is_withdrawn)

        with Atomizer(rs):
            case = self.get_case(rs, case_id)
            if involved_id not in case.involved:
                raise ValueError(n_("Uninvolved user."))
            involved = case.involved[involved_id]
            if companion_id not in involved.get_companions(is_active=None):
                raise ValueError(n_("Not a companion."))
            if is_withdrawn == (
                companion_id in involved.get_companions(is_active=False)
            ):
                return -1
            query = f"""
                UPDATE {models.ComplaintCompanion.database_table}
                SET is_withdrawn = %(is_withdrawn)s
                WHERE involved_id = %(involved_id)s
                    AND companion_persona_id = %(companion_id)s
            """
            params = {
                "involved_id": involved_id,
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
                persona_id=involved.persona_id,
                companion_id=companion_id,
            )
        return ret

    def _get_descriptions(
        self,
        rs: RequestState,
        *,
        case_id: int | None = None,
        entry_ids: Collection[int] | None = None,
        visible: bool | None,
        deleted: bool | None = False,
    ) -> dict[int, str]:
        query = f"""
            SELECT versions.id, versions.description
            FROM
                {models.ComplaintEntryVersion.database_table} AS versions
                LEFT JOIN {models.ComplaintEntry.database_table} AS entries
                    ON versions.entry_id = entries.id
        """
        params: dict[str, DatabaseValue_s] = {}
        conditions = []

        if case_id is not None:
            conditions.append("entries.case_id = %(case_id)s")
            params["case_id"] = case_id

        if entry_ids is not None:
            conditions.append("entries.id = ANY(%(entry_ids)s)")
            params['entry_ids'] = entry_ids

        if visible is not None:
            conditions.append("entries.entry_type = ANY(%(entry_types)s)")
            if visible:
                params["entry_types"] = const.ComplaintEntryType.visible_types()
            else:
                params["entry_types"] = const.ComplaintEntryType.hidden_types()

        if deleted is not None:
            if deleted:
                conditions.append("versions.dtime IS NOT NULL")
            else:
                conditions.append("versions.dtime IS NULL")

        if conditions:
            query += "WHERE " + " AND ".join(conditions)

        return {
            e["id"]: self.decrypt_decode(e["description"]) or ""
            for e in self.query_all(rs, query, params)
        }

    @access("complaint_admin")
    def get_visible_descriptions(
        self,
        rs: RequestState,
        case_id: int,
        entry_ids: Collection[int] | None = None,
        deleted: bool | None = False,
    ) -> dict[int, str]:
        """List all descriptions that are visible without unlock.

        :returns: Mapping of entry *version* ids to descriptions.
        """
        case_id = affirm(int, case_id)
        entry_ids = affirm(set[vtypes.ID] | None, entry_ids)
        deleted = affirm(bool | None, deleted)
        return self._get_descriptions(
            rs, case_id=case_id, entry_ids=entry_ids, visible=True, deleted=deleted
        )

    def _log_unlock(
        self, rs: RequestState, case_id: int, reason: str
    ) -> DefaultReturnCode:
        self.affirm_atomized_context(rs)
        ret = self.complaint_log(
            rs=rs,
            code=const.ComplaintLogCodes.case_unlocked,
            case_id=case_id,
            change_note=reason,
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

    def _unlock_case(
        self, rs: RequestState, case_id: int, reason: str
    ) -> DefaultReturnCode:
        self.affirm_atomized_context(rs)

        if not self.is_unlocked(rs, case_id):
            ret = self._log_unlock(rs, case_id=case_id, reason=reason)
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
    def unlock_case(
        self, rs: RequestState, case_id: int, reason: str
    ) -> DefaultReturnCode:
        """Log access to locked data, decrypt the descriptions and return them.

        :returns: Mapping of entry *version* ids to descriptions.
        """
        case_id = affirm(int, case_id)
        with Atomizer(rs):
            return self._unlock_case(rs, case_id, reason)

    @access("complaint_admin")
    def get_hidden_descriptions(self, rs: RequestState, case_id: int) -> dict[int, str]:
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

        access_timeout: datetime.datetime = (
            now() - self.conf["COMPLAINT_UNLOCK_TIMEOUT"]
        )
        # "SELECT * FROM" for syntax highlighting only
        view = f"""
            SELECT * FROM
                {models.Case.database_table} AS cases
                LEFT JOIN (
                    SELECT
                        id AS case_id,
                        EXISTS(
                            SELECT case_id
                            FROM {models.AccessLog.database_table}
                            WHERE
                                persona_id = {rs.user.persona_id}
                                AND case_id = cases.id
                                AND ctime > '{access_timeout.isoformat()}'
                        ) AS is_unlocked,
                        EXISTS(
                            SELECT entries.case_id
                            FROM
                                {models.ComplaintEntry.database_table} AS entries
                                JOIN {models.ComplaintEntryVersion.database_table} AS versions
                                    ON versions.entry_id = entries.id
                            WHERE
                                entries.case_id = cases.id
                                AND entries.entry_type = {const.ComplaintEntryType.statement_signed.value}
                                AND NOT entries.is_revoked
                                AND versions.dtime IS NULL
                        ) AS is_confirmed,
                        EXISTS(
                            SELECT entries.case_id
                            FROM
                                {models.ComplaintEntry.database_table} AS entries
                                JOIN {models.ComplaintEntryVersion.database_table} AS versions
                                    ON versions.entry_id = entries.id
                            WHERE
                                entries.case_id = cases.id
                                AND entries.entry_type = {const.ComplaintEntryType.synthesis.value}
                                AND NOT entries.is_revoked
                                AND versions.dtime IS NULL
                        ) AS is_closed,
                        (SELECT MAX(versions.timestamp)
                            FROM
                                {models.ComplaintEntry.database_table} AS entries
                                JOIN {models.ComplaintEntryVersion.database_table} AS versions
                                    ON versions.entry_id = entries.id
                            WHERE
                                entries.case_id = cases.id
                        ) AS last_entry
                    FROM {models.Case.database_table}
                ) AS status ON status.case_id = cases.id
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

    @access("persona")
    def get_user_measures(
        self, rs: RequestState, concerned_id: int, is_active: bool | None = True
    ) -> tuple[models.CdEDataclassMap[models.ComplaintEntry], dict[int, str]]:
        """Get all measures against a specific user.

        This includes active measures, future measures and expired measures,
        but not deleted, revoked or purged measures.

        Additionally it does not include expired provisional measures.
        """

        concerned_id = affirm(vtypes.ID, concerned_id)
        is_active = affirm(bool | None, is_active)
        if not (
            {"complaint_admin", "complaint.enforcer"} & rs.user.all_roles
            or concerned_id == rs.user.persona_id
        ):
            raise PrivilegeError

        query = f"""
            SELECT entries.id AS entry_id, versions.id AS version_id
            FROM {models.ComplaintEntryVersion.database_table} AS versions
                LEFT JOIN {models.ComplaintEntry.database_table} AS entries
                    ON entries.id = versions.entry_id
            WHERE
                entries.concerned_id = %(concerned_id)s
                AND entries.entry_type = ANY(%(entry_types)s)
                AND versions.dtime IS NULL
                AND NOT versions.is_purged
                AND NOT entries.is_revoked
        """
        params: dict[str, DatabaseValue_s] = {
            "concerned_id": concerned_id,
            "entry_types": const.ComplaintEntryType.measure_types(),
        }

        data = self.query_all(rs, query, params)
        entry_ids_to_version_ids = {e['entry_id']: e['version_id'] for e in data}
        entries = self._get_measures(rs, entry_ids_to_version_ids)

        entries = {
            e_id: e
            for e_id, e in entries.items()
            if not (e.is_provisional and e.is_expired_measure)
        }
        descriptions = self._get_descriptions(
            rs, entry_ids=entries.keys(), visible=True
        )
        return entries, descriptions

    @access("complaint_admin", "complaint.enforcer")
    def get_measures(
        self, rs: RequestState
    ) -> tuple[models.CdEDataclassMap[models.ComplaintEntry], dict[int, str]]:
        """Get all active measures against all users.

        This includes neither future nor expired measures regardless of their type.
        It also does not include deleted, revoked or purged measures.
        """
        query = f"""
            SELECT entries.id AS entry_id, versions.id AS version_id
            FROM {models.ComplaintEntryVersion.database_table} AS versions
                LEFT JOIN {models.ComplaintEntry.database_table} AS entries
                    ON entries.id = versions.entry_id
            WHERE
                entries.entry_type = ANY(%(entry_types)s)
                AND versions.dtime IS NULL
                AND NOT versions.is_purged
                AND NOT entries.is_revoked
        """
        params: dict[str, DatabaseValue_s] = {
            "entry_types": const.ComplaintEntryType.measure_types(),
        }

        data = self.query_all(rs, query, params)
        entry_ids_to_version_ids = {e['entry_id']: e['version_id'] for e in data}
        entries = self._get_measures(rs, entry_ids_to_version_ids)

        entries = {e_id: e for e_id, e in entries.items() if e.is_active_measure}
        descriptions = self._get_descriptions(
            rs, entry_ids=entries.keys(), visible=True
        )
        return entries, descriptions

    def _get_measures(
        self, rs: RequestState, entry_ids_to_version_ids: dict[int, int]
    ) -> models.CdEDataclassMap[models.ComplaintEntry]:
        """Get relevant information on specified measures

        :returns: the associated entry versions, their descriptions, and
            some keys on the respective entries.
        """
        entry_data = {
            e["id"]: e
            for e in self.query_all(
                rs,
                *models.ComplaintEntry.get_select_query(
                    entry_ids_to_version_ids.keys(), entity_key="id"
                ),
            )
        }
        version_data = self.query_all(
            rs,
            *models.ComplaintEntryVersion.get_select_query(
                entry_ids_to_version_ids.values(), entity_key="id"
            ),
        )
        for v in version_data:
            entry_data[v["entry_id"]]["all_versions"] = [v]

        entries = models.ComplaintEntry.many_from_database(entry_data.values())
        return entries
