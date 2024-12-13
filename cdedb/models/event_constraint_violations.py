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
import collections
import dataclasses
import datetime
import enum
import itertools
from collections.abc import Collection, Iterator
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, Self, cast

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import AgeClasses, CdEDBObject, make_persona_name, n_, now
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.filter import money_filter

if TYPE_CHECKING:
    from cdedb.frontend.event.course import CourseAttendees


class ViolationSeverity(enum.Enum):
    """Enum to indicate how severe a violation ist. Used for sorting and formatting."""
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
            ViolationSeverity.INFO: 'panel-info',
            ViolationSeverity.DEBUG: 'panel-default',
        }[self]

    def __lt__(self, other: 'ViolationSeverity') -> bool:
        return self.value < other.value

    def __ge__(self, other: 'ViolationSeverity') -> bool:
        return self.value >= other.value


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseStatsFormat:
    """Helper class for storing and aggregating formatting specs."""

    # List of html classes to be added to the relevant html tag.
    html_classes: list[str] = dataclasses.field(default_factory=list)
    # List of hover titles to be added to that same element.
    titles: list[str] = dataclasses.field(default_factory=list)
    # List of icons to be displayed near that element, each with it's own hover title.
    icons: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def __add__(self, other: 'CourseStatsFormat') -> 'CourseStatsFormat':
        return self.__class__(
            html_classes=self.html_classes + other.html_classes,
            titles=self.titles + other.titles,
            icons=self.icons + other.icons,
        )

    @cached_property
    def html_class(self) -> str:
        return " ".join(self.html_classes)

    def get_title(self, g: Callable[[str], str]) -> str:
        """Translate titles with the passed gettext. Join with newlines."""
        return "\n".join(map(g, self.titles))


_MISSING = object()


