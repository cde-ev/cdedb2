#!/usr/bin/env python3

"""Services for the cde realm."""

import copy
import csv
import datetime
import decimal
import functools
import itertools
import operator
import pathlib
import random
import re
import shutil
import string
import tempfile
import time
from collections import OrderedDict, defaultdict
from typing import Collection, Dict, List, Optional, Sequence, Set, Tuple, cast

import dateutil.easter
import psycopg2.extensions
import werkzeug.exceptions
from werkzeug import Response
from werkzeug.datastructures import FileStorage

import cdedb.database.constants as const
import cdedb.frontend.parse_statement as parse
import cdedb.validationtypes as vtypes
from cdedb.common import (
    Accounts, ArchiveError, CdEDBObject, CdEDBObjectMap, DefaultReturnCode,
    EntitySorter, Error, LineResolutions, LOG_FIELDS_COMMON, PERSONA_DEFAULTS,
    RequestState, SemesterSteps, TransactionType, asciificator, deduct_years,
    determine_age_class, diacritic_patterns, get_hash, glue, int_to_words,
    lastschrift_reference, merge_dicts, n_, now, unwrap, xsorted,
)
from cdedb.database.connection import Atomizer
from cdedb.frontend.common import (
    AbstractUserFrontend, CustomCSVDialect, REQUESTdata, REQUESTdatadict, REQUESTfile,
    Worker, access, calculate_db_logparams, calculate_loglinks, cdedbid_filter,
    check_validation as check, check_validation_optional as check_optional, csv_output,
    enum_entries_filter, make_membership_fee_reference, make_postal_address,
    money_filter, periodic, process_dynamic_input, request_extractor,
)
from cdedb.query import (
    QUERY_SPECS, Query, QueryConstraint, QueryOperators, mangle_query_input,
)
from cdedb.validation import (
    LASTSCHRIFT_COMMON_FIELDS, PAST_EVENT_FIELDS, PAST_COURSE_COMMON_FIELDS,
    PERSONA_FULL_CDE_CREATION, TypeMapping, filter_none, validate_check,
    validate_check_optional, PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS,
    is_optional
)

MEMBERSEARCH_DEFAULTS = {
    'qop_fulltext': QueryOperators.containsall,
    'qsel_family_name,birth_name': True,
    'qop_family_name,birth_name': QueryOperators.match,
    'qsel_given_names,display_name': True,
    'qop_given_names,display_name': QueryOperators.match,
    'qsel_username': True,
    'qop_username': QueryOperators.match,
    'qop_telephone,mobile': QueryOperators.match,
    'qop_address,address_supplement,address2,address_supplement2':
        QueryOperators.match,
    'qop_postal_code,postal_code2': QueryOperators.between,
    'qop_location,location2': QueryOperators.match,
    'qop_country,country2': QueryOperators.match,
    'qop_weblink,specialisation,affiliation,timeline,interests,free_form':
        QueryOperators.match,
    'qop_pevent_id': QueryOperators.equal,
    'qop_pcourse_id': QueryOperators.equal,
    'qord_primary': 'family_name,birth_name',
    'qord_primary_ascending': True,
}

COURSESEARCH_DEFAULTS = {
    'qsel_courses.title': True,
    'qop_courses.title': QueryOperators.match,
    'qsel_events.title': True,
    'qop_events.title': QueryOperators.match,
    'qop_courses.nr': QueryOperators.match,
    'qop_courses.description': QueryOperators.match,
    'qsel_courses.pevent_id': True,
    'qsel_events.tempus': True,
    'qord_primary': 'courses.title',
    'qord_primary_ascending': True,
    'qord_secondary': 'events.tempus',
    'qord_secondary_ascending': False
}


