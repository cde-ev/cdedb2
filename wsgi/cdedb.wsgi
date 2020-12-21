#!/usr/bin/env python3

"""Entry script for apache."""

import os.path
import sys

currentpath = os.path.dirname(os.path.abspath(__file__))
if not currentpath.startswith('/') or not currentpath.endswith('/wsgi'):
    raise RuntimeError("Failed to locate repository")
repopath = currentpath[:-5]

sys.path.append(repopath)

from cdedb.frontend.application import Application

configpath = "/etc/cdedb-application-config.py"
if not os.path.isfile(configpath):
   configpath = None
application = Application(configpath)
