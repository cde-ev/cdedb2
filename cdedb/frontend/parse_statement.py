import datetime
import enum
import re
from cdedb.common import diacritic_patterns
from cdedb.frontend.common import cdedbid_filter
import cdedb.validation as validate

STATEMENT_CSV_FIELDS = ("myBLZ", "myAccNr", "statementNr",
                        "statementDate", "currency", "valuta", "date",
                        "currency2", "amount", "textKey",
                        "customerReference", "instituteReference",
                        "transaction", "posting", "primanota",
                        "textKey2", "BLZ", "KontoNr", "BIC", "IBAN",
                        "accHolder", "accHolder2")
MEMBERSHIP_FEE_FIELDS = ("amount_export", "db_id", "family_name", "given_names",
                         "date", "member_confidence", "db_id_value",
                         "reference", "account_holder", "problems")
EVENT_FEE_FIELDS = ("amount_export", "db_id", "family_name", "given_names",
                    "date", "member_confidence", "event_shortname",
                    "event_confidence", "reference", "account_holder",
                    "problems")
OTHER_TRANSACTION_FIELDS = ("account", "amount_export", "db_id", "family_name",
                            "given_names", "date", "member_confidence",
                            "posting", "type", "type_confidence", "reference",
                            "account_holder", "iban", "bic", "problems")
ACCOUNT_FIELDS = ("date", "amount", "db_id", "name_or_holder",
                  "name_or_ref", "category", "account", "reference",
                  "account_holder", "iban", "bic")
STATEMENT_REFERENCE_DELIMITERS = ["ABWE", "ABWA", "SVWZ", "OAMT", "COAM",
                                  "DEBT", "CRED", "MREF", "KREF", "EREF"]
STATEMENT_RELEVANT_REFERENCE_DELIMITERS = ["SVWZ", "EREF"]
STATEMENT_CSV_RESTKEY = "reference"
STATEMENT_GIVEN_NAMES_UNKNOWN = "VORNAME"
STATEMENT_FAMILY_NAME_UNKNOWN = "NACHNAME"
STATEMENT_DATEFORMAT = "%d.%m.%y"
STATEMENT_DB_ID_EXTERN = "DB-EXTERN"
STATEMENT_DB_ID_UNKNOWN = "DB-UNKNOWN"
STATEMENT_POSTING_OTHER = re.compile(
    r"BUCHUNGSPOSTENGEBUEHREN|KONTOFUEHRUNGSGEBUEHREN", flags=re.I)
STATEMENT_POSTING_REFUND = re.compile(
    r"(Sammel-?)?(ü|ue|u| )berweisung", flags=re.I)
STATEMENT_REFERENCE_REFUND = re.compile(
    r"(R(ü|ue|u|\s)ck)?erstattung", flags=re.I)
STATEMENT_REFERENCE_MEMBERSHIP = re.compile(
    r"Mitglied(schaft)?(sbeitrag)?|(Halb)?Jahresbeitrag", flags=re.I)
STATEMENT_REFERENCE_EXTERNAL = re.compile(
    r"\d{4}-\d{2}-\d{2}[-,.\s]*Extern", flags=re.I)
STATEMENT_DB_ID_PATTERN = re.compile(
    r"(DB-[0-9]+-[0-9X])", flags=re.I)
STATEMENT_DB_ID_SIMILAR = re.compile(
    r"([-.\s]*[0-9]+[-.\s0-9]*[-.\s][0-9X])", flags=re.I)
STATEMENT_DB_ID_REMOVE = (
    re.compile(r"DB", flags=re.I),
    re.compile(r"[-.\s]", flags=re.I),
)


