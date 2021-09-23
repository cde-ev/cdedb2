"""Helpers for parsing bank statements"""

import collections
import datetime
import decimal
import enum
import json
import re
from typing import Callable, Dict, List, Optional, Tuple, Union

import cdedb.validationtypes as vtypes
from cdedb.common import (
    Accounts, CdEDBObject, CdEDBObjectMap, Error, TransactionType, diacritic_patterns,
    n_, now, EntitySorter, xsorted, PARSE_OUTPUT_DATEFORMAT
)
from cdedb.filter import cdedbid_filter
from cdedb.validation import validate_check

# This is the specification of the order of the fields in the input.
# This could be changed in the online banking, but we woud lose backwards
# compability with multiple years of saved csv exports.
# Note that "reference" is a `restkey` rather than a real key.
STATEMENT_CSV_FIELDS = ("myBLZ", "myAccNr", "statementNr",
                        "statementDate", "currency", "valuta", "date",
                        "currency2", "amount", "textKey",
                        "customerReference", "instituteReference",
                        "transaction", "posting", "primanota",
                        "textKey2", "BLZ", "KontoNr", "BIC", "IBAN",
                        "accHolder", "accHolder2")
# Since the reference is split over multiple columns, gather all of them here.
STATEMENT_CSV_RESTKEY = "reference"
# Specification for how the date is formatted in the input.
STATEMENT_INPUT_DATEFORMAT = "%d.%m.%y"

# This specifies the export fields for the (eventual) use with GnuCash.
# Since this is not yet currently in use this is very much subject to change.
GNUCASH_EXPORT_FIELDS = ("statement_date", "amount", "account", "t_id",
                         "posting", "category", "reference", "summary")

# This is the specification for how the export for membership fees should look
# like. The first five fields are a requirement by the reimport functionality in
# `cdedb.frontend.cde::money_transfers`, everything after that is curretnly
# ignored.
MEMBERSHIP_EXPORT_FIELDS = ("amount", "cdedbid", "family_name", "given_names",
                            "statement_date")

# This is the specification for how the export for event fees should look like.
# The first five fields are a requirement by the reimport funtionality in
# `cdedb.frontend.event::batch_fees`, everything after that is currently
# ignored.
EVENT_EXPORT_FIELDS = ("amount", "cdedbid", "family_name", "given_names",
                       "statement_date", "persona_id_confidence_str",
                       "transaction_type", "transaction_type_confidence_str",
                       "event_name", "event_id_confidence_str")

# This is the specification for how the export to be used in our (old)
# Excel-based bookkeeping should look like.
EXCEL_EXPORT_FIELDS = ("statement_date", "amount_german", "cdedbid",
                       "family_name", "given_names", "category_old", "account",
                       "reference", "account_holder", "iban", "bic")

# These are the available delimiter available in a SEPA reference as per SEPA
# specification.
STATEMENT_REFERENCE_DELIMITERS = ["ABWE", "ABWA", "SVWZ", "OAMT", "COAM",
                                  "DEBT", "CRED", "MREF", "KREF", "EREF"]

# The are the parts of the reference, that we actually care about.
# First the general free text reference (SVWZ) used in most cases.
# Second we have the End-To-End reference, which would in theory be great for
# including structured data like DB-IDs, but most bank don't actually allow
# their users to specify this. Still we should check it, because some banks do.
# Note that the order should be the same as in the above SEPA-specification
# (which is reverse of the actual order in the reference).
STATEMENT_RELEVANT_REFERENCE_DELIMITERS = ["SVWZ", "EREF"]

# The following are some regEx definitions to match some expected
# postings and references:

# Match the Posting for the Account fee special case.
POSTING_ACCOUNT_FEE = re.compile(
    r"BUCHUNGSPOSTENGEBUEHREN|KONTOFUEHRUNGSGEBUEHREN", flags=re.I)

# Match the Posting for most (active) outgoing transactions.
POSTING_REFUND = re.compile(
    r"(Sammel-?)?(ü|ue|u|\s+)berweisung", flags=re.I)

