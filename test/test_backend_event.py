#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT

class TestCdEBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self, user):
        data = self.event.get_data(self.key, (user['id'],))[user['id']]
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k : v for k, v in data.items() if k in
                  {'id', 'name_supplement', 'display_name', 'telephone'}}
        self.event.change_user(self.key, setter)
        new_data = self.event.get_data(self.key, (user['id'],))[user['id']]
        self.assertEqual(data, new_data)

    @as_users("anton", "berta")
    def test_participation_info(self, user):
        participation_info = self.event.participation_info(self.key, (1, 2))
        expectation = {1 : tuple(),
                       2 : ({'persona_id': 2,
                             'is_orga': False,
                             'is_instructor': True,
                             'course_name': 'Swish -- und alles ist gut',
                             'event_id': 1,
                             'event_name': 'PfingstAkademie 2014',
                             'course_id': 1},)}
        self.assertEqual(expectation, participation_info)

