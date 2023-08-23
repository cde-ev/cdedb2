import csv
import pathlib
import sys

from cdedb.backend.past_event import PastEventBackend
from cdedb.common import CdEDBObject
from cdedb.frontend.common import CustomCSVDialect
from cdedb.script import Script

infile_events = pathlib.Path(sys.argv[1])
infile_courses = pathlib.Path(sys.argv[2])

s = Script(dbuser='cdb_admin')

past_event: PastEventBackend = s.make_backend('past_event')

institution_ids = past_event.list_institutions(s.rs())
institution_map = {
    e['shortname']: e['id']
    for e in past_event.get_institutions(s.rs(), institution_ids).values()
}
institution_map['AT'] = institution_map['DSA']

with infile_events.open("r") as f:
    event_data = {
        event_line['ID']: {
            'title': event_line['Standort_Langbez'],
            'shortname': event_line['shortname'],
            'institution': institution_map[event_line['Programm']],
            'description': None,
            'tempus': event_line['Termin_Aka_von'],
        }
        for event_line in csv.DictReader(f, dialect=CustomCSVDialect)
    }

with infile_courses.open("r") as f:
    course_data: CdEDBObject = {}
    for course_line in csv.DictReader(f, dialect=CustomCSVDialect):
        event_id = course_line['FK_GLStandorte']
        if event_id not in course_data:
            course_data[event_id] = []
        course_data[event_id].append({
            'nr': course_line['KursNr'],
            'title': " – ".join(
                filter(None, map(str.strip, (
                    course_line['Kursobertitel'],
                    course_line['Kursuntertitel'],
                )))),
            'description': course_line['KursBeschreibung'],
        })

with s:
    pevent_count = pcourse_count = 0
    for external_id, pevent in event_data.items():
        pevent_id = past_event.create_past_event(s.rs(), pevent)
        pevent_count += 1
        for pcourse in course_data[external_id]:
            pcourse['pevent_id'] = pevent_id
            past_event.create_past_course(s.rs(), pcourse)
            pcourse_count += 1

    print(f"{pevent_count} events created with {pcourse_count} courses.")
