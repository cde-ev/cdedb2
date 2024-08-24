#!/usr/bin/env python3

"""Basic services for the cde realm.

General user management is available to both the "core_admin" and "cde_admin" roles.
The more involved batch admission and the finance log require the "cde_admin" role.
"""

import collections
import copy
import csv
import datetime
import decimal
import itertools
import operator
from collections import OrderedDict
from collections.abc import Collection, Sequence
from typing import Any, Optional

from werkzeug import Response
from werkzeug.datastructures import FileStorage

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.cde.base import BatchAdmissionStats
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, Error, LineResolutions, RequestState,
    ValidationWarning, deduct_years, get_hash, merge_dicts, now,
)
from cdedb.common.i18n import get_country_code_from_country, get_localized_country_codes
from cdedb.common.n_ import n_
from cdedb.common.query import QueryConstraint, QueryOperators, QueryScope
from cdedb.common.query.log_filter import FinanceLogFilter
from cdedb.common.roles import PERSONA_DEFAULTS
from cdedb.common.sorting import xsorted
from cdedb.common.validation.validate import (
    PERSONA_FULL_CREATION, filter_none, get_errors, get_warnings,
)
from cdedb.filter import enum_entries_filter
from cdedb.frontend.common import (
    AbstractUserFrontend, CustomCSVDialect, REQUESTdata, REQUESTdatadict, REQUESTfile,
    TransactionObserver, access, check_validation as check,
    check_validation_optional as check_optional, inspect_validation as inspect,
    make_membership_fee_reference, request_extractor,
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
    'qop_country,country2': QueryOperators.equal,
    'qop_weblink,specialisation,affiliation,timeline,interests,free_form':
        QueryOperators.match,
    'qop_pevent_id': QueryOperators.equal,
    'qop_pcourse_id': QueryOperators.equal,
    'qord_0': 'family_name,birth_name',
    'qord_0_ascending': True,
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
            year=int(deadline.year + periods_left // 2))

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
        rs.notify_return_code(code, success=message)
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
        scope = QueryScope.cde_member
        spec = scope.get_spec()
        cutoff = self.conf["MAX_MEMBER_SEARCH_RESULTS"]

        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': events,
            'near_radius': self.conf["NEARBY_SEARCH_RADII"],
        }

        result: Optional[Sequence[CdEDBObject]] = None
        count = 0

        if not is_search:
            query = None
        else:
            # our query facility does not allow + signs, thus special-case it here
            phone = rs.values['phone'] = rs.request.values.get('phone')
            if phone:
                # remove leading zeroes - in database,
                #  numbers are stored starting with '+'
                phone = ("".join(char for char in phone if char in '0123456789')
                         .removeprefix("0").removeprefix("0"))
                if phone:
                    defaults['qval_telephone,mobile'] = phone
                else:
                    rs.append_validation_error(
                            ('phone', ValueError(n_("Wrong formatting."))))
            pl = rs.values['postal_lower'] = rs.request.values.get('postal_lower')
            pu = rs.values['postal_upper'] = rs.request.values.get('postal_upper')
            near_pc = rs.values['near_pc'] = rs.request.values.get('near_pc')
            near_radius = rs.values['near_radius'] = request_extractor(
                rs, {'near_radius': Optional[int]})['near_radius']  # type: ignore[dict-item]
            if pl and pu:
                defaults['qval_postal_code,postal_code2'] = f"{pl:0<5} {pu:0<5}"
            elif pl:
                defaults['qval_postal_code,postal_code2'] = f"{pl:0<5} 99999"
            elif pu:
                defaults['qval_postal_code,postal_code2'] = f"00000 {pu:0<5}"
            if near_pc or near_radius:
                if (near_radius and
                      near_radius not in self.conf["NEARBY_SEARCH_RADII"]):
                    rs.append_validation_error(
                        ('near_radius', ValueError(n_("Invalid choice."))),
                    )
                if pl or pu:
                    warn = ValueError(n_(
                        "Incompatible with postal code search."))
                    rs.extend_validation_errors([
                        ('near_pc', warn),
                        ('near_radius', warn),
                    ])
                elif not near_pc:
                    rs.append_validation_error(
                        ('near_pc', ValueError(n_("Must not be empty."))),
                    )
                elif not near_radius:
                    rs.append_validation_error(
                        ('near_radius', ValueError(n_("Must not be empty."))),
                    )
                else:
                    defaults['qop_postal_code,postal_code2'] = QueryOperators.oneof
                    nearby_postal_codes = self.cdeproxy.get_nearby_postal_codes(
                        rs, near_pc, near_radius)
                    if not nearby_postal_codes:
                        rs.append_validation_error(
                            ('near_pc', ValidationWarning(n_("Unknown postal code."))),
                        )
                    defaults['qval_postal_code,postal_code2'] = " ".join(
                        nearby_postal_codes)
                    defaults['qval_country,country2'] = self.conf["DEFAULT_COUNTRY"]
            query = check(rs, vtypes.QueryInput,
                          scope.mangle_query_input(rs, defaults), "query", spec=spec,
                          allow_empty=not is_search, separator=" ")

            pevent_id = None
            if pevent_id := rs.values.get('qval_pevent_id'):
                try:
                    pevent_id = int(pevent_id)
                except ValueError:
                    pass
            if pevent_id:
                choices['pcourse_id'] = self.pasteventproxy.list_past_courses(
                    rs, pevent_id)

        if rs.has_validation_errors():
            self._fix_search_validation_error_references(
                rs, {'phone', 'near_pc', 'near_radius'})
        elif is_search and query and not query.constraints:
            rs.notify("error", n_("You have to specify some filters."))
        elif is_search:
            assert query is not None

            def restrict(constraint: QueryConstraint) -> QueryConstraint:
                field, operation, value = constraint
                if field == 'fulltext':
                    value = [fr"\m{val}\M" if len(val) <= 3 else val
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
    def _fix_search_validation_error_references(
            rs: RequestState, skip: Collection[str] = (),
    ) -> None:
        """A little hack to fix displaying of errors for course and meber search:

        The form uses 'qval_<field>' as input name, the validation only returns the
        field's name.
        """
        appraised = rs.validation_appraised
        current = tuple(rs.retrieve_validation_errors())
        rs.replace_validation_errors(
            [('qval_' + k, v) if k not in skip else (k, v) for k, v in current])  # type: ignore[operator]
        if appraised:
            rs.ignore_validation_errors()

    @access("core_admin", "cde_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str], is_search: bool,
                    ) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        courses = self.pasteventproxy.list_past_courses(rs)
        choices: dict[str, OrderedDict[Any, str]] = {
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
            rs, download, is_search, QueryScope.all_cde_users,
            self.cdeproxy.submit_general_query, choices=choices)

    @access("core_admin", "cde_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': True,
            'trial_member': False,
            'honorary_member': False,
            'is_searchable': False,
            'paper_expuls': True,
            'donation': decimal.Decimal(0),
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("core_admin", "cde_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_CREATION['cde']))
    def create_user(self, rs: RequestState, data: CdEDBObject) -> Response:
        defaults = {
            'is_cde_realm': True,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
            'decided_search': False,
            'bub_search': False,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("cde_admin")
    def batch_admission_form(self, rs: RequestState,
                             data: Optional[list[CdEDBObject]] = None,
                             csvfields: Optional[tuple[str, ...]] = None) -> Response:
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

    def examine_for_admission(self, rs: RequestState, datum: CdEDBObject,
                              ) -> CdEDBObject:
        """Check one line of batch admission.

        We test for fitness of the data itself, as well as possible
        existing duplicate accounts.

        :returns: The processed input datum.
        """
        warnings: list[Error] = []
        problems: list[Error]

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
            "f": str(const.Genders.female.value),
            "d": str(const.Genders.other.value),
        }
        gender = (persona.get('gender') or "3")[0].lower()
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
            'display_name': persona['display_name'] or persona['given_names'],
            'trial_member': False,
            'honorary_member': False,
            'paper_expuls': True,
            'donation': decimal.Decimal(0),
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
        persona_backup = copy.deepcopy(persona)
        persona, problems = inspect(
            vtypes.Persona, persona, argname="persona", creation=True)
        # make sure ValidationWarnings do not block the further processing
        if persona is None:
            persona, _ = inspect(
                vtypes.Persona, persona_backup, argname="persona", ignore_warnings=True,
                creation=True)
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
                elif dg['is_member']:
                    if datum['resolution'].do_trial():
                        msg = n_("May not grant trial membership to member.")
                        problems.append(("doppelganger", ValueError(msg)))
        if datum['doppelganger_id'] and pevent_id:
            existing = self.pasteventproxy.list_participants(rs, pevent_id=pevent_id)
            if (datum['doppelganger_id'], pcourse_id) in existing:
                warnings.append(
                    ("pevent_id", KeyError(n_("Participation already recorded."))))

        # ensure each ValidationWarning is considered as warning, even if it appears
        # during a call to check. Remove all ValidationWarnings from problems
        warnings.extend(get_warnings(problems))
        problems = get_errors(problems)

        datum.update({
            'persona': persona,
            'pevent_id': pevent_id,
            'pcourse_id': pcourse_id,
            'doppelgangers': doppelgangers,
            'warnings': warnings,
            'problems': problems,
        })
        return datum

    def perform_batch_admission(self, rs: RequestState, data: list[CdEDBObject],
                                trial_membership: bool, consent: bool, sendmail: bool,
                                ) -> tuple[bool, Optional[int], Optional[int]]:
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
            success, stats = self.cdeproxy.perform_batch_admission(
                rs, relevant_data, trial_membership, consent)
            if not success:
                assert stats is None or isinstance(stats, int)
                return success, stats, None
            assert isinstance(stats, BatchAdmissionStats)
            # Send mail after the transaction succeeded
            if sendmail:
                personas = self.coreproxy.get_personas(rs, stats.new_accounts)
                for persona in personas.values():
                    self.send_welcome_mail(rs, persona)
            count_new = len(stats.new_accounts | stats.new_members)
            return True, count_new, len(stats.modified_accounts)

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
            'event', 'course', 'family_name', 'given_names', 'display_name', 'title',
            'name_supplement', 'birth_name', 'gender', 'address_supplement',
            'address', 'postal_code', 'location', 'country', 'telephone',
            'mobile', 'username', 'birthday',
        )
        reader = csv.DictReader(
            accountlines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        total_account_number = 0
        for lineno, raw_entry in enumerate(reader):
            total_account_number += 1
            dataset: CdEDBObject = {'raw': raw_entry}
            params: vtypes.TypeMapping = {
                # as on the first submit no values for the resolution are transmitted,
                # we have to cast None -> LineResolutions.none after extraction
                f"resolution{lineno}": Optional[LineResolutions],  # type: ignore[dict-item]
                f"doppelganger_id{lineno}": Optional[vtypes.ID],  # type: ignore[dict-item]
                f"hash{lineno}": Optional[str],  # type: ignore[dict-item]
                f"is_orga{lineno}": Optional[bool],  # type: ignore[dict-item]
                f"is_instructor{lineno}": Optional[bool],  # type: ignore[dict-item]
                f"update_username{lineno}": Optional[bool],  # type: ignore[dict-item]
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

    def determine_open_permits(self, rs: RequestState,
                               lastschrift_ids: Optional[Collection[int]] = None,
                               ) -> set[int]:
        """Find ids, which to debit this period.

        Helper to find out which of the passed lastschrift permits has
        not been debited for a year.

        This is used for both lastschrift and semester management.

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

    @access("member", "cde_admin")
    def view_misc(self, rs: RequestState) -> Response:
        """View miscellaneos things."""
        meta_data = self.coreproxy.get_meta_info(rs)
        cde_misc = (meta_data.get("cde_misc") or rs.gettext("*Nothing here yet.*"))
        return self.render(rs, "view_misc", {"cde_misc": cde_misc})

    @REQUESTdatadict(*FinanceLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("cde_admin", "auditor")
    def view_finance_log(self, rs: RequestState, data: CdEDBObject, download: bool,
                         ) -> Response:
        """View financial activity."""
        return self.generic_view_log(
            rs, data, FinanceLogFilter, self.cdeproxy.retrieve_finance_log,
            download=download, template="view_finance_log",
        )
