#!/usr/bin/env python3

"""
The EventDownloadMixin subclasses the `EventBaseFrontend` and provides endpoints for
all event related downloads.
"""

import collections.abc
import pathlib
import shutil
import tempfile
from collections import OrderedDict
from typing import Collection, Optional

from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    EntitySorter, RequestState, asciificator, determine_age_class, json_serialize, n_,
    unwrap, xsorted,
)
from cdedb.frontend.common import REQUESTdata, access, event_guard, make_persona_name
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.frontend.event.lodgement_wishes import detect_lodgement_wishes
from cdedb.query import Query, QueryOperators, QueryScope


class EventDownloadMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def downloads(self, rs: RequestState, event_id: int) -> Response:
        """Offer documents like nametags for download."""
        return self.render(rs, "downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_nametags(self, rs: RequestState, event_id: int,
                          runs: vtypes.SingleDigitInt) -> Response:
        """Create nametags.

        You probably want to edit the provided tex file.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event']['begin'])
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        tex = self.fill_template(rs, "tex", "nametags", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'courses': courses})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_nametags.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w', encoding='utf-8') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "aka-logo.png")
            shutil.copy(src, work_dir / "orga-logo.png")
            shutil.copy(src, work_dir / "minor-pictogram.png")
            shutil.copy(src, work_dir / "multicourse-logo.png")
            for course_id in courses:
                shutil.copy(src, work_dir / "logo-{}.png".format(course_id))
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_nametags.tex".format(rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_course_puzzle(self, rs: RequestState, event_id: int,
                               runs: vtypes.SingleDigitInt) -> Response:
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        event = rs.ambience['event']
        tracks = event['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        counts = {
            course_id: {
                (track_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['tracks'][track_id]['choices']) > i
                        and reg['tracks'][track_id]['choices'][i] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             == const.RegistrationPartStati.participant)))
                for track_id, track in tracks.items() for i in
                range(track['num_choices'])
            }
            for course_id in course_ids
        }
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        tex = self.fill_template(rs, "tex", "course_puzzle", {
            'courses': courses, 'counts': counts,
            'tracks_sorted': tracks_sorted, 'registrations': registrations,
            'personas': personas})
        file = self.serve_latex_document(
            rs, tex,
            "{}_course_puzzle".format(rs.ambience['event']['shortname']), runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_lodgement_puzzle(self, rs: RequestState, event_id: int,
                                  runs: vtypes.SingleDigitInt) -> Response:
        """Aggregate lodgement information.

        This can be printed and cut to help with distribution of participants.
        This make use of the lodge_field and the camping_mat_field.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        event = rs.ambience['event']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                event['begin'])
        key = (lambda reg_id:
               personas[registrations[reg_id]['persona_id']]['birthday'])
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in xsorted(registrations,
                                                                  key=key))
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)

        rwish = collections.defaultdict(list)
        if event['lodge_field']:
            wishes, problems = detect_lodgement_wishes(registrations, personas,
                                                       event, None)
            for wish in wishes:
                if wish.negated:
                    continue
                rwish[wish.wished].append(wish.wishing)
                if wish.bidirectional:
                    rwish[wish.wishing].append(wish.wished)
        else:
            problems = []
        reverse_wish = {
            reg_id: ", ".join(
                make_persona_name(
                    personas[registrations[wishing_id]['persona_id']])
                for wishing_id in rwish[reg_id])
            for reg_id in registrations
        }

        tex = self.fill_template(rs, "tex", "lodgement_puzzle", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'reverse_wish': reverse_wish,
            'wish_problems': problems})
        file = self.serve_latex_document(rs, tex, "{}_lodgement_puzzle".format(
            rs.ambience['event']['shortname']), runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_course_lists(self, rs: RequestState, event_id: int,
                              runs: vtypes.SingleDigitInt) -> Response:
        """Create lists to post to course rooms."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        tracks = rs.ambience['event']['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        for p_id, p in personas.items():
            p['age'] = determine_age_class(
                p['birthday'], rs.ambience['event']['begin'])
        attendees = self.calculate_groups(
            courses, rs.ambience['event'], registrations, key="course_id",
            personas=personas)
        instructors = {}
        # Look for the field name of the course_room_field.
        cr_field_id = rs.ambience['event']['course_room_field']
        cr_field = rs.ambience['event']['fields'].get(cr_field_id, {})
        cr_field_name = cr_field.get('field_name')
        for c_id, course in courses.items():
            for t_id in course['active_segments']:
                instructors[(c_id, t_id)] = [
                    r_id
                    for r_id in attendees[(c_id, t_id)]
                    if (registrations[r_id]['tracks'][t_id]['course_instructor']
                        == c_id)
                ]
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        tex = self.fill_template(rs, "tex", "course_lists", {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'instructors': instructors, 'course_room_field': cr_field_name,
            'tracks_sorted': tracks_sorted, })
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_course_lists.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w', encoding='utf-8') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "event-logo.png")
            for course_id in courses:
                dest = work_dir / "course-logo-{}.png".format(course_id)
                path = self.conf["STORAGE_DIR"] / "course_logo" / str(course_id)
                if path.exists():
                    shutil.copy(path, dest)
                else:
                    shutil.copy(src, dest)
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_course_lists.tex".format(rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_lodgement_lists(self, rs: RequestState, event_id: int,
                                 runs: vtypes.SingleDigitInt) -> Response:
        """Create lists to post to lodgements."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id",
            personas=personas)
        tex = self.fill_template(rs, "tex", "lodgement_lists", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_lodgement_lists.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w', encoding='utf-8') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "aka-logo.png")
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_lodgement_lists.tex".format(
                    rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs", "landscape", "orgas_only", "part_ids")
    def download_participant_list(self, rs: RequestState, event_id: int,
                                  runs: vtypes.SingleDigitInt, landscape: bool,
                                  orgas_only: bool,
                                  part_ids: Collection[vtypes.ID]) -> Response:
        """Create list to send to all participants."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        data = self._get_participant_list_data(rs, event_id, part_ids)
        if runs and not data['registrations']:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")
        data['orientation'] = "landscape" if landscape else "portrait"
        data['orgas_only'] = orgas_only
        tex = self.fill_template(rs, "tex", "participant_list", data)
        file = self.serve_latex_document(
            rs, tex, "{}_participant_list".format(
                rs.ambience['event']['shortname']),
            runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    def download_dokuteam_courselist(self, rs: RequestState, event_id: int) -> Response:
        """A pipe-seperated courselist for the dokuteam aca-generator script."""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        if not course_ids:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        courses = self.eventproxy.get_courses(rs, course_ids)
        active_courses = filter(lambda c: c["active_segments"], courses.values())
        sorted_courses = xsorted(active_courses, key=EntitySorter.course)
        data = self.fill_template(rs, "other", "dokuteam_courselist", {
            "sorted_courses": sorted_courses
        })
        return self.send_file(
            rs, data=data, inline=False,
            filename=f"{rs.ambience['event']['shortname']}_dokuteam_courselist.txt")

    @access("event")
    @event_guard()
    def download_dokuteam_participant_list(self, rs: RequestState,
                                           event_id: int) -> Response:
        """Create participant list per track for dokuteam."""
        event = self.eventproxy.get_event(rs, event_id)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        spec = QueryScope.registration.get_spec(event=event)

        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()

            # create one list per track
            for part in rs.ambience["event"]["parts"].values():
                for track_id, track in part["tracks"].items():
                    fields_of_interest = ["persona.given_names", "persona.family_name",
                                          f"track{track_id}.course_id"]
                    constrains = [(f"track{track_id}.course_id",
                                   QueryOperators.nonempty, None)]
                    order = [("persona.given_names", True)]
                    query = Query(QueryScope.registration, spec, fields_of_interest,
                                  constrains, order)
                    query_res = self.eventproxy.submit_general_query(rs, query,
                                                                     event_id)
                    course_key = f"track{track_id}.course_id"
                    # we have to replace the course id with the course number
                    result = tuple(
                        {
                            k if k != course_key else 'course':
                                v if k != course_key else courses[v]['nr']
                            for k, v in entry.items()
                        }
                        for entry in query_res
                    )
                    data = self.fill_template(
                        rs, "other", "dokuteam_participant_list", {'result': result})

                    # save the result in one file per track
                    filename = f"{asciificator(track['shortname'])}.csv"
                    file = pathlib.Path(work_dir, filename)
                    file.write_text(data, encoding='utf-8')

            # create a zip archive of all lists
            zipname = f"{rs.ambience['event']['shortname']}_dokuteam_participant_list"
            zippath = shutil.make_archive(str(pathlib.Path(tmp_dir, zipname)), 'zip',
                                          base_dir=work_dir, root_dir=tmp_dir)

            return self.send_file(rs, path=zippath, inline=False,
                                  filename=f"{zipname}.zip")

    @access("event")
    @event_guard()
    def download_csv_courses(self, rs: RequestState, event_id: int) -> Response:
        """Create CSV file with all courses"""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        spec = QueryScope.event_course.get_spec(
            event=rs.ambience['event'], courses=courses)
        choices = {k: v.choices for k, v in spec.items() if v.choices}
        fields_of_interest = list(spec.keys())
        query = Query(QueryScope.event_course, spec, fields_of_interest,
                      constraints=[], order=[])
        result = self.eventproxy.submit_general_query(rs, query, event_id=event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_courses")

    @access("event")
    @event_guard()
    def download_csv_lodgements(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Create CSV file with all courses"""
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)

        spec = QueryScope.lodgement.get_spec(
            event=rs.ambience['event'], lodgements=lodgements, lodgement_groups=groups)
        choices = {k: v.choices for k, v in spec.items() if v.choices}
        fields_of_interest = list(spec.keys())
        query = Query(QueryScope.lodgement, spec, fields_of_interest,
                      constraints=[], order=[])
        result = self.eventproxy.submit_general_query(rs, query, event_id=event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_lodgements")

    @access("event")
    @event_guard()
    def download_csv_registrations(self, rs: RequestState, event_id: int
                                   ) -> Response:
        """Create CSV file with all registrations"""
        # Get data
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)

        spec = QueryScope.registration.get_spec(
            event=rs.ambience['event'], courses=courses, lodgements=lodgements,
            lodgement_groups=lodgement_groups)
        choices = {k: v.choices for k, v in spec.items() if v.choices}
        fields_of_interest = list(spec.keys())
        query = Query(QueryScope.registration, spec, fields_of_interest,
                      constraints=[], order=[])
        result = self.eventproxy.submit_general_query(rs, query, event_id=event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_registrations")

    @access("event", modi={"GET"})
    @event_guard()
    @REQUESTdata("agree_unlocked_download")
    def download_export(self, rs: RequestState, event_id: int,
                        agree_unlocked_download: Optional[bool]) -> Response:
        """Retrieve all data for this event to initialize an offline
        instance."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")

        if not (agree_unlocked_download
                or rs.ambience['event']['offline_lock']):
            rs.notify("info", n_("Please confirm to download a full export of "
                                 "an unlocked event."))
            return self.redirect(rs, "event/show_event")
        data = self.eventproxy.export_event(rs, event_id)
        if not data:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/show_event")
        json = json_serialize(data)
        return self.send_file(
            rs, data=json, inline=False,
            filename=f"{rs.ambience['event']['shortname']}_export_event.json")

    @access("event")
    @event_guard()
    def download_partial_export(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Retrieve data for third-party applications."""
        data = self.eventproxy.partial_export_event(rs, event_id)
        if not data:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        json = json_serialize(data)
        return self.send_file(
            rs, data=json, inline=False,
            filename="{}_partial_export_event.json".format(
                rs.ambience['event']['shortname']))

    @access("droid_quick_partial_export")
    def download_quick_partial_export(self, rs: RequestState) -> Response:
        """Retrieve data for third-party applications in offline mode.

        This is a zero-config variant of download_partial_export.
        """
        ret = {
            'message': "",
            'export': {},
        }
        if not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            ret['message'] = "Not in offline mode."
            return self.send_json(rs, ret)
        events = self.eventproxy.list_events(rs)
        if len(events) != 1:
            ret['message'] = "Exactly one event must exist."
            return self.send_json(rs, ret)
        event_id = unwrap(events.keys())
        ret['export'] = self.eventproxy.partial_export_event(rs, event_id)
        ret['message'] = "success"
        return self.send_json(rs, ret)
