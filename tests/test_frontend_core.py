#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import re
import urllib.parse
from typing import Dict, Optional

import webtest

import cdedb.database.constants as const
from cdedb.common import (
    ADMIN_VIEWS_COOKIE_NAME, IGNORE_WARNINGS_NAME, CdEDBObject, get_hash,
)
from cdedb.query import QueryOperators
from tests.common import (
    USER_DICT, FrontendTest, UserIdentifier, UserObject, as_users, storage,
)


class TestCoreFrontend(FrontendTest):
    def test_login(self) -> None:
        for i, u in enumerate(("vera", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                self.get("/")
                f = self.response.forms['loginform']
                f['username'] = user['username']
                f['password'] = user['password']
                self.submit(f, check_notification=False)
                self.assertPresence(user['display_name'], div='displayname',
                                    exact=True)

    def test_login_redirect(self) -> None:
        user = USER_DICT["berta"]
        self.get("/core/admins")  # could be any non-public page
        f = self.response.forms["loginform"]
        f["username"] = user["username"]
        f["password"] = user["password"]
        self.submit(f, check_notification=False)
        self.assertLogin(user["display_name"])
        self.assertTitle("Administratorenübersicht")

    @as_users("vera", "berta", "emilia")
    def test_logout(self) -> None:
        self.assertPresence(self.user['display_name'], div='displayname', exact=True)
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False)
        self.assertNonPresence(self.user['display_name'])
        self.assertIn('loginform', self.response.forms)

    @as_users("vera")
    def test_change_locale(self) -> None:
        # Test for german locale
        self.traverse({'description': 'Nutzer verwalten'})
        self.assertPresence("Suchmaske", div='qf_title')
        self.assertNonPresence("Search Mask")
        # Test changing locale to english
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', check_notification=False)
        self.assertPresence("Search Mask", div='qf_title')
        self.assertNonPresence("Suchmaske")
        # Test storing of locale (via cookie)
        self.traverse({'description': 'Members'},
                      {'description': 'Manage Users'})
        self.assertPresence("Search Mask", div='qf_title')
        self.assertNonPresence("Suchmaske")
        # Test changing locale back to german
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', check_notification=False)
        self.assertPresence("Suchmaske", div='qf_title')
        self.assertNonPresence("Search Mask")

    @as_users("anton", "berta")
    def test_index(self) -> None:
        self.assertTitle("CdE-Datenbank")
        self.assertPresence("Meine Daten", div='sidebar')
        self.assertPresence("Orga-Veranstaltungen", div='orga-box')
        if self.user_in("berta"):
            self.assertNonPresence("Log")
            self.assertNonPresence("Admin-Änderungen")
            self.assertNonPresence("Nutzer verwalten")
            self.assertNonPresence("Aktivenforum 2000")
            self.assertPresence("Aktivenforum 2001", div='moderator-box')
            # Check if there is actually the correct request
            self.traverse({'href': '/ml/mailinglist/7/management',
                           'description': "1 Abonnement-Anfrage"})
            self.traverse({'href': '/'})
            self.assertTitle("CdE-Datenbank")
        else:
            self.assertPresence("Account-Log", div='sidebar')
            self.assertPresence("Admin-Änderungen", div='sidebar')
            self.assertPresence("Nutzer verwalten", div='sidebar')
            self.assertPresence("Nutzer verwalten", div='adminshowuser-box')
            self.assertPresence("Platin-Lounge", div='moderator-box')
            # Check moderation notification
            self.assertPresence("Mailman-Migration", div='moderator-box')
            self.traverse({'href': '/ml/mailinglist/99/moderate',
                           'description': "3 E-Mails"})
            self.traverse({'href': '/'})
            self.assertTitle("CdE-Datenbank")
        self.assertPresence("Moderierte Mailinglisten", div='moderator-box')
        self.assertPresence("CdE-Party 2050", div='orga-box')
        self.assertNonPresence("Große Testakademie 2222", div='orga-box')
        self.assertPresence("Aktuelle Veranstaltungen", div='event-box')
        self.assertPresence("Große Testakademie 2222", div='event-box')
        self.assertNonPresence("CdE-Party 2050", div='event-box')
        self.assertPresence("Aktuelle Versammlungen", div='assembly-box')
        self.assertPresence("Internationaler Kongress", div='assembly-box')

    def test_anonymous_index(self) -> None:
        self.get('/')
        self.assertPresence("Anmelden")
        self.assertNonPresence("Meine Daten")

    @as_users("annika", "martin", "nina", "vera", "werner")
    def test_sidebar(self) -> None:
        self.assertTitle("CdE-Datenbank")
        everyone = {"Index", "Übersicht", "Meine Daten", "Administratorenübersicht"}
        genesis = {"Accountanfragen"}
        core_admin = {"Nutzer verwalten", "Archivsuche", "Änderungen prüfen",
                      "Account-Log", "Nutzerdaten-Log", "Metadaten"}
        meta_admin = {"Admin-Änderungen"}

        # admin of a realm without genesis cases
        if self.user_in('werner'):
            ins = everyone
            out = genesis | core_admin | meta_admin
        # admin of a realm with genesis cases
        elif self.user_in('annika', 'nina'):
            ins = everyone | genesis
            out = core_admin | meta_admin
        # core admin
        elif self.user_in('vera'):
            ins = everyone | genesis | core_admin
            out = meta_admin
        # meta admin
        elif self.user_in('martin'):
            ins = everyone | meta_admin
            out = genesis | core_admin
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("anton", "berta", "charly", "daniel", "emilia", "ferdinand",
              "garcia", "inga", "janis", "kalif", "martin", "nina",
              "vera", "werner", "annika", "farin", "akira")
    def test_showuser(self) -> None:
        self.traverse({'description': self.user['display_name']})
        self.assertTitle(self.user['default_name_format'])
        self.assertPresence(self.user['family_name'], div='title')

    @as_users("annika", "paul", "quintus")
    def test_showuser_events(self) -> None:
        if self.user_in("annika"):
            # event admins navigate via event page
            self.traverse("Veranstaltungen", "Große Testakademie",
                          "Garcia Generalis")
        elif self.user_in("paul"):
            # core admin
            self.admin_view_profile("garcia")
        elif self.user_in("quintus"):
            # cde admin
            self.realm_admin_view_profile("garcia", "cde")

        self.traverse("Veranstaltungs-Daten")
        self.assertTitle("Garcia Generalis – Veranstaltungs-Daten")
        self.assertPresence("CyberTestAkademie Teilnehmer")
        # part names not shown for one-part events
        self.assertNonPresence("CyberTestAkademie: Teilnehmer")
        self.assertPresence("Große Testakademie")
        self.assertPresence("Warmup: Teilnehmer, Erste Hälfte: Teilnehmer,"
                            " Zweite Hälfte: Teilnehmer")

    @as_users("nina", "paul", "quintus")
    def test_showuser_mailinglists(self) -> None:
        if self.user_in("nina"):
            # Mailinglist admins come from management
            self.traverse("Mailinglisten", "Allumfassende Liste", "Verwaltung",
                          "Inga Iota")
        elif self.user_in("paul"):
            self.admin_view_profile("inga")
        elif self.user_in("quintus"):
            # Relative admins may see this page
            self.realm_admin_view_profile("inga", "cde")

        self.traverse("Mailinglisten-Daten")
        self.assertTitle("Inga Iota – Mailinglisten-Daten")
        self.assertPresence("inga@example.cde", div='contact-email')
        self.assertPresence("CdE-Info E-Mail: inga-papierkorb@example.cde")
        self.assertPresence("Kampfbrief-Kommentare (geblockt)")
        self.assertNonPresence("Witz des Tages")

    @as_users("emilia", "janis")
    def test_showuser_self(self) -> None:
        name = f"{self.user['given_names']} {self.user['family_name']}"
        self.get('/core/self/show')
        self.assertTitle(name)
        if not self.user_in("janis"):  # Janis is no event user
            self.get('/core/self/events')
            self.assertTitle(f"{name} – Veranstaltungs-Daten")
        self.get('/core/self/mailinglists')
        self.assertTitle(f"{name} – Mailinglisten-Daten")
        # Check there are no links
        self.traverse({'description': self.user['display_name']})
        self.assertNonPresence("Veranstaltungs-Daten")
        self.assertNonPresence("Mailinglisten-Daten")

    @as_users("inga")
    def test_vcard(self) -> None:
        # we test here only if the presented vcard is kind of correct. *When* a vcard
        # should be present is tested in the privacy tests.
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)

        self.assertTitle(USER_DICT['berta']['default_name_format'])
        self.traverse({'description': 'VCard'})
        vcard = ["BEGIN:VCARD",
                 "VERSION:3.0",
                 "ADR:;;Im Garten 77;Utopia;;34576;Deutschland",
                 "BDAY:1981-02-11",
                 "EMAIL:berta@example.cde",
                 "FN:Bertålotta Beispiel",
                 "N:Beispiel;Bertålotta;;Dr.;MdB",
                 "NICKNAME:Bertå",
                 "TEL;TYPE=\"home,voice\":+49 (5432) 987654321",
                 "TEL;TYPE=\"cell,voice\":0163/123456789",
                 "END:VCARD"]
        for line in vcard:
            self.assertIn(line, self.response.text)

    @as_users("vera")
    def test_vcard_cde_admin(self) -> None:
        self.admin_view_profile('charly')
        self.traverse({'description': 'VCard'})

    @as_users("vera")
    def test_toggle_admin_views(self) -> None:
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')
        # Core Administration
        self.get('/')
        self.assertNoLink("/core/meta")
        # Submit the adminviewstoggleform with the right button
        self._click_admin_view_button(re.compile(r"Index-Administration"),
                                      current_state=False)
        self.traverse({'href': '/core/meta'},
                      {'href': '/'})
        self.assertNoLink("/core/search/user")  # Should not have an effect here
        self._click_admin_view_button(re.compile(r"Index-Administration"),
                                      current_state=True)
        self.assertNoLink("/core/meta")

        # No meta administration for vera
        button = self.response.html\
            .find(id="adminviewstoggleform") \
            .find(text=re.compile(r"Admin-Administration"))
        self.assertIsNone(button)

        # user administration
        # No adminshowuserform present
        self.assertNotIn('adminshowuserform', self.response.forms)
        self.assertNoLink('/core/genesis/list')
        self.assertNoLink('/core/changelog/list')
        self.assertNoLink('/core/changelog/view')
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=False)

        self.traverse({'href': '/core/genesis/list'},
                      {'href': '/core/changelog/list'},
                      {'href': '/core/changelog/view'},
                      {'href': '/cde/'},
                      {'href': '/cde/search/user'})
        # Now, the adminshowuserform is present, so we can navigate to Berta
        self.admin_view_profile('berta')
        # Test some of the admin buttons
        self.response.click(href='/username/adminchange')
        self.response.click(href=re.compile(r'\d+/adminchange'))
        self.response.click(href='/membership/change')
        # Disable the User admin view. No buttons should be present anymore
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=True)
        self.assertNoLink('/username/adminchange')
        self.assertNoLink(re.compile(r'\d+/adminchange'))
        self.assertNoLink('/membership/change')
        # We shouldn't even see realms and account balance anymore
        self.assertNonPresence('Bereiche')
        self.assertNonPresence('12,50€')
        self.assertNotIn('activitytoggleform', self.response.forms)
        self.assertNotIn('sendpasswordresetform', self.response.forms)

    @as_users("vera")
    def test_adminshowuser(self) -> None:
        self.admin_view_profile('berta')
        self.assertTitle("Bertå Beispiel")
        self.assertPresence("Bei Überweisungen aus dem Ausland achte bitte",
                            div='copy-paste-template')

        self.admin_view_profile('emilia')
        self.assertNonPresence("Bei Überweisungen aus dem Ausland achte bitte")

    @as_users("berta")
    def test_member_profile_past_events(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': "PfingstAkademie 2014"})
        self.assertTitle("PfingstAkademie 2014")
        self.traverse({'description': self.user['display_name']},
                      {'description': "Swish -- und alles ist gut"})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")

    @as_users("daniel", "emilia")
    def test_event_profile_past_events(self) -> None:
        self.traverse({'href': '/core/self/show'})
        self.assertPresence("PfingstAkademie 2014")
        self.assertPresence("Goethe zum Anfassen")
        self.assertNoLink(content="PfingstAkademie 2014")
        self.assertNoLink(content="Goethe zum Anfassen")

    @as_users("berta")
    def test_cppaymentinformation(self) -> None:
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence("Bei Überweisungen aus dem Ausland achte bitte")

    @as_users("anton")
    def test_selectpersona(self) -> None:
        self.get('/core/persona/select?kind=admin_persona&phrase=din')
        expectation = {
            'personas': [{'email': 'daniel@example.cde',
                          'id': 4,
                          'name': 'Daniel Dino'},
                         {'email': 'ferdinand@example.cde',
                          'id': 6,
                          'name': 'Ferdinand Findus'}]}
        self.assertEqual(expectation, self.response.json)
        self.get('/core/persona/select?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=pure_ml_user&phrase=@exam')
        expectation = (10, 14)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=event_user&phrase=bert')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=pure_assembly_user&phrase=kal')
        expectation = (11,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("quintus")
    def test_selectpersona_two(self) -> None:
        # Quintus is unsearchable, but this should not matter here.
        self.get('/core/persona/select?kind=admin_persona&phrase=din')
        expectation = (4, 6)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("berta", "martin", "nina", "rowena", "vera", "viktor", "werner", "annika")
    def test_selectpersona_403(self) -> None:
        # These can not be done by Berta no matter what.
        if not self.user_in("vera"):
            self.get('/core/persona/select?kind=admin_persona&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
            self.get('/core/persona/select?kind=past_event_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
        if not self.user_in("viktor", "werner"):
            self.get('/core/persona/select?kind=pure_assembly_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
        if self.user_in("martin", "rowena"):
            self.get('/core/persona/select?kind=ml_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
        if not self.user_in("nina"):
            self.get('/core/persona/select?kind=pure_ml_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
        if not self.user_in("annika", "berta"):
            self.get('/core/persona/select?kind=event_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')

        if self.user_in("martin", "rowena", "werner"):
            self.get('/core/persona/select'
                     '?kind=event_user&phrase=@exam',
                     status=403)
            self.assertTitle('403: Forbidden')
            self.get('/core/persona/select'
                     '?kind=ml_subscriber&phrase=@exam&aux=57',
                     status=403)
            self.assertTitle('403: Forbidden')

    @as_users("vera")
    def test_selectpersona_relative_cde_admin(self) -> None:
        self.get('/core/persona/select'
                 '?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("annika")
    def test_selectpersona_relative_event_admin(self) -> None:
        self.get('/core/persona/select'
                 '?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("viktor")
    def test_selectpersona_relative_assembly_admin(self) -> None:
        self.get('/core/persona/select'
                 '?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("garcia", "nina")
    def test_selectpersona_ml_event(self) -> None:
        # Only event participants are shown
        # ml_admins are allowed to do this even if they are no orgas.
        self.get('/core/persona/select'
                 '?kind=ml_subscriber&phrase=@exam&aux=9')
        expectation = (1, 2, 5)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select'
                 '?kind=ml_subscriber&phrase=inga&aux=9')
        expectation = (9,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("berta")
    def test_selectpersona_ml_event_403(self) -> None:
        self.get('/core/persona/select'
                 '?kind=ml_subscriber&phrase=@exam&aux=9',
                 status=403)
        self.assertTitle('403: Forbidden')

    @as_users("berta", "werner")
    def test_selectpersona_ml_assembly(self) -> None:
        # Only assembly participants are shown
        self.get('/core/persona/select'
                 '?kind=ml_subscriber&phrase=@exam&aux=5')
        expectation = (1, 2, 9)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("garcia")
    def test_selectpersona_unprivileged_event(self) -> None:
        self.get('/core/persona/select?kind=event_user&phrase=bert')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("werner")
    def test_selectpersona_unprivileged_assembly(self) -> None:
        # Normal use search
        self.get('/core/persona/select?kind=assembly_user&phrase=bert')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        # Pure assembly user search
        self.get('/core/persona/select?kind=pure_assembly_user&phrase=kalif')
        expectation = (11,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=pure_assembly_user&phrase=bert')
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(tuple(), reality)

    @as_users("berta")
    def test_selectpersona_unprivileged_ml(self) -> None:
        self.get('/core/persona/select?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("janis")
    def test_selectpersona_unprivileged_ml2(self) -> None:
        self.get('/core/persona/select?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("katarina")
    def test_selectpersona_auditor(self) -> None:
        self.get('/core/persona/select?kind=admin_persona&phrase=din')
        expectation = {
            'personas': [
                {
                    'id': 4,
                    'name': 'Daniel Dino',
                },
                {
                    'id': 6,
                    'name': 'Ferdinand Findus',
                },
            ],
        }
        self.assertEqual(expectation, self.response.json)
        self.get('/core/persona/select?kind=ml_user&phrase=@exam')
        expectation = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation[:self.conf["NUM_PREVIEW_PERSONAS"]], reality)
        self.get('/core/persona/select?kind=event_user&phrase=bert')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=past_event_user&phrase=emil')
        expectation = (5,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=assembly_user&phrase=kalif')
        expectation = (11,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=pure_assembly_user&phrase=kal', status=403)
        self.get('/core/persona/select?kind=pure_ml_user&phrase=@exam', status=403)
        for ml_id in self.ml.list_mailinglists(self.key):
            self.get(f'/core/persona/select?kind=ml_subscriber'
                     f'&phrase=@exam&aux={ml_id}', status=403)

    @as_users("vera")
    def test_adminshowuser_advanced(self) -> None:
        for phrase, user in (("DB-2-7", USER_DICT['berta']),
                              ("2", USER_DICT['berta']),
                              ("Bertålotta Beispiel", USER_DICT['berta']),
                              ("berta@example.cde", USER_DICT['berta']),
                              ("anton@example.cde", USER_DICT['anton']),
                              ("Spielmanns", USER_DICT['berta']),):
            self.traverse({'href': '^/$'})
            f = self.response.forms['adminshowuserform']
            f['phrase'] = phrase
            self.submit(f)
            self.assertTitle(user['default_name_format'])
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "nonsense asorecuhasoecurhkgdgdckgdoao"
        self.submit(f)
        self.assertTitle("CdE-Datenbank")
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "@example.cde"
        self.submit(f)
        self.assertTitle("Allgemeine Nutzerverwaltung")
        self.assertPresence("Bertålotta", div='query-result')
        self.assertPresence("Emilia", div='query-result')
        self.assertPresence("Garcia", div='query-result')
        self.assertPresence("Kalif", div='query-result')

    @as_users("vera", "berta", "garcia")
    def test_changedata(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location2'] = "Hyrule"
        f['country2'] = "AR"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertTitle(f"{self.user['given_names']} {self.user['family_name']}")
        self.assertPresence("Hyrule", div='address2')
        self.assertPresence("Okarinas", div='additional')
        self.assertPresence("(Zelda)", div='personal-information')

    @as_users("vera")
    def test_automatic_country(self) -> None:
        self.admin_view_profile('annika')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['location2'] = "Kabul"
        self.submit(f)
        self.assertTitle("Annika Akademieteam")
        self.assertNonPresence("Afghanistan")
        self.assertPresence("Deutschland", div='address2')

    @as_users("vera")
    def test_adminchangedata_other(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("Bertå Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("vera")
    def test_adminchangedata_self(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'href': '/core/persona/22/adminchange'})
        self.assertTitle("Vera Verwaltung bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Vera Verwaltung")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("vera", "berta", "emilia")
    def test_change_password_zxcvbn(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Passwort ändern'})
        # Password one: Common English words
        new_password = 'dragonSecret'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError(
            "new_password", "Das ist ähnlich zu einem häufig genutzten Passwort.",
            notification="Passwort ist zu schwach.")
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        # Password two: Repeating patterns
        new_password = 'dfgdfg123'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError("new_password",
                                   'Wiederholungen wie „abcabcabc“ sind nur geringfügig'
                                   ' schwieriger zu erraten als „abc“.',
                                   notification="Passwort ist zu schwach.")
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        self.assertPresence(
            'Vermeide Wiederholungen von Wörtern und Buchstaben.')
        # Password three: Common German words
        new_password = 'wurdeGemeinde'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError(
            "new_password",
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.',
            notification="Passwort ist zu schwach.")
        self.assertPresence('Großschreibung hilft nicht wirklich.')
        # Password four: German umlauts
        new_password = 'überwährend'
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError(
            "new_password",
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.',
            notification="Passwort ist zu schwach.")
        # Password five: User-specific passwords
        new_password = (self.user['given_names'].replace('-', ' ').split()[0] +
                        self.user['family_name'].replace('-', ' ').split()[0])
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError("new_password", "",
                                   notification="Passwort ist zu schwach.")
        # Password six+seven: CdE-specific passwords
        new_password = "cdeakademie"
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError("new_password", "",
                                   notification="Passwort ist zu schwach.")
        new_password = "duschorgie"
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError("new_password", "",
                                   notification="Passwort ist zu schwach.")

    @as_users("vera", "ferdinand")
    def test_change_password_zxcvbn_admin(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Passwort ändern'})
        # Strong enough for normal users, but not for admins
        new_password = 'phonebookbread'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertValidationError(
            "new_password", "Passwort ist zu schwach für einen Admin-Account.",
            notification="Passwort ist zu schwach.")

    @as_users("berta", "emilia")
    def test_change_password_zxcvbn_noadmin(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Passwort ändern'})
        # Strong enough for normal users, but not for admins
        new_password = 'phonebookbread'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.assertPresence('Passwort geändert.', div="notifications")

    @as_users("vera", "berta", "emilia")
    def test_change_password(self) -> None:
        user = self.user
        new_password = 'krce84#(=kNO3xb'
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Passwort ändern'})
        f = self.response.forms['passwordchangeform']
        f['old_password'] = self.user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.logout()
        self.assertNonPresence(self.user['display_name'])
        self.login(self.user)
        self.assertIn('loginform', self.response.forms)
        new_user = dict(user)
        new_user['password'] = new_password
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(self.user['display_name'])

    def test_reset_password(self) -> None:
        new_passwords = {
            "good": "krce63koLe#$e",
            "bad": "dragonSecret"
        }
        for key, val in new_passwords.items():
            for i, u in enumerate(("anton", "berta", "emilia", "ferdinand")):
                with self.subTest(u=u):
                    self.setUp()
                    user = USER_DICT[u]
                    self.get('/')
                    self.traverse({'description': 'Passwort zurücksetzen'})
                    self.assertTitle("Passwort zurücksetzen")
                    f = self.response.forms['passwordresetform']
                    f['email'] = user['username']
                    self.submit(f)
                    self.assertTitle("CdE-Datenbank")
                    if u in {"anton", "ferdinand"}:
                        text = self.fetch_mail_content()
                        self.assertNotIn('[1]', text)
                        self.assertIn('Sicherheitsgründe', text)
                        continue
                    link = self.fetch_link()
                    self.get(link)
                    self.follow()
                    self.assertTitle("Neues Passwort setzen")
                    f = self.response.forms['passwordresetform']
                    f['new_password'] = val
                    f['new_password2'] = val
                    if key == 'good':
                        self.submit(f)
                        self.login(user)
                        self.assertIn('loginform', self.response.forms)
                        new_user = dict(user)
                        new_user['password'] = val
                        self.login(new_user)
                        self.assertNotIn('loginform', self.response.forms)
                        self.assertLogin(user['display_name'])
                    elif key == 'bad':
                        self.submit(f, check_notification=False)
                        self.assertNonPresence('Passwort zurückgesetzt.')
                        self.assertValidationError(
                            "new_password",
                            "Das ist ähnlich zu einem häufig genutzten Passwort.",
                            notification="Passwort ist zu schwach.")

    def test_repeated_password_reset(self) -> None:
        new_password = "krce63koLe#$e"
        user = USER_DICT["berta"]
        self.get('/')
        self.traverse({'description': 'Passwort zurücksetzen'})
        f = self.response.forms['passwordresetform']
        f['email'] = user['username']
        self.submit(f)
        link = self.fetch_link()
        # First reset should work
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        # Second reset with same link should fail
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertPresence("Link ist ungültig oder wurde bereits verwendet.",
                            div="notifications")

    def test_admin_reset_password(self) -> None:
        new_password = "krce63koLe#$e"
        self.setUp()
        user = USER_DICT['vera']
        self.login(user)
        self.admin_view_profile('ferdinand')
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        link = self.fetch_link()
        self.logout()
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        other = USER_DICT['ferdinand']
        self.login(other)
        self.assertIn('loginform', self.response.forms)
        new_other = dict(other)
        new_other['password'] = new_password
        self.login(new_other)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(other['display_name'])

    @as_users("vera", "ferdinand")
    def test_cde_admin_reset_password(self) -> None:
        self.realm_admin_view_profile('berta', 'cde')
        self.assertTitle("Bertå Beispiel")
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        self.assertPresence("E-Mail abgeschickt.", div='notifications')
        self.assertTitle("Bertå Beispiel")

    @as_users("ferdinand", "nina")
    def test_ml_admin_reset_password(self) -> None:
        self.realm_admin_view_profile('janis', 'ml')
        self.assertTitle("Janis Jalapeño")
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        self.assertPresence("E-Mail abgeschickt.", div='notifications')
        self.assertTitle("Janis Jalapeño")

    @as_users("vera", "berta", "emilia")
    def test_change_username(self) -> None:
        # First test with current username
        user = self.user
        current_username = self.user['username']
        self.traverse({'description': self.user['display_name']},
                      {'href': '/core/self/username/change'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = current_username
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "new_username", "Muss sich von der aktuellen E-Mail-Adresse unterscheiden.")
        self.assertNonPresence("E-Mail abgeschickt!", div="notifications")
        # Now with new username
        new_username = "zelda@example.cde"
        f = self.response.forms['usernamechangeform']
        f['new_username'] = new_username
        self.submit(f)
        link = self.fetch_link()
        self.get(link)
        f = self.response.forms['usernamechangeform']
        f['password'] = self.user['password']
        self.submit(f)
        self.logout()
        self.assertIn('loginform', self.response.forms)
        self.login(self.user)
        self.assertIn('loginform', self.response.forms)
        new_user = dict(user)
        new_user['username'] = new_username
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(self.user['display_name'])

    def test_admin_username_change(self) -> None:
        new_username = "bertalotta@example.cde"
        vera = USER_DICT['vera']
        self.get('/')
        self.login(vera)
        self.admin_view_profile('berta')
        self.traverse({'href': '/username/adminchange'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = new_username
        self.submit(f)
        self.logout()
        berta = USER_DICT['berta']
        self.login(berta)
        self.assertIn('loginform', self.response.forms)
        new_berta = dict(berta)
        new_berta['username'] = new_username
        self.login(new_berta)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(new_berta['display_name'])

    def test_any_admin_query(self) -> None:
        admin1 = USER_DICT["anton"]
        admin2 = USER_DICT["martin"]
        new_admin1 = USER_DICT["garcia"]
        new_admin2 = USER_DICT["berta"]
        new_privileges1 = {
            'is_ml_admin': True,
        }
        new_privileges2 = {
            'is_assembly_admin': True,
        }
        # Grant new admin privileges.
        self._approve_privilege_change(
            admin1, admin2, new_admin1, new_privileges1)
        self.logout()
        self._approve_privilege_change(
            admin1, admin2, new_admin2, new_privileges2)
        self.logout()
        # Check results of Any Admin query.
        self.login(admin1)
        self.get('/core/search/user')
        save = self.response
        self.response = save.click(description="Alle Admins")
        self.assertPresence("Ergebnis [14]", div='query-results')
        self.assertPresence("Akira", div='query-result')
        self.assertPresence("Anton Armin A.", div='query-result')
        self.assertPresence("Beispiel", div='query-result')
        self.assertPresence("Farin", div='query-result')
        self.assertPresence("Findus", div='query-result')
        self.assertPresence("Generalis", div='query-result')
        self.assertPresence("Meister", div='query-result')
        self.assertPresence("Olaf", div='query-result')
        self.assertPresence("Panther", div='query-result')
        self.assertPresence("Quintus", div='query-result')
        self.assertPresence("Neubauer", div='query-result')
        self.assertPresence("Olafson", div='query-result')
        self.assertPresence("Vera", div='query-result')
        self.assertPresence("Viktor", div='query-result')

    def test_privilege_change(self) -> None:
        # Grant new admin privileges.
        new_admin = USER_DICT["berta"]
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
            'is_cdelokal_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
            'is_cdelokal_admin': False
        }
        new_password = "ihsokdmfsod"
        new_admin_copy = self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin,
            new_privileges, old_privileges, new_password=new_password)
        # Check success.
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {}".format(
            new_admin['default_name_format']))
        f = self.response.forms['privilegechangeform']
        old_privileges.update(new_privileges)
        for k, v in old_privileges.items():
            self.assertEqual(f[k].checked, v)

        # Check that we can login with new credentials but not with old.
        self.logout()
        self.login(new_admin)
        self.assertPresence("Login fehlgeschlagen.", div="notifications")
        self.login(new_admin_copy)
        self.assertNonPresence("Login fehlgeschlagen.", div="notifications")
        self.assertLogin(new_admin['display_name'])

    @as_users("anton")
    def test_change_privileges_dependency_error(self) -> None:
        new_admin = USER_DICT["berta"]
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {}".format(
            new_admin["default_name_format"]))
        f = self.response.forms['privilegechangeform']
        f['is_finance_admin'] = True
        f['notes'] = "Berta ist jetzt Praktikant der Finanz Vorstände."
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "is_finance_admin",
            "Diese Rolle kann nicht an nicht-CdE-Admin vergeben werden.")
        f['is_cde_admin'] = True
        f['notes'] = "Dann ist Berta jetzt eben CdE und Finanz Admin."
        self.submit(f)

    def test_privilege_change_reject(self) -> None:
        # Grant new admin privileges.
        new_admin = USER_DICT["berta"]
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
        }
        self._reject_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin,
            new_privileges, old_privileges)
        # Check success.
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {}".format(
            new_admin["default_name_format"]))
        f = self.response.forms['privilegechangeform']
        # Check that old privileges are still active.
        for k, v in old_privileges.items():
            self.assertEqual(f[k].checked, v)

    @as_users("anton")
    def test_privilege_change_realm_restrictions(self) -> None:
        new_admin = USER_DICT["emilia"]
        f = self.response.forms['adminshowuserform']
        f['phrase'] = new_admin["DB-ID"]
        self.submit(f)
        self.traverse(
            {'href': '/core/persona/{}/privileges'.format(new_admin["id"])})
        self.assertTitle("Privilegien ändern für {}".format(
            new_admin["default_name_format"]))
        f = self.response.forms['privilegechangeform']
        self.assertNotIn('is_meta_admin', f.fields)
        self.assertNotIn('is_core_admin', f.fields)
        self.assertNotIn('is_cde_admin', f.fields)
        self.assertNotIn('is_finance_admin', f.fields)

    @as_users("anton", "vera")
    def test_invalidate_password(self) -> None:
        other_user_name = "berta"
        self.admin_view_profile(other_user_name)
        f = self.response.forms["invalidatepasswordform"]
        f["confirm_username"] = USER_DICT[other_user_name]["username"]
        self.submit(f)
        self.logout()
        self.login(USER_DICT[other_user_name])
        self.assertPresence("Login fehlgeschlagen.", div="notifications")

    def test_archival_admin_requirement(self) -> None:
        # First grant admin privileges to new admin.
        new_admin = USER_DICT["berta"]
        new_privileges = {
            'is_core_admin': True,
            'is_cde_admin': True,
        }
        new_password = "ponsdfsidnsdgj"
        new_admin_copy = self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin,
            new_privileges, new_password=new_password)
        # Test archival
        self.logout()
        self.login(new_admin_copy)
        self.admin_view_profile("daniel")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "Archived for testing."
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')

    def test_privilege_change_self_approval(self) -> None:
        user = USER_DICT["anton"]
        new_privileges = {
            'is_event_admin': False,
        }
        self._initialize_privilege_change(user, user, user, new_privileges)
        self.login(user)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': "A. Administrator"})
        self.assertPresence(
            "Diese Änderung der Admin-Privilegien wurde von Dir angestoßen",
            div="notifications")
        self.assertNotIn('ackprivilegechangeform', self.response.forms)

    @as_users("anton")
    def test_meta_admin_archival(self) -> None:
        self.admin_view_profile("martin")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "Archived for testing."
        f["ack_delete"].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Admins können nicht archiviert werden.",
                            div="notifications")
        self.assertNonPresence("Benutzer ist archiviert", div="notifications")
        self.assertPresence(USER_DICT["martin"]["username"])

    def _initialize_privilege_change(self, admin1: UserIdentifier,
                                     admin2: UserIdentifier, new_admin: UserObject,
                                     new_privileges: Dict[str, bool],
                                     old_privileges: Dict[str, bool] = None,
                                     note: str = "For testing.") -> None:
        """Helper to initialize a privilege change."""
        self.login(admin1)
        f = self.response.forms['adminshowuserform']
        f['phrase'] = new_admin["DB-ID"]
        self.submit(f)
        self.traverse(
            {'href': '/core/persona/{}/privileges'.format(new_admin["id"])})
        self.assertTitle("Privilegien ändern für {}".format(
            new_admin["default_name_format"]))
        f = self.response.forms['privilegechangeform']
        if old_privileges:
            for k, v in old_privileges.items():
                self.assertEqual(v, f[k].checked)
        for k, v in new_privileges.items():
            f[k].checked = v
        f['notes'] = note
        self.submit(f)
        self.logout()

    def _approve_privilege_change(self, admin1: UserIdentifier, admin2: UserIdentifier,
                                  new_admin: UserObject,
                                  new_privileges: Dict[str, bool],
                                  old_privileges: Dict[str, bool] = None,
                                  note: str = "For testing.",
                                  new_password: str = None) -> UserObject:
        """Helper to make a user an admin."""
        self._initialize_privilege_change(
            admin1, admin2, new_admin, new_privileges, old_privileges)
        # Confirm privilege change.
        self.login(admin2)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': new_admin['family_name']})
        f = self.response.forms["ackprivilegechangeform"]
        self.submit(f)
        self.assertPresence("Änderung wurde übernommen.", div="notifications")
        if new_password:
            link = self.fetch_link(num=2)
            self.get(link)
            f = self.response.forms["passwordresetform"]
            f["new_password"] = new_password
            f["new_password2"] = new_password
            self.submit(f)
            # Only do this with a deepcopy of the user!
            new_admin = dict(new_admin)
            new_admin['password'] = new_password
        return new_admin

    def _reject_privilege_change(self, admin1: UserIdentifier, admin2: UserIdentifier,
                                 new_admin: UserObject,
                                 new_privileges: Dict[str, bool],
                                 old_privileges: Dict[str, bool] = None,
                                 note: str = "For testing.") -> None:
        """Helper to reject a privilege change."""
        self._initialize_privilege_change(
            admin1, admin2, new_admin, new_privileges, old_privileges)
        # Confirm privilege change.
        self.login(admin2)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': new_admin['family_name']})
        f = self.response.forms["nackprivilegechangeform"]
        self.submit(f)
        self.assertPresence("Änderung abgelehnt.", div="notifications")

    @as_users("vera")
    def test_toggle_activity(self) -> None:
        for i, u in enumerate(("berta", "charly", "daniel", "emilia", "garcia",
                               "inga", "janis", "kalif", "martin", "olaf")):
            with self.subTest(target=u):
                self.admin_view_profile(u)
                f = self.response.forms['activitytoggleform']
                self.submit(f)
                msg = "Benutzer ist deaktiviert."
                if u in {"olaf"}:
                    self.assertNonPresence(msg)
                    self.assertPresence("Ja", div='account-active')
                else:
                    self.assertPresence(msg, div='deactivated')
                    self.assertPresence("Nein", div='account-active')
                f = self.response.forms['activitytoggleform']
                self.submit(f)
                if u in {"olaf"}:
                    self.assertPresence(msg, div='deactivated')
                    self.assertPresence("Nein", div='account-active')
                else:
                    self.assertNonPresence(msg)
                    self.assertPresence("Ja", div='account-active')

    @storage
    @as_users("vera", "berta")
    def test_get_foto(self) -> None:
        response = self.app.get(
            '/core/foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e6'
            '1ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9')
        self.assertTrue(response.body.startswith(b"\x89PNG"))
        self.assertTrue(len(response.body) > 10000)

    @storage
    @as_users("vera", "berta")
    def test_set_foto(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Profilbild ändern'})
        f = self.response.forms['setfotoform']
        with open(self.testfile_dir / "picture.png", 'rb') as datafile:
            data = datafile.read()
        my_hash = get_hash(data)
        f['foto'] = webtest.Upload("picture.png", data, "application/octet-stream")
        self.submit(f)
        self.assertIn(f'foto/{my_hash}', self.response.text)
        self.get(f'/core/foto/{my_hash}')
        self.assertEqual(data, self.response.body)

    @storage
    @as_users("vera", "berta")
    def test_set_foto_jpg(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Profilbild ändern'})
        f = self.response.forms['setfotoform']
        with open(self.testfile_dir / "picture.jpg", 'rb') as datafile:
            data = datafile.read()
        my_hash = get_hash(data)
        f['foto'] = webtest.Upload("picture.jpg", data, "application/octet-stream")
        self.submit(f)
        self.assertIn(f'foto/{my_hash}', self.response.text)
        self.get(f'/core/foto/{my_hash}')
        self.assertEqual(data, self.response.body)

    @as_users("berta")
    def test_reset_foto(self) -> None:
        self.traverse({'description': self.user['display_name']},)
        foto_hash = self.get_sample_datum('core.personas', self.user['id'])['foto']
        self.assertIn(f'foto/{foto_hash}', self.response.text)
        self.traverse({'description': 'Profilbild ändern'})
        f = self.response.forms['resetfotoform']
        self.submit(f, check_notification=False)
        self.assertPresence("Profilbild entfernt.", div="notifications")
        self.assertNotIn(f'foto/{foto_hash}', self.response.text)

    @as_users("vera")
    def test_user_search(self) -> None:
        self.traverse({'description': 'Nutzer verwalten'})
        self.assertTitle("Allgemeine Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'n'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Allgemeine Nutzerverwaltung")
        self.assertPresence("Ergebnis [14]", div='query-results')
        self.assertPresence("Jalapeño", div='query-result')

    @as_users("vera")
    def test_create_user(self) -> None:

        def _traverse_to_realm(realm: str = None) -> webtest.Form:
            self.traverse('Index', 'Nutzer verwalten', 'Nutzer anlegen')
            self.assertTitle("Nutzer anlegen")
            f = self.response.forms['selectrealmform']
            if realm:
                f['realm'] = realm
            return f

        self.submit(_traverse_to_realm('cde'))
        self.assertTitle("Neues Mitglied anlegen")
        self.submit(_traverse_to_realm('event'))
        self.assertTitle("Neuen Veranstaltungsnutzer anlegen")
        self.submit(_traverse_to_realm('assembly'))
        self.assertTitle("Neuen Versammlungsnutzer anlegen")
        self.submit(_traverse_to_realm('ml'))
        self.assertTitle("Neuen Mailinglistennutzer anlegen ")
        # There is no kind "Core user"
        f = _traverse_to_realm()
        f['realm'].force_value('core')
        self.submit(f, check_notification=False)
        self.assertValidationError('realm', "Kein gültiger Bereich.")

    @as_users("vera")
    def test_archived_user_search(self) -> None:
        self.traverse({'description': 'Archivsuche'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qop_given_names'] = QueryOperators.match.value
        f['qval_given_names'] = 'des'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]", div='query-results')
        self.assertPresence("Hell", div='query-result')

    @as_users("vera")
    def test_archived_user_search2(self) -> None:
        self.traverse({'description': 'Archivsuche'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [2]", div='query-results')
        self.assertPresence("Hell", div='query-result')
        self.assertPresence("Lost", div='query-result')
        self.assertPresence("N/A", div='query-result')

    @as_users("vera")
    def test_show_archived_user(self) -> None:
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')

    @as_users("paul", "quintus")
    def test_archive_user(self) -> None:
        if self.user_in("paul"):
            self.admin_view_profile('charly')
        else:
            self.realm_admin_view_profile('charly', realm='cde')
        self.assertTitle("Charly Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt", div='address')
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        self.submit(f, check_notification=False)
        self.assertValidationError("note", "Darf nicht leer sein")
        self.assertTitle("Charly Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt", div='address')
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Charly Clown")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        self.assertNonPresence("Zirkusstadt")
        self.traverse({'description': "Account wiederherstellen"})
        f = self.response.forms['dearchivepersonaform']
        f['new_username'] = "charly@example.cde"
        self.submit(f)
        self.assertTitle("Charly Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")

    @as_users("vera")
    def test_purge_user(self) -> None:
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        f = self.response.forms['purgepersonaform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("N. N.")
        self.assertNonPresence("Hades")
        self.assertPresence("Name N. N. Geburtsdatum N/A Geschlecht keine Angabe",
                            div='personal-information', exact=True)
        self.assertNonPresence("archiviert")
        self.assertPresence("Der Benutzer wurde geleert.", div='purged')
        self.assertNotIn('dearchivepersonaform', self.response.forms)
        self.assertNotIn('purgepersonaform', self.response.forms)

    @as_users("farin")
    def test_modify_balance(self) -> None:
        self.admin_view_profile('ferdinand')
        self.assertPresence("22,20 €", div='balance')
        self.assertNonPresence("Probemitgliedschaft")
        self.traverse({'description': 'Guthaben anpassen'})
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        # Test form default values
        f = self.response.forms['modifybalanceform']
        self.assertEqual(f['new_balance'].value, "22.20")
        self.assertFalse(f['trial_member'].checked)
        f['change_note'] = 'nop'
        # Test 'Nothing changed!' warning
        self.submit(f, check_notification=False)
        self.assertPresence("Keine Änderungen", div="notifications")
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        # Test missing change note entry warning
        f = self.response.forms['modifybalanceform']
        f['new_balance'] = 15.66
        self.submit(f, check_notification=False)
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        self.assertValidationError("change_note", "Darf nicht leer sein.")
        # Test changing balance
        f = self.response.forms['modifybalanceform']
        f['new_balance'] = 15.66
        f['change_note'] = 'deduct stolen cookies'
        self.submit(f)
        self.assertPresence("15,66 €", div='balance')
        # Test changing trial membership
        self.traverse({'description': 'Guthaben anpassen'})
        f = self.response.forms['modifybalanceform']
        f['trial_member'].checked = True
        f['change_note'] = "deduct lost cookies"
        self.submit(f)
        self.assertPresence("CdE-Mitglied (Probemitgliedschaft)",
                            div='membership')
        # Test changing balance and trial membership
        self.traverse({'description': 'Guthaben anpassen'})
        f = self.response.forms['modifybalanceform']
        self.assertTrue(f['trial_member'].checked)
        f['new_balance'] = 22.22
        f['trial_member'].checked = False
        f['change_note'] = "deduct eaten cookies"
        self.submit(f)
        self.assertPresence("22,22 €", div='balance')
        self.assertNonPresence("Probemitgliedschaft")

    @as_users("vera")
    def test_meta_info(self) -> None:
        self.traverse({'description': 'Metadaten'})
        self.assertTitle("Metadaten")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Bertålotta Beispiel", f["Finanzvorstand_Name"].value)
        f["Finanzvorstand_Name"] = "Zelda"
        self.submit(f)
        self.assertTitle("Metadaten")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Zelda", f["Finanzvorstand_Name"].value)

    def test_changelog(self) -> None:
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'description': user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        f['birth_name'] = ""
        self.submit(f, check_notification=False)
        self.assertPresence("Die Änderung wartet auf Bestätigung.",
                            div='notifications')
        self.assertPresence(user['family_name'], div='personal-information')
        self.assertPresence("Gemeinser", div='personal-information')
        self.assertNonPresence('Ganondorf')
        self.logout()
        user = USER_DICT["vera"]
        self.login(user)
        self.traverse({'description': 'Änderungen prüfen'})
        self.assertTitle("Zu prüfende Profiländerungen [1]")
        self.traverse({'description': 'Ganondorf'},
                      {'description': 'Änderungen bearbeiten'})
        self.assertTitle("Bertå Ganondorf bearbeiten")
        self.traverse({'description': 'Änderungen prüfen'},
                      {'description': 'Ganondorf'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Zu prüfende Profiländerungen [0]")
        self.traverse({'description': 'Nutzerdaten-Log'})
        f = self.response.forms['logshowform']
        f['reviewed_by'] = 'DB-22-1'
        self.submit(f)
        self.assertTitle('Nutzerdaten-Log [1–1 von 1]')
        self.assertPresence("Bertå Ganondorf")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'description': user['display_name']})
        self.assertNonPresence(user['family_name'])
        self.assertNonPresence("Gemeinser")
        self.assertPresence('Ganondorf', div='personal-information')

    @as_users("vera")
    def test_history(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertå Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933", div='personal-information')
        self.traverse({'description': 'Änderungshistorie'})
        self.assertTitle("Änderungshistorie von Bertålotta Beispiel")
        self.assertPresence(r"Gen 2\W*03.04.1933", regex=True)
        self.assertPresence(r"Gen 1\W*11.02.1981", regex=True)

    @as_users("vera")
    def test_markdown(self) -> None:
        self.admin_view_profile('inga')
        self.assertIn('<h4 id="CDEDB_MD_inga">', self.response.text)
        self.assertIn('<div class="toc">', self.response.text)
        self.assertIn(
            '<li><a href="#CDEDB_MD_musik">Musik</a></li>', self.response.text)
        self.assertIn('<a class="btn btn-xs btn-warning" href="http://www.cde-ev.de">',
                      self.response.text)

    def test_admin_overview(self) -> None:
        # Makes Berta Event + CdE Admin
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
        }
        self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], USER_DICT["berta"],
            new_privileges, old_privileges)
        self.logout()

        # Check the overview.
        self.login(USER_DICT['inga'])
        self.traverse({"href": "/core/admins"})
        self.assertTitle("Administratorenübersicht")
        self.assertPresence("Anton Armin A. Administrator", div="meta")
        self.assertPresence("Martin Meiste", div="meta")
        self.assertPresence("Anton Armin A. Administrator", div="core")
        self.assertNonPresence("Martin Meister", div="core")
        self.assertNonPresence("Bertålotta Beispiel", div="core")
        self.assertPresence("Anton Armin A. Administrator", div="cde")
        self.assertPresence("Ferdinand F. Findus", div="cde")
        self.assertPresence("Anton Armin A. Administrator", div="finance")
        self.assertPresence("Ferdinand F. Findus", div="finance")
        self.assertPresence("Anton Armin A. Administrator", div="event")
        self.assertPresence("Ferdinand F. Findus", div="event")
        self.assertPresence("Bertålotta Beispiel", div="event")
        self.assertPresence("Nina Neubauer", div="ml")
        self.assertPresence("Inga Iota", div="cdelokal")
        self.assertPresence("Anton Armin A. Administrator", div="assembly")
        self.assertPresence("Ferdinand F. Findus", div="assembly")
        self.assertPresence("Bertålotta Beispiel", div="assembly")
        self.logout()
        self.login(USER_DICT["janis"])
        self.traverse({'description': 'Administratorenübersicht'})
        self.assertTitle("Administratorenübersicht")
        self.assertPresence("Anton Armin A. Administrator", div="core")
        self.assertNonPresence("Bertålotta Beispiel")

    @as_users("vera")
    def test_trivial_promotion(self) -> None:
        self.admin_view_profile('emilia')
        self.traverse({'description': 'Bereich hinzufügen'})
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['realmselectionform']
        self.assertNotIn("event", f['target_realm'].options)
        f['target_realm'] = "cde"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['promotionform']
        self.submit(f, check_notification=False)
        f = self.response.forms['promotionform']
        f['pevent_id'] = 2
        self.assertPresence("Die Kursauswahl wird angezeigt, nachdem")
        f['is_orga'] = True
        self.assertValidationError('change_note', "Darf nicht leer sein.")
        f['change_note'] = change_note = "Hat eine Akademie organisiert."
        self.submit(f, check_notification=False)
        f = self.response.forms['promotionform']
        self.assertNonPresence("Die Kursauswahl wird angezeigt, nachdem")
        f['pcourse_id'] = ''
        self.submit(f)
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("0,00 €", div='balance')
        self.assertPresence("Geburtstagsfete (Orga)", div="past-events")
        self.assertCheckbox(True, "paper_expuls_checkbox")
        self.assertNonPresence("CdE-Mitglied", div="cde-membership")
        self.assertNonPresence("Probemitgliedschaft", div="cde-membership")
        self.traverse("Änderungshistorie")
        self.assertPresence(change_note, div="generation2")

        # Do another promotion, this time granting trial membership.
        self.admin_view_profile('nina')
        self.traverse({'description': 'Bereich hinzufügen'})
        self.assertTitle("Bereichsänderung für Nina Neubauer")
        f = self.response.forms['realmselectionform']
        self.assertNotIn("event", f['target_realm'].options)
        f['target_realm'] = "cde"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Nina Neubauer")
        f = self.response.forms['promotionform']
        f['pevent_id'] = 1
        f['trial_member'].checked = True
        f['change_note'] = "Per Vorstandsbeschluss aufgenommen."
        self.submit(f, check_notification=False)
        f = self.response.forms['promotionform']
        f['pcourse_id'] = 1
        f['is_instructor'] = True
        self.submit(f)
        self.assertTitle("Nina Neubauer")
        self.assertPresence("0,00 €", div='balance')
        self.assertPresence("CdE-Mitglied", div="cde-membership")
        self.assertPresence("Probemitgliedschaft", div="cde-membership")
        self.assertPresence("PfingstAkademie", div="past-events")
        self.assertPresence("Swish", div="past-events")
        self.assertPresence("Kursleiter", div="past-events")

        # check for correct welcome mail
        mail = self.fetch_mail_content()
        self.assertIn(USER_DICT['nina']['display_name'], mail)
        self.assertIn("Ein herzliches Willkommen", mail)
        self.assertIn("zum ersten Mal in unserer Datenbank anmeldest", mail)
        self.assertIn("kostenlos", mail)  # check trial membership

    @as_users("vera")
    def test_nontrivial_promotion(self) -> None:
        self.admin_view_profile('kalif')
        self.traverse({'description': 'Bereich hinzufügen'})
        self.assertTitle("Bereichsänderung für Kalif Karabatschi")
        f = self.response.forms['realmselectionform']
        f['target_realm'] = "event"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Kalif Karabatschi")
        f = self.response.forms['promotionform']
        # First check error handling by entering an invalid birthday
        f['birthday'] = "foobar"
        self.submit(f, check_notification=False)
        self.assertValidationError("birthday", "Ungültige Eingabe für ein Datum")
        self.assertValidationError('change_note', "Darf nicht leer sein.")
        self.assertTitle("Bereichsänderung für Kalif Karabatschi")
        # Now, do it right
        f['birthday'] = "21.6.1977"
        f['gender'] = const.Genders.female
        f['change_note'] = "Komplizierte Aufnahme"
        self.submit(f)
        self.assertTitle("Kalif Karabatschi")
        self.assertPresence("21.06.1977", div='personal-information')
        # check that no welcome mail is sent - this is for cde promotion only
        with self.assertRaises(IndexError):
            self.fetch_mail_content()

    @as_users("vera")
    def test_ignore_warnings_postal_code(self) -> None:
        self.admin_view_profile("vera")

        self.traverse({'description': 'Bearbeiten \\(normal\\)'})
        f = self.response.forms['changedataform']
        f['postal_code'] = "11111"
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['changedataform']
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)
        self.assertTitle("Vera Verwaltung")

        self.traverse({'description': 'Bearbeiten \\(mit Adminrechten\\)'})
        f = self.response.forms['changedataform']
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['changedataform']
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)

        self.get("/core/genesis/request")
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "for testing"
        f['birthday'] = "2000-01-01"
        f['address'] = "Auf dem Hügel"
        # invalid postal code according to validationdata
        f['postal_code'] = "11111"
        f['location'] = "Überall"
        f['country'] = "DE"
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['genesisform']
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)
        link = self.fetch_link()
        self.get(link)
        self.follow()

        self.traverse({'description': 'Accountanfragen'},
                      {'description': 'Details'},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['genesismodifyform']
        f[IGNORE_WARNINGS_NAME].checked = True
        self.submit(f)
        f = self.response.forms['genesisapprovalform']
        self.submit(f)

    def _genesis_request(self, data: CdEDBObject, realm: Optional[str] = None) -> None:
        if realm:
            self.get('/core/genesis/request?realm=' + realm)
        elif self.user:
            self.get('/core/genesis/request')
        else:
            self.get('/')
            self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in data.items():
            f[field] = entry
        self.submit(f)
        link = self.fetch_link()
        self.get(link)
        self.follow()

    ML_GENESIS_DATA_NO_REALM: CdEDBObject = {
        'given_names': "Zelda", 'family_name': "Zeruda-Hime",
        'username': "zelda@example.cde", 'notes': "Gimme!"}
    ML_GENESIS_DATA: CdEDBObject = {**ML_GENESIS_DATA_NO_REALM, 'realm': "ml"}

    EVENT_GENESIS_DATA = ML_GENESIS_DATA.copy()
    EVENT_GENESIS_DATA.update({
        'realm': "event", 'gender': const.Genders.female,
        'birthday': "1987-06-05", 'address': "An der Eiche", 'postal_code': "12345",
        'location': "Marcuria", 'country': "AQ"
    })

    CDE_GENESIS_DATA = EVENT_GENESIS_DATA.copy()
    CDE_GENESIS_DATA.update({
        'realm': "cde"
    })

    def test_genesis_event(self) -> None:
        self._genesis_request(self.EVENT_GENESIS_DATA)

        self.login('vera')
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde", div='request-1001')
        self.assertNonPresence("zorro@example.cde")
        self.assertNonPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.",
            div='no-ml-request')
        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde", div='username')
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.",
            div='no-event-request')
        self.assertNonPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'event'
        self.submit(f)
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertNonPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.",
            div='no-ml-request')
        self.traverse({'href': '/core/genesis/1001/show'})
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        f = self.response.forms['genesisapprovalform']
        self.submit(f)
        link = self.fetch_link()
        self.submit(f, check_notification=False)
        self.assertPresence("Emailadresse bereits vergeben.", div="notifications")
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.logout()
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "long_saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        new_user = {
            'id': 9,
            'username': "zorro@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345", div='address')

    def test_genesis_ml(self) -> None:
        user = USER_DICT['vera']
        self._genesis_request(self.ML_GENESIS_DATA_NO_REALM, realm='ml')
        self.login(user)
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde", div='request-1001')
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.",
            div='no-event-request')
        self.assertNonPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        f = self.response.forms['genesismlapprovalform1']
        self.submit(f)
        link = self.fetch_link()
        self.logout()
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "long_saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        new_user = {
            'id': 11,
            'username': "zelda@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")

    @storage
    def test_genesis_cde(self) -> None:
        self.get('/core/genesis/request')
        self.assertTitle("Account anfordern")
        self.assertPresence("Die maximale Dateigröße ist 8 MB.")
        f = self.response.forms['genesisform']
        for field, entry in self.CDE_GENESIS_DATA.items():
            f[field] = entry
        self.submit(f, check_notification=False)
        self.assertValidationError('attachment')
        f = self.response.forms['genesisform']
        f['birth_name'] = "Ganondorf"
        f['notes'] = ""  # Do not send this to test upload permanance.
        with open(self.testfile_dir / "form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['attachment'] = webtest.Upload(
            "my_participation_certificate.pdf", data, content_type="application/pdf")
        self.submit(f, check_notification=False)
        self.assertValidationError("notes", "Darf nicht leer sein.")
        self.assertPresence("Anhang my_participation_certificate.pdf")
        f = self.response.forms['genesisform']
        f['notes'] = "Gimme!"
        f['birthday'] = ""
        self.submit(f, check_notification=False)
        self.assertValidationError("birthday", "Darf nicht leer sein.")
        f['birthday'] = self.CDE_GENESIS_DATA['birthday']
        self.submit(f)
        link = self.fetch_link()
        self.get(link)
        self.follow()
        self.login(USER_DICT["vera"])
        self.traverse({'href': '/core'},
                      {'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertNonPresence("zorro@example.cde")
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence(
            "Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/show'})
        self.assertPresence("Ganondorf")
        self.assertNonPresence("Zickzack")
        self.assertNonPresence("PfingstAkademie")
        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['birth_name'] = "Zickzack"
        f['pevent_id'] = 1
        self.submit(f)
        self.assertPresence("Zickzack")
        self.assertNonPresence("Ganondorf")
        self.assertPresence("PfingstAkademie 2014")

        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['pcourse_id'] = 2
        self.submit(f)
        self.assertPresence("Goethe")

        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.assertPresence("Anhang herunterladen")
        save = self.response
        self.traverse({'description': 'Anhang herunterladen'})
        with open(self.testfile_dir / "form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = save
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde")
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'cde'
        self.submit(f)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence(
            "Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/show'})
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        f = self.response.forms['genesisapprovalform']
        self.submit(f)
        link = self.fetch_link()
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "Zelda Zeruda-Hime"
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("0,00 €", div="balance")
        self.assertPresence("CdE-Mitglied", div="cde-membership")
        self.assertPresence("Probemitglied", div="cde-membership")
        self.logout()
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "long_saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        new_user = {
            'id': 9,
            'username': "zorro@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertCheckbox(True, "paper_expuls_checkbox")
        self.assertPresence("12345")
        self.assertPresence("Zickzack")
        self.assertPresence("PfingstAkademie 2014")
        self.assertPresence("Goethe")
        self.traverse({'href': '/cde'})
        self.assertTitle('CdE-Mitgliederbereich')
        self.traverse({'description': 'Sonstiges'})

    def test_genesis_name_collision(self) -> None:
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.ML_GENESIS_DATA.items():
            f[field] = entry
        # Submit once
        self.submit(f)
        # Submit twice
        self.submit(f, check_notification=False)
        self.assertPresence("Bestätigungsmail erneut versendet.",
                            div="notifications")
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Berta"
        f['family_name'] = "Beispiel"
        f['username'] = "berta@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "ml"
        # Submit once
        self.submit(f, check_notification=False)
        self.assertPresence("E-Mail-Adresse bereits vorhanden.",
                            div="notifications")
        user = USER_DICT['vera']
        self.login(user)
        self.traverse({'description': 'Account-Log'})
        f = self.response.forms['logshowform']
        f['codes'] = [20]
        self.submit(f)
        self.assertTitle("Account-Log [1–1 von 1]")

    def test_genesis_verification_mail_resend(self) -> None:
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.ML_GENESIS_DATA.items():
            f[field] = entry
        self.submit(f)
        self.assertTrue(self.fetch_mail_content())
        self.submit(f)
        self.assertPresence("Bestätigungsmail erneut versendet.", div="notifications")
        self.assertTrue(self.fetch_mail_content())

    def test_genesis_postal_code(self) -> None:
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['country'] = "DE"
        f['postal_code'] = "Z-12345"
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl.")
        f['country'] = "AQ"
        self.submit(f)

    def test_genesis_birthday(self) -> None:
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['birthday'] = "2222-06-05"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "birthday", "Ein Geburtsdatum muss in der Vergangenheit liegen.")

    def test_genesis_missing_data(self) -> None:
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['notes'] = ""
        self.submit(f, check_notification=False)
        self.assertValidationError("notes", "Darf nicht leer sein.")

    def test_genesis_modify(self) -> None:
        self._genesis_request(self.ML_GENESIS_DATA)

        admin = USER_DICT["vera"]
        self.login(admin)
        self.traverse({'description': 'Accountanfrage'},
                      {'description': 'Details'})
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['family_name'] = "Zeruda"
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda")

        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = "event"
        f['gender'] = const.Genders.female
        f['birthday'] = "1987-06-05"
        f['address'] = "An der Eiche"
        f['postal_code'] = "12345"
        f['location'] = "Marcuria"
        f['country'] = "AQ"
        self.submit(f)
        self.assertPresence("An der Eiche", div='address')
        self.assertPresence("Antarktis", div='address')

        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['birthday'] = "1987-06-05"
        self.submit(f)

        # Check that we cannot assign a username that is already taken.
        f['username'] = self.user['username']
        self.submit(f, check_notification=False)
        self.assertValidationError("username", "Emailadresse bereits vergeben.")
        self.traverse("Abbrechen")

        self.assertTitle("Accountanfrage von Zelda Zeruda")
        f = self.response.forms['genesisapprovalform']
        self.submit(f)

    @as_users("vera")
    def test_genesis_doppelganger(self) -> None:
        # Create a new request almost identical to the current user.
        dg_data = {k: self.user[k] for k in self.ML_GENESIS_DATA if k in self.user}
        dg_data["username"] = "notme@example.cde"
        dg_data["notes"] = "Bestimmt jemand anderes1"
        dg_data["realm"] = "ml"
        self._genesis_request(dg_data)

        self.traverse("Accountanfragen", "Details")
        self.assertTitle(f"Accountanfrage von {self.user['given_names']}"
                         f" {self.user['family_name']}")
        self.assertPresence("Ähnliche Accounts")
        self.assertPresence(self.user['username'], div="doppelgangers")
        self.assertPresence(self.user['username'], div="doppelganger0")
        f = self.response.forms['genesisrejectionform']
        # Rejection causes info not success notification.
        self.submit(f, check_notification=False)
        self.assertPresence("Anfrage abgewiesen", div="notifications")

        # Create two almost identical requests, approve one and check that the second
        # one finds a doppelgänger.
        self._genesis_request(self.EVENT_GENESIS_DATA)
        self._genesis_request(
            dict(self.EVENT_GENESIS_DATA, username="notzelda@example.cde"))

        self.traverse("Accountanfragen", "Details")
        self.assertTitle(f"Accountanfrage von {self.EVENT_GENESIS_DATA['given_names']}"
                         f" {self.EVENT_GENESIS_DATA['family_name']}")
        self.assertNonPresence("Ähnliche Accounts")
        f = self.response.forms['genesisapprovalform']
        self.submit(f)
        self.traverse("Accountanfragen", "Details")
        self.assertTitle(f"Accountanfrage von {self.EVENT_GENESIS_DATA['given_names']}"
                         f" {self.EVENT_GENESIS_DATA['family_name']}")
        self.assertPresence("Ähnliche Accounts")
        self.assertPresence(self.EVENT_GENESIS_DATA['username'], div="doppelgangers")
        self.assertPresence(self.EVENT_GENESIS_DATA['username'], div="doppelganger0")
        f = self.response.forms['genesisrejectionform']
        self.submit(f, check_notification=False)
        self.assertPresence("Anfrage abgewiesen", div="notifications")

    def test_resolve_api(self) -> None:
        at = urllib.parse.quote_plus('@')
        self.get(
            '/core/api/resolve?username=%20bErTa{}example.CDE%20'.format(at),
            headers={'X-CdEDB-API-token': 'a1o2e3u4i5d6h7t8n9s0'})
        self.assertEqual(self.response.json, {
            "given_names": USER_DICT["berta"]["given_names"],
            "family_name": "Beispiel",
            "is_member": True,
            "id": 2,
            "username": "berta@example.cde",
        })
        self.get(
            '/core/api/resolve?username=anton{}example.cde'.format(at),
            headers={'X-CdEDB-API-token': 'a1o2e3u4i5d6h7t8n9s0'})
        self.assertEqual(self.response.json, {
            "given_names": "Anton Armin A.",
            "family_name": "Administrator",
            "is_member": True,
            "id": 1,
            "username": "anton@example.cde",
        })
        self.get('/core/api/resolve', status=403)

    @as_users("janis")
    def test_markdown_endpoint(self) -> None:
        self.post('/core/markdown/parse', {'md_str': '**bold** <script></script>'})
        expectation = "<p><strong>bold</strong> &lt;script&gt;&lt;/script&gt;</p>"
        self.assertEqual(expectation, self.response.text)

    def test_log(self) -> None:
        user = USER_DICT['vera']
        logs = []
        # First: generate data
        # request two new accounts
        self._genesis_request(self.ML_GENESIS_DATA)
        logs.append((1001, const.CoreLogCodes.genesis_request))
        logs.append((1002, const.CoreLogCodes.genesis_verified))

        event_genesis = self.EVENT_GENESIS_DATA.copy()
        event_genesis['username'] = "tester@example.cde"
        self._genesis_request(event_genesis)
        logs.append((1003, const.CoreLogCodes.genesis_request))
        logs.append((1004, const.CoreLogCodes.genesis_verified))

        # approve the account requests
        self.login(user)
        self.traverse({'description': 'Accountanfragen'})
        f = self.response.forms['genesismlapprovalform1']
        self.submit(f)
        logs.append((1005, const.CoreLogCodes.genesis_approved))
        logs.append((1006, const.CoreLogCodes.persona_creation))
        logs.append((1007, const.CoreLogCodes.password_reset_cookie))

        self.traverse({'href': 'core/genesis/1002/show'})
        f = self.response.forms['genesisapprovalform']
        self.submit(f)
        logs.append((1008, const.CoreLogCodes.genesis_approved))
        logs.append((1009, const.CoreLogCodes.persona_creation))
        logs.append((1010, const.CoreLogCodes.password_reset_cookie))

        # make janis assembly user
        self.admin_view_profile('janis')
        self.traverse({'description': 'Bereich hinzufügen'})
        f = self.response.forms['realmselectionform']
        f['target_realm'] = "assembly"
        self.submit(f)
        f = self.response.forms['promotionform']
        f['change_note'] = promotion_change_note = "trivial promotion"
        self.submit(f)
        logs.append((1011, const.CoreLogCodes.realm_change))

        # change berta's user name
        self.admin_view_profile('berta')
        self.traverse({'href': '/username/adminchange'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = "bertalotta@example.cde"
        self.submit(f)
        logs.append((1012, const.CoreLogCodes.username_change))

        # Now check it
        self.traverse({'description': 'Index'},
                      {'description': 'Account-Log'})
        self.log_pagination("Account-Log", tuple(logs))
        f = self.response.forms["logshowform"]
        f["codes"] = [const.CoreLogCodes.genesis_verified.value,
                      const.CoreLogCodes.realm_change.value,
                      const.CoreLogCodes.username_change.value]
        self.submit(f)
        self.assertPresence(promotion_change_note)
        self.assertPresence("zelda@example.cde")
        self.assertPresence("bertalotta@example.cde")

    @as_users("katarina")
    def test_auditor(self) -> None:
        realm_logs = {
            "Index": ("Account-Log", "Nutzerdaten-Log",),
            "Mitglieder": ("CdE-Log", "Finanz-Log", "Verg.-Veranstaltungen-Log",),
            "Veranstaltungen": ("Log",),
            "Mailinglisten": ("Log",),
            "Versammlungen": ("Log",),
        }
        for realm, logs in realm_logs.items():
            self.traverse(realm, *logs, realm)
            self._click_admin_view_button("Kassenprüfer")
            for log in logs:
                self.assertNonPresence(log, div="sidebar-navigation")
            self._click_admin_view_button("Kassenprüfer")
