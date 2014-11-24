#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT
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
        self.core.set_persona_data(self.key, {'id' : user['id'],
                                              'display_name' : new_name})
        self.assertEqual(new_name, self.core.retrieve_persona_data_single(
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
            'id' : user['id'],
            'display_name' : new_name,
            'username' : new_address,
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
            dn, {'cn' : [new_name.encode('utf-8')],
                 'displayName' : [new_name.encode('utf-8')],
                 'mail' : [new_address.encode('utf-8')],
                 'cloudAccount' : [cloud_expectation],})]
        self.assertEqual(expectation, val)
        ldap_con.unbind()
