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

    @as_users("anton")
    def test_entity_mailinglist(self, user):
        expectation = {1: 'Verkündungen',
                       2: 'Werbung',
                       3: 'Witz des Tages',
                       4: 'Klatsch und Tratsch',
                       5: 'Sozialistischer Kampfbrief',
                       7: 'Aktivenforum 2001',
                       8: 'Orga-Liste',
                       9: 'Teilnehmer-Liste',
                       10: 'Warte-Liste',
                       11: 'Kampfbrief-Kommentare'}
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
            self.key, new_id, cascade=("subscriptions", "addresses",
                                       "whitelist", "moderators", "log")))
        self.assertNotIn(new_id, self.ml.list_mailinglists(self.key))

    @as_users("anton")
    def test_sample_data(self, user):
        ml_ids = self.ml.list_mailinglists(self.key, active_only=False)

        for ml_id in ml_ids:
            expectation = self.ml.get_subscription_states(self.key, ml_id)
            self.ml.write_subscription_states(self.key, ml_id)
            result = self.ml.get_subscription_states(self.key, ml_id)

            self.assertEqual(expectation, result)

    @as_users("norbert")
    def test_overrides(self, user):
        overrides = self.ml.list_overrides(self.key)
        self.assertEqual(overrides, {5: 'Sozialistischer Kampfbrief'})

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
            11: const.SubscriptionStates.implicit
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

    # These are some helpers to make the following tests less ugly
    def _check_state(self, user, mailinglist_id, expected_state):
        """This asserts that user has expected_state on given mailinglist."""
        state = self.ml.get_subscription(self.key, user['id'],
                                         mailinglist_id=mailinglist_id)
        if state is not None:
            self.assertEqual(state, expected_state)
        else:
            self.assertIsNone(state)

    def _change_own_sub(self, user, mailinglist_id, function, code=None,
                        state=None):
        """This calls functions to modify the own subscription state on a given
        mailinglist to state and asserts they return code and have the correct
        state after the operation. code=None asserts that a RuntimeError is
        raised."""
        if code is not None:
            result = function(self.key, mailinglist_id)
            self.assertEqual(result, code)
        else:
            with self.assertRaises(RuntimeError):
                function(self.key, mailinglist_id)
        self._check_state(user, mailinglist_id, state)

    def _change_sub(self, user, mailinglist_id, function, code=None,
                    state=None):
        """This calls functions to administratively modify the own subscription
        state on a given mailinglist to state and asserts they return code and
        have the correct state after the operation. code=None asserts that a
        RuntimeError is raised."""
        if code is not None:
            result = function(self.key, mailinglist_id, user['id'])
            self.assertEqual(result[0], code)
        else:
            with self.assertRaises(RuntimeError):
                function(self.key, mailinglist_id, user['id'])
        self._check_state(user, mailinglist_id, state)


    @as_users("anton", "berta", "ferdinand")
    def test_opt_in(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 7

        # Be aware that Ferdinands subscription is pending even though
        # this list is opt in. He should just be able to subscribe now.
        # This plays around with subscribing and unsubscribing.
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=1, state=const.SubscriptionStates.subscribed)
        self._change_own_sub(user,  mailinglist_id, self.ml.subscribe,
            code=None, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=-1, state=const.SubscriptionStates.subscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=1, state=const.SubscriptionStates.unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=None, state=const.SubscriptionStates.unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=-1, state=const.SubscriptionStates.unsubscribed)

        # This does some basic override testing.
        self._change_sub(user, mailinglist_id, self.ml.add_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=None, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=0, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=None, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=-1, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=1, state=const.SubscriptionStates.mod_subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=0, state=const.SubscriptionStates.mod_subscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=None, state=const.SubscriptionStates.mod_subscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=-1, state=const.SubscriptionStates.mod_subscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=1, state=const.SubscriptionStates.unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=None, state=const.SubscriptionStates.unsubscribed)

        # You cannot request subscriptions to such lists
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=None, state=const.SubscriptionStates.unsubscribed)

        # This adds and removes some subscriptions
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=1, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=-1, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=1, state=const.SubscriptionStates.unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=-1, state=const.SubscriptionStates.unsubscribed)

        # This does more override management testing
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_unsubscriber,
            code=None, state=const.SubscriptionStates.unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=None, state=const.SubscriptionStates.unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=1, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=1, state=const.SubscriptionStates.mod_subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=1, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=None, state=const.SubscriptionStates.subscribed)

    @as_users("anton", "berta", "ferdinand")
    def test_moderated_opt_in(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 4

        # Anton and Berta are already subscribed, unsubscribe them first
        if user['id'] in {1, 2}:
            self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
                code=1, state=const.SubscriptionStates.unsubscribed)
        else:
            self._check_state(user, mailinglist_id, None)

        # Try to subscribe
        with self.assertRaises(RuntimeError):
            self.ml.subscribe(self.key, mailinglist_id)
        state = self.ml.get_subscription(self.key, user['id'],
                                         mailinglist_id=mailinglist_id)
        if user['id'] in {1, 2}:
            self.assertEqual(state, const.SubscriptionStates.unsubscribed)
        else:
            self.assertIsNone(state)

        # Test cancelling a subscription request
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=1, state=const.SubscriptionStates.pending)
        self._change_own_sub(user, mailinglist_id, self.ml.cancel_subscription,
            code=1, state=None)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'resolution': const.SubscriptionRequestResolutions.denied,
        }
        with self.assertRaises(RuntimeError):
            self.ml.decide_subscription_request(self.key, datum)
        self._check_state(user, mailinglist_id, None)

        # Test different resolutions
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=1, state=const.SubscriptionStates.pending)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'resolution': const.SubscriptionRequestResolutions.denied,
        }
        code = self.ml.decide_subscription_request(self.key, datum)
        self.assertEqual(code, 1)
        self._check_state(user, mailinglist_id, None)
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=1, state=const.SubscriptionStates.pending)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'resolution': const.SubscriptionRequestResolutions.approved,
        }
        code = self.ml.decide_subscription_request(self.key, datum)
        self.assertEqual(code, 1)
        self._check_state(user, mailinglist_id,
                          const.SubscriptionStates.subscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=1, state=const.SubscriptionStates.unsubscribed)

        # Make sure it is impossible to subscribe if blocked
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=1, state=const.SubscriptionStates.pending)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'resolution': const.SubscriptionRequestResolutions.blocked,
        }
        code = self.ml.decide_subscription_request(self.key, datum)
        self.assertEqual(code, 1)
        self._check_state(user, mailinglist_id,
                          const.SubscriptionStates.mod_unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=None, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.unsubscribed)

        # Make sure it is impossible to remove a subscription request without
        # actually deciding it
        self._change_own_sub(user, mailinglist_id, self.ml.request_subscription,
            code=1, state=const.SubscriptionStates.pending)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=0, state=const.SubscriptionStates.pending)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=0, state=const.SubscriptionStates.pending)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_unsubscriber,
            code=0, state=const.SubscriptionStates.pending)
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'resolution': const.SubscriptionRequestResolutions.denied,
        }
        code = self.ml.decide_subscription_request(self.key, datum)
        self.assertEqual(code, 1)
        self._check_state(user, mailinglist_id, None)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
                        code=1, state=const.SubscriptionStates.subscribed)

    @as_users("anton", "ferdinand", "janis", "norbert")
    def test_opt_out(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 2
        # Ferdinand is unsubscribed already, resubscribe
        if user['id'] == 6:
            self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
                code=1, state=const.SubscriptionStates.subscribed)
        # Now we have a mix of explicit and implicit subscriptions, try to
        # subscribe again
        with self.assertRaises(RuntimeError):
            self.ml.subscribe(self.key, mailinglist_id)
        if user['id'] in {6, 14}:
            self._check_state(user, mailinglist_id,
                              const.SubscriptionStates.subscribed)
        else:
            self._check_state(user, mailinglist_id,
                              const.SubscriptionStates.implicit)
        # Now everyone unsubscribes (twice)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=1, state=const.SubscriptionStates.unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=None, state=const.SubscriptionStates.unsubscribed)

        # Test blocks
        self._change_sub(user, mailinglist_id, self.ml.add_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=None, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=0, state=const.SubscriptionStates.mod_unsubscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_unsubscriber,
            code=1, state=const.SubscriptionStates.unsubscribed)

        # Test forced subscriptions
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=1, state=const.SubscriptionStates.subscribed)
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=1, state=const.SubscriptionStates.mod_subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=0, state=const.SubscriptionStates.mod_subscribed)
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=1, state=const.SubscriptionStates.unsubscribed)

    @as_users("anton", "berta", "ferdinand")
    def test_mandatory(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1

        def _try_unsubscribe(expected_state):
            # Try to unsubscribe
            self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
                code=None, state=expected_state)
            # Try to remove subscription
            self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
                code=0, state=expected_state)
            # Try to block user
            self._change_sub(user, mailinglist_id, self.ml.add_mod_unsubscriber,
                code=0, state=expected_state)

        _try_unsubscribe(const.SubscriptionStates.implicit)
        # Force subscription
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=1, state=const.SubscriptionStates.mod_subscribed)
        _try_unsubscribe(const.SubscriptionStates.mod_subscribed)
        # Remove forced subscription
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=1, state=const.SubscriptionStates.subscribed)
        _try_unsubscribe(const.SubscriptionStates.subscribed)
        # For admins, some shallow cron testing
        if user['id'] != 2:
            self.ml.write_subscription_states(self.key, mailinglist_id)
            self._check_state(user, mailinglist_id,
                              const.SubscriptionStates.subscribed)

    @as_users('norbert')
    def test_mandatory_two(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1
        # Try to subscribe somehow
        self._change_own_sub(user, mailinglist_id, self.ml.subscribe,
            code=None, state=None)
        self._change_sub(user, mailinglist_id, self.ml.add_subscriber,
            code=0, state=None)
        # Force subscription
        self._change_sub(user, mailinglist_id, self.ml.add_mod_subscriber,
            code=1, state=const.SubscriptionStates.mod_subscribed)
        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(user, mailinglist_id,
                          const.SubscriptionStates.mod_subscribed)
        # It is impossible to unsubscribe normally
        self._change_own_sub(user, mailinglist_id, self.ml.unsubscribe,
            code=None, state=const.SubscriptionStates.mod_subscribed)
        self._change_sub(user, mailinglist_id, self.ml.remove_subscriber,
            code=0, state=const.SubscriptionStates.mod_subscribed)
        # Remove subscription
        self._change_sub(user, mailinglist_id, self.ml.remove_mod_subscriber,
            code=1, state=const.SubscriptionStates.subscribed)
        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(user, mailinglist_id, None)

    @as_users("anton")
    def test_ml_event(self, user):
        ml_id = 9
        SS = const.SubscriptionStates

        expectation = {
            1: SS.implicit,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=SS.implicit)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=1, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None,
            state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=1, state=SS.subscribed)
        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=SS.subscribed)

        self.ml.write_subscription_states(self.key, ml_id)

        expectation = {
            1: SS.subscribed,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        mdata = {
            'id': ml_id,
            'event_id': 2,
            'audience_policy': const.AudiencePolicy.require_event,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            5: SS.unsubscribed,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=None)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=None)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None, state=None)

    @as_users("anton")
    def test_ml_assembly(self, user):
        ml_id = 5
        SS = const.SubscriptionStates

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.mod_subscribed,
            9: SS.mod_unsubscribed,
            11: SS.implicit,
            14: SS.mod_subscribed,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=SS.implicit)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=1, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None,
            state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=1, state=SS.subscribed)

        mdata = {
            'id': ml_id,
            'assembly_id': None,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            3: SS.mod_subscribed,
            9: SS.mod_unsubscribed,
            14: SS.mod_subscribed,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=None)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=None)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None, state=None)

    @as_users("anton")
    def test_opt_in_opt_out(self, user):
        ml_id = 11
        SS = const.SubscriptionStates

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.subscribed,
            4: SS.unsubscribed,
            9: SS.mod_unsubscribed,
            11: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=SS.implicit)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=1, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None,
            state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=1, state=SS.subscribed)

        mdata = {
            'id': ml_id,
            'assembly_id': None,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: SS.subscribed,
            3: SS.subscribed,
            4: SS.unsubscribed,
            9: SS.mod_unsubscribed,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=None, state=SS.subscribed)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=1, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.unsubscribe, code=None, state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.request_subscription, code=None,
            state=SS.unsubscribed)
        self._change_own_sub(
            user, ml_id, self.ml.subscribe, code=1, state=SS.subscribed)

    @as_users("anton", "norbert")
    def test_bullshit_requests(self, user):
        # Can I remove people from lists the have not subscribed to?
        result = self.ml.remove_subscriber(self.key, 2, 6)
        self.assertEqual(result[0], -1)
        state = self.ml.get_subscription(self.key, 6, mailinglist_id=2)
        self.assertEqual(state, const.SubscriptionStates.unsubscribed)

        result = self.ml.remove_subscriber(self.key, 3, 2)
        self.assertEqual(result[0], -1)
        state = self.ml.get_subscription(self.key, 2, mailinglist_id=3)
        self.assertEqual(state, const.SubscriptionStates.unsubscribed)

        result = self.ml.remove_subscriber(self.key, 3, 3)
        self.assertEqual(result[0], -1)
        state = self.ml.get_subscription(self.key, 3, mailinglist_id=3)
        self.assertIsNone(state)

    @as_users("charly", "emilia", "janis")
    def test_no_privileges(self, user):
        # TODO Write less thorough tests testing non-moderators work as well,
        # especially for cases where policies differ for non cde users

        def _try_everything(ml_id, user_id):
            with self.assertRaises(PrivilegeError):
                self.ml.add_subscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.remove_subscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.remove_mod_subscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.add_mod_subscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.remove_mod_unsubscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.add_mod_unsubscriber(self.key, ml_id, user_id)
            with self.assertRaises(PrivilegeError):
                datum = {
                    'mailinglist_id': ml_id,
                    'persona_id': user_id,
                    'resolution': const.SubscriptionRequestResolutions.approved,
                }
                self.ml.decide_subscription_request(self.key, datum)
            # You had never the chance to actually change something anyway.
            with self.assertRaises(PrivilegeError):
                datum = {
                    'mailinglist_id': ml_id,
                    'persona_id': user_id,
                    'subscription_state': const.SubscriptionStates.unsubscribed,
                }
                self.ml._set_subscription(datum)

        # Make sure moderator functions do not tell you anything.
        # Garcia (7) is listed implicitly, explicitly or not at all on these
        for ml_id in {1, 4, 5, 6, 8, 9}:
            _try_everything(ml_id, 7)

        # Users have very diverse states on list 5.
        for user_id in range(1, 15):
            _try_everything(5, user_id)

    @as_users("janis", "kalif")
    def test_audience(self, user):
        # List 4 is moderated opt-in
        if user['id'] == 10:
            self._change_own_sub(user, 4, self.ml.unsubscribe, code=1,
                                 state=const.SubscriptionStates.unsubscribed)
        self._change_own_sub(user, 4, self.ml.subscribe, code=None,
                             state=const.SubscriptionStates.unsubscribed)
        self._change_own_sub(user, 4, self.ml.request_subscription, code=1,
                             state=const.SubscriptionStates.pending)
        self._change_own_sub(user, 4, self.ml.cancel_subscription, code=1,
                             state=None)
        # List 7 is not joinable my non-members
        self._change_own_sub(user, 7, self.ml.subscribe, code=None,
                             state=None)
        # List 9 is only allowed for event users, and not joinable anyway
        self._change_own_sub(user, 9, self.ml.subscribe, code=None,
                             state=None)
        # List 11 is only joinable by assembly users
        if user['id'] == 11:
            self._change_own_sub(user, 11, self.ml.unsubscribe, code=1,
                                 state=const.SubscriptionStates.unsubscribed)
            self._change_own_sub(user, 11, self.ml.subscribe, code=1,
                                 state=const.SubscriptionStates.subscribed)
        else:
            self._change_own_sub(user, 11, self.ml.subscribe, code=None,
                                 state=None)

    @as_users("anton")
    def test_write_subscription_states(self, user):
        # CdE-Member list.
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
        self.ml._set_subscriptions(self.key, data)
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': const.SubscriptionStates.mod_subscribed,
            }
            for persona_id in [4]
        ]
        self.ml._set_subscriptions(self.key, data)

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

        # Now test lists with implicit subscribers.
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
            9: const.SubscriptionStates.mod_unsubscribed,
            11: const.SubscriptionStates.implicit,
            14: const.SubscriptionStates.mod_subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.mod_subscribed,
            9: const.SubscriptionStates.mod_unsubscribed,
            11: const.SubscriptionStates.implicit,
            14: const.SubscriptionStates.mod_subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("anton")
    def test_change_sub_policy(self, user):
        mdata = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'audience_policy': const.AudiencePolicy.require_member,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': set(),
            'registration_stati': [],
            'sub_policy': const.SubscriptionPolicy.invitation_only,
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'fidel@example.cde',
                'che@example.cde',
            },
        }
        new_id = self.ml.create_mailinglist(self.key, mdata)

        # List should have no subscribers.
        self.assertEqual({}, self.ml.get_subscription_states(self.key, new_id))

        # Making the list Opt-Out should yield implicits subscribers.
        mdata = {
            'id': new_id,
            'sub_policy': const.SubscriptionPolicy.opt_out,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.implicit,
            6: const.SubscriptionStates.implicit,
            7: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.implicit,
            12: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        # Opt-Out allows unsubscribing.
        sub_data = [
            {
                'mailinglist_id': new_id,
                'persona_id': 2,
                'subscription_state': const.SubscriptionStates.unsubscribed,
            },
            # Not in the audience, should get removed in the next step.
            {
                'mailinglist_id': new_id,
                'persona_id': 4,
                'subscription_state': const.SubscriptionStates.mod_unsubscribed,
            },
            {
                'mailinglist_id': new_id,
                'persona_id': 7,
                'subscription_state': const.SubscriptionStates.mod_unsubscribed,
            },
            {
                'mailinglist_id': new_id,
                'persona_id': 12,
                'subscription_state': const.SubscriptionStates.pending,
            },
        ]
        self.ml._set_subscriptions(self.key, sub_data)

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            3: const.SubscriptionStates.implicit,
            4: const.SubscriptionStates.mod_unsubscribed,
            6: const.SubscriptionStates.implicit,
            7: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.implicit,
            12: const.SubscriptionStates.pending,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        # Making the list mandatory should get rid of all unsubscriptions, even
        # outside of the audience.
        mdata = {
            'id': new_id,
            'sub_policy': const.SubscriptionPolicy.mandatory,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            3: const.SubscriptionStates.implicit,
            6: const.SubscriptionStates.implicit,
            7: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.implicit,
            12: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

    @as_users("anton")
    def test_change_mailinglist_association(self, user):
        mdata = {
            'address': 'orga@example.cde',
            'description': None,
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'audience_policy': const.AudiencePolicy.require_event,
            'event_id': 2,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': set(),
            'registration_stati': [],
            'sub_policy': const.SubscriptionPolicy.invitation_only,
            'subject_prefix': 'orga',
            'title': 'Orgateam',
            'notes': None,
        }
        new_id = self.ml.create_mailinglist(self.key, mdata)

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'event_id': 1,
            'audience_policy': const.AudiencePolicy.require_event,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            7: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'registration_stati': [const.RegistrationPartStati.guest,
                                   const.RegistrationPartStati.cancelled],
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            5: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'audience_policy': const.AudiencePolicy.require_assembly,
            'event_id': None,
            'assembly_id': 1,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            9: const.SubscriptionStates.implicit,
            11: const.SubscriptionStates.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

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
            13: 'martin@example.cde',
            14: 'norbert@example.cde',
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
                       11: 'kalif@example.cde',
                       14: 'norbert@example.cde'}
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
            'persona_id': user['id'],
            'address': "anton-cde@example.cde",
        }
        expectation.update({datum['persona_id']: datum['address']})
        self.ml.set_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Remove an address.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
        }
        expectation.update({user['id']: user['username']})
        self.ml.remove_subscription_address(self.key, datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("janis")
    def test_remove_subscription_address(self, user):
        mailinglist_id = 3

        # Check sample data.
        expectation = {
            1: USER_DICT["anton"]["username"],
            10: 'janis-spam@example.cde',
        }
        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        expectation = {
            1: const.SubscriptionStates.subscribed,
            2: const.SubscriptionStates.unsubscribed,
            10: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now let janis delete his changed address

        expectation = {
            1: USER_DICT["anton"]["username"],
            10: USER_DICT["janis"]["username"],
        }
        datum = {'persona_id': 10, 'mailinglist_id': mailinglist_id}
        self.assertLess(0, self.ml.remove_subscription_address(self.key, datum))

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        expectation = {
            1: const.SubscriptionStates.subscribed,
            2: const.SubscriptionStates.unsubscribed,
            10: const.SubscriptionStates.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("inga")
    def test_moderation(self, user):
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.implicit,
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.implicit,
            11: const.SubscriptionStates.mod_unsubscribed,
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
        self.ml._set_subscriptions(self.key, data)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.pending,
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.unsubscribed,
            11: const.SubscriptionStates.mod_unsubscribed,
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
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.unsubscribed,
            11: const.SubscriptionStates.mod_unsubscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state': const.SubscriptionStates.unsubscribed,
        }
        self.ml._set_subscription(self.key, datum)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.unsubscribed,
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.unsubscribed,
            11: const.SubscriptionStates.mod_unsubscribed
        }
        self.assertEqual(expectation,
                         self.ml.get_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state':
                const.SubscriptionStates.pending,
        }
        self.ml._set_subscription(self.key, datum)
        expectation = {
            1: const.SubscriptionStates.implicit,
            2: const.SubscriptionStates.unsubscribed,
            4: const.SubscriptionStates.pending,
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.unsubscribed,
            11: const.SubscriptionStates.mod_unsubscribed,
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
            5: const.SubscriptionStates.mod_unsubscribed,
            9: const.SubscriptionStates.unsubscribed,
            11: const.SubscriptionStates.mod_unsubscribed,
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
        self.ml._set_subscription(self.key, datum)
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
        self.ml._set_subscription(self.key, datum)
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
        self.ml._set_subscription(self.key, datum)
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
        new_id = self.ml.create_mailinglist(self.key, new_data)
        self.ml.delete_mailinglist(
            self.key, 3, cascade=("subscriptions", "addresses",
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
             'mailinglist_id': new_id,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'che@example.cde',
             'code': const.MlLogCodes.whitelist_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
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
            self.ml.retrieve_log(self.key, mailinglist_id=new_id, start=1, stop=5))
        self.assertEqual(
            expectation[3:5],
            self.ml.retrieve_log(
                self.key, codes=(const.MlLogCodes.moderator_added,)))

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
                        'is_active': True},
                       {'address': 'opt@example.cde',
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
                            'kalif@example.cde',
                            'martin@example.cde',
                            'norbert@example.cde'),
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
                        'mime': False},
                       {'address': 'opt@example.cde',
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
                                       'kalif@example.cde',
                                       'martin@example.cde',
                                       'norbert@example.cde'),
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
