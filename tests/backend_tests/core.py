#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import copy
import datetime
import decimal
from typing import List, Optional, cast

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import (
    CdEDBObject, GenesisDecision, RequestState, get_hash, merge_dicts, nearly_now, now,
)
from cdedb.common.exceptions import ArchiveError, PrivilegeError
from cdedb.common.fields import (
    PERSONA_CDE_FIELDS, PERSONA_EVENT_FIELDS, PERSONA_ML_FIELDS,
)
from cdedb.common.query.log_filter import ChangelogLogFilter, CoreLogFilter
from cdedb.common.validation.validate import PERSONA_CDE_CREATION
from tests.common import (
    ANONYMOUS, USER_DICT, BackendTest, as_users, create_mock_image, prepsql, storage,
)

PERSONA_TEMPLATE = {
    'username': "zelda@example.cde",
    'notes': "Not Link.",
    'is_cde_realm': False,
    'is_event_realm': False,
    'is_ml_realm': False,
    'is_assembly_realm': False,
    'is_member': False,
    'is_searchable': False,
    'is_active': True,
    'display_name': "Zelda",
    'family_name': "Zeruda-Hime",
    'given_names': "Zelda",
    'title': None,
    'name_supplement': None,
    'gender': None,
    'pronouns': None,
    'pronouns_nametag': False,
    'pronouns_profile': False,
    'birthday': None,
    'telephone': None,
    'mobile': None,
    'address_supplement': None,
    'address': None,
    'postal_code': None,
    'location': None,
    'country': None,
    'birth_name': None,
    'address_supplement2': None,
    'address2': None,
    'postal_code2': None,
    'location2': None,
    'country2': None,
    'weblink': None,
    'specialisation': None,
    'affiliation': None,
    'timeline': None,
    'interests': None,
    'free_form': None,
    'trial_member': None,
    'honorary_member': None,
    'decided_search': None,
    'bub_search': None,
    'foto': None,
    'paper_expuls': None,
    'donation': None,
}
# This can be used whenever an ip needs to be specified.
IP = "127.0.0.0"


