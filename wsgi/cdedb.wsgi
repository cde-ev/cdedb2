#!/usr/bin/env python3

"""Entry script for apache."""

import os
import sys

currentpath = os.path.dirname(os.path.abspath(__file__))
if not currentpath.startswith('/') or not currentpath.endswith('/wsgi'):
    raise RuntimeError("Failed to locate repository")
repopath = currentpath[:-5]

sys.path.append(repopath)

# set the configpath to the default, since apache does not propagate environment
# variables consciously
from cdedb.setup.config import DEFAULT_CONFIGPATH, set_configpath

set_configpath(DEFAULT_CONFIGPATH)

from cdedb.frontend.application import Application

application = Application()
