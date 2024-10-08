#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import collections.abc
import datetime
import decimal
import json
import numbers
import unittest.mock
from typing import Any, Union, cast

import freezegun

import cdedb.database.constants as const
from cdedb.common import CdEDBObject, RequestState, now
from cdedb.common.sorting import xsorted
from tests.common import CronTest, event_keeper, execsql, prepsql, storage

INSERT_TEMPLATE = """
INSERT INTO {table} ({columns}) VALUES ({values});
"""

# numbers.Number should include Decimal, int and bool but doesn't.
SQL_DATA = dict[str, Union[None, datetime.datetime, datetime.date, str, numbers.Number,
                           decimal.Decimal, int, bool, dict[str, Any]]]

RS = cast(RequestState, None)


def format_insert_sql(table: str, data: SQL_DATA) -> str:
    tmp = {}
    for key, value in data.items():
        if value is None:
            tmp[key] = "NULL"
        elif isinstance(value, datetime.datetime):
            tmp[key] = f"timestamptz '{value.isoformat()}'"
        elif isinstance(value, datetime.date):
            tmp[key] = f"date '{value.isoformat()}'"
        elif isinstance(value, str):
            tmp[key] = f"'{value}'"
        elif isinstance(value, numbers.Number):
            tmp[key] = f"{value}"
        elif isinstance(value, collections.abc.Mapping):
            tmp[key] = f"'{json.dumps(value)}'::jsonb"
        else:
            raise ValueError(f"Unknown datum {key} -> {value}")  # pragma: no cover
    keys = tuple(tmp)
    return INSERT_TEMPLATE.format(table=table, columns=", ".join(keys),
                                  values=", ".join(tmp[key] for key in keys))


