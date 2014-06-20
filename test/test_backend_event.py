#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT

class TestCdEBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self, user):
        data = self.event.get_data(self.key, (user['id'],))[0]
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k : v for k, v in data.items() if k in set(
            ('id', 'name_supplement', 'display_name', 'telephone'))}
        self.event.change_user(self.key, setter)
        new_data = self.event.get_data(self.key, (user['id'],))[0]
        self.assertEqual(data, new_data)
