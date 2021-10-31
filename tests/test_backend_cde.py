#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import decimal

import pytz

import cdedb.database.constants as const
from cdedb.common import (
    PERSONA_CDE_FIELDS, PERSONA_CORE_FIELDS, PERSONA_EVENT_FIELDS, CdEDBLog,
    QuotaException,
)
from cdedb.query import Query, QueryOperators, QueryScope
from tests.common import USER_DICT, BackendTest, as_users, nearly_now


class TestCdEBackend(BackendTest):
    used_backends = ("core", "cde")

    @as_users("berta", "vera")
    def test_basics(self) -> None:
        data = self.core.get_cde_user(self.key, self.user['id'])
        data['display_name'] = "Zelda"
        setter = {k: v for k, v in data.items() if k in
                  {'id', 'display_name', 'telephone'}}
        generation = self.core.changelog_get_generation(self.key, self.user['id'])
        num = self.core.change_persona(self.key, setter, generation, change_note='note')
        self.assertEqual(1, num)
        new_data = self.core.get_cde_user(self.key, self.user['id'])
        self.assertEqual(data, new_data)

    @as_users("berta")
    def test_quota(self) -> None:
        self.assertEqual(0, self.core.quota(self.key))
        # Do two quotable accesses per loop, a number of times equal to half the limit.
        for i in range(1, self.conf["QUOTA_VIEWS_PER_DAY"]//2 + 1):
            if i % 3 == 0:
                self.assertEqual(i*2, self.core.quota(self.key, ids=(1, 2, 6)))
                self.assertEqual(i*2, self.core.quota(self.key, ids=(1, 2, 6)))
            elif i % 3 == 1:
                self.assertEqual(i*2, self.core.quota(self.key, ids=(3, 4)))
                self.assertEqual(i*2, self.core.quota(self.key, ids=(3, 4)))
            else:
                self.assertEqual(i*2, self.core.quota(self.key, num=2))
        self.core.get_cde_users(self.key, (1, 2, 6))
        with self.assertRaises(QuotaException):
            self.core.get_cde_users(self.key, (3, 4))
        # The missing 2 does not create a new kind of access as it's Berta's
        # ID and not counted in general.
        self.core.get_cde_users(self.key, (1, 6))

        query = Query(scope=QueryScope.cde_member,
                      spec=QueryScope.cde_member.get_spec(),
                      fields_of_interest=["id"], constraints=[], order=[])
        with self.assertRaises(QuotaException):
            self.cde.submit_general_query(self.key, query)

    def test_displacement(self) -> None:
        user = USER_DICT["berta"]
        self.login(user)
        data = {'id': self.user['id'], 'family_name': "Link"}
        self.assertEqual(-1, self.core.change_persona(self.key, data, generation=1))
        newaddress = "newaddress@example.cde"
        ret, _ = self.core.change_username(
            self.key, self.user['id'], newaddress, self.user['password'])
        self.assertTrue(ret)
        self.logout()
        self.assertTrue(self.user_in("anonymous"))
        self.login(user)
        self.assertTrue(self.user_in("anonymous"))
        newuser = dict(user)
        newuser['username'] = newaddress
        self.login(newuser)
        self.assertTrue(self.user_in(newuser))
        data = self.core.get_cde_user(self.key, newuser['id'])
        self.assertEqual(self.user['family_name'], data['family_name'])
        self.logout()
        self.login("vera")
        self.core.changelog_resolve_change(self.key, newuser['id'], 4, ack=True)
        data = self.core.get_cde_user(self.key, newuser['id'],)
        self.assertEqual("Link", data['family_name'])

    @as_users("berta")
    def test_nack_change(self) -> None:
        user = self.user
        self.assertEqual(
            -1, self.core.change_persona(self.key, {'id': user['id'],
                                                    'family_name': "Link"}, 1))
        self.assertEqual(2, self.core.changelog_get_generation(self.key, user['id']))
        self.core.logout(self.key)
        self.login('vera')
        self.core.changelog_resolve_change(self.key, user['id'], 2, ack=False)
        self.assertEqual(1, self.core.changelog_get_generation(self.key, user['id']))

    @as_users("berta", "vera")
    def test_get_cde_users(self) -> None:
        data = self.core.get_cde_users(self.key, (1, 2))
        expectation = self.get_sample_data(
            'core.personas', (1, 2), PERSONA_CDE_FIELDS)

        self.assertEqual(expectation, data)
        if self.user_in(22):
            data = self.core.get_event_users(self.key, (1, 2))
            expectation = self.get_sample_data(
                'core.personas', (1, 2), PERSONA_EVENT_FIELDS)
            self.assertEqual(expectation, data)
        data = self.core.get_personas(self.key, (1, 2))
        expectation = self.get_sample_data(
            'core.personas', (1, 2), PERSONA_CORE_FIELDS)
        self.assertEqual(expectation, data)

    @as_users("berta")
    def test_member_search(self) -> None:
        query = Query(
            scope=QueryScope.cde_member,
            spec=QueryScope.cde_member.get_spec(),
            fields_of_interest=("personas.id", "family_name", "birthday"),
            constraints=[
                ("given_names,display_name", QueryOperators.regex, '[ae]'),
                ("country,country2", QueryOperators.empty, None)],
            order=(("family_name,birth_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        expectation = {6, 9, 15, 100}
        self.assertEqual({e['id'] for e in result}, expectation)

    @as_users("vera")
    def test_user_search(self) -> None:
        query = Query(
            scope=QueryScope.cde_user,
            spec=QueryScope.cde_user.get_spec(),
            fields_of_interest=("personas.id", "family_name", "birthday"),
            constraints=[
                ("given_names", QueryOperators.regex, '[ae]'),
                ("birthday", QueryOperators.less, datetime.datetime.now())],
            order=(("family_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2, 3, 4, 6, 7, 13, 15, 16, 22, 23, 27, 32, 37, 100},
                         {e['id'] for e in result})

    @as_users("vera")
    def test_user_search_operators(self) -> None:
        query = Query(
            scope=QueryScope.cde_user,
            spec=QueryScope.cde_user.get_spec(),
            fields_of_interest=("personas.id", "family_name",
                                "birthday"),
            constraints=[
                ("given_names", QueryOperators.match, 'Berta'),
                ("address", QueryOperators.oneof, ("Auf der Düne 42", "Im Garten 77")),
                ("weblink", QueryOperators.containsall, ("/", ":", "http")),
                ("birthday", QueryOperators.between, (datetime.datetime(1000, 1, 1),
                                                      datetime.datetime.now()))],
            order=(("family_name", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual({2}, {e['id'] for e in result})

    @as_users("vera")
    def test_user_search_collation(self) -> None:
        query = Query(
            scope=QueryScope.cde_user,
            spec=QueryScope.cde_user.get_spec(),
            fields_of_interest=("personas.id", "family_name",
                                "address", "location"),
            constraints=[("location", QueryOperators.match, 'Musterstadt')],
            order=(("address", True),),)
        result = self.cde.submit_general_query(self.key, query)
        self.assertEqual([1, 27], [e['id'] for e in result])

    @as_users("vera")
    def test_demotion(self) -> None:
        self.assertLess(0, self.cde.change_membership(self.key, 2, False)[0])

    @as_users("farin")
    def test_lastschrift(self) -> None:
        expectation = {2: 2}
        self.assertEqual(expectation, self.cde.list_lastschrift(self.key))
        expectation = {1: 2, 2: 2}
        self.assertEqual(expectation, self.cde.list_lastschrift(self.key,
                                                                active=None))
        self.assertEqual({1: 2}, self.cde.list_lastschrift(self.key, active=False))
        expectation = {
            2: {
                'account_address': 'Im Geldspeicher 1',
                'account_owner': 'Dagobert Anatidae',
                'amount': decimal.Decimal('42.23'),
                'granted_at': datetime.datetime(2002, 2, 22, 20, 22, 22, 222222,
                                                tzinfo=pytz.utc),
                'iban': 'DE12500105170648489890',
                'id': 2,
                'notes': 'reicher Onkel',
                'persona_id': 2,
                'revoked_at': None,
                'submitted_by': 1,
            },
        }
        self.assertEqual(expectation, self.cde.get_lastschrifts(self.key, (2,)))
        update = {
            'id': 2,
            'notes': 'ehem. reicher Onkel',
            'revoked_at': datetime.datetime.now(pytz.utc),
        }
        self.assertLess(0, self.cde.set_lastschrift(self.key, update))
        expectation[2].update(update)
        self.assertEqual(expectation, self.cde.get_lastschrifts(self.key, (2,)))
        self.assertEqual({}, self.cde.list_lastschrift(self.key))
        self.assertEqual(
            {1: 2, 2: 2}, self.cde.list_lastschrift(self.key, active=False))
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'notes': None,
            'persona_id': 3,
        }
        new_id = self.cde.create_lastschrift(self.key, newdata)
        self.assertLess(0, new_id)
        self.assertEqual({new_id: 3}, self.cde.list_lastschrift(self.key))
        newdata.update({
            'id': new_id,
            'revoked_at': None,
            'submitted_by': self.user['id'],
        })
        self.assertEqual({new_id: newdata},
                         self.cde.get_lastschrifts(self.key, (new_id,)))
        self.assertEqual(
            ["revoked_at", "transactions"],
            list(self.cde.delete_lastschrift_blockers(self.key, 2)))

        transaction_data = {
            "lastschrift_id": new_id,
            "period_id": self.cde.current_period(self.key),
        }
        transaction_id = self.cde.issue_lastschrift_transaction(
            self.key, transaction_data, check_unique=True)
        self.assertEqual(
            ["revoked_at", "transactions", "active_transactions"],
            list(self.cde.delete_lastschrift_blockers(self.key, new_id)))
        with self.assertRaises(ValueError):
            self.cde.delete_lastschrift(
                self.key, new_id, ["transactions", "active_transactions"])
        self.cde.finalize_lastschrift_transaction(
            self.key, transaction_id, const.LastschriftTransactionStati.success)
        self.assertEqual(
            ["revoked_at", "transactions"],
            list(self.cde.delete_lastschrift_blockers(self.key, new_id)))

        self.assertEqual(
            ["transactions"],
            list(self.cde.delete_lastschrift_blockers(self.key, 1)))
        self.assertLess(
            0, self.cde.delete_lastschrift(self.key, 1, ["transactions"]))

    @as_users("farin")
    def test_lastschrift_multiple_active(self) -> None:
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'notes': None,
            'persona_id': 3,
        }
        self.cde.create_lastschrift(self.key, newdata)
        with self.assertRaises(ValueError):
            self.cde.create_lastschrift(self.key, newdata)

    @as_users("farin")
    def test_lastschrift_transaction(self) -> None:
        expectation = {1: 1, 2: 1, 3: 2}
        self.assertEqual(expectation,
                         self.cde.list_lastschrift_transactions(self.key))
        expectation = {1: 1, 3: 2}
        self.assertEqual(
            expectation, self.cde.list_lastschrift_transactions(
                self.key, lastschrift_ids=(1, 2), periods=(41,),
                stati=(const.LastschriftTransactionStati.success,
                       const.LastschriftTransactionStati.cancelled,)))
        expectation = {
            1: {
                'amount': decimal.Decimal('32.00'),
                'id': 1,
                'issued_at': datetime.datetime(2000, 3, 21, 22, 0, tzinfo=pytz.utc),
                'lastschrift_id': 1,
                'period_id': 41,
                'processed_at': datetime.datetime(2012, 3, 22, 20, 22, 22, 222222,
                                                  tzinfo=pytz.utc),
                'status': 12,
                'submitted_by': 1,
                'tally': decimal.Decimal('0.00'),
            },
        }
        self.assertEqual(expectation,
                         self.cde.get_lastschrift_transactions(self.key, (1,)))
        newdata = {
            'issued_at': datetime.datetime.now(pytz.utc),
            'lastschrift_id': 2,
            'period_id': 43,
        }
        new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
        self.assertLess(0, new_id)
        update = {
            'id': new_id,
            'amount': decimal.Decimal('42.23'),
            'processed_at': None,
            'status': 1,
            'submitted_by': self.user['id'],
            'tally': None,
        }
        newdata.update(update)
        self.assertEqual({new_id: newdata},
                         self.cde.get_lastschrift_transactions(self.key, (new_id,)))

    @as_users("farin")
    def test_lastschrift_transaction_finalization(self) -> None:
        ltstati = const.LastschriftTransactionStati
        for status, tally in ((ltstati.success, None),
                              (ltstati.cancelled, None),
                              (ltstati.failure, decimal.Decimal("-4.50"))):
            with self.subTest(status=status):
                newdata = {
                    'issued_at': datetime.datetime.now(pytz.utc),
                    'lastschrift_id': 2,
                    'period_id': 43,
                }
                new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
                self.assertLess(0, new_id)
                update = {
                    'id': new_id,
                    'amount': decimal.Decimal('42.23'),
                    'processed_at': None,
                    'status': 1,
                    'submitted_by': self.user['id'],
                    'tally': None,
                }
                newdata.update(update)
                self.assertEqual(
                    {new_id: newdata}, self.cde.get_lastschrift_transactions(
                        self.key, (new_id,)))
                self.assertLess(
                    0, self.cde.finalize_lastschrift_transaction(
                        self.key, new_id, status, tally=tally))
                data = self.cde.get_lastschrift_transactions(self.key, (new_id,))
                data = data[new_id]
                self.assertEqual(status, data['status'])
                if status == ltstati.success:
                    self.assertEqual(decimal.Decimal('42.23'), data['tally'])
                elif status == ltstati.cancelled:
                    self.assertEqual(decimal.Decimal('0'), data['tally'])
                elif status == ltstati.failure:
                    self.assertEqual(decimal.Decimal('-4.50'), data['tally'])

    @as_users("farin")
    def test_lastschrift_transaction_rollback(self) -> None:
        ltstati = const.LastschriftTransactionStati
        newdata = {
            'issued_at': datetime.datetime.now(pytz.utc),
            'lastschrift_id': 2,
            'period_id': 43,
        }
        new_id = self.cde.issue_lastschrift_transaction(self.key, newdata)
        self.assertLess(0, new_id)
        update = {
            'id': new_id,
            'amount': decimal.Decimal('42.23'),
            'processed_at': None,
            'status': 1,
            'submitted_by': self.user['id'],
            'tally': None,
        }
        newdata.update(update)
        self.assertEqual(
            {new_id: newdata}, self.cde.get_lastschrift_transactions(
                self.key, (new_id,)))
        self.assertLess(
            0, self.cde.finalize_lastschrift_transaction(
                self.key, new_id, ltstati.success))
        self.assertLess(
            0, self.cde.rollback_lastschrift_transaction(
                self.key, new_id, decimal.Decimal('-4.50')))
        data = self.cde.get_lastschrift_transactions(self.key, (new_id,))
        data = data[new_id]
        self.assertEqual(ltstati.rollback, data['status'])
        self.assertEqual(decimal.Decimal('-4.50'), data['tally'])

    @as_users("farin")
    def test_skip_lastschrift_transaction(self) -> None:
        # Skip testing for successful transaction
        self.assertLess(0, self.cde.lastschrift_skip(self.key, 2))
        # Skip testing for young permit
        newdata = {
            'account_address': None,
            'account_owner': None,
            'amount': decimal.Decimal('25.00'),
            'granted_at': datetime.datetime.now(pytz.utc),
            'iban': 'DE69370205000008068902',
            'notes': None,
            'persona_id': 3,
        }
        new_id = self.cde.create_lastschrift(self.key, newdata)
        self.assertLess(0, new_id)
        self.assertLess(0, self.cde.lastschrift_skip(self.key, new_id))

    @as_users("anton", "farin")
    def test_semester(self) -> None:
        period_id = self.cde.current_period(self.key)
        period = self.cde.get_period(self.key, period_id)
        for k, v in period.items():
            if k == "id":
                self.assertEqual(v, period_id)
            elif k == "semester_start":
                self.assertEqual(v, nearly_now())
            else:
                self.assertFalse(v)

        self.assertTrue(self.cde.may_start_semester_bill(self.key))
        self.assertFalse(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

        if self.user_in("anton"):
            self.cde.finish_semester_bill(self.key)
        elif self.user_in("farin"):
            self.cde.finish_archival_notification(self.key)
        else:
            self.fail("Invalid user configuration for this test.")
        self.assertTrue(self.cde.may_start_semester_bill(self.key))
        self.assertFalse(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

        if self.user_in("anton"):
            self.cde.finish_archival_notification(self.key)
        elif self.user_in("farin"):
            self.cde.finish_semester_bill(self.key)
        self.assertFalse(self.cde.may_start_semester_bill(self.key))
        self.assertTrue(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

        if self.user_in("anton"):
            self.cde.finish_semester_ejection(self.key)
        elif self.user_in("farin"):
            self.cde.finish_automated_archival(self.key)
        self.assertFalse(self.cde.may_start_semester_bill(self.key))
        self.assertTrue(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

        if self.user_in("anton"):
            self.cde.finish_automated_archival(self.key)
        elif self.user_in("farin"):
            self.cde.finish_semester_ejection(self.key)
        self.assertFalse(self.cde.may_start_semester_bill(self.key))
        self.assertFalse(self.cde.may_start_semester_ejection(self.key))
        self.assertTrue(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

        self.cde.finish_semester_balance_update(self.key)
        self.assertFalse(self.cde.may_start_semester_bill(self.key))
        self.assertFalse(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertTrue(self.cde.may_advance_semester(self.key))

        self.cde.advance_semester(self.key)
        self.assertTrue(self.cde.may_start_semester_bill(self.key))
        self.assertFalse(self.cde.may_start_semester_ejection(self.key))
        self.assertFalse(self.cde.may_start_semester_balance_update(self.key))
        self.assertFalse(self.cde.may_advance_semester(self.key))

    @as_users("vera")
    def test_cde_log(self) -> None:
        # first generate some data
        # TODO more when available

        # now check it
        expectation: CdEDBLog = (0, tuple())
        self.assertEqual(expectation, self.cde.retrieve_cde_log(self.key))
