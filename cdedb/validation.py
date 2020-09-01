#!/usr/bin/env python3
# pylint: disable=undefined-variable
# we do some setattrs which confuse pylint

"""User data input mangling.

We provide a set of functions testing arbitary user provided data for
fitness. Those functions returning a mangled value also convert to more
approriate python types (most input is given as strings which are
converted to e.g. :py:class:`datetime.datetime`).

We offer three variants.

* ``check_*`` return a tuple ``(mangled_value, errors)``.
* ``affirm_*`` on success return the mangled value, but if there is
  an error raise an exception.
* ``is_*`` returns a :py:class:`boolean`, but does no type conversion (hence
  things like dates mustn't be strings)

The raw validator implementations are functions with signature ``(val,
argname, *, _convert, _ignore_warnings, **kwargs)`` which are wrapped into the
three variants above.

They return the tuple ``(mangled_value, errors)``, where
``errors`` is a list containing tuples ``(argname, exception)``. Each
exception may have one or two arguments. The first is the error string
and the second optional may be a {str: object} dict describing
substitutions to the error string done after i18n.

The parameter ``_convert`` is present in every validator and is usually passed
along from the original caller to every validation inside. If ``True``,
validators may try to convert the value into the appropriate type. For instance
``_int`` will try to convert the input into an int which would be useful for
string inputs especially.

The parameter ``_ignore_warnings`` is present in every validator. If ``True``,
certain Errors of type ``ValidationWarning`` may be ignored instead of returned.
Think of this like a toggle to enable less strict validation of some constants
which might change externally like german postal codes.
"""

import copy
import datetime
import decimal
import distutils.util
import functools
import io
import itertools
import json
import logging
import math
import re
import string
import sys
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

import magic
import PIL.Image
import pytz
import werkzeug.datastructures
import zxcvbn

import cdedb.ml_type_aux as ml_type
from cdedb.common import (
    ASSEMBLY_BAR_MONIKER,
    EPSILON,
    EVENT_SCHEMA_VERSION,
    INFINITE_ENUM_MAGIC_NUMBER,
    REALM_SPECIFIC_GENESIS_FIELDS,
    Error,
    InfiniteEnum,
    ValidationWarning,
    asciificator,
    compute_checkdigit,
    extract_roles,
    n_,
    now,
)
from cdedb.config import BasicConfig
from cdedb.database.constants import FieldAssociations, FieldDatatypes
from cdedb.enums import ALL_ENUMS, ALL_INFINITE_ENUMS
from cdedb.query import (
    MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS,
    VALID_QUERY_OPERATORS,
    Query,
    QueryOperators,
)
from cdedb.validationdata import (
    FREQUENCY_LISTS,
    GERMAN_PHONE_CODES,
    GERMAN_POSTAL_CODES,
    IBAN_LENGTHS,
    ITU_CODES,
)
from cdedb.validationtypes import *

_BASICCONF = BasicConfig()

current_module = sys.modules[__name__]

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)

T = TypeVar('T')
F = Callable[..., T]

_ALL = []


# TODO maybe add values_progress attribute or similar
class ValidationSummary(ValueError, Sequence[Exception]):
    args: Tuple[Exception, ...]

    def __init__(self, *errors: Exception):
        super().__init__(*errors)

    def __len__(self):
        return len(self.args)

    def __getitem__(self, index):
        return self.args[index]

    def extend(self, errors: Iterable[Exception]):
        self.args = self.args + tuple(errors)

    def append(self, error: Exception):
        self.args = self.args + (error,)


class ValidatorStorage(Dict[Type, Callable]):
    __setitem__: Callable[["ValidatorStorage", Type[T], F[T]], None]
    __getitem__: Callable[["ValidatorStorage", Type[T]], F[T]]

    def __missing__(self, type_: Type[T]) -> F[T]:
        # TODO implement dynamic lookup for container types
        raise NotImplementedError()


_ALL_TYPED = ValidatorStorage()


def _addvalidator(fun):
    """Mark a function for processing into validators."""
    _ALL.append(fun)
    return fun


def _add_typed_validator(fun: F[T]) -> F[T]:
    """Mark a typed function for processing into validators."""
    return_type: Type[T] = get_type_hints(fun)["return"]
    if return_type in _ALL_TYPED:
        raise RuntimeError(f"Type {return_type:r} already registered")
    _ALL_TYPED[return_type] = fun
    _ALL_TYPED[Optional[return_type]] = fun

    return fun


def _examine_dictionary_fields(
    adict: Dict,
    mandatory_fields: Dict[str, Callable],
    optional_fields: Dict[str, Callable] = None,
    *,
    allow_superfluous: bool = False,
    _convert: bool = True,
    _ignore_warnings: bool = False
) -> Tuple[Dict[str, Any], ValidationSummary]:
    """Check more complex dictionaries.

    :param adict: a :py:class:`dict` to check
    :param mandatory_fields: The mandatory keys to be checked for in
      :py:obj:`adict`, the callable is a validator to check the corresponding
      value in :py:obj:`adict` for conformance. A missing key is an error in
      itself.
    :param optional_fields: Like :py:obj:`mandatory_fields`, but facultative.
    :param allow_superfluous: If ``False`` keys which are neither in
      :py:obj:`mandatory_fields` nor in :py:obj:`optional_fields` are errors.
    :param _convert: If ``True`` do type conversions.
    :param _ignore_warnings: If ``True`` skip Errors
        of type ``ValidationWarning``.
    """
    optional_fields = optional_fields or {}
    errs = ValidationSummary()
    retval: Dict[str, Any] = {}
    for key, value in adict.items():
        if key in mandatory_fields:
            try:
                v = mandatory_fields[key](value, argname=key, _convert=_convert,
                                          _ignore_warnings=_ignore_warnings)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif key in optional_fields:
            try:
                v = optional_fields[key](value, argname=key, _convert=_convert,
                                         _ignore_warnings=_ignore_warnings)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif not allow_superfluous:
            errs.append(KeyError(key, n_("Superfluous key found.")))

    missing_mandatory = set(mandatory_fields).difference(retval)
    if missing_mandatory:
        for key in missing_mandatory:
            errs.append(KeyError(key, n_("Mandatory key missing.")))
        raise errs

    return retval, errs


