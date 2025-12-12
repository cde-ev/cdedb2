#!/usr/bin/env python3

import csv
import pathlib
import sys

import cdedb.database.constants as const
from cdedb.common import CdEDBObject
from cdedb.frontend.common import CustomCSVDialect
from cdedb.script import Script

infile_events = pathlib.Path(sys.argv[1])
infile_courses = pathlib.Path(sys.argv[2])

s = Script(dbuser='cdb_admin')

past_event = s.make_past_event_backend(proxy=True)

institution_map = {e.shortname: e for e in const.PastInstitutions}
institution_map['AT'] = institution_map['DSA']

with infile_events.open("r") as f:
    event_data = {
        event_line['Standort_Kurzbez']: {
            'title': event_line['Standort_Langbez'],
            'shortname': event_line['Standort_Kurzbez'],
            'institution': const.PastInstitutions.bub,
            'description': None,
            'tempus': event_line['Termin_Aka_von'],
        }
        for event_line in csv.DictReader(f, dialect=CustomCSVDialect)
    }

with infile_courses.open("r") as f:
    course_data: CdEDBObject = {}
    for course_line in csv.DictReader(f, dialect=CustomCSVDialect):
        event_id = course_line['Standort_Kurzbez']
        if event_id not in course_data:
            course_data[event_id] = []
        course_data[event_id].append({
            'nr': course_line['GLKurse::KursNr'],
            'title': " – ".join(
                filter(None, map(str.strip, (
                    course_line['GLKurse::Kursobertitel'],
                    course_line['GLKurse::Kursuntertitel'],
                )))),
            'description': course_line['GLKurse::KursBeschreibung'],
        })

with s:
    pevent_count = pcourse_count = 0
    for external_id, pevent in event_data.items():
        pevent_id = past_event.create_past_event(s.rs(), pevent)
        pevent_count += 1
        for pcourse in course_data.get(external_id, []):
            if not pcourse['nr']:
                continue
            pcourse['pevent_id'] = pevent_id
            past_event.create_past_course(s.rs(), pcourse)
            pcourse_count += 1

    print(f"{pevent_count} events created with {pcourse_count} courses.")
