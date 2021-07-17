#!/usr/bin/env python3

import csv
import re
import unittest.mock
from typing import Any, List, Tuple

import cdedb.database.constants as const
from cdedb.common import ADMIN_VIEWS_COOKIE_NAME, CdEDBObject
from cdedb.devsamples import MockHeldMessage, HELD_MESSAGE_SAMPLE
from cdedb.frontend.common import CustomCSVDialect
from cdedb.ml_type_aux import CdeLokalMailinglist
from cdedb.query import QueryOperators
from tests.common import USER_DICT, FrontendTest, as_users, prepsql


class TestMlFrontend(FrontendTest):
    @as_users("berta", "emilia", "janis")
    def test_index(self) -> None:
        self.traverse({'href': '/ml/'})

    @as_users("nina", "berta", "annika")
    def test_manually_write_subscription_states(self) -> None:
        self.traverse({'description': 'Mailinglisten'})
        self.assertTitle('Mailinglisten')

        # we show this only for ml admins, not for moderators or relative admins
        if self.user_in('nina'):
            self.assertPresence("Aktualisieren der Subscription States")
            f = self.response.forms['writesubscriptionstates']
            self.submit(f)
        else:
            self.assertNonPresence("Aktualisieren der Subscription States")

    @as_users("annika", "anton", "berta", "martin", "nina", "vera", "viktor")
    def test_sidebar(self) -> None:
        self.traverse({'description': 'Mailinglisten'})
        # Users with no administrated and no moderated mailinglists:
        if self.user_in('martin'):
            ins = {"Übersicht"}
            out = {"Alle Mailinglisten", "Moderierte Mailinglisten",
                   "Aktive Mailinglisten", "Nutzer verwalten", "Archivsuche", "Log"}
        # Users with core admin privileges for some mailinglists:
        elif self.user_in('vera'):
            ins = {"Aktive Mailinglisten", "Administrierte Mailinglisten", "Log",
                   "Nutzer verwalten", "Archivsuche"}
            out = {"Übersicht", "Alle Mailinglisten", "Moderierte Mailinglisten"}
        # Users with relative admin privileges for some mailinglists:
        elif self.user_in('viktor'):
            ins = {"Aktive Mailinglisten", "Administrierte Mailinglisten", "Log"}
            out = {"Übersicht", "Alle Mailinglisten", "Moderierte Mailinglisten",
                   "Nutzer verwalten", "Archivsuche"}
        # Users with moderated mailinglists and relative admin privileges
        # for some mailinglists:
        elif self.user_in('annika'):
            ins = {"Aktive Mailinglisten", "Administrierte Mailinglisten",
                   "Moderierte Mailinglisten", "Log"}
            out = {"Übersicht", "Alle Mailinglisten", "Nutzer verwalten", "Archivsuche"}
        # Users with moderated mailinglists, but no admin privileges.
        elif self.user_in('berta'):
            ins = {"Aktive Mailinglisten", "Moderierte Mailinglisten", "Log"}
            out = {"Übersicht", "Administrierte Mailinglisten", "Alle Mailinglisten",
                   "Nutzer verwalten", "Archivsuche"}
        # Users with full ml-admin privileges.
        elif self.user_in('nina'):
            ins = {"Aktive Mailinglisten", "Alle Mailinglisten",
                   "Accounts verschmelzen", "Nutzer verwalten", "Archivsuche", "Log"}
            out = {"Übersicht", "Moderierte Mailinglisten"}
        # Users with moderated mailinglists with full ml-admin privileges.
        elif self.user_in('anton'):
            ins = {"Aktive Mailinglisten", "Alle Mailinglisten",
                   "Accounts verschmelzen", "Moderierte Mailinglisten",
                   "Nutzer verwalten", "Archivsuche", "Log"}
            out = {"Übersicht"}
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("janis")
    def test_showuser(self) -> None:
        self.traverse({'href': '/core/self/show'})
        self.assertTitle(f"{self.user['given_names']} {self.user['family_name']}")

    @as_users("janis")
    def test_changeuser(self) -> None:
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        self.submit(f)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("nina", "ferdinand")
    def test_adminchangeuser(self) -> None:
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
    def test_toggleactivity(self) -> None:
        self.realm_admin_view_profile('janis', 'ml')
        checkbox = self.response.lxml.get_element_by_id('activity_checkbox')
        self.assertEqual(True, checkbox.get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        checkbox = self.response.lxml.get_element_by_id('activity_checkbox')
        self.assertEqual(False, checkbox.get('data-checked') == 'True')

    @as_users("nina", "vera")
    def test_user_search(self) -> None:
        self.traverse({'href': '/ml/$'}, {'href': '/ml/search/user'})
        self.assertTitle("Mailinglistennutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 's@'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Mailinglistennutzerverwaltung")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Jalapeño")

    @as_users("nina", "vera")
    def test_create_archive_user(self) -> None:
        self.check_create_archive_user('ml')

    @as_users("nina")
    def test_merge_accounts(self) -> None:
        self.traverse({'description': "Mailinglisten"},
                      {'description': "Accounts verschmelzen"})

        berta_id = USER_DICT['berta']['DB-ID']
        janis_id = USER_DICT['janis']['DB-ID']

        # try some failing cases
        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = USER_DICT['rowena']['DB-ID']
        f['target_persona_id'] = berta_id
        self.submit(f, check_notification=False)
        msg = "Der Quellnutzer muss ein reiner Mailinglistennutzer und darf kein Admin sein."
        self.assertValidationError('source_persona_id', msg)

        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = USER_DICT['nina']['DB-ID']
        f['target_persona_id'] = berta_id
        self.submit(f, check_notification=False)
        msg = "Der Quellnutzer muss ein reiner Mailinglistennutzer und darf kein Admin sein."
        self.assertValidationError('source_persona_id', msg)

        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = janis_id
        f['target_persona_id'] = "DB-100000-4"
        self.submit(f, check_notification=False)
        msg = "Dieser Benutzer existiert nicht oder ist archiviert."
        self.assertValidationError('target_persona_id', msg)

        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = janis_id
        f['target_persona_id'] = USER_DICT['hades']['DB-ID']
        self.submit(f, check_notification=False)
        msg = "Dieser Benutzer existiert nicht oder ist archiviert."
        self.assertValidationError('target_persona_id', msg)

        # The next case is possible in principle, but has a blocking mailinglist ...
        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = janis_id
        f['target_persona_id'] = berta_id
        self.submit(f, check_notification=False)
        msg = "Beide Benutzer haben einen Bezug zu gleichen Mailinglisten: Witz des Tages"
        self.assertPresence(msg, div='notifications')

        # ... so we resolve the blocking ...
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Witz des Tages'},
                      {'description': 'Erweiterte Verwaltung'})
        self.assertPresence("Beispiel", div='unsubscriber-list')
        f = self.response.forms['resetunsubscriberform2']
        self.submit(f)

        # ... and finally merge the two.
        self.traverse({'description': "Mailinglisten"},
                      {'description': "Accounts verschmelzen"})
        f = self.response.forms['merge-accounts']
        f['source_persona_id'] = janis_id
        f['target_persona_id'] = berta_id
        self.submit(f)

    @as_users("anton")
    def test_ml_admin_views(self) -> None:
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
    def test_show_mailinglist(self) -> None:
        self.traverse({'href': '/ml/$'},)
        self.assertTitle("Mailinglisten")
        self.traverse({'href': '/ml/mailinglist/4'})
        self.assertTitle("Klatsch und Tratsch")

    @as_users("kalif", "janis")
    def test_assembly_ml_privileges(self) -> None:
        self.traverse({'href': '/ml/$'}, )
        self.assertTitle("Mailinglisten")
        self.assertNonPresence("Veranstaltungslisten")
        self.assertNonPresence("CdE-Party")
        self.traverse({'href': '/ml/mailinglist/61'})
        self.assertTitle("Kanonische Beispielversammlung")
        self.assertNoLink(content="Kanonische Beispielversammlung")

    @as_users("berta", "emilia", "annika", "nina")
    def test_hide_admin_notes(self) -> None:
        # CdElokal Hogwarts
        ml_data = self.get_sample_datum('ml.mailinglists', 65)
        self.traverse({'description': 'Mailinglisten'},
                      {'description': ml_data['title']})
        # Make sure that admin notes exist.
        self.assertTrue(ml_data['notes'])
        if self.user_in("emilia", "nina"):
            # Nina is admin, Emilia is moderator, they should see the notes.
            self.assertPresence(ml_data['notes'])
        else:
            # Berta has no admin privileges, Annika has none _for this list_.
            self.assertNonPresence(ml_data['notes'])

    @as_users("annika", "anton", "berta", "martin", "nina", "vera", "werner")
    def test_sidebar_one_mailinglist(self) -> None:
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Feriendorf Bau'})
        everyone = {"Mailinglisten-Übersicht", "Übersicht"}
        moderator = {"Verwaltung", "Erweiterte Verwaltung", "Konfiguration",
                     "Nachrichtenmoderation", "Log"}

        # Moderators:
        out = set()
        if self.user_in('berta'):
            ins = everyone | moderator
        # Relative admins that are not also moderators:
        elif self.user_in('vera'):
            ins = everyone | moderator
        # Absolute admins that are not also moderators:
        elif self.user_in('anton', 'nina'):
            ins = everyone | moderator
        # Other users:
        elif self.user_in('annika', 'martin', 'werner'):
            ins = everyone
            out = moderator
        else:
            self.fail("Please adjust users for this tests.")

        self.check_sidebar(ins, out)

    @as_users("anton", "janis")
    def test_show_ml_buttons_change_address(self) -> None:
        # not-mandatory
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/3/show'},)
        self.assertTitle("Witz des Tages")
        if self.user_in('anton'):
            self.assertPresence("new-anton@example.cde")
        else:
            self.assertPresence("janis-spam@example.cde")
        self.assertIn("resetaddressform", self.response.forms)
        self.assertIn("unsubscribeform", self.response.forms)
        self.assertIn("changeaddressform", self.response.forms)
        self.assertNonPresence("Diese Mailingliste ist obligatorisch.")

        # mandatory
        # janis is no cde-member, so use inga instead
        if self.user_in('janis'):
            self.logout()
            self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/1/show'},)
        self.assertTitle("Verkündungen")
        if self.user_in('anton'):
            self.assertPresence("anton@example.cde (Standard)")
        else:
            self.assertPresence("inga@example.cde (Standard)")
        self.assertNotIn("resetaddressform", self.response.forms)
        self.assertNotIn("unsubscribeform", self.response.forms)
        self.assertNotIn("changeaddressform", self.response.forms)
        self.assertPresence("Diese Mailingliste ist obligatorisch.")

    @as_users("anton", "charly")
    def test_show_ml_buttons_mod_opt_in(self) -> None:
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
    def test_show_ml_buttons_opt_in(self) -> None:
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/7'},)
        self.assertTitle("Aktivenforum 2001")
        self.assertPresence("Du bist zurzeit kein Abonnent dieser Mailingliste")
        self.assertIn("subscribe-no-mod-form", self.response.forms)

        f = self.response.forms['subscribe-no-mod-form']
        self.submit(f)
        self.assertPresence("Du hast diese Mailingliste abonniert.")
        self.assertIn("unsubscribeform", self.response.forms)

    @as_users("akira", "inga")
    def test_show_ml_buttons_blocked(self) -> None:
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/11'},)
        self.assertTitle("Kampfbrief-Kommentare")
        self.assertPresence("Du kannst diese Mailingliste nicht abonnieren")
        self.assertNotIn("subscribe-mod-form", self.response.forms)
        self.assertNotIn("subscribe-no-mod-form", self.response.forms)

    @as_users("nina")
    def test_list_all_mailinglist(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Alle Mailinglisten")
        # Exemplarily, test mailinglist 54 in detail.
        self.assertPresence("Gutscheine", div="mailinglist-54-row")
        self.assertPresence("Mitglieder (Moderiertes Opt-in)", div="mailinglist-54-row")
        self.assertPresence("3", div="mailinglist-54-row")
        self.assertPresence("2 Abonnenten. 1 Moderator.", div="mailinglist-54-row")
        # Test if moderation hints work
        self.assertPresence("Mailman-Migration", div="mailinglist-99-row")
        self.assertPresence("Mitglieder (Opt-in)", div="mailinglist-99-row")
        self.assertPresence("3", div="mailinglist-99-row")
        self.assertPresence("0 Abonnenten. 1 Moderator.", div="mailinglist-99-row")
        # Test that events are shown
        self.assertPresence("Große Testakademie 2222")
        self.assertPresence("CdE-Party 2050")
        # not yet published
        self.assertNoLink("CdE-Party 2050")
        self.assertPresence("Internationaler Kongress")
        # Nina is no assembly user
        self.assertNoLink("Internationaler Kongress")
        self.assertPresence("Öffentliche Mailinglisten")
        self.traverse({'href': '/ml/mailinglist/6/show'})
        self.assertTitle("Aktivenforum 2000")

    @as_users("annika")
    def test_list_event_mailinglist(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Administrierte Mailinglisten")
        self.assertPresence("Große Testakademie 2222")
        self.assertPresence("CdE-Party 2050 Orgateam")
        self.assertPresence("Veranstaltungslisten")
        # Moderated, but not administered mailinglists
        self.assertNonPresence("Versammlungslisten")
        self.assertNonPresence("Mitgliedermailinglisten")
        self.assertNonPresence("Öffentliche Mailinglisten")
        self.assertNonPresence("CdE-All")

    @as_users("berta", "janis")
    def test_moderated_mailinglist(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/moderated'})
        self.assertTitle("Moderierte Mailinglisten")
        # Moderated mailinglists
        self.assertPresence("Mitgliedermailinglisten")
        self.assertPresence("Aktivenforum 2001", div="mailinglist-7-row")
        self.assertPresence("Mitglieder (Opt-in)", div="mailinglist-7-row")
        self.assertPresence("3", div="mailinglist-7-row")
        self.assertPresence("1 Abonnent. 2 Moderatoren.", div="mailinglist-7-row")
        if self.user_in('berta'):
            self.assertPresence("Veranstaltungslisten")
            self.assertPresence("CdE-Party 2050 Orgateam")
            # Inactive moderated mailinglists
            self.assertPresence("Aktivenforum 2000")
            self.traverse({'description': 'Aktivenforum 2000'})
            self.assertTitle("Aktivenforum 2000 – Verwaltung")

    @as_users("annika")
    def test_admin_moderated_mailinglist(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/moderated'})
        self.assertTitle("Moderierte Mailinglisten")
        # Moderated mailinglists
        self.assertPresence("Mitgliedermailinglisten")
        self.assertPresence("CdE-All")
        self.assertPresence("Veranstaltungslisten")
        self.assertPresence("CdE-Party 2050 Orgateam")
        # Administrated, not moderated mailinglists
        self.assertNonPresence("Große Testakademie 2222")
        self.assertNonPresence("Versammlungslisten")
        self.assertNonPresence("Andere Mailinglisten")

    @as_users("quintus")
    def test_mailinglist_cde_admin(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'},
                      {'href': '/ml/mailinglist/7/show'},
                      {'href': '/ml/mailinglist/7/management'})

    @as_users("nina", "berta")
    def test_mailinglist_management(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'})
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota", div="moderator-list")
        self.assertNonPresence("Anton Administrator", div="moderator-list")
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
        self.assertPresence("Inga Iota", div="moderator-list")
        self.assertPresence("Anton Administrator",
                            div="moderator-list")
        f = self.response.forms['removemoderatorform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota", div="moderator-list")
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
    def test_advanced_management(self) -> None:
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
        self.assertNonPresence("Inga Iota", div="modsubscriber-list")
        # Inga is now in SubscriptionState 'subscribed'
        # self.assertPresence("Inga Iota", div="unsubscriber-list")

        self.assertPresence("Emilia E. Eventis")
        f = self.response.forms['removemodunsubscriberform5']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Emilia", div="modunsubscriber-list")
        self.assertPresence("Emilia E. Eventis", div="unsubscriber-list")

        self.assertPresence("zelda@example.cde")
        f = self.response.forms['removewhitelistform1']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("zelda@example.cde")

    @as_users("nina")
    def test_remove_unsubscriptions(self) -> None:
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Werbung'},
                      {'description': 'Erweiterte Verwaltung'})
        self.assertTitle("Werbung – Erweiterte Verwaltung")
        self.assertPresence("Annika", div='unsubscriber-list')
        self.assertPresence("Ferdinand", div='unsubscriber-list')

        # remove Annikas unsubscription
        f = self.response.forms['resetunsubscriberform27']
        self.assertNotIn('addsubscriberform27', self.response.forms)
        self.submit(f)
        self.assertNonPresence("Annika", div='unsubscriber-list')

        # re-add Ferdinand, he got implicit subscribing rights
        f = self.response.forms['addsubscriberform6']
        self.assertNotIn('resetunsubscriberform6', self.response.forms)
        self.submit(f)
        self.assertNonPresence("Ferdinand", div='unsubscriber-list')

        # check that Ferdinand was subscribed, while Annikas relation was removed
        self.assertNonPresence('Annika')
        self.traverse({'description': 'Verwaltung'})
        self.assertTitle("Werbung – Verwaltung")
        self.assertNonPresence("Annika")
        self.assertPresence("Ferdinand", div="subscriber-list")

    @as_users("janis")
    def test_not_remove_unsubscriptions(self) -> None:
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Werbung'},
                      {'description': 'Erweiterte Verwaltung'})
        self.assertTitle("Werbung – Erweiterte Verwaltung")
        self.assertPresence("Annika", div='unsubscriber-list')
        self.assertPresence("Ferdinand", div='unsubscriber-list')

        self.assertNotIn('resetunsubscriberform27', self.response.forms)
        self.assertNotIn('addsubscriberform27', self.response.forms)
        self.assertNotIn('addsubscriberform6', self.response.forms)
        self.assertNotIn('resetunsubscriberform6', self.response.forms)

    # TODO add a presider as moderator and use him too in this test
    @as_users("nina")
    def test_mailinglist_management_outside_audience(self) -> None:
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
    def test_mailinglist_management_multi(self) -> None:
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
        self.assertPresence("Der Nutzer ist aktuell Abonnent.",
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
        self.assertPresence("Der Nutzer ist aktuell Abonnent.",
                            div='notifications')
        self.assertPresence("Änderung fehlgeschlagen.", div='notifications')

    @as_users("berta")
    def test_advanced_management_multi(self) -> None:
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
            self.assertPresence("Info! Der Nutzer ist ", div='notifications')
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
            # clean up
            for anid in [1, 2, 5, 7, 9]:
                self.assertTitle("Aktivenforum 2001 – Erweiterte Verwaltung")
                f = self.response.forms[f'remove{state}form{anid}']
                self.submit(f)

    @as_users("nina")
    def test_create_mailinglist(self) -> None:
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
        self.assertPresence("Admin-Team")
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
        self.assertPresence("Garcia Generalis")

    @as_users("nina")
    def test_change_mailinglist(self) -> None:
        self.traverse({'description': 'Mailinglisten'},
                      {'description': 'Alle Mailinglisten'},
                      {'description': 'Werbung'},
                      {'description': 'Konfiguration'},)
        self.assertTitle("Werbung – Konfiguration")

        # Check if the attachment policy hint works
        self.assertPresence("Admin-Team")
        f = self.response.forms['changelistform']
        f['domain'] = const.MailinglistDomain.testmail.value
        f['maxsize'] = "intentionally no valid maxsize"
        self.submit(f, check_notification=False)
        self.assertValidationError("maxsize", "Ungültige Eingabe für eine Ganzzahl.")
        self.assertPresence("Admin-Team")
        f = self.response.forms['changelistform']
        f['maxsize'] = 12
        self.submit(f)
        self.assertTitle("Werbung")
        self.traverse({'href': '/ml/mailinglist/2/change'}, )
        self.assertPresence("Admin-Team")
        f['domain'] = const.MailinglistDomain.lists.value
        self.submit(f)
        self.assertTitle("Werbung")
        self.traverse({'href': '/ml/mailinglist/2/change'}, )
        self.assertPresence("Admin-Team")

        # Test list deactivation
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
    def test_change_ml_type(self) -> None:
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
        event_title = self.get_sample_datum('event.events', event_id)['title']
        assembly_id = 1
        assembly_title = self.get_sample_datum(
            'assembly.assemblies', assembly_id)['title']

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
                    self.assertValidationError(
                        'assembly_id', "Ungültige Eingabe für eine Ganzzahl.")
                    f['assembly_id'] = assembly_id
                    self.submit(f)
                    self.traverse({'description': r"\sÜbersicht"})
                    self.assertPresence(
                        f"Mailingliste zur Versammlung {assembly_title}")

    @as_users("nina")
    def test_change_mailinglist_registration_stati(self) -> None:
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
    def test_delete_ml(self) -> None:
        self.get("/ml/mailinglist/2/show")
        self.assertTitle("Werbung")
        f = self.response.forms["deletemlform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertTitle("Alle Mailinglisten")
        self.assertNonPresence("Werbung")

    def test_subscription_request(self) -> None:
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
        f = self.response.forms['handlerequestform9']
        self.submit(f, button='action', value='accept')
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNotIn('handlerequestform9', self.response.forms)
        self.logout()
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertIn('unsubscribeform', self.response.forms)

    @as_users("charly", "inga")
    def test_subscribe_unsubscribe(self) -> None:
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
    def test_moderator_add_subscriber(self) -> None:
        self.get("/ml/mailinglist/7/management")
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = "DB-1-9"
        self.submit(f)
        self.assertPresence("Anton Administrator")

    def _create_mailinglist(self, mdata: CdEDBObject) -> None:
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

    def test_event_mailinglist(self) -> None:
        for i, u in enumerate(("emilia", "garcia", "inga")):
            if i > 0:
                self.setUp()
            user = USER_DICT[u]
            with self.subTest(user=u):
                self.login("anton")
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
                    self.assertPresence(user['family_name'], div='manage-orgas')
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
    def test_change_sub_address(self) -> None:
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['changeaddressform']
        f['email'] = "pepper@example.cde"
        self.submit(f, check_notification=False)
        self.assertTitle("Klatsch und Tratsch")
        link = self.fetch_link()
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
    def test_subscription_errors(self) -> None:
        # preparation: subscription request from inga
        user = self.user
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
            "Der Nutzer hat aktuell eine Abonnement-Anfrage gestellt.",
            div="notifications")
        # as mod subscriber
        self.traverse({'href': '/ml/mailinglist/4/management/advanced'}, )
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_ids'] = USER_DICT["inga"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer hat aktuell eine Abonnement-Anfrage gestellt.",
            div="notifications")
        # as mod unsubscribe
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_ids'] = USER_DICT["inga"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence(
            "Der Nutzer hat aktuell eine Abonnement-Anfrage gestellt.",
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
        self.assertPresence("Der Nutzer ist aktuell fixierter Abonnent.",
                            div="notifications")
        # try to add a mod unsubscribed user
        f = self.response.forms['addsubscriberform']
        f['subscriber_ids'] = USER_DICT["garcia"]["DB-ID"]
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-danger", self.response.text)
        self.assertPresence("Der Nutzer ist aktuell blockiert.", div="notifications")

    @as_users("berta", "janis")
    def test_moderator_access(self) -> None:
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
    def test_moderator_change_mailinglist(self) -> None:
        self.traverse({"description": "Mailinglisten"},
                      {"description": "CdE-Party 2050 Teilnehmer"},
                      {"description": "Konfiguration"})

        old_ml = self.get_sample_datum('ml.mailinglists', 60)
        f = self.response.forms['changelistform']

        # these properties are not allowed to be changed by moderators
        f['title'].force_value("Party-Time")
        f['local_part'].force_value("partyparty")
        f['event_id'].force_value(1)
        f['is_active'].force_value(False)
        # these properties can be changed by full moderators only
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
        if self.user_in('berta'):
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
    # add Janis as restricted moderator
    @prepsql("INSERT INTO ml.moderators (mailinglist_id, persona_id) VALUES (9, 10)")
    # add someone (Charly) in unsubscription override state
    @prepsql(f"INSERT INTO ml.subscription_states"
             f" (mailinglist_id, persona_id, subscription_state)"
             f" VALUES (9, 3, {const.SubscriptionState.unsubscription_override.value})")
    # add someone (Daniel) in subscription override state
    @prepsql(f"INSERT INTO ml.subscription_states"
             f" (mailinglist_id, persona_id, subscription_state)"
             f" VALUES (9, 4, {const.SubscriptionState.subscription_override.value})")
    # add someone (Ferdinand) in unsubscription state (no implicit subscribing right)
    @prepsql(f"INSERT INTO ml.subscription_states"
             f" (mailinglist_id, persona_id, subscription_state)"
             f" VALUES (9, 6, {const.SubscriptionState.unsubscribed.value})")
    # add someone (Werner) in request subscription state
    @prepsql(f"INSERT INTO ml.subscription_states"
             f" (mailinglist_id, persona_id, subscription_state)"
             f" VALUES (9, 23, {const.SubscriptionState.pending.value})")
    def test_restricted_moderator(self) -> None:
        self.traverse({"description": "Mailinglisten"},
                      {"description": "Teilnehmer-Liste"},
                      {"description": "Verwaltung"})
        self.assertPresence("Du hast nur eingeschränkten Moderator-Zugriff",
                            div="static-notifications")

        # he can neither add nor remove subscriptions ...
        self.assertNotIn('addsubscriberform', self.response.forms)
        self.assertPresence("Anton", div='subscriber-list')
        self.assertNotIn('removesubscriberform1', self.response.forms)

        self.assertPresence("Werner", div='pending-list')
        self.assertNotIn('blockrequestform23', self.response.forms)
        self.assertNotIn('denyrequestform23', self.response.forms)
        self.assertNotIn('approverequestform23', self.response.forms)

        # ... but he can add and remove moderators
        f = self.response.forms['addmoderatorform']
        f['moderators'] = USER_DICT['berta']['DB-ID']
        self.submit(f)
        self.assertPresence("Bertå", div='moderator-list')
        self.assertPresence("Garcia", div='moderator-list')
        f = self.response.forms['removemoderatorform7']
        self.submit(f)
        self.assertNonPresence("Garcia", div='moderator-list')

        self.traverse({"description": "Erweiterte Verwaltung"})
        self.assertPresence("Du hast nur eingeschränkten Moderator-Zugriff",
                            div="static-notifications")

        # he can neither add nor remove subscriptions ...
        self.assertNotIn('addmodsubscriberform', self.response.forms)
        self.assertPresence("Daniel", div='modsubscriber-list')
        self.assertNotIn('removemodsubscriberform4', self.response.forms)

        self.assertNotIn('addmodunsubscriberform', self.response.forms)
        self.assertPresence("Charly", div='modunsubscriber-list')
        self.assertNotIn('removemodsubscriberform3', self.response.forms)

        self.assertPresence("Ferdinand", div='unsubscriber-list')
        self.assertNotIn('resetunsubscriberform6', self.response.forms)
        # Emilia is already unsubscribed, but has implicit subscription rights
        self.assertPresence("Emilia", div="unsubscriber-list")
        self.assertNotIn('addsubscriberform5', self.response.forms)

        # ... but he can add and remove whitelist entries
        f = self.response.forms['addwhitelistform']
        f['email'] = "testmail@example.cde"
        self.submit(f)
        self.assertPresence("testmail@example.cde", div='whitelist')
        f = self.response.forms['removewhitelistform1']
        self.submit(f)

    @as_users("inga")
    def test_cdelokal_admin(self) -> None:
        self.traverse({"description": "Mailinglisten"},
                      {"description": "Hogwarts"})
        admin_note = self.get_sample_datum('ml.mailinglists', 65)['notes']
        self.assertPresence(admin_note, div="adminnotes")
        self.traverse({"description": "Verwaltung"})
        f = self.response.forms['addmoderatorform']
        f['moderators'] = self.user['DB-ID']
        self.submit(f)
        self.assertPresence(self.user['given_names'], div="moderator-list")
        f = self.response.forms[f"removemoderatorform{self.user['id']}"]
        self.submit(f)
        self.assertNonPresence(self.user['given_names'], div="moderator-list")
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
        self.assertEqual(len(f['ml_type'].options), 2)
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
                         len(CdeLokalMailinglist.domains))
        moderator = USER_DICT["berta"]
        f['moderators'] = moderator["DB-ID"]
        self.submit(f)
        self.assertTitle("Little Whinging")
        self.assertPresence(moderator['family_name'], div="moderator-list")

    @as_users("anton")
    def test_1342(self) -> None:
        self.get("/ml/mailinglist/60/change")
        f = self.response.forms['changelistform']
        tmp = {f.get("registration_stati", index=i).value for i in range(7)}
        sample_data_stati = set(
            str(x) for x in self.get_sample_data(
                "ml.mailinglists", (60,), ("registration_stati",)
            )[60]["registration_stati"])
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

    def _prepare_moderation_mock(self, client_class: unittest.mock.Mock) -> Tuple[
            List[MockHeldMessage], unittest.mock.MagicMock, Any]:
        messages = HELD_MESSAGE_SAMPLE
        mmlist = unittest.mock.MagicMock()
        moderation_response = unittest.mock.MagicMock()
        moderation_response.status = 204
        mmlist.moderate_message.return_value = moderation_response
        client = client_class.return_value
        client.get_held_messages.return_value = messages
        client.get_list_safe.return_value = mmlist

        return messages, mmlist, client

    @unittest.mock.patch("cdedb.frontend.common.CdEMailmanClient")
    @as_users("anton")
    def test_mailman_moderation(self, client_class: unittest.mock.Mock) -> None:
        #
        # Prepare
        #
        messages, mmlist, client = self._prepare_moderation_mock(client_class)

        #
        # Run
        #
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/99'},
                      {'href': '/ml/mailinglist/99/moderate'})
        self.assertTitle("Mailman-Migration – Nachrichtenmoderation")
        self.assertPresence("Finanzbericht")
        self.assertPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        client.get_held_messages.return_value = messages[1:]
        f = self.response.forms['msg1']
        self.submit(f, button='action', value='accept')
        self.assertNonPresence("Finanzbericht")
        self.assertPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        client.get_held_messages.return_value = messages[2:]
        f = self.response.forms['msg2']
        self.submit(f, button='action', value='reject')
        self.assertNonPresence("Finanzbericht")
        self.assertNonPresence("Verschwurbelung")
        self.assertPresence("unerwartetes Erbe")
        client.get_held_messages.return_value = messages[3:]
        f = self.response.forms['msg3']
        self.submit(f, button='action', value='discard')
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

    @unittest.mock.patch("cdedb.frontend.common.CdEMailmanClient")
    @as_users("anton")
    def test_mailman_whitelist(self, client_class: unittest.mock.Mock) -> None:
        #
        # Prepare
        #
        messages, mmlist, client = self._prepare_moderation_mock(client_class)

        #
        # Run
        #
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'},
                      {'href': '/ml/mailinglist/99/moderate'})
        self.assertTitle("Mailman-Migration – Nachrichtenmoderation")
        self.assertPresence("Finanzbericht")
        self.assertPresence("kassenwart@example.cde")
        client.get_held_messages.return_value = messages[1:]
        f = self.response.forms['msg1']
        self.submit(f, button='action', value='whitelist')
        self.assertNonPresence("Finanzbericht")
        self.traverse({'description': "Log"})
        self.assertPresence("Whitelist-Eintrag hinzugefügt", div="1-1001")
        self.assertPresence("kassenwart@example.cde", div="1-1001")

    def test_log(self) -> None:
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
