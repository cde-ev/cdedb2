"""Provide a list of all enums in this project.

This is kind of ugly, since this is a manually compiled list, but this
is needed for creation of validators and serializers and thus we keep
one list instead of two.
"""

import cdedb.database.constants as const
from cdedb.query import QueryOperators
from cdedb.common import AgeClasses

#: The list.
ALL_ENUMS = (
    const.Genders, const.MemberChangeStati, const.RegistrationPartStati,
    const.GenesisStati, const.SubscriptionPolicy, const.ModerationPolicy,
    const.AttachmentPolicy, const.AudiencePolicy,
    const.LastschriftTransactionStati, const.CoreLogCodes,
    const.CdeLogCodes, const.FinanceLogCodes, const.EventLogCodes,
    const.PastEventLogCodes, const.AssemblyLogCodes, const.MlLogCodes,
    QueryOperators, AgeClasses)
