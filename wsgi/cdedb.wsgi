#!/usr/bin/env python3

"""Entry script for apache."""

import os
import sys

currentpath = os.path.dirname(os.path.abspath(__file__))
if not currentpath.startswith('/') or not currentpath.endswith('/wsgi'):
    raise RuntimeError("Failed to locate repository")
repopath = currentpath[:-5]

sys.path.append(repopath)

configpath = "/etc/cdedb-application-config.py"
if not os.path.isfile(configpath):
   pass
# set the configpath environment variable
os.environ["CDEDB_CONFIGPATH"] = ""

from cdedb.frontend.application import Application

application = Application()
