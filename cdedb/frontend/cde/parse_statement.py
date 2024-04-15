"""Helpers for parsing bank statements"""

import dataclasses
import datetime
import decimal
import json
import re
from typing import TYPE_CHECKING, Callable, Optional, Union

import cdedb.common.validation.types as vtypes
import cdedb.models.event as models_event
from cdedb.common import (
    PARSE_OUTPUT_DATEFORMAT, Accounts, CdEDBObject, CdEDBObjectMap, ConfidenceLevel,
    Error, RequestState, TransactionType, asciificator, diacritic_patterns, now,
)
from cdedb.common.n_ import n_
from cdedb.config import LazyConfig
from cdedb.filter import cdedbid_filter
from cdedb.frontend.common import inspect_validation as inspect
from cdedb.models.common import CdEDataclassMap

if TYPE_CHECKING:
    from cdedb.backend.core import CoreBackend
    from cdedb.backend.event import EventBackend

BackendGetter = Callable[[int], CdEDBObject]


_CONF = LazyConfig()
# _LOGGER = setup_logger('parse', _CONF['LOG_DIR'] / "parse.log", _CONF['LOG_LEVEL'])


@dataclasses.dataclass
class MatchedEntities:
    persona_matches: dict[int, ConfidenceLevel]
    personas: CdEDBObjectMap
    event_matches: dict[int, ConfidenceLevel]
    events: CdEDataclassMap[models_event.Event]

    def unpack(self) -> tuple[
        dict[int, ConfidenceLevel], CdEDBObjectMap,
        dict[int, ConfidenceLevel], CdEDataclassMap[models_event.Event],
    ]:
        return (self.persona_matches, self.personas, self.event_matches, self.events)


@dataclasses.dataclass
class EventMatch:
    event: models_event.Event
    confidence: ConfidenceLevel
    errors: list[Error] = dataclasses.field(default_factory=list)
    warnings: list[Error] = dataclasses.field(default_factory=list)

    def __lt__(self, other: "EventMatch") -> bool:
        return self.confidence < other.confidence


class StatementCSVKeys:
    """CSV keys present in the export from BFS.

    As of the onlinebanking update in April 2023, these are no longer configurable.

    Presence of all keys is checked, but additional keys are allowed.
    """
    # Information about our account.
    cde_account = "Bezeichnung Auftragskonto"
    cde_iban = "IBAN Auftragskonto"
    cde_bic = "BIC Auftragskonto"
    cde_bank = "Bankname Auftragskonto"
    cde_saldo = "Saldo nach Buchung"

    # Information about the transaction
    transaction_date = "Buchungstag"
    valuta = "Valutadatum"
    posting = "Buchungstext"
    reference = "Verwendungszweck"
    amount = "Betrag"
    currency = "Waehrung"
    notes = "Bemerkung"
    category = "Kategorie"
    tax_relevant = "Steuerrelevant"

    # Information about the other party.
    account_holder = "Name Zahlungsbeteiligter"
    iban = "IBAN Zahlungsbeteiligter"
    bic = "BIC (SWIFT-Code) Zahlungsbeteiligter"
    debitor_id = "Glaeubiger ID"
    mandate_reference = "Mandatsreferenz"

    @classmethod
    def all_keys(cls) -> set[str]:
        return {v for k, v in vars(cls).items()}


class ExportFields:
    """Specifications for the fields to include in the different download files"""

    # For the unified import (event fees and membership fees).
    db_import = (
        "transaction_date", "amount_german", "cdedbid", "family_name", "given_names",
        "category_old",
    )

    # For import in CdE-Realm `money_transfers`.
    member_fees = (
        "amount", "cdedbid", "family_name", "given_names", "transaction_date",
    )

    # For import in Event-Realm `batch_fees`.
    event_fees = (
        "amount", "cdedbid", "family_name", "given_names", "transaction_date",
    )

    # For use in Excel-based bookkeeping.
    excel = (
        "transaction_date", "amount_german", "cdedbid", "family_name", "given_names",
        "category_old", "account_nr", "reference", "account_holder", "iban",
    )

    festgeld = (
        "transaction_date", "amount_german", "reference",
    )


