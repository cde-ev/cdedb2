#!/usr/bin/env python3

import datetime
import unittest
import urllib.parse

from cdedb.common import encode_parameter
from test.common import (
    as_users, USER_DICT, FrontendTest, ADMIN_VIEWS_COOKIE_NAME, admin_views)

# TODO Profilfoto


class TestPrivacyFrontend(FrontendTest):

    FIELD_TO_DIV = {
        "Name": 'personal-information', "Geburtsname": 'personal-information',
        "Geburtsdatum": 'personal-information',
        "Geschlecht": 'personal-information', "CdEDB-ID": 'account',
        "Account aktiv": 'account', "Bereiche": 'account',
        "Admin-Privilegien": 'account', "Admin-Notizen": 'account',
        "Gedruckter exPuls": 'paper-expuls',
        "Mitgliedschaft": 'cde-membership', "Guthaben": 'cde-membership',
        "Sichtbarkeit": 'cde-membership', "E-Mail": 'contact-information',
        "Telefon": 'contact-information', "Mobiltelefon": 'contact-information',
        "WWW": 'contact-information', "Adresse": 'address-information',
        "Zweitadresse": 'address-information',
        "Fachgebiet": 'additional', "Schule, Uni, …": 'additional',
        "Jahrgang, Matrikel, …": 'additional', "Interessen": 'additional',
        "Sonstiges": 'additional', "Verg. Veranstaltungen": 'past-events',
        "VCard": 'vcard'
    }

    ALL_FIELDS = set(FIELD_TO_DIV.keys())

    def _profile_base_view(self, inspected):
        expected = {"Name", "CdEDB-ID", "E-Mail"}
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        return expected

    def _profile_relative_admin_view(self, inspected):
        expected = {
            "Account aktiv", "Bereiche", "Admin-Privilegien", "Admin-Notizen"
        }
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        # actual username should be displayed
        self.assertPresence(inspected['username'], div='contact-email')
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_ml_admin_view(self, inspected):
        expected = set()
        checked = self._profile_relative_admin_view(inspected)
        return expected | checked

    def _profile_assembly_admin_view(self, inspected):
        expected = set()
        checked = self._profile_relative_admin_view(inspected)
        return expected | checked

    def _profile_event_context_view(self, inspected):
        expected = {
            "Geburtsdatum", "Geschlecht", "Telefon", "Mobiltelefon", "Adresse"
        }
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        # actual username should be displayed
        self.assertPresence(inspected['username'], div='contact-email')
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_event_admin_view(self, inspected):
        expected = set()
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        checked = self._profile_relative_admin_view(inspected)
        checked.update(self._profile_event_context_view(inspected))
        return expected | checked

    def _profile_cde_context_view(self, inspected):
        expected = {
            "Geburtsname", "Geburtsdatum", "Telefon", "Mobiltelefon", "WWW",
            "Adresse", "Zweitadresse", "Fachgebiet", "Schule, Uni, …",
            "Jahrgang, Matrikel, …", "Interessen", "Sonstiges",
            "Verg. Veranstaltungen", "VCard"
        }
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        checked = self._profile_base_view(inspected)
        # actual username should be displayed
        self.assertPresence(inspected['username'], div='contact-email')
        return expected | checked

    def _profile_cde_admin_view(self, inspected):
        expected = {
            "Geschlecht", "Mitgliedschaft", "Guthaben", "Sichtbarkeit",
            "Gedruckter exPuls"
        }
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        checked = self._profile_relative_admin_view(inspected)
        checked.update(self._profile_cde_context_view(inspected))
        return expected | checked

    def _profile_core_admin_view(self, inspected):
        # Core Admins should view all Fields. This is used, to test if any field
        # was forgotten to test
        checked = set()
        checked.update(self._profile_relative_admin_view(inspected))
        checked.update(self._profile_ml_admin_view(inspected))
        checked.update(self._profile_assembly_admin_view(inspected))
        checked.update(self._profile_event_admin_view(inspected))
        checked.update(self._profile_cde_admin_view(inspected))
        checked.update(self._profile_meta_admin_view(inspected))
        return checked

    def _profile_meta_admin_view(self, inspected):
        expected = {"Bereiche", "Account aktiv", "Admin-Privilegien", "E-Mail",
                    "Admin-Notizen"}
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        # actual username should be displayed
        self.assertPresence(inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_member_view(self, inspected):
        # Note that event context is no subset of this, because missing gender
        expected = set()
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        checked = self._profile_cde_context_view(inspected)
        return expected | checked

    def _profile_orga_view(self, inspected):
        expected = set()
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        checked = self._profile_event_context_view(inspected)
        return expected | checked

    def _profile_moderator_view(self, inspected):
        expected = set()
        # actual username should be displayed
        self.assertPresence(inspected['username'], div='contact-email')
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _profile_of_archived(self, inspected):
        expected = {
            "Account aktiv", "Bereiche", "Admin-Privilegien", "Admin-Notizen",
            "Gedruckter exPuls", "Guthaben", "Mitgliedschaft", "Geburtsname",
            "Geschlecht", "Geburtsdatum", "VCard"
        }
        for field in expected:
            self.assertPresence(field, div=self.FIELD_TO_DIV[field])
        # username should have been deleted via archiving
        self.assertEqual(None, inspected['username'])
        checked = self._profile_base_view(inspected)
        return expected | checked

    def _disable_searchability(self, user):
        """ To avoid gaining more viewing rights through being a member"""
        self.logout()
        self.login(USER_DICT['anton'])
        self.admin_view_profile(user)
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = False
        self.submit(f)
        self.logout()

    def show_user_link(self, persona_id):
        confirm_id = urllib.parse.quote_plus(self.app.app.encode_parameter(
            "core/show_user", "confirm_id", persona_id,
            persona_id=None, timeout=datetime.timedelta(hours=12)))
        return f'/core/persona/{persona_id}/show?confirm_id={confirm_id}'

    def test_profile_base_information(self):
        # non-searchable user views normal account
        case1 = {
            'viewer': USER_DICT['charly'],
            'inspected': USER_DICT['anton'],
        }
        # normal user views non-searchable account
        case2 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['charly'],
        }
        # normal user views non-member account
        case3 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['daniel'],
        }
        # normal user views inactive account
        case4 = {
            'viewer': USER_DICT['inga'],
            'inspected': USER_DICT['olaf'],
        }

        for case in [case1, case2, case3, case4]:
            self.login(case['viewer'])
            self.get(self.show_user_link(case['inspected']['id']))
            found = self._profile_base_view(case['inspected'])
            # The username must not be visible, although "Email" occurs as field
            self.assertNonPresence(case['inspected']['username'])
            for field in self.ALL_FIELDS - found:
                self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                       check_div=False)
            self.logout()

    @as_users("nina")
    def test_profile_as_ml_admin(self, user):
        # on ml only users, ml admins get full view
        inspected = USER_DICT['janis']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_ml_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                       check_div=False)

        # on other users, they get no special view ...
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # ... unless they see them as mailinglist associated. Then, they get the
        # same view as a moderator of that mailinglist.
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']) + "&ml_id=51")
        found = self._profile_moderator_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("viktor")
    def test_profile_as_assembly_admin(self, user):
        self._disable_searchability('werner')

        # on (assembly and ml) only users, assembly admins get full view
        self.login(user)
        inspected = USER_DICT['kalif']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_assembly_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("annika")
    def test_profile_as_event_admin(self, user):
        self._disable_searchability('annika')

        # on event but not cde users, event admins get full view
        self.login(user)
        inspected = USER_DICT['emilia']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_event_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # on other users, they get no special view ...
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # ... unless they see them as event associated. Then, they get the same
        # view as an orga of this event.
        self.get(self.show_user_link(inspected['id']) + "&event_id=1")
        found = self._profile_orga_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("quintus")
    def test_profile_as_cde_admin(self, user):
        # Quintus in not searchable.

        # on cde users, cde admins get full view ...
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_cde_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # ... even if they are not searchable
        self._disable_searchability('berta')
        self.login(user)
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_cde_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("paul")
    def test_profile_as_core_admin(self, user):
        self._disable_searchability('paul')

        # core admin gets full access to all users...
        self.login(user)
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_core_admin_view(inspected)
        self.assertEqual((self.ALL_FIELDS - found), set())

        # ... especially also on archived users.
        inspected = USER_DICT['hades']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_of_archived(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("martin")
    def test_profile_as_meta_admin(self, user):
        # meta admins get the same view for every user
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_meta_admin_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("inga")
    def test_profile_as_member(self, user):
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))

        # members got first an un-quoted view on a profile, showing the basics
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # they can decide to got an quoted closer look on a profile
        self.traverse({'description': 'Gesamtes Profil anzeigen'})
        found = self._profile_member_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("garcia")
    def test_profile_as_orga(self, user):
        # orgas get a closer view on users associated to their event
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']) + "&event_id=1")
        found = self._profile_orga_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # otherwise, they have no special privileges ...
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # ... especially also for (event but not cde) users
        # (in contrast to event admins)
        inspected = USER_DICT['emilia']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

    @as_users("janis")
    def test_profile_as_moderator(self, user):
        # moderators get a closer view on users associated to their mailinglist
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']) + "&ml_id=2")
        found = self._profile_moderator_view(inspected)
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # otherwise, they have no special privileges ...
        inspected = USER_DICT['berta']
        self.get(self.show_user_link(inspected['id']))
        found = self._profile_base_view(inspected)
        # The username must not be visible, although "Email" occurs as field
        self.assertNonPresence(inspected['username'])
        for field in self.ALL_FIELDS - found:
            self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                   check_div=False)

        # ... especially also for ml only users (in contrast to ml admins)
        # TODO this is actual not possible caused by our sample-data
        # inspected = USER_DICT['emilia']
        # self.get(self.show_user_link(inspected['id']))
        # found = self._profile_base_view(inspected)
        # # The username must not be visible, although "Email" occurs as field
        # self.assertNonPresence(inspected['username'])
        # for field in self.ALL_FIELDS - found:
        #     self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
        #                                        check_div=False)

    @as_users("annika", "inga", "nina", "quintus", "viktor")
    @admin_views("ml_mod", "ml_mod_cde", "ml_mod_event", "ml_mod_assembly",
                 "ml_mod_cdelokal")
    def test_profile_as_relevant_ml_admin(self, user):
        ml_admin = USER_DICT['nina']['id']
        all_ml = (
            (64, 'janis', 'nina'),  # public
            (65, 'janis', 'inga'),  # cdelokal
            (56, 'garcia', 'quintus'),  # team
            (9, 'garcia', 'annika'),  # event
            (5, 'kalif', 'viktor'),  # assembly
        )

        for ml_id, profile, admin in all_ml:
            inspected = USER_DICT[profile]
            self.get(
                self.show_user_link(inspected['id']) + f"&ml_id={ml_id}")
            if user['id'] == USER_DICT[admin]['id'] or user['id'] == ml_admin:
                found = self._profile_moderator_view(inspected)
            else:
                found = self._profile_base_view(inspected)
                # The username must not be visible, although "Email" occurs as
                # field
                self.assertNonPresence(inspected['username'])
            for field in self.ALL_FIELDS - found:
                self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                       check_div=False)

    @as_users("annika", "berta", "emilia", "janis", "kalif", "nina", "quintus",
              "paul", "rowena", "viktor")
    def test_profile_of_realm_user(self, user):

        def get_id(name: str) -> int:
            return USER_DICT[name]['id']

        cases = {
            'ml': {
                'inspected': USER_DICT['janis'],
                'access': {get_id(u) for u in ("janis", "nina", "paul")},
                'no_access': {
                    get_id(u) for u in ("annika", "quintus", "viktor", "berta",
                                        "kalif", "emilia", "rowena")},
            },
            'assembly': {
                'inspected': USER_DICT['kalif'],
                'access': {get_id(u) for u in ("kalif", "paul", "viktor")},
                'no_access': {
                    get_id(u) for u in ("annika", "nina", "quintus", "berta",
                                        "janis", "emilia", "rowena")},
            },
            'event': {
                'inspected': USER_DICT['emilia'],
                'access': {get_id(u) for u in ("emilia", "annika", "paul")},
                'no_access': {
                    get_id(u) for u in ("quintus", "nina", "viktor", "berta",
                                        "kalif", "janis", "rowena")},
            },
            'a_e': {
                'inspected': USER_DICT['rowena'],
                'access': {get_id(u) for u in ("rowena", "annika", "viktor",
                                               "paul")},
                'no_access': {
                    get_id(u) for u in ("quintus", "nina", "janis", "berta",
                                        "kalif", "emilia")},
            },
            'cde': {
                'inspected': USER_DICT['berta'],
                'access': {get_id(u) for u in ("berta", "quintus", "paul")},
                'no_access': {
                    get_id(u) for u in ("annika", "nina", "viktor", "emilia",
                                        "kalif", "janis", "rowena")},
            }
        }

        # now the actual testing
        for realm, case in cases.items():
            inspected = case['inspected']
            self.get(self.show_user_link(inspected['id']))
            if user['id'] in case['access']:
                # username is only visible on extended profile views
                self.assertPresence(inspected['username'], div='contact-email')
            elif user['id'] in case['no_access']:
                found = self._profile_base_view(inspected)
                # username must not be visible on base profiles
                self.assertNonPresence(inspected['username'])
                for field in self.ALL_FIELDS - found:
                    self.assertNonPresence(field, div=self.FIELD_TO_DIV[field],
                                           check_div=False)
            else:
                msg = "Forget {} in case {}.".format(user['given_names'], realm)
                raise RuntimeError(msg)

    def test_profile_of_disabled_user(self):
        # a disabled user should be viewable as an equal non-disabled user
        # TODO maybe add all above tests as subtests?
        self.skipTest("Test not yet implemented.")

    @as_users("ferdinand", "martin", "paul")
    def test_profile_of_archived_user(self, user):
        inspected = USER_DICT['hades']

        # they should be visible to core admins only ...
        if user == USER_DICT['paul']:
            self.get(self.show_user_link(inspected['id']))
        # ... not for any other admin type
        elif user in [USER_DICT['ferdinand'], USER_DICT['martin']]:
            self.get(self.show_user_link(inspected['id']), status="403 FORBIDDEN")

    @as_users("annika", "berta", "farin", "martin", "nina", "quintus", "paul",
              "viktor")
    def test_user_search(self, user):
        # users who should have access to the specific user search
        core = {
            USER_DICT['farin']['id'], USER_DICT['paul']['id']
        }
        archive = {
            USER_DICT['farin']['id'], USER_DICT['paul']['id']
        }
        cde = {
            USER_DICT['farin']['id'], USER_DICT['quintus']['id']
        }
        event = {
            USER_DICT['farin']['id'], USER_DICT['annika']['id']
        }
        ml = {
            USER_DICT['farin']['id'], USER_DICT['nina']['id']
        }
        assembly = {
            USER_DICT['farin']['id'], USER_DICT['viktor']['id']
        }

        if user['id'] in core:
            self.get('/core/search/user')
            self.assertTitle("Allgemeine Nutzerverwaltung")
        else:
            self.get('/core/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user['id'] in archive:
            self.get('/core/search/archiveduser')
            self.assertTitle("Archivsuche")
        else:
            self.get('/core/search/archiveduser', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user['id'] in core | cde:
            self.get('/cde/search/user')
            self.assertTitle("CdE-Nutzerverwaltung")
        else:
            self.get('/cde/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user['id'] in core | event:
            self.get('/event/search/user')
            self.assertTitle("Veranstaltungs-Nutzerverwaltung")
        else:
            self.get('/event/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user['id'] in core | ml:
            self.get('/ml/search/user')
            self.assertTitle("Mailinglisten-Nutzerverwaltung")
        else:
            self.get('/ml/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

        if user['id'] in core | assembly:
            self.get('/assembly/search/user')
            self.assertTitle("Versammlungs-Nutzerverwaltung")
        else:
            self.get('/assembly/search/user', status="403 FORBIDDEN")
            self.assertTitle("403: Forbidden")

    @as_users("anton")
    def test_member_search_result(self, user):
        # test berta is accessible
        self.traverse({'description': "Mitglieder"})
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "Berta"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")

        # first case: make berta not-searchable
        self.traverse({'href': '/core/persona/2/adminchange'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = False
        self.submit(f)

        self.traverse({'description': "Mitglieder"})
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "Berta"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Keine Mitglieder gefunden.")

        # second case: make berta searchable again ...
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        f = self.response.forms['changedataform']
        f['is_searchable'].checked = True
        self.submit(f)
        # ... and then non-member
        self.traverse({'href': '/core/persona/2/membership/change'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)

        self.traverse({'description': "Mitglieder"})
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "Berta"
        self.submit(f)
        self.assertTitle("CdE-Mitglied suchen")
        self.assertPresence("Keine Mitglieder gefunden.")

    @as_users("charly", "daniel", "garcia", "inga")
    def test_show_past_event(self, user):
        akira = "Akira Abukara"
        berta = "Bertålotta Beispie"
        charly = "Charly C. Clown"
        emilia = "Emilia E. Eventis"
        ferdinand = "Ferdinand F. Findus"
        # non-members should not have access if they are no cde admin
        if user == USER_DICT['daniel']:
            self.get('/cde/past/event/list', status="403 FORBIDDEN")
        else:
            self.traverse({'description': 'Mitglieder'},
                          {'description': 'Verg. Veranstaltungen'},
                          {'description': 'PfingstAkademie 2014'})

        # non-searchable users which did not participate should not see any user
        if user == USER_DICT['garcia']:
            invisible = [akira, berta, charly, emilia, ferdinand]
            for participant in invisible:
                self.assertNonPresence(participant)

        # non-cde admin who doesnt participate should see searchable members only
        elif user == USER_DICT['inga']:
            visible = [akira, berta, ferdinand]
            invisible = [charly, emilia]
            for participant in visible:
                self.assertPresence(participant, div='list-participants')
            for participant in invisible:
                self.assertNonPresence(participant)

        # ... and every participant can see every participant. But if they are
        # not searchable, they should not see any profile links.
        elif user == USER_DICT['charly']:
            visible = [akira, berta, charly, emilia, ferdinand]
            for participant in visible:
                self.assertPresence(participant, div='list-participants')
                self.assertNoLink(participant)

    @as_users("charly", "daniel", "garcia", "inga")
    def test_show_past_course(self, user):
        akira = "Akira Abukara"
        emilia = "Emilia E. Eventis"
        ferdinand = "Ferdinand F. Findus"
        # non-members should not have access if they are no cde admin
        if user == USER_DICT['daniel']:
            self.get('/cde/past/event/1/course/2/show', status="403 FORBIDDEN")
        else:
            self.traverse({'description': 'Mitglieder'},
                          {'description': 'Verg. Veranstaltungen'},
                          {'description': 'PfingstAkademie 2014'},
                          {'description': 'Goethe zum Anfassen'})

        # non-searchable users which did not participate should not see any user
        if user == USER_DICT['garcia']:
            invisible = [akira, emilia, ferdinand]
            for participant in invisible:
                self.assertNonPresence(participant)

        # non-cde admin who doesnt participate should see searchable members only
        elif user == USER_DICT['inga']:
            visible = [akira, ferdinand]
            invisible = [emilia]
            for participant in visible:
                self.assertPresence(participant, div='list-participants')
            for participant in invisible:
                self.assertNonPresence(participant)

        # ... and every participant can see every participant. But if they are
        # not searchable, they should not see any profile links.
        elif user == USER_DICT['charly']:
            visible = [akira, emilia, ferdinand]
            for participant in visible:
                self.assertPresence(participant, div='list-participants')
                self.assertNoLink(participant)
