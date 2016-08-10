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
    def test_entity_past_course(self, user):
        pevent_id = 1
        old_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        data = {
            'pevent_id': pevent_id,
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
                                'is_orga': False, 'persona_id': 2}}
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
        self.event.set_event(self.key, update)
        new_id, _ = self.pastevent.archive_event(self.key, 1)
        expectation = {
            'description': 'Everybody come!',
            'id': 2,
            'institution': 1,
            'title': 'Große Testakademie 2222',
            'shortname': "TestAka",}
        data = self.pastevent.get_past_event(self.key, new_id)
        self.assertIn(data['tempus'], {datetime.date(2003, 2, 2),
                                       datetime.date(2003, 11, 1),
                                       datetime.date(2003, 11, 11),})
        del data['tempus']
        self.assertEqual(expectation, data)
        expectation = {3: 'Planetenretten für Anfänger',
                       4: 'Lustigsein für Fortgeschrittene'}
        self.assertEqual(expectation,
                         self.pastevent.list_past_courses(self.key, new_id))
        expectation = {
            (7, 4): {'pcourse_id': 4,
                     'is_instructor': False,
                     'is_orga': True,
                     'persona_id': 7}}
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pcourse_id=4))

