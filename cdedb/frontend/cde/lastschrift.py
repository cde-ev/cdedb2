#!/usr/bin/env python3

"""Lastschrift related services for the cde realm.

Viewing general information on the Lastschriftinitiative and filling in a lastschrift
form requires no privileges. Viewing ones own lastschrift requires the "member" role.
Everything else here requires the "finance_admin" role.
"""

import datetime
import pathlib
import random
import shutil
import string
import tempfile
from collections import OrderedDict
from typing import Collection, Dict, List, Optional

import dateutil.easter
import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, RequestState, asciificator, determine_age_class, glue,
    int_to_words, lastschrift_reference, merge_dicts, now,
)
from cdedb.common.n_ import n_
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation import LASTSCHRIFT_COMMON_FIELDS
from cdedb.filter import money_filter
from cdedb.frontend.cde.base import CdEBaseFrontend
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, cdedbid_filter, check_validation as check,
    make_postal_address, periodic,
)


class CdELastschriftMixin(CdEBaseFrontend):
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
        return self.render(rs, "lastschrift/lastschrift_index", {
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
        persona_ids = {x['submitted_by'] for x in lastschrifts.values()}.union(
            {x['submitted_by'] for x in transactions.values()})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        # we need to access the donation property of the associated user
        main_persona = self.coreproxy.get_cde_user(rs, persona_id)
        active_permit = None
        for lastschrift in lastschrifts.values():
            if not lastschrift['revoked_at']:
                active_permit = lastschrift['id']
        active_open = bool(
            active_permit and self.determine_open_permits(rs, (active_permit,)))
        return self.render(rs, "lastschrift/lastschrift_show", {
            'lastschrifts': lastschrifts, 'main_persona': main_persona,
            'active_permit': active_permit, 'active_open': active_open,
            'personas': personas, 'transactions': transactions,
        })

    @access("finance_admin")
    def lastschrift_change_form(self, rs: RequestState, lastschrift_id: int
                                ) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['lastschrift'])
        persona = self.coreproxy.get_cde_user(
            rs, rs.ambience['lastschrift']['persona_id'])
        return self.render(rs, "lastschrift/lastschrift_change", {'persona': persona})

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
        rs.notify_return_code(code)
        return self.redirect(rs, "cde/lastschrift_show", {
            'persona_id': rs.ambience['lastschrift']['persona_id']})

    @access("finance_admin")
    def lastschrift_create_form(self, rs: RequestState, persona_id: int = None
                                ) -> Response:
        """Render form."""
        min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
        typical_donation = self.conf["TYPICAL_LASTSCHRIFT_DONATION"]
        current_donation = None
        if persona_id:
            persona = self.coreproxy.get_cde_user(rs, persona_id)
            current_donation = persona["donation"] or None
        return self.render(rs, "lastschrift/lastschrift_create", {
            "min_donation": min_donation, "typical_donation": typical_donation,
            "current_donation": current_donation,
        })

    @access("finance_admin", modi={"POST"})
    @REQUESTdatadict(*LASTSCHRIFT_COMMON_FIELDS)
    @REQUESTdata("persona_id", "donation")
    def lastschrift_create(self, rs: RequestState, persona_id: vtypes.CdedbID,
                           data: CdEDBObject, donation: vtypes.PositiveDecimal
                           ) -> Response:
        """Create a new permit."""
        data['persona_id'] = persona_id
        data = check(rs, vtypes.Lastschrift, data, creation=True)
        if not self.coreproxy.verify_persona(rs, persona_id, ["cde"]):
            rs.add_validation_error(("persona_id", ValueError(
                n_("Persona must have cde realm."))))
        min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
        if donation < min_donation:
            rs.add_validation_error(("donation", ValueError(
                n_("Lastschrift donation must be at least %(min)s."),
                {"min": money_filter(min_donation)})))
        if rs.has_validation_errors():
            return self.lastschrift_create_form(rs, persona_id)
        assert data is not None
        if self.cdeproxy.list_lastschrift(
                rs, persona_ids=(persona_id,), active=True):
            rs.notify("error", n_("Multiple active permits are disallowed."))
            return self.redirect(rs, "cde/lastschrift_show", {
                'persona_id': persona_id})
        new_id = self.cdeproxy.create_lastschrift(rs, data, initial_donation=donation)
        rs.notify_return_code(new_id)
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
        rs.notify_return_code(code, success=n_("Permit revoked."))
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=(lastschrift_id,),
            stati=(const.LastschriftTransactionStati.issued,))
        if transaction_ids:
            subject = glue("Einzugsermächtigung zu ausstehender Lastschrift"
                           "widerrufen.")
            self.do_mail(rs, "lastschrift/pending_lastschrift_revoked",
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
                'amount': self.cdeproxy.transaction_amount(rs, persona['id']),
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
        if not lastschrift_id:
            all_lids = self.cdeproxy.list_lastschrift(rs)
            lastschrift_ids = tuple(self.determine_open_permits(
                rs, all_lids.keys()))
        else:
            lastschrift_ids = (lastschrift_id,)
            if not self.determine_open_permits(rs, lastschrift_ids):
                rs.notify("error", n_("Existing pending transaction."))
                return self.lastschrift_index(rs)
        transaction_ids = self.cdeproxy.issue_lastschrift_transaction_batch(
            rs, lastschrift_ids).values()
        if not transaction_ids:
            return self.lastschrift_index(rs)

        lastschrifts = self.cdeproxy.get_lastschrifts(rs, lastschrift_ids)
        transactions = self.cdeproxy.get_lastschrift_transactions(rs, transaction_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in lastschrifts.values()))
        for transaction in transactions.values():
            lastschrift = lastschrifts[transaction["lastschrift_id"]]
            persona = personas[lastschrift['persona_id']]
            data = {
                'persona': persona,
                'payment_date': self._calculate_payment_date(),
                'amount': transaction["amount"],
                'iban': lastschrift['iban'],
                'account_owner': lastschrift['account_owner'],
                'mandate_reference': lastschrift_reference(
                    lastschrift['persona_id'], lastschrift['id']),
                'glaeubiger_id': self.conf["SEPA_GLAEUBIGERID"],
            }
            subject = "Anstehender Lastschrifteinzug Lastschriftinitiative"
            self.do_mail(rs, "lastschrift/sepa_pre-notification",
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
        code = self.cdeproxy.finalize_lastschrift_transaction(
            rs, transaction_id, status)
        rs.notify_return_code(code)
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
        if success:
            status = const.LastschriftTransactionStati.success
        elif cancelled:
            status = const.LastschriftTransactionStati.cancelled
        elif failure:
            status = const.LastschriftTransactionStati.failure
        else:
            raise RuntimeError(n_("Impossible."))
        code = self.cdeproxy.finalize_lastschrift_transactions(
            rs, transaction_ids, status)
        rs.notify_return_code(code)
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
        code = self.cdeproxy.rollback_lastschrift_transaction(rs, transaction_id)
        rs.notify_return_code(code)
        transaction_ids = self.cdeproxy.list_lastschrift_transactions(
            rs, lastschrift_ids=(lastschrift_id,),
            stati=(const.LastschriftTransactionStati.issued,))
        if transaction_ids:
            subject = glue("Einzugsermächtigung zu ausstehender Lastschrift"
                           "widerrufen.")
            self.do_mail(rs, "lastschrift/pending_lastschrift_revoked",
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
        addressee = make_postal_address(rs, persona)
        # TODO add proper handling of missing address
        if addressee is None:
            addressee = []
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
        min_donation = self.conf["MINIMAL_LASTSCHRIFT_DONATION"]
        typical_donation = self.conf["TYPICAL_LASTSCHRIFT_DONATION"]
        return self.render(
            rs, "lastschrift/lastschrift_subscription_form_fill", {
                "persona": persona, "not_minor": not_minor,
                "min_donation": min_donation, "typical_donation": typical_donation
            }
        )

    @access("anonymous")
    @REQUESTdata("full_name", "db_id", "username", "address_supplement",
                 "address", "postal_code", "location", "country", "iban", "donation",
                 "account_holder")
    def lastschrift_subscription_form(
            self, rs: RequestState, full_name: Optional[str],
            db_id: Optional[vtypes.CdedbID], username: Optional[vtypes.Email],
            address_supplement: Optional[str], address: Optional[str],
            postal_code: Optional[vtypes.GermanPostalCode], location: Optional[str],
            country: Optional[str], iban: Optional[vtypes.IBAN],
            account_holder: Optional[str], donation: Optional[vtypes.PositiveDecimal]
    ) -> Response:
        """Fill the direct debit authorization template with information."""

        if rs.has_validation_errors():
            return self.lastschrift_subscription_form_fill(rs)

        data = {
            "full_name": full_name or "",
            "db_id": db_id,
            "username": username or "",
            "address_supplement": address_supplement or "",
            "address": address or "",
            "postal_code": postal_code or "",
            "location": location or "",
            "country": country or "",
            "iban": iban or "",
            "donation": float(donation) if donation else None,
            "account_holder": account_holder or "",
        }

        params = {
            "data": data,
            "meta_info": self.coreproxy.get_meta_info(rs),
            "min_donation": self.conf["MINIMAL_LASTSCHRIFT_DONATION"],
            "typical_donation": self.conf["TYPICAL_LASTSCHRIFT_DONATION"],
            "annual_fee": self.cdeproxy.annual_membership_fee(rs),
        }
        tex = self.fill_template(rs, "tex", "lastschrift_subscription_form", params)
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
        """Show information about 'Lastschriftinitiative' (former 'Initiative 25+')."""
        annual_fee = self.cdeproxy.annual_membership_fee(rs)
        return self.render(rs, "lastschrift/i25p_index", {
            "annual_fee": annual_fee,
            "min_donation": self.conf["MINIMAL_LASTSCHRIFT_DONATION"],
            "typical_donation": self.conf["TYPICAL_LASTSCHRIFT_DONATION"]})
