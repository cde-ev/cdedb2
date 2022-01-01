#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import json
import re
from typing import List

import freezegun
import webtest

from cdedb.common import (
    ADMIN_VIEWS_COOKIE_NAME, ASSEMBLY_BAR_SHORTNAME, CdEDBObject, NearlyNow, now,
)
from cdedb.frontend.common import datetime_filter
from cdedb.query import QueryOperators
from cdedb.validation import parse_datetime
from tests.common import (
    USER_DICT, FrontendTest, MultiAppFrontendTest, UserIdentifier, as_users, get_user,
    storage,
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
        f = self.response.forms['configureassemblyform']
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
        f = self.response.forms["configureballotform"]
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
    def test_index(self) -> None:
        self.traverse({'href': '/assembly/'})
        self.assertPresence("Internationaler Kongress", div='active-assemblies')
        self.assertPresence("(bereits angemeldet)", div='active-assemblies')
        # Werner and Kalif can only see assemblies he is signed up to
        if self.user_in("kalif"):
            self.assertNonPresence("Archiv-Sammlung")
        else:
            self.assertPresence("Archiv-Sammlung", div='active-assemblies')
        if self.user_in("berta"):
            self.assertPresence("Kanonische Beispielversammlung",
                                div='inactive-assemblies')
        else:
            self.assertNonPresence("Kanonische Beispielversammlung")
        # Only Werner is presider
        if self.user_in("werner"):
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
    def test_sidebar(self) -> None:
        self.traverse({'description': 'Versammlungen'})
        everyone = {"Versammlungen", "Übersicht"}

        # not assembly admins
        if self.user_in("annika", "martin", "werner"):
            ins = everyone
            out = {"Nutzer verwalten", "Archivsuche", "Log"}
        # core admins
        elif self.user_in("vera"):
            ins = everyone | {"Nutzer verwalten", "Archivsuche"}
            out = {"Log"}
        # assembly admins
        elif self.user_in("anton"):
            ins = everyone | {"Nutzer verwalten", "Archivsuche", "Log"}
            out = set()
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("kalif")
    def test_showuser(self) -> None:
        self.traverse({'description': self.user['display_name']})
        self.assertPresence("Versammlungen", div="has-realm")
        self.assertTitle(self.user['default_name_format'])

    @as_users("kalif")
    def test_changeuser(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id(
                'displayname').text_content().strip())

    @as_users("ferdinand")
    def test_adminchangeuser(self) -> None:
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
    def test_toggleactivity(self) -> None:
        self.realm_admin_view_profile('kalif', 'assembly')
        self.assertPresence('Ja', div='account-active')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence('Nein', div='account-active')

    @as_users("paul", "viktor")
    def test_user_search(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Nutzer verwalten'})
        self.assertTitle("Versammlungsnutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'f@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Versammlungsnutzerverwaltung")
        self.assertPresence("Ergebnis [1]", div="query-results")
        self.assertPresence("Karabatschi", div="result-container")

    @as_users("paul", "viktor")
    def test_create_archive_user(self) -> None:
        self.check_create_archive_user('assembly')

    @storage
    @as_users("anton")
    def test_assembly_admin_views(self) -> None:
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
        self.traverse({'href': '/assembly/assembly/1/ballot/list'})
        self.assertNoLink('/assembly/assembly/1/ballot/2/change')
        self.assertNoLink('/assembly/assembly/1/ballot/create')
        self.traverse({'href': '/assembly/assembly/1/ballot/2/show'})
        self.assertNoLink('/assembly/assembly/1/ballot/2/change')
        self.assertNotIn('removecandidateform6', self.response.forms)
        self.assertNotIn('addcandidateform', self.response.forms)
        self.assertNotIn('deleteballotform', self.response.forms)
        self.traverse({'href': '/assembly/assembly/1/attendees'})
        self.assertNotIn('addattendeeform', self.response.forms)
        self.assertNonPresence("TeX-Liste")

        # check attachments in Archiv-Versammlung
        self.traverse("Versammlungs-Übersicht", "Archiv-Sammlung", "Dateien")
        self.assertNotIn('deleteattachmentform1', self.response.forms)
        self.assertNotIn('removeattachmentversionform2_3', self.response.forms)
        self.assertNoLink('/assembly/assembly/3/attachment/add')
        self.assertNoLink('/assembly/assembly/3/attachment/1/add')

        self._click_admin_view_button(re.compile(r"Versammlungs-Administration"),
                                      current_state=True)
        self._click_admin_view_button(re.compile(r"Versammlungsleitung-Schaltflächen"),
                                      current_state=False)

        self.traverse("Versammlungs-Übersicht", "Archiv-Sammlung", "Dateien")
        self.assertIn('deleteattachmentform1', self.response.forms)
        self.assertIn('removeattachmentversionform2_3', self.response.forms)
        self.traverse({'href': '/assembly/assembly/3/attachment/add'},
                      {'href': '/assembly/assembly/3/attachments'},
                      {'href': '/assembly/assembly/3/attachment/1/add'})

        # go back to Internationaler Kongress
        self.traverse("Versammlungs-Übersicht", "Internationaler Kongress")
        self.traverse({'href': '/assembly/assembly/1/show'},
                      {'href': '/assembly/assembly/1/log'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/change'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/create'},
                      {'href': '/assembly/assembly/1/ballot/list'},
                      {'href': '/assembly/assembly/1/ballot/2/show'})
        self.assertIn('candidatessummaryform', self.response.forms)
        self.assertIn('deleteballotform', self.response.forms)
        self.traverse({'href': '/assembly/assembly/1/attendees'})
        self.assertIn('addattendeeform', self.response.forms)
        self.assertPresence("TeX-Liste")

    @as_users("annika", "martin", "vera", "werner")
    def test_sidebar_one_assembly(self) -> None:
        user = self.user
        self.traverse({'description': 'Versammlungen'})

        # they are no member and not yet signed up
        if self.user_in('annika', 'martin', 'vera'):
            self.assertNonPresence("Internationaler Kongress")

            # now, sign them up
            with self.switch_user('werner'):
                self.traverse({'description': 'Versammlungen'},
                              {'description': 'Internationaler Kongress'})
                self._external_signup(user)
            self.traverse({'description': 'Versammlungen'})

        self.traverse({'description': 'Internationaler Kongress'})
        attendee = {"Versammlungs-Übersicht", "Übersicht", "Teilnehmer",
                    "Abstimmungen", "Zusammenfassung", "Dateien"}
        admin = {"Konfiguration", "Log"}

        # not assembly admins
        if self.user_in('annika', 'martin', 'vera'):
            ins = attendee
            out = admin
        # assembly admin
        elif self.user_in('werner'):
            ins = attendee | admin
            out = set()
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("werner")
    def test_change_assembly(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        self.traverse({'description': 'Konfiguration'},)
        f = self.response.forms['configureassemblyform']
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
        f = self.response.forms['configureassemblyform']
        self.assertEqual(f['presider_address'].value, 'konzil@example.cde')

    @as_users("werner")
    def test_past_assembly(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Archiv-Sammlung'},
                      {'description': 'Konfiguration'}, )
        f = self.response.forms['configureassemblyform']
        f['signup_end'] = '2000-02-22T01:00:00'
        self.submit(f)
        self.assertPresence("22.02.2000, 01:00:00")
        self.traverse({'description': 'Versammlungen'})
        self.assertNonPresence("22.02.2000, 01:00:00")
        self.assertPresence("(Anmeldung nicht mehr möglich)")

    # Use ferdinand since viktor is not a member and may not signup.
    @storage
    @as_users("ferdinand")
    def test_create_delete_assembly(self) -> None:
        presider_address = "presider@lists.cde-ev.de"
        with open(self.testfile_dir / "form.pdf", 'rb') as datafile:
            attachment = datafile.read()
        bdata = {
            'title': 'Müssen wir wirklich regeln...',
            'vote_begin': "2222-12-12 00:00:00",
            'vote_end': "2223-5-1 00:00:00",
            'abs_quorum': "0",
            'rel_quorum': "0",
            'votes': "",
        }

        self._create_assembly(delta={'create_presider_list': True,
                                     'presider_address': presider_address})
        self.assertPresence("Häretiker", div='description')
        self.assertPresence("Aprilscherz", div='notes')
        self.assertPresence("Versammlungsleitungs-Mailingliste angelegt.",
                            div="notifications")
        self.assertPresence("Versammlungsleitungs-E-Mail-Adresse durch Adresse der"
                            " neuen Mailingliste ersetzt.", div="notifications")
        self.assertNotIn('createpresiderlistform', self.response.forms)
        # Make sure assemblies with mailinglists can be deleted
        f = self.response.forms['createattendeelistform']
        self.submit(f)
        self.assertPresence("Versammlungsteilnehmer-Mailingliste angelegt.",
                            div="notifications")

        # Assemblies with ballots which started voting can not be deleted.
        # Other ballots are ok
        self.traverse({'description': "Abstimmungen"})
        self.assertPresence("Es wurden noch keine Abstimmungen angelegt.")
        self._create_ballot(bdata, candidates=None)
        self.assertTitle("Müssen wir wirklich regeln... (Drittes CdE-Konzil)")

        # Make sure assemblies with attachments can be deleted
        self.traverse("Dateien", "Datei hinzufügen")
        f = self.response.forms['addattachmentform']
        f['title'] = "Vorläufige Beschlussvorlage"
        f['attachment'] = webtest.Upload("form", attachment, "application/octet-stream")
        f['filename'] = "beschluss.pdf"
        self.submit(f)
        self.assertPresence("Vorläufige Beschlussvorlage")

        # Make sure assemblies with attendees can be deleted
        self.traverse({'description': r"\sÜbersicht"})
        f = self.response.forms['signupform']
        self.submit(f)
        f = self.response.forms['deleteassemblyform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Versammlungen")
        self.assertNonPresence("Drittes CdE-Konzil")

        self._create_assembly(delta={'presider_address': presider_address})
        self.traverse("Konfiguration")
        f = self.response.forms['configureassemblyform']
        self.assertEqual(f['presider_address'].value, presider_address)

    @as_users("viktor")
    def test_show_assembly_admin(self) -> None:
        self.traverse("Versammlungen", "Archiv-Sammlung")
        self.assertTitle("Archiv-Sammlung")

        self.submit(
            self.response.forms[f"removepresiderform{ USER_DICT['werner']['id'] }"])
        f = self.response.forms['createpresiderlistform']
        self.assertIn('disabled', f.fields['submitform'][0].attrs)
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Mailingliste kann nur mit Versammlungsleitern erstellt werden.",
            div='notifications')
        f = self.response.forms['addpresidersform']
        f['presider_ids'] = USER_DICT['werner']['DB-ID']
        self.submit(f)
        self.submit(self.response.forms['createattendeelistform'])
        self.submit(self.response.forms['createpresiderlistform'])

    @as_users("werner")
    def test_show_assembly_presider(self) -> None:
        self.traverse("Versammlungen", "Archiv-Sammlung")
        self.assertTitle("Archiv-Sammlung")

        self.assertNotIn('addpresidersform', self.response.forms)
        self.assertNotIn('createattendeelistform', self.response.forms)

    @as_users("kalif")
    def test_show_assembly_attendee(self) -> None:
        self.traverse("Versammlungen", "Internationaler Kongress")
        self.assertTitle("Internationaler Kongress")

        self.assertNonPresence("Datei hinzufügen")
        self.assertNotIn('addpresidersform', self.response.forms)
        self.assertNotIn('createattendeelistform', self.response.forms)

    @as_users("charly")
    def test_signup(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'},)
        self.assertTitle("Internationaler Kongress")
        f = self.response.forms['signupform']
        self.submit(f)
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("kalif")
    def test_no_signup(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'}, )
        self.assertTitle("Internationaler Kongress")
        self.assertNotIn('signupform', self.response.forms)

    @as_users("werner", "ferdinand")
    def test_external_signup(self) -> None:
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
    def test_list_attendees(self) -> None:
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
        if self.user_in('kalif'):
            self.assertNonPresence("Download")
        elif self.user_in('viktor', 'werner'):
            self.assertPresence("Download")
            self.traverse("TeX-Liste")
            for attendee in attendees:
                self.assertIn(attendee, self.response.text)

    @storage
    @as_users("rowena")
    def test_summary_ballots(self) -> None:
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Kanonische Beispielversammlung'},
                      {'description': 'Zusammenfassung'})
        self.assertTitle("Zusammenfassung (Kanonische Beispielversammlung)")
        self.assertPresence("Entlastung des Vorstands")
        self.assertPresence("Wir kaufen den Eisenberg!")

    @storage
    @as_users("ferdinand")
    def test_conclude_assembly(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            self._create_assembly()
            self._signup()
            self.traverse({'description': 'Konfiguration'})
            f = self.response.forms['configureassemblyform']
            f['signup_end'] = "2002-4-1 00:00:00"
            self.submit(f)

            for ballot_nr in (1, 2):
                bdata = {
                    'title': f'Maximale Länge der {ballot_nr}. Satzung',
                    'description': "Dann muss man halt eine alte Regel rauswerfen,"
                                   " wenn man eine neue will.",
                    'vote_begin': base_time + delta,
                    'vote_end': base_time + delta + 2*ballot_nr*delta,
                    'abs_quorum': "0",
                    'rel_quorum': "0",
                    'votes': "",
                    'notes': "Kein Aprilscherz!",
                }
                self._create_ballot(bdata, candidates=None)
                self.assertTitle(f"{bdata['title']} (Drittes CdE-Konzil)")

            # regression test for #2310
            frozen_time.tick(delta=2 * delta)
            self.traverse("Abstimmungen", "Maximale Länge der 1. Satzung")
            frozen_time.tick(delta=2 * delta)
            # First ballot is concluded now, second still running. Ensure viewing
            # the second concludes the first and navigation works
            self.traverse("Nächste")
            frozen_time.tick(delta=2 * delta)
            self.traverse("Nächste", "Drittes CdE-Konzil")

            # now the actual conclusion test
            self.assertTitle("Drittes CdE-Konzil")
            f = self.response.forms['concludeassemblyform']
            f['ack_conclude'].checked = True
            self.submit(f)
            self.assertTitle("Drittes CdE-Konzil")
            # Presiders can no longer be changed
            self.assertNotIn("addpresidersform", self.response.forms)
            self.assertNotIn("removepresiderform1", self.response.forms)
            # deletion is not possible
            self.assertNotIn("deleteassemblyform", self.response.forms)

    @storage
    @as_users("anton")
    def test_preferential_vote_result(self) -> None:
        self.get('/assembly/assembly/1/ballot/1/show')
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        own_vote = ("Du hast mit der folgenden Präferenz abgestimmt:"
                    " 23 > 42 > Ablehnungsgrenze > Ich = Philosophie")
        self.assertPresence(own_vote, div='own-vote', exact=True)

    @storage
    @as_users("garcia")
    def test_show_ballot_without_vote(self) -> None:
        self.get('/assembly/assembly/1/show')
        f = self.response.forms['signupform']
        self.submit(f)
        self.get('/assembly/assembly/1/ballot/1/show')
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    @storage
    @as_users("berta")
    def test_show_ballot_status(self) -> None:
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

    @storage
    @as_users("garcia")
    def test_show_ballot_without_attendance(self) -> None:
        self.get('/assembly/assembly/1/ballot/1/show')
        self.assertTitle("Antwort auf die letzte aller Fragen "
                         "(Internationaler Kongress)")
        self.assertPresence("Nach dem Leben, dem Universum und dem ganzen Rest")
        self.traverse({'description': 'Ergebnisdetails'})
        self.assertPresence("Du nimmst nicht an der Versammlung teil.",
                            div='own-vote', exact=True)

    @storage
    @as_users("werner")
    def test_entity_ballot_simple(self) -> None:
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
        f = self.response.forms['configureballotform']
        self.assertEqual("Kein Aprilscherz!", f['notes'].value)
        f['notes'] = "April, April!"
        f['vote_begin'] = "2222-4-1 00:00:00"
        f['vote_end'] = "2222-4-1 00:00:01"
        self.submit(f)
        # votes must be empty or a positive int
        self.traverse({'description': 'Bearbeiten'}, )
        f = self.response.forms['configureballotform']
        f['votes'] = 0
        self.submit(f, check_notification=False)
        self.assertValidationError('votes', message="Muss positiv sein.")
        f['votes'] = 1
        self.submit(f)
        self.assertTitle("Maximale Länge der Satzung (Internationaler Kongress)")
        self.traverse({'description': 'Bearbeiten'},)
        f = self.response.forms['configureballotform']
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

    @storage
    @as_users("werner")
    def test_delete_ballot(self) -> None:
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

    @storage
    @as_users("charly", "viktor")
    def test_attachment_redirects(self) -> None:
        # Test that accessing the latest version and the legacy urls redirect to the
        # correct page.
        # attachment_ids = set.union(*
        attachment_ids = set.union(*[
            self.assembly.list_attachments(self.key, assembly_id=assembly_id)
            for assembly_id in self.assembly.list_assemblies(self.key)
        ])

        for attachment_id in attachment_ids:
            self._test_one_attachment_redirect(attachment_id)

    def _test_one_attachment_redirect(self, attachment_id: int) -> None:
        attachment = self.assembly.get_attachment(self.key, attachment_id)
        assembly_id = attachment['assembly_id']
        ballot_ids = attachment['ballot_ids']
        latest_version_nr = attachment['latest_version_nr']

        # Use get via the app, to avoid following the redirects.
        # Check that legacy urls with a version redirect to that version.
        version_target = (f"/assembly/assembly/{assembly_id}"
                          f"/attachment/{attachment_id}/version/{latest_version_nr}")

        urls = (
            # Shortcut that always redirects to the current version.
            f"/assembly/assembly/{assembly_id}/attachment/{attachment_id}/latest",
            # Legacy url with additional "/get".
            f"/assembly/assembly/{assembly_id}"
            f"/attachment/{attachment_id}/version/{latest_version_nr}/get",
        ) + tuple(
            # Legacy url with the ballot the attachment is linked to.
            # This redirect should work with arbitrary ballot_ids in theory.
            f"/assembly/assembly/{assembly_id}/ballot/{ballot_id}"
            f"/attachment/{attachment_id}/version/{latest_version_nr}/get"
            for ballot_id in ballot_ids
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertRedirect(url, target_url=version_target)

        # Check that urls without a version redirect to the latest version.
        non_version_target = urls[0]

        urls = (
            # simple url for convenience
            f"/assembly/assembly/{assembly_id}/attachment/{attachment_id}/",
            # Legacy url that used to retrieve the latest version.
            f"/assembly/assembly/{assembly_id}/attachment/{attachment_id}/get",
        ) + tuple(
            # Legacy url for retrieving the latest version of a ballot attachment.
            f"/assembly/assembly/{assembly_id}/ballot/{ballot_id}"
            f"/attachment/{attachment_id}/get"
            for ballot_id in ballot_ids
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertRedirect(url, target_url=non_version_target)

    @storage
    @as_users("werner")
    def test_attachment(self) -> None:
        with open(self.testfile_dir / "rechen.pdf", 'rb') as datafile:
            data = datafile.read()

        self.traverse("Versammlungen", "Archiv-Sammlung")

        self.assertPresence("Rechenschaftsbericht", div="attachment1_version1")
        self.assertPresence("Kassenprüferbericht 2 (Version 3)",
                            div="attachment2_version3")
        self.assertPresence("Liste der Kandidaten", div="attachment3_version1")

        # Check file content.
        saved_response = self.response
        self.traverse({"href": "/assembly/assembly/3/attachment/1/latest"})
        self.assertEqual(data, self.response.body)
        self.response = saved_response

        # Test Details link
        self.traverse({"href": "assembly/assembly/3/attachments#attachment2_version3"})
        self.assertTitle("Dateien (Archiv-Sammlung)")

        self.assertPresence("Rechenschaftsbericht (Version 1)",
                            div="attachment1_version1")
        self.assertPresence("Kassenprüferbericht 2 (Version 3)",
                            div="attachment2_version3")
        self.assertPresence("Version 2 wurde gelöscht", div="attachment2_version2")
        self.assertPresence("Kassenprüferbericht (Version 1)",
                            div="attachment2_version1")
        self.assertPresence("Liste der Kandidaten (Version 1)",
                            div="attachment3_version1")

        # remove Kassenprüferbericht
        f = self.response.forms["removeattachmentversionform2_3"]
        f["attachment_ack_delete"] = True
        self.submit(f)
        self.assertPresence("Version 3 wurde gelöscht", div="attachment2_version3")
        f = self.response.forms["deleteattachmentform2"]
        f["attachment_ack_delete"] = True
        self.submit(f)
        self.assertNonPresence("Kassenprüferbericht")

        # check log
        self.traverse("Log")
        self.assertPresence("Anhangsversion entfernt", div="1-1001")
        self.assertPresence("Kassenprüferbericht 2: Version 3", div="1-1001")
        self.assertPresence("Anhang entfernt", div="2-1002")
        self.assertPresence("Kassenprüferbericht", div="2-1002")

    @storage
    @as_users("werner")
    def test_attachment_ballot_linking(self) -> None:
        with open(self.testfile_dir / "form.pdf", 'rb') as datafile:
            data = datafile.read()
        self.traverse({'description': 'Versammlungen$'},
                      {'description': 'Internationaler Kongress'},
                      {'description': 'Dateien'})
        self.assertTitle("Dateien (Internationaler Kongress)")
        self.traverse("Datei hinzufügen")
        self.assertTitle("Datei hinzufügen (Internationaler Kongress)")

        # First try upload with invalid default filename
        f = self.response.forms['addattachmentform']
        f['title'] = "Vorläufige Beschlussvorlage"
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        self.submit(f, check_notification=False)
        self.assertValidationError(
            "filename", "Darf nur aus druckbaren ASCII-Zeichen bestehen")
        # Now, add an correct override filename
        f = self.response.forms['addattachmentform']
        f['attachment'] = webtest.Upload("form….pdf", data, "application/octet-stream")
        f['filename'] = "beschluss.pdf"
        self.submit(f)

        self.assertTitle("Dateien (Internationaler Kongress)")
        self.assertPresence(
            "Vorläufige Beschlussvorlage", div="attachment1001_version1")
        self.assertIn("deleteattachmentform1001", self.response.forms)

        # Check file content.
        saved_response = self.response
        self.traverse({'description': 'Vorläufige Beschlussvorlage'},)
        self.assertEqual(data, self.response.body)
        self.response = saved_response

        # Add a new version
        self.traverse({"href": "/assembly/assembly/1/attachment/1001/add"})
        # TODO assert there is no warning text about a locked ballot
        f = self.response.forms['addattachmentversionform']
        f['title'] = "Maßgebliche Beschlussvorlage"
        f['authors'] = "Der Vorstand"
        f['attachment'] = webtest.Upload("form.pdf", data, "application/octet-stream")
        self.submit(f)

        self.assertTitle("Dateien (Internationaler Kongress)")
        self.assertPresence(
            "Vorläufige Beschlussvorlage", div="attachment1001_version1")
        self.assertIn("removeattachmentversionform1001_1", self.response.forms)
        self.assertPresence(
            "Maßgebliche Beschlussvorlage", div="attachment1001_version2")
        self.assertIn("removeattachmentversionform1001_2", self.response.forms)
        self.assertNotIn("deleteattachmentform1001", self.response.forms)

        # Link the attachment with a ballot
        self.traverse("Abstimmungen", "Farbe des Logos")
        self.assertPresence("Zu dieser Abstimmung gibt es noch keine Dateien.",
                            div="attachments")
        self.traverse("Bearbeiten")
        f = self.response.forms["configureballotform"]
        f["linked_attachments"] = ["1001"]
        self.submit(f)

        self.assertTitle("Farbe des Logos (Internationaler Kongress)")
        self.assertPresence("Maßgebliche Beschlussvorlage (Version 2)",
                            div="attachments")
        # check that the correct version is linked
        saved_response = self.response
        self.traverse({"href": "/assembly/assembly/1/attachment/1001/version/2/"})
        self.response = saved_response

        # now start voting
        base_time = now()
        delta = datetime.timedelta(days=1)
        with freezegun.freeze_time(base_time) as frozen_time:
            self.traverse("Bearbeiten")
            f = self.response.forms['configureballotform']
            f['vote_begin'] = base_time + delta
            f['vote_end'] = base_time + 3*delta
            f['vote_extension_end'] = base_time + 5*delta
            f['abs_quorum'] = "0"
            f['rel_quorum'] = "100"
            self.submit(f)
            frozen_time.tick(delta=2*delta)

            self.traverse("Abstimmungen", "Farbe des Logos")
            self.assertTitle("Farbe des Logos (Internationaler Kongress)")
            self.assertPresence("Die Abstimmung läuft.", div="ballot-status")
            self.assertPresence("Maßgebliche Beschlussvorlage (Version 2, maßgeblich)",
                                div="attachments")

            # check that the attachment can not be deleted anymore
            self.traverse(
                {"href": "/assembly/assembly/1/attachments#attachment1001_version2"})
            self.assertTitle("Dateien (Internationaler Kongress)")
            self.assertNotIn("removeattachmentversionform1001_1", self.response.forms)
            self.assertNotIn("removeattachmentversionform1001_2", self.response.forms)

            # add a new version
            self.traverse({"href": "/assembly/assembly/1/attachment/1001/add"})
            # TODO assert there is a warning text about a locked ballot
            f = self.response.forms['addattachmentversionform']
            f['title'] = "Formal geänderte Beschlussvorlage"
            f['attachment'] = webtest.Upload("form.pdf", data,
                                             "application/octet-stream")
            self.submit(f, check_notification=False)
            self.assertValidationError("ack_creation", "Muss markiert sein.")
            f = self.response.forms['addattachmentversionform']
            f['title'] = "Formal geänderte Beschlussvorlage"
            f['attachment'] = webtest.Upload("form.pdf", data,
                                             "application/octet-stream")
            f['ack_creation'] = True
            self.submit(f)

            self.assertTitle("Dateien (Internationaler Kongress)")
            self.assertPresence(
                "Vorläufige Beschlussvorlage", div="attachment1001_version1")
            self.assertPresence(
                "Maßgebliche Beschlussvorlage", div="attachment1001_version2")
            self.assertPresence(
                "Formal geänderte Beschlussvorlage", div="attachment1001_version3")
            self.assertNotIn("removeattachmentversionform1001_3", self.response.forms)

            # check the definitive version is still correct and the new version is shown
            self.traverse("Abstimmungen", "Farbe des Logos")
            self.assertPresence("Die Abstimmung läuft.", div="ballot-status")
            self.assertPresence("Maßgebliche Beschlussvorlage (Version 2, maßgeblich)",
                                div="attachments")
            self.assertPresence(
                "Formal geänderte Beschlussvorlage (Version 3)", div="attachments")

        # check log
        self.traverse("Log")
        self.assertPresence("Anhang hinzugefügt", div="1-1001")
        self.assertPresence("Vorläufige Beschlussvorlage", div="1-1001")
        self.assertPresence("Anhangsversion hinzugefügt", div="2-1002")
        self.assertPresence("Maßgebliche Beschlussvorlage: Version 2", div="2-1002")
        self.assertPresence("Anhang mit Abstimmung verknüpft", div="5-1005")
        self.assertPresence("Maßgebliche Beschlussvorlage (Farbe des Logos)",
                            div="5-1005")
        self.assertPresence("Anhangsversion hinzugefügt", div="8-1008")
        self.assertPresence("Formal geänderte Beschlussvorlage: Version 3",
                            div="8-1008")

    @storage
    @as_users("werner", "inga", "kalif")
    def test_preferential_vote(self) -> None:
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

    @storage
    @as_users("werner", "inga", "kalif")
    def test_classical_vote_radio(self) -> None:
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

    @storage
    @as_users("werner", "inga", "kalif")
    def test_classical_vote_select(self) -> None:
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

    @storage
    @as_users("werner")
    def test_classical_voting_all_choices(self) -> None:
        # This test asserts that in classical voting, we can distinguish
        # between abstaining and voting for all candidates
        self.traverse({'description': 'Versammlungen'},
                      {'description': 'Internationaler Kongress'})

        # We need two subtests: One with an explict bar (including the "against
        # all candidates option), one without an explicit bar (i.e. the bar is
        # added implicitly)
        for use_bar in (False, True):
            with self.subTest(use_bar=use_bar):
                base_time = now()
                delta = datetime.timedelta(seconds=42)
                with freezegun.freeze_time(base_time) as frozen_time:
                    # First, create a new ballot
                    bdata = {
                        'title': 'Wahl zum Finanzvorstand -- {} bar'
                                 .format("w." if use_bar else "w/o"),
                        'vote_begin': base_time + delta,
                        'vote_end': base_time + 3*delta,
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
                    frozen_time.tick(delta=2*delta)
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
                    frozen_time.tick(delta=2*delta)
                    self.traverse({'description': 'Abstimmungen'},
                                  {'description': bdata['title']},
                                  {'description': 'Ergebnisdetails'})
                    self.assertPresence("Du hast für die folgenden Kandidaten "
                                        "gestimmt: Arthur Dent = Ford Prefect",
                                        div='own-vote', exact=True)

    @storage
    @as_users("werner", "inga", "kalif")
    def test_tally_and_get_result(self) -> None:
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
        with open(self.testfile_dir / "ballot_result.json", 'rb') as f:
            self.assertEqual(json.load(f), json.loads(self.response.body))

    @storage
    @as_users("kalif")
    def test_late_voting(self) -> None:
        # create a ballot shortly before its voting end
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        btitle = "Ganz kurzfristige Entscheidung"
        bdata = {
            'title': btitle,
            'vote_begin': base_time + delta,
            'vote_end': base_time + 3 * delta,
            'votes': "2",
        }
        candidates = [
            {'shortname': "y", 'title': "Ja!"},
            {'shortname': "n", 'title': "Nein!"},
        ]
        with freezegun.freeze_time(base_time) as frozen_time:
            # only presiders can create ballots
            with self.switch_user('werner'):
                self.traverse("Versammlungen", "Internationaler Kongress")
                self._create_ballot(bdata, candidates)

            # wait for voting to start then get vote form.
            frozen_time.tick(delta=2 * delta)
            self.traverse("Versammlungen", "Internationaler Kongress",
                          "Abstimmungen", btitle)
            f = self.response.forms["voteform"]
            f["vote"] = ["y"]

            # submit after voting period ended
            frozen_time.tick(delta=2 * delta)
            self.submit(f, check_notification=False)
            self.assertPresence("Fehler! Abstimmung ist außerhalb"
                                " des Abstimmungszeitraums",
                                div='notifications')

    @storage
    @as_users("werner")
    def test_comment(self) -> None:
        self.get('/assembly/assembly/3/ballot/6/show')
        self.assertNonPresence("Abstimmungskommentar")
        self.traverse("Kommentieren")
        f = self.response.forms['commentballotform']
        comment = "War nur ein *Experiment*."
        f['comment'] = comment
        self.submit(f)
        self.assertTitle("Test-Abstimmung – bitte ignorieren (Archiv-Sammlung)")
        self.assertPresence("Abstimmungskommentar")
        self.assertPresence("War nur ein Experiment.")
        self.traverse("Kommentieren")
        f = self.response.forms['commentballotform']
        # check that the form is filled with the current comment
        self.assertEqual(comment, f['comment'].value)
        f['comment'] = ""
        self.submit(f)
        self.assertTitle("Test-Abstimmung – bitte ignorieren (Archiv-Sammlung)")
        self.assertNonPresence("Abstimmungskommentar")

    @storage
    @as_users("anton")
    def test_ballot_result_page(self) -> None:
        for ballot_id in self.CANONICAL_BALLOTS:
            ballot = self.get_sample_datum('assembly.ballots', ballot_id)
            assembly = self.get_sample_datum(
                'assembly.assemblies', ballot['assembly_id'])
            self.get(f'/assembly/assembly/{assembly["id"]}/ballot/{ballot_id}/result')

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

    @storage
    @as_users("anton")
    def test_ballot_result_page_extended(self) -> None:
        # classical vote with bar
        self.traverse({'description': 'Versammlung'},
                      {'description': 'Kanonische Beispielversammlung'},
                      {'description': 'Zusammenfassung'},
                      {'description': 'Eine damals wichtige Frage'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/"
                         "Eine damals wichtige Frage)")

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
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/Entlastung des"
                         " Vorstands)")

        # test if the overall result is displayed correctly
        result = "Ja > Nein"
        self.assertPresence(result, div='combined-preference', exact=True)

        # test if abstentions are rendered correctly
        self.assertPresence("Enthalten 1", div='vote-3', exact=True)

        # preferential vote without bar
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Wie soll der CdE mit seinem Vermögen umgehen?'},
                      {'description': 'Ergebnisdetails'})
        self.assertTitle("Ergebnis (Kanonische Beispielversammlung/Wie soll der CdE mit"
                         " seinem Vermögen umgehen?)")

        # test if the overall result is displayed correctly
        result = ("Wir kaufen den Eisenberg! = Kostenlose Akademien für alle."
                  " > Investieren in Aktien und Fonds.")
        self.assertPresence(result, div='combined-preference', exact=True)

        # test a vote string
        vote = ("Kostenlose Akademien für alle. > Investieren in Aktien und Fonds."
                " = Wir kaufen den Eisenberg! 3")
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

    @storage
    @as_users("werner")
    def test_extend(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            self.traverse({'description': 'Versammlungen'},
                          {'description': 'Internationaler Kongress'},
                          {'description': 'Abstimmungen'},
                          {'description': 'Abstimmung anlegen'},)
            f = self.response.forms['configureballotform']
            f['title'] = 'Maximale Länge der Verfassung'
            f['vote_begin'] = base_time + delta
            f['vote_end'] = base_time + 3*delta
            f['vote_extension_end'] = "2037-5-1 00:00:00"
            f['abs_quorum'] = "0"
            f['rel_quorum'] = "100"
            f['votes'] = ""
            self.submit(f)
            self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
            ballot = self.assembly.get_ballot(self.key, 1001)
            self.assertPresence(
                f"Verlängerung bis 01.05.2037, 00:00:00, falls {ballot['quorum']}"
                f" Stimmen nicht erreicht werden.", div='voting-period')

            frozen_time.tick(delta=4*delta)
            self.traverse({'href': '/assembly/1/ballot/list'},
                          {'description': 'Maximale Länge der Verfassung'},)
            self.assertTitle("Maximale Länge der Verfassung (Internationaler Kongress)")
            s = (f"Wurde bis 01.05.2037, 00:00:00 verlängert, da {ballot['quorum']}"
                 f" Stimmen nicht erreicht wurden.")
            self.assertPresence(s, div='voting-period')

    @storage
    @as_users("werner")
    def test_candidate_manipulation(self) -> None:
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

    @storage
    @as_users("werner")
    def test_has_voted(self) -> None:
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
        self._external_signup(self.user)
        self.traverse({'description': 'Abstimmungen'},
                      {'description': 'Test-Abstimmung – bitte ignorieren'},
                      {'description': 'Ergebnisdetails'})

        self.assertNonPresence("Du nimmst nicht an der Versammlung teil.")
        self.assertPresence("Du hast nicht abgestimmt.", div='own-vote',
                            exact=True)

    @storage
    def test_provide_secret(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time,
                                   ignore=['cdedb.filter', 'icu']) as frozen_time:
            self.login('werner')
            self.traverse({'description': 'Versammlungen'},
                          {'description': 'Archiv-Sammlung'})
            # werner is no member, so he must signup external
            secret = self._external_signup('werner')
            # Create new ballot.
            bdata = {
                'title': 'Maximale Länge der Verfassung',
                'vote_begin': base_time + delta,
                'vote_end': base_time + 3*delta,
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
            frozen_time.tick(delta=2*delta)
            self.traverse({'description': 'Abstimmungen'},
                          {'description': bdata['title']})
            f = self.response.forms["voteform"]
            f["vote"] = "ja"
            self.submit(f)

            # Check tally and own vote.
            frozen_time.tick(delta=2*delta)
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
            self.traverse({'description': 'Abstimmungen'},
                          {'description': 'Genauso wichtige Wahl'})
            f = self.response.forms['deleteballotform']
            f['ack_delete'].checked = True
            self.submit(f)

            # Conclude assembly.
            with self.switch_user('viktor'):
                self.traverse({'description': "Versammlung"},
                              {'description': "Archiv-Sammlung"})
                self.assertTitle("Archiv-Sammlung")
                f = self.response.forms['concludeassemblyform']
                f['ack_conclude'].checked = True
                self.submit(f)

            # Own vote should be hidden now.
            self.traverse({'description': 'Maximale Länge der Verfassung'},
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
        f = self.response.forms['configureassemblyform']
        f['notes'] = "Werner war hier!"
        self.submit(f)
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
