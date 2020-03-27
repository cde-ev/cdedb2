#!/usr/bin/env python3

import collections.abc
import copy
import datetime
import decimal
import json
import pytz

from test.common import (
    BackendTest, as_users, USER_DICT, nearly_now, json_keys_to_int)
from cdedb.backend.event import EventBackend
from cdedb.backend.common import cast_fields
from cdedb.query import QUERY_SPECS, QueryOperators, Query
from cdedb.common import (
    PERSONA_EVENT_FIELDS, PartialImportError, CDEDB_EXPORT_EVENT_VERSION, now,
    PrivilegeError)
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

    @as_users("annika", "garcia")
    def test_entity_event(self, user):
        ## need administrator to create event
        self.login(USER_DICT["annika"])
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
            'nonmember_surcharge': decimal.Decimal("6.66"),
            'registration_text': None,
            'mail_text': None,
            'use_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {
                        -1: {'title': "First lecture",
                             'shortname': "First",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1}
                    },
                    'title': "First coming",
                    'shortname': "first",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'fee': decimal.Decimal("234.56"),
                },
                -2: {
                    'tracks': {
                        -1: {'title': "Second lecture",
                             'shortname': "Second",
                             'num_choices': 3,
                             'min_choices': 1,
                             'sortkey': 1}
                    },
                    'title': "Second coming",
                    'shortname': "second",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'fee': decimal.Decimal("0.00"),
                },
            },
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "instrument",
                    'kind': 1,
                    'entries': None,
                },
                -2: {
                    'association': 1,
                    'field_name': "preferred_excursion_date",
                    'kind': 5,
                    'entries': [["2109-08-16", "In the first coming"],
                                ["2110-08-16", "During the second coming"]],
                },
                -3: {
                    'association': const.FieldAssociations.registration,
                    'field_name': "is_child",
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                }
            },
            'fee_modifiers': {
                -1: {
                    'amount': decimal.Decimal("-7.00"),
                    'field_id': 1003,  # TODO allow specifying a negative id here?
                    'modifier_name': "is_child",
                    'part_id': 1002,  # TODO allow specifying a negative id here?
                }
            }
        }
        new_id = self.event.create_event(self.key, data)
        ## back to normal mode
        self.login(user)
        data['id'] = new_id
        data['offline_lock'] = False
        data['is_archived'] = False
        data['is_participant_list_visible'] = False
        data['courses_in_participant_list'] = False
        data['is_course_list_visible'] = False
        data['is_course_state_visible'] = False
        data['is_visible'] = False
        data['lodge_field'] = None
        data['reserve_field'] = None
        data['course_room_field'] = None
        data['orga_address'] = None
        data['begin'] = datetime.date(2109, 8, 7)
        data['end'] = datetime.date(2110, 8, 20)
        data['is_open'] = True
        # TODO dynamically adapt ids from the database result
        data['parts'][-1]['tracks'][-1].update({'id': 1001, 'part_id': 1001})
        data['parts'][-2]['tracks'][-1].update({'id': 1002, 'part_id': 1002})
        data['tracks'] = {1001: data['parts'][-1]['tracks'][-1],
                          1002: data['parts'][-2]['tracks'][-1]}
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
                    self.assertEqual(set(x['title']
                                         for x in data['parts'][part]['tracks'].values()),
                                     set(x['title']
                                         for x in tmp['parts'][part]['tracks'].values()))
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
        fee_modifier_map = {}
        for mod in tmp['fee_modifiers']:
            for oldmod in data['fee_modifiers']:
                if (tmp['fee_modifiers'][mod]['modifier_name']
                        == data['fee_modifiers'][oldmod]['modifier_name']):
                    fee_modifier_map[tmp['fee_modifiers'][mod]['modifier_name']] = mod
                    data['fee_modifiers'][mod] = data['fee_modifiers'][oldmod]
                    data['fee_modifiers'][mod]['id'] = mod
                    break
            del data['fee_modifiers'][oldmod]

        self.assertEqual(data,
                         self.event.get_event(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        data['orgas'] = {2, 7}
        newpart = {
            'tracks': {
                -1: {'title': "Third lecture",
                     'shortname': "Third",
                     'num_choices': 2,
                     'min_choices': 2,
                     'sortkey': 2}
            },
            'title': "Third coming",
            'shortname': "third",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'fee': decimal.Decimal("123.40"),
        }
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'fee': decimal.Decimal("1.23"),
            'tracks': {
                1002: {'title': "Second lecture v2",
                       'shortname': "Second v2",
                       'num_choices': 5,
                       'min_choices': 4,
                       'sortkey': 3}
            }}
        newfield = {
            'association': 3,
            'field_name': "kuea",
            'kind': 1,
            'entries': None,
        }
        changed_field = {
            'association': 2,
            'kind': 5,
            'entries': [["2110-08-15", "early second coming"],
                        ["2110-08-17", "late second coming"],],
        }
        self.event.set_event(self.key, {
            'id': new_id,
            'title': data['title'],
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
                self.assertEqual(set(x['title']
                                     for x in data['parts'][part]['tracks'].values()),
                                 set(x['title']
                                     for x in tmp['parts'][part]['tracks'].values()))
                data['parts'][part]['tracks'] = tmp['parts'][part]['tracks']
        del data['parts'][part_map["First coming"]]
        changed_part['id'] = part_map["Second coming"]
        changed_part['event_id'] = new_id
        changed_part['shortname'] = "second"
        changed_part['tracks'][1002].update({'part_id': 1002, 'id': 1002})
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
        data['tracks'] = {1002: {'id': 1002,
                                 'part_id': 1002,
                                 'title': 'Second lecture v2',
                                 'shortname': "Second v2",
                                 'num_choices': 5,
                                 'min_choices': 4,
                                 'sortkey': 3},
                          1003: {'id': 1003,
                                 'part_id': 1003,
                                 'title': 'Third lecture',
                                 'shortname': 'Third',
                                 'num_choices': 2,
                                 'min_choices': 2,
                                 'sortkey': 2}}

        self.assertEqual(data,
                         self.event.get_event(self.key, new_id))

        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_db_events(self.key)
        self.assertIn(new_id, new_events)

        new_course = {
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
            'segments': {1002},
        }
        new_course_id = self.event.create_course(self.key, new_course)
        new_course['id'] = new_course_id
        new_course['active_segments'] = new_course['segments']
        new_course['fields'] = {}
        self.assertEqual(new_course, self.event.get_course(
            self.key, new_course_id))

        new_group = {
            'event_id': new_id,
            'moniker': "Nebenan",
        }
        new_group_id = self.event.create_lodgement_group(self.key, new_group)
        self.assertLess(0, new_group_id)
        new_group['id'] = new_group_id
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))

        new_lodgement = {
            'capacity': 42,
            'event_id': new_id,
            'moniker': 'Hyrule',
            'notes': "Notizen",
            'reserve': 11,
            'group_id': new_group_id,
        }
        new_lodge_id = self.event.create_lodgement(self.key, new_lodgement)
        self.assertLess(0, new_lodge_id)
        new_lodgement['id'] = new_lodge_id
        new_lodgement['fields'] = {}
        self.assertEqual(new_lodgement, self.event.get_lodgement(
            self.key, new_lodge_id))

        new_reg = {
            'checkin': None,
            'event_id': new_id,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': True,
            'parts': {
                part_map["Second coming"]: {'lodgement_id': new_lodge_id,
                                            'status': 1
                                            },
                part_map["Third coming"]: {'lodgement_id': new_lodge_id,
                                           'status': 1
                                           },

            },
            'tracks': {
                1002: {'choices': [new_course_id],
                       'course_id': None,
                       'course_instructor': None
                      },
                1003: {'course_id': None,
                       'course_instructor': None
                      },
            },
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None
        }
        new_reg_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_reg_id)

        self.login(USER_DICT["annika"])
        self.assertLess(0, self.event.delete_event(
            self.key, new_id,
            ("event_parts", "course_tracks", "field_definitions", "courses",
             "orgas", "lodgement_groups", "lodgements", "registrations",
             "questionnaire", "log", "mailinglists", "fee_modifiers")))

    @as_users("annika")
    def test_aposteriori_track_creation(self, user):
        event_id = 1
        part_id = 1
        # The expected new id.
        new_track_id = 1001

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id))
        event = self.event.get_event(self.key, event_id)

        new_track = {
            'title': "Neue Kursschiene",
            'shortname': "Neu",
            'num_choices': 3,
            'min_choices': 1,
            'sortkey': 1,
        }
        update_event = {
            'id': event_id,
            'parts': {
                part_id: {
                    'tracks': {
                        -1: new_track,
                    }
                }
            }
        }
        self.event.set_event(self.key, update_event)
        new_track['id'] = new_track_id
        new_track['part_id'] = part_id

        for reg in regs.values():
            reg['tracks'][new_track_id] = {
                'choices': [],
                'course_id': None,
                'course_instructor': None,
                'registration_id': reg['id'],
                'track_id': new_track_id,
            }

        event['tracks'][new_track_id] = new_track
        event['parts'][part_id]['tracks'][new_track_id] = new_track

        self.assertEqual(regs, self.event.get_registrations(self.key, self.event.list_registrations(self.key, event_id)))
        self.assertEqual(event, self.event.get_event(self.key, event_id))

    @as_users("annika", "garcia")
    def test_aposteriori_track_deletion(self, user):
        event_id = 1
        part_id = 2
        track_id = 1

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id))
        event = self.event.get_event(self.key, event_id)

        expectation = {1, 2, 3}
        self.assertEqual(expectation, event["tracks"].keys())
        self.assertIn(track_id, event["parts"][part_id]["tracks"])
        for reg in regs.values():
            self.assertIn(track_id, reg["tracks"])

        edata = {
            'id': event_id,
            'parts': {
                part_id: {
                    'tracks': {
                        track_id: None,
                    },
                },
            },
        }

        self.assertLess(0, self.event.set_event(self.key, edata))
        event = self.event.get_event(self.key, event_id)
        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id))

        for reg in regs.values():
            self.assertNotIn(track_id, reg["tracks"])

        expectation -= {track_id}
        self.assertEqual(expectation, event["tracks"].keys())

    @as_users("anton")
    def test_event_field_double_link(self, user):
        questionnaire = [
            {
                'kind': const.QuestionnaireUsages.questionnaire,
                'field_id': 1,
                'title': None,
                'info': None,
                'input_size': None,
                'readonly': False,
                'default_value': None,
            },
            {
                'kind': const.QuestionnaireUsages.questionnaire,
                'field_id': 1,
                'title': None,
                'info': None,
                'input_size': None,
                'readonly': False,
                'default_value': None,
            },
        ]
        with self.assertRaises(ValueError) as cm:
            self.event.set_questionnaire(self.key, 1, questionnaire)
        self.assertIn("Must not duplicate field. (field_id)", cm.exception.args)

        old_event = self.event.get_event(self.key, 2)
        self.event.set_questionnaire(self.key, old_event['id'], [])
        data = {
            'id': old_event['id'],
            'fee_modifiers':
                {
                    anid: None
                    for anid in old_event['fee_modifiers']
                }
        }
        self.event.set_event(self.key, data)

        data = {
            'id': old_event['id'],
            'fee_modifiers': {
                -1: {
                    'field_id': list(old_event['fields'])[0],
                    'modifier_name': "is_child",
                    'amount': decimal.Decimal("-8.00"),
                    'part_id': list(old_event['parts'])[0],
                },
                -2: {
                    'field_id': list(old_event['fields'])[0],
                    'modifier_name': "is_child2",
                    'amount': decimal.Decimal("-7.00"),
                    'part_id': list(old_event['parts'])[0],
                },
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.set_event(self.key, data)
        msg = "Must not have multiple fee modifiers linked to the same" \
              " field in one event part."
        self.assertIn(msg + " (fee_modifiers)", cm.exception.args)

    @as_users("annika", "garcia")
    def test_json_fields_with_dates(self, user):
        event_id = 1
        update_event = {
            'id': event_id,
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "arrival",
                    'kind': 6,
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
        }
        self.assertEqual(expectation, data['fields'])

    @as_users("annika", "garcia")
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
        data['fields'] = {}
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

    @as_users("annika", "garcia")
    def test_course_non_removable(self, user):
        self.assertNotEqual({}, self.event.delete_course_blockers(self.key, 1))

    @as_users("annika", "garcia")
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
        self.assertEqual(
            self.event.delete_course_blockers(self.key, new_id).keys(),
            {"course_segments"})
        self.assertLess(0, self.event.delete_course(
            self.key, new_id, ("course_segments",)))

    @as_users("garcia")
    def test_course_choices_cascade(self, user):
        # Set the status quo.
        for course_id in (1, 2, 3, 4):
            cdata = {
                "id": course_id,
                "segments": [1, 2, 3],
                "active_segments": [1, 2, 3],
            }
            self.event.set_course(self.key, cdata)
        for reg_id in (1, 2, 3, 4):
            rdata = {
                "id": reg_id,
                "tracks": {
                    1: {
                        "choices": [1, 2, 3, 4],
                    },
                },
                "parts": {
                    1: {
                        "status": const.RegistrationPartStati.participant,
                    },
                },
            }
            self.event.set_registration(self.key, rdata)

        # Check that all for choices are present fpr registration 1.
        full_export = self.event.export_event(self.key, event_id=1)
        for course_choice in full_export["event.course_choices"].values():
            del course_choice["id"]
        expectations = [
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 1,
                "rank": 0,
            },
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 2,
                "rank": 1,
            },
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 3,
                "rank": 2,
            },
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 4,
                "rank": 3,
            },
        ]
        for exp in expectations:
            self.assertIn(exp, full_export["event.course_choices"].values())

        # Delete Course 2.
        cascade = self.event.delete_course_blockers(self.key, course_id=2)
        self.event.delete_course(self.key, course_id=2, cascade=cascade)

        # Check that the remaining three course choices have been moved up.
        full_export = self.event.export_event(self.key, event_id=1)
        for course_choice in full_export["event.course_choices"].values():
            del course_choice["id"]
        expectations = [
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 1,
                "rank": 0,
            },
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 3,
                "rank": 1,
            },
            {
                "registration_id": 1,
                "track_id": 1,
                "course_id": 4,
                "rank": 2,
            },
        ]
        for exp in expectations:
            self.assertIn(exp, full_export["event.course_choices"].values())

        # Check that no additional or duplicate choices exist.
        partial_export = self.event.partial_export_event(self.key, event_id=1)
        self.assertEqual(
            [1, 3, 4],
            partial_export["registrations"][1]["tracks"][1]["choices"])

    @as_users("annika", "garcia")
    def test_visible_events(self, user):
        expectation = {1: 'Große Testakademie 2222'}
        self.assertEqual(expectation, self.event.list_db_events(
            self.key, visible=True, archived=False))

    @as_users("annika", "garcia")
    def test_has_registrations(self, user):
        self.assertEqual(True, self.event.has_registrations(self.key, 1))

    @as_users("emilia")
    def test_registration_participant(self, user):
        expectation = {
            'amount_paid': decimal.Decimal("0.00"),
            'amount_owed': decimal.Decimal("589.49"),
            'checkin': None,
            'event_id': 1,
            'fields': {'brings_balls': True, 'transportation': 'pedes'},
            'list_consent': True,
            'id': 2,
            'mixed_lodging': True,
            'orga_notes': 'Unbedingt in die Einzelzelle.',
            'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
            'parental_agreement': True,
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
                1: {'choices': [5, 4, 2, 1],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 1,},
                2: {'choices': [3],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 2,},
                3: {'choices': [4, 2],
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

    @as_users("berta", "nina")
    def test_registering(self, user):
        new_reg = {
            'amount_paid': decimal.Decimal("42.00"),
            'checkin': None,
            'event_id': 1,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': True,
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
            'persona_id': 14,
            'real_persona_id': None}
        # try to create a registration for nina
        if user['id'] == USER_DICT['nina']['id']:
            new_id = self.event.create_registration(self.key, new_reg)
            self.assertLess(0, new_id)
            new_reg['id'] = new_id
            new_reg['amount_owed'] = decimal.Decimal("589.49")
            new_reg['fields'] = {}
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
        else:
            with self.assertRaises(PrivilegeError):
                self.event.create_registration(self.key, new_reg)

    @as_users("annika", "garcia")
    def test_entity_registration(self, user):
        event_id = 1
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, 5: 100},
                         self.event.list_registrations(self.key, event_id))
        expectation = {
            1: {'amount_owed': decimal.Decimal("573.99"),
                'amount_paid': decimal.Decimal("0.00"),
                'checkin': None,
                'event_id': 1,
                'fields': {'lodge': 'Die üblichen Verdächtigen :)'},
                'list_consent': True,
                'id': 1,
                'mixed_lodging': True,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': True,
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
                    1: {'choices': [1, 3, 4, 2],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 1},
                    2: {'choices': [2],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 2},
                    3: {'choices': [1, 4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 3}},
                'payment': None,
                'persona_id': 1,
                'real_persona_id': None},
            2: {'amount_owed': decimal.Decimal("589.49"),
                'amount_paid': decimal.Decimal("0.00"),
                'checkin': None,
                'event_id': 1,
                'fields': {'brings_balls': True, 'transportation': 'pedes'},
                'list_consent': True,
                'id': 2,
                'mixed_lodging': True,
                'orga_notes': 'Unbedingt in die Einzelzelle.',
                'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
                'parental_agreement': True,
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
                    1: {'choices': [5, 4, 2, 1],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 1},
                    2: {'choices': [3],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 2},
                    3: {'choices': [4, 2],
                        'course_id': 1,
                        'course_instructor': 1,
                        'registration_id': 2,
                        'track_id': 3}},
                'payment': datetime.date(2014, 2, 2),
                'persona_id': 5,
                'real_persona_id': None},
            4: {'amount_owed': decimal.Decimal("450.99"),
                'amount_paid': decimal.Decimal("0.00"),
                'checkin': None,
                'event_id': 1,
                'fields': {'brings_balls': False,
                           'may_reserve': True,
                           'transportation': 'etc'},
                'list_consent': False,
                'id': 4,
                'mixed_lodging': False,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': False,
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
                    1: {'choices': [2, 1, 4, 5],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 1},
                    2: {'choices': [4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 2},
                    3: {'choices': [1, 2],
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
                    'choices': [5, 4, 1, 2],
                },
                2: {
                    'choices': [2],
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
        expectation[4]['amount_owed'] = decimal.Decimal("10.50")
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        for key, value in expectation[4]['tracks'].items():
            if key in data['tracks']:
                value.update(data['tracks'][key])
        data = self.event.get_registrations(self.key, (1, 2, 4))
        self.assertEqual(expectation, data)
        new_reg = {
            'amount_paid': decimal.Decimal("0.00"),
            'checkin': None,
            'event_id': event_id,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': False,
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
                1: {'choices': [1, 2, 4, 5],
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
        new_reg['amount_owed'] = decimal.Decimal("584.49")
        new_reg['fields'] = {}
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
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, 5: 100, new_id: 2},
                         self.event.list_registrations(self.key, event_id))

    @as_users("annika", "garcia")
    def test_registration_delete(self, user):
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, 5: 100},
                         self.event.list_registrations(self.key, 1))
        self.assertLess(0, self.event.delete_registration(
            self.key, 1, ("registration_parts", "registration_tracks",
                          "course_choices")))
        self.assertEqual({2: 5, 3: 7, 4: 9, 5: 100},
                         self.event.list_registrations(self.key, 1))

    @as_users("annika", "garcia")
    def test_course_filtering(self, user):
        event_id = 1
        expectation={1: 1, 2: 5, 3: 7, 4: 9, 5: 100}
        self.assertEqual(expectation, self.event.registrations_by_course(self.key, event_id))
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, track_id=3))
        expectation={1: 1, 2: 5, 3: 7, 4: 9, 5: 100}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1))
        expectation={2: 5, 4: 9, 5: 100}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1, position=ENUMS_DICT['CourseFilterPositions'].assigned))

    @as_users("annika", "garcia")
    def test_entity_lodgement_group(self, user):
        event_id = 1
        expectation_list = {
            1: "Haupthaus",
            2: "AußenWohnGruppe",
        }
        group_ids = self.event.list_lodgement_groups(self.key, event_id)
        self.assertEqual(expectation_list, group_ids)

        expectation_groups = {
            1: {
                'id': 1,
                'event_id': 1,
                'moniker': "Haupthaus",
            },
            2: {
                'id': 2,
                'event_id': 1,
                'moniker': "AußenWohnGruppe",
            },
        }
        self.assertEqual(expectation_groups,
                         self.event.get_lodgement_groups(self.key, group_ids))

        new_group = {
            'event_id': event_id,
            'moniker': "Nebenan",
        }
        new_group_id = self.event.create_lodgement_group(self.key, new_group)
        self.assertLess(0, new_group_id)
        new_group['id'] = new_group_id
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))
        update = {
            'id': new_group_id,
            'moniker': "Auf der anderen Rheinseite",
        }
        self.assertLess(0, self.event.set_lodgement_group(self.key, update))
        new_group.update(update)
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))

        new_lodgement = {
            'capacity': 42,
            'event_id': 1,
            'moniker': 'Hyrule',
            'notes': "Notizen",
            'reserve': 11,
            'group_id': new_group_id,
        }
        new_lodgement_id = self.event.create_lodgement(self.key, new_lodgement)
        self.assertLess(0, new_lodgement_id)
        new_lodgement['id'] = new_lodgement_id
        new_lodgement['fields'] = {}
        self.assertEqual(
            new_lodgement, self.event.get_lodgement(self.key, new_lodgement_id))

        expectation_list[new_group_id] = new_group['moniker']
        self.assertEqual(expectation_list,
                         self.event.list_lodgement_groups(self.key, event_id))
        self.assertLess(
            0, self.event.delete_lodgement_group(
                self.key, new_group_id, ("lodgements",)))
        del expectation_list[new_group_id]
        self.assertEqual(expectation_list,
                         self.event.list_lodgement_groups(self.key, event_id))

        new_lodgement['group_id'] = None
        self.assertEqual(
            new_lodgement, self.event.get_lodgement(self.key, new_lodgement_id))

    @as_users("annika", "garcia")
    def test_entity_lodgement(self, user):
        event_id = 1
        expectation_list = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle',
        }
        self.assertEqual(expectation_list,
                         self.event.list_lodgements(self.key, event_id))
        expectation_get = {
            1: {
                'capacity': 5,
                'event_id': 1,
                'fields': {'contamination': 'high'},
                'id': 1,
                'moniker': 'Warme Stube',
                'notes': None,
                'reserve': 1,
                'group_id': 2,
            },
            4: {
                'capacity': 1,
                'event_id': 1,
                'fields': {'contamination': 'high'},
                'id': 4,
                'moniker': 'Einzelzelle',
                'notes': None,
                'reserve': 0,
                'group_id': 1,
            }
        }
        self.assertEqual(expectation_get, self.event.get_lodgements(self.key, (1,4)))
        new = {
            'capacity': 42,
            'event_id': 1,
            'moniker': 'Hyrule',
            'notes': "Notizen",
            'reserve': 11,
            'group_id': None,
        }
        new_id = self.event.create_lodgement(self.key, new)
        self.assertLess(0, new_id)
        new['id'] = new_id
        new['fields'] = {}
        self.assertEqual(new, self.event.get_lodgement(self.key, new_id))
        update = {
            'capacity': 21,
            'notes': None,
            'id': new_id,
        }
        self.assertLess(0, self.event.set_lodgement(self.key, update))
        new.update(update)
        self.assertEqual(new, self.event.get_lodgement(self.key, new_id))
        expectation_list = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle',
            new_id: 'Hyrule',
        }
        self.assertEqual(expectation_list,
                         self.event.list_lodgements(self.key, event_id))
        self.assertLess(0, self.event.delete_lodgement(self.key, new_id))
        del expectation_list[new_id]
        self.assertEqual(expectation_list,
                         self.event.list_lodgements(self.key, event_id))

    @as_users("berta", "emilia")
    def test_get_questionnaire(self, user):
        event_id = 1
        expectation = [
            {'field_id': None,
             'default_value': None,
             'info': 'mit Text darunter',
             'pos': 0,
             'readonly': None,
             'input_size': None,
             'title': 'Unterüberschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 1,
             'default_value': 'True',
             'info': 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.',
             'pos': 1,
             'readonly': False,
             'input_size': None,
             'title': 'Bälle',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': 'nur etwas Text',
             'pos': 2,
             'readonly': None,
             'input_size': None,
             'title': None,
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': None,
             'pos': 3,
             'readonly': None,
             'input_size': None,
             'title': 'Weitere Überschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 2,
             'default_value': 'etc',
             'info': None,
             'pos': 4,
             'readonly': False,
             'input_size': None,
             'title': 'Vehikel',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 3,
             'default_value': None,
             'info': None,
             'pos': 5,
             'readonly': False,
             'input_size': 3,
             'title': 'Hauswunsch',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
        ]
        self.assertEqual(expectation,
                         self.event.get_questionnaire(self.key, event_id))

    @as_users("annika", "garcia")
    def test_set_questionnaire(self, user):
        event_id = 1
        expectation = [
            {'field_id': None,
             'default_value': None,
             'info': None,
             'readonly': None,
             'input_size': None,
             'title': 'Weitere bla Überschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 2,
             'default_value': 'etc',
             'info': None,
             'readonly': True,
             'input_size': None,
             'title': 'Vehikel',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': 'mit Text darunter und so',
             'readonly': None,
             'input_size': None,
             'title': 'Unterüberschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 3,
             'default_value': None,
             'info': None,
             'readonly': True,
             'input_size': 5,
             'title': 'Vehikel',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': 'nur etwas mehr Text',
             'readonly': None,
             'input_size': None,
             'title': None,
             'kind': const.QuestionnaireUsages.questionnaire,
             },
        ]
        self.assertLess(0, self.event.set_questionnaire(
            self.key, event_id, expectation))
        for pos, entry in enumerate(expectation):
            entry['pos'] = pos
        self.assertEqual(expectation,
                         self.event.get_questionnaire(self.key, event_id))

    @as_users("annika", "garcia")
    def test_registration_query(self, user):
        query = Query(
            scope="qview_registration",
            spec=dict(QUERY_SPECS["qview_registration"]),
            fields_of_interest=(
                "reg.id", "reg.payment", "is_cde_realm", "persona.family_name",
                "birthday", "lodgement1.id", "part3.status",
                "course2.id", "course1.xfield_room",
                "lodgement2.xfield_contamination",
                "reg_fields.xfield_brings_balls",
                "reg_fields.xfield_transportation"),
            constraints=[
                ("reg.id", QueryOperators.nonempty, None),
                ("persona.given_names", QueryOperators.regex, '[aeiou]'),
                ("part2.status", QueryOperators.nonempty, None),
                ("reg_fields.xfield_transportation", QueryOperators.oneof,
                 ['pedes', 'etc'])],
            order=(("reg.id", True),),)

        ## fix query spec (normally done by frontend)
        query.spec.update({
            'lodgement1.id': "int",
            'part3.status': "int",
            'course2.id': "int",
            'lodgement2.xfield_contamination': "str",
            'course1.xfield_room': "str",
            'reg_fields.xfield_brings_balls': "bool",
            'reg_fields.xfield_transportation': "str",
            'part2.status': "int",
            })
        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {'birthday': datetime.date(2012, 6, 2),
             'reg_fields.xfield_brings_balls': True,
             'lodgement2.xfield_contamination': 'high',
             'course2.id': None,
             'persona.family_name': 'Eventis',
             'reg.id': 2,
             'id': 2,  # un-aliased id from QUERY_PRIMARIES / ordering
             'lodgement1.id': None,
             'reg.payment': datetime.date(2014, 2, 2),
             'is_cde_realm': False,
             'course1.xfield_room': None,
             'part3.status': 2,
             'reg_fields.xfield_transportation': 'pedes'},
            {'birthday': datetime.date(2222, 1, 1),
             'reg_fields.xfield_brings_balls': False,
             'lodgement2.xfield_contamination': None,
             'course2.id': None,
             'persona.family_name': 'Iota',
             'reg.id': 4,
             'id': 4,  # un-aliased id from QUERY_PRIMARIES / ordering
             'lodgement1.id': None,
             'reg.payment': datetime.date(2014, 4, 4),
             'is_cde_realm': True,
             'course1.xfield_room': None,
             'part3.status': 2,
             'reg_fields.xfield_transportation': 'etc'},
            {'birthday': datetime.date(2019, 12, 28),
             'course1.xfield_room': None,
             'course2.id': 2,
             'id': 5,
             'is_cde_realm': True,
             'lodgement1.id': 4,
             'lodgement2.xfield_contamination': 'high',
             'part3.status': 2,
             'persona.family_name': 'Abukara',
             'reg.id': 5,
             'reg.payment': None,
             'reg_fields.xfield_brings_balls': None,
             'reg_fields.xfield_transportation': 'pedes'})
        self.assertEqual(expectation, result)

    @as_users("annika")
    def test_is_instructor_query(self, user):
        registrations = (
            {
                "id": 1,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value
                    }
                },
                "tracks": {
                    1: {
                        "course_id": 1,
                        "course_instructor": 1,
                    }
                },
            },
            {
                "id": 2,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value
                    }
                },
                "tracks": {
                    1: {
                        "course_id": 1,
                        "course_instructor": None,
                    }
                },
            },
            {
                "id": 3,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value
                    }
                },
                "tracks": {
                    1: {
                        "course_id": None,
                        "course_instructor": 1,
                    }
                },
            },
            {
                "id": 4,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value
                    }
                },
                "tracks": {
                    1: {
                        "course_id": None,
                        "course_instructor": None,
                    }
                },
            },
        )

        for reg in registrations:
            self.assertLess(0, self.event.set_registration(self.key, reg))

        query = Query(
            scope="qview_registration",
            spec=dict(QUERY_SPECS["qview_registration"]),
            fields_of_interest=("reg.id", "track1.is_course_instructor"),
            constraints=[],
            order=(("reg.id", True),)
        )

        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {
                "id": 1,
                "reg.id": 1,
                "track1.is_course_instructor": True,
            },
            {
                "id": 2,
                "reg.id": 2,
                "track1.is_course_instructor": None,
            },
            {
                "id": 3,
                "reg.id": 3,
                "track1.is_course_instructor": False,
            },
            {
                "id": 4,
                "reg.id": 4,
                "track1.is_course_instructor": None,
            },
            {
                "id": 5,
                "reg.id": 5,
                'track1.is_course_instructor': None,
            }
        )
        self.assertEqual(expectation, result)

    @as_users("annika", "garcia")
    def test_lock_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        self.assertTrue(self.event.get_event(self.key, 1)['offline_lock'])

    @as_users("annika", "garcia")
    def test_export_event(self, user):
        expectation =  {
            'CDEDB_EXPORT_EVENT_VERSION': CDEDB_EXPORT_EVENT_VERSION,
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
                                  'is_meta_admin': True,
                                  'is_archived': False,
                                  'is_assembly_admin': True,
                                  'is_assembly_realm': True,
                                  'is_cde_admin': True,
                                  'is_finance_admin': True,
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
                                  'is_meta_admin': False,
                                  'is_archived': False,
                                  'is_assembly_admin': False,
                                  'is_assembly_realm': False,
                                  'is_cde_admin': False,
                                  'is_finance_admin': False,
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
                                  'is_meta_admin': False,
                                  'is_archived': False,
                                  'is_assembly_admin': False,
                                  'is_assembly_realm': True,
                                  'is_cde_admin': False,
                                  'is_finance_admin': False,
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
                                  'postal_code': '88484',
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
                                  'is_meta_admin': False,
                                  'is_archived': False,
                                  'is_assembly_admin': False,
                                  'is_assembly_realm': True,
                                  'is_cde_admin': False,
                                  'is_finance_admin': False,
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
                                  'postal_code': '10999',
                                  'telephone': None,
                                  'title': None,
                                  'username': 'inga@example.cde'},
                              100: {
                                  'address': 'Kasumigaseki 1-3-2',
                                  'address_supplement': None,
                                  'birthday': datetime.date(2019, 12, 28),
                                  'country': 'Japan',
                                  'display_name': 'Akira',
                                  'family_name': 'Abukara',
                                  'gender': 10,
                                  'given_names': 'Akira',
                                  'id': 100,
                                  'is_active': True,
                                  'is_archived': False,
                                  'is_assembly_admin': True,
                                  'is_assembly_realm': True,
                                  'is_cde_admin': True,
                                  'is_cde_realm': True,
                                  'is_core_admin': True,
                                  'is_event_admin': True,
                                  'is_event_realm': True,
                                  'is_finance_admin': True,
                                  'is_member': True,
                                  'is_meta_admin': True,
                                  'is_ml_admin': True,
                                  'is_ml_realm': True,
                                  'is_searchable': True,
                                  'location': 'Tokyo',
                                  'mobile': None,
                                  'name_supplement': None,
                                  'postal_code': None,
                                  'telephone': '+81 (314) 159263',
                                  'title': None,
                                  'username': 'akira@example.cde'}
                              },
            'event.course_choices': {1: {'course_id': 1,
                                         'id': 1,
                                         'rank': 0,
                                         'registration_id': 1,
                                         'track_id': 1},
                                     2: {'course_id': 3,
                                         'id': 2,
                                         'rank': 1,
                                         'registration_id': 1,
                                         'track_id': 1},
                                     3: {'course_id': 4,
                                         'id': 3,
                                         'rank': 2,
                                         'registration_id': 1,
                                         'track_id': 1},
                                     4: {'course_id': 2,
                                         'id': 4,
                                         'rank': 3,
                                         'registration_id': 1,
                                         'track_id': 1},
                                     5: {'course_id': 2,
                                         'id': 5,
                                         'rank': 0,
                                         'registration_id': 1,
                                         'track_id': 2},
                                     6: {'course_id': 1,
                                         'id': 6,
                                         'rank': 0,
                                         'registration_id': 1,
                                         'track_id': 3},
                                     7: {'course_id': 4,
                                         'id': 7,
                                         'rank': 1,
                                         'registration_id': 1,
                                         'track_id': 3},
                                     8: {'course_id': 5,
                                         'id': 8,
                                         'rank': 0,
                                         'registration_id': 2,
                                         'track_id': 1},
                                     9: {'course_id': 4,
                                         'id': 9,
                                         'rank': 1,
                                         'registration_id': 2,
                                         'track_id': 1},
                                     10: {'course_id': 2,
                                          'id': 10,
                                          'rank': 2,
                                          'registration_id': 2,
                                          'track_id': 1},
                                     11: {'course_id': 1,
                                          'id': 11,
                                          'rank': 3,
                                          'registration_id': 2,
                                          'track_id': 1},
                                     12: {'course_id': 3,
                                          'id': 12,
                                          'rank': 0,
                                          'registration_id': 2,
                                          'track_id': 2},
                                     13: {'course_id': 4,
                                          'id': 13,
                                          'rank': 0,
                                          'registration_id': 2,
                                          'track_id': 3},
                                     14: {'course_id': 2,
                                          'id': 14,
                                          'rank': 1,
                                          'registration_id': 2,
                                          'track_id': 3},
                                     15: {'course_id': 4,
                                          'id': 15,
                                          'rank': 0,
                                          'registration_id': 3,
                                          'track_id': 1},
                                     16: {'course_id': 2,
                                          'id': 16,
                                          'rank': 1,
                                          'registration_id': 3,
                                          'track_id': 1},
                                     17: {'course_id': 1,
                                          'id': 17,
                                          'rank': 2,
                                          'registration_id': 3,
                                          'track_id': 1},
                                     18: {'course_id': 5,
                                          'id': 18,
                                          'rank': 3,
                                          'registration_id': 3,
                                          'track_id': 1},
                                     19: {'course_id': 2,
                                          'id': 19,
                                          'rank': 0,
                                          'registration_id': 3,
                                          'track_id': 2},
                                     20: {'course_id': 2,
                                          'id': 20,
                                          'rank': 0,
                                          'registration_id': 3,
                                          'track_id': 3},
                                     21: {'course_id': 4,
                                          'id': 21,
                                          'rank': 1,
                                          'registration_id': 3,
                                          'track_id': 3},
                                     22: {'course_id': 2,
                                          'id': 22,
                                          'rank': 0,
                                          'registration_id': 4,
                                          'track_id': 1},
                                     23: {'course_id': 1,
                                          'id': 23,
                                          'rank': 1,
                                          'registration_id': 4,
                                          'track_id': 1},
                                     24: {'course_id': 4,
                                          'id': 24,
                                          'rank': 2,
                                          'registration_id': 4,
                                          'track_id': 1},
                                     25: {'course_id': 5,
                                          'id': 25,
                                          'rank': 3,
                                          'registration_id': 4,
                                          'track_id': 1},
                                     26: {'course_id': 4,
                                          'id': 26,
                                          'rank': 0,
                                          'registration_id': 4,
                                          'track_id': 2},
                                     27: {'course_id': 1,
                                          'id': 27,
                                          'rank': 0,
                                          'registration_id': 4,
                                          'track_id': 3},
                                     28: {'course_id': 2,
                                          'id': 28,
                                          'rank': 1,
                                          'registration_id': 4,
                                          'track_id': 3},
                                     29: {
                                         'course_id': 1,
                                         'id': 29,
                                         'rank': 0,
                                         'registration_id': 5,
                                         'track_id': 1},
                                     30: {
                                         'course_id': 5,
                                         'id': 30,
                                         'rank': 1,
                                         'registration_id': 5,
                                         'track_id': 1},
                                     31: {
                                         'course_id': 4,
                                         'id': 31,
                                         'rank': 2,
                                         'registration_id': 5,
                                         'track_id': 1},
                                     32: {
                                         'course_id': 2,
                                         'id': 32,
                                         'rank': 3,
                                         'registration_id': 5,
                                         'track_id': 1},
                                     33: {
                                         'course_id': 2,
                                         'id': 33,
                                         'rank': 0,
                                         'registration_id': 5,
                                         'track_id': 2},
                                     34: {
                                         'course_id': 1,
                                         'id': 34,
                                         'rank': 0,
                                         'registration_id': 5,
                                         'track_id': 3},
                                     35: {
                                         'course_id': 4,
                                         'id': 35,
                                         'rank': 1,
                                         'registration_id': 5,
                                         'track_id': 3}},
            'event.course_segments': {1: {'course_id': 1,
                                          'id': 1,
                                          'is_active': True,
                                          'track_id': 1},
                                      2: {'course_id': 1,
                                          'id': 2,
                                          'is_active': True,
                                          'track_id': 3},
                                      3: {'course_id': 2,
                                          'id': 3,
                                          'is_active': True,
                                          'track_id': 1},
                                      4: {'course_id': 2,
                                          'id': 4,
                                          'is_active': False,
                                          'track_id': 2},
                                      5: {'course_id': 2,
                                          'id': 5,
                                          'is_active': True,
                                          'track_id': 3},
                                      6: {'course_id': 3,
                                          'id': 6,
                                          'is_active': True,
                                          'track_id': 2},
                                      7: {'course_id': 4,
                                          'id': 7,
                                          'is_active': True,
                                          'track_id': 1},
                                      8: {'course_id': 4,
                                          'id': 8,
                                          'is_active': True,
                                          'track_id': 2},
                                      9: {'course_id': 4,
                                          'id': 9,
                                          'is_active': True,
                                          'track_id': 3},
                                      10: {'course_id': 5,
                                           'id': 10,
                                           'is_active': True,
                                           'track_id': 1},
                                      11: {'course_id': 5,
                                           'id': 11,
                                           'is_active': True,
                                           'track_id': 2},
                                      12: {'course_id': 5,
                                           'id': 12,
                                           'is_active': False,
                                           'track_id': 3}},
            'event.course_tracks': {1: {'id': 1,
                                        'num_choices': 4,
                                        'min_choices': 4,
                                        'part_id': 2,
                                        'shortname': 'Morgenkreis',
                                        'sortkey': 1,
                                        'title': 'Morgenkreis (Erste Hälfte)'},
                                    2: {'id': 2,
                                        'num_choices': 1,
                                        'min_choices': 1,
                                        'part_id': 2,
                                        'shortname': 'Kaffee',
                                        'sortkey': 2,
                                        'title': 'Kaffeekränzchen (Erste Hälfte)'},
                                    3: {'id': 3,
                                        'num_choices': 3,
                                        'min_choices': 2,
                                        'part_id': 3,
                                        'shortname': 'Sitzung',
                                        'sortkey': 3,
                                        'title': 'Arbeitssitzung (Zweite Hälfte)'}},
            'event.courses': {1: {'description': 'Wir werden die Bäume drücken.',
                                  'event_id': 1,
                                  'fields': {'room': 'Wald'},
                                  'id': 1,
                                  'instructors': 'ToFi & Co',
                                  'max_size': 10,
                                  'min_size': 2,
                                  'notes': 'Promotionen in Mathematik und Ethik für '
                                  'Teilnehmer notwendig.',
                                  'nr': 'α',
                                  'shortname': 'Heldentum',
                                  'title': 'Planetenretten für Anfänger'},
                              2: {'description': 'Inklusive Post, Backwaren und '
                                  'frühzeitigem Ableben.',
                                  'event_id': 1,
                                  'fields': {'room': 'Theater'},
                                  'id': 2,
                                  'instructors': 'Bernd Lucke',
                                  'max_size': 20,
                                  'min_size': 10,
                                  'notes': 'Kursleiter hat Sekt angefordert.',
                                  'nr': 'β',
                                  'shortname': 'Kabarett',
                                  'title': 'Lustigsein für Fortgeschrittene'},
                              3: {'description': 'mit hoher Leistung.',
                                  'event_id': 1,
                                  'fields': {'room': 'Seminarraum 42'},
                                  'id': 3,
                                  'instructors': 'Heinrich und Thomas Mann',
                                  'max_size': 14,
                                  'min_size': 5,
                                  'notes': None,
                                  'nr': 'γ',
                                  'shortname': 'Kurz',
                                  'title': 'Kurzer Kurs'},
                              4: {'description': 'mit hohem Umsatz.',
                                  'event_id': 1,
                                  'fields': {'room': 'Seminarraum 23'},
                                  'id': 4,
                                  'instructors': 'Stephen Hawking und Richard Feynman',
                                  'max_size': None,
                                  'min_size': None,
                                  'notes': None,
                                  'nr': 'δ',
                                  'shortname': 'Lang',
                                  'title': 'Langer Kurs'},
                              5: {'description': 'damit wir Auswahl haben',
                                  'event_id': 1,
                                  'fields': {'room': 'Nirwana'},
                                  'id': 5,
                                  'instructors': 'TBA',
                                  'max_size': None,
                                  'min_size': None,
                                  'notes': None,
                                  'nr': 'ε',
                                  'shortname': 'Backup',
                                  'title': 'Backup-Kurs'}},
            'event.event_parts': {1: {'event_id': 1,
                                      'fee': decimal.Decimal('10.50'),
                                      'id': 1,
                                      'part_begin': datetime.date(2222, 2, 2),
                                      'part_end': datetime.date(2222, 2, 2),
                                      'shortname': 'Wu',
                                      'title': 'Warmup'},
                                  2: {'event_id': 1,
                                      'fee': decimal.Decimal('123.00'),
                                      'id': 2,
                                      'part_begin': datetime.date(2222, 11, 1),
                                      'part_end': datetime.date(2222, 11, 11),
                                      'shortname': '1.H.',
                                      'title': 'Erste Hälfte'},
                                  3: {'event_id': 1,
                                      'fee': decimal.Decimal('450.99'),
                                      'id': 3,
                                      'part_begin': datetime.date(2222, 11, 11),
                                      'part_end': datetime.date(2222, 11, 30),
                                      'shortname': '2.H.',
                                      'title': 'Zweite Hälfte'}},
            'event.events': {1: {'course_room_field': 2,
                                 'description': 'Everybody come!',
                                 'iban': 'DE96370205000008068901',
                                 'nonmember_surcharge': decimal.Decimal("5.00"),
                                 'id': 1,
                                 'institution': 1,
                                 'is_archived': False,
                                 'is_participant_list_visible': False,
                                 'courses_in_participant_list': False,
                                 'is_course_list_visible': True,
                                 'is_course_state_visible': False,
                                 'is_visible': True,
                                 'lodge_field': 3,
                                 'registration_text': None,
                                 'mail_text': 'Wir verwenden ein neues '
                                 'Kristallkugel-basiertes '
                                 'Kurszuteilungssystem; bis wir das '
                                 'ordentlich ans Laufen gebracht haben, '
                                 'müsst ihr leider etwas auf die '
                                 'Teilnehmerliste warten.',
                                 'notes': 'Todoliste ... just kidding ;)',
                                 'offline_lock': False,
                                 'orga_address': 'aka@example.cde',
                                 'registration_hard_limit': datetime.datetime(2221, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'registration_soft_limit': datetime.datetime(2200, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'registration_start': datetime.datetime(2000, 10, 30, 0, 0, tzinfo=pytz.utc),
                                 'reserve_field': 4,
                                 'shortname': 'TestAka',
                                 'title': 'Große Testakademie 2222',
                                 'use_questionnaire': False}},
            'event.fee_modifiers': {},
            'event.field_definitions': {1: {'association': 1,
                                            'entries': None,
                                            'event_id': 1,
                                            'field_name': 'brings_balls',
                                            'id': 1,
                                            'kind': 2},
                                        2: {'association': 1,
                                            'entries': [['pedes', 'by feet'],
                                                        ['car', 'own car available'],
                                                        ['etc', 'anything else']],
                                            'event_id': 1,
                                            'field_name': 'transportation',
                                            'id': 2,
                                            'kind': 1},
                                        3: {'association': 1,
                                            'entries': None,
                                            'event_id': 1,
                                            'field_name': 'lodge',
                                            'id': 3,
                                            'kind': 1},
                                        4: {'association': 1,
                                            'entries': None,
                                            'event_id': 1,
                                            'field_name': 'may_reserve',
                                            'id': 4,
                                            'kind': 2},
                                        5: {'association': 2,
                                            'entries': None,
                                            'event_id': 1,
                                            'field_name': 'room',
                                            'id': 5,
                                            'kind': 1},
                                        6: {'association': 3,
                                            'entries': [['high', 'lots of radiation'],
                                                        ['medium',
                                                         'elevated level of radiation'],
                                                        ['low', 'some radiation'],
                                                        ['none', 'no radiation']],
                                            'event_id': 1,
                                            'field_name': 'contamination',
                                            'id': 6,
                                            'kind': 1}},
            'event.lodgement_groups': {1: {'id': 1,
                                           'event_id': 1,
                                           'moniker': 'Haupthaus'},
                                       2: {'id': 2,
                                           'event_id': 1,
                                           'moniker': 'AußenWohnGruppe'}},
            'event.lodgements': {1: {'capacity': 5,
                                     'event_id': 1,
                                     'fields': {'contamination': 'high'},
                                     'id': 1,
                                     'moniker': 'Warme Stube',
                                     'notes': None,
                                     'group_id': 2,
                                     'reserve': 1},
                                 2: {'capacity': 10,
                                     'event_id': 1,
                                     'fields': {'contamination': 'none'},
                                     'id': 2,
                                     'moniker': 'Kalte Kammer',
                                     'notes': 'Dafür mit Frischluft.',
                                     'group_id': 1,
                                     'reserve': 2},
                                 3: {'capacity': 0,
                                     'event_id': 1,
                                     'fields': {'contamination': 'low'},
                                     'id': 3,
                                     'moniker': 'Kellerverlies',
                                     'notes': 'Nur für Notfälle.',
                                     'group_id': None,
                                     'reserve': 100},
                                 4: {'capacity': 1,
                                     'event_id': 1,
                                     'fields': {'contamination': 'high'},
                                     'id': 4,
                                     'moniker': 'Einzelzelle',
                                     'notes': None,
                                     'group_id': 1,
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
            'event.orgas': {1: {'event_id': 1, 'id': 1, 'persona_id': 7}},
            'event.questionnaire_rows': {1: {'event_id': 1,
                                             'field_id': None,
                                             'id': 1,
                                             'info': 'mit Text darunter',
                                             'input_size': None,
                                             'pos': 0,
                                             'readonly': None,
                                             'title': 'Unterüberschrift',
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             },
                                         2: {'event_id': 1,
                                             'field_id': 1,
                                             'id': 2,
                                             'info': 'Du bringst genug Bälle mit um einen '
                                             'ganzen Kurs abzuwerfen.',
                                             'input_size': None,
                                             'pos': 1,
                                             'readonly': False,
                                             'title': 'Bälle',
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             },
                                         3: {'event_id': 1,
                                             'field_id': None,
                                             'id': 3,
                                             'info': 'nur etwas Text',
                                             'input_size': None,
                                             'pos': 2,
                                             'readonly': None,
                                             'title': None,
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             },
                                         4: {'event_id': 1,
                                             'field_id': None,
                                             'id': 4,
                                             'info': None,
                                             'input_size': None,
                                             'pos': 3,
                                             'readonly': None,
                                             'title': 'Weitere Überschrift',
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             },
                                         5: {'event_id': 1,
                                             'field_id': 2,
                                             'id': 5,
                                             'info': None,
                                             'input_size': None,
                                             'pos': 4,
                                             'readonly': False,
                                             'title': 'Vehikel',
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             },
                                         6: {'event_id': 1,
                                             'field_id': 3,
                                             'id': 6,
                                             'info': None,
                                             'input_size': 3,
                                             'pos': 5,
                                             'readonly': False,
                                             'title': 'Hauswunsch',
                                             'kind': const.QuestionnaireUsages.questionnaire,
                                             }},
            'event.registration_parts': {1: {'id': 1,
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
                                             'status': 2},
                                         4: {'id': 4,
                                             'is_reserve': False,
                                             'lodgement_id': None,
                                             'part_id': 1,
                                             'registration_id': 2,
                                             'status': 3},
                                         5: {'id': 5,
                                             'is_reserve': False,
                                             'lodgement_id': 4,
                                             'part_id': 2,
                                             'registration_id': 2,
                                             'status': 4},
                                         6: {'id': 6,
                                             'is_reserve': False,
                                             'lodgement_id': 4,
                                             'part_id': 3,
                                             'registration_id': 2,
                                             'status': 2},
                                         7: {'id': 7,
                                             'is_reserve': False,
                                             'lodgement_id': 2,
                                             'part_id': 1,
                                             'registration_id': 3,
                                             'status': 2},
                                         8: {'id': 8,
                                             'is_reserve': False,
                                             'lodgement_id': None,
                                             'part_id': 2,
                                             'registration_id': 3,
                                             'status': 2},
                                         9: {'id': 9,
                                             'is_reserve': False,
                                             'lodgement_id': 2,
                                             'part_id': 3,
                                             'registration_id': 3,
                                             'status': 2},
                                         10: {'id': 10,
                                              'is_reserve': False,
                                              'lodgement_id': None,
                                              'part_id': 1,
                                              'registration_id': 4,
                                              'status': 6},
                                         11: {'id': 11,
                                              'is_reserve': False,
                                              'lodgement_id': None,
                                              'part_id': 2,
                                              'registration_id': 4,
                                              'status': 5},
                                         12: {'id': 12,
                                              'is_reserve': True,
                                              'lodgement_id': 2,
                                              'part_id': 3,
                                              'registration_id': 4,
                                              'status': 2},
                                         13: {
                                             'id': 13,
                                             'is_reserve': False,
                                             'lodgement_id': 4,
                                             'part_id': 1,
                                             'registration_id': 5,
                                             'status': 2},
                                         14: {
                                             'id': 14,
                                             'is_reserve': False,
                                             'lodgement_id': 4,
                                             'part_id': 2,
                                             'registration_id': 5,
                                             'status': 2},
                                         15: {
                                             'id': 15,
                                             'is_reserve': False,
                                             'lodgement_id': 1,
                                             'part_id': 3,
                                             'registration_id': 5,
                                             'status': 2}},
            'event.registration_tracks': {1: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 1,
                                              'registration_id': 1,
                                              'track_id': 1},
                                          2: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 2,
                                              'registration_id': 1,
                                              'track_id': 2},
                                          3: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 3,
                                              'registration_id': 1,
                                              'track_id': 3},
                                          4: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 4,
                                              'registration_id': 2,
                                              'track_id': 1},
                                          5: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 5,
                                              'registration_id': 2,
                                              'track_id': 2},
                                          6: {'course_id': 1,
                                              'course_instructor': 1,
                                              'id': 6,
                                              'registration_id': 2,
                                              'track_id': 3},
                                          7: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 7,
                                              'registration_id': 3,
                                              'track_id': 1},
                                          8: {'course_id': 2,
                                              'course_instructor': None,
                                              'id': 8,
                                              'registration_id': 3,
                                              'track_id': 2},
                                          9: {'course_id': None,
                                              'course_instructor': None,
                                              'id': 9,
                                              'registration_id': 3,
                                              'track_id': 3},
                                          10: {'course_id': None,
                                               'course_instructor': None,
                                               'id': 10,
                                               'registration_id': 4,
                                               'track_id': 1},
                                          11: {'course_id': None,
                                               'course_instructor': None,
                                               'id': 11,
                                               'registration_id': 4,
                                               'track_id': 2},
                                          12: {'course_id': 1,
                                               'course_instructor': None,
                                               'id': 12,
                                               'registration_id': 4,
                                               'track_id': 3},
                                          13: {
                                              'course_id': None,
                                              'course_instructor': None,
                                              'id': 13,
                                              'registration_id': 5,
                                              'track_id': 1},
                                          14: {
                                              'course_id': 2,
                                              'course_instructor': None,
                                              'id': 14,
                                              'registration_id': 5,
                                              'track_id': 2},
                                          15: {
                                              'course_id': 1,
                                              'course_instructor': None,
                                              'id': 15,
                                              'registration_id': 5,
                                              'track_id': 3}},
            'event.registrations': {1: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'lodge': 'Die üblichen Verdächtigen :)'},
                                        'list_consent': True,
                                        'id': 1,
                                        'mixed_lodging': True,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': True,
                                        'payment': None,
                                        'persona_id': 1,
                                        'real_persona_id': None,
                                        'amount_paid': decimal.Decimal("0.00"),
                                        'amount_owed': decimal.Decimal("573.99"),
                                        },
                                    2: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'brings_balls': True,
                                                   'transportation': 'pedes'},
                                        'list_consent': True,
                                        'id': 2,
                                        'mixed_lodging': True,
                                        'notes': 'Extrawünsche: Meerblick, Weckdienst und '
                                        'Frühstück am Bett',
                                        'orga_notes': 'Unbedingt in die Einzelzelle.',
                                        'parental_agreement': True,
                                        'payment': datetime.date(2014, 2, 2),
                                        'persona_id': 5,
                                        'real_persona_id': None,
                                        'amount_paid': decimal.Decimal("0.00"),
                                        'amount_owed': decimal.Decimal("589.49"),
                                        },
                                    3: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'transportation': 'car'},
                                        'list_consent': False,
                                        'id': 3,
                                        'mixed_lodging': True,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': True,
                                        'payment': datetime.date(2014, 3, 3),
                                        'persona_id': 7,
                                        'real_persona_id': None,
                                        'amount_paid': decimal.Decimal("0.00"),
                                        'amount_owed': decimal.Decimal("584.49"),
                                        },
                                    4: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'brings_balls': False,
                                                   'may_reserve': True,
                                                   'transportation': 'etc'},
                                        'list_consent': False,
                                        'id': 4,
                                        'mixed_lodging': False,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': False,
                                        'payment': datetime.date(2014, 4, 4),
                                        'persona_id': 9,
                                        'real_persona_id': None,
                                        'amount_paid': decimal.Decimal("0.00"),
                                        'amount_owed': decimal.Decimal("450.99"),
                                        },
                                    5: {'checkin': None,
                                        'event_id': 1,
                                        'fields': {'transportation': 'pedes'},
                                        'id': 5,
                                        'list_consent': True,
                                        'mixed_lodging': False,
                                        'notes': None,
                                        'orga_notes': None,
                                        'parental_agreement': True,
                                        'payment': None,
                                        'persona_id': 100,
                                        'real_persona_id': None,
                                        'amount_paid': decimal.Decimal("0.00"),
                                        'amount_owed': decimal.Decimal("584.49"),
                                        },
                                    },
            'id': 1,
            'kind': 'full',
            'timestamp': nearly_now()
        }
        self.assertEqual(expectation, self.event.export_event(self.key, 1))

    @as_users("annika")
    def test_import_event(self, user):
        self.assertTrue(self.event.lock_event(self.key, 1))
        data = self.event.export_event(self.key, 1)
        new_data = copy.deepcopy(data)
        stored_data = copy.deepcopy(data)
        ##
        ## Apply some changes
        ##

        ## event
        new_data['event.events'][1]['description'] = "We are done!"
        ## event parts
        new_data['event.event_parts'][4000] = {
            'event_id': 1,
            'fee': decimal.Decimal('666.66'),
            'id': 4000,
            'part_begin': datetime.date(2345, 1, 1),
            'part_end': datetime.date(2345, 12, 31),
            'title': 'Aftershowparty',
            'shortname': 'Aftershow'}
        ## course tracks
        new_data['event.course_tracks'][1100] = {
            'part_id': 4000,
            'id': 1100,
            'title': 'Enlightnment',
            'shortname': 'Enlightnment',
            'num_choices': 3,
            'min_choices': 2,
            'sortkey': 1}
        ## lodgemnet groups
        new_data['event.lodgement_groups'][5000] = {
            'id': 5000,
            'event_id': 1,
            'moniker': 'Nebenan',
        }
        ## lodgements
        new_data['event.lodgements'][6000] = {
            'capacity': 1,
            'event_id': 1,
            'fields': {},
            'id': 6000,
            'moniker': 'Matte im Orgabüro',
            'notes': None,
            'group_id': 1,
            'reserve': 0}
        ## registration
        new_data['event.registrations'][1000] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good'},
            "list_consent": True,
            'id': 1000,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': True,
            'payment': None,
            'persona_id': 2000,
            'real_persona_id': 2,
            'amount_paid': decimal.Decimal("42.00"),
            'amount_owed': decimal.Decimal("666.66"),
        }
        ## registration parts
        new_data['event.registration_parts'].update({
            5000: {
                'id': 5000,
                'lodgement_id': 6000,
                'part_id': 4000,
                'registration_id': 1000,
                'status': 1,
            },
            5001: {
                'id': 5001,
                'lodgement_id': None,
                'part_id': 1,
                'registration_id': 1000,
                'status': const.RegistrationPartStati.not_applied,
            },
            5002: {
                'id': 5002,
                'lodgement_id': None,
                'part_id': 2,
                'registration_id': 1000,
                'status': const.RegistrationPartStati.not_applied,
            },
            5003: {
                'id': 5003,
                'lodgement_id': None,
                'part_id': 3,
                'registration_id': 1000,
                'status': const.RegistrationPartStati.not_applied,
            },
            5004: {
                'id': 5004,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 1,
                'status': const.RegistrationPartStati.not_applied,
            },
            5005: {
                'id': 5005,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 2,
                'status': const.RegistrationPartStati.not_applied,
            },
            5006: {
                'id': 5006,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 3,
                'status': const.RegistrationPartStati.not_applied,
            },
            5007: {
                'id': 5007,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 4,
                'status': const.RegistrationPartStati.not_applied,
            },
            5008: {
                'id': 5008,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 5,
                'status': const.RegistrationPartStati.not_applied,
            },
        })
        ## registration parts
        new_data['event.registration_tracks'][1200] = {
            'course_id': 3000,
            'course_instructor': None,
            'id': 1200,
            'track_id': 1100,
            'registration_id': 1000}
        ## orgas
        new_data['event.orgas'][7000] = {
            'event_id': 1, 'id': 7000, 'persona_id': 2000}
        ## course
        new_data['event.courses'][3000] = {
            'description': 'Spontankurs',
            'event_id': 1,
            'fields': {},
            'id': 3000,
            'instructors': 'Alle',
            'max_size': 111,
            'min_size': 111,
            'notes': None,
            'nr': 'φ',
            'shortname': 'Spontan',
            'title': 'Spontankurs'}
        ## course parts
        new_data['event.course_segments'][8000] = {
            'course_id': 3000, 'id': 8000, 'track_id': 1100, 'is_active': True}
        ## course choices
        ## - an update
        new_data['event.course_choices'][27] = {
            'course_id': 5, 'id': 27, 'track_id': 3, 'rank': 0, 'registration_id': 4}
        ## - a delete and an insert
        del new_data['event.course_choices'][28]
        new_data['event.course_choices'][9000] = {
            'course_id': 4, 'id': 9000, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        ## - an insert
        new_data['event.course_choices'][10000] = {
            'course_id': 3000, 'id': 10000, 'track_id': 1100, 'rank': 0, 'registration_id': 1000}
        ## field definitions
        new_data['event.field_definitions'].update({
            11000: {
                'association': 1,
                'entries': [['good', 'good'],
                            ['neutral', 'so so'],
                            ['bad', 'not good']],
                'event_id': 1,
                'field_name': 'behaviour',
                'id': 11000,
                'kind': 1,
            },
            11001: {
                'association': const.FieldAssociations.registration,
                'entries': None,
                'event_id': 1,
                'field_name': "is_child",
                'id': 11001,
                'kind': const.FieldDatatypes.bool,
            }
        })
        ## questionnaire rows
        new_data['event.questionnaire_rows'][12000] = {
            'event_id': 1,
            'field_id': 11000,
            'id': 12000,
            'info': 'Wie brav wirst Du sein',
            'input_size': None,
            'pos': 1,
            'readonly': True,
            'title': 'Vorsätze',
            'kind': const.QuestionnaireUsages.questionnaire,
        }
        new_data['event.fee_modifiers'][13000] = {
            'id': 13000,
            'part_id': 4000,
            'field_id': 11001,
            'modifier_name': 'is_child',
            'amount': decimal.Decimal("-12.50"),
        }
        ## Note that the changes above are not entirely consistent/complete (as
        ## in some stuff is missing and another part may throw an error if we
        ## used the resulting data set for real)
        self.assertLess(0, self.event.unlock_import_event(self.key, new_data))
        ## Now we have to fix for new stuff
        stored_data['event.events'][1]['offline_lock'] = False
        stored_data['timestamp'] = nearly_now()
        ## Apply the same changes as above but this time with (guessed) correct IDs
        stored_data['event.events'][1]['description'] = "We are done!"
        stored_data['event.event_parts'][1001] = {
            'event_id': 1,
            'fee': decimal.Decimal('666.66'),
            'id': 1001,
            'part_begin': datetime.date(2345, 1, 1),
            'part_end': datetime.date(2345, 12, 31),
            'shortname': 'Aftershow',
            'title': 'Aftershowparty'}
        stored_data['event.course_tracks'][1001] = {
            'part_id': 1001,
            'id': 1001,
            'shortname': 'Enlightnment',
            'num_choices': 3,
            'min_choices': 2,
            'sortkey': 1,
            'title': 'Enlightnment'}
        stored_data['event.lodgement_groups'][1001] = {
            'id': 1001,
            'event_id': 1,
            'moniker': 'Nebenan',
        }
        stored_data['event.lodgements'][1001] = {
            'capacity': 1,
            'event_id': 1,
            'fields': {},
            'id': 1001,
            'moniker': 'Matte im Orgabüro',
            'notes': None,
            'group_id': 1,
            'reserve': 0}
        stored_data['event.registrations'][1001] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good'},
            "list_consent": True,
            'id': 1001,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': True,
            'payment': None,
            'persona_id': 2,
            'real_persona_id': None,
            'amount_paid': decimal.Decimal("42.00"),
            'amount_owed': decimal.Decimal("666.66"),
        }
        stored_data['event.registration_parts'].update({
            1001: {
                'id': 1001,
                'is_reserve': False,
                'lodgement_id': 1001,
                'part_id': 1001,
                'registration_id': 1001,
                'status': 1,
            },
            1002: {
                'id': 1002,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1003: {
                'id': 1003,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 2,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1004: {
                'id': 1004,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 3,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1005: {
                'id': 1005,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 1,
                'status': const.RegistrationPartStati.not_applied,
            },
            1006: {
                'id': 1006,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 2,
                'status': const.RegistrationPartStati.not_applied,
            },
            1007: {
                'id': 1007,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 3,
                'status': const.RegistrationPartStati.not_applied,
            },
            1008: {
                'id': 1008,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 4,
                'status': const.RegistrationPartStati.not_applied,
            },
            1009: {
                'id': 1009,
                'is_reserve': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 5,
                'status': const.RegistrationPartStati.not_applied,
            },
        })
        stored_data['event.registration_tracks'][1001] = {
            'course_id': 1001,
            'course_instructor': None,
            'id': 1001,
            'track_id': 1001,
            'registration_id': 1001}
        stored_data['event.orgas'][1001] = {
            'event_id': 1, 'id': 1001, 'persona_id': 2}
        stored_data['event.courses'][1001] = {
            'description': 'Spontankurs',
            'event_id': 1,
            'fields': {},
            'id': 1001,
            'instructors': 'Alle',
            'max_size': 111,
            'min_size': 111,
            'notes': None,
            'nr': 'φ',
            'shortname': 'Spontan',
            'title': 'Spontankurs'}
        stored_data['event.course_segments'][1001] = {
            'course_id': 1001, 'id': 1001, 'track_id': 1001, 'is_active': True}
        stored_data['event.course_choices'][27] = {
            'course_id': 5, 'id': 27, 'track_id': 3, 'rank': 0, 'registration_id': 4}
        del stored_data['event.course_choices'][28]
        stored_data['event.course_choices'][1002] = {
            'course_id': 1001, 'id': 1002, 'track_id': 1001, 'rank': 0, 'registration_id': 1001}
        stored_data['event.course_choices'][1001] = {
            'course_id': 4, 'id': 1001, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        stored_data['event.field_definitions'].update({
            1001: {
                'association': const.FieldAssociations.registration,
                'entries': [['good', 'good'],
                            ['neutral', 'so so'],
                            ['bad', 'not good']],
                'event_id': 1,
                'field_name': 'behaviour',
                'id': 1001,
                'kind': const.FieldDatatypes.str,
            },
            1002: {
                'association': const.FieldAssociations.registration,
                'entries': None,
                'event_id': 1,
                'field_name': 'is_child',
                'id': 1002,
                'kind': const.FieldDatatypes.bool,
            },
        })
        stored_data['event.fee_modifiers'][1001] = {
            'id': 1001,
            'modifier_name': "is_child",
            'field_id': 1002,
            'amount': decimal.Decimal("-12.50"),
            'part_id': 1001,
        }
        stored_data['event.questionnaire_rows'][1001] = {
            'event_id': 1,
            'field_id': 1001,
            'id': 1001,
            'info': 'Wie brav wirst Du sein',
            'input_size': None,
            'pos': 1,
            'readonly': True,
            'title': 'Vorsätze',
            'kind': const.QuestionnaireUsages.questionnaire,
        }

        result = self.event.export_event(self.key, 1)
        ## because it's irrelevant anyway simply paste the result
        stored_data['core.personas'] = result['core.personas']
        ## add log message
        stored_data['event.log'][1002] = {
            'additional_info': None,
            'code': 61,
            'ctime': nearly_now(),
            'event_id': 1,
            'id': 1002,
            'persona_id': None,
            'submitted_by': user['id']}

        self.assertEqual(stored_data, result)

    @as_users("annika")
    def test_partial_export_event(self, user):
        expectation = {
            'CDEDB_EXPORT_EVENT_VERSION': CDEDB_EXPORT_EVENT_VERSION,
            'courses': {1: {'description': 'Wir werden die Bäume drücken.',
                            'fields': {'room': 'Wald'},
                            'instructors': 'ToFi & Co',
                            'max_size': 10,
                            'min_size': 2,
                            'notes': 'Promotionen in Mathematik und Ethik für Teilnehmer '
                            'notwendig.',
                            'nr': 'α',
                            'segments': {1: True, 3: True},
                            'shortname': 'Heldentum',
                            'title': 'Planetenretten für Anfänger'},
                        2: {'description': 'Inklusive Post, Backwaren und frühzeitigem '
                            'Ableben.',
                            'fields': {'room': 'Theater'},
                            'instructors': 'Bernd Lucke',
                            'max_size': 20,
                            'min_size': 10,
                            'notes': 'Kursleiter hat Sekt angefordert.',
                            'nr': 'β',
                            'segments': {1: True, 2: False, 3: True},
                            'shortname': 'Kabarett',
                            'title': 'Lustigsein für Fortgeschrittene'},
                        3: {'description': 'mit hoher Leistung.',
                            'fields': {'room': 'Seminarraum 42'},
                            'instructors': 'Heinrich und Thomas Mann',
                            'max_size': 14,
                            'min_size': 5,
                            'notes': None,
                            'nr': 'γ',
                            'segments': {2: True},
                            'shortname': 'Kurz',
                            'title': 'Kurzer Kurs'},
                        4: {'description': 'mit hohem Umsatz.',
                            'fields': {'room': 'Seminarraum 23'},
                            'instructors': 'Stephen Hawking und Richard Feynman',
                            'max_size': None,
                            'min_size': None,
                            'notes': None,
                            'nr': 'δ',
                            'segments': {1: True, 2: True, 3: True},
                            'shortname': 'Lang',
                            'title': 'Langer Kurs'},
                        5: {'description': 'damit wir Auswahl haben',
                            'fields': {'room': 'Nirwana'},
                            'instructors': 'TBA',
                            'max_size': None,
                            'min_size': None,
                            'notes': None,
                            'nr': 'ε',
                            'segments': {1: True, 2: True, 3: False},
                            'shortname': 'Backup',
                            'title': 'Backup-Kurs'}},
            'event': {'course_room_field': 'transportation',
                      'description': 'Everybody come!',
                      'fee_modifiers': {},
                      'fields': {'brings_balls': {'association': 1,
                                                  'entries': None,
                                                  'kind': 2},
                                 'contamination': {'association': 3,
                                                   'entries': [['high',
                                                                'lots of radiation'],
                                                               ['medium',
                                                                'elevated level of '
                                                                'radiation'],
                                                               ['low', 'some radiation'],
                                                               ['none', 'no radiation']],
                                                   'kind': 1},
                                 'lodge': {'association': 1,
                                           'entries': None,
                                           'kind': 1},
                                 'may_reserve': {'association': 1,
                                                 'entries': None,
                                                 'kind': 2},
                                 'room': {'association': 2,
                                          'entries': None,
                                          'kind': 1},
                                 'transportation': {'association': 1,
                                                    'entries': [['pedes', 'by feet'],
                                                                ['car',
                                                                 'own car available'],
                                                                ['etc', 'anything else']],
                                                    'kind': 1}},
                      'iban': 'DE96370205000008068901',
                      'nonmember_surcharge': decimal.Decimal("5.00"),
                      'institution': 1,
                      'is_archived': False,
                      'is_participant_list_visible': False,
                      'courses_in_participant_list': False,
                      'is_course_list_visible': True,
                      'is_course_state_visible': False,
                      'is_visible': True,
                      'lodge_field': 'lodge',
                      'mail_text': 'Wir verwenden ein neues Kristallkugel-basiertes '
                                   'Kurszuteilungssystem; bis wir das ordentlich ans '
                                   'Laufen gebracht haben, müsst ihr leider etwas auf die '
                                   'Teilnehmerliste warten.',
                      'notes': 'Todoliste ... just kidding ;)',
                      'offline_lock': False,
                      'orga_address': 'aka@example.cde',
                      'parts': {1: {'fee': decimal.Decimal('10.50'),
                                    'part_begin': datetime.date(2222, 2, 2),
                                    'part_end': datetime.date(2222, 2, 2),
                                    'shortname': 'Wu',
                                    'tracks': {},
                                    'title': 'Warmup'},
                                2: {'fee': decimal.Decimal('123.00'),
                                    'part_begin': datetime.date(2222, 11, 1),
                                    'part_end': datetime.date(2222, 11, 11),
                                    'shortname': '1.H.',
                                    'tracks': {1: {'num_choices': 4,
                                                   'min_choices': 4,
                                                   'shortname': 'Morgenkreis',
                                                   'sortkey': 1,
                                                   'title': 'Morgenkreis (Erste Hälfte)'},
                                               2: {'num_choices': 1,
                                                   'min_choices': 1,
                                                   'shortname': 'Kaffee',
                                                   'sortkey': 2,
                                                   'title': 'Kaffeekränzchen (Erste Hälfte)'}},
                                    'title': 'Erste Hälfte'},
                                3: {'fee': decimal.Decimal('450.99'),
                                    'part_begin': datetime.date(2222, 11, 11),
                                    'part_end': datetime.date(2222, 11, 30),
                                    'shortname': '2.H.',
                                    'tracks': {3: {'num_choices': 3,
                                                   'min_choices': 2,
                                                   'shortname': 'Sitzung',
                                                   'sortkey': 3,
                                                   'title': 'Arbeitssitzung (Zweite Hälfte)'}},
                                    'title': 'Zweite Hälfte'}},
                      'registration_hard_limit': datetime.datetime(2221, 10, 30, 0, 0, tzinfo=pytz.utc),
                      'registration_soft_limit': datetime.datetime(2200, 10, 30, 0, 0, tzinfo=pytz.utc),
                      'registration_start': datetime.datetime(2000, 10, 30, 0, 0, tzinfo=pytz.utc),
                      'registration_text': None,
                      'reserve_field': 'may_reserve',
                      'shortname': 'TestAka',
                      'title': 'Große Testakademie 2222',
                      'use_questionnaire': False},
            'id': 1,
            'kind': 'partial',
            'lodgement_groups': {1: {'moniker': 'Haupthaus'},
                                 2: {'moniker': 'AußenWohnGruppe'}},
            'lodgements': {1: {'capacity': 5,
                               'fields': {'contamination': 'high'},
                               'moniker': 'Warme Stube',
                               'notes': None,
                               'group_id': 2,
                               'reserve': 1},
                           2: {'capacity': 10,
                               'fields': {'contamination': 'none'},
                               'moniker': 'Kalte Kammer',
                               'notes': 'Dafür mit Frischluft.',
                               'group_id': 1,
                               'reserve': 2},
                           3: {'capacity': 0,
                               'fields': {'contamination': 'low'},
                               'moniker': 'Kellerverlies',
                               'notes': 'Nur für Notfälle.',
                               'group_id': None,
                               'reserve': 100},
                           4: {'capacity': 1,
                               'fields': {'contamination': 'high'},
                               'moniker': 'Einzelzelle',
                               'notes': None,
                               'group_id': 1,
                               'reserve': 0}},
            'registrations': {1: {'amount_owed': decimal.Decimal("573.99"),
                                  'amount_paid': decimal.Decimal("0.00"),
                                  'checkin': None,
                                  'fields': {'lodge': 'Die üblichen Verdächtigen :)'},
                                  'list_consent': True,
                                  'mixed_lodging': True,
                                  'notes': None,
                                  'orga_notes': None,
                                  'parental_agreement': True,
                                  'parts': {1: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': -1},
                                            2: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': 1},
                                            3: {'is_reserve': False,
                                                'lodgement_id': 1,
                                                'status': 2}},
                                  'payment': None,
                                  'persona': {'address': 'Auf der Düne 42',
                                              'address_supplement': None,
                                              'birthday': datetime.date(1991, 3, 30),
                                              'country': None,
                                              'display_name': 'Anton',
                                              'family_name': 'Administrator',
                                              'gender': 2,
                                              'given_names': 'Anton Armin A.',
                                              'id': 1,
                                              'is_member': True,
                                              'is_orga': False,
                                              'location': 'Musterstadt',
                                              'mobile': None,
                                              'name_supplement': None,
                                              'postal_code': '03205',
                                              'telephone': '+49 (234) 98765',
                                              'title': None,
                                              'username': 'anton@example.cde'},
                                  'tracks': {1: {'choices': [1, 3, 4, 2],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             2: {'choices': [2],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             3: {'choices': [1, 4],
                                                 'course_id': None,
                                                 'course_instructor': None}}},
                              2: {'amount_owed': decimal.Decimal("589.49"),
                                  'amount_paid': decimal.Decimal("0.00"),
                                  'checkin': None,
                                  'fields': {'brings_balls': True,
                                             'transportation': 'pedes'},
                                  'list_consent': True,
                                  'mixed_lodging': True,
                                  'notes': 'Extrawünsche: Meerblick, Weckdienst und '
                                  'Frühstück am Bett',
                                  'orga_notes': 'Unbedingt in die Einzelzelle.',
                                  'parental_agreement': True,
                                  'parts': {1: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': 3},
                                            2: {'is_reserve': False,
                                                'lodgement_id': 4,
                                                'status': 4},
                                            3: {'is_reserve': False,
                                                'lodgement_id': 4,
                                                'status': 2}},
                                  'payment': datetime.date(2014, 2, 2),
                                  'persona': {'address': 'Hohle Gasse 13',
                                              'address_supplement': None,
                                              'birthday': datetime.date(2012, 6, 2),
                                              'country': 'Deutschland',
                                              'display_name': 'Emilia',
                                              'family_name': 'Eventis',
                                              'gender': 1,
                                              'given_names': 'Emilia E.',
                                              'id': 5,
                                              'is_member': False,
                                              'is_orga': False,
                                              'location': 'Wolkenkuckuksheim',
                                              'mobile': None,
                                              'name_supplement': None,
                                              'postal_code': '56767',
                                              'telephone': '+49 (5432) 555666777',
                                              'title': None,
                                              'username': 'emilia@example.cde'},
                                  'tracks': {1: {'choices': [5, 4, 2, 1],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             2: {'choices': [3],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             3: {'choices': [4, 2],
                                                 'course_id': 1,
                                                 'course_instructor': 1}}},
                              3: {'amount_owed': decimal.Decimal("584.49"),
                                  'amount_paid': decimal.Decimal("0.00"),
                                  'checkin': None,
                                  'fields': {'transportation': 'car'},
                                  'list_consent': False,
                                  'mixed_lodging': True,
                                  'notes': None,
                                  'orga_notes': None,
                                  'parental_agreement': True,
                                  'parts': {1: {'is_reserve': False,
                                                'lodgement_id': 2,
                                                'status': 2},
                                            2: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': 2},
                                            3: {'is_reserve': False,
                                                'lodgement_id': 2,
                                                'status': 2}},
                                  'payment': datetime.date(2014, 3, 3),
                                  'persona': {'address': 'Bei der Wüste 39',
                                              'address_supplement': None,
                                              'birthday': datetime.date(1978, 12, 12),
                                              'country': None,
                                              'display_name': 'Garcia',
                                              'family_name': 'Generalis',
                                              'gender': 1,
                                              'given_names': 'Garcia G.',
                                              'id': 7,
                                              'is_member': True,
                                              'is_orga': True,
                                              'location': 'Weltstadt',
                                              'mobile': None,
                                              'name_supplement': None,
                                              'postal_code': '88484',
                                              'telephone': None,
                                              'title': None,
                                              'username': 'garcia@example.cde'},
                                  'tracks': {1: {'choices': [4, 2, 1, 5],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             2: {'choices': [2],
                                                 'course_id': 2,
                                                 'course_instructor': None},
                                             3: {'choices': [2, 4],
                                                 'course_id': None,
                                                 'course_instructor': None}}},
                              4: {'amount_owed': decimal.Decimal("450.99"),
                                  'amount_paid': decimal.Decimal("0.00"),
                                  'checkin': None,
                                  'fields': {'brings_balls': False,
                                             'may_reserve': True,
                                             'transportation': 'etc'},
                                  'list_consent': False,
                                  'mixed_lodging': False,
                                  'notes': None,
                                  'orga_notes': None,
                                  'parental_agreement': False,
                                  'parts': {1: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': 6},
                                            2: {'is_reserve': False,
                                                'lodgement_id': None,
                                                'status': 5},
                                            3: {'is_reserve': True,
                                                'lodgement_id': 2,
                                                'status': 2}},
                                  'payment': datetime.date(2014, 4, 4),
                                  'persona': {'address': 'Zwergstraße 1',
                                              'address_supplement': None,
                                              'birthday': datetime.date(2222, 1, 1),
                                              'country': None,
                                              'display_name': 'Inga',
                                              'family_name': 'Iota',
                                              'gender': 1,
                                              'given_names': 'Inga',
                                              'id': 9,
                                              'is_member': True,
                                              'is_orga': False,
                                              'location': 'Liliput',
                                              'mobile': '0163/456897',
                                              'name_supplement': None,
                                              'postal_code': '10999',
                                              'telephone': None,
                                              'title': None,
                                              'username': 'inga@example.cde'},
                                  'tracks': {1: {'choices': [2, 1, 4, 5],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             2: {'choices': [4],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             3: {'choices': [1, 2],
                                                 'course_id': 1,
                                                 'course_instructor': None}}},
                              5: {'amount_owed': decimal.Decimal("584.49"),
                                  'amount_paid': decimal.Decimal("0.00"),
                                  'checkin': None,
                                  'fields': {'transportation': 'pedes'},
                                  'list_consent': True,
                                  'mixed_lodging': False,
                                  'notes': None,
                                  'orga_notes': None,
                                  'parental_agreement': True,
                                  'parts': {1: {'is_reserve': False,
                                                'lodgement_id': 4,
                                                'status': 2},
                                            2: {
                                                'is_reserve': False,
                                                'lodgement_id': 4,
                                                'status': 2},
                                            3: {
                                                'is_reserve': False,
                                                'lodgement_id': 1,
                                                'status': 2}},
                                  'payment': None,
                                  'persona': {'address': 'Kasumigaseki 1-3-2',
                                              'address_supplement': None,
                                              'birthday': datetime.date(2019, 12, 28),
                                              'country': 'Japan',
                                              'display_name': 'Akira',
                                              'family_name': 'Abukara',
                                              'gender': 10,
                                              'given_names': 'Akira',
                                              'id': 100,
                                              'is_member': True,
                                              'is_orga': False,
                                              'location': 'Tokyo',
                                              'mobile': None,
                                              'name_supplement': None,
                                              'postal_code': None,
                                              'telephone': '+81 (314) 159263',
                                              'title': None,
                                              'username': 'akira@example.cde'},
                                  'tracks': {1: {'choices': [1, 5, 4, 2],
                                                 'course_id': None,
                                                 'course_instructor': None},
                                             2: {'choices': [2],
                                                 'course_id': 2,
                                                 'course_instructor': None},
                                             3: {'choices': [1, 4],
                                                 'course_id': 1,
                                                 'course_instructor': None}}}},
            'timestamp': nearly_now()
        }
        export = self.event.partial_export_event(self.key, 1)
        self.assertEqual(expectation, export)

    @as_users("annika")
    def test_partial_import_event(self, user):
        event = self.event.get_event(self.key, 1)
        previous = self.event.partial_export_event(self.key, 1)
        with open("/tmp/cdedb-store/testfiles/partial_event_import.json") \
                as datafile:
            data = json.load(datafile)

        # first a test run
        token1, delta = self.event.partial_import_event(self.key, data,
                                                        dryrun=True)
        expectation = copy.deepcopy(delta)
        self.assertEqual(expectation, delta)
        # second check the token functionality
        with self.assertRaises(PartialImportError):
            self.event.partial_import_event(self.key, data, dryrun=False,
                                            token=token1 + "wrong")
        # now for real
        token2, delta = self.event.partial_import_event(
            self.key, data, dryrun=False, token=token1)
        self.assertEqual(token1, token2)

        updated = self.event.partial_export_event(self.key, 1)
        expectation = previous
        delta = json_keys_to_int(data)

        CMAP = {
            ('courses', -1): 1002,
            ('lodgement_groups', -1): 1002,
            ('lodgements', -1): 1003,
            ('lodgements', -2): 1004,
            ('registrations', -1): 1002,
        }
        TMAP = {
            'courses': {'segments': {}, 'fields': {}},
            'lodgement_groups': {},
            'lodgements': {'fields': {}},
            'registrations': {'parts': {}, 'tracks': {}, 'fields': {}},
        }

        def recursive_update(old, new, hint=None):
            if hint == 'fields':
                new = cast_fields(new, event['fields'])
            deletions = [key for key, val in new.items()
                         if val is None and key in old]
            for key in deletions:
                if (isinstance(old[key], collections.abc.Mapping)
                        or hint == 'segments'):
                    del old[key]
                    del new[key]
            recursions = [key for key, val in new.items()
                          if isinstance(val, collections.abc.Mapping)]
            for key in recursions:
                temp = new.pop(key)
                if isinstance(key, int) and key < 0:
                    new_key = CMAP[(hint, key)]
                    old[new_key] = copy.deepcopy(TMAP[hint])
                else:
                    new_key = key
                if new_key not in old:
                    old[new_key] = {}
                recursive_update(old[new_key], temp, new_key)
            for key in ('persona_id', 'real_persona_id'):
                if key in new:
                    del new[key]
            for key in ('payment',):
                if new.get(key):
                    try:
                        new[key] = datetime.date.fromisoformat(new[key])
                    except AttributeError:
                        del new[key]
                        if key in old:
                            del old[key]
            for key in ('course_id', 'course_instructor', 'choices'):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = CMAP.get(('courses', new[key]), new[key])
                    elif isinstance(new[key], collections.abc.Sequence):
                        new[key] = [CMAP.get(('courses', anid), anid)
                                    for anid in new[key]]
            for key in ('lodgement_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = CMAP.get(('lodgements', new[key]), new[key])
            for key in ('group_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = CMAP.get(
                            ('lodgement_groups', new[key]), new[key])
            old.update(new)

        recursive_update(expectation, delta)
        del expectation['timestamp']
        del updated['timestamp']
        del updated['registrations'][1002]['persona']  # ignore additional info
        updated['registrations'][1002]['amount_paid'] = str(
            updated['registrations'][1002]['amount_paid'])
        updated['registrations'][1002]['amount_owed'] = str(
            updated['registrations'][1002]['amount_owed'])
        self.assertEqual(expectation, updated)

    @as_users("annika")
    def test_partial_import_integrity(self, user):
        with open("/tmp/cdedb-store/testfiles/partial_event_import.json") \
                as datafile:
            orig_data = json.load(datafile)

        base_data = {
            k: orig_data[k] for k in ("id", "CDEDB_EXPORT_EVENT_VERSION",
                                      "timestamp", "kind")
        }

        data = copy.deepcopy(base_data)
        data["registrations"] = {
            1: {
                "tracks": {
                    1: {
                        "course_id": -1,
                    },
                },
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.partial_import_event(
                self.key, data, dryrun=False)
        self.assertIn("Referential integrity of courses violated.",
                      cm.exception.args)

        data = copy.deepcopy(base_data)
        data["registrations"] = {
            1: {
                "parts": {
                    1: {
                        "lodgement_id": -1,
                    },
                },
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.partial_import_event(
                self.key, data, dryrun=False)
        self.assertIn("Referential integrity of lodgements violated.",
                      cm.exception.args)

        data = copy.deepcopy(base_data)
        data["lodgements"] = {
            1: {
                "group_id": -1,
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.partial_import_event(
                self.key, data, dryrun=False)
        self.assertIn("Referential integrity of lodgement groups violated.",
                      cm.exception.args)

    @as_users("annika")
    def test_partial_import_event_twice(self, user):
        with open("/tmp/cdedb-store/testfiles/partial_event_import.json") \
                as datafile:
            data = json.load(datafile)

        # first a test run
        token1, delta = self.event.partial_import_event(
            self.key, data, dryrun=True)
        # second a real run
        token2, delta = self.event.partial_import_event(
            self.key, data, dryrun=False, token=token1)
        self.assertEqual(token1, token2)
        # third another concurrent real run
        with self.assertRaises(PartialImportError):
            self.event.partial_import_event(
                self.key, data, dryrun=False, token=token1)
        token3, delta = self.event.partial_import_event(
            self.key, data, dryrun=True)
        self.assertNotEqual(token1, token3)
        expectation = {
            'courses': {-1: {'description': 'Ein Lichtstrahl traf uns',
                             'fields': {'room': 'Wintergarten'},
                             'instructors': 'The Flash',
                             'max_size': None,
                             'min_size': None,
                             'notes': None,
                             'nr': 'ζ',
                             'segments': {1: False, 3: True},
                             'shortname': 'Blitz',
                             'title': 'Blitzkurs'},
                        3: None,
                        4: {'segments': {1: None}}},
            'lodgement_groups': {-1: {'moniker': 'Geheime Etage'}},
            'lodgements': {-1: {'capacity': 12,
                                'fields': {'contamination': 'none'},
                                'moniker': 'Geheimkabinett',
                                'notes': 'Einfach den unsichtbaren Schildern folgen.',
                                'group_id': -1,
                                'reserve': 2},
                           -2: {'capacity': 42,
                                'fields': {'contamination': 'low'},
                                'moniker': 'Handtuchraum',
                                'notes': 'Hier gibt es Handtücher für jeden.',
                                'group_id': None,
                                'reserve': 0},
                           3: None,
                           4: {'group_id': -1}},
            'registrations': {3: {'tracks': {3: {'course_id': -1,
                                                 'choices': [4, -1, 5]}}},
                              4: None,
                              1001: {'parts': {2: {'lodgement_id': -1}},
                                  'tracks': {3: {'choices': [1, 4, 5, -1],
                                                 'course_id': -1,
                                                 'course_instructor': -1}}}}}
        self.assertEqual(expectation, delta)

    @as_users("annika", "garcia")
    def test_check_registration_status(self, user):
        event_id = 1

        # Check for participant status
        stati = [const.RegistrationPartStati.participant]
        self.assertTrue(self.event.check_registration_status(self.key, 1, event_id, stati))
        self.assertFalse(self.event.check_registration_status(self.key, 3, event_id, stati))
        self.assertTrue(self.event.check_registration_status(self.key, 5, event_id, stati))
        self.assertTrue(self.event.check_registration_status(self.key, 9, event_id, stati))

        # Check for waitlist status
        stati = [const.RegistrationPartStati.waitlist]
        self.assertFalse(self.event.check_registration_status(self.key, 1, event_id, stati))
        self.assertTrue(self.event.check_registration_status(self.key, 5, event_id, stati))
        self.assertFalse(self.event.check_registration_status(self.key, 9, event_id, stati))

    @as_users("emilia", "garcia", "annika")
    def test_calculate_fees(self, user):
        if user['id'] != 5:
            reg_ids = self.event.list_registrations(self.key, event_id=1)
            expectation = {
                1: decimal.Decimal("573.99"),
                2: decimal.Decimal("589.49"),
                3: decimal.Decimal("584.49"),
                4: decimal.Decimal("450.99"),
                5: decimal.Decimal("584.49"),
            }
            self.assertEqual(expectation, self.event.calculate_fees(self.key, reg_ids))
        reg_id = 2
        reg = self.event.get_registration(self.key, reg_id)
        self.assertEqual(reg['amount_owed'], decimal.Decimal("589.49"))
        self.assertEqual(reg['parts'][1]['status'], const.RegistrationPartStati.waitlist)
        self.assertEqual(reg['parts'][2]['status'], const.RegistrationPartStati.guest)
        self.assertEqual(reg['parts'][3]['status'], const.RegistrationPartStati.participant)
        update = {
            'id': reg_id,
            'parts': {
                1: {
                    'status': const.RegistrationPartStati.cancelled,
                },
                2: {
                    'status': const.RegistrationPartStati.participant,
                },
                3: {
                    'status': const.RegistrationPartStati.rejected,
                },
            },
        }
        self.assertLess(0, self.event.set_registration(self.key, update))
        reg = self.event.get_registration(self.key, reg_id)
        self.assertEqual(reg['amount_owed'], decimal.Decimal("128.00"))
        self.assertEqual(reg['parts'][1]['status'],
                         const.RegistrationPartStati.cancelled)
        self.assertEqual(reg['parts'][2]['status'],
                         const.RegistrationPartStati.participant)
        self.assertEqual(reg['parts'][3]['status'],
                         const.RegistrationPartStati.rejected)

    @as_users("annika")
    def test_fee_modifiers(self, user):
        event_id = 1
        field_name = 'is_child'
        data = {
            'id': event_id,
            'fields': {
                -1: {
                    'field_name': field_name,
                    'association': const.FieldAssociations.registration,
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                }
            }
        }
        self.assertTrue(self.event.set_event(self.key, data))
        event = self.event.get_event(self.key, event_id)
        new_field_id = None,
        for field in event['fields'].values():
            if field['field_name'] == field_name:
                new_field_id = field['id']
        field_links = ((2, ValueError, "Fee modifier linked to non-bool field."),
                       (5, ValueError, "Fee modifier linked to non-registration field."),
                       (new_field_id, None, None))
        for field_id, error, error_msg in field_links:
            data = {
                'id': event_id,
                'fee_modifiers': {
                    -1: {
                        'modifier_name': 'child',
                        'amount': decimal.Decimal("-12.50"),
                        'field_id': field_id,
                        'part_id': 2,
                    }
                }
            }
            if error:
                with self.assertRaises(error) as cm:
                    self.event.set_event(self.key, data)
                self.assertEqual(error_msg, cm.exception.args[0])
            else:
                self.assertTrue(self.event.set_event(self.key, data))
        reg_id = 2
        self.assertEqual(self.event.calculate_fee(self.key, reg_id),
                         decimal.Decimal("589.49"))
        data = {
            'id': reg_id,
            'fields': {
                field_name: True,
            }
        }
        self.assertTrue(self.event.set_registration(self.key, data))
        self.assertEqual(self.event.calculate_fee(self.key, reg_id),
                         decimal.Decimal("576.99"))

    @as_users("annika")
    def test_log(self, user):
        # first generate some data
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
            'nonmember_surcharge': decimal.Decimal("6.66"),
            'registration_text': None,
            'mail_text': None,
            'use_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {
                        -1: {'title': "First lecture",
                             'shortname': "First",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1}},
                    'title': "First coming",
                    'shortname': "First",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'fee': decimal.Decimal("234.56"),
                },
                -2: {
                    'tracks': {
                        -1: {'title': "Second lecture",
                             'shortname': "Second",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1}},
                    'title': "Second coming",
                    'shortname': "Second",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'fee': decimal.Decimal("0.00"),
                },
            },
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "instrument",
                    'kind': 1,
                    'entries': None,
                },
                -2: {
                    'association': 1,
                    'field_name': "preferred_excursion_date",
                    'kind': 5,
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
            'tracks': {
                -1: {'title': "Third lecture",
                     'shortname': "Third",
                     'num_choices': 2,
                     'min_choices': 2,
                     'sortkey': 2}},
            'title': "Third coming",
            'shortname': "Third",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'fee': decimal.Decimal("123.40"),
        }
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'fee': decimal.Decimal("1.23"),
            'tracks': {
                1002: {'title': "Second lecture v2",  # hardcoded id 5
                       'shortname': "Second v2",
                       'num_choices': 5,
                       'min_choices': 4,
                       'sortkey': 3}}
        }
        newfield = {
            'association': 1,
            'field_name': "kuea",
            'kind': 1,
            'entries': None,
        }
        changed_field = {
            'association': 1,
            'kind': 5,
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
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': True,
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
            'reserve': 11,
            'group_id': None,
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
             'default_value': None,
             'info': None,
             'readonly': None,
             'input_size': None,
             'title': 'Weitere bla Überschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 2,
             'default_value': 'etc',
             'info': None,
             'readonly': True,
             'input_size': None,
             'title': 'Vehikel',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': 'mit Text darunter und so',
             'readonly': None,
             'input_size': None,
             'title': 'Unterüberschrift',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': 3,
             'default_value': None,
             'info': None,
             'readonly': True,
             'input_size': 5,
             'title': 'Vehikel',
             'kind': const.QuestionnaireUsages.questionnaire,
             },
            {'field_id': None,
             'default_value': None,
             'info': 'nur etwas mehr Text',
             'readonly': None,
             'input_size': None,
             'title': None,
             'kind': const.QuestionnaireUsages.questionnaire,
             },
        ]
        self.event.set_questionnaire(self.key, 1, data)

        ## now check it
        expectation = (
            {'additional_info': None,
             'code': 30,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Hyrule',
             'code': 27,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Hyrule',
             'code': 25,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Hyrule',
             'code': 26,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 51,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 9,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 50,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': 2,
             'submitted_by': user['id']},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 42,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 41,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 40,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Topos theory for the kindergarden',
             'code': 42,
             'ctime': nearly_now(),
             'event_id': 1,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'instrument',
             'code': 22,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'preferred_excursion_date',
             'code': 21,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'kuea',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'First coming',
             'code': 17,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'First lecture',
             'code': 37,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Second coming',
             'code': 16,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Second lecture v2',
             'code': 36,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Third coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Third lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 11,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': 2,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': 1,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 2,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'preferred_excursion_date',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'instrument',
             'code': 20,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Second coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'Second lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'First coming',
             'code': 15,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': 'First lecture',
             'code': 35,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': 7,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 10,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': 2,
             'submitted_by': user['id']},
            {'additional_info': None,
             'code': 1,
             'ctime': nearly_now(),
             'event_id': 1001,
             'persona_id': None,
             'submitted_by': user['id']},
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
        result = self.event.retrieve_log(self.key)
        self.assertEqual(expectation, result)
