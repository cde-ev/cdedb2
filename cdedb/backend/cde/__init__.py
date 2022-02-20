#!/usr/bin/env python3

"""The CdE backend provides services for (former) members as well as
facilities for managing the organization.

The relevant user roles are:
* `cde`: For members and former members that may gain membership.
* `member`: For users that are currently members.
"""

from cdedb.backend.cde.base import CdEBaseBackend
from cdedb.backend.cde.lastschrift import CdELastschriftBackend
from cdedb.backend.cde.semester import CdESemesterBackend


class CdEBackend(CdESemesterBackend, CdELastschriftBackend, CdEBaseBackend):
    pass
