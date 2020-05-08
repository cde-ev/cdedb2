#!/usr/bin/env python3

import datetime
import re
import time
import webtest
import unittest

from test.common import as_users, USER_DICT, FrontendTest

from cdedb.common import ASSEMBLY_BAR_MONIKER, now, ADMIN_VIEWS_COOKIE_NAME
from cdedb.query import QueryOperators
import cdedb.database.constants as const


class TestAssemblyFrontend(FrontendTest):
    # Helper functions:

    def _create_assembly(self, adata=None):
        if not adata:
            adata = {
                'title': 'Drittes CdE-Konzil',
                'signup_end': "2222-4-1 00:00:00",
                'description': "Wir werden alle Häretiker exkommunizieren.",
                'notes': "Nur ein Aprilscherz",
            }
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Versammlung anlegen'})
        self.assertTitle("Versammlung anlegen")
        f = self.response.forms['createassemblyform']
        for k, v in adata.items():
            f[k] = v
        self.submit(f)
        self.assertTitle(adata['title'])

    def _signup(self):
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertNotIn('signupform', self.response.forms)
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        secret = text.split(
            "Versammlung lautet", 1)[1].split("ohne Leerzeichen.", 1)[0].strip()
        return secret

    def _create_ballot(self, bdata, candidates=None, atitle=None):
        self.traverse({"description": "Abstimmungen"},
                      {"description": "Abstimmung anlegen"})
        f = self.response.forms["createballotform"]
        for k, v in bdata.items():
            f[k] = v
        self.submit(f)
        if atitle:
            self.assertTitle("{} ({})".format(bdata['title'], atitle))
        self.traverse({"description": "Abstimmungen"},
                      {"description": bdata['title']})
        if candidates:

            for candidate in candidates:
                f = self.response.forms["candidatessummaryform"]
                for k, v in candidate.items():
                    f[f'{k}_-1'] = v
                f['create_-1'].checked = True
                self.submit(f)

    @as_users("werner", "berta", "kalif")
    def test_index(self, user):
        self.traverse({'href': '/assembly/'})

    @as_users("annika", "martin", "vera", "werner")
    def test_sidebar(self, user):
        self.traverse({'description': 'Versammlungen'})
        everyone = ["Versammlungen", "Übersicht"]
        admins = ["Nutzer verwalten", "Log"]

        # not assembly admins
        if user in [USER_DICT['annika'], USER_DICT['martin'], USER_DICT['vera']]:
            ins = everyone
            out = admins
        # assembly admins
        elif user == USER_DICT['werner']:
            ins = everyone + admins
            out = []
        else:
            self.fail("Please adjust users for this test.")

        self.check_sidebar(ins, out)

    @as_users("kalif")
    def test_showuser(self, user):
        self.traverse({'description': user['display_name']})
        self.assertPresence("Versammlungen", div="has-realm")
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("kalif")
    def test_changeuser(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id(
                'displayname').text_content().strip())

    @as_users("werner", "ferdinand")
    def test_adminchangeuser(self, user):
        self.realm_admin_view_profile('kalif', 'assembly')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.assertNotIn('birthday', f.fields)
        self.submit(f)
        self.assertPresence("Zelda", div="personal-information")
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")

    @as_users("werner", "ferdinand")
    def test_toggleactivity(self, user):
        self.realm_admin_view_profile('kalif', 'assembly')
        self.assertPresence('Ja', div='account-active')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence('Nein', div='account-active')

    @as_users("werner", "ferdinand")
    def test_user_search(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Nutzer verwalten'})
        self.assertTitle("Versammlungs-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'f@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Versammlungs-Nutzerverwaltung")
        self.assertPresence("Ergebnis [1]", div="query-results")
        self.assertPresence("Karabatschi", div="result-container")

    @as_users("werner", "ferdinand")
    def test_create_user(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Nutzer anlegen'})
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
    def test_assembly_admin_views(self, user):
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')

        self.traverse({'href': '/assembly/'})
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=False)

        # Test Assembly Management Admin View
        self.assertNoLink('/assembly/log')
        self.traverse({'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/attendees'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/show'},
                      {'href': '/assembly/assembly/1/show'})
        self.assertNoLink('assembly/assembly/1/change')
        self.assertNoLink('assembly/assembly/1/log')
        self.assertNotIn('concludeassemblyform', self.response.forms)
        self._click_admin_view_button(re.compile(r"Versammlungs-Verwaltung"),
                                      current_state=False)
        self.assertIn('concludeassemblyform', self.response.forms)
        self.traverse({'href': 'assembly/assembly/1/change'},
                      {'href': 'assembly/assembly/1/log'})

        # Test Assembly Configuration Admin View
        self.traverse({'href': '/assembly/assembly/1/show'})
        self.assertNoLink('/assembly/assembly/1/attachment/add')
        self.traverse({'href': '/assembly/assembly/1/ballot/list'})
        self.assertNoLink('/assembly/assembly/1/ballot/2/change')
        self.assertNoLink('/assembly/assembly/1/ballot/create')
        self.traverse({'href': '/assembly/assembly/1/ballot/2/show'})
        self.assertNoLink('/assembly/assembly/1/ballot/2/change')
        self.assertNoLink('/assembly/assembly/1/ballot/2/attachment/add')
        self.assertNotIn('removecandidateform6', self.response.forms)
        self.assertNotIn('addcandidateform', self.response.forms)
        self.assertNotIn('deleteballotform', self.response.forms)

        self._click_admin_view_button(re.compile(r"Versammlungs-Verwaltung"),
                                      current_state=True)
        self._click_admin_view_button(re.compile(r"Versammlungs-Konfig."),
                                      current_state=False)
        self.traverse({'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/attachment/add'},
                      {'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/change'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/create'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/show'},
                      {'href': '/assembly/assembly/1/ballot/2/attachment/add'},
                      {'href': '/assembly/assembly/1/ballot/2/show'})
        self.assertIn('candidatessummaryform', self.response.forms)
        self.assertIn('deleteballotform', self.response.forms)

    @as_users("annika", "martin", "vera", "werner")
    def test_sidebar_one_assembly(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'})
        everyone = ["Versammlungs-Übersicht", "Übersicht", "Teilnehmer",
                    "Abstimmungen", "Zusammenfassung"]
        admin = ["Konfiguration", "Log"]

        # not assembly admins
        if user in [USER_DICT['annika'], USER_DICT['martin'], USER_DICT['vera']]:
            ins = everyone
            out = admin
        # assembly admin
        elif user == USER_DICT['werner']:
            ins = everyone + admin
            out = []
        else:
            self.fail("Please adjust users for this test.")

        self.check_sidebar(ins, out)

    @as_users("werner")
    def test_change_assembly(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        self.traverse({'description': 'Konfiguration'},)
        f = self.response.forms['changeassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertPresence("Häretiker", div='description')

    @as_users("werner")
    def test_create_assembly(self, user):
        self._create_assembly()
        self.assertPresence("Häretiker", div='description')
        self.assertPresence("Aprilscherz", div='notes')
        self.traverse({'description': 'Abstimmungen'})
        self.assertPresence("Es wurden noch keine Abstimmungen angelegt.")

    @as_users("werner")
    def test_delete_assembly(self, user):
        self._create_assembly()
        f = self.response.forms['deleteassemblyform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Versammlungen")
        self.assertNonPresence("Drittes CdE-Konzil")

    @as_users("charly")
    def test_signup(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("werner", "ferdinand")
    def test_external_signup(self, user):
        self._create_assembly()
        self.assertNonPresence("Kalif")
        self.traverse({'description': 'Teilnehmer'})
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-11-6"
        self.submit(f)
        self.assertTitle('Anwesenheitsliste (Drittes CdE-Konzil)')
        self.assertPresence("Kalif", div='attendees-list')

    @as_users("kalif")
    def test_list_attendees(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Teilnehmer'})
        self.assertTitle("Anwesenheitsliste (Internationaler Kongress)")
        self.assertPresence("Anton", div='attendees-list')
        self.assertPresence("Akira", div='attendees-list')
        self.assertPresence("Bertålotta", div='attendees-list')
        self.assertPresence("Kalif", div='attendees-list')
        self.assertPresence("Inga", div='attendees-list')
        self.assertPresence("Werner", div='attendees-list')
        self.assertPresence("Insgesamt 6 Anwesende.", div='attendees-count')
        self.assertNonPresence("Charly")

    @as_users("werner")
    def test_conclude_assembly(self, user):
        self._create_assembly()
        f = self.response.forms['signupform']
        self.submit(f)
        self.traverse({'description': 'Konfiguration'})
        f = self.response.forms['changeassemblyform']
        f['signup_end'] = "2002-4-1 00:00:00"
        self.submit(f)

        wait_time = 0.5
        future = now() + datetime.timedelta(seconds=wait_time)
        farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
        bdata = {
            'title': 'Maximale Länge der Satzung',
            'description': "Dann muss man halt eine alte Regel rauswerfen, wenn man eine neue will.",
            'vote_begin': future.isoformat(),
            'vote_end': farfuture.isoformat(),
            'quorum': "0",
            'votes': "",
            'notes': "Kein Aprilscherz!",
        }
        self._create_ballot(bdata, candidates=None)
        self.assertTitle("Maximale Länge der Satzung (Drittes CdE-Konzil)")
        time.sleep(2 * wait_time)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Satzung'},
                      {'description': 'Drittes CdE-Konzil'},)
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
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.assertPresence("Du hast mit 2>3>_bar_>1=4 abgestimmt.",
                            div='own-vote', exact=True)

    @as_users("garcia")
    def test_show_ballot_without_vote(self, user):
        self.get('/assembly/assembly/1/show')
        f = self.response.forms['signupform']
        self.submit(f)
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    @as_users("garcia")
    def test_show_ballot_without_attendance(self, user):
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.assertPresence("Du nimmst nicht an der Versammlung teil.",
                            div='own-vote', exact=True)

    @as_users("werner")
    def test_entity_ballot_simple(self, user):
        self.traverse({'description': 'Versammlungen$'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Maximale Länge der Satzung")
        self.assertNonPresence("Es wurden noch keine Abstimmungen angelegt")
        bdata = {
            'title': 'Maximale Länge der Satzung',
            'description': "Dann muss man halt eine alte Regel rauswerfen, wenn man eine neue will.",
            'vote_begin': "2222-4-1 00:00:00",
            'vote_end': "2222-5-1 00:00:00",
            'votes': "",
            'notes': "Kein Aprilscherz!",

        }
        self._create_ballot(bdata, atitle="Internationaler Kongress")
        self.traverse({'description': 'Bearbeiten'},)
        f = self.response.forms['changeballotform']
        self.assertEqual("Kein Aprilscherz!", f['notes'].value)
        f['notes'] = "April, April!"
        f['vote_begin'] = "2222-4-1 00:00:00"
        f['vote_end'] = "2222-4-1 00:00:01"
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.traverse({'description': 'Bearbeiten'},)
        f = self.response.forms['changeballotform']
        self.assertEqual("April, April!", f['notes'].value)
        self.traverse({'description': 'Abstimmungen'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertPresence("Maximale Länge der Satzung")
        self.traverse({'description': 'Maximale Länge der Satzung'},)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse({'description': 'Abstimmungen'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Maximale Länge der Satzung")

    @as_users("werner")
    def test_delete_ballot(self, user):
        self.get("/assembly/assembly/1/ballot/2/show")
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertPresence("Diese Abstimmung hat noch nicht begonnen.",
                            div='status')
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        self.assertNonPresence("Farbe des Logos")
        self.assertNonPresence("Zukünftige Abstimmungen")
        self.traverse({"description": "Lieblingszahl"})
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung läuft.", div='status')
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)
        self.get("/assembly/assembly/1/ballot/list")
        self.traverse({"description": "Antwort auf die letzte aller Fragen"})
        self.assertTitle("Antwort auf die letzte aller Fragen (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung ist beendet.", div='status')
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)

    @as_users("werner")
    def test_attachments(self, user):
        self.traverse({'description': 'Versammlungen$'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Datei anhängen'},)
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
        self.assertPresence("Maßgebliche Beschlussvorlage", div='attachments')

        saved_response = self.response
        self.traverse({'description': 'Maßgebliche Beschlussvorlage'},)
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = saved_response

        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Farbe des Logos'},
                      {'description': 'Datei anhängen'},)
        self.assertTitle("Datei anhängen (Internationaler Kongress/Farbe des Logos)")
        f = self.response.forms['addattachmentform']
        f['title'] = "Magenta wie die Telekom"
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['attachment'] = webtest.Upload("form.pdf", data, "application/octet-stream")
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        saved_response = self.response
        self.assertPresence("Magenta wie die Telekom", div='attachments')
        self.traverse({'description': 'Magenta wie die Telekom'},)
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = saved_response
        f = self.response.forms['removeattachmentform1002']
        f['attachment_ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertNonPresence("Magenta wie die Telekom")

    @as_users("werner", "inga", "kalif")
    def test_vote(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Lieblingszahl'},)
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

    @as_users("werner", "inga", "kalif")
    def test_classical_vote_radio(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Bester Hof'},)
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
        self.assertPresence("Du hast Dich enthalten.", div='status')
        f['vote'] = "St"
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("St", f['vote'].value)

    @as_users("werner", "inga", "kalif")
    def test_classical_vote_select(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Akademie-Nachtisch'},)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        f['vote'] = ["W", "S"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        tmp = {f.get('vote', index=3).value, f.get('vote', index=4).value}
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
        self.assertPresence("Du hast Dich enthalten.", div='status')
        f['vote'] = ["E"]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual("E", f.get('vote', index=0).value)
        self.assertEqual(None, f.get('vote', index=1).value)
        self.assertEqual(None, f.get('vote', index=2).value)

    @as_users("werner")
    def test_classical_voting_all_choices(self, user):
        # This test asserts that in classical voting, we can distinguish
        # between abstaining and voting for all candidates
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'})

        # We need two subtests: One with an explict bar (including the "against
        # all candidates option), one without an explicit bar (i.e. the bar is
        # added implicitly)
        for use_bar in (False, True):
            with self.subTest(use_bar=use_bar):
                # First, create a new ballot
                wait_time = 2
                future = now() + datetime.timedelta(seconds=wait_time)
                farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
                bdata = {
                    'title': 'Wahl zum Finanzvorstand -- {} bar'
                             .format("w." if use_bar else "w/o"),
                    'vote_begin': future.isoformat(),
                    'vote_end': farfuture.isoformat(),
                    'quorum': "0",
                    'votes': "2",
                    'use_bar': use_bar,
                }
                candidates = [
                    {'moniker': 'arthur', 'description': 'Arthur Dent'},
                    {'moniker': 'ford', 'description': 'Ford Prefect'},
                ]
                self._create_ballot(bdata, candidates)

                # Wait for voting to start then cast own vote.
                time.sleep(wait_time)
                self.traverse({'description': 'Abstimmungen'},
                              {'description': bdata['title']})

                f = self.response.forms["voteform"]
                f["vote"] = ["arthur"]
                self.submit(f)
                self.assertNonPresence("Du hast Dich enthalten.")

                if use_bar:
                    f = self.response.forms["voteform"]
                    f["vote"] = [ASSEMBLY_BAR_MONIKER]
                    self.submit(f)
                    self.assertNonPresence("Du hast Dich enthalten.")

                f = self.response.forms["voteform"]
                f["vote"] = []
                self.submit(f)
                self.assertPresence("Du hast Dich enthalten.", div='status')

                f = self.response.forms['abstentionform']
                self.submit(f)
                self.assertPresence("Du hast Dich enthalten.", div='status')

                f = self.response.forms["voteform"]
                f["vote"] = ["arthur", "ford"]
                self.submit(f)
                self.assertNonPresence("Du hast Dich enthalten.")

                # Check tally and own vote.
                time.sleep(wait_time)
                self.traverse({'description': 'Abstimmungen'},
                              {'description': bdata['title']})
                self.assertPresence("Du hast für die folgenden Kandidaten "
                                    "gestimmt: Arthur Dent, Ford Prefect",
                                    div='own-vote', exact=True)

    @as_users("werner", "inga", "kalif")
    def test_tally_and_get_result(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},)
        self.assertTitle("Internationaler Kongress – Abstimmungen")
        mail = self.fetch_mail()[0]
        text = mail.get_body().get_content()
        self.assertIn('"Antwort auf die letzte aller Fragen"', text)
        self.assertIn('"Internationaler Kongress"', text)
        self.traverse({'description': 'Antwort auf die letzte aller Fragen'},
                      {'description': 'Ergebnisdatei herunterladen'},)
        with open("/tmp/cdedb-store/testfiles/ballot_result.json", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)

    @as_users("werner")
    def test_extend(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Abstimmung anlegen'},)
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
        self.assertPresence(
            "Verlängerung bis 01.05.2222, 00:00:00, falls 1000 Stimmen nicht "
            "erreicht werden.", div='voting-period')
        time.sleep(1)
        self.traverse({'href': '/assembly/1/ballot/list'},
                      {'description': 'Maximale Länge der Verfassung'},)
        self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
        s = ("Wurde bis 01.05.2222, 00:00:00 verlängert, da 1000 Stimmen nicht "
             "erreicht wurden.")
        self.assertPresence(s, div='voting-period')

    @as_users("werner")
    def test_candidate_manipulation(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Farbe des Logos'},)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        self.assertEqual("rot", f['moniker_6'].value)
        self.assertEqual("gelb", f['moniker_7'].value)
        self.assertEqual("gruen", f['moniker_8'].value)
        self.assertNotIn("Dunkelaquamarin", f.fields)
        f['create_-1'].checked = True
        f['moniker_-1'] = "aqua"
        f['description_-1'] = "Dunkelaquamarin"
        self.submit(f)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        self.assertEqual("aqua", f['moniker_1001'].value)
        f['moniker_7'] = "rot"
        self.submit(f, check_notification=False)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        f['moniker_7'] = "gelb"
        f['moniker_8'] = "_bar_"
        self.submit(f, check_notification=False)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        f['moniker_8'] = "farbe"
        f['description_6'] = "lila"
        f['delete_7'].checked = True
        self.submit(f)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertEqual("rot", f['moniker_6'].value)
        self.assertEqual("lila", f['description_6'].value)
        self.assertEqual("farbe", f['moniker_8'].value)
        self.assertEqual("aqua", f['moniker_1001'].value)
        self.assertNotIn("gelb", f.fields)

    @as_users("werner")
    def test_has_voted(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'})

        self.assertPresence("Du nimmst nicht an der Versammlung teil.",
                            div='own-vote', exact=True)
        self.assertNonPresence("Du hast nicht abgestimmt.")

        self.traverse({'description': 'Archiv-Sammlung'})
        secret = self._signup()
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'})

        self.assertNonPresence("Du nimmst nicht an der Versammlung teil.")
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    @as_users("werner")
    def test_provide_secret(self, user):
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'})
        secret = self._signup()
        # Create new ballot.
        wait_time = 2
        future = now() + datetime.timedelta(seconds=wait_time)
        farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
        bdata = {
            'title': 'Maximale Länge der Verfassung',
            'vote_begin': future.isoformat(),
            'vote_end': farfuture.isoformat(),
            'quorum': "0",
            'votes': "1",
        }
        candidates = [
            {'moniker': 'ja', 'description': 'Ja'},
            {'moniker': 'nein', 'description': 'Nein'},
        ]
        self._create_ballot(bdata, candidates)

        # Wait for voting to start then cast own vote.
        time.sleep(wait_time)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': bdata['title']})
        f = self.response.forms["voteform"]
        f["vote"] = "ja"
        self.submit(f)

        # Check tally and own vote.
        time.sleep(wait_time)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': bdata['title']})
        self.assertPresence("Du hast für die folgenden Kandidaten gestimmt: Ja",
                            div='own-vote', exact=True)

        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'})
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

        # Conclude assembly.
        self.traverse({'description': 'Archiv-Sammlung'})
        self.assertTitle("Archiv-Sammlung")
        f = self.response.forms['concludeassemblyform']
        f['ack_conclude'].checked = True
        self.submit(f)

        # Own vote should be hidden now.
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Verfassung'})
        self.assertPresence("Die Versammlung wurde beendet und die "
                            "Stimmen sind nun verschlüsselt.")
        self.assertNonPresence(
            "Du hast für die folgenden Kandidaten gestimmt:")

        # Provide the secret to retrieve the vote.
        f = self.response.forms['showoldvoteform']
        f['secret'] = secret
        self.submit(f, check_notification=False)
        self.assertNonPresence("Die Versammlung wurde beendet und die "
                               "Stimmen sind nun verschlüsselt.")
        self.assertPresence("Du hast für die folgenden Kandidaten gestimmt: Ja",
                            div='own-vote', exact=True)

    def test_log(self):
        # First: generate data
        self.test_entity_ballot_simple()
        self.logout()
        self.test_conclude_assembly()
        # test_tally_and_get_result
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Antwort auf die letzte aller Fragen'},)
        self.logout()
        self.test_extend()
        self.logout()

        # Now check it
        self.login(USER_DICT['werner'])
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Log'})
        self.assertTitle("Versammlungs-Log [1–16 von 16]")
        f = self.response.forms['logshowform']
        codes = [const.AssemblyLogCodes.assembly_created.value,
                 const.AssemblyLogCodes.assembly_changed.value,
                 const.AssemblyLogCodes.ballot_created.value,
                 const.AssemblyLogCodes.ballot_changed.value,
                 const.AssemblyLogCodes.ballot_deleted.value,
                 const.AssemblyLogCodes.ballot_tallied.value]
        f['codes'] = codes
        f['assembly_id'] = 1
        self.submit(f)
        self.assertTitle("Versammlungs-Log [1–7 von 7]")

        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Drittes CdE-Konzil'},
                      {'description': 'Log'})
        self.assertTitle("Drittes CdE-Konzil: Log [1–7 von 7]")

        f = self.response.forms['logshowform']
        f['codes'] = codes
        f['offset'] = 2
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil: Log [3–52 von 5]")
