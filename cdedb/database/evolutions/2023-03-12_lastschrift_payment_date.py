#!/usr/bin/env python3

import datetime

import dateutil.easter

from cdedb.backend.core import CoreBackend
from cdedb.script import Script

s = Script(dbuser='cdb')

core: CoreBackend = s.make_backend("core", proxy=False)


def calculate_payment_date(issued_at: datetime.datetime) -> datetime.date:
    """Helper to calculate a payment date that is a valid TARGET2 bankday."""
    payment_date = issued_at.date() + s.config["SEPA_PAYMENT_OFFSET"]

    # Before anything else: check whether we are on special easter days.
    easter = dateutil.easter.easter(payment_date.year)
    good_friday = easter - datetime.timedelta(days=2)
    easter_monday = easter + datetime.timedelta(days=1)
    if payment_date in (good_friday, easter_monday):
        payment_date = easter + datetime.timedelta(days=2)

    # First: check we are not on the weekend.
    if payment_date.isoweekday() == 6:
        payment_date += datetime.timedelta(days=2)
    elif payment_date.isoweekday() == 7:
        payment_date += datetime.timedelta(days=1)

    # Second: check we are not on some special day.
    if payment_date.day == 1 and payment_date.month in (1, 5):
        payment_date += datetime.timedelta(days=1)
    elif payment_date.month == 12 and payment_date.day == 25:
        payment_date += datetime.timedelta(days=2)
    elif payment_date.month == 12 and payment_date.day == 26:
        payment_date += datetime.timedelta(days=1)

    # Third: check whether the second step landed us on the weekend.
    if payment_date.isoweekday() == 6:
        payment_date += datetime.timedelta(days=2)
    elif payment_date.isoweekday() == 7:
        payment_date += datetime.timedelta(days=1)

    return payment_date


with s:
    # Add new column.
    query = """
        ALTER TABLE cde.lastschrift_transactions
        ADD COLUMN payment_date date DEFAULT NULL;
    """
    core.query_exec(s.rs(), query, ())
    print("Added new column.")

    # SELECT all existing transactions
    query = "SELECT id, issued_at FROM cde.lastschrift_transactions;"
    print("Set the payment date for all existing transactions.", end="", flush=True)
    entries = core.query_all(s.rs(), query, ())

    # Set the payment date for all existing transactions.
    step = (len(entries) // 10) if len(entries) > 20 else 1
    for i, e in enumerate(entries):
        data = {
            'id': e['id'],
            'payment_date': calculate_payment_date(e['issued_at']),
        }
        core.sql_update(s.rs(), "cde.lastschrift_transactions", data)

        if i % step == 0:
            print(".", end="", flush=True)
    print()
