"""Provide a list of all enums in this project.

This is kind of ugly, since this is a manually compiled list, but this
is needed for creation of validators and serializers and thus we keep
one list instead of two.
"""

from enum import Enum
from typing import Tuple, Type

import cdedb.database.constants as const
from cdedb.common import (
    Accounts, AgeClasses, CourseChoiceToolActions, CourseFilterPositions,
    LineResolutions, LodgementsSortkeys, SubscriptionActions, TransactionType,
)
from cdedb.query import QueryOperators

#: The list of normal enums
ALL_ENUMS: Tuple[Type[Enum], ...] = (
    const.Genders,
    const.MemberChangeStati,
    const.RegistrationPartStati,
    const.PrivilegeChangeStati,
    const.GenesisStati,
    const.SubscriptionStates,
    const.MailinglistInteractionPolicy,
    const.ModerationPolicy,
    const.AttachmentPolicy,
    const.AudiencePolicy,
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
    const.QuestionnaireUsages,
    QueryOperators,
    AgeClasses,
    LineResolutions,
    SubscriptionActions,
    LodgementsSortkeys,
    Accounts,
    TransactionType,
)

#: The list of infinite enums
ALL_INFINITE_ENUMS: Tuple[Type[Enum], ...] = (
    CourseFilterPositions, CourseChoiceToolActions)

#: A dict for enum lookup in the templates.
ENUMS_DICT = {e.__name__: e for e in ALL_ENUMS}
ENUMS_DICT.update({e.__name__: e for e in ALL_INFINITE_ENUMS})
