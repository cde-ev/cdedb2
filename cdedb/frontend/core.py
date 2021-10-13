#!/usr/bin/env python3

"""Services for the core realm."""

from cdedb.frontend.core_base import CoreBaseFrontend
from cdedb.frontend.core_genesis import CoreGenesisMixin


class CoreFrontend(CoreGenesisMixin, CoreBaseFrontend):
    pass
