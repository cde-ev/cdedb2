"""data types for the CdEDB project"""

import datetime as _datetime
import decimal as _decimal
from collections.abc import MutableMapping as _MutableMapping
from typing import TYPE_CHECKING, Any as _Any, NewType as _NewType

from subman import SubscriptionState as _SubscriptionState

from cdedb.common.query import Query as _Query

if TYPE_CHECKING:
    from cdedb.common import (
        CdEDBObject as _CdEDBObject, CdEDBOptionalMap as _CdEDBOptionalMap,
    )
else:
    _CdEDBObject = _CdEDBOptionalMap = None

del TYPE_CHECKING

TypeMapping = _MutableMapping[str, type[_Any]]

# SIMPLE/PRIMITIVE/ATOMIC TYPES

NonNegativeInt = _NewType("NonNegativeInt", int)
PositiveInt = _NewType("PositiveInt", int)
NegativeInt = _NewType("NegativeInt", int)
NonZeroInt = _NewType("NonZeroInt", int)
ProtoID = _NewType("ProtoID", int)
ID = _NewType("ID", ProtoID)
CreationID = _NewType("CreationID", ProtoID)
CdedbID = _NewType("CdedbID", ID)  # subtype of ID as it also uses that validator
PartialImportID = _NewType("PartialImportID", int)
SingleDigitInt = _NewType("SingleDigitInt", int)

NonNegativeFloat = _NewType("NonNegativeFloat", float)

NonNegativeDecimal = _NewType("NonNegativeDecimal", _decimal.Decimal)
NonNegativeLargeDecimal = _NewType(
    "NonNegativeLargeDecimal", NonNegativeDecimal)
PositiveDecimal = _NewType("PositiveDecimal", _decimal.Decimal)

EmptyDict = _NewType("EmptyDict", dict[_Any, _Any])
EmptyList = _NewType("EmptyList", list[_Any])

Realm = _NewType("Realm", str)
StringType = _NewType("StringType", str)
Url = _NewType("Url", str)
Shortname = _NewType("Shortname", str)
ShortnameIdentifier = _NewType("ShortnameIdentifier", Shortname)
ShortnameRestrictiveIdentifier = _NewType(
    "ShortnameRestrictiveIdentifier", ShortnameIdentifier)
LegacyShortname = _NewType("LegacyShortname", str)
PrintableASCIIType = _NewType("PrintableASCIIType", str)
PrintableASCII = _NewType("PrintableASCII", str)  # TODO make these subtypes?
Identifier = _NewType("Identifier", str)
RestrictiveIdentifier = _NewType("RestrictiveIdentifier", str)
CSVIdentifier = _NewType("CSVIdentifier", str)
TokenString = _NewType("TokenString", str)
Base64 = _NewType("Base64", str)
PasswordStrength = _NewType("PasswordStrength", str)
Email = _NewType("Email", str)
EmailLocalPart = _NewType("EmailLocalPart", str)
Phone = _NewType("Phone", str)
GermanPostalCode = _NewType("GermanPostalCode", str)
Country = _NewType("Country", str)
IBAN = _NewType("IBAN", str)
SafeStr = _NewType("SafeStr", str)
Vote = _NewType("Vote", str)
Regex = _NewType("Regex", str)
NonRegex = _NewType("NonRegex", str)

IntCSVList = _NewType("IntCSVList", list[int])
CdedbIDList = _NewType("CdedbIDList", list[CdedbID])

OrgaToken = _NewType("OrgaToken", _CdEDBObject)
APITokenString = _NewType("APITokenString", tuple[str, str])

Birthday = _NewType("Birthday", _datetime.date)

InputFile = _NewType("InputFile", bytes)
CSVFile = _NewType("CSVFile", str)
ProfilePicture = _NewType("ProfilePicture", bytes)
PDFFile = _NewType("PDFFile", bytes)


# While not technically correct, this should always be true.
JSON = _NewType("JSON", _CdEDBObject)

# TODO this probably requires custom logic...
ByFieldDatatype = _NewType("ByFieldDatatype", str)

# COMPLEX/DICTIONARY TYPES
# TODO some could be subtypes (e.g. serializedeventupload -> serializedevent)

