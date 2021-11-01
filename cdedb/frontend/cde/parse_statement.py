"""Helpers for parsing bank statements"""

import collections
import datetime
import decimal
import json
import re
from typing import Callable, Dict, List, Optional, Tuple, Union

import cdedb.validationtypes as vtypes
from cdedb.common import (
    PARSE_OUTPUT_DATEFORMAT, Accounts, CdEDBObject, CdEDBObjectMap, ConfidenceLevel,
    EntitySorter, Error, TransactionType, diacritic_patterns, n_, now, xsorted,
)
from cdedb.filter import cdedbid_filter
from cdedb.frontend.common import inspect_validation as inspect

# This is the specification of keys in the file exported from the bank. This is
# configurable in the online banking interface, but changes will cause loss of
# backwards compatibility.
# The export contains these keys in the first row. This will be checked.
STATEMENT_CSV_ACCOUNT_KEY = "Kontonummer"
STATEMENT_CSV_STATEMENT_NR_KEY = "Auszugsnummer"
STATEMENT_CSV_STATEMENT_DATE_KEY = "Buchungsdatum"
STATEMENT_CSV_AMOUNT_KEY = "Betrag"
STATEMENT_CSV_ACCOUNT_HOLDER_KEYS = [
    "Auftraggeber-/Empfängername 1",
    "Auftraggeber-/Empfängername 2",
]
STATEMENT_CSV_IBAN_KEY = "Auftraggeber-/Empfängerkonto"
STATEMENT_CSV_BIC_KEY = "Auftraggeber-/Empfängerbank"
STATEMENT_CSV_REFERENCE_KEYS = [
    "Verwendungszweck " + str(i + 1) for i in range(14)
]
STATEMENT_CSV_OTHER_REFERENCE_KEYS = [
    "Ende-zu-Ende-Referenz",
]
STATEMENT_CSV_KREF_KEY = "Kundenreferenz (KREF)"
STATEMENT_CSV_POSTING_KEY = "Buchungstext"
STATEMENT_CSV_GVC_KEY = "Geschäftsvorfallcode"

STATEMENT_CSV_ALL_KEY = {
    STATEMENT_CSV_ACCOUNT_KEY,
    STATEMENT_CSV_STATEMENT_NR_KEY,
    STATEMENT_CSV_STATEMENT_DATE_KEY,
    STATEMENT_CSV_AMOUNT_KEY,
    *STATEMENT_CSV_ACCOUNT_HOLDER_KEYS,
    STATEMENT_CSV_IBAN_KEY,
    STATEMENT_CSV_BIC_KEY,
    STATEMENT_CSV_KREF_KEY,
    STATEMENT_CSV_POSTING_KEY,
    STATEMENT_CSV_GVC_KEY,
    *STATEMENT_CSV_OTHER_REFERENCE_KEYS,
    *STATEMENT_CSV_REFERENCE_KEYS,
}

# Map common GVCs to readable descriptions.
GVC_DESCRIPTIONS = {
    '088': 'Eilüberweisung',
    '105': 'Basislastschrift',
    '109': 'Rückruf Basislastschrift',
    '116': 'Überweisung',
    '152': 'Gutschrift Dauerauftrag',
    '153': 'Gutschrift Lohn/Gehalt/Rente',
    '159': 'Überweisung Retoure',
    '166': 'Gutschriftt',
    '169': 'Gutschrift Spende',
    '171': 'Einzug Basislastschrift',
    '191': 'Sammelüberweisung',
    '192': 'Sammeleinzug Basislastschrift',
    '201': 'Auslandsüberweisung',
    '808': 'Gebühren',
    '814': 'Verwahrentgelt',
}

# Specification for how the date is formatted in the input.
STATEMENT_INPUT_DATEFORMAT = "%d.%m.%Y"
REFERENCE_SEPARATOR = ";"
STATEMENT_REFERENCE_IGNORES = {"", "NOTPROVIDED"}

# This specifies the export fields for the (eventual) use with GnuCash.
# Since this is not yet currently in use this is very much subject to change.
GNUCASH_EXPORT_FIELDS = ("statement_date", "amount", "account_nr", "t_id",
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
                       "statement_date")

