#!/usr/bin/env python3

import csv
import datetime
import decimal
import itertools
import json
import re
from typing import Set, Tuple

import webtest

import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, ADMIN_VIEWS_COOKIE_NAME, Role, extract_roles, now, LineResolutions
)
from cdedb.query import QueryOperators
from tests.common import (
    FrontendTest, UserIdentifier, USER_DICT, as_users, get_user, prepsql, storage,
)


PERSONA_TEMPLATE = {
        "username": 'zelda@example.cde',
        "title": "Dr.",
        "given_names": "Zelda",
        "family_name": "Zeruda-Hime",
        "name_supplement": 'von und zu',
        "display_name": 'Zelda',
        "birthday": "1987-06-05",
        "specialisation": "oehm",
        "affiliation": "Hogwarts",
        "timeline": "tja",
        "interests": "hmmmm",
        "free_form": "jaaah",
        "gender": "1",
        "telephone": "030456790",
        "mobile": "01602047",
        "weblink": "www.zzz.cc",
        "address": "Street 7",
        "address_supplement": "on the left",
        "postal_code": "12345",
        "location": "Lynna",
        "country": "HY",
        "address2": "Ligusterweg 4",
        "address_supplement2": "Im Schrank unter der Treppe",
        "postal_code2": "00AA",
        "location2": "Little Whinging",
        "country2": "GB",
        "notes": "some talk",
    }


