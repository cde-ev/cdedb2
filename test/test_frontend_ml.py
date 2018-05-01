#!/usr/bin/env python3

import unittest
import quopri
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

    @as_users("anton")
    def test_adminchangeuser(self, user):
        self.admin_view_profile('janis')
        self.traverse({'href': '/core/persona/10/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.assertNotIn('birthday', f.fields)
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Janis Jalapeño")

    @as_users("anton")
    def test_toggleactivity(self, user):
        self.admin_view_profile('janis')
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').get('data-checked') == 'True')

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/search/user'})
        self.assertTitle("Mailinglisten-Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.similar.value
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

    @as_users("anton")
    def test_list_all_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list'})
        self.assertTitle("Mailinglisten Komplettübersicht")
        self.traverse({'href': '/ml/mailinglist/6'})
        self.assertTitle("Aktivenforum 2000")

    @as_users("anton", "berta")
    def test_mailinglist_management(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'})
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertNonPresence("Inga Iota")
        f = self.response.forms['addmoderatorform']
        f['moderator_id'] = "DB-9-E"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertPresence("Inga Iota")
        f = self.response.forms['removemoderatorform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertNonPresence("Inga Iota")
        self.assertNonPresence("zelda@example.cde")
        f = self.response.forms['addwhitelistform']
        f['email'] = "zelda@example.cde"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertPresence("zelda@example.cde")
        f = self.response.forms['removewhitelistform1']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("Janis Jalapeño")
        f = self.response.forms['removesubscriberform10']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertNonPresence("Janis Jalapeño")
        self.assertNotIn("removesubscriberform9", self.response.forms)
        f = self.response.forms['addsubscriberform']
        f['subscriber_id'] = "DB-9-E"
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertIn("removesubscriberform9", self.response.forms)

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

    def test_subscription_request(self):
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribeform']
        self.submit(f, check_notification=False)
        self.logout()
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/management'},)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        f = self.response.forms['ackrequestform9']
        self.submit(f)
        self.assertTitle("Klatsch und Tratsch -- Verwalten")
        self.assertNotIn('ackrequestform9', self.response.forms)
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
        f = self.response.forms['subscribeform']
        self.submit(f)
        self.assertTitle("Witz des Tages")
        f = self.response.forms['unsubscribeform']
        self.submit(f)
        self.assertTitle("Witz des Tages")
        self.assertIn('subscribeform', self.response.forms)

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
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
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

    @as_users("anton")
    def test_check_states(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/3'},
                      {'href': '/ml/mailinglist/3/management'},
                      {'href': '/ml/mailinglist/3/check'},)
        self.assertTitle("Witz des Tages – Konsistenzcheck")
        self.assertNonPresence("Janis Jalapeño")
        self.traverse({'href': '/ml/mailinglist/3/change'},)
        self.assertTitle("Witz des Tages – Konfiguration")
        f = self.response.forms['changelistform']
        f['audience_policy'] = 5
        self.submit(f)
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/3'},
                      {'href': '/ml/mailinglist/3/management'},
                      {'href': '/ml/mailinglist/3/check'},)
        self.assertTitle("Witz des Tages – Konsistenzcheck")
        self.assertPresence("Janis Jalapeño")

    @as_users("anton")
    def test_overrides(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/3'},
                      {'href': '/ml/mailinglist/3/change'},)
        self.assertTitle("Witz des Tages – Konfiguration")
        f = self.response.forms['changelistform']
        f['audience_policy'] = 5
        self.submit(f)
        self.traverse({'href': '/ml/mailinglist/3/management'},
                      {'href': '/ml/mailinglist/3/check'},)
        self.assertTitle("Witz des Tages – Konsistenzcheck")
        self.assertPresence("Janis Jalapeño")
        self.assertNonPresence("Ausnahmen")
        f = self.response.forms['markoverrideform10']
        self.submit(f)
        self.assertTitle("Witz des Tages – Konsistenzcheck")
        self.assertPresence("Janis Jalapeño")
        self.assertPresence("Ausnahmen")

    def test_export(self):
        self.app.set_cookie('scriptkey', "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3")
        expectation =  [{'address': 'announce@example.cde', 'is_active': True},
                        {'address': 'werbung@example.cde', 'is_active': True},
                        {'address': 'witz@example.cde', 'is_active': True},
                        {'address': 'klatsch@example.cde', 'is_active': True},
                        {'address': 'kongress@example.cde', 'is_active': True},
                        {'address': 'aktivenforum2000@example.cde', 'is_active': False},
                        {'address': 'aktivenforum@example.cde', 'is_active': True},
                        {'address': 'aka@example.cde', 'is_active': True},
                        {'address': 'participants@example.cde', 'is_active': True},
                        {'address': 'wait@example.cde', 'is_active': True}]
        self.get("/ml/script/all")
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
                            'emilia@example.cde',
                            'garcia@example.cde',
                            'inga@example.cde',
                            'janis@example.cde',
                            'kalif@example.cde'],
            'whitelist': ['honeypot@example.cde']}
        self.get("/ml/script/one?address=werbung@example.cde")
        self.assertEqual(expectation, self.response.json)

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
        self.assertTitle("Log: Mailinglisten [0–7]")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 11, 20, 21, 22]
        f['mailinglist_id'] = 4
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("Log: Mailinglisten [1–3]")

        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/log'})
        self.assertTitle("Log: Klatsch und Tratsch [0–6]")
