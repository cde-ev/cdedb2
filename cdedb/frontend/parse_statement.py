import datetime
import enum
import re
from cdedb.common import n_, diacritic_patterns
from cdedb.frontend.common import cdedbid_filter
import cdedb.validation as validate

STATEMENT_CSV_FIELDS = ("myBLZ", "myAccNr", "statementNr",
                        "statementDate", "currency", "valuta", "date",
                        "currency2", "amount", "textKey",
                        "customerReference", "instituteReference",
                        "transaction", "posting", "primanota",
                        "textKey2", "BLZ", "KontoNr", "BIC", "IBAN",
                        "accHolder", "accHolder2")
STATEMENT_CSV_RESTKEY = "reference"
STATEMENT_GIVEN_NAMES_UNKNOWN = "VORNAME"
STATEMENT_FAMILY_NAME_UNKNOWN = "NACHNAME"
STATEMENT_DATEFORMAT = "%d.%m.%y"
STATEMENT_POSTING_OTHER = "BUCHUNGSPOSTENGEBUEHREN|" \
                          "KONTOFUEHRUNGSGEBUEHREN"
STATEMENT_POSTING_REFUND = "(Sammel-?)?(ü|ue|u| )berweisung"
STATEMENT_REFERENCE_REFUND = "R(ü|ue|u| )ckerstattung"
STATEMENT_REFERENCE_MEMBERSHIP = "Mitglied(schaft)?(sbeitrag)?|" \
                                 "(Halb)?Jahresbeitrag"
STATEMENT_REFERENCE_EXTERNAL = "\d\d\d\d-\d\d-\d\d[,-. ]*Extern"
STATEMENT_DB_ID_PATTERN = "(DB-[0-9]+-[0-9X])"
STATEMENT_DB_ID_SIMILAR = "(DB[-. ]*[0-9]+[-. 0-9]*[0-9X])"


def get_event_name_pattern(event):
    """
    Turn event_name into a re pattern that hopefully matches most
    variants of the event name.

    :type event: {str: object}
    :rtype: str
    """
    y_p = re.compile("(\d\d)(\d\d)")
    replacements = [
        ("Pseudo", "Pseudo"),
        ("Winter", "Winter"),
        ("Sommer", "Sommer"),
        ("Musik", "Musik"),
        ("Herbst", "Herbst"),
        ("Familien", "Familien"),
        ("Pfingst(en)?", "Pfingst(en)?"),
        ("Multi(nationale)?", "Multi(nationale)?"),
        ("Nachhaltigkeits", "(Nachhaltigkeits|N)"),
        ("(NRW|JuniorAka(demie)?|Velbert|Nachtreffen)",
         "(NRW|JuniorAka(demie)?|Velbert|Nachtreffen)"),
        ("Studi(en)?info(rmations)?", "Studi(en)?info(rmations)?"),
        ("Wochenende", "(Wochenende)?"),
        ("Ski(freizeit)?", "Ski(freizeit)?"),
        ("Segeln", "Segeln"),
        ("Seminar", "Seminar"),
        ("Test", "Test"),
        ("Party", "Party"),
        ("Biomodels", "Biomodels"),
        ("Academy", "(Academy|Akademie)"),
        ("Aka(demie)?", "Aka(demie)?"),
        ]
    result_parts = []
    for key, replacement in replacements:
        if re.search(key, event["title"], flags=re.IGNORECASE):
            result_parts.append(replacement)
    
    if event.get("begin") and event.get("end"):
        if event["begin"].year == event["end"].year:
            result_parts.append(y_p.sub("(\\1)?\\2", str(event["begin"].year)))
        else:
            x = "(" + y_p.sub("(\\1)?\\2", str(event["begin"].year)) + "/" + \
                y_p.sub("(\\1)?\\2", str(event["end"].year)) + ")?"
            result_parts.append(x)
    
    if result_parts:
        result_pattern = "[-\s]*".join(result_parts)
    else:
        result_pattern = y_p.sub("(\\1)?\\2", event["title"])
    
    return result_pattern


def parse_cents(amount):
    """Parse amount into cents, trying different decimal separators."""
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
    number = str(number)
    if len(number) <= 3:
        return number
    result = ""
    for i, x in enumerate(number):
        if i % 3 == len(number) % 3:
            result += "."
        result += x
    return result


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
        to_string = {TransactionType.MembershipFee.name: n_("Mitgliedsbeitrag"),
                     TransactionType.EventFee.name: n_("Teilnehmerbeitrag"),
                     TransactionType.Other.name: n_("Sonstiges"),
                     TransactionType.Refund.name: n_("Rückerstattung"),
                     TransactionType.Unknown.name: n_("Unbekannt"), }
        if self.name in to_string:
            return to_string[self.name]
        else:
            return repr(self)


