#!/usr/bin/env python3

"""
The `EventCourseMixin` subclasses the `EventBaseFrontend` and provides all the frontend
endpoints related to managing an events courses, participants' course choices
and courses' attendees.
"""

from collections import OrderedDict
from typing import Collection, Optional, cast

from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, CourseChoiceToolActions, CourseFilterPositions, EntitySorter,
    InfiniteEnum, RequestState, merge_dicts, n_, unwrap, xsorted,
)
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, check_validation as check, event_guard,
    make_persona_name, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.query import Query, QueryOperators, QueryScope
from cdedb.validation import COURSE_COMMON_FIELDS
from cdedb.validationtypes import VALIDATOR_LOOKUP


class EventCourseMixin(EventBaseFrontend):
    @access("anonymous")
    @REQUESTdata("track_ids")
    def course_list(self, rs: RequestState, event_id: int,
                    track_ids: Collection[int] = None) -> Response:
        """List courses from an event."""
        if (not rs.ambience['event']['is_course_list_visible']
                and not (event_id in rs.user.orga or self.is_admin(rs))):
            rs.notify("warning", n_("Course list not published yet."))
            return self.redirect(rs, "event/show_event")
        if rs.has_validation_errors() or not track_ids:
            track_ids = rs.ambience['event']['tracks'].keys()
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = None
        if course_ids:
            courses = self.eventproxy.get_courses(rs, course_ids.keys())
        return self.render(rs, "course/course_list",
                           {'courses': courses, 'track_ids': track_ids})

    @access("event")
    @event_guard()
    def show_course(self, rs: RequestState, event_id: int, course_id: int
                    ) -> Response:
        """Display course associated to event organized via DB."""
        params: CdEDBObject = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            all_registrations = self.eventproxy.get_registrations(
                rs, registration_ids)
            registrations = {
                k: v
                for k, v in all_registrations.items()
                if any(course_id in {track['course_id'], track['course_instructor']}
                       for track in v['tracks'].values())
            }
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
            attendees = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas, instructors=True)
            learners = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas, instructors=False)
            params['personas'] = personas
            params['registrations'] = registrations
            params['attendees'] = attendees
            params['learners'] = learners
            params['blockers'] = self.eventproxy.delete_course_blockers(
                rs, course_id).keys() - {"instructors", "course_choices",
                                         "course_segments"}
            instructor_ids = {reg['persona_id']
                              for reg in all_registrations.values()
                              if any(t['course_instructor'] == course_id
                                     for t in reg['tracks'].values())}
            instructors = self.coreproxy.get_personas(rs, instructor_ids)
            params['instructor_emails'] = [p['username']
                                           for p in instructors.values()]
        return self.render(rs, "course/show_course", params)

    @access("event")
    @event_guard(check_offline=True)
    def change_course_form(self, rs: RequestState, event_id: int, course_id: int
                           ) -> Response:
        """Render form."""
        if 'segments' not in rs.values:
            rs.values.setlist('segments', rs.ambience['course']['segments'])
        if 'active_segments' not in rs.values:
            rs.values.setlist('active_segments',
                              rs.ambience['course']['active_segments'])
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['course']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['course'], field_values)
        return self.render(rs, "course/change_course")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*COURSE_COMMON_FIELDS)
    @REQUESTdata("segments", "active_segments")
    def change_course(self, rs: RequestState, event_id: int, course_id: int,
                      segments: Collection[int],
                      active_segments: Collection[int], data: CdEDBObject
                      ) -> Response:
        """Modify a course associated to an event organized via DB."""
        data['id'] = course_id
        data['segments'] = segments
        data['active_segments'] = active_segments
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, vtypes.Course, data)
        if rs.has_validation_errors():
            return self.change_course_form(rs, event_id, course_id)
        assert data is not None
        code = self.eventproxy.set_course(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @access("event")
    @event_guard(check_offline=True)
    def create_course_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        # by default select all tracks
        tracks = rs.ambience['event']['tracks']
        if not tracks:
            rs.notify("error", n_("Event without tracks forbids courses."))
            return self.redirect(rs, 'event/course_stats')
        if 'segments' not in rs.values:
            rs.values.setlist('segments', tracks)
        return self.render(rs, "course/create_course")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*COURSE_COMMON_FIELDS)
    @REQUESTdata("segments")
    def create_course(self, rs: RequestState, event_id: int,
                      segments: Collection[int], data: CdEDBObject) -> Response:
        """Create a new course associated to an event organized via DB."""
        data['event_id'] = event_id
        data['segments'] = segments
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, vtypes.Course, data, creation=True)
        if rs.has_validation_errors():
            return self.create_course_form(rs, event_id)
        assert data is not None

        new_id = self.eventproxy.create_course(rs, data)
        self.notify_return_code(rs, new_id, success=n_("Course created."))
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_course(self, rs: RequestState, event_id: int, course_id: int,
                      ack_delete: bool) -> Response:
        """Delete a course from an event organized via DB."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_course(rs, event_id, course_id)
        blockers = self.eventproxy.delete_course_blockers(rs, course_id)
        # Do not allow deletion of course with attendees
        if "attendees" in blockers:
            rs.notify("error", n_("Course cannot be deleted, because it still "
                                  "has attendees."))
            return self.redirect(rs, "event/show_course")
        code = self.eventproxy.delete_course(
            rs, course_id, {"instructors", "course_choices", "course_segments"})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/course_stats")

    @access("event")
    @event_guard()
    def course_assignment_checks(self, rs: RequestState, event_id: int
                                 ) -> Response:
        """Provide some consistency checks for course assignment."""
        event = rs.ambience['event']
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        stati = const.RegistrationPartStati

        # Helper for calculation of assign_counts
        course_participant_lists = {
            course_id: {
                track_id: [
                    reg for reg in registrations.values()
                    if (reg['tracks'][track_id]['course_id'] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             == stati.participant))]
                for track_id, track in tracks.items()
            }
            for course_id in course_ids
        }
        # Get number of attendees per course
        # assign_counts has the structure:
        # {course_id: {track_id: (num_participants, num_instructors)}}
        assign_counts = {
            course_id: {
                track_id: (
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            != course_id)),
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            == course_id))
                )
                for track_id, course_track_p_data in course_p_data.items()
            }
            for course_id, course_p_data in course_participant_lists.items()
        }

        # Tests for problematic courses
        course_tests = {
            'cancelled_with_p': lambda c, tid: (
                tid not in c['active_segments']
                and (assign_counts[c['id']][tid][0]
                     + assign_counts[c['id']][tid][1]) > 0),
            'many_p': lambda c, tid: (
                tid in c['active_segments']
                and c['max_size'] is not None
                and assign_counts[c['id']][tid][0] > c['max_size']),
            'few_p': lambda c, tid: (
                tid in c['active_segments']
                and c['min_size']
                and assign_counts[c['id']][tid][0] < c['min_size']),
            'no_instructor': lambda c, tid: (
                tid in c['active_segments']
                and assign_counts[c['id']][tid][1] <= 0),
        }

        # Calculate problematic course lists
        # course_problems will have the structure {key: [(reg_id, [track_id])]}
        max_course_no_len = max((len(c['nr']) for c in courses.values()),
                                default=0)
        course_problems = {}
        for key, test in course_tests.items():
            problems = []
            for course_id, course in courses.items():
                problem_tracks = [
                    track_id
                    for track_id in event['tracks']
                    if test(course, track_id)]
                if problem_tracks:
                    problems.append((course_id, problem_tracks))
            course_problems[key] = xsorted(
                problems, key=lambda problem:
                    courses[problem[0]]['nr'].rjust(max_course_no_len, '\0'))

        # Tests for registrations with problematic assignments
        reg_tests = {
            'no_course': lambda r, p, t: (
                p['status'] == stati.participant
                and not t['course_id']),
            'instructor_wrong_course': lambda r, p, t: (
                p['status'] == stati.participant
                and t['course_instructor']
                and t['track_id'] in
                    courses[t['course_instructor']]['active_segments']
                and t['course_id'] != t['course_instructor']),
            'unchosen': lambda r, p, t: (
                p['status'] == stati.participant
                and t['course_id']
                and t['course_id'] != t['course_instructor']
                and (t['course_id'] not in
                     t['choices']
                     [:event['tracks'][t['track_id']]['num_choices']])),
        }

        # Calculate problematic registrations
        # reg_problems will have the structure {key: [(reg_id, [track_id])]}
        reg_problems = {}
        for key, test in reg_tests.items():
            problems = []
            for reg_id, reg in registrations.items():
                problem_tracks = [
                    track_id
                    for part_id, part in event['parts'].items()
                    for track_id in part['tracks']
                    if test(reg, reg['parts'][part_id],
                            reg['tracks'][track_id])]
                if problem_tracks:
                    problems.append((reg_id, problem_tracks))
            reg_problems[key] = xsorted(
                problems, key=lambda problem:
                    EntitySorter.persona(
                        personas[registrations[problem[0]]['persona_id']]))

        return self.render(rs, "course/course_assignment_checks", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'course_problems': course_problems,
            'reg_problems': reg_problems})

    @access("event")
    @event_guard()
    @REQUESTdata("course_id", "track_id", "position", "ids", "include_active")
    def course_choices_form(
            self, rs: RequestState, event_id: int, course_id: Optional[vtypes.ID],
            track_id: Optional[vtypes.ID],
            position: Optional[InfiniteEnum[CourseFilterPositions]],
            ids: Optional[vtypes.IntCSVList], include_active: Optional[bool]
            ) -> Response:
        """Provide an overview of course choices.

        This allows flexible filtering of the displayed registrations.
        """
        tracks = rs.ambience['event']['tracks']
        if not tracks:
            rs.ignore_validation_errors()
            rs.notify("error", n_("Event without tracks forbids courses."))
            return self.redirect(rs, 'event/course_stats')
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
        stati = const.RegistrationPartStati

        if rs.has_validation_errors():
            registration_ids = all_reg_ids
            registrations = all_regs
            personas = self.coreproxy.get_personas(
                rs, tuple(r['persona_id'] for r in registrations.values()))
        else:
            if include_active:
                include_states = tuple(
                    status for status in const.RegistrationPartStati if
                    status.is_involved())
            else:
                include_states = (const.RegistrationPartStati.participant,)
            registration_ids = self.eventproxy.registrations_by_course(
                rs, event_id, course_id, track_id, position, ids,
                include_states)
            registrations = self.eventproxy.get_registrations(
                rs, registration_ids.keys())
            personas = self.coreproxy.get_personas(
                rs, registration_ids.values())

        course_infos = {}
        reg_part = lambda registration, track_id: \
            registration['parts'][tracks[track_id]['part_id']]
        for course_id, course in courses.items():  # pylint: disable=redefined-argument-from-local
            for track_id in tracks:  # pylint: disable=redefined-argument-from-local
                assigned = sum(
                    1 for reg in all_regs.values()
                    if reg_part(reg, track_id)['status'] == stati.participant
                    and reg['tracks'][track_id]['course_id'] == course_id and
                    reg['tracks'][track_id]['course_instructor'] != course_id)
                all_instructors = sum(
                    1 for reg in all_regs.values()
                    if
                    reg['tracks'][track_id]['course_instructor'] == course_id)
                assigned_instructors = sum(
                    1 for reg in all_regs.values()
                    if reg_part(reg, track_id)['status'] == stati.participant
                    and reg['tracks'][track_id]['course_id'] == course_id
                    and reg['tracks'][track_id][
                        'course_instructor'] == course_id)
                course_infos[(course_id, track_id)] = {
                    'assigned': assigned,
                    'all_instructors': all_instructors,
                    'assigned_instructors': assigned_instructors,
                    'is_happening': track_id in course['segments'],
                }
        corresponding_query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"] + [
                "course{0}.id".format(track_id)
                for track_id in tracks],
            (("reg.id", QueryOperators.oneof, registration_ids.keys()),),
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        filter_entries = [
            (CourseFilterPositions.anywhere.value,
             rs.gettext("somehow know")),
            (CourseFilterPositions.assigned.value,
             rs.gettext("participate in")),
            (CourseFilterPositions.instructor.value,
             rs.gettext("offer")),
            (CourseFilterPositions.any_choice.value,
             rs.gettext("chose"))
        ]
        filter_entries.extend(
            (i, rs.gettext("have as {}. choice").format(i + 1))
            for i in range(max(t['num_choices'] for t in tracks.values())))
        action_entries = [
            (i, rs.gettext("into their {}. choice").format(i + 1))
            for i in range(max(t['num_choices'] for t in tracks.values()))]
        action_entries.extend((
            (CourseChoiceToolActions.assign_fixed.value,
             rs.gettext("in the course …")),
            (CourseChoiceToolActions.assign_auto.value,
             rs.gettext("automatically"))))
        return self.render(rs, "course/course_choices", {
            'courses': courses, 'personas': personas,
            'registrations': OrderedDict(
                xsorted(registrations.items(),
                        key=lambda reg: EntitySorter.persona(
                           personas[reg[1]['persona_id']]))),
            'course_infos': course_infos,
            'corresponding_query': corresponding_query,
            'filter_entries': filter_entries,
            'action_entries': action_entries})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("course_id", "track_id", "position", "ids", "include_active",
                 "registration_ids", "assign_track_ids", "assign_action",
                 "assign_course_id")
    def course_choices(self, rs: RequestState, event_id: int,
                       course_id: Optional[vtypes.ID], track_id: Optional[vtypes.ID],
                       position: Optional[InfiniteEnum[CourseFilterPositions]],
                       ids: Optional[vtypes.IntCSVList],
                       include_active: Optional[bool],
                       registration_ids: Collection[int],
                       assign_track_ids: Collection[int],
                       assign_action: InfiniteEnum[CourseChoiceToolActions],
                       assign_course_id: Optional[vtypes.ID]) -> Response:
        """Manipulate course choices.

        The first four parameters (course_id, track_id, position, ids) are the
        filter parameters for the course_choices_form used for displaying
        an equally filtered form on validation errors or after successful
        submit.

        Allow assignment of multiple people in multiple tracks to one of
        their choices or a specific course.
        """
        if rs.has_validation_errors():
            return self.course_choices_form(rs, event_id)  # type: ignore
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        tracks = rs.ambience['event']['tracks']
        # Orchestrate change_note
        if len(tracks) == 1:
            change_note = "Kurs eingeteilt."
        elif len(assign_track_ids) == 1:
            change_note = (
                "Kurs eingeteilt in Kursschiene"
                f" {tracks[unwrap(assign_track_ids)]['shortname']}.")
        else:
            change_note = (
                "Kurs eingeteilt in Kursschienen " +
                ", ".join(tracks[anid]['shortname'] for anid in assign_track_ids) +
                ".")

        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        courses = None
        if assign_action.enum == CourseChoiceToolActions.assign_auto:
            course_ids = self.eventproxy.list_courses(rs, event_id)
            courses = self.eventproxy.get_courses(rs, course_ids)

        num_committed = 0
        for registration_id in registration_ids:
            persona = personas[registrations[registration_id]['persona_id']]
            tmp: CdEDBObject = {
                'id': registration_id,
                'tracks': {}
            }
            for atrack_id in assign_track_ids:
                reg_part = registrations[registration_id]['parts'][
                    tracks[atrack_id]['part_id']]
                reg_track = registrations[registration_id]['tracks'][atrack_id]
                if (reg_part['status']
                        != const.RegistrationPartStati.participant):
                    continue
                if assign_action.enum == CourseChoiceToolActions.specific_rank:
                    if assign_action.int >= len(reg_track['choices']):
                        rs.notify("warning",
                                  (n_("%(name)s has no "
                                      "%(rank)i. choice in %(track_name)s.")
                                   if len(tracks) > 1
                                   else n_("%(name)s has no %(rank)i. choice.")),
                                  {'name': make_persona_name(persona),
                                   'rank': assign_action.int + 1,
                                   'track_name': tracks[atrack_id]['title']})
                        continue
                    choice = reg_track['choices'][assign_action.int]
                    tmp['tracks'][atrack_id] = {'course_id': choice}
                elif assign_action.enum == CourseChoiceToolActions.assign_fixed:
                    tmp['tracks'][atrack_id] = {'course_id': assign_course_id}
                elif assign_action.enum == CourseChoiceToolActions.assign_auto:
                    cid = reg_track['course_id']
                    assert courses is not None
                    if cid and atrack_id in courses[cid]['active_segments']:
                        # Do not modify a valid assignment
                        continue
                    instructor = reg_track['course_instructor']
                    if (instructor
                            and atrack_id in courses[instructor]
                            ['active_segments']):
                        # Let instructors instruct
                        tmp['tracks'][atrack_id] = {'course_id': instructor}
                        continue
                    for choice in (
                            reg_track['choices'][
                            :tracks[atrack_id]['num_choices']]):
                        if atrack_id in courses[choice]['active_segments']:
                            # Assign first possible choice
                            tmp['tracks'][atrack_id] = {'course_id': choice}
                            break
                    else:
                        rs.notify("warning",
                                  (n_("No choice available for %(name)s in "
                                      "%(track_name)s.")
                                   if len(tracks) > 1
                                   else n_("No choice available for "
                                           "%(name)s.")),
                                  {'name': make_persona_name(persona),
                                   'track_name': tracks[atrack_id]['title']})
            if tmp['tracks']:
                res = self.eventproxy.set_registration(rs, tmp, change_note)
                if res:
                    num_committed += 1
                else:
                    rs.notify("warning",
                              n_("Error committing changes for %(name)s."),
                              {'name': make_persona_name(persona)})
        rs.notify("success" if num_committed > 0 else "warning",
                  n_("Course assignment for %(num_committed)s of %(num_total)s "
                     "registrations committed."),
                  {'num_total': len(registration_ids),
                   'num_committed': num_committed})
        return self.redirect(
            rs, "event/course_choices_form",
            {'course_id': course_id, 'track_id': track_id,
             'position': position.value if position is not None else None,
             'ids': ",".join(str(i) for i in ids),
             'include_active': include_active})

    @access("event")
    @event_guard()
    @REQUESTdata("include_active")
    def course_stats(self, rs: RequestState, event_id: int, include_active: bool
                     ) -> Response:
        """List courses.

        Provide an overview of the number of choices and assignments for
        all courses.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/show_event')
        if include_active:
            include_states = tuple(
                status for status in const.RegistrationPartStati
                if status.is_involved())
        else:
            include_states = (const.RegistrationPartStati.participant,)

        event = rs.ambience['event']
        tracks = event['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        choice_counts = {
            course_id: {
                (track_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['tracks'][track_id]['choices']) > i
                        and reg['tracks'][track_id]['choices'][i] == course_id
                        and (reg['parts'][tracks[track_id]['part_id']]['status']
                             in include_states)))
                for track_id, track in tracks.items()
                for i in range(track['num_choices'])
            }
            for course_id in course_ids
        }
        # Helper for calculation of assign_counts
        course_participant_lists = {
            course_id: {
                track_id: [
                    reg for reg in registrations.values()
                    if (reg['tracks'][track_id]['course_id'] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             in include_states))]
                for track_id, track in tracks.items()
            }
            for course_id in course_ids
        }
        # Tuple of (number of assigned participants, number of instructors) for
        # each course in each track
        assign_counts = {
            course_id: {
                track_id: (
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                                 != course_id)),
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            == course_id))
                )
                for track_id, course_track_p_data in course_p_data.items()
            }
            for course_id, course_p_data in course_participant_lists.items()
        }
        return self.render(rs, "course/course_stats", {
            'courses': courses, 'choice_counts': choice_counts,
            'assign_counts': assign_counts, 'include_active': include_active})

    @access("event")
    @event_guard(check_offline=True)
    def manage_attendees_form(self, rs: RequestState, event_id: int,
                              course_id: int) -> Response:
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        attendees = self.calculate_groups(
            (course_id,), rs.ambience['event'], registrations, key="course_id",
            personas=personas)

        # Generate options for the multi select boxes
        def _check_without_course(registration_id: int, track_id: int) -> bool:
            """Un-inlined check for registration without course."""
            reg = registrations[registration_id]
            part = reg['parts'][tracks[track_id]['part_id']]
            track = reg['tracks'][track_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and not track['course_id'])

        without_course = {
            track_id: [
                (registration_id, make_persona_name(
                    personas[registrations[registration_id]['persona_id']]))
                for registration_id in registrations
                if _check_without_course(registration_id, track_id)
            ]
            for track_id in tracks
        }

        # Generate data to be encoded to json and used by the
        # cdedbMultiSelect() javascript function
        def _check_not_this_course(registration_id: int, track_id: int) -> bool:
            """Un-inlined check for registration with different course."""
            reg = registrations[registration_id]
            part = reg['parts'][tracks[track_id]['part_id']]
            track = reg['tracks'][track_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and track['course_id'] != course_id)

        selectize_data = {
            track_id: xsorted(
                ({'name': make_persona_name(personas[registration['persona_id']]),
                  'current': registration['tracks'][track_id]['course_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_course(registration_id, track_id)),
                key=lambda x: (
                    x['current'] is not None,
                    EntitySorter.persona(
                        personas[registrations[x['id']]['persona_id']]))
            )
            for track_id in tracks
        }
        courses = self.eventproxy.list_courses(rs, event_id)
        course_names = {
            course['id']: "{}. {}".format(course['nr'], course['shortname'])
            for course_id, course
            in self.eventproxy.get_courses(rs, courses.keys()).items()
        }

        return self.render(rs, "course/manage_attendees", {
            'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'without_course': without_course,
            'selectize_data': selectize_data, 'course_names': course_names})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_attendees(self, rs: RequestState, event_id: int, course_id: int
                         ) -> Response:
        """Alter who is assigned to this course."""
        # Get all registrations and especially current attendees of this course
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        current_attendees = {
            track_id: [reg_id for reg_id, registration in registrations.items()
                       if registration['tracks'][track_id]['course_id']
                       == course_id]
            for track_id in rs.ambience['course']['segments']}

        # Parse request data
        params: vtypes.TypeMapping = {
            **{
                f"new_{track_id}": Collection[Optional[vtypes.ID]]
                for track_id in rs.ambience['course']['segments']
            },
            **{
                f"delete_{track_id}_{reg_id}": bool
                for track_id in rs.ambience['course']['segments']
                for reg_id in current_attendees[track_id]
            }
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_attendees_form(rs, event_id, course_id)

        # Iterate all registrations to find changed ones
        code = 1
        change_note = ("Kursteilnehmer von"
                       f" {rs.ambience['course']['shortname']} geändert.")
        for registration_id, registration in registrations.items():
            new_reg: CdEDBObject = {
                'id': registration_id,
                'tracks': {},
            }
            # Check if registration is new attendee or deleted attendee
            # in any track of the course
            for track_id in rs.ambience['course']['segments']:
                new_attendee = (
                        registration_id in data["new_{}".format(track_id)])
                deleted_attendee = data.get(
                    "delete_{}_{}".format(track_id, registration_id), False)
                if new_attendee or deleted_attendee:
                    new_reg['tracks'][track_id] = {
                        'course_id': (course_id if new_attendee else None)
                    }
            if new_reg['tracks']:
                code *= self.eventproxy.set_registration(rs, new_reg, change_note)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")
