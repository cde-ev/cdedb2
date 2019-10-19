#!/usr/bin/env python3

import sys

sys.path.insert(0, "/cdedb2/")
from cdedb.script import setup, make_backend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
from cdedb.common import ProxyShim
# Configuration

rs = setup(persona_id=-1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")

# prepare backends

ml = make_backend("ml")
mlproxy = ProxyShim(make_backend("ml"))

# Start of actual script.

DEFAULT_ID = 1

with Atomizer(rs(DEFAULT_ID)):
    query = ("ALTER TABLE ml.subscription_states "
             "ADD COLUMN subscription_state integer")

    ml.query_exec(rs(DEFAULT_ID), query, tuple())

    query = ("UPDATE ml.subscription_states SET subscription_state = %s"
             "WHERE is_subscribed = %s AND is_override = %s")

    # This covers every possible case, because both these bools cannot be NULL.
    ml.query_exec(rs(DEFAULT_ID), query, (const.SubscriptionStates.subscribed, True, False))
    ml.query_exec(rs(DEFAULT_ID), query, (const.SubscriptionStates.unsubscribed, False, False))
    ml.query_exec(rs(DEFAULT_ID), query, (const.SubscriptionStates.mod_subscribed, True, True))
    ml.query_exec(rs(DEFAULT_ID), query, (const.SubscriptionStates.unsubscribed, False, True))

    query = ("ALTER TABLE ml.subscription_states "
             "ALTER COLUMN subscription_state SET NOT NULL")

    ml.query_exec(rs(DEFAULT_ID), query, tuple())

    query = """ CREATE TABLE ml.subscription_addresses (
            id                      serial PRIMARY KEY ,
            mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
            persona_id              integer NOT NULL REFERENCES core.personas(id),
            address                 varchar NOT NULL
    );
    CREATE UNIQUE INDEX idx_subscription_address_constraint ON ml.subscription_addresses(mailinglist_id, persona_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_addresses TO cdb_persona;
    GRANT SELECT, UPDATE ON ml.subscription_addresses_id_seq TO cdb_persona;"""

    ml.query_exec(rs(DEFAULT_ID), query, tuple())

    query = ("SELECT mailinglist_id, persona_id, address as email "
             "FROM ml.subscription_states WHERE address IS NOT NULL")

    data = ml.query_all(rs(DEFAULT_ID), query, tuple())

    for datum in data:
        # Setting address is not allowed for anyone other than the person.
        ml.set_subscription_address(rs(datum["persona_id"]), **datum)

    query = "ALTER TABLE ml.subscription_states DROP COLUMN {}"

    ml.query_exec(rs(DEFAULT_ID), query.format("is_subscribed"), tuple())
    ml.query_exec(rs(DEFAULT_ID), query.format("is_override"), tuple())
    ml.query_exec(rs(DEFAULT_ID), query.format("address"), tuple())

    query = "SELECT mailinglist_id, persona_id FROM ml.subscription_requests"

    data = ml.query_all(rs(DEFAULT_ID), query, tuple())

    for datum in data:
        datum["subscription_state"] = const.SubscriptionStates.pending

    ml._set_subscriptions(rs(DEFAULT_ID), data)

    query = "DROP TABLE ml.subscription_requests"

    ml.query_exec(rs(DEFAULT_ID), query, tuple())

    from pprint import pprint

    ml_ids = ml.list_mailinglists(rs(DEFAULT_ID), active_only=False)
    for ml_id in ml_ids:
        mlproxy.write_subscription_states(rs(DEFAULT_ID), ml_id)

        # Some debug output.
        pprint(ml_id)
        pprint(ml.get_subscription_states(rs(DEFAULT_ID), ml_id))
        pprint(list(filter(None, ml.get_subscription_addresses(
            rs(DEFAULT_ID), ml_id, explicits_only=True).values())))
