#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime

import cdedb.database.constants as const
from cdedb.common import nearly_now
from cdedb.common.sorting import xsorted
from tests.common import BackendTest, as_users


class TestPastEventBackend(BackendTest):
    used_backends = ("core", "event", "pastevent")

    @as_users("vera", "berta")
    def test_participation_infos(self) -> None:
        participation_infos = self.pastevent.participation_infos(self.key, (1, 2))
        expectation = {
            1: dict(),
            2: {1: {'id': 1,
                    'persona_id': 2,
                    'is_orga': False,
                    'courses': {1: {'id': 1,
                                    'title': 'Swish -- und alles ist gut',
                                    'nr': '1a',
                                    'is_instructor': True,
                                    },
                                },
                    'title': 'PfingstAkademie 2014',
                    'tempus': datetime.date(2014, 5, 25),
                    },
                },
            }
        self.assertEqual(expectation, participation_infos)
        participation_info = self.pastevent.participation_info(self.key, 1)
        participation_infos = self.pastevent.participation_infos(self.key, (1,))
        self.assertEqual(participation_infos[1], participation_info)

    @as_users("vera")
    def test_entity_past_event(self) -> None:
        old_events = self.pastevent.list_past_events(self.key)
        data = {
            'title': "New Link Academy",
            'shortname': "link",
            'institution': 1,
            'description': """Some more text

            on more lines.""",
            'tempus': datetime.date(2000, 1, 1),
            'participant_info': None,
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

    @as_users("vera")
    def test_delete_past_course_cascade(self) -> None:
        self.assertIn(1, self.pastevent.list_past_courses(self.key, 1))
        # add the past course to a genesis case
        genesis_case = self.core.genesis_get_case(self.key, 3)
        genesis_case.update({
            'pevent_id': 1,
            'pcourse_id': 1,
            'reviewer': self.user['id']})
        self.assertTrue(self.core.genesis_modify_case(self.key, genesis_case))

        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_course(
                self.key, 1, cascade=("genesis_cases",))
        self.assertIn("participants", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_course(
                self.key, 1, cascade=("participants",))
        self.assertIn("genesis_cases", e.exception.args[1].get('block'))
        self.pastevent.delete_past_course(
            self.key, 1, cascade=("participants", "genesis_cases"))
        self.assertNotIn(1, self.pastevent.list_past_courses(self.key, 1))

    @as_users("vera")
    def test_delete_past_event_cascade(self) -> None:
        # create a log entry for this past event
        pevent = self.pastevent.get_past_event(self.key, 1)
        pevent['description'] = "changed"
        self.assertTrue(self.pastevent.set_past_event(self.key, pevent))
        # add the past event to a genesis case
        genesis_case = self.core.genesis_get_case(self.key, 3)
        genesis_case.update({
            'pevent_id': 1,
            'reviewer': self.user['id']})
        self.assertTrue(self.core.genesis_modify_case(self.key, genesis_case))

        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_event(
                self.key, 1, cascade=("participants", "log", "genesis_cases"))
        self.assertIn("courses", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_event(
                self.key, 1,
                cascade=("courses", "log", "genesis_cases"))
        self.assertIn("participants", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_event(
                self.key, 1,
                cascade=("courses", "participants", "genesis_cases"))
        self.assertIn("log", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_event(
                self.key, 1,
                cascade=("courses", "participants", "log"))
        self.assertIn("genesis_cases", e.exception.args[1].get('block'))
        self.pastevent.delete_past_event(
            self.key, 1, cascade=("courses", "participants", "log", "genesis_cases"))
        self.assertNotIn(1, self.pastevent.list_past_events(self.key))

    @as_users("vera")
    def test_entity_past_course(self) -> None:
        pevent_id = 1
        expectation = {
            1: 'Swish -- und alles ist gut',
            2: 'Goethe zum Anfassen',
            3: 'Torheiten im Zwiebelrouter',
        }
        self.assertEqual(expectation, self.pastevent.list_past_courses(self.key))
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

    @as_users("vera")
    def test_entity_participant(self) -> None:
        expectation = {
            (2, 1): {
                'pcourse_id': 1, 'is_instructor': True,
                'is_orga': False, 'persona_id': 2,
            },
            (3, None): {
                'pcourse_id': None, 'is_instructor': False,
                'is_orga': False, 'persona_id': 3,
            },
            (4, 2): {
                'pcourse_id': 2, 'is_instructor': False,
                'is_orga': False, 'persona_id': 4,
            },
            (5, 2): {
                'pcourse_id': 2, 'is_instructor': False,
                'is_orga': False, 'persona_id': 5,
            },
            (6, 2): {
                'pcourse_id': 2, 'is_instructor': False,
                'is_orga': True, 'persona_id': 6,
            },
            (100, 2): {
                'pcourse_id': 2, 'is_instructor': False,
                'is_orga': False, 'persona_id': 100,
            },
        }

        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pevent_id=1))
        self.pastevent.add_participant(self.key, 1, None, 5, False, False)
        expectation[(5, None)] = {
            'pcourse_id': None, 'is_instructor': False,
            'is_orga': False, 'persona_id': 5,
        }
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

        # past course not associated with specified past event
        with self.assertRaises(ValueError) as cm:
            self.pastevent.add_participant(self.key, 2, 1, 5, False, False)
        self.assertIn(
            "Course not associated with past event specified.", cm.exception.args[0])
        # mailinglist user can not be added to past event
        with self.assertRaises(ValueError) as cm:
            self.pastevent.add_participant(self.key, 1, 1, 10, False, False)
        self.assertIn(
            "This past event participant is no event user.", cm.exception.args[0])

    @as_users("vera")
    def test_participant_consistency(self) -> None:
        # See issue #1458
        participants = self.pastevent.list_participants(self.key, pevent_id=1)
        self.assertIn((3, None), participants)
        self.pastevent.add_participant(self.key, pevent_id=1, pcourse_id=2,
                                       persona_id=3)
        participants = self.pastevent.list_participants(self.key, pevent_id=1)
        self.assertNotIn((3, None), participants)
        self.assertIn((3, 2), participants)

    @as_users("vera")
    def test_past_log(self) -> None:
        # first generate some data
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

        # now check it
        expectation = (
            {'id': 1001,
             'change_note': None,
             'code': const.PastEventLogCodes.event_created,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1002,
             'change_note': None,
             'code': const.PastEventLogCodes.event_changed,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1003,
             'change_note': 'Topos theory for the kindergarden',
             'code': const.PastEventLogCodes.course_created,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1004,
             'change_note': 'New improved title',
             'code': const.PastEventLogCodes.course_changed,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1005,
             'change_note': 'New improved title',
             'code': const.PastEventLogCodes.course_deleted,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1006,
             'change_note': None,
             'code': const.PastEventLogCodes.participant_added,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'persona_id': 5,
             'submitted_by': self.user['id']},
            {'id': 1007,
             'change_note': None,
             'code': const.PastEventLogCodes.participant_removed,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'persona_id': 5,
             'submitted_by': self.user['id']})
        self.assertLogEqual(expectation, 'past_event')

    @as_users("anton")
    def test_archive(self) -> None:
        # First, an event without participants
        self.event.set_event(self.key, event_id=2, data={'is_cancelled': True})
        with self.assertRaises(ValueError):
            self.pastevent.archive_event(self.key, 2)
        new_ids, _ = self.pastevent.archive_event(self.key, 2, create_past_event=False)
        self.assertEqual(None, new_ids)

        # Event with participants
        event_id = 1
        update = {
            'registration_soft_limit': datetime.datetime(2001, 10, 30, 0, 0, 0,
                                                         tzinfo=datetime.timezone.utc),
            'registration_hard_limit': datetime.datetime(2002, 10, 30, 0, 0, 0,
                                                         tzinfo=datetime.timezone.utc),
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
                },
            },
        }
        self.event.set_event(self.key, event_id, update)
        new_ids, _ = self.pastevent.archive_event(self.key, event_id)
        assert new_ids is not None
        self.assertEqual(3, len(new_ids))
        pevent_data = xsorted(
            (self.pastevent.get_past_event(self.key, new_id)
             for new_id in new_ids),
            key=lambda d: d['tempus'])
        expectation = {
            'description': 'Everybody come!',
            'id': 1002,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Warmup)',
            'shortname': "TestAka (Wu)",
            'tempus': datetime.date(2003, 2, 2),
            'participant_info': None}
        self.assertEqual(expectation, pevent_data[0])
        expectation = {
            'description': 'Everybody come!',
            'id': 1003,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Erste Hälfte)',
            'shortname': "TestAka (1.H.)",
            'tempus': datetime.date(2003, 11, 1),
            'participant_info': None}
        self.assertEqual(expectation, pevent_data[1])
        expectation = {
            'description': 'Everybody come!',
            'id': 1004,
            'institution': 1,
            'title': 'Große Testakademie 2222 (Zweite Hälfte)',
            'shortname': "TestAka (2.H.)",
            'tempus': datetime.date(2003, 11, 11),
            'participant_info': None}
        self.assertEqual(expectation, pevent_data[2])
        self.assertEqual(
            set(),
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
            (7, 1008): {'pcourse_id': 1008,
                        'is_instructor': False,
                        'is_orga': True,
                        'persona_id': 7},
            (100, 1008): {'is_instructor': False,
                          'is_orga': False,
                          'pcourse_id': 1008,
                          'persona_id': 100}}
        self.assertEqual(expectation,
                         self.pastevent.list_participants(self.key, pcourse_id=1008))