@enum.unique
class ConfidenceLevel(enum.IntEnum):
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
    
    def __init__(self, given_names, family_name, db_id):
        self.given_names = given_names
        self.family_name = family_name
        self.db_id = db_id
    
    def __str__(self):
        return "({}, {}, {})".format(self.given_names,
                                     self.family_name,
                                     self.db_id)


class Transaction:
    """Class to hold all transaction information,"""
    
    def __init__(self, raw):
        self.t_id = raw["id"] + 1
        problems = []
        
        try:
            self.account = Accounts(int(raw["myAccNr"]))
        except ValueError:
            problems.append("Unknown Account {} in Transaction {}"
                            .format(raw["myAccNr"], raw["id"]))
            self.account = Accounts.Unknown
        
        try:
            self.statement_date = datetime.datetime.strptime(
                raw["statementDate"], STATEMENT_DATEFORMAT).date()
        except ValueError:
            problems.append("Incorrect Date Format in Transaction {}"
                            .format(raw["id"]))
            self.statement_date = datetime.datetime.now().date()
        
        try:
            self.cents = parse_cents(raw["amount"])
        except ValueError as e:
            if e.args == ("Could not parse",):
                problems.append("Could not parse Transaction Amount "
                                "for Transaction {}".format(raw["id"]))
                self.cents = 0
            else:
                raise
        else:
            if self.amount_simplified != raw["amount"] \
                    and self.amount != raw["amount"]:
                # Check whether the original input can be reconstructed
                problems.append(
                    "Problem in line {}: {} != {}. Cents: {}"
                        .format(self.t_id,
                                self.amount_simplified,
                                raw["amount"], self.cents))
        
        if STATEMENT_CSV_RESTKEY in raw:
            self.reference = "".join(raw[STATEMENT_CSV_RESTKEY])
            if "SVWZ+" in self.reference:
                # Only use the part after "SVWZ+"
                self.reference = self.reference.split("SVWZ+", 1)[-1]
            elif "EREF+" in self.reference or "KREF+" in self.reference:
                # There seems to be no useful reference
                self.reference = ""
        else:
            self.reference = ""
        
        self.account_holder = "".join([raw["accHolder"],
                                       raw["accHolder2"]])
        
        self.posting = str(raw["posting"]).upper()
        
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
        """
        
        confidence = ConfidenceLevel["Full"]
        
        if self.account == Accounts.Account0:
            if re.search(STATEMENT_DB_ID_PATTERN, self.reference,
                         flags=re.IGNORECASE):
                # Correct ID found, so we assume this is a
                # Membership Fee Transaction
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_DB_ID_SIMILAR, self.reference,
                           flags=re.IGNORECASE):
                # Semi-Correct ID found, so we decrease confidence
                # but still assume this to be a Membership Fee
                self.type = TransactionType.MembershipFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_POSTING_OTHER, self.posting,
                           flags=re.IGNORECASE):
                # Posting reserved for administrative fees found
                self.type = TransactionType.Other
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_POSTING_REFUND, self.posting,
                           flags=re.IGNORECASE):
                # Posting used for refunds found
                if re.search(STATEMENT_REFERENCE_REFUND, self.reference,
                             flags=re.IGNORECASE):
                    # Reference mentions a refund
                    self.type = TransactionType.Refund
                    self.type_confidence = confidence
                    return self.type, confidence
                
                else:
                    # Reference doesn't mention a refund so this
                    # probably is a different kind of payment
                    self.type = TransactionType.Other
                    confidence = confidence.decrease()
                    self.type_confidence = confidence
                    return self.type, confidence
            
            elif re.search(STATEMENT_REFERENCE_MEMBERSHIP,
                           self.reference, flags=re.IGNORECASE):
                # No DB-ID found, but membership mentioned in reference
                self.type = TransactionType.MembershipFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return self.type, confidence
            
            else:
                # No other Options left so we assume this to be
                # something else, but with lower confidence
                self.type = TransactionType.Other
                confidence = confidence.decrease(2)
                self.type_confidence = confidence
                return self.type, confidence
        
        elif self.account == Accounts.Account1:
            if re.search(STATEMENT_DB_ID_PATTERN, self.reference,
                         flags=re.IGNORECASE):
                # Correct DB-ID found, so we assume this to be an
                # Event Fee
                self.type = TransactionType.EventFee
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_DB_ID_SIMILAR, self.reference,
                           flags=re.IGNORECASE):
                # Semi-Correct DB-ID found, so we decrease confidence
                # but still assume this is an Event Fee
                self.type = TransactionType.EventFee
                confidence = confidence.decrease()
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_POSTING_OTHER, self.posting,
                           flags=re.IGNORECASE):
                # Reserved Posting for administrative fees
                self.type = TransactionType.Other
                self.type_confidence = confidence
                return self.type, confidence
            
            elif re.search(STATEMENT_POSTING_REFUND, self.posting,
                           flags=re.IGNORECASE):
                # Posting used for refunds found
                if re.search(STATEMENT_REFERENCE_REFUND, self.reference,
                             flags=re.IGNORECASE):
                    # Refund mentioned in reference
                    self.type = TransactionType.Refund
                    self.type_confidence = confidence
                    return self.type, confidence
                else:
                    # Reference doesn't mention refund, so this
                    # probably is a different kind of payment
                    self.type = TransactionType.Other
                    confidence = confidence.decrease()
                    self.type_confidence = confidence
                    return self.type, confidence
            
            else:
                # Iterate through known Event names and their variations
                for event_name, pattern in event_names.items():
                    if re.search(event_name.upper(), self.reference,
                                 flags=re.IGNORECASE):
                        self.type = TransactionType.EventFee
                        confidence = confidence.decrease()
                        self.type_confidence = confidence
                        return self.type, confidence
                    if re.search(pattern, self.reference,
                                 flags=re.IGNORECASE):
                        self.type = TransactionType.EventFee
                        confidence = confidence.decrease(2)
                        self.type_confidence = confidence
                        return self.type, confidence
                
                # No other Options left, so we assume this to be
                # something else, but with lower confidence.
                self.type = TransactionType.Other
                confidence = confidence.decrease(2)
                self.type_confidence = confidence
                return self.type, confidence
        
        elif self.account == Accounts.Account2:
            # This account should not be in use
            self.type = TransactionType.Other
            confidence = confidence.decrease(3)
            self.type_confidence = confidence
            return self.type, confidence
        
        else:
            # This Transaction uses an unknown account
            self.type = TransactionType.Unknown
            confidence = confidence.destroy()
            self.type_confidence = confidence
            return self.type, confidence
    
    def match_member(self, rs, get_persona):
        """Add all matching members to self.member_matches."""
        
        members = []
        confidence = ConfidenceLevel["Full"]
        if self.type in {TransactionType.MembershipFee,
                         TransactionType.EventFee}:
            
            result = re.search(STATEMENT_DB_ID_PATTERN, self.reference,
                               flags=re.IGNORECASE)
            result2 = re.search(STATEMENT_DB_ID_SIMILAR, self.reference,
                                flags=re.IGNORECASE)
            if not result and result2:
                confidence = confidence.decrease()
                result = result2
            
            if result:
                if len(result.groups()) > 1:
                    # Multiple DB-IDs found, where only one is expected.
                    p = "Multiple ({}) DB-IDs found in line {}!"
                    p = p.format(len(result.groups()), self.t_id)
                    self.problems.append(p)
                    confidence = confidence.decrease()
                
                for db_id in result.groups():
                    # Clone ConfidenceLevel for every result
                    temp_confidence = ConfidenceLevel(
                        confidence.value)
                    
                    # Reconstruct DB-ID
                    value = int(db_id[:-1].replace("DB", "")
                                .replace(" ", "-").replace("-", ""))
                    checkdigit = db_id[-1]
                    
                    p_id, p = validate.check_cdedbid(
                        "DB-{}-{}".format(value, checkdigit), "persona_id")
                    persona_id = cdedbid_filter(p_id)
                    self.problems.extend(p)
                    
                    if not p:
                        try:
                            persona = get_persona(rs, p_id)
                        except KeyError as e:
                            if value in e.args:
                                p = "No Member with ID {} found.".format(
                                    p_id)
                                self.problems.append(p)
                            else:
                                self.problems.append(str((e, db_id)))
                            temp_confidence = temp_confidence.decrease(
                                2)
                            m = (Member(STATEMENT_GIVEN_NAMES_UNKNOWN,
                                        STATEMENT_FAMILY_NAME_UNKNOWN,
                                        persona_id),
                                 temp_confidence)
                            members.append(m)
                            continue
                        else:
                            given_names = persona.get('given_names', "")
                            d_p = diacritic_patterns
                            gn_pattern = d_p(given_names,
                                             two_way_replace=True)
                            family_name = persona.get('family_name', "")
                            fn_pattern = d_p(family_name,
                                             two_way_replace=True)
                            
                            if not re.search(gn_pattern, self.reference,
                                             flags=re.IGNORECASE):
                                p = "({}) not found in ({})". \
                                    format(gn_pattern, self.reference)
                                self.problems.append(p)
                                temp_confidence = \
                                    temp_confidence.decrease()
                            if not re.search(fn_pattern, self.reference,
                                             flags=re.IGNORECASE):
                                p = "({}) not found in ({})". \
                                    format(fn_pattern, self.reference)
                                self.problems.append(p)
                                temp_confidence = \
                                    temp_confidence.decrease()

                            members.append((Member(given_names,
                                                   family_name,
                                                   persona_id),
                                            temp_confidence))
                    
                    else:
                        p = "Invalid checkdigit: {}".format(db_id)
                        self.problems.append(p)
        
        elif self.type in {TransactionType.EventFee}:
            result = re.search(STATEMENT_REFERENCE_EXTERNAL,
                               self.reference, flags=re.IGNORECASE)
            if result:
                # Reference matches External Event Fee
                confidence = confidence.decrease()
                members.append((Member("Extern",
                                       "Extern",
                                       "DB-EXTERN"),
                                confidence))
        
        if members:
            # Save all matched members
            self.member_matches = members
            
            # Find the member with the best confidence
            best_match = None
            best_confidence = ConfidenceLevel["Null"]
            
            for member in members:
                if member[1] > best_confidence:
                    best_confidence = member[1]
                    best_match = member[0]
            
            if best_confidence not in {ConfidenceLevel.Null}:
                self.best_member_match = best_match
                self.best_member_confidence = best_confidence
                return best_match, best_confidence
            
            return None, None
        
        return None, None
    
    def match_event(self, event_names):
        """
        Add all matching Events to self.event_matches.

        Add the best match to self.best_event_match and
        the confidence of the best match to self.best_event_confidence.
        """
        
        if self.type in {TransactionType.EventFee}:
            events = []
            confidence = ConfidenceLevel["Full"]
            
            for event_name, pattern in event_names.items():
                # Clone confidence for every event
                temp_confidence = ConfidenceLevel(
                    confidence.value)
                
                result = re.search(event_name.upper(), self.reference,
                                   flags=re.IGNORECASE)
                if result:
                    # Exact match to Event Name
                    events.append((event_name, temp_confidence))
                    continue
                else:
                    result = re.search(pattern, self.reference,
                                       flags=re.IGNORECASE)
                    if result:
                        # Similar to Event Name
                        temp_confidence = temp_confidence.decrease()
                        events.append((event_name, temp_confidence))
            
            if events:
                self.event_matches = events
                
                best_match = None
                best_confidence = ConfidenceLevel["Null"]
                
                for event in events:
                    if event[1] > best_confidence:
                        best_confidence = event[1]
                        best_match = event[0]
                
                if best_confidence not in {ConfidenceLevel.Null}:
                    self.best_event_match = best_match
                    self.best_event_confidence = best_confidence
                    return best_match, best_confidence
                
                return None, None
        
        return None, None
    
    @property
    def abs_cents(self):
        return abs(self.cents)
    
    @property
    def amount(self):
        return "{}{},{}{}".format("-" if self.cents < 0 else "",
                                  print_delimiters(
                                      self.abs_cents // 100),
                                  (self.abs_cents % 100) // 10,
                                  self.abs_cents % 10)
    
    @property
    def amount_export(self):
        return self.amount.replace(".", "").replace(",", ".")
    
    @property
    def amount_simplified(self):
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
             "Reference:\t\t {}".format(self.reference),
             "Posting:\t\t {}".format(self.posting),
             "Type:\t\t\t {}".format(self.type),
             "Type-Conf.:\t\t {}".format(self.type_confidence),
             "Member:\t\t\t {}".format(str(self.best_member_match)),
             "Member-Conf.:\t {}".format(self.best_member_confidence),
             "Event:\t\t\t {}".format(self.best_event_match),
             "Events:\t\t\t {}".format(self.event_matches),
             "Event-Conf.:\t {}".format(self.best_event_confidence),
             ])
