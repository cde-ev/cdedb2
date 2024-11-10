"""
Classes for constraint violations in the event realm.
"""

import dataclasses
import itertools
from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import AgeClasses, CdEDBObject, make_persona_name, n_
from cdedb.common.sorting import xsorted

if TYPE_CHECKING:
    from cdedb.frontend.event.course import CourseAttendees


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConstraintViolation:
    event: models.Event
    severity: int

    # Primary entities.
    registration: CdEDBObject | None = None
    persona: CdEDBObject | None = None
    course: CdEDBObject | None = None

    # Secondary entities.
    part: models.EventPart | None = None
    track: models.CourseTrack | None = None
    part_group: models.PartGroup | None = None
    track_group: models.TrackGroup | None = None

    # Helper properties.
    @cached_property
    def registration_part(self) -> CdEDBObject | None:
        return (
            self.registration['parts'][self.part]
            if self.registration and self.part else None
        )

    @cached_property
    def registration_track(self) -> CdEDBObject | None:
        return (
            self.registration['tracks'][self.track]
            if self.registration and self.track else None
        )

    # Constructor interface.
    # Inheritance does not work very nicely with typing, due to different signatures.
    @classmethod
    @abstractmethod
    def check(cls, event: models.Event, **kwargs: Any) -> Self | None:
        """
        Takes the event and some entites and determines whether there is a violation.

        If so this constructor returns a new instance with the appropriate severity.
        """
        raise NotImplementedError

    # Display interface.
    def get_translation(self) -> tuple[str, CdEDBObject]:
        """
        Must return a string template for translation and a dict of translation params.

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
class MutuallyExclusiveParticipationCV(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
    part_group: models.PartGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            mep_group: models.PartGroup,
    ) -> Self | None:
        """
        If the given registration is present at competing parts, return a violation.

        Depending on the exact status, the violation can have a different severity.
        """
        participant_parts = {
            part_id for part_id in mep_group.parts
            if registration['parts'][part_id]['status']
               == const.RegistrationPartStati.participant
        }
        if len(participant_parts) > 1:
            return cls(
                event=event,
                severity=2,
                registration=registration,
                persona=persona,
                part_group=mep_group,
            )

        is_present_parts = {
            part_id for part_id in mep_group.parts
            if registration['parts'][part_id]['status'].is_present()
        }
        if len(is_present_parts) > 1:
            return cls(
                event=event,
                severity=1,
                registration=registration,
                persona=persona,
                part_group=mep_group,
            )

        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        if self.severity >= 2:
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
            "link": make_persona_name(self.persona),
            "part_list": ", ".join(
                part.shortname for part in xsorted(self.part_group.parts.values())
                if part_filter(part)
            ),
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_registration", {'registration_id': self.registration['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseChoiceSyncCV(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
    track_group: models.TrackGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            ccs_group: models.TrackGroup,
    ) -> Self | None:
        """
        If the registration has unyncen course choices, return a violation.

        The backend should always ensure, that this cannot occur, so such a
        violation has a very high severity if it does occur.
        """
        if any(
                registration['tracks'][t1]['choices']
                != registration['tracks'][t2]['choices']
                or registration['tracks'][t1]['course_instructor']
                != registration['tracks'][t2]['course_instructor']
                for t1, t2 in itertools.combinations(ccs_group.tracks, 2)
        ):
            return cls(
                event=event,
                severity=3,
                registration=registration,
                persona=persona,
                track_group=ccs_group,
            )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        msg = n_(
            "%(link)s has unsynchrozied course choices in synchronized"
            " tracks (%(track_list)s).",
        )
        params = {
            "link": make_persona_name(self.persona),
            "track_list": ", ".join(
                track.shortname for track in xsorted(self.track_group.tracks.values())
            ),
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_registration", {'registration_id': self.registration['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class MutuallyExclusiveCoursesCV(ConstraintViolation):
    course: CdEDBObject
    track_group: models.TrackGroup

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            mec_group: models.TrackGroup,
    ) -> Self | None:
        """If the given course takes place in competing tracks, return a violation."""
        if len(set(course['active_segments']) & set(mec_group.tracks)) > 1:
            return cls(
                event=event,
                severity=1,
                course=course,
                track_group=mec_group,
            )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
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
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_course", {'course_id': self.course['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class CancelledWithAttendeesCV(ConstraintViolation):
    course: CdEDBObject
    track: models.CourseTrack

    num: int

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            attendees: "CourseAttendees",
            track: models.CourseTrack,
    ) -> Self | None:
        """Return a validation if the course is cancelled but has attendees."""
        if track.id not in course['segments']:
            if attendees.involved:
                return cls(
                    event=event,
                    severity=3,
                    course=course,
                    track=track,
                    num=attendees.num_involved,
                )
        elif track.id not in course['active_segments']:
            if attendees.involved:
                return cls(
                    event=event,
                    severity=2,
                    course=course,
                    track=track,
                    num=attendees.num_involved,
                )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        if self.severity >= 3:
            msg = n_("%(link)s is not offered in %(track)s but has %(num)s attendees.")
        else:
            msg = n_("%(link)s is cancelled in %(track)s but has %(num)s attendees.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num,
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_course", {'course_id': self.course['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectNumAttendeesCV(ConstraintViolation):
    course: CdEDBObject
    track: models.CourseTrack

    num: int

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            course: CdEDBObject,
            attendees: "CourseAttendees",
            track: models.CourseTrack,
    ) -> Self | None:
        """Return a violation if the course has too few or too many attendees."""
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
                    severity=1 if attendees.num_involved_learners else 0,
                    course=course,
                    track=track,
                    num=attendees.num_involved_learners,
                )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        if self.course['min_size'] and self.num < self.course['min_size']:
            msg = n_("%(link)s has too few attendees (%(num)s < %(min_size)s) in %(track)s.")
        else:
            msg = n_("%(link)s has too many attendees (%(num)s > %(max_size)s) in %(track)s.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "num": self.num,
            "track": self.track.shortname,
            "min_size": self.course['min_size'],
            "max_size": self.course['max_size'],
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_course", {'course_id': self.course['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class LonelyAttendeesCV(ConstraintViolation):
    course: CdEDBObject
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
            if bool(attendees.involved_learners) != bool(attendees.involved_instructors):
                return cls(
                    event=event,
                    severity=1,
                    course=course,
                    track=track,
                    num_learners=attendees.num_involved_learners,
                    num_instructors=attendees.num_involved_instructors,
                )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        if self.num_learners:
            msg = n_("%(link)s has %(num)s attendees but no instructors in %(track)s.")
        else:
            msg = n_("%(link)s has %(num)s instructors but no attendees in %(track)s.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num_learners or self.num_instructors,
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_course", {'course_id': self.course['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class NoCourseAssignedCV(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
    track: models.CourseTrack

    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event, *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            track: models.CourseTrack,
    ) -> Self | None:
        reg_track = registration['tracks'][track.id]
        reg_part = registration['parts'][track.part_id]
        if not reg_part['status'].is_present():
            return None
        if reg_track['course_id'] is None:
            return cls(
                event=event,
                severity=0 if (
                        persona['id'] in event.orgas
                        or reg_part['age'] == AgeClasses.u10
                        or reg_part['status'] != const.RegistrationPartStati.participant
                ) else 1,
                registration=registration,
                persona=persona,
                track=track,
            )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        msg = n_("%(link)s is not assigned to a course in %(track)s.")
        params = {
            "link": make_persona_name(self.persona),
            "track": self.track.shortname,
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_registration", {'registration_id': self.registration['id']}


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectCourseAssignedCV(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
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
                severity=1,
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
                severity=1,
                registration=registration,
                persona=persona,
                track=track,
                assigned_course=assigned_course,
            )
        return None

    def get_translation(self) -> tuple[str, CdEDBObject]:
        if self.instructed_course:
            msg = n_("%(link)s does not instruct their course (%(instructed_course)s)"
                     " in %(track)s.")
        else:
            msg = n_("%(link)s did not choose their assigned course"
                     " (%(assigned_course)s) in %(track)s.")

        params = {
            "link": make_persona_name(self.persona),
            "track": self.track.shortname,
            "assigned_course":
                f"{self.assigned_course['nr']}. {self.assigned_course['shortname']}",
            "instructed_course":
                f"{self.instructed_course['nr']}."
                f" {self.instructed_course['shortname']}"
                if self.instructed_course else None,
        }
        return msg, params

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        return "event/show_registration", {'registration_id': self.registration['id']}