class PostingPatterns:
    """Common patterns for postings belonging to specific types of transactions."""

    account_fee = re.compile(r"Abschluss", flags=re.I)

    # Most actively sent outgoing payments, either individual or as a collection.
    payment = re.compile(r"Überweisungsauftrag", flags=re.I)

    retoure = re.compile(r"(Retouren|Storno)", flags=re.I)

    # Posting for an incoming direct debit.
    incoming_direct_debit = re.compile(r"^Basislastschrift Ev$", flags=re.I)


class ReferencePatterns:
    """Common patterns for references belonging to specific types of transactions."""

    event_fee = re.compile(r"Teiln(ahme|ehmer)[-\s]*(beitrag)?", flags=re.I)

    event_fee_refund = re.compile(
        r"Erstattung (Teilnahmebeitrag|(Erste|Zweite) Rate|Anzahlung)", flags=re.I)

    event_fee_instructor_refund = re.compile(r"KL[-\s]Erstattung", flags=re.I)

    expenses = re.compile(r"Erstattung Auslagen", flags=re.I)

    donation = re.compile(r"Spende", flags=re.I)

    member_fee = re.compile(
        r"Mitglied(schaft)?(sbeitrag)?|(Halb)?Jahresbeitrag", flags=re.I)

    # Probably no longer relevant:
    # This matches the old reference used by external participants. We keep this
    # in case some people keep using the old format, although we cannot extract a
    # DB-ID to do the persona lookup.
    member_fee_old = re.compile(r"\d{4}-\d{2}-\d{2}[-,.\s]*Extern", flags=re.I)


class IDPatterns:
    persona = re.compile(
        r"DB-(?P<persona_id>[0-9]+)-(?P<checkdigit>[0-9X])",
        flags=re.I)

    persona_close = re.compile(
        r"DB[-./\s]*(?P<persona_id>[0-9]{1,6})[-./\s]*(?P<checkdigit>[0-9X])",
        flags=re.I)

    whitespace = re.compile(r"[-./\s]", flags=re.I)


# Minimum amount for us to consider a transaction an Event fee.
AMOUNT_MIN_EVENT_FEE = 40

# Specification for how the date is formatted in the input.
STATEMENT_INPUT_DATEFORMAT = "%d.%m.%Y"

STATEMENT_FILENAME_PATTERN = re.compile(
    r"Umsaetze_DE(?:26|96)37020500000806890[01]_(\d{4}.\d{2}.\d{2})(?: \(\d+\))?.csv")


def date_from_filename(filename: str) -> datetime.date:
    """
    Use the known format of the inputfile name to find out the last transaction date.

    Example filename from BSF: "Umsaetze_DE26370205000008068900_2023.04.23.csv"
    """
    try:
        if m := re.fullmatch(STATEMENT_FILENAME_PATTERN, filename):
            date = datetime.datetime.strptime(m.group(1), "%Y.%m.%d").date()
            return date
    except ValueError:
        pass
    return now().date()


class ParseAmountError(Exception):
    """Thrown if the amount string for a transaction could not be parsed."""


def parse_amount(amount: str) -> decimal.Decimal:
    """Safely determine how to interpret a string as Decimal."""
    if not amount:
        raise ParseAmountError
    try:
        ret = decimal.Decimal(amount)
    except decimal.InvalidOperation:
        amount = number_from_german(amount)
        try:
            ret = decimal.Decimal(amount)
        except decimal.InvalidOperation as e:
            raise ParseAmountError from e
    return ret


