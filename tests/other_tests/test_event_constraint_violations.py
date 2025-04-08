import copy
import datetime
import unittest
import unittest.mock
from unittest.mock import Mock

from cdedb.common import CdEDBObject
from cdedb.database.constants import RegistrationPartStati
from cdedb.models import event as models
from cdedb.models.event_constraint_violations import (
    AbsentCheckedinCV,
    ConstraintViolation,
    PresentNeverCheckedinCV,
    ViolationSeverity,
)

RPS = RegistrationPartStati

begin = datetime.date(2020, 7, 20)
checkin_time = datetime.time(hour=17)
checkout_time = datetime.time(hour=11)
day = datetime.timedelta(days=1)
week = 7 * day

# mock minimum event data needed for violation checks
event_id = 42
summerA = Mock(spec=models.EventPart, id=1, event_id=event_id,
               part_begin=begin, part_end=begin + week)
summerB = Mock(spec=models.EventPart, id=2, event_id=event_id,
               part_begin=begin + week, part_end=begin + 2*week)
summerC = Mock(spec=models.EventPart, id=3, event_id=event_id,
               part_begin=begin + 2*week, part_end=begin + 3*week)
summerAka = Mock(spec=models.Event, id=event_id,
                 parts={p.id: p for p in (summerA, summerB, summerC)})
single_part = Mock(spec=models.EventPart, id=10, event_id=event_id,
                   part_begin=begin, part_end=begin + week)
onePartAka = Mock(spec=models.Event, id=event_id, parts={single_part.id: single_part})

single_part_registration: CdEDBObject = {
    'parts': {
        single_part.id: {
            'status': RPS.participant,
        },
    },
    'checkin_periods': [
        models.ReducedCheckinPeriod(
            datetime.datetime.combine(single_part.part_begin, checkin_time),
            datetime.datetime.combine(single_part.part_end, checkout_time),
        ),
    ],
}


