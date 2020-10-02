#!/usr/bin/env python3

from cdedb.script import setup, make_backend
import cdedb.database.constants as const

# Configuration

dry_run = False

rs = setup(persona_id=1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")
# Execution

ml = make_backend("ml")
ml_list = ml.list_mailinglists(rs())
mls = ml.get_mailinglists(rs(), ml_list)

for k, v in ml_list.items():
    new_type = None
    if "Orgateam" in v:
        if mls[k]["event_id"]:
            new_type = const.MailinglistTypes.event_orga
        else:
            new_type = const.MailinglistTypes.event_orga_legacy
    if "Teilnehmer" in v:
        if mls[k]["event_id"]:
            new_type = const.MailinglistTypes.event_associated
        else:
            new_type = const.MailinglistTypes.event_associated_legacy

    if new_type:
        mdata = {
            "id": k,
            "ml_type": new_type,
        }
        print(v, new_type)
        if not dry_run:
            ml.set_mailinglist(rs(), mdata)
