#!/usr/bin/env python3

import collections.abc
import datetime
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


def cron_template(**kwargs):
    defaults = {
        'moniker': None,
        'store': {}
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.cron_store", data)


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