class TestEventConstraintViolations(unittest.TestCase):
    def test_absent_checked_in(self) -> None:
        def check(event: models.Event, registration: CdEDBObject,
                  ) -> ConstraintViolation | None:
            return AbsentCheckedinCV.check(
                event, registration=registration, persona={})

        def assert_info_violation(event: models.Event, registration: CdEDBObject,
                                  ) -> None:
            violation = check(event, registration)
            # mypy does not recognize unittest asserts
            assert violation is not None, "Expected a violation"
            self.assertEqual(violation.severity, ViolationSeverity.INFO)

        # basic test case for one-part event
        reg = copy.deepcopy(single_part_registration)
        self.assertIsNone(check(onePartAka, reg))
        reg['checkin_periods'][0].checkin_time += day
        self.assertIsNone(check(onePartAka, reg))
        reg['checkin_periods'][0].checkin_time -= 2 * day
        assert_info_violation(onePartAka, reg)
        reg['checkin_periods'][0].checkin_time += day
        reg['checkin_periods'][0].checkout_time -= day
        self.assertIsNone(check(onePartAka, reg))
        reg['checkin_periods'][0].checkout_time += 2 * day
        assert_info_violation(onePartAka, reg)

        # complex test case for multipart event
        reg: CdEDBObject = {
            'parts': {
                1: {
                    'status': RPS.not_applied,
                },
                2: {
                    'status': RPS.not_applied,
                },
                3: {
                    'status': RPS.not_applied,
                },
            },
            'checkin_periods': [
                models.ReducedCheckinPeriod(
                    datetime.datetime.combine(summerA.part_begin, checkin_time),
                    datetime.datetime.combine(summerA.part_end, checkout_time)),
            ],
        }
        # checked in but should not be present at all
        violation = check(summerAka, reg)
        assert violation is not None, "Expected a violation"
        self.assertEqual(violation.severity, ViolationSeverity.ERROR)

        reg['parts'][summerC.id]['status'] = RPS.participant  # arrived to wrong part
        assert_info_violation(summerAka, reg)
        reg['parts'][summerC.id]['status'] = RPS.rejected
        reg['parts'][summerA.id]['status'] = RPS.participant
        self.assertIsNone(check(summerAka, reg))
        reg['checkin_periods'][0].checkout_time += day  # one day longer
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][0].checkin_time -= day  # and one day early
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][0].checkout_time -= day
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][0].checkin_time += day
        reg['checkin_periods'] += [  # additionally arrive for third week
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerC.part_begin, checkin_time),
                datetime.datetime.combine(summerC.part_end, checkout_time),
            ),
        ]
        assert_info_violation(summerAka, reg)
        del reg['checkin_periods'][1]

        # registered for two consecutive parts
        reg['parts'][summerB.id]['status'] = RPS.participant
        reg['checkin_periods'][0].checkout_time = (  # stay one day to long
            datetime.datetime.combine(summerB.part_end + day, checkout_time))
        assert_info_violation(summerAka, reg)

        # registered for two non-consecutive parts
        reg['parts'][summerC.id]['status'] = RPS.participant
        self.assertIsNone(check(summerAka, reg))
        reg['parts'][summerB.id]['status'] = RPS.applied  # should not be present
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerA.part_begin, checkin_time),
                datetime.datetime.combine(summerA.part_end, checkout_time),
            ),
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerC.part_begin, checkin_time),
                datetime.datetime.combine(summerC.part_end, checkout_time),
            ),
        ]
        self.assertIsNone(check(summerAka, reg))
        reg['checkin_periods'][0].checkout_time += day  # one day longer in first part
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][1].checkin_time -= day  # and one day early for third part
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][0].checkout_time -= day
        assert_info_violation(summerAka, reg)
        reg['parts'][summerB.id]['status'] = RPS.guest
        self.assertIsNone(check(summerAka, reg))

        # it is no problem to have separate checkin periods per part
        reg['checkin_periods'].insert(1, models.ReducedCheckinPeriod(
            datetime.datetime.combine(summerB.part_begin, checkin_time),
            datetime.datetime.combine(summerB.part_end, checkout_time),
        ))
        self.assertIsNone(check(summerAka, reg))

        # missing checkout is a problem
        reg['checkin_periods'] = [models.ReducedCheckinPeriod(
            checkin_time=datetime.datetime.combine(summerC.part_begin, checkin_time),
            checkout_time=None,
        )]
        reg['parts'][summerA.id]['status'] = RPS.cancelled
        reg['parts'][summerB.id]['status'] = RPS.cancelled
        reg['parts'][summerC.id]['status'] = RPS.participant
        assert_info_violation(summerAka, reg)
        # ... but only if part is over
        summerC.part_end = datetime.date.today() + week
        self.assertIsNone(check(summerAka, reg))
        summerC.part_end = begin + 3 * week

    def test_present_never_checked_in(self) -> None:
        def check(registration: CdEDBObject) -> ConstraintViolation | None:
            return PresentNeverCheckedinCV.check(onePartAka, registration=registration,
                                                 persona={}, part=single_part)

        reg = copy.deepcopy(single_part_registration)
        self.assertIsNone(check(reg))
        # error if missing or non-overlapping checkin
        reg['checkin_periods'] = [models.ReducedCheckinPeriod(
            datetime.datetime.combine(single_part.part_begin - week, checkin_time),
            datetime.datetime.combine(single_part.part_begin - day, checkin_time),
        )]
        violation = check(reg)
        assert violation is not None  # mypy does not recognize unittest asserts
        self.assertEqual(violation.severity, ViolationSeverity.ERROR)
        reg['checkin_periods'] = []
        violation = check(reg)
        assert violation is not None
        self.assertEqual(violation.severity, ViolationSeverity.ERROR)
        single_part.part_end = datetime.date.today() + week
        # level is only warning if event is still ongoing
        violation = check(reg)
        assert violation is not None
        self.assertEqual(violation.severity, ViolationSeverity.WARNING)
        reg['parts'][single_part.id]['status'] = RPS.cancelled
        self.assertIsNone(check(reg))
