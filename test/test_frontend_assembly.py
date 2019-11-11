#!/usr/bin/env python3

import datetime
import time
import webtest

from test.common import as_users, USER_DICT, FrontendTest

from cdedb.common import ASSEMBLY_BAR_MONIKER, now
from cdedb.query import QueryOperators


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
        self.traverse({'href': '/core/self/show'},
                      {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id(
                'displayname').text_content().strip())

    @as_users("anton", "ferdinand")
    def test_adminchangeuser(self, user):
        self.realm_admin_view_profile('kalif', 'assembly')
        self.traverse({'href': '/core/persona/11/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.assertNotIn('birthday', f.fields)
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")

    @as_users("anton", "ferdinand")
    def test_toggleactivity(self, user):
        self.realm_admin_view_profile('kalif', 'assembly')
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id(
                'activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id(
                'activity_checkbox').get('data-checked') == 'True')

    @as_users("anton", "ferdinand")
    def test_user_search(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/search/user'})
        self.assertTitle("Versammlungs-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'f@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Versammlungs-Nutzerverwaltung")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Karabatschi")

    @as_users("anton", "ferdinand")
    def test_create_user(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/search/user'},
                      {'href': '/assembly/user/create'})
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

    @as_users("anton")
    def test_change_assembly(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},)
        self.assertTitle("Internationaler Kongress")
        self.traverse({'href': '/assembly/1/change'},)
        f = self.response.forms['changeassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertPresence("Häretiker")

    @as_users("anton")
    def test_create_assembly(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/create'},)
        self.assertTitle("Versammlung anlegen")
        f = self.response.forms['createassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['signup_end'] = "2222-4-1 00:00:00"
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        f['notes'] = "Nur ein Aprilscherz"
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertPresence("Häretiker")
        self.assertPresence("Aprilscherz")

    @as_users("anton")
    def test_delete_assembly(self, user):
        self.logout()
        self.test_create_assembly()
        f = self.response.forms['deleteassemblyform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Versammlungen")
        self.assertNonPresence("Drittes CdE-Konzil")

    @as_users("charly")
    def test_signup(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},)
        self.assertTitle("Internationaler Kongress")
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("anton", "ferdinand")
    def test_external_signup(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/create'},)
        f = self.response.forms['createassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['signup_end'] = "2222-4-1 00:00:00"
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        f['notes'] = "Nur ein Aprilscherz"
        self.submit(f)
        self.assertTitle('Drittes CdE-Konzil')
        self.traverse({'href': '/assembly/2/attendees'})
        self.assertNonPresence("Kalif")
        self.traverse({'href': '/assembly/2/attendees'})
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-11-6"
        self.submit(f)
        self.assertTitle('Anwesenheitsliste (Drittes CdE-Konzil)')
        self.traverse({'href': '/assembly/2/attendees'})
        self.assertPresence("Kalif")

    @as_users("kalif")
    def test_list_attendees(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/attendees'})
        self.assertTitle("Anwesenheitsliste (Internationaler Kongress)")
        self.assertPresence("Anton")
        self.assertPresence("Bertålotta")
        self.assertPresence("Kalif")
        self.assertPresence("Inga")
        self.assertPresence("Insgesamt 4 Anwesende.")
        self.assertNonPresence("Charly")

    @as_users("anton")
    def test_conclude_assembly(self, user):
        self.logout()
        self.test_create_assembly()
        self.traverse({'href': '/assembly/$'},
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
        future = now() + datetime.timedelta(seconds=.5)
        farfuture = now() + datetime.timedelta(seconds=1)
        f['vote_begin'] = future.isoformat()
        f['vote_end'] = farfuture.isoformat()
        f['quorum'] = "0"
        f['votes'] = ""
        f['notes'] = "Kein Aprilscherz!"
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Drittes CdE-Konzil)")
        time.sleep(1)
        self.traverse({'href': '/assembly/2/ballot/list'},
                      {'description': 'Maximale Länge der Satzung'},
                      {'href': '/assembly/2/show'},)
        self.assertTitle("Drittes CdE-Konzil")
        f = self.response.forms['concludeassemblyform']
        f['ack_conclude'].checked = True
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")

    @as_users("anton")
    def test_preferential_vote_result(self, user):
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Du hast mit 2>3>_bar_>1=4 abgestimmt.")

    @as_users("garcia")
    def test_show_ballot_without_vote(self, user):
        self.get('/assembly/assembly/1/show')
        f = self.response.forms['signupform']
        self.submit(f)
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Du hast nicht abgestimmt.")

    @as_users("garcia")
    def test_show_ballot_without_attendance(self, user):
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Du nimmst nicht an der Versammlung teil.")

    @as_users("anton")
    def test_entity_ballot_simple(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Maximale Länge der Satzung")
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
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertPresence("Maximale Länge der Satzung")
        self.traverse({'href': '/assembly/1/ballot/6/show'},)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse({'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Maximale Länge der Satzung")

    @as_users("anton")
    def test_delete_ballot(self, user):
        self.get("/assembly/assembly/1/ballot/2/show")
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertPresence("Diese Abstimmung hat noch nicht begonnen.")
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Farbe des Logos")
        self.assertNonPresence("Zukünftige Abstimmungen")
        self.traverse({"description": "Lieblingszahl"})
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung läuft.")
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)
        self.get("/assembly/assembly/1/ballot/list")
        self.traverse({"description": "Antwort auf die letzte aller Fragen"})
        self.assertTitle("Antwort auf die letzte aller Fragen (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung ist beendet.")
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)

    @as_users("anton")
    def test_attachments(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/attachment/add'},)
        self.assertTitle("Datei anhängen (Internationaler Kongress)")
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()

        # First try upload with invalid default filename
        f = self.response.forms['addattachmentform']
        f['title'] = "Maßgebliche Beschlussvorlage"
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        self.submit(f, check_notification=False)
        self.assertValidationError("filename", "Darf nur aus druckbaren ASCII-Zeichen bestehen")
        # Now, add an correct override filename
        f = self.response.forms['addattachmentform']
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        f['filename'] = "beschluss.pdf"
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
        self.assertTitle("Datei anhängen (Internationaler Kongress/Farbe des Logos)")
        f = self.response.forms['addattachmentform']
        f['title'] = "Magenta wie die Telekom"
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['attachment'] = webtest.Upload("form.pdf", data, "application/octet-stream")
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        saved_response = self.response
        self.traverse({'description': 'Magenta wie die Telekom'},)
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = saved_response
        f = self.response.forms['removeattachmentform2']
        f['attachment_ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNonPresence("Magenta wie die Telekom")

    @as_users("anton", "inga", "kalif")
    def test_vote(self, user):
        self.traverse({'href': '/assembly/$'},
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
        self.traverse({'href': '/assembly/$'},
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
        f['vote'] = ASSEMBLY_BAR_MONIKER
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        self.assertEqual(ASSEMBLY_BAR_MONIKER, f['vote'].value)
        self.assertNonPresence("Du hast Dich enthalten.")
        f = self.response.forms['abstentionform']
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f['vote'].value)
        self.assertPresence("Du hast Dich enthalten.")
        f['vote'] = "St"
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("St", f['vote'].value)

    @as_users("anton", "inga", "kalif")
    def test_classical_vote_select(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/4/show'},)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        f['vote'] = ["W", "S"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        tmp = {f.get('vote', index=1).value, f.get('vote', index=4).value}
        self.assertEqual({"W", "S"}, tmp)
        self.assertEqual(None, f.get('vote', index=2).value)
        f['vote'] = [ASSEMBLY_BAR_MONIKER]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(ASSEMBLY_BAR_MONIKER, f.get('vote', index=5).value)
        self.assertEqual(None, f.get('vote', index=0).value)
        self.assertEqual(None, f.get('vote', index=1).value)
        self.assertNonPresence("Du hast Dich enthalten.")
        f = self.response.forms['abstentionform']
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(None, f.get('vote', index=0).value)
        self.assertPresence("Du hast Dich enthalten.")
        f['vote'] = ["E"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("E", f.get('vote', index=0).value)
        self.assertEqual(None, f.get('vote', index=1).value)
        self.assertEqual(None, f.get('vote', index=2).value)

    @as_users("anton", "inga", "kalif")
    def test_tally_and_get_result(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/1/show'},)
        self.assertTitle("Antwort auf die letzte aller Fragen (Internationaler Kongress)")
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        self.assertIn('die Abstimmung "Antwort auf die letzte aller Fragen" der Versammlung', text)
        self.traverse({'href': '/assembly/1/ballot/1/result'},)
        with open("/tmp/cdedb-store/testfiles/ballot_result.json", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)

    @as_users("anton")
    def test_extend(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/create'},)
        f = self.response.forms['createballotform']
        f['title'] = 'Maximale Länge der Verfassung'
        future = now() + datetime.timedelta(seconds=.5)
        farfuture = now() + datetime.timedelta(seconds=1)
        f['vote_begin'] = future.isoformat()
        f['vote_end'] = farfuture.isoformat()
        f['vote_extension_end'] = "2222-5-1 00:00:00"
        f['quorum'] = "1000"
        f['votes'] = ""
        self.submit(f)
        self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
        time.sleep(1)
        self.traverse({'href': '/assembly/1/ballot/list'},
                      {'description': 'Maximale Länge der Verfassung'},)
        self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
        self.assertPresence("verlängert, da 1000 Stimmen nicht erreicht wurden.")

    @as_users("anton")
    def test_candidate_manipulation(self, user):
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/2/show'},)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNonPresence("Dunkelaquamarin")
        f = self.response.forms['addcandidateform']
        f['moniker'] = 'aqua'
        f['description'] = 'Dunkelaquamarin'
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertPresence("Dunkelaquamarin")
        f = self.response.forms['removecandidateform28']
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNonPresence("Dunkelaquamarin")

    @as_users("anton")
    def test_provide_secret(self, user):
        # Create new assembly.
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Versammlung anlegen'})
        f = self.response.forms["createassemblyform"]
        f['title'] = 'Drittes CdE-Konzil'
        f['signup_end'] = "2222-4-1 00:00:00"
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        f['notes'] = "Nur ein Aprilscherz"
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        f = self.response.forms['signupform']
        self.submit(f)
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        secret = text.split(
            "Versammlung lautet", 1)[1].split("ohne Leerzeichen.", 1)[0].strip()
        self.traverse({"description": "Abstimmungen"},
                      {"description": "Abstimmung anlegen"})
        f = self.response.forms["createballotform"]
        f['title'] = 'Maximale Länge der Verfassung'
        wait_time = 2
        future = now() + datetime.timedelta(seconds=wait_time)
        farfuture = now() + datetime.timedelta(seconds=2*wait_time)
        f['vote_begin'] = future.isoformat()
        f['vote_end'] = farfuture.isoformat()
        f['quorum'] = "0"
        f['votes'] = "1"
        self.submit(f)
        f = self.response.forms["addcandidateform"]
        f['moniker'] = "ja"
        f['description'] = "Ja"
        self.submit(f)
        f['moniker'] = "nein"
        f['description'] = "Nein"
        self.submit(f)
        time.sleep(wait_time)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Verfassung'})
        f = self.response.forms["voteform"]
        f["vote"] = "ja"
        self.submit(f)
        time.sleep(wait_time)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Verfassung'})
        self.assertPresence(
            "Du hast für die folgenden Kandidaten gestimmt: Ja")
        self.traverse({'description': 'Versammlungs-Übersicht'},
                      {'description': 'Drittes CdE-Konzil'})
        self.assertTitle("Drittes CdE-Konzil")
        f = self.response.forms['concludeassemblyform']
        f['ack_conclude'].checked = True
        self.submit(f)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Verfassung'})
        self.assertPresence("Die Versammlung wurde beendet und die "
                            "Stimmen sind nun verschlüsselt.")
        self.assertNonPresence(
            "Du hast für die folgenden Kandidaten gestimmt:")
        f = self.response.forms['showoldvoteform']
        f['secret'] = secret
        self.submit(f, check_notification=False)
        self.assertNonPresence("Die Versammlung wurde beendet und die "
                               "Stimmen sind nun verschlüsselt.")
        self.assertPresence(
            "Du hast für die folgenden Kandidaten gestimmt: Ja")

    def test_log(self):
        ## First: generate data
        self.test_entity_ballot_simple()
        self.logout()
        self.test_conclude_assembly()
        ## test_tally_and_get_result
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/1/ballot/list'},
                      {'href': '/assembly/1/ballot/1/show'},)
        self.logout()
        self.test_extend()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/log'})
        self.assertTitle("\nVersammlungs-Log [0–14]\n")
        f = self.response.forms['logshowform']
        f['codes'] = [0, 1, 2, 10, 11, 12, 14]
        f['assembly_id'] = 1
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("\nVersammlungs-Log [1–6]\n")

        self.traverse({'href': '/assembly/$'},
                      {'href': '/assembly/1/show'},
                      {'href': '/assembly/log.*1'})
        self.assertTitle("\nVersammlungs-Log [0–7]\n")
