#!/usr/bin/env python3

import csv
import re
import unittest.mock

import cdedb.database.constants as const
from test.common import as_users, USER_DICT, FrontendTest, prepsql
from cdedb.common import ADMIN_VIEWS_COOKIE_NAME
from cdedb.frontend.common import CustomCSVDialect

from cdedb.query import QueryOperators
import cdedb.ml_type_aux as ml_type


class TestMlFrontend(FrontendTest):
    @as_users("berta", "emilia", "janis")
    def test_index(self, user):
        self.traverse({'href': '/ml/'})

    @as_users("annika", "anton", "berta", "martin", "nina", "vera", "viktor")
    def test_sidebar(self, user):
        self.traverse({'description': 'Mailinglisten'})
        # Users with no administrated and no moderated mailinglists:
        if user['id'] in {USER_DICT['martin']['id']}:
            ins = ["Übersicht"]
            out = ["Alle Mailinglisten", "Moderierte Mailinglisten",
                   "Aktive Mailinglisten", "Nutzer verwalten", "Log"]
        # Users with core admin privileges for some mailinglists:
        elif user['id'] in {USER_DICT['vera']['id']}:
            ins = ["Aktive Mailinglisten", "Administrierte Mailinglisten",
                   "Log", "Nutzer verwalten"]
            out = ["Übersicht", "Alle Mailinglisten",
                   "Moderierte Mailinglisten"]
        # Users with relative admin privileges for some mailinglists:
        elif user['id'] in {USER_DICT['viktor']['id']}:
            ins = ["Aktive Mailinglisten", "Administrierte Mailinglisten",
                   "Log"]
            out = ["Übersicht", "Alle Mailinglisten",
                   "Moderierte Mailinglisten", "Nutzer verwalten"]
        # Users with moderated mailinglists and relative admin privileges
        # for some mailinglists:
        elif user['id'] in {USER_DICT['annika']['id']}:
            ins = ["Aktive Mailinglisten", "Administrierte Mailinglisten",
                   "Moderierte Mailinglisten", "Log"]
            out = ["Übersicht", "Alle Mailinglisten",
                   "Nutzer verwalten"]
        # Users with moderated mailinglists, but no admin privileges.
        elif user['id'] in {USER_DICT['berta']['id']}:
            ins = ["Aktive Mailinglisten", "Moderierte Mailinglisten", "Log"]
            out = ["Übersicht", "Administrierte Mailinglisten",
                   "Alle Mailinglisten", "Nutzer verwalten"]
        # Users with full ml-admin privileges.
        elif user['id'] in {USER_DICT['nina']['id']}:
            ins = ["Aktive Mailinglisten", "Alle Mailinglisten",
                   "Nutzer verwalten", "Log"]
            out = ["Übersicht", "Moderierte Mailinglisten"]
        # Users with moderated mailinglisrs with full ml-admin privileges.
        elif user['id'] in {USER_DICT['anton']['id']}:
            ins = ["Aktive Mailinglisten", "Alle Mailinglisten",
                   "Moderierte Mailinglisten", "Nutzer verwalten", "Log"]
            out = ["Übersicht"]
        else:
            self.fail("Please adjust users for this test.")

        self.check_sidebar(ins, out)

    @as_users("janis")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))

    @as_users("janis")
    def test_changeuser(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("nina", "ferdinand")
    def test_adminchangeuser(self, user):
        self.realm_admin_view_profile('janis', 'ml')
        self.traverse({'href': '/core/persona/10/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.assertNotIn('birthday', f.fields)
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Janis Jalapeño")

    @as_users("nina", "ferdinand")
    def test_toggleactivity(self, user):
        self.realm_admin_view_profile('janis', 'ml')
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("nina", "vera")
    def test_user_search(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/search/user'})
        self.assertTitle("Mailinglisten-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 's@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Mailinglisten-Nutzerverwaltung")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Jalapeño")

    @as_users("nina", "vera")
    def test_create_user(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/search/user'}, {'href': '/ml/user/create'})
        self.assertTitle("Neuen Mailinglistennutzer anlegen")
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
    def test_ml_admin_views(self, user):
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, '')

        self.traverse({'description': 'Mailinglisten'})
        self._click_admin_view_button(re.compile(r"Benutzer-Administration"),
                                      current_state=False)

        # Test Event Administration Admin View
        # This is still available because we are a moderator.
        # self.assertNoLink('/ml/mailinglist/list')
        # self.assertNoLink('/ml/log')
        self.traverse({'description': 'Verkündungen'})
        self.assertNoLink('/ml/mailinglist/1/change')
        self.assertNoLink('/ml/mailinglist/1/log')
        self.assertPresence("Du hast diese Mailingliste abonniert.")
        self._click_admin_view_button(re.compile(r"Mailinglisten-Administration"),
                                      current_state=False)
        self.traverse({'href': '/ml/mailinglist/1/change'})
        self.assertPresence('Speichern')
        self.traverse({'href': '/ml/'},
                      {'href': '/ml/mailinglist/list'},
                      {'href': '/ml/mailinglist/create'})

        # Test Moderator Controls Admin View
        self.traverse({'href': '/ml/'},
                      {'href': '/ml/mailinglist/1/show'})
        self.assertNoLink('/ml/mailinglist/1/management')
        self.assertNoLink('/ml/mailinglist/1/management/advanced')

        self._click_admin_view_button(re.compile(r"Mailinglisten-Administration"),
                                      current_state=True)
        self._click_admin_view_button(re.compile(r"Moderator-Schaltflächen"),
                                      current_state=False)
        self.traverse({'href': '/ml/mailinglist/1/management'},
                      {'href': '/ml/mailinglist/1/management/advanced'},
                      {'href': '/ml/mailinglist/1/log'},
                      {'href': '/ml/mailinglist/1/change'})
        f = self.response.forms['changelistform']
        f['notes'] = "I can change this!"
        f['subject_prefix'] = "Spaß"
        self.submit(f)

        self.traverse({"description": "Konfiguration"})
        f = self.response.forms['changelistform']
        self.assertEqual("I can change this!", f['notes'].value)
        self.assertEqual("Spaß", f['subject_prefix'].value)

    @as_users("berta", "charly")
    def test_show_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},)
        self.assertTitle("Mailinglisten")
        self.traverse({'href': '/ml/mailinglist/4'})
        self.assertTitle("Klatsch und Tratsch")

    @as_users("berta", "emilia", "annika", "nina")
    def test_hide_admin_notes(self, user):
        # CdElokal Hogwarts
        ml_data = self.sample_data['ml.mailinglists'][65]
        self.traverse({'description': 'Mailinglisten'},
                      {'description': ml_data['title']})
        # Make sure that admin notes exist.
        self.assertTrue(ml_data['notes'])
        if user['id'] in {5, 14}:
            # Nina is admin, Emilia is moderator, they should see the notes.
            self.assertPresence(ml_data['notes'])
        else:
            # Berta has no admin privileges, Annika has none _for this list_.
            self.assertNonPresence(ml_data['notes'])

    @as_users("annika", "anton", "berta", "martin", "nina", "vera", "werner")
    def test_sidebar_one_mailinglist(self, user):
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Feriendorf Bau'})
        everyone = ["Mailinglisten-Übersicht", "Übersicht"]
        moderator = ["Verwaltung", "Erweiterte Verwaltung", "Konfiguration",
                     "Nachrichtenmoderation", "Log"]

        # Moderators:
        if user['id'] in {USER_DICT['berta']['id']}:
            ins = everyone + moderator
            out = []
        # Relative admins that are not also moderators:
        elif user['id'] in {USER_DICT['vera']['id']}:
            ins = everyone + moderator
            out = []
        # Absolute admins that are not also moderators:
        elif user['id'] in {USER_DICT['anton']['id'], USER_DICT['nina']['id']}:
            ins = everyone + moderator
            out = []
        # Other users:
        elif user['id'] in {USER_DICT['annika']['id'],
                            USER_DICT['martin']['id'],
                            USER_DICT['werner']['id']}:
            ins = everyone
            out = moderator
        else:
            self.fail("Please adjust users for this test.")

        self.check_sidebar(ins, out)

    @as_users("anton", "janis")
    def test_show_ml_buttons_change_address(self, user):
        # not-mandatory
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/3'},)
        self.assertTitle("Witz des Tages")
        if user['id'] == USER_DICT['anton']['id']:
            self.assertPresence("new-anton@example.cde")
        else:
            self.assertPresence("janis-spam@example.cde")
        self.assertIn("resetaddressform", self.response.forms)
        self.assertIn("unsubscribeform", self.response.forms)
        self.assertIn("changeaddressform", self.response.forms)
        self.assertNonPresence("Diese Mailingliste ist obligatorisch.")

        # mandatory
        # janis is no cde-member, so use inga instead
        if user['id'] == USER_DICT['janis']['id']:
            self.logout()
            self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/1'},)
        self.assertTitle("Verkündungen")
        if user['id'] == USER_DICT['anton']['id']:
            self.assertPresence("anton@example.cde (default)")
        else:
            self.assertPresence("inga@example.cde (default)")
        self.assertNotIn("resetaddressform", self.response.forms)
        self.assertNotIn("unsubscribeform", self.response.forms)
        self.assertNotIn("changeaddressform", self.response.forms)
        self.assertPresence("Diese Mailingliste ist obligatorisch.")

    @as_users("anton", "charly")
    def test_show_ml_buttons_mod_opt_in(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['unsubscribeform']
        self.submit(f)
        self.assertPresence("Du bist zurzeit kein Abonnent dieser Mailingliste")
        self.assertIn("subscribe-mod-form", self.response.forms)

        f = self.response.forms['subscribe-mod-form']
        self.submit(f)
        self.assertPresence("Deine Anfrage für diese Mailingliste wartet auf "
                            "Bestätigung durch einen Moderator. ")
        self.assertIn("cancel-request-form", self.response.forms)

    @as_users("anton", "berta")
    def test_show_ml_buttons_opt_in(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/7'},)
        self.assertTitle("Aktivenforum 2001")
        self.assertPresence("Du bist zurzeit kein Abonnent dieser Mailingliste")
        self.assertIn("subscribe-no-mod-form", self.response.forms)

        f = self.response.forms['subscribe-no-mod-form']
        self.submit(f)
        self.assertPresence("Du hast diese Mailingliste abonniert.")
        self.assertIn("unsubscribeform", self.response.forms)

    @as_users("akira", "inga")
    def test_show_ml_buttons_blocked(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/11'},)
        self.assertTitle("Kampfbrief-Kommentare")
        self.assertPresence("Du kannst diese Mailingliste nicht abonnieren")
        self.assertNotIn("subscribe-mod-form", self.response.forms)
        self.assertNotIn("subscribe-no-mod-form", self.response.forms)

    @as_users("nina")
    def test_list_all_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Alle Mailinglisten")
        self.assertPresence("Mitglieder (Moderiertes Opt-in)")
        self.assertPresence("Große Testakademie 2222")
        self.assertPresence("CdE-Party 2050")
        # not yet published
        self.assertNoLink("CdE-Party 2050")
        self.assertPresence("Internationaler Kongress")
        # Nina is no assembly user
        self.assertNoLink("Internationaler Kongress")
        self.assertPresence("Andere Mailinglisten")
        self.traverse({'href': '/ml/mailinglist/6'})
        self.assertTitle("Aktivenforum 2000")

    @as_users("annika")
    def test_list_event_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Administrierte Mailinglisten")
        self.assertPresence("Große Testakademie 2222")
        self.assertPresence("CdE-Party 2050 Orgateam")
        self.assertPresence("Veranstaltungslisten")
        # Moderated, but not administered mailinglists
        self.assertNonPresence("Versammlungslisten")
        self.assertNonPresence("Allgemeine Mailinglisten")
        self.assertNonPresence("Andere Mailinglisten")
        self.assertNonPresence("CdE-All")

    @as_users("berta", "janis")
    def test_moderated_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/moderated'})
        self.assertTitle("Moderierte Mailinglisten")
        # Moderated mailinglists
        self.assertPresence("Allgemeine Mailinglisten")
        self.assertPresence("Aktivenforum 2001")
        if user['id'] == USER_DICT['berta']['id']:
            self.assertPresence("Veranstaltungslisten")
            self.assertPresence("CdE-Party 2050 Orgateam")
            # Inactive moderated mailinglists
            self.assertPresence("Aktivenforum 2000")
            self.traverse({'description': 'Aktivenforum 2000'})
            self.assertTitle("Aktivenforum 2000 – Verwaltung")

    @as_users("annika")
    def test_admin_moderated_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/moderated'})
        self.assertTitle("Moderierte Mailinglisten")
        # Moderated mailinglists
        self.assertPresence("Allgemeine Mailinglisten")
        self.assertPresence("CdE-All")
        self.assertPresence("Veranstaltungslisten")
        self.assertPresence("CdE-Party 2050 Orgateam")
        # Administrated, not moderated mailinglists
        self.assertNonPresence("Große Testakademie 2222")
        self.assertNonPresence("Versammlungslisten")
        self.assertNonPresence("Andere Mailinglisten")

    @as_users("nina", "berta")
    def test_mailinglist_management(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'})
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota", div="moderator_list")
        self.assertNonPresence("Anton Armin A. Administrator", div="moderator_list")
        f = self.response.forms['addmoderatorform']
        # Check that you cannot add non-existing or archived moderators.
        errormsg = "Einige dieser Nutzer existieren nicht oder sind archiviert."
        f['moderators'] = "DB-100000-4"
        self.submit(f, check_notification=False)
        self.assertPresence(errormsg, div="addmoderatorform")
        # Hades is archived.
        f['moderators'] = USER_DICT["hades"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertPresence(errormsg, div="addmoderatorform")

        # Now for real.
        f['moderators'] = "DB-9-4, DB-1-9"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertPresence("Inga Iota", div="moderator_list")
        self.assertPresence("Anton Armin A. Administrator",
                            div="moderator_list")
        f = self.response.forms['removemoderatorform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota", div="moderator_list")
        self.assertNotIn("removesubscriberform9", self.response.forms)
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-9-4"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertIn("removesubscriberform9", self.response.forms)

        self.traverse({'href': '/ml/mailinglist/4/management/advanced'})
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("zelda@example.cde")
        f = self.response.forms['addwhitelistform']
        f['email'] = "zelda@example.cde"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("zelda@example.cde")
        f = self.response.forms['removewhitelistform1']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("zelda@example.cde")

    @as_users("nina", "berta")
    def test_advanced_management(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management/advanced'})

        # add some persona
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Inga Iota", div="modsubscriber-list")
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_ids'] = "DB-9-4"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Inga Iota", div="modsubscriber-list")

        self.assertNonPresence("Emilia E. Eventis", div="modunsubscriber-list")
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_ids'] = "DB-5-1"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Emilia E. Eventis", div="modunsubscriber-list")

        self.assertNonPresence("zelda@example.cde", div="whitelist")
        f = self.response.forms['addwhitelistform']
        f['email'] = "zelda@example.cde"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("zelda@example.cde", div="whitelist")

        # now check the download file

        save = self.response

        self.traverse({"href": "ml/mailinglist/4/download"})

        result = list(csv.DictReader(
            self.response.body.decode('utf-8-sig').split("\n"),
            dialect=CustomCSVDialect))
        all_rows = []

        for row in result:
            line = (row['db_id'] + ";" + row['given_names'] + ";" +
                    row['family_name'] + ";" + row['subscription_state'] + ";" +
                    row['email'] + ";" + row['subscription_address'])
            all_rows.append(line)

        self.assertIn('DB-5-1;Emilia E.;Eventis;unsubscription_override;'
                      'emilia@example.cde;', all_rows)
        self.assertIn('DB-9-4;Inga;Iota;subscription_override;'
                      'inga@example.cde;', all_rows)

        # remove the former added persona
        self.response = save

        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Inga Iota")
        f = self.response.forms['removemodsubscriberform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Inga Iota")

        self.assertPresence("Emilia E. Eventis")
        f = self.response.forms['removemodunsubscriberform5']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Emilia E. Eventis")

        self.assertPresence("zelda@example.cde")
        f = self.response.forms['removewhitelistform1']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("zelda@example.cde")

    # TODO add a presider as moderator and use him too in this test
    @as_users("nina")
    def test_mailinglist_management_outside_audience(self, user):
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Sozialistischer Kampfbrief'},
                      {'description': 'Erweiterte Verwaltung'})
        self.assertTitle("Sozialistischer Kampfbrief – Erweiterte Verwaltung")
        self.assertNonPresence("Janis Jalapeño")
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_ids'] = "DB-10-8"
        self.submit(f)
        self.assertTitle("Sozialistischer Kampfbrief – Erweiterte Verwaltung")
        self.assertPresence("Janis Jalapeño")

    @as_users("berta")
    def test_mailinglist_management_multi(self, user):
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Aktivenforum 2001'},
                      {'description': 'Verwaltung'})
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9, DB-2-7"
        self.submit(f)
        # noop
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9, DB-2-7"
        self.submit(f, check_notification=False)
        self.assertPresence("Aktion hatte keinen Effekt.", div='notifications')
        # Partial noop
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9, DB-9-4"
        self.submit(f)
        self.assertPresence("Der Nutzer ist bereits Abonnent.",
                            div='notifications')
        # One user archived. Action aborted.
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9, DB-8-6"
        self.submit(f, check_notification=False)
        self.assertPresence("Einige dieser Nutzer existieren nicht "
                            "oder sind archiviert.")
        # one user is event user only
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-7-8, DB-5-1"
        self.submit(f)
        self.assertPresence("Der Nutzer hat keine Berechtigung auf "
                            "dieser Liste zu stehen.",
                            div='notifications')
        # noop with one event user
        self.assertTitle("Aktivenforum 2001 – Verwaltung")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-7-8, DB-5-1"
        self.submit(f, check_notification=False)
        self.assertPresence("Der Nutzer hat keine Berechtigung auf "
                            "dieser Liste zu stehen.",
                            div='notifications')
        self.assertPresence("Der Nutzer ist bereits Abonnent.",
                            div='notifications')
        self.assertPresence("Änderung fehlgeschlagen.", div='notifications')

    @as_users("berta")
    def test_advanced_management_multi(self, user):
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Aktivenforum 2001'},
                      {'description': 'Erweiterte Verwaltung'})
        self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
        for state in ('modsubscriber', 'modunsubscriber'):
            form = 'add' + state + 'form'
            field = state + '_ids'

            f = self.response.forms[form]
            f[field] = "DB-1-9, DB-2-7"
            self.submit(f)
            # noop
            self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
            f = self.response.forms[form]
            f[field] = "DB-1-9, DB-2-7"
            self.submit(f, check_notification=False)
            self.assertPresence("Aktion hatte keinen Effekt.", div='notifications')
            # Partial noop
            self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
            f = self.response.forms[form]
            f[field] = "DB-1-9, DB-9-4"
            self.submit(f)
            self.assertPresence("Info! Nutzer ist ", div='notifications')
            # One user archived. Action aborted.
            self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
            f = self.response.forms[form]
            f[field] = "DB-1-9, DB-8-6"
            self.submit(f, check_notification=False)
            self.assertPresence("Einige dieser Nutzer existieren nicht "
                                "oder sind archiviert.")
            # one user is event user only
            self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
            f = self.response.forms[form]
            f[field] = "DB-7-8, DB-5-1"
            self.submit(f)
            self.assertNonPresence("Der Nutzer hat keine Berechtigung auf "
                                   "dieser Liste zu stehen.",
                                    div='notifications')

    @as_users("nina")
    def test_create_mailinglist(self, user):
        self.traverse({'description': 'Mailinglisten'})
        self.assertTitle("Mailinglisten")
        self.assertNonPresence("Munkelwand")
        self.traverse({'description': 'Mailingliste anlegen'})
        self.assertTitle("Mailingliste anlegen")
        f = self.response.forms['selectmltypeform']
        f['ml_type'] = const.MailinglistTypes.member_mandatory.value
        self.submit(f)
        f = self.response.forms['createlistform']
        self.assertEqual(f['maxsize'].value, '64')
        f['title'] = "Munkelwand"
        f['mod_policy'] = 1
        f['attachment_policy'] = 2
        f['subject_prefix'] = "[munkel]"
        f['maxsize'] = 512
        f['is_active'].checked = True
        f['notes'] = "Noch mehr Gemunkel."
        f['domain'] = 1
        f['local_part'] = 'munkelwand'
        # Check that there must be some moderators
        errormsg = "Darf nicht leer sein."
        f['moderators'] = ""
        self.submit(f, check_notification=False)
        self.assertValidationError("moderators", errormsg)
        # Check that you cannot add non-existing or archived moderators.
        errormsg = "Einige dieser Nutzer existieren nicht oder sind archiviert"
        f['moderators'] = "DB-100000-4"
        self.submit(f, check_notification=False)
        self.assertValidationError("moderators", errormsg)
        # Hades is archived.
        f['moderators'] = "DB-8-6"
        self.submit(f, check_notification=False)
        self.assertValidationError("moderators", errormsg)
        # Now for real.
        f['moderators'] = "DB-3-5, DB-7-8"
        # Check that no lists with the same address can be made
        f['local_part'] = "platin"
        self.submit(f, check_notification=False)
        self.assertValidationError("local_part", "Uneindeutige Mailadresse")

        f['local_part'] = "munkelwand"
        self.submit(f)
        self.assertTitle("Munkelwand")
        self.assertPresence("Clown")
        self.assertPresence("Garcia G. Generalis")

    @as_users("nina")
    def test_change_mailinglist(self, user):
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Alle Mailinglisten'},
                      {'description': 'Werbung'},
                      {'description': 'Konfiguration'},)
        self.assertTitle("Werbung – Konfiguration")
        f = self.response.forms['changelistform']
        self.assertEqual("Werbung", f['title'].value)
        f['title'] = "Munkelwand"
        self.assertEqual("werbung", f['local_part'].value)
        self.assertTrue(f['is_active'].checked)
        f['is_active'].checked = False

        # Check that no lists with the same address can be made
        f['local_part'] = "platin"
        self.submit(f, check_notification=False)
        self.assertValidationError("local_part", "Uneindeutige Mailadresse")
        self.assertValidationError("domain", "Uneindeutige Mailadresse")

        f['local_part'] = "munkelwand"
        self.submit(f)
        self.assertTitle("Munkelwand")
        self.traverse({'href': '/ml/mailinglist/2/change'},)
        f = self.response.forms['changelistform']
        self.assertEqual("Munkelwand", f['title'].value)
        self.assertEqual("munkelwand", f['local_part'].value)
        self.assertFalse(f['is_active'].checked)
        self.traverse({'href': '/ml/$'})
        self.assertTitle("Mailinglisten")
        self.assertNonPresence("Munkelwand")

    @as_users("nina")
    def test_change_ml_type(self, user):
        # TODO: check auto subscription for opt-out lists
        assembly_types = {
            const.MailinglistTypes.assembly_associated,
            const.MailinglistTypes.assembly_presider,
        }
        # MailinglistTypes.assembly_opt_in is not bound to an assembly
        event_types = {
            const.MailinglistTypes.event_associated,
            const.MailinglistTypes.event_orga,
        }
        general_types = {
            t for t in const.MailinglistTypes if t not in (
                assembly_types.union(event_types)
            )}
        event_id = 1
        event_title = self.sample_data['event.events'][event_id]['title']
        assembly_id = 1
        assembly_title = self.sample_data[
            'assembly.assemblies'][assembly_id]['title']

        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Alle Mailinglisten'},
                      {'description': 'Mitgestaltungsforum'},
                      {'description': 'Konfiguration'}, )
        self.assertTitle("Mitgestaltungsforum – Konfiguration")
        self.traverse({'description': 'Typ ändern'})
        self.assertTitle("Mitgestaltungsforum – Typ ändern")
        f = self.response.forms['changemltypeform']

        for ml_type in const.MailinglistTypes:
            with self.subTest(ml_type=ml_type):
                f['ml_type'] = ml_type.value
                f['event_id'] = event_id
                f['registration_stati'] = [
                    const.RegistrationPartStati.participant.value,
                    const.RegistrationPartStati.waitlist.value,
                ]
                f['assembly_id'] = assembly_id
                # no ml type should allow event *and* assembly fields to be set
                self.submit(f, check_notification=False)
                if ml_type not in event_types:
                    self.assertValidationError('event_id', "Muss leer sein.")
                    self.assertValidationError("registration_stati",
                                               "Muss eine leere Liste sein.",
                                               index=0)
                elif ml_type == const.MailinglistTypes.event_orga:
                    self.assertValidationError("registration_stati",
                                               "Muss eine leere Liste sein.",
                                               index=0)
                else:
                    self.assertNonPresence("Muss eine leere Liste sein.")
                if ml_type not in assembly_types:
                    self.assertValidationError('assembly_id', "Muss leer sein.")

                f['event_id'] = ''
                f['registration_stati'] = []
                f['assembly_id'] = ''
                if ml_type in general_types:
                    self.submit(f)
                elif ml_type in event_types:
                    self.submit(f)  # only works if all event-associated ml
                    # types can also not be associated with an event, which may
                    # change in future
                    self.traverse({'description': r"\sÜbersicht"})
                    self.assertNonPresence("Mailingliste zur Veranstaltung")
                    f['event_id'] = event_id
                    self.submit(f)
                    self.traverse({'description': r"\sÜbersicht"})
                    self.assertPresence(
                        f"Mailingliste zur Veranstaltung {event_title}")
                elif ml_type in assembly_types:
                    self.submit(f, check_notification=False)
                    self.assertValidationError('assembly_id', "Ungültige "
                                                "Eingabe für eine Ganzzahl.")
                    f['assembly_id'] = assembly_id
                    self.submit(f)
                    self.traverse({'description': r"\sÜbersicht"})
                    self.assertPresence(
                        f"Mailingliste zur Versammlung {assembly_title}")

    @as_users("nina")
    def test_change_mailinglist_registration_stati(self, user):
        self.get("/ml/mailinglist/9/change")
        self.assertTitle("Teilnehmer-Liste – Konfiguration")
        f = self.response.forms['changelistform']
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        self.assertEqual({"2", "4", None}, tmp)
        f['registration_stati'] = [3, 5]
        self.submit(f)
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        self.assertEqual({"3", "5", None}, tmp)

    @as_users("nina")
    def test_delete_ml(self, user):
        self.get("/ml/mailinglist/2/show")
        self.assertTitle("Werbung")
        f = self.response.forms["deletemlform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertTitle("Alle Mailinglisten")
        self.assertNonPresence("Werbung")

    def test_subscription_request(self):
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribe-mod-form']
        self.submit(f)
        self.logout()
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'},)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        f = self.response.forms['approverequestform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNotIn('approverequestform9', self.response.forms)
        self.logout()
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertIn('unsubscribeform', self.response.forms)

    @as_users("charly", "inga")
    def test_subscribe_unsubscribe(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/3'},)
        self.assertTitle("Witz des Tages")
        f = self.response.forms['subscribe-no-mod-form']
        self.submit(f)
        self.assertTitle("Witz des Tages")
        f = self.response.forms['unsubscribeform']
        self.submit(f)
        self.assertTitle("Witz des Tages")
        self.assertIn('subscribe-no-mod-form', self.response.forms)

    @as_users("janis")
    def test_moderator_add_subscriber(self, user):
        self.get("/ml/mailinglist/7/management")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9"
        self.submit(f)
        self.assertPresence("Anton Armin A. Administrator")

    def _create_mailinglist(self, mdata):
        self.traverse({'href': '/ml/'},
                      {'href': '/ml/mailinglist/create'})
        f = self.response.forms['selectmltypeform']
        f['ml_type'] = mdata['ml_type']
        self.submit(f)
        f = self.response.forms['createlistform']
        for k, v in mdata.items():
            if k == 'ml_type':
                continue
            f[k] = v
        self.submit(f)
        self.assertTitle(mdata['title'])

    def test_event_mailinglist(self):
        for i, u in enumerate(("emilia", "garcia", "inga")):
            if i > 0:
                self.setUp()
            user = USER_DICT[u]
            with self.subTest(user=u):
                self.login(USER_DICT["anton"])
                mdata = {
                    'title': 'TestAkaList',
                    'ml_type': const.MailinglistTypes.event_associated.value,
                    'local_part': 'testaka',
                    'domain': const.MailinglistDomain.aka.value,
                    'event_id': "1",
                    'moderators': user['DB-ID'],
                }
                self._create_mailinglist(mdata)
                # Add the user as orga. (Garcia is orga already.)
                if user["id"] in {USER_DICT["emilia"]["id"], USER_DICT["inga"]["id"]}:
                    self.traverse({'href': '/event/'},
                                  {'href': '/event/event/1/show'})
                    f = self.response.forms['addorgaform']
                    f['orga_id'] = user['DB-ID']
                    self.submit(f, check_notification=False)
                    self.assertPresence(user['given_names'], div='manage-orgas')
                self.logout()
                self.login(user)
                self.traverse({'href': '/'})
                self.traverse({'href': '/ml/mailinglist/1001/show'})
                self.traverse({'description': 'Erweiterte Verwaltung'})
                self.assertTitle(mdata['title'] + " – Erweiterte Verwaltung")
                f = self.response.forms['addmodsubscriberform']
                f['modsubscriber_ids'] = "DB-2-7"
                self.submit(f)
                f = self.response.forms['removemodsubscriberform2']
                self.submit(f)

    @as_users("berta", "charly")
    def test_change_sub_address(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['changeaddressform']
        f['email'] = "pepper@example.cde"
        self.submit(f, check_notification=False)
        self.assertTitle("Klatsch und Tratsch")
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.assertTitle("Klatsch und Tratsch")
        self.assertIn('unsubscribeform', self.response.forms)
        self.assertPresence('pepper@example.cde')
        f = self.response.forms['resetaddressform']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch")
        self.assertIn('unsubscribeform', self.response.forms)
        self.assertNonPresence('pepper@example.cde')

    @as_users("nina", "berta")
    def test_subscription_errors(self, user):
        # preparation: subscription request from inga
        self.logout()
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'}, )
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribe-mod-form']
        self.submit(f)
        self.logout()
        self.login(user)
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'}, )
        self.assertTitle("Klatsch und Tratsch – Verwaltung")

        # testing: try to add a subscription request
        # as normal user
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = USER_DICT["inga"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            div="notifications")
        # as mod subscriber
        self.traverse({'href': '/ml/mailinglist/4/management/advanced'}, )
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_ids'] = USER_DICT["inga"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            div="notifications")
        # as mod unsubscribe
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_ids'] = USER_DICT["inga"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            div="notifications")

        # testing: mod subscribe and unsubscribe
        # add already subscribed user as mod subscribe
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_ids'] = USER_DICT["anton"]["DB-ID"]
        self.submit(f, check_notification=True)
        # add already subscribed user as mod unsubscribe
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_ids'] = USER_DICT["janis"]["DB-ID"]
        self.submit(f, check_notification=True)
        # try to remove mod subscribe with normal subscriber form
        self.traverse({'href': '/ml/mailinglist/4/management'}, )
        f = self.response.forms['removesubscriberform1']
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer kann nicht entfernt werden, da er fixiert ist. "
            "Dies kannst du unter Erweiterte Verwaltung ändern.",
            div="notifications")
        # try to add a mod unsubscribed user
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = USER_DICT["garcia"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence("Der Nutzer wurde geblockt. "
                            "Dies kannst du unter Erweiterte Verwaltung ändern.",
                            div="notifications")

    def test_export(self):
        HEADERS = {'MLSCRIPTKEY': "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"}
        expectation = [{'address': 'announce@lists.cde-ev.de', 'is_active': True},
                       {'address': 'werbung@lists.cde-ev.de', 'is_active': True},
                       {'address': 'witz@lists.cde-ev.de', 'is_active': True},
                       {'address': 'klatsch@lists.cde-ev.de', 'is_active': True},
                       {'address': 'kongress@lists.cde-ev.de', 'is_active': True},
                       {'address': 'aktivenforum2000@lists.cde-ev.de', 'is_active': False},
                       {'address': 'aktivenforum@lists.cde-ev.de', 'is_active': True},
                       {'address': 'aka@aka.cde-ev.de', 'is_active': True},
                       {'address': 'participants@aka.cde-ev.de', 'is_active': True},
                       {'address': 'wait@aka.cde-ev.de', 'is_active': True},
                       {'address': 'opt@lists.cde-ev.de', 'is_active': True},
                       {'address': 'all@lists.cde-ev.de', 'is_active': True},
                       {'address': 'info@lists.cde-ev.de', 'is_active': True},
                       {'address': 'mitgestaltung@lists.cde-ev.de', 'is_active': True},
                       {'address': 'gutscheine@lists.cde-ev.de', 'is_active': True},
                       {'address': 'platin@lists.cde-ev.de', 'is_active': True},
                       {'address': 'bau@lists.cde-ev.de', 'is_active': True},
                       {'address': 'geheim@lists.cde-ev.de', 'is_active': True},
                       {'address': 'test-gast@aka.cde-ev.de', 'is_active': True},
                       {'address': 'party50@aka.cde-ev.de', 'is_active': True},
                       {'address': 'party50-all@aka.cde-ev.de', 'is_active': True},
                       {'address': 'kanonisch@lists.cde-ev.de', 'is_active': True},
                       {'address': 'wal@lists.cde-ev.de', 'is_active': True},
                       {'address': 'dsa@lists.cde-ev.de', 'is_active': True},
                       {'address': '42@lists.cde-ev.de', 'is_active': True},
                       {'address': 'hogwarts@cdelokal.cde-ev.de', 'is_active': True},
                       {'address': 'kongress-leitung@lists.cde-ev.de', 'is_active': True},
                       {'address': 'migration@testmail.cde-ev.de', 'is_active': True},
                       ]
        self.get("/ml/script/all", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {
            'address': 'werbung@lists.cde-ev.de',
            'admin_address': 'werbung-owner@lists.cde-ev.de',
            'listname': 'Werbung',
            'moderators': ['janis@example.cde'],
            'sender': 'werbung@lists.cde-ev.de',
            'size_max': None,
            'subscribers': ['anton@example.cde',
                            'berta@example.cde',
                            'charly@example.cde',
                            'garcia@example.cde',
                            'inga@example.cde',
                            'olaf@example.cde',
                            'akira@example.cde'],
            'whitelist': ['honeypot@example.cde']}
        self.get("/ml/script/one?address=werbung@lists.cde-ev.de", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)

    def test_oldstyle_access(self):
        HEADERS = {'MLSCRIPTKEY': "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"}
        expectation = [{'address': 'announce@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': True},
                       {'address': 'werbung@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'witz@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': 2048,
                        'mime': None},
                       {'address': 'klatsch@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'kongress@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aktivenforum2000@lists.cde-ev.de',
                        'inactive': True,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aktivenforum@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aka@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'participants@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'wait@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'opt@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'all@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'info@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': None},
                       {'address': 'mitgestaltung@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'gutscheine@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'platin@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'bau@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'geheim@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'test-gast@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': True},
                       {'address': 'party50@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': False},
                       {'address': 'party50-all@aka.cde-ev.de',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'kanonisch@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': None},
                       {'address': 'wal@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'dsa@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': True},
                       {'address': '42@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'hogwarts@cdelokal.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'kongress-leitung@lists.cde-ev.de',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'migration@testmail.cde-ev.de',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None}]
        self.get("/ml/script/all/compat", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {'address': 'werbung@lists.cde-ev.de',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': 'werbung',
                       'moderators': ['janis@example.cde',],
                       'sender': 'werbung-bounces@lists.cde-ev.de',
                       'subscribers': ['anton@example.cde',
                                       'berta@example.cde',
                                       'charly@example.cde',
                                       'garcia@example.cde',
                                       'inga@example.cde',
                                       'olaf@example.cde',
                                       'akira@example.cde'],
                       'whitelist': ['honeypot@example.cde',]}
        self.get("/ml/script/one/compat?address=werbung@lists.cde-ev.de",
                 headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {'address': 'werbung@lists.cde-ev.de',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': 'werbung',
                       'moderators': ['janis@example.cde',],
                       'sender': 'cdedb-doublebounces@cde-ev.de',
                       'subscribers': ['janis@example.cde',],
                       'whitelist': ['*']}
        self.get("/ml/script/mod/compat?address=werbung@lists.cde-ev.de",
                 headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        self.post("/ml/script/bounce/compat",
                  params={'address': "anton@example.cde", 'error': 1},
                  headers=HEADERS)
        self.assertEqual(True, self.response.json)

    @as_users("berta", "janis")
    def test_moderator_access(self, user):
        self.traverse({"href": "/ml"},
                      {"href": "/ml/mailinglist/3/show"})
        self.assertTitle("Witz des Tages")
        self.traverse({"href": "/ml/mailinglist/3/manage"})
        self.assertTitle("Witz des Tages – Verwaltung")
        self.traverse({"href": "/ml/mailinglist/3/change"})
        self.assertTitle("Witz des Tages – Konfiguration")
        self.assertIn('changelistform', self.response.forms)
        # TODO check that some form elements are readonly

        self.traverse({"href": "ml/mailinglist/3/log"})
        self.assertTitle("Witz des Tages: Log [0–0 von 0]")

    @as_users("berta", "janis")
    @prepsql("INSERT INTO ml.moderators (mailinglist_id, persona_id) VALUES (60, 10)")
    def test_moderator_change_mailinglist(self, user):
        self.traverse({"description": "Mailinglisten"},
                      {"description": "CdE-Party 2050 Teilnehmer"},
                      {"description": "Konfiguration"})

        old_ml = self.sample_data['ml.mailinglists'][60]
        f = self.response.forms['changelistform']

        # these properties are not allowed to be changed by moderators
        f['title'].force_value("Party-Time")
        f['local_part'].force_value("partyparty")
        f['event_id'].force_value(1)
        f['is_active'].force_value(False)
        # these properties can be changed by privileged moderators
        f['registration_stati'] = [const.RegistrationPartStati.guest.value]
        # these properties can be changed by every moderator
        f['description'] = "Wir machen Party!"
        f['notes'] = "Nur geladene Gäste."
        f['mod_policy'] = const.ModerationPolicy.unmoderated.value
        f['subject_prefix'] = "party"
        f['attachment_policy'] = const.AttachmentPolicy.allow.value
        f['maxsize'] = 1111
        self.submit(f)

        # Check that these have not changed ...
        self.traverse({"description": "Konfiguration"})
        f = self.response.forms['changelistform']
        self.assertEqual('True', f['is_active'].value)
        self.assertEqual(old_ml['title'], f['title'].value)
        self.assertEqual(old_ml['local_part'], f['local_part'].value)
        self.assertEqual(str(old_ml['event_id']), f['event_id'].value)

        # ... these have only changed if the moderator is privileged ...
        reality = {f.get("registration_stati", index=i).value for i in range(7)}
        if user == USER_DICT['berta']:
            expectation = {None, str(const.RegistrationPartStati.guest.value)}
        else:
            expectation = {str(status)
                           for status in old_ml['registration_stati']} | {None}
        self.assertEqual(expectation, reality)

        # ... and these have changed.
        self.assertEqual("Wir machen Party!", f['description'].value)
        self.assertEqual("Nur geladene Gäste.", f['notes'].value)
        self.assertEqual(str(const.ModerationPolicy.unmoderated.value),
                         f['mod_policy'].value)
        self.assertEqual("party", f['subject_prefix'].value)
        self.assertEqual(str(const.AttachmentPolicy.allow.value),
                         f['attachment_policy'].value)
        self.assertEqual("1111", f['maxsize'].value)

    @as_users("janis")
    @prepsql("INSERT INTO ml.moderators (mailinglist_id, persona_id) VALUES (5, 10)")
    def test_non_privileged_moderator(self, user):
        self.traverse({"description": "Mailinglisten"},
                      {"description": "Sozialistischer Kampfbrief"},
                      {"description": "Erweiterte Verwaltung"})
        self.assertPresence("Du hast keinen Zugriff als Privilegierter Moderator",
                            div="static-notifications")
        # they can neither add nor remove subscriptions.
        self.assertNotIn('addmodsubscriberform', self.response.forms)
        self.assertNotIn('removemodsubscriberform100', self.response.forms)

    @as_users("inga")
    def test_cdelokal_admin(self, user):
        self.traverse({"description": "Mailinglisten"},
                      {"description": "Hogwarts"})
        admin_note = self.sample_data['ml.mailinglists'][65]['notes']
        self.assertPresence(admin_note, div="adminnotes")
        self.traverse({"description": "Verwaltung"})
        f = self.response.forms['addmoderatorform']
        f['moderators'] = user['DB-ID']
        self.submit(f)
        self.assertPresence(user['given_names'], div="moderator_list")
        f = self.response.forms[f"removemoderatorform{user['id']}"]
        self.submit(f)
        self.assertNonPresence(user['given_names'], div="moderator_list")
        self.traverse({"description": "Konfiguration"})
        f = self.response.forms['changelistform']
        new_notes = "Free Butterbeer for everyone!"
        f['notes'] = new_notes
        self.submit(f)
        self.assertPresence(new_notes, div="adminnotes")
        self.traverse({"description": "Mailinglisten"},
                      {"description": "Mailingliste anlegen"})
        f = self.response.forms['selectmltypeform']
        f['ml_type'] = const.MailinglistTypes.cdelokal.value
        self.assertEqual(len(f['ml_type'].options), 1)
        self.submit(f)
        f = self.response.forms['createlistform']
        f['title'] = "Little Whinging"
        f['notes'] = "Only one wizard lives here, but he insisted on a" \
                     " Lokalgruppen-Mailinglist."
        f['description'] = "If anyone else lives here, please come by, " \
                           "I am lonely."
        f['local_part'] = "littlewhinging"
        f['domain'] = const.MailinglistDomain.cdelokal.value
        self.assertEqual(len(f['domain'].options),
                         len(ml_type.CdeLokalMailinglist.domains))
        moderator = USER_DICT["berta"]
        f['moderators'] = moderator["DB-ID"]
        self.submit(f)
        self.assertTitle("Little Whinging")
        self.assertPresence(moderator['given_names'], div="moderator_list")

    @as_users("anton")
    def test_1342(self, user):
        self.get("/ml/mailinglist/60/change")
        f = self.response.forms['changelistform']
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        sample_data_stati = set(str(x) for x in self.get_sample_data(
            "ml.mailinglists", (60,), ("registration_stati",))[60]["registration_stati"])
        self.assertEqual(sample_data_stati | {None}, tmp)
        stati = [const.RegistrationPartStati.waitlist.value,
                 const.RegistrationPartStati.guest.value]
        f['registration_stati'] = stati
        self.submit(f)
        self.traverse({"description": "Konfiguration"})
        f = self.response.forms['changelistform']
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        self.assertEqual({str(x) for x in stati} | {None}, tmp)

        stati = [const.RegistrationPartStati.not_applied.value]
        f['registration_stati'] = stati
        self.submit(f)
        self.traverse({"description": "Konfiguration"})
        f = self.response.forms['changelistform']
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        self.assertEqual({str(x) for x in stati} | {None}, tmp)

    @unittest.mock.patch("mailmanclient.Client")
    @as_users("anton")
    def test_mailman_moderation(self, client_class, user):
        #
        # Prepare
        #
        messages = [unittest.mock.MagicMock() for _ in range(3)]
        messages[0].request_id = 1
        messages[0].sender = 'kassenwart@example.cde'
        messages[0].subject = 'Finanzbericht'
        messages[0].reason = 'Spam'
        messages[1].request_id = 2
        messages[1].sender = 'illuminati@example.cde'
        messages[1].subject = 'Verschwurbelung'
        messages[1].reason = 'Spam'
        messages[2].request_id = 3
        messages[2].sender = 'nigerian_prince@example.cde'
        messages[2].subject = 'unerwartetes Erbe'
        messages[2].reason = 'Spam'
        for i in range(3):
            messages[i].msg = """
Received: from mail-il1-f180.google.com (mail-il1-f180.google.com [209.85.166.180])
	by mail.cde-ev.de (Postfix) with ESMTP id D03062000E7
	for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 18:36:08 +0100 (CET)
Received: by mail-il1-f180.google.com with SMTP id x15so20028263ilq.1
        for <mailman-migration@testmail.cde-ev.de>; Tue, 15 Dec 2020 09:36:08 -0800 (PST)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=gmail.com; s=20161025;
        h=mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=AnaGVaqslVzu6nvKOibF2ATCvUzNwKkuDlRHNe3Q0V20xHvsfnyEb9V+lvFf4mXhWY
         Cerg11qBWhpdKsk6rWlKBl5IPHY0wIRAM8N1h3vtKMfHuxyJ4U6k7LGEmlKXSuDl+QQk
         DAgL1ZpTtTjToEiP7QmOAQSOcG5jryV7KhbBrQSujHYv6s62MnNHYQXFnfkKBWgVCekf
         yFJ7oASV73GXZatnmDAAMhSRZBe39UjljlOCb4//S8G/XuSnponPrtdCzc4d67FTB4YL
         KyNwRpRF1/jMmKLkjXKKfgMj42EpIOwl7kA1uiyRA88HER3b56+1049Gi1kLybTkl9i1
         WFnA==
X-Google-DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=1e100.net; s=20161025;
        h=x-gm-message-state:mime-version:from:date:message-id:subject:to;
        bh=wxNIxkuiI0Hi2ZG/kqkcMfwGbfJ5LyA0tFjqoSn4zuA=;
        b=SEKJe6BemekvQQ+NEIBJIvSvG2GlNUn123x98BYNqnBUlkVqxpQzIo5W1+44NHB6Yk
         3FThiCdw3I9rT0FQUwrLYjZ1ZIBXCy7bWWmXvBONUAgIC196dVlCtsarDY/M7OJWmGqj
         H3KG6BVCq+Dmz9rhEM77Zd4nu+KaoPwKrUnVfJzmN1kgignUdUZ1oJsoir/s9snipX2h
         b94wF9FAmym3wQ3Z1wkLCsdlEyWy3H5GBnZMZmRJfgDc2dZi5lAE0puMhTyS1qw34P2J
         9MrSaVrFpXb8P7v25nw881EvfG7vZJCEHj45tH6I3sTsRJV3ymHtxfEUXIiNgfgUopOQ
         8U2w==
X-Gm-Message-State: AOAM530lMaqnS52U4kQrOddMRG5Ad7SPgbJZSkMrqj7MiwK/RaJX8nCA
	hn8iNHWPIJUlEHWiUmlwSxnN3wiIfzNwo2Ypr9c3QTbh
X-Google-Smtp-Source: ABdhPJyjYmKYwkmrNjBO0lVYclFiACiQIwht7Fr8W3PGSof4Slav7pBgn4SnnOS97LLxbFcPV7dmsQHM4oBwwcdDHUg=
X-Received: by 2002:a92:8404:: with SMTP id l4mr42107425ild.49.1608053767397;
 Tue, 15 Dec 2020 09:36:07 -0800 (PST)
MIME-Version: 1.0
From: Lokalgruppenleitung Bonn CdE <lokalleiter.cde.bonn@gmail.com>
Date: Tue, 15 Dec 2020 18:35:56 +0100
Message-ID: <CAJBhFmopLy3XW=fZ-=jBzEhwfKhUZ9cPEThauX+JV+kWt_E_SA@mail.gmail.com>
Subject: Test
To: mailman-migration@testmail.cde-ev.de
Content-Type: multipart/alternative; boundary="00000000000095e6f305b6843107"
X-MailFrom: lokalleiter.cde.bonn@gmail.com
X-Mailman-Rule-Hits: nonmember-moderation
X-Mailman-Rule-Misses: dmarc-mitigation; no-senders; approved; emergency; loop; banned-address; member-moderation
Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK
X-Message-ID-Hash: PRNZQCMT4PUEDIWYMIXGNRT4Y2I53NLK

--00000000000095e6f305b6843107
Content-Type: text/plain; charset="UTF-8"

Test-Mail

--00000000000095e6f305b6843107
Content-Type: text/html; charset="UTF-8"

<div dir="ltr">Test-Mail</div>

--00000000000095e6f305b6843107--
""".strip()
        mmlist = unittest.mock.MagicMock()
        mmlist.held = messages
        client = client_class.return_value
        client.get_list.return_value = mmlist

        #
        # Run
        #
        self.traverse({'href': '/ml/$'})
        self.traverse({'href': '/ml/mailinglist/99'})
        self.traverse({'href': '/ml/mailinglist/99/moderate'})
        self.assertTitle("Mailman-Migration – Nachrichtenmoderation")
        self.assertPresence("Finanzbericht")
        self.assertPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        mmlist.held = messages[1:]
        f = self.response.forms['acceptmsg1']
        self.submit(f)
        self.assertNonPresence("Finanzbericht")
        self.assertPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        mmlist.held = messages[2:]
        f = self.response.forms['rejectmsg2']
        self.submit(f)
        self.assertNonPresence("Finanzbericht")
        self.assertNonPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        mmlist.held = messages[3:]
        f = self.response.forms['discardmsg3']
        self.submit(f)
        self.assertNonPresence("Finanzbericht")
        self.assertNonPresence("Verschwurbelung")
        self.assertNonPresence("unerwartetes Erbe")

        #
        # Check
        #
        umcall = unittest.mock.call
        # Creation
        self.assertEqual(
            mmlist.moderate_message.call_args_list,
            [umcall(1, 'accept'), umcall(2, 'reject'), umcall(3, 'discard')])

    def test_log(self):
        # First: generate data
        self.test_mailinglist_management()
        self.logout()
        self.test_create_mailinglist()
        self.logout()

        # Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/log'})
        self.assertTitle("Mailinglisten-Log [1–9 von 9]")
        self.assertNonPresence("LogCodes")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 11, 20, 21, 22]
        f['mailinglist_id'] = 4

        self.submit(f)
        self.assertTitle("Mailinglisten-Log [1–4 von 4]")

        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/log'})
        self.assertTitle("Klatsch und Tratsch: Log [1–6 von 6]")
        self.logout()

        self.login(USER_DICT['berta'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/log'})
        self.assertTitle("Mailinglisten-Log [1–6 von 6]")
        self.assertPresence("Witz des Tages")
        self.assertNonPresence("Platin-Lounge")
        self.logout()

        self.login(USER_DICT['vera'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/log'})
        self.assertTitle("Mailinglisten-Log [1–6 von 6]")
        self.assertPresence("Aktivenforum 2001")
        self.assertNonPresence("CdE-Party")
        self.logout()

        self.login(USER_DICT['annika'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/log'})
        self.assertTitle("Mailinglisten-Log [0–0 von 0]")
        self.assertNonPresence("Aktivenforum")
        self.assertPresence("CdE-Party")
