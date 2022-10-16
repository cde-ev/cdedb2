#!/usr/bin/env python3

"""
The `EventRegistrationMixin` subclasses the `EventBaseFrontend` and provides endpoints
for managing registrations both by orgas and participants.
"""

import csv
import datetime
import decimal
import io
import re
from collections import OrderedDict
from typing import Collection, Dict, List, Optional, Tuple

import segno.helpers
import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, RequestState, build_msg, determine_age_class,
    diacritic_patterns, get_hash, merge_dicts, now, unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.types import VALIDATOR_LOOKUP
from cdedb.frontend.common import (
    CustomCSVDialect, Headers, REQUESTdata, REQUESTfile, TransactionObserver, access,
    cdedbid_filter, check_validation_optional as check_optional, event_guard,
    inspect_validation as inspect, make_event_fee_reference, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend


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
                persona_amounts = {e['persona_id']: e['amount'] for e in data}
                personas = self.coreproxy.get_personas(rs, persona_amounts)
                subject = "Überweisung für {} eingetroffen".format(
                    rs.ambience['event']['title'])
                for persona in personas.values():
                    headers: Headers = {
                        'To': (persona['username'],),
                        'Subject': subject,
                    }
                    if rs.ambience['event']['orga_address']:
                        headers['Reply-To'] = rs.ambience['event']['orga_address']
                    self.do_mail(rs, "transfer_received", headers, {
                        'persona': persona, 'amount': persona_amounts[persona['id']]})
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

    def get_course_choice_params(self, rs: RequestState, event_id: int) -> CdEDBObject:
        """Helper to gather all info needed for course choice forms.

        The return can be unpacked and passed to the template directly.
        """
        event = rs.ambience['event']
        tracks = event['tracks']
        track_groups = event['track_groups']

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        courses_per_track = self.eventproxy.get_course_segments_per_track(
            rs, event_id, event['is_course_state_visible'])
        courses_per_track_group = self.eventproxy.get_course_segments_per_track_group(
            rs, event_id, event['is_course_state_visible'])
        reference_tracks = {}
        simple_tracks = set(tracks)
        track_group_map = {track_id: None for track_id in tracks}
        sync_track_groups = {tg_id: tg for tg_id, tg in track_groups.items()
                             if tg['constraint_type'].is_sync()}
        ccos_per_part: Dict[int, List[str]] = {
            part_id: [] for part_id in event['parts']}
        for track_group_id, track_group in sync_track_groups.items():
            simple_tracks.difference_update(track_group['track_ids'])
            track_group_map.update(
                {track_id: track_group_id for track_id in track_group['track_ids']})
            for track_id in track_group['track_ids']:
                ccos_per_part[tracks[track_id]['part_id']].append(
                    f"group-{track_group_id}")
                reference_tracks[track_group_id] = tracks[track_id]
        for track_id in simple_tracks:
            ccos_per_part[tracks[track_id]['part_id']].append(f"{track_id}")
        choice_objects = [t for t_id, t in tracks.items() if t_id in simple_tracks] + [
            tg for tg in track_groups.values() if tg['constraint_type'].is_sync()]
        choice_objects = xsorted(choice_objects, key=EntitySorter.course_choice_object)
        return {
            'courses': courses, 'courses_per_track': courses_per_track,
            'courses_per_track_group': courses_per_track_group,
            'reference_tracks': reference_tracks, 'simple_tracks': simple_tracks,
            'choice_objects': choice_objects, 'sync_track_groups': sync_track_groups,
            'track_group_map': track_group_map, 'ccos_per_part': ccos_per_part,
        }

    @access("event")
    @REQUESTdata("preview")
    def register_form(self, rs: RequestState, event_id: int,
                      preview: bool = False) -> Response:
        """Render form."""
        event = rs.ambience['event']
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(persona['birthday'], event['begin'])
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
                raise werkzeug.exceptions.Forbidden(n_("Must be Orga to use preview."))
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        # by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', event['parts'])

        course_choice_params = self.get_course_choice_params(rs, event_id)

        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "registration/register", {
            'persona': persona, 'age': age, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'preview': preview,
            **course_choice_params,
        })

    def new_process_registration_input(
            self, rs: RequestState, orga_input: bool, parts: CdEDBObjectMap = None,
            skip: Collection[str] = (), check_enabled: bool = False,
    ) -> CdEDBObject:

        def filter_params(params: vtypes.TypeMapping) -> vtypes.TypeMapping:
            """Helper to filter out params that are skipped or not enabled."""
            params = {key: kind for key, kind in params.items() if key not in skip}
            if not check_enabled:
                return params
            enable_params = {f"enable_{key}": bool for key in params}
            enable = request_extractor(rs, enable_params)
            return {
                key: kind for key, kind in params.items() if enable[f"enable_{key}"]}

        event = rs.ambience['event']
        tracks = event['tracks']
        track_groups = event['track_groups']
        course_choice_params = self.get_course_choice_params(rs, event['id'])
        simple_tracks = course_choice_params['simple_tracks']
        sync_track_groups = course_choice_params['sync_track_groups']
        reference_tracks = course_choice_params['reference_tracks']
        track_group_map = course_choice_params['track_group_map']

        # Top-level registration data.
        standard_params: vtypes.TypeMapping = {
            "reg.list_consent": bool,
            "reg.mixed_lodging": bool,
            "reg.notes": Optional[str],  # type: ignore[dict-item]
        }
        if orga_input:
            standard_params.update({
                "reg.amount_paid": vtypes.NonNegativeDecimal,
                "reg.checkin": bool,
                "reg.orga_notes": Optional[str],  # type: ignore[dict-item]
                "reg.parental_agreement": bool,
                "reg.payment": Optional[datetime.date],  # type: ignore[dict-item]
            })
            if self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                standard_params.update({
                    "reg.real_persona_id": Optional[vtypes.ID]  # type: ignore[dict-item]
                })
        standard_params = filter_params(standard_params)
        registration = {
            key.removeprefix("reg."): val
            for key, val in request_extractor(rs, standard_params).items()
        }

        # Part specific data:
        if orga_input:
            part_params: vtypes.TypeMapping = {}
            for part_id in event['parts']:
                part_params.update({
                    f"part{part_id}.status": const.RegistrationPartStati,
                    f"part{part_id}.lodgement_id": Optional[vtypes.ID],  # type: ignore[dict-item]
                    f"part{part_id}.is_camping_mat": bool,
                })
            part_params = filter_params(part_params)
            raw_parts = request_extractor(rs, part_params)
            registration['parts'] = {
                part_id: {
                    key: raw_parts[raw_key]
                    for key in ("status", "lodgement_id", "is_camping_mat")
                    if (raw_key := f"part{part_id}.{key}") in raw_parts
                }
                for part_id in event['parts']
            }
            part_ids = {
                part_id for part_id in registration['parts']
                if (status := registration['parts'][part_id].get('status'))
                   and status.is_involved()
            }
        elif parts is None:
            # If no parts were given, this must be a new registration.
            rps = const.RegistrationPartStati
            part_ids = set(request_extractor(rs, {"parts": Collection[int]})["parts"])
            registration['parts'] = {
                part_id: {
                    "status": rps.applied if part_id in part_ids else rps.not_applied
                }
                for part_id in event['parts']
            }
        else:
            # This must be a user amending their own registration.
            part_ids = {
                part_id for part_id in parts
                if parts[part_id]['status'].is_involved()
            }

        # Track specific data:
        # First for simple tracks.
        track_params: vtypes.TypeMapping = {}
        if orga_input:
            track_params.update({
                f"track{track_id}.course_id": Optional[vtypes.ID]  # type: ignore[misc]
                for track_id in tracks
            })
        track_params.update({
            f"track{track_id}.course_choice_{i}": Optional[vtypes.ID]  # type: ignore[misc]
            for track_id in simple_tracks
            for i in range(tracks[track_id]['num_choices'])
        })
        track_params.update({
            f"track{track_id}.course_instructor": Optional[vtypes.ID]  # type: ignore[misc]
            for track_id in simple_tracks
        })
        track_params = filter_params(track_params)
        raw_tracks = request_extractor(rs, track_params)

        # Now for synced tracks.
        num_choices = lambda g_id: tracks[reference_tracks[g_id]['id']]['num_choices']
        synced_params: vtypes.TypeMapping = {
            f"group{group_id}.course_choice_{i}": Optional[vtypes.ID]  # type: ignore[misc]
            for group_id in sync_track_groups for i in range(num_choices(group_id))
        }
        synced_params.update({
            f"group{group_id}.course_instructor": Optional[vtypes.ID]  # type: ignore[misc]
            for group_id in sync_track_groups
        })
        synced_params = filter_params(synced_params)
        synced_data = request_extractor(rs, synced_params)

        for group_id in sync_track_groups:
            for track_id in track_groups[group_id]['track_ids']:
                # Be careful not to override non-present keys here, due to multiedit.
                for i in range(num_choices(group_id)):
                    key = f"group{group_id}.course_choice_{i}"
                    if key in synced_data:
                        raw_tracks[f"track{track_id}.course_choice_{i}"] = synced_data[
                            key]
                key = f"group{group_id}.course_instructor"
                if key in synced_data:
                    raw_tracks[f"track{track_id}.course_instructor"] = synced_data[key]

        # Combine all regular track data.
        reg_tracks = {
            track_id: {
                key: raw_tracks[raw_key]
                for key in ("course_id", "course_instructor")
                if (raw_key := f"track{track_id}.{key}") in raw_tracks
            }
            for track_id in tracks
        }

        # Now retrieve _and validate_ course choices.
        aux = self.eventproxy.get_course_choice_validation_aux(
            rs, event['id'], registration_id=None, part_ids=part_ids)
        for track_id, track in tracks.items():
            # If not all keys are present we are probably in the multiedit.
            if not all(
                f"track{track_id}.course_choice_{x}" in raw_tracks
                for x in range(track['num_choices'])
            ):
                # In which case we don't want to touch the course choices.
                continue
            choice = lambda x: raw_tracks.get(f"track{track_id}.course_choice_{x}")
            choice_key = lambda x: (
                f"group{group_id}.course_choice_{x}"
                if (group_id := track_group_map[track_id])
                else f"track{track_id}.course_choice_{x}"
            )
            choices_list = [
                c_id for i in range(track['num_choices']) if (c_id := choice(i))]  # pylint: disable=superfluous-parens,line-too-long # seems like a bug.
            instructed_course = reg_tracks[track_id].get("course_instructor")
            for rank, course_id in enumerate(choices_list):
                # Check for choosing instructed course.
                if course_id == instructed_course:
                    rs.add_validation_error((
                        choice_key(rank),
                        ValueError(n_("Instructed course must not be chosen."))
                        if orga_input else
                        ValueError(n_("You may not choose your own course."))
                    ))
                # Check for duplicated course choices.
                for x in range(rank):
                    if course_id == choice(x):
                        rs.add_validation_error((
                            choice_key(rank),
                             ValueError(n_(
                                 "You cannot have the same course as %(i)s."
                                 " and %(j)s. choice"),
                                 {'i': x + 1, 'j': rank + 1})
                        ))
                # Check that the course choice is allowed for this track.
                if not self.eventproxy.validate_single_course_choice(
                        rs, course_id, track_id, aux):
                    rs.add_validation_error((
                        choice_key(rank),
                        ValueError(n_("Invalid course choice for this track."))
                    ))

            # Check for unfilled mandatory course choices, but only if not orga.
            if (len(choices_list) < track['min_choices']
                    and track['part_id'] in part_ids and not orga_input):
                rs.add_validation_errors(
                    (choice_key(x), ValueError(n_(
                        "You must choose at least %(min_choices)s courses."),
                        {'min_choices': track['min_choices']}))
                    for x in range(len(choices_list), track['min_choices'])
                )
            reg_tracks[track_id]["choices"] = choices_list
        registration['tracks'] = reg_tracks

        # Custom data field data:
        if orga_input:
            field_params: vtypes.TypeMapping = {
                f"fields.{field['field_name']}": Optional[  # type: ignore[misc]
                    VALIDATOR_LOOKUP[field['kind'].name]]  # noqa: F821  # seems like a bug.
                for field in event['fields'].values()
                if field['association'] == const.FieldAssociations.registration
            }
            field_params = filter_params(field_params)
            raw_fields = request_extractor(rs, field_params)
            registration['fields'] = {
                field['field_name']: raw_fields[raw_key]
                for field in event['fields'].values()
                if (raw_key := f"fields.{field['field_name']}") in raw_fields
            }
        else:
            field_params = self._questionnaire_params(
                rs, const.QuestionnaireUsages.registration)
            registration['fields'] = {
                key.removeprefix("fields."): val
                for key, val in request_extractor(rs, field_params).items()
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
        registration = self.new_process_registration_input(
            rs, orga_input=False)
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
        payment_data = self._get_payment_data(rs, event_id)
        if not payment_data:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        persona = payment_data.pop('persona')
        registration = payment_data.pop('registration')

        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
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
        course_choice_parameters = self.get_course_choice_params(rs, event_id)

        status = lambda track: registration['parts'][track['part_id']]['status']
        involved_tracks = {
            track_id for track_id, track in rs.ambience['event']['tracks'].items()
            if const.RegistrationPartStati(status(track)).is_involved()}

        return self.render(rs, "registration/registration_status", {
            'registration': registration, 'age': age,
            'reg_questionnaire': reg_questionnaire,
            'waitlist_position': waitlist_position, 'involved_tracks': involved_tracks,
            **payment_data, **course_choice_parameters,
        })

    @staticmethod
    def _prepare_registration_values(event: CdEDBObject,
                                     registration: CdEDBObject) -> CdEDBObject:
        values: CdEDBObject = {
            f"reg.{key}": val
            for key, val in registration.items()
            if key not in ("parts", "tracks", "fields")
        }
        for part_id, reg_part in registration['parts'].items():
            values |= {
                f"part{part_id}.{key}": value
                for key, value in reg_part.items()}
        for track_id, reg_track in registration['tracks'].items():
            values |= {
                f"track{track_id}.{key}": value
                for key, value in reg_track.items()
                if key != "choices"
            }
            values |= {
                f"track{track_id}.course_choice_{i}": choice
                for i, choice in enumerate(reg_track['choices'])
            }
            for tg_id, tg in event['tracks'][track_id]['track_groups'].items():
                if not tg['constraint_type'].is_sync():
                    continue
                values |= {
                    f"group{tg_id}.{key}": value
                    for key, value in reg_track.items()
                    if key != "choices"
                }
                values |= {
                    f"group{tg_id}.course_choice_{i}": choice
                    for i, choice in enumerate(reg_track['choices'])
                }
        values |= {
            f"fields.{key}": val
            for key, val in registration['fields'].items()
        }
        return values

    @access("event")
    def amend_registration_form(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys() or None)
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
        values = self._prepare_registration_values(event, registration)
        merge_dicts(rs.values, values)

        stat = lambda track: registration['parts'][track['part_id']]['status']
        involved_tracks = {
            track_id for track_id, track in tracks.items()
            if const.RegistrationPartStati(stat(track)).is_involved()}

        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        course_choice_params = self.get_course_choice_params(rs, event_id)
        return self.render(rs, "registration/amend_registration", {
            'age': age, 'involved_tracks': involved_tracks,
            'reg_questionnaire': reg_questionnaire,
            **course_choice_params,
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
        stored = self.eventproxy.get_registration(rs, registration_id)
        registration = self.new_process_registration_input(
            rs, orga_input=False, parts=stored['parts'])
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
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=persona['id'])
        constraint_violations = self.get_constraint_violations(
            rs, event_id, registration_id=registration_id, course_id=-1)
        course_choice_parameters = self.get_course_choice_params(rs, event_id)
        return self.render(rs, "registration/show_registration", {
            'persona': persona, 'age': age,
            'lodgements': lodgements, 'meta_info': meta_info, 'fee': fee,
            'reference': reference, 'waitlist_position': waitlist_position,
            'mep_violations': constraint_violations['mep_violations'],
            'ccs_violations': constraint_violations['ccs_violations'],
            'violation_severity': constraint_violations['max_severity'],
            **course_choice_parameters,
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
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_event_user(
            rs, registration['persona_id'], event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        course_choice_params = self.get_course_choice_params(rs, event_id)

        values = self._prepare_registration_values(rs.ambience['event'], registration)
        # Fix formatting of ID
        values['reg.real_persona_id'] = cdedbid_filter(registration['real_persona_id'])
        merge_dicts(rs.values, values)
        return self.render(rs, "registration/change_registration", {
            'persona': persona, 'lodgements': lodgements,
            'skip': skip or [], 'change_note': change_note,
            **course_choice_params,
        })

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
        registration = self.new_process_registration_input(
            rs, orga_input=True, skip=skip)
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
        registrations = self.eventproxy.list_registrations(rs, event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        defaults = {
            "part{}.status".format(part_id):
                const.RegistrationPartStati.participant
            for part_id in rs.ambience['event']['parts']
        }
        merge_dicts(rs.values, defaults)
        course_choice_params = self.get_course_choice_params(rs, event_id)
        return self.render(rs, "registration/add_registration", {
            'lodgements': lodgements, 'registered_personas': registrations.values(),
            **course_choice_params,
        })

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
        registration = self.new_process_registration_input(rs, orga_input=True)
        if (not rs.has_validation_errors()
                and not self.eventproxy.check_orga_addition_limit(rs, event_id)):
            rs.append_validation_error(
                ("persona.persona_id", ValueError(n_("Rate-limit reached."))))
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
        pre_msg = f"Snapshot vor Löschen von Anmeldung {db_id}."
        post_msg = f"Lösche Anmeldung {db_id}."
        self.eventproxy.event_keeper_commit(rs, event_id, pre_msg)
        code = self.eventproxy.delete_registration(
            rs, registration_id, {"registration_parts", "registration_tracks",
                                  "course_choices"})
        self.eventproxy.event_keeper_commit(rs, event_id, post_msg, after_change=True)
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
        registrations = self.eventproxy.get_registrations(rs, reg_ids)
        reg_vals = registrations.values()
        if not registrations:
            rs.notify("error", n_("No participants found to edit."))
            return self.redirect(rs, 'event/registration_query')

        personas = self.coreproxy.get_event_users(
            rs, [r['persona_id'] for r in reg_vals], event_id)
        for reg in reg_vals:
            reg['gender'] = personas[reg['persona_id']]['gender']
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)

        representative = next(iter(registrations.values()))

        course_choice_params = self.get_course_choice_params(rs, event_id)

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
                    # Do no include course choices in multiedit.
                    if key == 'choices':
                        continue
                    if all(r['tracks'][track_id][key] == value for r in reg_vals):
                        reg_data[f'track{track_id}.{key}'] = value
                        reg_data[f'enable_track{track_id}.{key}'] = True

        for tg_id, tg in rs.ambience['event']['track_groups'].items():
            if not tg['constraint_type'].is_sync():
                continue
            repr_track_id = next(iter(tg['track_ids']))
            for key, value in representative['tracks'][repr_track_id].items():
                if key == 'choices':
                    continue
                if all(
                    r['tracks'][track_id][key] == value
                    for track_id in tg['track_ids'] for r in reg_vals
                ):
                    reg_data[f'group{tg_id}.{key}'] = value
                    reg_data[f'enable_group{tg_id}.{key}'] = True

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
            'lodgements': lodgements, 'change_note': change_note,
            **course_choice_params,
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("reg_ids", "change_note")
    def change_registrations(self, rs: RequestState, event_id: int,
                             reg_ids: vtypes.IntCSVList,
                             change_note: Optional[str]) -> Response:
        """Make privileged changes to any information pertaining to multiple
        registrations.
        """
        registration = self.new_process_registration_input(
            rs, orga_input=True, check_enabled=True)
        if rs.has_validation_errors():
            return self.change_registrations_form(rs, event_id, reg_ids, change_note)

        code = 1
        self.logger.info(
            f"Updating registrations {reg_ids} with data {registration}")
        msg1 = build_msg("Snapshot vor Bearbeitung mehrerer Anmeldungen", change_note)
        msg2 = build_msg("Bearbeite mehrere Anmeldungen", change_note)
        change_note = build_msg("Multi-Edit", change_note)

        self.eventproxy.event_keeper_commit(rs, event_id, msg1)
        for reg_id in reg_ids:
            registration['id'] = reg_id
            code *= self.eventproxy.set_registration(rs, registration, change_note)
        self.eventproxy.event_keeper_commit(rs, event_id, msg2, after_change=True)
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
        return self.redirect(rs, scope.get_target(), query.serialize_to_url())

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

    def _get_payment_data(self, rs: RequestState, event_id: int
                          ) -> Optional[CdEDBObject]:
        reg_list = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not reg_list:
            return None
        registration_id = unwrap(reg_list.keys())
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)

        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        to_pay = fee - registration['amount_paid']

        return {
            'registration': registration, 'persona': persona,
            'meta_info': meta_info, 'reference': reference, 'to_pay': to_pay,
            'iban': rs.ambience['event']['iban'], 'fee': fee,
            'semester_fee': self.conf['MEMBERSHIP_FEE']
        }

    @access("event")
    def registration_fee_qr(self, rs: RequestState, event_id: int) -> Response:
        payment_data = self._get_payment_data(rs, event_id)
        if not payment_data:
            return self.redirect(rs, "event/show_event")
        qrcode = self._registration_fee_qr(payment_data)
        if not qrcode:
            return self.redirect(rs, "event/show_event")

        buffer = io.BytesIO()
        qrcode.save(buffer, kind='svg', scale=4)

        return self.send_file(rs, afile=buffer, mimetype="image/svg+xml")

    @staticmethod
    def _registration_fee_qr_data(payment_data: CdEDBObject) -> Optional[CdEDBObject]:
        if not payment_data['iban']:
            return None
        # Ensure that the "free-"text parts are not too long. The exact size is limited
        # by third parties.
        return {
            'name': payment_data['meta_info']['CdE_Konto_Inhaber'][:70],
            'text': payment_data['reference'][:140],
            'amount': payment_data['to_pay'],
            'iban': payment_data['iban'],
            'bic': payment_data['meta_info']['CdE_Konto_BIC'],
        }

    def _registration_fee_qr(self, payment_data: CdEDBObject) -> Optional[segno.QRCode]:
        data = self._registration_fee_qr_data(payment_data)
        if not data:
            return None
        return segno.helpers.make_epc_qr(**data)
