#!/usr/bin/env python3
from cdedb.backend.event import EventBackend
from cdedb.common import unwrap
from cdedb.script import Script, make_proxy

s = Script(dbuser='cdb')

event: EventBackend = s.make_backend('event', proxy=False)

with s:
    no_ctime = no_is_member = success = 0

    q = """
        ALTER TABLE event.registrations ADD COLUMN is_member boolean DEFAULT FALSE;
    """
    event.query_exec(s.rs(), q, ())

    q = """SELECT id FROM event.registrations"""
    for registration_id in map(unwrap, event.query_all(s.rs(), q, ())):
        registration = event.get_registration(s.rs(), registration_id)

        persona_id = registration['persona_id']
        ctime = registration['ctime']

        if not ctime:
            no_ctime += 1
            print(f"No registration time found for registration {registration_id} (persona {persona_id}).")
            continue

        q = """
            SELECT is_member FROM core.changelog
            WHERE persona_id = %s and ctime <= %s
            ORDER BY ctime DESC LIMIT 1
        """
        data = event.query_one(s.rs(), q, (persona_id, ctime))
        if data:
            update = {
                'id': registration_id,
                'is_member': data['is_member'],
            }
            event.sql_update(s.rs(), "event.registrations", update)

            success += 1
            print(f"Updated registration {registration_id} (persona {persona_id}) with historical member status (is_member={data['is_member']}).")
        else:
            no_is_member += 1
            print(f"No historical member status found for registration {registration_id} (persona {persona_id}).")

    q = """
        ALTER TABLE event.registrations ALTER COLUMN is_member DROP DEFAULT;
        ALTER TABLE event.registrations ALTER COLUMN is_member SET NOT NULL;
    """
    event.query_exec(s.rs(), q, ())

    print()
    print('-' * 20)
    print()
    if no_ctime:
        print(f"No registration time found for {no_ctime} registrations.")
    if no_is_member:
        print(f"No membership status found for {no_is_member} registrations.")
    print(f"{success} registrations were updated successfully.")