Persona = _NewType("Persona", _CdEDBObject)
GenesisCase = _NewType("GenesisCase", _CdEDBObject)
BatchAdmissionEntry = _NewType("BatchAdmissionEntry", _CdEDBObject)
PrivilegeChange = _NewType("PrivilegeChange", _CdEDBObject)
AnonymousMessage = _NewType("AnonymousMessage", _CdEDBObject)
Period = _NewType("Period", _CdEDBObject)
ExPuls = _NewType("ExPuls", _CdEDBObject)
MoneyTransferEntry = _NewType("MoneyTransferEntry", _CdEDBObject)
Lastschrift = _NewType("Lastschrift", _CdEDBObject)
SepaTransactions = _NewType("SepaTransactions", list[_CdEDBObject])
SepaMeta = _NewType("SepaMeta", _CdEDBObject)
MetaInfo = _NewType("MetaInfo", _CdEDBObject)
Institution = _NewType("Institution", _CdEDBObject)
PastEvent = _NewType("PastEvent", _CdEDBObject)
Event = _NewType("Event", _CdEDBObject)
EventPart = _NewType("EventPart", _CdEDBObject)
EventPartGroup = _NewType("EventPartGroup", _CdEDBObject)
EventPartGroupSetter = _NewType("EventPartGroupSetter", _CdEDBOptionalMap)
EventTrack = _NewType("EventTrack", _CdEDBObject)
EventTrackGroup = _NewType("EventTrackGroup", _CdEDBObject)
EventTrackGroupSetter = _NewType("EventTrackGroupSetter", _CdEDBOptionalMap)
EventField = _NewType("EventField", _CdEDBObject)
EventFee = _NewType("EventFee", _CdEDBObject)
EventFeeSetter = _NewType("EventFeeSetter", _CdEDBOptionalMap)
EventFeeCondition = _NewType("EventFeeCondition", str)
EventFeeModifier = _NewType("EventFeeModifier", _CdEDBObject)
PastCourse = _NewType("PastCourse", _CdEDBObject)
Course = _NewType("Course", _CdEDBObject)
Registration = _NewType("Registration", _CdEDBObject)
RegistrationPart = _NewType("RegistrationPart", _CdEDBObject)
RegistrationTrack = _NewType("RegistrationTrack", _CdEDBObject)
EventAssociatedFields = _NewType("EventAssociatedFields", _CdEDBObject)
FeeBookingEntry = _NewType("FeeBookingEntry", _CdEDBObject)
LodgementGroup = _NewType("LodgementGroup", _CdEDBObject)
Lodgement = _NewType("Lodgement", _CdEDBObject)
QuestionnaireRow = _NewType("QuestionnaireRow", _CdEDBObject)
# TODO maybe cast keys to str
Questionnaire = _NewType("Questionnaire", dict[int, list[QuestionnaireRow]])

SerializedEvent = _NewType("SerializedEvent", _CdEDBObject)
SerializedEventUpload = _NewType("SerializedEventUpload", SerializedEvent)
SerializedPartialEvent = _NewType("SerializedPartialEvent", _CdEDBObject)
SerializedPartialEventUpload = _NewType(
    "SerializedPartialEventUpload", SerializedPartialEvent)
SerializedEventQuestionnaire = _NewType("SerializedEventQuestionnaire", _CdEDBObject)
SerializedEventQuestionnaireUpload = _NewType(
    "SerializedEventQuestionnaireUpload", SerializedEventQuestionnaire)
SerializedEventConfiguration = _NewType("SerializedEventConfiguration", _CdEDBObject)

PartialCourse = _NewType("PartialCourse", _CdEDBObject)
PartialLodgementGroup = _NewType("PartialLodgementGroup", _CdEDBObject)
PartialLodgement = _NewType("PartialLodgement", _CdEDBObject)
PartialRegistration = _NewType("PartialRegistration", _CdEDBObject)
PartialRegistrationPart = _NewType("PartialRegistrationPart", _CdEDBObject)
PartialRegistrationTrack = _NewType("PartialRegistrationTrack", _CdEDBObject)

Mailinglist = _NewType("Mailinglist", _CdEDBObject)
DatabaseSubscriptionState = _NewType("DatabaseSubscriptionState", _SubscriptionState)
SubscriptionIdentifier = _NewType("SubscriptionIdentifier", _CdEDBObject)
SubscriptionDataset = _NewType("SubscriptionDataset", _CdEDBObject)
SubscriptionAddress = _NewType("SubscriptionAddress", _CdEDBObject)
Assembly = _NewType("Assembly", _CdEDBObject)
Ballot = _NewType("Ballot", _CdEDBObject)
BallotCandidate = _NewType("BallotCandidate", _CdEDBObject)
AssemblyAttachment = _NewType("AssemblyAttachment", _CdEDBObject)
AssemblyAttachmentVersion = _NewType("AssemblyAttachmentVersion", _CdEDBObject)
QueryInput = _NewType("QueryInput", _Query)
LogFilter = _NewType("LogFilter", _CdEDBObject)
CustomQueryFilter = _NewType("CustomQueryFilter", _CdEDBObject)

# This is used for places where transitioning to the new API is not yet feasible
# e.g. query specifications
VALIDATOR_LOOKUP: dict[str, type[_Any]] = {
    "str": str,
    "id": ID,
    "int": int,
    "float": float,
    "date": _datetime.date,
    "datetime": _datetime.datetime,
    "bool": bool,
    "non_negative_int": NonNegativeInt,
    "non_negtative_float": NonNegativeFloat,
    "phone": Phone,
    # This is not strictly accurate, but an acceptable fallback.
    "enum_int": int,
    "enum_str": str,
}
