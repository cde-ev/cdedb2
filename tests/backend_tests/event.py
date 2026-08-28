#!/usr/bin/env python3

# pyrefly: ignore-errors[implicit-any-empty-container]

import collections.abc
import copy
import datetime
import decimal
import json
import unittest
from typing import Any, cast

import freezegun
import psycopg2
import psycopg2.errorcodes
import psycopg2.errors

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    EVENT_SCHEMA_VERSION,
    AgeClasses,
    CdEDBObject,
    CdEDBObjectMap,
    CourseFilterPositions,
    InfiniteEnum,
    RequestState,
    cast_fields,
    nearly_now,
    now,
    parse_datetime,
)
from cdedb.common.exceptions import (
    APITokenError,
    EventIsBalancedError,
    PartialImportError,
    PrivilegeError,
)
from cdedb.common.query import Query, QueryConstraint, QueryOperators, QueryScope
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.filter import datetime_filter
from cdedb.models.droid import OrgaToken
from tests.common import (
    ANONYMOUS,
    USER_DICT,
    BackendTest,
    as_users,
    event_keeper,
    json_keys_to_int,
    prepsql,
    storage,
)

UNIQUE_VIOLATION = psycopg2.errors.lookup(psycopg2.errorcodes.UNIQUE_VIOLATION)
NON_EXISTING_ID = 2**30

EventID = lambda x: vtypes.EventID(vtypes.ID(x))
CourseID = lambda x: vtypes.CourseID(vtypes.ID(x))
PersonaID = lambda x: vtypes.PersonaID(vtypes.ID(x))
RegistrationID = lambda x: vtypes.RegistrationID(vtypes.ID(x))
LodgementID = lambda x: vtypes.LodgementID(vtypes.ID(x))
LodgementGroupID = lambda x: vtypes.LodgementGroupID(vtypes.ID(x))


