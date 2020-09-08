#!/usr/bin/env python3
from cdedb.common import User
from test.common import BackendTest, USER_DICT, MultiAppFrontendTest


class TestSessionBackend(BackendTest):
    used_backends = ("core", "session")

    def test_sessionlookup(self):
        user = self.session.lookupsession("random key", "127.0.0.0")
        self.assertIsNone(user.persona_id)
        self.assertEqual({"anonymous"}, user.roles)
        key = self.login(USER_DICT["anton"])
        user = self.session.lookupsession(key, "127.0.0.0")
        self.assertIsInstance(user, User)
        self.assertEqual(USER_DICT["anton"]['id'], user.persona_id)

    def test_ip_mismatch(self):
        key = self.login(USER_DICT["anton"], ip="1.2.3.4")
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertIsInstance(user, User)
        self.assertTrue(user.persona_id)
        user = self.session.lookupsession(key, "4.3.2.1")
        self.assertEqual(None, user.persona_id)
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertEqual(None, user.persona_id)

    def test_multiple_sessions(self):
        # Logging out only works with the ip "127.0.0.0", which is the
        # default value from `setup_requeststate`.
        ips = ["127.0.0.0", "4.3.2.1", "127.0.0.0"]
        keys = []
        users = []
        for ip in ips:
            keys.append(self.login(USER_DICT["anton"], ip=ip))
            users.append(self.session.lookupsession(keys[-1], ip))
            self.assertIsInstance(users[-1], User)
            self.assertTrue(users[-1].persona_id)
        for i, user in enumerate(users[:-1]):
            self.assertNotEqual({"anonymous"}, user.roles)
            self.assertNotEqual(user, users[i+1])
            self.assertEqual(user.__dict__, users[i+1].__dict__)

        # Terminate a single session.
        self.core.logout(keys[0])
        # Check termination.
        self.assertEqual(
            {"anonymous"},
            self.session.lookupsession(keys[0], ips[0]).roles)
        # Check that other sessions are untouched.
        for i in (1, 2):
            self.assertEqual(
                users[i].__dict__,
                self.session.lookupsession(keys[i], ips[i]).__dict__)

        # Terminate all sessions.
        self.core.logout(keys[2], all_sessions=True)
        # Check that all sessions have been terminated.
        for i in (0, 1, 2):
            self.assertEqual(
                {"anonymous"},
                self.session.lookupsession(keys[i], ips[i]).roles)

    def test_max_active_sessions(self):
        user_data = USER_DICT["anton"]
        ip = "1.2.3.4"
        # Create and check the maximum number of allowed sessions.
        keys = [self.login(user_data, ip=ip)
                for _ in range(self.conf["MAX_ACTIVE_SESSIONS"])]
        for i, key in enumerate(keys):
            with self.subTest(i=i, key=key):
                user = self.session.lookupsession(key, ip=ip)
                self.assertEqual(user.persona_id, user_data['id'])
                self.assertLess({"anonymous"}, user.roles)
        # Create another session and check it.
        keys.append(self.login(user_data, ip=ip))
        user = self.session.lookupsession(keys[-1], ip=ip)
        self.assertEqual(user.persona_id, user_data['id'])
        self.assertLess({"anonymous"}, user.roles)
        # Check that the oldest session has now been terminated.
        user = self.session.lookupsession(keys[0], ip=ip)
        self.assertIsNone(user.persona_id)
        self.assertEqual({"anonymous"}, user.roles)


class TestMultiSessionFrontend(MultiAppFrontendTest):
    n = 3  # Needs to be at least 3 for the following test to work correctly.

    def test_logout_all(self):
        self.assertGreaterEqual(self.n, 3, "This test will only work correctly"
                                           " with 3 or more apps.")

        user = USER_DICT["anton"]
        session_cookie = "sessionkey"

        # Set up multiple sessions.
        keys = []
        for i in range(self.n):
            self.switch_app(i)
            self.login(user)
            keys.append(self.app.cookies[session_cookie])
            # Check that we are correctly logged in.
            self.get("/core/self/show")
            self.assertTitle(f"{user['given_names']} {user['family_name']}")
            self.assertNotIn('loginform', self.response.forms)
        self.assertEqual(len(set(keys)), len(keys))

        # Terminate session 0.
        self.switch_app(0)
        self.logout()
        self.get("/core/self/show")
        self.assertTitle("CdE-Datenbank")
        self.assertIn('loginform', self.response.forms)
        # Check that other sessions are still active.
        for i in range(1, self.n):
            self.switch_app(i)
            with self.subTest(app_index=i):
                self.get("/core/self/show")
                self.assertTitle(f"{user['given_names']} {user['family_name']}")
                self.assertNotIn('loginform', self.response.forms)

        # Now terminate all sessions and check that they are all inactive.
        self.switch_app(self.n - 1)
        f = self.response.forms['logoutallform']
        self.submit(f)
        self.assertPresence(f"{self.n - 1} Sitzung(en) beendet.",
                            div="notifications")
        for i in range(self.n):
            self.switch_app(i)
            with self.subTest(app_index=i):
                self.get("/core/self/show")
                self.assertTitle("CdE-Datenbank")
                self.assertIn('loginform', self.response.forms)

    def test_basics(self):
        self.login(USER_DICT["anton"])
        self.switch_app(1)
        self.login(USER_DICT["berta"])
        self.switch_app(0)
        self.assertLogin(USER_DICT["anton"]["display_name"])
        self.switch_app(1)
        self.assertLogin(USER_DICT["berta"]["display_name"])
        self.logout()
        self.assertIn('loginform', self.response.forms)
        self.switch_app(0)
        self.assertLogin(USER_DICT["anton"]["display_name"])
