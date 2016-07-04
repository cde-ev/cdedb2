#!/usr/bin/env python3

import re
import unittest
import time

from test.common import as_users, USER_DICT, FrontendTest
from cdedb.query import QueryOperators

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
        f['location'] = "Hyrule"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertPresence("Hyrule")
        self.assertPresence("Okarinas")
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("anton")
    def test_adminchangedata(self, user):
        self.admin_view_profile('berta', realm="cde")
        self.traverse({'href': '/cde/user/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("1933-04-03")

    @as_users("anton")
    def test_validation(self, user):
        self.admin_view_profile('berta', realm="cde")
        self.traverse({'href': '/cde/user/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "garbage"
        self.submit(f, check_notification=False)
        self.assertTitle("Administration -- Bertålotta Beispiel bearbeiten")
        self.assertIn("alert alert-danger", self.response.text)
        f = self.response.forms['changedataform']
        self.assertEqual("Zelda", f['display_name'].value)

    def test_consent(self):
        user = USER_DICT["garcia"]
        self.login(user)
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.traverse({'description': 'Start'})
        self.assertTitle("CdE Datenbank")
        self.traverse({'href': '/core/self/show'},
                      {'href': '/cde/self/consent'})
        f = self.response.forms['ackconsentform']
        self.submit(f)
        ## automatic check for success notification

    @as_users("anton", "berta")
    def test_member_search_one(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77")

    @as_users("anton", "berta")
    def test_member_search_accents(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77")

    @as_users("anton", "berta")
    def test_member_search(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_pevent_id'] = 1
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")

    @as_users("anton", "berta")
    def test_member_search_fulltext(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "876 @example.cde"
        self.submit(f)
        self.assertTitle("Mitgliedersuche")
        self.assertPresence("2 Mitglieder gefunden")
        self.assertPresence("Anton")
        self.assertPresence("Bertålotta")

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/cde/search/user'})
        self.assertTitle("CdE Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.similar.value
        f['qval_address'] = 'Garten'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("CdE Nutzerverwaltung")
        self.assertPresence("Ergebnis -- 1 Eintrag gefunden")
        self.assertIn('"row_0_id" value="2"', self.response.text)

    @as_users("anton")
    def test_user_search_csv(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/cde/search/user'})
        self.assertTitle("CdE Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.regex.value
        f['qval_address'] = 'a[rm]'
        f['qsel_personas.id'].checked = True
        f['qsel_birthday'].checked = True
        f['qsel_decided_search'].checked = True
        f['qsel_free_form'].checked = True
        f['qsel_given_names'].checked = True
        f['qord_primary'] = "personas.id"
        self.response = f.submit("CSV")
        expectation = '''personas.id;given_names;birthday;free_form;decided_search
2;Bertålotta;1981-02-11;Jede Menge Gefasel         Gut verteilt        Über mehrere Zeilen;True
3;Charly C.;1984-05-13;;True
4;Daniel D.;1963-02-19;;False
6;Ferdinand F.;1988-01-01;;True
'''.encode('utf-8')
        self.assertEqual(expectation, self.response.body)

    @as_users("anton")
    def test_toggle_activity(self, user):
        self.admin_view_profile('berta', realm="cde")
        self.assertTrue(self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertFalse(self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("anton")
    def test_modify_membership(self, user):
        self.admin_view_profile('berta', realm="cde")
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
        self.assertPresence("Daten sind nicht sichtbar")

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
            "gender": "0",
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
        self.assertFalse(self.response.lxml.get_element_by_id('input_checkbox_bub_search').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('input_checkbox_cloud_account').checked)
        f['is_searchable'].checked = True
        f['is_member'].checked = True
        f['trial_member'].checked = True
        f['bub_search'].checked = True
        f['cloud_account'].checked = False
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345")
        self.assertPresence("Probemitgliedschaft")
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.")

    @as_users("anton")
    def test_lastschrift_index(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
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
    def test_lastschrift_generate_transactions(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionsform']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)

    @as_users("anton")
    def test_lastschrift_generate_single_transaction(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)

    @as_users("anton")
    def test_lastschrift_transaction_rollback(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactionsuccessform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.traverse({'href': '^/$'})
        self.admin_view_profile('berta', realm="cde")
        self.assertPresence("17.50€")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        f = self.response.forms['transactionrollbackform4']
        self.submit(f)
        self.assertPresence("Keine aktive Einzugsermächtigung")
        self.traverse({'href': '^/$'})
        self.admin_view_profile('berta', realm="cde")
        self.assertPresence("12.50€")

    @as_users("anton")
    def test_lastschrift_transaction_cancel(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactioncancelform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn('generatetransactionform2', self.response.forms)
        self.assertNotIn('transactionsuccessform4', self.response.forms)

    @as_users("anton")
    def test_lastschrift_transaction_failure(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactionfailureform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertNotIn('transactionsuccessform4', self.response.forms)

    @as_users("anton")
    def test_lastschrift_skip(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['skiptransactionform2']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertNotIn('transactionsuccessform', self.response.forms)

    @as_users("anton")
    def test_lastschrift_create(self, user):
        self.admin_view_profile('charly', realm="cde")
        self.traverse({'href': '/cde/user/3/lastschrift'})
        self.assertPresence("Keine aktive Einzugsermächtigung")
        self.traverse({'href': '/cde/user/3/lastschrift/create'})
        self.assertTitle("Neue Einzugsermächtigung (Charly C. Clown)")
        f = self.response.forms['createlastschriftform']
        f['amount'] = "123.45"
        f['iban'] = "DE26370205000008068900"
        f['max_dsa'] = "0.1"
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
        self.admin_view_profile('berta', realm="cde")
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
        self.admin_view_profile('berta', realm="cde")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        f = self.response.forms['receiptform3']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton")
    def test_lastschrift_subscription_form(self, user):
        self.traverse({'href': '/cde'},
                      {'href': '/cde/i25p'},
                      {'href': '/cde/lastschrift/subscription'})
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    def test_lastschrift_subscription_form_anonymous(self):
        self.get("/cde/lastschrift/subscription")
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton")
    def test_batch_admission(self, user):
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/search/user'},
                      {'href': '/cde/admission$'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        with open("/tmp/cdedb-store/testfiles/batch_admission.csv") as datafile:
            f['accounts'] = datafile.read()
        self.submit(f, check_notification=False)

        ## first round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Validieren")
        output.append(head)
        expectation = (
            (r"given_names:\W*Mustn't be empty.",
             r"pevent_id:\W*No input supplied."),
            tuple(),
            (r"Lines 3 and 4 are the same.",),
            (r"Lines 3 and 4 are the same.",),
            (r"persona:\W*Doppelgangers found.",),
            (r"persona:\W*Doppelgangers found.",),
            (r"persona:\W*Doppelgangers found.",),
            (r"course:\W*No course available.",),
            (r"pevent_id:\W*No event found.",
             r"course:\W*No course available.",),
            (r"pcourse_id:\W*No course found.",),
            (r"birthday:\W*day is out of range for month",
             r"birthday:\W*Mandatory key missing."),
            (r"postal_code:\W*Invalid german postal code.",),
            (r"Lines 13 and 14 are the same.",),
            (r"Lines 13 and 14 are the same.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        for i in range(14):
            if i in (1, 7):
                expectation = '0'
            else:
                expectation = None
            self.assertEqual(expectation, f['resolution{}'.format(i)].value)
        inputdata = f['accounts'].value
        f['resolution0'] = 1
        f['resolution2'] = 1
        f['resolution3'] = 1
        f['resolution4'] = 4
        f['doppelganger_id4'] = '2'
        f['resolution5'] = 3
        f['doppelganger_id5'] = '4'
        f['resolution6'] = 2
        f['doppelganger_id6'] = '5'
        inputdata = inputdata.replace("pa99", "pa14")
        inputdata = inputdata.replace("Doomed course from hell", "Swish -- und alles ist gut")
        inputdata = inputdata.replace("31.02.1981", "21.02.1981")
        inputdata = inputdata.replace("00000", "07751")
        f['resolution12'] = 1
        f['resolution13'] = 1
        f['accounts'] = inputdata
        self.submit(f, check_notification=False)

        ## second round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Validieren".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"doppelganger:\W*Doppelganger not a CdE-Account.",),
            tuple(),
            (r"Entry changed.",),
            (r"Entry changed.",),
            (r"Entry changed.",),
            (r"Entry changed.",),
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
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"pevent_id:\W*No event found.",
             r"course:\W*No course available.",),
            (r"pcourse_id:\W*No course found.",),
            (r"birthday:\W*day is out of range for month",
             r"birthday:\W*Mandatory key missing."),
            (r"postal_code:\W*Invalid german postal code.",),
            tuple(),
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertFalse(re.search(piece, out))
        f['resolution6'] = 0
        f['resolution8'] = 0
        f['resolution9'] = 0
        f['resolution10'] = 0
        f['resolution11'] = 0
        self.submit(f, check_notification=False)

        ## third round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {}:".format(i))
            output.append(head)
        head, _ = content.split("Validieren".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"doppelganger:\W*Doppelganger choice doesn't fit resolution.",),
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
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"Entry changed.",),
            (r"Entry changed.",),
            (r"Entry changed.",),
            (r"Entry changed.",),
            tuple(),
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertFalse(re.search(piece, out))
        f['resolution6'] = 1
        f['doppelganger_id6'] = ''
        self.assertEqual('', f['finalized'].value)
        self.submit(f, check_notification=False)

        ## fourth round
        self.assertPresence("Anlegen")
        self.assertNonPresence("Validieren")
        f = self.response.forms['admissionform']
        self.assertEqual('True', f['finalized'].value)
        self.submit(f)
        self.assertPresence("Created 6 accounts.", div="notifications")

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
        self.assertPresence("ExPuls trägt die Nummer 42")
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
        self.assertPresence("ExPuls trägt die Nummer 43")
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
        self.assertPresence("ExPuls trägt die Nummer 43")
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
        self.assertPresence("ExPuls trägt die Nummer 44")
        self.assertIn('addresscheckform', self.response.forms)

    @as_users("anton")
    def test_institutions(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/institution/summary'})
        self.assertTitle("Organisationen der abg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertNotIn("title_2", f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Bildung und Begabung"
        f['moniker_-1'] = "BuB"
        self.submit(f)
        self.assertTitle("Organisationen der abg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertEqual("Bildung und Begabung", f['title_2'].value)
        f['title_1'] = "Monster Academy"
        f['moniker_1'] = "MA"
        self.submit(f)
        self.assertTitle("Organisationen der abg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertEqual("Bildung und Begabung", f['title_2'].value)
        f['delete_2'].checked = True
        self.submit(f)
        self.assertTitle("Organisationen der abg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertNotIn("title_2", f.fields)

    @as_users("anton")
    def test_list_past_events(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/event/list'})
        self.assertTitle("Abgeschlossene Veranstaltungen")
        self.assertPresence("PfingstAkademie")

    @as_users("anton")
    def test_show_past_event_course(self, user):
        self.traverse({'href': '/cde/$'}, {'href': '/past/event/list'})
        self.assertTitle("Abgeschlossene Veranstaltungen")
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
        self.assertTitle("Veranstaltung anlegen")
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
        self.assertTitle("Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy II"
        f['shortname'] = "link"
        f['institution'] = 1
        f['description'] = "Ganz ohne Minderjährige."
        f['tempus'] = "1.1.2000"
        f['courses'] = '''"Hoola Hoop";"Spaß mit dem Reifen"
"Abseilen";"Von ganz oben"
"Tretbootfahren";""
'''
        self.submit(f)
        self.assertTitle("Link Academy II")
        self.assertPresence("Club der Ehemaligen")
        self.assertPresence("Ganz ohne Minderjährige.")
        self.assertPresence("Hoola Hoop")
        self.assertPresence("Abseilen")
        self.assertPresence("Tretbootfahren")

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
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
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
        self.assertTitle("Kurs hinzufügen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['title'] = "Abstract Nonsense"
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        f = self.response.forms['deletecourseform']
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
        self.assertNonPresence("Emilia")
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-B"
        f['is_orga'].checked = True
        f['is_instructor'].checked = True
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Emilia")
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Emilia")

        self.traverse({'href': '/cde/$'},
                      {'href': '/past/event/list'},
                      {'href': '/past/event/1/show'})
        f = self.response.forms['addparticipantform']
        f['persona_id'] = "DB-5-B"
        f['is_orga'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Emilia")
        f = self.response.forms['removeparticipantform5']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Emilia")

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
        self.assertTitle("Log: Abgeschlossene Veranstaltungen [0–8]")
        f = self.response.forms['logshowform']
        f['codes'] = [0, 10, 21]
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Log: Abgeschlossene Veranstaltungen [1–4]\n")

    def test_cde_log(self):
        ## First: generate data
        pass

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/log'})
        self.assertTitle("Log: CdE allgemein [0–0]")

    @as_users("anton")
    def test_changelog_meta(self, user):
        self.traverse({'href': '^/$'},
                      {'href': '/core/changelog/view'})
        self.assertTitle("Nutzerdaten-Log [0–11]")
