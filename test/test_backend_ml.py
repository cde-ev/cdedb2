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
                'id': 7,
                'is_active': True,
                'maxsize': 1024,
                'mod_policy': 2,
                'moderators': {2, 10},
                'registration_stati': [],
                'sub_policy': 3,
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
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 5,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'fidel@example.cde',
                'che@example.cde',
            },
        }
        new_id = self.ml.create_mailinglist(self.key, new_data)
        self.assertLess(0, new_id)
        self.assertNotIn(new_id, oldlists)
        self.assertIn(new_id, self.ml.list_mailinglists(self.key))
        new_data['id'] = new_id
        self.assertEqual(new_data, self.ml.get_mailinglist(self.key, new_id))
        self.assertLess(0, self.ml.delete_mailinglist(
            self.key, new_id, cascade=("gateway", "subscriptions", "addresses",
                                       "whitelist", "moderators", "log")))
        self.assertNotIn(new_id, self.ml.list_mailinglists(self.key))

    @as_users("anton")
    def test_sample_data(self, user):
        ml_ids = self.ml.list_mailinglists(self.key)

        from pprint import pprint
        for ml_id in ml_ids:
            expectation = self.ml.get_subscription_states(self.key, ml_id)
            self.ml.write_subscription_states(self.key, ml_id)
            result = self.ml.get_subscription_states(self.key, ml_id)

            self.assertEqual(expectation, result)

    @as_users("anton", "berta")
    def test_subscriptions(self, user):
        # Which lists is Berta subscribed to.
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.subscribed,
            5: const.SubscriptionStates.implicit,
            6: const.SubscriptionStates.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=2))

    @as_users("anton", "janis")
    def test_subscriptions_two(self, user):
        # Which lists is Janis subscribed to.
        expectation = {
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.subscribed,
            4: const.SubscriptionStates.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=10))

    @as_users("anton", "emilia")
    def test_subscriptions_three(self, user):
        # Which lists is Emila subscribed to.
        expectation = {
            2: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
            10: const.SubscriptionStates.implicit,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=5))

    @as_users("anton", "garcia")
    def test_subscriptions_four(self, user):
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            8: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=7))

    @as_users("anton")
    def test_write_subscription_states(self, user):
        # TODO change implicit subscribers within this test somehow.
        mailinglist_id = 7

        expectation = {
            1: const.SubscriptionStates.unsubscribed,
            3: const.SubscriptionStates.subscribed,
            6: const.SubscriptionStates.pending,
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
            3: const.SubscriptionStates.subscribed,
            4: const.SubscriptionStates.mod_subscribed,
            5: const.SubscriptionStates.subscribed,
            6: const.SubscriptionStates.pending,
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
            6: const.SubscriptionStates.pending,
            9: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now test adding implicit subscribers.
        # First for events.
        mailinglist_id = 9

        # Initially sample-data.
        expectation = {
            1: const.SubscriptionStates.implicit,
            5: const.SubscriptionStates.unsubscribed,
            7: const.SubscriptionStates.subscribed,
            9: const.SubscriptionStates.implicit,
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
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.mod_subscribed,
            9: const.SubscriptionStates.implicit,
            11: const.SubscriptionStates.implicit,
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

    @as_users("anton", "janis")
    def test_subscription_addresses(self, user):
        expectation = {
            1: 'anton@example.cde',
            2: 'berta@example.cde',
            3: 'charly@example.cde',
            4: 'daniel@example.cde',
            5: 'emilia@example.cde',
            7: 'garcia@example.cde',
            9: 'inga@example.cde',
            10: 'janis@example.cde',
            11: 'kalif@example.cde',
            12: None,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 2))
        expectation = {
            1: 'anton@example.cde',
            10: 'janis-spam@example.cde',
        }
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 3))
        expectation = {
            3: 'charly@example.cde',
        }
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 7))

    @as_users("anton", "berta")
    def test_subscription_addresses_two(self, user):
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       3: 'charly@example.cde',
                       9: 'inga@example.cde',
                       11: 'kalif@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 5))

    @as_users("anton", "garcia")
    def test_subscription_addresses_three(self, user):
            expectation = {7: 'garcia@example.cde'}
            self.assertEqual(expectation,
                             self.ml.get_subscription_addresses(self.key, 8))
            expectation = {1: 'anton@example.cde',
                           7: 'garcia@example.cde',
                           9: 'inga@example.cde'}
            self.assertEqual(expectation,
                             self.ml.get_subscription_addresses(self.key, 9))
            expectation = {5: 'emilia@example.cde'}
            self.assertEqual(expectation,
                             self.ml.get_subscription_addresses(self.key, 10))

    @as_users("anton")
    def test_set_subscription_address(self, user):
        # This is a bit tricky, since users may only change their own
        # subscrption address.
        mailinglist_id = 3

        # Check sample data.
        expectation = {
            1: USER_DICT["anton"]["username"],
            10: 'janis-spam@example.cde',
        }
        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Add an addresses.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'address': "anton-spam@example.cde",
        }
        expectation.update({datum['persona_id']: datum['address']})
        self.ml.set_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': 1,
            'address': "anton-cde@example.cde",
        }
        expectation.update({datum['persona_id']: datum['address']})
        self.ml.set_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Remove an address.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': 1,
        }
        del expectation[datum['persona_id']]
        self.ml.remove_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("inga")
    def test_moderation(self, user):
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.implicit,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))
        data = [
            {
                'mailinglist_id': 2,
                'persona_id': 9,
                'subscription_state': const.SubscriptionStates.unsubscribed,
            },
            {
                'mailinglist_id': 9,
                'persona_id': 9,
                'subscription_state': const.SubscriptionStates.unsubscribed,
            },
            {
                'mailinglist_id': 4,
                'persona_id': 9,
                'subscription_state':
                    const.SubscriptionStates.pending,
            },
        ]
        self.ml.set_subscriptions(self.key, data)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.pending,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        self.login(USER_DICT['berta'])
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'resolution': const.SubscriptionRequestResolutions.approved,
        }
        self.assertLess(0,
                        self.ml.decide_subscription_request(
                            self.key, datum))

        self.login(USER_DICT['inga'])
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.subscribed,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state': const.SubscriptionStates.unsubscribed,
        }
        self.ml.set_subscription(self.key, datum)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.unsubscribed,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state':
                const.SubscriptionStates.pending,
        }
        self.ml.set_subscription(self.key, datum)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.pending,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        self.login(USER_DICT['berta'])
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'resolution': const.SubscriptionRequestResolutions.denied,
        }
        self.assertLess(0,
                        self.ml.decide_subscription_request(
                            self.key, datum))

        self.login(USER_DICT['inga'])
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

    @as_users("inga")
    def test_request_cancellation(self, user):
        expectation = None
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state':
                const.SubscriptionStates.pending,
        }
        self.ml.set_subscription(self.key, datum)
        expectation = const.SubscriptionStates.pending
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'resolution': const.SubscriptionRequestResolutions.cancelled,
        }
        self.ml.decide_subscription_request(self.key, datum)
        expectation = None
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))

    @as_users("anton")
    def test_log(self, user):
        # first generate some data
        datum = {
            'mailinglist_id': 1,
            'persona_id': 1,
            'subscription_state': const.SubscriptionStates.unsubscribed,
        }
        self.ml.set_subscription(self.key, datum)
        datum = {
            'mailinglist_id': 4,
            'persona_id': 1,
            'address': 'devnull@example.cde',
        }
        self.ml.set_subscription_address(self.key, datum)
        datum = {
            'mailinglist_id': 7,
            'persona_id': 1,
            'subscription_state': const.SubscriptionStates.subscribed,
        }
        self.ml.set_subscription(self.key, datum)
        new_data = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': 3,
            'audience_policy': 5,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'sub_policy': 5,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'che@example.cde',
            }
        }
        self.ml.create_mailinglist(self.key, new_data)
        self.ml.delete_mailinglist(
            self.key, 3, cascade=("gateway", "subscriptions", "addresses",
                                  "whitelist", "moderators", "log"))

        # now check it
        expectation = (
            {'additional_info': 'Witz des Tages (witz@example.cde)',
             'code': const.MlLogCodes.list_deleted,
             'ctime': nearly_now(),
             'mailinglist_id': None,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.list_created,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'che@example.cde',
             'code': const.MlLogCodes.whitelist_added,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': 11,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.subscribed,
             'ctime': nearly_now(),
             'mailinglist_id': 7,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': 'devnull@example.cde',
             'code': const.MlLogCodes.subscription_changed,
             'ctime': nearly_now(),
             'mailinglist_id': 4,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.unsubscribed,
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

    @as_users("anton")
    def test_export(self, user):
        expectation = ({'address': 'announce@example.cde',
                        'is_active': True},
                       {'address': 'werbung@example.cde',
                        'is_active': True},
                       {'address': 'witz@example.cde',
                        'is_active': True},
                       {'address': 'klatsch@example.cde',
                        'is_active': True},
                       {'address': 'kongress@example.cde',
                        'is_active': True},
                       {'address': 'aktivenforum2000@example.cde',
                        'is_active': False},
                       {'address': 'aktivenforum@example.cde',
                        'is_active': True},
                       {'address': 'aka@example.cde',
                        'is_active': True},
                       {'address': 'participants@example.cde',
                        'is_active': True},
                       {'address': 'wait@example.cde',
                        'is_active': True})
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
                            'kalif@example.cde'),
            'whitelist': {'honeypot@example.cde'}}
        self.assertEqual(
            expectation,
            self.ml.export_one("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
                               "werbung@example.cde"))

    @as_users("anton")
    def test_oldstyle_scripting(self, user):
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
            self.ml.oldstyle_mailinglist_config_export(
                "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3"))
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
                                       'kalif@example.cde'),
                       'whitelist': ['honeypot@example.cde']}
        self.assertEqual(
            expectation,
            self.ml.oldstyle_mailinglist_export(
                "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
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
