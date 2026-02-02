#!/usr/bin/env python3

import datetime

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.past_event as models
from cdedb.common import nearly_now
from tests.common import BackendTest, as_users, event_keeper


class TestPastEventBackend(BackendTest):
    used_backends = ("core", "event", "pastevent")

    @as_users("vera")
    def test_entity_past_event(self) -> None:
        old_events = self.pastevent.list_past_events(self.key)
        data = models.PastEvent(
            id=vtypes.ID(-1),
            title="New Link Academy",
            shortname="link",
            institution=const.PastInstitutions(1),
            description="""Some more text

            on more lines.""",
            tempus=datetime.date(2000, 1, 1),
            participant_info=None,
        )
        new_id = self.pastevent.create_past_event(self.key, data.to_database())
        data.id = vtypes.ID(new_id)
        self.assertEqual(data, self.pastevent.get_past_event(self.key, new_id))
        data.title = "Alternate Universe Academy"
        self.pastevent.set_past_event(self.key, new_id, {'title': data.title})
        self.assertEqual(data, self.pastevent.get_past_event(self.key, new_id))
        self.assertNotIn(new_id, old_events)
        new_events = self.pastevent.list_past_events(self.key)
        self.assertIn(new_id, new_events)

    @as_users("vera")
    def test_delete_past_course_cascade(self) -> None:
        # create a log entry for this past course
        pcourse = self.pastevent.get_past_course(self.key, 1)
        pcourse.description = "changed"
        data = pcourse.to_database()
        data.pop("pevent_id")
        self.assertTrue(self.pastevent.set_past_course(self.key, data))
        # add the past course to a genesis case
        update = {'id': 3, 'pevent_id': 1, 'pcourse_id': 1}
        self.assertTrue(self.core.genesis_modify_case(self.key, update))

        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_course(
                self.key, 1, cascade=("genesis_cases",))
        self.assertIn("participants", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_course(
                self.key, 1, cascade=("participants",))
        self.assertIn("genesis_cases", e.exception.args[1].get('block'))
        with self.assertRaises(ValueError) as e:
            self.pastevent.delete_past_course(
                self.key, 1, cascade=("genesis_cases", "participants"))
        self.assertIn("log", e.exception.args[1].get('block'))
        self.pastevent.delete_past_course(
            self.key, 1, cascade=("participants", "genesis_cases", "log"))
        self.assertNotIn(1, self.pastevent.list_past_courses(self.key, 1))

    @as_users("vera")
    def test_delete_past_event_cascade(self) -> None:
        # create a log entry for this past event
        pevent = self.pastevent.get_past_event(self.key, 1)
        pevent.description = "changed"
        data = pevent.to_database()
        data.pop("id")
        self.assertTrue(self.pastevent.set_past_event(self.key, pevent.id, data))
        # add the past event to a genesis case
        update = {"id": 3, "pevent_id": 1}
        self.assertTrue(self.core.genesis_modify_case(self.key, update))

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
        pevent_id = vtypes.ID(1)
        expectation = {
            1: 'Swish -- und alles ist gut',
            2: 'Goethe zum Anfassen',
            3: 'Torheiten im Zwiebelrouter',
        }
        self.assertEqual(expectation, self.pastevent.list_past_courses(self.key))
        old_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        data = models.PastCourse(
            id=vtypes.ID(-1),
            pevent_id=pevent_id,
            nr='0',
            title="Topos theory for the kindergarden",
            description="""This is an interesting topic

            which will be treated.""",
        )
        new_id = self.pastevent.create_past_course(self.key, data.to_database())
        data.id = vtypes.ID(new_id)
        self.assertEqual(data, self.pastevent.get_past_course(self.key, new_id))
        data.title = "Alternate Universe Academy"
        self.pastevent.set_past_course(self.key, {'id': new_id, 'title': data.title})
        self.assertEqual(data, self.pastevent.get_past_course(self.key, new_id))
        self.assertNotIn(new_id, old_courses)
        new_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        self.assertIn(new_id, new_courses)
        self.pastevent.delete_past_course(self.key, new_id, cascade=("log", ))
        newer_courses = self.pastevent.list_past_courses(self.key, pevent_id)
        self.assertNotIn(new_id, newer_courses)

    @as_users("vera")
    def test_entity_participant(self) -> None:
        personas = self.core.get_personas(self.key, [2, 3, 4, 5, 6, 100])
        pevent = self.pastevent.get_past_event(self.key, 1)
        pcourses = self.pastevent.get_past_courses(self.key, [1, 2])
        expectation = {
            vtypes.ID(2): models.PastEventParticipant(id=vtypes.ID(1), persona_id=vtypes.ID(2), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.none, music_status=const.PastMusicKind.none,
                                           persona=personas[vtypes.ID(2)], pevent=pevent),
            vtypes.ID(3): models.PastEventParticipant(id=vtypes.ID(2), persona_id=vtypes.ID(3), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.none, music_status=const.PastMusicKind.ensemble,
                                           persona=personas[vtypes.ID(3)], pevent=pevent),
            vtypes.ID(4): models.PastEventParticipant(id=vtypes.ID(3), persona_id=vtypes.ID(4), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.none, music_status=const.PastMusicKind.none,
                                           persona=personas[vtypes.ID(4)], pevent=pevent),
            vtypes.ID(5): models.PastEventParticipant(id=vtypes.ID(4), persona_id=vtypes.ID(5), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.none, music_status=const.PastMusicKind.kuemu,
                                           persona=personas[vtypes.ID(5)], pevent=pevent),
            vtypes.ID(6): models.PastEventParticipant(id=vtypes.ID(5), persona_id=vtypes.ID(6), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.orga, music_status=const.PastMusicKind.none,
                                           persona=personas[vtypes.ID(6)], pevent=pevent),
            vtypes.ID(100): models.PastEventParticipant(id=vtypes.ID(6), persona_id=vtypes.ID(100), pevent_id=vtypes.ID(1), orga_status=const.PastOrgaKind.none, music_status=const.PastMusicKind.none,
                                             persona=personas[vtypes.ID(100)], pevent=pevent),
        }
        expectation[vtypes.ID(2)].course_assignments = [models.PastCourseAssignment(id=vtypes.ID(1), persona_id=vtypes.ID(2), participant_id=vtypes.ID(1), pcourse_id=vtypes.ID(1), instructor_status=const.PastInstructorKind.kl, pcourse=pcourses[1])]
        expectation[vtypes.ID(4)].course_assignments = [models.PastCourseAssignment(id=vtypes.ID(2), persona_id=vtypes.ID(4), participant_id=vtypes.ID(3), pcourse_id=vtypes.ID(2), instructor_status=const.PastInstructorKind.none, pcourse=pcourses[2])]
        expectation[vtypes.ID(5)].course_assignments = [models.PastCourseAssignment(id=vtypes.ID(3), persona_id=vtypes.ID(5), participant_id=vtypes.ID(4), pcourse_id=vtypes.ID(2), instructor_status=const.PastInstructorKind.none, pcourse=pcourses[2])]
        expectation[vtypes.ID(6)].course_assignments = [models.PastCourseAssignment(id=vtypes.ID(4), persona_id=vtypes.ID(6), participant_id=vtypes.ID(5), pcourse_id=vtypes.ID(2), instructor_status=const.PastInstructorKind.none, pcourse=pcourses[2])]
        expectation[vtypes.ID(100)].course_assignments = [models.PastCourseAssignment(id=vtypes.ID(5), persona_id=vtypes.ID(100), participant_id=vtypes.ID(6), pcourse_id=vtypes.ID(2), instructor_status=const.PastInstructorKind.none, pcourse=pcourses[2])]
        self.assertEqual((6, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # unset music status, keeps the courses
        self.pastevent.set_participant(self.key, pevent_id=1, persona_id=5)
        expectation[vtypes.ID(5)].music_status = const.PastMusicKind.none
        self.assertEqual((6, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # removing someone who is no participant does nothing
        self.assertEqual(0, self.pastevent.remove_participant(self.key, pevent_id=1, persona_id=1))
        self.assertEqual(0, self.pastevent.remove_course_assignment(self.key, pcourse_id=1, persona_id=1))
        self.assertEqual((6, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # remove participant also removes course assignment
        self.assertEqual(1, self.pastevent.remove_participant(self.key, pevent_id=1, persona_id=5))
        tmp = expectation.pop(vtypes.ID(5))
        self.assertEqual((5, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # add again as participant
        self.pastevent.set_participant(self.key, pevent_id=1, persona_id=5, orga_status=const.PastOrgaKind.al)
        expectation[vtypes.ID(5)] = tmp
        expectation[vtypes.ID(5)].id = vtypes.ID(1002)
        expectation[vtypes.ID(5)].orga_status = const.PastOrgaKind.al
        expectation[vtypes.ID(5)].course_assignments = []
        self.assertEqual((6, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # add to different course
        self.pastevent.set_course_assignments(self.key, pcourse_id=2, persona_id=5)
        expectation[vtypes.ID(5)].course_assignments.append(models.PastCourseAssignment(id=vtypes.ID(1001), persona_id=vtypes.ID(5), participant_id=vtypes.ID(1002), pcourse_id=vtypes.ID(2), pcourse=pcourses[vtypes.ID(2)], instructor_status=const.PastInstructorKind.none))
        self.assertEqual((6, expectation), self.pastevent.list_event_participants(self.key, pevent_id=1))

        # course assignment without participation not possible
        with self.assertRaises(ValueError) as cm:
            self.pastevent.set_course_assignments(self.key, pcourse_id=1, persona_id=1)
        self.assertIn(
            "This user does not participate at this event.", cm.exception.args[0])
        # mailinglist user can not be added to past event
        with self.assertRaises(ValueError) as cm:
            self.pastevent.set_participant(self.key, pevent_id=1, persona_id=10)
        self.assertIn(
            "This past event participant is no event user.", cm.exception.args[0])

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
        self.pastevent.set_past_event(self.key, new_id, {'title': "Alternate Universe Academy"})
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

        # now check it (first round)
        expectation = (
            {'id': 1001,
             'change_note': None,
             'code': const.PastEventLogCodes.event_created,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'pcourse_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1002,
             'change_note': None,
             'code': const.PastEventLogCodes.event_changed,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'pcourse_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1003,
             'change_note': None,
             'code': const.PastEventLogCodes.course_created,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'pcourse_id': 1001,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1004,
             'change_note': None,
             'code': const.PastEventLogCodes.course_changed,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'pcourse_id': 1001,
             'persona_id': None,
             'submitted_by': self.user['id']})
        self.assertLogEqual(expectation, 'past_event')

        # now, delete the course, add more log codes
        self.pastevent.delete_past_course(self.key, new_id, cascade=("log",))
        self.pastevent.set_participant(self.key, new_id, 5)
        self.pastevent.remove_participant(self.key, new_id, 5)

        # check the data, note that the log codes regarding the course are deleted
        expectation = (
            {'id': 1001,
             'change_note': None,
             'code': const.PastEventLogCodes.event_created,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'pcourse_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1002,
             'change_note': None,
             'code': const.PastEventLogCodes.event_changed,
             'ctime': nearly_now(),
             'pevent_id': 1001,
             'pcourse_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1005,
             'change_note': 'New improved title',
             'code': const.PastEventLogCodes.course_deleted,
             'ctime': nearly_now(),
             'pevent_id': 1,
             'pcourse_id': None,
             'persona_id': None,
             'submitted_by': self.user['id']},
            {'id': 1006,
             'change_note': None,
             'code': const.PastEventLogCodes.participant_set,
             'ctime': nearly_now(),
             'pevent_id': new_id,
             'pcourse_id': None,
             'persona_id': 5,
             'submitted_by': self.user['id']},
            {'id': 1007,
             'change_note': None,
             'code': const.PastEventLogCodes.participant_removed,
             'ctime': nearly_now(),
             'pevent_id': new_id,
             'pcourse_id': None,
             'persona_id': 5,
             'submitted_by': self.user['id']})
        self.assertLogEqual(expectation, 'past_event')

    @event_keeper
    @as_users("anton")
    def test_archive(self) -> None:
        # First, an event without participants
        self.event.set_event(self.key, event_id=2, data={'is_cancelled': True})
        with self.assertRaises(ValueError):
            self.pastevent.archive_event(self.key, 2)
        new_ids = self.pastevent.archive_event(self.key, 2, create_past_event=False)
        self.assertEqual(None, new_ids)

        # Event with participants
        event_id = 1
        update = {
            'registration_soft_limit': datetime.datetime(2001, 10, 30, 0, 0, 0,
                                                         tzinfo=datetime.UTC),
            'registration_hard_limit': datetime.datetime(2002, 10, 30, 0, 0, 0,
                                                         tzinfo=datetime.UTC),
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
        new_ids = self.pastevent.archive_event(self.key, event_id)
        assert new_ids is not None
        self.assertEqual(3, len(new_ids))
        pevent_data = list(self.pastevent.get_past_events(self.key, new_ids).values())

        # Warmup
        expectation = models.PastEvent(
            id=vtypes.ID(1002),
            description='Everybody come!',
            institution=const.PastInstitutions(1),
            title='Große Testakademie 2222 (Warmup)',
            shortname="TestAka (Wu)",
            tempus=datetime.date(2003, 2, 2),
            participant_info=None
        )
        self.assertEqual(expectation, pevent_data[2])
        self.assertEqual(
            set(),
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[2].id).values()))

        # Erste Hälfte
        expectation = models.PastEvent(
            id=vtypes.ID(1003),
            description='Everybody come!',
            institution=const.PastInstitutions(1),
            title='Große Testakademie 2222 (Erste Hälfte)',
            shortname="TestAka (1.H.)",
            tempus=datetime.date(2003, 11, 1),
            participant_info=None
        )
        self.assertEqual(expectation, pevent_data[1])
        expectation = {
            "Planetenretten für Anfänger",
            "Lustigsein für Fortgeschrittene",
            "Kurzer Kurs",
            "Langer Kurs",
            "Backup-Kurs",
            "Extra-Kurs",
        }
        self.assertEqual(
            expectation,
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[1].id).values()))
        _, participants = self.pastevent.list_event_participants(self.key, pevent_data[1].id)
        self.assertEqual(const.PastOrgaKind.orga, participants[7].orga_status)
        self.assertEqual(const.PastOrgaKind.none, participants[100].orga_status)
        self.assertEqual("Lustigsein für Fortgeschrittene", participants[7].course_assignments[0].pcourse.title)

        # Zweite Hälfte
        expectation = models.PastEvent(
            id=vtypes.ID(1004),
            description='Everybody come!',
            institution=const.PastInstitutions(1),
            title='Große Testakademie 2222 (Zweite Hälfte)',
            shortname="TestAka (2.H.)",
            tempus=datetime.date(2003, 11, 11),
            participant_info=None
        )
        self.assertEqual(expectation, pevent_data[0])
        expectation = {
            "Planetenretten für Anfänger",
            "Lustigsein für Fortgeschrittene",
            "Langer Kurs",
            "Extra-Kurs",
        }
        self.assertEqual(
            expectation,
            set(self.pastevent.list_past_courses(
                self.key, pevent_data[0].id).values()))
        _, participants = self.pastevent.list_event_participants(self.key, pevent_data[0].id)
        self.assertEqual(const.PastInstructorKind.kl, participants[5].course_assignments[0].instructor_status)
        self.assertEqual(const.PastInstructorKind.none, participants[100].course_assignments[0].instructor_status)
