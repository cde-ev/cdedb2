#!/usr/bin/env python3
import collections
import datetime
import decimal
import pathlib
import re
import sys

import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObjectMap,
    json_serialize,
    make_persona_name,
    parse_date,
)
from cdedb.common.query.log_filter import CdELogFilter
from cdedb.filter import money_filter
from cdedb.script import Script

s = Script(dbuser="cdb_admin", check_system_user=False, dry_run=True)

core = s.make_core_backend()
cde = s.make_cde_backend()
event = s.make_event_backend()
event_raw = s.make_event_backend(proxy=False)

if len(sys.argv) <= 1:
    print("Please provide a year and optionally a filename for the export data.")
    sys.exit()

year = int(sys.argv[1])
outfile = pathlib.Path(
    sys.argv[2] if len(sys.argv) > 2 else pathlib.Path.cwd() / f"donations_{year}.json"
)

if outfile.exists():
    if input(f"{outfile.name!r} already exists, overwrite? (y/n) ").lower() != "y":
        sys.exit()

data: CdEDBObjectMap = {}

with s:
    rs = s.rs()
    events = event.get_events(rs, event.list_events(rs))

    # Heuristic for which events to consider. Can give a moderate speed up, but
    #  might not be correct in some rare cases.
    for event_ in list(events.values()):
        if event_.begin.year > year + 1 or event_.end.year < year - 1:
            # del events[event_.id]
            pass

    print(f"Found {len(events)} events.")

    # Determine period ids from the given year. (Does not work well with sample data.)
    log_filter = CdELogFilter(
        codes=[const.CdeLogCodes.semester_advance],
        ctime_from=datetime.datetime(year, 1, 1, tzinfo=datetime.UTC),
        ctime_to=datetime.datetime(year, 12, 31, 23, 59, 59, tzinfo=datetime.UTC),
    )
    periods = [int(e["change_note"]) for e in cde.retrieve_cde_log(rs, log_filter)[1]]
    print(f"Found periods: {periods}")

    if periods:
        print(f"Periods: {periods}")

        # Retrieve _all_ lastschrifts to not miss those cancelled later on.
        lastschrifts = cde.get_lastschrifts(rs, cde.list_lastschrift(rs, active=None))
        print(f"Found {len(lastschrifts)} lastschrifts.")
        transactions = cde.get_lastschrift_transactions(
            rs,
            cde.list_lastschrift_transactions(
                rs, stati=[const.LastschriftTransactionStati.success], periods=periods
            ),
        )
        print(
            f"Found {len(transactions)} successful transactions in the given periods."
        )
        for transaction in transactions.values():
            lastschrift = lastschrifts[transaction["lastschrift_id"]]
            persona_id = lastschrift["persona_id"]

            # Only consider the donation part, i.e. without the membership fee.
            data.setdefault(persona_id, {}).setdefault("lastschrift", []).append({
                "amount": transaction["amount"] - cde.annual_membership_fee(rs),
                "date": transaction["payment_date"],
                "verzicht": False,
            })
    else:
        print("No periods given.")

    for event_ in events.values():
        registrations = event.get_registrations(
            rs, event.list_registrations(rs, event_.id)
        )
        event_donations: dict[str, decimal.Decimal] = collections.defaultdict(
            decimal.Decimal
        )
        for reg in registrations.values():
            # Only consider fully paid registrations.
            if reg["amount_owed"] > reg["amount_paid"]:
                continue
            persona_id = reg["persona_id"]
            reg["persona"] = core.get_event_user(rs, persona_id)
            complex_fee = event_raw._calculate_complex_fee(rs, reg=reg, event=event_)
            for fee, amount in complex_fee.fees:
                if fee.kind.category != const.EventFeeCategory.donation:
                    continue
                # print(f"Found donation {fee.title} for {fee.event.shortname}.")

                # A instructor donation should always be a Verzicht.
                #  Otherwise check the notes.
                verzicht = (
                    bool(fee.notes and "Verzicht" in fee.notes)
                    or fee.kind == const.EventFeeType.instructor_donation
                )

                # Verzicht is always dated at the end of the event, everything else at
                #  payment.
                if verzicht:
                    donation_date = event_.end
                else:
                    donation_date = reg["payment"] or reg["ctime"].date()

                # In either case allow override via notes. (Especially relevant when
                #  crossing into another year.
                if fee.notes:
                    if m := re.search(r"Buchung: (\d{1,2}.\d{1,2}.\d{2,4})", fee.notes):
                        donation_date = parse_date(m[1])
                if donation_date.year != year:
                    # print("Wrong year.")
                    continue

                datum = {
                    "amount": amount,
                    "date": donation_date,
                    "verzicht": verzicht,
                    "notes": f"{fee.event.shortname}",
                }

                if fee.kind == const.EventFeeType.solidary_donation:
                    data.setdefault(persona_id, {}).setdefault("soli", []).append(datum)
                    event_donations["soli"] += amount
                elif fee.kind == const.EventFeeType.instructor_donation:
                    data.setdefault(persona_id, {}).setdefault("kl", []).append(datum)
                    event_donations["kl"] += amount
                else:
                    data.setdefault(persona_id, {}).setdefault("sonst", []).append(
                        datum
                    )
                    event_donations["sonst"] += amount
        if event_donations:
            print()
            print(f"{event_.shortname}:")
        for kind, amount in event_donations.items():
            print(f"{kind}: {money_filter(amount)}")

    result: CdEDBObjectMap = {}

    for persona_id, persona_donations in data.items():
        persona = core.get_event_user(rs, persona_id)
        g = rs.gettext
        persona_data = {
            "persona": {
                "name": persona.get_name(use_legal_name=True),
                "given_names": persona.given_names,
                "email": persona.username,
                "address": persona.address,
                "postal_code": persona.postal_code,
                "location": persona.location,
                "country": g(persona.country),
            }
        }

        all_groups = {}
        for kind, kind_data in persona_donations.items():
            grouped_data = {}
            for donation in kind_data:
                key = ";".join((
                    donation["date"].isoformat(),
                    str(donation["verzicht"]),
                    donation.get("notes", ""),
                ))
                if key not in grouped_data:
                    grouped_data[key] = 0
                grouped_data[key] += donation["amount"]
            all_groups[kind] = grouped_data

        if all_groups:
            result[persona_id] = {"persona": persona_data, "donations": all_groups}

    print()
    # from pprint import pprint
    # pprint([x["donations"] for x in result.values()])
    # pprint(data)
    print()

    totals = {
        "lastschrift": sum(
            amount
            for x in result.values()
            for amount in x["donations"].get("lastschrift", {}).values()
        ),
        "soli": sum(
            amount
            for x in result.values()
            for amount in x["donations"].get("soli", {}).values()
        ),
        "kl": sum(
            amount
            for x in result.values()
            for amount in x["donations"].get("kl", {}).values()
        ),
        "sonst": sum(
            amount
            for x in result.values()
            for amount in x["donations"].get("sonst", {}).values()
        ),
    }

    print()
    print("Totals:")
    print(f"{len(result)} donors.")
    for k, v in totals.items():
        print(f"{k}: {money_filter(v)}")

    outfile.write_text(json_serialize(result), encoding="utf-8")
    print(f"Wrote to {outfile.name!r}.")