def get_event_name_pattern(event):
    """
    Turn event_name into a re pattern that hopefully matches most
    variants of the event name.

    :type event: {str: object}
    :rtype: str
    """
    y_p = re.compile(r"(\d\d)(\d\d)")
    replacements = [
        ("Pseudo", r"Pseudo"),
        ("Winter", r"Winter"),
        ("Sommer", r"Sommer"),
        ("Musik", r"Musik"),
        ("Herbst", r"Herbst"),
        ("Familien", r"Familien"),
        ("Pfingst(en)?", r"Pfingst(en)?"),
        ("Multi(nationale)?", r"Multi(nationale)?"),
        ("Nachhaltigkeits", r"(Nachhaltigkeits|N)"),
        ("(NRW|JuniorAka(demie)?|Velbert|Nachtreffen)",
         r"(NRW|JuniorAka(demie)?|Velbert|Nachtreffen)"),
        ("Studi(en)?info(rmations)?", r"Studi(en)?info(rmations)?"),
        ("Wochenende", r"(Wochenende)?"),
        ("Ski(freizeit)?", r"Ski(freizeit|fahrt)?"),
        ("Segeln", r"Segeln"),
        ("Seminar", "rSeminar"),
        ("Test", r"Test"),
        ("Party", r"Party"),
        ("Biomodels", r"Biomodels"),
        ("Academy", r"(Academy|Akademie)"),
        ("Aka(demie)?", r"Aka(demie)?"),
    ]
    result_parts = []
    for key, replacement in replacements:
        if re.search(key, event["title"], flags=re.IGNORECASE):
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


def parse_cents(amount):
    """
    Parse amount into cents, trying different decimal separators.
    
    :param amount: amount in Euros as a string with either "," or "." as decimal
        seperator.
    :type amount: str
    :return: the amount in cents.
    :rtype: int
    """
    if amount:
        cents = int(amount.replace(",", "").replace(".", ""))
        if "," in amount:
            if len(amount) >= 3 and amount[-3] == ",":
                # Comma seems to be decimal separator with 2 decimal digits
                pass
            elif len(amount) >= 2 and amount[-2] == ",":
                # Comma seems to be decimal separator, with decimal digit
                cents *= 10
            else:
                # Comma seems to be a grouping delimiter
                if "." in amount:
                    if len(amount) >= 3 and amount[-3] == ".":
                        # Point seems to be decimal separator
                        # with 2 decimal digits
                        pass
                    elif len(amount) >= 2 and amount[-2] == ".":
                        # Point seems to be decimal separator
                        # with only 1 decimal digit
                        cents *= 10
                    else:
                        # Point seems to also be a grouping delimiter
                        cents *= 100
                else:
                    # There seems to be no decimal separator
                    cents *= 100

        elif "." in amount:
            if len(amount) >= 3 and amount[-3] == ".":
                # Point seems to be decimal separator
                # with 2 decimal digits
                pass
            elif len(amount) >= 2 and amount[-2] == ".":
                # Point seems to be decimal separator
                # with only 1 decimal digit
                cents *= 10
            else:
                # Point seems to also be a grouping delimiter
                cents *= 100
        else:
            # There seems to be no decimal separator
            cents *= 100

        return cents
    else:
        raise ValueError("Could not parse")


def print_delimiters(number):
    """
    Convert number to String with thousands separators.
    
    This is used to check whether the input was parsed correctly.
    
    :type number: int
    :return: input as String with thousands separators
    :rtype: str
    """
    number = str(number)
    if len(number) <= 3:
        return number
    result = ""
    for i, x in enumerate(number):
        if i % 3 == len(number) % 3:
            result += "."
        result += x
    return result


def escape(s):
    """
    Custom escape function, because re.escape does not work as expected.
    
    We simply remove all re special characters since we don't expect them to
    show up in names.
    
    :param s: String to make re safe
    :type s: str
    :return: String without re special characters
    :rtype: str
    """

    special_characters = r".^$*+?{}()[]\|"
    for x in special_characters:
        s = s.replace(x, "")
    return s


@enum.unique
class Accounts(enum.Enum):
    """Store the existing CdE Accounts."""
    Account0 = 8068900
    Account1 = 8068901
    Account2 = 8068902
    # Fallback if Account is none of the above
    Unknown = 0

    def __str__(self):
        return str(self.value)


