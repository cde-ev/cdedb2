#!/usr/bin/env python3

import datetime
import json
import re
import time
from typing import List

import webtest

import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, ADMIN_VIEWS_COOKIE_NAME, ASSEMBLY_BAR_SHORTNAME, now, NearlyNow
)
from cdedb.frontend.common import datetime_filter
from cdedb.query import QueryOperators
from cdedb.validation import parse_datetime
from tests.common import (
    FrontendTest, MultiAppFrontendTest, UserIdentifier, USER_DICT, as_users,
    get_user,
)


class AssemblyTestHelpers(FrontendTest):
    """This class contains only helpers and no tests."""

    # order ballot ids in some semantic categories
    BALLOT_TYPES = {
        'classical': {3, 4, 6, 7, 8, 9, 11, 12},
        'preferential': {1, 2, 5, 10, 13, 14, 15, 16}
    }
    BALLOT_STATES = {
        'edit': {2, 16},
        'voting': {3, 4, 5, 11, 12, 13, 14},
        'extended': {8, 15},
        'tallied': {1, 6, 7, 8, 9, 10},
    }
    BALLOTS_ARCHIVED = {7, 8, 9, 10}

    # a mixture of ballot ids representing every combination of type and state,
    # including archived
    CANONICAL_BALLOTS = {
        # TODO add classical ballot in edit state
        3,  # voting, classical
        8,  # extended, classical
        6,  # tallied, classical
        7,  # archived, classical
        2,  # edit, preferential
        5,  # voting, preferential
        15,  # extended, preferential
        1,  # tallied, preferential
        10,  # archived, preferential
    }

    def _create_assembly(self, adata: CdEDBObject = None,
                         delta: CdEDBObject = None) -> None:
        """Helper function to automatically create a new asembly.

        :param adata: This can be a full set of assembly data. If this is None
            sensible defaults will be used instead.
        :param delta: If given, modify the given (or default) data set before creation.
        """
        if not adata:
            adata = {
                'title': 'Drittes CdE-Konzil',
                'shortname': 'konzil3',
                'signup_end': "2222-4-1 00:00:00",
                'description': "Wir werden alle Häretiker exkommunizieren.",
                'notes': "Nur ein Aprilscherz",
                'presider_ids': "DB-23-X",
            }
        else:
            adata = adata.copy()
        if delta:
            adata.update(delta)
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Versammlung anlegen'})
        self.assertTitle("Versammlung anlegen")
        f = self.response.forms['createassemblyform']
        for k, v in adata.items():
            if isinstance(f[k], webtest.forms.Checkbox):
                f[k].checked = bool(v)
            else:
                f[k] = v
        self.submit(f)
        self.assertTitle(adata['title'])

    def _fetch_secret(self) -> str:
        content = self.fetch_mail_content()
        secret = content.split(
            "Versammlung lautet", 1)[1].split("ohne Leerzeichen.", 1)[0].strip()
        return secret

    def _signup(self) -> str:
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertNotIn('signupform', self.response.forms)
        return self._fetch_secret()

    def _external_signup(self, user: UserIdentifier) -> str:
        user = get_user(user)
        self.traverse({'description': 'Teilnehmer'})
        f = self.response.forms['addattendeeform']
        f['persona_id'] = user['DB-ID']
        self.submit(f)
        return self._fetch_secret()

    def _create_ballot(self, bdata: CdEDBObject, candidates: List[CdEDBObject] = None,
                       atitle: str = None) -> None:
        """Helper to create a new ballot.

        In order to use this you must have already navigated to somewhere inside the
        assembly to which the ballot will belong.

        :param atitle: The Title of the assembly. If given check the page title of the
            newly created ballot using the ballot's and the assembly's titles.
        """
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


