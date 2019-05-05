#!/usr/bin/env python3

"""To be executed by the cron of user www-data with the following settings:

*/15 * * * * PYTHONPATH="/cdedb2/:${PYTHONPATH}" flock -n /var/lib/cdedb/cron.lock /cdedb2/bin/cron_execute.py
"""

import pathlib

from cdedb.frontend.cron import CronFrontend

if __name__ == "__main__":
    configpath = pathlib.Path("/etc/cdedb-application-config.py")
    if not configpath.exists():
        configpath = None
    cron = CronFrontend(configpath)
    cron.execute()
