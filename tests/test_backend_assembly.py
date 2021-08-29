#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import json
from typing import Collection, Optional, NamedTuple

import freezegun
import pytz

import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, get_hash, now, nearly_now,
)
from tests.common import (
    BackendTest, UserIdentifier, USER_DICT, as_users, prepsql, storage,
)


class TestAssemblyBackend(BackendTest):
    used_backends = ("core", "assembly")

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

    @as_users("anton", "berta", "charly", "kalif")
    def test_does_attend(self) -> None:
        self.assertEqual(self.user['id'] != 3, self.assembly.does_attend(
            self.key, assembly_id=1))
        self.assertEqual(self.user['id'] != 3, self.assembly.does_attend(
            self.key, ballot_id=3))

    @as_users("charly")
    def test_list_attendees(self) -> None:
        expectation = {1, 2, 9, 11, 23, 100}
        self.assertEqual(expectation, self.assembly.list_attendees(self.key, 1))

    def test_entity_assembly(self) -> None:
        self.login("werner")
        expectation = {
            1: {
                'id': 1,
                'is_active': True,
                'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                'title': 'Internationaler Kongress'
            },
            2: {
                'id': 2,
                'is_active': False,
                'signup_end': datetime.datetime(2020, 2, 22, 0, 0, tzinfo=pytz.utc),
                'title': 'Kanonische Beispielversammlung'
            },
            3: {
                'id': 3,
                'is_active': True,
                'signup_end': datetime.datetime(2222, 2, 22, 0, 0, tzinfo=pytz.utc),
                'title': 'Archiv-Sammlung'
            },
        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))
        expectation = {
            'description': 'Proletarier aller Länder vereinigt Euch!',
            'id': 1,
            'is_active': True,
            'presider_address': 'kongress@example.cde',
            'notes': None,
            'presiders': {23},
            'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
            'title': 'Internationaler Kongress',
            'shortname': 'kongress',
        }
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, 1))
        data = {
            'id': 1,
            'notes': "More fun for everybody",
            'signup_end': datetime.datetime(2111, 11, 11, 23, 0, tzinfo=pytz.utc),
            'title': "Allumfassendes Konklave",
            'shortname': 'konklave',
        }
        self.assertLess(0, self.assembly.set_assembly(self.key, data))
        expectation.update(data)
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, 1))
        new_assembly = {
            'description': 'Beschluss über die Anzahl anzuschaffender Schachsets',
            'notes': None,
            'signup_end': now(),
            'title': 'Außerordentliche Mitgliederversammlung',
            'shortname': 'amgv',
            'presiders': {1, 23},
        }
        self.login("viktor")
        new_id = self.assembly.create_assembly(self.key, new_assembly)
        expectation: CdEDBObject = new_assembly
        expectation['id'] = new_id
        expectation['presider_address'] = None
        expectation['is_active'] = True
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, new_id))
        self.assertLess(0, self.assembly.remove_assembly_presider(self.key, new_id, 23))
        self.assertTrue(self.assembly.add_assembly_presiders(self.key, new_id, {23}))
        # Check return of setting presiders to the same thing.
        self.assertEqual(0, self.assembly.add_assembly_presiders(self.key,
                                                                 new_id, {23}))
        expectation['presiders'] = {1, 23}
        self.assertEqual(expectation, self.assembly.get_assembly(self.key, new_id))
        self.assertLess(0, self.assembly.delete_assembly(
            self.key, new_id, ("ballots", "attendees", "attachments",
                               "presiders", "log", "mailinglists")))

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

    @as_users("werner")
    def test_entity_ballot(self) -> None:
        assembly_id = 1
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
        self.assertEqual(expectation, self.assembly.list_ballots(self.key,
                                                                 assembly_id))
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
                'description': 'Nach dem Leben, dem Universum und dem ganzen Rest.',
                'extended': True,
                'id': 1,
                'is_tallied': False,
                'notes': None,
                'abs_quorum': 2,
                'rel_quorum': 0,
                'quorum': 2,
                'title': 'Antwort auf die letzte aller Fragen',
                'vote_begin': datetime.datetime(2002, 2, 22, 20, 22, 22, 222222,
                                                tzinfo=pytz.utc),
                'vote_end': datetime.datetime(2002, 2, 23, 20, 22, 22, 222222,
                                              tzinfo=pytz.utc),
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
                'description': 'denkt an die Frutaner',
                'extended': None,
                'id': 4,
                'is_tallied': False,
                'notes': None,
                'abs_quorum': 0,
                'rel_quorum': 0,
                'quorum': 0,
                'title': 'Akademie-Nachtisch',
                'vote_begin': nearly_now(),
                'vote_end': datetime.datetime(2222, 1, 1, 20, 22, 22, 222222,
                                              tzinfo=pytz.utc),
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
        expectation: CdEDBObject = {
            'assembly_id': 1,
            'use_bar': False,
            'candidates': {6: {'ballot_id': 2,
                               'title': 'Rot',
                               'id': 6,
                               'shortname': 'rot'},
                           7: {'ballot_id': 2,
                               'title': 'Gelb',
                               'id': 7,
                               'shortname': 'gelb'},
                           8: {'ballot_id': 2,
                               'title': 'Grün',
                               'id': 8,
                               'shortname': 'gruen'},
                           9: {'ballot_id': 2,
                               'title': 'Blau',
                               'id': 9,
                               'shortname': 'blau'}},
            'description': 'Ulitmativ letzte Entscheidung',
            'extended': None,
            'id': 2,
            'is_tallied': False,
            'notes': 'Nochmal alle auf diese wichtige Entscheidung hinweisen.',
            'abs_quorum': 0,
            'rel_quorum': 0,
            'quorum': 0,
            'title': 'Farbe des Logos',
            'vote_begin': datetime.datetime(2222, 2, 2, 20, 22, 22, 222222,
                                            tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 3, 20, 22, 22, 222222,
                                          tzinfo=pytz.utc),
            'vote_extension_end': None,
            'votes': None}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, 2))
        data: CdEDBObject = {
            'id': 2,
            'use_bar': True,
            'candidates': {
                6: {'title': 'Teracotta', 'shortname': 'terra', 'id': 6},
                7: None,
                -1: {'title': 'Aquamarin', 'shortname': 'aqua'},
            },
            'notes': "foo",
            'vote_extension_end': datetime.datetime(2222, 2, 20, 20, 22, 22, 222222,
                                                    tzinfo=pytz.utc),
            'rel_quorum': 100,
        }
        self.assertLess(0, self.assembly.set_ballot(self.key, data))
        for key in ('use_bar', 'notes', 'vote_extension_end', 'rel_quorum'):
            expectation[key] = data[key]
        expectation['abs_quorum'] = 0
        expectation['quorum'] = 10
        expectation['candidates'][6]['title'] = data['candidates'][6]['title']
        expectation['candidates'][6]['shortname'] = data['candidates'][6]['shortname']
        del expectation['candidates'][7]
        expectation['candidates'][1001] = {
            'id': 1001,
            'ballot_id': 2,
            'title': 'Aquamarin',
            'shortname': 'aqua'}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, 2))

        data = {
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
                                            tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222,
                                          tzinfo=pytz.utc),
            'vote_extension_end': datetime.datetime(2222, 2, 7, 13, 22, 22, 222222,
                                                    tzinfo=pytz.utc),
            'votes': None,
        }
        new_id = self.assembly.create_ballot(self.key, data)
        self.assertLess(0, new_id)
        data.update({
            'extended': None,
            'quorum': 10,
            'id': new_id,
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

        self.assertLess(0, self.assembly.delete_ballot(
            self.key, 2, cascade=("candidates", "attachments", "voters")))
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
                                            tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222,
                                          tzinfo=pytz.utc),
            'vote_extension_end': None,
            'votes': None}
        with self.assertRaises(ValueError):
            self.assembly.create_ballot(self.key, data)

        data['abs_quorum'] = 0
        data['vote_extension_end'] = datetime.datetime(2222, 2, 7, 13, 22, 22, 222222,
                                                       tzinfo=pytz.utc)
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
            self.assertEqual(8, self.assembly.get_ballot(self.key, ballot_id)["quorum"])

            # Adding a non-member attendee increases the quorum.
            self.assembly.external_signup(self.key, assembly_id, 4)
            self.assertEqual(9, self.assembly.get_ballot(self.key, ballot_id)["quorum"])

            frozen_time.tick(delta=4*delta)
            self.assembly.check_voting_period_extension(self.key, ballot_id)
            # Now adding an attendee does not change the quorum.
            self.assembly.external_signup(self.key, assembly_id, 11)
            self.assertEqual(9, self.assembly.get_ballot(self.key, ballot_id)["quorum"])

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
        self.assertEqual(False, self.assembly.does_attend(
            self.key, assembly_id=1))
        secret = self.assembly.signup(self.key, 1)
        assert secret is not None
        self.assertLess(0, len(secret))
        self.assertEqual(True, self.assembly.does_attend(
            self.key, assembly_id=1))

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
        self.assertEqual(False, self.assembly.get_ballot(self.key, 1)['is_tallied'])
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

    @storage
    @as_users("werner")
    def test_entity_attachments(self) -> None:
        assembly_id = 1
        ballot_id = 2
        attachment_id = 1
        with open("/cdedb2/tests/ancillary_files/rechen.pdf", "rb") as f:
            self.assertEqual(
                f.read(),
                self.assembly.get_attachment_content(
                    self.key, attachment_id=attachment_id))
        self.assertEqual(
            set(), self.assembly.list_attachments(self.key, assembly_id=assembly_id))
        self.assertEqual(
            set(), self.assembly.list_attachments(self.key, ballot_id=ballot_id))
        data = {
            "assembly_id": assembly_id,
            "title": "Rechenschaftsbericht",
            "authors": "Farin",
            "filename": "rechen.pdf",
        }
        new_id = self.assembly.add_attachment(self.key, data, b'123')
        self.assertGreater(new_id, 0)
        self.assertEqual(
            b'123', self.assembly.get_attachment_content(self.key, new_id, 1))
        expectation = {
            "id": new_id,
            "assembly_id": assembly_id,
            "ballot_ids": None,
            "num_versions": 1,
            "current_version_nr": 1,
        }
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))
        self.assertTrue(self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id))
        expectation = {
            "id": new_id,
            "assembly_id": assembly_id,
            "ballot_ids": [ballot_id],
            'num_versions': 1,
            'current_version_nr': 1,
        }
        self.assertEqual(expectation, self.assembly.get_attachment(self.key, new_id))
        with self.assertRaises(ValueError):
            self.assembly.add_attachment_ballot_link(self.key, new_id, ballot_id=6)
        expectation = {
            1: {
                "attachment_id": new_id,
                "id": 1001,
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
        with self.assertRaises(ValueError):
            self.assembly.remove_attachment_version(self.key, new_id, 1)
        data = {
            "attachment_id": new_id,
            "title": "Rechensaftsbericht",
            "authors": "Farin",
            "filename": "rechen_v2.pdf",
        }
        self.assertEqual(
            b'123', self.assembly.get_attachment_content(self.key, new_id))
        self.assertLess(
            0, self.assembly.add_attachment_version(self.key, data, b'1234'))
        self.assertLess(
            0, self.assembly.add_attachment_version(self.key, data, b'12345'))
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
        self.assertLess(
            0, self.assembly.remove_attachment_version(
                self.key, attachment_id=new_id, version_nr=3))
        expectation = {
            "id": new_id,
            "assembly_id": assembly_id,
            "ballot_ids": [ballot_id],
            "num_versions": 2,
            "current_version_nr": 2,
        }
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))
        self.assertLess(
            0, self.assembly.remove_attachment_version(
                self.key, attachment_id=new_id, version_nr=1))
        expectation.update({"num_versions": 1})
        self.assertEqual(
            expectation, self.assembly.get_attachment(self.key, attachment_id=new_id))
        self.assertIsNone(self.assembly.get_attachment_content(
            self.key, attachment_id=new_id, version_nr=1))
        data.update({
            "version_nr": 2,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'1234'),
        })
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
            2: data,
            3: deleted_version.copy(),
        }
        history_expectation[3]['version_nr'] = 3
        history_expectation[3]['file_hash'] = get_hash(b'12345')
        self.assertEqual(
            history_expectation, self.assembly.get_attachment_versions(
                self.key, new_id, current_version_only=False))
        with self.assertRaises(ValueError):
            self.assembly.delete_attachment(self.key, new_id)

        data = {
            "attachment_id": new_id,
            "version_nr": 2,
            "title": "Rechenschaftsbericht",
        }
        self.assertTrue(self.assembly.change_attachment_version(self.key, data))
        history_expectation[2].update(data)

        data = {
            "assembly_id": assembly_id,
            "title": "Verfassung des Staates der CdEler",
            "authors": "Anton",
            "filename": "verf.pdf",
        }
        self.assertLess(0, self.assembly.add_attachment(self.key, data, b'abc'))
        del data["assembly_id"]
        history_expectation = {1001: history_expectation, 1002: {1: data}}
        history_expectation[1002][1].update({
            "attachment_id": 1002,
            "version_nr": 1,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'abc'),
        })
        data = {
            "assembly_id": assembly_id,
            "title": "Beschlussvorlage",
            "authors": "Berta",
            "filename": "beschluss.pdf",
        }
        self.assertLess(
            0, self.assembly.add_attachment(self.key, data, b'super secret'))
        del data['assembly_id']
        history_expectation[1003] = {1: data}
        history_expectation[1003][1].update({
            "attachment_id": 1003,
            "version_nr": 1,
            "ctime": nearly_now(),
            "dtime": None,
            "file_hash": get_hash(b'super secret'),
        })
        self.assertEqual(
            {1001, 1002, 1003},
            self.assembly.list_attachments(self.key, assembly_id=assembly_id))
        self.assertEqual(
            {1001}, self.assembly.list_attachments(self.key, ballot_id=ballot_id))
        expectation = {
            1001: {
                'assembly_id': assembly_id,
                'ballot_ids': [ballot_id],
                'id': 1001,
                'num_versions': 1,
                'current_version_nr': 2,
            },
            1002: {
                'assembly_id': assembly_id,
                'ballot_ids': None,
                'id': 1002,
                'num_versions': 1,
                'current_version_nr': 1,
           },
            1003: {
                'assembly_id': assembly_id,
                'ballot_ids': None,
                'id': 1003,
                'num_versions': 1,
                'current_version_nr': 1,
            },
        }
        self.assertEqual(
            expectation, self.assembly.get_attachments(self.key, (1001, 1002, 1003)))
        self.assertEqual(
            history_expectation,
            self.assembly.get_attachments_versions(
                self.key, (1001, 1002, 1003), current_version_only=False))
        history_expectation = {
            1001: {
                2: {
                    'attachment_id': 1001,
                    'authors': 'Farin',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'1234'),
                    'filename': 'rechen_v2.pdf',
                    'id': 1002,
                    'title': 'Rechenschaftsbericht',
                    'version_nr': 2,
                }
            },
            1002: {
                1: {
                    'attachment_id': 1002,
                    'authors': 'Anton',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'abc'),
                    'filename': 'verf.pdf',
                    'id': 1004,
                    'title': 'Verfassung des Staates der CdEler',
                    'version_nr': 1,
                }
            },
            1003: {
                1: {
                    'attachment_id': 1003,
                    'authors': 'Berta',
                    'ctime': nearly_now(),
                    'dtime': None,
                    'file_hash': get_hash(b'super secret'),
                    'filename': 'beschluss.pdf',
                    'id': 1005,
                    'title': 'Beschlussvorlage',
                    'version_nr': 1,
                },
            },
        }
        self.assertEqual(
            history_expectation, self.assembly.get_attachments_versions(
                self.key, (1001, 1002, 1003), current_version_only=True))
        self.assertTrue(self.assembly.delete_attachment(self.key, 1003, {"versions"}))
        del expectation[1003]
        self.assertEqual(
            expectation, self.assembly.get_attachments(self.key, (1001, 1002, 1003)))

    @as_users("werner")
    @prepsql("""INSERT INTO assembly.assemblies
        (title, shortname, description, presider_address, signup_end) VALUES
        ('Umfrage', 'umfrage', 'sagt eure Meinung!', 'umfrage@example.cde',
         date '2111-11-11');""")
    def test_prepsql(self) -> None:
        expectation = {
            1: {'id': 1, 'is_active': True,
                'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                'title': 'Internationaler Kongress'},
            2: {'id': 2, 'is_active': False,
                'signup_end': datetime.datetime(2020, 2, 22, 0, 0, tzinfo=pytz.utc),
                'title': 'Kanonische Beispielversammlung'},
            3: {'id': 3, 'is_active': True,
                'signup_end': datetime.datetime(2222, 2, 22, 0, 0, tzinfo=pytz.utc),
                'title': 'Archiv-Sammlung'},
            1001: {'id': 1001, 'is_active': True,
                   'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                   'title': 'Umfrage'}
        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))

    def test_log(self) -> None:
        # first check the already existing log
        offset = 8
        expectation = (offset, (
            {"id": 1,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 1,
             "assembly_id": 2,
             "persona_id": 18,
             "change_note": None},
            {"id": 2,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 1,
             "assembly_id": 2,
             "persona_id": 1,
             "change_note": None},
            {"id": 3,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 3,
             "assembly_id": 2,
             "persona_id": 3,
             "change_note": None},
            {"id": 4,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 32,
             "assembly_id": 2,
             "persona_id": 32,
             "change_note": None},
            {"id": 5,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 7,
             "assembly_id": 2,
             "persona_id": 7,
             "change_note": None},
            {"id": 6,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 9,
             "assembly_id": 2,
             "persona_id": 9,
             "change_note": None},
            {"id": 7,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 1,
             "assembly_id": 2,
             "persona_id": 17,
             "change_note": None},
            {"id": 8,
             "ctime": nearly_now(),
             "code": const.AssemblyLogCodes.new_attendee,
             "submitted_by": 1,
             "assembly_id": 2,
             "persona_id": 22,
             "change_note": None},
        ))
        self.login("viktor")
        result = self.assembly.retrieve_log(self.key)
        self.assertEqual(expectation, result)
        self.core.logout(self.key)

        # now generate some data
        self.test_entity_assembly()
        self.test_vote()
        self.test_entity_ballot()

        self.login("viktor")
        # check the new data
        sub_id = USER_DICT['werner']['id']
        expectation = (11+offset, (
            {'id': 1001,
             'change_note': None,
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.assembly_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            # we delete all log entries related to an entity when deleting it
            {'id': 1007,
             'change_note': "Außerordentliche Mitgliederversammlung",
             'assembly_id': None,
             'code': const.AssemblyLogCodes.assembly_deleted,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': 48},
            {'id': 1008,
             'change_note': 'Farbe des Logos',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1009,
             'change_note': 'aqua',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1010,
             'change_note': 'rot',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_updated,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1011,
             'change_note': 'gelb',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_removed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1012,
             'change_note': 'j',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1013,
             'change_note': 'n',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1014,
             'change_note': 'Verstehen wir Spaß',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1015,
             'change_note': 'Verstehen wir Spaß',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_created,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'id': 1016,
             'change_note': 'Farbe des Logos',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_deleted,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
        ))
        result = self.assembly.retrieve_log(self.key, offset=offset)
        self.assertEqual(expectation, result)
