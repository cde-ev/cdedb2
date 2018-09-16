#!/usr/bin/env python3

"""Services for the cde realm."""

import cgitb
from collections import OrderedDict
import copy
import csv
import hashlib
import itertools
import pathlib
import random
import re
import string
import sys
import tempfile

import psycopg2.extensions
import werkzeug

import cdedb.database.constants as const
import cdedb.validation as validate
from cdedb.database.connection import Atomizer
from cdedb.common import (
    _, merge_dicts, name_key, lastschrift_reference, now, glue, unwrap,
    int_to_words, determine_age_class, LineResolutions, PERSONA_DEFAULTS,
    ProxyShim, diacritic_patterns, open_utf8, shutil_copy)
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, Worker, csv_output,
    check_validation as check, cdedbid_filter, request_extractor,
    make_postal_address, make_transaction_subject, query_result_to_json)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input, QueryOperators
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.cde import CdEBackend

MEMBERSEARCH_DEFAULTS = {
    'qop_fulltext': QueryOperators.containsall,
    'qsel_family_name,birth_name': True,
    'qop_family_name,birth_name': QueryOperators.similar,
    'qsel_given_names,display_name': True,
    'qop_given_names,display_name': QueryOperators.similar,
    'qsel_username': True,
    'qop_username': QueryOperators.similar,
    'qop_telephone,mobile': QueryOperators.similar,
    'qop_address,address_supplement,address2,address_supplement2':
        QueryOperators.similar,
    'qop_postal_code,postal_code2': QueryOperators.similar,
    'qop_location,location2': QueryOperators.similar,
    'qop_country,country2': QueryOperators.similar,
    'qop_weblink,specialisation,affiliation,timeline,interests,free_form':
        QueryOperators.similar,
    'qop_pevent_id': QueryOperators.equal,
    'qop_pcourse_id': QueryOperators.equal,
    'qord_primary': 'family_name,birth_name',
    'qord_primary_ascending': True,
}

