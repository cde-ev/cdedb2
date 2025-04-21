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
import inspect
import itertools
from collections.abc import Collection, Iterable
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, Self, cast

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    AgeClasses,
    CdEDBObject,
    CdEDBObjectMap,
    determine_age_class,
    make_persona_name,
    n_,
    now,
)
from cdedb.common.sorting import Sortkey, xsorted
from cdedb.filter import keydictsort_filter, money_filter

if TYPE_CHECKING:
    from cdedb.frontend.event.course import AttendeeStats, ChoiceStats
    from cdedb.frontend.event.lodgement import LodgementInhabitants


td = datetime.timedelta


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
class ViolationFormat:
    """Helper class for storing and aggregating formatting specs."""

    # List of html classes to be added to the relevant html tag.
    html_classes: list[str] = dataclasses.field(default_factory=list)
    # List of hover titles to be added to that same element.
    titles: list[str] = dataclasses.field(default_factory=list)
    # List of icons to be displayed near that element, each with it's own hover title.
    icons: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def __add__(self, other: 'ViolationFormat') -> 'ViolationFormat':
        return self.__class__(
            html_classes=self.html_classes + other.html_classes,
            titles=self.titles + other.titles,
            icons=self.icons + other.icons,
        )

    @cached_property
    def html_class(self) -> str:
        return " ".join(xsorted(self.html_classes, reverse=True))

    def get_title(self, g: Callable[[str], str]) -> str:
        """Translate titles with the passed gettext. Join with newlines."""
        return "\n".join(map(g, self.titles))


_MISSING = object()


class ViolationList(list['ConstraintViolation']):
    """Container class for a list of violations.

    Provides sorting, grouping and aggregation.
    """

    def __init__(self, __iterable: 'Iterable[ConstraintViolation | None]' = ()) -> None:
        super().__init__(filter(None, __iterable))

    @cached_property
    def by_class(self) -> dict[str, 'ViolationList']:
        """Return lists of violations grouped by class, sorted by max severity."""
        by_class = collections.defaultdict(list)
        for v in self:
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
            (v.severity for v in self),
            default=ViolationSeverity.DEBUG,
        )

    def get(
            self, *,
            course_id: int | None = cast(int, _MISSING),
            lodgement_id: int | None = cast(int, _MISSING),
            registration_id: int | None = cast(int, _MISSING),
            track: models.CourseTrack | None = cast(models.CourseTrack, _MISSING),
            track_not: Collection[int] = cast(Collection[int], _MISSING),
            track_group: models.TrackGroup | None = cast(models.TrackGroup, _MISSING),
            part: models.EventPart | None = cast(models.EventPart, _MISSING),
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
            v for v in self
            if (course_id is _MISSING
                    or v.course is None and course_id is None
                    or v.course is not None and v.course['id'] == course_id
                    or (assigned_course := getattr(v, 'assigned_course', None)) is not None and assigned_course['id'] == course_id
                    or (instructed_course := getattr(v, 'instructed_course', None)) is not None and instructed_course['id'] == course_id
                )
            and (lodgement_id is _MISSING
                     or v.lodgement is None and lodgement_id is None
                     or v.lodgement is not None and v.lodgement['id'] == lodgement_id
                 )
            and (registration_id is _MISSING
                    or v.registration is None and registration_id is None
                    or v.registration is not None and v.registration['id'] == registration_id
                 )
            and (track is _MISSING or v.track == track)
            and (track_not is _MISSING or v.track is None or v.track.id not in track_not)
            and (track_group is _MISSING or v.track_group == track_group)
            and (part is _MISSING or v.part == part)
        ])

    @cached_property
    def course_stats_format(self) -> ViolationFormat:
        """
        Aggregate and return course stats formats.

        Sum all non-None formats from violations in this container, if they define
        the `course_stats_format` property.
        """
        return sum(
            (
                format_
                for v in self
                if (format_ := getattr(v, 'course_stats_format', None))
            ),
            start=ViolationFormat(),
        )

    @cached_property
    def lodgement_stats_format(self) -> ViolationFormat:
        return sum(
            (
                format_
                for v in self
                if (format_ := getattr(v, 'lodgement_stats_format', None))
            ),
            start=ViolationFormat(),
        )

    @cached_property
    def regular_inhabitant_stats_format(self) -> ViolationFormat:
        return sum(
            (
                format_
                for v in self
                if (format_ := getattr(v, 'regular_inhabitant_stats_format', None))
            ),
            start=ViolationFormat(),
        )

    @cached_property
    def camping_mat_inhabitant_stats_format(self) -> ViolationFormat:
        return sum(
            (
                format_
                for v in self
                if (format_ := getattr(v, 'camping_mat_inhabitant_stats_format', None))
            ),
            start=ViolationFormat(),
        )

    def __lt__(self, other: 'list[ConstraintViolation] | ViolationList') -> bool:
        if not isinstance(other, ViolationList):
            return NotImplemented
        return self.get_sortkey() < other.get_sortkey()

    def get_sortkey(self) -> Sortkey:
        return (-self.max_severity.value,)

    def append(self, __object: 'ConstraintViolation | None') -> None:
        if __object is not None:
            super().append(__object)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ViolationAux:
    """Container for passing event data through to Violations for instantiation."""
    event: models.Event
    registrations: CdEDBObjectMap
    personas: CdEDBObjectMap

    all_courses: CdEDBObjectMap
    courses: CdEDBObjectMap  # Violations are only checked for these courses.
    all_lodgements: CdEDBObjectMap
    lodgements: CdEDBObjectMap  # Violations are only checked for these lodgements.

    attendee_data: "AttendeeStats"
    choices_data: "ChoiceStats"
    inhabitants_data: "dict[int, dict[int, LodgementInhabitants]]"

    def evaluate_all(self) -> ViolationList:
        ret = ConstraintViolation.dispatch(self, ViolationContext())
        ret.sort()
        return ret


