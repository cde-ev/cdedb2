import datetime

import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import nearly_now
from tests.common import BackendTest, as_users


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
