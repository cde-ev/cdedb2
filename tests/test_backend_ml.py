#!/usr/bin/env python3

from typing import Collection, Set, Optional, cast

import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
from cdedb.common import (
    CdEDBObject, PrivilegeError, RequestState, nearly_now,
)
from cdedb.database.constants import SubscriptionState as SS
from cdedb.subman.exceptions import SubscriptionError
from cdedb.subman.machine import SubscriptionAction as SA
from tests.common import USER_DICT, BackendTest, as_users, prepsql


class TestMlBackend(BackendTest):
    used_backends = ("core", "ml")

    @as_users("janis")
    def test_basics(self) -> None:
        data = self.core.get_ml_user(self.key, self.user['id'])
        data['display_name'] = "Zelda"
        data['family_name'] = "Lord von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'given_names', 'family_name'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_ml_user(self.key, self.user['id'])
        self.assertEqual(data, new_data)

    @as_users("anton")
    def test_merge_accounts(self) -> None:
        berta_id = USER_DICT['berta']['id']
        janis_id = USER_DICT['janis']['id']

        # try some failing cases
        with self.assertRaises(ValueError) as e:
            self.ml.merge_accounts(self.key,
                                   source_persona_id=USER_DICT['rowena']['id'],
                                   target_persona_id=berta_id)
        self.assertEqual("Source persona must be a ml-only user.", str(e.exception))

        with self.assertRaises(ValueError) as e:
            self.ml.merge_accounts(self.key,
                                   source_persona_id=USER_DICT['nina']['id'],
                                   target_persona_id=berta_id)
        self.assertEqual("Source User is admin and can not be merged.", str(e.exception))

        with self.assertRaises(ValueError) as e:
            self.ml.merge_accounts(self.key,
                                   source_persona_id=janis_id,
                                   target_persona_id=USER_DICT['hades']['id'])
        self.assertEqual("Target User is not accessible.", str(e.exception))

        code = self.ml.merge_accounts(self.key,
                                      source_persona_id=janis_id,
                                      target_persona_id=berta_id)
        self.assertEqual(code, 0)
        self.assertFalse(self.core.get_persona(self.key, janis_id)["is_archived"])

        # remove the blocking subscription of berta
        self.ml._remove_subscription(self.key, {'mailinglist_id': 3, 'persona_id': 2})
        berta_mls = self.ml.get_user_subscriptions(self.key, berta_id)
        berta_mod = self.ml.moderator_info(self.key, berta_id)
        janis_mls = self.ml.get_user_subscriptions(self.key, janis_id)
        janis_mod = self.ml.moderator_info(self.key, janis_id)
        code = self.ml.merge_accounts(self.key,
                                      source_persona_id=janis_id,
                                      target_persona_id=berta_id)
        self.assertLess(0, code)

        # assert the merging of subscription states and moderator rights was successfull
        berta_new_mls = self.ml.get_user_subscriptions(self.key, berta_id)
        berta_new_mod = self.ml.moderator_info(self.key, berta_id)
        self.assertEqual(berta_new_mls, {**berta_mls, **janis_mls})
        self.assertEqual(berta_new_mod, berta_mod | janis_mod)

        # check the logs
        expectation = (8, (
            {'change_note': 'Nutzer 10 ist in diesem Account aufgegangen.',
             'code': const.MlLogCodes.subscribed,
             'ctime': nearly_now(),
             'id': 1001,
             'mailinglist_id': 3,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'janis-spam@example.cde',
             'code': const.MlLogCodes.subscription_changed,
             'ctime': nearly_now(),
             'id': 1002,
             'mailinglist_id': 3,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'Nutzer 10 ist in diesem Account aufgegangen.',
             'code': const.MlLogCodes.subscribed,
             'ctime': nearly_now(),
             'id': 1003,
             'mailinglist_id': 64,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'janis@example.cde',
             'code': const.MlLogCodes.subscription_changed,
             'ctime': nearly_now(),
             'id': 1004,
             'mailinglist_id': 64,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'Nutzer 10 ist in diesem Account aufgegangen.',
             'code': const.MlLogCodes.subscribed,
             'ctime': nearly_now(),
             'id': 1005,
             'mailinglist_id': 65,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'janis@example.cde',
             'code': const.MlLogCodes.subscription_changed,
             'ctime': nearly_now(),
             'id': 1006,
             'mailinglist_id': 65,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'Nutzer 10 ist in diesem Account aufgegangen.',
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'id': 1007,
             'mailinglist_id': 2,
             'persona_id': 2,
             'submitted_by': 1},
            {'change_note': 'Nutzer 10 ist in diesem Account aufgegangen.',
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'id': 1008,
             'mailinglist_id': 63,
             'persona_id': 2,
             'submitted_by': 1}))
        self.assertEqual(expectation, self.ml.retrieve_log(self.key))

        # assure janis is archived
        janis = self.core.get_persona(self.key, janis_id)
        self.assertTrue(janis['is_archived'])

    @as_users("nina")
    def test_entity_mailinglist(self) -> None:
        expectation = {
            1: 'Verkündungen',
            2: 'Werbung',
            3: 'Witz des Tages',
            4: 'Klatsch und Tratsch',
            5: 'Sozialistischer Kampfbrief',
            7: 'Aktivenforum 2001',
            8: 'Orga-Liste',
            9: 'Teilnehmer-Liste',
            10: 'Warte-Liste',
            11: 'Kampfbrief-Kommentare',
            12: 'Moderatoren-Liste',
            13: 'Allumfassende Liste',
            14: 'Lokalgruppen-Liste',
            51: 'CdE-All',
            52: 'CdE-Info',
            53: 'Mitgestaltungsforum',
            54: 'Gutscheine',
            55: 'Platin-Lounge',
            56: 'Feriendorf Bau',
            57: 'Geheimbund',
            58: 'Testakademie 2222, Gäste',
            59: 'CdE-Party 2050 Orgateam',
            60: 'CdE-Party 2050 Teilnehmer',
            61: 'Kanonische Beispielversammlung',
            62: 'Walergebnisse',
            63: 'DSA-Liste',
            64: 'Das Leben, das Universum ...',
            65: 'Hogwarts',
            66: 'Versammlungsleitung Internationaler Kongress',
            99: 'Mailman-Migration',
        }
        self.assertEqual(expectation, self.ml.list_mailinglists(self.key))
        expectation[6] = 'Aktivenforum 2000'
        self.assertEqual(expectation,
                         self.ml.list_mailinglists(self.key, active_only=False))
        expectation = {
            3: {'local_part': 'witz',
                'domain': const.MailinglistDomain.lists,
                'domain_str': 'lists.cde-ev.de',
                'address': 'witz@lists.cde-ev.de',
                'description': "Einer geht noch ...",
                'assembly_id': None,
                'attachment_policy': const.AttachmentPolicy.pdf_only.value,
                'event_id': None,
                'id': 3,
                'is_active': True,
                'maxsize': 2048,
                'ml_type': const.MailinglistTypes.general_opt_in.value,
                'ml_type_class': ml_type.GeneralOptInMailinglist,
                'mod_policy': const.ModerationPolicy.non_subscribers.value,
                'moderators': {2, 3, 10},
                'registration_stati': [],
                'subject_prefix': 'witz',
                'title': 'Witz des Tages',
                'notes': None,
                'whitelist': set()},
            5: {'local_part': 'kongress',
                'domain': const.MailinglistDomain.lists,
                'domain_str': 'lists.cde-ev.de',
                'address': 'kongress@lists.cde-ev.de',
                'description': None,
                'assembly_id': 1,
                'attachment_policy': const.AttachmentPolicy.pdf_only.value,
                'event_id': None,
                'id': 5,
                'is_active': True,
                'maxsize': 1024,
                'ml_type': const.MailinglistTypes.assembly_associated.value,
                'ml_type_class': ml_type.AssemblyAssociatedMailinglist,
                'mod_policy': const.ModerationPolicy.non_subscribers.value,
                'moderators': {2, 23},
                'registration_stati': [],
                'subject_prefix': 'kampf',
                'title': 'Sozialistischer Kampfbrief',
                'notes': None,
                'whitelist': set()},
            7: {'local_part': 'aktivenforum',
                'domain': const.MailinglistDomain.lists,
                'domain_str': 'lists.cde-ev.de',
                'address': 'aktivenforum@lists.cde-ev.de',
                'description': None,
                'assembly_id': None,
                'attachment_policy': const.AttachmentPolicy.pdf_only.value,
                'event_id': None,
                'id': 7,
                'is_active': True,
                'maxsize': 1024,
                'ml_type': const.MailinglistTypes.member_opt_in.value,
                'ml_type_class': ml_type.MemberOptInMailinglist,
                'mod_policy': const.ModerationPolicy.non_subscribers.value,
                'moderators': {2, 10},
                'registration_stati': [],
                'subject_prefix': 'aktivenforum',
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
            'local_part': 'passivenforum',
            'notes': "this list is no more",
        }
        expectation = expectation[7]
        expectation.update(setter)
        expectation['ml_type_class'] = ml_type.MemberModeratedOptInMailinglist
        expectation['address'] = ml_type.get_full_address(expectation)
        self.assertLess(0, self.ml.set_mailinglist(self.key, setter))
        self.assertEqual(expectation, self.ml.get_mailinglist(self.key, 7))

    @as_users("janis")
    def test_double_link(self) -> None:
        setter = {
            'id': 7,
            'event_id': 1,
            'assembly_id': 1
        }
        with self.assertRaises(ValueError):
            self.ml.set_mailinglist(self.key, setter)

    @as_users("nina")
    def test_mailinglist_creation_deletion(self) -> None:
        oldlists = self.ml.list_mailinglists(self.key)
        new_data = {
            'local_part': 'revolution',
            'domain': const.MailinglistDomain.lists,
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': {1, 2},
            'registration_stati': [],
            'subject_prefix': 'viva la revolution',
            'title': 'Proletarier aller Länder',
            'notes': "secrecy is important",
            'whitelist': {
                'fidel@example.cde',
                'che@example.cde',
            },
            'ml_type': const.MailinglistTypes.member_invitation_only,
        }
        new_id = self.ml.create_mailinglist(self.key, new_data)
        self.assertLess(0, new_id)
        self.assertNotIn(new_id, oldlists)
        self.assertIn(new_id, self.ml.list_mailinglists(self.key))
        new_data['id'] = new_id
        new_data['address'] = ml_type.get_full_address(new_data)
        new_data['domain_str'] = str(new_data['domain'])
        atype = new_data['ml_type']
        assert isinstance(atype, const.MailinglistTypes)
        new_data['ml_type_class'] = ml_type.get_type(atype)
        self.assertEqual(new_data, self.ml.get_mailinglist(self.key, new_id))
        self.assertLess(0, self.ml.delete_mailinglist(
            self.key, new_id, cascade=("subscriptions", "addresses",
                                       "whitelist", "moderators", "log")))
        self.assertNotIn(new_id, self.ml.list_mailinglists(self.key))

    @as_users("nina")
    def test_mailinglist_creation_optional_fields(self) -> None:
        new_data = {
            'local_part': 'revolution',
            'domain': const.MailinglistDomain.lists,
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
        assert isinstance(new_data['moderators'], Set)
        new_data['moderators'] |= {100000}
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['moderators'] -= {100000}
        # Hades is archived.
        new_data['moderators'] |= {8}
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['moderators'] -= {8}
        assert isinstance(new_data['local_part'], str)
        new_data['local_part'] += "x"
        new_data['registration_stati'] = [const.RegistrationPartStati.guest]
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['registration_stati'] = []
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['local_part'] += "x"
        new_data['whitelist'] = "datenbank@example.cde"
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['local_part'] += "x"
        new_data['whitelist'] = ["datenbank@example.cde"]
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['local_part'] += "x"
        new_data['whitelist'] = []
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['local_part'] += "x"
        new_data['event_id'] = 1
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['event_id'] = None
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))
        new_data['local_part'] += "x"
        new_data['assembly_id'] = 1
        with self.assertRaises(ValueError):
            self.ml.create_mailinglist(self.key, new_data)
        new_data['assembly_id'] = None
        self.assertLess(0, self.ml.create_mailinglist(self.key, new_data))

    @as_users("nina")
    def test_sample_data(self) -> None:
        ml_ids = self.ml.list_mailinglists(self.key, active_only=False)

        for ml_id in ml_ids:
            with self.subTest(ml_id=ml_id):
                expectation = self.ml.get_subscription_states(self.key, ml_id)
                self.ml.write_subscription_states(self.key, ml_id)
                result = self.ml.get_subscription_states(self.key, ml_id)

                self.assertEqual(expectation, result)

    @as_users("nina", "berta", "janis")
    @prepsql("INSERT INTO ml.moderators (mailinglist_id, persona_id) VALUES (60, 10)")
    def test_moderator_set_mailinglist(self) -> None:
        mailinglist_id = 60

        admin_mdatas: Collection[CdEDBObject] = [
            {
                'id': mailinglist_id,
                'ml_type': const.MailinglistTypes.event_associated,
                'title': 'Hallo Welt',
            },
            {
                'id': mailinglist_id,
                'ml_type': const.MailinglistTypes.event_associated,
                'local_part': 'alternativ',
            },
            {
                'id': mailinglist_id,
                'ml_type': const.MailinglistTypes.event_associated,
                'is_active': False,
            },
            {
                'id': mailinglist_id,
                'ml_type': const.MailinglistTypes.event_associated,
                'event_id': 1,
                'registration_stati': [],
            },
            {
                'id': mailinglist_id,
                'ml_type': const.MailinglistTypes.event_orga,
                'event_id': None,
                'registration_stati': [],
            },
        ]

        restricted_mod_mdata = {
            'id': mailinglist_id,
            'ml_type': const.MailinglistTypes.event_associated,
            'description': "Nice one",
            'notes': "Blabediblubblabla",
            'mod_policy': const.ModerationPolicy.unmoderated,
            'attachment_policy': const.AttachmentPolicy.allow,
            'subject_prefix': 'Aufbruch',
            'maxsize': 101,
        }

        full_mod_mdata = {
            'id': mailinglist_id,
            'ml_type': const.MailinglistTypes.event_associated,
            'registration_stati': [const.RegistrationPartStati.applied],
        }

        expectation = self.ml.get_mailinglist(self.key, mailinglist_id)

        for data in admin_mdatas:
            # admins may change any attribute of a mailinglist
            if self.is_user('nina'):
                expectation.update(data)
                self.assertLess(0, self.ml.set_mailinglist(self.key, data))
            else:
                with self.assertRaises(PrivilegeError):
                    self.ml.set_mailinglist(self.key, data)

        # every moderator may change these attributes ...
        expectation.update(restricted_mod_mdata)
        self.assertLess(0, self.ml.set_mailinglist(self.key, restricted_mod_mdata))

        # ... but only full moderators (here: orgas) may change these.
        if self.is_user('janis'):
            with self.assertRaises(PrivilegeError):
                self.ml.set_mailinglist(self.key, full_mod_mdata)
        else:
            expectation.update(full_mod_mdata)
            self.assertLess(0, self.ml.set_mailinglist(self.key, full_mod_mdata))

        if self.is_user('nina'):
            # adjust address form changed local part
            expectation['address'] = 'alternativ@aka.cde-ev.de'

        reality = self.ml.get_mailinglist(self.key, mailinglist_id)
        self.assertEqual(expectation, reality)

    @as_users("nina", "berta")
    def test_subscriptions(self) -> None:
        # Which lists is Berta subscribed to.
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            3: SS.unsubscribed,
            4: SS.subscribed,
            5: SS.implicit,
            6: SS.subscribed,
            9: SS.implicit,
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            54: SS.pending,
            59: SS.implicit,
            63: SS.subscribed
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=2))

    @as_users("nina", "janis")
    def test_subscriptions_two(self) -> None:
        # Which lists is Janis subscribed to.
        expectation = {
            3: SS.subscribed,
            12: SS.implicit,
            13: SS.implicit,
            64: SS.subscribed,
            65: SS.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=10))

    @as_users("nina", "emilia")
    def test_subscriptions_three(self) -> None:
        expectation = {
            9: SS.unsubscribed,
            10: SS.implicit,
            12: SS.implicit,
            13: SS.implicit,
            14: SS.implicit,
            58: SS.implicit,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=5))

    @as_users("nina", "garcia")
    def test_subscriptions_four(self) -> None:
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            4: SS.unsubscription_override,
            8: SS.implicit,
            9: SS.subscribed,
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            54: SS.unsubscription_override,
            56: SS.pending,
            61: SS.implicit,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=7))

    # These are some helpers to make the following tests less ugly
    def _check_state(self, persona_id: int, mailinglist_id: int,
                     expected_state: SS) -> None:
        """This asserts that user has expected_state on given mailinglist."""
        state = self.ml.get_subscription(
            self.key, persona_id=persona_id, mailinglist_id=mailinglist_id)
        self.assertEqual(state, expected_state)

    def _change_sub(self, persona_id: int, mailinglist_id: int, action: SA,
                    state: SS, kind: str = None) -> None:
        """This calls functions to (administratively) modify the own subscription
        state on a given mailinglist to state and asserts they return code and
        have the correct state after the operation. If kind is given, we assert that a
        SubscriptionError of the specified kind is raised."""
        if kind is None:
            result = self.ml.do_subscription_action(
                self.key, action, mailinglist_id=mailinglist_id,
                persona_id=persona_id)
            self.assertEqual(result, 1)
            action_state = action.get_target_state()
        else:
            with self.assertRaises(SubscriptionError) as cm:
                self.ml.do_subscription_action(
                    self.key, action, mailinglist_id=mailinglist_id,
                    persona_id=persona_id)
            self.assertEqual(cm.exception.kind, kind)
            action_state = state
        # This asserts that user has state on a given mailinglist.
        actual_state = self.ml.get_subscription(
            self.key, persona_id=persona_id, mailinglist_id=mailinglist_id)
        self.assertEqual(actual_state, state)
        self.assertEqual(actual_state, action_state)
        # In case of success and check if log entry was created, if the required
        # permissions are present. This should work for moderators as well,
        # but it does not for some reason.
        if kind is None and self.ml.may_manage(self.key, mailinglist_id):
            expected_log = {
                'change_note': None,
                'code': const.MlLogCodes.from_subman(action),
                'ctime': nearly_now(),
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
            }
            _, log_entries = self.ml.retrieve_log(
                self.key, mailinglist_ids=[mailinglist_id])
            # its a bit annoying to check always the correct log id
            log_entries = [{k: v for k, v in log.items()
                            if k not in {'id', 'submitted_by'}}
                           for log in log_entries]
            self.assertIn(expected_log, log_entries)

    @as_users("anton", "berta", "ferdinand")
    def test_opt_in(self) -> None:
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 7

        # Be aware that Ferdinands subscription is pending even though
        # this list is opt in. He should just be able to subscribe now.
        # This plays around with subscribing and unsubscribing.
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscribed, kind="info")

        # This does some basic override testing.
        self._change_sub(self.user['id'], mailinglist_id, SA.add_unsubscription_override,
                         state=SS.unsubscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.unsubscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.unsubscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscription_override, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscription_override, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.subscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscription_override, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscription_override, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscription_override,
                         state=SS.unsubscribed, kind="error")

        # You cannot request subscriptions to such lists
        self._change_sub(self.user['id'], mailinglist_id,
                         SA.request_subscription,
                         state=SS.unsubscribed, kind="error")

        # This adds and removes some subscriptions
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscribed, kind="info")

        # This does more override management testing
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_unsubscription_override,
                         state=SS.unsubscribed, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscription_override,
                         state=SS.unsubscribed, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_unsubscription_override,
                         state=SS.unsubscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_unsubscription_override,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscription_override,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscription_override,
                         state=SS.subscribed, kind="error")

        # This tests the unsubscription reset.
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.reset,
                         state=SS.none)
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.reset,
                         state=SS.none)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)

    @as_users("anton", "berta", "ferdinand")
    def test_moderated_opt_in(self) -> None:
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 4

        # Anton and Berta are already subscribed, unsubscribe them first
        if self.is_user(1, 2):
            self._change_sub(self.user['id'], mailinglist_id,
                             SA.unsubscribe,
                             state=SS.unsubscribed)

        # Try to subscribe
        expected_state = SS.unsubscribed if self.is_user(1, 2) else SS.none
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=expected_state, kind="error")

        # Test cancelling a subscription request
        self._change_sub(self.user['id'], mailinglist_id, SA.request_subscription,
                         state=SS.pending)
        self._change_sub(self.user['id'], mailinglist_id, SA.cancel_request,
                         state=SS.none)
        self._change_sub(self.user['id'], mailinglist_id, SA.deny_request,
                         state=SS.none, kind='error')

        # Test different resolutions
        self._change_sub(self.user['id'], mailinglist_id, SA.request_subscription,
                         state=SS.pending)
        self._change_sub(self.user['id'], mailinglist_id, SA.deny_request,
                         state=SS.none)

        self._change_sub(self.user['id'], mailinglist_id, SA.request_subscription,
                         state=SS.pending)
        self._change_sub(self.user['id'], mailinglist_id, SA.approve_request,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)

        # Make sure it is impossible to subscribe if blocked
        self._change_sub(self.user['id'], mailinglist_id, SA.request_subscription,
                         state=SS.pending)
        self._change_sub(self.user['id'], mailinglist_id, SA.block_request,
                         state=SS.unsubscription_override)
        self._change_sub(self.user['id'], mailinglist_id,
                         SA.request_subscription,
                         state=SS.unsubscription_override, kind="error")

        self._change_sub(self.user['id'], mailinglist_id,
                         SA.remove_unsubscription_override,
                         state=SS.unsubscribed)

        # Make sure it is impossible to remove a subscription request without
        # actually deciding it
        self._change_sub(self.user['id'], mailinglist_id, SA.request_subscription,
                         state=SS.pending)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.pending, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.pending, kind="error")
        self._change_sub(self.user['id'], mailinglist_id,
                         SA.add_unsubscription_override,
                         state=SS.pending, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.deny_request,
                         state=SS.none)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed)

        # This tests the unsubscription reset.
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.reset,
                         state=SS.none)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.none, kind='info')
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed)

    @as_users("anton", "ferdinand")
    def test_opt_out(self) -> None:
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 2

        # Ferdinand is unsubscribed already, resubscribe
        if self.is_user(6):
            self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                             state=SS.subscribed)

        # Now we have a mix of explicit and implicit subscriptions, try to
        # subscribe again
        expected_state = SS.subscribed if self.is_user(6, 14) else SS.implicit
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=expected_state, kind="info")

        # Now everyone unsubscribes (twice)
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed, kind="info")

        # Test administrative subscriptions
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.subscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed, kind="info")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.unsubscribed)

        # Test blocks
        self._change_sub(self.user['id'], mailinglist_id, SA.add_unsubscription_override,
                         state=SS.unsubscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.unsubscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.unsubscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_unsubscription_override,
                         state=SS.unsubscribed)

        # Test forced subscriptions
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.subscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.unsubscribed)

    @as_users("anton")
    def test_opt_out_unsubscriptions(self) -> None:
        # the mailinglist is member opt-out. Quintus, Annika and Farin are no member
        # but explict unsubscribed from this list
        mailinglist_id = 2

        for persona_id in {17, 27, 32}:
            self._change_sub(persona_id, mailinglist_id, SA.reset, state=SS.none)
        self.ml.write_subscription_states(self.key, mailinglist_id)
        for persona_id in {17, 27, 32}:
            new_state = self.ml.get_subscription(self.key, persona_id=persona_id,
                                                 mailinglist_id=mailinglist_id)
            self.assertEqual(new_state, SS.none)
            self._change_sub(persona_id, mailinglist_id, SA.add_subscriber,
                             state=SS.none, kind='error')
            self._change_sub(persona_id, mailinglist_id, SA.add_subscription_override,
                             state=SS.subscription_override)
            self._change_sub(persona_id, mailinglist_id,
                             SA.remove_subscription_override, state=SS.subscribed)
        self.ml.write_subscription_states(self.key, mailinglist_id)
        for persona_id in {17, 27, 32}:
            new_state = self.ml.get_subscription(self.key, persona_id=persona_id,
                                                 mailinglist_id=mailinglist_id)
            self.assertEqual(new_state, SS.none)

    @as_users("anton", "berta", "ferdinand")
    def test_mandatory(self) -> None:
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1

        def _try_unsubscribe(expected_state: SS) -> None:
            # Try to unsubscribe
            self._change_sub(self.user['id'], mailinglist_id,
                             SA.unsubscribe,
                             state=expected_state, kind="error")
            # Try to remove subscription
            self._change_sub(self.user['id'], mailinglist_id,
                             SA.remove_subscriber,
                             state=expected_state, kind="error")
            # Try to block user
            self._change_sub(self.user['id'], mailinglist_id,
                             SA.add_unsubscription_override,
                             state=expected_state, kind="error")

        _try_unsubscribe(SS.implicit)

        # Force subscription
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)
        _try_unsubscribe(SS.subscription_override)

        # Remove forced subscription
        self._change_sub(self.user['id'], mailinglist_id,
                         SA.remove_subscription_override,
                         state=SS.subscribed)
        _try_unsubscribe(SS.subscribed)

        # For admins, some shallow cron testing
        if not self.is_user(2):
            self.ml.write_subscription_states(self.key, mailinglist_id)
            self._check_state(self.user['id'], mailinglist_id, SS.subscribed)

    @as_users('nina')
    def test_mandatory_two(self) -> None:
        # this does test only ml_admins and moderators thoroughly, as we need
        # a user managing a list and a user interacting with it normally at
        # the same time.
        mailinglist_id = 1

        # Try to subscribe somehow
        self._change_sub(self.user['id'], mailinglist_id, SA.subscribe,
                         state=SS.none, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscriber,
                         state=SS.none, kind="error")

        # Force subscription
        self._change_sub(self.user['id'], mailinglist_id, SA.add_subscription_override,
                         state=SS.subscription_override)

        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(self.user['id'], mailinglist_id, SS.subscription_override)

        # It is impossible to unsubscribe normally
        self._change_sub(self.user['id'], mailinglist_id, SA.unsubscribe,
                         state=SS.subscription_override, kind="error")
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscriber,
                         state=SS.subscription_override, kind="error")

        # Remove subscription
        self._change_sub(self.user['id'], mailinglist_id, SA.remove_subscription_override,
                         state=SS.subscribed)

        # Cron testing
        self.ml.write_subscription_states(self.key, mailinglist_id)
        self._check_state(self.user['id'], mailinglist_id, SS.none)

    @as_users("anton")
    def test_ml_event(self) -> None:
        ml_id = 9

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            5: SS.unsubscribed,
            7: SS.subscribed,
            9: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.implicit, kind="info")
        self._change_sub(self.user['id'], ml_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], ml_id, SA.unsubscribe,
                         state=SS.unsubscribed, kind="info")
        self._change_sub(self.user['id'], ml_id, SA.request_subscription,
                         state=SS.unsubscribed, kind="error")
        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.subscribed)
        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.subscribed, kind="info")

        self.ml.write_subscription_states(self.key, ml_id)

        expectation = {
            1: SS.subscribed,
            2: SS.implicit,
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

        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.none, kind="error")
        self._change_sub(self.user['id'], ml_id, SA.unsubscribe,
                         state=SS.none, kind="info")
        self._change_sub(self.user['id'], ml_id, SA.request_subscription,
                         state=SS.none, kind="error")

    @as_users("ferdinand")
    def test_ml_event_two(self) -> None:
        ml_id = 9

        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.none, kind="error")
        self._change_sub(self.user['id'], ml_id, SA.add_subscriber,
                         state=SS.none, kind="error")

    @as_users("werner")
    def test_ml_assembly(self) -> None:
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

        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.implicit, kind="info")
        self._change_sub(self.user['id'], ml_id, SA.unsubscribe,
                         state=SS.unsubscribed)
        self._change_sub(self.user['id'], ml_id, SA.unsubscribe,
                         state=SS.unsubscribed, kind="info")
        self._change_sub(self.user['id'], ml_id, SA.request_subscription,
                         state=SS.unsubscribed, kind="error")
        self._change_sub(self.user['id'], ml_id, SA.subscribe,
                         state=SS.subscribed)

        ml_id = 66
        assembly_id = self.ml.get_mailinglist(self.key, ml_id)["assembly_id"]

        expectation = {
            23: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

        admin_key = cast(RequestState, self.login("viktor"))
        self.assembly.set_assembly_presiders(admin_key, assembly_id, set())
        self.ml.write_subscription_states(self.key, ml_id)
        self.assertEqual({}, self.ml.get_subscription_states(self.key, ml_id))
        self.assembly.set_assembly_presiders(admin_key, assembly_id, {1})
        self.ml.write_subscription_states(self.key, ml_id)

        expectation = {
            1: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, ml_id)
        self.assertEqual(result, expectation)

    @as_users("nina")
    def test_bullshit_requests(self) -> None:
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
            mailinglist_id=3, persona_id=3, expected_state=SS.none)

    @as_users("charly", "emilia", "janis")
    def test_no_privileges(self) -> None:

        def _try_everything(ml_id: int, user_id: int) -> None:
            for action in SA.managing_actions():
                with self.assertRaises(PrivilegeError):
                    self.ml.do_subscription_action(
                        self.key, action, mailinglist_id=ml_id,
                        persona_id=user_id)
            with self.assertRaises(PrivilegeError):
                self.ml.do_subscription_action(
                    self.key, SA.approve_request, mailinglist_id=ml_id,
                    persona_id=user_id)
            # You had never the chance to actually change something anyway, trying to
            # change the subscription state of someone else.
            if self.is_user(user_id):
                with self.assertRaises(PrivilegeError):
                    datum = {
                        'mailinglist_id': ml_id,
                        'persona_id': user_id,
                        'subscription_state': SS.unsubscribed,
                    }
                    self.ml._set_subscription(self.key, datum)

        # Make sure moderator functions do not tell you anything.
        # Garcia (7) is listed implicitly, explicitly or not at all on these
        for ml_id in {1, 4, 5, 6, 8, 9}:
            _try_everything(ml_id, USER_DICT['garcia']['id'])

        # Users have very diverse states on list 5.
        for subscriber in USER_DICT.values():
            _try_everything(5, subscriber['id'])

    @as_users("janis", "kalif")
    def test_audience(self) -> None:
        # List 4 is moderated opt-in for members only.
        self._change_sub(self.user['id'], 4, SA.subscribe,
                         state=SS.none, kind="error")
        self._change_sub(self.user['id'], 4, SA.request_subscription,
                         state=SS.none, kind="error")
        self._change_sub(self.user['id'], 4, SA.cancel_request,
                         state=SS.none, kind="error")
        # List 7 is not joinable by non-members
        self._change_sub(self.user['id'], 7, SA.subscribe,
                         state=SS.none, kind="error")
        # List 9 is only allowed for event users, and not joinable anyway
        self._change_sub(self.user['id'], 9, SA.subscribe,
                         state=SS.none, kind="error")
        # List 11 is only joinable by assembly users
        if self.is_user(11):
            self._change_sub(self.user['id'], 11, SA.unsubscribe,
                             state=SS.unsubscribed)
            self._change_sub(self.user['id'], 11, SA.subscribe,
                             state=SS.subscribed)
        else:
            self._change_sub(self.user['id'], 11, SA.subscribe,
                             state=SS.none, kind="error")

    @as_users("nina")
    def test_write_subscription_states(self) -> None:
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
        _, log_entries = self.ml.retrieve_log(
            self.key, mailinglist_ids=[mailinglist_id])
        expected_log = {
            'id': 1001,
            'change_note': None,
            'code': const.MlLogCodes.automatically_removed,
            'ctime': nearly_now(),
            'mailinglist_id': mailinglist_id,
            'persona_id': 5,
            'submitted_by': self.user['id']
        }
        self.assertIn(expected_log, log_entries)

        # Now test lists with implicit subscribers.
        # First for events.
        mailinglist_id = 9

        # Initially sample-data.
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
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
            2: SS.implicit,
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

        removes = [3, 9, 14]
        data = [
            {
                'mailinglist_id': mailinglist_id,
                'persona_id': persona_id,
                'subscription_state': const.SubscriptionState.none,
            }
            for persona_id in removes
        ]
        self.ml._set_subscriptions(self.key, data)
        self.ml.write_subscription_states(self.key, mailinglist_id)

        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            9: SS.implicit,
            11: SS.implicit,
            23: SS.implicit,
            100: SS.subscription_override,
        }
        result = self.ml.get_subscription_states(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("nina")
    def test_change_sub_policy(self) -> None:
        mdata = {
            'local_part': 'revolution',
            'domain': const.MailinglistDomain.lists,
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': {2},
            'registration_stati': [],
            'subject_prefix': 'viva la revolution',
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
            15: SS.implicit,
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
            15: SS.implicit,
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
            15: SS.implicit,
            100: SS.implicit,
        }
        result = self.ml.get_subscription_states(self.key, new_id)
        self.assertEqual(expectation, result)

    @as_users("nina")
    def test_change_mailinglist_association(self) -> None:
        mdata = {
            'local_part': 'orga',
            'domain': const.MailinglistDomain.aka,
            'description': None,
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'event_id': 2,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': {2},
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

    @as_users("nina", "janis")
    def test_subscription_addresses(self) -> None:
        expectation = {
            1: 'anton@example.cde',
            2: 'berta@example.cde',
            3: 'charly@example.cde',
            7: 'garcia@example.cde',
            9: 'inga@example.cde',
            15: 'olaf@example.cde',
            100: 'akira@example.cde',
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

    @as_users("nina", "berta")
    def test_subscription_addresses_two(self) -> None:
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       3: 'charly@example.cde',
                       11: 'kalif@example.cde',
                       14: 'nina@example.cde',
                       23: 'werner@example.cde',
                       100: 'akira@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 5))

    @as_users("nina", "garcia")
    def test_subscription_addresses_three(self) -> None:
        expectation = {7: 'garcia@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 8))
        expectation = {1: 'anton@example.cde',
                       2: 'berta@example.cde',
                       7: 'garcia@example.cde',
                       9: 'inga@example.cde',
                       100: 'akira@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 9))
        expectation = {5: 'emilia@example.cde'}
        self.assertEqual(expectation,
                         self.ml.get_subscription_addresses(self.key, 10))

    @as_users("janis")
    def test_set_subscription_address(self) -> None:
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
            'persona_id': self.user['id'],
            'email': "new-janis@example.cde",
        }
        expectation.update({datum['persona_id']: datum['email']})
        self.ml.set_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': self.user['id'],
            'email': "janis-ist-toll@example.cde",
        }
        expectation.update({datum['persona_id']: datum['email']})
        self.ml.set_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

        # Remove an address.
        datum = {
            'mailinglist_id': mailinglist_id,
            'persona_id': self.user['id'],
        }
        expectation.update({self.user['id']: self.user['username']})
        self.ml.remove_subscription_address(self.key, **datum)

        result = self.ml.get_subscription_addresses(self.key, mailinglist_id)
        self.assertEqual(result, expectation)

    @as_users("janis")
    def test_remove_subscription_address(self) -> None:
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
    def test_moderation(self) -> None:
        expectation = {
            1: SS.implicit,
            2: SS.implicit,
            5: SS.unsubscription_override,
            9: SS.implicit,
            11: SS.unsubscription_override,
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
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
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
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
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
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
            11: SS.unsubscription_override,
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
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
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
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
            12: SS.implicit,
            13: SS.implicit,
            51: SS.implicit,
            52: SS.implicit,
            53: SS.subscribed,
            56: SS.subscribed,
            61: SS.implicit,
            63: SS.subscribed,
            64: SS.subscribed,
        }
        self.assertEqual(expectation,
                         self.ml.get_user_subscriptions(self.key, persona_id=9))

    @as_users("inga")
    def test_request_cancellation(self) -> None:
        expectation = SS.none
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
        expectation = SS.none
        self.assertEqual(expectation,
                         self.ml.get_subscription(
                             self.key, persona_id=9, mailinglist_id=4))

    @as_users("annika", "viktor", "quintus", "nina")
    def test_relevant_admins(self) -> None:
        if self.is_user("annika", "nina"):
            # Create a new event mailinglist.
            mldata = {
                'local_part': "cyber",
                'domain': const.MailinglistDomain.aka,
                'description': "Für alle, die nicht ohne Akademien können.",
                'event_id': None,
                'ml_type': const.MailinglistTypes.event_associated,
                'is_active': True,
                'attachment_policy': const.AttachmentPolicy.forbid,
                'maxsize': None,
                'moderators': {self.user['id']},
                'subject_prefix': "cyber",
                'title': "CyberAka",
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'notes': None,
                'registration_stati': [],
            }
            new_id = self.ml.create_mailinglist(self.key, mldata)
            self.assertGreater(new_id, 0)

            # Add self as a subscriber.
            self.ml.do_subscription_action(
                self.key, SA.add_subscriber, new_id, self.user['id'])

            # Modify the new mailinglist.
            mdata = {
                'id': new_id,
                'registration_stati': [
                    const.RegistrationPartStati.guest,
                    const.RegistrationPartStati.participant,
                    const.RegistrationPartStati.applied,
                    const.RegistrationPartStati.waitlist,
                ],
                'event_id': 1,
                'ml_type': const.MailinglistTypes.event_associated,
            }
            self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Attempt to change the mailinglist type.
            mdata = {
                'id': new_id,
                'ml_type': const.MailinglistTypes.member_opt_in,
            }
            if self.user['display_name'] != "Nina":
                with self.assertRaises(PrivilegeError) as cm:
                    self.ml.set_mailinglist(self.key, mdata)
                self.assertEqual(cm.exception.args,
                                 ("Not privileged to make this change.",))
            else:
                self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Delete the mailinglist.
            self.assertTrue(self.ml.delete_mailinglist(
                self.key, new_id,
                cascade=["moderators", "subscriptions", "log"]))

        if self.is_user("viktor", "nina"):
            # Create a new assembly mailinglist.
            mldata = {
                'local_part': "mgv-ag",
                'domain': const.MailinglistDomain.lists,
                'description': "Vor der nächsten MGV müssen wir noch ein paar"
                               " Dinge klären.",
                'ml_type': const.MailinglistTypes.assembly_opt_in,
                'is_active': True,
                'attachment_policy': const.AttachmentPolicy.forbid,
                'maxsize': None,
                'moderators': {self.user['id']},
                'subject_prefix': "mgv-ag",
                'title': "Arbeitsgruppe Mitgliederversammlung",
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'notes': None,
            }
            new_id = self.ml.create_mailinglist(self.key, mldata)
            self.assertGreater(new_id, 0)

            # Add self as a subscriber.
            self.ml.do_subscription_action(
                self.key, SA.add_subscription_override, new_id, self.user['id'])

            # Modify the new mailinglist.
            mdata = {
                'id': new_id,
                'assembly_id': 2,
                'ml_type': const.MailinglistTypes.assembly_associated,
            }
            self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Attempt to change the mailinglist type.
            mdata = {
                'id': new_id,
                'ml_type': const.MailinglistTypes.member_opt_in,
            }
            if self.is_user("nina"):
                with self.assertRaises(PrivilegeError) as cm:
                    self.ml.set_mailinglist(self.key, mdata)
                self.assertEqual(cm.exception.args,
                                 ("Not privileged to make this change.",))
            else:
                self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Delete the mailinglist.
            self.assertTrue(self.ml.delete_mailinglist(
                self.key, new_id,
                cascade=["moderators", "subscriptions", "log"]))
        if self.is_user("quintus", "nina"):
            # Create a new member mailinglist.
            mldata = {
                'local_part': "literatir",
                'domain': const.MailinglistDomain.lists,
                'description': "Wir reden hier über coole Bücher die wir"
                               " gelesen haben.",
                'ml_type': const.MailinglistTypes.member_opt_in,
                'is_active': True,
                'attachment_policy': const.AttachmentPolicy.forbid,
                'maxsize': None,
                'moderators': {self.user['id']},
                'subject_prefix': "literatur",
                'title': "Buchclub",
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'notes': None,
            }
            new_id = self.ml.create_mailinglist(self.key, mldata)
            self.assertGreater(new_id, 0)

            # Add self as a subscriber.
            self.ml.do_subscription_action(
                self.key, SA.add_subscription_override, new_id, self.user['id'])

            # Modify the new mailinglist.
            mdata = {
                'id': new_id,
                'ml_type': const.MailinglistTypes.member_opt_out,
            }
            self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Attempt to change the mailinglist type.
            mdata = {
                'id': new_id,
                'ml_type': const.MailinglistTypes.general_opt_in,
            }
            if not self.is_user("nina"):
                with self.assertRaises(PrivilegeError) as cm:
                    self.ml.set_mailinglist(self.key, mdata)
                self.assertEqual(cm.exception.args,
                                 ("Not privileged to make this change.",))
            else:
                self.assertTrue(self.ml.set_mailinglist(self.key, mdata))

            # Delete the mailinglist.
            self.assertTrue(self.ml.delete_mailinglist(
                self.key, new_id,
                cascade=["moderators", "subscriptions", "log"]))

    @as_users("anton")
    def test_log(self) -> None:
        # first generate some data
        self.ml.do_subscription_action(self.key, SA.unsubscribe, 2, 1)
        datum: CdEDBObject = {
            'mailinglist_id': 4,
            'persona_id': 1,
            'email': 'devnull@example.cde',
        }
        self.ml.set_subscription_address(self.key, **datum)
        self.ml.do_subscription_action(self.key, SA.add_subscriber, 7, 1)
        new_data = {
            'local_part': 'revolution',
            'domain': const.MailinglistDomain.lists,
            'description': 'Vereinigt Euch',
            'assembly_id': None,
            'attachment_policy': const.AttachmentPolicy.forbid,
            'event_id': None,
            'is_active': True,
            'maxsize': None,
            'mod_policy': const.ModerationPolicy.unmoderated,
            'moderators': {1, 2},
            'registration_stati': [],
            'subject_prefix': 'viva la revolution',
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
        expectation = (8, (
            {'id': 1001,
             'change_note': None,
             'code': const.MlLogCodes.unsubscribed,
             'ctime': nearly_now(),
             'mailinglist_id': 2,
             'persona_id': 1,
             'submitted_by': self.user['id']},
            {'id': 1002,
             'change_note': 'devnull@example.cde',
             'code': const.MlLogCodes.subscription_changed,
             'ctime': nearly_now(),
             'mailinglist_id': 4,
             'persona_id': 1,
             'submitted_by': self.user['id']},
            {'id': 1003,
             'change_note': None,
             'code': const.MlLogCodes.subscribed,
             'ctime': nearly_now(),
             'mailinglist_id': 7,
             'persona_id': 1,
             'submitted_by': self.user['id']},
            {'id': 1004,
             'change_note': None,
             'code': const.MlLogCodes.list_created,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1005,
             'change_note': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': 1,
             'submitted_by': self.user['id']},
            {'id': 1006,
             'change_note': None,
             'code': const.MlLogCodes.moderator_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': 2,
             'submitted_by': self.user['id']},
            {'id': 1007,
             'change_note': 'che@example.cde',
             'code': const.MlLogCodes.whitelist_added,
             'ctime': nearly_now(),
             'mailinglist_id': new_id,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1008,
             'change_note': 'Witz des Tages (witz@lists.cde-ev.de)',
             'code': const.MlLogCodes.list_deleted,
             'ctime': nearly_now(),
             'mailinglist_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']}
        ))
        self.assertEqual(expectation, self.ml.retrieve_log(self.key))
        self.assertEqual(
            (expectation[0], expectation[1][2:5]),
            self.ml.retrieve_log(self.key, offset=2, length=3))
        self.assertEqual(
            (4, expectation[1][3:7]),
            self.ml.retrieve_log(self.key, mailinglist_ids=[new_id]))
        self.assertEqual(
            (2, expectation[1][4:6]),
            self.ml.retrieve_log(
                self.key, codes=(const.MlLogCodes.moderator_added,)))
