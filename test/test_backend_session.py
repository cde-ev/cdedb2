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
        ip1 = ip2 = "127.0.0.0"
        ip3 = "4.3.2.1"
        key1 = self.login(USER_DICT["anton"], ip=ip1)
        key2 = self.login(USER_DICT["anton"], ip=ip2)
        key3 = self.login(USER_DICT["anton"], ip=ip3)
        user1 = self.session.lookupsession(key1, ip1)
        self.assertIsInstance(user1, User)
        self.assertTrue(user1.persona_id)
        user2 = self.session.lookupsession(key2, ip2)
        self.assertIsInstance(user2, User)
        self.assertTrue(user2.persona_id)
        user3 = self.session.lookupsession(key3, ip3)
        self.assertIsInstance(user3, User)
        self.assertTrue(user3.persona_id)
        self.assertNotEqual(user1, user2)
        self.assertNotEqual(user1, user3)
        self.assertNotEqual(user2, user3)
        self.assertEqual(user1.__dict__, user2.__dict__)
        self.assertEqual(user1.__dict__, user3.__dict__)
        self.assertEqual(user2.__dict__, user3.__dict__)

        self.core.logout(key1)
        self.assertEqual(
            {"anonymous"},
            self.session.lookupsession(key1, ip1).roles)
        self.assertEqual(
            user2.__dict__,
            self.session.lookupsession(key2, ip2).__dict__)
        self.assertEqual(
            user3.__dict__,
            self.session.lookupsession(key3, ip3).__dict__)
        self.core.logout(key2, all_sessions=True)
        self.assertEqual(
            {"anonymous"},
            self.session.lookupsession(key2, ip2).roles)
        self.assertEqual(
            {"anonymous"},
            self.session.lookupsession(key3, ip3).roles)
