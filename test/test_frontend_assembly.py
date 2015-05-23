#!/usr/bin/env python3

import unittest
import quopri
import webtest
import email.parser
from test.common import as_users, USER_DICT, FrontendTest

class TestAssemblyFrontend(FrontendTest):
    @as_users("anton", "berta", "kalif")
    def test_index(self, user):
        self.traverse({'href': '/assembly/'})

    @as_users("kalif")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("kalif")
    def test_changeuser(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/assembly/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content())

    @as_users("anton")
    def test_adminchangeuser(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-11-D"
        self.submit(f)
        self.traverse({'href': '/assembly/user/11/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.submit(f)
        self.assertIn("Zelda", self.response)
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")
        self.assertIn("Blowing in the wind.", self.response)

    @as_users("anton")
    def test_toggleactivity(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-11-D"
        self.submit(f)
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'description': '^Versammlung$'}, {'href': '/assembly/search/user/form'})
        self.assertTitle("Versammlungsnutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_username'] = 'f@'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("\nVersammlungsnutzersuche -- 1 Ergebnis gefunden\n")
        self.assertIn("Karabatschi", self.response.text)

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'description': '^Versammlung$'}, {'href': '/assembly/user/create'})
        self.assertTitle("Neuen Versammlungsnutzer anlegen")
        data = {
            "username": 'zelda@example.cde',
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "display_name": 'Zelda',
            "notes": "some fancy talk",
        }
        f = self.response.forms['newuserform']
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertIn("some fancy talk", self.response.text)

    @as_users("anton")
    def test_change_assembly(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},)
        self.assertTitle("Internationaler Kongress")
        self.traverse({'href': '/assembly/1/change'},)
        f = self.response.forms['changeassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertIn("Häretiker", self.response.text)

    @as_users("anton")
    def test_create_assembly(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/create'},)
        self.assertTitle("Versammlung anlegen")
        f = self.response.forms['createassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['signup_end'] = "2222-4-1 00:00:00"
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        f['notes'] = "Nur ein Aprilscherz"
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertIn("Häretiker", self.response.text)
        self.assertIn("Aprilscherz", self.response.text)

    @as_users("charly")
    def test_signup(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},)
        self.assertTitle("Internationaler Kongress")
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)
        mail = self.fetch_mail()[0]
        parser = email.parser.Parser()
        msg = parser.parsestr(mail)
        attachment = msg.get_payload()[1]
        value = attachment.get_payload(decode=True)
        with open("./bin/verify_votes.py", 'rb') as f:
            self.assertEqual(f.read(), value)

    @as_users("kalif")
    def test_list_attendees(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/attendees'})
        self.assertTitle("Anwesenheitsliste -- Internationaler Kongress")
        self.assertIn("Anton", self.response.text)
        self.assertIn("Bertålotta", self.response.text)
        self.assertIn("Kalif", self.response.text)
        self.assertIn("Inga", self.response.text)
        self.assertIn("Insgesamt 4 Anwesende.", self.response.text)
        self.assertNotIn("Charly", self.response.text)

    @as_users("anton")
    def test_conclude_assembly(self, user):
        self.logout()
        self.test_create_assembly()
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/2/show'},)
        self.assertTitle("Drittes CdE-Konzil")
        f = self.response.forms['signupform']
        self.submit(f)
        self.traverse({'href': '/assembly/2/show'},
                      {'href': '/assembly/2/change'},)
        f = self.response.forms['changeassemblyform']
        f['signup_end'] = "2002-4-1 00:00:00"
        self.submit(f)
        self.traverse({'href': '/assembly/2/ballot/list'},
                      {'href': '/assembly/2/ballot/create'},)
        f = self.response.forms['createballotform']
        f['title'] = 'Maximale Länge der Satzung'
        f['description'] = "Dann muss man halt eine alte Regel rauswerfen, wenn man eine neue will."
        f['vote_begin'] = "2002-4-1 00:00:00"
        f['vote_end'] = "2002-5-1 00:00:00"
        f['quorum'] = "0"
        f['votes'] = ""
        f['notes'] = "Kein Aprilscherz!"
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Drittes CdE-Konzil)")
        self.traverse({'href': '/assembly/2/show'},)
        self.assertTitle("Drittes CdE-Konzil")
        f = self.response.forms['concludeassemblyform']
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")

    @as_users("anton")
    def test_entity_ballot_simple(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},)
        self.assertTitle("Internationaler Kongress -- Abstimmungen")
        self.assertNotIn("Maximale Länge der Satzung", self.response.text)
        self.traverse({'href': '/assembly/1/ballot/create'},)
        f = self.response.forms['createballotform']
        f['title'] = 'Maximale Länge der Satzung'
        f['description'] = "Dann muss man halt eine alte Regel rauswerfen, wenn man eine neue will."
        f['vote_begin'] = "2222-4-1 00:00:00"
        f['vote_end'] = "2222-5-1 00:00:00"
        f['quorum'] = "0"
        f['votes'] = ""
        f['notes'] = "Kein Aprilscherz!"
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.traverse({'href': '/assembly/1/ballot/6/change'},)
        f = self.response.forms['changeballotform']
        self.assertEqual("Kein Aprilscherz!", f['notes'].value)
        f['notes'] = "April, April!"
        f['vote_begin'] = "2222-4-1 00:00:00"
        f['vote_end'] = "2222-4-1 00:00:01"
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.traverse({'href': '/assembly/1/ballot/6/change'},)
        f = self.response.forms['changeballotform']
        self.assertEqual("April, April!", f['notes'].value)
        self.traverse({'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},)
        self.assertTitle("Internationaler Kongress -- Abstimmungen")
        self.assertIn("Maximale Länge der Satzung", self.response.text)
        self.traverse({'href': '/assembly/1/ballot/6/show'},)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        f = self.response.forms['deleteballotform']
        self.submit(f)
        self.traverse({'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},)
        self.assertTitle("Internationaler Kongress -- Abstimmungen")
        self.assertNotIn("Maximale Länge der Satzung", self.response.text)

    @as_users("anton")
    def test_attachments(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/attachment/add'},)
        self.assertTitle("Datei anhängen (Internationaler Kongress)")
        f = self.response.forms['addattachmentform']
        f['title'] = "Maßgebliche Beschlussvorlage"
        f['filename'] = "beschluss.pdf"
        f['attachment'] = webtest.Upload("/tmp/cdedb-store/testfiles/form.pdf")
        self.submit(f)
        self.traverse({'href': '/assembly/1/show'},)
        saved_response = self.response
        self.traverse({'description': 'Maßgebliche Beschlussvorlage'},)
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = saved_response
        self.traverse({'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/2/show'},
                      {'href': '/attachment/add'},)
        self.assertTitle("Datei anhängen (Farbe des Logos)")
        f = self.response.forms['addattachmentform']
        f['title'] = "Magenta wie die Telekom"
        f['attachment'] = webtest.Upload("/tmp/cdedb-store/testfiles/form.pdf")
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        saved_response = self.response
        self.traverse({'description': 'Magenta wie die Telekom'},)
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = saved_response
        f = self.response.forms['removeattachmentform3']
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNotIn("Magenta wie die Telekom", self.response.text)

    @as_users("anton", "inga", "kalif")
    def test_vote(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/5/show'},)
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("", f['vote'].value)
        f['vote'] = "e>pi>1=0>i"
        self.submit(f)
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("e>pi>1=0>i", f['vote'].value)
        f['vote'] = "1=i>pi>e=0"
        self.submit(f)
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("1=i>pi>e=0", f['vote'].value)

    @as_users("anton", "inga", "kalif")
    def test_classical_vote_radio(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/3/show'},)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        f['vote'] = "Li"
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("Li", f['vote'].value)
        f['vote'] = "special: none"
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("special: none", f['vote'].value)
        self.assertNotIn("Du hast Dich enthalten.", self.response.text)
        f = self.response.forms['abstentionform']
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f['vote'].value)
        self.assertIn("Du hast Dich enthalten.", self.response.text)
        f['vote'] = "St"
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("St", f['vote'].value)

    @as_users("anton", "inga", "kalif")
    def test_classical_vote_select(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/4/show'},)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        f['vote'] = ["W", "S"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        tmp = {f.get('vote', index=0).value, f.get('vote', index=1).value}
        self.assertEqual({"W", "S"}, tmp)
        self.assertEqual(None, f.get('vote', index=2).value)
        f = self.response.forms['rejectionform']
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f.get('vote', index=0).value)
        self.assertNotIn("Du hast Dich enthalten.", self.response.text)
        f = self.response.forms['abstentionform']
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f.get('vote', index=0).value)
        self.assertIn("Du hast Dich enthalten.", self.response.text)
        f['vote'] = ["E"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f.get('vote', index=0).value)
        self.assertEqual(None, f.get('vote', index=1).value)
        self.assertEqual("E", f.get('vote', index=2).value)

    @as_users("anton", "inga", "kalif")
    def test_tally_and_get_result(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/1/show'},)
        self.assertTitle("Antwort auf die letzte aller Fragen (Internationaler Kongress)")
        mail = self.fetch_mail()[0]
        parser = email.parser.Parser()
        msg = parser.parsestr(mail)
        text = msg.get_payload()[0].get_payload()
        self.assertIn('die Abstimmung "Antwort auf die letzte aller Fragen" der Versammlung', text)
        self.traverse({'href': '/assembly/1/ballot/1/result'},)
        with open("/tmp/cdedb-store/testfiles/ballot_result.json", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)

    @as_users("anton")
    def test_extend(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/create'},)
        f = self.response.forms['createballotform']
        f['title'] = 'Maximale Länge der Satzung'
        f['vote_begin'] = "2002-4-1 00:00:00"
        f['vote_end'] = "2002-5-1 00:00:00"
        f['vote_extension_end'] = "2222-5-1 00:00:00"
        f['quorum'] = "1000"
        f['votes'] = ""
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.assertIn("Die Abstimmung hat das Quorum von 1000 Stimmen nicht erreicht,", self.response.text)

    @as_users("anton")
    def test_candidate_manipulation(self, user):
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/2/show'},)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNotIn("Dunkelaquamarin", self.response.text)
        f = self.response.forms['addcandidateform']
        f['moniker'] = 'aqua'
        f['description'] = 'Dunkelaquamarin'
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertIn("Dunkelaquamarin", self.response.text)
        f = self.response.forms['removecandidateform28']
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNotIn("Dunkelaquamarin", self.response.text)

    def test_log(self):
        ## First: generate data
        self.test_entity_ballot_simple()
        self.logout()
        self.test_conclude_assembly()
        ## test_tally_and_get_result
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/1/show'},)
        self.logout()
        self.test_extend()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/log'})
        self.assertTitle("\nVersammlung -- Logs (0--16)\n")
        f = self.response.forms['logshowform']
        f['codes'] = [0, 1, 2, 10, 11, 12, 14]
        f['assembly_id'] = 1
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("\nVersammlung -- Logs (1--7)\n")

        self.traverse({'description': '^Versammlung$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/log.*1'})
        self.assertTitle("\nVersammlung -- Logs (0--8)\n")
