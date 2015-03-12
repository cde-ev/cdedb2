#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.query import QUERY_SPECS, QueryOperators
from cdedb.common import PrivilegeError
import cdedb.database.constants as const
import datetime
import decimal

class TestMlBackend(BackendTest):
    used_backends = ("core", "ml")

    @as_users("janis")
    def test_basics(self, user):
        data = self.ml.get_data_one(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['family_name'] = "Lord von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'given_names', 'family_name'}}
        self.ml.change_user(self.key, setter)
        new_data = self.ml.get_data_one(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("janis")
    def test_entity_mailinglist(self, user):
        expectation = {1: 'Verkündungen',
                       2: 'Werbung',
                       3: 'Witz des Tages',
                       4: 'Klatsch und Tratsch',
                       5: 'Sozialistischer Kampfbrief',
                       7: 'Aktivenforum 2001',
                       8: 'Orga-Liste',
                       9: 'Teilnehmer-Liste',
                       10: 'Warte-Liste'}
        self.assertEqual(expectation, self.ml.list_mailinglists(self.key))
        expectation[6] = 'Aktivenforum 2000'
        self.assertEqual(expectation,
                         self.ml.list_mailinglists(self.key, active_only=False))
        expectation = {2: 'Werbung',
                       3: 'Witz des Tages',
                       4: 'Klatsch und Tratsch'}
        self.assertEqual(expectation, self.ml.list_mailinglists(
            self.key, status=40, active_only=False))
        expectation = {
            3: {'address': 'witz@example.cde',
                'description': "Einer geht noch ...",
                'assembly_id': None,
                'attachement_policy': 1,
                'audience': [0, 1, 2, 40],
                'event_id': None,
                'gateway': None,
                'id': 3,
                'is_active': True,
                'maxsize': 2048,
                'mod_policy': 1,
                'moderators': {2, 3, 10},
                'registration_stati': [],
                'sub_policy': 2,
                'subject_prefix': '[witz]',
                'title': 'Witz des Tages',
                'notes': None,
                'whitelist': set()},
            5: {'address': 'kongress@example.cde',
                'description': None,
                'assembly_id': 1,
                'attachement_policy': 1,
                'audience': [0, 1, 30],
                'event_id': None,
                'gateway': None,
                'id': 5,
                'is_active': True,
                'maxsize': 1024,
                'mod_policy': 1,
                'moderators': {2},
                'registration_stati': [],
                'sub_policy': 4,
                'subject_prefix': '[kampf]',
                'title': 'Sozialistischer Kampfbrief',
                'notes': None,
                'whitelist': set()},
            7: {'address': 'aktivenforum@example.cde',
                'description': None,
                'assembly_id': None,
                'attachement_policy': 1,
                'audience': [0, 1],
                'event_id': None,
                'gateway': 6,
                'id': 7,
                'is_active': True,
                'maxsize': 1024,
                'mod_policy': 1,
                'moderators': {2, 10},
                'registration_stati': [],
                'sub_policy': 4,
                'subject_prefix': '[aktivenforum]',
                'title': 'Aktivenforum 2001',
                'notes': None,
                'whitelist': {'aliens@example.cde',
                              'captiankirk@example.cde',
                              'drwho@example.cde'}}}
        self.assertEqual(expectation,
                         self.ml.get_mailinglists(self.key, (3, 5, 7)))
        setter = {
            'id': 7,
            'maxsize': 3096,
            'moderators': {1, 10},
            'whitelist': {'aliens@example.cde',
                           'captiankirk@example.cde',
                           'picard@example.cde'},
            'sub_policy': 3,
            'is_active': False,
            'address': 'passivenforum@example.cde',
            'notes': "this list is no more",
        }
        expectation = expectation[7]
        expectation.update(setter)
        self.assertLess(0, self.ml.set_mailinglist(self.key, setter))
        self.assertEqual(expectation, self.ml.get_mailinglist(self.key, 7))

    @as_users("anton")
    def test_mailinglist_creation_deletion(self, user):
        oldlists = self.ml.list_mailinglists(self.key)
        new_data = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachement_policy': 2,
            'audience': [0],
            'event_id': None,
            'gateway': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 0,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 4,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {'fidel@example.cde',
                          'che@example.cde',}}
        new_id = self.ml.create_mailinglist(self.key, new_data)
        self.assertLess(0, new_id)
        self.assertNotIn(new_id, oldlists)
        self.assertIn(new_id, self.ml.list_mailinglists(self.key))
        new_data['id'] = new_id
        self.assertEqual(new_data, self.ml.get_mailinglist(self.key, new_id))
        self.assertLess(0, self.ml.delete_mailinglist(self.key, new_id,
                                                      cascade=True))
        self.assertNotIn(new_id, self.ml.list_mailinglists(self.key))

    @as_users("anton", "berta")
    def test_subscriptions(self, user):
        expectation = {1: None, 2: None, 4: None, 5: None, 7: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 2))

    @as_users("anton", "janis")
    def test_subscriptions_two(self, user):
        expectation = {1: None, 2: None, 3: 'janis-spam@example.cde', 4: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 10))

    @as_users("anton", "emilia")
    def test_subscriptions_three(self, user):
        expectation = {1: None, 2: None, 9: None, 10: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 5))

    @as_users("anton", "garcia")
    def test_subscriptions_four(self, user):
        expectation = {1: None, 2: None, 8: None, 9: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 7))

    @as_users("anton", "janis")
    def test_subscribers(self, user):
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       3: 'charly@example.cde',
                       7: 'garcia@example.cde',
                       9: 'inga@example.cde',
                       10: 'janis@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 2))
        expectation = {1: 'anton@example.cde', 10: 'janis-spam@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 3))
        expectation = {2: 'berta@example.cde', 3: 'charly@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 7))

    @as_users("anton", "berta")
    def test_subscribers_two(self, user):
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       9: 'inga@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 5))

    @as_users("anton", "garcia")
    def test_subscribers_three(self, user):
        expectation = {7: 'garcia@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 8))
        expectation = {1: 'anton@example.cde',
                       5: 'emilia@example.cde',
                       7: 'garcia@example.cde',
                       9: 'inga@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 9))
        expectation = {5: 'emilia@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 10))

    @as_users("anton")
    def test_change_state(self, user):
        expectation = {1: None, 2: None, 3: None, 4: None, 5: None, 9: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 1))
        self.ml.change_subscription_state(self.key, 1, 1, False, None)
        self.ml.change_subscription_state(self.key, 3, 1, False, None)
        self.ml.change_subscription_state(self.key, 4, 1, True, 'devnull@example.cde')
        self.ml.change_subscription_state(self.key, 7, 1, True, 'devnull@example.cde')
        expectation = {2: None,
                       4: 'devnull@example.cde',
                       5: None,
                       7: 'devnull@example.cde',
                       9: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 1))

    def test_moderation(self):
        self.login(USER_DICT['inga'])
        expectation = {1: None, 2: None, 5: None, 9: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))
        self.ml.change_subscription_state(self.key, 2, 9, False)
        self.ml.change_subscription_state(
            self.key, 3, 9, True, 'devnull@example.cde')
        self.ml.change_subscription_state(self.key, 9, 9, False)
        expectation = {1: None, 3: 'devnull@example.cde', 5: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))
        self.assertEqual(-1, self.ml.change_subscription_state(
            self.key, 4, 9, True, None))
        self.login(USER_DICT['berta'])
        self.assertEqual(1, self.ml.decide_request(
            self.key, 4, 9, True))
        self.login(USER_DICT['inga'])
        self.assertEqual(1, self.ml.change_subscription_state(
            self.key, 4, 9, True, 'devnull@example.cde'))
        expectation = {1: None,
                       3: 'devnull@example.cde',
                       4: 'devnull@example.cde',
                       5: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))

        self.assertEqual(1, self.ml.change_subscription_state(
            self.key, 4, 9, False))
        expectation = {1: None, 3: 'devnull@example.cde', 5: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))
        self.assertEqual(-1, self.ml.change_subscription_state(
            self.key, 4, 9, True))
        self.login(USER_DICT['berta'])
        self.assertEqual(1, self.ml.decide_request(
            self.key, 4, 9, False))
        self.login(USER_DICT['inga'])
        expectation = {1: None, 3: 'devnull@example.cde', 5: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))

    @as_users("anton")
    def test_log(self, user):
        ## first generate some data
        self.ml.change_subscription_state(self.key, 1, 1, False, None)
        self.ml.change_subscription_state(self.key, 3, 1, False, None)
        self.ml.change_subscription_state(self.key, 4, 1, True, 'devnull@example.cde')
        self.ml.change_subscription_state(self.key, 7, 1, True, 'devnull@example.cde')
        new_data = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachement_policy': 2,
            'audience': [0],
            'event_id': None,
            'gateway': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 0,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 4,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {'che@example.cde',}}
        self.ml.create_mailinglist(self.key, new_data)
        self.ml.delete_mailinglist(self.key, 3, cascade=True)

        ## now check it
        expectation = (
            {'additional_info': 'Witz des Tages (witz@example.cde)',
             'code': 2,
             'ctime': nearly_now(),
             'mailinglist_id': None,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 0,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'che@example.cde',
             'code': 12,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 21,
             'ctime': nearly_now(),
             'mailinglist_id': 7,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': 'devnull@example.cde',
             'code': 22,
             'ctime': nearly_now(),
             'mailinglist_id': 4,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 23,
             'ctime': nearly_now(),
             'mailinglist_id': 1,
             'persona_id': 1,
             'submitted_by': 1})
        self.assertEqual(expectation, self.ml.retrieve_log(self.key))
        self.assertEqual(
            expectation[2:5],
            self.ml.retrieve_log(self.key, start=2, stop=5))
        self.assertEqual(
            expectation[2:6],
            self.ml.retrieve_log(self.key, mailinglist_id=11, start=1, stop=5))
        self.assertEqual(expectation[4:6],
                         self.ml.retrieve_log(self.key, codes=(10,)))

    @as_users("anton")
    def test_check_states(self, user):
        self.ml.change_subscription_state(self.key, 1, 5, True)
        self.ml.change_subscription_state(self.key, 7, 8, True)
        self.ml.change_subscription_state(self.key, 8, 10, True)
        lists = self.ml.list_mailinglists(self.key)
        expectation = {1: (5,),
                       2: (),
                       3: (),
                       4: (),
                       5: (),
                       7: (8,),
                       8: (10,),
                       9: (),
                       10: ()}
        self.assertEqual(expectation,
                         self.ml.check_states(self.key, lists.keys()))

    def test_gateway(self):
        self.login(USER_DICT['inga'])
        with self.assertRaises(PrivilegeError):
            self.ml.change_subscription_state(self.key, 7, 9, True)
        self.login(USER_DICT['anton'])
        self.assertEqual(
            1, self.ml.change_subscription_state(self.key, 6, 9, True))
        self.login(USER_DICT['inga'])
        self.assertEqual(
            1, self.ml.change_subscription_state(self.key, 7, 9, True))

    def test_export(self):
        with self.assertRaises(NotImplementedError):
            self.ml.export("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3", 1)
