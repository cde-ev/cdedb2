#!/usr/bin/env python3

import copy
import csv
import datetime
import decimal
import itertools
import json
import re
import tempfile
import unittest
from collections.abc import Collection, Sequence
from typing import Optional, cast

import freezegun
import lxml.etree
import webtest
from subman import SubscriptionError

import cdedb.database.constants as const
import cdedb.models.event as models
import cdedb.models.event.constraint_violations as models_cv
from cdedb.common import (
    ANTI_CSRF_TOKEN_NAME,
    IGNORE_WARNINGS_NAME,
    CdEDBObject,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.parse.util import Accounts
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.common.roles import ADMIN_VIEWS_COOKIE_NAME
from cdedb.common.sorting import xsorted
from cdedb.filter import datetime_filter, iban_filter
from cdedb.frontend.common import (
    CustomCSVDialect,
    _make_epc_qr_data,  # noqa: PLC2701
    make_event_fee_reference,
)
from cdedb.frontend.event.query_stats import (
    PART_STATISTICS,
    TRACK_STATISTICS,
    EventRegistrationInXChoiceGrouper,
    StatisticMixin,
    StatisticPartMixin,
    StatisticTrackMixin,
    get_id_constraint,
)
from cdedb.models.complaint import ComplaintInvolved
from cdedb.models.droid import OrgaToken
from cdedb.models.ml import (
    EventAssociatedExclusiveMailinglist,
    EventAssociatedMailinglist,
)
from tests.common import (
    USER_DICT,
    FrontendTest,
    UserObject,
    as_users,
    event_keeper,
    execsql,
    prepsql,
    storage,
)


class TestEventFrontend(FrontendTest):
    def _set_payment_info(
        self,
        reg_id: int,
        event_id: int,
        amount_paid: decimal.Decimal,
        payment: Optional[datetime.date] = None,
    ) -> None:
        """Mocker around book_fees to ease setting of payment stuff in tests.

        This sets the amount_paid to the given value. Since book_fees only accepts
        deltas of amount_paid, we do the additional book keeping here.
        """
        current = self.event.get_registration(self.key, reg_id)
        data = {
            'registration_id': reg_id,
            'persona_id': current['persona_id'],
            'date': payment or now().date(),
            # used in log entry
            'amount': amount_paid - current['amount_paid'],
        }
        self.event.book_fees(self.key, event_id, [data])

    @as_users("anton", "emilia", maintain_data=True)
    def test_index(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        # TODO Add someone who already has paid.
        registered = "(bereits angemeldet, Bezahlung ausstehend)"
        self.assertPresence(registered, div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        if self.user_in('emilia'):
            self.assertNonPresence("CdE-Party 2050")
        self.assertNonPresence("CyberTestAkademie", div="organized-events")

    @as_users("anonymous", "janis", maintain_data=True)
    def test_no_event_realm_view(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("CdE-Party 2050")

        self.traverse({'description': 'Große Testakademie 2222'})
        self.assertPresence("aka@example.cde", div="orga-address")
        self.assertPresence("Erste Hälfte", div="timeframe-parts")
        self.assertNonPresence("Everybody come!")
        self.assertPresence(
            "für eingeloggte Veranstaltungsnutzer sichtbar", div='static-notifications'
        )

        self.traverse({'description': 'Kursliste'})
        self.assertPresence("α. Planetenretten für Anfänger", div='list-courses')
        self.assertPresence("Wir werden die Bäume drücken.", div='list-courses')
        msg = (
            "Die Kursleitenden sind nur für eingeloggte Veranstaltungsnutzer sichtbar."
        )
        self.assertPresence(msg, div="instructors-not-visible")
        self.assertNonPresence("Bernd Lucke")

    @as_users("anton", "berta", maintain_data=True)
    def test_index_orga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertPresence("CdE-Party 2050", div='organized-events')
        self.assertNonPresence("CdE-Party 2050", div='current-events')

    @as_users(
        "annika",
        "emilia",
        "martin",
        "vera",
        "werner",
        "katarina",
        "petra",
        maintain_data=True,
    )
    def test_sidebar(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        everyone = {"Veranstaltungen", "Übersicht", "Veranstaltungshelfer"}
        admin = {"Alle Veranstaltungen", "Ungereimtheiten", "Log"}

        # not event admins (also orgas!)
        if self.user_in('emilia', 'martin', 'werner'):
            ins = everyone
            out = admin | {"Nutzer verwalten"}
        # core admins
        elif self.user_in('vera'):
            ins = everyone | {"Nutzer verwalten"}
            out = admin
        # event admins
        elif self.user_in('annika'):
            ins = everyone | admin | {"Nutzer verwalten"}
            out = set()
        # event helpers
        elif self.user_in('petra'):
            ins = everyone | {"Alle Veranstaltungen", "Ungereimtheiten"}
            out = {"Log"}
        # auditors
        elif self.user_in('katarina'):
            ins = everyone | {"Log"}
            out = admin - {"Log"}
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("emilia")
    def test_showuser(self) -> None:
        self.traverse({'description': self.user['given_names']})
        self.assertTitle(self.user['default_name_format'])

    @as_users("annika")
    def test_changeuser(self) -> None:
        with self.switch_user("emilia"):
            self.traverse(
                {'description': self.user['given_names']}, {'description': 'Bearbeiten'}
            )
            f = self.response.forms['changedataform']
            self.submit(f, check_notification=False)
            self.assertValidationWarning("mobile", "Telefonnummer scheint ungültig zu")
            f = self.response.forms['changedataform']
            f['nickname'] = "Zelda"
            f['location'] = "Hyrule"
            f[IGNORE_WARNINGS_NAME].checked = True
            self.submit(f, check_notification=False)
            self.assertNotification("Änderung wartet auf Bestätigung", 'info')

        with self.switch_user("quintus"):
            # cde admin may not see event user change
            self.traverse({'description': 'Änderungen prüfen'})
            self.assertTitle("Zu prüfende Profiländerungen [0]")
            self.get('/core/persona/5/changelog/inspect', status=403)

        self.traverse({'description': 'Änderungen prüfen'})
        self.assertTitle("Zu prüfende Profiländerungen [1]")
        self.traverse({'href': '/core/persona/5/changelog/inspect'})
        self.assertTitle("Änderungen prüfen für Emilia Eventis")
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Zu prüfende Profiländerungen [0]")
        self.realm_admin_view_profile("emilia", "event")
        self.assertTitle("Emilia Eventis")
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertPresence("Hyrule", div='address')

    @as_users("annika", "ferdinand")
    def test_adminchangeuser(self) -> None:
        self.realm_admin_view_profile('emilia', 'event')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        self.submit(f, check_notification=False)
        self.assertValidationWarning("mobile", "Telefonnummer scheint ungültig zu")
        f = self.response.forms['changedataform']
        f['nickname'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.assertNotIn('free_form', f.fields)
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)
        self.assertPresence("Emilia (Zelda) Eventis", div='personal-information')
        self.assertTitle("Emilia Eventis")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("annika", "ferdinand")
    def test_toggleactivity(self) -> None:
        self.realm_admin_view_profile('emilia', 'event')
        self.assertPresence("Ja", div='account-active')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence("Nein", div='account-active')

    @as_users("annika", "vera", maintain_data=True)
    def test_user_search(self) -> None:
        self.traverse(
            {'description': 'Veranstaltunge'}, {'description': 'Nutzer verwalten'}
        )
        self.assertTitle("Veranstaltungsnutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'a@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsnutzerverwaltung")
        self.assertPresence("Ergebnis [2]", div='query-results')
        self.assertPresence("Hohle Gasse 13", div='query-result')
        self.assertPresence("Vereinigtes Königreich")

    @as_users("annika", "paul")
    def test_create_archive_user(self) -> None:
        data = {
            "title": "Dr.",
            "name_supplement": 'von und zu',
            "birthday": "1987-06-05",
            "gender": const.Genders.female,
            "telephone": "030456790",
            # "mobile"
            "address": "Street 7",
            "address_supplement": "on the left",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "HY",
        }
        self.check_create_archive_user("event", data)

    @as_users("anton")
    def test_event_admin_views(self) -> None:
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')

        self.traverse({'href': '/event'})
        self._click_admin_view_button(
            re.compile(r"Benutzer-Administration"), current_state=False
        )

        # Test Event Administration Admin View
        self.assertNoLink('/event/event/log')
        self.assertNoLink('/event/event/list', content="Alle Veranstaltungen")
        self.traverse({'href': '/event/event/1/show'})
        self.assertNoLink('/event/event/1/roles/manage')
        self.assertNotIn('deleteeventform', self.response.forms)
        self.traverse({'href': '/event/event/1/registration/status'})
        self._click_admin_view_button(
            re.compile(r"Veranstaltungs-Administration"), current_state=False
        )
        self.traverse({'href': '/event/event/1/show'})
        self.assertIn('deleteeventform', self.response.forms)
        self.traverse("Betreuer verwalten")
        self.assertIn('addorgasform', self.response.forms)
        self.traverse(
            "Veranstaltungen", "Alle Veranstaltungen", "Veranstaltung anlegen"
        )

        # Test Orga Controls Admin View
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self.assertNoLink('/event/event/1/registration/list')
        self.assertNoLink('/event/event/1/registration/query')
        self.assertNoLink('/event/event/1/change')
        self.assertNoLink('/event/event/1/part/summary')
        self.assertNoLink('/event/event/1/part/checkin')
        self.assertNotIn('quickregistrationform', self.response.forms)
        self.assertNotIn('changeminorformform', self.response.forms)
        self.assertNotIn('lockform', self.response.forms)
        self.traverse({'href': '/event/event/1/course/list'})
        self.assertNoLink('/event/event/1/course/1/show')

        self._click_admin_view_button(
            re.compile(r"Veranstaltungs-Administration"), current_state=True
        )
        # Even without the Orga Controls Admin View we should see the Orga
        # Controls of our own event:
        self.traverse(
            {'href': '/event/'},
            {'href': '/event/event/2/show'},
            {'href': '/event/event/2/registration/list'},
            {'href': '/event/event/2/registration/query'},
            {'href': '/event/event/2/change'},
            {'href': '/event/event/2/part/summary'},
            {'href': '/event/event/2/show'},
        )
        self.assertIn('quickregistrationform', self.response.forms)
        self.assertIn('changeminorformform', self.response.forms)
        self.assertIn('lockeventform', self.response.forms)
        self.assertNoLink("Orga-Schaltflächen")

        self.traverse({'href': '/event/'}, {'href': '/event/event/1/show'})
        self._click_admin_view_button(
            re.compile(r"Orga-Schaltflächen"), current_state=False
        )
        self.traverse(
            {'href': '/event/event/1/registration/list'},
            {'href': '/event/event/1/registration/query'},
            {'href': '/event/event/1/change'},
            {'href': '/event/event/1/part/summary'},
            {'href': '/event/event/1/course/list'},
            {'href': '/event/event/1/course/1/show'},
            {'href': '/event/event/1/show'},
        )
        self.assertIn('quickregistrationform', self.response.forms)
        self.assertIn('changeminorformform', self.response.forms)
        self.assertIn('lockeventform', self.response.forms)

    @as_users("annika")
    def test_list_events(self) -> None:
        self.traverse('Veranstaltungen', 'Alle Veranstaltungen')
        self.assertTitle("Alle Veranstaltungen")
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertPresence("CdE-Party 2050", div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertPresence("Orgas")
        self.assertPresence("Anmeldungen")

        with self.conf.with_overrides(EVENT_LIMITED_ACCESS_CUTOFF_ID=1):
            self.traverse('Alle Veranstaltungen')
            self.assertNoLink('/event/event/1/registration/query')
            self.traverse({'href': '/event/event/2/registration/query'})

    @as_users("anonymous", "garcia", maintain_data=True)
    def test_list_events_unprivileged(self) -> None:
        self.traverse({'description': 'Veranstaltungen'}, {'href': '/event/event/list'})
        self.assertTitle("Alle Veranstaltungen")
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertNonPresence("CdE-Party 2050")
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("Orgas")
        self.assertNonPresence("Anmeldungen")

    @as_users("berta", "charly", "annika", "garcia", "emilia", maintain_data=True)
    def test_show_event_noorga(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
        )
        self.assertTitle("Große Testakademie 2222")
        if self.user_in("annika", "berta", "emilia"):
            link = self.response.html.find(id="website-link").find(name="a")
            self.assertEqual(link.attrs["href"], "https://www.cde-ev.de/")
            self.assertIn("Große Testakademie 2222", link.getText())
            self.assertPresence(
                "Warmup: 02.02.2222 – 02.02.2222 "
                "Erste Hälfte: 01.11.2222 – 11.11.2222 "
                "Zweite Hälfte: 11.11.2222 – 30.11.2222",
                div='timeframe-parts',
            )
            self.assertPresence("Everybody come!", div='description')
            self.assertNonPresence(
                "für eingeloggte Veranstaltungsnutzer sichtbar", div='notifications'
            )
            self.assertPresence(
                "30.10.2000, 01:00:00 – 30.10.2200, 01:00:00 ",
                div='timeframe-registration',
            )
            self.assertPresence("aka@example.cde", div='orga-address')
            self.assertPresence("Garcia Generalis", div='orgas', exact=True)
        if self.user_in("berta", "charly"):
            # no orga
            self.assertNonPresence("TestAka")
            self.assertNonPresence("CdE-Konto IBAN")
            self.assertNonPresence("Fragebogen aktiv")
            self.assertNonPresence("Todoliste … just kidding ;)")
            self.assertNonPresence("Kristallkugel-basiertes Kurszuteilungssystemm")

            self.assertNotIn("quickregistrationform", self.response.forms)
            self.assertNotIn("changeminorformform", self.response.forms)
            self.assertNotIn("lockform", self.response.forms)
            self.assertNotIn("createparticipantlistform", self.response.forms)
        if self.user_in("annika", "garcia"):
            # orga
            self.traverse(
                {'description': 'Veranstaltungen'},
                {'description': 'Große Testakademie 2222'},
            )
            self.assertTitle("Große Testakademie 2222")

            self.assertPresence("TestAka", div='shortname')
            self.assertPresence("Club der Ehemaligen", div='institution')
            self.assertPresence(
                iban_filter(Accounts.Sozialbank.get_iban()), div='cde-iban'
            )
            self.assertPresence("Nein", div='questionnaire-active')
            self.assertPresence("Todoliste … just kidding ;)", div='orga-notes')

            self.assertIn('quickregistrationform', self.response.forms)
            self.assertIn('changeminorformform', self.response.forms)
            self.assertIn('lockeventform', self.response.forms)
            self.assertIn('createparticipantlistform', self.response.forms)
        if self.user_in("berta", "garcia"):
            # no admin
            self.assertNotIn("archiveeventform", self.response.forms)
            self.assertNotIn("deleteeventform", self.response.forms)
            self.assertNotIn("approveregistrationform", self.response.forms)
            self.assertNotIn("unapproveregistrationform", self.response.forms)

    @as_users("charly")
    def test_manage_orgas(self) -> None:
        with self.switch_user("annika"):
            self.traverse(
                "Veranstaltungen", "Große Testakademie 2222", "Betreuer verwalten"
            )
            f = self.response.forms['addcaretakersform']
            f['caretaker_ids'] = USER_DICT['charly']['DB-ID']
            self.submit(f)

        self.traverse("Veranstaltungen", "Große Testakademie", "Orgas verwalten")

        f = self.response.forms[f"removeorgaform{USER_DICT['garcia']['id']}"]
        self.submit(f, check_notification=False)
        self.assertValidationError("ack_delete", "Muss markiert sein.", index=0)
        f['ack_delete'].checked = True
        self.submit(f)

        self.traverse("Übersicht")
        f = self.response.forms['createparticipantlistform']
        self.assertInputHasAttr(f['submitform'], 'disabled')
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Mailingliste kann nur mit Orgas erstellt werden.", div='notifications'
        )

        self.traverse("Orgas verwalten")
        f = self.response.forms['addorgasform']
        f['orga_ids'] = f"{USER_DICT['garcia']['DB-ID']},{USER_DICT['emilia']['DB-ID']}"
        self.submit(f)

        log_expectation = [
            {
                "code": const.EventLogCodes.caretaker_added,
                "persona_id": USER_DICT['charly']['id'],
                "submitted_by": USER_DICT['annika']['id'],
            },
            {
                "code": const.EventLogCodes.orga_removed,
                "persona_id": USER_DICT['garcia']['id'],
            },
            {
                "code": const.EventLogCodes.orga_added,
                "persona_id": USER_DICT['emilia']['id'],
            },
            {
                "code": const.EventLogCodes.orga_added,
                "persona_id": USER_DICT['garcia']['id'],
            },
        ]
        self.assertLogEqual(
            log_expectation, "event", event_id=1, offset=self.EVENT_LOG_OFFSET
        )

    @as_users(
        "annika",
        "emilia",
        "garcia",
        "ludwig",
        "martin",
        "vera",
        "werner",
        "katarina",
        "farin",
        "petra",
        maintain_data=True,
    )
    def test_sidebar_one_event(self) -> None:
        everyone = {"Veranstaltungsübersicht", "Übersicht", "Kursliste"}
        not_registered = {"Anmelden"}
        registered = {"Meine Anmeldung"}
        registered_or_privileged = {"Teilnehmer-Infos"}
        privileged = {
            "Statistik",
            "Kurse",
            "Unterkünfte",
            "Teilnahmebeiträge",
            "Konfiguration",
            "Datenfelder konfigurieren",
            "Anmeldung konfigurieren",
            "Fragebogen konfigurieren",
            "Downloads & Import",
        }
        registrations_stats = {"Statistik", "Kurse", "Unterkünfte", "Teilnahmebeiträge"}
        orga = {
            "Teilnehmerliste",
            "Anmeldungen",
            "Log",
            "Checkin",
            "Ungereimtheiten",
        }
        checkin_helper = {"Teilnehmerliste", "Checkin"}
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        # TODO this could be more expanded (event without courses, distinguish
        #  between registered and participant, ...
        # not registered, not event admin, no event helper, no auditor
        if self.user_in('martin', 'vera', 'werner'):
            ins = everyone | not_registered
            out = registered | registered_or_privileged | privileged | orga
        # registered
        elif self.user_in('emilia'):
            ins = everyone | registered | registered_or_privileged
            out = not_registered | privileged | orga
        # orga
        elif self.user_in('garcia'):
            ins = everyone | registered | registered_or_privileged | privileged | orga
            out = not_registered
        # checkin helper
        elif self.user_in('ludwig'):
            ins = (
                everyone
                | not_registered
                | registered_or_privileged
                | privileged
                | checkin_helper
            )
            out = registered | orga - checkin_helper
        # event helper
        elif self.user_in('petra'):
            ins = everyone | not_registered | registered_or_privileged | privileged
            out = registered | orga
        # event admin (annika is not registered)
        elif self.user_in('annika'):
            ins = (
                everyone | not_registered | registered_or_privileged | privileged | orga
            )
            out = registered
        # not registered, auditor
        elif self.user_in('katarina'):
            ins = (
                everyone
                | not_registered
                | privileged
                | registered_or_privileged
                | {"Log"}
            ) - registrations_stats
            out = (registered | orga | registrations_stats) - {"Log"}
        # finance admin
        elif self.user_in('farin'):
            ins = (
                everyone | not_registered | privileged | registered_or_privileged
            ) - registrations_stats | {"Teilnahmebeiträge", "Log", "Unterkünfte"}
            out = (registered | orga | registrations_stats) - {
                "Teilnahmebeiträge",
                "Log",
                "Unterkünfte",
            }
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

        with self.conf.with_overrides(EVENT_LIMITED_ACCESS_CUTOFF_ID=1):
            self.get('/event/event/1/show')
            ins_both = everyone | registered_or_privileged | privileged | {"Log"}
            if self.user_in('annika'):
                ins = ins_both | not_registered
                out = registered | orga - {"Log"}
                self.check_sidebar(ins, out)
            if self.user_in('garcia'):
                ins = ins_both | registered
                out = not_registered | orga - {"Log"}
                self.check_sidebar(ins, out)

    @as_users("anton", "berta")
    def test_no_soft_limit(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self.assertTitle("Große Testakademie 2222")
        with self.switch_user('garcia'):
            self.traverse("Veranstaltungen", "Große Testakademie", "Konfiguration")
            f = self.response.forms['changeeventform']
            f['registration_soft_limit'] = ""
            f['registration_hard_limit'] = "2222-05-01T00:00:00"
            self.submit(f)
            self.assertTitle("Große Testakademie 2222")
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("30.10.2000, 01:00:00 – 01.05.2222, 00:00:00")

    @as_users("anton", "berta", maintain_data=True)
    def test_no_hard_limit(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'}, {'description': 'CdE-Party 2050'}
        )
        self.assertTitle("CdE-Party 2050")
        self.assertPresence("Let‘s have a party!")
        self.assertPresence(
            "01.12.2049, 01:00:00 – 31.12.2049, 01:00:00",
            div='timeframe-registration',
            exact=True,
        )

    @as_users("annika", "garcia", "charly", "emilia", maintain_data=True)
    def test_hard_limit(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
        )
        self.assertTitle("Große Testakademie 2222")

        if self.user_in("annika", "garcia"):
            # orga
            self.assertPresence(
                "30.10.2000, 01:00:00 – 30.10.2200, 01:00:00 "
                "(Nachmeldungen bis 30.10.2221, 01:00:00) ",
                div='timeframe-registration',
                exact=True,
            )
        else:
            # no orga
            self.assertPresence(
                "30.10.2000, 01:00:00 – 30.10.2200, 01:00:00",
                div='timeframe-registration',
                exact=True,
            )

    @as_users("annika", "berta", "emilia")
    @prepsql("UPDATE event.courses SET is_visible = False WHERE id = 2")
    def test_course_list(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Kursliste")
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertPresence("ToFi")
        self.assertPresence("Wir werden die Bäume drücken.")
        self.assertNonPresence("Lustigsein")
        f = self.response.forms['coursefilterform']
        f['track_ids'] = [1, 3]
        self.submit(f)
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertNonPresence("Kurzer Kurs")
        f = self.response.forms['coursefilterform']
        f['track_ids'] = [2]
        self.submit(f)
        self.assertNonPresence("β. Lustigsein für Fortgeschrittene")
        self.assertPresence("γ. Kurzer Kurs")
        execsql("UPDATE event.courses SET is_visible = True WHERE id = 2")
        self.submit(f)
        self.assertPresence("β. Lustigsein für Fortgeschrittene")
        f = self.response.forms['coursefilterform']
        self.assertNotIn("active_only", f.fields)
        if self.user_in('annika'):
            self.event.set_event(self.key, 1, {"is_course_state_visible": True})
            self.traverse("Kursliste")
            f = self.response.forms['coursefilterform']
            f['track_ids'] = [2]
            f['active_only'].checked = True
            self.submit(f)
            self.assertNonPresence("β. Lustigsein für Fortgeschrittene")
            self.assertPresence("γ. Kurzer Kurs")
            # check that validation converting works and is shown in the form
            self.get(
                self.response.request.url.replace(
                    'active_only=True', 'active_only=nonBoolButTrue'
                )
            )
            self.assertTrue(
                self.response.forms['coursefilterform']['active_only'].checked
            )
            self.assertNonPresence("β. Lustigsein für Fortgeschrittene")
            self.assertPresence("γ. Kurzer Kurs")
            # check handling if no courses match the search
            execsql(
                "UPDATE event.course_segments SET is_active = False WHERE track_id = 1"
            )
            f = self.response.forms['coursefilterform']
            f['active_only'].checked = True
            f['track_ids'] = [1]
            self.submit(f)
            self.assertPresence("Filter")
            self.assertPresence("Keine passenden Kurse gefunden.")
        else:
            # check that taking place filter not accessible for non-privileged users
            self.assertNonPresence("Zeige nur stattfindende Kurse")
            self.get(self.response.request.url + '&active_only=True')
            self.assertPresence("β. Lustigsein für Fortgeschrittene")

    @as_users("annika", "garcia", "ferdinand")
    def test_change_event(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Konfiguration'},
        )
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        self.assertNonPresence("getragen", div='static-notifications', check_div=False)
        # basic event data
        f = self.response.forms['changeeventform']
        self.assertEqual(f['registration_start'].value, "2000-10-30T01:00:00")
        f['title'] = "Universale Akademie"
        f['registration_start'] = "2001-10-30 00:00:00"
        f['use_additional_questionnaire'].checked = True
        f['institution'] = const.PastInstitutions.private
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertNonPresence("30.10.2000")
        self.assertPresence("30.10.2001", div='timeframe-registration')
        self.assertPresence("nicht durch den CdE getragen", div='static-notifications')
        # orgas
        self.assertNonPresence("Beispiel")
        # check visibility and hint text on empty participant_info
        self.traverse("Teilnehmer-Infos")
        self.assertTitle("Universale Akademie – Teilnehmer-Infos")
        self.assertPresence("Die Kristallkugel hat gute Dienste geleistet, nicht wahr?")
        self.traverse("Bearbeiten")
        self.assertTitle("Universale Akademie – Freitexte")
        f = self.response.forms['changefreetextform-participant_info']
        f['free_text_value'] = ""
        self.submit(f)
        self.assertNoLink("Teilnehmer-Infos")
        self.get('/event/event/1/notes')
        self.assertPresence(
            "Diese Seite ist momentan für Teilnehmer nicht sichtbar. Um das zu ändern, "
            "können Orgas über die Konfigurations-Seite hier etwas hinzufügen.",
            div='static-notifications',
        )
        self.traverse("Übersicht")
        if self.user_in('ferdinand', 'annika'):
            self.traverse("Orgas verwalten")
            f = self.response.forms['addorgasform']
            # Try to add an invalid cdedbid.
            f['orga_ids'] = "DB-1-1"
            self.submit(f, check_notification=False)
            self.assertValidationError('orga_ids', "Checksumme stimmt nicht.", index=-1)
            # Try to add a non event user.
            f['orga_ids'] = USER_DICT['janis']['DB-ID']
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'orga_ids',
                "Einige dieser Accounts sind keine Veranstaltungsnutzer.",
                index=-1,
            )
            # Try to add an archived user.
            f['orga_ids'] = USER_DICT['hades']['DB-ID']
            self.submit(f, check_notification=False)
            msg = "Einige dieser Accounts existieren nicht oder sind archiviert."
            self.assertValidationError('orga_ids', msg, index=-1)
            # Try to add a non-existent user.
            f['orga_ids'] = "DB-1000-6"
            self.submit(f, check_notification=False)
            self.assertValidationError('orga_ids', msg, index=-1)
            f['orga_ids'] = USER_DICT['berta']['DB-ID']
            self.submit(f)
            self.assertTitle("Orgas & Betreuer verwalten (Universale Akademie)")
            self.assertPresence("Beispiel", div='orgas_list')
            text = self.fetch_mail_content()
            self.assertIn("als Orgas hinzugefügt", text)
            f = self.response.forms['removeorgaform2']
            f['ack_delete'].checked = True
            self.submit(f)
            self.assertTitle("Orgas & Betreuer verwalten (Universale Akademie)")
            self.assertNonPresence("Beispiel")
            text = self.fetch_mail_content()
            self.assertIn("als Orga entfernt", text)

    @event_keeper
    @as_users("garcia")
    def test_orga_rate_limit(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
        )

        for _ in range(10):
            self.traverse({'href': '/event/event/1/registration/add'})
            f = self.response.forms['addregistrationform']
            f['persona.persona_id'] = "DB-3-5"
            self.submit(f)
            f = self.response.forms['deleteregistrationform']
            f['ack_delete'].checked = True
            self.submit(f)

        self.traverse({'href': 'event/event/1/registration/add'})
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-3-5"
        self.submit(f, check_notification=False)
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        self.assertValidationError('persona.persona_id', "Limit erreicht")
        self.traverse(
            {'href': 'event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        self.assertNonPresence("Charly")

    def test_event_visibility(self) -> None:
        # add a course track
        self.login(USER_DICT['annika'])
        self.get("/event/event/2/part/4/change")
        f = self.response.forms['changepartform']
        f['track_title_-1'] = "Spätschicht"
        f['track_shortname_-1'] = "Spät"
        f['track_create_-1'].checked = True
        f['track_sortkey_-1'] = "1"
        self.submit(f)

        # add a course
        self.traverse("Kurse", "Kurs hinzufügen")
        f = self.response.forms['configurecourseform']
        f['title'] = "Chillout mit Musik"
        f['nr'] = "1"
        f['shortname'] = "music"
        f['instructors'] = "Giorgio Moroder"
        self.submit(f)

        # move the registration start to one week in the future.
        self.traverse("Konfiguration")
        f = self.response.forms['changeeventform']
        f['registration_start'] = (now() + datetime.timedelta(days=7)).isoformat()
        self.submit(f)

        # Check visibility for orga
        self.traverse("Kursliste")
        self.assertPresence("Chillout mit Musik")

        # Check for inexistence of links to event, invisible event page, but
        # visible course page
        self.logout()
        self.login(USER_DICT['emilia'])
        self.assertNonPresence("CdE Party")
        self.traverse("Veranstaltungen")
        self.assertNonPresence("CdE Party")
        self.get('/event/event/2/course/list')
        self.assertPresence("Chillout mit Musik")
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.get('/event/event/2/show', status=403)

        # Now, the other way round: visible event without visible course list
        self.get('/')
        self.logout()
        self.login(USER_DICT['annika'])
        self.traverse(
            "Veranstaltungen", "Alle Veranstaltungen", "CdE-Party 2050", "Konfiguration"
        )
        f = self.response.forms['changeeventform']
        f['is_course_list_visible'] = False
        f['is_visible'] = True
        self.submit(f)
        self.traverse("Kursliste")
        self.assertPresence("Chillout mit Musik")
        self.logout()

        self.login(USER_DICT['emilia'])
        self.traverse("CdE-Party 2050")
        # Because of markdown smarty, the apostroph is replaced
        # with its typographically correct form here.
        self.assertPresence("Let‘s have a party!")
        self.assertNonPresence("Kursliste", div="sidebar")
        self.get('/event/event/2/course/list')
        self.assertPresence(
            "Die Kursliste ist noch nicht öffentlich", div='notifications'
        )

    def test_course_state_visibility(self) -> None:
        with self.switch_user("charly"):
            self.get("/event/event/1/course/list")
            self.assertNonPresence("fällt aus")
            self.get('/event/event/1/register')
            f = self.response.forms['registerform']
            # Course ε. Backup-Kurs is cancelled in track 3 (but still choosable).
            self.assertIn(
                '5', [value for (value, _, _) in f['track3.course_choice_0'].options]
            )

        with self.switch_user("garcia"):
            self.get("/event/event/1/course/list")
            self.assertNonPresence("fällt aus")
            self.get('/event/event/1/change')
            f = self.response.forms['changeeventform']
            f['is_course_state_visible'].checked = True
            self.submit(f)
            self.get('/event/event/1/course/list')
            self.assertPresence("fällt aus")

        with self.switch_user("charly"):
            self.get('/event/event/1/course/list')
            self.assertPresence("fällt aus")
            self.get('/event/event/1/register')
            f = self.response.forms['registerform']
            # Course ε. Backup-Kurs is cancelled in track 3 and no longer choosable.
            self.assertNotIn(
                '5', [value for (value, _, _) in f['track3.course_choice_0'].options]
            )

    @event_keeper
    @as_users("garcia")
    def test_part_summary_trivial(self) -> None:
        # check there is no log generation if nothing changes
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie",
            "Konfiguration",
            "Veranstaltungsteile",
        )
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        self.traverse({"href": "/event/event/1/part/1/change"})
        f = self.response.forms['changepartform']
        self.assertEqual("Warmup", f['title'].value)
        self.submit(f)

        # check there is no log generation if nothing changes
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms['fieldsummaryform']
        self.submit(f)

        self.assertLogEqual([], 'event', event_id=1, offset=self.EVENT_LOG_OFFSET)

    @as_users("annika")
    def test_part_summary_complex(self) -> None:
        event_id = 2
        log_expectation = []

        self.traverse(
            "Veranstaltungen",
            'Alle Veranstaltungen',
            'CdE-Party 2050',
            'Konfiguration',
            'Veranstaltungsteile',
        )
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        self.assertNonPresence("Cooldown")

        # Add a new part.
        self.traverse("Teil hinzufügen")
        f = self.response.forms['addpartform']
        f['title'] = "Cooldown"
        f['shortname'] = "cd"
        f['part_begin'] = "2244-4-5"
        f['part_end'] = "2233-6-7"
        f['fee'] = "123.45"
        self.submit(f, check_notification=False)
        self.assertValidationError('part_end', "Muss später als Beginn sein.")
        f['part_begin'] = "2233-4-5"
        self.submit(f)
        log_expectation.extend([
            {
                'code': const.EventLogCodes.part_created,
                'change_note': f['title'].value,
            },
            {
                'code': const.EventLogCodes.event_fee_created,
                'change_note': f['title'].value,
            },
        ])

        # Add a track to newly added part.
        self.traverse({"href": "/event/event/2/part/1001/change"})
        f = self.response.forms['changepartform']
        f['track_create_-1'].checked = True
        f['track_title_-1'] = "Chillout Training"
        f['track_shortname_-1'] = "Chillout"
        f['track_num_choices_-1'] = "1"
        f['track_min_choices_-1'] = "1"
        f['track_sortkey_-1'] = "1"
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.track_added,
            'change_note': f['track_title_-1'].value,
        })

        # Change the newly added part.
        self.traverse({"href": "/event/event/2/part/1001/change"})
        f = self.response.forms['changepartform']
        self.assertEqual("Cooldown", f['title'].value)
        self.assertEqual("cd", f['shortname'].value)
        self.assertEqual("Chillout Training", f['track_title_1001'].value)
        f['title'] = "Größere Hälfte"
        f['part_end'] = "2222-6-7"
        self.submit(f, check_notification=False)
        self.assertValidationError('part_end', "Muss später als Beginn sein")
        f['part_end'] = "2233-4-5"
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.part_changed,
            'change_note': f['title'].value,
        })
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")

        # Add another track.
        self.traverse({"href": "/event/event/2/part/1001/change"})
        f = self.response.forms['changepartform']
        self.assertNotIn('track_1002', f.fields)
        f['track_title_-1'] = "Spätschicht"
        f['track_shortname_-1'] = "Spät"
        f['track_num_choices_-1'] = "3"
        f['track_min_choices_-1'] = "4"
        f['track_sortkey_-1'] = "1"
        f['track_create_-1'].checked = True
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'track_min_choices_-1',
            "Muss kleiner oder gleich der Gesamtzahl von Kurswahlen sein.",
        )
        f['track_min_choices_-1'] = "2"
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.track_added,
            'change_note': f['track_title_-1'].value,
        })

        # Change the new track.
        self.traverse({"href": "/event/event/2/part/1001/change"})
        f = self.response.forms['changepartform']
        self.assertEqual("Spätschicht", f['track_title_1002'].value)
        f['track_title_1002'] = "Nachtschicht"
        f['track_shortname_1002'] = "Nacht"
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.track_updated,
            'change_note': f['track_title_1002'].value,
        })

        # delete the track
        self.traverse({"href": "/event/event/2/part/1001/change"})
        f = self.response.forms['changepartform']
        self.assertEqual("Nachtschicht", f['track_title_1002'].value)
        self.assertEqual("Nacht", f['track_shortname_1002'].value)
        f['track_delete_1002'].checked = True
        self.submit(f)
        log_expectation.extend([
            {
                'code': const.EventLogCodes.track_removed,
                'change_note': log_expectation[-1]['change_note'],
            },
        ])
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        self.assertNonPresence("Nachtschicht", div="part1001")

        # delete new part
        self.traverse("Teilnahmebeiträge")
        f = self.response.forms['deleteeventfeeform1001']
        self.submit(f)
        self.traverse("Veranstaltungsteile")
        f = self.response.forms['deletepartform1001']
        f['ack_delete'].checked = True
        self.submit(f)
        log_expectation.extend([
            {
                'code': const.EventLogCodes.event_fee_deleted,
                'change_note': log_expectation[0]['change_note'],
            },
            {
                'code': const.EventLogCodes.track_removed,
                'change_note': "Chillout Training",
            },
            {
                'code': const.EventLogCodes.part_deleted,
                'change_note': "Größere Hälfte",
            },
        ])

        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        self.assertNonPresence("Größere Hälfte")

        # check log
        self.assertLogEqual(log_expectation, realm="event", event_id=event_id)

    @as_users("garcia")
    def test_aposteriori_change_num_choices(self) -> None:
        # Increase number of course choices of track 2 ("Kaffekränzchen")
        self.get('/event/event/1/part/summary')
        self.traverse(
            {'description': "Teil bearbeiten", 'href': '/event/event/1/part/2/change'},
        )
        f = self.response.forms['changepartform']
        f['track_num_choices_2'] = "2"
        self.submit(f)

        # Change course choices as Orga
        self.traverse(
            "Anmeldungen",
            "Alle Anmeldungen",
            {'href': '/event/event/1/registration/3/show'},
            "Bearbeiten",
        )
        self.assertTitle(
            "Anmeldung von Garcia Generalis bearbeiten (Große Testakademie 2222)"
        )
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)
        f['track2.course_choice_0'] = 3
        self.submit(f)
        self.traverse("Bearbeiten")
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)

        # Amend registration with new choice and check via course_choices
        self.traverse("Meine Anmeldung", "Ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual('3', f['track2.course_choice_0'].value)
        # Check preconditions for second part
        self.assertIsNotNone(f.get('track1.course_choice_3', default=None))
        f['track2.course_choice_1'] = 4
        self.submit(f)
        self.traverse("Kurse", "Kurseinteilung")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 2
        f['course_id'] = 4
        f['position'] = 1
        self.submit(f)
        self.assertPresence("Garcia")

        # Reduce number of course choices of track 1 ("Morgenkreis")
        self.get('/event/event/1/part/summary')
        self.traverse({'href': '/event/event/1/part/2/change'})
        f = self.response.forms['changepartform']
        f['track_num_choices_1'] = "3"
        f['track_min_choices_1'] = "3"
        self.submit(f)

        # Check registration as Orga
        self.traverse(
            "Anmeldungen",
            "Alle Anmeldungen",
            {'href': '/event/event/1/registration/3/show'},
        )
        self.assertPresence('3. Wahl')
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')

        # Amend registration
        self.traverse("Meine Anmeldung")
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')
        self.traverse("Ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual('1', f['track1.course_choice_2'].value)
        self.assertIsNone(f.get('track1.course_choice_3', default=None))
        f['track1.course_choice_0'] = 2
        f['track1.course_choice_1'] = 4
        self.submit(f)

        # Change registration as orga
        self.traverse(
            "Anmeldungen",
            "Alle Anmeldungen",
            {'href': '/event/event/1/registration/3/show'},
            "Bearbeiten",
        )
        f = self.response.forms['changeregistrationform']
        self.assertIsNone(f.get('track1.course_choice_3', default=None))
        self.assertEqual('4', f['track1.course_choice_1'].value)
        self.assertEqual('1', f['track1.course_choice_2'].value)
        f['track1.course_choice_2'] = ''
        self.submit(f)
        self.assertNonPresence('Heldentum')

    @event_keeper
    @as_users("annika", "garcia")
    def test_change_event_fields(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/field/summary'},
        )
        # fields
        self.assertPresence(
            "Die Sortierung der Felder bitte nicht ändern!",
            div="field-definition-notes",
            exact=True,
        )
        self.assertPresence("Kursfelder", div="fieldsummaryform")
        self.assertPresence("Unterkunftsfelder", div="fieldsummaryform")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('transportation', f['field_name_2'].value)
        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.str
        f['entries_-1'] = """everything goes!
        vegetarian;no meat
        vegan;plants only"""
        self.submit(f, check_notification=False)
        self.assertValidationError('entries_-1', "Falsch formatierte Eingabe.")
        f['entries_-1'] = """all;everything goes
                vegetarian;no meat
                vegan;plants only"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('food_stuff', f['field_name_1001'].value)
        self.assertEqual(
            """pedes;by feet
car;own car available
etc;anything else""",
            f['entries_2'].value,
        )
        f['entries_2'] = """pedes;by feet
        broom;flying implements
        etc;anything else"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual(
            """pedes;by feet
broom;flying implements
etc;anything else""",
            f['entries_2'].value,
        )
        f['delete_1001'].checked = True
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertNotIn('field_name_1001', f.fields)

        if self.user_in("annika"):
            self.traverse(
                {'href': '/event/$'},
                {'href': '/event/list'},
                {'href': '/event/event/2/show'},
                {'href': '/event/event/2/field/summary'},
            )
            self.assertNonPresence("Kursfelder")

    @event_keeper
    @as_users("garcia")
    def test_event_fields_unique_name(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = f['field_name_8'].value
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.str
        self.submit(f, check_notification=False)
        self.assertValidationError('field_name_-1', "Feldname nicht eindeutig.")
        self.assertValidationError('field_name_8', "Feldname nicht eindeutig.")
        f = self.response.forms['fieldsummaryform']
        self.assertIn('field_name_1', f.fields)
        self.assertNotIn('field_name_1001', f.fields)

        # If we delete the old field first, this works.
        f['delete_8'] = True
        self.submit(f)

        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.str
        f['create_-2'].checked = True
        f['field_name_-2'] = "food_stuff"
        f['association_-2'] = const.FieldAssociations.registration
        f['kind_-2'] = const.FieldDatatypes.str
        self.submit(f, check_notification=False)
        self.assertValidationError('field_name_-1', "Feldname nicht eindeutig.")
        self.assertValidationError('field_name_-2', "Feldname nicht eindeutig.")

    @event_keeper
    @as_users("garcia")
    def test_event_fields_datatype(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'].force_value("invalid")
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertValidationError(
            "kind_-1", "Ungültige Eingabe für Enumeration 'FieldDatatypes'."
        )
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'].force_value(sum(x for x in const.FieldDatatypes))
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertValidationError(
            "kind_-1", "Ungültige Eingabe für Enumeration 'FieldDatatypes'."
        )

    @event_keeper
    @as_users("annika", "garcia")
    def test_event_fields_change_datatype(self) -> None:
        # First, remove the "lodge" field from the questionaire and the event's,
        # so it can be deleted
        self.get("/event/event/1/questionnaire/config")
        f = self.response.forms['configurequestionnaireform']
        f['delete_6'].checked = True
        self.submit(f)
        self.get("/event/event/1/change")
        f = self.response.forms['changeeventform']
        f['lodge_field_id'] = ''
        self.submit(f)

        # Change datatype of "lodge" field to phone number and check those are preserved
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['kind_3'] = const.FieldDatatypes.phone
        self.submit(f)
        self.traverse(
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_lodge'].checked = True
        self.submit(f)
        self.assertPresence("+49 1511 2345678")

        # Change datatype of "transportation" field to datetime and delete
        # options, delete and recreate "lodge" field with int type.
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['kind_2'] = const.FieldDatatypes.datetime
        f['entries_2'] = ""
        f['delete_3'].checked = True
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "lodge"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.int
        self.submit(f)

        # No page of the orga area should be broken by this
        self.traverse(
            {'href': '/event/event/1/stats'},
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/choices'},
            {'href': '/event/event/1/registration/checkin'},
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_lodge'].checked = True
        f['qsel_reg_fields.xfield_transportation'].checked = True
        self.submit(f)
        f = self.response.forms['queryform']
        f['qop_reg_fields.xfield_transportation'] = QueryOperators.empty.value
        self.submit(f)
        self.traverse(
            {'href': '/event/event/1/registration/1/show'},
            {'href': '/event/event/1/registration/1/change'},
        )

    @event_keeper
    @as_users("garcia")
    def test_event_fields_boolean(self) -> None:
        self.traverse(
            "Veranstaltungen", "Große Testakademie 2222", "Datenfelder konfigurieren"
        )
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = const.FieldAssociations.registration
        f['entries_-1'] = "True;definitely\nFalse;no way!"
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse("Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse("Fragebogen konfigurieren")
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'].checked = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['label_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "1001"
        self.submit(f)
        self.traverse("Fragebogen")
        f = self.response.forms['questionnaireform']
        f['fields.notevil'] = "True"
        self.submit(f)

    @event_keeper
    @as_users("garcia")
    def test_event_fields_date(self) -> None:
        self.traverse(
            "Veranstaltungen", "Große Testakademie 2222", "Datenfelder konfigurieren"
        )
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.date
        f['entries_-1'] = """2018-01-01;new year
        2018-10-03;party!
        2018-04-01;April fools"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse("Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse("Fragebogen konfigurieren")
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'].checked = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['label_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "1001"
        self.submit(f)
        self.traverse("Fragebogen")
        f = self.response.forms['questionnaireform']
        f['fields.notevil'] = "2018-10-03"
        self.submit(f)

    @event_keeper
    @as_users("annika", "garcia")
    def test_event_fields_query_capital_letter(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "CapitalLetters"
        f['association_-1'] = const.FieldAssociations.registration
        f['kind_-1'] = const.FieldDatatypes.str
        self.submit(f)
        self.get("/event/event/1/field/setselect?kind=1")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 1001
        self.submit(f)
        f = self.response.forms['fieldform']
        f['fields.CapitalLetters1'] = "Example Text"
        f['fields.CapitalLetters2'] = ""
        f['fields.CapitalLetters3'] = "Other Text"
        self.submit(f)
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertPresence("Anton")
        self.assertPresence("Garcia")
        self.assertPresence("Emilia")
        self.assertPresence("Example Text")
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_CapitalLetters'].checked = True
        f['qop_reg_fields.xfield_CapitalLetters'] = QueryOperators.nonempty.value
        f['qord_0'] = 'reg_fields.xfield_CapitalLetters'
        self.submit(f)
        self.assertPresence("Anton")
        self.assertPresence("Garcia")
        self.assertNonPresence("Emilia")
        self.assertPresence("Other Text")
        # Reset and do not specify operator to exhibit bug #1754
        self.traverse({'href': '/event/event/1/registration/query'})
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_CapitalLetters'].checked = True
        f['qord_0'] = 'reg_fields.xfield_CapitalLetters'
        self.submit(f)
        self.assertPresence("Other Text")

    @storage
    @as_users("annika", "garcia")
    def test_change_minor_form(self) -> None:
        self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['changeminorformform']
        self.submit(f, check_notification=False)
        self.assertValidationError('minor_form', "Darf nicht leer sein.")
        with open(self.testfile_dir / "form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['minor_form'] = webtest.Upload("form.pdf", data, "application/octet-stream")
        self.submit(f)
        self.traverse({'href': '/event/event/1/minorform'})
        with open(self.testfile_dir / "form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        # Remove the form again
        self.get("/event/event/1/show")
        self.assertTitle("Große Testakademie 2222")
        self.assertNonPresence("Kein Formular vorhanden")
        f = self.response.forms['removeminorformform']
        self.submit(f, check_notification=False)
        self.assertValidationError("ack_delete", "Muss markiert sein.", index=0)
        f['ack_delete'].checked = True
        self.submit(f, check_notification=False)
        self.assertNotification("Minderjährigenformular wurde entfernt.", "info")
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Formular vorhanden", div='minor-form')

    @event_keeper
    @as_users("annika", "ferdinand")
    def test_create_event(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/list'},
            {'href': '/event/event/create'},
        )
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['institution'] = const.PastInstitutions.private
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['part_begin'] = "2345-01-01"
        f['part_end'] = "1345-6-7"
        f['orga_ids'] = "DB-10-8"
        f['fee'] = "123.45"
        f['nonmember_surcharge'] = "8"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'orga_ids', "Einige dieser Accounts sind keine Veranstaltungsnutzer."
        )
        self.assertValidationError('part_end', "Muss später als Beginn sein.")
        f = self.response.forms['createeventform']
        f['part_end'] = "2345-6-7"
        f['orga_ids'] = "DB-2-7, DB-7-8"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Mit Co und Coco.")
        self.assertPresence("Beispiel")
        self.assertPresence("Garcia")

        # Check creation of parts and no tracks
        self.traverse("Konfiguration", "Veranstaltungsteile")
        self.assertPresence("Universale Akademie", div="part1001")
        self.assertPresence('01.01.2345', div='part1001_begin', exact=True)
        self.assertPresence('07.06.2345', div='part1001_end', exact=True)
        self.assertDivNotExists("#trackrow1001_1001")

        # Check log
        log_expectation: list[CdEDBObject] = [
            {
                'code': const.EventLogCodes.event_created,
                'event_id': 1001,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'persona_id': 2,
                'event_id': 1001,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'persona_id': 7,
                'event_id': 1001,
            },
            {
                'change_note': "Universale Akademie",
                'code': const.EventLogCodes.part_created,
                'event_id': 1001,
            },
            {
                'change_note': "Universale Akademie",
                'code': const.EventLogCodes.lodgement_group_created,
                'event_id': 1001,
            },
            {
                'change_note': "Universale Akademie",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 1001,
            },
            {
                'change_note': "Externenzusatzbeitrag",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 1001,
            },
            {
                'code': const.EventLogCodes.questionnaire_changed,
                'change_note': "Anmeldungs-Fragebogen",
                'event_id': 1001,
            },
        ]

        # Create another event with course track and orga mailinglist
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Alle Veranstaltungen'},
            {'description': 'Veranstaltung anlegen'},
        )
        f = self.response.forms['createeventform']
        f['title'] = "Alternative Akademie"
        f['institution'] = const.PastInstitutions.cde
        f['shortname'] = ""
        f['part_begin'] = "2345-01-01"
        f['part_end'] = "2345-6-7"
        f['orga_ids'] = "DB-1-9, DB-5-1"
        f['fee'] = "0"
        f['nonmember_surcharge'] = "0"
        f['create_track'].checked = True
        f['create_orga_list'].checked = True
        f['create_participant_list'].checked = True
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        # The following submissions with invalid shortnames also check for the
        # mailignlist creation bug in #1487.
        self.assertValidationError("shortname", "Darf nicht leer sein.")
        f['shortname'] = "²@³"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "shortname", "Darf nur aus druckbaren ASCII-Zeichen bestehen."
        )
        f['shortname'] = "AltAka"
        self.submit(f)
        self.assertTitle("Alternative Akademie")
        self.assertPresence("altaka-orga@aka.cde-ev.de")

        # Check creation of parts and no tracks
        self.traverse("Konfiguration", "Veranstaltungsteile")
        self.assertPresence("Alternative Akademie", div="part1002")
        self.assertPresence("Alternative Akademie", div="trackrow1002_1001")
        self.assertDivNotExists("#trackrow1002_1002")

        # Check event log
        log_expectation.extend([
            {
                'code': const.EventLogCodes.event_created,
                'event_id': 1002,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'persona_id': 1,
                'event_id': 1002,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'persona_id': 5,
                'event_id': 1002,
            },
            {
                'change_note': "Alternative Akademie",
                'code': const.EventLogCodes.part_created,
                'event_id': 1002,
            },
            {
                'change_note': "Alternative Akademie",
                'code': const.EventLogCodes.track_added,
                'event_id': 1002,
            },
            {
                'change_note': "Alternative Akademie",
                'code': const.EventLogCodes.lodgement_group_created,
                'event_id': 1002,
            },
            {
                'change_note': "Alternative Akademie",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 1002,
            },
            {
                'change_note': "Externenzusatzbeitrag",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 1002,
            },
            {
                'code': const.EventLogCodes.questionnaire_changed,
                'change_note': "Anmeldungs-Fragebogen",
                'event_id': 1002,
            },
            {
                'change_note': "Mailadresse der Orgas gesetzt.",
                'code': const.EventLogCodes.event_changed,
                'event_id': 1002,
            },
        ])
        self.assertLogEqual(
            log_expectation, realm="event", offset=self.EVENT_LOG_OFFSET
        )

        # Check mailinglist creation
        # first the orga list
        self.traverse(
            {'description': 'Mailinglisten'},
            {'description': 'Alternative Akademie Orgateam'},
        )
        self.assertPresence("Anton", div="moderator-list")
        self.assertPresence("Emilia", div="moderator-list")
        self.traverse({'description': 'Konfiguration'})
        f = self.response.forms['configuremailinglistform']
        self.assertEqual('altaka-orga', f['local_part'].value)
        self.assertPresence("Orga (Opt-out)")
        self.assertEqual('AltAka', f['subject_prefix'].value)

        # then the participant list
        self.traverse(
            {'description': 'Mailinglisten'},
            {'description': 'Alternative Akademie Teilnehmer'},
        )
        self.assertPresence("Anton", div="moderator-list")
        self.assertPresence("Emilia", div="moderator-list")
        self.traverse({'description': 'Konfiguration'})
        f = self.response.forms['configuremailinglistform']
        self.assertEqual('altaka-all', f['local_part'].value)
        self.assertPresence("Teilnehmer/Anmeldungen (Opt-out)")
        # TODO check for correct registration part stati
        self.assertEqual('AltAka', f['subject_prefix'].value)

        # Check ml log
        ml_log_expectation = [
            {
                'code': const.MlLogCodes.list_created,
                'mailinglist_id': 1001,
            },
            {
                'code': const.MlLogCodes.moderator_added,
                'persona_id': 1,
                'mailinglist_id': 1001,
            },
            {
                'code': const.MlLogCodes.moderator_added,
                'persona_id': 5,
                'mailinglist_id': 1001,
            },
            {
                'code': const.MlLogCodes.list_created,
                'mailinglist_id': 1002,
            },
            {
                'code': const.MlLogCodes.moderator_added,
                'persona_id': 1,
                'mailinglist_id': 1002,
            },
            {
                'code': const.MlLogCodes.moderator_added,
                'persona_id': 5,
                'mailinglist_id': 1002,
            },
        ]
        self.assertLogEqual(
            ml_log_expectation, realm="ml", _mailinglist_ids={1001, 1002}
        )

    @as_users("annika", "garcia")
    def test_change_course(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie",
            "Kursliste",
            {'href': '/event/event/1/course/2/change'},
            "Abbrechen",
            "Vorherige",
            "Bearbeiten",
        )
        self.assertTitle("Heldentum bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['configurecourseform']
        self.assertEqual("10", f['max_size'].value)
        self.assertEqual("2", f['min_size'].value)
        self.assertEqual(True, f['segment1'].checked)
        self.assertEqual(False, f['segment2'].checked)
        self.assertEqual(True, f['segment3'].checked)
        self.assertEqual(True, f['segment1.is_active'].checked)
        self.assertEqual(False, f['segment2.is_active'].checked)
        self.assertEqual(True, f['segment3.is_active'].checked)
        self.assertEqual("Wald", f['fields.room'].value)
        self.assertEqual(True, f['is_visible'].checked)
        f['shortname'] = "Helden"
        f['nr'] = "ω"
        f['max_size'] = "21"
        f['segment1'] = False
        f['segment2'] = True
        f['segment2.is_active'] = True
        f['segment3.is_active'] = False
        f['fields.room'] = "Canyon"
        f['is_visible'] = False
        self.submit(f)
        self.assertTitle("Kurs Helden (Große Testakademie 2222)")
        self.traverse("Bearbeiten")
        f = self.response.forms['configurecourseform']
        self.assertEqual(f['nr'].value, "ω")
        self.assertEqual("21", f['max_size'].value)
        self.assertEqual(False, f['segment1'].checked)
        self.assertEqual(True, f['segment2'].checked)
        self.assertEqual(True, f['segment3'].checked)
        self.assertEqual(False, f['segment1.is_active'].checked)
        self.assertEqual(True, f['segment2.is_active'].checked)
        self.assertEqual(False, f['segment3.is_active'].checked)
        self.assertEqual("Canyon", f['fields.room'].value)
        self.assertEqual(False, f['is_visible'].checked)

        log_expecation = [
            {
                "code": const.EventLogCodes.course_changed,
                "change_note": "Planetenretten für Anfänger",
            },
            {
                "code": const.EventLogCodes.course_segment_deleted,
                "change_note": "Planetenretten für Anfänger (Morgenkreis (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_deactivated,
                "change_note": "Planetenretten für Anfänger (Morgenkreis (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": "Planetenretten für Anfänger (Kaffeekränzchen (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_activated,
                "change_note": "Planetenretten für Anfänger (Kaffeekränzchen (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_deactivated,
                "change_note": "Planetenretten für Anfänger (Arbeitssitzung (Zweite Hälfte))",
            },
        ]
        self.assertLogEqual(
            log_expecation, "event", event_id=1, offset=self.EVENT_LOG_OFFSET
        )

    @event_keeper
    @as_users("annika", "garcia")
    def test_create_delete_course(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie", "Kursliste")
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertPresence("Planetenretten für Anfänger")
        self.assertNonPresence("Abstract Nonsense")
        self.traverse("Kurse", "Kurs hinzufügen")
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['configurecourseform']
        f['title'] = title = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['instructors'] = "Alexander Grothendieck"
        f['notes'] = "transcendental appearence"
        f['segment2'] = False
        f['segment3.is_active'] = False
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertNonPresence("Kursfelder gesetzt.", div="notifications")
        self.assertPresence("transcendental appearence")
        self.assertPresence("Alexander Grothendieck")
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("math bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['configurecourseform']
        self.assertEqual(True, f['segment1'].checked)
        self.assertEqual(False, f['segment2'].checked)
        self.assertEqual(True, f['segment3'].checked)
        self.assertEqual(True, f['segment1.is_active'].checked)
        self.assertEqual(False, f['segment2.is_active'].checked)
        self.assertEqual(False, f['segment3.is_active'].checked)
        self.traverse("Abbrechen")
        f = self.response.forms['deletecourseform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertNonPresence("Abstract Nonsense")

        log_expecation = [
            {
                "code": const.EventLogCodes.course_created,
                "change_note": title,
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": f"{title} (Morgenkreis (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_activated,
                "change_note": f"{title} (Morgenkreis (Erste Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": f"{title} (Arbeitssitzung (Zweite Hälfte))",
            },
            {
                "code": const.EventLogCodes.course_deleted,
                "change_note": title,
            },
        ]
        self.assertLogEqual(
            log_expecation, "event", event_id=1, offset=self.EVENT_LOG_OFFSET
        )

    @as_users("annika", "garcia")
    def test_create_course_with_fields(self) -> None:
        self.get("/event/event/1/course/create")
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['configurecourseform']
        f['title'] = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['fields.room'] = "Outside"
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertPresence("Outside")

    @as_users("charly", "daniel", "rowena")
    @prepsql("UPDATE core.personas SET birthday = date '2220-02-19' WHERE id = 4;")
    def test_register(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        # check participant info page for unregistered users
        participant_info_url = '/event/event/1/notes'
        self.get(participant_info_url)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Teilnehmer der Veranstaltung.", div='notifications')

        # now, start registration testing
        surcharge = "Da Du kein CdE-Mitglied bist, musst Du "
        self.traverse("Anmelden")
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        if self.user_in('charly'):
            self.assertNonPresence(surcharge)
            self.assertPresence("13.05.1984")
            self.assertNonPresence("Gemischte Unterbringung nicht möglich")
            self.assertDivNotExists("#minor-with-guardian")
        elif self.user_in('daniel'):
            self.assertPresence(surcharge)
            self.assertPresence("19.02.2220")
            self.assertNonPresence("Gemischte Unterbringung nicht möglich")
            self.assertPresence(
                "gemeinsam mit einem Erziehungsberechtigten", div="minor-with-guardian"
            )
        elif self.user_in('rowena'):
            self.assertPresence(surcharge)
            self.assertPresence("26.08.932")
            self.assertNonPresence("Gemischte Unterbringung nicht möglich")
            self.assertDivNotExists("#minor-with-guardian")
        else:
            self.fail("Please reconfigure the users for the above checks.")

        self.assertPresence("Warmup (02.02.2222 – 02.02.2222)")
        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['reg.mixed_lodging'] = 'True'
        f['reg.notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        self.assertIn('track3.course_choice_2', f.fields)
        self.assertNotIn(
            '3', tuple(o for o, _, _ in f['track3.course_choice_1'].options)
        )
        f['track3.course_choice_0'] = 2
        f['track3.course_instructor'] = 2
        # No second choice given -> expecting error
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertValidationError(
            'track3.course_choice_1', "Du musst mindestens 2 Kurse wählen."
        )
        f['track3.course_choice_1'] = 2
        # Two equal choices given -> expecting error
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertValidationError(
            'track3.course_choice_1',
            "Du kannst diesen Kurs nicht als 1. und 2. Wahl wählen.",
        )
        f['track3.course_choice_1'] = 4
        # Chose instructed course also as course choice -> expecting error
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertValidationError(
            'track3.course_choice_0', "Bitte wähle nicht deinen eigenen Kurs."
        )
        f['track3.course_choice_0'] = 5
        # Now, we did it right.
        self.submit(f)
        text = self.fetch_mail_content()
        # This should work only once.
        self.submit(f, check_notification=False)
        self.assertPresence("Bereits angemeldet", div='notifications')
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Offen (Bezahlung ausstehend)")
        mail_surcharge = "Externenbeitrag"
        complex_fee = "Beitrag setzt sich wie folgt zusammen"
        if self.user_in('charly'):
            self.assertNotIn(mail_surcharge, text)
            self.assertNotIn(complex_fee, text)
            self.assertIn("461,49", text)
        elif self.user_in('daniel'):
            self.assertIn(mail_surcharge, text)
            self.assertIn(complex_fee, text)
            self.assertIn("442,49", text)
        elif self.user_in('rowena'):
            self.assertIn(mail_surcharge, text)
            self.assertIn(complex_fee, text)
            self.assertIn("466,49", text)
        else:
            self.fail("Please reconfigure the users for the above checks.")
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.traverse("Ändern")
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        self.assertNonPresence("Morgenkreis")
        self.assertNonPresence("Kaffeekränzchen")
        self.assertPresence("Arbeitssitzung")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("5", f['track3.course_choice_0'].value)
        self.assertEqual("4", f['track3.course_choice_1'].value)
        self.assertEqual("", f['track3.course_choice_2'].value)
        self.assertEqual("2", f['track3.course_instructor'].value)
        self.assertPresence("Ich freu mich schon so zu kommen")
        f['reg.notes'] = "Ich kann es kaum erwarten!"
        f['track3.course_choice_0'] = 4
        f['track3.course_choice_1'] = 2
        f['track3.course_choice_2'] = 5
        f['track3.course_instructor'] = 1
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Ich kann es kaum erwarten!")
        self.traverse("Ändern")
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['track3.course_choice_0'].value)
        self.assertEqual("2", f['track3.course_choice_1'].value)
        self.assertEqual("5", f['track3.course_choice_2'].value)
        self.assertEqual("1", f['track3.course_instructor'].value)
        self.assertPresence("Ich kann es kaum erwarten!")

        # check that participant info page is only visible for accepted registrations
        with self.assertRaises(IndexError):
            self.traverse({'href': participant_info_url})
        self.get(participant_info_url)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Teilnehmer der Veranstaltung", div='notifications')

        # check log
        # TODO Rewrite this test to not require reset to work
        self.logout()
        self.login("garcia")
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Log")
        self.assertPresence(
            "Anmeldung erstellt", div=str(self.EVENT_LOG_OFFSET + 1) + "-1001"
        )
        self.assertPresence(
            "Anmeldung durch Teilnehmer bearbeitet.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    @as_users("emilia")
    def test_registration_fee_qrcode(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Meine Anmeldung")
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Überweisung")
        self.assertPresence("Betrag 466,49 €", div="registrationsummary")
        self.assertPresence("QR", div="show-registration-fee-qr")
        save = self.response
        self.traverse("QR")
        self.response = save

        event = self.event.get_event(self.key, 1)
        persona = self.core.get_event_user(self.key, self.user['id'])

        qr_expectation = b"""\
BCD
002
2
SCT
BFSWDE33XXX
CdE e.V.
DE26370205000008068900
EUR466.49


Teilnahmebeitrag Grosse Testakademie 2222, Emilia Eventis, DB-5-1"""
        self.assertEqual(
            qr_expectation,
            _make_epc_qr_data(
                account=cast(Accounts, event.iban),
                reference=make_event_fee_reference(persona, event),
                amount=decimal.Decimal("466.49"),
            ),
        )
        self.get("/event/event/1/registration/2/fee/qr")
        with self.assertRaises(PrivilegeError):
            self.get("/event/event/1/registration/1/fee/qr", status=403)

    @as_users("anton")
    def test_registration_status(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/status'},
        )
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")

        self.traverse("Als Orga ansehen")  # shorthand link shown for orga/event admin
        self.assertTitle("Anmeldung von Anton Administrator (Große Testakademie 2222)")
        self.traverse("Meine Anmeldung")
        with self.switch_user('berta'):  # but not for unprivileged users
            self.traverse("angemeldet")
            self.assertNoLink("/event/event/1/registration/.*/show")
        self.assertNonPresence("Warteliste")
        self.assertNonPresence("Eingeteilt in")
        self.assertPresence("α. Planetenretten für Anfänger")
        self.assertPresence("β. Lustigsein für Fortgeschrittene")
        self.assertPresence("Ich stimme zu, dass meine Daten")
        self.assertPresence("353,99 € auf folgendes Konto")

        # Payment checks with iban
        self._set_payment_info(1, event_id=1, amount_paid=decimal.Decimal("0"))
        self.traverse({'href': '/event/event/1/registration/status'})
        self.assertPresence("Du musst noch den übrigen Betrag von 553,99 € bezahlen.")
        self.assertPresence("Bitte überweise 553,99 € auf folgendes Konto")
        self._set_payment_info(1, event_id=1, amount_paid=decimal.Decimal("100"))
        self.traverse("Meine Anmeldung")
        self.assertPresence("Bitte überweise 453,99 € auf folgendes Konto")
        self.assertPresence("Du hast bereits 100,00 € bezahlt.")
        self.assertPresence("Du musst noch den übrigen Betrag von 453,99 € bezahlen.")
        self._set_payment_info(1, event_id=1, amount_paid=decimal.Decimal("1000"))
        self.traverse("Meine Anmeldung")
        self.assertNonPresence("Überweisung")
        self.assertNonPresence("Konto")
        self.assertNonPresence("1000,00")
        self.assertPresence(
            "Du hast 446,01 € mehr bezahlt als deinen Teilnahmebeitrag von 553,99 €."
        )
        self._set_payment_info(1, event_id=1, amount_paid=decimal.Decimal("200"))

        # Payment checks without iban
        self.traverse({'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['iban'] = ""
        f['is_course_assignment_visible'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/status'})
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Eingeteilt in")
        self.assertPresence("separat mitteilen, wie du deinen Teilnahmebeitrag")
        self.assertPresence("Du hast bereits 200,00 € bezahlt.")
        self.assertPresence("Du musst noch den übrigen Betrag von 353,99 € bezahlen.")

        # check payment messages for different registration stati
        payment_pending = "Bezahlung ausstehend"

        # sample data are for part 1, 2, 3: not_applied, open, participant
        self.assertPresence(payment_pending)
        self.traverse("Index")
        self.assertPresence(payment_pending, div='event-box')
        self.traverse("Veranstaltungen")
        self.assertPresence(payment_pending, div='current-events')

        # registration stati that are not really registered
        self.get('/event/event/1/registration/1/change')
        f = self.response.forms['changeregistrationform']
        f['part1.status'] = const.RegistrationPartStati.not_applied
        f['part2.status'] = const.RegistrationPartStati.cancelled
        f['part3.status'] = const.RegistrationPartStati.rejected
        self.submit(f)
        self.traverse("Index")
        self.assertPresence("ehemals angemeldet", div='event-box')
        self.assertNonPresence(payment_pending)
        self.traverse("Veranstaltungen")
        self.assertPresence("ehemals angemeldet", div='current-events')
        self.assertNonPresence(payment_pending)

        # guests do not necessarily need to pay
        self.get('/event/event/1/registration/1/change')
        f = self.response.forms['changeregistrationform']
        f['part3.status'] = const.RegistrationPartStati.guest
        self.submit(f)
        self.traverse("Index")
        self.assertPresence("bereits angemeldet", div='event-box')
        self.assertNonPresence(payment_pending)
        self.traverse("Veranstaltungen")
        self.assertPresence("bereits angemeldet", div='current-events')
        self.assertNonPresence(payment_pending)
        self.traverse("angemeldet")
        self.assertNonPresence(payment_pending)

        # participant in all parts
        self.get('/event/event/1/registration/1/change')
        f = self.response.forms['changeregistrationform']
        f['part1.status'] = const.RegistrationPartStati.participant
        f['part2.status'] = const.RegistrationPartStati.participant
        f['part3.status'] = const.RegistrationPartStati.participant
        self.submit(f)
        self.traverse("Meine Anmeldung")
        self.assertPresence("Regulärer Beitrag 584,49 €")
        self.assertPresence("KL-Erstattung -20,00 €")
        self.assertPresence("Solidarische Reduktion -0,01 €")
        self.assertPresence("Gesamtsumme 564,48 €")

        # participant again, only for one part
        self.get('/event/event/1/registration/1/change')
        f = self.response.forms['changeregistrationform']
        f['part1.status'] = const.RegistrationPartStati.not_applied
        f['part2.status'] = const.RegistrationPartStati.not_applied
        f['part3.status'] = const.RegistrationPartStati.participant
        self.submit(f)
        self._set_payment_info(1, event_id=1, amount_paid=decimal.Decimal("0"))
        self.traverse("Meine Anmeldung")
        self.assertPresence("430,99 €")
        self.assertNonPresence("bereits bezahlt")
        self.assertPresence(payment_pending)

        # unset fee for the only part participated in - no payment needed anymore
        self.traverse("Teilnahmebeiträge")
        f = self.response.forms['deleteeventfeeform3']
        self.submit(f)
        self.traverse("Index")
        self.assertNonPresence(payment_pending)
        self.traverse("Veranstaltungen")
        self.assertNonPresence(payment_pending)
        self.traverse("angemeldet")
        self.assertNonPresence(payment_pending)

        self.traverse(
            "Veranstaltunge", "CdE-Party", "Anmeldungen", "Anmeldung hinzufügen"
        )
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = self.user['DB-ID']
        f['part4.status'] = const.RegistrationPartStati.cancelled
        self.submit(f)
        self.traverse("Meine Anmeldung")
        self.assertPresence("Anmeldestatus Abgemeldet")
        self.assertNonPresence("Bezahlung")

    def test_register_no_registration_end(self) -> None:
        # Remove registration end (soft and hard) from Große Testakademie 2222
        self.login(USER_DICT['garcia'])
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Konfiguration")
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['registration_soft_limit'] = ""
        f['registration_hard_limit'] = ""
        self.submit(f)
        self.logout()

        # Charly tries registering and amending registraions. We do less checks
        # than in test_register()
        # (the login checks the dashboard for Exceptions, by the way)
        self.login(USER_DICT['charly'])
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Anmelden")
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['reg.notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['parts'] = ['1']
        f['reg.mixed_lodging'] = 'True'
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        text = self.fetch_mail_content()
        self.assertIn("10,50", text)
        self.traverse("Ändern")
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")

    @as_users("berta")
    @prepsql(
        "DELETE FROM event.course_choices;"
        "DELETE FROM event.registration_tracks;"
        "DELETE FROM event.registration_parts;"
        "DELETE FROM event.registrations;"
        "UPDATE event.event_fees SET condition = 'part.Wu and field.is_child' WHERE id = 4;",
    )
    def test_register_conditional_fee_with_event_field(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Anmelden")
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertPresence("Ich bin unter 13 Jahre alt.")
        f = self.response.forms["registerform"]
        self.assertFalse(f['fields.is_child'].checked)
        f['fields.is_child'].checked = True
        f['parts'] = [1]
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Betrag 5,50 €")
        self.traverse("Ändern")
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms["amendregistrationform"]
        self.assertTrue(f['fields.is_child'].checked is True)
        f['fields.is_child'].checked = False
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Betrag 10,50 €")

    @event_keeper
    @as_users("annika")
    def test_registration_questionnaire(self) -> None:
        event_id = 2
        # Create new boolean registration fields
        event_update = {
            "registration_start": now(),
            "registration_soft_limit": None,
            "registration_hard_limit": None,
            "fields": {
                -1: {
                    "field_name": "is_child",
                    "kind": const.FieldDatatypes.bool,
                    "association": const.FieldAssociations.registration,
                },
                -2: {
                    "field_name": "plus_one",
                    "kind": const.FieldDatatypes.bool,
                    "association": const.FieldAssociations.registration,
                },
                -3: {
                    "field_name": "partner",
                    "kind": const.FieldDatatypes.str,
                    "association": const.FieldAssociations.registration,
                },
                -4: {
                    "field_name": "anzahl_kissen",
                    "kind": const.FieldDatatypes.int,
                    "association": const.FieldAssociations.registration,
                },
                -5: {
                    "field_name": "eats_meats",
                    "kind": const.FieldDatatypes.str,
                    "association": const.FieldAssociations.registration,
                    "entries": """meat;Eat meat everyday!
                        half-vegetarian;Sometimes
                        vegetarian;Meat is Murder!
                        vegan;Milk is Murder too!""",
                },
                -6: {
                    "field_name": "favorite_day",
                    "kind": const.FieldDatatypes.date,
                    "association": const.FieldAssociations.registration,
                },
            },
        }
        self.event.set_event(self.key, event_id, event_update)
        self.event.create_event_fee(
            self.key,
            event_id,
            {
                "title": "Is Child",
                "amount": "-10",
                "condition": "part.Party AND field.is_child",
                "kind": const.EventFeeType.common,
            },
        )
        self.event.create_event_fee(
            self.key,
            event_id,
            {
                "title": "Plus One",
                "amount": "+14.99",
                "condition": "part.Party AND field.plus_one",
                "kind": const.EventFeeType.common,
            },
        )
        self.event.set_questionnaire(
            self.key,
            event_id,
            const.QuestionnaireUsages.registration,
            [
                {
                    "role": const.QuestionnaireRowRole.my_data,
                },
                {
                    "role": const.QuestionnaireRowRole.part_selection,
                },
                {
                    "role": const.QuestionnaireRowRole.fee_preview,
                },
                {
                    "role": const.QuestionnaireRowRole.course_choices,
                },
                {
                    "role": const.QuestionnaireRowRole.list_consent,
                },
                {
                    "role": const.QuestionnaireRowRole.foto_notice,
                },
                {
                    "role": const.QuestionnaireRowRole.mixed_lodging,
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1001,
                    "label": "Ich bin unter 13 Jahre alt.",
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1002,
                    "label": "Ich bringe noch jemanden mit.",
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1003,
                    "label": "Name des Partners.",
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1004,
                    "label": "Anzahl an Kissen",
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1005,
                    "label": "Essgewohnheiten.",
                },
                {
                    "role": const.QuestionnaireRowRole.event_field,
                    "field_id": 1006,
                    "label": "Dein Lieblingstag",
                },
            ],
        )

        self.get(f"/event/event/{event_id}/register")
        self.assertTitle("Anmeldung für CdE-Party 2050")
        f = self.response.forms['registerform']
        self.assertPresence(
            "Ich bin unter 13 Jahre alt.", div="registrationquestionnaire"
        )
        f['fields.is_child'].checked = True
        self.assertPresence(
            "Ich bringe noch jemanden mit.", div="registrationquestionnaire"
        )
        f['fields.plus_one'].checked = True
        self.assertPresence("Name des Partners", div="registrationquestionnaire")
        f['fields.partner'] = ""
        f['fields.anzahl_kissen'] = ""
        self.assertPresence("Essgewohnheiten", div="registrationquestionnaire")
        f['fields.eats_meats'] = "vegan"
        self.assertPresence("Dein Lieblingstag", div="registrationquestionnaire")
        self.submit(f, check_notification=False)
        f = self.response.forms['registerform']
        self.assertValidationError('fields.anzahl_kissen', "Darf nicht leer sein.")
        f['fields.anzahl_kissen'] = 3
        self.assertValidationError('fields.favorite_day', "Darf nicht leer sein.")
        f['fields.favorite_day'] = now().date().isoformat()
        self.submit(f)
        self.assertTitle("Deine Anmeldung (CdE-Party 2050)")
        self.assertPresence("21,99 €", div="registrationsummary")

    @as_users("garcia")
    def test_questionnaire(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Konfiguration")
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse("Fragebogen")
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual("car", f['fields.transportation'].value)
        f['fields.transportation'] = "etc"
        self.assertEqual("", f['fields.lodge'].value)
        f['fields.lodge'] = "Bitte in ruhiger Lage.\nEcht."
        self.submit(f)
        with self.conf.with_overrides(EVENT_LIMITED_ACCESS_CUTOFF_ID=1):
            self.submit(f, check_notification=False)
            self.assertNotification("Veranstaltungssperre aktiviert.")
        self.traverse("Fragebogen")
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual("etc", f['fields.transportation'].value)
        self.assertEqual("Bitte in ruhiger Lage.\nEcht.", f['fields.lodge'].value)

        # check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Veranstaltung geändert", div=str(self.EVENT_LOG_OFFSET + 1) + "-1001"
        )
        self.assertPresence(
            "Fragebogen durch Teilnehmer bearbeitet.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    def _create_event_field(self, fdata: CdEDBObject) -> None:
        self.traverse({'description': "Datenfelder konfigurieren"})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        for k, v in fdata.items():
            f[k + "_-1"] = v
        self.submit(f)

    @event_keeper
    @unittest.skip("removed feature.")
    @as_users("annika")
    def test_fee_modifiers(self) -> None:
        self.traverse("Veranstaltungen", "Alle Veranstaltungen", "CdE-Party 2050")
        self._create_event_field({
            "field_name": "field_is_child1",
            "kind": const.FieldDatatypes.bool,
            "association": const.FieldAssociations.registration,
        })  # id 1001
        self._create_event_field({
            "field_name": "field_is_child2",
            "kind": const.FieldDatatypes.str,
            "association": const.FieldAssociations.registration,
        })  # id 1002
        self._create_event_field({
            "field_name": "field_is_child3",
            "kind": const.FieldDatatypes.bool,
            "association": const.FieldAssociations.course,
        })  # id 1003

        self.traverse("Veranstaltungsteile")
        self.traverse({"href": "/event/event/2/part/4/change"})
        f: webtest.Form = self.response.forms["changepartform"]
        f['fee_modifier_create_-1'].checked = True
        f['fee_modifier_modifier_name_-1'] = "Ich bin Unter 13 Jahre alt."
        f['fee_modifier_amount_-1'] = "abc"
        # check that only fitting fields are shown in the drop-down
        self.assertEqual(
            ['1001'], [x[0] for x in f['fee_modifier_field_id_-1'].options]
        )
        f['fee_modifier_field_id_-1'].force_value(1002)
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'fee_modifier_amount_-1', "Ungültige Eingabe für eine Dezimalzahl"
        )

        f['fee_modifier_modifier_name_-1'] = "modifier_is_child1"
        f['fee_modifier_amount_-1'] = "-5"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'fee_modifier_field_id_-1', "Unpassendes Datenfeld für Beitragsmodifikator."
        )

        f['fee_modifier_field_id_-1'].force_value(1003)
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'fee_modifier_field_id_-1', "Unpassendes Datenfeld für Beitragsmodifikator."
        )

        f['fee_modifier_field_id_-1'].force_value('')
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_field_id_-1', "Darf nicht leer sein.")

        f['fee_modifier_field_id_-1'] = '1001'
        self.submit(f)

        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms['fieldsummaryform']
        f['kind_1002'] = const.FieldDatatypes.bool
        f['association_1003'] = const.FieldAssociations.registration
        self.submit(f)

        self.traverse("Veranstaltungsteile")
        self.traverse({"href": "/event/event/2/part/4/change"})
        f = self.response.forms['changepartform']
        f['fee_modifier_create_-1'].checked = True
        f['fee_modifier_modifier_name_-1'] = "modifier_is_child1"
        f['fee_modifier_amount_-1'] = "-7"
        f['fee_modifier_field_id_-1'] = 1001
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'fee_modifier_field_id_-1',
            "Nicht mehr als ein Beitragsmodifikator pro"
            " Veranstaltungsteil darf mit dem gleichen Feld"
            " verbunden sein.",
        )
        self.assertValidationError(
            'fee_modifier_modifier_name_-1',
            "Nicht mehr als ein Beitragsmodifikator pro"
            " Veranstaltungsteil darf den selben Bezeichner haben.",
        )

        f['fee_modifier_modifier_name_-1'] = "modifier_is_child2"
        f['fee_modifier_field_id_-1'] = 1002
        self.submit(f)

        # add, change and delete a fee-modifier simultaneously, involving the same field
        # delete: is_child1 (id 1001): field 1001 -> None
        # edit:   is_child2 (id 1002): field 1002 -> field 1001
        # new:    is_child3 (id None): None       -> field 1002
        self.traverse({"href": "/event/event/2/part/4/change"})
        f = self.response.forms['changepartform']
        f['fee_modifier_delete_1001'].checked = True
        f['fee_modifier_field_id_1002'] = 1001
        f['fee_modifier_create_-1'].checked = True
        f['fee_modifier_modifier_name_-1'] = "modifier_is_child3"
        f['fee_modifier_amount_-1'] = "0"
        f['fee_modifier_field_id_-1'] = 1002
        self.submit(f)
        self.assertNonPresence("modifier_is_child1")
        self.assertPresence("modifier_is_child2", div='feemodifierrow_4_1002')
        self.assertPresence("field_is_child1", div='feemodifierrow_4_1002')
        self.assertPresence("modifier_is_child3", div='feemodifierrow_4_1003')
        self.assertPresence("field_is_child2", div='feemodifierrow_4_1003')

        # check log
        log_expectation = [
            {
                'change_note': "field_is_child1",
                'code': const.EventLogCodes.field_added,
                'event_id': 2,
            },
            {
                'change_note': "field_is_child2",
                'code': const.EventLogCodes.field_added,
                'event_id': 2,
            },
            {
                'change_note': "field_is_child3",
                'code': const.EventLogCodes.field_added,
                'event_id': 2,
            },
            {
                'change_note': "modifier_is_child1",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 2,
            },
            {
                'change_note': "field_is_child2",
                'code': const.EventLogCodes.field_updated,
                'event_id': 2,
            },
            {
                'change_note': "field_is_child3",
                'code': const.EventLogCodes.field_updated,
                'event_id': 2,
            },
            {
                'change_note': "modifier_is_child2",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 2,
            },
            {
                'change_note': "modifier_is_child1",
                'code': const.EventLogCodes.event_fee_deleted,
                'event_id': 2,
            },
            {
                'change_note': "modifier_is_child2",
                'code': const.EventLogCodes.event_fee_modified,
                'event_id': 2,
            },
            {
                'change_note': "modifier_is_child3",
                'code': const.EventLogCodes.event_fee_created,
                'event_id': 2,
            },
        ]
        self.assertLogEqual(
            log_expectation, realm="event", offset=self.EVENT_LOG_OFFSET
        )

    @event_keeper
    @as_users("garcia")
    def test_event_fees(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Teilnahmebeiträge",
            "Beitrag hinzufügen",
        )
        f = self.response.forms['configureeventfeeform']
        f['title'] = "New fee!"
        f['kind'] = const.EventFeeType.common
        f['amount'] = 1
        f['condition'] = "field.unknown_field OR part.unknown_part"
        self.submit(f, check_notification=False)
        self.assertValidationError('condition', "Unknown field(s): 'unknown_field'")
        self.assertValidationError(
            'condition', "Unknown part shortname(s): 'unknown_part'"
        )
        f['condition'] = "part.Wu AND (part.1.H. OR part.2.H.)"
        self.submit(f)

        self.assertTitle("Teilnahmebeiträge (Große Testakademie 2222)")
        self.assertPresence(
            "Teilnahmebeitrag Warmup 10,50 € 4 Zu Zahlen: 1 Bezahlt: 42,00 € 10,50 €",
            div="eventfee_1",
        )

        self.traverse({'linkid': "eventfee1001_change"})
        f = self.response.forms['configureeventfeeform']
        f['notes'] = "Some more information."
        self.submit(f)

        self.traverse("Meine Anmeldung", "Als Orga ansehen", "Teilnahmebeitragsdetails")
        self.assertHasClass("#eventfee-title-1", "alert-success")
        self.assertHasClass("#eventfee-title-2", "alert-success")
        self.assertHasClass("#eventfee-title-3", "alert-success")
        self.assertHasClass("#eventfee-title-4", "alert-danger")
        self.assertHasClass("#eventfee-title-5", "alert-danger")
        self.assertHasClass("#eventfee-title-6", "alert-danger")
        self.assertHasClass("#eventfee-title-7", "alert-danger")
        self.assertHasClass("#eventfee-title-8", "alert-success")
        self.assertHasClass("#eventfee-title-9", "alert-success")

        # TODO: actually add some tests for conditions.

        f = self.response.forms['quickregistrationform']
        f['phrase'] = "Inga"
        self.submit(f)
        self.assertTitle("Anmeldung von Inga Iota (Große Testakademie 2222)")
        self.assertPresence("431,99 €", div="amount-owed")

        self.event.set_event(
            self.key,
            1,
            {
                'parts': {
                    part_id: {
                        'part_begin': "2322-01-01",
                        'part_end': "2322-01-01",
                    }
                    for part_id in [1, 2, 3]
                },
            },
        )

        self.submit(f)
        self.assertTitle("Anmeldung von Inga Iota (Große Testakademie 2222)")
        self.assertPresence("450,99 €", div="amount-owed")

    @event_keeper
    @as_users("garcia")
    def test_waitlist(self) -> None:
        # Create some new fields.
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self._create_event_field({
            "field_name": "waitlist_position",
            "kind": const.FieldDatatypes.int,
            "association": const.FieldAssociations.registration,
        })  # id 1001
        self._create_event_field({
            "field_name": "wrong1",
            "kind": const.FieldDatatypes.str,
            "association": const.FieldAssociations.registration,
        })  # id 1002
        self._create_event_field({
            "field_name": "wrong2",
            "kind": const.FieldDatatypes.int,
            "association": const.FieldAssociations.course,
        })  # id 1003

        # Check that the incorrect fields do not work as the waitlist field.
        self.traverse("Veranstaltungsteile")
        self.traverse({"href": "/event/event/1/part/1/change"})
        f: webtest.Form = self.response.forms["changepartform"]
        self.assertEqual(
            [x[0] for x in f['waitlist_field_id'].options], ['', '8', '1001']
        )
        f['waitlist_field_id'].force_value(1002)
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'waitlist_field_id', "Wartelistenfeld muss vom Typ 'Zahl' sein."
        )
        f['waitlist_field_id'].force_value(1003)
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'waitlist_field_id', "Wartelistenfeld muss ein Anmeldungsfeld sein."
        )

        # Set the correct waitlist field.
        f['waitlist_field_id'] = '1001'
        self.submit(f)

        # Check log
        log_expectation = [
            {
                "code": const.EventLogCodes.field_added,
                "change_note": "waitlist_position",
            },
            {
                "code": const.EventLogCodes.field_added,
                "change_note": "wrong1",
            },
            {
                "code": const.EventLogCodes.field_added,
                "change_note": "wrong2",
            },
            {
                "code": const.EventLogCodes.part_changed,
                "change_note": "Warmup",
            },
        ]
        self.assertLogEqual(
            log_expectation, "event", event_id=1, offset=self.EVENT_LOG_OFFSET
        )

        # Check that the linked stat query applies the correct ordering.
        self.traverse('Statistik', {'linkid': 'part_waitlist_1'})
        f = self.response.forms['queryform']
        self.assertEqual(f['qord_0'].value, "reg_fields.xfield_waitlist_position")
        self.assertEqual(f['qop_part1.status'].value, str(QueryOperators.equal.value))
        self.assertEqual(
            f['qval_part1.status'].value,
            str(const.RegistrationPartStati.waitlist.value),
        )
        self.assertPresence("Emilia", div="result-container")

        # Check that participants can see their waitlist position.
        self.logout()
        self.login(USER_DICT["emilia"])
        self.traverse({'href': "/event/event/1/registration/status"})
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence(
            "Warteliste (Bezahlung ausstehend) (Platz 1)",
            exact=True,
            div="registration_status_part1",
        )

    @as_users('emilia')
    def test_participant_list(self) -> None:
        # first, check non-visibility for all participants
        def _check_invisible() -> None:
            self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'})
            self.get('/event/event/1/registration/list')
            self.assertTitle("Große Testakademie 2222")
            self.assertPresence(
                "Fehler! Die Teilnehmerliste ist noch nicht veröffentlicht.",
                div='notifications',
            )

        _check_invisible()

        # check non-visibility for event helper
        with self.switch_user('petra'):
            _check_invisible()

        # now, check visibility for orgas
        with self.switch_user('garcia'):
            self.traverse(
                {'href': '/event/$'},
                {'href': '/event/event/1/show'},
                {'href': 'event/event/1/registration/list'},
            )
            self.assertTitle("Teilnehmerliste Große Testakademie 2222")
            self.assertPresence(
                "Die Teilnehmerliste ist aktuell nur für Orgas und Admins sichtbar.",
                div='static-notifications',
            )
            self.assertPresence("Übersicht")
            self.assertPresence("Administrator")
            self.assertPresence("emilia@example.cde")
            self.assertPresence("Emilia (Emmy)")
            self.assertPresence("03205 Musterstadt")
            self.assertNonPresence("Inga")
            self.assertPresence("Veranstaltungsteile")
            self.assertNonPresence("Kurs")

            self.traverse({'href': r'event/event/1/registration/list\?part_id=1'})
            self.assertPresence("Es gibt in Summe 3 Teilnehmer.")
            self.assertNonPresence("Garcia")
            self.assertNonPresence("Kurs")
            self.assertNonPresence("Veranstaltungsteile")

            self.traverse({'href': '/event/event/1/change'})
            self.assertTitle("Große Testakademie 2222 – Konfiguration")
            f = self.response.forms['changeeventform']
            f['is_course_assignment_visible'].checked = True
            self.submit(f)

            self.traverse({'href': 'event/event/1/registration/list'})
            self.assertTitle("Teilnehmerliste Große Testakademie 2222")
            self.assertPresence("Veranstaltungsteile")
            self.assertNonPresence("Kurs")
            self.traverse({'href': r'event/event/1/registration/list\?part_id=1'})
            self.assertNonPresence("Veranstaltungsteile")
            self.assertNonPresence("Kurs")
            self.traverse({'href': r'event/event/1/registration/list\?part_id=2'})
            self.assertNonPresence("Veranstaltungsteile")
            self.assertPresence("Kurse")
            self.traverse({'href': r'event/event/1/registration/list\?part_id=3'})
            self.assertNonPresence("Veranstaltungsteile")
            self.assertPresence("Kurs")
            self.assertNonPresence("Kurse")
            self.assertPresence("α. Heldentum")

            # now, make participant list visible to participants
            self.traverse({'href': '/event/event/1/change'})
            self.assertTitle("Große Testakademie 2222 – Konfiguration")
            f = self.response.forms['changeeventform']
            f['is_participant_list_visible'].checked = True
            self.submit(f)

        def _check_visible() -> None:
            self.traverse(
                {'href': '/event/$'},
                {'href': '/event/event/1/show'},
                {'href': '/event/event/1/registration/list'},
            )
            self.assertTitle("Teilnehmerliste Große Testakademie 2222")
            self.assertNonPresence(
                "Die Teilnehmerliste ist aktuell nur für Orgas und Admins sichtbar.",
                div='static-notifications',
            )
            self.assertPresence("Warmup")
            self.assertPresence("Zweite Hälfte")
            self.traverse({'description': 'Zweite Hälfte'})
            self.assertPresence("α. Heldentum (KL)")

        # check visibility for participant with list consent
        _check_visible()

        # check visibility for event helper
        with self.switch_user('petra'):
            _check_visible()

        # check non-visibility for participant without list consent
        with self.switch_user('inga'):
            self.traverse(
                {'href': '/event/$'},
                {'href': '/event/event/1/show'},
                {'href': '/event/event/1/registration/list'},
            )
            self.assertTitle("Teilnehmerliste Große Testakademie 2222")
            self.assertPresence(
                "Du kannst die Teilnehmerliste nicht sehen, da du "
                "nicht zugestimmt hast, deine Daten auf der "
                "Teilnehmerliste zur Verfügung zu stellen."
            )
            self.assertNonPresence("Übersicht")
            self.assertNonPresence("Zweite Hälfte")
            self.assertNonPresence("Anton")
            self.assertNonPresence("Stadt, Postleitzahl")

        # check for correct participant count and visibility of tab navigation (#2748)
        self.traverse(
            "Veranstaltungen", "TripelAkademie", "Anmeldungen", "Anmeldung hinzufügen"
        )  # Emmy is Orga
        f = self.response.forms['addregistrationform']
        f["persona.persona_id"] = "DB-2-7"  # Berta
        f["part6.status"] = const.RegistrationPartStati.participant  # Oberwesel H1
        f["part7.status"] = const.RegistrationPartStati.not_applied
        f["part8.status"] = const.RegistrationPartStati.not_applied
        f["part9.status"] = const.RegistrationPartStati.not_applied
        f["part10.status"] = const.RegistrationPartStati.participant  # Windischleuba H2
        f["part11.status"] = const.RegistrationPartStati.not_applied
        f["part12.status"] = const.RegistrationPartStati.guest  # Silvesterfeier
        f["reg.list_consent"].checked = True
        self.submit(f)

        self.traverse("Teilnehmerliste")
        # Emmy has not given list_consent, check she is counted anyway
        self.assertPresence("berta@example.cde")
        self.assertNonPresence("emilia@example.cde")
        self.assertPresence("Es gibt in Summe 2 Teilnehmer.")

        self.traverse("Silvesterfeier")
        # Berta is only guest - neither counted nor listed
        self.assertPresence("Es gibt in Summe 1 Teilnehmer.")
        self.assertNonPresence("Vorname")

        self.traverse("1. Hälfte Windischleuba")
        self.assertNonPresence("Vorname")
        self.assertPresence("Bisher gibt es keine Teilnehmer.")

        self.traverse("1. Hälfte Oberwesel")
        self.assertPresence("berta@example.cde")
        self.assertPresence("Es gibt in Summe 1 Teilnehmer.")

        self.traverse("1. Hälfte Kaub")
        self.assertNonPresence("Vorname")
        self.assertPresence("Es gibt in Summe 1 Teilnehmer.")

    @as_users("berta")
    def test_participant_list_event_with_one_part(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/2/show'},
            {'href': '/event/event/2/registration/list'},
        )
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Bisher gibt es keine Teilnehmer.")

        # add a registration
        self.traverse(
            {'href': '/event/event/2/registration/query'},
            {'href': '/event/event/2/registration/add'},
        )
        self.assertTitle("Neue Anmeldung (CdE-Party 2050)")
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-1-9"
        f['reg.list_consent'] = True
        self.submit(f)

        # now test participant list
        self.traverse({'href': 'event/event/2/registration/list'})
        self.assertPresence("Rufname")
        self.assertPresence("E-Mail-Adresse")
        self.assertNonPresence("Veranstaltungsteile")
        self.assertNonPresence("Übersicht")
        self.assertNonPresence("Party")

        # at last, test url magic
        self.get('/event/event/2/registration/list?part_id=5000', status=404)
        self.get('/event/event/2/registration/list?part_id=3', status=404)

    def _sort_appearance(self, userlist: Sequence[UserObject]) -> None:
        row = 1
        for user in userlist:
            self.assertPresence(user['family_name'], div="row-" + str(row))
            row += 1

    @prepsql(
        f"UPDATE core.personas SET country = 'CH'"
        f" WHERE id = {USER_DICT['berta']['id']};"
        f"UPDATE core.personas SET postal_code = '01234'"
        f" WHERE id = {USER_DICT['akira']['id']};"
    )
    @as_users("garcia")
    def test_participant_list_sorting(self) -> None:
        # first, show courses on participant list
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Konfiguration'},
        )
        f = self.response.forms['changeeventform']
        f['is_course_assignment_visible'].checked = True
        self.submit(f)

        # now, check the sorting
        self.traverse({'description': 'Teilnehmerliste'})
        self.assertTitle("Teilnehmerliste Große Testakademie 2222")
        akira = USER_DICT['akira']
        anton = USER_DICT['anton']
        berta = USER_DICT['berta']
        emilia = USER_DICT['emilia']

        # default sort is by given names
        self._sort_appearance([akira, anton, berta, emilia])
        # explicit sort by given names, ascending
        self.traverse({'description': r"\sRufname$"})
        self._sort_appearance([akira, anton, berta, emilia])
        # explicit sort by given names, descending
        self.traverse({'description': r"\sRufname$"})
        self._sort_appearance([emilia, berta, anton, akira])
        # ... and again, ascending
        self.traverse({'description': r"\sRufname$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sFamilienname$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sE-Mail-Adresse$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sPostleitzahl, Stadt$"})
        self._sort_appearance([anton, emilia, akira, berta])

        self.traverse({'description': r"^Zweite Hälfte$"})
        self.traverse({'description': r"\sRufname"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sFamilienname$"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sE-Mail-Adresse$"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sPostleitzahl, Stadt$"})
        self._sort_appearance([anton, emilia, akira])
        self.traverse({'description': r"\sKurs$"})
        self._sort_appearance([anton, akira, emilia])

    @as_users("emilia", "garcia", maintain_data=True)
    def test_participant_list_profile_link(self) -> None:
        # first, show list for participants
        if self.user_in('emilia'):
            self.logout()
            self.login(USER_DICT['garcia'])
            self.traverse(
                {'description': 'Veranstaltungen'},
                {'description': 'Große Testakademie 2222'},
                {'description': 'Konfiguration'},
            )
            f = self.response.forms['changeeventform']
            f['is_participant_list_visible'].checked = True
            self.submit(f)
            self.logout()
            self.login(USER_DICT['emilia'])

        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Teilnehmerliste'},
        )
        # emilia is no member and therefore must not be linked
        self.assertNoLink(content='Eventis')
        # akira is member and searchable, so there should be a link
        self.traverse({'description': 'Akira'})
        if self.user_in('emilia'):
            # this must be a reduced profile, since emilia is not a member
            self.assertPresence("Akira Abukara", div='personal-information')
            self.assertNonPresence("akira@example.cde")
        else:
            # this is an expanded profile, since garcia is not searchable but
            # orga of this event
            self.assertPresence("akira@example.cde", div='contact-email')

    @as_users("berta", "emilia")
    def test_lodgement_wish_detection(self) -> None:
        with self.switch_user("garcia"):
            self.event.set_event(
                self.key,
                1,
                {
                    'is_participant_list_visible': True,
                    'use_additional_questionnaire': True,
                },
            )
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Fragebogen")
        f = self.response.forms['questionnaireform']
        f['fields.lodge'] = ""
        self.submit(f)
        self.assertPresence(
            "Du kannst Zimmerwünsche im entsprechenden Fragebogenfeld",
            div="lodgement-wishes",
        )
        self.assertNonPresence(
            "Folgende Unterbringungswünsche wurden aus Deiner Eingabe erkannt.",
            div="lodgement-wishes",
        )
        self.assertPresence(
            "Erkannte Unterbringungswünsche werden hier angezeigt",
            div="lodgement-wishes",
        )
        self.assertPresence("Falls ein Wunsch fehlen sollte", div="lodgement-wishes")
        f['fields.lodge'] = """
            Armin Administrator, garcia@example.cde, DB-100-7, Daniel Dino, Emmy
        """
        self.submit(f)
        self.assertPresence("Folgende Unterbringungswünsche", div="lodgement-wishes")
        self.assertNonPresence("Anton Administrator", div="lodgement-wishes-list")
        self.assertNonPresence("Garcia", div="lodgement-wishes-list")
        self.assertNonPresence("Emilia", div="lodgement-wishes-list")
        self.assertPresence("Akira Abukara", div="lodgement-wishes-list")
        self.assertNonPresence("Daniel", div="lodgement-wishes-list")
        with self.switch_user("garcia"):
            reg_id = unwrap(
                self.event.list_registrations(
                    self.key, event_id=1, persona_id=self.user['id']
                ).keys()
            )
            self.event.set_registration(self.key, {'id': reg_id, 'list_consent': True})
        execsql("UPDATE core.personas SET show_legal_given_names = True WHERE id = 1;")
        execsql("UPDATE core.personas SET nickname = 'Akky' WHERE id = 100;")
        self.submit(f)
        self.assertPresence("Anton Administrator", div="lodgement-wishes-list")
        self.assertPresence("Akira (Akky) Abukara", div="lodgement-wishes-list")
        self.assertPresence("Garcia Generalis", div="lodgement-wishes-list")

    @as_users("annika", "garcia")
    def test_cancellation(self) -> None:
        self.traverse({'href': '/event/$'})
        self.assertNonPresence("abgesagt")
        if self.user_in("garcia"):
            self.traverse({'href': '/event/event/list'})
            self.assertPresence("(3 Teile)")
            self.assertNonPresence("abgesagt")

        self.traverse({'href': '/event/event/1/show'})
        self.assertNonPresence("abgesagt", div="notifications")
        self.assertNonPresence("abgesagt", div="static-notifications")

        self.traverse({'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['is_cancelled'].checked = True
        self.submit(f)

        self.traverse({'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence(
            "Diese Veranstaltung wurde abgesagt.", div="static-notifications"
        )
        self.traverse({'href': '/event/event/1/course/list'})
        self.assertPresence(
            "Diese Veranstaltung wurde abgesagt.", div="static-notifications"
        )

        if self.user_in("annika"):
            # Make sure the index shows it as cancelled.
            # Orgas only see it as Organized event now.
            self.traverse({'href': '/event'})
            self.assertPresence("02.02.2222 – 30.11.2222, wurde abgesagt.")

            # Make sure the management page shows it as cancelled
            self.traverse({'href': '/event/event/list'})
            self.assertPresence("(3 Teile, wurde abgesagt)")

    @as_users("farin")
    @prepsql("UPDATE core.personas SET is_event_admin = False WHERE id = 32;")
    def test_batch_fee(self) -> None:
        # TODO Finance admin can not access Teilnahmebeiträge due to lacking permissions
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Teilnahmebeiträge",
            "Überweisungen eintragen",
        )
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['transfers'] = """
01.04.18;353.99;DB-1-9;Administrator;Anton
02.04.18;455.99;DB-5-1;Eventis;Emilia
03.04.18;999.99;DB-100-7;Abukara;Akira
04.04.18;570.99;DB-11-6;Karabatschi;Kalif
77.04.18;0.0;DB-666-1;Y;Z
30.12.19;-116.49;DB-9-4;Iota;Inga
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld. 455,99 € < 466,49 €", div="line1_infos")
        self.assertPresence("Zu viel Geld. 999,99 € > 584,48 €", div="line2_infos")
        self.assertPresence(
            "Benutzer ist nicht für diese Veranstaltung angemeldet.",
            div="line3_problems",
        )
        self.assertPresence("Ungültige Eingabe für ein Datum.", div="line4_problems")
        self.assertPresence("Kein Account mit ID 666 gefunden.", div="line4_problems")
        self.assertPresence("amount: Darf nicht null sein.", div="line4_problems")
        f = self.response.forms['batchfeesform']
        f['transfers'] = """
01.04.18;353.99;DB-1-9;Administrator;Anton
02.04.18;455.99;DB-5-1;Eventis;Emilia
03.04.18;999.99;DB-100-7;Abukara;Akira
30.12.19;-116.49;DB-9-4;Iota;Inga
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld. 455,99 € < 466,49 €", div="line1_infos")
        self.assertPresence("Zu viel Geld. 999,99 € > 584,48 €", div="line2_infos")
        f = self.response.forms['batchfeesform']
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld. 455,99 € < 466,49 €", div="line1_infos")
        self.assertPresence("Zu viel Geld. 999,99 € > 584,48 €", div="line2_infos")
        f = self.response.forms['batchfeesform']
        self.submit(f)
        for i in range(6):
            text = self.fetch_mail_content(i)
            if i == 1:
                self.assertIn("455,99", text)
            if i == 3:
                self.assertRegex(
                    text,
                    r"Für Eure Veranstaltung\s+Große Testakademie 2222\s+"
                    r"wurden 3 neue Überweisungen in der Datenbank eingetragen.",
                )
            elif i == 4:
                self.assertRegex(
                    text,
                    r"Für die Veranstaltung\s+Große Testakademie 2222\s+"
                    r"haben wir dir am 30.12.2019 eine Erstattung in Höhe von\s+"
                    r"116,49\s€\s+überwiesen",
                )
            elif i == 5:
                self.assertRegex(
                    text,
                    r"Für Eure Veranstaltung\s+Große Testakademie 2222\s+"
                    r"wurden 1 Erstattungen durchgeführt\s+"
                    r"und in der Datenbank eingetragen.",
                )
            else:
                self.assertIn(
                    "Deine Überweisung für die Veranstaltung",
                    text,
                )
                self.assertIn(
                    "Große Testakademie 2222",
                    text,
                )
        self.logout()

        # Now, test the results. To do so, switch to Garcia (Orga of this event)
        self.login("garcia")
        self.get('/event/event/1/registration/1/show')
        self.assertTitle("Anmeldung von Anton Administrator (Große Testakademie 2222)")
        # Previous payment date was kept.
        self.assertPresence("Bezahlt am 01.01.2014", div="payment-date", exact=True)
        self.assertPresence("553,99 €", div="amount-paid", exact=True)

        self.get('/event/event/1/registration/2/show')
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 02.04.2018", div="payment-date", exact=True)
        self.assertPresence("455,99 €", div="amount-paid", exact=True)

        self.get('/event/event/1/registration/4/show')
        self.assertTitle("Anmeldung von Inga Iota (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 04.04.2014", div="payment-date", exact=True)
        self.assertPresence("431,99 €", div="amount-paid", exact=True)

        self.get('/event/event/1/registration/5/show')
        self.assertTitle("Anmeldung von Akira Abukara (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 03.04.2018", div="payment-date")
        self.assertPresence("999,99 €", div="amount-paid", exact=True)
        self.assertPresence("-415,51 €", div="remaining-owed", exact=True)
        # Check log
        log_expectation = [
            {
                'persona_id': 1,
                'code': const.EventLogCodes.registration_payment_received_orga,
                'change_note': "353,99 € am 01.04.2018 gezahlt.",
                'submitted_by': 32,
            },
            {
                'persona_id': 5,
                'code': const.EventLogCodes.registration_payment_received_orga,
                'change_note': "455,99 € am 02.04.2018 gezahlt.",
                'submitted_by': 32,
            },
            {
                'persona_id': 100,
                'code': const.EventLogCodes.registration_payment_received_orga,
                'change_note': "999,99 € am 03.04.2018 gezahlt.",
                'submitted_by': 32,
            },
            {
                'persona_id': 9,
                'code': const.EventLogCodes.registration_payment_reimbursed_orga,
                'change_note': "116,49 € am 30.12.2019 zurückerstattet.",
                'submitted_by': 32,
            },
        ]
        self.assertLogEqual(
            log_expectation, 'event', event_id=1, offset=self.EVENT_LOG_OFFSET
        )

    @as_users("farin")
    @prepsql("UPDATE core.personas SET is_event_admin = False WHERE id = 32;")
    def test_batch_fee_regex(self) -> None:
        self.get('/event/event/1/batchfees')
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['transfers'] = "01.04.18;666.66;DB-1-9;Fiese[;Zeichen{;überall("
        self.submit(f, check_notification=False)
        # Here the active regex chars where successfully neutralised

    @as_users("farin")
    @prepsql("UPDATE core.personas SET is_event_admin = False WHERE id = 32;")
    def test_batch_fee_duplicate(self) -> None:
        self.get('/event/event/1/batchfees')
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['transfers'] = """
01.04.18;466.49;DB-5-1;Eventis;Emilia
02.04.18;466.49;DB-5-1;Eventis;Emilia
"""
        self.submit(f, check_notification=False)
        self.assertNonPresence("Zu viel Geld.", div="line0_infos", check_div=False)
        self.assertPresence(
            "Mehrere Überweisungen für diesen Account", div="line1_infos"
        )
        self.assertPresence("Zu viel Geld.", div="line1_infos")

        f['transfers'] = """
01.04.18;400;DB-5-1;Eventis;Emilia
02.04.18;66.49;DB-5-1;Eventis;Emilia
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld.", div="line0_infos")
        self.assertNonPresence("Zu viel Geld.", div="line1_infos")
        self.assertPresence(
            "Mehrere Überweisungen für diesen Account", div="line1_infos"
        )

    @as_users("farin")
    @prepsql(
        "UPDATE core.personas SET is_event_admin = False WHERE id = 32;"
        "UPDATE event.registrations SET payment = NULL;"
    )
    def test_batch_fee_twice(self) -> None:
        self.get('/event/event/1/batchfees')
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['send_notifications'].checked = True
        f['transfers'] = """01.04.18;266.49;DB-5-1;Eventis;Emilia"""
        self.submit(f, check_notification=False)
        # submit again because of checksum
        self.assertPresence("Bestätigen")
        f = self.response.forms['batchfeesform']
        self.submit(f)
        for i in range(1):
            text = self.fetch_mail_content(i)
            self.assertIn("Überweisung für die Veranstaltung", text)
            self.assertIn("Große Testakademie 2222", text)

        with self.switch_user("garcia"):
            self.traverse(
                "Veranstaltungen",
                "Große Testakademie 2222",
                "Anmeldungen",
                "Alle Anmeldungen",
                {'href': '/event/event/1/registration/2/show'},
            )
            self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
            self.assertPresence("Bezahlt am 01.04.2018")
            self.assertPresence("Bereits Bezahlt 266,49 €")

        self.get('/event/event/1/batchfees')
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['send_notifications'].checked = True
        f['transfers'] = """02.04.18;200.00;DB-5-1;Eventis;Emilia"""
        self.submit(f, check_notification=False)
        # submit again because of checksum
        f = self.response.forms['batchfeesform']
        self.submit(f)
        for i in range(1):
            text = self.fetch_mail_content(i)
            self.assertIn("Überweisung für die Veranstaltung", text)
            self.assertIn("Große Testakademie 2222", text)
        self.logout()

        # Now, test the results. To do so, switch to Garcia (Orga of this event)
        self.login("garcia")
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
            {'href': '/event/event/1/registration/2/show'},
        )
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
        self.assertNonPresence("Bezahlt am 02.04.2018")
        self.assertPresence("Bezahlt am 01.04.2018")
        self.assertPresence("Bereits Bezahlt 466,49 €")
        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "266,49 € am 01.04.2018 gezahlt.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "200,00 € am 02.04.2018 gezahlt.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    @event_keeper
    @as_users("garcia")
    def test_registration_query(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
        )
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_persona.family_name'] = QueryOperators.match.value
        f['qval_persona.family_name'] = 'e'
        f['qord_0'] = 'reg.id'
        self.submit(f)
        self.assertTitle("\nAnmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [3]")
        self.assertPresence("Beispiel")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Deutschland", div="query-result")
        self.assertNonPresence("DE", div="query-result")
        self.assertEqual(
            "Einzelzelle",
            self.response.lxml.xpath(
                '//*[@id="query-result"]//tr[1]/td[@data-col="lodgement2.title"]'
            )[0].text.strip(),
        )
        self.assertEqual(
            "",
            self.response.lxml.xpath(
                '//*[@id="query-result"]//tr[2]/td[@data-col="lodgement2.title"]'
            )[0].text.strip(),
        )
        f["query_name"] = query_name = "My registration query"
        self.submit(f, button="store_query", check_button_attrs=True)
        self.assertPresence("Ergebnis [3]")
        self.assertPresence("Beispiel")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence(query_name, div="default_queries_container")
        self.traverse("Anmeldungen", query_name)
        self.assertPresence("Ergebnis [3]")
        self.assertPresence("Beispiel")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.submit(
            f, button="store_query", check_notification=False, check_button_attrs=True
        )
        self.assertPresence(
            f"Suchabfrage mit dem Namen '{query_name}' existiert bereits"
            f" für diese Veranstaltung.",
            div="notifications",
        )
        f = self.response.forms["deletequeryform1001"]
        self.submit(f)
        self.assertNonPresence(query_name, div="default_queries_container")

        # Store query using the 'anzahl_GROSSBUUCHSTABEN' field.
        self.traverse("Anmeldungen")
        f = self.response.forms["queryform"]
        f["qsel_reg.id"].checked = True
        f["qsel_persona.given_names"] = False
        f["qsel_persona.family_name"] = False
        f["qsel_persona.username"] = False
        f["qsel_reg_fields.xfield_anzahl_GROSSBUCHSTABEN"].checked = True
        f["qop_reg_fields.xfield_anzahl_GROSSBUCHSTABEN"] = (
            QueryOperators.nonempty.value
        )
        f["qord_0"] = "reg_fields.xfield_anzahl_GROSSBUCHSTABEN"
        f["query_name"] = "Großbuchstaben"
        self.submit(f, button="store_query", check_button_attrs=True)
        self.assertPresence("Anzahl Großbuchstaben", div="query-result")

        # Delete that field.
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms["fieldsummaryform"]
        f["delete_8"].checked = True
        self.submit(f)

        self.traverse("Anmeldungen", "Großbuchstaben")
        self.assertNonPresence("Anzahl Großbuchstaben", div="query-result")

        # Add the field again.
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms["fieldsummaryform"]
        f["create_-1"].checked = True
        f["field_name_-1"] = "anzahl_GROSSBUCHSTABEN"
        f["association_-1"] = const.FieldAssociations.registration
        f["kind_-1"] = const.FieldDatatypes.int
        self.submit(f)

        self.traverse("Anmeldungen", "Großbuchstaben")
        # Remove the old constraint, because all field data is now empty.
        f = self.response.forms["queryform"]
        f["qop_reg_fields.xfield_anzahl_GROSSBUCHSTABEN"] = ""
        self.submit(f)
        # The field has been deleted, hence the title is no longer known.
        self.assertPresence("anzahl_GROSSBUCHSTABEN", div="query-result")

        # Regression test for https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues/3342
        self.traverse("Anmeldungen")
        f = self.response.forms["queryform"]
        f["qord_0"] = 'course1.id'
        self.submit(f)

        # Test for https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues/3937.
        self.event.set_registration(
            self.key, {'id': 1, 'parts': {3: {'lodgement_id': 3}}}
        )
        self.traverse("Anmeldungen")
        f = self.response.forms["queryform"]
        f["qsel_part3.lodgement_id"] = True
        f["qsel_lodgement3.id"] = True
        f["qord_0"] = "part3.lodgement_id"
        self.submit(f, button="download", value="json")
        data = json.loads(self.response.text)
        self.assertEqual(
            [
                "Einzelzelle",
                "Kalte Kammer",
                "Kalte Kammer",
                "Kellerverlies",
                "Warme Stube",
                None,
            ],
            [entry["part3.lodgement_id"] for entry in data],
        )
        self.assertEqual(
            [4, 2, 2, 3, 1, 0],
            [int(entry["lodgement3.id"] or 0) for entry in data],
        )

    @as_users("annika")
    def test_course_query(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Kurse'},
            {'description': 'Kurssuche'},
        )
        self.assertTitle('Kurssuche (Große Testakademie 2222)')
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_track3.takes_place'] = QueryOperators.equal.value
        f['qval_track3.takes_place'] = True
        f['qop_track3.num_choices1'] = QueryOperators.greaterequal.value
        f['qval_track3.num_choices1'] = 2
        f['qord_0'] = 'track2.num_choices0'
        self.submit(f)
        self.assertTitle('Kurssuche (Große Testakademie 2222)')
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Lang", div="result-container")
        self.assertPresence("Seminarraum 23", div="result-container")
        self.assertPresence("Kabarett", div="result-container")
        self.assertPresence("Theater", div="result-container")
        f["query_name"] = query_name = "custom_course_query"
        self.submit(f, button="store_query", check_button_attrs=True)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Lang", div="result-container")
        self.assertPresence("Seminarraum 23", div="result-container")
        self.assertPresence("Kabarett", div="result-container")
        self.assertPresence("Theater", div="result-container")
        self.assertPresence(query_name, div="default_queries_container")
        self.traverse("Kurse", "Kurssuche", query_name)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Lang", div="result-container")
        self.assertPresence("Seminarraum 23", div="result-container")
        self.assertPresence("Kabarett", div="result-container")
        self.assertPresence("Theater", div="result-container")
        self.submit(
            f, button="store_query", check_notification=False, check_button_attrs=True
        )
        self.assertPresence(
            f"Suchabfrage mit dem Namen '{query_name}' existiert bereits für"
            f" diese Veranstaltung.",
            div="notifications",
        )
        f = self.response.forms["deletequeryform1001"]
        self.submit(f)
        self.assertNonPresence(query_name, div="default_queries_container")

    @as_users("garcia")
    def test_lodgement_query(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Unterkünfte'},
            {'description': 'Unterkunftssuche'},
        )
        self.assertTitle('Unterkunftssuche (Große Testakademie 2222)')
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_part3.total_inhabitants'] = QueryOperators.greater.value
        f['qval_part3.total_inhabitants'] = 1
        f['qord_0'] = 'lodgement_group.title'
        self.submit(f)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Kalte Kammer", div="result-container")
        self.assertPresence("Warme Stube", div="result-container")
        f["query_name"] = query_name = "My lodgement query with a funny symbol: 🏠"
        self.submit(f, button="store_query", check_button_attrs=True)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Kalte Kammer", div="result-container")
        self.assertPresence("Warme Stube", div="result-container")
        self.assertPresence(query_name, div="default_queries_container")
        self.traverse("Unterkünfte", "Unterkunftssuche", query_name)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Kalte Kammer", div="result-container")
        self.assertPresence("Warme Stube", div="result-container")
        self.submit(
            f, button="store_query", check_notification=False, check_button_attrs=True
        )
        self.assertPresence(
            f"Suchabfrage mit dem Namen '{query_name}' existiert bereits"
            f" für diese Veranstaltung.",
            div="notifications",
        )
        f = self.response.forms["deletequeryform1001"]
        self.submit(f)
        self.assertNonPresence(
            query_name, div="default_queries_container", check_div=False
        )

    @event_keeper
    @as_users("garcia")
    def test_multiedit(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Anmeldungen",
            "Alle Anmeldungen",
        )
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertNotEqual(
            self.response.lxml.xpath(
                '//table[@id="query-result"]/tbody/tr[@data-id="2"]'
            ),
            [],
        )
        # Fake JS link redirection
        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationsform']
        self.assertFalse(f['enable_part2.status'].checked)
        self.assertTrue(f['enable_part3.status'].checked)
        self.assertEqual(
            str(const.RegistrationPartStati.participant), f['part3.status'].value
        )
        f['part3.status'] = const.RegistrationPartStati.cancelled
        self.assertFalse(f['enable_fields.transportation'].checked)
        self.assertTrue(f['enable_fields.may_reserve'].checked)
        f['enable_fields.transportation'].checked = True
        f['fields.transportation'] = "pedes"
        f['fields.may_reserve'] = True
        f['enable_fields.anzahl_GROSSBUCHSTABEN'] = False
        f['fields.anzahl_GROSSBUCHSTABEN'] = 1024
        self.submit(f)

        log_expectation = [
            {
                'persona_id': 5,
                'code': const.EventLogCodes.registration_status_changed,
                'change_note': "2.H.: Teilnehmer -> Abgemeldet",
            },
            {
                'persona_id': 5,
                'code': const.EventLogCodes.registration_changed,
                'change_note': "Multi-Edit.",
            },
            {
                'persona_id': 7,
                'code': const.EventLogCodes.registration_status_changed,
                'change_note': "2.H.: Teilnehmer -> Abgemeldet",
            },
            {
                'persona_id': 7,
                'code': const.EventLogCodes.registration_changed,
                'change_note': "Multi-Edit.",
            },
        ]

        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        f = self.response.forms['changeregistrationsform']
        self.assertTrue(f['enable_fields.transportation'].checked)
        self.assertTrue(f['enable_fields.may_reserve'].checked)
        self.assertEqual("pedes", f['fields.transportation'].value)
        self.assertTrue(f['fields.may_reserve'].checked)
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        self.assertEqual(
            str(const.RegistrationPartStati.guest), f['part2.status'].value
        )
        self.assertEqual(
            str(const.RegistrationPartStati.cancelled), f['part3.status'].value
        )
        self.assertEqual("pedes", f['fields.transportation'].value)
        self.assertEqual("3", f["fields.anzahl_GROSSBUCHSTABEN"].value)
        self.get('/event/event/1/registration/3/change')
        f = self.response.forms['changeregistrationform']
        self.assertEqual(
            str(const.RegistrationPartStati.participant), f['part2.status'].value
        )
        self.assertEqual(
            str(const.RegistrationPartStati.cancelled), f['part3.status'].value
        )
        self.assertEqual("pedes", f['fields.transportation'].value)
        self.assertEqual("3", f["fields.anzahl_GROSSBUCHSTABEN"].value)

        # Now, check with change_note
        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationsform']
        f['fields.transportation'] = "etc"
        f['change_note'] = "Muss doch nicht laufen."
        self.submit(f)

        log_expectation.extend([
            {
                'persona_id': 5,
                'code': const.EventLogCodes.registration_changed,
                'change_note': "Multi-Edit: Muss doch nicht laufen.",
            },
            {
                'persona_id': 7,
                'code': const.EventLogCodes.registration_changed,
                'change_note': "Multi-Edit: Muss doch nicht laufen.",
            },
        ])

        # Check log
        self.assertLogEqual(
            log_expectation, realm="event", event_id=1, offset=self.EVENT_LOG_OFFSET
        )

        # Now check that not selecting the enable does not reset or change the field.
        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationsform']
        f['enable_fields.transportation'] = False
        f['fields.transportation'] = "pedes"
        self.submit(f)
        self.get('/event/event/1/registration/3/change')
        f = self.response.forms['changeregistrationform']
        self.assertEqual("etc", f['fields.transportation'].value)

    @event_keeper
    @as_users("garcia")
    def test_multiedit_course_instructors(self) -> None:
        event_id = 3
        event = self.event.get_event(self.key, event_id)
        track_id = unwrap(event.tracks.keys())
        course_id = 8
        registration_id = 7
        regisration2_id = 8
        # Disable course choices
        edata = {
            'parts': {
                event.tracks[track_id].part_id: {
                    'tracks': {
                        track_id: {
                            'num_choices': 0,
                            'min_choices': 0,
                        },
                    },
                },
            },
        }
        self.event.set_event(self.key, event_id, edata)
        # Make Daniel a course instructor.
        rdata = {
            'id': registration_id,
            'tracks': {
                track_id: {
                    'course_instructor': course_id,
                },
            },
        }
        self.event.set_registration(self.key, rdata)
        # Multiedit doesn't work without JS.
        self.get(
            f'/event/event/{event_id}/registration/multiedit?'
            f'reg_ids={registration_id},{regisration2_id}'
        )
        f = self.response.forms['changeregistrationsform']
        self.submit(f)

    @as_users("garcia")
    def test_show_registration(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
        )
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse(
            {'description': 'Alle Anmeldungen'},
            {'href': '/event/event/1/registration/2/show'},
        )
        self.assertTitle("\nAnmeldung von Emilia Eventis (Große Testakademie 2222)\n")
        self.assertPresence("56767 Wolkenkuckuksheim")
        self.assertPresence("Einzelzelle")
        self.assertPresence("α. Heldentum")
        self.assertPresence("Extrawünsche: Meerblick, Weckdienst")
        self.assertPresence("Teilnahme\xadbeitrag 466,49 €")

    @event_keeper
    @as_users("garcia")
    def test_multiedit_wa1920(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        # Fake JS link redirection
        self.get("/event/event/1/registration/multiedit?reg_ids=1,2,3,4")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationsform']
        self.assertFalse(f['enable_track2.course_id'].checked)
        self.submit(f)
        self.traverse(
            {'description': 'Alle Anmeldungen'},
            {'href': '/event/event/1/registration/3/show'},
            {'href': '/event/event/1/registration/3/change'},
        )
        self.assertTitle(
            "Anmeldung von Garcia Generalis bearbeiten (Große Testakademie 2222)"
        )
        f = self.response.forms['changeregistrationform']
        self.assertEqual("2", f['track2.course_id'].value)

    @as_users("garcia")
    def test_change_registration(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Anmeldungen",
            "Alle Anmeldungen",
            {'href': '/event/event/1/registration/2/show'},
            "Bearbeiten",
        )
        self.assertTitle(
            "Anmeldung von Emilia Eventis bearbeiten (Große Testakademie 2222)"
        )
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Unbedingt in die Einzelzelle.", f['reg.orga_notes'].value)
        f['reg.orga_notes'] = "Wir wollen mal nicht so sein."
        self.assertTrue(f['reg.mixed_lodging'].checked)
        f['reg.mixed_lodging'].checked = False
        self.assertEqual(
            str(const.RegistrationPartStati.waitlist), f['part1.status'].value
        )
        f['part1.status'] = const.RegistrationPartStati.participant
        self.assertEqual("4", f['part2.lodgement_id'].value)
        f['part2.lodgement_id'] = 3
        self.assertEqual("2", f['track3.course_choice_1'].value)
        f['track3.course_choice_1'] = 5
        self.assertEqual("pedes", f['fields.transportation'].value)
        f['fields.transportation'] = "etc"
        self.assertEqual("015112345678", f['fields.lodge'].value)
        f['fields.lodge'] = "Om nom nom nom"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
        self.assertPresence("Om nom nom nom")
        self.traverse({'href': '/event/event/1/registration/2/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Wir wollen mal nicht so sein.", f['reg.orga_notes'].value)
        self.assertFalse(f['reg.mixed_lodging'].checked)
        self.assertEqual(
            str(const.RegistrationPartStati.participant), f['part1.status'].value
        )
        self.assertEqual("3", f['part2.lodgement_id'].value)
        self.assertEqual("5", f['track3.course_choice_1'].value)
        self.assertEqual("etc", f['fields.transportation'].value)
        self.assertEqual("Om nom nom nom", f['fields.lodge'].value)

    @as_users("garcia")
    def test_change_registration_with_note(self) -> None:
        self.get('/event/event/1/registration/2/change')
        self.assertTitle(
            "Anmeldung von Emilia Eventis bearbeiten (Große Testakademie 2222)"
        )
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Unbedingt in die Einzelzelle.", f['reg.orga_notes'].value)
        f['reg.orga_notes'] = "Wir wollen mal nicht so sein."
        f['change_note'] = "Orga-Notizen geändert."
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
        self.assertNonPresence("Orga-Notizen geändert")
        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Orga-Notizen geändert.", div=str(self.EVENT_LOG_OFFSET + 1) + "-1001"
        )

    @as_users("garcia")
    def test_add_registration(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Anmeldungen",
            "Anmeldung hinzufügen",
        )
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms['addregistrationform']
        # Try to add an archived user.
        f['persona.persona_id'] = "DB-8-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id', "Dieser Benutzer existiert nicht oder ist archiviert."
        )
        # Try to add a non-existent user.
        f['persona.persona_id'] = "DB-10000-5"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id', "Dieser Benutzer existiert nicht oder ist archiviert."
        )
        # Try to add a non-event user.
        f['persona.persona_id'] = "DB-11-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id', "Dieser Nutzer ist kein Veranstaltungsnutzer."
        )
        # Check invalid course choices
        f['track1.course_choice_0'] = 5
        f['track1.course_choice_1'] = 5
        f['track1.course_instructor'] = 5
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "track1.course_choice_0", "Geleiteter Kurs kann nicht gewählt werden."
        )
        self.assertValidationError(
            "track1.course_choice_1", "1. und 2. Kurswahl müssen unterschiedlich sein."
        )
        # Now add an actually valid user.
        f['persona.persona_id'] = USER_DICT['charly']['DB-ID']
        f['reg.orga_notes'] = "Du entkommst uns nicht."
        f['reg.mixed_lodging'].checked = False
        f['part1.status'] = const.RegistrationPartStati.applied
        f['part2.status'] = const.RegistrationPartStati.waitlist
        f['part3.status'] = const.RegistrationPartStati.not_applied
        f['part1.lodgement_id'] = 4
        f['track1.course_id'] = 5
        f['track1.course_choice_0'] = 5
        f['track1.course_choice_1'] = 4
        f['track1.course_instructor'] = 2
        f['fields.brings_balls'] = True
        self.submit(f)
        self.assertTitle("\nAnmeldung von Charly Clown (Große Testakademie 2222)\n")
        self.assertPresence("Du entkommst uns nicht.")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Du entkommst uns nicht.", f['reg.orga_notes'].value)
        self.assertFalse(f['reg.mixed_lodging'].checked)
        self.assertEqual(
            str(const.RegistrationPartStati.applied), f['part1.status'].value
        )
        self.assertEqual(
            str(const.RegistrationPartStati.waitlist), f['part2.status'].value
        )
        self.assertEqual(
            str(const.RegistrationPartStati.not_applied), f['part3.status'].value
        )
        self.assertEqual("4", f['part1.lodgement_id'].value)
        self.assertEqual("5", f['track1.course_id'].value)
        self.assertEqual("5", f['track1.course_choice_0'].value)
        self.assertEqual("4", f['track1.course_choice_1'].value)
        self.assertEqual("2", f['track1.course_instructor'].value)
        self.assertEqual(f['fields.brings_balls'].checked, True)

    @as_users("garcia")
    def test_add_illegal_registration(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Anmeldungen",
            "Anmeldung hinzufügen",
        )
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = USER_DICT['charly']['DB-ID']
        f["part1.status"] = const.RegistrationPartStati.applied
        f["track1.course_choice_0"] = 5
        f["track1.course_choice_1"] = 5
        self.submit(f, check_notification=False)
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        self.assertValidationError(
            'track1.course_choice_1', "1. und 2. Kurswahl müssen unterschiedlich sein."
        )
        f = self.response.forms["addregistrationform"]
        f["track1.course_choice_1"] = 4
        self.submit(f)
        self.assertTitle("\nAnmeldung von Charly Clown (Große Testakademie 2222)\n")
        self.assertEqual("5", f['track1.course_choice_0'].value)
        self.assertEqual("4", f['track1.course_choice_1'].value)

    @as_users("emilia")
    def test_add_empty_registration(self) -> None:
        self.assertTitle("CdE-Datenbank")
        self.assertNonPresence("CdE-Party 2050")
        self.traverse("Veranstaltungen")
        self.assertNonPresence("CdE-Party 2050")
        self.assertNonPresence("Veranstaltung versteckt")
        self.get('/event/event/2/show', status=403)
        self.assertTitle('403: Forbidden')
        with self.switch_user("berta"):
            self.traverse(
                "Veranstaltungen",
                "CdE-Party 2050",
                "Anmeldungen",
                "Anmeldung hinzufügen",
            )
            f = self.response.forms['addregistrationform']
            f['persona.persona_id'] = "DB-5-1"
            f['reg.parental_agreement'].checked = True
            f['part4.status'] = const.RegistrationPartStati.not_applied
            self.submit(f)
            self.assertTitle("Anmeldung von Emilia Eventis (CdE-Party 2050)")
            with self.switch_user("emilia"):
                self.assertTitle("CdE-Datenbank")
                self.assertNonPresence("CdE-Party 2050")
            self.traverse({'description': 'Bearbeiten'})
            f = self.response.forms['changeregistrationform']
            self.assertTrue(f['reg.parental_agreement'].checked)
            f['part4.status'] = const.RegistrationPartStati.applied
            self.submit(f)
        self.get('/')
        self.assertTitle("CdE-Datenbank")
        self.assertPresence("CdE-Party 2050", div="event-box")
        self.traverse("Veranstaltungen")
        self.assertPresence("CdE-Party 2050", div="current-events")
        self.assertPresence("Veranstaltung versteckt", div="current-events")
        self.traverse("CdE-Party 2050")
        self.assertPresence("have a party", div="description")
        self.assertPresence("Übersicht", div="sidebar-navigation")

    @event_keeper
    @as_users("garcia")
    def test_delete_registration(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        self.assertPresence("Anton")
        self.traverse({'href': '/event/event/1/registration/1/show'})
        self.assertTitle("Anmeldung von Anton Administrator (Große Testakademie 2222)")
        f = self.response.forms['deleteregistrationform']
        f['ack_delete'].checked = True
        with self.assertRaises(ValueError):
            self.submit(f)
        self.traverse(
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        self.assertPresence("Anton")
        self.assertPresence("Akira")
        self.traverse({'href': '/event/event/1/registration/5/show'})
        self.assertTitle("Anmeldung von Akira Abukara (Große Testakademie 2222)")
        f = self.response.forms['deleteregistrationform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse(
            {'href': '/event/event/1/registration/query'},
            {'description': 'Alle Anmeldungen'},
        )
        self.assertNonPresence("Akira")

    @as_users("garcia")
    def test_profile_link(self) -> None:
        # Test if I can view the profile of searchable members
        self.get('/event/event/1/registration/5/show')
        self.traverse({'description': 'DB-100-7'})
        # Test privacy: that I can see exactly the information I should see
        self.assertTitle("Akira Abukara")
        self.assertPresence("Geschlecht")
        self.assertPresence("divers")
        # self.assertPresence("Mitgliedschaft")
        self.assertNonPresence("Sichtbarkeit")
        self.assertPresence("28.12.2019")
        self.assertPresence("Tokyo Japan")
        self.assertNonPresence("Ich bin ein „Künstler“; im weiteren Sinne.")

    @event_keeper
    @as_users("garcia")
    def test_lodgements(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Unterkünfte")
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertPresence("Kalte Kammer")
        # Use the pager to navigate to Einzelzelle and test proper sorting
        self.traverse("Einzelzelle", "Nächste", "Vorherige")

        self.assertTitle("Unterkunft Einzelzelle (Große Testakademie 2222)")
        self.assertPresence("Emilia (Emmy) Eventis (Gast)")
        self.assertNonPresence("Überfüllte Unterkunft", div="inhabitants-1")
        self.assertPresence("Überfüllte Unterkunft", div="inhabitants-2")
        self.assertNonPresence("Überfüllte Unterkunft", div="inhabitants-3")
        self.assertNonPresence("Isomatte eingeteilt, hat dem aber nicht zugestimmt.")
        self.traverse("Bearbeiten")
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("1", f['regular_capacity'].value)
        f['regular_capacity'] = 3
        self.assertEqual("", f['notes'].value)
        f['notes'] = "neu mit Anbau"
        self.assertEqual("high", f['fields.contamination'].value)
        f['fields.contamination'] = "medium"
        self.submit(f)
        self.assertNonPresence("Überfüllte Unterkunft")
        self.traverse("Bearbeiten")
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("3", f['regular_capacity'].value)
        self.assertEqual("neu mit Anbau", f['notes'].value)
        self.assertEqual("medium", f['fields.contamination'].value)

        self.traverse("Unterkünfte", "Kalte Kammer")
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Inga Iota (U10)")

        self.traverse("Unterkünfte", "Kellerverlies")
        self.assertTitle("Unterkunft Kellerverlies (Große Testakademie 2222)")
        f = self.response.forms['deletelodgementform']
        self.submit(f)
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertNonPresence("Kellerverlies")
        self.traverse("Unterkunft anlegen")
        f = self.response.forms['createlodgementform']
        f['title'] = "Zelte"
        f['regular_capacity'] = 0
        f['camping_mat_capacity'] = 20
        f['notes'] = "oder gleich unter dem Sternenhimmel?"
        f['fields.contamination'] = "low"
        f['group_id'] = ""
        self.assertEqual("", f['group_id'].value)
        f['new_group_title'] = "Draußen"
        self.submit(f)
        self.assertTitle("Unterkunft Zelte (Große Testakademie 2222)")
        self.assertPresence("Unterkunftsgruppe Draußen")
        self.traverse("Bearbeiten")
        self.assertTitle("Unterkunft Zelte bearbeiten (Große Testakademie 2222)")
        self.assertPresence("some radiation")
        f = self.response.forms['changelodgementform']
        self.assertEqual('20', f['camping_mat_capacity'].value)
        self.assertEqual("oder gleich unter dem Sternenhimmel?", f['notes'].value)
        self.traverse("Unterkünfte", {'linkid': f"create_lodgement_in_group_{1001}"})
        self.assertTitle("Unterkunft anlegen (Große Testakademie 2222)")
        f = self.response.forms['createlodgementform']
        self.assertEqual("1001", f['group_id'].value)

    @event_keeper
    @as_users("anton")
    def test_lodgement_creation_with_groups(self) -> None:
        self.traverse("CdE-Party 2050", "Unterkünfte", "Unterkunftsgruppen verwalten")
        # only one lodgement group exists
        f = self.response.forms["lodgementgroupsummaryform"]
        self.assertEqual(f["title_4"].value, "CdE-Party")
        self.traverse("Unterkünfte", "Unterkunft anlegen")
        f = self.response.forms["createlodgementform"]
        # existing lodgement group is a hidden input
        self.assertEqual(f["group_id"].value, "4")
        self.assertNonPresence("Unterkunftsgruppe")
        f["title"] = "Testzimmer"
        f["regular_capacity"] = 1
        f["camping_mat_capacity"] = 0
        self.submit(f)
        self.traverse("Unterkünfte")
        # check the new lodgement was created
        self.assertPresence("Testzimmer")
        # check the lodgement can be changed
        self.traverse("Testzimmer", "Bearbeiten")
        f = self.response.forms["changelodgementform"]
        f["regular_capacity"] = 10
        self.submit(f)

        self.traverse(
            "Veranstaltungen",
            "TripelAkademie",
            "Unterkünfte",
            "Unterkunftsgruppen verwalten",
        )
        # delete all lodgement groups
        f = self.response.forms["lodgementgroupsummaryform"]
        self.assertEqual(f["title_6"].value, "Kaub")
        self.assertEqual(f["title_7"].value, "Oberwesel")
        self.assertEqual(f["title_8"].value, "Windischleuba")
        f["delete_6"] = True
        f["delete_7"] = True
        f["delete_8"] = True
        self.submit(f)
        # create new lodgement and new lodgement group
        self.traverse("Unterkünfte", "Unterkunft anlegen")
        self.assertPresence("Titel der neuen Unterkunftsgruppe")
        f = self.response.forms["createlodgementform"]
        self.assertEqual(f["group_id"].value, "")
        f["title"] = "Testzimmer"
        f["regular_capacity"] = 1
        f["camping_mat_capacity"] = 0
        f["new_group_title"] = "Testgruppe"
        self.submit(f)
        self.traverse("Unterkünfte")
        # check the new lodgement was created
        self.assertPresence("Testzimmer")

    @as_users("garcia")
    def test_lodgement_capacities(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/lodgement/overview'},
        )
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")

        expectations = {
            "group_regular_inhabitants_3_1": "2",
            "lodge_camping_mat_inhabitants_3_2": "1",
            "group_regular_capacity_1": "11",
            "total_inhabitants_3": "4",
            "total_camping_mat": "103",
            "total_regular": "16",
        }

        for k, v in expectations.items():
            self.assertPresence(v, div=k)

        self.traverse({'href': '/event/event/1/lodgement/1/change'})
        f = self.response.forms['changelodgementform']
        f['regular_capacity'] = 42
        self.submit(f)
        self.traverse({'href': '/event/event/1/lodgement/overview'})

        self.assertPresence("42", div="group_regular_capacity_2")
        self.assertPresence("53", div="total_regular")

    @as_users("garcia")
    def test_lodgement_display_with_different_participation_stati(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/lodgement/overview'},
        )
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        # Precondition: Einzelzelle (4) has currently 2 participants in part 2,
        # one of them is Emilia, but Emilia is GUEST in this part
        self.assertPresence("2", div="lodge_inhabitants_2_4")
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        self.assertEqual(f['part2.status'].value, "RegistrationPartStati.guest")
        self.assertEqual(f['part2.lodgement_id'].value, "4")

        # Emilia is listed in the inhabitants of the lodgement (with "(Gast)" suffix)
        self.traverse(
            {'href': '/event/event/1/lodgement/overview'},
            {'href': '/event/event/1/lodgement/4/show'},
        )
        self.assertPresence("Emilia (Emmy) Eventis (Gast)", div="inhabitants-2")
        # The lodgement check considers the lodgement as overfull
        self.assertPresence("Überfüllt", div="inhabitants-2")
        self.traverse({'href': '/event/event/1/lodgement/4/manage'})
        self.assertPresence("Emilia (Emmy) Eventis (Gast)", div="inhabitants-2")

        # Now, put Emilia to the WAITLIST
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        f['part2.status'] = "RegistrationPartStati.waitlist"
        f.submit()

        # Nothing should have changed, except for the suffix
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.assertPresence("2", div="lodge_inhabitants_2_4")
        self.traverse({'href': '/event/event/1/lodgement/4/show'})
        self.assertPresence("Emilia (Emmy) Eventis (Warteliste)", div="inhabitants-2")
        self.assertPresence("Überfüllt", div="inhabitants-2")
        self.traverse({'href': '/event/event/1/lodgement/4/manage'})
        self.assertPresence("Emilia (Emmy) Eventis (Warteliste)", div="inhabitants-2")

        # As a PARTICIPANT, ...
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        f['part2.status'] = "RegistrationPartStati.participant"
        f.submit()

        # ... Emilia should be listed without suffix
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.assertPresence("2", div="lodge_inhabitants_2_4")
        self.traverse({'href': '/event/event/1/lodgement/4/show'})
        # check that no suffix is shown after Emilia's name
        self.assertEqual(
            self.getFullTextOfElementWithText(
                "Emilia", "li", div="inhabitants-2"
            ).strip(),
            "Emilia (Emmy) Eventis",
        )
        self.traverse({'href': '/event/event/1/lodgement/4/manage'})
        # check that no suffix is shown after Emilia's name
        self.assertEqual(
            self.getFullTextOfElementWithText(
                "Emilia", "td", div="inhabitants-2"
            ).strip(),
            "Emilia (Emmy) Eventis",
        )

        # When CANCELLED, ...
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        f['part2.status'] = "RegistrationPartStati.cancelled"
        f.submit()

        # ... Emilia should be listed with suffix, but stroke-through and not counted
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.assertPresence("1", div="lodge_inhabitants_2_4")
        self.traverse({'href': '/event/event/1/lodgement/4/show'})
        self.assertPresence("Emilia (Emmy) Eventis (Abgemeldet)", div="inhabitants-2")
        # Assert "Emilia" is in an <s> (strike-through) element
        self.assertTextContainedInElement("Emilia", "s", div="inhabitants-2")
        # Assert "Emilia" is in the last <li> element
        self.assertTextContainedInNthElement("Emilia", "li", -1, div="inhabitants-2")
        self.assertNonPresence("Überfüllt", div="inhabitants-2")
        self.traverse({'href': '/event/event/1/lodgement/4/manage'})
        self.assertPresence("Emilia (Emmy) Eventis (Abgemeldet)", div="inhabitants-2")
        # Assert "Emilia" is in an <s> (strike-through) element
        self.assertTextContainedInElement("Emilia", "s", div="inhabitants-2")
        # Assert "Emilia" is in the last <tr> element
        self.assertTextContainedInNthElement("Emilia", "tr", -1, div="inhabitants-2")

    @event_keeper
    @as_users("garcia")
    def test_lodgement_groups(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Unterkünfte",
            "Unterkunftsgruppen verwalten",
        )
        self.assertTitle("Unterkunftsgruppen (Große Testakademie 2222)")

        # First try with invalid (empty name)
        f = self.response.forms["lodgementgroupsummaryform"]
        self.assertEqual(f['title_1'].value, "Haupthaus")
        f['create_-1'] = True
        f['title_1'] = "Hauptgebäude"
        self.submit(f, check_notification=False)
        self.assertTitle("Unterkunftsgruppen (Große Testakademie 2222)")
        self.assertValidationError('title_-1', "Darf nicht leer sein.")

        # Now, it should work
        f = self.response.forms["lodgementgroupsummaryform"]
        f['title_-1'] = "Zeltplatz"
        f['create_-2'] = True
        f['title_-2'] = "Altes Schloss"
        self.submit(f)

        # Check (non-)existence of groups in lodgement overview
        self.traverse("Unterkünfte")
        self.assertPresence("Hauptgebäude")
        self.assertPresence("Altes Schloss")
        self.assertPresence("AußenWohnGruppe")

        # Move all lodgements from Hautpgebäude to Altes Schloss.
        self.traverse({'linkid': 'move_or_delete_lodgements_in_group_1$'})
        self.assertTitle(
            "Verschiebe oder lösche Unterkünfte aus Hauptgebäude"
            " (Große Testakademie 2222)"
        )
        f = self.response.forms['movelodgementsform']
        self.submit(f, value='False', button='delete_group', check_notification=False)
        self.assertPresence("Nichts zu tun.", div='notifications')
        f['target_group_id'] = 1002
        self.submit(f, value='False', button='delete_group')
        self.assertPresence("Hauptgebäude")
        self.assertPresence("Altes Schloss")
        self.traverse("Einzelzelle")
        self.assertPresence("Altes Schloss")
        self.assertNonPresence("Hauptgebäude")
        self.assertNonPresence("Haupthaus")

        # Delete Sonstige with all lodgements.
        self.traverse("Unterkünfte", {'linkid': 'move_or_delete_lodgements_in_group_3'})
        self.assertTitle(
            "Verschiebe oder lösche Unterkünfte aus Sonstige (Große Testakademie 2222)"
        )
        self.assertPresence("Es gibt 1 Unterkünfte in dieser Gruppe.")
        f = self.response.forms['movelodgementsform']
        self.submit(f, value='True', button='delete_group')
        self.assertNonPresence("Sonstige")
        self.assertNonPresence("Kellerverlies")

    @event_keeper
    @as_users("garcia")
    def test_field_multiset(self) -> None:
        # first for registration-associated fields
        self.get('/event/event/1/field/setselect?kind=1&ids=1,2')
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertNonPresence("Validierung fehlgeschlagen.")
        self.assertNonPresence("Inga")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Datenfeld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("pedes", f['fields.transportation2'].value)
        f['fields.transportation2'] = "etc"
        f['change_note'] = "We need to fill missing entries…"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Datenfeld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("etc", f['fields.transportation2'].value)
        # Value of Inga should not have changed
        self.assertEqual("etc", f['fields.transportation4'].value)

        self.traverse(
            {'href': '/event/event/1/registration/query'},
            {'href': '/event/event/1/field/setselect'},
        )
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("", f['fields.lodge4'].value)
        f['fields.lodge4'] = "Test\nmit\n\nLeerzeilen"
        self.submit(f)
        self.traverse(
            {'href': '/event/event/1/registration/query'},
            {'href': '/event/event/1/field/setselect'},
        )
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Test\nmit\n\nLeerzeilen", f['fields.lodge4'].value)

        # now, we perform some basic checks for course-associated fields
        self.traverse(
            {'href': '/event/event/1/course/stats'},
            {'description': 'Kurssuche'},
            {'description': 'Datenfeld setzen'},
        )
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertPresence("Zu ändernde Kurse")
        self.assertPresence("α. Heldentum")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 5
        self.submit(f)
        self.assertTitle("Datenfeld room setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Nirwana", f['fields.room5'].value)
        f['fields.room5'] = "Ganz wo anders!"
        self.submit(f)
        self.assertNonPresence("Nirwana")
        self.assertPresence("Ganz wo anders!")

        # now, we perform some basic checks for lodgement-associated fields
        self.traverse(
            {'href': '/event/event/1/lodgement/overview'},
            {'description': 'Unterkunftssuche'},
            {'description': 'Datenfeld setzen'},
        )
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertPresence("Zu ändernde Unterkünfte")
        self.assertPresence("Einzelzelle, Haupthaus")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 6
        self.submit(f)
        self.assertTitle("Datenfeld contamination setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("high", f['fields.contamination1'].value)
        f['fields.contamination1'] = "medium"
        self.submit(f)
        self.assertPresence("elevated level of radiation ")

        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Anmeldung geändert", div=str(self.EVENT_LOG_OFFSET + 1) + "-1001"
        )
        self.assertPresence(
            "transportation gesetzt: We need to fill missing entries…",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "Anmeldung geändert", div=str(self.EVENT_LOG_OFFSET + 2) + "-1002"
        )
        self.assertPresence(
            "lodge gesetzt.", div=str(self.EVENT_LOG_OFFSET + 2) + "-1002"
        )
        self.assertPresence(
            "Kurs geändert", div=str(self.EVENT_LOG_OFFSET + 3) + "-1003"
        )
        self.assertPresence("Backup-Kurs", div=str(self.EVENT_LOG_OFFSET + 3) + "-1003")
        self.assertPresence(
            "Unterkunft geändert", div=str(self.EVENT_LOG_OFFSET + 4) + "-1004"
        )
        self.assertPresence("Warme Stube", div=str(self.EVENT_LOG_OFFSET + 4) + "-1004")

    @as_users("garcia")
    def test_stats(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/stats'},
        )
        self.assertTitle("Statistik (Große Testakademie 2222)")

        self.assertPresence("Teilnehmer-Statistik")
        self.assertPresence("1.H.", div="participant-stats")
        self.assertPresence("Nie eingecheckt")

        self.assertPresence("Kursstatistik")
        self.assertPresence("Morgenkreis", div="course-stats")
        self.assertPresence("Kursleitende (theoretisch)", div="course-stats")

        self.traverse({'href': '/event/event/1/registration/query', 'index': 2})
        self.assertPresence("Ergebnis [1]")

    @as_users("garcia")
    def test_stats_matches(self) -> None:
        # Create a statistic part group containing all event parts
        event_id = 1
        self.get('/event/event/1/part/summary')
        self.traverse("Gruppen", "Veranstaltungsteilgruppe hinzufügen")
        f = self.response.forms['configurepartgroupform']
        f['title'] = f['shortname'] = "3/3"
        f['constraint_type'] = const.EventPartGroupType.Statistic
        f['part_ids'] = ["1", "2", "3"]
        self.submit(f)

        # Create a statistic part group containing 2/3 event parts
        self.traverse("Veranstaltungsteilgruppe hinzufügen")
        f = self.response.forms['configurepartgroupform']
        f['title'] = f['shortname'] = "2/3"
        f['constraint_type'] = const.EventPartGroupType.Statistic
        f['part_ids'] = ["2", "3"]
        self.submit(f)

        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/stats'},
        )
        self.assertTitle("Statistik (Große Testakademie 2222)")

        event = self.event.get_event(self.key, event_id)

        def _test_one_stat(
            stat: StatisticMixin,
            *,
            track_id: int = 0,
            part_id: int = 0,
            part_group_id: int = 0,
        ) -> None:
            """Only one of track_id, part_id and part_group_id should be given."""

            # First retrieve the query for the given context id.
            if track_id:
                assert isinstance(stat, StatisticTrackMixin)
                query = stat.get_query(event, track_id, [-1])
            elif part_id:
                if isinstance(stat, StatisticTrackMixin):
                    query = stat.get_query_part(event, part_id, [-1])
                else:
                    query = stat.get_query(event, part_id, [-1])
            else:
                query = stat.get_query_part_group(event, part_group_id, [-1])

            # Take special care if the query filters by id. Since we do not supply
            #  valid ids, we cannot execute those queries.
            if get_id_constraint(stat.id_field, [-1]) in query.constraints:
                num = None
            else:
                num = len(self.event.submit_general_query(self.key, query, event_id))

            link_id = stat.get_link_id(
                track_id=track_id, part_id=part_id, part_group_id=part_group_id
            )

            with self.subTest(link_id=link_id):
                # Find the single link with matching id.
                [link] = self.response.html.find_all(id=link_id)
                # If the query is not by id, check that the result equals the link text.
                if num is not None:
                    self.assertEqual(int(link.text), num)
                else:
                    response = self.response
                    self.get(link['href'])
                    self.assertPresence(f"Ergebnis [{link.text}]", div="query-results")
                    self.response = response

        stat: StatisticMixin
        part_stats: Collection[StatisticPartMixin] = tuple(
            itertools.chain.from_iterable(PART_STATISTICS)
        )
        track_stats: Collection[StatisticTrackMixin] = tuple(
            itertools.chain.from_iterable(TRACK_STATISTICS)
        )

        # Test single track stats.
        for track_id, track in event.tracks.items():
            for stat in track_stats:
                _test_one_stat(stat, track_id=track_id)

        # Test single part stats.
        for part_id, part in event.parts.items():
            for stat in part_stats:
                _test_one_stat(stat, part_id=part_id)

            # Skip track-based stats for parts with at most one track.
            if len(StatisticMixin.get_track_ids(event, part_id=part_id)) <= 1:
                continue
            for stat in track_stats:
                _test_one_stat(stat, part_id=part_id)

        # Test single part group stats.
        for part_group_id, part_group in event.part_groups.items():
            # Skip all part groups with at most one part.
            if len(part_group.parts) <= 1:
                continue  # pragma: no cover
            for stat in part_stats:
                _test_one_stat(stat, part_group_id=part_group_id)

            if (
                len(StatisticMixin.get_track_ids(event, part_group_id=part_group_id))
                <= 1
            ):
                continue  # pragma: no cover
            for stat in track_stats:
                _test_one_stat(stat, part_group_id=part_group_id)

        registration_ids = self.event.list_registrations(self.key, event_id)
        registrations = self.event.get_registrations(self.key, registration_ids)
        grouper = EventRegistrationInXChoiceGrouper(event, registrations)

        def _test_grouper_link(reg_ids: Optional[set[int]], link_id: str) -> None:
            with self.subTest(link_id=link_id):
                links = self.response.html.find_all(id=link_id)
                if reg_ids is None:
                    self.assertEqual(links, [])
                else:
                    [link] = links
                    self.assertEqual(int(link.text), len(reg_ids))

        for x, row in grouper:
            for track_id, reg_ids in row['tracks'].items():
                _test_grouper_link(reg_ids, grouper.get_link_id(x, track_id=track_id))
            for part_id, reg_ids in row['parts'].items():
                if len(StatisticMixin.get_track_ids(event, part_id=part_id)) <= 1:
                    continue
                _test_grouper_link(reg_ids, grouper.get_link_id(x, part_id=part_id))
            for pg_id, reg_ids in row['part_groups'].items():
                if len(StatisticMixin.get_track_ids(event, part_group_id=pg_id)) <= 1:
                    continue  # pragma: no cover
                _test_grouper_link(reg_ids, grouper.get_link_id(x, part_group_id=pg_id))

    @as_users("garcia")
    def test_stats_links(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Statistik")
        part_stats_table = self.response.html.find(id="participant-stats")
        track_stats_table = self.response.html.find(id="course-stats")

        # Sporadically click on a few links.
        # Do this, because they take a very long time otherwise.
        n = 5
        for table in (part_stats_table, track_stats_table):
            for link in table.findAll("a")[::n]:
                with self.subTest(clicked_link_id=link.attrs['id']):
                    self.get(link["href"])
                    self.assertPresence(f"Ergebnis [{link.text}]", div="query-results")

    @as_users("garcia")
    def test_course_stats(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/course/stats'},
        )
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertPresence("Heldentum")
        self.assertPresence("1")
        self.assertPresence("δ")

    @as_users("garcia")
    def test_course_choices(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/choices'},
        )
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        self.assertPresence("Morgenkreis", div="course_choice_table")
        self.assertPresence("Morgenkreis", div="assignment-options")
        self.assertPresence("Heldentum")
        self.assertPresence("Anton")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 1
        self.submit(f)
        self.assertNonPresence("Anton")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = ''
        f['course_id'] = 2
        f['position'] = -7
        self.submit(f)
        self.assertNonPresence("Anton")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        self.submit(f)
        self.assertNonPresence("Inga")
        self.assertNonPresence("Anton")
        self.assertPresence("Garcia")
        self.assertPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton")
        self.assertNonPresence("Inga")
        self.assertNonPresence("Garcia")
        self.assertPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['position'] = ''
        f['track_id'] = ''
        self.submit(f)
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2]
        f['assign_track_ids'] = [3]
        f['assign_action'] = 0
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 1
        f['position'] = -6
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton")
        self.assertPresence("Inga")
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = -6
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton")
        self.assertPresence("Emilia")
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['position'] = ''
        f['track_id'] = ''
        self.submit(f)
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [3]
        f['assign_track_ids'] = [2, 3]
        f['assign_action'] = -4
        f['assign_course_id'] = 5
        self.submit(f)
        f = self.response.forms['choicefilterform']
        f['course_id'] = 5
        f['position'] = -6
        self.submit(f)
        self.assertNonPresence("Anton")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

        # Test filtering for unassigned participants
        f = self.response.forms['choicefilterform']
        f['course_id'] = ''
        f['track_id'] = ''
        f['position'] = -6
        self.submit(f)
        self.assertNonPresence("Inga")
        self.assertPresence("Garcia")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 2
        self.submit(f)
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Emilia")

        # Test including all open registrations
        f = self.response.forms['choicefilterform']
        f['include_active'].checked = True
        self.submit(f)
        self.assertPresence("Emilia")

        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Kurs eingeteilt in Kursschiene Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "Kurs eingeteilt in Kursschiene Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )
        self.assertPresence(
            "Kurs eingeteilt in Kursschienen Kaffee, Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 3) + "-1003",
        )

        # Single-track event
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/3/show'},
            {'href': '/event/event/3/course/stats'},
            {'href': '/event/event/3/course/choices'},
        )
        self.assertTitle("Kurswahlen (CyberTestAkademie)")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [7]
        f['assign_action'] = -4
        self.submit(f)

        # Check log
        self.traverse({'href': '/event/event/3/log'})
        self.assertPresence("Kurs eingeteilt.", div="1-1004")

    @as_users("anton")
    def test_invalid_course_choices(self) -> None:
        # Check there is no error for without courses
        self.get('/event/event/2/course/choices')
        self.basic_validate()
        self.assertTitle("Kurse verwalten (CdE-Party 2050)")
        self.assertPresence(
            "sind nur in Veranstaltungen mit Kursschienen möglich.", div='notifications'
        )

    @as_users("garcia")
    def test_automatic_assignment(self) -> None:
        self.get('/event/event/1/course/choices')
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3, 4]
        f['assign_track_ids'] = [1, 2, 3]
        f['assign_action'] = -5
        self.submit(f)
        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Kurs eingeteilt in Kursschienen Morgenkreis, Kaffee, Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "Kurs eingeteilt in Kursschienen Morgenkreis, Kaffee, Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    @as_users("garcia")
    def test_course_choices_filter_persistence(self) -> None:
        self.get('/event/event/1/course/choices')
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")

        # Test persistence of filters when submitting assignment
        f = self.response.forms['choicefilterform']
        f['course_id'] = 2
        f['track_id'] = 3
        f['position'] = -5
        f['ids'] = "2,3"
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [2]
        f['assign_track_ids'] = [3]
        f['assign_action'] = 0
        self.submit(f)

        f = self.response.forms['choicefilterform']
        self.assertEqual(f['course_id'].value, "2")
        self.assertEqual(f['track_id'].value, "3")
        self.assertEqual(f['position'].value, "-5")
        self.assertEqual(f['ids'].value, "2,3")
        self.assertNonPresence("Anton")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

        # Check log
        self.traverse({'href': '/event/event/1/log'})
        self.assertPresence(
            "Kurs eingeteilt in Kursschiene Sitzung.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )

    @as_users("garcia")
    def test_course_choices_problems(self) -> None:
        self.get('/event/event/1/course/choices')
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        # Assigning Anton and Emilia to their 3rd choice (which is not present)
        # should not raise an exception but a warning
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2]
        f['assign_track_ids'] = [3]
        f['assign_action'] = 2
        self.submit(f, check_notification=False)
        self.assertNotification("Emilia Eventis hat keine 3. Kurswahl", 'warning')
        self.assertPresence("0 von 2 Anmeldungen gespeichert", div="notifications")

        # Deleting Anton's choices and doing an automatic assignment should also
        # raise a warning (but no exception)
        self.traverse(
            {'href': '/event/event/1/registration/1/show'},
            {'href': '/event/event/1/registration/1/change'},
        )
        f = self.response.forms['changeregistrationform']
        f['track3.course_choice_0'] = ''
        f['track3.course_choice_1'] = ''
        self.submit(f)
        self.get('/event/event/1/course/choices')
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 3]
        f['assign_track_ids'] = [3]
        f['assign_action'] = -5
        self.submit(f, check_notification=False)
        self.assertNotification("Keine Kurswahlen für Anton Administrator", 'warning')
        self.assertPresence("1 von 2 Anmeldungen gespeichert", div="notifications")

    @as_users("garcia")
    def test_course_assignment_violations(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Ungereimtheiten")
        self.assertPresence("Ausfallende Kurse mit Teilnehmenden")
        self.assertPresence("Kabarett", div='CancelledWithAttendeesCV-list')
        self.traverse("Kabarett")
        self.assertPresence(
            r"Findet nicht statt aber hat \d+ Teilnehmende.",
            regex=True,
            div="track-violations-2",
        )
        self.traverse("Ungereimtheiten")
        self.assertPresence("Fehlende Kurseinteilungen")
        self.assertPresence("Anton", div='NoCourseAssignedCV-list')
        self.traverse("Anton")
        self.assertPresence(
            "Ist in Sitzung in keinen Kurs eingeteilt.",
            div="constraint-violations-list",
        )

        # Assigning Garcia to "Backup" in "Kaffekränzchen" fixes 'cancelled'
        # problem, but raises 'unchosen' problem
        self.get('/event/event/1/registration/3/change')
        f = self.response.forms['changeregistrationform']
        f['track2.course_id'] = "5"
        self.submit(f)
        # Assign Garcia and Anton to their 1. choice to fix 'no_course' issues;
        # accidentally, also assign emilia (instructor) to 1. choice ;-)
        self.traverse("Kurse", "Kurseinteilung")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3]
        f['assign_track_ids'] = [1, 3]
        f['assign_action'] = 0
        self.submit(f)

        self.traverse("Ungereimtheiten")
        self.assertPresence("Fehlerhafte Kurseinteilungen")
        self.assertPresence(
            "Garcia Generalis ist in Kaffee in einen nicht"
            " gewählten Kurs (ε. Backup) eingeteilt.",
            div='IncorrectCourseAssignedCV-list',
        )
        self.assertPresence(
            "Emilia (Emmy) Eventis ist in Sitzung nicht in"
            " seinen/ihren geleiteten Kurs (α. Heldentum) eingeteilt.",
            div='IncorrectCourseAssignedCV-list',
        )
        self.traverse("Emilia")
        self.assertPresence(
            "Ist in Sitzung nicht in geleiteten Kurs (α. Heldentum) eingeteilt."
        )

        # Change "Backup" to "never offered" in "Kaffeekränzchen".
        self.traverse("Kurse", "Backup", "Bearbeiten")
        f = self.response.forms['configurecourseform']
        f['segment2'] = False
        self.submit(f)
        self.assertPresence(
            "Wird in Kaffee nicht angeboten aber hat", div="constraint-violations-list"
        )
        self.traverse("Ungereimtheiten")

        # Reduce max size of "Heldentum".
        self.traverse("Kurse", "Heldentum", "Bearbeiten")
        f = self.response.forms['configurecourseform']
        f['max_size'] = 1
        self.submit(f)
        self.assertPresence("Zu viele Teilnehmende (3 > 1).")
        self.traverse("Ungereimtheiten")
        self.assertPresence(
            "Heldentum hat zu viele Teilnehmende (3 > 1) in Sitzung.",
            div="IncorrectNumAttendeesCV-list",
        )
        f['max_size'] = 3
        self.submit(f)
        self.traverse("Kurse")
        self.assertHasClass("#course-1-track-3", "course-exactly-full")

        # Remove all non instructors from "Heldentum" in "Sitzung".
        self.get('/event/event/1/registration/2/change')
        f = self.response.forms['changeregistrationform']
        f['track3.course_id'] = 1
        self.submit(f)
        self.traverse("Kurse", "Heldentum", "Kursteilnehmende verwalten")
        f = self.response.forms['manageattendeesform']
        f['delete_3_5'] = f['delete_3_4'] = f['delete_3_1'] = True
        self.submit(f)
        self.assertPresence("1 Kursleitende aber keine Teilnehmenden.")
        self.traverse("Ungereimtheiten")
        self.assertPresence(
            "Heldentum hat 1 Kursleitende aber keine Teilnehmenden in Sitzung.",
            div="LonelyAttendeesCV-list",
        )

    @as_users("garcia")
    def test_course_display_with_different_participation_stati(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/1/show'},
        )
        # Precondition: Heldentum (1) has currently 2+1 participants in track 3,
        # one of them is Inga, who is PARTICIPANT in the relevant part (3)
        self.assertPresence("2 + 1", div="track3-attendees")
        self.get('/event/event/1/registration/4/change')
        f = self.response.forms['changeregistrationform']
        self.assertEqual(f['part3.status'].value, "RegistrationPartStati.participant")
        self.assertEqual(f['track3.course_id'].value, "1")

        # Inga should be listed in the course without suffix
        self.traverse(
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/1/show'},
        )
        # check that no suffix is shown after Inga's name
        self.assertEqual(
            self.getFullTextOfElementWithText(
                "Inga", "li", div="track3-attendees"
            ).strip(),
            "Inga Iota",
        )
        self.traverse({'href': '/event/event/1/course/1/manage'})
        # check that no suffix is shown after Inga's name
        self.assertEqual(
            self.getFullTextOfElementWithText(
                "Inga", "td", div="track3-attendees"
            ).strip(),
            "Inga Iota",
        )
        # The course check considers the course as full enough
        self.assertNonPresence("Zu wenige Teilnehmende", div="track3-attendees")

        # As a GUEST, ...
        self.get('/event/event/1/registration/4/change')
        f = self.response.forms['changeregistrationform']
        f['part3.status'] = "RegistrationPartStati.guest"
        f.submit()

        # ... Inga should be listed with "(Gast)" suffix
        self.traverse(
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/1/show'},
        )
        self.assertPresence("2 + 1", div="track3-attendees")
        self.assertPresence("Inga Iota (Gast)", div="track3-attendees")
        self.assertNonPresence("Zu wenige Teilnehmende", div="track3-attendees")
        self.traverse({'href': '/event/event/1/course/1/manage'})
        self.assertPresence("Inga Iota (Gast)", div="track3-attendees")

        # Now, put Inga to the WAITLIST
        self.get('/event/event/1/registration/4/change')
        f = self.response.forms['changeregistrationform']
        f['part3.status'] = "RegistrationPartStati.waitlist"
        f.submit()

        # Nothing should have changed, except for the suffix
        self.traverse(
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/1/show'},
        )
        self.assertPresence("2 + 1", div="track3-attendees")
        self.assertPresence("Inga Iota (Warteliste)", div="track3-attendees")
        self.assertNonPresence("Zu wenige Teilnehmende", div="track3-attendees")
        self.traverse({'href': '/event/event/1/course/1/manage'})
        self.assertPresence("Inga Iota (Warteliste)", div="track3-attendees")

        # When cancelled, ...
        self.get('/event/event/1/registration/4/change')
        f = self.response.forms['changeregistrationform']
        f['part3.status'] = "RegistrationPartStati.cancelled"
        f.submit()

        # ... Inga should be listed with suffix, but stroke-through and not counted
        self.traverse(
            {'href': '/event/event/1/course/stats'},
            {'href': '/event/event/1/course/1/show'},
        )
        self.assertPresence("1 + 1", div="track3-attendees")
        self.assertPresence("Inga Iota (Abgemeldet)", div="track3-attendees")
        # Assert "Inga" is in an <s> (strike-through) element
        self.assertTextContainedInElement("Inga", "s", div="track3-attendees")
        # Assert "Inga" is in the last <li> element
        self.assertTextContainedInNthElement("Inga", "li", -1, div="track3-attendees")
        # Now, we're missing a course attendee
        self.assertPresence("Zu wenige Teilnehmende", div="track3-attendees")
        self.traverse({'href': '/event/event/1/course/1/manage'})
        self.assertPresence("Inga Iota (Abgemeldet)", div="track3-attendees")
        # Assert "Inga" is in an <s> (strike-through) element
        self.assertTextContainedInElement("Inga", "s", div="track3-attendees")
        # Assert "Inga" is in the last <tr> element
        self.assertTextContainedInNthElement("Inga", "tr", -1, div="track3-attendees")

    @as_users("garcia")
    def test_lodgement_wishes_graph(self) -> None:

        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/lodgement/'},
            {'href': '/event/event/1/lodgement/graph/form'},
        )
        self.assertPresence(
            "Unterdrücke Wunsche-Kante von Anton Administrator zu Bertå Beispiel",
            div='wish-problems',
        )
        f = self.response.forms['settingsform']
        self.submit(f, check_notification=False)
        # unfortunately Webtest's response.lxml property has a bug, as it tries
        # to construct the lxml ElementTree from unicode, which is not supported
        # by lxml (see https://github.com/Pylons/webtest/issues/236). So, let's
        # do it manually.
        xml = lxml.etree.XML(self.response.body)
        xml_namespaces = {
            'svg': "http://www.w3.org/2000/svg",
            'xlink': "http://www.w3.org/1999/xlink",
        }

        node_link = xml.xpath(  # type: ignore[index]
            '//svg:a[.//svg:text[contains(text(),"Garcia")]]',
            namespaces=xml_namespaces,
        )[0]
        assert isinstance(node_link, lxml.etree._Element)
        self.assertEqual(
            "/event/event/1/registration/3/show",
            node_link.attrib['{http://www.w3.org/1999/xlink}href'],
        )
        parts_text_text = node_link.xpath(
            './svg:text/text()', namespaces=xml_namespaces
        )
        assert isinstance(parts_text_text, list)
        self.assertIn("Wu, 1.H., 2.H.", parts_text_text[1])
        edge_group = xml.xpath('//svg:g[@class="edge"]', namespaces=xml_namespaces)
        assert isinstance(edge_group, list)
        self.assertEqual(1, len(edge_group))
        assert isinstance(edge_group[0], lxml.etree._Element)
        edge_link_title = edge_group[0].xpath(
            './/svg:a/@xlink:title', namespaces=xml_namespaces
        )
        assert isinstance(edge_link_title, list)
        self.assertEqual("Anton Administrator → Garcia Generalis", edge_link_title[0])
        # Emilia has no wishes and has not been wished
        self.assertNotIn("Emilia", self.response.text)
        # We don't display lodgement group / lodgement clusters this time
        self.assertNotIn("Haupthaus", self.response.text)
        self.assertNotIn("Einzelzelle", self.response.text)

        # Second time
        self.get('/event/event/1/lodgement/graph/form')
        f = self.response.forms['settingsform']
        f['all_participants'] = True
        f['show_lodgements'] = True
        f['part_id'] = 2
        self.submit(f, check_notification=False)
        xml = lxml.etree.XML(self.response.body)

        self.assertIn("Emilia", self.response.text)
        self.assertIn("Einzelzelle", self.response.text)
        # Again no lodgement groups
        self.assertNotIn("Haupthaus", self.response.text)
        # Anton is not present in 1. Hälfte
        self.assertNotIn("Anton", self.response.text)
        edge_group = xml.xpath('//svg:g[@class="edge"]', namespaces=xml_namespaces)
        assert isinstance(edge_group, list)
        self.assertEqual(0, len(edge_group))

        # Only lodgement groups
        self.get('/event/event/1/lodgement/graph/form')
        f = self.response.forms['settingsform']
        f['all_participants'] = True
        f['show_lodgement_groups'] = True
        f['part_id'] = 2
        self.submit(f, check_notification=False)
        xml = lxml.etree.XML(self.response.body)

        self.assertIn("Emilia", self.response.text)
        # No lodgements, but  lodgement groups
        self.assertNotIn("Einzelzelle", self.response.text)
        self.assertIn("Haupthaus", self.response.text)

        # Lodgement and lodgement groups
        self.get('/event/event/1/lodgement/graph/form')
        f = self.response.forms['settingsform']
        f['all_participants'] = True
        f['show_lodgements'] = True
        f['show_lodgement_groups'] = True
        f['part_id'] = 2
        self.submit(f, check_notification=False)
        xml = lxml.etree.XML(self.response.body)

        self.assertIn("Emilia", self.response.text)
        self.assertIn("Einzelzelle", self.response.text)
        self.assertIn("Haupthaus", self.response.text)

    @storage
    @as_users("garcia")
    def test_downloads(self) -> None:
        magic_bytes = {
            'pdf': b"%PDF",
            'targz': b"\x1f\x8b",
            'zip': b"PK\x03\x04",
        }

        def assertLatex(*phrases: str) -> None:
            self.assertEqual("text/x-tex", self.response.content_type)
            self.assertIn("documentclass", self.response.text)
            for phrase in phrases:
                self.assertIn(phrase, self.response.text)

        def assertLatexNotIn(*phrases: str) -> None:
            self.assertEqual("text/x-tex", self.response.content_type)
            self.assertIn("documentclass", self.response.text)
            for phrase in phrases:
                self.assertNotIn(phrase, self.response.text)

        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/download'},
        )
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        save = self.response

        # printables
        # nametags
        self.response = save.click(href='/event/event/1/download/nametag\\?runs=0')
        self.assertTrue(self.response.body.startswith(magic_bytes['targz']))
        self.assertLess(1000, len(self.response.body))
        with tempfile.TemporaryFile() as f:
            f.write(self.response.body)
        self.response = save.click(href='/event/event/1/download/nametag\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # course attendee list
        self.response = save.click(href='/event/event/1/download/courselists\\?runs=0')
        self.assertTrue(self.response.body.startswith(magic_bytes['targz']))
        self.assertLess(1000, len(self.response.body))
        self.response = save.click(href='/event/event/1/download/courselists\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # lodgement inhabitant list
        self.response = save.click(
            href='/event/event/1/download/lodgementlists\\?runs=0'
        )
        self.assertTrue(self.response.body.startswith(magic_bytes['targz']))
        self.assertLess(1000, len(self.response.body))
        self.response = save.click(
            href='/event/event/1/download/lodgementlists\\?runs=2'
        )
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # course puzzle
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=0')
        assertLatex('Planetenretten für Anfänger')
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # lodgement puzzle
        self.response = save.click(
            href='/event/event/1/download/lodgementpuzzle\\?runs=0'
        )
        assertLatex('Kalte Kammer')
        self.response = save.click(
            href='/event/event/1/download/lodgementpuzzle\\?runs=2'
        )
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))

        # participant lists
        # public list
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=0', index=0
        )
        assertLatex('Heldentum', 'Emilia')  # we don't want nicknames here
        assertLatexNotIn('Garcia')
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=2', index=0
        )
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # orga list
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=0&orgas_only=True',
            index=0,
        )
        assertLatex('Heldentum', 'Emilia', 'Garcia')  # we don't want nicknames here

        # export
        # partial event export
        self.response = save.click(href='/event/event/1/download/partial')
        self.assertEqual("partial", self.response.json['kind'])
        self.assertEqual(
            "Planetenretten für Anfänger", self.response.json['courses']['1']['title']
        )
        # registrations
        self.response = save.click(href='/event/event/1/download/csv_registrations')
        self.assertIn(
            'reg.id;persona.id;persona.nickname;persona.given_names;',
            self.response.text,
        )
        # courselist
        self.response = save.click(href='/event/event/1/download/csv_courses')
        self.assertIn('course.id;course.course_id;course.nr;', self.response.text)
        # lodgementlist
        self.response = save.click(href='/event/event/1/download/csv_lodgements')
        self.assertIn(
            'lodgement.id;lodgement.lodgement_id;lodgement.title;', self.response.text
        )
        # dokuteam courselist
        self.response = save.click(href='/event/event/1/download/dokuteam_course')
        self.assertIn('|cde', self.response.text)
        # dokuteam participant list
        self.response = save.click(href='event/event/1/download/dokuteam_participant')
        self.assertTrue(self.response.body.startswith(magic_bytes['zip']))
        self.assertLess(500, len(self.response.body))

    @storage
    @as_users("garcia")
    def test_download_export(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Downloads & Import",
            {'href': '/event/1/export'},
        )
        with open(
            self.testfile_dir / "event_export.json",
            encoding="utf-8",
        ) as datafile:
            expectation = json.load(datafile)
        result = json.loads(self.response.text)
        expectation['timestamp'] = result['timestamp']  # nearly_now() won't do
        for log_entry in result['event.log'].values():
            del log_entry['ctime']
        for log_entry in expectation['event.log'].values():
            del log_entry['ctime']
        for token_id, token in expectation[OrgaToken.database_table].items():
            token['ctime'] = result[OrgaToken.database_table][token_id]['ctime']
        self.assertEqual(expectation, result)

    @as_users("garcia")
    def test_download_csv(self) -> None:

        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/download'},
        )
        save = self.response
        self.response = save.click(href='/event/event/1/download/csv_registrations')

        result = list(
            csv.DictReader(self.response.text.split('\n'), dialect=CustomCSVDialect)
        )
        self.assertIn('2222-01-01', tuple(row['persona.birthday'] for row in result))
        self.assertIn(
            'high', tuple(row['lodgement3.xfield_contamination'] for row in result)
        )
        self.assertIn(
            const.RegistrationPartStati.cancelled.name,
            tuple(row['part2.status'] for row in result),
        )

        self.response = save.click(href='/event/event/1/download/csv_courses')
        result = list(
            csv.DictReader(self.response.text.split('\n'), dialect=CustomCSVDialect)
        )
        self.assertIn('ToFi & Co', tuple(row['course.instructors'] for row in result))
        self.assertTrue(
            any(
                row['track2.is_offered'] == 'True'
                and row['track2.takes_place'] == 'False'
                for row in result
            )
        )
        self.assertIn(
            'Seminarraum 42', tuple(row['course_fields.xfield_room'] for row in result)
        )

        self.response = save.click(href='/event/event/1/download/csv_lodgements')
        result = list(
            csv.DictReader(self.response.text.split('\n'), dialect=CustomCSVDialect)
        )
        self.assertIn(
            '100', tuple(row['lodgement.camping_mat_capacity'] for row in result)
        )
        self.assertIn(
            'low', tuple(row['lodgement_fields.xfield_contamination'] for row in result)
        )

    @as_users("berta")
    def test_no_downloads(self) -> None:
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'CdE-Party 2050'},
            {'description': 'Downloads'},
        )
        self.assertTitle("Downloads zur Veranstaltung CdE-Party 2050")

        # first check empty csv
        self.traverse({'href': '/event/event/2/download/csv_registrations'})
        self.assertPresence('Leere Datei.', div='notifications')
        self.assertNonPresence("Kursteilnehmendenlisten")
        self.get('/event/event/2/download/csv_courses')
        self.assertPresence('Leere Datei.', div='notifications')
        self.assertNonPresence("Unterkunftbewohnerlisten")
        self.get('/event/event/2/download/csv_lodgements')
        self.assertPresence('Leere Datei.', div='notifications')

        # Test nametags
        save = self.response
        self.traverse({'href': '/event/event/2/download/nametag\\?runs=2'})
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        self.response = save.click(href='/event/event/2/download/nametag\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.response = save

        downloads = [  # name of download, visibility over UI
            ('participantlist', True),
            ('courselists', False),
            ('lodgementlists', False),
            ('coursepuzzle', False),
            ('lodgementpuzzle', False),
        ]
        for doc, visible in downloads:
            link = f'/event/event/2/download/{doc}'
            self.response = save
            if visible:
                self.assertIn(link, self.response.text)
            else:
                self.assertNoLink(link)
            # now check empty pdfs
            self.get(link + '?runs=2')
            self.assertPresence('Leeres PDF', div='notifications')
            self.assertNonPresence('konnte nicht kompiliert werden.')
            # and availability of (empty) LaTeX sources
            self.get(link + '?runs=0')
            if link.endswith('lists'):  # downloads with multiple docs are zipped
                self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
            else:
                self.assertEqual("text/x-tex", self.response.content_type)
                self.assertIn("documentclass", self.response.text)

    @as_users("garcia")
    def test_questionnaire_manipulation(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Konfiguration")
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse("Fragebogen")
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertNotIn("may_reserve", f.fields)
        self.traverse("Fragebogen konfigurieren")
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")

        f = self.response.forms['configurequestionnaireform']
        self.assertEqual("3", f['field_id_6'].value)
        self.assertEqual("2", f['field_id_5'].value)
        self.assertEqual("Weitere Überschrift", f['title_4'].value)
        self.assertEqual("mit Text darunter", f['text_1'].value)

        f['title_4'] = "Immernoch Überschrift"
        f['text_1'] = "mehr Text darunter\nviel mehr"
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")

        f = self.response.forms['configurequestionnaireform']
        self.assertEqual("3", f['field_id_6'].value)
        self.assertEqual("Hauswunsch", f['label_6'].value)
        self.assertEqual("Immernoch Überschrift", f['title_4'].value)
        self.assertEqual("mehr Text darunter\nviel mehr", f['text_1'].value)

        f['delete_4'].checked = True
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")

        f = self.response.forms['configurequestionnaireform']
        self.assertNotIn("field_id_6", f.fields)
        self.assertEqual("Unterüberschrift", f['title_0'].value)
        self.assertEqual("nur etwas Text", f['text_3'].value)
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("Hauswunsch", f['label_5'].value)

        f['create_-1'].checked = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['field_id_-1'] = 4
        f['label_-1'] = "Input"
        f['readonly_-1'].checked = True
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")

        # Test warning against overwrite.
        self.submit(f, check_notification=False)
        self.assertNotification(
            "Die Konfiguration hat sich in der Zwischenzeit geändert."
        )
        self.traverse("Fragebogen konfigurieren")

        f = self.response.forms['configurequestionnaireform']
        self.assertIn("field_id_6", f.fields)
        self.assertEqual("4", f['field_id_6'].value)
        self.assertEqual("Input", f['label_6'].value)

        # Add a row with a datetime field and check that the default value works.
        f['create_-1'] = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['field_id_-1'] = 9  # 'arrival_at'
        f['default_value_-1'] = expectation = "2025-05-24 23:47:32"
        self.submit(f)
        f = self.response.forms['configurequestionnaireform']
        self.assertEqual(expectation + "+02:00", f['default_value_7'].value)

        execsql("UPDATE event.registrations SET fields = '{}';")
        self.traverse("Fragebogen")
        f = self.response.forms['questionnaireform']
        self.assertEqual(expectation, f['fields.arrival_at'].value.replace("T", " "))

    @as_users("garcia")
    def test_questionnaire_reorder(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/questionnaire/config'},
            {'href': '/event/event/1/questionnaire/reorder'},
        )
        f = self.response.forms['reorderquestionnaireform']
        self.assertEqual(f['order'].value, "0,1,2,3,4,5,6")
        f['order'] = "Hallo, Kekse"
        self.submit(f, check_notification=False)
        self.assertValidationError('order', "Ungültige Eingabe für eine Ganzzahl.")
        # row index out of range
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "-1,100"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Zeile darf nur genau einmal vorkommen."
        )
        # row included twice
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "0,1,1,3,4,5,6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Zeile darf nur genau einmal vorkommen."
        )
        # not all rows included
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "0,1,2"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Zeile darf nur genau einmal vorkommen."
        )
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = '5,3,1,0,2,4'
        f['order'] = '6,4,2,0,1,3,5'
        self.submit(f)
        self.assertTitle("Fragebogen umordnen (Große Testakademie 2222)")
        self.traverse({'description': 'Fragebogen konfigurieren'})
        f = self.response.forms['configurequestionnaireform']
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        self.assertEqual("3", f['field_id_0'].value)
        self.assertEqual("2", f['field_id_6'].value)
        self.assertEqual("1", f['field_id_2'].value)
        self.assertEqual("", f['field_id_3'].value)

    @event_keeper
    @as_users("garcia", "ludwig")
    def test_checkin(self) -> None:
        # multi-part
        self.traverse("Veranstaltungen", "Große Testakademie", "Checkin")
        self.assertTitle("Checkin (Große Testakademie 2222)")

        # Check the display of custom datafields.
        self.assertPresence("Anzahl Großbuchstaben 4", div="checkin-fields-1")
        self.assertPresence("Anzahl Großbuchstaben 3", div="checkin-fields-2")
        self.assertPresence("Anzahl Großbuchstaben 2", div="checkin-fields-6")
        with self.switch_user("garcia"):
            self.traverse(
                "Veranstaltungen", "Große Testakademie", "Datenfelder konfigurieren"
            )
            f = self.response.forms['fieldsummaryform']
            f['checkin_8'].checked = False
            self.submit(f)
        self.traverse("Checkin")
        self.assertNonPresence("Anzahl Großbuchstaben", div="checkin-list")

        # Check the filtering per event part.
        self.assertPresence("Anton", div="checkin-list")
        self.assertPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertPresence("Emilia", div="checkin-list")
        f = self.response.forms['checkinfilterform']
        f['part_ids'] = [1, 2, 3]
        self.submit(f)
        self.assertPresence("Anton", div="checkin-list")
        self.assertPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertPresence("Emilia", div="checkin-list")
        f = self.response.forms['checkinfilterform']
        f['part_ids'] = [1]
        self.submit(f)
        self.assertNonPresence("Anton", div="checkin-list")
        self.assertPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertNonPresence("Emilia", div="checkin-list")
        f = self.response.forms['checkinfilterform']
        f['part_ids'] = [2]
        self.submit(f)
        self.assertNonPresence("Anton", div="checkin-list")
        self.assertNonPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertPresence("Emilia", div="checkin-list")
        f = self.response.forms['checkinfilterform']
        f['part_ids'] = [3]
        self.submit(f)
        self.assertPresence("Anton", div="checkin-list")
        self.assertNonPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertPresence("Emilia", div="checkin-list")
        # TODO this check does not really make sense with the existing data.
        f = self.response.forms['checkinfilterform']
        parts_wo_berta = [2, 3]
        f['part_ids'] = parts_wo_berta
        self.submit(f)
        self.assertPresence("Anton", div="checkin-list")
        self.assertNonPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        self.assertPresence("Emilia", div="checkin-list")

        # test checkout
        delta = datetime.timedelta(seconds=2)
        # we need a delta of at least one second between checkin and checkout
        with freezegun.freeze_time(now() - delta) as frozen_time:
            f = self.response.forms['checkinfilterform']
            f['part_ids'] = []
            self.submit(f)
            self.submit(self.response.forms['checkinform1'])
            self.submit(self.response.forms['checkinform6'])
            f = self.response.forms['checkinfilterform']
            f['part_ids'] = parts_wo_berta
            self.submit(f)
            self.traverse({'description': "Checkout"})
            self.assertPresence("Anton", div="checkin-list")
            self.assertNonPresence("Bertå", div="checkin-list")
            f = self.response.forms['checkinfilterform']
            f['part_ids'] = []
            self.submit(f)
            self.assertPresence("Anton", div="checkin-list")
            self.assertPresence("Bertå", div="checkin-list")
            frozen_time.tick(delta)
            f = self.response.forms['checkinform6']
            self.submit(f)
            self.submit(f, check_notification=False)
            self.assertNotification("Bereits ausgecheckt.", 'error')
            self.assertPresence("Anton", div="checkin-list")
            self.assertNonPresence("Bertå", div="checkin-list")
            self.traverse({'description': "Checkin", 'index': 1})
            self.assertNonPresence("Anton", div="checkin-list")
            self.assertPresence("Bertå", div="checkin-list")

        f = self.response.forms['checkinform2']
        self.submit(f)
        self.assertTitle("Checkin (Große Testakademie 2222)")
        # cannot checkin twice
        self.submit(f, check_notification=False)
        self.assertNotification("Bereits eingecheckt.", "error")
        self.assertTitle("Checkin (Große Testakademie 2222)")
        self.assertPresence("Bertå (Bindi) Beispiel", div="checkin-list")
        # Emilia is now checked in and thus no longer appears.
        self.assertNonPresence("Emilia", div="checkin-list")
        self.assertNotIn('checkinform2', self.response.forms)
        if self.user_in("garcia"):
            # Check log
            self.traverse({'href': '/event/event/1/log'})
            self.assertPresence("Checkin", div=str(self.EVENT_LOG_OFFSET + 5) + "-1005")
            # single-part
            self.traverse("Veranstaltungen", "CyberTestAkademie", "Checkin")
            self.assertTitle("Checkin (CyberTestAkademie)")
            self.assertPresence("Daniel Dino")
            self.assertPresence("Olaf Olafson")
            f = self.response.forms['checkinform7']
            self.submit(f)
            self.assertTitle("Checkin (CyberTestAkademie)")
            self.assertNotIn('checkinform7', self.response.forms)
            # Check that checkin did not break registration editing.
            self.get('/event/event/3/registration/7/change')
            f = self.response.forms['changeregistrationform']
            self.submit(f)
            # Check log
            self.traverse({'href': '/event/event/3/log'})
            self.assertPresence("Checkin", div="1-1006")

    @event_keeper
    @as_users("garcia", "ludwig")
    def test_checkin_periods(self) -> None:
        self.get('/event/event/1/registration/6/show')
        self.assertTitle("Anmeldung von Bertå Beispiel (Große Testakademie 2222)")
        self.assertPresence("22.02.2022, 18:00:00 – 23.02.2022, 10:00:00")

        # Test checkin helper access
        if self.user_in("garcia"):
            self.assertPresence("Anreise")
        else:
            self.assertNonPresence("Anreise")
            self.traverse("Bearbeiten")
            f = self.response.forms['changeregistrationform']
            self.assertNonPresence("Anreise")
            self.submit(f)
            with self.switch_user("garcia"):
                self.get('/event/event/1/registration/6/show')
                self.assertPresence("22.02.2022, 15:00:00")

        base_time = now().replace(microsecond=0)
        delta = datetime.timedelta(seconds=42)
        # check adding future checkout times
        f = self.response.forms['changeperiodform1']
        f['checkout_time_1'] = "2222-02-01T10:00:00+01:00"
        self.submit(f, check_notification=False)
        self.assertValidationWarning(
            'checkout_time_1', "Sollte weniger als 6 Stunden in der Zukunft sein."
        )
        f = self.response.forms['changeperiodform1']
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)
        self.assertPresence("22.02.2022, 18:00:00 – 01.02.2222, 10:00:00")
        f = self.response.forms['changeperiodform1']
        f['checkout_time_1'] = "2022-02-23T10:00:00+01:00"
        self.submit(f)
        self.assertPresence("22.02.2022, 18:00:00 – 23.02.2022, 10:00:00")

        with freezegun.freeze_time(base_time) as frozen_time:
            self.assertNotIn('checkoutform', self.response.forms)
            # check Berta in
            f = self.response.forms['checkinform']
            self.submit(f)  # period id 1001
            self.submit(f, check_notification=False)
            self.assertNotification("Bereits eingecheckt.", "error")
            self.assertTitle("Anmeldung von Bertå Beispiel (Große Testakademie 2222)")
            frozen_time.tick(delta / 2)
            self.assertNotIn('checkinform', self.response.forms)
            # check Berta out again
            f = self.response.forms['checkoutform']
            self.submit(f)
            self.submit(f, check_notification=False)
            self.assertNotification("Bereits ausgecheckt.", "error")
            self.assertTitle("Anmeldung von Bertå Beispiel (Große Testakademie 2222)")

            # adding a backdated checkin period
            f = self.response.forms['addperiodform']
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time', "Muss ein valides Datum mit Uhrzeit sein."
            )
            f['checkin_time'] = "2022-02-22T00:00:00+01:00"
            self.submit(f, check_notification=False)
            self.assertValidationError('checkout_time', "Darf nicht leer sein.")
            f['checkin_time'] = "2022-02-22T00:00:00+01:00"
            f['checkout_time'] = "2022-02-23T00:00:00+01:00"
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkout_time', "Checkout muss vor folgendem Checkin sein."
            )
            f['checkin_time'] = "2022-02-23T00:00+01:00"
            f['checkout_time'] = "2022-02-22T18:00+01:00"
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time', "Checkin muss nach vorhergehendem Checkout sein."
            )
            self.assertValidationError(
                'checkout_time', "Checkout muss nach Checkin liegen."
            )
            f['checkin_time'] = "2222-02-23T00:00+01:00"
            f['checkout_time'] = "2222-02-22T18:00+01:00"
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time', "Muss in der Vergangenheit liegen."
            )
            self.assertValidationError(
                'checkout_time', "Checkout muss nach Checkin liegen."
            )
            f['checkin_time'] = "2022-03-03T18:00+01:00"
            f['checkout_time'] = "2022-03-04T10:00+01:00"
            self.submit(f)  # period id 1002
            self.assertPresence("03.03.2022, 18:00:00 – 04.03.2022, 10:00:00")
            frozen_time.tick(delta / 2)
            # adding a checkin via this form is possible
            f['checkin_time'] = base_time + delta / 4
            f['checkout_time'] = None
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time', "Checkin muss nach vorhergehendem Checkout sein."
            )
            f['checkin_time'] = base_time + delta
            f['checkout_time'] = None
            self.submit(f)  # period id 1003
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time', "Kann eingecheckte Nutzer nicht einchecken."
            )
            self.submit(self.response.forms['deleteperiodform1003'])

            # changing a checkin period
            f = self.response.forms['changeperiodform1']
            f['checkout_time_1'] = base_time + delta
            original_checkin = f['checkin_time_1'].value
            f['checkin_time_1'] = base_time + delta
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkout_time_1', "Checkout muss vor folgendem Checkin sein."
            )
            self.assertValidationError(
                'checkin_time_1', "Checkout muss nach Checkin liegen."
            )

            f = self.response.forms['changeperiodform1001']
            f['checkin_time_1001'] = "2000-01-01T00:00:00+02:00"
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'checkin_time_1001', "Checkin muss nach vorhergehendem Checkout sein."
            )

            f = self.response.forms['changeperiodform1']
            f['checkin_time_1'] = original_checkin
            f['checkout_time_1'] = "2022-02-28T10:00:00+01:00"
            with self.assertRaises(ValueError) as cm:
                f['period_id'] = 2
                self.submit(f, check_notification=False)
            self.assertEqual("Inconsistent data.", cm.exception.args[0])
            f['period_id'] = 1
            self.submit(f)
            self.assertPresence("22.02.2022, 18:00:00 – 28.02.2022, 10:00:00")
            self.submit(self.response.forms['deleteperiodform1'])
            self.assertNonPresence("22.02.2022, 18:00:00 – 28.02.2022, 10:00:00")

            # test multiset form
            url = "/event/event/1/registration/checkin/multiset"
            if self.user_in("ludwig"):
                self.get(url + "?registration_ids=1..6", status=403)
                return
            self.get(url + "?registration_ids=1..6")
            self.assertNotification("Validierung fehlgeschlagen.", "error")
            self.assertTitle("Anmeldungen (Große Testakademie 2222)")
            self.get(url + "?registration_ids=1,6")
            self.assertTitle(
                "Checkin-/Checkoutzeiten hinzufügen (Große Testakademie 2222)"
            )
            self.assertNonPresence("Auschecken")
            self.assertPresence("Einchecken")
            self.assertPresence("Anton Administrator Nie eingecheckt")
            self.assertPresence(
                f"Bertå Beispiel letzter Checkout"
                f" {datetime_filter(base_time + delta / 2, lang='de')}"
            )
            f = self.response.forms['checkinform']
            f['checkout_time'] = base_time + 2 * delta  # future
            self.submit(f, button='action', value='modify_checkout')
            self.assertTitle("Anmeldungen (Große Testakademie 2222)")
            self.assertPresence("Ergebnis [2]", div='query-results')
            self.assertPresence("Anton")
            self.assertPresence("Bertå")
            frozen_time.tick(delta)
            self.get(url + "?registration_ids=1,6")
            self.assertPresence("Anton Administrator Nie eingecheckt")
            self.assertPresence(
                f"Bertå Beispiel letzter Checkout"
                f" {datetime_filter(base_time + 2 * delta, lang='de')}"
            )
            old_f = f
            f = self.response.forms['checkinform']
            f['checkin_time'] = base_time + 3 * delta
            self.submit(f, button='action', value='checkin', check_notification=False)
            self.assertValidationError(
                "checkin_time", "Muss in der Vergangenheit liegen."
            )
            frozen_time.tick(delta)
            f['checkin_time'] = None
            self.submit(f, button='action', value='checkin', check_notification=False)
            self.assertValidationError(
                "checkin_time", "Genau eins muss angegeben werden."
            )
            f['checkin_time'] = base_time + delta
            self.submit(f, button='action', value='checkin', check_notification=False)
            self.assertValidationError(
                "checkin_time", "Muss nach dem letzten Checkout sein."
            )
            f['checkin_time'] = base_time + 3 * delta
            self.submit(f, button='action', value='checkin')
            self.assertTitle("Anmeldungen (Große Testakademie 2222)")
            self.assertPresence("Ergebnis [2]", div='query-results')
            self.assertPresence("Anton")
            self.assertPresence("Bertå")
            self.submit(
                old_f,
                button='action',
                value='modify_checkout',
                check_notification=False,
            )
            self.assertNotification("Personen dürfen nicht eingecheckt sein.")

            self.get(url)
            self.assertTitle(
                "Checkin-/Checkoutzeiten hinzufügen (Große Testakademie 2222)"
            )
            self.assertPresence("Auschecken")
            self.assertPresence(
                f"Anton Administrator anwesend seit"
                f" {datetime_filter(base_time + 3 * delta, lang='de')}"
            )
            self.assertPresence(
                f"Bertå Beispiel anwesend seit"
                f" {datetime_filter(base_time + 3 * delta, lang='de')}"
            )
            self.assertPresence("Einchecken")
            self.assertPresence("Emilia Eventis Nie eingecheckt")
            f = self.response.forms['checkoutform']
            self.assertEqual("1,6", f['registration_ids'].value)
            f['checkin_time'] = base_time
            self.submit(
                f, button='action', value='modify_checkin', check_notification=False
            )
            self.assertValidationError(
                "checkin_time", "Muss nach dem letzten Checkout sein."
            )
            f['checkin_time'] = base_time + 3 * delta
            self.submit(f, button='action', value='modify_checkin')
            self.assertTitle("Anmeldungen (Große Testakademie 2222)")
            self.assertPresence("Ergebnis [2]", div='query-results')
            self.assertPresence("Anton")
            self.assertPresence("Bertå")
            self.get(url)
            f = self.response.forms['checkoutform']
            f['checkout_time'] = None
            self.submit(f, button='action', value='checkout', check_notification=False)
            self.assertValidationError(
                "checkout_time", "Genau eins muss angegeben werden."
            )
            f['checkout_time'] = base_time + 2 * delta
            self.submit(f, button='action', value='checkout', check_notification=False)
            self.assertValidationError(
                "checkout_time", "Muss nach dem letzten Checkin sein."
            )
            f['checkout_time'] = base_time + 4 * delta  # in future
            self.submit(f, button='action', value='checkout')
            self.assertTitle("Anmeldungen (Große Testakademie 2222)")
            self.assertPresence("Ergebnis [2]", div='query-results')
            self.assertPresence("Anton")
            self.assertPresence("Bertå")
            frozen_time.tick(delta)
            self.submit(f, button='action', value='checkout', check_notification=False)
            self.assertNotification("Personen müssen eingecheckt sein", "error")

    @event_keeper
    @as_users("garcia")
    def test_checkin_multiset(self) -> None:
        # multiset from field is tested here, multiset from form input above
        url = "/event/event/1/registration/checkin/multiset"
        self.get(url)
        f = self.response.forms["checkinform"]
        f['field_id'] = 9
        f['checkin_time'] = "2022-02-02T20:22:00+02:00"
        self.submit(f, button='action', value='checkin', check_notification=False)
        self.assertValidationError("field_id", "Genau eins muss angegeben werden.")
        self.assertValidationError("checkin_time", "Genau eins muss angegeben werden.")
        f['checkin_time'] = None
        self.submit(f, button='action', value='checkin', check_notification=False)
        self.assertValidationError("field_id", "Muss nach dem letzten Checkout sein.")
        self.assertValidationError("field_id", "Feld darf nicht leer sein.")
        self.assertPresence("Akira Abukara Nie eingecheckt neuer Checkin: kein Eintrag")
        self.assertPresence(
            "Anton Administrator Nie eingecheckt neuer Checkin: 02.02.2022, 10:00:00"
        )
        self.assertPresence(
            "Bertå Beispiel letzter Checkout 23.02.2022, 10:00:00"
            " neuer Checkin: 22.02.2022, 15:00:00 (vor Checkout)"
        )
        self.get(url + '?registration_ids=1')
        f = self.response.forms["checkinform"]
        f['field_id'] = 9
        self.submit(f, button='action', value='checkin', check_notification=False)
        f = self.response.forms["checkinform"]
        f['ack_field'].checked = True
        self.submit(f, button='action', value='checkin')

        self.get(url + '?registration_ids=2')
        f = self.response.forms['checkinform']
        f['checkin_time'] = now().isoformat()
        self.submit(f, button='action', value='checkin')

        def _change_antons_arrival(timestamp: str) -> None:
            saved = self.response
            self.get('/event/event/1/registration/1/change')
            f = self.response.forms['changeregistrationform']
            f['fields.arrival_at'] = timestamp
            self.submit(f)
            self.response = saved

        _change_antons_arrival("2022-02-02T00:00:00+02:00")
        self.get(url)
        self.assertPresence("Anton Administrator anwesend seit")
        self.assertPresence("Emilia Eventis anwesend seit")
        f = self.response.forms['checkoutform']
        f['field_id'] = 9
        f['checkout_time'] = "2022-02-02T20:22:00+02:00"
        self.submit(f, button='action', value='checkout', check_notification=False)
        self.assertValidationError("field_id", "Genau eins muss angegeben werden.")
        self.assertValidationError("checkout_time", "Genau eins muss angegeben werden.")
        f['checkout_time'] = None
        self.submit(f, button='action', value='checkout', check_notification=False)
        self.assertValidationError("field_id", "Muss nach dem letzten Checkin sein.")
        self.assertValidationError("field_id", "Feld darf nicht leer sein.")
        _change_antons_arrival("2022-02-02T20:00:00+02:00")
        self.submit(f, button='action', value='checkout', check_notification=False)
        self.assertValidationError("field_id", "Feld darf nicht leer sein.")
        self.get(url + '?registration_ids=1')
        f = self.response.forms['checkoutform']
        f['field_id'] = 9
        self.submit(f, button='action', value='checkout', check_notification=False)
        f = self.response.forms['checkoutform']
        f['ack_field'].checked = True
        self.submit(f, button='action', value='checkout')

    @as_users("garcia")
    def test_manage_attendees(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie",
            "Kursliste",
            {'description': "Details", 'href': '/event/event/1/course/1/show'},
        )
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertNonPresence("Garcia", div='track1-attendees')
        self.assertPresence("0 + 0", div='track1-attendees')
        self.assertPresence("2 + 1", div='track3-attendees')
        # Check the attendees link in the footer.
        self.assertNonPresence("Kurswahlen Kursteilnehmende", div='track1-attendees')
        self.assertPresence("Inga", div='track3-attendees')

        self.traverse("Kursteilnehmende verwalten")
        self.assertTitle(
            "Kursteilnehmende für Kurs Planetenretten für Anfänger"
            " verwalten (Große Testakademie 2222)"
        )
        f = self.response.forms['manageattendeesform']
        f['new_1'] = "3"
        f['delete_3_4'] = True
        self.submit(f)

        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertPresence("Garcia", div='track1-attendees')
        self.assertPresence("Kursteilnehmende", div='track1-attendees')
        self.assertPresence("1 + 0", div='track1-attendees')
        self.assertPresence("Akira", div='track3-attendees')
        self.assertPresence("Emilia", div='track3-attendees')
        self.assertNonPresence("Inga", div='track3-attendees')
        self.assertPresence("1 + 1", div='track3-attendees')

        # Check the attendees link in the footer.
        self.assertPresence("Alle Kurswahlen", div='track3-attendees')
        self.assertPresence("Kursteilnehmende", div='track3-attendees')
        self.assertPresence("In Anmeldungsliste", div='track3-attendees')
        self.traverse({
            'description': "In Anmeldungsliste anzeigen",
            'linkid': "attendees-link-3",
        })
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [2]", div='query-results')
        self.assertPresence("Akira", div='result-container')
        self.assertPresence("Emilia", div='result-container')

        # check log
        self.traverse("Log")
        self.assertPresence(
            "Kursteilnehmer von Heldentum geändert.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "Kursteilnehmer von Heldentum geändert.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    @as_users("garcia")
    def test_manage_inhabitants(self) -> None:
        self.traverse(
            "Veranstaltungen", "Große Testakademie", "Unterkünfte", "Kalte Kammer"
        )
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Inga", div='inhabitants-3')
        self.assertPresence("Garcia", div='inhabitants-3')
        self.assertPresence("In Anmeldungsliste", div='inhabitants-3')
        self.assertPresence("Garcia", div='inhabitants-1')
        self.assertPresence("In Anmeldungsliste", div='inhabitants-1')
        self.assertNonPresence("Emilia", div='inhabitants')
        self.assertNonPresence("In Anmeldungsliste", div='inhabitants-2')
        self.assertNonPresence("nicht zugestimmt")
        self.traverse("Bewohner verwalten")
        self.assertTitle(
            "Bewohner der Unterkunft Kalte Kammer verwalten (Große Testakademie 2222)"
        )
        self.assertCheckbox(False, "is_camping_mat_3_3")
        self.assertCheckbox(True, "is_camping_mat_3_4")
        f = self.response.forms['manageinhabitantsform']
        f['new_1'] = ""
        f['delete_1_3'] = True
        f['new_2'] = ""
        f['new_3'].force_value(2)
        self.submit(f)
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Emilia", div='inhabitants-3')
        self.assertPresence("Garcia", div='inhabitants-3')
        self.assertPresence("Inga", div='inhabitants-3')

        # check the status of the camping mat checkbox was not overridden
        self.traverse("Bewohner verwalten")
        self.assertTitle(
            "Bewohner der Unterkunft Kalte Kammer verwalten (Große Testakademie 2222)"
        )
        self.assertCheckbox(False, "is_camping_mat_3_3")
        self.assertCheckbox(True, "is_camping_mat_3_4")
        # Override camping mat status
        f = self.response.forms['manageinhabitantsform']
        f['is_camping_mat_3_3'] = True
        f['is_camping_mat_3_4'] = False
        self.submit(f)
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence(
            "Garcia Generalis ist auf eine Isomatte eingeteilt, hat dem"
            " aber nicht zugestimmt.",
            div='inhabitants-3',
        )

        # Check inhabitants link
        self.traverse({
            'description': "In Anmeldungsliste anzeigen",
            'linkid': "inhabitants-link-3",
        })
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [3]", div='query-results')
        self.assertPresence("Emilia", div='result-container')
        self.assertPresence("Garcia", div='result-container')
        self.assertPresence("Inga", div='result-container')

        # check log
        self.traverse("Log")
        self.assertPresence(
            "Bewohner von Kalte Kammer geändert.",
            div=str(self.EVENT_LOG_OFFSET + 1) + "-1001",
        )
        self.assertPresence(
            "Bewohner von Kalte Kammer geändert.",
            div=str(self.EVENT_LOG_OFFSET + 2) + "-1002",
        )

    @as_users("garcia")
    def test_lodgements_swap_inhabitants(self) -> None:
        # check current inhabitants
        self.traverse(
            {'description': 'Veranstaltungen'},
            {'description': 'Große Testakademie 2222'},
            {'description': 'Unterkünfte'},
            {'description': 'Einzelzelle'},
            {'description': 'Bewohner verwalten'},
        )
        self.assertPresence('Akira', div='inhabitant-1-5')
        self.assertCheckbox(False, "is_camping_mat_1_5")
        self.assertPresence('Akira', div='inhabitant-2-5')
        self.assertCheckbox(False, "is_camping_mat_2_5")
        self.assertPresence('Emilia', div='inhabitant-2-2')
        self.assertCheckbox(False, "is_camping_mat_2_2")
        self.assertPresence('Emilia', div='inhabitant-3-2')
        self.assertCheckbox(False, "is_camping_mat_3_2")
        self.assertNonPresence('Garcia', div="inhabitants-1")
        self.assertNonPresence('Garcia', div="inhabitants-3")
        self.assertNonPresence('Inga', div="inhabitants-3")

        self.traverse(
            {'description': 'Unterkünfte'},
            {'description': 'Kalte Kammer'},
            {'description': 'Bewohner verwalten'},
        )
        self.assertPresence('Garcia', div='inhabitant-1-3')
        self.assertCheckbox(False, "is_camping_mat_1_3")
        self.assertPresence('Zur Zeit keine Bewohner eingeteilt.', div='inhabitants-2')
        self.assertPresence('Garcia', div='inhabitant-3-3')
        self.assertCheckbox(False, "is_camping_mat_3_3")
        self.assertPresence('Inga', div='inhabitant-3-4')
        self.assertCheckbox(True, "is_camping_mat_3_4")
        self.assertNonPresence('Akira', div='inhabitants-1')
        self.assertNonPresence('Emilia', div="inhabitants-3")

        # swap inhabitants of both lodgements in part 1 and 3
        f = self.response.forms['swapinhabitantsform']
        f['swap_with_1'] = 4
        f['swap_with_3'] = 4
        self.submit(f)

        # check the inhabitants of both lodgements
        self.traverse(
            {'description': 'Unterkünfte'},
            {'description': 'Einzelzelle'},
            {'description': 'Bewohner verwalten'},
        )
        self.assertPresence('Garcia', div='inhabitant-1-3')
        self.assertCheckbox(False, "is_camping_mat_1_3")
        self.assertPresence('Akira', div='inhabitant-2-5')
        self.assertCheckbox(False, "is_camping_mat_2_5")
        self.assertPresence('Emilia', div='inhabitant-2-2')
        self.assertCheckbox(False, "is_camping_mat_2_2")
        self.assertPresence('Garcia', div='inhabitant-3-3')
        self.assertCheckbox(False, "is_camping_mat_3_3")
        self.assertPresence('Inga', div='inhabitant-3-4')
        self.assertCheckbox(True, "is_camping_mat_3_4")
        self.assertNonPresence('Akira', div="inhabitants-1")
        self.assertNonPresence('Emilia', div="inhabitants-3")

        self.traverse(
            {'description': 'Unterkünfte'},
            {'description': 'Kalte Kammer'},
            {'description': 'Bewohner verwalten'},
        )
        self.assertPresence('Akira', div='inhabitant-1-5')
        self.assertCheckbox(False, "is_camping_mat_1_5")
        self.assertPresence('Zur Zeit keine Bewohner eingeteilt.', div='inhabitants-2')
        self.assertPresence('Emilia', div='inhabitant-3-2')
        self.assertCheckbox(False, "is_camping_mat_3_2")
        self.assertNonPresence('Garcia', div="inhabitants-1")
        self.assertNonPresence('Garcia', div="inhabitants-3")
        self.assertNonPresence('Inga', div="inhabitants-3")

        # check log
        self.get('/event/event/1/log')
        change_note = (
            "Bewohner von Kalte Kammer und Einzelzelle für Warmup getauscht, "
            "Bewohner von Kalte Kammer und Einzelzelle für Zweite Hälfte getauscht."
        )
        self.assertPresence(change_note, div=str(self.EVENT_LOG_OFFSET + 1) + "-1001")
        self.assertPresence(change_note, div=str(self.EVENT_LOG_OFFSET + 2) + "-1002")
        self.assertPresence(change_note, div=str(self.EVENT_LOG_OFFSET + 3) + "-1003")
        self.assertPresence(change_note, div=str(self.EVENT_LOG_OFFSET + 4) + "-1004")

    @event_keeper
    @as_users("annika", "garcia")
    def test_lock_unlock_event(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Sperrt die Veranstaltung vorübergehend")
        f = self.response.forms["lockeventform"]
        self.submit(f)
        self.assertPresence("Die Veranstaltung ist vorübergehend gesperrt")
        f = self.response.forms['unlockeventform']
        self.submit(f)
        self.assertPresence("Sperrt die Veranstaltung vorübergehend")

    @storage
    @event_keeper
    @as_users("annika", "garcia")
    def test_partial_import_normal(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/download'},
            {'href': '/event/event/1/import'},
        )
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        with open(self.testfile_dir / "partial_event_import.json", 'rb') as datafile:
            data = datafile.read()
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload(
            "partial_event_import.json", data, "application/octet-stream"
        )
        self.submit(f, check_notification=False)
        # Check diff
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        # Registrations
        self.assertPresence("Emilia", div="box-changed-registrations")
        self.assertPresence("2.H.: Unterkunft", div="box-changed-registrations")
        self.assertPresence("Warme Stube", div="box-changed-registrations")
        self.assertPresence("brings_balls", div="box-changed-registration-fields")
        self.assertPresence("Notizen", div="box-changed-registration-fields")
        self.assertPresence("2.H.: Unterkunft", div="box-changed-registration-fields")
        self.assertPresence(
            "Morgenkreis: Kurswahlen", div="box-changed-registration-fields"
        )
        self.assertNonPresence(
            "Sitzung: Kursleitende", div="box-changed-registration-fields"
        )
        self.assertNonPresence("Inga", div="box-changed-registrations")
        self.assertPresence("Charly", div="box-new-registrations")
        self.assertPresence("Akira", div="box-deleted-registrations")
        # Courses
        self.assertPresence("α.", div="box-changed-courses")
        self.assertPresence("GanzKurz", div="box-changed-courses")
        self.assertPresence("Kaffee: Status", div="box-changed-courses")
        self.assertPresence("nicht angeboten", div="box-changed-courses")
        self.assertPresence("fällt aus", div="box-changed-courses")
        self.assertPresence("room", div="box-changed-courses")
        self.assertPresence("room", div="box-changed-course-fields")
        self.assertPresence("Sitzung: Status", div="box-changed-courses")
        self.assertPresence("Max.-Größe", div="box-changed-course-fields")
        self.assertPresence("ζ.", div="box-new-courses")
        self.assertPresence("γ.", div="box-deleted-courses")
        # Lodgements
        self.assertPresence("Kalte Kammer", div="box-changed-lodgements")
        self.assertPresence("contamination", div="box-changed-lodgements")
        self.assertPresence("Bezeichnung", div="box-changed-lodgement-fields")
        self.assertPresence("Wirklich eng.", div="box-changed-lodgements")
        self.assertPresence("Dafür mit Frischluft.", div="box-changed-lodgements")
        self.assertPresence("Geheimkabinett", div="box-new-lodgements")
        self.assertPresence("Kellerverlies", div="box-deleted-lodgements")
        # Lodgement Groups
        self.assertPresence("Geheime Etage", div="list-new-lodgement-groups")

        # Do import
        f = self.response.forms["importexecuteform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")

        # Check that changes have acutally been applied (at least for some)
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.assertNonPresence("Kellerverlies")
        self.assertPresence("Geheime Etage")
        self.assertPresence("Geheimkabinett")

    @storage
    @event_keeper
    @as_users("annika", "garcia")
    def test_partial_import_interleaved(self) -> None:
        self.get('/event/event/1/import/partial')
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        with open(self.testfile_dir / "partial_event_import.json", 'rb') as datafile:
            data = datafile.read()
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload(
            "partial_event_import.json", data, "application/octet-stream"
        )
        self.submit(f, check_notification=False)
        saved = self.response
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        f = self.response.forms["importexecuteform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.response = saved
        f = self.response.forms["importexecuteform"]
        self.submit(f, check_notification=False)
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        self.assertPresence("doppelte Löschungen von Anmeldungen", div="notifications")
        self.assertPresence("doppelte Löschungen von Kursen", div="notifications")
        self.assertPresence("doppelte Löschungen von Unterkünften", div="notifications")
        self.assertPresence("doppelt erstellte Kurse", div="notifications")
        self.assertPresence("doppelt erstellte Unterkünfte", div="notifications")

    @as_users("annika")
    def test_delete_event(self) -> None:
        self.get("/event/event/1/part/summary")
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        past_date = now().date() - datetime.timedelta(days=1)
        past_past_date = now().date() - datetime.timedelta(days=2)

        # Warmup
        self.traverse({"href": "/event/event/1/part/1/change"})
        f = self.response.forms['changepartform']
        f['part_begin'] = past_past_date
        f['part_end'] = past_date
        self.submit(f)

        # Erste Hälfte
        self.traverse({"href": "/event/event/1/part/2/change"})
        f = self.response.forms["changepartform"]
        f['part_begin'] = past_past_date
        f['part_end'] = past_date
        self.submit(f)

        # Zweite Hälfte
        self.traverse({"href": "/event/event/1/part/3/change"})
        f = self.response.forms['changepartform']
        f['part_begin'] = past_past_date
        f['part_end'] = past_date
        self.submit(f)

        # Check that there are logs for this event
        log_expectation = [
            {
                'change_note': "Warmup",
                'code': const.EventLogCodes.part_changed,
                'event_id': 1,
            },
            {
                'change_note': "Erste Hälfte",
                'code': const.EventLogCodes.part_changed,
                'event_id': 1,
            },
            {
                'change_note': "Zweite Hälfte",
                'code': const.EventLogCodes.part_changed,
                'event_id': 1,
            },
        ]
        self.assertLogEqual(
            log_expectation, realm="event", offset=self.EVENT_LOG_OFFSET
        )

        # Delete the event
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        f = self.response.forms['deleteeventform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungen")
        self.assertNonPresence("Testakademie")

        # Check that all old logs are deleted and there is only a deletion log entry
        log_expectation = [
            {
                'change_note': "Große Testakademie 2222",
                'code': const.EventLogCodes.event_deleted,
                'event_id': None,
            },
        ]
        self.assertLogEqual(log_expectation, realm="event")

        # since annika is no member, she can not access the past events
        self.logout()
        self.login(USER_DICT['berta'])
        self.traverse("Mitglieder", "Verg. Veranstaltungen")
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertNonPresence("Testakademie")

    @as_users("annika", "garcia", maintain_data=True)
    def test_selectregistration(self) -> None:
        self.get(
            '/event/registration' + '/select?kind=orga_registration&phrase=emil&aux=1'
        )
        expectation = {
            'registrations': [
                {
                    'email': 'emilia@example.cde',
                    'id': 2,
                    'name': 'Emilia (Emmy) Eventis',
                }
            ]
        }
        self.assertEqual(expectation, self.response.json)
        self.get(
            '/event/registration' + '/select?kind=orga_registration&phrase=@exam&aux=1'
        )
        expectation = (5, 1, 6, 2, 3, 4)
        reality = tuple(e['id'] for e in self.response.json['registrations'])
        self.assertEqual(expectation, reality)

    @as_users("annika", "garcia", "ludwig")
    def test_quick_registration(self) -> None:
        self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "Emilia"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")
        self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'})
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "i a"
        self.submit(f)
        if self.user_in("ludwig"):
            self.assertTitle("Große Testakademie 2222")
            self.assertNotification(ntype='warning')
            return
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        # TODO who knows if this is correct...
        self.assertPresence("Ergebnis [4]")
        self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'})
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "DB-5-1"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia Eventis (Große Testakademie 2222)")

    @storage
    @as_users("annika", "garcia", maintain_data=True)
    def test_partial_export(self) -> None:
        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/download'},
        )
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/download/partial'})
        result = json.loads(self.response.text)
        reference_export_file = self.testfile_dir / "TestAka_partial_export_event.json"
        with open(reference_export_file, encoding="utf-8") as f:
            expectation = json.load(f)
        expectation['timestamp'] = result['timestamp']
        for reg_id, reg in result['registrations'].items():
            expectation['registrations'][reg_id]['ctime'] = reg['ctime']
            expectation['registrations'][reg_id]['mtime'] = reg['mtime']
        for token_id, token in expectation['event']['orga_tokens'].items():
            token['ctime'] = result['event']['orga_tokens'][token_id]['ctime']
        self.assertEqual(expectation, result)

        # ensure stable sorting of the export file
        ref_export_lines = reference_export_file.read_text().splitlines()
        expected_lines = [
            ln
            for ln in ref_export_lines
            if not ("ctime" in ln or "mtime" in ln or "timestamp" in ln)
        ]
        exported_lines = [
            ln
            for ln in self.response.text.splitlines()
            if not ("ctime" in ln or "mtime" in ln or "timestamp" in ln)
        ]
        self.assertEqual("\n".join(expected_lines), "\n".join(exported_lines))

    @event_keeper
    @as_users("annika", "garcia")
    def test_partial_idempotency(self) -> None:
        self.get('/event/event/1/download')
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/download/partial'})
        first = json.loads(self.response.text)

        upload = copy.deepcopy(first)
        self.get('/event/event/1/import/partial')
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload(
            "partial_event_import.json",
            json.dumps(upload).encode('utf-8'),
            "application/octet-stream",
        )
        self.submit(f, check_notification=False)
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        f = self.response.forms["importexecuteform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")

        self.traverse(
            {'href': '/event/event/1/download'},
            {'href': '/event/event/1/download/partial'},
        )
        second = json.loads(self.response.text)
        del first['timestamp']
        del second['timestamp']
        self.assertEqual(first, second)

    @event_keeper
    @as_users("ferdinand")
    def test_archive(self) -> None:
        #
        # prepare dates
        #
        self.get('/event/event/1/part/summary')
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")

        # Warmup
        self.traverse({"href": "/event/event/1/part/1/change"})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-02-02"
        f['part_end'] = "2003-02-02"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")

        # Erste Hälfte
        self.traverse({"href": "/event/event/1/part/2/change"})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-11-01"
        f['part_end'] = "2003-11-11"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")

        # Zweite Hälfte
        self.traverse({"href": "/event/event/1/part/3/change"})
        f = self.response.forms["changepartform"]
        f['part_begin'] = "2003-11-11"
        f['part_end'] = "2003-11-30"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")

        # prepare courses to check if archival logic works
        self.traverse("Kurse", "Extra", "Bearbeiten")
        f = self.response.forms["configurecourseform"]
        f["segment2.is_active"].checked = False
        self.submit(f)
        self.assertTitle("Kurs Extra (Große Testakademie 2222)")

        # do it
        self.traverse("Übersicht")
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        # checkbox to create a past event is checked by default
        self.submit(f)
        mail = self.fetch_mail_content()
        self.assertIn("Große Testakademie 2222\nwurde archiviert", mail)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence(
            "Diese Veranstaltung wurde archiviert.", div="static-notifications"
        )
        self.assertNotIn("archiveeventform", self.response.forms)

        # check created past events (there are three, one per part)
        # use Anton, since Ferdinand didn't participate
        with self.switch_user("anton"):
            # Warmup has no courses, but participants and orgas
            self.traverse(
                "Mitglieder",
                "Verg. Veranstaltungen",
                r"Große Testakademie 2222 \(Warmup\)",
            )
            self.assertPresence("Kurse [0]")
            self.assertPresence("Akira Abukara")
            # not registered
            self.assertNonPresence("Anton")
            self.assertPresence("Bertå (Bindi) Beispiel")
            # waitlist
            self.assertNonPresence("Emilia")
            self.assertPresence("Garcia Generalis (Orga)")
            # rejected
            self.assertNonPresence("Inga")

            # Erste Hälfte has some courses (had two course tracks)
            self.traverse(
                "Mitglieder",
                "Verg. Veranstaltungen",
                r"Große Testakademie 2222 \(Erste Hälfte\)",
            )
            # cancelled in one of the two tracks, but still present since it was not cancelled in both
            self.assertPresence("β. Lustigsein für Fortgeschrittene")
            # only offerred in one track
            self.assertPresence("γ. Kurzer Kurs")
            # cancelled in an other course track
            self.assertPresence("ε. Backup-Kurs")
            # cancelled in both tracks
            self.assertNonPresence("ζ. Extra-Kurs")
            # check participants
            self.assertPresence("Akira Abukara (β. Lustigsein für Fortgeschrittene)")
            # applied
            self.assertNonPresence("Anton")
            # not applied
            self.assertNonPresence("Bertå")
            # guest
            self.assertNonPresence("Emilia")
            self.assertPresence(
                "Garcia Generalis (β. Lustigsein für Fortgeschrittene) (Orga)"
            )
            # cancelled
            self.assertNonPresence("Inga")

            # Zweite Hälfte has some courses (had one course tracks)
            self.traverse(
                "Mitglieder",
                "Verg. Veranstaltungen",
                r"Große Testakademie 2222 \(Zweite Hälfte\)",
            )
            # has some participants
            self.assertPresence("α. Planetenretten für Anfänger")
            # not offerred in this course track
            self.assertNonPresence("γ. Kurzer Kurs")
            # cancelled in this course track
            self.assertNonPresence("ε. Backup-Kurs")
            # only cancelled in the other course tracks, not in this one
            self.assertPresence("ζ. Extra-Kurs")
            # check participants
            self.assertPresence("Akira Abukara (α. Planetenretten für Anfänger)")
            self.assertPresence("Anton Administrator")
            # not applied
            self.assertNonPresence("Bertå")
            self.assertPresence(
                "Emilia (Emmy) Eventis (α. Planetenretten für Anfänger (Kursleitung))"
            )
            self.assertPresence("Garcia Generalis (Orga)")
            self.assertPresence("Inga Iota")

        # check log
        self.get("/event/event/1/log")
        self.assertPresence("Veranstaltung archiviert")
        # TODO check past event log

        # Check that questionnaire is readonly
        self.traverse({'href': '/event/event/1/questionnaire/config'})
        f = self.response.forms['configurequestionnaireform']
        self.assertTrue(f['readonly_2'].checked)
        self.assertTrue(f['readonly_5'].checked)
        self.assertTrue(f['readonly_6'].checked)

        # Check visibility but un-modifiability for participants
        self.logout()
        self.login(USER_DICT["emilia"])
        self.get("/event/event/1/show")
        self.assertPresence(
            "Diese Veranstaltung wurde archiviert.", div="static-notifications"
        )
        self.traverse("Meine Anmeldung")
        self.assertNonPresence("Bearbeiten")
        self.get("/event/event/1/registration/amend")
        self.assertPresence(
            "Veranstaltung ist bereits archiviert.", div="notifications"
        )

    @event_keeper
    @as_users("anton")
    def test_archive_without_past_event(self) -> None:
        self.traverse("Veranstaltungen", "CdE-Party 2050")
        self.assertTitle("CdE-Party 2050")

        # cancel
        self.traverse("Konfiguration")
        f = self.response.forms["changeeventform"]
        f['is_cancelled'] = True
        self.submit(f)

        # try with past event even though there are no participants
        self.traverse(r"\sÜbersicht")
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        f['create_past_event'].checked = True
        self.submit(f, check_notification=False)
        self.assertNotification(
            "Keine Veranstaltungsteile haben Teilnehmende.", 'error'
        )

        # do it
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        f['create_past_event'].checked = False
        self.submit(f)

        self.assertTitle("CdE-Party 2050")
        self.assertPresence(
            "Diese Veranstaltung wurde abgesagt und archiviert.",
            div="static-notifications",
        )

        # check that there is no past event
        self.traverse("Mitglieder", "Verg.-Veranstaltungen")
        self.assertNonPresence("CdE-Party 2050")

    @event_keeper
    @as_users("anton")
    def test_archive_event_purge_persona(self) -> None:
        self.traverse("Veranstaltungen", "Alle Veranstaltungen", "CyberTestAkademie")
        self.assertTitle("CyberTestAkademie")
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        f['create_past_event'].checked = True
        self.submit(f)

        # now, archive and purge a participant
        self.realm_admin_view_profile("daniel", "cde")
        self.assertTitle("Daniel Dino")
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Daniel Dino")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        f = self.response.forms['purgepersonaform']
        f['ack_delete'].checked = True
        with self.assertRaises(RuntimeError):
            self.submit(f)
        execsql(
            f"DELETE FROM {ComplaintInvolved.database_table} WHERE persona_id = 4", 1
        )
        self.submit(f)
        self.assertTitle("N. N.")
        self.assertPresence("Der Benutzer wurde geleert.", div='purged')

        # now, test if the event is still working
        self.traverse(
            "Veranstaltungen", "Alle Veranstaltungen", "CyberTestAkademie", "Statistik"
        )
        self.assertTitle("Statistik (CyberTestAkademie)")
        self.get('/event/event/3/registration/7/show')
        self.assertTitle("Anmeldung von N. N. (CyberTestAkademie)")
        self.assertNonPresence("Daniel")

    @as_users("annika")
    def test_one_track_no_courses(self) -> None:
        self.traverse("Veranstaltungen", "Alle Veranstaltungen", "CdE-Party 2050")
        # Check if course list is present (though we have no course track)
        self.assertNonPresence('/event/event/2/course/list', div="sidebar")
        self.assertNonPresence('/event/event/2/course/stats', div="sidebar")

        # Add course track
        self.traverse("Konfiguration", "Veranstaltungsteile")
        self.traverse({"href": "/event/event/2/part/4/change"})
        f = self.response.forms['changepartform']
        f['track_create_-1'].checked = True
        f['track_title_-1'] = "Chillout Training"
        f['track_shortname_-1'] = "Chill"
        f['track_num_choices_-1'] = "1"
        f['track_min_choices_-1'] = "1"
        f['track_sortkey_-1'] = "1"
        self.submit(f)

        # Add registration
        self.traverse("Anmeldungen", "Anmeldung hinzufügen")
        # We have only one part, thus it should not be named
        self.assertNonPresence('Partywoche')
        # We have only one track, thus it should not be named
        self.assertNonPresence('Chillout')
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-7"
        f['part4.status'] = const.RegistrationPartStati.applied
        self.submit(f)
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse('Bearbeiten')
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.get("/event/event/2/registration/multiedit?reg_ids=1001")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

        # Check course related pages for errors
        self.traverse("Kursliste")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse("Kurse")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse("Kurseinteilung")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

    @as_users("charly", "daniel", maintain_data=True)
    def test_free_event(self) -> None:
        # first, make Große Testakademie 2222 free
        with self.switch_user("garcia"):
            self.traverse(
                "Veranstaltungen", "Große Testakademie 2222", "Teilnahmebeiträge"
            )
            for fee_id, fee in self.event.get_event(self.key, 1).fees.items():
                if fee.title == "Externenzusatzbeitrag":
                    continue
                f = self.response.forms[f'deleteeventfeeform{fee_id}']
                self.submit(f)

        pay_request = "Anmeldung erst mit Überweisung des Teilnahmebeitrags"
        iban = iban_filter(Accounts.Sozialbank.get_iban())

        # now check ...
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Anmelden")
        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['track3.course_choice_0'] = 2
        f['track3.course_choice_1'] = 2
        f['track3.course_choice_1'] = 4
        self.submit(f)

        text = self.fetch_mail_content()

        # ... the registration mail ...
        # ... as member
        if self.user_in('charly'):
            self.assertNotIn(pay_request, text)
            self.assertNotIn(iban, text)
        # ... as not member (we still need to pay the no member surcharge)
        else:
            self.assertIn(pay_request, text)
            self.assertIn(iban, text)

        # ... the registration page ...
        # ... as member
        if self.user_in('charly'):
            self.assertNotIn(pay_request, text)
            self.assertNotIn(iban, text)
        # ... as not member (we still need to pay the no member surcharge)
        else:
            self.assertIn(pay_request, text)
            self.assertIn(iban, text)

    @as_users("garcia")
    def test_no_choices(self) -> None:
        """This is a regression test for #1224, #1271 and #1395."""
        # set all choices in all tracks to 0
        self.get("/event/event/1/part/2/change")
        f = self.response.forms['changepartform']
        f['track_num_choices_1'] = 0
        f['track_min_choices_1'] = 0
        f['track_num_choices_2'] = 0
        f['track_min_choices_2'] = 0
        self.submit(f)
        self.traverse({"href": "/event/event/1/part/3/change"})
        f = self.response.forms['changepartform']
        f['track_num_choices_3'] = 0
        f['track_min_choices_3'] = 0

        self.traverse("Anmeldungen")
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.traverse("Kurse", "Kurssuche")
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)

    @event_keeper
    @as_users("anton")
    def test_archived_participant(self) -> None:
        self.traverse(
            "Veranstaltungen", "CdE-Party", "Anmeldungen", "Anmeldung hinzufügen"
        )
        # add charly as participant with list consent
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = USER_DICT["charly"]["DB-ID"]
        f["part4.status"] = const.RegistrationPartStati.participant
        f["reg.list_consent"].checked = True
        self.submit(f)

        # adjust dates
        self.get("/event/event/2/part/4/change")
        f = self.response.forms["changepartform"]
        f["part_begin"] = now().date() - datetime.timedelta(days=1)
        f["part_end"] = now().date() - datetime.timedelta(days=1)
        self.submit(f)

        # archive the event
        self.traverse(r"\sÜbersicht")
        f = self.response.forms["archiveeventform"]
        f["ack_archive"].checked = True
        self.submit(f)
        self.assertTitle("CdE-Party 2050")
        self.assertPresence("Charly")

        self.traverse("Veranstaltungen", "CdE-Party 2050", "Teilnehmerliste")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Charly")

        # archive charly
        self.admin_view_profile("charly")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "For testing."
        f["ack_delete"].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Unausgeglichener Veranstaltungs-Kontostand", div="notifications"
        )
        execsql(
            "UPDATE event.registrations SET amount_paid = 15.00"
            " WHERE persona_id = 3 AND event_id = 2;"
        )
        f = self.response.forms["archivepersonaform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertPresence("CdE-Party 2050")

        self.traverse("Veranstaltungen", "CdE-Party 2050", "Teilnehmerliste")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Charly")

        # purge charly
        self.admin_view_profile("charly")
        f = self.response.forms["purgepersonaform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertNonPresence("CdE-Party 2050")

        self.traverse("Veranstaltungen", "CdE-Party 2050", "Teilnehmerliste")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertNonPresence("Charly")
        self.assertPresence("N. N.")

    @storage
    @as_users("garcia")
    def test_questionnaire_import(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Fragebogen konfigurieren",
            "Fragebogenimport",
        )
        self.assertTitle("Fragebogenimport zur Veranstaltung Große Testakademie 2222")
        with open(self.testfile_dir / "questionnaire_import.json", 'rb') as datafile:
            data = json.load(datafile)

        def create_upload(data: CdEDBObject) -> webtest.Upload:
            return webtest.Upload(
                "questionnaire_import.json",
                json.dumps(data).encode(),
                "application/octet-stream",
            )

        # First: Try importing only the questionnaire.
        f = self.response.forms["importform"]
        f['json_file'] = create_upload({'questionnaire': data['questionnaire']})
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Unbekannter Datenfeldname: 'KleidungAnmerkungen'",
            div="importerrorsummary",
        )

        # Second: Try importing only the fields. This should work.
        f['json_file'] = create_upload({'fields': data['fields']})
        self.submit(f)

        # Try submitting the same import again.
        self.assertEqual(f['skip_existing_fields'].checked, False)
        self.submit(f, check_notification=False)
        self.assertPresence(
            "fields[KleidungAnmerkungen]: Es existiert bereits ein Datenfeld mit diesem Namen.",
            div="importerrorsummary",
        )
        f['skip_existing_fields'].checked = True
        self.submit(f)

        # Third: Try to import the questionnaire again. This should now work.
        f['json_file'] = create_upload({'questionnaire': data['questionnaire']})
        self.submit(f)

        # Try resubmitting:
        self.assertEqual(f['extend_questionnaire'].checked, True)
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Felder dürfen nicht doppelt auftreten: 'KleidungAnmerkungen'.",
            div="importerrorsummary",
        )
        f['extend_questionnaire'].checked = False
        self.submit(f)

        # Fourth: Try submitting the entire thing.
        f['json_file'] = create_upload(data)
        self.submit(f)
        # This only works because we configured the checkboxes accordingly.
        self.traverse("Fragebogen konfigurieren", "Fragebogenimport")
        f = self.response.forms["importform"]
        f['json_file'] = create_upload(data)
        self.submit(f, check_notification=False)
        self.assertPresence(
            "fields[KleidungAnmerkungen]: Es existiert bereits ein Datenfeld mit diesem Namen.",
            div="importerrorsummary",
        )
        self.assertPresence(
            "Felder dürfen nicht doppelt auftreten: 'KleidungAnmerkungen'.",
            div="importerrorsummary",
        )

        # Fifth: Reset Questionnaire and fields and try the full import again:
        self.event.set_questionnaire(
            self.key, 1, const.QuestionnaireUsages.additional, []
        )
        event = self.event.get_event(self.key, 1)
        self.event.set_event(
            self.key,
            1,
            {
                'fields': {id_: None for id_ in event.fields if id_ > 1000},
            },
        )

        self.submit(f)

        # Sixth: Compare the questionnaire export to the import file:
        with self.switch_user("annika"):
            self.traverse(
                "Veranstaltungen",
                "TripelAkademie",
                "Fragebogen konfigurieren",
                "Fragebogenimport",
            )
            f = self.response.forms["importform"]
            f["json_file"] = create_upload(data)
            self.submit(f)
            self.traverse("Downloads & Import", {"href": "/download/questionnaire"})
            export = json.loads(self.response.text)
            del export["questionnaire"][str(const.QuestionnaireUsages.registration)]
            self.assertEqual(data, export)
            self.get("/")

    @as_users("emilia")
    def test_part_groups(self) -> None:
        event_id = 4
        event = self.event.get_event(self.key, event_id)
        log_expectation = []
        offset = self.event.retrieve_log(self.key, EventLogFilter(event_id=event_id))[0]

        self.get(f'/event/event/{event_id}/part/summary')
        self.traverse("Gruppen")
        self.assertTitle("Gruppen (TripelAkademie)")

        # Check summary display.
        for pg_id, pg in event.part_groups.items():
            div = f"partgroup_{pg_id}"
            self.assertPresence(pg.title, div=div)
            self.assertPresence(pg.shortname, div=div)
            for part_id, part in event.parts.items():
                if part_id in pg.parts:
                    self.assertPresence(part.shortname, div=div)
                else:
                    self.assertNonPresence(part.shortname, div=div)

        # Create new part group:
        self.traverse("Veranstaltungsteilgruppe hinzufügen")
        self.assertTitle("Veranstaltungsteilgruppe hinzufügen (TripelAkademie)")
        f = self.response.forms['configurepartgroupform']
        f['title'] = ""
        f['shortname'] = ""
        f['constraint_type'] = const.EventPartGroupType.Statistic
        f['part_ids'] = list(event.parts.keys())
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('title', "Darf nicht leer sein.")
        self.assertValidationError('shortname', "Darf nicht leer sein.")
        f['title'] = new_title = "Everything"
        f['shortname'] = new_shortname = "all"
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.part_group_created,
            'change_note': new_title,
        })
        log_expectation.extend([
            {
                'code': const.EventLogCodes.part_group_link_created,
                'change_note': part.title + " -> " + new_title,
            }
            for part_id, part in xsorted(event.parts.items())
        ])
        # TODO: How to force value into multiple checkboxes?
        # f['part_ids'].force_value([10 ** 10])
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'title',
            "Es existiert bereits eine Veranstaltungsteilgruppe mit diesem Namen.",
        )
        self.assertValidationError(
            'shortname',
            "Es existiert bereits eine Veranstaltungsteilgruppe mit diesem Namen.",
        )
        # self.assertValidationError('part_ids', "Unbekannter Veranstaltungsteil")

        new_id = max(self.event.get_event(self.key, event_id).part_groups)
        self.traverse("Gruppen")
        self.assertPresence(new_title, div=f"partgroup_{new_id}")
        self.assertPresence(new_shortname, div=f"partgroup_{new_id}")

        # Check part group badges.
        self.traverse("Veranstaltungsteile")
        for part_id, part in event.parts.items():
            div = f"part{part_id}_partgroups"
            self.assertPresence(new_shortname, div=div)
            for pg_id, pg in event.part_groups.items():
                if part_id in pg.parts:
                    self.assertPresence(pg.shortname, div=div)
                else:
                    self.assertNonPresence(pg.shortname, div=div)

        # Change the new part group.
        self.traverse("Gruppen", {'linkid': f'partgroup{new_id}_change'})
        f = self.response.forms['configurepartgroupform']

        # Check that constraint_type and part_ids fields are disabled.
        self.assertNotIn('constraint_type', f.fields)
        for field in f.fields.get('part_ids'):
            self.assertEqual(field.attrs, {'type': 'hidden'})

        # Submit garbage.
        f['title'] = ""
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('title', "Darf nicht leer sein.")
        f['title'] = "placeholder"
        f['shortname'] = list(event.part_groups.values())[0].shortname
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError(
            'shortname',
            "Es existiert bereits eine Veranstaltungsteilgruppe mit diesem Namen.",
        )

        # Submit real stuff.
        f['title'] = new_title[::-1]
        f['shortname'] = new_shortname[::-1]
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.part_group_changed,
            'change_note': new_title[::-1],
        })
        self.assertNonPresence(new_title, div=f"partgroup_{new_id}")
        self.assertPresence(new_title[::-1], div=f"partgroup_{new_id}")
        self.assertNonPresence(new_shortname, div=f"partgroup_{new_id}")
        self.assertPresence(new_shortname[::-1], div=f"partgroup_{new_id}")

        # Check that resubmitting works but changes nothing.
        self.submit(f)

        self.traverse("Statistik")
        self.assertPresence(new_shortname[::-1], div="participant-stats")

        # Delete the new part group.
        self.traverse("Veranstaltungsteile", "Gruppen")
        f = self.response.forms[f'deletepartgroupform{new_id}']
        self.submit(f)
        log_expectation.append({
            'code': const.EventLogCodes.part_group_deleted,
            'change_note': new_title[::-1]
            + f" ({const.EventPartGroupType.Statistic.name})",
        })
        self.assertNonPresence(new_title[::-1], div="part-group-summary")

        self.traverse("Veranstaltungsteile")
        for part_id, part in event.parts.items():
            div = f"part{part_id}_partgroups"
            self.assertNonPresence(new_shortname, div=div)
            self.assertNonPresence(new_shortname[::-1], div=div)

        self.assertLogEqual(
            log_expectation, realm="event", event_id=event_id, offset=offset
        )

    @unittest.skip("deprecated test")
    def test_log(self) -> None:
        # TODO This is a big anti-pattern for log tests. Logs shall be checked inline.
        #  This is comment-out to avoid annoying test fails.

        # The following calls to other test methods do not work as intended, since
        # a test method with multiple `as_users` resets intermediate database state.
        # First: generate data
        self.test_register()
        self.logout()
        self.test_create_delete_course()
        self.logout()
        self.test_create_event()
        self.logout()
        self.test_lodgements()
        self.logout()
        self.test_add_empty_registration()
        self.logout()

        # Now check it
        self.login(USER_DICT['annika'])
        self.traverse({'href': '/event/$'}, {'href': '/event/log'})
        self.assertTitle("Veranstaltungen-Log [1–17 von 17]")
        self.assertNonPresence("LogCodes")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 27, 51]
        f['event_id'] = 1
        self.submit(f)
        self.assertTitle("Veranstaltungen-Log [1–1 von 1]")

        self.traverse(
            {'href': '/event/$'},
            {'href': '/event/event/1/show'},
            {'href': '/event/event/1/log'},
        )
        self.assertTitle("Große Testakademie 2222: Log [1–7 von 7]")

        self.traverse({'href': '/event/$'}, {'href': '/event/log'})
        self.assertTitle("Veranstaltungen-Log [1–17 von 17]")
        f = self.response.forms['logshowform']
        f['persona_id'] = "DB-5-1"
        f['submitted_by'] = "DB-1-9"
        self.submit(f)
        self.assertTitle("Veranstaltungen-Log [0–0 von 0]")

    @as_users("garcia")
    def test_registration_query_datetime_serialization(self) -> None:
        reference_time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Anmeldungen")
        f = self.response.forms['queryform']

        # Submit a query using a timezone unaware datetime value.
        f['qop_ctime.creation_time'] = QueryOperators.greater.value
        f['qval_ctime.creation_time'] = reference_time.isoformat()
        self.submit(f)

        # Check that the value stayed the same.
        f = self.response.forms['queryform']
        self.assertEqual(
            f['qval_ctime.creation_time'].value,
            reference_time.isoformat(),
        )

        # Now store that query.
        f['query_name'] = "Timezone Storage Test"
        self.submit(f, button="store_query", check_button_attrs=True)

        # And check that the value didn't change
        # Note that this is still the submitted value not the stored one.
        f = self.response.forms['queryform']
        self.assertEqual(
            f['qval_ctime.creation_time'].value,
            reference_time.isoformat(),
        )

        # Now retrieve the stored query and check that the value is still the same.
        self.traverse("Anmeldungen", "Timezone Storage Test")
        f = self.response.forms['queryform']
        self.assertEqual(
            f['qval_ctime.creation_time'].value,
            reference_time.isoformat(),
        )

    @as_users("garcia")
    def test_questionnaire_csrf(self) -> None:
        self.event.set_event(self.key, 1, {'use_additional_questionnaire': True})
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Fragebogen")
        f = self.response.forms['questionnaireform']
        f['fields.lodge'] = "Test"
        f[ANTI_CSRF_TOKEN_NAME] = "I am a Hax0r!1"
        self.submit(f, check_notification=False)
        f = self.response.forms['questionnaireform']
        self.assertEqual("Test", f['fields.lodge'].value)

    @as_users("emilia")
    def test_constraint_violations(self) -> None:
        self.traverse("TripelAkademie")
        self.assertPresence("Ungereimtheiten", div="constraint-violations")
        self.assertPresence(
            "Es gibt 1 Verstöße gegen Teilnahmeausschließlichkeit",
            div="constraint-violations",
        )
        self.assertPresence(
            "Es gibt 5 Verstöße gegen Kursausschließlichkeit",
            div="constraint-violations",
        )
        self.traverse("Kurse", "Ungereimtheiten")
        self.assertTitle("TripelAkademie – Ungereimtheiten")
        self.assertPresence("Teilnahmeausschließlichkeit")
        self.assertPresence(
            "Emilia (Emmy) Eventis ist an sich gegenseitig"
            " ausschließenden Veranstaltungsteilen anwesend (K1, W1).",
            div="MutuallyExclusiveParticipationCV-list",
        )
        self.assertPresence("Kursausschließlichkeit")
        self.assertPresence(
            "4. Akrobatik findet in sich gegenseitig ausschließenden"
            " Kursschienen statt (KK1, OK1).",
            div="MutuallyExclusiveCoursesCV-list",
        )
        self.assertNonPresence(
            "4. Akrobatik findet in sich gegenseitig"
            " ausschließenden Kursschienen statt (WK2m, WK2n).",
            div="MutuallyExclusiveCoursesCV-list",
        )

        # Change Emilia's registration.
        self.traverse({"href": "/event/event/4/registration/10/show"})
        self.assertPresence("Ungereimtheiten", div="constraint-violations")
        self.assertPresence(
            "Ist an sich gegenseitig ausschließenden"
            " Veranstaltungsteilen anwesend (K1, W1).",
            div="constraint-violations-list",
        )
        self.traverse("Bearbeiten")
        f = self.response.forms['changeregistrationform']
        self.assertEqual(
            f['part6.status'].value, str(const.RegistrationPartStati.waitlist)
        )
        self.assertEqual(
            f['part7.status'].value, str(const.RegistrationPartStati.guest)
        )
        self.assertEqual(
            f['part8.status'].value, str(const.RegistrationPartStati.participant)
        )
        self.assertEqual(
            f['part9.status'].value, str(const.RegistrationPartStati.guest)
        )
        self.assertEqual(
            f['part10.status'].value, str(const.RegistrationPartStati.rejected)
        )
        self.assertEqual(
            f['part11.status'].value, str(const.RegistrationPartStati.waitlist)
        )
        f['part9.status'] = f['part11.status'] = const.RegistrationPartStati.participant
        self.submit(f)

        self.assertPresence("Ungereimtheiten", div="constraint-violations")
        self.assertPresence(
            "Ist an sich gegenseitig ausschließenden"
            " Veranstaltungsteilen anwesend (K1, W1).",
            div="constraint-violations-list",
        )
        self.assertPresence(
            "Nimmt an sich gegenseitig ausschließenden"
            " Veranstaltungsteilen teil (K2, O2).",
            div="constraint-violations-list",
        )
        self.traverse("Ungereimtheiten")
        self.assertPresence(
            "Emilia (Emmy) Eventis nimmt an sich gegenseitig"
            " ausschließenden Veranstaltungsteilen teil (K2, O2).",
            div="MutuallyExclusiveParticipationCV-list",
        )

        f['part7.status'] = f['part9.status'] = const.RegistrationPartStati.cancelled
        self.submit(f)
        self.assertNonPresence("sich gegenseitig ausschließenden")

        self.traverse("Ungereimtheiten")
        self.assertNonPresence("Teilnahmebeschränkungen")

        # Change the Akrobatik course's active segments.
        self.traverse("4. Akrobatik")
        self.assertPresence("Ungereimtheiten", div="constraint-violations")
        self.assertPresence(
            "Findet in sich gegenseitig ausschließenden Kursschienen statt (KK1, OK1).",
            div="constraint-violations-list",
        )
        self.assertNonPresence("Findet nicht statt")

        self.traverse("Bearbeiten")
        f = self.response.forms['configurecourseform']
        self.assertEqual(f["segment6"].checked, True)
        self.assertEqual(f["segment6.is_active"].checked, True)
        self.assertEqual(f["segment7"].checked, False)
        self.assertEqual(f["segment7.is_active"].checked, False)
        self.assertEqual(f["segment8"].checked, True)
        self.assertEqual(f["segment8.is_active"].checked, True)
        self.assertEqual(f["segment9"].checked, False)
        self.assertEqual(f["segment9.is_active"].checked, False)
        self.assertEqual(f["segment10"].checked, False)
        self.assertEqual(f["segment10.is_active"].checked, False)
        self.assertEqual(f["segment11"].checked, True)
        self.assertEqual(f["segment11.is_active"].checked, True)
        self.assertEqual(f["segment12"].checked, True)
        self.assertEqual(f["segment12.is_active"].checked, True)
        self.assertEqual(f["segment13"].checked, False)
        self.assertEqual(f["segment13.is_active"].checked, False)
        self.assertEqual(f["segment14"].checked, False)
        self.assertEqual(f["segment14.is_active"].checked, False)
        self.assertEqual(f["segment15"].checked, False)
        self.assertEqual(f["segment15.is_active"].checked, False)

        f['segment8.is_active'] = False
        self.submit(f)
        self.assertNonPresence(
            "Ungereimtheiten", div="constraint-violations", check_div=False
        )
        self.assertPresence("Findet nicht statt", div="track8-attendees")

        # Cancel all other courses:
        event = self.event.get_event(self.key, 4)
        course_ids = self.event.list_courses(self.key, event.id)
        for course_id, title in course_ids.items():
            if title == "Akrobatik für Anfangende":
                continue
            data = {'segments': {track_id: None for track_id in event.tracks}}
            self.event.set_course(self.key, course_id, data)

        self.traverse("Ungereimtheiten")
        self.assertNonPresence("Kursausschließlichkeit")

    @as_users("anton")
    def test_financial_violations(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222")
        self.assertPresence("Ungereimtheiten", div="constraint-violations")
        self.assertPresence(
            "Es gibt 1 Anmeldungen mit negativem übrigen zu zahlenden Beitrag",
            div="constraint-violations",
        )
        self.assertPresence(
            "Es gibt 3 Anmeldungen mit nicht bezahltem Beitrag",
            div="constraint-violations",
        )
        self.assertPresence(
            "Es gibt 1 Anmeldungen mit übrigem zu zahlenden Beitrag",
            div="constraint-violations",
        )

        self.traverse("Ungereimtheiten")
        f = self.response.forms['filterconstraintsform']
        f['violation_kind'] = models_cv.ViolationKind.financial
        self.submit(f, check_notification=False)
        texts = [
            "Akira Abukara hat noch keinen Teilnahmebeitrag bezahlt (584,48 €).",
            "Emilia (Emmy) Eventis hat noch keinen Teilnahmebeitrag bezahlt (466,49 €).",
            "Garcia Generalis hat noch keinen Teilnahmebeitrag bezahlt (504,48 €). (Als Orga).",
            "Anton Administrator hat noch nicht den vollständigen Teilnahmebeitrag bezahlt (übrig: 353,99 €).",
            "Inga Iota muss eine Erstattung erhalten (116,49 €).",
            "Teilnahmebeiträge sollten über das Skatbankkonto laufen.",
        ]
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            filtered_kind=models_cv.ViolationKind.financial,
            texts=texts,
            check_complete=True,
            only_severity=False,
        )

        self.traverse("Inga")
        self.assertPresence("Muss eine Erstattung erhalten (116,49 €).")

        # Manipulate amount paid without setting payment date:
        execsql("""
            UPDATE event.registrations SET amount_paid = -5, amount_owed = -5
            WHERE id = 1
        """)
        execsql("UPDATE event.registrations SET amount_paid = 5 WHERE id = 2")
        execsql("UPDATE event.registrations SET amount_owed = 0 WHERE id = 3")
        execsql("UPDATE event.registrations SET amount_owed = 0 WHERE id = 5")

        self.traverse("Ungereimtheiten")
        texts = [
            "Anton Administrator hat einen negativen Betrag bezahlt (-5,00 €).",
            "Anton Administrator muss insgesamt einen negativen Betrag bezahlen (-5,00 €).",
            "Emilia (Emmy) Eventis hat bezahlt, aber kein Bezahlungsdatum.",
            "Emilia (Emmy) Eventis hat noch nicht den vollständigen Teilnahmebeitrag bezahlt (übrig: 461,49 €).",
            "Akira Abukara ist involviert, muss aber keinen Beitrag bezahlen.",
            "Inga Iota muss eine Erstattung erhalten",
            "Teilnahmebeiträge sollten über das Skatbankkonto laufen.",
        ]
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            filtered_kind=models_cv.ViolationKind.financial,
            texts=texts,
            check_complete=True,
            only_severity=False,
        )
        f = self.response.forms['filterconstraintsform']
        f['min_severity'] = models_cv.ViolationSeverity.DEBUG
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.DEBUG,
            check_complete=False,
            only_severity=True,
            texts=[
                "Garcia Generalis ist involviert, muss aber keinen Beitrag bezahlen.",
            ],
        )
        f['min_severity'] = models_cv.ViolationSeverity.DEBUG
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.ERROR,
            filtered_kind=models_cv.ViolationKind.financial,
            check_complete=True,
            only_severity=False,
            texts=[
                "Anton Administrator hat einen negativen Betrag bezahlt (-5,00 €).",
                "Anton Administrator muss insgesamt einen negativen Betrag bezahlen (-5,00 €).",
                "Emilia (Emmy) Eventis hat bezahlt, aber kein Bezahlungsdatum.",
            ],
        )
        self.traverse("Anton Administrator")
        self.assertPresence("Hat einen negativen Betrag bezahlt (-5,00 €).")
        self.assertPresence("Muss insgesamt einen negativen Betrag bezahlen (-5,00 €).")
        self.traverse("Ungereimtheiten")
        self.traverse("Emilia")
        self.assertPresence("Hat bezahlt, aber kein Bezahlungsdatum.")
        self.traverse("Ungereimtheiten")
        # Garcia is orga.
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "Garcia"
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung von Garcia Generalis (Große Testakademie 2222)")
        self.assertNonPresence(
            "Ist involviert, muss aber keinen Beitrag bezahlen.",
            div="constraint-violations",
            check_div=False,
        )
        self.traverse("Ungereimtheiten")
        self.traverse("Akira")
        self.assertPresence("Ist involviert, muss aber keinen Beitrag bezahlen.")
        self.traverse("Übersicht")
        self.assertPresence(
            "Es gibt 1 Anmeldungen ohne zu zahlendem Beitrag.",
            div="constraint-violations",
        )

    def _check_shown_violations(
        self,
        event_id: int,
        filtered_severity: models_cv.ViolationSeverity,
        filtered_kind: models_cv.ViolationKind | None = None,
        *,
        texts: list[str],
        check_complete: bool = True,
        only_severity: bool = True,
    ) -> None:

        def assertNodesHidden(nodes: list["lxml.html.Element"]) -> None:
            for node in nodes:
                self._assertNodeHasClass(node, "softhide")

        def assertNodesNotHidden(nodes: list["lxml.html.Element"]) -> None:
            for node in nodes:
                self._assertNodeNotHasClass(node, "softhide")

        parents = self._get_nodes(f"#event_{event_id}", check_exists=False)
        if not parents:
            self.fail(f"Did not find event {event_id}.")
        assertNodesNotHidden(parents)
        if texts:
            selector = lambda severity: (
                f"[data-severity='{severity.value}']"
                + (
                    f"[data-violation_kind='{filtered_kind.value}']"
                    if filtered_kind
                    else ""
                )
            )
            nodes = self._get_nodes(
                selector(filtered_severity), root_node=parents[0], check_exists=False
            )
            if not only_severity:
                for severity in models_cv.ViolationSeverity:
                    if severity > filtered_severity:
                        nodes.extend(
                            self._get_nodes(
                                selector(severity),
                                root_node=parents[0],
                                check_exists=False,
                            )
                        )
            if not nodes:
                self.fail(
                    f"Did not find violations for severity {filtered_severity.name} for event {event_id}."
                )
            assertNodesNotHidden(nodes)
            node_texts = [
                re.sub(r"\s+", " ", node.text_content().strip()) for node in nodes
            ]
            for text in texts:
                if not any(text in node_text for node_text in node_texts):
                    self.fail(
                        f"{text!r} not found for event {event_id} at severity {filtered_severity.name}."
                        f" I found these texts:\n" + "\n".join(node_texts),
                    )
            if check_complete and len(nodes) > len(texts):
                # print("\n".join(lxml.etree.tostring(node, encoding="unicode") for node in nodes))
                self.fail(
                    f"Found more violations for {event_id} at severity {filtered_severity.name}"
                    f" than were checked ({len(nodes)} > {len(texts)})."
                    f" I found these texts:\n" + "\n".join(node_texts),
                )
        if not texts:
            nodes = self._get_nodes(
                ".violations", root_node=parents[0], check_exists=False
            )
            assertNodesHidden(nodes)

    @event_keeper
    @as_users("annika", "petra")
    def test_constraint_violations_summary(self) -> None:
        self.traverse("Veranstaltungen", "Ungereimtheiten")
        self.assertTitle("Übersicht über Ungereimtheiten")

        all_event_ids = set(self.event.list_events(self.key))

        def test_events_shown(*event_ids: int) -> None:
            self.assertTitle("Übersicht über Ungereimtheiten")
            for event_id in event_ids:
                self.assertNotHidden(f"#event_{event_id}")
            for event_id in all_event_ids - set(event_ids):
                self.assertHidden(f"#event_{event_id}")

        test_events_shown(1, 2, 3, 4)

        self.assertPresence("CyberTestAkademie", div="event_3")
        self._check_shown_violations(
            event_id=3,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            texts=[
                "2 Fehlende Kurseinteilungen",
            ],
        )

        self.assertPresence("CdE-Party 2050", div="event_2")
        self._check_shown_violations(
            event_id=2,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            texts=[],
        )

        self.assertPresence("Große Testakademie 2222", div="event_1")
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            texts=[
                "1 Ausfallende Kurse mit Teilnehmenden",
                "3 Anmeldungen mit nicht bezahltem Beitrag",
                "2 Unzulässige gemischte Unterkünfte",
                "1 Unterkünfte mit inkorrekter Bewohnerzahl",
                "2 Fehlende Kurseinteilungen",
                "1 Anmeldungen mit übrigem zu zahlenden Beitrag",
                "1 Eingecheckte Abwesende",
                "1 Anmeldungen mit negativem übrigen zu zahlenden Beitrag",
                "1 Falsche IBAN-Konfiguration",
            ],
        )

        self.assertPresence("TripelAkademie", div="event_4")
        self._check_shown_violations(
            event_id=4,
            filtered_severity=models_cv.ViolationSeverity.INFO,
            texts=[
                "5 Verstöße gegen Kursausschließlichkeit",
                "1 Verstöße gegen Teilnahmeausschließlichkeit",
                "1 Anmeldungen mit nicht bezahltem Beitrag",
            ],
        )

        f = self.response.forms['filterconstraintsform']
        self.assertEqual(f['event_ids'].value, "")
        self.assertEqual(f['is_archived'].value, "-1")
        self.assertEqual(f['is_balanced'].value, "-1")
        self.assertEqual(f['is_archived'].value, "-1")

        f['event_ids'] = "1,3"
        self.submit(f, check_notification=False)
        test_events_shown(1, 3)

        f['event_ids'] = "1,3,2"
        self.submit(f, check_notification=False)
        test_events_shown(1, 2, 3)

        f['is_concluded'] = 1
        self.submit(f, check_notification=False)
        test_events_shown(3)

        f['is_concluded'] = 0
        self.submit(f, check_notification=False)
        test_events_shown(1, 2)

        f['event_ids'] = ""
        self.submit(f, check_notification=False)
        test_events_shown(1, 2, 4)

        f['is_balanced'] = 1
        self.submit(f, check_notification=False)
        test_events_shown()

        with self.switch_user("farin"):
            self.event.balance_event(self.key, 2)
        self.submit(f, check_notification=False)
        test_events_shown(2)

        f['is_balanced'] = 0
        self.submit(f)
        test_events_shown(1, 4)

        with self.switch_user("farin"):
            self.event.unbalance_event(self.key, 2)
        self.submit(f, check_notification=False)
        test_events_shown(1, 2, 4)

        f['is_balanced'] = -1
        f['is_concluded'] = -1
        f['event_ids'] = ""
        self.submit(f, check_notification=False)
        test_events_shown(1, 2, 3, 4)

        f['is_archived'] = 1
        self.submit(f, check_notification=False)
        test_events_shown()

        with self.switch_user("anton"):
            self.event.set_event_archived(self.key, 3)
        self.submit(f, check_notification=False)
        test_events_shown(3)

        f['is_balanced'] = 1
        self.submit(f, check_notification=False)
        test_events_shown()

        with self.switch_user("farin"):
            self.event.balance_event(self.key, 1)
            self.event.balance_event(self.key, 3)
        self.submit(f, check_notification=False)
        test_events_shown(3)

        f['is_archived'] = -1
        f['is_concluded'] = 0
        self.submit(f, check_notification=False)
        test_events_shown(1)

        f['is_balanced'] = -1
        f['is_concluded'] = -1
        self.submit(f, check_notification=False)
        test_events_shown(1, 2, 3, 4)

        f['min_severity'] = models_cv.ViolationSeverity.ERROR
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=3,
            filtered_severity=models_cv.ViolationSeverity.ERROR,
            texts=[],
        )
        self._check_shown_violations(
            event_id=2,
            filtered_severity=models_cv.ViolationSeverity.ERROR,
            texts=[],
        )
        self._check_shown_violations(
            event_id=1,
            filtered_severity=models_cv.ViolationSeverity.ERROR,
            texts=[
                "1 Ausfallende Kurse mit Teilnehmenden",
                "2 Anmeldungen mit nicht bezahltem Beitrag",
            ],
        )
        self._check_shown_violations(
            event_id=4,
            filtered_severity=models_cv.ViolationSeverity.ERROR,
            texts=[
                "5 Verstöße gegen Kursausschließlichkeit",
            ],
        )

        f['min_severity'] = models_cv.ViolationSeverity.CRITICAL
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=1, filtered_severity=models_cv.ViolationSeverity.CRITICAL, texts=[]
        )
        self._check_shown_violations(
            event_id=2, filtered_severity=models_cv.ViolationSeverity.CRITICAL, texts=[]
        )
        self._check_shown_violations(
            event_id=3, filtered_severity=models_cv.ViolationSeverity.CRITICAL, texts=[]
        )
        self._check_shown_violations(
            event_id=4, filtered_severity=models_cv.ViolationSeverity.CRITICAL, texts=[]
        )

        f['min_severity'] = models_cv.ViolationSeverity.WARNING
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=3,
            filtered_severity=models_cv.ViolationSeverity.WARNING,
            texts=[
                "2 Fehlende Kurseinteilungen",
            ],
        )

        f['min_severity'] = models_cv.ViolationSeverity.DEBUG
        self.submit(f, check_notification=False)
        self._check_shown_violations(
            event_id=3,
            filtered_severity=models_cv.ViolationSeverity.DEBUG,
            texts=[
                "3 Uneingecheckte Teilnehmende",
                "3 Fehlende Kurseinteilungen",
                "2 Kurse mit inkorrekter Teilnehmendenzahl",
            ],
        )

    @as_users("berta")
    def test_part_group_part_order(self) -> None:
        self.get('/event/event/2/part/summary')
        self.traverse("Teil hinzufügen")
        f = self.response.forms['addpartform']
        f['title'] = "Afterparty"
        f['shortname'] = "Afterparty"
        f['part_begin'] = "2050-01-16"
        f['part_end'] = "2050-01-17"
        f['fee'] = "1"
        self.submit(f)

        f['title'] = "Pregame"
        f['shortname'] = "Pregame"
        f['part_begin'] = "2050-01-14"
        f['part_end'] = "2050-01-15"
        f['fee'] = "2"
        self.submit(f)

        self.traverse("Gruppen", "Veranstaltungsteilgruppe hinzufügen")
        f = self.response.forms['configurepartgroupform']
        f['title'] = "All"
        f['shortname'] = "all"
        f['constraint_type'] = const.EventPartGroupType.Statistic
        f['part_ids'] = [4, 1001, 1002]
        self.submit(f)

        self.traverse("Statistik", {'linkid': 'part_group_participant_1001'})
        f = self.response.forms['queryform']
        self.assertEqual(
            f['qop_part4.status,part1001.status,part1002.status'].value,
            str(QueryOperators.equal.value),
        )

    @as_users("annika")
    def test_track_groups(self) -> None:
        self.get('/event/event/1/part/summary')
        self.traverse("Gruppen", "Kursschienengruppe hinzufügen")
        self.assertTitle("Kursschienengruppe hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['configuretrackgroupform']

        # Try to submit some invalid forms:
        f['title'] = ""
        f['shortname'] = ""
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('title', "Darf nicht leer sein.")
        self.assertValidationError('shortname', "Darf nicht leer sein.")
        f['title'] = f['shortname'] = "abc"
        f['track_ids'] = []
        self.submit(f, check_notification=False)
        self.assertValidationError('track_ids', "Darf nicht leer sein.", index=0)
        f['track_ids'] = [1, 2]
        self.submit(f, check_notification=False)
        course_choices_error_mgs = (
            "Alle Kursschienen einer Kurswahlsynchronisierung müssen die gleiche"
            " Kurswahl-Anzahl haben."
        )
        self.assertValidationError('track_ids', course_choices_error_mgs, index=0)

        # Now a valid one. (TripelAkademie)
        self.get('/event/event/4/part/summary')
        self.traverse("Gruppen", "Kursschienengruppe hinzufügen")
        f = self.response.forms['configuretrackgroupform']
        f['title'] = "Gruppe mit einer Kursschiene"
        f['shortname'] = "kl. Gr."
        f['sortkey'] = -10
        f['constraint_type'] = const.CourseTrackGroupType.course_choice_sync
        f['track_ids'] = []
        self.submit(f, check_notification=False)
        self.assertValidationError('track_ids', "Darf nicht leer sein.", index=0)
        f['track_ids'] = [6, 15]
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'track_ids',
            "Maximal eine Kurswahlsynchronisierung pro Kursschiene.",
            index=0,
        )
        self.assertValidationError('track_ids', course_choices_error_mgs, index=0)
        f['track_ids'] = [15]
        self.submit(f)

        self.submit(f, check_notification=False)
        self.assertValidationError(
            'title', "Es existiert bereits eine Kursschienengruppe mit diesem Namen."
        )
        self.assertValidationError(
            'shortname',
            "Es existiert bereits eine Kursschienengruppe mit diesem Namen.",
        )
        self.traverse("Gruppen", {'href': "/event/event/4/track/group/1001/change"})
        self.assertTitle("Kursschienengruppe bearbeiten (TripelAkademie)")
        f = self.response.forms['configuretrackgroupform']
        f['title'] = "Nur eine Kursschiene in dieser Gruppe"
        f['shortname'] = "Kurz"
        f['notes'] = "Das soll so!"
        self.submit(f)

        self.assertTitle("Gruppen (TripelAkademie)")
        self.assertPresence(
            "Nur eine Kursschiene in dieser Gruppe", div="track-group-summary"
        )
        self.assertNonPresence(
            "Gruppe mit einer Kursschiene", div="track-group-summary"
        )
        f = self.response.forms['deletetrackgroupform1001']
        self.submit(f, check_notification=False)
        self.assertValidationError('ack_delete', "Muss markiert sein.", index=3)
        f['ack_delete'] = True
        self.submit(f)
        self.assertNonPresence(
            "Keine Kursschiene in dieser Gruppe", div="track-group-summary"
        )

        # No tracks, no track groups (CdE-Party)
        self.get('/event/event/2/part/summary')
        self.assertNonPresence("Kursschienengruppe")

    @event_keeper
    @as_users("anton")
    def test_course_choice_sync(self) -> None:

        with self.switch_user("emilia"):
            # Emilia is only involved with O2 and K2, not W2 and should not be able to
            #  choose a W2 course when amending her registration.
            self.traverse(
                "Veranstaltungen", "TripelAkademie", "Meine Anmeldung", "Ändern"
            )
            f = self.response.forms['amendregistrationform']
            self.assertNotIn(
                "12",
                [value for value, _, _ in f['group3.course_choice_0'].options],
            )

        self.traverse("Veranstaltungen", "TripelAkademie", "Anmelden")

        # Register for TripelAkademie and choose some courses.
        f = self.response.forms['registerform']
        self.assertPresence(
            "Kurswahlen für Kurs 1. Hälfte", div="course-choice-container-group-1"
        )
        f['group1.course_choice_0'] = 9
        f['group1.course_choice_1'] = 10
        f['group1.course_choice_2'] = 12
        f['group1.course_choice_3'] = ''
        f['group1.course_instructor'] = 11
        self.assertPresence(
            "Kurswahlen für Kaub Vorträge", div="course-choice-container-15"
        )
        f['track15.course_choice_0'] = 11
        f['track15.course_instructor'] = 12
        self.assertPresence(
            "Kurswahlen für Kurs 2. Hälfte morgens",
            div="course-choice-container-group-3",
        )
        f['group3.course_choice_0'] = 12
        f['group3.course_choice_1'] = 11
        f['group3.course_choice_2'] = 9
        f['group3.course_choice_3'] = ''
        f['group3.course_choice_4'] = ''
        f['group3.course_instructor'] = ''
        self.assertPresence(
            "Kurswahlen für Kurs 2. Hälfte nachmittags",
            div="course-choice-container-group-2",
        )
        f['group2.course_choice_0'] = 11
        f['group2.course_choice_1'] = ''
        f['group2.course_choice_2'] = ''
        f['group2.course_instructor'] = 9
        self.submit(f)

        # Check that choices are correctly displayed.
        self.assertTitle("Deine Anmeldung (TripelAkademie)")
        self.assertPresence(
            "Geleiteter Kurs 2. All-Embracement", div="course-choices-group-1"
        )
        self.assertPresence(
            "1. Wahl 4. Akrobatik für Anfangende", div="course-choices-group-1"
        )
        self.assertPresence(
            "2. Wahl 1. Das Niebelungenlied", div="course-choices-group-1"
        )
        self.assertPresence("3. Wahl 3. Nostalgie", div="course-choices-group-1")

        self.assertPresence("Geleiteter Kurs 3. Nostalgie", div="course-choices-15")
        self.assertPresence("1. Wahl 2. All-Embracement", div="course-choices-15")

        self.assertPresence("1. Wahl 3. Nostalgie", div="course-choices-group-3")
        self.assertPresence("2. Wahl 2. All-Embracement", div="course-choices-group-3")
        self.assertPresence(
            "3. Wahl 4. Akrobatik für Anfangende", div="course-choices-group-3"
        )
        self.assertPresence("4. Wahl —", div="course-choices-group-3")
        self.assertPresence("5. Wahl —", div="course-choices-group-3")

        self.assertPresence(
            "Geleiteter Kurs 4. Akrobatik für Anfangende", div="course-choices-group-2"
        )
        self.assertPresence("1. Wahl 2. All-Embracement", div="course-choices-group-2")
        self.assertPresence("2. Wahl —", div="course-choices-group-2")
        self.assertPresence("3. Wahl —", div="course-choices-group-2")

        # Check that non-offered courses are illegal to choose.
        self.traverse("Ändern")
        f = self.response.forms['amendregistrationform']
        f['group1.course_choice_3'] = 9
        f['track15.course_instructor'] = 11
        f['group3.course_choice_3'].force_value(10)
        f['group2.course_choice_0'] = ''
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'group1.course_choice_3',
            "Du kannst diesen Kurs nicht als 1. und 4. Wahl wählen.",
        )
        self.assertValidationError(
            'track15.course_choice_0', "Bitte wähle nicht deinen eigenen Kurs"
        )
        self.assertValidationError(
            'group3.course_choice_3', "Unzulässige Kurswahl für diese Kursschiene."
        )
        self.assertValidationError(
            'group2.course_choice_0', "Du musst mindestens 1 Kurse wählen."
        )

        # Check that choices are correctly synced for each track group.
        registration = self.event.get_registration(self.key, 1001)
        event = self.event.get_event(self.key, 4)
        for tg in event.track_groups.values():
            choices_set = set()
            for track_id in tg.tracks.keys():
                choices_set.add(tuple(registration['tracks'][track_id]['choices']))
            self.assertEqual(len(choices_set), 1)

        # Check that changing one track propagates to others in the group.
        self.get("/event/event/4/part/8/change")
        f = self.response.forms['changepartform']
        f['track_num_choices_8'] = 10
        f['track_min_choices_8'] = 9
        self.submit(f)
        event = self.event.get_event(self.key, 4)
        for track in event.track_groups[1].tracks.values():
            self.assertEqual(track.num_choices, 10)
            self.assertEqual(track.min_choices, 9)

        # Check that change_registration works properly.
        self.get("/event/event/4/registration/10/show")
        self.assertTitle("Anmeldung von Emilia Eventis (TripelAkademie)")

        self.assertPresence("Kurs 2. Hälfte nachmittags", div="course-choices-group-2")
        self.assertPresence("Geleiteter Kurs —", div="course-choices-group-2")
        self.assertPresence("1. Wahl —", div="course-choices-group-2")
        self.assertPresence("2. Wahl —", div="course-choices-group-2")
        self.assertPresence("3. Wahl —", div="course-choices-group-2")

        self.traverse("Bearbeiten")
        f = self.response.forms['changeregistrationform']
        f['group2.course_choice_0'] = 9
        f['group2.course_choice_1'] = 11
        f['group2.course_choice_2'] = ''
        f['group2.course_instructor'] = 12
        self.submit(f)

        self.assertPresence("Kurs 2. Hälfte nachmittags", div="course-choices-group-2")
        self.assertPresence(
            "Geleiteter Kurs 3. Nostalgie", div="course-choices-group-2"
        )
        self.assertPresence("1. Wahl 4. Akrobatik", div="course-choices-group-2")
        self.assertPresence("2. Wahl 2. All-Embracement", div="course-choices-group-2")
        self.assertPresence("3. Wahl —", div="course-choices-group-2")

        # Test add_registration too.
        self.traverse("Anmeldungen", "Anmeldung hinzufügen")
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-7"
        self.assertPresence(
            "Kurswahlen für Kurs 1. Hälfte", div="course-choice-container-group-1"
        )
        f['group1.course_choice_0'] = 9
        f['group1.course_choice_1'] = 10
        f['group1.course_choice_2'] = 12
        f['group1.course_choice_3'] = ''
        f['group1.course_instructor'] = 11
        self.assertPresence(
            "Kurswahlen für Kaub Vorträge", div="course-choice-container-15"
        )
        f['track15.course_choice_0'] = 12
        f['track15.course_instructor'] = 11
        self.assertPresence(
            "Kurswahlen für Kurs 2. Hälfte morgens",
            div="course-choice-container-group-3",
        )
        f['group3.course_choice_0'] = 12
        f['group3.course_choice_1'] = 11
        f['group3.course_choice_2'] = ''
        f['group3.course_choice_3'] = ''
        f['group3.course_choice_4'] = ''
        f['group3.course_instructor'] = 9
        self.assertPresence(
            "Kurswahlen für Kurs 2. Hälfte nachmittags",
            div="course-choice-container-group-2",
        )
        f['group2.course_choice_0'] = 11
        f['group2.course_choice_1'] = ''
        f['group2.course_choice_2'] = ''
        f['group2.course_instructor'] = 9
        self.submit(f)

        # Check that choices are correctly displayed.
        self.assertTitle("Anmeldung von Bertå Beispiel (TripelAkademie)")
        self.assertPresence(
            "Geleiteter Kurs 2. All-Embracement", div="course-choices-group-1"
        )
        self.assertPresence("1. Wahl 4. Akrobatik", div="course-choices-group-1")
        self.assertPresence("2. Wahl 1. Niebelungenlied", div="course-choices-group-1")
        self.assertPresence("3. Wahl 3. Nostalgie", div="course-choices-group-1")

        self.assertPresence(
            "Geleiteter Kurs 2. All-Embracement", div="course-choices-15"
        )
        self.assertPresence("1. Wahl 3. Nostalgie", div="course-choices-15")

        self.assertPresence(
            "Geleiteter Kurs 4. Akrobatik", div="course-choices-group-3"
        )
        self.assertPresence("1. Wahl 3. Nostalgie", div="course-choices-group-3")
        self.assertPresence("2. Wahl 2. All-Embracement", div="course-choices-group-3")
        self.assertPresence("3. Wahl —", div="course-choices-group-3")
        self.assertPresence("4. Wahl —", div="course-choices-group-3")
        self.assertPresence("5. Wahl —", div="course-choices-group-3")

        self.assertPresence(
            "Geleiteter Kurs 4. Akrobatik", div="course-choices-group-2"
        )
        self.assertPresence("1. Wahl 2. All-Embracement", div="course-choices-group-2")
        self.assertPresence("2. Wahl —", div="course-choices-group-2")
        self.assertPresence("3. Wahl —", div="course-choices-group-2")

        self.traverse("Bearbeiten")
        f = self.response.forms['changeregistrationform']
        f['part10.status'] = const.RegistrationPartStati.rejected  # Windischleuba 2
        f['group2.course_choice_0'] = 9
        self.submit(f, check_notification=False)
        # Akrobatik and Nostalgie are only offered in Windischleuba in the second half.
        # This no longer is a validation error for orgas.
        # self.assertValidationError(
        #     'group3.course_choice_0', "Unzulässige Kurswahl für diese Kursschiene.")
        # self.assertValidationError(
        #     'group2.course_choice_0', "Unzulässige Kurswahl für diese Kursschiene.")
        f['group2.course_choice_0'] = ''
        f['group3.course_choice_0'] = ''
        self.submit(f)

        # Test muldiedit.
        self.get('/event/event/4/registration/multiedit?reg_ids=1001,1002')
        f = self.response.forms['changeregistrationsform']
        self.assertEqual(f['enable_group2.course_instructor'].checked, True)
        self.assertEqual(f['group2.course_instructor'].value, '9')
        f['group2.course_instructor'] = 11
        self.assertEqual(f['enable_group3.course_instructor'].checked, False)
        f['enable_group3.course_instructor'] = True
        f['group3.course_instructor'] = 12
        self.assertEqual(f['enable_track15.course_id'].checked, True)
        self.assertEqual(f['track15.course_id'].value, '')
        f['track15.course_id'] = 12

        self.assertEqual(f['enable_track6.course_id'].checked, True)
        self.assertEqual(f['track6.course_id'].value, '')
        f['track6.course_id'] = 10
        self.submit(f)

        for id_ in (1001, 1002):
            self.get(f'/event/event/4/registration/{id_}/show')
            self.assertPresence(
                "Geleiteter Kurs 2. All-Embracement", div="course-choices-group-2"
            )
            self.assertPresence(
                "Geleiteter Kurs 3. Nostalgie", div="course-choices-group-3"
            )
            self.assertPresence("Kurs KV 3. Nostalgie")
            self.assertPresence("Kurs OK1 1. Niebelungenlied")

        # Check that a CCS group can be recreated after being deleted, while
        #  compatible choices exist.
        event_id = 4
        event = self.event.get_event(self.key, event_id)
        self.get(f'/event/event/{event_id}/part/summary')
        self.traverse("Gruppen")
        f = self.response.forms['deletetrackgroupform1']
        f['ack_delete'] = True
        self.submit(f)
        self.traverse("Kursschienengruppe hinzufügen")
        f = self.response.forms['configuretrackgroupform']
        f['title'] = f['shortname'] = "K1"
        f['track_ids'] = list(str(id_) for id_ in event.track_groups[1].tracks.keys())
        self.submit(f)

        # Check failing creation after changing choices for the tracks.
        f = self.response.forms['deletetrackgroupform1001']
        f['ack_delete'] = True
        self.submit(f)

        track_ids = list(event.track_groups[1].tracks.keys())
        reg_id = list(self.event.list_registrations(self.key, event_id))[0]
        self.event.set_registration(
            self.key,
            {
                'id': reg_id,
                'tracks': {
                    track_ids[0]: {
                        'course_instructor': 10,
                    },
                    track_ids[1]: {
                        'course_instructor': 11,
                    },
                },
            },
        )

        self.traverse("Kursschienengruppe hinzufügen")
        f = self.response.forms['configuretrackgroupform']
        f['title'] = f['shortname'] = "K1"
        f['track_ids'] = list(str(id_) for id_ in event.track_groups[1].tracks.keys())
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'track_ids',
            "Kursschienensynchronisierung fehlgeschlagen, weil"
            " inkompatible Kurswahlen existieren.",
            index=0,
        )

    @as_users("emilia")
    def test_ccs_cancelled_courses(self) -> None:
        self.event.set_event(
            self.key,
            4,
            {
                'is_course_state_visible': True,
                'is_participant_list_visible': True,
                'is_course_assignment_visible': True,
            },
        )
        course_id = 9
        course = self.event.get_course(self.key, course_id)
        self.event.set_course(
            self.key,
            course_id,
            {
                'segments': {
                    track_id: {"is_active": False} for track_id in course.segments
                },
            },
        )

        self.traverse("Veranstaltungen", "TripelAkademie", "Meine Anmeldung", "Ändern")
        f = self.response.forms['amendregistrationform']
        with self.assertRaises(ValueError):
            f['group1.course_choice_0'] = course_id
        f['group1.course_instructor'] = course_id
        self.traverse("Anmeldungen", "Alle Anmeldungen", "Details", "Bearbeiten")
        f = self.response.forms['changeregistrationform']
        f['group1.course_choice_0'] = course_id
        f['group1.course_instructor'] = course_id

    @event_keeper
    @as_users("anton")
    def test_registration_strict_bool(self) -> None:
        event_update = {
            "registration_start": now(),
            "fields": {
                -1: {
                    "kind": const.FieldDatatypes.bool,
                    "association": const.FieldAssociations.registration,
                    "field_name": "test1",
                },
                -2: {
                    "kind": const.FieldDatatypes.bool,
                    "association": const.FieldAssociations.registration,
                    "field_name": "test2",
                    "entries": {
                        True: "Ja",
                        False: "Nein",
                    },
                },
                -3: {
                    "kind": const.FieldDatatypes.int,
                    "association": const.FieldAssociations.registration,
                    "field_name": "test3",
                },
            },
        }
        self.event.set_event(self.key, 2, event_update)
        self.traverse("Veranstaltungen", "CdE-Party", "Anmeldung konfigurieren")
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'] = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['field_id_-1'] = 1001
        self.submit(f)
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'] = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['field_id_-1'] = 1002
        self.submit(f)
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'] = True
        f['role_-1'] = const.QuestionnaireRowRole.event_field
        f['field_id_-1'] = 1003
        self.submit(f)
        self.traverse("Anmelden")
        f = self.response.forms['registerform']
        f["fields.test1"] = ""
        f["fields.test2"] = ""
        f["fields.test3"] = ""
        self.submit(f, check_notification=False)
        self.assertValidationError('fields.test2', "Darf nicht leer sein.")
        self.assertValidationError('fields.test3', "Darf nicht leer sein.")
        f["fields.test2"] = False
        f["fields.test3"] = 0
        self.submit(f)

    @event_keeper
    @as_users("garcia")
    def test_custom_query_filter(self) -> None:
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Datenfelder konfigurieren",
            "Eigene Filter",
            "Kursfilter hinzufügen",
        )
        f = self.response.forms['configurecustomfilterform']
        f['title'] = "Kur(s|z)titel"
        f['cf_course.title'] = f['cf_course.shortname'] = True
        self.submit(f)
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'title', "Es existiert bereits ein Filter mit diesem Titel."
        )
        self.assertPresence("Es existiert bereits ein Filter mit diesen Feldern.")
        self.traverse("Kurse", "Kurssuche")
        f = self.response.forms['queryform']
        f['qop_course.shortname,course.title'] = QueryOperators.match.value
        f['qval_course.shortname,course.title'] = "rett"
        self.submit(f)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Heldentum", div="query-result")
        self.assertPresence("Kabarett", div="query-result")
        self.traverse("Eigene Filter", {'href': r'filter/\d+/change'})
        self.assertTitle(
            "Eigenen Filter „Kur(s|z)titel“ ändern (Große Testakademie 2222)"
        )
        f = self.response.forms['configurecustomfilterform']
        f['notes'] = "abc"
        self.submit(f)
        f = self.response.forms['deletecustomfilterform1001']
        self.submit(f)
        self.assertNonPresence("Kur(s|z)titel")

        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'] = True
        f['title_-1'] = "Bringt Kugeln mit"
        f['field_name_-1'] = "brings_kugeln"
        f['kind_-1'] = const.FieldDatatypes.bool
        f['association_-1'] = const.FieldAssociations.registration
        self.submit(f)
        self.traverse("Eigene Filter", "Anmeldungsfilter hinzufügen")
        f = self.response.forms['configurecustomfilterform']
        f['title'] = "Bälle oder Kugeln?"
        f['cf_reg_fields.xfield_brings_balls'] = f[
            'cf_reg_fields.xfield_brings_kugeln'
        ] = True
        self.submit(f)
        self.assertPresence("Bringt Kugeln mit")
        self.assertNonPresence("brings_kugeln")
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms['fieldsummaryform']
        f['delete_1001'] = True
        self.submit(f)
        self.traverse("Eigene Filter")
        self.assertNonPresence("Bringt Kugeln mit")
        self.assertPresence("brings_kugeln")

        new_fields = {
            -1: {
                'field_name': 'TEST',
                'title': 'Test',
                'kind': const.FieldDatatypes.bool,
                'association': const.FieldAssociations.registration,
                'entries': None,
            },
            -2: {
                'field_name': 'TEST2',
                'title': 'Test 2',
                'kind': const.FieldDatatypes.bool,
                'association': const.FieldAssociations.registration,
                'entries': None,
            },
        }
        self.event.set_event(self.key, 1, {'fields': new_fields})
        new_filter = models.CustomQueryFilter(
            id=-1,  # type: ignore[arg-type]
            event_id=1,  # type: ignore[arg-type]
            scope=QueryScope.registration,
            title='Test',
            fields={'reg_fields.xfield_TEST', 'reg_fields.xfield_TEST2'},
            notes=None,
        )
        data = {
            'title': new_filter.title,
            'fields': new_filter.fields,
            'notes': new_filter.notes,
        }
        self.event.add_custom_query_filter(
            self.key, scope=new_filter.scope, event_id=new_filter.event_id, data=data
        )

        self.traverse("Anmeldungen")
        f = self.response.forms['queryform']
        f[f'qop_{new_filter.get_field_string()}'] = QueryOperators.equal.value
        f[f'qval_{new_filter.get_field_string()}'] = True
        self.submit(f)

    @as_users("garcia")
    def test_orga_droid(self) -> None:
        event_id = 1

        # Create a token.
        self.traverse(
            "Veranstaltungen",
            "Große Testakademie 2222",
            "Downloads & Import",
            "Orga-Tokens",
            "Orga-Token erstellen",
        )
        f = self.response.forms['configureorgatokenform']
        f['etime'] = datetime.datetime(now().year + 1, 1, 1)
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('title', "Darf nicht leer sein")
        f['title'] = "New Token!"
        self.submit(f)
        new_token_id, secret = self.fetch_orga_token()

        # Change it.
        self.traverse({'href': f"/event/event/{event_id}/droid/{new_token_id}/change"})
        f = self.response.forms['configureorgatokenform']
        f['title'] = ""
        f['notes'] = "Spam"
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('title', "Darf nicht leer sein")
        f['title'] = "Changed title"
        self.submit(f)
        deletion_form = self.response.forms[f'deleteorgatokenform{new_token_id}']

        # Test and compare exports.
        orga_token = self.event.get_orga_token(self.key, new_token_id)

        self.get(f"/event/event/{event_id}/download/partial")
        orga_export = self.response.json
        self.get("/")

        headers = {orga_token.request_header_key: orga_token.get_token_string(secret)}
        with self.switch_user("anonymous"):
            for url in [
                "/event/event/droid/export",
                f'/event/event/{event_id}/droid/partial',
            ]:
                with self.subTest(url=url):
                    self.get(url, headers=headers)
                    droid_export = self.response.json
                    droid_export['timestamp'] = orga_export['timestamp']
                    droid_export['event']['orga_tokens'][str(orga_token.id)][
                        'atime'
                    ] = None
                    self.assertEqual(orga_export, droid_export)

        # Revoke the used token.
        self.get(f"/event/event/{event_id}/droid/summary")
        f = self.response.forms[f'revokeorgatokenform{new_token_id}']
        self.submit(f)

        # Test deletion:
        self.submit(deletion_form, check_notification=False)
        self.assertPresence(
            "Ein Orga-Token kann nicht mehr gelöscht werden, nachdem es benutzt wurde.",
            div="notifications",
        )

        self.traverse("Orga-Token erstellen")
        f = self.response.forms['configureorgatokenform']
        f['title'] = "To be deleted."
        f['etime'] = datetime.datetime(now().year + 1, 1, 1)
        self.submit(f)
        new_token_id, secret = self.fetch_orga_token()
        f = self.response.forms[f'deleteorgatokenform{new_token_id}']
        self.submit(f)

        log_expectation = [
            {
                'code': const.EventLogCodes.orga_token_created,
                'change_note': "New Token!",
            },
            {
                'code': const.EventLogCodes.orga_token_changed,
                'change_note': "'New Token!' -> 'Changed title'",
            },
            {
                'code': const.EventLogCodes.orga_token_revoked,
                'change_note': "Changed title",
            },
            {
                'code': const.EventLogCodes.orga_token_created,
                'change_note': "To be deleted.",
            },
            {
                'code': const.EventLogCodes.orga_token_deleted,
                'change_note': "To be deleted.",
            },
        ]
        self.assertLogEqual(
            log_expectation, 'event', event_id=event_id, offset=self.EVENT_LOG_OFFSET
        )

    @as_users("anton")
    def test_event_fee_stats(self) -> None:
        event_id = 2
        reg_ids = []
        reg_data: CdEDBObject = {
            "event_id": event_id,
            "persona_id": self.user['id'],
            "mixed_lodging": True,
            "list_consent": True,
            "notes": None,
            "parts": {
                4: {
                    "status": const.RegistrationPartStati.participant,
                },
            },
            "tracks": {},
            "fields": {
                "solidarity": True,
                "donation": False,
            },
        }
        reg_ids.append(self.event.create_registration(self.key, reg_data))
        reg_data['persona_id'] = 5
        reg_data['fields'] = {
            "solidarity": False,
            "donation": True,
        }
        reg_ids.append(self.event.create_registration(self.key, reg_data))
        reg_data['persona_id'] = 2
        reg_ids.append(self.event.create_registration(self.key, reg_data))
        reg_data['persona_id'] = 3
        reg_ids.append(self.event.create_registration(self.key, reg_data))
        reg_data['persona_id'] = 4
        reg_data['fields'] = {}
        reg_data['parts'][4]['status'] = const.RegistrationPartStati.cancelled
        reg_ids.append(self.event.create_registration(self.key, reg_data))
        registrations = self.event.get_registrations(self.key, reg_ids)
        self.assertEqual(
            decimal.Decimal("0.01"), registrations[reg_ids[0]]['amount_owed']
        )
        self.assertEqual(
            decimal.Decimal("437.00"), registrations[reg_ids[1]]['amount_owed']
        )
        self.assertEqual(
            decimal.Decimal("425.00"), registrations[reg_ids[2]]['amount_owed']
        )
        self.assertEqual(
            decimal.Decimal("435.00"), registrations[reg_ids[3]]['amount_owed']
        )
        self.assertEqual(
            decimal.Decimal("0.00"), registrations[reg_ids[4]]['amount_owed']
        )

        # set amount_paid
        self._set_payment_info(
            reg_ids[0], event_id, registrations[reg_ids[0]]['amount_owed']
        )
        self._set_payment_info(
            reg_ids[1], event_id, registrations[reg_ids[1]]['amount_owed']
        )
        self._set_payment_info(reg_ids[3], event_id, decimal.Decimal("200.00"))
        self._set_payment_info(reg_ids[4], event_id, decimal.Decimal("123.00"))

        self.traverse(
            "Veranstaltungen",
            "CdE-Party 2050",
            "Teilnahmebeiträge",
            "Beitrags-Statistik",
        )
        self.assertTitle("Beitrags-Statistik (CdE-Party 2050)")
        self.assertPresence(
            "Regulärer Beitrag .* 40,00 € 4 Anmeldungen 20,00 € 2 Anmeldungen",
            regex=True,
            div="event-fee-stats",
        )
        self.assertPresence(
            "Stornokosten .* 0,00 € 0 Anmeldungen 0,00 € 0 Anmeldungen",
            regex=True,
            div="event-fee-stats",
        )
        self.assertPresence(
            "Externenbeitrag .* 2,00 € 1 Anmeldungen 2,00 € 1 Anmeldungen",
            regex=True,
            div="event-fee-stats",
        )
        self.assertPresence(
            "Solidarische Reduktion .* -4,99 € 1 Anmeldungen -4,99 € 1 Anmeldungen",
            regex=True,
            div="event-fee-stats",
        )
        self.assertNonPresence("Solidarische Erhöhung", div="event-fee-stats")
        self.assertPresence(
            "Solidarische Spende .* 1.260,00 € 3 Anmeldungen 420,00 € 1 Anmeldungen",
            regex=True,
            div="event-fee-stats",
        )
        self.assertPresence(
            "Überschuss – 123,00 € 1 Anmeldungen", div="event-fee-stats"
        )

        self.assertPresence(
            "Teilnahmebeitrag 37,01 € 4 Anmeldungen",
            div="event-fee-stats-by-category",
        )
        self.assertPresence(
            "Spende 1.260,00 € 3 Anmeldungen",
            div="event-fee-stats-by-category",
        )
        self.assertPresence(
            "Stornokosten 0,00 € 0 Anmeldungen",
            div="event-fee-stats-by-category",
        )
        self.assertPresence(
            "Ausgaben 40,00 € 4 Anmeldungen",
            div="event-fee-stats-by-budget",
        )
        self.assertPresence(
            "Solitopf 1.255,01 € 4 Anmeldungen",
            div="event-fee-stats-by-budget",
        )
        self.assertPresence(
            "Vereinsvermögen 2,00 € 1 Anmeldungen",
            div="event-fee-stats-by-budget",
        )

        save = self.response
        self.traverse({'linkid': '^kind_solidary_donation_owed_query$'})
        self.assertPresence("Ergebnis [3]", div="query-results")
        f = self.response.forms['queryform']
        self.submit(f, button="download", value="json")
        result = json.loads(self.response.text)
        key = "amount_owed.kind_solidary_donation"
        for entry in result:
            self.assertIn(key, entry.keys())
            self.assertEqual("420.00", entry[key])
        self.response = save

        save = self.response
        self.traverse({'linkid': '^category_donation_owed_query$'})
        self.assertPresence("Ergebnis [3]", div="query-results")
        f = self.response.forms['queryform']
        self.submit(f, button="download", value="json")
        result = json.loads(self.response.text)
        key = "amount_owed.category_donation"
        for entry in result:
            self.assertIn(key, entry.keys())
            self.assertEqual("420.00", entry[key])
        self.response = save

        save = self.response
        self.traverse({'linkid': '^budget_solidarity_owed_query$'})
        self.assertPresence("Ergebnis [4]", div="query-results")
        f = self.response.forms['queryform']
        self.submit(f, button="download", value="json")
        result = json.loads(self.response.text)
        key = "amount_owed.budget_solidarity"
        for entry in result:
            self.assertIn(key, entry.keys())
            if entry["persona.id"] == 1:
                self.assertEqual("-4.99", entry[key])
            else:
                self.assertEqual("420.00", entry[key])
        self.response = save

        self.traverse({'linkid': 'surplus_query'})
        self.assertPresence("Ergebnis [1]", div="query-results")
        self.response = save

        self.assertPresence("Gesamtsumme 1.297,01 € 560,01 €")
        self.assertPresence("1 Personen haben 200,00 € gezahlt, ohne")
        self.assertPresence("1 Personen haben noch nichts")
        self.traverse("In Anmeldungsliste anzeigen")
        self.assertPresence("Ergebnis [1]", div='query-results')

        self.get(f"/event/event/{event_id}/registration/{reg_ids[0]}/show")
        self.assertPresence("Anton")
        self.assertPresence("Teilnahmebeitrag CdE-Party 2050, Anton Administrator")

        self.get(f"/event/event/{event_id}/registration/{reg_ids[1]}/show")
        self.assertPresence("Emilia")
        self.assertPresence("Teilnahmebeitrag CdE-Party 2050")

        self.get(f"/event/event/{event_id}/registration/{reg_ids[2]}/show")
        self.assertPresence("Berta")
        self.assertPresence("Teilnahmebeitrag CdE-Party 2050")

        self.traverse("Teilnahmebeiträge")
        self.assertPresence(
            "Orgarabatt -10,00 € 2 Zu Zahlen: 1 Bezahlt: -20,00 € -10,00 €"
        )
        self.assertPresence(
            "Teilnahmebeitrag Party 15,00 € 4 Zu Zahlen: 2 Bezahlt: 60,00 € 30,00 €"
        )
        self.assertPresence(
            "Absager TODO: add real condition once implemented."
            " 7,50 € 0 Zu Zahlen: 0 Bezahlt: 0,00 € 0,00 €"
        )
        self.assertPresence(
            "Externenzusatzbeitrag 2,00 € 1 Zu Zahlen: 1 Bezahlt: 2,00 € 2,00 €"
        )
        self.assertPresence(
            "Solidarische Reduktion -4,99 € 1 Zu Zahlen: 1 Bezahlt: -4,99 € -4,99 €"
        )
        self.assertPresence(
            "Generöse Spende 420,00 € 3 Zu Zahlen: 1 Bezahlt: 1.260,00 € 420,00 €"
        )

    @as_users("garcia")
    def test_personalized_event_fees(self) -> None:
        event_id = 1

        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Teilnahmebeiträge")
        self.assertPresence("KL-Erstattung", div="eventfee_10")
        self.assertPresence("-30,00 € – -20,00 €", div="eventfee_10")
        self.assertPresence("Personalisierter Teilnahmebeitrag", div="eventfee_10")

        self.traverse("Meine Anmeldung", "Als Orga ansehen", "Teilnahmebeitragsdetails")
        self.traverse("Personalisierten Beitrag hinzufügen")
        f = self.response.forms['configureeventfeeform']
        self.assertIsNone(f.get('condition', default=None))
        f['title'] = "Rabatt auf Ehrenhomiebasis"
        f['kind'] = const.EventFeeType.solidary_reduction
        f['amount'] = "-33.33"
        self.submit(f)

        self.assertPresence("Rabatt auf Ehrenhomiebasis", div="eventfee_1001")
        self.assertPresence("-33,33 €", exact=True, div="eventfee_amount_1001")
        self.assertPresence(
            "Personalisierter Teilnahmebeitrag (-33,33 €)",
            exact=True,
            div="eventfee_condition_1001",
        )

        self.traverse("Teilnahmebeiträge")
        self.assertPresence("-33,33 €", exact=True, div="eventfee_amount_1001")

        self.traverse({'linkid': "eventfee1_change"})
        f = self.response.forms['configureeventfeeform']
        f['amount'] = 0
        self.submit(f)
        self.assertPresence("0,00 €", exact=True, div="eventfee_amount_1")

        self.traverse({'linkid': "personalized_fee1001_multiset"})
        f = self.response.forms['personalizedfeemultisetform']
        self.assertEqual(f['amount3'].value, "-33.33")
        self.assertEqual(f['amount5'].value, "")
        f['amount3'] = "0"
        f['amount5'] = "12"
        self.submit(f)

        self.assertPresence("0,00 € – 12,00 €", exact=True, div="eventfee_amount_1001")
        f = self.response.forms['deleteeventfeeform1001']
        self.submit(f)

        log_expectation = [
            {
                'code': const.EventLogCodes.event_fee_created,
                'change_note': "Rabatt auf Ehrenhomiebasis",
            },
            {
                'code': const.EventLogCodes.personalized_fee_amount_set,
                'change_note': "Rabatt auf Ehrenhomiebasis (-33,33 €)",
                'persona_id': self.user['id'],
            },
            {
                'code': const.EventLogCodes.event_fee_modified,
                'change_note': "Teilnahmebeitrag Warmup",
            },
            {
                'code': const.EventLogCodes.personalized_fee_amount_set,
                'change_note': "Rabatt auf Ehrenhomiebasis (0,00 €)",
                'persona_id': self.user['id'],
            },
            {
                'code': const.EventLogCodes.personalized_fee_amount_set,
                'change_note': "Rabatt auf Ehrenhomiebasis (12,00 €)",
                'persona_id': 100,
            },
            {
                'code': const.EventLogCodes.personalized_fee_amount_deleted,
                'change_note': "Rabatt auf Ehrenhomiebasis",
                'persona_id': self.user['id'],
            },
            {
                'code': const.EventLogCodes.personalized_fee_amount_deleted,
                'change_note': "Rabatt auf Ehrenhomiebasis",
                'persona_id': 100,
            },
            {
                'code': const.EventLogCodes.event_fee_deleted,
                'change_note': "Rabatt auf Ehrenhomiebasis",
            },
        ]
        self.assertLogEqual(
            log_expectation,
            "event",
            event_id=event_id,
            offset=self.EVENT_LOG_OFFSET,
        )

    def test_limited_event_mailinglists(self) -> None:
        # Test creation of part group linked lists by orga.
        with self.switch_user("garcia"):
            self.get('/event/event/1/part/summary')
            self.traverse("Gruppen", "Veranstaltungsteilgruppe hinzufügen")
            f = self.response.forms["configurepartgroupform"]
            f['title'] = f['shortname'] = "Beide"
            f['part_ids'] = [2, 3]
            f['constraint_type'] = const.EventPartGroupType.mailinglist_link
            self.submit(f)

            f = self.response.forms["createeventmailinglistform1001"]
            self.submit(f)
            self.assertTitle("Gruppen (Große Testakademie 2222)")
            self.assertNotIn("createeventmailinglistform1001", self.response.forms)

            ml_log_expectation = (
                {
                    'code': const.MlLogCodes.list_created,
                    'mailinglist_id': 1001,
                },
                {
                    'code': const.MlLogCodes.moderator_added,
                    'mailinglist_id': 1001,
                    'persona_id': self.user['id'],
                },
            )
            self.assertLogEqual(ml_log_expectation, "ml", _mailinglist_ids=[1001])

        # Test subscribability of limited and limited exclusive lists.
        with self.switch_user("emilia"):
            persona_id = self.user['id']
            event_id = 4
            part_group_id = 10
            limited_ml = self.ml.get_mailinglist(self.key, 68)
            exclusive_ml = self.ml.get_mailinglist(self.key, 69)
            registration_id = unwrap(
                self.event.list_registrations(self.key, event_id, persona_id).keys()
            )

            event = self.event.get_event(self.key, event_id)
            self.assertEqual(
                "Mailingliste Windischleuba",
                event.part_groups[part_group_id].title,
            )
            self.assertEqual(
                {7, 10},
                set(event.part_groups[part_group_id].parts),
            )

            assert isinstance(limited_ml, EventAssociatedMailinglist)
            assert not isinstance(limited_ml, EventAssociatedExclusiveMailinglist)
            self.assertEqual(
                event_id,
                limited_ml.event_id,
            )
            self.assertEqual(
                part_group_id,
                limited_ml.event_part_group_id,
            )

            assert isinstance(exclusive_ml, EventAssociatedExclusiveMailinglist)
            self.assertEqual(
                event_id,
                exclusive_ml.event_id,
            )
            self.assertEqual(
                part_group_id,
                exclusive_ml.event_part_group_id,
            )

            self.assertEqual(
                {
                    persona_id: const.SubscriptionState.implicit,
                },
                self.ml.get_subscription_states(self.key, limited_ml.id),
            )
            self.assertEqual(
                {
                    persona_id: const.SubscriptionState.implicit,
                },
                self.ml.get_subscription_states(self.key, exclusive_ml.id),
            )

            self.event.set_registration(
                self.key,
                {
                    'id': registration_id,
                    'parts': {
                        7: {  # W1
                            'status': const.RegistrationPartStati.cancelled,
                        },
                        10: {  # W2
                            'status': const.RegistrationPartStati.not_applied,
                        },
                    },
                },
            )

            self.ml.write_subscription_states(
                self.key, [limited_ml.id, exclusive_ml.id]
            )

            self.assertEqual(
                {},
                self.ml.get_subscription_states(self.key, limited_ml.id),
            )
            self.assertEqual(
                {},
                self.ml.get_subscription_states(self.key, exclusive_ml.id),
            )

            self.assertTrue(
                self.ml.do_subscription_action(
                    self.key,
                    const.SubscriptionAction.add_subscriber,
                    limited_ml.id,
                    persona_id,
                ),
            )
            with self.assertRaises(SubscriptionError):
                self.ml.do_subscription_action(
                    self.key,
                    const.SubscriptionAction.add_subscriber,
                    exclusive_ml.id,
                    persona_id,
                )

    @event_keeper
    @as_users("garcia")
    def test_reimbursement_iban_field(self) -> None:
        # Create a new string datafield.
        self.traverse(
            "Veranstaltungen", "Große Testakademie 2222", "Datenfelder konfigurieren"
        )
        f = self.response.forms["fieldsummaryform"]
        f["create_-1"] = True
        f["field_name_-1"] = "iban"
        f["association_-1"] = const.FieldAssociations.registration
        f["kind_-1"] = const.FieldDatatypes.str
        self.submit(f)

        # Enter a valid IBAN.
        self.traverse("Übersicht")
        f = self.response.forms["quickregistrationform"]
        f["phrase"] = "Inga"
        self.submit(f)
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        f["fields.iban"] = iban = "DE26 3702 0500 0008 0689 00"
        self.submit(f)
        self.assertPresence(iban)
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        self.assertEqual(iban, f["fields.iban"].value)

        # Enter an invalid IBAN.
        self.traverse("Übersicht")
        f = self.response.forms["quickregistrationform"]
        f["phrase"] = "Anton"
        self.submit(f)
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        f["fields.iban"] = non_iban = "random bullshit"
        self.submit(f)
        self.assertPresence(non_iban)

        # Change datatype to IBAN.
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms["fieldsummaryform"]
        f['kind_1001'] = const.FieldDatatypes.iban
        self.submit(f)

        # Check conversions.
        self.traverse("Übersicht")
        f = self.response.forms["quickregistrationform"]
        f["phrase"] = "Inga"
        self.submit(f)
        self.assertPresence(iban)
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        self.assertEqual(iban, f["fields.iban"].value)

        self.traverse("Übersicht")
        f = self.response.forms["quickregistrationform"]
        f["phrase"] = "Anton"
        self.submit(f)
        self.assertNonPresence(non_iban)
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        self.assertEqual("", f["fields.iban"].value)

        # Configure reimbursement field.
        self.traverse("Konfiguration")
        f = self.response.forms["changeeventform"]
        f["reimbursement_iban_field_id"] = 1001
        self.submit(f)
        self.traverse(
            "Teilnahmebeiträge",
            "Beitrags-Statistik",
            {"linkid": "surplus_query"},
        )
        self.assertPresence("Inga", div="result-container")
        self.assertPresence(iban, div="result-container")

    @event_keeper
    @as_users("garcia", "ludwig", "petra")
    def test_helper(self) -> None:
        # Sidebar buttons are basic_validated in test_sidebar(_one_event)
        if self.user_in("garcia"):
            cutoff_id = 1
        else:
            cutoff_id = 0
        with self.conf.with_overrides(EVENT_LIMITED_ACCESS_CUTOFF_ID=cutoff_id):
            self.traverse("Veranstaltungen", "Veranstaltungshelfer")
            self.assertTitle("Veranstaltungshelfer [1]")
            self.assertNotIn('addeventhelperform', self.response.forms)
            self.assertNotIn('removeeventhelperform42', self.response.forms)
            self.assertPresence("Petra Philanthrop")

            if self.user_in("petra"):
                self.traverse("Alle Veranstaltungen")
                self.assertPresence("CdE-Party 2050")
                self.assertPresence("6 Anmeldungen, 1 Orga")
                self.assertNoLink("Anmeldungen")
            else:
                self.traverse("Veranstaltungen")
            self.traverse("Große Testakademie 2222")
            saved_response = self.response
            self.get('/event/event/2/registration/query', status=403)
            if self.user_in("petra"):
                self.get('/event/event/1/registration/3/show', status=403)
            self.response = saved_response
            self.traverse("Statistik")
            self.assertNoLink('/event/event/1/registration/query')
            self.traverse(
                {'href': '/event/event/1/course/query', 'description': "2"},
                {'href': "/event/event/1/course/stats"},
            )
            self.assertPresence("2 + 0")
            self.traverse("Heldentum")
            self.assertPresence("2 + 1")
            if not self.user_in("ludwig"):
                self.assertNonPresence("Akira")
                self.assertNotIn('emilia', self.response.text)
            else:
                self.assertPresence("Akira")
                self.assertIn('emilia', self.response.text)
            self.traverse(
                {'href': "/event/event/1/course/stats"},
                {'href': "/event/event/1/course/query"},
                "Unterkünfte",
            )
            saved_response = self.response
            self.assertNoLink('/event/event/1/lodgement/graph/form')
            self.traverse("Warme Stube")
            self.assertPresence("2 + 0", div='inhabitants-3')
            self.assertPresence(
                "Gemischte Unterkunft mit konfligierenden Teilnehmern.",
                div='inhabitants-3',
            )
            if not self.user_in("ludwig"):
                self.assertNonPresence("Akira")
            else:
                self.assertPresence("Akira")
            self.get('/event/event/1/lodgement/graph/show', status=403)
            self.response = saved_response
            self.traverse("Unterkunftssuche")
            f = self.response.forms['queryform']
            self.submit(f)
            self.traverse("Konfiguration")
            f = self.response.forms['changeeventform']
            if self.user_in("garcia"):
                self.submit(f)
            else:
                with self.assertRaises(webtest.app.AppError):
                    self.submit(f)
            self.traverse("Datenfelder konfigurieren")
            f = self.response.forms['fieldsummaryform']
            if self.user_in("garcia"):
                self.submit(f)
            else:
                with self.assertRaises(webtest.app.AppError):
                    self.submit(f)

    @event_keeper
    @as_users("anton")
    def test_event_dearchive_unbalance(self) -> None:
        self.traverse("Veranstaltungen", "CyberTestAkademie")
        f = self.response.forms['archiveeventform']
        f['ack_archive'] = True
        f['create_past_event'] = False
        self.submit(f)
        self.assertPresence(
            "Diese Veranstaltung wurde archiviert.", div="static-notifications"
        )
        f = self.response.forms['balanceeventform']
        self.submit(f)
        self.traverse("Konfiguration")
        f = self.response.forms['changeeventform']
        self.submit(f)
        self.assertPresence(
            "Diese Veranstaltung wurde archiviert.", div="static-notifications"
        )
        self.assertIn('unbalanceeventform', self.response.forms)

    @event_keeper
    @as_users("garcia")
    @prepsql("UPDATE event.events SET is_balanced = True WHERE id = 1 OR id = 2;")
    def test_event_is_balanced(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Teilnahmebeiträge")
        self.assertNoLink("fee/add")
        self.assertNoLink(r"fee/\d/change")
        f = self.response.forms['deleteeventfeeform1']
        self.assertIn("disabled", f['submitform'].attrs)

        self.get("/event/event/1/fee/add?personalized=True")
        self.assertTitle("Teilnahmebeiträge (Große Testakademie 2222)")
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        self.get("/event/event/1/fee/add?personalized=False")
        self.assertTitle("Teilnahmebeiträge (Große Testakademie 2222)")
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        self.get("/event/event/1/fee/1/change")
        self.assertTitle("Teilnahmebeiträge (Große Testakademie 2222)")
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")

        self.traverse("Meine Anmeldung", "Als Orga ansehen", "Teilnahmebeitragsdetails")
        self.assertNoLink("fee/add")
        f = self.response.forms['deletepersonalizedfeeform10']
        self.assertIn("disabled", f['submitform'].attrs)

        self.get("/event/event/1/registration/3/fee/add")
        self.assertTitle(
            "Teilnahmebeitragsdetails für Garcia Generalis (Große Testakademie 2222)"
        )
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")

        self.get("/event/event/1/registration/2/fee/summary")
        f = self.response.forms['addpersonalizedfeeform10']
        self.assertIn("disabled", f['submitform'].attrs)

        self.get("/event/event/1/registration/2/change")
        self.assertNotification(
            "Veranstaltung ist finanziell abgeschlossen.", "warning", static=True
        )
        f = self.response.forms['changeregistrationform']
        self.assertEqual(
            f['part1.status'].value, str(const.RegistrationPartStati.waitlist)
        )
        f['part1.status'].value = const.RegistrationPartStati.cancelled
        self.submit(f, check_notification=False)
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        f['part1.status'].value = const.RegistrationPartStati.participant
        self.submit(f)

        self.traverse("Anmeldungen", "Anmeldung hinzufügen")
        self.assertNotification(
            "Veranstaltung ist finanziell abgeschlossen.", "warning", static=True
        )
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-4-3"
        self.submit(f, check_notification=False)
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        f['part1.status'] = f['part2.status'] = f['part3.status'] = (
            const.RegistrationPartStati.not_applied
        )
        self.submit(f)

        self.get("/event/event/1/registration/multiedit?reg_ids=1,2")
        self.assertNotification(
            "Veranstaltung ist finanziell abgeschlossen.", "warning", static=True
        )
        f = self.response.forms['changeregistrationsform']
        f['enable_part1.status'] = True
        f['part1.status'] = const.RegistrationPartStati.participant
        self.submit(f, check_notification=False)
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        f['enable_part1.status'] = False
        f['enable_fields.is_child'] = True
        f['fields.is_child'] = True
        self.submit(f, check_notification=False)
        self.assertNotification("Veranstaltung ist finanziell abgeschlossen.", "error")
        f['enable_fields.is_child'] = False
        f['enable_reg.orga_notes'] = True
        f['reg.orga_notes'] = "Test"
        self.submit(f)

        with self.switch_user("farin"):
            self.traverse("Veranstaltungen", "Große Testakademie 2222")
            f = self.response.forms["unbalanceeventform"]
            self.submit(f)

        with self.switch_user("berta"):
            self.traverse(
                "Veranstaltungen",
                "CdE-Party 2050",
                "Konfiguration",
                "Veranstaltungsteile",
            )
            self.assertNoLink("part/add")
            self.get("/event/event/2/part/add")
            self.assertNotification(
                "Veranstaltung ist finanziell abgeschlossen.", "error"
            )
            self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")

    @as_users("emilia")
    @prepsql(
        f"UPDATE {models.Event.database_table} SET is_course_assignment_visible = True WHERE id = 1"
    )
    def test_course_instructor_attendees(self) -> None:
        self.traverse(
            "Veranstaltungen", "Große Testakademie 2222", "Meine geleiteten Kurse"
        )
        self.assertTitle("Deine geleiteten Kurse (Große Testakademie 2222)")
        self.assertPresence("Planetenretten für Anfänger", div="track3")
        self.assertPresence("Arbeitssitzung (Zweite Hälfte)", div="track3")

        self.assertPresence("Kursteilnehmende [2 + 1]", div="attendees3")
        self.assertPresence(
            "Emilia (Emmy) Eventis (KL) emilia@example.cde", div="attendee-list3"
        )
        self.assertPresence("Akira Abukara akira@example.cde", div="attendee-list3")
        self.assertPresence("Inga Iota inga@example.cde", div="attendee-list3")

    @as_users("annika")
    def test_event_quicksearch(self) -> None:
        self.traverse("Veranstaltungen", "Veranstaltungshelfer")
        self.assertTitle("Veranstaltungshelfer [1]")
        f = self.response.forms["quickeventform"]
        f["event_id"] = ""
        self.submit(f)
        self.assertTitle("Veranstaltungshelfer [1]")
        self.assertNotification("Unbekannte Veranstaltung.", "error")
        f = self.response.forms["quickeventform"]
        f["event_id"] = 1
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms["quickeventform"]
        f["event_id"] = ""
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertNotification("Unbekannte Veranstaltung.", "error")
        f = self.response.forms["quickeventform"]
        f["event_id"] = 2
        self.submit(f)
        self.assertTitle("CdE-Party 2050")
        self.traverse("Teilnahmebeiträge")
        self.assertTitle("Teilnahmebeiträge (CdE-Party 2050)")
        f = self.response.forms["quickeventform"]
        f["event_id"] = 1
        self.submit(f)
        self.assertTitle("Teilnahmebeiträge (Große Testakademie 2222)")
        self.traverse("Kurse", "Heldentum")
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        f = self.response.forms["quickeventform"]
        f["event_id"] = 1
        self.submit(f)
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        f = self.response.forms["quickeventform"]
        g = self.response.forms["quickregistrationform"]
        f["event_id"] = 2
        self.submit(f)
        self.assertTitle("CdE-Party 2050")
        self.assertNotification(
            "Weiterleitung auf spezifische Unterseite nicht möglich.", "info"
        )
        g["phrase"] = "Garcia"
        self.submit(g)
        self.assertTitle("Anmeldung von Garcia Generalis (Große Testakademie 2222)")
        f = self.response.forms["quickeventform"]
        f["event_id"] = 3
        self.submit(f)
        self.assertTitle("Anmeldung von Garcia Generalis (CyberTestAkademie)")

    @as_users("annika")
    def test_approve_registration(self) -> None:
        self.traverse("Veranstaltungen", "TripelAkademie")
        self.assertPresence(
            r"ab \d{2}.\d{2}.\d{4}", div="timeframe-registration", regex=True
        )
        f = self.response.forms["unapproveregistrationform"]
        self.submit(f)
        mail = self.fetch_mail_content()
        self.assertIn("gesperrt", mail)
        self.assertNotification(
            "Es wurde ein Anmeldebeginn eingestellt,"
            " aber die Anmeldung ist noch nicht freigeschaltet worden.",
            "warning",
            static=True,
        )
        self.assertDivNotExists("#timeframe-registration")
        self.assertNoLink("/register", content="Anmelden")

        self.get("/event/event/4/register")
        self.assertTitle("TripelAkademie")
        self.assertNotification("Anmeldung noch nicht eröffnet.", "warning")
        self.traverse("Anmeldungen", "Anmeldung hinzufügen")
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = "DB-1-9"
        self.submit(f)

        self.traverse("Übersicht", "Betreuer verwalten")
        f = self.response.forms["addcaretakersform"]
        f["caretaker_ids"] = "DB-5-1"
        self.submit(f)

        with self.switch_user(5):
            self.traverse("Veranstaltungen", "TripelAkademie")
            f = self.response.forms["approveregistrationform"]
            self.submit(f)
            mail = self.fetch_mail_content()
            self.assertIn("freigeschaltet", mail)

        self.get("/event/event/4/register")
        self.assertTitle("Anmeldung für TripelAkademie")

        log_expectation: list[CdEDBObject] = [
            {
                "code": const.EventLogCodes.registration_unapproved,
            },
            {
                "code": const.EventLogCodes.registration_created,
                "persona_id": 1,
            },
            {
                "code": const.EventLogCodes.caretaker_added,
                "persona_id": 5,
            },
            {
                "code": const.EventLogCodes.registration_approved,
                "submitted_by": 5,
            },
        ]
        self.assertLogEqual(log_expectation, "event", event_id=4)

    @as_users("garcia")
    def test_change_instructor_no_choices(self) -> None:
        event_id = 1
        self.event.set_event(
            self.key,
            event_id,
            {"parts": {3: {"tracks": {3: {"num_choices": 0, "min_choices": 0}}}}},
        )

        self.get(f"/event/event/{event_id}/registration/1/show")
        self.assertPresence("Arbeitssitzung (Zweite Hälfte) Geleiteter Kurs —")
        self.traverse("Bearbeiten")
        f = self.response.forms["changeregistrationform"]
        f["track3.course_instructor"] = 5
        self.submit(f)
        self.assertPresence("Arbeitssitzung (Zweite Hälfte) Geleiteter Kurs ε. Backup")