class CdEFrontend(AbstractUserFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def _calculate_ejection_deadline(self, persona_data: CdEDBObject,
                                     period: CdEDBObject) -> datetime.date:
        """Helper to calculate when a membership will end."""
        if not self.conf["PERIODS_PER_YEAR"] == 2:
            msg = (f"{self.conf['PERIODS_PER_YEAR']} periods per year not"
                   f" supported.")
            if self.conf["CDEDB_DEV"] or self.conf["CDEDB_TEST"]:
                raise RuntimeError(msg)
            else:
                self.logger.error(msg)
                return now().date()
        periods_left = persona_data['balance'] // self.conf["MEMBERSHIP_FEE"]
        if persona_data['trial_member']:
            periods_left += 1
        if period['balance_done']:
            periods_left += 1
        deadline = (period.get("semester_start") or now()).date().replace(day=1)
        # With our buffer zones around the expected semester start dates there
        # are 3 possible semesters within a year with different deadlines.
        if deadline.month in range(5, 11):
            # Start was two months before or 4 months after expected start for
            # summer semester, so we assume that we are in the summer semester.
            if periods_left % 2:
                deadline = deadline.replace(year=deadline.year + 1, month=2)
            else:
                deadline = deadline.replace(month=8)
        else:
            # Start was two months before or 4 months after expected start for
            # winter semester, so we assume that we are in a winter semester.
            if deadline.month in range(1, 5):
                # We are in the first semester of the year.
                deadline = deadline.replace(month=2)
            else:
                # We are in the last semester of the year.
                deadline = deadline.replace(year=deadline.year + 1, month=2)
            if periods_left % 2:
                deadline = deadline.replace(month=8)
        return deadline.replace(
            year=deadline.year + periods_left // 2)

    @access("cde")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        meta_info = self.coreproxy.get_meta_info(rs)
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        deadline = None
        reference = make_membership_fee_reference(data)
        has_lastschrift = False
        if "member" in rs.user.roles:
            assert rs.user.persona_id is not None
            has_lastschrift = bool(self.cdeproxy.list_lastschrift(
                rs, persona_ids=(rs.user.persona_id,), active=True))
            period = self.cdeproxy.get_period(
                rs, self.cdeproxy.current_period(rs))
            deadline = self._calculate_ejection_deadline(data, period)
        return self.render(rs, "index", {
            'has_lastschrift': has_lastschrift, 'data': data,
            'meta_info': meta_info, 'deadline': deadline,
            'reference': reference,
        })

    @access("member")
    def consent_decision_form(self, rs: RequestState) -> Response:
        """After login ask cde members for decision about searchability. Do
        this only if no decision has been made in the past.

        This is the default page after login, but most users will instantly
        be redirected.
        """
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        return self.render(rs, "consent_decision",
                           {'decided_search': data['decided_search']})

    @access("member", modi={"POST"})
    @REQUESTdata("ack")
    def consent_decision(self, rs: RequestState, ack: bool) -> Response:
        """Record decision."""
        if rs.has_validation_errors():
            return self.consent_decision_form(rs)
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        new = {
            'id': rs.user.persona_id,
            'decided_search': True,
            'is_searchable': ack,
        }
        change_note = "Datenschutz-Einwilligung entschieden ({ack}).".format(
            ack="akzeptiert" if ack else "abgelehnt")
        code = self.coreproxy.change_persona(
            rs, new, generation=None, may_wait=False,
            change_note=change_note)
        message = n_("Consent noted.") if ack else n_("Decision noted.")
        self.notify_return_code(rs, code, success=message)
        if not code:
            return self.consent_decision_form(rs)
        if not data['decided_search']:
            return self.redirect(rs, "core/index")
        return self.redirect(rs, "cde/index")

    @access("cde_admin", "member")
    def member_stats(self, rs: RequestState) -> Response:
        """Display stats about our members."""
        stats = self.cdeproxy.get_member_stats(rs)
        return self.render(rs, "member_stats", {'stats': stats})

    @access("persona")
    @REQUESTdata("is_search")
    def member_search(self, rs: RequestState, is_search: bool) -> Response:
        """Search for members."""
        if "searchable" not in rs.user.roles:
            # As this is linked externally, show a meaningful error message to
            # unprivileged users.
            rs.ignore_validation_errors()
            return self.render(rs, "member_search")
        defaults = copy.deepcopy(MEMBERSEARCH_DEFAULTS)
        pl = rs.values['postal_lower'] = rs.request.values.get('postal_lower')
        pu = rs.values['postal_upper'] = rs.request.values.get('postal_upper')
        if pl and pu:
            defaults['qval_postal_code,postal_code2'] = "{:0<5} {:0<5}".format(
                pl, pu)
        elif pl:
            defaults['qval_postal_code,postal_code2'] = "{:0<5} 99999".format(
                pl)
        elif pu:
            defaults['qval_postal_code,postal_code2'] = "00000 {:0<5}".format(
                pu)
        else:
            defaults['qop_postal_code,postal_code2'] = QueryOperators.match
        spec = copy.deepcopy(QUERY_SPECS['qview_cde_member'])
        query = check(rs, vtypes.QueryInput,
                      mangle_query_input(rs, spec, defaults), "query", spec=spec,
                      allow_empty=not is_search, separator=" ")

        events = self.pasteventproxy.list_past_events(rs)
        pevent_id = None
        if rs.values.get('qval_pevent_id'):
            try:
                pevent_id = int(rs.values.get('qval_pevent_id'))  # type: ignore
            except ValueError:
                pass
        courses: Dict[int, str] = {}
        if pevent_id:
            courses = self.pasteventproxy.list_past_courses(rs, pevent_id)
        choices = {"pevent_id": events, 'pcourse_id': courses}
        result: Optional[Sequence[CdEDBObject]] = None
        count = 0
        cutoff = self.conf["MAX_MEMBER_SEARCH_RESULTS"]

        if rs.has_validation_errors():
            self._fix_search_validation_error_references(rs)
        else:
            assert query is not None
            if is_search and not query.constraints:
                rs.notify("error", n_("You have to specify some filters."))
            elif is_search:

                def restrict(constraint: QueryConstraint) -> QueryConstraint:
                    field, operation, value = constraint
                    if field == 'fulltext':
                        value = [r"\m{}\M".format(val) if len(val) <= 3 else val
                                 for val in value]
                    elif len(str(value)) <= 3:
                        operation = QueryOperators.equal
                    constraint = (field, operation, value)
                    return constraint

                query.constraints = [restrict(constrain)
                                     for constrain in query.constraints]
                query.scope = "qview_cde_member"
                query.fields_of_interest.append('personas.id')
                result = self.cdeproxy.submit_general_query(rs, query)
                count = len(result)
                if count == 1:
                    return self.redirect_show_user(rs, result[0]['id'], quote_me=True)
                if count > cutoff:
                    result = result[:cutoff]
                    rs.notify("info", n_("Too many query results."))

        return self.render(rs, "member_search", {
            'spec': spec, 'choices': choices, 'result': result,
            'cutoff': cutoff, 'count': count,
        })

    @access("member", "cde_admin")
    @REQUESTdata("is_search")
    def past_course_search(self, rs: RequestState, is_search: bool) -> Response:
        """Search for past courses."""
        defaults = copy.deepcopy(COURSESEARCH_DEFAULTS)
        spec = copy.deepcopy(QUERY_SPECS['qview_pevent_course'])
        query = check(rs, vtypes.QueryInput,
                      mangle_query_input(rs, spec, defaults), "query", spec=spec,
                      allow_empty=not is_search, separator=" ")
        result: Optional[Sequence[CdEDBObject]] = None
        count = 0

        if rs.has_validation_errors():
            self._fix_search_validation_error_references(rs)
        else:
            assert query is not None
            if is_search and not query.constraints:
                rs.notify("error", n_("You have to specify some filters."))
            elif is_search:
                query.scope = "qview_pevent_course"
                query.fields_of_interest.append('courses.id')
                result = self.pasteventproxy.submit_general_query(rs, query)
                count = len(result)
                if count == 1:
                    return self.redirect(rs, "cde/show_past_course", {
                        'pevent_id': result[0]['courses.pevent_id'],
                        'pcourse_id': result[0]['courses.id']})

        return self.render(rs, "past_course_search", {
            'spec': spec, 'result': result, 'count': count})

    @staticmethod
    def _fix_search_validation_error_references(rs: RequestState) -> None:
        """A little hack to fix displaying of errors for course and meber search:

        The form uses 'qval_<field>' as input name, the validation only returns the
        field's name.
        """
        current = tuple(rs.retrieve_validation_errors())
        rs.replace_validation_errors(
            [('qval_' + k, v) for k, v in current])  # type: ignore[operator]
        rs.ignore_validation_errors()

    @access("core_admin", "cde_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str], is_search: bool
                    ) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        return self.generic_user_search(
            rs, download, is_search, 'qview_cde_user', 'qview_cde_user',
            self.cdeproxy.submit_general_query, choices=choices)

    @access("core_admin", "cde_admin")
    @REQUESTdata("download", "is_search")
    def archived_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        return self.generic_user_search(
            rs, download, is_search,
            'qview_archived_past_event_user', 'qview_archived_persona',
            self.cdeproxy.submit_general_query, choices=choices,
            endpoint="archived_user_search")

    @access("core_admin", "cde_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': True,
            'bub_search': False,
            'paper_expuls': True,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("core_admin", "cde_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_CDE_CREATION))
    def create_user(self, rs: RequestState, data: CdEDBObject,
                    ignore_warnings: bool = False) -> Response:
        defaults = {
            'is_cde_realm': True,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
            'decided_search': False,
            'paper_expuls': True,
        }
        data.update(defaults)
        return super().create_user(rs, data, ignore_warnings)

    @access("cde_admin")
    def batch_admission_form(self, rs: RequestState,
                             data: List[CdEDBObject] = None,
                             csvfields: Tuple[str, ...] = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        defaults = {
            'membership': True,
            'trial_membership': True,
            'consent': False,
            'sendmail': True,
        }
        merge_dicts(rs.values, defaults)
        data = data or []
        csvfields = csvfields or tuple()
        pevents = self.pasteventproxy.list_past_events(rs)
        pevent_ids = {d['pevent_id'] for d in data if d.get('pevent_id')}
        pcourses = {
            pevent_id: self.pasteventproxy.list_past_courses(rs, pevent_id)
            for pevent_id in pevent_ids}
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['pevent_id'] = csv_position.pop('event', -1)
        csv_position['pcourse_id'] = csv_position.get('course', -1)
        return self.render(rs, "batch_admission", {
            'data': data, 'pevents': pevents, 'pcourses': pcourses,
            'csvfields': csv_position})

    def examine_for_admission(self, rs: RequestState, datum: CdEDBObject
                              ) -> CdEDBObject:
        """Check one line of batch admission.

        We test for fitness of the data itself, as well as possible
        existing duplicate accounts.

        :returns: The processed input datum.
        """
        warnings: List[Error] = []
        problems: List[Error]

        # short-circuit if additional fields like the resolution are error prone
        problems = [
            (field, error)
            for error_field, error in rs.retrieve_validation_errors() for field in datum
            if error_field == f"{field}{datum['lineno']}"]
        if problems:
            datum['problems'] = problems
            return datum

        if datum['old_hash'] and datum['old_hash'] != datum['new_hash']:
            # reset resolution in case of a change
            datum['resolution'] = LineResolutions.none
            rs.values[f"resolution{datum['lineno']}"] = LineResolutions.none
            warnings.append((None, ValueError(n_("Entry changed."))))
        persona = copy.deepcopy(datum['raw'])
        # Adapt input of gender from old convention (this is the format
        # used by external processes, i.e. BuB)
        gender_convert = {
            "0": str(const.Genders.other.value),
            "1": str(const.Genders.male.value),
            "2": str(const.Genders.female.value),
            "3": str(const.Genders.not_specified.value),
        }
        gender = persona.get('gender') or "3"
        persona['gender'] = gender_convert.get(
            gender.strip(), str(const.Genders.not_specified.value))
        del persona['event']
        del persona['course']
        persona.update({
            'is_cde_realm': True,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_member': True,
            'display_name': persona['given_names'],
            'trial_member': False,
            'paper_expuls': True,
            'bub_search': False,
            'decided_search': False,
            'notes': None,
            'country2': self.conf["DEFAULT_COUNTRY"],
        })
        if not (persona.get('country') and persona['country'].strip()):
            persona['country'] = self.conf["DEFAULT_COUNTRY"]
        merge_dicts(persona, PERSONA_DEFAULTS)
        persona, problems = validate_check(
            vtypes.Persona, persona, argname="persona", creation=True)
        if persona and (persona['birthday'] > deduct_years(now().date(), 10)):
            problems.extend([('birthday', ValueError(
                n_("Persona is younger than 10 years.")))])

        pevent_id, w, p = self.pasteventproxy.find_past_event(rs, datum['raw']['event'])
        warnings.extend(w)
        problems.extend(p)
        pcourse_id = None
        if datum['raw']['course'] and pevent_id:
            pcourse_id, w, p = self.pasteventproxy.find_past_course(
                rs, datum['raw']['course'], pevent_id)
            warnings.extend(w)
            problems.extend(p)
        else:
            warnings.append(("course", ValueError(n_("No course available."))))

        doppelgangers: CdEDBObjectMap = {}
        if persona:
            if (datum['resolution'] == LineResolutions.create
                    and self.coreproxy.verify_existence(rs, persona['username'])
                    and not bool(datum['doppelganger_id'])):
                problems.append(
                    ("persona", ValueError(n_("Email address already taken."))))
            temp = copy.deepcopy(persona)
            temp['id'] = 1
            doppelgangers = self.coreproxy.find_doppelgangers(rs, temp)
        if doppelgangers:
            warnings.append(("persona", ValueError(n_("Doppelgangers found."))))
        if bool(datum['doppelganger_id']) != datum['resolution'].is_modification():
            problems.append(
                ("doppelganger",
                 RuntimeError(n_("Doppelganger choice doesn’t fit resolution."))))
        if datum['doppelganger_id']:
            if datum['doppelganger_id'] not in doppelgangers:
                problems.append(
                    ("doppelganger", KeyError(n_("Doppelganger unavailable."))))
            else:
                dg = doppelgangers[datum['doppelganger_id']]
                if (
                    persona
                    and dg['username'] != persona['username']
                    and self.coreproxy.verify_existence(rs, persona['username'])
                ):
                    warnings.append(
                        ("doppelganger", ValueError(n_("Email address already taken."))))
                if not dg['is_cde_realm']:
                    warnings.append(
                        ("doppelganger",
                         ValueError(n_("Doppelganger will upgrade to CdE."))))
                    if not datum['resolution'].do_update():
                        if dg['is_event_realm']:
                            warnings.append(
                                ("doppelganger",
                                 ValueError(n_("Unmodified realm upgrade."))))
                        else:
                            problems.append(
                                ("doppelganger",
                                 ValueError(n_("Missing data for realm upgrade."))))
        if datum['doppelganger_id'] and pevent_id:
            existing = self.pasteventproxy.list_participants(rs, pevent_id=pevent_id)
            if (datum['doppelganger_id'], pcourse_id) in existing:
                problems.append(
                    ("pevent_id", KeyError(n_("Participation already recorded."))))

        datum.update({
            'persona': persona,
            'pevent_id': pevent_id,
            'pcourse_id': pcourse_id,
            'doppelgangers': doppelgangers,
            'warnings': warnings,
            'problems': problems,
        })
        return datum

    def _perform_one_batch_admission(self, rs: RequestState, datum: CdEDBObject,
                                     trial_membership: bool, consent: bool
                                     ) -> int:
        """Uninlined code from perform_batch_admission().

        :returns: number of created accounts (0 or 1)
        """
        ret = 0
        batch_fields = (
            'family_name', 'given_names', 'title', 'name_supplement',
            'birth_name', 'gender', 'address_supplement', 'address',
            'postal_code', 'location', 'country', 'telephone',
            'mobile', 'birthday')  # email omitted as it is handled separately
        if datum['resolution'] == LineResolutions.skip:
            return ret
        elif datum['resolution'] == LineResolutions.create:
            new_persona = copy.deepcopy(datum['persona'])
            new_persona.update({
                'is_member': True,
                'trial_member': trial_membership,
                'paper_expuls': True,
                'is_searchable': consent,
            })
            persona_id = self.coreproxy.create_persona(rs, new_persona)
            ret = 1
        elif datum['resolution'].is_modification():
            persona_id = datum['doppelganger_id']
            current = self.coreproxy.get_persona(rs, persona_id)
            if not current['is_cde_realm']:
                # Promote to cde realm dependent on current realm
                promotion: CdEDBObject = {field: None for field in CDE_TRANSITION_FIELDS}
                # The ream independent upgrades of the persona. They are applied at last
                # to prevent unintentional overrides
                upgrades = {
                    'is_cde_realm': True,
                    'is_event_realm': True,
                    'is_assembly_realm': True,
                    'is_ml_realm': True,
                    'decided_search': False,
                    'trial_member': False,
                    'paper_expuls': True,
                    'bub_search': False,
                    'id': persona_id,
                }
                # This applies a part of the newly imported data necessary for realm
                # transition. The remaining data will be updated later.
                mandatory_fields = {
                    field for field, validator in CDE_TRANSITION_FIELDS.items()
                    if field not in upgrades and not is_optional(validator)
                }
                assert mandatory_fields <= set(batch_fields)
                if not current['is_event_realm']:
                    if not datum['resolution'].do_update():
                        raise RuntimeError(n_("Need extra data."))
                    for field in mandatory_fields:
                        promotion[field] = datum['persona'][field]
                else:
                    current = self.coreproxy.get_event_user(rs, persona_id)
                    # take care that we do not override existent data
                    current_fields = {
                        field for field in CDE_TRANSITION_FIELDS
                        if current.get(field) is not None
                    }
                    for field in current_fields:
                        promotion[field] = current[field]
                    for field in mandatory_fields:
                        if promotion[field] is None:
                            promotion[field] = datum['persona'][field]
                # apply the actual changes
                promotion.update(upgrades)
                self.coreproxy.change_persona_realms(rs, promotion)
            if datum['resolution'].do_trial():
                self.coreproxy.change_membership(
                    rs, datum['doppelganger_id'], is_member=True)
                update = {
                    'id': datum['doppelganger_id'],
                    'trial_member': True,
                }
                self.coreproxy.change_persona(
                    rs, update, may_wait=False,
                    change_note="Probemitgliedschaft erneuert.")
            if datum['resolution'].do_update():
                self.coreproxy.change_username(
                    rs, persona_id, datum['persona']['username'], password=None)
                update = {'id': datum['doppelganger_id']}
                for field in batch_fields:
                    update[field] = datum['persona'][field]
                self.coreproxy.change_persona(
                    rs, update, may_wait=True, force_review=True,
                    change_note="Import aktualisierter Daten.")
        else:
            raise RuntimeError(n_("Impossible."))
        if datum['pevent_id'] and persona_id:
            self.pasteventproxy.add_participant(
                rs, datum['pevent_id'], datum['pcourse_id'], persona_id,
                is_instructor=datum['is_instructor'], is_orga=datum['is_orga'])
        return ret

    def perform_batch_admission(self, rs: RequestState, data: List[CdEDBObject],
                                trial_membership: bool, consent: bool,
                                sendmail: bool) -> Tuple[bool, Optional[int]]:
        """Resolve all entries in the batch admission form.

        :returns: Success information and for positive outcome the
          number of created accounts or for negative outcome the line
          where an exception was triggered or None if it was a DB
          serialization error.
        """
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                for index, datum in enumerate(data, start=1):
                    count += self._perform_one_batch_admission(
                        rs, datum, trial_membership, consent)
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None
        except Exception:
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during batch creation",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index
        # Send mail after the transaction succeeded
        if sendmail:
            for datum in data:
                if datum['resolution'] == LineResolutions.create:
                    success, message = self.coreproxy.make_reset_cookie(
                        rs, datum['raw']['username'],
                        timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
                    email = self.encode_parameter(
                        "core/do_password_reset_form", "email",
                        datum['raw']['username'],
                        persona_id=None,
                        timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
                    meta_info = self.coreproxy.get_meta_info(rs)
                    self.do_mail(rs, "welcome",
                                 {'To': (datum['raw']['username'],),
                                  'Subject': "Aufnahme in den CdE",
                                  },
                                 {'data': datum['persona'],
                                  'fee': self.conf["MEMBERSHIP_FEE"],
                                  'email': email if success else "",
                                  'cookie': message if success else "",
                                  'meta_info': meta_info,
                                  })
        return True, count

    @staticmethod
    def similarity_score(ds1: CdEDBObject, ds2: CdEDBObject) -> str:
        """Helper to determine similar input lines.

        This is separate from the detection of existing accounts, and
        can happen because of some human error along the way.

        :returns: One of "high", "medium" and "low" indicating similarity.
        """
        score = 0
        if (ds1['raw']['given_names'] == ds2['raw']['given_names']
                and ds1['raw']['family_name'] == ds2['raw']['family_name']):
            score += 12
        if ds1['raw']['username'] == ds2['raw']['username']:
            score += 20
        if ds1['raw']['birthday'] == ds2['raw']['birthday']:
            score += 8
        if score >= 20:
            return "high"
        elif score >= 10:
            return "medium"
        else:
            return "low"

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("membership", "trial_membership", "consent", "sendmail",
                 "finalized", "accounts")
    def batch_admission(self, rs: RequestState, membership: bool,
                        trial_membership: bool, consent: bool, sendmail: bool,
                        finalized: bool, accounts: str) -> Response:
        """Make a lot of new accounts.

        This is rather involved to make this job easier for the administration.

        The additional parameters membership, trial_membership, consent
        and sendmail modify the behaviour and can be selected by the
        user. Note however, that membership currently must be ``True``.

        The internal parameter finalized is used to explicitly signal at
        what point account creation will happen.
        """
        accounts = accounts or ''
        accountlines = accounts.splitlines()
        fields = (
            'event', 'course', 'family_name', 'given_names', 'title',
            'name_supplement', 'birth_name', 'gender', 'address_supplement',
            'address', 'postal_code', 'location', 'country', 'telephone',
            'mobile', 'username', 'birthday')
        reader = csv.DictReader(
            accountlines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        total_account_number = 0
        for lineno, raw_entry in enumerate(reader):
            total_account_number += 1
            dataset: CdEDBObject = {'raw': raw_entry}
            params: TypeMapping = {
                # as on the first submit no values for the resolution are transmitted,
                # we have to cast None -> LineResolutions.none after extraction
                f"resolution{lineno}": Optional[LineResolutions],  # type: ignore
                f"doppelganger_id{lineno}": Optional[vtypes.ID],  # type: ignore
                f"hash{lineno}": Optional[str],  # type: ignore
                f"is_orga{lineno}": Optional[bool],  # type: ignore
                f"is_instructor{lineno}": Optional[bool],  # type: ignore
            }
            tmp = request_extractor(rs, params)
            if tmp[f"resolution{lineno}"] is None:
                tmp[f"resolution{lineno}"] = LineResolutions.none

            dataset['resolution'] = tmp[f"resolution{lineno}"]
            dataset['doppelganger_id'] = tmp[f"doppelganger_id{lineno}"]
            dataset['is_orga'] = tmp[f"is_orga{lineno}"]
            dataset['is_instructor'] = tmp[f"is_instructor{lineno}"]
            dataset['old_hash'] = tmp[f"hash{lineno}"]
            dataset['new_hash'] = get_hash(accountlines[lineno].encode())
            rs.values[f"hash{lineno}"] = dataset['new_hash']
            dataset['lineno'] = lineno
            data.append(self.examine_for_admission(rs, dataset))

        if rs.has_validation_errors():
            return self.batch_admission_form(rs, data=data, csvfields=fields)

        for ds1, ds2 in itertools.combinations(data, 2):
            similarity = self.similarity_score(ds1, ds2)
            if similarity == "high":
                # note that we 0-indexed our lines internally but present them 1-indexed
                # to the user. So, we need to increase the line number here manually.
                problem = (None, ValueError(
                    n_("Lines %(first)s and %(second)s are the same."),
                    {'first': ds1['lineno']+1, 'second': ds2['lineno']+1}))
                ds1['problems'].append(problem)
                ds2['problems'].append(problem)
            elif similarity == "medium":
                warning = (None, ValueError(
                    n_("Lines %(first)s and %(second)s look the same."),
                    {'first': ds1['lineno'], 'second': ds2['lineno']}))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
            elif similarity == "low":
                pass
            else:
                raise RuntimeError(n_("Impossible."))

        for dataset in data:
            if (dataset['resolution'] == LineResolutions.none
                    and not dataset['doppelgangers']
                    and not dataset['problems']
                    and not dataset['old_hash']):
                # automatically select resolution if this is an easy case
                dataset['resolution'] = LineResolutions.create
                rs.values[f"resolution{dataset['lineno']}"] = LineResolutions.create.value

        if total_account_number != len(accountlines):
            rs.append_validation_error(
                ("accounts", ValueError(n_("Lines didn’t match up."))))
        if not membership:
            rs.append_validation_error(
                ("membership", ValueError(n_("Only member admission supported."))))
        open_issues = any(
            e['resolution'] == LineResolutions.none
            or (e['problems'] and e['resolution'] != LineResolutions.skip)
            for e in data)
        if rs.has_validation_errors() or not data or open_issues:
            # force a new validation round if some errors came up
            rs.values['finalized'] = False
            return self.batch_admission_form(rs, data=data, csvfields=fields)
        if not finalized:
            rs.values['finalized'] = True
            return self.batch_admission_form(rs, data=data, csvfields=fields)

        # Here we have survived all validation
        success, num = self.perform_batch_admission(rs, data, trial_membership,
                                                    consent, sendmail)
        if success:
            rs.notify("success", n_("Created %(num)s accounts."), {'num': num})
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line %(num)s."),
                          {'num': num})
            return self.batch_admission_form(rs, data=data, csvfields=fields)

    @access("finance_admin")
    def parse_statement_form(self, rs: RequestState, data: CdEDBObject = None,
                             params: CdEDBObject = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or {}
        merge_dicts(rs.values, data)
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)
        event_entries = xsorted(
            [(event['id'], event['title']) for event in events.values()],
            key=lambda e: EntitySorter.event(events[e[0]]), reverse=True)
        params = {
            'params': params or None,
            'data': data,
            'TransactionType': parse.TransactionType,
            'event_entries': event_entries,
            'events': events,
        }
        return self.render(rs, "parse_statement", params)

    def organize_transaction_data(
            self, rs: RequestState, transactions: List[parse.Transaction],
            start: Optional[datetime.date], end: Optional[datetime.date],
            timestamp: datetime.datetime) -> Tuple[CdEDBObject, CdEDBObject]:
        """Organize transactions into data and params usable in the form."""

        get_persona = functools.partial(self.coreproxy.get_persona, rs)
        get_event = functools.partial(self.eventproxy.get_event, rs)

        data = {"{}{}".format(k, t.t_id): v
                for t in transactions
                for k, v in t.to_dict(get_persona, get_event).items()}
        data["count"] = len(transactions)
        data["start"] = start
        data["end"] = end
        data["timestamp"] = timestamp
        params: CdEDBObject = {
            "all": [],
            "has_error": [],
            "has_warning": [],
            "jump_order": {},
            "has_none": [],
            "accounts": defaultdict(int),
            "events": defaultdict(int),
            "memberships": 0,
        }
        prev_jump = None
        for t in transactions:
            params["all"].append(t.t_id)
            if t.errors or t.warnings:
                params["jump_order"][prev_jump] = t.t_id
                params["jump_order"][t.t_id] = None
                prev_jump = t.t_id
                if t.errors:
                    params["has_error"].append(t.t_id)
                else:
                    params["has_warning"].append(t.t_id)
            else:
                params["has_none"].append(t.t_id)
            params["accounts"][str(t.account)] += 1
            if t.event_id:
                params["events"][t.event_id] += 1
            if t.type == TransactionType.MembershipFee:
                params["memberships"] += 1
        return data, params

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("statement_file")
    def parse_statement(self, rs: RequestState,
                        statement_file: FileStorage) -> Response:
        """
        Parse the statement into multiple CSV files.

        Every transaction is matched to a TransactionType, as well as to a
        member and an event, if applicable.

        The transaction's reference is searched for DB-IDs.
        If found the associated persona is looked up and their given_names and
        family_name, and variations thereof, are compared to the transaction's
        reference.

        To match to an event, this compares the names of current events, and
        variations thereof, to the transacion's reference.

        Every match to Type, Member and Event is given a ConfidenceLevel, to be
        used on further validation.

        This uses POST because the expected data is too large for GET.
        """
        assert statement_file.filename is not None
        filename = pathlib.Path(statement_file.filename).parts[-1]
        start, end, timestamp = parse.dates_from_filename(filename)
        # The statements from BFS are encoded in latin-1
        statement_file = check(rs, vtypes.CSVFile, statement_file,
                               "statement_file", encoding="latin-1")
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)
        assert statement_file is not None
        statementlines = statement_file.splitlines()

        event_list = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_list)

        get_persona = functools.partial(self.coreproxy.get_persona, rs)

        # This does not use the cde csv dialect, but rather the bank's.
        reader = csv.DictReader(statementlines, delimiter=";",
                                quotechar='"',
                                fieldnames=parse.STATEMENT_CSV_FIELDS,
                                restkey=parse.STATEMENT_CSV_RESTKEY,
                                restval="")

        transactions = []

        for i, line in enumerate(reversed(list(reader))):
            if not len(line) == 23:
                p = ("statement_file",
                     ValueError(n_("Line %(lineno)s does not have "
                                   "the correct number of "
                                   "columns."),
                                {'lineno': i + 1}
                                ))
                rs.append_validation_error(p)
                continue
            line["id"] = i  # type: ignore
            t = parse.Transaction.from_csv(line)
            t.analyze(events, get_persona)
            t.inspect(get_persona)

            transactions.append(t)
        if rs.has_validation_errors():
            return self.parse_statement_form(rs)

        data, params = self.organize_transaction_data(
            rs, transactions, start, end, timestamp)

        return self.parse_statement_form(rs, data, params)

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("count", "start", "end", "timestamp", "validate", "event",
                 "membership", "excel", "gnucash", "ignore_warnings")
    def parse_download(self, rs: RequestState, count: int, start: datetime.date,
                       end: Optional[datetime.date],
                       timestamp: datetime.datetime, validate: str = None,
                       event: vtypes.ID = None, membership: str = None,
                       excel: str = None, gnucash: str = None,
                       ignore_warnings: bool = False) -> Response:
        """
        Provide data as CSV-Download with the given filename.

        This uses POST, because the expected filesize is too large for GET.
        """
        rs.ignore_validation_errors()

        def params_generator(i: int) -> TypeMapping:
            return {
                f"reference{i}": Optional[str],  # type: ignore
                f"account{i}": Accounts,
                f"statement_date{i}": datetime.date,
                f"amount{i}": decimal.Decimal,
                f"account_holder{i}": Optional[str],  # type: ignore
                f"posting{i}": str,
                f"iban{i}": Optional[vtypes.IBAN],  # type: ignore
                f"t_id{i}": vtypes.ID,
                f"transaction_type{i}": TransactionType,
                f"transaction_type_confidence{i}": int,
                f"transaction_type_confirm{i}": Optional[bool],  # type: ignore
                f"cdedbid{i}": Optional[vtypes.CdedbID],  # type: ignore
                f"persona_id_confidence{i}": Optional[int],  # type: ignore
                f"persona_id_confirm{i}": Optional[bool],  # type: ignore
                f"event_id{i}": Optional[vtypes.ID],  # type: ignore
                f"event_id_confidence{i}": Optional[int],  # type: ignore
                f"event_id_confirm{i}": Optional[bool],  # type: ignore
            }

        get_persona = functools.partial(self.coreproxy.get_persona, rs)
        get_event = functools.partial(self.eventproxy.get_event, rs)

        transactions = []
        for i in range(1, count + 1):
            t = request_extractor(rs, params_generator(i))
            t = parse.Transaction({k.rstrip(str(i)): v for k, v in t.items()})
            t.inspect(get_persona)
            transactions.append(t)

        data, params = self.organize_transaction_data(
            rs, transactions, start, end, timestamp)

        fields: Sequence[str]
        if validate is not None or params["has_error"] \
                or (params["has_warning"] and not ignore_warnings):
            return self.parse_statement_form(rs, data, params)
        elif membership is not None:
            filename = "Mitgliedsbeiträge"
            transactions = [t for t in transactions
                            if t.type == TransactionType.MembershipFee]
            fields = parse.MEMBERSHIP_EXPORT_FIELDS
            write_header = False
        elif event is not None:
            aux = int(event)
            event_data = self.eventproxy.get_event(rs, aux)
            filename = event_data["shortname"]
            transactions = [t for t in transactions
                            if t.event_id == aux
                            and t.type == TransactionType.EventFee]
            fields = parse.EVENT_EXPORT_FIELDS
            write_header = False
        elif gnucash is not None:
            filename = "gnucash"
            fields = parse.GNUCASH_EXPORT_FIELDS
            write_header = True
        elif excel is not None:
            account = excel
            filename = "transactions_" + account
            transactions = [t for t in transactions
                            if str(t.account) == account]
            fields = parse.EXCEL_EXPORT_FIELDS
            write_header = False
        else:
            rs.notify("error", n_("Unknown action."))
            return self.parse_statement_form(rs, data, params)
        if end is None:
            filename += "_{}".format(start)
        else:
            filename += "_{}_bis_{}.csv".format(start, end)
        csv_data = [t.to_dict(get_persona, get_event)
                    for t in transactions]
        csv_data = csv_output(csv_data, fields, write_header)
        return self.send_csv_file(rs, "text/csv", filename, data=csv_data)

    @access("finance_admin")
    def money_transfers_form(self, rs: RequestState,
                             data: List[CdEDBObject] = None,
                             csvfields: Tuple[str, ...] = None,
                             saldo: decimal.Decimal = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        defaults = {'sendmail': True}
        merge_dicts(rs.values, defaults)
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        return self.render(rs, "money_transfers", {
            'data': data, 'csvfields': csv_position, 'saldo': saldo,
        })

    def examine_money_transfer(self, rs: RequestState, datum: CdEDBObject
                               ) -> CdEDBObject:
        """Check one line specifying a money transfer.

        We test for fitness of the data itself.

        :returns: The processed input datum.
        """
        amount, problems = validate_check(
            vtypes.PositiveDecimal, datum['raw']['amount'], argname="amount")
        persona_id, p = validate_check(
            vtypes.CdedbID, datum['raw']['persona_id'].strip(),
            argname="persona_id")
        problems.extend(p)
        family_name, p = validate_check(
            str, datum['raw']['family_name'], argname="family_name")
        problems.extend(p)
        given_names, p = validate_check(
            str, datum['raw']['given_names'], argname="given_names")
        problems.extend(p)
        note, p = validate_check_optional(str, datum['raw']['note'], argname="note")
        problems.extend(p)

        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append(('persona_id',
                                 ValueError(
                                     n_("No Member with ID %(p_id)s found."),
                                     {'p_id': persona_id})))
            else:
                if persona['is_archived']:
                    problems.append(('persona_id',
                                     ValueError(n_("Persona is archived."))))
                if not persona['is_cde_realm']:
                    problems.append((
                        'persona_id',
                        ValueError(n_("Persona is not in CdE realm."))))

                if family_name is not None and not re.search(
                    diacritic_patterns(re.escape(family_name)),
                    persona['family_name'],
                    flags=re.IGNORECASE
                ):
                    problems.append(('family_name', ValueError(
                        n_("Family name doesn’t match."))))

                if given_names is not None and not re.search(
                    diacritic_patterns(re.escape(given_names)),
                    persona['given_names'],
                    flags=re.IGNORECASE
                ):
                    problems.append(('given_names', ValueError(
                        n_("Given names don’t match."))))
        datum.update({
            'persona_id': persona_id,
            'amount': amount,
            'note': note,
            'warnings': [],
            'problems': problems,
        })
        return datum

    def perform_money_transfers(
            self, rs: RequestState, data: List[CdEDBObject], sendmail: bool
    ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Resolve all entries in the money transfers form.

        :returns: A bool indicating success and:
            * In case of success:
                * The number of recorded transactions
                * The number of new members.
            * In case of error:
                * The index of the erronous line or None
                    if a DB-serialization error occurred.
                * None
        """
        index = 0
        note_template = ("Guthabenänderung um {amount} auf {new_balance} "
                         "(Überwiesen am {date})")
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                memberships_gained = 0
                persona_ids = tuple(e['persona_id'] for e in data)
                personas = self.coreproxy.get_total_personas(rs, persona_ids)
                for index, datum in enumerate(data):
                    assert isinstance(datum['amount'], decimal.Decimal)
                    new_balance = (personas[datum['persona_id']]['balance']
                                   + datum['amount'])
                    note = datum['note']
                    if note:
                        try:
                            date = datetime.datetime.strptime(
                                note, parse.OUTPUT_DATEFORMAT)
                        except ValueError:
                            pass
                        else:
                            # This is the default case and makes it pretty
                            note = note_template.format(
                                amount=money_filter(datum['amount']),
                                new_balance=money_filter(new_balance),
                                date=date.strftime(parse.OUTPUT_DATEFORMAT))
                    count += self.coreproxy.change_persona_balance(
                        rs, datum['persona_id'], new_balance,
                        const.FinanceLogCodes.increase_balance,
                        change_note=note)
                    if new_balance >= self.conf["MEMBERSHIP_FEE"]:
                        memberships_gained += self.coreproxy.change_membership(
                            rs, datum['persona_id'], is_member=True)
                    # Remember the changed balance in case of multiple transfers.
                    personas[datum['persona_id']]['balance'] = new_balance
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None, None
        except Exception:
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index, None
        if sendmail:
            for datum in data:
                persona = personas[datum['persona_id']]
                self.do_mail(rs, "transfer_received",
                             {'To': (persona['username'],),
                              'Subject': "Überweisung eingegangen",
                              },
                             {'persona': persona,
                              'address': make_postal_address(persona),
                              'new_balance': persona['balance']})
        return True, count, memberships_gained

    @access("finance_admin", modi={"POST"})
    @REQUESTfile("transfers_file")
    @REQUESTdata("sendmail", "transfers", "checksum")
    def money_transfers(self, rs: RequestState, sendmail: bool,
                        transfers: Optional[str], checksum: Optional[str],
                        transfers_file: Optional[FileStorage]
                        ) -> Response:
        """Update member balances.

        The additional parameter sendmail modifies the behaviour and can
        be selected by the user.

        The internal parameter checksum is used to guard against data
        corruption and to explicitly signal at what point the data will
        be committed (for the second purpose it works like a boolean).
        """
        transfers_file = check_optional(
            rs, vtypes.CSVFile, transfers_file, "transfers_file")
        if rs.has_validation_errors():
            return self.money_transfers_form(rs)
        if transfers_file and transfers:
            rs.notify("warning", n_("Only one input method allowed."))
            return self.money_transfers_form(rs)
        elif transfers_file:
            rs.values["transfers"] = transfers_file
            transfers = transfers_file
            transferlines = transfers_file.splitlines()
        elif transfers:
            transferlines = transfers.splitlines()
        else:
            rs.notify("error", n_("No input provided."))
            return self.money_transfers_form(rs)
        fields = ('amount', 'persona_id', 'family_name', 'given_names', 'note')
        reader = csv.DictReader(
            transferlines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        for lineno, raw_entry in enumerate(reader):
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno + 1}
            data.append(self.examine_money_transfer(rs, dataset))
        for ds1, ds2 in itertools.combinations(data, 2):
            if ds1['persona_id'] and ds1['persona_id'] == ds2['persona_id']:
                warning = (None, ValueError(
                    n_("More than one transfer for this account "
                       "(lines %(first)s and %(second)s)."),
                    {'first': ds1['lineno'], 'second': ds2['lineno']}))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
        if len(data) != len(transferlines):
            rs.append_validation_error(
                ("transfers", ValueError(n_("Lines didn’t match up."))))
        open_issues = any(e['problems'] for e in data)
        saldo = cast(decimal.Decimal,
                     sum(e['amount'] for e in data if e['amount']))
        if rs.has_validation_errors() or not data or open_issues:
            rs.values['checksum'] = None
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)
        current_checksum = get_hash(transfers.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)

        # Here validation is finished
        success, num, new_members = self.perform_money_transfers(
            rs, data, sendmail)
        if success:
            rs.notify("success", n_("Committed %(num)s transfers. "
                                    "There were %(new_members)s new members."),
                      {'num': num, 'new_members': new_members})
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line %(num)s."),
                          {'num': num + 1})
            return self.money_transfers_form(rs, data=data, csvfields=fields,
                                             saldo=saldo)

    def determine_open_permits(self, rs: RequestState,
                               lastschrift_ids: Collection[int] = None
                               ) -> Set[int]:
        """Find ids, which to debit this period.

        Helper to find out which of the passed lastschrift permits has
        not been debited for a year.

        :param lastschrift_ids: If None is passed all existing permits
          are checked.
        """
        if lastschrift_ids is None:
            lastschrift_ids = self.cdeproxy.list_lastschrift(rs).keys()
        stati = const.LastschriftTransactionStati
        period = self.cdeproxy.current_period(rs)
        periods = tuple(range(period - self.conf["PERIODS_PER_YEAR"] + 1,
                              period + 1))
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=lastschrift_ids, periods=periods,
            stati=(stati.success, stati.issued, stati.skipped))
        return set(lastschrift_ids) - set(transaction_ids.values())

    @access("finance_admin")
    def lastschrift_index(self, rs: RequestState) -> Response:
        """General lastschrift overview.

        This presents open items as well as all permits.
        """
        lastschrift_ids = self.cdeproxy.list_lastschrift(rs)
        lastschrifts = self.cdeproxy.get_lastschrifts(
            rs, lastschrift_ids.keys())
        all_lastschrift_ids = self.cdeproxy.list_lastschrift(rs, active=None)
        all_lastschrifts = self.cdeproxy.get_lastschrifts(
            rs, all_lastschrift_ids.keys())
        period = self.cdeproxy.current_period(rs)
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, periods=(period,),
            stati=(const.LastschriftTransactionStati.issued,))
        transactions = self.cdeproxy.get_lastschrift_transactions(
            rs, transaction_ids.keys())
        persona_ids = set(all_lastschrift_ids.values()).union({
            x['submitted_by'] for x in lastschrifts.values()})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        open_permits = self.determine_open_permits(rs, lastschrift_ids)
        for lastschrift in lastschrifts.values():
            lastschrift['open'] = lastschrift['id'] in open_permits
        last_order = xsorted(
            lastschrifts.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[lastschrifts[anid]['persona_id']]))
        lastschrifts = OrderedDict(
            (last_id, lastschrifts[last_id]) for last_id in last_order)
        return self.render(rs, "lastschrift_index", {
            'lastschrifts': lastschrifts, 'personas': personas,
            'transactions': transactions, 'all_lastschrifts': all_lastschrifts})

    @access("member", "finance_admin")
    def lastschrift_show(self, rs: RequestState, persona_id: int) -> Response:
        """Display all lastschrift information for one member.

        Especially all permits and transactions.
        """
        if not (persona_id == rs.user.persona_id
                or "finance_admin" in rs.user.roles):
            raise werkzeug.exceptions.Forbidden()
        lastschrift_ids = self.cdeproxy.list_lastschrift(
            rs, persona_ids=(persona_id,), active=None)
        lastschrifts = self.cdeproxy.get_lastschrifts(rs,
                                                      lastschrift_ids.keys())
        transactions: CdEDBObjectMap = {}
        if lastschrifts:
            transaction_ids = self.cdeproxy.list_lastschrift_transactions(
                rs, lastschrift_ids=lastschrift_ids.keys())
            transactions = self.cdeproxy.get_lastschrift_transactions(
                rs, transaction_ids.keys())
        persona_ids = {persona_id}.union({
            x['submitted_by'] for x in lastschrifts.values()}).union(
            {x['submitted_by'] for x in transactions.values()})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        active_permit = None
        for lastschrift in lastschrifts.values():
            if not lastschrift['revoked_at']:
                active_permit = lastschrift['id']
        active_open = bool(
            active_permit and self.determine_open_permits(rs, (active_permit,)))
        return self.render(rs, "lastschrift_show", {
            'lastschrifts': lastschrifts,
            'active_permit': active_permit, 'active_open': active_open,
            'personas': personas, 'transactions': transactions,
        })

    @access("finance_admin")
    def lastschrift_change_form(self, rs: RequestState, lastschrift_id: int
                                ) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['lastschrift'])
        persona = self.coreproxy.get_persona(
            rs, rs.ambience['lastschrift']['persona_id'])
        return self.render(rs, "lastschrift_change", {'persona': persona})

    @access("finance_admin", modi={"POST"})
    @REQUESTdatadict(*LASTSCHRIFT_COMMON_FIELDS)
    def lastschrift_change(self, rs: RequestState, lastschrift_id: int,
                           data: CdEDBObject) -> Response:
        """Modify one permit."""
        data['id'] = lastschrift_id
        data = check(rs, vtypes.Lastschrift, data)
        if rs.has_validation_errors():
            return self.lastschrift_change_form(rs, lastschrift_id)
        assert data is not None
        code = self.cdeproxy.set_lastschrift(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': rs.ambience['lastschrift']['persona_id']})

    @access("finance_admin")
    def lastschrift_create_form(self, rs: RequestState, persona_id: int = None
                                ) -> Response:
        """Render form."""
        return self.render(rs, "lastschrift_create")

    @access("finance_admin", modi={"POST"})
    @REQUESTdatadict(*LASTSCHRIFT_COMMON_FIELDS)
    @REQUESTdata('persona_id')
    def lastschrift_create(self, rs: RequestState, persona_id: vtypes.CdedbID,
                           data: CdEDBObject) -> Response:
        """Create a new permit."""
        data['persona_id'] = persona_id
        data = check(rs, vtypes.Lastschrift, data, creation=True)
        if rs.has_validation_errors():
            return self.lastschrift_create_form(rs, persona_id)
        assert data is not None
        if self.cdeproxy.list_lastschrift(
                rs, persona_ids=(persona_id,), active=True):
            rs.notify("error", n_("Multiple active permits are disallowed."))
            return self.redirect(rs, "cde/lastschrift_show", {
                'persona_id': persona_id})
        new_id = self.cdeproxy.create_lastschrift(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(
            rs, "cde/lastschrift_show", {'persona_id': persona_id})

    @access("finance_admin", modi={"POST"})
    def lastschrift_revoke(self, rs: RequestState, lastschrift_id: int
                           ) -> Response:
        """Disable a permit."""
        if rs.has_validation_errors():
            return self.lastschrift_show(
                rs, rs.ambience['lastschrift']['persona_id'])
        data = {
            'id': lastschrift_id,
            'revoked_at': now(),
        }
        lastschrift = self.cdeproxy.get_lastschrift(rs, lastschrift_id)
        persona_id = lastschrift['persona_id']
        code = self.cdeproxy.set_lastschrift(rs, data)
        self.notify_return_code(rs, code, success=n_("Permit revoked."))
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=(lastschrift_id,),
            stati=(const.LastschriftTransactionStati.issued,))
        if transaction_ids:
            subject = glue("Einzugsermächtigung zu ausstehender Lastschrift"
                           "widerrufen.")
            self.do_mail(rs, "pending_lastschrift_revoked",
                         {'To': (self.conf["MANAGEMENT_ADDRESS"],),
                          'Subject': subject},
                         {'persona_id': persona_id})
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': rs.ambience['lastschrift']['persona_id']})

    def _calculate_payment_date(self) -> datetime.date:
        """Helper to calculate a payment date that is a valid TARGET2
        bankday.
        """
        payment_date = now().date() + self.conf["SEPA_PAYMENT_OFFSET"]

        # Before anything else: check whether we are on special easter days.
        easter = dateutil.easter.easter(payment_date.year)
        good_friday = easter - datetime.timedelta(days=2)
        easter_monday = easter + datetime.timedelta(days=1)
        if payment_date in (good_friday, easter_monday):
            payment_date = easter + datetime.timedelta(days=2)

        # First: check we are not on the weekend.
        if payment_date.isoweekday() == 6:
            payment_date += datetime.timedelta(days=2)
        elif payment_date.isoweekday() == 7:
            payment_date += datetime.timedelta(days=1)

        # Second: check we are not on some special day.
        if payment_date.day == 1 and payment_date.month in (1, 5):
            payment_date += datetime.timedelta(days=1)
        elif payment_date.month == 12 and payment_date.day == 25:
            payment_date += datetime.timedelta(days=2)
        elif payment_date.month == 12 and payment_date.day == 26:
            payment_date += datetime.timedelta(days=1)

        # Third: check whether the second step landed us on the weekend.
        if payment_date.isoweekday() == 6:
            payment_date += datetime.timedelta(days=2)
        elif payment_date.isoweekday() == 7:
            payment_date += datetime.timedelta(days=1)

        return payment_date

    def create_sepapain(self, rs: RequestState, transactions: List[CdEDBObject]
                        ) -> Optional[str]:
        """Create an XML document for submission to a bank.

        The relevant document is the EBICS (Electronic Banking Internet
        Communication Standard; http://www.ebics.de/index.php?id=77).

        This communicates our wish to withdraw funds from the
        participating members. Here we do all the dirty work to conform
        to the standard and produce an acceptable output.

        :param transactions: Transaction infos from the backend enriched by
          some additional attributes which are necessary.
        """
        sanitized_transactions = check(
            rs, vtypes.SepaTransactions, transactions)
        if rs.has_validation_errors():
            return None
        assert sanitized_transactions is not None
        sorted_transactions: Dict[str, List[CdEDBObject]] = {}
        for transaction in sanitized_transactions:
            sorted_transactions.setdefault(transaction['type'], []).append(
                transaction)
        message_id = "{:.6f}-{}".format(
            now().timestamp(),
            ''.join(random.choice(string.ascii_letters + string.digits)
                    for _ in range(10)))
        meta = {
            'message_id': message_id,
            'total_sum': sum(e['amount'] for e in transactions),
            'partial_sums': {key: sum(e['amount'] for e in value)
                             for key, value in sorted_transactions.items()},
            'count': len(transactions),
            'sender': {
                'name': self.conf["SEPA_SENDER_NAME"],
                'address': self.conf["SEPA_SENDER_ADDRESS"],
                'country': self.conf["SEPA_SENDER_COUNTRY"],
                'iban': self.conf["SEPA_SENDER_IBAN"],
                'glaeubigerid': self.conf["SEPA_GLAEUBIGERID"],
            },
            'payment_date': self._calculate_payment_date(),
        }
        meta = check(rs, vtypes.SepaMeta, meta)
        if rs.has_validation_errors():
            return None
        sepapain_file = self.fill_template(rs, "other", "pain.008.003.02", {
            'transactions': sorted_transactions, 'meta': meta})
        return sepapain_file

    @access("finance_admin")
    @REQUESTdata("lastschrift_id")
    def lastschrift_download_sepapain(
            self, rs: RequestState, lastschrift_id: Optional[vtypes.ID]) -> Response:
        """Provide the sepapain file without actually issueing the transactions.

        Creates and returns an XML-file for one lastschrift is a
        lastschrift_id is given. If it is None, then this creates the file
        for all open permits (c.f. :py:func:`determine_open_permits`).
        """
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        period = self.cdeproxy.current_period(rs)
        if lastschrift_id is None:
            all_ids = self.cdeproxy.list_lastschrift(rs)
            lastschrift_ids = tuple(self.determine_open_permits(
                rs, all_ids.keys()))
        else:
            lastschrift_ids = (lastschrift_id,)
            if not self.determine_open_permits(rs, lastschrift_ids):
                rs.notify("error", n_("Existing pending transaction."))
                return self.lastschrift_index(rs)

        lastschrifts = self.cdeproxy.get_lastschrifts(rs, lastschrift_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in lastschrifts.values()))

        new_transactions = []

        for lastschrift in lastschrifts.values():
            persona = personas[lastschrift['persona_id']]
            transaction = {
                'issued_at': now(),
                'lastschrift_id': lastschrift['id'],
                'period_id': period,
                'mandate_reference': lastschrift_reference(
                    persona['id'], lastschrift['id']),
                'amount': lastschrift['amount'],
                'iban': lastschrift['iban'],
                'type': "RCUR",  # TODO remove this, hardcode it in template
            }
            if (lastschrift['granted_at'].date()
                    >= self.conf["SEPA_INITIALISATION_DATE"]):
                transaction['mandate_date'] = lastschrift['granted_at'].date()
            else:
                transaction['mandate_date'] = self.conf["SEPA_CUTOFF_DATE"]
            if lastschrift['account_owner']:
                transaction['account_owner'] = lastschrift['account_owner']
            else:
                transaction['account_owner'] = "{} {}".format(
                    persona['given_names'], persona['family_name'])
            timestamp = "{:.6f}".format(now().timestamp())
            transaction['unique_id'] = "{}-{}".format(
                transaction['mandate_reference'], timestamp[-9:])
            transaction['subject'] = asciificator(glue(
                "{}, {}, {} I25+ Mitgliedsbeitrag u. Spende CdE e.V.",
                "z. Foerderung der Volks- u. Berufsbildung u.",
                "Studentenhilfe").format(
                cdedbid_filter(persona['id']), persona['family_name'],
                persona['given_names']))[:140]  # cut off bc of limit

            new_transactions.append(transaction)
        sepapain_file = self.create_sepapain(rs, new_transactions)
        if not sepapain_file:
            rs.notify("error", n_("Creation of SEPA-PAIN-file failed."))
            return self.lastschrift_index(rs)
        return self.send_file(rs, data=sepapain_file, inline=False,
                              filename="i25p_semester{}.xml".format(period))

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("lastschrift_id")
    def lastschrift_generate_transactions(
            self, rs: RequestState, lastschrift_id: Optional[vtypes.ID]) -> Response:
        """Issue direct debit transactions.

        This creates new transactions either for the lastschrift_id
        passed or if that is None, then for all open permits
        (c.f. :py:func:`determine_open_permits`).
        """
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        period = self.cdeproxy.current_period(rs)
        if not lastschrift_id:
            all_lids = self.cdeproxy.list_lastschrift(rs)
            lastschrift_ids = tuple(self.determine_open_permits(
                rs, all_lids.keys()))
        else:
            lastschrift_ids = (lastschrift_id,)
            if not self.determine_open_permits(rs, lastschrift_ids):
                rs.notify("error", n_("Existing pending transaction."))
                return self.lastschrift_index(rs)
        new_transactions = tuple(
            {
                'issued_at': now(),
                'lastschrift_id': anid,
                'period_id': period,
            } for anid in lastschrift_ids
        )
        transaction_ids = self.cdeproxy.issue_lastschrift_transaction_batch(
            rs, new_transactions, check_unique=True)
        if not transaction_ids:
            return self.lastschrift_index(rs)

        lastschrifts = self.cdeproxy.get_lastschrifts(
            rs, lastschrift_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in lastschrifts.values()))
        for lastschrift in lastschrifts.values():
            persona = personas[lastschrift['persona_id']]
            data = {
                'persona': persona,
                'payment_date': self._calculate_payment_date(),
                'amount': lastschrift['amount'],
                'iban': lastschrift['iban'],
                'account_owner': lastschrift['account_owner'],
                'mandate_reference': lastschrift_reference(
                    lastschrift['persona_id'], lastschrift['id']),
                'glaeubiger_id': self.conf["SEPA_GLAEUBIGERID"],
            }
            subject = "Anstehender Lastschrifteinzug Initiative 25+"
            self.do_mail(rs, "sepa_pre-notification",
                         {'To': (persona['username'],),
                          'Subject': subject},
                         {'data': data})
        rs.notify("success",
                  n_("%(num)s Direct Debits issued. Notification mails sent."),
                  {'num': len(transaction_ids)})
        return self.redirect(rs, "cde/lastschrift_index")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def lastschrift_skip(self, rs: RequestState, lastschrift_id: int,
                         persona_id: Optional[vtypes.ID]) -> Response:
        """Do not do a direct debit transaction for this year.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        success = self.cdeproxy.lastschrift_skip(rs, lastschrift_id)
        if not success:
            rs.notify("warning", n_("Unable to skip transaction."))
        else:
            rs.notify("success", n_("Skipped."))
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    def lastschrift_process_transaction(
            self, rs: RequestState, transaction_id: int,
            status: const.LastschriftTransactionStati) -> DefaultReturnCode:
        """Process one transaction and store the outcome."""
        tally = None
        if status == const.LastschriftTransactionStati.failure:
            tally = -self.conf["SEPA_ROLLBACK_FEE"]
        return self.cdeproxy.finalize_lastschrift_transaction(
            rs, transaction_id, status, tally=tally)

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("status", "persona_id")
    def lastschrift_finalize_transaction(
            self, rs: RequestState, lastschrift_id: int, transaction_id: int,
            status: const.LastschriftTransactionStati,
            persona_id: Optional[vtypes.ID]) -> Response:
        """Finish one transaction.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        code = self.lastschrift_process_transaction(rs, transaction_id, status)
        self.notify_return_code(rs, code)
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("transaction_ids", "success", "cancelled", "failure")
    def lastschrift_finalize_transactions(
            self, rs: RequestState, transaction_ids: Collection[vtypes.ID],
            success: Optional[bool], cancelled: Optional[bool], failure: Optional[bool]
            ) -> Response:
        """Finish many transaction."""
        if sum(1 for s in (success, cancelled, failure) if s) != 1:
            rs.append_validation_error(
                ("action", ValueError(n_("Wrong number of actions."))))
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        if not transaction_ids:
            rs.notify("warning", n_("No transactions selected."))
            return self.redirect(rs, "cde/lastschrift_index")
        status = None
        if success:
            status = const.LastschriftTransactionStati.success
        elif cancelled:
            status = const.LastschriftTransactionStati.cancelled
        elif failure:
            status = const.LastschriftTransactionStati.failure
        else:
            raise RuntimeError("Impossible.")
        code = 1
        with Atomizer(rs):
            for transaction_id in transaction_ids:
                code *= self.lastschrift_process_transaction(
                    rs, transaction_id, status)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/lastschrift_index")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def lastschrift_rollback_transaction(
            self, rs: RequestState, lastschrift_id: int, transaction_id: int,
            persona_id: Optional[vtypes.ID]) -> Response:
        """Revert a successful transaction.

        The user can cancel a direct debit transaction after the
        fact. So we have to deal with this possibility.
        """
        if rs.has_validation_errors():
            return self.lastschrift_index(rs)
        tally = -self.conf["SEPA_ROLLBACK_FEE"]
        code = self.cdeproxy.rollback_lastschrift_transaction(
            rs, transaction_id, tally)
        self.notify_return_code(rs, code)
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=(lastschrift_id,),
            stati=(const.LastschriftTransactionStati.issued,))
        if transaction_ids:
            subject = glue("Einzugsermächtigung zu ausstehender Lastschrift"
                           "widerrufen.")
            self.do_mail(rs, "pending_lastschrift_revoked",
                         {'To': (self.conf["MANAGEMENT_ADDRESS"],),
                          'Subject': subject},
                         {'persona_id': persona_id})
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    @access("finance_admin")
    def lastschrift_receipt(self, rs: RequestState, lastschrift_id: int,
                            transaction_id: int) -> Response:
        """Generate a donation certificate.

        This allows tax deductions.
        """
        transaction = rs.ambience['transaction']
        persona = self.coreproxy.get_cde_user(
            rs, rs.ambience['lastschrift']['persona_id'])
        addressee = make_postal_address(persona)
        if rs.ambience['lastschrift']['account_owner']:
            addressee[0] = rs.ambience['lastschrift']['account_owner']
        if rs.ambience['lastschrift']['account_address']:
            addressee = addressee[:1]
            addressee.extend(
                rs.ambience['lastschrift']['account_address'].split('\n'))
        # We do not support receipts or number conversion in other locales.
        lang = "de"
        words = (
            int_to_words(int(transaction['amount']), lang),
            int_to_words(int(transaction['amount'] * 100) % 100, lang))
        transaction['amount_words'] = words
        meta_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_receipt", {
            'meta_info': meta_info, 'persona': persona, 'addressee': addressee})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir) / 'workdir'
            work_dir.mkdir()
            with open(work_dir / "lastschrift_receipt.tex", 'w') as f:
                f.write(tex)
            logo_src = self.conf["REPOSITORY_PATH"] / "misc/cde-logo.jpg"
            shutil.copy(logo_src, work_dir / "cde-logo.jpg")
            errormsg = n_("LaTeX compiliation failed. "
                          "This might be due to special characters.")
            pdf = self.serve_complex_latex_document(
                rs, tmp_dir, 'workdir', "lastschrift_receipt.tex",
                errormsg=errormsg)
            if pdf:
                return pdf
            else:
                return self.redirect(
                    rs, "cde/lastschrift_show",
                    {"persona_id": rs.ambience['lastschrift']['persona_id']})

    @access("anonymous")
    def lastschrift_subscription_form_fill(self, rs: RequestState) -> Response:
        """Generate a form for configuring direct debit authorization.

        If we are not anonymous we prefill this with known information.
        """
        persona = None
        not_minor = False
        if rs.user.persona_id:
            persona = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            not_minor = not determine_age_class(
                persona['birthday'], now().date()).is_minor()
        return self.render(rs, "lastschrift_subscription_form_fill",
                           {"persona": persona, "not_minor": not_minor})

    @access("anonymous")
    @REQUESTdata("full_name", "db_id", "username", "not_minor", "address_supplement",
                 "address", "postal_code", "location", "country", "amount",
                 "iban", "account_holder")
    def lastschrift_subscription_form(
            self, rs: RequestState, full_name: Optional[str],
            db_id: Optional[vtypes.CdedbID], username: Optional[vtypes.Email],
            not_minor: bool, address_supplement: Optional[str], address: Optional[str],
            postal_code: Optional[vtypes.GermanPostalCode], location: Optional[str],
            country: Optional[str], amount: Optional[vtypes.PositiveDecimal],
            iban: Optional[vtypes.IBAN], account_holder: Optional[str]) -> Response:
        """Fill the direct debit authorization template with information."""

        if rs.has_validation_errors():
            return self.lastschrift_subscription_form_fill(rs)

        data = {
            "full_name": full_name or "",
            "db_id": db_id,
            "username": username or "",
            "not_minor": not_minor,
            "address_supplement": address_supplement or "",
            "address": address or "",
            "postal_code": postal_code or "",
            "location": location or "",
            "country": country or "",
            "amount": float(amount) if amount else None,
            "iban": iban or "",
            "account_holder": account_holder or "",
        }

        meta_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_subscription_form",
                                 {'meta_info': meta_info, 'data': data})
        errormsg = n_("Form could not be created. Please refrain from using "
                      "special characters if possible.")
        pdf = self.serve_latex_document(
            rs, tex, "lastschrift_subscription_form", errormsg=errormsg, runs=1)
        if pdf:
            return pdf
        else:
            return self.redirect(rs, "cde/lastschrift_subscription_form_fill")

    @periodic("forget_old_lastschrifts", period=7*24*4)
    def forget_old_lastschrifts(self, rs: RequestState, store: CdEDBObject
                                ) -> CdEDBObject:
        """Forget revoked and old lastschrifts."""
        lastschrift_ids = self.cdeproxy.list_lastschrift(
            rs, persona_ids=None, active=False)
        lastschrifts = self.cdeproxy.get_lastschrifts(rs, lastschrift_ids)

        count = 0
        deleted = []
        for ls_id, ls in lastschrifts.items():
            if "revoked_at" not in self.cdeproxy.delete_lastschrift_blockers(
                    rs, ls_id):
                try:
                    self.cdeproxy.delete_lastschrift(rs, ls_id, {"transactions"})
                except ValueError as e:
                    self.logger.error(
                        f"Deletion of lastschrift {ls_id} failed. {e}")
                else:
                    count += 1
                    deleted.append(ls_id)
        if count:
            self.logger.info(f"Deleted {count} old lastschrifts.")
            store.setdefault('deleted', []).extend(deleted)
        return store

    @access("anonymous")
    def i25p_index(self, rs: RequestState) -> Response:
        """Show information about 'Initiative 25+'."""
        return self.render(rs, "i25p_index")

    @access("finance_admin")
    def show_semester(self, rs: RequestState) -> Response:
        """Show information."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        period_history = self.cdeproxy.get_period_history(rs)
        if self.cdeproxy.may_start_semester_bill(rs):
            current_period_step = SemesterSteps.billing
        elif self.cdeproxy.may_start_semester_ejection(rs):
            current_period_step = SemesterSteps.ejection
        elif self.cdeproxy.may_start_semester_balance_update(rs):
            current_period_step = SemesterSteps.balance
        elif self.cdeproxy.may_advance_semester(rs):
            current_period_step = SemesterSteps.advance
        else:
            rs.notify("error", n_("Inconsistent semester state."))
            current_period_step = SemesterSteps.error
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        expuls_history = self.cdeproxy.get_expuls_history(rs)
        stats = self.cdeproxy.finance_statistics(rs)
        return self.render(rs, "show_semester", {
            'period': period, 'expuls': expuls, 'stats': stats,
            'period_history': period_history, 'expuls_history': expuls_history,
            'current_period_step': current_period_step,
        })

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("addresscheck", "testrun")
    def semester_bill(self, rs: RequestState, addresscheck: bool, testrun: bool
                      ) -> Response:
        """Send billing mail to all members and archival notification to inactive users.

        In case of a test run we send a single mail of each to the button presser.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "cde/show_semester")
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_bill(rs):
            rs.notify("error", n_("Billing already done."))
            return self.redirect(rs, "cde/show_semester")
        open_lastschrift = self.determine_open_permits(rs)
        meta_info = self.coreproxy.get_meta_info(rs)

        if rs.has_validation_errors():
            return self.show_semester(rs)

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def send_billing_mail(rrs: RequestState, rs: None = None) -> bool:
            """Send one billing mail and advance semester state."""
            with Atomizer(rrs):
                period = self.cdeproxy.get_period(rrs, period_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, period['billing_state'], is_member=True, is_archived=False)
                if testrun:
                    persona_id = rrs.user.persona_id
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or period['billing_done']:
                    if not period['billing_done']:
                        self.cdeproxy.finish_semester_bill(rrs, addresscheck)
                    return False
                period_update = {
                    'id': period_id,
                    'billing_state': persona_id,
                }
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                lastschrift_list = self.cdeproxy.list_lastschrift(
                    rrs, persona_ids=(persona_id,))
                lastschrift = None
                if lastschrift_list:
                    lastschrift = self.cdeproxy.get_lastschrift(
                        rrs, unwrap(lastschrift_list.keys()))
                    lastschrift['reference'] = lastschrift_reference(
                        persona['id'], lastschrift['id'])
                address = make_postal_address(persona)
                transaction_subject = make_membership_fee_reference(persona)
                endangered = (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                              and not persona['trial_member']
                              and not lastschrift)
                if endangered:
                    subject = "Mitgliedschaft verlängern"
                else:
                    subject = "Mitgliedschaft verlängert"
                period_update['billing_count'] = period['billing_count'] + 1
                if not testrun:
                    self.cdeproxy.set_period(rrs, period_update)

            # Send mail only if transaction completed successfully.
            self.do_mail(
                rrs, "billing",
                {'To': (persona['username'],),
                 'Subject': subject},
                {'persona': persona,
                 'fee': self.conf["MEMBERSHIP_FEE"],
                 'lastschrift': lastschrift,
                 'open_lastschrift': open_lastschrift,
                 'address': address,
                 'transaction_subject': transaction_subject,
                 'addresscheck': addresscheck,
                 'meta_info': meta_info})
            return not testrun

        def send_archival_notification(rrs: RequestState, rs: None = None) -> bool:
            """Send archival notifications to inactive accounts."""
            with Atomizer(rrs):
                period = self.cdeproxy.get_period(rrs, period_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, period['archival_notification_state'], is_member=None,
                    is_archived=False)
                if testrun:
                    persona_id = rrs.user.persona_id
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or period['archival_notification_done']:
                    if not period['archival_notification_done']:
                        self.cdeproxy.finish_archival_notification(rrs)
                    return False
                period_update = {
                    'id': period_id,
                    'archival_notification_state': persona_id,
                }
                is_archivable = self.coreproxy.is_persona_automatically_archivable(
                    rrs, persona_id)
                if is_archivable or testrun:
                    persona = self.coreproxy.get_persona(rrs, persona_id)
                    period_update['archival_notification_count'] = \
                        period['archival_notification_count'] + 1
                if not testrun:
                    self.cdeproxy.set_period(rrs, period_update)

            if is_archivable or testrun:
                self.do_mail(
                    rrs, "imminent_archival",
                    {'To': (persona['username'],),
                     'Subject': "Bevorstehende Löschung Deines"
                                " CdE-Datenbank-Accounts"},
                    {'persona': persona,
                     'fee': self.conf["MEMBERSHIP_FEE"],
                     'meta_info': meta_info})
            return not testrun

        Worker(self.conf, (send_billing_mail, send_archival_notification), rs).start()
        rs.notify("success", n_("Started sending billing mails."))
        rs.notify("success", n_("Started sending archival notifications."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_eject(self, rs: RequestState) -> Response:
        """Eject members without enough credit and archive inactive users."""
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_ejection(rs):
            rs.notify("error", n_("Wrong timing for ejection."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def eject_member(rrs: RequestState, rs: None = None) -> bool:
            """Check one member for ejection and advance semester state."""
            with Atomizer(rrs):
                period = self.cdeproxy.get_period(rrs, period_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, period['ejection_state'], is_member=True, is_archived=False)
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or period['ejection_done']:
                    if not period['ejection_done']:
                        self.cdeproxy.finish_semester_ejection(rrs)
                    return False
                period_update = {
                    'id': period_id,
                    'ejection_state': persona_id,
                }
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                do_eject = (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                            and not persona['trial_member'])
                if do_eject:
                    self.coreproxy.change_membership(rrs, persona_id,
                                                     is_member=False)
                    period_update['ejection_count'] = \
                        period['ejection_count'] + 1
                    period_update['ejection_balance'] = \
                        period['ejection_balance'] + persona['balance']
                    transaction_subject = make_membership_fee_reference(persona)
                    meta_info = self.coreproxy.get_meta_info(rrs)
                self.cdeproxy.set_period(rrs, period_update)
            if do_eject:
                self.do_mail(
                    rrs, "ejection",
                    {'To': (persona['username'],),
                     'Subject': "Austritt aus dem CdE e.V."},
                    {'persona': persona,
                     'fee': self.conf["MEMBERSHIP_FEE"],
                     'transaction_subject': transaction_subject,
                     'meta_info': meta_info})
            return True

        def automated_archival(rrs: RequestState, rs: None = None) -> bool:
            """Archive one inactive user if they are eligible."""
            with Atomizer(rrs):
                period = self.cdeproxy.get_period(rrs, period_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, period['archival_state'], is_member=False, is_archived=False)
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or period['archival_done']:
                    if not period['archival_done']:
                        self.cdeproxy.finish_automated_archival(rrs)
                    return False
                period_update = {
                    'id': period_id,
                    'archival_state': persona_id,
                }
                mail = None
                if self.coreproxy.is_persona_automatically_archivable(
                        rrs, persona_id, reference_date=period['billing_done']):
                    note = "Autmoatisch archiviert wegen Inaktivität."
                    try:
                        code = self.coreproxy.archive_persona(rrs, persona_id, note)
                    except ArchiveError as e:
                        self.logger.exception(f"Unexpected error during archival of"
                                              f" persona {persona_id}.")
                        # TODO: somehow combine all failures into a single mail.
                        #  This requires storing the ids somehow.
                        mail = self._create_mail(
                            text=f"Automated archival of persona {persona_id} failed"
                                 f" with ArchivalError:\n{e}",
                            headers={'Subject': "Automated Archival failure",
                                     'To': (rrs.user.username,)},
                            attachments=None)
                    else:
                        if code:
                            period_update['archival_count'] = \
                                period['archival_count'] + 1
                        else:
                            self.logger.error(
                                f"Automated archival of persona {persona_id} failed"
                                f" for unknown reasons.")
                            # TODO: combine all failures into a single mail. See above.
                            mail = self._create_mail(
                                text=f"Automated archival of persona {persona_id}"
                                     f" failed with unknown error.",
                                headers={'Subject': "Automated Archival failure",
                                         'To': (rrs.user.username,)},
                                attachments=None)
                self.cdeproxy.set_period(rrs, period_update)
            if mail is not None:
                self._send_mail(mail)
            return True

        Worker(self.conf, (eject_member, automated_archival), rs).start()
        rs.notify("success", n_("Started ejection."))
        rs.notify("success", n_("Started automated archival."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_balance_update(self, rs: RequestState) -> Response:
        """Deduct membership fees from all member accounts."""
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_balance_update(rs):
            rs.notify("error", n_("Wrong timing for balance update."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def update_balance(rrs: RequestState, rs: None = None) -> bool:
            """Update one members balance and advance state."""
            with Atomizer(rrs):
                period = self.cdeproxy.get_period(rrs, period_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, period['balance_state'], is_member=True, is_archived=False)
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or period['balance_done']:
                    if not period['balance_done']:
                        self.cdeproxy.finish_semester_balance_update(rrs)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                period_update = {
                    'id': period_id,
                    'balance_state': persona_id,
                }
                if (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                        and not persona['trial_member']):
                    # TODO maybe fail more gracefully here?
                    # Maybe set balance to 0 and send a mail or something.
                    raise ValueError(n_("Balance too low."))
                else:
                    if persona['trial_member']:
                        update = {
                            'id': persona_id,
                            'trial_member': False,
                        }
                        self.coreproxy.change_persona(
                            rrs, update,
                            change_note="Probemitgliedschaft beendet."
                        )
                        period_update['balance_trialmembers'] = \
                            period['balance_trialmembers'] + 1
                    else:
                        new_b = persona['balance'] - self.conf["MEMBERSHIP_FEE"]
                        note = "Mitgliedsbeitrag abgebucht ({}).".format(
                            money_filter(self.conf["MEMBERSHIP_FEE"]))
                        self.coreproxy.change_persona_balance(
                            rrs, persona_id, new_b,
                            const.FinanceLogCodes.deduct_membership_fee,
                            change_note=note)
                        new_total = (period['balance_total']
                                     + self.conf["MEMBERSHIP_FEE"])
                        period_update['balance_total'] = new_total
                self.cdeproxy.set_period(rrs, period_update)
                return True

        worker = Worker(self.conf, update_balance, rs)
        worker.start()
        rs.notify("success", n_("Started updating balance."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_advance(self, rs: RequestState) -> Response:
        """Proceed to next period."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['balance_done']:
            rs.notify("error", n_("Wrong timing for advancing the semester."))
            return self.redirect(rs, "cde/show_semester")
        self.cdeproxy.advance_semester(rs)
        rs.notify("success", n_("New period started."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("testrun", "skip")
    def expuls_addresscheck(self, rs: RequestState, testrun: bool, skip: bool
                            ) -> Response:
        """Send address check mail to all members.

        In case of a test run we send only a single mail to the button
        presser.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'cde/show_semester')

        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if expuls['addresscheck_done']:
            rs.notify("error", n_("Addresscheck already done."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def send_addresscheck(rrs: RequestState, rs: None = None) -> bool:
            """Send one address check mail and advance state."""
            with Atomizer(rrs):
                expuls = self.cdeproxy.get_expuls(rrs, expuls_id)
                persona_id = self.coreproxy.next_persona(
                    rrs, expuls['addresscheck_state'],
                    is_member=True, is_archived=False)
                if testrun:
                    persona_id = rrs.user.persona_id
                # We are finished if we reached the end or if this was previously done.
                if not persona_id or expuls['addresscheck_done']:
                    if not expuls['addresscheck_done']:
                        self.cdeproxy.finish_expuls_addresscheck(
                            rrs, skip=False)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                address = make_postal_address(persona)
                if not testrun:
                    expuls_update = {
                        'id': expuls_id,
                        'addresscheck_state': persona_id,
                        'addresscheck_count': expuls['addresscheck_count'] + 1,
                    }
                    self.cdeproxy.set_expuls(rrs, expuls_update)
            self.do_mail(
                rrs, "addresscheck",
                {'To': (persona['username'],),
                 'Subject': "Adressabfrage für den exPuls"},
                {'persona': persona, 'address': address})
            return not testrun

        if skip:
            self.cdeproxy.finish_expuls_addresscheck(rs, skip=True)
            rs.notify("success", n_("Not sending mail."))
        else:
            worker = Worker(self.conf, send_addresscheck, rs)
            worker.start()
            time.sleep(1)
            rs.notify("success", n_("Started sending mail."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def expuls_advance(self, rs: RequestState) -> Response:
        """Proceed to next expuls."""
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if rs.has_validation_errors():
            return self.show_semester(rs)
        if not expuls['addresscheck_done']:
            rs.notify("error", n_("Addresscheck not done."))
            return self.redirect(rs, "cde/show_semester")
        self.cdeproxy.create_expuls(rs)
        rs.notify("success", n_("New expuls started."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin")
    def institution_summary_form(self, rs: RequestState) -> Response:
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs)
        institutions = self.pasteventproxy.get_institutions(
            rs, institution_ids.keys())
        current = {
            "{}_{}".format(key, institution_id): value
            for institution_id, institution in institutions.items()
            for key, value in institution.items() if key != 'id'}
        merge_dicts(rs.values, current)
        is_referenced = set()
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids.keys())
        pevent_ids = self.pasteventproxy.list_past_events(rs)
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids.keys())
        for event in events.values():
            is_referenced.add(event['institution'])
        for pevent in pevents.values():
            is_referenced.add(pevent['institution'])
        return self.render(rs, "institution_summary", {
            'institutions': institutions, 'is_referenced': is_referenced})

    @access("cde_admin", modi={"POST"})
    def institution_summary(self, rs: RequestState) -> Response:
        """Manipulate organisations which are behind events."""
        institution_ids = self.pasteventproxy.list_institutions(rs)
        spec = {'title': str, 'shortname': str}
        institutions = process_dynamic_input(rs, institution_ids.keys(), spec)
        if rs.has_validation_errors():
            return self.institution_summary_form(rs)
        code = 1
        for institution_id, institution in institutions.items():
            if institution is None:
                code *= self.pasteventproxy.delete_institution(
                    rs, institution_id)
            elif institution_id < 0:
                code *= self.pasteventproxy.create_institution(rs, institution)
            else:
                with Atomizer(rs):
                    current = self.pasteventproxy.get_institution(
                        rs, institution_id)
                    # Do not update unchanged
                    if current != institution:
                        code *= self.pasteventproxy.set_institution(
                            rs, institution)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/institution_summary_form")

    def _process_participants(self, rs: RequestState, pevent_id: int,
                              pcourse_id: int = None, orgas_only: bool = False
                              ) -> Tuple[CdEDBObjectMap, CdEDBObjectMap, int]:
        """Helper to pretty up participation infos.

        The problem is, that multiple participations can be logged for a
        persona per event (easiest example multiple courses in multiple
        parts). So here we fuse these entries into one per persona.

        Additionally, this function takes care of privacy: Participants
        are removed from the result if they are not searchable and the viewing
        user is neither admin nor participant of the past event themselves.

        Note that the returned dict of participants is already sorted.

        :param pcourse_id: if not None, restrict to participants of this
          course
        :returns: This returns three things: the processed participants,
          the persona data sets of the participants and the number of
          redacted participants.
        """
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        # We are privileged to see other participants if we are admin (and have
        # the relevant admin view enabled) or participant by ourselves
        privileged = is_participant or "past_event" in rs.user.admin_views
        participants = {}
        personas: CdEDBObjectMap = {}
        extra_participants = 0
        if privileged or ("searchable" in rs.user.roles):
            persona_ids = {persona_id
                           for persona_id, _ in participant_infos.keys()}
            for persona_id in persona_ids:
                base_set = tuple(x for x in participant_infos.values()
                                 if x['persona_id'] == persona_id)
                entry: CdEDBObject = {
                    'pevent_id': pevent_id,
                    'persona_id': persona_id,
                    'is_orga': any(x['is_orga'] for x in base_set),
                    'pcourse_ids': tuple(x['pcourse_id'] for x in base_set),
                    'is_instructor': any(x['is_instructor'] for x in base_set
                                         if (x['pcourse_id'] == pcourse_id
                                             or not pcourse_id))}
                if pcourse_id and pcourse_id not in entry['pcourse_ids']:
                    # remove non-participants with respect to the relevant
                    # course if there is a relevant course
                    continue
                if orgas_only and not entry['is_orga']:
                    # remove non-orgas
                    continue
                participants[persona_id] = entry

            personas = self.coreproxy.get_personas(rs, participants.keys())
            participants = OrderedDict(xsorted(
                participants.items(),
                key=lambda x: EntitySorter.persona(personas[x[0]])))
        # Delete unsearchable participants if we are not privileged
        if not privileged:
            if participants:
                for anid, persona in personas.items():
                    if not persona['is_searchable'] or not persona['is_member']:
                        del participants[anid]
                        extra_participants += 1
            else:
                extra_participants = len(participant_infos)
        # Flag linkable user profiles (own profile + all searchable profiles
        # + all (if we are admin))
        for anid in participants:
            participants[anid]['viewable'] = (self.is_admin(rs)
                                              or anid == rs.user.persona_id)
        if "searchable" in rs.user.roles:
            for anid in participants:
                if (personas[anid]['is_searchable']
                        and personas[anid]['is_member']):
                    participants[anid]['viewable'] = True
        return participants, personas, extra_participants

    @access("cde_admin")
    def download_past_event_participantlist(self, rs: RequestState,
                                            pevent_id: int) -> Response:
        """Provide a download of a participant list for a past event."""
        query = Query(
            "qview_past_event_user", QUERY_SPECS['qview_past_event_user'],
            ("personas.id", "given_names", "family_name", "address",
             "address_supplement", "postal_code", "location", "country"),
            [("pevent_id", QueryOperators.equal, pevent_id), ],
            (("family_name", True), ("given_names", True),
             ("personas.id", True)))

        result = self.cdeproxy.submit_general_query(rs, query)
        fields: List[str] = []
        for csvfield in query.fields_of_interest:
            fields.extend(csvfield.split(','))
        csv_data = csv_output(result, fields)
        return self.send_csv_file(
            rs, data=csv_data, inline=False,
            filename="{}.csv".format(rs.ambience["pevent"]["shortname"]))

    @access("member", "cde_admin")
    def show_past_event(self, rs: RequestState, pevent_id: int) -> Response:
        """Display concluded event."""
        course_ids = self.pasteventproxy.list_past_courses(rs, pevent_id)
        courses = self.pasteventproxy.get_past_courses(rs, course_ids)
        institutions = self.pasteventproxy.list_institutions(rs)
        participants, personas, extra_participants = self._process_participants(
            rs, pevent_id)
        orgas, _, extra_orgas = self._process_participants(rs, pevent_id,
                                                           orgas_only=True)
        for p_id, p in participants.items():
            p['pcourses'] = {
                pc_id: {
                    k: courses[pc_id][k]
                    for k in ('id', 'title', 'nr')
                }
                for pc_id in p['pcourse_ids']
                if pc_id
            }
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        return self.render(rs, "show_past_event", {
            'courses': courses, 'personas': personas, 'institutions': institutions,
            'participants': participants, 'extra_participants': extra_participants,
            'orgas': orgas, 'extra_orgas': extra_orgas,
            'is_participant': is_participant,
        })

    @access("member", "cde_admin")
    def show_past_course(self, rs: RequestState, pevent_id: int,
                         pcourse_id: int) -> Response:
        """Display concluded course."""
        participants, personas, extra_participants = self._process_participants(
            rs, pevent_id, pcourse_id=pcourse_id)
        return self.render(rs, "show_past_course", {
            'participants': participants, 'personas': personas,
            'extra_participants': extra_participants})

    @access("member", "cde_admin")
    @REQUESTdata("institution_id")
    def list_past_events(self, rs: RequestState, institution_id: vtypes.ID = None
                         ) -> Response:
        """List all concluded events."""
        if rs.has_validation_errors():
            rs.notify('warning', n_("Institution parameter got lost."))
        events = self.pasteventproxy.list_past_events(rs)
        shortnames = {
            pevent_id: value['shortname']
            for pevent_id, value in
            self.pasteventproxy.get_past_events(rs, events).items()
        }
        stats = self.pasteventproxy.past_event_stats(rs)
        institution_ids = self.pasteventproxy.list_institutions(rs)
        if institution_id and institution_id not in institution_ids:
            raise werkzeug.exceptions.NotFound(n_("Invalid institution id."))

        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)

        # Generate (reverse) chronologically sorted list of past event ids
        stats_sorter = xsorted(stats, key=lambda x: events[x])
        stats_sorter.sort(key=lambda x: stats[x]['tempus'], reverse=True)
        # Bunch past events by years
        # Using idea from http://stackoverflow.com/a/8983196
        years: Dict[int, List[int]] = {}
        for anid in stats_sorter:
            if institution_id \
                    and stats[anid]['institution_id'] != institution_id:
                continue
            years.setdefault(stats[anid]['tempus'].year, []).append(anid)

        return self.render(rs, "list_past_events", {
            'events': events,
            'stats': stats,
            'years': years,
            'institutions': institutions,
            'institution_id': institution_id,
            'shortnames': shortnames,
        })

    @access("cde_admin")
    def change_past_event_form(self, rs: RequestState, pevent_id: int
                               ) -> Response:
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        merge_dicts(rs.values, rs.ambience['pevent'])
        return self.render(rs, "change_past_event", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_EVENT_FIELDS)
    def change_past_event(self, rs: RequestState, pevent_id: int,
                          data: CdEDBObject) -> Response:
        """Modify a concluded event."""
        data['id'] = pevent_id
        data = check(rs, vtypes.PastEvent, data)
        if rs.has_validation_errors():
            return self.change_past_event_form(rs, pevent_id)
        assert data is not None
        code = self.pasteventproxy.set_past_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin")
    def create_past_event_form(self, rs: RequestState) -> Response:
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        return self.render(rs, "create_past_event", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_EVENT_FIELDS)
    @REQUESTdata("courses")
    def create_past_event(self, rs: RequestState, courses: Optional[str],
                          data: CdEDBObject) -> Response:
        """Add new concluded event."""
        data = check(rs, vtypes.PastEvent, data, creation=True)
        thecourses: List[CdEDBObject] = []
        if courses:
            courselines = courses.split('\n')
            reader = csv.DictReader(
                courselines, fieldnames=("nr", "title", "description"),
                dialect=CustomCSVDialect())
            lineno = 0
            pcourse: Optional[CdEDBObject]
            for pcourse in reader:
                lineno += 1
                # This is a placeholder for validation and will be substituted
                # later. The typechecker expects a str here.
                assert pcourse is not None
                pcourse['pevent_id'] = "1"
                pcourse = check(rs, vtypes.PastCourse, pcourse, creation=True)
                if pcourse:
                    thecourses.append(pcourse)
                else:
                    rs.notify("warning", n_("Line %(lineno)s is faulty."),
                              {'lineno': lineno})
        if rs.has_validation_errors():
            return self.create_past_event_form(rs)
        assert data is not None
        with Atomizer(rs):
            new_id = self.pasteventproxy.create_past_event(rs, data)
            for course in thecourses:
                course['pevent_id'] = new_id
                self.pasteventproxy.create_past_course(rs, course)
        self.notify_return_code(rs, new_id, success=n_("Event created."))
        return self.redirect(rs, "cde/show_past_event", {'pevent_id': new_id})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def delete_past_event(self, rs: RequestState, pevent_id: int,
                          ack_delete: bool) -> Response:
        """Remove a past event."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_past_event(rs, pevent_id)

        code = self.pasteventproxy.delete_past_event(
            rs, pevent_id, cascade=("courses", "participants", "log"))
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/list_past_events")

    @access("cde_admin")
    def change_past_course_form(self, rs: RequestState, pevent_id: int,
                                pcourse_id: int) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['pcourse'])
        return self.render(rs, "change_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_COURSE_COMMON_FIELDS)
    def change_past_course(self, rs: RequestState, pevent_id: int,
                           pcourse_id: int, data: CdEDBObject) -> Response:
        """Modify a concluded course."""
        data['id'] = pcourse_id
        data = check(rs, vtypes.PastCourse, data)
        if rs.has_validation_errors():
            return self.change_past_course_form(rs, pevent_id, pcourse_id)
        assert data is not None
        code = self.pasteventproxy.set_past_course(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_course")

    @access("cde_admin")
    def create_past_course_form(self, rs: RequestState, pevent_id: int
                                ) -> Response:
        """Render form."""
        return self.render(rs, "create_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_COURSE_COMMON_FIELDS)
    def create_past_course(self, rs: RequestState, pevent_id: int,
                           data: CdEDBObject) -> Response:
        """Add new concluded course."""
        data['pevent_id'] = pevent_id
        data = check(rs, vtypes.PastCourse, data, creation=True)
        if rs.has_validation_errors():
            return self.create_past_course_form(rs, pevent_id)
        assert data is not None
        new_id = self.pasteventproxy.create_past_course(rs, data)
        self.notify_return_code(rs, new_id, success=n_("Course created."))
        return self.redirect(rs, "cde/show_past_course", {'pcourse_id': new_id})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def delete_past_course(self, rs: RequestState, pevent_id: int,
                           pcourse_id: int, ack_delete: bool) -> Response:
        """Delete a concluded course.

        This also deletes all participation information w.r.t. this course.
        """
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_past_course(rs, pevent_id, pcourse_id)

        code = self.pasteventproxy.delete_past_course(
            rs, pcourse_id, cascade=("participants",))
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("pcourse_id", "persona_ids", "is_instructor", "is_orga")
    def add_participants(self, rs: RequestState, pevent_id: int,
                         pcourse_id: Optional[vtypes.ID],
                         persona_ids: vtypes.CdedbIDList,
                         is_instructor: bool, is_orga: bool) -> Response:
        """Add participant to concluded event."""
        if rs.has_validation_errors():
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)

        # Check presence of valid event users for the given ids
        if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=None):
            rs.append_validation_error(
                ("persona_ids",
                 ValueError(n_("Some of these users do not exist."))))
        if not self.coreproxy.verify_personas(rs, persona_ids, {"event"}):
            rs.append_validation_error(
                ("persona_ids",
                 ValueError(n_("Some of these users are not event users."))))
        if rs.has_validation_errors():
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)

        code = 1
        # TODO: Check if participants are already present.
        for persona_id in persona_ids:
            code *= self.pasteventproxy.add_participant(
                rs, pevent_id, pcourse_id, persona_id, is_instructor, is_orga)
        self.notify_return_code(rs, code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course",
                                 {'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("persona_id", "pcourse_id")
    def remove_participant(self, rs: RequestState, pevent_id: int,
                           persona_id: vtypes.ID, pcourse_id: Optional[vtypes.ID]
                           ) -> Response:
        """Remove participant."""
        if rs.has_validation_errors():
            return self.show_past_event(rs, pevent_id)
        code = self.pasteventproxy.remove_participant(
            rs, pevent_id, pcourse_id, persona_id)
        self.notify_return_code(rs, code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course", {
                'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @access("member", "cde_admin")
    def view_misc(self, rs: RequestState) -> Response:
        """View miscellaneos things."""
        meta_data = self.coreproxy.get_meta_info(rs)
        cde_misc = (meta_data.get("cde_misc")
                    or rs.gettext("*Nothing here yet.*"))
        return self.render(rs, "view_misc", {"cde_misc": cde_misc})

    @access("cde_admin")
    @REQUESTdata(*LOG_FIELDS_COMMON)
    def view_cde_log(self, rs: RequestState,
                     codes: Collection[const.CdeLogCodes],
                     offset: Optional[int],
                     length: Optional[vtypes.PositiveInt],
                     persona_id: Optional[vtypes.CdedbID],
                     submitted_by: Optional[vtypes.CdedbID],
                     change_note: Optional[str],
                     time_start: Optional[datetime.datetime],
                     time_stop: Optional[datetime.datetime]) -> Response:
        """View general activity."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.cdeproxy.retrieve_cde_log(
            rs, codes, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_cde_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'loglinks': loglinks})

    @access("cde_admin")
    @REQUESTdata(*LOG_FIELDS_COMMON)
    def view_finance_log(self, rs: RequestState,
                         codes: Collection[const.FinanceLogCodes],
                         offset: Optional[int],
                         length: Optional[vtypes.PositiveInt],
                         persona_id: Optional[vtypes.CdedbID],
                         submitted_by: Optional[vtypes.CdedbID],
                         change_note: Optional[str],
                         time_start: Optional[datetime.datetime],
                         time_stop: Optional[datetime.datetime]) -> Response:
        """View financial activity."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.cdeproxy.retrieve_finance_log(
            rs, codes, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_finance_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'loglinks': loglinks})

    @access("cde_admin")
    @REQUESTdata(*LOG_FIELDS_COMMON, "pevent_id")
    def view_past_log(self, rs: RequestState,
                      codes: Collection[const.PastEventLogCodes],
                      pevent_id: Optional[vtypes.ID],
                      offset: Optional[int],
                      length: Optional[vtypes.PositiveInt],
                      persona_id: Optional[vtypes.CdedbID],
                      submitted_by: Optional[vtypes.CdedbID],
                      change_note: Optional[str],
                      time_start: Optional[datetime.datetime],
                      time_stop: Optional[datetime.datetime]) -> Response:
        """View activities concerning concluded events."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.pasteventproxy.retrieve_past_log(
            rs, codes, pevent_id, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        pevent_ids = self.pasteventproxy.list_past_events(rs)
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_past_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'pevents': pevents, 'loglinks': loglinks})
