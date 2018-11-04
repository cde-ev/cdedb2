#!/usr/bin/env python3

import copy
import datetime
import decimal
import pytz

from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.backend.event import EventBackend
from cdedb.query import QUERY_SPECS, QueryOperators, Query
from cdedb.common import PERSONA_EVENT_FIELDS
from cdedb.enums import ENUMS_DICT
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

    @as_users("anton", "garcia")
    def test_entity_event(self, user):
        ## need administrator to create event
        self.login(USER_DICT["anton"])
        old_events = self.event.list_db_events(self.key)
        data = {
            'title': "New Link Academy",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'shortname': 'link',
            'registration_start': datetime.datetime(2000, 11, 22, 0, 0, 0, tzinfo=pytz.utc),
            'registration_soft_limit': datetime.datetime(2022, 1, 2, 0, 0, 0, tzinfo=pytz.utc),
            'registration_hard_limit': None,
            'iban': None,
            'mail_text': None,
            'use_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {-1: "First lecture"},
                    'title': "First coming",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'fee': decimal.Decimal("234.56")},
                -2: {
                    'tracks': {-1: "Second lecture"},
                    'title': "Second coming",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'fee': decimal.Decimal("0.00")},
            },
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "instrument",
                    'kind': "str",
                    'entries': None,
                },
                -2: {
                    'association': 1,
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
        data['is_course_list_visible'] = False
        data['is_visible'] = False
        data['lodge_field'] = None
        data['reserve_field'] = None
        data['begin'] = datetime.date(2109, 8, 7)
        data['end'] = datetime.date(2110, 8, 20)
        data['is_open'] = True
        # TODO dynamically adapt ids from the database result
        data['tracks'] = {4: {'id': 4, 'part_id': 5, 'title': 'Second lecture'},
                          5: {'id': 5, 'part_id': 6, 'title': 'First lecture'}}
        ## correct part and field ids
        tmp = self.event.get_event(self.key, new_id)
        part_map = {}
        for part in tmp['parts']:
            for oldpart in data['parts']:
                if tmp['parts'][part]['title'] == data['parts'][oldpart]['title']:
                    part_map[tmp['parts'][part]['title']] = part
                    data['parts'][part] = data['parts'][oldpart]
                    data['parts'][part]['id'] = part
                    data['parts'][part]['event_id'] = new_id
                    self.assertEqual(set(data['parts'][part]['tracks'].values()),
                                     set(tmp['parts'][part]['tracks'].values()))
                    data['parts'][part]['tracks'] = tmp['parts'][part]['tracks']
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
                         self.event.get_event(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        data['orgas'] = {1, 7}
        newpart = {
            'tracks': {-1: "Third lecture"},
            'title': "Third coming",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'fee': decimal.Decimal("123.40")}
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'fee': decimal.Decimal("1.23"),
            'tracks': {4: "Second lecture v2"}} # hardcoded value 4
        newfield = {
            'association': 3,
            'field_name': "kuea",
            'kind': "str",
            'entries': None,
        }
        changed_field = {
            'association': 2,
            'kind': "date",
            'entries': [["2110-8-15", "early second coming"],
                        ["2110-8-17", "late second coming"],],
        }
        self.event.set_event(self.key, {
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
        tmp = self.event.get_event(self.key, new_id)
        for part in tmp['parts']:
            if tmp['parts'][part]['title'] == "Third coming":
                part_map[tmp['parts'][part]['title']] = part
                data['parts'][part] = newpart
                data['parts'][part]['id'] = part
                data['parts'][part]['event_id'] = new_id
                self.assertEqual(set(data['parts'][part]['tracks'].values()),
                                 set(tmp['parts'][part]['tracks'].values()))
                data['parts'][part]['tracks'] = tmp['parts'][part]['tracks']
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
        data['begin'] = datetime.date(2110, 9, 8)
        data['end'] = datetime.date(2111, 8, 20)
        # TODO dynamically adapt ids from the database result
        data['tracks'] = {4: {'id': 4, 'part_id': 5, 'title': 'Second lecture v2'},
                          6: {'id': 6, 'part_id': 7, 'title': 'Third lecture'}}

        self.assertEqual(data,
                         self.event.get_event(self.key, new_id))

        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_db_events(self.key)
        self.assertIn(new_id, new_events)

        cdata = {
            'event_id': new_id,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'max_size': 12,
            'min_size': None,
            'notes': "Beware of dragons.",
            'segments': {4}, # hardcoded value 4
        }
        new_course_id = self.event.create_course(self.key, cdata)
        cdata['id'] = new_course_id
        cdata['active_segments'] = cdata['segments']
        cdata['fields'] = {'course_id': new_course_id}
        self.assertEqual(cdata, self.event.get_course(
            self.key, new_course_id))

    @as_users("anton", "garcia")
    def test_json_fields_with_dates(self, user):
        event_id = 1
        update_event = {
            'id': event_id,
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "arrival",
                    'kind': "datetime",
                    'entries': None,
                }
            }
        }
        self.event.set_event(self.key, update_event)
        reg_id = 1
        update_registration = {
            'id': reg_id,
            'fields': {
                'arrival': datetime.datetime(2222, 11, 9, 8, 55, 44, tzinfo=pytz.utc),
            }
        }
        self.event.set_registration(self.key, update_registration)
        data = self.event.get_registration(self.key, reg_id)
        expectation = {
            'arrival': datetime.datetime(2222, 11, 9, 8, 55, 44, tzinfo=pytz.utc),
            'lodge': 'Die üblichen Verdächtigen :)',
            'registration_id': 1
        }
        self.assertEqual(expectation, data['fields'])

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
            'segments': {2, 3},
            'active_segments': {2},
            'max_size': 42,
            'min_size': 23,
        }
        new_id = self.event.create_course(self.key, data)
        data['id'] = new_id
        data['fields'] = {'course_id': new_id}
        self.assertEqual(data,
                         self.event.get_course(self.key, new_id))
        data['title'] = "Alternate Universes"
        data['segments'] = {1, 3}
        data['active_segments'] = {1, 3}
        self.event.set_course(self.key, {
            'id': new_id, 'title': data['title'], 'segments': data['segments'],
            'active_segments': data['active_segments']})
        self.assertEqual(data,
                         self.event.get_course(self.key, new_id))
        self.assertNotIn(new_id, old_courses)
        new_courses = self.event.list_db_courses(self.key, event_id)
        self.assertIn(new_id, new_courses)
        data['active_segments'] = {1}
        self.event.set_course(self.key, {
            'id': new_id, 'active_segments': data['active_segments']})
        self.assertEqual(data,
                         self.event.get_course(self.key, new_id))

    @as_users("anton", "garcia")
    def test_course_non_removable(self, user):
        self.assertEqual(False, self.event.is_course_removable(self.key, 1))

    @as_users("anton", "garcia")
    def test_course_delete(self, user):
        event_id = 1
        data = {
            'event_id': event_id,
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'notes': "Beware of dragons.",
            'segments': {2, 3},
            'active_segments': {2},
            'max_size': 42,
            'min_size': 23,
        }
        new_id = self.event.create_course(self.key, data)
        self.assertEqual(True, self.event.is_course_removable(self.key, new_id))
        self.assertLess(0, self.event.delete_course(self.key, new_id))

    @as_users("anton", "garcia")
    def test_visible_events(self, user):
        expectation = {1: 'Große Testakademie 2222'}
        self.assertEqual(expectation, self.event.list_visible_events(self.key))

    @as_users("anton", "garcia")
    def test_has_registrations(self, user):
        self.assertEqual(True, self.event.has_registrations(self.key, 1))

    @as_users("emilia")
    def test_registration_participant(self, user):
        expectation = {
            'checkin': None,
            'event_id': 1,
            'fields': {'registration_id': 2, 'brings_balls': True, 'transportation': 'pedes'},
            'foto_consent': True,
            'id': 2,
            'mixed_lodging': True,
            'orga_notes': 'Unbedingt in die Einzelzelle.',
            'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
            'parental_agreement': None,
            'parts': {
                1: {'is_reserve': False,
                    'lodgement_id': None,
                    'part_id': 1,
                    'registration_id': 2,
                    'status': 3},
                2: {'is_reserve': False,
                    'lodgement_id': 4,
                    'part_id': 2,
                    'registration_id': 2,
                    'status': 4},
                3: {'is_reserve': False,
                    'lodgement_id': 4,
                    'part_id': 3,
                    'registration_id': 2,
                    'status': 2}},
            'tracks': {
                1: {'choices': [5, 4, 1],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 1,},
                2: {'choices': [3, 4, 2],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 2,},
                3: {'choices': [4, 2, 1],
                    'course_id': 1,
                    'course_instructor': 1,
                    'registration_id': 2,
                    'track_id': 3,},},
            'payment': datetime.date(2014, 2, 2),
            'persona_id': 5,
            'real_persona_id': None}
        self.assertEqual(expectation,
                         self.event.get_registration(self.key, 2))
        data = {
            'id': 2,
            'tracks': {2: {'choices': [2, 3, 4]}},
            'fields': {'transportation': 'etc'},
            'mixed_lodging': False,
        }
        self.assertLess(0, self.event.set_registration(self.key, data))
        expectation['tracks'][2]['choices'] = [2, 3, 4]
        expectation['fields']['transportation'] = 'etc'
        expectation['mixed_lodging'] = False
        self.assertEqual(expectation,
                         self.event.get_registration(self.key, 2))

    @as_users("berta")
    def test_registering(self, user):
        new_reg = {
            'checkin': None,
            'event_id': 1,
            'foto_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': None,
            'parts': {
                1: {'is_reserve': False,
                    'lodgement_id': None,
                    'status': 1
                },
                2: {'is_reserve': False,
                    'lodgement_id': None,
                    'status': 1
                },
                3: {'is_reserve': False,
                    'lodgement_id': None,
                    'status': 1
                },
            },
            'tracks': {
                1: {'choices': [1, 4, 5],
                    'course_id': None,
                    'course_instructor': None,
                },
                2: {'course_id': None,
                    'course_instructor': None,
                },
                3: {'course_id': None,
                    'course_instructor': None,
                },
            },
            'notes': "Some bla.",
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None}
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['fields'] = {'registration_id': new_id}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        new_reg['tracks'][1]['track_id'] = 1
        new_reg['tracks'][1]['registration_id'] = new_id
        new_reg['tracks'][2]['track_id'] = 2
        new_reg['tracks'][2]['registration_id'] = new_id
        new_reg['tracks'][2]['choices'] = []
        new_reg['tracks'][3]['track_id'] = 3
        new_reg['tracks'][3]['registration_id'] = new_id
        new_reg['tracks'][3]['choices'] = []
        self.assertEqual(new_reg,
                         self.event.get_registration(self.key, new_id))

    @as_users("anton", "garcia")
    def test_entity_registration(self, user):
        event_id = 1
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9},
                         self.event.list_registrations(self.key, event_id))
        expectation = {
            1: {'checkin': None,
                'event_id': 1,
                'fields': {'registration_id': 1,
                               'lodge': 'Die üblichen Verdächtigen :)'},
                'foto_consent': True,
                'id': 1,
                'mixed_lodging': True,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': None,
                'parts': {
                    1: {'is_reserve': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 1,
                        'status': -1},
                    2: {'is_reserve': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 1,
                        'status': 1},
                    3: {'is_reserve': False,
                        'lodgement_id': 1,
                        'part_id': 3,
                        'registration_id': 1,
                        'status': 2}},
                'tracks': {
                    1: {'choices': [1, 3, 4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 1},
                    2: {'choices': [2, 3, 4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 2},
                    3: {'choices': [1, 4, 5],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 3}},
                'payment': None,
                'persona_id': 1,
                'real_persona_id': None},
            2: {'checkin': None,
                'event_id': 1,
                'fields': {'registration_id': 2, 'brings_balls': True, 'transportation': 'pedes'},
                'foto_consent': True,
                'id': 2,
                'mixed_lodging': True,
                'orga_notes': 'Unbedingt in die Einzelzelle.',
                'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
                'parental_agreement': None,
                'parts': {
                    1: {'is_reserve': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 2,
                        'status': 3},
                    2: {'is_reserve': False,
                        'lodgement_id': 4,
                        'part_id': 2,
                        'registration_id': 2,
                        'status': 4},
                    3: {'is_reserve': False,
                        'lodgement_id': 4,
                        'part_id': 3,
                        'registration_id': 2,
                        'status': 2}},
                'tracks': {
                    1: {'choices': [5, 4, 1],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 1},
                    2: {'choices': [3, 4, 2],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 2},
                    3: {'choices': [4, 2, 1],
                        'course_id': 1,
                        'course_instructor': 1,
                        'registration_id': 2,
                        'track_id': 3}},
                'payment': datetime.date(2014, 2, 2),
                'persona_id': 5,
                'real_persona_id': None},
            4: {'checkin': None,
                'event_id': 1,
                'fields': {'registration_id': 4,
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
                    1: {'is_reserve': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 4,
                        'status': 6},
                    2: {'is_reserve': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 4,
                        'status': 5},
                    3: {'is_reserve': True,
                        'lodgement_id': 2,
                        'part_id': 3,
                        'registration_id': 4,
                        'status': 2}},
                'tracks': {
                    1: {'choices': [1, 4, 5],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 1},
                    2: {'choices': [4, 2, 3],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 2},
                    3: {'choices': [1, 2, 4],
                        'course_id': 1,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 3}},
                'payment': datetime.date(2014, 4, 4),
                'persona_id': 9,
                'real_persona_id': None}}
        self.assertEqual(expectation,
                         self.event.get_registrations(self.key, (1, 2, 4)))
        data = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(pytz.utc),
            'parts': {
                1: {
                    'status': 2,
                    'lodgement_id': 2,
                },
                3: {
                    'status': 6,
                    'lodgement_id': None,
                }
            },
            'tracks': {
                1: {
                    'course_id': 5,
                    'choices': [5, 4, 1],
                },
                2: {
                    'choices': [2, 3, 4],
                },
                3: {
                    'course_id': None,
                }
            }
        }
        self.assertLess(0, self.event.set_registration(self.key, data))
        expectation[4]['tracks'][1]['choices'] = data['tracks'][1]['choices']
        expectation[4]['tracks'][2]['choices'] = data['tracks'][2]['choices']
        expectation[4]['fields'].update(data['fields'])
        expectation[4]['mixed_lodging'] = data['mixed_lodging']
        expectation[4]['checkin'] = nearly_now()
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        for key, value in expectation[4]['tracks'].items():
            if key in data['tracks']:
                value.update(data['tracks'][key])
        data = self.event.get_registrations(self.key, (1, 2, 4))
        self.assertEqual(expectation, data)
        new_reg = {
            'checkin': None,
            'event_id': event_id,
            'foto_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': None,
            'parts': {
                1: {'lodgement_id': None,
                    'status': 1
                },
                2: {'lodgement_id': None,
                    'status': 1
                },
                3: {'lodgement_id': None,
                    'status': 1
                },
            },
            'tracks': {
                1: {'choices': [1, 4, 5],
                    'course_id': None,
                    'course_instructor': None
                },
                2: {'course_id': None,
                    'course_instructor': None
                },
                3: {'course_id': None,
                    'course_instructor': None
                },
            },
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None
        }
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['fields'] = {'registration_id': new_id}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][1]['is_reserve'] = False
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][2]['is_reserve'] = False
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        new_reg['parts'][3]['is_reserve'] = False
        new_reg['tracks'][1]['track_id'] = 1
        new_reg['tracks'][1]['registration_id'] = new_id
        new_reg['tracks'][2]['track_id'] = 2
        new_reg['tracks'][2]['registration_id'] = new_id
        new_reg['tracks'][2]['choices'] = []
        new_reg['tracks'][3]['track_id'] = 3
        new_reg['tracks'][3]['registration_id'] = new_id
        new_reg['tracks'][3]['choices'] = []
        self.assertEqual(new_reg,
                         self.event.get_registration(self.key, new_id))
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, new_id: 2},
                         self.event.list_registrations(self.key, event_id))

    @as_users("anton", "garcia")
    def test_registration_delete(self, user):
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9},
                         self.event.list_registrations(self.key, 1))
        self.event.delete_registration(self.key, 1)
        self.assertEqual({2: 5, 3: 7, 4: 9},
                         self.event.list_registrations(self.key, 1))
        
    @as_users("anton", "garcia")
    def test_course_filtering(self, user):
        event_id = 1
        expectation={1: 1, 2: 5, 3: 7, 4: 9}
        self.assertEqual(expectation, self.event.registrations_by_course(self.key, event_id))
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, track_id=3))
        expectation={1: 1, 2: 5, 3: 7, 4: 9}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1))
        expectation={2: 5, 4: 9}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1, position=ENUMS_DICT['CourseFilterPositions'].assigned))

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
                'fields': {'contamination': 'high', 'lodgement_id': 1},
                'id': 1,
                'moniker': 'Warme Stube',
                'notes': None,
                'reserve': 1},
            4: {
                'capacity': 1,
                'event_id': 1,
                'fields': {'contamination': 'high', 'lodgement_id': 4},
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
        new['fields'] = {'lodgement_id': new_id}
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
                "birthday", "part1.lodgement_id1", "part3.status3", "track2.course_id2",
                "lodge_fields2.xfield_contamination_2", "course_fields1.xfield_room_1",
                "reg_fields.xfield_brings_balls", "reg_fields.xfield_transportation"),
            constraints=[("reg.id", QueryOperators.nonempty, None),
                           ("persona.given_names", QueryOperators.regex, '[aeiou]'),
                           ("part2.status2", QueryOperators.nonempty, None),
                           ("reg_fields.xfield_transportation", QueryOperators.oneof, ['pedes', 'etc'])],
            order=(("reg.id", True),),)
        ## fix query spec (normally done by frontend)
        query.spec.update({
            'part1.lodgement_id1': "int",
            'part3.status3': "int",
            'track2.course_id2': "int",
            'lodge_fields2.xfield_contamination_2': "str",
            'course_fields1.xfield_room_1': "str",
            'reg_fields.xfield_brings_balls': "bool",
            'reg_fields.xfield_transportation': "str",
            'part2.status2': "int",
            })
        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {'birthday': datetime.date(2012, 6, 2),
             'xfield_brings_balls': True,
             'xfield_contamination_2': 'high',
             'course_id2': None,
             'family_name': 'Eventis',
             'id': 2,
             'lodgement_id1': None,
             'payment': datetime.date(2014, 2, 2),
             'is_cde_realm': False,
             'xfield_room_1': None,
             'status3': 2,
             'xfield_transportation': 'pedes'},
            {'birthday': datetime.date(2222, 1, 1),
             'xfield_brings_balls': False,
             'xfield_contamination_2': None,
             'course_id2': None,
             'family_name': 'Iota',
             'id': 4,
             'lodgement_id1': None,
             'payment': datetime.date(2014, 4, 4),
             'is_cde_realm': True,
             'xfield_room_1': None,
             'status3': 2,
             'xfield_transportation': 'etc'})
        self.assertEqual(expectation, result)

    @as_users("anton", "garcia")
    def test_lock_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        self.assertTrue(self.event.get_event(self.key, 1)['offline_lock'])

    @as_users("anton", "garcia")
    def test_export_event(self, user):
        expectation = {
            'CDEDB_EXPORT_EVENT_VERSION': 1,
            'core.personas': {1: {'address': 'Auf der Düne 42',
                                  'address_supplement': None,
                                  'birthday': datetime.date(1991, 3, 30),
                                  'country': None,
                                  'display_name': 'Anton',
                                  'family_name': 'Administrator',
                                  'gender': 2,
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
                                  'postal_code': '03205',
                                  'telephone': '+49 (234) 98765',
                                  'title': None,
                                  'username': 'anton@example.cde'},
                              5: {'address': 'Hohle Gasse 13',
                                  'address_supplement': None,
                                  'birthday': datetime.date(2012, 6, 2),
                                  'country': 'Deutschland',
                                  'display_name': 'Emilia',
                                  'family_name': 'Eventis',
                                  'gender': 1,
                                  'given_names': 'Emilia E.',
                                  'id': 5,
                                  'is_active': True,
                                  'is_admin': False,
                                  'is_archived': False,
                                  'is_assembly_admin': False,
                                  'is_assembly_realm': False,
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
                                  'postal_code': '56767',
                                  'telephone': '+49 (5432) 555666777',
                                  'title': None,
                                  'username': 'emilia@example.cde'},
                              7: {'address': 'Bei der Wüste 39',
                                  'address_supplement': None,
                                  'birthday': datetime.date(1978, 12, 12),
                                  'country': None,
                                  'display_name': 'Garcia',
                                  'family_name': 'Generalis',
                                  'gender': 1,
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
                                  'postal_code': '8888',
                                  'telephone': None,
                                  'title': None,
                                  'username': 'garcia@example.cde'},
                              9: {'address': 'Zwergstraße 1',
                                  'address_supplement': None,
                                  'birthday': datetime.date(2222, 1, 1),
                                  'country': None,
                                  'display_name': 'Inga',
                                  'family_name': 'Iota',
                                  'gender': 1,
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
                                  'postal_code': '1111',
                                  'telephone': None,
                                  'title': None,
                                  'username': 'inga@example.cde'}},
            'event.courses': {1: {'description': 'Wir werden die Bäume drücken.',
                                  'event_id': 1,
                                  'fields': {'course_id': 1, 'room': 'Wald'},
                                  'id': 1,
                                  'instructors': 'ToFi & Co',
                                  'max_size': 10,
                                  'min_size': 3,
                                  'notes': 'Promotionen in Mathematik und Ethik für '
                                  'Teilnehmer notwendig.',
                                  'nr': 'α',
                                  'segments': {1: {'course_id': 1,
                                                   'id': 1,
                                                   'is_active': True,
                                                   'track_id': 1},
                                               3: {'course_id': 1,
                                                   'id': 2,
                                                   'is_active': True,
                                                   'track_id': 3}},
                                  'shortname': 'Heldentum',
                                  'title': 'Planetenretten für Anfänger'},
                              2: {'description': 'Inklusive Post, Backwaren und '
                                  'frühzeitigem Ableben.',
                                  'event_id': 1,
                                  'fields': {'course_id': 2, 'room': 'Theater'},
                                  'id': 2,
                                  'instructors': 'Bernd Lucke',
                                  'max_size': 20,
                                  'min_size': 10,
                                  'notes': 'Kursleiter hat Sekt angefordert.',
                                  'nr': 'β',
                                  'segments': {2: {'course_id': 2,
                                                   'id': 3,
                                                   'is_active': False,
                                                   'track_id': 2},
                                               3: {'course_id': 2,
                                                   'id': 4,
                                                   'is_active': True,
                                                   'track_id': 3}},
                                  'shortname': 'Kabarett',
                                  'title': 'Lustigsein für Fortgeschrittene'},
                              3: {'description': 'mit hoher Leistung.',
                                  'event_id': 1,
                                  'fields': {'course_id': 3, 'room': 'Seminarraum 42'},
                                  'id': 3,
                                  'instructors': 'Heinrich und Thomas Mann',
                                  'max_size': 14,
                                  'min_size': 5,
                                  'notes': None,
                                  'nr': 'γ',
                                  'segments': {2: {'course_id': 3,
                                                   'id': 5,
                                                   'is_active': True,
                                                   'track_id': 2}},
                                  'shortname': 'Kurz',
                                  'title': 'Kurzer Kurs'},
                              4: {'description': 'mit hohem Umsatz.',
                                  'event_id': 1,
                                  'fields': {'course_id': 4, 'room': 'Seminarraum 23'},
                                  'id': 4,
                                  'instructors': 'Stephen Hawking und Richard Feynman',
                                  'max_size': None,
                                  'min_size': None,
                                  'notes': None,
                                  'nr': 'δ',
                                  'segments': {1: {'course_id': 4,
                                                   'id': 6,
                                                   'is_active': True,
                                                   'track_id': 1},
                                               2: {'course_id': 4,
                                                   'id': 7,
                                                   'is_active': True,
                                                   'track_id': 2},
                                               3: {'course_id': 4,
                                                   'id': 8,
                                                   'is_active': True,
                                                   'track_id': 3}},
                                  'shortname': 'Lang',
                                  'title': 'Langer Kurs'},
                              5: {'description': 'damit wir Auswahl haben',
                                  'event_id': 1,
                                  'fields': {'course_id': 5, 'room': 'Nirwana'},
                                  'id': 5,
                                  'instructors': 'TBA',
                                  'max_size': None,
                                  'min_size': None,
                                  'notes': None,
                                  'nr': 'ε',
                                  'segments': {1: {'course_id': 5,
                                                   'id': 9,
                                                   'is_active': True,
                                                   'track_id': 1},
                                               2: {'course_id': 5,
                                                   'id': 10,
                                                   'is_active': True,
                                                   'track_id': 2},
                                               3: {'course_id': 5,
                                                   'id': 11,
                                                   'is_active': False,
                                                   'track_id': 3}},
                                  'shortname': 'Backup',
                                  'title': 'Backup-Kurs'}},
            'event.events': {1: {'description': 'Everybody come!',
                                 'fields': {1: {'association': 1,
                                                'entries': None,
                                                'event_id': 1,
                                                'field_name': 'brings_balls',
                                                'id': 1,
                                                'kind': 'bool'},
                                            2: {'association': 1,
                                                'entries': [['pedes', 'by feet'],
                                                            ['car', 'own car available'],
                                                            ['etc', 'anything else']],
                                                'event_id': 1,
                                                'field_name': 'transportation',
                                                'id': 2,
                                                'kind': 'str'},
                                            3: {'association': 1,
                                                'entries': None,
                                                'event_id': 1,
                                                'field_name': 'lodge',
                                                'id': 3,
                                                'kind': 'str'},
                                            4: {'association': 1,
                                                'entries': None,
                                                'event_id': 1,
                                                'field_name': 'may_reserve',
                                                'id': 4,
                                                'kind': 'bool'},
                                            5: {'association': 2,
                                                'entries': None,
                                                'event_id': 1,
                                                'field_name': 'room',
                                                'id': 5,
                                                'kind': 'str'},
                                            6: {'association': 3,
                                                'entries': [['high', 'lots of radiation'],
                                                            ['medium',
                                                             'elevated level of '
                                                             'radiation'],
                                                            ['low', 'some radiation'],
                                                            ['none', 'no radiation']],
                                                'event_id': 1,
                                                'field_name': 'contamination',
                                                'id': 6,
                                                'kind': 'str'}},
                                 'iban': 'DE96 3702 0500 0008 0689 01',
                                 'id': 1,
                                 'institution': 1,
                                 'is_archived': False,
                                 'is_course_list_visible': True,
                                 'is_visible': True,
                                 'lodge_field': 3,
                                 'mail_text': 'Wir verwenden ein neues '
                                 'Kristallkugel-basiertes '
                                 'Kurszuteilungssystem; bis wir das '
                                 'ordentlich ans Laufen gebracht haben, '
                                 'müsst ihr leider etwas auf die '
                                 'Teilnehmerliste warten.',
                                 'notes': 'Todoliste ... just kidding ;)',
                                 'offline_lock': False,
                                 'orgas': {7: {'event_id': 1, 'id': 1, 'persona_id': 7}},
                                 'parts': {1: {'event_id': 1,
                                               'fee': decimal.Decimal('10.50'),
                                               'id': 1,
                                               'part_begin': datetime.date(2222, 2, 2),
                                               'part_end': datetime.date(2222, 2, 2),
                                               'title': 'Warmup',
                                               'tracks': {}},
                                           2: {'event_id': 1,
                                               'fee': decimal.Decimal('123.00'),
                                               'id': 2,
                                               'part_begin': datetime.date(2222, 11, 1),
                                               'part_end': datetime.date(2222, 11, 11),
                                               'title': 'Erste Hälfte',
                                               'tracks': {1: {'id': 1,
                                                              'part_id': 2,
                                                              'title': 'Morgenkreis '
                                                              '(Erste Hälfte)'},
                                                          2: {'id': 2,
                                                              'part_id': 2,
                                                              'title': 'Kaffeekränzchen '
                                                              '(Erste Hälfte)'}}},
                                           3: {'event_id': 1,
                                               'fee': decimal.Decimal('450.99'),
                                               'id': 3,
                                               'part_begin': datetime.date(2222, 11, 11),
                                               'part_end': datetime.date(2222, 11, 30),
                                               'title': 'Zweite Hälfte',
                                               'tracks': {3: {'id': 3,
                                                              'part_id': 3,
                                                              'title': 'Arbeitssitzung '
                                                              '(Zweite '
                                                              'Hälfte)'}}}},
                                 'questionnaire_rows': {1: {'event_id': 1,
                                                            'field_id': None,
                                                            'id': 1,
                                                            'info': 'mit Text darunter',
                                                            'input_size': None,
                                                            'pos': 0,
                                                            'readonly': None,
                                                            'title': 'Unterüberschrift'},
                                                        2: {'event_id': 1,
                                                            'field_id': 1,
                                                            'id': 2,
                                                            'info': 'Du bringst genug '
                                                            'Bälle mit um einen '
                                                            'ganzen Kurs '
                                                            'abzuwerfen.',
                                                            'input_size': None,
                                                            'pos': 1,
                                                            'readonly': False,
                                                            'title': 'Bälle'},
                                                        3: {'event_id': 1,
                                                            'field_id': None,
                                                            'id': 3,
                                                            'info': 'nur etwas Text',
                                                            'input_size': None,
                                                            'pos': 2,
                                                            'readonly': None,
                                                            'title': None},
                                                        4: {'event_id': 1,
                                                            'field_id': None,
                                                            'id': 4,
                                                            'info': None,
                                                            'input_size': None,
                                                            'pos': 3,
                                                            'readonly': None,
                                                            'title': 'Weitere '
                                                            'Überschrift'},
                                                        5: {'event_id': 1,
                                                            'field_id': 2,
                                                            'id': 5,
                                                            'info': None,
                                                            'input_size': None,
                                                            'pos': 4,
                                                            'readonly': False,
                                                            'title': 'Vehikel'},
                                                        6: {'event_id': 1,
                                                            'field_id': 3,
                                                            'id': 6,
                                                            'info': None,
                                                            'input_size': 3,
                                                            'pos': 5,
                                                            'readonly': False,
                                                            'title': 'Hauswunsch'}},
                                 'registration_hard_limit': datetime.datetime(2220, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'registration_soft_limit': datetime.datetime(2200, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'registration_start': datetime.datetime(2000, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'reserve_field': 4,
                                 'shortname': 'TestAka',
                                 'title': 'Große Testakademie 2222',
                                 'use_questionnaire': False}},
            'event.lodgements': {1: {'capacity': 5,
                                     'event_id': 1,
                                     'fields': {'contamination': 'high',
                                                'lodgement_id': 1},
                                     'id': 1,
                                     'moniker': 'Warme Stube',
                                     'notes': None,
                                     'reserve': 1},
                                 2: {'capacity': 10,
                                     'event_id': 1,
                                     'fields': {'contamination': 'none',
                                                'lodgement_id': 2},
                                     'id': 2,
                                     'moniker': 'Kalte Kammer',
                                     'notes': 'Dafür mit Frischluft.',
                                     'reserve': 2},
                                 3: {'capacity': 0,
                                     'event_id': 1,
                                     'fields': {'contamination': 'low', 'lodgement_id': 3},
                                     'id': 3,
                                     'moniker': 'Kellerverlies',
                                     'notes': 'Nur für Notfälle.',
                                     'reserve': 100},
                                 4: {'capacity': 1,
                                     'event_id': 1,
                                     'fields': {'contamination': 'high',
                                                'lodgement_id': 4},
                                     'id': 4,
                                     'moniker': 'Einzelzelle',
                                     'notes': None,
                                     'reserve': 0}},
            'event.log': {1: {'additional_info': None,
                              'code': 50,
                              'ctime': datetime.datetime(2014, 1, 1, 1, 4, 5, tzinfo=pytz.utc),
                              'event_id': 1,
                              'id': 1,
                              'persona_id': 1,
                              'submitted_by': 1},
                          2: {'additional_info': None,
                              'code': 50,
                              'ctime': datetime.datetime(2014, 1, 1, 2, 5, 6, tzinfo=pytz.utc),
                              'event_id': 1,
                              'id': 2,
                              'persona_id': 5,
                              'submitted_by': 5},
                          3: {'additional_info': None,
                              'code': 50,
                              'ctime': datetime.datetime(2014, 1, 1, 3, 6, 7, tzinfo=pytz.utc),
                              'event_id': 1,
                              'id': 3,
                              'persona_id': 7,
                              'submitted_by': 7},
                          4: {'additional_info': None,
                              'code': 50,
                              'ctime': datetime.datetime(2014, 1, 1, 4, 7, 8, tzinfo=pytz.utc),
                              'event_id': 1,
                              'id': 4,
                              'persona_id': 9,
                              'submitted_by': 9}},
            'event.registrations': {1: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'lodge': 'Die üblichen Verdächtigen :)',
                                                   'registration_id': 1},
                                        'foto_consent': True,
                                        'id': 1,
                                        'mixed_lodging': True,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': None,
                                        'parts': {1: {'id': 1,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 1,
                                                      'registration_id': 1,
                                                      'status': -1},
                                                  2: {'id': 2,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 2,
                                                      'registration_id': 1,
                                                      'status': 1},
                                                  3: {'id': 3,
                                                      'is_reserve': False,
                                                      'lodgement_id': 1,
                                                      'part_id': 3,
                                                      'registration_id': 1,
                                                      'status': 2}},
                                        'payment': None,
                                        'persona_id': 1,
                                        'real_persona_id': None,
                                        'tracks': {1: {'choices': [{'course_id': 1,
                                                                    'id': 1,
                                                                    'rank': 0,
                                                                    'registration_id': 1,
                                                                    'track_id': 1},
                                                                   {'course_id': 3,
                                                                    'id': 2,
                                                                    'rank': 1,
                                                                    'registration_id': 1,
                                                                    'track_id': 1},
                                                                   {'course_id': 4,
                                                                    'id': 3,
                                                                    'rank': 2,
                                                                    'registration_id': 1,
                                                                    'track_id': 1}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 1,
                                                       'registration_id': 1,
                                                       'track_id': 1},
                                                   2: {'choices': [{'course_id': 2,
                                                                    'id': 4,
                                                                    'rank': 0,
                                                                    'registration_id': 1,
                                                                    'track_id': 2},
                                                                   {'course_id': 3,
                                                                    'id': 5,
                                                                    'rank': 1,
                                                                    'registration_id': 1,
                                                                    'track_id': 2},
                                                                   {'course_id': 4,
                                                                    'id': 6,
                                                                    'rank': 2,
                                                                    'registration_id': 1,
                                                                    'track_id': 2}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 2,
                                                       'registration_id': 1,
                                                       'track_id': 2},
                                                   3: {'choices': [{'course_id': 1,
                                                                    'id': 7,
                                                                    'rank': 0,
                                                                    'registration_id': 1,
                                                                    'track_id': 3},
                                                                   {'course_id': 4,
                                                                    'id': 8,
                                                                    'rank': 1,
                                                                    'registration_id': 1,
                                                                    'track_id': 3},
                                                                   {'course_id': 5,
                                                                    'id': 9,
                                                                    'rank': 2,
                                                                    'registration_id': 1,
                                                                    'track_id': 3}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 3,
                                                       'registration_id': 1,
                                                       'track_id': 3}}},
                                    2: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'brings_balls': True,
                                                   'registration_id': 2,
                                                   'transportation': 'pedes'},
                                        'foto_consent': True,
                                        'id': 2,
                                        'mixed_lodging': True,
                                        'notes': 'Extrawünsche: Meerblick, Weckdienst und '
                                        'Frühstück am Bett',
                                        'orga_notes': 'Unbedingt in die Einzelzelle.',
                                        'parental_agreement': None,
                                        'parts': {1: {'id': 4,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 1,
                                                      'registration_id': 2,
                                                      'status': 3},
                                                  2: {'id': 5,
                                                      'is_reserve': False,
                                                      'lodgement_id': 4,
                                                      'part_id': 2,
                                                      'registration_id': 2,
                                                      'status': 4},
                                                  3: {'id': 6,
                                                      'is_reserve': False,
                                                      'lodgement_id': 4,
                                                      'part_id': 3,
                                                      'registration_id': 2,
                                                      'status': 2}},
                                        'payment': datetime.date(2014, 2, 2),
                                        'persona_id': 5,
                                        'real_persona_id': None,
                                        'tracks': {1: {'choices': [{'course_id': 5,
                                                                    'id': 10,
                                                                    'rank': 0,
                                                                    'registration_id': 2,
                                                                    'track_id': 1},
                                                                   {'course_id': 4,
                                                                    'id': 11,
                                                                    'rank': 1,
                                                                    'registration_id': 2,
                                                                    'track_id': 1},
                                                                   {'course_id': 1,
                                                                    'id': 12,
                                                                    'rank': 2,
                                                                    'registration_id': 2,
                                                                    'track_id': 1}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 4,
                                                       'registration_id': 2,
                                                       'track_id': 1},
                                                   2: {'choices': [{'course_id': 3,
                                                                    'id': 13,
                                                                    'rank': 0,
                                                                    'registration_id': 2,
                                                                    'track_id': 2},
                                                                   {'course_id': 4,
                                                                    'id': 14,
                                                                    'rank': 1,
                                                                    'registration_id': 2,
                                                                    'track_id': 2},
                                                                   {'course_id': 2,
                                                                    'id': 15,
                                                                    'rank': 2,
                                                                    'registration_id': 2,
                                                                    'track_id': 2}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 5,
                                                       'registration_id': 2,
                                                       'track_id': 2},
                                                   3: {'choices': [{'course_id': 4,
                                                                    'id': 16,
                                                                    'rank': 0,
                                                                    'registration_id': 2,
                                                                    'track_id': 3},
                                                                   {'course_id': 2,
                                                                    'id': 17,
                                                                    'rank': 1,
                                                                    'registration_id': 2,
                                                                    'track_id': 3},
                                                                   {'course_id': 1,
                                                                    'id': 18,
                                                                    'rank': 2,
                                                                    'registration_id': 2,
                                                                    'track_id': 3}],
                                                       'course_id': 1,
                                                       'course_instructor': 1,
                                                       'id': 6,
                                                       'registration_id': 2,
                                                       'track_id': 3}}},
                                    3: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'registration_id': 3,
                                                   'transportation': 'car'},
                                        'foto_consent': True,
                                        'id': 3,
                                        'mixed_lodging': True,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': None,
                                        'parts': {1: {'id': 7,
                                                      'is_reserve': False,
                                                      'lodgement_id': 2,
                                                      'part_id': 1,
                                                      'registration_id': 3,
                                                      'status': 2},
                                                  2: {'id': 8,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 2,
                                                      'registration_id': 3,
                                                      'status': 2},
                                                  3: {'id': 9,
                                                      'is_reserve': False,
                                                      'lodgement_id': 2,
                                                      'part_id': 3,
                                                      'registration_id': 3,
                                                      'status': 2}},
                                        'payment': datetime.date(2014, 3, 3),
                                        'persona_id': 7,
                                        'real_persona_id': None,
                                        'tracks': {1: {'choices': [{'course_id': 4,
                                                                    'id': 19,
                                                                    'rank': 0,
                                                                    'registration_id': 3,
                                                                    'track_id': 1},
                                                                   {'course_id': 1,
                                                                    'id': 20,
                                                                    'rank': 1,
                                                                    'registration_id': 3,
                                                                    'track_id': 1},
                                                                   {'course_id': 5,
                                                                    'id': 21,
                                                                    'rank': 2,
                                                                    'registration_id': 3,
                                                                    'track_id': 1}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 7,
                                                       'registration_id': 3,
                                                       'track_id': 1},
                                                   2: {'choices': [{'course_id': 2,
                                                                    'id': 22,
                                                                    'rank': 0,
                                                                    'registration_id': 3,
                                                                    'track_id': 2},
                                                                   {'course_id': 3,
                                                                    'id': 23,
                                                                    'rank': 1,
                                                                    'registration_id': 3,
                                                                    'track_id': 2},
                                                                   {'course_id': 4,
                                                                    'id': 24,
                                                                    'rank': 2,
                                                                    'registration_id': 3,
                                                                    'track_id': 2}],
                                                       'course_id': 2,
                                                       'course_instructor': None,
                                                       'id': 8,
                                                       'registration_id': 3,
                                                       'track_id': 2},
                                                   3: {'choices': [{'course_id': 2,
                                                                    'id': 25,
                                                                    'rank': 0,
                                                                    'registration_id': 3,
                                                                    'track_id': 3},
                                                                   {'course_id': 4,
                                                                    'id': 26,
                                                                    'rank': 1,
                                                                    'registration_id': 3,
                                                                    'track_id': 3},
                                                                   {'course_id': 1,
                                                                    'id': 27,
                                                                    'rank': 2,
                                                                    'registration_id': 3,
                                                                    'track_id': 3}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 9,
                                                       'registration_id': 3,
                                                       'track_id': 3}}},
                                    4: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'brings_balls': False,
                                                   'may_reserve': True,
                                                   'registration_id': 4,
                                                   'transportation': 'etc'},
                                        'foto_consent': True,
                                        'id': 4,
                                        'mixed_lodging': False,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': None,
                                        'parts': {1: {'id': 10,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 1,
                                                      'registration_id': 4,
                                                      'status': 6},
                                                  2: {'id': 11,
                                                      'is_reserve': False,
                                                      'lodgement_id': None,
                                                      'part_id': 2,
                                                      'registration_id': 4,
                                                      'status': 5},
                                                  3: {'id': 12,
                                                      'is_reserve': True,
                                                      'lodgement_id': 2,
                                                      'part_id': 3,
                                                      'registration_id': 4,
                                                      'status': 2}},
                                        'payment': datetime.date(2014, 4, 4),
                                        'persona_id': 9,
                                        'real_persona_id': None,
                                        'tracks': {1: {'choices': [{'course_id': 1,
                                                                    'id': 28,
                                                                    'rank': 0,
                                                                    'registration_id': 4,
                                                                    'track_id': 1},
                                                                   {'course_id': 4,
                                                                    'id': 29,
                                                                    'rank': 1,
                                                                    'registration_id': 4,
                                                                    'track_id': 1},
                                                                   {'course_id': 5,
                                                                    'id': 30,
                                                                    'rank': 2,
                                                                    'registration_id': 4,
                                                                    'track_id': 1}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 10,
                                                       'registration_id': 4,
                                                       'track_id': 1},
                                                   2: {'choices': [{'course_id': 4,
                                                                    'id': 31,
                                                                    'rank': 0,
                                                                    'registration_id': 4,
                                                                    'track_id': 2},
                                                                   {'course_id': 2,
                                                                    'id': 32,
                                                                    'rank': 1,
                                                                    'registration_id': 4,
                                                                    'track_id': 2},
                                                                   {'course_id': 3,
                                                                    'id': 33,
                                                                    'rank': 2,
                                                                    'registration_id': 4,
                                                                    'track_id': 2}],
                                                       'course_id': None,
                                                       'course_instructor': None,
                                                       'id': 11,
                                                       'registration_id': 4,
                                                       'track_id': 2},
                                                   3: {'choices': [{'course_id': 1,
                                                                    'id': 34,
                                                                    'rank': 0,
                                                                    'registration_id': 4,
                                                                    'track_id': 3},
                                                                   {'course_id': 2,
                                                                    'id': 35,
                                                                    'rank': 1,
                                                                    'registration_id': 4,
                                                                    'track_id': 3},
                                                                   {'course_id': 4,
                                                                    'id': 36,
                                                                    'rank': 2,
                                                                    'registration_id': 4,
                                                                    'track_id': 3}],
                                                       'course_id': 1,
                                                       'course_instructor': None,
                                                       'id': 12,
                                                       'registration_id': 4,
                                                       'track_id': 3}}}},
            'id': 1,
            'kind': 'full',
            'timestamp': nearly_now()}
        self.assertEqual(expectation, self.event.export_event(self.key, 1))


    @as_users("anton")
    def test_refine_destill_idempotency(self, user):
        zero = self.event.export_event(self.key, 1)
        one = EventBackend.destill_import(zero)
        two = EventBackend.refine_export(one)
        three = EventBackend.destill_import(two)
        four = EventBackend.refine_export(three)
        self.assertEqual(zero, two)
        self.assertEqual(one, three)
        self.assertEqual(two, four)

    @as_users("anton")
    def test_import_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        data = self.event.export_event(self.key, 1)
        new_data = copy.deepcopy(data)
        stored_data = copy.deepcopy(data)
        ##
        ## Apply some changes
        ##

        ## event
        event = new_data['event.events'][1]
        event['description'] = "We are done!"
        ## event parts
        event['parts'][4000] = {
            'event_id': 1,
            'fee': decimal.Decimal('666.66'),
            'id': 4000,
            'part_begin': datetime.date(2345, 1, 1),
            'part_end': datetime.date(2345, 12, 31),
            'title': 'Aftershowparty',
            'tracks': {}}
        ## course tracks
        event['parts'][4000]['tracks'][1100] = {
            'part_id': 4000,
            'id': 1100,
            'title': 'Enlightnment'}
        ## lodgements
        new_data['event.lodgements'][6000] = {
            'capacity': 1,
            'event_id': 1,
            'fields': {'lodgement_id': 6000},
            'id': 6000,
            'moniker': 'Matte im Orgabüro',
            'notes': None,
            'reserve': 0}
        ## registration
        new_data['event.registrations'][1000] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good',
                       'registration_id': 1000},
            'foto_consent': True,
            'id': 1000,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': None,
            'parts': {
                4000: {
                    'id': 5000,
                    'lodgement_id': 6000,
                    'part_id': 4000,
                    'registration_id': 1000,
                    'status': 1}},
            'payment': None,
            'persona_id': 2000,
            'real_persona_id': 2,
            'tracks': {
                1100: {
                    'choices': [],
                    'course_id': 3000,
                    'course_instructor': None,
                    'id': 1200,
                    'track_id': 1100,
                    'registration_id': 1000}}}
        ## orgas
        event['orgas'][2000] = {
            'event_id': 1, 'id': 7000, 'persona_id': 2000}
        ## course
        new_data['event.courses'][3000] = {
            'description': 'Spontankurs',
            'event_id': 1,
            'fields': {'course_id': 3000},
            'id': 3000,
            'instructors': 'Alle',
            'max_size': 111,
            'min_size': 111,
            'notes': None,
            'nr': 'φ',
            'segments': {
                1100: {
                    'course_id': 3000,
                    'id': 8000,
                    'track_id': 1100,
                    'is_active': True}},
            'shortname': 'Spontan',
            'title': 'Spontankurs'}
        ## course choices
        oldreg = new_data['event.registrations'][4]
        newreg = new_data['event.registrations'][1000]
        ## - an update
        oldreg['tracks'][3]['choices'][1] = {
            'course_id': 5, 'id': 35, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        ## - a delete and an insert
        oldreg['tracks'][3]['choices'][2] = {
            'course_id': 4, 'id': 9000, 'track_id': 3, 'rank': 2, 'registration_id': 4}
        ## - an insert
        newreg['tracks'][1100]['choices'].append({
            'course_id': 3000, 'id': 10000, 'track_id': 1100, 'rank': 0, 'registration_id': 1000})
        ## field definitions
        event['fields'][11000] = {
            'association': 1,
            'entries': [['good', 'good'],
                        ['neutral', 'so so'],
                        ['bad', 'not good']],
            'event_id': 1,
            'field_name': 'behaviour',
            'id': 11000,
            'kind': 'str'}
        ## questionnaire rows
        event['questionnaire_rows'][12000] = {
            'event_id': 1,
            'field_id': 11000,
            'id': 12000,
            'info': 'Wie brav wirst Du sein',
            'input_size': None,
            'pos': 1,
            'readonly': True,
            'title': 'Vorsätze'}
        ## Note that the changes above are not entirely consistent/complete (as
        ## in some stuff is missing and another part may throw an error if we
        ## used the resulting data set for real)
        self.assertLess(0, self.event.unlock_import_event(self.key, new_data))
        ## Now we have to fix for new stuff
        event = stored_data['event.events'][1]
        event['offline_lock'] = False
        stored_data['timestamp'] = nearly_now()
        ## Apply the same changes as above but this time with (guessed) correct IDs
        event['description'] = "We are done!"
        event['parts'][5] = {
            'event_id': 1,
            'fee': decimal.Decimal('666.66'),
            'id': 5,
            'part_begin': datetime.date(2345, 1, 1),
            'part_end': datetime.date(2345, 12, 31),
            'title': 'Aftershowparty',
            'tracks': {4: {
                'part_id': 5,
                'id': 4,
                'title': 'Enlightnment'}}}
        stored_data['event.lodgements'][5] = {
            'capacity': 1,
            'event_id': 1,
            'fields': {'lodgement_id': 5},
            'id': 5,
            'moniker': 'Matte im Orgabüro',
            'notes': None,
            'reserve': 0}
        stored_data['event.registrations'][5] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good',
                       'registration_id': 5},
            'foto_consent': True,
            'id': 5,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': None,
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None,
            'parts': {5: {
                'id': 13,
                'is_reserve': False,
                'lodgement_id': 5,
                'part_id': 5,
                'registration_id': 5,
                'status': 1}},
            'tracks': {4: {
                'course_id': 6,
                'course_instructor': None,
                'id': 13,
                'track_id': 4,
                'registration_id': 5}}}
        event['orgas'][2] = {
            'event_id': 1, 'id': 4, 'persona_id': 2}
        stored_data['event.courses'][6] = {
            'description': 'Spontankurs',
            'event_id': 1,
            'fields': {'course_id': 6},
            'id': 6,
            'instructors': 'Alle',
            'max_size': 111,
            'min_size': 111,
            'notes': None,
            'nr': 'φ',
            'shortname': 'Spontan',
            'title': 'Spontankurs',
            'segments': {4: {
                'course_id': 6, 'id': 12, 'track_id': 4, 'is_active': True}}}
        registrations = stored_data['event.registrations']
        registrations[4]['tracks'][3]['choices'][1] = {
            'course_id': 5, 'id': 35, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        registrations[5]['tracks'][4]['choices'] = [{
            'course_id': 6, 'id': 37, 'track_id': 4, 'rank': 0, 'registration_id': 5}]
        registrations[4]['tracks'][3]['choices'][2] = {
            'course_id': 4, 'id': 38, 'track_id': 3, 'rank': 2, 'registration_id': 4}
        event['fields'][7] = {
            'association': 1,
            'entries': [['good', 'good'],
                        ['neutral', 'so so'],
                        ['bad', 'not good']],
            'event_id': 1,
            'field_name': 'behaviour',
            'id': 7,
            'kind': 'str'}
        event['questionnaire_rows'][7] = {
            'event_id': 1,
            'field_id': 7,
            'id': 7,
            'info': 'Wie brav wirst Du sein',
            'input_size': None,
            'pos': 1,
            'readonly': True,
            'title': 'Vorsätze'}

        result = self.event.export_event(self.key, 1)
        ## because it's irrelevant anyway simply paste the result
        stored_data['core.personas'] = result['core.personas']
        ## add log message
        stored_data['event.log'][6] = {
            'additional_info': None,
            'code': 61,
            'ctime': nearly_now(),
            'event_id': 1,
            'id': 6,
            'persona_id': None,
            'submitted_by': 1}

        self.assertEqual(stored_data, result)

    @as_users("anton")
    def test_log(self, user):
        ## first generate some data
        data = {
            'title': "New Link Academy",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'shortname': 'link',
            'registration_start': datetime.datetime(2000, 11, 22, 0, 0, 0, tzinfo=pytz.utc),
            'registration_soft_limit': datetime.datetime(2022, 1, 2, 0, 0, 0, tzinfo=pytz.utc),
            'registration_hard_limit': None,
            'iban': None,
            'mail_text': None,
            'use_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {-1: 'First lecture'},
                    'title': "First coming",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'fee': decimal.Decimal("234.56")},
                -2: {
                    'tracks': {-1: 'Second lecture'},
                    'title': "Second coming",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'fee': decimal.Decimal("0.00")},
            },
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "instrument",
                    'kind': "str",
                    'entries': None,
                },
                -2: {
                    'association': 1,
                    'field_name': "preferred_excursion_date",
                    'kind': "date",
                    'entries': [["2109-8-16", "In the first coming"],
                                ["2110-8-16", "During the second coming"]],
                },
            },
        }
        new_id = self.event.create_event(self.key, data)
        ## correct part and field ids
        tmp = self.event.get_event(self.key, new_id)
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
            'tracks': {-1: "Third lecture"},
            'title': "Third coming",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'fee': decimal.Decimal("123.40")}
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'fee': decimal.Decimal("1.23"),
            'tracks': {4: "Second lecture v2"}, # hardcoded value 4
        }
        newfield = {
            'association': 1,
            'field_name': "kuea",
            'kind': "str",
            'entries': None,
        }
        changed_field = {
            'association': 1,
            'kind': "date",
            'entries': [["2110-8-15", "early second coming"],
                        ["2110-8-17", "late second coming"],],
        }
        self.event.set_event(self.key, {
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
            'max_size': 14,
            'min_size': 5,
            'notes': "Beware of dragons.",
            'segments': {2, 3},
        }
        new_id = self.event.create_course(self.key, data)
        data['title'] = "Alternate Universes"
        data['segments'] = {1, 3}
        self.event.set_course(self.key, {
            'id': new_id, 'title': data['title'], 'segments': data['segments']})
        new_reg = {
            'checkin': None,
            'event_id': 1,
            'foto_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': None,
            'parts': {
                1: {'lodgement_id': None,
                    'status': 1
                },
                2: {'lodgement_id': None,
                    'status': 1
                },
                3: {'lodgement_id': None,
                    'status': 1
                },
            },
            'tracks': {
                1: {'choices': {1: [1, 4, 5]},
                    'course_id': None,
                    'course_instructor': None,
                },
                2: {'course_id': None,
                    'course_instructor': None,
                },
                3: {'course_id': None,
                    'course_instructor': None,
                },
            },
            'notes': "Some bla.",
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None}
        new_id = self.event.create_registration(self.key, new_reg)
        data = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(pytz.utc),
            'parts': {
                1: {
                    'status': 2,
                    'lodgement_id': 2,
                },
                3: {
                    'status': 6,
                    'lodgement_id': None,
                }
            },
            'tracks': {
                1: {
                    'choices': [5, 4, 1],
                    'course_id': 5,
                },
                2: {
                    'choices': [2, 3, 4],
                },
                3: {
                    'course_id': None,
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
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'preferred_excursion_date',
             'code': 21,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'kuea',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'First coming',
             'code': 17,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 37,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second coming',
             'code': 16,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second lecture v2',
             'code': 36,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Third coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Third lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 11,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': 1,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 2,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'instrument',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'preferred_excursion_date',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': 7,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': 2,
             'submitted_by': 1},
            {'additional_info': 'First coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'First lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': 'Second lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 3,
             'persona_id': None,
             'submitted_by': 1},
            {'additional_info': None,
             'code': 50,
             'ctime': datetime.datetime(2014, 1, 1, 4, 7, 8, tzinfo=pytz.utc),
             'event_id': 1,
             'persona_id': 9,
             'submitted_by': 9},
            {'additional_info': None,
             'code': 50,
             'ctime': datetime.datetime(2014, 1, 1, 3, 6, 7, tzinfo=pytz.utc),
             'event_id': 1,
             'persona_id': 7,
             'submitted_by': 7},
            {'additional_info': None,
             'code': 50,
             'ctime': datetime.datetime(2014, 1, 1, 2, 5, 6, tzinfo=pytz.utc),
             'event_id': 1,
             'persona_id': 5,
             'submitted_by': 5},
            {'additional_info': None,
             'code': 50,
             'ctime': datetime.datetime(2014, 1, 1, 1, 4, 5, tzinfo=pytz.utc),
             'event_id': 1,
             'persona_id': 1,
             'submitted_by': 1}
        )
        self.assertEqual(expectation, self.event.retrieve_log(self.key))
