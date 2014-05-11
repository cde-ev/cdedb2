#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT
import copy

class TestCoreBackend(BackendTest):
    used_backends = ("core",)

    def test_login(self):
        for i, u in enumerate(("anton", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                key = self.core.login(None, user['username'], user['password'],
                                      "0.0.0.0")
                self.assertIsInstance(key, str)
                self.assertTrue(key)

                key = self.core.login(None, user['username'], "wrong key",
                                      "0.0.0.0")
                self.assertEqual(None, key)

    @as_users("anton", "berta", "emilia")
    def test_logout(self, user):
        self.assertTrue(self.key)
        self.assertEqual(1, self.core.logout(self.key))
        with self.assertRaises(RuntimeError):
            self.core.logout(self.key)

    @as_users("anton", "berta", "emilia")
    def test_change_persona(self, user):
        new_name = "Zelda"
        self.core.change_persona(self.key, {'id' : user['id'],
                                            'display_name' : new_name})
        self.assertEqual(new_name, self.core.retrieve_persona_data(
            self.key, (user['id'],))[0]['display_name'])

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
    def test_change_username(self, user):
        newaddress = "newaddress@example.cde"
        ret = self.core.change_username(self.key, user['id'], newaddress, "wrongpass")
        self.assertEqual(ret, (False, "Failed."))
        ret = self.core.change_username(self.key, user['id'], newaddress, user['password'])
        self.assertTrue(ret)
        self.core.logout(self.key)
        self.key = None
        self.login(user)
        self.assertEqual(None, self.key)
        newuser = copy.deepcopy(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.key)