# Match the Posting for a (incoming) direct debit.
POSTING_DIRECT_DEBIT = re.compile(
    r"SAMMELEINZ\.BASIS-LS", flags=re.I)

# Match a refund of an event participant fee.
REFERENCE_REFUND_EVENT_FEE = re.compile(
    r"Erstattung\s*(Teiln(ahme|ehmer)beitrag|(Erste|Zweite)\s*Rate|Anzahlung)",
    flags=re.I)

# Match a instructor refund.
REFERENCE_REFUND_INSTRUCTOR = re.compile(
    r"(Kursleiter|KL)[-\s]*Erstattung", flags=re.I)

# Match a refund for expenses.
REFERENCE_REFUND_EXPENSES = re.compile(
    r"Erstattung\s*Auslagen", flags=re.I)

# Match a reference indicating a membership fee.
REFERENCE_MEMBERSHIP = re.compile(
    r"Mitglied(schaft)?(sbeitrag)?|(Halb)?Jahresbeitrag", flags=re.I)

# Match a donation.
REFERENCE_DONATION = re.compile(
    r"Spende", flags=re.I)

# This matches the old reference used by external participants. We keep this
# in case some people keep using the old format, although we cannot extract a
# DB-ID to do the persona lookup.
STATEMENT_REFERENCE_EXTERNAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[-,.\s]*Extern", flags=re.I)
# This matches a correct DB-ID. Since this has to be the exact format we do not
# limit the length.
STATEMENT_DB_ID_EXACT = re.compile(
    r"DB-([0-9]+-[0-9X])", flags=re.I)
# This matches something very close to a correct DB-ID. Either the D or the B
# might be missing and there may be some additional whitespaces/delimiters.
STATEMENT_DB_ID_CLOSE = re.compile(
    r"(?:D\w|\wB)[-.\s]*([0-9][-.\s0-9]{0,9}[0-9X])", flags=re.I)
# Helper Patterns to remove the format markers from the DB-ID.
STATEMENT_DB_ID_REMOVE = (
    re.compile(r"DB", flags=re.I),
    re.compile(r"[-.\s]", flags=re.I),
)

# Minimum amount for us to consider a transaction an Event fee.
AMOUNT_MIN_EVENT_FEE = 40


BackendGetter = Callable[[int], CdEDBObject]


def dates_from_filename(filename: str) -> Tuple[datetime.date,
                                                Optional[datetime.date],
                                                datetime.datetime]:
    """
    Use the known format of the inputfile name to find out the date range.

    Example filename from BSF: "20200223_bis_20200229_20200229160818.csv"
    """
    try:
        start_str, sep, end_str, timestamp = filename.split("_", 3)
        if sep != "bis" or timestamp[-4:] != ".csv":
            raise ValueError()
        start = datetime.datetime.strptime(start_str, "%Y%m%d").date()
        end = datetime.datetime.strptime(end_str, "%Y%m%d").date()
        time = datetime.datetime.strptime(timestamp[:-4], "%Y%m%d%H%M%S")
    except ValueError:
        return now().date(), None, now()
    else:
        return start, end, time


