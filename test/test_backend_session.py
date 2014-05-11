#!/usr/bin/env python3

from test.common import BackendTest, USER_DICT

class TestSessionBackend(BackendTest):
    used_backends = ("core", "session")

    def test_sessionlookup(self):
        data = self.session.lookupsession("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", "random key", "0.0.0.0")
        self.assertEqual(None, data['persona_id'])
        self.assertEqual(None, data['db_privileges'])
        key = self.login(USER_DICT["anton"])
        data = self.session.lookupsession("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", key, "0.0.0.0")
        self.assertIsInstance(data, dict)
        self.assertTrue(data['persona_id'])
        self.assertIsInstance(data['db_privileges'], int)

    def test_ip_mismatch(self):
        key = self.login(USER_DICT["anton"], ip="1.2.3.4")
        data = self.session.lookupsession("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", key, "1.2.3.4")
        self.assertIsInstance(data, dict)
        self.assertTrue(data['persona_id'])
        data = self.session.lookupsession("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", key, "4.3.2.1")
        self.assertEqual(None, data['persona_id'])
        data = self.session.lookupsession("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", key, "1.2.3.4")
        self.assertEqual(None, data['persona_id'])
