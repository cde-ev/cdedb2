#!/usr/bin/env python3

"""Services for the cde realm."""

from cdedb.frontend.cde_base import CdEBaseFrontend
from cdedb.frontend.cde_lastschrift import CdELastschriftMixin
from cdedb.frontend.cde_parse import CdEParseMixin
from cdedb.frontend.cde_past_event import CdEPastEventMixin
from cdedb.frontend.cde_semester import CdESemesterMixin


class CdEFrontend(CdELastschriftMixin, CdEPastEventMixin, CdEParseMixin,
                  CdESemesterMixin, CdEBaseFrontend):
    pass
