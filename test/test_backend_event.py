#!/usr/bin/env python3

import copy
import datetime
import decimal
import pytz

from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.query import QUERY_SPECS, QueryOperators, Query
from cdedb.common import PERSONA_EVENT_FIELDS
import cdedb.database.constants as const


class TestEventBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self, user):
        data = self.core.get_event_user(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'name_supplement', 'display_name', 'telephone'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_event_user(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("anton", "berta")
    def test_participation_infos(self, user):
        participation_infos = self.event.participation_infos(self.key, (1, 2))
        expectation = {1: tuple(),
                       2: ({'persona_id': 2,
                            'is_orga': False,
                            'is_instructor': True,
                            'course_name': 'Swish -- und alles ist gut',
                            'pevent_id': 1,
                            'event_name': 'PfingstAkademie 2014',
                            'tempus': datetime.date(2014, 5, 25),
                            'pcourse_id': 1},)}
        self.assertEqual(expectation, participation_infos)
        participation_info = self.event.participation_info(self.key, 1)
        participation_infos = self.event.participation_infos(self.key, (1,))
        self.assertEqual(participation_infos[1], participation_info)

    @as_users("anton")
    def test_genesis(self, user):
        data = {
            "family_name": "Zeruda-Hime",
            "given_names": "Zelda",
            "username": 'zelda@example.cde',
            "notes": "Some blah",
            "realm": "event",
        }
        case_id = self.core.genesis_request(None, data)
        self.core.genesis_verify(None, case_id)
        update = {
            'id': case_id,
            'case_status': const.GenesisStati.approved,
            'secret': "foobar",
            'reviewer': user['id'],
        }
        self.core.genesis_modify_case(self.key, update)
        self.assertTrue(self.core.genesis_check(
            None, case_id, update['secret'], "event"))
        self.assertFalse(self.core.genesis_check(
            None, case_id, "wrong", "event"))
        self.assertFalse(self.core.genesis_check(
            None, case_id, update['secret'], "cde"))
        user_data = {
            "username": 'zelda@example.cde',
            "display_name": 'Zelda',
            "is_active": True,
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
            "birth_name": None,
            "address_supplement2": None,
            "address2": None,
            "postal_code2": None,
            "location2": None,
            "country2": None,
            "weblink": None,
            "specialisation": None,
            "affiliation": None,
            "timeline": None,
            "interests": None,
            "free_form": None,
            "trial_member": None,
            "decided_search": None,
            "bub_search": None,
            "foto": None,
        }
        new_id = self.core.genesis(None, case_id, update['secret'], "event", user_data)
        self.assertLess(0, new_id)
        value = self.core.get_event_user(self.key, new_id)
        user_data = {k: v for k, v in user_data.items() if k in PERSONA_EVENT_FIELDS}
        user_data.update({
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_member': False,
            'is_ml_admin': False,
            'id': new_id,
        })
        self.assertEqual(user_data, value)

    @as_users("anton")
    def test_entity_past_event(self, user):
        old_events = self.event.list_events(self.key, past=True)
        data = {
            'title': "New Link Academy",
            'shortname': "link",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'tempus': datetime.date(2000, 1, 1),
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
        pevent_id = 1
        old_courses = self.event.list_past_courses(self.key, pevent_id)
        data = {
            'pevent_id': pevent_id,
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
        new_courses = self.event.list_past_courses(self.key, pevent_id)
        self.assertIn(new_id, new_courses)
        self.event.delete_past_course(self.key, new_id)
        newer_courses = self.event.list_past_courses(self.key, pevent_id)
        self.assertNotIn(new_id, newer_courses)

    @as_users("anton")
    def test_entity_participant(self, user):
        expectation = {2: {'pcourse_id': 1, 'is_instructor': True,
                           'is_orga': False, 'persona_id': 2}}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.event.add_participant(self.key, 1, None, 5, False, False)
        expectation[5] = {'pcourse_id': None, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.assertEqual(0, self.event.remove_participant(self.key, 1, 1, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.assertEqual(1, self.event.remove_participant(self.key, 1, None, 5))
        del expectation[5]
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.event.add_participant(self.key, 1, 1, 5, False, False)
        expectation[5] = {'pcourse_id': 1, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.assertEqual(0, self.event.remove_participant(self.key, 1, None, 5))
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))
        self.assertEqual(1, self.event.remove_participant(self.key, 1, 1, 5))
        del expectation[5]
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pevent_id=1))

    @as_users("anton", "garcia")
    def test_entity_event(self, user):
        ## need administrator to create event
        self.login(USER_DICT["anton"])
        old_events = self.event.list_events(self.key, past=False)
        data = {
            'title': "New Link Academy",
            'institution': 1,
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
        data['is_archived'] = False
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
        old_courses = self.event.list_db_courses(self.key, event_id)
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
        new_courses = self.event.list_db_courses(self.key, event_id)
        self.assertIn(new_id, new_courses)

    @as_users("anton", "garcia")
    def test_open_events(self, user):
        expectation = {1: 'Große Testakademie 2222'}
        self.assertEqual(expectation, self.event.list_open_events(self.key))

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
            'checkin': datetime.datetime.now(pytz.utc),
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
        expectation[4]['checkin'] = nearly_now()
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        data = self.event.get_registrations(self.key, (1, 2, 4))
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
        query = Query(
            scope="qview_registration",
            spec=dict(QUERY_SPECS["qview_registration"]),
            fields_of_interest=(
               "reg.id", "reg.payment", "is_cde_realm", "persona.family_name",
               "birthday", "part1.lodgement_id1", "part3.status3",
               "fields.brings_balls", "fields.transportation"),
            constraints=[("reg.id", QueryOperators.nonempty, None),
                           ("persona.given_names", QueryOperators.regex, '[aeiou]'),
                           ("part2.status2", QueryOperators.nonempty, None),
                           ("fields.transportation", QueryOperators.oneof, ['pedes', 'etc'])],
            order=(("reg.id", True),),)
        ## fix query spec (normally done by frontend)
        query.spec.update({
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
             'is_cde_realm': False,
             'status3': 1,
             'transportation': 'pedes'},
            {'birthday': datetime.date(2222, 1, 1),
             'brings_balls': False,
             'family_name': 'Iota',
             'id': 4,
             'lodgement_id1': None,
             'payment': datetime.date(2014, 4, 4),
             'is_cde_realm': True,
             'status3': 1,
             'transportation': 'etc'})
        self.assertEqual(expectation, result)

    @as_users("anton", "garcia")
    def test_lock_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        self.assertTrue(self.event.get_event_data_one(self.key, 1)['offline_lock'])

    @as_users("anton", "garcia")
    def test_export_event(self, user):
        expectation = {
            'CDEDB_EXPORT_EVENT_VERSION': 1,
            'core.personas': ({'address': 'Auf der Düne 42',
                               'address_supplement': None,
                               'birthday': datetime.date(1991, 3, 30),
                               'cloud_account': True,
                               'country': None,
                               'display_name': 'Anton',
                               'family_name': 'Administrator',
                               'gender': 1,
                               'given_names': 'Anton Armin A.',
                               'id': 1,
                               'is_active': True,
                               'is_admin': True,
                               'is_archived': False,
                               'is_assembly_admin': True,
                               'is_assembly_realm': True,
                               'is_cde_admin': True,
                               'is_cde_realm': True,
                               'is_core_admin': True,
                               'is_event_admin': True,
                               'is_event_realm': True,
                               'is_member': True,
                               'is_ml_admin': True,
                               'is_ml_realm': True,
                               'is_searchable': True,
                               'location': 'Musterstadt',
                               'mobile': None,
                               'name_supplement': None,
                               'notes': None,
                               'postal_code': '03205',
                               'telephone': '+49 (234) 98765',
                               'title': None,
                               'username': 'anton@example.cde'},
                              {'address': 'Hohle Gasse 13',
                               'address_supplement': None,
                               'birthday': datetime.date(2012, 6, 2),
                               'cloud_account': False,
                               'country': 'Deutschland',
                               'display_name': 'Emilia',
                               'family_name': 'Eventis',
                               'gender': 0,
                               'given_names': 'Emilia E.',
                               'id': 5,
                               'is_active': True,
                               'is_admin': False,
                               'is_archived': False,
                               'is_assembly_admin': False,
                               'is_assembly_realm': True,
                               'is_cde_admin': False,
                               'is_cde_realm': False,
                               'is_core_admin': False,
                               'is_event_admin': False,
                               'is_event_realm': True,
                               'is_member': False,
                               'is_ml_admin': False,
                               'is_ml_realm': True,
                               'is_searchable': False,
                               'location': 'Wolkenkuckuksheim',
                               'mobile': None,
                               'name_supplement': None,
                               'notes': None,
                               'postal_code': '56767',
                               'telephone': '+49 (5432) 555666777',
                               'title': None,
                               'username': 'emilia@example.cde'},
                              {'address': 'Bei der Wüste 39',
                               'address_supplement': None,
                               'birthday': datetime.date(1978, 12, 12),
                               'cloud_account': True,
                               'country': None,
                               'display_name': 'Garcia',
                               'family_name': 'Generalis',
                               'gender': 0,
                               'given_names': 'Garcia G.',
                               'id': 7,
                               'is_active': True,
                               'is_admin': False,
                               'is_archived': False,
                               'is_assembly_admin': False,
                               'is_assembly_realm': True,
                               'is_cde_admin': False,
                               'is_cde_realm': True,
                               'is_core_admin': False,
                               'is_event_admin': False,
                               'is_event_realm': True,
                               'is_member': True,
                               'is_ml_admin': False,
                               'is_ml_realm': True,
                               'is_searchable': False,
                               'location': 'Weltstadt',
                               'mobile': None,
                               'name_supplement': None,
                               'notes': None,
                               'postal_code': '8888',
                               'telephone': None,
                               'title': None,
                               'username': 'garcia@example.cde'},
                              {'address': 'Zwergstraße 1',
                               'address_supplement': None,
                               'birthday': datetime.date(2222, 1, 1),
                               'cloud_account': True,
                               'country': None,
                               'display_name': 'Inga',
                               'family_name': 'Iota',
                               'gender': 0,
                               'given_names': 'Inga',
                               'id': 9,
                               'is_active': True,
                               'is_admin': False,
                               'is_archived': False,
                               'is_assembly_admin': False,
                               'is_assembly_realm': True,
                               'is_cde_admin': False,
                               'is_cde_realm': True,
                               'is_core_admin': False,
                               'is_event_admin': False,
                               'is_event_realm': True,
                               'is_member': True,
                               'is_ml_admin': False,
                               'is_ml_realm': True,
                               'is_searchable': True,
                               'location': 'Liliput',
                               'mobile': '0163/456897',
                               'name_supplement': None,
                               'notes': None,
                               'postal_code': '1111',
                               'telephone': None,
                               'title': None,
                               'username': 'inga@example.cde'}),
            'event.course_choices': ({'course_id': 2,
                                      'id': 1,
                                      'part_id': 2,
                                      'rank': 0,
                                      'registration_id': 1},
                                     {'course_id': 3,
                                      'id': 2,
                                      'part_id': 2,
                                      'rank': 1,
                                      'registration_id': 1},
                                     {'course_id': 4,
                                      'id': 3,
                                      'part_id': 2,
                                      'rank': 2,
                                      'registration_id': 1},
                                     {'course_id': 1,
                                      'id': 4,
                                      'part_id': 3,
                                      'rank': 0,
                                      'registration_id': 1},
                                     {'course_id': 4,
                                      'id': 5,
                                      'part_id': 3,
                                      'rank': 1,
                                      'registration_id': 1},
                                     {'course_id': 5,
                                      'id': 6,
                                      'part_id': 3,
                                      'rank': 2,
                                      'registration_id': 1},
                                     {'course_id': 5,
                                      'id': 7,
                                      'part_id': 1,
                                      'rank': 0,
                                      'registration_id': 2},
                                     {'course_id': 4,
                                      'id': 8,
                                      'part_id': 1,
                                      'rank': 1,
                                      'registration_id': 2},
                                     {'course_id': 1,
                                      'id': 9,
                                      'part_id': 1,
                                      'rank': 2,
                                      'registration_id': 2},
                                     {'course_id': 3,
                                      'id': 10,
                                      'part_id': 2,
                                      'rank': 0,
                                      'registration_id': 2},
                                     {'course_id': 4,
                                      'id': 11,
                                      'part_id': 2,
                                      'rank': 1,
                                      'registration_id': 2},
                                     {'course_id': 2,
                                      'id': 12,
                                      'part_id': 2,
                                      'rank': 2,
                                      'registration_id': 2},
                                     {'course_id': 4,
                                      'id': 13,
                                      'part_id': 3,
                                      'rank': 0,
                                      'registration_id': 2},
                                     {'course_id': 2,
                                      'id': 14,
                                      'part_id': 3,
                                      'rank': 1,
                                      'registration_id': 2},
                                     {'course_id': 1,
                                      'id': 15,
                                      'part_id': 3,
                                      'rank': 2,
                                      'registration_id': 2},
                                     {'course_id': 4,
                                      'id': 16,
                                      'part_id': 1,
                                      'rank': 0,
                                      'registration_id': 3},
                                     {'course_id': 1,
                                      'id': 17,
                                      'part_id': 1,
                                      'rank': 1,
                                      'registration_id': 3},
                                     {'course_id': 5,
                                      'id': 18,
                                      'part_id': 1,
                                      'rank': 2,
                                      'registration_id': 3},
                                     {'course_id': 2,
                                      'id': 19,
                                      'part_id': 2,
                                      'rank': 0,
                                      'registration_id': 3},
                                     {'course_id': 3,
                                      'id': 20,
                                      'part_id': 2,
                                      'rank': 1,
                                      'registration_id': 3},
                                     {'course_id': 4,
                                      'id': 21,
                                      'part_id': 2,
                                      'rank': 2,
                                      'registration_id': 3},
                                     {'course_id': 2,
                                      'id': 22,
                                      'part_id': 3,
                                      'rank': 0,
                                      'registration_id': 3},
                                     {'course_id': 4,
                                      'id': 23,
                                      'part_id': 3,
                                      'rank': 1,
                                      'registration_id': 3},
                                     {'course_id': 1,
                                      'id': 24,
                                      'part_id': 3,
                                      'rank': 2,
                                      'registration_id': 3},
                                     {'course_id': 1,
                                      'id': 25,
                                      'part_id': 1,
                                      'rank': 0,
                                      'registration_id': 4},
                                     {'course_id': 4,
                                      'id': 26,
                                      'part_id': 1,
                                      'rank': 1,
                                      'registration_id': 4},
                                     {'course_id': 5,
                                      'id': 27,
                                      'part_id': 1,
                                      'rank': 2,
                                      'registration_id': 4},
                                     {'course_id': 4,
                                      'id': 28,
                                      'part_id': 2,
                                      'rank': 0,
                                      'registration_id': 4},
                                     {'course_id': 2,
                                      'id': 29,
                                      'part_id': 2,
                                      'rank': 1,
                                      'registration_id': 4},
                                     {'course_id': 3,
                                      'id': 30,
                                      'part_id': 2,
                                      'rank': 2,
                                      'registration_id': 4},
                                     {'course_id': 1,
                                      'id': 31,
                                      'part_id': 3,
                                      'rank': 0,
                                      'registration_id': 4},
                                     {'course_id': 2,
                                      'id': 32,
                                      'part_id': 3,
                                      'rank': 1,
                                      'registration_id': 4},
                                     {'course_id': 4,
                                      'id': 33,
                                      'part_id': 3,
                                      'rank': 2,
                                      'registration_id': 4}),
            'event.course_parts': ({'course_id': 1, 'id': 1, 'part_id': 1},
                                   {'course_id': 1, 'id': 2, 'part_id': 3},
                                   {'course_id': 2, 'id': 3, 'part_id': 2},
                                   {'course_id': 2, 'id': 4, 'part_id': 3},
                                   {'course_id': 3, 'id': 5, 'part_id': 2},
                                   {'course_id': 4, 'id': 6, 'part_id': 1},
                                   {'course_id': 4, 'id': 7, 'part_id': 2},
                                   {'course_id': 4, 'id': 8, 'part_id': 3},
                                   {'course_id': 5, 'id': 9, 'part_id': 1},
                                   {'course_id': 5, 'id': 10, 'part_id': 2},
                                   {'course_id': 5, 'id': 11, 'part_id': 3}),
            'event.courses': ({'description': 'Wir werden die Bäume drücken.',
                               'event_id': 1,
                               'id': 1,
                               'instructors': 'ToFi & Co',
                               'notes': 'Promotionen in Mathematik und Ethik für '
                                        'Teilnehmer notwendig.',
                               'nr': 'α',
                               'shortname': 'Heldentum',
                               'title': 'Planetenretten für Anfänger'},
                              {'description': 'Inklusive Post, Backwaren und '
                                              'frühzeitigem Ableben.',
                               'event_id': 1,
                               'id': 2,
                               'instructors': 'Bernd Lucke',
                               'notes': 'Kursleiter hat Sekt angefordert.',
                               'nr': 'β',
                               'shortname': 'Kabarett',
                               'title': 'Lustigsein für Fortgeschrittene'},
                              {'description': 'mit hoher Leistung.',
                               'event_id': 1,
                               'id': 3,
                               'instructors': 'Heinrich und Thomas Mann',
                               'notes': None,
                               'nr': 'γ',
                               'shortname': 'Kurz',
                               'title': 'Kurzer Kurs'},
                              {'description': 'mit hohem Umsatz.',
                               'event_id': 1,
                               'id': 4,
                               'instructors': 'Stephen Hawking und Richard Feynman',
                               'notes': None,
                               'nr': 'δ',
                               'shortname': 'Lang',
                               'title': 'Langer Kurs'},
                              {'description': 'damit wir Auswahl haben',
                               'event_id': 1,
                               'id': 5,
                               'instructors': 'TBA',
                               'notes': None,
                               'nr': 'ε',
                               'shortname': 'Backup',
                               'title': 'Backup-Kurs'}),
            'event.event_parts': ({'event_id': 1,
                                   'fee': decimal.Decimal('10.50'),
                                   'id': 1,
                                   'part_begin': datetime.date(2222, 2, 2),
                                   'part_end': datetime.date(2222, 2, 2),
                                   'title': 'Warmup'},
                                  {'event_id': 1,
                                   'fee': decimal.Decimal('123.00'),
                                   'id': 2,
                                   'part_begin': datetime.date(2222, 11, 1),
                                   'part_end': datetime.date(2222, 11, 11),
                                   'title': 'Erste Hälfte'},
                                  {'event_id': 1,
                                   'fee': decimal.Decimal('450.99'),
                                   'id': 3,
                                   'part_begin': datetime.date(2222, 11, 11),
                                   'part_end': datetime.date(2222, 11, 30),
                                   'title': 'Zweite Hälfte'}),
            'event.events': ({'description': 'Everybody come!',
                              'iban': 'DE96 3702 0500 0008 0689 01',
                              'id': 1,
                              'notes': 'Todoliste ... just kidding ;)',
                              'offline_lock': False,
                              'is_archived': False,
                              'institution': 1,
                              'registration_hard_limit': datetime.date(2220, 10, 30),
                              'registration_soft_limit': datetime.date(2200, 10, 30),
                              'registration_start': datetime.date(2000, 10, 30),
                              'shortname': 'TestAka',
                              'title': 'Große Testakademie 2222',
                              'use_questionnaire': False},),
            'event.field_definitions': ({'entries': None,
                                         'event_id': 1,
                                         'field_name': 'brings_balls',
                                         'id': 1,
                                         'kind': 'bool'},
                                        {'entries': [['pedes', 'by feet'],
                                                     ['car', 'own car available'],
                                                     ['etc', 'anything else']],
                                         'event_id': 1,
                                         'field_name': 'transportation',
                                         'id': 2,
                                         'kind': 'str'},
                                        {'entries': None,
                                         'event_id': 1,
                                         'field_name': 'lodge',
                                         'id': 3,
                                         'kind': 'str'},
                                        {'entries': None,
                                         'event_id': 1,
                                         'field_name': 'may_reserve',
                                         'id': 4,
                                         'kind': 'bool'},
                                        {'entries': None,
                                         'event_id': 1,
                                         'field_name': 'reserve_1',
                                         'id': 5,
                                         'kind': 'bool'},
                                        {'entries': None,
                                         'event_id': 1,
                                         'field_name': 'reserve_2',
                                         'id': 6,
                                         'kind': 'bool'},
                                        {'entries': None,
                                         'event_id': 1,
                                         'field_name': 'reserve_3',
                                         'id': 7,
                                         'kind': 'bool'}),
            'event.lodgements': ({'capacity': 5,
                                  'event_id': 1,
                                  'id': 1,
                                  'moniker': 'Warme Stube',
                                  'notes': None,
                                  'reserve': 1},
                                 {'capacity': 10,
                                  'event_id': 1,
                                  'id': 2,
                                  'moniker': 'Kalte Kammer',
                                  'notes': 'Dafür mit Frischluft.',
                                  'reserve': 2},
                                 {'capacity': 0,
                                  'event_id': 1,
                                  'id': 3,
                                  'moniker': 'Kellerverlies',
                                  'notes': 'Nur für Notfälle.',
                                  'reserve': 100},
                                 {'capacity': 1,
                                  'event_id': 1,
                                  'id': 4,
                                  'moniker': 'Einzelzelle',
                                  'notes': None,
                                  'reserve': 0}),
            'event.orgas': ({'event_id': 1, 'id': 1, 'persona_id': 7},),
            'event.questionnaire_rows': ({'event_id': 1,
                                          'field_id': None,
                                          'id': 1,
                                          'info': 'mit Text darunter',
                                          'input_size': None,
                                          'pos': 0,
                                          'readonly': None,
                                          'title': 'Unterüberschrift'},
                                         {'event_id': 1,
                                          'field_id': 1,
                                          'id': 2,
                                          'info': 'Du bringst genug Bälle mit um '
                                                  'einen ganzen Kurs abzuwerfen.',
                                          'input_size': None,
                                          'pos': 1,
                                          'readonly': False,
                                          'title': 'Bälle'},
                                         {'event_id': 1,
                                          'field_id': None,
                                          'id': 3,
                                          'info': 'nur etwas Text',
                                          'input_size': None,
                                          'pos': 2,
                                          'readonly': None,
                                          'title': None},
                                         {'event_id': 1,
                                          'field_id': None,
                                          'id': 4,
                                          'info': None,
                                          'input_size': None,
                                          'pos': 3,
                                          'readonly': None,
                                          'title': 'Weitere Überschrift'},
                                         {'event_id': 1,
                                          'field_id': 2,
                                          'id': 5,
                                          'info': None,
                                          'input_size': None,
                                          'pos': 4,
                                          'readonly': False,
                                          'title': 'Vehikel'},
                                         {'event_id': 1,
                                          'field_id': 3,
                                          'id': 6,
                                          'info': None,
                                          'input_size': 3,
                                          'pos': 5,
                                          'readonly': False,
                                          'title': 'Hauswunsch'}),
            'event.registration_parts': ({'course_id': None,
                                          'course_instructor': None,
                                          'id': 1,
                                          'lodgement_id': None,
                                          'part_id': 1,
                                          'registration_id': 1,
                                          'status': -1},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 2,
                                          'lodgement_id': None,
                                          'part_id': 2,
                                          'registration_id': 1,
                                          'status': 0},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 3,
                                          'lodgement_id': 1,
                                          'part_id': 3,
                                          'registration_id': 1,
                                          'status': 1},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 4,
                                          'lodgement_id': None,
                                          'part_id': 1,
                                          'registration_id': 2,
                                          'status': 2},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 5,
                                          'lodgement_id': 4,
                                          'part_id': 2,
                                          'registration_id': 2,
                                          'status': 3},
                                         {'course_id': 1,
                                          'course_instructor': 1,
                                          'id': 6,
                                          'lodgement_id': 4,
                                          'part_id': 3,
                                          'registration_id': 2,
                                          'status': 1},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 7,
                                          'lodgement_id': 2,
                                          'part_id': 1,
                                          'registration_id': 3,
                                          'status': 1},
                                         {'course_id': 2,
                                          'course_instructor': None,
                                          'id': 8,
                                          'lodgement_id': None,
                                          'part_id': 2,
                                          'registration_id': 3,
                                          'status': 1},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 9,
                                          'lodgement_id': 2,
                                          'part_id': 3,
                                          'registration_id': 3,
                                          'status': 1},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 10,
                                          'lodgement_id': None,
                                          'part_id': 1,
                                          'registration_id': 4,
                                          'status': 5},
                                         {'course_id': None,
                                          'course_instructor': None,
                                          'id': 11,
                                          'lodgement_id': None,
                                          'part_id': 2,
                                          'registration_id': 4,
                                          'status': 4},
                                         {'course_id': 1,
                                          'course_instructor': None,
                                          'id': 12,
                                          'lodgement_id': 2,
                                          'part_id': 3,
                                          'registration_id': 4,
                                          'status': 1}),
            'event.registrations': ({'checkin': None,
                                     'event_id': 1,
                                     'field_data': {'lodge': 'Die üblichen '
                                                             'Verdächtigen :)',
                                                    'registration_id': 1},
                                     'foto_consent': True,
                                     'id': 1,
                                     'mixed_lodging': True,
                                     'notes': None,
                                     'orga_notes': None,
                                     'parental_agreement': None,
                                     'payment': None,
                                     'persona_id': 1,
                                     'real_persona_id': None},
                                    {'checkin': None,
                                     'event_id': 1,
                                     'field_data': {'brings_balls': True,
                                                    'registration_id': 2,
                                                    'transportation': 'pedes'},
                                     'foto_consent': True,
                                     'id': 2,
                                     'mixed_lodging': True,
                                     'notes': 'Extrawünsche: Meerblick, Weckdienst '
                                              'und Frühstück am Bett',
                                     'orga_notes': 'Unbedingt in die Einzelzelle.',
                                     'parental_agreement': None,
                                     'payment': datetime.date(2014, 2, 2),
                                     'persona_id': 5,
                                     'real_persona_id': None},
                                    {'checkin': None,
                                     'event_id': 1,
                                     'field_data': {'registration_id': 3,
                                                    'transportation': 'car'},
                                     'foto_consent': True,
                                     'id': 3,
                                     'mixed_lodging': True,
                                     'notes': None,
                                     'orga_notes': None,
                                     'parental_agreement': None,
                                     'payment': datetime.date(2014, 3, 3),
                                     'persona_id': 7,
                                     'real_persona_id': None},
                                    {'checkin': None,
                                     'event_id': 1,
                                     'field_data': {'brings_balls': False,
                                                    'may_reserve': True,
                                                    'registration_id': 4,
                                                    'transportation': 'etc'},
                                     'foto_consent': True,
                                     'id': 4,
                                     'mixed_lodging': False,
                                     'notes': None,
                                     'orga_notes': None,
                                     'parental_agreement': None,
                                     'payment': datetime.date(2014, 4, 4),
                                     'persona_id': 9,
                                     'real_persona_id': None}),
            'id': 1,
            'timestamp': nearly_now()}
        self.assertEqual(expectation, self.event.export_event(self.key, 1))

    @as_users("anton")
    def test_import_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        data = self.event.export_event(self.key, 1)
        new_data = copy.deepcopy(data)
        ##
        ## Apply some changes
        ##
        for table in ('event.events', 'event.event_parts', 'event.courses',
                      'event.course_parts', 'event.orgas',
                      'event.field_definitions', 'event.lodgements',
                      'event.registrations', 'event.registration_parts',
                      'event.course_choices', 'event.questionnaire_rows'):
            new_data[table] = list(new_data[table])
        ## event
        new_data['event.events'][0]['description'] = "We are done!"
        ## event parts
        new_data['event.event_parts'].append(
            {'event_id': 1,
             'fee': decimal.Decimal('666.66'),
             'id': 4000,
             'part_begin': datetime.date(2345, 1, 1),
             'part_end': datetime.date(2345, 12, 31),
             'title': 'Aftershowparty'})
        ## lodgements
        new_data['event.lodgements'].append(
            {'capacity': 1,
             'event_id': 1,
             'id': 6000,
             'moniker': 'Matte im Orgabüro',
             'notes': None,
             'reserve': 0})
        ## registration
        new_data['event.registrations'].append(
            {'checkin': None,
             'event_id': 1,
             'field_data': {'lodge': 'Langschläfer',
                            'behaviour': 'good',
                            'registration_id': 1000},
             'foto_consent': True,
             'id': 1000,
             'mixed_lodging': True,
             'notes': None,
             'orga_notes': None,
             'parental_agreement': None,
             'payment': None,
             'persona_id': 2000,
             'real_persona_id': 2})
        ## registration parts
        new_data['event.registration_parts'].append(
            {'course_id': 3000,
             'course_instructor': None,
             'id': 5000,
             'lodgement_id': 6000,
             'part_id': 4000,
             'registration_id': 1000,
             'status': 1})
        ## orgas
        new_data['event.orgas'].append(
            {'event_id': 1, 'id': 7000, 'persona_id': 2000})
        ## course
        new_data['event.courses'].append(
            {'description': 'Spontankurs',
             'event_id': 1,
             'id': 3000,
             'instructors': 'Alle',
             'notes': None,
             'nr': 'φ',
             'shortname': 'Spontan',
             'title': 'Spontankurs'})
        ## course parts
        new_data['event.course_parts'].append(
            {'course_id': 3000, 'id': 8000, 'part_id': 4000})
        ## course choices
        choices = new_data['event.course_choices'][:-2]
        choices.append({'course_id': 5, 'id': 32, 'part_id': 3, 'rank': 1,
                        'registration_id': 4}) ## an update
        choices.append({'course_id': 4, 'id': 9000, 'part_id': 3, 'rank': 2,
                        'registration_id': 4}) ## a delete and an insert
        choices.append({'course_id': 3000, 'id': 10000, 'part_id': 4000, 'rank': 0,
                        'registration_id': 1000}) ## an insert
        new_data['event.course_choices'] = choices
        assert(len(new_data['event.course_choices'])
               == len(data['event.course_choices']) + 1)
        ## field definitions
        new_data['event.field_definitions'].append(
            {'entries': [['good', 'good'],
                         ['neutral', 'so so'],
                         ['bad', 'not good']],
             'event_id': 1,
             'field_name': 'behaviour',
             'id': 11000,
             'kind': 'str'})
        ## questionnaire rows
        new_data['event.questionnaire_rows'].append(
            {'event_id': 1,
             'field_id': 11000,
             'id': 12000,
             'info': 'Wie brav wirst Du sein',
             'input_size': None,
             'pos': 1,
             'readonly': True,
             'title': 'Vorsätze'})
        ## Note that the changes above are not entirely consistent/complete (as
        ## in some stuff is missing and another part may throw an error if we
        ## used the resulting data set for real)
        self.assertLess(0, self.event.unlock_import_event(self.key, new_data))
        ## Now we have to fix for new stuff
        new_data['event.events'][0]['offline_lock'] = False
        new_data['timestamp'] = nearly_now()
        ## Fix IDs in a static way, everything else is overkill
        new_data['event.event_parts'][-1]['id'] = 4
        new_data['event.orgas'][-1]['id'] = 2
        new_data['event.orgas'][-1]['persona_id'] = 2
        new_data['event.registrations'][-1]['id'] = 5
        new_data['event.registrations'][-1]['field_data']['registration_id'] = 5
        new_data['event.registrations'][-1]['persona_id'] = 2
        new_data['event.registrations'][-1]['real_persona_id'] = None
        new_data['event.registration_parts'][-1]['id'] = 13
        new_data['event.registration_parts'][-1]['course_id'] = 6
        new_data['event.registration_parts'][-1]['lodgement_id'] = 5
        new_data['event.registration_parts'][-1]['part_id'] = 4
        new_data['event.registration_parts'][-1]['registration_id'] = 5
        new_data['event.courses'][-1]['id'] = 6
        new_data['event.courses'][-1]['id'] = 6
        new_data['event.course_choices'][-2]['id'] = 34
        new_data['event.course_choices'][-1]['id'] = 35
        new_data['event.course_choices'][-1]['course_id'] = 6
        new_data['event.course_choices'][-1]['part_id'] = 4
        new_data['event.course_choices'][-1]['registration_id'] = 5
        new_data['event.course_parts'][-1]['id'] = 12
        new_data['event.course_parts'][-1]['course_id'] = 6
        new_data['event.course_parts'][-1]['part_id'] = 4
        new_data['event.lodgements'][-1]['id'] = 5
        new_data['event.field_definitions'][-1]['id'] = 8
        new_data['event.questionnaire_rows'][-1]['id'] = 7
        new_data['event.questionnaire_rows'][-1]['field_id'] = 8
        ## make tuples again
        for table in ('event.events', 'event.event_parts', 'event.courses',
                      'event.course_parts', 'event.orgas',
                      'event.field_definitions', 'event.lodgements',
                      'event.registrations', 'event.registration_parts',
                      'event.course_choices', 'event.questionnaire_rows'):
            new_data[table] = tuple(new_data[table])

        result = self.event.export_event(self.key, 1)
        ## this comes out in the wrong order, most probably this is not
        ## guaranteed by Postgres
        for table in ('event.field_definitions', 'event.orgas'):
            result[table] = tuple(sorted(result[table], key=lambda x: x['id']))
        ## because it's irrelevant anyway simply paste the result
        new_data['core.personas'] = result['core.personas']
        self.assertEqual(new_data, result)

    @as_users("anton")
    def test_past_log(self, user):
        ## first generate some data
        data = {
            'title': "New Link Academy",
            'shortname': "link",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'tempus': datetime.date(2000, 1, 1),
        }
        new_id = self.event.create_past_event(self.key, data)
        self.event.set_past_event_data(self.key, {
            'id': new_id, 'title': "Alternate Universe Academy"})
        data = {
            'pevent_id': 1,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
        }
        new_id = self.event.create_past_course(self.key, data)
        self.event.set_past_course_data(self.key, {
            'id': new_id, 'title': "New improved title"})
        self.event.delete_past_course(self.key, new_id)
        self.event.add_participant(self.key, 1, None, 5, False, False)
        self.event.remove_participant(self.key, 1, None, 5)

        ## now check it
        expectation = ({'additional_info': None,
                        'code': 21,
                        'ctime': nearly_now(),
                        'pevent_id': 1,
                        'persona_id': 5,
                        'submitted_by': 1},
                       {'additional_info': None,
                        'code': 20,
                        'ctime': nearly_now(),
                        'pevent_id': 1,
                        'persona_id': 5,
                        'submitted_by': 1},
                       {'additional_info': 'New improved title',
                        'code': 12,
                        'ctime': nearly_now(),
                        'pevent_id': 1,
                        'persona_id': None,
                        'submitted_by': 1},
                       {'additional_info': 'New improved title',
                        'code': 11,
                        'ctime': nearly_now(),
                        'pevent_id': 1,
                        'persona_id': None,
                        'submitted_by': 1},
                       {'additional_info': 'Topos theory for the kindergarden',
                        'code': 10,
                        'ctime': nearly_now(),
                        'pevent_id': 1,
                        'persona_id': None,
                        'submitted_by': 1},
                       {'additional_info': None,
                        'code': 1,
                        'ctime': nearly_now(),
                        'pevent_id': 2,
                        'persona_id': None,
                        'submitted_by': 1},
                       {'additional_info': None,
                        'code': 0,
                        'ctime': nearly_now(),
                        'pevent_id': 2,
                        'persona_id': None,
                        'submitted_by': 1})
        self.assertEqual(expectation, self.event.retrieve_past_log(self.key))

    @as_users("anton")
    def test_archive(self, user):
        update = {
            'id': 1,
            'registration_soft_limit': datetime.date(2001, 10, 30),
            'registration_hard_limit': datetime.date(2002, 10, 30),
            'parts': {
                1: {
                    'part_begin': datetime.date(2003, 2, 2),
                    'part_end': datetime.date(2003, 2, 2),
                },
                2: {
                    'part_begin': datetime.date(2003, 11, 1),
                    'part_end': datetime.date(2003, 11, 11),
                },
                3: {
                    'part_begin': datetime.date(2003, 11, 11),
                    'part_end': datetime.date(2003, 11, 30),
                }
            }
        }
        self.event.set_event_data(self.key, update)
        new_id, _ = self.event.archive_event(self.key, 1)
        expectation = {
            'description': 'Everybody come!',
            'id': 2,
            'institution': 1,
            'title': 'Große Testakademie 2222',
            'shortname': "TestAka",}
        data = self.event.get_past_event_data_one(self.key, new_id)
        self.assertIn(data['tempus'], {datetime.date(2003, 2, 2),
                                       datetime.date(2003, 11, 1),
                                       datetime.date(2003, 11, 11),})
        del data['tempus']
        self.assertEqual(expectation, data)
        expectation = {2: 'Planetenretten für Anfänger',
                       3: 'Lustigsein für Fortgeschrittene'}
        self.assertEqual(expectation,
                         self.event.list_past_courses(self.key, new_id))
        expectation = {
            7: {'pcourse_id': 3,
                'is_instructor': False,
                'is_orga': True,
                'persona_id': 7}}
        self.assertEqual(expectation,
                         self.event.list_participants(self.key, pcourse_id=3))

    @as_users("anton")
    def test_log(self, user):
        ## first generate some data
        data = {
            'title': "New Link Academy",
            'institution': 1,
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
        data = {
            'event_id': 1,
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
        data['title'] = "Alternate Universes"
        data['parts'] = {1, 3}
        self.event.set_course_data(self.key, {
            'id': new_id, 'title': data['title'], 'parts': data['parts']})
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
        data = {
            'id': 4,
            'choices': {1:[5, 4, 1], 2: [2, 3, 4]},
            'field_data': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(pytz.utc),
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
        self.event.set_registration(self.key, data)
        new = {
            'capacity': 42,
            'event_id': 1,
            'moniker': 'Hyrule',
            'notes': "Notizen",
            'reserve': 11
        }
        new_id = self.event.create_lodgement(self.key, new)
        update = {
            'capacity': 21,
            'notes': None,
            'id': new_id,
        }
        self.event.set_lodgement(self.key, update)
        self.event.delete_lodgement(self.key, new_id)
        data = [
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
        self.event.set_questionnaire(self.key, 1, data)

        ## now check it
        expectation = (
            {'additional_info': None,
             'code': 30,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Hyrule',
             'code': 27,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Hyrule',
             'code': 25,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Hyrule',
             'code': 26,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 51,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 9,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 50,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 51,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 51,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 42,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 41,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 40,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 42,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'instrument',
             'code': 22,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'preferred_excursion_date',
             'code': 21,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'kuea',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'First coming',
             'code': 17,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second coming',
             'code': 16,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Third coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 11,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 0,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'instrument',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'preferred_excursion_date',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': 7,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': 'First coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 2,
             'persona_id': None,
             'submitted_by': 1})
        self.assertEqual(expectation, self.event.retrieve_log(self.key))
