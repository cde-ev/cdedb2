#!/usr/bin/env python3

import itertools
import json
import csv
import re
import unittest
import time
import webtest

from test.common import as_users, USER_DICT, FrontendTest
from cdedb.common import now
from cdedb.query import QueryOperators
from cdedb.frontend.parse_statement import (
    get_event_name_pattern, MEMBERSHIP_FEE_FIELDS, EVENT_FEE_FIELDS,
    OTHER_TRANSACTION_FIELDS, ACCOUNT_FIELDS, STATEMENT_DB_ID_UNKNOWN,
    STATEMENT_FAMILY_NAME_UNKNOWN, STATEMENT_GIVEN_NAMES_UNKNOWN)
from datetime import datetime

class TestCdEFrontend(FrontendTest):
    @as_users("anton", "berta")
    def test_index(self, user):
        self.traverse({'href': '/cde/$'})

    @as_users("anton", "berta")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'},)
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        if user['id'] == 2:
            self.assertPresence('PfingstAkademie')

    @as_users("berta")
    def test_changedata(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location2'] = "Hyrule"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertPresence("Hyrule")
        self.assertPresence("Okarinas")
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("anton")
    def test_adminchangedata(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        f['free_form'] = "Jabberwocky for the win."
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933")
        self.assertPresence("Jabberwocky for the win.")

    @as_users("anton")
    def test_validation(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "garbage"
        self.submit(f, check_notification=False)
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        self.assertIn("alert alert-danger", self.response.text)
        f = self.response.forms['changedataform']
        self.assertEqual("Zelda", f['display_name'].value)

    def test_consent(self):
        user = USER_DICT["garcia"]
        self.login(user)
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.traverse({'description': 'Index'})
        self.assertTitle("CdE-Datenbank")
        self.traverse({'href': '/core/self/show'},
                      {'href': '/cde/self/consent'})
        f = self.response.forms['ackconsentform']
        self.submit(f)
        ## automatic check for success notification

    def test_consent_change(self):
        # Remove consent decision of Bertalotta Beispiel
        self.login(USER_DICT["anton"])
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = False
        self.submit(f)

        # Check that Consent Decision is reachable for Berta but does not show
        # up upon login. CdE Member search should be disabled
        self.logout()
        self.login(USER_DICT["berta"])
        self.assertTitle("CdE-Datenbank")
        self.traverse({'href': '/cde'})
        self.assertNotIn("membersearchform", self.response.forms)
        self.traverse({'href': '/cde/self/consent'})
        # Re-acknowledge consent
        f = self.response.forms['ackconsentform']
        self.submit(f)

    @as_users("berta")
    def test_quota(self, user):
        count = 42
        for search, title in itertools.cycle((
                ("Anton Armin", "Anton Armin A. Administrator"),
                ("Inga Iota", "Inga Iota"))):
            count -= 1
            self.traverse({'href': '/cde/$'})
            f = self.response.forms['membersearchform']
            f['qval_fulltext'] = search
            if count >= 0:
                self.submit(f)
                self.assertTitle(title)
            else:
                self.response = f.submit()
                self.follow(status=403)
                self.assertPresence("Limit für Zugriffe")
                self.assertPresence("automatisch zurückgesetzt")
                break

    @as_users("anton", "berta", "inga")
    def test_member_search_one(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77")

    @as_users("anton", "berta")
    def test_member_search_accents(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77")

    @as_users("anton", "berta")
    def test_member_search(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_pevent_id'] = 1
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")

    @as_users("anton", "berta")
    def test_member_search_fulltext(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "876 @example.cde"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden")
        self.assertPresence("Anton")
        self.assertPresence("Bertålotta")
       
    @as_users("anton", "berta")
    def test_member_search_zip(self, user):
        self.get("/cde/search/member")
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms["membersearchform"]
        f['postal_upper'] = 20000
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Anton Armin A. Administrator")
        self.assertPresence("Inga Iota")
        
        f = self.response.forms["membersearchform"]
        f['postal_lower'] = 60000
        f['postal_upper'] = ""
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Bertålotta Beispiel")
        self.assertPresence("Ferdinand F. Findus")
        
        f = self.response.forms["membersearchform"]
        f['postal_lower'] = 10000
        f['postal_upper'] = 20000
        self.submit(f)
        self.assertTitle("Inga Iota")

    @as_users("anton", "berta")
    def test_member_search_phone(self, user):
        self.get("/cde/search/member")
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms["membersearchform"]
        f["qval_telephone,mobile"] = 234
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden")
        self.assertPresence("Anton Armin A. Administrator")
        self.assertPresence("Bertålotta Beispiel")

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/cde/search/user'})
        self.assertTitle("CdE-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.similar.value
        f['qval_address'] = 'Garten'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("CdE-Nutzerverwaltung")
        self.assertPresence("Ergebnis [1]")
        self.assertEqual(self.response.lxml.xpath("//*[@id='query-result']/tbody/tr[1]/@data-id")[0], "2")

    @as_users("anton")
    def test_user_search_csv(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/cde/search/user'})
        self.assertTitle("CdE-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.regex.value
        f['qval_address'] = '[aA][rm]'
        f['qsel_personas.id'].checked = True
        f['qsel_birthday'].checked = True
        f['qsel_decided_search'].checked = True
        f['qsel_free_form'].checked = True
        f['qsel_given_names'].checked = True
        f['qord_primary'] = "personas.id"
        self.response = f.submit("download", value="csv")
        expectation = '''personas.id;given_names;family_name;username;birthday;decided_search;free_form
2;Bertålotta;Beispiel;berta@example.cde;1981-02-11;True;"Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen"
3;Charly C.;Clown;charly@example.cde;1984-05-13;True;"Ich bin ein ""Künstler""; im weiteren Sinne."
4;Daniel D.;Dino;daniel@example.cde;1963-02-19;False;
6;Ferdinand F.;Findus;ferdinand@example.cde;1988-01-01;True;
'''.encode('utf-8-sig')
        self.assertEqual(expectation, self.response.body)

    @as_users("anton")
    def test_user_search_json(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/cde/search/user'})
        self.assertTitle("CdE-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.regex.value
        f['qval_address'] = '[aA][rm]'
        f['qsel_personas.id'].checked = True
        f['qsel_birthday'].checked = True
        f['qsel_decided_search'].checked = True
        f['qsel_free_form'].checked = True
        f['qsel_given_names'].checked = True
        f['qord_primary'] = "personas.id"
        self.response = f.submit("download", value="json")
        expectation = [
            {'birthday': '1981-02-11',
             'decided_search': True,
             'family_name': 'Beispiel',
             'free_form': 'Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen',
             'given_names': 'Bertålotta',
             'personas.id': 2,
             'username': 'berta@example.cde'},
            {'birthday': '1984-05-13',
             'decided_search': True,
             'family_name': 'Clown',
             'free_form': 'Ich bin ein "Künstler"; im weiteren Sinne.',
             'given_names': 'Charly C.',
             'personas.id': 3,
             'username': 'charly@example.cde'},
            {'birthday': '1963-02-19',
             'decided_search': False,
             'family_name': 'Dino',
             'free_form': None,
             'given_names': 'Daniel D.',
             'personas.id': 4,
             'username': 'daniel@example.cde'},
            {'birthday': '1988-01-01',
             'decided_search': True,
             'family_name': 'Findus',
             'free_form': None,
             'given_names': 'Ferdinand F.',
             'personas.id': 6,
             'username': 'ferdinand@example.cde'}]
        self.assertEqual(expectation, json.loads(self.response.body.decode('utf-8')))

    @as_users("anton")
    def test_toggle_activity(self, user):
        self.admin_view_profile('berta')
        self.assertTrue(self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertFalse(self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("anton")
    def test_modify_membership(self, user):
        self.admin_view_profile('berta')
        self.assertTrue(self.response.lxml.get_element_by_id('membership_checkbox').get('data-checked') == 'True')
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.")
        self.traverse({'href': '/membership/change'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertFalse(self.response.lxml.get_element_by_id('membership_checkbox').get('data-checked') == 'True')
        self.traverse({'href': '/membership/change'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertTrue(self.response.lxml.get_element_by_id('membership_checkbox').get('data-checked') == 'True')
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.")

    @as_users("anton")
    def test_double_lastschrift_revoke(self, user):
        self.get("/cde/user/2/lastschrift")
        self.assertPresence("Aktive Einzugsermächtigung")
        self.assertPresence("Betrag 42,23 €")
        self.get("/cde/user/2/lastschrift/create")
        f = self.response.forms['createlastschriftform']
        f['amount'] = 25
        f['iban'] = "DE12 5001 0517 0648 4898 90"
        self.submit(f, check_notification=False)
        self.assertPresence("Mehrere aktive Einzugsermächtigungen sind unzulässig.",
                            div="notifications")

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/user'},
                      {'href': '/cde/user/create'})
        self.assertTitle("Neues Mitglied anlegen")
        data = {
            "username": 'zelda@example.cde',
            "title": "Dr.",
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "name_supplement": 'von und zu',
            "display_name": 'Zelda',
            "birthday": "5.6.1987",
            "specialisation": "oehm",
            ## "affiliation"
            "timeline": "tja",
            "interests": "hmmmm",
            "free_form": "jaaah",
            "gender": "1",
            "telephone": "030456790",
            ## "mobile"
            "weblink": "www.zzz.cc",
            "address": "Street 7",
            "address_supplement": "on the left",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
            ## "address2",
            ## "address_supplement2",
            ## "postal_code2",
            ## "location2",
            ## "country2",
            "notes": "some talk",
        }
        f = self.response.forms['newuserform']
        self.assertEqual(None, self.response.lxml.get_element_by_id('input_checkbox_is_searchable').value)
        self.assertFalse(self.response.lxml.get_element_by_id('input_checkbox_trial_member').checked)
        f['is_searchable'].checked = True
        f['is_member'].checked = True
        f['trial_member'].checked = True
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345")
        self.assertPresence("Probemitgliedschaft")
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.")
        mail = self.fetch_mail()[0]
        self.logout()
        link = self.fetch_link(mail)
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "krce63koLe#$e"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.assertNonPresence("Verifizierung für Zurücksetzen fehlgeschlagen.",
                               div="notifications")
        data['password'] = new_password
        self.login(data)
        self.assertLogin(data['display_name'])

    @as_users("anton")
    def test_lastschrift_index(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn("generatetransactionform2", self.response.forms)

    @as_users("anton", "berta")
    def test_lastschrift_show(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        if user['id'] == 1:
            self.assertIn("revokeform", self.response.forms)
            self.assertIn("receiptform3", self.response.forms)
        else:
            self.assertNotIn("revokeform", self.response.forms)
            self.assertNotIn("receiptform3", self.response.forms)

    @as_users("anton")
    def test_lastschrift_subject_limit(self, user):
        self.get("/core/persona/1/adminchange")
        f = self.response.forms["changedataform"]
        f["given_names"] = "Anton Armin ÄÖÜ"
        self.submit(f)
        self.get("/cde/user/1/lastschrift/create")
        f = self.response.forms["createlastschriftform"]
        f["amount"] = 100.00
        f["iban"] = "DE12500105170648489890"
        self.submit(f)
        f = self.response.forms["generatetransactionform"]
        self.submit(f, check_notification=False)
        self.assertNonPresence("Erstellung der SEPA-PAIN-Datei fehlgeschlagen.",
                               div="notifications")
        self.submit(f, check_notification=False)
        self.assertPresence("Es liegen noch unbearbeitete Transaktionen vor.",
                            div="notifications")

    @as_users("anton")
    def test_lastschrift_generate_transactions(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNonPresence("Keine zu bearbeitenden Lastschriften für "
                               "dieses Semester.")
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.")
        f = self.response.forms['downloadsepapainform']
        g = self.response.forms['generatetransactionsform']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)
        self.submit(g)
        self.assertPresence("1 Lastschriften initialisiert.",
                            div="notifications")
        self.assertPresence("Keine zu bearbeitenden Lastschriften für dieses "
                            "Semester.")
        self.assertNonPresence("Aktuell befinden sich keine Einzüge in der "
                               "Schwebe.")

    @as_users("anton")
    def test_lastschrift_generate_single_transaction(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNonPresence("Keine zu bearbeitenden Lastschriften für "
                               "dieses Semester.")
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.")
        f = self.response.forms['downloadsepapainform2']
        g = self.response.forms['generatetransactionform2']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)
        self.submit(g)
        self.assertPresence("1 Lastschriften initialisiert.",
                            div="notifications")
        self.assertPresence("Keine zu bearbeitenden Lastschriften für dieses "
                            "Semester.")
        self.assertNonPresence("Aktuell befinden sich keine Einzüge in der "
                               "Schwebe.")

    @as_users("anton")
    def test_lastschrift_transaction_rollback(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift/$'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [4]
        self.submit(f, button="success")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.traverse({'href': '^/$'})
        self.admin_view_profile('berta')
        self.assertPresence("17,50 €")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        f = self.response.forms['transactionrollbackform4']
        self.submit(f)
        self.assertPresence("Keine aktive Einzugsermächtigung")
        self.traverse({'href': '^/$'})
        self.admin_view_profile('berta')
        self.assertPresence("12,50 €")

    @as_users("anton")
    def test_lastschrift_transaction_cancel(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift/$'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [4]
        self.submit(f, button="cancelled")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn('generatetransactionform2', self.response.forms)
        self.assertPresence("Aktuell befinden sich keine Einzüge in der Schwebe.")

    @as_users("anton")
    def test_lastschrift_transaction_failure(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift/$'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [4]
        self.submit(f, button="failure")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertPresence("Aktuell befinden sich keine Einzüge in der Schwebe.")

    @as_users("anton")
    def test_lastschrift_skip(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift/$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['skiptransactionform2']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertNotIn('transactionsuccessform', self.response.forms)

    @as_users("anton")
    def test_lastschrift_create(self, user):
        self.admin_view_profile('charly')
        self.traverse({'href': '/cde/user/3/lastschrift'})
        self.assertPresence("Keine aktive Einzugsermächtigung")
        self.traverse({'href': '/cde/user/3/lastschrift/create'})
        self.assertTitle("Neue Einzugsermächtigung (Charly C. Clown)")
        f = self.response.forms['createlastschriftform']
        f['amount'] = "123.45"
        f['iban'] = "DE26370205000008068900"
        f['notes'] = "grosze Siebte: Take on me"
        self.submit(f)
        self.assertTitle("Einzugsermächtigung Charly C. Clown")
        self.assertIn("revokeform", self.response.forms)
        self.traverse({'href': '/cde/lastschrift/3/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("123.45", f['amount'].value)
        self.assertEqual("grosze Siebte: Take on me", f['notes'].value)

    @as_users("anton")
    def test_lastschrift_change(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/cde/user/2/lastschrift'},
                      {'href': '/cde/lastschrift/2/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("42.23", f['amount'].value)
        self.assertEqual('Dagobert Anatidae', f['account_owner'].value)
        self.assertEqual('reicher Onkel', f['notes'].value)
        f['amount'] = "27.16"
        f['account_owner'] = "Dagobert Beetlejuice"
        f['notes'] = "reicher Onkel (neu verheiratet)"
        self.submit(f)
        self.traverse({'href': '/cde/lastschrift/2/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("27.16", f['amount'].value)
        self.assertEqual('Dagobert Beetlejuice', f['account_owner'].value)
        self.assertEqual('reicher Onkel (neu verheiratet)', f['notes'].value)

    @as_users("anton")
    def test_lastschrift_receipt(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/cde/user/2/lastschrift'})
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        f = self.response.forms['receiptform3']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        
    @as_users("anton")
    def test_lastschrift_subscription_form(self, user):
        self.get("/cde/lastschrift/form/download")
        self.assertTrue(self.response.body.startswith(b"%PDF"))
        
    def test_lastschrift_subscription_form_anonymous(self):
        self.get("/cde/lastschrift/form/download")
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton", "charly")
    def test_lastschrift_subscription_form_fill(self, user):
        self.traverse({'href': '/cde'},
                      {'href': '/cde/i25p'},
                      {'href': '/cde/lastschrift/form/fill'})
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))
    
    @as_users("anton")
    def test_lastschrift_subscription_form_fill_fail(self, user):
        self.traverse({'href': '/cde'},
                      {'href': '/cde/i25p'},
                      {'href': '/cde/lastschrift/form/fill'})
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        f["db_id"] = "DB-1-8"
        f["postal_code"] = "ABC"
        f["iban"] = "DE12500105170648489809"
        self.submit(f)
        self.assertPresence("Checksumme stimmt nicht")
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Ungültige Checksumme")

    def test_lastschrift_subscription_form_fill_anonymous(self):
        self.get("/cde/lastschrift/form/fill")
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        f["iban"] = "DE12500105170648489890"
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton")
    def test_batch_admission(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/user'},
                      {'href': '/cde/admission$'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        with open("/tmp/cdedb-store/testfiles/batch_admission.csv") as datafile:
            tmp = datafile.read()
            placeholder_birthday = "03.10.9999"
            wandering_birthday = "03.10.{}".format(now().year - 5)
            unproblematic_birthday = "03.10.{}".format(now().year - 15)
            tmp = tmp.replace(placeholder_birthday, wandering_birthday)
            f['accounts'] = tmp
        self.submit(f, check_notification=False)

        ## first round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Erneut validieren")
        output.append(head)
        expectation = (
            (r"given_names:\W*Darf nicht leer sein.",
             r"pevent_id:\W*Keine Eingabe vorhanden."),
            tuple(),
            (r"Zeilen 3 und 4 sind identisch.",),
            (r"Zeilen 3 und 4 sind identisch.",),
            (r"persona:\W*Ähnlicher Account gefunden.",),
            (r"persona:\W*Ähnlicher Account gefunden.",),
            (r"persona:\W*Ähnlicher Account gefunden.",),
            (r"course:\W*Kein Kurs verfügbar.",),
            (r"pevent_id:\W*Keine Veranstaltung gefunden.",
             r"course:\W*Kein Kurs verfügbar.",),
            (r"pcourse_id:\W*Kein Kurs gefunden.",),
            (r"birthday:\W*Ungültige Eingabe für ein Datum.",
             r"birthday:\W*Notwendige Angabe fehlt."),
            (r"postal_code:\W*Ungültige Postleitzahl.",),
            (r"Zeilen 13 und 14 sind identisch.",),
            (r"Zeilen 13 und 14 sind identisch.",
             r"pcourse_id\W*Lediglich nach Titel zugeordnet."),
            (r"pevent_id\W*Nur unscharfer Treffer.",
             r"pcourse_id\W*Nur unscharfer Treffer.",
             r"birthday\W*Person ist jünger als 10 Jahre.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        for i in range(15):
            if i in (1, 7):
                expectation = '1'
            else:
                expectation = ''
            self.assertEqual(expectation, f['resolution{}'.format(i)].value)
        inputdata = f['accounts'].value
        f['resolution0'] = 2
        f['resolution2'] = 2
        f['resolution3'] = 2
        f['resolution4'] = 5
        f['doppelganger_id4'] = '2'
        f['resolution5'] = 4
        f['doppelganger_id5'] = '4'
        f['resolution6'] = 3
        f['doppelganger_id6'] = '5'
        inputdata = inputdata.replace("pa99", "pa14")
        inputdata = inputdata.replace("Doomed course from hell", "Swish -- und alles ist gut")
        inputdata = inputdata.replace("31.02.1981", "21.02.1981")
        inputdata = inputdata.replace("00000", "07751")
        inputdata = inputdata.replace("fPingst", "Pfingst")
        inputdata = inputdata.replace("wSish", "Swish")
        inputdata = inputdata.replace(wandering_birthday, unproblematic_birthday)
        f['resolution12'] = 2
        f['resolution13'] = 2
        f['accounts'] = inputdata
        self.submit(f, check_notification=False)

        ## second round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Erneut validieren".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"pevent_id:\W*Teilnahme bereits erfasst.",),
            tuple(),
            (r"doppelganger:\W*Accountzusammenführung mit einem nicht-CdE-Account.",),
            tuple(),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            tuple(),
            tuple(),
            (r"Eintrag geändert.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        nonexpectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"pevent_id:\W*Keine Veranstaltung gefungen.",
             r"course:\W*Kein Kurs verfügbar.",),
            (r"pcourse_id:\W*Kein Kurs gefunden.",),
            (r"birthday:\W*Tag liegt nicht im Monat.",
             r"birthday:\W*Notwendige Angabe fehlt."),
            (r"postal_code:\W*Ungültige Postleitzahl.",),
            tuple(),
            tuple(),
            (r"pevent_id\W*Nur unscharfer Treffer.",
             r"pevent_id\W*Nur unscharfer Treffer.",),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertFalse(re.search(piece, out))

        inputdata = f['accounts'].value
        inputdata = inputdata.replace('"1a";"Beispiel";"Bertålotta"',
                                      '"Ω";"Beispiel";"Bertålotta"')
        f['accounts'] = inputdata
        f['resolution4'] = 5
        f['doppelganger_id4'] = '2'
        f['resolution6'] = 1
        f['resolution8'] = 1
        f['resolution9'] = 1
        f['resolution10'] = 1
        f['resolution11'] = 1
        f['resolution14'] = 1
        self.submit(f, check_notification=False)

        ## third round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        self.assertEqual('', f['resolution4'].value)
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Erneut validieren".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"doppelganger:\W*Accountzusammenführung inkonsistent mit Aktion.",),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        nonexpectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"pevent_id:\W*Teilnahme bereits erfasst.",),
            tuple(),
            tuple(),
            tuple(),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            tuple(),
            tuple(),
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertFalse(re.search(piece, out))
        f['resolution4'] = 5
        f['doppelganger_id4'] = '2'
        f['resolution6'] = 2
        f['doppelganger_id6'] = ''
        self.assertEqual('', f['finalized'].value)
        self.submit(f, check_notification=False)

        ## fourth round
        self.assertPresence("Anlegen")
        self.assertNonPresence("Erneut validieren")
        f = self.response.forms['admissionform']
        self.assertEqual('5', f['resolution4'].value)
        self.assertEqual('True', f['finalized'].value)
        self.submit(f)
        self.assertPresence("7 Accounts erstellt.", div="notifications")

        ## validate
        self.traverse({'href': '/cde/$'}, {'href': '/past/event/list'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.traverse({'href': '/past/event/1/show'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Willy Brandt")
        self.assertPresence("Gerhard Schröder")
        self.assertPresence("Angela Merkel")

    def test_parse_statement_additional(self):
    
        pseudo_winter = {"title": "CdE Pseudo-WinterAkademie",
                         "begin": datetime(2222, 12, 27),
                         "end": datetime(2223, 1, 6)}
        test_pfingsten = {"title": "CdE Pfingstakademie",
                          "begin": datetime(1234, 5, 20),
                          "end": datetime(1234, 5, 23)}
        naka = {"title": "NachhaltigkeitsAkademie 2019",
                "begin": datetime(2019, 3, 23),
                "end": datetime(2019, 3, 30)}
        velbert = {"title": "JuniorAkademie NRW - Nachtreffen Velbert 2019",
                   "begin": datetime(2019, 11, 15),
                   "end": datetime(2019, 11, 17)}
        
        pattern = re.compile(get_event_name_pattern(pseudo_winter),
                             flags=re.IGNORECASE)
        
        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/2223"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/23"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademieXYZ"))
        self.assertTrue(pattern.search("Pseudo winter -Aka"))
        self.assertTrue(pattern.search("pseudo\twinter\naka\n"))
        
        pattern = re.compile(get_event_name_pattern(test_pfingsten),
                             flags=re.IGNORECASE)
        self.assertTrue(pattern.search("PfingstAkademie 1234"))
        self.assertTrue(pattern.search("Pfingst Akademie 34"))
        
        pattern = re.compile(get_event_name_pattern(naka),
                             flags=re.IGNORECASE)
        
        self.assertTrue(pattern.search("NAka 2019"))
        self.assertTrue(pattern.search("N Akademie 19"))
        self.assertTrue(pattern.search("NachhaltigkeitsAka 2019"))
        self.assertTrue(pattern.search("nachhaltigkeitsakademie"))

        p = re.compile(get_event_name_pattern(velbert), flags=re.I)

        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 19"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW-Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen  2019"))
        self.assertTrue(p.search("JuniorAkademie 2019"))
        self.assertTrue(p.search("NRW 2019"))
        self.assertTrue(p.search("Nachtreffen 2019"))
        self.assertTrue(p.search("Velbert 2019"))
        self.assertTrue(p.search("JUNIORAKADDEMIENRW - NACHTREFFEN VELBERT2019"))
        self.assertTrue(p.search("JUNIOR A.AKADEMIE NRW NACHTREFF VELBERT 2019"))

    @as_users("anton")
    def test_parse_statement(self, user):
        self.get("/cde/parse")
        self.assertTitle("Kontoauszug parsen")
        f = self.response.forms["statementform"]
        with open("/cdedb2/test/ancillary_files/statement.csv") as statementfile:
            f["statement"] = statementfile.read()
        self.submit(f, check_notification=False, verbose=True)
        
        self.assertTitle("Kontoauszug parsen")
        self.assertPresence("3 Transaktionen für event_fees gefunden.")
        self.assertPresence("2 Transaktionen für membership_fees gefunden.")
        self.assertPresence("7 Transaktionen für other_transactions gefunden.")
        self.assertPresence("12 Transaktionen für transactions gefunden.")
        
        save = self.response
        
        # check event_fees.csv
        f = save.forms["event_fees"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=EVENT_FEE_FIELDS))
                
        self.assertEqual("584.49", result[0]["amount_export"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["family_name"])
        self.assertEqual("Anton Armin A.", result[0]["given_names"])
        self.assertEqual("28.12.2018", result[0]["date"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["type_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["member_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["event_confidence"])

        self.assertEqual("584.49", result[1]["amount_export"])
        self.assertEqual("DB-7-8", result[1]["db_id"])
        self.assertEqual("Generalis", result[1]["family_name"])
        self.assertEqual("Garcia G.", result[1]["given_names"])
        self.assertEqual("27.12.2018", result[1]["date"])
        self.assertEqual("ConfidenceLevel.High", result[1]["type_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[1]["member_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[1]["event_confidence"])

        self.assertEqual("100.00", result[2]["amount_export"])
        self.assertEqual("DB-5-1", result[2]["db_id"])
        self.assertEqual("Eventis", result[2]["family_name"])
        self.assertEqual("Emilia E.", result[2]["given_names"])
        self.assertEqual("20.12.2018", result[2]["date"])
        self.assertEqual("ConfidenceLevel.Medium", result[2]["type_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[2]["member_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[2]["event_confidence"])
        
        # check Testakademie file
        f = save.forms["Große_Testakademie_2222"]
        self.submit(f, check_notification=False)
        # Should be equal to event_fees.csv
        self.assertEqual(list(csv.DictReader(self.response.text.split("\n"),
                                             delimiter=";",
                                             fieldnames=EVENT_FEE_FIELDS)),
                         result)
        
        # check membership_fees.csv
        f = save.forms["membership_fees"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=MEMBERSHIP_FEE_FIELDS))

        self.assertEqual("DB-2-7", result[0]["db_id"])
        self.assertEqual("Beispiel", result[0]["family_name"])
        self.assertEqual("Bertålotta", result[0]["given_names"])
        self.assertEqual("5.00", result[0]["amount_export"])
        self.assertEqual("25.12.2018", result[0]["date"])
        self.assertNotIn("not found in", result[0]["problems"])

        self.assertEqual("DB-7-8", result[1]["db_id"])
        self.assertEqual("Generalis", result[1]["family_name"])
        self.assertEqual("Garcia G.", result[1]["given_names"])
        self.assertEqual("2.50", result[1]["amount_export"])
        self.assertEqual("24.12.2018", result[1]["date"])
        self.assertIn("not found in", result[1]["problems"])
        
        # check other_transactions
        f = save.forms["other_transactions"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";"))

        self.assertEqual("8068900", result[0]["account"])
        self.assertEqual("26.12.2018", result[0]["date"])
        self.assertEqual("10.00", result[0]["amount_export"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["family_name"])
        self.assertEqual("Anton Armin A.", result[0]["given_names"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertIn("not found in", result[0]["problems"])

        self.assertEqual("8068900", result[1]["account"])
        self.assertEqual("23.12.2018", result[1]["date"])
        self.assertEqual("2.50", result[1]["amount_export"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[1]["db_id"])
        self.assertEqual(STATEMENT_FAMILY_NAME_UNKNOWN,
                         result[1]["family_name"])
        self.assertEqual(STATEMENT_GIVEN_NAMES_UNKNOWN,
                         result[1]["given_names"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertIn("No DB-ID found.", result[1]["problems"])

        self.assertEqual("8068900", result[2]["account"])
        self.assertEqual("21.12.2018", result[2]["date"])
        self.assertEqual("10.00", result[2]["amount_export"])
        self.assertEqual("Mitgliedsbeitrag für Anton Armin A. Administrator "
                         "DB-1-9 und Bertalotta Beispiel DB-2.7",
                         result[2]["reference"])
        self.assertEqual("Anton & Berta", result[2]["account_holder"])
        self.assertEqual("Mitgliedsbeitrag", result[2]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[2]["type_confidence"])
        self.assertIn("reference: Multiple (2) DB-IDs found in line 11!",
                      result[2]["problems"])
        
        self.assertEqual("8068901", result[3]["account"])
        self.assertEqual("31.12.2018", result[3]["date"])
        self.assertEqual("-18.54", result[3]["amount_export"])
        self.assertIn("Genutzte Freiposten", result[3]["reference"])
        self.assertEqual("", result[3]["account_holder"])
        self.assertEqual("Sonstiges", result[3]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[3]["type_confidence"])
        self.assertEqual("", result[3]["problems"])
        
        self.assertEqual("8068901", result[4]["account"])
        self.assertEqual("30.12.2018", result[4]["date"])
        self.assertEqual("-52.50", result[4]["amount_export"])
        self.assertEqual("KONTOFUEHRUNGSGEBUEHREN", result[4]["reference"])
        self.assertEqual("", result[4]["account_holder"])
        self.assertEqual("Sonstiges", result[4]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[4]["type_confidence"])
        self.assertEqual("", result[4]["problems"])

        self.assertEqual("8068900", result[5]["account"])
        self.assertEqual("22.12.2018", result[5]["date"])
        self.assertEqual("50.00", result[5]["amount_export"])
        self.assertEqual("Anton Armin A. Administrator DB-1-9 Spende",
                         result[5]["reference"])
        self.assertEqual("Anton", result[5]["account_holder"])
        self.assertEqual("Sonstiges", result[5]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[5]["type_confidence"])
        self.assertEqual("", result[5]["problems"])
        
        # check transactions files
        # check account 00
        f = save.forms["transactions_8068900"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=ACCOUNT_FIELDS))

        self.assertEqual("26.12.2018", result[0]["date"])
        self.assertEqual("10,00", result[0]["amount"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[0]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertEqual("8068900", result[0]["account"])

        self.assertEqual("25.12.2018", result[1]["date"])
        self.assertEqual("5,00", result[1]["amount"])
        self.assertEqual("DB-2-7", result[1]["db_id"])
        self.assertEqual("Beispiel", result[1]["name_or_holder"])
        self.assertEqual("Bertålotta", result[1]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[1]["category"])
        self.assertEqual("8068900", result[1]["account"])

        self.assertEqual("24.12.2018", result[2]["date"])
        self.assertEqual("2,50", result[2]["amount"])
        self.assertEqual("DB-7-8", result[2]["db_id"])
        self.assertEqual("Generalis", result[2]["name_or_holder"])
        self.assertEqual("Garcia G.", result[2]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[2]["category"])
        self.assertEqual("8068900", result[2]["account"])

        self.assertEqual("23.12.2018", result[3]["date"])
        self.assertEqual("2,50", result[3]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[3]["db_id"])
        self.assertEqual("Daniel Dino", result[3]["name_or_holder"])
        self.assertEqual("Mitgliedsbeitrag", result[3]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[3]["category"])
        self.assertEqual("8068900", result[3]["account"])

        self.assertEqual("22.12.2018", result[4]["date"])
        self.assertEqual("50,00", result[4]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[4]["db_id"])
        self.assertEqual("Anton", result[4]["name_or_holder"])
        self.assertEqual("Anton Armin A. Administrator DB-1-9 Spende",
                         result[4]["name_or_ref"])
        self.assertEqual("Sonstiges", result[4]["category"])
        self.assertEqual("8068900", result[4]["account"])

        self.assertEqual("21.12.2018", result[5]["date"])
        self.assertEqual("10,00", result[5]["amount"])
        self.assertEqual("DB-1-9", result[5]["db_id"])
        self.assertEqual("Administrator", result[5]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[5]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[5]["category"])
        self.assertEqual("8068900", result[5]["account"])

        self.assertEqual("20.12.2018", result[6]["date"])
        self.assertEqual("100,00", result[6]["amount"])
        self.assertEqual("DB-5-1", result[6]["db_id"])
        self.assertEqual("Eventis", result[6]["name_or_holder"])
        self.assertEqual("Emilia E.", result[6]["name_or_ref"])
        self.assertEqual("TestAka", result[6]["category"])
        self.assertEqual("8068900", result[6]["account"])

        # check account 01
        f = save.forms["transactions_8068901"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=ACCOUNT_FIELDS))

        self.assertEqual("31.12.2018", result[0]["date"])
        self.assertEqual("-18,54", result[0]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[0]["db_id"])
        self.assertEqual("", result[0]["name_or_holder"])
        self.assertIn("Genutzte Freiposten", result[0]["name_or_ref"])
        self.assertEqual("Sonstiges", result[0]["category"])
        self.assertEqual("8068901", result[0]["account"])

        self.assertEqual("30.12.2018", result[1]["date"])
        self.assertEqual("-52,50", result[1]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[1]["db_id"])
        self.assertEqual("", result[1]["name_or_holder"])
        self.assertEqual("KONTOFUEHRUNGSGEBUEHREN", result[1]["name_or_ref"])
        self.assertEqual("Sonstiges", result[1]["category"])
        self.assertEqual("8068901", result[1]["account"])

        self.assertEqual("29.12.2018", result[2]["date"])
        self.assertEqual("-584,49", result[2]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[2]["db_id"])
        self.assertEqual("Anton Administrator", result[2]["name_or_holder"])
        self.assertEqual("Kursleitererstattung Anton Armin A. Administrator "
                         "Große Testakademie 2222", result[2]["name_or_ref"])
        self.assertEqual("TestAka", result[2]["category"])
        self.assertEqual("8068901", result[2]["account"])

        self.assertEqual("28.12.2018", result[3]["date"])
        self.assertEqual("584,49", result[3]["amount"])
        self.assertEqual("DB-1-9", result[3]["db_id"])
        self.assertEqual("Administrator", result[3]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[3]["name_or_ref"])
        self.assertEqual("TestAka", result[3]["category"])
        self.assertEqual("8068901", result[3]["account"])

        self.assertEqual("27.12.2018", result[4]["date"])
        self.assertEqual("584,49", result[4]["amount"])
        self.assertEqual("DB-7-8", result[4]["db_id"])
        self.assertEqual("Generalis", result[4]["name_or_holder"])
        self.assertEqual("Garcia G.", result[4]["name_or_ref"])
        self.assertEqual("TestAka", result[4]["category"])
        self.assertEqual("8068901", result[4]["account"])
    
    @as_users("anton")
    def test_money_transfers(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/user'},
                      {'href': '/cde/transfers$'})
        self.assertTitle("Überweisungen eintragen")
        f = self.response.forms['transfersform']
        with open("/tmp/cdedb-store/testfiles/money_transfers.csv") as datafile:
            f['transfers'] = datafile.read()
        self.submit(f, check_notification=False)

        # first round
        self.assertPresence("Validieren")
        self.assertNonPresence("Abschicken")
        f = self.response.forms['transfersform']
        self.assertFalse(f['checksum'].value)
        content = self.response.lxml.xpath(
            "//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 7):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Validieren")
        output.append(head)
        expectation = (
            (r"persona_id:\W*Darf nicht leer sein.",
             r"family_name:\W*Darf nicht leer sein.",
             r"given_names:\W*Darf nicht leer sein.",
             r"amount:.*\W*Ungültige Eingabe für eine Dezimalzahl.",),
            (r"persona_id:\W*Falsches Format.",),
            (r"family_name:\W*Nachname passt nicht.",),
            (r"persona_id:\W*Falsches Format.",),
            (r"amount:\W*Überweisungsbetrag ist negativ.",),
            tuple(),
            (r"Mehrere Überweisungen für diesen Account \(Zeilen 6 und 7\).",),
            (r"Mehrere Überweisungen für diesen Account \(Zeilen 6 und 7\).",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        lines = f['transfers'].value.split('\n')
        inputdata = '\n'.join(lines[4:8]).replace('-12.34', '12.34')
        f['transfers'] = inputdata
        self.submit(f, check_notification=False)

        # second round
        self.assertPresence("Bestätigen")
        self.assertPresence("Saldo: 151,09 €")
        self.assertNonPresence("Validieren")
        f = self.response.forms['transfersform']
        self.assertTrue(f['checksum'].value)
        self.submit(f)
        self.assertPresence("4 Überweisungen gebucht. 1 neue Mitglieder.",
                            div="notifications")
        self.admin_view_profile("daniel")
        self.traverse({"description": "Änderungs-Historie"})
        self.assertPresence("Guthabenänderung um 100,00 € auf 100,00 € "
                            "(Überwiesen am 17.03.2019)")

    @as_users("anton")
    def test_money_transfers_file(self, user):
        self.get("/cde/transfers")
        f = self.response.forms['transfersform']
        # This file has a newline at the end, which needs to be stripped or it
        # causes the checksum to differ and require a third round.
        with open("/tmp/cdedb-store/testfiles/money_transfers_valid.csv", 'rb') as datafile:
            data = datafile.read().replace(b"\r", b"").replace(b"\n", b"\r\n")

        self.assertIn(b"\r\n", data)
        f['transfers_file'] = webtest.Upload("money_transfers_valid.csv", data, "text/csv")
        self.submit(f, check_notification=False)
        f = self.response.forms['transfersform']
        self.submit(f)

    @as_users("anton")
    def test_money_transfer_low_balance(self, user):
        self.admin_view_profile("daniel")
        self.assertPresence("Guthaben 0,00 €")
        self.get("/core/persona/4/membership/change")
        self.assertPresence("Zum Mitglied machen")
        self.get("/cde/transfers")
        f = self.response.forms["transfersform"]
        f["transfers"] = "1.00;DB-4-3;Dino;Daniel D.;"
        self.submit(f, check_notification=False)
        f = self.response.forms["transfersform"]
        self.submit(f)
        self.get("/core/persona/4/membership/change")
        self.assertPresence("Zum Mitglied machen")

    @as_users("anton")
    def test_semester(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/semester/show'})
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['billform']
        f['testrun'].checked = True
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'billform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['billform']
        f['addresscheck'].checked = True
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'ejectform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Derzeit haben 0 Mitglieder ein zu niedriges Guthaben")
        # Check error handling for bill
        self.submit(f, check_notification=False)
        self.assertPresence('Zahlungserinnerung bereits erledigt',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['ejectform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'balanceform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Derzeit haben 3 Mitglieder eine Probemitgliedschaft")
        # Check error handling for eject
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Bereinigung',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['balanceform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'proceedform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 43")
        # Check error handling for balance
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Guthabenaktualisierung',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'billform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 44")
        # Check error handling for proceed
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Beendigung des Semesters',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['billform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'ejectform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Derzeit haben 2 Mitglieder ein zu niedriges Guthaben")

        f = self.response.forms['ejectform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'balanceform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Derzeit haben 0 Mitglieder eine Probemitgliedschaft")

        f = self.response.forms['balanceform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'proceedform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 44")

        f = self.response.forms['proceedform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'billform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 45")
        self.assertIn('billform', self.response.forms)

    @as_users("anton")
    def test_expuls(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/semester/show'})
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['addresscheckform']
        f['testrun'].checked = True
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'addresscheckform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['addresscheckform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'proceedexpulsform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 42")
        # Check error handling for addresscheck
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage bereits erledigt',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'addresscheckform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 43")

        f = self.response.forms['noaddresscheckform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'proceedexpulsform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 43")
        # Check error handling for noaddresscheck
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage bereits erledigt',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        count = 0
        while count < 42:
            time.sleep(.1)
            self.traverse({'href': '/cde/semester/show'})
            if 'addresscheckform' in self.response.forms:
                break
            count += 1
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 44")
        self.assertIn('addresscheckform', self.response.forms)
        # Check error handling for proceedexpuls
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage noch nicht erledigt',
                            'notifications')
        self.assertTitle("Semesterverwaltung")

    @as_users("anton")
    def test_institutions(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/institution/summary'})
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertNotIn("title_2", f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Bildung und Begabung"
        f['moniker_-1'] = "BuB"
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertEqual("Bildung und Begabung", f['title_2'].value)
        f['title_1'] = "Monster Academy"
        f['moniker_1'] = "MA"
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertEqual("Bildung und Begabung", f['title_2'].value)
        f['delete_2'].checked = True
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertNotIn("title_2", f.fields)

    @as_users("anton")
    def test_list_past_events(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/event/list'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertPresence("PfingstAkademie")

    @as_users("anton")
    def test_show_past_event_course(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/event/list'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertPresence("PfingstAkademie")
        self.traverse({'href': '/past/event/1/show'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Great event!")
        self.traverse({'href': '/past/event/1/course/1/show'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Ringelpiez")

    @as_users("anton")
    def test_change_past_event(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'},
                      {'href': '/past/event/1/change'},)
        self.assertTitle("PfingstAkademie 2014 bearbeiten")
        f = self.response.forms['changeeventform']
        f['title'] = "Link Academy"
        f['institution'] = 1
        f['description'] = "Ganz ohne Minderjährige."
        self.submit(f)
        self.assertTitle("Link Academy")
        self.assertPresence("Club der Ehemaligen")
        self.assertPresence("Ganz ohne Minderjährige.")

    @as_users("anton")
    def test_create_past_event(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/past/event/list'},
                      {'href': '/past/event/create'})
        self.assertTitle("Verg. Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy II"
        f['shortname'] = "link"
        f['institution'] = 1
        f['description'] = "Ganz ohne Minderjährige."
        f['tempus'] = "1.1.2000"
        self.submit(f)
        self.assertTitle("Link Academy II")
        self.assertPresence("Club der Ehemaligen")
        self.assertPresence("Ganz ohne Minderjährige.")

    @as_users("anton")
    def test_create_past_event_with_courses(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/past/event/list'},
                      {'href': '/past/event/create'})
        self.assertTitle("Verg. Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy II"
        f['shortname'] = "link"
        f['institution'] = 1
        f['description'] = "Ganz ohne Minderjährige."
        f['tempus'] = "1.1.2000"
        f['courses'] = '''"1";"Hoola Hoop";"Spaß mit dem Reifen"
"2";"Abseilen";"Von ganz oben"
"3";"Tretbootfahren";""
'''
        self.submit(f)
        self.assertTitle("Link Academy II")
        self.assertPresence("Club der Ehemaligen")
        self.assertPresence("Ganz ohne Minderjährige.")
        self.assertPresence("Hoola Hoop")
        self.assertPresence("Abseilen")
        self.assertPresence("Tretbootfahren")

    @as_users("anton")
    def test_delete_past_event(self, user):
        self.get("/cde/past/event/list")
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertPresence("2014")
        self.get("/cde/past/event/1/show")
        self.assertTitle("PfingstAkademie 2014")
        f = self.response.forms['deletepasteventform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertNonPresence("2014")

    @as_users("anton")
    def test_change_past_course(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'},
                      {'href': '/past/event/1/course/1/show'},
                      {'href': '/past/event/1/course/1/change'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014) bearbeiten")
        f = self.response.forms['changecourseform']
        f['title'] = "Omph"
        f['description'] = "Loud and proud."
        self.submit(f)
        self.assertTitle("Omph (PfingstAkademie 2014)")
        self.assertPresence("Loud and proud.")

    @as_users("anton")
    def test_create_past_course(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'},
                      {'href': '/past/event/1/course/create'},)
        self.assertTitle("Kurs anlegen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['nr'] = "42"
        f['title'] = "Abstract Nonsense"
        f['description'] = "Lots of arrows."
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        self.assertPresence("Lots of arrows.")

    @as_users("anton")
    def test_delete_past_course(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'},
                      {'href': '/past/event/1/course/create'},)
        self.assertTitle("Kurs anlegen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['nr'] = "42"
        f['title'] = "Abstract Nonsense"
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        f = self.response.forms['deletecourseform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Abstract Nonsense")

    @as_users("anton")
    def test_participant_manipulation(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'},
                      {'href': '/past/event/1/course/1/show'},)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Garcia")
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-7-8"
        f['is_orga'].checked = True
        f['is_instructor'].checked = True
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Garcia")
        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Garcia")

        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'})
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-7-8"
        f['is_orga'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Garcia")
        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Garcia")

    def test_past_log(self):
        ## First: generate data
        self.test_participant_manipulation()
        self.logout()
        self.test_change_past_course()
        self.logout()
        self.test_create_past_course()
        self.logout()
        self.test_change_past_event()
        self.logout()
        self.test_create_past_event()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/cde/$'},
                      {'href': '/past/log'})
        self.assertTitle("Verg.-Veranstaltungen-Log [0–7]")
        f = self.response.forms['logshowform']
        f['codes'] = [1, 10, 21]
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Verg.-Veranstaltungen-Log [1–3]\n")

    def test_cde_log(self):
        ## First: generate data
        pass

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/log'})
        self.assertTitle("CdE-Log")

    def test_finance_log(self):
        ## First: generate data
        pass

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/finances'})
        self.assertTitle("Finanz-Log [0–1]")

    @as_users("anton")
    def test_changelog_meta(self, user):
        self.traverse({'href': '^/$'},
                      {'href': '/core/changelog/view'})
        self.assertTitle("Nutzerdaten-Log [0–11]")
        f = self.response.forms['logshowform']
        f['persona_id'] = "DB-2-7"
        self.submit(f)
        self.assertTitle("Nutzerdaten-Log [0–0]")
        self.assertPresence("Bertålotta Beispiel")