class TestEventBackend(BackendTest):
    used_backends = ("core", "event")

    @as_users("emilia")
    def test_basics(self) -> None:
        data = self.core.get_event_user(self.key, self.user['id'])
        data.nickname = "Zelda"
        data.name_supplement = "von und zu Hylia"
        setter = {
            "id": data.id,
            "nickname": data.nickname,
            "name_supplement": data.name_supplement,
            "telephone": data.telephone,
        }
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_event_user(self.key, self.user['id'])
        self.assertEqual(data, new_data)

    @event_keeper
    @as_users("annika", "garcia", "charly")
    def test_entity_event(self) -> None:
        old_events = self.event.list_events(self.key)
        data: CdEDBObject = {
            'title': "New Link Academy",
            'institution': 1,
            'website_url': "https://www.example.com/test",
            'shortname': 'link',
            'registration_start': datetime.datetime(
                2000, 11, 22, 0, 0, 0, tzinfo=datetime.UTC
            ),
            'registration_soft_limit': datetime.datetime(
                2022, 1, 2, 0, 0, 0, tzinfo=datetime.UTC
            ),
            'registration_hard_limit': None,
            'iban': None,
            'use_additional_questionnaire': False,
            "notify_on_registration": const.NotifyOnRegistration.never,
            'description': """Some more text

                on more lines.""",
            'registration_status_text': None,
            'mail_text': None,
            'participant_info': """Welcome to our

            **new**
            and
            _fancy_

            academy! :)""",
            'notes': None,
            'field_definition_notes': "No fields plz",
            'orgas': {2, 7},
            'caretakers': {3},
            'checkin_helpers': set(),
            'parts': {
                -1: {
                    'tracks': {
                        -1: {
                            'title': "First lecture",
                            'shortname': "First",
                            'num_choices': 3,
                            'min_choices': 3,
                            'sortkey': 1,
                            'course_room_field_id': None,
                        },
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
                        -1: {
                            'title': "Second lecture",
                            'shortname': "Second",
                            'num_choices': 3,
                            'min_choices': 1,
                            'sortkey': 1,
                            'course_room_field_id': None,
                        },
                    },
                    'title': "Second coming",
                    'shortname': "second",
                    'part_begin': datetime.date(2110, 8, 7),
                    'part_end': datetime.date(2110, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
            },
            'fields': {
                -1: {
                    'field_name': "instrument",
                    'title': "Instrument",
                    'description': None,
                    'kind': const.FieldDatatypes.str,
                    'association': const.FieldAssociations.registration,
                    'sort_group': None,
                    'sortkey': 0,
                    'checkin': False,
                    'entries': None,
                },
                -2: {
                    'field_name': "preferred_excursion_date",
                    'title': "Bevorzugtes Ausflugsdatum",
                    'description': None,
                    'kind': const.FieldDatatypes.date,
                    'association': const.FieldAssociations.registration,
                    'sort_group': None,
                    'sortkey': 0,
                    'checkin': True,
                    'entries': {
                        None: "never",
                        datetime.date.fromisoformat(
                            "2109-08-16"
                        ): "In the first coming",
                        datetime.date.fromisoformat(
                            "2110-08-16"
                        ): "During the second coming",
                    },
                },
                -3: {
                    'field_name': "is_child",
                    'title': "Ist Kind",
                    'description': None,
                    'kind': const.FieldDatatypes.bool,
                    'association': const.FieldAssociations.registration,
                    'sort_group': None,
                    'sortkey': 5,
                    'checkin': False,
                    'entries': None,
                },
            },
        }
        fee_data = [
            {
                "kind": const.EventFeeType.common,
                "title": "first",
                "notes": None,
                "amount": decimal.Decimal("234.56"),
                "condition": "part.first",
            },
            {
                "kind": const.EventFeeType.common,
                "title": "second",
                "notes": None,
                "amount": decimal.Decimal("0.00"),
                "condition": "part.second",
            },
            {
                "kind": const.EventFeeType.solidary_reduction,
                "title": "Is Child",
                "notes": None,
                "amount": decimal.Decimal("-7.00"),
                "condition": "part.second and field.is_child",
            },
            {
                "kind": const.EventFeeType.external,
                "title": "Externenzusatzbeitrag",
                "notes": None,
                "amount": decimal.Decimal("6.66"),
                "condition": "any_part and not is_member",
            },
        ]
        with self.switch_user("annika"):
            new_id = self.event.create_event(self.key, data)
        for fee in fee_data:
            self.event.create_event_fee(self.key, new_id, fee)
        data['id'] = new_id
        data['is_locked'] = False
        data['is_archived'] = False
        data['is_participant_list_visible'] = False
        data['is_course_assignment_visible'] = False
        data['is_course_list_visible'] = False
        data['is_course_state_visible'] = False
        data['is_cancelled'] = False
        data['is_balanced'] = False
        data['is_registration_approved'] = False
        data['is_visible'] = False
        data['reimbursement_iban_field_id'] = None
        data['lodge_field_id'] = None
        data['orga_address'] = None
        data['questionnaire_notes'] = None
        # TODO dynamically adapt ids from the database result
        data['tracks'] = {
            1001: data['parts'][-1]['tracks'][-1],
            1002: data['parts'][-2]['tracks'][-1],
        }
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
                    data['parts'][part]['event_id'] = new_id
                    data['parts'][part]['part_group_ids'] = set()
                    self.assertEqual(
                        set(x['title'] for x in data['parts'][part]['tracks'].values()),
                        set(x.title for x in tmp.parts[part].tracks.values()),
                    )
                    data['parts'][part]['tracks'] = tmp.parts[part].as_dict()['tracks']
                    del data['parts'][oldpart]
                    break
        for track in data['tracks'].values():
            track['track_group_ids'] = set()
        field_map: dict[str, int] = {}
        for field in tmp.fields:
            for oldfield in data['fields']:
                if (
                    tmp.fields[field].field_name
                    == data['fields'][oldfield]['field_name']
                ):
                    field_map[tmp.fields[field].field_name] = field
                    data['fields'][field] = data['fields'][oldfield]
                    data['fields'][field]['id'] = field
                    data['fields'][field]['event_id'] = new_id
                    del data['fields'][oldfield]
                    break
        data['fees'] = {}
        for fee_id in tmp.fees:
            for fee in fee_data:
                if tmp.fees[fee_id].title == fee['title']:
                    data['fees'][fee_id] = fee
                    data['fees'][fee_id]['id'] = fee_id
                    data['fees'][fee_id]['event_id'] = new_id
                    data['fees'][fee_id]['amount_min'] = None
                    data['fees'][fee_id]['amount_max'] = None
                    break

        self.assertEqual(data, self.event.get_event(self.key, new_id).as_dict())
        data['title'] = "Alternate Universe Academy"
        newpart = {
            'tracks': {
                -1: {
                    'title': "Third lecture",
                    'shortname': "Third",
                    'num_choices': 2,
                    'min_choices': 2,
                    'sortkey': 2,
                    'course_room_field_id': None,
                },
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
        updated_fees: CdEDBObjectMap = {
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
            'field_name': "kuea",
            'title': "KäA",
            'description': None,
            'kind': const.FieldDatatypes.str,
            'association': const.FieldAssociations.lodgement,
            'sort_group': None,
            'sortkey': -7,
            'checkin': False,
            'entries': None,
        }
        changed_field: CdEDBObject = {
            'kind': const.FieldDatatypes.date,
            'entries': {
                datetime.date.fromisoformat("2110-08-15"): "early second coming",
                datetime.date.fromisoformat("2110-08-17"): "late second coming",
            },
            'checkin': True,
        }
        self.event.set_event(
            self.key,
            new_id,
            {
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
            },
        )
        for fee_id, fee in updated_fees.items():
            if fee_id < 0:
                self.event.create_event_fee(self.key, new_id, fee)
            else:
                self.event.change_event_fee(self.key, fee_id, fee)
        # fixup parts and fields
        tmp = self.event.get_event(self.key, new_id)
        for part in tmp.parts:
            if tmp.parts[part].title == "Third coming":
                part_map[tmp.parts[part].title] = part
                data['parts'][part] = newpart
                data['parts'][part]['event_id'] = new_id
                self.assertEqual(
                    set(x['title'] for x in data['parts'][part]['tracks'].values()),
                    set(x.title for x in tmp.parts[part].tracks.values()),
                )
                data['parts'][part]['tracks'] = tmp.parts[part].as_dict()['tracks']
        del data['parts'][part_map["First coming"]]
        changed_part['event_id'] = new_id
        changed_part['shortname'] = "second"
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
                'title': 'Second lecture v2',
                'shortname': "Second v2",
                'num_choices': 5,
                'min_choices': 4,
                'sortkey': 3,
                'course_room_field_id': None,
                'track_group_ids': set(),
            },
            1003: {
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
            'id': 1005,
            'event_id': new_id,
            'amount_min': None,
            'amount_max': None,
        })

        self.assertEqual(data, self.event.get_event(self.key, new_id).as_dict())

        self.assertNotIn(new_id, old_events)
        new_events = self.event.list_events(self.key)
        self.assertIn(new_id, new_events)

        new_course = {
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'max_size': 12,
            'min_size': None,
            'notes': "Beware of dragons.",
            'segments': {
                1002: {
                    "is_active": True,
                },
            },
            'is_visible': True,
        }
        new_course_id = self.event.create_course(self.key, new_id, new_course)
        new_course['id'] = new_course_id
        new_course['event_id'] = new_id
        new_course['fields'] = {}
        self.assertEqual(
            new_course, self.event.get_course(self.key, new_course_id).as_dict()
        )

        new_group_data: CdEDBObject = {'title': "Nebenan"}
        new_group_id = self.event.create_lodgement_group(
            self.key, new_id, new_group_data
        )
        self.assertLess(0, new_group_id)
        new_group_data.update({
            'id': new_group_id,
            'event_id': new_id,
            'lodgement_ids': set(),
            'regular_capacity': 0,
            'camping_mat_capacity': 0,
        })
        new_group = models.LodgementGroup(**new_group_data)
        self.assertEqual(
            new_group,
            self.event.get_lodgement_groups(self.key, new_id)[new_group_id],
        )

        new_lodgement_data: CdEDBObject = {
            "group_id": new_group_id,
            "title": 'HY',
            "notes": "Notizen",
            "regular_capacity": 42,
            "camping_mat_capacity": 11,
        }
        new_lodge_id = self.event.create_lodgement(self.key, new_id, new_lodgement_data)
        self.assertLess(0, new_lodge_id)
        new_lodgement_data.update({
            'id': new_lodge_id,
            'event_id': new_id,
            'fields': {},
        })
        self.assertEqual(
            new_lodgement_data,
            self.event.new_get_lodgement(self.key, new_lodge_id).as_dict(),
        )

        new_reg = {
            'event_id': new_id,
            'list_consent': True,
            'mixed_lodging': False,
            'orga_notes': None,
            'notes': None,
            'parental_agreement': True,
            'parts': {
                part_map["Second coming"]: {
                    'lodgement_id': new_lodge_id,
                    'status': 1,
                },
                part_map["Third coming"]: {
                    'lodgement_id': new_lodge_id,
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
        query = Query(
            scope,
            scope.get_spec(event=event),
            ['reg.notes'],
            [('reg.notes', QueryOperators.nonempty, None)],
            [('reg.notes', True)],
        )
        query_id = self.event.store_event_query(
            self.key,
            new_id,
            scope,
            {"query_name": "test_query", "serialized_query": query.serialize()},
        )
        self.assertTrue(query_id)
        self.assertEqual(
            self.event.get_event_queries(self.key, new_id)[query_id].serialize_to_url(),
            query.serialize_to_url()
            | {"query_name": "test_query", "query_group": None},
        )

        with self.switch_user("annika"):
            self.assertLess(
                0,
                self.event.delete_event(
                    self.key,
                    new_id,
                    (
                        "event_parts",
                        "course_tracks",
                        "field_definitions",
                        "courses",
                        "orgas",
                        "lodgement_groups",
                        "lodgements",
                        "registrations",
                        "log",
                        "questionnaire",
                        "stored_queries",
                        "mailinglists",
                        "event_fees",
                        "caretakers",
                        "checkin_helpers",
                    ),
                ),
            )

            # Test deletion of event, cascading all blockers.
            self.assertLess(
                0,
                self.event.delete_event(
                    self.key,
                    EventID(1),
                    self.event.delete_event_blockers(self.key, EventID(1)),
                ),
            )

        # Test part groups and track groups in get_event.
        expectation_part = {
            'event_id': 4,
            'title': "1. Hälfte Oberwesel",
            'shortname': "O1",
            'part_begin': datetime.date(3000, 1, 1),
            'part_end': datetime.date(3000, 2, 1),
            'waitlist_field_id': None,
            'camping_mat_field_id': None,
            'tracks': {
                6: {
                    'title': "Oberwesel Kurs 1",
                    'shortname': "OK1",
                    'num_choices': 4,
                    'min_choices': 2,
                    'sortkey': 1,
                    'course_room_field_id': None,
                    'track_group_ids': {1, 4},
                },
            },
            'part_group_ids': {1, 3, 6},
        }
        self.assertEqual(
            expectation_part,
            self.event.get_event(self.key, EventID(4)).parts[6].as_dict(),
        )

    @as_users("annika")
    def test_track_groups(self) -> None:
        event_id = EventID(4)
        event = self.event.get_event(self.key, event_id)
        # delete existent track groups to avoid interference
        for tg_id in event.track_groups.keys():
            self.assertTrue(self.event.delete_track_group(self.key, tg_id))

        new_track_group: CdEDBObject = {
            'title': "Test",
            'shortname': "Test",
            'constraint_type': const.CourseTrackGroupType.course_choice_sync,
            'notes': None,
            'track_ids': event.tracks.keys(),
            'sortkey': 1,
        }
        # Test incompatible tracks.
        with self.assertRaisesRegex(ValueError, "must have the same number of choices"):
            self.event.add_track_group(self.key, event_id, new_track_group)
        # Test empty tracks.
        new_track_group['track_ids'] = []
        with self.assertRaisesRegex(ValueError, "Must not be empty."):
            self.event.add_track_group(self.key, event_id, new_track_group)
        # Test unknown tracks.
        new_track_group['track_ids'] = {1, 2}
        with self.assertRaisesRegex(ValueError, "Unknown track."):
            self.event.add_track_group(self.key, event_id, new_track_group)

        # Test correct tracks with incompatible choices:
        reg_data = {
            "event_id": event_id,
            "parts": {
                part_id: {
                    "status": const.RegistrationPartStati.applied,
                }
                for part_id in event.parts
            },
            "tracks": {
                track_id: {
                    "choices": [11] if track_id == 6 else [],
                }
                for track_id in event.tracks
            },
            "persona_id": 1,
            "notes": None,
            "list_consent": True,
            "mixed_lodging": True,
        }
        registration_id = self.event.create_registration(self.key, reg_data)

        new_track_group['track_ids'] = {6, 7}
        with self.assertRaisesRegex(ValueError, "incompatible existing course choices"):
            self.event.add_track_group(self.key, event_id, new_track_group)

        self.assertTrue(
            self.event.delete_registration(
                self.key,
                registration_id,
                {"registration_parts", "registration_tracks", "course_choices"},
            )
        )

        # Test correct tracks.
        self.assertTrue(self.event.add_track_group(self.key, event_id, new_track_group))
        event = self.event.get_event(self.key, event_id)
        expectation: CdEDBObject = new_track_group.copy()
        expectation['id'] = 1001
        expectation['event_id'] = event_id
        expectation['tracks'] = {
            track_id: event.tracks[track_id].as_dict()
            for track_id in expectation['track_ids']
        }
        self.assertEqual(expectation, event.track_groups[1001].as_dict())

        # Test duplicate tracks.
        with self.assertRaises(ValueError):
            self.event.add_track_group(self.key, event_id, new_track_group)
        # Test duplicate title.
        with self.assertRaises(ValueError):
            tmp = copy.copy(new_track_group)
            tmp['track_ids'] = [8]
            self.event.add_track_group(self.key, event_id, tmp)

        # Test update
        tg_update = {
            'title': "tEST",
            'track_ids': {7, 8},
        }
        # updating track_ids is forbidden
        with self.assertRaises(KeyError):
            self.event.change_track_group(self.key, 1001, tg_update)
        del tg_update['track_ids']
        self.assertTrue(self.event.change_track_group(self.key, 1001, tg_update))
        event = self.event.get_event(self.key, event_id)
        expectation.update(tg_update)
        expectation['tracks'] = {
            track_id: event.tracks[track_id].as_dict()
            for track_id in expectation['track_ids']
        }
        self.assertEqual(expectation, event.track_groups[1001].as_dict())

    @as_users("emilia")
    def test_course_choice_sync(self) -> None:
        event_id = EventID(4)
        registration_id = 10
        track_id = 6
        event = self.event.get_event(self.key, event_id)
        self.assertTrue(event.tracks[track_id].track_groups)
        self.assertTrue(event.track_groups[1].constraint_type.is_sync())
        self.assertGreater(len(event.track_groups[1].tracks), 1)
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
        event_id = EventID(1)
        with open("/cdedb2/tests/ancillary_files/form.pdf", "rb") as f:
            minor_form = f.read()
        self.assertFalse(self.event.has_minor_form(self.key, event_id))
        self.assertLess(0, self.event.change_minor_form(self.key, event_id, minor_form))
        with open(self.event.get_minor_form_path(self.key, event_id), "rb") as f:
            new_minor_form = f.read()
        self.assertEqual(minor_form, new_minor_form)
        self.assertGreater(0, self.event.change_minor_form(self.key, event_id, None))
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
        self.assertLogEqual(
            expectation,
            "event",
            event_id=event_id,
            codes=[
                const.EventLogCodes.minor_form_updated,
                const.EventLogCodes.minor_form_removed,
            ],
        )

    @as_users("annika")
    def test_aposteriori_track_creation(self) -> None:
        event_id = EventID(1)
        part_id = 1
        # The expected new id.
        new_track_id = 1001

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id)
        )
        event = self.event.get_event(self.key, event_id)

        new_track: CdEDBObject = {
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

        new_track_obj = models.CourseTrack.from_database(new_track)
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
        event_id = EventID(1)
        part_id = 2
        track_id = 1

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id)
        )
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
            self.key, self.event.list_registrations(self.key, event_id)
        )

        for reg in regs.values():
            self.assertNotIn(track_id, reg["tracks"])

        expectation -= {track_id}
        self.assertEqual(expectation, event.tracks.keys())

    @as_users("emilia")
    def test_aposteriori_part_creation(self) -> None:
        event_id = EventID(4)

        self.assertTrue(self.event.list_registrations(self.key, event_id))

        regs = self.event.get_registrations(
            self.key, self.event.list_registrations(self.key, event_id)
        )
        event = self.event.get_event(self.key, event_id)

        new_part: CdEDBObject = {
            'title': "Abreise",
            'shortname': "D",
            'part_begin': datetime.date(2222, 11, 11),
            'part_end': datetime.date(2222, 12, 12),
        }
        update_event = {
            'parts': {
                -1: new_part,
            },
        }
        self.event.set_event(self.key, event_id, update_event)

        new_part['id'] = new_part_id = 1001
        new_part['event_id'] = event_id
        new_part['tracks'] = {}
        new_part['part_groups'] = {}
        new_part['waitlist_field_id'] = new_part['camping_mat_field_id'] = None

        for reg in regs.values():
            reg['parts'][new_part_id] = {
                'status': const.RegistrationPartStati.not_applied,
                'lodgement_id': None,
                'is_camping_mat': False,
                'part_id': new_part_id,
                'registration_id': reg['id'],
                'age': AgeClasses.full,
            }

        new_part_obj = models.EventPart.from_database(new_part)
        event.parts[new_part_id] = new_part_obj

        reg_ids = self.event.list_registrations(self.key, event_id)
        self.assertEqual(regs, self.event.get_registrations(self.key, reg_ids))
        self.assertEqual(
            event.as_dict(), self.event.get_event(self.key, event_id).as_dict()
        )
        self.assertEqual(event, self.event.get_event(self.key, event_id))

    @as_users("annika", "garcia")
    def test_json_fields_with_dates(self) -> None:
        event_id = EventID(1)
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
        reg_id = RegistrationID(1)
        update_registration = {
            'id': reg_id,
            'fields': {
                'arrival': datetime.datetime(
                    2222, 11, 9, 8, 55, 44, tzinfo=datetime.UTC
                ),
            },
        }
        self.event.set_registration(self.key, update_registration)
        data = self.event.get_registration(self.key, reg_id)
        expectation = {
            'anzahl_GROSSBUCHSTABEN': 4,
            'arrival': datetime.datetime(2222, 11, 9, 8, 55, 44, tzinfo=datetime.UTC),
            'arrival_at': datetime.datetime(2022, 2, 2, 9, 0, tzinfo=datetime.UTC),
            'lodge': 'Die üblichen Verdächtigen, insb. Berta Beispiel und '
            'garcia@example.cde :)',
            'is_child': False,
        }
        self.assertEqual(expectation, data['fields'])

    @as_users("annika", "garcia")
    def test_entity_course(self) -> None:
        event_id = EventID(1)
        event = self.event.get_event(self.key, event_id)
        old_courses = self.event.list_courses(self.key, event_id)
        data: CdEDBObject = {
            'title': (original_title := "Topos theory for the kindergarden"),
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'notes': "Beware of dragons.",
            'segments': {
                2: {
                    "is_active": True,
                },
                3: {
                    "is_active": False,
                },
            },
            'max_size': 42,
            'min_size': 23,
            'is_visible': True,
            'fields': {
                'room': "outside",
            },
        }
        new_id = self.event.create_course(self.key, event_id, data)
        data['id'] = new_id
        data['event_id'] = event_id
        self.assertEqual(data, self.event.get_course(self.key, new_id).as_dict())
        data['title'] = "Alternate Universes"
        data['segments'][2] = None
        data['segments'][1] = {
            "is_active": True,
        }
        self.event.set_course(
            self.key,
            new_id,
            {
                'title': data['title'],
                'segments': data['segments'],
            },
        )
        del data["segments"][2]
        self.assertEqual(data, self.event.get_course(self.key, new_id).as_dict())
        self.assertNotIn(new_id, old_courses)
        new_courses = self.event.list_courses(self.key, event_id)
        self.assertIn(new_id, new_courses)
        data["segments"][3]["is_active"] = True
        self.event.set_course(self.key, new_id, {'segments': data['segments']})
        self.assertEqual(data, self.event.get_course(self.key, new_id).as_dict())

        log_expectation = [
            {
                "code": const.EventLogCodes.course_created,
                "change_note": original_title,
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": original_title + f" ({event.tracks[2].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_activated,
                "change_note": original_title + f" ({event.tracks[2].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": original_title + f" ({event.tracks[3].title})",
            },
            {
                "code": const.EventLogCodes.course_changed,
                "change_note": original_title,
            },
            {
                "code": const.EventLogCodes.course_segment_deleted,
                "change_note": original_title + f" ({event.tracks[2].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_deactivated,
                "change_note": original_title + f" ({event.tracks[2].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_created,
                "change_note": original_title + f" ({event.tracks[1].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_activated,
                "change_note": original_title + f" ({event.tracks[1].title})",
            },
            {
                "code": const.EventLogCodes.course_segment_activated,
                "change_note": data["title"] + f" ({event.tracks[3].title})",
            },
        ]
        offset = len(self.get_sample_data("event.log"))
        self.assertLogEqual(
            log_expectation, "event", event_id=EventID(1), offset=offset
        )

    @as_users("annika", "garcia", maintain_data=True)
    def test_course_non_removable(self) -> None:
        self.assertNotEqual(
            {}, self.event.delete_course_blockers(self.key, CourseID(1))
        )

    @as_users("annika", "garcia")
    def test_course_delete(self) -> None:
        event_id = EventID(1)
        data = {
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'notes': "Beware of dragons.",
            'segments': {
                2: {
                    "is_active": True,
                },
                3: {
                    "is_active": False,
                },
            },
            'max_size': 42,
            'min_size': 23,
            'is_visible': True,
        }
        new_id = self.event.create_course(self.key, event_id, data)
        self.assertEqual(
            self.event.delete_course_blockers(self.key, new_id).keys(),
            {"course_segments"},
        )
        self.assertLess(
            0, self.event.delete_course(self.key, new_id, ("course_segments",))
        )

    @as_users("garcia")
    def test_course_choices_cascade(self) -> None:
        # Set the status quo.
        for course_id in (CourseID(1), CourseID(2), CourseID(3), CourseID(4)):
            cdata = {
                "segments": {
                    1: {"is_active": True},
                    2: {"is_active": True},
                    3: {"is_active": True},
                },
            }
            self.event.set_course(self.key, course_id, cdata)
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
        full_export = self.event.export_event(self.key, event_id=EventID(1))
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
        cascade = self.event.delete_course_blockers(self.key, course_id=CourseID(2))
        self.event.delete_course(self.key, course_id=CourseID(2), cascade=cascade)

        # Check that the remaining three course choices have been moved up.
        full_export = self.event.export_event(self.key, event_id=EventID(1))
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
        partial_export = self.event.partial_export_event(self.key, event_id=EventID(1))
        self.assertEqual(
            [1, 3, 4], partial_export["registrations"][1]["tracks"][1]["choices"]
        )

    @as_users("annika", "garcia", maintain_data=True)
    def test_visible_events(self) -> None:
        rs = self.event.get_rs(self.key)  # type: ignore[attr-defined]
        expectation = {
            1: 'Große Testakademie 2222',
            3: 'CyberTestAkademie',
            4: 'TripelAkademie',
        }
        event_ids = self.event.list_events(self.key, archived=False)
        events = self.event.get_events(self.key, event_ids)
        visible_events = {
            event.id: event.title for event in events.values() if event.is_visible
        }
        my_visible_events = {
            event.id: event.title
            for event in events.values()
            if event.is_visible_for(rs.user, False, privileged=False)
        }
        self.assertEqual(expectation, visible_events)
        self.assertEqual(expectation, my_visible_events)
        total_registration = {
            event.id: event.title
            for event in events.values()
            if event.is_visible_for(rs.user, True, privileged=False)
        }
        self.assertEqual(event_ids, total_registration)

    @as_users("annika", "garcia", maintain_data=True)
    def test_has_registrations(self) -> None:
        self.assertTrue(self.event.has_registrations(self.key, EventID(1)))

    @as_users("emilia")
    def test_registration_participant(self) -> None:
        expectation: CdEDBObject = {
            'age': AgeClasses.full,
            'amount_paid': decimal.Decimal("0.00"),
            'amount_owed': decimal.Decimal("466.49"),
            'remaining_owed': decimal.Decimal("466.49"),
            'amount_owed_by_kind': {
                const.EventFeeType.common: decimal.Decimal("461.49"),
                const.EventFeeType.external: decimal.Decimal("5.00"),
            },
            'amount_owed_by_category': {
                const.EventFeeCategory.participation_fee: decimal.Decimal("466.49"),
            },
            'amount_owed_by_budget': {
                const.EventFeeBudget.expenses: decimal.Decimal("461.49"),
                const.EventFeeBudget.cde: decimal.Decimal("5.00"),
            },
            'checkin_periods': [],
            'ctime': nearly_now(),
            'event_id': 1,
            'fields': {
                'lodge': '015112345678',
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
                    'age': AgeClasses.full,
                    'is_camping_mat': False,
                    'lodgement_id': None,
                    'part_id': 1,
                    'registration_id': 2,
                    'status': 3,
                },
                2: {
                    'age': AgeClasses.full,
                    'is_camping_mat': False,
                    'lodgement_id': 4,
                    'part_id': 2,
                    'registration_id': 2,
                    'status': 4,
                },
                3: {
                    'age': AgeClasses.full,
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
            'payment': None,
            'persona_id': 5,
            'real_persona_id': None,
        }
        self.assertEqual(
            expectation, self.event.get_registration(self.key, RegistrationID(2))
        )
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
        self.assertEqual(
            expectation, self.event.get_registration(self.key, RegistrationID(2))
        )

    @as_users("berta", "paul")
    def test_registering(self) -> None:
        new_reg: CdEDBObject = {
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
            'real_persona_id': None,
        }
        # try to create a registration for paul
        if self.user_in('paul'):
            new_id = self.event.create_registration(self.key, new_reg)
            self.assertLess(0, new_id)
            new_reg['id'] = new_id
            # amount_owed include non-member additional fee
            new_reg['amount_owed'] = new_reg['remaining_owed'] = decimal.Decimal(
                "589.48"
            )
            new_reg['amount_owed_by_kind'] = {
                const.EventFeeType.common: decimal.Decimal("584.49"),
                const.EventFeeType.solidary_reduction: decimal.Decimal("-0.01"),
                const.EventFeeType.external: decimal.Decimal("5.00"),
            }
            new_reg['amount_owed_by_category'] = {
                const.EventFeeCategory.participation_fee: decimal.Decimal("589.48"),
            }
            new_reg['amount_owed_by_budget'] = {
                const.EventFeeBudget.expenses: decimal.Decimal("584.49"),
                const.EventFeeBudget.solidarity: decimal.Decimal("-0.01"),
                const.EventFeeBudget.cde: decimal.Decimal("5.00"),
            }
            new_reg['amount_paid'] = decimal.Decimal("0.00")
            new_reg['age'] = AgeClasses.full
            new_reg['payment'] = None
            new_reg['personalized_fees'] = {}
            new_reg['is_member'] = False
            new_reg['fields'] = {}
            new_reg['parts'][1]['part_id'] = 1
            new_reg['parts'][1]['registration_id'] = new_id
            new_reg['parts'][1]['age'] = AgeClasses.full
            new_reg['parts'][2]['part_id'] = 2
            new_reg['parts'][2]['registration_id'] = new_id
            new_reg['parts'][2]['age'] = AgeClasses.full
            new_reg['parts'][3]['part_id'] = 3
            new_reg['parts'][3]['registration_id'] = new_id
            new_reg['parts'][3]['age'] = AgeClasses.full
            new_reg['tracks'][1]['track_id'] = 1
            new_reg['tracks'][1]['registration_id'] = new_id
            new_reg['tracks'][2]['track_id'] = 2
            new_reg['tracks'][2]['registration_id'] = new_id
            new_reg['tracks'][2]['choices'] = []
            new_reg['tracks'][3]['track_id'] = 3
            new_reg['tracks'][3]['registration_id'] = new_id
            new_reg['tracks'][3]['choices'] = []
            new_reg['checkin_periods'] = []
            new_reg['ctime'] = nearly_now()
            new_reg['mtime'] = None
            self.assertEqual(new_reg, self.event.get_registration(self.key, new_id))
        else:
            with self.assertRaises(PrivilegeError):
                self.event.create_registration(self.key, new_reg)

    @as_users("annika", "garcia")
    def test_entity_registration(self) -> None:
        event_id = EventID(1)
        self.assertEqual(
            {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2},
            self.event.list_registrations(self.key, event_id),
        )
        expectation: CdEDBObjectMap = {
            1: {
                'age': AgeClasses.full,
                'amount_owed': decimal.Decimal("553.99"),
                'amount_owed_by_kind': {
                    const.EventFeeType.common: decimal.Decimal("573.99"),
                    const.EventFeeType.instructor_refund: decimal.Decimal("-20.00"),
                },
                'amount_owed_by_category': {
                    const.EventFeeCategory.participation_fee: decimal.Decimal("573.99"),
                    const.EventFeeCategory.reimbursement: decimal.Decimal("-20.00"),
                },
                'amount_owed_by_budget': {
                    const.EventFeeBudget.expenses: decimal.Decimal("553.99"),
                },
                'amount_paid': decimal.Decimal("200.00"),
                'remaining_owed': decimal.Decimal("353.99"),
                'checkin_periods': [],
                'ctime': nearly_now(),
                'event_id': 1,
                'fields': {
                    'anzahl_GROSSBUCHSTABEN': 4,
                    'arrival_at': datetime.datetime(2022, 2, 2, 9, tzinfo=datetime.UTC),
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
                        'age': AgeClasses.full,
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 1,
                        'status': const.RegistrationPartStati.not_applied,
                    },
                    2: {
                        'age': AgeClasses.full,
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 1,
                        'status': const.RegistrationPartStati.applied,
                    },
                    3: {
                        'age': AgeClasses.full,
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
                'payment': datetime.date(2014, 1, 1),
                'persona_id': 1,
                'real_persona_id': None,
            },
            2: {
                'age': AgeClasses.full,
                'amount_owed': decimal.Decimal("466.49"),
                'amount_owed_by_kind': {
                    const.EventFeeType.common: decimal.Decimal("461.49"),
                    const.EventFeeType.external: decimal.Decimal("5.00"),
                },
                'amount_owed_by_category': {
                    const.EventFeeCategory.participation_fee: decimal.Decimal("466.49"),
                },
                'amount_owed_by_budget': {
                    const.EventFeeBudget.expenses: decimal.Decimal("461.49"),
                    const.EventFeeBudget.cde: decimal.Decimal("5.00"),
                },
                'amount_paid': decimal.Decimal("0.00"),
                'remaining_owed': decimal.Decimal("466.49"),
                'checkin_periods': [],
                'ctime': nearly_now(),
                'event_id': 1,
                'fields': {
                    'lodge': '015112345678',
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
                        'age': AgeClasses.full,
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 2,
                        'status': const.RegistrationPartStati.waitlist,
                    },
                    2: {
                        'age': AgeClasses.full,
                        'is_camping_mat': False,
                        'lodgement_id': 4,
                        'part_id': 2,
                        'registration_id': 2,
                        'status': const.RegistrationPartStati.guest,
                    },
                    3: {
                        'age': AgeClasses.full,
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
                'payment': None,
                'persona_id': 5,
                'real_persona_id': None,
            },
            4: {
                'age': AgeClasses.u10,
                'amount_owed': decimal.Decimal("431.99"),
                'amount_owed_by_kind': {
                    const.EventFeeType.common: decimal.Decimal("431.99"),
                },
                'amount_owed_by_category': {
                    const.EventFeeCategory.participation_fee: decimal.Decimal("431.99"),
                },
                'amount_owed_by_budget': {
                    const.EventFeeBudget.expenses: decimal.Decimal("431.99"),
                },
                'amount_paid': decimal.Decimal("548.48"),
                'remaining_owed': decimal.Decimal("-116.49"),
                'checkin_periods': [],
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
                        'age': AgeClasses.u10,
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 1,
                        'registration_id': 4,
                        'status': const.RegistrationPartStati.rejected,
                    },
                    2: {
                        'age': AgeClasses.u10,
                        'is_camping_mat': False,
                        'lodgement_id': None,
                        'part_id': 2,
                        'registration_id': 4,
                        'status': const.RegistrationPartStati.cancelled,
                    },
                    3: {
                        'age': AgeClasses.u10,
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
        self.assertEqual(
            expectation,
            self.event.get_registrations(
                self.key, (RegistrationID(1), RegistrationID(2), RegistrationID(4))
            ),
        )
        data: CdEDBObject = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
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
        expectation[4]['mtime'] = nearly_now()
        expectation[4]['amount_owed'] = decimal.Decimal("5.50")
        expectation[4]['amount_owed_by_kind'][const.EventFeeType.common] = (
            decimal.Decimal("5.50")
        )
        expectation[4]['amount_owed_by_category'][
            const.EventFeeCategory.participation_fee
        ] = decimal.Decimal("5.50")
        expectation[4]['amount_owed_by_budget'][const.EventFeeBudget.expenses] = (
            decimal.Decimal("5.50")
        )
        expectation[4]['remaining_owed'] = (
            expectation[4]['amount_owed'] - expectation[4]['amount_paid']
        )
        for key, value in expectation[4]['parts'].items():
            if key in data['parts']:
                value.update(data['parts'][key])
        for key, value in expectation[4]['tracks'].items():
            if key in data['tracks']:
                value.update(data['tracks'][key])
        regs = self.event.get_registrations(
            self.key, (RegistrationID(1), RegistrationID(2), RegistrationID(4))
        )
        self.assertEqual(expectation, regs)
        new_reg: CdEDBObject = {
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
        self.assertIn("This user does not exist or is archived.", cm.exception.args)
        new_reg['persona_id'] = 8
        with self.assertRaises(ValueError) as cm:
            self.event.create_registration(self.key, new_reg)
        self.assertIn("This user does not exist or is archived.", cm.exception.args)
        new_reg['persona_id'] = 11
        with self.assertRaises(ValueError) as cm:
            self.event.create_registration(self.key, new_reg)
        self.assertIn("This user is not an event user.", cm.exception.args)

        new_reg['persona_id'] = 3
        new_id = self.event.create_registration(self.key, new_reg)
        self.assertLess(0, new_id)
        new_reg['id'] = new_id
        new_reg['amount_owed'] = new_reg['remaining_owed'] = decimal.Decimal("584.48")
        new_reg['amount_owed_by_kind'] = {
            const.EventFeeType.common: decimal.Decimal("584.49"),
            const.EventFeeType.solidary_reduction: decimal.Decimal("-0.01"),
        }
        new_reg['amount_owed_by_category'] = {
            const.EventFeeCategory.participation_fee: decimal.Decimal("584.48"),
        }
        new_reg['amount_owed_by_budget'] = {
            const.EventFeeBudget.expenses: decimal.Decimal("584.49"),
            const.EventFeeBudget.solidarity: decimal.Decimal("-0.01"),
        }
        new_reg['amount_paid'] = decimal.Decimal("0.00")
        new_reg['age'] = AgeClasses.full
        new_reg['payment'] = None
        new_reg['personalized_fees'] = {}
        new_reg['is_member'] = True
        new_reg['fields'] = {}
        new_reg['parts'][1]['part_id'] = 1
        new_reg['parts'][1]['registration_id'] = new_id
        new_reg['parts'][1]['is_camping_mat'] = False
        new_reg['parts'][1]['age'] = AgeClasses.full
        new_reg['parts'][2]['part_id'] = 2
        new_reg['parts'][2]['registration_id'] = new_id
        new_reg['parts'][2]['is_camping_mat'] = False
        new_reg['parts'][2]['age'] = AgeClasses.full
        new_reg['parts'][3]['part_id'] = 3
        new_reg['parts'][3]['registration_id'] = new_id
        new_reg['parts'][3]['is_camping_mat'] = False
        new_reg['parts'][3]['age'] = AgeClasses.full
        new_reg['tracks'][1]['track_id'] = 1
        new_reg['tracks'][1]['registration_id'] = new_id
        new_reg['tracks'][2]['track_id'] = 2
        new_reg['tracks'][2]['registration_id'] = new_id
        new_reg['tracks'][2]['choices'] = []
        new_reg['tracks'][3]['track_id'] = 3
        new_reg['tracks'][3]['registration_id'] = new_id
        new_reg['tracks'][3]['choices'] = []
        new_reg['checkin_periods'] = []
        new_reg['ctime'] = nearly_now()
        new_reg['mtime'] = None
        self.assertEqual(new_reg, self.event.get_registration(self.key, new_id))
        self.assertEqual(
            {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2, new_id: 3},
            self.event.list_registrations(self.key, event_id),
        )

    @as_users("annika", "garcia")
    def test_registration_delete(self) -> None:
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(
            expectation, self.event.list_registrations(self.key, EventID(1))
        )
        with self.assertRaises(ValueError):
            self.event.delete_registration(
                self.key,
                RegistrationID(1),
                ("registration_parts", "registration_tracks", "course_choices"),
            )
        del expectation[1]
        for reg_id in [RegistrationID(2), RegistrationID(3), RegistrationID(5)]:
            self.assertLess(
                0,
                self.event.delete_registration(
                    self.key,
                    reg_id,
                    ("registration_parts", "registration_tracks", "course_choices"),
                ),
            )
        self.assertEqual(
            {1: 1, 4: 9, 6: 2},
            self.event.list_registrations(self.key, EventID(1)),
        )

    @as_users("annika", "garcia")
    def test_course_filtering(self) -> None:
        event_id = EventID(1)
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(
            expectation, self.event.registrations_by_course(self.key, event_id)
        )
        self.assertEqual(
            {},
            self.event.registrations_by_course(
                self.key,
                event_id,
                position=InfiniteEnum(CourseFilterPositions.specific_rank, 1),
            ),
        )
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100}
        self.assertEqual(
            expectation,
            self.event.registrations_by_course(self.key, event_id, track_id=3),
        )
        expectation = {1: 1, 2: 5, 3: 7, 4: 9, 5: 100, 6: 2}
        self.assertEqual(
            expectation,
            self.event.registrations_by_course(
                self.key, event_id, course_id=CourseID(1)
            ),
        )
        expectation = {2: 5, 4: 9, 5: 100}
        self.assertEqual(
            expectation,
            self.event.registrations_by_course(
                self.key,
                event_id,
                course_id=CourseID(1),
                position=InfiniteEnum(CourseFilterPositions.assigned, 0),
            ),
        )

    @storage
    @as_users("garcia")
    def test_entity_lodgement_group(self) -> None:
        event_id = EventID(1)

        expectation_groups = {
            1: models.LodgementGroup(
                id=LodgementGroupID(1),
                event_id=event_id,
                title="Haupthaus",
                lodgement_ids={LodgementID(2), LodgementID(4)},
                camping_mat_capacity=2,
                regular_capacity=11,
            ),
            2: models.LodgementGroup(
                id=LodgementGroupID(2),
                event_id=event_id,
                title="AußenWohnGruppe",
                lodgement_ids={LodgementID(1)},
                camping_mat_capacity=1,
                regular_capacity=5,
            ),
            3: models.LodgementGroup(
                id=LodgementGroupID(3),
                event_id=event_id,
                title="Sonstige",
                lodgement_ids={LodgementID(3)},
                camping_mat_capacity=100,
                regular_capacity=0,
            ),
        }
        self.assertEqual(
            expectation_groups, self.event.get_lodgement_groups(self.key, event_id)
        )

        new_group: CdEDBObject = {'title': "Nebenan"}
        new_group_id = self.event.create_lodgement_group(self.key, event_id, new_group)
        self.assertLess(0, new_group_id)
        new_group.update({
            'id': new_group_id,
            'event_id': event_id,
            'lodgement_ids': set(),
            'camping_mat_capacity': 0,
            'regular_capacity': 0,
        })
        self.assertEqual(
            models.LodgementGroup(**new_group),
            self.event.get_lodgement_groups(self.key, event_id)[new_group_id],
        )
        update = {'title': "Auf der anderen Rheinseite"}
        self.assertLess(
            0, self.event.set_lodgement_group(self.key, new_group_id, update)
        )
        new_group.update(update)
        self.assertEqual(
            models.LodgementGroup(**new_group),
            self.event.get_lodgement_groups(self.key, event_id)[new_group_id],
        )

        new_lodgement: CdEDBObject = {
            'regular_capacity': 42,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': new_group_id,
        }
        new_lodgement_id = self.event.create_lodgement(
            self.key, event_id, new_lodgement
        )
        self.assertLess(0, new_lodgement_id)
        new_lodgement['id'] = new_lodgement_id
        new_lodgement['event_id'] = event_id
        new_lodgement['fields'] = {}
        self.assertEqual(
            new_lodgement,
            self.event.new_get_lodgement(self.key, new_lodgement_id).as_dict(),
        )

        new_group.update({
            'camping_mat_capacity': new_lodgement['camping_mat_capacity'],
            'regular_capacity': new_lodgement['regular_capacity'],
            'lodgement_ids': {new_lodgement_id},
        })
        self.assertEqual(
            models.LodgementGroup(**new_group),
            self.event.get_lodgement_groups(self.key, event_id)[new_group_id],
        )

        expectation_groups[new_group_id] = models.LodgementGroup(**new_group)
        self.assertEqual(
            expectation_groups, self.event.get_lodgement_groups(self.key, event_id)
        )
        self.assertLess(
            0,
            self.event.delete_lodgement_group(self.key, new_group_id, ("lodgements",)),
        )
        del expectation_groups[new_group_id]
        self.assertEqual(
            expectation_groups, self.event.get_lodgement_groups(self.key, event_id)
        )

        self.assertNotIn(
            new_lodgement_id, self.event.list_lodgements(self.key, event_id)
        )

        new_event_data = {
            'title': (new_event_title := "KreativAkademie"),
            'shortname': "KrAka",
            'institution': 1,
            'parts': {
                -1: {
                    'part_begin': "2222-02-02",
                    'part_end': "2222-02-22",
                    'title': "KreativAkademie",
                    'shortname': "KrAka",
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
            },
        }
        with self.switch_user("annika"):
            new_event_id = self.event.create_event(self.key, new_event_data)

        groups = self.event.get_lodgement_groups(self.key, new_event_id)
        groups_expectation = {
            1002: models.LodgementGroup(
                id=LodgementGroupID(1002),
                event_id=new_event_id,
                title=new_event_title,
            ),
        }
        self.assertEqual(groups_expectation, groups)

    @as_users("annika", "garcia")
    def test_entity_lodgement(self) -> None:
        event_id = EventID(1)
        expectation_list = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle',
        }
        self.assertEqual(
            expectation_list, self.event.list_lodgements(self.key, event_id)
        )
        expectation_get = {
            1: models.Lodgement(
                id=LodgementID(1),
                event_id=event_id,
                title='Warme Stube',
                group_id=LodgementGroupID(2),
                group=models.LodgementGroup(
                    id=LodgementGroupID(2),
                    event_id=event_id,
                    title="AußenWohnGruppe",
                    lodgement_ids={LodgementID(1)},
                    regular_capacity=5,
                    camping_mat_capacity=1,
                ),
                regular_capacity=vtypes.NonNegativeInt(5),
                camping_mat_capacity=vtypes.NonNegativeInt(1),
                notes=None,
                fields=vtypes.EventAssociatedFields({'contamination': 'high'}),
            ),
            4: models.Lodgement(
                id=LodgementID(4),
                event_id=event_id,
                title='Einzelzelle',
                group_id=LodgementGroupID(1),
                group=models.LodgementGroup(
                    id=LodgementGroupID(1),
                    event_id=event_id,
                    title="Haupthaus",
                    lodgement_ids={LodgementID(2), LodgementID(4)},
                    regular_capacity=11,
                    camping_mat_capacity=2,
                ),
                regular_capacity=vtypes.NonNegativeInt(1),
                camping_mat_capacity=vtypes.NonNegativeInt(0),
                notes=None,
                fields=vtypes.EventAssociatedFields({'contamination': 'high'}),
            ),
        }
        self.assertEqual(
            expectation_get, self.event.new_get_lodgements(self.key, (1, 4))
        )
        new: CdEDBObject = {
            'regular_capacity': 42,
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': 3,
        }
        new_id = self.event.create_lodgement(self.key, event_id, new)
        self.assertLess(0, new_id)
        new['id'] = new_id
        new['event_id'] = event_id
        new['fields'] = {}
        self.assertEqual(new, self.event.new_get_lodgement(self.key, new_id).as_dict())
        update = {
            'regular_capacity': 21,
            'notes': None,
        }
        self.assertLess(0, self.event.set_lodgement(self.key, new_id, update))
        new.update(update)
        self.assertEqual(new, self.event.new_get_lodgement(self.key, new_id).as_dict())
        expectation_list = {
            1: 'Warme Stube',
            2: 'Kalte Kammer',
            3: 'Kellerverlies',
            4: 'Einzelzelle',
            new_id: 'HY',
        }
        self.assertEqual(
            expectation_list, self.event.list_lodgements(self.key, event_id)
        )
        self.assertLess(0, self.event.delete_lodgement(self.key, new_id))
        del expectation_list[new_id]
        self.assertLess(
            0,
            self.event.delete_lodgement(
                self.key, LodgementID(1), cascade={"inhabitants"}
            ),
        )
        del expectation_list[1]
        self.assertEqual(
            expectation_list, self.event.list_lodgements(self.key, event_id)
        )

    @as_users("berta", "emilia", maintain_data=True)
    def test_get_all_questionnaires(self) -> None:
        event_id = EventID(1)
        expectation = models.questionnaire.QuestionnaireContainer({
            const.QuestionnaireUsages.registration: models.questionnaire.Questionnaire(
                [
                    models.questionnaire.MyData(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=0,
                        role=const.QuestionnaireRowRole.my_data,
                    ),
                    models.questionnaire.PartSelection(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=1,
                        role=const.QuestionnaireRowRole.part_selection,
                    ),
                    models.questionnaire.FeePreview(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=2,
                        role=const.QuestionnaireRowRole.fee_preview,
                    ),
                    models.questionnaire.CourseChoices(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=3,
                        role=const.QuestionnaireRowRole.course_choices,
                    ),
                    models.questionnaire.QuestionnaireHeadingRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=4,
                        role=const.QuestionnaireRowRole.heading,
                        title="Weitere Angaben",
                        text=None,
                    ),
                    models.questionnaire.ListConsent(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=5,
                        role=const.QuestionnaireRowRole.list_consent,
                    ),
                    models.questionnaire.QuestionnaireFieldRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=6,
                        role=const.QuestionnaireRowRole.event_field,
                        field_id=vtypes.ID(7),
                        label="Ich bin unter 13 Jahre alt.",
                        info="Denk daran, deine Eltern mitzubringen!",
                    ),
                    models.questionnaire.MixedLodging(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=7,
                        role=const.QuestionnaireRowRole.mixed_lodging,
                    ),
                    models.questionnaire.FotoNotice(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=8,
                        role=const.QuestionnaireRowRole.foto_notice,
                    ),
                    models.questionnaire.RegistrationNotes(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=9,
                        role=const.QuestionnaireRowRole.registration_notes,
                    ),
                    models.questionnaire.FeePreview(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.registration,
                        pos=10,
                        role=const.QuestionnaireRowRole.fee_preview,
                    ),
                ],
                kind=const.QuestionnaireUsages.registration,
            ),
            const.QuestionnaireUsages.additional: models.questionnaire.Questionnaire(
                [
                    models.questionnaire.QuestionnaireHeadingRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=0,
                        role=const.QuestionnaireRowRole.heading,
                        title="Unterüberschrift",
                        text=None,
                    ),
                    models.questionnaire.QuestionnaireTextRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=1,
                        role=const.QuestionnaireRowRole.text,
                        title=None,
                        text="mit Text darunter",
                    ),
                    models.questionnaire.QuestionnaireFieldRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=2,
                        role=const.QuestionnaireRowRole.event_field,
                        field_id=vtypes.ID(1),
                        label="Bälle",
                        info="Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.",
                        default_value=True,
                    ),
                    models.questionnaire.QuestionnaireTextRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=3,
                        role=const.QuestionnaireRowRole.text,
                        title=None,
                        text="nur etwas Text",
                    ),
                    models.questionnaire.QuestionnaireHeadingRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=4,
                        role=const.QuestionnaireRowRole.heading,
                        title="Weitere Überschrift",
                        text=None,
                    ),
                    models.questionnaire.QuestionnaireFieldRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=5,
                        role=const.QuestionnaireRowRole.event_field,
                        field_id=vtypes.ID(2),
                        label="Vehikel",
                        info=None,
                        default_value="etc",
                    ),
                    models.questionnaire.QuestionnaireFieldRow(
                        event_id=vtypes.ID(1),
                        kind=const.QuestionnaireUsages.additional,
                        pos=6,
                        role=const.QuestionnaireRowRole.event_field,
                        field_id=vtypes.ID(3),
                        label="Hauswunsch",
                        info=None,
                    ),
                ],
                kind=const.QuestionnaireUsages.additional,
            ),
        })
        reality = self.event.get_all_questionnaires(self.key, event_id)
        self.assertEqual(expectation.as_dict(), reality.as_dict())
        self.assertEqual(expectation, reality)

    @as_users("annika", "garcia")
    def test_set_questionnaire(self) -> None:
        event_id = EventID(1)
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
        aq_data: list[CdEDBObject] = [
            {
                'role': const.QuestionnaireRowRole.heading,
                'text': None,
                'title': 'Weitere bla Überschrift',
                'panel_kind': None,
            },
            {
                'role': const.QuestionnaireRowRole.event_field,
                'label': 'Vehikel',
                'info': None,
                'field_id': 2,
                'readonly': True,
                'default_value': 'etc',
            },
            {
                'role': const.QuestionnaireRowRole.heading,
                'text': None,
                'title': 'Unterüberschrift',
                'panel_kind': None,
            },
            {
                'role': const.QuestionnaireRowRole.text,
                'text': 'mit Text darunter und so',
                'title': None,
                'panel_kind': None,
            },
            {
                'role': const.QuestionnaireRowRole.event_field,
                'label': 'Vehikel',
                'info': None,
                'field_id': 3,
                'readonly': True,
                'default_value': None,
            },
            {
                'role': const.QuestionnaireRowRole.text,
                'text': 'nur etwas mehr Text',
                'title': None,
                'panel_kind': None,
            },
        ]
        self.assertLess(
            0,
            self.event.set_questionnaire(
                self.key, event_id, const.QuestionnaireUsages.additional, aq_data
            ),
        )
        rq_data: list[CdEDBObject] = [
            {
                'role': const.QuestionnaireRowRole.my_data,
            },
            {
                'role': const.QuestionnaireRowRole.part_selection,
            },
            {
                'role': const.QuestionnaireRowRole.course_choices,
            },
            {
                'role': const.QuestionnaireRowRole.event_field,
                'label': "Ich möchte den Solidaritätszuschlag bezahlen.",
                'info': "Du kannst freiwillig etwas mehr bezahlen um zukünftige Akademien zu unterstützen.",
                'field_id': 1001,
                'readonly': False,
                'default_value': None,
            },
            {
                'role': const.QuestionnaireRowRole.fee_preview,
            },
            {
                'role': const.QuestionnaireRowRole.list_consent,
            },
            {
                'role': const.QuestionnaireRowRole.mixed_lodging,
            },
        ]
        with self.assertRaisesRegex(ValueError, "Missing role:"):
            self.event.set_questionnaire(
                self.key, event_id, const.QuestionnaireUsages.registration, rq_data
            )
        rq_data.append({'role': const.QuestionnaireRowRole.foto_notice})
        self.assertLess(
            0,
            self.event.set_questionnaire(
                self.key, event_id, const.QuestionnaireUsages.registration, rq_data
            ),
        )
        for pos, row in enumerate(aq_data):
            row['pos'] = pos
            row['kind'] = const.QuestionnaireUsages.additional
        for pos, row in enumerate(rq_data):
            row['pos'] = pos
            row['kind'] = const.QuestionnaireUsages.registration
        result = self.event.get_all_questionnaires(self.key, event_id)
        expectation = {
            const.QuestionnaireUsages.additional: aq_data,
            const.QuestionnaireUsages.registration: rq_data,
        }
        self.assertEqual(expectation, result.as_dict())

    @as_users("annika", "garcia")
    def test_registration_query(self) -> None:
        scope = QueryScope.registration
        query = Query(
            scope=scope,
            spec=scope.get_spec(event=self.event.get_event(self.key, EventID(1))),
            fields_of_interest=(
                "reg.id",
                "reg.payment",
                "is_cde_realm",
                "persona.family_name",
                "birthday",
                "lodgement1.id",
                "part3.status",
                "course2.id",
                "course1.xfield_room",
                "lodgement2.xfield_contamination",
                "reg_fields.xfield_brings_balls",
                "reg_fields.xfield_transportation",
            ),
            constraints=[
                ("reg.id", QueryOperators.nonempty, None),
                ("persona.given_names", QueryOperators.regex, '[aeiou]'),
                ("part2.status", QueryOperators.nonempty, None),
                (
                    "reg_fields.xfield_transportation",
                    QueryOperators.oneof,
                    ['pedes', 'etc'],
                ),
            ],
            order=(("reg.id", True),),
        )

        result = self.event.submit_general_query(self.key, query, event_id=EventID(1))
        expectation = (
            {
                'birthday': datetime.date(2012, 6, 2),
                'reg_fields.xfield_brings_balls': True,
                'lodgement2.xfield_contamination': 'high',
                'course2.id': None,
                'persona.family_name': 'Eventis',
                'reg.id': 2,
                'lodgement1.id': None,
                'reg.payment': None,
                'is_cde_realm': False,
                'course1.xfield_room': None,
                'part3.status': 2,
                'reg_fields.xfield_transportation': 'pedes',
            },
            {
                'birthday': datetime.date(2222, 1, 1),
                'reg_fields.xfield_brings_balls': False,
                'lodgement2.xfield_contamination': None,
                'course2.id': None,
                'persona.family_name': 'Iota',
                'reg.id': 4,
                'lodgement1.id': None,
                'reg.payment': datetime.date(2014, 4, 4),
                'is_cde_realm': True,
                'course1.xfield_room': None,
                'part3.status': 2,
                'reg_fields.xfield_transportation': 'etc',
            },
            {
                'birthday': datetime.date(2019, 12, 28),
                'course1.xfield_room': None,
                'course2.id': 2,
                'is_cde_realm': True,
                'lodgement1.id': 4,
                'lodgement2.xfield_contamination': 'high',
                'part3.status': 2,
                'persona.family_name': 'Abukara',
                'reg.id': 5,
                'reg.payment': None,
                'reg_fields.xfield_brings_balls': None,
                'reg_fields.xfield_transportation': 'pedes',
            },
            {
                'birthday': datetime.date(1981, 2, 11),
                'course1.xfield_room': None,
                'course2.id': None,
                'is_cde_realm': True,
                'lodgement1.id': None,
                'lodgement2.xfield_contamination': None,
                'part3.status': -1,
                'persona.family_name': 'Beispiel',
                'reg.id': 6,
                'reg.payment': datetime.date(2014, 6, 6),
                'reg_fields.xfield_brings_balls': None,
                'reg_fields.xfield_transportation': 'pedes',
            },
        )
        self.assertEqual(expectation, result)

    @as_users("annika")
    def test_queries_without_fields(self) -> None:
        # Check that the query views work if there are no custom fields.
        event = self.event.get_event(self.key, EventID(3))
        self.assertFalse(event.fields)
        query = Query(
            scope=QueryScope.registration,
            spec=QueryScope.registration.get_spec(event=event),
            fields_of_interest=["reg.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=EventID(2))
        self.assertEqual(tuple(), result)
        query = Query(
            scope=QueryScope.event_course,
            spec=QueryScope.event_course.get_spec(event=event),
            fields_of_interest=["course.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=EventID(2))
        self.assertEqual(tuple(), result)
        query = Query(
            scope=QueryScope.lodgement,
            spec=QueryScope.lodgement.get_spec(event=event),
            fields_of_interest=["lodgement.id"],
            constraints=[],
            order=[],
        )
        result = self.event.submit_general_query(self.key, query, event_id=EventID(2))
        self.assertEqual(tuple(), result)

    @as_users("garcia")
    def test_lodgement_query(self) -> None:
        query = Query(
            scope=QueryScope.lodgement,
            spec=QueryScope.lodgement.get_spec(
                event=self.event.get_event(self.key, EventID(1))
            ),
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
        result = self.event.submit_general_query(self.key, query, event_id=EventID(1))
        expectation = (
            {
                'lodgement.id': 4,
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
                'lodgement.id': 2,
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
                event=self.event.get_event(self.key, EventID(1))
            ),
            fields_of_interest=[
                "course.id",
                "track1.attendees",
                "track2.is_offered",
                "track3.num_choices1",
                "track3.instructors",
                "course_fields.xfield_room",
            ],
            constraints=[],
            order=[
                ("course.max_size", True),
                ("course.id", True),
            ],
        )
        result = self.event.submit_general_query(self.key, query, event_id=EventID(1))
        expectation = (
            {
                'course.id': 1,
                'course_fields.xfield_room': 'Wald',
                'course.max_size': 10,
                'track1.attendees': 0,
                'track2.is_offered': False,
                'track3.instructors': 1,
                'track3.num_choices1': 0,
            },
            {
                'course.id': 3,
                'course_fields.xfield_room': 'Seminarraum 42',
                'course.max_size': 14,
                'track1.attendees': 0,
                'track3.instructors': 0,
                'track2.is_offered': True,
                'track3.num_choices1': 0,
            },
            {
                'course.id': 2,
                'course_fields.xfield_room': 'Theater',
                'course.max_size': 20,
                'track1.attendees': 0,
                'track2.is_offered': True,
                'track3.instructors': 0,
                'track3.num_choices1': 2,
            },
            {
                'course.id': 4,
                'course_fields.xfield_room': 'Seminarraum 23',
                'course.max_size': None,
                'track1.attendees': 0,
                'track2.is_offered': True,
                'track3.instructors': 0,
                'track3.num_choices1': 3,
            },
            {
                'course.id': 5,
                'course_fields.xfield_room': 'Nirwana',
                'course.max_size': None,
                'track1.attendees': 0,
                'track2.is_offered': True,
                'track3.instructors': 0,
                'track3.num_choices1': 0,
            },
            {
                'course.id': 13,
                'course_fields.xfield_room': None,
                'course.max_size': None,
                'track1.attendees': 0,
                'track2.is_offered': True,
                'track3.instructors': 0,
                'track3.num_choices1': 0,
            },
        )
        self.assertEqual(expectation, result)

        # Query with one text column as foi, constraint and order to test aliasing.
        query = Query(
            scope=QueryScope.event_course,
            spec=QueryScope.event_course.get_spec(
                event=self.event.get_event(self.key, EventID(1))
            ),
            fields_of_interest=[
                "course.title",
            ],
            constraints=[
                ("course.title", QueryOperators.nonempty, None),
            ],
            order=[
                ("course.title", True),
            ],
        )
        result = self.event.submit_general_query(self.key, query, event_id=EventID(1))
        self.assertEqual({'course.id': 5, 'course.title': "Backup-Kurs"}, result[0])

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
                event=self.event.get_event(self.key, EventID(1))
            ),
            fields_of_interest=("reg.id", "track1.is_course_instructor"),
            constraints=[],
            order=(("reg.id", True),),
        )

        result = self.event.submit_general_query(self.key, query, event_id=EventID(1))
        expectation = (
            {
                "reg.id": 1,
                "track1.is_course_instructor": True,
            },
            {
                "reg.id": 2,
                "track1.is_course_instructor": None,
            },
            {
                "reg.id": 3,
                "track1.is_course_instructor": False,
            },
            {
                "reg.id": 4,
                "track1.is_course_instructor": None,
            },
            {
                "reg.id": 5,
                'track1.is_course_instructor': None,
            },
            {
                "reg.id": 6,
                'track1.is_course_instructor': None,
            },
        )
        self.assertEqual(expectation, result)

    @as_users("garcia")
    def test_store_event_query(self) -> None:
        event_id = EventID(1)
        event = self.event.get_event(self.key, event_id)

        def store(query: Query, name: str) -> int:
            query.query_id = self.event.store_event_query(
                self.key,
                event_id,
                query.scope,
                {"query_name": name, "serialized_query": query.serialize()},
            )
            return query.query_id

        # Try storing valid queries.
        expectation = {}
        query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=[
                "persona.family_name",
                "reg.payment",
                "ctime.creation_time",
                "part1.status",
                "course2.title",
                "lodgement3.title",
                "reg_fields.xfield_brings_balls",
            ],
            constraints=[],
            order=[],
        )
        name = "My registration query :)"
        store(query, name)
        expectation[name] = query
        query = Query(
            QueryScope.lodgement,
            QueryScope.lodgement.get_spec(event=event),
            fields_of_interest=[
                "lodgement.title",
                "lodgement_group.title",
                "part1.total_inhabitants",
                "lodgement_fields.xfield_contamination",
            ],
            constraints=[],
            order=[],
        )
        name = "Lodgement Query with funny symbol: 🏠"
        store(query, name)
        expectation[name] = query
        query = Query(
            QueryScope.event_course,
            QueryScope.event_course.get_spec(event=event),
            fields_of_interest=[
                "course.title",
                "track1.is_offered",
                "course_fields.xfield_room",
            ],
            constraints=[],
            order=[],
        )
        name = "custom_course_query"
        store(query, name)
        expectation[name] = query

        queries = self.event.get_event_queries(self.key, event_id)
        for stored_query in queries.values():
            name, query = stored_query.query_name, stored_query.query
            assert query is not None
            if name != "Test-Query":
                self.assertIn(name, expectation)
                q = expectation[name]
                self.assertEqual(
                    set(q.fields_of_interest), set(query.fields_of_interest)
                )
                self.assertEqual(set(q.constraints), set(query.constraints))
                self.assertEqual(set(q.order), set(query.order))
                self.assertEqual(q.query_id, query.query_id)
            assert query.query_id is not None
            self.assertTrue(self.event.delete_event_query(self.key, query.query_id))
        self.assertEqual({}, self.event.get_event_queries(self.key, event_id))

        # Now try some invalid things.
        query = Query(
            None,  # type: ignore[arg-type]
            {},
            fields_of_interest=[],
            constraints=[],
            order=[],
        )
        name = ""
        with self.assertRaises(ValueError) as cm:
            store(query, name)
        self.assertEqual(
            "Invalid input for the enumeration 'QueryScope'. (scope)",
            cm.exception.args[0] % cm.exception.args[1],
        )

        query.scope = QueryScope.persona
        with self.assertRaises(ValueError) as cm:
            store(query, name)
        self.assertIn("Cannot store this kind of query.", cm.exception.args)

        query.scope = QueryScope.registration
        with self.assertRaises(ValueError) as cm:
            store(query, name)
        self.assertIn("Must not be empty. (query_name)", cm.exception.args)

        name = "test"
        with self.assertRaises(ValueError) as cm:
            store(query, name)
        self.assertIn(
            "Selection may not be empty. (serialized_query)", cm.exception.args
        )

        query.fields_of_interest = ["persona.id"]
        self.assertTrue(store(query, name))

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
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            ["reg_fields.xfield_foo"],
            [("reg_fields.xfield_foo", QueryOperators.equal, "foo")],
            [],
        )
        name = "foo_string"
        query_id = store(query, name)
        self.assertIn(query.query_id, self.event.get_event_queries(self.key, event_id))

        # Now change the datatype of that field.
        field_data["kind"] = const.FieldDatatypes.date
        del field_data["field_name"]
        del field_data["association"]
        event_data["fields"] = {1001: field_data}
        self.event.set_event(self.key, event_id, event_data)

        # The query can no longer be retrieved.
        stored_query = self.event.get_event_queries(self.key, event_id)[query_id]
        self.assertIsNone(stored_query.query)
        self.assertTrue(stored_query.errors)

        # Change the field back.
        field_data["kind"] = const.FieldDatatypes.str
        self.event.set_event(self.key, event_id, event_data)

        # The query is valid again.
        self.assertIsNotNone(
            self.event.get_event_queries(self.key, event_id)[query_id].query
        )

    @event_keeper
    @as_users("annika", "garcia")
    def test_lock_unlock_event(self) -> None:
        event_id = EventID(1)
        offset, _ = self.event.retrieve_log(self.key, EventLogFilter(event_id=event_id))

        self.assertTrue(self.event.lock_event(self.key, event_id))
        self.assertTrue(self.event.get_event(self.key, event_id).is_locked)
        self.assertTrue(self.event.is_locked(self.key, event_id=event_id))
        with self.assertRaises(RuntimeError):
            self.event.assert_lock(self.key, event_id=event_id)
        self.assertTrue(self.event.unlock_event(self.key, event_id))
        self.assertFalse(self.event.get_event(self.key, event_id).is_locked)
        self.assertFalse(self.event.is_locked(self.key, event_id=event_id))

        self.assertLogEqual(
            [
                {
                    'code': const.EventLogCodes.event_locked,
                },
                {
                    'code': const.EventLogCodes.event_unlocked,
                },
            ],
            realm="event",
            event_id=event_id,
            offset=offset,
        )

    def cleanup_event_export(self, data: CdEDBObject) -> CdEDBObject:
        ret = json_keys_to_int(data)
        for k, v in ret.items():
            if isinstance(v, dict):
                ret[k] = self.cleanup_event_export(v)
            elif isinstance(v, list):
                for i, e in enumerate(v):
                    if isinstance(e, dict):
                        v[i] = self.cleanup_event_export(e)
                ret[k] = v
            elif isinstance(v, str):
                if k in {"balance", "amount_paid", "amount_owed", "amount"}:
                    ret[k] = decimal.Decimal(v)
                elif k in {"birthday", "payment", "part_begin", "part_end"}:
                    ret[k] = datetime.date.fromisoformat(v)
                elif k in {
                    "ctime",
                    "mtime",
                    "timestamp",
                    "registration_start",
                    "registration_soft_limit",
                    "registration_hard_limit",
                    "etime",
                    "rtime",
                    "atime",
                    "checkin_time",
                    "checkout_time",
                }:
                    ret[k] = datetime.datetime.fromisoformat(v)

        return ret

    @storage
    @as_users("annika", "garcia")
    def test_export_event(self) -> None:
        with open(self.testfile_dir / "event_export.json", encoding="utf-8") as f:
            expectation = self.cleanup_event_export(json.load(f))
        expectation['timestamp'] = nearly_now()
        expectation['EVENT_SCHEMA_VERSION'] = tuple(expectation['EVENT_SCHEMA_VERSION'])
        for log_entry in expectation['event.log'].values():
            log_entry['ctime'] = nearly_now()
        for token in expectation[OrgaToken.database_table].values():
            token['ctime'] = nearly_now()
        for reg in expectation['event.registrations'].values():
            for k in (
                "amount_owed_by_kind",
                "amount_owed_by_category",
                "amount_owed_by_budget",
            ):
                reg[k] = {str(key): val for key, val in reg[k].items()}
        self.assertEqual(expectation, self.event.export_event(self.key, EventID(1)))

    @storage
    @as_users("annika")
    def test_partial_export_event(self) -> None:
        with open(
            self.testfile_dir / "TestAka_partial_export_event.json",
            encoding="utf-8",
        ) as f:
            expectation = self.cleanup_event_export(json.load(f))
        expectation['timestamp'] = nearly_now()
        expectation['event']['caretakers'] = set(expectation['event']['caretakers'])
        expectation['event']['checkin_helpers'] = set(
            expectation['event']['checkin_helpers']
        )
        for reg in expectation['registrations'].values():
            reg['ctime'] = nearly_now()
            reg['mtime'] = None
            for fee_id, amount in reg['personalized_fees'].items():
                reg['personalized_fees'][fee_id] = decimal.Decimal(amount)
            for fee_kind, amount in reg['amount_owed_by_kind'].items():
                reg['amount_owed_by_kind'][fee_kind] = decimal.Decimal(amount)
            for fee_category, amount in reg['amount_owed_by_category'].items():
                reg['amount_owed_by_category'][fee_category] = decimal.Decimal(amount)
            for fee_budget, amount in reg['amount_owed_by_budget'].items():
                reg['amount_owed_by_budget'][fee_budget] = decimal.Decimal(amount)
        for token in expectation['event']['orga_tokens'].values():
            token['ctime'] = nearly_now()
        for reg in expectation['registrations'].values():
            if timestamp := reg['fields'].get('arrival_at'):
                reg['fields']['arrival_at'] = datetime.datetime.fromisoformat(timestamp)
        expectation['EVENT_SCHEMA_VERSION'] = tuple(expectation['EVENT_SCHEMA_VERSION'])
        export = self.event.partial_export_event(self.key, EventID(1))
        self.assertEqual(expectation, export)

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_event(self) -> None:
        event = self.event.get_event(self.key, EventID(1))
        previous = self.event.partial_export_event(self.key, EventID(1))
        with open(
            self.testfile_dir / "partial_event_import.json",
            encoding="utf-8",
        ) as datafile:
            data = json.load(datafile)
        self.assertEqual(
            (EVENT_SCHEMA_VERSION[0], 0),
            tuple(data["EVENT_SCHEMA_VERSION"]),
            "Partial Import should be tested with a minor version of 0.",
        )

        # first a test run
        token1, delta = self.event.partial_import_event(
            self.key,
            event.id,
            data,
            dryrun=True,
        )
        expectation = copy.deepcopy(delta)
        self.assertEqual(expectation, delta)
        # second check the token functionality
        with self.assertRaises(PartialImportError):
            self.event.partial_import_event(
                self.key,
                event.id,
                data,
                dryrun=False,
                token=token1 + "wrong",
            )
        # now for real
        token2, delta = self.event.partial_import_event(
            self.key,
            event.id,
            data,
            dryrun=False,
            token=token1,
        )
        self.assertEqual(token1, token2)

        updated = self.event.partial_export_event(self.key, EventID(1))
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

        def recursive_update(
            old: dict[Any, Any], new: dict[Any, Any], hint: str | None = None
        ) -> None:
            """Helper function to replace some placeholder values inside of a dict."""
            if hint == 'fields':
                new = cast_fields(new, event.fields)
            deletions = [key for key, val in new.items() if val is None and key in old]
            for key in deletions:
                if isinstance(old[key], collections.abc.Mapping) or hint == 'segments':
                    del old[key]
                    del new[key]
            recursions = [
                key
                for key, val in new.items()
                if isinstance(val, collections.abc.Mapping)
            ]
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
                        new[key] = [
                            cmap.get(('courses', anid), anid) for anid in new[key]
                        ]
            for key in ('lodgement_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = cmap.get(('lodgements', new[key]), new[key])
            for key in ('group_id',):
                if key in new:
                    if isinstance(new[key], int):
                        new[key] = cmap.get(('lodgement_groups', new[key]), new[key])
            for key in ('status',):
                if key in new:
                    new[key] = const.RegistrationPartStati(new[key])
            for key in ('checkin_periods',):
                if key in new:
                    for period in new[key]:
                        period['checkin_time'] = parse_datetime(period['checkin_time'])
                        if period['checkout_time']:
                            period['checkout_time'] = parse_datetime(
                                period['checkout_time']
                            )
            old.update(new)

        recursive_update(expectation, delta)
        del expectation['summary']
        del expectation['timestamp']
        del updated['timestamp']
        del updated['registrations'][1002]['persona']  # ignore additional info
        expectation['registrations'][1]['mtime'] = nearly_now()
        # amount_owed is recalculated
        expectation['registrations'][2]['amount_owed'] = decimal.Decimal("589.48")
        expectation['registrations'][2]['amount_owed_by_kind'] = {
            "common": decimal.Decimal("584.49"),
            "external": decimal.Decimal("5.00"),
            "solidary_reduction": decimal.Decimal("-0.01"),
        }
        expectation['registrations'][2]['amount_owed_by_category'] = {
            "participation_fee": decimal.Decimal("589.48"),
        }
        expectation['registrations'][2]['amount_owed_by_budget'] = {
            "expenses": decimal.Decimal("584.49"),
            "cde": decimal.Decimal("5.00"),
            "solidarity": decimal.Decimal("-0.01"),
        }
        expectation['registrations'][2]['mtime'] = nearly_now()
        expectation['registrations'][3]['mtime'] = nearly_now()
        expectation['registrations'][3]['amount_owed'] = decimal.Decimal("489.48")
        expectation['registrations'][3]['personalized_fees'][10] = decimal.Decimal(
            expectation['registrations'][3]['personalized_fees'][10],
        )
        expectation['registrations'][3]['amount_owed_by_kind'] = {
            "common": decimal.Decimal("534.49"),
            "instructor_refund": decimal.Decimal("-45.00"),
            "solidary_reduction": decimal.Decimal("-0.01"),
        }
        expectation['registrations'][3]['amount_owed_by_category'] = {
            "participation_fee": decimal.Decimal("534.48"),
            "reimbursement": decimal.Decimal("-45.00"),
        }
        expectation['registrations'][3]['amount_owed_by_budget'] = {
            "expenses": decimal.Decimal("489.49"),
            "solidarity": decimal.Decimal("-0.01"),
        }
        # add default values
        expectation['registrations'][1002]['amount_paid'] = decimal.Decimal('0.00')
        expectation['registrations'][1002]['payment'] = None
        expectation['registrations'][1002]['amount_owed'] = decimal.Decimal("573.99")
        expectation['registrations'][1002]['is_member'] = True
        expectation['registrations'][1002]['ctime'] = nearly_now()
        expectation['registrations'][1002]['mtime'] = None
        expectation['registrations'][1002]['personalized_fees'] = {}
        expectation['registrations'][1002]['amount_owed_by_kind'] = {
            "common": decimal.Decimal("573.99"),
        }
        expectation['registrations'][1002]['amount_owed_by_category'] = {
            "participation_fee": decimal.Decimal("573.99"),
        }
        expectation['registrations'][1002]['amount_owed_by_budget'] = {
            "expenses": decimal.Decimal("573.99"),
        }
        expectation['EVENT_SCHEMA_VERSION'] = EVENT_SCHEMA_VERSION
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
                'change_note': 'Kalte Kammer -> Kühle Kammer',
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
                'change_note': 'Planetenretten für Anfänger (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
            },
            {
                'change_note': 'Planetenretten für Anfänger (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
            },
            {
                'change_note': 'Planetenretten für Anfänger (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deactivated,
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
                'change_note': 'Langer Kurs (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deleted,
            },
            {
                'change_note': 'Langer Kurs (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deactivated,
            },
            {
                'change_note': 'Backup-Kurs (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deactivated,
            },
            {
                'change_note': 'Backup-Kurs (Arbeitssitzung (Zweite Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
            },
            {
                'change_note': 'Blitzkurs',
                'code': const.EventLogCodes.course_created,
            },
            {
                'change_note': 'Blitzkurs (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
            },
            {
                'change_note': 'Blitzkurs (Arbeitssitzung (Zweite Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
            },
            {
                'change_note': 'Blitzkurs (Arbeitssitzung (Zweite Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
            },
            {
                'change_note': 'Partieller Import: Sehr wichtiger Import',
                'code': const.EventLogCodes.registration_changed,
                'persona_id': 1,
            },
            {
                'change_note': '1.H.: Gast -> Teilnahme',
                'code': const.EventLogCodes.registration_status_changed,
                'persona_id': 5,
            },
            {
                'change_note': 'Partieller Import: Sehr wichtiger Import',
                'code': const.EventLogCodes.registration_changed,
                'persona_id': 5,
            },
            {
                'change_note': '1.H.: Teilnahme -> Warteliste',
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
                'persona_id': 100,
            },
            {
                'change_note': "23.02.2022, 10:00:01",
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 2,
            },
            {
                'change_note': "23.02.2022, 10:00:02",
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 2,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'persona_id': 3,
            },
            {
                'change_note': "22.02.2022, 18:00:00",
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 3,
            },
            {
                'change_note': "23.02.2022, 10:00:00",
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 3,
            },
            {
                'change_note': 'Sehr wichtiger Import',
                'code': const.EventLogCodes.event_partial_import,
            },
        ]
        self.assertLogEqual(
            log_expectation,
            event_id=EventID(1),
            realm="event",
            offset=self.EVENT_LOG_OFFSET,
        )

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_integrity(self) -> None:
        event_id = EventID(1)
        with open(
            self.testfile_dir / "partial_event_import.json",
            encoding="utf-8",
        ) as datafile:
            orig_data = json.load(datafile)

        base_data = {
            k: orig_data[k] for k in ("id", "EVENT_SCHEMA_VERSION", "timestamp", "kind")
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
                self.key,
                event_id,
                data,
                dryrun=False,
            )
        self.assertIn("Referential integrity of courses violated.", cm.exception.args)

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
                self.key,
                event_id,
                data,
                dryrun=False,
            )
        self.assertIn(
            "Referential integrity of lodgements violated.", cm.exception.args
        )

        data = copy.deepcopy(base_data)
        data["lodgements"] = {
            1: {
                "group_id": -1,
            },
        }
        with self.assertRaises(ValueError) as cm:
            self.event.partial_import_event(
                self.key,
                event_id,
                data,
                dryrun=False,
            )
        self.assertIn(
            "Referential integrity of lodgement groups violated.", cm.exception.args
        )

    @storage
    @event_keeper
    @as_users("annika")
    def test_partial_import_event_twice(self) -> None:
        event_id = EventID(1)
        with open(
            self.testfile_dir / "partial_event_import.json",
            encoding="utf-8",
        ) as datafile:
            data = json.load(datafile)

        # first a test run
        token1, delta = self.event.partial_import_event(
            self.key,
            event_id,
            data,
            dryrun=True,
        )
        # second a real run
        token2, delta = self.event.partial_import_event(
            self.key,
            event_id,
            data,
            dryrun=False,
            token=token1,
        )
        self.assertEqual(token1, token2)
        # third another concurrent real run
        with self.assertRaises(PartialImportError):
            self.event.partial_import_event(
                self.key,
                event_id,
                data,
                dryrun=False,
                token=token1,
            )
        token3, delta = self.event.partial_import_event(
            self.key,
            event_id,
            data,
            dryrun=True,
        )
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
                    'title': 'Blitzkurs',
                    'is_visible': True,
                },
                3: None,
                4: {
                    'segments': {1: None},
                },
            },
            'lodgement_groups': {
                -1: {'title': 'Geheime Etage'},
            },
            'lodgements': {
                -1: {
                    'regular_capacity': 12,
                    'fields': {'contamination': 'none'},
                    'title': 'Geheimkabinett',
                    'notes': 'Einfach den unsichtbaren Schildern folgen.',
                    'group_id': -1,
                    'camping_mat_capacity': 2,
                },
                -2: {
                    'regular_capacity': 42,
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
                3: {'tracks': {3: {'course_id': -1, 'choices': [4, -1, 5]}}},
                5: None,
                6: {
                    'checkin_periods': [
                        models.ReducedCheckinPeriod(
                            datetime.datetime(2022, 2, 22, 17, 0, tzinfo=datetime.UTC),
                            datetime.datetime(2022, 2, 23, 9, 0, tzinfo=datetime.UTC),
                        ),
                        models.ReducedCheckinPeriod(
                            datetime.datetime(
                                2022, 2, 23, 9, 0, 1, tzinfo=datetime.UTC
                            ),
                            datetime.datetime(
                                2022, 2, 23, 9, 0, 2, tzinfo=datetime.UTC
                            ),
                        ),
                    ],
                },
                1001: {
                    'checkin_periods': [
                        models.ReducedCheckinPeriod(
                            datetime.datetime(2022, 2, 22, 17, 0, tzinfo=datetime.UTC),
                            datetime.datetime(2022, 2, 23, 9, 0, tzinfo=datetime.UTC),
                        ),
                    ],
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

    @as_users("annika", "garcia", maintain_data=True)
    def test_check_registration_status(self) -> None:
        event_id = EventID(1)

        # Check for participant status
        stati = [const.RegistrationPartStati.participant]
        self.assertTrue(
            self.event.check_registration_status(self.key, 1, event_id, stati)
        )
        self.assertFalse(
            self.event.check_registration_status(self.key, 3, event_id, stati)
        )
        self.assertTrue(
            self.event.check_registration_status(self.key, 5, event_id, stati)
        )
        self.assertTrue(
            self.event.check_registration_status(self.key, 9, event_id, stati)
        )

        # Check for waitlist status
        stati = [const.RegistrationPartStati.waitlist]
        self.assertFalse(
            self.event.check_registration_status(self.key, 1, event_id, stati)
        )
        self.assertTrue(
            self.event.check_registration_status(self.key, 5, event_id, stati)
        )
        self.assertFalse(
            self.event.check_registration_status(self.key, 9, event_id, stati)
        )

    @as_users("emilia", "garcia", "annika")
    def test_calculate_fees(self) -> None:
        if not self.user_in("emilia"):
            reg_ids = self.event.list_registrations(self.key, event_id=EventID(1))
            expectation = {
                1: decimal.Decimal("553.99"),
                2: decimal.Decimal("466.49"),
                3: decimal.Decimal("504.48"),
                4: decimal.Decimal("431.99"),
                5: decimal.Decimal("584.48"),
                6: decimal.Decimal("10.50"),
            }
            reality = {
                reg_id: self.event.calculate_complex_fee(self.key, reg_id).amount
                for reg_id in reg_ids
            }
            self.assertEqual(expectation, reality)

        if self.user_in("annika"):
            for event_id in self.event.list_events(self.key):
                for reg_id in self.event.list_registrations(
                    self.key, event_id=event_id
                ):
                    data = self._raw_backend.sql_select_one(
                        self.key,
                        models.Registration.database_table,
                        [
                            "amount_owed",
                            "amount_owed_by_kind",
                            "amount_owed_by_category",
                            "amount_owed_by_budget",
                        ],
                        entity=reg_id,
                    )
                    assert data is not None
                    expectation_amount = data["amount_owed"]
                    expectation_by_kind = {
                        const.EventFeeType(int(key)): decimal.Decimal(val)
                        for key, val in data["amount_owed_by_kind"].items()
                    }
                    expectation_by_category = {
                        const.EventFeeCategory(int(key)): decimal.Decimal(val)
                        for key, val in data["amount_owed_by_category"].items()
                    }
                    expectation_by_budget = {
                        const.EventFeeBudget(int(key)): decimal.Decimal(val)
                        for key, val in data["amount_owed_by_budget"].items()
                    }
                    complex_reality = self.event.calculate_complex_fee(self.key, reg_id)
                    self.assertEqual(expectation_amount, complex_reality.amount)
                    self.assertEqual(expectation_by_kind, dict(complex_reality.by_kind))
                    self.assertEqual(
                        expectation_by_category, dict(complex_reality.by_category)
                    )
                    self.assertEqual(
                        expectation_by_budget, dict(complex_reality.by_budget)
                    )

        reg_id = RegistrationID(2)
        reg = self.event.get_registration(self.key, reg_id)
        self.assertEqual(reg['amount_owed'], decimal.Decimal("466.49"))
        self.assertEqual(
            const.RegistrationPartStati.waitlist, reg['parts'][1]['status']
        )
        self.assertEqual(const.RegistrationPartStati.guest, reg['parts'][2]['status'])
        self.assertEqual(
            const.RegistrationPartStati.participant, reg['parts'][3]['status']
        )
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
        self.assertEqual(
            reg['parts'][1]['status'], const.RegistrationPartStati.cancelled
        )
        self.assertEqual(
            reg['parts'][2]['status'], const.RegistrationPartStati.participant
        )
        self.assertEqual(
            reg['parts'][3]['status'], const.RegistrationPartStati.rejected
        )

    @as_users("berta")
    def test_uniqueness(self) -> None:
        event_id = EventID(2)
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
        event_id = EventID(2)
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
                    self.assertEqual(
                        error_msg, cm.exception.args[0] % cm.exception.args[1]
                    )
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
            "tracks": {},
            "mixed_lodging": True,
            "list_consent": True,
            "notes": None,
        }
        reg_id = self.event.create_registration(self.key, reg_data)
        self.assertEqual(
            self.event.calculate_complex_fee(self.key, reg_id).amount,
            decimal.Decimal("15"),
        )
        reg_data = {
            'id': reg_id,
            'fields': {
                'solidarity': True,
            },
        }
        self.assertTrue(self.event.set_registration(self.key, reg_data))
        self.assertEqual(
            self.event.calculate_complex_fee(self.key, reg_id).amount,
            decimal.Decimal("2.50"),
        )

    @as_users("garcia")
    def test_waitlist(self) -> None:
        event_id = EventID(1)
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
                        'status': (
                            const.RegistrationPartStati.waitlist
                            if anid in {2, 3}
                            else const.RegistrationPartStati.participant
                        ),
                    },
                    3: {
                        'status': (
                            const.RegistrationPartStati.waitlist
                            if anid in {2, 3}
                            else const.RegistrationPartStati.participant
                        ),
                    },
                },
                'fields': {
                    'waitlist': i + 1,
                },
            }
            for i, anid in enumerate((5, 4, 3, 2, 1))
        ]
        for rdata in regs:
            self.event.set_registration(self.key, rdata)
        # Registration 3 belongs to Garcia (persona_id 7).
        expectation = {1: [5, 4, 3, 2, 1], 2: [3, 2], 3: [3, 2]}
        self.assertEqual(
            expectation, self.event.get_waitlist(self.key, event_id=EventID(1))
        )
        self.assertEqual(
            {1: 3, 2: 1, 3: 1},
            self.event.get_waitlist_position(self.key, event_id=EventID(1)),
        )
        # Registration 2 belongs to Emilia (persona_id 5).
        self.assertEqual(
            {1: 4, 2: 2, 3: 2},
            self.event.get_waitlist_position(
                self.key, event_id=EventID(1), persona_id=PersonaID(5)
            ),
        )
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
        self.assertEqual(
            expectation, self.event.get_waitlist(self.key, event_id=EventID(1))
        )

        # Check that users can check their own waitlist position.
        self.login(USER_DICT["emilia"])
        self.assertEqual(
            {1: 3, 2: 2, 3: 2},
            self.event.get_waitlist_position(self.key, event_id=EventID(1)),
        )
        with self.assertRaises(PrivilegeError):
            self.event.get_waitlist_position(
                self.key, event_id=EventID(1), persona_id=PersonaID(1)
            )

    @as_users("annika")
    def test_set_event_orgas(self) -> None:
        event_id = EventID(1)
        self.assertEqual({7}, self.event.get_event(self.key, event_id).orgas)
        self.assertLess(
            0, self.event.add_event_roles(self.key, event_id, {PersonaID(1)}, 'orga')
        )
        self.assertEqual({1, 7}, self.event.get_event(self.key, event_id).orgas)
        self.assertLess(
            0, self.event.remove_event_role(self.key, event_id, PersonaID(1), 'orga')
        )
        self.assertLess(
            0, self.event.add_event_roles(self.key, event_id, {PersonaID(1)}, 'orga')
        )
        self.assertEqual({1, 7}, self.event.get_event(self.key, event_id).orgas)

        with self.assertRaises(ValueError) as cm:
            self.event.add_event_roles(self.key, event_id, {PersonaID(8)}, 'orga')
        self.assertIn(
            "Some of these personas do not exist or are archived.", cm.exception.args
        )
        with self.assertRaises(ValueError) as cm:
            self.event.add_event_roles(self.key, event_id, {PersonaID(1000)}, 'orga')
        self.assertIn(
            "Some of these personas do not exist or are archived.", cm.exception.args
        )
        with self.assertRaises(ValueError) as cm:
            self.event.add_event_roles(self.key, event_id, {PersonaID(11)}, 'orga')
        self.assertIn("Some of these personas are not event users.", cm.exception.args)

    @event_keeper
    @as_users("annika")
    def test_log(self) -> None:
        # first check the already existing log
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
            {
                'code': const.EventLogCodes.registration_payment_received,
                'event_id': 1,
                'persona_id': 1,
                'submitted_by': 1,
                'change_note': "200,00 € am 01.01.2014 gezahlt.",
            },
            {
                'code': const.EventLogCodes.registration_payment_received,
                'event_id': 1,
                'persona_id': 9,
                'submitted_by': 1,
                'change_note': "548,48 € am 04.04.2014 gezahlt.",
            },
            {
                'code': const.EventLogCodes.registration_payment_received,
                'event_id': 1,
                'persona_id': 2,
                'submitted_by': 1,
                'change_note': "10,50 € am 06.06.2014 gezahlt.",
            },
            {
                "code": const.EventLogCodes.checkin_added,
                "event_id": 1,
                "persona_id": 2,
                "submitted_by": 1,
                "change_note": "22.02.2022, 18:00:00",
            },
            {
                "code": const.EventLogCodes.checkout_added,
                "event_id": 1,
                "persona_id": 2,
                "submitted_by": 1,
                "change_note": "23.02.2022, 10:00:00",
            },
            {
                'code': const.EventLogCodes.checkin_helper_added,
                'event_id': 1,
                'persona_id': 38,
                'submitted_by': 7,
                'change_note': None,
            },
        )

        self.assertLogEqual(expectation, realm="event")
        offset = len(expectation)

        # then generate some data
        data: CdEDBObject = {
            'title': "New Link Academy",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'shortname': 'link',
            'registration_start': datetime.datetime(
                2000, 11, 22, 0, 0, 0, tzinfo=datetime.UTC
            ),
            'registration_soft_limit': datetime.datetime(
                2022, 1, 2, 0, 0, 0, tzinfo=datetime.UTC
            ),
            'registration_hard_limit': None,
            'iban': None,
            'registration_status_text': None,
            'mail_text': None,
            'use_additional_questionnaire': False,
            'notes': None,
            'orgas': {2, 7},
            'parts': {
                -1: {
                    'tracks': {
                        -1: {
                            'title': "First lecture",
                            'shortname': "First",
                            'num_choices': 3,
                            'min_choices': 3,
                            'sortkey': 1,
                            'course_room_field_id': None,
                        }
                    },
                    'title': "First coming",
                    'shortname': "First",
                    'part_begin': datetime.date(2109, 8, 7),
                    'part_end': datetime.date(2109, 8, 20),
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                },
                -2: {
                    'tracks': {
                        -1: {
                            'title': "Second lecture",
                            'shortname': "Second",
                            'num_choices': 3,
                            'min_choices': 3,
                            'sortkey': 1,
                            'course_room_field_id': None,
                        }
                    },
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
                    'entries': [
                        ["2109-8-16", "In the first coming"],
                        ["2110-8-16", "During the second coming"],
                    ],
                    'checkin': True,
                },
            },
        }
        new_id = self.event.create_event(self.key, data)
        for lg_title in ["Draußen", "Drinnen"]:
            self.event.create_lodgement_group(self.key, new_id, {'title': lg_title})
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
                if (
                    tmp.fields[field].field_name
                    == data['fields'][oldfield]['field_name']
                ):
                    field_map[tmp.fields[field].field_name] = field
                    data['fields'][field] = data['fields'][oldfield]
                    data['fields'][field]['id'] = field
                    data['fields'][field]['event_id'] = new_id
                    del data['fields'][oldfield]
                    break

        data['title'] = "Alternate Universe Academy"
        newpart = {
            'tracks': {
                -1: {
                    'title': "Third lecture",
                    'shortname': "Third",
                    'num_choices': 2,
                    'min_choices': 2,
                    'sortkey': 2,
                    'course_room_field_id': None,
                }
            },
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
            'kind': const.FieldDatatypes.date,
            'entries': [
                ["2110-8-15", "early second coming"],
                ["2110-8-17", "late second coming"],
            ],
            'checkin': True,
        }
        self.event.add_event_roles(
            self.key, new_id, {PersonaID(1), PersonaID(2)}, 'orga'
        )
        self.event.remove_event_role(self.key, new_id, PersonaID(2), 'orga')
        self.event.set_event(
            self.key,
            new_id,
            {
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
            },
        )
        data = {
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
            'nr': 'ζ',
            'shortname': "Topos",
            'instructors': "Alexander Grothendieck",
            'max_size': 14,
            'min_size': 5,
            'notes': "Beware of dragons.",
            'segments': {
                2: {
                    "is_active": True,
                },
                3: {
                    "is_active": True,
                },
            },
            'is_visible': True,
        }
        new_id = self.event.create_course(self.key, EventID(1), data)
        data['title'] = "Alternate Universes"
        data['segments'] = {
            1: {
                "is_active": True,
            },
            2: None,
        }
        self.event.set_course(
            self.key, new_id, {'title': data['title'], 'segments': data['segments']}
        )
        new_reg = {
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
            'real_persona_id': None,
        }
        new_id = self.event.create_registration(self.key, new_reg)
        data = {
            'id': 4,
            'fields': {'transportation': 'pedes'},
            'mixed_lodging': True,
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
            'title': 'HY',
            'notes': "Notizen",
            'camping_mat_capacity': 11,
            'group_id': 1,
        }
        new_id = self.event.create_lodgement(self.key, event_id=EventID(1), data=new)
        update = {
            'regular_capacity': 21,
            'notes': None,
        }
        self.event.set_lodgement(self.key, new_id, update)
        self.event.delete_lodgement(self.key, new_id)
        q_data: list[CdEDBObject] = [
            {
                'role': const.QuestionnaireRowRole.heading,
                'title': 'Weitere bla Überschrift',
            },
            {
                'role': const.QuestionnaireRowRole.event_field,
                'field_id': 2,
                'label': 'Vehikel',
                'default_value': 'etc',
                'readonly': True,
            },
            {
                'role': const.QuestionnaireRowRole.heading,
                'title': 'Unterüberschrift',
            },
            {
                'role': const.QuestionnaireRowRole.text,
                'text': 'mit Text darunter und so',
            },
            {
                'role': const.QuestionnaireRowRole.event_field,
                'field_id': 3,
                'label': 'Hauswunsch',
                'readonly': True,
            },
            {
                'role': const.QuestionnaireRowRole.text,
                'text': 'nur etwas mehr Text',
            },
        ]
        self.event.set_questionnaire(
            self.key, EventID(1), const.QuestionnaireUsages.additional, q_data
        )

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
                'change_note': "New Link Academy",
                'code': const.EventLogCodes.lodgement_group_created,
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
                'change_note': 'Topos theory for the kindergarden (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Arbeitssitzung (Zweite Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Arbeitssitzung (Zweite Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden',
                'code': const.EventLogCodes.course_changed,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deleted,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Kaffeekränzchen (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_deactivated,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_created,
                'event_id': 1,
            },
            {
                'change_note': 'Topos theory for the kindergarden (Morgenkreis (Erste Hälfte))',
                'code': const.EventLogCodes.course_segment_activated,
                'event_id': 1,
            },
            {
                'code': const.EventLogCodes.registration_created,
                'event_id': 1,
                'persona_id': 3,
            },
            {
                'change_note': "Wu: Abgelehnt -> Teilnahme",
                'code': const.EventLogCodes.registration_status_changed,
                'event_id': 1,
                'persona_id': 9,
            },
            {
                'change_note': "2.H.: Teilnahme -> Abgelehnt",
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
                'change_note': "Zusätzlicher Fragebogen",
                'event_id': 1,
            },
        )

        self.assertLogEqual(expectation, realm="event", offset=offset)

    def _create_registration(
        self, persona_id: vtypes.PersonaID, event_id: vtypes.EventID
    ) -> vtypes.RegistrationID:
        event = self.event.get_event(self.key, event_id)
        return self.event.create_registration(
            self.key,
            {
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
                    for p_id in event.parts
                    for t_id in event.parts[p_id].tracks
                },
            },
        )

    @as_users("annika")
    def test_registration_timestamps(self) -> None:
        persona_id = self.user['id']
        event_ids = [EventID(1), EventID(2)]
        reg_ids = {}
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            for event_id in event_ids:
                reg_id = self._create_registration(persona_id, event_id)
                frozen_time.tick(delta)
                self.event.set_registration(
                    self.key, {'id': reg_id, 'notes': "Important change!"}
                )
                frozen_time.tick(delta)
                reg_ids[event_id] = reg_id
            for i, (event_id, reg_id) in enumerate(reg_ids.items()):
                reg = self.event.get_registration(self.key, reg_id)
                self.assertEqual(reg['ctime'], base_time + 2 * i * delta)
                self.assertEqual(reg['mtime'], base_time + (2 * i + 1) * delta)

    @as_users("garcia")
    def test_checkin_checkout(self) -> None:
        reg_id = RegistrationID(1)
        base_time = now().replace(microsecond=0)
        delta = datetime.timedelta(seconds=42)
        future_time = base_time + 42 * delta
        with freezegun.freeze_time(base_time) as frozen_time:
            # single checkins / checkouts first
            p_id = 1001
            self.event.add_checkin(self.key, reg_id)
            self.assertEqual(self.event.add_checkin(self.key, reg_id), 0)
            frozen_time.tick(delta)
            self.assertEqual(
                self.event.add_checkout(self.key, reg_id, base_time - delta), 0
            )
            self.assertGreater(
                self.event.add_checkout(self.key, reg_id, future_time), 0
            )
            with self.assertRaises(ValueError) as cm:
                self.event.add_checkin(self.key, reg_id, future_time)
            self.assertEqual(cm.exception.args[0], "Must be in the past.")
            self.assertEqual(self.event.add_checkout(self.key, reg_id), 0)
            period: CdEDBObject = {
                "id": p_id,
                "registration_id": reg_id,
                "checkin_time": base_time,
                "checkout_time": future_time,
            }
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(
                reg['checkin_periods'], [models.CheckinPeriod.from_database(period)]
            )

            # change a period
            period["checkin_time"] += delta
            period["checkout_time"] += delta
            frozen_time.tick(2 * delta)
            with self.assertRaises(ValueError) as cm:
                self.event.change_checkin_period(
                    self.key,
                    reg_id,
                    p_id,
                    checkin_time=period["checkin_time"] + delta,
                    checkout_time=period["checkin_time"],
                )
            self.assertEqual("Checkout must be after checkin.", cm.exception.args[0])
            with self.assertRaises(ValueError) as cm:
                self.event.change_checkin_period(
                    self.key,
                    reg_id,
                    p_id + 42,
                    checkin_time=period["checkin_time"],
                    checkout_time=period["checkout_time"],
                )
            self.assertEqual(
                "Period is not from this registration.", cm.exception.args[0]
            )

            self.assertGreater(
                self.event.change_checkin_period(
                    self.key,
                    reg_id,
                    p_id,
                    checkin_time=period["checkin_time"],
                    checkout_time=period["checkout_time"],
                ),
                0,
            )
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(
                reg['checkin_periods'], [models.CheckinPeriod.from_database(period)]
            )
            period["checkout_time"] = None
            self.assertGreater(
                self.event.change_checkin_period(
                    self.key,
                    reg_id,
                    p_id,
                    checkin_time=period["checkin_time"],
                    checkout_time=None,
                ),
                0,
            )
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(
                reg['checkin_periods'], [models.CheckinPeriod.from_database(period)]
            )

            # adding an earlier period
            early_period: CdEDBObject = {
                "registration_id": reg_id,
                "checkin_time": base_time - delta,
                "checkout_time": base_time,
            }
            with self.assertRaises(ValueError) as cm:
                self.event.add_backdated_checkin_period(
                    self.key,
                    reg_id,
                    checkin_time=early_period["checkin_time"],
                    checkout_time=early_period["checkin_time"],
                )
            self.assertEqual("Checkout must be after checkin.", cm.exception.args[0])
            with self.assertRaises(ValueError) as cm:
                self.event.add_backdated_checkin_period(
                    self.key,
                    reg_id,
                    checkin_time=early_period["checkin_time"],
                    checkout_time=future_time,
                )
            self.assertEqual(
                "Checkout must be before next checkin.", cm.exception.args[0]
            )
            with self.assertRaises(ValueError) as cm:
                self.event.add_backdated_checkin_period(
                    self.key,
                    reg_id,
                    checkin_time=future_time,
                    checkout_time=future_time + delta,
                )
            self.assertEqual("Cannot check in checked-in users.", cm.exception.args[0])
            self.assertGreater(
                self.event.add_backdated_checkin_period(self.key, **early_period), 0
            )
            expected = [
                models.CheckinPeriod.from_database(early_period | {"id": p_id + 1}),
                models.CheckinPeriod.from_database(period),
            ]
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(reg['checkin_periods'], expected)

            # replacing
            new_periods: list[CdEDBObject] = [
                {
                    # this is backdated and created at end in backend func
                    "id": p_id + 4,
                    "registration_id": reg_id,
                    "checkin_time": base_time - 2 * delta,
                    "checkout_time": base_time,
                },
                {
                    # checkin time matches, so period will be edited instead of deleted
                    "id": p_id,
                    "registration_id": reg_id,
                    "checkin_time": period["checkin_time"],
                    "checkout_time": base_time + 2 * delta,
                },
                {
                    "id": p_id + 2,
                    "registration_id": reg_id,
                    "checkin_time": base_time + 4 * delta,
                    "checkout_time": None,
                },
                {
                    "id": p_id + 3,
                    "registration_id": reg_id,
                    "checkin_time": base_time + 8 * delta,
                    "checkout_time": base_time + 10 * delta,
                },
            ]
            replace_input: list[models.ReducedCheckinPeriod] = [
                models.ReducedCheckinPeriod(
                    checkin_time=p["checkin_time"], checkout_time=p["checkout_time"]
                )
                for p in new_periods
            ]
            frozen_time.tick(10 * delta)  # are at base_time + 12*delta now
            with self.assertRaises(ValueError) as cm:
                self.event.replace_checkin_periods(self.key, reg_id, replace_input)
            self.assertEqual("Checkout date must be provided.", cm.exception.args[0])
            new_periods[2]["checkout_time"] = base_time + 6 * delta
            replace_input[2].checkout_time = base_time + 6 * delta
            self.assertGreater(
                self.event.replace_checkin_periods(self.key, reg_id, replace_input), 0
            )
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(
                reg['checkin_periods'],
                [models.CheckinPeriod.from_database(p) for p in new_periods],
            )

            # delete
            self.assertGreater(
                self.event.delete_checkin_period(self.key, reg_id, p_id), 0
            )
            del new_periods[1]
            reg = self.event.get_registration(self.key, reg_id)
            self.assertEqual(
                reg['checkin_periods'],
                [models.CheckinPeriod.from_database(p) for p in new_periods],
            )

            # multi-checkin
            new_periods.append({
                "id": p_id + 5,
                "registration_id": reg_id,
                "checkin_time": now() - delta,
                "checkout_time": now() + delta,
            })
            new_period2 = {
                "id": p_id + 6,
                "registration_id": reg_id + 1,
                "checkin_time": base_time,
                "checkout_time": base_time + delta,
            }
            self.assertEqual(  # checkin time too early
                self.event.add_checkins_multi(
                    self.key, {reg_id: base_time, RegistrationID(reg_id + 1): base_time}
                ),
                0,
            )
            self.assertEqual(
                self.event.add_checkins_multi(
                    self.key,
                    {reg_id: now() - delta, RegistrationID(reg_id + 1): base_time},
                ),
                2,
            )
            self.assertEqual(  # someone already checked in
                self.event.add_checkins_multi(
                    self.key, {reg_id: now(), RegistrationID(reg_id + 2): base_time}
                ),
                0,
            )
            self.assertEqual(  # checkout time before last checkin
                self.event.add_checkouts_multi(
                    self.key, {reg_id: base_time, RegistrationID(reg_id + 1): base_time}
                ),
                0,
            )
            self.assertEqual(
                self.event.add_checkouts_multi(  # someone not checked in
                    self.key,
                    {reg_id: now(), RegistrationID(reg_id + 2): base_time + delta},
                ),
                0,
            )
            self.assertGreater(
                self.event.add_checkouts_multi(
                    self.key,
                    {
                        reg_id: now() + delta,
                        RegistrationID(reg_id + 1): base_time + delta,
                    },
                ),
                0,
            )
            reg = self.event.get_registration(self.key, reg_id)
            reg1 = self.event.get_registration(self.key, RegistrationID(reg_id + 1))
            reg2 = self.event.get_registration(self.key, RegistrationID(reg_id + 2))
            self.assertEqual(
                reg['checkin_periods'],
                [models.CheckinPeriod.from_database(p) for p in new_periods],
            )
            self.assertEqual(
                reg1['checkin_periods'],
                [models.CheckinPeriod.from_database(new_period2)],
            )
            self.assertEqual(reg2['checkin_periods'], [])

    @as_users("emilia")
    def test_part_groups(self) -> None:
        event_id = EventID(4)
        event = self.event.get_event(self.key, event_id)

        # Delete existing registrations so we are free to create and delete event parts.
        registration_ids = self.event.list_registrations(self.key, event_id)
        for reg_id in registration_ids:
            self.event.delete_registration(
                self.key, reg_id, cascade=("registration_parts", "registration_tracks")
            )

        # Load expected sample part groups.
        part_group_parts_data = self.get_sample_data("event.part_group_parts")
        part_group_expectation = {
            part_group_id: part_group
            for part_group_id, part_group in self.get_sample_data(
                "event.part_groups"
            ).items()
            if part_group['event_id'] == event_id
        }
        # Add dynamic data and convert enum.
        for part_group in part_group_expectation.values():
            part_group['part_ids'] = {
                e['part_id']
                for e in part_group_parts_data.values()
                if e['part_group_id'] == part_group['id']
            }
            part_group['constraint_type'] = const.EventPartGroupType(
                part_group['constraint_type']
            )
        # Compare to retrieved data.
        reality = event.as_dict()['part_groups']
        for pg in reality.values():
            pg['part_ids'] = set(pg.pop('parts'))
        self.assertEqual(
            part_group_expectation,
            reality,
        )

        # Check setting of part groups.

        new_part_group: CdEDBObject = {
            'title': "Everything",
            'shortname': "all",
            'notes': "Let's see what happens",
            'part_ids': set(event.parts),
            'constraint_type': const.EventPartGroupType.Statistic,
        }

        # Setting is not allowed for non-privileged users.
        with self.assertRaises(PrivilegeError):
            self.event.add_part_group(ANONYMOUS, event_id, {})
        with self.switch_user("garcia"):
            with self.assertRaises(PrivilegeError):
                self.event.add_part_group(self.key, event_id, {})

        new_part_group_id = self.event.add_part_group(
            self.key, event_id, new_part_group
        )  # id 1001
        self.assertTrue(new_part_group_id)

        # we require shortname and title to be unique
        with self.assertRaises(ValueError):
            self.event.add_part_group(self.key, event_id, new_part_group)

        data = new_part_group.copy()
        data['shortname'] = "ALL"
        with self.assertRaises(ValueError):
            self.event.add_part_group(self.key, event_id, data)

        data = new_part_group.copy()
        data['title'] = "All"
        with self.assertRaises(ValueError):
            self.event.add_part_group(self.key, event_id, data)

        data = new_part_group.copy()
        data['shortname'] = "ALL"
        data['title'] = "All"
        self.event.add_part_group(self.key, event_id, data)  # id 1002

        part_group_expectation.update({
            1001: {**new_part_group, **{'event_id': event_id, 'id': 1001}},
            1002: {**data, **{'event_id': event_id, 'id': 1002}},
        })

        # Update an existing group.
        update = {
            'notes': "Pack explosives for New Years!",
        }
        self.assertTrue(self.event.change_part_group(self.key, 1, update))
        part_group_expectation[1].update(update)

        # Delete an existing group
        self.assertTrue(self.event.delete_part_group(self.key, 4))
        del part_group_expectation[4]

        reality = self.event.get_event(self.key, event_id).as_dict()['part_groups']
        for pg in reality.values():
            pg['part_ids'] = set(pg.pop('parts'))
        self.assertEqual(
            part_group_expectation,
            reality,
        )

        # ValueError is raised when trying to update or delete a nonexisting part group.
        with self.assertRaises(ValueError):
            self.event.change_part_group(
                self.key, NON_EXISTING_ID, {"id": NON_EXISTING_ID}
            )
        with self.assertRaises(ValueError):
            self.event.delete_part_group(self.key, NON_EXISTING_ID)
        # ValueError when creating a part group with a non existing part.
        data = new_part_group.copy()
        data["part_ids"] = [NON_EXISTING_ID]
        with self.assertRaises(ValueError):
            self.event.add_part_group(self.key, event_id, data)

        # Delete a part still linked to a part group.
        self.assertTrue(
            self.event.set_event(
                self.key, event_id, {'parts': {min(event.parts): None}}
            )
        )

        export_expectation = {
            1: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': 'Pack explosives for New Years!',
                'part_ids': [7, 8],
                'shortname': '1.H.',
                'title': '1. Hälfte',
            },
            2: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [9, 10, 11],
                'shortname': '2.H.',
                'title': '2. Hälfte',
            },
            3: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [9],
                'shortname': 'OW',
                'title': 'Oberwesel',
            },
            5: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': None,
                'part_ids': [8, 11],
                'shortname': 'KA',
                'title': 'Kaub',
            },
            6: {
                'constraint_type': const.EventPartGroupType.mutually_exclusive_participants,
                'notes': None,
                'part_ids': [7, 8],
                'shortname': 'TN 1H',
                'title': 'Teilnehmer 1. Hälfte',
            },
            7: {
                'constraint_type': const.EventPartGroupType.mutually_exclusive_participants,
                'notes': None,
                'part_ids': [9, 10, 11],
                'shortname': 'TN 2H',
                'title': 'Teilnehmer 2. Hälfte',
            },
            10: {
                'constraint_type': const.EventPartGroupType.mailinglist_link,
                'notes': None,
                'part_ids': [7, 10],
                'shortname': 'ML W',
                'title': 'Mailingliste Windischleuba',
            },
            1001: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': "Let's see what happens",
                'part_ids': [7, 8, 9, 10, 11, 12],
                'shortname': 'all',
                'title': 'Everything',
            },
            1002: {
                'constraint_type': const.EventPartGroupType.Statistic,
                'notes': "Let's see what happens",
                'part_ids': [7, 8, 9, 10, 11, 12],
                'shortname': 'ALL',
                'title': 'All',
            },
        }
        export = self.event.partial_export_event(self.key, event_id)
        self.assertEqual(export['event']['part_groups'], export_expectation)

        # Delete the entire event. Requires admin.
        with self.switch_user("annika"):
            blockers = self.event.delete_event_blockers(self.key, event_id)
            self.assertEqual(
                {
                    "orgas",
                    "event_parts",
                    "course_tracks",
                    "part_groups",
                    "part_group_parts",
                    "track_groups",
                    "track_group_tracks",
                    "courses",
                    "log",
                    "lodgement_groups",
                    "event_fees",
                    "mailinglists",
                    "questionnaire_text_rows",
                    "questionnaire_magic_rows",
                },
                set(blockers),
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

        fee_data: CdEDBObjectMap = {
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
        for fee in fee_data.values():
            self.event.create_event_fee(self.key, event_id, fee)

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
            fee_amount = self.event.calculate_complex_fee(self.key, reg_id).amount
            with self.subTest(combination=combination):
                self.assertEqual(fee_amount, decimal.Decimal(expected_fee))

    @as_users("garcia")
    def test_part_shortname_change(self) -> None:
        event_id = EventID(1)
        new_fee = {
            'kind': const.EventFeeType.common,
            'title': "Test",
            'amount': "1",
            'condition': "part.1.H. and not part.2.H.",
            'notes': None,
        }
        self.event.create_event_fee(self.key, event_id, new_fee)
        event_data = {
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
        self.assertEqual("part.2.H. and not part.1.H.", event.fees[1001].condition)

    @as_users("garcia")
    def test_orga_apitokens(self) -> None:
        event_id = EventID(1)
        event_log_offset, _ = self.event.retrieve_log(
            self.key, EventLogFilter(event_id=EventID(1))
        )

        orga_token_ids = self.event.list_orga_tokens(self.key, event_id)
        orga_tokens = self.event.get_orga_tokens(self.key, orga_token_ids)
        expectation = {
            1: OrgaToken(
                id=cast(vtypes.ID, 1),
                event_id=event_id,
                title="Garcias technische Spielerei",
                notes="Mal probieren, was diese API so alles kann.",
                etime=datetime.datetime(
                    2222,
                    12,
                    31,
                    23,
                    59,
                    59,
                    tzinfo=datetime.UTC,
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
                id=cast(vtypes.ID, -1),
                event_id=event_id,
                title="New Token!",
                notes=None,
                etime=base_time + delta,
            )
            data = new_token.to_database()
            new_id, secret = self.event.create_orga_token(self.key, data)
            new_token.id = vtypes.ID(new_id)
            apitoken = cast(RequestState, new_token.get_token_string(secret))

            log_expectation = [
                {
                    'code': const.EventLogCodes.orga_token_created,
                    'change_note': new_token.title,
                    'ctime': now(),
                },
            ]
            self.assertEqual(
                {}, self.event.delete_orga_token_blockers(self.key, new_id)
            )

            droid_export = self.event.partial_export_event(apitoken, event_id)
            partial_export = self.event.partial_export_event(self.key, event_id)
            self.assertEqual(droid_export, partial_export)

            blockers = self.event.delete_orga_token_blockers(self.key, new_id)
            self.assertEqual({'atime': [True]}, blockers)

            frozen_time.tick(2 * delta)

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
                APITokenError, "This .+ token has been revoked."
            ):
                self.event.partial_export_event(apitoken, event_id)

            self.assertTrue(self.event.delete_orga_token(self.key, new_id, ("atime",)))
            self.assertNotIn(new_id, self.event.list_orga_tokens(self.key, event_id))
            log_expectation.append({
                'code': const.EventLogCodes.orga_token_deleted,
                'change_note': changed_token['title'],
            })

            self.assertLogEqual(
                log_expectation,
                realm='event',
                event_id=event_id,
                offset=event_log_offset,
            )

    @storage
    @as_users("anton")
    def test_external_fee(self) -> None:
        external_fee_amount = decimal.Decimal(1)

        # 1. Create a lightweight event with only an external fee.
        event_id = self.event.create_event(
            self.key,
            {
                'title': "TestAkademie",
                'shortname': "tAka",
                'institution': const.PastInstitutions.main_insitution(),
                'parts': {
                    -1: {
                        'part_begin': "2222-02-02",
                        'part_end': "2222-02-22",
                        'title': "TestPart",
                        'shortname': "TP",
                    },
                },
            },
        )
        self.event.create_event_fee(
            self.key,
            event_id,
            {
                'title': "Externenzusatzbeitrag",
                'notes': None,
                'amount': external_fee_amount,
                'condition': "NOT is_member",
                'kind': const.EventFeeType.external,
            },
        )

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
            'tracks': {},
        }
        reg_id = self.event.create_registration(self.key, rdata)
        self.assertEqual(
            external_fee_amount,
            self.event.calculate_complex_fee(self.key, reg_id).amount,
        )

        # 2.2 Now grant them membership and check that the external fee still holds.
        self.cde.change_membership(self.key, persona_id, True)
        self.assertEqual(
            external_fee_amount,
            self.event.calculate_complex_fee(self.key, reg_id).amount,
        )

        # 3.1 Delete and recreate the registration.
        #  Check that external fee does not apply.
        self.event.delete_registration(self.key, reg_id, ('registration_parts',))
        new_reg_id = self.event.create_registration(self.key, rdata)
        self.assertEqual(
            decimal.Decimal(0),
            self.event.calculate_complex_fee(self.key, new_reg_id).amount,
        )

        # 3.2 Revoke membership and check that external fee still does not apply.
        self.cde.change_membership(self.key, persona_id, False)
        self.assertEqual(
            decimal.Decimal(0),
            self.event.calculate_complex_fee(self.key, new_reg_id).amount,
        )

    @event_keeper
    @as_users("anton")
    def test_event_keeper_log_entries(self) -> None:

        event_id = EventID(1)

        def normalize_reference_time(dt: datetime.datetime) -> datetime.datetime:
            return datetime.datetime.fromisoformat(
                self.event._event_keeper.format_datetime(dt).decode()
            )

        base_time = now() + datetime.timedelta(hours=1)
        delta = datetime.timedelta(minutes=42)

        # Convert reference time to same format as parsed time because of tz trouble.
        reference_time = normalize_reference_time(base_time)

        self.event.event_keeper_commit(
            self.key,
            event_id,
            "pre test",
            after_change=True,
        )
        # Ensure that the commit time matches the current (non-frozen) time.
        self.assertEqual(
            nearly_now(delta=datetime.timedelta(seconds=5)),
            self.event._event_keeper.latest_logtime(event_id),
        )

        with freezegun.freeze_time(base_time) as frozen_time:
            frozen_time.tick(delta)

            # Create any log entry.
            pdf_data = (self.testfile_dir / "form.pdf").read_bytes()
            self.event.change_minor_form(self.key, event_id, pdf_data)

            # Retrieve the time of the log entry.
            log = self.event.retrieve_log(
                self.key,
                EventLogFilter(length=1),
            )[1][0]
            log_reference_time = normalize_reference_time(log['ctime'])

            frozen_time.tick(delta)

            # Create a commit and ensure that the commit time matches the log time
            #  instead of the current (frozen) time.
            self.event.event_keeper_commit(
                self.key,
                event_id,
                "foo bar",
                after_change=True,
            )
            self.assertEqual(
                log_reference_time,
                self.event._event_keeper.latest_logtime(event_id),
            )
            self.assertNotEqual(
                reference_time,
                self.event._event_keeper.latest_logtime(event_id),
            )

        # Check size limit bypass for commited file.
        self.event._event_keeper.commit(event_id, "X" * 300_000, "file size test")

    @as_users("garcia")
    def test_replace_checkin_periods(self) -> None:
        registration_id = RegistrationID(1)
        log_offset = len(self.get_sample_data("event.log"))

        self.assertEqual(
            [],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        td = datetime.timedelta
        ref_time = now().replace(microsecond=0) - td(days=1)

        self.event.add_checkin(self.key, registration_id, ref_time)
        self.event.add_checkout(self.key, registration_id, ref_time + td(hours=1))
        self.event.add_checkin(self.key, registration_id, ref_time + td(hours=2))

        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1001,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time,
                    checkout_time=ref_time + td(hours=1),
                ),
                models.CheckinPeriod(
                    id=1002,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=2),
                    checkout_time=None,
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation: list[CdEDBObject] = [
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time, lang="de"),
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=1), lang="de"),
            },
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=2), lang="de"),
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

        # Delete first period, add checkout to second period.
        new_periods = [
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=2),
                checkout_time=ref_time + td(hours=3),
            ),
        ]
        self.event.replace_checkin_periods(self.key, registration_id, new_periods)
        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1002,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=2),
                    checkout_time=ref_time + td(hours=3),
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation = [
            {
                'code': const.EventLogCodes.checkin_period_deleted,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time, lang="de")};'
                f' {datetime_filter(ref_time + td(hours=1), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=3), lang="de"),
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

        # Insert new period in front, change checkout at the end.
        new_periods = [
            models.ReducedCheckinPeriod(
                checkin_time=ref_time,
                checkout_time=ref_time + td(hours=1),
            ),
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=2),
                checkout_time=ref_time + td(hours=5),
            ),
        ]
        self.event.replace_checkin_periods(self.key, registration_id, new_periods)
        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1003,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time,
                    checkout_time=ref_time + td(hours=1),
                ),
                models.CheckinPeriod(
                    id=1002,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=2),
                    checkout_time=ref_time + td(hours=5),
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation = [
            {
                'code': const.EventLogCodes.checkout_changed,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time + td(hours=3), lang="de")}'
                f' -> {datetime_filter(ref_time + td(hours=5), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time, lang="de"),
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=1), lang="de"),
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

        # Change checkin of last period.
        new_periods = [
            models.ReducedCheckinPeriod(
                checkin_time=ref_time,
                checkout_time=ref_time + td(hours=1),
            ),
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=4),
                checkout_time=ref_time + td(hours=5),
            ),
        ]
        self.event.replace_checkin_periods(self.key, registration_id, new_periods)
        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1003,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time,
                    checkout_time=ref_time + td(hours=1),
                ),
                models.CheckinPeriod(
                    id=1004,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=4),
                    checkout_time=ref_time + td(hours=5),
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation = [
            {
                'code': const.EventLogCodes.checkin_period_deleted,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time + td(hours=2), lang="de")};'
                f' {datetime_filter(ref_time + td(hours=5), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=4), lang="de"),
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=5), lang="de"),
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

        # Add new period in the middle and at the end.
        new_periods = [
            models.ReducedCheckinPeriod(
                checkin_time=ref_time,
                checkout_time=ref_time + td(hours=1),
            ),
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=2),
                checkout_time=ref_time + td(hours=3),
            ),
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=4),
                checkout_time=ref_time + td(hours=5),
            ),
            models.ReducedCheckinPeriod(
                checkin_time=ref_time + td(hours=6),
                checkout_time=ref_time + td(hours=7),
            ),
        ]
        self.event.replace_checkin_periods(self.key, registration_id, new_periods)
        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1003,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time,
                    checkout_time=ref_time + td(hours=1),
                ),
                models.CheckinPeriod(
                    id=1006,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=2),
                    checkout_time=ref_time + td(hours=3),
                ),
                models.CheckinPeriod(
                    id=1004,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=4),
                    checkout_time=ref_time + td(hours=5),
                ),
                models.CheckinPeriod(
                    id=1005,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time + td(hours=6),
                    checkout_time=ref_time + td(hours=7),
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation = [
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=6), lang="de"),
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=7), lang="de"),
            },
            {
                'code': const.EventLogCodes.checkin_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=2), lang="de"),
            },
            {
                'code': const.EventLogCodes.checkout_added,
                'persona_id': 1,
                'change_note': datetime_filter(ref_time + td(hours=3), lang="de"),
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

        # Delete all but the first checkin.
        new_periods = [
            models.ReducedCheckinPeriod(
                checkin_time=ref_time,
                checkout_time=None,
            ),
        ]
        self.event.replace_checkin_periods(self.key, registration_id, new_periods)
        self.assertEqual(
            [
                models.CheckinPeriod(
                    id=1003,  # type: ignore[arg-type]
                    registration_id=registration_id,
                    checkin_time=ref_time,
                    checkout_time=None,
                ),
            ],
            self.event.get_registration(self.key, registration_id)['checkin_periods'],
        )

        log_expectation = [
            {
                'code': const.EventLogCodes.checkin_period_deleted,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time + td(hours=2), lang="de")};'
                f' {datetime_filter(ref_time + td(hours=3), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkin_period_deleted,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time + td(hours=4), lang="de")};'
                f' {datetime_filter(ref_time + td(hours=5), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkin_period_deleted,
                'persona_id': 1,
                'change_note': f'{datetime_filter(ref_time + td(hours=6), lang="de")};'
                f' {datetime_filter(ref_time + td(hours=7), lang="de")}',
            },
            {
                'code': const.EventLogCodes.checkout_changed,
                'persona_id': 1,
                'change_note': f'Entfernt {datetime_filter(ref_time + td(hours=1), lang="de")}',
            },
        ]
        self.assertLogEqual(
            log_expectation,
            realm="event",
            event_id=EventID(1),
            offset=log_offset,
        )
        log_offset += len(log_expectation)

    @event_keeper
    @as_users("garcia")
    @prepsql("DELETE FROM event.checkin_periods")
    def test_checkin_query(self) -> None:
        event_id = EventID(1)
        registration_id = RegistrationID(1)

        base_time = now() - datetime.timedelta(days=2)
        delta = datetime.timedelta(hours=2)

        self.event.replace_checkin_periods(
            self.key,
            registration_id,
            [
                models.ReducedCheckinPeriod(base_time, base_time + delta),
                models.ReducedCheckinPeriod(
                    base_time + 2 * delta, base_time + 3 * delta
                ),
            ],
        )

        base_query = Query(
            QueryScope.registration,
            spec={},
            fields_of_interest=["reg.id"],
            order=[],
            constraints=[("reg.id", QueryOperators.equal, registration_id)],
        )
        spec = base_query.scope.get_spec(event=self.event.get_event(self.key, event_id))

        def _check_queries(
            constraint_a: QueryConstraint, constraint_b: QueryConstraint, first: bool
        ) -> None:
            query = copy.deepcopy(base_query)
            query.spec = spec
            query.constraints.append(constraint_a)
            data_a = self.event.submit_general_query(self.key, query, event_id)
            query.constraints[-1] = constraint_b
            data_b = self.event.submit_general_query(self.key, query, event_id)

            self.assertEqual(int(first), len(data_a))
            self.assertEqual(int(not first), len(data_b))

        # Test at and notat operators.
        _at = lambda dt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_at,
            dt,
        )
        _notat = lambda dt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_notat,
            dt,
        )
        for i, (time, expectation) in enumerate([
            (base_time - 0.5 * delta, False),
            (base_time + 0.5 * delta, True),
            (base_time + 1.5 * delta, False),
            (base_time + 2.5 * delta, True),
            (base_time + 3.5 * delta, False),
        ]):
            with self.subTest(operator="at/notat", i=i, time=time):
                _check_queries(_at(time), _notat(time), expectation)

        # Test oneof and noneof operators.
        _oneof = lambda ldt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_oneof,
            ldt,
        )
        _noneof = lambda ldt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_noneof,
            ldt,
        )
        for i, (ldt, expectation) in enumerate([
            (
                [
                    base_time - 0.5 * delta,
                    base_time + 1.5 * delta,
                    base_time + 3.5 * delta,
                ],
                False,
            ),
            ([base_time + 0.5 * delta], True),
            ([base_time + 2.5 * delta], True),
            ([base_time + 0.5 * delta, base_time + 2.5 * delta], True),
            (
                [
                    base_time + 0.5 * delta,
                    base_time + 1.5 * delta,
                    base_time + 2.5 * delta,
                ],
                True,
            ),
        ]):
            with self.subTest(operator="oneof/noneof", i=i, times=ldt):
                _check_queries(_oneof(ldt), _noneof(ldt), expectation)

        # Test allof and notallof operators.
        _allof = lambda ldt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_allof,
            ldt,
        )
        _notallof = lambda ldt: (
            "checkin_at.checkin_time,checkin_at.checkout_time",
            QueryOperators.ranged_notallof,
            ldt,
        )
        for i, (ldt, expectation) in enumerate([
            ([base_time + 0.5 * delta, base_time + 2.5 * delta], True),
            ([base_time - 0.5 * delta], False),
            ([base_time + 1.5 * delta], False),
            ([base_time + 3.5 * delta], False),
            (
                [
                    base_time + 0.5 * delta,
                    base_time + 2.5 * delta,
                    base_time + 3.5 * delta,
                ],
                False,
            ),
        ]):
            with self.subTest(operator="allof/notallof", i=i, times=ldt):
                _check_queries(_allof(ldt), _notallof(ldt), expectation)

    @event_keeper
    @as_users("garcia")
    @prepsql("UPDATE event.events SET is_balanced = True WHERE id = 1;")
    def test_event_is_balanced(self) -> None:
        event_id = EventID(1)

        with self.assertRaises(EventIsBalancedError):
            self.event.create_event_fee(self.key, event_id, {})
        with self.assertRaises(EventIsBalancedError):
            self.event.change_event_fee(self.key, 1, {})
        with self.assertRaises(EventIsBalancedError):
            self.event.delete_event_fee(self.key, 1)

        with self.assertRaises(EventIsBalancedError):
            self.event.set_registration(
                self.key,
                {
                    'id': 1,
                    'parts': {1: {'status': const.RegistrationPartStati.participant}},
                },
            )

        self.event.set_registration(
            self.key, {'id': 1, 'fields': {'brings_balls': False}}
        )

        with self.assertRaises(EventIsBalancedError):
            self.event.set_personalized_fee_amount(
                self.key, RegistrationID(1), 10, decimal.Decimal(5)
            )

        with self.assertRaises(EventIsBalancedError):
            self.event.set_event(
                self.key,
                event_id,
                {
                    'parts': {
                        part_id: {
                            'part_begin': "2322-01-01",
                            'part_end': "2322-01-01",
                        }
                        for part_id in [1, 2, 3]
                    },
                },
            )

        self.event.set_event(
            self.key,
            event_id,
            {
                'parts': {
                    part_id: {
                        'part_begin': "2223-01-01",
                        'part_end': "2223-01-01",
                    }
                    for part_id in [1, 2, 3]
                },
            },
        )

        new_reg: CdEDBObject = {
            'event_id': event_id,
            'persona_id': 4,
            'parts': {
                1: {
                    'status': const.RegistrationPartStati.applied,
                },
                2: {
                    'status': const.RegistrationPartStati.not_applied,
                },
                3: {
                    'status': const.RegistrationPartStati.not_applied,
                },
            },
            'tracks': {
                1: {},
                2: {},
                3: {},
            },
            'notes': None,
            'mixed_lodging': False,
            'list_consent': True,
        }
        with self.assertRaises(EventIsBalancedError):
            self.event.create_registration(self.key, new_reg)

        new_reg['parts'][1]['status'] = const.RegistrationPartStati.cancelled
        self.event.create_registration(self.key, new_reg)

    @as_users("emilia")
    def test_course_attendees(self) -> None:
        event_id = EventID(1)
        course_id = CourseID(1)
        other_course_id = CourseID(2)

        registration_id = self.event.get_registration_id(
            self.key, self.user["id"], event_id
        )
        assert registration_id is not None

        self.event.set_registration(
            self.key,
            {
                "id": registration_id,
                "tracks": {1: {"course_instructor": course_id, "course_id": course_id}},
            },
        )

        registration = self.event.get_registration(self.key, registration_id)

        self.assertEqual(course_id, registration["tracks"][1]["course_instructor"])
        self.assertEqual(course_id, registration["tracks"][3]["course_instructor"])

        expectation = {
            1: (set(), {self.user["id"]}),
            3: ({9, 100}, {self.user["id"]}),
        }
        course_attendees = self.event.get_attendee_stats(self.key, course_id)

        self.assertEqual(len(expectation), len(course_attendees))
        for track_id, (learners, instructors) in expectation.items():
            self.assertEqual(
                learners,
                set(persona["id"] for persona in course_attendees[track_id].learners),
            )
            self.assertEqual(
                instructors,
                set(
                    persona["id"] for persona in course_attendees[track_id].instructors
                ),
            )

        with self.assertRaises(PrivilegeError):
            self.event.get_attendee_stats(self.key, other_course_id)
