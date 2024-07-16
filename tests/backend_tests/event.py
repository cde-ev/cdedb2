#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import collections.abc
import copy
import datetime
import decimal
import json
import unittest
from typing import Any, Dict, List, Optional, cast

import freezegun
import freezegun.api
import psycopg2
import psycopg2.errorcodes
import psycopg2.errors

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models_event
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, CdEDBOptionalMap, CourseFilterPositions, InfiniteEnum,
    RequestState, cast_fields, nearly_now, now, unwrap,
)
from cdedb.common.exceptions import APITokenError, PartialImportError, PrivilegeError
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.models.droid import OrgaToken
from tests.common import (
    ANONYMOUS, USER_DICT, BackendTest, as_users, event_keeper, json_keys_to_int,
    storage,
)

UNIQUE_VIOLATION = psycopg2.errors.lookup(psycopg2.errorcodes.UNIQUE_VIOLATION)
NON_EXISTING_ID = 2 ** 30


class TestEventBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self) -> None:
        data = self.core.get_event_user(self.key, self.user['id'])
        data['display_name'] = "Zelda"
        data['name_supplement'] = "von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'name_supplement', 'display_name', 'telephone'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_event_user(self.key, self.user['id'])
        self.assertEqual(data, new_data)

    @event_keeper
    @as_users("annika", "garcia")
    def test_entity_event(self) -> None:
        # need administrator to create event
        self.login(USER_DICT["annika"])
        old_events = self.event.list_events(self.key)
        data: CdEDBObject = {
            'title': "New Link Academy",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'website_url': "https://www.example.com/test",
            'shortname': 'link',
            'registration_start': datetime.datetime(2000, 11, 22, 0, 0, 0,
                                                    tzinfo=datetime.timezone.utc),
            'registration_soft_limit': datetime.datetime(2022, 1, 2, 0, 0, 0,
                                                         tzinfo=datetime.timezone.utc),
            'registration_hard_limit': None,
            'iban': None,
            'registration_text': None,
            'mail_text': None,
            'participant_info': """Welcome to our

            **new**
            and
            _fancy_

            academy! :)""",
            'use_additional_questionnaire': False,
            'notes': None,
            'field_definition_notes': "No fields plz",
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {
                        -1: {'title': "First lecture",
                             'shortname': "First",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1,
                             'course_room_field_id': None},
                    },
                    'title': "First coming",
                    'shortname': "first",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
                -2: {
                    'tracks': {
                        -1: {'title': "Second lecture",
                             'shortname': "Second",
                             'num_choices': 3,
                             'min_choices': 1,
                             'sortkey': 1,
                             'course_room_field_id': None},
                    },
                    'title': "Second coming",
                    'shortname': "second",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
            },
            'fees': {
                -1: {
                    "kind": const.EventFeeType.common,
                    "title": "first",
                    "notes": None,
                    "amount": decimal.Decimal("234.56"),
                    "condition": "part.first",
                },
                -2: {
                    "kind": const.EventFeeType.common,
                    "title": "second",
                    "notes": None,
                    "amount": decimal.Decimal("0.00"),
                    "condition": "part.second",
                },
                -3: {
                    "kind": const.EventFeeType.solidary_reduction,
                    "title": "Is Child",
                    "notes": None,
                    "amount": decimal.Decimal("-7.00"),
                    "condition": "part.second and field.is_child",
                },
                -4: {
                    "kind": const.EventFeeType.external,
                    "title": "Externenzusatzbeitrag",
                    "notes": None,
                    "amount": decimal.Decimal("6.66"),
                    "condition": "any_part and not is_member",
                },
            },
            'fields': {
                -1: {
                    'association': const.FieldAssociations.registration,
                    'field_name': "instrument",
                    'title': "Instrument",
                    'sortkey': 0,
                    'kind': const.FieldDatatypes.str,
                    'entries': None,
                    'checkin': False,
                },
                -2: {
                    'association': const.FieldAssociations.registration,
                    'field_name': "preferred_excursion_date",
                    'title': "Bevorzugtes Ausflugsdatum",
                    'sortkey': 0,
                    'kind': const.FieldDatatypes.date,
                    'entries': {
                        "2109-08-16": "In the first coming",
                        "2110-08-16": "During the second coming",
                    },
                    'checkin': True,
                },
                -3: {
                    'association': const.FieldAssociations.registration,
                    'field_name': "is_child",
                    'title': "Ist Kind",
                    'sortkey': 5,
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                    'checkin': False,
                },
            },
        }
        new_id = self.event.create_event(self.key, data)
        # back to normal mode
        self.login(self.user)
        data['id'] = new_id
        data['offline_lock'] = False
        data['is_archived'] = False
        data['is_participant_list_visible'] = False
        data['is_course_assignment_visible'] = False
        data['is_course_list_visible'] = False
        data['is_course_state_visible'] = False
        data['is_cancelled'] = False
        data['is_visible'] = False
        data['lodge_field_id'] = None
        data['orga_address'] = None
        # TODO dynamically adapt ids from the database result
        data['parts'][-1].update({'id': 1001})
        data['parts'][-2].update({'id': 1002})
        data['parts'][-1]['tracks'][-1].update({'id': 1001, 'part_id': 1001})
        data['parts'][-2]['tracks'][-1].update({'id': 1002, 'part_id': 1002})
        data['tracks'] = {1001: data['parts'][-1]['tracks'][-1],
                          1002: data['parts'][-2]['tracks'][-1]}
        data['part_groups'] = {}
        data['track_groups'] = {}
        data['custom_query_filters'] = {}
        # correct part and field ids
        tmp = self.event.get_event(self.key, new_id)
        part_map = {}
        for part in tmp.parts:
            for oldpart in data['parts']:
                if tmp.parts[part].title == data['parts'][oldpart]['title']:
                    part_map[tmp.parts[part].title] = part
                    data['parts'][part] = data['parts'][oldpart]
                    data['parts'][part]['id'] = part
                    data['parts'][part]['event_id'] = new_id
                    data['parts'][part]['part_group_ids'] = set()
                    self.assertEqual(
                        set(x['title'] for x in data['parts'][part]['tracks'].values()),
                        set(x.title for x in tmp.parts[part].tracks.values()))
                    data['parts'][part]['tracks'] = tmp.parts[part].as_dict()['tracks']
                    del data['parts'][oldpart]
                    break
        for track in data['tracks'].values():
            track['track_group_ids'] = set()
        field_map: dict[str, int] = {}
        for field in tmp.fields:
            for oldfield in data['fields']:
                if (tmp.fields[field].field_name
                        == data['fields'][oldfield]['field_name']):
                    field_map[tmp.fields[field].field_name] = field
                    data['fields'][field] = data['fields'][oldfield]
                    data['fields'][field]['id'] = field
                    data['fields'][field]['event_id'] = new_id
                    del data['fields'][oldfield]
                    break
        for fee_id in tmp.fees:
            for old_fee_id in data['fees']:
                if tmp.fees[fee_id].title == data['fees'][old_fee_id]['title']:
                    data['fees'][fee_id] = data['fees'][old_fee_id]
                    data['fees'][fee_id]['id'] = fee_id
                    data['fees'][fee_id]['event_id'] = new_id
                    data['fees'][fee_id]['amount_min'] = None
                    data['fees'][fee_id]['amount_max'] = None
                    del data['fees'][old_fee_id]
                    break

        self.assertEqual(data, self.event.get_event(self.key, new_id).as_dict())
        data['title'] = "Alternate Universe Academy"
        newpart = {
            'tracks': {
                -1: {'title': "Third lecture",
                     'shortname': "Third",
                     'num_choices': 2,
                     'min_choices': 2,
                     'sortkey': 2,
                     'course_room_field_id': None},
            },
            'title': "Third coming",
            'shortname': "third",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'waitlist_field_id': None,
            'camping_mat_field_id': 1003,
        }
        changed_part: CdEDBObject = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
            'tracks': {
                1002: {
                    'title': "Second lecture v2",
                    'shortname': "Second v2",
                    'num_choices': 5,
                    'min_choices': 4,
                    'sortkey': 3,
                    'course_room_field_id': None,
                },
            },
        }
        updated_fees: CdEDBOptionalMap = {
            -1: {
                'kind': const.EventFeeType.common,
                'title': "third",
                'notes': None,
                'amount': decimal.Decimal("123.40"),
                'condition': "part.third",
            },
            1002: {
                'amount': decimal.Decimal("1.23"),
            },
            1003: {
                'title': "ist kind",
                'amount': decimal.Decimal("3.33"),
            },
        }
        newfield = {
            'association': const.FieldAssociations.lodgement,
            'field_name': "kuea",
            'title': "KäA",
            'sortkey': -7,
            'kind': const.FieldDatatypes.str,
            'entries': None,
            'checkin': False,
        }
        changed_field = {
            'association': const.FieldAssociations.registration,
            'kind': const.FieldDatatypes.date,
            'entries': {
                "2110-08-15": "early second coming",
                "2110-08-17": "late second coming",
            },
            'checkin': True,
        }
        self.event.set_event(self.key, new_id, {
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
        self.event.set_event_fees(self.key, new_id, updated_fees)
        # fixup parts and fields
        tmp = self.event.get_event(self.key, new_id)
        for part in tmp.parts:
            if tmp.parts[part].title == "Third coming":
                part_map[tmp.parts[part].title] = part
                data['parts'][part] = newpart
                data['parts'][part]['id'] = part
                data['parts'][part]['event_id'] = new_id
                self.assertEqual(
                    set(x['title'] for x in data['parts'][part]['tracks'].values()),
                    set(x.title for x in tmp.parts[part].tracks.values()))
                data['parts'][part]['tracks'] = tmp.parts[part].as_dict()['tracks']
        del data['parts'][part_map["First coming"]]
        changed_part['id'] = part_map["Second coming"]
        changed_part['event_id'] = new_id
        changed_part['shortname'] = "second"
        changed_part['tracks'][1002].update({'part_id': 1002, 'id': 1002})
        data['parts'][part_map["Second coming"]] = changed_part
        for part in data['parts'].values():
            part['part_group_ids'] = set()
            for track in part['tracks'].values():
                track['track_group_ids'] = set()
        for field in tmp.fields:
            if tmp.fields[field].field_name == "kuea":
                field_map[tmp.fields[field].field_name] = field
                data['fields'][field] = newfield
                data['fields'][field]['id'] = field
                data['fields'][field]['event_id'] = new_id
        del data['fields'][field_map["instrument"]]
        changed_field['id'] = field_map["preferred_excursion_date"]
        changed_field['event_id'] = new_id
        changed_field['field_name'] = "preferred_excursion_date"
        data['fields'][field_map["preferred_excursion_date"]].update(changed_field)
        # TODO dynamically adapt ids from the database result
        data['tracks'] = {
            1002: {
                'id': 1002,
                'part_id': 1002,
                'title': 'Second lecture v2',
                'shortname': "Second v2",
                'num_choices': 5,
                'min_choices': 4,
                'sortkey': 3,
                'course_room_field_id': None,
                'track_group_ids': set(),
            },
            1003: {
                'id': 1003,
                'part_id': 1003,
                'title': 'Third lecture',
                'shortname': 'Third',
                'num_choices': 2,
                'min_choices': 2,
                'sortkey': 2,
                'course_room_field_id': None,
                'track_group_ids': set(),
            },
        }
        data['part_groups'] = {}
        del data['fees'][1001]
        data['fees'][1002].update(updated_fees[1002])
        data['fees'][1003].update(updated_fees[1003])
        data['fees'][1005] = updated_fees[-1]
        data['fees'][1005].update({
            'id': 1005, 'event_id': new_id, 'amount_min': None, 'amount_max': None,
        })

        self.assertEqual(data, self.event.get_event(self.key, new_id).as_dict())

        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_events(self.key)
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
            'title': "Nebenan",
        }
        new_group_id = self.event.create_lodgement_group(
            self.key, vtypes.LodgementGroup(new_group))
        self.assertLess(0, new_group_id)
        new_group.update({
            'id': new_group_id,
            'lodgement_ids': [],
            'regular_capacity': 0,
            'camping_mat_capacity': 0,
        })
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))

        new_lodgement = {
            'regular_capacity': 42,
            'event_id': new_id,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
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
                                            'status': 1,
                                            },
                part_map["Third coming"]: {'lodgement_id': new_lodge_id,
                                           'status': 1,
                                           },

            },
            'tracks': {
                1002: {
                    'choices': [new_course_id],
                    'course_id': None,
                    'course_instructor': None,
                },
                1003: {
                    'course_id': None,
                    'course_instructor': None,
                },
            },
            'persona_id': 2,
            'real_persona_id': None,
        }
        new_reg_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_reg_id)

        scope = QueryScope.registration
        event = self.event.get_event(self.key, data['id'])
        query = Query(scope, scope.get_spec(event=event),
                      ['reg.notes'], [('reg.notes', QueryOperators.nonempty, None)],
                      [('reg.notes', True)], name="test_query")
        self.assertTrue(self.event.store_event_query(self.key, new_id, query))
        self.assertEqual(
            self.event.get_event_queries(
                self.key, new_id)["test_query"].serialize_to_url(),
            query.serialize_to_url())
        self.assertEqual(
            self.event.get_event_queries(
                self.key, new_id, scopes={QueryScope.registration},
            )["test_query"].serialize_to_url(),
            query.serialize_to_url())
        self.assertEqual(
            self.event.get_event_queries(
                self.key, new_id, scopes={QueryScope.persona}),
            {},
        )

        self.login(USER_DICT["annika"])
        self.assertLess(0, self.event.delete_event(
            self.key, new_id,
            ("event_parts", "course_tracks", "field_definitions", "courses",
             "orgas", "lodgement_groups", "lodgements", "registrations", "log",
             "questionnaire", "stored_queries", "mailinglists", "event_fees")))

        # Test deletion of event, cascading all blockers.
        self.assertLess(
            0,
            self.event.delete_event(
                self.key, 1, self.event.delete_event_blockers(self.key, 1)))

        # Test part groups and track groups in get_event.
        expectation_part = {
            'id': 6,
            'event_id': 4,
            'title': "1. Hälfte Oberwesel",
            'shortname': "O1",
            'part_begin': datetime.date(3000, 1, 1),
            'part_end': datetime.date(3000, 2, 1),
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
            'tracks': {
                6: {
                    'id': 6,
                    'part_id': 6,
                    'title': "Oberwesel Kurs 1",
                    'shortname': "OK1",
                    'num_choices': 4,
                    'min_choices': 2,
                    'sortkey': 1,
                    'course_room_field_id': None,
                    'track_group_ids': {1},
                },
            },
            'part_group_ids': {1, 3, 6, 8},
        }
        self.assertEqual(
            expectation_part,
            self.event.get_event(self.key, 4).parts[6].as_dict(),
        )

    @as_users("annika")
    def test_track_groups(self) -> None:
        event_id = 4
        event = self.event.get_event(self.key, event_id)
        track_group_ids = self.event.get_event(self.key, event_id).track_groups.keys()
        self.assertTrue(self.event.set_track_groups(self.key, event_id, {
            tg_id: None
            for tg_id in track_group_ids
        }))
        tg_data: CdEDBOptionalMap = {
            -1: {
                'title': "Test",
                'shortname': "Test",
                'constraint_type': const.CourseTrackGroupType.course_choice_sync,
                'notes': None,
                'track_ids': event.tracks.keys(),
                'sortkey': 1,
            },
        }
        assert tg_data[-1] is not None
        # Test incompatible tracks.
        with self.assertRaises(ValueError):
            self.event.set_track_groups(self.key, event_id, tg_data)
        # Test empty tracks.
        tg_data[-1]['track_ids'] = []
        with self.assertRaises(ValueError):
            self.event.set_track_groups(self.key, event_id, tg_data)
        # Test unknown tracks.
        tg_data[-1]['track_ids'] = {1, 2}
        with self.assertRaises(ValueError):
            self.event.set_track_groups(self.key, event_id, tg_data)

        # Test correct tracks.
        tg_data[-1]['track_ids'] = {6, 7}
        self.assertTrue(self.event.set_track_groups(self.key, event_id, tg_data))
        event = self.event.get_event(self.key, event_id)
        tg = tg_data[-1].copy()
        tg['id'] = 1003
        tg['event_id'] = event_id
        tg['tracks'] = {
            track_id: event.tracks[track_id].as_dict()
            for track_id in tg.pop('track_ids')
        }
        self.assertEqual(
            tg, self.event.get_event(self.key, event_id).track_groups[1003].as_dict())

        # Test duplicate tracks.
        with self.assertRaises(ValueError):
            self.event.set_track_groups(self.key, event_id, tg_data)
        # Test dupliclate title.
        with self.assertRaises(psycopg2.errors.UniqueViolation):
            tmp = copy.deepcopy(tg_data)
            assert tmp[-1] is not None
            tmp[-1]['track_ids'] = [8]
            self.event.set_track_groups(self.key, event_id, tmp)

        # Test update
        tg_update: CdEDBOptionalMap = {
            1003: {
                'title': "tEST",
                'track_ids': {7, 8},
            },
        }
        assert tg_update[1003] is not None
        self.assertTrue(self.event.set_track_groups(self.key, event_id, tg_update))
        event = self.event.get_event(self.key, event_id)
        tg.update(tg_update[1003])
        tg['tracks'] = {
            track_id: event.tracks[track_id].as_dict()
            for track_id in tg.pop('track_ids')
        }
        self.assertEqual(
            tg, self.event.get_event(self.key, event_id).track_groups[1003].as_dict())

    @as_users("emilia")
    def test_course_choice_sync(self) -> None:
        event_id = 4
        registration_id = 10
        track_id = 6
        event = self.event.get_event(self.key, event_id)
        self.assertTrue(event.tracks[track_id].track_groups)
        self.assertTrue(unwrap(
            event.tracks[track_id].track_groups).constraint_type.is_sync())
        self.assertGreater(
            len(unwrap(event.tracks[track_id].track_groups).tracks), 1)
        reg_data = {
            'id': registration_id,
            'tracks': {
                track_id: {
                    'choices': [10, 11, 12],
                },
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.set_registration(self.key, reg_data)
        self.assertEqual(cm.exception.args[0], "Incompatible course choices present.")

    @storage
    @as_users("annika", "garcia")
    def test_change_minor_form(self) -> None:
        event_id = 1
        with open("/cdedb2/tests/ancillary_files/form.pdf", "rb") as f:
            minor_form = f.read()
        self.assertIsNone(self.event.get_minor_form(self.key, event_id))
        self.assertLess(0, self.event.change_minor_form(self.key, event_id, minor_form))
        self.assertEqual(minor_form, self.event.get_minor_form(self.key, event_id))
        self.assertGreater(0, self.event.change_minor_form(self.key, event_id, None))
        count, log = self.event.retrieve_log(
            self.key, EventLogFilter(
                codes=[const.EventLogCodes.minor_form_updated,
                       const.EventLogCodes.minor_form_removed],
                event_id=event_id),
        )
        expectation = [
            {
                'code': const.EventLogCodes.minor_form_updated,
                'submitted_by': self.user['id'],
                'persona_id': None,
                'event_id': event_id,
                'ctime': nearly_now(),
                'change_note': None,
            },
            {
                'code': const.EventLogCodes.minor_form_removed,
                'submitted_by': self.user['id'],
                'persona_id': None,
                'event_id': event_id,
                'ctime': nearly_now(),
                'change_note': None,
            },
        ]
        self.assertEqual(len(expectation), len(log))
        for e, l in zip(expectation, log):
            for k in e:
                self.assertEqual(e[k], l[k])

    @as_users("annika")
    def test_aposteriori_track_creation(self) -> None:
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
            'course_room_field_id': None,
        }
        update_event = {
            'parts': {
                part_id: {
                    'tracks': {
                        -1: new_track,
                    },
                },
            },
        }
        self.event.set_event(self.key, event_id, update_event)
        new_track['id'] = new_track_id
        new_track['part_id'] = part_id
        new_track['track_groups'] = {}

        for reg in regs.values():
            reg['tracks'][new_track_id] = {
                'choices': [],
                'course_id': None,
                'course_instructor': None,
                'registration_id': reg['id'],
                'track_id': new_track_id,
            }

        new_track_obj = models_event.CourseTrack.from_database(new_track)
        event.tracks[new_track_id] = new_track_obj
        event.parts[part_id].tracks[new_track_id] = new_track_obj

        reg_ids = self.event.list_registrations(self.key, event_id)
        self.assertEqual(regs, self.event.get_registrations(self.key, reg_ids))
        self.assertEqual(
            event,
            self.event.get_event(self.key, event_id),
        )

    @as_users("annika", "garcia")
    def test_aposteriori_track_deletion(self) -> None:
        event_id = 1
        part_id = 2
        track_id = 1

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id))
        event = self.event.get_event(self.key, event_id)

        expectation = {1, 2, 3}
        self.assertEqual(expectation, event.tracks.keys())
        self.assertIn(track_id, event.parts[part_id].tracks)
        for reg in regs.values():
            self.assertIn(track_id, reg["tracks"])

        edata = {
            'parts': {
                part_id: {
                    'tracks': {
                        track_id: None,
                    },
                },
            },
        }

        self.assertLess(0, self.event.set_event(self.key, event_id, edata))
        event = self.event.get_event(self.key, event_id)
        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id))

        for reg in regs.values():
            self.assertNotIn(track_id, reg["tracks"])

        expectation -= {track_id}
        self.assertEqual(expectation, event.tracks.keys())

    @as_users("annika", "garcia")
    def test_json_fields_with_dates(self) -> None:
        event_id = 1
        update_event = {
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "arrival",
                    'kind': 6,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, update_event)
        reg_id = 1
        update_registration = {
            'id': reg_id,
            'fields': {
                'arrival': datetime.datetime(2222, 11, 9, 8, 55, 44,
                                             tzinfo=datetime.timezone.utc),
            },
        }
        self.event.set_registration(self.key, update_registration)
        data = self.event.get_registration(self.key, reg_id)
        expectation = {
            'anzahl_GROSSBUCHSTABEN': 4,
            'arrival': datetime.datetime(2222, 11, 9, 8, 55, 44,
                                         tzinfo=datetime.timezone.utc),
            'lodge': 'Die üblichen Verdächtigen, insb. Berta Beispiel und '
                     'garcia@example.cde :)',
            'is_child': False,
        }
        self.assertEqual(expectation, data['fields'])

    @as_users("annika", "garcia")
    def test_entity_course(self) -> None:
        event_id = 1
        old_courses = self.event.list_courses(self.key, event_id)
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
        new_courses = self.event.list_courses(self.key, event_id)
        self.assertIn(new_id, new_courses)
        data['active_segments'] = {1}
        self.event.set_course(self.key, {
            'id': new_id, 'active_segments': data['active_segments']})
        self.assertEqual(data,
                         self.event.get_course(self.key, new_id))

    @as_users("annika", "garcia")
    def test_course_non_removable(self) -> None:
        self.assertNotEqual({}, self.event.delete_course_blockers(self.key, 1))

    @as_users("annika", "garcia")
    def test_course_delete(self) -> None:
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
    def test_course_choices_cascade(self) -> None:
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
    def test_visible_events(self) -> None:
        expectation = {
            1: 'Große Testakademie 2222', 3: 'CyberTestAkademie', 4: 'TripelAkademie'}
        self.assertEqual(expectation, self.event.list_events(
            self.key, visible=True, archived=False))

    @as_users("annika", "garcia")
    def test_has_registrations(self) -> None:
        self.assertTrue(self.event.has_registrations(self.key, 1))

    @as_users("emilia")
    def test_registration_participant(self) -> None:
        expectation: CdEDBObject = {
            'amount_paid': decimal.Decimal("0.00"),
            'amount_owed': decimal.Decimal("466.49"),
            'checkin': None,
            'ctime': nearly_now(),
            'event_id': 1,
            'fields': {
                'anzahl_GROSSBUCHSTABEN': 3,
                'brings_balls': True,
                'transportation': 'pedes',
                'is_child': False,
            },
            'list_consent': True,
            'id': 2,
            'is_member': False,
            'mixed_lodging': True,
            'mtime': None,
            'orga_notes': 'Unbedingt in die Einzelzelle.',
            'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
            'parental_agreement': True,
            'parts': {
                1: {
                    'is_camping_mat': False,
                    'lodgement_id': None,
                    'part_id': 1,
                    'registration_id': 2,
                    'status': 3,
                },
                2: {
                    'is_camping_mat': False,
                    'lodgement_id': 4,
                    'part_id': 2,
                    'registration_id': 2,
                    'status': 4,
                },
                3: {
                    'is_camping_mat': False,
                    'lodgement_id': 4,
                    'part_id': 3,
                    'registration_id': 2,
                    'status': 2,
                },
            },
            'tracks': {
                1: {
                    'choices': [5, 4, 2, 1],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 1,
                },
                2: {
                    'choices': [3],
                    'course_id': None,
                    'course_instructor': None,
                    'registration_id': 2,
                    'track_id': 2,
                },
                3: {
                    'choices': [4, 2],
                    'course_id': 1,
                    'course_instructor': 1,
                    'registration_id': 2,
                    'track_id': 3,
                },
            },
            'personalized_fees': {},
            'payment': datetime.date(2014, 2, 2),
            'persona_id': 5,
            'real_persona_id': None,
        }
        self.assertEqual(expectation, self.event.get_registration(self.key, 2))
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
        expectation['mtime'] = nearly_now()
        self.assertEqual(expectation, self.event.get_registration(self.key, 2))

    @as_users("berta", "paul")
    def test_registering(self) -> None:
        new_reg: CdEDBObject = {
            'checkin': None,
            'event_id': 1,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'parental_agreement': True,
            'parts': {
                1: {
                    'is_camping_mat': False,
                    'lodgement_id': None,
                    'status': 1,
                },
                2: {
                    'is_camping_mat': False,
                    'lodgement_id': None,
                    'status': 1,
                },
                3: {
                    'is_camping_mat': False,
                    'lodgement_id': None,
                    'status': 1,
                },
            },
            'tracks': {
                1: {
                    'choices': [1, 4, 5],
                    'course_id': None,
                    'course_instructor': None,
                },
                2: {
                    'course_id': None,
                    'course_instructor': None,
                },
                3: {
                    'course_id': None,
                    'course_instructor': None,
                },
            },
            'notes': "Some bla.",
            'persona_id': 16,
            'real_persona_id': None}
        # try to create a registration for paul
        if self.user_in('paul'):
            new_id = self.event.create_registration(self.key, new_reg)
            self.assertLess(0, new_id)
            new_reg['id'] = new_id
            # amount_owed include non-member additional fee
            new_reg['amount_owed'] = decimal.Decimal("589.48")
            new_reg['amount_paid'] = decimal.Decimal("0.00")
            new_reg['payment'] = None
            new_reg['personalized_fees'] = {}
            new_reg['is_member'] = False
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
            new_reg['ctime'] = nearly_now()
            new_reg['mtime'] = None
            self.assertEqual(new_reg, self.event.get_registration(self.key, new_id))
        else:
            with self.assertRaises(PrivilegeError):
                self.event.create_registration(self.key, new_reg)

    @as_users("annika", "garcia")
    def test_entity_registration(self) -> None:
        event_id = 1
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2},
                         self.event.list_registrations(self.key, event_id))
        expectation: CdEDBObjectMap = {
            1: {
                'amount_owed': decimal.Decimal("553.99"),
                'amount_paid': decimal.Decimal("200.00"),
                'checkin': None,
                'ctime': nearly_now(),
                'event_id': 1,
                'fields': {
                    'anzahl_GROSSBUCHSTABEN': 4,
                    'lodge': 'Die üblichen Verdächtigen, insb. Berta Beispiel '
                             'und garcia@example.cde :)',
                    'is_child': False,
                },
                'list_consent': True,
                'id': 1,
                'is_member': True,
                'mixed_lodging': True,
                'mtime': None,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': True,
                'parts': {
                    1: {
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 1,
                        'status': const.RegistrationPartStati.not_applied,
                    },
                    2: {
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 1,
                        'status': const.RegistrationPartStati.applied,
                    },
                    3: {
                        'is_camping_mat': False,
                        'lodgement_id': 1,
                        'part_id': 3,
                        'registration_id': 1,
                        'status': const.RegistrationPartStati.participant,
                    },
                },
                'tracks': {
                    1: {
                        'choices': [1, 3, 4, 2],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 1,
                    },
                    2: {
                        'choices': [2],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 2,
                    },
                    3: {
                        'choices': [1, 4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 1,
                        'track_id': 3,
                    },
                },
                'personalized_fees': {
                    10: decimal.Decimal("-20.00"),
                },
                'payment': None,
                'persona_id': 1,
                'real_persona_id': None,
            },
            2: {
                'amount_owed': decimal.Decimal("466.49"),
                'amount_paid': decimal.Decimal("0.00"),
                'checkin': None,
                'ctime': nearly_now(),
                'event_id': 1,
                'fields': {
                    'anzahl_GROSSBUCHSTABEN': 3,
                    'brings_balls': True,
                    'transportation': 'pedes',
                    'is_child': False,
                },
                'list_consent': True,
                'id': 2,
                'is_member': False,
                'mixed_lodging': True,
                'mtime': None,
                'orga_notes': 'Unbedingt in die Einzelzelle.',
                'notes': 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett',
                'parental_agreement': True,
                'parts': {
                    1: {
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 2,
                        'status': const.RegistrationPartStati.waitlist,
                    },
                    2: {
                        'is_camping_mat': False,
                        'lodgement_id': 4,
                        'part_id': 2,
                        'registration_id': 2,
                        'status': const.RegistrationPartStati.guest,
                    },
                    3: {
                        'is_camping_mat': False,
                        'lodgement_id': 4,
                        'part_id': 3,
                        'registration_id': 2,
                        'status': const.RegistrationPartStati.participant,
                    },
                },
                'tracks': {
                    1: {
                        'choices': [5, 4, 2, 1],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 1,
                    },
                    2: {
                        'choices': [3],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 2,
                        'track_id': 2,
                    },
                    3: {
                        'choices': [4, 2],
                        'course_id': 1,
                        'course_instructor': 1,
                        'registration_id': 2,
                        'track_id': 3,
                    },
                },
                'personalized_fees': {},
                'payment': datetime.date(2014, 2, 2),
                'persona_id': 5,
                'real_persona_id': None,
            },
            4: {
                'amount_owed': decimal.Decimal("431.99"),
                'amount_paid': decimal.Decimal("0.00"),
                'checkin': None,
                'ctime': nearly_now(),
                'event_id': 1,
                'fields': {
                    'anzahl_GROSSBUCHSTABEN': 2,
                    'brings_balls': False,
                    'may_reserve': True,
                    'transportation': 'etc',
                    'is_child': True,
                },
                'list_consent': False,
                'id': 4,
                'is_member': True,
                'mixed_lodging': False,
                'mtime': None,
                'orga_notes': None,
                'notes': None,
                'parental_agreement': False,
                'parts': {
                    1: {
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 4,
                        'status': const.RegistrationPartStati.rejected,
                    },
                    2: {
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 4,
                        'status': const.RegistrationPartStati.cancelled,
                    },
                    3: {
                        'is_camping_mat': True,
                        'lodgement_id': 2,
                        'part_id': 3,
                        'registration_id': 4,
                        'status': const.RegistrationPartStati.participant,
                    },
                },
                'tracks': {
                    1: {
                        'choices': [2, 1, 4, 5],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 1,
                    },
                    2: {
                        'choices': [4],
                        'course_id': None,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 2,
                    },
                    3: {
                        'choices': [1, 2],
                        'course_id': 1,
                        'course_instructor': None,
                        'registration_id': 4,
                        'track_id': 3,
                    },
                },
                'personalized_fees': {},
                'payment': datetime.date(2014, 4, 4),
                'persona_id': 9,
                'real_persona_id': None,
            },
        }
        self.assertEqual(expectation,
                         self.event.get_registrations(self.key, (1, 2, 4)))
        data: CdEDBObject = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(datetime.timezone.utc),
            'parts': {
                1: {
                    'status': const.RegistrationPartStati.participant,
                    'lodgement_id': 2,
                },
                3: {
                    'status': const.RegistrationPartStati.rejected,
                    'lodgement_id': None,
                },
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
                },
            },
        }
        self.assertLess(0, self.event.set_registration(self.key, data))
        expectation[4]['tracks'][1]['choices'] = data['tracks'][1]['choices']
        expectation[4]['tracks'][2]['choices'] = data['tracks'][2]['choices']
        expectation[4]['fields'].update(data['fields'])
        expectation[4]['mixed_lodging'] = data['mixed_lodging']
        expectation[4]['checkin'] = nearly_now()
        expectation[4]['mtime'] = nearly_now()
        expectation[4]['amount_owed'] = decimal.Decimal("5.50")
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        for key, value in expectation[4]['tracks'].items():
            if key in data['tracks']:
                value.update(data['tracks'][key])
        data = self.event.get_registrations(self.key, (1, 2, 4))
        self.assertEqual(expectation, data)
        new_reg: CdEDBObject = {
            'checkin': None,
            'event_id': event_id,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': False,
            'parts': {
                1: {
                    'lodgement_id': None,
                    'status': const.RegistrationPartStati.applied,
                },
                2: {
                    'lodgement_id': None,
                    'status': const.RegistrationPartStati.applied,
                },
                3: {
                    'lodgement_id': None,
                    'status': const.RegistrationPartStati.applied,
                },
            },
            'tracks': {
                1: {
                    'choices': [1, 2, 4, 5],
                    'course_id': None,
                    'course_instructor': None,
                },
                2: {
                    'course_id': None,
                    'course_instructor': None,
                },
                3: {
                    'course_id': None,
                    'course_instructor': None,
                },
            },
            'persona_id': 999,
            'real_persona_id': None,
        }
        with self.assertRaises(ValueError) as cm:
            self.event.create_registration(self.key, new_reg)
        self.assertIn("This user does not exist or is archived.",
                      cm.exception.args)
        new_reg['persona_id'] = 8
        with self.assertRaises(ValueError) as cm:
            self.event.create_registration(self.key, new_reg)
        self.assertIn("This user does not exist or is archived.",
                      cm.exception.args)
        new_reg['persona_id'] = 11
        with self.assertRaises(ValueError) as cm:
            self.event.create_registration(self.key, new_reg)
        self.assertIn("This user is not an event user.", cm.exception.args)

        new_reg['persona_id'] = 3
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['amount_owed'] = decimal.Decimal("584.48")
        new_reg['amount_paid'] = decimal.Decimal("0.00")
        new_reg['payment'] = None
        new_reg['personalized_fees'] = {}
        new_reg['is_member'] = True
        new_reg['fields'] = {}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][1]['is_camping_mat'] = False
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][2]['is_camping_mat'] = False
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        new_reg['parts'][3]['is_camping_mat'] = False
        new_reg['tracks'][1]['track_id'] = 1
        new_reg['tracks'][1]['registration_id'] = new_id
        new_reg['tracks'][2]['track_id'] = 2
        new_reg['tracks'][2]['registration_id'] = new_id
        new_reg['tracks'][2]['choices'] = []
        new_reg['tracks'][3]['track_id'] = 3
        new_reg['tracks'][3]['registration_id'] = new_id
        new_reg['tracks'][3]['choices'] = []
        new_reg['ctime'] = nearly_now()
        new_reg['mtime'] = None
        self.assertEqual(new_reg,
                         self.event.get_registration(self.key, new_id))
        self.assertEqual({1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2, new_id: 3},
                         self.event.list_registrations(self.key, event_id))

    @as_users("annika", "garcia")
    def test_registration_delete(self) -> None:
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(expectation, self.event.list_registrations(self.key, 1))
        with self.assertRaises(ValueError):
            self.event.delete_registration(
                self.key, 1, ("registration_parts", "registration_tracks",
                              "course_choices"))
        del expectation[1]
        for reg_id in expectation.keys():
            self.assertLess(0, self.event.delete_registration(
                self.key, reg_id, ("registration_parts", "registration_tracks",
                              "course_choices")))
        self.assertEqual({1: 1}, self.event.list_registrations(self.key, 1))

    @as_users("annika", "garcia")
    def test_course_filtering(self) -> None:
        event_id = 1
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(
            expectation, self.event.registrations_by_course(self.key, event_id))
        self.assertEqual({}, self.event.registrations_by_course(
            self.key, event_id, position=InfiniteEnum(
                CourseFilterPositions.specific_rank, 1)))
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, track_id=3))
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1))
        expectation = {2: 5, 4: 9, 5: 100}
        self.assertEqual(expectation, self.event.registrations_by_course(
            self.key, event_id, course_id=1, position=InfiniteEnum(
                CourseFilterPositions.assigned, 0)))

    @as_users("annika", "garcia")
    def test_entity_lodgement_group(self) -> None:
        event_id = 1
        expectation_list = {
            1: "Haupthaus",
            2: "AußenWohnGruppe",
            3: "Sonstige",
        }
        group_ids = self.event.list_lodgement_groups(self.key, event_id)
        self.assertEqual(expectation_list, group_ids)

        expectation_groups = {
            1: {
                'id': 1,
                'event_id': 1,
                'title': "Haupthaus",
                'lodgement_ids': [2, 4],
                'camping_mat_capacity': 2,
                'regular_capacity': 11,
            },
            2: {
                'id': 2,
                'event_id': 1,
                'title': "AußenWohnGruppe",
                'lodgement_ids': [1],
                'camping_mat_capacity': 1,
                'regular_capacity': 5,
            },
            3: {
                'id': 3,
                'event_id': 1,
                'title': "Sonstige",
                'lodgement_ids': [3],
                'camping_mat_capacity': 100,
                'regular_capacity': 0,
            },
        }
        self.assertEqual(expectation_groups,
                         self.event.get_lodgement_groups(self.key, group_ids))

        new_group: CdEDBObject = {
            'event_id': event_id,
            'title': "Nebenan",
        }
        new_group_id = self.event.create_lodgement_group(
            self.key, vtypes.LodgementGroup(new_group))
        self.assertLess(0, new_group_id)
        new_group.update({
            'id': new_group_id,
            'lodgement_ids': [],
            'camping_mat_capacity': 0,
            'regular_capacity': 0,
        })
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))
        update = {
            'id': new_group_id,
            'title': "Auf der anderen Rheinseite",
        }
        self.assertLess(0, self.event.set_lodgement_group(self.key, update))
        new_group.update(update)
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))

        new_lodgement: CdEDBObject = {
            'regular_capacity': 42,
            'event_id': 1,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': new_group_id,
        }
        new_lodgement_id = self.event.create_lodgement(self.key, new_lodgement)
        self.assertLess(0, new_lodgement_id)
        new_lodgement.update({
            'id': new_lodgement_id,
            'fields': {},
        })
        self.assertEqual(
            new_lodgement, self.event.get_lodgement(self.key, new_lodgement_id))

        new_group.update({
            'camping_mat_capacity': new_lodgement['camping_mat_capacity'],
            'regular_capacity': new_lodgement['regular_capacity'],
            'lodgement_ids': [new_lodgement_id],
        })
        self.assertEqual(
            new_group, self.event.get_lodgement_group(self.key, new_group_id))

        expectation_list[new_group_id] = new_group['title']
        self.assertEqual(expectation_list,
                         self.event.list_lodgement_groups(self.key, event_id))
        self.assertLess(
            0, self.event.delete_lodgement_group(
                self.key, new_group_id, ("lodgements",)))
        del expectation_list[new_group_id]
        self.assertEqual(
            expectation_list, self.event.list_lodgement_groups(self.key, event_id))

        self.assertNotIn(
            new_lodgement_id, self.event.list_lodgements(self.key, event_id))

    @storage
    @as_users("annika")
    def test_implicit_lodgement_group(self) -> None:
        new_event_data = {
            'title': "KreativAkademie",
            'shortname': "KreAka",
            'institution': 1,
            'description': None,
            'parts': {
                -1: {
                    'part_begin': "2222-02-02",
                    'part_end': "2222-02-22",
                    'title': "KreativAkademie",
                    'shortname': "KreAka",
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
            },
        }
        new_event_id = self.event.create_event(self.key, new_event_data)
        groups = self.event.list_lodgement_groups(self.key, new_event_id)
        groups_expectation = {1001: new_event_data['title']}
        self.assertEqual(groups_expectation, groups)

    @as_users("annika", "garcia")
    def test_entity_lodgement(self) -> None:
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
                'regular_capacity': 5,
                'event_id': 1,
                'fields': {'contamination': 'high'},
                'id': 1,
                'title': 'Warme Stube',
                'notes': None,
                'camping_mat_capacity': 1,
                'group_id': 2,
            },
            4: {
                'regular_capacity': 1,
                'event_id': 1,
                'fields': {'contamination': 'high'},
                'id': 4,
                'title': 'Einzelzelle',
                'notes': None,
                'camping_mat_capacity': 0,
                'group_id': 1,
            },
        }
        self.assertEqual(expectation_get, self.event.get_lodgements(self.key, (1, 4)))
        new = {
            'regular_capacity': 42,
            'event_id': 1,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': 3,
        }
        new_id = self.event.create_lodgement(self.key, new)
        self.assertLess(0, new_id)
        new['id'] = new_id
        new['fields'] = {}
        self.assertEqual(new, self.event.get_lodgement(self.key, new_id))
        update = {
            'regular_capacity': 21,
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
            new_id: 'HY',
        }
        self.assertEqual(expectation_list,
                         self.event.list_lodgements(self.key, event_id))
        self.assertLess(0, self.event.delete_lodgement(self.key, new_id))
        del expectation_list[new_id]
        self.assertLess(0, self.event.delete_lodgement(self.key, 1,
                                                       cascade={"inhabitants"}))
        del expectation_list[1]
        self.assertEqual(expectation_list,
                         self.event.list_lodgements(self.key, event_id))

    @as_users("berta", "emilia")
    def test_get_questionnaire(self) -> None:
        event_id = 1
        expectation = {
            const.QuestionnaireUsages.registration:
                [
                    {'field_id': 7,
                     'default_value': None,
                     'info': None,
                     'pos': 0,
                     'readonly': False,
                     'input_size': None,
                     'title': 'Ich bin unter 13 Jahre alt.',
                     'kind': const.QuestionnaireUsages.registration,
                     },
                ],
            const.QuestionnaireUsages.additional: [
                {
                    'field_id': None,
                    'default_value': None,
                    'info': 'mit Text darunter',
                    'pos': 0,
                    'readonly': None,
                    'input_size': None,
                    'title': 'Unterüberschrift',
                    'kind': const.QuestionnaireUsages.additional,
                },
                {
                    'field_id': 1,
                    'default_value': 'True',
                    'info': 'Du bringst genug Bälle mit um einen ganzen Kurs'
                            ' abzuwerfen.',
                    'pos': 1,
                    'readonly': False,
                    'input_size': None,
                    'title': 'Bälle',
                    'kind': const.QuestionnaireUsages.additional,
                },
                {
                    'field_id': None,
                    'default_value': None,
                    'info': 'nur etwas Text',
                    'pos': 2,
                    'readonly': None,
                    'input_size': None,
                    'title': None,
                    'kind': const.QuestionnaireUsages.additional,
                },
                {
                    'field_id': None,
                    'default_value': None,
                    'info': None,
                    'pos': 3,
                    'readonly': None,
                    'input_size': None,
                    'title': 'Weitere Überschrift',
                    'kind': const.QuestionnaireUsages.additional,
                },
                {
                    'field_id': 2,
                    'default_value': 'etc',
                    'info': None,
                    'pos': 4,
                    'readonly': False,
                    'input_size': None,
                    'title': 'Vehikel',
                    'kind': const.QuestionnaireUsages.additional,
                },
                {
                    'field_id': 3,
                    'default_value': None,
                    'info': None,
                    'pos': 5,
                    'readonly': False,
                    'input_size': 3,
                    'title': 'Hauswunsch',
                    'kind': const.QuestionnaireUsages.additional,
                },
            ],
        }
        self.assertEqual(expectation,
                         self.event.get_questionnaire(self.key, event_id))

    @as_users("annika", "garcia")
    def test_set_questionnaire(self) -> None:
        event_id = 1
        edata = {
            'fields': {
                -1: {
                    'field_name': 'solidarity',
                    'kind': const.FieldDatatypes.bool,
                    'association': const.FieldAssociations.registration,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, edata)
        qdata: Dict[const.QuestionnaireUsages, List[CdEDBObject]] = {
            const.QuestionnaireUsages.additional: [
                {
                    'field_id': None,
                    'default_value': None,
                    'info': None,
                    'readonly': None,
                    'input_size': None,
                    'title': 'Weitere bla Überschrift',
                },
                {
                    'field_id': 2,
                    'default_value': 'etc',
                    'info': None,
                    'readonly': True,
                    'input_size': None,
                    'title': 'Vehikel',
                },
                {
                    'field_id': None,
                    'default_value': None,
                    'info': 'mit Text darunter und so',
                    'readonly': None,
                    'input_size': None,
                    'title': 'Unterüberschrift',
                },
                {
                    'field_id': 3,
                    'default_value': None,
                    'info': None,
                    'readonly': True,
                    'input_size': 5,
                    'title': 'Vehikel',
                },
                {
                    'field_id': None,
                    'default_value': None,
                    'info': 'nur etwas mehr Text',
                    'readonly': None,
                    'input_size': None,
                    'title': None,
                },
            ],
            const.QuestionnaireUsages.registration: [
                {
                    'field_id': 1001,
                    'default_value': None,
                    'info': "Du kannst freiwillig etwas mehr bezahlen um zukünftige"
                            " Akademien zu unterstützen.",
                    'readonly': False,
                    'input_size': None,
                    'title': "Ich möchte den Solidaritätszuschlag bezahlen.",
                },
            ],
        }
        self.assertLess(0, self.event.set_questionnaire(self.key, event_id, qdata))
        for k, v in qdata.items():
            for pos, row in enumerate(v):
                row['pos'] = pos
                row['kind'] = k
        result = self.event.get_questionnaire(self.key, event_id)
        self.assertEqual(qdata, result)

    @as_users("annika", "garcia")
    def test_registration_query(self) -> None:
        scope = QueryScope.registration
        query = Query(
            scope=scope,
            spec=scope.get_spec(event=self.event.get_event(self.key, 1)),
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
            order=(("reg.id", True),))

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
             'reg_fields.xfield_transportation': 'pedes'},
            {'birthday': datetime.date(1981, 2, 11),
             'course1.xfield_room': None,
             'course2.id': None,
             'id': 6,
             'is_cde_realm': True,
             'lodgement1.id': None,
             'lodgement2.xfield_contamination': None,
             'part3.status': -1,
             'persona.family_name': 'Beispiel',
             'reg.id': 6,
             'reg.payment': None,
             'reg_fields.xfield_brings_balls': None,
             'reg_fields.xfield_transportation': 'pedes'})
        self.assertEqual(expectation, result)

    @as_users("annika")
    def test_queries_without_fields(self) -> None:
        # Check that the query views work if there are no custom fields.
        event = self.event.get_event(self.key, 3)
        self.assertFalse(event.fields)
        query = Query(
            scope=QueryScope.registration,
            spec=QueryScope.registration.get_spec(event=event),
            fields_of_interest=["reg.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=2)
        self.assertEqual(tuple(), result)
        query = Query(
            scope=QueryScope.event_course,
            spec=QueryScope.event_course.get_spec(event=event),
            fields_of_interest=["course.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=2)
        self.assertEqual(tuple(), result)
        query = Query(
            scope=QueryScope.lodgement,
            spec=QueryScope.lodgement.get_spec(event=event),
            fields_of_interest=["lodgement.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=2)
        self.assertEqual(tuple(), result)

    @as_users("garcia")
    def test_lodgement_query(self) -> None:
        query = Query(
            scope=QueryScope.lodgement,
            spec=QueryScope.lodgement.get_spec(event=self.event.get_event(self.key, 1)),
            fields_of_interest=[
                "lodgement.regular_capacity",
                "lodgement.group_id",
                "lodgement.title",
                "lodgement.camping_mat_capacity",
                "lodgement_fields.xfield_contamination",
                "lodgement_group.title",
                "lodgement_group.regular_capacity",
                "lodgement_group.camping_mat_capacity",
                "part1.regular_inhabitants",
                "part1.camping_mat_inhabitants",
                "part1.total_inhabitants",
                "part1.group_regular_inhabitants",
                "part1.group_camping_mat_inhabitants",
                "part1.group_total_inhabitants",
            ],
            constraints=[
                ("lodgement.id", QueryOperators.oneof, [2, 4]),
            ],
            order=[
                ("lodgement.id", False),
            ],
        )
        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {
                'id': 4,
                'lodgement.regular_capacity': 1,
                'lodgement.group_id': 1,
                'lodgement.title': "Einzelzelle",
                'lodgement.camping_mat_capacity': 0,
                'lodgement_fields.xfield_contamination': 'high',
                'lodgement_group.regular_capacity': 11,
                'lodgement_group.title': 'Haupthaus',
                'lodgement_group.camping_mat_capacity': 2,
                'part1.group_regular_inhabitants': 2,
                'part1.group_camping_mat_inhabitants': 0,
                'part1.group_total_inhabitants': 2,
                'part1.regular_inhabitants': 1,
                'part1.camping_mat_inhabitants': 0,
                'part1.total_inhabitants': 1,
            },
            {
                'id': 2,
                'lodgement.regular_capacity': 10,
                'lodgement.group_id': 1,
                'lodgement.title': "Kalte Kammer",
                'lodgement.camping_mat_capacity': 2,
                'lodgement_fields.xfield_contamination': 'none',
                'lodgement_group.regular_capacity': 11,
                'lodgement_group.title': 'Haupthaus',
                'lodgement_group.camping_mat_capacity': 2,
                'part1.group_regular_inhabitants': 2,
                'part1.group_camping_mat_inhabitants': 0,
                'part1.group_total_inhabitants': 2,
                'part1.regular_inhabitants': 1,
                'part1.camping_mat_inhabitants': 0,
                'part1.total_inhabitants': 1,
            },
        )
        self.assertEqual(result, expectation)

    @as_users("garcia")
    def test_course_query(self) -> None:
        query = Query(
            scope=QueryScope.event_course,
            spec=QueryScope.event_course.get_spec(
                event=self.event.get_event(self.key, 1)),
            fields_of_interest=[
                "course.id",
                "track1.attendees",
                "track2.is_offered",
                "track3.num_choices1",
                "track3.instructors",
                "course_fields.xfield_room"],
            constraints=[],
            order=[("course.max_size", True) ],
        )
        result = self.event.submit_general_query(self.key, query, event_id=1)
        expectation = (
            {'course.id': 1,
             'course_fields.xfield_room': 'Wald',
             'id': 1,
             'max_size': 10,
             'track1.attendees': 0,
             'track2.is_offered': False,
             'track3.instructors': 1,
             'track3.num_choices1': 0},
            {'course.id': 3,
             'course_fields.xfield_room': 'Seminarraum 42',
             'id': 3,
             'max_size': 14,
             'track1.attendees': 0,
             'track3.instructors': 0,
             'track2.is_offered': True,
             'track3.num_choices1': 0},
            {'course.id': 2,
             'course_fields.xfield_room': 'Theater',
             'id': 2,
             'max_size': 20,
             'track1.attendees': 0,
             'track2.is_offered': True,
             'track3.instructors': 0,
             'track3.num_choices1': 2},
            {'course.id': 4,
             'course_fields.xfield_room': 'Seminarraum 23',
             'id': 4,
             'max_size': None,
             'track1.attendees': 0,
             'track2.is_offered': True,
             'track3.instructors': 0,
             'track3.num_choices1': 3},
            {'course.id': 5,
             'course_fields.xfield_room': 'Nirwana',
             'id': 5,
             'max_size': None,
             'track1.attendees': 0,
             'track2.is_offered': True,
             'track3.instructors': 0,
             'track3.num_choices1': 0},
            {'course.id': 13,
             'course_fields.xfield_room': None,
             'id': 13,
             'max_size': None,
             'track1.attendees': 0,
             'track2.is_offered': True,
             'track3.instructors': 0,
             'track3.num_choices1': 0})
        self.assertEqual(result, expectation)

    @as_users("annika")
    def test_is_instructor_query(self) -> None:
        registrations = (
            {
                "id": 1,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value,
                    },
                },
                "tracks": {
                    1: {
                        "course_id": 1,
                        "course_instructor": 1,
                    },
                },
            },
            {
                "id": 2,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value,
                    },
                },
                "tracks": {
                    1: {
                        "course_id": 1,
                        "course_instructor": None,
                    },
                },
            },
            {
                "id": 3,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value,
                    },
                },
                "tracks": {
                    1: {
                        "course_id": None,
                        "course_instructor": 1,
                    },
                },
            },
            {
                "id": 4,
                "parts": {
                    2: {
                        "status": const.RegistrationPartStati.participant.value,
                    },
                },
                "tracks": {
                    1: {
                        "course_id": None,
                        "course_instructor": None,
                    },
                },
            },
        )

        for reg in registrations:
            self.assertLess(0, self.event.set_registration(self.key, reg))

        query = Query(
            scope=QueryScope.registration,
            spec=QueryScope.registration.get_spec(
                event=self.event.get_event(self.key, 1)),
            fields_of_interest=("reg.id", "track1.is_course_instructor"),
            constraints=[],
            order=(("reg.id", True),),
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
            },
            {
                "id": 6,
                "reg.id": 6,
                'track1.is_course_instructor': None,
            },
        )
        self.assertEqual(expectation, result)

    @as_users("garcia")
    def test_store_event_query(self) -> None:
        event_id = 1
        event = self.event.get_event(self.key, event_id)
        # Try storing valid queries.
        expectation = {}
        query = Query(
            QueryScope.registration, QueryScope.registration.get_spec(event=event),
            fields_of_interest=["persona.family_name", "reg.payment",
                                "ctime.creation_time", "part1.status", "course2.title",
                                "lodgement3.title", "reg_fields.xfield_brings_balls",
                                ],
            constraints=[],
            order=[],
            name="My registration query :)",
        )
        query.query_id = self.event.store_event_query(self.key, event_id, query)
        expectation[query.name] = query
        query = Query(
            QueryScope.lodgement, QueryScope.lodgement.get_spec(event=event),
            fields_of_interest=["lodgement.title", "lodgement_group.title",
                                "part1.total_inhabitants",
                                "lodgement_fields.xfield_contamination"],
            constraints=[],
            order=[],
            name="Lodgement Query with funny symbol: 🏠",
        )
        query.query_id = self.event.store_event_query(self.key, event_id, query)
        expectation[query.name] = query
        query = Query(
            QueryScope.event_course, QueryScope.event_course.get_spec(event=event),
            fields_of_interest=["course.title", "track1.is_offered",
                                "course_fields.xfield_room",
                                ],
            constraints=[],
            order=[],
            name="custom_course_query",
        )
        query.query_id = self.event.store_event_query(self.key, event_id, query)
        expectation[query.name] = query

        result = self.event.get_event_queries(self.key, event_id)
        for name, query in result.items():
            if name != "Test-Query":
                self.assertIn(name, expectation)
                q = expectation[name]
                self.assertEqual(set(q.fields_of_interest),
                                 set(query.fields_of_interest))
                self.assertEqual(set(q.constraints), set(query.constraints))
                self.assertEqual(set(q.order), set(query.order))
                self.assertEqual(q.query_id, query.query_id)
            assert query.query_id is not None
            self.assertTrue(self.event.delete_event_query(self.key, query.query_id))
        self.assertEqual({}, self.event.get_event_queries(self.key, event_id))

        # Now try some invalid things.
        query = Query(
            None, {},  # type: ignore[arg-type]
            fields_of_interest=[],
            constraints=[],
            order=[],
            name="",
        )
        with self.assertRaises(ValueError) as cm:
            self.event.store_event_query(self.key, event_id, query)
        self.assertIn("Invalid input for the enumeration %(enum)s (scope)",
                      cm.exception.args)
        query.scope = QueryScope.persona
        with self.assertRaises(ValueError) as cm:
            self.event.store_event_query(self.key, event_id, query)
        self.assertIn("Must not be empty. (fields_of_interest)", cm.exception.args)
        query.fields_of_interest = ["persona.id"]
        with self.assertRaises(ValueError) as cm:
            self.event.store_event_query(self.key, event_id, query)
        self.assertIn("Cannot store this kind of query.", cm.exception.args)
        query.scope = QueryScope.registration
        self.assertFalse(self.event.store_event_query(self.key, event_id, query))
        query.name = "test"
        self.assertTrue(self.event.store_event_query(self.key, event_id, query))

        # Store a query using a custom datafield using a datatype specific comparison.
        field_data = {
            "field_name": "foo",
            "kind": const.FieldDatatypes.str,
            "association": const.FieldAssociations.registration,
            "entries": None,
        }
        event_data = {
            "fields": {
                -1: field_data,
            },
        }
        self.event.set_event(self.key, event_id, event_data)
        event = self.event.get_event(self.key, event_id)
        query = Query(
            QueryScope.registration, QueryScope.registration.get_spec(event=event),
            ["reg_fields.xfield_foo"],
            [("reg_fields.xfield_foo", QueryOperators.equal, "foo")],
            [],
            name="foo_string",
        )
        self.assertTrue(self.event.store_event_query(self.key, event_id, query))
        self.assertIn(query.name, self.event.get_event_queries(self.key, event_id))

        # Now change the datatype of that field.
        field_data["kind"] = const.FieldDatatypes.date
        del field_data["field_name"]
        event_data["fields"] = {1001: field_data}
        self.event.set_event(self.key, event_id, event_data)

        # The query can no longer be retrieved.
        self.assertNotIn(query.name, self.event.get_event_queries(self.key, event_id))

        # Change the field back.
        field_data["kind"] = const.FieldDatatypes.str
        self.event.set_event(self.key, event_id, event_data)

        # The query is valid again.
        self.assertIn(query.name, self.event.get_event_queries(self.key, event_id))

    @event_keeper
    @as_users("annika", "garcia")
    def test_lock_event(self) -> None:
        self.assertTrue(self.event.lock_event(self.key, 1))
        self.assertTrue(self.event.get_event(self.key, 1).offline_lock)

    def cleanup_event_export(self, data: CdEDBObject) -> CdEDBObject:
        ret = json_keys_to_int(data)
        for k, v in ret.items():
            if isinstance(v, dict):
                ret[k] = self.cleanup_event_export(v)
            elif isinstance(v, str):
                if k in {"balance", "amount_paid", "amount_owed", "amount"}:
                    ret[k] = decimal.Decimal(v)
                elif k in {"birthday", "payment", "part_begin", "part_end"}:
                    ret[k] = datetime.date.fromisoformat(v)
                elif k in {"ctime", "mtime", "timestamp", "registration_start",
                           "registration_soft_limit", "registration_hard_limit",
                           "etime", "rtime", "atime"}:
                    ret[k] = datetime.datetime.fromisoformat(v)

        return ret

    @storage
    @as_users("annika", "garcia")
    def test_export_event(self) -> None:
        with open(self.testfile_dir / "event_export.json", "r") as f:
            expectation = self.cleanup_event_export(json.load(f))
        expectation['timestamp'] = nearly_now()
        expectation['EVENT_SCHEMA_VERSION'] = tuple(expectation['EVENT_SCHEMA_VERSION'])
        for log_entry in expectation['event.log'].values():
            log_entry['ctime'] = nearly_now()
        for token in expectation[OrgaToken.database_table].values():
            token['ctime'] = nearly_now()
        self.assertEqual(expectation, self.event.export_event(self.key, 1))

    @event_keeper
    @as_users("annika")
    def test_import_event(self) -> None:
        self.assertTrue(self.event.lock_event(self.key, 1))
        data = self.event.export_event(self.key, 1)
        new_data = copy.deepcopy(data)
        stored_data = copy.deepcopy(data)
        # Apply some changes

        # event
        new_data['event.events'][1]['description'] = "We are done!"
        # event parts
        new_data['event.event_parts'][4000] = {
            'event_id': 1,
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
            'id': 4000,
            'part_begin': datetime.date(2345, 1, 1),
            'part_end': datetime.date(2345, 12, 31),
            'title': 'Aftershowparty',
            'shortname': 'Aftershow'}
        # course tracks
        new_data['event.course_tracks'][1100] = {
            'part_id': 4000,
            'id': 1100,
            'title': 'Enlightnment',
            'shortname': 'Enlightnment',
            'num_choices': 3,
            'min_choices': 2,
            'sortkey': 1,
            'course_room_field_id': None}
        # lodgement groups
        new_data['event.lodgement_groups'][5000] = {
            'id': 5000,
            'event_id': 1,
            'title': 'Nebenan',
        }
        # lodgements
        new_data['event.lodgements'][6000] = {
            'regular_capacity': 1,
            'event_id': 1,
            'fields': {},
            'id': 6000,
            'title': 'Matte im Orgabüro',
            'notes': None,
            'group_id': 1,
            'camping_mat_capacity': 0}
        # registration
        new_data['event.registrations'][1000] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good'},
            "list_consent": True,
            'id': 1000,
            'is_member': True,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': True,
            'payment': None,
            'persona_id': 2000,
            'real_persona_id': 3,
            'amount_paid': decimal.Decimal("0.00"),
            'amount_owed': decimal.Decimal("666.66"),
        }
        # registration parts
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
            5009: {
                'id': 5009,
                'lodgement_id': None,
                'part_id': 4000,
                'registration_id': 6,
                'status': const.RegistrationPartStati.not_applied,
            },
        })
        # registration parts
        new_data['event.registration_tracks'][1200] = {
            'course_id': 3000,
            'course_instructor': None,
            'id': 1200,
            'track_id': 1100,
            'registration_id': 1000}
        # orgas
        new_data['event.orgas'][7000] = {
            'event_id': 1, 'id': 7000, 'persona_id': 2000}
        # course
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
        # course parts
        new_data['event.course_segments'][8000] = {
            'course_id': 3000, 'id': 8000, 'track_id': 1100, 'is_active': True}
        # course choices
        # - an update
        new_data['event.course_choices'][27] = {
            'course_id': 5, 'id': 27, 'track_id': 3, 'rank': 0, 'registration_id': 4}
        # - a delete and an insert
        del new_data['event.course_choices'][28]
        new_data['event.course_choices'][9000] = {
            'course_id': 4, 'id': 9000, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        # - an insert
        new_data['event.course_choices'][10000] = {
            'course_id': 3000, 'id': 10000, 'track_id': 1100, 'rank': 0,
            'registration_id': 1000,
        }
        # field definitions
        new_data['event.field_definitions'].update({
            11000: {
                'association': const.FieldAssociations.registration,
                'entries': {
                    'good': 'good',
                    'neutral': 'so so',
                    'bad': 'not good',
                },
                'event_id': 1,
                'field_name': "behaviour",
                'title': "Benehmen",
                'id': 11000,
                'kind': const.FieldDatatypes.str,
                'checkin': False,
            },
            11001: {
                'association': const.FieldAssociations.registration,
                'entries': None,
                'event_id': 1,
                'field_name': "solidarity",
                'title': "Solidarität",
                'id': 11001,
                'kind': const.FieldDatatypes.bool,
                'checkin': False,
            },
        })
        # questionnaire rows
        new_data['event.questionnaire_rows'][12000] = {
            'event_id': 1,
            'field_id': 11000,
            'id': 12000,
            'info': 'Wie brav wirst Du sein',
            'input_size': None,
            'pos': 1,
            'readonly': True,
            'title': 'Vorsätze',
            'kind': const.QuestionnaireUsages.additional,
            'default_value': None,
        }
        new_data['event.event_fees'][13000] = {
            'id': 13000,
            'event_id': 1,
            'kind': const.EventFeeType.common,
            'title': 'Aftershowparty',
            'notes': None,
            'amount': decimal.Decimal("666.66"),
            'condition': "part.Aftershow",
        }
        # This is an invalid stored query, which is just dropped silently on import.
        new_data['event.stored_queries'][10000] = {
            "event_id": 1,
            "id": 1,
            "query_name": "Test-Query",
            "scope": 30,
            "serialized_query": {
                "invalid": True,
                "superfluous_key": None,
            },
        }
        # Note that the changes above are not entirely consistent/complete (as
        # in some stuff is missing and another part may throw an error if we
        # used the resulting data set for real)
        self.assertLess(0, self.event.unlock_import_event(self.key, new_data))
        # Now we have to fix for new stuff
        stored_data['event.events'][1]['offline_lock'] = False
        stored_data['timestamp'] = nearly_now()
        # Apply the same changes as above but this time with (guessed) correct IDs
        stored_data['event.events'][1]['description'] = "We are done!"
        stored_data['event.event_parts'][1001] = {
            'event_id': 1,
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
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
            'title': 'Enlightnment',
            'course_room_field_id': None}
        stored_data['event.lodgement_groups'][1001] = {
            'id': 1001,
            'event_id': 1,
            'title': 'Nebenan',
        }
        stored_data['event.lodgements'][1001] = {
            'regular_capacity': 1,
            'event_id': 1,
            'fields': {},
            'id': 1001,
            'title': 'Matte im Orgabüro',
            'notes': None,
            'group_id': 1,
            'camping_mat_capacity': 0}
        stored_data['event.registrations'][1001] = {
            'checkin': None,
            'event_id': 1,
            'fields': {'lodge': 'Langschläfer',
                       'behaviour': 'good'},
            "list_consent": True,
            'id': 1001,
            'is_member': True,
            'mixed_lodging': True,
            'notes': None,
            'orga_notes': None,
            'parental_agreement': True,
            'payment': None,
            'persona_id': 3,
            'real_persona_id': None,
            'amount_paid': decimal.Decimal("0.00"),
            'amount_owed': decimal.Decimal("666.66"),
        }
        stored_data['event.registrations'][3]['amount_owed'] += decimal.Decimal("0.01")
        stored_data['event.registrations'][5]['amount_owed'] += decimal.Decimal("0.01")
        stored_data['event.registration_parts'].update({
            1001: {
                'id': 1001,
                'is_camping_mat': False,
                'lodgement_id': 1001,
                'part_id': 1001,
                'registration_id': 1001,
                'status': 1,
            },
            1002: {
                'id': 1002,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1003: {
                'id': 1003,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 2,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1004: {
                'id': 1004,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 3,
                'registration_id': 1001,
                'status': const.RegistrationPartStati.not_applied,
            },
            1005: {
                'id': 1005,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 1,
                'status': const.RegistrationPartStati.not_applied,
            },
            1006: {
                'id': 1006,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 2,
                'status': const.RegistrationPartStati.not_applied,
            },
            1007: {
                'id': 1007,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 3,
                'status': const.RegistrationPartStati.not_applied,
            },
            1008: {
                'id': 1008,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 4,
                'status': const.RegistrationPartStati.not_applied,
            },
            1009: {
                'id': 1009,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 5,
                'status': const.RegistrationPartStati.not_applied,
            },
            1010: {
                'id': 1010,
                'is_camping_mat': False,
                'lodgement_id': None,
                'part_id': 1001,
                'registration_id': 6,
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
            'event_id': 1, 'id': 1001, 'persona_id': 3}
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
            'course_id': 1001, 'id': 1002, 'track_id': 1001, 'rank': 0,
            'registration_id': 1001,
        }
        stored_data['event.course_choices'][1001] = {
            'course_id': 4, 'id': 1001, 'track_id': 3, 'rank': 1, 'registration_id': 4}
        stored_data['event.field_definitions'].update({
            1001: {
                'association': const.FieldAssociations.registration,
                'entries': [['good', 'good'],
                            ['neutral', 'so so'],
                            ['bad', 'not good']],
                'event_id': 1,
                'field_name': "behaviour",
                'title': "Benehmen",
                'sortkey': 0,
                'id': 1001,
                'kind': const.FieldDatatypes.str,
                'checkin': False,
            },
            1002: {
                'association': const.FieldAssociations.registration,
                'entries': None,
                'event_id': 1,
                'field_name': "solidarity",
                'title': "Solidarität",
                'sortkey': 0,
                'id': 1002,
                'kind': const.FieldDatatypes.bool,
                'checkin': False,
            },
        })
        stored_data['event.event_fees'][1001] = {
            'id': 1001,
            'event_id': 1,
            'kind': const.EventFeeType.common,
            'title': 'Aftershowparty',
            'notes': None,
            'amount': decimal.Decimal("666.66"),
            'condition': "part.Aftershow",
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
            'kind': const.QuestionnaireUsages.additional,
            'default_value': None,
        }
        # stored_data['event.stored_queries'][10000]
        # is already deleted due to the import deleting invalid queries

        result = self.event.export_event(self.key, 1)
        # because it's irrelevant anyway simply paste the result
        stored_data['core.personas'] = result['core.personas']
        # add log message
        stored_data['event.log'][1002] = {
            'change_note': None,
            'code': 61,
            'ctime': nearly_now(),
            'event_id': 1,
            'id': 1002,
            'persona_id': None,
            'submitted_by': self.user['id']}

        self.assertEqual(stored_data, result)

    @storage
    @as_users("annika")
    def test_partial_export_event(self) -> None:
        with open(self.testfile_dir / "TestAka_partial_export_event.json") as f:
            expectation = self.cleanup_event_export(json.load(f))
        expectation['timestamp'] = nearly_now()
        for reg in expectation['registrations'].values():
            reg['ctime'] = nearly_now()
            reg['mtime'] = None
            for fee_id, amount in reg['personalized_fees'].items():
                reg['personalized_fees'][fee_id] = decimal.Decimal(amount)
        for token in expectation['event']['orga_tokens'].values():
            token['ctime'] = nearly_now()
        expectation['EVENT_SCHEMA_VERSION'] = tuple(expectation['EVENT_SCHEMA_VERSION'])
        export = self.event.partial_export_event(self.key, 1)
        self.assertEqual(expectation, export)

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_event(self) -> None:
        event = self.event.get_event(self.key, 1)
        previous = self.event.partial_export_event(self.key, 1)
        with open(self.testfile_dir / "partial_event_import.json") as datafile:
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

        cmap = {
            ('courses', -1): 1002,
            ('lodgement_groups', -1): 1002,
            ('lodgements', -1): 1003,
            ('lodgements', -2): 1004,
            ('registrations', -1): 1002,
        }
        tmap: dict[str, dict[str, dict[Any, Any]]] = {
            'courses': {'segments': {}, 'fields': {}},
            'lodgement_groups': {},
            'lodgements': {'fields': {}},
            'registrations': {'parts': {}, 'tracks': {}, 'fields': {}},
        }

        def recursive_update(old: Dict[Any, Any], new: Dict[Any, Any],
                             hint: Optional[str] = None) -> None:
            """Helper function to replace some placeholder values inside of a dict."""
            if hint == 'fields':
                new = cast_fields(new, event.fields)
            deletions = [key for key, val in new.items()
                         if val is None and key in old]
            for key in deletions:
                if isinstance(old[key], collections.abc.Mapping) or hint == 'segments':
                    del old[key]
                    del new[key]
            recursions = [key for key, val in new.items()
                          if isinstance(val, collections.abc.Mapping)]
            for key in recursions:
                temp = new.pop(key)
                if isinstance(key, int) and key < 0:
                    assert hint is not None
                    new_key = cmap[(hint, key)]
                    old[new_key] = copy.deepcopy(tmap[hint])
                else:
                    new_key = key
                if new_key not in old:
                    old[new_key] = {}
                recursive_update(old[new_key], temp, new_key)  # type: ignore[arg-type]
            for key in ('persona_id', 'real_persona_id'):
                if key in new:
                    del new[key]
            for key in ('payment',):
                # coverage: Setting payment via partial import is disallowed.
                if new.get(key):  # pragma: no cover
                    try:
                        new[key] = datetime.date.fromisoformat(new[key])
                    except AttributeError:
                        del new[key]
                        if key in old:
                            del old[key]
            for key in ('course_id', 'course_instructor', 'choices'):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = cmap.get(('courses', new[key]), new[key])
                    elif isinstance(new[key], collections.abc.Sequence):
                        new[key] = [cmap.get(('courses', anid), anid)
                                    for anid in new[key]]
            for key in ('lodgement_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = cmap.get(('lodgements', new[key]), new[key])
            for key in ('group_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = cmap.get(
                            ('lodgement_groups', new[key]), new[key])
            for key in ('status',):
                if key in new:
                    new[key] = const.RegistrationPartStati(new[key])
            old.update(new)

        recursive_update(expectation, delta)
        del expectation['summary']
        del expectation['timestamp']
        del updated['timestamp']
        del updated['registrations'][1002]['persona']  # ignore additional info
        expectation['registrations'][1]['mtime'] = nearly_now()
        # amount_owed is recalculated
        expectation['registrations'][2]['amount_owed'] = decimal.Decimal("589.48")
        expectation['registrations'][2]['mtime'] = nearly_now()
        expectation['registrations'][3]['mtime'] = nearly_now()
        expectation['registrations'][3]['amount_owed'] = decimal.Decimal("489.48")
        expectation['registrations'][3]['personalized_fees'][10] = decimal.Decimal(
            expectation['registrations'][3]['personalized_fees'][10],
        )
        # add default values
        expectation['registrations'][1002]['amount_paid'] = decimal.Decimal('0.00')
        expectation['registrations'][1002]['payment'] = None
        expectation['registrations'][1002]['amount_owed'] = decimal.Decimal("573.99")
        expectation['registrations'][1002]['is_member'] = True
        expectation['registrations'][1002]['ctime'] = nearly_now()
        expectation['registrations'][1002]['mtime'] = None
        expectation['registrations'][1002]['personalized_fees'] = {}
        expectation['EVENT_SCHEMA_VERSION'] = tuple(
            expectation['EVENT_SCHEMA_VERSION'])
        self.assertEqual(expectation, updated)

        # Test logging
        log_expectation: list[CdEDBObject] = [
            {
                'change_note': 'Geheime Etage',
                'code': const.EventLogCodes.lodgement_group_created,
            },
            {
                'change_note': 'Warme Stube',
                'code': const.EventLogCodes.lodgement_changed,
            },
            {
                'change_note': 'Kalte Kammer',
                'code': const.EventLogCodes.lodgement_changed,
            },
            {
                'change_note': 'Kellerverlies',
                'code': const.EventLogCodes.lodgement_deleted,
            },
            {
                'change_note': 'Einzelzelle',
                'code': const.EventLogCodes.lodgement_changed,
            },
            {
                'change_note': 'Geheimkabinett',
                'code': const.EventLogCodes.lodgement_created,
            },
            {
                'change_note': 'Handtuchraum',
                'code': const.EventLogCodes.lodgement_created,
            },
            {
                'change_note': 'Planetenretten für Anfänger',
                'code': const.EventLogCodes.course_changed,
            },
            {
                'change_note': 'Planetenretten für Anfänger',
                'code': const.EventLogCodes.course_segments_changed,
            },
            {
                'change_note': 'Planetenretten für Anfänger',
                'code': const.EventLogCodes.course_segment_activity_changed,
            },
            {
                'change_note': 'Lustigsein für Fortgeschrittene',
                'code': const.EventLogCodes.course_changed,
            },
            {
                'change_note': 'Kurzer Kurs',
                'code': const.EventLogCodes.course_deleted,
            },
            {
                'change_note': 'Langer Kurs',
                'code': const.EventLogCodes.course_segments_changed,
            },
            {
                'change_note': 'Backup-Kurs',
                'code': const.EventLogCodes.course_segment_activity_changed,
            },
            {
                'change_note': 'Blitzkurs',
                'code': const.EventLogCodes.course_created,
            },
            {
                'change_note': 'Blitzkurs',
                'code': const.EventLogCodes.course_segments_changed,
            },
            {
                'change_note': 'Blitzkurs',
                'code': const.EventLogCodes.course_segment_activity_changed,
            },
            {
                'change_note': 'Partieller Import: Sehr wichtiger Import',
                'code': const.EventLogCodes.registration_changed,
                'persona_id': 1,
            },
            {
                'change_note': '1.H.: Gast -> Teilnehmer',
                'code': const.EventLogCodes.registration_status_changed,
                'persona_id': 5,
            },
            {
                'change_note': 'Partieller Import: Sehr wichtiger Import',
                'code': const.EventLogCodes.registration_changed,
                'persona_id': 5,
            },
            {
                'change_note': '1.H.: Teilnehmer -> Warteliste',
                'code': const.EventLogCodes.registration_status_changed,
                'persona_id': 7,
            },
            {
                'change_note': 'Partieller Import: Sehr wichtiger Import',
                'code': const.EventLogCodes.registration_changed,
                'persona_id': 7,
            },
            {
                'change_note': 'KL-Erstattung (-45,00 €)',
                'code': const.EventLogCodes.personalized_fee_amount_set,
                'persona_id': 7,
            },
            {
                'code': const.EventLogCodes.registration_deleted,
                'persona_id': 9,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'persona_id': 3,
            },
            {
                'change_note': 'Sehr wichtiger Import',
                'code': const.EventLogCodes.event_partial_import,
            },
        ]
        self.assertLogEqual(log_expectation, event_id=1, realm="event", offset=6)

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_integrity(self) -> None:
        with open(self.testfile_dir / "partial_event_import.json") as datafile:
            orig_data = json.load(datafile)

        base_data = {
            k: orig_data[k] for k in ("id", "EVENT_SCHEMA_VERSION",
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

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_event_twice(self) -> None:
        with open(self.testfile_dir / "partial_event_import.json") as datafile:
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
            'courses': {
                -1: {
                    'description': 'Ein Lichtstrahl traf uns',
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
                4: {
                    'segments': {1: None},
                },
            },
            'lodgement_groups': {
                -1: {'title': 'Geheime Etage'},
            },
            'lodgements': {
                -1: {'regular_capacity': 12,
                     'fields': {'contamination': 'none'},
                     'title': 'Geheimkabinett',
                     'notes': 'Einfach den unsichtbaren Schildern folgen.',
                     'group_id': -1,
                     'camping_mat_capacity': 2,
                     },
                -2: {'regular_capacity': 42,
                     'fields': {'contamination': 'low'},
                     'title': 'Handtuchraum',
                     'notes': 'Hier gibt es Handtücher für jeden.',
                     'group_id': 2,
                     'camping_mat_capacity': 0,
                     },
                3: None,
                4: {'group_id': -1},
            },
            'registrations': {
                3: {
                    'tracks': {
                        3: {
                            'course_id': -1,
                            'choices': [4, -1, 5]}}},
                4: None,
                1001: {
                    'parts': {
                        2: {'lodgement_id': -1},
                    },
                    'tracks': {
                        3: {
                            'choices': [1, 4, 5, -1],
                            'course_id': -1,
                            'course_instructor': -1,
                        },
                    },
                },
            },
        }
        self.assertEqual(expectation, delta)

    @as_users("annika", "garcia")
    def test_check_registration_status(self) -> None:
        event_id = 1

        # Check for participant status
        stati = [const.RegistrationPartStati.participant]
        self.assertTrue(
            self.event.check_registration_status(self.key, 1, event_id, stati))
        self.assertFalse(
            self.event.check_registration_status(self.key, 3, event_id, stati))
        self.assertTrue(
            self.event.check_registration_status(self.key, 5, event_id, stati))
        self.assertTrue(
            self.event.check_registration_status(self.key, 9, event_id, stati))

        # Check for waitlist status
        stati = [const.RegistrationPartStati.waitlist]
        self.assertFalse(
            self.event.check_registration_status(self.key, 1, event_id, stati))
        self.assertTrue(
            self.event.check_registration_status(self.key, 5, event_id, stati))
        self.assertFalse(
            self.event.check_registration_status(self.key, 9, event_id, stati))

    @as_users("emilia", "garcia", "annika")
    def test_calculate_fees(self) -> None:
        if not self.user_in("emilia"):
            reg_ids = self.event.list_registrations(self.key, event_id=1)
            expectation = {
                1: decimal.Decimal("553.99"),
                2: decimal.Decimal("466.49"),
                3: decimal.Decimal("504.48"),
                4: decimal.Decimal("431.99"),
                5: decimal.Decimal("584.48"),
                6: decimal.Decimal("10.50"),
            }
            self.assertEqual(expectation, self.event.calculate_fees(self.key, reg_ids))
        reg_id = 2
        reg = self.event.get_registration(self.key, reg_id)
        self.assertEqual(reg['amount_owed'], decimal.Decimal("466.49"))
        self.assertEqual(
            const.RegistrationPartStati.waitlist, reg['parts'][1]['status'])
        self.assertEqual(
            const.RegistrationPartStati.guest, reg['parts'][2]['status'])
        self.assertEqual(
            const.RegistrationPartStati.participant,
            reg['parts'][3]['status'])
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

    @as_users("berta")
    def test_uniqueness(self) -> None:
        event_id = 2
        unique_name = 'unique_name'
        data = {
            'fields': {
                -1: {
                    'association': const.FieldAssociations.registration,
                    'field_name': unique_name,
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, data)
        # TODO throw an actual backend error here.
        with self.assertRaises(psycopg2.IntegrityError):
            self.event.set_event(self.key, event_id, data)
        data = {
            'fields': {
                -1: {
                    'association': const.FieldAssociations.registration,
                    'field_name': unique_name + "2",
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, data)

    @as_users("annika")
    @unittest.skip("Removed feature.")
    def test_fee_modifiers(self) -> None:
        event_id = 2
        event = self.event.get_event(self.key, event_id)
        field_data = {
            'fields': {
                -1: {
                    'association': const.FieldAssociations.registration,
                    'field_name': 'solidarity',
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                },
                -2: {
                    'association': const.FieldAssociations.registration,
                    'field_name': 'solidarity_int',
                    'kind': const.FieldDatatypes.int,
                    'entries': None,
                },
                -3: {
                    'association': const.FieldAssociations.course,
                    'field_name': 'solidarity_course',
                    'kind': const.FieldDatatypes.bool,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, field_data)
        field_links = (
            (1001, None, None),
            (1001, psycopg2.IntegrityError, None),
            (1002, ValueError, "Unfit field for fee_modifier."),
            (1003, ValueError, "Unfit field for fee_modifier."),
        )
        for field_id, error, error_msg in field_links:
            data = {
                'parts': {
                    list(event.parts)[0]: {
                        'fee_modifiers': {
                            -1: {
                                'modifier_name': 'solidarity',
                                'amount': decimal.Decimal("-12.50"),
                                'field_id': field_id,
                            },
                        },
                    },
                },
            }
            if error:
                with self.assertRaises(error) as cm:
                    self.event.set_event(self.key, event_id, data)
                if error_msg is not None:
                    self.assertEqual(error_msg,
                                     cm.exception.args[0] % cm.exception.args[1])
            else:
                self.assertTrue(self.event.set_event(self.key, event_id, data))
        reg_data = {
            "persona_id": 1,
            "event_id": event_id,
            "parts": {
                4: {
                    "status": const.RegistrationPartStati.applied,
                },
            },
            "tracks": {

            },
            "mixed_lodging": True,
            "list_consent": True,
            "notes": None,
        }
        reg_id = self.event.create_registration(self.key, reg_data)
        self.assertEqual(self.event.calculate_fee(self.key, reg_id),
                         decimal.Decimal("15"))
        reg_data = {
            'id': reg_id,
            'fields': {
                'solidarity': True,
            },
        }
        self.assertTrue(self.event.set_registration(self.key, reg_data))
        self.assertEqual(self.event.calculate_fee(self.key, reg_id),
                         decimal.Decimal("2.50"))

    @as_users("garcia")
    def test_waitlist(self) -> None:
        event_id = 1
        edata = {
            'fields': {
                -1: {
                    'field_name': "waitlist",
                    'association': const.FieldAssociations.registration,
                    'kind': const.FieldDatatypes.int,
                    'entries': None,
                },
            },
        }
        self.event.set_event(self.key, event_id, edata)
        edata = {
            'parts': {
                1: {
                    'waitlist_field_id': 1001,
                },

                2: {
                    'waitlist_field_id': 1001,
                },

                3: {
                    'waitlist_field_id': 1001,
                },
            },
        }
        self.event.set_event(self.key, event_id, edata)
        regs = [
            {
                'id': anid,
                'parts': {
                    1: {
                        'status': const.RegistrationPartStati.waitlist,
                    },
                    2: {
                        'status': (const.RegistrationPartStati.waitlist
                                   if anid in {2, 3}
                                   else const.RegistrationPartStati.participant),
                    },
                    3: {
                        'status': (const.RegistrationPartStati.waitlist
                                   if anid in {2, 3}
                                   else const.RegistrationPartStati.participant),
                    },
                },
                'fields': {
                    'waitlist': i+1,
                },
            }
            for i, anid in enumerate((5, 4, 3, 2, 1))
        ]
        for rdata in regs:
            self.event.set_registration(self.key, rdata)
        # Registration 3 belongs to Garcia (persona_id 7).
        expectation = {1: [5, 4, 3, 2, 1], 2: [3, 2], 3: [3, 2]}
        self.assertEqual(expectation, self.event.get_waitlist(self.key, event_id=1))
        self.assertEqual({1: 3, 2: 1, 3: 1},
                         self.event.get_waitlist_position(self.key, event_id=1))
        # Registration 2 belongs to Emilia (persona_id 5).
        self.assertEqual({1: 4, 2: 2, 3: 2},
                         self.event.get_waitlist_position(
                             self.key, event_id=1, persona_id=5))
        # Unset waitlist field data.
        reg_id = 4
        reg_data = {
            'id': reg_id,
            'fields': {
                'waitlist': None,
            },
        }
        self.event.set_registration(self.key, reg_data)
        # The altered registration will be placed last in the waitlist, because
        # it defaults to 2**31.
        for waitlist in expectation.values():
            if reg_id in waitlist:
                waitlist.remove(reg_id)
                waitlist.append(reg_id)
        self.assertEqual(expectation, self.event.get_waitlist(self.key, event_id=1))

        # Check that users can check their own waitlist position.
        self.login(USER_DICT["emilia"])
        self.assertEqual({1: 3, 2: 2, 3: 2},
                         self.event.get_waitlist_position(self.key, event_id=1))
        with self.assertRaises(PrivilegeError):
            self.event.get_waitlist_position(
                self.key, event_id=1, persona_id=1)

    @as_users("annika")
    def test_set_event_orgas(self) -> None:
        event_id = 1
        self.assertEqual({7}, self.event.get_event(self.key, event_id).orgas)
        self.assertLess(0, self.event.add_event_orgas(self.key, event_id, {1}))
        self.assertEqual({1, 7}, self.event.get_event(self.key, event_id).orgas)
        self.assertLess(
            0, self.event.remove_event_orga(self.key, event_id, 1))
        self.assertLess(
            0, self.event.add_event_orgas(self.key, event_id, {1}))
        self.assertEqual({1, 7}, self.event.get_event(self.key, event_id).orgas)

        with self.assertRaises(ValueError) as cm:
            self.event.add_event_orgas(self.key, event_id, {8})
        self.assertIn("Some of these orgas do not exist or are archived.",
                      cm.exception.args)
        with self.assertRaises(ValueError) as cm:
            self.event.add_event_orgas(self.key, event_id, {1000})
        self.assertIn("Some of these orgas do not exist or are archived.",
                      cm.exception.args)
        with self.assertRaises(ValueError) as cm:
            self.event.add_event_orgas(self.key, event_id, {11})
        self.assertIn("Some of these orgas are not event users.",
                      cm.exception.args)

    @event_keeper
    @as_users("annika")
    def test_log(self) -> None:
        # first check the already existing log
        offset = 6
        expectation = (
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 1,
                'submitted_by': 1,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 5,
                'submitted_by': 5,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 7,
                'submitted_by': 7,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 9,
                'submitted_by': 9,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 100,
                'submitted_by': 100,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 2,
                'submitted_by': 2,
            },
        )

        self.assertLogEqual(expectation, realm="event")

        # then generate some data
        data: CdEDBObject = {
            'title': "New Link Academy",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'shortname': 'link',
            'registration_start': datetime.datetime(2000, 11, 22, 0, 0, 0,
                                                    tzinfo=datetime.timezone.utc),
            'registration_soft_limit': datetime.datetime(2022, 1, 2, 0, 0, 0,
                                                         tzinfo=datetime.timezone.utc),
            'registration_hard_limit': None,
            'iban': None,
            'registration_text': None,
            'mail_text': None,
            'use_additional_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {
                        -1: {'title': "First lecture",
                             'shortname': "First",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1,
                             'course_room_field_id': None}},
                    'title': "First coming",
                    'shortname': "First",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
                -2: {
                    'tracks': {
                        -1: {'title': "Second lecture",
                             'shortname': "Second",
                             'num_choices': 3,
                             'min_choices': 3,
                             'sortkey': 1,
                             'course_room_field_id': None}},
                    'title': "Second coming",
                    'shortname': "Second",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
            },
            'fields': {
                -1: {
                    'association': 1,
                    'field_name': "instrument",
                    'kind': 1,
                    'entries': None,
                    'checkin': False,
                },
                -2: {
                    'association': 1,
                    'field_name': "preferred_excursion_date",
                    'kind': 5,
                    'entries': [["2109-8-16", "In the first coming"],
                                ["2110-8-16", "During the second coming"]],
                    'checkin': True,
                },
            },
            'lodgement_groups': {
                -1: {
                    'title': "Draußen",
                },
                -2: {
                    'title': "Drinnen",
                },
            },
        }
        new_id = self.event.create_event(self.key, data)
        # correct part and field ids
        tmp = self.event.get_event(self.key, new_id)
        part_map = {}
        for part in tmp.parts:
            for oldpart in data['parts']:
                if tmp.parts[part].title == data['parts'][oldpart]['title']:
                    part_map[tmp.parts[part].title] = part
                    data['parts'][part] = data['parts'][oldpart]
                    data['parts'][part]['id'] = part
                    data['parts'][part]['event_id'] = new_id
                    del data['parts'][oldpart]
                    break
        field_map: dict[str, int] = {}
        for field in tmp.fields:
            for oldfield in data['fields']:
                if (tmp.fields[field].field_name
                        == data['fields'][oldfield]['field_name']):
                    field_map[tmp.fields[field].field_name] = field
                    data['fields'][field] = data['fields'][oldfield]
                    data['fields'][field]['id'] = field
                    data['fields'][field]['event_id'] = new_id
                    del data['fields'][oldfield]
                    break

        data['title'] = "Alternate Universe Academy"
        newpart = {
            'tracks': {
                -1: {'title': "Third lecture",
                     'shortname': "Third",
                     'num_choices': 2,
                     'min_choices': 2,
                     'sortkey': 2,
                     'course_room_field_id': None}},
            'title': "Third coming",
            'shortname': "Third",
            'part_begin': datetime.date(2111, 8, 7),
            'part_end': datetime.date(2111, 8, 20),
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
        }
        changed_part = {
            'title': "Second coming",
            'part_begin': datetime.date(2110, 9, 8),
            'part_end': datetime.date(2110, 9, 21),
            'tracks': {
                1002: {
                    'title': "Second lecture v2",  # hardcoded id 5
                    'shortname': "Second v2",
                    'num_choices': 5,
                    'min_choices': 4,
                    'sortkey': 3,
                },
            },
        }
        newfield = {
            'association': const.FieldAssociations.registration,
            'field_name': "kuea",
            'kind': const.FieldDatatypes.date,
            'entries': None,
            'checkin': False,
        }
        changed_field = {
            'association': const.FieldAssociations.registration,
            'kind': const.FieldDatatypes.date,
            'entries': [
                ["2110-8-15", "early second coming"],
                ["2110-8-17", "late second coming"],
            ],
            'checkin': True,
        }
        self.event.add_event_orgas(self.key, new_id, {2, 1})
        self.event.remove_event_orga(self.key, new_id, 2)
        self.event.set_event(self.key, new_id, {
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
                1: {
                    'lodgement_id': None,
                    'status': 1,
                },
                2: {
                    'lodgement_id': None,
                    'status': 1,
                },
                3: {
                    'lodgement_id': None,
                    'status': 1,
                },
            },
            'tracks': {
                1: {
                    'choices': {1: [1, 4, 5]},
                    'course_id': None,
                    'course_instructor': None,
                },
                2: {
                    'course_id': None,
                    'course_instructor': None,
                },
                3: {
                    'course_id': None,
                    'course_instructor': None,
                },
            },
            'notes': "Some bla.",
            'persona_id': 3,
            'real_persona_id': None}
        new_id = self.event.create_registration(self.key, new_reg)
        data = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
            'checkin': datetime.datetime.now(datetime.timezone.utc),
            'parts': {
                1: {
                    'status': 2,
                    'lodgement_id': 2,
                },
                3: {
                    'status': 6,
                    'lodgement_id': None,
                },
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
                },
            },
        }
        self.event.set_registration(self.key, data, change_note="Boring change.")
        new = {
            'regular_capacity': 42,
            'event_id': 1,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': 1,
        }
        new_id = self.event.create_lodgement(self.key, new)
        update = {
            'regular_capacity': 21,
            'notes': None,
            'id': new_id,
        }
        self.event.set_lodgement(self.key, update)
        self.event.delete_lodgement(self.key, new_id)
        data: Dict[const.QuestionnaireUsages, List[CdEDBObject]] = {
            const.QuestionnaireUsages.additional:
                [
                    {'field_id': None,
                     'default_value': None,
                     'info': None,
                     'readonly': None,
                     'input_size': None,
                     'title': 'Weitere bla Überschrift',
                     'kind': const.QuestionnaireUsages.additional,
                     },
                    {'field_id': 2,
                     'default_value': 'etc',
                     'info': None,
                     'readonly': True,
                     'input_size': None,
                     'title': 'Vehikel',
                     'kind': const.QuestionnaireUsages.additional,
                     },
                    {'field_id': None,
                     'default_value': None,
                     'info': 'mit Text darunter und so',
                     'readonly': None,
                     'input_size': None,
                     'title': 'Unterüberschrift',
                     'kind': const.QuestionnaireUsages.additional,
                     },
                    {'field_id': 3,
                     'default_value': None,
                     'info': None,
                     'readonly': True,
                     'input_size': 5,
                     'title': 'Vehikel',
                     'kind': const.QuestionnaireUsages.additional,
                     },
                    {'field_id': None,
                     'default_value': None,
                     'info': 'nur etwas mehr Text',
                     'readonly': None,
                     'input_size': None,
                     'title': None,
                     'kind': const.QuestionnaireUsages.additional,
                     },
                ],
        }
        self.event.set_questionnaire(self.key, 1, data)

        # now check it
        expectation = (
            {
                'code': const.EventLogCodes.event_created,
                'event_id': 1001,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'event_id': 1001,
                'persona_id': 2,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'event_id': 1001,
                'persona_id': 7,
            },
            {
                'change_note': 'instrument',
                'code': const.EventLogCodes.field_added,
                'event_id': 1001,
            },
            {
                'change_note': 'preferred_excursion_date',
                'code': const.EventLogCodes.field_added,
                'event_id': 1001,
            },
            {
                'change_note': 'First coming',
                'code': const.EventLogCodes.part_created,
                'event_id': 1001,
            },
            {
                'change_note': 'First lecture',
                'code': const.EventLogCodes.track_added,
                'event_id': 1001,
            },
            {
                'change_note': 'Second coming',
                'code': const.EventLogCodes.part_created,
                'event_id': 1001,
            },
            {
                'change_note': 'Second lecture',
                'code': const.EventLogCodes.track_added,
                'event_id': 1001,
            },
            {
                'change_note': "Draußen",
                'code': const.EventLogCodes.lodgement_group_created,
                'event_id': 1001,
            },
            {
                'change_note': "Drinnen",
                'code': const.EventLogCodes.lodgement_group_created,
                'event_id': 1001,
            },
            {
                'code': const.EventLogCodes.orga_added,
                'event_id': 1001,
                'persona_id': 1,
            },
            {
                'code': const.EventLogCodes.orga_removed,
                'event_id': 1001,
                'persona_id': 2,
            },
            {
                'code': const.EventLogCodes.event_changed,
                'event_id': 1001,
            },
            {
                'change_note': 'instrument',
                'code': const.EventLogCodes.field_removed,
                'event_id': 1001,
            },
            {
                'change_note': 'kuea',
                'code': const.EventLogCodes.field_added,
                'event_id': 1001,
            },
            {
                'change_note': 'preferred_excursion_date',
                'code': const.EventLogCodes.field_updated,
                'event_id': 1001,
            },
            {
                'change_note': 'Third coming',
                'code': const.EventLogCodes.part_created,
                'event_id': 1001,
            },
            {
                'change_note': 'Third lecture',
                'code': const.EventLogCodes.track_added,
                'event_id': 1001,
            },
            {
                'change_note': 'Second coming',
                'code': const.EventLogCodes.part_changed,
                'event_id': 1001,
            },
            {
                'change_note': 'Second lecture v2',
                'code': const.EventLogCodes.track_updated,
                'event_id': 1001,
            },
            {
                'change_note': 'First lecture',
                'code': const.EventLogCodes.track_removed,
                'event_id': 1001,
            },
            {
                'change_note': 'First coming',
                'code': const.EventLogCodes.part_deleted,
                'event_id': 1001,
            },
            {
                'change_note': 'Topos theory for the kindergarden',
                'code': const.EventLogCodes.course_created,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden',
                'code': const.EventLogCodes.course_segments_changed,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden',
                'code': const.EventLogCodes.course_changed,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden',
                'code': const.EventLogCodes.course_segments_changed,
                'event_id': 1,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 3,
            },
            {
                'change_note': "Wu: Abgelehnt -> Teilnehmer",
                'code': const.EventLogCodes.registration_status_changed,
                'event_id': 1,
                'persona_id': 9,
            },
            {
                'change_note': "2.H.: Teilnehmer -> Abgelehnt",
                'code': const.EventLogCodes.registration_status_changed,
                'event_id': 1,
                'persona_id': 9,
            },
            {
                'change_note': "Boring change.",
                'code': const.EventLogCodes.registration_changed,
                'event_id': 1,
                'persona_id': 9,
            },
            {
                'change_note': 'HY',
                'code': const.EventLogCodes.lodgement_created,
                'event_id': 1,
            },
            {
                'change_note': 'HY',
                'code': const.EventLogCodes.lodgement_changed,
                'event_id': 1,
            },
            {
                'change_note': 'HY',
                'code': const.EventLogCodes.lodgement_deleted,
                'event_id': 1,
            },
            {
                'code': const.EventLogCodes.questionnaire_changed,
                'event_id': 1,
            },
        )

        self.assertLogEqual(expectation, realm="event", offset=offset)

    def _create_registration(self, persona_id: int, event_id: int) -> int:
        event = self.event.get_event(self.key, event_id)
        return self.event.create_registration(self.key, {
            'persona_id': persona_id,
            'event_id': event.id,
            'mixed_lodging': True,
            'list_consent': True,
            'notes': None,
            'parts': {
                p_id: {'status': const.RegistrationPartStati.applied}
                for p_id in event.parts
            },
            'tracks': {
                t_id: {}
                for p_id in event.parts for t_id in event.parts[p_id].tracks
            },
        })

    @as_users("annika")
    def test_registration_timestamps(self) -> None:
        persona_id = self.user['id']
        event_ids = [1, 2]
        reg_ids = {}
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            for event_id in event_ids:
                reg_id = self._create_registration(persona_id, event_id)
                frozen_time.tick(delta)
                self.event.set_registration(
                    self.key, {'id': reg_id, 'notes': "Important change!"})
                frozen_time.tick(delta)
                reg_ids[event_id] = reg_id
            for i, (event_id, reg_id) in enumerate(reg_ids.items()):
                reg = self.event.get_registration(self.key, reg_id)
                self.assertEqual(reg['ctime'], base_time + 2 * i * delta)
                self.assertEqual(reg['mtime'], base_time + (2 * i + 1) * delta)

    @as_users("emilia")
    def test_part_groups(self) -> None:
        event_id = 4
        event = self.event.get_event(self.key, event_id)

        # Delete existing registrations so we are free to create and delete event parts.
        registration_ids = self.event.list_registrations(self.key, event_id)
        for reg_id in registration_ids:
            self.event.delete_registration(
                self.key, reg_id, cascade=("registration_parts", "registration_tracks"))

        # Load expected sample part groups.
        part_group_parts_data = self.get_sample_data("event.part_group_parts")
        part_group_expectation = {
            part_group_id: part_group
            for part_group_id, part_group
            in self.get_sample_data("event.part_groups").items()
            if part_group['event_id'] == event_id
        }
        # Add dynamic data and convert enum.
        for part_group in part_group_expectation.values():
            part_group['part_ids'] = {
                e['part_id'] for e in part_group_parts_data.values()
                if e['part_group_id'] == part_group['id']
            }
            part_group['constraint_type'] = const.EventPartGroupType(
                part_group['constraint_type'])
        # Compare to retrieved data.
        reality = event.as_dict()['part_groups']
        for pg in reality.values():
            pg['part_ids'] = set(pg.pop('parts'))
        self.assertEqual(
            part_group_expectation,
            reality,
        )

        # Check setting of part groups.

        new_part_group = {
            'title': "Everything",
            'shortname': "all",
            'notes': "Let's see what happens",
            'part_ids': set(event.parts),
            'constraint_type': const.EventPartGroupType.Statistic,
        }

        # Setting is not allowed for non-privileged users.
        with self.assertRaises(PrivilegeError):
            self.event.set_part_groups(ANONYMOUS, event_id, {})
        with self.switch_user("garcia"):
            with self.assertRaises(PrivilegeError):
                self.event.set_part_groups(self.key, event_id, {})

        # Empty setter just returns 1.
        self.assertEqual(self.event.set_part_groups(self.key, event_id, {}), 1)

        new_part_group_id = self.event.set_part_groups(
            self.key, event_id, {-1: new_part_group})
        self.assertTrue(new_part_group_id)

        with self.assertRaises(UNIQUE_VIOLATION):
            self.event.set_part_groups(self.key, event_id, {-1: new_part_group})

        data = new_part_group.copy()
        data['shortname'] = "ALL"
        with self.assertRaises(UNIQUE_VIOLATION):
            self.event.set_part_groups(self.key, event_id, {-1: data})

        data = new_part_group.copy()
        data['title'] = "All"
        with self.assertRaises(UNIQUE_VIOLATION):
            self.event.set_part_groups(self.key, event_id, {-1: data})

        data = new_part_group.copy()
        data['shortname'] = "ALL"
        data['title'] = "All"
        self.event.set_part_groups(self.key, event_id, {-1: data})  # id 1005

        # Simultaneous deletion and recreation of part group with same name works.
        self.event.set_part_groups(
            self.key, event_id, {1001: None, -1: new_part_group},  # id 1006
        )

        # Switching of shortnames for exisitng groups is also possible.
        setter = {
            1005: {'shortname': new_part_group['shortname']},
            1006: {'shortname': data['shortname']},
        }
        self.assertTrue(self.event.set_part_groups(self.key, event_id, setter))  # type: ignore[arg-type]
        part_group_expectation.update({
            1005: {**data, **setter[1005], **{'event_id': event_id, 'id': 1005}},
            1006: {**new_part_group, **setter[1006],
                   **{'event_id': event_id, 'id': 1006}},
        })

        # Update and delete an existing group.
        update = {
            1: {
                'notes': "Pack explosives for New Years!",
            },
            4: None,
            1006: {
                'part_ids': set(list(event.parts)[:len(event.parts) // 2]),
            },
        }
        self.assertTrue(self.event.set_part_groups(self.key, event_id, update))
        part_group_expectation[1].update(update[1])  # type: ignore[arg-type]
        del part_group_expectation[4]
        part_group_expectation[1006].update(update[1006])  # type: ignore[arg-type]

        reality = self.event.get_event(self.key, event_id).as_dict()['part_groups']
        for pg in reality.values():
            pg['part_ids'] = set(pg.pop('parts'))
        self.assertEqual(
            part_group_expectation,
            reality,
        )

        # ValueError is raised when trying to update or delete a nonexisting part group.
        with self.assertRaises(ValueError):
            self.event.set_part_groups(self.key, event_id, {NON_EXISTING_ID: None})
        # ValueError when creating or updating a part group with a non existing part.
        with self.assertRaises(ValueError):
            self.event.set_part_groups(
                self.key, event_id,
                {-1: {**new_part_group, **{'part_ids': [NON_EXISTING_ID]}}})
        with self.assertRaises(ValueError):
            self.event.set_part_groups(
                self.key, event_id, {1: {'part_ids': [NON_EXISTING_ID]}})

        # Delete a part still linked to a part group.
        self.assertTrue(self.event.set_event(
            self.key, event_id, {'parts': {min(event.parts): None}}))

        export_expectation = {
            1: {'constraint_type': const.EventPartGroupType.Statistic,
                'notes': 'Pack explosives for New Years!',
                'part_ids': [7, 8],
                'shortname': '1.H.',
                'title': '1. Hälfte'},
            2: {'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [9, 10, 11],
                'shortname': '2.H.',
                'title': '2. Hälfte'},
            3: {'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [9],
                'shortname': 'OW',
                'title': 'Oberwesel'},
            5: {'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [8, 11],
                'shortname': 'KA',
                'title': 'Kaub'},
            6: {'constraint_type':
                    const.EventPartGroupType.mutually_exclusive_participants,
                'notes': None,
                'part_ids': [7, 8],
                'shortname': 'TN 1H',
                'title': 'Teilnehmer 1. Hälfte'},
            7: {'constraint_type':
                    const.EventPartGroupType.mutually_exclusive_participants,
                'notes': None,
                'part_ids': [9, 10, 11],
                'shortname': 'TN 2H',
                'title': 'Teilnehmer 2. Hälfte'},
            8: {'constraint_type': const.EventPartGroupType.mutually_exclusive_courses,
                'notes': None,
                'part_ids': [7, 8],
                'shortname': 'Kurs 1H',
                'title': 'Kurse 1. Hälfte'},
            9: {'constraint_type': const.EventPartGroupType.mutually_exclusive_courses,
                'notes': None,
                'part_ids': [9, 10, 11],
                'shortname': 'Kurs 2H',
                'title': 'Kurse 2. Hälfte'},
            1005: {'constraint_type': const.EventPartGroupType.Statistic,
                   'notes': "Let's see what happens",
                   'part_ids': [7, 8, 9, 10, 11, 12],
                   'shortname': 'all',
                   'title': 'All'},
            1006: {'constraint_type': const.EventPartGroupType.Statistic,
                   'notes': "Let's see what happens",
                   'part_ids': [7, 8],
                   'shortname': 'ALL',
                   'title': 'Everything'},
        }
        export = self.event.partial_export_event(self.key, event_id)
        self.assertEqual(export['event']['part_groups'], export_expectation)

        # Delete the entire event. Requires admin.
        with self.switch_user("annika"):
            blockers = self.event.delete_event_blockers(self.key, event_id)
            self.assertEqual(
                set(blockers),
                {"orgas", "event_parts", "course_tracks", "part_groups",
                 "part_group_parts", "track_groups", "track_group_tracks",
                 "courses", "log", "lodgement_groups", "event_fees"},
            )
            self.assertTrue(self.event.delete_event(self.key, event_id, blockers))

    @as_users("annika")
    @storage
    def test_calculate_fee_mep(self) -> None:
        # Create a new event with some part groups, have someone register and
        #  check the calculated fees.
        e_data = {
            "title": "Fragmentierte Akademie",
            "shortname": "frAka",
            "institution": 1,
            "description": None,
            "parts": {
                -1: {
                    "title": "A",
                    "shortname": "A",
                    "part_begin": "3000-01-01",
                    "part_end": "3000-01-02",
                    "waitlist_field_id": None,
                    "camping_mat_field_id": None,
                },
                -2: {
                    "title": "B",
                    "shortname": "B",
                    "part_begin": "3000-01-01",
                    "part_end": "3000-01-02",
                    "waitlist_field_id": None,
                    "camping_mat_field_id": None,
                },
                -3: {
                    "title": "C",
                    "shortname": "C",
                    "part_begin": "3000-01-01",
                    "part_end": "3000-01-02",
                    "waitlist_field_id": None,
                    "camping_mat_field_id": None,
                },
                -4: {
                    "title": "D",
                    "shortname": "D",
                    "part_begin": "3000-01-01",
                    "part_end": "3000-01-02",
                    "waitlist_field_id": None,
                    "camping_mat_field_id": None,
                },
            },
        }
        event_id = self.event.create_event(self.key, e_data)

        # These are the mep constraints, but they no longer have any direct effect on
        #  the fees.
        # mep = const.EventPartGroupType.mutually_exclusive_participants
        # pg_data: CdEDBOptionalMap = {
        #     -1: {
        #         "title": "A+B",
        #         "shortname": "A+B",
        #         "part_ids": [1001, 1002],
        #         "constraint_type": mep,
        #         "notes": None,
        #     },
        #     -2: {
        #         "title": "B+C",
        #         "shortname": "B+C",
        #         "part_ids": [1002, 1003],
        #         "constraint_type": mep,
        #         "notes": None,
        #     },
        #     -3: {
        #         "title": "C+D",
        #         "shortname": "C+D",
        #         "part_ids": [1003, 1004],
        #         "constraint_type": mep,
        #         "notes": None,
        #     },
        # }
        # self.event.set_part_groups(self.key, event_id, pg_data)

        fee_data: CdEDBOptionalMap = {
            -1: {
                "kind": const.EventFeeType.common,
                "title": "A",
                "notes": None,
                "amount": "1",
                "condition": "part.A",
            },
            -2: {
                "kind": const.EventFeeType.common,
                "title": "B",
                "notes": None,
                "amount": "2",
                "condition": "part.B",
            },
            -3: {
                "kind": const.EventFeeType.common,
                "title": "C",
                "notes": None,
                "amount": "3",
                "condition": "part.C",
            },
            -4: {
                "kind": const.EventFeeType.common,
                "title": "D",
                "notes": None,
                "amount": "4",
                "condition": "part.D",
            },
            -5: {
                "kind": const.EventFeeType.common,
                "title": "A und B",
                "notes": None,
                "amount": "-1",
                "condition": "part.A AND part.B",
            },
            -6: {
                "kind": const.EventFeeType.common,
                "title": "B und C",
                "notes": None,
                "amount": "-2",
                "condition": "part.B AND part.C",
            },
            -7: {
                "kind": const.EventFeeType.common,
                "title": "C und D",
                "notes": None,
                "amount": "-3",
                "condition": "part.C AND part.D",
            },
            -8: {
                "kind": const.EventFeeType.common,
                "title": "A und B und C",
                "notes": None,
                "amount": "1",
                "condition": "part.A AND part.B AND part.C",
            },
            -9: {
                "kind": const.EventFeeType.common,
                "title": "B und C und D",
                "notes": None,
                "amount": "2",
                "condition": "part.B AND part.C AND part.D",
            },
            -10: {
                "kind": const.EventFeeType.common,
                "title": "A und B und C und D",
                "notes": None,
                "amount": "-1",
                "condition": "part.A AND part.B AND part.C AND part.D",
            },
        }
        self.event.set_event_fees(self.key, event_id, fee_data)

        r_data = {
            "event_id": event_id,
            "persona_id": self.user['id'],
            "mixed_lodging": True,
            "list_consent": True,
            "notes": None,
            "parts": {
                1001: {
                    "status": const.RegistrationPartStati.participant,
                    "lodgement_id": None,
                    "is_camping_mat": False,
                },
                1002: {
                    "status": const.RegistrationPartStati.participant,
                    "lodgement_id": None,
                    "is_camping_mat": False,
                },
                1003: {
                    "status": const.RegistrationPartStati.participant,
                    "lodgement_id": None,
                    "is_camping_mat": False,
                },
                1004: {
                    "status": const.RegistrationPartStati.participant,
                    "lodgement_id": None,
                    "is_camping_mat": False,
                },
            },
            "tracks": {},
        }
        reg_id = self.event.create_registration(self.key, r_data)

        c = const.RegistrationPartStati.cancelled
        p = const.RegistrationPartStati.participant
        expectation = {
            (c, c, c, c): 0,
            (c, c, c, p): 4,
            (c, c, p, c): 3,
            (c, c, p, p): 4,
            (c, p, c, c): 2,
            (c, p, c, p): 6,
            (c, p, p, c): 3,
            (c, p, p, p): 6,
            (p, c, c, c): 1,
            (p, c, c, p): 5,
            (p, c, p, c): 4,
            (p, c, p, p): 5,
            (p, p, c, c): 2,
            (p, p, c, p): 6,
            (p, p, p, c): 4,
            (p, p, p, p): 6,
        }

        for stati, expected_fee in expectation.items():
            r_data = {
                "id": reg_id,
                "parts": {
                    1001: {
                        "status": stati[0],
                    },
                    1002: {
                        "status": stati[1],
                    },
                    1003: {
                        "status": stati[2],
                    },
                    1004: {
                        "status": stati[3],
                    },
                },
            }
            self.event.set_registration(self.key, r_data)
            combination = ", ".join(str(int(x == p)) for x in stati)
            fee = self.event.calculate_fee(self.key, reg_id)
            with self.subTest(combination=combination):
                self.assertEqual(fee, decimal.Decimal(expected_fee))

    @as_users("garcia")
    def test_part_shortname_change(self) -> None:
        event_id = 1
        new_fee = {
            'kind': const.EventFeeType.common,
            'title': "Test",
            'amount': "1",
            'condition': "part.1.H. and not part.2.H.",
            'notes': None,
        }
        self.event.set_event_fees(self.key, event_id, {-1: new_fee})
        event_data = {
            'id': event_id,
            'parts': {
                2: {
                    'shortname': "2.H.",
                },
                3: {
                    'shortname': "1.H.",
                },
            },
        }
        self.event.set_event(self.key, event_id, event_data)
        event = self.event.get_event(self.key, event_id)
        self.assertEqual(
            "part.2.H. and not part.1.H.", event.fees[1001].condition)

    @as_users("garcia")
    def test_rcw_mechanism(self) -> None:
        # Cull readonly attributes
        def _get_lodgement_group(rs: RequestState, group_id: int) -> CdEDBObject:
            ret = self.event.get_lodgement_group(rs, group_id=group_id)
            del ret['lodgement_ids']
            del ret['camping_mat_capacity']
            del ret['regular_capacity']
            return ret

        group_id = 1
        data = _get_lodgement_group(self.key, group_id=group_id)
        self.event.rcw_lodgement_group(self.key, data)
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))

        # positional argument
        data['title'] = "Stavromula Beta"
        self.event.rcw_lodgement_group(self.key, data)
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        self.event.rcw_lodgement_group(
            self.key, {'id': data['id'], 'title': data['title']})
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        data['title'] = "Stavromula Gamma"
        self.event.rcw_lodgement_group(self.key, data)
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        data['title'] = "Stavromula Delta"
        self.event.rcw_lodgement_group(
            self.key, {'id': data['id'], 'title': data['title']})
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))

        # keyword argument
        data['title'] = "Stavromula Epsilon"
        self.event.rcw_lodgement_group(self.key, data=data)
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        self.event.rcw_lodgement_group(
            self.key, data={'id': data['id'], 'title': data['title']})
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        data['title'] = "Stavromula Zeta"
        self.event.rcw_lodgement_group(self.key, data=data)
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))
        data['title'] = "Stavromula Eta"
        self.event.rcw_lodgement_group(
            self.key, data={'id': data['id'], 'title': data['title']})
        self.assertEqual(data, _get_lodgement_group(self.key, group_id=group_id))

    @as_users("garcia")
    def test_orga_apitokens(self) -> None:
        event_id = 1
        event_log_offset, _ = self.event.retrieve_log(
            self.key, EventLogFilter(event_id=1))

        orga_token_ids = self.event.list_orga_tokens(self.key, event_id)
        orga_tokens = self.event.get_orga_tokens(self.key, orga_token_ids)
        expectation = {
            1: OrgaToken(
                id=cast(vtypes.ID, 1),
                event_id=cast(vtypes.ID, event_id),
                title="Garcias technische Spielerei",
                notes="Mal probieren, was diese API so alles kann.",
                etime=datetime.datetime(
                    2222, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc,
                ),
            ),
        }
        for token in expectation.values():
            token.ctime = nearly_now()
        self.assertEqual(expectation, orga_tokens)

        base_time = now()
        delta = datetime.timedelta(minutes=1)
        with freezegun.freeze_time(base_time) as frozen_time:
            new_token = OrgaToken(
                id=cast(vtypes.ProtoID, -1),
                event_id=cast(vtypes.ID, event_id),
                title="New Token!",
                notes=None,
                etime=base_time + delta,
            )
            new_id, secret = self.event.create_orga_token(self.key, new_token)
            new_token.id = vtypes.ProtoID(new_id)
            apitoken = cast(RequestState, new_token.get_token_string(secret))

            log_expectation = [
                {
                    'code': const.EventLogCodes.orga_token_created,
                    'change_note': new_token.title,
                    'ctime': now(),
                },
            ]
            self.assertEqual(
                {}, self.event.delete_orga_token_blockers(self.key, new_id))

            droid_export = self.event.partial_export_event(apitoken, event_id)
            partial_export = self.event.partial_export_event(self.key, event_id)
            self.assertEqual(droid_export, partial_export)

            blockers = self.event.delete_orga_token_blockers(self.key, new_id)
            self.assertEqual({'atime': [True]}, blockers)

            frozen_time.tick(2*delta)

            with self.assertRaisesRegex(APITokenError, "This .+ token has expired."):
                self.event.partial_export_event(apitoken, event_id)

            self.assertTrue(self.event.revoke_orga_token(self.key, new_id))
            log_expectation.append({
                'code': const.EventLogCodes.orga_token_revoked,
                'change_note': new_token.title,
            })

            changed_token = {'id': new_id, 'notes': "For testing only."}
            self.assertTrue(self.event.change_orga_token(self.key, changed_token))

            changed_token = {'id': new_id, 'title': "New Name"}
            self.assertTrue(self.event.change_orga_token(self.key, changed_token))

            log_expectation.extend([
                {
                    'code': const.EventLogCodes.orga_token_changed,
                    'change_note': new_token.title,
                },
                {
                    'code': const.EventLogCodes.orga_token_changed,
                    'change_note': f"'{new_token.title}' -> '{changed_token['title']}'",
                },
            ])

            with self.assertRaisesRegex(
                    APITokenError, "This .+ token has been revoked."):
                self.event.partial_export_event(apitoken, event_id)

            self.assertTrue(self.event.delete_orga_token(self.key, new_id, ("atime",)))
            self.assertNotIn(new_id, self.event.list_orga_tokens(self.key, event_id))
            log_expectation.append({
                'code': const.EventLogCodes.orga_token_deleted,
                'change_note': changed_token['title'],
            })

            self.assertLogEqual(log_expectation, realm='event', event_id=event_id,
                                offset=event_log_offset)

    @storage
    @as_users("anton")
    def test_external_fee(self) -> None:
        external_fee_amount = decimal.Decimal(1)

        # 1. Create a lightweight event with only an external fee.
        event_id = self.event.create_event(self.key, {
            'title': "TestAkademie",
            'shortname': "tAka",
            'institution': const.PastInstitutions.main_insitution(),
            'description': None,
            'parts': {
                -1: {
                    'part_begin': "2222-02-02",
                    'part_end': "2222-02-22",
                    'title': "TestPart",
                    'shortname': "TP",
                },
            },
            'fees': {
                -1: {
                    'title': "Externenzusatzbeitrag",
                    'notes': None,
                    'amount': external_fee_amount,
                    'condition': "NOT is_member",
                    'kind': const.EventFeeType.external,
                },
            },
        })

        # 2.1 Set test user to not be a member then register them.
        #  Check that external fee applies.
        persona_id = 2
        self.cde.change_membership(self.key, persona_id, False)

        rdata: CdEDBObject = {
            'event_id': event_id,
            'persona_id': persona_id,
            'mixed_lodging': True,
            'list_consent': True,
            'notes': None,
            'parts': {
                1001: {
                    'status': const.RegistrationPartStati.participant,
                },
            },
            'tracks': {
            },
        }
        reg_id = self.event.create_registration(self.key, rdata)
        self.assertEqual(
            external_fee_amount, self.event.calculate_fee(self.key, reg_id))

        # 2.2 Now grant them membership and check that the external fee still holds.
        self.cde.change_membership(self.key, persona_id, True)
        self.assertEqual(
            external_fee_amount, self.event.calculate_fee(self.key, reg_id))

        # 3.1 Delete and recreate the registration.
        #  Check that external fee does not apply.
        self.event.delete_registration(
            self.key, reg_id, ('registration_parts',))
        new_reg_id = self.event.create_registration(self.key, rdata)
        self.assertEqual(
            decimal.Decimal(0), self.event.calculate_fee(self.key, new_reg_id))

        # 3.2 Revoke membership and check that external fee still does not apply.
        self.cde.change_membership(self.key, persona_id, False)
        self.assertEqual(
            decimal.Decimal(0), self.event.calculate_fee(self.key, new_reg_id))

    @event_keeper
    @as_users("anton")
    def test_event_keeper_log_entries(self) -> None:
        # pylint: disable=protected-access
        event_id = 1

        def normalize_reference_time(dt: datetime.datetime) -> datetime.datetime:
            return datetime.datetime.fromisoformat(
                self.event._event_keeper.format_datetime(dt).decode())

        base_time = now() + datetime.timedelta(hours=1)
        delta = datetime.timedelta(minutes=42)

        # Convert reference time to same format as parsed time because of tz trouble.
        reference_time = normalize_reference_time(base_time)

        self.event.event_keeper_commit(
            self.key, event_id, "pre test", after_change=True,
        )
        # Ensure that the commit time matches the current (non-frozen) time.
        self.assertEqual(
            nearly_now(delta=datetime.timedelta(milliseconds=10)),
            self.event._event_keeper.latest_logtime(event_id),
        )

        with freezegun.freeze_time(base_time) as frozen_time:
            frozen_time.tick(delta)

            # Create any log entry.
            pdf_data = (self.testfile_dir / "form.pdf").read_bytes()
            self.event.change_minor_form(self.key, event_id, pdf_data)

            # Retrieve the time of the log entry.
            log = self.event.retrieve_log(
                self.key, EventLogFilter(length=1),
            )[1][0]
            log_reference_time = normalize_reference_time(log['ctime'])

            frozen_time.tick(delta)

            # Create a commit and ensure that the commit time matches the log time
            #  instead of the current (frozen) time.
            self.event.event_keeper_commit(
                self.key, event_id, "foo bar", after_change=True,
            )
            self.assertEqual(
                log_reference_time,
                self.event._event_keeper.latest_logtime(event_id),
            )
            self.assertNotEqual(
                reference_time,
                self.event._event_keeper.latest_logtime(event_id),
            )
