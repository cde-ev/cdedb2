"""
Classes for constraint violations in the event realm.

A violation marks a valid but undesired state that should be addressed
with some level of urgency depending on the given `severity`.

Severities and their meaning are roughtly as follows:

CRITICAL: A state which should never exist and only does so because of:
    - a bug
    - a corrupted database entry
    - human error outside of the orgateam
ERROR: A state which is always incorrect and should be fixed within a few days.
WARNING: A state which should be fixed, but which may be correct for some period
    of time or in some special circumstances.
INFO: A state which should be addressed at some point and not forgotten but which
    can only be addressed long term or by someone outside of the orgateam.
    Might later turn into more severe state, depending on other factors.
DEBUG: A placeholder for violations which are implemented but are not relevant in
    practice and therefore hidden in the UI.
"""
import abc
import dataclasses
import datetime
import enum
import itertools
from typing import TYPE_CHECKING, Any, Self

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import AgeClasses, CdEDBObject, make_persona_name, n_, now
from cdedb.common.sorting import xsorted
from cdedb.filter import money_filter

if TYPE_CHECKING:
    from cdedb.frontend.event.course import CourseAttendees


class ViolationSeverity(enum.Enum):
    CRITICAL = 4
    ERROR = 3
    WARNING = 2
    INFO = 1
    DEBUG = 0

    def html_class(self) -> str:
        return {
            ViolationSeverity.CRITICAL: 'text-danger fw-bold',
            ViolationSeverity.ERROR: 'text-danger',
            ViolationSeverity.WARNING: 'text-warning',
            ViolationSeverity.INFO: '',
            ViolationSeverity.DEBUG: 'text-muted',
        }[self]

    def panel_class(self) -> str:
        return {
            ViolationSeverity.CRITICAL: 'panel-danger fw-bold',
            ViolationSeverity.ERROR: 'panel-danger',
            ViolationSeverity.WARNING: 'panel-warning',
            ViolationSeverity.INFO: 'panel-default',
            ViolationSeverity.DEBUG: 'panel-default',
        }[self]

    def __lt__(self, other: 'ViolationSeverity') -> bool:
        return self.value < other.value

    def __ge__(self, other: 'ViolationSeverity') -> bool:
        return self.value >= other.value


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConstraintViolation(abc.ABC):
    event: models.Event
    severity: ViolationSeverity

    # Primary entities.
    registration: CdEDBObject | None = None
    persona: CdEDBObject | None = None
    course: CdEDBObject | None = None

    # Secondary entities.
    part: models.EventPart | None = None
    track: models.CourseTrack | None = None
    part_group: models.PartGroup | None = None
    track_group: models.TrackGroup | None = None

    # Constructor interface.
    # Inheritance does not work very nicely with typing, due to different signatures.
    @classmethod
    def check(cls, event: models.Event, **kwargs: Any) -> Self | None:
        """
        Takes the event and some entites and determines whether there is a violation.

        If so this constructor returns a new instance with the appropriate severity.
        """
        raise NotImplementedError

    # Display interface.
    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        """
        Must return a list of strings for translation and a dict of translation params.

        One of the parameters must be named 'link' and be the link text of the link
        defined by `get_link_params`.
        """
        raise NotImplementedError

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        """
        Must return a string specifying a link target and a dict of link parameters.

        The link text will be the 'link' parameter from `get_translations`.
        """
        raise NotImplementedError


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationConstraintViolation(ConstraintViolation, abc.ABC):
    registration: CdEDBObject
    persona: CdEDBObject

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_registration", {'registration_id': self.registration['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseConstraintViolation(ConstraintViolation, abc.ABC):
    course: CdEDBObject

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_course", {'course_id': self.course['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class MutuallyExclusiveParticipationCV(RegistrationConstraintViolation):
    part_group: models.PartGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            part_group: models.PartGroup,
    ) -> Self | None:
        """
        If the given registration is present at competing parts, return a violation.

        Depending on the exact status, the violation can have a different severity.
        """
        ct = part_group.constraint_type
        if ct != const.EventPartGroupType.mutually_exclusive_participants:
            return None
        participant_parts = {
            part_id for part_id in part_group.parts
            if registration['parts'][part_id]['status']
               == const.RegistrationPartStati.participant
        }
        if len(participant_parts) > 1:
            return cls(
                event=event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
                persona=persona,
                part_group=part_group,
            )

        is_present_parts = {
            part_id for part_id in part_group.parts
            if registration['parts'][part_id]['status'].is_present()
        }
        if len(is_present_parts) > 1:
            return cls(
                event=event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
                persona=persona,
                part_group=part_group,
            )

        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.severity >= ViolationSeverity.ERROR:
            msg = n_(
                "%(link)s is participant in mutually exclusive parts (%(part_list)s).",
            )
            part_filter = lambda part: (
                self.registration['parts'][part.id]['status']
                    == const.RegistrationPartStati.participant
            )
        else:
            msg = n_(
                "%(link)s is present at mutually exclusive parts (%(part_list)s).",
            )
            part_filter = lambda part: (
                self.registration['parts'][part.id]['status'].is_present()
            )
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "part_list": ", ".join(
                part.shortname for part in xsorted(self.part_group.parts.values())
                if part_filter(part)
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseChoiceSyncCV(RegistrationConstraintViolation):
    track_group: models.TrackGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            track_group: models.TrackGroup,
    ) -> Self | None:
        """
        If the registration has unyncen course choices, return a violation.

        The backend should always ensure, that this cannot occur, so such a
        violation has a critical severity if it does occur.
        """
        ct = track_group.constraint_type
        if ct != const.CourseTrackGroupType.course_choice_sync:
            return None
        if any(
                registration['tracks'][t1]['choices']
                != registration['tracks'][t2]['choices']
                or registration['tracks'][t1]['course_instructor']
                != registration['tracks'][t2]['course_instructor']
                for t1, t2 in itertools.combinations(track_group.tracks, 2)
        ):  # pragma: no cover
            return cls(
                event=event,
                severity=ViolationSeverity.CRITICAL,
                registration=registration,
                persona=persona,
                track_group=track_group,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:  # pragma: no cover
        msg = n_(
            "%(link)s has unsynchrozied course choices in synchronized"
            " tracks (%(track_list)s).",
        )
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "track_list": ", ".join(
                track.shortname for track in xsorted(self.track_group.tracks.values())
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NoCourseAssignedCV(RegistrationConstraintViolation):
    track: models.CourseTrack

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            track: models.CourseTrack,
    ) -> Self | None:
        """Return a violation if the registration has no assigned course.

        Severity of DEBUG for registrations which are unlikely to need a course.
        """
        reg_track = registration['tracks'][track.id]
        reg_part = registration['parts'][track.part_id]
        if not reg_part['status'].is_present():
            return None
        if reg_track['course_id'] is None:
            return cls(
                event=event,
                severity=ViolationSeverity.DEBUG if (
                        persona['id'] in event.orgas
                        or reg_part['age'] == AgeClasses.u10
                        or reg_part['status'] != const.RegistrationPartStati.participant
                ) else ViolationSeverity.WARNING,
                registration=registration,
                persona=persona,
                track=track,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        msg = n_("%(link)s is not assigned to a course in %(track)s.")
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "track": self.track.shortname,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectCourseAssignedCV(RegistrationConstraintViolation):
    track: models.CourseTrack

    assigned_course: CdEDBObject
    instructed_course: CdEDBObject | None = None

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            track: models.CourseTrack,
            assigned_course: CdEDBObject | None,
            instructed_course: CdEDBObject | None,
    ) -> Self | None:
        """
        Return a violation if the registration is assigned to an unchosen course.

        Make the violation a warning if an instructor is not assigned to their
        instructed course event though it takes place.
        """
        reg_track = registration['tracks'][track.id]
        reg_part = registration['parts'][track.part_id]
        if not reg_part['status'].is_present() or assigned_course is None:
            return None
        if (
                instructed_course
                and track.id in instructed_course['active_segments']
                and instructed_course['id'] != assigned_course['id']
        ):
            return cls(
                event=event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
                persona=persona,
                track=track,
                assigned_course=assigned_course,
                instructed_course=instructed_course,
            )
        if (
                assigned_course['id'] not in reg_track['choices']
                and (
                    instructed_course is None
                    or assigned_course['id'] != instructed_course['id']
                )
        ):
            return cls(
                event=event,
                severity=ViolationSeverity.INFO,
                registration=registration,
                persona=persona,
                track=track,
                assigned_course=assigned_course,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.instructed_course:
            msg = n_("%(link)s does not instruct their course (%(instructed_course)s)"
                     " in %(track)s.")
        else:
            msg = n_("%(link)s did not choose their assigned course"
                     " (%(assigned_course)s) in %(track)s.")

        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "track": self.track.shortname,
            "assigned_course":
                f"{self.assigned_course['nr']}. {self.assigned_course['shortname']}",
            "instructed_course":
                f"{self.instructed_course['nr']}."
                f" {self.instructed_course['shortname']}"
                if self.instructed_course else None,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class InconsistentPaymentCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
    ) -> Self | None:
        if registration['amount_paid'] < 0:
            return cls(
                event=event,
                severity=ViolationSeverity.CRITICAL,
                registration=registration,
                persona=persona,
            )
        if registration['amount_paid'] > 0 and registration['payment'] is None:
            return cls(
                event=event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
                persona=persona,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.registration['amount_paid'] < 0:
            msgs = [n_("%(link)s has paid a negative amount (%(amount_paid)s).")]
        else:
            msgs = [n_("%(link)s has paid without a payment date.")]

        msgs.append(n_("This likely means someone entered invalid payment data."))

        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "amount_paid": money_filter(self.registration['amount_paid']),
        }
        return msgs, params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NotPaidCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
    ) -> Self | None:
        if registration['amount_paid'] == 0 and registration['amount_owed'] > 0:
            if any(reg_part['status'] == const.RegistrationPartStati.participant
                   for reg_part in registration['parts'].values()):
                return cls(
                    event=event,
                    severity=(
                        ViolationSeverity.INFO if persona['id'] in event.orgas
                        else ViolationSeverity.ERROR
                    ),
                    registration=registration,
                    persona=persona,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.persona['id'] in self.event.orgas:
            msg = n_("%(link)s is orga but has not paid their fee (%(amount_owed)s).")
        else:
            msg = n_("%(link)s has not paid their fee (%(amount_owed)s).")

        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "amount_owed": money_filter(self.registration['amount_owed']),
        }

        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NegativeAmountOwedCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
    ) -> Self | None:
        if registration['amount_owed'] < 0:
            return cls(
                event=event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
                persona=persona,
            )
        if registration['amount_owed'] == 0:
            if any(reg_part['status'].is_involved()
                   for reg_part in registration['parts'].values()):
                return cls(
                    event=event,
                    severity=(
                        ViolationSeverity.DEBUG if persona['id'] in event.orgas
                        else ViolationSeverity.INFO
                    ),
                    registration=registration,
                    persona=persona,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.registration['amount_owed'] < 0:
            msg = n_("%(link)s owes a negative amount (%(amount_owed)s).")
        else:
            msg = n_("%(link)s is involved but owes no fee.")

        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "amount_owed": money_filter(self.registration['amount_owed']),
        }

        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NegativeRemainingOwedCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
    ) -> Self | None:
        if registration['remaining_owed'] < 0:
            return cls(
                event=event,
                severity=(
                    ViolationSeverity.WARNING if event.is_archived
                    else ViolationSeverity.INFO
                ),
                registration=registration,
                persona=persona,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        msg = n_("%(link)s needs to be reimbursed (%(remaining_owed)s).")
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "remaining_owed": money_filter(-self.registration['remaining_owed']),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class RemainingOwedCV(RegistrationConstraintViolation):
    min_involved_part_begin: datetime.date

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
    ) -> Self | None:
        if registration['remaining_owed'] > 0 and registration['amount_paid'] > 0:
            if any(reg_part['status'].is_involved()
                   for reg_part in registration['parts'].values()):
                min_involved_part_begin = min(
                    event.parts[part_id].part_begin
                    for part_id, reg_part in registration['parts'].items()
                    if reg_part['status'].is_involved()
                )
                return cls(
                    event=event,
                    severity=(
                        ViolationSeverity.ERROR
                        if min_involved_part_begin < now().date()
                        else ViolationSeverity.WARNING
                    ),
                    registration=registration,
                    persona=persona,
                    min_involved_part_begin=min_involved_part_begin,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        msg = n_(
            "%(link)s has not fully paid their fee (remaining: %(remaining_owed)s).")

        parms = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "remaining_owed": money_filter(self.registration['remaining_owed']),
        }

        return [msg], parms