@dataclasses.dataclass(frozen=True)
class ViolationList:
    """Container class for a list of violations.

    Provides sorting, grouping and aggregation.
    """
    violations: list['ConstraintViolation']

    def __post_init__(self) -> None:
        self.violations.sort()

    @cached_property
    def by_class(self) -> dict[str, 'ViolationList']:
        """Return lists of violations grouped by class, sorted by max severity."""
        by_class = collections.defaultdict(list)
        for v in self.violations:
            by_class[v.__class__.__name__].append(v)

        if len(by_class) == 0:
            # If there are no violations, return an empty dict.
            return {}  # pragma: no cover
        elif len(by_class) == 1:
            # If there are only violations of one class, return self.
            return {  # pragma: no cover
                next(iter(by_class)): self,
            }

        # Otherwise return a new container instance for every class.
        ret = {
            class_name: ViolationList(violations)
            for class_name, violations in by_class.items()
        }
        return dict(xsorted(ret.items(), key=lambda item: (item[1], item[0])))

    @cached_property
    def max_severity(self) -> ViolationSeverity:
        return max(
            (v.severity for v in self.violations),
            default=ViolationSeverity.DEBUG,
        )

    def get(
            self, *,
            course_id: int | None = cast(int, _MISSING),
            track: models.CourseTrack | None = cast(models.CourseTrack, _MISSING),
            track_not: Collection[int] = cast(Collection[int], _MISSING),
            track_group: models.TrackGroup | None = cast(models.TrackGroup, _MISSING),
    ) -> 'ViolationList':
        """Filter and return violations matching the given criteria.

        :param course_id: If None return only violations with no course.
            If an id, return only violations with a course with that id.
        :params track: If None return only violations with no track.
            If a track, return only violations with that track.
        :param track_not: If given return only violations with no track, or with a
            track whos id is not in the given collection.
        :param track_group: Like track.
        """
        return ViolationList([
            v for v in self.violations
            if (course_id is _MISSING or (v.course is None and course_id is None or v.course is not None and v.course['id'] == course_id))
            and (track is _MISSING or v.track == track)
            and (track_not is _MISSING or v.track is None or v.track.id not in track_not)
            and (track_group is _MISSING or v.track_group == track_group)
        ])

    @cached_property
    def format(self) -> CourseStatsFormat:
        """
        Aggregate and return course stats formats.

        Sum all non-None formats from violations in this container, if they define
        the `course_stats_format` property.
        """
        return sum(
            (
                format_
                for v in self.violations
                if (format_ := getattr(v, 'course_stats_format', None))
            ),
            start=CourseStatsFormat(),
        )

    def __iter__(self) -> Iterator['ConstraintViolation']:
        yield from self.violations

    def __lt__(self, other: 'ViolationList') -> bool:
        if not isinstance(other, ViolationList):
            return NotImplemented  # type: ignore[unreachable]
        return self.get_sortkey() < other.get_sortkey()

    def get_sortkey(self) -> Sortkey:
        return (-self.max_severity.value,)


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
    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        """
        Must return a list of strings for translation and a dict of translation params.

        :param entity_page: If True, return translations for the specific entity page.
            Otherwise, return translations for the violation overview page.

        Translations for the overview page should contain a parameter named 'link',
        which should contain the link text for the link defined by `get_link_params`,
        usually the name/moniker of the primary entity, e.g. a persona name or a
        course moniker.

        Translations for the entity page typically leave out the link parameter, but
        may also leave out secondary entities, depending on how and where they are
        rendered on the entity page.
        """
        raise NotImplementedError

    def get_link_params(self) -> tuple[str, CdEDBObject]:
        """
        Return a link target and necessary parameters for linking to the primary entity.

        Link target will be something like "event/show_course", parameters will contain
        the entity id, e.g. `{'course_id': self.course_id}`.
        The link text will be the 'link' parameter from `get_translations`.

        Usually implemented in an intermediate baseclass.
        """
        raise NotImplementedError

    def __lt__(self, other: 'ConstraintViolation') -> bool:
        if not isinstance(other, ConstraintViolation):
            return NotImplemented  # type: ignore[unreachable]
        return self.get_sortkey() < other.get_sortkey()

    def get_sortkey(self) -> Sortkey:
        return (-self.severity.value, self.__class__.__name__)


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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.severity >= ViolationSeverity.ERROR:
            if entity_page:
                msg = n_("Participant in mutually exclusive parts (%(part_list)s).")
            else:
                msg = n_(
                    "%(link)s is participant in mutually exclusive"
                    " parts (%(part_list)s).",
                )
            part_filter = lambda part: (
                self.registration['parts'][part.id]['status']
                    == const.RegistrationPartStati.participant
            )
        else:
            if entity_page:
                msg = n_(
                    "Present at mutually exclusive parts (%(part_list)s).",
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:  # pragma: no cover
        if entity_page:
            msg = n_(
                "Unsynchronized course choices in synchronized tracks (%(track_list)s).",
            )
        else:
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Not assigned to a course in %(track)s.")
        else:
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.instructed_course:
            if entity_page:
                msg = n_(
                    "Does not instruct their course (%(instructed_course)s)"
                    " in %(track)s.",
                )
            else:
                msg = n_(
                    "%(link)s does not instruct their course (%(instructed_course)s)"
                    " in %(track)s.",
                )
        elif entity_page:
            msg = n_(
                "Did not choose their assigned course"
                " (%(assigned_course)s) in %(track)s.",
            )
        else:
            msg = n_(
                "%(link)s did not choose their assigned course"
                " (%(assigned_course)s) in %(track)s.",
            )

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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.registration['amount_paid'] < 0:
            if entity_page:
                msgs = [n_("Has paid a negative amount (%(amount_paid)s).")]
            else:
                msgs = [n_("%(link)s has paid a negative amount (%(amount_paid)s).")]
        elif entity_page:
            msgs = [n_("Has paid without a payment date.")]
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.persona['id'] in self.event.orgas:
            if entity_page:
                msg = n_("is orga but has not paid their fee (%(amount_owed)s).")
            else:
                msg = n_(
                    "%(link)s is orga but has not paid their fee (%(amount_owed)s).",
                )
        elif entity_page:
            msg = n_("Has not paid their fee (%(amount_owed)s).")
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.registration['amount_owed'] < 0:
            if entity_page:
                msg = n_("Owes a negative amount (%(amount_owed)s).")
            else:
                msg = n_("%(link)s owes a negative amount (%(amount_owed)s).")
        elif entity_page:
            msg = n_("Is involved but owes no fee.")
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Needs to be reimbursed (%(remaining_owed)s).")
        else:
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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Has not fully paid their fee (remaining: %(remaining_owed)s).")
        else:
            msg = n_(
                "%(link)s has not fully paid their fee (remaining: %(remaining_owed)s).",
            )

        parms = {
            "link": make_persona_name(self.persona, include_nickname=True),
            "remaining_owed": money_filter(self.registration['remaining_owed']),
        }

        return [msg], parms


@dataclasses.dataclass(frozen=True, kw_only=True)
class HiddenCourseCV(CourseConstraintViolation):
    @classmethod
    def check(  # type: ignore[override]
            cls, event: models.Event,
            course: CdEDBObject,
    ) -> Self | None:
        td = datetime.timedelta(days=7)
        ref_time = now()
        if course['is_visible']:
            return None
        if event.registration_start and event.registration_start - ref_time < td:
            # Registration starts in less than a week (or has already started).
            if (
                    event.registration_soft_limit
                    and not event.registration_hard_limit
                    and event.registration_soft_limit < ref_time
            ):
                # Registration already over, no late registration.
                severity = ViolationSeverity.INFO
            elif (
                    event.registration_hard_limit
                    and event.registration_hard_limit < ref_time
            ):
                # Late registration already over.
                severity = ViolationSeverity.DEBUG
            else:
                severity = ViolationSeverity.WARNING
        else:
            severity = ViolationSeverity.DEBUG
        return cls(
            event=event,
            severity=severity,
            course=course,
        )

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Is hidden and registration is open or about to start.")
        else:
            msg = n_("%(link)s is hidden and registration is open or about to start.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> CourseStatsFormat | None:
        return CourseStatsFormat(
            html_classes=["course-primary"],
            titles=[n_("not visible")],
        )


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

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Taking place in mutually exclusive tracks (%(track_list)s).")
        else:
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
            return cls(
                event=event,
                severity=(
                    ViolationSeverity.ERROR
                    if attendees.all else ViolationSeverity.DEBUG
                ),
                course=course,
                track=track,
                num=attendees.num,
            )
        elif track.id not in course['active_segments']:
            return cls(
                event=event,
                severity=(
                    ViolationSeverity.ERROR
                    if attendees.all else ViolationSeverity.DEBUG
                ),
                course=course,
                track=track,
                num=attendees.num,
            )
        return None

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.track.id not in self.course['segments']:
            if entity_page:
                msg = n_("Not offered in %(track)s but has %(num)s attendees.")
            else:
                msg = n_(
                    "%(link)s is not offered in %(track)s but has %(num)s attendees.",
                )
        elif entity_page:
            if self.num:
                msg = n_("Cancelled but has %(num)s attendees.")
            else:
                msg = n_("Course cancelled")
        else:
            msg = n_("%(link)s is cancelled in %(track)s but has %(num)s attendees.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num,
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> CourseStatsFormat | None:
        title = (
            n_("Course cancelled, has Attendees")
            if self.num else n_("Course cancelled")
        )
        return CourseStatsFormat(
            html_classes=["course-cancelled" if self.num else "course-cancelled-ok"],
            titles=[title],
            icons=[("ban", title)],
        )


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
                    and attendees.num_learners < course['min_size']
                    or
                    course['max_size'] is not None
                    and attendees.num_learners > course['max_size']
            ):
                return cls(
                    event=event,
                    severity=(
                        ViolationSeverity.WARNING if attendees.num_learners
                        else ViolationSeverity.DEBUG
                    ),
                    course=course,
                    track=track,
                    num=attendees.num_learners,
                )
            if (
                    course['max_size'] is not None
                    and attendees.num_learners == course['max_size']
            ):
                return cls(
                    event=event,
                    severity=ViolationSeverity.DEBUG,
                    course=course,
                    track=track,
                    num=attendees.num_learners,
                )
        return None

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.course['min_size'] is not None and self.num < self.course['min_size']:
            if entity_page:
                msg = n_("Too few attendees (%(num)s < %(min_size)s).")
            else:
                msg = n_(
                    "%(link)s has too few attendees (%(num)s < %(min_size)s)"
                    " in %(track)s.",
                )
        elif self.course['max_size'] is not None and self.num > self.course['max_size']:
            if entity_page:
                msg = n_("Too many attendees (%(num)s > %(max_size)s).")
            else:
                msg = n_("%(link)s has too many attendees (%(num)s > %(max_size)s)"
                         " in %(track)s.")
        else:
            return [], {}
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "num": self.num,
            "track": self.track.shortname,
            "min_size": self.course['min_size'],
            "max_size": self.course['max_size'],
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> CourseStatsFormat | None:
        if self.course['min_size'] is not None and self.num < self.course['min_size']:
            return CourseStatsFormat(
                html_classes=["course-too-few"],
                titles=[n_("Not enough Attendees")],
            )
        elif self.course['max_size'] is not None and self.num > self.course['max_size']:
            return CourseStatsFormat(
                html_classes=["course-too-many"],
                titles=[n_("Too many Attendees")],
            )
        else:
            title = n_("Exactly full")
            return CourseStatsFormat(
                html_classes=["course-exactly-full"],
                titles=[title],
                # icons=[("maximize", title)],
            )


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
            if bool(attendees.learners) != bool(attendees.instructors):  # pylint: disable=line-too-long
                return cls(
                    event=event,
                    severity=ViolationSeverity.INFO,
                    course=course,
                    track=track,
                    num_learners=attendees.num_learners,
                    num_instructors=attendees.num_instructors,
                )
        return None

    def get_translation(
            self, *, entity_page: bool = True,
    ) -> tuple[list[str], CdEDBObject]:
        if self.num_learners:
            if entity_page:
                msg = n_("%(num)s attendees but no instructors.")
            else:
                msg = n_("%(link)s has %(num)s attendees but no instructors in %(track)s.")
        elif entity_page:
            msg = n_("%(num)s instructors but no attendees.")
        else:
            msg = n_("%(link)s has %(num)s instructors but no attendees in %(track)s.")
        params = {
            "link": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num_learners or self.num_instructors,
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> CourseStatsFormat | None:
        title = n_("Lonely attendees") if self.num_learners else n_("Lonely instructors")
        icon = "balance-scale-left" if self.num_learners else "balance-scale-right"
        return CourseStatsFormat(
            titles=[title],
            icons=[(icon, title)],
        )
