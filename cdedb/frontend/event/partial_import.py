#!/usr/bin/env python3

"""
The `EventImportMixin` subclasses the `EventBaseFrontend` and provides endpoints for
both the partial import and the questionnaire import.
"""

import collections.abc
import json
from typing import Any, Mapping, Optional, Set, Tuple

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, PartialImportError, RequestState, json_serialize, n_,
    xsorted,
)
from cdedb.filter import enum_entries_filter, safe_filter
from cdedb.frontend.common import (
    REQUESTdata, REQUESTfile, access, check_validation as check, event_guard,
)
from cdedb.frontend.event.base import EventBaseFrontend


class EventImportMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def questionnaire_import_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form for uploading questionnaire data."""
        return self.render(rs, "import/questionnaire_import")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("json_file")
    @REQUESTdata("extend_questionnaire", "skip_existing_fields", "token")
    def questionnaire_import(
        self, rs: RequestState, event_id: int,
        json_file: Optional[werkzeug.datastructures.FileStorage],
        extend_questionnaire: bool, skip_existing_fields: bool, token: Optional[str],
    ) -> Response:
        """Import questionnaire rows and custom datafields.

        :param extend_questionnaire: If True, append the imported questionnaire rows to
            any existing ones. Otherwise replace the existing ones.
        :param skip_existing_fields: If True, the import of fields that already exist
            is skipped, even if their definition is different from the existing one.
            Otherwise, duplicate field names will cause an error and prevent the import.
        """
        kwargs = {
            'field_definitions': rs.ambience['event']['fields'],
            'fee_modifiers': rs.ambience['event']['fee_modifiers'],
            'questionnaire': self.eventproxy.get_questionnaire(rs, event_id),
            'extend_questionnaire': extend_questionnaire,
            'skip_existing_fields': skip_existing_fields,
        }
        data = check(rs, vtypes.SerializedEventQuestionnaireUpload, json_file,
                     **kwargs)
        if rs.has_validation_errors():
            return self.questionnaire_import_form(rs, event_id)
        assert data is not None

        code = self.eventproxy.questionnaire_import(
            rs, event_id, fields=data['fields'], questionnaire=data['questionnaire'])

        rs.notify_return_code(code)
        return self.redirect(rs, "event/configure_additional_questionnaire")

    @access("event")
    @event_guard()
    def partial_import_form(self, rs: RequestState, event_id: int) -> Response:
        """First step of partial import process: Render form to upload file"""
        return self.render(rs, "import/partial_import")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("json_file")
    @REQUESTdata("partial_import_data", "token")
    def partial_import(self, rs: RequestState, event_id: int,
                       json_file: Optional[werkzeug.datastructures.FileStorage],
                       partial_import_data: Optional[str], token: Optional[str]
                       ) -> Response:
        """Further steps of partial import process

        This takes the changes and generates a transaction token. If the new
        token agrees with the submitted token, the change were successfully
        applied, otherwise a diff-view of the changes is displayed.

        In the first iteration the data is extracted from a file upload and
        in further iterations it is embedded in the page.
        """
        # ignore ValidationWarnings here to not prevent submission.
        # TODO We show them later in the diff.
        rs.ignore_warnings = True

        if partial_import_data:
            data = check(rs, vtypes.SerializedPartialEvent,
                         json.loads(partial_import_data))
        else:
            data = check(rs, vtypes.SerializedPartialEventUpload, json_file)
        if rs.has_validation_errors():
            return self.partial_import_form(rs, event_id)
        assert data is not None
        if event_id != data['id']:
            rs.notify("error", n_("Data from wrong event."))
            return self.partial_import_form(rs, event_id)

        # First gather infos for comparison
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(
            rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(
            rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(
            rs, lodgement_group_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        persona_ids = (
            ({e['persona_id'] for e in registrations.values()}
             | {e.get('persona_id')
                for e in data.get('registrations', {}).values() if e})
            - {None})
        personas = self.coreproxy.get_personas(rs, persona_ids)

        # Second invoke partial import
        try:
            new_token, delta = self.eventproxy.partial_import_event(
                rs, data, dryrun=(not bool(token)), token=token)
        except PartialImportError:
            rs.notify("warning",
                      n_("The data changed, please review the difference."))
            token = None
            new_token, delta = self.eventproxy.partial_import_event(
                rs, data, dryrun=True)

        # Third check if we were successful
        if token == new_token:
            rs.notify("success", n_("Changes applied."))
            return self.redirect(rs, "event/show_event")

        # Fourth prepare
        rs.values['token'] = new_token
        rs.values['partial_import_data'] = json_serialize(data)
        for course in courses.values():
            course['segments'] = {
                id: id in course['active_segments']
                for id in course['segments']
            }

        # Fifth prepare summary
        def flatten_recursive_delta(data: Mapping[Any, Any],
                                    old: Mapping[Any, Any],
                                    prefix: str = "") -> CdEDBObject:
            ret = {}
            for key, val in data.items():
                if isinstance(val, collections.abc.Mapping):
                    tmp = flatten_recursive_delta(
                        val, old.get(key, {}), f"{prefix}{key}.")
                    ret.update(tmp)
                else:
                    ret[f"{prefix}{key}"] = (old.get(key, None), val)
            return ret

        summary: CdEDBObject = {
            'changed_registrations': {
                anid: flatten_recursive_delta(val, registrations[anid])
                for anid, val in delta.get('registrations', {}).items()
                if anid > 0 and val
            },
            'new_registration_ids': tuple(xsorted(
                anid for anid in delta.get('registrations', {})
                if anid < 0)),
            'deleted_registration_ids': tuple(xsorted(
                anid for anid, val in delta.get('registrations', {}).items()
                if val is None)),
            'real_deleted_registration_ids': tuple(xsorted(
                anid for anid, val in delta.get('registrations', {}).items()
                if val is None and registrations.get(anid))),
            'changed_courses': {
                anid: flatten_recursive_delta(val, courses[anid])
                for anid, val in delta.get('courses', {}).items()
                if anid > 0 and val
            },
            'new_course_ids': tuple(xsorted(
                anid for anid in delta.get('courses', {}) if anid < 0)),
            'deleted_course_ids': tuple(xsorted(
                anid for anid, val in delta.get('courses', {}).items()
                if val is None)),
            'real_deleted_course_ids': tuple(xsorted(
                anid for anid, val in delta.get('courses', {}).items()
                if val is None and courses.get(anid))),
            'changed_lodgements': {
                anid: flatten_recursive_delta(val, lodgements[anid])
                for anid, val in delta.get('lodgements', {}).items()
                if anid > 0 and val
            },
            'new_lodgement_ids': tuple(xsorted(
                anid for anid in delta.get('lodgements', {}) if anid < 0)),
            'deleted_lodgement_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgements', {}).items()
                if val is None)),
            'real_deleted_lodgement_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgements', {}).items()
                if val is None and lodgements.get(anid))),

            'changed_lodgement_groups': {
                anid: flatten_recursive_delta(val, lodgement_groups[anid])
                for anid, val in delta.get('lodgement_groups', {}).items()
                if anid > 0 and val},
            'new_lodgement_group_ids': tuple(xsorted(
                anid for anid in delta.get('lodgement_groups', {})
                if anid < 0)),
            'real_deleted_lodgement_group_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgement_groups', {}).items()
                if val is None and lodgement_groups.get(anid))),
        }

        changed_registration_fields: Set[str] = set()
        for reg in summary['changed_registrations'].values():
            changed_registration_fields |= reg.keys()
        summary['changed_registration_fields'] = tuple(xsorted(
            changed_registration_fields))
        changed_course_fields: Set[str] = set()
        for course in summary['changed_courses'].values():
            changed_course_fields |= course.keys()
        summary['changed_course_fields'] = tuple(xsorted(
            changed_course_fields))
        changed_lodgement_fields: Set[str] = set()
        for lodgement in summary['changed_lodgements'].values():
            changed_lodgement_fields |= lodgement.keys()
        summary['changed_lodgement_fields'] = tuple(xsorted(
            changed_lodgement_fields))

        (reg_titles, reg_choices, course_titles, course_choices,
         lodgement_titles) = self._make_partial_import_diff_aux(
            rs, rs.ambience['event'], courses, lodgements)

        # Sixth look for double deletions/creations
        if (len(summary['deleted_registration_ids'])
                > len(summary['real_deleted_registration_ids'])):
            rs.notify('warning', n_("There were double registration deletions."
                                    " Did you already import this file?"))
        if len(summary['deleted_course_ids']) > len(summary['real_deleted_course_ids']):
            rs.notify('warning', n_("There were double course deletions."
                                    " Did you already import this file?"))
        if (len(summary['deleted_lodgement_ids'])
                > len(summary['real_deleted_lodgement_ids'])):
            rs.notify('warning', n_("There were double lodgement deletions."
                                    " Did you already import this file?"))
        all_current_data = self.eventproxy.partial_export_event(rs, data['id'])
        for course_id, course in delta.get('courses', {}).items():
            if course_id < 0:
                if any(current == course
                       for current in all_current_data['courses'].values()):
                    rs.notify('warning',
                              n_("There were hints at double course creations."
                                 " Did you already import this file?"))
                    break
        for lodgement_id, lodgement in delta.get('lodgements', {}).items():
            if lodgement_id < 0:
                if any(current == lodgement
                       for current in all_current_data['lodgements'].values()):
                    rs.notify('warning',
                              n_("There were hints at double lodgement creations."
                                 " Did you already import this file?"))
                    break

        # Seventh render diff
        template_data = {
            'delta': delta,
            'registrations': registrations,
            'lodgements': lodgements,
            'lodgement_groups': lodgement_groups,
            'courses': courses,
            'personas': personas,
            'summary': summary,
            'reg_titles': reg_titles,
            'reg_choices': reg_choices,
            'course_titles': course_titles,
            'course_choices': course_choices,
            'lodgement_titles': lodgement_titles,
        }
        return self.render(rs, "import/partial_import_check", template_data)

    # TODO: be more specific about the return types.
    @staticmethod
    def _make_partial_import_diff_aux(
            rs: RequestState, event: CdEDBObject, courses: CdEDBObjectMap,
            lodgements: CdEDBObjectMap
    ) -> Tuple[CdEDBObject, CdEDBObject, CdEDBObject, CdEDBObject, CdEDBObject]:
        """ Helper method, similar to make_registration_query_aux(), to
        generate human readable field names and values for the diff presentation
        of partial_import().

        This method does only generate titles and choice-dicts for the dynamic,
        event-specific fields (i.e. part- and track-specific and custom fields).
        Titles for all static fields are added in the template file."""
        reg_titles = {}
        reg_choices = {}
        course_titles = {}
        course_choices = {}
        lodgement_titles = {}

        # Prepare choices lists
        # TODO distinguish old and new course/lodgement titles
        # Heads up! There's a protected space (u+00A0) in the string below
        course_entries = {
            c["id"]: "{}. {}".format(c["nr"], c["shortname"])
            for c in courses.values()}
        lodgement_entries = {lgd["id"]: lgd["title"] for lgd in lodgements.values()}
        reg_part_stati_entries =\
            dict(enum_entries_filter(const.RegistrationPartStati, rs.gettext))
        segment_stati_entries = {
            None: rs.gettext('not offered'),
            False: rs.gettext('cancelled'),
            True: rs.gettext('takes place'),
        }

        # Titles and choices for track-specific fields
        for track_id, track in event['tracks'].items():
            if len(event['tracks']) > 1:
                prefix = "{title}: ".format(title=track['shortname'])
            else:
                prefix = ""
            reg_titles[f"tracks.{track_id}.course_id"] = (
                    prefix + rs.gettext("Course"))
            reg_choices[f"tracks.{track_id}.course_id"] = course_entries
            reg_titles[f"tracks.{track_id}.course_instructor"] = (
                    prefix + rs.gettext("Instructor"))
            reg_choices[f"tracks.{track_id}.course_instructor"] = course_entries
            reg_titles[f"tracks.{track_id}.choices"] = (
                    prefix + rs.gettext("Course Choices"))
            reg_choices[f"tracks.{track_id}.choices"] = course_entries
            course_titles[f"segments.{track_id}"] = (
                    prefix + rs.gettext("Status"))
            course_choices[f"segments.{track_id}"] = segment_stati_entries

        for field in event['fields'].values():
            # TODO add choices?
            key = f"fields.{field['field_name']}"
            title = safe_filter("<i>{}</i>").format(field['field_name'])
            if field['association'] == const.FieldAssociations.registration:
                reg_titles[key] = title
            elif field['association'] == const.FieldAssociations.course:
                course_titles[key] = title
            elif field['association'] == const.FieldAssociations.lodgement:
                lodgement_titles[key] = title

        # Titles and choices for part-specific fields
        for part_id, part in event['parts'].items():
            if len(event['parts']) > 1:
                prefix = f"{part['shortname']}: "
            else:
                prefix = ""
            reg_titles[f"parts.{part_id}.status"] = (
                    prefix + rs.gettext("Status"))
            reg_choices[f"parts.{part_id}.status"] = reg_part_stati_entries
            reg_titles[f"parts.{part_id}.lodgement_id"] = (
                    prefix + rs.gettext("Lodgement"))
            reg_choices[f"parts.{part_id}.lodgement_id"] = lodgement_entries
            reg_titles[f"parts.{part_id}.is_camping_mat"] = (
                    prefix + rs.gettext("Camping Mat"))

        return (reg_titles, reg_choices, course_titles, course_choices,
                lodgement_titles)
