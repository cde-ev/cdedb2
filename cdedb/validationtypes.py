import datetime
import decimal
from typing import Any, Iterable, List, Mapping, NewType, Optional

# needs typing_extensions.TypedDict until 3.9 due to runtime inspection
# from typing_extensions import Literal, TypedDict

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
