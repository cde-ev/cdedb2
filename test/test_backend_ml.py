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
        data = self.core.get_ml_user(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['family_name'] = "Lord von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'given_names', 'family_name'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_ml_user(self.key, user['id'])
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
            self.key, audience_policies=(1,), active_only=False))
        expectation = {
            3: {'address': 'witz@example.cde',
                'description': "Einer geht noch ...",
                'assembly_id': None,
                'attachment_policy': 2,
                'audience_policy': 1,
                'event_id': None,
                'gateway': None,
                'id': 3,
                'is_active': True,
                'maxsize': 2048,
                'mod_policy': 2,
                'moderators': {2, 3, 10},
                'registration_stati': [],
                'sub_policy': 3,
                'subject_prefix': '[witz]',
                'title': 'Witz des Tages',
                'notes': None,
                'whitelist': set()},
            5: {'address': 'kongress@example.cde',
                'description': None,
                'assembly_id': 1,
                'attachment_policy': 2,
                'audience_policy': 2,
                'event_id': None,
                'gateway': None,
                'id': 5,
                'is_active': True,
                'maxsize': 1024,
                'mod_policy': 2,
                'moderators': {2},
                'registration_stati': [],
                'sub_policy': 5,
                'subject_prefix': '[kampf]',
                'title': 'Sozialistischer Kampfbrief',
                'notes': None,
                'whitelist': set()},
            7: {'address': 'aktivenforum@example.cde',
                'description': None,
                'assembly_id': None,
                'attachment_policy': 2,
                'audience_policy': 5,
                'event_id': None,
                'gateway': 6,
                'id': 7,
                'is_active': True,
                'maxsize': 1024,
                'mod_policy': 2,
                'moderators': {2, 10},
                'registration_stati': [],
                'sub_policy': 5,
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
            'sub_policy': 4,
            'is_active': False,
            'address': 'passivenforum@example.cde',
            'notes': "this list is no more",
        }
        expectation = expectation[7]
        expectation.update(setter)
        self.assertLess(0, self.ml.set_mailinglist(self.key, setter))
        self.assertEqual(expectation, self.ml.get_mailinglist(self.key, 7))

    @as_users("janis")
    def test_double_link(self, user):
        setter = {
            'id': 7,
            'event_id': 1,
            'assembly_id': 1
        }
        with self.assertRaises(ValueError):
            self.ml.set_mailinglist(self.key, setter)

    @as_users("anton")
    def test_mailinglist_creation_deletion(self, user):
        oldlists = self.ml.list_mailinglists(self.key)
        new_data = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': 3,
            'audience_policy': 5,
            'event_id': None,
            'gateway': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 5,
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
        self.assertLess(0, self.ml.delete_mailinglist(
            self.key, new_id, cascade=("gateway", "subscriptions", "requests",
                                       "whitelist", "moderators", "log")))
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
                       4: 'daniel@example.cde',
                       5: 'emilia@example.cde',
                       7: 'garcia@example.cde',
                       9: 'inga@example.cde',
                       10: 'janis@example.cde',
                       11: 'kalif@example.cde',
                       12: None,
                       13: 'martin@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 2))
        expectation = {1: 'anton@example.cde', 10: 'janis-spam@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 3))
        expectation = {2: 'berta@example.cde', 3: 'charly@example.cde'}
        self.assertEqual(expectation, self.ml.subscribers(self.key, 7))

    @as_users("anton", "berta")
    def test_subscribers_two(self, user):
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       9: 'inga@example.cde',
                       11: 'kalif@example.cde'}
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
        self.assertGreater(0, self.ml.change_subscription_state(
            self.key, 4, 9, True, None))
        self.login(USER_DICT['berta'])
        self.assertLess(0, self.ml.decide_request(self.key, 4, 9, True))
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
        self.assertGreater(0, self.ml.change_subscription_state(
            self.key, 4, 9, True))
        self.login(USER_DICT['berta'])
        self.assertEqual(1, self.ml.decide_request(
            self.key, 4, 9, False))
        self.login(USER_DICT['inga'])
        expectation = {1: None, 3: 'devnull@example.cde', 5: None}
        self.assertEqual(expectation, self.ml.subscriptions(self.key, 9))

    def test_lookup_subscription_states(self):
        self.login(USER_DICT['inga'])
        self.ml.change_subscription_state(self.key, 4, 9, True)
        self.login(USER_DICT['anton'])
        expectation = {
            (1, 1): 2,
            (1, 4): 2,
            (1, 9): 2,
            (2, 1): 2,
            (2, 4): 2,
            (2, 9): 1,
            (9, 1): 2,
            (9, 4): 10,
            (9, 9): 2,}
        self.assertEqual(expectation,
                         self.ml.lookup_subscription_states(
                             self.key, (1, 2, 9), (1, 4, 9)))

    @as_users("anton")
    def test_subscription_addresses(self, user):
        mailinglist_id = 3

        # Check sample data.
        expectation = {
            1: USER_DICT["anton"]["username"],
            10: 'janis-spam@example.cde',
        }
        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Add and change addresses.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': 1,
            'address': "anton-spam@example.cde",
        }
        expectation.update({datum['persona_id']: datum['address']})
        self.ml.set_subscription_address(self.key, datum)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': 10,
            'address': "janis-cde@example.cde",
        }
        expectation.update({datum['persona_id']: datum['address']})
        self.ml.set_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Remove an address.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': 10,
        }
        del expectation[datum['persona_id']]
        self.ml.remove_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("anton")
    def test_write_subscription_states(self, user):
        mailinglist_id = 7

        expectation = {
            1: const.SubscriptionStates.unsubscribed,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.subscribed,
            6: const.SubscriptionStates.subscription_requested,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Add and change some subscriptions.
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': const.SubscriptionStates.subscribed,
            }
            for persona_id in [1, 4, 5, 9]
        ]
        self.ml.set_subscriptions(self.key, data)
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': const.SubscriptionStates.mod_subscribed,
            }
            for persona_id in [4]
        ]
        self.ml.set_subscriptions(self.key, data)

        expectation = {
            1: const.SubscriptionStates.subscribed,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.subscribed,
            4: const.SubscriptionStates.mod_subscribed,
            5: const.SubscriptionStates.subscribed,
            6: const.SubscriptionStates.subscription_requested,
            9: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: const.SubscriptionStates.subscribed,
            3: const.SubscriptionStates.subscribed,
            4: const.SubscriptionStates.mod_subscribed,
            6: const.SubscriptionStates.subscription_requested,
            9: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now test adding implicit subscribers.
        # First for events.
        mailinglist_id = 9

        # Initially sample-data.
        expectation = {
            1: const.SubscriptionStates.subscription_requested,
            5: const.SubscriptionStates.unsubscribed,
            7: const.SubscriptionStates.subscribed,
            11: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: const.SubscriptionStates.implicit,
            5: const.SubscriptionStates.unsubscribed,
            7: const.SubscriptionStates.subscribed,
            9: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now for assemblies.
        mailinglist_id = 5

        expectation = {
            3: const.SubscriptionStates.mod_subscribed,
            10: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.mod_subscribed,
            9: const.SubscriptionStates.implicit,
            11: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("inga")
    def test_request_cancellation(self, user):
        self.assertEqual({(9, 4): 1},
                         self.ml.lookup_subscription_states(
                             self.key, (9,), (4,)))
        self.ml.change_subscription_state(self.key, 4, 9, True)
        self.assertEqual({(9, 4): 10},
                         self.ml.lookup_subscription_states(
                             self.key, (9,), (4,)))
        self.ml.change_subscription_state(self.key, 4, 9, False)
        self.assertEqual({(9, 4): 1},
                         self.ml.lookup_subscription_states(
                             self.key, (9,), (4,)))

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
            'attachment_policy': 3,
            'audience_policy': 5,
            'event_id': None,
            'gateway': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 5,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {'che@example.cde',}}
        self.ml.create_mailinglist(self.key, new_data)
        self.ml.delete_mailinglist(
            self.key, 3, cascade=("gateway", "subscriptions", "requests",
                                  "whitelist", "moderators", "log"))

        ## now check it
        expectation = (
            {'additional_info': 'Witz des Tages (witz@example.cde)',
             'code': 3,
             'ctime': nearly_now(),
             'mailinglist_id': None,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 1,
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
            expectation[2:5],
            self.ml.retrieve_log(self.key, mailinglist_id=11, start=1, stop=5))
        self.assertEqual(expectation[3:5],
                         self.ml.retrieve_log(self.key, codes=(10,)))

    def test_gateway(self):
        self.login(USER_DICT['inga'])
        with self.assertRaises(PrivilegeError):
            self.ml.change_subscription_state(self.key, 7, 9, True)
        self.login(USER_DICT['anton'])
        self.assertLess(
            0, self.ml.change_subscription_state(self.key, 6, 9, True))
        self.login(USER_DICT['inga'])
        self.assertLess(
            0, self.ml.change_subscription_state(self.key, 7, 9, True))

    def test_export(self):
        expectation =  ({'address': 'announce@example.cde', 'is_active': True},
                        {'address': 'werbung@example.cde', 'is_active': True},
                        {'address': 'witz@example.cde', 'is_active': True},
                        {'address': 'klatsch@example.cde', 'is_active': True},
                        {'address': 'kongress@example.cde', 'is_active': True},
                        {'address': 'aktivenforum2000@example.cde', 'is_active': False},
                        {'address': 'aktivenforum@example.cde', 'is_active': True},
                        {'address': 'aka@example.cde', 'is_active': True},
                        {'address': 'participants@example.cde', 'is_active': True},
                        {'address': 'wait@example.cde', 'is_active': True})
        self.assertEqual(
            expectation,
            self.ml.export_overview("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"))
        expectation = {
            'address': 'werbung@example.cde',
            'admin_address': 'werbung-owner@example.cde',
            'listname': 'Werbung',
            'moderators': ('janis@example.cde',),
            'sender': 'werbung@example.cde',
            'size_max': None,
            'subscribers': ('anton@example.cde',
                            'berta@example.cde',
                            'charly@example.cde',
                            'daniel@example.cde',
                            'emilia@example.cde',
                            'garcia@example.cde',
                            'inga@example.cde',
                            'janis@example.cde',
                            'kalif@example.cde',
                            'martin@example.cde'),
            'whitelist': {'honeypot@example.cde'}}
        self.assertEqual(
            expectation,
            self.ml.export_one("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
                               "werbung@example.cde"))

    def test_oldstyle_scripting(self):
        expectation = ({'address': 'announce@example.cde',
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
                        'mime': False})
        self.assertEqual(
            expectation,
            self.ml.oldstyle_mailinglist_config_export("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"))
        expectation = {'address': 'werbung@example.cde',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': '[werbung]',
                       'moderators': ('janis@example.cde',),
                       'sender': 'werbung-bounces@example.cde',
                       'subscribers': ('anton@example.cde',
                                       'berta@example.cde',
                                       'charly@example.cde',
                                       'daniel@example.cde',
                                       'emilia@example.cde',
                                       'garcia@example.cde',
                                       'inga@example.cde',
                                       'janis@example.cde',
                                       'kalif@example.cde',
                                       'martin@example.cde'),
                       'whitelist': ['honeypot@example.cde']}
        self.assertEqual(
            expectation,
            self.ml.oldstyle_mailinglist_export("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
                                                "werbung@example.cde"))
        expectation = {'address': 'werbung@example.cde',
                       'list-owner': 'https://db.cde-ev.de/',
                       'list-subscribe': 'https://db.cde-ev.de/',
                       'list-unsubscribe': 'https://db.cde-ev.de/',
                       'listname': '[werbung]',
                       'moderators': ('janis@example.cde',),
                       'sender': 'cdedb-doublebounces@cde-ev.de',
                       'subscribers': ('janis@example.cde',),
                       'whitelist': ['*']}
        self.assertEqual(
            expectation,
            self.ml.oldstyle_modlist_export("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
                                            "werbung@example.cde"))
        self.assertEqual(
            True,
            self.ml.oldstyle_bounce("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
                                    "anton@example.cde", 1))
