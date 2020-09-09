#!/usr/bin/env python3

import sys
import csv
import re

sys.path.insert(0, "/cdedb2/")

from cdedb.script import setup, make_backend

# Configuration

dry_run = True
rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")
input_path = "/cdedb2/bin/fotogalerien-logins.csv"

# Execution

past_event = make_backend("past_event")

with open(input_path, "r") as infile:
    reader = csv.DictReader(infile, fieldnames=("title", "link"), delimiter=",")
    data = list(reader)

all_pevents = past_event.list_past_events(rs())

template = \
"""Mediensammlung
: Link [https://{simple_link}]({link})
: Benutzername: {user}
: Passwort: {pw}"""

for e in data:
    pw, user, simple_link = re.search("https://(.+):(.+)@(.+)", e["link"]).groups()

    pevents = {k for k, v in all_pevents.items() if e["title"] in v}
    if not pevents:
        print("No past events found for '{}'.".format(e["title"]))
    else:
        print("'{}': {}".format(e["title"], pevents))

    for pevent_id in pevents:
        setter = {
            "id": pevent_id,
            "notes": template.format(simple_link=simple_link, link=e["link"], user=user, pw=pw)
        }
        if not dry_run:
            code = past_event.set_past_event(rs(), setter)
            print("Change committed with code {}.".format(code))

if dry_run:
    print("Skipped all changes due to dry run mode.")
