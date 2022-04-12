#!/usr/bin/env python3

"""Entry script for apache."""

import pathlib
import sys

# determine the path of the repository, including all modules (cdedb, tests, doc etc)
currentpath = pathlib.Path(__file__).resolve().parent
if currentpath.parts[0] != '/' or currentpath.parts[-1] != 'wsgi':
    raise RuntimeError("Failed to locate repository")
repopath = currentpath.parent

sys.path.append(str(repopath))

# set the configpath to the default, since apache does not propagate environment
# variables consciously
from cdedb.config import DEFAULT_CONFIGPATH, set_configpath

set_configpath(DEFAULT_CONFIGPATH)

from cdedb.frontend.application import Application

application = Application()
