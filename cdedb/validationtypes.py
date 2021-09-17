"""data types for the CdEDB project"""

import datetime
import decimal
from typing import Any, Dict, List, NewType as _NewType, Type

from cdedb.common import CdEDBObject
from cdedb.subman import SubscriptionState
from cdedb.query import Query

# SIMPLE/PRIMITIVE/ATOMIC TYPES

NonNegativeInt = _NewType("NonNegativeInt", int)
PositiveInt = _NewType("PositiveInt", int)
ID = _NewType("ID", int)
CdedbID = _NewType("CdedbID", ID)  # subtype of ID as it also uses that validator
PartialImportID = _NewType("PartialImportID", int)
SingleDigitInt = _NewType("SingleDigitInt", int)

NonNegativeDecimal = _NewType("NonNegativeDecimal", decimal.Decimal)
NonNegativeLargeDecimal = _NewType(
    "NonNegativeLargeDecimal", NonNegativeDecimal)
PositiveDecimal = _NewType("PositiveDecimal", decimal.Decimal)

EmptyDict = _NewType("EmptyDict", Dict[Any, Any])
EmptyList = _NewType("EmptyList", List[Any])

Realm = _NewType("Realm", str)
StringType = _NewType("StringType", str)
PrintableASCIIType = _NewType("PrintableASCIIType", str)
PrintableASCII = _NewType("PrintableASCII", str)  # TODO make these subtypes?
Alphanumeric = _NewType("Alphanumeric", str)
CSVAlphanumeric = _NewType("CSVAlphanumeric", str)
Identifier = _NewType("Identifier", str)
RestrictiveIdentifier = _NewType("RestrictiveIdentifier", str)
CSVIdentifier = _NewType("CSVIdentifier", str)
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

IntCSVList = _NewType("IntCSVList", List[int])
CdedbIDList = _NewType("CdedbIDList", List[CdedbID])


Birthday = _NewType("Birthday", datetime.date)

InputFile = _NewType("InputFile", bytes)
CSVFile = _NewType("CSVFile", str)
ProfilePicture = _NewType("ProfilePicture", bytes)
PDFFile = _NewType("PDFFile", bytes)


JSON = _NewType("JSON", Any)  # type: ignore  # TODO can we narrow this down?

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
LastschriftTransaction = _NewType("LastschriftTransaction", CdEDBObject)
LastschriftTransactionEntry = _NewType("LastschriftTransactionEntry", CdEDBObject)
SepaTransactions = _NewType("SepaTransactions", List[CdEDBObject])
SepaMeta = _NewType("SepaMeta", CdEDBObject)
MetaInfo = _NewType("MetaInfo", CdEDBObject)
Institution = _NewType("Institution", CdEDBObject)
PastEvent = _NewType("PastEvent", CdEDBObject)
Event = _NewType("Event", CdEDBObject)
EventPart = _NewType("EventPart", CdEDBObject)
EventTrack = _NewType("EventTrack", CdEDBObject)
EventField = _NewType("EventField", CdEDBObject)
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
Questionnaire = _NewType("Questionnaire", Dict[int, Any])  # TODO maybe cast keys to str

SerializedEvent = _NewType("SerializedEvent", CdEDBObject)
SerializedEventUpload = _NewType("SerializedEventUpload", SerializedEvent)
SerializedPartialEvent = _NewType("SerializedPartialEvent", CdEDBObject)
SerializedPartialEventUpload = _NewType(
    "SerializedPartialEventUpload", SerializedPartialEvent)

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


# This is used for places where transitioning to the new API is not yet feasible
# e.g. query specifications
VALIDATOR_LOOKUP: Dict[str, Type[Any]] = {
    "str": str,
    "id": ID,
    "int": int,
    "float": float,
    "date": datetime.date,
    "datetime": datetime.datetime,
    "bool": bool,
}
