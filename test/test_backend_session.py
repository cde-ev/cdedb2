#!/usr/bin/env python3
from cdedb.common import User
from test.common import BackendTest, USER_DICT

class TestSessionBackend(BackendTest):
    used_backends = ("core", "session")

    def test_sessionlookup(self):
        user = self.session.lookupsession("random key", "127.0.0.0")
        self.assertIsNone(user['persona_id'])
        self.assertEqual(False, user['is_active'])
        key = self.login(USER_DICT["anton"])
        user = self.session.lookupsession(key, "127.0.0.0")
        self.assertIsInstance(user, User)
        self.assertTrue(user.persona_id)

    def test_ip_mismatch(self):
        key = self.login(USER_DICT["anton"], ip="1.2.3.4")
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertIsInstance(user, User)
        self.assertTrue(user.persona_id)
        user = self.session.lookupsession(key, "4.3.2.1")
        self.assertEqual(None, user.persona_id)
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertEqual(None, user.persona_id)
