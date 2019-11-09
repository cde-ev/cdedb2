#!/usr/bin/env python3

import copy
import datetime
import decimal
import pytz

from test.common import BackendTest, as_users, USER_DICT, nearly_now
from cdedb.query import QUERY_SPECS, QueryOperators, Query
from cdedb.common import PERSONA_EVENT_FIELDS
import cdedb.database.constants as const


class TestPastEventBackend(BackendTest):
    used_backends = ("core", "event", "pastevent")

    @as_users("anton", "berta")
    def test_participation_infos(self, user):
        participation_infos = self.pastevent.participation_infos(self.key, (1, 2))
        expectation = {1: tuple(),
                       2: ({'persona_id': 2,
                            'is_orga': False,
                            'is_instructor': True,
                            'nr': '1a',
                            'course_name': 'Swish -- und alles ist gut',
                            'pevent_id': 1,
                            'event_name': 'PfingstAkademie 2014',
                            'tempus': datetime.date(2014, 5, 25),
                            'pcourse_id': 1},)}
        self.assertEqual(expectation, participation_infos)
        participation_info = self.pastevent.participation_info(self.key, 1)
        participation_infos = self.pastevent.participation_infos(self.key, (1,))
        self.assertEqual(participation_infos[1], participation_info)

    @as_users("anton")
    def test_entity_past_event(self, user):
        old_events = self.pastevent.list_past_events(self.key)
        data = {
            'title': "New Link Academy",
            'shortname': "link",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'tempus': datetime.date(2000, 1, 1),
            'notes': None,
        }
        new_id = self.pastevent.create_past_event(self.key, data)
        data['id'] = new_id
        self.assertEqual(data,
                         self.pastevent.get_past_event(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        self.pastevent.set_past_event(self.key, {
            'id': new_id, 'title': data['title']})
        self.assertEqual(data,
                         self.pastevent.get_past_event(self.key, new_id))
        self.assertNotIn(new_id, old_events)
        new_events = self.pastevent.list_past_events(self.key)
        self.assertIn(new_id, new_events)

    @as_users("anton")
    def test_delete_past_course_cascade(self, user):
        self.assertIn(1, self.pastevent.list_past_courses(self.key, 1))
        self.pastevent.delete_past_course(
            self.key, 1, cascade=("participants",))
        self.assertNotIn(1, self.pastevent.list_past_courses(self.key, 1))

    @as_users("anton")
    def test_delete_past_event_cascade(self, user):
        self.assertIn(1, self.pastevent.list_past_events(self.key))
        self.pastevent.delete_past_event(
            self.key, 1, cascade=("courses", "participants", "log"))
        self.assertNotIn(1, self.pastevent.list_past_events(self.key))

    @as_users("anton")
    def test_entity_past_course(self, user):
        pevent_id = 1
        old_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        data = {
            'pevent_id': pevent_id,
            'nr': '0',
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
        }
        new_id = self.pastevent.create_past_course(self.key, data)
        data['id'] = new_id
        self.assertEqual(data,
                         self.pastevent.get_past_course(self.key, new_id))
        data['title'] = "Alternate Universe Academy"
        self.pastevent.set_past_course(self.key, {
            'id': new_id, 'title': data['title']})
        self.assertEqual(data,
                         self.pastevent.get_past_course(self.key, new_id))
        self.assertNotIn(new_id, old_courses)
        new_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        self.assertIn(new_id, new_courses)
        self.pastevent.delete_past_course(self.key, new_id)
        newer_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        self.assertNotIn(new_id, newer_courses)

    @as_users("anton")
    def test_entity_participant(self, user):
        expectation = {(2, 1): {'pcourse_id': 1, 'is_instructor': True,
                                'is_orga': False, 'persona_id': 2},
                       (3, None): {'pcourse_id': None, 'is_instructor': False,
                                   'is_orga': False, 'persona_id': 3},
                       (5, 2): {'pcourse_id': 2, 'is_instructor': False,
                                'is_orga': False, 'persona_id': 5},
                       (6, 2): {'pcourse_id': 2, 'is_instructor': False,
                                'is_orga': True, 'persona_id': 6}}

        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.pastevent.add_participant(self.key, 1, None, 5, False, False)
        expectation[(5, None)] = {'pcourse_id': None, 'is_instructor': False,
                          'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.assertEqual(0, self.pastevent.remove_participant(self.key, 1, 1, 5))
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.assertEqual(1, self.pastevent.remove_participant(self.key, 1, None, 5))
        del expectation[(5, None)]
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.pastevent.add_participant(self.key, 1, 1, 5, False, False)
        expectation[(5, 1)] = {'pcourse_id': 1, 'is_instructor': False,
                               'is_orga': False, 'persona_id': 5}
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.assertEqual(0, self.pastevent.remove_participant(self.key, 1, None, 5))
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.assertEqual(1, self.pastevent.remove_participant(self.key, 1, 1, 5))
        del expectation[(5, 1)]
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))

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
        new_id = self.pastevent.create_past_event(self.key, data)
        self.pastevent.set_past_event(self.key, {
            'id': new_id, 'title': "Alternate Universe Academy"})
        data = {
            'pevent_id': 1,
            'nr': '0',
            'title': "Topos theory for the kindergarden",
            'description': """This is an interesting topic

            which will be treated.""",
        }
        new_id = self.pastevent.create_past_course(self.key, data)
        self.pastevent.set_past_course(self.key, {
            'id': new_id, 'title': "New improved title"})
        self.pastevent.delete_past_course(self.key, new_id)
        self.pastevent.add_participant(self.key, 1, None, 5, False, False)
        self.pastevent.remove_participant(self.key, 1, None, 5)

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
                        'code': 2,
                        'ctime': nearly_now(),
                        'pevent_id': 2,
                        'persona_id': None,
                        'submitted_by': 1},
                       {'additional_info': None,
                        'code': 1,
                        'ctime': nearly_now(),
                        'pevent_id': 2,
                        'persona_id': None,
                        'submitted_by': 1})
        self.assertEqual(expectation, self.pastevent.retrieve_past_log(self.key))

    @as_users("anton")
    def test_archive(self, user):
        update = {
            'id': 1,
            'registration_soft_limit': datetime.datetime(2001, 10, 30, 0, 0, 0, tzinfo=pytz.utc),
            'registration_hard_limit': datetime.datetime(2002, 10, 30, 0, 0, 0, tzinfo=pytz.utc),
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
        self.event.set_event(self.key, update)
        new_ids, _ = self.pastevent.archive_event(self.key, 1)
        self.assertEqual(3, len(new_ids))
        pevent_data = sorted(
            (self.pastevent.get_past_event(self.key, new_id)
             for new_id in new_ids),
            key=lambda d: d['tempus'])
        expectation = {
            'description': 'Everybody come!',
            'id': 2,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Warmup)',
            'shortname': "TestAka (Wu)",
            'tempus': datetime.date(2003, 2, 2),
            'notes': None, }
        self.assertEqual(expectation, pevent_data[0])
        expectation = {
            'description': 'Everybody come!',
            'id': 3,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Erste Hälfte)',
            'shortname': "TestAka (1.H.)",
            'tempus': datetime.date(2003, 11, 1),
            'notes': None, }
        self.assertEqual(expectation, pevent_data[1])
        expectation = {
            'description': 'Everybody come!',
            'id': 4,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Zweite Hälfte)',
            'shortname': "TestAka (2.H.)",
            'tempus': datetime.date(2003, 11, 11),
            'notes': None, }
        self.assertEqual(expectation, pevent_data[2])
        expectation = set()
        self.assertEqual(
            expectation,
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[0]['id']).values()))
        expectation = {'Lustigsein für Fortgeschrittene'}
        self.assertEqual(
            expectation,
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[1]['id']).values()))
        expectation = {'Planetenretten für Anfänger'}
        self.assertEqual(
            expectation,
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[2]['id']).values()))
        expectation = {
            (7, 9): {'pcourse_id': 9,
                     'is_instructor': False,
                     'is_orga': True,
                     'persona_id': 7}}
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pcourse_id=9))

