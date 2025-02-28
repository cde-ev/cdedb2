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
from collections.abc import Collection
from typing import Optional, cast

import segno.helpers
import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    Accounts,
    CdEDBObject,
    CdEDBObjectMap,
    RequestState,
    build_msg,
    determine_age_class,
    diacritic_patterns,
    get_hash,
    json_serialize,
    make_persona_name,
    merge_dicts,
    now,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.privileges import EventPrivileges
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.validate import FIELD_DATATYPE_VALIDATORS
from cdedb.filter import date_filter, money_filter
from cdedb.frontend.common import (
    CustomCSVDialect,
    Headers,
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    TransactionObserver,
    access,
    cdedbid_filter,
    check_validation as check,
    check_validation_optional as check_optional,
    event_guard,
    inspect_validation as inspect,
    make_event_fee_reference,
    periodic,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend


class EventRegistrationMixin(EventBaseFrontend):
    @access("finance_admin")
    def batch_fees_form(self, rs: RequestState, event_id: int,
                        data: Optional[Collection[CdEDBObject]] = None,
                        csvfields: Optional[Collection[str]] = None,
                        saldo: Optional[decimal.Decimal] = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        # manual check for offline log, since we can not use event_guard here
        is_locked = self.eventproxy.is_offline_locked(rs, event_id=event_id)
        if is_locked != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            raise werkzeug.exceptions.Forbidden(
                n_("This event is locked for offline usage."))
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['persona_id'] = csv_position.pop('id', -1)
        return self.render(rs, "registration/batch_fees",
                           {'data': data, 'csvfields': csv_position,
                            'saldo': saldo})

    def _examine_fee(self, rs: RequestState, datum: CdEDBObject,
                     expected_fees: dict[int, decimal.Decimal],
                     seen_reg_ids: set[int],
                     ) -> CdEDBObject:
        """Check one line specifying a paid fee. Uninlined from `batch_fees`.

        We test for fitness of the data itself.

        :note: This modifies the parameters `expected_fees` and `seen_reg_ids`.

        :returns: The processed input datum.
        """
        event = rs.ambience['event']
        warnings = []
        infos = []
        # Allow an amount of zero to allow non-modification of amount_paid.
        amount: Optional[decimal.Decimal]
        amount, problems = inspect(decimal.Decimal,
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
                    rs, event.id, persona_id).keys()
                if registration_ids:
                    registration_id = unwrap(registration_ids)
                    if registration_id in seen_reg_ids:
                        warnings.append(
                            ('persona_id',
                             ValueError(n_("Multiple transfers for this user."))))
                    seen_reg_ids.add(registration_id)
                    registration = self.eventproxy.get_registration(
                        rs, registration_id)
                    if not amount:
                        problems.append(
                            ('amount', ValueError(n_("Must not be zero."))))
                    else:
                        amount_paid = registration['amount_paid']
                        total = amount + amount_paid
                        fee = expected_fees[registration_id]
                        params = {
                            'total': money_filter(total, lang=rs.lang),
                            'expected': money_filter(fee, lang=rs.lang),
                        }
                        if total < fee:
                            infos.append((
                                'amount',
                                ValueError(
                                    n_("Not enough money. %(total)s < %(expected)s"),
                                    params,
                                ),
                            ))
                        elif total > fee:
                            infos.append((
                                'amount',
                                ValueError(
                                    n_("Too much money. %(total)s > %(expected)s"),
                                    params,
                                ),
                            ))
                        expected_fees[registration_id] -= amount
                else:
                    problems.append(('persona_id',
                                     ValueError(n_("No registration found."))))

                if family_name is not None and not re.search(
                    diacritic_patterns(re.escape(family_name)),
                    persona['family_name'],
                    flags=re.IGNORECASE,
                ):
                    warnings.append(('family_name', ValueError(
                        n_("Family name doesn’t match."))))

                if given_names is not None and not re.search(
                    diacritic_patterns(re.escape(given_names)),
                    persona['given_names'],
                    flags=re.IGNORECASE,
                ):
                    warnings.append(('given_names', ValueError(
                        n_("Given names don’t match."))))
        datum.update({
            'persona_id': persona_id,
            'registration_id': registration_id,
            'date': date,
            'amount': amount,
            'warnings': warnings,
            'problems': problems,
            'infos': infos,
        })
        return datum

    def book_fees(self, rs: RequestState,
                  data: Collection[CdEDBObject], send_notifications: bool = False,
                  ) -> tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        relevant_keys = {'registration_id', 'date', 'amount'}
        relevant_data = [{k: v for k, v in item.items() if k in relevant_keys}
                         for item in data]
        with TransactionObserver(rs, self, "book_fees"):
            success, number = self.eventproxy.book_fees(
                rs, rs.ambience['event'].id, relevant_data)
            if success and send_notifications:
                persona_amounts = {e['persona_id']: e['amount'] for e in data}
                personas = self.coreproxy.get_personas(rs, persona_amounts)
                subject = f"Überweisung für {rs.ambience['event'].title} eingetroffen"
                for persona in personas.values():
                    headers: Headers = {
                        'To': (persona['username'],),
                        'Subject': subject,
                    }
                    if rs.ambience['event'].orga_address:
                        headers['Reply-To'] = rs.ambience['event'].orga_address
                    self.do_mail(rs, "transfer_received", headers, {
                        'persona': persona, 'amount': persona_amounts[persona['id']]})
            return success, number

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("fee_data_file")
    @REQUESTdata("force", "fee_data", "checksum", "send_notifications")
    def batch_fees(self, rs: RequestState, event_id: int, force: bool,
                   fee_data: Optional[str],
                   fee_data_file: Optional[werkzeug.datastructures.FileStorage],
                   checksum: Optional[str], send_notifications: bool) -> Response:
        """Allow finance admins to add payment information of participants.

        This is the only entry point for those information.
        """
        # manual check for offline log, since we can not use event_guard here
        is_locked = self.eventproxy.is_offline_locked(rs, event_id=event_id)
        if is_locked != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            raise werkzeug.exceptions.Forbidden(
                n_("This event is locked for offline usage."))

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
        seen_reg_ids: set[int] = set()
        for lineno, raw_entry in enumerate(reader):
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno}
            data.append(self._examine_fee(
                rs, dataset, expected_fees, seen_reg_ids=seen_reg_ids))
        open_issues = any(e['problems'] for e in data)
        saldo: decimal.Decimal = sum(
            (e['amount'] for e in data if e['amount']), decimal.Decimal("0.00"))
        if not force:
            open_issues = open_issues or any(e['warnings'] for e in data)
        if rs.has_validation_errors() or not data or open_issues:
            return self.batch_fees_form(
                rs, event_id, data=data, csvfields=fields, saldo=saldo)

        current_checksum = get_hash(fee_data.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.batch_fees_form(
                rs, event_id, data=data, csvfields=fields, saldo=saldo)

        # Here validation is finished
        success, num = self.book_fees(rs, data, send_notifications)
        if success:
            rs.notify("success", n_("Committed %(num)s fees."), {'num': num})
            if send_notifications and (
                    orga_address := rs.ambience['event'].orga_address):
                headers: Headers = {
                    'To': (orga_address,),
                    'Reply-To': self.conf["FINANCE_ADMIN_ADDRESS"],
                    'Subject': "Neue Überweisungen für Eure Veranstaltung",
                    'Prefix': "",
                }
                self.do_mail(rs, "transfers_booked", headers, {'num': num})
            return self.redirect(rs, "event/show_event")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line %(num)s."),
                          {'num': num + 1})
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

    def get_course_choice_params(self, rs: RequestState, event_id: int,
                                 orga: bool = True) -> CdEDBObject:
        """Helper to gather all info needed for course choice forms.

        The return can be unpacked and passed to the template directly.

        :param orga: Whether we are retrieving input from an orga form like
            change_registration or a participant form, like register.
        """
        event = rs.ambience['event']
        tracks = event.tracks
        track_groups = event.track_groups
        ccs = const.CourseTrackGroupType.course_choice_sync

        involved_parts = None
        registration_ids = self.eventproxy.list_registrations(
            rs, event_id, rs.user.persona_id)
        if registration_ids and not orga:
            reg = self.eventproxy.get_registration(rs, unwrap(registration_ids.keys()))
            involved_parts = {part_id for part_id, rpart in reg['parts'].items()
                              if rpart['status'].is_involved()}

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        courses_per_track = self.eventproxy.get_course_segments_per_track(
            rs, event_id, event.is_course_state_visible and not orga)
        all_courses_per_track = (
            self.eventproxy.get_course_segments_per_track(rs, event_id))
        courses_per_track_group = self.eventproxy.get_course_segments_per_track_group(
            rs, event_id, event.is_course_state_visible and not orga, involved_parts)
        all_courses_per_track_group = (
            self.eventproxy.get_course_segments_per_track_group(rs, event_id))
        simple_tracks = set(tracks)
        track_group_map: dict[int, Optional[int]] = {
            track_id: None for track_id in tracks}
        sync_track_groups = {
            tg_id: tg for tg_id, tg in track_groups.items()
            if isinstance(tg, models.SyncTrackGroup)
        }
        ccos_per_part: dict[int, list[str]] = {part_id: [] for part_id in event.parts}
        for track_group_id, track_group in sync_track_groups.items():
            simple_tracks.difference_update(track_group.tracks)
            track_group_map.update(
                {track_id: track_group_id for track_id in track_group.tracks})
            for track in track_group.tracks.values():
                ccos_per_part[track.part_id].append(f"group-{track_group_id}")
        for track_id in simple_tracks:
            ccos_per_part[tracks[track_id].part_id].append(f"{track_id}")
        choice_objects = [t for t_id, t in tracks.items() if t_id in simple_tracks] + [
            tg for tg in track_groups.values() if tg.constraint_type.is_sync()]
        choice_objects = xsorted(choice_objects)

        # For every course and track, determine all tracks that allow you to choose
        #  this course in this track.
        parts_per_track_group_per_course = {
            course_id: {
                tg_id: {
                    event.tracks[t_id].part_id for t_id in
                    (set(tg.tracks) & course['segments'])
                }
                for tg_id, tg in event.track_groups.items()
                if tg.constraint_type == ccs
            }
            for course_id, course in courses.items()
        }

        return {
            'courses': courses, 'courses_per_track': courses_per_track,
            'all_courses_per_track': all_courses_per_track,
            'courses_per_track_group': courses_per_track_group,
            'all_courses_per_track_group': all_courses_per_track_group,
            'simple_tracks': simple_tracks,
            'choice_objects': choice_objects, 'sync_track_groups': sync_track_groups,
            'track_group_map': track_group_map, 'ccos_per_part': ccos_per_part,
            'parts_per_track_group_per_course': parts_per_track_group_per_course,
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
        age = determine_age_class(persona['birthday'], event.begin)
        rs.ignore_validation_errors()
        if not preview:
            if rs.user.persona_id in registrations.values():
                rs.notify("info", n_("Already registered."))
                return self.redirect(rs, "event/registration_status")
            if not event.is_open:
                rs.notify("warning", n_("Registration not open."))
                return self.redirect(rs, "event/show_event")
            if self.is_locked(event):
                rs.notify("warning", n_("Event locked."))
                return self.redirect(rs, "event/show_event")
            if rs.ambience['event'].is_archived:
                rs.notify("error", n_("Event is already archived."))
                return self.redirect(rs, "event/show_event")
            if not self.eventproxy.has_minor_form(rs, event_id) and age.is_minor():
                rs.notify("info", n_("No minors may register. "
                                     "Please contact the Orgateam."))
                return self.redirect(rs, "event/show_event")
        elif not self.is_privileged(rs, EventPrivileges.basic_read):
            raise werkzeug.exceptions.Forbidden(n_("Must be Orga to use preview."))
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        # by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', event.parts)
        # display the date for part choices
        part_options = None
        if len(event.parts) > 1:
            part_options = [
                # narrow non-breaking space below, the string is purely user-facing
                (part.id,
                 f"{part.title}"
                 f" ({date_filter(part.part_begin, lang=rs.lang)}\u202f–\u202f"
                 f"{date_filter(part.part_end, lang=rs.lang)})")
                for part in xsorted(event.parts.values())]

        course_choice_params = self.get_course_choice_params(rs, event_id, orga=False)

        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "registration/register", {
            'persona': persona, 'age': age, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'preview': preview,
            'part_options': part_options, **course_choice_params,
        })

    def _calculate_single_fee(
            self, rs: RequestState, reg: CdEDBObject, persona_id: int | None = None,
    ) -> decimal.Decimal:
        """Calculate the fee for one registration based on a (partial) registration."""
        if current := rs.ambience.get('registration'):
            registration = {
                **reg,
                'persona_id': current['persona_id'],
                'is_member': current['is_member'],
                'personalized_fees': current['personalized_fees'],
            }
        else:
            if not persona_id:
                raise ValueError
            registration = {
                **reg,
                'persona_id': persona_id,
                'is_member': self.coreproxy.get_persona(rs, persona_id)['is_member'],
                'personalized_fees': {},
            }
        return self.eventproxy._calculate_single_fee(
            rs, registration, event=rs.ambience['event'])

    @access("event")
    @REQUESTdata("persona_id", "part_ids", "field_ids", "is_member", "is_orga")
    def precompute_fee(self, rs: RequestState, event_id: int, persona_id: Optional[int],
                       part_ids: vtypes.IntCSVList, field_ids: vtypes.IntCSVList,
                       is_member: Optional[bool] = None, is_orga: Optional[bool] = None,
                       ) -> Response:
        """Compute the total fee for a user based on seleceted parts and bool fields.

        Note that this does not require an existing registration, so this can be used
        for a preview during registration.

        :returns: A dict with localized text to be used in the preview.
        """

        if self.is_privileged(rs, EventPrivileges.registrations_read):
            pass
        # Preview access for event helpers
        elif not persona_id and self.is_privileged(rs, EventPrivileges.basic_read):
            pass
        elif persona_id == rs.user.persona_id and (
                rs.ambience['event'].is_open
                or self.eventproxy.list_registrations(rs, event_id, persona_id)):
            pass
        else:
            return Response("{}", mimetype='application/json', status=403)
        if rs.has_validation_errors():
            return Response("{}", mimetype='application/json', status=400)

        field_params = {f"field.{field_id}": bool
                        for field_id in rs.ambience['event'].fields}
        field_values = request_extractor(rs, field_params, omit_missing=True)

        complex_fee = self.eventproxy.precompute_fee(
            rs, event_id, persona_id, part_ids, is_member, is_orga, field_values)

        msg = rs.gettext("Because you are not a CdE-Member, you will have to pay an"
                         " additional fee of %(additional_fee)s"
                         " (already included in the above figure).")
        nonmember_msg = msg % {
            'additional_fee': money_filter(
                complex_fee.nonmember_surcharge, lang=rs.lang) or "",
        }

        fee_breakdown_template = """
{%- import "web/event/generic.tmpl" as generic_event with context -%}
{{- generic_event.fee_breakdown_by_kind() -}}
"""
        fee_breakdown_html = self.jinja_env.from_string(fee_breakdown_template).render(
            complex_fee=complex_fee, gettext=rs.gettext, lang=rs.lang,
        )

        if complex_fee.is_complex():
            fee_preview = fee_breakdown_html
        else:
            fee_preview = money_filter(complex_fee.amount, lang=rs.lang) or ""

        ret = {
            'fee': fee_preview,
            'nonmember': nonmember_msg,
            'show_nonmember': bool(complex_fee.nonmember_surcharge),
            'active_fees': complex_fee.active_fees,
            'visual_debug': complex_fee.visual_debug,
        }
        return Response(json_serialize(ret), mimetype='application/json')

    def new_process_registration_input(
            self, rs: RequestState, orga_input: bool,
            parts: Optional[CdEDBObjectMap] = None, check_enabled: bool = False,
    ) -> CdEDBObject:
        """Helper to retrieve input data for e registration and convert it into a
        registration dict that can be used for `create_registration` or
        `set_registration`.

        :param orga_input: False if the form is filled in and submitted by a non-orga
            user. (Or an orga using the regular register form). There are more fields
            available to set for orgas and some slight semantic differences.
        :param parts: Only relevant for non-orga input. If None, the part information
            will be retrieved from the input (meaning this is a new registration
            being created). Otherwise the data from `get_registration()['parts']`.
        :param check_enabled: If True, only retrieve data for fields where a
            corresponding enable checkbox is selected. Only relevant for the multiedit.
        """

        def filter_params(params: vtypes.TypeMapping) -> vtypes.TypeMapping:
            """Helper to filter out params that are skipped or not enabled."""
            if not check_enabled:
                return params
            enable_params = {f"enable_{key}": bool for key in params}
            enable = request_extractor(rs, enable_params)
            return {
                key: kind for key, kind in params.items() if enable[f"enable_{key}"]}

        event = rs.ambience['event']
        tracks = event.tracks
        course_choice_params = self.get_course_choice_params(
            rs, event.id, orga=orga_input)
        simple_tracks = course_choice_params['simple_tracks']
        sync_track_groups = course_choice_params['sync_track_groups']
        track_group_map = course_choice_params['track_group_map']

        # Top-level registration data.
        standard_params: vtypes.TypeMapping = {
            "reg.list_consent": bool,
            "reg.mixed_lodging": bool,
            "reg.notes": Optional[str],  # type: ignore[dict-item]
        }
        if orga_input:
            standard_params.update({
                "reg.orga_notes": Optional[str],  # type: ignore[dict-item]
                "reg.parental_agreement": bool,
            })
            if self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                standard_params.update({
                    "reg.real_persona_id": Optional[vtypes.ID],  # type: ignore[dict-item]
                })
        standard_params = filter_params(standard_params)
        registration = {
            key.removeprefix("reg."): val
            for key, val in request_extractor(rs, standard_params).items()
        }

        # Part specific data:
        if orga_input:
            part_params: vtypes.TypeMapping = {}
            for part_id in event.parts:
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
                for part_id in event.parts
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
                    "status": rps.applied if part_id in part_ids else rps.not_applied,
                }
                for part_id in event.parts
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
            for i in range(tracks[track_id].num_choices)
        })
        track_params.update({
            f"track{track_id}.course_instructor": Optional[vtypes.ID]  # type: ignore[misc]
            for track_id in simple_tracks
        })
        track_params = filter_params(track_params)
        raw_tracks = request_extractor(rs, track_params)

        # Now for synced tracks.
        synced_params: vtypes.TypeMapping = {
            f"group{group.id}.course_choice_{i}": Optional[vtypes.ID]  # type: ignore[misc]
            for group in sync_track_groups.values() for i in range(group.num_choices)
        }
        synced_params.update({
            f"group{group_id}.course_instructor": Optional[vtypes.ID]  # type: ignore[misc]
            for group_id in sync_track_groups
        })
        synced_params = filter_params(synced_params)
        synced_data = request_extractor(rs, synced_params)

        for group_id, group in sync_track_groups.items():
            for track_id in group.tracks:
                # Be careful not to override non-present keys here, due to multiedit.
                for i in range(group.num_choices):
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
            rs, event.id, registration_id=None, part_ids=part_ids,
            orga_input=orga_input)
        for track_id, track in tracks.items():
            # If not all keys are present we are probably in the multiedit.
            if not all(
                f"track{track_id}.course_choice_{x}" in raw_tracks
                for x in range(track.num_choices)
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
                c_id for i in range(track.num_choices) if (c_id := choice(i))]
            instructed_course = reg_tracks[track_id].get("course_instructor")
            for rank, course_id in enumerate(choices_list):
                # Check for choosing instructed course.
                if course_id == instructed_course:
                    rs.append_validation_error((
                        choice_key(rank),
                        ValueError(n_("Instructed course must not be chosen."))
                        if orga_input else
                        ValueError(n_("You may not choose your own course.")),
                    ))
                # Check for duplicated course choices.
                for x in range(rank):
                    if course_id == choice(x):
                        rs.append_validation_error((
                            choice_key(rank),
                             ValueError(
                                 n_("Cannot have the same course as %(i)s."
                                    " and %(j)s. choice.")
                                 if orga_input else
                                 n_("You cannot have the same course as %(i)s."
                                    " and %(j)s. choice."),
                                 {'i': x + 1, 'j': rank + 1}),
                        ))
                # Check that the course choice is allowed for this track.
                if not self.eventproxy.validate_single_course_choice(
                        rs, course_id, track_id, aux):
                    rs.append_validation_error((
                        choice_key(rank),
                        ValueError(n_("Invalid course choice for this track.")),
                    ))

            # Check for unfilled mandatory course choices, but only if not orga.
            if (len(choices_list) < track.min_choices
                    and track.part_id in part_ids and not orga_input):
                rs.extend_validation_errors(
                    (choice_key(x), ValueError(n_(
                        "You must choose at least %(min_choices)s courses."),
                        {'min_choices': track.min_choices}))
                    for x in range(len(choices_list), track.min_choices)
                )
            reg_tracks[track_id]["choices"] = choices_list
        registration['tracks'] = reg_tracks

        # Custom data field data:
        if orga_input:
            field_params: vtypes.TypeMapping = {
                f"fields.{field.field_name}": Optional[  # type: ignore[misc]
                    FIELD_DATATYPE_VALIDATORS[field.kind]]
                for field in event.fields.values()
                if field.association == const.FieldAssociations.registration
            }
            field_params = filter_params(field_params)
            raw_fields = request_extractor(rs, field_params)
            registration['fields'] = {
                field.field_name: raw_fields[raw_key]
                for field in event.fields.values()
                if (raw_key := f"fields.{field.field_name}") in raw_fields
            }
        else:
            field_params = self._questionnaire_params(
                rs, const.QuestionnaireUsages.registration)

            # Take special care to disallow empty fields with entries.
            tmp_fields = request_extractor(rs, field_params, postpone_validation=True)
            fields_by_name = {
                f"fields.{f.field_name}": f for f in event.fields.values()}
            for key, val in tmp_fields.items():
                if not val and fields_by_name[key].entries:
                    rs.append_validation_error(
                        (key, ValueError(n_("Must not be empty."))))

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
        if not rs.ambience['event'].is_open:
            rs.notify("error", n_("Registration not open."))
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/show_event")
        if rs.ambience['event'].is_archived:
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
            persona['birthday'], rs.ambience['event'].begin)
        if not self.eventproxy.has_minor_form(rs, event_id) and age.is_minor():
            rs.notify("error", n_("No minors may register. "
                                  "Please contact the Orgateam."))
            return self.redirect(rs, "event/show_event")
        registration['parental_agreement'] = not age.is_minor()
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration, orga_input=False)

        payment_data = self._get_payment_data(rs, event_id)

        subject = f"Anmeldung für {rs.ambience['event'].title}"
        reply_to = (rs.ambience['event'].orga_address or
                    self.conf["EVENT_ADMIN_ADDRESS"])
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': subject,
             'Reply-To': reply_to},
            {'age': age, 'mail_text': rs.ambience['event'].mail_text,
             **payment_data})
        rs.notify_return_code(new_id, success=n_("Registered for event."))

        if rs.ambience['event'].notify_on_registration.send_on_register():
            self._notify_on_registration(rs, rs.ambience['event'], new_id)

        return self.redirect(rs, "event/registration_status")

    def _notify_on_registration(self, rs: RequestState, event: models.Event,
                                registration_id: Optional[int] = None,
                                prev_timestamp: Optional[datetime.datetime] = None,
                                ) -> tuple[int, datetime.datetime]:
        """Retrieve recent registrations and if any, send notification.

        :returns: The number of new registrations and the current timestamp.
        """
        ref_timestamp = now().replace(microsecond=0)
        td = datetime.timedelta(minutes=15)
        prev_timestamp = \
            prev_timestamp or ref_timestamp - td * event.notify_on_registration.value

        if not event.orga_address:
            return 0, ref_timestamp

        if event.notify_on_registration.send_on_register() and registration_id:
            registration = self.eventproxy.get_registration(rs, registration_id)
            persona = self.coreproxy.get_event_user(rs, registration['persona_id'])
            registrations = [
                {
                    'persona.given_names': persona['given_names'],
                    'persona.family_name': persona['family_name'],
                    'id': registration_id,
                },
            ]
            query: Query | None = None
        elif event.notify_on_registration.send_periodically():
            query = Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=event),
                [
                    "persona.given_names",
                    "persona.family_name",
                    "persona.username",
                    "ctime.creation_time",
                ],
                [
                    (
                        "ctime.creation_time",
                        QueryOperators.between,
                        (
                            prev_timestamp,
                            ref_timestamp,
                        ),
                    ),
                ],
                [
                    ("ctime.creation_time", False),
                ],
            )
            registrations = list(
                self.eventproxy.submit_general_query(rs, query, event.id))
        else:
            return 0, ref_timestamp

        if not registrations:
            return 0, ref_timestamp

        self.do_mail(
            rs, "notify_on_registration",
            {
                "Subject": "Neue Anmeldung(en) für eure Veranstaltung",
                "To": (event.orga_address,),
            },
            {
                'event': event,
                'registrations': registrations,
                'query': query,
                'serialized_query': {
                    **query.serialize_to_url(),
                    'event_id': event.id,
                } if query else None,
                'NotifyOnRegistration': const.NotifyOnRegistration,
                'persona_name':
                    lambda r:
                        f"{r['persona.given_names']} {r['persona.family_name']}",
            },
        )
        return len(registrations), ref_timestamp

    @periodic("notify_on_registration")
    def notify_on_registration(self, rs: RequestState, store: CdEDBObject,
                               ) -> CdEDBObject:
        """Periodic for notifying orgas about recent new registrations."""
        store['period'] = store.get('period', -1) + 1
        event_ids = self.eventproxy.list_events(rs, archived=False)
        events = self.eventproxy.get_events(rs, event_ids)

        for event in events.values():
            timestamps = store.setdefault('timestamps', {})

            if event.notify_on_registration.send_periodically():
                if (store['period'] % event.notify_on_registration.value) == 0:
                    # Key needs to be string, because we store this as JSON:
                    prev_timestamp = (
                        datetime.datetime.fromisoformat(prev_str)
                        if (prev_str := timestamps.get(str(event.id)))
                        else None
                    )

                    num, new_timestamp = self._notify_on_registration(
                        rs, event, prev_timestamp=prev_timestamp,
                    )

                    store['timestamps'][event.id] = new_timestamp
                    if num:
                        self.logger.info(
                            f"Sent notification to orgas of {event.title}"
                            f" about {num} new registrations.")

        return store

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
            persona['birthday'], rs.ambience['event'].begin)
        registration['parts'] = OrderedDict(
            (part.id, registration['parts'][part.id])
            for part in xsorted(rs.ambience['event'].parts.values())
            if part.id in registration['parts'])
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, (const.QuestionnaireUsages.registration,)))
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=rs.user.persona_id)
        course_choice_parameters = self.get_course_choice_params(
            rs, event_id, orga=False)

        sorted_involved_tracks = {
            track.id: track for track in xsorted(rs.ambience['event'].tracks.values())
            if registration['parts'][track.part_id]['status'].is_involved()
        }

        is_involved = lambda cco: (set(cco.tracks) & sorted_involved_tracks.keys()
                                   if isinstance(cco, models.TrackGroup)
                                   else cco.id in sorted_involved_tracks)
        filtered_choice_objects = [
            cco for cco in course_choice_parameters['choice_objects']
            if cco.num_choices and is_involved(cco)
        ]

        return self.render(rs, "registration/registration_status", {
            'registration': registration, 'age': age,
            'reg_questionnaire': reg_questionnaire,
            'waitlist_position': waitlist_position,
            'sorted_involved_tracks': sorted_involved_tracks,
            'filtered_choice_objects': filtered_choice_objects,
            **payment_data, **course_choice_parameters,
        })

    @staticmethod
    def _prepare_registration_values(event: models.Event,
                                     registration: CdEDBObject) -> CdEDBObject:
        values: CdEDBObject = {
            f"reg.{key}": val
            for key, val in registration.items()
            if key not in {"parts", "tracks", "fields"}
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
            for tg_id, tg in event.tracks[track_id].track_groups.items():
                if not tg.constraint_type.is_sync():
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
    def amend_registration_form(self, rs: RequestState, event_id: int,
                                ) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event.tracks
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys() or None)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if event.is_archived:
            rs.notify("warning", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        if (event.registration_soft_limit and
                now() > event.registration_soft_limit):
            rs.notify("warning",
                      n_("Registration closed, no changes possible."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event'].begin)
        values = self._prepare_registration_values(event, registration)
        merge_dicts(rs.values, values)

        stat = lambda track: registration['parts'][track.part_id]['status']
        involved_tracks = {
            track_id for track_id, track in tracks.items()
            if const.RegistrationPartStati(stat(track)).is_involved()}

        payment_parts = {part_id for part_id, reg_part in registration['parts'].items()
                         if reg_part['status'].has_to_pay()}

        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        course_choice_params = self.get_course_choice_params(rs, event_id, orga=False)
        return self.render(rs, "registration/amend_registration", {
            'age': age, 'involved_tracks': involved_tracks,
            'persona': persona, 'semester_fee': self.conf['MEMBERSHIP_FEE'],
            'reg_questionnaire': reg_questionnaire, 'payment_parts': payment_parts,
            'was_member': registration['is_member'], **course_choice_params,
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
        if (rs.ambience['event'].registration_soft_limit and
                now() > rs.ambience['event'].registration_soft_limit):
            rs.notify("error", n_("No changes allowed anymore."))
            return self.redirect(rs, "event/registration_status")
        if rs.ambience['event'].is_archived:
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
            persona['birthday'], rs.ambience['event'].begin)
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        change_note = "Anmeldung durch Teilnehmer bearbeitet."
        code = self.eventproxy.set_registration(
            rs, registration, change_note, orga_input=False)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    @event_guard(EventPrivileges.registrations_read)
    def show_registration(self, rs: RequestState, event_id: int,
                          registration_id: int) -> Response:
        """Display all information pertaining to one registration."""
        payment_data = self._get_payment_data(rs, event_id, registration_id)
        persona = payment_data.pop('persona')
        age = determine_age_class(
            persona['birthday'], rs.ambience['event'].begin)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=persona['id'])
        constraint_violations = self.get_constraint_violations(
            rs, rs.ambience['event'], registration_id=registration_id, course_id=-1)
        course_choice_parameters = self.get_course_choice_params(rs, event_id)
        return self.render(rs, "registration/show_registration", {
            'persona': persona, 'age': age, 'lodgements': lodgements,
            'waitlist_position': waitlist_position,
            'constraint_violations': constraint_violations,
            **payment_data,
            **course_choice_parameters,
        })

    @access("event")
    @event_guard(EventPrivileges.registrations_read)
    def show_registration_fee(self, rs: RequestState, event_id: int,
                              registration_id: int) -> Response:
        """Display detailed information about amount owed and individual fees."""
        payment_data = self._get_payment_data(rs, event_id, registration_id)
        return self.render(rs, "registration/registration_fee_summary", {
            **payment_data,
        })

    @access("event")
    @event_guard(EventPrivileges.registrations_write)
    def add_new_personalized_fee_form(
            self, rs: RequestState, event_id: int, registration_id: int,
    ) -> Response:
        """Render form for creating a new personalized fee for a specific registration.

        The personalized amount for that registration is created at the same time.
        """
        if rs.ambience['event'].is_balanced:
            rs.notify(
                "error", n_("Event is balanced. May not change fee configuration."))
            return self.redirect(rs, "event/show_registration_fee")
        persona = self.coreproxy.get_persona(
            rs, rs.ambience['registration']['persona_id'])
        return self.render(rs, "event/fee/configure_fee",
                           {'persona': persona, 'personalized': True})

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write | EventPrivileges.registrations_write)
    @REQUESTdata('amount')
    @REQUESTdatadict(*models.EventFee.requestdict_fields(creation=True))
    def add_new_personalized_fee(
            self, rs: RequestState, event_id: int, registration_id: int,
            data: CdEDBObject, amount: decimal.Decimal,
    ) -> Response:
        """Create a personalized fee along with an amount for a specific registration.
        """
        data['amount'] = None
        fee_data = check(
            rs, vtypes.EventFee, data, creation=True, id_=-1,
            event=rs.ambience['event'].as_dict(), questionnaire={}, personalized=True,
        )
        if rs.has_validation_errors() or not fee_data:
            return self.add_new_personalized_fee_form(rs, event_id, registration_id)

        new_fee_id = self.eventproxy.set_event_fees(rs, event_id, {-1: fee_data})
        if new_fee_id:
            code = self.eventproxy.set_personalized_fee_amount(
                rs, registration_id, new_fee_id, amount)
            rs.notify_return_code(code)
        else:
            rs.notify("error", n_("Fee creation failed."))
        return self.redirect(rs, "event/show_registration_fee")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    def add_personalized_fee(
            self, rs: RequestState, event_id: int, registration_id: int, fee_id: int,
    ) -> Response:
        """Add a personalized fee amount for this registration and this fee."""
        if not rs.ambience['fee'].is_personalized():
            rs.ignore_validation_errors()
            rs.notify(
                "error", n_("Cannot set personalized amount for conditional fee."),
            )
            return self.redirect(rs, "event/show_registration_fee")
        key = f'amount{fee_id}'
        amount = request_extractor(rs, {key: decimal.Decimal})[key]
        if rs.has_validation_errors():
            return self.show_registration_fee(rs, event_id, registration_id)
        code = self.eventproxy.set_personalized_fee_amount(
            rs, registration_id, fee_id, amount,
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_registration_fee")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    def delete_personalized_fee(
            self, rs: RequestState, event_id: int, registration_id: int, fee_id: int,
    ) -> Response:
        """Remove the personalized fee amount for this registration and this fee."""
        if not rs.ambience['fee'].is_personalized():
            rs.notify(
                "error", n_("Cannot set personalized amount for conditional fee."),
            )
            return self.redirect(rs, "event/show_registration_fee")
        code = self.eventproxy.set_personalized_fee_amount(
            rs, registration_id, fee_id, amount=None,
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_registration_fee")

    @access("event")
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("registration_ids")
    def personalized_fee_multiset_form(
            self, rs: RequestState, event_id: int, fee_id: int | None = None,
            registration_ids: vtypes.IntCSVList | None = None,
    ) -> Response:
        """
        Render a form for setting an individual personalized fee for multiple
        registrations at once.

        This endpoint is used both with a fee id in the URL and without.
        In case of no fee id, we try to retrieve it from the request, and if that fails,
        we render a form to select a fee.
        Once a fee is thusly selected, we redirect to the URL with that fee id.

        The registration ids will default to **all registrations** if empty.
        """
        if fee_id is None:
            if len(fees := rs.ambience['event'].personalized_fees) == 1:
                fee_id = unwrap(fees.keys())
            else:
                fee_id = request_extractor(
                    rs, {'fee_id': Optional[int]},  # type: ignore[dict-item]
                )['fee_id']
            if fee_id:
                # Defer validation to after the redirect.
                rs.ignore_validation_errors()
                return self.redirect(
                    rs, 'event/personalized_fee_multiset_form',
                    {
                        'fee_id': fee_id,
                        'registration_ids': rs.request.values['registration_ids'],
                    },
                )
        if rs.has_validation_errors():
            if registration_ids is None:
                rs.notify("warning", n_("Invalid registrations."))
                registration_ids = vtypes.IntCSVList([])
        if not registration_ids:
            registration_ids = vtypes.IntCSVList(list(
                self.eventproxy.list_registrations(rs, event_id)))
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        if any(reg['event_id'] != event_id for reg in registrations.values()):
            rs.notify("error", n_("Invalid registrations."))
            registrations = {}
        if not registrations:
            rs.notify("info", n_("No registrations selected."))
            return self.redirect(rs, "event/fee_summary")
        personas = self.coreproxy.get_personas(
            rs, [reg['persona_id'] for reg in registrations.values()])
        sorted_registrations = xsorted(
            registrations.values(),
            key=lambda reg: EntitySorter.persona(personas[reg['persona_id']]),
        )
        if fee_id:
            values = {
                f'amount{reg_id}': reg['personalized_fees'].get(fee_id)
                for reg_id, reg in registrations.items()
            }
            merge_dicts(rs.values, values)
        fee_titles = {
            fee.id: fee.title for fee in rs.ambience['event'].personalized_fees.values()
        }
        return self.render(
            rs, "event/fee/personalized_fee_multiset",
            {
                'registration_ids': xsorted(registration_ids),
                'registrations': sorted_registrations,
                'personas': personas,
                'fee_titles': fee_titles,
            },
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("registration_ids")
    def personalized_fee_multiset(
            self, rs: RequestState, event_id: int, fee_id: int,
            registration_ids: vtypes.IntCSVList,
    ) -> Response:
        """Set multiple personalized fees at once."""
        if rs.has_validation_errors():
            rs.notify("warning", n_("Invalid registrations."))
            registration_ids = []  # type: ignore[assignment]
        registrations = {}
        if registration_ids:
            registrations = self.eventproxy.get_registrations(rs, registration_ids)
        if not registrations or any(
                reg['event_id'] != event_id for reg in registrations.values()
        ):
            rs.notify("error", n_("Invalid registrations."))
            return self.redirect(rs, "event/fee_summary")

        params: vtypes.TypeMapping = {
            f'amount{reg_id}': Optional[decimal.Decimal]  # type: ignore[misc]
            for reg_id in registrations
        }
        data = request_extractor(rs, params)

        if rs.has_validation_errors():
            return self.personalized_fee_multiset_form(
                rs, event_id, fee_id, registration_ids=registration_ids)

        description = (
            f"{rs.user.persona_name()} is setting personalized fees"
            f" for {len(registrations)} registrations"
            f" for fee {rs.ambience['fee'].title}"
            f" for event {rs.ambience['event'].title}."
        )
        recipients = (
            rs.ambience['event'].orga_address or self.conf['EVENT_ADMIN_ADDRESS'],
        )

        count = 0
        with TransactionObserver(
                rs, self, "personalized_fee_multiset", description=description,
                recipients=recipients,
        ):
            # Sort by id for consistency.
            for reg_id, reg in xsorted(registrations.items()):
                new_amount = data[f'amount{reg_id}']
                if new_amount != reg['personalized_fees'].get(fee_id):
                    count += bool(
                        self.eventproxy.set_personalized_fee_amount(
                            rs, reg_id, fee_id, new_amount),
                    )

        if count:
            rs.notify("success", n_("Updated %(count)s personalized fees."),
                      {'count': count})
        else:
            rs.notify("info", n_("Nothing changed."))
        return self.redirect(rs, "event/fee_summary")

    @access("event")
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("change_note")
    def change_registration_form(self, rs: RequestState, event_id: int,
                                 registration_id: int, change_note: Optional[str],
                                 internal: bool = False,
                                 ) -> Response:
        """Render form.

        :param internal: used if the call comes from another frontend
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
            'persona': persona, 'lodgements': lodgements, 'change_note': change_note,
            **course_choice_params,
        })

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("change_note")
    def change_registration(self, rs: RequestState, event_id: int,
                            registration_id: int,
                            change_note: Optional[str]) -> Response:
        """Make privileged changes to any information pertaining to a
        registration.

        Strictly speaking this makes a lot of the other functionality
        redundant (like managing the lodgement inhabitants), but it would be
        much more cumbersome to always use this interface.
        """
        registration = self.new_process_registration_input(rs, orga_input=True)
        if rs.ambience['event'].is_balanced:
            new_amount_owed = self._calculate_single_fee(rs, registration)
            if new_amount_owed != rs.ambience['registration']['amount_owed']:
                msg = n_("Event is balanced. Amount owed may no longer change.")
                # This is not an input so this error won't mark any input field.
                rs.append_validation_error(("amount_owed", ValueError(msg)))
                rs.notify("error", msg)
        if rs.has_validation_errors():
            return self.change_registration_form(
                rs, event_id, registration_id, internal=True,
                change_note=change_note)
        registration['id'] = registration_id
        code = self.eventproxy.set_registration(rs, registration, change_note)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_registration")

    @access("event")
    @event_guard(EventPrivileges.registrations_write)
    def add_registration_form(self, rs: RequestState, event_id: int,
                              ) -> Response:
        """Render form."""
        registrations = self.eventproxy.list_registrations(rs, event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        defaults = {
            f"part{part_id}.status":
                const.RegistrationPartStati.participant
            for part_id in rs.ambience['event'].parts
        }
        merge_dicts(rs.values, defaults)
        course_choice_params = self.get_course_choice_params(rs, event_id)
        return self.render(rs, "registration/add_registration", {
            'lodgements': lodgements, 'registered_personas': registrations.values(),
            **course_choice_params,
        })

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
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
        if persona_id and self.eventproxy.list_registrations(rs, event_id, persona_id):
            rs.append_validation_error(("persona.persona_id",
                                        ValueError(n_("Already registered."))))
        registration = self.new_process_registration_input(rs, orga_input=True)
        if not self.eventproxy.check_orga_addition_limit(rs, event_id):
            rs.append_validation_error(
                ("persona.persona_id", ValueError(n_("Rate-limit reached."))))
        if persona_id and self._calculate_single_fee(rs, registration, persona_id):
            msg = n_("Event is balanced. May not create registration which owes a fee.")
            # This is not an input so this error won't mark any input field.
            rs.append_validation_error(("amount_owed", ValueError(msg)))
            rs.notify("error", msg)
        if rs.has_validation_errors():
            return self.add_registration_form(rs, event_id)

        registration['persona_id'] = persona_id
        registration['event_id'] = event_id
        new_id = self.eventproxy.create_registration(rs, registration)
        rs.notify_return_code(new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
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
    @event_guard(EventPrivileges.registrations_write)
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
        for part_id, part in rs.ambience['event'].parts.items():
            for key, value in representative['parts'][part_id].items():
                if all(r['parts'][part_id][key] == value for r in reg_vals):
                    reg_data[f'part{part_id}.{key}'] = value
                    reg_data[f'enable_part{part_id}.{key}'] = True
            for track_id in part.tracks:
                for key, value in representative['tracks'][track_id].items():
                    # Do no include course choices in multiedit.
                    if key == 'choices':
                        continue
                    if all(r['tracks'][track_id][key] == value for r in reg_vals):
                        reg_data[f'track{track_id}.{key}'] = value
                        reg_data[f'enable_track{track_id}.{key}'] = True

        for tg_id, tg in rs.ambience['event'].track_groups.items():
            if not tg.constraint_type.is_sync():
                continue
            repr_track = next(iter(tg.tracks))
            for key, value in representative['tracks'][repr_track].items():
                if key == 'choices':
                    continue
                if all(
                    r['tracks'][track][key] == value
                    for track in tg.tracks for r in reg_vals
                ):
                    reg_data[f'group{tg_id}.{key}'] = value
                    reg_data[f'enable_group{tg_id}.{key}'] = True

        for field_id, field in rs.ambience['event'].fields.items():
            key = field.field_name
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
    @event_guard(EventPrivileges.registrations_write)
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

        self.logger.info(
            f"Updating registrations {reg_ids} with data {registration}")
        msg1 = build_msg("Snapshot vor Bearbeitung mehrerer Anmeldungen", change_note)
        msg2 = build_msg("Bearbeite mehrere Anmeldungen", change_note)
        change_note = build_msg("Multi-Edit", change_note)

        self.eventproxy.event_keeper_commit(rs, event_id, msg1)
        data = [
            {'id': reg_id, **registration}
            for reg_id in reg_ids
        ]
        code = self.eventproxy.set_registrations(rs, data, change_note)
        self.eventproxy.event_keeper_commit(rs, event_id, msg2, after_change=True)
        rs.notify_return_code(code)

        # redirect to query filtered by reg_ids
        scope = QueryScope.registration
        query = Query(
            scope, scope.get_spec(event=rs.ambience['event']),
            ("reg.id", "persona.given_names", "persona.family_name",
             "persona.username"),
            (("reg.id", QueryOperators.oneof, reg_ids),),
            (("persona.family_name", True), ("persona.given_names", True)),
        )
        return self.redirect(rs, scope.get_target(), query.serialize_to_url())

    @access("event")
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("part_ids")
    def checkin_form(self, rs: RequestState, event_id: int,
                     part_ids: Optional[Collection[int]] = None) -> Response:
        """Render form."""
        if rs.has_validation_errors() or not part_ids:
            parts = rs.ambience['event'].parts
        else:
            parts = {p_id: rs.ambience['event'].parts[p_id] for p_id in part_ids}
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        there = lambda registration, part_id: const.RegistrationPartStati(
            registration['parts'][part_id]['status']).is_present()
        registrations = {
            k: v for k, v in registrations.items()
            if ((not v['checkin_periods'] or v['checkin_periods'][-1].checkout_time)
                and any(there(v, id_) for id_ in parts))}
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event'].begin)
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        checkin_fields = {
            field_id: f for field_id, f in rs.ambience['event'].fields.items()
            if f.checkin and f.association == const.FieldAssociations.registration
        }
        camping_mat_field_names = self._get_camping_mat_field_names(
            rs.ambience['event'])
        return self.render(rs, "registration/checkin", {
            'registrations': registrations, 'personas': personas,
            'lodgements': lodgements, 'checkin_fields': checkin_fields,
            'part_ids': part_ids, 'camping_mat_field_names': camping_mat_field_names,
        })

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("from_checkin_page", "part_ids")
    def add_checkin(
        self, rs: RequestState, event_id: int, registration_id: vtypes.ID,
        from_checkin_page: Optional[bool] = False,
        part_ids: Optional[Collection[int]] = None,
    ) -> Response:
        """Check a participant in."""
        if rs.has_validation_errors():
            if from_checkin_page:
                return self.checkin_form(rs, event_id)
            return self.show_registration(rs, event_id, registration_id)

        if (rs.ambience['registration']['checkin_periods']
            and not rs.ambience['registration']['checkin_periods'][-1].checkout_time):
            rs.notify("error", n_("Already checked in."))
            if from_checkin_page:
                return self.checkin_form(rs, event_id)
            return self.show_registration(rs, event_id, registration_id)

        code = self.eventproxy.add_checkin(rs, registration_id)
        rs.notify_return_code(code, error=n_("Action failed."))
        if from_checkin_page:
            return self.redirect(rs, 'event/checkin_form', {'part_ids': part_ids})
        return self.redirect(rs, 'event/show_registration',
                             {'registration_id': registration_id})

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    def add_checkout(
        self, rs: RequestState, event_id: int, registration_id: vtypes.ID,
    ) -> Response:
        """Check a participant out."""
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        if rs.ambience['registration']['checkin_periods'][-1].checkout_time:
            rs.notify("error", n_("Already checked out."))
            return self.show_registration(rs, event_id, registration_id)

        code = self.eventproxy.add_checkout(rs, registration_id)
        rs.notify_return_code(code, error=n_("Action failed."))
        return self.redirect(rs, 'event/show_registration',
                             {'registration_id': registration_id})

    @access('event', modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("period_id")
    def change_checkin_period(self, rs: RequestState, event_id: int,
                              registration_id: vtypes.ID, period_id: vtypes.ID,
                              ) -> Response:
        """Change the time a participant was present."""
        reg = rs.ambience['registration']
        if period_id not in {period.id for period in reg['checkin_periods']}:
            raise ValueError(n_("Inconsistent data."))
        checkin_time: datetime.datetime = unwrap(request_extractor(
            rs, {f'checkin_time_{period_id}': datetime.datetime}))
        checkout_time: Optional[datetime.datetime] = unwrap(request_extractor(
            rs, {f'checkout_time_{period_id}': Optional[datetime.datetime]}))  # type:ignore[dict-item]
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        # check positive timespan in past
        ref_time = now()
        if checkin_time > ref_time:
            rs.append_validation_error(
                (f'checkin_time_{period_id}', ValueError(n_("Must be in the past."))))
        if checkout_time and checkout_time > ref_time:
            rs.append_validation_error(
                (f'checkout_time_{period_id}', ValueError(n_("Must be in the past."))))
        if checkout_time and not checkin_time < checkout_time:
            rs.append_validation_error(
                (f'checkout_time_{period_id}', ValueError(n_("Checkout must be after checkin."))))
        by_id = {p.id: p for p in reg['checkin_periods']}
        if (idx := reg['checkin_periods'].index(by_id[period_id])) > 0:
            prev = reg['checkin_periods'][idx - 1]
            if not prev.checkout_time <= checkin_time:
                rs.append_validation_error((f'checkin_time_{period_id}', ValueError(
                    n_("Checkin must be after previous checkout."),
                )))
        if idx < len(reg['checkin_periods']) - 1:
            nxt = reg['checkin_periods'][idx + 1]
            if not checkout_time or checkout_time > nxt.checkin_time:
                rs.append_validation_error((f'checkout_time_{period_id}', ValueError(
                    n_("Checkout must be before next checkin."),
                )))
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        ret = self.eventproxy.change_checkin_period(
            rs, registration_id, period_id, checkin_time, checkout_time)
        rs.notify_return_code(ret)
        return self.redirect(rs, 'event/show_registration',
                             {'registration_id': registration_id})

    @access('event', modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("period_id")
    def delete_checkin_period(self, rs: RequestState, event_id: int,
                              registration_id: vtypes.ID,
                              period_id: vtypes.ID) -> Response:
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)
        # no validation errors can be caused by the user. Errors are a bug in code,
        # or due to racing. Let them be raised by the backend.
        ret = self.eventproxy.delete_checkin_period(rs, registration_id, period_id)
        rs.notify_return_code(ret, error=n_("Action failed."))
        return self.redirect(rs, 'event/show_registration',
                             {'registration_id': registration_id})

    @access('event')
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("registration_ids")
    def checkin_multiset_form(self, rs: RequestState, event_id: int,
                              registration_ids: Optional[vtypes.IntCSVList] = None,
                              internal: bool = False) -> Response:
        """Form to check in or out multiple people at once,

        :param internal: if called from another frontend method,
         use to avoid further redirects on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, 'event/registration_query',
                                 {'event_id': event_id})
        if not registration_ids:
            registration_ids = cast(
                vtypes.IntCSVList,
                list(self.eventproxy.list_registrations(rs, event_id)),
            )
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(reg['persona_id'] for reg in registrations.values()))
        registrations = {reg['id']: reg for reg in xsorted(
            registrations.values(),
            key=lambda reg: EntitySorter.persona(personas[reg['persona_id']]),
        )}
        names = {
            reg_id: make_persona_name(personas[reg['persona_id']])
            for reg_id, reg in registrations.items()
        }
        present = {
            reg_id: reg['checkin_periods'] for reg_id, reg in registrations.items()
            if reg['checkin_periods'] and not reg['checkin_periods'][-1].checkout_time
        }
        absent = {
            reg_id: reg['checkin_periods'] for reg_id, reg in registrations.items()
            if reg_id not in present
        }
        return self.render(rs, 'registration/checkin_multiset',
                           {'names': names, 'present': present, 'absent': absent})

    @access('event', modi={"POST"})
    @event_guard(EventPrivileges.registrations_write)
    @REQUESTdata("registration_ids", "action", "checkin_time", "checkout_time")
    def checkin_multiset(self, rs: RequestState, event_id: int,
                         registration_ids: vtypes.IntCSVList, action: str,
                         checkin_time: Optional[datetime.datetime],
                         checkout_time: Optional[datetime.datetime]) -> Response:
        """Checkin/-out multiple people at once.

        :param action: One of 'checkout','modify_checkin', 'checkin', 'modify_checkout'.
            The modify_ options mass-reset the latest respective timestamp and
            the others add new ones.
        """
        ref_time = now()
        if checkin_time and checkin_time > ref_time:
            rs.append_validation_error(
                ('checkin_time', ValueError(n_("Must be in the past."))))
        if checkout_time and checkout_time > ref_time:
            rs.append_validation_error(
                ('checkout_time', ValueError(n_("Must be in the past."))))
        if rs.has_validation_errors():
            return self.checkin_multiset_form(rs, event_id, internal=True)
        if action not in {'checkin', 'modify_checkout', 'checkout', 'modify_checkin'}:
            rs.notify("error", n_("Invalid action."))
            return self.checkin_multiset_form(rs, event_id, internal=True)

        regs = self.eventproxy.get_registrations(rs, registration_ids)
        # first, validate
        consistent = True
        if action == 'checkout':
            if not checkout_time:
                rs.append_validation_error(
                    ('checkout_time', ValueError(n_("Must not be empty."))))
            elif checkout_time < max(
                reg['checkin_periods'][-1].checkin_time for reg in regs.values()
            ):
                rs.append_validation_error(
                    ('checkout_time', ValueError(n_("Must be after last checkin."))))
        if action in {'checkout', 'modify_checkin'}:
            if any(
                not reg['checkin_periods'] or reg['checkin_periods'][-1].checkout_time
                for reg in regs.values()
            ):
                rs.notify('error', n_("People must be checked in."))
                consistent = False
        if (action == 'modify_checkin'
            and any(len(reg['checkin_periods']) >= 2 for reg in regs.values())
            and checkin_time < max(
                reg['checkin_periods'][-2].checkout_time
                for reg in regs.values() if len(reg['checkin_periods']) >= 2)
        ):
            rs.append_validation_error(
                ('checkin_time', ValueError(n_("Must be after last checkout."))))
        if action == 'checkin':
            if not checkin_time:
                rs.append_validation_error(
                    ('checkin_time', ValueError(n_("Must not be empty."))))
            elif (any(reg['checkin_periods'] for reg in regs.values())
                  and checkin_time <= max(
                    reg['checkin_periods'][-1].checkout_time
                    for reg in regs.values() if reg['checkin_periods'])
            ):
                rs.append_validation_error(
                    ('checkin_time', ValueError(n_("Must be after last checkout."))))
        if action in {'checkin', 'modify_checkout'}:
            if any(
                reg['checkin_periods'] and not reg['checkin_periods'][-1].checkout_time
                for reg in regs.values()
            ):
                rs.notify('error', n_("People must not be checked in."))
                consistent = False
        if (action == 'modify_checkout'
            and any(reg['checkin_periods'] for reg in regs.values())
            and checkout_time < max(reg['checkin_periods'][-1].checkin_time
                                    for reg in regs.values() if reg['checkin_periods'])
        ):
            rs.append_validation_error(
                ('checkout_time', ValueError(n_("Must be after last checkin."))))
        if rs.has_validation_errors() or not consistent:
            return self.checkin_multiset_form(rs, event_id, internal=True)

        # then, process
        ret = 1
        if action == 'checkin':
            ret *= self.eventproxy.add_checkins(rs, registration_ids, checkin_time)
        elif action == 'checkout':
            ret *= self.eventproxy.add_checkouts(rs, registration_ids, checkout_time)
        elif action == 'modify_checkin':
            if not checkin_time:  # delete latest checkins
                for reg_id, reg in regs.items():
                    ret *= self.eventproxy.delete_checkin_period(
                        rs, reg_id, reg['checkin_periods'][-1].id)
            else:
                for reg_id, reg in regs.items():
                    ret *= self.eventproxy.change_checkin_period(
                        rs, reg_id, reg['checkin_periods'][-1].id, checkin_time, None)
        elif action == 'modify_checkout':
            for reg_id, reg in regs.items():
                if reg['checkin_periods']:
                    last_period = reg['checkin_periods'][-1]
                    ret *= self.eventproxy.change_checkin_period(
                        rs, reg_id, last_period.id, last_period.checkin_time,
                        checkout_time)

        rs.notify_return_code(ret)
        return self.redirect(rs, 'event/registration_query',
                             {'event_id': event_id})

    def _get_payment_data(self, rs: RequestState, event_id: int,
                          registration_id: Optional[int] = None) -> CdEDBObject:
        if not registration_id:
            reg_list = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id)
            if not reg_list:
                return {}
            registration_id = unwrap(reg_list.keys())
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(
            rs, registration['persona_id'], event_id)

        meta_info = self.coreproxy.get_meta_info(rs)
        complex_fee = self.eventproxy.calculate_complex_fee(
            rs, registration_id, visual_debug=True)
        fee = complex_fee.amount
        to_pay = fee - registration['amount_paid']
        reference = make_event_fee_reference(persona, rs.ambience['event'])

        return {
            'registration': registration, 'persona': persona,
            'meta_info': meta_info, 'reference': reference, 'to_pay': to_pay,
            'account': rs.ambience['event'].iban, 'fee': fee,
            'complex_fee': complex_fee, 'semester_fee': self.conf['MEMBERSHIP_FEE'],
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
        if not payment_data['account']:
            return None
        # Ensure that the "free-"text parts are not too long. The exact size is limited
        # by third parties.
        account: Accounts = payment_data['account']
        return {
            'name': account.get_account_holder()[:70],
            'text': payment_data['reference'][:140],
            'amount': payment_data['to_pay'],
            'iban': account.get_iban(),
            'bic': account.get_bic(),
        }

    def _registration_fee_qr(self, payment_data: CdEDBObject) -> Optional[segno.QRCode]:
        data = self._registration_fee_qr_data(payment_data)
        if not data:
            return None
        return segno.helpers.make_epc_qr(**data)
