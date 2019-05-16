#!/usr/bin/env python3

import datetime
import unittest
import unittest.mock

import cdedb.database.constants as const
import cdedb.common as now

from test.common import CronTest, prepsql

GENESIS_TEMPLATE = """
INSERT INTO core.genesis_cases
(ctime, username, given_names, family_name, realm, case_status) VALUES
(timestamptz '{timestamp}', '{username}', '{given_names}', '{family_name}', 
{realm}, {state});
"""

def genesis_template(
        timestamp, realm="event", state=const.GenesisStati.to_review,
        username="zaphod@example.cde", given_names="Zaphod",
        family_name="Zappa"):
    realm = "'{}'".format(realm) if realm else "NULL"
    state = state.value
    return GENESIS_TEMPLATE.format(
        timestamp=timestamp, realm=realm, state=state, username=username,
        given_names=given_names, family_name=family_name)

CRON_TEMPLATE = """
INSERT INTO core.cron_store
(moniker, store) VALUES
('{moniker}', '{data}'::jsonb);
"""

def cron_template(moniker, data):
    return CRON_TEMPLATE.format(moniker=moniker, data=data)

class TestCron(CronTest):
    def test_genesis_remind_empty(self):
        self.cron.execute(['genesis_remind'])

    @prepsql(genesis_template(
        (now() - datetime.timedelta(hours=6)).isoformat()))
    def test_genesis_remind_new(self):
        self.run('genesis_remind')
        self.assertEqual(["genesis_request"],
                         [mail.template for mail in self.mails])
        
    @prepsql(genesis_template(now().isoformat()))
    def test_genesis_remind_newer(self):
        self.run('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])
        
    @prepsql(
        genesis_template((now() - datetime.timedelta(hours=6)).isoformat())
        + cron_template(
            "genesis_remind", '{{"tstamp": {}, "ids": [1]}}'.format(
                (now() - datetime.timedelta(hours=1)).timestamp())))
    def test_genesis_remind_old(self):
        self.run('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])
        
    @prepsql(
        genesis_template((now() - datetime.timedelta(hours=6)).isoformat())
        + cron_template("genesis_remind", '{"tstamp": 1, "ids": [1]}'))
    def test_genesis_remind_older(self):
        self.run('genesis_remind')
        self.assertEqual(["genesis_request"],
                         [mail.template for mail in self.mails])
        