@dataclasses.dataclass(frozen=True, kw_only=True)
class AbsentCheckedinCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
        cls, event: models.Event, *,
        registration: CdEDBObject,
        persona: CdEDBObject,
    ) -> Self | None:
        """Return a violation if a persona should not be checked in, but is.

        If they are checked in even though they are is not present in the relevant part,
        return an INFO. If they are not present at all, return an ERROR.
        If they have not been checked out even though they should have been, return an
        INFO as well.
        """
        is_present_parts = {
            part_id: part for part_id, part in event.parts.items()
            if registration['parts'][part_id]['status'].is_present()
        }

        if not is_present_parts:
            if registration['checkin_periods']:
                return cls(
                    event=event,
                    severity=ViolationSeverity.ERROR,
                    registration=registration,
                    persona=persona,
                )

        ref_time = now().date()
        day = datetime.timedelta(days=1)
        for period in registration['checkin_periods']:
            valid_checkin_time = valid_checkout_time = False
            for part in is_present_parts.values():
                if part.part_begin < period.checkin_time.date() < part.part_end:
                    valid_checkin_time = True
                has_contingent_successor = any(
                    other.part_begin - day <= part.part_end < other.part_end
                    for other in is_present_parts.values())
                if (not period.checkout_time and part.part_end >= ref_time
                        and not has_contingent_successor):
                    valid_checkout_time = True
            if period.checkout_time:
                for part in is_present_parts.values():
                    if part.part_begin < period.checkout_time.date() < part.part_end:
                        valid_checkout_time = True
                        break
            if not (valid_checkin_time and valid_checkout_time):
                return cls(
                    event=event,
                    severity=ViolationSeverity.INFO,
                    registration=registration,
                    persona=persona,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.severity == ViolationSeverity.INFO:
            msg = n_("%(link)s's is checked in, but should not be at these times.")
        else:
            msg = n_("%(link)s's is checked in, but was never present.")
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class PresentNeverCheckedinCV(RegistrationConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
        cls, event: models.Event, *,
        registration: CdEDBObject,
        persona: CdEDBObject,
        part: models.EventPart,
    ) -> Self | None:
        """Return a violation if a persona should be checked in, but is not.

        If a registration is participant and not checked in after the first day of the
        part, return a WARNING. If at the end of the respective part, they still never
        checked in, return an ERROR.
        """
        ref_time = now().date()
        if not (registration['parts'][part.id]['status'].is_present()
                and ref_time > part.part_begin):
            return None
        valid_checkin_time = False
        for period in registration['checkin_periods']:
            if (period.checkin_time.date() <= part.part_end
                    and (not period.checkout_time
                         or period.checkout_time.date() < part.part_begin)):
                valid_checkin_time = True
                break
        if not valid_checkin_time:
            return cls(
                event=event,
                severity=(
                    ViolationSeverity.ERROR
                    if ref_time > part.part_end else
                    ViolationSeverity.WARNING),
                registration=registration,
                persona=persona,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.severity == ViolationSeverity.ERROR:
            msg = n_("%(link)s was present, but never checked in.")
        else:
            msg = n_("%(link)s will be present, but has not checked in yet.")
        params = {
            "link": make_persona_name(self.persona, include_nickname=True),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class MutuallyExclusiveCoursesCV(CourseConstraintViolation):
    track_group: models.TrackGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            track_group: models.TrackGroup,
    ) -> Self | None:
        """If the given course takes place in competing tracks, return a violation."""
        ct = track_group.constraint_type
        if ct != const.CourseTrackGroupType.mutually_exclusive_courses:
            return None
        if len(set(course['active_segments']) & set(track_group.tracks)) > 1:
            return cls(
                event=event,
                severity=ViolationSeverity.ERROR,  # TODO: WARNING if no attendees.
                course=course,
                track_group=track_group,
            )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        msg = n_(
            "%(link)s is taking place in mutually exclusive tracks (%(track_list)s).",
        )
        track_ids = set(self.course['active_segments']) & set(self.track_group.tracks)
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track_list": ", ".join(
                track.shortname for track in xsorted(self.track_group.tracks.values())
                if track.id in track_ids
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class CancelledWithAttendeesCV(CourseConstraintViolation):
    track: models.CourseTrack

    num: int

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            attendees: "CourseAttendees",
            track: models.CourseTrack,
    ) -> Self | None:
        """Return a violation if the course is cancelled but has attendees.

        If the course was never offered but has attendees, someone misused the
        course segments toggle. In that case this is an error, otherwise a warning.
        """
        if track.id not in course['segments']:
            if attendees.involved:
                return cls(
                    event=event,
                    severity=ViolationSeverity.ERROR,
                    course=course,
                    track=track,
                    num=attendees.num_involved,
                )
        elif track.id not in course['active_segments']:
            if attendees.involved:
                return cls(
                    event=event,
                    severity=ViolationSeverity.WARNING,
                    course=course,
                    track=track,
                    num=attendees.num_involved,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.severity >= ViolationSeverity.ERROR:
            msg = n_("%(link)s is not offered in %(track)s but has %(num)s attendees.")
        else:
            msg = n_("%(link)s is cancelled in %(track)s but has %(num)s attendees.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectNumAttendeesCV(CourseConstraintViolation):
    track: models.CourseTrack

    num: int

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            attendees: "CourseAttendees",
            track: models.CourseTrack,
    ) -> Self | None:
        """
        Return a violation if the course has too few or too many attendees.

        Make the violation DEBUG if no attendees are assigned yet to avoid clutter.
        """
        if track.id in course['active_segments']:
            if (
                    course['min_size'] is not None
                    and attendees.num_involved_learners < course['min_size']
                    or
                    course['max_size'] is not None
                    and attendees.num_involved_learners > course['max_size']
            ):
                return cls(
                    event=event,
                    severity=(
                        ViolationSeverity.WARNING if attendees.num_involved_learners
                        else ViolationSeverity.DEBUG
                    ),
                    course=course,
                    track=track,
                    num=attendees.num_involved_learners,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.course['min_size'] and self.num < self.course['min_size']:
            msg = n_("%(link)s has too few attendees (%(num)s < %(min_size)s)"
                     " in %(track)s.")
        else:
            msg = n_("%(link)s has too many attendees (%(num)s > %(max_size)s)"
                     " in %(track)s.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "num": self.num,
            "track": self.track.shortname,
            "min_size": self.course['min_size'],
            "max_size": self.course['max_size'],
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class LonelyAttendeesCV(CourseConstraintViolation):
    track: models.CourseTrack

    num_learners: int
    num_instructors: int

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event,
            course: CdEDBObject,
            attendees: "CourseAttendees",
            track: models.CourseTrack,
    ) -> Self | None:
        """Return a violation if the course has attendees but no instructors."""
        if track.id in course['active_segments']:
            if bool(attendees.involved_learners) != bool(attendees.involved_instructors):  # pylint: disable=line-too-long
                return cls(
                    event=event,
                    severity=ViolationSeverity.INFO,
                    course=course,
                    track=track,
                    num_learners=attendees.num_involved_learners,
                    num_instructors=attendees.num_involved_instructors,
                )
        return None

    def get_translation(self) -> tuple[list[str], CdEDBObject]:
        if self.num_learners:
            msg = n_("%(link)s has %(num)s attendees but no instructors in %(track)s.")
        else:
            msg = n_("%(link)s has %(num)s instructors but no attendees in %(track)s.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num_learners or self.num_instructors,
        }
        return [msg], params
