#!/usr/bin/env python3

from cdedb.common import QuotaException
from cdedb.query import QUERY_SPECS, QueryOperators
import cdedb.database.constants as const
from test.common import BackendTest, as_users, USER_DICT, nearly_now
import decimal
import datetime
import pytz
import copy

class TestCdEBackend(BackendTest):
    used_backends = ("core", "cde")

    @as_users("anton", "berta")
    def test_basics(self, user):
        data = self.cde.get_data_one(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['birth_name'] = "Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'birth_name', 'display_name', 'telephone'}}
        num = self.cde.change_user(self.key, setter, 1, change_note='note')
        self.assertEqual(1, num)
        new_data = self.cde.get_data_one(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("berta")
    def test_quota(self, user):
        for _ in range(25):
            self.cde.get_data(self.key, (1, 2, 3))
        with self.assertRaises(QuotaException):
            self.cde.get_data(self.key, (1, 2, 3))

    @as_users("berta")
    def test_displacement(self, user):
        self.assertEqual(
            -1, self.cde.change_user(self.key, {'id': user['id'],
                                                'family_name': "Link"}, 1))
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
        data = self.cde.get_data_one(self.key, user['id'],)
        self.assertEqual(user['family_name'], data['family_name'])
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.cde.resolve_change(self.key, user['id'], 4, ack=True)
        data = self.cde.get_data_one(self.key, user['id'],)
        self.assertEqual("Link", data['family_name'])

    @as_users("berta")
    def test_nack_change(self, user):
        self.assertEqual(
            -1, self.cde.change_user(self.key, {'id': user['id'],
                                                'family_name': "Link"}, 1))
        self.assertEqual(2, self.cde.get_generation(self.key, user['id']))
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.cde.resolve_change(self.key, user['id'], 2, ack=False)
        self.assertEqual(1, self.cde.get_generation(self.key, user['id']))

    @as_users("anton", "berta")
    def test_get_data(self, user):
        data = self.cde.get_data(self.key, (1, 2))
        expectation = {1: {
            'bub_search': True,
            'location': 'Musterstadt',
            'cloud_account': True,
            'specialisation': None,
            'id': 1,
            'address_supplement': None,
            'username': 'anton@example.cde',
            'affiliation': None,
            'interests': None,
            'location2': 'Hintertupfingen',
            'birth_name': None,
            'weblink': None,
            'balance': decimal.Decimal('17.50'),
            'decided_search': True,
            'timeline': None,
            'address_supplement2': None,
            'given_names': 'Anton Armin A.',
            'address': 'Auf der Düne 42',
            'status': 0,
            'db_privileges': 1,
            'gender': 1,
            'title': None,
            'mobile': None,
            'country': None,
            'country2': None,
            'family_name': 'Administrator',
            'trial_member': False,
            'display_name': 'Anton',
            'name_supplement': None,
            'notes': None,
            'telephone': '+49 (234) 98765',
            'address2': 'Unter dem Hügel 23',
            'postal_code': '03205',
            'free_form': None,
            'is_active': True,
            'postal_code2': '22335',
            'birthday': datetime.datetime(1991, 3, 30).date()},
            2: {'bub_search': True,
            'location': 'Utopia',
            'cloud_account': True,
            'specialisation': 'Alles\nUnd noch mehr',
            'id': 2,
            'address_supplement': 'bei Spielmanns',
            'username': 'berta@example.cde',
            'affiliation': 'Jedermann',
            'interests': 'Immer',
            'location2': 'Foreign City',
            'birth_name': 'Gemeinser',
            'weblink': 'https://www.bundestag.cde',
            'balance': decimal.Decimal('12.50'),
            'decided_search': True,
            'timeline': 'Überall',
            'address_supplement2': None,
            'given_names': 'Bertålotta',
            'address': 'Im Garten 77',
            'status': 0,
            'db_privileges': 0,
            'gender': 0,
            'title': 'Dr.',
            'mobile': '0163/123456789',
            'country': None,
            'country2': 'Far Away',
            'family_name': 'Beispiel',
            'trial_member': False,
            'display_name': 'Bertå',
            'name_supplement': 'MdB',
            'notes': None,
            'telephone': '+49 (5432) 987654321',
            'address2': 'Strange Road 9 3/4',
            'postal_code': '34576',
            'free_form': 'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen',
            'is_active': True,
            'postal_code2': '8XA 45-$',
            'birthday': datetime.datetime(1981, 2, 11).date()}}
        self.assertEqual(expectation, data)
        data = self.cde.get_data_no_quota(self.key, (1, 2))
        self.assertEqual(expectation, data)
        expectation = {1: {
            'id': 1,
            'username': 'anton@example.cde',
            'given_names': 'Anton Armin A.',
            'status': 0,
            'title': None,
            'family_name': 'Administrator',
            'display_name': 'Anton',
            'name_supplement': None,
            },
            2: {
            'id': 2,
            'username': 'berta@example.cde',
            'given_names': 'Bertålotta',
            'status': 0,
            'title': 'Dr.',
            'family_name': 'Beispiel',
            'display_name': 'Bertå',
            'name_supplement': 'MdB',
            }
        }
        data = self.cde.get_data_outline(self.key, (1, 2))
        self.assertEqual(expectation, data)

    @as_users("berta")
    def test_member_search(self, user):
        query = {
            "scope": "qview_cde_member",
            "spec": dict(QUERY_SPECS["qview_cde_member"]),
            "fields_of_interest": ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints": (("given_names,display_name", QueryOperators.regex.value, '[ae]'),
                             ("country,country2", QueryOperators.empty.value, None)),
            "order": (("family_name", True),),
        }
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({1, 2, 6, 9, 12}, {e['persona_id'] for e in result})

    @as_users("anton")
    def test_user_search(self, user):
        query = {
            "scope": "qview_cde_user",
            "spec": dict(QUERY_SPECS["qview_cde_user"]),
            "fields_of_interest": ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints": (("given_names", QueryOperators.regex.value, '[ae]'),
                             ("birthday", QueryOperators.less.value, datetime.datetime.now())),
            "order": (("family_name", True),),
        }
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({1, 2, 3, 4, 6, 7}, {e['persona_id'] for e in result})

    @as_users("anton")
    def test_user_search_operators(self, user):
        query = {
            "scope": "qview_cde_user",
            "spec": dict(QUERY_SPECS["qview_cde_user"]),
            "fields_of_interest": ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints": (("given_names", QueryOperators.similar.value, 'Berta'),
                             ("address", QueryOperators.oneof.value, ("Auf der Düne 42", "Im Garten 77")),
                             ("weblink", QueryOperators.containsall.value, ("/", ":", "http")),
                             ("birthday", QueryOperators.between.value, (datetime.datetime(1000, 1, 1),
                                                                         datetime.datetime.now()))),
            "order": (("family_name", True),),
        }
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2}, {e['persona_id'] for e in result})

    @as_users("anton", "berta")
    def test_get_fotos(self, user):
        expectation = {1: None,
                       2: 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9'}
        result = self.cde.get_fotos(self.key, (1, 2))
        self.assertEqual(expectation, result)

    @as_users("anton", "berta")
    def test_set_foto(self, user):
        new_foto = "rkorechkorekchoreckhoreckhorechkrocehkrocehk"
        self.assertEqual(True, self.cde.set_foto(self.key, 2, new_foto))
        result = self.cde.get_fotos(self.key, (1, 2))
        self.assertEqual({1: None, 2: new_foto}, result)

    @as_users("anton")
    def test_create_user(self, user):
        user_data = {
            "username": 'zelda@example.cde',
            "display_name": 'Zelda',
            "is_active": True,
            "status": const.PersonaStati.searchmember,
            "cloud_account": True,
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "title": None,
            "name_supplement": None,
            "gender": const.Genders.female,
            "birthday": datetime.date(1987, 6, 5),
            "telephone": None,
            "mobile": None,
            "address_supplement": None,
            "address": "Street 7",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
            "notes": None,
            "birth_name": "Impa",
            "address_supplement2": None,
            "address2": None,
            "postal_code2": None,
            "location2": None,
            "country2": None,
            "weblink": None,
            "specialisation": "foo",
            "affiliation": "bar",
            "timeline": "baz",
            "interests": "thud",
            "free_form": "stuff",
            "trial_member": True,
        }
        new_id = self.cde.create_user(self.key, user_data)
        value = self.cde.get_data_one(self.key, new_id)
        user_data.update({
            'id': new_id,
            'db_privileges': 0,
            'balance': decimal.Decimal('0.00'),
            'bub_search': False,
            'decided_search': False,
            "gender": 0,
            "status": 0,
        })
        self.assertEqual(user_data, value)


    @as_users("anton")
    def test_demotion(self, user):
        self.assertLess(
            0, self.cde.change_user(
                self.key, {'id': 2, 'status': const.PersonaStati.formermember},
                None))

    @as_users("anton")
    def test_lastschrift(self, user):
        expectation = {2: 2}
        self.assertEqual(expectation, self.cde.list_lastschrift(self.key))
        expectation = {1: 2, 2: 2}
        self.assertEqual(expectation, self.cde.list_lastschrift(self.key,
                                                                active=None))
        self.assertEqual({1: 2}, self.cde.list_lastschrift(self.key, active=False))
        expectation = {
            2: {'account_address': 'Im Geldspeicher 1',
            'account_owner': 'Dagobert Anatidae',
            'amount': decimal.Decimal('42.23'),
            'granted_at': datetime.datetime(2002, 2, 22, 20, 22, 22, 222222,
                                            tzinfo=pytz.utc),
            'iban': 'DE12500105170648489890',
            'id': 2,
            'max_dsa': decimal.Decimal('0.40'),
            'notes': 'reicher Onkel',
            'persona_id': 2,
            'revoked_at': None,
            'submitted_by': 1}}
        self.assertEqual(expectation, self.cde.get_lastschrift(self.key, (2,)))
        update = {
            'id': 2,
            'notes': 'ehem. reicher Onkel',
            'revoked_at': datetime.datetime.now(pytz.utc),
        }
        self.assertLess(0, self.cde.set_lastschrift(self.key, update))
        expectation[2].update(update)
        self.assertEqual(expectation, self.cde.get_lastschrift(self.key, (2,)))
        self.assertEqual({}, self.cde.list_lastschrift(self.key))
        self.assertEqual({1: 2, 2: 2}, self.cde.list_lastschrift(self.key, active=False))
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'max_dsa': decimal.Decimal('0.33'),
            'notes': None,
            'persona_id': 3,
        }
        new_id = self.cde.create_lastschrift(self.key, newdata)
        self.assertLess(0, new_id)
        self.assertEqual({new_id: 3}, self.cde.list_lastschrift(self.key))
        newdata.update({
            'id': new_id,
            'revoked_at': None,
            'submitted_by': 1,
        })
        self.assertEqual({new_id: newdata},
                         self.cde.get_lastschrift(self.key, (new_id,)))

    @as_users("anton")
    def test_lastschrift_transaction(self, user):
        expectation = {1: 1, 2: 1, 3: 2}
        self.assertEqual(expectation,
                         self.cde.list_lastschrift_transactions(self.key))
        expectation = {1: 1, 3: 2}
        self.assertEqual(
            expectation, self.cde.list_lastschrift_transactions(
                self.key, lastschrift_ids=(1, 2), periods=(41,),
                stati=(const.LastschriftTransactionStati.success,
                       const.LastschriftTransactionStati.cancelled,)))
        expectation = {
            1: {'amount': decimal.Decimal('32.00'),
            'id': 1,
            'issued_at': datetime.datetime(2000, 3, 21, 22, 0, tzinfo=pytz.utc),
            'lastschrift_id': 1,
            'period_id': 41,
            'processed_at': datetime.datetime(2012, 3, 22, 20, 22, 22, 222222,
                                              tzinfo=pytz.utc),
            'status': 12,
            'submitted_by': 1,
            'tally': decimal.Decimal('0.00')}}
        self.assertEqual(expectation,
                         self.cde.get_lastschrift_transactions(self.key, (1,)))
        newdata = {
            'issued_at': datetime.datetime.now(pytz.utc),
            'lastschrift_id': 2,
            'period_id': 43,
        }
        new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
        self.assertLess(0, new_id)
        update = {
            'id': new_id,
            'amount': decimal.Decimal('42.23'),
            'processed_at': None,
            'status': 0,
            'submitted_by': 1,
            'tally': None,
        }
        newdata.update(update)
        self.assertEqual({new_id: newdata},
                         self.cde.get_lastschrift_transactions(self.key, (new_id,)))

    @as_users("anton")
    def test_lastschrift_transaction_finalization(self, user):
        ltstati = const.LastschriftTransactionStati
        for status, tally in ((ltstati.success, None),
                              (ltstati.cancelled, None),
                              (ltstati.failure, decimal.Decimal("-4.50"))):
            with self.subTest(status=status):
                newdata = {
                    'issued_at': datetime.datetime.now(pytz.utc),
                    'lastschrift_id': 2,
                    'period_id': 43,
                }
                new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
                self.assertLess(0, new_id)
                update = {
                    'id': new_id,
                    'amount': decimal.Decimal('42.23'),
                    'processed_at': None,
                    'status': 0,
                    'submitted_by': 1,
                    'tally': None,
                }
                newdata.update(update)
                self.assertEqual(
                    {new_id: newdata}, self.cde.get_lastschrift_transactions(
                        self.key, (new_id,)))
                self.assertLess(
                    0, self.cde.finalize_lastschrift_transaction(
                        self.key, new_id, status, tally=tally))
                data = self.cde.get_lastschrift_transactions(self.key, (new_id,))
                data = data[new_id]
                self.assertEqual(status, data['status'])
                if status == ltstati.success:
                    self.assertEqual(decimal.Decimal('42.23'), data['tally'])
                elif status == ltstati.cancelled:
                    self.assertEqual(decimal.Decimal('0'), data['tally'])
                elif status == ltstati.failure:
                    self.assertEqual(decimal.Decimal('-4.50'), data['tally'])

    @as_users("anton")
    def test_lastschrift_transaction_rollback(self, user):
        ltstati = const.LastschriftTransactionStati
        newdata = {
            'issued_at': datetime.datetime.now(pytz.utc),
            'lastschrift_id': 2,
            'period_id': 43,
        }
        new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
        self.assertLess(0, new_id)
        update = {
            'id': new_id,
            'amount': decimal.Decimal('42.23'),
            'processed_at': None,
            'status': 0,
            'submitted_by': 1,
            'tally': None,
        }
        newdata.update(update)
        self.assertEqual(
            {new_id: newdata}, self.cde.get_lastschrift_transactions(
                self.key, (new_id,)))
        self.assertLess(
            0, self.cde.finalize_lastschrift_transaction(
                self.key, new_id, ltstati.success))
        self.assertLess(
            0, self.cde.rollback_lastschrift_transaction(
                self.key, new_id, decimal.Decimal('-4.50')))
        data = self.cde.get_lastschrift_transactions(self.key, (new_id,))
        data = data[new_id]
        self.assertEqual(ltstati.rollback, data['status'])
        self.assertEqual(decimal.Decimal('-4.50'), data['tally'])

    @as_users("anton")
    def test_skip_lastschrift_transaction(self, user):
        ## Skip testing for successful transaction
        self.assertLess(0, self.cde.lastschrift_skip(self.key, 2))
        ## Skip testing for young permit
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'max_dsa': decimal.Decimal('0.33'),
            'notes': None,
            'persona_id': 3,
        }
        new_id = self.cde.create_lastschrift(self.key, newdata)
        self.assertLess(0, new_id)
        self.assertLess(0, self.cde.lastschrift_skip(self.key, new_id))

    @as_users("anton")
    def test_cde_meta_info(self, user):
        expectation = {
            'Finanzvorstand_Adresse_Einzeiler':
                'Bertålotta Beispiel, bei Spielmanns, Im Garten 77, 34576 Utopia',
            'Finanzvorstand_Adresse_Zeile2': 'bei Spielmanns',
            'Finanzvorstand_Adresse_Zeile3': 'Im Garten 77',
            'Finanzvorstand_Adresse_Zeile4': '34576 Utopia',
            'Finanzvorstand_Name': 'Bertålotta Beispiel',
            'Finanzvorstand_Ort': 'Utopia',
            'Finanzvorstand_Vorname': 'Bertålotta'}
        self.assertEqual(expectation, self.cde.get_meta_info(self.key))
        update = {
            'Finanzvorstand_Name': 'Zelda'
        }
        self.assertLess(0, self.cde.set_meta_info(self.key, update))
        expectation.update(update)
        self.assertEqual(expectation, self.cde.get_meta_info(self.key))

    @as_users("anton")
    def test_cde_log(self, user):
        ## first generate some data
        new_foto = "rkorechkorekchoreckhoreckhorechkrocehkrocehk"
        self.cde.set_foto(self.key, 2, new_foto)
        # TODO more when available

        ## now check it
        expectation = (
            {'additional_info': None,
             'code': 0,
             'ctime': nearly_now(),
             'persona_id': 2,
             'submitted_by': 1},)
        self.assertEqual(expectation, self.cde.retrieve_cde_log(self.key))

    @as_users("anton")
    def test_changelog_meta(self, user):
        expectation = (
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 9,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 7,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 6,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 4,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 3,
             'reviewed_by': None,
             'submitted_by': 1},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 2,
             'reviewed_by': None,
             'submitted_by': 2},
            {'change_note': 'Init.',
             'change_status': 1,
             'ctime': nearly_now(),
             'generation': 1,
             'persona_id': 1,
             'reviewed_by': None,
             'submitted_by': 1})
        self.assertEqual(expectation,
                         self.cde.retrieve_changelog_meta(self.key))
