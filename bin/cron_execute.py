#!/usr/bin/env python3

"""To be executed by the cron of user www-cde with the following settings:

*/15 * * * * flock -n /var/lib/cdedb/cron.lock /cdedb2/bin/cron_execute.py
"""

import getpass

from cdedb.config import DEFAULT_CONFIGPATH, set_configpath
from cdedb.frontend.cron import CronFrontend

if __name__ == "__main__":
    if getpass.getuser() != "www-cde":
        raise RuntimeError("Must be run as user www-cde.")
    set_configpath(DEFAULT_CONFIGPATH)
    cron = CronFrontend()
    cron.execute()
