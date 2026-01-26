import datetime
import functools

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import CdEDBObject, PrivilegeError, get_hash, nearly_now, now
from cdedb.common.crypt import get_decrypt
from cdedb.common.exceptions import AdverseCompanionError
from cdedb.common.query import Query, QueryOperators, QueryScope
from tests.common import USER_DICT, BackendTest, as_users, execsql, storage
from tests.other_tests.test_validation import INVAL, TestValidationBase


class TestComplaintBackend(BackendTest):
    @functools.cached_property
    def LOG_OFFSET(self) -> int:
        return len(self.get_sample_data("complaint.log"))

    @as_users("simon")
    def test_get_case(self) -> None:
        expectation = models.Case(
            id=1,  # type: ignore[arg-type]
            kind=const.ComplaintKind.other_harassment,
            is_grave=False,
            summary="Jemand schnarcht ganz furchtbar.",
            start_date=datetime.date(2025, 5, 28),
            end_date=None,
            involved={
                const.ComplaintInvolvementType.affected: {4},
                const.ComplaintInvolvementType.target: {2},
            },
            informed_involved={4},
            companions={
                3: {2},
                7: {4},
            },
            withdrawn_companions={
                3: {2},
            },
            entries={
                1: models.ComplaintEntry(
                    id=1,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.generic_information,
                    parent_id=None,
                    concerned_id=None,
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=1,  # type: ignore[arg-type]
                            entry_id=1,  # type: ignore[arg-type]
                            length=146,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 14, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        ),
                    ],
                ),
                2: models.ComplaintEntry(
                    id=2,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.provisional_statement_given,
                    parent_id=None,
                    concerned_id=2,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=2,  # type: ignore[arg-type]
                            entry_id=2,  # type: ignore[arg-type]
                            length=258,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 14, tzinfo=datetime.timezone.utc
                            ),
                            attachment_hash="REDACTED:d28c1a205a1d",
                            attachment_title="Aussage von Charly",
                            attachment_filename="aussage_charly.pdf",
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        ),
                    ],
                ),
                3: models.ComplaintEntry(
                    id=3,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.statement_signed,
                    parent_id=2,  # type: ignore[arg-type]
                    concerned_id=None,
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=3,  # type: ignore[arg-type]
                            entry_id=3,  # type: ignore[arg-type]
                            length=None,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 15, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        ),
                    ],
                ),
                4: models.ComplaintEntry(
                    id=4,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement,
                    parent_id=None,
                    concerned_id=None,
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=4,  # type: ignore[arg-type]
                            entry_id=4,  # type: ignore[arg-type]
                            length=80,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            dtime=nearly_now(),
                            deleted_by=1,  # type: ignore[arg-type]
                            dreason="Ungünstige Wortwahl.",
                            authors={3},  # type: ignore[arg-type]
                        ),
                        models.ComplaintEntryVersion(
                            id=5,  # type: ignore[arg-type]
                            entry_id=4,  # type: ignore[arg-type]
                            length=77,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        ),
                    ],
                ),
                5: models.ComplaintEntry(
                    id=5,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement_measure,
                    parent_id=4,  # type: ignore[arg-type]
                    concerned_id=2,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=6,  # type: ignore[arg-type]
                            entry_id=5,  # type: ignore[arg-type]
                            length=53,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        ),
                    ],
                ),
                6: models.ComplaintEntry(
                    id=6,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement_measure,
                    parent_id=4,  # type: ignore[arg-type]
                    concerned_id=2,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=7,  # type: ignore[arg-type]
                            entry_id=6,  # type: ignore[arg-type]
                            length=26,
                            timestamp=datetime.datetime(
                                2025, 5, 31, 23, 6, 25, tzinfo=datetime.timezone.utc
                            ),
                            etime=datetime.datetime(
                                2025, 6, 8, 6, 6, 25, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        )
                    ],
                ),
                7: models.ComplaintEntry(
                    id=7,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement_measure,
                    parent_id=4,  # type: ignore[arg-type]
                    concerned_id=2,  # type: ignore[arg-type]
                    is_revoked=True,
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=8,  # type: ignore[arg-type]
                            entry_id=7,  # type: ignore[arg-type]
                            length=91,
                            timestamp=datetime.datetime(
                                2025, 6, 9, 12, 0, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={42},  # type: ignore[arg-type]
                        )
                    ],
                ),
                8: models.ComplaintEntry(
                    id=8,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.revocation_explanation,
                    parent_id=7,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=9,  # type: ignore[arg-type]
                            entry_id=8,  # type: ignore[arg-type]
                            length=68,
                            timestamp=datetime.datetime(
                                2025, 6, 10, 12, 0, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            authors={3},  # type: ignore[arg-type]
                        )
                    ],
                ),
                9: models.ComplaintEntry(
                    id=vtypes.ID(9),
                    case_id=vtypes.ID(1),
                    entry_type=const.ComplaintEntryType.agreement_measure,
                    parent_id=vtypes.ID(4),
                    concerned_id=vtypes.CdedbID(vtypes.ID(2)),
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=vtypes.ID(10),
                            entry_id=vtypes.ID(9),
                            length=33,
                            timestamp=datetime.datetime(
                                3000, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=vtypes.ID(1),
                            authors={3},  # type: ignore[arg-type]
                        )
                    ],
                ),
            },
        )
        reality = self.complaint.get_case(self.key, 1)
        for expected_entry, real_entry in zip(
            expectation.entries.values(), reality.entries.values()
        ):
            for expected_version, real_version in zip(
                expected_entry.all_versions, real_entry.all_versions
            ):
                self.assertEqual(expected_version.as_dict(), real_version.as_dict())
                self.assertEqual(expected_version, real_version)
            self.assertEqual(expected_entry.as_dict(), real_entry.as_dict())
            self.assertEqual(expected_entry, real_entry)
        self.assertEqual(expectation.as_dict(), reality.as_dict())
        self.assertEqual(expectation, reality)

        self.assertEqual({1, 2, 3, 4, 7, 42}, reality.get_persona_ids(tuple()))
        self.assertEqual({2, 4}, reality.all_involved.keys())
        self.assertEqual({2: {3}, 4: {7}}, reality.companions_by_involved)
        self.assertEqual({2: {3}}, reality.withdrawn_companions_by_involved)
        self.assertEqual({7: {4}}, reality.active_companions)

    @as_users("simon")
    def test_set_case(self) -> None:
        case_id = 1
        case_data = self.complaint.get_case(self.key, case_id).as_dict()
        case_update = {
            "is_grave": True,
            "end_date": datetime.date.today(),
        }
        self.assertLess(0, self.complaint.set_case(self.key, case_id, case_update))
        case_data |= case_update
        self.assertEqual(
            case_data, self.complaint.get_case(self.key, case_id).as_dict()
        )
        case_update = {
            "summary": "Da war eigentlich gar nix.",
            "start_date": None,
        }
        self.assertLess(0, self.complaint.set_case(self.key, case_id, case_update))
        self.assertEqual(
            case_data | case_update,
            self.complaint.get_case(self.key, case_id).as_dict(),
        )
        log_expectation = [
            {
                "code": const.ComplaintLogCodes.case_changed_grave,
                "change_note": "Ist jetzt schwerwiegend.",
            },
            {
                "code": const.ComplaintLogCodes.case_changed_end_date,
                "change_note": f"Hinzugefügt ({datetime.date.today().strftime('%d.%m.%Y')})",
            },
            {
                "code": const.ComplaintLogCodes.case_changed_summary,
                "change_note": "Jemand schnarcht ganz furchtbar. -> Da war eigentlich gar nix.",
            },
            {
                "code": const.ComplaintLogCodes.case_changed_start_date,
                "change_note": "Entfernt (28.05.2025)",
            },
        ]
        self.assertLogEqual(
            log_expectation, "complaint", case_id=case_id, offset=self.LOG_OFFSET
        )

    @as_users("simon")
    def test_create_case(self) -> None:
        new_case_data: CdEDBObject = {
            "kind": const.ComplaintKind.mobbing.value,
            "is_grave": False,
            "summary": "<REDACTED> hat jemandem Kaugummi in die Haare geklebt.",
        }
        new_case = self.complaint.create_case(self.key, new_case_data)
        expectation = models.Case(
            id=new_case.id,
            **new_case_data,
            entries={},
            involved={},
            informed_involved=set(),
            companions={},
            withdrawn_companions={},
        )
        self.assertEqual(expectation.as_dict(), new_case.as_dict())
        self.assertEqual(expectation, new_case)
        log_expectation = [
            {
                "code": const.ComplaintLogCodes.case_created,
            }
        ]
        self.assertLogEqual(
            log_expectation,
            "complaint",
            case_id=new_case.id,
            case_id_include_empty="IncludeEmpty.no",
        )

    @as_users("simon")
    def test_add_entry(self) -> None:
        case_id = 1
        new_entry_data: CdEDBObject = {
            "entry_type": const.ComplaintEntryType.provisional_statement_given,
            "concerned_id": 2,
        }
        new_version_data: CdEDBObject = {
            "description": "Ich hab auch etwas zu sagen!",
            "timestamp": now(),
            "authors": [3],
        }
        new_entry_id = self.complaint.add_entry(
            self.key, case_id, new_entry_data, new_version_data
        )
        case = self.complaint.get_case(self.key, case_id)
        expectation = models.ComplaintEntry(
            id=new_entry_id,  # type: ignore[arg-type]
            case_id=case_id,  # type: ignore[arg-type]
            **new_entry_data,
            all_versions=[
                models.ComplaintEntryVersion(
                    id=1001,  # type: ignore[arg-type]
                    entry_id=new_entry_id,  # type: ignore[arg-type]
                    timestamp=new_version_data["timestamp"],
                    length=len(new_version_data["description"]),
                    ctime=nearly_now(),
                    submitted_by=self.user['id'],
                    authors={3},  # type: ignore[arg-type]
                )
            ],
        )
        self.assertEqual(expectation.as_dict(), case.entries[new_entry_id].as_dict())
        self.assertEqual(expectation, case.entries[new_entry_id])
        self.assertLogEqual([], "complaint", case_id=case_id, offset=self.LOG_OFFSET)

    @as_users("simon")
    def test_replace_entry(self) -> None:
        case_id = 1
        entry_id = 3
        original_case = self.complaint.get_case(self.key, case_id)
        new_version_data: CdEDBObject = {
            "timestamp": now(),
            "authors": {3},
        }
        self.complaint.replace_entry_version(
            self.key, entry_id, new_version_data, "Zeitpunkt aktualisiert."
        )

        replaced_entry = original_case.entries[entry_id]
        assert replaced_entry.active_version is not None
        replaced_entry.active_version.dreason = "Zeitpunkt aktualisiert."
        replaced_entry.active_version.dtime = nearly_now()
        replaced_entry.active_version.deleted_by = self.user['id']
        replaced_entry.all_versions.append(
            models.ComplaintEntryVersion(
                id=1001,  # type: ignore[arg-type]
                entry_id=entry_id,  # type: ignore[arg-type]
                **new_version_data,
                ctime=nearly_now(),
                submitted_by=self.user['id'],
            )
        )
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(replaced_entry.as_dict(), case.entries[entry_id].as_dict())
        self.assertEqual(replaced_entry, case.entries[entry_id])

        self.assertLogEqual([], "complaint", case_id=case_id, offset=self.LOG_OFFSET)

    @as_users("simon")
    def test_delete_entry(self) -> None:
        case_id = 1
        entry_id = 3

        original_case = self.complaint.get_case(self.key, case_id)

        self.complaint.delete_entry(self.key, entry_id, "Vertippt.")

        deleted_entry = original_case.entries[entry_id]
        assert deleted_entry.active_version is not None
        deleted_entry.active_version.dreason = "Vertippt."
        deleted_entry.active_version.dtime = nearly_now()
        deleted_entry.active_version.deleted_by = self.user['id']

        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(deleted_entry.as_dict(), case.entries[entry_id].as_dict())
        self.assertEqual(deleted_entry, case.entries[entry_id])
        self.assertLogEqual([], "complaint", case_id=case_id, offset=self.LOG_OFFSET)

    @as_users("simon")
    def test_add_remove_involved(self) -> None:
        case_id = 1
        new_involved = 1
        _case = self.complaint.get_case(self.key, case_id)
        original_involved = sorted(
            _case.involved[const.ComplaintInvolvementType.target]
        )[0]
        original_companions = sorted(_case.companions_by_involved[original_involved])
        self.assertNotIn(
            new_involved, _case.all_involved, "Sample data changed. Review test setup."
        )

        original_case = self.complaint.get_case(self.key, case_id)
        expectation = self.complaint.get_case(self.key, case_id)

        # Adding an empty list does nothing.
        self.assertEqual(
            0,
            self.complaint.add_involved(
                self.key, case_id, const.ComplaintInvolvementType.target, []
            ),
        )
        # Add a new involved as a target.
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id=case_id,
                involved_type=const.ComplaintInvolvementType.target,
                persona_ids=[new_involved],
            ),
        )
        # Adding them again is a noop.
        self.assertEqual(
            -1,
            self.complaint.add_involved(
                self.key,
                case_id=case_id,
                involved_type=const.ComplaintInvolvementType.target,
                persona_ids=[new_involved],
            ),
        )

        # Check that new target shows up in the case.
        case = self.complaint.get_case(self.key, case_id)
        expectation.involved.setdefault(
            const.ComplaintInvolvementType.target, set()
        ).add(new_involved)

        self.assertEqual(expectation.as_dict(), case.as_dict())
        self.assertEqual(expectation, case)

        self.assertLessEqual(
            1,
            self.complaint.set_involved_informed(self.key, case_id, new_involved, True),
        )
        # Set them as uninformed.
        self.assertLessEqual(
            1,
            self.complaint.set_involved_informed(
                self.key, case_id, new_involved, False
            ),
        )

        # Removing noone does nothing.
        self.assertEqual(0, self.complaint.remove_involved(self.key, case_id, []))
        # Removing the new involved works.
        self.assertLessEqual(
            1, self.complaint.remove_involved(self.key, case_id, [new_involved])
        )
        # But doing it again is a noop.
        self.assertEqual(
            -1, self.complaint.remove_involved(self.key, case_id, [new_involved])
        )

        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(original_case.as_dict(), case.as_dict())
        self.assertEqual(original_case, case)

        # Adding the original involved as a new type removes and readds their companions.
        self.assertLessEqual(
            1,
            self.complaint.set_involved_informed(
                self.key, case_id, original_involved, True
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.other,
                [original_involved],
            ),
        )

        # Removing the original involved also removes their companions.
        self.assertLessEqual(
            1, self.complaint.remove_involved(self.key, case_id, [original_involved])
        )

        original_case.involved.pop(const.ComplaintInvolvementType.target)
        for companion_id in original_companions:
            original_case.companions[companion_id].remove(original_involved)
            if not original_case.companions[companion_id]:
                del original_case.companions[companion_id]  # pragma: no cover
            original_case.withdrawn_companions.pop(companion_id, None)
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(original_case.as_dict(), case.as_dict())
        self.assertEqual(original_case, case)

        log_expectation: list[CdEDBObject] = [
            {
                "code": const.ComplaintLogCodes.involved_added,
                "change_note": "Zielpersonen",
                "persona_id": new_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_informed,
                "persona_id": new_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_uninformed,
                "persona_id": new_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_removed,
                "change_note": "Zielpersonen",
                "persona_id": new_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_informed,
                "persona_id": original_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_removed,
                "change_note": "Zielpersonen",
                "persona_id": original_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_uninformed,
                "persona_id": original_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_added,
                "change_note": "Sonstige",
                "persona_id": original_involved,
            },
            {
                "code": const.ComplaintLogCodes.involved_removed,
                "change_note": "Sonstige",
                "persona_id": original_involved,
            },
            *[
                {
                    "code": const.ComplaintLogCodes.companion_removed,
                    "persona_id": original_involved,
                    "companion_id": companion_id,
                }
                for companion_id in original_companions
            ],
        ]
        self.assertLogEqual(
            log_expectation, "complaint", case_id=case_id, offset=self.LOG_OFFSET
        )

    @as_users("simon")
    def test_add_remove_companions(self) -> None:
        case_id = 1
        _case = self.complaint.get_case(self.key, case_id)
        persona_id = 2
        old_companion = list(_case.companions_by_involved[persona_id])[0]
        new_companion = 5
        self.assertNotIn(
            new_companion, _case.companions, "Sample data changed, review test setup."
        )

        original_case = self.complaint.get_case(self.key, case_id)

        self.assertEqual(
            0, self.complaint.add_companions(self.key, case_id, persona_id, [])
        )
        self.assertEqual(
            -1,
            self.complaint.add_companions(
                self.key, case_id, persona_id, [old_companion]
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_companions(
                self.key, case_id, persona_id, [new_companion]
            ),
        )

        original_case.companions[5] = {2}
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(original_case.as_dict(), case.as_dict())
        self.assertEqual(original_case, case)

        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, persona_id, new_companion, True
            ),
        )
        self.assertEqual(
            -1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, persona_id, new_companion, True
            ),
        )

        original_case.withdrawn_companions.setdefault(new_companion, set()).add(
            persona_id
        )
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(original_case.as_dict(), case.as_dict())
        self.assertEqual(original_case, case)

        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, persona_id, new_companion, False
            ),
        )

        self.assertEqual(
            0, self.complaint.remove_companions(self.key, case_id, persona_id, [])
        )
        self.assertLessEqual(
            1,
            self.complaint.remove_companions(
                self.key, case_id, persona_id, [new_companion]
            ),
        )
        self.assertEqual(
            -1,
            self.complaint.remove_companions(
                self.key, case_id, persona_id, [new_companion]
            ),
        )

        log_expectation = [
            {
                "code": const.ComplaintLogCodes.companion_added,
                "persona_id": persona_id,
                "companion_id": new_companion,
            },
            {
                "code": const.ComplaintLogCodes.companion_withdrawn,
                "persona_id": persona_id,
                "companion_id": new_companion,
            },
            {
                "code": const.ComplaintLogCodes.companion_reinstated,
                "persona_id": persona_id,
                "companion_id": new_companion,
            },
            {
                "code": const.ComplaintLogCodes.companion_removed,
                "persona_id": persona_id,
                "companion_id": new_companion,
            },
        ]
        self.assertLogEqual(
            log_expectation, "complaint", case_id=case_id, offset=self.LOG_OFFSET
        )

    @as_users("simon")
    def test_lock_unlock_case(self) -> None:
        case_id = 1
        self.assertIsNone(self.complaint.is_unlocked(self.key, case_id))
        self.assertTrue(self.complaint.unlock_case(self.key, case_id, "Why not?"))
        self.assertIs(True, self.complaint.is_unlocked(self.key, case_id))
        self.assertEqual(1, self.complaint.lock_case(self.key, case_id))
        self.assertEqual(-1, self.complaint.lock_case(self.key, case_id))
        self.assertIsNone(self.complaint.is_unlocked(self.key, case_id))

        execsql(
            f"""
            INSERT INTO {models.AccessLog.database_table} (case_id, persona_id, ctime)
            VALUES ({case_id}, {self.user['id']}, '{now() - datetime.timedelta(hours=1)}')
        """,
            verbose=1,
        )
        self.assertIs(False, self.complaint.is_unlocked(self.key, case_id))
        self.assertTrue(self.complaint.unlock_case(self.key, case_id, "Once more."))

        log_expectation: list[CdEDBObject] = [
            {
                "code": const.ComplaintLogCodes.case_unlocked,
                "change_note": "Why not?",
            },
            {
                "code": const.ComplaintLogCodes.case_unlocked,
                "change_note": "Once more.",
            },
        ]
        self.assertLogEqual(
            log_expectation, "complaint", case_id=case_id, offset=self.LOG_OFFSET
        )

    @as_users("simon")
    def test_query(self) -> None:
        case_id = 1
        scope = QueryScope.complaint_case
        query = Query(
            scope=scope,
            spec=scope.get_spec(),
            fields_of_interest=["cases.id", "cases.summary"],
            constraints=[
                (
                    "entries.entry_type",
                    QueryOperators.oneof,
                    [
                        const.ComplaintEntryType.agreement_measure,
                        const.ComplaintEntryType.definite_measure,
                        const.ComplaintEntryType.provisional_measure,
                    ],
                ),
            ],
            order=[],
        )
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(1, len(result))
        self.assertEqual(case_id, result[0]["cases.id"])

        query.constraints = [
            ("companion.companion_persona_id", QueryOperators.equal, 3),
            ("companion.is_withdrawn", QueryOperators.equal, True),
            ("involved.persona_id", QueryOperators.equal, 2),
        ]
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(1, len(result))
        self.assertEqual(case_id, result[0]["cases.id"])

        self.complaint.set_companion_withdrawn(self.key, case_id, 2, 3, False)
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(0, len(result))

        query.constraints = [
            (
                "entries.concerned_id,authors.persona_id,involved.persona_id,companion.companion_persona_id",
                QueryOperators.equal,
                2,
            ),
        ]
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(1, len(result))
        self.assertEqual(case_id, result[0]["cases.id"])

        query.constraints = [
            (
                "entries.concerned_id,authors.persona_id,involved.persona_id,companion.companion_persona_id",
                QueryOperators.equal,
                1,
            ),
        ]
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(0, len(result))

        self.complaint.add_involved(
            self.key, case_id, const.ComplaintInvolvementType.appellant, [1]
        )
        result = self.complaint.submit_general_query(self.key, query)
        self.assertEqual(1, len(result))
        self.assertEqual(case_id, result[0]["cases.id"])

    @as_users("simon")
    def test_revoke_entry(self) -> None:
        case_id = 1
        entry_id = 5
        revocation_type = const.ComplaintEntryType.revocation_explanation

        expectation = self.complaint.get_case(self.key, case_id)

        # Revoke an entry.
        revoke_data: CdEDBObject = {
            "timestamp": now(),
            "description": "Oops!... I Did It Again",
            "authors": {3},
        }
        new_entry_id = self.complaint.revoke_entry(self.key, entry_id, revoke_data)
        self.assertLessEqual(1, new_entry_id)

        with self.assertRaisesRegex(ValueError, "Entry already revoked."):
            self.complaint.revoke_entry(self.key, entry_id, revoke_data)

        # Check the result.
        expectation.entries[entry_id].is_revoked = True
        expectation.entries[new_entry_id] = models.ComplaintEntry(
            id=new_entry_id,  # type: ignore[arg-type]
            case_id=case_id,  # type: ignore[arg-type]
            entry_type=revocation_type,
            parent_id=entry_id,  # type: ignore[arg-type]
            all_versions=[
                models.ComplaintEntryVersion(
                    id=1001,  # type: ignore[arg-type]
                    entry_id=new_entry_id,  # type: ignore[arg-type]
                    length=len(revoke_data["description"]),
                    ctime=nearly_now(),
                    submitted_by=self.user['id'],
                    authors=revoke_data["authors"],
                    timestamp=revoke_data["timestamp"],
                ),
            ],
        )
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(expectation.as_dict(), case.as_dict())
        self.assertEqual(expectation, case)

        # Revoke the revocation.
        new_new_entry_id = self.complaint.revoke_entry(
            self.key, new_entry_id, revoke_data
        )
        self.assertLessEqual(1, new_new_entry_id)

        with self.assertRaisesRegex(ValueError, "Cannot chain revoke."):
            self.complaint.revoke_entry(self.key, new_new_entry_id, revoke_data)

        # Check the result.
        expectation.entries[entry_id].is_revoked = False
        expectation.entries[new_entry_id].is_revoked = True
        expectation.entries[new_new_entry_id] = models.ComplaintEntry(
            id=new_new_entry_id,  # type: ignore[arg-type]
            case_id=case_id,  # type: ignore[arg-type]
            entry_type=revocation_type,
            parent_id=new_entry_id,  # type: ignore[arg-type]
            all_versions=[
                models.ComplaintEntryVersion(
                    id=1002,  # type: ignore[arg-type]
                    entry_id=new_new_entry_id,  # type: ignore[arg-type]
                    length=len(revoke_data["description"]),
                    ctime=nearly_now(),
                    submitted_by=self.user['id'],
                    authors=revoke_data["authors"],
                    timestamp=revoke_data["timestamp"],
                )
            ],
        )
        case = self.complaint.get_case(self.key, case_id)
        self.assertEqual(expectation.as_dict(), case.as_dict())
        self.assertEqual(expectation, case)

        self.assertLogEqual([], "complaint", case_id=case_id, offset=self.LOG_OFFSET)

    @as_users("simon")
    def test_adverse_companions(self) -> None:
        case_id = 1

        case = self.complaint.get_case(self.key, case_id)

        target_id = list(case.involved[const.ComplaintInvolvementType.target])[0]
        target_companion_id = list(case.companions_by_involved[target_id])[0]
        affected_id = list(case.involved[const.ComplaintInvolvementType.affected])[0]
        affected_companion_id = list(case.companions_by_involved[affected_id])[0]
        appellant_id = 5
        appellant_companion_id = 6

        self.assertEqual(
            6,
            len({
                target_id,
                target_companion_id,
                affected_id,
                affected_companion_id,
                appellant_id,
                appellant_companion_id,
            }),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.appellant,
                [appellant_id],
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_companions(
                self.key, case_id, appellant_id, [appellant_companion_id]
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, target_id, target_companion_id, False
            ),
        )

        with self.assertRaises(AdverseCompanionError):
            self.complaint.add_companions(
                self.key, case_id, target_id, [affected_companion_id]
            )
        with self.assertRaises(AdverseCompanionError):
            self.complaint.add_companions(
                self.key, case_id, target_id, [appellant_companion_id]
            )
        with self.assertRaises(AdverseCompanionError):
            self.complaint.add_companions(
                self.key, case_id, affected_id, [target_companion_id]
            )
        with self.assertRaises(AdverseCompanionError):
            self.complaint.add_companions(
                self.key, case_id, appellant_id, [target_companion_id]
            )

        # Adding an involved persona as another type migrates their companions so it also doesn't work.
        self.assertLessEqual(
            1,
            self.complaint.add_companions(
                self.key, case_id, appellant_id, [affected_companion_id]
            ),
        )
        with self.assertRaises(AdverseCompanionError):
            self.complaint.add_involved(
                self.key, case_id, const.ComplaintInvolvementType.target, [affected_id]
            )
        self.assertLessEqual(
            1,
            self.complaint.remove_companions(
                self.key, case_id, appellant_id, [affected_companion_id]
            ),
        )

        with self.assertRaisesRegex(ValueError, "Involved companion."):
            self.complaint.add_companions(self.key, case_id, target_id, [target_id])
        with self.assertRaisesRegex(ValueError, "Involved companion."):
            self.complaint.add_companions(self.key, case_id, affected_id, [affected_id])
        with self.assertRaisesRegex(ValueError, "Involved companion."):
            self.complaint.add_companions(
                self.key, case_id, appellant_id, [appellant_id]
            )

        with self.assertRaisesRegex(ValueError, "Already active companions."):
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.target,
                [target_companion_id],
            )
        with self.assertRaisesRegex(ValueError, "Already active companions."):
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.affected,
                [affected_companion_id],
            )
        with self.assertRaisesRegex(ValueError, "Already active companions."):
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.appellant,
                [appellant_companion_id],
            )

        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, target_id, target_companion_id, True
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.target,
                [target_companion_id],
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, affected_id, affected_companion_id, True
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.affected,
                [affected_companion_id],
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.set_companion_withdrawn(
                self.key, case_id, appellant_id, appellant_companion_id, True
            ),
        )
        self.assertLessEqual(
            1,
            self.complaint.add_involved(
                self.key,
                case_id,
                const.ComplaintInvolvementType.appellant,
                [appellant_companion_id],
            ),
        )

        log_expecation: list[CdEDBObject] = [
            {
                "code": const.ComplaintLogCodes.involved_added,
                "persona_id": appellant_id,
                "change_note": "Beschwerdeführer",
            },
            {
                "code": const.ComplaintLogCodes.involved_informed,
                "persona_id": appellant_id,
            },
            {
                "code": const.ComplaintLogCodes.companion_added,
                "persona_id": appellant_id,
                "companion_id": appellant_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.companion_reinstated,
                "persona_id": target_id,
                "companion_id": target_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.companion_added,
                "persona_id": appellant_id,
                "companion_id": affected_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.companion_removed,
                "persona_id": appellant_id,
                "companion_id": affected_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.companion_withdrawn,
                "persona_id": target_id,
                "companion_id": target_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.involved_added,
                "persona_id": target_companion_id,
                "change_note": "Zielpersonen",
            },
            {
                "code": const.ComplaintLogCodes.companion_withdrawn,
                "persona_id": affected_id,
                "companion_id": affected_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.involved_added,
                "persona_id": affected_companion_id,
                "change_note": "Betroffene",
            },
            {
                "code": const.ComplaintLogCodes.companion_withdrawn,
                "persona_id": appellant_id,
                "companion_id": appellant_companion_id,
            },
            {
                "code": const.ComplaintLogCodes.involved_added,
                "persona_id": appellant_companion_id,
                "change_note": "Beschwerdeführer",
            },
            {
                "code": const.ComplaintLogCodes.involved_informed,
                "persona_id": appellant_companion_id,
            },
        ]
        self.assertLogEqual(
            log_expecation, "complaint", case_id=case_id, offset=self.LOG_OFFSET
        )

    @as_users("simon", "janis")
    def test_user_measures(self) -> None:
        case_id = 1
        active_measure_entry_id = 5
        active_measure_persona_id = 2

        self.assertEqual(
            set(), self.complaint.list_user_measures(self.key, 3, is_active=None)
        )
        self.assertEqual(
            set(), self.complaint.list_user_measures(self.key, 4, is_active=None)
        )
        self.assertEqual(
            set(), self.complaint.list_user_measures(self.key, 7, is_active=None)
        )
        self.assertEqual(
            {7, 10}, self.complaint.list_user_measures(self.key, 2, is_active=False)
        )

        with self.switch_user("simon"):
            case = self.complaint.get_case(self.key, case_id)
        measure = case.entries[active_measure_entry_id].active_version
        assert measure is not None
        self.assertEqual(
            {measure.id},
            self.complaint.list_user_measures(self.key, active_measure_persona_id),
        )

        revoke_data: CdEDBObject = {
            "timestamp": now(),
            "description": "Oops!... I Did It Again",
            "authors": {3},
        }
        with self.switch_user("simon"):
            self.complaint.revoke_entry(self.key, active_measure_entry_id, revoke_data)

        self.assertEqual(
            set(),
            self.complaint.list_user_measures(
                self.key, active_measure_persona_id, is_active=True
            ),
        )

        with self.switch_user("simon"):
            case = self.complaint.get_case(self.key, case_id)
        measure = case.entries[active_measure_entry_id].active_version
        assert measure is not None
        self.assertEqual(
            {7, 10},
            self.complaint.list_user_measures(
                self.key, active_measure_persona_id, is_active=False
            ),
        )

    @as_users("berta")
    def test_user_measures_unprivileged(self) -> None:
        measure_entry_id = 6
        measure_persona_id = 2
        # access own measures
        self.assertEqual(
            {measure_entry_id},
            self.complaint.list_user_measures(self.key, measure_persona_id),
        )

        measures, descriptions, entries = self.complaint.get_measures(
            self.key, {measure_entry_id}
        )
        self.assertEqual({measure_entry_id}, measures.keys())
        self.assertEqual({measure_entry_id}, descriptions.keys())
        self.assertEqual({measures[measure_entry_id].entry_id}, entries.keys())

        with self.assertRaises(PrivilegeError):
            self.complaint.list_measures(self.key)

        # non-affected user
        with self.switch_user("inga"):
            with self.assertRaises(PrivilegeError):
                self.complaint.list_user_measures(self.key, measure_persona_id)
            with self.assertRaises(PrivilegeError):
                self.complaint.get_measures(self.key, {measure_entry_id})

    @as_users("simon", "janis")
    def test_measures(self) -> None:
        measure_ids_expectation = {6: 1}
        self.assertEqual(
            measure_ids_expectation,
            self.complaint.list_measures(self.key),
        )

        measures_expectation = {
            6: models.ComplaintEntryVersion(
                id=6,  # type: ignore[arg-type]
                entry_id=5,  # type: ignore[arg-type]
                length=53,
                ctime=nearly_now(),
                submitted_by=1,  # type: ignore[arg-type]
                authors={3},  # type: ignore[arg-type]
                timestamp=datetime.datetime(
                    2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                ),
            ),
        }
        descriptions_expectation = {
            6: "Berta muss bei Anmeldung ein Einzelzimmer beantragen.",
        }
        entries_expectation = {
            5: {
                "case_id": 1,
                "concerned_id": 2,
                "entry_type": const.ComplaintEntryType.agreement_measure,
                "id": 5,
                "is_revoked": False,
            }
        }
        self.assertEqual(
            (measures_expectation, descriptions_expectation, entries_expectation),
            self.complaint.get_measures(
                self.key, self.complaint.list_measures(self.key)
            ),
        )

    @as_users("simon")
    def test_enforcers(self) -> None:
        janis_id = USER_DICT['janis']['id']
        kalif_id = USER_DICT['kalif']['id']
        self.assertEqual({janis_id}, self.complaint.list_enforcers(self.key))

        self.assertEqual(1001, self.complaint.add_enforcer(self.key, kalif_id))
        self.assertEqual(-1, self.complaint.add_enforcer(self.key, kalif_id))

        self.assertEqual({janis_id, kalif_id}, self.complaint.list_enforcers(self.key))

        self.assertEqual(1, self.complaint.remove_enforcer(self.key, janis_id))
        self.assertEqual(-1, self.complaint.remove_enforcer(self.key, janis_id))

    @as_users("simon")
    @storage
    def test_attachment_store(self) -> None:
        decrypt = get_decrypt(self.secrets["COMPLAINT_SECRET"])
        invalid_pdf = b"abc"
        with self.assertRaisesRegex(ValueError, "Only pdf allowed."):
            self.complaint.get_attachment_store(self.key).store(invalid_pdf)

        case_id, entry_id, version_nr = 1, 2, 1
        sample_attachment_content = (self.testfile_dir / "form.pdf").read_bytes()
        sample_attachment_hash = self.get_sample_datum(
            models.ComplaintEntryVersion.database_table,
            entry_id,
        )["attachment_hash"]
        self.assertEqual(
            get_hash(sample_attachment_content),
            sample_attachment_hash,
        )
        self.assertEqual(
            sample_attachment_content,
            self.complaint.get_attachment_store(self.key).get(sample_attachment_hash),
        )
        with self.assertRaises(PrivilegeError):
            self.complaint.retrieve_attachment(self.key, entry_id, version_nr)

        self.complaint.unlock_case(self.key, case_id, "testing")
        self.assertEqual(
            sample_attachment_content,
            self.complaint.retrieve_attachment(self.key, entry_id, version_nr),
        )

        valid_pdf = (self.testfile_dir / "rechen.pdf").read_bytes()
        attachment_hash = self.complaint.get_attachment_store(self.key).store(valid_pdf)
        self.assertEqual(
            valid_pdf,
            self.complaint.get_attachment_store(self.key).get(attachment_hash),
        )
        encrypted = (
            self.complaint
            .get_attachment_store(self.key)
            .get_path(attachment_hash)
            .read_bytes()
        )
        self.assertNotEqual(valid_pdf, encrypted)
        self.assertEqual(valid_pdf, decrypt(encrypted))
        self.complaint.get_attachment_store(self.key).store(valid_pdf)
        new_encrypted = (
            self.complaint
            .get_attachment_store(self.key)
            .get_path(attachment_hash)
            .read_bytes()
        )
        self.assertNotEqual(encrypted, new_encrypted)
        self.assertEqual(valid_pdf, decrypt(new_encrypted))

        case_id = 1
        entry_data = {
            "entry_type": const.ComplaintEntryType.provisional_statement_given,
            "concerned_id": 2,
        }
        version_data = {
            "description": "Test",
            "timestamp": now(),
            "authors": [1],
            "attachment_hash": "abc",
            "attachment_title": "Test",
            "attachment_filename": "test.pdf",
        }
        with self.assertRaisesRegex(RuntimeError, "File has been lost."):
            self.complaint.add_entry(self.key, case_id, entry_data, version_data)
        version_data["attachment_hash"] = attachment_hash
        self.complaint.add_entry(self.key, case_id, entry_data, version_data)

        self.assertTrue(
            self.complaint.get_attachment_store(self.key).forget_one(
                self.key, lambda rs, attachment_hash: False, attachment_hash
            )
        )
        self.assertIsNone(
            self.complaint.get_attachment_store(self.key).get(attachment_hash)
        )
        self.assertFalse(
            self.complaint.get_attachment_store(self.key).is_available(attachment_hash)
        )