def get_event_name_pattern(event: CdEDBObject) -> str:
    """
    Turn event_name into a re pattern that hopefully matches most
    variants of the event name.
    """
    y_p = re.compile(r"(\d\d)(\d\d)")
    replacements = [
        ("Pseudo", r"Pseudo"),  # For testing purposes.
        ("Cyber", r"Cyber"),
        ("Winter", r"Winter"),
        ("Sommer", r"Sommer"),
        ("Musik", r"Musik"),
        ("Herbst", r"Herbst"),
        ("Familien", r"Familien"),
        ("Pfingst(en)?", r"Pfingst(en)?"),
        ("Multi(nationale)?", r"Multi(nationale)?"),
        ("Nachhaltigkeits", r"(Nachhaltigkeits|N)"),
        ("(JuniorAka(demie)?|Nachtreffen|Velbert|NRW)",
         r"(JuniorAka(demie)?|Nachtreffen|Velbert|NRW)"),
        ("Studi(en)?info(rmations)?", r"Studi(en)?info(rmations)?"),
        ("Wochenende", r"(Wochenende)?"),
        ("Ski(freizeit)?", r"Ski(freizeit|fahrt)?"),
        ("Segeln", r"Segeln"),
        ("Seminar", "rSeminar"),
        ("Test", r"Test"),  # For testing purposes.
        ("Party", r"Party"),  # For testing purposes.
        ("Biomodels", r"Biomodels"),
        ("Academy", r"(Academy|Akademie)"),
        ("Aka(demie)?", r"Aka(demie)?"),
    ]
    result_parts = []
    search_title = event["title"]
    for pattern, replacement in replacements:
        result = re.search(pattern, search_title, flags=re.IGNORECASE)
        if result:
            search_title = re.sub(pattern, "", search_title, flags=re.I)
            result_parts.append(replacement)

    if result_parts:
        if event.get("begin") and event.get("end"):
            if event["begin"].year == event["end"].year:
                x = "(" + y_p.sub(r"(\1)?\2", str(event["begin"].year)) + ")?"
                result_parts.append(x)
            else:
                x = ("(" + y_p.sub(r"(\1)?\2", str(event["begin"].year)) + "/"
                     + y_p.sub(r"(\1)?\2", str(event["end"].year)) + ")?")
                result_parts.append(x)

        result_pattern = r"[-\s]*".join(result_parts)
    else:
        result_pattern = y_p.sub(r"(\1)?\2", event["title"])

    return result_pattern


def parse_amount(amount: str) -> decimal.Decimal:
    """Safely determine how to interpret a string as Decimal."""
    if not amount:
        raise ValueError("Could not parse.")
    try:
        ret = decimal.Decimal(amount)
    except decimal.InvalidOperation:
        amount = number_from_german(amount)
        try:
            ret = decimal.Decimal(amount)
        except decimal.InvalidOperation as e:
            raise ValueError("Could not parse.") from e
    return ret


def _reconstruct_cdedbid(db_id: str) -> Tuple[Optional[int], List[Error]]:
    """
    Uninlined code from `Transaction._find_cdedb_ids`.

    This takes the match to a DB-ID found in a reference, extracts the value
    of the persona_id and the checkdigit and then validates it.
    """

    value = db_id[:-1]
    for pattern in STATEMENT_DB_ID_REMOVE:
        value = re.sub(pattern, "", value)
    checkdigit = db_id[-1].upper()

    # Check the DB-ID
    p_id, p = validate_check(
        vtypes.CdedbID, "DB-{}-{}".format(value, checkdigit), argname="persona_id")

    return p_id, p


def number_to_german(number: Union[decimal.Decimal, int, str]) -> str:
    """Helper to convert an input to a number in german format."""
    if isinstance(number, decimal.Decimal):
        ret = "{:,.2f}".format(number)
    else:
        ret = str(number)
    ret = ret.replace(",", "_").replace(".", ",").replace("_", ".")
    return ret


def number_from_german(number: str) -> str:
    """Helper to convert a number in german format to english format."""
    if not isinstance(number, str):
        raise ValueError
    ret = number.replace(".", "_").replace(",", ".")
    return ret


def simplify_amount(amt: Union[decimal.Decimal, int, str]) -> str:
    """Helper to convert a number to german and strip decimal zeros."""
    return str(number_to_german(amt)).rstrip("0").rstrip(",")


@enum.unique
class ConfidenceLevel(enum.IntEnum):
    """Store the different Levels of Confidence about the prediction."""
    Null = 0
    Low = 1
    Medium = 2
    High = 3
    Full = 4

    @classmethod
    def destroy(cls) -> "ConfidenceLevel":
        return cls.Null

    def decrease(self, amount: int = 1) -> "ConfidenceLevel":
        if self.value - amount > self.__class__.Null.value:
            return self.__class__(self.value - amount)
        else:
            return self.__class__.Null

    def increase(self, amount: int = 1) -> "ConfidenceLevel":
        if self.value + amount < self.__class__.Full.value:
            return self.__class__(self.value + amount)
        else:
            return self.__class__.Full

    def __format__(self, format_spec: str) -> str:
        return str(self)


