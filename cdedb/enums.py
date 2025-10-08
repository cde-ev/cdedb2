"""Provide a list of all enums in this project.

This is kind of ugly, since this is a manually compiled list, but this
is needed for creation of validators and serializers and thus we keep
one list instead of two.
"""

# ruff: noqa: F401

import enum

from cdedb.common import (
    AgeClasses,
    CourseChoiceToolActions,
    CourseFilterPositions,
    GenesisDecision,
    LineResolutions,
    LodgementsSortkeys,
)
from cdedb.common.parse.util import (
    Accounts,
    ConfidenceLevel,
    TransactionType,
)
from cdedb.common.privileges import EventPrivileges
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.common.query.log_filter import IncludeEmpty
from cdedb.database.constants import *  # noqa: F403
from cdedb.models.event_constraint_violations import (
    ViolationKind,
    ViolationSeverity,
)
from cdedb.models.ml import MailinglistGroup
from cdedb.uncommon.intenum import CdEIntEnum
from cdedb.uncommon.submanshim import SubscriptionAction, SubscriptionPolicy

ALL_ENUMS: tuple[type[enum.Enum], ...] = tuple(
    enum_ for enum_ in locals().values()
    if isinstance(enum_, type)
       and issubclass(enum_, enum.Enum)
       and not getattr(enum_, "infinite_enum", False)
)

ALL_INFINITE_ENUMS: tuple[type[CdEIntEnum], ...] = tuple(
    enum_ for enum_ in locals().values()
    if isinstance(enum_, type)
       and issubclass(enum_, CdEIntEnum)
       and getattr(enum_, "infinite_enum", False)
)

#: A dict for enum lookup in the templates.
ENUMS_DICT = {e.__name__: e for e in ALL_ENUMS}
ENUMS_DICT.update({e.__name__: e for e in ALL_INFINITE_ENUMS})

NON_TRANSLATED_ENUMS = {
    SubscriptionState,
    MailinglistDomain,
    LockType,
    TransactionType,
    SubscriptionPolicy,
    SubscriptionAction,
    LodgementsSortkeys,
    Accounts,
    CourseChoiceToolActions,
    CourseFilterPositions,
    QueryScope,
    ConfidenceLevel,
    GenesisDecision,
    EventPrivileges,
}
