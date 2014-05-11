#!/usr/bin/env python3

"""Entry script for apache."""

import sys
import os.path

currentpath = os.path.dirname(os.path.abspath(__file__))
if not currentpath.startswith('/') or not currentpath.endswith('/wsgi'):
    raise RuntimeError("Failed to locate repository")
repopath = currentpath[:-5]

sys.path.append(repopath)

from cdedb.frontend.application import Application
configpath = "/etc/cdedb-frontend-config.py"
if not os.path.isfile(configpath):
   configpath = None
application = Application(configpath)
