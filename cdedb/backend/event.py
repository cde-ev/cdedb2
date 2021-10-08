#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

from cdedb.backend.event_base import EventBaseBackend
from cdedb.backend.event_helpers import EventBackendHelpers


class EventBackend(EventBaseBackend, EventBackendHelpers):
    pass
