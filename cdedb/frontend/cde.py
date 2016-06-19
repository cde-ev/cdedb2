#!/usr/bin/env python3

"""Services for the cde realm."""

from collections import OrderedDict
import copy
import csv
import hashlib
import itertools
import logging
import os.path
import random
import shutil
import string
import tempfile
import werkzeug

import cdedb.database.constants as const
import cdedb.validation as validate
from cdedb.database.connection import Atomizer
from cdedb.common import (
    merge_dicts, name_key, lastschrift_reference, now, glue, unwrap,
    int_to_words, determine_age_class, LineResolutions, PERSONA_DEFAULTS,
    ProxyShim)
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access, Worker,
    check_validation as check, cdedbid_filter, request_data_extractor,
    make_postal_address, make_transaction_subject)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input, QueryOperators
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
    logger = logging.getLogger(__name__)
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_cde_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(CdEBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs):
        super().finalize_session(rs)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        """Render start page."""
        return self.render(rs, "index")

    @access("cde")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        data = self.coreproxy.get_cde_user(rs, persona_id)
        participation_info = self.pasteventproxy.participation_info(
            rs, persona_id)
        params = {
            'data': data,
            'participation_info': participation_info,
        }
        if data['is_archived']:
            if self.is_admin(rs):
                return self.render(rs, "show_archived_user", params)
            else:
                rs.notify("error", "Accessing archived member impossible.")
                return self.redirect(rs, "core/index")
        else:
            return self.render(rs, "show_user", params)

    @access("cde_admin")
    def admin_change_user_form(self, rs, persona_id):
        return super().admin_change_user_form(rs, persona_id)


    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "birth_name", "gender", "birthday", "telephone",
        "mobile", "address_supplement", "address", "postal_code",
        "location", "country", "address_supplement2", "address2",
        "postal_code2", "location2", "country2", "weblink",
        "specialisation", "affiliation", "timeline", "interests",
        "free_form", "bub_search", "cloud_account", "notes")
    def admin_change_user(self, rs, persona_id, generation, change_note, data):
        return super().admin_change_user(rs, persona_id, generation,
                                         change_note, data)

    @access("cde")
    def get_foto(self, rs, foto):
        """Retrieve profile picture."""
        path = os.path.join(self.conf.STORAGE_DIR, "foto", foto)
        return self.send_file(rs, path=path)

    @access("cde")
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden("Not privileged.")
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "set_foto", {'data': data})

    @access("cde", modi={"POST"})
    @REQUESTfile("foto")
    def set_foto(self, rs, persona_id, foto):
        """Set profile picture."""
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise werkzeug.exceptions.Forbidden("Not privileged.")
        foto = check(rs, 'profilepic', foto, "foto")
        if rs.errors:
            return self.set_foto_form(rs, persona_id)
        previous = self.coreproxy.get_cde_user(rs, persona_id)['foto']
        myhash = hashlib.sha512()
        myhash.update(foto)
        path = os.path.join(self.conf.STORAGE_DIR, 'foto', myhash.hexdigest())
        if not os.path.isfile(path):
            with open(path, 'wb') as f:
                f.write(foto)
        code = self.coreproxy.change_foto(rs, persona_id,
                                          foto=myhash.hexdigest())
        if previous:
            if not self.coreproxy.foto_usage(rs, previous):
                path = os.path.join(self.conf.STORAGE_DIR, 'foto', previous)
                os.remove(path)
        self.notify_return_code(rs, code, success="Foto updated.")
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def consent_decision_form(self, rs):
        """After login ask cde members for decision about searchability. Do
        this only if no decision has been made in the past.

        This is the default page after login, but most users will instantly
        be redirected.
        """
        if "member" not in rs.user.roles or "searchable" in rs.user.roles:
            return self.redirect(rs, "core/index")
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        return self.render(rs, "consent_decision")

    @access("member", modi={"POST"})
    @REQUESTdata(("ack", "bool"))
    def consent_decision(self, rs, ack):
        """Record decision."""
        if rs.errors:
            return self.consent_decision_form(rs)
        data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        new_data = {
            'id': rs.user.persona_id,
            'decided_search': True,
            'is_searchable': ack,
        }
        change_note = "Consent decision (is {}).".format(ack)
        code = self.coreproxy.change_persona(
            rs, new_data, generation=None, may_wait=False,
            change_note=change_note)
        message = "Consent noted." if ack else "Decision noted."
        self.notify_return_code(rs, code, success=message)
        if not code:
            return self.consent_decision_form(rs)
        return self.redirect(rs, "core/index")

    @access("searchable")
    @REQUESTdata(("is_search", "bool"))
    def member_search(self, rs, is_search):
        """Search for members."""
        spec = QUERY_SPECS['qview_cde_member']
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
                return self.redirect_show_user(rs, result[0]['id'])
            if (len(result) > self.conf.MAX_QUERY_RESULTS
                    and not self.is_admin(rs)):
                result = result[:self.conf.MAX_QUERY_RESULTS]
                rs.notify("info", "Too many query results.")
        return self.render(rs, "member_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'result': result})

    @access("cde_admin")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    def user_search(self, rs, CSV, is_search):
        """Perform search."""
        spec = QUERY_SPECS['qview_cde_user']
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
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries, 'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_cde_user"
            result = self.cdeproxy.submit_general_query(rs, query)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("cde_admin")
    def modify_membership_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "modify_membership", {'data': data})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("is_member", "bool"))
    def modify_membership(self, rs, persona_id, is_member):
        """Change association status."""
        if rs.errors:
            return self.modify_membership_form(rs, persona_id)
        code = self.coreproxy.change_membership(rs, persona_id, is_member)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

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

    def genesis_form(self, rs, case_id, secret):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available in cde realm.")

    def genesis(self, rs, case_id, secret, data):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available in cde realm.")

    @access("cde_admin")
    def batch_admission_form(self, rs, data=None):
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
        return self.render(rs, "batch_admission", {
            'data': data, 'LineResolutions': LineResolutions,})

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
            warnings.append((None, ValueError("Entry changed.")))
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
        pevent_id, p = self.pasteventproxy.find_past_event(
            rs, datum['raw']['event'])
        problems.extend(p)
        pcourse_id = None
        if datum['raw']['course'] and pevent_id:
            pcourse_id, p = self.pasteventproxy.find_past_course(
                rs, datum['raw']['course'], pevent_id)
            problems.extend(p)
        else:
            warnings.append(("course", ValueError("No course available.")))
        doppelgangers = tuple()
        if persona:
            temp = copy.deepcopy(persona)
            temp['id'] = 1
            doppelgangers = self.coreproxy.find_doppelgangers(rs, temp)
        if doppelgangers:
            warnings.append(("persona", ValueError("Doppelgangers found.")))
        if (datum['resolution'] is not None and
                (bool(datum['doppelganger_id'])
                 != datum['resolution'].is_modification())):
            problems.append(
                ("doppelganger",
                 RuntimeError("Doppelganger choice doesn't fit resolution.")))
        if datum['doppelganger_id']:
            if datum['doppelganger_id'] not in doppelgangers:
                problems.append(
                    ("doppelganger", KeyError("Doppelganger unavailable.")))
            else:
                if not doppelgangers[datum['doppelganger_id']]['is_cde_realm']:
                    problems.append(
                        ("doppelganger",
                         ValueError("Doppelganger not a CdE-Account.")))
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
                    if datum['resolution'] == LineResolutions.skip:
                        continue
                    elif datum['resolution'] == LineResolutions.create:
                        datum['persona'].update({
                            'is_member': True,
                            'trial_member': trial_membership,
                            'is_searchable': consent,
                            })
                        self.coreproxy.create_persona(rs, datum['persona'])
                        count += 1
                    elif datum['resolution'].is_modification():
                        if datum['resolution'].do_trial():
                            self.coreproxy.change_membership(
                                rs, datum['doppelganger_id'], is_member=True)
                            update = {
                                'id': datum['doppelganger_id'],
                                'trial_member': True,
                            }
                            self.coreproxy.change_persona(
                                rs, update, may_wait=False,
                                change_note="Renewed trial membership.")
                        if datum['resolution'].do_update():
                            update = {'id': datum['doppelganger_id']}
                            for field in fields:
                                update[field] = datum['persona'][field]
                            self.coreproxy.change_persona(
                                rs, update, may_wait=False,
                                change_note="Imported recent data.")
                            self.coreproxy.change_username(
                                rs, datum['doppelganger_id'],
                                datum['persona']['username'], password=None)
                    else:
                        raise RuntimeError("Impossible.")
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
                                  'Subject': 'CdE admission',},
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
        accountlines = accounts.splitlines()
        fields = (
            'event', 'course', 'family_name', 'given_names', 'title',
            'name_supplement', 'birth_name', 'gender', 'address_supplement',
            'address', 'postal_code', 'location', 'country', 'telephone',
            'mobile', 'username', 'birthday')
        reader = csv.DictReader(
            accountlines, fieldnames=fields, delimiter=';',
            quoting=csv.QUOTE_ALL, doublequote=True, quotechar='"')
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset = {'raw': raw_entry}
            params = (
                ("resolution{}".format(lineno), "enum_lineresolutions_or_None"),
                ("doppelganger_id{}".format(lineno), "id_or_None"),
                ("hash{}".format(lineno), "str_or_None"),)
            tmp = request_data_extractor(rs, params)
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
                    "Lines {} and {} are the same.".format(ds1['lineno'],
                                                           ds2['lineno'])))
                ds1['problems'].append(problem)
                ds2['problems'].append(problem)
            elif similarity == "medium":
                warning = (None, ValueError(
                    "Lines {} and {} look the same.".format(ds1['lineno'],
                                                            ds2['lineno'])))
                ds1['warnings'].append(warning)
                ds2['warnings'].append(warning)
            elif similarity == "low":
                pass
            else:
                raise RuntimeError("Impossible.")
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
            rs.errors.append(("accounts", ValueError("Lines didn't match up.")))
        if not membership:
            rs.errors.append(("membership",
                              ValueError("Only member admission supported.")))
        open_issues = any(
            e['resolution'] is None
            or (e['problems'] and e['resolution'] != LineResolutions.skip)
            for e in data)
        if rs.errors or not data or open_issues:
            return self.batch_admission_form(rs, data=data)
        if not finalized:
            rs.values['finalized'] = True
            return self.batch_admission_form(rs, data=data)

        ## Here we have survived all validation
        success, num = self.perform_batch_admission(rs, data, trial_membership,
                                                    consent, sendmail)
        if success:
            rs.notify("success", "Created {} accounts.".format(num))
            return self.redirect(rs, "cde/index")
        else:
            if num is None:
                rs.notify("warning", "DB serialization error.")
            else:
                rs.notify("error", "Unexpected error on line {}.".format(num))
            return self.batch_admission_form(rs, data=data)

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
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_cde_log", {
            'log': log, 'persona_data': persona_data})

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
        lastschrift_data = self.cdeproxy.get_lastschrift(rs,
                                                         lastschrift_ids.keys())
        period = self.cdeproxy.current_period(rs)
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, periods=(period,),
            stati=(const.LastschriftTransactionStati.issued,))
        transaction_data = self.cdeproxy.get_lastschrift_transactions(
            rs, transaction_ids.keys())
        persona_ids = set(lastschrift_ids.values()).union({
            x['submitted_by'] for x in lastschrift_data.values()})
        persona_data = self.coreproxy.get_personas(rs, persona_ids)
        open_permits = self.determine_open_permits(rs, lastschrift_ids)
        for lastschrift in lastschrift_data.values():
            lastschrift['open'] = lastschrift['id'] in open_permits
        return self.render(rs, "lastschrift_index", {
            'lastschrift_data': lastschrift_data, 'persona_data': persona_data,
            'transaction_data': transaction_data})

    @access("member")
    def lastschrift_show(self, rs, persona_id):
        """Display all lastschrift information for one member.

        Especially all permits and transactions.
        """
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        lastschrift_ids = self.cdeproxy.list_lastschrift(
            rs, persona_ids=(persona_id,), active=None)
        lastschrift_data = self.cdeproxy.get_lastschrift(rs,
                                                         lastschrift_ids.keys())
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=lastschrift_ids.keys())
        transaction_data = self.cdeproxy.get_lastschrift_transactions(
            rs, transaction_ids.keys())
        persona_ids = {persona_id}.union({
            x['submitted_by'] for x in lastschrift_data.values()}).union({
                x['submitted_by'] for x in transaction_data.values()})
        persona_data = self.coreproxy.get_personas(rs, persona_ids)
        active_permit = None
        for lastschrift in lastschrift_data.values():
            if not lastschrift['revoked_at']:
                active_permit = lastschrift['id']
        active_open = bool(
            active_permit and self.determine_open_permits(rs, (active_permit,)))
        return self.render(rs, "lastschrift_show", {
            'lastschrift_data': lastschrift_data,
            'active_permit': active_permit, 'active_open': active_open,
            'persona_data': persona_data, 'transaction_data': transaction_data,
            })

    @access("cde_admin")
    def lastschrift_change_form(self, rs, lastschrift_id):
        """Render form."""
        lastschrift_data = self.cdeproxy.get_lastschrift_one(rs, lastschrift_id)
        merge_dicts(rs.values, lastschrift_data)
        persona_data = self.coreproxy.get_persona(
            rs, lastschrift_data['persona_id'])
        return self.render(rs, "lastschrift_change", {
            'lastschrift_data': lastschrift_data, 'persona_data': persona_data})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict('amount', 'iban', 'account_owner', 'account_address',
                     'notes', 'max_dsa',)
    def lastschrift_change(self, rs, lastschrift_id, data):
        """Modify one permit."""
        data['id'] = lastschrift_id
        data = check(rs, "lastschrift_data", data)
        if rs.errors:
            return self.lastschrift_change_form(rs, lastschrift_id)
        code = self.cdeproxy.set_lastschrift(rs, data)
        lastschrift = self.cdeproxy.get_lastschrift_one(rs, lastschrift_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': lastschrift['persona_id']})

    @access("cde_admin")
    def lastschrift_create_form(self, rs, persona_id):
        """Render form."""
        persona_data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "lastschrift_create", {
            'persona_data': persona_data})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict('amount', 'iban', 'account_owner', 'account_address',
                     'notes', 'max_dsa')
    def lastschrift_create(self, rs, persona_id, data):
        """Create a new permit."""
        data['persona_id'] = persona_id
        data = check(rs, "lastschrift_data", data, creation=True)
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
        self.notify_return_code(rs, code, success="Permit revoked.")
        lastschrift = self.cdeproxy.get_lastschrift_one(rs, lastschrift_id)
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': lastschrift['persona_id']})

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
        sanitized_transactions = check(rs, "sepa_data", transactions)
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
        lastschrift_data = self.cdeproxy.get_lastschrift(
            rs, lastschrift_ids)
        persona_data = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in lastschrift_data.values()))
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
            lastschrift = lastschrift_data[transaction['lastschrift_id']]
            pdata = persona_data[lastschrift['persona_id']]
            transaction.update({
                'mandate_reference': lastschrift_reference(
                    pdata['id'], lastschrift['id']),
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
                    pdata['given_names'], pdata['family_name'])
            timestamp = "{:.6f}".format(now().timestamp())
            transaction['unique_id'] = "{}-{}".format(
                transaction['mandate_reference'], timestamp[-9:])
            transaction['subject'] = glue(
                "{}, {}, {} I25+ Mitgliedsbeitrag u. Spende CdE e.V.",
                "z. Foerderung der Volks- u. Berufsbildung u.",
                "Studentenhilfe").format(
                    cdedbid_filter(pdata['id']), pdata['family_name'],
                    pdata['given_names'])[:140] ## cut off bc of limit
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
            rs.notify("error", "Creation of SEPA-PAIN-file failed.")
            return self.lastschrift_index(rs)
        return self.send_file(rs, data=sepapain_file, inline=False,
                              filename=self.i18n("sepa.cdd", rs.lang))

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "id_or_None"))
    def lastschrift_skip(self, rs, lastschrift_id, persona_id):
        """Do not do a direct debit transaction for this year.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.errors:
            return self.redirect(rs, "cde/lastschrift_index")
        success = self.cdeproxy.lastschrift_skip(rs, lastschrift_id)
        if not success:
            rs.notify("warning", "Unable to skip transaction.")
        else:
            rs.notify("success", "Skipped.")
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
            return self.redirect(rs, "cde/lastschrift_index")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("status", "enum_lastschrifttransactionstati"),
                 ("persona_id", "id_or_None"))
    def lastschrift_finalize_transaction(self, rs, lastschrift_id,
                                         transaction_id, status, persona_id):
        """Process a transaction and store the outcome.

        If persona_id is given return to the persona-specific
        lastschrift page, otherwise return to a general lastschrift
        page.
        """
        if rs.errors:
            return self.redirect(rs, "cde/lastschrift_index")
        tally = None
        if status == const.LastschriftTransactionStati.failure:
            tally = -self.conf.SEPA_ROLLBACK_FEE
        code = self.cdeproxy.finalize_lastschrift_transaction(
            rs, transaction_id, status, tally=tally)
        self.notify_return_code(rs, code)
        if persona_id:
            return self.redirect(rs, "cde/lastschrift_show",
                                 {'persona_id': persona_id})
        else:
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
            return self.redirect(rs, "cde/lastschrift_index")
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
        lastschrift_data = self.cdeproxy.get_lastschrift_one(
            rs, lastschrift_id)
        transaction_data = self.cdeproxy.get_lastschrift_transaction(
            rs, transaction_id)
        persona_data = self.coreproxy.get_cde_user(
            rs, lastschrift_data['persona_id'])
        addressee = make_postal_address(persona_data)
        if lastschrift_data['account_owner']:
            addressee[0] = lastschrift_data['account_owner']
        if lastschrift_data['account_address']:
            addressee = addressee[:1]
            addressee.extend(lastschrift_data['account_address'].split('\n'))
        words = (
            int_to_words(int(transaction_data['amount']), rs.lang),
            int_to_words(int(transaction_data['amount'] * 100) % 100, rs.lang))
        transaction_data['amount_words'] = words
        cde_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_receipt", {
            'lastschrift_data': lastschrift_data, 'cde_info': cde_info,
            'transaction_data': transaction_data, 'persona_data': persona_data,
            'addressee': addressee})
        with tempfile.TemporaryDirectory() as tmp_dir:
            j = os.path.join
            work_dir = j(tmp_dir, 'workdir')
            os.mkdir(work_dir)
            with open(j(work_dir, "lastschrift_receipt.tex"), 'w') as f:
                f.write(tex)
            logo_src = j(self.conf.REPOSITORY_PATH, "misc/cde-logo.jpg")
            shutil.copy(logo_src, j(work_dir, "cde-logo.jpg"))
            return self.serve_complex_latex_document(
                rs, tmp_dir, 'workdir', "lastschrift_receipt.tex")

    @access("anonymous")
    def lastschrift_subscription_form(self, rs):
        """Generate a form for allowing direct debit transactions.

        If we are not anonymous we prefill this with known information.
        """
        persona_data = None
        minor = True
        if rs.user.persona_id:
            persona_data = self.coreproxy.get_cde_user(rs, rs.user.persona_id)
            minor = determine_age_class(
                persona_data['birthday'], now().date()).is_minor()
        cde_info = self.coreproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_subscription_form", {
            'cde_info': cde_info, 'persona_data': persona_data, 'minor': minor})
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
            raise RuntimeError("Already done.")
        open_lastschrift = self.determine_open_permits(rs)
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
                    lastschrift = self.cdeproxy.get_lastschrift_one(
                        rrs, unwrap(lastschrift_list))
                    lastschrift['reference'] = lastschrift_reference(
                        persona['id'], lastschrift['id'])
                address = make_postal_address(persona)
                transaction_subject = make_transaction_subject(persona)
                self.do_mail(
                    rrs, "billing",
                    {'To': (persona['username'],),
                     'Subject': 'Renew your CdE membership'},
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
        rs.notify("success", "Started sending mail.")
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_eject(self, rs):
        """Eject members without enough credit."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['billing_done'] or period['ejection_done']:
            raise RuntimeError("Wrong timing.")
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
                         'Subject': 'Ejection from CdE'},
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
        rs.notify("success", "Started ejection.")
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_balance_update(self, rs):
        """Deduct membership fees from all member accounts."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['ejection_done'] or period['balance_done']:
            raise RuntimeError("Wrong timing.")
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
                    raise ValueError("Balance too low.")
                else:
                    if persona['trial_member']:
                        update = {
                            'id': persona_id,
                            'trial_member': False,
                        }
                        self.coreproxy.change_persona(
                            rrs, update, change_note="End trial membership.")
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
        rs.notify("success", "Started updating balance.")
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def semester_advance(self, rs):
        """Proceed to next period."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['balance_done']:
            raise RuntimeError("Wrong timing.")
        self.cdeproxy.create_period(rs)
        rs.notify("success", "New period started.")
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
            raise RuntimeError("Already done.")
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
                    lastschrift = self.cdeproxy.get_lastschrift_one(
                        rrs, unwrap(lastschrift_list))
                    lastschrift['reference'] = lastschrift_reference(
                        persona['id'], lastschrift['id'])
                self.do_mail(
                    rrs, "addresscheck",
                    {'To': (persona['username'],),
                     'Subject': 'Address check for ExPuls'},
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
            rs.notify("success", "Not sending mail.")
        else:
            worker = Worker(self.conf, task, rs)
            worker.start()
            rs.notify("success", "Started sending mail.")
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin", modi={"POST"})
    def expuls_advance(self, rs):
        """Proceed to next expuls."""
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if not expuls['addresscheck_done']:
            raise RuntimeError("Wrong timing.")
        self.cdeproxy.create_expuls(rs)
        rs.notify("success", "New expuls started.")
        return self.redirect(rs, "cde/show_semester")

    #
    # XXX
    #

    @access("cde_admin")
    def list_institutions(self, rs):
        """Display all organizing bodies."""
        institutions = self.pasteventproxy.list_institutions(rs)
        return self.render(rs, "list_institutions", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("title", "moniker")
    def create_institution(self, rs, data):
        """Make a new institution."""
        data = check(rs, "institution", data, creation=True)
        if rs.errors:
            return self.list_institutions(rs)
        new_id = self.pasteventproxy.create_institution(rs, data)
        self.notify_return_code(rs, new_id, success="Institution created.")
        return self.redirect(rs, "cde/list_institutions")

    @access("cde_admin")
    def change_institution_form(self, rs, institution_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['institution'])
        return self.render(rs, "change_institution")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("title", "moniker")
    def change_institution(self, rs, institution_id, data):
        """Modify an institution."""
        data['id'] = institution_id
        data = check(rs, "institution", data)
        if rs.errors:
            return self.change_institution_form(rs, institution_id)
        code = self.pasteventproxy.set_institution(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/list_institutions")

    @access("cde")
    def show_past_event(self, rs, pevent_id):
        """Display concluded event."""
        courses = self.pasteventproxy.list_past_courses(rs, pevent_id)
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        institutions = self.pasteventproxy.list_institutions(rs)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        if not (is_participant or self.is_admin(rs)):
            ## make list of participants only visible to other participants
            participant_infos = participants = None
        else:
            ## fix up participants, so we only see each persona once
            persona_ids = {persona_id
                           for persona_id, _ in participant_infos.keys()}
            tmp = {}
            for persona_id in persona_ids:
                base_set = tuple(x for x in participant_infos.values()
                                 if x['persona_id'] == persona_id)
                entry = {
                    'pevent_id': pevent_id,
                    'persona_id': persona_id,
                    'is_orga': any(x['is_orga'] for x in base_set),
                    'is_instructor': False,
                    }
                if any(x['pcourse_id'] is None for x in base_set):
                    entry['pcourse_id'] = None
                else:
                    entry['pcourse_id'] = min(x['pcourse_id'] for x in base_set)
                tmp[persona_id] = entry
            participants = tmp

            personas = self.coreproxy.get_personas(rs, participants.keys())
            participants = OrderedDict(sorted(
                participants.items(), key=lambda x: name_key(personas[x[0]])))
        return self.render(rs, "show_past_event", {
            'courses': courses, 'participants': participants,
            'personas': personas, 'institutions': institutions})

    @access("cde")
    def show_past_course(self, rs, pevent_id, pcourse_id):
        """Display concluded course."""
        participant_infos = self.pasteventproxy.list_participants(
            rs, pcourse_id=pcourse_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        if not (is_participant or self.is_admin(rs)):
            ## make list of participants only visible to other participants
            participant_infos = participants = None
        else:
            participants = self.coreproxy.get_personas(
                rs, tuple(anid for anid, _ in participant_infos.keys()))
            participants = OrderedDict(sorted(
                participants.items(), key=lambda x: name_key(x[1])))
        return self.render(rs, "show_past_course", {
            'participants': participants})

    @access("cde_admin")
    def list_past_events(self, rs):
        """List all concluded events."""
        events = self.pasteventproxy.list_past_events(rs)
        return self.render(rs, "list_past_events", {'events': events})

    @access("cde_admin")
    def change_past_event_form(self, rs, pevent_id):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        merge_dicts(rs.values, rs.ambience['pevent'])
        return self.render(rs, "change_past_event", {
            'institutions': institutions})

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("title", "shortname", "institution", "description", "tempus")
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
    @REQUESTdatadict("title", "shortname", "institution", "description", "tempus")
    def create_past_event(self, rs, courses, data):
        """Add new concluded event."""
        data = check(rs, "past_event", data, creation=True)
        thecourses = []
        if courses:
            courselines = courses.split('\n')
            reader = csv.DictReader(
                courselines, fieldnames=("title", "description"), delimiter=';',
                quoting=csv.QUOTE_ALL, doublequote=True, quotechar='"')
            lineno = 0
            for entry in reader:
                lineno += 1
                entry['pevent_id'] = 1
                entry = check(rs, "past_course", entry, creation=True)
                if entry:
                    thecourses.append(entry)
                else:
                    rs.notify("warning", "Line {} is faulty.".format(lineno))
        if rs.errors:
            return self.create_past_event_form(rs)
        with Atomizer(rs):
            new_id = self.pasteventproxy.create_past_event(rs, data)
            for cdata in thecourses:
                cdata['pevent_id'] = new_id
                self.pasteventproxy.create_past_course(rs, cdata)
        self.notify_return_code(rs, new_id, success="Event created.")
        return self.redirect(rs, "cde/show_past_event", {'pevent_id': new_id})

    @access("cde_admin")
    def change_past_course_form(self, rs, pevent_id, pcourse_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['pcourse'])
        return self.render(rs, "change_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict("title", "description")
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
    @REQUESTdatadict("title", "description")
    def create_past_course(self, rs, pevent_id, data):
        """Add new concluded course."""
        data['pevent_id'] = pevent_id
        data = check(rs, "past_course", data, creation=True)
        if rs.errors:
            return self.create_past_course_form(rs, pevent_id)
        new_id = self.pasteventproxy.create_past_course(rs, data)
        self.notify_return_code(rs, new_id, success="Course created.")
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
            return self.show_past_course(rs, pevent_id, pcourse_id)
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
