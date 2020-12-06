#!/usr/bin/env python3

import collections.abc
import datetime
import decimal
import json
import numbers
import unittest.mock

import cdedb.database.constants as const
from cdedb.common import now, xsorted

from test.common import CronTest, prepsql

INSERT_TEMPLATE = """
INSERT INTO {table} ({columns}) VALUES ({values});
"""


def format_insert_sql(table, data):
    tmp = {}
    for key, value in data.items():
        if value is None:
            tmp[key] = "NULL"
        elif isinstance(value, datetime.datetime):
            tmp[key] = "timestamptz '{}'".format(value.isoformat())
        elif isinstance(value, datetime.date):
            tmp[key] = "date '{}'".format(value.isoformat())
        elif isinstance(value, str):
            tmp[key] = "'{}'".format(value)
        elif isinstance(value, numbers.Number):
            tmp[key] = "{}".format(value)
        elif isinstance(value, collections.Mapping):
            tmp[key] = "'{}'::jsonb".format(json.dumps(value))
        else:
            raise ValueError("Unknown datum {} -> {}".format(key, value))
    keys = tuple(tmp)
    return INSERT_TEMPLATE.format(table=table, columns=", ".join(keys),
                                  values=", ".join(tmp[key] for key in keys))


def genesis_template(**kwargs):
    defaults = {
        'ctime': now(),
        'realm': "event",
        'case_status': const.GenesisStati.to_review.value,
        'username': "zaphod@example.cde",
        'given_names': "Zaphod",
        'family_name': "Zappa"
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.genesis_cases", data)


def changelog_template(**kwargs):
    defaults = {
        'address': 'Im Garten 55',
        'address2': 'Strange Road 1 3/4',
        'address_supplement': 'bei Spielfraus',
        'address_supplement2': 'in between',
        'affiliation': 'nobody',
        'balance': decimal.Decimal('12.50'),
        'birth_name': 'Gemeinser',
        'birthday': datetime.date(1980, 2, 11),
        'bub_search': True,
        'change_note': 'Radical change.',
        'code': const.MemberChangeStati.pending.value,
        'country': None,
        'country2': 'Further Away',
        'ctime': now(),
        'decided_search': True,
        'display_name': 'Zelda',
        'family_name': 'Zeruda-Hime',
        'foto': 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9',
        'free_form': 'stuff she said',
        'gender': const.Genders.female.value,
        'generation': 2,
        'given_names': 'Zelda',
        'interests': 'never',
        'is_active': True,
        'is_meta_admin': False,
        'is_archived': False,
        'is_assembly_admin': False,
        'is_assembly_realm': True,
        'is_cde_admin': False,
        'is_cde_realm': True,
        'is_core_admin': False,
        'is_event_admin': False,
        'is_event_realm': True,
        'is_member': True,
        'is_ml_admin': False,
        'is_ml_realm': True,
        'is_searchable': True,
        'location': 'Dystopia',
        'location2': 'Random City',
        'mobile': '0163/987654321',
        'name_supplement': 'a.D.',
        'notes': 'Not Link.',
        'persona_id': 2,
        'postal_code': '34576',
        'postal_code2': '9XA 45-$',
        'reviewed_by': None,
        'specialisation': 'nix',
        'submitted_by': 2,
        'telephone': '+49 (5432) 123456789',
        'timeline': 'nirgendwo',
        'title': 'Prof.',
        'trial_member': False,
        'username': 'zelda@example.cde',
        'weblink': 'https://www.uni.cde'
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.changelog", data)


def cron_template(**kwargs):
    defaults = {
        'title': None,
        'store': {}
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.cron_store", data)


def subscription_request_template(**kwargs):
    defaults = {
        'subscription_state': const.SubscriptionStates.pending
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("ml.subscription_states", data)


def privilege_change_template(**kwargs):
    defaults = {
        'persona_id': 2,
        'ctime': now(),
        'submitted_by': 1,
        'reviewer': None,
        'status': const.PrivilegeChangeStati.pending,
        'notes': "For testing",
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.privilege_changes", data)


class TestCron(CronTest):
    def test_genesis_remind_empty(self):
        self.execute('genesis_remind')

    @prepsql(genesis_template(
        ctime=(now() - datetime.timedelta(hours=6))))
    def test_genesis_remind_new(self):
        self.execute('genesis_remind')
        self.assertEqual(["genesis_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql(genesis_template())
    def test_genesis_remind_newer(self):
        self.execute('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        genesis_template(ctime=(now() - datetime.timedelta(hours=6)))
        + cron_template(
            title="genesis_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": [1001]}))
    def test_genesis_remind_old(self):
        self.execute('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        genesis_template(ctime=(now() - datetime.timedelta(hours=6)))
        + cron_template(title="genesis_remind",
                        store={"tstamp": 1, "ids": [1001]}))
    def test_genesis_remind_older(self):
        self.execute('genesis_remind')
        self.assertEqual(["genesis_requests_pending"],
                         [mail.template for mail in self.mails])

    def test_genesis_forget_empty(self):
        self.execute('genesis_forget')

    @prepsql(genesis_template())
    def test_genesis_forget_unrelated(self):
        self.execute('genesis_forget')
        self.assertEqual({1001}, set(self.core.genesis_list_cases()))

    @prepsql(genesis_template(
        ctime=datetime.datetime(2000, 1, 1),
        case_status=const.GenesisStati.rejected.value))
    def test_genesis_forget_rejected(self):
        self.execute('genesis_forget')
        self.assertEqual({}, self.core.genesis_list_cases())

    @prepsql(genesis_template(
        ctime=datetime.datetime(2000, 1, 1),
        case_status=const.GenesisStati.unconfirmed.value))
    def test_genesis_forget_unconfirmed(self):
        self.execute('genesis_forget')
        self.assertEqual({}, self.core.genesis_list_cases())

    @prepsql(genesis_template(
        case_status=const.GenesisStati.unconfirmed.value))
    def test_genesis_forget_recent_unconfirmed(self):
        self.execute('genesis_forget')
        self.assertEqual({1001}, set(self.core.genesis_list_cases()))

    def test_changelog_remind_empty(self):
        self.cron.execute(['pending_changelog_remind'])

    @prepsql(changelog_template(
        ctime=now() - datetime.timedelta(hours=14)))
    def test_changelog_remind_new(self):
        self.execute('pending_changelog_remind')
        self.assertEqual(["changelog_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql(changelog_template())
    def test_changelog_remind_newer(self):
        self.execute('pending_changelog_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        changelog_template(ctime=now() - datetime.timedelta(hours=14))
        + cron_template(
            title="pending_changelog_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": ['2/2']}))
    def test_changelog_remind_old(self):
        self.execute('pending_changelog_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        changelog_template(ctime=now() - datetime.timedelta(hours=14))
        + cron_template(
            title="pending_changelog_remind",
            store={"tstamp": 1, "ids": ['2/2']}))
    def test_changelog_remind_older(self):
        self.execute('pending_changelog_remind')
        self.assertEqual(["changelog_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql("DELETE FROM ml.subscription_states WHERE subscription_state = "
             "{};".format(const.SubscriptionStates.pending))
    def test_subscription_request_remind_empty(self):
        self.execute('subscription_request_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    def test_subscription_request_remind_new(self):
        # Mailinglist 7 has pending subscription for persona 6
        # Mailinglist 54 for 2 and Mailinglist 56 for 7
        self.execute('subscription_request_remind')
        self.assertEqual(["subscription_request_remind"] * 3,
                         [mail.template for mail in self.mails])

    @prepsql(subscription_request_template(persona_id=9, mailinglist_id=4)
             + subscription_request_template(persona_id=27, mailinglist_id=4)
             + subscription_request_template(persona_id=2, mailinglist_id=7)
             + subscription_request_template(persona_id=3, mailinglist_id=8))
    def test_subscription_request_remind_multiple(self):
        self.execute('subscription_request_remind')
        # 7, 54 and 56 have pending subscriptions
        self.assertEqual(["subscription_request_remind"] * 5,
                         [mail.template for mail in self.mails])

    @prepsql(cron_template(title="subscription_request_remind",
                           store={7: {'persona_ids': [6],
                                      'tstamp': now().timestamp()},
                                  54: {'persona_ids': [2],
                                      'tstamp': now().timestamp()},
                                  56: {'persona_ids': [7],
                                      'tstamp': now().timestamp()}}))
    def test_subscription_request_remind_old(self):
        self.execute('subscription_request_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    def test_privilege_change_remind_empty(self):
        self.execute('privilege_change_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(privilege_change_template(
        is_cde_admin=True, ctime=now() - datetime.timedelta(hours=6)))
    def test_privilege_change_remind_new(self):
        self.execute('privilege_change_remind')
        self.assertEqual(['privilege_change_remind'],
                         [mail.template for mail in self.mails])

    @prepsql(privilege_change_template(is_cde_admin=True))
    def test_privilege_change_remind_newer(self):
        self.execute('privilege_change_remind')
        self.assertEqual([],
                         [mail.template for mail in self.mails])

    @prepsql(
        privilege_change_template(is_cde_admin=True,
                                  ctime=now() - datetime.timedelta(hours=6))
        + cron_template(
            title="privilege_change_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": [1001]}))
    def test_privilege_change_remind_old(self):
        self.execute('privilege_change_remind')
        self.assertEqual([],
                         [mail.template for mail in self.mails])

    @prepsql(
        privilege_change_template(is_cde_admin=True,
                                  ctime=now() - datetime.timedelta(hours=6))
        + cron_template(
            title="privilege_change_remind",
            store={"tstamp": 1, "ids": [1001]}))
    def test_privilege_change_remind_older(self):
        self.execute('privilege_change_remind')
        self.assertEqual(['privilege_change_remind'],
                         [mail.template for mail in self.mails])

    @prepsql("UPDATE cde.lastschrift SET revoked_at = now() WHERE id = 2")
    def test_forget_old_lastschrifts(self):
        name = "forget_old_lastschrifts"
        self.assertEqual(
            [1, 2], list(self.cde.list_lastschrift(active=False)))
        self.execute(name)
        # Make sure only the old lastschrift is deleted.
        self.assertEqual(
            [2], list(self.cde.list_lastschrift(active=False))
        )
        self.assertEqual([1], self.core.get_cron_store(name)["deleted"])
        self.execute(name)
        # Make sure nothing changes when the cron job runs again.
        self.assertEqual(
            [2], list(self.cde.list_lastschrift(active=False))
        )
        self.assertEqual([1], self.core.get_cron_store(name)["deleted"])

    def test_tally_ballots(self):
        ballot_ids = set()
        for assembly_id in self.assembly.list_assemblies():
            ballot_ids |= self.assembly.list_ballots(assembly_id).keys()
        ballots = self.assembly.get_ballots(ballot_ids)
        self.assertTrue(all(not b['is_tallied'] for b in ballots.values()))
        self.execute("check_tally_ballot")
        ballots = self.assembly.get_ballots(ballot_ids)
        self.assertEqual(2, sum(1 for b in ballots.values() if b['is_tallied']))
        self.assertEqual(['ballot_tallied'] * 2,
                         [mail.template for mail in self.mails])

    def test_write_subscription_states(self):
        # We just want to test that no exception is raised.
        self.execute('write_subscription_states')

    @unittest.mock.patch("mailmanclient.Client")
    def test_mailman_sync(self, client_class):
        self._run_periodics.add('mailman_sync')
        #
        # Prepare
        #

        class SaveDict(dict):
            def save(self):
                pass

        # Commented items will be available in mailman 3.3
        base_settings = {
            'send_welcome_message': False,
            # 'send_goodbye_message': False,
            'subscription_policy': 'moderate',
            # 'unsubscription_policy': 'moderate',
            'archive_policy': 'private',
            # 'filter_content': True,
            # 'filter_action': 'forward',
            # 'pass_extensions': ['pdf'],
            # 'pass_types': ['multipart', 'text/plain', 'application/pdf'],
            'convert_html_to_plaintext': True,
            'dmarc_mitigate_action': 'wrap_message',
            'dmarc_mitigate_unconditionally': False,
            'dmarc_wrapped_message_text': 'Nachricht wegen DMARC eingepackt.',
            'administrivia': True,
            'member_roster_visibility': 'moderators',
            'advertised': True,
        }
        mm_lists = {
            'zombie': unittest.mock.MagicMock(
                fqdn_listname='zombie@lists.cde-ev.de'),
            'announce': unittest.mock.MagicMock(
                fqdn_listname='announce@lists.cde-ev.de',
                settings=SaveDict(
                    **base_settings,
                    **{'display_name': "Announce name",
                       'description': "Announce description",
                       'info': "Announce info",
                       'subject_prefix': "[ann] ",
                       'max_message_size': 1024,
                       'default_member_action': 'hold',
                       'default_nonmember_action': 'hold',
                       })),
            'witz': unittest.mock.MagicMock(
                fqdn_listname='witz@lists.cde-ev.de',
                settings=SaveDict(
                    **base_settings,
                    **{'display_name': "Witz name",
                       'description': "Witz description",
                       'info': "Witz info",
                       'subject_prefix': "[witz] ",
                       'max_message_size': 512,
                       'default_member_action': 'hold',
                       'default_nonmember_action': 'hold',
                       })),
            'klatsch': unittest.mock.MagicMock(),
            'aktivenforum2000': unittest.mock.MagicMock(),
            'aktivenforum': unittest.mock.MagicMock(),
            'wait': unittest.mock.MagicMock(),
            'participants': unittest.mock.MagicMock(),
            'kongress': unittest.mock.MagicMock(),
            'kongress-leitung': unittest.mock.MagicMock(),
            'werbung': unittest.mock.MagicMock(),
            'aka': unittest.mock.MagicMock(),
            'opt': unittest.mock.MagicMock(),
            'party50-all': unittest.mock.MagicMock(),
            'party50': unittest.mock.MagicMock(),
            'info': unittest.mock.MagicMock(),
            'mitgestaltung': unittest.mock.MagicMock(),
            'all': unittest.mock.MagicMock(),
            'gutscheine': unittest.mock.MagicMock(),
            'bau': unittest.mock.MagicMock(),
            'wal': unittest.mock.MagicMock(),
            'test-gast': unittest.mock.MagicMock(),
            'kanonisch': unittest.mock.MagicMock(),
            '42': unittest.mock.MagicMock(),
            'dsa': unittest.mock.MagicMock(),
            'platin': unittest.mock.MagicMock(),
            'geheim': unittest.mock.MagicMock(),
            'hogwarts': unittest.mock.MagicMock(),
        }

        client = client_class.return_value
        client.lists = [mm_lists['announce'], mm_lists['witz'],
                        mm_lists['zombie']]
        client.get_domain.return_value.create_list.side_effect = mm_lists.get
        mm_lists['witz'].members = [
            unittest.mock.MagicMock(address=unittest.mock.MagicMock(
                email='janis-spam@example.cde')),
            unittest.mock.MagicMock(address=unittest.mock.MagicMock(
                email='undead@example.cde'))]

        #
        # Run
        #
        self.execute('mailman_sync')

        #
        # Check
        #
        umcall = unittest.mock.call
        # Creation
        self.assertEqual(
            list(xsorted(
                client.get_domain.return_value.create_list.call_args_list)),
            list(xsorted([umcall('wait'),
                          umcall('klatsch'),
                          umcall('aka'),
                          umcall('opt'),
                          umcall('werbung'),
                          umcall('aktivenforum'),
                          umcall('aktivenforum2000'),
                          umcall('kongress'),
                          umcall('participants'),
                          umcall('party50-all'),
                          umcall('party50'),
                          umcall('info'),
                          umcall('mitgestaltung'),
                          umcall('all'),
                          umcall('gutscheine'),
                          umcall('bau'),
                          umcall('wal'),
                          umcall('test-gast'),
                          umcall('kanonisch'),
                          umcall('42'),
                          umcall('dsa'),
                          umcall('platin'),
                          umcall('geheim'),
                          umcall('hogwarts'),
                          ])))
        # Meta update
        expectation = {
            'advertised': True,
            'default_member_action': 'accept',
            'default_nonmember_action': 'hold',
            'display_name': 'Witz des Tages',
            'info': 'Einer geht noch ...',
            'max_message_size': 2048,
            'subject_prefix': '[witz] ',
        }
        for key, value in expectation.items():
            self.assertEqual(mm_lists['witz'].settings[key], value)
        self.assertEqual(mm_lists['werbung'].set_template.call_count, 1)
        # Subscriber update
        self.assertEqual(
            mm_lists['witz'].subscribe.call_args_list,
            [umcall('new-anton@example.cde',
                    display_name='Anton Armin A. Administrator',
                    pre_approved=True, pre_confirmed=True, pre_verified=True)])
        self.assertEqual(
            mm_lists['witz'].unsubscribe.call_args_list,
            [umcall('undead@example.cde')])
        self.assertEqual(mm_lists['klatsch'].subscribe.call_count, 4)
        # Moderator update
        self.assertEqual(
            mm_lists['aka'].add_moderator.call_args_list,
            [umcall('garcia@example.cde')])
        # Whitelist update
        self.assertEqual(
            list(xsorted(mm_lists['aktivenforum'].add_role.call_args_list)),
            list(xsorted([umcall('nonmember', 'captiankirk@example.cde'),
                          umcall('nonmember', 'aliens@example.cde'),
                          umcall('nonmember', 'drwho@example.cde')])))

        # Deletion
        self.assertEqual(client.delete_list.call_args_list,
                         [umcall('zombie@lists.cde-ev.de')])
