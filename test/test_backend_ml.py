#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.query import QUERY_SPECS, QueryOperators
from cdedb.common import (
    PrivilegeError, SubscriptionError, SubscriptionActions as SA)
from cdedb.database.constants import (SubscriptionStates as SS,)
import cdedb.database.constants as const
import datetime
import decimal
import copy
import cdedb.validation as validate


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

    @as_users("anton", "nina")
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
        expectation = {
            3: {'address': 'witz@example.cde',
                'description': "Einer geht noch ...",
                'assembly_id': None,
                'attachment_policy': 2,
                'event_id': None,
                'id': 3,
                'is_active': True,
                'maxsize': 2048,
                'ml_type': 40,
                'mod_policy': 2,
                'moderators': {2, 3, 10},
                'registration_stati': [],
                'subject_prefix': '[witz]',
                'title': 'Witz des Tages',
                'notes': None,
                'whitelist': set()},
            5: {'address': 'kongress@example.cde',
                'description': None,
                'assembly_id': 1,
                'attachment_policy': 2,
                'event_id': None,
                'id': 5,
                'is_active': True,
                'maxsize': 1024,
                'ml_type': 30,
                'mod_policy': 2,
                'moderators': {2, 7},
                'registration_stati': [],
                'subject_prefix': '[kampf]',
                'title': 'Sozialistischer Kampfbrief',
                'notes': None,
                'whitelist': set()},
            7: {'address': 'aktivenforum@example.cde',
                'description': None,
                'assembly_id': None,
                'attachment_policy': 2,
                'event_id': None,
                'id': 7,
                'is_active': True,
                'maxsize': 1024,
                'ml_type': 3,
                'mod_policy': 2,
                'moderators': {2, 10},
                'registration_stati': [],
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
            'ml_type': const.MailinglistTypes.member_moderated_opt_in,
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
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'fidel@example.cde',
                'che@example.cde',
            },
            'ml_type': 5,
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
    def test_mailinglist_creation_optional_fields(self, user):
        new_data = {
            'address': 'revolution1@example.cde',
            'description': 'Vereinigt Euch',
            'attachment_policy': const.AttachmentPolicy.forbid,
            'is_active': True,
            'maxsize': None,
            'ml_type': const.MailinglistTypes.member_moderated_opt_in,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': {2, 9},
            'notes': None,
            'subject_prefix': 'viva la revolution',
            'title': 'Proletarier aller Länder',
        }
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['address'] += "x"
        new_data['registration_stati'] = [const.RegistrationPartStati.guest]
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['registration_stati'] = []
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['address'] += "x"
        new_data['whitelist'] = "datenbank@example.cde"
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['address'] += "x"
        new_data['whitelist'] = ["datenbank@example.cde"]
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['address'] += "x"
        new_data['whitelist'] = []
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['address'] += "x"
        new_data['event_id'] = 1
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['event_id'] = None
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['address'] += "x"
        new_data['assembly_id'] = 1
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['assembly_id'] = None
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))

    @as_users("anton")
    def test_sample_data(self, user):
        ml_ids = self.ml.list_mailinglists(self.key, active_only=False)

        for ml_id in ml_ids:
            with self.subTest(ml_id=ml_id):
                expectation = self.ml.get_subscription_states(self.key, ml_id)
                self.ml.write_subscription_states(self.key, ml_id)
                result = self.ml.get_subscription_states(self.key, ml_id)

                self.assertEqual(expectation, result)

    @as_users("nina", "berta")
    def test_moderator_set_mailinglist(self, user):
        mailinglist_id = 7

        mdata = {
            'id': mailinglist_id,
            'moderators': {2, 10, 1},
            'whitelist': {'link@example.cde'},
        }
        expectation = self.ml.get_mailinglist(self.key, mailinglist_id)
        expectation.update(mdata)

        if user['id'] in {2}:
            with self.assertRaises(PrivilegeError):
                self.ml.set_mailinglist(self.key, mdata)
            self.assertLess(0, self.ml.set_moderators(self.key, mdata['id'], mdata['moderators']))
            self.assertLess(0, self.ml.set_whitelist(self.key, mdata['id'], mdata['whitelist']))
        else:
            self.assertLess(0, self.ml.set_mailinglist(self.key, mdata))

        reality = self.ml.get_mailinglist(self.key, mailinglist_id)
        self.assertEqual(expectation, reality)

    @as_users("anton", "berta")
    def test_subscriptions(self, user):
        # Which lists is Berta subscribed to.
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.unsubscribed,
            4: SS.subscribed,
            5: SS.implicit,
            6: SS.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=2))

    @as_users("anton", "janis")
    def test_subscriptions_two(self, user):
        # Which lists is Janis subscribed to.
        expectation = {
            3: SS.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=10))

    @as_users("anton", "emilia")
    def test_subscriptions_three(self, user):
        expectation = {
            9: SS.unsubscribed,
            10: SS.implicit,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=5))

    @as_users("anton", "garcia")
    def test_subscriptions_four(self, user):
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            4: SS.unsubscription_override,
            8: SS.implicit,
            9: SS.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=7))

    # These are some helpers to make the following tests less ugly
    def _check_state(self, persona_id, mailinglist_id, expected_state):
        """This asserts that user has expected_state on given mailinglist."""
        state = self.ml.get_subscription(
            self.key, persona_id=persona_id, mailinglist_id=mailinglist_id)
        if expected_state is not None:
            self.assertEqual(state, expected_state)
        else:
            self.assertIsNone(state)

    def _change_sub(self, persona_id, mailinglist_id, action, code=None,
                    state=None, kind=None):
        """This calls functions to (administratively) modify the own subscription
        state on a given mailinglist to state and asserts they return code and
        have the correct state after the operation. code=None asserts that a
        SubscriptionError is raised. If kind is given, the error is verified
        to be of the specified kind."""
        if code is not None:
            result = self.ml.do_subscription_action(
                self.key, action, mailinglist_id=mailinglist_id,
                persona_id=persona_id)
            self.assertEqual(result, code)
            action_state = action.get_target_state()
        else:
            with self.assertRaises(SubscriptionError) as cm:
                self.ml.do_subscription_action(
                    self.key, action, mailinglist_id=mailinglist_id,
                    persona_id=persona_id)
            if kind is not None:
                self.assertEqual(cm.exception.kind, kind)
            action_state = state
        # "This asserts that user has state on a given mailinglist.
        actual_state = self.ml.get_subscription(
            self.key, persona_id=persona_id, mailinglist_id=mailinglist_id)
        if state is not None:
            self.assertEqual(actual_state, state)
            self.assertEqual(actual_state, action_state)
        else:
            self.assertIsNone(actual_state)
            self.assertIsNone(action_state)
        # In case of success and check if log entry was created, if the required
        # permissions are present. This should work for moderators as well,
        # but it does not for some reason.
        if code is not None and self.ml.may_manage(self.key, mailinglist_id):
            log_entry = {
                'additional_info': None,
                'code': action.get_log_code(),
                'ctime': nearly_now(),
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'submitted_by': persona_id
            }
            self.assertIn(
                log_entry, self.ml.retrieve_log(
                    self.key, mailinglist_id=mailinglist_id))

    @as_users("anton", "berta", "ferdinand")
    def test_opt_in(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 7

        # Be aware that Ferdinands subscription is pending even though
        # this list is opt in. He should just be able to subscribe now.
        # This plays around with subscribing and unsubscribing.
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=SS.subscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.subscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=None, state=SS.unsubscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.unsubscribed, kind="info")

        # This does some basic override testing.
        self._change_sub(user['id'], mailinglist_id,
                         SA.add_unsubscription_override,
                         code=1, state=SS.unsubscription_override)
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=SS.unsubscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.unsubscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=None, state=SS.unsubscription_override, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.unsubscription_override, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscription_override,
                         code=1, state=SS.subscription_override)
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.subscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=SS.subscription_override, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.subscription_override, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         code=None, state=SS.unsubscribed, kind="error")

        # You cannot request subscriptions to such lists
        self._change_sub(user['id'], mailinglist_id,
                         SA.request_subscription,
                         code=None, state=SS.unsubscribed, kind="error")

        # This adds and removes some subscriptions
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.subscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.unsubscribed, kind="info")

        # This does more override management testing
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_unsubscription_override,
                         code=None, state=SS.unsubscribed, kind="error")
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         code=None, state=SS.unsubscribed, kind="error")
        self._change_sub(user['id'], mailinglist_id,
                             SA.subscribe,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id,
                         SA.add_unsubscription_override,
                         code=1, state=SS.unsubscription_override)
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_unsubscription_override,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'], mailinglist_id,
                         SA.add_subscription_override,
                         code=1, state=SS.subscription_override)
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         code=None, state=SS.subscribed, kind="error")

    @as_users("anton", "berta", "ferdinand")
    def test_moderated_opt_in(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 4

        # Anton and Berta are already subscribed, unsubscribe them first
        if user['id'] in {1, 2}:
            self._change_sub(user['id'], mailinglist_id,
                                 SA.unsubscribe,
                             code=1, state=SS.unsubscribed)

        # Try to subscribe
        expected_state = SS.unsubscribed if user['id'] in {1, 2} else None
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=expected_state, kind="error")

        # Test cancelling a subscription request
        self._change_sub(user['id'], mailinglist_id, SA.request_subscription,
                         code=1, state=SS.pending)
        self._change_sub(user['id'], mailinglist_id, SA.cancel_request,
                         code=1, state=None)
        self._change_sub(user['id'], mailinglist_id, SA.deny_request,
                         code=None, state=None)

        # Test different resolutions
        self._change_sub(user['id'], mailinglist_id, SA.request_subscription,
                         code=1, state=SS.pending)
        self._change_sub(user['id'], mailinglist_id, SA.deny_request,
                         code=1, state=None)

        self._change_sub(user['id'], mailinglist_id, SA.request_subscription,
                         code=1, state=SS.pending)
        self._change_sub(user['id'], mailinglist_id, SA.approve_request,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)

        # Make sure it is impossible to subscribe if blocked
        self._change_sub(user['id'], mailinglist_id, SA.request_subscription,
                         code=1, state=SS.pending)
        self._change_sub(user['id'], mailinglist_id, SA.block_request,
                         code=1, state=SS.unsubscription_override)
        self._change_sub(user['id'], mailinglist_id,
                         SA.request_subscription,
                         code=None, state=SS.unsubscription_override, kind="error")

        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_unsubscription_override,
                         code=1, state=SS.unsubscribed)

        # Make sure it is impossible to remove a subscription request without
        # actually deciding it
        self._change_sub(user['id'], mailinglist_id, SA.request_subscription,
                         code=1, state=SS.pending)
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.pending, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscription_override,
                         code=None, state=SS.pending, kind="error")
        self._change_sub(user['id'], mailinglist_id,
                         SA.add_unsubscription_override,
                         code=None, state=SS.pending, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.deny_request,
                         code=1, state=None)
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=1, state=SS.subscribed)

    @as_users("anton", "ferdinand")
    def test_opt_out(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 2
        
        # Ferdinand is unsubscribed already, resubscribe
        if user['id'] == 6:
            self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                             code=1, state=SS.subscribed)
        
        # Now we have a mix of explicit and implicit subscriptions, try to
        # subscribe again
        expected_state = SS.subscribed if user['id'] in {6, 14} else SS.implicit
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=expected_state, kind="info")
            
        # Now everyone unsubscribes (twice)
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=None, state=SS.unsubscribed, kind="info")

        # Test administrative subscriptions
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.subscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=SS.subscribed, kind="info")
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=1, state=SS.unsubscribed)

        # Test blocks
        self._change_sub(user['id'], mailinglist_id, SA.add_unsubscription_override,
                         code=1, state=SS.unsubscription_override)
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=SS.unsubscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=SS.unsubscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.remove_unsubscription_override,
                         code=1, state=SS.unsubscribed)

        # Test forced subscriptions
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'], mailinglist_id, SA.add_subscription_override,
                         code=1, state=SS.subscription_override)
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.subscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)

    @as_users("anton", "berta", "ferdinand")
    def test_mandatory(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1

        def _try_unsubscribe(expected_state):
            # Try to unsubscribe
            self._change_sub(user['id'], mailinglist_id,
                             SA.unsubscribe,
                             code=None, state=expected_state, kind="error")
            # Try to remove subscription
            self._change_sub(user['id'], mailinglist_id,
                             SA.remove_subscriber,
                             code=None, state=expected_state, kind="error")
            # Try to block user
            self._change_sub(user['id'], mailinglist_id,
                             SA.add_unsubscription_override,
                             code=None, state=expected_state, kind="error")

        _try_unsubscribe(SS.implicit)

        # Force subscription
        self._change_sub(user['id'], mailinglist_id, SA.add_subscription_override,
                         code=1, state=SS.subscription_override)
        _try_unsubscribe(SS.subscription_override)

        # Remove forced subscription
        self._change_sub(user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         code=1, state=SS.subscribed)
        _try_unsubscribe(SS.subscribed)

        # For admins, some shallow cron testing
        if user['id'] != 2:
            self.ml.write_subscription_states(self.key, mailinglist_id)
            self._check_state(user['id'], mailinglist_id, SS.subscribed)

    @as_users('nina')
    def test_mandatory_two(self, user):
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1

        # Try to subscribe somehow
        self._change_sub(user['id'], mailinglist_id, SA.subscribe,
                         code=None, state=None, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.add_subscriber,
                         code=None, state=None, kind="error")

        # Force subscription
        self._change_sub(user['id'], mailinglist_id, SA.add_subscription_override,
                         code=1, state=SS.subscription_override)

        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(user['id'], mailinglist_id, SS.subscription_override)

        # It is impossible to unsubscribe normally
        self._change_sub(user['id'], mailinglist_id, SA.unsubscribe,
                         code=None, state=SS.subscription_override, kind="error")
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscriber,
                         code=None, state=SS.subscription_override, kind="error")

        # Remove subscription
        self._change_sub(user['id'], mailinglist_id, SA.remove_subscription_override,
                         code=1, state=SS.subscribed)

        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(user['id'], mailinglist_id, None)

    @as_users("anton")
    def test_ml_event(self, user):
        ml_id = 9

        expectation = {
            1: SS.implicit,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=None, state=SS.implicit, kind="info")
        self._change_sub(user['id'],  ml_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'],  ml_id, SA.unsubscribe,
                         code=None, state=SS.unsubscribed, kind="info")
        self._change_sub(user['id'],  ml_id, SA.request_subscription,
                         code=None, state=SS.unsubscribed, kind="error")
        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=1, state=SS.subscribed)
        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=None, state=SS.subscribed, kind="info")

        self.ml.write_subscription_states(self.key, ml_id)

        expectation = {
            1: SS.subscribed,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        mdata = {
            'id': ml_id,
            'event_id': 2,
            'ml_type': const.MailinglistTypes.event_associated,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            5: SS.unsubscribed,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=None, state=None, kind="error")
        self._change_sub(user['id'],  ml_id, SA.unsubscribe,
                         code=None, state=None, kind="info")
        self._change_sub(user['id'],  ml_id, SA.request_subscription,
                         code=None, state=None, kind="error")

    @as_users("ferdinand")
    def test_ml_event_two(self, user):
        ml_id = 9

        self._change_sub(user['id'], ml_id, SA.subscribe,
                         code=None, state=None, kind="error")
        self._change_sub(user['id'], ml_id, SA.add_subscriber,
                         code=None, state=None, kind="error")

    @as_users("anton")
    def test_ml_assembly(self, user):
        ml_id = 5

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.subscription_override,
            9: SS.unsubscription_override,
            11: SS.implicit,
            14: SS.subscription_override,
            23: SS.implicit,
            100: SS.subscription_override,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=None, state=SS.implicit, kind="info")
        self._change_sub(user['id'],  ml_id, SA.unsubscribe,
                         code=1, state=SS.unsubscribed)
        self._change_sub(user['id'],  ml_id, SA.unsubscribe,
                         code=None, state=SS.unsubscribed, kind="info")
        self._change_sub(user['id'],  ml_id, SA.request_subscription,
                         code=None, state=SS.unsubscribed, kind="error")
        self._change_sub(user['id'],  ml_id, SA.subscribe,
                         code=1, state=SS.subscribed)

    @as_users("anton", "nina")
    def test_bullshit_requests(self, user):
        # Can I remove people from lists they have not subscribed to?
        with self.assertRaises(SubscriptionError) as cm:
            self.ml.do_subscription_action(
                self.key, SA.remove_subscriber, mailinglist_id=2, persona_id=6)
        self.assertIn("User already unsubscribed.", cm.exception.args)
        self._check_state(
            mailinglist_id=2, persona_id=6, expected_state=SS.unsubscribed)

        with self.assertRaises(SubscriptionError) as cm:
            self.ml.do_subscription_action(
                self.key, SA.remove_subscriber, mailinglist_id=3, persona_id=2)
        self.assertIn("User already unsubscribed.", cm.exception.args)
        self._check_state(
            mailinglist_id=3, persona_id=2, expected_state=SS.unsubscribed)

        with self.assertRaises(SubscriptionError) as cm:
            self.ml.do_subscription_action(
                self.key, SA.remove_subscriber, mailinglist_id=3, persona_id=3)
        self.assertIn("User already unsubscribed.", cm.exception.args)
        self._check_state(
            mailinglist_id=3, persona_id=3, expected_state=None)

    @as_users("charly", "emilia", "janis")
    def test_no_privileges(self, user):

        def _try_everything(ml_id, user_id):
            moderator_actions = {
                SA.add_subscriber, SA.remove_subscriber,
                SA.add_subscription_override, SA.remove_subscription_override,
                SA.add_unsubscription_override, SA.remove_unsubscription_override}
            for action in moderator_actions:
                with self.assertRaises(PrivilegeError):
                    self.ml.do_subscription_action(
                        self.key, action, mailinglist_id=ml_id,
                        persona_id=user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.do_subscription_action(
                    self.key, SA.approve_request, mailinglist_id=ml_id,
                    persona_id=user_id)
            # You had never the chance to actually change something anyway.
            with self.assertRaises(PrivilegeError):
                datum = {
                    'mailinglist_id': ml_id,
                    'persona_id': user_id,
                    'subscription_state': SS.unsubscribed,
                }
                self.ml._set_subscription(datum)

        # Make sure moderator functions do not tell you anything.
        # Garcia (7) is listed implicitly, explicitly or not at all on these
        for ml_id in {1, 4, 5, 6, 8, 9}:
            _try_everything(ml_id, USER_DICT['garcia']['id'])

        # Users have very diverse states on list 5.
        for subscriber in USER_DICT.values():
            _try_everything(5, subscriber['id'])

    @as_users("janis", "kalif")
    def test_audience(self, user):
        # List 4 is moderated opt-in for members only.
        self._change_sub(user['id'], 4, SA.subscribe,
                         code=None, state=None, kind="error")
        self._change_sub(user['id'], 4, SA.request_subscription,
                         code=None, state=None, kind="error")
        self._change_sub(user['id'], 4, SA.cancel_request,
                         code=None, state=None, kind="error")
        # List 7 is not joinable by non-members
        self._change_sub(user['id'], 7, SA.subscribe,
                         code=None, state=None, kind="error")
        # List 9 is only allowed for event users, and not joinable anyway
        self._change_sub(user['id'],  9, SA.subscribe,
                         code=None, state=None, kind="error")
        # List 11 is only joinable by assembly users
        if user['id'] == 11:
            self._change_sub(user['id'], 11, SA.unsubscribe,
                             code=1, state=SS.unsubscribed)
            self._change_sub(user['id'], 11, SA.subscribe,
                             code=1, state=SS.subscribed)
        else:
            self._change_sub(user['id'], 11, SA.subscribe,
                             code=None, state=None, kind="error")

    @as_users("anton")
    def test_write_subscription_states(self, user):
        # CdE-Member list.
        mailinglist_id = 7

        expectation = {
            1: SS.unsubscribed,
            3: SS.subscribed,
            6: SS.pending,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Add and change some subscriptions.
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': SS.subscribed,
            }
            for persona_id in [1, 4, 5, 9]
        ]
        self.ml._set_subscriptions(self.key, data)
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': SS.subscription_override,
            }
            for persona_id in [4]
        ]
        self.ml._set_subscriptions(self.key, data)

        expectation = {
            1: SS.subscribed,
            3: SS.subscribed,
            4: SS.subscription_override,
            5: SS.subscribed,
            6: SS.pending,
            9: SS.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: SS.subscribed,
            3: SS.subscribed,
            4: SS.subscription_override,
            6: SS.pending,
            9: SS.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Check that this has been logged
        log_entry = {
            'additional_info': None,
            'code': const.MlLogCodes.cron_removed,
            'ctime': nearly_now(),
            'mailinglist_id': mailinglist_id,
            'persona_id': 5,
            'submitted_by': user['id']
        }
        self.assertIn(
            log_entry, self.ml.retrieve_log(
                self.key, mailinglist_id=mailinglist_id))

        # Now test lists with implicit subscribers.
        # First for events.
        mailinglist_id = 9

        # Initially sample-data.
        expectation = {
            1: SS.implicit,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: SS.implicit,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now for assemblies.
        mailinglist_id = 5

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.subscription_override,
            9: SS.unsubscription_override,
            11: SS.implicit,
            14: SS.subscription_override,
            23: SS.implicit,
            100: SS.subscription_override,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        self.assertLess(
            0, self.ml.write_subscription_states(self.key, mailinglist_id))

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.subscription_override,
            9: SS.unsubscription_override,
            11: SS.implicit,
            14: SS.subscription_override,
            23: SS.implicit,
            100: SS.subscription_override,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("anton")
    def test_change_sub_policy(self, user):
        pass
        mdata = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': set(),
            'registration_stati': [],
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'fidel@example.cde',
                'che@example.cde',
            },
            'ml_type': const.MailinglistTypes.member_invitation_only,
        }
        new_id = self.ml.create_mailinglist(self.key, mdata)

        # List should have no subscribers.
        self.assertEqual({}, self.ml.get_subscription_states(self.key, new_id))

        # Making the list Opt-Out should yield implicits subscribers.
        mdata = {
            'id': new_id,
            'ml_type': const.MailinglistTypes.member_opt_out,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.implicit,
            6: SS.implicit,
            7: SS.implicit,
            9: SS.implicit,
            12: SS.implicit,
            13: SS.implicit,
            22: SS.implicit,
            23: SS.implicit,
            27: SS.implicit,
            32: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        # Opt-Out allows unsubscribing.
        sub_data = [
            {
                'mailinglist_id': new_id,
                'persona_id': 2,
                'subscription_state': SS.unsubscribed,
            },
            # Not in the audience, should get removed in the next step.
            {
                'mailinglist_id': new_id,
                'persona_id': 4,
                'subscription_state': SS.unsubscription_override,
            },
            {
                'mailinglist_id': new_id,
                'persona_id': 7,
                'subscription_state': SS.unsubscription_override,
            },
            {
                'mailinglist_id': new_id,
                'persona_id': 12,
                'subscription_state': SS.pending,
            },
        ]
        self.ml._set_subscriptions(self.key, sub_data)

        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            3: SS.implicit,
            4: SS.unsubscription_override,
            6: SS.implicit,
            7: SS.unsubscription_override,
            9: SS.implicit,
            12: SS.pending,
            13: SS.implicit,
            22: SS.implicit,
            23: SS.implicit,
            27: SS.implicit,
            32: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        # Making the list mandatory should get rid of all unsubscriptions, even
        # outside of the audience.
        mdata = {
            'id': new_id,
            'ml_type': const.MailinglistTypes.member_mandatory,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.implicit,
            6: SS.implicit,
            7: SS.implicit,
            9: SS.implicit,
            12: SS.implicit,
            13: SS.implicit,
            22: SS.implicit,
            23: SS.implicit,
            27: SS.implicit,
            32: SS.implicit,
            100: SS.implicit,
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
            'event_id': 2,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': set(),
            'registration_stati': [],
            'subject_prefix': 'orga',
            'title': 'Orgateam',
            'notes': None,
            'ml_type': const.MailinglistTypes.event_orga,
        }
        new_id = self.ml.create_mailinglist(self.key, mdata)

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'event_id': 1,
            'ml_type': const.MailinglistTypes.event_orga,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            7: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'ml_type': const.MailinglistTypes.event_associated,
            'registration_stati': [const.RegistrationPartStati.guest,
                                   const.RegistrationPartStati.cancelled],
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            5: SS.implicit,
            9: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

        mdata = {
            'id': new_id,
            'ml_type': const.MailinglistTypes.assembly_associated,
            'event_id': None,
            'assembly_id': 1,
        }
        self.ml.set_mailinglist(self.key, mdata)

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            9: SS.implicit,
            11: SS.implicit,
            23: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

    @as_users("anton", "janis")
    def test_subscription_addresses(self, user):
        expectation = {
            1: 'anton@example.cde',
            2: 'berta@example.cde',
            3: 'charly@example.cde',
            7: 'garcia@example.cde',
            9: 'inga@example.cde',
            12: None,
            13: 'martin@example.cde',
            22: 'vera@example.cde',
            23: 'werner@example.cde',
            27: 'annika@example.cde',
            32: 'farin@example.cde',
            100: 'akira@example.cde'
        ,
        }
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 2))
        expectation = {
            1: 'new-anton@example.cde',
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
                       14: 'nina@example.cde',
                       23: 'werner@example.cde',
                       100: 'akira@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 5))

    @as_users("anton", "garcia")
    def test_subscription_addresses_three(self, user):
            expectation = {7: 'garcia@example.cde'}
            self.assertEqual(expectation,
                             self.ml.get_subscription_addresses(self.key, 8))
            expectation = {1: 'anton@example.cde',
                           7: 'garcia@example.cde',
                           9: 'inga@example.cde',
                           100: 'akira@example.cde'}
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
            1: 'new-anton@example.cde',
            10: 'janis-spam@example.cde',
        }
        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Add an addresses.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'email': "anton-spam@example.cde",
        }
        expectation.update({datum['persona_id']: datum['email']})
        self.ml.set_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
            'email': "anton-cde@example.cde",
        }
        expectation.update({datum['persona_id']: datum['email']})
        self.ml.set_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Remove an address.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': user['id'],
        }
        expectation.update({user['id']: user['username']})
        self.ml.remove_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("janis")
    def test_remove_subscription_address(self, user):
        mailinglist_id = 3

        # Check sample data.
        expectation = {
            1: 'new-anton@example.cde',
            10: 'janis-spam@example.cde',
        }
        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        expectation = {
            1: SS.subscribed,
            2: SS.unsubscribed,
            10: SS.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Now let janis delete his changed address

        expectation = {
            1: 'new-anton@example.cde',
            10: USER_DICT["janis"]["username"],
        }
        datum = {'persona_id': 10, 'mailinglist_id': mailinglist_id}
        self.assertLess(
            0, self.ml.remove_subscription_address(self.key, **datum))

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        expectation = {
            1: SS.subscribed,
            2: SS.unsubscribed,
            10: SS.subscribed,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("inga")
    def test_moderation(self, user):
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            5: SS.unsubscription_override,
            9: SS.implicit,
            11: SS.unsubscription_override,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))
        data = [
            {
                'mailinglist_id': 2,
                'persona_id': 9,
                'subscription_state': SS.unsubscribed,
            },
            {
                'mailinglist_id': 9,
                'persona_id': 9,
                'subscription_state': SS.unsubscribed,
            },
            {
                'mailinglist_id': 4,
                'persona_id': 9,
                'subscription_state': SS.pending,
            },
        ]
        self.ml._set_subscriptions(self.key, data)
        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            4: SS.pending,
            5: SS.unsubscription_override,
            9: SS.unsubscribed,
            11: SS.unsubscription_override,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

        self.login(USER_DICT['berta'])
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
        }
        self.assertLess(
            0,
            self.ml.do_subscription_action(self.key, SA.approve_request, **datum))

        self.login(USER_DICT['inga'])
        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            4: SS.subscribed,
            5: SS.unsubscription_override,
            9: SS.unsubscribed,
            11: SS.unsubscription_override,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state': SS.unsubscribed,
        }
        self.ml._set_subscription(self.key, datum)
        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            4: SS.unsubscribed,
            5: SS.unsubscription_override,
            9: SS.unsubscribed,
            11: SS.unsubscription_override
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state': SS.pending,
        }
        self.ml._set_subscription(self.key, datum)
        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            4: SS.pending,
            5: SS.unsubscription_override,
            9: SS.unsubscribed,
            11: SS.unsubscription_override,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

        self.login(USER_DICT['berta'])
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
        }
        self.assertLess(
            0,
            self.ml.do_subscription_action(self.key, SA.deny_request, **datum))

        self.login(USER_DICT['inga'])
        expectation = {
            1: SS.implicit,
            2: SS.unsubscribed,
            5: SS.unsubscription_override,
            9: SS.unsubscribed,
            11: SS.unsubscription_override,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

    @as_users("inga")
    def test_request_cancellation(self, user):
        expectation = None
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
            'subscription_state': SS.pending,
        }
        self.ml._set_subscription(self.key, datum)
        expectation = SS.pending
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))
        datum = {
            'mailinglist_id': 4,
            'persona_id': 9,
        }
        self.assertLess(
            0,
            self.ml.do_subscription_action(self.key, SA.cancel_request, **datum))
        expectation = None
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))

    @as_users("anton")
    def test_log(self, user):
        # first generate some data
        self.ml.do_subscription_action(self.key, SA.unsubscribe, 2, 1)
        datum = {
            'mailinglist_id': 4,
            'persona_id': 1,
            'email': 'devnull@example.cde',
        }
        self.ml.set_subscription_address(self.key, **datum)
        self.ml.do_subscription_action(self.key, SA.add_subscriber, 7, 1)
        new_data = {
            'address': 'revolution@example.cde',
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': 3,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': 1,
            'moderators': {1, 2},
            'registration_stati': [],
            'subject_prefix': '[viva la revolution]',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'che@example.cde',
            },
            'ml_type': const.MailinglistTypes.member_invitation_only,
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
             'code': const.MlLogCodes.list_created,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': None,
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
             'mailinglist_id': 2,
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
            expectation[2:4],
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
                            'garcia@example.cde',
                            'inga@example.cde',
                            'martin@example.cde',
                            'vera@example.cde',
                            'werner@example.cde',
                            'annika@example.cde',
                            'farin@example.cde',
                            'akira@example.cde'),
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
                                       'garcia@example.cde',
                                       'inga@example.cde',
                                       'martin@example.cde',
                                       'vera@example.cde',
                                       'werner@example.cde',
                                       'annika@example.cde',
                                       'farin@example.cde',
                                       'akira@example.cde'),
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
