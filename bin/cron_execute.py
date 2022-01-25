#!/usr/bin/env python3

"""To be executed by the cron of user www-data with the following settings:

*/15 * * * * flock -n /var/lib/cdedb/cron.lock /cdedb2/bin/cron_execute.py
"""

import getpass
import os

# this must be defined before the first import from the cdedb module
configpath = "/etc/cdedb-application-config.py"
os.environ["CDEDB_CONFIGPATH"] = configpath

from cdedb.frontend.cron import CronFrontend

if __name__ == "__main__":
    if getpass.getuser() != "www-data":
        raise RuntimeError("Must be run as user www-data.")
    cron = CronFrontend()
    cron.execute()
