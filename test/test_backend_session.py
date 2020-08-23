#!/usr/bin/env python3
from cdedb.common import User
from test.common import BackendTest, USER_DICT


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
        # Use the default value from `setup_requeststate` here.
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