@dataclasses.dataclass(frozen=True, kw_only=True)
class ViolationContext:
    """Container for specifying the context under which to evaluate a violation.

    E.g. when evualuating a violation for every registration, that violation will be
    checked multiple times with different contexts.

    A context can be added to to create a new context, e.g. when evaluating a violation
    for every part of every registration, that violation will be checked multiple times
    with the same base context (containing only the registration) augmented with the
    different parts. Adding to a context via the `.add()` method returns a new context,
    usually with one or more fields being overwritten.
    """

    registration: CdEDBObject | None = None
    course: CdEDBObject | None = None
    lodgement: CdEDBObject | None = None

    part: models.EventPart | None = None
    track: models.CourseTrack | None = None
    part_group: models.PartGroup | None = None
    track_group: models.TrackGroup | None = None

    def add(self, **kwargs: Any) -> Self:
        """Create a new context by overwriting any field with the given kwarg."""
        return self.__class__(**{**vars(self), **kwargs})


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConstraintViolation(abc.ABC):
    """Abstract base class for all event violations.

    Actual violations must be non-abstract subclasses implementing the constructor
    and display interfaces.

    - Constructor:
        - `check(cls, aux, context) -> Self | None`
            - Takes all potentially relevant data and returns an instance if something
              is amiss, None otherwise.
    - Display:
        - `get_translation(self, *, enity_page) -> tuple[list[str], CdEDBobject]`
            - Returns a list of messages to be displayed for this violation and page.
              These are translated individually and then formatted with the parameters.

    Abstract subclasses define different kinds of violations (e,g, violations
    concerning registrations, courses, lodgements, etc.).

    All violation subclasses are evaluated and constructed automatically via the
    `dispatch` constructor. To make this work, an abstract subclass need only define
    the additional context needed for the evaluation ob its non-abstract children.
    """
    event: models.Event
    severity: ViolationSeverity

    # Primary entities.
    registration: CdEDBObject | None = None

    @property
    def persona(self) -> CdEDBObject:
        if self.registration:
            return self.registration['persona']
        raise NameError

    course: CdEDBObject | None = None
    lodgement: CdEDBObject | None = None

    # Secondary entities.
    part: models.EventPart | None = None
    track: models.CourseTrack | None = None
    part_group: models.PartGroup | None = None
    track_group: models.TrackGroup | None = None

    # Constructor interface.
    @classmethod
    @abc.abstractmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Take event and entity data and decide if there is a violation for the given
        context.

        If so, returns a new violation instance, otherwise None.
        """
        raise NotImplementedError

    # Display interface.
    @abc.abstractmethod
    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        """
        Return a list of messages to be translated individually and then displayed with
        the translation params.

        :param entity_page: If empty, return display messages for the overview page.
            Otherwise, return display messages for the given entity page.

        For the overview page, the message should contain a placeholder for primary
        entities, while the parameters should contain the name/title/moniker of that
        entity, e.g. a persona name or a course moniker.
        These placeholders are automatically replaced with a link to that entities page.

        For an entity page, that entitys placeholder is left out, but secondary
        entities might also be left out, depending on how and where the violation is
        displayed on that page.
        """
        raise NotImplementedError

    def get_link_params(self) -> dict[str, tuple[str, CdEDBObject]]:
        """
        Return link targets and necessary parameters for linking to primary entities.

        Link target will be something like "event/show_course", parameters will contain
        the entity id, e.g. `{'course_id': self.course['id']}`.
        The link text will be the corresponding parameter from `get_translations`.

        Need only be overridden if a subclass has additional associated primary entities.
        """
        ret = {}
        if self.registration:
            ret['registration'] = (
                "event/show_registration",
                {'registration_id': self.registration['id']},
            )
        if self.course:
            ret['course'] = (
                "event/show_course",
                {'course_id': self.course['id']},
            )
        if self.lodgement:
            ret['lodgement'] = (
                "event/show_lodgement",
                {'lodgement_id': self.lodgement['id']},
            )
        return ret

    def __lt__(self, other: 'ConstraintViolation') -> bool:
        if not isinstance(other, ConstraintViolation):
            return NotImplemented  # type: ignore[unreachable]
        return self.get_sortkey() < other.get_sortkey()

    def get_sortkey(self) -> Sortkey:
        return (-self.severity.value, self.__class__.__name__)

    @classmethod
    def get_contexts(
            cls, aux: ViolationAux, context: ViolationContext,
    ) -> list[ViolationContext]:
        """
        Classmethod for adding additional context for subclasses.

        Overriding this is the primary way an abstract subclass
        defines what context is needed for its children.

        Overrides by subclasses should not call the parent implementation,
        since this is called by the `dispatch` from the base class to the
        subclasses automatically.

        The returned contexts should be derived from the received context.
        """
        return [context]

    @classmethod
    def dispatch(cls, aux: ViolationAux, context: ViolationContext) -> ViolationList:
        """
        Return a list of instances of this classes children, by automatically
        delegationg the construction to those subclasses.

        Abstract subclasses are responsible for defining what context is needed for
        their children by overriding the `get_contexts` classmethod. This works
        without needing to override the implementation of the `dispatch` classmethod.`


        First create a list of derived contexts from the given context via
        `get_contexts`, then iterate over all subclasses:

        - For abstract subclasses, call that subclasses `dispatch` with each derived
            context to further dispatch the evaluation of it's children.
            This returns a list of violation instances each.
        - For non-abstract subclasses, call that subclasses `check` to evaluate each
            derived context.
            This returns a single violation instance (or None) each.
            (`ViolationList.append` automatically skips appending None).

        Gather all of these violations and return the resulting list.
        """
        ret = ViolationList()

        for new_context in cls.get_contexts(aux, context):
            for cv in cls.__subclasses__():
                if inspect.isabstract(cv):
                    ret += cv.dispatch(aux, new_context)
                    continue
                ret.append(cv.check(aux, new_context))

        return ret


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationConstraintViolation(ConstraintViolation, abc.ABC):
    registration: CdEDBObject

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        """
        Create a context for every registration. Add persona into registration.
        Add some derived data (age, remaining owed).
        """

        for registration_ in aux.registrations.values():

            persona = aux.personas[registration_['persona_id']]
            registration_['persona'] = persona
            registration_['age'] = determine_age_class(
                persona['birthday'], aux.event.begin)
            registration_['remaining_owed'] = \
                registration_['amount_owed'] - registration_['amount_paid']

            for part in aux.event.parts.values():
                registration_['parts'][part.id]['age'] = determine_age_class(
                    persona['birthday'], part.part_begin)

        return [
            context.add(registration=registration)
            for registration in aux.registrations.values()
        ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationPartConstraintViolation(RegistrationConstraintViolation, abc.ABC):
    part: models.EventPart

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [context.add(part=part) for part in aux.event.parts.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationTrackConstraintViolation(RegistrationConstraintViolation, abc.ABC):
    track: models.CourseTrack

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [context.add(track=track) for track in aux.event.tracks.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationPartGroupConstraintViolation(RegistrationConstraintViolation, abc.ABC):
    part_group: models.PartGroup

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [
            context.add(part_group=part_group)
            for part_group in aux.event.part_groups.values()
        ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationTrackGroupConstraintViolation(RegistrationConstraintViolation, abc.ABC):
    track_group: models.TrackGroup

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [
            context.add(track_group=track_group)
            for track_group in aux.event.track_groups.values()
        ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseConstraintViolation(ConstraintViolation, abc.ABC):
    course: CdEDBObject

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [context.add(course=course) for course in aux.courses.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseTrackConstraintViolation(CourseConstraintViolation, abc.ABC):
    track: models.CourseTrack

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [context.add(track=track) for track in aux.event.tracks.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseTrackGroupConstraintViolation(CourseConstraintViolation, abc.ABC):
    track_group: models.TrackGroup

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [
            context.add(track_group=track_group)
            for track_group in aux.event.track_groups.values()
        ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class LodgementConstraintViolation(ConstraintViolation, abc.ABC):
    lodgement: CdEDBObject

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [
            context.add(lodgement=lodgement)
            for lodgement in aux.lodgements.values()
        ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class LodgementPartConstraintViolation(LodgementConstraintViolation, abc.ABC):
    part: models.EventPart

    @classmethod
    def get_contexts(cls, aux: ViolationAux, context: ViolationContext) -> list[ViolationContext]:
        return [context.add(part=part) for part in aux.event.parts.values()]


@dataclasses.dataclass(frozen=True, kw_only=True)
class MutuallyExclusiveParticipationCV(RegistrationPartGroupConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation If the given registration is present at competing parts.

        Depending on the exact status, the violation can have a different severity.
        """
        assert context.registration is not None
        assert context.part_group is not None
        registration = context.registration
        part_group = context.part_group

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
                event=aux.event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
                part_group=part_group,
            )

        is_present_parts = {
            part_id for part_id in part_group.parts
            if registration['parts'][part_id]['status'].is_present()
        }
        if len(is_present_parts) > 1:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
                part_group=part_group,
            )

        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.severity >= ViolationSeverity.ERROR:
            if entity_page:
                msg = n_("Participant in mutually exclusive parts (%(part_list)s).")
            else:
                msg = n_(
                    "%(registration)s is participant in mutually exclusive"
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
                    "%(registration)s is present at mutually exclusive parts (%(part_list)s).",
                )
            part_filter = lambda part: (
                self.registration['parts'][part.id]['status'].is_present()
            )
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "part_list": ", ".join(
                part.shortname for part in xsorted(self.part_group.parts.values())
                if part_filter(part)
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class CourseChoiceSyncCV(RegistrationTrackGroupConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration has unynced course choices.

        The backend should always ensure, that this cannot occur, so such a
        violation has a critical severity if it does occur.
        """
        assert context.registration is not None
        assert context.track_group is not None
        registration = context.registration
        track_group = context.track_group

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
                event=aux.event,
                severity=ViolationSeverity.CRITICAL,
                registration=registration,
                track_group=track_group,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:  # pragma: no cover
        if entity_page:
            msg = n_(
                "Unsynchronized course choices in synchronized tracks (%(track_list)s).",
            )
        else:
            msg = n_(
                "%(registration)s has unsynchrozied course choices in synchronized"
                " tracks (%(track_list)s).",
            )
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "track_list": ", ".join(
                track.shortname for track in xsorted(self.track_group.tracks.values())
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NoCourseAssignedCV(RegistrationTrackConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration has no assigned course.

        Severity of DEBUG for registrations which are unlikely to need a course.
        """
        assert context.registration is not None
        assert context.track is not None
        registration = context.registration
        track = context.track

        reg_track = registration['tracks'][track.id]
        reg_part = registration['parts'][track.part_id]
        if not reg_part['status'].is_present():
            return None
        if reg_track['course_id'] is None:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.DEBUG if (
                        registration['persona']['id'] in aux.event.orgas
                        or reg_part['age'] == AgeClasses.u10
                        or reg_part['status'] != const.RegistrationPartStati.participant
                ) else ViolationSeverity.WARNING,
                registration=registration,
                track=track,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Not assigned to a course in %(track)s.")
        else:
            msg = n_("%(registration)s is not assigned to a course in %(track)s.")
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "track": self.track.shortname,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectCourseAssignedCV(RegistrationTrackConstraintViolation):
    assigned_course: CdEDBObject | None
    instructed_course: CdEDBObject | None = None

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration is assigned to an unchosen course.

        Make the violation a warning if an instructor is not assigned to their
        instructed course event though it takes place.
        """
        assert context.registration is not None
        assert context.track is not None
        registration = context.registration
        track = context.track

        reg_track = registration['tracks'][track.id]
        reg_part = registration['parts'][track.part_id]

        assigned_course: CdEDBObject | None = aux.all_courses.get(
            reg_track['course_id'])
        instructed_course: CdEDBObject | None = aux.all_courses.get(
            reg_track['course_instructor'])

        if not reg_part['status'].is_present():
            return None
        if (
                instructed_course
                and track.id in instructed_course['active_segments']
                and (
                    assigned_course is None
                    or instructed_course['id'] != assigned_course['id']
                )
        ):
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
                track=track,
                assigned_course=assigned_course,
                instructed_course=instructed_course,
            )
        if assigned_course is None:
            return None
        if (
                assigned_course['id'] not in reg_track['choices']
                and (
                    instructed_course is None
                    or assigned_course['id'] != instructed_course['id']
                )
        ):
            return cls(
                event=aux.event,
                severity=ViolationSeverity.INFO,
                registration=registration,
                track=track,
                assigned_course=assigned_course,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.instructed_course:
            if entity_page == "registration":
                msg = n_(
                    "Does not instruct their course (%(instructed_course)s)"
                    " in %(track)s.",
                )
            elif entity_page == "course":
                msg = n_(
                    "%(registration)s (Instructor) is not assigned to this course.",
                )
            else:
                msg = n_(
                    "%(registration)s does not instruct their course"
                    " (%(instructed_course)s) in %(track)s.",
                )
        elif entity_page == "registration":
            msg = n_(
                "Did not choose their assigned course"
                " (%(assigned_course)s) in %(track)s.",
            )
        elif entity_page == "course":
            msg = n_("%(registration)s did not choose this course.")
        else:
            msg = n_(
                "%(registration)s did not choose their assigned course"
                " (%(assigned_course)s) in %(track)s.",
            )

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "track": self.track.shortname,
            "assigned_course":
                f"{self.assigned_course['nr']}. {self.assigned_course['shortname']}"
                if self.assigned_course else None,
            "instructed_course":
                f"{self.instructed_course['nr']}. {self.instructed_course['shortname']}"
                if self.instructed_course else None,
        }
        return [msg], params

    def get_link_params(self) -> dict[str, tuple[str, CdEDBObject]]:
        ret = super().get_link_params()
        if self.assigned_course:
            ret['assigned_course'] = (
                "event/show_course",
                {'course_id': self.assigned_course['id']},
            )
        if self.instructed_course:
            ret['instructed_course'] = (
                "event/show_course",
                {'course_id': self.instructed_course['id']},
            )
        return ret


@dataclasses.dataclass(frozen=True, kw_only=True)
class InconsistentPaymentCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration has an inconsistent payment status.

        Make the violation critical for a negative amount paid and an error for a
        missing payment date.
        """
        assert context.registration is not None
        registration = context.registration

        if registration['amount_paid'] < 0:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.CRITICAL,
                registration=registration,
            )
        if registration['amount_paid'] > 0 and registration['payment'] is None:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
            )
        return None

    def get_translation(
            self, *, entity_page: str = "registration",
    ) -> tuple[list[str], CdEDBObject]:
        if self.registration['amount_paid'] < 0:
            if entity_page:
                msgs = [n_("Has paid a negative amount (%(amount_paid)s).")]
            else:
                msgs = [n_("%(registration)s has paid a negative amount (%(amount_paid)s).")]
        elif entity_page:
            msgs = [n_("Has paid without a payment date.")]
        else:
            msgs = [n_("%(registration)s has paid without a payment date.")]

        msgs.append(n_("This likely means someone entered invalid payment data."))

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "amount_paid": money_filter(self.registration['amount_paid']),
        }
        return msgs, params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NotPaidCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration owes money but hasn't paid.

        Make the violation an info for orgas.
        """
        assert context.registration is not None
        registration = context.registration

        if registration['amount_paid'] == 0 and registration['amount_owed'] > 0:
            if any(reg_part['status'] == const.RegistrationPartStati.participant
                   for reg_part in registration['parts'].values()):
                return cls(
                    event=aux.event,
                    severity=(
                        ViolationSeverity.INFO if registration['persona_id'] in aux.event.orgas
                        else ViolationSeverity.ERROR
                    ),
                    registration=registration,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msgs = [n_("Has not paid their fee (%(amount_owed)s).")]
        else:
            msgs = [n_("%(registration)s has not paid their fee (%(amount_owed)s).")]

        if self.persona['id'] in self.event.orgas:
            msgs.append(n_("(They are orga)."))

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "amount_owed": money_filter(self.registration['amount_owed']),
        }

        return msgs, params


@dataclasses.dataclass(frozen=True, kw_only=True)
class ZeroAmountOwedCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration is involved but owes no money.

        Skip this if the event has no fees.

        Severity of DEBUG for orgas.
        """
        assert context.registration is not None
        registration = context.registration

        if not aux.event.fees:
            return None
        if registration['amount_owed'] == 0:
            if any(reg_part['status'].is_involved()
                   for reg_part in registration['parts'].values()):
                return cls(
                    event=aux.event,
                    severity=(
                        ViolationSeverity.DEBUG if registration['persona_id'] in aux.event.orgas
                        else ViolationSeverity.INFO
                    ),
                    registration=registration,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Is involved but owes no fee.")
        else:
            msg = n_("%(registration)s is involved but owes no fee.")

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
        }

        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NegativeAmountOwedCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration owes a negative amount of money.
        """
        assert context.registration is not None
        registration = context.registration

        if registration['amount_owed'] < 0:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.ERROR,
                registration=registration,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Owes a negative amount (%(amount_owed)s).")
        else:
            msg = n_("%(registration)s owes a negative amount (%(amount_owed)s).")

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "amount_owed": money_filter(self.registration['amount_owed']),
        }

        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class NegativeRemainingOwedCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration has a negative remaining owed, i.e. has
        paid too much and needs a reimbursement.

        Make this a warning once the event has been archived.
        """
        assert context.registration is not None
        registration = context.registration

        if registration['remaining_owed'] < 0:
            return cls(
                event=aux.event,
                severity=(
                    ViolationSeverity.WARNING if aux.event.is_archived
                    else ViolationSeverity.INFO
                ),
                registration=registration,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Needs to be reimbursed (%(remaining_owed)s).")
        else:
            msg = n_("%(registration)s needs to be reimbursed (%(remaining_owed)s).")
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "remaining_owed": money_filter(-self.registration['remaining_owed']),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class RemainingOwedCV(RegistrationConstraintViolation):
    min_involved_part_begin: datetime.date

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration has paid some but not all of their fee.

        Make this an error once their participation has begun.
        """
        assert context.registration is not None
        registration = context.registration

        if registration['remaining_owed'] > 0 and registration['amount_paid'] > 0:
            if any(reg_part['status'].is_involved()
                   for reg_part in registration['parts'].values()):
                min_involved_part_begin = min(
                    aux.event.parts[part_id].part_begin
                    for part_id, reg_part in registration['parts'].items()
                    if reg_part['status'].is_involved()
                )
                return cls(
                    event=aux.event,
                    severity=(
                        ViolationSeverity.ERROR
                        if min_involved_part_begin < now().date()
                        else ViolationSeverity.WARNING
                    ),
                    registration=registration,
                    min_involved_part_begin=min_involved_part_begin,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Has not fully paid their fee (remaining: %(remaining_owed)s).")
        else:
            msg = n_(
                "%(registration)s has not fully paid their fee (remaining: %(remaining_owed)s).",
            )

        parms = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "remaining_owed": money_filter(self.registration['remaining_owed']),
        }

        return [msg], parms


@dataclasses.dataclass(frozen=True, kw_only=True)
class AbsentCheckedinCV(RegistrationConstraintViolation):
    shall_be_present_at_all: bool

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if a persona should not be checked in, but is.

        If they are checked in even though they are is not present in the relevant part,
        return an INFO. If they are not present at all, return an ERROR.
        If they have not been checked out even though they should have been, return an
        INFO as well.
        """
        assert context.registration is not None
        registration = context.registration

        # sorting this is relevant for checkout validity, thus sort by part end
        is_present_parts = {
            part_id: part for part_id, part in keydictsort_filter(
                aux.event.parts, sortkey=lambda part: part.part_end)
            if registration['parts'][part_id]['status'].is_present()
        }

        if not is_present_parts:
            if registration['checkin_periods']:
                return cls(
                    event=aux.event,
                    severity=ViolationSeverity.ERROR,
                    registration=registration,
                    shall_be_present_at_all=False,
                )

        ref_time = now().date()
        day = datetime.timedelta(days=1)
        for period in registration['checkin_periods']:
            valid_checkin_time = valid_checkout_time = False
            has_successor = False
            for part in is_present_parts.values():
                # look if period starts within some part where you should be present
                if part.part_begin <= period.checkin_time.date() < part.part_end:
                    valid_checkin_time = True
                    valid_checkout_time = True
                    has_successor = True  # dummy, to trigger check below
                if has_successor:  # You were present in a previous part...
                    # ... but may you stay until a following part?
                    has_successor = any(
                        other.part_begin - day <= part.part_end < other.part_end
                        for other in is_present_parts.values())
                # You must check out within this part
                # or participate in a directly succeeding part.
                if (period.checkout_time
                        and period.checkout_time.date() <= part.part_end):
                    break
                elif valid_checkin_time and not has_successor:
                    valid_checkout_time = part.part_end >= ref_time
                    break
            if not (valid_checkin_time and valid_checkout_time):
                return cls(
                    event=aux.event,
                    severity=ViolationSeverity.INFO,
                    registration=registration,
                    shall_be_present_at_all=True,
                )
        return None

    def get_translation(
        self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.shall_be_present_at_all:
            if entity_page:
                msg = n_("Is checked in, but should not be at these times.")
            else:
                msg = n_("%(registration)s is checked in, but should not be at these times.")
        elif entity_page:
            msg = n_("Is checked in, but was never present.")
        else:
            msg = n_("%(registration)s is checked in, but was never present.")
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class PresentNeverCheckedinCV(RegistrationPartConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if a persona should be checked in, but is not.

        If a registration is participant and not checked in after the first day of the
        part, return a WARNING. If at the end of the respective part, they still never
        checked in, return an ERROR.
        """
        assert context.registration is not None
        assert context.part is not None
        registration = context.registration
        part = context.part

        ref_time = now().date()
        if not (registration['parts'][part.id]['status'].is_present()
                and ref_time > part.part_begin):
            return None
        valid_checkin_time = False
        for period in registration['checkin_periods']:
            if (period.checkin_time.date() <= part.part_end
                    and (not period.checkout_time
                         or period.checkout_time.date() > part.part_begin)):
                valid_checkin_time = True
                break
        if not valid_checkin_time:
            return cls(
                event=aux.event,
                severity=(
                    ViolationSeverity.ERROR
                    if ref_time > part.part_end else
                    ViolationSeverity.WARNING),
                registration=registration,
                part=part,
            )
        return None

    def get_translation(
        self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if now().date() > self.part.part_end:
            if entity_page:
                msg = n_("Was present in %(part)s , but never checked in.")
            else:
                msg = n_("%(registration)s was present in %(part)s, but never checked in.")
        elif entity_page:
            msg = n_("Will be present in %(part)s, but has not checked in yet.")
        else:
            msg = n_("%(registration)s will be present in %(part)s, but has not checked in yet.")
        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "part": self.part.shortname,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class MissingMinorFormCV(RegistrationConstraintViolation):
    participant_begin: datetime.date

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if a registration is a minor (while present) but
        parental consent is missing.

        Make this an error 30 days before they will be present.
        """
        assert context.registration is not None
        registration = context.registration

        min_participating_part = min(
            (
                ep for ep in aux.event.parts.values()
                if registration['parts'][ep.id]['status'].is_present()
            ),
            key=lambda ep: ep.part_begin,
            default=None,
        )
        if (
                min_participating_part
                and registration['parts'][min_participating_part.id]['age'].is_minor()
                and not registration['parental_agreement']
        ):
            return cls(
                event=aux.event,
                severity=(
                    ViolationSeverity.ERROR
                    if min_participating_part.part_begin - now().date() < td(days=30)
                    else ViolationSeverity.WARNING
                ),
                registration=registration,
                participant_begin=min_participating_part.part_begin,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Is present, but parental consent is missing.")
        else:
            msg = n_("%(registration)s is present, but parental consent is missing.")

        msgs = [msg]
        if self.participant_begin - now().date() < td(days=30):
            msgs.append(n_("Will be present in less than a month."))

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
        }
        return msgs, params


@dataclasses.dataclass(frozen=True, kw_only=True)
class IllegalMixedLodgingCV(RegistrationConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if a registration has consented to mixed lodging, even
        though they are too young.
        """
        assert context.registration is not None
        registration = context.registration

        min_participating_part = min(
            (
                ep for ep in aux.event.parts.values()
                if registration['parts'][ep.id]['status'].is_present()
            ),
            key=lambda ep: ep.part_begin,
            default=None,
        )
        if (
            min_participating_part
            and not registration['parts'][min_participating_part.id]['age'].may_mix()
            and registration['mixed_lodging']
        ):
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Too young for mixed lodging.")
        else:
            msg = n_("%(registration)s is too young for mixed lodging.")

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectCampingMatAssignmentCV(RegistrationPartConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation of a registration is assigned to a camping mat, but
        has not consented o that.

        Skip this if no camping mat consent field is set (for the given part).
        """
        assert context.registration is not None
        assert context.part is not None
        registration = context.registration
        part = context.part

        if not part.camping_mat_field:
            return None
        if (
                registration['parts'][part.id]['is_camping_mat']
                and not registration['fields'].get(part.camping_mat_field.field_name)
        ):
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                registration=registration,
                lodgement=aux.all_lodgements.get(
                    registration['parts'][part.id]['lodgement_id']),
                part=part,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page == "registration":
            msgs = [
                n_("Assigned to, but may not sleep on a camping mat in %(part)s."),
            ]
            if self.lodgement:
                msgs.append(n_("(Lodgement: %(lodgement)s)"))
        elif entity_page == "lodgement":
            msgs = [
                n_("%(registration)s is assigned to, but may not sleep on a camping mat."),
            ]
        else:
            msgs = [
                n_("%(registration)s is assigned to, but may not sleep on a camping mat"
                   " in %(part)s."),
            ]
            if self.lodgement:
                msgs.append(n_("(Lodgement: %(lodgement)s)"))

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "part": self.part.shortname,
            "lodgement": self.lodgement['title'] if self.lodgement else "",
        }
        return msgs, params

    @cached_property
    def camping_mat_inhabitant_stats_format(self) -> ViolationFormat | None:
        return ViolationFormat(
            html_classes=["lodgement-illegal-camping-mat"],
            titles=[
                n_("An inhabitant is assigned to, but may not sleep on a camping mat."),
            ],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class NoLodgementCV(RegistrationPartConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the registration is present but not assigned to a lodgement.

        Make this a warning for guests and an error for participants.

        Ship this if the event has no lodgements.
        """
        assert context.registration is not None
        assert context.part is not None
        registration = context.registration
        part = context.part

        reg_part = registration['parts'][part.id]
        if not reg_part['status'].is_present() or not aux.all_lodgements:
            return None
        if reg_part['lodgement_id'] is None:
            if part.part_begin <= now().date():
                return cls(
                    event=aux.event,
                    severity=(
                        ViolationSeverity.ERROR
                        if reg_part['status'] == const.RegistrationPartStati.participant
                        else ViolationSeverity.WARNING
                    ),
                    registration=registration,
                    part=part,
                )
            if part.part_begin - now().date() < td(days=7):
                return cls(
                    event=aux.event,
                    severity=(
                        ViolationSeverity.WARNING
                        if reg_part['status'] == const.RegistrationPartStati.participant
                        else ViolationSeverity.INFO
                    ),
                    registration=registration,
                    part=part,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Has no lodgement in %(part)s.")
        else:
            msg = n_("%(registration)s has no lodgement in %(part)s.")

        params = {
            "registration": make_persona_name(self.persona, include_nickname=True),
            "part": self.part.shortname,
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class HiddenCourseCV(CourseConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the course is hidden.

        Make the severity DEBUG if there is no registration start, if the start is more
        than 7 days away or if the late registration is over.
        Make it INFO if the registration is over, but late registration isn't.
        Make it WARNING otherwise.
        """
        assert context.course is not None
        course = context.course

        ref_time = now()
        event = aux.event
        if course['is_visible']:
            return None
        if event.registration_start and event.registration_start - ref_time < td(days=7):
            # Registration starts in less than a week (or has already started).
            if (
                    event.registration_soft_limit
                    and event.registration_soft_limit < ref_time
                    and (
                        not event.registration_hard_limit
                        or event.registration_hard_limit > ref_time
                    )
            ):
                # Registration already over, late registration not over.
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
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Is hidden and registration is open or about to start.")
        else:
            msg = n_("%(course)s is hidden and registration is open or about to start.")
        params = {
            "course": f"{self.course['nr']}. {self.course['shortname']}",
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> ViolationFormat | None:
        return ViolationFormat(
            html_classes=["course-primary"],
            titles=[n_("not visible")],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class MutuallyExclusiveCoursesCV(CourseTrackGroupConstraintViolation):
    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation of the course is taking place in mutually exclusive tracks.
        """
        assert context.course is not None
        assert context.track_group is not None
        course = context.course
        track_group = context.track_group

        ct = track_group.constraint_type
        if ct != const.CourseTrackGroupType.mutually_exclusive_courses:
            return None
        if len(set(course['active_segments']) & set(track_group.tracks)) > 1:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.ERROR,  # TODO: WARNING if no attendees.
                course=course,
                track_group=track_group,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Taking place in mutually exclusive tracks (%(track_list)s).")
        else:
            msg = n_(
                "%(course)s is taking place in mutually exclusive tracks (%(track_list)s).",
            )
        track_ids = set(self.course['active_segments']) & set(self.track_group.tracks)
        params = {
            "course": f"{self.course['nr']}. {self.course['shortname']}",
            "track_list": ", ".join(
                track.shortname for track in xsorted(self.track_group.tracks.values())
                if track.id in track_ids
            ),
        }
        return [msg], params


@dataclasses.dataclass(frozen=True, kw_only=True)
class CancelledWithAttendeesCV(CourseTrackConstraintViolation):
    num: int

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the course is cancelled but has attendees.

        If the course was never offered but has attendees, someone misused the
        course segments toggle. In that case this is an error, otherwise a warning.
        """
        assert context.course is not None
        assert context.track is not None
        course = context.course
        track = context.track

        attendees = aux.attendee_data.involved.get(course['id'], track.id)

        if track.id not in course['segments']:
            return cls(
                event=aux.event,
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
                event=aux.event,
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
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.track.id not in self.course['segments']:
            if entity_page:
                msg = n_("Not offered in %(track)s but has %(num)s attendees.")
            else:
                msg = n_(
                    "%(course)s is not offered in %(track)s but has %(num)s attendees.",
                )
        elif entity_page:
            if self.num:
                msg = n_("Cancelled but has %(num)s attendees.")
            else:
                msg = n_("Course cancelled")
        else:
            msg = n_("%(course)s is cancelled in %(track)s but has %(num)s attendees.")
        params = {
            "course": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num,
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> ViolationFormat | None:
        title = (
            n_("Course cancelled, has Attendees")
            if self.num else n_("Course cancelled")
        )
        return ViolationFormat(
            html_classes=["course-cancelled" if self.num else "course-cancelled-ok"],
            titles=[title],
            icons=[("ban", title)],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectNumAttendeesCV(CourseTrackConstraintViolation):
    num: int

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the course has too few or too many attendees.

        Make the severity DEBUG if no attendees are assigned yet (to this course)
        to avoid clutter.
        """
        assert context.course is not None
        assert context.track is not None
        course = context.course
        track = context.track

        attendees = aux.attendee_data.involved.get(course['id'], track.id)
        event_over = now().date() > aux.event.end

        if track.id in course['active_segments']:
            if (
                    course['min_size'] is not None
                    and attendees.num_learners < course['min_size']
                    or
                    course['max_size'] is not None
                    and attendees.num_learners > course['max_size']
            ):
                if not attendees.num_learners:
                    severity = ViolationSeverity.DEBUG
                elif event_over:
                    severity = ViolationSeverity.INFO
                else:
                    severity = ViolationSeverity.WARNING
                return cls(
                    event=aux.event,
                    severity=severity,
                    course=course,
                    track=track,
                    num=attendees.num_learners,
                )
            if (
                    course['max_size'] is not None
                    and attendees.num_learners == course['max_size']
            ):
                return cls(
                    event=aux.event,
                    severity=ViolationSeverity.DEBUG,
                    course=course,
                    track=track,
                    num=attendees.num_learners,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.course['min_size'] is not None and self.num < self.course['min_size']:
            if entity_page:
                msg = n_("Too few attendees (%(num)s < %(min_size)s).")
            else:
                msg = n_(
                    "%(course)s has too few attendees (%(num)s < %(min_size)s)"
                    " in %(track)s.",
                )
        elif self.course['max_size'] is not None and self.num > self.course['max_size']:
            if entity_page:
                msg = n_("Too many attendees (%(num)s > %(max_size)s).")
            else:
                msg = n_("%(course)s has too many attendees (%(num)s > %(max_size)s)"
                         " in %(track)s.")
        else:
            return [], {}
        params = {
            "course": f"{self.course['nr']}. {self.course['shortname']}",
            "num": self.num,
            "track": self.track.shortname,
            "min_size": self.course['min_size'],
            "max_size": self.course['max_size'],
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> ViolationFormat | None:
        if self.course['min_size'] is not None and self.num < self.course['min_size']:
            return ViolationFormat(
                html_classes=["course-too-few"],
                titles=[n_("Not enough Attendees")],
            )
        elif self.course['max_size'] is not None and self.num > self.course['max_size']:
            return ViolationFormat(
                html_classes=["course-too-many"],
                titles=[n_("Too many Attendees")],
            )
        else:
            title = n_("Exactly full")
            return ViolationFormat(
                html_classes=["course-exactly-full"],
                titles=[title],
                # icons=[("maximize", title)],
            )


@dataclasses.dataclass(frozen=True, kw_only=True)
class LonelyAttendeesCV(CourseTrackConstraintViolation):
    num_learners: int
    num_instructors: int

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """Return a violation if the course has attendees but no instructors."""
        assert context.course is not None
        assert context.track is not None
        course = context.course
        track = context.track

        attendees = aux.attendee_data.involved.get(course['id'], track.id)
        if track.id in course['active_segments']:
            if bool(attendees.learners) != bool(attendees.instructors):
                return cls(
                    event=aux.event,
                    severity=ViolationSeverity.INFO,
                    course=course,
                    track=track,
                    num_learners=attendees.num_learners,
                    num_instructors=attendees.num_instructors,
                )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if self.num_learners:
            if entity_page:
                msg = n_("%(num)s attendees but no instructors.")
            else:
                msg = n_("%(course)s has %(num)s attendees but no instructors in %(track)s.")
        elif entity_page:
            msg = n_("%(num)s instructors but no attendees.")
        else:
            msg = n_("%(course)s has %(num)s instructors but no attendees in %(track)s.")
        params = {
            "course": f"{self.course['nr']}. {self.course['shortname']}",
            "track": self.track.shortname,
            "num": self.num_learners or self.num_instructors,
        }
        return [msg], params

    @cached_property
    def course_stats_format(self) -> ViolationFormat | None:
        title = n_("Lonely attendees") if self.num_learners else n_("Lonely instructors")
        icon = "balance-scale-left" if self.num_learners else "balance-scale-right"
        return ViolationFormat(
            titles=[title],
            icons=[(icon, title)],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncorrectNumInhabitantsCV(LodgementPartConstraintViolation):
    num_regular: int
    num_camping_mat: int

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the lodgement has too many or too few inhabitants.

        Severity is complicated and depends on camping mat assignments and capacity too.
        """
        assert context.lodgement is not None
        assert context.part is not None
        lodgement = context.lodgement
        part = context.part

        inhabitants = aux.inhabitants_data[lodgement['id']][part.id]
        event_over = now().date() > aux.event.end
        severity = None

        if (
            lodgement['regular_capacity'] is not None
            and len(inhabitants.regular) > lodgement['regular_capacity']
        ):
            # For participants assigned to regular beds only, raise an error rather
            # than a warning if the lodgement is overfull.
            status = const.RegistrationPartStati.participant
            error = lodgement['regular_capacity'] < len(
                [reg for reg in inhabitants.regular
                 if reg['parts'][part.id]['status'] == status.participant])

            if event_over:
                severity = ViolationSeverity.INFO
            elif error:
                severity = ViolationSeverity.ERROR
            else:
                severity = ViolationSeverity.WARNING
        if (
            lodgement['camping_mat_capacity'] is not None
            and len(inhabitants.camping_mat) > lodgement['camping_mat_capacity']
        ):
            if event_over:
                severity = ViolationSeverity.INFO
            else:
                severity = ViolationSeverity.WARNING
        if (
            lodgement['regular_capacity'] is not None
            and 0 < len(inhabitants.regular) < lodgement['regular_capacity']
            or lodgement['camping_mat_capacity'] is not None
            and 0 < len(inhabitants.camping_mat) < lodgement['camping_mat_capacity']
        ):
            severity = ViolationSeverity.DEBUG

        if severity is None:
            return None
        return cls(
            event=aux.event,
            severity=severity,
            lodgement=lodgement,
            part=part,
            num_regular=len(inhabitants.regular),
            num_camping_mat=len(inhabitants.camping_mat),
        )

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if (
            self.lodgement['regular_capacity'] is not None
            and self.num_regular > self.lodgement['regular_capacity']
            or self.lodgement['camping_mat_capacity'] is not None
            and self.num_camping_mat > self.lodgement['camping_mat_capacity']
        ):
            if entity_page:
                msg = n_("Overfull lodgement.")
            else:
                msg = n_("%(lodgement)s is overfull in %(part)s.")
        elif entity_page:
            msg = n_("Underfull lodgement.")
        else:
            msg = n_("%(lodgement)s is underfull in %(part)s.")

        params = {
            "lodgement": self.lodgement['title'],
            "part": self.part.shortname,
        }
        return [msg], params

    @cached_property
    def regular_inhabitant_stats_format(self) -> ViolationFormat | None:
        ret = ViolationFormat()
        if (
            self.lodgement['regular_capacity'] is not None
            and self.num_regular > self.lodgement['regular_capacity']
        ):
            ret += ViolationFormat(
                html_classes=["lodgement-too-many"],
                titles=[n_("Overfull lodgement.")],
            )
        if (
            self.lodgement['regular_capacity'] is not None
            and 0 < self.num_regular < self.lodgement['regular_capacity']
        ):
            ret += ViolationFormat(
                html_classes=["lodgement-too-few"],
                titles=[n_("Underfull lodgement.")],
            )
        return ret

    @cached_property
    def camping_mat_inhabitant_stats_format(self) -> ViolationFormat | None:
        ret = ViolationFormat()
        if (
            self.lodgement['camping_mat_capacity'] is not None
            and self.num_camping_mat > self.lodgement['camping_mat_capacity']
        ):
            ret += ViolationFormat(
                html_classes=["lodgement-too-many"],
                titles=[n_("Too many camping mats.")],
            )
        if (
            self.lodgement['camping_mat_capacity'] is not None
            and 0 < self.num_camping_mat < self.lodgement['camping_mat_capacity']
        ):
            ret += ViolationFormat(
                html_classes=["lodgement-too-few"],
                titles=[n_("Not enough camping mats.")],
            )
        return ret


@dataclasses.dataclass(frozen=True, kw_only=True)
class IllegalMixedLodgementCV(LodgementPartConstraintViolation):
    not_specified: bool

    @classmethod
    def check(cls, aux: ViolationAux, context: ViolationContext) -> Self | None:
        """
        Return a violation if the lodgement has concurrent inhabitants that may not mix.
        """
        assert context.lodgement is not None
        assert context.part is not None
        lodgement = context.lodgement
        part = context.part

        inhabitants = aux.inhabitants_data[lodgement['id']][part.id]
        non_mixing_regs = [
            reg for reg in inhabitants.all
            if not reg['mixed_lodging']
        ]
        if not non_mixing_regs:
            return None
        genders = set(aux.personas[reg['persona_id']]['gender'] for reg in inhabitants.all)
        if const.Genders.not_specified in genders:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                lodgement=lodgement,
                part=part,
                not_specified=True,
            )
        if len(genders) > 1:
            return cls(
                event=aux.event,
                severity=ViolationSeverity.WARNING,
                lodgement=lodgement,
                part=part,
                not_specified=False,
            )
        return None

    def get_translation(
            self, *, entity_page: str,
    ) -> tuple[list[str], CdEDBObject]:
        if entity_page:
            msg = n_("Mixed with non-mixing inhabitants.")
        else:
            msg = n_("%(lodgement)s is mixed with non-mixing inhabitants in %(part)s.")

        params = {
            "lodgement": self.lodgement['title'],
            "part": self.part.shortname,
        }
        return [msg], params

    @cached_property
    def regular_inhabitant_stats_format(self) -> ViolationFormat | None:
        return ViolationFormat(
            html_classes=["lodgement-illegal-mixing"],
            titles=[n_("Mixed with non-mixing inhabitants.")],
        )