class TestAssemblyFrontend(AssemblyTestHelpers):
    @as_users("werner", "berta", "kalif")
    def test_index(self, user: CdEDBObject) -> None:
        self.traverse({'href': '/assembly/'})
        self.assertPresence("Internationaler Kongress", div='active-assemblies')
        self.assertPresence("(bereits angemeldet)", div='active-assemblies')
        # Werner and Kalif can only see assemblies he is signed up to
        if user['id'] == USER_DICT["kalif"]['id']:
            self.assertNonPresence("Archiv-Sammlung")
        else:
            self.assertPresence("Archiv-Sammlung", div='active-assemblies')
        if user['id'] == USER_DICT["berta"]['id']:
            self.assertPresence("Kanonische Beispielversammlung",
                                div='inactive-assemblies')
        else:
            self.assertNonPresence("Kanonische Beispielversammlung")
        # Only Werner is presider
        if user['id'] == USER_DICT["werner"]['id']:
            self.assertPresence("Geleitete Versammlungen")
            self.assertPresence("Archiv-Sammlung", div='presided-assemblies')
            self.assertPresence("Internationaler Kongress", div='presided-assemblies')
            self.assertPresence("6 Teilnehmer")
            self.assertPresence("0 Teilnehmer")
        else:
            self.assertNonPresence("Geleitete Versammlungen")
            self.assertNonPresence("Teilnehmer")
        self.assertPresence("Inaktive Versammlungen")

    @as_users("annika", "martin", "vera", "werner", "anton")
    def test_sidebar(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'})
        everyone = ["Versammlungen", "Übersicht"]

        # not assembly admins
        if user['id'] in {USER_DICT["annika"]['id'], USER_DICT["martin"]['id'],
                          USER_DICT["werner"]['id']}:
            ins = everyone
            out = ["Nutzer verwalten", "Log"]
        # core admins
        elif user['id'] == USER_DICT["vera"]['id']:
            ins = everyone + ["Nutzer verwalten"]
            out = ["Log"]
        # assembly admins
        elif user['id'] == USER_DICT["anton"]['id']:
            ins = everyone + ["Nutzer verwalten", "Log"]
            out = []
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("kalif")
    def test_showuser(self, user: CdEDBObject) -> None:
        self.traverse({'description': user['display_name']})
        self.assertPresence("Versammlungen", div="has-realm")
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("kalif")
    def test_changeuser(self, user: CdEDBObject) -> None:
        self.traverse({'description': user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id(
                'displayname').text_content().strip())

    @as_users("ferdinand")
    def test_adminchangeuser(self, user: CdEDBObject) -> None:
        self.realm_admin_view_profile('kalif', 'assembly')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.assertNotIn('birthday', f.fields)
        self.submit(f)
        self.assertPresence("Zelda", div="personal-information")
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")

    @as_users("ferdinand")
    def test_toggleactivity(self, user: CdEDBObject) -> None:
        self.realm_admin_view_profile('kalif', 'assembly')
        self.assertPresence('Ja', div='account-active')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence('Nein', div='account-active')

    @as_users("ferdinand", "vera")
    def test_user_search(self, user: CdEDBObject) -> None:
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

    @as_users("ferdinand", "vera")
    def test_create_user(self, user: CdEDBObject) -> None:
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
    def test_assembly_admin_views(self, user: CdEDBObject) -> None:
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')

        self.traverse({'href': '/assembly/'})
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=False)

        # Test Assembly Administration Admin View
        self.assertNoLink('/assembly/log')
        self.traverse({'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/attendees'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/show'},
                      {'href': '/assembly/assembly/1/show'})
        self.assertNoLink('assembly/assembly/1/change')
        self.assertNoLink('assembly/assembly/1/log')
        self.assertNotIn('concludeassemblyform', self.response.forms)
        self._click_admin_view_button(re.compile(r"Versammlungs-Administration"),
                                      current_state=False)
        self.assertIn('concludeassemblyform', self.response.forms)
        self.assertNoLink('assembly/assembly/1/log')
        self.assertNoLink('assembly/assembly/1/change')

        # Test Presider Controls Admin View
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
        self.traverse({'href': '/assembly/assembly/1/attendees'})
        self.assertNotIn('addattendeeform', self.response.forms)
        self.assertNonPresence("TeX-Liste")

        self._click_admin_view_button(re.compile(r"Versammlungs-Administration"),
                                      current_state=True)
        self._click_admin_view_button(re.compile(r"Versammlungsleitung-Schaltflächen"),
                                      current_state=False)
        self.traverse({'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/attachment/add'},
                      {'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/log'},
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
        self.traverse({'href': '/assembly/assembly/1/attendees'})
        self.assertIn('addattendeeform', self.response.forms)
        self.assertPresence("TeX-Liste")

    @as_users("annika", "martin", "vera", "werner")
    def test_sidebar_one_assembly(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'})

        # they are no member and not yet signed up
        if user in [USER_DICT['annika'], USER_DICT['martin'], USER_DICT['vera']]:
            self.assertNonPresence("Internationaler Kongress")

            # now, sign them up
            self.logout()
            self.login(USER_DICT['werner'])
            self.traverse({'description': 'Versammlungen'},
                          {'description': 'Internationaler Kongress'})
            self._external_signup(user)
            self.logout()
            self.login(user)
            self.traverse({'description': 'Versammlungen'})

        self.traverse({'description': 'Internationaler Kongress'})
        attendee = ["Versammlungs-Übersicht", "Übersicht", "Teilnehmer",
                    "Abstimmungen", "Zusammenfassung", "Datei-Übersicht"]
        admin = ["Konfiguration", "Log"]

        # not assembly admins
        if user in [USER_DICT['annika'], USER_DICT['martin'], USER_DICT['vera']]:
            ins = attendee
            out = admin
        # assembly admin
        elif user == USER_DICT['werner']:
            ins = attendee + admin
            out = []
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("werner")
    def test_change_assembly(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        self.traverse({'description': 'Konfiguration'},)
        f = self.response.forms['changeassemblyform']
        f['title'] = 'Drittes CdE-Konzil'
        f['description'] = "Wir werden alle Häretiker exkommunizieren."
        f['presider_address'] = "drittes konzil@example.cde"
        self.submit(f, check_notification=False)
        self.assertValidationError('presider_address',
                                   "Muss eine valide E-Mail-Adresse sein.")
        f['presider_address'] = "Konzil@example.cde"
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertPresence("Häretiker", div='description')
        self.traverse({'description': 'Konfiguration'},)
        f = self.response.forms['changeassemblyform']
        self.assertEqual(f['presider_address'].value, 'konzil@example.cde')

    @as_users("werner")
    def test_past_assembly(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'},
                      {'description': 'Konfiguration'}, )
        f = self.response.forms['changeassemblyform']
        f['signup_end'] = '2000-02-22T01:00:00'
        self.submit(f)
        self.assertPresence("22.02.2000, 01:00:00")
        self.traverse({'description': 'Versammlungen'})
        self.assertNonPresence("22.02.2000, 01:00:00")
        self.assertPresence("(Anmeldung nicht mehr möglich)")

    # Use ferdinand since viktor is not a member and may not signup.
    @as_users("ferdinand")
    def test_create_delete_assembly(self, user: CdEDBObject) -> None:
        presider_address = "presider@lists.cde-ev.de"
        self._create_assembly(delta={'create_presider_list': True,
                                     'presider_address': presider_address})
        self.assertPresence("Häretiker", div='description')
        self.assertPresence("Aprilscherz", div='notes')
        self.assertPresence("Versammlungsleitungs-Mailingliste angelegt.",
                            div="notifications")
        self.assertPresence("Versammlungsleitungs-E-Mail-Adresse durch Adresse der"
                            " neuen Mailingliste ersetzt.", div="notifications")
        self.assertNotIn('createpresiderlistform', self.response.forms)
        f = self.response.forms['createattendeelistform']
        self.submit(f)
        self.assertPresence("Versammlungsteilnehmer-Mailingliste angelegt.",
                            div="notifications")
        self.traverse({'description': "Abstimmungen"})
        self.assertPresence("Es wurden noch keine Abstimmungen angelegt.")
        self.traverse({'description': r"\sÜbersicht"})
        # Make sure assemblies with attendees can be deleted
        f = self.response.forms['signupform']
        self.submit(f)
        f = self.response.forms['deleteassemblyform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Versammlungen")
        self.assertNonPresence("Drittes CdE-Konzil")

        self._create_assembly(delta={'presider_address': presider_address})
        self.traverse("Konfiguration")
        f = self.response.forms['changeassemblyform']
        self.assertEqual(f['presider_address'].value, presider_address)

    @as_users("charly")
    def test_signup(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("kalif")
    def test_no_signup(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'}, )
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("werner", "ferdinand")
    def test_external_signup(self, user: CdEDBObject) -> None:
        self.get("/assembly/assembly/3/show")
        self.traverse({'description': "Teilnehmer"})
        self.assertTitle("Anwesenheitsliste (Archiv-Sammlung)")
        self.assertNonPresence("Kalif", div='attendees-list')
        # Valid request
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-11-6"
        self.submit(f)
        self.assertTitle('Anwesenheitsliste (Archiv-Sammlung)')
        self.assertPresence("Kalif", div='attendees-list')
        # Archived user
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-8-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "persona_id", "Dieser Benutzer existiert nicht oder ist archiviert.")
        # Member
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-2-7"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "persona_id", "Mitglieder müssen sich selbst anmelden.")
        # Event user
        f = self.response.forms['addattendeeform']
        f['persona_id'] = "DB-5-1"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "persona_id", "Dieser Nutzer ist kein Versammlungsnutzer.")
        # TODO: add a check for a non-existant user and an invalid DB-ID.

    @as_users("werner", "viktor", "kalif")
    def test_list_attendees(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Teilnehmer'})
        self.assertTitle("Anwesenheitsliste (Internationaler Kongress)")
        attendees = ["Anton", "Akira", "Bertålotta", "Kalif", "Inga", "Werner"]
        for attendee in attendees:
            self.assertPresence(attendee, div='attendees-list')
        self.assertPresence(
            f"Insgesamt {len(attendees)} Anwesende.", div='attendees-count')
        self.assertNonPresence("Charly")
        if user['id'] in {USER_DICT['kalif']['id']}:
            self.assertNonPresence("Download")
        elif user['id'] in {USER_DICT['viktor']['id'], USER_DICT['werner']['id']}:
            self.assertPresence("Download")
            self.traverse("TeX-Liste")
            for attendee in attendees:
                self.assertIn(attendee, self.response.text)

    @as_users("rowena")
    def test_summary_ballots(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Kanonische Beispielversammlung'},
                      {'description': 'Zusammenfassung'})
        self.assertTitle("Zusammenfassung (Kanonische Beispielversammlung)")
        self.assertPresence("Entlastung des Vorstands")
        self.assertPresence("Wir kaufen den Eisenberg!")

    @as_users("ferdinand")
    def test_conclude_assembly(self, user: CdEDBObject) -> None:
        self._create_assembly()
        # werner is no member, so he must signup external
        secret = self._signup()
        self.traverse({'description': 'Konfiguration'})
        f = self.response.forms['changeassemblyform']
        f['signup_end'] = "2002-4-1 00:00:00"
        self.submit(f)

        wait_time = 0.5
        future = now() + datetime.timedelta(seconds=wait_time)
        farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
        bdata = {
            'title': 'Maximale Länge der Satzung',
            'description': "Dann muss man halt eine alte Regel rauswerfen,"
                           " wenn man eine neue will.",
            'vote_begin': future.isoformat(),
            'vote_end': farfuture.isoformat(),
            'abs_quorum': "0",
            'rel_quorum': "0",
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
        # Presiders can no longer be changed
        self.assertNotIn("addpresidersform", self.response.forms)
        self.assertNotIn("removepresiderform1", self.response.forms)

    @as_users("anton")
    def test_preferential_vote_result(self, user: CdEDBObject) -> None:
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        own_vote = ("Du hast mit der folgenden Präferenz abgestimmt:"
                    " 23 > 42 > Ablehnungsgrenze > Ich = Philosophie")
        self.assertPresence(own_vote, div='own-vote', exact=True)

    @as_users("garcia")
    def test_show_ballot_without_vote(self, user: CdEDBObject) -> None:
        self.get('/assembly/assembly/1/show')
        f = self.response.forms['signupform']
        self.submit(f)
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    @as_users("berta")
    def test_show_ballot_status(self, user: CdEDBObject) -> None:
        ballots = self.get_sample_data(
            'assembly.ballots', self.CANONICAL_BALLOTS,
            ('vote_begin', 'vote_end', 'assembly_id', 'title', 'abs_quorum',
             'vote_extension_end'))
        assemblies = self.get_sample_data(
            'assembly.assemblies', set(b['assembly_id'] for b in ballots.values()),
            ('title', 'id'))
        for ballot_id, ballot in ballots.items():
            with self.subTest(ballot=ballot_id):
                assembly = assemblies[ballot['assembly_id']]
                self.get(f"/assembly/assembly/{assembly['id']}/ballot/{ballot_id}/show")
                # redirect in case of tallying, extending etc
                self.follow()
                self.assertTitle(f"{ballot['title']} ({assembly['title']})")

                # Check display of regular voting period.
                raw = self.get_content('regular-voting-period').strip()
                date_pattern = r"\d{2}\.\d{2}\.\d{3,4}"
                time_pattern = r"\d{2}:\d{2}:\d{2}"
                pattern = re.compile(f"(?P<start_date>{date_pattern})"
                                     f", (?P<start_time>{time_pattern})"
                                     f" bis (?P<end_date>{date_pattern})"
                                     f", (?P<end_time>{time_pattern})")
                result = re.search(pattern, raw)
                assert result is not None
                self.assertEqual(
                    parse_datetime(f"{result.group('start_date')}"
                                   f" {result.group('start_time')}"),
                    NearlyNow.from_datetime(ballot['vote_begin']))
                self.assertEqual(
                    parse_datetime(f"{result.group('end_date')}"
                                   f" {result.group('end_time')}"),
                    NearlyNow.from_datetime(ballot['vote_end']))

                # Check display of extension time.
                if ballot_id in self.BALLOT_STATES['extended']:
                    date_str = datetime_filter(ballot['vote_extension_end'], lang='de')
                    self.assertPresence(
                        f"Wurde bis {date_str} verlängert, da"
                        f" {ballot['abs_quorum']} Stimmen nicht erreicht wurden.",
                        div='extension-period')

                msg = "Diese Abstimmung hat noch nicht begonnen."
                if ballot_id in self.BALLOT_STATES['edit']:
                    self.assertPresence(msg, div='ballot-status')
                else:
                    self.assertNonPresence(msg, div='ballot-status')
                if (ballot_id in self.BALLOT_STATES['voting']
                        or ballot_id in self.BALLOT_STATES['extended']
                        and ballot_id not in self.BALLOT_STATES['tallied']):
                    self.assertPresence("Die Abstimmung läuft.", div='ballot-status')
                else:
                    self.assertNonPresence("Die Abstimmung läuft.", div='ballot-status')

    @as_users("garcia")
    def test_show_ballot_without_attendance(self, user: CdEDBObject) -> None:
        self.get('/assembly/assembly/1/ballot/1/show')
        self.follow()  # Redirect because ballot has not been tallied yet.
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        self.assertPresence("Du nimmst nicht an der Versammlung teil.",
                            div='own-vote', exact=True)

    @as_users("werner")
    def test_entity_ballot_simple(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen$'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},)
        self.assertTitle("Abstimmungen (Internationaler Kongress)")
        self.assertNonPresence("Maximale Länge der Satzung")
        self.assertNonPresence("Es wurden noch keine Abstimmungen angelegt")
        bdata = {
            'title': 'Maximale Länge der Satzung',
            'description': "Dann muss man halt eine alte Regel rauswerfen,"
                           " wenn man eine neue will.",
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
        # votes must be empty or a positive int
        self.traverse({'description': 'Bearbeiten'}, )
        f = self.response.forms['changeballotform']
        f['votes'] = 0
        self.submit(f, check_notification=False)
        self.assertValidationError('votes', message="Muss positiv sein.")
        f['votes'] = 1
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.traverse({'description': 'Bearbeiten'},)
        f = self.response.forms['changeballotform']
        self.assertEqual("April, April!", f['notes'].value)
        self.traverse({'description': 'Abstimmungen'},)
        self.assertTitle("Abstimmungen (Internationaler Kongress)")
        self.assertPresence("Maximale Länge der Satzung")
        self.traverse({'description': 'Maximale Länge der Satzung'},)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.traverse({'description': 'Abstimmungen'},)
        self.assertTitle("Abstimmungen (Internationaler Kongress)")
        self.assertNonPresence("Maximale Länge der Satzung")

    @as_users("werner")
    def test_delete_ballot(self, user: CdEDBObject) -> None:
        self.get("/assembly/assembly/1/ballot/2/show")
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertPresence("Diese Abstimmung hat noch nicht begonnen.",
                            div='status')
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Abstimmungen (Internationaler Kongress)")
        self.assertNonPresence("Farbe des Logos")
        self.assertNonPresence("Zukünftige Abstimmungen")
        self.traverse({"description": "Lieblingszahl"})
        self.assertTitle("Lieblingszahl (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung läuft.", div='status')
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)
        self.get("/assembly/assembly/1/ballot/list")
        self.traverse({"description": "Antwort auf die letzte aller Fragen"})
        self.assertTitle(
            "Antwort auf die letzte aller Fragen (Internationaler Kongress)")
        self.assertPresence("Die Abstimmung ist beendet.", div='status')
        self.assertNonPresence("Löschen")
        self.assertNotIn("deleteballotform", self.response.forms)

    @as_users("werner", "ferdinand")
    def test_attachments(self, user: CdEDBObject) -> None:
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()
        self.traverse({'description': 'Versammlungen$'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Datei-Übersicht'})
        if user['id'] in {6}:
            f = self.response.forms['adminviewstoggleform']
            self.submit(f, button="view_specifier", value="-assembly_presider")
            self.assertTitle("Datei-Übersicht (Internationaler Kongress)")
            self.assertPresence("Es wurden noch keine Dateien hochgeladen.")
            f = self.response.forms['adminviewstoggleform']
            self.submit(f, button="view_specifier", value="+assembly_presider")
        self.traverse({'description': r"\sÜbersicht"},
                      {'description': "Datei hinzufügen"})
        self.assertTitle("Datei hinzufügen (Internationaler Kongress)")

        # First try upload with invalid default filename
        f = self.response.forms['addattachmentform']
        f['title'] = "Maßgebliche Beschlussvorlage"
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "filename", "Darf nur aus druckbaren ASCII-Zeichen bestehen")
        # Now, add an correct override filename
        f = self.response.forms['addattachmentform']
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        f['filename'] = "beschluss.pdf"
        self.submit(f)
        self.assertTitle(
            "Datei-Details (Internationaler Kongress) – Maßgebliche Beschlussvorlage")

        # Check file content.
        saved_response = self.response
        self.traverse({'description': 'Maßgebliche Beschlussvorlage'},)
        self.assertEqual(data, self.response.body)
        self.response = saved_response

        # Change version data.
        self.traverse({'href': '/assembly/assembly/1/attachment/1001/version/1/edit'})
        self.assertTitle("Version bearbeiten (Internationaler Kongress)"
                         " – Maßgebliche Beschlussvorlage (Version 1)")
        f = self.response.forms['editattachmentversionform']
        f['title'] = "Insignifikante Beschlussvorlage"
        f['authors'] = "Der Vorstand"
        self.submit(f)
        self.assertTitle("Datei-Details (Internationaler Kongress)"
                         " – Insignifikante Beschlussvorlage")
        self.traverse({'description': 'Datei-Verknüpfung ändern'})
        self.assertTitle("Datei-Verknüpfung ändern (Internationaler Kongress)"
                         " – Insignifikante Beschlussvorlage")
        f = self.response.forms['changeattachmentlinkform']
        f['new_ballot_id'] = 2
        self.submit(f)
        self.assertTitle("Datei-Details (Internationaler Kongress/Farbe des Logos)"
                         " – Insignifikante Beschlussvorlage")
        self.traverse({'description': 'Version hinzufügen'})
        self.assertTitle("Version hinzufügen (Internationaler Kongress/Farbe des Logos)"
                         " – Insignifikante Beschlussvorlage")
        f = self.response.forms['addattachmentform']
        f['title'] = "Alternative Beschlussvorlage"
        f['authors'] = "Die Wahlleitung"
        f['attachment'] = webtest.Upload("beschluss2.pdf", data + b'123',
                                         "application/octet-stream")
        self.submit(f)
        self.assertTitle("Datei-Details (Internationaler Kongress/Farbe des Logos)"
                         " – Alternative Beschlussvorlage")
        self.assertPresence("Insignifikante Beschlussvorlage (Version 1)")
        self.assertPresence("Alternative Beschlussvorlage (Version 2)")
        f = self.response.forms['removeattachmentversionform1001_1']
        f['attachment_ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Datei-Details (Internationaler Kongress/Farbe des Logos)"
                         " – Alternative Beschlussvorlage")
        self.assertPresence("Version 1 wurde gelöscht")

        # Now check the attachment over view without the presider admin view.
        self.traverse({'description': "Datei-Übersicht"})
        if user['id'] in {6}:
            f = self.response.forms['adminviewstoggleform']
            self.submit(f, button="view_specifier", value="-assembly_presider")
            self.assertTitle("Datei-Übersicht (Internationaler Kongress)")
            self.assertPresence("Alternative Beschlussvorlage (Version 2)")
            self.assertPresence("Version 1 wurde gelöscht.")
            self.assertNonPresence("Es wurden noch keine Dateien hochgeladen.")
            f = self.response.forms['adminviewstoggleform']
            self.submit(f, button="view_specifier", value="+assembly_presider")
        f = self.response.forms['deleteattachmentform1001']
        f['attachment_ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")

    @as_users("werner", "inga", "kalif")
    def test_preferential_vote(self, user: CdEDBObject) -> None:
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
    def test_classical_vote_radio(self, user: CdEDBObject) -> None:
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
        f['vote'] = ASSEMBLY_BAR_SHORTNAME
        self.submit(f)
        self.assertTitle("Bester Hof (Internationaler Kongress)")
        self.assertEqual(ASSEMBLY_BAR_SHORTNAME, f['vote'].value)
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
    def test_classical_vote_select(self, user: CdEDBObject) -> None:
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
        f['vote'] = [ASSEMBLY_BAR_SHORTNAME]
        self.submit(f)
        self.assertTitle("Akademie-Nachtisch (Internationaler Kongress)")
        f = self.response.forms['voteform']
        self.assertEqual(ASSEMBLY_BAR_SHORTNAME, f.get('vote', index=5).value)
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
    def test_classical_voting_all_choices(self, user: CdEDBObject) -> None:
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
                wait_time = 3
                future = now() + datetime.timedelta(seconds=wait_time)
                farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
                bdata = {
                    'title': 'Wahl zum Finanzvorstand -- {} bar'
                             .format("w." if use_bar else "w/o"),
                    'vote_begin': future.isoformat(),
                    'vote_end': farfuture.isoformat(),
                    'abs_quorum': "0",
                    'rel_quorum': "0",
                    'votes': "2",
                    'use_bar': use_bar,
                }
                candidates = [
                    {'shortname': 'arthur', 'title': 'Arthur Dent'},
                    {'shortname': 'ford', 'title': 'Ford Prefect'},
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
                    f["vote"] = [ASSEMBLY_BAR_SHORTNAME]
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
                              {'description': bdata['title']},
                              {'description': 'Ergebnisdetails'})
                self.assertPresence("Du hast für die folgenden Kandidaten "
                                    "gestimmt: Arthur Dent = Ford Prefect",
                                    div='own-vote', exact=True)

    @as_users("werner", "inga", "kalif")
    def test_tally_and_get_result(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},)
        self.assertTitle("Abstimmungen (Internationaler Kongress)")
        text = self.fetch_mail_content()
        self.assertIn('"Antwort auf die letzte aller Fragen"', text)
        self.assertIn('"Internationaler Kongress"', text)
        self.traverse({'description': 'Antwort auf die letzte aller Fragen'},
                      {'description': 'Ergebnisdetails'},
                      {'description': 'Ergebnisdatei herunterladen'},)
        with open("/tmp/cdedb-store/testfiles/ballot_result.json", 'rb') as f:
            self.assertEqual(json.load(f), json.loads(self.response.body))

    @as_users("anton")
    def test_ballot_result_page(self, user: CdEDBObject) -> None:
        for ballot_id in self.CANONICAL_BALLOTS:
            ballot = self.sample_data['assembly.ballots'][ballot_id]
            assembly = self.sample_data['assembly.assemblies'][ballot['assembly_id']]
            self.get(f'/assembly/assembly/{assembly["id"]}/ballot/{ballot_id}/result')
            # redirect in case of tallying, extending etc
            self.follow()

            # redirect to show_ballot if the ballot has not been tallied yet
            if ballot_id in self.BALLOT_STATES['tallied']:
                self.assertTitle(f"Ergebnis ({assembly['title']}/{ballot['title']})")
            else:
                self.assertTitle(f"{ballot['title']} ({assembly['title']})")
                self.assertPresence("Abstimmung wurde noch nicht ausgezählt.",
                                    div='notifications')
                continue

            save = self.response

            # check the download result file
            self.traverse({'description': 'Ergebnisdatei herunterladen'})
            self.assertPresence(f'"assembly": "{assembly["title"]}",')
            # self.assertPresence(f'"ballot": "{ballot["title"]}",')
            self.assertPresence('"result": ')
            self.assertPresence('"candidates": ')
            self.assertPresence('"use_bar": ')
            self.assertPresence('"voters": ')
            self.assertPresence('"votes": ')

            # check if the verification scripts are present
            # TODO expose the static files in our test suite
            # self.response = save
            # self.traverse({'description': 'Download Result Verification Script'})
            # self.assertPresence("Skript um die Auszählung in Ergebnisdateien"
            #                     " von Wahlen zu verifizieren.")
            # self.response = save
            # self.traverse({'description': 'Download Own Vote Verification Script'})
            # self.assertPresence("Skript um Stimmen in Ergebnisdateien"
            #                     " von Wahlen zu verifizieren.")

            self.response = save

            # check pagination
            if ballot_id == 7:
                self.traverse({'description': 'Vorherige'})
                self.assertTitle("Ergebnis (Kanonische Beispielversammlung"
                                 "/Eine damals wichtige Frage)")
                self.response = save
                self.traverse({'description': 'Nächste'})
                self.assertTitle("Ergebnis (Kanonische Beispielversammlung"
                                 "/Wahl des Finanzvorstands)")
            elif ballot_id == 10:
                self.traverse({'description': 'Vorherige'})
                self.assertTitle("Ergebnis (Kanonische Beispielversammlung"
                                 "/Wahl des Finanzvorstands)")
                self.response = save
                self.assertNonPresence("Nächste")
            elif ballot_id == 1:
                # we dont have links to traverse to neighbour ballots, since no other
                # is tallied
                self.assertNonPresence("Vorherige")
                self.assertNonPresence("Nächste")

            self.response = save

    @as_users("anton")
    def test_ballot_result_page_extended(self, user: CdEDBObject) -> None:
        # classical vote with bar
        self.traverse({'description': 'Versammlung'},
                      {'description': 'Kanonische Beispielversammlung'},
                      {'description': 'Zusammenfassung'},
                      {'description': 'Eine damals wichtige Frage'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/Eine damals wichtige Frage)")

        # test if the overall result is displayed correctly
        result = "CdE Wappen > CdE Glühbirne = Baum & Blätter = Gegen alle Kandidaten"
        self.assertPresence(result, div='combined-preference', exact=True)

        # test if the sorting of the single votes is correct
        self.assertPresence("CdE Wappen 3", div='vote-1', exact=True)
        self.assertPresence("CdE Glühbirne 1 ", div='vote-2', exact=True)
        self.assertPresence("Baum & Blätter 1", div='vote-3', exact=True)
        self.assertPresence("Gegen alle Kandidaten 1", div='vote-4', exact=True)
        self.assertNonPresence("", div='vote-5', check_div=False)

        # test the list of all voters
        self.assertPresence("Anton Armin A. Administrator", div='voters-list')
        self.assertPresence("Rowena Ravenclaw", div='voters-list')
        self.assertNonPresence("Vera", div='voters-list')


        # classical vote without bar
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Entlastung des Vorstands'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/Entlastung des Vorstands)")

        # test if the overall result is displayed correctly
        result = "Ja > Nein"
        self.assertPresence(result, div='combined-preference', exact=True)

        # test if abstentions are rendered correctly
        self.assertPresence("Enthalten 1", div='vote-3', exact=True)


        # preferential vote without bar
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Wie soll der CdE mit seinem Vermögen umgehen?'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/Wie soll der CdE mit seinem Vermögen umgehen?)")

        # test if the overall result is displayed correctly
        result = "Wir kaufen den Eisenberg! = Kostenlose Akademien für alle. > Investieren in Aktien und Fonds."
        self.assertPresence(result, div='combined-preference', exact=True)

        # test a vote string
        vote = "Kostenlose Akademien für alle. > Investieren in Aktien und Fonds. = Wir kaufen den Eisenberg! 3"
        self.assertPresence(vote, div='vote-1', exact=True)


        # preferential vote with bar
        self.traverse({'description': 'Versammlung'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Antwort auf die letzte aller Fragen'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle(
            "Ergebnis (Internationaler Kongress/Antwort auf die letzte aller Fragen)")

        # test if the overall result is displayed correctly
        result = "42 > 23 = Philosophie > Ablehnungsgrenze > Ich"
        self.assertPresence(result, div='combined-preference', exact=True)

        # test a vote string
        self.assertPresence("42 > 23 = Philosophie > Ablehnungsgrenze > Ich 1",
                            div='vote-1', exact=True)


    @as_users("werner")
    def test_extend(self, user: CdEDBObject) -> None:
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
        f['abs_quorum'] = "0"
        f['rel_quorum'] = "100"
        f['votes'] = ""
        self.submit(f)
        self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
        self.assertPresence(
            "Verlängerung bis 01.05.2222, 00:00:00, falls 11 Stimmen nicht "
            "erreicht werden.", div='voting-period')
        time.sleep(1)
        self.traverse({'href': '/assembly/1/ballot/list'},
                      {'description': 'Maximale Länge der Verfassung'},)
        self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
        s = ("Wurde bis 01.05.2222, 00:00:00 verlängert, da 11 Stimmen nicht "
             "erreicht wurden.")
        self.assertPresence(s, div='voting-period')

    @as_users("werner")
    def test_candidate_manipulation(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Farbe des Logos'},)
        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        self.assertEqual("rot", f['shortname_6'].value)
        self.assertEqual("gelb", f['shortname_7'].value)
        self.assertEqual("gruen", f['shortname_8'].value)
        self.assertNotIn("Dunkelaquamarin", f.fields)
        f['create_-1'].checked = True
        f['shortname_-1'] = "aqua"
        f['title_-1'] = "Dunkelaquamarin"
        self.submit(f)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        self.assertEqual("aqua", f['shortname_1001'].value)
        f['shortname_7'] = "rot"
        self.submit(f, check_notification=False)
        self.assertValidationError("shortname_7", "Option doppelt gefunden")

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        f['shortname_7'] = "gelb"
        f['shortname_8'] = "_bar_"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "shortname_8", "Darf nicht der Bezeichner der Ablehnungsoption sein")

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        f = self.response.forms['candidatessummaryform']
        f['shortname_8'] = "farbe"
        f['title_6'] = "lila"
        f['delete_7'].checked = True
        self.submit(f)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertEqual("rot", f['shortname_6'].value)
        self.assertEqual("lila", f['title_6'].value)
        self.assertEqual("farbe", f['shortname_8'].value)
        self.assertEqual("aqua", f['shortname_1001'].value)
        self.assertNotIn("gelb", f.fields)

    @as_users("werner")
    def test_has_voted(self, user: CdEDBObject) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'},
                      {'description': 'Ergebnisdetails'})

        self.assertPresence("Du nimmst nicht an der Versammlung teil.",
                            div='own-vote', exact=True)
        self.assertNonPresence("Du hast nicht abgestimmt.")

        self.traverse({'description': 'Archiv-Sammlung'})
        # werner is no member, so he must signup external
        secret = self._external_signup(user)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'},
                      {'description': 'Ergebnisdetails'})

        self.assertNonPresence("Du nimmst nicht an der Versammlung teil.")
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    def test_provide_secret(self) -> None:
        user = USER_DICT["werner"]
        self.login(user)
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'})
        # werner is no member, so he must signup external
        secret = self._external_signup(user)
        # Create new ballot.
        wait_time = 2
        future = now() + datetime.timedelta(seconds=wait_time)
        farfuture = now() + datetime.timedelta(seconds=2 * wait_time)
        bdata = {
            'title': 'Maximale Länge der Verfassung',
            'vote_begin': future.isoformat(),
            'vote_end': farfuture.isoformat(),
            'abs_quorum': "0",
            'rel_quorum': "0",
            'votes': "1",
        }
        candidates = [
            {'shortname': 'ja', 'title': 'Ja'},
            {'shortname': 'nein', 'title': 'Nein'},
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
                      {'description': bdata['title']},
                      {'description': 'Ergebnisdetails'})
        self.assertPresence("Du hast für die folgenden Kandidaten gestimmt: Ja",
                            div='own-vote', exact=True)

        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'},
                      {'description': 'Ergebnisdetails'})
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Ganz wichtige Wahl'})
        f = self.response.forms['deleteballotform']
        f['ack_delete'].checked = True
        self.submit(f)

        self.logout()
        self.login("anton")
        # Conclude assembly.
        self.traverse({'description': "Versammlung"},
                      {'description': "Archiv-Sammlung"})
        self.assertTitle("Archiv-Sammlung")
        f = self.response.forms['concludeassemblyform']
        f['ack_conclude'].checked = True
        self.submit(f)

        self.logout()
        self.login(user)
        # Own vote should be hidden now.
        self.traverse({'description': "Versammlung"},
                      {'description': 'Archiv-Sammlung'},
                      {'description': 'Abstimmungen'},
                      {'description': 'Maximale Länge der Verfassung'},
                      {'description': 'Ergebnisdetails'})
        s = ("Die Versammlung wurde beendet. Das Abstimmungsverhalten einzelner"
             " Nutzer ist nicht mehr aus der Datenbank auslesbar.")
        self.assertPresence(s)
        self.assertNonPresence("Du hast für die folgenden Kandidaten gestimmt:")

        # Provide the secret to retrieve the vote.
        f = self.response.forms['showoldvoteform']
        f['secret'] = secret
        self.submit(f, check_notification=False)
        self.assertNonPresence("Die Versammlung wurde beendet und die "
                               "Stimmen sind nun verschlüsselt.")
        self.assertPresence("Du hast für die folgenden Kandidaten gestimmt: Ja",
                            div='own-vote', exact=True)

    def test_log(self) -> None:
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
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Log'})
        self.assertTitle("Versammlungs-Log [1–26 von 26]")
        self.assertNonPresence("LogCodes")
        f = self.response.forms['logshowform']
        codes = [const.AssemblyLogCodes.assembly_created.value,
                 const.AssemblyLogCodes.assembly_changed.value,
                 const.AssemblyLogCodes.ballot_created.value,
                 const.AssemblyLogCodes.ballot_changed.value,
                 const.AssemblyLogCodes.ballot_deleted.value,
                 const.AssemblyLogCodes.ballot_tallied.value,
                 const.AssemblyLogCodes.assembly_presider_added.value,
                 ]
        f['codes'] = codes
        f['assembly_id'] = 1
        self.submit(f)
        self.assertTitle("Versammlungs-Log [1–8 von 8]")

        self.logout()
        self.login("werner")
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Drittes CdE-Konzil'},
                      {'description': 'Log'})
        self.assertTitle("Drittes CdE-Konzil: Log [1–8 von 8]")

        f = self.response.forms['logshowform']
        f['codes'] = codes
        f['offset'] = 2
        self.submit(f)
        self.assertTitle("Drittes CdE-Konzil: Log [3–52 von 6]")


class TestMultiAssemblyFrontend(MultiAppFrontendTest, AssemblyTestHelpers):
    n = 2

    def test_presiders(self) -> None:
        self.login("anton")
        self._create_assembly()
        self._external_signup(USER_DICT["werner"])
        self.traverse(r"\sÜbersicht")
        self.assertPresence("Werner Wahlleitung", div='assembly-presiders')
        self.switch_app(1)
        self.login("werner")
        self.traverse("Versammlung", "Drittes CdE-Konzil", "Konfiguration")
        f = self.response.forms['changeassemblyform']
        f['notes'] = "Werner war hier!"
        self.submit(f, verbose=True)
        self.assertTitle("Drittes CdE-Konzil")
        self.assertPresence("Werner war hier!", div='notes')
        self.assertNotIn('removepresiderform23', self.response.forms)
        self.traverse("Log")
        self.switch_app(0)
        self.traverse(r"\sÜbersicht")
        self.assertPresence("Werner war hier!", div='notes')
        f = self.response.forms['removepresiderform23']
        self.submit(f, verbose=True)
        self.assertNonPresence("Werner Wahlleitung", div='assembly-presiders',
                               check_div=False)
        self.switch_app(1)
        self.traverse(r"\sÜbersicht")
        self.assertNonPresence("Werner war hier!")
        self.assertNoLink("Konfiguration")
        self.assertNoLink("Log")
        self.switch_app(0)
        f = self.response.forms['addpresidersform']
        # Try non-existing user.
        f['presider_ids'] = "DB-1000-6"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "presider_ids",
            "Einige dieser Nutzer existieren nicht oder sind archiviert.")
        # Try archived user.
        f['presider_ids'] = USER_DICT["hades"]['DB-ID']
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "presider_ids",
            "Einige dieser Nutzer existieren nicht oder sind archiviert.")
        # Try non-assembly user.
        f['presider_ids'] = USER_DICT["emilia"]['DB-ID']
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "presider_ids",
            "Einige dieser Nutzer sind keine Versammlungsnutzer.")
        # Proceed with a valid user.
        f['presider_ids'] = USER_DICT["werner"]['DB-ID']
        self.submit(f)
        self.assertPresence("Werner Wahlleitung", div='assembly-presiders')
        self.switch_app(1)
        self.traverse(r"\sÜbersicht")
        self.assertPresence("Werner war hier!", div='notes')
        self.traverse("Konfiguration", "Log")
