#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT

class TestCdEBackend(BackendTest):
    used_backends = ("core", "cde")
    maxDiff = None

    @as_users("anton", "berta")
    def test_basics(self, user):
        data = self.cde.get_data(self.key, (user['id'],))[0]
        data['display_name'] = "Zelda"
        data['birth_name'] = "Hylia"
        setter = {k : v for k, v in data.items() if k in set(
            ('id', 'birth_name', 'display_name', 'telephone'))}
        self.cde.change_member(self.key, setter)
        new_data = self.cde.get_data(self.key, (user['id'],))[0]
        self.assertEqual(new_data, data)
