#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT
import cdedb.database.constants as const
import datetime
import decimal

class TestEventBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self, user):
        data = self.event.get_data_one(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'name_supplement', 'display_name', 'telephone'}}
        self.event.change_user(self.key, setter)
        new_data = self.event.get_data_one(self.key, user['id'])
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
        value = self.event.get_data_one(self.key, new_id)
        user_data.update({
            'id': new_id,
            'db_privileges': 0,
            "gender": 0,
            "status": 20,
        })
        self.assertEqual(user_data, value)

    @as_users("anton")
    def test_entity_past_event(self, user):
        old_events = self.event.list_events(self.key, past=True)
        data = {
            'title': "New Link Academy",
            'organizer': "Illuminati",
            'description': """Some more text

            on more lines.""",
        }
        new_id = self.event.create_past_event(self.key, data)
        data['id'] = new_id
        self.assertEqual(data,
                         self.event.get_past_event_data_one(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        self.event.set_past_event_data(self.key, {
            'id': new_id, 'title': data['title']})
        self.assertEqual(data,
                         self.event.get_past_event_data_one(self.key, new_id))
        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_events(self.key, past=True)
        self.assertIn(new_id, new_events)

    @as_users("anton")
    def test_entity_past_course(self, user):
        event_id = 1
        old_courses = self.event.list_courses(self.key, event_id, past=True)
        data = {
            'event_id': event_id,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
        }
        new_id = self.event.create_past_course(self.key, data)
        data['id'] = new_id
        self.assertEqual(data,
                         self.event.get_past_course_data_one(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        self.event.set_past_course_data(self.key, {
            'id': new_id, 'title': data['title']})
        self.assertEqual(data,
                         self.event.get_past_course_data_one(self.key, new_id))
        self.assertNotIn(new_id, old_courses)
        new_courses = self.event.list_courses(self.key, event_id, past=True)
        self.assertIn(new_id, new_courses)
        self.event.delete_past_course(self.key, new_id)
        newer_courses = self.event.list_courses(self.key, event_id, past=True)
        self.assertNotIn(new_id, newer_courses)

    @as_users("anton")
    def test_entity_participant(self, user):
        expectation = {2: {'course_id': 1, 'is_instructor': True,
                           'is_orga': False, 'persona_id': 2}}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.event.create_participant(self.key, 1, None, 5, False, False)
        expectation[5] = {'course_id': None, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(0, self.event.delete_participant(self.key, 1, 1, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(1, self.event.delete_participant(self.key, 1, None, 5))
        del expectation[5]
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.event.create_participant(self.key, 1, 1, 5, False, False)
        expectation[5] = {'course_id': 1, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(0, self.event.delete_participant(self.key, 1, None, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(1, self.event.delete_participant(self.key, 1, 1, 5))
        del expectation[5]
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))

    @as_users("anton", "garcia")
    def test_entity_event(self, user):
        ## need administrator to create event
        self.login(USER_DICT["anton"])
        old_events = self.event.list_events(self.key, past=False)
        data = {
            'title': "New Link Academy",
            'organizer': "Illuminati",
            'description': """Some more text

            on more lines.""",
            'shortname': 'link',
            'registration_start': datetime.date(2000, 11, 22),
            'registration_soft_limit': datetime.date(2022, 1, 2),
            'registration_hard_limit': None,
            'use_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'title': "First coming",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'fee': decimal.Decimal("234.56")},
                -2: {
                    'title': "Second coming",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'fee': decimal.Decimal("0.00")},
            },
            'fields': {
                -1: {
                    'field_name': "instrument",
                    'kind': "str",
                    'entries': None,
                },
                -2: {
                    'field_name': "preferred_excursion_date",
                    'kind': "date",
                    'entries': [["2109-8-16", "In the first coming"],
                                ["2110-8-16", "During the second coming"]],
                },
            },
        }
        new_id = self.event.create_event(self.key, data)
        ## back to normal mode
        self.login(user)
        data['id'] = new_id
        data['offline_lock'] = False
        ## correct part and field ids
        tmp = self.event.get_event_data_one(self.key, new_id)
        part_map = {}
        for part in tmp['parts']:
            for oldpart in data['parts']:
                if tmp['parts'][part]['title'] == data['parts'][oldpart]['title']:
                    part_map[tmp['parts'][part]['title']] = part
                    data['parts'][part] = data['parts'][oldpart]
                    data['parts'][part]['id'] = part
                    data['parts'][part]['event_id'] = new_id
                    break
            del data['parts'][oldpart]
        field_map = {}
        for field in tmp['fields']:
            for oldfield in data['fields']:
                if tmp['fields'][field]['field_name'] == data['fields'][oldfield]['field_name']:
                    field_map[tmp['fields'][field]['field_name']] = field
                    data['fields'][field] = data['fields'][oldfield]
                    data['fields'][field]['id'] = field
                    data['fields'][field]['event_id'] = new_id
                    break
            del data['fields'][oldfield]

        self.assertEqual(data,
                         self.event.get_event_data_one(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        data['orgas'] = {1, 7}
        newpart = {
            'title': "Third coming",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'fee': decimal.Decimal("123.40")}
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'fee': decimal.Decimal("1.23")}
        newfield = {
            'field_name': "kuea",
            'kind': "str",
            'entries': None,
        }
        changed_field = {
            'field_name': "preferred_excursion_date",
            'kind': "date",
            'entries': [["2110-8-15", "early second coming"],
                        ["2110-8-17", "late second coming"],],
        }
        self.event.set_event_data(self.key, {
            'id': new_id,
            'title': data['title'],
            'orgas': data['orgas'],
            'parts': {
                part_map["First coming"]: None,
                part_map["Second coming"]: changed_part,
                -1: newpart,
                },
            'fields': {
                field_map["instrument"]: None,
                field_map["preferred_excursion_date"]: changed_field,
                -1: newfield,
                },
            })
        ## fixup parts and fields
        tmp = self.event.get_event_data_one(self.key, new_id)
        for part in tmp['parts']:
            if tmp['parts'][part]['title'] == "Third coming":
                part_map[tmp['parts'][part]['title']] = part
                data['parts'][part] = newpart
                data['parts'][part]['id'] = part
                data['parts'][part]['event_id'] = new_id
        del data['parts'][part_map["First coming"]]
        changed_part['id'] = part_map["Second coming"]
        changed_part['event_id'] = new_id
        data['parts'][part_map["Second coming"]] = changed_part
        for field in tmp['fields']:
            if tmp['fields'][field]['field_name'] == "kuea":
                field_map[tmp['fields'][field]['field_name']] = field
                data['fields'][field] = newfield
                data['fields'][field]['id'] = field
                data['fields'][field]['event_id'] = new_id
        del data['fields'][field_map["instrument"]]
        changed_field['id'] = field_map["preferred_excursion_date"]
        changed_field['event_id'] = new_id
        data['fields'][field_map["preferred_excursion_date"]] = changed_field

        self.assertEqual(data,
                         self.event.get_event_data_one(self.key, new_id))


        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_events(self.key, past=False)
        self.assertIn(new_id, new_events)

        cdata = {
            'event_id': new_id,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ε',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'notes': "Beware of dragons.",
            'parts': {part_map["Second coming"]},
        }
        new_course_id = self.event.create_course(self.key, cdata)
        cdata['id'] = new_course_id
        self.assertEqual(cdata, self.event.get_course_data_one(
            self.key, new_course_id))

    @as_users("anton", "garcia")
    def test_entity_course(self, user):
        event_id = 1
        old_courses = self.event.list_courses(self.key, event_id, past=False)
        data = {
            'event_id': event_id,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ε',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'notes': "Beware of dragons.",
            'parts': {2, 3},
        }
        new_id = self.event.create_course(self.key, data)
        data['id'] = new_id
        self.assertEqual(data,
                         self.event.get_course_data_one(self.key, new_id))
        data['title'] = "Alternate Universes"
        data['parts'] = {1, 3}
        self.event.set_course_data(self.key, {
            'id': new_id, 'title': data['title'], 'parts': data['parts']})
        self.assertEqual(data,
                         self.event.get_course_data_one(self.key, new_id))
        self.assertNotIn(new_id, old_courses)
        new_courses = self.event.list_courses(self.key, event_id, past=False)
        self.assertIn(new_id, new_courses)

    @as_users("berta", "emilia")
    def test_acquire_data(self, user):
        expectation = {
            1: {
                'address': 'Auf der Düne 42',
                'address_supplement': '',
                'birthday': datetime.date(1991, 3, 30),
                'cloud_account': True,
                'country': '',
                'db_privileges': 1,
                'display_name': 'Anton',
                'family_name': 'Administrator',
                'gender': 1,
                'given_names': 'Anton Armin A.',
                'id': 1,
                'is_active': True,
                'location': 'Musterstadt',
                'mobile': '',
                'name_supplement': '',
                'notes': '',
                'postal_code': '03205',
                'status': 0,
                'telephone': '+49 (234) 98765',
                'title': '',
                'username': 'anton@example.cde',
            },
            5: {
                'address': 'Hohle Gasse 13',
                'address_supplement': None,
                'birthday': datetime.date(2012, 6, 2),
                'cloud_account': False,
                'country': 'Deutschland',
                'db_privileges': 0,
                'display_name': 'Emilia',
                'family_name': 'Eventis',
                'gender': 0,
                'given_names': 'Emilia E.',
                'id': 5,
                'is_active': True,
                'location': 'Wolkenkuckuksheim',
                'mobile': '',
                'name_supplement': '',
                'notes': '',
                'postal_code': '56767',
                'status': 20,
                'telephone': '+49 (5432) 555666777',
                'title': '',
                'username': 'emilia@example.cde',
            },
        }
        self.assertEqual(expectation, self.event.acquire_data(self.key, (1, 5)))

    @as_users("anton", "garcia")
    def test_sidebar_events(self, user):
        expectation = {1: {'registered': False,
                           'title': 'Große Testakademie 2222',
                           'use_questionnaire': False}}
        self.assertEqual(expectation, self.event.sidebar_events(self.key))