# This is the specification for how the export to be used in our (old)
# Excel-based bookkeeping should look like.
EXCEL_EXPORT_FIELDS = ("statement_date", "amount_german", "cdedbid",
                       "family_name", "given_names", "category_old", "account_nr",
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
POSTING_ACCOUNT_FEE = re.compile(r"^Gebühren$", flags=re.I)

# Match the Posting for most (active) outgoing transactions.
POSTING_REFUND = re.compile(r"^(Sammel)?überweisung$", flags=re.I)

# Match the Posting for a (incoming) direct debit.
POSTING_DIRECT_DEBIT = re.compile(r"^(Sammel)Einzug Basislastschrift$", flags=re.I)

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

# Match a reference indicating an event fee.
REFERENCE_EVENT_FEE = re.compile(
    r"Teiln(ahme|ehmer)[-\s]*(beitrag)?", flags=re.I)

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
    r"(?:D\w|\wB)[-./\s]*([0-9][-./\s0-9]{0,9}[0-9X])", flags=re.I)
# Helper Patterns to remove the format markers from the DB-ID.
STATEMENT_DB_ID_REMOVE = (
    re.compile(r"^DB", flags=re.I),
    re.compile(r"[-./\s]", flags=re.I),
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
        ("Tripel", r"Tripel"),  # For testing purposes.
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


def format_events(events: CdEDBObjectMap) -> List[Tuple[(CdEDBObject, str)]]:
    return [
        (e, get_event_name_pattern(e))
        for e in xsorted(events.values(), key=EntitySorter.event, reverse=True)
    ]


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

    db_id, p = inspect(str, db_id)
    if not db_id:
        return None, p

    value = db_id[:-1]
    for pattern in STATEMENT_DB_ID_REMOVE:
        value = re.sub(pattern, "", value)
    checkdigit = db_id[-1].upper()

    # Check the DB-ID
    p_id, p = inspect(vtypes.CdedbID, f"DB-{value}-{checkdigit}", argname="persona_id")

    return p_id, p


def number_to_german(number: Union[decimal.Decimal, int, str]) -> str:
    """Helper to convert an input to a number in german format."""
    if isinstance(number, decimal.Decimal):
        ret = "{:,.2f}".format(number)
    else:
        ret = str(number)
    ret = ret.replace(",", "").replace(".", ",")
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


class Transaction:
    """Class to hold all transaction information,"""

    def __init__(self, data: CdEDBObject, index: int = None) -> None:
        """We reconstruct a Transaction from the validation form dict here."""
        # Fix parameter suffix.
        if index is not None:
            data = {k.rstrip(str(index)): v for k, v in data.items()}

        # These fields are all very essential and need to be present.
        self.t_id = data["t_id"]
        self.account = data["account"]
        self.statement_nr = data["statement_nr"]
        self.statement_date = data["statement_date"]
        self.amount = data["amount"]
        self.reference = data["reference"]
        self.other_references = (data["other_references"] or "").split(
            REFERENCE_SEPARATOR)
        self.account_holder = data["account_holder"]
        self.iban = data["iban"]
        self.bic = data["bic"]
        self.posting = data["posting"]

        # We need the following fields, but we actually set them later.
        self.errors = data.get("errors", [])
        self.warnings = data.get("warnings", [])
        self.type: Optional[TransactionType] = data.get("type")
        self._event_id = data.get("event_id")
        self.event: Optional[CdEDBObject] = None
        self._persona_id = data.get("cdedbid")
        self.persona: Optional[CdEDBObject] = None

        # We can be confident in our data if it was manually confirmed.
        cl = ConfidenceLevel
        if data.get("type_confirm"):
            self.type_confidence = cl.Full
        elif val := data.get("type_confidence"):
            self.type_confidence = cl(val)
        else:
            self.type_confidence = cl.Null
        if data.get("persona_confirm"):
            self.persona_confidence = cl.Full
        elif val := data.get("persona_confidence"):
            self.persona_confidence = cl(val)
        else:
            self.persona_confidence = cl.Null
        if data.get("event_confirm"):
            self.event_confidence = cl.Full
        elif val := data.get("event_confidence"):
            self.event_confidence = cl(val)
        else:
            self.event_confidence = cl.Null

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
            data["account"] = Accounts(int(raw[STATEMENT_CSV_ACCOUNT_KEY]))
        except ValueError:
            errors.append(
                ("account",
                 ValueError("Unknown Account %(acc)s in Transaction %(t_id)s",
                            {"acc": raw[STATEMENT_CSV_ACCOUNT_KEY],
                             "t_id": data["t_id"]})))
            data["account"] = Accounts.Unknown

        data["statement_nr"] = int(raw[STATEMENT_CSV_STATEMENT_NR_KEY])
        try:
            data["statement_date"] = datetime.datetime.strptime(
                raw[STATEMENT_CSV_STATEMENT_DATE_KEY], STATEMENT_INPUT_DATEFORMAT
            ).date()
        except ValueError:
            errors.append((STATEMENT_CSV_STATEMENT_DATE_KEY,
                           ValueError("Incorrect Date Format in Transaction %(t_id)s",
                                      {"t_id": t_id})))
            data["statement_date"] = datetime.datetime.now().date()

        try:
            data["amount"] = parse_amount(raw[STATEMENT_CSV_AMOUNT_KEY])
        except ValueError as e:
            if "Could not parse." in e.args:
                errors.append(
                    (STATEMENT_CSV_AMOUNT_KEY,
                     ValueError("Could not parse Transaction Amount (%(amt)s)"
                                "for Transaction %(t_id)s",
                                {"amt": raw[STATEMENT_CSV_AMOUNT_KEY], "t_id": t_id})))
                data["amount"] = decimal.Decimal(0)
            else:
                raise
        else:
            # Check whether the original input can be reconstructed
            raw_amount = raw[STATEMENT_CSV_AMOUNT_KEY]
            reconstructed_amount = number_to_german(data["amount"])
            if raw_amount != reconstructed_amount:
                errors.append(
                    ("amount",
                     ValueError("Problem in line %(t_id)s: raw value "
                                "%(amt_r)s != parsed value %(amt_p)s.",
                                {"t_id": t_id,
                                 "amt_r": raw_amount,
                                 "amt_p": reconstructed_amount,
                                 })))

        data["reference"] = "".join(
            raw[k].strip("'") for k in STATEMENT_CSV_REFERENCE_KEYS)
        data["other_references"] = REFERENCE_SEPARATOR.join(
            raw[k].strip("'") for k in STATEMENT_CSV_OTHER_REFERENCE_KEYS
            if raw[k] not in STATEMENT_REFERENCE_IGNORES)

        data["account_holder"] = "".join(
            raw[k] for k in STATEMENT_CSV_ACCOUNT_HOLDER_KEYS)
        data["iban"] = raw[STATEMENT_CSV_IBAN_KEY]
        data["bic"] = raw[STATEMENT_CSV_BIC_KEY]

        data["posting"] = GVC_DESCRIPTIONS.get(
            raw[STATEMENT_CSV_GVC_KEY], raw[STATEMENT_CSV_POSTING_KEY])

        data["errors"] = errors
        data["warnings"] = []

        return Transaction(data)

    @property
    def all_references(self) -> List[str]:
        return [self.reference, *self.other_references]

    @property
    def full_reference(self) -> str:
        return REFERENCE_SEPARATOR.join(self.all_references)

    @staticmethod
    def get_request_params(index: int = None, *, hidden_only: bool = False
                           ) -> vtypes.TypeMapping:
        """Returns a specification for the parameters that should be extracted from
        the request to create a `Transaction` object.

        The return should be used with `request_extractor`. The data thusly extracted
        can be used to call `Transaction.__init__`. The appended suffix can be passed
        there too, where it will automatically be stripped away.

        :param hidden_only: If True, only return the keys used for hidden form inputs.
        """
        suffix = "" if index is None else str(index)
        ret: vtypes.TypeMapping = {
            f"t_id{suffix}": vtypes.ID,
            f"account{suffix}": Accounts,
            f"statement_nr{suffix}": vtypes.ID,
            f"statement_date{suffix}": datetime.date,
            f"amount{suffix}": decimal.Decimal,
            f"reference{suffix}": Optional[str],  # type: ignore[dict-item]
            f"other_references{suffix}": Optional[str],  # type: ignore[dict-item]
            f"account_holder{suffix}": Optional[str],  # type: ignore[dict-item]
            f"iban{suffix}": Optional[vtypes.IBAN],  # type: ignore[dict-item]
            f"bic{suffix}": Optional[str],  # type: ignore[dict-item]
            f"posting{suffix}": str,
            f"type_confidence{suffix}": ConfidenceLevel,
            f"persona_confidence{suffix}": ConfidenceLevel,
            f"event_confidence{suffix}": ConfidenceLevel,
        }
        if not hidden_only:
            ret = dict(**ret, **{  # type: ignore[arg-type]
                f"type{suffix}": TransactionType,
                f"type_confirm{suffix}": bool,
                f"cdedbid{suffix}": Optional[vtypes.CdedbID],
                f"persona_confirm{suffix}": bool,
                f"event_id{suffix}": Optional[vtypes.ID],
                f"event_confirm{suffix}": bool,
            })
        return ret

    def _find_cdedbids(self, confidence: ConfidenceLevel = ConfidenceLevel.Full
                       ) -> Dict[int, ConfidenceLevel]:
        """Find db_ids in a reference.

        Check the reference parts in order of relevancy.
        """
        ret: Dict[int, ConfidenceLevel] = {}
        patterns = [STATEMENT_DB_ID_EXACT, STATEMENT_DB_ID_CLOSE]
        orig_confidence = confidence
        for pattern in patterns:
            for ref in self.all_references:
                if result := re.findall(pattern, ref):
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

    def analyze(self, events: CdEDBObjectMap, get_persona: BackendGetter) -> None:
        """
        Try to guess the TransactionType.

        Assign the best guess for transaction type to self.type
        and the confidence level to self.type_confidence.

        :param events: Current Events organized via DB.
        :param get_persona: Backend method to retrieve a persona via their id.
        """

        confidence = ConfidenceLevel.Full

        # Try to find and match an event.
        self._match_event(events)
        # Try to find and match cdedbids.
        self._match_members(get_persona)

        # Return early, if we already matched a type.
        if self.type:
            return

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
                if re.search(REFERENCE_DONATION, self.full_reference):
                    self.type = TransactionType.Donation
                    self.type_confidence = ConfidenceLevel.Full
                    return

                # Check for refund of participant fee:
                if re.search(REFERENCE_REFUND_EVENT_FEE, self.full_reference):
                    self.type = TransactionType.EventFeeRefund
                    self.type_confidence = confidence
                # Check for refund of instructor fee:
                elif re.search(REFERENCE_REFUND_INSTRUCTOR, self.full_reference):
                    self.type = TransactionType.InstructorRefund
                    self.type_confidence = confidence

                elif re.search(REFERENCE_REFUND_EXPENSES, self.full_reference):
                    if self.event:
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
            elif re.search(REFERENCE_DONATION, self.full_reference):
                self.type = TransactionType.Donation
                self.type_confidence = ConfidenceLevel.Full
                return

            # Look for Membership fees.
            elif re.search(REFERENCE_MEMBERSHIP, self.full_reference):
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence

            elif self.event and self.amount > AMOUNT_MIN_EVENT_FEE:
                self.type = TransactionType.EventFee
                self.type_confidence = confidence

            # Look for event fee without event match.
            elif self.amount > AMOUNT_MIN_EVENT_FEE and re.search(REFERENCE_EVENT_FEE,
                                                                  self.full_reference):
                self.type = TransactionType.EventFee
                self.type_confidence = confidence.decrease()

            elif self.persona:
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

    def get_data(self, *, get_persona: BackendGetter = None,
                 events: CdEDBObjectMap = None) -> None:
        """Try retrieving the persona and event belonging to this transaction."""
        if self._persona_id and get_persona:
            try:
                self.persona = get_persona(self._persona_id)
            except KeyError:
                self._persona_id = None
        if self._event_id and events:
            try:
                self.event = events[self._event_id]
            except KeyError:
                self._event_id = None

    def _match_members(self, get_persona: BackendGetter) -> None:
        """
        Assign all matching members to self.member_matches.

        Assign the best match to self.best_member_match and it's Confidence to
        self.best_member_confidence.
        """
        self.get_data(get_persona=get_persona)
        # Return early, if we already matched a persona.
        if self.persona:
            return

        members = []
        Member = collections.namedtuple("Member", ("persona", "confidence"))

        if result := self._find_cdedbids():
            if len(result) > 1:
                self.errors.append(
                    ("reference",
                     ValueError(
                         n_("Multiple (%(count)s) DB-IDs found in line %(t_id)s."),
                         {"count": len(result), "t_id": self.t_id})))
        else:
            return

        for p_id, confidence in result.items():
            # Check that the persona exists.
            try:
                persona = get_persona(p_id)
            except KeyError as e:
                if p_id in e.args:
                    p = ("persona", KeyError(n_("No Member with ID %(p_id)s found."),
                                                {"p_id": p_id}))
                    self.errors.append(p)
                else:
                    p = ("persona", e)
                    self.errors.append(p)
                continue

            # TODO improve pattern construction.
            d_p = diacritic_patterns
            # Search reference for given_names.
            given_names = persona['given_names']
            gn_pattern = d_p(re.escape(given_names), two_way_replace=True)
            try:
                if not re.search(gn_pattern, self.full_reference, flags=re.I):
                    self.warnings.append(
                        ("given_names", KeyError(n_("(%(p)s) not found in reference."),
                                                 {"p": given_names})))
                    confidence = confidence.decrease()
            except re.error as e:
                self.warnings.append(
                    ("given_names",
                     TypeError(n_("(%(p)s) is not a valid regEx (%(e)s)."),
                               {"p": gn_pattern, "e": e})))
                confidence = confidence.decrease()
            # Search reference for family_name.
            family_name = persona['family_name']
            fn_pattern = d_p(re.escape(family_name), two_way_replace=True)
            try:
                if not re.search(fn_pattern, self.full_reference, flags=re.I):
                    self.warnings.append(
                        ("family_name", KeyError(n_("(%(p)s) not found in reference."),
                                                 {"p": family_name})))
                    confidence = confidence.decrease()
            except re.error as e:
                self.warnings.append(
                    ("family_name",
                     TypeError(n_("(%(p)s) is not a valid regEx (%(e)s)."),
                               {"p": fn_pattern, "e": e})))
                confidence = confidence.decrease()

            members.append(Member(persona, confidence))

        if members:
            # Find the member with the best confidence
            best_match = None
            best_confidence = ConfidenceLevel.Null

            for member in members:
                if member.confidence > best_confidence:
                    best_confidence = member.confidence
                    best_match = member

            if best_match and best_confidence > ConfidenceLevel.Null:
                self.persona_confidence = best_confidence
                self.persona = best_match.persona

    def _match_event(self, events: CdEDBObjectMap) -> None:
        """
        Assign all matching Events to self.event_matches.

        :param events: Collection of events as returned by `EventBackend.get_events`.

        Assign the best match to self.best_event_match and
        the confidence of the best match to self.best_event_confidence.
        """
        self.get_data(events=events)
        # Return early if we already matched an event.
        if self.event:
            return

        confidence = ConfidenceLevel.Full

        Event = collections.namedtuple("Event", ("event", "confidence"))

        matched_events = []
        for e, pattern in format_events(events):
            if e["is_archived"]:
                confidence = confidence.decrease()

            if re.search(re.escape(e["title"]), self.reference, flags=re.IGNORECASE):
                # Exact match to Event Name
                matched_events.append(Event(e, confidence))
                continue
            elif re.search(pattern, self.reference, flags=re.IGNORECASE):
                # Similar to Event Name
                matched_events.append(Event(e, confidence.decrease()))

        if matched_events:
            best_match = None
            best_confidence = ConfidenceLevel.Null

            for event in matched_events:
                if event.confidence > best_confidence:
                    best_confidence = event.confidence
                    best_match = event

            if best_match and best_confidence > ConfidenceLevel.Null:
                self.event_confidence = best_confidence
                self.event = best_match.event

    def inspect(self) -> None:
        """Inspect transaction for problems."""
        cutoff = ConfidenceLevel.High
        if not self.type:
            self.type = TransactionType.Unknown

        # First: Check whether we are confident about the transaction type.
        if self.type and self.type_confidence and self.type_confidence >= cutoff:
            pass
        elif not self.type or self.type == TransactionType.Unknown:
            self.errors.append(
                ("type", ValueError(n_("Could not determine transaction type."))))
        elif not self.type_confidence or self.type_confidence < cutoff:
            self.errors.append(
                ("type", ValueError(n_(
                    "Not confident about transaction type."))))

        # Second: If the type needs an event, check the event.
        if self.type.has_event:
            if self.event:
                if self.event_confidence and self.event_confidence >= cutoff:
                    pass
                else:
                    self.errors.append(
                        ("event", ValueError(n_(
                            "Not confident about event match."))))
            else:
                self.errors.append(
                    ("event", ValueError(n_("Needs event match."))))

            if self.type == TransactionType.EventFee:
                if self.amount < AMOUNT_MIN_EVENT_FEE:
                    self.warnings.append(
                        ("amount", ValueError(n_(
                            "Amount lower than expected for event fee."))))

        # Third: If the type needs a persona, check the persona.
        if self.type.has_member:
            if self.persona:
                if self.persona_confidence and self.persona_confidence >= cutoff:
                    pass
                else:
                    self.errors.append(
                        ("cdedbid", ValueError(n_(
                            "Not confident about member match."))))
            else:
                self.errors.append(
                    ("cdedbid", ValueError(n_("Needs member match."))))

            if self.type == TransactionType.MembershipFee:
                if self.persona and not self.persona['is_cde_realm']:
                    self.errors.append(
                        ("persona", ValueError(n_("Not a CdE-Account."))))
                if self.amount > AMOUNT_MIN_EVENT_FEE:
                    self.warnings.append(
                        ("amount", ValueError(n_(
                            "Amount higher than expected for membership fee."))))

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

    def to_dict(self) -> CdEDBObject:
        """
        Convert the transaction to a dict to be displayed in the validation
        form or to be written to a csv file.

        This contains a whole bunsch of information, not all of which is needed.
        Rather the specific user can choose which of these fields to use.
        See also the export definitons at the top of this file.
        """

        if not self.type:
            raise RuntimeError(n_("This transaction has not been analyzed yet."))

        ret = {
            "reference": self.reference,
            "other_references": REFERENCE_SEPARATOR.join(self.other_references),
            "account": self.account,
            "account_nr": self.account.value,
            "statement_nr": self.statement_nr,
            "statement_date": self.statement_date.strftime(PARSE_OUTPUT_DATEFORMAT),
            "amount": self.amount_english,
            "amount_german": self.amount_german,
            "account_holder": self.account_holder,
            "posting": self.posting,
            "type": self.type,
            "category": ((self.event['shortname'] + '-') if self.event else '')
                        + self.type.display_str(),
            "type_confidence": self.type_confidence,
            "cdedbid": cdedbid_filter(self.persona['id']) if self.persona else None,
            "persona_confidence": self.persona_confidence,
            "given_names": self.persona['given_names'] if self.persona else "",
            "family_name": self.persona['family_name'] if self.persona else "",
            "event_id": self.event['id'] if self.event else None,
            "event_confidence": self.event_confidence,
            "event_name": self.event['shortname'] if self.event else None,
            "errors_str": ", ".join("{}: {}".format(
                key, e.args[0].format(**e.args[1]) if len(e.args) == 2 else e)
                                    for key, e in self.errors),
            "warnings_str": ", ".join("{}: {}".format(
                key, w.args[0].format(**w.args[1]) if len(w.args) == 2 else w)
                                      for key, w in self.warnings),
            "iban": self.iban,
            "bic": self.bic,
            "t_id": self.t_id,
            "category_old": self.event['shortname'] if self.event else self.type.old(),
        }
        ret["summary"] = json.dumps(ret)
        ret["persona"] = self.persona
        ret["event"] = self.event
        ret["errors"] = self.errors
        ret["warnings"] = self.warnings

        return ret
