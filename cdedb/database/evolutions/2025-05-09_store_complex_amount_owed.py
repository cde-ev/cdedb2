#! /usr/bin/env python3

from cdedb.backend.event import EventBackend
from cdedb.script import Script

s = Script(dbuser='cdb')
rs = s.rs()

event_backend: EventBackend = s.make_backend("event", proxy=False)


with s:

    print("Adding new column to 'event.registrations' with default...")

    query = """
        ALTER TABLE event.registrations
            ADD COLUMN amount_owed_by_kind jsonb NOT NULL DEFAULT '{}'::jsonb
    """
    event_backend.query_exec(rs, query, ())

    print("Done. Recalculating amount owed for every registrations...")

    registrations_updated = 0
    events_updated = 0
    fee_stats_changed = []

    for event in event_backend.get_events(rs, event_backend.list_events(rs)).values():
        fee_stats_pre = fee_stats_post = None
        print()
        print(f"{event.title}{' (already balanced)' if event.is_balanced else ''}...", end="", flush=True)
        print("getting fee stats...", end="", flush=True)
        fee_stats_pre = event_backend.get_fee_stats(rs, event.id)
        print("done. Proceeding...", end="", flush=True)
        rowcount = event_backend._update_registrations_amount_owed(rs, event.id)
        registrations_updated += rowcount
        print(f"updated {rowcount} registrations.")
        print("Comparing fee stats...", end="", flush=True)
        fee_stats_post = event_backend.get_fee_stats(rs, event.id)
        if fee_stats_pre != fee_stats_post:
            print("stats differ!! This is a problem.")
            fee_stats_changed.append(event)
        else:
            print("done.")
        events_updated += 1

    print("\n" + "–" * 80 + "\n")
    print(f"Updated {registrations_updated} registrations of {events_updated} events.")
    if fee_stats_changed:
        print(f"This changed the fee stats of {len(fee_stats_changed)} events:")
        print(", ".join(event.title for event in fee_stats_changed))
