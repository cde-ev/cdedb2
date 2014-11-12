#!/usr/bin/env python3

from cdedb.common import QuotaException
from cdedb.query import QUERY_SPECS, QueryOperators
from test.common import BackendTest, as_users, USER_DICT
import decimal
import datetime
import copy

class TestCdEBackend(BackendTest):
    used_backends = ("core", "cde")
    maxDiff = None

    @as_users("anton", "berta")
    def test_basics(self, user):
        data = self.cde.get_data_single(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['birth_name'] = "Hylia"
        setter = {k : v for k, v in data.items() if k in
                  {'id', 'birth_name', 'display_name', 'telephone'}}
        num = self.cde.change_user(self.key, setter, 1)
        self.assertEqual(1, num)
        new_data = self.cde.get_data_single(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("berta")
    def test_quota(self, user):
        for _ in range(25):
            self.cde.get_data(self.key, (1, 2, 3))
        with self.assertRaises(QuotaException):
            self.cde.get_data(self.key, (1, 2, 3))

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user):
        newaddress = "newaddress@example.cde"
        token = self.core.change_username_token(self.key, user['id'], newaddress, user['password'])
        ret, _ = self.cde.change_username(self.key, user['id'], newaddress, token)
        self.assertTrue(ret)
        self.core.logout(self.key)
        self.key = None
        self.login(user)
        self.assertEqual(None, self.key)
        newuser = copy.deepcopy(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.key)

    @as_users("berta")
    def test_displacement(self, user):
        self.assertEqual(
            -1, self.cde.change_user(self.key, {'id' : user['id'],
                                                'family_name' : "Link"}, 1))
        newaddress = "newaddress@example.cde"
        token = self.core.change_username_token(self.key, user['id'],
                                                newaddress, user['password'])
        ret, _ = self.cde.change_username(self.key, user['id'], newaddress, token)
        self.assertTrue(ret)
        self.core.logout(self.key)
        self.key = None
        self.login(user)
        self.assertEqual(None, self.key)
        newuser = copy.deepcopy(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.key)
        data = self.cde.get_data_single(self.key, user['id'],)
        self.assertEqual(user['family_name'], data['family_name'])
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.cde.resolve_change(self.key, user['id'], 4, ack=True)
        data = self.cde.get_data_single(self.key, user['id'],)
        self.assertEqual("Link", data['family_name'])

    @as_users("berta")
    def test_nack_change(self, user):
        self.assertEqual(
            -1, self.cde.change_user(self.key, {'id' : user['id'],
                                                'family_name' : "Link"}, 1))
        self.assertEqual(2, self.cde.get_generation(self.key, user['id']))
        self.core.logout(self.key)
        self.login(USER_DICT['anton'])
        self.cde.resolve_change(self.key, user['id'], 2, ack=False)
        self.assertEqual(1, self.cde.get_generation(self.key, user['id']))

    @as_users("anton", "berta")
    def test_get_data(self, user):
        data = self.cde.get_data(self.key, (1, 2))
        expectation = {1 : {
            'bub_search': True,
            'location': 'Musterstadt',
            'cloud_account': True,
            'specialisation': None,
            'id': 1,
            'address_supplement': '',
            'username': 'anton@example.cde',
            'affiliation': None,
            'interests': None,
            'location2': 'Hintertupfingen',
            'birth_name': None,
            'weblink': None,
            'balance': decimal.Decimal('17.50'),
            'decided_search': True,
            'timeline': None,
            'address_supplement2': '',
            'given_names': 'Anton Armin A.',
            'address': 'Auf der Düne 42',
            'status': 0,
            'db_privileges': 1,
            'gender': 1,
            'title': '',
            'mobile': '',
            'country': '',
            'country2': '',
            'family_name': 'Administrator',
            'trial_member': False,
            'display_name': 'Anton',
            'name_supplement': '',
            'notes': '',
            'telephone': '+49 (234) 98765',
            'address2': 'Unter dem Hügel 23',
            'postal_code': '03205',
            'free_form': None,
            'is_active': True,
            'postal_code2': '22335',
            'birthday': datetime.datetime(1991, 3, 30).date()},
            2 : {'bub_search': True,
            'location': 'Utopia',
            'cloud_account': True,
            'specialisation': 'Alles',
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
            'address_supplement2': '',
            'given_names': 'Bertålotta',
            'address': 'Im Garten 77',
            'status': 0,
            'db_privileges': 0,
            'gender': 0,
            'title': 'Dr.',
            'mobile': '0163/123456789',
            'country': '',
            'country2': 'Far Away',
            'family_name': 'Beispiel',
            'trial_member': False,
            'display_name': 'Bertå',
            'name_supplement': 'MdB',
            'notes': '',
            'telephone': '+49 (5432) 987654321',
            'address2': 'Strange Road 9 3/4',
            'postal_code': '34576',
            'free_form': 'Jede Menge Gefasel',
            'is_active': True,
            'postal_code2': '8XA 45-$',
            'birthday': datetime.datetime(1981, 2, 11).date()}}
        self.assertEqual(expectation, data)

    @as_users("berta")
    def test_member_search(self, user):
        query = {
            "scope" : "qview_cde_member",
            "spec" : dict(QUERY_SPECS["qview_cde_member"]),
            "fields_of_interest" : ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints" : (("given_names,display_name", QueryOperators.regex.value, '[ae]'),
                             ("country,country2", QueryOperators.empty.value, None)),
            "order" : ("family_name",),
        }
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({1, 2, 6}, {e['persona_id'] for e in result})

    @as_users("anton")
    def test_user_search(self, user):
        query = {
            "scope" : "qview_cde_user",
            "spec" : dict(QUERY_SPECS["qview_cde_user"]),
            "fields_of_interest" : ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints" : (("given_names", QueryOperators.regex.value, '[ae]'),
                             ("birthday", QueryOperators.less.value, datetime.datetime.now())),
            "order" : ("family_name",),
        }
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({1, 2, 3, 4, 6, 7}, {e['persona_id'] for e in result})

    @as_users("anton")
    def test_user_search_operators(self, user):
        query = {
            "scope" : "qview_cde_user",
            "spec" : dict(QUERY_SPECS["qview_cde_user"]),
            "fields_of_interest" : ("member_data.persona_id", "family_name",
                                    "birthday"),
            "constraints" : (("given_names", QueryOperators.similar.value, 'Berta'),
                             ("address", QueryOperators.oneof.value, ("Auf der Düne 42", "Im Garten 77")),
                             ("weblink", QueryOperators.containsall.value, ("/", ":", "http")),
                             ("birthday", QueryOperators.between.value, (datetime.datetime(1000, 1, 1),
                                                                         datetime.datetime.now()))),
            "order" : ("family_name",),
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