@enum.unique
class TransactionType(enum.Enum):
    """Store the type of a Transactions."""
    MembershipFee = 1
    EventFee = 2
    Other = 3
    Refund = 4
    Unknown = 10

    def __str__(self):
        """
        Return a string represantation for the TransactionType.
        
        These are _not_ translated on purpose, so that the generated download
        is the same regardless of locale.
        """
        to_string = {TransactionType.MembershipFee.name: "Mitgliedsbeitrag",
                     TransactionType.EventFee.name: "Teilnehmerbeitrag",
                     TransactionType.Other.name: "Sonstiges",
                     TransactionType.Refund.name: "Erstattung",
                     TransactionType.Unknown.name: "Unbekannt",
                     }
        if self.name in to_string:
            return to_string[self.name]
        else:
            return repr(self)


@enum.unique
class ConfidenceLevel(enum.IntEnum):
    """Store the different Levels of Confidence about the prediction."""
    Null = 0
    Low = 1
    Medium = 2
    High = 3
    Full = 4

    @staticmethod
    def destroy():
        return __class__.Null

    def decrease(self, amount=1):
        if self.value - amount > __class__.Null.value:
            return __class__(self.value - amount)
        else:
            return __class__.Null

    def increase(self, amount=1):
        if self.value + amount < __class__.Full.value:
            return __class__(self.value + amount)
        else:
            return __class__.Full

    def __format__(self, format_spec):
        return str(self)


class Member:
    """Helper class to store the relevant member data."""

    def __init__(self, given_names, family_name, db_id, confidence):
        self.given_names = given_names
        self.family_name = family_name
        self.db_id = db_id
        self.confidence = confidence

    def __str__(self):
        return "({} ({}), {} ({}), {}, {})".format(
            self.given_names,
            diacritic_patterns(escape(self.given_names), True),
            self.family_name,
            diacritic_patterns(escape(self.family_name), True),
            self.db_id, self.confidence)

    def __format__(self, format_spec):
        return str(self)


class Event:
    """Helper class to store the relevant event data."""

    def __init__(self, title, shortname, confidence):
        self.title = title
        self.shortname = shortname
        self.confidence = confidence

    def __str__(self):
        return "({}, {}, {})".format(self.title,
                                     self.shortname,
                                     self.confidence)

    def __format__(self, format_spec):
        return str(self)


