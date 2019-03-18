#!/usr/bin/env python3

import copy
import datetime
import decimal
import subprocess

import cdedb.database.constants as const
from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.common import (
    PERSONA_EVENT_FIELDS, PERSONA_ML_FIELDS, PrivilegeError)

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
    'decided_search': None,
    'bub_search': None,
    'foto': None,
}

class TestCoreBackend(BackendTest):
    used_backends = ("core",)

    def test_login(self):
        for i, u in enumerate(("anton", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                key = self.core.login(None, user['username'], user['password'],
                                      "127.0.0.0")
                self.assertIsInstance(key, str)
                self.assertTrue(key)

                key = self.core.login(None, user['username'], "wrong key",
                                      "127.0.0.0")
                self.assertEqual(None, key)

    @as_users("anton", "berta", "emilia")
    def test_logout(self, user):
        self.assertTrue(self.key)
        self.assertEqual(1, self.core.logout(self.key))
        with self.assertRaises(RuntimeError):
            self.core.logout(self.key)

    @as_users("anton", "berta", "emilia")
    def test_set_persona(self, user):
        new_name = "Zelda"
        self.core.set_persona(self.key, {'id': user['id'],
                                         'display_name': new_name})
        self.assertEqual(new_name, self.core.retrieve_persona(
            self.key, user['id'])['display_name'])

    @as_users("anton", "berta")
    def test_change_password(self, user):
        ret, _ = self.core.change_password(self.key, user['password'],
                                           "weakpass")
        self.assertFalse(ret)
        newpass = "er3NQ_5bkrc#"
        ret, message = self.core.change_password(self.key, user['password'],
                                                 newpass)
        self.assertTrue(ret)
        self.assertEqual(newpass, message)
        self.core.logout(self.key)
        self.key = None
        self.login(user)
        self.assertEqual(None, self.key)
        newuser = copy.deepcopy(user)
        newuser['password'] = newpass
        self.login(newuser)
        self.assertTrue(self.key)

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user):
        newaddress = "newaddress@example.cde"
        ret, _ = self.core.change_username(self.key, user['id'], newaddress, user['password'])
        self.assertTrue(ret)
        self.core.logout(self.key)
        self.key = None
        self.login(user)
        self.assertEqual(None, self.key)
        newuser = copy.deepcopy(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.key)

    @as_users("anton", "berta")
    def test_set_foto(self, user):
        new_foto = "rkorechkorekchoreckhoreckhorechkrocehkrocehk"
        self.assertLess(0, self.core.change_foto(self.key, 2, new_foto))
        result = self.core.get_cde_users(self.key, (1, 2))
        self.assertEqual({1: None, 2: new_foto}, {k: result[k]['foto'] for k in result})

    def test_verify_existence(self):
        self.assertTrue(self.core.verify_existence(self.key, "anton@example.cde"))
        self.assertFalse(self.core.verify_existence(self.key, "nonexistent@example.cde"))

    def test_password_reset(self):
        new_pass = "rK;7e$ekgReW2t"
        ret, cookie = self.core.make_reset_cookie(self.key, "berta@example.cde")
        self.assertTrue(ret)
        ret, effective = self.core.reset_password(self.key, "berta@example.cde", new_pass, cookie)
        self.assertTrue(ret)
        self.assertEqual(new_pass, effective)
        with self.assertRaises(PrivilegeError):
            self.core.make_reset_cookie(self.key, "anton@example.cde")
        ret, _ = self.core.make_reset_cookie(self.key, "nonexistant@example.cde")
        self.assertFalse(ret)

    @as_users("anton")
    def test_create_persona(self, user):
        data = copy.deepcopy(PERSONA_TEMPLATE)
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        self.assertEqual(data, new_data)
        expectation = {
            1: {
                'address': None,
                'address2': None,
                'address_supplement': None,
                'address_supplement2': None,
                'affiliation': None,
                'balance': None,
                'birth_name': None,
                'birthday': None,
                'bub_search': None,
                'change_note': 'Account erstellt.',
                'change_status': 2,
                'country': None,
                'country2': None,
                'ctime': nearly_now(),
                'decided_search': None,
                'display_name': 'Zelda',
                'family_name': 'Zeruda-Hime',
                'foto': None,
                'free_form': None,
                'gender': None,
                'generation': 1,
                'given_names': 'Zelda',
                'id': 13,
                'interests': None,
                'is_active': True,
                'is_admin': False,
                'is_archived': False,
                'is_assembly_admin': False,
                'is_assembly_realm': False,
                'is_cde_admin': False,
                'is_cde_realm': False,
                'is_core_admin': False,
                'is_event_admin': False,
                'is_event_realm': False,
                'is_member': False,
                'is_ml_admin': False,
                'is_ml_realm': False,
                'is_searchable': False,
                'location': None,
                'location2': None,
                'mobile': None,
                'name_supplement': None,
                'notes': 'Not Link.',
                'postal_code': None,
                'postal_code2': None,
                'reviewed_by': None,
                'specialisation': None,
                'submitted_by': 1,
                'telephone': None,
                'timeline': None,
                'title': None,
                'trial_member': None,
                'username': 'zelda@example.cde',
                'weblink': None}}
        history = self.core.changelog_get_history(self.key, new_id, None)
        self.assertEqual(expectation, history)

    @as_users("anton")
    def test_create_member(self, user):
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
            'country': "Arkadien",
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
            'decided_search': False,
            'bub_search': False,
            'foto': None,
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': decimal.Decimal('0.00'),
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        self.assertEqual(data, new_data)

    @as_users("anton")
    def test_create_event_user(self, user):
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
            'country': "Arkadien",
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        self.assertEqual(data, new_data)


    @as_users("anton")
    def test_create_assembly_user(self, user):
        data = copy.deepcopy(PERSONA_TEMPLATE)
        data['is_ml_realm'] = True
        data['is_assembly_realm'] = True
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        self.assertEqual(data, new_data)

    @as_users("anton")
    def test_create_mixed_user(self, user):
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
            'country': "Arkadien",
        })
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_total_persona(self.key, new_id)
        data.update({
            'balance': None,
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        self.assertEqual(data, new_data)

    @as_users("anton")
    def test_meta_info(self, user):
        expectation = {
            'CdE_Konto_BIC': 'BFSWDE33XXX',
            'CdE_Konto_IBAN': 'DE26370205000008068900',
            'CdE_Konto_Inhaber': 'CdE e.V.',
            'CdE_Konto_Institut': 'Bank für Sozialwirtschaft',
            'Finanzvorstand_Adresse_Einzeiler':
                'Bertålotta Beispiel, bei Spielmanns, Im Garten 77, 34576 Utopia',
            'Finanzvorstand_Adresse_Zeile2': 'bei Spielmanns',
            'Finanzvorstand_Adresse_Zeile3': 'Im Garten 77',
            'Finanzvorstand_Adresse_Zeile4': '34576 Utopia',
            'Finanzvorstand_Name': 'Bertålotta Beispiel',
            'Finanzvorstand_Ort': 'Utopia',
            'Finanzvorstand_Vorname': 'Bertålotta',
            'banner_before_login': 'Das Passwort ist secret!',
            'Vorstand': 'Anton und Berta',
            'banner_after_login': '*Dies ist eine Testversion der Datenbank, alles wird gelöscht werden!*'}
        self.assertEqual(expectation, self.core.get_meta_info(self.key))
        update = {
            'Finanzvorstand_Name': 'Zelda'
        }
        self.assertLess(0, self.core.set_meta_info(self.key, update))
        expectation.update(update)
        self.assertEqual(expectation, self.core.get_meta_info(self.key))

    @as_users("anton")
    def test_genesis_event(self, user):
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
            'country': "Arkadien",
        }
        case_id = self.core.genesis_request(None, data)
        self.assertGreater(case_id, 0)
        self.assertEqual((1, 'event'), self.core.genesis_verify(None, case_id))
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, stati=(const.GenesisStati.to_review,))))
        expectation = data
        expectation.update({
            'id': case_id,
            'case_status': const.GenesisStati.to_review,
            'reviewer': None,
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        update = {
            'id': case_id,
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
        expectation = {k: v for k, v in expectation.items() if k in PERSONA_EVENT_FIELDS}
        expectation.update({
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': False,
            'is_ml_admin': False,
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
        })
        self.assertEqual(expectation, value)

    @as_users("anton")
    def test_genesis_ml(self, user):
        data = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zelda@example.cde',
            "realm": "ml",
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(None, data)
        self.assertGreater(case_id, 0)
        self.assertEqual((1, 'ml'), self.core.genesis_verify(None, case_id))
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, stati=(const.GenesisStati.to_review,))))
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
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        update = {
            'id': case_id,
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
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': False,
            'is_ml_admin': False,
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

    @as_users("anton")
    def test_verify_personas(self, user):
        self.assertEqual(
            {1, 2, 3, 5, 6, 7, 9, 12},
            set(self.core.verify_personas(self.key, (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1000), ("event",))))

    @as_users("anton")
    def test_user_getters(self, user):
        expectation = {
            'display_name': 'Bertå',
            'family_name': 'Beispiel',
            'given_names': 'Bertålotta',
            'name_supplement': 'MdB',
            'title': 'Dr.',
            'id': 2,
            'is_active': True,
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_assembly_realm': True,
            'is_cde_admin': False,
            'is_cde_realm': True,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_event_realm': True,
            'is_member': True,
            'is_ml_admin': False,
            'is_ml_realm': True,
            'is_searchable': True,
            'username': 'berta@example.cde'}
        self.assertEqual(expectation, self.core.get_persona(self.key, 2))
        self.assertEqual(expectation, self.core.get_ml_user(self.key, 2))
        self.assertEqual(expectation, self.core.get_assembly_user(self.key, 2))
        expectation.update({
            'address': 'Im Garten 77',
            'address_supplement': 'bei Spielmanns',
            'birthday': datetime.date(1981, 2, 11),
            'country': None,
            'gender': 1,
            'location': 'Utopia',
            'mobile': '0163/123456789',
            'name_supplement': 'MdB',
            'postal_code': '34576',
            'telephone': '+49 (5432) 987654321',
            'title': 'Dr.',
            })
        self.assertEqual(expectation, self.core.get_event_user(self.key, 2))
        expectation.update({
            'address2': 'Strange Road 9 3/4',
            'address_supplement2': None,
            'affiliation': 'Jedermann',
            'balance': decimal.Decimal('12.50'),
            'birth_name': 'Gemeinser',
            'bub_search': True,
            'country2': 'Far Away',
            'decided_search': True,
            'foto': 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9',
            'free_form': 'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen',
            'interests': 'Immer',
            'location2': 'Foreign City',
            'postal_code2': '8XA 45-$',
            'specialisation': 'Alles\nUnd noch mehr',
            'telephone': '+49 (5432) 987654321',
            'timeline': 'Überall',
            'trial_member': False,
            'username': 'berta@example.cde',
            'weblink': 'https://www.bundestag.cde'})
        self.assertEqual(expectation, self.core.get_cde_user(self.key, 2))
        expectation['notes'] = None
        self.assertEqual(expectation, self.core.get_total_persona(self.key, 2))

    @as_users("anton")
    def test_archive(self, user):
        data = self.core.get_total_persona(self.key, 3)
        self.assertEqual(False, data['is_archived'])
        ret = self.core.archive_persona(self.key, 3)
        self.assertLess(0, ret)
        data = self.core.get_total_persona(self.key, 3)
        self.assertEqual(True, data['is_archived'])
        ret = self.core.dearchive_persona(self.key, 3)
        self.assertLess(0, ret)
        data = self.core.get_total_persona(self.key, 3)
        self.assertEqual(False, data['is_archived'])

    @as_users("anton")
    def test_archive_activate_bug(self, user):
        self.core.archive_persona(self.key, 4)
        self.core.dearchive_persona(self.key, 4)
        # The following call sometimes failed with the error "editing
        # archived members impossbile". The solution may be to add some
        # sleep to let the DB settle, but this seems kind of bogus.
        #
        # import time
        # time.sleep(1)
        data = {
            'id': 4,
            'is_active': True,
        }
        self.core.change_persona(self.key, data, may_wait=False)

    @as_users("anton")
    def test_purge(self, user):
        data = self.core.get_total_persona(self.key, 8)
        self.assertEqual("Hades", data['given_names'])
        ret = self.core.purge_persona(self.key, 8)
        self.assertLess(0, ret)
        data = self.core.get_total_persona(self.key, 8)
        self.assertEqual("N.", data['given_names'])

    @as_users("anton")
    def test_log(self, user):
        ## first generate some data
        data = copy.deepcopy(PERSONA_TEMPLATE)
        self.core.create_persona(self.key, data)
        data = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zeldax@example.cde',
            'realm': "ml",
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(None, data)
        update = {
            'id': case_id,
            'case_status': const.GenesisStati.approved,
            'reviewer': 1,
        }
        self.core.genesis_modify_case(self.key, update)
        newpass = "er3NQ_5bkrc#"
        self.core.change_password(self.key, user['password'], newpass)

        ## now check it
        expectation = (
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': 'zeldax@example.cde',
             'code': 21,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'zeldax@example.cde',
             'code': 20,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': None},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'persona_id': 13,
             'submitted_by': 1})
        self.assertEqual(expectation, self.core.retrieve_log(self.key))

    @as_users("anton")
    def test_changelog_meta(self, user):
        expectation = (
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 12,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 11,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 10,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 9,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 8,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 7,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 6,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 5,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 4,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 3,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 2,
             'reviewed_by': None,
             'submitted_by': 2},
            {'change_note': 'Init.',
             'change_status': 2,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 1,
             'reviewed_by': None,
             'submitted_by': 1})
        self.assertEqual(expectation,
                         self.core.retrieve_changelog_meta(self.key))
