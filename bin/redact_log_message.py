#!/usr/bin/env python3
"""Generic interactive script to redact a message for a specific log entry.
"""
from pprint import pprint

from cdedb.backend.core import CoreBackend
from cdedb.common.query.log_filter import ALL_LOG_FILTERS, GenericLogFilter
from cdedb.script import Script

# setup

script = Script(dbuser="cdb_admin")
rs = script.rs()
core: CoreBackend = script.make_backend("core", proxy=False)

# work

with script:
    log_table = input("Which table do you want to delete from? ")
    if log_table not in {log_filter.log_table for log_filter in ALL_LOG_FILTERS}:
        raise ValueError("Unknown log")

    # raises if unsuccessful
    log_id = int(input("For which log id do you want to change the message? "))

    cols = GenericLogFilter.get_columns()
    log_entry = core.sql_select_one(rs, log_table, cols, log_id)
    if not log_entry:
        raise RuntimeError("Log entry not found.")
    print(f"Log entry:")
    pprint(log_entry)
    decision = input("Do you really want to change this change note (y/n)? ")
    proceed = decision.strip().lower() in {'y', 'yes', 'j', 'ja'}
    if not proceed:
        print("Abort change of log message.")
        exit()

    new_message = input("Which new change note do you want to set? ")
    core.redact_log(rs, log_table, log_id, new_message)

    log_entry = core.sql_select_one(rs, log_table, cols, log_id)
    if not log_entry:
        raise RuntimeError("Changed Log entry not found.")
    print("Change successful. New log entry:")
    pprint(log_entry)
