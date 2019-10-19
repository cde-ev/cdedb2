#!/usr/bin/env python3

import csv
import json
import unittest
import webtest

from test.common import as_users, USER_DICT, FrontendTest

from cdedb.query import QueryOperators

class TestMlFrontend(FrontendTest):
    @as_users("anton", "berta", "emilia", "janis")
    def test_index(self, user):
        self.traverse({'href': '/ml/'})

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

    @as_users("anton", "ferdinand")
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

    @as_users("anton", "ferdinand")
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

    @as_users("anton", "ferdinand")
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

    @as_users("anton")
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

    @as_users("berta", "janis")
    def test_show_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},)
        self.assertTitle("Mailinglisten")
        self.traverse({'href': '/ml/mailinglist/4'})
        self.assertTitle("Klatsch und Tratsch")

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

    @as_users("anton", "janis")
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

    @as_users("anton", "inga")
    def test_show_ml_buttons_blocked(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/mailinglist/11'},)
        self.assertTitle("Kampfbrief-Kommentare")
        self.assertPresence("Du kannst diese Mailingliste nicht abonnieren")
        self.assertNotIn("subscribe-mod-form", self.response.forms)
        self.assertNotIn("subscribe-no-mod-form", self.response.forms)

    @as_users("nina")
    def test_show_other_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},)
        self.assertTitle("Mailinglisten")
        self.assertPresence("Allgemeine Mailinglisten")
        self.assertPresence("Andere Mailinglisten")
        self.assertPresence("Sozialistischer Kampfbrief")

    @as_users("anton")
    def test_list_all_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Mailinglisten Komplettübersicht")
        self.traverse({'href': '/ml/mailinglist/6'})
        self.assertTitle("Aktivenforum 2000 – Verwaltung")

    @as_users("anton", "ferdinand", "berta")
    def test_mailinglist_management(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'})
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota")
        f = self.response.forms['addmoderatorform']
        f['moderator_id'] = "DB-9-4"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertPresence("Inga Iota")
        f = self.response.forms['removemoderatorform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Inga Iota")
        self.assertPresence("Janis Jalapeño")
        f = self.response.forms['removesubscriberform10']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNonPresence("Janis Jalapeño")
        self.assertNotIn("removesubscriberform9", self.response.forms)
        f = self.response.forms['addsubscriberform']
        f['subscriber_id'] = "DB-9-4"
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

    @as_users("anton", "berta", "ferdinand")
    def test_advanced_management(self, user):
        class dialect(csv.Dialect):
            delimiter = ';'
            quotechar = '"'
            doublequote = False
            escapechar = '\\'
            lineterminator = '\n'
            quoting = csv.QUOTE_MINIMAL

        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management/advanced'})

        # add some persona
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Inga Iota")
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_id'] = "DB-9-4"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Inga Iota")

        self.assertNonPresence("Emilia E. Eventis")
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_id'] = "DB-5-1"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Emilia E. Eventis")

        self.assertNonPresence("zelda@example.cde")
        f = self.response.forms['addwhitelistform']
        f['email'] = "zelda@example.cde"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("zelda@example.cde")

        # now check the download file

        save = self.response

        self.traverse({"href": "ml/mailinglist/4/download"})

        result = list(csv.DictReader(self.response.body.decode('utf-8-sig')
            .split("\n"), delimiter=";", dialect=dialect))
        all_rows = []

        for row in result:
            line = (row['db_id'] + ";" + row['given_names'] + ";" +
                    row['family_name'] + ";" + row['subscription_state'] + ";" +
                    row['email'] + ";" + row['subscription_address'])
            all_rows.append(line)

        self.assertIn('DB-5-1;Emilia E.;Eventis;mod_unsubscribed;'
                      'emilia@example.cde;', all_rows)
        self.assertIn('DB-9-4;Inga;Iota;mod_subscribed;'
                      'inga@example.cde;', all_rows)

        # remove the former added persona
        self.response = save

        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertPresence("Inga Iota")
        f = self.response.forms['removemodsubscribeform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Inga Iota")

        self.assertPresence("Emilia E. Eventis")
        f = self.response.forms['removemodunsubscribeform5']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("Emilia E. Eventis")

        self.assertPresence("zelda@example.cde")
        f = self.response.forms['removewhitelistform1']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Erweiterte Verwaltung")
        self.assertNonPresence("zelda@example.cde")

    @as_users("anton", "berta")
    def test_mailinglist_management_outside_audience(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/5'},
                      {'href': '/ml/mailinglist/5/management/advanced'})
        self.assertTitle("Sozialistischer Kampfbrief – Erweiterte Verwaltung")
        self.assertNonPresence("Janis Jalapeño")
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_id'] = "DB-10-8"
        self.submit(f)
        self.assertTitle("Sozialistischer Kampfbrief – Erweiterte Verwaltung")
        self.assertPresence("Janis Jalapeño")

    @as_users("anton")
    def test_create_mailinglist(self, user):
        self.traverse({'href': '/ml/$'})
        self.assertTitle("Mailinglisten")
        self.assertNonPresence("Munkelwand")
        self.traverse({'href': '/ml/mailinglist/create$'})
        self.assertTitle("Mailingliste anlegen")
        f = self.response.forms['createlistform']
        f['title'] = "Munkelwand"
        f['address'] = "munkelwand@example.cde"
        f['sub_policy'] = 3
        f['mod_policy'] = 1
        f['attachment_policy'] = 2
        f['audience_policy'] = 1
        f['subject_prefix'] = "[munkel]"
        f['maxsize'] = 512
        f['is_active'].checked = True
        f['notes'] = "Noch mehr Gemunkel."
        self.submit(f)
        self.assertTitle("Munkelwand")

    @as_users("anton")
    def test_change_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/2'},
                      {'href': '/ml/mailinglist/2/change'},)
        self.assertTitle("Werbung – Konfiguration")
        f = self.response.forms['changelistform']
        self.assertEqual("Werbung", f['title'].value)
        f['title'] = "Munkelwand"
        self.assertEqual("werbung@example.cde", f['address'].value)
        f['address'] = "munkelwand@example.cde"
        self.assertEqual("2", f['sub_policy'].value)
        f['sub_policy'] = 4
        f['audience_policy'] = 2
        self.assertTrue(f['is_active'].checked)
        f['is_active'].checked = False
        self.submit(f)
        self.assertTitle("Munkelwand")
        self.traverse({'href': '/ml/mailinglist/2/change'},)
        f = self.response.forms['changelistform']
        self.assertEqual("Munkelwand", f['title'].value)
        self.assertEqual("munkelwand@example.cde", f['address'].value)
        self.assertEqual("4", f['sub_policy'].value)
        self.assertFalse(f['is_active'].checked)
        self.traverse({'href': '/ml/$'})
        self.assertTitle("Mailinglisten")
        self.assertNonPresence("Munkelwand")
        
    @as_users("anton")
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

    @as_users("anton")
    def test_delete_ml(self, user):
        self.get("/ml/mailinglist/2/management")
        self.assertTitle("Werbung – Verwaltung")
        f = self.response.forms["deletemlform"]
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertTitle("Mailinglisten Komplettübersicht")
        self.assertNonPresence("Werbung")

    def test_subscription_request(self):
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribe-mod-form']
        self.submit(f, check_notification=False)
        self.logout()
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'},)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        f = self.response.forms['acceptrequestform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch – Verwaltung")
        self.assertNotIn('acceptrequestform9', self.response.forms)
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
        f['subscriber_id'] = "DB-1-9"
        self.submit(f)
        self.assertPresence("Anton Armin A. Administrator")

    @as_users("janis")
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

    @as_users("anton", "berta")
    def test_subscription_errors(self, user):
        # preparation: subscription request from inga
        self.logout()
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'}, )
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribe-mod-form']
        self.submit(f, check_notification=False)
        self.logout()
        self.login(user)
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'}, )
        self.assertTitle("Klatsch und Tratsch – Verwaltung")

        # testing: try to add a subscription request
        # as normal user
        f = self.response.forms['addsubscriberform']
        f['subscriber_id'] = "DB-9-4"
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertIn(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            self.response.text)
        # as mod subscriber
        self.traverse({'href': '/ml/mailinglist/4/management/advanced'}, )
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_id'] = "DB-9-4"
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertIn(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            self.response.text)
        # as mod unsubscribe
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_id'] = "DB-9-4"
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertIn(
            "Der Nutzer hat bereits eine Abonnement-Anfrage gestellt.",
            self.response.text)

        # testing: mod subscribe and unsubscribe
        # add already subscribed user as mod subscribe
        f = self.response.forms['addmodsubscriberform']
        f['modsubscriber_id'] = "DB-1-9"
        self.submit(f, check_notification=True)
        # add already subscribed user as mod unsubscribe
        f = self.response.forms['addmodunsubscriberform']
        f['modunsubscriber_id'] = "DB-10-8"
        self.submit(f, check_notification=True)
        # try to remove mod subscribe with normal subscriber form
        self.traverse({'href': '/ml/mailinglist/4/management'}, )
        f = self.response.forms['removesubscriberform1']
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertIn(
            "Der Nutzer kann nicht entfernt werden, da er fixiert ist. "
            "Dies kannst du unter Erweiterte Verwaltung ändern.",
            self.response.text)
        # try to add a mod unsubscribed user
        f = self.response.forms['addsubscriberform']
        f['subscriber_id'] = "DB-10-8"
        self.submit(f, check_notification=False)
        self.assertIn("alert alert-warning", self.response.text)
        self.assertIn("Der Nutzer wurde geblockt. "
                      "Dies kannst du unter Erweiterte Verwaltung ändern.",
                      self.response.text)

    def test_export(self):
        HEADERS = {'SCRIPTKEY': "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"}
        expectation =  [{'address': 'announce@example.cde', 'is_active': True},
                        {'address': 'werbung@example.cde', 'is_active': True},
                        {'address': 'witz@example.cde', 'is_active': True},
                        {'address': 'klatsch@example.cde', 'is_active': True},
                        {'address': 'kongress@example.cde', 'is_active': True},
                        {'address': 'aktivenforum2000@example.cde', 'is_active': False},
                        {'address': 'aktivenforum@example.cde', 'is_active': True},
                        {'address': 'aka@example.cde', 'is_active': True},
                        {'address': 'participants@example.cde', 'is_active': True},
                        {'address': 'wait@example.cde', 'is_active': True},
                        {'address': 'opt@example.cde', 'is_active': True}]
        self.get("/ml/script/all", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {
            'address': 'werbung@example.cde',
            'admin_address': 'werbung-owner@example.cde',
            'listname': 'Werbung',
            'moderators': ['janis@example.cde'],
            'sender': 'werbung@example.cde',
            'size_max': None,
            'subscribers': ['anton@example.cde',
                            'berta@example.cde',
                            'charly@example.cde',
                            'daniel@example.cde',
                            'emilia@example.cde',
                            'garcia@example.cde',
                            'inga@example.cde',
                            'janis@example.cde',
                            'kalif@example.cde',
                            'martin@example.cde',
                            'nina@example.cde'],
            'whitelist': ['honeypot@example.cde']}
        self.get("/ml/script/one?address=werbung@example.cde", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)

    def test_oldstyle_access(self):
        HEADERS = {'SCRIPTKEY': "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"}
        expectation = [{'address': 'announce@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': True},
                       {'address': 'werbung@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'witz@example.cde',
                        'inactive': False,
                        'maxsize': 2048,
                        'mime': None},
                       {'address': 'klatsch@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'kongress@example.cde',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aktivenforum2000@example.cde',
                        'inactive': True,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aktivenforum@example.cde',
                        'inactive': False,
                        'maxsize': 1024,
                        'mime': None},
                       {'address': 'aka@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'participants@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'wait@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False},
                       {'address': 'opt@example.cde',
                        'inactive': False,
                        'maxsize': None,
                        'mime': False}]
        self.get("/ml/script/all/compat", headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {'address': 'werbung@example.cde',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': '[werbung]',
                       'moderators': ['janis@example.cde',],
                       'sender': 'werbung-bounces@example.cde',
                       'subscribers': ['anton@example.cde',
                                       'berta@example.cde',
                                       'charly@example.cde',
                                       'daniel@example.cde',
                                       'emilia@example.cde',
                                       'garcia@example.cde',
                                       'inga@example.cde',
                                       'janis@example.cde',
                                       'kalif@example.cde',
                                       'martin@example.cde',
                                       'nina@example.cde'],
                       'whitelist': ['honeypot@example.cde',]}
        self.get("/ml/script/one/compat?address=werbung@example.cde",
                 headers=HEADERS)
        self.assertEqual(expectation, self.response.json)
        expectation = {'address': 'werbung@example.cde',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': '[werbung]',
                       'moderators': ['janis@example.cde',],
                       'sender': 'cdedb-doublebounces@cde-ev.de',
                       'subscribers': ['janis@example.cde',],
                       'whitelist': ['*']}
        self.get("/ml/script/mod/compat?address=werbung@example.cde",
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
        self.assertPresence("Nur Administratoren dürfen die Mailinglisten-"
                            "Konfiguration ändern.", div="notifications")
        self.assertNotIn('changelistform', self.response.forms)
        # TODO check that form elements are readonly

        self.traverse({"href": "ml/mailinglist/3/log"})
        self.assertTitle("Witz des Tages: Log")

    def test_log(self):
        ## First: generate data
        self.test_mailinglist_management()
        self.logout()
        self.test_create_mailinglist()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/log'})
        self.assertTitle("Mailinglisten-Log [0–6]")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 11, 20, 21, 22]
        f['mailinglist_id'] = 4
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Mailinglisten-Log [1–2]")

        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/log'})
        self.assertTitle("Klatsch und Tratsch: Log [0–5]")
