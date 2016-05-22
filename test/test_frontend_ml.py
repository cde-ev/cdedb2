#!/usr/bin/env python3

import unittest
import quopri
import webtest
from test.common import as_users, USER_DICT, FrontendTest

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
        self.admin_view_profile('janis', realm="ml")
        self.traverse({'href': '/ml/user/10/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['notes'] = "Blowing in the wind."
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Janis Jalapeño")
        self.assertPresence("Blowing in the wind.")

    @as_users("anton")
    def test_toggleactivity(self, user):
        self.admin_view_profile('janis', realm="ml")
        self.assertEqual(
            True,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertEqual(
            False,
            self.response.lxml.get_element_by_id('activity_checkbox').checked)

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/search/user'})
        self.assertTitle("Mailinglistennutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_username'] = 's@'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Mailinglistennutzersuche")
        self.assertPresence("Ergebnis -- 1 Eintrag gefunden")
        self.assertPresence("Jalapeño")

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'href': '/ml/$'}, {'href': '/ml/user/create'})
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
        self.assertPresence("some fancy talk")

    def test_genesis(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/core/genesis/request'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "ml"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen (zurzeit 1 zu begutachten)")
        f = self.response.forms['genesisapprovalform1']
        f['realm'] = "ml"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.assertTitle("Accountanfragen (zurzeit 0 zu begutachten)")
        self.logout()
        self.get(link)
        self.assertTitle("Mailinglistenaccount anlegen")
        data = {
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "display_name": 'Zelda',
        }
        f = self.response.forms['newuserform']
        f['display_name'] = data['display_name']
        self.submit(f)
        self.assertTitle("Passwort zurücksetzen -- Bestätigung")
        new_password = "saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        self.submit(f)
        new_user = {
            'id': 11,
            'username': "zelda@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")

    @as_users("berta", "janis")
    def test_show_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'})
        self.assertTitle("Mailinglisten Übersicht")
        self.traverse({'href': '/ml/mailinglist/4'})
        self.assertTitle("Klatsch und Tratsch")

    @as_users("anton")
    def test_list_all_mailinglist(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list/all'})
        self.assertTitle("Mailinglisten Komplettübersicht")
        self.traverse({'href': '/ml/mailinglist/6'})
        self.assertTitle("Aktivenforum 2000")

    @as_users("anton", "berta")
    def test_mailinglist_management(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
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
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'})
        self.assertTitle("Mailinglisten Übersicht")
        self.assertNonPresence("Munkelwand")
        self.traverse({'href': '/ml/mailinglist/create$'})
        self.assertTitle("Mailingliste anlegen")
        f = self.response.forms['createlistform']
        f['title'] = "Munkelwand"
        f['address'] = "munkelwand@example.cde"
        f['sub_policy'] = 2
        f['mod_policy'] = 0
        f['attachment_policy'] = 1
        f['audience_policy'] = 0
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
        self.assertTitle("Werbung -- Konfiguration")
        f = self.response.forms['changelistform']
        self.assertEqual("Werbung", f['title'].value)
        f['title'] = "Munkelwand"
        self.assertEqual("werbung@example.cde", f['address'].value)
        f['address'] = "munkelwand@example.cde"
        self.assertEqual("1", f['sub_policy'].value)
        f['sub_policy'] = 2
        f['audience_policy'] = 0
        self.assertTrue(f['is_active'].checked)
        f['is_active'].checked = False
        self.submit(f)
        self.assertTitle("Munkelwand")
        self.traverse({'href': '/ml/mailinglist/2/change'},)
        f = self.response.forms['changelistform']
        self.assertEqual("Munkelwand", f['title'].value)
        self.assertEqual("munkelwand@example.cde", f['address'].value)
        self.assertEqual("2", f['sub_policy'].value)
        self.assertFalse(f['is_active'].checked)
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'})
        self.assertTitle("Mailinglisten Übersicht")
        self.assertNonPresence("Munkelwand")

    def test_subscription_request(self):
        self.login(USER_DICT['inga'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertTitle("Klatsch und Tratsch")
        f = self.response.forms['subscribeform']
        self.submit(f, check_notification=False)
        self.logout()
        self.login(USER_DICT['berta'])
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
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
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},)
        self.assertIn('unsubscribeform', self.response.forms)

    @as_users("charly", "inga")
    def test_subscribe_unsubscribe(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
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
                      {'href': '/ml/mailinglist/list$'},
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

    @as_users("anton")
    def test_check_states(self, user):
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/3'},
                      {'href': '/ml/mailinglist/3/management'},
                      {'href': '/ml/mailinglist/3/check'},)
        self.assertTitle("Witz des Tages -- Konsistenzcheck")
        self.assertNonPresence("Janis Jalapeño")
        self.traverse({'href': '/ml/mailinglist/3/change'},)
        self.assertTitle("Witz des Tages -- Konfiguration")
        f = self.response.forms['changelistform']
        f['audience_policy'] = 4
        self.submit(f)
        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/3'},
                      {'href': '/ml/mailinglist/3/management'},
                      {'href': '/ml/mailinglist/3/check'},)
        self.assertTitle("Witz des Tages -- Konsistenzcheck")
        self.assertPresence("Janis Jalapeño")

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
        self.assertTitle("\nMailinglisten -- Logs (0--7)\n")
        f = self.response.forms['logshowform']
        f['codes'] = [10, 11, 20, 21, 22]
        f['mailinglist_id'] = 4
        f['start'] = 1
        f['stop'] = 10
        self.submit(f)
        self.assertTitle("\nMailinglisten -- Logs (1--3)\n")

        self.traverse({'href': '/ml/$'},
                      {'href': '/ml/mailinglist/list$'},
                      {'href': '/ml/mailinglist/4'},
                      {'href': '/ml/mailinglist/4/log'})
        self.assertTitle("\nKlatsch und Tratsch -- Logs (0--6)\n")
