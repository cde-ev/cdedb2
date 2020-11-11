import datetime
import decimal
from typing import (
    Any,
    AnyStr,
    Dict,
    Iterable,
    List,
    Mapping,
    NewType,
    Optional,
    Union,
)

from cdedb.common import CdEDBObject
from cdedb.query import Query

# needs typing_extensions.TypedDict until 3.9 due to runtime inspection
# from typing_extensions import Literal, TypedDict

# SIMPLE/PRIMITIVE/ATOMIC TYPES

NonNegativeInt = NewType("NonNegativeInt", int)
PositiveInt = NewType("PositiveInt", int)
ID = NewType("ID", int)
PartialImportID = NewType("PartialImportID", int)
SingleDigitInt = NewType("SingleDigitInt", int)
CdedbID = NewType("CdedbID", int)

NonNegativeDecimal = NewType("NonNegativeDecimal", decimal.Decimal)
NonNegativeLargeDecimal = NewType(
    "NonNegativeLargeDecimal", NonNegativeDecimal)
PositiveDecimal = NewType("PositiveDecimal", decimal.Decimal)

EmptyDict = NewType("EmptyDict", Dict[Any, Any])
EmptyList = NewType("EmptyList", List[Any])

Realm = NewType("Realm", str)
StringType = NewType("StringType", str)
PrintableASCIIType = NewType("PrintableASCIIType", str)
PrintableASCII = NewType("PrintableASCII", str)  # TODO make these subtypes?
Alphanumeric = NewType("Alphanumeric", str)
CSVAlphanumeric = NewType("CSVAlphanumeric", str)
Identifier = NewType("Identifier", str)
RestrictiveIdentifier = NewType("RestrictiveIdentifier", str)
CSVIdentifier = NewType("CSVIdentifier", str)
PasswordStrength = NewType("PasswordStrength", str)
Email = NewType("Email", str)
EmailLocalPart = NewType("EmailLocalPart", str)
Phone = NewType("Phone", str)
GermanPostalCode = NewType("GermanPostalCode", str)
IBAN = NewType("IBAN", str)
SafeStr = NewType("SafeStr", str)
Vote = NewType("Vote", str)
Regex = NewType("Regex", str)
NonRegex = NewType("NonRegex", str)

IntCSVList = NewType("IntCSVList", List[int])
CdedbIDList = NewType("CdedbIDList", List[CdedbID])


Birthday = NewType("Birthday", datetime.date)

InputFile = NewType("InputFile", bytes)
CSVFile = NewType("CSVFile", str)
ProfilePicture = NewType("ProfilePicture", bytes)
PDFFile = NewType("PDFFile", bytes)


JSON = NewType("JSON", Any)  # TODO can we narrow this down?

# TODO this probably requires custom logic...
ByFieldDatatype = NewType("ByFieldDatatype", str)

# COMPLEX/DICTIONARY TYPES
# TODO some could be subtypes (e.g. serializedeventupload -> serializedevent)

Persona = NewType("Persona", CdEDBObject)
GenesisCase = NewType("GenesisCase", CdEDBObject)
PrivilegeChange = NewType("PrivilegeChange", CdEDBObject)
Period = NewType("Period", CdEDBObject)
ExPuls = NewType("ExPuls", CdEDBObject)
Lastschrift = NewType("Lastschrift", CdEDBObject)
LastschriftTransaction = NewType("LastschriftTransaction", CdEDBObject)
SepaTransactions = NewType("SepaTransactions", List[CdEDBObject])
SepaMeta = NewType("SepaMeta", CdEDBObject)
MetaInfo = NewType("MetaInfo", CdEDBObject)
Institution = NewType("Institution", CdEDBObject)
PastEvent = NewType("PastEvent", CdEDBObject)
Event = NewType("Event", CdEDBObject)
EventPart = NewType("EventPart", CdEDBObject)
EventTrack = NewType("EventTrack", CdEDBObject)
EventField = NewType("EventField", CdEDBObject)
EventFeeModifier = NewType("EventFeeModifier", CdEDBObject)
PastCourse = NewType("PastCourse", CdEDBObject)
Course = NewType("Course", CdEDBObject)
Registration = NewType("Registration", CdEDBObject)
RegistrationPart = NewType("RegistrationPart", CdEDBObject)
RegistrationTrack = NewType("RegistrationTrack", CdEDBObject)
EventAssociatedFields = NewType("EventAssociatedFields", CdEDBObject)
LodgementGroup = NewType("LodgementGroup", CdEDBObject)
Lodgement = NewType("Lodgement", CdEDBObject)
Questionnaire = NewType("Questionnaire", CdEDBObject)

SerializedEventUpload = NewType("SerializedEventUpload", CdEDBObject)
SerializedEvent = NewType("SerializedEvent", CdEDBObject)
SerializedPartialEventUpload = NewType(
    "SerializedPartialEventUpload", CdEDBObject)
SerializedPartialEvent = NewType("SerializedPartialEvent", CdEDBObject)

PartialCourse = NewType("PartialCourse", CdEDBObject)
PartialLodgementGroup = NewType("PartialLodgementGroup", CdEDBObject)
PartialLodgement = NewType("PartialLodgement", CdEDBObject)
PartialRegistration = NewType("PartialRegistration", CdEDBObject)
PartialRegistrationPart = NewType("PartialRegistrationPart", CdEDBObject)
PartialRegistrationTrack = NewType("PartialRegistrationTrack", CdEDBObject)

Mailinglist = NewType("Mailinglist", CdEDBObject)
SubscriptionIdentifier = NewType("SubscriptionIdentifier", CdEDBObject)
SubscriptionState = NewType("SubscriptionState", CdEDBObject)
SubscriptionAddress = NewType("SubscriptionAddress", CdEDBObject)
SubscriptionRequestResolution = NewType(
    "SubscriptionRequestResolution", CdEDBObject)
Assembly = NewType("Assembly", CdEDBObject)
Ballot = NewType("Ballot", CdEDBObject)
BallotCandidate = NewType("BallotCandidate", CdEDBObject)
AssemblyAttachment = NewType("AssemblyAttachment", CdEDBObject)
AssemblyAttachmentVersion = NewType("AssemblyAttachmentVersion", CdEDBObject)
QueryInput = NewType("QueryInput", Query)
