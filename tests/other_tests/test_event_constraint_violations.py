import copy
import datetime
import unittest
from unittest.mock import Mock

from cdedb.common import CdEDBObject
from cdedb.database.constants import RegistrationPartStati
from cdedb.models import event as models
from cdedb.models.event.constraint_violations import (
    AbsentCheckedinCV,
    ConstraintViolation,
    PresentNeverCheckedinCV,
    ViolationAux,
    ViolationContext,
    ViolationSeverity,
)

RPS = RegistrationPartStati

begin = datetime.date(2020, 7, 20)
checkin = datetime.time(hour=17)
checkout = datetime.time(hour=11)
day = datetime.timedelta(days=1)
week = 7 * day

# mock minimum event data needed for violation checks
event_id = 42
summerA = Mock(
    spec=models.EventPart,
    id=1,
    event_id=event_id,
    part_begin=begin,
    part_end=begin + week,
)
summerB = Mock(
    spec=models.EventPart,
    id=2,
    event_id=event_id,
    part_begin=begin + week,
    part_end=begin + 2 * week,
)
summerC = Mock(
    spec=models.EventPart,
    id=3,
    event_id=event_id,
    part_begin=begin + 2 * week,
    part_end=begin + 3 * week,
)
summerAka = Mock(
    spec=models.Event,
    id=event_id,
    is_archived=False,
    parts={p.id: p for p in (summerA, summerB, summerC)},
)
single_part = Mock(
    spec=models.EventPart,
    id=10,
    event_id=event_id,
    part_begin=begin,
    part_end=begin + week,
)
onePartAka = Mock(
    spec=models.Event,
    id=event_id,
    is_archived=False,
    parts={single_part.id: single_part},
)

single_part_registration: CdEDBObject = {
    'id': 1001,
    'parts': {
        single_part.id: {
            'status': RPS.participant,
        },
    },
    'checkin_periods': [
        models.ReducedCheckinPeriod(
            datetime.datetime.combine(single_part.part_begin, checkin),
            datetime.datetime.combine(single_part.part_end, checkout),
        ),
    ],
}


