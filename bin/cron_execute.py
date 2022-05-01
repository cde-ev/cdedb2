#!/usr/bin/env python3

"""To be executed by the cron of user www-data with the following settings:

*/15 * * * * flock -n /var/lib/cdedb/cron.lock /cdedb2/bin/cron_execute.py
"""

import getpass

from cdedb.config import DEFAULT_CONFIGPATH, set_configpath

set_configpath(DEFAULT_CONFIGPATH)
# TODO make importing from the cdedb module working without config path set
from cdedb.frontend.cron import CronFrontend  # pylint: disable=import-outside-toplevel

if __name__ == "__main__":
    if getpass.getuser() != "www-data":
        raise RuntimeError("Must be run as user www-data.")
    cron = CronFrontend()
    cron.execute()
