#!/usr/bin/env python3

"""
The `EventRegistrationMixin` subclasses the `EventBaseFrontend` and provides endpoints
for managing registrations both by orgas and participants.
"""

import csv
import datetime
import decimal
import re
from collections import OrderedDict
from typing import Collection, Dict, Optional, Tuple, Union

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, EntitySorter, RequestState, determine_age_class,
    diacritic_patterns, get_hash, merge_dicts, n_, now, unwrap, xsorted,
)
from cdedb.filter import keydictsort_filter
from cdedb.frontend.common import (
    CustomCSVDialect, REQUESTdata, REQUESTfile, TransactionObserver, access,
    cdedbid_filter, check_validation_optional as check_optional, event_guard,
    inspect_validation as inspect, make_event_fee_reference, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.query import Query, QueryOperators, QueryScope
from cdedb.validationtypes import VALIDATOR_LOOKUP


class EventRegistrationMixin(EventBaseFrontend):
    @access("event")
    @event_guard(check_offline=True)
    def batch_fees_form(self, rs: RequestState, event_id: int,
                        data: Collection[CdEDBObject] = None,
                        csvfields: Collection[str] = None,
                        saldo: decimal.Decimal = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['persona_id'] = csv_position.pop('id', -1)
        return self.render(rs, "registration/batch_fees",
                           {'data': data, 'csvfields': csv_position,
                            'saldo': saldo})

    def examine_fee(self, rs: RequestState, datum: CdEDBObject,
                    expected_fees: Dict[int, decimal.Decimal],
                    full_payment: bool = True) -> CdEDBObject:
        """Check one line specifying a paid fee.

        We test for fitness of the data itself.

        :param full_payment: If True, only write the payment date if the fee
            was paid in full.
        :returns: The processed input datum.
        """
        event = rs.ambience['event']
        warnings = []
        infos = []
        # Allow an amount of zero to allow non-modification of amount_paid.
        amount: Optional[decimal.Decimal]
        amount, problems = inspect(vtypes.NonNegativeDecimal,
            (datum['raw']['amount'] or "").strip(), argname="amount")
        persona_id, p = inspect(vtypes.CdedbID,
            (datum['raw']['id'] or "").strip(), argname="persona_id")
        problems.extend(p)
        family_name, p = inspect(str,
            datum['raw']['family_name'], argname="family_name")
        problems.extend(p)
        given_names, p = inspect(str,
            datum['raw']['given_names'], argname="given_names")
        problems.extend(p)
        date, p = inspect(datetime.date,
            (datum['raw']['date'] or "").strip(), argname="date")
        problems.extend(p)

        registration_id = None
        original_date = date
        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append(('persona_id',
                                 ValueError(
                                     n_("No Member with ID %(p_id)s found."),
                                     {"p_id": persona_id})))
            else:
                registration_ids = self.eventproxy.list_registrations(
                    rs, event['id'], persona_id).keys()
                if registration_ids:
                    registration_id = unwrap(registration_ids)
                    registration = self.eventproxy.get_registration(
                        rs, registration_id)
                    amount = amount or decimal.Decimal(0)
                    amount_paid = registration['amount_paid']
                    total = amount + amount_paid
                    fee = expected_fees[registration_id]
                    if total < fee:
                        error = ('amount', ValueError(n_("Not enough money.")))
                        if full_payment:
                            warnings.append(error)
                            date = None
                        else:
                            infos.append(error)
                    elif total > fee:
                        warnings.append(('amount',
                                         ValueError(n_("Too much money."))))
                else:
                    problems.append(('persona_id',
                                     ValueError(n_("No registration found."))))

                if family_name is not None and not re.search(
                    diacritic_patterns(re.escape(family_name)),
                    persona['family_name'],
                    flags=re.IGNORECASE
                ):
                    warnings.append(('family_name', ValueError(
                        n_("Family name doesn’t match."))))

                if given_names is not None and not re.search(
                    diacritic_patterns(re.escape(given_names)),
                    persona['given_names'],
                    flags=re.IGNORECASE
                ):
                    warnings.append(('given_names', ValueError(
                        n_("Given names don’t match."))))
        datum.update({
            'persona_id': persona_id,
            'registration_id': registration_id,
            'date': date,
            'original_date': original_date,
            'amount': amount,
            'warnings': warnings,
            'problems': problems,
            'infos': infos,
        })
        return datum

    def book_fees(self, rs: RequestState,
                  data: Collection[CdEDBObject], send_notifications: bool = False
                  ) -> Tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        relevant_keys = {'registration_id', 'date', 'original_date', 'amount'}
        relevant_data = [{k: v for k, v in item.items() if k in relevant_keys}
                         for item in data]
        with TransactionObserver(rs, self, "book_fees"):
            success, number = self.eventproxy.book_fees(
                rs, rs.ambience['event']['id'], relevant_data)
            if success and send_notifications:
                persona_ids = tuple(e['persona_id'] for e in data)
                personas = self.coreproxy.get_personas(rs, persona_ids)
                subject = "Überweisung für {} eingetroffen".format(
                    rs.ambience['event']['title'])
                for persona in personas.values():
                    headers: Dict[str, Union[str, Collection[str]]] = {
                        'To': (persona['username'],),
                        'Subject': subject,
                    }
                    if rs.ambience['event']['orga_address']:
                        headers['Reply-To'] = rs.ambience['event']['orga_address']
                    self.do_mail(rs, "transfer_received", headers,
                                 {'persona': persona})
            return success, number

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("fee_data_file")
    @REQUESTdata("force", "fee_data", "checksum", "send_notifications", "full_payment")
    def batch_fees(self, rs: RequestState, event_id: int, force: bool,
                   fee_data: Optional[str],
                   fee_data_file: Optional[werkzeug.datastructures.FileStorage],
                   checksum: Optional[str], send_notifications: bool,
                   full_payment: bool) -> Response:
        """Allow orgas to add lots paid of participant fee at once."""
        fee_data_file = check_optional(
            rs, vtypes.CSVFile, fee_data_file, "fee_data_file")
        if rs.has_validation_errors():
            return self.batch_fees_form(rs, event_id)

        if fee_data_file and fee_data:
            rs.notify("warning", n_("Only one input method allowed."))
            return self.batch_fees_form(rs, event_id)
        elif fee_data_file:
            rs.values["fee_data"] = fee_data_file
            fee_data = fee_data_file
            fee_data_lines = fee_data_file.splitlines()
        elif fee_data:
            fee_data_lines = fee_data.splitlines()
        else:
            rs.notify("error", n_("No input provided."))
            return self.batch_fees_form(rs, event_id)

        reg_ids = self.eventproxy.list_registrations(rs, event_id=event_id)
        expected_fees = self.eventproxy.calculate_fees(rs, reg_ids)

        fields = ('amount', 'id', 'family_name', 'given_names', 'date')
        reader = csv.DictReader(
            fee_data_lines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        for lineno, raw_entry in enumerate(reader):
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno}
            data.append(self.examine_fee(rs, dataset, expected_fees, full_payment))
        open_issues = any(e['problems'] for e in data)
        saldo: decimal.Decimal = sum(
            (e['amount'] for e in data if e['amount']), decimal.Decimal("0.00"))
        if not force:
            open_issues = open_issues or any(e['warnings'] for e in data)
        if rs.has_validation_errors() or not data or open_issues:
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

        current_checksum = get_hash(fee_data.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields, saldo=saldo)

        # Here validation is finished
        success, num = self.book_fees(rs, data, send_notifications)
        if success:
            rs.notify("success", n_("Committed %(num)s fees."), {'num': num})
            return self.redirect(rs, "event/show_event")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line {num}."),
                          {'num': num + 1})
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

    @access("event")
    @REQUESTdata("preview")
    def register_form(self, rs: RequestState, event_id: int,
                      preview: bool = False) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'],
            event['begin'])
        minor_form = self.eventproxy.get_minor_form(rs, event_id)
        rs.ignore_validation_errors()
        if not preview:
            if rs.user.persona_id in registrations.values():
                rs.notify("info", n_("Already registered."))
                return self.redirect(rs, "event/registration_status")
            if not event['is_open']:
                rs.notify("warning", n_("Registration not open."))
                return self.redirect(rs, "event/show_event")
            if self.is_locked(event):
                rs.notify("warning", n_("Event locked."))
                return self.redirect(rs, "event/show_event")
            if rs.ambience['event']['is_archived']:
                rs.notify("error", n_("Event is already archived."))
                return self.redirect(rs, "event/show_event")
            if not minor_form and age.is_minor():
                rs.notify("info", n_("No minors may register. "
                                     "Please contact the Orgateam."))
                return self.redirect(rs, "event/show_event")
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    n_("Must be Orga to use preview."))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']
                           or (not event['is_course_state_visible']
                               and track_id in course['segments'])]
            for track_id in tracks}
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        # by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', event['parts'])
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "registration/register", {
            'persona': persona, 'age': age, 'courses': courses,
            'course_choices': course_choices, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'preview': preview})

    def process_registration_input(
            self, rs: RequestState, event: CdEDBObject, courses: CdEDBObjectMap,
            reg_questionnaire: Collection[CdEDBObject],
            parts: CdEDBObjectMap = None) -> CdEDBObject:
        """Helper to handle input by participants.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event.

        :param parts: If not None this specifies the ids of the parts this
          registration applies to (since you can apply for only some of the
          parts of an event and should not have to choose courses for the
          non-relevant parts this is important). If None the parts have to
          be provided in the input.
        :returns: registration data set
        """
        tracks = event['tracks']
        standard_params: vtypes.TypeMapping = {
            "mixed_lodging": bool,
            "notes": Optional[str],  # type: ignore
            "list_consent": bool
        }
        if parts is None:
            standard_params["parts"] = Collection[int]  # type: ignore
        standard = request_extractor(rs, standard_params)
        if parts is not None:
            standard['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params: vtypes.TypeMapping = {
            f"course_choice{track_id}_{i}": Optional[vtypes.ID]  # type: ignore
            for part_id in standard['parts']
            for track_id in event['parts'][part_id]['tracks']
            for i in range(event['tracks'][track_id]['num_choices'])
        }
        choices = request_extractor(rs, choice_params)
        instructor_params: vtypes.TypeMapping = {
            f"course_instructor{track_id}": Optional[vtypes.ID]  # type: ignore
            for part_id in standard['parts']
            for track_id in event['parts'][part_id]['tracks']
        }
        instructor = request_extractor(rs, instructor_params)
        if not standard['parts']:
            rs.append_validation_error(
                ("parts", ValueError(n_("Must select at least one part."))))
        present_tracks = set()
        choice_getter = (
            lambda track_id, i: choices[f"course_choice{track_id}_{i}"])
        for part_id in standard['parts']:
            for track_id, track in event['parts'][part_id]['tracks'].items():
                present_tracks.add(track_id)
                # Check for duplicate course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, j),
                     ValueError(n_("You cannot have the same course as %(i)s."
                                   " and %(j)s. choice"), {'i': i+1, 'j': j+1}))
                    for j in range(track['num_choices'])
                    for i in range(j)
                    if (choice_getter(track_id, j) is not None
                        and choice_getter(track_id, i)
                            == choice_getter(track_id, j)))
                # Check for unfilled mandatory course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, i),
                     ValueError(n_("You must choose at least %(min_choices)s"
                                   " courses."),
                                {'min_choices': track['min_choices']}))
                    for i in range(track['min_choices'])
                    if choice_getter(track_id, i) is None)
        reg_parts: CdEDBObjectMap = {part_id: {} for part_id in event['parts']}
        if parts is None:
            for part_id in reg_parts:
                stati = const.RegistrationPartStati
                if part_id in standard['parts']:
                    reg_parts[part_id]['status'] = stati.applied
                else:
                    reg_parts[part_id]['status'] = stati.not_applied
        reg_tracks = {
            track_id: {
                'course_instructor':
                    instructor.get("course_instructor{}".format(track_id))
                    if track['num_choices'] else None,
            }
            for track_id, track in tracks.items()
        }
        for track_id in present_tracks:
            all_choices = tuple(
                choice_getter(track_id, i)
                for i in range(tracks[track_id]['num_choices'])
                if choice_getter(track_id, i) is not None)

            if reg_tracks[track_id]["course_instructor"] in all_choices:
                i_choice = all_choices.index(reg_tracks[track_id]["course_instructor"])
                rs.add_validation_error(
                    (f"course_choice{track_id}_{i_choice}",
                     ValueError(n_("You may not choose your own course.")))
                )
            reg_tracks[track_id]['choices'] = all_choices

        params = self._questionnaire_params(rs, const.QuestionnaireUsages.registration)
        field_data = request_extractor(rs, params)

        registration = {
            'mixed_lodging': standard['mixed_lodging'],
            'list_consent': standard['list_consent'],
            'notes': standard['notes'],
            'parts': reg_parts,
            'tracks': reg_tracks,
            'fields': field_data,
        }
        return registration

    @access("event", modi={"POST"})
    def register(self, rs: RequestState, event_id: int) -> Response:
        """Register for an event."""
        if rs.has_validation_errors():
            return self.register_form(rs, event_id)
        if not rs.ambience['event']['is_open']:
            rs.notify("error", n_("Registration not open."))
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/show_event")
        if rs.ambience['event']['is_archived']:
            rs.notify("error", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        if self.eventproxy.list_registrations(rs, event_id, rs.user.persona_id):
            rs.notify("error", n_("Already registered."))
            return self.redirect(rs, "event/registration_status")
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, reg_questionnaire)
        if rs.has_validation_errors():
            return self.register_form(rs, event_id)
        registration['event_id'] = event_id
        registration['persona_id'] = rs.user.persona_id
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        minor_form = self.eventproxy.get_minor_form(rs, event_id)
        if not minor_form and age.is_minor():
            rs.notify("error", n_("No minors may register. "
                                  "Please contact the Orgateam."))
            return self.redirect(rs, "event/show_event")
        registration['parental_agreement'] = not age.is_minor()
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration)
        meta_info = self.coreproxy.get_meta_info(rs)
        fee = self.eventproxy.calculate_fee(rs, new_id)
        semester_fee = self.conf["MEMBERSHIP_FEE"]

        subject = "Anmeldung für {}".format(rs.ambience['event']['title'])
        reply_to = (rs.ambience['event']['orga_address'] or
                    self.conf["EVENT_ADMIN_ADDRESS"])
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': subject,
             'Reply-To': reply_to},
            {'fee': fee, 'age': age, 'meta_info': meta_info,
             'semester_fee': semester_fee, 'reference': reference})
        rs.notify_return_code(new_id, success=n_("Registered for event."))
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def registration_status(self, rs: RequestState, event_id: int) -> Response:
        """Present current state of own registration."""
        reg_list = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not reg_list:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(reg_list.keys())
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        part_order = xsorted(
            registration['parts'].keys(),
            key=lambda anid:
                rs.ambience['event']['parts'][anid]['part_begin'])
        registration['parts'] = OrderedDict(
            (part_id, registration['parts'][part_id]) for part_id in part_order)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, (const.QuestionnaireUsages.registration,)))
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=rs.user.persona_id)
        return self.render(rs, "registration/registration_status", {
            'registration': registration, 'age': age, 'courses': courses,
            'meta_info': meta_info, 'fee': fee, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'reference': reference,
            'waitlist_position': waitlist_position,
        })

    @access("event")
    def amend_registration_form(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys())
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if event['is_archived']:
            rs.notify("warning", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        if (event['registration_soft_limit'] and
                now() > event['registration_soft_limit']):
            rs.notify("warning",
                      n_("Registration closed, no changes possible."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']
                           or (not event['is_course_state_visible']
                               and track_id in course['segments'])]
            for track_id in tracks}
        non_trivials = {}
        for track_id, track in registration['tracks'].items():
            for i, choice in enumerate(track['choices']):
                param = "course_choice{}_{}".format(track_id, i)
                non_trivials[param] = choice
        for track_id, entry in registration['tracks'].items():
            param = "course_instructor{}".format(track_id)
            non_trivials[param] = entry['course_instructor']
        for k, v in registration['fields'].items():
            non_trivials[k] = v
        stat = lambda track: registration['parts'][track['part_id']]['status']
        involved_tracks = {
            track_id for track_id, track in tracks.items()
            if const.RegistrationPartStati(stat(track)).is_involved()}
        merge_dicts(rs.values, non_trivials, registration)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "registration/amend_registration", {
            'age': age, 'courses': courses, 'course_choices': course_choices,
            'involved_tracks': involved_tracks,
            'reg_questionnaire': reg_questionnaire,
        })

    @access("event", modi={"POST"})
    def amend_registration(self, rs: RequestState, event_id: int) -> Response:
        """Change information provided during registering.

        Participants are not able to change for which parts they applied on
        purpose. For this they have to communicate with the orgas.
        """
        if rs.has_validation_errors():
            return self.amend_registration_form(rs, event_id)
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys())
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if (rs.ambience['event']['registration_soft_limit'] and
                now() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("error", n_("No changes allowed anymore."))
            return self.redirect(rs, "event/registration_status")
        if rs.ambience['event']['is_archived']:
            rs.notify("error", n_("Event is already archived."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        stored = self.eventproxy.get_registration(rs, registration_id)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, reg_questionnaire,
            parts=stored['parts'])
        if rs.has_validation_errors():
            return self.amend_registration_form(rs, event_id)

        registration['id'] = registration_id
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        change_note = "Anmeldung durch Teilnehmer bearbeitet."
        code = self.eventproxy.set_registration(rs, registration, change_note)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    @event_guard()
    def show_registration(self, rs: RequestState, event_id: int,
                          registration_id: int) -> Response:
        """Display all information pertaining to one registration."""
        persona = self.coreproxy.get_event_user(
            rs, rs.ambience['registration']['persona_id'], event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=persona['id'])
        return self.render(rs, "registration/show_registration", {
            'persona': persona, 'age': age, 'courses': courses,
            'lodgements': lodgements, 'meta_info': meta_info, 'fee': fee,
            'reference': reference, 'waitlist_position': waitlist_position,
        })

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("skip", "change_note")
    def change_registration_form(self, rs: RequestState, event_id: int,
                                 registration_id: int, skip: Collection[str],
                                 change_note: Optional[str], internal: bool = False
                                 ) -> Response:
        """Render form.

        The skip parameter is meant to hide certain fields and skip them when
        evaluating the submitted from in change_registration(). This can be
        used in situations, where changing those fields could override
        concurrent changes (e.g. the Check-in).


        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, 'event/show_registration')
        tracks = rs.ambience['event']['tracks']
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_event_user(rs, registration['persona_id'],
                                                event_id)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['segments']]
            for track_id in tracks}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        reg_values = {"reg.{}".format(key): value
                      for key, value in registration.items()}
        part_values = []
        for part_id, part in registration['parts'].items():
            one_part = {
                "part{}.{}".format(part_id, key): value
                for key, value in part.items()}
            part_values.append(one_part)
        track_values = []
        for track_id, track in registration['tracks'].items():
            one_track = {
                "track{}.{}".format(track_id, key): value
                for key, value in track.items()
                if key != "choices"}
            for i, choice in enumerate(track['choices']):
                key = 'track{}.course_choice_{}'.format(track_id, i)
                one_track[key] = choice
            track_values.append(one_track)
        field_values = {
            "fields.{}".format(key): value
            for key, value in registration['fields'].items()}
        # Fix formatting of ID
        reg_values['reg.real_persona_id'] = cdedbid_filter(
            reg_values['reg.real_persona_id'])
        merge_dicts(rs.values, reg_values, field_values,
                    *(part_values + track_values))
        return self.render(rs, "registration/change_registration", {
            'persona': persona, 'courses': courses,
            'course_choices': course_choices, 'lodgements': lodgements,
            'skip': skip or [], 'change_note': change_note})

    @staticmethod
    def process_orga_registration_input(
            rs: RequestState, event: CdEDBObject, do_fields: bool = True,
            check_enabled: bool = False, skip: Collection[str] = (),
            do_real_persona_id: bool = False) -> CdEDBObject:
        """Helper to handle input by orgas.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event. This puts less restrictions
        on the input (like not requiring different course choices).

        :param do_fields: Process custom fields of the registration(s)
        :param check_enabled: Check if the "enable" checkboxes, corresponding
                              to the fields are set. This is required for the
                              multiedit page.
        :param skip: A list of field names to be entirely skipped
        :param do_real_persona_id: Process the `real_persona_id` field. Should
                                   only be done when CDEDB_OFFLINE_DEPLOYMENT
        :returns: registration data set
        """

        def filter_parameters(params: vtypes.TypeMapping) -> vtypes.TypeMapping:
            """Helper function to filter parameters by `skip` list and `enabled`
            checkboxes"""
            params = {key: kind for key, kind in params.items() if key not in skip}
            if not check_enabled:
                return params
            enable_params = {f"enable_{i}": bool for i, t in params.items()}
            enable = request_extractor(rs, enable_params)
            return {
                key: kind for key, kind in params.items() if enable[f"enable_{key}"]}

        # Extract parameters from request
        tracks = event['tracks']
        reg_params: vtypes.TypeMapping = {
            "reg.notes": Optional[str],  # type: ignore
            "reg.orga_notes": Optional[str],  # type: ignore
            "reg.payment": Optional[datetime.date],  # type: ignore
            "reg.amount_paid": vtypes.NonNegativeDecimal,
            "reg.parental_agreement": bool,
            "reg.mixed_lodging": bool,
            "reg.checkin": Optional[datetime.datetime],  # type: ignore
            "reg.list_consent": bool,
        }
        part_params: vtypes.TypeMapping = {}
        for part_id in event['parts']:
            part_params.update({  # type: ignore
                f"part{part_id}.status": const.RegistrationPartStati,
                f"part{part_id}.lodgement_id": Optional[vtypes.ID],
                f"part{part_id}.is_camping_mat": bool
            })
        track_params: vtypes.TypeMapping = {}
        for track_id, track in tracks.items():
            track_params.update({  # type: ignore
                f"track{track_id}.{key}": Optional[vtypes.ID]
                for key in ("course_id", "course_instructor")
            })
            track_params.update({  # type: ignore
                f"track{track_id}.course_choice_{i}": Optional[vtypes.ID]
                for i in range(track['num_choices'])
            })
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in event['fields'].values()
            if field['association'] == const.FieldAssociations.registration
        }

        raw_reg = request_extractor(rs, filter_parameters(reg_params))
        if do_real_persona_id:
            raw_reg.update(request_extractor(rs, filter_parameters({
                "reg.real_persona_id": Optional[vtypes.CdedbID]  # type: ignore
            })))
        raw_parts = request_extractor(rs, filter_parameters(part_params))
        raw_tracks = request_extractor(rs, filter_parameters(track_params))
        raw_fields = request_extractor(rs, filter_parameters(field_params))

        # Build `parts`, `tracks` and `fields` dict
        new_parts = {
            part_id: {
                key: raw_parts["part{}.{}".format(part_id, key)]
                for key in ("status", "lodgement_id", "is_camping_mat")
                if "part{}.{}".format(part_id, key) in raw_parts
            }
            for part_id in event['parts']
        }
        new_tracks = {
            track_id: {
                key: raw_tracks["track{}.{}".format(track_id, key)]
                for key in ("course_id", "course_instructor")
                if "track{}.{}".format(track_id, key) in raw_tracks
            }
            for track_id in tracks
        }
        # Build course choices (but only if all choices are present)
        for track_id, track in tracks.items():
            if not all("track{}.course_choice_{}".format(track_id, i)
                       in raw_tracks
                       for i in range(track['num_choices'])):
                continue
            extractor = lambda i: raw_tracks["track{}.course_choice_{}".format(
                track_id, i)]
            choices_tuple = tuple(
                extractor(i)
                for i in range(track['num_choices']) if extractor(i))
            choices_set = set()
            own_course = new_tracks[track_id].get("course_instructor")
            for i_choice, choice in enumerate(choices_tuple):
                if own_course == choice:
                    rs.add_validation_error(
                        (f"track{track_id}.course_choice_{i_choice}",
                         ValueError(n_("Instructed course must not be chosen.")))
                    )
                if choice in choices_set:
                    rs.append_validation_error(
                        (f"track{track_id}.course_choice_{i_choice}",
                         ValueError(n_("Must choose different courses."))))
                else:
                    choices_set.add(choice)
            new_tracks[track_id]['choices'] = choices_tuple
        new_fields = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}

        # Put it all together
        registration = {
            key.split('.', 1)[1]: value for key, value in raw_reg.items()}
        registration['parts'] = new_parts
        registration['tracks'] = new_tracks
        if do_fields:
            registration['fields'] = new_fields
        return registration

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("skip", "change_note")
    def change_registration(self, rs: RequestState, event_id: int,
                            registration_id: int, skip: Collection[str],
                            change_note: Optional[str]) -> Response:
        """Make privileged changes to any information pertaining to a
        registration.

        Strictly speaking this makes a lot of the other functionality
        redundant (like managing the lodgement inhabitants), but it would be
        much more cumbersome to always use this interface.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], skip=skip,
            do_real_persona_id=self.conf["CDEDB_OFFLINE_DEPLOYMENT"])
        if rs.has_validation_errors():
            return self.change_registration_form(
                rs, event_id, registration_id, skip=(), internal=True,
                change_note=change_note)
        registration['id'] = registration_id
        code = self.eventproxy.set_registration(rs, registration, change_note)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_registration")

    @access("event")
    @event_guard(check_offline=True)
    def add_registration_form(self, rs: RequestState, event_id: int
                              ) -> Response:
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        registrations = self.eventproxy.list_registrations(rs, event_id)
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']]
            for track_id in tracks}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        defaults = {
            "part{}.status".format(part_id):
                const.RegistrationPartStati.participant
            for part_id in rs.ambience['event']['parts']
        }
        merge_dicts(rs.values, defaults)
        return self.render(rs, "registration/add_registration", {
            'courses': courses, 'course_choices': course_choices,
            'lodgements': lodgements,
            'registered_personas': registrations.values()})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def add_registration(self, rs: RequestState, event_id: int) -> Response:
        """Register a participant by an orga.

        This should not be used that often, since a registration should
        singnal legal consent which is not provided this way.
        """
        persona_id = unwrap(
            request_extractor(rs, {"persona.persona_id": vtypes.CdedbID}))
        if persona_id is not None:
            if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
                rs.append_validation_error(
                    ("persona.persona_id", ValueError(n_(
                        "This user does not exist or is archived."))))
            elif not self.coreproxy.verify_persona(rs, persona_id, {"event"}):
                rs.append_validation_error(
                    ("persona.persona_id", ValueError(n_(
                        "This user is not an event user."))))
        if (not rs.has_validation_errors()
                and self.eventproxy.list_registrations(rs, event_id, persona_id)):
            rs.append_validation_error(("persona.persona_id",
                                        ValueError(n_("Already registered."))))
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], do_fields=False,
            do_real_persona_id=self.conf["CDEDB_OFFLINE_DEPLOYMENT"])
        if (not rs.has_validation_errors()
                and not self.eventproxy.check_orga_addition_limit(
                    rs, event_id)):
            rs.append_validation_error(
                ("persona.persona_id",
                  ValueError(n_("Rate-limit reached."))))
        if rs.has_validation_errors():
            return self.add_registration_form(rs, event_id)

        registration['persona_id'] = persona_id
        registration['event_id'] = event_id
        new_id = self.eventproxy.create_registration(rs, registration)
        rs.notify_return_code(new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_registration(self, rs: RequestState, event_id: int,
                            registration_id: int, ack_delete: bool) -> Response:
        """Remove a registration."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        # maybe exclude some blockers
        db_id = cdedbid_filter(rs.ambience['registration']['persona_id'])
        self.eventproxy.event_keeper_commit(
            rs, event_id, f"Vor Löschen von Anmeldung {db_id}.", is_marker=True)
        code = self.eventproxy.delete_registration(
            rs, registration_id, {"registration_parts", "registration_tracks",
                                  "course_choices"})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/registration_query")

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("reg_ids", "change_note")
    def change_registrations_form(self, rs: RequestState, event_id: int,
                                  reg_ids: vtypes.IntCSVList,
                                  change_note: Optional[str]) -> Response:
        """Render form for changing multiple registrations."""

        # Redirect, if the reg_ids parameters is error-prone, to avoid backend
        # errors. Other errors are okay, since they can occur on submitting the
        # form
        if (rs.has_validation_errors()
                and all(field == 'reg_ids'
                        for field, _ in rs.retrieve_validation_errors())):
            return self.redirect(rs, 'event/registration_query',
                                 {'download': None, 'is_search': False})
        # Get information about registrations, courses and lodgements
        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, reg_ids)
        reg_vals = registrations.values()
        if not registrations:
            rs.notify("error", n_("No participants found to edit."))
            return self.redirect(rs, 'event/registration_query')

        personas = self.coreproxy.get_event_users(
            rs, [r['persona_id'] for r in reg_vals], event_id)
        for reg in reg_vals:
            reg['gender'] = personas[reg['persona_id']]['gender']
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['segments']]
            for track_id in tracks
        }
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)

        representative = next(iter(registrations.values()))

        # iterate registrations to check for differing values
        reg_data = {}
        for key, value in representative.items():
            if all(r[key] == value for r in reg_vals):
                reg_data[f'reg.{key}'] = value
                reg_data[f'enable_reg.{key}'] = True

        # do the same for registration parts', tracks' and field values
        for part_id, part in rs.ambience['event']['parts'].items():
            for key, value in representative['parts'][part_id].items():
                if all(r['parts'][part_id][key] == value for r in reg_vals):
                    reg_data[f'part{part_id}.{key}'] = value
                    reg_data[f'enable_part{part_id}.{key}'] = True
            for track_id in part['tracks']:
                for key, value in representative['tracks'][track_id].items():
                    if all(r['tracks'][track_id][key] == value for r in reg_vals):
                        reg_data[f'track{track_id}.{key}'] = value
                        reg_data[f'enable_track{track_id}.{key}'] = True

        for field_id, field in rs.ambience['event']['fields'].items():
            key = field['field_name']
            # Collect all existing values.
            present = [r['fields'][key] for r in reg_vals if key in r['fields']]
            # If no registration has a value, consider everything equal.
            if not present:
                reg_data[f'enable_fields.{key}'] = True
            # If all registrations have a value, we have to compare them
            elif len(present) == len(registrations):
                value = representative['fields'][key]
                if all(r['fields'][key] == value for r in reg_vals):
                    reg_data[f'enable_fields.{key}'] = True
                    reg_data[f'fields.{key}'] = value

        merge_dicts(rs.values, reg_data)

        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))

        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        return self.render(rs, "registration/change_registrations", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'course_choices': course_choices,
            'lodgements': lodgements, 'change_note': change_note})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("reg_ids", "change_note")
    def change_registrations(self, rs: RequestState, event_id: int,
                             reg_ids: vtypes.IntCSVList,
                             change_note: Optional[str]) -> Response:
        """Make privileged changes to any information pertaining to multiple
        registrations.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], check_enabled=True)
        if rs.has_validation_errors():
            return self.change_registrations_form(rs, event_id, reg_ids, change_note)

        code = 1
        self.logger.info(
            f"Updating registrations {reg_ids} with data {registration}")
        if change_note:
            change_note = "Multi-Edit: " + change_note
        else:
            change_note = "Multi-Edit"

        self.eventproxy.event_keeper_commit(rs, event_id, "Vor " + change_note)
        for reg_id in reg_ids:
            registration['id'] = reg_id
            code *= self.eventproxy.set_registration(rs, registration, change_note)
        self.eventproxy.event_keeper_commit(rs, event_id, "Nach " + change_note,
                                            is_marker=True)
        rs.notify_return_code(code)

        # redirect to query filtered by reg_ids
        scope = QueryScope.registration
        query = Query(
            scope, scope.get_spec(event=rs.ambience['event']),
            ("reg.id", "persona.given_names", "persona.family_name",
             "persona.username"),
            (("reg.id", QueryOperators.oneof, reg_ids),),
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        return self.redirect(rs, scope.get_target(), query.serialize())

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("part_ids")
    def checkin_form(self, rs: RequestState, event_id: int,
                     part_ids: Collection[int] = None) -> Response:
        """Render form."""
        if rs.has_validation_errors() or not part_ids:
            parts = rs.ambience['event']['parts']
        else:
            parts = {p_id: rs.ambience['event']['parts'][p_id] for p_id in part_ids}
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        there = lambda registration, part_id: const.RegistrationPartStati(
            registration['parts'][part_id]['status']).is_present()
        registrations = {
            k: v for k, v in registrations.items()
            if (not v['checkin'] and any(there(v, id) for id in parts))}
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
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
        checkin_fields = {
            field_id: f for field_id, f in rs.ambience['event']['fields'].items()
            if f['checkin'] and f['association'] == const.FieldAssociations.registration
        }
        return self.render(rs, "registration/checkin", {
            'registrations': registrations, 'personas': personas,
            'lodgements': lodgements, 'checkin_fields': checkin_fields,
            'part_ids': part_ids
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("registration_id", "part_ids")
    def checkin(self, rs: RequestState, event_id: int, registration_id: vtypes.ID,
                part_ids: Collection[int] = None) -> Response:
        """Check a participant in."""
        if rs.has_validation_errors():
            return self.checkin_form(rs, event_id)
        registration = self.eventproxy.get_registration(rs, registration_id)
        if registration['event_id'] != event_id:
            raise werkzeug.exceptions.NotFound(n_("Wrong associated event."))
        if registration['checkin']:
            rs.notify("warning", n_("Already checked in."))
            return self.checkin_form(rs, event_id)

        new_reg = {
            'id': registration_id,
            'checkin': now(),
        }
        code = self.eventproxy.set_registration(rs, new_reg, "Eingecheckt.")
        rs.notify_return_code(code)
        return self.redirect(rs, 'event/checkin', {'part_ids': part_ids})