class Transaction:
    """Class to hold all transaction information,"""

    def __init__(self, raw):
        """
        Convert DictReader line into a Transaction.
        
        :param raw: DictReader line of parse_statement input.
        :type raw: {str: str}
        """
        self.t_id = raw["id"] + 1
        problems = []

        try:
            self.account = Accounts(int(raw["myAccNr"]))
        except ValueError:
            problems.append(
                ("MyAccNr",
                 ValueError("Unknown Account %(acc)s in Transaction %(t_id)s",
                            {"acc": raw["myAccNr"], "t_id": self.t_id})))
            self.account = Accounts.Unknown

        try:
            self.statement_date = datetime.datetime.strptime(
                raw["statementDate"], STATEMENT_DATEFORMAT).date()
        except ValueError:
            problems.append(
                ("statementDate",
                 ValueError("Incorrect Date Format in Transaction %(t_id)s",
                            {"t_id": self.t_id})))
            self.statement_date = datetime.datetime.now().date()

        try:
            self.cents = parse_cents(raw["amount"])
        except ValueError as e:
            if e.args == ("Could not parse",):
                problems.append(
                    ("amount",
                     ValueError("Could not parse Transaction Amount (%(amt)s)"
                                "for Transaction %(t_id)s",
                                {"amt": raw["amount"], "t_id": self.t_id})))
                self.cents = 0
            else:
                raise
        else:
            if raw["amount"] not in (self.amount_simplified, self.amount):
                # Check whether the original input can be reconstructed
                problems.append(
                    ("amount",
                     ValueError("Problem in line %(t_id)s: "
                                "%(amt_s)s != %(amt)s. Cents: %(cents)s",
                                {"t_id": self.t_id,
                                 "amt_s": self.amount_simplified,
                                 "amt": raw["amount"],
                                 "cents": self.cents})))

        if STATEMENT_CSV_RESTKEY in raw:
            reference = "".join(raw[STATEMENT_CSV_RESTKEY])
            reference_parts = []
            for delimiter in STATEMENT_REFERENCE_DELIMITERS:
                pattern = re.compile(r"{}\+(.*)$".format(delimiter))
                result = pattern.findall(reference)
                if result:
                    if delimiter in STATEMENT_RELEVANT_REFERENCE_DELIMITERS:
                        reference_parts.extend(result)
                    reference = pattern.sub("", reference)
            if reference_parts:
                self.reference = "; ".join(part for part in reference_parts
                                           if part and part != "NOTPROVIDED")
            else:
                self.reference = "".join(raw[STATEMENT_CSV_RESTKEY])
        else:
            self.reference = ""

        self.account_holder = "".join([raw["accHolder"],
                                       raw["accHolder2"]])
        self.iban = raw["IBAN"]
        self.bic = raw["BIC"]

        self.posting = str(raw["posting"]).split(" ", 1)[0]

        # Guess the transaction type
        self.type = TransactionType.Unknown
        self.type_confidence = None

        # Get all matching members and the best match
        self.member_matches = []
        self.best_member_match = None
        self.best_member_confidence = None

        # Get all matching events and the best match
        self.event_matches = []
        self.best_event_match = None
        self.best_event_confidence = None

        self.problems = problems

    def guess_type(self, event_names):
        """
        Try to guess the TransactionType.

        Assign the best guess for transaction type to self.type
        and the confidence level to self.type_confidence.
        
        :param event_names: Current Event Names and RegEx Patternstrings for
            these Names.
        :type event_names: {str: str}
        """

        confidence = ConfidenceLevel.Full

        if self.account == Accounts.Account0:
            if re.search(STATEMENT_DB_ID_PATTERN, self.reference):
                # Correct ID found, so we assume this is a
                # Membership Fee Transaction
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_DB_ID_SIMILAR, self.reference):
                # Semi-Correct ID found, so we decrease confidence
                # but still assume this to be a Membership Fee
                self.type = TransactionType.MembershipFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_POSTING_OTHER, self.posting):
                # Posting reserved for administrative fees found
                self.type = TransactionType.Other
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_POSTING_REFUND, self.posting):
                # Posting used for refunds found
                if re.search(STATEMENT_REFERENCE_REFUND, self.reference):
                    # Reference mentions a refund
                    self.type = TransactionType.Refund
                    self.type_confidence = confidence
                    return

                else:
                    # Reference doesn't mention a refund so this
                    # probably is a different kind of payment
                    self.type = TransactionType.Other
                    confidence = confidence.decrease()
                    self.type_confidence = confidence
                    return

            elif re.search(STATEMENT_REFERENCE_MEMBERSHIP, self.reference):
                # No DB-ID found, but membership mentioned in reference
                self.type = TransactionType.MembershipFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return

            else:
                # No other Options left so we assume this to be
                # something else, but with lower confidence
                self.type = TransactionType.Other
                confidence = confidence.decrease(2)
                self.type_confidence = confidence
                return

        elif self.account == Accounts.Account1:
            if re.search(STATEMENT_DB_ID_PATTERN, self.reference):
                # Correct DB-ID found, so we assume this to be an
                # Event Fee
                self.type = TransactionType.EventFee
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_DB_ID_SIMILAR, self.reference):
                # Semi-Correct DB-ID found, so we decrease confidence
                # but still assume this is an Event Fee
                self.type = TransactionType.EventFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_POSTING_OTHER, self.posting):
                # Reserved Posting for administrative fees
                self.type = TransactionType.Other
                self.type_confidence = confidence
                return

            elif re.search(STATEMENT_POSTING_REFUND, self.posting):
                # Posting used for refunds found
                if re.search(STATEMENT_REFERENCE_REFUND, self.reference):
                    # Refund mentioned in reference
                    self.type = TransactionType.Refund
                    self.type_confidence = confidence
                    return
                else:
                    # Reference doesn't mention refund, so this
                    # probably is a different kind of payment
                    self.type = TransactionType.Other
                    confidence = confidence.decrease()
                    self.type_confidence = confidence
                    return

            else:
                # Iterate through known Event names and their variations
                for event_name, value in event_names.items():
                    pattern, shortname = value
                    if re.search(escape(event_name), self.reference,
                                 flags=re.IGNORECASE):
                        self.type = TransactionType.EventFee
                        confidence = confidence.decrease()
                        self.type_confidence = confidence
                        return
                    if re.search(pattern, self.reference,
                                 flags=re.IGNORECASE):
                        self.type = TransactionType.EventFee
                        confidence = confidence.decrease(2)
                        self.type_confidence = confidence
                        return

                # No other Options left, so we assume this to be
                # something else, but with lower confidence.
                self.type = TransactionType.Other
                confidence = confidence.decrease(2)
                self.type_confidence = confidence
                return

        elif self.account == Accounts.Account2:
            # This account should not be in use
            self.type = TransactionType.Other
            confidence = confidence.decrease(3)
            self.type_confidence = confidence
            return

        else:
            # This Transaction uses an unknown account
            self.type = TransactionType.Unknown
            confidence = confidence.destroy()
            self.type_confidence = confidence
            return

    def match_member(self, rs, get_persona):
        """
        Assing all matching members to self.member_matches.
        
        Assign the best match to self.best_member_match and it's Confidence to
        self.best_member_confidence.
        
        
        :type rs: :py:class:`cdedb.common.RequestState`
        :param get_persona: The function to be called to retrieve a persona
            via their id.
        """

        members = []
        confidence = ConfidenceLevel.Full
        if self.type not in {TransactionType.MembershipFee,
                             TransactionType.EventFee}:
            return

        result = re.findall(STATEMENT_DB_ID_PATTERN, self.reference)
        result2 = re.findall(STATEMENT_DB_ID_SIMILAR, self.reference)
        if not result and result2:
            confidence = confidence.decrease()
            result = result2

        if result:
            if len(result) > 1:
                # Multiple DB-IDs found, where only one is expected.
                p = ("reference",
                     ValueError("Multiple (%(count)s) DB-IDs found "
                                "in line %(t_id)s!",
                                {"count": len(result),
                                 "t_id": self.t_id}))
                self.problems.append(p)
                confidence = confidence.decrease(2)

            for db_id in result:
                # Clone ConfidenceLevel for every result
                temp_confidence = ConfidenceLevel(
                    confidence.value)

                # Reconstruct DB-ID
                value = db_id[:-1]
                for pattern in STATEMENT_DB_ID_REMOVE:
                    value = re.sub(pattern, "", value)
                checkdigit = db_id[-1].upper()

                # Check the DB-ID
                p_id, p = validate.check_cdedbid(
                    "DB-{}-{}".format(value, checkdigit), "persona_id")
                self.problems.extend(p)

                persona_id = cdedbid_filter(p_id)

                if not p:
                    try:
                        persona = get_persona(rs, p_id)
                    except KeyError as e:
                        if p_id in e.args:
                            p = ("persona_id",
                                 KeyError("No Member with ID %(p_id)s found.",
                                          {"p_id": p_id}))
                            self.problems.append(p)
                        else:
                            p = ("persona_id", e)
                            self.problems.append(p)

                        members.append(Member(STATEMENT_GIVEN_NAMES_UNKNOWN,
                                              STATEMENT_FAMILY_NAME_UNKNOWN,
                                              persona_id,
                                              temp_confidence.decrease(2)))
                        continue
                    else:
                        given_names = persona.get('given_names', "")
                        d_p = diacritic_patterns
                        gn_pattern = d_p(escape(given_names),
                                         two_way_replace=True)
                        family_name = persona.get('family_name', "")
                        fn_pattern = d_p(escape(family_name),
                                         two_way_replace=True)
                        try:
                            if not re.search(gn_pattern, self.reference,
                                             flags=re.IGNORECASE):
                                p = ("given_names",
                                     KeyError(
                                         "(%(gnp)s) not found in (%(ref)s)",
                                         {"gnp": given_names,
                                          "ref": self.reference}))
                                self.problems.append(p)
                                temp_confidence = temp_confidence.decrease()
                        except re.error as e:
                            p = ("given_names",
                                 TypeError(
                                     "(%(gnp)s) is not a valid regEx (%(e)s)",
                                     {"gnp": gn_pattern, "e": e}))
                            self.problems.append(p)
                            temp_confidence = temp_confidence.decrease()
                        try:
                            if not re.search(fn_pattern, self.reference,
                                             flags=re.IGNORECASE):
                                p = ("family_name",
                                     KeyError(
                                         "(%(fnp)s) not found in (%(ref)s)",
                                         {"fnp": family_name,
                                          "ref": self.reference}))
                                self.problems.append(p)
                                temp_confidence = temp_confidence.decrease()
                        except re.error as e:
                            p = ("family_name",
                                 TypeError(
                                     "(%(fnp)s) is not a valid regEx (%(e)s)",
                                     {"fnp": fn_pattern, "e": e}))
                            self.problems.append(p)
                            temp_confidence = temp_confidence.decrease()

                        members.append(Member(given_names,
                                              family_name,
                                              persona_id,
                                              temp_confidence))

                else:
                    p = ("persona_id",
                         ValueError("Invalid checkdigit: %(db_id)s",
                                    {"db_id": db_id}))
                    self.problems.append(p)

        elif self.type in {TransactionType.EventFee}:
            result = re.search(STATEMENT_REFERENCE_EXTERNAL, self.reference)
            if result:
                # Reference matches External Event Fee
                members.append(Member(STATEMENT_GIVEN_NAMES_UNKNOWN,
                                      STATEMENT_FAMILY_NAME_UNKNOWN,
                                      STATEMENT_DB_ID_EXTERN,
                                      confidence.decrease()))
            else:
                members.append(Member(STATEMENT_GIVEN_NAMES_UNKNOWN,
                                      STATEMENT_FAMILY_NAME_UNKNOWN,
                                      STATEMENT_DB_ID_UNKNOWN,
                                      ConfidenceLevel.Low))
                self.problems.append(("reference",
                                      ValueError("No DB-ID found.")))
        else:
            m = Member(STATEMENT_GIVEN_NAMES_UNKNOWN,
                       STATEMENT_FAMILY_NAME_UNKNOWN,
                       STATEMENT_DB_ID_UNKNOWN,
                       ConfidenceLevel.Low)
            members.append(m)
            self.problems.append(("reference",
                                  ValueError("No DB-ID found.")))

        if members:
            # Save all matched members
            self.member_matches = members

            # Find the member with the best confidence
            best_match = None
            best_confidence = ConfidenceLevel.Null

            for member in members:
                if member.confidence > best_confidence:
                    best_confidence = member.confidence
                    best_match = member

            if best_confidence > ConfidenceLevel.Null:
                self.best_member_match = best_match
                self.best_member_confidence = best_confidence

    def match_event(self, event_names):
        """
        Assign all matching Events to self.event_matches.

        Assign the best match to self.best_event_match and
        the confidence of the best match to self.best_event_confidence.
        
        :param event_names: Current Event Names and RegEx Patternstrings for
            these Names.
        :type event_names: {str: (str, str)}
        """

        if self.type in {TransactionType.EventFee}:
            events = []
            confidence = ConfidenceLevel.Full

            for event_name, value in event_names.items():
                pattern, shortname = value

                result = re.search(escape(event_name), self.reference,
                                   flags=re.IGNORECASE)
                if result:
                    # Exact match to Event Name
                    events.append(Event(event_name,
                                        shortname,
                                        confidence))
                    continue
                else:
                    result = re.search(pattern, self.reference,
                                       flags=re.IGNORECASE)
                    if result:
                        # Similar to Event Name
                        events.append(Event(event_name,
                                            shortname,
                                            confidence.decrease()))

            if events:
                self.event_matches = events

                best_match = None
                best_confidence = ConfidenceLevel.Null

                for event in events:
                    if event.confidence > best_confidence:
                        best_confidence = event.confidence
                        best_match = event

                if best_confidence > ConfidenceLevel.Null:
                    self.best_event_match = best_match
                    self.best_event_confidence = best_confidence

    def to_dict(self):
        """
        Convert all Transaction data to a dict to be used by csv.DictWriter.
        
        :rtype: {str: str}
        """
        ret = {
            "account": self.account,
            "amount_export": self.amount_export,
            "amount": self.amount,
            "date": self.statement_date.strftime(STATEMENT_DATEFORMAT),
            "db_id": self.best_member_match.db_id
            if self.best_member_match else STATEMENT_DB_ID_UNKNOWN,
            "db_id_value": self.best_member_match.db_id.split("-")[1] if
            self.best_member_match else "",
            "name_or_holder": self.best_member_match.family_name
            if self.best_member_match and self.best_member_confidence > 1
            else self.account_holder,
            "name_or_ref": self.best_member_match.given_names
            if self.best_member_match and self.best_member_confidence > 1
            else self.reference,
            "given_names": self.best_member_match.given_names
            if self.best_member_match else "",
            "family_name": self.best_member_match.family_name
            if self.best_member_match else "",
            "member_confidence": self.best_member_confidence,
            "event": self.best_event_match.title
            if self.best_event_match else "",
            "event_shortname": self.best_event_match.shortname
            if self.best_event_match else "",
            "event_confidence": str(self.best_event_confidence),
            "reference": self.reference,
            "posting": self.posting,
            "account_holder": self.account_holder,
            "iban": self.iban,
            "bic": self.bic,
            "type": self.type,
            "category": self.best_event_match.shortname.replace("-", " ")
            if self.type == TransactionType.EventFee and self.best_event_match
            else self.type,
            "type_confidence": self.type_confidence,
            "problems": ", ".join(["{}: {}".format(
                     key, error.args[0] % error.args[1]
                     if len(error.args) == 2 else error)
                     for key, error in self.problems]),
        }
        return ret

    @property
    def abs_cents(self):
        return abs(self.cents)

    @property
    def amount(self):
        """German way of writing the amount."""
        return "{}{},{}{}".format("-" if self.cents < 0 else "",
                                  print_delimiters(self.abs_cents // 100),
                                  (self.abs_cents % 100) // 10,
                                  self.abs_cents % 10)

    @property
    def amount_export(self):
        """English way of writing the amount (without thousands separators)"""
        return self.amount.replace(".", "").replace(",", ".")

    @property
    def amount_simplified(self):
        """German way of writing the amount with simplified decimal places."""
        if self.cents % 100 == 0:
            return "{}{}".format("-" if self.cents < 0 else "",
                                 print_delimiters(
                                     self.abs_cents // 100))
        elif self.cents % 10 == 0:
            return "{}{},{}".format("-" if self.cents < 0 else "",
                                    print_delimiters(
                                        self.abs_cents // 100),
                                    (self.abs_cents % 100) // 10)
        else:
            return "{}{},{}".format("-" if self.cents < 0 else "",
                                    print_delimiters(
                                        self.abs_cents // 100),
                                    self.abs_cents % 100)

    def __str__(self):
        return "\n\t".join(
            ["Transaction {}:".format(self.t_id),
             "Account:\t\t {}".format(self.account),
             "Statement-Date:\t {}".format(self.statement_date),
             "Amount:\t\t\t {}".format(self.amount),
             "Account Holder:\t {}".format(self.account_holder),
             "IBAN:\t\t\t {}".format(self.iban),
             "BIC:\t\t\t {}".format(self.bic),
             "Reference:\t\t {}".format(self.reference),
             "Posting:\t\t {}".format(self.posting),
             "Type:\t\t\t {}".format(self.type),
             "Type-Conf.:\t\t {}".format(self.type_confidence),
             "Member:\t\t\t {}".format(str(self.best_member_match)),
             "Member-Conf.:\t {}".format(self.best_member_confidence),
             "Event:\t\t\t {}".format(str(self.best_event_match)),
             "Events:\t\t\t {}".format(self.event_matches),
             "Event-Conf.:\t {}".format(self.best_event_confidence),
             "Problems:\t\t {}".format(
                 ["{}: {}".format(
                     key, error.args[0] % error.args[1]
                     if len(error.args) == 2 else error)
                     for key, error in self.problems]),
             ])
