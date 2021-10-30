#!/usr/bin/env python3

"""
The `EventFrontend` provides services for the event realm.

It is created via multiple inheritance from a bunch of mixins, all of which are
subclasses of the `EventBaseFrontend`.

You should never need to access the individual mixins, only the `EventFrontend`.
"""

from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.frontend.event.course import EventCourseMixin
from cdedb.frontend.event.download import EventDownloadMixin
from cdedb.frontend.event.event import EventEventMixin
from cdedb.frontend.event.fields import EventFieldMixin
from cdedb.frontend.event.lodgement import EventLodgementMxin
from cdedb.frontend.event.partial_import import EventImportMixin
from cdedb.frontend.event.query import EventQueryMixin
from cdedb.frontend.event.questionnaire import EventQuestionnaireMixin
from cdedb.frontend.event.registration import EventRegistrationMixin

__all__ = ['EventFrontend']


class EventFrontend(
    EventRegistrationMixin,
    EventQuestionnaireMixin,
    EventQueryMixin,
    EventLodgementMxin,
    EventFieldMixin,
    EventImportMixin,
    EventEventMixin,
    EventDownloadMixin,
    EventCourseMixin,
    EventBaseFrontend
):
    pass