class TestCoreBackend(BackendTest):
    used_backends = ("core",)

    def test_login(self) -> None:
        for i, u in enumerate(("anton", "berta", "janis")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                key = self.core.login(ANONYMOUS, user['username'], user['password'], IP)
                self.assertIsInstance(key, str)
                self.assertTrue(key)

                key = self.core.login(ANONYMOUS, user['username'], "wrong key", IP)
                self.assertIsNone(key)

    @as_users("anton", "berta", "janis")
    def test_logout(self) -> None:
        self.assertTrue(self.key)
        self.assertEqual(1, self.core.logout(self.key))
        with self.assertRaises(RuntimeError):
            self.core.logout(self.key)

    @as_users("anton")
    def test_entity_persona(self) -> None:
        persona_id: Optional[int] = -1
        while True:
            persona_id = self.core.next_persona(
                self.key, persona_id=persona_id, is_member=None, is_archived=False)

            if not persona_id:
                break

            # Validate ml data
            persona = self.core.get_ml_user(self.key, persona_id)
            affirm(vtypes.Persona, persona)

            # Validate event data if applicable
            if not persona['is_event_realm']:
                continue

            persona = self.core.get_event_user(self.key, persona_id)
            if persona_id != USER_DICT["inga"]["id"]:
                affirm(vtypes.Persona, persona)
            else:
                with self.assertRaises(ValueError) as cm:
                    affirm(vtypes.Persona, persona)
                self.assertIn(
                    "A birthday must be in the past. (birthday)", cm.exception.args)

            # Validate cde/total data if applicable
            if not persona['is_cde_realm']:
                continue

            persona = self.core.get_total_persona(self.key, persona_id)
            if persona_id != USER_DICT["inga"]["id"]:
                affirm(vtypes.Persona, persona)
            else:
                with self.assertRaises(ValueError) as cm:
                    affirm(vtypes.Persona, persona)
                self.assertIn(
                    "A birthday must be in the past. (birthday)", cm.exception.args)

    @as_users("anton", "berta", "janis")
    def test_set_persona(self) -> None:
        new_name = "Zelda"
        self.core.set_persona(self.key, {'id': self.user['id'],
                                         'display_name': new_name})
        self.assertEqual(new_name, self.core.retrieve_persona(
            self.key, self.user['id'])['display_name'])

    @as_users("anton", "berta", "janis")
    def test_change_password(self) -> None:
        user = self.user
        ret, _ = self.core.change_password(self.key, self.user['password'], "weakpass")
        self.assertFalse(ret)
        newpass = "er3NQ_5bkrc#"
        ret, message = self.core.change_password(self.key, self.user['password'],
                                                 newpass)
        self.assertTrue(ret)
        self.assertEqual(newpass, message)
        self.core.logout(self.key)
        self.login(self.user)
        self.assertIsNone(self.key)
        newuser = dict(user)
        newuser['password'] = newpass
        self.login(newuser)
        self.assertTrue(self.key)

    @storage
    # Martin may do this in the backend, but not manually via the frontend.
    @as_users("anton", "martin", "vera")
    def test_invalidate_session(self) -> None:
        # Login with another user.
        other_user = copy.deepcopy(USER_DICT["berta"])
        new_foto = create_mock_image()
        other_key = cast(RequestState, self.core.login(
            ANONYMOUS, other_user["username"], other_user["password"], IP))
        self.assertIsNotNone(other_key)
        self.assertLess(
            0, self.core.change_foto(other_key, other_user["id"], new_foto))

        # Invalidate the other users password and session.
        self.assertLess(
            0, self.core.invalidate_password(self.key, other_user["id"]))

        with self.assertRaises(PrivilegeError):
            self.core.change_foto(other_key, other_user["id"], new_foto)
        self.assertIsNone(self.login(other_user))

    @as_users("anton", "berta", "janis")
    def test_change_username(self) -> None:
        user = self.user
        newaddress = "newaddress@example.cde"
        ret, _ = self.core.change_username(
            self.key, self.user['id'], newaddress, self.user['password'])
        self.assertTrue(ret)
        self.core.logout(self.key)
        self.login(self.user)
        self.assertIsNone(self.key)
        newuser = dict(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.key)

    @as_users("vera")
    def test_admin_change_username(self) -> None:
        persona_id = 2
        newaddress = "newaddress@example.cde"
        ret, _ = self.core.change_username(
            self.key, persona_id, newaddress, password=None)
        self.assertTrue(ret)
        expected_log = {
            'id': 1001,
            'ctime': nearly_now(),
            'persona_id': persona_id,
            'code': const.CoreLogCodes.username_change,
            'submitted_by': self.user['id'],
            'change_note': newaddress,
        }
        _, log_entry = self.core.retrieve_log(self.key, CoreLogFilter())
        self.assertIn(expected_log, log_entry)

    @storage
    @as_users("vera", "berta")
    def test_set_foto(self) -> None:
        new_foto = create_mock_image('png')
        persona_id = 2
        self.assertLess(0, self.core.change_foto(self.key, persona_id, new_foto))
        cde_user = self.core.get_cde_user(self.key, persona_id)
        self.assertEqual(get_hash(new_foto), cde_user['foto'])
        self.assertEqual(new_foto, self.core.get_foto(self.key, cde_user['foto']))
        self.assertGreater(0, self.core.change_foto(self.key, persona_id, None))
        self.assertIsNone(self.core.get_cde_user(self.key, persona_id)['foto'])

    def test_verify_existence(self) -> None:
        self.assertTrue(self.core.verify_existence(self.key, "anton@example.cde"))
        self.assertFalse(
            self.core.verify_existence(self.key, "nonexistent@example.cde"))
        self.login(USER_DICT["berta"])
        self.assertTrue(self.core.verify_ids(self.key, {1, 2, 5, 100}))
        self.assertFalse(self.core.verify_ids(self.key, {123456}))
        # Hades is archived.
        self.assertTrue(self.core.verify_ids(self.key, {8}, is_archived=True))
        self.assertFalse(self.core.verify_ids(self.key, {8}, is_archived=False))
        self.assertTrue(self.core.verify_ids(self.key, {8}, is_archived=None))
        self.assertTrue(self.core.verify_ids(self.key, {1, 8}, is_archived=None))
        self.assertTrue(self.core.verify_ids(self.key, {8}, is_archived=True))
        self.assertFalse(self.core.verify_ids(self.key, {1, 8}, is_archived=True))

    def test_password_reset(self) -> None:
        new_pass = "rK;7e$ekgReW2t"
        ret, cookie = self.core.make_reset_cookie(self.key, "berta@example.cde")
        self.assertTrue(ret)
        ret, effective = self.core.reset_password(
            self.key, "berta@example.cde", new_pass, cookie)
        self.assertTrue(ret)
        self.assertEqual(new_pass, effective)
        with self.assertRaises(PrivilegeError):
            self.core.make_reset_cookie(self.key, "anton@example.cde")
        ret, _ = self.core.make_reset_cookie(self.key, "nonexistent@example.cde")
        self.assertFalse(ret)

    @as_users("vera")
    def test_create_persona(self) -> None:
        data = copy.deepcopy(PERSONA_TEMPLATE)
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
        })
        self.assertEqual(data, new_data)
        expectation = {
            1: {
                **data,
                'automated_change': False,
                'change_note': 'Account erstellt.',
                'code': 2,
                'ctime': nearly_now(),
                'generation': 1,
                'id': new_id,
                'reviewed_by': None,
                'submitted_by': self.user['id'],
            }}
        history = self.core.changelog_get_history(self.key, new_id, None)
        self.assertEqual(expectation, history)

    @as_users("vera")
    def test_create_member(self) -> None:
        data = copy.deepcopy(PERSONA_TEMPLATE)
        data.update({
            'is_ml_realm': True,
            'is_event_realm': True,
            'is_assembly_realm': True,
            'is_cde_realm': True,
            'is_member': True,
            'title': "Dr.",
            'name_supplement': None,
            'gender': const.Genders.female,
            'birthday': datetime.date(1987, 6, 5),
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': "An der Eiche",
            'postal_code': "12345",
            'location': "Marcuria",
            'country': "AQ",
            'birth_name': None,
            'address_supplement2': None,
            'address2': None,
            'postal_code2': None,
            'location2': None,
            'country2': None,
            'weblink': None,
            'specialisation': "Being rescued",
            'affiliation': "Link",
            'timeline': None,
            'interests': "Ocarinas",
            'free_form': None,
            'trial_member': True,
            'honorary_member': False,
            'decided_search': False,
            'bub_search': False,
            'foto': None,
            'paper_expuls': True,
            'donation': decimal.Decimal(0)
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': decimal.Decimal('0.00'),
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
        })
        self.assertEqual(data, new_data)

    @as_users("annika", "vera")
    def test_create_event_user(self) -> None:
        data = copy.deepcopy(PERSONA_TEMPLATE)
        data.update({
            'is_ml_realm': True,
            'is_event_realm': True,
            'title': "Dr.",
            'name_supplement': None,
            'gender': const.Genders.female,
            'birthday': datetime.date(1987, 6, 5),
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': "An der Eiche",
            'postal_code': "12345",
            'location': "Marcuria",
            'country': "AQ",
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
        })
        self.assertEqual(data, new_data)

    @as_users("vera", "viktor")
    def test_create_assembly_user(self) -> None:
        data = copy.deepcopy(PERSONA_TEMPLATE)
        data['is_ml_realm'] = True
        data['is_assembly_realm'] = True
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
        })
        self.assertEqual(data, new_data)

    @as_users("vera")
    def test_create_mixed_user(self) -> None:
        data = copy.deepcopy(PERSONA_TEMPLATE)
        data.update({
            'is_ml_realm': True,
            'is_assembly_realm': True,
            'is_event_realm': True,
            'title': "Dr.",
            'name_supplement': None,
            'gender': const.Genders.female,
            'birthday': datetime.date(1987, 6, 5),
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': "An der Eiche",
            'postal_code': "12345",
            'location': "Marcuria",
            'country': "AQ",
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
        })
        self.assertEqual(data, new_data)

    @as_users("vera")
    def test_change_realm(self) -> None:
        persona_id = 5
        data = {
            'id': 5,
            'is_cde_realm': True,
            'is_assembly_realm': True,
        }
        persona = self.core.get_total_persona(self.key, persona_id)
        reference = {**PERSONA_CDE_CREATION}
        for key in tuple(persona):
            if key not in reference and key != 'id':
                del persona[key]
            persona.update({
                'trial_member': False,
                'honorary_member': False,
                'decided_search': False,
                'bub_search': False,
                'paper_expuls': True,
                'donation': decimal.Decimal(0),
            })
        merge_dicts(data, persona)
        change_note = "Bereichsänderung"
        self.assertLess(0, self.core.change_persona_realms(self.key, data, change_note))
        log_entry = {
            'id': 1001,
            'ctime': nearly_now(),
            'code': const.CoreLogCodes.realm_change,
            'persona_id': persona_id,
            'submitted_by': self.user['id'],
            'change_note': change_note,
        }
        _, expected_log = self.core.retrieve_log(self.key, CoreLogFilter())
        self.assertIn(log_entry, expected_log)

    @as_users("vera")
    def test_change_persona_membership(self) -> None:
        # Test persona without cde realm
        with self.assertRaises(RuntimeError) as cm:
            self.core.change_membership_easy_mode(
                self.key, persona_id=5, is_member=False, trial_member=False)
        self.assertEqual(str(cm.exception), "Not a CdE account.")

        # Test membership changing is forbidden if user has an active lastschrift
        with self.assertRaises(RuntimeError) as cm:
            self.core.change_membership_easy_mode(
                self.key, persona_id=2, is_member=False, trial_member=False)
        self.assertEqual(str(cm.exception), "Active lastschrift permit found.")

        def persona_membership(rs: RequestState, persona_id: int) -> CdEDBObject:
            return self.core.retrieve_persona(
                rs, persona_id, ("is_member", "trial_member"))

        def log_entry(code: const.FinanceLogCodes, members: int) -> CdEDBObject:
            if members == 8:
                member_total = "113.76"
            elif members == 9:
                member_total = "114.76"
            else:
                self.fail("Test needs adjustment.")
            data = {'persona_id': persona_id, 'code': code, 'total': "725.87",
                    'delta': None, 'new_balance': None, 'transaction_date': None,
                    'members': members, 'member_total': member_total}
            if code == const.FinanceLogCodes.lose_membership:
                data["delta"] = None
                data["new_balance"] = None
                data["member_total"] = "113.76"
            return data

        persona_id = 3
        expectation = {"id": persona_id, "is_member": True, "trial_member": True}
        self.assertEqual(expectation, persona_membership(self.key, persona_id))
        logs = []

        # Test revoking membership without trial membership
        with self.assertRaises(ValueError) as ccm:
            self.core.change_membership_easy_mode(
                self.key, persona_id=persona_id, is_member=False)
        self.assertEqual(str(ccm.exception), "Trial membership requires membership.")

        # Test revoking trial membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, trial_member=False), 0)
        expectation["trial_member"] = False
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.end_trial_membership, 9))

        # Test revoking membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, is_member=False), 0)
        expectation["is_member"] = False
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.lose_membership, 8))

        # Test granting trial membership
        with self.assertRaises(ValueError) as ccm:
            self.core.change_membership_easy_mode(
                self.key, persona_id=persona_id, trial_member=True)
        self.assertEqual(str(ccm.exception), "Trial membership requires membership.")

        # Test granting membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, is_member=True), 0)
        expectation["is_member"] = True
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.gain_membership, 9))

        # Test granting trial membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, trial_member=True), 0)
        expectation["trial_member"] = True
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.start_trial_membership, 9))

        # Test revoking membership and trial membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, is_member=False, trial_member=False), 0)
        expectation["is_member"] = expectation["trial_member"] = False
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.lose_membership, 8))
        logs.append(log_entry(const.FinanceLogCodes.end_trial_membership, 8))

        # Test granting trial membership and membership
        self.assertGreater(self.core.change_membership_easy_mode(
            self.key, persona_id, is_member=True, trial_member=True), 0)
        expectation["is_member"] = expectation["trial_member"] = True
        self.assertDictEqual(expectation, persona_membership(self.key, persona_id))
        logs.append(log_entry(const.FinanceLogCodes.gain_membership, 9))
        logs.append(log_entry(const.FinanceLogCodes.start_trial_membership, 9))

        self.assertLogEqual(logs, realm="finance", offset=3)

    @as_users("vera")
    def test_change_persona_balance(self) -> None:
        log_code = const.FinanceLogCodes.manual_balance_correction
        # Test non-members
        with self.assertRaises(RuntimeError) as cm:
            self.core.change_persona_balance(self.key, 5, '23.45', log_code)
        self.assertEqual(str(cm.exception),
                         "Tried to credit balance to non-cde person.")

        def persona_finances(rs: RequestState, persona_id: int) -> CdEDBObject:
            return self.core.retrieve_persona(
                rs, persona_id, ("balance", "trial_member"))

        persona_id = 2
        persona = persona_finances(self.key, persona_id)
        # Test no changes
        self.assertFalse(self.core.change_persona_balance(
            self.key, persona_id, persona['balance'], log_code))
        # Test change balance
        self.assertGreater(self.core.change_persona_balance(
            self.key, persona_id, '23.45', log_code), 0)
        persona['balance'] = decimal.Decimal('23.45')
        self.assertDictEqual(persona_finances(self.key, persona_id), persona)

    @as_users("vera")
    def test_meta_info(self) -> None:
        expectation = self.get_sample_datum('core.meta_info', 1)['info']
        self.assertEqual(expectation, self.core.get_meta_info(self.key))
        update = {
            'Finanzvorstand_Name': 'Zelda'
        }
        self.assertLess(0, self.core.set_meta_info(self.key, update))
        expectation.update(update)
        self.assertEqual(expectation, self.core.get_meta_info(self.key))

    @as_users("vera")
    def test_genesis_deletion(self) -> None:
        case_data = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zelda@example.cde',
            "realm": "ml",
            "notes": "Some blah",
        }
        # Create the request anonymously.
        case_id = self.core.genesis_request(ANONYMOUS, case_data)
        assert case_id is not None
        self.assertLess(0, case_id)

        # Deletion is blocked, because link has not timed out yet.
        blockers = self.core.delete_genesis_case_blockers(self.key, case_id)
        self.assertIn("unconfirmed", blockers)

        # "unconfirmed" blocker cannot be cascaded.
        with self.assertRaises(ValueError):
            self.core.delete_genesis_case(self.key, case_id, cascade=blockers)

        # Verify the request anonymously.
        self.core.genesis_verify(ANONYMOUS, case_id)

        # Deletion is blocked, because it is being reviewed.
        blockers = self.core.delete_genesis_case_blockers(self.key, case_id)
        self.assertIn("case_status", blockers)

        # Reject the case.
        modify_data = {
            'id': case_id,
            'realm': 'ml',
            'reviewer': self.user['id'],
            'case_status': const.GenesisStati.rejected,
        }
        self.core.genesis_modify_case(self.key, modify_data)

        # Should be deletable now.
        blockers = self.core.delete_genesis_case_blockers(self.key, case_id)
        self.assertEqual({}, blockers)
        self.assertLess(0, self.core.delete_genesis_case(self.key, case_id))

        genesis_deleted = const.CoreLogCodes.genesis_deleted
        log_entry_expectation = {
            'id': 1004,
            'change_note': case_data['username'],
            'code': genesis_deleted,
            'ctime': nearly_now(),
            'persona_id': None,
            'submitted_by': self.user['id'],
        }
        _, log_entries = self.core.retrieve_log(
            self.key, CoreLogFilter(codes=[genesis_deleted]))
        self.assertIn(log_entry_expectation, log_entries)

    @as_users("annika", "vera")
    def test_genesis_event(self) -> None:
        data = {
            'family_name': "Zeruda-Hime",
            'given_names': "Zelda",
            'username': 'zelda@example.cde',
            'realm': "event",
            'notes': "Some blah",
            'gender': const.Genders.female,
            'birthday': datetime.date(1987, 6, 5),
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': "An der Eiche",
            'postal_code': "12345",
            'location': "Marcuria",
            'country': "AQ",
        }
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, realms=["event"], stati=(const.GenesisStati.to_review,))))
        case_id = self.core.genesis_request(ANONYMOUS, data)
        assert case_id is not None
        self.assertGreater(case_id, 0)
        self.assertEqual((1, 'event'), self.core.genesis_verify(ANONYMOUS, case_id))
        self.assertEqual(2, len(self.core.genesis_list_cases(
            self.key, realms=["event"], stati=(const.GenesisStati.to_review,))))
        expectation = data
        expectation.update({
            'id': case_id,
            'case_status': const.GenesisStati.to_review,
            'reviewer': None,
            'attachment_hash': None,
            'birth_name': None,
            'persona_id': None,
            'pevent_id': None,
            'pcourse_id': None,
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)

        # Just update the genesis request
        update = {
            'id': case_id,
            'realm': "event",
            'address': "An dem Elche",
        }
        self.assertEqual(1, self.core.genesis_modify_case(self.key, update))
        expectation.update(update)
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        if self.user_in("vera"):
            log_entry_expectation = {
                'change_note': expectation['username'],
                'code': const.CoreLogCodes.genesis_change,
                'persona_id': None,
                'submitted_by': self.user['id'],
            }
            self.assertLogEqual([log_entry_expectation], realm='core', offset=2)

        update = {
            'id': case_id,
            'realm': "event",
            'case_status': const.GenesisStati.approved,
            'reviewer': 1,
        }
        self.assertEqual(1, self.core.genesis_modify_case(self.key, update))
        expectation.update(update)
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        new_id = self.core.genesis(self.key, case_id)
        self.assertLess(0, new_id)
        value = self.core.get_event_user(self.key, new_id)
        expectation = {k: v for k, v in expectation.items()
                       if k in PERSONA_EVENT_FIELDS}
        expectation.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
            'id': new_id,
            'display_name': 'Zelda',
            'is_active': True,
            'is_assembly_realm': False,
            'is_cde_realm': False,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_searchable': False,
            'name_supplement': None,
            'title': None,
            'pronouns': None,
            'pronouns_nametag': False,
            'pronouns_profile': False,
        })
        self.assertEqual(expectation, value)

    @as_users("anton")
    def test_genesis_ml(self) -> None:
        data: CdEDBObject = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zelda@example.cde',
            "realm": "ml",
            "notes": "Some blah",
        }
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, realms=["ml"], stati=(const.GenesisStati.to_review,))))
        case_id = self.core.genesis_request(ANONYMOUS, data)
        assert case_id is not None
        self.assertGreater(case_id, 0)
        self.assertEqual((1, "ml"), self.core.genesis_verify(ANONYMOUS, case_id))
        self.assertEqual(2, len(self.core.genesis_list_cases(
            self.key, realms=["ml"], stati=(const.GenesisStati.to_review,))))
        expectation = data
        expectation.update({
            'id': case_id,
            'case_status': const.GenesisStati.to_review,
            'reviewer': None,
            'address': None,
            'address_supplement': None,
            'birthday': None,
            'country': None,
            'gender': None,
            'location': None,
            'mobile': None,
            'postal_code': None,
            'telephone': None,
            'attachment_hash': None,
            'birth_name': None,
            'persona_id': None,
            'pevent_id': None,
            'pcourse_id': None,
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        update = {
            'id': case_id,
            'realm': "ml",
            'case_status': const.GenesisStati.approved,
            'reviewer': 1,
        }
        self.assertEqual(1, self.core.genesis_modify_case(self.key, update))
        expectation.update(update)
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        new_id = self.core.genesis(self.key, case_id)
        self.assertLess(0, new_id)
        value = self.core.get_ml_user(self.key, new_id)
        expectation = {k: v for k, v in expectation.items() if k in PERSONA_ML_FIELDS}
        expectation.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': False,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
            'id': new_id,
            'display_name': 'Zelda',
            'is_active': True,
            'is_assembly_realm': False,
            'is_cde_realm': False,
            'is_event_realm': False,
            'is_ml_realm': True,
            'is_searchable': False,
            'name_supplement': None,
            'title': None,
        })
        self.assertEqual(expectation, value)

    @as_users("vera")
    def test_genesis_cde(self) -> None:
        attachment_hash = "really_cool_filename"
        data = {
            'family_name': "Zeruda-Hime",
            'given_names': "Zelda",
            'username': 'zelda@example.cde',
            'realm': "cde",
            'notes': "Some blah",
            'gender': const.Genders.female,
            'birthday': datetime.date(1987, 6, 5),
            'telephone': None,
            'mobile': None,
            'address_supplement': None,
            'address': "An der Eiche",
            'postal_code': "12345",
            'location': "Marcuria",
            'country': "AQ",
            'attachment_hash': attachment_hash,
            'persona_id': None,
            'pevent_id': None,
            'pcourse_id': None,
        }
        self.assertFalse(self.core.genesis_attachment_usage(
            self.key, attachment_hash))
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, realms=["cde"], stati=(const.GenesisStati.to_review,))))
        case_id = self.core.genesis_request(ANONYMOUS, data)
        self.assertTrue(self.core.genesis_attachment_usage(
            self.key, attachment_hash))
        assert case_id is not None
        self.assertLess(0, case_id)
        self.assertEqual((1, 'cde'), self.core.genesis_verify(ANONYMOUS, case_id))
        self.assertEqual(2, len(self.core.genesis_list_cases(
            self.key, realms=["cde"], stati=(const.GenesisStati.to_review,))))
        expectation = data
        expectation.update({
            'id': case_id,
            'birth_name': None,
            'case_status': const.GenesisStati.to_review,
            'reviewer': None,
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        update = {
            'id': case_id,
            'case_status': const.GenesisStati.approved,
            'reviewer': self.user['id'],
            'realm': "cde",
        }
        self.assertEqual(1, self.core.genesis_modify_case(self.key, update))
        expectation.update(update)
        new_id = self.core.genesis(self.key, case_id)
        self.assertLess(0, new_id)
        expectation = {k: v for k, v in expectation.items() if k in PERSONA_CDE_FIELDS}
        expectation.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': True,
            'is_ml_admin': False,
            'is_purged': False,
            'is_cdelokal_admin': False,
            'is_auditor': False,
            'id': new_id,
            'display_name': 'Zelda',
            'is_active': True,
            'is_assembly_realm': True,
            'is_cde_realm': True,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_searchable': False,
            'pronouns': None,
            'pronouns_nametag': False,
            'pronouns_profile': False,
            'name_supplement': None,
            'title': None,
            'balance': decimal.Decimal("0.00"),
            'donation': decimal.Decimal("0.00"),
            'trial_member': True,
            'honorary_member': False,
            'decided_search': False,
            'bub_search': False,
            'address2': None,
            'address_supplement2': None,
            'postal_code2': None,
            'location2': None,
            'country2': None,
            'foto': None,
            'affiliation': None,
            'free_form': None,
            'weblink': None,
            'interests': None,
            'specialisation': None,
            'timeline': None,
            'paper_expuls': True,
        })
        value = self.core.get_cde_user(self.key, new_id)
        self.assertEqual(expectation, value)
        self.assertTrue(self.core.delete_genesis_case(self.key, case_id))
        self.assertFalse(self.core.genesis_attachment_usage(
            self.key, attachment_hash))

    @storage
    def test_genesis_attachments(self) -> None:
        pdffile = self.testfile_dir / "form.pdf"
        with open(pdffile, 'rb') as f:
            pdfdata = f.read()
        pdfhash = get_hash(pdfdata)
        self.assertEqual(
            pdfhash, self.core.genesis_set_attachment(self.key, pdfdata))
        with self.assertRaises(PrivilegeError):
            self.core.genesis_attachment_usage(self.key, pdfhash)
        self.login(USER_DICT["anton"])
        self.assertEqual(
            0, self.core.genesis_attachment_usage(self.key, pdfhash))
        self.assertEqual(1, self.core.genesis_forget_attachments(self.key))

    def test_genesis_verify_multiple(self) -> None:
        self.assertEqual((0, "core"), self.core.genesis_verify(ANONYMOUS, 123))
        genesis_data = {
            "given_names": "Max",
            "family_name": "Mailschreiber",
            "realm": "ml",
            "username": "max@mailschreiber.de",
            "notes": "Max möchte Mails mitbekommen.",
        }
        case_id = self.core.genesis_request(ANONYMOUS, genesis_data)
        assert case_id is not None
        self.assertLess(0, case_id)
        ret, realm = self.core.genesis_verify(ANONYMOUS, case_id)
        self.assertLess(0, ret)
        ret, realm = self.core.genesis_verify(ANONYMOUS, case_id)
        self.assertLess(ret, 0)
        self.login(USER_DICT["anton"])
        total, _ = self.core.retrieve_log(
            self.key, CoreLogFilter(codes=[const.CoreLogCodes.genesis_verified]))
        self.assertEqual(1, total)

    @as_users("vera")
    def test_verify_personas(self) -> None:
        self.assertFalse(self.core.verify_personas(
            self.key, (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1000), {"event"}))
        self.assertFalse(self.core.verify_persona(self.key, 1000))
        self.assertFalse(self.core.verify_persona(self.key, 5, {"cde"}))
        self.assertTrue(self.core.verify_persona(self.key, 5, {"event"}))
        self.assertTrue(self.core.verify_persona(self.key, 2, {"cde"}))
        self.assertTrue(self.core.verify_persona(self.key, 1, {"meta_admin"}))
        self.assertTrue(self.core.verify_personas(
            self.key, (1, 2, 3, 7, 9), {"cde", "member"}))
        self.assertFalse(self.core.verify_personas(
            self.key, (1, 2, 3, 7, 9), {"searchable"}))
        self.assertTrue(self.core.verify_personas(
            self.key, (1, 2, 9), {"searchable"}))

    @as_users("vera")
    def test_user_getters(self) -> None:
        expectation = {
            'display_name': 'Bertå',
            'family_name': 'Beispiel',
            'given_names': 'Bertålotta',
            'name_supplement': 'MdB',
            'title': 'Dr.',
            'id': 2,
            'is_active': True,
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_assembly_realm': True,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_cde_realm': True,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_event_realm': True,
            'is_member': True,
            'is_ml_admin': False,
            'is_ml_realm': True,
            'is_cdelokal_admin': False,
            'is_auditor': False,
            'is_purged': False,
            'is_searchable': True,
            'username': 'berta@example.cde'}
        self.assertEqual(expectation, self.core.get_persona(self.key, 2))
        self.assertEqual(expectation, self.core.get_ml_user(self.key, 2))
        self.assertEqual(expectation, self.core.get_assembly_user(self.key, 2))
        expectation.update({
            'address': 'Im Garten 77',
            'address_supplement': 'bei Spielmanns',
            'birthday': datetime.date(1981, 2, 11),
            'country': "DE",
            'gender': 1,
            'pronouns': "she/her",
            'pronouns_nametag': False,
            'pronouns_profile': True,
            'location': 'Utopia',
            'mobile': '+4916312345678',
            'name_supplement': 'MdB',
            'postal_code': '34576',
            'telephone': '+495432987654321',
            'title': 'Dr.',
            })
        self.assertEqual(expectation, self.core.get_event_user(self.key, 2))
        expectation.update({
            'address2': 'Strange Road 9 3/4',
            'address_supplement2': None,
            'affiliation': 'Jedermann',
            'balance': decimal.Decimal('12.50'),
            'donation': decimal.Decimal('42.23'),
            'birth_name': 'Gemeinser',
            'bub_search': True,
            'country2': 'GB',
            'decided_search': True,
            'foto': 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbe'
                    'c03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9',
            'free_form': 'Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen',
            'interests': 'Immer',
            'location2': 'Foreign City',
            'paper_expuls': True,
            'postal_code2': '8XA 45-$',
            'specialisation': 'Alles\nUnd noch mehr',
            'telephone': '+495432987654321',
            'timeline': 'Überall',
            'trial_member': False,
            'honorary_member': False,
            'username': 'berta@example.cde',
            'weblink': '<https://www.bundestag.cde>'})
        self.assertEqual(expectation, self.core.get_cde_user(self.key, 2))
        expectation['notes'] = 'Beispielhaft, Besser, Baum.'
        self.assertEqual(expectation, self.core.get_total_persona(self.key, 2))

    @as_users("paul", "quintus")
    def test_archive(self) -> None:
        persona_id = 3
        with self.switch_user("anton"):
            self.core.change_membership_easy_mode(self.key, persona_id,
                                                  honorary_member=True)
            self.core.set_persona(self.key, {'id': persona_id, "balance": 5},
                                  allow_specials=('finance', ))
        data = self.core.get_total_persona(self.key, persona_id)
        self.assertEqual(False, data['is_archived'])
        self.assertEqual(True, data['is_cde_realm'])
        ret = self.core.archive_persona(
            self.key, persona_id, "Archived for testing.")
        self.assertLess(0, ret)
        self.assertEqual(True, data['is_cde_realm'])
        data = self.core.get_total_persona(self.key, persona_id)
        self.assertEqual(True, data['is_archived'])
        # The user may have balance if he lost his membership in the ongoing semester
        #  Ensure that the removal of the balance is logged correctly
        log = [{
            "code": const.FinanceLogCodes.remove_balance_on_archival,
            "submitted_by": self.user['id'],
            "persona_id": persona_id,
            "delta": "-5.00",
            "new_balance": "0.00",
            "members": 8,
            "total": "724.87",
            "member_total": "113.76",
            "transaction_date": None,
        }]
        self.assertLogEqual(
            log, 'finance', codes=[const.FinanceLogCodes.remove_balance_on_archival])
        ret = self.core.dearchive_persona(self.key, persona_id,
                                          new_username="charly@example.cde")
        self.assertLess(0, ret)
        data = self.core.get_total_persona(self.key, persona_id)
        self.assertEqual(False, data['is_archived'])

        # Test correct handling of lastschrift during archival.
        self.login("anton")
        ls_data = {
            "persona_id": persona_id,
            "iban": "DE12500105170648489890",
            "account_owner": "Der Opa",
            "account_address": "Nebenan",
            "notes": "Ganz wichtige Notizen",
            "granted_at": datetime.datetime.fromisoformat("2000-01-01"),
            "revoked_at": datetime.datetime.fromisoformat("2000-01-01"),
        }
        old_ls_id = self.cde.create_lastschrift(
            self.key, ls_data, initial_donation=decimal.Decimal("5"))
        del ls_data["revoked_at"]
        ls_id = self.cde.create_lastschrift(
            self.key, ls_data, initial_donation=decimal.Decimal("7"))
        self.login("vera")
        with self.assertRaises(ArchiveError) as cm:
            self.core.archive_persona(self.key, persona_id, "Testing")
        self.assertEqual("Active lastschrift exists.", cm.exception.args[0])
        update = {
            'id': ls_id,
            'revoked_at': now(),
        }
        self.cde.set_lastschrift(self.key, update)
        self.core.archive_persona(self.key, persona_id, "Testing")
        ls = self.cde.get_lastschrift(self.key, ls_id)
        ls_data.update(update)
        ls_data["submitted_by"] = 1
        ls["granted_at"] = ls_data["granted_at"]
        self.assertEqual(ls, ls_data)
        old_ls = self.cde.get_lastschrift(self.key, old_ls_id)
        self.assertEqual(old_ls["iban"], "")
        self.assertEqual(old_ls["account_owner"], "")
        self.assertEqual(old_ls["account_address"], "")
        self.assertEqual(old_ls["notes"], ls_data["notes"])
        self.core.dearchive_persona(self.key, persona_id,
                                    new_username="charly@example.cde")

        # Check that sole moderators cannot be archived.
        with self.switch_user("nina"):
            self.ml.add_moderators(self.key, 2, {persona_id})
            self.ml.remove_moderator(self.key, 2, 10)
        with self.assertRaises(ArchiveError) as cm:
            self.core.archive_persona(self.key, persona_id, "Testing")
        self.assertIn("Sole moderator of a mailinglist", cm.exception.args[0])

        # Test archival of user that is no moderator.
        self.core.archive_persona(self.key, 8, "Testing")

    @as_users("vera")
    def test_archive_activate_bug(self) -> None:
        self.core.archive_persona(self.key, 4, "Archived for testing.")
        self.core.dearchive_persona(self.key, 4, new_username="daniel@example.cde")
        # The following call sometimes failed with the error "editing
        # archived members impossbile". This could be pampered over with a
        # sleep to let the DB settle, but this would only hide a real problem.
        data = {
            'id': 4,
            'is_active': True,
        }
        self.core.change_persona(self.key, data, may_wait=False)

    @as_users("vera")
    def test_archive_admin(self) -> None:
        # Nina is mailinglist admin.
        with self.assertRaises(ArchiveError):
            self.core.archive_persona(self.key, 14, "Admins can not be archived.")

    @as_users("vera")
    @prepsql("DELETE FROM ml.moderators WHERE persona_id = 10")
    def test_purge(self) -> None:
        purged_personas = {}
        for p_id, name in ((8, "Hades"), (3, "Charly C."), (10, "Janis")):
            if p_id != 8:
                self.core.archive_persona(self.key, p_id, "Archived for testing.")
            data = self.core.get_total_persona(self.key, p_id)
            self.assertEqual(name, data['given_names'])
            ret = self.core.purge_persona(self.key, p_id)
            self.assertLess(0, ret)
            purged_personas[p_id] = self.core.get_total_persona(self.key, p_id)
            del purged_personas[p_id]['id']
            self.assertEqual("N.", purged_personas[p_id]['given_names'])
        self.assertEqual(purged_personas[3], purged_personas[10])

    def test_privilege_change(self) -> None:
        # This is somewhat hacky for now, because we need a second meta admin
        # for this to work with the new pending PrivilegeChange system
        admin1 = USER_DICT["anton"]
        admin2 = USER_DICT["martin"]
        new_admin = USER_DICT["berta"]

        self.login(admin1)
        data = {
            "persona_id": new_admin["id"],
            "notes": "Granting admin privileges for testing.",
            "is_cde_admin": True,
            "is_finance_admin": True,
        }

        case_id = self.core.initialize_privilege_change(self.key, data)
        self.assertLess(0, case_id)

        persona = self.core.get_persona(self.key, new_admin["id"])
        self.assertEqual(False, persona["is_cde_admin"])
        self.assertEqual(False, persona["is_finance_admin"])

        self.login(admin2)
        self.core.finalize_privilege_change(
            self.key, case_id, const.PrivilegeChangeStati.approved)

        persona = self.core.get_persona(self.key, new_admin["id"])
        self.assertEqual(True, persona["is_cde_admin"])
        self.assertEqual(True, persona["is_finance_admin"])

        self.login(admin1)
        core_log_expectation = (3, (
            # Finalizing the privilege process.
            {
                'id': 1001,
                'change_note': "Änderung der Admin-Privilegien angestoßen.",
                'code': const.CoreLogCodes.privilege_change_pending.value,
                'ctime': nearly_now(),
                'persona_id': new_admin["id"],
                'submitted_by': admin1["id"],
            },
            # Starting the privilege change process.
            {
                'id': 1002,
                'change_note': "Änderung der Admin-Privilegien bestätigt.",
                'code': const.CoreLogCodes.privilege_change_approved.value,
                'ctime': nearly_now(),
                'persona_id': new_admin["id"],
                'submitted_by': admin2["id"],
            },
            # Password invalidation.
            {
                'id': 1003,
                'change_note': None,
                'code': const.CoreLogCodes.password_invalidated,
                'ctime': nearly_now(),
                'persona_id': new_admin['id'],
                'submitted_by': admin2['id'],
            },
        ))
        result = self.core.retrieve_log(self.key, CoreLogFilter())
        self.assertEqual(core_log_expectation, result)

        total_entries = self.core.retrieve_changelog_meta(
            self.key, ChangelogLogFilter())[0]
        changelog_expectation = (
            # Committing the changed admin bits.
            {
                'id': 1001,
                'change_note': data["notes"],
                'code': const.PersonaChangeStati.committed.value,
                'ctime': nearly_now(),
                'generation': 2,
                'persona_id': new_admin["id"],
                'reviewed_by': None,
                'submitted_by': admin2["id"],
                'automated_change': False,
            },
        )
        # Set offset to avoid selecting the Init. changelog entries
        self.assertLogEqual(changelog_expectation, 'changelog', offset=total_entries-1)

    @as_users("anton", "martin")
    def test_invalid_privilege_change(self) -> None:
        data = {
            "persona_id": USER_DICT["janis"]["id"],
            "is_meta_admin": True,
            "notes": "For testing.",
        }
        with self.assertRaises(ValueError):
            self.core.initialize_privilege_change(self.key, data)

        data = {
            "persona_id": USER_DICT["emilia"]["id"],
            "is_core_admin": True,
            "notes": "For testing.",
        }
        with self.assertRaises(ValueError):
            self.core.initialize_privilege_change(self.key, data)

        data = {
            "persona_id": USER_DICT["berta"]["id"],
            "is_finance_admin": True,
            "notes": "For testing.",
        }
        with self.assertRaises(ValueError):
            self.core.initialize_privilege_change(self.key, data)

        data = {
            "persona_id": USER_DICT["ferdinand"]["id"],
            "is_finance_admin": True,
            "is_cde_admin": False,
            "notes": "For testing.",
        }
        with self.assertRaises(ValueError):
            self.core.initialize_privilege_change(self.key, data)

    @as_users("garcia")
    def test_non_participant_privacy(self) -> None:
        with self.assertRaises(PrivilegeError) as cm:
            self.core.get_event_users(self.key, (3,), 1)
        self.assertIn("Access to persona data inhibited.",
                      cm.exception.args)
        self.core.get_event_users(self.key, (9,), 1)

    @as_users("vera")
    def test_get_persona_latest_session(self) -> None:
        ip = "127.0.0.1"
        for u in USER_DICT.values():
            if u["id"] is None:
                continue
            with self.subTest(u=u["id"]):
                if u["id"] in {8, 12, 15}:
                    if u["id"] in {15}:  # These users are deactivated.
                        ret = self.core.login(
                            ANONYMOUS, u["username"], u["password"], ip)
                        self.assertIsNone(ret)
                    else:  # These users have no usernames.
                        with self.assertRaises(TypeError):
                            self.core.login(ANONYMOUS, u["username"], u["password"], ip)
                else:
                    if not self.user_in(u["id"]):
                        self.assertIsNone(
                            self.core.get_persona_latest_session(self.key, u["id"]))
                        self.core.login(ANONYMOUS, u["username"], u["password"], ip)
                    self.assertEqual(
                        nearly_now(),
                        self.core.get_persona_latest_session(self.key, u["id"]))

    @prepsql(f"UPDATE core.changelog SET ctime ="
             f" '{now() - datetime.timedelta(days=365 * 2 + 1)}'")
    @prepsql("DELETE FROM ml.subscription_states"
             " WHERE persona_id = 4 AND mailinglist_id = 62")
    def test_automated_archival(self) -> None:
        self.login("anton")
        self.event.delete_registration(self.key, 7,
                                       ("registration_parts", "course_choices",
                                        "registration_tracks"))
        for u in USER_DICT.values():
            self.login("vera")
            if u["id"] is None:
                continue
            with self.subTest(u=u["id"]):
                res = self.core.is_persona_automatically_archivable(self.key, u["id"])
                if u["id"] == 4:
                    self.assertTrue(res)
                    key = self.key
                    self.core.set_persona(
                        key, {"id": u["id"], "notes": "test"},
                        change_note="Diese Änderung wurde maschinell erstellt und ist"
                                    " auch ohne Unterschrift gültig.",
                        automated_change=True)
                    self.assertTrue(
                        self.core.is_persona_automatically_archivable(key, u["id"]))
                    self.assertIsNone(
                        self.core.get_persona_latest_session(key, u["id"]))
                    self.login(u)
                    self.assertIsNotNone(
                        self.core.get_persona_latest_session(key, u["id"]))
                    self.assertFalse(
                        self.core.is_persona_automatically_archivable(key, u["id"]))
                else:
                    self.assertFalse(res)

    @as_users("janis")
    def test_list_personas(self) -> None:
        all_personas = tuple(e for e in self.get_sample_data("core.personas").values()
                             if not e['is_archived'])
        reality = self.core.list_all_personas(self.key, is_active=False)
        self.assertEqual(reality, {e['id'] for e in all_personas})
        active_personas = {e['id'] for e in all_personas if e['is_active']}
        reality = self.core.list_all_personas(self.key, is_active=True)
        self.assertEqual(reality, active_personas)
        current_active_members = {
            e['id'] for e in all_personas if e['is_member'] and e['is_active']}
        reality = self.core.list_current_members(self.key, is_active=True)
        self.assertEqual(reality, current_active_members)
        current_members = {e['id'] for e in all_personas if e['is_member']}
        reality = self.core.list_current_members(self.key, is_active=False)
        self.assertEqual(reality, current_members)
        all_moderators = {
            e['persona_id'] for e in self.get_sample_data("ml.moderators").values()}
        reality = self.core.list_all_moderators(self.key)
        self.assertEqual(reality, all_moderators)
        MT = const.MailinglistTypes
        reality = self.core.list_all_moderators(
            self.key, {MT.member_moderated_opt_in, MT.cdelokal})
        self.assertEqual({2, 5, 9, 100}, reality)

    @as_users("vera")
    def test_log(self) -> None:
        # first generate some data
        data = copy.deepcopy(PERSONA_TEMPLATE)
        new_persona_id = self.core.create_persona(self.key, data)
        genesis_data = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zeldax@example.cde',
            'realm': "ml",
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(ANONYMOUS, genesis_data)
        assert case_id is not None
        self.core.genesis_verify(ANONYMOUS, case_id)
        new_genesis_persona_id = self.core.genesis_decide(
            self.key, case_id, GenesisDecision.approve)
        newpass = "er3NQ_5bkrc#"
        self.core.change_password(self.key, self.user['password'], newpass)

        log_expectation: List[CdEDBObject] = [
            {
                'code': const.CoreLogCodes.persona_creation,
                'persona_id': new_persona_id,
            },
            {
                'code': const.CoreLogCodes.genesis_request,
                'change_note': genesis_data['username'],
                'submitted_by': None,
            },
            {
                'code': const.CoreLogCodes.genesis_verified,
                'change_note': genesis_data['username'],
                'submitted_by': None,
            },
            {
                'code': const.CoreLogCodes.persona_creation,
                'persona_id': new_genesis_persona_id,
            },
            {
                'code': const.CoreLogCodes.genesis_approved,
                'change_note': genesis_data['username'],
                'persona_id': new_genesis_persona_id,
            },
            {
                'code': const.CoreLogCodes.password_change,
                'persona_id': self.user['id'],
            },
        ]

        self.assertLogEqual(log_expectation, realm="core")
        with self.assertRaises(ValueError):
            self.core.redact_log(self.key, "core.personas", 1002)
        self.core.redact_log(self.key, "core.log", 1002)
        log_expectation[1]['change_note'] = None
        self.assertLogEqual(log_expectation, realm="core")

    @as_users("vera")
    def test_changelog_meta(self) -> None:
        expectation = self.get_sample_data(
            "core.changelog", ids=None,
            keys=("id", "submitted_by", "reviewed_by", "ctime", "generation",
                  "change_note", "code", "persona_id", "automated_change"))
        self.assertLogEqual(list(expectation.values()), 'changelog')

    @as_users("katarina")
    def test_auditor(self) -> None:
        for log_realm, table in (
            ('core', "core.log"),
            ('changelog', "core.changelog"),
            ('cde', "cde.log"),
            ('finance', "cde.finance_log"),
            ('assembly', "assembly.log"),
            ('event', "event.log"),
            ('ml', "ml.log"),
            ('past_event', "past_event.log"),
        ):
            with self.subTest(log=table):
                keys = None
                if table == "core.changelog":
                    keys = ("change_note", "code", "ctime", "generation", "id",
                            "persona_id", "reviewed_by", "submitted_by",
                            "automated_change")
                self.assertLogEqual(
                    tuple(self.get_sample_data(table, keys=keys).values()),
                    realm=log_realm
                )
