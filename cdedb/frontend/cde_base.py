#!/usr/bin/env python3

"""Basic services for the cde realm."""

import collections
import copy
import csv
import datetime
import decimal
import functools
import itertools
import operator
import pathlib
import re
from collections import OrderedDict, defaultdict
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple, Set, cast

from werkzeug import Response
from werkzeug.datastructures import FileStorage

import cdedb.database.constants as const
import cdedb.frontend.parse_statement as parse
import cdedb.validationtypes as vtypes
from cdedb.common import (
    Accounts, CdEDBObject, CdEDBObjectMap,
    EntitySorter, Error, LineResolutions, LOG_FIELDS_COMMON, PERSONA_DEFAULTS,
    RequestState, SemesterSteps, TransactionType, deduct_years,
    diacritic_patterns, get_hash, get_localized_country_codes,
    lastschrift_reference, merge_dicts, n_, now, unwrap, xsorted,
    get_country_code_from_country,
)
from cdedb.filter import enum_entries_filter
from cdedb.frontend.common import (
    AbstractUserFrontend, CustomCSVDialect, REQUESTdata, REQUESTdatadict, REQUESTfile,
    access, calculate_db_logparams, calculate_loglinks, check_validation as check,
    check_validation_optional as check_optional, csv_output,
    make_membership_fee_reference, make_postal_address, request_extractor, Worker,
    TransactionObserver,
)
from cdedb.query import (
    QueryConstraint, QueryOperators, QueryScope,
)
from cdedb.validation import (
    PERSONA_FULL_CDE_CREATION, TypeMapping, filter_none, validate_check,
    validate_check_optional
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


class CdEBaseFrontend(AbstractUserFrontend):
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
        simple_stats, other_stats, year_stats = self.cdeproxy.get_member_stats(rs)
        all_years = list(collections.ChainMap(*year_stats.values()))
        return self.render(rs, "member_stats", {
            'simple_stats': simple_stats, 'other_stats': other_stats,
            'year_stats': year_stats, 'all_years': all_years})

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
        scope = QueryScope.cde_member
        spec = scope.get_spec()
        query = check(rs, vtypes.QueryInput,
                      scope.mangle_query_input(rs, defaults), "query", spec=spec,
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
        courses = self.pasteventproxy.list_past_courses(rs)
        choices: Dict[str, OrderedDict[Any, str]] = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'pcourse_id': OrderedDict(
                xsorted(courses.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext)),
            'country': OrderedDict(get_localized_country_codes(rs)),
            'country2': OrderedDict(get_localized_country_codes(rs)),
        }
        return self.generic_user_search(
            rs, download, is_search, QueryScope.cde_user, QueryScope.cde_user,
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
            QueryScope.archived_past_event_user, QueryScope.archived_persona,
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
            "m": str(const.Genders.male.value),
            "w": str(const.Genders.female.value),
            "d": str(const.Genders.other.value),
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
        if (persona.get('country') or "").strip():
            persona['country'] = get_country_code_from_country(rs, persona['country'])
        else:
            persona['country'] = self.conf["DEFAULT_COUNTRY"]
        for k in ('telephone', 'mobile'):
            if persona[k] and not persona[k].strip().startswith(("0", "+")):
                persona[k] = "0" + persona[k].strip()
        merge_dicts(persona, PERSONA_DEFAULTS)
        persona, problems = validate_check(
            vtypes.Persona, persona, argname="persona", creation=True)
        if persona:
            if persona['birthday'] > deduct_years(now().date(), 10):
                problems.append(
                    ('birthday', ValueError(n_("Persona is younger than 10 years."))))
            if persona['gender'] == const.Genders.not_specified:
                warnings.append(
                    ('gender', ValueError(n_("No gender specified."))))
            birth_name = (persona['birth_name'] or "").strip()
            if birth_name == (persona['family_name'] or "").strip():
                persona['birth_name'] = None

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
                        ("doppelganger",
                         ValueError(n_("Email address already taken."))))
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
                warnings.append(
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

    def perform_batch_admission(self, rs: RequestState, data: List[CdEDBObject],
                                trial_membership: bool, consent: bool, sendmail: bool
                                ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Resolve all entries in the batch admission form.

        :returns: Success information and for positive outcome the
          number of created accounts or for negative outcome the line
          where an exception was triggered or None if it was a DB
          serialization error.
        """
        relevant_keys = {
            'resolution', 'doppelganger_id', 'pevent_id', 'pcourse_id',
            'is_instructor', 'is_orga', 'update_username', 'persona',
        }
        relevant_data = [{k: v for k, v in item.items() if k in relevant_keys}
                         for item in data]
        with TransactionObserver(rs, self, "perform_batch_admission"):
            success, count_new, count_renewed = self.cdeproxy.perform_batch_admission(
                rs, relevant_data, trial_membership, consent)
            if not success:
                return success, count_new, count_renewed
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
            return True, count_new, count_renewed

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
    @REQUESTfile("accounts_file")
    @REQUESTdata("membership", "trial_membership", "consent", "sendmail",
                 "finalized", "accounts")
    def batch_admission(self, rs: RequestState, membership: bool,
                        trial_membership: bool, consent: bool, sendmail: bool,
                        finalized: bool, accounts: Optional[str],
                        accounts_file: Optional[FileStorage],
                        ) -> Response:
        """Make a lot of new accounts.

        This is rather involved to make this job easier for the administration.

        The additional parameters membership, trial_membership, consent
        and sendmail modify the behaviour and can be selected by the
        user. Note however, that membership currently must be ``True``.

        The internal parameter finalized is used to explicitly signal at
        what point account creation will happen.
        """
        accounts_file = check_optional(
            rs, vtypes.CSVFile, accounts_file, "accounts_file")
        if rs.has_validation_errors():
            return self.batch_admission_form(rs)

        if accounts_file and accounts:
            rs.notify("warning", n_("Only one input method allowed."))
            return self.batch_admission_form(rs)
        elif accounts_file:
            rs.values["accounts"] = accounts = accounts_file
            accountlines = accounts.splitlines()
        elif accounts:
            accountlines = accounts.splitlines()
        else:
            rs.notify("error", n_("No input provided."))
            return self.batch_admission_form(rs)

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
                f"update_username{lineno}": Optional[bool],  # type: ignore
            }
            tmp = request_extractor(rs, params)
            if tmp[f"resolution{lineno}"] is None:
                tmp[f"resolution{lineno}"] = LineResolutions.none

            dataset['resolution'] = tmp[f"resolution{lineno}"]
            dataset['doppelganger_id'] = tmp[f"doppelganger_id{lineno}"]
            dataset['is_orga'] = tmp[f"is_orga{lineno}"]
            dataset['is_instructor'] = tmp[f"is_instructor{lineno}"]
            dataset['update_username'] = tmp[f"update_username{lineno}"]
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
                rs.values[
                    f"resolution{dataset['lineno']}"] = LineResolutions.create.value

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
        success, num_new, num_renewed = self.perform_batch_admission(
            rs, data, trial_membership, consent, sendmail)
        if success:
            if num_new:
                rs.notify("success", n_("%(num)s new members."), {'num': num_new})
            if num_renewed:
                rs.notify("success", n_("Modified %(num)s existing members."),
                          {'num': num_renewed})
            return self.redirect(rs, "cde/index")
        else:
            if num_new is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line %(num)s."),
                          {'num': num_new})
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
            if t.event_id and t.type == TransactionType.EventFee:
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
            dataset: CdEDBObject = {'raw': raw_entry, 'lineno': lineno}
            data.append(self.examine_money_transfer(rs, dataset))
        for ds1, ds2 in itertools.combinations(data, 2):
            if ds1['persona_id'] and ds1['persona_id'] == ds2['persona_id']:
                warning = (None, ValueError(
                    n_("More than one transfer for this account "
                       "(lines %(first)s and %(second)s)."),
                    {'first': ds1['lineno'] + 1, 'second': ds2['lineno'] + 1}))
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
        relevant_keys = {'amount', 'persona_id', 'note'}
        relevant_data = [{k: v for k, v in item.items() if k in relevant_keys}
                         for item in data]
        with TransactionObserver(rs, self, "money_transfers"):
            success, num, new_members = self.cdeproxy.perform_money_transfers(
                rs, relevant_data)
            if success and sendmail:
                for datum in data:
                    persona_ids = tuple(e['persona_id'] for e in data)
                    personas = self.coreproxy.get_cde_users(rs, persona_ids)
                    persona = personas[datum['persona_id']]
                    self.do_mail(rs, "transfer_received",
                                 {'To': (persona['username'],),
                                  'Subject': "Überweisung eingegangen",
                                  },
                                 {'persona': persona,
                                  'address': make_postal_address(rs, persona),
                                  'new_balance': persona['balance']})
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
            with TransactionObserver(rrs, self, "send_billing_mail"):
                proceed, persona = self.cdeproxy.process_for_semester_bill(
                    rrs, period_id, addresscheck, testrun)

                # Send mail only if transaction completed successfully.
                if persona:
                    lastschrift_list = self.cdeproxy.list_lastschrift(
                        rrs, persona_ids=(persona['id'],))
                    lastschrift = None
                    if lastschrift_list:
                        lastschrift = self.cdeproxy.get_lastschrift(
                            rrs, unwrap(lastschrift_list.keys()))
                        lastschrift['reference'] = lastschrift_reference(
                            persona['id'], lastschrift['id'])

                    address = make_postal_address(rrs, persona)
                    transaction_subject = make_membership_fee_reference(persona)
                    endangered = (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                                  and not persona['trial_member']
                                  and not lastschrift)
                    if endangered:
                        subject = "Mitgliedschaft verlängern"
                    else:
                        subject = "Mitgliedschaft verlängert"

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
            return proceed and not testrun

        def send_archival_notification(rrs: RequestState, rs: None = None) -> bool:
            """Send archival notifications to inactive accounts."""
            with TransactionObserver(rrs, self, "send_archival_notification"):
                proceed, persona = self.cdeproxy.process_for_semester_prearchival(
                    rrs, period_id, testrun)

                if persona:
                    self.do_mail(
                        rrs, "imminent_archival",
                        {'To': (persona['username'],),
                         'Subject': "Bevorstehende Löschung Deines"
                                    " CdE-Datenbank-Accounts"},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'meta_info': meta_info})
            return proceed and not testrun

        Worker.create(
            rs, "semester_bill",
            (send_billing_mail, send_archival_notification), self.conf)
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
            with TransactionObserver(rrs, self, "eject_member"):
                proceed, persona = self.cdeproxy.process_for_semester_eject(
                    rrs, period_id)

                if persona:
                    transaction_subject = make_membership_fee_reference(persona)
                    meta_info = self.coreproxy.get_meta_info(rrs)
                    self.do_mail(
                        rrs, "ejection",
                        {'To': (persona['username'],),
                         'Subject': "Austritt aus dem CdE e.V."},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'transaction_subject': transaction_subject,
                         'meta_info': meta_info})
            return proceed

        def automated_archival(rrs: RequestState, rs: None = None) -> bool:
            """Archive one inactive user if they are eligible."""
            with TransactionObserver(rrs, self, "automated_archival"):
                proceed, persona = self.cdeproxy.process_for_semester_archival(
                    rrs, period_id)

                if persona:
                    # TODO: somehow combine all failures into a single mail.
                    # This requires storing the ids somehow.
                    mail = self._create_mail(
                        text=f"Automated archival of persona {persona['id']} failed",
                        headers={'Subject': "Automated Archival failure",
                                 'To': (rrs.user.username,)},
                        attachments=None)
                    self._send_mail(mail)
            return proceed

        Worker.create(
            rs, "semester_eject", (eject_member, automated_archival), self.conf)
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
            proceed, persona = self.cdeproxy.process_for_semester_balance(
                rrs, period_id)
            return proceed

        Worker.create(rs, "semester_balance_update", update_balance, self.conf)
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
            with TransactionObserver(rrs, self, "send_addresscheck"):
                proceed, persona = self.cdeproxy.process_for_expuls_check(
                    rrs, expuls_id, testrun)
                if persona:
                    address = make_postal_address(rrs, persona)
                    self.do_mail(
                        rrs, "addresscheck",
                        {'To': (persona['username'],),
                         'Subject': "Adressabfrage für den exPuls"},
                        {'persona': persona, 'address': address})
            return proceed and not testrun

        if skip:
            self.cdeproxy.finish_expuls_addresscheck(rs, skip=True)
            rs.notify("success", n_("Not sending mail."))
        else:
            Worker.create(rs, "expuls_addresscheck", send_addresscheck, self.conf)
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
