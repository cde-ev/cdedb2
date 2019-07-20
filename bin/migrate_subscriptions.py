#!/usr/bin/env python3

import datetime
import gettext
import csv
from pprint import pprint

import psycopg2
import psycopg2.extras
import psycopg2.extensions

import pytz
import sys
from pathlib import Path
import shutil
import time

sys.path.insert(0, "/cdedb2/")

from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database.connection import IrradiatedConnection, Atomizer

import cdedb.database.constants as const
from cdedb.common import ProxyShim

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

#
# helpers
#

class User:
    def __init__(self, persona_id):
        self.persona_id = persona_id
        self.roles = {
            "anonymous", "persona", "cde", "event", "ml", "assembly",
            "cde_admin", "event_admin", "ml_admin", "assembly_admin",
            "core_admin", "admin", "member", "searchable"}
        self.orga = set()
        self.moderator = set()
        self.username = None
        self.display_name = None
        self.given_names = None
        self.family_name = None


class RequestState:
    def __init__(self, persona_id, conn):
        self.ambience = None
        self.sessionkey = None
        self.user = User(persona_id)
        self.request = None
        self.response = None
        self.notifications = None
        self.urls = None
        self.requestargs = None
        self.urlmap = None
        self.errors = None
        self.values = None
        self.lang = "de"
        self.gettext = gettext.translation('cdedb', languages=("de",),
                                           localedir="/cdedb2/i18n").gettext
        self.ngettext = gettext.translation('cdedb', languages=("de",),
                                            localedir="/cdedb2/i18n").ngettext
        self._coders = None
        self.begin = None
        self.conn = conn
        self._conn = conn
        self.is_quiet = False


#
# create connections
#
conn_string = "dbname=cdb user=cdb password=987654321098765432109876543210 port=5432 host=localhost"
cdb = psycopg2.connect(conn_string,
                       connection_factory=IrradiatedConnection,
                       cursor_factory=psycopg2.extras.RealDictCursor)
cdb.set_client_encoding("UTF8")


def rs(persona_id):
    return RequestState(persona_id, cdb)


#
# prepare backends
#
# core = CoreBackend("/etc/cdedb-application-config.py")
# cde = CdEBackend("/etc/cdedb-application-config.py")
# past_event = PastEventBackend("/etc/cdedb-application-config.py")
ml = MlBackend("/etc/cdedb-application-config.py")
mlproxy = ProxyShim(MlBackend("/etc/cdedb-application-config.py"))
# assembly = AssemblyBackend("/etc/cdedb-application-config.py")

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

    query = ("SELECT mailinglist_id, persona_id, address "
             "FROM ml.subscription_states WHERE address IS NOT NULL")

    data = ml.query_all(rs(DEFAULT_ID), query, tuple())

    for datum in data:
        # Setting address is not allowed for anyone other than the person.
        ml.set_subscription_address(rs(datum["persona_id"]), datum)

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
        # this needs ml_proxy to have access to singularized variants.
        mlproxy.write_subscription_states(rs(DEFAULT_ID), ml_id)

        # Some debug output.
        # pprint(ml_id)
        # pprint(mlproxy.get_subscription_states(rs(DEFAULT_ID), ml_id))
        # pprint(list(filter(None, mlproxy.get_subscription_addresses(
        #     rs(DEFAULT_ID), ml_id, explicits_only=True).values())))