class TestCdEFrontend(FrontendTest):
    @as_users("vera", "berta")
    def test_index(self) -> None:
        self.traverse({'description': 'Mitglieder'})

    def test_ejection_date(self) -> None:
        def _calculate_ejection_deadline(persona_data: CdEDBObject,
                                         period: CdEDBObject) -> datetime.datetime:
            """Clone of `CdEFrontend._calculate_ejection_deadline`."""
            periods_left = persona_data['balance'] // decimal.Decimal("2.50")
            if persona_data['trial_member']:
                periods_left += 1
            if period['balance_done']:
                periods_left += 1
            deadline = period["semester_start"].date().replace(day=1)
            # There are 3 semesters within any year with different deadlines.
            if deadline.month in range(5, 11):
                # We are in the summer semester.
                if periods_left % 2:
                    deadline = deadline.replace(year=deadline.year + 1, month=2)
                else:
                    deadline = deadline.replace(month=8)
            else:
                # We are in a winter semester.
                if deadline.month in range(1, 5):
                    # We are in the first semester of the year.
                    deadline = deadline.replace(month=2)
                else:
                    # We are in the last semester of the year.
                    deadline = deadline.replace(year=deadline.year + 1, month=2)
                if periods_left % 2:
                    deadline = deadline.replace(month=8)
            return deadline.replace(
                year=deadline.year + periods_left // 2)
        persona_data = {
            "balance": 0,
            "trial_member": False,
        }
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-01-01"),
            "balance_done": False,
        }
        self.assertEqual(datetime.date.fromisoformat("2020-02-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-01-01"),
            "balance_done": True,
        }
        self.assertEqual(datetime.date.fromisoformat("2020-08-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-07-01"),
            "balance_done": False,
        }
        self.assertEqual(datetime.date.fromisoformat("2020-08-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-07-01"),
            "balance_done": True,
        }
        self.assertEqual(datetime.date.fromisoformat("2021-02-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-12-01"),
            "balance_done": False,
        }
        self.assertEqual(datetime.date.fromisoformat("2021-02-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))
        period_data = {
            "semester_start": datetime.datetime.fromisoformat("2020-12-01"),
            "balance_done": True,
        }
        self.assertEqual(datetime.date.fromisoformat("2021-08-01"),
                         _calculate_ejection_deadline(
                             persona_data, period_data))

    @as_users("annika", "berta", "charly", "farin", "martin", "vera", "werner")
    def test_sidebar(self) -> None:
        self.traverse({'description': 'Mitglieder'})
        everyone = {"Mitglieder", "Übersicht"}
        past_event = {"Verg. Veranstaltungen", "Kurssuche"}
        member = {"Sonstiges", "Datenschutzerklärung"}
        searchable = {"CdE-Mitglied suchen"}
        cde_admin_or_member = {"Mitglieder-Statistik"}
        cde_admin = {"Nutzer verwalten", "Archivsuche", "Organisationen verwalten",
                     "Verg.-Veranstaltungen-Log"}
        finance_admin = {
            "Einzugsermächtigungen", "Kontoauszug parsen", "Finanz-Log",
            "Überweisungen eintragen", "Semesterverwaltung", "CdE-Log"}

        # non-members
        if self.user_in('annika', 'werner', 'martin'):
            ins = everyone
            out = past_event | member | searchable | cde_admin | finance_admin
        # searchable member
        elif self.user_in('berta'):
            ins = everyone | past_event | member | cde_admin_or_member | searchable
            out = cde_admin | finance_admin
        # not-searchable member
        elif self.user_in('charly'):
            ins = everyone | past_event | member | cde_admin_or_member
            out = searchable | cde_admin | finance_admin
        # cde but not finance admin (vera is no member)
        elif self.user_in('vera'):
            ins = everyone | past_event | cde_admin_or_member | cde_admin
            out = member | searchable | finance_admin
        # cde and finance admin (farin is no member)
        elif self.user_in('farin'):
            ins = everyone | past_event | cde_admin_or_member | cde_admin | finance_admin
            out = member | searchable
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("vera", "berta")
    def test_showuser(self) -> None:
        self.traverse({'description': self.user['display_name']},)
        self.assertTitle(f"{self.user['given_names']} {self.user['family_name']}")
        # TODO extend
        if self.user_in("berta"):
            self.assertPresence('PfingstAkademie')

    @as_users("berta")
    def test_changedata(self) -> None:
        self.traverse({'description': self.user['display_name']},
                      {'description': 'Bearbeiten'})
        # Make sure all country codes are translated
        self.assertNonPresence("CountryCode")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location2'] = "Hyrule"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertPresence("Hyrule", div='address2')
        self.assertPresence("Okarinas", div='additional')
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("quintus", "vera")
    def test_adminchangedata(self) -> None:
        # Berta
        self.realm_admin_view_profile('berta', "cde")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        f['free_form'] = "Jabberwocky for the win."
        self.submit(f)
        self.assertPresence("Zelda", div='personal-information')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933", div='personal-information')
        self.assertPresence("Jabberwocky for the win.", div='additional')

        # Olaf, disabled
        self.realm_admin_view_profile('olaf', "cde")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Link"
        f['birthday'] = "21.11.1998"
        f['free_form'] = "Spiele gerne Okarina."
        self.submit(f)
        self.assertPresence("Link", div='personal-information')
        self.assertTitle("Olafson Olaf")
        self.assertPresence("21.11.1998", div='personal-information')
        self.assertPresence("Spiele gerne Okarina.", div='additional')

    @as_users("anton")
    def test_cde_admin_views(self) -> None:
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')

        self.traverse({'href': '/cde'})
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=False)

        # Test Finance Admin View
        self.traverse({'href': '/cde/search/user'})
        self.assertNoLink('/cde/semester/show')
        self.assertNoLink('/cde/lastschrift/')
        self.assertNoLink('/cde/log')
        self.realm_admin_view_profile('berta', 'cde')
        self.assertNoLink('/lastschrift')
        self.assertNoLink('/balance/change')
        self.traverse({'href': '/cde'})
        self._click_admin_view_button(re.compile(r"Finanz-Administration"),
                                      current_state=False)
        self.traverse({'href': '/cde/semester/show'},
                      {'href': '/cde/log'},
                      {'href': '/cde/parse'},
                      {'href': '/cde/lastschrift'},
                      {'href': '/cde/user/2/lastschrift'},
                      {'href': '/core/persona/2/show'},
                      {'href': '/cde/user/2/lastschrift'})

        # Test Past Event Admin View
        self.traverse({'href': '/cde/past/event/list'})
        self.assertNoLink('/cde/past/event/create')
        self.traverse({'href': '/cde/past/event/1/show'})
        self.assertNoLink('/cde/past/event/1/change')
        self.assertNoLink('/cde/past/event/1/course/create')
        self.assertNotIn('addparticipantform', self.response.forms)
        self.assertNotIn('removeparticipantform3', self.response.forms)
        self.assertNotIn('deletepasteventform', self.response.forms)
        self.assertNonPresence('Emilia')
        self.assertPresence('weitere …')
        self.traverse({'href': '/cde/past/event/1/course/2/show'})

        self._click_admin_view_button(re.compile(r"Verg.-Veranst.-Administration"),
                                      current_state=False)
        self.traverse({'href': '/cde/past/event/1/show'},
                      {'href': '/cde/past/event/1/change'},
                      {'href': '/cde/past/event/list'},
                      {'href': '/cde/past/event/create'},
                      {'href': '/cde/past/event/list'},
                      {'href': '/cde/past/event/1/show'})
        self.assertPresence('Emilia')
        self.assertIn('addparticipantform', self.response.forms)
        self.assertIn('removeparticipantform3', self.response.forms)
        self.assertIn('deletepasteventform', self.response.forms)

    @as_users("vera")
    def test_validation(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "garbage"
        self.submit(f, check_notification=False)
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        self.assertValidationError("birthday", "Ungültige Eingabe für ein Datum")
        f = self.response.forms['changedataform']
        self.assertEqual("Zelda", f['display_name'].value)

    @as_users("garcia")
    def test_consent(self) -> None:
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.traverse({'description': 'Index'})
        self.assertTitle("CdE-Datenbank")
        self.traverse({'description': self.user['display_name']})
        self.assertPresence("Noch nicht entschieden", div='searchability')
        self.traverse({'description': 'Entscheiden'})
        f = self.response.forms['ackconsentform']
        self.submit(f)
        self.traverse({'description': self.user['display_name']})
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.",
                            div='searchability', exact=True)

    @as_users("garcia")
    def test_consent_decline(self) -> None:

        def _roles(user: UserIdentifier) -> Set[Role]:
            user = get_user(user)
            return extract_roles(self.core.get_persona(self.key, user['id']))

        # First, do not change anything
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.traverse({'description': 'Später entscheiden'})
        self.logout()
        # Now, decline consent and check searchability
        self.login(USER_DICT["garcia"])
        f = self.response.forms['nackconsentform']
        self.submit(f)
        self.assertNotIn("searchable", _roles(self.user))
        self.logout()
        # Now check, that you are not redirected to form, and search is not shown
        self.login(USER_DICT["garcia"])
        self.assertTitle("CdE-Datenbank")
        self.traverse({'description': 'Mitglieder'})
        self.assertPresence("Um die Mitgliedersuche verwenden zu können")
        # And do not change anything.
        self.traverse({'description': 'Datenschutzerklärung'})
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.traverse({'description': 'Nichts ändern'})
        self.assertNotIn("searchable", _roles(self.user))
        # Now, finally agree to consent
        self.traverse({'description': 'Datenschutzerklärung'})
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        f = self.response.forms['ackconsentform']
        self.submit(f)
        self.assertIn("searchable", _roles(self.user))

    @as_users("berta")
    def test_consent_noop(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Datenschutzerklärung'})
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        self.assertNotIn('ackconsentform', self.response.forms)
        self.assertNotIn('nackconsentform', self.response.forms)

    def test_consent_change(self) -> None:
        # Remove searchability of Bertalotta Beispiel
        self.login(USER_DICT["vera"])
        self.admin_view_profile('berta')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = False
        self.submit(f)

        # Check that Consent Decision is reachable for Berta but does not show
        # up upon login. CdE Member search should be disabled
        self.logout()
        self.login(USER_DICT["berta"])
        self.assertTitle("CdE-Datenbank")
        self.traverse({'description': 'Mitglieder'})
        self.assertNotIn("membersearchform", self.response.forms)
        self.traverse({'description': 'Datenschutzerklärung'})
        # Re-acknowledge consent
        f = self.response.forms['ackconsentform']
        self.submit(f)

    @as_users("berta")
    def test_quota(self) -> None:
        self.traverse({'description': 'Mitglieder'})
        f = self.response.forms['membersearchform']
        save = "/"

        count = self.conf["QUOTA_VIEWS_PER_DAY"] // 2
        for search, title in itertools.cycle((
                ("Anton Armin", "Anton Armin A. Administrator"),
                ("Inga Iota", "Inga Iota"))):
            count -= 1
            f['qval_fulltext'] = search
            if count >= 0:
                # Submitting the form will give a single result and redirect.
                self.response = f.submit()
                # Remember where this redirect leads.
                save = self.response.location
                self.follow()
                self.basic_validate()
                self.assertTitle(title)
            else:
                # After some iterations, the query will fail due to quota limit.
                self.response = f.submit(status=429)
                self.assertPresence("Limit für Zugriffe")
                self.assertPresence("automatisch zurückgesetzt")
                # Check that the redirect from a previous search now also fails.
                self.get(save, status=429)
                self.assertPresence("Limit für Zugriffe")
                self.assertNonPresence("unbekannter Fehler")
                self.assertPresence("automatisch zurückgesetzt")
                # Check that own profile remains accessible
                self.traverse({'href': '/core/self/show'})
                break

        # Check if all of this has been logged properly
        self.logout()
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Account-Log'})
        self.assertTitle("Account-Log [1–2 von 2]")
        self.assertPresence("Quota überschritten", div='1-1001')
        self.assertPresence("Quota überschritten", div='2-1002')
        self.assertPresence("Bertålotta Beispiel", div='1-1001')
        self.assertPresence("Bertålotta Beispiel", div='2-1002')

    @as_users("anton", "berta", "inga")
    def test_member_search(self) -> None:
        # by family_name and birth_name
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77", div='address')

        # by given_names and display_name
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77", div='address')

        # by past event
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms['membersearchform']
        f['qval_pevent_id'] = 1
        self.submit(f)
        self.traverse({'href': '/core/persona/2/show'})
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Im Garten 77", div='address')

        # by fulltext. This matchs only complete words, here on ...
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "1"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("3 Mitglieder gefunden", div='result-count')
        self.assertPresence("Akira", div='result')  # ... Address
        self.assertPresence("Ferdinand", div='result')  # ... Address
        self.assertPresence("Inga", div='result')  # ... Address
        # fulltext search must not match on DB-Id
        self.assertNonPresence("Anton", div='result')  # ... ID

        # by zip: upper
        self.traverse({'description': 'CdE-Mitglied suchen'})
        f = self.response.forms["membersearchform"]
        f['postal_upper'] = 20000
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden", div='result-count')
        self.assertPresence("Anton Armin A. Administrator", div='result')
        self.assertPresence("Inga Iota", div='result')

        # by zip: lower
        self.traverse({'description': 'CdE-Mitglied suchen'})
        f = self.response.forms["membersearchform"]
        f['postal_lower'] = 60000
        f['postal_upper'] = ""
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden", div='result-count')
        self.assertPresence("Bertålotta Beispiel", div='result')
        self.assertPresence("Ferdinand F. Findus", div='result')

        # by zip: upper and lower
        self.traverse({'description': 'CdE-Mitglied suchen'})
        f = self.response.forms["membersearchform"]
        f['postal_lower'] = 10100
        f['postal_upper'] = 20000
        self.submit(f)
        self.assertTitle("Inga Iota")
        self.assertPresence("Ich war ein Jahr in Südafrika.", div='additional')

        # by phone number
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms["membersearchform"]
        f["qval_telephone,mobile"] = 9876
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden", div='result-count')
        self.assertPresence("Anton Armin A. Administrator", div='result')
        self.assertPresence("Bertålotta Beispiel", div='result')

        # Test error displaying for invalid search input
        f = self.response.forms['membersearchform']
        fields = [
            "fulltext", "given_names,display_name", "family_name,birth_name",
            "weblink,specialisation,affiliation,timeline,interests,free_form",
            "username", "telephone,mobile",
            "address,address_supplement,address2,address_supplement2",
            "location,location2", "country,country2"]
        for field in fields:
            f['qval_' + field] = "[a]"
        self.submit(f, check_notification=False)
        for field in fields:
            self.assertValidationError("qval_" + field,
                                       "Darf keine verbotenen Zeichen enthalten")

        # Test too many separators
        # See #1816
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        f = self.response.forms["membersearchform"]
        f["qval_fulltext"] = "Inga  Iota"
        self.submit(f)
        self.assertTitle("Inga Iota")

    @as_users("inga")
    def test_member_search_restrictions(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        # len(entry) <= 3 must equal the column entry in the database
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Ant"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Keine Mitglieder gefunden.")

        # len(entry) > 3 performs a wildcard search
        f['qval_given_names,display_name'] = "Anton"
        self.submit(f)
        self.assertTitle("Anton Armin A. Administrator")

        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})

        # Fulltext search is a bit special: This handles every word individually
        # len(word) <= 3 must be a word (add word boundaries in the query)
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "sta"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Keine Mitglieder gefunden.")

        # len(word) > 3 can be just a part of a word
        f['qval_fulltext'] = "stadt"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden", div='result-count')
        self.assertPresence("Anton", div='result')
        self.assertPresence("Inga", div='result')

        # handle both cases individual in the same query
        f['qval_fulltext'] = "am"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("2 Mitglieder gefunden", div='result-count')
        self.assertPresence("Ferdinand", div='result')
        self.assertPresence("Inga", div='result')

        f['qval_fulltext'] = "am stadt"
        self.submit(f)
        self.assertTitle("Inga Iota")

    @as_users("charly")
    def test_member_search_non_searchable(self) -> None:
        self.traverse({'description': 'Mitglieder'})
        self.assertPresence("Mitglieder-Schnellsuche",
                            div='member-quick-search')
        self.assertPresence("Um die Mitgliedersuche verwenden zu können, musst "
                            "Du die Datenschutzerklärung bestätigen.",
                            div='member-quick-search')
        self.assertNonPresence("CdE-Mitglied suchen")
        self.get("/cde/search/member")
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Um die Mitgliedersuche verwenden zu können")
        self.assertPresence("Datenschutzerklärung")
        self.assertNonPresence("Suchmaske")

    @as_users("daniel", "janis")
    def test_member_search_non_member(self) -> None:
        self.get("/cde/search/member")
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Um die Mitgliedersuche verwenden zu können")
        self.assertNonPresence("Datenschutzerklärung")
        self.assertNonPresence("Suchmaske")

    @as_users("inga")
    def test_member_profile_gender_privacy(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'CdE-Mitglied suchen'})
        self.assertTitle("CdE-Mitglied suchen")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertNonPresence("weiblich")

    @as_users("inga", "farin")
    def test_past_course_search(self) -> None:
        # by description
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Kurssuche'})
        self.assertTitle("CdE-Kurssuche")
        self.assertNonPresence("Ergebnis")
        f = self.response.forms['coursesearchform']
        f['qval_courses.description'] = "anfassen"
        self.submit(f)
        self.assertTitle("CdE-Kurssuche")
        self.assertPresence("Ergebnis", div='result-count')
        self.assertPresence("2 Kurse gefunden", div='result-count')
        self.assertPresence("Goethe", div='result')
        self.assertPresence("Swish", div='result')
        self.assertPresence("PfingstAkademie 2014", div='result')
        self.traverse({'description': 'Goethe'})
        self.assertTitle("Goethe zum Anfassen (PfingstAkademie 2014)")

        # by course title
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Kurssuche'})
        f = self.response.forms['coursesearchform']
        f['qval_courses.title'] = "Goethe"
        self.submit(f)
        self.assertTitle("Goethe zum Anfassen (PfingstAkademie 2014)")

        # by course nr
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Kurssuche'})
        f = self.response.forms['coursesearchform']
        f['qval_courses.nr'] = "Ω"
        self.submit(f)
        self.assertTitle("Goethe zum Anfassen (PfingstAkademie 2014)")

        # by academy
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Kurssuche'})
        self.assertTitle("CdE-Kurssuche")
        f = self.response.forms['coursesearchform']
        f['qval_events.title'] = "2014"
        self.submit(f)
        self.assertTitle("CdE-Kurssuche")
        self.assertPresence("Ergebnis", div='result-count')
        self.assertPresence("2 Kurse gefunden", div='result-count')

        # way too specific
        # no navigation, since we are still on the course search page
        f = self.response.forms['coursesearchform']
        f['qval_courses.title'] = "Goethe"
        f['qval_courses.nr'] = "Ω"
        f['qval_courses.description'] = "anfassen"
        f['qval_events.title'] = "2014"
        self.submit(f)
        self.assertTitle("Goethe zum Anfassen (PfingstAkademie 2014)")

        # no results
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Kurssuche'})
        f = self.response.forms['coursesearchform']
        f['qval_courses.title'] = "Schiller"
        self.assertTitle("CdE-Kurssuche")
        self.submit(f)
        self.assertPresence("Ergebnis", div='result-count')
        self.assertPresence("Keine Kurse gefunden.")

        # Test error displaying for invalid search input
        f = self.response.forms['coursesearchform']
        f['qval_courses.title'] = "[a]"
        fields = [
            "courses.title", "courses.nr", "events.title", "courses.description"]
        for field in fields:
            f['qval_' + field] = "[a]"
        self.submit(f, check_notification=False)
        for field in fields:
            self.assertValidationError("qval_" + field,
                                       "Darf keine verbotenen Zeichen enthalten")

    @as_users("paul", "quintus")
    def test_user_search(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'})
        self.assertTitle("CdE-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_address'] = QueryOperators.match.value
        f['qval_address'] = 'Garten'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("CdE-Nutzerverwaltung")
        self.assertPresence("Ergebnis [1]", div='query-results')
        self.assertEqual(
            "2",
            self.response.lxml.xpath("//*[@id='query-result']/tbody/tr[1]/@data-id")[0])

    @as_users("vera")
    def test_user_search_csv(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'})
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
        expectation = "\n".join((
            'personas.id;given_names;family_name;username;birthday;decided_search;'
            'free_form',
            '2;Bertålotta;Beispiel;berta@example.cde;1981-02-11;True;'
            '"Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen"',
            '3;Charly C.;Clown;charly@example.cde;1984-05-13;True;'
            '"Ich bin ein ""Künstler""; im weiteren Sinne."',
            '4;Daniel D.;Dino;daniel@example.cde;1963-02-19;False;',
            '6;Ferdinand F.;Findus;ferdinand@example.cde;1988-01-01;True;',
            ''
        )).encode('utf-8-sig')
        self.assertEqual(expectation, self.response.body)

    @as_users("vera")
    def test_user_search_json(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'})
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

    @as_users("vera")
    def test_toggle_activity(self) -> None:
        self.admin_view_profile('berta')
        self.assertPresence("Ja", div='account-active', exact=True)
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertPresence("Nein", div='account-active', exact=True)

    @as_users("vera")
    def test_modify_membership(self) -> None:
        self.admin_view_profile('berta')
        self.assertPresence("CdE-Mitglied", div='membership')
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.",
                            div='searchability')
        self.traverse({'description': 'Status ändern'})
        self.assertTitle("Mitgliedsstatus von Bertålotta Beispiel bearbeiten")
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertNonPresence("CdE-Mitglied", div='membership')
        self.assertNonPresence("Daten sind für andere Mitglieder sichtbar.")
        self.traverse({'description': 'Status ändern'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("CdE-Mitglied", div='membership')
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.",
                            div='searchability')

    @as_users("farin")
    def test_iban_visibility(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'},
                      {'description': 'Bertålotta Beispiel'})
        self.assertTitle('Einzugsermächtigung Bertålotta Beispiel')
        # the iban should be visible for finance admins
        self.assertPresence("DE12 5001 0517 0648 4898 90", div='iban', exact=True)

        f = self.response.forms['generatetransactionform']
        self.submit(f)

        text = self.fetch_mail_content()
        # but in the notification mail there should be only the hidden iban version
        self.assertNotIn("DE12 5001 0517 0648 4898 90", text)
        self.assertIn("DE12 **** **** **** **98 90", text)

    @as_users("berta")
    def test_iban_non_visibility(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigung'})
        self.assertTitle('Einzugsermächtigung Bertålotta Beispiel')
        # the full iban should not be visible for non-finance admins ...
        self.assertNonPresence("DE12 5001 0517 0648 4898 90")
        # ... only a hidden form should be shown
        self.assertPresence("DE12 **** **** **** **98 90", div='iban', exact=True)

    @as_users("farin")
    def test_double_lastschrift_revoke(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'},
                      {'description': 'Bertålotta Beispiel'},)
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        self.assertPresence("42,23 €", div='amount', exact=True)
        self.get("/cde/user/2/lastschrift/create")
        f = self.response.forms['createlastschriftform']
        f['amount'] = 25
        f['iban'] = "DE12 5001 0517 0648 4898 90"
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Mehrere aktive Einzugsermächtigungen sind unzulässig.",
            div="notifications")

    @as_users("paul", "quintus")
    def test_create_user(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Nutzer anlegen'})
        self.assertTitle("Neues Mitglied anlegen")
        data = PERSONA_TEMPLATE.copy()
        f = self.response.forms['newuserform']
        self.assertEqual(f['country'].value, self.conf["DEFAULT_COUNTRY"])
        self.assertIsNone(
            self.response.lxml.get_element_by_id('input_checkbox_is_searchable').value)
        self.assertFalse(
            self.response.lxml.get_element_by_id('input_checkbox_trial_member').checked)
        f['is_searchable'].checked = True
        f['is_member'].checked = True
        f['trial_member'].checked = True
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("Dr. Zelda Zeruda-Hime von und zu",
                            div='personal-information')
        self.assertPresence("05.06.1987", div='personal-information')
        self.assertPresence("+49 (30) 456790", div='contact-telephone',
                            exact=True)
        self.assertPresence("+49 (160) 2047", div='contact-mobile', exact=True)
        self.assertPresence("12345 Lynna", div='address')
        self.assertPresence("Ligusterweg 4", div='address2')
        self.assertPresence("CdE-Mitglied (Probemitgliedschaft)",
                            div='membership')
        self.assertPresence("Daten sind für andere Mitglieder sichtbar.",
                            div='searchability')
        self.assertCheckbox(True, "paper_expuls_checkbox")
        mail = self.fetch_mail()[0]
        self.logout()
        link = self.fetch_link(mail)
        assert link is not None
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

    @as_users("paul", "quintus")
    def test_create_archive_user(self) -> None:
        self.check_create_archive_user('cde', PERSONA_TEMPLATE.copy())

    @as_users("farin")
    def test_lastschrift_index(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn("generatetransactionform2", self.response.forms)

    @as_users("farin", "berta")
    def test_lastschrift_show(self) -> None:
        if self.user_in("berta"):
            self.traverse({'description': 'Mitglieder'},
                          {'description': 'CdE-Mitglied suchen'})
            f = self.response.forms['membersearchform']
            f['qval_family_name,birth_name'] = "Beispiel"
            self.submit(f)
        else:
            self.realm_admin_view_profile('berta', "cde")
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'description': 'Einzugsermächtigung'})
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        if self.user_in("farin"):
            self.assertIn("revokeform", self.response.forms)
            self.assertIn("receiptform3", self.response.forms)
        else:
            self.assertNotIn("revokeform", self.response.forms)
            self.assertNotIn("receiptform3", self.response.forms)

    def test_membership_lastschrift_revoke(self) -> None:
        self.login(USER_DICT["vera"])
        self.admin_view_profile('berta')
        self.assertPresence("Einzugsermächtigung", div="balance")
        self.assertNonPresence("Neue Einzugsermächtigung", div="balance")
        self.traverse({'description': 'Status ändern'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertPresence("Lastschriftmandat widerrufen.",
                            div="notifications")
        self.assertNonPresence("Einzugsermächtigung", div="balance")
        self.logout()
        self.login(USER_DICT["farin"])
        self.get('/cde/user/2/lastschrift')
        self.assertPresence("Keine aktive Einzugsermächtigung")

    @as_users("farin")
    def test_lastschrift_subject_limit(self) -> None:
        self.admin_view_profile('anton')
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms["changedataform"]
        f["given_names"] = "Anton Armin ÄÖÜ"
        self.submit(f)
        self.traverse({'description': 'Neue Einzugsermächtigung …'},
                      {'description': 'Anlegen'})
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

    @storage
    @as_users("farin")
    def test_lastschrift_generate_transactions(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNonPresence("Keine zu bearbeitenden Lastschriften für "
                               "dieses Semester.")
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.", div='open-dd', exact=True)
        f = self.response.forms['downloadsepapainform']
        g = self.response.forms['generatetransactionsform']
        self.submit(f, check_notification=False)
        with open(self.testfile_dir / "sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)
        self.submit(g)
        self.assertPresence("1 Lastschriften initialisiert.",
                            div="notifications")
        self.assertPresence("Keine zu bearbeitenden Lastschriften für dieses "
                            "Semester.", div='open-dd-authorization',
                            exact=True)
        self.assertNonPresence("Aktuell befinden sich keine Einzüge in der "
                               "Schwebe.")

    @storage
    @as_users("farin")
    def test_lastschrift_generate_single_transaction(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNonPresence("Keine zu bearbeitenden Lastschriften für "
                               "dieses Semester.")
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.", div='open-dd', exact=True)
        f = self.response.forms['downloadsepapainform2']
        g = self.response.forms['generatetransactionform2']
        self.submit(f, check_notification=False)
        with open(self.testfile_dir / "sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)
        self.submit(g)
        self.assertPresence("1 Lastschriften initialisiert.",
                            div="notifications")
        self.assertPresence("Keine zu bearbeitenden Lastschriften für dieses "
                            "Semester.", div='open-dd-authorization',
                            exact=True)
        self.assertNonPresence("Aktuell befinden sich keine Einzüge in der "
                               "Schwebe.")

    @as_users("farin")
    def test_lastschrift_transaction_rollback(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'description': 'Einzugsermächtigungen'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [1001]
        self.submit(f, button="success")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        # self.traverse({'href': '^/$'})
        self.admin_view_profile('berta')
        self.assertPresence("17,50 €")
        self.traverse({'description': 'Einzugsermächtigung'})
        f = self.response.forms['transactionrollbackform1001']
        self.submit(f)
        self.assertPresence("Keine aktive Einzugsermächtigung – Anlegen",
                            div='active-permit', exact=True)
        self.traverse({'href': '^/$'})
        self.admin_view_profile('berta')
        self.assertPresence("12,50 €")

    @as_users("farin")
    def test_lastschrift_transaction_cancel(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'description': 'Einzugsermächtigungen'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [1001]
        self.submit(f, button="cancelled")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn('generatetransactionform2', self.response.forms)
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.", div='open-dd', exact=True)

    @as_users("farin")
    def test_lastschrift_transaction_failure(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'description': 'Einzugsermächtigungen'})
        f = self.response.forms['finalizationform']
        f['transaction_ids'] = [1001]
        self.submit(f, button="failure")
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertPresence("Aktuell befinden sich keine Einzüge in der "
                            "Schwebe.", div='open-dd', exact=True)

    @as_users("farin")
    def test_lastschrift_skip(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigungen'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['skiptransactionform2']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.forms)
        self.assertNotIn('transactionsuccessform', self.response.forms)

    @as_users("farin")
    def test_lastschrift_create(self) -> None:
        self.admin_view_profile('charly')
        self.traverse({'description': 'Neue Einzugsermächtigung …'})
        self.assertPresence("Keine aktive Einzugsermächtigung – Anlegen",
                            div='active-permit', exact=True)
        self.traverse({'description': 'Anlegen'})
        self.assertTitle("Neue Einzugsermächtigung (Charly C. Clown)")
        self.traverse({'description': "Einzugsermächtigungen"},
                      {'description': "Neue Einzugsermächtigung"})
        f = self.response.forms['createlastschriftform']
        self.assertTitle("Neue Einzugsermächtigung")
        f['persona_id'] = "DB-3-5"
        f['amount'] = "123.45"
        f['iban'] = "DE26370205000008068900"
        f['notes'] = "grosze Siebte: Take on me"
        self.submit(f)
        self.assertTitle("Einzugsermächtigung Charly C. Clown")
        self.assertIn("revokeform", self.response.forms)
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("123.45", f['amount'].value)
        self.assertEqual("grosze Siebte: Take on me", f['notes'].value)

    @as_users("farin")
    def test_lastschrift_change(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'description': 'Einzugsermächtigung'},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("42.23", f['amount'].value)
        self.assertEqual('Dagobert Anatidae', f['account_owner'].value)
        self.assertEqual('reicher Onkel', f['notes'].value)
        f['amount'] = "27.16"
        f['account_owner'] = "Dagobert Beetlejuice"
        f['notes'] = "reicher Onkel (neu verheiratet)"
        self.submit(f)
        self.assertPresence("27,16 €", div='amount', exact=True)
        self.assertPresence('Dagobert Beetlejuice', div='account-holder',
                            exact=True)
        self.assertPresence('reicher Onkel (neu verheiratet)', div='notes',
                            exact=True)

    @as_users("farin")
    def test_lastschrift_receipt(self) -> None:
        self.admin_view_profile('berta')
        self.traverse({'description': 'Einzugsermächtigung'})
        self.assertTitle("Einzugsermächtigung Bertålotta Beispiel")
        f = self.response.forms['receiptform3']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("vera")
    def test_lastschrift_subscription_form(self) -> None:
        # as user
        self.get("/cde/lastschrift/form/download")
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    def test_lastschrift_subscription_form_anonymous(self) -> None:
        self.get("/cde/lastschrift/form/download")
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("vera", "charly")
    def test_lastschrift_subscription_form_fill(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Einzugsermächtigung'})
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("inga")
    def test_lastschrift_subscription_form_fill_fail(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Weitere Informationen'},
                      {'description': 'dieses Formular'})
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        f["db_id"] = "DB-1-8"
        f["postal_code"] = "ABC"
        f["iban"] = "DE12500105170648489809"
        self.submit(f)
        self.assertPresence("Checksumme stimmt nicht")
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Ungültige Checksumme")

    def test_lastschrift_subscription_form_fill_anonymous(self) -> None:
        self.get("/cde/lastschrift/form/fill")
        self.assertTitle("Einzugsermächtigung ausfüllen")
        f = self.response.forms['filllastschriftform']
        f["iban"] = "DE12500105170648489890"
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @storage
    @as_users("vera")
    def test_batch_admission(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Massenaufnahme'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        with open(self.testfile_dir / "batch_admission.csv") as datafile:
            tmp = datafile.read()
            placeholder_birthday = "03.10.9999"
            wandering_birthday = f"03.10.{now().year - 5}"
            unproblematic_birthday = f"03.10.{now().year - 15}"
            tmp = tmp.replace(placeholder_birthday, wandering_birthday)
            f['accounts'] = tmp
        self.submit(f, check_notification=False)

        # first round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.get_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(f" Zeile {i}:")
            output.append(head)
        head, _ = content.split("Erneut validieren")
        output.append(head)
        expectation: Tuple[Tuple[str, ...], ...] = (
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
            (r"birthday:\W*Ungültige Eingabe für ein Datum.",),
            (r"postal_code:\W*Ungültige Postleitzahl.",),
            (r"Zeilen 13 und 14 sind identisch.",),
            (r"Zeilen 13 und 14 sind identisch.",
             r"pcourse_id\W*Lediglich nach Titel zugeordnet."),
            (r"pevent_id\W*Nur unscharfer Treffer.",
             r"pcourse_id\W*Nur unscharfer Treffer.",
             r"birthday\W*Person ist jünger als 10 Jahre.",),
            (r"persona:\W*Ähnlicher Account gefunden.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        for i in range(0, 15):
            if i in (1, 7):
                exp = str(LineResolutions.create.value)
            else:
                exp = ''
            self.assertEqual(exp, f[f'resolution{i}'].value)
        inputdata = f['accounts'].value
        f['resolution0'] = LineResolutions.skip.value
        f['resolution2'] = LineResolutions.skip.value
        f['resolution3'] = LineResolutions.skip.value
        f['resolution4'] = LineResolutions.renew_and_update.value
        f['doppelganger_id4'] = '2'
        f['resolution5'] = LineResolutions.update.value
        f['doppelganger_id5'] = '4'
        f['resolution6'] = LineResolutions.renew_and_update.value
        f['doppelganger_id6'] = '5'
        inputdata = inputdata.replace("pa99", "pa14")
        inputdata = inputdata.replace(
            "Doomed course from hell", "Swish -- und alles ist gut")
        inputdata = inputdata.replace("31.02.1981", "21.02.1981")
        inputdata = inputdata.replace("00000", "07751")
        inputdata = inputdata.replace("fPingst", "Pfingst")
        inputdata = inputdata.replace("wSish", "Swish")
        f['is_orga9'] = True
        inputdata = inputdata.replace(wandering_birthday, unproblematic_birthday)
        f['resolution12'] = LineResolutions.skip.value
        f['resolution13'] = LineResolutions.skip.value
        f['resolution15'] = LineResolutions.renew_and_update.value
        f['is_instructor15'] = True
        f['doppelganger_id15'] = '10'
        f['accounts'] = inputdata
        self.submit(f, check_notification=False)

        # second round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.get_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(f" Zeile {i}:")
            output.append(head)
        head, _ = content.split("Erneut validieren")
        output.append(head)
        expectation: Tuple[Tuple[str, ...], ...] = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            (r"pevent_id:\W*Teilnahme bereits erfasst.",),
            tuple(),
            (r"doppelganger:\W*Accountzusammenführung mit nicht-CdE Account.",),
            tuple(),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            (r"Eintrag geändert.",),
            tuple(),
            tuple(),
            (r"Eintrag geändert.",),
            (r"doppelganger:\W*Accountzusammenführung mit nicht-CdE Account.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertTrue(re.search(piece, out))
        nonexpectation: Tuple[Tuple[str, ...], ...] = (
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
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertFalse(re.search(piece, out))

        inputdata = f['accounts'].value
        inputdata = inputdata.replace('"1a";"Beispiel";"Bertålotta"',
                                      '"Ω";"Beispiel";"Bertålotta"')
        f['accounts'] = inputdata
        f['resolution4'] = LineResolutions.renew_and_update.value
        f['doppelganger_id4'] = '2'
        f['resolution6'] = LineResolutions.create.value
        f['resolution8'] = LineResolutions.create.value
        f['resolution9'] = LineResolutions.create.value
        f['resolution10'] = LineResolutions.create.value
        f['resolution11'] = LineResolutions.create.value
        f['resolution14'] = LineResolutions.create.value
        self.submit(f, check_notification=False)

        # third round
        self.assertPresence("Erneut validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        self.assertEqual('', f['resolution4'].value)
        content = self.get_content()
        _, content = content.split(" Zeile 1:")
        output = []
        for i in range(2, 16):
            head, content = content.split(f" Zeile {i}:")
            output.append(head)
        head, _ = content.split("Erneut validieren")
        output.append(head)
        expectation: Tuple[Tuple[str, ...], ...] = (
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
        nonexpectation: Tuple[Tuple[str, ...], ...] = (
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
        f['resolution4'] = LineResolutions.renew_and_update.value
        f['doppelganger_id4'] = '2'
        f['resolution6'] = LineResolutions.renew_and_update.value
        self.assertEqual('False', f['finalized'].value)
        self.submit(f, check_notification=False)

        # fourth round
        self.assertPresence("Anlegen")
        self.assertNonPresence("Erneut validieren")
        f = self.response.forms['admissionform']
        self.assertEqual(str(LineResolutions.renew_and_update.value), f['resolution4'].value)
        self.assertEqual('True', f['finalized'].value)
        self.submit(f, check_notification=False)
        self.assertPresence("7 Accounts erstellt.", div="notifications")

        # validate
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.traverse({'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Willy Brandt")
        self.assertPresence("Gerhard Schröder", div='list-participants')
        self.assertPresence("Angela Merkel", div='list-participants')
        self.assertPresence("Gustav Heinemann (1a. Swish -- und alles ist gut) (Orga)",
                            div='list-participants')

        self.traverse({'description': 'Swish -- und alles ist gut'})
        self.assertPresence("Janis Jalapeño (Kursleiter)")

        self.traverse({'description': 'Angela Merkel'})
        self.assertPresence("0,00 €", div='balance')
        self.assertCheckbox(True, "paper_expuls_checkbox")
        self.assertPresence("CdE-Mitglied (Probemitgliedschaft)",
                            div="membership")

    @as_users("vera")
    def test_batch_admission_review(self) -> None:
        # check that we force a review if an existing data set is been upgraded
        data = (
            '"pa14";"1a";"Dino";"Daniel";"lustiger Titel";"";"";"1";"";"";"";"";"";"";"";"daniel@example.cde";"1.01.1900"\n'
            '"pa14";"1a";"Jalapeño";"Janis";"";"komischer Namenszusatz";"";"1";"";"Chilliallee 23";"56767";"Scoville";"";"+49 (5432) 321321";"";"janis@example.cde";"04.01.2001"'
        )

        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Massenaufnahme'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['accounts'] = data
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['resolution0'] = LineResolutions.update.value
        f['doppelganger_id0'] = "4"
        f['resolution1'] = LineResolutions.update.value
        f['doppelganger_id1'] = "10"
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        self.submit(f)

        # now, lets check the reviews exists
        self.traverse({"description": "Index"},
                      {"description": "Änderungen prüfen"})
        self.assertPresence("Daniel Dino")
        self.assertPresence("Janis")

        # take special care that no fields were silently updated during realm transition
        self.admin_view_profile("janis")
        self.assertNonPresence("komischer Namenszusatz", div='personal-information')
        self.admin_view_profile("daniel")
        self.assertPresence("19.02.1963", div='personal-information')
        self.assertPresence("Am Denkmal 91", div='address-information')

    @as_users("vera")
    def test_batch_admission_username_taken(self) -> None:
        # check that we do not allow to create an account with already taken mail adress
        data = ('"pa14";"1a";"Dino";"Daniel";"";"";"";"1";"";"";"";"";"";"";"";'
                '"daniel@example.cde";"19.02.1963"')

        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Massenaufnahme'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['accounts'] = data
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['resolution0'] = LineResolutions.create.value
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        # check a already taken mailadress is not a warning but an error, since
        # it would otherwise violate our postgres integrity
        self.assertPresence("Fehler persona: Emailadresse bereits vergeben.")
        f = self.response.forms['admissionform']
        f['resolution0'] = LineResolutions.update.value
        f['doppelganger_id0'] = "4"
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        # but updating a persona is ok
        self.assertNonPresence("Emailadresse bereits vergeben.")
        f = self.response.forms['admissionform']
        self.submit(f)

    @as_users("vera")
    def test_batch_admission_reset_finalized(self) -> None:
        # check that we reset the "finalized" parameter every time a new change comes up
        data = ["pa14", "1a", "Dino", "Daniel", "", "", "", "1", "", "", "", "", "", "",
                "", "daniel@example.cde", "19.02.1963"]

        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Nutzer verwalten'},
                      {'description': 'Massenaufnahme'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['accounts'] = ";".join(data)
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        f['resolution0'] = LineResolutions.skip.value
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        self.assertEqual('True', f['finalized'].value)
        # now change the data in the data field
        data[4] = "eine kleine Änderung"
        f['accounts'] = ";".join(data)
        self.submit(f, check_notification=False)

        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        self.assertEqual('False', f['finalized'].value)
        self.assertPresence("Warnung Eintrag geändert.")

    @storage
    @as_users("farin")
    def test_money_transfers(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Überweisungen eintragen'})
        self.assertTitle("Überweisungen eintragen")
        f = self.response.forms['transfersform']
        with open(self.testfile_dir / "money_transfers.csv") as datafile:
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
        expectation: Tuple[Tuple[str, ...], ...] = (
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
        self.assertPresence("Saldo: 151,09 €", div='saldo', exact=True)
        self.assertNonPresence("Validieren")
        f = self.response.forms['transfersform']
        self.assertTrue(f['checksum'].value)
        self.submit(f)
        self.assertPresence("4 Überweisungen gebucht. 1 neue Mitglieder.",
                            div="notifications")
        self.admin_view_profile("daniel")
        self.traverse({"description": "Änderungshistorie"})
        self.assertPresence("Guthabenänderung um 100,00 € auf 100,00 € "
                            "(Überwiesen am 17.03.2019)")
        self.admin_view_profile("ferdinand")
        self.traverse("Änderungshistorie")
        self.assertPresence("Guthabenänderung um 25,00 € auf 47,20 €"
                            " (Überwiesen am 15.03.2019)")
        self.assertPresence("Guthabenänderung um 13,75 € auf 60,95 €"
                            " (Überwiesen am 16.03.2019)")

        # Test for correctly applying duplicate transfer with same amount.
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Überweisungen eintragen'})
        self.assertTitle("Überweisungen eintragen")
        f = self.response.forms['transfersform']
        f['transfers'] = """"10";"DB-1-9";"Administrator";"Anton Armin A.";"15.03.2019"
"10";"DB-1-9";"Administrator";"Anton Armin A.";"16.03.2019"
""".strip()
        self.submit(f, check_notification=False)
        self.assertPresence("Mehrere Überweisungen für diesen Account"
                            " (Zeilen 1 und 2).")
        f = self.response.forms['transfersform']
        self.assertTrue(f['checksum'].value)
        self.submit(f)
        self.assertPresence("2 Überweisungen gebucht. 0 neue Mitglieder",
                            div="notifications")
        self.admin_view_profile("anton")
        self.traverse("Änderungshistorie")
        self.assertPresence("Guthabenänderung um 10,00 € auf 27,50 €"
                            " (Überwiesen am 15.03.2019)")
        self.assertPresence("Guthabenänderung um 10,00 € auf 37,50 €"
                            " (Überwiesen am 16.03.2019)")

    @as_users("farin")
    def test_money_transfers_regex(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Überweisungen eintragen'})
        self.assertTitle("Überweisungen eintragen")
        f = self.response.forms['transfersform']
        f['transfers'] = '"10";"DB-1-9";"Fiese[";"Zeichen{";"überall("'
        self.submit(f, check_notification=False)
        # Here the active regex chars where successfully neutralised

    @storage
    @as_users("farin")
    def test_money_transfers_file(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Überweisungen eintragen'})
        f = self.response.forms['transfersform']
        # This file has a newline at the end, which needs to be stripped or it
        # causes the checksum to differ and require a third round.

        with open(self.testfile_dir / "money_transfers_valid.csv", 'rb') as datafile:
            data = datafile.read().replace(b"\r", b"").replace(b"\n", b"\r\n")

        self.assertIn(b"\r\n", data)
        f['transfers_file'] = webtest.Upload(
            "money_transfers_valid.csv", data, "text/csv")
        self.submit(f, check_notification=False)
        f = self.response.forms['transfersform']
        self.submit(f)

    @as_users("farin")
    def test_money_transfer_low_balance(self) -> None:
        self.admin_view_profile("daniel")
        self.assertPresence("0,00 €", div='balance')
        self.assertNonPresence("CdE-Mitglied", div='membership')
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Überweisungen eintragen'})
        f = self.response.forms["transfersform"]
        f["transfers"] = "1.00;DB-4-3;Dino;Daniel D.;"
        self.submit(f, check_notification=False)
        f = self.response.forms["transfersform"]
        self.submit(f)
        self.admin_view_profile("daniel")
        self.assertNonPresence("CdE-Mitglied", div='membership')

    @prepsql(f"UPDATE core.changelog SET ctime ="
             f" '{now() - datetime.timedelta(days=365 * 2 + 1)}' WHERE persona_id = 18")
    @as_users("farin")
    def test_semester(self) -> None:
        link = {'description': 'Semesterverwaltung'}
        self.traverse({'description': 'Mitglieder'}, link)
        self.assertTitle("Semesterverwaltung")

        # 1.1 Payment Request
        self.assertPresence("Später zu erledigen.", div='eject-members')
        self.assertPresence("Später zu erledigen.", div='balance-update')
        self.assertPresence("Später zu erledigen.", div='next-semester')

        f = self.response.forms['billform']
        f['testrun'].checked = True
        self.submit(f)
        self.reload_and_check_form('billform', link)
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['billform']
        f['addresscheck'].checked = True
        self.submit(f)
        self.reload_and_check_form('ejectform', link)
        self.assertTitle("Semesterverwaltung")

        # 1.2 Remove Inactive Members
        self.assertPresence("Erledigt am", div='payment-request')
        self.assertPresence("8 E-Mails versandt", div='payment-request')
        self.assertPresence("Später zu erledigen.", div='balance-update')
        self.assertPresence("Später zu erledigen.", div='next-semester')

        self.assertPresence(
            "Derzeit haben 0 Mitglieder ein zu niedriges Guthaben "
            "(insgesamt 0,00 €, davon 0 mit einer aktiven Einzugsermächtigung)."
            " Zusätzlich gibt es 2 Probemitglieder.", div='eject-members')
        # Check error handling for bill
        self.submit(f, check_notification=False)
        self.assertPresence('Zahlungserinnerung bereits erledigt',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['ejectform']
        self.submit(f)
        self.reload_and_check_form('balanceform', link)
        self.assertTitle("Semesterverwaltung")

        # 1.3 Update Balances
        self.assertPresence("Erledigt am", div='payment-request')
        self.assertPresence("Erledigt am", div='eject-members')
        self.assertPresence("Später zu erledigen.", div='next-semester')

        self.assertPresence("Insgesamt 8 Mitglieder, 2 davon haben eine "
                            "Probemitgliedschaft", div='balance-update')
        # Check error handling for eject
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Bereinigung',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['balanceform']
        self.submit(f)
        self.reload_and_check_form('proceedform', link)
        self.assertTitle("Semesterverwaltung")

        # 1.4 Next Semester
        self.assertPresence("Erledigt am", div='payment-request')
        self.assertPresence("Erledigt am", div='eject-members')
        self.assertPresence("Erledigt am", div='balance-update')

        self.assertPresence("Semester Nummer 43", div='current-semester')
        # Check error handling for balance
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Guthabenaktualisierung',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedform']
        self.submit(f)
        self.reload_and_check_form('billform', link)
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 44", div='current-semester')

        # Check error handling for proceed
        self.submit(f, check_notification=False)
        self.assertPresence('Falscher Zeitpunkt für Beendigung des Semesters',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        # 2.1 Payment Request
        f = self.response.forms['billform']
        self.submit(f)
        self.reload_and_check_form('ejectform', link)
        self.assertTitle("Semesterverwaltung")

        # 2.2 Remove Inactive Members
        self.assertPresence(
            "Derzeit haben 3 Mitglieder ein zu niedriges Guthaben "
            "(insgesamt 2,44 €, davon 0 mit einer aktiven Einzugsermächtigung)."
            " Zusätzlich gibt es 0 Probemitglieder.", div='eject-members')

        f = self.response.forms['ejectform']
        self.submit(f)
        self.reload_and_check_form('balanceform', link)
        self.assertTitle("Semesterverwaltung")

        # 2.3 Update Balances
        self.assertPresence("Insgesamt 5 Mitglieder, 0 davon haben eine "
                            "Probemitgliedschaft", div='balance-update')

        f = self.response.forms['balanceform']
        self.submit(f)
        self.reload_and_check_form('proceedform', link)
        self.assertTitle("Semesterverwaltung")

        # 2.4 Next Semester
        self.assertPresence("Semester Nummer 44", div='current-semester')

        f = self.response.forms['proceedform']
        self.submit(f)
        self.reload_and_check_form('billform', link)
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("Semester Nummer 45", div='current-semester')
        self.assertIn('billform', self.response.forms)

        # Verify Log
        self.traverse({'description': 'CdE-Log'})
        self.assertTitle("CdE-Log [1–12 von 12]")
        self.assertPresence("1 E-Mails versandt.", div="2-1002")
        self.assertPresence("0 inaktive Mitglieder gestrichen.", div="3-1003")
        self.assertPresence("1 Accounts archiviert.", div="4-1004")
        self.assertPresence("2 Probemitgliedschaften beendet", div="5-1005")
        self.assertPresence("15.00 € Guthaben abgebucht.", div="5-1005")

        self.assertPresence("3 inaktive Mitglieder gestrichen.", div="9-1009")
        self.assertPresence("0 Probemitgliedschaften beendet", div="11-1011")
        self.assertPresence("12.50 € Guthaben abgebucht.", div="11-1011")

    @as_users("farin")
    def test_expuls(self) -> None:
        link = {'description': 'Semesterverwaltung'}
        self.traverse({'description': 'Mitglieder'}, link)
        self.assertTitle("Semesterverwaltung")

        # Address Check
        self.assertPresence("Später zu erledigen.", div='expuls-next')
        f = self.response.forms['addresscheckform']
        f['testrun'].checked = True
        self.submit(f)
        self.reload_and_check_form('addresscheckform', link)
        self.assertTitle("Semesterverwaltung")

        self.assertPresence("Später zu erledigen.", div='expuls-next')
        f = self.response.forms['addresscheckform']
        self.submit(f)
        self.reload_and_check_form('proceedexpulsform', link)
        self.assertTitle("Semesterverwaltung")

        # Next exPuls
        self.assertPresence("Erledigt am", div='expuls-address')
        self.assertPresence("exPuls trägt die Nummer 42", div='expuls-number')
        # Check error handling for addresscheck
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage bereits erledigt',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        self.reload_and_check_form('addresscheckform', link)
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 43", div='expuls-number')

        # No Address-Check
        f = self.response.forms['noaddresscheckform']
        self.submit(f)
        self.reload_and_check_form('proceedexpulsform', link)
        self.assertTitle("Semesterverwaltung")

        # Next exPuls
        self.assertPresence("Erledigt am", div='expuls-address')
        self.assertPresence("exPuls trägt die Nummer 43", div='expuls-number')
        # Check error handling for noaddresscheck
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage bereits erledigt',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        self.reload_and_check_form('addresscheckform', link)
        self.assertTitle("Semesterverwaltung")
        self.assertPresence("exPuls trägt die Nummer 44", div='expuls-number')
        self.assertIn('addresscheckform', self.response.forms)
        # Check error handling for proceedexpuls
        self.submit(f, check_notification=False)
        self.assertPresence('Adressabfrage noch nicht erledigt',
                            div='notifications')
        self.assertTitle("Semesterverwaltung")

        # Verify Log
        self.traverse({'description': 'CdE-Log'})
        f = self.response.forms['logshowform']
        f['codes'] = [const.CdeLogCodes.expuls_addresscheck.value,
                      const.CdeLogCodes.expuls_addresscheck_skipped.value,
                      const.CdeLogCodes.expuls_advance.value]
        self.submit(f)
        self.assertTitle("CdE-Log [1–4 von 4]")
        f = self.response.forms['logshowform']
        f['codes'] = [const.CdeLogCodes.expuls_advance.value]
        self.submit(f)
        self.assertTitle("CdE-Log [1–2 von 2]")
        f = self.response.forms['logshowform']
        f['codes'] = [const.CdeLogCodes.expuls_addresscheck.value]
        self.submit(f)
        self.assertTitle("CdE-Log [1–1 von 1]")
        f = self.response.forms['logshowform']
        f['codes'] = [const.CdeLogCodes.expuls_addresscheck_skipped.value]
        self.submit(f)
        self.assertTitle("CdE-Log [1–1 von 1]")

    @as_users("vera")
    def test_institutions(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Organisationen verwalten'})
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertEqual("Disco des Ehemaligen", f['title_2'].value)
        self.assertNotIn("title_3", f.fields)
        f['create_-1'].checked = True
        f['title_-1'] = "Bildung und Begabung"
        f['shortname_-1'] = "BuB"
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Club der Ehemaligen", f['title_1'].value)
        self.assertEqual("Disco des Ehemaligen", f['title_2'].value)
        self.assertEqual("Bildung und Begabung", f['title_1001'].value)
        f['title_1'] = "Monster Academy"
        f['shortname_1'] = "MA"
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertEqual("Disco des Ehemaligen", f['title_2'].value)
        self.assertEqual("Bildung und Begabung", f['title_1001'].value)
        f['delete_1001'].checked = True
        self.submit(f)
        self.assertTitle("Organisationen der verg. Veranstaltungen verwalten")
        f = self.response.forms['institutionsummaryform']
        self.assertEqual("Monster Academy", f['title_1'].value)
        self.assertEqual("Disco des Ehemaligen", f['title_2'].value)
        self.assertNotIn("title_1001", f.fields)

    @as_users("berta")
    def test_list_past_events(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")

        # Overview
        self.assertPresence("PfingstAkademie 2014 (CdE)", div='events-2014')
        self.assertPresence("Geburtstagsfete (DdE)", div='events-2019')
        self.assertPresence("Übersicht", div='navigation')
        self.assertPresence("CdE", div='navigation')
        self.assertPresence("DdE", div='navigation')

        # Institution CdE
        self.traverse({'description': '^CdE$'})
        self.assertPresence("PfingstAkademie 2014", div='events-2014')
        self.assertNonPresence("Geburtstagsfete")
        self.assertNonPresence("2019")
        self.assertPresence("Übersicht", div='navigation')
        self.assertPresence("CdE", div='navigation')
        self.assertPresence("DdE", div='navigation')

        # Institution DdE
        self.traverse({'description': '^DdE$'})
        self.assertPresence("Geburtstagsfete", div='events-2019')
        self.assertNonPresence("PfingstAkademie")
        self.assertNonPresence("2014")
        self.assertPresence("Übersicht", div='navigation')
        self.assertPresence("CdE", div='navigation')
        self.assertPresence("DdE", div='navigation')

    @as_users("vera")
    def test_list_past_events_admin(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")

        # Overview
        self.assertPresence("PfingstAkademie 2014 [pa14] (CdE) 2 Kurse, 5 "
                            "Teilnehmer", div='events-2014')
        self.assertPresence(
            "Geburtstagsfete [gebi] (DdE) 0 Kurse, 0 Teilnehmer",
            div='events-2019')

        # Institution CdE
        self.traverse({'description': '^CdE$'})
        self.assertPresence("PfingstAkademie 2014 [pa14] 2 Kurse, 5 "
                            "Teilnehmer", div='events-2014')
        self.assertNonPresence("Geburtstagsfete")

        # Institution DdE
        self.traverse({'description': '^DdE$'})
        self.assertPresence("Geburtstagsfete [gebi] 0 Kurse, 0 Teilnehmer",
                            div='events-2019')
        self.assertNonPresence("PfingstAkademie")

    @as_users("charly", "inga")
    def test_show_past_event_course(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.traverse({'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Club der Ehemaligen", div='institution',
                            exact=True)
        self.assertPresence("Great event!", div='description', exact=True)
        self.assertPresence("1a. Swish -- und alles ist gut",
                            div='list-courses')
        self.traverse({'description': 'Swish -- und alles ist gut'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Ringelpiez mit anfassen.", div='description',
                            exact=True)

    @as_users("vera", "berta", "charly", "ferdinand", "inga")
    def test_show_past_event_gallery(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.traverse({'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        if self.user_in(22):
            self.assertPresence(
                "Du bist kein Teilnehmer dieser vergangenen Veranstaltung und "
                "kannst diesen Link nur in Deiner Eigenschaft als Admin sehen.",
                div='gallery-admin-info')
        else:
            self.assertNonPresence(
                "Du bist kein Teilnehmer dieser vergangenen Veranstaltung und "
                "kannst diesen Link nur in Deiner Eigenschaft als Admin sehen.")
        # inga is no participant nor admin
        if self.user_in(9):
            self.assertNonPresence("Mediensammlung "
                                   "https://pa14:secret@example.cde/pa14/")
        else:
            self.assertPresence(
                "Mediensammlung https://pa14:secret@example.cde/pa14/",
                div='gallery-link')

    @as_users("vera", "berta", "charly", "garcia", "inga")
    def test_show_past_event_privacy(self) -> None:

        def _traverse_back() -> None:
            self.traverse({'description': 'Mitglieder'},
                          {'description': 'Verg. Veranstaltungen'},
                          {'description': 'PfingstAkademie 2014'})

        _traverse_back()
        self.assertTitle("PfingstAkademie 2014")
        # Check list privacy
        # non-searchable non-participants can not see anything interesting
        if self.user_in("garcia"):
            self.assertPresence("5 Teilnehmer", div='count-extra-participants')
            self.assertNonPresence("Bertå")
            self.assertNonPresence("Ferdinand")
        else:
            self.assertNonPresence("5 Teilnehmer")
            self.assertPresence("Bertå", div='list-participants')
            self.assertPresence("Ferdinand", div='list-participants')

        # non-searchable users are only visible to admins and participants
        if self.user_in("berta", "charly", "vera"):
            # members and participants
            self.assertPresence("Charly", div='list-participants')
            self.assertPresence("Emilia", div='list-participants')
            self.assertNonPresence("weitere")
            # no links are displayed to non-searchable users
            if not self.user_in("charly"):
                # searchable member
                self.traverse({'description': 'Ferdinand F. Findus'})
                _traverse_back()
            else:
                self.assertNoLink('/core/persona/2/show')
                self.assertNoLink('/core/persona/5/show')
                self.assertNoLink('/core/persona/6/show')
        else:
            self.assertNonPresence("Charly")
            self.assertNonPresence("Emilia")
            if not self.user_in("garcia"):
                self.assertPresence("2 weitere", div='count-extra-participants')

        # links to non-searchable users are only displayed for admins
        if self.user_in("vera"):
            # admin
            self.traverse({'description': 'Charly C. Clown'})
            _traverse_back()
            self.traverse({'description': 'Emilia E. Eventis'})
            _traverse_back()
        else:
            # normal members
            self.assertNoLink('/core/persona/5/show')
            if not self.user_in("charly"):
                self.assertNoLink('/core/persona/3/show')

    @as_users("daniel")
    def test_show_past_event_unprivileged(self) -> None:
        self.traverse({'description': 'Mitglieder'})
        self.assertNoLink('cde/past/event/list')
        self.get("/cde/past/event/list", status=403)
        self.get("/cde/past/event/1/show", status=403)

    @as_users("berta", "charly")
    def test_show_past_event_own_link(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        self.traverse({'description': '{} {}'.format(self.user['given_names'],
                                                     self.user['family_name'])})

    @as_users("anton", "charly", "garcia", "inga")
    def test_show_past_event_orgas(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'FingerAkademie 2020'})
        self.assertTitle("FingerAkademie 2020")
        self.assertPresence("Ferdinand F. Findus", div="orgas")
        if self.user_in("inga"):
            # no patricipant, but searchable.
            self.assertPresence("und 2 weitere", div="orgas")
            self.assertNonPresence("Charly")
            self.assertNonPresence("Emilia")
            self.assertNonPresence("Garcia", div="orgas")
            self.traverse({'description': 'Ferdinand'})
        else:
            self.assertPresence("Charly C. Clown", div="orgas")
            self.assertPresence("Emilia E. Eventis", div="orgas")
            self.assertPresence("Ferdinand F. Findus", div="orgas")
            self.assertNonPresence("Garcia", div="orgas")
            self.assertNonPresence("weitere")
            if self.user_in("anton"):
                self.traverse({'description': 'Emilia'})
            else:
                # requesting user not searchable / no member
                self.assertNoLink(content="Emilia")
                self.assertNoLink(content="Ferdindand")
                if not self.user_in("charly"):
                    # requested user not searchable.
                    self.assertNoLink(content="Charly")

    @as_users("vera")
    def test_past_event_addresslist(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Bertålotta Beispiel", div='list-participants')
        self.assertPresence("Charly C. Clown", div='list-participants')
        self.assertPresence("Emilia E. Eventis", div='list-participants')
        self.assertPresence("Ferdinand F. Findus", div='list-participants')
        self.assertPresence("Akira Abukara", div='list-participants')

        save = self.response
        self.response = save.click(href='/cde/past/event/1/download',
                                   description='Dokuteam-Adressliste')

        class dialect(csv.Dialect):
            delimiter = ';'
            quotechar = '"'
            doublequote = False
            escapechar = '\\'
            lineterminator = '\n'
            quoting = csv.QUOTE_MINIMAL

        result = list(csv.DictReader(self.response.text.split('\n'),
                                     dialect=dialect))
        given_names = {e["given_names"] for e in result}
        expectation = {
            "Bertålotta", "Charly C.", "Emilia E.", "Ferdinand F.", "Akira"
        }
        self.assertEqual(expectation, given_names)

    @as_users("vera")
    def test_change_past_event(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'},
                      {'description': 'Bearbeiten'})
        self.assertTitle("PfingstAkademie 2014 bearbeiten")
        f = self.response.forms['changeeventform']
        f['title'] = "Link Academy"
        f['institution'] = 2
        f['description'] = "Ganz ohne Minderjährige."
        f['participant_info'] = "<https://zelda:hyrule@link.cde>"
        self.submit(f)
        self.assertTitle("Link Academy")
        self.assertPresence("Disco des Ehemaligen", div='institution')
        self.assertPresence("Ganz ohne Minderjährige.", div='description')
        self.assertPresence("https://zelda:hyrule@link.cde", div='gallery-link',
                            exact=True)

    @as_users("vera")
    def test_create_past_event(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'Verg. Veranstaltung anlegen'})
        self.assertTitle("Verg. Veranstaltung anlegen")
        f = self.response.forms['createeventform']
        f['title'] = "Link Academy II"
        f['shortname'] = "link"
        f['institution'] = 2
        f['description'] = "Ganz ohne Minderjährige."
        f['participant_info'] = "<https://zelda:hyrule@link.cde>"
        f['tempus'] = "1.1.2000"
        self.submit(f)
        self.assertTitle("Link Academy II")
        self.assertPresence("link", div='shortname')
        self.assertPresence("Disco des Ehemaligen", div='institution')
        self.assertPresence("Ganz ohne Minderjährige.", div='description')
        self.assertPresence("https://zelda:hyrule@link.cde", div='gallery-link',
                            exact=True)

    @as_users("vera")
    def test_create_past_event_with_courses(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'Verg. Veranstaltung anlegen'})
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
        self.assertPresence("link", div='shortname')
        self.assertPresence("Club der Ehemaligen", div='institution')
        self.assertPresence("Ganz ohne Minderjährige.", div='description')
        self.assertPresence("1. Hoola Hoop", div='list-courses')
        self.assertPresence("2. Abseilen", div='list-courses')
        self.assertPresence("3. Tretbootfahren", div='list-courses')

    @as_users("vera")
    def test_delete_past_event(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'})
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertPresence("PfingstAkademie 2014", div='events-2014')
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'})
        self.assertTitle("PfingstAkademie 2014")
        f = self.response.forms['deletepasteventform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("Vergangene Veranstaltungen")
        self.assertNonPresence("PfingstAkademie 2014")

    @as_users("vera")
    def test_change_past_course(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'},
                      {'description': 'Swish -- und alles ist gut'})
        self.assertPresence("Bertålotta Beispiel", div='list-participants')
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014) bearbeiten")
        f = self.response.forms['changecourseform']
        f['title'] = "Omph"
        f['description'] = "Loud and proud."
        self.submit(f)
        self.assertTitle("Omph (PfingstAkademie 2014)")
        self.assertPresence("Loud and proud.", div='description', exact=True)
        self.assertPresence("Bertålotta Beispiel", div='list-participants')

    @as_users("vera")
    def test_create_past_course(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'},
                      {'description': 'Kurs hinzufügen'})
        self.assertTitle("Kurs anlegen (PfingstAkademie 2014)")
        f = self.response.forms['createcourseform']
        f['nr'] = "42"
        f['title'] = "Abstract Nonsense"
        f['description'] = "Lots of arrows."
        self.submit(f)
        self.assertTitle("Abstract Nonsense (PfingstAkademie 2014)")
        self.assertPresence("Lots of arrows.", div='description')

    @as_users("vera")
    def test_delete_past_course(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'},
                      {'description': 'Kurs hinzufügen'})
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

    @as_users("vera")
    def test_participant_manipulation(self) -> None:
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'},
                      {'description': 'Swish -- und alles ist gut'})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Garcia")
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8, DB-33-7"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona_ids', "Einige dieser Nutzer existieren nicht.")
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8, DB-10-8"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'persona_ids',
            "Einige dieser Nutzer sind keine Veranstaltungsnutzer.")
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8, DB-8-6, DB-5-1, DB-3-5"
        f['is_orga'].checked = True
        f['is_instructor'].checked = True
        self.submit(f)

        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertPresence("Garcia G. Generalis", div='list-participants')
        self.assertPresence("Hades Hell", div='list-participants')

        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Garcia")

        f = self.response.forms['removeparticipantform3']
        self.submit(f)
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")
        self.assertNonPresence("Garcia")

        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Verg. Veranstaltungen'},
                      {'description': 'PfingstAkademie 2014'})
        self.assertNonPresence("Garcia")
        # See #1458
        self.assertNonPresence("Charly")
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8"
        f['is_orga'].checked = True
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertPresence("Garcia G. Generalis (Orga) ")
        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        self.assertTitle("PfingstAkademie 2014")
        self.assertNonPresence("Garcia")

    @as_users("farin", "inga")
    def test_member_stats(self) -> None:
        self.traverse("Mitglieder", "Mitglieder-Statistik")
        self.assertPresence("Mitglieder", div="cde-simple-stats")
        self.assertPresence("davon suchbar", div="cde-simple-stats")
        self.assertPresence("Inaktive Mitglieder", div="cde-simple-stats")
        self.assertPresence("Mitglieder nach Land",
                            div="complex-stats-members_by_country")
        self.assertPresence("Deutschland",
                            div="complex-stats-members_by_country")
        self.assertPresence("Japan",
                            div="complex-stats-members_by_country")
        self.assertNonPresence("DE")
        self.assertNonPresence("JP")
        self.assertPresence("Mitglieder nach Stadt",
                            div="complex-stats-members_by_city")
        self.assertNonPresence("Burokratia")
        self.assertNonPresence("Liliput")
        self.assertDivNotExists(div="year-stats-members_by_birthday-1")
        self.assertNonPresence("–", div="year-stats-members_by_birthday-1991")
        self.assertNonPresence("–", div="year-stats-members_by_birthday-2222")
        self.assertPresence("–", div="year-stats-members_by_birthday-2014")
        self.assertNonPresence("–", div="year-stats-members_by_first_event-2014")
        self.assertPresence("–", div="year-stats-members_by_first_event-2010")
        self.assertNonPresence("–", div="year-stats-unique_participants_per_year-2010")
        self.assertNonPresence("–", div="year-stats-unique_participants_per_year-2014")

    @as_users("vera")
    def test_past_log(self) -> None:
        # First: generate data
        logs = []

        # add new institution
        self.traverse({'description': 'Mitglieder'},
                      {'description': 'Organisationen verwalten'})
        f = self.response.forms['institutionsummaryform']
        f['create_-1'].checked = True
        f['title_-1'] = "East India Company advanced"
        f['shortname_-1'] = "EIC"
        self.submit(f)
        logs.append((1001, const.PastEventLogCodes.institution_created))

        # change institution
        f = self.response.forms['institutionsummaryform']
        f['title_1001'] = "East India Company"
        self.submit(f)
        logs.append((1002, const.PastEventLogCodes.institution_changed))

        # add new past event
        self.traverse({'description': 'Verg. Veranstaltungen'},
                      {'description': 'Verg. Veranstaltung anlegen'})
        f = self.response.forms['createeventform']
        f['title'] = "Piraten Arrrkademie"
        f['shortname'] = "Arrr"
        f['institution'] = 2
        f['description'] = "Alle Mann an Deck!"
        f['participant_info'] = "<https://piraten:schiff@ahoi.cde>"
        f['tempus'] = "1.1.2000"
        self.submit(f)
        logs.append((1003, const.PastEventLogCodes.event_created))

        # add new course
        self.traverse({'description': 'Kurs hinzufügen'})
        f = self.response.forms['createcourseform']
        f['nr'] = "3.1415"
        f['title'] = "...raten!"
        f['description'] = "Wir können nicht im Kreis fahren."
        self.submit(f)
        logs.append((1004, const.PastEventLogCodes.course_created))

        # change course
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changecourseform']
        f['title'] = "raten"
        self.submit(f)
        logs.append((1005, const.PastEventLogCodes.course_changed))

        # add participant (to course)
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8,DB-1-9"
        self.submit(f)
        logs.append((1006, const.PastEventLogCodes.participant_added))
        logs.append((1007, const.PastEventLogCodes.participant_added))

        # delete participant (from course)
        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        logs.append((1008, const.PastEventLogCodes.participant_removed))

        # delete course
        f = self.response.forms['deletecourseform']
        f['ack_delete'].checked = True
        self.submit(f)
        logs.append((1009, const.PastEventLogCodes.course_deleted))

        # add participant (to past event)
        f = self.response.forms['addparticipantform']
        f['persona_ids'] = "DB-7-8"
        self.submit(f)
        logs.append((1010, const.PastEventLogCodes.participant_added))

        # delete participant (from past event)
        f = self.response.forms['removeparticipantform7']
        self.submit(f)
        logs.append((1011, const.PastEventLogCodes.participant_removed))

        # change past event
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changeeventform']
        f['description'] = "Leider ins Wasser gefallen..."
        self.submit(f)
        logs.append((1012, const.PastEventLogCodes.event_changed))

        # delete past event
        # this deletes an other event, because deletion includes log codes
        self.traverse({'description': 'Verg. Veranstaltungen'},
                      {'description': 'Geburtstagsfete'})
        f = self.response.forms['deletepasteventform']
        f['ack_delete'].checked = True
        self.submit(f)
        logs.append((1013, const.PastEventLogCodes.event_deleted))

        # delete institution
        self.traverse({'description': 'Organisationen verwalten'})
        f = self.response.forms['institutionsummaryform']
        f['delete_1001'].checked = True
        self.submit(f)
        logs.append((1014, const.PastEventLogCodes.institution_deleted))

        # Now check it
        self.traverse({'description': 'Verg.-Veranstaltungen-Log'})
        self.log_pagination("Verg.-Veranstaltungen-Log", tuple(logs))
        self.assertPresence("Piraten Arrrkademie", div="4-1004")

    @as_users("farin")
    def test_cde_log(self) -> None:
        # First: generate data
        logs = []

        # Payment Request
        link = {'description': 'Semesterverwaltung'}
        self.traverse({'description': 'Mitglieder'}, link)
        f = self.response.forms['billform']
        self.submit(f)
        logs.append((1001, const.CdeLogCodes.semester_bill))
        logs.append((1002, const.CdeLogCodes.automated_archival_notification_done))

        # Remove Inactive Members
        self.reload_and_check_form('ejectform', link)
        f = self.response.forms['ejectform']
        self.submit(f)
        logs.append((1003, const.CdeLogCodes.semester_ejection))
        logs.append((1004, const.CdeLogCodes.automated_archival_done))

        # Update Balances
        self.reload_and_check_form('balanceform', link)
        f = self.response.forms['balanceform']
        self.submit(f)
        logs.append((1005, const.CdeLogCodes.semester_balance_update))

        # Next Semester
        self.reload_and_check_form('proceedform', link)
        f = self.response.forms['proceedform']
        self.submit(f)
        logs.append((1006, const.CdeLogCodes.semester_advance))

        # Payment Request with addresscheck
        self.reload_and_check_form('billform', link)
        f = self.response.forms['billform']
        f['addresscheck'].checked = True
        self.submit(f)
        logs.append((1007, const.CdeLogCodes.semester_bill_with_addresscheck))
        logs.append((1008, const.CdeLogCodes.automated_archival_notification_done))

        # exPuls with addresscheck
        self.reload_and_check_form('addresscheckform', link)
        f = self.response.forms['addresscheckform']
        self.submit(f)
        logs.append((1009, const.CdeLogCodes.expuls_addresscheck))

        # Next exPuls
        self.reload_and_check_form('proceedexpulsform', link)
        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        logs.append((1010, const.CdeLogCodes.expuls_advance))

        # exPuls without addresscheck
        self.reload_and_check_form('noaddresscheckform', link)
        f = self.response.forms['noaddresscheckform']
        self.submit(f)
        logs.append((1011, const.CdeLogCodes.expuls_addresscheck_skipped))

        # Next exPuls
        self.reload_and_check_form('proceedexpulsform', link)
        f = self.response.forms['proceedexpulsform']
        self.submit(f)
        logs.append((1012, const.CdeLogCodes.expuls_advance))

        # Now check it
        self.traverse({'description': "CdE-Log"})
        self.log_pagination("CdE-Log", tuple(logs))

    def test_finance_log(self) -> None:
        # First: generate data
        pass

        # Now check it
        self.login(USER_DICT['farin'])
        self.traverse({'href': '/cde/$'},
                      {'href': '/cde/finances'})
        self.assertTitle("Finanz-Log [1–2 von 2]")
        self.assertNonPresence("LogCodes")

    @as_users("vera")
    def test_changelog_meta(self) -> None:
        self.traverse({'description': 'Nutzerdaten-Log'})
        self.assertTitle("Nutzerdaten-Log [1–31 von 31]")
        f = self.response.forms['logshowform']
        f['persona_id'] = "DB-2-7"
        self.submit(f)
        self.assertTitle("Nutzerdaten-Log [1–1 von 1]")
        self.assertPresence("Bertålotta Beispiel")
