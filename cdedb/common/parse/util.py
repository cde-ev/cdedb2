import decimal
import enum
import re
from typing import TYPE_CHECKING

from cdedb.common.n_ import n_
from cdedb.uncommon.intenum import CdEEnum, CdEIntEnum

if TYPE_CHECKING:
    from cdedb.common import Error


@enum.unique
class Accounts(CdEEnum):
    """Store the existing CdE Accounts."""

    Sozialbank = "DE26370205000008068900"
    Sozialbank_Spenden = "DE96370205000008068901"
    Festgeld = "DE45370205000010042605"
    Festgeld2 = "DE05370205000010047205"
    Skatbank = "DE23830654080005374499"
    Tagesgeld = "DE96830654087005374499"
    # Fallback if Account is none of the above
    Unknown = "Unknown"

    def display_str(self) -> str:
        return {
            Accounts.Sozialbank: "8068900",
            Accounts.Sozialbank_Spenden: "8068901",
            Accounts.Festgeld: "Festgeld",
            Accounts.Festgeld2: "Festgeld2",
            Accounts.Skatbank: "Skatbank",
            Accounts.Tagesgeld: "Tagesgeld",
            Accounts.Unknown: "Unknown",
        }[self]

    def get_iban(self) -> str:
        return self.value

    def get_account_holder(self) -> str:
        return "CdE e.V."

    def get_bic(self) -> str:
        if self in {Accounts.Skatbank, Accounts.Tagesgeld}:
            return "GENODEF1SLR"
        return "BFSWDE33XXX"

    def get_bank(self) -> str:
        if self in {Accounts.Skatbank, Accounts.Tagesgeld}:
            return "Skatbank"
        return "Sozialbank"

    @classmethod
    def get_event_accounts(cls) -> list["Accounts"]:
        return [
            cls.Sozialbank,
            cls.Skatbank,
        ]


@enum.unique
class ConfidenceLevel(CdEIntEnum):
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


@enum.unique
class TransactionType(CdEIntEnum):
    """Store the type of a Transactions."""

    MembershipFee = 1
    EventFee = 2
    Donation = 3
    LastschriftInitiative = 4
    Retoure = 5
    Other = 100

    EventFeeRefund = 10
    InstructorRefund = 11
    EventExpenses = 12
    Expenses = 13
    AccountFee = 14
    OtherPayment = 200

    Unknown = 1000

    @property
    def has_event(self) -> bool:
        return self in {
            TransactionType.EventFee,
            TransactionType.EventFeeRefund,
            TransactionType.InstructorRefund,
            TransactionType.EventExpenses,
        }

    @property
    def has_member(self) -> bool:
        return self in {
            TransactionType.MembershipFee,
            TransactionType.EventFee,
            TransactionType.LastschriftInitiative,
        }

    @property
    def is_unknown(self) -> bool:
        return self in {
            TransactionType.Unknown,
            TransactionType.Other,
            TransactionType.OtherPayment,
        }

    def category(self) -> str:
        """Return a string representation for excel and import"""
        if self.has_member or self.has_event:
            return self.display_str()
        return "Sonstiges"

    def display_str(self) -> str:
        """
        Return a string representation for the TransactionType meant to be displayed.

        These are _not_ translated on purpose, so that the generated download
        is the same regardless of locale.
        """
        display_str = {
            TransactionType.MembershipFee: "Mitgliedsbeitrag",
            TransactionType.EventFee: "Teilnahmebeitrag",
            TransactionType.Donation: "Spende",
            TransactionType.LastschriftInitiative: "Lastschriftinitiative",
            TransactionType.Retoure: "Storno",
            TransactionType.Other: "Sonstiges",
            TransactionType.EventFeeRefund: "TN-Erstattung",
            TransactionType.InstructorRefund: "KL-Erstattung",
            TransactionType.EventExpenses: "Veranstaltungsausgabe",
            TransactionType.Expenses: "Ausgabe",
            TransactionType.AccountFee: "Kontogebühr",
            TransactionType.OtherPayment: "Andere Zahlung",
            TransactionType.Unknown: "Unbekannt",
        }
        return display_str.get(self, str(self))


class ParseAmountError(Exception):
    """Thrown if the amount string for a transaction could not be parsed."""


def parse_amount(amount: str) -> decimal.Decimal:
    """Safely determine how to interpret a string as Decimal."""
    if not amount:
        raise ParseAmountError
    try:
        # parentheses indicate negative amount
        if '(' in amount:
            match = re.match(r'\((.+)\)', amount)
            if match:
                amount = '-' + match.group(1).strip()
        # remove currency suffix
        amount = amount.removesuffix('€')
        ret = decimal.Decimal(amount)
    except decimal.InvalidOperation:
        amount = number_from_german(amount)
        try:
            ret = decimal.Decimal(amount)
        except decimal.InvalidOperation as e:
            raise ParseAmountError from e
    return ret


def check_amount(amount_str: str) -> tuple[decimal.Decimal | None, list["Error"]]:
    try:
        amount = parse_amount(amount_str)
    except ParseAmountError:
        return None, [('amount', ValueError(n_("Invalid input for amount.")))]
    else:
        return amount, []


def number_to_german(number: decimal.Decimal | int | str) -> str:
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


def simplify_amount(amt: decimal.Decimal | int | str) -> str:
    """Helper to convert a number to german and strip decimal zeros."""
    return str(number_to_german(amt)).rstrip("0").rstrip(",")
