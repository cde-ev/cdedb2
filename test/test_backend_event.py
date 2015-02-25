#!/usr/bin/env python3

from test.common import BackendTest, as_users, USER_DICT
from cdedb.query import QUERY_SPECS, QueryOperators
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
        self.assertEqual(0, self.event.remove_participant(self.key, 1, 1, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(1, self.event.remove_participant(self.key, 1, None, 5))
        del expectation[5]
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.event.create_participant(self.key, 1, 1, 5, False, False)
        expectation[5] = {'course_id': 1, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(0, self.event.remove_participant(self.key, 1, None, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, event_id=1))
        self.assertEqual(1, self.event.remove_participant(self.key, 1, 1, 5))
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
            'iban': None,
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
                if (tmp['fields'][field]['field_name']
                        == data['fields'][oldfield]['field_name']):
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
        changed_field['field_name'] = "preferred_excursion_date"
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
            'nr': 'ζ',
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
            'nr': 'ζ',
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
                'address_supplement': None,
                'birthday': datetime.date(1991, 3, 30),
                'cloud_account': True,
                'country': None,
                'db_privileges': 1,
                'display_name': 'Anton',
                'family_name': 'Administrator',
                'gender': 1,
                'given_names': 'Anton Armin A.',
                'id': 1,
                'is_active': True,
                'location': 'Musterstadt',
                'mobile': None,
                'name_supplement': None,
                'notes': None,
                'postal_code': '03205',
                'status': 0,
                'telephone': '+49 (234) 98765',
                'title': None,
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
                'mobile': None,
                'name_supplement': None,
                'notes': None,
                'postal_code': '56767',
                'status': 20,
                'telephone': '+49 (5432) 555666777',
                'title': None,
                'username': 'emilia@example.cde',
            },
        }
        self.assertEqual(expectation, self.event.acquire_data(self.key, (1, 5)))

    @as_users("anton", "garcia")
    def test_sidebar_events(self, user):
        expectation = {1: {'registration_id': 1 if user['id'] == 1 else 3,
                           'title': 'Große Testakademie 2222',
                           'use_questionnaire': False,
                           'locked': False}}
        self.assertEqual(expectation, self.event.sidebar_events(self.key))

    @as_users("emilia")
    def test_registration_participant(self, user):
        expectation = {
            'checkin': None,
            'choices': {1: [5, 4, 1], 2: [3, 4, 2], 3: [4, 2, 1]},
            'event_id': 1,
            'field_data': {'registration_id': 2, 'brings_balls': True, 'transportation': 'pedes'},
            'foto_consent': True,
            'id': 2,
            'mixed_lodging': True,
            'orga_notes': 'Unbedingt in die Einzelzelle.',
            'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
            'parental_agreement': None,
            'parts': {
                1: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'part_id': 1,
                    'registration_id': 2,
                    'status': 2},
                2: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': 4,
                    'part_id': 2,
                    'registration_id': 2,
                    'status': 3},
                3: {'course_id': 1,
                    'course_instructor': 1,
                    'lodgement_id': 4,
                    'part_id': 3,
                    'registration_id': 2,
                    'status': 1}},
            'payment': datetime.date(2014, 2, 2),
            'persona_id': 5,
            'real_persona_id': None}
        self.assertEqual(expectation,
                         self.event.get_registration(self.key, 2))
        data = {
            'id': 2,
            'choices': {2: [2, 3, 4]},
            'field_data': {'transportation': 'etc'},
            'mixed_lodging': False,
        }
        self.assertLess(0, self.event.set_registration(self.key, data))
        expectation['choices'][2] = [2, 3, 4]
        expectation['field_data']['transportation'] = 'etc'
        expectation['mixed_lodging'] = False
        self.assertEqual(expectation,
                         self.event.get_registration(self.key, 2))

    @as_users("berta")
    def test_registering(self, user):
        new_reg = {
            'checkin': None,
            'choices': {1: [1, 4, 5]},
            'event_id': 1,
            'foto_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': None,
            'parts': {
                1: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
                2: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
                3: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
            },
            'notes': "Some bla.",
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None}
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['field_data'] = {'registration_id': new_id}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        self.assertEqual(new_reg,
                         self.event.get_registration(self.key, new_id))

    @as_users("anton", "garcia")
    def test_entity_registration(self, user):
        event_id = 1
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9},
                         self.event.list_registrations(self.key, event_id))
        expectation = {
            1: {'checkin': None,
                'choices': {1: [], 2: [2, 3, 4], 3: [1, 4, 5]},
                'event_id': 1,
                'field_data': {'registration_id': 1,
                               'lodge': 'Die üblichen Verdächtigen :)'},
                'foto_consent': True,
                'id': 1,
                'mixed_lodging': True,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': None,
                'parts': {
                    1: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 1,
                        'status': -1},
                    2: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 1,
                        'status': 0},
                    3: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': 1,
                        'part_id': 3,
                        'registration_id': 1,
                        'status': 1}},
                'payment': None,
                'persona_id': 1,
                'real_persona_id': None},
            2: {'checkin': None,
                'choices': {1: [5, 4, 1], 2: [3, 4, 2], 3: [4, 2, 1]},
                'event_id': 1,
                'field_data': {'registration_id': 2, 'brings_balls': True, 'transportation': 'pedes'},
                'foto_consent': True,
                'id': 2,
                'mixed_lodging': True,
                'orga_notes': 'Unbedingt in die Einzelzelle.',
                'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
                'parental_agreement': None,
                'parts': {
                    1: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 2,
                        'status': 2},
                    2: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': 4,
                        'part_id': 2,
                        'registration_id': 2,
                        'status': 3},
                    3: {'course_id': 1,
                        'course_instructor': 1,
                        'lodgement_id': 4,
                        'part_id': 3,
                        'registration_id': 2,
                        'status': 1}},
                'payment': datetime.date(2014, 2, 2),
                'persona_id': 5,
                'real_persona_id': None},
            4: {'checkin': None,
                'choices': {1: [1, 4, 5], 2: [4, 2, 3], 3: [1, 2, 4]},
                'event_id': 1,
                'field_data': {'registration_id': 4,
                               'brings_balls': False,
                               'may_reserve': True,
                               'transportation': 'etc'},
                'foto_consent': True,
                'id': 4,
                'mixed_lodging': False,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': None,
                'parts': {
                    1: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 4,
                        'status': 5},
                    2: {'course_id': None,
                        'course_instructor': None,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 4,
                        'status': 4},
                    3: {'course_id': 1,
                        'course_instructor': None,
                        'lodgement_id': 2,
                        'part_id': 3,
                        'registration_id': 4,
                        'status': 1}},
                'payment': datetime.date(2014, 4, 4),
                'persona_id': 9,
                'real_persona_id': None}}
        self.assertEqual(expectation,
                         self.event.get_registrations(self.key, (1, 2, 4)))
        data = {
            'id': 4,
            'choices': {1:[5, 4, 1], 2: [2, 3, 4]},
            'field_data': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(),
            'parts': {
                1: {
                    'status': 1,
                    'course_id': 5,
                    'lodgement_id': 2,
                },
                3: {
                    'status': 5,
                    'course_id': None,
                    'lodgement_id': None,
                }
            }
        }
        self.assertLess(0, self.event.set_registration(self.key, data))
        expectation[4]['choices'].update(data['choices'])
        expectation[4]['field_data'].update(data['field_data'])
        expectation[4]['mixed_lodging'] = data['mixed_lodging']
        expectation[4]['checkin'] = data['checkin']
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        data = self.event.get_registrations(self.key, (1, 2, 4))
        # TODO handle timezone info gracefully
        self.assertEqual(expectation[4]['checkin'].date(),
                         data[4]['checkin'].date())
        data[4]['checkin'] = expectation[4]['checkin']
        self.assertEqual(expectation, data)
        new_reg = {
            'checkin': None,
            'choices': {1: [1, 4, 5]},
            'event_id': event_id,
            'foto_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': None,
            'parts': {
                1: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
                2: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
                3: {'course_id': None,
                    'course_instructor': None,
                    'lodgement_id': None,
                    'status': 0
                },
            },
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None
        }
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['field_data'] = {'registration_id': new_id}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        self.assertEqual(new_reg,
                         self.event.get_registration(self.key, new_id))
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, new_id: 2},
                         self.event.list_registrations(self.key, event_id))

    @as_users("anton", "garcia")
    def test_entity_lodgement(self, user):
        event_id = 1
        expectation = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle'}
        self.assertEqual(expectation,
                         self.event.list_lodgements(self.key, event_id))
        expectation = {
            1: {
                'capacity': 5,
                'event_id': 1,
                'id': 1,
                'moniker': 'Warme Stube',
                'notes': None,
                'reserve': 1},
            4: {
                'capacity': 1,
                'event_id': 1,
                'id': 4,
                'moniker': 'Einzelzelle',
                'notes': None,
                'reserve': 0}
        }
        self.assertEqual(expectation, self.event.get_lodgements(self.key, (1,4)))
        new = {
            'capacity': 42,
            'event_id': 1,
            'moniker': 'Hyrule',
            'notes': "Notizen",
            'reserve': 11
        }
        new_id = self.event.create_lodgement(self.key, new)
        self.assertLess(0, new_id)
        new['id'] = new_id
        self.assertEqual(new, self.event.get_lodgement(self.key, new_id))
        update = {
            'capacity': 21,
            'notes': None,
            'id': new_id,
        }
        self.assertLess(0, self.event.set_lodgement(self.key, update))
        new.update(update)
        self.assertEqual(new, self.event.get_lodgement(self.key, new_id))
        expectation = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle',
            new_id: 'Hyrule'}
        self.assertEqual(expectation,
                         self.event.list_lodgements(self.key, event_id))
        self.assertLess(0, self.event.delete_lodgement(self.key, new_id))
        del expectation[new_id]
        self.assertEqual(expectation,
                         self.event.list_lodgements(self.key, event_id))

    @as_users("berta", "emilia")
    def test_get_questionnaire(self, user):
        event_id = 1
        expectation = [
            {'field_id': None,
             'info': 'mit Text darunter',
             'pos': 0,
             'readonly': None,
             'input_size': None,
             'title': 'Unterüberschrift'},
            {'field_id': 1,
             'info': 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.',
             'pos': 1,
             'readonly': False,
             'input_size': None,
             'title': 'Bälle'},
            {'field_id': None,
             'info': 'nur etwas Text',
             'pos': 2,
             'readonly': None,
             'input_size': None,
             'title': None},
            {'field_id': None,
             'info': None,
             'pos': 3,
             'readonly': None,
             'input_size': None,
             'title': 'Weitere Überschrift'},
            {'field_id': 2,
             'info': None,
             'pos': 4,
             'readonly': False,
             'input_size': None,
             'title': 'Vehikel'},
            {'field_id': 3,
             'info': None,
             'pos': 5,
             'readonly': False,
             'input_size': 3,
             'title': 'Hauswunsch'}]
        self.assertEqual(expectation,
                         self.event.get_questionnaire(self.key, event_id))

    @as_users("anton", "garcia")
    def test_set_questionnaire(self, user):
        event_id = 1
        expectation = [
            {'field_id': None,
             'info': None,
             'readonly': None,
             'input_size': None,
             'title': 'Weitere bla Überschrift'},
            {'field_id': 2,
             'info': None,
             'readonly': True,
             'input_size': None,
             'title': 'Vehikel'},
            {'field_id': None,
             'info': 'mit Text darunter und so',
             'readonly': None,
             'input_size': None,
             'title': 'Unterüberschrift'},
            {'field_id': 3,
             'info': None,
             'readonly': True,
             'input_size': 5,
             'title': 'Vehikel'},
            {'field_id': None,
             'info': 'nur etwas mehr Text',
             'readonly': None,
             'input_size': None,
             'title': None},]
        self.assertLess(0, self.event.set_questionnaire(
            self.key, event_id, expectation))
        for pos, entry in enumerate(expectation):
            entry['pos'] = pos
        self.assertEqual(expectation,
                         self.event.get_questionnaire(self.key, event_id))

    @as_users("anton", "garcia")
    def test_registration_query(self, user):
        query = {
            "scope": "qview_registration",
            "spec": dict(QUERY_SPECS["qview_registration"]),
            "fields_of_interest": (
                "reg.id", "reg.payment", "persona.status", "user_data.family_name",
                "user_data.birthday", "part1.lodgement_id1", "part3.status3",
                "fields.brings_balls", "fields.transportation"),
            "constraints": (("reg.id", QueryOperators.greater.value, 0),
                            ("user_data.given_names", QueryOperators.regex.value, '[aeiou]'),
                            ("part2.status2", QueryOperators.nonempty.value, None),
                            ("fields.transportation", QueryOperators.oneof.value, ['pedes', 'etc'])),
            "order": (("reg.id", True),),
        }
        ## fix query spec (normally done by frontend)
        query['spec'].update({
            'part1.lodgement_id1': "int",
            'part3.status3': "int",
            'fields.brings_balls': "bool",
            'fields.transportation': "str",
            'part2.status2': "int",
            })
        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {'birthday': datetime.date(2012, 6, 2),
             'brings_balls': True,
             'family_name': 'Eventis',
             'id': 2,
             'lodgement_id1': None,
             'payment': datetime.date(2014, 2, 2),
             'status': 20,
             'status3': 1,
             'transportation': 'pedes'},
            {'birthday': datetime.date(2222, 1, 1),
             'brings_balls': False,
             'family_name': 'Iota',
             'id': 4,
             'lodgement_id1': None,
             'payment': datetime.date(2014, 4, 4),
             'status': 0,
             'status3': 1,
             'transportation': 'etc'})
        self.assertEqual(expectation, result)
