"""Provide a list of all enums in this project.

This is kind of ugly, since this is a manually compiled list, but this
is needed for creation of validators and serializers and thus we keep
one list instead of two.
"""

from enum import Enum, IntEnum

import cdedb.database.constants as const
from cdedb.common import (
    Accounts, AgeClasses, ConfidenceLevel, CourseChoiceToolActions,
    CourseFilterPositions, GenesisDecision, LineResolutions, LodgementsSortkeys,
    TransactionType,
)
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.uncommon.submanshim import SubscriptionAction, SubscriptionPolicy

#: The list of normal enums
ALL_ENUMS: tuple[type[Enum], ...] = (
    const.Genders,
    const.PersonaChangeStati,
    const.RegistrationPartStati,
    const.PrivilegeChangeStati,
    const.GenesisStati,
    const.SubscriptionState,
    const.ModerationPolicy,
    const.AttachmentPolicy,
    const.LastschriftTransactionStati,
    const.CoreLogCodes,
    const.CdeLogCodes,
    const.FinanceLogCodes,
    const.EventLogCodes,
    const.PastEventLogCodes,
    const.AssemblyLogCodes,
    const.MlLogCodes,
    const.FieldAssociations,
    const.FieldDatatypes,
    const.MailinglistTypes,
    const.MailinglistDomain,
    const.MailinglistRosterVisibility,
    const.QuestionnaireUsages,
    const.EventPartGroupType,
    const.CourseTrackGroupType,
    const.EventFeeType,
    const.PastInstitutions,
    QueryOperators,
    QueryScope,
    AgeClasses,
    LineResolutions,
    GenesisDecision,
    SubscriptionAction,
    SubscriptionPolicy,
    LodgementsSortkeys,
    Accounts,
    TransactionType,
    ConfidenceLevel,
)

#: The list of infinite enums
ALL_INFINITE_ENUMS: tuple[type[IntEnum], ...] = (
    CourseFilterPositions, CourseChoiceToolActions)

#: A dict for enum lookup in the templates.
ENUMS_DICT = {e.__name__: e for e in ALL_ENUMS}
ENUMS_DICT.update({e.__name__: e for e in ALL_INFINITE_ENUMS})
