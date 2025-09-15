#!/usr/bin/env python3

"""Services for the core realm."""

from cdedb.frontend.core.base import CoreBaseFrontend
from cdedb.frontend.core.complaint import CoreComplaintMixin
from cdedb.frontend.core.genesis import CoreGenesisMixin

__all__ = ['CoreFrontend']


class CoreFrontend(CoreComplaintMixin, CoreGenesisMixin, CoreBaseFrontend):
    pass
