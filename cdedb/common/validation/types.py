"""data types for the CdEDB project"""

import datetime as _datetime
import decimal as _decimal
from collections.abc import Mapping as _Mapping, MutableMapping as _MutableMapping
from typing import TYPE_CHECKING, Any as _Any, NewType as _NewType

from subman import SubscriptionState as _SubscriptionState
from typing_extensions import TypeForm as _TypeForm

if TYPE_CHECKING:
    from cdedb.common.query import Query as _Query
else:
    _Query = None

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = dict[str, _Any]

# Map of pseudo objects, indexed by their id, as returned by
# `get_events`, event["parts"], etc.

CdEDBObjectMap = dict[int, CdEDBObject]

# Same as above, but we also allow negative ints (for creation, not reflected
# in the type] and None (for deletion). Used in `_set_tracks` and partial
# import diff.
CdEDBOptionalMap = dict[int, CdEDBObject | None]

TypeMapping = _Mapping[str, _TypeForm[_Any]]
MutableTypeMapping = _MutableMapping[_Any, _TypeForm[_Any]]

# SIMPLE/PRIMITIVE/ATOMIC TYPES

NonNegativeInt = _NewType("NonNegativeInt", int)
PositiveInt = _NewType("PositiveInt", int)
NegativeInt = _NewType("NegativeInt", int)
ID = _NewType("ID", int)
# PersonaID is special and will validate strings as "DB-X-Y" format.
PersonaID = _NewType("PersonaID", ID)
# Other IDs that are only differentiated by the type checker.
InvolvedID = _NewType("InvolvedID", ID)
EventID = _NewType("EventID", ID)


PartialImportID = _NewType("PartialImportID", int)
SingleDigitInt = _NewType("SingleDigitInt", int)

NonNegativeFloat = _NewType("NonNegativeFloat", float)

NonNegativeDecimal = _NewType("NonNegativeDecimal", _decimal.Decimal)
PositiveDecimal = _NewType("PositiveDecimal", _decimal.Decimal)

Realm = _NewType("Realm", str)
StringType = _NewType("StringType", str)
Url = _NewType("Url", str)
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
Vote = _NewType("Vote", str)
Regex = _NewType("Regex", str)
NonRegex = _NewType("NonRegex", str)

APITokenString = _NewType("APITokenString", tuple[str, str])

Birthday = _NewType("Birthday", _datetime.date)

InputFile = _NewType("InputFile", bytes)
CSVFile = _NewType("CSVFile", str)
ProfilePicture = _NewType("ProfilePicture", bytes)
PDFFile = _NewType("PDFFile", bytes)


# While not technically correct, this should always be true.
JSON = _NewType("JSON", CdEDBObject)

ByFieldDatatype = _NewType("ByFieldDatatype", object)

# COMPLEX/DICTIONARY TYPES
# TODO some could be subtypes (e.g. serializedeventupload -> serializedevent)

Persona = _NewType("Persona", CdEDBObject)
BatchAdmissionEntry = _NewType("BatchAdmissionEntry", CdEDBObject)
PrivilegeChange = _NewType("PrivilegeChange", CdEDBObject)
Period = _NewType("Period", CdEDBObject)
ExPuls = _NewType("ExPuls", CdEDBObject)
MoneyTransferEntry = _NewType("MoneyTransferEntry", CdEDBObject)
Lastschrift = _NewType("Lastschrift", CdEDBObject)
SepaTransactions = _NewType("SepaTransactions", list[CdEDBObject])
SepaMeta = _NewType("SepaMeta", CdEDBObject)
Institution = _NewType("Institution", CdEDBObject)
EventFeeCondition = _NewType("EventFeeCondition", str)
Registration = _NewType("Registration", CdEDBObject)
RegistrationPart = _NewType("RegistrationPart", CdEDBObject)
RegistrationTrack = _NewType("RegistrationTrack", CdEDBObject)
EventAssociatedFields = _NewType("EventAssociatedFields", CdEDBObject)
# TODO why is this still in usage?
Questionnaire = _NewType("Questionnaire", list[CdEDBObject])

SerializedEvent = _NewType("SerializedEvent", CdEDBObject)
SerializedEventUpload = _NewType("SerializedEventUpload", SerializedEvent)
SerializedPartialEvent = _NewType("SerializedPartialEvent", CdEDBObject)
SerializedPartialEventUpload = _NewType(
    "SerializedPartialEventUpload", SerializedPartialEvent
)
SerializedEventQuestionnaire = _NewType("SerializedEventQuestionnaire", CdEDBObject)
SerializedEventQuestionnaireUpload = _NewType(
    "SerializedEventQuestionnaireUpload", SerializedEventQuestionnaire
)

PartialCourse = _NewType("PartialCourse", CdEDBObject)
PartialLodgementGroup = _NewType("PartialLodgementGroup", CdEDBObject)
PartialLodgement = _NewType("PartialLodgement", CdEDBObject)
PartialRegistration = _NewType("PartialRegistration", CdEDBObject)
PartialRegistrationPart = _NewType("PartialRegistrationPart", CdEDBObject)
PartialRegistrationTrack = _NewType("PartialRegistrationTrack", CdEDBObject)
PartialRegistrationCheckinPeriod = _NewType(
    "PartialRegistrationCheckinPeriod", CdEDBObject
)

DatabaseSubscriptionState = _NewType("DatabaseSubscriptionState", _SubscriptionState)
SubscriptionIdentifier = _NewType("SubscriptionIdentifier", CdEDBObject)
SubscriptionDataset = _NewType("SubscriptionDataset", CdEDBObject)
SubscriptionAddress = _NewType("SubscriptionAddress", CdEDBObject)
Assembly = _NewType("Assembly", CdEDBObject)
Ballot = _NewType("Ballot", CdEDBObject)
BallotCandidate = _NewType("BallotCandidate", CdEDBObject)
AssemblyAttachment = _NewType("AssemblyAttachment", CdEDBObject)
AssemblyAttachmentVersion = _NewType("AssemblyAttachmentVersion", CdEDBObject)
QueryInput = _NewType("QueryInput", _Query)


QUERY_INPUT_VALIDATORS: dict[str, type[_Any]] = {
    "str": str,
    "id": ID,
    "int": int,
    "float": float,
    "date": _datetime.date,
    "datetime": _datetime.datetime,
    "ranged_date": _datetime.date,
    "ranged_datetime": _datetime.datetime,
    "bool": bool,
    "non_negative_int": NonNegativeInt,
    "non_negative_float": NonNegativeFloat,
    "phone": Phone,
    # This is not strictly accurate, but an acceptable fallback.
    "iban": str,
    "enum_int": int,
    "enum_str": str,
    "money": float,
    "cdedbid": PersonaID,
}