def number_to_german(number: Union[decimal.Decimal, int, str]) -> str:
    """Helper to convert an input to a number in german format."""
    if isinstance(number, decimal.Decimal):
        ret = f"{number:,.2f}"
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

    def __init__(self, data: CdEDBObject, index: Optional[int] = None) -> None:
        """We reconstruct a Transaction from the validation form dict here."""
        # Fix parameter suffix.
        if index is not None:
            data = {k.rstrip(str(index)): v for k, v in data.items()}

        # These fields are all very essential and need to be present.
        self.t_id = data["t_id"]
        self.account = data["account"]
        self.transaction_date = data["transaction_date"]
        self.amount = data["amount"]
        self.reference = re.sub(r"\s+", " ", data["reference"] or "")
        self.account_holder = data["account_holder"]
        self.iban = data["iban"]
        self.bic = data["bic"]
        self.posting = data["posting"]

        # We need the following fields, but we actually set them later.
        self.errors = data.get("errors", [])
        self.warnings = data.get("warnings", [])
        self.type: Optional[TransactionType] = data.get("type")
        self._event_id = data.get("event_id")
        self.event: Optional[models_event.Event] = None
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
            data["account"] = Accounts(raw[StatementCSVKeys.cde_iban])
        except ValueError:
            errors.append(
                (StatementCSVKeys.cde_iban,
                 ValueError("Unknown Account %(acc)s in Transaction %(t_id)s",
                            {"acc": raw[StatementCSVKeys.cde_iban],
                             "t_id": data["t_id"]})))
            data["account"] = Accounts.Unknown

        try:
            data["transaction_date"] = datetime.datetime.strptime(
                raw[StatementCSVKeys.transaction_date], STATEMENT_INPUT_DATEFORMAT,
            ).date()
        except ValueError:
            errors.append((StatementCSVKeys.transaction_date,
                           ValueError("Incorrect Date Format in Transaction %(t_id)s",
                                      {"t_id": t_id})))
            data["statement_date"] = datetime.datetime.now().date()

        try:
            data["amount"] = parse_amount(raw[StatementCSVKeys.amount])
        except ParseAmountError:
            errors.append(
                (StatementCSVKeys.amount,
                 ValueError("Could not parse Transaction Amount (%(amt)s)"
                            "for Transaction %(t_id)s",
                            {"amt": raw[StatementCSVKeys.amount], "t_id": t_id})))
            data["amount"] = decimal.Decimal(0)
        else:
            # Check whether the original input can be reconstructed
            raw_amount = raw[StatementCSVKeys.amount]
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

        data["reference"] = raw[StatementCSVKeys.reference]

        data["account_holder"] = raw[StatementCSVKeys.account_holder]
        data["iban"] = raw[StatementCSVKeys.iban]
        data["bic"] = raw[StatementCSVKeys.bic]

        data["posting"] = raw[StatementCSVKeys.posting]

        data["errors"] = errors
        data["warnings"] = []

        return Transaction(data)

    @staticmethod
    def get_request_params(index: Optional[int] = None, *, hidden_only: bool = False,
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
            f"transaction_date{suffix}": datetime.date,
            f"amount{suffix}": decimal.Decimal,
            f"reference{suffix}": Optional[str],  # type: ignore[dict-item]
            f"account_holder{suffix}": Optional[str],  # type: ignore[dict-item]
            f"iban{suffix}": Optional[vtypes.IBAN],  # type: ignore[dict-item]
            f"bic{suffix}": Optional[str],  # type: ignore[dict-item]
            f"posting{suffix}": str,
            f"type_confidence{suffix}": ConfidenceLevel,
            f"persona_confidence{suffix}": ConfidenceLevel,
            f"event_confidence{suffix}": ConfidenceLevel,
        }
        if not hidden_only:
            ret = dict(**ret, **{
                f"type{suffix}": TransactionType,
                f"type_confirm{suffix}": bool,
                f"cdedbid{suffix}": Optional[vtypes.CdedbID],
                f"persona_confirm{suffix}": bool,
                f"event_id{suffix}": Optional[vtypes.ID],
                f"event_confirm{suffix}": bool,
            })
        return ret

    def _find_cdedbids(self, confidence: ConfidenceLevel = ConfidenceLevel.Full,
                       ) -> dict[int, ConfidenceLevel]:
        """Find db_ids in a reference.

        Check the reference parts in order of relevancy.
        """
        ret: dict[int, ConfidenceLevel] = {}
        patterns = (IDPatterns.persona, IDPatterns.persona_close)
        orig_confidence = confidence
        for pattern in patterns:
            if result := re.findall(pattern, self.reference):
                for persona_id_str, checkdigit in result:
                    persona_id, problems = inspect(
                        vtypes.CdedbID, f"DB-{persona_id_str}-{checkdigit}")
                    if persona_id and not problems and persona_id not in ret:
                        ret[persona_id] = confidence

            confidence = orig_confidence.decrease(1)

        if len(ret) > 1:
            ids = []
            for persona_id_, confidence_ in ret.items():
                ids.append(cdedbid_filter(persona_id_))
                ret[persona_id_] = confidence_.decrease(2)
            self.warnings.append((
                'persona',
                ValueError(
                    n_("Found more than one persona ID: (%(ids)s)."),
                    {'ids': ", ".join(ids)}),
            ))

        return ret

    def parse(self, rs: RequestState, core: "CoreBackend", event: "EventBackend",
              ) -> None:
        """Try to determine the type of the transaction and referenced entities."""
        self._get_entities(rs, core, event)
        self._match_persona(rs, core)
        self._match_event(rs, event)
        self._determine_type()

    def _get_entities(self, rs: RequestState, core: "CoreBackend",
                      event: "EventBackend") -> None:
        """Try retrieving the persona and event belonging to this transaction."""
        if self._persona_id:
            try:
                self.persona = core.get_persona(rs, self._persona_id)
            except KeyError:
                self._persona_id = None
                self.persona = None
        if self._event_id:
            try:
                self.event = event.get_event(rs, self._event_id)
            except KeyError:
                self._event_id = None
                self.event = None

    def _match_persona(self, rs: RequestState, core: "CoreBackend") -> None:
        """Try to match a persona to this transaction."""
        if self.persona:
            persona_matches = {
                self.persona['id']: self.persona_confidence,
            }
        else:
            persona_matches = self._find_cdedbids()

        personas = core.get_personas(rs, persona_matches)

        for persona_id, confidence in persona_matches.items():
            # Check that the persona exists.
            if persona_id not in personas:
                self.errors.append((
                    'persona',
                    KeyError(n_("No Persona with ID %(persona_id)s found."),
                             {'persona_id': persona_id}),
                ))
                persona_matches[persona_id] = ConfidenceLevel.Null
                continue
            persona = personas[persona_id]

            d_p = diacritic_patterns
            # Search reference for given_names.
            try:
                if not any(
                    re.search(
                        d_p(re.escape(gn), two_way_replace=True),
                        self.reference,
                        flags=re.I,
                    )
                    for gn in persona['given_names'].split()
                ):
                    self.warnings.append((
                        'given_names',
                        KeyError(
                            n_("%(text)s not found in reference."),
                            {'text': persona['given_names']}),
                    ))
                    confidence = confidence.decrease()
            except re.error as e:
                self.warnings.append((
                    'given_names',
                    TypeError(
                        n_("(%(p)s) is not a valid regEx (%(e)s)."),
                        {'p': d_p(re.escape(persona['given_names'])), 'e': e}),
                ))
                confidence = confidence.decrease()

            # Search reference for family_name.
            try:
                if not any(
                        re.search(
                            d_p(re.escape(fn), two_way_replace=True),
                            self.reference,
                            flags=re.I,
                        )
                        for fn in persona['family_name'].split()
                ):
                    self.warnings.append((
                        'family_name',
                        KeyError(
                            n_("%(text)s not found in reference."),
                            {'text': persona['family_name']}),
                    ))
                    confidence = confidence.decrease()
            except re.error as e:
                self.warnings.append((
                    'family_name',
                    TypeError(
                        n_("(%(p)s) is not a valid regEx (%(e)s)."),
                        {'p': d_p(re.escape(persona['given_names'])), 'e': e}),
                ))
                confidence = confidence.decrease()

            persona_matches[persona_id] = confidence

        if persona_matches:
            best_persona_id = max(
                persona_matches, key=lambda p_id: persona_matches[p_id])
            self.persona = personas[best_persona_id]
            self.persona_confidence = persona_matches[best_persona_id]

    def _match_event(self, rs: RequestState, event_backend: "EventBackend") -> None:
        """Try to match an event to this transaction."""
        if self.event:
            return

        events = event_backend.get_events(rs, event_backend.list_events(rs))
        if not self.persona:
            amounts_owed = {}
        else:
            amounts_owed = event_backend.list_amounts_owed(rs, self.persona['id'])

        event_matches = [
            match for event in events.values()
            if (match := self._match_one_event(event, amounts_owed.get(event.id)))
        ]

        if len(event_matches) > 1:
            # Force manual reviews.
            for match in event_matches:
                match.confidence = match.confidence.decrease(2)

        if event_matches:
            best_match = max(event_matches)
            self.event = best_match.event
            self.event_confidence = best_match.confidence
            self.errors.extend(best_match.errors)
            self.warnings.extend(best_match.warnings)

    @staticmethod
    def compile_pattern(s: str, strict: bool) -> re.Pattern[str]:
        s = re.escape(asciificator(s))
        if strict:
            s = rf"\b{s}\b"
        return re.compile(s, flags=re.I)

    def _match_one_event(self, event: models_event.Event,
                         amount_owed: Optional[decimal.Decimal] = None,
                         ) -> Optional[EventMatch]:
        if self.compile_pattern(event.shortname, strict=True).search(self.reference):
            ret = EventMatch(event, ConfidenceLevel.Full)
        elif self.compile_pattern(event.title, strict=True).search(self.reference):
            ret = EventMatch(event, ConfidenceLevel.Full)
        elif self.compile_pattern(event.shortname, strict=False).search(self.reference):
            ret = EventMatch(event, ConfidenceLevel.High)
        elif self.compile_pattern(event.title, strict=False).search(self.reference):
            ret = EventMatch(event, ConfidenceLevel.High)
        elif amount_owed is not None and self.amount == amount_owed:
            ret = EventMatch(
                event=event,
                confidence=ConfidenceLevel.Medium,
                warnings=[(
                    'event',
                    ValueError(
                        n_("Matched event %(title)s via amount owed only."),
                        {'title': event.title}),
                )],
            )
        else:
            return None
        reference_date = now().date()
        if event.end < (reference_date - datetime.timedelta(180)):
            ret.confidence = ret.confidence.decrease(2)
        return ret

    def _determine_type(self) -> None:
        """Try to guess the TransactionType."""

        confidence = ConfidenceLevel.Full

        # Return early, if we already matched a type.
        if self.type:
            return

        # Sanity check whether we know the Account.
        if self.account == Accounts.Unknown:
            self.type = TransactionType.Unknown
            self.type_confidence = confidence.destroy()
            return

        # Handle all outgoing payments.
        if self.amount < 0:
            # Check outgoing active payments.
            if PostingPatterns.payment.search(self.posting):

                # Special case for outgoing donations.
                if ReferencePatterns.donation.search(self.reference):
                    self.type = TransactionType.Donation
                    self.type_confidence = ConfidenceLevel.Full
                    return

                # Check for refund of participant fee:
                if ReferencePatterns.event_fee_refund.search(self.reference):
                    self.type = TransactionType.EventFeeRefund
                    self.type_confidence = confidence
                    return

                # Check for refund of instructor fee:
                elif ReferencePatterns.event_fee_instructor_refund.search(
                        self.reference):
                    self.type = TransactionType.InstructorRefund
                    self.type_confidence = confidence
                    return

                # Check for refund of expenses.
                elif ReferencePatterns.expenses.search(self.reference):
                    if self.event:
                        self.type = TransactionType.EventExpenses
                    else:
                        self.type = TransactionType.Expenses
                    self.type_confidence = confidence
                    return

                # Some other active payment. Might require manual review.
                else:
                    self.type = TransactionType.OtherPayment
                    self.type_confidence = confidence.decrease()
                    return

            # Special case for account fees.
            elif PostingPatterns.account_fee.search(self.posting):
                # Posting reserved for administrative fees found.
                self.type = TransactionType.AccountFee
                self.type_confidence = ConfidenceLevel.Full
                return

            # Some other outgoing payment, probably a direct debit. Manual review.
            else:
                self.type = TransactionType.OtherPayment
                self.type_confidence = confidence.decrease(2)
                return

        elif self.amount > 0:

            # Check for incoming direct debits.
            if PostingPatterns.incoming_direct_debit.search(self.posting):
                self.type = TransactionType.LastschriftInitiative
                self.type_confidence = confidence
                return

            elif PostingPatterns.retoure.search(self.posting):
                self.type = TransactionType.Retoure
                self.type_confidence = confidence
                return

            # Look for explicit membership fee.
            elif ReferencePatterns.member_fee.search(self.reference):
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence
                return

            # Look for matched event and minimum amount.
            elif self.event and self.amount > AMOUNT_MIN_EVENT_FEE:
                self.type = TransactionType.EventFee
                self.type_confidence = confidence
                return

            # Look for event fee without event match.
            elif ReferencePatterns.event_fee.search(self.reference) and (
                    self.amount > AMOUNT_MIN_EVENT_FEE):
                self.type = TransactionType.EventFee
                self.type_confidence = confidence.decrease()
                return

            # Special case for incoming donations.
            elif ReferencePatterns.donation.search(self.reference):
                self.type = TransactionType.Donation
                self.type_confidence = ConfidenceLevel.Full
                return

            # Look for persona match without event match.
            elif self.persona:
                self.type = TransactionType.MembershipFee
                self.type_confidence = confidence
                return

            # Some other incoming payment, require manual review.
            else:
                self.type = TransactionType.Other
                self.type_confidence = confidence.decrease(2)
                return

        elif self.amount == 0:
            self.warnings.append(("amount", ValueError("Amount is zero.")))
            self.type = TransactionType.Other
            self.type_confidence = confidence.destroy()
            return

        else:
            raise RuntimeError(n_("Impossible."))

    def validate(self, rs: RequestState, core: "CoreBackend", event: "EventBackend",
                 ) -> None:
        """Inspect transaction for problems."""
        self._get_entities(rs, core, event)

        cutoff = ConfidenceLevel.High
        if not self.type:
            self.type = TransactionType.Unknown

        # First: Check whether we are confident about the transaction type.
        if self.type and self.type_confidence and self.type_confidence >= cutoff:
            pass
        elif not self.type or self.type == TransactionType.Unknown:
            self.errors.append((
                "type",
                ValueError(n_("Could not determine transaction type.")),
            ))
        elif not self.type_confidence or self.type_confidence < cutoff:
            self.errors.append((
                "type",
                ValueError(n_("Not confident about transaction type.")),
            ))

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
                if self.event and self.persona:
                    amount_owed = event.get_amount_owed(
                        rs, self.persona['id'], self.event.id)
                    if amount_owed is None:
                        self.warnings.append((
                            'event',
                            ValueError(n_("User is not registered for this event.")),
                        ))
                    elif self.amount != amount_owed:
                        self.warnings.append((
                            'event',
                            ValueError(n_("Amount does not match amount owed.")),
                        ))

        # Third: If the type needs a persona, check the persona.
        if self.type.has_member:
            if self.persona:
                if self.persona_confidence and self.persona_confidence >= cutoff:
                    pass
                else:
                    self.errors.append((
                        "cdedbid",
                        ValueError(n_("Not confident about member match.")),
                    ))
            else:
                self.errors.append((
                    "cdedbid",
                    ValueError(n_("Needs member match.")),
                ))

            if self.type == TransactionType.MembershipFee:
                if self.event:
                    self.errors.append((
                        "event",
                        ValueError(n_("Mustn't have event match.")),
                    ))
                if self.persona and not self.persona['is_cde_realm']:
                    self.errors.append((
                        "persona",
                        ValueError(n_("Not a CdE-Account.")),
                    ))
                if self.amount > AMOUNT_MIN_EVENT_FEE:
                    self.warnings.append((
                        "amount",
                        ValueError(
                            n_("Amount higher than expected for membership fee.")),
                    ))
        if self.type == TransactionType.Donation:
            if self.event:
                self.warnings.append((
                    "event",
                    ValueError(n_("Donation to event might be an event fee.")),
                ))

    @property
    def amount_german(self) -> str:
        """German way of writing the amount (without thousands separators)"""
        return number_to_german(self.amount)

    @property
    def amount_english(self) -> str:
        """English way of writing the amount."""
        return f"{self.amount:.2f}"

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
            "account": str(self.account),
            "account_nr": self.account.display_str(),
            "account_iban": self.account.value,
            "transaction_date": self.transaction_date.strftime(PARSE_OUTPUT_DATEFORMAT),
            "amount": self.amount_english,
            "amount_german": self.amount_german,
            "account_holder": self.account_holder,
            "posting": self.posting,
            "type": self.type,
            "category": ((self.event.shortname + '-') if self.event else '')
                        + self.type.display_str(),
            "type_confidence": self.type_confidence,
            "cdedbid": cdedbid_filter(self.persona['id']) if self.persona else None,
            "persona_confidence": self.persona_confidence,
            "given_names": self.persona['given_names'] if self.persona else "",
            "family_name": self.persona['family_name'] if self.persona else "",
            "event_id": self.event.id if self.event else None,
            "event_confidence": self.event_confidence,
            "event_name": self.event.shortname if self.event else None,
            "errors_str": ", ".join("{}: {}".format(
                key, e.args[0].format(**e.args[1]) if len(e.args) == 2 else e)
                                    for key, e in self.errors),
            "warnings_str": ", ".join("{}: {}".format(
                key, w.args[0].format(**w.args[1]) if len(w.args) == 2 else w)
                                      for key, w in self.warnings),
            "iban": self.iban,
            "bic": self.bic,
            "t_id": self.t_id,
            "category_old": self.event.shortname if self.event else self.type.old(),
        }
        ret["summary"] = json.dumps(ret)
        ret["persona"] = self.persona
        ret["event"] = self.event
        ret["errors"] = self.errors
        ret["warnings"] = self.warnings

        return ret
