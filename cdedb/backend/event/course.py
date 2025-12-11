#!/usr/bin/env python3

"""
The `EventCourseBackend` subclasses the `EventBaseBackend` and provides functionality
for managing courses belonging to an event.
"""

import abc
import collections
from collections.abc import Collection
from typing import Optional, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.backend.common import (
    access,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    CdEDBObject,
    CdEDBOptionalMap,
    DefaultReturnCode,
    DeletionBlockers,
    PsycoJson,
    RequestState,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.privileges import (
    EventPrivileges,
    is_privileged_event as is_privileged,
)
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.database.connection import Atomizer
from cdedb.database.query import DatabaseValue_s, ParamDict


class EventCourseBackend(EventBaseBackend, abc.ABC):
    @access("anonymous")
    def list_courses(self, rs: RequestState, event_id: int) -> dict[int, str]:
        """List all courses organized via DB.

        :returns: Mapping of course ids to titles.
        """
        event_id = affirm(vtypes.ID, event_id)
        data = self.sql_select(
            rs, "event.courses", ("id", "title"), (event_id,), entity_key="event_id"
        )
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def get_courses(
        self,
        rs: RequestState,
        course_ids: Collection[int],
        *,
        _event: models.Event | None = None,
    ) -> models.CdEDataclassMap[models.Course]:
        """Retrieve data for some courses organized via DB.

        They must be associated to the same event. This contains additional
        information on the parts in which the course takes place.
        """
        course_ids = affirm_set(vtypes.ID, course_ids)
        with Atomizer(rs):
            course_data = {
                e["id"]: e
                for e in self.query_all(rs, *models.Course.get_select_query(course_ids))
            }
            if not course_data:
                return {}
            events = {e['event_id'] for e in course_data.values()}
            if len(events) > 1:
                raise ValueError(n_("Only courses from one event allowed."))
            event_id = unwrap(events)
            if _event:
                event = _event
            else:
                event = self.get_event(rs, event_id)

            segment_data = self.query_all(
                rs, *models.CourseSegment.get_select_query(course_ids)
            )

            for course in course_data.values():
                course['event'] = event
                course["segments"] = []
            for segment in segment_data:
                course_data[segment["course_id"]]["segments"].append(segment)

        return models.Course.many_from_database(course_data.values())

    class _GetCourseProtocol(Protocol):
        def __call__(self, rs: RequestState, course_id: int) -> models.Course: ...

    get_course: _GetCourseProtocol = singularize(get_courses, "course_ids", "course_id")

    @access("event")
    def set_course(
        self, rs: RequestState, course_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Update some keys of a course linked to an event organized via DB.

        If the 'segments' key is present you have to pass the complete list
        of track IDs, which will superseed the current list of tracks.

        If the 'active_segments' key is present you have to pass the
        complete list of active track IDs, which will superseed the current
        list of active tracks. This has to be a subset of the segments of
        the course.
        """
        course_id = affirm(vtypes.ID, course_id)
        ret = 1
        with Atomizer(rs):
            current = self.get_course(rs, course_id)
            data = affirm(models.Course, data, event=current.event)
            current_dict = current.as_dict()
            if not is_privileged(rs, EventPrivileges.courses_write, current.event_id):
                raise PrivilegeError
            self.assert_lock(rs, event_id=current.event_id)

            course_fields = set(models.Course.database_fields()) - {"fields"}

            changed = False
            data["id"] = course_id
            changed_data = {
                k: v
                for k, v in data.items()
                if k in course_fields and v != current_dict[k]
            }
            if changed_data:
                changed_data["id"] = current.id
                ret *= self.sql_update(rs, "event.courses", changed_data)
                changed = True

            if 'fields' in data:
                fdata = {
                    k: v
                    for k, v in data['fields'].items()
                    if k not in current.fields or v != current.fields[k]
                }
                if fdata:
                    fupdate = {'id': current.id, 'fields': fdata}
                    ret *= self.sql_json_inplace_update(
                        rs, models.Course.database_table, fupdate
                    )
                    changed = True

            if changed:
                self.event_log(
                    rs,
                    const.EventLogCodes.course_changed,
                    current.event_id,
                    change_note=current.title,
                )

            if 'segments' in data:
                ret *= self._set_course_segments(rs, data['segments'], current)

        return ret

    def _set_course_segments(
        self, rs: RequestState, segment_data: CdEDBOptionalMap, course: models.Course
    ) -> DefaultReturnCode:
        """Uninlined code from set_course."""

        self.affirm_atomized_context(rs)
        ret = 1

        if not segment_data.keys() <= course.event.tracks.keys():
            raise ValueError(n_("Invalid tracks specified."))

        deleted = {
            track_id
            for track_id, segment in segment_data.items()
            if segment is None and track_id in course.segments
        }
        new = {
            track_id: segment
            for track_id, segment in segment_data.items()
            if segment is not None and track_id not in course.segments
        }
        changed = {
            track_id: segment
            for track_id, segment in segment_data.items()
            if segment is not None
            and track_id in course.segments
            and segment != course.segments[track_id].as_dict()
        }

        cn = lambda track_id: f"{course.title} ({course.event.tracks[track_id].title})"

        if deleted:
            params: dict[str, DatabaseValue_s] = {
                "course_id": course.id,
                "track_ids": deleted,
            }
            query = f"""
                DELETE FROM {models.CourseSegment.database_table}
                WHERE course_id = %(course_id)s AND track_id = ANY(%(track_ids)s)
            """
            ret *= self.query_exec(rs, query, params)
            for track_id in xsorted(deleted):
                self.event_log(
                    rs,
                    const.EventLogCodes.course_segment_deleted,
                    course.event_id,
                    change_note=cn(track_id),
                )
                if course.segments[track_id].is_active:
                    self.event_log(
                        rs,
                        const.EventLogCodes.course_segment_deactivated,
                        course.event_id,
                        change_note=cn(track_id),
                    )

        for track_id, segment in xsorted(new.items()):
            _metadata = {"course_id": course.id, "track_id": track_id}
            segment = {**segment, **_metadata}
            ret *= self.sql_insert(rs, models.CourseSegment.database_table, segment)
            self.event_log(
                rs,
                const.EventLogCodes.course_segment_created,
                course.event_id,
                change_note=cn(track_id),
            )
            if segment["is_active"]:
                self.event_log(
                    rs,
                    const.EventLogCodes.course_segment_activated,
                    course.event_id,
                    change_note=cn(track_id),
                )

        for track_id, segment in xsorted(changed.items()):
            _metadata = {"course_id": course.id, "track_id": track_id}
            segment = {**segment, **_metadata}
            ret *= self.sql_insert(
                rs,
                models.CourseSegment.database_table,
                segment,
                update_on_conflict=True,
                conflict_target="course_id, track_id",
            )
            if segment["is_active"] != course.segments[track_id].is_active:
                if segment["is_active"]:
                    code = const.EventLogCodes.course_segment_activated
                else:
                    code = const.EventLogCodes.course_segment_deactivated
                self.event_log(rs, code, course.event_id, change_note=cn(track_id))

        return ret

    @access("event")
    def create_course(
        self, rs: RequestState, event_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Make a new course organized via DB."""
        event_id = affirm(vtypes.ID, event_id)
        event = self.get_event(rs, event_id)
        data = affirm(models.Course, data, creation=True, event=event)

        with Atomizer(rs):
            self.assert_lock(rs, event_id=event_id)
            if not is_privileged(rs, EventPrivileges.courses_write, event_id):
                raise PrivilegeError

            course_fields = set(models.Course.database_fields())
            data['fields'] = PsycoJson(data.get('fields', {}))
            data['event_id'] = event_id
            course_data = {k: v for k, v in data.items() if k in course_fields}
            new_id = self.sql_insert(rs, models.Course.database_table, course_data)
            self.event_log(
                rs,
                const.EventLogCodes.course_created,
                event_id,
                change_note=data['title'],
            )

            course = self.get_course(rs, new_id)
            self._set_course_segments(rs, data['segments'], course)
        return new_id

    @access("event")
    def delete_course_blockers(
        self, rs: RequestState, course_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a course from beeing deleted.

        Possible blockers:

        * attendees: A registration track that assigns a registration to
                     the course as an attendee.
        * instructors: A registration track that references the course meaning
                       the participant is (potentially) the course's instructor.
        * course_choices: A course choice of the course.
        * course_segments: The course segments of the course.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        course_id = affirm(vtypes.ID, course_id)
        blockers = {}

        attendees = self.sql_select(
            rs,
            "event.registration_tracks",
            ("id",),
            (course_id,),
            entity_key="course_id",
        )
        if attendees:
            blockers["attendees"] = [e["id"] for e in attendees]

        instructors = self.sql_select(
            rs,
            "event.registration_tracks",
            ("id",),
            (course_id,),
            entity_key="course_instructor",
        )
        if instructors:
            blockers["instructors"] = [e["id"] for e in instructors]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (course_id,), entity_key="course_id"
        )
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        course_segments = self.sql_select(
            rs, "event.course_segments", ("id",), (course_id,), entity_key="course_id"
        )
        if course_segments:
            blockers["course_segments"] = [e["id"] for e in course_segments]

        return blockers

    @access("event")
    def delete_course(
        self,
        rs: RequestState,
        course_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Remove a course organized via DB from the DB.

        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        """
        course_id = affirm(vtypes.ID, course_id)
        current = self.sql_select_one(
            rs, "event.courses", ("title", "event_id"), course_id
        )
        assert current is not None
        if not is_privileged(rs, EventPrivileges.courses_write, current['event_id']):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_lock(rs, event_id=current['event_id'])

        blockers = self.delete_course_blockers(rs, course_id)
        cascade = affirm_set(str, cascade or set()) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "course",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            # cascade specified blockers
            if cascade:
                if "attendees" in cascade:
                    for anid in blockers["attendees"]:
                        deletor = {
                            'course_id': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(rs, "event.registration_tracks", deletor)
                if "instructors" in cascade:
                    for anid in blockers["instructors"]:
                        deletor = {
                            'course_instructor': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(rs, "event.registration_tracks", deletor)
                if "course_choices" in cascade:
                    # Get the data of the affected choices grouped by track.
                    data = self.sql_select(
                        rs,
                        "event.course_choices",
                        ("track_id", "registration_id"),
                        blockers["course_choices"],
                    )
                    data_by_tracks = {
                        track_id: [
                            e["registration_id"]
                            for e in data
                            if e["track_id"] == track_id
                        ]
                        for track_id in set(e["track_id"] for e in data)
                    }

                    # Delete choices of the deletable course.
                    ret *= self.sql_delete(
                        rs, "event.course_choices", blockers["course_choices"]
                    )

                    # Construct list of inserts.
                    choices: list[CdEDBObject] = []
                    for track_id, reg_ids in data_by_tracks.items():
                        query = f"""
                            SELECT id, course_id, track_id, registration_id
                            FROM event.course_choices
                            WHERE track_id = {track_id} AND registration_id = ANY(%s)
                            ORDER BY registration_id, rank
                        """
                        choices.extend(self.query_all(rs, query, (reg_ids,)))

                    deletion_ids = {e['id'] for e in choices}

                    # Update the ranks and remove the ids from the insert data.
                    i = 0
                    current_id = None
                    for row in choices:
                        if current_id != row['registration_id']:
                            current_id = row['registration_id']
                            i = 0
                        row['rank'] = i
                        del row['id']
                        i += 1

                    self.sql_delete(rs, "event.course_choices", deletion_ids)
                    self.sql_insert_many(rs, "event.course_choices", choices)

                if "course_segments" in cascade:
                    ret *= self.sql_delete(
                        rs, "event.course_segments", blockers["course_segments"]
                    )

                # check if course is deletable after cascading
                blockers = self.delete_course_blockers(rs, course_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.courses", course_id)
                self.event_log(
                    rs,
                    const.EventLogCodes.course_deleted,
                    current['event_id'],
                    change_note=current['title'],
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "course", "block": blockers.keys()},
                )
        return ret

    @access("event")
    def get_attendee_stats(
        self, rs: RequestState, course_id: int
    ) -> models.CourseAttendees:
        """Retrieve a list of personas assigned to the given course in each track.

        This is only available for instrcutors of the given course.
        """
        course_id = affirm(vtypes.ID, course_id)

        with Atomizer(rs):
            query = f"""
                SELECT reg.id
                FROM
                    {models.Registration.database_table} AS reg
                    JOIN {models.RegistrationTrack.database_table} AS rt
                        ON rt.registration_id = reg.id
                WHERE
                    reg.persona_id = %(persona_id)s
                    AND rt.course_instructor = %(course_id)s
            """
            params: ParamDict = {
                "persona_id": rs.user.persona_id,
                "course_id": course_id,
            }
            if not self.query_one(rs, query, params):
                raise PrivilegeError(
                    n_("Only available for instructors of this course.")
                )
            query = f"""
                SELECT
                    reg.persona_id,
                    rt.track_id,
                    COALESCE(rt.course_id = rt.course_instructor, False) AS is_instructor
                FROM
                    {models.RegistrationTrack.database_table} AS rt
                    JOIN {models.CourseTrack.database_table} AS ct
                        ON rt.track_id = ct.id
                    JOIN {models.RegistrationPart.database_table} AS rp
                        ON rt.registration_id = rp.registration_id AND ct.part_id = rp.part_id
                    JOIN {models.Registration.database_table} AS reg
                        ON rt.registration_id = reg.id
                WHERE
                    rt.course_id = %(course_id)s
                    AND rp.status = ANY(%(stati)s)
            """
            params: ParamDict = {
                "course_id": course_id,
                "stati": const.RegistrationPartStati.involved_states(),
            }
            persona_ids = set()
            attendees_by_track = collections.defaultdict(list)
            instructors_by_track = collections.defaultdict(list)
            for e in self.query_all(rs, query, params):
                persona_ids.add(e["persona_id"])
                if e["is_instructor"]:
                    instructors_by_track[e["track_id"]].append(e["persona_id"])
                else:
                    attendees_by_track[e["track_id"]].append(e["persona_id"])
            personas = self.core.get_personas(rs, persona_ids)
            return models.CourseAttendees({
                track_id: models.CourseSegmentAttendees(
                    learners=xsorted(
                        (
                            personas[persona_id]
                            for persona_id in attendees_by_track[track_id]
                        ),
                        key=EntitySorter.persona,
                    ),
                    instructors=xsorted(
                        (
                            personas[persona_id]
                            for persona_id in instructors_by_track[track_id]
                        ),
                        key=EntitySorter.persona,
                    ),
                )
                for track_id in attendees_by_track.keys() | instructors_by_track.keys()
            })