class TestEventConstraintViolations(unittest.TestCase):
    def test_absent_checked_in(self) -> None:
        def check(
            event: models.Event,
            registration: CdEDBObject,
        ) -> ConstraintViolation | None:
            return AbsentCheckedinCV.check(
                Mock(spec=ViolationAux, event=event),
                ViolationContext(registration=registration),
            )

        def assert_info_violation(
            event: models.Event,
            registration: CdEDBObject,
        ) -> None:
            violation = check(event, registration)
            # mypy does not recognize unittest asserts
            assert violation is not None, "Expected a violation"
            self.assertEqual(violation.severity, ViolationSeverity.INFO)

        # basic test case for one-part event
        reg: CdEDBObject = copy.deepcopy(single_part_registration)
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

        # no violation for checkin on last day
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(single_part.part_begin, checkin),
                datetime.datetime.combine(single_part.part_end, checkout),
            ),
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(single_part.part_end, checkout),
                datetime.datetime.combine(single_part.part_end, checkin),
            ),
        ]
        self.assertIsNone(check(onePartAka, reg))

        # complex test case for multipart event
        reg = {
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
                    datetime.datetime.combine(summerA.part_begin, checkin),
                    datetime.datetime.combine(summerA.part_end, checkout),
                ),
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
                datetime.datetime.combine(summerC.part_begin, checkin),
                datetime.datetime.combine(summerC.part_end, checkout),
            ),
        ]
        assert_info_violation(summerAka, reg)
        del reg['checkin_periods'][1]

        # registered for two consecutive parts
        reg['parts'][summerB.id]['status'] = RPS.participant
        reg['checkin_periods'][0].checkout_time = (  # stay one day to long
            datetime.datetime.combine(summerB.part_end + day, checkout)
        )
        assert_info_violation(summerAka, reg)

        # registered for two non-consecutive parts
        reg['parts'][summerC.id]['status'] = RPS.participant
        self.assertIsNone(check(summerAka, reg))
        reg['parts'][summerB.id]['status'] = RPS.applied  # should not be present
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerA.part_begin, checkin),
                datetime.datetime.combine(summerA.part_end, checkout),
            ),
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerC.part_begin, checkin),
                datetime.datetime.combine(summerC.part_end, checkout),
            ),
        ]
        self.assertIsNone(check(summerAka, reg))
        reg['checkin_periods'][0].checkout_time += day  # one day longer in first part
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][
            1
        ].checkin_time -= day  # and one day early for third part
        assert_info_violation(summerAka, reg)
        reg['checkin_periods'][0].checkout_time -= day
        assert_info_violation(summerAka, reg)
        reg['parts'][summerB.id]['status'] = RPS.guest
        self.assertIsNone(check(summerAka, reg))

        # it is no problem to have separate checkin periods per part
        reg['checkin_periods'].insert(
            1,
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(summerB.part_begin, checkin),
                datetime.datetime.combine(summerB.part_end, checkout),
            ),
        )
        self.assertIsNone(check(summerAka, reg))

        # missing checkout is a problem
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                checkin_time=datetime.datetime.combine(summerC.part_begin, checkin),
                checkout_time=None,
            )
        ]
        reg['parts'][summerA.id]['status'] = RPS.cancelled
        reg['parts'][summerB.id]['status'] = RPS.cancelled
        reg['parts'][summerC.id]['status'] = RPS.participant
        assert_info_violation(summerAka, reg)
        # ... but only if part is over
        summerC.part_end = datetime.date.today() + week
        self.assertIsNone(check(summerAka, reg))
        summerC.part_end = begin + 3 * week

    def test_present_never_checked_in(self) -> None:
        def check(
            registration: CdEDBObject, other_registrations: CdEDBObject | None = None
        ) -> ConstraintViolation | None:
            return PresentNeverCheckedinCV.check(
                Mock(
                    spec=ViolationAux,
                    event=onePartAka,
                    registrations={registration["id"]: registration}
                    | (other_registrations if other_registrations else {}),
                ),
                ViolationContext(registration=registration, part=single_part),
            )

        reg = copy.deepcopy(single_part_registration)
        self.assertIsNone(check(reg))
        # error for incorrect checkin
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(single_part.part_begin - week, checkin),
                datetime.datetime.combine(single_part.part_begin - day, checkin),
            )
        ]
        violation = check(reg)
        assert violation is not None  # mypy does not recognize unittest asserts
        self.assertEqual(violation.severity, ViolationSeverity.ERROR)

        # debug for missing checkin because no checkins at all.
        reg['checkin_periods'] = []
        violation = check(reg)
        assert violation is not None
        self.assertEqual(violation.severity, ViolationSeverity.DEBUG)
        # error for missing checking if there are some checkins.
        reg2 = copy.deepcopy(single_part_registration)
        reg2["id"] += 1
        violation = check(reg, other_registrations={reg2["id"]: reg2})
        assert violation is not None
        self.assertEqual(violation.severity, ViolationSeverity.ERROR)

        # no violation for immediate checkout
        reg['checkin_periods'] = [
            models.ReducedCheckinPeriod(
                datetime.datetime.combine(single_part.part_begin, checkin),
                datetime.datetime.combine(single_part.part_begin, checkin)
                + datetime.timedelta(seconds=5),
            )
        ]
        self.assertIsNone(check(reg))

        reg['checkin_periods'] = []
        single_part.part_end = datetime.date.today() + week
        # level is only warning if event is still ongoing
        violation = check(reg, other_registrations={reg2["id"]: reg2})
        assert violation is not None
        self.assertEqual(violation.severity, ViolationSeverity.WARNING)
        reg['parts'][single_part.id]['status'] = RPS.cancelled
        self.assertIsNone(check(reg))