class Transaction:
    """Class to hold all transaction information,"""

    def __init__(self, data: CdEDBObject) -> None:
        """We reconstruct a Transaction from the validation form dict here."""
        # These fields are all very essential and need to be present.
        self.t_id = data["t_id"]
        self.account = data["account"]
        self.statement_date = data["statement_date"]
        self.amount = data["amount"]
        self.reference = data["reference"]
        ref_parts_default = {
                STATEMENT_RELEVANT_REFERENCE_DELIMITERS[0]: self.reference
            }
        self.reference_parts = data.get("reference_parts", ref_parts_default)
        self.account_holder = data["account_holder"]
        self.iban = data["iban"]
        self.bic = data.get("bic")
        self.posting = data["posting"]

        # We need the following fields, but we actually set them later.
        self.errors = data.get("errors", [])
        self.warnings = data.get("warnings", [])
        self.type: TransactionType
        self.type = data.get("transaction_type")  # type: ignore
        self.event_id = data.get("event_id")
        if data.get("cdedbid"):
            self.persona_id = data["cdedbid"]
        else:
            self.persona_id = data.get("persona_id")

        # We can be confident in our data if it was manually confirmed.
        cl = ConfidenceLevel
        if data.get("transaction_type_confirm"):
            self.type_confidence = cl.Full
        elif data.get("transaction_type_confidence"):
            self.type_confidence = cl(data["transaction_type_confidence"])
        else:
            self.type_confidence = cl.Null
        if data.get("persona_id_confirm"):
            self.persona_id_confidence = cl.Full
        elif data.get("persona_id_confidence"):
            self.persona_id_confidence = cl(data["persona_id_confidence"])
        else:
            self.persona_id_confidence = cl.Null
        if data.get("event_id_confirm"):
            self.event_id_confidence = cl.Full
        elif data.get("event_id_confidence"):
            self.event_id_confidence = cl(data["event_id_confidence"])
        else:
            self.event_id_confidence = cl.Null

    @classmethod
    def from_csv(cls, raw: CdEDBObject) -> "Transaction":
        """
        Convert DictReader line of BFS import to Transaction.

        :param raw: DictReader line of parse_statement input.
        """
        data = {}
        t_id = raw["id"] + 1
        data["t_id"] = t_id
        errors = []

        try:
            data["account"] = Accounts(int(raw["myAccNr"]))
        except ValueError:
            errors.append(
                ("MyAccNr",
                 ValueError("Unknown Account %(acc)s in Transaction %(t_id)s",
                            {"acc": raw["myAccNr"], "t_id": data["t_id"]})))
            data["account"] = Accounts.Unknown

        try:
            data["statement_date"] = datetime.datetime.strptime(
                raw["statementDate"], STATEMENT_INPUT_DATEFORMAT).date()
        except ValueError:
            errors.append(
                ("statementDate",
                 ValueError("Incorrect Date Format in Transaction %(t_id)s",
                            {"t_id": t_id})))
            data["statement_date"] = datetime.datetime.now().date()

        try:
            data["amount"] = parse_amount(raw["amount"])
        except ValueError as e:
            if "Could not parse." in e.args:
                errors.append(
                    ("amount",
                     ValueError("Could not parse Transaction Amount (%(amt)s)"
                                "for Transaction %(t_id)s",
                                {"amt": raw["amount"], "t_id": t_id})))
                data["amount"] = decimal.Decimal(0)
            else:
                raise
        else:
            # Check whether the original input can be reconstructed
            if raw["amount"] != number_to_german(data["amount"]):
                errors.append(
                    ("amount",
                     ValueError("Problem in line %(t_id)s: raw value "
                                "%(amt_r)s != parsed value %(amt_p)s.",
                                {"t_id": t_id,
                                 "amt_r": raw["amount"],
                                 "amt_p": number_to_german(data["amount"]),
                                 })))

        if STATEMENT_CSV_RESTKEY in raw:
            # The complete reference might be split over multiple columns.
            reference = "".join(raw[STATEMENT_CSV_RESTKEY])

            # Split the reference at all SEPA reference delimiters.
            reference_parts = {}
            for delimiter in STATEMENT_REFERENCE_DELIMITERS:
                pattern = re.compile(r"{}\+(.*)$".format(delimiter))
                result = pattern.findall(reference)
                if result:
                    reference_parts[delimiter] = result[0]
                    reference = pattern.sub("", reference)
            if reference_parts:
                # Construct a single reference string.
                data["reference"] = ";".join(
                    v for k, v in reference_parts.items()
                    if v and v != "NOTPROVIDED")
                # Save the actually useful parts separately.
                data["reference_parts"] = {
                    k: v for k, v in reference_parts.items()
                    if (v and v != "NOTPROVIDED"
                        and k in STATEMENT_RELEVANT_REFERENCE_DELIMITERS)}
            else:
                data["reference"] = "".join(raw[STATEMENT_CSV_RESTKEY])
                data["reference_parts"] = {
                    STATEMENT_RELEVANT_REFERENCE_DELIMITERS[0]:
                        data["reference"]
                }
        else:
            data["reference"] = ""
            data["reference_parts"] = {
                STATEMENT_RELEVANT_REFERENCE_DELIMITERS[0]: ""
            }

        data["account_holder"] = "".join([raw["accHolder"], raw["accHolder2"]])
        data["iban"] = raw["IBAN"]
        data["bic"] = raw["BIC"]

        data["posting"] = str(raw["posting"]).split(" ", 1)[0]

        data["errors"] = errors
        data["warnings"] = []

        return Transaction(data)

    def _find_cdedbids(self, confidence: ConfidenceLevel = ConfidenceLevel.Full
                       ) -> Dict[int, ConfidenceLevel]:
        """Find db_ids in a reference.

        Check the reference parts in order of relevancy.
        """
        ret: Dict[int, ConfidenceLevel] = {}
        patterns = [STATEMENT_DB_ID_EXACT, STATEMENT_DB_ID_CLOSE]
        orig_confidence = confidence
        for pattern in patterns:
            for kind in STATEMENT_RELEVANT_REFERENCE_DELIMITERS:
                if kind in self.reference_parts:
                    result = re.findall(pattern, self.reference_parts[kind])
                    if result:
                        for db_id in result:
                            p_id, p = _reconstruct_cdedbid(db_id)

                            if not p:
                                assert p_id is not None
                                if p_id not in ret:
                                    ret[p_id] = confidence

                confidence = confidence.decrease(1)

            confidence = orig_confidence.decrease(1)

        if len(ret) > 1:
            for p_id in ret:
                ret[p_id] = ret[p_id].decrease(2)

        return ret

    def analyze(self, events: CdEDBObjectMap,
                get_persona: BackendGetter) -> None:
        """
        Try to guess the TransactionType.

        Assign the best guess for transaction type to self.type
        and the confidence level to self.type_confidence.

        :param events: Current Events organized via DB.
        :param get_persona: Backend method to retrieve a persona via their id.
        """

        confidence = ConfidenceLevel.Full

        # Try to find and match an event.
        events = [
            (e, get_event_name_pattern(e))
            for e in xsorted(events.values(), key=EntitySorter.event, reverse=True)
        ]
        self._match_event(events)
        # Try to find and match cdedbids.
        self._match_members(get_persona)

        # Sanity check whether we know the Account.
        if self.account == Accounts.Unknown:
            self.type = TransactionType.Unknown
            confidence = confidence.destroy()
            self.type_confidence = confidence
            return

        # Handle all outgoing payments.
        if self.amount < 0:
            # Check outgoing active payments.
            if re.search(POSTING_REFUND, self.posting):

                # Special case for incoming (or outgoing) donations.
                if re.search(REFERENCE_DONATION, self.reference):
                    self.type = TransactionType.Donation
                    self.type_confidence = ConfidenceLevel.Full
                    return

                # Check for refund of participant fee:
                if re.search(REFERENCE_REFUND_EVENT_FEE, self.reference):
                    self.type = TransactionType.EventFeeRefund
                    self.type_confidence = confidence
                # Check for refund of instructor fee:
                elif re.search(REFERENCE_REFUND_INSTRUCTOR, self.reference):
                    self.type = TransactionType.InstructorRefund
                    self.type_confidence = confidence

                elif re.search(REFERENCE_REFUND_EXPENSES, self.reference):
                    if self.event_id:
                        self.type = TransactionType.EventExpenses
                    else:
                        self.type = TransactionType.Expenses
                    self.type_confidence = confidence

                else:
                    self.type = TransactionType.OtherPayment
                    self.type_confidence = confidence.decrease()

            # Special case for account fees.
            elif re.search(POSTING_ACCOUNT_FEE, self.posting):
                # Posting reserved for administrative fees found.
                self.type = TransactionType.AccountFee
                self.type_confidence = ConfidenceLevel.Full

            else:
                # There shouldn't be too many outgoing direct debits.
                self.type = TransactionType.OtherPayment
                self.type_confidence = confidence.decrease(2)

        elif self.amount > 0:

            # Check for incoming direct debits.
            if re.search(POSTING_DIRECT_DEBIT, self.posting):
                self.type = TransactionType.I25p
                self.type_confidence = confidence

            # Special case for incoming (or outgoing) donations.
            elif re.search(REFERENCE_DONATION, self.reference):
                self.type = TransactionType.Donation
                self.type_confidence = ConfidenceLevel.Full
                return

            # Look for Membership fees.
            elif re.search(REFERENCE_MEMBERSHIP, self.reference):
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence

            elif self.event_id and self.amount > AMOUNT_MIN_EVENT_FEE:
                self.type = TransactionType.EventFee
                self.type_confidence = confidence

            elif self.persona_id:
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence

            else:
                self.type = TransactionType.Other
                self.type_confidence = confidence.decrease(2)

        elif self.amount == 0:
            self.warnings.append(("amount", ValueError("Amount is zero.")))
            self.type = TransactionType.Other
            self.type_confidence = confidence.destroy()
            return

        else:
            raise RuntimeError("Impossible!")

    def _match_members(self, get_persona: BackendGetter) -> None:
        """
        Assign all matching members to self.member_matches.

        Assign the best match to self.best_member_match and it's Confidence to
        self.best_member_confidence.
        """

        members = []
        Member = collections.namedtuple("Member", ("persona_id", "confidence"))

        result = self._find_cdedbids()
        p: Error
        if result:
            if len(result) > 1:
                p = ("reference",
                     ValueError(n_(
                         "Multiple (%(count)s) DB-IDs found in line %(t_id)s."),
                         {"count": len(result), "t_id": self.t_id}))
                self.errors.append(p)

            for p_id, confidence in result.items():

                try:
                    persona = get_persona(p_id)
                except KeyError as e:
                    if p_id in e.args:
                        p = ("persona_id",
                             KeyError(n_("No Member with ID %(p_id)s found."),
                                      {"p_id": p_id}))
                        self.errors.append(p)
                    else:
                        p = ("persona_id", e)
                        self.errors.append(p)
                    continue
                else:
                    d_p = diacritic_patterns
                    given_names = persona.get('given_names', "")
                    gn_pattern = d_p(re.escape(given_names),
                                     two_way_replace=True)
                    family_name = persona.get('family_name', "")
                    fn_pattern = d_p(re.escape(family_name),
                                     two_way_replace=True)
                    try:
                        if not re.search(gn_pattern, self.reference,
                                         flags=re.IGNORECASE):
                            p = ("given_names",
                                 KeyError(
                                     n_("(%(p)s) not found in (%(ref)s)."),
                                     {"p": given_names, "ref": self.reference}))
                            self.warnings.append(p)
                            confidence = confidence.decrease()
                    except re.error as e:
                        p = ("given_names",
                             TypeError(
                                 n_("(%(p)s) is not a valid regEx (%(e)s)."),
                                 {"p": gn_pattern, "e": e}))
                        self.warnings.append(p)
                        confidence = confidence.decrease()
                    try:
                        if not re.search(fn_pattern, self.reference,
                                         flags=re.IGNORECASE):
                            p = ("family_name",
                                 KeyError(
                                     n_("(%(p)s) not found in (%(ref)s)."),
                                     {"p": family_name, "ref": self.reference}))
                            self.warnings.append(p)
                            confidence = confidence.decrease()
                    except re.error as e:
                        p = ("family_name",
                             TypeError(
                                 n_("(%(p)s) is not a valid regEx (%(e)s)."),
                                 {"p": fn_pattern, "e": e}))
                        self.warnings.append(p)
                        confidence = confidence.decrease()

                    members.append(Member(p_id, confidence))

        if members:
            # Find the member with the best confidence
            best_match = None
            best_confidence = ConfidenceLevel.Null

            for member in members:
                if member.confidence > best_confidence:
                    best_confidence = member.confidence
                    best_match = member

            if best_match and best_confidence > ConfidenceLevel.Null:
                self.persona_id = best_match.persona_id
                self.persona_id_confidence = best_confidence

    def _match_event(self, processed_events: List[Tuple[CdEDBObject, str]]) -> None:
        """
        Assign all matching Events to self.event_matches.

        :param processed_events: This should be a sorted list of events, and
            event name patterns derived from them.

        Assign the best match to self.best_event_match and
        the confidence of the best match to self.best_event_confidence.
        """

        confidence = ConfidenceLevel.Full

        Event = collections.namedtuple("Event", ("event_id", "confidence"))

        matched_events = []
        for e, pattern in processed_events:
            if e["is_archived"]:
                confidence = confidence.decrease()

            if re.search(re.escape(e["title"]), self.reference,
                         flags=re.IGNORECASE):
                # Exact match to Event Name
                matched_events.append(Event(e["id"], confidence))
                continue
            elif re.search(pattern, self.reference, flags=re.IGNORECASE):
                # Similar to Event Name
                matched_events.append(Event(e["id"], confidence.decrease()))

        if matched_events:
            best_match = None
            best_confidence = ConfidenceLevel.Null

            for event in matched_events:
                if event.confidence > best_confidence:
                    best_confidence = event.confidence
                    best_match = event

            if best_match and best_confidence > ConfidenceLevel.Null:
                self.event_id = best_match.event_id
                self.event_id_confidence = best_confidence

    def inspect(self, get_persona: BackendGetter) -> None:
        """Inspect transaction for problems."""
        cl = ConfidenceLevel

        if self.type and self.type_confidence \
                and self.type_confidence >= cl.High:
            pass
        elif not self.type or self.type == TransactionType.Unknown:
            self.errors.append(
                ("type", ValueError(n_(
                    "Could not determine transaction type."))))
        elif not self.type_confidence \
                or self.type_confidence < ConfidenceLevel.High:
            self.errors.append(
                ("transaction_type", ValueError(n_(
                    "Not confident about transaction type."))))

        if self.type.has_event:
            if self.event_id and self.event_id_confidence \
                    and self.event_id_confidence >= cl.High:
                pass
            elif self.event_id:
                self.errors.append(
                    ("event_id", ValueError(n_(
                        "Not confident about event match."))))
            else:
                self.errors.append(
                    ("event_id", ValueError(n_(
                        "Needs event match."))))

        if self.type.has_member:
            if self.persona_id and self.persona_id_confidence \
                    and self.persona_id_confidence >= cl.High:
                pass
            elif self.persona_id:
                self.errors.append(
                    ("cdedbid", ValueError(n_(
                        "Not confident about member match."))))
            else:
                self.errors.append(
                    ("cdedbid", ValueError(n_(
                        "Needs member match."))))

        p: Error
        if self.type == TransactionType.MembershipFee:
            if self.persona_id:
                try:
                    persona = get_persona(self.persona_id)
                except KeyError as e:
                    if self.persona_id in e.args:
                        p = ("persona_id",
                             KeyError(n_("No Member with ID %(p_id)s found."),
                                      {"p_id": self.persona_id}))
                        self.errors.append(p)
                    else:
                        p = ("persona_id", e)
                        self.errors.append(p)
                else:
                    if not persona.get("is_cde_realm"):
                        p = ("persona_id",
                             ValueError(n_("Not a CdE-Account.")))
                        self.errors.append(p)
            if self.amount > AMOUNT_MIN_EVENT_FEE:
                p = ("amount",
                     ValueError(n_(
                         "Amount higher than expected for membership fee.")))
                self.warnings.append(p)

        if self.type == TransactionType.EventFee:
            if self.amount < AMOUNT_MIN_EVENT_FEE:
                p = ("amount",
                     ValueError(n_(
                         "Amount lower than expected for event fee.")))
                self.warnings.append(p)

    @property
    def amount_german(self) -> str:
        """German way of writing the amount (without thousands separators)"""
        return number_to_german(self.amount)

    @property
    def amount_english(self) -> str:
        """English way of writing the amount."""
        return "{:.2f}".format(self.amount)

    @property
    def amount_simplified(self) -> str:
        """German way of writing the amount with simplified decimal places."""
        return simplify_amount(self.amount)

    def to_dict(self, get_persona: BackendGetter, get_event: BackendGetter
                ) -> CdEDBObject:
        """
        Convert the transaction to a dict to be displayed in the validation
        form or to be written to a csv file.

        This contains a whole bunsch of information, not all of which is needed.
        Rather the specific user can choose which of these fields to use.
        See also the export definitons at the top of this file.
        """

        ret = {
            "reference": self.reference,
            "account": self.account.value,
            "statement_date": self.statement_date.strftime(PARSE_OUTPUT_DATEFORMAT),
            "amount": self.amount_english,
            "amount_german": self.amount_german,
            "account_holder": self.account_holder,
            "posting": self.posting,
            "transaction_type": self.type,
            "category": self.type.to_string(),
            "transaction_type_confidence": self.type_confidence.value,
            "transaction_type_confidence_str": str(self.type_confidence),
            "cdedbid":
                cdedbid_filter(self.persona_id) if self.persona_id else None,
            "persona_id": self.persona_id,
            "persona_id_confidence":
                getattr(self.persona_id_confidence, "value", None),
            "persona_id_confidence_str": str(self.persona_id_confidence),
            "event_id": self.event_id,
            "event_id_confidence":
                getattr(self.event_id_confidence, "value", None),
            "event_id_confidence_str": str(self.event_id_confidence),
            "errors_str": ", ".join("{}: {}".format(
                key, e.args[0].format(**e.args[1]) if len(e.args) == 2 else e)
                                for key, e in self.errors),
            "warnings_str": ", ".join("{}: {}".format(
                key, w.args[0].format(**w.args[1]) if len(w.args) == 2 else w)
                                for key, w in self.warnings),
            "iban": self.iban,
            "bic": self.bic,
            "t_id": self.t_id,
            "given_names": "",
            "family_name": "",
            "event_name": "",
            "category_old": self.type.old(),
        }
        if self.persona_id:
            persona = get_persona(self.persona_id)
            ret.update({
                "given_names": persona["given_names"],
                "family_name": persona["family_name"],
            })
        if self.event_id:
            event = get_event(self.event_id)
            ret.update({
                "event_name": event["shortname"],
                "category": event["shortname"] + "-" + str(self.type),
                "category_old": event["shortname"],
            })
        ret["summary"] = json.dumps(ret)
        ret["errors"] = self.errors
        ret["warnings"] = self.warnings

        return ret