class CdEFrontend(AbstractUserFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_cde_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(CdEBackend(configpath))
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("cde")
    def index(self, rs):
        """Render start page."""
        meta_info = self.coreproxy.get_meta_info(rs)
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        deadline = None
        user_lastschrift = []
        if "member" in rs.user.roles:
            user_lastschrift = self.cdeproxy.list_lastschrift(
                rs, persona_ids=(rs.user.persona_id,), active=True)
            periods_left = data['balance'] // self.conf.MEMBERSHIP_FEE
            if data['trial_member']:
                periods_left += 1
            period = self.cdeproxy.get_period(rs,
                                              self.cdeproxy.current_period(rs))
            today = now().date()
            ## Compensate if the start of the period is not exactly on the
            ## 1.1. or 1.7.
            if not period['billing_done'] and today.month in (6, 12):
                periods_left += 1
            if period['balance_done'] and today.month in (1, 7):
                periods_left -= 1
            ## Initialize deadline
            deadline = now().date().replace(day=1)
            month = 7 if deadline.month >= 7 else 1
            deadline = deadline.replace(month=month)
            ## Add remaining periods
            deadline = deadline.replace(year=deadline.year + periods_left//2)
            if periods_left % 2:
                if deadline.month >= 7:
                    deadline = deadline.replace(year=deadline.year + 1, month=1)
                else:
                    deadline = deadline.replace(month=7)
        return self.render(rs, "index", {
            'has_lastschrift': (len(user_lastschrift) > 0), 'data': data,
            'meta_info': meta_info, 'deadline': deadline})

    @access("persona")
    @REQUESTdata(("stay", "bool_or_None"))
    def consent_decision_form(self, rs, stay):
        """After login ask cde members for decision about searchability. Do
        this only if no decision has been made in the past.

        This is the default page after login, but most users will instantly
        be redirected.
        """
        if "member" not in rs.user.roles or "searchable" in rs.user.roles:
            return self.redirect(rs, "core/index")
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        if data['decided_search'] and not stay:
            return self.redirect(rs, "core/index")
        return self.render(rs, "consent_decision", {
            'decided_search': data['decided_search']})

    @access("member", modi={"POST"})
    @REQUESTdata(("ack", "bool"))
    def consent_decision(self, rs, ack):
        """Record decision."""
        if rs.errors:
            return self.consent_decision_form(rs, stay=True)
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        new = {
            'id': rs.user.persona_id,
            'decided_search': True,
            'is_searchable': ack,
        }
        change_note = rs.gettext("Consent decision (is {ack}).").format(ack=ack)
        code = self.coreproxy.change_persona(
            rs, new, generation=None, may_wait=False,
            change_note=change_note)
        message = _("Consent noted.") if ack else _("Decision noted.")
        self.notify_return_code(rs, code, success=message)
        if not code:
            return self.consent_decision_form(rs, stay=True)
        if not data['decided_search']:
            return self.redirect(rs, "core/index")
        return self.redirect(rs, "cde/index")

    @access("searchable")
    @REQUESTdata(("is_search", "bool"))
    def member_search(self, rs, is_search):
        """Search for members."""
        spec = copy.deepcopy(QUERY_SPECS['qview_cde_member'])
        query = check(
            rs, "query_input",
            mangle_query_input(rs, spec, MEMBERSEARCH_DEFAULTS), "query",
            spec=spec, allow_empty=not is_search, separator=' ')
        events = {k: v
                  for k, v in self.pasteventproxy.list_past_events(rs).items()}
        pevent_id = None
        if rs.values.get('qval_pevent_id'):
            try:
                pevent_id = int(rs.values.get('qval_pevent_id'))
            except ValueError:
                pass
        courses = tuple()
        if pevent_id:
            courses = {k: v for k, v in self.pasteventproxy.list_past_courses(
                rs, pevent_id).items()}
        choices = {"pevent_id": events, 'pcourse_id': courses}
        result = None
        if is_search and not rs.errors:
            query.scope = "qview_cde_member"
            query.fields_of_interest.append('personas.id')
            result = self.cdeproxy.submit_general_query(rs, query)
            result = sorted(result, key=name_key)
            if len(result) == 1:
                return self.redirect_show_user(rs, result[0]['id'],
                                               quote_me=True)
            if (len(result) > self.conf.MAX_MEMBER_SEARCH_RESULTS
                    and not self.is_admin(rs)):
                result = result[:self.conf.MAX_MEMBER_SEARCH_RESULTS]
                rs.notify("info", _("Too many query results."))
        return self.render(rs, "member_search", {
            'spec': spec, 'choices': choices, 'result': result})

    @access("cde_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs, download, is_search):
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_cde_user'])
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {'pevent_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_cde_user']
        params = {
            'spec': spec, 'choices': choices,
            'default_queries': default_queries, 'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_cde_user"
            result = self.cdeproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    for field in csvfield.split(','):
                        fields.append(field.split('.')[-1])
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=csv_data, inline=False,
                        filename=rs.gettext("result.csv"))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename=rs.gettext("result.json"))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("cde_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': True,
            'bub_search': False,
            'cloud_account': True,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "birth_name", "name_supplement",
        "display_name", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "gender", "birthday", "username",
        "telephone", "mobile", "weblink", "address", "address_supplement",
        "postal_code", "location", "country", "address2",
        "address_supplement2", "postal_code2", "location2", "country2",
        "is_member", "is_searchable", "trial_member", "bub_search",
        "cloud_account", "notes")
    def create_user(self, rs, data):
        defaults = {
            'is_cde_realm': True,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_active': True,
            'decided_search': False,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("cde_admin")
    def batch_admission_form(self, rs, data=None, csvfields=None):
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
        data = data or {}
        csvfields = csvfields or tuple()
        pevents = self.pasteventproxy.list_past_events(rs)
        pevent_ids = {d['pevent_id'] for d in data if d['pevent_id']}
        pcourses = {
            pevent_id: self.pasteventproxy.list_past_courses(rs, pevent_id)
            for pevent_id in pevent_ids}
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['pevent_id'] = csv_position.pop('event', -1)
        csv_position['pcourse_id'] = csv_position.get('course', -1)
        return self.render(rs, "batch_admission", {
            'data': data, 'pevents': pevents, 'pcourses': pcourses,
            'csvfields': csv_position})

    def examine_for_admission(self, rs, datum):
        """Check one line of batch admission.

        We test for fitness of the data itself, as well as possible
        existing duplicate accounts.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: object}
        :rtype: {str: object}
        :returns: The processed input datum.
        """
        warnings = []
        if datum['old_hash'] and datum['old_hash'] != datum['new_hash']:
            ## remove resolution in case of a change
            datum['resolution'] = None
            rs.values['resolution{}'.format(datum['lineno'] - 1)] = None
            warnings.append((None, ValueError(_("Entry changed."))))
        persona = copy.deepcopy(datum['raw'])
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
            'bub_search': False,
            'decided_search': False,
            'notes': None})
        merge_dicts(persona, PERSONA_DEFAULTS)
        persona, problems = validate.check_persona(persona, "persona",
                                                   creation=True)
        pevent_id, w, p = self.pasteventproxy.find_past_event(
            rs, datum['raw']['event'])
        warnings.extend(w)
        problems.extend(p)
        pcourse_id = None
        if datum['raw']['course'] and pevent_id:
            pcourse_id, w, p = self.pasteventproxy.find_past_course(
                rs, datum['raw']['course'], pevent_id)
            warnings.extend(w)
            problems.extend(p)
        else:
            warnings.append(("course", ValueError(_("No course available."))))
        doppelgangers = tuple()
        if persona:
            temp = copy.deepcopy(persona)
            temp['id'] = 1
            doppelgangers = self.coreproxy.find_doppelgangers(rs, temp)
        if doppelgangers:
            warnings.append(("persona", ValueError(_("Doppelgangers found."))))
        if (datum['resolution'] is not None and
                (bool(datum['doppelganger_id'])
                 != datum['resolution'].is_modification())):
            problems.append(
                ("doppelganger",
                 RuntimeError(
                     _("Doppelganger choice doesn't fit resolution."))))
        if datum['doppelganger_id']:
            if datum['doppelganger_id'] not in doppelgangers:
                problems.append(
                    ("doppelganger", KeyError(_("Doppelganger unavailable."))))
            else:
                if not doppelgangers[datum['doppelganger_id']]['is_cde_realm']:
                    problems.append(
                        ("doppelganger",
                         ValueError(_("Doppelganger not a CdE-Account."))))
        if datum['doppelganger_id'] and pevent_id:
            existing = self.pasteventproxy.list_participants(
                rs, pevent_id=pevent_id)
            if (datum['doppelganger_id'], pcourse_id) in existing:
                problems.append(
                    ("pevent_id",
                     KeyError(_("Participation already recorded."))))
        datum.update({
            'persona': persona,
            'pevent_id': pevent_id,
            'pcourse_id': pcourse_id,
            'doppelgangers': doppelgangers,
            'warnings': warnings,
            'problems': problems,})
        return datum

    def perform_batch_admission(self, rs, data, trial_membership, consent,
                                sendmail):
        """Resolve all entries in the batch admission form.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: [{str: object}]
        :type trial_membership: bool
        :type consent: bool
        :type sendmail: bool
        :rtype: bool, int
        :returns: Success information and for positive outcome the
          number of created accounts or for negative outcome the line
          where an exception was triggered or None if it was a DB
          serialization error.
        """
        fields = ('family_name', 'given_names', 'title', 'name_supplement',
                  'birth_name', 'gender', 'address_supplement', 'address',
                  'postal_code', 'location', 'country', 'telephone',
                  'mobile')
        try:
            with Atomizer(rs):
                count = 0
                for index, datum in enumerate(data):
                    persona_id = None
                    if datum['resolution'] == LineResolutions.skip:
                        continue
                    elif datum['resolution'] == LineResolutions.create:
                        datum['persona'].update({
                            'is_member': True,
                            'trial_member': trial_membership,
                            'is_searchable': consent,
                            })
                        persona_id = self.coreproxy.create_persona(
                            rs, datum['persona'])
                        count += 1
                    elif datum['resolution'].is_modification():
                        persona_id = datum['doppelganger_id']
                        if datum['resolution'].do_trial():
                            self.coreproxy.change_membership(
                                rs, datum['doppelganger_id'], is_member=True)
                            update = {
                                'id': datum['doppelganger_id'],
                                'trial_member': True,
                            }
                            self.coreproxy.change_persona(
                                rs, update, may_wait=False,
                                change_note=rs.gettext(
                                    "Renewed trial membership."))
                        if datum['resolution'].do_update():
                            update = {'id': datum['doppelganger_id']}
                            for field in fields:
                                update[field] = datum['persona'][field]
                            self.coreproxy.change_persona(
                                rs, update, may_wait=False,
                                change_note=rs.gettext("Imported recent data."))
                            self.coreproxy.change_username(
                                rs, datum['doppelganger_id'],
                                datum['persona']['username'], password=None)
                    else:
                        raise RuntimeError(_("Impossible."))
                    if datum['pevent_id']:
                        ## TODO preserve instructor/orga information
                        self.pasteventproxy.add_participant(
                            rs, datum['pevent_id'], datum['pcourse_id'],
                            persona_id, is_instructor=False, is_orga=False)
        except psycopg2.extensions.TransactionRollbackError:
            ## We perform a rather big transaction, so serialization errors
            ## could happen.
            return False, None
        except:
            ## This blanket catching of all exceptions is a last resort. We try
            ## to do enough validation, so that this should never happen, but
            ## an opaque error (as would happen without this) would be rather
            ## frustrating for the users -- hence some extra error handling
            ## here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during batch creation",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.logger.error(cgitb.text(sys.exc_info(), context=7))
            return False, index
        ## Send mail after the transaction succeeded
        if sendmail:
            for datum in data:
                if datum['resolution'] == LineResolutions.create:
                    self.do_mail(rs, "welcome",
                                 {'To': (datum['raw']['username'],),
                                  'Subject': _('CdE admission'),},
                                 {'data': datum['persona']})
        return True, count

    @staticmethod
    def similarity_score(ds1, ds2):
        """Helper to determine similar input lines.

        This is separate from the detection of existing accounts, and
        can happen because of some human error along the way.

        :type ds1: {str: object}
        :type ds2: {str: object}
        :rtype: str
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
    @REQUESTdata(("membership", "bool"), ("trial_membership", "bool"),
                 ("consent", "bool"), ("sendmail", "bool"), ("accounts", "str"),
                 ("finalized", "bool"))
    def batch_admission(self, rs, membership, trial_membership, consent,
                        sendmail, finalized, accounts):
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
            accountlines, fieldnames=fields, delimiter=';',
            quoting=csv.QUOTE_MINIMAL, quotechar='"', doublequote=False,
            escapechar='\\')
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset = {'raw': raw_entry}
            params = (
                ("resolution{}".format(lineno), "enum_lineresolutions_or_None"),
                ("doppelganger_id{}".format(lineno), "id_or_None"),
                ("hash{}".format(lineno), "str_or_None"),)
            tmp = request_extractor(rs, params)
            dataset['resolution'] = tmp["resolution{}".format(lineno)]
            dataset['doppelganger_id'] = tmp["doppelganger_id{}".format(lineno)]
            dataset['old_hash'] = tmp["hash{}".format(lineno)]
            dataset['new_hash'] = hashlib.md5(
                accountlines[lineno].encode()).hexdigest()
            rs.values["hash{}".format(lineno)] = dataset['new_hash']
            lineno += 1
            dataset['lineno'] = lineno
            data.append(self.examine_for_admission(rs, dataset))
        for ds1, ds2 in itertools.combinations(data, 2):
            similarity = self.similarity_score(ds1, ds2)
            if similarity == "high":
                problem = (None, ValueError(
                    _("Lines {first} and {second} are the same."),
                    {'first': ds1['lineno'], 'second': ds2['lineno']}))
                ds1['problems'].append(problem)
                ds2['problems'].append(problem)
            elif similarity == "medium":
                warning = (None, ValueError(
                    _("Lines {first} and {second} look the same."),
                    {'first': ds1['lineno'], 'second': ds2['lineno']}))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
            elif similarity == "low":
                pass
            else:
                raise RuntimeError(_("Impossible."))
        for dataset in data:
            if (dataset['resolution'] is None
                    and not dataset['doppelgangers']
                    and not dataset['problems']
                    and not dataset['old_hash']):
                ## automatically select resolution if this is an easy case
                dataset['resolution'] = LineResolutions.create
                rs.values['resolution{}'.format(dataset['lineno'] - 1)] = \
                  LineResolutions.create.value
        if lineno != len(accountlines):
            rs.errors.append(("accounts",
                              ValueError(_("Lines didn't match up."))))
        if not membership:
            rs.errors.append(("membership",
                              ValueError(
                                  _("Only member admission supported."))))
        open_issues = any(
            e['resolution'] is None
            or (e['problems'] and e['resolution'] != LineResolutions.skip)
            for e in data)
        if rs.errors or not data or open_issues:
            return self.batch_admission_form(rs, data=data, csvfields=fields)
        if not finalized:
            rs.values['finalized'] = True
            return self.batch_admission_form(rs, data=data, csvfields=fields)

        ## Here we have survived all validation
        success, num = self.perform_batch_admission(rs, data, trial_membership,
                                                    consent, sendmail)
        if success:
            rs.notify("success", _("Created {num} accounts."), {'num': num})
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", _("DB serialization error."))
            else:
                rs.notify("error", _("Unexpected error on line {num}."),
                          {'num': num})
            return self.batch_admission_form(rs, data=data, csvfields=fields)

    @access("cde_admin")
    def money_transfers_form(self, rs, data=None):
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        defaults = {'sendmail': True,}
        merge_dicts(rs.values, defaults)
        data = data or {}
        return self.render(rs, "money_transfers", {'data': data})

    def examine_money_transfer(self, rs, datum):
        """Check one line specifying a money transfer.

        We test for fitness of the data itself.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: object}
        :rtype: {str: object}
        :returns: The processed input datum.
        """
        persona_id, problems = validate.check_cdedbid(
            datum['raw']['persona_id'], "persona_id")
        family_name, p = validate.check_str(
            datum['raw']['family_name'], "family_name")
        problems.extend(p)
        given_names, p = validate.check_str(
            datum['raw']['given_names'], "given_names")
        problems.extend(p)
        amount, p = validate.check_non_negative_decimal(datum['raw']['amount'],
                                                        "amount")
        problems.extend(p)
        note, p = validate.check_str_or_None(datum['raw']['note'], "note")
        problems.extend(p)

        persona = None
        if persona_id:
            persona = self.coreproxy.get_persona(rs, persona_id)
            if persona['is_archived']:
                problems.append(('persona_id',
                                 ValueError(_("Persona is archived."))))
            if not re.search(diacritic_patterns(family_name),
                             persona['family_name'], flags=re.IGNORECASE):
                problems.append(('family_name',
                                 ValueError(_("Family name doesn't match."))))
            if not re.search(diacritic_patterns(given_names),
                             persona['given_names'], flags=re.IGNORECASE):
                problems.append(('given_names',
                                 ValueError(_("Given names don't match."))))
        datum.update({
            'persona_id': persona_id,
            'amount': amount,
            'note': note,
            'warnings': [],
            'problems': problems,})
        return datum

    def perform_money_transfers(self, rs, data, sendmail):
        """Resolve all entries in the money transfers form.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: [{str: object}]
        :type sendmail: bool
        :rtype: bool, int, int
        :returns: Success information and
          * for positive outcome the number of recorded transfer as well as
            the number of new members or
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error as first number and
            None as second number.
        """
        try:
            with Atomizer(rs):
                count = 0
                memberships_gained = 0
                persona_ids = tuple(e['persona_id'] for e in data)
                personas = self.coreproxy.get_total_personas(rs, persona_ids)
                for index, datum in enumerate(data):
                    new_balance = (personas[datum['persona_id']]['balance']
                                   + datum['amount'])
                    count += self.coreproxy.change_persona_balance(
                        rs, datum['persona_id'], new_balance,
                        const.FinanceLogCodes.increase_balance,
                        change_note=datum['note'])
                    if new_balance > 0:
                        memberships_gained += self.coreproxy.change_membership(
                            rs, datum['persona_id'], is_member=True)
        except psycopg2.extensions.TransactionRollbackError:
            ## We perform a rather big transaction, so serialization errors
            ## could happen.
            return False, None, None
        except:
            ## This blanket catching of all exceptions is a last resort. We try
            ## to do enough validation, so that this should never happen, but
            ## an opaque error (as would happen without this) would be rather
            ## frustrating for the users -- hence some extra error handling
            ## here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.logger.error(cgitb.text(sys.exc_info(), context=7))
            return False, index, None
        if sendmail:
            for datum in data:
                persona = personas[datum['persona_id']]
                address = make_postal_address(persona)
                new_balance = (personas[datum['persona_id']]['balance']
                               + datum['amount'])
                self.do_mail(rs, "transfer_received",
                             {'To': (persona['username'],),
                              'Subject': _('CdE money transfer received'),},
                             {'persona': persona, 'address': address,
                              'new_balance': new_balance})
        return True, count, memberships_gained

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("sendmail", "bool"), ("transfers", "str"),
                 ("checksum", "str_or_None"))
    def money_transfers(self, rs, sendmail, transfers, checksum):
        """Update member balances.

        The additional parameter sendmail modifies the behaviour and can
        be selected by the user.

        The internal parameter checksum is used to guard against data
        corruption and to explicitly signal at what point the data will
        be committed (for the second purpose it works like a boolean).
        """
        transfers = transfers or ''
        transferlines = transfers.splitlines()
        fields = ('persona_id', 'family_name', 'given_names', 'amount', 'note')
        reader = csv.DictReader(
            transferlines, fieldnames=fields, delimiter=';',
            quoting=csv.QUOTE_MINIMAL, quotechar='"', doublequote=False,
            escapechar='\\')
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset = {'raw': raw_entry}
            lineno += 1
            dataset['lineno'] = lineno
            data.append(self.examine_money_transfer(rs, dataset))
        for ds1, ds2 in itertools.combinations(data, 2):
            if ds1['persona_id'] and ds1['persona_id'] == ds2['persona_id']:
                warning = (None, ValueError(
                    _("More than one transfer for this account "
                      "(lines {first} and {second})."),
                    {'first': ds1['lineno'], 'second': ds2['lineno']}))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
        if lineno != len(transferlines):
            rs.errors.append(("transfers",
                              ValueError(_("Lines didn't match up."))))
        open_issues = any(e['problems'] for e in data)
        if rs.errors or not data or open_issues:
            rs.values['checksum'] = None
            return self.money_transfers_form(rs, data=data)
        current_checksum = hashlib.md5(transfers.encode()).hexdigest()
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.money_transfers_form(rs, data=data)

        ## Here validation is finished
        success, num, new_members = self.perform_money_transfers(
            rs, data, sendmail)
        if success:
            rs.notify("success", _("Committed {num} transfers. "
                                   "There were {new_members} new members."),
                      {'num': num, 'new_members': new_members})
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", _("DB serialization error."))
            else:
                rs.notify("error", _("Unexpected error on line {num}."),
                          {'num': num})
            return self.money_transfers_form(rs, data=data)

    def determine_open_permits(self, rs, lastschrift_ids=None):
        """Find ids, which to debit this period.

        Helper to find out which of the passed lastschrift permits has
        not been debitted for a year.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lastschrift_ids: [int] or None
        :param lastschrift_ids: If None is passed all existing permits
          are checked.
        :rtype: {int}
        """
        if lastschrift_ids is None:
            lastschrift_ids = self.cdeproxy.list_lastschrift(rs).keys()
        stati = const.LastschriftTransactionStati
        period = self.cdeproxy.current_period(rs)
        periods = tuple(range(period - self.conf.PERIODS_PER_YEAR +1,
                              period + 1))
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=lastschrift_ids, periods=periods,
            stati=(stati.success, stati.issued, stati.skipped))
        return set(lastschrift_ids) - set(transaction_ids.values())

    @access("cde_admin")
    def lastschrift_index(self, rs):
        """General lastschrift overview.

        This presents open items as well as all permits.
        """
        lastschrift_ids = self.cdeproxy.list_lastschrift(rs)
        lastschrifts = self.cdeproxy.get_lastschrifts(rs,
                                                      lastschrift_ids.keys())
        period = self.cdeproxy.current_period(rs)
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, periods=(period,),
            stati=(const.LastschriftTransactionStati.issued,))
        transactions = self.cdeproxy.get_lastschrift_transactions(
            rs, transaction_ids.keys())
        persona_ids = set(lastschrift_ids.values()).union({
            x['submitted_by'] for x in lastschrifts.values()})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        open_permits = self.determine_open_permits(rs, lastschrift_ids)
        for lastschrift in lastschrifts.values():
            lastschrift['open'] = lastschrift['id'] in open_permits
        return self.render(rs, "lastschrift_index", {
            'lastschrifts': lastschrifts, 'personas': personas,
            'transactions': transactions})

    @access("member")
    def lastschrift_show(self, rs, persona_id):
        """Display all lastschrift information for one member.

        Especially all permits and transactions.
        """
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        lastschrift_ids = self.cdeproxy.list_lastschrift(
            rs, persona_ids=(persona_id,), active=None)
        lastschrifts = self.cdeproxy.get_lastschrifts(rs,
                                                      lastschrift_ids.keys())
        transactions = {}
        if lastschrifts:
            transaction_ids = self.cdeproxy.list_lastschrift_transactions(
                rs, lastschrift_ids=lastschrift_ids.keys())
            transactions = self.cdeproxy.get_lastschrift_transactions(
                rs, transaction_ids.keys())
        persona_ids = {persona_id}.union({
            x['submitted_by'] for x in lastschrifts.values()}).union({
                x['submitted_by'] for x in transactions.values()})
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

    @access("cde_admin")
    def lastschrift_change_form(self, rs, lastschrift_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['lastschrift'])
        persona = self.coreproxy.get_persona(
            rs, rs.ambience['lastschrift']['persona_id'])
        return self.render(rs, "lastschrift_change", {'persona': persona})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict('amount', 'iban', 'account_owner', 'account_address',
                     'notes', 'max_dsa',)
    def lastschrift_change(self, rs, lastschrift_id, data):
        """Modify one permit."""
        data['id'] = lastschrift_id
        data = check(rs, "lastschrift", data)
        if rs.errors:
            return self.lastschrift_change_form(rs, lastschrift_id)
        code = self.cdeproxy.set_lastschrift(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': rs.ambience['lastschrift']['persona_id']})

    @access("cde_admin")
    def lastschrift_create_form(self, rs, persona_id):
        """Render form."""
        return self.render(rs, "lastschrift_create")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict('amount', 'iban', 'account_owner', 'account_address',
                     'notes', 'max_dsa')
    def lastschrift_create(self, rs, persona_id, data):
        """Create a new permit."""
        data['persona_id'] = persona_id
        data = check(rs, "lastschrift", data, creation=True)
        if rs.errors:
            return self.lastschrift_create_form(rs, persona_id)
        new_id = self.cdeproxy.create_lastschrift(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "cde/lastschrift_show")

    @access("cde_admin", modi={"POST"})
    def lastschrift_revoke(self, rs, lastschrift_id):
        """Disable a permit."""
        data = {
            'id': lastschrift_id,
            'revoked_at': now(),
        }
        code = self.cdeproxy.set_lastschrift(rs, data)
        self.notify_return_code(rs, code, success=_("Permit revoked."))
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': rs.ambience['lastschrift']['persona_id']})

    def create_sepapain(self, rs, transactions):
        """Create an XML document for submission to a bank.

        The relevant document is the EBICS (Electronic Banking Internet
        Communication Standard; http://www.ebics.de/index.php?id=77).

        This communicates our wish to withdraw funds from the
        participating members. Here we do all the dirty work to conform
        to the standard and produce an acceptable output.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type transactions: [{str: object}]
        :param transactions: Transaction infos from the backend enriched by
          some additional attributes which are necessary.
        :rtype: str
        """
        sanitized_transactions = check(rs, "sepa_transactions", transactions)
        if rs.errors:
            return None
        sorted_transactions = {}
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
                'name': self.conf.SEPA_SENDER_NAME,
                'address': self.conf.SEPA_SENDER_ADDRESS,
                'country': self.conf.SEPA_SENDER_COUNTRY,
                'iban': self.conf.SEPA_SENDER_IBAN,
                'glaeubigerid': self.conf.SEPA_GLAEUBIGERID,
            },
            'payment_date': now().date() + self.conf.SEPA_PAYMENT_OFFSET,
        }
        meta = check(rs, "sepa_meta", meta)
        if rs.errors:
            return None
        sepapain_file = self.fill_template(rs, "other", "pain.008.003.02", {
            'transactions': sorted_transactions, 'meta': meta})
        return sepapain_file

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("lastschrift_id", "id_or_None"))
    def lastschrift_generate_transactions(self, rs, lastschrift_id):
        """Issue direct debit transactions.

        This creates new transactions either for the lastschrift_id
        passed or if that is None, then for all open permits
        (c.f. :py:func:`determine_open_permits`).

        Afterwards it creates and returns an XML-file to send to the
        bank. If this fails all new transactions are directly
        cancelled.
        """
        if rs.errors:
            return self.lastschrift_index(rs)
        stati = const.LastschriftTransactionStati
        period = self.cdeproxy.current_period(rs)
        if not lastschrift_id:
            all_lids = self.cdeproxy.list_lastschrift(rs)
            lastschrift_ids = tuple(self.determine_open_permits(
                rs, all_lids.keys()))
        else:
            lastschrift_ids = (lastschrift_id,)
        lastschrifts = self.cdeproxy.get_lastschrifts(
            rs, lastschrift_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in lastschrifts.values()))
        new_transactions = tuple(
            {
                'issued_at': now(),
                'lastschrift_id': anid,
                'period_id': period,
            } for anid in lastschrift_ids
        )
        transaction_ids = self.cdeproxy.issue_lastschrift_transaction_batch(
            rs, new_transactions, check_unique=True)
        for transaction in new_transactions:
            lastschrift = lastschrifts[transaction['lastschrift_id']]
            persona = personas[lastschrift['persona_id']]
            transaction.update({
                'mandate_reference': lastschrift_reference(
                    persona['id'], lastschrift['id']),
                'amount': lastschrift['amount'],
                'iban': lastschrift['iban'],
            })
            if (lastschrift['granted_at'].date()
                    >= self.conf.SEPA_INITIALISATION_DATE):
                transaction['mandate_date'] = lastschrift['granted_at'].date()
            else:
                transaction['mandate_date'] = self.conf.SEPA_CUTOFF_DATE
            if lastschrift['account_owner']:
                transaction['account_owner'] = lastschrift['account_owner']
            else:
                transaction['account_owner'] = "{} {}".format(
                    persona['given_names'], persona['family_name'])
            timestamp = "{:.6f}".format(now().timestamp())
            transaction['unique_id'] = "{}-{}".format(
                transaction['mandate_reference'], timestamp[-9:])
            transaction['subject'] = glue(
                "{}, {}, {} I25+ Mitgliedsbeitrag u. Spende CdE e.V.",
                "z. Foerderung der Volks- u. Berufsbildung u.",
                "Studentenhilfe").format(
                    cdedbid_filter(persona['id']), persona['family_name'],
                    persona['given_names'])[:140] ## cut off bc of limit
            previous = self.cdeproxy.list_lastschrift_transactions(
                rs, lastschrift_ids=(lastschrift['id'],),
                stati=(stati.success,))
            transaction['type'] = ("RCUR" if previous else "FRST")
        sepapain_file = self.create_sepapain(rs, new_transactions)
        if not sepapain_file:
            ## Validation of SEPA data failed
            for transaction_id in transaction_ids:
                self.cdeproxy.finalize_lastschrift_transaction(
                    rs, transaction_id, stati.cancelled)
            rs.notify("error", _("Creation of SEPA-PAIN-file failed."))
            return self.redirect(rs, "cde/lastschrift_index")
        return self.send_file(rs, data=sepapain_file, inline=False,
                              filename=rs.gettext("sepa.cdd"))

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "id_or_None"))
    def lastschrift_skip(self, rs, lastschrift_id, persona_id):
        """Do not do a direct debit transaction for this year.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.errors:
            return self.lastschrift_index(rs)
        success = self.cdeproxy.lastschrift_skip(rs, lastschrift_id)
        if not success:
            rs.notify("warning", _("Unable to skip transaction."))
        else:
            rs.notify("success", _("Skipped."))
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    def lastschrift_process_transaction(self, rs, transaction_id, status):
        """Process one transaction and store the outcome.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type transaction_id: int
        :type status:
          :py:class:`cdedb.database.constants.LastschriftTransactionStati`
        :rtype: int
        :returns: default return code
        """
        tally = None
        if status == const.LastschriftTransactionStati.failure:
            tally = -self.conf.SEPA_ROLLBACK_FEE
        return self.cdeproxy.finalize_lastschrift_transaction(
            rs, transaction_id, status, tally=tally)

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("status", "enum_lastschrifttransactionstati"),
                 ("persona_id", "id_or_None"))
    def lastschrift_finalize_transaction(self, rs, lastschrift_id,
                                         transaction_id, status, persona_id):
        """Finish one transaction.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.errors:
            return self.lastschrift_index(rs)
        code = self.lastschrift_process_transaction(rs, transaction_id, status)
        self.notify_return_code(rs, code)
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("transaction_ids", "[id]"), ("success", "bool_or_None"),
                 ("cancelled", "bool_or_None"), ("failure", "bool_or_None"))
    def lastschrift_finalize_transactions(self, rs, transaction_ids, success,
                                          cancelled, failure):
        """Finish many transaction."""
        if sum(1 for s in (success, cancelled, failure) if s) != 1:
            rs.errors.append((None, ValueError(_("Wrong number of actions."))))
        if rs.errors:
            return self.lastschrift_index(rs)
        if not transaction_ids:
            rs.notify("warning", _("No transactions selected."))
            return self.redirect(rs, "cde/lastschrift_index")
        status = None
        if success:
            status = const.LastschriftTransactionStati.success
        if cancelled:
            status = const.LastschriftTransactionStati.cancelled
        if failure:
            status = const.LastschriftTransactionStati.failure
        code = 1
        for transaction_id in transaction_ids:
            code *= self.lastschrift_process_transaction(rs, transaction_id,
                                                         status)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/lastschrift_index")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "id_or_None"))
    def lastschrift_rollback_transaction(self, rs, lastschrift_id,
                                         transaction_id, persona_id):
        """Revert a successful transaction.

        The user can cancel a direct debit transaction after the
        fact. So we have to deal with this possibility.
        """
        if rs.errors:
            return self.lastschrift_index(rs)
        tally = -self.conf.SEPA_ROLLBACK_FEE
        code = self.cdeproxy.rollback_lastschrift_transaction(
            rs, transaction_id, tally)
        self.notify_return_code(rs, code)
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    @access("member")
    def lastschrift_receipt(self, rs, lastschrift_id, transaction_id):
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
        words = (
            int_to_words(int(transaction['amount']), rs.lang),
            int_to_words(int(transaction['amount'] * 100) % 100, rs.lang))
        transaction['amount_words'] = words
        meta_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_receipt", {
            'meta_info': meta_info, 'persona': persona, 'addressee': addressee})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir) / 'workdir'
            work_dir.mkdir()
            with open_utf8(work_dir / "lastschrift_receipt.tex", 'w') as f:
                f.write(tex)
            logo_src = self.conf.REPOSITORY_PATH / "misc/cde-logo.jpg"
            shutil_copy(logo_src, work_dir / "cde-logo.jpg")
            return self.serve_complex_latex_document(
                rs, tmp_dir, 'workdir', "lastschrift_receipt.tex")

    @access("anonymous")
    def lastschrift_subscription_form(self, rs):
        """Generate a form for allowing direct debit transactions.

        If we are not anonymous we prefill this with known information.
        """
        persona = None
        minor = True
        if rs.user.persona_id:
            persona = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            minor = determine_age_class(
                persona['birthday'], now().date()).is_minor()
        meta_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_subscription_form", {
            'meta_info': meta_info, 'persona': persona, 'minor': minor})
        return self.serve_latex_document(rs, tex,
                                         "lastschrift_subscription_form")

    @access("anonymous")
    def i25p_index(self, rs):
        """Show information about 'Initiative 25+'."""
        return self.render(rs, "i25p_index")

    @access("cde_admin")
    def show_semester(self, rs):
        """Show information."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        stats = self.cdeproxy.finance_statistics(rs)
        return self.render(rs, "show_semester", {
            'period': period, 'expuls': expuls, 'stats': stats})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("addresscheck", "bool"), ("testrun", "bool"))
    def semester_bill(self, rs, addresscheck, testrun):
        """Send billing mail to all members.

        In case of a test run we send only a single mail to the button
        presser.
        """
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if period['billing_done']:
            rs.notify("error", _("Billing already done."))
            return self.redirect(rs, "show/semester")
        open_lastschrift = self.determine_open_permits(rs)
        ## The rs parameter shadows the outer request state, making sure that
        ## it doesn't leak
        def task(rrs, rs=None):
            """Send one billing mail and advance state."""
            with Atomizer(rrs):
                period_id = self.cdeproxy.current_period(rrs)
                period = self.cdeproxy.get_period(rrs, period_id)
                previous = period['billing_state'] or 0
                persona_id = self.coreproxy.next_persona(rrs, previous)
                if testrun:
                    persona_id = rrs.user.persona_id
                if not persona_id or period['billing_done']:
                    if not period['billing_done']:
                        period_update = {
                            'id': period_id,
                            'billing_state': None,
                            'billing_done': now(),
                        }
                        self.cdeproxy.set_period(rrs, period_update)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                lastschrift_list = self.cdeproxy.list_lastschrift(
                    rrs, persona_ids=(persona_id,))
                lastschrift = None
                if lastschrift_list:
                    lastschrift = self.cdeproxy.get_lastschrift(
                        rrs, unwrap(lastschrift_list))
                    lastschrift['reference'] = lastschrift_reference(
                        persona['id'], lastschrift['id'])
                address = make_postal_address(persona)
                transaction_subject = make_transaction_subject(persona)
                self.do_mail(
                    rrs, "billing",
                    {'To': (persona['username'],),
                     'Subject': _('Renew your CdE membership')},
                    {'persona': persona,
                     'fee': self.conf.MEMBERSHIP_FEE,
                     'lastschrift': lastschrift,
                     'open_lastschrift': open_lastschrift,
                     'address': address,
                     'transaction_subject': transaction_subject,
                     'addresscheck': addresscheck,})
                if testrun:
                    return False
                period_update = {
                    'id': period_id,
                    'billing_state': persona_id,
                }
                self.cdeproxy.set_period(rrs, period_update)
                return True
        worker = Worker(self.conf, task, rs)
        worker.start()
        rs.notify("success", _("Started sending mail."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_eject(self, rs):
        """Eject members without enough credit."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['billing_done'] or period['ejection_done']:
            rs.notify("error", _("Wrong timing for ejection."))
            return self.redirect(rs, "show/semester")
        ## The rs parameter shadows the outer request state, making sure that
        ## it doesn't leak
        def task(rrs, rs=None):
            """Check one member for ejection and advance state."""
            with Atomizer(rrs):
                period_id = self.cdeproxy.current_period(rrs)
                period = self.cdeproxy.get_period(rrs, period_id)
                previous = period['ejection_state'] or 0
                persona_id = self.coreproxy.next_persona(rrs, previous)
                if not persona_id or period['ejection_done']:
                    if not period['ejection_done']:
                        period_update = {
                            'id': period_id,
                            'ejection_state': None,
                            'ejection_done': now(),
                        }
                        self.cdeproxy.set_period(rrs, period_update)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                if (persona['balance'] < self.conf.MEMBERSHIP_FEE
                        and not persona['trial_member']):
                    self.coreproxy.change_membership(rrs, persona_id,
                                                     is_member=False)
                    transaction_subject = make_transaction_subject(persona)
                    self.do_mail(
                        rrs, "ejection",
                        {'To': (persona['username'],),
                         'Subject': _('Ejection from CdE')},
                        {'persona': persona,
                         'fee': self.conf.MEMBERSHIP_FEE,
                         'transaction_subject': transaction_subject,})
                period_update = {
                    'id': period_id,
                    'ejection_state': persona_id,
                }
                self.cdeproxy.set_period(rrs, period_update)
                return True
        worker = Worker(self.conf, task, rs)
        worker.start()
        rs.notify("success", _("Started ejection."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_balance_update(self, rs):
        """Deduct membership fees from all member accounts."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['ejection_done'] or period['balance_done']:
            rs.notify("error", _("Wrong timing for balance update."))
            return self.redirect(rs, "show/semester")
        ## The rs parameter shadows the outer request state, making sure that
        ## it doesn't leak
        def task(rrs, rs=None):
            """Update one members balance and advance state."""
            with Atomizer(rrs):
                period_id = self.cdeproxy.current_period(rrs)
                period = self.cdeproxy.get_period(rrs, period_id)
                previous = period['balance_state'] or 0
                persona_id = self.coreproxy.next_persona(rrs, previous)
                if not persona_id or period['balance_done']:
                    if not period['balance_done']:
                        period_update = {
                            'id': period_id,
                            'balance_state': None,
                            'balance_done': now(),
                        }
                        self.cdeproxy.set_period(rrs, period_update)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                if (persona['balance'] < self.conf.MEMBERSHIP_FEE
                        and not persona['trial_member']):
                    raise ValueError(_("Balance too low."))
                else:
                    if persona['trial_member']:
                        update = {
                            'id': persona_id,
                            'trial_member': False,
                        }
                        self.coreproxy.change_persona(
                            rrs, update, change_note=rrs.gettext(
                                _("End trial membership.")))
                    else:
                        new_b = persona['balance'] - self.conf.MEMBERSHIP_FEE
                        self.coreproxy.change_persona_balance(
                            rrs, persona_id, new_b,
                            const.FinanceLogCodes.deduct_membership_fee)
                period_update = {
                    'id': period_id,
                    'balance_state': persona_id,
                }
                self.cdeproxy.set_period(rrs, period_update)
                return True
        worker = Worker(self.conf, task, rs)
        worker.start()
        rs.notify("success", _("Started updating balance."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_advance(self, rs):
        """Proceed to next period."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['balance_done']:
            rs.notify("error", _("Wrong timing for advancing the semester."))
            return self.redirect(rs, "show/semester")
        self.cdeproxy.create_period(rs)
        rs.notify("success", _("New period started."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("testrun", "bool"), ("skip", "bool"))
    def expuls_addresscheck(self, rs, testrun, skip):
        """Send address check mail to all members.

        In case of a test run we send only a single mail to the button
        presser.
        """
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if expuls['addresscheck_done']:
            rs.notify("error", _("Addresscheck already done."))
            return self.redirect(rs, "show/semester")
        ## The rs parameter shadows the outer request state, making sure that
        ## it doesn't leak
        def task(rrs, rs=None):
            """Send one address check mail and advance state."""
            with Atomizer(rrs):
                expuls_id = self.cdeproxy.current_expuls(rrs)
                expuls = self.cdeproxy.get_expuls(rrs, expuls_id)
                previous = expuls['addresscheck_state'] or 0
                persona_id = self.coreproxy.next_persona(rrs, previous)
                if testrun:
                    persona_id = rrs.user.persona_id
                if not persona_id or expuls['addresscheck_done']:
                    if not expuls['addresscheck_done']:
                        expuls_update = {
                            'id': expuls_id,
                            'addresscheck_state': None,
                            'addresscheck_done': now(),
                        }
                        self.cdeproxy.set_expuls(rrs, expuls_update)
                    return False
                persona = self.coreproxy.get_cde_user(rrs, persona_id)
                address = make_postal_address(persona)
                lastschrift_list = self.cdeproxy.list_lastschrift(
                    rrs, persona_ids=(persona_id,))
                lastschrift = None
                if lastschrift_list:
                    lastschrift = self.cdeproxy.get_lastschrift(
                        rrs, unwrap(lastschrift_list))
                    lastschrift['reference'] = lastschrift_reference(
                        persona['id'], lastschrift['id'])
                self.do_mail(
                    rrs, "addresscheck",
                    {'To': (persona['username'],),
                     'Subject': _('Address check mail for ExPuls')},
                    {'persona': persona,
                     'lastschrift': lastschrift,
                     'fee': self.conf.MEMBERSHIP_FEE,
                     'address': address,})
                if testrun:
                    return False
                expuls_update = {
                    'id': expuls_id,
                    'addresscheck_state': persona_id,
                }
                self.cdeproxy.set_expuls(rrs, expuls_update)
                return True
        if skip:
            expuls_update = {
                'id': expuls_id,
                'addresscheck_state': None,
                'addresscheck_done': now(),
                }
            self.cdeproxy.set_expuls(rs, expuls_update)
            rs.notify("success", _("Not sending mail."))
        else:
            worker = Worker(self.conf, task, rs)
            worker.start()
            rs.notify("success", _("Started sending mail."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def expuls_advance(self, rs):
        """Proceed to next expuls."""
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if not expuls['addresscheck_done']:
            rs.notify("error", _("Addresscheck not done."))
            return self.redirect(rs, "show/semester")
        self.cdeproxy.create_expuls(rs)
        rs.notify("success", _("New expuls started."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin")
    def institution_summary_form(self, rs):
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
        event_ids = self.eventproxy.list_db_events(rs)
        events = self.eventproxy.get_events(rs, event_ids.keys())
        pevent_ids = self.pasteventproxy.list_past_events(rs)
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids.keys())
        for event in events.values():
            is_referenced.add(event['institution'])
        for pevent in pevents.values():
            is_referenced.add(pevent['institution'])
        return self.render(rs, "institution_summary", {
            'institutions': institutions, 'is_referenced': is_referenced})

    @staticmethod
    def process_institution_input(rs, institutions):
        """This handles input to configure the institutions.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type institutions: [int]
        :param institutions: ids of existing institutions
        :rtype: {int: {str: object} or None}
        """
        delete_flags = request_extractor(
            rs, (("delete_{}".format(institution_id), "bool")
                 for institution_id in institutions))
        deletes = {institution_id for institution_id in institutions
                   if delete_flags['delete_{}'.format(institution_id)]}
        spec = {
            'title': "str",
            'moniker': "str",
        }
        params = tuple(("{}_{}".format(key, institution_id), value)
                       for institution_id in institutions
                       if institution_id not in deletes
                       for key, value in spec.items())
        data = request_extractor(rs, params)
        ret = {
            institution_id: {key: data["{}_{}".format(key, institution_id)]
                             for key in spec}
            for institution_id in institutions if institution_id not in deletes
        }
        for institution_id in institutions:
            if institution_id in deletes:
                ret[institution_id] = None
            else:
                ret[institution_id]['id'] = institution_id
        marker = 1
        while marker < 2**10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_extractor(rs, params)
                ret[-marker] = {key: data["{}_-{}".format(key, marker)]
                                for key in spec}
            else:
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("cde_admin", modi={"POST"})
    def institution_summary(self, rs):
        """Manipulate organisations which are behind events."""
        institution_ids = self.pasteventproxy.list_institutions(rs)
        institutions = self.process_institution_input(
            rs, institution_ids.keys())
        if rs.errors:
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
                    ## Do not update unchanged
                    if current != institution:
                        code *= self.pasteventproxy.set_institution(
                            rs, institution)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/institution_summary_form")

    def process_participants(self, rs, pevent_id, pcourse_id=None):
        """Helper to pretty up participation infos.

        The problem is, that multiple participations can be logged for a
        persona per event (easiest example multiple courses in multiple
        parts). So here we fuse these entries into one per persona.

        Note that the returned dict of participants is already sorted.

        :type rs: :py:class:`FrontendRequestState`
        :type pevent_id: int
        :type pcourse_id: int or None
        :param pcourse_id: if not None, restrict to participants of this
          course
        :rtype: ({int: {str: object}}, {int: {str: object}}, int)
        :returns: This returns three things: the processed participants,
          the persona data sets of the participants and the number of
          redacted participants.
        """
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        privileged = is_participant or self.is_admin(rs)
        participants = {}
        personas = {}
        extra_participants = 0
        if (privileged or ("searchable" in rs.user.roles)):
            persona_ids = {persona_id
                           for persona_id, _ in participant_infos.keys()}
            for persona_id in persona_ids:
                base_set = tuple(x for x in participant_infos.values()
                                 if x['persona_id'] == persona_id)
                entry = {
                    'pevent_id': pevent_id,
                    'persona_id': persona_id,
                    'is_orga': any(x['is_orga'] for x in base_set),
                    }
                entry['pcourse_ids'] = tuple(x['pcourse_id'] for x in base_set)
                entry['is_instructor'] = any(x['is_instructor']
                                             for x in base_set
                                             if (x['pcourse_id'] == pcourse_id
                                                 or not pcourse_id))
                if pcourse_id and pcourse_id not in entry['pcourse_ids']:
                    ## remove non-participants with respect to the relevant
                    ## course if there is a relevant course
                    continue
                participants[persona_id] = entry

            personas = self.coreproxy.get_personas(rs, participants.keys())
            participants = OrderedDict(sorted(
                participants.items(), key=lambda x: name_key(personas[x[0]])))
        if participants and not privileged:
            for anid, persona in personas.items():
                if not persona['is_searchable'] or not persona['is_member']:
                    del participants[anid]
                    extra_participants += 1
        for anid in participants:
            participants[anid]['viewable'] = (self.is_admin(rs)
                                              or anid == rs.user.persona_id)
        if "searchable" in rs.user.roles:
            for anid in participants:
                if personas[anid]['is_searchable']:
                    participants[anid]['viewable'] = True
        return participants, personas, extra_participants

    @access("cde")
    def show_past_event(self, rs, pevent_id):
        """Display concluded event."""
        course_ids = self.pasteventproxy.list_past_courses(rs, pevent_id)
        courses = self.pasteventproxy.get_past_courses(rs, course_ids)
        institutions = self.pasteventproxy.list_institutions(rs)
        participants, personas, extra_participants = self.process_participants(
            rs, pevent_id)
        return self.render(rs, "show_past_event", {
            'courses': courses, 'participants': participants,
            'personas': personas, 'institutions': institutions,
            'extra_participants': extra_participants})

    @access("cde")
    def show_past_course(self, rs, pevent_id, pcourse_id):
        """Display concluded course."""
        participants, personas, extra_participants = self.process_participants(
            rs, pevent_id, pcourse_id=pcourse_id)
        return self.render(rs, "show_past_course", {
            'participants': participants, 'personas': personas,
            'extra_participants': extra_participants})

    @access("cde")
    def list_past_events(self, rs):
        """List all concluded events."""
        events = self.pasteventproxy.list_past_events(rs)
        stats = self.pasteventproxy.past_event_stats(rs)
        # Generate (reverse) chronologically sorted list of past event ids
        stats_sorter = sorted(
            stats.keys(), key=lambda x: stats[x]['tempus'], reverse=True)
        # Bunch past events by years
        # Using idea from http://stackoverflow.com/a/8983196
        years = {}
        for anid in stats_sorter:
            years.setdefault(stats[anid]['tempus'].year, []).append(anid)
        return self.render(rs, "list_past_events", {
            'events': events, 'stats': stats, 'years': years})

    @access("cde_admin")
    def change_past_event_form(self, rs, pevent_id):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        merge_dicts(rs.values, rs.ambience['pevent'])
        return self.render(rs, "change_past_event", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("title", "shortname", "institution", "description",
                     "tempus")
    def change_past_event(self, rs, pevent_id, data):
        """Modify a concluded event."""
        data['id'] = pevent_id
        data = check(rs, "past_event", data)
        if rs.errors:
            return self.change_past_event_form(rs, pevent_id)
        code = self.pasteventproxy.set_past_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin")
    def create_past_event_form(self, rs):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        return self.render(rs, "create_past_event", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("courses", "str_or_None"))
    @REQUESTdatadict("title", "shortname", "institution", "description",
                     "tempus")
    def create_past_event(self, rs, courses, data):
        """Add new concluded event."""
        data = check(rs, "past_event", data, creation=True)
        thecourses = []
        if courses:
            courselines = courses.split('\n')
            reader = csv.DictReader(
                courselines, fieldnames=("nr", "title", "description"),
                delimiter=';', quoting=csv.QUOTE_MINIMAL,
                quotechar='"', doublequote=False, escapechar='\\')
            lineno = 0
            for entry in reader:
                lineno += 1
                entry['pevent_id'] = 1
                entry = check(rs, "past_course", entry, creation=True)
                if entry:
                    thecourses.append(entry)
                else:
                    rs.notify("warning", _("Line {lineno} is faulty."),
                              {'lineno': lineno})
        if rs.errors:
            return self.create_past_event_form(rs)
        with Atomizer(rs):
            new_id = self.pasteventproxy.create_past_event(rs, data)
            for course in thecourses:
                course['pevent_id'] = new_id
                self.pasteventproxy.create_past_course(rs, course)
        self.notify_return_code(rs, new_id, success=_("Event created."))
        return self.redirect(rs, "cde/show_past_event", {'pevent_id': new_id})

    @access("cde_admin")
    def change_past_course_form(self, rs, pevent_id, pcourse_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['pcourse'])
        return self.render(rs, "change_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("nr", "title", "description")
    def change_past_course(self, rs, pevent_id, pcourse_id, data):
        """Modify a concluded course."""
        data['id'] = pcourse_id
        data = check(rs, "past_course", data)
        if rs.errors:
            return self.change_past_course_form(rs, pevent_id, pcourse_id)
        code = self.pasteventproxy.set_past_course(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_course")

    @access("cde_admin")
    def create_past_course_form(self, rs, pevent_id):
        """Render form."""
        return self.render(rs, "create_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("nr", "title", "description")
    def create_past_course(self, rs, pevent_id, data):
        """Add new concluded course."""
        data['pevent_id'] = pevent_id
        data = check(rs, "past_course", data, creation=True)
        if rs.errors:
            return self.create_past_course_form(rs, pevent_id)
        new_id = self.pasteventproxy.create_past_course(rs, data)
        self.notify_return_code(rs, new_id, success=_("Course created."))
        return self.redirect(rs, "cde/show_past_course", {'pcourse_id': new_id})

    @access("cde_admin", modi={"POST"})
    def delete_past_course(self, rs, pevent_id, pcourse_id):
        """Delete a concluded course.

        This also deletes all participation information w.r.t. this course.
        """
        code = self.pasteventproxy.delete_past_course(rs, pcourse_id,
                                                      cascade=True)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("pcourse_id", "id_or_None"), ("persona_id", "cdedbid"),
                 ("is_instructor", "bool"), ("is_orga", "bool"))
    def add_participant(self, rs, pevent_id, pcourse_id, persona_id,
                        is_instructor, is_orga):
        """Add participant to concluded event."""
        if rs.errors:
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)
        if pcourse_id:
            param = {'pcourse_id': pcourse_id}
        else:
            param = {'pevent_id': pevent_id}
        participants = self.pasteventproxy.list_participants(rs, **param)
        if persona_id in participants:
            rs.notify("warning", _("Participant already present."))
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)
        code = self.pasteventproxy.add_participant(
            rs, pevent_id, pcourse_id, persona_id, is_instructor, is_orga)
        self.notify_return_code(rs, code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course",
                                 {'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "id"), ("pcourse_id", "id_or_None"))
    def remove_participant(self, rs, pevent_id, persona_id, pcourse_id):
        """Remove participant."""
        if rs.errors:
            return self.show_event(rs, pevent_id)
        code = self.pasteventproxy.remove_participant(
            rs, pevent_id, pcourse_id, persona_id)
        self.notify_return_code(rs, code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course", {
                'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_cde_log(self, rs, codes, persona_id, start, stop):
        """View general activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.cdeproxy.retrieve_cde_log(rs, codes, persona_id, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_cde_log", {
            'log': log, 'personas': personas})

    @access("cde_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_finance_log(self, rs, codes, persona_id, start, stop):
        """View financial activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.cdeproxy.retrieve_finance_log(
            rs, codes, persona_id, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_finance_log", {
            'log': log, 'personas': personas})

    @access("cde_admin")
    @REQUESTdata(("codes", "[int]"), ("pevent_id", "id_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_past_log(self, rs, codes, pevent_id, start, stop):
        """View activities concerning concluded events."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.pasteventproxy.retrieve_past_log(
            rs, codes, pevent_id, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        pevent_ids = {entry['pevent_id'] for entry in log if entry['pevent_id']}
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids)
        return self.render(rs, "view_past_log", {
            'log': log, 'personas': personas, 'pevents': pevents})
