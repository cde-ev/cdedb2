import datetime
import decimal
from typing import Any, Iterable, List, Mapping, NewType, Optional

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
PositiveDecimal = NewType("PositiveDecimal", decimal.Decimal)

EmptyDict = NewType("EmptyDict", dict)
EmptyList = NewType("EmptyList", list)

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


JSON = NewType("JSON", dict)  # TODO actually Any

# TODO this probably requires custom logic...
ByFieldDatatype = NewType("ByFieldDatatype", str)

# COMPLEX/DICTIONARY TYPES
# TODO replace dict with CdEDBObject = Dict[str, Any]
# TODO some could be subtypes (e.g. serializedeventupload -> serializedevent)

Persona = NewType("Persona", dict)
GenesisCase = NewType("GenesisCase", dict)
PrivilegeChange = NewType("PrivilegeChange", dict)
Period = NewType("Period", dict)
ExPuls = NewType("ExPuls", dict)
Lastschrift = NewType("Lastschrift", dict)
LastschriftTransaction = NewType("LastschriftTransaction", dict)
SepaTransactions = NewType("SepaTransactions", List[dict])
SepaMeta = NewType("SepaMeta", dict)
MetaInfo = NewType("MetaInfo", dict)
Institution = NewType("Institution", dict)
PastEvent = NewType("PastEvent", dict)
Event = NewType("Event", dict)
EventPart = NewType("EventPart", dict)
EventTrack = NewType("EventTrack", dict)
EventField = NewType("EventField", dict)
EventFeeModifier = NewType("EventFeeModifier", dict)
PastCourse = NewType("PastCourse", dict)
Course = NewType("Course", dict)
Registration = NewType("Registration", dict)
RegistrationPart = NewType("RegistrationPart", dict)
RegistrationTrack = NewType("RegistrationTrack", dict)
EventAssociatedFields = NewType("EventAssociatedFields", dict)
LodgementGroup = NewType("LodgementGroup", dict)
Lodgement = NewType("Lodgement", dict)
Questionnaire = NewType("Questionnaire", dict)

SerializedEventUpload = NewType("SerializedEventUpload", dict)
SerializedEvent = NewType("SerializedEvent", dict)
SerializedPartialEventUpload = NewType("SerializedPartialEventUpload", dict)
SerializedPartialEvent = NewType("SerializedPartialEvent", dict)

PartialCourse = NewType("PartialCourse", dict)
PartialLodgementGroup = NewType("PartialLodgementGroup", dict)
PartialLodgement = NewType("PartialLodgement", dict)
PartialRegistration = NewType("PartialRegistration", dict)
PartialRegistrationPart = NewType("PartialRegistrationPart", dict)
PartialRegistrationTrack = NewType("PartialRegistrationTrack", dict)

Mailinglist = NewType("Mailinglist", dict)
SubscriptionIdentifier = NewType("SubscriptionIdentifier", dict)
SubscriptionState = NewType("SubscriptionState", dict)
SubscriptionAddress = NewType("SubscriptionAddress", dict)
SubscriptionRequestResolution = NewType("SubscriptionRequestResolution", dict)
Assembly = NewType("Assembly", dict)
Ballot = NewType("Ballot", dict)
BallotCandidate = NewType("BallotCandidate", dict)
AssemblyAttachment = NewType("AssemblyAttachment", dict)
AssemblyAttachmentVersion = NewType("AssemblyAttachmentVersion", dict)
QueryInput = NewType("QueryInput", Query)
