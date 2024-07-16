#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import json
from typing import Collection, List, NamedTuple, Optional

import freezegun

import cdedb.database.constants as const
from cdedb.backend.assembly import BallotConfiguration
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, PrivilegeError, get_hash, nearly_now, now,
)
from cdedb.common.query import Query, QueryScope
from cdedb.common.query.log_filter import AssemblyLogFilter
from tests.common import (
    USER_DICT, BackendTest, UserIdentifier, as_users, execsql, get_user, prepsql,
    storage,
)


class TestAssemblyBackend(BackendTest):
    used_backends = ("core", "assembly")

    def _get_sample_quorum(self, assembly_id: int) -> int:
        attendees = {
            e['persona_id'] for e in self.get_sample_data('assembly.attendees').values()
            if e['assembly_id'] == assembly_id}
        return sum(
            1 for e in self.get_sample_data('core.personas').values()
            if e['is_member'] or e['id'] in attendees)

    @as_users("kalif")
    def test_basics(self) -> None:
        data = self.core.get_assembly_user(self.key, self.user['id'])
        data['display_name'] = "Zelda"
        data['family_name'] = "Lord von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'given_names', 'family_name'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_assembly_user(self.key, self.user['id'])
        self.assertEqual(data, new_data)

        with self.assertRaises(ValueError):
            self.assembly.get_assembly_id(self.key)

        with self.assertRaises(ValueError):
            self.assembly.check_attendance(self.key)
        with self.assertRaises(ValueError):
            self.assembly.check_attendance(self.key, assembly_id=1, ballot_id=1)
        with self.switch_user("emilia"):
            with self.assertRaises(PrivilegeError):
                self.assembly.check_attendance(self.key, assembly_id=1, persona_id=1)

        query = Query(
            QueryScope.core_user,
            QueryScope.core_user.get_spec(),
            [],
            [],
            [],
        )
        with self.assertRaises(RuntimeError):
            self.assembly.submit_general_query(self.key, query)

    @as_users("viktor")
    def test_archived_user_search(self) -> None:
        # Search for pure assembly users.
        query = Query(
            QueryScope.assembly_user,
            QueryScope.assembly_user.get_spec(),
            ["given_names"],
            [],
            [("given_names", True)],
        )
        self.assertFalse(query.scope.includes_archived)

        # Check that all users are found.
        self.assertEqual(
            ["Kalif ibn al-Ḥasan", "Rowena"],
            [
                e["given_names"]
                for e in self.assembly.submit_general_query(self.key, query)
            ],
        )

        # Archive one user.
        self.core.archive_persona(self.key, get_user("rowena")['id'], "For testing.")

        # Check that they are no longer found.
        self.assertEqual(
            ["Kalif ibn al-Ḥasan"],
            [
                e["given_names"]
                for e in self.assembly.submit_general_query(self.key, query)
            ],
        )

        # Check that the more inclusive search still finds them.
        query.scope = QueryScope.all_assembly_users
        self.assertEqual(
            ["Kalif ibn al-Ḥasan", "Rowena"],
            [
                e["given_names"]
                for e in self.assembly.submit_general_query(self.key, query)
            ],
        )

    @as_users("anton", "berta", "charly", "kalif")
    def test_does_attend(self) -> None:
        self.assertEqual(self.user['id'] != 3, self.assembly.does_attend(
            self.key, assembly_id=1))
        self.assertEqual(self.user['id'] != 3, self.assembly.does_attend(
            self.key, ballot_id=3))

    @as_users("charly")
    def test_list_attendees(self) -> None:
        assembly_id = 1
        expectation = {1, 2, 9, 11, 23, 100}
        self.assertEqual(
            expectation,
            self.assembly.list_attendees(self.key, assembly_id))
        self.assertNotIn(self.user['id'], expectation)
        self.assertTrue(self.assembly.signup(self.key, assembly_id))
        expectation.add(self.user['id'])
        self.assertEqual(
            expectation,
            self.assembly.list_attendees(self.key, assembly_id))

    @storage
    def test_entity_assembly(self) -> None:
        assembly_id = 1
        presider_id = 23
        log = []
        self.login("anton")
        log_offset, _ = self.assembly.retrieve_log(self.key, AssemblyLogFilter())
        self.login("werner")

        expectation = {
            1: {
                'id': 1,
                'is_active': True,
                'signup_end': datetime.datetime(
                    2111, 11, 11, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Internationaler Kongress',
            },
            2: {
                'id': 2,
                'is_active': False,
                'signup_end': datetime.datetime(
                    2020, 2, 22, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Kanonische Beispielversammlung',
            },
            3: {
                'id': 3,
                'is_active': True,
                'signup_end': datetime.datetime(
                    2222, 2, 22, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Archiv-Sammlung',
            },
        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))
        expectation = self.get_sample_datum("assembly.assemblies", assembly_id)
        expectation['presiders'] = {presider_id}
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, assembly_id))
        data = {
            'id': assembly_id,
            'notes': "More fun for everybody",
            'signup_end': datetime.datetime(
                2111, 11, 11, 23, 0, tzinfo=datetime.timezone.utc),
            'title': "Allumfassendes Konklave",
            'shortname': 'konklave',
        }
        self.assertLess(0, self.assembly.set_assembly(self.key, data))
        log.append({
            "code": const.AssemblyLogCodes.assembly_changed,
            "submitted_by": self.user['id'],
            "assembly_id": assembly_id,
        })
        expectation.update(data)
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, 1))
        new_assembly = {
            'description': 'Beschluss über die Anzahl anzuschaffender Schachsets',
            'notes': None,
            'signup_end': now(),
            'title': 'Außerordentliche Mitgliederversammlung',
            'shortname': 'amgv',
            'presiders': {1, presider_id},
        }
        self.login("viktor")
        new_id = self.assembly.create_assembly(self.key, new_assembly)
        log.append({
            "code": const.AssemblyLogCodes.assembly_created,
            "submitted_by": self.user['id'],
            "assembly_id": new_id,
        })
        for p_id in new_assembly['presiders']:  # type: ignore[union-attr]
            log.append({
                "code": const.AssemblyLogCodes.assembly_presider_added,
                "submitted_by": self.user['id'],
                "assembly_id": new_id,
                "persona_id": p_id,
            })
        expectation: CdEDBObject = new_assembly
        expectation['id'] = new_id
        expectation['presider_address'] = None
        expectation['is_active'] = True
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, new_id))
        self.assertTrue(
            self.assembly.remove_assembly_presider(self.key, new_id, presider_id))
        log.append({
            "code": const.AssemblyLogCodes.assembly_presider_removed,
            "submitted_by": self.user['id'],
            "assembly_id": new_id,
            "persona_id": presider_id,
        })
        self.assertTrue(
            self.assembly.add_assembly_presiders(self.key, new_id, {presider_id}))
        log.append({
            "code": const.AssemblyLogCodes.assembly_presider_added,
            "submitted_by": self.user['id'],
            "assembly_id": new_id,
            "persona_id": presider_id,
        })
        # Check return of setting presiders to the same thing.
        self.assertEqual(
            0, self.assembly.add_assembly_presiders(self.key, new_id, {presider_id}))
        expectation['presiders'] = {1, presider_id}
        self.assertEqual(expectation, self.assembly.get_assembly(self.key, new_id))
        attachment_data = {
            "assembly_id": new_id,
            "title": "Rechenschaftsbericht",
            "authors": "Farin",
            "filename": "rechen.pdf",
        }
        self.assertTrue(self.assembly.add_attachment(self.key, attachment_data, b'123'))
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "submitted_by": self.user['id'],
            "assembly_id": new_id,
            "change_note": attachment_data['title'],
        })
        self.assertEqual({}, self.assembly.conclude_assembly_blockers(self.key, new_id))
        self.assertTrue(self.assembly.conclude_assembly(self.key, new_id))
        log.append({
            "code": const.AssemblyLogCodes.assembly_concluded,
            "submitted_by": self.user['id'],
            "assembly_id": new_id,
        })
        self.assertLogEqual(log, realm="assembly", offset=log_offset)

        cascade = {"assembly_is_locked", "log", "presiders", "attachments"}
        self.assertEqual(
            cascade, self.assembly.delete_assembly_blockers(self.key, new_id).keys())
        self.assertLess(0, self.assembly.delete_assembly(self.key, new_id, cascade))
        log = log[:1] + [{
            "assembly_id": None,
            "code": const.AssemblyLogCodes.assembly_deleted,
            "submitted_by": self.user['id'],
            "change_note": expectation["title"],
        }]
        self.assertLogEqual(log, realm="assembly", offset=log_offset)

    @as_users("viktor")
    def test_ticket_176(self) -> None:
        data = {
            'description': None,
            'notes': None,
            'signup_end': now(),
            'title': 'Außerordentliche Mitgliederversammlung',
            'shortname': 'amgv',
        }
        new_id = self.assembly.create_assembly(self.key, data)
        self.assertLess(0, self.assembly.conclude_assembly(self.key, new_id))

    @storage
    @as_users("werner")
    def test_entity_ballot(self) -> None:
        assembly_id = 1
        log_offset, _ = self.assembly.retrieve_log(
            self.key, AssemblyLogFilter(assembly_id=assembly_id))
        log: List[CdEDBObject] = []
        expectation = {1: 'Antwort auf die letzte aller Fragen',
                       2: 'Farbe des Logos',
                       3: 'Bester Hof',
                       4: 'Akademie-Nachtisch',
                       5: 'Lieblingszahl',
                       11: 'Antrag zur DSGVO 2.0',
                       12: 'Eine aktuell wichtige Frage',
                       13: 'Wahl des Innenvorstand',
                       14: 'Wie sollen Akademien sich in Zukunft finanzieren',
                       15: 'Welche Sprache ist die Beste?',
                       }
        self.assertEqual(expectation, self.assembly.list_ballots(self.key, assembly_id))
        expectation = {
            1: {
                'assembly_id': 1,
                'use_bar': True,
                'candidates': {
                    2: {
                        'ballot_id': 1,
                        'title': 'Ich',
                        'id': 2,
                        'shortname': '1',
                    },
                    3: {
                        'ballot_id': 1,
                        'title': '23',
                        'id': 3,
                        'shortname': '2',
                    },
                    4: {
                        'ballot_id': 1,
                        'title': '42',
                        'id': 4,
                        'shortname': '3',
                    },
                    5: {
                        'ballot_id': 1,
                        'title': 'Philosophie',
                        'id': 5,
                        'shortname': '4',
                    },
                },
                'comment': None,
                'description': 'Nach dem Leben, dem Universum und dem ganzen Rest.',
                'extended': True,
                'id': 1,
                'is_locked': True,
                'is_voting': False,
                'is_tallied': False,
                'notes': None,
                'abs_quorum': 2,
                'rel_quorum': 0,
                'quorum': 2,
                'title': 'Antwort auf die letzte aller Fragen',
                'vote_begin': datetime.datetime(2002, 2, 22, 20, 22, 22, 222222,
                                                tzinfo=datetime.timezone.utc),
                'vote_end': datetime.datetime(2002, 2, 23, 20, 22, 22, 222222,
                                              tzinfo=datetime.timezone.utc),
                'vote_extension_end': nearly_now(),
                'votes': None,
            },
            4: {
                'assembly_id': 1,
                'use_bar': True,
                'candidates': {
                    17: {
                        'ballot_id': 4,
                        'title': 'Wackelpudding',
                        'id': 17,
                        'shortname': 'W',
                    },
                    18: {
                        'ballot_id': 4,
                        'title': 'Salat',
                        'id': 18,
                        'shortname': 'S',
                    },
                    19: {
                        'ballot_id': 4,
                        'title': 'Eis',
                        'id': 19,
                        'shortname': 'E',
                    },
                    20: {
                        'ballot_id': 4,
                        'title': 'Joghurt',
                        'id': 20,
                        'shortname': 'J',
                    },
                    21: {
                        'ballot_id': 4,
                        'title': 'Nichts',
                        'id': 21,
                        'shortname': 'N',
                    },
                },
                'comment': None,
                'description': 'denkt an die Frutaner',
                'extended': None,
                'id': 4,
                'is_locked': True,
                'is_voting': True,
                'is_tallied': False,
                'notes': None,
                'abs_quorum': 0,
                'rel_quorum': 0,
                'quorum': 0,
                'title': 'Akademie-Nachtisch',
                'vote_begin': nearly_now(),
                'vote_end': datetime.datetime(2222, 1, 1, 20, 22, 22, 222222,
                                              tzinfo=datetime.timezone.utc),
                'vote_extension_end': None,
                'votes': 2,
            },
        }
        self.assertEqual(
            expectation, self.assembly.get_ballots(self.key, (1, 4)))
        data = {
            'id': 4,
            'notes': "Won't work",
        }
        with self.assertRaises(ValueError):
            self.assembly.set_ballot(self.key, data)
        ballot_id = 2
        expectation: CdEDBObject = {
            'assembly_id': assembly_id,
            'use_bar': False,
            'candidates': {6: {'ballot_id': ballot_id,
                               'title': 'Rot',
                               'id': 6,
                               'shortname': 'rot'},
                           7: {'ballot_id': ballot_id,
                               'title': 'Gelb',
                               'id': 7,
                               'shortname': 'gelb'},
                           8: {'ballot_id': ballot_id,
                               'title': 'Grün',
                               'id': 8,
                               'shortname': 'gruen'},
                           9: {'ballot_id': ballot_id,
                               'title': 'Blau',
                               'id': 9,
                               'shortname': 'blau'}},
            'comment': None,
            'description': 'Ulitmativ letzte Entscheidung',
            'extended': None,
            'id': ballot_id,
            'is_locked': False,
            'is_voting': False,
            'is_tallied': False,
            'notes': 'Nochmal alle auf diese wichtige Entscheidung hinweisen.',
            'abs_quorum': 0,
            'rel_quorum': 83,
            'quorum': 10,
            'title': 'Farbe des Logos',
            'vote_begin': datetime.datetime(2222, 2, 2, 20, 22, 22,
                                            tzinfo=datetime.timezone.utc),
            'vote_end': datetime.datetime(2222, 2, 3, 20, 22, 22,
                                          tzinfo=datetime.timezone.utc),
            'vote_extension_end': datetime.datetime(2222, 2, 4, 20, 22, 22,
                                                    tzinfo=datetime.timezone.utc),
            'votes': None}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, ballot_id))
        data: CdEDBObject = {
            'id': ballot_id,
            'use_bar': True,
            'candidates': {
                6: {'title': 'Teracotta', 'shortname': 'terra'},
                7: None,
                -1: {'title': 'Aquamarin', 'shortname': 'aqua'},
            },
            'notes': "foo",
            'vote_extension_end': datetime.datetime(2222, 2, 20, 20, 22, 22, 222222,
                                                    tzinfo=datetime.timezone.utc),
            'rel_quorum': 100,
        }
        self.assertLess(0, self.assembly.set_ballot(self.key, data))
        log.extend((
            {
                "code": const.AssemblyLogCodes.ballot_changed,
                "assembly_id": assembly_id,
                "change_note": self.get_sample_datum(
                    "assembly.ballots", ballot_id)['title'],
            }, {
                "code": const.AssemblyLogCodes.candidate_added,
                "assembly_id": assembly_id,
                "change_note": data['candidates'][-1]['shortname'],
            }, {
                "code": const.AssemblyLogCodes.candidate_updated,
                "assembly_id": assembly_id,
                "change_note": expectation['candidates'][6]['shortname'],
            }, {
                "code": const.AssemblyLogCodes.candidate_removed,
                "assembly_id": assembly_id,
                "change_note": expectation['candidates'][7]['shortname'],
            },
        ))
        for key in ('use_bar', 'notes', 'vote_extension_end', 'rel_quorum'):
            expectation[key] = data[key]
        expectation['abs_quorum'] = 0
        expectation['quorum'] = self._get_sample_quorum(assembly_id)
        expectation['candidates'][6]['title'] = data['candidates'][6]['title']
        expectation['candidates'][6]['shortname'] = data['candidates'][6]['shortname']
        del expectation['candidates'][7]
        expectation['candidates'][1001] = {
            'id': 1001,
            'ballot_id': 2,
            'title': 'Aquamarin',
            'shortname': 'aqua'}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, 2))

        data: CdEDBObject = {
            'assembly_id': assembly_id,
            'use_bar': False,
            'candidates': {
                -1: {'title': 'Ja', 'shortname': 'j'},
                -2: {'title': 'Nein', 'shortname': 'n'},
            },
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'abs_quorum': 10,
            'rel_quorum': 0,
            'title': 'Verstehen wir Spaß',
            'vote_begin': datetime.datetime(2222, 2, 5, 13, 22, 22, 222222,
                                            tzinfo=datetime.timezone.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222,
                                          tzinfo=datetime.timezone.utc),
            'vote_extension_end': datetime.datetime(2222, 2, 7, 13, 22, 22, 222222,
                                                    tzinfo=datetime.timezone.utc),
            'votes': None,
        }
        new_id = self.assembly.create_ballot(self.key, data)
        log.extend((
            {
                "code": const.AssemblyLogCodes.ballot_created,
                "assembly_id": assembly_id,
                "change_note": data['title'],
            },
            *({
                "code": const.AssemblyLogCodes.candidate_added,
                "assembly_id": assembly_id,
                "change_note": data['candidates'][cid]['shortname'],
            } for cid in (-1, -2)),
        ))
        self.assertLess(0, new_id)
        data.update({
            'comment': None,
            'extended': None,
            'quorum': 10,
            'id': new_id,
            'is_locked': False,
            'is_voting': False,
            'is_tallied': False,
            'candidates': {
                1002: {
                    'ballot_id': new_id,
                    'title': 'Ja',
                    'id': 1002,
                    'shortname': 'j',
                },
                1003: {
                    'ballot_id': new_id,
                    'title': 'Nein',
                    'id': 1003,
                    'shortname': 'n',
                },
            },
        })
        self.assertEqual(data, self.assembly.get_ballot(self.key, new_id))
        old_ballot_id = 2
        old_ballot_data = self.get_sample_datum("assembly.ballots", old_ballot_id)

        # differentiate attachments by title to test stable sorting
        attachment_data = [{
            "assembly_id": assembly_id,
            "title": "Rechenschaftsbericht" + str(n),
            "authors": "Farin",
            "filename": "rechen.pdf",
        } for n in range(4)]

        # First, we'll modify both ballots symmetrically.
        # dict order is stable, i.e. list(ballots) == [old_ballot_id, new_id]
        ballots = {
            old_ballot_id: old_ballot_data,
            new_id: data,
        }

        # simply add one attachment and link it
        attachment_id = self.assembly.add_attachment(
            self.key, attachment_data[0], b'123')
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": attachment_data[0]['title'],
        })
        for bid, bdata in ballots.items():
            self.assertTrue(
                self.assembly.add_attachment_ballot_link(self.key, attachment_id, bid))
            log.append({
                "code": const.AssemblyLogCodes.attachment_ballot_link_created,
                "assembly_id": assembly_id,
                "change_note": f"{attachment_data[0]['title']} ({bdata['title']})",
            })

        self.assertEqual(
            list(ballots),
            self.assembly.get_attachment(self.key, attachment_id)['ballot_ids'])
        for bid in ballots:
            self.assertEqual(
                {attachment_id},
                self.assembly.list_attachments(self.key, ballot_id=bid))

        # add and link two more attachments
        attachment_id1 = self.assembly.add_attachment(
            self.key, attachment_data[1], b'123')
        attachment_id2 = self.assembly.add_attachment(
            self.key, attachment_data[2], b'123')
        log.extend({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": attachment_data[n]['title'],
        } for n in (1, 2))
        for bid, bdata in ballots.items():
            self.assertTrue(
                self.assembly.set_ballot_attachments(
                    self.key, bid, [attachment_id, attachment_id2, attachment_id1]))
            # Two of three links are new, they were added ordered by their ids.
            log.extend({
                "code": const.AssemblyLogCodes.attachment_ballot_link_created,
                "assembly_id": assembly_id,
                "change_note": f"{attachment_data[n]['title']} ({bdata['title']})",
            } for n in (1, 2))

        for aid in (attachment_id, attachment_id1, attachment_id2):
            self.assertEqual(
                list(ballots),
                self.assembly.get_attachment(self.key, aid)['ballot_ids'])
        for bid in ballots:
            self.assertEqual(
                {attachment_id, attachment_id1, attachment_id2},
                self.assembly.list_attachments(self.key, ballot_id=bid))

        # add and link another attachment, unlink two attachments
        attachment_id3 = self.assembly.add_attachment(
            self.key, attachment_data[3], b'123')
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": attachment_data[3]['title'],
        })
        for bid, bdata in ballots.items():
            self.assertTrue(
                self.assembly.set_ballot_attachments(
                    self.key, bid, {attachment_id1, attachment_id3}))
            # link removal also sorted by attachment_id
            log.extend((
                {
                    "code": const.AssemblyLogCodes.attachment_ballot_link_created,
                    "assembly_id": assembly_id,
                    "change_note": f"{attachment_data[3]['title']} ({bdata['title']})",
                },
                *({
                    "code": const.AssemblyLogCodes.attachment_ballot_link_deleted,
                    "assembly_id": assembly_id,
                    "change_note": f"{attachment_data[n]['title']} ({bdata['title']})",
                } for n in (0, 2)),
            ))

        for aid in (attachment_id, attachment_id2):
            self.assertEqual(
                [],
                self.assembly.get_attachment(self.key, aid)['ballot_ids'])
        for aid in (attachment_id1, attachment_id3):
            self.assertEqual(
                list(ballots),
                self.assembly.get_attachment(self.key, aid)['ballot_ids'])
        for bid in ballots:
            self.assertEqual(
                {attachment_id1, attachment_id3},
                self.assembly.list_attachments(self.key, ballot_id=bid))

        cascade = {"attachments", "candidates", "voters"}
        for bid in ballots:
            self.assertEqual(
                cascade,
                self.assembly.delete_ballot_blockers(self.key, bid).keys())

        # now the symmetry ends
        self.assertTrue(
            self.assembly.delete_ballot(self.key, old_ballot_id, cascade=cascade))
        log.append({
            "code": const.AssemblyLogCodes.ballot_deleted,
            "assembly_id": assembly_id,
            "change_note": old_ballot_data['title'],
        })
        for aid in (attachment_id1, attachment_id3):
            self.assertEqual(
                [new_id],
                self.assembly.get_attachment(self.key, aid)['ballot_ids'])
        expectation = {
            1: 'Antwort auf die letzte aller Fragen',
            3: 'Bester Hof',
            4: 'Akademie-Nachtisch',
            5: 'Lieblingszahl',
            11: 'Antrag zur DSGVO 2.0',
            12: 'Eine aktuell wichtige Frage',
            13: 'Wahl des Innenvorstand',
            14: 'Wie sollen Akademien sich in Zukunft finanzieren',
            15: 'Welche Sprache ist die Beste?',
            new_id: 'Verstehen wir Spaß'}
        self.assertEqual(expectation, self.assembly.list_ballots(self.key, assembly_id))
        self.assertLogEqual(
            log, realm="assembly", offset=log_offset, assembly_id=assembly_id)

    @as_users("werner")
    def test_quorum(self) -> None:
        data = {
            'assembly_id': 1,
            'use_bar': False,
            'candidates': {
                -1: {'title': 'Ja', 'shortname': 'j'},
                -2: {'title': 'Nein', 'shortname': 'n'},
            },
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'abs_quorum': 10,
            'title': 'Verstehen wir Spaß',
            'vote_begin': datetime.datetime(2222, 2, 5, 13, 22, 22, 222222,
                                            tzinfo=datetime.timezone.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222,
                                          tzinfo=datetime.timezone.utc),
            'vote_extension_end': None,
            'votes': None}
        with self.assertRaises(ValueError):
            self.assembly.create_ballot(self.key, data)

        data['abs_quorum'] = 0
        data['vote_extension_end'] = datetime.datetime(2222, 2, 7, 13, 22, 22, 222222,
                                                       tzinfo=datetime.timezone.utc)
        with self.assertRaises(ValueError):
            self.assembly.create_ballot(self.key, data)

        # now create the ballot
        data['abs_quorum'] = 10
        new_id = self.assembly.create_ballot(self.key, data)

        data = {
            'id': new_id,
            'abs_quorum': 0,
        }
        with self.assertRaises(ValueError):
            self.assembly.set_ballot(self.key, data)

        data = {
            'id': new_id,
            'vote_extension_end': None,
        }
        with self.assertRaises(ValueError):
            self.assembly.set_ballot(self.key, data)

        data = {
            'id': new_id,
            'abs_quorum': 0,
            'vote_extension_end': None,
        }
        self.assembly.set_ballot(self.key, data)

    @as_users("viktor")
    def test_relative_quorum(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            NUMBER_OF_MEMBERS = self._get_sample_quorum(0)
            assembly_data = {
                'description': None,
                'notes': None,
                'signup_end': datetime.datetime(2222, 2, 22),
                'title': "MGV 2222",
                'shortname': "mgv2222",
            }
            assembly_id = self.assembly.create_assembly(self.key, assembly_data)
            ballot_data = {
                'assembly_id': assembly_id,
                'use_bar': False,
                'candidates': {
                    -1: {'title': 'Ja', 'shortname': 'j'},
                    -2: {'title': 'Nein', 'shortname': 'n'},
                },
                'description': 'Sind sie sich sicher?',
                'notes': None,
                'rel_quorum': 100,
                'title': 'Verstehen wir Spaß',
                'vote_begin': base_time + delta,
                'vote_end': base_time + 3*delta,
                'vote_extension_end': base_time + 5*delta,
            }
            ballot_id = self.assembly.create_ballot(self.key, ballot_data)

            # noinspection PyTypedDict
            ballot_data['rel_quorum'] = 3.141
            with self.assertRaises(ValueError) as cm:
                self.assembly.create_ballot(self.key, ballot_data)
            self.assertIn("Precision loss.", cm.exception.args[0])
            ballot_data['rel_quorum'] = -5
            with self.assertRaises(ValueError) as cm:
                self.assembly.create_ballot(self.key, ballot_data)
            self.assertIn("Relative quorum must be between 0 and 100.",
                          cm.exception.args[0])
            ballot_data['rel_quorum'] = 168
            with self.assertRaises(ValueError) as cm:
                self.assembly.create_ballot(self.key, ballot_data)
            self.assertIn("Relative quorum must be between 0 and 100.",
                          cm.exception.args[0])

            # Initial quorum should be number of members.
            self.assertEqual(
                self.assembly.get_ballot(self.key, ballot_id)["quorum"],
                NUMBER_OF_MEMBERS,
            )

            # Adding a non-member attendee increases the quorum.
            self.assembly.external_signup(self.key, assembly_id, 4)
            self.assertEqual(
                self.assembly.get_ballot(self.key, ballot_id)["quorum"],
                NUMBER_OF_MEMBERS + 1,
            )

            frozen_time.tick(delta=4*delta)
            self.assembly.check_voting_period_extension(self.key, ballot_id)
            # Now adding an attendee does not change the quorum.
            self.assembly.external_signup(self.key, assembly_id, 11)
            self.assertEqual(
                self.assembly.get_ballot(self.key, ballot_id)["quorum"],
                NUMBER_OF_MEMBERS + 1,
            )

    def test_extension(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            self.login(USER_DICT['werner'])
            data = {
                'assembly_id': 1,
                'use_bar': False,
                'candidates': {
                    -1: {'title': 'Ja', 'shortname': 'j'},
                    -2: {'title': 'Nein', 'shortname': 'n'},
                },
                'description': 'Sind sie sich sicher?',
                'notes': None,
                'abs_quorum': 10,
                'title': 'Verstehen wir Spaß',
                'vote_begin': base_time + delta,
                'vote_end': base_time + 3*delta,
                'vote_extension_end': base_time + 5*delta,
                'votes': None,
            }
            new_id = self.assembly.create_ballot(self.key, data)
            self.assertEqual(None,
                             self.assembly.get_ballot(self.key, new_id)['extended'])

            frozen_time.tick(delta=4*delta)
            self.login(USER_DICT['kalif'])
            self.assertTrue(
                self.assembly.check_voting_period_extension(self.key, new_id))
            self.assertEqual(True,
                             self.assembly.get_ballot(self.key, new_id)['extended'])

    @as_users("charly")
    def test_signup(self) -> None:
        self.assertFalse(self.assembly.does_attend(self.key, assembly_id=1))
        secret = self.assembly.signup(self.key, 1)
        assert secret is not None
        self.assertLess(0, len(secret))
        self.assertTrue(self.assembly.does_attend(self.key, assembly_id=1))

    def test_get_vote(self) -> None:
        testcase = NamedTuple(
            "testcase", [
                ("user", UserIdentifier), ("ballot_id", int),
                ("secret", Optional[str]), ("vote", Optional[str])])
        tests: Collection[testcase] = (
            testcase('anton', 1, 'aoeuidhtns', '2>3>_bar_>1=4'),
            testcase('berta', 1, 'snthdiueoa', '3>2=4>_bar_>1'),
            testcase('inga', 1, 'asonetuhid', '_bar_>4>3>2>1'),
            testcase('kalif', 1, 'bxronkxeud', '1>2=3=4>_bar_'),
            testcase('anton', 1, None, '2>3>_bar_>1=4'),
            testcase('berta', 1, None, '3>2=4>_bar_>1'),
            testcase('inga', 1, None, '_bar_>4>3>2>1'),
            testcase('kalif', 1, None, '1>2=3=4>_bar_'),
            testcase('berta', 2, None, None),
            testcase('berta', 3, None, 'Lo>Li=St=Fi=Bu=Go=_bar_'),
            testcase('berta', 4, None, None),
        )
        for case in tests:
            user, ballot_id, secret, vote = case
            with self.subTest(case=case):
                self.login(user)
                self.assertEqual(
                    vote, self.assembly.get_vote(self.key, ballot_id, secret))

    def test_vote(self) -> None:
        self.login(USER_DICT['anton'])
        self.assertEqual(None, self.assembly.get_vote(self.key, 3, secret=None))
        self.assertLess(
            0, self.assembly.vote(self.key, 3, 'Go>Li=St=Fi=Bu=Lo=_bar_', secret=None))
        self.assertEqual(
            'Go>Li=St=Fi=Bu=Lo=_bar_', self.assembly.get_vote(self.key, 3, secret=None))
        self.login(USER_DICT['berta'])
        self.assertEqual(
            'Lo>Li=St=Fi=Bu=Go=_bar_', self.assembly.get_vote(self.key, 3, secret=None))
        self.assertLess(
            0, self.assembly.vote(self.key, 3, 'St>Li=Go=Fi=Bu=Lo=_bar_', secret=None))
        self.assertEqual(
            'St>Li=Go=Fi=Bu=Lo=_bar_', self.assembly.get_vote(self.key, 3, secret=None))

    @storage
    @as_users("kalif")
    def test_tally(self) -> None:
        self.assertFalse(self.assembly.get_ballot(self.key, 1)['is_tallied'])
        self.assertTrue(self.assembly.tally_ballot(self.key, 1))
        with open(self.testfile_dir / "ballot_result.json", 'rb') as f:
            with open(self.conf['STORAGE_DIR'] / "ballot_result/1", 'rb') as g:
                self.assertEqual(json.load(f), json.load(g))

    @storage
    def test_conclusion(self) -> None:
        base_time = now()
        delta = datetime.timedelta(seconds=42)
        with freezegun.freeze_time(base_time) as frozen_time:
            self.login("viktor")
            data = {
                'description': 'Beschluss über die Anzahl anzuschaffender Schachsets',
                'notes': None,
                'signup_end': base_time + 10*delta,
                'title': 'Außerordentliche Mitgliederversammlung',
                'shortname': 'amgv',
            }
            new_id = self.assembly.create_assembly(self.key, data)
            non_member_id = USER_DICT["werner"]["id"]
            assert isinstance(non_member_id, int)
            self.assertTrue(self.assembly.add_assembly_presiders(
                self.key, new_id, {non_member_id}))
            self.login(non_member_id)
            # werner is no member, so he must use the external signup function
            self.assembly.external_signup(self.key, new_id, non_member_id)
            data = {
                'assembly_id': new_id,
                'use_bar': False,
                'candidates': {
                    -1: {'title': 'Ja', 'shortname': 'j'},
                    -2: {'title': 'Nein', 'shortname': 'n'},
                },
                'description': 'Sind sie sich sicher?',
                'notes': None,
                'abs_quorum': 0,
                'title': 'Verstehen wir Spaß',
                'vote_begin': base_time + delta,
                'vote_end': base_time + 3*delta,
                'vote_extension_end': None,
                'votes': None,
            }
            ballot_id = self.assembly.create_ballot(self.key, data)

            frozen_time.tick(delta=4*delta)
            self.assembly.check_voting_period_extension(self.key, ballot_id)
            self.assertTrue(self.assembly.tally_ballot(self.key, ballot_id))
            self.assembly.external_signup(self.key, new_id,
                                          persona_id=USER_DICT['kalif']['id'])
            update = {
                'id': new_id,
                'signup_end': now(),
            }
            self.assembly.set_assembly(self.key, update)
            self.assertEqual({23, 11}, self.assembly.list_attendees(self.key, new_id))
            self.login("anton")
            self.assertLess(0, self.assembly.conclude_assembly(self.key, new_id))

    @as_users("werner")
    def test_comment(self) -> None:
        comment = "Ein Kommentar."

        # Comment not possible for future and running ballots
        for ballot_id in {2, 14, 15}:
            with self.assertRaises(ValueError) as cm:
                self.assembly.comment_concluded_ballot(self.key, ballot_id, comment)
            self.assertIn("Comments are only allowed for concluded ballots.",
                          cm.exception.args[0])

        # Comment is possible for tallied ballots
        self.assembly.comment_concluded_ballot(self.key, 1, comment)
        self.assertEqual(self.assembly.get_ballot(self.key, 1)['comment'], comment)
        self.assembly.comment_concluded_ballot(self.key, 1, "")
        self.assertEqual(self.assembly.get_ballot(self.key, 1)['comment'], None)

        # Test log
        entry = {'change_note': 'Antwort auf die letzte aller Fragen',
                 'code': const.AssemblyLogCodes.ballot_changed}
        expectation = (entry, entry.copy())
        self.assertLogEqual(expectation, realm="assembly", assembly_id=1)

    @storage
    @as_users("werner")
    def test_entity_attachments(self) -> None:
        # Set some default ids.
        assembly_id = 1
        ballot_id = 2
        attachment_id = 1
        log_offset, _ = self.assembly.retrieve_log(
            self.key, AssemblyLogFilter(assembly_id=assembly_id))
        log = []

        # Check the default entities.
        with open("/cdedb2/tests/ancillary_files/rechen.pdf", "rb") as f:
            self.assertEqual(
                f.read(),
                self.assembly.get_attachment_content(
                    self.key, attachment_id=attachment_id))
        self.assertEqual(
            set(), self.assembly.list_attachments(self.key, assembly_id=assembly_id))
        self.assertEqual(
            set(), self.assembly.list_attachments(self.key, ballot_id=ballot_id))

        # Create a new attachment.
        data = {
            "assembly_id": assembly_id,
            "title": "Rechenschaftsbericht",
            "authors": "Farin",
            "filename": "rechen.pdf",
        }
        new_id = self.assembly.add_attachment(self.key, data, b'123')
        attachment_ids = [new_id]
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": data['title'],
        })

        # Check that everything can be retrieved correctly.
        self.assertEqual(
            b'123', self.assembly.get_attachment_content(self.key, new_id, 1))
        expectation: CdEDBObject = {
            "id": new_id,
            "assembly_id": assembly_id,
            "ballot_ids": [],
            "num_versions": 1,
            "latest_version_nr": 1,
        }
        ballot_data = self.get_sample_datum("assembly.ballots", ballot_id)
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))
        self.assertTrue(
            self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id))
        expectation["ballot_ids"] = [ballot_id]
        log.append({
            "code": const.AssemblyLogCodes.attachment_ballot_link_created,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']} ({ballot_data['title']})",
        })
        self.assertEqual(expectation, self.assembly.get_attachment(self.key, new_id))

        # Check success of adding and removing ballot links.
        with self.assertRaises(ValueError) as e:
            self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id=6)
        self.assertIn(
            "Can only retrieve id for exactly one assembly.", e.exception.args)
        with self.assertRaises(ValueError) as e:
            self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id=1)
        self.assertIn("Cannot link attachment to ballot that has been locked.",
                      e.exception.args)
        self.assertTrue(
            self.assembly.remove_attachment_ballot_link(self.key, new_id, ballot_id))
        log.append({
            "code": const.AssemblyLogCodes.attachment_ballot_link_deleted,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']} ({ballot_data['title']})",
        })
        # Removing a nonexistant link should not raise an error, but return 0.
        self.assertEqual(
            0, self.assembly.remove_attachment_ballot_link(self.key, new_id, ballot_id))

        # Check version data.
        expectation = {
            1: {
                "attachment_id": new_id,
                "version_nr": 1,
                "title": "Rechenschaftsbericht",
                "authors": "Farin",
                "filename": "rechen.pdf",
                "ctime": nearly_now(),
                "dtime": None,
                "file_hash": get_hash(b'123'),
            },
        }
        self.assertEqual(
            expectation, self.assembly.get_attachment_versions(self.key, new_id))
        with self.assertRaises(ValueError) as e:
            self.assembly.remove_attachment_version(self.key, new_id, version_nr=1)
        self.assertIn("Cannot remove the last remaining version of an attachment.",
                      e.exception.args)

        # Add and Change more versions and check that the correct content is returned.
        data = {
            "attachment_id": new_id,
            "title": "Rechenschaftsbericht",
            "authors": "Farin",
            "filename": "rechen_v2.pdf",
        }
        self.assertTrue(self.assembly.add_attachment_version(self.key, data, b'1234'))
        update = {
            "attachment_id": new_id,
            "version_nr": 2,
            "title": "Verrechnungsbericht",
            "authors": "Farina",
            "filename": "alles_falsch.pdf",
        }
        self.assertTrue(self.assembly.change_attachment_version(self.key, update))
        self.assertTrue(self.assembly.add_attachment_version(self.key, data, b'12345'))
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_added,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']}: Version 2",
        })
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_changed,
            "assembly_id": assembly_id,
            "change_note": f"{update['title']}: Version 2",
        })
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_added,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']}: Version 3",
        })
        self.assertEqual(
            b'123', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=1))
        self.assertEqual(
            b'1234', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=2))
        self.assertEqual(
            b'12345', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=3))
        self.assertEqual(
            b'12345', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id))

        # Remove the some versions and check the resulting returns.
        self.assertTrue(
            self.assembly.remove_attachment_version(
                self.key, attachment_id=new_id, version_nr=3))
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_removed,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']}: Version 3",
        })
        expectation = {
            "id": new_id,
            "assembly_id": assembly_id,
            "ballot_ids": [],
            "num_versions": 2,
            "latest_version_nr": 2,
        }
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))

        self.assertTrue(
            self.assembly.remove_attachment_version(
                self.key, attachment_id=new_id, version_nr=1))
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_removed,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']}: Version 1",
        })
        expectation["num_versions"] = 1
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))

        self.assertIsNone(
            self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=1))
        self.assertIsNone(
            self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=3))
        self.assertEqual(
            b'1234', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=2))
        self.assertEqual(
            b'1234', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id))

        # Check that adding a new version is still possible
        self.assertTrue(self.assembly.add_attachment_version(self.key, data, b'123456'))
        log.append({
            "code": const.AssemblyLogCodes.attachment_version_added,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']}: Version 4",
        })
        self.assertEqual(
            b'123456', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id, version_nr=4))
        self.assertEqual(
            b'123456', self.assembly.get_attachment_content(
                self.key, attachment_id=new_id))

        # Check the attachments history.
        data.update({
            "version_nr": 2,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'1234'),
        })
        updated_data = data.copy()
        updated_data.update(update)
        deleted_version = {
            "attachment_id": new_id,
            "version_nr": 1,
            "title": None,
            "authors": None,
            "filename": None,
            "ctime": nearly_now(),
            "dtime": nearly_now(),
            "file_hash": get_hash(b'123'),
        }
        history_expectation: CdEDBObjectMap = {
            1: deleted_version,
            2: updated_data,
            3: deleted_version.copy(),
            4: data,
        }
        history_expectation[3]['version_nr'] = 3
        history_expectation[3]['file_hash'] = get_hash(b'12345')
        history_expectation[4]['version_nr'] = 4
        history_expectation[4]['file_hash'] = get_hash(b'123456')
        self.assertEqual(
            history_expectation,
            self.assembly.get_attachment_versions(self.key, new_id))

        # Create more attachments and check the histories of all attachments.
        history_expectation = {
            new_id: history_expectation,
        }
        data = {
            "assembly_id": assembly_id,
            "title": "Verfassung des Staates der CdEler",
            "authors": "Anton",
            "filename": "verf.pdf",
        }
        new_id = self.assembly.add_attachment(self.key, data, b'abc')
        attachment_ids.append(new_id)
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": data['title'],
        })
        del data["assembly_id"]
        data.update({
            "attachment_id": 1002,
            "version_nr": 1,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'abc'),
        })
        history_expectation[new_id] = {1: data}

        data = {
            "assembly_id": assembly_id,
            "title": "Beschlussvorlage",
            "authors": "Berta",
            "filename": "beschluss.pdf",
        }
        new_id = self.assembly.add_attachment(self.key, data, b'super secret')
        attachment_ids.append(new_id)
        log.append({
            "code": const.AssemblyLogCodes.attachment_added,
            "assembly_id": assembly_id,
            "change_note": data['title'],
        })
        self.assertTrue(
            self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id))
        log.append({
            "code": const.AssemblyLogCodes.attachment_ballot_link_created,
            "assembly_id": assembly_id,
            "change_note": f"{data['title']} ({ballot_data['title']})",
        })
        del data['assembly_id']
        data.update({
            "attachment_id": new_id,
            "version_nr": 1,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'super secret'),
        })
        history_expectation[new_id] = {1: data}

        self.assertEqual(
            set(attachment_ids),
            self.assembly.list_attachments(self.key, assembly_id=assembly_id))
        self.assertEqual(
            {new_id},
            self.assembly.list_attachments(self.key, ballot_id=ballot_id))

        expectation = {
            attachment_ids[0]: {
                'assembly_id': assembly_id,
                'ballot_ids': [],
                'id': attachment_ids[0],
                'num_versions': 2,
                'latest_version_nr': 4,
            },
            attachment_ids[1]: {
                'assembly_id': assembly_id,
                'ballot_ids': [],
                'id': attachment_ids[1],
                'num_versions': 1,
                'latest_version_nr': 1,
           },
            attachment_ids[2]: {
                'assembly_id': assembly_id,
                'ballot_ids': [ballot_id],
                'id': attachment_ids[2],
                'num_versions': 1,
                'latest_version_nr': 1,
            },
        }
        self.assertEqual(
            expectation, self.assembly.get_attachments(self.key, attachment_ids))
        self.assertEqual(
            history_expectation,
            self.assembly.get_attachments_versions(self.key, attachment_ids))
        history_expectation = {
            attachment_ids[0]: {
                1: {
                    'attachment_id': attachment_ids[0],
                    'authors': None,
                    'ctime': nearly_now(),
                    'dtime': nearly_now(),
                    'file_hash': get_hash(b'123'),
                    'filename': None,
                    'title': None,
                    'version_nr': 1,
                },
                2: {
                    'attachment_id': attachment_ids[0],
                    'authors': 'Farina',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'1234'),
                    'filename': 'alles_falsch.pdf',
                    'title': 'Verrechnungsbericht',
                    'version_nr': 2,
                },
                3: {
                    'attachment_id': attachment_ids[0],
                    'authors': None,
                    'ctime': nearly_now(),
                    'dtime': nearly_now(),
                    'file_hash': get_hash(b'12345'),
                    'filename': None,
                    'title': None,
                    'version_nr': 3,
                },
                4: {
                    'attachment_id': attachment_ids[0],
                    'authors': 'Farin',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'123456'),
                    'filename': 'rechen_v2.pdf',
                    'title': 'Rechenschaftsbericht',
                    'version_nr': 4,
                },
            },
            attachment_ids[1]: {
                1: {
                    'attachment_id': attachment_ids[1],
                    'authors': 'Anton',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'abc'),
                    'filename': 'verf.pdf',
                    'title': 'Verfassung des Staates der CdEler',
                    'version_nr': 1,
                },
            },
            attachment_ids[2]: {
                1: {
                    'attachment_id': attachment_ids[2],
                    'authors': 'Berta',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'super secret'),
                    'filename': 'beschluss.pdf',
                    'title': 'Beschlussvorlage',
                    'version_nr': 1,
                },
            },
        }
        self.assertEqual(
            history_expectation, self.assembly.get_attachments_versions(
                self.key, attachment_ids))
        cascade = {"versions", "ballots"}
        self.assertEqual(
            cascade, self.assembly.delete_attachment_blockers(self.key, new_id).keys())
        self.assertTrue(self.assembly.delete_attachment(self.key, new_id, cascade))
        log.append({
            "code": const.AssemblyLogCodes.attachment_removed,
            "assembly_id": assembly_id,
            "change_note": data['title'],
        })
        del expectation[new_id]
        self.assertEqual(
            expectation, self.assembly.get_attachments(self.key, attachment_ids))
        self.assertLogEqual(
            log, realm="assembly", offset=log_offset, assembly_id=assembly_id)

    @storage
    @as_users("werner")
    def test_ballot_attachment_links(self) -> None:
        assembly_id = 3
        n = 3
        log_offset, _ = self.assembly.retrieve_log(
            self.key, AssemblyLogFilter(assembly_id=assembly_id))
        log = []
        base_time = now()
        delta = datetime.timedelta(seconds=10)
        with freezegun.freeze_time(base_time) as frozen_time:
            # Create new attachment.
            attachment_data = {
                "assembly_id": assembly_id,
                "title": "Unabhängigkeitserklärung des Freistaates CdE",
                "authors": "AbCdE",
                "filename": "Freiheit.pdf",
            }
            attachment_id = self.assembly.add_attachment(self.key, attachment_data, b'')
            log.append({
                "code": const.AssemblyLogCodes.attachment_added,
                "assembly_id": assembly_id,
                "change_note": attachment_data['title'],
            })
            attachment_expectation: CdEDBObject = {
                "assembly_id": assembly_id,
                "ballot_ids": [],
                "id": attachment_id,
                "num_versions": 1,
                "latest_version_nr": 1,
            }
            self.assertEqual(
                attachment_expectation,
                self.assembly.get_attachment(self.key, attachment_id))
            version_expectation = {
                "attachment_id": attachment_id,
                "authors": attachment_data["authors"],
                "title": attachment_data["title"],
                "filename": attachment_data["filename"],
                "ctime": base_time,
                "dtime": None,
                "file_hash": get_hash(b''),
                "version_nr": 1,
            }
            self.assertEqual(
                {version_expectation["version_nr"]: version_expectation},
                self.assembly.get_attachment_versions(self.key, attachment_id))

            # Create some new ballots and link the attachment to them.
            ballot_ids = []
            for i in range(n):
                ballot_data = {
                    "assembly_id": assembly_id,
                    "description": None,
                    "notes": None,
                    "title": "TestAbstimmung" + str(i),
                    "use_bar": True,
                    "abs_quorum": 0,
                    "rel_quorum": 0,
                    "vote_begin": base_time + (2 * i + 1) * delta,
                    "vote_end": base_time + (2 * (i + n) + 1) * delta,
                    "vote_extension_end": None,
                }
                ballot_ids.append(
                    ballot_id := self.assembly.create_ballot(self.key, ballot_data))
                log.append({
                    "code": const.AssemblyLogCodes.ballot_created,
                    "assembly_id": assembly_id,
                    "change_note": ballot_data['title'],
                })
                self.assertTrue(
                    self.assembly.add_attachment_ballot_link(
                        self.key, attachment_id, ballot_id))
                log.append({
                    "code": const.AssemblyLogCodes.attachment_ballot_link_created,
                    "assembly_id": assembly_id,
                    "change_note":
                        f"{attachment_data['title']} ({ballot_data['title']})",
                })
                self.assertEqual(
                    {attachment_id: version_expectation},
                    self.assembly.get_definitive_attachments_version(
                        self.key, ballot_id),
                )
            attachment_expectation["ballot_ids"] = ballot_ids
            self.assertEqual(
                attachment_expectation,
                self.assembly.get_attachment(self.key, attachment_id))

            # Advanve time and add new versions.
            for i in range(n):
                frozen_time.tick(delta=2*delta)
                version_data = {
                    "attachment_id": attachment_id,
                    "title": attachment_data["title"],
                    "authors": attachment_data["authors"],
                    "filename": attachment_data["filename"],
                }
                self.assertTrue(
                    self.assembly.add_attachment_version(
                        self.key, version_data, bytes(i+1)))
                log.append({
                    "code": const.AssemblyLogCodes.attachment_version_added,
                    "assembly_id": assembly_id,
                    "change_note": f"{attachment_data['title']}: Version {i+2}",
                })

            attachment_expectation["num_versions"] = \
                attachment_expectation["latest_version_nr"] = n + 1
            attachment_expectation["ballot_ids"] = ballot_ids
            self.assertEqual(
                attachment_expectation,
                self.assembly.get_attachment(self.key, attachment_id))

            for i, ballot_id in enumerate(ballot_ids):
                version_expectation.update({
                    "version_nr": i + 1,
                    "file_hash": get_hash(bytes(i)),
                    "ctime": base_time + (2 * i) * delta,
                })
                self.assertEqual(
                    {attachment_id: version_expectation},
                    self.assembly.get_definitive_attachments_version(
                        self.key, ballot_id),
                )
        self.assertLogEqual(
            log, realm="assembly", offset=log_offset, assembly_id=assembly_id)

    @as_users("werner")
    def test_2289(self) -> None:
        ballot_id = 2
        old_candidates = self.assembly.get_ballot(self.key, ballot_id)['candidates']
        for candidate in old_candidates.values():
            del candidate['ballot_id']
            del candidate['id']
        bdata = {
            'id': ballot_id,
            'candidates': {
                6: None,
                -1: old_candidates[6],
            },
        }
        self.assertTrue(self.assembly.set_ballot(self.key, bdata))
        candidates = self.assembly.get_ballot(self.key, ballot_id)['candidates']
        self.assertNotIn(6, candidates)
        self.assertEqual(candidates[1001]['shortname'], old_candidates[6]['shortname'])

        bdata['candidates'] = {
            7: old_candidates[8],
            8: old_candidates[7],
        }
        self.assertTrue(self.assembly.set_ballot(self.key, bdata))
        candidates = self.assembly.get_ballot(self.key, ballot_id)['candidates']
        self.assertEqual(candidates[7]['shortname'], old_candidates[8]['shortname'])
        self.assertEqual(candidates[8]['shortname'], old_candidates[7]['shortname'])

    @as_users("werner", "berta")
    def test_group_ballots_by_config(self) -> None:
        assembly_id = 1
        grouped = self.assembly.group_ballots_by_config(self.key, assembly_id)
        ballots = self.assembly.get_ballots(
            self.key, self.assembly.list_ballots(self.key, assembly_id))

        for ballot_id, ballot in ballots.items():
            key = BallotConfiguration(
                ballot['vote_begin'], ballot['vote_end'], ballot['vote_extension_end'],
                ballot['abs_quorum'], ballot['rel_quorum'])
            self.assertIn(ballot_id, grouped[key])

    @as_users("werner", "berta")
    @storage
    def test_group_ballots(self) -> None:
        assembly_id = 1
        grouped = self.assembly.group_ballots(self.key, assembly_id)
        ballots = self.assembly.get_ballots(
            self.key, self.assembly.list_ballots(self.key, assembly_id))

        for ballot_id, ballot in ballots.items():
            try:
                self.assembly.tally_ballot(self.key, ballot_id)
            except ValueError:
                pass
            if self.assembly.is_ballot_voting(self.key, ballot_id):
                if ballot['extended']:
                    self.assertIn(ballot_id, grouped.extended)
                else:
                    self.assertIn(ballot_id, grouped.current)
                self.assertIn(ballot_id, grouped.running)
            elif self.assembly.is_ballot_concluded(self.key, ballot_id):
                self.assertIn(ballot_id, grouped.concluded)
            else:
                self.assertIn(ballot_id, grouped.upcoming)

    @as_users("werner")
    @prepsql("""INSERT INTO assembly.assemblies
        (title, shortname, description, presider_address, signup_end) VALUES
        ('Umfrage', 'umfrage', 'sagt eure Meinung!', 'umfrage@example.cde',
         date '2111-11-11');""")
    def test_prepsql(self) -> None:
        expectation = {
            1: {'id': 1, 'is_active': True,
                'signup_end': datetime.datetime(
                    2111, 11, 11, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Internationaler Kongress'},
            2: {'id': 2, 'is_active': False,
                'signup_end': datetime.datetime(
                    2020, 2, 22, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Kanonische Beispielversammlung'},
            3: {'id': 3, 'is_active': True,
                'signup_end': datetime.datetime(
                    2222, 2, 22, 0, 0, tzinfo=datetime.timezone.utc),
                'title': 'Archiv-Sammlung'},
            1001: {'id': 1001, 'is_active': True,
                   'signup_end': datetime.datetime(
                    2111, 11, 11, 0, 0, tzinfo=datetime.timezone.utc),
                   'title': 'Umfrage'},
        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))

    @storage
    @as_users("viktor")
    def test_privilege_checks(self) -> None:
        assembly_ids = self.assembly.list_assemblies(self.key)

        presider = get_user("berta")

        for assembly_id in assembly_ids:
            execsql(f"""
                INSERT into assembly.presiders (persona_id, assembly_id)
                VALUES ({presider['id']}, {assembly_id}) ON CONFLICT DO NOTHING
            """)
        self.assertEqual(
            set(assembly_ids), self.assembly.presider_info(self.key, presider['id']))

        other_presider = get_user("werner")
        presided_assembly_id = 3
        non_presided_assembly_id = 2
        presided_assembly_ids = self.assembly.presider_info(
            self.key, other_presider['id'])
        non_presided_assemblies = assembly_ids.keys() - presided_assembly_ids
        self.assertTrue(presided_assembly_ids)
        self.assertIn(presided_assembly_id, presided_assembly_ids)
        self.assertNotIn(non_presided_assembly_id, presided_assembly_ids)
        self.assertNotIn(
            "member", self.core.get_roles_single(self.key, other_presider['id']))

        attendee = get_user("rowena")
        attended_assembly_id = non_presided_assembly_id
        non_attended_assembly_id = presided_assembly_id
        self.assertTrue(self.assembly.check_attendance(
            self.key, assembly_id=attended_assembly_id, persona_id=attendee['id']))
        self.assertFalse(self.assembly.check_attendance(
            self.key, assembly_id=non_attended_assembly_id, persona_id=attendee['id']))
        self.assertFalse(self.assembly.presider_info(self.key, attendee['id']))
        self.assertNotIn(
            "member", self.core.get_roles_single(self.key, attendee['id']))

        member = get_user("ferdinand")
        for assembly_id in assembly_ids:
            self.assertFalse(self.assembly.check_attendance(
                self.key, assembly_id=assembly_id, persona_id=member['id']))
        self.assertFalse(self.assembly.presider_info(self.key, member['id']))
        self.assertIn(
            "member", self.core.get_roles_single(self.key, member['id']))
        execsql(f"""
            UPDATE core.personas SET is_assembly_admin = False
            WHERE id = {member['id']}
        """)
        self.assertNotIn(
            "assembly_admin", self.core.get_roles_single(self.key, member['id']))

        unprivileged = get_user("daniel")
        self.assertFalse(self.assembly.presider_info(self.key, unprivileged['id']))
        for assembly_id in assembly_ids:
            self.assertFalse(self.assembly.check_attendance(
                self.key, assembly_id=assembly_id, persona_id=unprivileged['id']))
        self.assertNotIn(
            "member", self.core.get_roles_single(self.key, unprivileged['id']))

        some_assemblies_filter = AssemblyLogFilter(
            _assembly_ids=list(presided_assembly_ids))
        other_assemblies_filter = AssemblyLogFilter(
            _assembly_ids=list(assembly_ids.keys() - presided_assembly_ids))
        all_assemblies_filter = AssemblyLogFilter(_assembly_ids=list(assembly_ids))
        global_filter = AssemblyLogFilter()

        all_ballot_ids = {
            assembly_id: self.assembly.list_ballots(self.key, assembly_id)
            for assembly_id in assembly_ids
        }
        all_attachment_ids = {
            assembly_id: self.assembly.list_attachments(
                self.key, assembly_id=assembly_id, ballot_id=None)
            for assembly_id in assembly_ids
        }

        new_ballot_data = {
            'title': "New Ballot",
            'description': None,
            'notes': None,
            'vote_begin': now() + datetime.timedelta(days=1),
            'vote_end': now() + datetime.timedelta(days=2),
            'use_bar': False,
        }
        new_attachment_data = {
            'title': "New Attachment",
            'filename': "attachment.pdf",
            'authors': None,
        }

        with self.switch_user(presider):
            assemblies = self.assembly.get_assemblies(self.key, assembly_ids)

            for assembly_id, assembly in assemblies.items():
                ballot_ids = self.assembly.list_ballots(self.key, assembly_id)
                ballots = self.assembly.get_ballots(self.key, ballot_ids)
                for ballot_id, ballot in ballots.items():
                    if not ballot['is_locked']:
                        self.assembly.set_ballot(self.key, {'id': ballot_id})
                    else:
                        with self.assertRaises(ValueError):
                            self.assembly.set_ballot(
                                self.key, {'id': ballot_id})

                    if ballot['is_locked'] and not ballot['is_voting']:
                        self.assembly.comment_concluded_ballot(self.key, ballot_id, "!")

                    self.assembly.get_ballot_result(self.key, ballot_id)

                if assemblies[assembly_id]['is_active']:
                    self.assembly.set_assembly(self.key, {'id': assembly_id})
                else:
                    with self.assertRaises(ValueError):
                        self.assembly.set_assembly(self.key, {'id': assembly_id})

                if assembly['is_active']:
                    new_ballot_id = self.assembly.create_ballot(
                        self.key, {'assembly_id': assembly_id, **new_ballot_data})
                    self.assertTrue(
                        self.assembly.delete_ballot(
                            self.key, new_ballot_id,
                            self.assembly.delete_ballot_blockers(
                                self.key, new_ballot_id,
                            ),
                        ),
                    )

                    new_attachment_id = self.assembly.add_attachment(
                        self.key, {'assembly_id': assembly_id, **new_attachment_data},
                        b"123",
                    )
                    self.assertTrue(
                        self.assembly.delete_attachment(
                            self.key, new_attachment_id,
                            self.assembly.delete_attachment_blockers(
                                self.key, new_attachment_id,
                            ),
                        ),
                    )

            self.assembly.retrieve_log(self.key, some_assemblies_filter)
            self.assembly.retrieve_log(self.key, other_assemblies_filter)
            self.assembly.retrieve_log(self.key, all_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, global_filter)

            self.assembly.get_attendees(self.key, presided_assembly_id, now())
            self.assembly.get_attendees(self.key, non_presided_assembly_id, now())

        with self.switch_user(other_presider):
            with self.assertRaises(PrivilegeError):
                self.assembly.get_assemblies(self.key, assembly_ids)
            self.assembly.get_assemblies(self.key, presided_assembly_ids)
            with self.assertRaises(PrivilegeError):
                self.assembly.get_assemblies(self.key, (non_presided_assembly_id,))

            for assembly_id in presided_assembly_ids:
                ballot_ids = self.assembly.list_ballots(self.key, assembly_id)
                ballots = self.assembly.get_ballots(self.key, ballot_ids)
                for ballot_id, ballot in ballots.items():
                    if not ballot['is_locked']:
                        self.assembly.set_ballot(self.key, {'id': ballot_id})
                    else:
                        with self.assertRaises(ValueError):
                            self.assembly.set_ballot(
                                self.key, {'id': ballot_id})

                    if ballot['is_locked'] and not ballot['is_voting']:
                        self.assembly.comment_concluded_ballot(self.key, ballot_id, "!")

                    self.assembly.get_ballot_result(self.key, ballot_id)

                if assemblies[assembly_id]['is_active']:
                    self.assembly.set_assembly(self.key, {'id': assembly_id})
                else:
                    # No inactive assembly exists in sample data.
                    # with self.assertRaises(ValueError):
                    #     self.assembly.set_assembly(self.key, {'id': assembly_id})
                    self.fail(
                        f"Sample data changed to include inactive assembly for"
                        f" presider '{self.user['display_name']}'.")

            for assembly_id in non_presided_assemblies:
                with self.assertRaises(PrivilegeError):
                    self.assembly.list_ballots(self.key, assembly_id)

                with self.assertRaises(PrivilegeError):
                    self.assembly.set_assembly(self.key, {'id': assembly_id})

                with self.assertRaises(PrivilegeError):
                    self.assembly.create_ballot(
                        self.key, {'assembly_id': assembly_id, **new_ballot_data})

                for ballot_id in all_ballot_ids[assembly_id]:
                    with self.assertRaises(PrivilegeError):
                        self.assembly.delete_ballot_blockers(self.key, ballot_id)
                    with self.assertRaises(PrivilegeError):
                        self.assembly.delete_ballot(self.key, ballot_id)

                with self.assertRaises(PrivilegeError):
                    self.assembly.external_signup(
                        self.key, assembly_id, self.user['id'])

                with self.assertRaises(PrivilegeError):
                    self.assembly.add_attachment(
                        self.key, {'assembly_id': assembly_id, **new_attachment_data},
                        b"123",
                    )

            self.assembly.retrieve_log(self.key, some_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, other_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, all_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, global_filter)

            self.assembly.get_attendees(self.key, presided_assembly_id, now())
            with self.assertRaises(PrivilegeError):
                self.assembly.get_attendees(self.key, non_presided_assembly_id, now())

        with self.switch_user(attendee):
            with self.assertRaises(PrivilegeError):
                self.assembly.get_assemblies(self.key, assembly_ids)
            self.assembly.get_assemblies(self.key, (attended_assembly_id,))
            with self.assertRaises(PrivilegeError):
                self.assembly.get_assemblies(self.key, (non_attended_assembly_id,))

            for assembly_id in assembly_ids:
                if self.assembly.check_attendance(self.key, assembly_id=assembly_id):
                    ballot_ids = self.assembly.list_ballots(self.key, assembly_id)
                    for ballot_id in ballot_ids:
                        with self.assertRaises(PrivilegeError):
                            self.assembly.set_ballot(self.key, {'id': ballot_id})

                        with self.assertRaises(PrivilegeError):
                            self.assembly.comment_concluded_ballot(
                                self.key, ballot_id, "Test!")

                        self.assembly.has_voted(self.key, ballot_id)
                        self.assembly.get_vote(self.key, ballot_id, None)

                        self.assembly.get_ballot_result(self.key, ballot_id)
                else:
                    with self.assertRaises(PrivilegeError):
                        self.assembly.list_ballots(self.key, assembly_id)

                    # A bit hacky, since we can't actually get these ids.
                    for ballot_id in all_ballot_ids[assembly_id]:
                        with self.assertRaises(PrivilegeError):
                            self.assembly.get_ballot_result(self.key, ballot_id)

                        with self.assertRaises(PrivilegeError):
                            self.assembly.tally_ballot(self.key, ballot_id)

                    with self.assertRaises(PrivilegeError):
                        self.assembly.list_attachments(
                            self.key, assembly_id=assembly_id, ballot_id=None)

                    attachment_ids = all_attachment_ids[assembly_id]
                    if not attachment_ids:
                        continue

                    with self.assertRaises(PrivilegeError):
                        self.assembly.get_attachments_versions(self.key, attachment_ids)

                    for attachment_id in attachment_ids:
                        with self.assertRaises(PrivilegeError):
                            self.assembly.get_attachment_version(
                                self.key, attachment_id, 1)

                        with self.assertRaises(PrivilegeError):
                            self.assembly.get_attachment_content(
                                self.key, attachment_id)

                    with self.assertRaises(PrivilegeError):
                        self.assembly.get_latest_attachments_version(
                            self.key, attachment_ids)

                with self.assertRaises(PrivilegeError):
                    self.assembly.set_assembly(self.key, {'id': assembly_id})

                for attachment_id in all_attachment_ids[assembly_id]:
                    with self.assertRaises(PrivilegeError):
                        self.assembly.delete_attachment(
                            self.key, attachment_id,
                            self.assembly.delete_attachment_blockers(
                                self.key, attachment_id,
                            ),
                        )

            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(
                    self.key, AssemblyLogFilter(assembly_id=attended_assembly_id))
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(
                    self.key, AssemblyLogFilter(assembly_id=non_attended_assembly_id))
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, all_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, global_filter)

            self.assembly.get_attendees(self.key, attended_assembly_id, now())
            with self.assertRaises(PrivilegeError):
                self.assembly.get_attendees(self.key, non_attended_assembly_id, now())

        with self.switch_user(member):
            self.assembly.get_assemblies(self.key, assembly_ids)

            for assembly_id in assembly_ids:
                self.assembly.list_ballots(self.key, assembly_id)
                ballot_ids = self.assembly.list_ballots(self.key, assembly_id)
                for ballot_id in ballot_ids:
                    with self.assertRaises(PrivilegeError):
                        self.assembly.set_ballot(self.key, {'id': ballot_id})

                    with self.assertRaises(PrivilegeError):
                        self.assembly.comment_concluded_ballot(self.key, ballot_id, "!")

                    if self.assembly.check_attendance(
                            self.key, assembly_id=assembly_id):
                        # No attended assembly exists.
                        # self.assembly.has_voted(self.key, ballot_id)
                        # self.assembly.get_vote(self.key, ballot_id)
                        self.fail(
                            f"Sample data changed to include attended assembly for"
                            f" member '{self.user['display_name']}'.")
                    else:
                        with self.assertRaises(PrivilegeError):
                            self.assembly.has_voted(self.key, ballot_id)

                        with self.assertRaises(PrivilegeError):
                            self.assembly.get_vote(self.key, ballot_id, None)

                    self.assembly.get_ballot_result(self.key, ballot_id)

                with self.assertRaises(PrivilegeError):
                    self.assembly.set_assembly(self.key, {'id': assembly_id})

                with self. assertRaises(PrivilegeError):
                    self.assembly.retrieve_log(
                        self.key, AssemblyLogFilter(assembly_id=assembly_id))

        with self.switch_user(unprivileged):
            for assembly_id in assembly_ids:
                with self.assertRaises(PrivilegeError):
                    self.assembly.get_assembly(self.key, assembly_id)

            for assembly_id in assembly_ids:
                with self.assertRaises(PrivilegeError):
                    self.assembly.list_ballots(self.key, assembly_id)

                with self.assertRaises(PrivilegeError):
                    self.assembly.set_assembly(self.key, {'id': assembly_id})

            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, some_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, other_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, all_assemblies_filter)
            with self.assertRaises(PrivilegeError):
                self.assembly.retrieve_log(self.key, global_filter)

            with self.assertRaises(PrivilegeError):
                self.assembly.get_attendees(self.key, presided_assembly_id, now())
            with self.assertRaises(PrivilegeError):
                self.assembly.get_attendees(self.key, non_presided_assembly_id, now())
