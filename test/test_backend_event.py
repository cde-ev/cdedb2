#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT
import cdedb.database.constants as const
import datetime

class TestEventBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self, user):
        data = self.event.get_data_single(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'name_supplement', 'display_name', 'telephone'}}
        self.event.change_user(self.key, setter)
        new_data = self.event.get_data_single(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("anton", "berta")
    def test_participation_infos(self, user):
        participation_infos = self.event.participation_infos(self.key, (1, 2))
        expectation = {1: tuple(),
                       2: ({'persona_id': 2,
                             'is_orga': False,
                             'is_instructor': True,
                             'course_name': 'Swish -- und alles ist gut',
                             'event_id': 1,
                             'event_name': 'PfingstAkademie 2014',
                             'course_id': 1},)}
        self.assertEqual(expectation, participation_infos)
        participation_info = self.event.participation_info(self.key, 1)
        participation_infos = self.event.participation_infos(self.key, (1,))
        self.assertEqual(participation_infos[1], participation_info)

    @as_users("anton")
    def test_genesis(self, user):
        data = {
            "full_name": "Zelda",
            "username": 'zelda@example.cde',
            "notes": "Some blah",
        }
        case_id = self.core.genesis_request(
            None, data['username'], data['full_name'], data['notes'])
        self.core.genesis_verify(None, case_id)
        update = {
            'id': case_id,
            'persona_status': const.PersonaStati.event_user,
            'case_status': const.GenesisStati.approved,
            'secret': "foobar",
        }
        self.core.genesis_modify_case(self.key, update)
        self.assertTrue(self.event.genesis_check(
            None, case_id, update['secret']))
        self.assertFalse(self.event.genesis_check(None, case_id, "wrong"))
        user_data = {
            "username": 'zelda@example.cde',
            "display_name": 'Zelda',
            "is_active": True,
            "status": const.PersonaStati.event_user,
            "cloud_account": True,
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "title": None,
            "name_supplement": None,
            "gender": const.Genders.female,
            "birthday": datetime.date(1987, 6, 5),
            "telephone": None,
            "mobile": None,
            "address_supplement": None,
            "address": "Street 7",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
            "notes": None,
        }
        new_id = self.event.genesis(None, case_id, update['secret'], user_data)
        value = self.event.get_data_single(self.key, new_id)
        user_data.update({
            'id': new_id,
            'db_privileges': 0,
            "gender": 0,
            "status": 20,
        })
        self.assertEqual(user_data, value)
