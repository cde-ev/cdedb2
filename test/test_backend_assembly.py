#!/usr/bin/env python3

import datetime
import decimal
import time

import pytz

from test.common import BackendTest, as_users, USER_DICT, nearly_now, prepsql
from cdedb.query import QUERY_SPECS, QueryOperators
from cdedb.common import PrivilegeError, FUTURE_TIMESTAMP, now
import cdedb.database.constants as const


class TestAssemblyBackend(BackendTest):
    used_backends = ("core", "assembly")

    @as_users("kalif")
    def test_basics(self, user):
        data = self.core.get_assembly_user(self.key, user['id'])
        data['display_name'] = "Zelda"
        data['family_name'] = "Lord von und zu Hylia"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'given_names', 'family_name'}}
        self.core.change_persona(self.key, setter)
        new_data = self.core.get_assembly_user(self.key, user['id'])
        self.assertEqual(data, new_data)

    @as_users("anton", "berta", "charly", "kalif")
    def test_does_attend(self, user):
        self.assertEqual(user['id'] != 3, self.assembly.does_attend(
            self.key, assembly_id=1))
        self.assertEqual(user['id'] != 3, self.assembly.does_attend(
            self.key, ballot_id=3))

    @as_users("charly")
    def test_list_attendees(self, user):
        expectation = {1, 2, 9, 11, 23, 100}
        self.assertEqual(expectation, self.assembly.list_attendees(self.key, 1))

    @as_users("werner")
    def test_entity_assembly(self, user):
        expectation = {
            1: {
                'id': 1,
                'is_active': True,
                'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                'title': 'Internationaler Kongress'
            },
            2: {
                'id': 2,
                'is_active': True,
                'signup_end': datetime.datetime(2222, 2, 22, 0, 0,tzinfo=pytz.utc),
                'title': 'Kanonische Beispielversammlung'
            }

        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))
        expectation = {
            'description': 'Proletarier aller Länder vereinigt Euch!',
            'id': 1,
            'is_active': True,
            'mail_address': 'kongress@example.cde',
            'notes': None,
            'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
            'title': 'Internationaler Kongress'}
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, 1))
        data = {
            'id': 1,
            'notes': "More fun for everybody",
            'signup_end': datetime.datetime(2111, 11, 11, 23, 0, tzinfo=pytz.utc),
            'title': "Allumfassendes Konklave",
        }
        self.assertLess(0, self.assembly.set_assembly(self.key, data))
        expectation.update(data)
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, 1))
        data = {
            'description': 'Beschluss über die Anzahl anzuschaffender Schachsets',
            'notes': None,
            'signup_end': now(),
            'title': 'Außerordentliche Mitgliederversammlung'
        }
        new_id = self.assembly.create_assembly(self.key, data)
        expectation = data
        expectation['id'] = new_id
        expectation['mail_address'] = None
        expectation['is_active'] = True
        self.assertEqual(expectation, self.assembly.get_assembly(
            self.key, new_id))

        self.assertLess(0, self.assembly.delete_assembly(
            self.key, new_id, ("ballots", "attendees", "attachments", "log",
                               "mailinglists")))

    @as_users("werner")
    def test_ticket_176(self, user):
        data = {
            'description': None,
            'notes': None,
            'signup_end': now(),
            'title': 'Außerordentliche Mitgliederversammlung'
        }
        new_id = self.assembly.create_assembly(self.key, data)
        self.assertLess(0, self.assembly.conclude_assembly(self.key, new_id))

    @as_users("werner")
    def test_entity_ballot(self, user):
        assembly_id = 1
        expectation = {1: 'Antwort auf die letzte aller Fragen',
                       2: 'Farbe des Logos',
                       3: 'Bester Hof',
                       4: 'Akademie-Nachtisch',
                       5: 'Lieblingszahl'}
        self.assertEqual(expectation, self.assembly.list_ballots(self.key,
                                                                 assembly_id))
        expectation = {
            1: {'assembly_id': 1,
                'use_bar': True,
                'candidates': {2: {'ballot_id': 1,
                                   'description': 'Ich',
                                   'id': 2,
                                   'moniker': '1'},
                               3: {'ballot_id': 1,
                                   'description': '23',
                                   'id': 3,
                                   'moniker': '2'},
                               4: {'ballot_id': 1,
                                   'description': '42',
                                   'id': 4,
                                   'moniker': '3'},
                               5: {'ballot_id': 1,
                                   'description': 'Philosophie',
                                   'id': 5,
                                   'moniker': '4'}},
                'description': 'Nach dem Leben, dem Universum und dem ganzen Rest.',
                'extended': True,
                'id': 1,
                'is_tallied': False,
                'notes': None,
                'quorum': 2,
                'title': 'Antwort auf die letzte aller Fragen',
                'vote_begin': datetime.datetime(2002, 2, 22, 20, 22, 22, 222222, tzinfo=pytz.utc),
                'vote_end': datetime.datetime(2002, 2, 23, 20, 22, 22, 222222, tzinfo=pytz.utc),
                'vote_extension_end': nearly_now(),
                'votes': None},
            4: {'assembly_id': 1,
                'use_bar': True,
                'candidates': {17: {'ballot_id': 4,
                                    'description': 'Wackelpudding',
                                    'id': 17,
                                    'moniker': 'W'},
                               18: {'ballot_id': 4,
                                    'description': 'Salat',
                                    'id': 18,
                                    'moniker': 'S'},
                               19: {'ballot_id': 4,
                                    'description': 'Eis',
                                    'id': 19,
                                    'moniker': 'E'},
                               20: {'ballot_id': 4,
                                    'description': 'Joghurt',
                                    'id': 20,
                                    'moniker': 'J'},
                               21: {'ballot_id': 4,
                                    'description': 'Nichts',
                                    'id': 21,
                                    'moniker': 'N'},},
                'description': 'denkt an die Frutaner',
                'extended': None,
                'id': 4,
                'is_tallied': False,
                'notes': None,
                'quorum': 0,
                'title': 'Akademie-Nachtisch',
                'vote_begin': nearly_now(),
                'vote_end': datetime.datetime(2222, 1, 1, 20, 22, 22, 222222, tzinfo=pytz.utc),
                'vote_extension_end': None,
                'votes': 2}}
        self.assertEqual(expectation, self.assembly.get_ballots(self.key,
                                                                (1, 4)))
        data = {
            'id': 4,
            'notes': "Won't work",
        }
        with self.assertRaises(ValueError):
            self.assembly.set_ballot(self.key, data)
        expectation = {
            'assembly_id': 1,
            'use_bar': False,
            'candidates': {6: {'ballot_id': 2,
                               'description': 'Rot',
                               'id': 6,
                               'moniker': 'rot'},
                           7: {'ballot_id': 2,
                               'description': 'Gelb',
                               'id': 7,
                               'moniker': 'gelb'},
                           8: {'ballot_id': 2,
                               'description': 'Grün',
                               'id': 8,
                               'moniker': 'gruen'},
                           9: {'ballot_id': 2,
                               'description': 'Blau',
                               'id': 9,
                               'moniker': 'blau'}},
            'description': 'Ulitmativ letzte Entscheidung',
            'extended': None,
            'id': 2,
            'is_tallied': False,
            'notes': 'Nochmal alle auf diese wichtige Entscheidung hinweisen.',
            'quorum': 0,
            'title': 'Farbe des Logos',
            'vote_begin': datetime.datetime(2222, 2, 2, 20, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 3, 20, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_extension_end': None,
            'votes': None}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, 2))
        data = {
            'id': 2,
            'use_bar': True,
            'candidates': {
                6: {'description': 'Teracotta', 'moniker': 'terra'},
                7: None,
                -1: {'description': 'Aquamarin', 'moniker': 'aqua'},
            },
            'notes': "foo",
            'vote_extension_end': datetime.datetime(2222, 2, 20, 20, 22, 22, 222222, tzinfo=pytz.utc),
            'quorum': 42,
        }
        self.assertLess(0, self.assembly.set_ballot(self.key, data))
        for key in ('use_bar', 'notes', 'vote_extension_end', 'quorum'):
            expectation[key] = data[key]
        expectation['candidates'][6]['description'] = data['candidates'][6]['description']
        expectation['candidates'][6]['moniker'] = data['candidates'][6]['moniker']
        del expectation['candidates'][7]
        expectation['candidates'][1001] = {
            'id': 1001,
            'ballot_id': 2,
            'description': 'Aquamarin',
            'moniker': 'aqua'}
        self.assertEqual(expectation, self.assembly.get_ballot(self.key, 2))

        data = {
            'assembly_id': assembly_id,
            'use_bar': False,
            'candidates': {-1: {'description': 'Ja', 'moniker': 'j'},
                           -2: {'description': 'Nein', 'moniker': 'n'},},
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'quorum': 10,
            'title': 'Verstehen wir Spaß',
            'vote_begin': datetime.datetime(2222, 2, 5, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_extension_end': datetime.datetime(2222, 2, 7, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'votes': None}
        new_id = self.assembly.create_ballot(self.key, data)
        self.assertLess(0, new_id)
        data.update({
            'extended': None,
            'id': new_id,
            'is_tallied': False,
            'candidates': {1002: {'ballot_id': new_id,
                                  'description': 'Ja',
                                  'id': 1002,
                                  'moniker': 'j'},
                           1003: {'ballot_id': new_id,
                                  'description': 'Nein',
                                  'id': 1003,
                                  'moniker': 'n'},},
        })
        self.assertEqual(data, self.assembly.get_ballot(self.key, new_id))

        self.assertLess(0, self.assembly.delete_ballot(
            self.key, 2, cascade=("candidates", "attachments", "voters")))
        expectation = {
            1: 'Antwort auf die letzte aller Fragen',
            3: 'Bester Hof',
            4: 'Akademie-Nachtisch',
            5: 'Lieblingszahl',
            new_id: 'Verstehen wir Spaß'}
        self.assertEqual(expectation, self.assembly.list_ballots(self.key, assembly_id))

    @as_users("werner")
    def test_quorum(self, user):
        data = {
            'assembly_id': 1,
            'use_bar': False,
            'candidates': {-1: {'description': 'Ja', 'moniker': 'j'},
                           -2: {'description': 'Nein', 'moniker': 'n'},},
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'quorum': 11,
            'title': 'Verstehen wir Spaß',
            'vote_begin': datetime.datetime(2222, 2, 5, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'vote_extension_end': None,
            'votes': None}
        with self.assertRaises(ValueError):
            self.assembly.create_ballot(self.key, data)

        data['quorum'] = 0
        data['vote_extension_end'] = datetime.datetime(2222, 2, 7, 13, 22, 22, 222222, tzinfo=pytz.utc)
        with self.assertRaises(ValueError):
            self.assembly.create_ballot(self.key, data)

        # now create the ballot
        data['quorum'] = 11
        new_id = self.assembly.create_ballot(self.key, data)

        data = {
            'id': new_id,
            'quorum': 0,
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
            'quorum': 0,
            'vote_extension_end': None,
        }
        self.assembly.set_ballot(self.key, data)

    def test_extension(self):
        self.login(USER_DICT['werner'])
        future = now() + datetime.timedelta(seconds=.5)
        farfuture = now() + datetime.timedelta(seconds=1)
        data = {
            'assembly_id': 1,
            'use_bar': False,
            'candidates': {-1: {'description': 'Ja', 'moniker': 'j'},
                           -2: {'description': 'Nein', 'moniker': 'n'},},
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'quorum': 10,
            'title': 'Verstehen wir Spaß',
            'vote_begin': future,
            'vote_end': farfuture,
            'vote_extension_end': datetime.datetime(2222, 2, 6, 13, 22, 22, 222222, tzinfo=pytz.utc),
            'votes': None}
        new_id = self.assembly.create_ballot(self.key, data)
        self.assertEqual(None, self.assembly.get_ballot(self.key, new_id)['extended'])
        self.login(USER_DICT['kalif'])
        time.sleep(1)
        self.assertEqual(True, self.assembly.check_voting_priod_extension(self.key, new_id))
        self.assertEqual(True, self.assembly.get_ballot(self.key, new_id)['extended'])

    @as_users("charly")
    def test_signup(self, user):
        self.assertEqual(False, self.assembly.does_attend(
            self.key, assembly_id=1))
        secret = self.assembly.signup(self.key, 1)
        self.assertLess(0, len(secret))
        self.assertEqual(True, self.assembly.does_attend(
            self.key, assembly_id=1))

    def test_get_vote(self):
        tests = (
            {'user': 'anton', 'ballot_id': 1, 'secret': 'aoeuidhtns', 'expectation': '2>3>_bar_>1=4'},
            {'user': 'berta', 'ballot_id': 1, 'secret': 'snthdiueoa', 'expectation': '3>2=4>_bar_>1'},
            {'user': 'inga', 'ballot_id': 1, 'secret': 'asonetuhid', 'expectation': '_bar_>4>3>2>1'},
            {'user': 'kalif', 'ballot_id': 1, 'secret': 'bxronkxeud', 'expectation': '1>2=3=4>_bar_'},
            {'user': 'anton', 'ballot_id': 1, 'secret': None, 'expectation': '2>3>_bar_>1=4'},
            {'user': 'berta', 'ballot_id': 1, 'secret': None, 'expectation': '3>2=4>_bar_>1'},
            {'user': 'inga', 'ballot_id': 1, 'secret': None, 'expectation': '_bar_>4>3>2>1'},
            {'user': 'kalif', 'ballot_id': 1, 'secret': None, 'expectation': '1>2=3=4>_bar_'},
            {'user': 'berta', 'ballot_id': 2, 'secret': None, 'expectation': None},
            {'user': 'berta', 'ballot_id': 3, 'secret': None, 'expectation': 'Lo>Li=St=Fi=Bu=Go=_bar_'},
            {'user': 'berta', 'ballot_id': 4, 'secret': None, 'expectation': None},
        )
        for case in tests:
            with self.subTest(case=case):
                self.login(USER_DICT[case['user']])
                self.assertEqual(case['expectation'],
                                 self.assembly.get_vote(self.key, case['ballot_id'], case['secret']))

    def test_vote(self):
        self.login(USER_DICT['anton'])
        self.assertEqual(None, self.assembly.get_vote(self.key, 3, secret=None))
        self.assertLess(0, self.assembly.vote(self.key, 3, 'Go>Li=St=Fi=Bu=Lo=_bar_', secret=None))
        self.assertEqual('Go>Li=St=Fi=Bu=Lo=_bar_', self.assembly.get_vote(self.key, 3, secret=None))
        self.login(USER_DICT['berta'])
        self.assertEqual('Lo>Li=St=Fi=Bu=Go=_bar_', self.assembly.get_vote(self.key, 3, secret=None))
        self.assertLess(0, self.assembly.vote(self.key, 3, 'St>Li=Go=Fi=Bu=Lo=_bar_', secret=None))
        self.assertEqual('St>Li=Go=Fi=Bu=Lo=_bar_', self.assembly.get_vote(self.key, 3, secret=None))

    @as_users("kalif")
    def test_tally(self, user):
        self.assertEqual(False, self.assembly.get_ballot(self.key, 1)['is_tallied'])
        self.assertTrue(self.assembly.tally_ballot(self.key, 1))
        with open("/tmp/cdedb-store/testfiles/ballot_result.json", 'rb') as f:
            with open("/tmp/cdedb-store/ballot_result/1", 'rb') as g:
                self.assertEqual(f.read(), g.read())

    @as_users("werner")
    def test_conclusion(self, user):
        data = {
            'description': 'Beschluss über die Anzahl anzuschaffender Schachsets',
            'notes': None,
            'signup_end': FUTURE_TIMESTAMP,
            'title': 'Außerordentliche Mitgliederversammlung'
        }
        new_id = self.assembly.create_assembly(self.key, data)
        self.assembly.signup(self.key, new_id)
        future = now() + datetime.timedelta(seconds=.5)
        farfuture = now() + datetime.timedelta(seconds=1)
        data = {
            'assembly_id': new_id,
            'use_bar': False,
            'candidates': {-1: {'description': 'Ja', 'moniker': 'j'},
                           -2: {'description': 'Nein', 'moniker': 'n'},},
            'description': 'Sind sie sich sicher?',
            'notes': None,
            'quorum': 0,
            'title': 'Verstehen wir Spaß',
            'vote_begin': future,
            'vote_end': farfuture,
            'vote_extension_end': None,
            'votes': None}
        ballot_id = self.assembly.create_ballot(self.key, data)
        time.sleep(1)
        self.assembly.check_voting_priod_extension(self.key, ballot_id)
        self.assertTrue(self.assembly.tally_ballot(self.key, ballot_id))
        self.assembly.external_signup(self.key, new_id,
                                      persona_id=USER_DICT['kalif']['id'])
        update = {
            'id': new_id,
            'signup_end': now(),
        }
        self.assembly.set_assembly(self.key, update)
        self.assertEqual({23, 11}, self.assembly.list_attendees(self.key, new_id))
        self.assertLess(0, self.assembly.conclude_assembly(self.key, new_id))

    @as_users("werner")
    def test_entity_attachments(self, user):
        expectation = {}
        self.assertEqual(expectation, self.assembly.list_attachments(self.key, assembly_id=1))
        self.assertEqual(expectation, self.assembly.list_attachments(self.key, ballot_id=1))
        data = {
            "assembly_id": 1,
            "title": "Rechenschaftsbericht",
            "filename": "rechen.pdf",
        }
        self.assertLess(0, self.assembly.add_attachment(self.key, data, b'123'))
        data = {
            "assembly_id": 1,
            "title": "Verfassung des Staates der CdEler",
            "filename": "verf.pdf",
        }
        self.assertLess(0, self.assembly.add_attachment(self.key, data, b'123'))
        data = {
            "ballot_id": 2,
            "title": "Beschlussvorlage",
            "filename": "beschluss.pdf",
        }
        self.assertLess(0, self.assembly.add_attachment(self.key, data, b'123'))
        expectation = {1: 'Rechenschaftsbericht', 2: 'Verfassung des Staates der CdEler'}
        self.assertEqual(expectation, self.assembly.list_attachments(self.key, assembly_id=1))
        expectation = {3: 'Beschlussvorlage'}
        self.assertEqual(expectation, self.assembly.list_attachments(self.key, ballot_id=2))
        expectation = {
            1: {'assembly_id': 1,
                'ballot_id': None,
                'filename': 'rechen.pdf',
                'id': 1,
                'title': 'Rechenschaftsbericht'},
            2: {'assembly_id': 1,
                'ballot_id': None,
                'filename': 'verf.pdf',
                'id': 2,
                'title': 'Verfassung des Staates der CdEler'},
            3: {'assembly_id': None,
                'ballot_id': 2,
                'filename': 'beschluss.pdf',
                'id': 3,
                'title': 'Beschlussvorlage'}}
        self.assertEqual(expectation, self.assembly.get_attachments(self.key, (1, 2, 3)))
        self.assertLess(0, self.assembly.remove_attachment(self.key, 1))
        expectation = {2: 'Verfassung des Staates der CdEler'}
        self.assertEqual(expectation, self.assembly.list_attachments(self.key, assembly_id=1))

    @as_users("werner")
    @prepsql("""INSERT INTO assembly.assemblies
        (title, description, mail_address, signup_end) VALUES
        ('Umfrage', 'sagt eure Meinung!', 'umfrage@example.cde',
         date '2111-11-11');""")
    def test_prepsql(self, user):
        expectation = {
            1: {'id': 1, 'is_active': True,
                'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                'title': 'Internationaler Kongress'},
            2: {'id': 2, 'is_active': True,
                'signup_end': datetime.datetime(2222, 2, 22, 0, 0, tzinfo=pytz.utc),
                'title': 'Kanonische Beispielversammlung'},
            1001: {'id': 1001, 'is_active': True,
                   'signup_end': datetime.datetime(2111, 11, 11, 0, 0, tzinfo=pytz.utc),
                   'title': 'Umfrage'}
        }
        self.assertEqual(expectation, self.assembly.list_assemblies(self.key))

    @as_users("werner")
    def test_log(self, user):
        # first generate some data
        self.test_entity_assembly()
        self.test_vote()
        self.test_entity_ballot()

        # now check it
        sub_id = USER_DICT['werner']['id']
        expectation = (11, (
            {'additional_info': None,
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.assembly_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': "Außerordentliche Mitgliederversammlung",
             'assembly_id': None,
             'code': const.AssemblyLogCodes.assembly_deleted,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'Farbe des Logos',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'aqua',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'rot',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_updated,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'gelb',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_removed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'j',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'n',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.candidate_added,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'Verstehen wir Spaß',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_changed,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'Verstehen wir Spaß',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_created,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
            {'additional_info': 'Farbe des Logos',
             'assembly_id': 1,
             'code': const.AssemblyLogCodes.ballot_deleted,
             'ctime': nearly_now(),
             'persona_id': None,
             'submitted_by': sub_id},
        ))
        self.assertEqual(expectation, self.assembly.retrieve_log(self.key))
