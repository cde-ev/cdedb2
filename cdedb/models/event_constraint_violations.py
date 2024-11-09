"""
Classes for constraint violations in the event realm.
"""

import dataclasses
import itertools
from functools import cached_property
from typing import Self

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import CdEDBObject, make_persona_name, n_
from cdedb.common.sorting import xsorted


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConstraintViolation:
    event: models.Event
    severity: int

    registration: CdEDBObject | None = None

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

    persona: CdEDBObject | None = None

    course: CdEDBObject | None = None

    part: models.EventPart | None = None

    track: models.CourseTrack | None = None

    part_group: models.PartGroup | None = None

    track_group: models.TrackGroup | None = None

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
class MEPConstraintViolation(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
    part_group: models.PartGroup

    @classmethod
    def check(
            cls, event: models.Event,
            *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            mep_group: models.PartGroup,
    ) -> Self | None:
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
class CCSConstraintViolation(ConstraintViolation):
    registration: CdEDBObject
    persona: CdEDBObject
    track_group: models.TrackGroup

    @classmethod
    def check(
            cls, event: models.Event,
            *,
            registration: CdEDBObject,
            persona: CdEDBObject,
            ccs_group: models.TrackGroup,
    ) -> Self | None:
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
class MECConstraintViolation(ConstraintViolation):
    course: CdEDBObject
    track_group: models.TrackGroup

    @classmethod
    def check(
            cls, event: models.Event,
            *,
            course: CdEDBObject,
            mec_group: models.TrackGroup,
    ) -> Self | None:
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
