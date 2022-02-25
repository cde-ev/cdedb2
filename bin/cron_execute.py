#!/usr/bin/env python3

"""To be executed by the cron of user www-data with the following settings:

*/15 * * * * flock -n /var/lib/cdedb/cron.lock /cdedb2/bin/cron_execute.py
"""

import getpass

from cdedb.frontend.cron import CronFrontend
from cdedb.setup.config import set_configpath

if __name__ == "__main__":
    if getpass.getuser() != "www-data":
        raise RuntimeError("Must be run as user www-data.")
    set_configpath("/etc/cdedb-application-config.py")
    cron = CronFrontend()
    cron.execute()