def _augment_dict_validator(
    validator: Callable,
    augmentation: Dict[str, Callable],
    strict: bool = True
) -> Callable:
    """Beef up a dict validator.

    This is for the case where you have two similar specs for a data set
    in form of a dict and already a validator for one of them, but some
    additional fields in the second spec.

    This can also be used as a decorator.

    :param augmentation: Syntax is the same as for :py:meth:`_examine_dictionary_fields`.
    :param strict: If True the additional arguments are mandatory otherwise they are optional.
    """

    @functools.wraps(validator)
    def new_validator(
        val: Any, argname: str = None, **kwargs
    ) -> Tuple[Dict[str, Any], ValidationSummary]:
        mandatory_fields = augmentation if strict else {}
        optional_fields = {} if strict else augmentation

        errs = ValidationSummary()
        ret: Dict[str, Any] = {}
        try:
            ret, errs = _examine_dictionary_fields(
                val, mandatory_fields, optional_fields, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

        tmp = copy.deepcopy(val)
        for field in augmentation:
            if field in tmp:
                del tmp[field]

        v = None
        try:
            v = validator(tmp, argname, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

        if ret is not None and v is not None:
            ret.update(v)
        if errs:
            raise errs
        return ret, errs

    return new_validator


def escaped_split(string: str, delim: str, escape: str = '\\') -> List[str]:
    """Helper function for anvanced list splitting.

    Split the list at every delimiter, except if it is escaped (and
    allow the escape char to be escaped itself).

    Basend on http://stackoverflow.com/a/18092547
    """
    ret = []
    current = ''
    itr = iter(string)
    for char in itr:
        if char == escape:
            try:
                current += next(itr)
            except StopIteration:
                pass
        elif char == delim:
            ret.append(current)
            current = ''
        else:
            current += char
    ret.append(current)
    return ret


#
# Below is the real stuff
#

@_add_typed_validator
def _None(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs
) -> None:
    """Force a None.

    This is mostly for ensuring proper population of dicts.
    """
    if _convert:
        if isinstance(val, str) and not val:
            val = None
    if val is not None:
        raise ValidationSummary(ValueError(argname, n_("Must be None.")))
    return None


@_add_typed_validator
def _any(
    val: Any, argname: str = None, **kwargs
) -> Any:
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.
    """
    return val


@_add_typed_validator
def _int(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs
) -> int:
    if _convert:
        if isinstance(val, str) or isinstance(val, bool):
            try:
                val = int(val)
            except ValueError as e:
                raise ValidationSummary(ValueError(argname, n_(
                    "Invalid input for integer."))) from e
        elif isinstance(val, float):
            if not math.isclose(val, int(val), abs_tol=EPSILON):
                raise ValidationSummary(ValueError(
                    argname, n_("Precision loss.")))
            val = int(val)
    if not isinstance(val, int):
        raise ValidationSummary(TypeError(argname, n_("Must be an integer.")))
    return val


@_add_typed_validator
def _non_negative_int(
    val: Any, argname: str = None, **kwargs
) -> NonNegativeInt:
    val = _int(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Must not be negative.")))
    return NonNegativeInt(val)


@_add_typed_validator
def _positive_int(
    val: Any, argname: str = None, **kwargs
) -> PositiveInt:
    val = _int(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be positive.")))
    return PositiveInt(val)


@_add_typed_validator
def _id(
    val: Any, argname: str = None, **kwargs
) -> ID:
    """A numeric ID as in a database key.

    This is just a wrapper around `_positive_int`, to differentiate this
    semantically.
    """
    return ID(_positive_int(val, argname, **kwargs))


@_add_typed_validator
def _partial_import_id(
    val: Any, argname: str = None, **kwargs
) -> PartialImportID:
    """A numeric id or a negative int as a placeholder."""
    val = _int(val, argname, **kwargs)
    if val == 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be zero.")))
    return PartialImportID(val)


@_add_typed_validator
def _float(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs
) -> float:
    if _convert:
        try:  # TODO why not test for string/bytes here like in _int
            val = float(val)
        except (ValueError, TypeError) as e:
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for float."))) from e
    if not isinstance(val, float):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a floating point number.")))
    return val


@_add_typed_validator
def _decimal(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs
) -> decimal.Decimal:
    if _convert and isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise ValueError(argname, n_(
                "Invalid input for decimal number.")) from e
    if not isinstance(val, decimal.Decimal):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a decimal.Decimal.")))
    return val


@_add_typed_validator
def _non_negative_decimal(
    val: Any, argname: str = None, **kwargs
) -> NonNegativeDecimal:
    val = _decimal(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return NonNegativeDecimal(val)


@_add_typed_validator
def _positive_decimal(
    val: Any, argname: str = None, **kwargs
) -> PositiveDecimal:
    val = _decimal(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return PositiveDecimal(val)


@_add_typed_validator
def _str_type(
    val: Any, argname: str = None, *,
    zap: str = '', sieve: str = '', _convert: bool = True, **kwargs
) -> StringType:
    """
    :param zap: delete all characters in this from the result
    :param sieve: allow only the characters in this into the result
    """
    if _convert and val is not None:
        try:
            val = str(val)
        except (ValueError, TypeError) as e:
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for string."))) from e
    if not isinstance(val, str):
        raise ValidationSummary(TypeError(argname, n_("Must be a string.")))
    if zap:
        val = ''.join(c for c in val if c not in zap)
    if sieve:
        val = ''.join(c for c in val if c in sieve)
    val = val.replace("\r\n", "\n").replace("\r", "\n")
    return StringType(val)


@_add_typed_validator
def _str(val: Any, argname: str = None, **kwargs) -> str:
    """ Like :py:class:`_str_type` (parameters see there),
    but mustn't be empty (whitespace doesn't count).
    """
    val = _str_type(val, argname, **kwargs)
    if not val:
        raise ValidationSummary(ValueError(argname, n_("Mustn’t be empty.")))
    return val


@_add_typed_validator
def _bytes(
    val: Any, argname: str = None, *,
    _convert: bool = True, encoding: str = None, **kwargs
) -> bytes:
    if _convert:
        if isinstance(val, str):
            if not encoding:  # TODO are there cases where we do not use utf-8?
                raise RuntimeError(  # TODO should this be a validation error?
                    "Not encoding specified to convert str to bytes.")
            val = val.encode(encoding=encoding)
        else:
            try:
                val = bytes(val)
            except ValueError as e:
                raise ValidationSummary(ValueError(argname, n_("Cannot convert {val} to bytes."),
                                                   {'val': val})) from e
    if not isinstance(val, bytes):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a bytes object.")))
    return val


@_add_typed_validator
def _mapping(
    val: Any, argname: str = None, **kwargs
) -> Mapping:
    """
    :param _convert: is ignored since no useful default conversion is available
    """
    if not isinstance(val, Mapping):
        raise ValidationSummary(TypeError(argname, n_("Must be a mapping.")))
    return val


@_add_typed_validator
def _iterable(
    val: Any, argname: str = None, **kwargs
) -> Iterable:
    """
    :param _convert: is ignored since no useful default conversion is available
    """
    if not isinstance(val, Iterable):
        raise ValidationSummary(TypeError(argname, n_("Must be an iterable.")))
    return val


@_add_typed_validator
def _sequence(
    val: Any, argname: str = None, *, _convert=True, **kwargs
) -> Sequence:
    if _convert:
        try:
            val = tuple(val)
        except (ValueError, TypeError) as e:  # TODO what raises ValueError
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for sequence."))) from e
    if not isinstance(val, Sequence):
        raise ValidationSummary(TypeError(argname, n_("Must be a sequence.")))
    return val


@_add_typed_validator
def _bool(
    val: Any, argname: str = None, *, _convert=True, **kwargs
) -> bool:
    # TODO why do we convert first if it may already be a subclass of bool?
    if _convert and val is not None:
        try:
            return distutils.util.strtobool(val)
        except (AttributeError, ValueError):
            try:
                return bool(val)
            except (ValueError, TypeError) as e:
                raise ValidationSummary(ValueError(argname, n_(
                    "Invalid input for boolean."))) from e
    if not isinstance(val, bool):
        raise ValidationSummary(TypeError(argname, n_("Must be a boolean.")))
    return val


@_add_typed_validator
def _empty_dict(
    val: Any, argname: str = None, **kwargs
) -> EmptyDict:
    if val != {}:
        raise ValidationSummary(
            TypeError(argname, n_("Must be an empty dict.")))
    return EmptyDict(val)


@_add_typed_validator
def _empty_list(
    val: Any, argname: str = None, *, _convert=True, **kwargs
) -> EmptyList:
    if _convert:  # TODO why do we convert here but not for _empty_dict?
        val = list(_iterable(val, argname, _convert=_convert, **kwargs))
    if val != []:
        raise TypeError(argname, n_("Must be an empty list."))
    return EmptyList(val)


@_add_typed_validator  # TODO use Union of Literal
def _realm(
    val: Any, argname: str = None, **kwargs
) -> Realm:
    """A realm in the sense of the DB."""
    val = _str(val, argname, **kwargs)
    if val not in ("session", "core", "cde", "event", "ml", "assembly"):
        raise ValidationSummary(ValueError(argname, n_("Not a valid realm.")))
    return Realm(val)


@_add_typed_validator
def _cdedbid(
    val: Any, argname: str = None, **kwargs
) -> CdedbID:
    val = _str(val, argname, **kwargs).strip()  # TODO is strip necessary here?
    match = re.search('^DB-(?P<value>[0-9]*)-(?P<checkdigit>[0-9X])$', val)
    if match is None:  # TODO should we always use is None or test for truthy?
        raise ValidationSummary(ValueError(argname, n_("Wrong formatting.")))

    value = _id(match["value"], argname, **kwargs)
    if compute_checkdigit(value) != match["checkdigit"]:
        raise ValidationSummary(ValueError(argname, n_("Checksum failure.")))
    return CdedbID(value)


@_add_typed_validator
def _printable_ascii_type(
    val: Any, argname: str = None, **kwargs
) -> PrintableASCIIType:
    val = _str_type(val, argname, **kwargs)
    if re.search(r'^[ -~]*$', val) is None:
        raise ValidationSummary(ValueError(
            argname, n_("Must be printable ASCII.")))
    return PrintableASCIIType(val)


@_add_typed_validator
def _printable_ascii(
    val: Any, argname: str = None, **kwargs
) -> PrintableASCII:
    """Like :py:func:`_printable_ascii_type` (parameters see there),
    but mustn't be empty (whitespace doesn't count).
    """
    val = _printable_ascii_type(val, argname, **kwargs)
    if not val:  # TODO leave strip here?
        raise ValidationSummary(ValueError(argname, n_("Mustn’t be empty.")))
    return PrintableASCII(val)


@_add_typed_validator
def _alphanumeric(
    val: Any, argname: str = None, **kwargs
) -> Alphanumeric:
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9]+$', val) is None:
        raise ValidationSummary(ValueError(
            argname, n_("Must be alphanumeric.")))
    return Alphanumeric(val)


@_add_typed_validator
def _csv_alphanumeric(
    val: Any, argname: str = None, **kwargs
) -> CSVAlphanumeric:
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9]+(,[a-zA-Z0-9]+)*$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated alphanumeric.")))
    return CSVAlphanumeric(val)


@_add_typed_validator
def _identifier(
    val: Any, argname: str = None, **kwargs
) -> Identifier:
    """Identifiers encompass everything from file names to short names for
    events.
    """
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9_.-]+$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be an identifier (only letters,"
            " numbers, underscore, dot and hyphen).")))
    return Identifier(val)


@_add_typed_validator
def _restrictive_identifier(
    val: Any, argname: str = None, **kwargs
) -> RestrictiveIdentifier:
    """Restrictive identifiers are for situations, where normal identifiers
    are too lax.

    One example are sql column names.
    """
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9_]+$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be a restrictive identifier (only letters,"
            " numbers and underscore).")))
    return RestrictiveIdentifier(val)


@_add_typed_validator
def _csv_identifier(
        val: Any, argname: str = None, **kwargs):
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated identifiers.")))
    return CSVIdentifier(val)


# TODO manual handling of @_add_typed_validator inside decorator or storage?
@_add_typed_validator
def _list_of(
    val: Any, validator: Callable[..., T],
    argname: str = None, *,
    _convert: bool = True, _allow_empty: bool = True, **kwargs
) -> List[T]:
    """Apply another validator to all entries of of a list.

    With `_convert` being True, the input may be a comma-separated string.
    """
    if _convert:
        if isinstance(val, str):
            # TODO use default separator from config here?
            # TODO use escaped_split?
            # Skip emtpy entries which can be produced by JavaScript.
            val = [v for v in val.split(",") if v]
        val = list(_iterable(val, argname, _convert=_convert, **kwargs))
    else:
        # TODO why _sequence here but iterable above?
        val = list(_sequence(val, argname, _convert=_convert, **kwargs))
    vals: List[T] = []
    errs = ValidationSummary()
    for v in val:
        try:
            vals.append(validator(v, argname, _convert=_convert, **kwargs))
        except ValidationSummary as e:
            errs.extend(e)
    if errs:
        raise errs

    if not _allow_empty and not vals:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))

    return vals


@_add_typed_validator
def _int_csv_list(
    val: Any, argname: str = None, **kwargs
) -> IntCSVList:
    return IntCSVList(_list_of(val, _int, argname, **kwargs))


@_add_typed_validator
def _cdedbid_csv_list(
    val: Any, argname: str = None, **kwargs
) -> CdedbIDList:
    """This deals with strings containing multiple cdedbids,
    like when they are returned from cdedbSearchPerson.
    """
    return CdedbIDList(_list_of(val, _cdedbid, argname, **kwargs))


@_add_typed_validator  # TODO split into Password and AdminPassword?
def _password_strength(
    val: Any, argname: str = None, *,
    admin: bool = False, inputs: List[str] = None, **kwargs
) -> PasswordStrength:
    """Implement a password policy.

    This has the strictly competing goals of security and usability.

    We are using zxcvbn for this task instead of any other solutions here,
    as it is the most popular solution to measure the actual entropy of a
    password and does not force character rules to the user that are not
    really improving password strength.
    """
    inputs = inputs or []
    val = _str(val, argname=argname, **kwargs)
    errors = ValidationSummary()

    results = zxcvbn.zxcvbn(val, list(filter(None, inputs)))
    # if user is admin in any realm, require a score of 4. After
    # migration, everyone must change their password, so this is
    # actually enforced for admins of the old db. Afterwards,
    # meta admins are intended to do a password reset.
    if results['score'] < 2:
        feedback: List[str] = [results['feedback']['warning']]
        feedback.extend(results['feedback']['suggestions'][:2])
        for fb in filter(None, feedback):
            errors.append(ValueError(argname, fb))
        if not errors:
            # generate custom feedback
            # TODO this should never be the case
            errors.append(ValueError(argname, n_("Password too weak.")))

    if admin and results['score'] < 4:
        # TODO also include zxcvbn feedback here?
        errors.append(ValueError(argname, n_(
            "Password too weak for admin account.")))

    if errors:
        raise errors

    return PasswordStrength(val)


@_add_typed_validator
def _email(
    val: Any, argname: str = None, **kwargs
) -> Email:
    """We accept only a subset of valid email addresses since implementing the
    full standard is horrendous. Also we normalize emails to lower case.
    """
    val = _printable_ascii(val, argname, **kwargs)
    # TODO why is this necessary
    # strip address and normalize to lower case
    val = val.strip().lower()
    if re.search(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$', val) is None:
        raise ValidationSummary(ValueError(
            argname, n_("Must be a valid email address.")))
    return Email(val)


@_add_typed_validator
def _email_local_part(
    val: Any, argname: str = None, **kwargs
) -> EmailLocalPart:
    """We accept only a subset of valid email addresses.
    Here we only care about the local part.
    """
    val = _printable_ascii(val, argname, **kwargs)
    # strip address and normalize to lower case
    val = val.strip().lower()
    if not re.match(r'^[a-z0-9._+-]+$', val):  # TODO inspect match vs search
        raise ValidationSummary(ValueError(
            argname, n_("Must be a valid email local part.")))
    return EmailLocalPart(val)


_PERSONA_TYPE_FIELDS = {
    'is_cde_realm': _bool,
    'is_event_realm': _bool,
    'is_ml_realm': _bool,
    'is_assembly_realm': _bool,
    'is_member': _bool,
    'is_searchable': _bool,
    'is_active': _bool,
}


def _PERSONA_BASE_CREATION(): return {
    'username': _email,
    'notes': _str_or_None,
    'is_cde_realm': _bool,
    'is_event_realm': _bool,
    'is_ml_realm': _bool,
    'is_assembly_realm': _bool,
    'is_member': _bool,
    'is_searchable': _bool,
    'is_active': _bool,
    'display_name': _str,
    'given_names': _str,
    'family_name': _str,
    'title': _None,
    'name_supplement': _None,
    'gender': _None,
    'birthday': _None,
    'telephone': _None,
    'mobile': _None,
    'address_supplement': _None,
    'address': _None,
    'postal_code': _None,
    'location': _None,
    'country': _None,
    'birth_name': _None,
    'address_supplement2': _None,
    'address2': _None,
    'postal_code2': _None,
    'location2': _None,
    'country2': _None,
    'weblink': _None,
    'specialisation': _None,
    'affiliation': _None,
    'timeline': _None,
    'interests': _None,
    'free_form': _None,
    'trial_member': _None,
    'decided_search': _None,
    'bub_search': _None,
    'foto': _None,
    'paper_expuls': _None,
}


def _PERSONA_CDE_CREATION(): return {
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _birthday,
    'telephone': _phone_or_None,
    'mobile': _phone_or_None,
    'address_supplement': _str_or_None,
    'address': _str_or_None,
    'postal_code': _printable_ascii_or_None,
    'location': _str_or_None,
    'country': _str_or_None,
    'birth_name': _str_or_None,
    'address_supplement2': _str_or_None,
    'address2': _str_or_None,
    'postal_code2': _printable_ascii_or_None,
    'location2': _str_or_None,
    'country2': _str_or_None,
    'weblink': _str_or_None,
    'specialisation': _str_or_None,
    'affiliation': _str_or_None,
    'timeline': _str_or_None,
    'interests': _str_or_None,
    'free_form': _str_or_None,
    'trial_member': _bool,
    'decided_search': _bool,
    'bub_search': _bool,
    # 'foto': _str_or_None, # No foto -- this is another special
    'paper_expuls': _bool,
}


def _PERSONA_EVENT_CREATION(): return {
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _birthday,
    'telephone': _phone_or_None,
    'mobile': _phone_or_None,
    'address_supplement': _str_or_None,
    'address': _str_or_None,
    'postal_code': _printable_ascii_or_None,
    'location': _str_or_None,
    'country': _str_or_None,
}


def _PERSONA_COMMON_FIELDS(): return {
    'username': _email,
    'notes': _str_or_None,
    'is_meta_admin': _bool,
    'is_core_admin': _bool,
    'is_cde_admin': _bool,
    'is_finance_admin': _bool,
    'is_event_admin': _bool,
    'is_ml_admin': _bool,
    'is_assembly_admin': _bool,
    'is_cdelokal_admin': _bool,
    'is_cde_realm': _bool,
    'is_event_realm': _bool,
    'is_ml_realm': _bool,
    'is_assembly_realm': _bool,
    'is_member': _bool,
    'is_searchable': _bool,
    'is_archived': _bool,
    'is_active': _bool,
    'display_name': _str,
    'given_names': _str,
    'family_name': _str,
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _birthday,
    'telephone': _phone_or_None,
    'mobile': _phone_or_None,
    'address_supplement': _str_or_None,
    'address': _str_or_None,
    'postal_code': _printable_ascii_or_None,
    'location': _str_or_None,
    'country': _str_or_None,
    'birth_name': _str_or_None,
    'address_supplement2': _str_or_None,
    'address2': _str_or_None,
    'postal_code2': _printable_ascii_or_None,
    'location2': _str_or_None,
    'country2': _str_or_None,
    'weblink': _str_or_None,
    'specialisation': _str_or_None,
    'affiliation': _str_or_None,
    'timeline': _str_or_None,
    'interests': _str_or_None,
    'free_form': _str_or_None,
    'balance': _non_negative_decimal,
    'trial_member': _bool,
    'decided_search': _bool,
    'bub_search': _bool,
    'foto': _str_or_None,
    'paper_expuls': _bool_or_None,
}


@_addvalidator
def _persona(val, argname=None, *, creation=False, transition=False,
             _convert=True, _ignore_warnings=False):
    """Check a persona data set.

    This is a bit tricky since attributes have different constraints
    according to which status a persona has. Since an all-encompassing
    solution would be quite tedious we expect status-bits only in case
    of creation and transition and apply restrictive tests in all other
    cases.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :type transition: bool
    :param transition: If ``True`` test the data set on fitness for changing
      the realms of a persona.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "persona"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation and transition:
        raise RuntimeError(
            n_("Only one of creation, transition may be specified."))
    if creation:
        temp, errs = _examine_dictionary_fields(
            val, _PERSONA_TYPE_FIELDS, {}, allow_superfluous=True,
            _convert=_convert, _ignore_warnings=_ignore_warnings)
        if errs:
            return temp, errs
        temp.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_cdelokal_admin': False,
        })
        roles = extract_roles(temp)
        optional_fields = {}
        mandatory_fields = copy.deepcopy(_PERSONA_BASE_CREATION())
        if "cde" in roles:
            mandatory_fields.update(_PERSONA_CDE_CREATION())
        if "event" in roles:
            mandatory_fields.update(_PERSONA_EVENT_CREATION())
        # ml and assembly define no custom fields
    elif transition:
        realm_checks = {
            'is_cde_realm': _PERSONA_CDE_CREATION(),
            'is_event_realm': _PERSONA_EVENT_CREATION(),
            'is_ml_realm': {},
            'is_assembly_realm': {},
        }
        mandatory_fields = {'id': _id}
        for key, checkers in realm_checks.items():
            if val.get(key):
                mandatory_fields.update(checkers)
        optional_fields = {key: _bool for key in realm_checks}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = _PERSONA_COMMON_FIELDS()
    val, errs = _examine_dictionary_fields(val, mandatory_fields,
                                           optional_fields, _convert=_convert,
                                           _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    for suffix in ("", "2"):
        if val.get('postal_code' + suffix):
            postal_code, e = _german_postal_code(
                val['postal_code' + suffix], 'postal_code' + suffix,
                aux=val.get('country' + suffix), _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            val['postal_code' + suffix] = postal_code
            errs.extend(e)
    if errs:
        return None, errs
    return val, errs


def parse_date(val: str) -> datetime.date:
    """Make a string into a date.

    We only support a limited set of formats to avoid any surprises
    """
    formats = (("%Y-%m-%d", 10), ("%Y%m%d", 8), ("%d.%m.%Y", 10),
               ("%m/%d/%Y", 10), ("%d.%m.%y", 8))
    for fmt, _ in formats:
        try:
            return datetime.datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    # Shorten strings to allow datetimes as inputs
    for fmt, length in formats:
        try:
            return datetime.datetime.strptime(val[:length], fmt).date()
        except ValueError:
            pass
    raise ValueError(n_("Invalid date string."))


# TODO move this above _persona stuff?
@_add_typed_validator
def _date(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs
) -> datetime.date:
    if _convert and isinstance(val, str) and len(val.strip()) >= 6:
        try:
            val = parse_date(val)
        except (ValueError, TypeError) as e:  # TODO TypeError should not occur
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for date."))) from e
    if isinstance(val, datetime.datetime):
        # TODO why not just use the subclass
        # necessary: isinstance(datetime.datetime.now(), datetime.date) == True
        val = val.date()
    if not isinstance(val, datetime.date):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a datetime.date.")))
    return val


@_add_typed_validator
def _birthday(val: Any, argname: str = None, **kwargs) -> Birthday:
    val = _date(val, argname=argname, **kwargs)
    if now().date() < val:
        raise ValidationSummary(ValueError(
            argname, n_("A birthday must be in the past.")))
    return Birthday(val)


def parse_datetime(
    val: str, default_date: datetime.date = None
) -> datetime.date:
    """Make a string into a datetime.

    We only support a limited set of formats to avoid any surprises
    """
    date_formats = ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%d.%m.%y")
    connectors = ("T", " ")
    time_formats = (
        "%H:%M:%S.%f%z", "%H:%M:%S%z", "%H:%M:%S.%f", "%H:%M:%S", "%H:%M")
    formats = itertools.chain(
        map("".join, itertools.product(date_formats, connectors, time_formats)),
        map(" ".join, itertools.product(time_formats, date_formats))
    )
    ret = None
    for fmt in formats:
        try:
            ret = datetime.datetime.strptime(val, fmt)
            break
        except ValueError:
            pass
    if ret is None and default_date:
        for fmt in time_formats:
            try:
                # TODO if we get to here this should be unparseable?
                ret = datetime.datetime.strptime(val, fmt)
                ret = ret.replace(
                    year=default_date.year, month=default_date.month,
                    day=default_date.day)
                break
            except ValueError:
                pass
    if ret is None:
        # TODO is isoformat not included above?
        ret = datetime.datetime.fromisoformat(val)
    # TODO what if ret is still None?
    if ret.tzinfo is None:
        timezone: pytz.BaseTzInfo = _BASICCONF["DEFAULT_TIMEZONE"]
        ret = timezone.localize(ret)
    return ret.astimezone(pytz.utc)


@_add_typed_validator
def _datetime(
    val: Any, argname: str = None, *,
    _convert: bool = True, default_date: datetime.date = None, **kwargs
) -> datetime.datetime:
    """
    :param default_date: If the user-supplied value specifies only a time, this
      parameter allows to fill in the necessary date information to fill
      the gap.
    """
    if _convert and isinstance(val, str) and len(val.strip()) >= 5:
        try:
            val = parse_datetime(val, default_date)
        except (ValueError, TypeError) as e:  # TODO should never be TypeError?
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for datetime."))) from e
    if not isinstance(val, datetime.datetime):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a datetime.datetime.")))
    return val


@_add_typed_validator
def _single_digit_int(
    val: Any, argname: str = None, **kwargs
) -> SingleDigitInt:
    """Like _int, but between +9 and -9."""
    val = _int(val, argname, **kwargs)
    if not -9 <= val <= 9:
        raise ValidationSummary(ValueError(
            argname, n_("More than one digit.")))
    return SingleDigitInt(val)


@_add_typed_validator
def _phone(
    val: Any, argname: str = None, **kwargs
) -> Phone:
    val = _printable_ascii(val, argname, **kwargs)
    orig = val.strip()
    val = ''.join(c for c in val if c in '+1234567890')

    if len(val) < 7:
        raise ValidationSummary(ValueError(argname, n_("Too short.")))

    # This is pretty horrible, but seems to be the best way ...
    # It works thanks to the test-suite ;)

    errs = ValidationSummary()
    retval = "+"
    # first the international part
    if val.startswith(("+", "00")):
        for prefix in ("+", "00"):
            if val.startswith(prefix):
                val = val[len(prefix):]
        for code in ITU_CODES:
            if val.startswith(code):
                retval += code
                val = val[len(code):]
                break
        else:
            errs.append(ValueError(argname, n_("Invalid international part.")))
        if retval == "+49" and not val.startswith("0"):
            val = "0" + val
    else:
        retval += "49"
    # now the national part
    if retval == "+49":
        # german stuff here
        if not val.startswith("0"):
            errs.append(ValueError(argname, n_("Invalid national part.")))
        else:
            val = val[1:]
        for length in range(1, 7):
            if val[:length] in GERMAN_PHONE_CODES:
                retval += " ({}) {}".format(val[:length], val[length:])
                if length + 2 >= len(val):
                    errs.append(ValueError(argname, n_("Invalid local part.")))
                break
        else:
            errs.append(ValueError(argname, n_("Invalid national part.")))
    else:
        index = 0
        try:
            index = orig.index(retval[1:]) + len(retval) - 1
        except ValueError:
            errs.append(ValueError(argname, n_("Invalid international part.")))
        # this will terminate since we know that there are sufficient digits
        while not orig[index] in string.digits:
            index += 1
        rest = orig[index:]
        sep = ''.join(c for c in rest if c not in string.digits)
        try:
            national = rest[:rest.index(sep)]
            local = rest[rest.index(sep) + len(sep):]
            if not len(national) or not len(local):
                raise ValidationSummary()  # TODO more specific?
            retval += " ({}) {}".format(national, local)
        except ValueError:
            retval += " " + val

    if errs:
        raise errs

    return Phone(retval)


@_add_typed_validator
def _german_postal_code(
    val: Any, argname: str = None, *,
    aux: str = None, _ignore_warnings: bool = False, **kwargs
) -> GermanPostalCode:
    """
    :param aux: Additional information. In this case the country belonging
        to the postal code.
    :param _ignore_warnings: If True, ignore invalid german postcodes.
    """
    val = _printable_ascii(
        val, argname, _ignore_warnings=_ignore_warnings, **kwargs)
    val = val.strip()  # TODO remove strip?
    # TODO change aux? Optional[str] -> str with default of "" or "Deutschland"?
    if not aux or aux == "Deutschland":
        if val not in GERMAN_POSTAL_CODES and not _ignore_warnings:
            raise ValidationWarning(argname, n_("Invalid german postal code."))
    return GermanPostalCode(val)


def _GENESIS_CASE_COMMON_FIELDS(): return {
    'username': _email,
    'given_names': _str,
    'family_name': _str,
    'realm': _str,
    'notes': _str,
}


def _GENESIS_CASE_OPTIONAL_FIELDS(): return {
    'case_status': _enum_genesisstati,
    'reviewer': _id,
}


def _GENESIS_CASE_ADDITIONAL_FIELDS(): return {
    'gender': _enum_genders,
    'birthday': _birthday,
    'telephone': _phone_or_None,
    'mobile': _phone_or_None,
    'address_supplement': _str_or_None,
    'address': _str,
    'postal_code': _printable_ascii_or_None,
    'location': _str,
    'country': _str_or_None,
    'birth_name': _str_or_None,
    'attachment': _str,
}


@_addvalidator
def _genesis_case(val, argname=None, *, creation=False, _convert=True,
                  _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
   :type _ignore_warnings: bool
    :type _ignore_warnings: bool
    :param _ignore_warnings: If True, ignore ValidationWarnings.
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "genesis_case"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    additional_fields = {}
    if 'realm' in val:
        if val['realm'] not in REALM_SPECIFIC_GENESIS_FIELDS:
            errs.append(('realm', ValueError(n_(
                "This realm is not supported for genesis."))))
        else:
            additional_fields = {
                k: v for k, v in _GENESIS_CASE_ADDITIONAL_FIELDS().items()
                if k in REALM_SPECIFIC_GENESIS_FIELDS[val['realm']]}
    else:
        raise ValueError(n_("Must specify realm."))

    if creation:
        mandatory_fields = dict(_GENESIS_CASE_COMMON_FIELDS(),
                                **additional_fields)
        optional_fields = {}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_GENESIS_CASE_COMMON_FIELDS(),
                               **_GENESIS_CASE_OPTIONAL_FIELDS(),
                               **additional_fields)

    # allow_superflous=True will result in superfluous keys being removed.
    val, e = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        allow_superfluous=True, _ignore_warnings=_ignore_warnings)
    errs.extend(e)
    if errs:
        return val, errs

    if val.get('postal_code'):
        postal_code, e = _german_postal_code(
            val['postal_code'], 'postal_code', aux=val.get('country'),
            _convert=_convert, _ignore_warnings=_ignore_warnings)
        val['postal_code'] = postal_code
        errs.extend(e)

    return val, errs


def _PRIVILEGE_CHANGE_COMMON_FIELDS(): return {
    'persona_id': _id,
    'submitted_by': _id,
    'status': _enum_privilegechangestati,
    'notes': _str,
}


def _PRIVILEGE_CHANGE_OPTIONAL_FIELDS(): return {
    'is_meta_admin': _bool_or_None,
    'is_core_admin': _bool_or_None,
    'is_cde_admin': _bool_or_None,
    'is_finance_admin': _bool_or_None,
    'is_event_admin': _bool_or_None,
    'is_ml_admin': _bool_or_None,
    'is_assembly_admin': _bool_or_None,
    'is_cdelokal_admin': _bool_or_None,
}


@_addvalidator
def _privilege_change(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)]
    """
    argname = argname or "privilege_change"

    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs

    val, errs = _examine_dictionary_fields(
        val, _PRIVILEGE_CHANGE_COMMON_FIELDS(),
        _PRIVILEGE_CHANGE_OPTIONAL_FIELDS(), _convert=_convert,
        _ignore_warnings=_ignore_warnings)

    return val, errs


# TODO also move these up?
@_add_typed_validator
def _input_file(
    val: Any, argname: str = None, **kwargs
) -> InputFile:
    if not isinstance(val, werkzeug.datastructures.FileStorage):
        raise ValidationSummary(TypeError(argname, n_("Not a FileStorage.")))
    blob = val.read()
    if not blob:
        raise ValidationSummary(ValueError(argname, n_("Empty FileStorage.")))
    return InputFile(blob)


# TODO check encoding or maybe use union of literals
# TODO get rid of encoding and use try-catch with UnicodeDecodeError?
@_add_typed_validator
def _csvfile(
    val: Any, argname: str = None, *,
    encoding: str = "utf-8-sig", **kwargs
) -> CSVFile:
    """
    We default to 'utf-8-sig', since it behaves exactly like 'utf-8' if the
    file is 'utf-8' but it gets rid of the BOM if the file is 'utf-8-sig'.
    """
    val = _input_file(val, argname, **kwargs)
    mime = magic.from_buffer(val, mime=True)
    if mime not in ("text/csv", "text/plain"):
        raise ValidationSummary(ValueError(
            argname, n_("Only text/csv allowed.")))
    val = _str(val.decode(encoding).strip(), argname, **kwargs)
    return CSVFile(val)


@_add_typed_validator
def _profilepic(
    val: Any, argname: str = None, *,
    file_storage: bool = True, **kwargs
) -> ProfilePicture:
    """
    Validate a file for usage as a profile picture.

    Limit file size, resolution and ratio.

    :param file_storage: If `True` expect the input to be a
        `werkzeug.FileStorage`, otherwise expect a `bytes` object.
    """
    if file_storage:
        val = _input_file(val, argname, **kwargs)
    else:
        val = _bytes(val, argname, **kwargs)

    errs = ValidationSummary()
    if len(val) < 2 ** 10:
        errs.append(ValueError(argname, n_("Too small.")))
    if len(val) > 2 ** 17:
        errs.append(ValueError(argname, n_("Too big.")))

    mime = magic.from_buffer(val, mime=True)
    if mime not in ("image/jpeg", "image/jpg", "image/png"):
        errs.append(ValueError(
            argname, n_("Only jpg and png allowed.")))
    if errs:
        raise errs

    image = PIL.Image.open(io.BytesIO(val))
    width, height = image.size
    if width / height < 0.9 or height / width < 0.9:
        errs.append(ValueError(argname, n_("Not square enough.")))
    if width * height < 5000:
        errs.append(ValueError(argname, n_("Resolution too small.")))

    if errs:
        raise errs

    return ProfilePicture(val)


@_add_typed_validator
def _pdffile(
    val: Any, argname: str = None, *,
    file_storage: bool = True, **kwargs
) -> PDFFile:
    """Validate a file as a pdf.

    Limit the maximum file size.

    :param file_storage: If `True` expect the input to be a
        `werkzeug.FileStorage`, otherwise expect a `bytes` object.
    """
    if file_storage:
        val = _input_file(val, argname, **kwargs)
    else:
        val = _bytes(val, argname, **kwargs)

    errs = ValidationSummary()
    if len(val) > 2 ** 23:  # Disallow files bigger than 8 MB.
        errs.append(ValueError(argname, n_("Filesize too large.")))
    mime = magic.from_buffer(val, mime=True)
    if mime != "application/pdf":
        errs.append(ValueError(argname, n_("Only pdf allowed.")))

    if errs:
        raise errs

    return PDFFile(val)


@_add_typed_validator
def _pair_of_int(
    val: Any, argname: str = "pair", **kwargs
) -> Tuple[int, int]:
    """Validate a pair of integers."""

    val: List[int] = _list_of(val, _int, argname, **kwargs)

    try:
        a, b = val
    except ValueError as e:
        raise ValidationSummary(ValueError(
            argname, n_("Must contain exactly two elements."))) from e

    return (a, b)


@_addvalidator
def _period(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "period"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'billing_state': _id_or_None,
        'billing_done': _datetime,
        'billing_count': _non_negative_int,
        'ejection_state': _id_or_None,
        'ejection_done': _datetime,
        'ejection_count': _non_negative_int,
        'ejection_balance': _non_negative_decimal,
        'balance_state': _id_or_None,
        'balance_done': _datetime,
        'balance_trialmembers': _non_negative_int,
        'balance_total': _non_negative_decimal,
    }
    return _examine_dictionary_fields(
        val, {'id': _id}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _expuls(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "expuls"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'addresscheck_state': _id_or_None,
        'addresscheck_done': _datetime,
        'addresscheck_count': _non_negative_int,
    }
    return _examine_dictionary_fields(
        val, {'id': _id}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _LASTSCHRIFT_COMMON_FIELDS(): return {
    'amount': _positive_decimal,
    'iban': _iban,
    'account_owner': _str_or_None,
    'account_address': _str_or_None,
    'notes': _str_or_None,
}


def _LASTSCHRIFT_OPTIONAL_FIELDS(): return {
    'granted_at': _datetime,
    'revoked_at': _datetime_or_None,
}


@_addvalidator
def _lastschrift(val, argname=None, *, creation=False, _convert=True,
                 _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lastschrift"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(), persona_id=_id)
        optional_fields = _LASTSCHRIFT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(),
                               **_LASTSCHRIFT_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    return val, errs


# TODO move above
@_add_typed_validator
def _iban(
    val: Any, argname: str = "iban", **kwargs
) -> IBAN:
    val = _str(val, argname, **kwargs).upper().replace(' ', '')
    errs = ValidationSummary()

    if len(val) < 5:
        errs.append(ValueError(argname, n_("Too short.")))
        raise errs

    country_code, check_digits, bban = val[:2], val[2:4], val[4:]

    for char in country_code:
        if char not in string.ascii_uppercase:
            errs.append(ValueError(argname, n_(
                "Must start with country code.")))
    for char in check_digits:
        if char not in string.digits:
            errs.append(ValueError(argname, n_(
                "Must have digits for checksum.")))
    for char in bban:
        if char not in string.digits + string.ascii_uppercase:
            errs.append(ValueError(argname, n_("Invalid character in IBAN.")))
    if country_code not in IBAN_LENGTHS:
        errs.append(ValueError(argname, n_(
            "Unknown or unsupported Country Code.")))

    if not errs:
        if len(val) != IBAN_LENGTHS[country_code]:
            errs.append(ValueError(argname, n_(
                "Invalid length %(len)s for Country Code %(code)s."
                " Expexted length %(exp)s."),
                {"len": len(val), "code": country_code,
                 "exp": IBAN_LENGTHS[country_code]}
            ))
        temp = ''.join(c if c in string.digits else str(10 + ord(c) - ord('A'))
                       for c in bban + country_code + check_digits)
        if int(temp) % 97 != 1:
            errs.append(ValueError(argname, n_("Invalid checksum.")))

    if errs:
        raise errs

    return IBAN(val)


def _LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS(): return {
    'amount': _positive_decimal,
    'status': _enum_lastschrifttransactionstati,
    'issued_at': _datetime,
    'processed_at': _datetime_or_None,
    'tally': _decimal_or_None,
}


@_addvalidator
def _lastschrift_transaction(val, argname=None, *, creation=False,
                             _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lastschrift_transaction"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = {
            'lastschrift_id': _id,
            'period_id': _id,
        }
        optional_fields = _LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS()
    else:
        return None, [(argname, ValueError(n_("Modification of lastschrift"
                                              " transactions not supported.")))]
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    return val, errs


_SEPA_TRANSACTIONS_FIELDS = {
    'issued_at': _datetime,
    'lastschrift_id': _id,
    'period_id': _id,
    'mandate_reference': _str,
    'amount': _positive_decimal,
    'iban': _iban,
    'mandate_date': _date,
    'account_owner': _str,
    'unique_id': _str,
    'subject': _str,
    'type': _str,
}
_SEPA_TRANSACTIONS_LIMITS = {
    'account_owner': 70,
    'subject': 140,
    'mandate_reference': 35,
    'unique_id': 35,
}


@_addvalidator
def _sepa_transactions(val, argname=None, *, _convert=True,
                       _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (tuple or None, [(str or None, exception)])
    """
    argname = argname or "sepa_transactions"
    val, errs = _iterable(val, argname, _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_TRANSACTIONS_FIELDS
    optional_fields = {}
    ret = []
    for entry in val:
        entry, e = _mapping(entry, argname, _convert=_convert,
                            _ignore_warnings=_ignore_warnings)
        if e:
            errs.extend(e)
            continue
        entry, e = _examine_dictionary_fields(
            entry, mandatory_fields, optional_fields, _convert=_convert,
            _ignore_warnings=_ignore_warnings)
        if e:
            errs.extend(e)
            continue
        for attribute, validator in _SEPA_TRANSACTIONS_FIELDS.items():
            if validator == _str:
                entry[attribute] = asciificator(entry[attribute])
            if attribute in _SEPA_TRANSACTIONS_LIMITS:
                if len(entry[attribute]) > _SEPA_TRANSACTIONS_LIMITS[attribute]:
                    errs.append((attribute, ValueError(n_("Too long."))))
        if entry['type'] not in ("OOFF", "FRST", "RCUR"):
            errs.append(('type', ValueError(n_("Invalid constant."))))
        if errs:
            continue
        ret.append(entry)
    return ret, errs


_SEPA_META_FIELDS = {
    'message_id': _str,
    'total_sum': _positive_decimal,
    'partial_sums': _mapping,
    'count': _int,
    'sender': _mapping,
    'payment_date': _date,
}
_SEPA_SENDER_FIELDS = {
    'name': _str,
    'address': _iterable,
    'country': _str,
    'iban': _iban,
    'glaeubigerid': _str,
}
_SEPA_META_LIMITS = {
    'message_id': 35,
    # 'name': 70, easier to check by hand
    # 'address': 70, has to be checked by hand
    'glaeubigerid': 35,
}


@_addvalidator
def _sepa_meta(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "sepa_meta"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_META_FIELDS
    optional_fields = {}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_SENDER_FIELDS
    val['sender'], errs = _examine_dictionary_fields(
        val['sender'], mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    for attribute, validator in _SEPA_META_FIELDS.items():
        if validator == _str:
            val[attribute] = asciificator(val[attribute])
        if attribute in _SEPA_META_LIMITS:
            if len(val[attribute]) > _SEPA_META_LIMITS[attribute]:
                errs.append((attribute, ValueError(n_("Too long."))))
    if val['sender']['country'] != "DE":
        errs.append(('country', ValueError(n_("Unsupported constant."))))
    if len(val['sender']['address']) != 2:
        errs.append(('address', ValueError(n_("Exactly two lines required."))))
    val['sender']['address'] = tuple(asciificator(x)
                                     for x in val['sender']['address'])
    for line in val['sender']['address']:
        if len(line) > 70:
            errs.append(('address', ValueError(n_("Too long."))))
    for attribute, validator in _SEPA_SENDER_FIELDS.items():
        if validator == _str:
            val['sender'][attribute] = asciificator(val['sender'][attribute])
    if len(val['sender']['name']) > 70:
        errs.append(('name', ValueError(n_("Too long."))))
    if errs:
        return None, errs
    return val, errs


@_add_typed_validator
def _safe_str(
    val: Any, argname: str = None, **kwargs
) -> SafeStr:
    """This allows alpha-numeric, whitespace and known good others."""
    ALLOWED = ".,-+()/"
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()

    for char in val:
        if not (char.isalnum() or char.isspace() or char in ALLOWED):
            # TODO bundle these? e.g. forbidden chars: abc...
            errs.append(ValueError(argname, n_(
                "Forbidden character (%(char)s)."), {'char': char}))
    if errs:
        raise errs

    return SafeStr(val)


@_addvalidator
def _meta_info(val, keys, argname=None, *, _convert=True,
               _ignore_warnings=False):
    """
    :type val: object
    :type keys: [str]
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "meta_info"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_fields = {}
    optional_fields = {key: _str_or_None for key in keys}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    return val, errs


def _INSTITUTION_COMMON_FIELDS(): return {
    'title': _str,
    'moniker': _str,
}


@_addvalidator
def _institution(val: Any, argname: str = "institution", *,
                 creation: bool = False, _convert: bool = True,
                 _ignore_warnings: bool = False):
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    val = _mapping(val, argname, _convert=_convert,
                   _ignore_warnings=_ignore_warnings)

    if creation:
        mandatory_fields = _INSTITUTION_COMMON_FIELDS()
        optional_fields = {}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = _INSTITUTION_COMMON_FIELDS()
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _PAST_EVENT_COMMON_FIELDS(): return {
    'title': _str,
    'shortname': _str,
    'institution': _id,
    'tempus': _date,
    'description': _str_or_None,
}


def _PAST_EVENT_OPTIONAL_FIELDS(): return {
    'notes': _str_or_None
}


@_addvalidator
def _past_event(val, argname=None, *, creation=False, _convert=True,
                _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "past_event"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _PAST_EVENT_COMMON_FIELDS()
        optional_fields = _PAST_EVENT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_PAST_EVENT_COMMON_FIELDS(),
                               **_PAST_EVENT_OPTIONAL_FIELDS())
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _EVENT_COMMON_FIELDS(): return {
    'title': _str,
    'institution': _id,
    'description': _str_or_None,
    'shortname': _identifier,
}


def _EVENT_OPTIONAL_FIELDS(): return {
    'offline_lock': _bool,
    'is_visible': _bool,
    'is_course_list_visible': _bool,
    'is_course_state_visible': _bool,
    'use_additional_questionnaire': _bool,
    'registration_start': _datetime_or_None,
    'registration_soft_limit': _datetime_or_None,
    'registration_hard_limit': _datetime_or_None,
    'notes': _str_or_None,
    'is_participant_list_visible': _bool,
    'courses_in_participant_list': _bool,
    'is_cancelled': _bool,
    'is_archived': _bool,
    'iban': _iban_or_None,
    'nonmember_surcharge': _non_negative_decimal,
    'orgas': _iterable,
    'mail_text': _str_or_None,
    'parts': _mapping,
    'fields': _mapping,
    'fee_modifiers': _mapping,
    'registration_text': _str_or_None,
    'orga_address': _email_or_None,
    'lodge_field': _id_or_None,
    'camping_mat_field': _id_or_None,
    'course_room_field': _id_or_None,
}


@_addvalidator
def _event(val, argname=None, *, creation=False, _convert=True,
           _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_COMMON_FIELDS()
        optional_fields = _EVENT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_EVENT_COMMON_FIELDS(),
                               **_EVENT_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'registration_soft_limit' in val and 'registration_hard_limit' in val:
        if (val['registration_soft_limit']
                and val['registration_hard_limit']
                and (val['registration_soft_limit']
                     > val['registration_hard_limit'])):
            errs.append(("registration_soft_limit",
                         ValueError(
                             n_("Must be before or equal to hard limit."))))
        if val.get('registration_start') and (
                val['registration_soft_limit'] and
                val['registration_start'] > val['registration_soft_limit']
                or val['registration_hard_limit'] and
                val['registration_start'] > val['registration_hard_limit']):
            errs.append(("registration_start",
                         ValueError(n_("Must be before hard and soft limit."))))
    if 'orgas' in val:
        orgas = set()
        for anid in val['orgas']:
            v, e = _id(anid, 'orgas', _convert=_convert,
                       _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                orgas.add(v)
        val['orgas'] = orgas
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            anid, e = _int(anid, 'parts', _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                part, ee = _event_part_or_None(
                    part, 'parts', creation=creation,
                    _convert=_convert, _ignore_warnings=_ignore_warnings)
                if ee:
                    errs.extend(ee)
                else:
                    newparts[anid] = part
        val['parts'] = newparts
    if 'fields' in val:
        newfields = {}
        for anid, field in val['fields'].items():
            anid, e = _int(anid, 'fields', _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                field, ee = _event_field_or_None(
                    field, 'fields', creation=creation,
                    _convert=_convert, _ignore_warnings=_ignore_warnings)
                if ee:
                    errs.extend(ee)
                else:
                    newfields[anid] = field
        val['fields'] = newfields
    if 'fee_modifiers' in val:
        new_modifiers = {}
        for anid, fee_modifier in val['fee_modifiers'].items():
            anid, e = _int(anid, 'fee_modifiers', _convert=_convert)
            if e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                fee_modifier, ee = _event_fee_modifier_or_None(
                    fee_modifier, 'fee_modifiers',
                    creation=creation, _convert=_convert)
                if ee:
                    errs.extend(ee)
                else:
                    new_modifiers[anid] = fee_modifier
        msg = n_("Must not have multiple fee modifiers linked to the same"
                 " field in one event part.")
        for e1, e2 in itertools.combinations(
                filter(None, val['fee_modifiers'].values()), 2):
            if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:
                if e1['part_id'] == e2['part_id']:
                    errs.append(('fee_modifiers', ValueError(msg)))
    return val, errs


_EVENT_PART_COMMON_FIELDS = {
    'title': _str,
    'shortname': _str,
    'part_begin': _date,
    'part_end': _date,
    'fee': _non_negative_decimal,
    'tracks': _mapping,
}


@_addvalidator
def _event_part(val, argname=None, *, creation=False, _convert=True,
                _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_part"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_PART_COMMON_FIELDS
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_PART_COMMON_FIELDS
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if ('part_begin' in val and 'part_end' in val
            and val['part_begin'] > val['part_end']):
        errs.append(("part_end",
                     ValueError(n_("Must be later than part begin."))))
    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            anid, e = _int(anid, 'tracks', _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                if creation:
                    track, ee = _event_track(
                        track, 'tracks', _convert=_convert, creation=True,
                        _ignore_warnings=_ignore_warnings)
                else:
                    track, ee = _event_track_or_None(
                        track, 'tracks', _convert=_convert,
                        _ignore_warnings=_ignore_warnings)
                if ee:
                    errs.extend(ee)
                else:
                    newtracks[anid] = track
        val['tracks'] = newtracks
    return val, errs


_EVENT_TRACK_COMMON_FIELDS = {
    'title': _str,
    'shortname': _str,
    'num_choices': _non_negative_int,
    'min_choices': _non_negative_int,
    'sortkey': _int,
}


@_addvalidator
def _event_track(val, argname=None, *, creation=False, _convert=True,
                 _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "tracks"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_TRACK_COMMON_FIELDS
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_TRACK_COMMON_FIELDS
    val, errs = _examine_dictionary_fields(val, mandatory_fields,
                                           optional_fields, _convert=_convert,
                                           _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if ('num_choices' in val and 'min_choices' in val
            and val['min_choices'] > val['num_choices']):
        errs.append(
            ("min_choices",
             ValueError(
                 n_("Must be less or equal than total Course Choices."))))
    return val, errs


def _EVENT_FIELD_COMMON_FIELDS(extra_suffix): return {
    'kind{}'.format(extra_suffix): _enum_fielddatatypes,
    'association{}'.format(extra_suffix): _enum_fieldassociations,
    'entries{}'.format(extra_suffix): _any,
}


@_addvalidator
def _event_field(val, argname=None, *, creation=False, _convert=True,
                 _ignore_warnings=False,
                 extra_suffix=''):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :type extra_suffix: str
    :param extra_suffix: Suffix appended to all keys. This is due to the
      necessity of the frontend to create unambiguous names.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_field"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    field_name_key = "field_name{}".format(extra_suffix)
    if creation:
        spec = _EVENT_FIELD_COMMON_FIELDS(extra_suffix)
        spec[field_name_key] = _restrictive_identifier
        mandatory_fields = spec
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_FIELD_COMMON_FIELDS(extra_suffix)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    entries_key = "entries{}".format(extra_suffix)
    kind_key = "kind{}".format(extra_suffix)
    if not val.get(entries_key, True):
        val[entries_key] = None
    if entries_key in val and val[entries_key] is not None:
        if isinstance(val[entries_key], str) and _convert:
            val[entries_key] = tuple(tuple(y.strip() for y in x.split(';', 1))
                                     for x in val[entries_key].split('\n'))
        oldentries, e = _iterable(val[entries_key], entries_key,
                                  _convert=_convert,
                                  _ignore_warnings=_ignore_warnings)
        seen_values = set()
        if e:
            errs.extend(e)
        else:
            entries = []
            for idx, entry in enumerate(oldentries):
                try:
                    value, description = entry
                except (ValueError, TypeError):
                    msg = n_("Invalid entry in line %(line)s.")
                    errs.append((entries_key,
                                 ValueError(msg, {'line': idx + 1})))
                else:
                    # Validate value according to type and use the opportunity
                    # to normalize the value by transforming it back to string
                    value, e = _by_field_datatype(
                        value, entries_key,
                        kind=val.get(kind_key, FieldDatatypes.str),
                        _convert=_convert, _ignore_warnings=_ignore_warnings)
                    description, ee = _str(
                        description, entries_key, _convert=_convert,
                        _ignore_warnings=_ignore_warnings)
                    if value in seen_values:
                        e.append((entries_key,
                                  ValueError(n_("Duplicate value."))))
                    if e or ee:
                        errs.extend(e)
                        errs.extend(ee)
                        continue
                    entries.append((value, description))
                    seen_values.add(value)
            val[entries_key] = entries
    return val, errs


def _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix): return {
    "modifier_name{}".format(extra_suffix): _restrictive_identifier,
    "amount{}".format(extra_suffix): _decimal,
    "part_id{}".format(extra_suffix): _id,
    "field_id{}".format(extra_suffix): _id,
}


@_addvalidator
def _event_fee_modifier(val, argname=None, *, creation=False,
                        _convert=True, extra_suffix=''):
    argname = argname or "fee_modifiers"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix)
        optional_fields = {}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    return val, errs


def _PAST_COURSE_COMMON_FIELDS(): return {
    'nr': _str,
    'title': _str,
    'description': _str_or_None,
}


@_addvalidator
def _past_course(val, argname=None, *, creation=False, _convert=True,
                 _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "past_course"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_PAST_COURSE_COMMON_FIELDS(), pevent_id=_id)
        optional_fields = {}
    else:
        # no pevent_id, since the associated event should be fixed
        mandatory_fields = {'id': _id}
        optional_fields = _PAST_COURSE_COMMON_FIELDS()
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _COURSE_COMMON_FIELDS(): return {
    'title': _str,
    'description': _str_or_None,
    'nr': _str,
    'shortname': _str,
    'instructors': _str_or_None,
    'max_size': _non_negative_int_or_None,
    'min_size': _non_negative_int_or_None,
    'notes': _str_or_None,
}


_COURSE_OPTIONAL_FIELDS = {
    'segments': _iterable,
    'active_segments': _iterable,
    'fields': _mapping,
}


@_addvalidator
def _course(val, argname=None, *, creation=False, _convert=True,
            _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "course"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_COURSE_COMMON_FIELDS(), event_id=_id)
        optional_fields = _COURSE_OPTIONAL_FIELDS
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': _id}
        optional_fields = dict(_COURSE_COMMON_FIELDS(),
                               **_COURSE_OPTIONAL_FIELDS)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'segments' in val:
        segments = set()
        for anid in val['segments']:
            v, e = _id(anid, 'segments', _convert=_convert,
                       _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                segments.add(v)
        val['segments'] = segments
    if 'active_segments' in val:
        active_segments = set()
        for anid in val['active_segments']:
            v, e = _id(anid, 'active_segments', _convert=_convert,
                       _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                active_segments.add(v)
        val['active_segments'] = active_segments
    if 'segments' in val and 'active_segments' in val:
        if not val['active_segments'] <= val['segments']:
            errs.append(('segments',
                         ValueError(
                             n_("Must be a superset of active segments."))))
    # the check of fields is delegated to _event_associated_fields
    return val, errs


def _REGISTRATION_COMMON_FIELDS(): return {
    'mixed_lodging': _bool,
    'list_consent': _bool,
    'notes': _str_or_None,
    'parts': _mapping,
    'tracks': _mapping,
}


def _REGISTRATION_OPTIONAL_FIELDS(): return {
    'parental_agreement': _bool,
    'real_persona_id': _id_or_None,
    'orga_notes': _str_or_None,
    'payment': _date_or_None,
    'amount_paid': _non_negative_decimal,
    'checkin': _datetime_or_None,
    'fields': _mapping
}


@_addvalidator
def _registration(val, argname=None, *, creation=False, _convert=True,
                  _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration"

    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        # creation does not allow fields for sake of simplicity
        mandatory_fields = dict(_REGISTRATION_COMMON_FIELDS(),
                                persona_id=_id, event_id=_id)
        optional_fields = _REGISTRATION_OPTIONAL_FIELDS()
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {'id': _id}
        optional_fields = dict(
            _REGISTRATION_COMMON_FIELDS(),
            **_REGISTRATION_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            anid, e = _id(anid, 'parts', _convert=_convert)
            part, ee = _registration_part_or_None(
                part, 'parts', _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                newparts[anid] = part
        val['parts'] = newparts
    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            anid, e = _id(anid, 'tracks', _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
            track, ee = _registration_track_or_None(
                track, 'tracks', _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                newtracks[anid] = track
        val['tracks'] = newtracks
    # the check of fields is delegated to _event_associated_fields
    return val, errs


@_addvalidator
def _registration_part(val, argname=None, *, _convert=True,
                       _ignore_warnings=False):
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration_part"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'status': _enum_registrationpartstati,
        'lodgement_id': _id_or_None,
        'is_camping_mat': _bool,
    }
    return _examine_dictionary_fields(
        val, {}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _registration_track(val, argname=None, *, _convert=True,
                        _ignore_warnings=False):
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration_track"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'course_id': _id_or_None,
        'course_instructor': _id_or_None,
        'choices': _iterable,
    }
    val, errs = _examine_dictionary_fields(
        val, {}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if 'choices' in val:
        newchoices = []
        for choice in val['choices']:
            choice, e = _id(choice, 'choices', _convert=_convert,
                            _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
                break
            else:
                newchoices.append(choice)
        val['choices'] = newchoices
    return val, errs


@_addvalidator
def _event_associated_fields(val, argname=None, fields=None, association=None,
                             *, _convert=True, _ignore_warnings=False):
    """Check fields associated to an event entity.

    This can be used for all different kinds of entities (currently
    registration, courses and lodgements) via the multiplexing in form of
    the ``association`` parameter.

    :type val: object
    :type argname: str or None
    :type fields: {int: dict}
    :type association: cdedb.constants.FieldAssociations
    :param fields: definition of the event specific fields which are available
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])

    """
    argname = argname or "fields"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    raw = copy.deepcopy(val)
    datatypes = {}
    for field in fields.values():
        if field['association'] == association:
            dt, errs = _enum_fielddatatypes(
                field['kind'], field['field_name'], _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if errs:
                return val, errs
            datatypes[field['field_name']] = getattr(
                current_module, "_{}_or_None".format(dt.name))
    optional_fields = {
        field['field_name']: datatypes[field['field_name']]
        for field in fields.values() if field['association'] == association
    }
    val, errs = _examine_dictionary_fields(
        val, {}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    lookup = {v['field_name']: k for k, v in fields.items()}
    for field in val:
        field_id = lookup[field]
        if fields[field_id]['entries'] is not None and val[field] is not None:
            if not any(str(raw[field]) == x
                       for x, _ in fields[field_id]['entries']):
                errs.append(
                    (field, ValueError(n_("Entry not in definition list."))))
    return val, errs


def _LODGEMENT_GROUP_FIELDS(): return {
    'moniker': _str,
}


@_addvalidator
def _lodgement_group(val, argname=None, *, creation=False, _convert=True,
                     _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set for fitness for creation
        of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lodgement group"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_LODGEMENT_GROUP_FIELDS(), event_id=_id)
        optional_fields = {}
    else:
        # no event_id, since the associated event should be fixed.
        mandatory_fields = {'id': _id}
        optional_fields = _LODGEMENT_GROUP_FIELDS()
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _LODGEMENT_COMMON_FIELDS(): return {
    'moniker': _str,
    'regular_capacity': _non_negative_int,
    'camping_mat_capacity': _non_negative_int,
    'notes': _str_or_None,
    'group_id': _id_or_None,
}


_LODGEMENT_OPTIONAL_FIELDS = {
    'fields': _mapping,
}


@_addvalidator
def _lodgement(val, argname=None, *, creation=False, _convert=True,
               _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lodgement"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_LODGEMENT_COMMON_FIELDS(), event_id=_id)
        optional_fields = _LODGEMENT_OPTIONAL_FIELDS
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': _id}
        optional_fields = dict(_LODGEMENT_COMMON_FIELDS(),
                               **_LODGEMENT_OPTIONAL_FIELDS)
    # the check of fields is delegated to _event_associated_fields
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


# TODO is kind optional?
@_addvalidator
def _by_field_datatype(val, argname=None, *, kind=None, _convert=True,
                       _ignore_warnings=False):
    """
    :type val: object
    :type kind: FieldDatatypes or int
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    kind = FieldDatatypes(kind)
    validator = getattr(current_module, "_{}".format(kind.name))
    val, errs = validator(val, argname, _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if kind == FieldDatatypes.date or kind == FieldDatatypes.datetime:
        val = val.isoformat()
    else:
        val = str(val)
    return val, errs


@_addvalidator
def _questionnaire(val, field_definitions, fee_modifiers, argname=None, *,
                   _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type field_definitions: Dict[int, Dict]
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: ([dict] or None, [(str or None, exception)])
    """
    argname = argname or "questionnaire"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    ret = {}
    fee_modifier_fields = {e['field_id'] for e in fee_modifiers.values()}
    for k, v in copy.deepcopy(val).items():
        k, e = _enum_questionnaireusages(k, argname, _convert=_convert,
                                         _ignore_warnings=_ignore_warnings)
        v, ee = _iterable(v, argname, _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
        if e or ee:
            errs.extend(e)
            errs.extend(ee)
        else:
            ret[k] = []
            mandatory_fields = {
                'field_id': _id_or_None,
                'title': _str_or_None,
                'info': _str_or_None,
                'input_size': _int_or_None,
                'readonly': _bool_or_None,
                'default_value': _str_or_None,
            }
            optional_fields = {
                'kind': _enum_questionnaireusages,
            }
            for value in v:
                value, e = _mapping(value, argname, _convert=_convert,
                                    _ignore_warnings=_ignore_warnings)
                if e:
                    errs.extend(e)
                    continue

                value, e = _examine_dictionary_fields(
                    value, mandatory_fields, optional_fields, _convert=_convert,
                    _ignore_warnings=_ignore_warnings)
                if 'kind' in value:
                    if value['kind'] != k:
                        msg = n_("Incorrect kind for this part of the"
                                 " questionnaire")
                        e.append(('kind', ValueError(msg)))
                else:
                    value['kind'] = k
                if e:
                    errs.extend(e)
                    continue
                if value['field_id'] and value['default_value']:
                    field = field_definitions.get(value['field_id'], None)
                    if not field:
                        msg = n_("Referenced field does not exist.")
                        errs.append(('default_value',
                                     KeyError(msg)))
                        continue
                    value['default_value'], e = _by_field_datatype(
                        value['default_value'], "default_value",
                        kind=field.get('kind', FieldDatatypes.str),
                        _convert=_convert, _ignore_warnings=_ignore_warnings)
                    errs.extend(e)
                field_id = value['field_id']
                if field_id and field_id in fee_modifier_fields:
                    if not k.allow_fee_modifier():
                        msg = n_("Inappropriate questionnaire usage for fee"
                                 " modifier field.")
                        errs.append(('kind', ValueError(msg)))
                if value['readonly'] and not k.allow_readonly():
                    msg = n_("Registration questionnaire rows may not be"
                             " readonly.")
                    errs.append(('readonly', ValueError(msg)))
                ret[k].append(value)
    all_rows = itertools.chain.from_iterable(ret.values())
    for e1, e2 in itertools.combinations(all_rows, 2):
        if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:
            msg = n_("Must not duplicate field.")
            errs.append(('field_id', ValueError(msg)))
    return ret, errs


# TODO move above
@_add_typed_validator
def _json(
    val: Any, argname: str = "json", *, _convert: bool = True, **kwargs
) -> JSON:
    """Deserialize a JSON payload.

    This is a bit different from many other validatiors in that it is not
    idempotent.

    :rtype: (dict or None, [(str or None, exception)])

    """
    if not _convert:
        raise RuntimeError("This is a conversion by definition.")
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8")  # TODO remove encoding argument?
        except UnicodeDecodeError as e:
            raise ValidationSummary(ValueError(
                argname, n_("Invalid UTF-8 sequence."))) from e
    val = _str(val, argname, _convert=_convert, **kwargs)
    try:
        data = json.loads(val)
    except json.decoder.JSONDecodeError as e:
        msg = n_("Invalid JSON syntax (line %(line)s, col %(col)s).")
        raise ValidationSummary(ValueError(
            argname, msg, {'line': e.lineno, 'col': e.colno})) from e
    return JSON(data)


@_addvalidator
def _serialized_event_upload(val, argname=None, *, _convert=True,
                             _ignore_warnings=False):
    """Check an event data set for import after offline usage.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "serialized_event_upload"
    val, errs = _input_file(val, argname, _convert=_convert,
                            _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    val, errs = _json(val, argname, _convert=_convert,
                      _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    return _serialized_event(val, argname, _convert=_convert,
                             _ignore_warnings=_ignore_warnings)


@_addvalidator
def _serialized_event(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """Check an event data set for import after offline usage.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "serialized_event"
    # First a basic check
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'kind' not in val or val['kind'] != "full":
        return None, [(argname, KeyError(n_(
            "Only full exports are supported.")))]

    mandatory_fields = {
        'EVENT_SCHEMA_VERSION': _pair_of_int,
        'kind': _str,
        'id': _id,
        'timestamp': _datetime,
        'event.events': _mapping,
        'event.event_parts': _mapping,
        'event.course_tracks': _mapping,
        'event.courses': _mapping,
        'event.course_segments': _mapping,
        'event.log': _mapping,
        'event.orgas': _mapping,
        'event.field_definitions': _mapping,
        'event.lodgement_groups': _mapping,
        'event.lodgements': _mapping,
        'event.registrations': _mapping,
        'event.registration_parts': _mapping,
        'event.registration_tracks': _mapping,
        'event.course_choices': _mapping,
        'event.questionnaire_rows': _mapping,
        'event.fee_modifiers': _mapping,
    }
    optional_fields = {
        'core.personas': _mapping,
    }
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if val['EVENT_SCHEMA_VERSION'] != EVENT_SCHEMA_VERSION:
        return None, [(argname, ValueError(n_("Schema version mismatch.")))]
    # Second a thorough investigation
    #
    # We reuse the existing validators, but have to augment them since the
    # data looks a bit different.
    table_validators = {
        'event.events': _event,
        'event.event_parts': _augment_dict_validator(
            _event_part, {'id': _id, 'event_id': _id}),
        'event.course_tracks': _augment_dict_validator(
            _event_track, {'id': _id, 'part_id': _id}),
        'event.courses': _augment_dict_validator(
            _course, {'event_id': _id}),
        'event.course_segments': _augment_dict_validator(
            _empty_dict, {'id': _id, 'course_id': _id, 'track_id': _id,
                          'is_active': _bool}),
        'event.log': _augment_dict_validator(
            _empty_dict, {'id': _id, 'ctime': _datetime, 'code': _int,
                          'submitted_by': _id, 'event_id': _id_or_None,
                          'persona_id': _id_or_None,
                          'additional_info': _str_or_None}),
        'event.orgas': _augment_dict_validator(
            _empty_dict, {'id': _id, 'event_id': _id, 'persona_id': _id}),
        'event.field_definitions': _augment_dict_validator(
            _event_field, {'id': _id, 'event_id': _id,
                           'field_name': _restrictive_identifier}),
        'event.lodgement_groups': _augment_dict_validator(
            _lodgement_group, {'event_id': _id}),
        'event.lodgements': _augment_dict_validator(
            _lodgement, {'event_id': _id}),
        'event.registrations': _augment_dict_validator(
            _registration, {'event_id': _id, 'persona_id': _id,
                            'amount_owed': _non_negative_decimal}),
        'event.registration_parts': _augment_dict_validator(
            _registration_part, {'id': _id, 'part_id': _id,
                                 'registration_id': _id}),
        'event.registration_tracks': _augment_dict_validator(
            _registration_track, {'id': _id, 'track_id': _id,
                                  'registration_id': _id}),
        'event.course_choices': _augment_dict_validator(
            _empty_dict, {'id': _id, 'course_id': _id, 'track_id': _id,
                          'registration_id': _id, 'rank': _int}),
        'event.questionnaire_rows': _augment_dict_validator(
            _empty_dict, {'id': _id, 'event_id': _id, 'pos': _int,
                          'field_id': _id_or_None, 'title': _str_or_None,
                          'info': _str_or_None, 'input_size': _int_or_None,
                          'readonly': _bool_or_None,
                          'kind': _enum_questionnaireusages,
                          }),
        'event.fee_modifiers': _event_fee_modifier,
    }
    for table, validator in table_validators.items():
        new_table = {}
        for key, entry in val[table].items():
            new_entry, e = validator(entry, table, _convert=_convert)
            # _convert=True to fix JSON key restriction
            new_key, ee = _int(
                key, table, _convert=True, _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                new_table[new_key] = new_entry
        val[table] = new_table
    if errs:
        return None, errs
    # Third a consistency check
    if len(val['event.events']) != 1:
        errs.append(('event.events',
                     ValueError(n_("Only a single event is supported."))))
    if (len(val['event.events'])
            and val['id'] != val['event.events'][val['id']]['id']):
        errs.append(('event.events', ValueError(n_("Wrong event specified."))))
    for k, v in val.items():
        if k not in ('id', 'EVENT_SCHEMA_VERSION', 'timestamp', 'kind'):
            for e in v.values():
                if e.get('event_id') and e['event_id'] != val['id']:
                    errs.append((k, ValueError(n_("Mismatched event."))))
    if errs:
        val = None
    return val, errs


@_addvalidator
def _serialized_partial_event_upload(val, argname=None, *, _convert=True,
                                     _ignore_warnings=False):
    """Check an event data set for delta import.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "serialized_partial_event_upload"
    val, errs = _input_file(val, argname, _convert=_convert,
                            _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    val, errs = _json(val, argname, _convert=_convert,
                      _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    return _serialized_partial_event(
        val, argname, _convert=_convert, _ignore_warnings=_ignore_warnings)


@_addvalidator
def _serialized_partial_event(val, argname=None, *, _convert=True,
                              _ignore_warnings=False):
    """Check an event data set for delta import.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "serialized_partial_event"
    # First a basic check
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'kind' not in val or val['kind'] != "partial":
        return None, [(argname, KeyError(n_(
            "Only partial exports are supported.")))]

    mandatory_fields = {
        'EVENT_SCHEMA_VERSION': _pair_of_int,
        'kind': _str,
        'id': _id,
        'timestamp': _datetime,
    }
    optional_fields = {
        'courses': _mapping,
        'lodgement_groups': _mapping,
        'lodgements': _mapping,
        'registrations': _mapping,
    }
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not((EVENT_SCHEMA_VERSION[0], 0) <= val['EVENT_SCHEMA_VERSION']
           <= EVENT_SCHEMA_VERSION):
        return None, [(argname, ValueError(n_("Schema version mismatch.")))]
    domain_validators = {
        'courses': _partial_course_or_None,
        'lodgement_groups': _partial_lodgement_group_or_None,
        'lodgements': _partial_lodgement_or_None,
        'registrations': _partial_registration_or_None,
    }
    for domain, validator in domain_validators.items():
        if domain not in val:
            continue
        new_dict = {}
        for key, entry in val[domain].items():
            # fix JSON key restriction
            new_key, e = _int(key, domain, _convert=True,
                              _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
                continue
            creation = (new_key < 0)
            new_entry, e = validator(
                entry, domain, _convert=_convert, creation=creation,
                _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                new_dict[new_key] = new_entry
        val[domain] = new_dict
    if errs:
        val = None
    return val, errs


def _PARTIAL_COURSE_COMMON_FIELDS(): return {
    'title': _str,
    'description': _str_or_None,
    'nr': _str_or_None,
    'shortname': _str,
    'instructors': _str_or_None,
    'max_size': _int_or_None,
    'min_size': _int_or_None,
    'notes': _str_or_None,
}


_PARTIAL_COURSE_OPTIONAL_FIELDS = {
    'segments': _mapping,
    'fields': _mapping,
}


@_addvalidator
def _partial_course(val, argname=None, *, creation=False, _convert=True,
                    _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "course"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _PARTIAL_COURSE_COMMON_FIELDS()
        optional_fields = _PARTIAL_COURSE_OPTIONAL_FIELDS
    else:
        mandatory_fields = {}
        optional_fields = dict(_PARTIAL_COURSE_COMMON_FIELDS(),
                               **_PARTIAL_COURSE_OPTIONAL_FIELDS)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'segments' in val:
        new_dict = {}
        for key, entry in val['segments'].items():
            new_key, e = _int(key, 'segments', _convert=True,
                              _ignore_warnings=_ignore_warnings)
            new_entry, ee = _bool_or_None(entry, 'segments', _convert=_convert,
                                          _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                new_dict[new_key] = new_entry
        val['segments'] = new_dict
    # the check of fields is delegated to _event_associated_fields
    return val, errs


def _PARTIAL_LODGEMENT_GROUP_FIELDS(): return {
    'moniker': _str,
}


@_addvalidator
def _partial_lodgement_group(val, argname=None, *, creation=False,
                             _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lodgement group"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _PARTIAL_LODGEMENT_GROUP_FIELDS()
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _PARTIAL_LODGEMENT_GROUP_FIELDS()
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _PARTIAL_LODGEMENT_COMMON_FIELDS(): return {
    'moniker': _str,
    'regular_capacity': _non_negative_int,
    'camping_mat_capacity': _non_negative_int,
    'notes': _str_or_None,
    'group_id': _partial_import_id_or_None,
}


_PARTIAL_LODGEMENT_OPTIONAL_FIELDS = {
    'fields': _mapping,
}


@_addvalidator
def _partial_lodgement(val, argname=None, *, creation=False, _convert=True,
                       _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lodgement"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _PARTIAL_LODGEMENT_COMMON_FIELDS()
        optional_fields = _PARTIAL_LODGEMENT_OPTIONAL_FIELDS
    else:
        mandatory_fields = {}
        optional_fields = dict(_PARTIAL_LODGEMENT_COMMON_FIELDS(),
                               **_PARTIAL_LODGEMENT_OPTIONAL_FIELDS)
    # the check of fields is delegated to _event_associated_fields
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _PARTIAL_REGISTRATION_COMMON_FIELDS(): return {
    'mixed_lodging': _bool,
    'list_consent': _bool,
    'notes': _str_or_None,
    'parts': _mapping,
    'tracks': _mapping,
}


def _PARTIAL_REGISTRATION_OPTIONAL_FIELDS(): return {
    'parental_agreement': _bool_or_None,
    'orga_notes': _str_or_None,
    'payment': _date_or_None,
    'amount_paid': _non_negative_decimal,
    'amount_owed': _non_negative_decimal,
    'checkin': _datetime_or_None,
    'fields': _mapping,
}


@_addvalidator
def _partial_registration(val, argname=None, *, creation=False, _convert=True,
                          _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration"

    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        # creation does not allow fields for sake of simplicity
        mandatory_fields = dict(_PARTIAL_REGISTRATION_COMMON_FIELDS(),
                                persona_id=_id)
        optional_fields = _PARTIAL_REGISTRATION_OPTIONAL_FIELDS()
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {}
        optional_fields = dict(
            _PARTIAL_REGISTRATION_COMMON_FIELDS(),
            **_PARTIAL_REGISTRATION_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'amount_owed' in val:
        del val['amount_owed']
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            anid, e = _id(anid, 'parts', _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
            part, ee = _partial_registration_part(
                part, 'parts', _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                newparts[anid] = part
        val['parts'] = newparts
    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            anid, e = _id(anid, 'tracks', _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
            track, ee = _partial_registration_track(
                track, 'tracks', _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if e or ee:
                errs.extend(e)
                errs.extend(ee)
            else:
                newtracks[anid] = track
        val['tracks'] = newtracks
    # the check of fields is delegated to _event_associated_fields
    return val, errs


@_addvalidator
def _partial_registration_part(val, argname=None, *, _convert=True,
                               _ignore_warnings=False):
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "partial_registration_part"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'status': _enum_registrationpartstati,
        'lodgement_id': _partial_import_id_or_None,
        'is_camping_mat': _bool,
    }
    return _examine_dictionary_fields(
        val, {}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _partial_registration_track(val, argname=None, *, _convert=True,
                                _ignore_warnings=False):
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "partial_registration_track"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    optional_fields = {
        'course_id': _partial_import_id_or_None,
        'course_instructor': _partial_import_id_or_None,
        'choices': _iterable,
    }
    val, errs = _examine_dictionary_fields(
        val, {}, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if 'choices' in val:
        newchoices = []
        for choice in val['choices']:
            choice, e = _partial_import_id(choice, 'choices', _convert=_convert,
                                           _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
                break
            else:
                newchoices.append(choice)
        val['choices'] = newchoices
    return val, errs


def _MAILINGLIST_COMMON_FIELDS(): return {
    'title': _str,
    'local_part': _email_local_part,
    'domain': _enum_mailinglistdomain,
    'description': _str_or_None,
    'mod_policy': _enum_moderationpolicy,
    'attachment_policy': _enum_attachmentpolicy,
    'ml_type': _enum_mailinglisttypes,
    'subject_prefix': _str_or_None,
    'maxsize': _id_or_None,
    'is_active': _bool,
    'notes': _str_or_None,
}


def _MAILINGLIST_OPTIONAL_FIELDS(): return {
    'assembly_id': _None,
    'event_id': _None,
    'registration_stati': _empty_list,
}


_MAILINGLIST_READONLY_FIELDS = {
    'address',
    'domain_str',
    'ml_type_class',
}


@_addvalidator
def _mailinglist(val, argname=None, *, creation=False, _convert=True,
                 _ignore_warnings=False, _allow_readonly=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "mailinglist"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_validation_fields = [('moderators', '[id]'), ]
    optional_validation_fields = [('whitelist', '[email]'), ]
    if "ml_type" in val:
        atype = ml_type.get_type(val["ml_type"])
        mandatory_validation_fields.extend(atype.mandatory_validation_fields)
        optional_validation_fields.extend(atype.optional_validation_fields)
    mandatory_fields = dict(_MAILINGLIST_COMMON_FIELDS())
    optional_fields = dict(_MAILINGLIST_OPTIONAL_FIELDS())
    iterable_fields = []
    for source, target in ((mandatory_validation_fields, mandatory_fields),
                           (optional_validation_fields, optional_fields)):
        for key, validator_str in source:
            if validator_str.startswith('[') and validator_str.endswith(']'):
                target[key] = _iterable
                iterable_fields.append((key, "_" + validator_str[1:-1]))
            else:
                target[key] = getattr(current_module, "_" + validator_str)
    # Optionally remove readonly attributes, take care to keep the original.
    if _allow_readonly:
        val = copy.deepcopy(val)
        for key in _MAILINGLIST_READONLY_FIELDS:
            if key in val:
                del val[key]
    if creation:
        pass
    else:
        # The order is important here, so that mandatory fields take precedence.
        optional_fields = dict(optional_fields, **mandatory_fields)
        mandatory_fields = {'id': _id}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if val and "moderators" in val and len(val["moderators"]) == 0:
        errs.append(("moderators", ValueError(n_("Must not be empty."))))
    if errs:
        return val, errs
    for key, validator_str in iterable_fields:
        validator = getattr(current_module, validator_str)
        newarray = []
        if key in val:
            for x in val[key]:
                v, e = validator(x, argname=key, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
                if e:
                    errs.extend(e)
                else:
                    newarray.append(v)
            val[key] = newarray
    if "domain" in val:
        if "ml_type" not in val:
            errs.append(("domain", ValueError(n_(
                "Must specify mailinglist type to change domain."))))
        else:
            atype = ml_type.get_type(val["ml_type"])
            if val["domain"].value not in atype.domains:
                errs.append(("domain", ValueError(n_(
                    "Invalid domain for this mailinglist type."))))
    return val, errs


_SUBSCRIPTION_ID_FIELDS = {
    'mailinglist_id': _id,
    'persona_id': _id,
}


def _SUBSCRIPTION_STATE_FIELDS(): return {
    'subscription_state': _enum_subscriptionstates,
}


_SUBSCRIPTION_ADDRESS_FIELDS = {
    'address': _email,
}


@_addvalidator
def _subscription_identifier(val, argname=None, *, _convert=True,
                             _ignore_warnings=False):
    argname = argname or "subscription identifier"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    return _examine_dictionary_fields(
        val, mandatory_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _subscription_state(val, argname=None, *, _convert=True,
                        _ignore_warnings=False):
    argname = argname or "subscription state"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_STATE_FIELDS())
    return _examine_dictionary_fields(
        val, mandatory_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _subscription_address(val, argname=None, *, _convert=True,
                          _ignore_warnings=False):
    argname = argname or "subscription address"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_ADDRESS_FIELDS)
    return _examine_dictionary_fields(
        val, mandatory_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


@_addvalidator
def _subscription_request_resolution(val, argname=None, *, _convert=True,
                                     _ignore_warnings=False):
    argname = argname or "subscription request resolution"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_REQUEST_RESOLUTION_FIELDS())
    return _examine_dictionary_fields(
        val, mandatory_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _ASSEMBLY_COMMON_FIELDS(): return {
    'title': _str,
    'description': _str_or_None,
    'signup_end': _datetime,
    'notes': _str_or_None,
}


def _ASSEMBLY_OPTIONAL_FIELDS(): return {
    'is_active': _bool,
    'mail_address': _str_or_None,
}


@_addvalidator
def _assembly(val, argname=None, *, creation=False, _convert=True,
              _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "assembly"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _ASSEMBLY_COMMON_FIELDS()
        optional_fields = _ASSEMBLY_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_ASSEMBLY_COMMON_FIELDS(),
                               **_ASSEMBLY_OPTIONAL_FIELDS())
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


def _BALLOT_COMMON_FIELDS(): return {
    'title': _str,
    'description': _str_or_None,
    'vote_begin': _datetime,
    'vote_end': _datetime,
    'notes': _str_or_None
}


def _BALLOT_OPTIONAL_FIELDS(): return {
    'extended': _bool_or_None,
    'vote_extension_end': _datetime_or_None,
    'quorum': _int,
    'votes': _int_or_None,
    'use_bar': _bool,
    'is_tallied': _bool,
    'candidates': _mapping
}


@_addvalidator
def _ballot(val, argname=None, *, creation=False, _convert=True,
            _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "ballot"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_BALLOT_COMMON_FIELDS(), assembly_id=_id)
        optional_fields = _BALLOT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _id}
        optional_fields = dict(_BALLOT_COMMON_FIELDS(),
                               **_BALLOT_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if 'vote_begin' in val:
        if val['vote_begin'] <= now():
            errs.append(
                ("vote_begin", ValueError(n_("Mustn’t be in the past.")))
            )
        if 'vote_end' in val:
            if val['vote_end'] <= val['vote_begin']:
                errs.append(
                    ("vote_end", ValueError(n_(
                        "Mustn’t be before start of voting period.")))
                )
            if 'vote_extension_end' in val and val['vote_extension_end']:
                if val['vote_extension_end'] <= val['vote_end']:
                    errs.append(
                        ("vote_extension_end", ValueError(n_(
                            "Mustn’t be before end of voting period.")))
                    )
    if 'candidates' in val:
        newcandidates = {}
        for anid, candidate in val['candidates'].items():
            anid, e = _int(anid, 'candidates', _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                candidate, ee = _ballot_candidate_or_None(
                    candidate, 'candidates', creation=creation,
                    _convert=_convert, _ignore_warnings=_ignore_warnings)
                if ee:
                    errs.extend(ee)
                else:
                    newcandidates[anid] = candidate
        val['candidates'] = newcandidates
    if ('quorum' in val) != ('vote_extension_end' in val):
        errs.extend(
            [("vote_extension_end",
              ValueError(n_("Must be specified if quorum is given."))),
             ("quorum", ValueError(
                 n_("Must be specified if vote extension end is given.")))]
        )
    if 'quorum' in val and 'vote_extension_end' in val:
        if not ((val['quorum'] != 0 and val['vote_extension_end'] is not None)
                or (val['quorum'] == 0 and val['vote_extension_end'] is None)):
            errs.extend(
                [("vote_extension_end",
                  ValueError(n_("Inconsitent with quorum."))),
                 ("quorum", ValueError(
                     n_("Inconsitent with vote extension end.")))]
            )
    return val, errs


_BALLOT_CANDIDATE_COMMON_FIELDS = {
    'description': _str,
    'moniker': _identifier,
}


@_addvalidator
def _ballot_candidate(val, argname=None, *, creation=False, _convert=True,
                      _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "ballot_candidate"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _BALLOT_CANDIDATE_COMMON_FIELDS
        optional_fields = {}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = _BALLOT_CANDIDATE_COMMON_FIELDS
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if val.get('moniker') == ASSEMBLY_BAR_MONIKER:
        errs.append(("moniker", ValueError(n_("Mustn’t be the bar moniker."))))
    return val, errs


def _ASSEMBLY_ATTACHMENT_FIELDS(): return {
    'assembly_id': _id_or_None,
    'ballot_id': _id_or_None,
}


def _ASSEMBLY_ATTACHMENT_VERSION_FIELDS(): return {
    'title': _str,
    'authors': _str_or_None,
    'filename': _str,
}


@_addvalidator
def _assembly_attachment(val, argname=None, *, creation=False, _convert=True,
                         _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type creation: bool
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "assembly_attachment"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _ASSEMBLY_ATTACHMENT_VERSION_FIELDS()
        optional_fields = _ASSEMBLY_ATTACHMENT_FIELDS()
    else:
        mandatory_fields = dict(_ASSEMBLY_ATTACHMENT_FIELDS(), id=_id)
        optional_fields = {}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if val.get("assembly_id") and val.get("ballot_id"):
        errs.append((argname, ValueError(n_("Only one host allowed."))))
    if not val.get("assembly_id") and not val.get("ballot_id"):
        errs.append((argname, ValueError(n_("No host given."))))
    if errs:
        return None, errs
    return val, errs


@_addvalidator
def _assembly_attachment_version(val, argname=None, *, creation=False,
                                 _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type creation: bool
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "assembly_attachment_version"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_ASSEMBLY_ATTACHMENT_VERSION_FIELDS(),
                                attachment_id=_id)
        optional_fields = {}
    else:
        mandatory_fields = {'attachment_id': _id, 'version': _id}
        optional_fields = _ASSEMBLY_ATTACHMENT_VERSION_FIELDS()
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    return val, errs


@_add_typed_validator
def _vote(
    val: Any, argname: str = "vote", ballot: Mapping[str, Any] = None, **kwargs
) -> Vote:
    """Validate a single voters intent.

    This is mostly made complicated by the fact that we offer to emulate
    ordinary voting instead of full preference voting.

    :param ballot: Ballot the vote was cast for.
    """
    assert ballot is not None  # TODO needed because of default for argname, change this
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()

    entries = tuple(y for x in val.split('>') for y in x.split('='))
    reference = set(e['moniker'] for e in ballot['candidates'].values())
    if ballot['use_bar'] or ballot['votes']:
        reference.add(ASSEMBLY_BAR_MONIKER)
    if set(entries) - reference:
        errs.append(KeyError(argname, n_("Superfluous candidates.")))
    if reference - set(entries):
        errs.append(KeyError(argname, n_("Missing candidates.")))
    if errs:
        raise errs
    if ballot['votes'] and '>' in val:
        # ordinary voting has more constraints
        # if no strictly greater we have a valid abstention
        groups = val.split('>')
        if len(groups) > 2:
            errs.append(ValueError(argname, n_("Too many levels.")))
        if len(groups[0].split('=')) > ballot['votes']:
            errs.append(ValueError(argname, n_("Too many votes.")))
        first_group = groups[0].split('=')
        if (ASSEMBLY_BAR_MONIKER in first_group
                and first_group != [ASSEMBLY_BAR_MONIKER]):
            errs.append(ValueError(argname, n_("Misplaced bar.")))
        if errs:
            raise errs

    return Vote(val)


# TODO move above
@_add_typed_validator
def _regex(
    val: Any, argname: str = None, **kwargs
) -> Regex:
    val = _str(val, argname, **kwargs)
    try:
        re.compile(val)
    except re.error as e:
        # TODO maybe provide more precise feedback?
        raise ValidationSummary(
            ValueError(argname,
                       n_("Invalid  regular expression (position %(pos)s)."), {
                       'pos': e.pos})) from e  # type: ignore
                       # TODO wait for mypy to ship updated typeshed
    return Regex(val)


@_add_typed_validator
def _non_regex(
    val: Any, argname: str = None, **kwargs
) -> NonRegex:
    val = _str(val, argname, **kwargs)
    forbidden_chars = r'\*+?{}()[]|'
    msg = n_(r"Must not contain any forbidden characters"
             f" (which are {forbidden_chars} while .^$ are allowed).")
    if any(char in val for char in forbidden_chars):
        raise ValidationSummary(ValueError(argname, msg))
    return NonRegex(val)


@_addvalidator
def _query_input(val, argname=None, *, spec=None, allow_empty=False,
                 _convert=True, _ignore_warnings=False, separator=',',
                 escape='\\'):
    """This is for the queries coming from the web.

    It is not usable with decorators since the spec is often only known at
    runtime. To alleviate this circumstance there is the
    :py:func:`cdedb.query.mangle_query_input` function to take care of the
    things the decorators normally do.

    This has to be careful to treat checkboxes and selects correctly
    (which are partly handled by an absence of data).

    :type val: object
    :type argname: str or None
    :type spec: {str: str}
    :param spec: a query spec from :py:mod:`cdedb.query`
    :type allow_empty: bool
    :param allow_empty: Toggles whether no selected output fields is an error.
    :type _convert: bool
    :type _ignore_warnings: bool
    :type separator: char
    :param separator: Defines separator for multi-value-inputs.
    :type escape: char
    :param escape: Defines escape character so that the input may contain a
      separator for multi-value-inputs.
    :rtype: (:py:class:`cdedb.query.Query` or None, [(str or None, exception)])
    """
    if spec is None:
        raise RuntimeError(n_("Query must be specified."))
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    fields_of_interest = []
    constraints = []
    order = []
    for field, validator in spec.items():
        # First the selection of fields of interest
        selected, e = _bool(
            val.get("qsel_{}".format(field), "False"), field, _convert=_convert,
            _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if selected:
            fields_of_interest.append(field)

        # Second the constraints (filters)
        # Get operator
        operator, e = _enum_queryoperators_or_None(
            val.get("qop_{}".format(field)), field, _convert=_convert,
            _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if e or not operator:
            # Skip if invalid or empty operator
            continue
        if operator not in VALID_QUERY_OPERATORS[validator]:
            errs.append((field,
                         ValueError(n_("Invalid operator for this field."))))
            continue
        if operator in NO_VALUE_OPERATORS:
            constraints.append((field, operator, None))
            continue

        # Get value
        value = val.get("qval_{}".format(field))
        if value is None or value == "":
            # No value supplied means no constraint
            # TODO: make empty string a valid constraint
            continue

        if operator in MULTI_VALUE_OPERATORS:
            values = escaped_split(value, separator, escape)
            value = []
            for v in values:
                # Validate every single value
                vv, e = getattr(current_module,
                                "_{}_or_None".format(validator))(
                    v, field, _convert=_convert,
                    _ignore_warnings=_ignore_warnings)
                errs.extend(e)
                if e or not vv:
                    continue
                if operator in (QueryOperators.containsall,
                                QueryOperators.containssome,
                                QueryOperators.containsnone):
                    vv, e = _non_regex(vv, field, _convert=_convert,
                                       _ignore_warnings=_ignore_warnings)
                    errs.extend(e)
                if e or not vv:
                    continue
                value.append(vv)
            if not value:
                continue
            if (operator in (QueryOperators.between, QueryOperators.outside)
                    and len(value) != 2):
                errs.append((field, ValueError(n_("Two endpoints required."))))
                continue
        elif operator in (QueryOperators.match, QueryOperators.unmatch):
            value, e = _non_regex_or_None(value, field, _convert=_convert,
                                          _ignore_warnings=_ignore_warnings)
            errs.extend(e)
            if e or not value:
                continue
        elif operator in (QueryOperators.regex, QueryOperators.notregex):
            value, e = _regex_or_None(value, field, _convert=_convert,
                                      _ignore_warnings=_ignore_warnings)
            errs.extend(e)
            if e or not value:
                continue
        else:
            value, e = getattr(current_module, "_{}_or_None".format(validator))(
                value, field, _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            errs.extend(e)
            if e:
                continue
        if value is not None:
            constraints.append((field, operator, value))
    if not fields_of_interest and not allow_empty:
        errs.append((argname, ValueError(n_("Selection may not be empty."))))

    # Third the ordering
    for postfix in ("primary", "secondary", "tertiary"):
        if "qord_" + postfix not in val:
            continue
        value, e = _csv_identifier_or_None(
            val["qord_" + postfix], "qord_" + postfix, _convert=_convert,
            _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        tmp = "qord_" + postfix + "_ascending"
        ascending, e = _bool(val.get(tmp, "True"), tmp, _convert=_convert,
                             _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if value:
            order.append((value, ascending))
    if errs:
        return None, errs
    return Query(None, spec, fields_of_interest, constraints, order), errs


# TODO ignore _ignore_warnings here too?
@_addvalidator
def _query(val, argname=None, *, _convert=None, _ignore_warnings=False):
    """Check query object for consistency.

    This is a tad weird, since the specification against which we check
    is also provided by the query object. If we use an actual RPC
    mechanism queries must be serialized and this gets more interesting.

    :type val: object
    :type argname: str or None
    :type _convert: None
    :param _convert: Ignored and only present for compatability reasons.
    :rtype: (:py:class:`cdedb.query.Query` or None, [(str or None, exception)])
    """
    if not isinstance(val, Query):
        return None, [(argname, TypeError(n_("Not a Query.")))]
    # scope
    _, errs = _identifier(val.scope, "scope", _convert=False,
                          _ignore_warnings=_ignore_warnings)
    if not val.scope.startswith("qview_"):
        errs.append(("scope", ValueError(n_("Must start with “qview_”."))))
    # spec
    for field, validator in val.spec.items():
        _, e = _csv_identifier(field, "spec", _convert=False,
                               _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        _, e = _printable_ascii(validator, "spec", _convert=False,
                                _ignore_warnings=_ignore_warnings)
        errs.extend(e)
    # fields_of_interest
    for field in val.fields_of_interest:
        _, e = _csv_identifier(field, "fields_of_interest", _convert=False,
                               _ignore_warnings=_ignore_warnings)
        errs.extend(e)
    if not val.fields_of_interest:
        errs.append(("fields_of_interest", ValueError(n_("Mustn’t be empty."))))
    # constraints
    for idx, x in enumerate(val.constraints):
        try:
            field, operator, value = x
        except ValueError:
            msg = n_("Invalid constraint number %(index)s")
            errs.append(("constraints", ValueError(msg, {"index": idx})))
            continue
        field, e = _csv_identifier(field, "constraints", _convert=False,
                                   _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if field not in val.spec:
            errs.append(("constraints", KeyError(n_("Invalid field."))))
            continue
        operator, e = _enum_queryoperators(
            operator, "constraints/{}".format(field), _convert=False,
            _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if operator not in VALID_QUERY_OPERATORS[val.spec[field]]:
            errs.append(("constraints/{}".format(field),
                         ValueError(n_("Invalid operator."))))
            continue
        if operator in NO_VALUE_OPERATORS:
            value = None
        elif operator in MULTI_VALUE_OPERATORS:
            validator = getattr(current_module, "_{}".format(val.spec[field]))
            for v in value:
                v, e = validator(
                    v, "constraints/{}".format(field), _convert=False,
                    _ignore_warnings=_ignore_warnings)
                errs.extend(e)
        else:
            _, e = getattr(current_module, "_{}".format(val.spec[field]))(
                value, "constraints/{}".format(field), _convert=False,
                _ignore_warnings=_ignore_warnings)
            errs.extend(e)
    # order
    for idx, entry in enumerate(val.order):
        entry, e = _iterable(entry, 'order', _convert=False,
                             _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if e:
            continue
        try:
            field, ascending = entry
        except ValueError:
            msg = n_("Invalid ordering condition number %(index)s")
            errs.append(('order', ValueError(msg, {'index': idx})))
        else:
            _, e = _csv_identifier(field, "order", _convert=False,
                                   _ignore_warnings=_ignore_warnings)
            _, ee = _bool(ascending, "order", _convert=False,
                          _ignore_warnings=_ignore_warnings)
            errs.extend(e)
            errs.extend(ee)
    if errs:
        val = None
    else:
        val = copy.deepcopy(val)
    return val, errs


def _enum_validator_maker(anenum, name=None, internal=False):
    """Automate validator creation for enums.

    Since this is pretty generic we do this all in one go.

    :type anenum: Enum
    :type name: str or None
    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    :type internal: bool
    :param internal: If True the validator is not added to the module.
    """
    error_msg = n_("Invalid input for the enumeration %(enum)s")

    def the_validator(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
        """
        :type val: object
        :type argname: str or None
        :type _convert: bool
       :type _ignore_warnings: bool
        :type _ignore_warnings: bool
        :rtype: (enum or None, [(str or None, exception)])
        """
        if _convert and not isinstance(val, anenum):
            val, errs = _int(val, argname=argname, _convert=_convert,
                             _ignore_warnings=_ignore_warnings)
            if errs:
                return val, errs
            try:
                val = anenum(val)
            except ValueError:
                return None, [(argname,
                               ValueError(error_msg, {'enum': anenum}))]
        else:
            if not isinstance(val, anenum):
                if isinstance(val, int):
                    try:
                        val = anenum(val)
                    except ValueError:
                        return None, [(
                            argname, ValueError(error_msg, {'enum': anenum}))]
                else:
                    return None, [
                        (argname, TypeError(n_("Must be a %(type)s."),
                                            {'type': anenum}))]
        return val, []

    the_validator.__name__ = name or "_enum_{}".format(anenum.__name__.lower())
    if not internal:
        _addvalidator(the_validator)
        setattr(current_module, the_validator.__name__, the_validator)
    return the_validator


for oneenum in ALL_ENUMS:
    _enum_validator_maker(oneenum)


def _infinite_enum_validator_maker(anenum, name=None):
    """Automate validator creation for infinity enums.

    Since this is pretty generic we do this all in one go.

    For further information about infinite enums see
    :py:func:`cdedb.common.infinite_enum`.

    :type anenum: Enum
    :type name: str or None
    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    """
    raw_validator = _enum_validator_maker(anenum, internal=True)
    error_msg = n_("Invalid input for the enumeration %(enum)s")

    def the_validator(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
        """
        :type val: object
        :type argname: str or None
        :type _convert: bool
        :type _ignore_warnings: bool
        :rtype: (InfiniteEnum or None, [(str or None, exception)])
        """
        if isinstance(val, InfiniteEnum):
            val_enum, errs = raw_validator(
                val.enum, argname=argname, _convert=_convert,
                _ignore_warnings=_ignore_warnings)
            if errs:
                return None, errs
            if val.enum.value == INFINITE_ENUM_MAGIC_NUMBER:
                val_int, errs = _non_negative_int(
                    val.int, argname=argname, _convert=_convert,
                    _ignore_warnings=_ignore_warnings)
            else:
                val_int = None
            if errs:
                return None, errs
        else:
            if _convert:
                val, errs = _int(val, argname=argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
                if errs:
                    return None, errs
                val_int = None
                if val < 0:
                    try:
                        val_enum = anenum(val)
                    except ValueError:
                        return None, [
                            (argname, ValueError(error_msg, {'enum': anenum}))]
                else:
                    val_enum = anenum(INFINITE_ENUM_MAGIC_NUMBER)
                    val_int = val
            else:
                return None, [(argname, TypeError(n_("Must be a %(type)s."),
                                                  {'type': anenum}))]
        return InfiniteEnum(val_enum, val_int), []

    the_validator.__name__ = name or "_infinite_enum_{}".format(
        anenum.__name__.lower())
    _addvalidator(the_validator)
    setattr(current_module, the_validator.__name__, the_validator)


for oneenum in ALL_INFINITE_ENUMS:
    _infinite_enum_validator_maker(oneenum)


#
# Above is the real stuff
#

def _create_assert_valid(fun):
    """
    :type fun: callable
    """

    @functools.wraps(fun)
    def assert_valid(*args, **kwargs):
        val, errs = fun(*args, **kwargs)
        if errs:
            e = errs[0][1]
            e.args = ("{} ({})".format(e.args[0], errs[0][0]),) + e.args[1:]
            raise e
        return val

    return assert_valid


def _create_is_valid(fun):
    """
    :type fun: callable
    """

    @functools.wraps(fun)
    def is_valid(*args, **kwargs):
        kwargs['_convert'] = False
        _, errs = fun(*args, **kwargs)
        return not errs

    return is_valid


def _create_check_valid(fun):
    """
    :type fun: callable
    """

    @functools.wraps(fun)
    def check_valid(*args, **kwargs):
        val, errs = fun(*args, **kwargs)
        if errs:
            _LOGGER.debug("{} for '{}' with input {}, {}.".format(
                errs, fun.__name__, args, kwargs))
            return None, errs
        return val, errs

    return check_valid


def _allow_None(fun):
    """Wrap a validator to allow ``None`` as valid input. This causes falsy
    values to be mapped to ``None`` if there is an error.

    :type fun: callable
    """

    @functools.wraps(fun)
    def new_fun(val, *args, **kwargs):
        if val is None:
            return None, []
        else:
            try:
                retval, errs = fun(val, *args, **kwargs)
            except:  # we need to catch everything
                if kwargs.get('_convert', True) and not val:
                    return None, []
                else:
                    raise
            if errs and kwargs.get('_convert', True) and not val:
                return None, []
            return retval, errs

    return new_fun


def _create_validators(funs):
    """This instantiates the validators used in the rest of the code.

    :type funs: [callable]
    """
    for fun in funs:
        setattr(current_module, "is{}".format(fun.__name__),
                _create_is_valid(fun))
        setattr(current_module, "assert{}".format(fun.__name__),
                _create_assert_valid(fun))
        setattr(current_module, "check{}".format(fun.__name__),
                _create_check_valid(fun))
        fun_or_None = _allow_None(fun)
        setattr(current_module, "{}_or_None".format(fun.__name__), fun_or_None)
        setattr(current_module, "is{}_or_None".format(fun.__name__),
                _create_is_valid(fun_or_None))
        setattr(current_module, "assert{}_or_None".format(fun.__name__),
                _create_assert_valid(fun_or_None))
        setattr(current_module, "check{}_or_None".format(fun.__name__),
                _create_check_valid(fun_or_None))


_create_validators(_ALL)


def typed_assert_valid(
    type_: Type[T], value: Any, *args: Any, **kwargs: Any
) -> T:

    try:
        val = _ALL_TYPED[type_](value, *args, **kwargs)
    except (ValueError, TypeError) as err:
        raise ValidationSummary(err)
    except ValidationSummary as errs:
        argname, error = errs[0]
        error.args = ("{} ({})".format(
            error.args[0], argname),) + error.args[1:]
        raise error
    assert isinstance(val, type_)
    return val


def typed_is_valid(
    type_: Type[T], value: Any, *args: Any, **kwargs: Any
) -> bool:

    kwargs['_convert'] = False
    try:
        _ALL_TYPED[type_](value, *args, **kwargs)
        return True
    except (ValueError, TypeError, ValidationSummary):
        return False


def typed_check_valid(
    type_: Type[T], value: Any, *args: Any, **kwargs: Any
) -> Tuple[Optional[T], List[Error]]:

    try:
        val = _ALL_TYPED[type_](value, *args, **kwargs)
    except (ValueError, TypeError) as err:
        raise ValidationSummary(err)
    except ValidationSummary as errs:
        _LOGGER.debug(
            f"{errs} for '{_ALL_TYPED[type_].__name__}'"
            f" with input {args}, {kwargs}."
        )
        errors = map(lambda err: (err.args[0], ValueError(err.args[1:])), errs)
        return None, list(errors)
    return val, []
