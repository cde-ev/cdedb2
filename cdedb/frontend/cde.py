#!/usr/bin/env python3

"""Services for the cde realm."""

import hashlib
import logging
import os.path
import random
import shutil
import string
import tempfile
import werkzeug

import cdedb.database.constants as const
from cdedb.common import (
    merge_dicts, name_key, lastschrift_reference, now, glue,
    int_to_words, determine_age_class, PERSONA_STATUS_FIELDS, ProxyShim)
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access,
    check_validation as check,
    cdedbid_filter, request_data_extractor, make_postal_address)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input, QueryOperators
from cdedb.backend.event import EventBackend
from cdedb.backend.cde import CdEBackend

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
        self.eventproxy = ProxyShim(EventBackend(configpath))

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
        participation_info = self.eventproxy.participation_info(rs, persona_id)
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
        blob = foto.read()
        myhash = hashlib.sha512()
        myhash.update(blob)
        path = os.path.join(self.conf.STORAGE_DIR, 'foto', myhash.hexdigest())
        if not os.path.isfile(path):
            with open(path, 'wb') as f:
                f.write(blob)
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
    @REQUESTdata(("submitform", "bool"))
    def member_search(self, rs, submitform):
        """Render form and do search queries. This has a double meaning so
        that we are able to update the course selection upon request.

        ``submitform`` is present in the request data if the corresponding
        button was pressed and absent otherwise.
        """
        spec = QUERY_SPECS['qview_cde_member']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=not submitform)
        if not submitform or rs.errors:
            events = {k: v for k, v in self.eventproxy.list_events(
                rs, past=True).items()}
            pevent_id = None
            if query:
                for field, _, value in query.constraints:
                    if field == "pevent_id" and value:
                        pevent_id = value
            courses = tuple()
            if pevent_id:
                courses = {k: v for k, v in self.eventproxy.list_courses(
                    rs, pevent_id, past=True).items()}
            choices = {"pevent_id": events, 'pcourse_id': courses}
            return self.render(rs, "member_search",
                               {'spec': spec, 'choices': choices,
                                'queryops': QueryOperators,})
        else:
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
            return self.render(rs, "member_search_result", {'result': result})

    @access("cde_admin")
    def user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_cde_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        events = self.eventproxy.list_events(rs, past=True)
        choices = {'pevent_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_cde_user']
        return self.render(rs, "user_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries,})

    @access("cde_admin")
    @REQUESTdata(("CSV", "bool"))
    def user_search(self, rs, CSV):
        """Perform search."""
        spec = QUERY_SPECS['qview_cde_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.user_search_form(rs)
        query.scope = "qview_cde_user"
        result = self.cdeproxy.submit_general_query(rs, query)
        choices = {'gender': self.enum_choice(rs, const.Genders)}
        params = {'result': result, 'query': query, 'choices': choices}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            return self.render(rs, "user_search_result", params)

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
            {entry['submitted_by'] for entry in log}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_cde_log", {
            'log': log, 'persona_data': persona_data})

    def determine_open_permits(self, rs, lastschrift_ids=None):
        """Find ids, which to debit this period.

        Helper to find out which of the passed lastschrift permits has
        not been debitted for a year.

        :type rs: :py:class:`cdedb.frontend.common.FrontendRequestState`
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

        :type rs: :py:class:`cdedb.frontend.common.FrontendRequestState`
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
    @REQUESTdata(("lastschrift_id", "int_or_None"))
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
        return self.send_file(rs, data=sepapain_file,
                              filename=self.i18n("sepa.cdd", rs.lang))

    @access("cde_admin", modi={"POST"})
    @REQUESTdata(("persona_id", "int_or_None"))
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
                 ("persona_id", "int_or_None"))
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
    @REQUESTdata(("persona_id", "int_or_None"))
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
        cde_info = self.cdeproxy.get_meta_info(rs)
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
        cde_info = self.cdeproxy.get_meta_info(rs)
        tex = self.fill_template(rs, "tex", "lastschrift_subscription_form", {
            'cde_info': cde_info, 'persona_data': persona_data, 'minor': minor})
        return self.serve_latex_document(rs, tex,
                                         "lastschrift_subscription_form")

    @access("cde_admin")
    def meta_info_form(self, rs):
        """Render form."""
        info = self.cdeproxy.get_meta_info(rs)
        merge_dicts(rs.values, info)
        return self.render(rs, "meta_info", {'keys': self.conf.META_INFO_KEYS})

    @access("cde_admin", modi={"POST"})
    def change_meta_info(self, rs):
        """Change the meta info constants."""
        data_params = tuple((key, "any") for key in self.conf.META_INFO_KEYS)
        data = request_data_extractor(rs, data_params)
        data = check(rs, "cde_meta_info", data, keys=self.conf.META_INFO_KEYS)
        if rs.errors:
            return self.meta_info_form(rs)
        code = self.cdeproxy.set_meta_info(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "cde/meta_info_form")
