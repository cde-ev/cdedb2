import datetime

import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import CdEDBObject, nearly_now
from tests.common import BackendTest, as_users
from tests.other_tests import TestValidation
from tests.other_tests.test_validation import INVAL


class TestComplaintBackend(BackendTest):
    @as_users("anton")
    def test_get_case(self) -> None:
        expectation = models.Case(
            id=1,  # type: ignore[arg-type]
            kind=const.ComplaintKind.other_harassment,
            is_grave=False,
            summary="Jemand schnarcht ganz furchtbar.",
            start_date=datetime.date(2025, 5, 28),
            end_date=None,
            entries={
                1: models.ComplaintEntry(
                    id=1,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.initial_information,
                    root_entry_id=None,
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
                            dtime=None,
                            deleted_by=None,
                            dreason=None,
                        ),
                    ],
                ),
                2: models.ComplaintEntry(
                    id=2,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.provisional_statement_given,
                    root_entry_id=None,
                    concerned_id=2,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=2,  # type: ignore[arg-type]
                            entry_id=2,  # type: ignore[arg-type]
                            length=258,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 14, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            dtime=None,
                            deleted_by=None,
                            dreason=None,
                        ),
                    ],
                ),
                3: models.ComplaintEntry(
                    id=3,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.statement_signed,
                    root_entry_id=2,  # type: ignore[arg-type]
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
                            dtime=None,
                            deleted_by=None,
                            dreason=None,
                        ),
                    ],
                ),
                4: models.ComplaintEntry(
                    id=4,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement,
                    root_entry_id=None,
                    concerned_id=None,
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=4,  # type: ignore[arg-type]
                            entry_id=4,  # type: ignore[arg-type]
                            length=77,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            dtime=None,
                            deleted_by=None,
                            dreason=None,
                        ),
                    ],
                ),
                5: models.ComplaintEntry(
                    id=5,  # type: ignore[arg-type]
                    case_id=1,  # type: ignore[arg-type]
                    entry_type=const.ComplaintEntryType.agreement_measure,
                    root_entry_id=4,  # type: ignore[arg-type]
                    concerned_id=2,  # type: ignore[arg-type]
                    all_versions=[
                        models.ComplaintEntryVersion(
                            id=5,  # type: ignore[arg-type]
                            entry_id=5,  # type: ignore[arg-type]
                            length=None,
                            timestamp=datetime.datetime(
                                2025, 5, 28, 16, tzinfo=datetime.timezone.utc
                            ),
                            ctime=nearly_now(),
                            submitted_by=1,  # type: ignore[arg-type]
                            dtime=None,
                            deleted_by=None,
                            dreason=None,
                        ),
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

    @as_users("anton")
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
        self.assertLogEqual(log_expectation, "complaint", case_id=case_id)

    @as_users("anton")
    def test_create_case(self) -> None:
        new_case_data: CdEDBObject = {
            "kind": const.ComplaintKind.mobbing.value,
            "is_grave": False,
            "summary": "<REDACTED> hat jemandem Kaugummi in die Haare geklebt.",
        }
        new_case = self.complaint.create_case(self.key, new_case_data)
        expectation = models.Case(id=new_case.id, **new_case_data, entries={})
        self.assertEqual(expectation.as_dict(), new_case.as_dict())
        self.assertEqual(expectation, new_case)
        log_expectation = [
            {
                "code": const.ComplaintLogCodes.case_created,
            }
        ]
        self.assertLogEqual(log_expectation, "complaint", case_id=new_case.id)


class TestComplaintValidation(TestValidation):
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
                        "summary": "<REDACTED> schnarcht.",
                        "start_date": datetime.date(2025, 5, 28),
                        "end_date": datetime.date(2025, 5, 29),
                    },
                    None,
                    KeyError("Mandatory key missing. (is_grave)"),
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
