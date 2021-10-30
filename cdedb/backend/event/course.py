#!/usr/bin/env python3

"""
The `EventCourseBackend` subclasses the `EventBaseBackend` and provides functionality
for managing courses belonging to an event.
"""

from typing import Collection, List, Protocol

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    access, affirm_set_validation as affirm_set, affirm_validation as affirm,
    cast_fields, singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    COURSE_FIELDS, COURSE_SEGMENT_FIELDS, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, DeletionBlockers, PrivilegeError, PsycoJson, RequestState, glue,
    n_, unwrap,
)
from cdedb.database.connection import Atomizer


class EventCourseBackend(EventBaseBackend):
    @access("anonymous")
    def list_courses(self, rs: RequestState,
                        event_id: int) -> CdEDBObjectMap:
        """List all courses organized via DB.

        :returns: Mapping of course ids to titles.
        """
        event_id = affirm(vtypes.ID, event_id)
        data = self.sql_select(rs, "event.courses", ("id", "title"),
                               (event_id,), entity_key="event_id")
        return {e['id']: e['title'] for e in data}

    @access("anonymous")
    def get_courses(self, rs: RequestState, course_ids: Collection[int]
                    ) -> CdEDBObjectMap:
        """Retrieve data for some courses organized via DB.

        They must be associated to the same event. This contains additional
        information on the parts in which the course takes place.
        """
        course_ids = affirm_set(vtypes.ID, course_ids)
        with Atomizer(rs):
            data = self.sql_select(rs, "event.courses", COURSE_FIELDS, course_ids)
            if not data:
                return {}
            ret = {e['id']: e for e in data}
            events = {e['event_id'] for e in data}
            if len(events) > 1:
                raise ValueError(n_("Only courses from one event allowed."))
            event_fields = self._get_event_fields(rs, unwrap(events))
            data = self.sql_select(
                rs, "event.course_segments", COURSE_SEGMENT_FIELDS, course_ids,
                entity_key="course_id")
            for anid in course_ids:
                segments = {p['track_id'] for p in data if p['course_id'] == anid}
                if 'segments' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['segments'] = segments
                active_segments = {p['track_id'] for p in data
                                   if p['course_id'] == anid and p['is_active']}
                if 'active_segments' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['active_segments'] = active_segments
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'], event_fields)
        return ret

    class _GetCourseProtocol(Protocol):
        def __call__(self, rs: RequestState, course_id: int) -> CdEDBObject: ...
    get_course: _GetCourseProtocol = singularize(get_courses, "course_ids", "course_id")

    @access("event")
    def set_course(self, rs: RequestState,
                   data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a course linked to an event organized via DB.

        If the 'segments' key is present you have to pass the complete list
        of track IDs, which will superseed the current list of tracks.

        If the 'active_segments' key is present you have to pass the
        complete list of active track IDs, which will superseed the current
        list of active tracks. This has to be a subset of the segments of
        the course.
        """
        data = affirm(vtypes.Course, data)
        if not self.is_orga(rs, course_id=data['id']) and not self.is_admin(rs):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=data['id'])
        ret = 1
        with Atomizer(rs):
            current = self.sql_select_one(rs, "event.courses",
                                          ("title", "event_id"), data['id'])
            assert current is not None

            cdata = {k: v for k, v in data.items()
                     if k in COURSE_FIELDS and k != "fields"}
            changed = False
            if len(cdata) > 1:
                ret *= self.sql_update(rs, "event.courses", cdata)
                changed = True
            if 'fields' in data:
                # delayed validation since we need additional info
                event_fields = self._get_event_fields(rs, current['event_id'])
                fdata = affirm(
                    vtypes.EventAssociatedFields, data['fields'],
                    fields=event_fields,
                    association=const.FieldAssociations.course)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.courses",
                                                    fupdate)
                changed = True
            if changed:
                self.event_log(
                    rs, const.EventLogCodes.course_changed, current['event_id'],
                    change_note=current['title'])
            if 'segments' in data:
                current_segments = self.sql_select(
                    rs, "event.course_segments", ("track_id",),
                    (data['id'],), entity_key="course_id")
                existing = {e['track_id'] for e in current_segments}
                new = data['segments'] - existing
                deleted = existing - data['segments']
                if new:
                    # check, that all new tracks belong to the event of the
                    # course
                    tracks = self.sql_select(
                        rs, "event.course_tracks", ("part_id",), new)
                    associated_parts = list(unwrap(e) for e in tracks)
                    associated_events = self.sql_select(
                        rs, "event.event_parts", ("event_id",),
                        associated_parts)
                    event_ids = {e['event_id'] for e in associated_events}
                    if {current['event_id']} != event_ids:
                        raise ValueError(n_("Non-associated tracks found."))

                    for anid in new:
                        insert = {
                            'course_id': data['id'],
                            'track_id': anid,
                            'is_active': True,
                        }
                        ret *= self.sql_insert(rs, "event.course_segments",
                                               insert)
                if deleted:
                    query = ("DELETE FROM event.course_segments"
                             " WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deleted))
                if new or deleted:
                    self.event_log(
                        rs, const.EventLogCodes.course_segments_changed,
                        current['event_id'], change_note=current['title'])
            if 'active_segments' in data:
                current_segments = self.sql_select(
                    rs, "event.course_segments", ("track_id", "is_active"),
                    (data['id'],), entity_key="course_id")
                existing = {e['track_id'] for e in current_segments}
                # check that all active segments are actual segments of this
                # course
                if not existing >= data['active_segments']:
                    raise ValueError(n_("Wrong-associated segments found."))
                active = {e['track_id'] for e in current_segments
                          if e['is_active']}
                activated = data['active_segments'] - active
                deactivated = active - data['active_segments']
                if activated:
                    query = glue(
                        "UPDATE event.course_segments SET is_active = True",
                        "WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], activated))
                if deactivated:
                    query = glue(
                        "UPDATE event.course_segments SET is_active = False",
                        "WHERE course_id = %s AND track_id = ANY(%s)")
                    ret *= self.query_exec(rs, query, (data['id'], deactivated))
                if activated or deactivated:
                    self.event_log(
                        rs, const.EventLogCodes.course_segment_activity_changed,
                        current['event_id'], change_note=current['title'])
        return ret

    @access("event")
    def create_course(self, rs: RequestState,
                      data: CdEDBObject) -> DefaultReturnCode:
        """Make a new course organized via DB."""
        data = affirm(vtypes.Course, data, creation=True)
        # direct validation since we already have an event_id
        event_fields = self._get_event_fields(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata,
            fields=event_fields, association=const.FieldAssociations.course)
        data['fields'] = PsycoJson(fdata)
        if (not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=data['event_id'])
        with Atomizer(rs):
            # Check for existence of course tracks
            event = self.get_event(rs, data['event_id'])
            if not event['tracks']:
                raise RuntimeError(n_("Event without tracks forbids courses."))

            cdata = {k: v for k, v in data.items()
                     if k in COURSE_FIELDS}
            new_id = self.sql_insert(rs, "event.courses", cdata)
            if 'segments' in data or 'active_segments' in data:
                pdata = {
                    'id': new_id,
                }
                if 'segments' in data:
                    pdata['segments'] = data['segments']
                if 'active_segments' in data:
                    pdata['active_segments'] = data['active_segments']
                self.set_course(rs, pdata)
            self.event_log(rs, const.EventLogCodes.course_created,
                           data['event_id'], change_note=data['title'])
        return new_id

    @access("event")
    def delete_course_blockers(self, rs: RequestState,
                               course_id: int) -> DeletionBlockers:
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
            rs, "event.registration_tracks", ("id",), (course_id,),
            entity_key="course_id")
        if attendees:
            blockers["attendees"] = [e["id"] for e in attendees]

        instructors = self.sql_select(
            rs, "event.registration_tracks", ("id",), (course_id,),
            entity_key="course_instructor")
        if instructors:
            blockers["instructors"] = [e["id"] for e in instructors]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (course_id,),
            entity_key="course_id")
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        course_segments = self.sql_select(
            rs, "event.course_segments", ("id",), (course_id,),
            entity_key="course_id")
        if course_segments:
            blockers["course_segments"] = [e["id"] for e in course_segments]

        return blockers

    @access("event")
    def delete_course(self, rs: RequestState, course_id: int,
                      cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove a course organized via DB from the DB.

        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        """
        course_id = affirm(vtypes.ID, course_id)
        if (not self.is_orga(rs, course_id=course_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, course_id=course_id)

        blockers = self.delete_course_blockers(rs, course_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "course",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            course = self.get_course(rs, course_id)
            # cascade specified blockers
            if cascade:
                if "attendees" in cascade:
                    for anid in blockers["attendees"]:
                        deletor = {
                            'course_id': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(
                            rs, "event.registration_tracks", deletor)
                if "instructors" in cascade:
                    for anid in blockers["instructors"]:
                        deletor = {
                            'course_instructor': None,
                            'id': anid,
                        }
                        ret *= self.sql_update(
                            rs, "event.registration_tracks", deletor)
                if "course_choices" in cascade:
                    # Get the data of the affected choices grouped by track.
                    data = self.sql_select(
                        rs, "event.course_choices",
                        ("track_id", "registration_id"),
                        blockers["course_choices"])
                    data_by_tracks = {
                        track_id: [e["registration_id"] for e in data
                                   if e["track_id"] == track_id]
                        for track_id in set(e["track_id"] for e in data)
                    }

                    # Delete choices of the deletable course.
                    ret *= self.sql_delete(
                        rs, "event.course_choices", blockers["course_choices"])

                    # Construct list of inserts.
                    choices: List[CdEDBObject] = []
                    for track_id, reg_ids in data_by_tracks.items():
                        query = (
                            "SELECT id, course_id, track_id, registration_id"
                            " FROM event.course_choices"
                            " WHERE track_id = {} AND registration_id = ANY(%s)"
                            " ORDER BY registration_id, rank").format(track_id)
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
                    ret *= self.sql_delete(rs, "event.course_segments",
                                           blockers["course_segments"])

                # check if course is deletable after cascading
                blockers = self.delete_course_blockers(rs, course_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "event.courses", course_id)
                self.event_log(rs, const.EventLogCodes.course_deleted,
                               course['event_id'],
                               change_note=course['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "course", "block": blockers.keys()})
        return ret
