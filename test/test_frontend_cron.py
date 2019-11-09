#!/usr/bin/env python3

import collections.abc
import datetime
import decimal
import json
import numbers

import cdedb.database.constants as const
from cdedb.common import now

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
        'change_status': const.MemberChangeStati.pending.value,
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
        'moniker': None,
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
            moniker="genesis_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": [1]}))
    def test_genesis_remind_old(self):
        self.execute('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        genesis_template(ctime=(now() - datetime.timedelta(hours=6)))
        + cron_template(moniker="genesis_remind",
                        store={"tstamp": 1, "ids": [1]}))
    def test_genesis_remind_older(self):
        self.execute('genesis_remind')
        self.assertEqual(["genesis_requests_pending"],
                         [mail.template for mail in self.mails])

    def test_genesis_forget_empty(self):
        self.execute('genesis_forget')

    @prepsql(genesis_template())
    def test_genesis_forget_unrelated(self):
        self.execute('genesis_forget')
        self.assertEqual({1}, set(self.core.genesis_list_cases()))

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
        self.assertEqual({1}, set(self.core.genesis_list_cases()))

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
            moniker="pending_changelog_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": ['2/2']}))
    def test_changelog_remind_old(self):
        self.execute('pending_changelog_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        changelog_template(ctime=now() - datetime.timedelta(hours=14))
        + cron_template(
            moniker="pending_changelog_remind",
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
        self.execute('subscription_request_remind')
        self.assertEqual(["subscription_request_remind"],
                         [mail.template for mail in self.mails])

    @prepsql(subscription_request_template(persona_id=3, mailinglist_id=4)
             + subscription_request_template(persona_id=5, mailinglist_id=4)
             + subscription_request_template(persona_id=2, mailinglist_id=7)
             + subscription_request_template(persona_id=3, mailinglist_id=8))
    def test_subscription_request_remind_multiple(self):
        self.execute('subscription_request_remind')
        self.assertEqual(["subscription_request_remind"] * 3,
                         [mail.template for mail in self.mails])

    @prepsql(cron_template(moniker="subscription_request_remind",
                           store={7: {'persona_ids': [6],
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
            moniker="privilege_change_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": [1]}))
    def test_privilege_change_remind_old(self):
        self.execute('privilege_change_remind')
        self.assertEqual([],
                         [mail.template for mail in self.mails])

    @prepsql(
        privilege_change_template(is_cde_admin=True,
                                  ctime=now() - datetime.timedelta(hours=6))
        + cron_template(
            moniker="privilege_change_remind",
            store={"tstamp": 1, "ids": [1]}))
    def test_privilege_change_remind_older(self):
        self.execute('privilege_change_remind')
        self.assertEqual(['privilege_change_remind'],
                         [mail.template for mail in self.mails])
