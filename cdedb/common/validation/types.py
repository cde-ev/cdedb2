"""data types for the CdEDB project"""

import datetime
import decimal
from collections.abc import MutableMapping
from typing import (  # pylint: disable=unused-import
    TYPE_CHECKING, Any, NewType as _NewType,
)

from subman import SubscriptionState

from cdedb.common.query import Query

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject, CdEDBOptionalMap
else:
    CdEDBObject = CdEDBOptionalMap = None

TypeMapping = MutableMapping[str, type[Any]]

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

NonNegativeDecimal = _NewType("NonNegativeDecimal", decimal.Decimal)
NonNegativeLargeDecimal = _NewType(
    "NonNegativeLargeDecimal", NonNegativeDecimal)
PositiveDecimal = _NewType("PositiveDecimal", decimal.Decimal)

EmptyDict = _NewType("EmptyDict", dict[Any, Any])
EmptyList = _NewType("EmptyList", list[Any])

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

OrgaToken = _NewType("OrgaToken", CdEDBObject)
APITokenString = _NewType("APITokenString", tuple[str, str])

Birthday = _NewType("Birthday", datetime.date)

InputFile = _NewType("InputFile", bytes)
CSVFile = _NewType("CSVFile", str)
ProfilePicture = _NewType("ProfilePicture", bytes)
PDFFile = _NewType("PDFFile", bytes)


# While not technically correct, this should always be true.
JSON = _NewType("JSON", CdEDBObject)

# TODO this probably requires custom logic...
ByFieldDatatype = _NewType("ByFieldDatatype", str)

# COMPLEX/DICTIONARY TYPES
# TODO some could be subtypes (e.g. serializedeventupload -> serializedevent)

Persona = _NewType("Persona", CdEDBObject)
GenesisCase = _NewType("GenesisCase", CdEDBObject)
BatchAdmissionEntry = _NewType("BatchAdmissionEntry", CdEDBObject)
PrivilegeChange = _NewType("PrivilegeChange", CdEDBObject)
Period = _NewType("Period", CdEDBObject)
ExPuls = _NewType("ExPuls", CdEDBObject)
MoneyTransferEntry = _NewType("MoneyTransferEntry", CdEDBObject)
Lastschrift = _NewType("Lastschrift", CdEDBObject)
SepaTransactions = _NewType("SepaTransactions", list[CdEDBObject])
SepaMeta = _NewType("SepaMeta", CdEDBObject)
MetaInfo = _NewType("MetaInfo", CdEDBObject)
Institution = _NewType("Institution", CdEDBObject)
PastEvent = _NewType("PastEvent", CdEDBObject)
Event = _NewType("Event", CdEDBObject)
EventPart = _NewType("EventPart", CdEDBObject)
EventPartGroup = _NewType("EventPartGroup", CdEDBObject)
EventPartGroupSetter = _NewType("EventPartGroupSetter", CdEDBOptionalMap)
EventTrack = _NewType("EventTrack", CdEDBObject)
EventTrackGroup = _NewType("EventTrackGroup", CdEDBObject)
EventTrackGroupSetter = _NewType("EventTrackGroupSetter", CdEDBOptionalMap)
EventField = _NewType("EventField", CdEDBObject)
EventFee = _NewType("EventFee", CdEDBObject)
EventFeeSetter = _NewType("EventFeeSetter", CdEDBOptionalMap)
EventFeeCondition = _NewType("EventFeeCondition", str)
EventFeeModifier = _NewType("EventFeeModifier", CdEDBObject)
PastCourse = _NewType("PastCourse", CdEDBObject)
Course = _NewType("Course", CdEDBObject)
Registration = _NewType("Registration", CdEDBObject)
RegistrationPart = _NewType("RegistrationPart", CdEDBObject)
RegistrationTrack = _NewType("RegistrationTrack", CdEDBObject)
EventAssociatedFields = _NewType("EventAssociatedFields", CdEDBObject)
FeeBookingEntry = _NewType("FeeBookingEntry", CdEDBObject)
LodgementGroup = _NewType("LodgementGroup", CdEDBObject)
Lodgement = _NewType("Lodgement", CdEDBObject)
QuestionnaireRow = _NewType("QuestionnaireRow", CdEDBObject)
# TODO maybe cast keys to str
Questionnaire = _NewType("Questionnaire", dict[int, list[QuestionnaireRow]])

SerializedEvent = _NewType("SerializedEvent", CdEDBObject)
SerializedEventUpload = _NewType("SerializedEventUpload", SerializedEvent)
SerializedPartialEvent = _NewType("SerializedPartialEvent", CdEDBObject)
SerializedPartialEventUpload = _NewType(
    "SerializedPartialEventUpload", SerializedPartialEvent)
SerializedEventQuestionnaire = _NewType("SerializedEventQuestionnaire", CdEDBObject)
SerializedEventQuestionnaireUpload = _NewType(
    "SerializedEventQuestionnaireUpload", SerializedEventQuestionnaire)
SerializedEventConfiguration = _NewType("SerializedEventConfiguration", CdEDBObject)

PartialCourse = _NewType("PartialCourse", CdEDBObject)
PartialLodgementGroup = _NewType("PartialLodgementGroup", CdEDBObject)
PartialLodgement = _NewType("PartialLodgement", CdEDBObject)
PartialRegistration = _NewType("PartialRegistration", CdEDBObject)
PartialRegistrationPart = _NewType("PartialRegistrationPart", CdEDBObject)
PartialRegistrationTrack = _NewType("PartialRegistrationTrack", CdEDBObject)

Mailinglist = _NewType("Mailinglist", CdEDBObject)
DatabaseSubscriptionState = _NewType("DatabaseSubscriptionState", SubscriptionState)
SubscriptionIdentifier = _NewType("SubscriptionIdentifier", CdEDBObject)
SubscriptionDataset = _NewType("SubscriptionDataset", CdEDBObject)
SubscriptionAddress = _NewType("SubscriptionAddress", CdEDBObject)
Assembly = _NewType("Assembly", CdEDBObject)
Ballot = _NewType("Ballot", CdEDBObject)
BallotCandidate = _NewType("BallotCandidate", CdEDBObject)
AssemblyAttachment = _NewType("AssemblyAttachment", CdEDBObject)
AssemblyAttachmentVersion = _NewType("AssemblyAttachmentVersion", CdEDBObject)
QueryInput = _NewType("QueryInput", Query)
LogFilter = _NewType("LogFilter", CdEDBObject)
CustomQueryFilter = _NewType("CustomQueryFilter", CdEDBObject)

# This is used for places where transitioning to the new API is not yet feasible
# e.g. query specifications
VALIDATOR_LOOKUP: dict[str, type[Any]] = {
    "str": str,
    "id": ID,
    "int": int,
    "float": float,
    "date": datetime.date,
    "datetime": datetime.datetime,
    "bool": bool,
}