def genesis_template(**kwargs: Any) -> str:
    defaults: SQL_DATA = {
        'ctime': now(),
        'realm': "event",
        # This seems like a mypy bug:
        'case_status': const.GenesisStati.to_review.value,
        'username': "zaphod@example.cde",
        'given_names': "Zaphod",
        'family_name': "Zappa",
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.genesis_cases", data)


def forget_finalized_genesis_template() -> str:
    ctime = now() - datetime.timedelta(days=89)
    status = const.GenesisStati
    successful = genesis_template(
        username="1@example.cde", case_status=status.successful, ctime=ctime)
    updated = genesis_template(
        username="2@example.cde", case_status=status.existing_updated, ctime=ctime)
    rejected = genesis_template(
        username="3@example.cde", case_status=status.rejected, ctime=ctime)
    return successful + updated + rejected


def changelog_template(**kwargs: Any) -> str:
    defaults: SQL_DATA = {
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
        'code': const.PersonaChangeStati.pending.value,
        'country': None,
        'country2': 'US',
        'ctime': now(),
        'decided_search': True,
        'display_name': 'Zelda',
        'family_name': 'Zeruda-Hime',
        'foto': 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbe'
                'c03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9',
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
        'is_purged': False,
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
        'weblink': 'https://www.uni.cde',
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.changelog", data)


def cron_template(**kwargs: Any) -> str:
    defaults: SQL_DATA = {
        'title': None,
        'store': {},
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("core.cron_store", data)


def subscription_request_template(**kwargs: Any) -> Any:
    defaults: SQL_DATA = {
        'subscription_state': const.SubscriptionState.pending,
    }
    data = {**defaults, **kwargs}
    return format_insert_sql("ml.subscription_states", data)


def privilege_change_template(**kwargs: Any) -> str:
    defaults: SQL_DATA = {
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
    def test_genesis_remind_empty(self) -> None:
        self.execute('genesis_remind')

    @prepsql(genesis_template(
        ctime=(now() - datetime.timedelta(hours=6))))
    def test_genesis_remind_new(self) -> None:
        self.execute('genesis_remind')
        self.assertEqual(["genesis/genesis_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql(genesis_template())
    def test_genesis_remind_newer(self) -> None:
        self.execute('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        genesis_template(ctime=(now() - datetime.timedelta(hours=6)))
        + cron_template(
            title="genesis_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": [1001]}))
    def test_genesis_remind_old(self) -> None:
        self.execute('genesis_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        genesis_template(ctime=(now() - datetime.timedelta(hours=6)))
        + cron_template(title="genesis_remind",
                        store={"tstamp": 1, "ids": [1001]}))
    def test_genesis_remind_older(self) -> None:
        self.execute('genesis_remind')
        self.assertEqual(["genesis/genesis_requests_pending"],
                         [mail.template for mail in self.mails])

    @storage
    def test_genesis_forget_empty(self) -> None:
        self.execute('genesis_forget')

    @storage
    @prepsql(genesis_template())
    def test_genesis_forget_unrelated(self) -> None:
        self.execute('genesis_forget')
        self.assertEqual({1, 2, 3, 4, 1001}, set(self.core.genesis_list_cases(RS)))

    @storage
    @prepsql(genesis_template(
        ctime=datetime.datetime(2000, 1, 1),
        case_status=const.GenesisStati.successful.value))
    def test_genesis_forget_successful(self) -> None:
        self.execute('genesis_forget')
        self.assertEqual({1, 2, 3, 4}, set(self.core.genesis_list_cases(RS)))

    @storage
    @prepsql(genesis_template(
        ctime=datetime.datetime(2000, 1, 1),
        case_status=const.GenesisStati.rejected.value))
    def test_genesis_forget_rejected(self) -> None:
        self.execute('genesis_forget')
        self.assertEqual({1, 2, 3, 4}, set(self.core.genesis_list_cases(RS)))

    @storage
    @prepsql(genesis_template(
        ctime=datetime.datetime(2000, 1, 1),
        case_status=const.GenesisStati.unconfirmed.value))
    def test_genesis_forget_unconfirmed(self) -> None:
        self.execute('genesis_forget')
        self.assertEqual({1, 2, 3, 4}, set(self.core.genesis_list_cases(RS)))

    @storage
    @prepsql(genesis_template(
        case_status=const.GenesisStati.unconfirmed.value))
    def test_genesis_forget_recent_unconfirmed(self) -> None:
        self.execute('genesis_forget')
        self.assertEqual({1, 2, 3, 4, 1001}, set(self.core.genesis_list_cases(RS)))

    @storage
    @prepsql(forget_finalized_genesis_template())
    def test_genesis_forget_finalized(self) -> None:
        """Do not forget finalized cases which are less than 90 days old."""
        self.execute('genesis_forget')
        self.assertEqual(
            {1, 2, 3, 4, 1001, 1002, 1003}, set(self.core.genesis_list_cases(RS)))

    def test_changelog_remind_empty(self) -> None:
        self.cron.execute(['pending_changelog_remind'])

    @prepsql(changelog_template(
        ctime=now() - datetime.timedelta(hours=14)))
    def test_changelog_remind_new(self) -> None:
        self.execute('pending_changelog_remind')
        self.assertEqual(["changelog_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql(changelog_template())
    def test_changelog_remind_newer(self) -> None:
        self.execute('pending_changelog_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        changelog_template(ctime=now() - datetime.timedelta(hours=14))
        + cron_template(
            title="pending_changelog_remind",
            store={"tstamp": (now() - datetime.timedelta(hours=1)).timestamp(),
                   "ids": ['2/2']}))
    def test_changelog_remind_old(self) -> None:
        self.execute('pending_changelog_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(
        changelog_template(ctime=now() - datetime.timedelta(hours=14))
        + cron_template(
            title="pending_changelog_remind",
            store={"tstamp": 1, "ids": ['2/2']}))
    def test_changelog_remind_older(self) -> None:
        self.execute('pending_changelog_remind')
        self.assertEqual(["changelog_requests_pending"],
                         [mail.template for mail in self.mails])

    @prepsql("DELETE FROM ml.subscription_states WHERE subscription_state = "
             f"{const.SubscriptionState.pending};")
    def test_subscription_request_remind_empty(self) -> None:
        self.execute('subscription_request_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    def test_subscription_request_remind_new(self) -> None:
        # Mailinglist 7 has pending subscription for persona 6
        # Mailinglist 54 for 2 and Mailinglist 56 for 7
        self.execute('subscription_request_remind')
        self.assertEqual(["subscription_request_remind"] * 3,
                         [mail.template for mail in self.mails])

    @prepsql(subscription_request_template(persona_id=9, mailinglist_id=4)
             + subscription_request_template(persona_id=27, mailinglist_id=4)
             + subscription_request_template(persona_id=2, mailinglist_id=7)
             + subscription_request_template(persona_id=3, mailinglist_id=8))
    def test_subscription_request_remind_multiple(self) -> None:
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
    def test_subscription_request_remind_old(self) -> None:
        self.execute('subscription_request_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    def test_privilege_change_remind_empty(self) -> None:
        self.execute('privilege_change_remind')
        self.assertEqual([], [mail.template for mail in self.mails])

    @prepsql(privilege_change_template(
        is_cde_admin=True, ctime=now() - datetime.timedelta(hours=6)))
    def test_privilege_change_remind_new(self) -> None:
        self.execute('privilege_change_remind')
        self.assertEqual(['privilege_change_remind'],
                         [mail.template for mail in self.mails])

    @prepsql(privilege_change_template(is_cde_admin=True))
    def test_privilege_change_remind_newer(self) -> None:
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
    def test_privilege_change_remind_old(self) -> None:
        self.execute('privilege_change_remind')
        self.assertEqual([],
                         [mail.template for mail in self.mails])

    @prepsql(
        privilege_change_template(is_cde_admin=True,
                                  ctime=now() - datetime.timedelta(hours=6))
        + cron_template(
            title="privilege_change_remind",
            store={"tstamp": 1, "ids": [1001]}))
    def test_privilege_change_remind_older(self) -> None:
        self.execute('privilege_change_remind')
        self.assertEqual(['privilege_change_remind'],
                         [mail.template for mail in self.mails])

    @prepsql("UPDATE cde.lastschrift SET revoked_at = now() WHERE id = 3")
    def test_forget_old_lastschrifts(self) -> None:
        name = "forget_old_lastschrifts"
        self.assertEqual(
            [1, 3], list(self.cde.list_lastschrift(RS, active=False)))
        self.execute(name)
        # Make sure only the old lastschrift is deleted.
        self.assertEqual(
            [3], list(self.cde.list_lastschrift(RS, active=False)),
        )
        self.assertEqual([1], self.core.get_cron_store(RS, name)["deleted"])
        self.execute(name)
        # Make sure nothing changes when the cron job runs again.
        self.assertEqual(
            [3], list(self.cde.list_lastschrift(RS, active=False)),
        )
        self.assertEqual([1], self.core.get_cron_store(RS, name)["deleted"])

    @storage
    def test_tally_ballots(self) -> None:
        ballot_ids: set[int] = set()
        for assembly_id in self.assembly.list_assemblies(RS):
            ballot_ids |= self.assembly.list_ballots(RS, assembly_id).keys()
        ballots = self.assembly.get_ballots(RS, ballot_ids)
        self.assertTrue(all(not b['is_tallied'] for b in ballots.values()))
        self.execute("check_tally_ballot")
        ballots = self.assembly.get_ballots(RS, ballot_ids)
        self.assertEqual(2, sum(1 for b in ballots.values() if b['is_tallied']))
        self.assertEqual(['ballot_tallied'] * 2,
                         [mail.template for mail in self.mails])

    def test_clean_session_log(self) -> None:
        # We just want to test that no exception is raised.
        self.execute('deactivate_old_sessions', 'clean_session_log')

    def test_validate_stored_event_queries(self) -> None:
        # We just want to test that no exception is raised.
        self.execute('validate_stored_event_queries')

    @event_keeper
    def test_event_keeper(self) -> None:
        # We just want to test that no exception is raised.
        self.execute('event_keeper')

    def test_mail_orgateam_reminders_none(self) -> None:
        cronjob = "mail_orgateam_reminders"
        self.execute(cronjob)
        self.assertEqual([], [mail.template for mail in self.mails])
        self.assertEqual(
            {"1": {}, "2": {}, "3": {}, "4": {}}, self.core.get_cron_store(RS, cronjob))

    # this part belongs to "Große Testakademie 2222"
    @prepsql("UPDATE event.event_parts"
             " SET (part_begin, part_end) = (CURRENT_DATE, CURRENT_DATE) WHERE id = 1")
    def test_mail_orgateam_reminders_halftime(self) -> None:
        cronjob = "mail_orgateam_reminders"
        self.execute(cronjob)
        self.assertEqual(["halftime_reminder"], [mail.template for mail in self.mails])
        self.assertEqual(
            {"1": {}, "2": {}, "3": {}, "4": {}}, self.core.get_cron_store(RS, cronjob))

    # this part is the only event part of the event "CdE-Party 2050"
    # we need to set an orga address to the event, otherwise no mails can be sent
    @prepsql("UPDATE event.event_parts"
             " SET (part_begin, part_end) = (date '2000-01-01', date '2000-01-01')"
             " WHERE id = 4;"
             " UPDATE event.events SET orga_address = 'party@example.cde' WHERE id = 2")
    def test_mail_orgateam_reminders_past(self) -> None:
        cronjob = "mail_orgateam_reminders"
        self.execute(cronjob)
        self.assertEqual(
            ["past_event_reminder"], [mail.template for mail in self.mails])
        self.assertEqual(
            {"1": {}, "2": {'did_past_event_reminder': True}, "3": {}, "4": {}},
            self.core.get_cron_store(RS, cronjob))

        # make sure that the past mail is sent only once
        self.mails = []
        self.execute(cronjob)
        self.assertEqual([], [mail.template for mail in self.mails])
        self.assertEqual(
            {"1": {}, "2": {'did_past_event_reminder': True}, "3": {}, "4": {}},
            self.core.get_cron_store(RS, cronjob))

    @prepsql(f"UPDATE event.events SET notify_on_registration ="
             f" {const.NotifyOnRegistration.hourly.value}")
    def test_notify_on_registration(self) -> None:
        cronjob = "notify_on_registration"

        base_time = now().replace(microsecond=0) + datetime.timedelta(seconds=5)
        delta = datetime.timedelta(minutes=5)
        with freezegun.freeze_time(base_time) as frozen_time:

            self.execute(cronjob)
            mail_expectation = ["notify_on_registration"]
            store_expectation: CdEDBObject = {
                'period': 0,
                'timestamps': {
                    "1": now().isoformat(),
                    "2": now().isoformat(),
                    "3": now().isoformat(),
                    "4": now().isoformat(),
                },
            }
            self.assertEqual(
                mail_expectation,
                [mail.template for mail in self.mails],
            )
            self.assertEqual(
                store_expectation,
                self.core.get_cron_store(RS, cronjob),
            )

            frozen_time.tick(delta * 2)

            execsql(f"UPDATE event.log SET ctime = '{base_time + delta}'")

            for _ in range(const.NotifyOnRegistration.hourly - 1):
                self.execute(cronjob)
                self.assertEqual(
                    mail_expectation,
                    [mail.template for mail in self.mails],
                )
                store_expectation['period'] += 1
                self.assertEqual(
                    store_expectation,
                    self.core.get_cron_store(RS, cronjob),
                )

                frozen_time.tick(delta)

            self.execute(cronjob)

            mail_expectation *= 2
            store_expectation['period'] += 1
            self.assertEqual(
                mail_expectation,
                [mail.template for mail in self.mails],
            )
            self.assertNotEqual(
                store_expectation,
                self.core.get_cron_store(RS, cronjob),
            )
            store_expectation = {
                'period': 4,
                'timestamps': {
                    "1": now().isoformat(),
                    "2": now().isoformat(),
                    "3": now().isoformat(),
                    "4": now().isoformat(),
                },
            }
            self.assertEqual(
                store_expectation,
                self.core.get_cron_store(RS, cronjob),
            )

    @storage
    def test_forget_assembly_attachments(self) -> None:
        self.execute('forget_assembly_attachments')
        self.assertTrue(self.assembly.get_attachment_store(RS).is_available(
            self.get_sample_datum(
                'assembly.attachment_versions', 4)['file_hash']))
        execsql("UPDATE assembly.attachment_versions SET dtime = now() WHERE id = 4")
        self.execute('forget_assembly_attachments')
        self.assertFalse(self.assembly.get_attachment_store(RS).is_available(
            self.get_sample_datum(
                'assembly.attachment_versions', 4)['file_hash']))
        versions = self.get_sample_data('assembly.attachment_versions')
        for version in versions.values():
            if version['dtime'] is None and version['id'] != 4:
                self.assertTrue(self.assembly.get_attachment_store(RS).is_available(
                    version['file_hash']))

    @storage
    def test_forget_fotos(self) -> None:
        # We just want to test that no exception is raised.
        self.execute('forget_profile_fotos')

    @storage
    @unittest.mock.patch("cdedb.frontend.common.CdEMailmanClient")
    def test_mailman_sync(self, client_class: unittest.mock.Mock) -> None:
        #
        # Prepare
        #

        class SaveDict(dict[Any, Any]):
            def save(self) -> None:
                pass

        # Commented items will be available in mailman 3.3
        base_settings = {
            'send_welcome_message': False,
            'send_goodbye_message': False,
            'subscription_policy': 'moderate',
            'unsubscription_policy': 'moderate',
            'archive_policy': 'private',
            'digests_enabled': False,
            'filter_content': True,
            'filter_action': 'reject',
            'pass_extensions': ['pdf'],
            'pass_types': ['multipart', 'text/plain', 'application/pdf'],
            'convert_html_to_plaintext': True,
            'collapse_alternatives': True,
            'dmarc_mitigate_action': 'munge_from',
            'dmarc_mitigate_unconditionally': False,
            # 'dmarc_wrapped_message_text': 'Nachricht wegen DMARC eingepackt.',
            'administrivia': True,
            'member_roster_visibility': 'moderators',
            'advertised': True,
            'max_num_recipients': 0,
            'acceptable_aliases': {"cde-ev.de", "lists.schuelerakademie.de"},
            'require_explicit_destination': True,
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
            'moderatoren': unittest.mock.MagicMock(),
            'everyone': unittest.mock.MagicMock(),
            'lokalgruppen': unittest.mock.MagicMock(),
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
            'gu': unittest.mock.MagicMock(),
            'whz': unittest.mock.MagicMock(),
            'whzmfz': unittest.mock.MagicMock(),
            'migration': unittest.mock.MagicMock(),
        }

        client = client_class.return_value
        client.lists = [mm_lists['announce'], mm_lists['witz'],
                        mm_lists['zombie']]
        client.get_domain.return_value.create_list.side_effect = mm_lists.get
        mm_lists['witz'].members = [
            unittest.mock.MagicMock(email='janis-spam@example.cde'),
            unittest.mock.MagicMock(email='undead@example.cde')]

        #
        # Run
        #
        self.execute('sync_subscriptions')

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
                          umcall('kongress-leitung'),
                          umcall('participants'),
                          umcall('party50-all'),
                          umcall('party50'),
                          umcall('info'),
                          umcall('mitgestaltung'),
                          umcall('moderatoren'),
                          umcall('everyone'),
                          umcall('lokalgruppen'),
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
                          umcall('gu'),
                          umcall('whz'),
                          umcall('whzmfz'),
                          umcall('migration'),
                          ])))
        # Meta update
        expectation = {
            'advertised': True,
            'default_member_action': 'defer',
            'default_nonmember_action': 'hold',
            'display_name': 'Witz des Tages',
            'info': 'Einer geht noch ...',
            'max_message_size': 2048,
            'subject_prefix': '[witz] ',
        }
        for key, value in expectation.items():
            self.assertEqual(mm_lists['witz'].settings[key], value)
        self.assertEqual(mm_lists['werbung'].set_template.call_count, 3)
        # Subscriber update
        self.assertEqual(
            mm_lists['witz'].subscribe.call_args_list,
            [umcall('new-anton@example.cde',
                    display_name='Anton Administrator',
                    pre_approved=True, pre_confirmed=True, pre_verified=True)])
        self.assertEqual(
            mm_lists['witz'].unsubscribe.call_args_list,
            [umcall('undead@example.cde', pre_confirmed=True, pre_approved=True)])
        self.assertEqual(mm_lists['klatsch'].subscribe.call_count, 3)
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

    @storage
    @prepsql("DELETE FROM core.email_states")
    @unittest.mock.patch("cdedb.frontend.common.CdEMailmanClient")
    def test_defect_email_mailman(self, client_class: unittest.mock.Mock) -> None:
        #
        # Prepare
        #
        mm_lists = {
            'zombie': unittest.mock.MagicMock(),
            'announce': unittest.mock.MagicMock(),
            'witz': unittest.mock.MagicMock(),
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
            'moderatoren': unittest.mock.MagicMock(),
            'everyone': unittest.mock.MagicMock(),
            'lokalgruppen': unittest.mock.MagicMock(),
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
            'gu': unittest.mock.MagicMock(),
            'whz': unittest.mock.MagicMock(),
            'whzmfz': unittest.mock.MagicMock(),
            'migration': unittest.mock.MagicMock(),
        }

        client = client_class.return_value
        client.get_domain.return_value.create_list.side_effect = mm_lists.get

        #
        # Run
        #
        self.execute('sync_subscriptions')

        #
        # Check
        #
        self.assertEqual(mm_lists['klatsch'].subscribe.call_count, 4)
