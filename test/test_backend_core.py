#!/usr/bin/env python3

import cdedb.database.constants as const
from test.common import BackendTest, as_users, USER_DICT, nearly_now
import copy
import subprocess
import ldap

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
    def test_set_persona_data(self, user):
        new_name = "Zelda"
        self.core.set_persona_data(self.key, {'id': user['id'],
                                              'display_name': new_name})
        self.assertEqual(new_name, self.core.retrieve_persona_data_one(
            self.key, user['id'])['display_name'])

    @as_users("anton", "berta")
    def test_change_password(self, user):
        ret, _ = self.core.change_password(self.key, user['id'], user['password'], "weakpass")
        self.assertFalse(ret)
        newpass = "er3NQ_5bkrc#"
        ret, message = self.core.change_password(self.key, user['id'], user['password'], newpass)
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

    def test_verify_existence(self):
        self.assertTrue(self.core.verify_existence(self.key, "anton@example.cde"))
        self.assertFalse(self.core.verify_existence(self.key, "nonexistent@example.cde"))

    def test_password_reset(self):
        ret, _ = self.core.reset_password(self.key, "berta@example.cde")
        self.assertTrue(ret)
        ret, _ = self.core.reset_password(self.key, "anton@example.cde")
        self.assertFalse(ret)
        ret, _ = self.core.reset_password(self.key, "nonexistant@example.cde")
        self.assertFalse(ret)

    @as_users("anton", "berta")
    def test_ldap(self, user):
        new_name = "Zelda"
        new_address = "zelda@example.cde"
        newpass = "er3NQ_5bkrc#"
        dn = "uid={},{}".format(user['id'], "ou=personas-test,dc=cde-ev,dc=de")
        ret, message = self.core.change_password(self.key, user['id'], user['password'], newpass)
        self.assertTrue(ret)
        self.assertEqual(newpass, message)
        self.assertEqual(
            "dn:{}\n".format(dn).encode('utf-8'), subprocess.check_output(
            ['/usr/bin/ldapwhoami', '-x', '-D', dn, '-w', newpass]))
        update = {
            'id': user['id'],
            'display_name': new_name,
            'username': new_address,
        }
        if user['id'] == 1:
            update['cloud_account'] = False
        self.core.set_persona_data(self.key, update, allow_username_change=True)
        ldap_con = ldap.initialize("ldap://localhost")
        ldap_con.simple_bind_s("cn=root,dc=cde-ev,dc=de",
                               "s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0")
        val = ldap_con.search_s("ou=personas-test,dc=cde-ev,dc=de",
                                ldap.SCOPE_ONELEVEL,
                                filterstr='(uid={})'.format(user['id']),
                                attrlist=['cn', 'displayName', 'mail',
                                          'cloudAccount'])
        cloud_expectation = b'TRUE'
        if user['id'] == 1:
            cloud_expectation = b'FALSE'
        expectation = [(
            dn, {'cn': [new_name.encode('utf-8')],
                 'displayName': [new_name.encode('utf-8')],
                 'mail': [new_address.encode('utf-8')],
                 'cloudAccount': [cloud_expectation],})]
        self.assertEqual(expectation, val)
        ldap_con.unbind()

    @as_users("anton")
    def test_create_persona(self, user):
        data = {
            "username": 'zelda@example.cde',
            "display_name": 'Zelda',
            "is_active": True,
            "status": 1,
            "cloud_account": True,
            "db_privileges": 0,
        }
        new_id = self.core.create_persona(self.key, data)
        data["id"] = new_id
        self.assertGreater(new_id, 0)
        new_data = self.core.get_data_one(self.key, new_id)
        self.assertEqual(data, new_data)
        ldap_con = ldap.initialize("ldap://localhost")
        ldap_con.simple_bind_s("cn=root,dc=cde-ev,dc=de",
                               "s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0")
        val = ldap_con.search_s("ou=personas-test,dc=cde-ev,dc=de",
                                ldap.SCOPE_ONELEVEL,
                                filterstr='(uid={})'.format(new_id),
                                attrlist=['cn', 'displayName', 'mail',
                                          'cloudAccount', 'isActive'])
        dn = "uid={},{}".format(new_id, "ou=personas-test,dc=cde-ev,dc=de")
        expectation = [(
            dn, {'cn': [data['display_name'].encode('utf-8')],
                 'displayName': [data['display_name'].encode('utf-8')],
                 'mail': [data['username'].encode('utf-8')],
                 'cloudAccount': [b"TRUE"],
                 'isActive': [b"TRUE"]})]
        self.assertEqual(expectation, val)
        ldap_con.unbind()

    @as_users("anton")
    def test_genesis(self, user):
        data = {
            "full_name": "Zelda",
            "username": 'zelda@example.cde',
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(
            None, data['username'], data['full_name'], data['notes'])
        self.assertGreater(case_id, 0)
        self.assertEqual(1, self.core.genesis_verify(None, case_id))
        self.assertEqual(1, len(self.core.genesis_list_cases(
            self.key, stati=(const.GenesisStati.to_review,))))
        expectation = data
        expectation.update({
            'id': case_id,
            'persona_status': None,
            'case_status': const.GenesisStati.to_review,
            'secret': None,
            'reviewer': None,
        })
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)
        update = {
            'id': case_id,
            'persona_status': const.PersonaStati.event_user,
            'case_status': const.GenesisStati.approved,
            'secret': "foobar",
            'reviewer': 1,
        }
        self.assertEqual(1, self.core.genesis_modify_case(self.key, update))
        expectation.update(update)
        value = self.core.genesis_get_case(self.key, case_id)
        del value['ctime']
        self.assertEqual(expectation, value)

    @as_users("anton")
    def test_verify_personas(self, user):
        self.assertEqual(
            {1, 2, 4, 5, 6},
            set(self.core.verify_personas(self.key, (1, 2, 3, 4, 5, 6, 7, 8, 1000), (0, 2, 20))))

    @as_users("anton")
    def test_log(self, user):
        ## first generate some data
        data = {
            "username": 'zelda@example.cde',
            "display_name": 'Zelda',
            "is_active": True,
            "status": 1,
            "cloud_account": True,
            "db_privileges": 0,
        }
        self.core.create_persona(self.key, data)
        data = {
            "full_name": "Zelda",
            "username": 'zeldax@example.cde',
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(
            None, data['username'], data['full_name'], data['notes'])
        update = {
            'id': case_id,
            'persona_status': const.PersonaStati.event_user,
            'case_status': const.GenesisStati.approved,
            'secret': "foobar",
            'reviewer': 1,
        }
        self.core.genesis_modify_case(self.key, update)
        newpass = "er3NQ_5bkrc#"
        self.core.change_password(self.key, user['id'], user['password'], newpass)

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
             'code': 0,
             'ctime': nearly_now(),
             'persona_id': 11,
             'submitted_by': 1})
        self.assertEqual(expectation, self.core.retrieve_log(self.key))
