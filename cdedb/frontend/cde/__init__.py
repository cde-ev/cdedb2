#!/usr/bin/env python3

"""Services for the cde realm."""

from cdedb.frontend.cde.base import CdEBaseFrontend
from cdedb.frontend.cde.lastschrift import CdELastschriftMixin
from cdedb.frontend.cde.parse import CdEParseMixin
from cdedb.frontend.cde.semester import CdESemesterMixin

__all__ = ['CdEFrontend']


class CdEFrontend(
    CdELastschriftMixin,
    CdEParseMixin,
    CdESemesterMixin,
    CdEBaseFrontend,
):
    pass