class TestComplaintValidation(TestValidationBase):
    def test_case(self) -> None:
        # Test successful creations.
        self.do_validator_test(
            models.Case,
            [
                (
                    {
                        "kind": const.ComplaintKind.other_harassment,
                        "is_grave": False,
                        "summary": "<REDACTED> schnarcht.",
                        "start_date": datetime.date(2025, 5, 28),
                    },
                    INVAL,
                    None,
                ),
                (
                    {
                        "kind": const.ComplaintKind.mobbing.value,
                        "is_grave": False,
                        "summary": "<REDACTED> hat jemandem Kaugummi in die Haare geklebt.",
                    },
                    INVAL,
                    None,
                ),
                (
                    {
                        "kind": const.ComplaintKind.volunteer_harassment,
                        "is_grave": False,
                        "summary": "<REDACTED> hat mal wieder einen halben Roman in die Orga-Notizen geschrieben.",
                        "start_date": datetime.date.today(),
                        "end_date": datetime.date.today(),
                    },
                    INVAL,
                    None,
                ),
                (
                    {
                        "kind": str(const.ComplaintKind.verbal_abuse),
                        "is_grave": False,
                        "summary": "<REDACTED> hat Kursteilys angeschriehen.",
                        "end_date": datetime.date.today(),
                    },
                    {
                        "kind": const.ComplaintKind.verbal_abuse,
                        "is_grave": False,
                        "summary": "<REDACTED> hat Kursteilys angeschriehen.",
                        "end_date": datetime.date.today(),
                    },
                    None,
                ),
            ],
            {"creation": True},
        )
        # Test unsuccessful creations.
        self.do_validator_test(
            models.Case,
            [
                (
                    {
                        "summary": "<REDACTED> schnarcht.",
                        "is_grave": False,
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    None,
                    KeyError("Mandatory key missing. (kind)"),
                ),
                (
                    {
                        "kind": const.ComplaintKind.other_harassment,
                        "is_grave": False,
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    None,
                    KeyError("Mandatory key missing. (summary)"),
                ),
            ],
            {"creation": True},
        )
        # Test successful updates.
        self.do_validator_test(
            models.Case,
            [
                (
                    {"kind": const.ComplaintKind.volunteer_harassment},
                    INVAL,
                    None,
                ),
                (
                    {"summary": "<REDACTED> schnarcht."},
                    INVAL,
                    None,
                ),
                (
                    {"start_date": datetime.date.today()},
                    INVAL,
                    None,
                ),
                (
                    {"end_date": datetime.date.today()},
                    INVAL,
                    None,
                ),
                (
                    {
                        "kind": const.ComplaintKind.other_harassment,
                        "summary": "<REDACTED> schnarcht.",
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    INVAL,
                    None,
                ),
            ],
        )
        # Test unsuccessful updates.
        self.do_validator_test(
            models.Case,
            [
                (
                    {
                        "kind": 2**30,
                        "summary": "<REDACTED> schnarcht.",
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    None,
                    ValueError(
                        "Invalid input for the enumeration %(enum)s (kind)",
                        {'enum': const.ComplaintKind},
                    ),
                ),
                (
                    {
                        "kind": const.ComplaintKind.other_harassment,
                        "summary": "",
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    None,
                    ValueError("Must not be empty. (summary)"),
                ),
            ],
        )

    def test_entry(self) -> None:
        entries = {
            1: models.ComplaintEntry(
                id=1,  # type: ignore[arg-type]
                case_id=1,  # type: ignore[arg-type]
                entry_type=const.ComplaintEntryType.agreement,
                all_versions=[],
            ),
            2: models.ComplaintEntry(
                id=2,  # type: ignore[arg-type]
                case_id=1,  # type: ignore[arg-type]
                entry_type=const.ComplaintEntryType.provisional_statement_given,
                all_versions=[],
            ),
        }

        # These cannot be updated, so creation only.
        # Test successful creations.
        self.do_validator_test(
            models.ComplaintEntry,
            [
                (
                    {
                        "entry_type": str(const.ComplaintEntryType.generic_information),
                    },
                    {
                        "entry_type": const.ComplaintEntryType.generic_information,
                        "concerned_id": None,
                        "parent_id": None,
                    },
                    None,
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.provisional_statement_given.value,
                        "concerned_id": "DB-1-9",
                    },
                    {
                        "entry_type": const.ComplaintEntryType.provisional_statement_given,
                        "concerned_id": 1,
                        "parent_id": None,
                    },
                    None,
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.statement_signed,
                        "parent_id": 2,
                    },
                    {
                        "entry_type": const.ComplaintEntryType.statement_signed,
                        "parent_id": 2,
                        "concerned_id": None,
                    },
                    None,
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.agreement_measure,
                        "concerned_id": 1,
                        "parent_id": 1,
                    },
                    INVAL,
                    None,
                ),
            ],
            {"creation": True, "passthrough": True, "entries": entries},
        )
        # Test unsuccessful creations.
        self.do_validator_test(
            models.ComplaintEntry,
            [
                (
                    {
                        "entry_type": "bla",
                    },
                    None,
                    ValueError(
                        "Invalid input for the enumeration %(enum)s (entry_type)",
                        {'enum': const.ComplaintEntryType},
                    ),
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.agreement.name,
                    },
                    None,
                    ValueError(
                        "Invalid input for the enumeration %(enum)s (entry_type)",
                        {'enum': const.ComplaintEntryType},
                    ),
                ),
                (
                    {
                        "concerned_id": 1,
                        "parent_id": 1,
                    },
                    None,
                    KeyError("Mandatory key missing. (entry_type)"),
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.agreement,
                        "parent_id": 1,
                    },
                    None,
                    ValueError("Must be empty. (parent_id)"),
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.agreement,
                        "concerned_id": 1,
                    },
                    None,
                    ValueError("Must be empty. (concerned_id)"),
                ),
                (
                    {
                        "entry_type": const.ComplaintEntryType.definite_measure,
                        "concerned_id": 1,
                        "parent_id": 1,
                    },
                    None,
                    ValueError("Invalid parent type. (parent_id)"),
                ),
            ],
            {"creation": True, "passthrough": True, "entries": entries},
        )

    def test_entry_version(self) -> None:
        # Only creation allowed.
        # Test successful creation of entry version without description.
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": None,
                        "timestamp": "2025-05-30 22:25:00",
                        "authors": [1],
                    },
                    {
                        "description": None,
                        "timestamp": datetime.datetime(
                            2025, 5, 30, 20, 25, tzinfo=datetime.timezone.utc
                        ),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": None,
                        "attachment_title": None,
                        "attachment_filename": None,
                    },
                    None,
                ),
                (
                    {
                        "description": None,
                        "timestamp": now(),
                        "authors": [1, 2, 3],
                        "etime": None,
                        "attachment_hash": None,
                        "attachment_title": None,
                        "attachment_filename": None,
                    },
                    INVAL,
                    None,
                ),
                (
                    {
                        "timestamp": datetime.datetime(
                            2025, 5, 30, 22, 25, tzinfo=datetime.timezone.utc
                        ),
                        "authors": ["DB-1-9"],
                    },
                    {
                        "description": None,
                        "timestamp": datetime.datetime(
                            2025, 5, 30, 22, 25, tzinfo=datetime.timezone.utc
                        ),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": None,
                        "attachment_title": None,
                        "attachment_filename": None,
                    },
                    None,
                ),
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.statement_signed,
            },
        )
        # Test successful creation of entry version with expiration:
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "authors": [1],
                        "timestamp": "2025-05-30 22:25:00",
                        "etime": "2025-05-31 22:25:00",
                    },
                    {
                        "description": "Test.",
                        "authors": [1],
                        "timestamp": datetime.datetime(
                            2025, 5, 30, 20, 25, tzinfo=datetime.timezone.utc
                        ),
                        "etime": datetime.datetime(
                            2025, 5, 31, 20, 25, tzinfo=datetime.timezone.utc
                        ),
                        "attachment_hash": None,
                        "attachment_title": None,
                        "attachment_filename": None,
                    },
                    None,
                ),
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.definite_measure,
            },
        )
        # Test successful creation of entry version with description:
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": None,
                        "attachment_title": None,
                        "attachment_filename": None,
                    },
                    INVAL,
                    None,
                ),
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.generic_information,
            },
        )
        # Test successful creation of entry version with attachment:
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": get_hash(b"abc"),
                        "attachment_title": "Test",
                        "attachment_filename": "test.pdf",
                    },
                    INVAL,
                    None,
                )
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.provisional_statement_given,
            },
        )
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": get_hash(b"abc"),
                        "attachment_title": "Test",
                        "attachment_filename": "test.pdf",
                    },
                    INVAL,
                    None,
                )
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.generic_information,
            },
        )
        # Test creation of entry version with attachment with invalid entry type.
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": get_hash(b"abc"),
                        "attachment_title": "Test",
                        "attachment_filename": "test.pdf",
                    },
                    None,
                    ValueError("Must be empty. (attachment_hash)"),
                )
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.synthesis,
            },
        )
        # Test invalid input for entry version with attachment:
        self.do_validator_test(
            models.ComplaintEntryVersion,
            [
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": "",
                        "attachment_title": "Test",
                        "attachment_filename": "test.pdf",
                    },
                    None,
                    ValueError("Incomplete attachment. (attachment_hash)"),
                ),
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": get_hash(b"abc"),
                        "attachment_title": "",
                        "attachment_filename": "test.pdf",
                    },
                    None,
                    ValueError("Incomplete attachment. (attachment_title)"),
                ),
                (
                    {
                        "description": "Test.",
                        "timestamp": now(),
                        "authors": [1],
                        "etime": None,
                        "attachment_hash": get_hash(b"abc"),
                        "attachment_title": "Test",
                        "attachment_filename": "",
                    },
                    None,
                    ValueError("Incomplete attachment. (attachment_filename)"),
                ),
            ],
            {
                "creation": True,
                "passthrough": True,
                "entry_type": const.ComplaintEntryType.provisional_statement_given,
            },
        )
