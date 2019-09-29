#!/usr/bin/env python3

from cdedb.common import QuotaException
from cdedb.query import QUERY_SPECS, QueryOperators, Query
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
        data = self.core.get_cde_user(self.key, user['id'])
        data['display_name'] = "Zelda"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'telephone'}}
        num = self.core.change_persona(self.key, setter, 1, change_note='note')
        self.assertEqual(1, num)
        new_data = self.core.get_cde_user(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("berta")
    def test_quota(self, user):
        for _ in range(21):
            self.core.get_cde_users(self.key, (1, 2, 6))
        with self.assertRaises(QuotaException):
            self.core.get_cde_users(self.key, (1, 2, 6))

    @as_users("berta")
    def test_displacement(self, user):
        self.assertEqual(
            -1, self.core.change_persona(self.key, {'id': user['id'],
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
        data = self.core.get_cde_user(self.key, user['id'],)
        self.assertEqual(user['family_name'], data['family_name'])
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.core.changelog_resolve_change(self.key, user['id'], 4, ack=True)
        data = self.core.get_cde_user(self.key, user['id'],)
        self.assertEqual("Link", data['family_name'])

    @as_users("berta")
    def test_nack_change(self, user):
        self.assertEqual(
            -1, self.core.change_persona(self.key, {'id': user['id'],
                                                    'family_name': "Link"}, 1))
        self.assertEqual(2, self.core.changelog_get_generation(self.key, user['id']))
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.core.changelog_resolve_change(self.key, user['id'], 2, ack=False)
        self.assertEqual(1, self.core.changelog_get_generation(self.key, user['id']))

    @as_users("anton", "berta")
    def test_get_cde_users(self, user):
        data = self.core.get_cde_users(self.key, (1, 2))
        expectation = {
            1: {
                'address': 'Auf der Düne 42',
                'address2': 'Unter dem Hügel 23',
                'address_supplement': None,
                'address_supplement2': None,
                'affiliation': None,
                'balance': decimal.Decimal('17.50'),
                'birth_name': None,
                'birthday': datetime.date(1991, 3, 30),
                'bub_search': True,
                'country': None,
                'country2': None,
                'decided_search': True,
                'display_name': 'Anton',
                'family_name': 'Administrator',
                'foto': None,
                'free_form': None,
                'gender': 2,
                'given_names': 'Anton Armin A.',
                'id': 1,
                'interests': None,
                'is_active': True,
                'is_admin': True,
                'is_archived': False,
                'is_assembly_admin': True,
                'is_assembly_realm': True,
                'is_cde_admin': True,
                'is_cde_realm': True,
                'is_core_admin': True,
                'is_event_admin': True,
                'is_event_realm': True,
                'is_member': True,
                'is_ml_admin': True,
                'is_ml_realm': True,
                'is_searchable': True,
                'location': 'Musterstadt',
                'location2': 'Hintertupfingen',
                'mobile': None,
                'name_supplement': None,
                'postal_code': '03205',
                'postal_code2': '22335',
                'specialisation': None,
                'telephone': '+49 (234) 98765',
                'timeline': None,
                'title': None,
                'trial_member': False,
                'username': 'anton@example.cde',
                'weblink': None},
            2: {
                'address': 'Im Garten 77',
                'address2': 'Strange Road 9 3/4',
                'address_supplement': 'bei Spielmanns',
                'address_supplement2': None,
                'affiliation': 'Jedermann',
                'balance': decimal.Decimal('12.50'),
                'birth_name': 'Gemeinser',
                'birthday': datetime.date(1981, 2, 11),
                'bub_search': True,
                'country': None,
                'country2': 'Far Away',
                'decided_search': True,
                'display_name': 'Bertå',
                'family_name': 'Beispiel',
                'foto': 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9',
                'free_form': 'Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen',
                'gender': 1,
                'given_names': 'Bertålotta',
                'id': 2,
                'interests': 'Immer',
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
                'location': 'Utopia',
                'location2': 'Foreign City',
                'mobile': '0163/123456789',
                'name_supplement': 'MdB',
                'postal_code': '34576',
                'postal_code2': '8XA 45-$',
                'specialisation': 'Alles\nUnd noch mehr',
                'telephone': '+49 (5432) 987654321',
                'timeline': 'Überall',
                'title': 'Dr.',
                'trial_member': False,
                'username': 'berta@example.cde',
                'weblink': 'https://www.bundestag.cde'}}
        self.assertEqual(expectation, data)
        if user['id'] == 1:
            data = self.core.get_event_users(self.key, (1, 2))
            expectation =  {
                1: {
                    'address': 'Auf der Düne 42',
                    'address_supplement': None,
                    'birthday': datetime.date(1991, 3, 30),
                    'country': None,
                    'display_name': 'Anton',
                    'family_name': 'Administrator',
                    'gender': 2,
                    'given_names': 'Anton Armin A.',
                    'id': 1,
                    'is_active': True,
                    'is_admin': True,
                    'is_archived': False,
                    'is_assembly_admin': True,
                    'is_assembly_realm': True,
                    'is_cde_admin': True,
                    'is_cde_realm': True,
                    'is_core_admin': True,
                    'is_event_admin': True,
                    'is_event_realm': True,
                    'is_member': True,
                    'is_ml_admin': True,
                    'is_ml_realm': True,
                    'is_searchable': True,
                    'location': 'Musterstadt',
                    'mobile': None,
                    'name_supplement': None,
                    'postal_code': '03205',
                    'telephone': '+49 (234) 98765',
                    'title': None,
                    'username': 'anton@example.cde'},
                2: {
                    'address': 'Im Garten 77',
                    'address_supplement': 'bei Spielmanns',
                    'birthday': datetime.date(1981, 2, 11),
                    'country': None,
                    'display_name': 'Bertå',
                    'family_name': 'Beispiel',
                    'gender': 1,
                    'given_names': 'Bertålotta',
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
                    'location': 'Utopia',
                    'mobile': '0163/123456789',
                    'name_supplement': 'MdB',
                    'postal_code': '34576',
                    'telephone': '+49 (5432) 987654321',
                    'title': 'Dr.',
                    'username': 'berta@example.cde'}}
            self.assertEqual(expectation, data)
        expectation = {
            1: {

                'display_name': 'Anton',
                'family_name': 'Administrator',
                'given_names': 'Anton Armin A.',
                'name_supplement': None,
                'title': None,
                'id': 1,
                'is_active': True,
                'is_admin': True,
                'is_archived': False,
                'is_assembly_admin': True,
                'is_assembly_realm': True,
                'is_cde_admin': True,
                'is_cde_realm': True,
                'is_core_admin': True,
                'is_event_admin': True,
                'is_event_realm': True,
                'is_member': True,
                'is_ml_admin': True,
                'is_ml_realm': True,
                'is_searchable': True,
                'username': 'anton@example.cde'},
            2: {
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
                'username': 'berta@example.cde'}}
        data = self.core.get_personas(self.key, (1, 2))
        self.assertEqual(expectation, data)

    @as_users("berta")
    def test_member_search(self, user):
        query = Query(
            scope="qview_cde_member",
            spec=dict(QUERY_SPECS["qview_cde_member"]),
            fields_of_interest=("personas.id", "family_name", "birthday"),
            constraints=[
                ("given_names,display_name", QueryOperators.regex, '[ae]'),
                ("country,country2", QueryOperators.empty, None)],
            order=(("family_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2, 6, 9, 12}, {e['id'] for e in result})

    @as_users("anton")
    def test_user_search(self, user):
        query = Query(
            scope="qview_cde_user",
            spec=dict(QUERY_SPECS["qview_cde_user"]),
            fields_of_interest=("personas.id", "family_name", "birthday"),
            constraints=[
                ("given_names", QueryOperators.regex, '[ae]'),
                ("birthday", QueryOperators.less, datetime.datetime.now())],
            order=(("family_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2, 3, 4, 6, 7}, {e['id'] for e in result})

    @as_users("anton")
    def test_user_search_operators(self, user):
        query = Query(
            scope="qview_cde_user",
            spec=dict(QUERY_SPECS["qview_cde_user"]),
            fields_of_interest=("personas.id", "family_name",
                                   "birthday"),
            constraints=[("given_names", QueryOperators.match, 'Berta'),
                            ("address", QueryOperators.oneof, ("Auf der Düne 42", "Im Garten 77")),
                            ("weblink", QueryOperators.containsall, ("/", ":", "http")),
                            ("birthday", QueryOperators.between, (datetime.datetime(1000, 1, 1),
                                                                        datetime.datetime.now()))],
            order=(("family_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2}, {e['id'] for e in result})

    @as_users("anton")
    def test_demotion(self, user):
        self.assertLess(0, self.core.change_membership(self.key, 2, False))

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
            'notes': 'reicher Onkel',
            'persona_id': 2,
            'revoked_at': None,
            'submitted_by': 1}}
        self.assertEqual(expectation, self.cde.get_lastschrifts(self.key, (2,)))
        update = {
            'id': 2,
            'notes': 'ehem. reicher Onkel',
            'revoked_at': datetime.datetime.now(pytz.utc),
        }
        self.assertLess(0, self.cde.set_lastschrift(self.key, update))
        expectation[2].update(update)
        self.assertEqual(expectation, self.cde.get_lastschrifts(self.key, (2,)))
        self.assertEqual({}, self.cde.list_lastschrift(self.key))
        self.assertEqual({1: 2, 2: 2}, self.cde.list_lastschrift(self.key, active=False))
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
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
                         self.cde.get_lastschrifts(self.key, (new_id,)))

    @as_users("anton")
    def test_lastschrift_multiple_active(self, user):
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'notes': None,
            'persona_id': 3,
        }
        self.cde.create_lastschrift(self.key, newdata)
        with self.assertRaises(ValueError):
            self.cde.create_lastschrift(self.key, newdata)

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
            'status': 1,
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
                    'status': 1,
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
            'status': 1,
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
            'notes': None,
            'persona_id': 3,
        }
        new_id = self.cde.create_lastschrift(self.key, newdata)
        self.assertLess(0, new_id)
        self.assertLess(0, self.cde.lastschrift_skip(self.key, new_id))

    @as_users("anton")
    def test_cde_log(self, user):
        ## first generate some data
        # TODO more when available

        ## now check it
        expectation = tuple()
        self.assertEqual(expectation, self.cde.retrieve_cde_log(self.key))
