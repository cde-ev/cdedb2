#!/usr/bin/env python3

import copy
import csv
import datetime
import json
import re
import tempfile
from typing import Sequence

import webtest

import cdedb.database.constants as const
from cdedb.common import ADMIN_VIEWS_COOKIE_NAME, CdEDBObject, now
from cdedb.frontend.common import CustomCSVDialect, iban_filter
from cdedb.query import QueryOperators
from tests.common import UserObject, USER_DICT, FrontendTest, as_users, prepsql, storage


class TestEventFrontend(FrontendTest):
    @as_users("emilia")
    def test_index(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("CdE-Party 2050")

    @as_users("anonymous", "janis")
    def test_no_event_realm_view(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("CdE-Party 2050")

        self.traverse({'description': 'Große Testakademie 2222'})
        self.assertPresence("aka@example.cde", div="orga-address")
        self.assertPresence("Erste Hälfte", div="timeframe-parts")
        self.assertNonPresence("Everybody come!")
        self.assertPresence("für eingeloggte Veranstaltungsnutzer sichtbar",
                            div='static-notifications')

        self.traverse({'description': 'Kursliste'})
        self.assertPresence("α. Planetenretten für Anfänger", div='list-courses')
        self.assertPresence("Wir werden die Bäume drücken.", div='list-courses')
        msg = ("Die Kursleiter sind nur für eingeloggte Veranstaltungsnutzer "
               "sichtbar.")
        self.assertPresence(msg, div="instructors-not-visible")
        self.assertNonPresence("Bernd Lucke")

    @as_users("anton", "berta")
    def test_index_orga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertPresence("CdE-Party 2050", div='organized-events')
        self.assertNonPresence("CdE-Party 2050", div='current-events')

    @as_users("annika", "emilia", "martin", "vera", "werner")
    def test_sidebar(self) -> None:
        self.traverse({'description': 'Veranstaltungen'})
        everyone = {"Veranstaltungen", "Übersicht"}
        admin = {"Alle Veranstaltungen", "Log"}

        # not event admins (also orgas!)
        if self.user_in('emilia', 'martin', 'werner'):
            ins = everyone
            out = admin | {"Nutzer verwalten", "Archivsuche"}
        # core admins
        elif self.user_in('vera'):
            ins = everyone | {"Nutzer verwalten", "Archivsuche"}
            out = admin
        # event admins
        elif self.user_in('annika'):
            ins = everyone | admin | {"Nutzer verwalten", "Archivsuche"}
            out = set()
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("emilia")
    def test_showuser(self) -> None:
        self.traverse({'description': self.user['display_name']})
        self.assertTitle("{} {}".format(self.user['given_names'],
                                        self.user['family_name']))

    @as_users("emilia")
    def test_changeuser(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        self.submit(f)
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertPresence("Hyrule", div='address')

    @as_users("annika", "ferdinand")
    def test_adminchangeuser(self) -> None:
        self.realm_admin_view_profile('emilia', 'event')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.assertNotIn('free_form', f.fields)
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("annika", "ferdinand")
    def test_toggleactivity(self) -> None:
        self.realm_admin_view_profile('emilia', 'event')
        self.assertPresence("Ja", div='account-active')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence("Nein", div='account-active')

    @as_users("annika", "vera")
    def test_user_search(self) -> None:
        self.traverse({'description': 'Veranstaltunge'},
                      {'description': 'Nutzer verwalten'})
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

    @as_users("annika", "paul")
    def test_create_archive_user(self) -> None:
        data = {
            "title": "Dr.",
            "name_supplement": 'von und zu',
            "birthday": "1987-06-05",
            "gender": "1",
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
            re.compile(r"Benutzer-Administration"), current_state=False)

        # Test Event Administration Admin View
        self.assertNoLink('/event/event/log')
        self.assertNoLink('/event/event/list', content="Alle Veranstaltungen")
        self.traverse({'href': '/event/event/1/show'})
        self.assertNotIn('deleteeventform', self.response.forms)
        self.assertNotIn('addorgaform', self.response.forms)
        self.traverse({'href': '/event/event/1/registration/status'})
        self._click_admin_view_button(re.compile(r"Veranstaltungs-Administration"),
                                      current_state=False)
        self.traverse({'href': '/event/event/1/show'})
        self.assertIn('deleteeventform', self.response.forms)
        self.assertIn('addorgaform', self.response.forms)
        self.traverse({'href': '/event/'},
                      {'href': '/event/list'},
                      {'href': '/event/event/create'})

        # Test Orga Controls Admin View
        self.traverse({'href': '/event/'},
                      {'href': '/event/event/1/show'})
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

        self._click_admin_view_button(re.compile(r"Veranstaltungs-Administration"),
                                      current_state=True)
        # Even without the Orga Controls Admin View we should see the Orga
        # Controls of our own event:
        self.traverse({'href': '/event/'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/registration/list'},
                      {'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/change'},
                      {'href': '/event/event/2/part/summary'},
                      {'href': '/event/event/2/show'})
        self.assertIn('quickregistrationform', self.response.forms)
        self.assertIn('changeminorformform', self.response.forms)
        self.assertIn('lockform', self.response.forms)
        self.assertNoLink("Orga-Schaltflächen")

        self.traverse({'href': '/event/'},
                      {'href': '/event/event/1/show'})
        self._click_admin_view_button(
            re.compile(r"Orga-Schaltflächen"), current_state=False)
        self.traverse({'href': '/event/event/1/registration/list'},
                      {'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/change'},
                      {'href': '/event/event/1/part/summary'},
                      {'href': '/event/event/1/course/list'},
                      {'href': '/event/event/1/course/1/show'},
                      {'href': '/event/event/1/show'})
        self.assertIn('quickregistrationform', self.response.forms)
        self.assertIn('changeminorformform', self.response.forms)
        self.assertIn('lockform', self.response.forms)

    @as_users("annika")
    def test_list_events(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Alle Veranstaltungen'})
        self.assertTitle("Alle Veranstaltungen")
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertPresence("CdE-Party 2050", div='current-events')
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertPresence("Orgas")
        self.assertPresence("Anmeldungen")

    @as_users("anonymous", "garcia")
    def test_list_events_unprivileged(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'href': '/event/event/list'})
        self.assertTitle("Alle Veranstaltungen")
        self.assertPresence("Große Testakademie 2222", div='current-events')
        self.assertNonPresence("CdE-Party 2050")
        self.assertNonPresence("PfingstAkademie 2014")
        self.assertNonPresence("Orgas")
        self.assertNonPresence("Anmeldungen")

    @as_users("annika", "berta", "emilia")
    def test_show_event(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Warmup: 02.02.2222 – 02.02.2222 "
                            "Erste Hälfte: 01.11.2222 – 11.11.2222 "
                            "Zweite Hälfte: 11.11.2222 – 30.11.2222",
                            div='timeframe-parts')
        self.assertPresence("Everybody come!", div='description')
        self.assertNonPresence("für eingeloggte Veranstaltungsnutzer sichtbar",
                               div='notifications')
        self.assertPresence("30.10.2000, 01:00:00 – 30.10.2200, 01:00:00 ",
                            div='timeframe-registration')
        self.assertPresence("aka@example.cde", div='orga-address')
        self.assertPresence("Garcia G. Generalis", div='orgas', exact=True)

    @as_users("berta", "charly")
    def test_show_event_noorga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")

        self.assertNonPresence("TestAka")
        self.assertNonPresence("CdE-Konto IBAN")
        self.assertNonPresence("Fragebogen aktiv")
        self.assertNonPresence("Todoliste … just kidding ;)")
        self.assertNonPresence("Kristallkugel-basiertes Kurszuteilungssystemm")

        self.assertNotIn("quickregistrationform", self.response.forms)
        self.assertNotIn("changeminorformform", self.response.forms)
        self.assertNotIn("lockform", self.response.forms)
        self.assertNotIn("createparticipantlistform", self.response.forms)

    @as_users("annika", "garcia")
    def test_show_event_orga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")

        self.assertPresence("TestAka", div='shortname')
        self.assertPresence("Club der Ehemaligen", div='institution')
        iban = iban_filter(self.app.app.conf['EVENT_BANK_ACCOUNTS'][0][0])
        self.assertPresence(iban, div='cde-iban')
        self.assertPresence("Nein", div='questionnaire-active')
        self.assertPresence("Todoliste … just kidding ;)", div='orga-notes')
        self.assertPresence("Kristallkugel-basiertes Kurszuteilungssystem",
                            div='mail-text')

        self.assertIn('quickregistrationform', self.response.forms)
        self.assertIn('changeminorformform', self.response.forms)
        self.assertIn('lockform', self.response.forms)
        if not self.user_in('annika'):  # annika is also admin
            self.assertNotIn('createparticipantlistform', self.response.forms)

    @as_users("berta", "garcia")
    def test_show_event_noadmin(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")

        self.assertNotIn("createparticipantlistform", self.response.forms)
        self.assertNotIn("addorgaform", self.response.forms)
        self.assertNotIn("removeorgaform7", self.response.forms)

    @as_users("annika")
    def test_show_event_admin(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")

        self.assertNotIn('createorgalistform', self.response.forms)
        f = self.response.forms[f"removeorgaform{ USER_DICT['garcia']['id'] }"]
        self.submit(f)
        f = self.response.forms['createparticipantlistform']
        self.assertIn('disabled', f.fields['submitform'][0].attrs)
        self.submit(f, check_notification=False)
        self.assertPresence("Mailingliste kann nur mit Orgas erstellt werden.",
                            div='notifications')
        f = self.response.forms['addorgaform']
        f['orga_id'] = USER_DICT['garcia']['DB-ID']
        self.submit(f)
        f = self.response.forms['createparticipantlistform']
        self.submit(f)

    @as_users("anton")
    def test_create_participant_list(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms["createparticipantlistform"]
        self.submit(f)

    @as_users("annika", "emilia", "garcia", "martin", "vera", "werner")
    def test_sidebar_one_event(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        everyone = {"Veranstaltungsübersicht", "Übersicht", "Kursliste"}
        not_registered = {"Anmelden"}
        registered = {"Meine Anmeldung"}
        registered_or_orga = {"Teilnehmer-Infos"}
        orga = {
            "Teilnehmerliste",  "Anmeldungen", "Statistik", "Kurse", "Kurseinteilung",
            "Unterkünfte", "Downloads", "Partieller Import", "Überweisungen eintragen",
            "Konfiguration", "Veranstaltungsteile", "Datenfelder konfigurieren",
            "Anmeldung konfigurieren", "Fragebogen konfigurieren", "Log", "Checkin"}

        # TODO this could be more expanded (event without courses, distinguish
        #  between registered and participant, ...
        # not registered, not event admin
        if self.user_in('martin', 'vera', 'werner'):
            ins = everyone | not_registered
            out = registered | registered_or_orga | orga
        # registered
        elif self.user_in('emilia'):
            ins = everyone | registered | registered_or_orga
            out = not_registered | orga
        # orga
        elif self.user_in('garcia'):
            ins = everyone | registered | registered_or_orga | orga
            out = not_registered
        # event admin (annika is not registered)
        elif self.user_in('annika'):
            ins = everyone | not_registered | registered_or_orga | orga
            out = registered
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("anton", "berta")
    def test_no_hard_limit(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'CdE-Party 2050'})
        self.assertTitle("CdE-Party 2050")
        self.assertPresence("Let‘s have a party!")
        self.assertPresence("01.12.2049, 01:00:00 – 31.12.2049, 01:00:00",
                            div='timeframe-registration', exact=True)

    @as_users("annika", "garcia")
    def test_hard_limit_orga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("30.10.2000, 01:00:00 – 30.10.2200, 01:00:00 "
                            "(Nachmeldungen bis 30.10.2221, 01:00:00) ",
                            div='timeframe-registration', exact=True)

    @as_users("charly", "emilia")
    def test_hard_limit_noorga(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("30.10.2000, 01:00:00 – 30.10.2200, 01:00:00",
                            div='timeframe-registration', exact=True)

    @as_users("annika", "berta", "emilia")
    def test_course_list(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Kursliste'})
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertPresence("ToFi")
        self.assertPresence("Wir werden die Bäume drücken.")

    @as_users("annika", "garcia", "ferdinand")
    def test_change_event(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Konfiguration'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        # basic event data
        f = self.response.forms['changeeventform']
        self.assertEqual(f['registration_start'].value, "2000-10-30T01:00:00")
        f['title'] = "Universale Akademie"
        f['registration_start'] = "2001-10-30 00:00:00"
        f['notes'] = """Some

        more

        text"""
        f['use_additional_questionnaire'].checked = True
        f['participant_info'] = ""
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertNonPresence("30.10.2000")
        self.assertPresence("30.10.2001", div='timeframe-registration')
        # orgas
        self.assertNonPresence("Bertålotta")
        # check visibility and hint text on empty participant_info
        self.traverse("Teilnehmer-Infos")
        self.assertTitle("Universale Akademie – Teilnehmer-Infos")
        self.assertPresence(
            "Diese Seite ist momentan für Teilnehmer nicht sichtbar. Um das zu ändern, "
            "können Orgas über die Konfigurations-Seite hier etwas hinzufügen.",
            div='static-notifications')
        self.traverse("Übersicht")
        if self.user_in('ferdinand', 'annika'):
            f = self.response.forms['addorgaform']
            # Try to add an invalid cdedbid.
            f['orga_id'] = "DB-1-1"
            self.submit(f, check_notification=False)
            self.assertValidationError('orga_id', "Checksumme stimmt nicht.", index=-1)
            # Try to add a non event-user.
            f['orga_id'] = USER_DICT['janis']['DB-ID']
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'orga_id', "Dieser Nutzer ist kein Veranstaltungsnutzer.", index=-1)
            # Try to add an archived user.
            f['orga_id'] = USER_DICT['hades']['DB-ID']
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'orga_id', "Dieser Benutzer existiert nicht oder ist archiviert.",
                index=-1)
            # Try to add a non-existent user.
            f['orga_id'] = "DB-1000-6"
            self.submit(f, check_notification=False)
            self.assertValidationError(
                'orga_id', "Dieser Benutzer existiert nicht oder ist archiviert.",
                index=-1)
            f['orga_id'] = USER_DICT['berta']['DB-ID']
            self.submit(f)
            self.assertTitle("Universale Akademie")
            self.assertPresence("Bertålotta", div='manage-orgas')
            f = self.response.forms['removeorgaform2']
            self.submit(f)
            self.assertTitle("Universale Akademie")
            self.assertNonPresence("Bertålotta")

    @as_users("garcia")
    def test_orga_rate_limit(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})

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
        self.traverse({'href': 'event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertNonPresence("Charly")

    def test_event_visibility(self) -> None:
        # Add a course track, a course and move the registration start to one
        # week in the future.
        self.login(USER_DICT['annika'])
        self.traverse({'href': '/event/$'},
                      {'description': 'Alle Veranstaltungen'},
                      {'description': 'CdE-Party 2050'},
                      {'description': 'Veranstaltungsteile'})
        f = self.response.forms['partsummaryform']
        f['track_title_4_-1'] = "Spätschicht"
        f['track_shortname_4_-1'] = "Spät"
        f['track_create_4_-1'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/2/course/stats'},
                      {'href': '/event/event/2/course/create'})
        f = self.response.forms['createcourseform']
        f['title'] = "Chillout mit Musik"
        f['nr'] = "1"
        f['shortname'] = "music"
        f['instructors'] = "Giorgio Moroder"
        self.submit(f)
        self.traverse({'href': '/event/event/2/change'})
        f = self.response.forms['changeeventform']
        f['registration_start'] =\
            (now() + datetime.timedelta(days=7)).isoformat()
        self.submit(f)

        # Check visibility for orga
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertPresence("Chillout mit Musik")
        # Check for inexistence of links to event, invisible event page, but
        # visible course page
        self.logout()
        self.login(USER_DICT['emilia'])
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.traverse({'href': '/event/$'})
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.get('/event/event/2/course/list')
        self.assertPresence("Chillout mit Musik")
        self.assertNotIn('/event/event/2/show', self.response.text)
        self.get('/event/event/2/show', status=403)

        # Now, the other way round: visible event without visible course list
        self.get('/')
        self.logout()
        self.login(USER_DICT['annika'])
        self.traverse({'href': '/event/$'},
                      {'description': 'Alle Veranstaltungen'},
                      {'description': 'CdE-Party 2050'},
                      {'description': 'Konfiguration'})
        f = self.response.forms['changeeventform']
        f['is_course_list_visible'] = False
        f['is_visible'] = True
        self.submit(f)
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertPresence("Chillout mit Musik")
        self.logout()

        self.login(USER_DICT['emilia'])
        self.traverse({'href': '/event/event/2/show'})
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'})
        # Becuase of markdown smarty, the apostroph is replaced
        # with its typographically correct form here.
        self.assertPresence("Let‘s have a party!")
        self.assertNotIn('/event/event/2/course/list', self.response.text)
        self.get('/event/event/2/course/list')
        self.follow()
        self.assertPresence("Die Kursliste ist noch nicht öffentlich",
                            div='notifications')

    def test_course_state_visibility(self) -> None:
        self.login(USER_DICT['charly'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertNonPresence("fällt aus")
        self.traverse({'href': '/event/event/1/register'})
        f = self.response.forms['registerform']
        # Course ε. Backup-Kurs is cancelled in track 3 (but not visible by now)
        self.assertIn('5', [value for (value, checked, text)
                            in f['course_choice3_0'].options])

        self.logout()
        self.login(USER_DICT['garcia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertPresence("fällt aus")
        self.assertPresence("Info! Ausfallende Kurse werden nur für Orgas "
                            "hier markiert.", div='static-notifications')
        self.traverse({'href': '/event/event/1/change'})
        f = self.response.forms['changeeventform']
        f['is_course_state_visible'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/course/list'})
        self.assertNonPresence("Ausfallende Kurse werden nur für Orgas",
                               div='static-notifications')

        self.logout()
        self.login(USER_DICT['charly'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertPresence("fällt aus")
        self.traverse({'href': '/event/event/1/register'})
        f = self.response.forms['registerform']
        # Course ε. Backup-Kurs is cancelled in track 3 (but not visible by now)
        self.assertNotIn('5', [value for (value, checked, text)
                               in f['course_choice3_0'].options])

    @as_users("annika", "garcia")
    def test_part_summary_trivial(self) -> None:
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Log")
        self.assertTitle("Große Testakademie 2222: Log [1–4 von 4]")
        self.traverse("Veranstaltungsteile")
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Warmup", f['title_1'].value)
        self.submit(f)
        self.traverse("Datenfelder konfigurieren")
        f = self.response.forms['fieldsummaryform']
        self.submit(f)
        self.traverse("Log")
        self.assertTitle("Große Testakademie 2222: Log [1–4 von 4]")

    @as_users("annika")
    def test_part_summary_complex(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'description': 'Alle Veranstaltungen'},
                      {'description': 'CdE-Party 2050'},
                      {'description': 'Veranstaltungsteile'})
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_1001', f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Cooldown"
        f['shortname_-1'] = "cd"
        f['part_begin_-1'] = "2244-4-5"
        f['part_end_-1'] = "2233-6-7"
        f['fee_-1'] = "23456.78"
        f['track_create_-1_-1'].checked = True
        f['track_title_-1_-1'] = "Chillout Training"
        f['track_shortname_-1_-1'] = "Chillout"
        f['track_num_choices_-1_-1'] = "1"
        f['track_min_choices_-1_-1'] = "1"
        f['track_sortkey_-1_-1'] = "1"
        self.submit(f, check_notification=False)
        self.assertValidationError('part_end_-1', "Muss später als Beginn sein.")
        f['part_begin_-1'] = "2233-4-5"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Cooldown", f['title_1001'].value)
        self.assertEqual("cd", f['shortname_1001'].value)
        self.assertEqual("Chillout Training", f['track_title_1001_1001'].value)
        f['title_1001'] = "Größere Hälfte"
        f['fee_1001'] = "99.99"
        f['part_end_1001'] = "2222-6-7"
        self.submit(f, check_notification=False)
        self.assertValidationError('part_end_1001', "Muss später als Beginn sein")
        f['part_end_1001'] = "2233-4-5"
        self.submit(f)
        # and now for tracks
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_1001_1002', f.fields)
        f['track_title_1001_-1'] = "Spätschicht"
        f['track_shortname_1001_-1'] = "Spät"
        f['track_num_choices_1001_-1'] = "3"
        f['track_min_choices_1001_-1'] = "4"
        f['track_sortkey_1001_-1'] = "1"
        f['track_create_1001_-1'].checked = True
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'track_min_choices_1001_-1',
            "Muss kleiner oder gleich der Gesamtzahl von Kurswahlen sein.")
        f['track_min_choices_1001_-1'] = "2"
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Spätschicht", f['track_title_1001_1002'].value)
        f['track_title_1001_1002'] = "Nachtschicht"
        f['track_shortname_1001_1002'] = "Nacht"
        self.submit(f)
        f = self.response.forms['partsummaryform']
        self.assertEqual("Nachtschicht", f['track_title_1001_1002'].value)
        self.assertEqual("Nacht", f['track_shortname_1001_1002'].value)
        f['track_delete_1001_1002'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('track_title_1001_1002', f.fields)
        # finally deletion
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertEqual("Größere Hälfte", f['title_1001'].value)
        f['delete_1001'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (CdE-Party 2050)")
        f = self.response.forms['partsummaryform']
        self.assertNotIn('title_1001', f.fields)

    @as_users("garcia")
    def test_aposteriori_change_num_choices(self) -> None:
        # Increase number of course choices of track 2 ("Kaffekränzchen")
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_num_choices_2_2'] = "2"
        self.submit(f)

        # Change course choices as Orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)
        f['track2.course_choice_0'] = 3
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual('', f['track2.course_choice_1'].value)

        # Amend registration with new choice and check via course_choices
        self.traverse({'href': '/event/event/1/registration/status'},
                      {'href': '/event/event/1/registration/amend'})
        f = self.response.forms['amendregistrationform']
        self.assertEqual('3', f['course_choice2_0'].value)
        # Check preconditions for second part
        self.assertIsNotNone(f.get('course_choice1_3', default=None))
        f['course_choice2_1'] = 4
        self.submit(f)
        self.traverse({'href': '/event/event/1/course/choices'})
        f = self.response.forms['choicefilterform']
        f['track_id'] = 2
        f['course_id'] = 4
        f['position'] = 1
        self.submit(f)
        self.assertPresence("Garcia")

        # Reduce number of course choices of track 1 ("Morgenkreis")
        self.traverse({'href': '/event/event/1/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_num_choices_2_1'] = "3"
        f['track_min_choices_2_1'] = "3"
        self.submit(f)

        # Check registration as Orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'})
        self.assertPresence('3. Wahl')
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')

        # Amend registration
        self.traverse({'href': '/event/event/1/registration/status'})
        self.assertNonPresence('4. Wahl')
        self.assertNonPresence('ε. Backup')
        self.traverse({'href': '/event/event/1/registration/amend'})
        f = self.response.forms['amendregistrationform']
        self.assertEqual('1', f['course_choice1_2'].value)
        self.assertIsNone(f.get('course_choice1_3', default=None))
        f['course_choice1_0'] = 2
        f['course_choice1_1'] = 4
        self.submit(f)

        # Change registration as orga
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertIsNone(f.get('track1.course_choice_3', default=None))
        self.assertEqual('4', f['track1.course_choice_1'].value)
        self.assertEqual('1', f['track1.course_choice_2'].value)
        f['track1.course_choice_2'] = ''
        self.submit(f)
        self.assertNonPresence('Heldentum')

    @as_users("annika", "garcia")
    def test_change_event_fields(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        # fields
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('transportation', f['field_name_2'].value)
        self.assertNotIn('field_name_9', f.fields)
        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.str.value
        f['entries_-1'] = """all;everything goes
        vegetarian;no meat
        vegan;plants only"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual('food_stuff', f['field_name_1001'].value)
        self.assertEqual("""pedes;by feet
car;own car available
etc;anything else""", f['entries_2'].value)
        f['entries_2'] = """pedes;by feet
        broom;flying implements
        etc;anything else"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertEqual("""pedes;by feet
broom;flying implements
etc;anything else""", f['entries_2'].value)
        f['delete_1001'].checked = True
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['fieldsummaryform']
        self.assertNotIn('field_name_9', f.fields)

    @as_users("garcia")
    def test_event_fields_unique_name(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['delete_1'].checked = True
        f['create_-1'].checked = True
        f['field_name_-1'] = f['field_name_1'].value
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.str.value
        self.submit(f, check_notification=False)
        self.assertValidationError('field_name_-1', "Feldname nicht eindeutig.")
        f = self.response.forms['fieldsummaryform']
        self.assertIn('field_name_1', f.fields)
        self.assertNotIn('field_name_9', f.fields)

        f = self.response.forms['fieldsummaryform']
        # If the form would be valid in the first turn, we would need the
        # following (hacky) code to add the fields, which are normally added by
        # Javascript.
        # for field in (webtest.forms.Checkbox(f, 'input', 'create_-2', 100,
        #                                      value='True'),
        #               webtest.forms.Text(f, 'input', 'field_name_-2', 101),
        #               webtest.forms.Text(f, 'input', 'association_-2', 102),
        #               webtest.forms.Text(f, 'input', 'kind_-2', 103)):
        #     f.fields.setdefault(field.name, []).append(field)
        #     f.field_order.append((field.name, field))

        f['create_-1'].checked = True
        f['field_name_-1'] = "food_stuff"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.str.value
        f['create_-2'].checked = True
        f['field_name_-2'] = "food_stuff"
        f['association_-2'] = const.FieldAssociations.registration.value
        f['kind_-2'] = const.FieldDatatypes.str.value
        self.submit(f, check_notification=False)
        self.assertValidationError('field_name_-1', "Feldname nicht eindeutig.")
        self.assertValidationError('field_name_-2', "Feldname nicht eindeutig.")

    @as_users("garcia")
    def test_event_fields_datatype(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'].force_value("invalid")
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertValidationError(
            "kind_-1", "Ungültige Eingabe für Enumeration <enum 'FieldDatatypes'>.")
        f['create_-1'].checked = True
        f['field_name_-1'] = "invalid"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'].force_value(sum(x for x in const.FieldDatatypes))
        self.submit(f, check_notification=False)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.assertValidationError(
            "kind_-1",
            "Ungültige Eingabe für Enumeration <enum 'FieldDatatypes'>.")

    @as_users("annika", "garcia")
    def test_event_fields_change_datatype(self) -> None:
        # First, remove the "lodge" field from the questionaire and the event's,
        # so it can be deleted
        self.get("/event/event/1/questionnaire/config")
        f = self.response.forms['configurequestionnaireform']
        f['delete_5'].checked = True
        self.submit(f)
        self.get("/event/event/1/change")
        f = self.response.forms['changeeventform']
        f['lodge_field'] = ''
        self.submit(f)

        # Change datatype of "transportation" field to datetime and delete
        # options, delete and recreate "lodge" field with int type.
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['kind_2'] = const.FieldDatatypes.datetime.value
        f['entries_2'] = ""
        f['delete_3'].checked = True
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "lodge"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.int.value
        self.submit(f)

        # No page of the orga area should be broken by this
        self.traverse({'href': '/event/event/1/course/choices'},
                      {'href': '/event/event/1/stats'},
                      {'href': '/event/event/1/course/stats'},
                      {'href': '/event/event/1/checkin'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_lodge'].checked = True
        f['qsel_reg_fields.xfield_transportation'].checked = True
        self.submit(f)
        f = self.response.forms['queryform']
        f['qop_reg_fields.xfield_transportation'] = QueryOperators.empty.value
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/1/show'},
                      {'href': '/event/event/1/registration/1/change'})

    @as_users("garcia")
    def test_event_fields_boolean(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['entries_-1'] = """True;definitely
        False;no way!"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/questionnaire/config'})
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'].checked = True
        f['title_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "1001"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        f = self.response.forms['questionnaireform']
        f['notevil'] = "True"
        self.submit(f)

    @as_users("garcia")
    def test_event_fields_date(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/field/summary'})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "notevil"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.date.value
        f['entries_-1'] = """2018-01-01;new year
        2018-10-03;party!
        2018-04-01;April fools"""
        self.submit(f)
        self.assertTitle("Datenfelder konfigurieren (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/questionnaire/config'})
        f = self.response.forms['configurequestionnaireform']
        f['create_-1'].checked = True
        f['title_-1'] = "foobar"
        f['info_-1'] = "blaster master"
        f['field_id_-1'] = "1001"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        f = self.response.forms['questionnaireform']
        f['notevil'] = "2018-10-03"
        self.submit(f)

    @as_users("annika", "garcia")
    def test_event_fields_query_capital_letter(self) -> None:
        self.get("/event/event/1/field/summary")
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "CapitalLetters"
        f['association_-1'] = const.FieldAssociations.registration.value
        f['kind_-1'] = const.FieldDatatypes.str.value
        self.submit(f)
        self.get("/event/event/1/field/setselect?kind=1")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 1001
        self.submit(f)
        f = self.response.forms['fieldform']
        f['input1'] = "Example Text"
        f['input2'] = ""
        f['input3'] = "Other Text"
        self.submit(f)
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertPresence("Anton Armin A.")
        self.assertPresence("Garcia G.")
        self.assertPresence("Emilia E.")
        self.assertPresence("Example Text")
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_CapitalLetters'].checked = True
        f['qop_reg_fields.xfield_CapitalLetters'] = QueryOperators.nonempty.value
        f['qord_primary'] = 'reg_fields.xfield_CapitalLetters'
        self.submit(f)
        self.assertPresence("Anton Armin A.")
        self.assertPresence("Garcia G.")
        self.assertNonPresence("Emilia E.")
        self.assertPresence("Other Text")
        # Reset and do not specify operator to exhibit bug #1754
        self.traverse({'href': '/event/event/1/registration/query'})
        f = self.response.forms['queryform']
        f['qsel_reg_fields.xfield_CapitalLetters'].checked = True
        f['qord_primary'] = 'reg_fields.xfield_CapitalLetters'
        self.submit(f)
        self.assertPresence("Other Text")

    @storage
    @as_users("annika", "garcia")
    def test_change_minor_form(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['changeminorformform']
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
        f['ack_delete'].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Minderjährigenformular wurde entfernt.",
                            div="notifications")
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Formular vorhanden", div='minor-form')

    @as_users("annika", "ferdinand")
    def test_create_event(self) -> None:
        # Some helper to find dynamic ids
        def find_event_id(url: str) -> int:
            result = re.search(r'event/event/(\d+)', url)
            assert result is not None
            return int(result.group(1))

        find_parts = lambda f: [int(m.group(1))
                                for m in (re.match(r'delete_(\d+)', field)
                                          for field in f.fields
                                          if field is not None)
                                if m]
        find_tracks = lambda f: \
            [int(m.group(1))
             for m in (re.match(r'track_delete_\d+_(\d+)', field)
                       for field in f.fields
                       if field is not None)
             if m]

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/list'},
                      {'href': '/event/event/create'})
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Universale Akademie"
        f['institution'] = 1
        f['description'] = "Mit Co und Coco."
        f['shortname'] = "UnAka"
        f['part_begin'] = "2345-01-01"
        f['part_end'] = "1345-6-7"
        f['nonmember_surcharge'] = "6.66"
        f['notes'] = "Die spinnen die Orgas."
        f['orga_ids'] = "DB-10-8"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'orga_ids', "Einige dieser Nutzer sind keine Veranstaltungsnutzer.")
        self.assertValidationError('part_end', "Muss später als Beginn sein.")
        f = self.response.forms['createeventform']
        f['part_end'] = "2345-6-7"
        f['orga_ids'] = "DB-2-7, DB-7-8"
        self.submit(f)
        self.assertTitle("Universale Akademie")
        self.assertPresence("Mit Co und Coco.")
        self.assertPresence("Bertålotta")
        self.assertPresence("Garcia")

        # Check creation of parts and no tracks
        self.traverse({'href': '/event/event/{}/part/summary'
                      .format(find_event_id(self.response.request.url))})
        f = self.response.forms['partsummaryform']
        parts = find_parts(f)
        self.assertEqual(len(parts), 1)
        self.assertEqual('2345-01-01', f["part_begin_{}".format(parts[0])].value)
        self.assertEqual('2345-06-07', f["part_end_{}".format(parts[0])].value)
        tracks = find_tracks(f)
        self.assertEqual(len(tracks), 0)

        # Create another event with course track and orga mailinglist
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/list'},
                      {'href': '/event/event/create'})
        f = self.response.forms['createeventform']
        f['title'] = "Alternative Akademie"
        f['institution'] = 1
        f['shortname'] = ""
        f['part_begin'] = "2345-01-01"
        f['part_end'] = "2345-6-7"
        f['nonmember_surcharge'] = "4.20"
        f['orga_ids'] = "DB-1-9, DB-5-1"
        f['create_track'].checked = True
        f['create_orga_list'].checked = True
        f['create_participant_list'].checked = True
        self.submit(f, check_notification=False)
        # The following submissions with invalid shortnames also check for the
        # mailignlist creation bug in #1487.
        self.assertValidationError("shortname", "Darf nicht leer sein.")
        f['shortname'] = "²@³"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "shortname", "Darf nur aus druckbaren ASCII-Zeichen bestehen.")
        f['shortname'] = "AltAka"
        self.submit(f)
        self.assertTitle("Alternative Akademie")
        self.assertPresence("altaka@aka.cde-ev.de")
        self.traverse({'href': '/event/event/{}/part/summary'
                      .format(find_event_id(self.response.request.url))})
        f = self.response.forms['partsummaryform']
        tracks = find_tracks(f)
        self.assertEqual(len(tracks), 1)

    @as_users("annika", "garcia")
    def test_change_course(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'},
                      {'href': '/event/event/1/course/1/change'})
        self.assertTitle("Heldentum bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changecourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual(None, f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.assertEqual("1", f.get('active_segments', index=0).value)
        self.assertEqual(None, f.get('active_segments', index=1).value)
        self.assertEqual("3", f.get('active_segments', index=2).value)
        self.assertEqual("10", f['max_size'].value)
        self.assertEqual("2", f['min_size'].value)
        self.assertEqual("Wald", f['fields.room'].value)
        f['shortname'] = "Helden"
        f['nr'] = "ω"
        f['max_size'] = "21"
        f['segments'] = ['2', '3']
        f['active_segments'] = ['2']
        f['fields.room'] = "Canyon"
        self.submit(f)
        self.assertTitle("Kurs Helden (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/course/1/change'})
        f = self.response.forms['changecourseform']
        self.assertEqual(f['nr'].value, "ω")
        self.assertEqual(None, f.get('segments', index=0).value)
        self.assertEqual("2", f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.assertEqual(None, f.get('active_segments', index=0).value)
        self.assertEqual("2", f.get('active_segments', index=1).value)
        self.assertEqual(None, f.get('active_segments', index=2).value)
        self.assertEqual("21", f['max_size'].value)
        self.assertEqual("Canyon", f['fields.room'].value)

    @as_users("annika", "garcia")
    def test_create_delete_course(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'})
        self.assertTitle("Kursliste Große Testakademie 2222")
        self.assertPresence("Planetenretten für Anfänger")
        self.assertNonPresence("Abstract Nonsense")
        self.traverse({'href': '/event/event/1/course/stats'},
                      {'href': '/event/event/1/course/create'})
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['createcourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual("2", f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        f['title'] = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['instructors'] = "Alexander Grothendieck"
        f['notes'] = "transcendental appearence"
        f['segments'] = ['1', '3']
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertNonPresence("Kursfelder gesetzt.", div="notifications")
        self.assertPresence("transcendental appearence")
        self.assertPresence("Alexander Grothendieck")
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("math bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changecourseform']
        self.assertEqual("1", f.get('segments', index=0).value)
        self.assertEqual(None, f.get('segments', index=1).value)
        self.assertEqual("3", f.get('segments', index=2).value)
        self.traverse({'href': '/event/event/1/course/1001/show'})
        f = self.response.forms['deletecourseform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertNonPresence("Abstract Nonsense")

    @as_users("annika", "garcia")
    def test_create_course_with_fields(self) -> None:
        self.get("/event/event/1/course/create")
        self.assertTitle("Kurs hinzufügen (Große Testakademie 2222)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        f['nr'] = "ω"
        f['shortname'] = "math"
        f['fields.room'] = "Outside"
        self.submit(f)
        self.assertTitle("Kurs math (Große Testakademie 2222)")
        self.assertPresence("Outside")

    @as_users("charly", "daniel", "rowena")
    def test_register(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        # check participant info page for unregistered users
        participant_info_url = '/event/event/1/notes'
        self.get(participant_info_url)
        self.follow()
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Teilnehmer der Veranstaltung.", div='notifications')

        # now, start registration testing
        surcharge = "Da Du kein CdE-Mitglied bist, musst du einen zusätzlichen Beitrag"
        membership_fee = "Du kannst auch stattdessen Deinen regulären Mitgliedsbeitrag"
        self.traverse({'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        if self.user_in('charly'):
            self.assertNonPresence(surcharge)
            self.assertNonPresence(membership_fee)
        elif self.user_in('daniel'):
            self.assertPresence(surcharge, div="nonmember-surcharge")
            self.assertPresence(membership_fee, div="nonmember-surcharge")
        elif self.user_in('rowena'):
            self.assertPresence(surcharge, div="nonmember-surcharge")
            self.assertNonPresence(membership_fee)
        else:
            self.fail("Please reconfigure the users for the above checks.")

        f = self.response.forms['registerform']
        f['parts'] = ['1', '3']
        f['mixed_lodging'] = 'True'
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        self.assertIn('course_choice3_2', f.fields)
        self.assertNotIn('3', tuple(
            o for o, _, _ in f['course_choice3_1'].options))
        f['course_choice3_0'] = 2
        f['course_instructor3'] = 2
        # No second choice given -> expecting error
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertValidationError('course_choice3_1',
                                   "Du musst mindestens 2 Kurse wählen.")
        f['course_choice3_1'] = 2
        # Two equal choices given -> expecting error
        self.submit(f, check_notification=False)
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertValidationError(
            'course_choice3_1',
            "Du kannst diesen Kurs nicht als 1. und 2. Wahl wählen.")
        f['course_choice3_1'] = 4
        # Now, we did it right.
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        text = self.fetch_mail_content()
        if self.user_in('charly'):
            self.assertIn("461,49", text)
        elif self.user_in('daniel'):
            self.assertIn("466,49", text)
            self.assertIn(surcharge, text)
            self.assertIn(membership_fee, text)
        elif self.user_in('rowena'):
            self.assertIn("466,49", text)
            self.assertIn(surcharge, text)
            self.assertNotIn(membership_fee, text)
        else:
            self.fail("Please reconfigure the users for the above checks.")
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        self.assertNonPresence("Morgenkreis")
        self.assertNonPresence("Kaffeekränzchen")
        self.assertPresence("Arbeitssitzung")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice3_1'].value)
        self.assertEqual("", f['course_choice3_2'].value)
        self.assertEqual("2", f['course_instructor3'].value)
        self.assertPresence("Ich freu mich schon so zu kommen")
        f['notes'] = "Ich kann es kaum erwarten!"
        f['course_choice3_0'] = 4
        f['course_choice3_1'] = 1
        f['course_choice3_2'] = 5
        f['course_instructor3'] = 1
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Ich kann es kaum erwarten!")
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertEqual("4", f['course_choice3_0'].value)
        self.assertEqual("5", f['course_choice3_2'].value)
        self.assertEqual("1", f['course_instructor3'].value)
        self.assertPresence("Ich kann es kaum erwarten!")

        # check that participant info page is only visible for accepted registrations
        with self.assertRaises(IndexError):
            self.traverse({'href': participant_info_url})
        self.get(participant_info_url)
        self.follow()
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Kein Teilnehmer der Veranstaltung", div='notifications')

    @as_users("anton")
    def test_registration_status(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/status'})
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence(
            "Anmeldung erst mit Überweisung des Teilnehmerbeitrags")
        self.assertPresence("573,99 €")
        self.assertNonPresence("Warteliste")
        self.assertNonPresence("Eingeteilt in")
        self.assertPresence("α. Planetenretten für Anfänger")
        self.assertPresence("β. Lustigsein für Fortgeschrittene")
        self.assertPresence("Ich stimme zu, dass meine Daten")
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

    def test_register_no_registration_end(self) -> None:
        # Remove registration end (soft and hard) from Große Testakademie 2222
        self.login(USER_DICT['garcia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
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
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/register'})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        f = self.response.forms['registerform']
        f['notes'] = "Ich freu mich schon so zu kommen\n\nyeah!\n"
        f['parts'] = ['1']
        f['mixed_lodging'] = 'True'
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        text = self.fetch_mail_content()
        self.assertIn("10,50", text)
        self.traverse({'href': '/event/event/1/registration/amend'})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms['amendregistrationform']
        self.assertPresence("Ich freu mich schon so zu kommen")
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")

    @as_users("anton", "berta")
    @prepsql(
        "DELETE FROM event.course_choices;"
        "DELETE FROM event.registration_tracks;"
        "DELETE FROM event.registration_parts;"
        "DELETE FROM event.registrations;"
    )
    def test_register_with_fee_modifier(self) -> None:
        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Große Testakademie 2222"},
                      {'description': "Anmelden"})
        self.assertTitle("Anmeldung für Große Testakademie 2222")
        self.assertPresence("Ich bin unter 13 Jahre alt.")
        f = self.response.forms["registerform"]
        self.assertFalse(f['is_child'].checked)
        f['is_child'].checked = True
        f['parts'] = [1]
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Betrag 5,50 €")
        self.traverse({'description': "Ändern"})
        self.assertTitle("Anmeldung für Große Testakademie 2222 ändern")
        f = self.response.forms["amendregistrationform"]
        self.assertTrue(f['is_child'].checked is True)
        f['is_child'].checked = False
        self.submit(f)
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Betrag 10,50 €")

    @as_users("annika")
    def test_registration_questionnaire(self) -> None:
        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Große Testakademie 2222"},
                      {'description': "Veranstaltungsteile"})
        f = self.response.forms['partsummaryform']
        for part_id in [1, 2, 3]:
            field_name = f"fee_modifier_create_{part_id}_-1"
            self.assertNotIn(field_name, f.fields)

        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Alle Veranstaltungen"},
                      {'description': "CdE-Party 2050"})
        # Create new boolean registration fields.
        self.traverse({'description': "Datenfelder konfigurieren"})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "is_child"
        f['kind_-1'] = const.FieldDatatypes.bool.value
        f['association_-1'] = const.FieldAssociations.registration.value
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "plus_one"
        f['kind_-1'] = const.FieldDatatypes.bool.value
        f['association_-1'] = const.FieldAssociations.registration.value
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "partner"
        f['kind_-1'] = const.FieldDatatypes.str.value
        f['association_-1'] = const.FieldAssociations.registration.value
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "eats_meats"
        f['kind_-1'] = const.FieldDatatypes.str.value
        f['association_-1'] = const.FieldAssociations.registration.value
        f['entries_-1'] = """meat;Eat meat everyday!
        half-vegetarian;Sometimes
        vegetarian;Meat is Murder!
        vegan;Milk is Murder too!"""
        self.submit(f)
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        f['field_name_-1'] = "favorite_day"
        f['kind_-1'] = const.FieldDatatypes.date.value
        f['association_-1'] = const.FieldAssociations.registration.value
        self.submit(f)

        self.traverse({'description': "Veranstaltungsteile"})
        f = self.response.forms['partsummaryform']
        f['fee_modifier_create_4_-1'].checked = True
        f['fee_modifier_modifier_name_4_-1'] = "is_child"
        f['fee_modifier_amount_4_-1'] = "-10"
        f['fee_modifier_field_id_4_-1'] = 1001
        self.submit(f)
        f = self.response.forms['partsummaryform']
        f['fee_modifier_create_4_-1'].checked = True
        f['fee_modifier_modifier_name_4_-1'] = "plus_one"
        f['fee_modifier_amount_4_-1'] = "+14.99"
        f['fee_modifier_field_id_4_-1'] = 1002
        self.submit(f)

        self.traverse({'description': "Anmeldung konfigurieren"})
        f = self.response.forms['configureregistrationform']
        f['create_-1'].checked = True
        f['title_-1'] = "Ich bin unter 13 Jahre alt."
        f['field_id_-1'] = 1001
        self.submit(f)
        f = self.response.forms['configureregistrationform']
        f['create_-1'].checked = True
        f['title_-1'] = "Ich bringe noch jemanden mit."
        f['field_id_-1'] = 1002
        self.submit(f)
        f = self.response.forms['configureregistrationform']
        f['create_-1'].checked = True
        f['title_-1'] = "Name des Partners"
        f['field_id_-1'] = 1003
        self.submit(f)
        f = self.response.forms['configureregistrationform']
        f['create_-1'].checked = True
        f['title_-1'] = "Essgewohnheiten"
        f['field_id_-1'] = 1004
        self.submit(f)
        f = self.response.forms['configureregistrationform']
        f['create_-1'].checked = True
        f['title_-1'] = "Dein Lieblingstag"
        f['field_id_-1'] = 1005
        self.submit(f)

        self.traverse({'description': "Konfiguration"})
        f = self.response.forms['changeeventform']
        f['registration_start'] = now().isoformat()
        f['registration_soft_limit'] = ""
        f['registration_hard_limit'] = ""
        self.submit(f)

        self.traverse({'description': "Anmelden"})
        self.assertTitle("Anmeldung für CdE-Party 2050")
        f = self.response.forms['registerform']
        self.assertPresence("Ich bin unter 13 Jahre alt.",
                            div="registrationquestionnaire")
        f['is_child'].checked = True
        self.assertPresence("Ich bringe noch jemanden mit.",
                            div="registrationquestionnaire")
        f['plus_one'].checked = True
        self.assertPresence("Name des Partners", div="registrationquestionnaire")
        f['partner'] = ""
        self.assertPresence("Essgewohnheiten", div="registrationquestionnaire")
        f['eats_meats'] = "vegan"
        self.assertPresence("Dein Lieblingstag", div="registrationquestionnaire")
        # f['favorite_day'] = now().date().isoformat()
        self.submit(f, check_notification=False)
        f = self.response.forms['registerform']
        self.assertValidationError('partner', "Darf nicht leer sein.")
        f['partner'] = "Antonai Akademieleitfaden"
        self.assertValidationError('favorite_day', "Kein Datum gefunden.")
        f['favorite_day'] = now().date().isoformat()
        self.submit(f)
        self.assertTitle("Deine Anmeldung (CdE-Party 2050)")
        self.assertPresence("21,99 €", div="registrationsummary")

    @as_users("garcia")
    def test_questionnaire(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual("car", f['transportation'].value)
        f['transportation'] = "etc"
        self.assertEqual("", f['lodge'].value)
        f['lodge'] = "Bitte in ruhiger Lage.\nEcht."
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertEqual("etc", f['transportation'].value)
        self.assertEqual("Bitte in ruhiger Lage.\nEcht.", f['lodge'].value)

    def _create_event_field(self, fdata: CdEDBObject) -> None:
        self.traverse({'description': "Datenfelder konfigurieren"})
        f = self.response.forms['fieldsummaryform']
        f['create_-1'].checked = True
        for k, v in fdata.items():
            f[k + "_-1"] = v
        self.submit(f)

    @as_users("annika")
    def test_fee_modifiers(self) -> None:
        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Alle Veranstaltungen"},
                      {'description': "CdE-Party 2050"})
        self._create_event_field({
            "field_name": "is_child",
            "kind": const.FieldDatatypes.bool.value,
            "association": const.FieldAssociations.registration.value,
        })  # id 1001
        self._create_event_field({
            "field_name": "is_child2",
            "kind": const.FieldDatatypes.str.value,
            "association": const.FieldAssociations.registration.value,
        })  # id 1002
        self._create_event_field({
            "field_name": "is_child3",
            "kind": const.FieldDatatypes.bool.value,
            "association": const.FieldAssociations.course.value,
        })  # id 1003
        self.traverse({'description': "Veranstaltungsteile"})
        f: webtest.Form = self.response.forms["partsummaryform"]
        f['fee_modifier_create_4_-1'].checked = True
        f['fee_modifier_modifier_name_4_-1'] = "Ich bin Unter 13 Jahre alt."
        f['fee_modifier_amount_4_-1'] = "abc"
        self.assertEqual(
            ['', '1001'], [x[0] for x in f['fee_modifier_field_id_4_-1'].options])
        f['fee_modifier_field_id_4_-1'].force_value(1002)
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_amount_4_-1',
                                   "Ungültige Eingabe für eine Dezimalzahl")
        f['fee_modifier_modifier_name_4_-1'] = "is_child"
        f['fee_modifier_amount_4_-1'] = "-5"
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_field_id_4_-1',
                                   "Unpassendes Datenfeld für Beitragsmodifikator.")
        f['fee_modifier_field_id_4_-1'].force_value(1003)
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_field_id_4_-1',
                                   "Unpassendes Datenfeld für Beitragsmodifikator.")
        f['fee_modifier_field_id_4_-1'] = ''
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_field_id_4_-1',
                                   "Ungültige Eingabe für eine Ganzzahl")
        f['fee_modifier_field_id_4_-1'] = '1001'
        self.submit(f)

        self.traverse({'description': "Datenfelder konfigurieren"})
        f = self.response.forms['fieldsummaryform']
        f['kind_1002'] = const.FieldDatatypes.bool.value
        f['association_1003'] = const.FieldAssociations.registration.value
        self.submit(f)
        self.traverse({'description': "Veranstaltungsteile"})
        f = self.response.forms['partsummaryform']
        f['fee_modifier_create_4_-1'].checked = True
        f['fee_modifier_modifier_name_4_-1'] = "is_child"
        f['fee_modifier_amount_4_-1'] = "-7"
        f['fee_modifier_field_id_4_-1'] = 1001
        self.submit(f, check_notification=False)
        self.assertValidationError('fee_modifier_field_id_4_-1',
                                   "Nicht mehr als ein Beitragsmodifikator pro"
                                   " Veranstaltungsteil darf mit dem gleichen Feld"
                                   " verbunden sein.")
        self.assertValidationError(
            'fee_modifier_modifier_name_4_-1',
            "Nicht mehr als ein Beitragsmodifikator pro"
            " Veranstaltungsteil darf den selben Bezeichner haben.")
        f['fee_modifier_modifier_name_4_-1'] = "is_child2"
        f['fee_modifier_field_id_4_-1'] = 1002
        self.submit(f)

    @as_users("garcia")
    def test_waitlist(self) -> None:
        # 1. Create some new fields.
        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Große Testakademie 2222"})
        self._create_event_field({
            "field_name": "waitlist_position",
            "kind": const.FieldDatatypes.int.value,
            "association": const.FieldAssociations.registration.value,
        })  # id 1001
        self._create_event_field({
            "field_name": "wrong1",
            "kind": const.FieldDatatypes.str.value,
            "association": const.FieldAssociations.registration.value,
        })  # id 1002
        self._create_event_field({
            "field_name": "wrong2",
            "kind": const.FieldDatatypes.int.value,
            "association": const.FieldAssociations.course.value,
        })  # id 1003
        # 2. Check that the incorrect fields do not work as the waitlist field.
        self.traverse({'description': "Veranstaltungsteile"})
        f: webtest.Form = self.response.forms["partsummaryform"]
        self.assertEqual(
            [x[0] for x in f['waitlist_field_3'].options], ['', '8', '1001'])
        f['waitlist_field_1'].force_value(1002)
        self.submit(f, check_notification=False)
        self.assertValidationError('waitlist_field_1',
                                   "Unpassendes Datenfeld für die Warteliste.")
        f['waitlist_field_1'].force_value(1003)
        self.submit(f, check_notification=False)
        self.assertValidationError('waitlist_field_1',
                                   "Unpassendes Datenfeld für die Warteliste.")
        # 3. Set the correct waitlist field.
        f['waitlist_field_1'] = '1001'
        self.submit(f)
        # 4. Check that the default query applies the correct ordering.
        self.traverse({'description': 'Anmeldungen'},
                      {'description': 'Warteliste Wu'})
        f = self.response.forms['queryform']
        self.assertEqual(f['qord_primary'].value,
                         "reg_fields.xfield_waitlist_position")
        self.assertEqual(f['qop_part1.status'].value,
                         str(QueryOperators.equal.value))
        self.assertEqual(f['qval_part1.status'].value,
                         str(const.RegistrationPartStati.waitlist.value))
        self.assertPresence("Emilia E.", div="result-container")
        # 5. Check that participants can see their wailist position.
        self.logout()
        self.login(USER_DICT["emilia"])
        self.traverse({'href': "/event/event/1/registration/status"})
        self.assertTitle("Deine Anmeldung (Große Testakademie 2222)")
        self.assertPresence("Warteliste (Platz 1)", exact=True,
                            div="registration_status_part1")

    def test_participant_list(self) -> None:
        # first, check non-visibility for all participants
        self.login(USER_DICT['emilia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.get('/event/event/1/registration/list')
        self.follow()
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Fehler! Die Teilnehmerliste ist noch nicht "
                            "veröffentlicht.", div='notifications')
        self.logout()

        # now, check visibility for orgas
        self.login(USER_DICT['garcia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': 'event/event/1/registration/list'})
        self.assertTitle("Teilnehmerliste Große Testakademie 2222")
        self.assertPresence("Die Teilnehmerliste ist aktuell nur für Orgas und "
                            "Admins sichtbar.", div='static-notifications')
        self.assertPresence("Übersicht")
        self.assertPresence("Administrator")
        self.assertPresence("emilia@example.cde")
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
        self.logout()

        # check visibility for participant with list consent
        self.login(USER_DICT['emilia'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/list'})
        self.assertTitle("Teilnehmerliste Große Testakademie 2222")
        self.assertNonPresence("Die Teilnehmerliste ist aktuell nur für Orgas "
                               "und Admins sichtbar.", div='static-notifications')
        self.assertPresence("Warmup")
        self.assertPresence("Zweite Hälfte")
        self.traverse({'description': 'Zweite Hälfte'},)
        self.assertPresence("α. Heldentum (KL)")
        self.logout()

        # check non-visibility for participant without list consent
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/list'})
        self.assertTitle("Teilnehmerliste Große Testakademie 2222")
        self.assertPresence("Du kannst die Teilnehmerliste nicht sehen, da du "
                            "nicht zugestimmt hast, deine Daten auf der "
                            "Teilnehmerliste zur Verfügung zu stellen.")
        self.assertNonPresence("Übersicht")
        self.assertNonPresence("Zweite Hälfte")
        self.assertNonPresence("Anton")
        self.assertNonPresence("Stadt, Postleitzahl")

    @as_users("berta")
    def test_participant_list_event_with_one_part(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/2/show'},
                      {'href': '/event/event/2/registration/list'})
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Bisher gibt es keine Teilnehmer.")

        # add a registration
        self.traverse({'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/registration/add'})
        self.assertTitle("Neue Anmeldung (CdE-Party 2050)")
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-1-9"
        self.submit(f)

        # now test participant list
        self.traverse({'href': 'event/event/2/registration/list'})
        self.assertPresence("Vorname")
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
            self.assertPresence(user['given_names'], div="row-" + str(row))
            row += 1

    @as_users("garcia")
    def test_participant_list_sorting(self) -> None:
        # first, show courses on participant list
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Konfiguration'})
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
        self.traverse({'description': r"\sVorname\(n\)$"})
        self._sort_appearance([akira, anton, berta, emilia])
        # explicit sort by given names, descending
        self.traverse({'description': r"\sVorname\(n\)$"})
        self._sort_appearance([emilia, berta, anton, akira])
        # ... and again, ascending
        self.traverse({'description': r"\sVorname\(n\)$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sNachname$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sE-Mail-Adresse$"})
        self._sort_appearance([akira, anton, berta, emilia])
        self.traverse({'description': r"\sPostleitzahl, Stadt$"})
        self._sort_appearance([anton, berta, emilia, akira])

        self.traverse({'description': r"^Zweite Hälfte$"})
        self.traverse({'description': r"\sVorname\(n\)"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sNachname$"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sE-Mail-Adresse$"})
        self._sort_appearance([akira, anton, emilia])
        self.traverse({'description': r"\sPostleitzahl, Stadt$"})
        self._sort_appearance([anton, emilia, akira])
        self.traverse({'description': r"\sKurs$"})
        self._sort_appearance([anton, akira, emilia])

    @as_users("emilia", "garcia")
    def test_participant_list_profile_link(self) -> None:
        # first, show list for participants
        if self.user_in('emilia'):
            self.logout()
            self.login(USER_DICT['garcia'])
            self.traverse({'description': 'Veranstaltungen'},
                          {'description': 'Große Testakademie 2222'},
                          {'description': 'Konfiguration'})
            f = self.response.forms['changeeventform']
            f['is_participant_list_visible'].checked = True
            self.submit(f)
            self.logout()
            self.login(USER_DICT['emilia'])

        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Teilnehmerliste'})
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
        self.assertPresence("Diese Veranstaltung wurde abgesagt.",
                            div="static-notifications")
        self.traverse({'href': '/event/event/1/course/list'})
        self.assertPresence("Diese Veranstaltung wurde abgesagt.",
                            div="static-notifications")

        if self.user_in("annika"):
            # Make sure the index shows it as cancelled.
            # Orgas only see it as Organized event now.
            self.traverse({'href': '/event'})
            self.assertPresence("02.02.2222 – 30.11.2222, wurde abgesagt.")

            # Make sure the management page shows it as cancelled
            self.traverse({'href': '/event/event/list'})
            self.assertPresence("(3 Teile, wurde abgesagt)")

    @as_users("garcia")
    def test_batch_fee(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/batchfees'})
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['fee_data'] = """
573.99;DB-1-9;Admin;Anton;01.04.18
466.99;DB-5-1;Eventis;Emilia;01.04.18
589.49;DB-9-4;Iota;Inga;30.12.19
570.99;DB-11-6;K;Kalif;01.04.18
0.0;DB-666-1;Y;Z;77.04.18;stuff
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld.", div="line2_warnings")
        self.assertPresence("Zu viel Geld.", div="line3_warnings")
        self.assertPresence("Keine Anmeldung gefunden.", div="line4_problems")
        self.assertPresence("Kein Account mit ID 666 gefunden.", div="line5_problems")
        f = self.response.forms['batchfeesform']
        f['full_payment'].checked = True
        f['fee_data'] = """
573.98;DB-1-9;Admin;Anton;01.04.18
589.49;DB-5-1;Eventis;Emilia;04.01.18
451.00;DB-9-4;Iota;Inga;30.12.19
"""
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld.", div="line1_warnings")
        self.assertPresence("Zu viel Geld.", div="line3_warnings")
        f = self.response.forms['batchfeesform']
        f['force'].checked = True
        f['send_notifications'].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Nicht genug Geld", div="line1_warnings")
        self.assertPresence("Zu viel Geld", div="line3_warnings")
        # submit again because of checksum
        f = self.response.forms['batchfeesform']
        self.submit(f)
        mails = self.fetch_mail()
        self.assertEqual(3, len(mails))
        for i in range(3):
            text = self.fetch_mail_content(i)
            self.assertIn("Überweisung für die Veranstaltung", text)
            self.assertIn('"Große Testakademie 2222"', text)
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/1/show'})
        self.assertTitle("Anmeldung von Anton Armin A. Administrator"
                         " (Große Testakademie 2222)")
        self.assertPresence("Teilnehmerbeitrag ausstehend")
        self.assertPresence("Bereits bezahlter Betrag 573,98 €")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'})
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 04.01.2018")
        self.assertPresence("Bereits bezahlter Betrag 589,49 €")
        self.traverse({'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/4/show'})
        self.assertTitle("Anmeldung von Inga Iota (Große Testakademie 2222)")
        self.assertPresence("Bezahlt am 30.12.2019")
        self.assertPresence("Bereits bezahlter Betrag 451,00 €")

    @as_users("garcia")
    def test_batch_fee_regex(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/batchfee'})
        self.assertTitle("Überweisungen eintragen (Große Testakademie 2222)")
        f = self.response.forms['batchfeesform']
        f['fee_data'] = "666.66;DB-1-9;Fiese[;Zeichen{;01.04.18;überall("
        self.submit(f, check_notification=False)
        # Here the active regex chars where successfully neutralised

    @as_users("garcia")
    def test_registration_query(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_persona.family_name'] = QueryOperators.match.value
        f['qval_persona.family_name'] = 'e'
        f['qord_primary'] = 'reg.id'
        self.submit(f)
        self.assertTitle("\nAnmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [3]")
        self.assertPresence("Beispiel")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertEqual(
            "Einzelzelle",
            self.response.lxml.xpath('//*[@id="query-result"]//tr[1]/td[@data-col='
                                     '"lodgement2.title"]')[0].text.strip())
        self.assertEqual(
            "",
            self.response.lxml.xpath('//*[@id="query-result"]//tr[2]/td[@data-col='
                                     '"lodgement2.title"]')[0].text.strip())

    @as_users("annika")
    def test_course_query(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Kurse'},
                      {'description': 'Kurssuche'})
        self.assertTitle('Kurssuche (Große Testakademie 2222)')
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_track3.takes_place'] = QueryOperators.equal.value
        f['qval_track3.takes_place'] = True
        f['qop_track3.num_choices1'] = QueryOperators.greaterequal.value
        f['qval_track3.num_choices1'] = 2
        f['qord_primary'] = 'track2.num_choices0'
        self.submit(f)
        self.assertTitle('Kurssuche (Große Testakademie 2222)')
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Lang", div="result-container")
        self.assertPresence("Seminarraum 23", div="result-container")
        self.assertPresence("Kabarett", div="result-container")
        self.assertPresence("Theater", div="result-container")

    @as_users("garcia")
    def test_lodgement_query(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'Große Testakademie 2222'},
                      {'description': 'Unterkünfte'},
                      {'description': 'Unterkunftssuche'})
        self.assertTitle('Unterkunftssuche (Große Testakademie 2222)')
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        f['qop_part3.total_inhabitants'] = QueryOperators.greater.value
        f['qval_part3.total_inhabitants'] = 1
        f['qord_primary'] = 'lodgement_group.title'
        self.submit(f)
        self.assertPresence("Ergebnis [2]", div="query-results")
        self.assertPresence("Kalte Kammer", div="result-container")
        self.assertPresence("Warme Stube", div="result-container")

    @as_users("garcia")
    def test_multiedit(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertNotEqual(self.response.lxml.xpath(
            '//table[@id="query-result"]/tbody/tr[@data-id="2"]'), [])
        # Fake JS link redirection
        self.get("/event/event/1/registration/multiedit?reg_ids=2,3")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual(False, f['enable_part2.status'].checked)
        self.assertEqual(True, f['enable_part3.status'].checked)
        self.assertEqual("2", f['part3.status'].value)
        f['part3.status'] = 5
        self.assertEqual(False, f['enable_fields.transportation'].checked)
        self.assertEqual(True, f['enable_fields.may_reserve'].checked)
        f['enable_fields.transportation'].checked = True
        f['fields.transportation'] = "pedes"
        self.submit(f)
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'},
                      {'href': '/event/event/1/registration/2/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("4", f['part2.status'].value)
        self.assertEqual("5", f['part3.status'].value)
        self.assertEqual("pedes", f['fields.transportation'].value)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("2", f['part2.status'].value)
        self.assertEqual("5", f['part3.status'].value)
        self.assertEqual("pedes", f['fields.transportation'].value)

    @as_users("garcia")
    def test_show_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'})
        self.assertTitle(
            "\nAnmeldung von Emilia E. Eventis (Große Testakademie 2222)\n")
        self.assertPresence("56767 Wolkenkuckuksheim")
        self.assertPresence("Einzelzelle")
        self.assertPresence("α. Heldentum")
        self.assertPresence("Extrawünsche: Meerblick, Weckdienst")

    @as_users("garcia")
    def test_multiedit_wa1920(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        # Fake JS link redirection
        self.get("/event/event/1/registration/multiedit?reg_ids=1,2,3,4")
        self.assertTitle("Anmeldungen bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual(False, f['enable_track2.course_id'].checked)
        self.submit(f)
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/3/show'},
                      {'href': '/event/event/1/registration/3/change'})
        self.assertTitle(
            "Anmeldung von Garcia G. Generalis bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual("2", f['track2.course_id'].value)

    @as_users("garcia")
    def test_change_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'})
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.traverse({'description': 'Alle Anmeldungen'},
                      {'href': '/event/event/1/registration/2/show'},
                      {'href': '/event/event/1/registration/2/change'})
        self.assertTitle(
            "Anmeldung von Emilia E. Eventis bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Unbedingt in die Einzelzelle.", f['reg.orga_notes'].value)
        f['reg.orga_notes'] = "Wir wollen mal nicht so sein."
        self.assertEqual(True, f['reg.mixed_lodging'].checked)
        f['reg.mixed_lodging'].checked = False
        self.assertEqual("0.00", f['reg.amount_paid'].value)
        f['reg.amount_paid'] = "42.01"
        self.assertEqual("3", f['part1.status'].value)
        f['part1.status'] = 2
        self.assertEqual("4", f['part2.lodgement_id'].value)
        f['part2.lodgement_id'] = 3
        self.assertEqual("2", f['track3.course_choice_1'].value)
        f['track3.course_choice_1'] = 5
        self.assertEqual("pedes", f['fields.transportation'].value)
        f['fields.transportation'] = "etc"
        self.assertEqual("", f['fields.lodge'].value)
        f['fields.lodge'] = "Om nom nom nom"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")
        self.assertPresence("Om nom nom nom")
        self.traverse({'href': '/event/event/1/registration/2/change'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Wir wollen mal nicht so sein.", f['reg.orga_notes'].value)
        self.assertEqual(False, f['reg.mixed_lodging'].checked)
        self.assertEqual("42.01", f['reg.amount_paid'].value)
        self.assertEqual("2", f['part1.status'].value)
        self.assertEqual("3", f['part2.lodgement_id'].value)
        self.assertEqual("5", f['track3.course_choice_1'].value)
        self.assertEqual("etc", f['fields.transportation'].value)
        self.assertEqual("Om nom nom nom", f['fields.lodge'].value)

    @as_users("garcia")
    def test_add_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/registration/add'})
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms['addregistrationform']
        # Try to add an archived user.
        f['persona.persona_id'] = "DB-8-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id',
            "Dieser Benutzer existiert nicht oder ist archiviert.")
        # Try to add a non-existent user.
        f['persona.persona_id'] = "DB-10000-5"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id',
            "Dieser Benutzer existiert nicht oder ist archiviert.")
        # Try to add a non-event user.
        f['persona.persona_id'] = "DB-11-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona.persona_id', "Dieser Nutzer ist kein Veranstaltungsnutzer.")
        # Now add an actually valid user.
        f['persona.persona_id'] = USER_DICT['charly']['DB-ID']
        f['reg.orga_notes'] = "Du entkommst uns nicht."
        f['reg.mixed_lodging'].checked = False
        f['part1.status'] = 1
        f['part2.status'] = 3
        f['part3.status'] = -1
        f['part1.lodgement_id'] = 4
        f['track1.course_id'] = 5
        f['track1.course_choice_0'] = 5
        self.submit(f)
        self.assertTitle("\nAnmeldung von Charly C. Clown (Große Testakademie 2222)\n")
        self.assertPresence("Du entkommst uns nicht.")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual("Du entkommst uns nicht.", f['reg.orga_notes'].value)
        self.assertEqual(False, f['reg.mixed_lodging'].checked)
        self.assertEqual("1", f['part1.status'].value)
        self.assertEqual("3", f['part2.status'].value)
        self.assertEqual("-1", f['part3.status'].value)
        self.assertEqual("4", f['part1.lodgement_id'].value)
        self.assertEqual("5", f['track1.course_id'].value)
        self.assertEqual("5", f['track1.course_choice_0'].value)

    @as_users("garcia")
    def test_add_illegal_registration(self) -> None:
        self.get("/event/event/1/registration/add")
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = USER_DICT['charly']['DB-ID']
        f["part1.status"] = 1
        f["track1.course_choice_0"] = 5
        f["track1.course_choice_1"] = 5
        self.submit(f, check_notification=False)
        self.assertTitle("Neue Anmeldung (Große Testakademie 2222)")
        self.assertValidationError('track1.course_choice_1',
                                   "Bitte verschiedene Kurse wählen.")
        f = self.response.forms["addregistrationform"]
        f["track1.course_choice_1"] = 4
        self.submit(f)
        self.assertTitle("\nAnmeldung von Charly C. Clown (Große Testakademie 2222)\n")
        self.assertEqual("5", f['track1.course_choice_0'].value)
        self.assertEqual("4", f['track1.course_choice_1'].value)

    @as_users("berta")
    def test_add_empty_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'description': 'CdE-Party 2050'},
                      {'description': 'Anmeldungen'},
                      {'description': 'Teilnehmer hinzufügen'})
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-5-1"
        f['reg.parental_agreement'].checked = True
        f['part4.status'] = -1
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia E. Eventis (CdE-Party 2050)")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changeregistrationform']
        self.assertEqual(True, f['reg.parental_agreement'].checked)

    @as_users("garcia")
    def test_delete_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertPresence("Anton Armin A.")
        self.traverse({'href': '/event/event/1/registration/1/show'})
        self.assertTitle(
            "Anmeldung von Anton Armin A. Administrator (Große Testakademie 2222)")
        f = self.response.forms['deleteregistrationform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'description': 'Alle Anmeldungen'})
        self.assertNonPresence("Anton Armin A.")

    @as_users("garcia")
    def test_profile_link(self) -> None:
        # Test if I can view the profile of searchable members
        self.get('/event/event/1/registration/5/show')
        self.traverse({'description': 'DB-100-7'})
        # Test privacy: that I can see exactly the information I should see
        self.assertTitle("Akira Abukara")
        self.assertPresence("Geschlecht")
        self.assertPresence("sonstiges")
        # self.assertPresence("Mitgliedschaft")
        self.assertNonPresence("Sichtbarkeit")
        self.assertPresence("28.12.2019")
        self.assertPresence("Tokyo Japan")
        self.assertNonPresence("Ich bin ein „Künstler“; im weiteren Sinne.")

    @as_users("garcia")
    def test_lodgements(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'})
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertPresence("Kalte Kammer")
        self.traverse({'href': '/event/event/1/lodgement/4/show'})
        self.assertTitle("Unterkunft Einzelzelle (Große Testakademie 2222)")
        self.assertPresence("Emilia")
        self.traverse({'href': '/event/event/1/lodgement/4/change'})
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("1", f['regular_capacity'].value)
        f['regular_capacity'] = 3
        self.assertEqual("", f['notes'].value)
        f['notes'] = "neu mit Anbau"
        self.assertEqual("high", f['fields.contamination'].value)
        f['fields.contamination'] = "medium"
        self.submit(f)
        self.traverse({'href': '/event/event/1/lodgement/4/change'})
        self.assertTitle("Unterkunft Einzelzelle bearbeiten (Große Testakademie 2222)")
        f = self.response.forms['changelodgementform']
        self.assertEqual("3", f['regular_capacity'].value)
        self.assertEqual("neu mit Anbau", f['notes'].value)
        self.assertEqual("medium", f['fields.contamination'].value)
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.traverse({'href': '/event/event/1/lodgement/3/show'})
        self.assertTitle("Unterkunft Kellerverlies (Große Testakademie 2222)")
        f = self.response.forms['deletelodgementform']
        self.submit(f)
        self.assertTitle("Unterkünfte (Große Testakademie 2222)")
        self.assertNonPresence("Kellerverlies")
        self.traverse({'href': '/event/event/1/lodgement/create'})
        f = self.response.forms['createlodgementform']
        f['title'] = "Zelte"
        f['regular_capacity'] = 0
        f['camping_mat_capacity'] = 20
        f['notes'] = "oder gleich unter dem Sternenhimmel?"
        f['fields.contamination'] = "low"
        self.submit(f)
        self.assertTitle("Unterkunft Zelte (Große Testakademie 2222)")
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("Unterkunft Zelte bearbeiten (Große Testakademie 2222)")
        self.assertPresence("some radiation")
        f = self.response.forms['changelodgementform']
        self.assertEqual('20', f['camping_mat_capacity'].value)
        self.assertEqual("oder gleich unter dem Sternenhimmel?",
                         f['notes'].value)

    @as_users("garcia")
    def test_lodgement_capacities(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'})
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
    def test_lodgement_groups(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'},
                      {'href': '/event/event/1/lodgement/group/summary'})
        self.assertTitle("Unterkunftgruppen (Große Testakademie 2222)")

        # First try with invalid (empty name)
        f = self.response.forms["lodgementgroupsummaryform"]
        self.assertEqual(f['title_1'].value, "Haupthaus")
        f['create_-1'] = True
        f['title_1'] = "Hauptgebäude"
        f['delete_2'] = True
        self.submit(f, check_notification=False)
        self.assertTitle("Unterkunftgruppen (Große Testakademie 2222)")
        self.assertValidationError('title_-1', "Darf nicht leer sein.")

        # Now, it should work
        f = self.response.forms["lodgementgroupsummaryform"]
        f['title_-1'] = "Zeltplatz"
        f['create_-2'] = True
        f['title_-2'] = "Altes Schloss"
        self.submit(f)

        # Check (non-)existence of groups in lodgement overview
        self.traverse({'href': '/event/event/1/lodgement/overview'})
        self.assertPresence("Hauptgebäude")
        self.assertPresence("Altes Schloss")
        self.assertNonPresence("AußenWohnGruppe")
        self.assertPresence("Warme Stube")
        # Check correct unassignment of "Warme Stube"
        self.traverse({'href': '/event/event/1/lodgement/1/change'})
        f = self.response.forms['changelodgementform']
        self.assertEqual(f['group_id'].value, "")

        # Assign "Kellerverlies" to "Altes Schloss"
        self.traverse({'href': '/event/event/1/lodgement/overview'},
                      {'href': '/event/event/1/lodgement/3/change'})
        f = self.response.forms['changelodgementform']
        self.assertEqual(f['group_id'].value, "")
        f['group_id'] = "1002"  # Should be the "Altes Schloss"
        self.submit(f)
        self.assertTitle("Unterkunft Kellerverlies (Große Testakademie 2222)")
        self.assertPresence("Altes Schloss")

    @as_users("garcia")
    def test_field_set(self) -> None:
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
        self.assertEqual("pedes", f['input2'].value)
        f['input2'] = "etc"
        self.submit(f)
        self.traverse({'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 2
        self.submit(f)
        self.assertTitle("Datenfeld transportation setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("etc", f['input2'].value)
        # Value of Inga should not have changed
        self.assertEqual("etc", f['input4'].value)

        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("", f['input4'].value)
        f['input4'] = "Test\nmit\n\nLeerzeilen"
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/query'},
                      {'href': '/event/event/1/field/setselect'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 3
        self.submit(f)
        self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Test\nmit\n\nLeerzeilen", f['input4'].value)

        # now, we perform some basic checks for course-associated fields
        self.traverse({'href': '/event/event/1/course/stats'},
                      {'description': 'Kurssuche'},
                      {'description': 'Datenfeld setzen'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertPresence("Zu ändernde Kurse")
        self.assertPresence("α Heldentum")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 5
        self.submit(f)
        self.assertTitle("Datenfeld room setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("Nirwana", f['input5'].value)
        f['input5'] = "Ganz wo anders!"
        self.submit(f)
        self.assertNonPresence("Nirwana")
        self.assertPresence("Ganz wo anders!")

        # now, we perform some basic checks for lodgement-associated fields
        self.traverse({'href': '/event/event/1/lodgement/overview'},
                      {'description': 'Unterkunftssuche'},
                      {'description': 'Datenfeld setzen'})
        self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
        self.assertPresence("Zu ändernde Unterkünfte")
        self.assertPresence("Einzelzelle, Haupthaus")
        f = self.response.forms['selectfieldform']
        f['field_id'] = 6
        self.submit(f)
        self.assertTitle("Datenfeld contamination setzen (Große Testakademie 2222)")
        f = self.response.forms['fieldform']
        self.assertEqual("high", f['input1'].value)
        f['input1'] = "medium"
        self.submit(f)
        self.assertPresence("elevated level of radiation ")

    @as_users("garcia")
    def test_stats(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/stats'},)
        self.assertTitle("Statistik (Große Testakademie 2222)")

    @as_users("garcia")
    def test_course_stats(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/stats'},)
        self.assertTitle("Kurse verwalten (Große Testakademie 2222)")
        self.assertPresence("Heldentum")
        self.assertPresence("1")
        self.assertPresence("δ")

    @as_users("garcia")
    def test_course_choices(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},)
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        self.assertPresence("Morgenkreis", div="course_choice_table")
        self.assertPresence("Morgenkreis", div="assignment-options")
        self.assertPresence("Heldentum")
        self.assertPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 3
        self.submit(f)
        self.assertPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = 1
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertNonPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['track_id'] = ''
        f['course_id'] = 2
        f['position'] = -7
        self.submit(f)
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Inga")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        self.submit(f)
        self.assertNonPresence("Inga")
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Garcia")
        self.assertPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = 0
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton Armin")
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
        self.assertPresence("Anton Armin")
        self.assertPresence("Inga")
        self.assertNonPresence("Garcia")
        self.assertNonPresence("Emilia")
        f = self.response.forms['choicefilterform']
        f['course_id'] = 4
        f['position'] = -6
        f['track_id'] = 3
        self.submit(f)
        self.assertNonPresence("Anton Armin")
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
        self.assertNonPresence("Anton Armin")
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

    @as_users("garcia")
    def test_automatic_assignment(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},)
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3, 4]
        f['assign_track_ids'] = [1, 2, 3]
        f['assign_action'] = -5
        self.submit(f)

    @as_users("garcia")
    def test_course_choices_filter_persistence(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},)
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
        self.assertNonPresence("Anton Armin")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

    @as_users("garcia")
    def test_course_choices_problems(self) -> None:
        self.traverse({'href': '/event/$'}, {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'}, )
        self.assertTitle("Kurswahlen (Große Testakademie 2222)")
        # Assigning Anton and Emilia to their 3rd choice (which is not present)
        # should not raise an exception but a warning
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2]
        f['assign_track_ids'] = [3]
        f['assign_action'] = 2
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertPresence("Emilia E. Eventis hat keine 3. Kurswahl",
                            div="notifications")
        self.assertPresence("0 von 2 Anmeldungen gespeichert",
                            div="notifications")

        # Deleting Anton's choices and doing an automatic assignment should also
        # raise a warning (but no exception)
        self.traverse({'href': '/event/event/1/registration/1/show'},
                      {'href': '/event/event/1/registration/1/change'})
        f = self.response.forms['changeregistrationform']
        f['track3.course_choice_0'] = ''
        f['track3.course_choice_1'] = ''
        self.submit(f)
        self.traverse({'href': '/event/event/1/course/choices'})
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 3]
        f['assign_track_ids'] = [3]
        f['assign_action'] = -5
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertPresence("Keine Kurswahlen für Anton Armin A. Administrator",
                            div="notifications")
        self.assertPresence("1 von 2 Anmeldungen gespeichert",
                            div="notifications")

    @as_users("garcia")
    def test_assignment_checks(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/choices'},
                      {'href': '/event/event/1/course/checks'},)
        self.assertTitle("Kurseinteilungsprüfung (Große Testakademie 2222)")
        self.assertPresence("Ausfallende Kurse mit Teilnehmern")
        self.assertPresence("Kabarett", div='problem_cancelled_with_p')
        self.assertPresence("Teilnehmer ohne Kurs")
        self.assertPresence("Anton", div='problem_no_course')

        # Assigning Garcia to "Backup" in "Kaffekränzchen" fixes 'cancelled'
        # problem, but raises 'unchosen' problem
        self.get('/event/event/1/registration/3/change')
        f = self.response.forms['changeregistrationform']
        f['track2.course_id'] = "5"
        self.submit(f)
        # Assign Garcia and Anton to their 1. choice to fix 'no_course' issues;
        # accidentally, also assign emilia (instructor) to 1. choice ;-)
        self.get('/event/event/1/course/choices')
        f = self.response.forms['choiceactionform']
        f['registration_ids'] = [1, 2, 3]
        f['assign_track_ids'] = [1, 3]
        f['assign_action'] = 0
        self.submit(f)

        self.traverse({'href': '/event/event/1/course/checks'})
        self.assertPresence("Teilnehmer in einem ungewählten Kurs")
        self.assertPresence("Garcia", div='problem_unchosen')
        self.assertPresence("Kursleiter im falschen Kurs")
        self.assertPresence("Emilia", div='problem_instructor_wrong_course')
        self.assertPresence("α", div='problem_instructor_wrong_course')
        self.assertPresence("δ", div='problem_instructor_wrong_course')

    @storage
    @as_users("garcia")
    def test_downloads(self) -> None:
        magic_bytes = {
            'pdf': b"%PDF",
            'targz': b"\x1f\x8b",
            'zip': b"PK\x03\x04",
        }

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
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
            href='/event/event/1/download/lodgementlists\\?runs=0')
        self.assertTrue(self.response.body.startswith(magic_bytes['targz']))
        self.assertLess(1000, len(self.response.body))
        self.response = save.click(
            href='/event/event/1/download/lodgementlists\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # course puzzle
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.assertPresence('Planetenretten für Anfänger')
        self.response = save.click(href='/event/event/1/download/coursepuzzle\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # lodgement puzzle
        self.response = save.click(
            href='/event/event/1/download/lodgementpuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.assertPresence('Kalte Kammer')
        self.response = save.click(
            href='/event/event/1/download/lodgementpuzzle\\?runs=2')
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))

        # participant lists
        # public list
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=0', index=0)
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        self.assertNonPresence('Garcia G.')
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=2', index=0)
        self.assertTrue(self.response.body.startswith(magic_bytes['pdf']))
        self.assertLess(1000, len(self.response.body))
        # orga list
        self.response = save.click(
            href='/event/event/1/download/participantlist\\?runs=0&orgas_only=True',
            index=0)
        self.assertPresence('documentclass')
        self.assertPresence('Heldentum')
        self.assertPresence('Emilia E.')
        self.assertPresence('Garcia G.')

        # export
        # partial event export
        self.response = save.click(href='/event/event/1/download/partial')
        self.assertPresence('"kind": "partial",')
        self.assertPresence('"title": "Langer Kurs",')
        # registrations
        self.response = save.click(href='/event/event/1/download/csv_registrations')
        self.assertIn('reg.id;persona.id;persona.given_names;', self.response.text)
        # courselist
        self.response = save.click(href='/event/event/1/download/csv_courses')
        self.assertIn('course.id;course.course_id;course.nr;', self.response.text)
        # lodgementlist
        self.response = save.click(href='/event/event/1/download/csv_lodgements')
        self.assertIn(
            'lodgement.id;lodgement.lodgement_id;lodgement.title;', self.response.text)
        # dokuteam courselist
        self.response = save.click(href='/event/event/1/download/dokuteam_course')
        self.assertPresence('|cde')
        # dokuteam participant list
        self.response = save.click(href='event/event/1/download/dokuteam_participant')
        self.assertTrue(self.response.body.startswith(magic_bytes['zip']))
        self.assertLess(500, len(self.response.body))

    @storage
    @as_users("garcia")
    def test_download_export(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")

        # test mechanism to reduce unwanted exports of unlocked events
        f = self.response.forms['fullexportform']
        f['agree_unlocked_download'].checked = False
        self.submit(f, check_notification=False)
        info_msg = ("Bestätige, das du einen Export herunterladen willst, "
                    "obwohl die Veranstaltung nicht gesperrt ist.")
        self.assertPresence(info_msg, div='notifications')

        f['agree_unlocked_download'].checked = True
        self.submit(f)
        with open(self.testfile_dir / "event_export.json") as datafile:
            expectation = json.load(datafile)
        result = json.loads(self.response.text)
        expectation['timestamp'] = result['timestamp']  # nearly_now() won't do
        self.assertEqual(expectation, result)

    @as_users("garcia")
    def test_download_csv(self) -> None:

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'},)
        save = self.response
        self.response = save.click(href='/event/event/1/download/csv_registrations')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=CustomCSVDialect))
        self.assertIn('2222-01-01', tuple(row['persona.birthday']
                                          for row in result))
        self.assertIn('high', tuple(row['lodgement3.xfield_contamination']
                                    for row in result))
        self.assertIn(const.RegistrationPartStati.cancelled.name,
                      tuple(row['part2.status'] for row in result))
        self.response = save.click(href='/event/event/1/download/csv_courses')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=CustomCSVDialect))
        self.assertIn('ToFi & Co', tuple(row['course.instructors'] for row in result))
        self.assertTrue(any(
            row['track2.is_offered'] == 'True'
            and row['track2.takes_place'] == 'False' for row in result))
        self.assertIn('Seminarraum 42', tuple(row['course_fields.xfield_room']
                                              for row in result))
        self.response = save.click(href='/event/event/1/download/csv_lodgements')

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=CustomCSVDialect))
        self.assertIn(
            '100', tuple(row['lodgement.camping_mat_capacity'] for row in result))
        self.assertIn('low', tuple(row['lodgement_fields.xfield_contamination']
                                   for row in result))

    @as_users("berta")
    def test_no_downloads(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'CdE-Party 2050'},
                      {'description': 'Downloads'})
        self.assertTitle("Downloads zur Veranstaltung CdE-Party 2050")

        # first check empty csv
        self.traverse({'href': '/event/event/2/download/csv_registrations'})
        self.assertPresence('Leere Datei.', div='notifications')
        self.traverse({'href': '/event/event/2/download/csv_courses'})
        self.assertPresence('Leere Datei.', div='notifications')
        self.traverse({'href': '/event/event/2/download/csv_lodgements'})
        self.assertPresence('Leere Datei.', div='notifications')

        # now check empty pdfs
        self.traverse({'href': '/event/event/2/download/nametag\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')
        self.traverse({'href': '/event/event/2/download/courselists\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')
        self.traverse({'href': '/event/event/2/download/lodgementlists\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')
        self.traverse({'href': '/event/event/2/download/coursepuzzle\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')
        self.traverse({'href': '/event/event/2/download/lodgementpuzzle\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')
        self.traverse({'href': '/event/event/2/download/participantlist\\?runs=2'})
        self.assertPresence('Leeres PDF.', div='notifications')

        # but the latex source code should still be available
        save = self.response
        self.response = save.click(href='/event/event/2/download/nametag\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.response = save.click(href='/event/event/2/download/courselists\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.response = save.click(
            href='/event/event/2/download/lodgementlists\\?runs=0')
        self.assertTrue(self.response.body.startswith(b"\x1f\x8b"))
        self.response = save.click(href='/event/event/2/download/coursepuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.response = save.click(
            href='/event/event/2/download/lodgementpuzzle\\?runs=0')
        self.assertPresence('documentclass')
        self.response = save.click(
            href='/event/event/2/download/participantlist\\?runs=0$')
        self.assertPresence('documentclass')

    @as_users("garcia")
    def test_questionnaire_manipulation(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/change'})
        self.assertTitle("Große Testakademie 2222 – Konfiguration")
        f = self.response.forms['changeeventform']
        f['use_additional_questionnaire'].checked = True
        self.submit(f)
        self.traverse({'href': '/event/event/1/registration/questionnaire'})
        self.assertTitle("Fragebogen (Große Testakademie 2222)")
        f = self.response.forms['questionnaireform']
        self.assertNotIn("may_reserve", f.fields)
        self.traverse({'href': '/event/event/1/questionnaire/config'})
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['configurequestionnaireform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("3", f['input_size_5'].value)
        f['input_size_5'] = 3
        self.assertEqual("2", f['field_id_4'].value)
        f['field_id_4'] = ""
        self.assertEqual("Weitere Überschrift", f['title_3'].value)
        f['title_3'] = "Immernoch Überschrift"
        self.assertEqual("mit Text darunter", f['info_0'].value)
        f['info_0'] = "mehr Text darunter\nviel mehr"
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['configurequestionnaireform']
        self.assertEqual("3", f['field_id_5'].value)
        self.assertEqual("3", f['input_size_5'].value)
        self.assertEqual("Hauswunsch", f['title_5'].value)
        self.assertEqual("", f['field_id_4'].value)
        self.assertEqual("Immernoch Überschrift", f['title_3'].value)
        self.assertEqual("mehr Text darunter\nviel mehr", f['info_0'].value)
        f['delete_4'].checked = True
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['configurequestionnaireform']
        self.assertNotIn("field_id_5", f.fields)
        self.assertEqual("Unterüberschrift", f['title_0'].value)
        self.assertEqual("nur etwas Text", f['info_2'].value)
        self.assertEqual("3", f['field_id_4'].value)
        self.assertEqual("3", f['input_size_4'].value)
        self.assertEqual("Hauswunsch", f['title_4'].value)
        f['create_-1'].checked = True
        f['field_id_-1'] = 4
        f['title_-1'] = "Input"
        f['readonly_-1'].checked = True
        f['input_size_-1'] = 2
        self.submit(f)
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['configurequestionnaireform']
        self.assertIn("field_id_5", f.fields)
        self.assertEqual("4", f['field_id_5'].value)
        self.assertEqual("Input", f['title_5'].value)

    @as_users("garcia")
    def test_questionnaire_reorder(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/questionnaire/config'},
                      {'href': '/event/event/1/questionnaire/reorder'})
        f = self.response.forms['reorderquestionnaireform']
        self.assertEqual(f['order'].value, "0,1,2,3,4,5")
        f['order'] = "Hallo, Kekse"
        self.submit(f, check_notification=False)
        self.assertValidationError('order', "Ungültige Eingabe für eine Ganzzahl.")
        # row index out of range
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "-1,6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Reihe darf nur genau einmal vorkommen.")
        # row included twice
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "0,1,1,3,4,5"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Reihe darf nur genau einmal vorkommen.")
        # not all rows included
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = "0,1,2"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "order", "Jede Reihe darf nur genau einmal vorkommen.")
        f = self.response.forms['reorderquestionnaireform']
        f['order'] = '5,3,1,0,2,4'
        self.submit(f)
        self.assertTitle("Fragebogen umordnen (Große Testakademie 2222)")
        self.traverse({'description': 'Fragebogen konfigurieren'})
        f = self.response.forms['configurequestionnaireform']
        self.assertTitle("Fragebogen konfigurieren (Große Testakademie 2222)")
        self.assertEqual("3", f['field_id_0'].value)
        self.assertEqual("2", f['field_id_5'].value)
        self.assertEqual("1", f['field_id_2'].value)
        self.assertEqual("", f['field_id_3'].value)

    @as_users("garcia")
    def test_checkin(self) -> None:
        # multi-part
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/checkin'})
        self.assertTitle("Checkin (Große Testakademie 2222)")
        f = self.response.forms['checkinform2']
        self.submit(f)
        self.assertTitle("Checkin (Große Testakademie 2222)")
        self.assertNotIn('checkinform2', self.response.forms)
        # single-part
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/3/show'},
                      {'href': '/event/event/3/checkin'})
        self.assertTitle("Checkin (CyberTestAkademie)")
        self.assertPresence("Daniel D. Dino")
        self.assertPresence("Olaf Olafson")
        f = self.response.forms['checkinform7']
        self.submit(f)
        self.assertTitle("Checkin (CyberTestAkademie)")
        self.assertNotIn('checkinform7', self.response.forms)

    @as_users("garcia")
    def test_checkin_concurrent_modification(self) -> None:
        # Test the special measures of the 'Edit' button at the Checkin page,
        # that ensure that the checkin state is not overriden by the
        # change_registration form
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/checkin'})
        f = self.response.forms['checkinform2']
        self.traverse({'href': '/event/event/1/registration/2/change'})
        f2 = self.response.forms['changeregistrationform']
        f2['part2.lodgement_id'] = 3
        self.submit(f)
        self.submit(f2)
        # Check that the change to lodgement was committed ...
        self.assertPresence("Kellerverlies")
        # ... but the checkin is still valid
        self.assertPresence("eingecheckt:")

    @as_users("garcia")
    def test_manage_attendees(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/course/list'},
                      {'href': '/event/event/1/course/1/show'})
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.traverse({'href': '/event/event/1/course/1/manage'})
        self.assertTitle("\nKursteilnehmer für Kurs Planetenretten für Anfänger"
                         " verwalten (Große Testakademie 2222)\n")
        f = self.response.forms['manageattendeesform']
        f['new_1'] = "3"
        f['delete_3_4'] = True
        self.submit(f)
        self.assertTitle("Kurs Heldentum (Große Testakademie 2222)")
        self.assertPresence("Garcia G.")
        self.assertNonPresence("Inga")

    @as_users("garcia")
    def test_manage_inhabitants(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/lodgement/overview'},
                      {'href': '/event/event/1/lodgement/2/show'})
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Inga")
        self.assertNonPresence("Emilia")
        self.traverse({'href': '/event/event/1/lodgement/2/manage'})
        self.assertTitle("\nBewohner der Unterkunft Kalte Kammer verwalten"
                         " (Große Testakademie 2222)\n")
        f = self.response.forms['manageinhabitantsform']
        f['new_1'] = ""
        f['delete_1_3'] = True
        f['new_2'] = ""
        f['new_3'].force_value(2)
        f['delete_3_4'] = True
        self.submit(f)
        self.assertTitle("Unterkunft Kalte Kammer (Große Testakademie 2222)")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertNonPresence("Inga")

    @as_users("annika", "garcia")
    def test_lock_event(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist nicht gesperrt.")
        f = self.response.forms["lockform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence(
            "Die Veranstaltung ist zur Offline-Nutzung gesperrt.")

    @as_users("annika", "garcia")
    def test_unlock_event(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms["lockform"]
        self.submit(f)
        saved = self.response
        data = saved.click(href='/event/event/1/export$').body
        data = data.replace(b"Gro\\u00dfe Testakademie 2222",
                            b"Mittelgro\\u00dfe Testakademie 2222")
        data = data.replace(b'"CDEDB_EXPORT_EVENT_VERSION": 13,', b'')
        self.response = saved
        self.assertPresence(
            "Die Veranstaltung ist zur Offline-Nutzung gesperrt.")
        f = self.response.forms['unlockform']
        f['json'] = webtest.Upload("event_export.json", data,
                                   "application/octet-stream")
        self.submit(f)
        self.assertTitle("Mittelgroße Testakademie 2222")
        self.assertPresence("Die Veranstaltung ist nicht gesperrt.")

    @storage
    @as_users("annika", "garcia")
    def test_partial_import_normal(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/import'})
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        with open(self.testfile_dir / "partial_event_import.json", 'rb') as datafile:
            data = datafile.read()
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload("partial_event_import.json", data,
                                        "application/octet-stream")
        self.submit(f, check_notification=False)
        # Check diff
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        # Registrations
        self.assertPresence("Emilia", div="box-changed-registrations")
        self.assertPresence("2.H.: Unterkunft", div="box-changed-registrations")
        self.assertPresence("Warme Stube", div="box-changed-registrations")
        self.assertPresence("brings_balls", div="box-changed-registration-fields")
        self.assertPresence("Notizen", div="box-changed-registration-fields")
        self.assertPresence("2.H.: Unterkunft",
                            div="box-changed-registration-fields")
        self.assertPresence("Morgenkreis: Kurswahlen",
                            div="box-changed-registration-fields")
        self.assertNonPresence(
            "Sitzung: Kursleiter", div="box-changed-registration-fields")
        self.assertNonPresence("Inga", div="box-changed-registrations")
        self.assertPresence("Charly", div="box-new-registrations")
        self.assertPresence("Inga", div="box-deleted-registrations")
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
    @as_users("annika", "garcia")
    def test_partial_import_interleaved(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/import'})
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        with open(self.testfile_dir / "partial_event_import.json", 'rb') as datafile:
            data = datafile.read()
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload("partial_event_import.json", data,
                                        "application/octet-stream")
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
        self.traverse({'href': '/event'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/part/summary'})
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        f = self.response.forms['partsummaryform']
        past_past_date = now().date() - datetime.timedelta(days=2)
        f['part_begin_1'] = past_past_date
        f['part_begin_2'] = past_past_date
        f['part_begin_3'] = past_past_date
        past_date = now().date() - datetime.timedelta(days=1)
        f['part_end_1'] = past_date
        f['part_end_2'] = past_date
        f['part_end_3'] = past_date
        self.submit(f)

        self.traverse({'href': '/event/event/1/show'})
        f = self.response.forms['deleteeventform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Veranstaltungen")
        self.assertNonPresence("Testakademie")
        self.logout()

        # since annika is no member, she can not access the past events
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/cde'},
                      {'href': '/cde/past/event/list'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertNonPresence("Testakademie")

    @as_users("annika", "garcia")
    def test_selectregistration(self) -> None:
        self.get('/event/registration'
                 + '/select?kind=orga_registration&phrase=emil&aux=1')
        expectation = {
            'registrations': [{'display_name': 'Emilia',
                               'email': 'emilia@example.cde',
                               'id': 2,
                               'name': 'Emilia E. Eventis'}]}
        if not self.user_in("annika"):
            del expectation['registrations'][0]['email']
        self.assertEqual(expectation, self.response.json)

    @as_users("annika", "garcia")
    def test_quick_registration(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "Emilia"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "i a"
        self.submit(f)
        self.assertTitle("Anmeldungen (Große Testakademie 2222)")
        self.assertPresence("Ergebnis [6]")
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        f = self.response.forms['quickregistrationform']
        f['phrase'] = "DB-5-1"
        self.submit(f)
        self.assertTitle("Anmeldung von Emilia E. Eventis (Große Testakademie 2222)")

    @storage
    @as_users("annika", "garcia")
    def test_partial_export(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'})
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/download/partial'})
        result = json.loads(self.response.text)
        with open(self.testfile_dir / "TestAka_partial_export_event.json") as f:
            expectation = json.load(f)
        expectation['timestamp'] = result['timestamp']
        self.assertEqual(expectation, result)

    @as_users("annika", "garcia")
    def test_partial_idempotency(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/download'})
        self.assertTitle("Downloads zur Veranstaltung Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/download/partial'})
        first = json.loads(self.response.text)

        upload = copy.deepcopy(first)
        del upload['event']
        del upload['CDEDB_EXPORT_EVENT_VERSION']
        for reg in upload['registrations'].values():
            del reg['persona']
        self.get('/')
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/import'})
        self.assertTitle("Partieller Import zur Veranstaltung Große Testakademie 2222")
        f = self.response.forms["importform"]
        f['json_file'] = webtest.Upload(
            "partial_event_import.json", json.dumps(upload).encode('utf-8'),
            "application/octet-stream")
        self.submit(f, check_notification=False)
        self.assertTitle("Validierung Partieller Import (Große Testakademie 2222)")
        f = self.response.forms["importexecuteform"]
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")

        self.traverse({'href': '/event/event/1/download'},
                      {'href': '/event/event/1/download/partial'})
        second = json.loads(self.response.text)
        del first['timestamp']
        del second['timestamp']
        self.assertEqual(first, second)

    @as_users("ferdinand")
    def test_archive(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'})
        self.assertTitle("Große Testakademie 2222")
        # prepare dates
        self.traverse({'href': '/event/event/1/change'})
        f = self.response.forms["changeeventform"]
        f['registration_soft_limit'] = "2001-10-30 00:00:00+0000"
        f['registration_hard_limit'] = "2001-10-30 00:00:00+0000"
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.traverse({'href': '/event/event/1/part/summary'})
        f = self.response.forms["partsummaryform"]
        f['part_begin_1'] = "2003-02-02"
        f['part_end_1'] = "2003-02-02"
        f['part_begin_2'] = "2003-11-01"
        f['part_end_2'] = "2003-11-11"
        f['part_begin_3'] = "2003-11-11"
        f['part_end_3'] = "2003-11-30"
        self.submit(f)
        self.assertTitle("Veranstaltungsteile konfigurieren (Große Testakademie 2222)")
        # do it
        self.traverse({'href': '/event/event/1/show'})
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        # checkbox to create a past event is checked by default
        self.submit(f)
        self.assertTitle("Große Testakademie 2222")
        self.assertPresence("Diese Veranstaltung wurde archiviert.",
                            div="static-notifications")
        self.assertNotIn("archiveeventform", self.response.forms)
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/past/event/list'})
        self.assertPresence("Große Testakademie 2222 (Warmup)")

        # Check visibility but un-modifiability for participants
        self.logout()
        self.login(USER_DICT["emilia"])
        self.get("/event/event/1/show")
        self.assertPresence("Diese Veranstaltung wurde archiviert.",
                            div="static-notifications")
        self.traverse({'href': '/event/event/1/registration/status'})
        self.assertNonPresence("Bearbeiten")
        self.get("/event/event/1/registration/amend")
        self.follow()
        self.assertPresence("Veranstaltung ist bereits archiviert.",
                            div="notifications")

    @as_users("anton")
    def test_archive_without_past_event(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'CdE-Party 2050'})
        self.assertTitle("CdE-Party 2050")

        # prepare dates
        self.traverse({'description': 'Konfiguration'})
        f = self.response.forms["changeeventform"]
        f['registration_start'] = "2000-10-30 00:00:00+0000"
        f['registration_soft_limit'] = "2001-10-30 00:00:00+0000"
        f['registration_hard_limit'] = "2001-10-30 00:00:00+0000"
        self.submit(f)
        self.traverse({'description': 'Veranstaltungsteile'})
        f = self.response.forms["partsummaryform"]
        f['part_begin_4'] = "2003-02-02"
        f['part_end_4'] = "2003-02-03"
        self.submit(f)

        # do it
        self.traverse({'description': 'Übersicht'})
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        f['create_past_event'].checked = False
        self.submit(f)

        self.assertTitle("CdE-Party 2050")
        self.assertPresence("Diese Veranstaltung wurde archiviert.",
                            div="static-notifications")

        # check that there is no past event
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg.-Veranstaltungen'})
        self.assertNonPresence("CdE-Party 2050")

    @as_users("anton")
    def test_archive_event_purge_persona(self) -> None:
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'CyberTestAkademie'})
        self.assertTitle("CyberTestAkademie")
        f = self.response.forms["archiveeventform"]
        f['ack_archive'].checked = True
        f['create_past_event'].checked = False
        self.submit(f)

        self.assertTitle("CyberTestAkademie")
        self.assertPresence("Diese Veranstaltung wurde archiviert.",
                            div="static-notifications")

        # check that there is no past event
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg.-Veranstaltungen'})
        self.assertNonPresence("CdE-CyberTestAkademie")

        # now, archive and purge a participant
        self.realm_admin_view_profile("daniel", "cde")
        self.assertTitle("Daniel D. Dino")
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Daniel D. Dino")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        f = self.response.forms['purgepersonaform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("N. N.")
        self.assertPresence("Der Benutzer wurde geleert.", div='purged')

        # now, test if the event is still working
        self.traverse({'description': 'Veranstaltungen'},
                      {'description': 'CyberTestAkademie'},
                      {'description': 'Statistik'})
        self.assertTitle("Statistik (CyberTestAkademie)")
        self.get('/event/event/3/registration/7/show')
        self.assertTitle("Anmeldung von N. N. (CyberTestAkademie)")
        self.assertNonPresence("Daniel")

    @as_users("annika")
    def test_one_track_no_courses(self) -> None:
        self.traverse({'href': '/event/$'},
                      {'description': 'Alle Veranstaltungen'},
                      {'description': 'CdE-Party 2050'})
        # Check if course list is present (though we have no course track)
        self.assertNonPresence('/event/event/2/course/list', div="sidebar")
        self.assertNonPresence('/event/event/2/course/stats', div="sidebar")
        self.assertNonPresence('/event/event/2/course/choices', div="sidebar")

        # Add course track
        self.traverse({'href': '/event/event/2/part/summary'})
        f = self.response.forms['partsummaryform']
        f['track_create_4_-1'].checked = True
        f['track_title_4_-1'] = "Chillout Training"
        f['track_shortname_4_-1'] = "Chill"
        f['track_num_choices_4_-1'] = "1"
        f['track_min_choices_4_-1'] = "1"
        f['track_sortkey_4_-1'] = "1"
        self.submit(f)

        # Add registration
        self.traverse({'href': '/event/event/2/registration/query'},
                      {'href': '/event/event/2/registration/add'})
        # We have only one part, thus it should not be named
        self.assertNonPresence('Partywoche')
        # We have only one track, thus it should not be named
        self.assertNonPresence('Chillout')
        f = self.response.forms['addregistrationform']
        f['persona.persona_id'] = "DB-2-7"
        f['part4.status'] = 1
        self.submit(f)
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'description': 'Bearbeiten'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.get("/event/event/2/registration/multiedit?reg_ids=1001")
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

        # Check course related pages for errors
        self.traverse({'href': '/event/event/2/course/list'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'href': '/event/event/2/course/stats'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')
        self.traverse({'href': '/event/event/2/course/choices'})
        self.assertNonPresence('Partywoche')
        self.assertNonPresence('Chillout')

    def test_free_event(self) -> None:
        # first, make Große Testakademie 2222 free
        self.login(USER_DICT['garcia'])
        self.traverse({'description': "Veranstaltungen"},
                      {'description': "Große Testakademie 2222"},
                      {'description': "Veranstaltungsteile"})
        f = self.response.forms['partsummaryform']
        f['fee_1'] = 0
        f['fee_2'] = 0
        f['fee_3'] = 0
        self.submit(f)

        pay_request = "Anmeldung erst mit Überweisung des Teilnehmerbeitrags"
        iban = iban_filter(self.app.app.conf['EVENT_BANK_ACCOUNTS'][0][0])
        no_member_surcharge = "zusätzlichen Beitrag in Höhe von 5,00"

        # now check ...
        for user in {'charly', 'daniel'}:
            self.logout()
            self.login(user)
            self.traverse({'href': '/event/event/1/register'})
            f = self.response.forms['registerform']
            f['parts'] = ['1', '3']
            f['course_choice3_0'] = 2
            f['course_choice3_1'] = 2
            f['course_choice3_1'] = 4
            self.submit(f)

            text = self.fetch_mail_content()

            # ... the registration mail ...
            # ... as member
            if self.user_in('charly'):
                self.assertNotIn(pay_request, text)
                self.assertNotIn(iban, text)
                self.assertNotIn(no_member_surcharge, text)
            # ... as not member (we still need to pay the no member surcharge)
            else:
                self.assertIn(pay_request, text)
                self.assertIn(iban, text)
                self.assertIn(no_member_surcharge, text)

            # ... the registration page ...
            # ... as member
            if self.user_in('charly'):
                self.assertNotIn(pay_request, text)
                self.assertNotIn(iban, text)
                self.assertNotIn(no_member_surcharge, text)
            # ... as not member (we still need to pay the no member surcharge)
            else:
                self.assertIn(pay_request, text)
                self.assertIn(iban, text)
                self.assertIn(no_member_surcharge, text)

    @as_users("garcia")
    def test_no_choices(self) -> None:
        """This is a regression test for #1224, #1271 and #1395."""
        self.traverse({"description": "Veranstaltungen"},
                      {"description": "Große Testakademie 2222"},
                      {"description": "Veranstaltungsteile"})
        f = self.response.forms['partsummaryform']
        f['track_num_choices_2_1'] = 0
        f['track_min_choices_2_1'] = 0
        f['track_num_choices_2_2'] = 0
        f['track_min_choices_2_2'] = 0
        f['track_num_choices_3_3'] = 0
        f['track_min_choices_3_3'] = 0
        self.submit(f)
        self.traverse({"description": "Anmeldungen"})
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.traverse({'description': "Kurse"},
                      {'description': "Kurssuche"})
        f = self.response.forms['queryform']
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)

    @as_users("anton")
    # @prepsql("UPDATE event.events SET registration_start = now() WHERE id = 2")
    def test_archived_participant(self) -> None:
        self.get("/event/event/2/registration/add")
        f = self.response.forms["addregistrationform"]
        f["persona.persona_id"] = USER_DICT["charly"]["DB-ID"]
        f["part4.status"] = const.RegistrationPartStati.participant.value
        f["reg.list_consent"].checked = True
        self.submit(f)
        self.traverse({"description": "Veranstaltungsteile"})
        f = self.response.forms["partsummaryform"]
        f["part_begin_4"] = now().date() - datetime.timedelta(days=1)
        f["part_end_4"] = now().date() - datetime.timedelta(days=1)
        self.submit(f)
        self.traverse({"description": r"\sÜbersicht"})
        f = self.response.forms["archiveeventform"]
        f["ack_archive"].checked = True
        self.submit(f, verbose=True)
        self.assertTitle("CdE-Party 2050")
        self.assertPresence("Charly")
        self.get("/event/event/2/registration/list")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Charly")
        self.admin_view_profile("charly")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "For testing."
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertPresence("CdE-Party 2050")
        self.get("/event/event/2/registration/list")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertPresence("Charly")
        self.admin_view_profile("charly")
        f = self.response.forms["purgepersonaform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertNonPresence("CdE-Party 2050")
        self.get("/event/event/2/registration/list")
        self.assertTitle("Teilnehmerliste CdE-Party 2050")
        self.assertNonPresence("Charly")
        self.assertPresence("N. N.")

    def test_log(self) -> None:
        # The following calls to other test methods do not work as intended, since
        # a test method with multiple `as_users` resets intermediate database state.
        # First: generate data
        self.test_register()
        self.logout()
        self.test_create_delete_course()
        self.logout()
        self.test_lodgements()
        self.logout()
        self.test_create_event()
        self.logout()
        self.test_manage_attendees()
        self.logout()
        self.test_add_empty_registration()
        self.logout()

        # Now check it
        self.login(USER_DICT['annika'])
        self.traverse({'href': '/event/$'},
                      {'href': '/event/log'})
        self.assertTitle("Veranstaltungen-Log [1–16 von 16]")
        self.assertNonPresence("LogCodes")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 27, 51]
        f['event_id'] = 1
        self.submit(f)
        self.assertTitle("Veranstaltungen-Log [1–2 von 2]")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/event/1/show'},
                      {'href': '/event/event/1/log'})
        self.assertTitle("Große Testakademie 2222: Log [1–6 von 6]")

        self.traverse({'href': '/event/$'},
                      {'href': '/event/log'})
        self.assertTitle("Veranstaltungen-Log [1–16 von 16]")
        f = self.response.forms['logshowform']
        f['persona_id'] = "DB-5-1"
        f['submitted_by'] = "DB-1-9"
        self.submit(f)
        self.assertTitle("Veranstaltungen-Log [0–0 von 0]")
