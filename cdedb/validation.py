# pylint: disable=undefined-variable
# we do some setattrs which confuse pylint
# TODO using doctest may be nice for the atomic validators
# TODO split in multiple files?
# TODO do not use underscore for protection but instead specify __all__
# TODO why sometimes function and sometimes .copy() for field templates?

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

The raw validator implementations are functions with signature
``(val, argname, **kwargs)`` of which many support the keyword arguments
``_convert`` and ``_ignore_warnings``.
These functions are registered and than wrapped to generate the above variants.

They return the the validated and optionally converted value
and raise a ``ValidationSummary`` when encountering errors.
Each exception summary contains a list of ``ValdidationError``s
which store the ``argname`` of the validator where the error occured
as well as the original ``exception``.
A ``ValidationError`` may also store a third argument.
This optional argument should be a ``Mapping[str, Any]``
describing substitutions of the error string to done after i18n.

The parameter ``_convert`` is present in many validators
and is usually passed along from the original caller to every validation inside
as part of the keyword arugments.
If ``True``, validators may try to convert the value into the appropriate type.
For instance ``_int`` will try to convert the input into an int
which would be useful for string inputs especially.

The parameter ``_ignore_warnings`` is present in some validators.
If ``True``, ``ValidationWarning`` may be ignored instead of raised.
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
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
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
    ASSEMBLY_BAR_SHORTNAME,
    EPSILON,
    EVENT_SCHEMA_VERSION,
    INFINITE_ENUM_MAGIC_NUMBER,
    REALM_SPECIFIC_GENESIS_FIELDS,
    CdEDBObject,
    CdEDBObjectMap,
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
NoneType = type(None)

current_module = sys.modules[__name__]

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)

T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])
TypeMapping = Dict[str, Type[Any]]


class ValidationSummary(ValueError, Sequence[Exception]):
    args: Tuple[Exception, ...]

    def __init__(self, *errors: Exception):
        super().__init__(*errors)

    def __len__(self):
        return len(self.args)

    def __getitem__(self, index):
        return self.args[index]

    def extend(self, errors: Iterable[Exception]) -> None:
        self.args = self.args + tuple(errors)

    def append(self, error: Exception) -> None:
        self.args = self.args + (error,)


class ValidatorStorage(Dict[Type[Any], Callable[..., Any]]):
    def __setitem__(self, type_: Type[T], validator: Callable[..., T]) -> None:
        super().__setitem__(type_, validator)

    def __getitem__(self, type_: Type[T]) -> Callable[..., T]:
        return super().__getitem__(type_)

    def __missing__(self, type_: Type[T]) -> Callable[..., T]:
        # TODO resolve potential cyclic imports with enums
        if callable(type_):
            return type_  # we have a raw enum validator
        # TODO implement dynamic lookup for container types
        raise NotImplementedError(type_)


_ALL_TYPED = ValidatorStorage()


def _create_assert_valid(fun: Callable[..., T]) -> Callable[..., T]:
    @ functools.wraps(fun)
    def assert_valid(*args: Any, **kwargs: Any) -> T:
        try:
            val = fun(*args, **kwargs)
        except ValidationSummary as errs:
            old_format = [(e.args[0], type(e)(*e.args[1:])) for e in errs]
            _LOGGER.debug(
                f"{old_format} for '{fun.__name__}'"
                f" with input {args}, {kwargs}."
            )
            e = errs[0]
            e.args = ("{} ({})".format(e.args[1], e.args[0]),) + e.args[2:]
            raise e from errs
        return val

    return assert_valid


def _create_is_valid(fun: Callable[..., T]) -> Callable[..., bool]:
    @ functools.wraps(fun)
    def is_valid(*args: Any, **kwargs: Any) -> bool:
        kwargs['_convert'] = False
        try:
            fun(*args, **kwargs)
            return True
        except ValidationSummary as errs:
            return False

    return is_valid


def _create_check_valid(fun: Callable[..., T]
                        ) -> Callable[..., Tuple[Optional[T], List[Error]]]:
    @ functools.wraps(fun)
    def check_valid(*args: Any, **kwargs: Any) -> Tuple[Optional[T], List[Error]]:
        try:
            val = fun(*args, **kwargs)
            return val, []
        except ValidationSummary as errs:
            old_format = [(e.args[0], type(e)(*e.args[1:])) for e in errs]
            _LOGGER.debug(
                f"{old_format} for '{fun.__name__}'"
                f" with input {args}, {kwargs}."
            )
            return None, old_format

    return check_valid


def _allow_None(fun: Callable[..., T]) -> Callable[..., Optional[T]]:
    """Wrap a validator to allow ``None`` as valid input.

    This causes falsy values to be mapped to ``None`` if there is an error.
    """

    @ functools.wraps(fun)
    def new_fun(val: Any, *args: Any, **kwargs: Any) -> Optional[T]:
        if val is None:
            return None
        else:
            try:
                return fun(val, *args, **kwargs)
            except ValidationSummary as errs:  # we need to catch everything
                if kwargs.get('_convert', True) and not val:
                    return None
                else:
                    raise

    new_fun.__name__ += "_or_None"

    return new_fun


def _create_validators(funs: Iterable[F]) -> None:
    """This instantiates the validators used in the rest of the code."""
    for fun in funs:
        setattr(current_module, "is{}".format(fun.__name__),
                _create_is_valid(fun))
        setattr(current_module, "assert{}".format(fun.__name__),
                _create_assert_valid(fun))
        setattr(current_module, "check{}".format(fun.__name__),
                _create_check_valid(fun))


def _add_typed_validator(fun: F, return_type: Type[Any] = None) -> F:
    """Mark a typed function for processing into validators."""
    # TODO get rid of dynamic return types for enum
    if not return_type:
        return_type = get_type_hints(fun)["return"]
    assert return_type
    if return_type in _ALL_TYPED:
        raise RuntimeError(f"Type {return_type} already registered")
    _ALL_TYPED[return_type] = fun
    allow_none = _allow_None(fun)
    _ALL_TYPED[Optional[return_type]] = allow_none
    setattr(current_module, allow_none.__name__, allow_none)

    return fun


def _examine_dictionary_fields(
    adict: Mapping[str, Any],
    mandatory_fields: Mapping[str, Type[Any]],
    optional_fields: Mapping[str, Type[Any]] = None,
    *,
    allow_superfluous: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Check more complex dictionaries.

    :param adict: the dictionary to check
    :param mandatory_fields: mandatory fields to be checked for.
      It should map keys to registered types.
      A missing key is an error in itself.
    :param optional_fields: Like :py:obj:`mandatory_fields`, but facultative.
    :param allow_superfluous: If ``False`` keys which are neither in
      :py:obj:`mandatory_fields` nor in :py:obj:`optional_fields` are errors.
    """
    optional_fields = optional_fields or {}
    errs = ValidationSummary()
    retval: Dict[str, Any] = {}
    for key, value in adict.items():
        if key in mandatory_fields:
            try:
                v = _ALL_TYPED[mandatory_fields[key]](
                    value, argname=key, **kwargs)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif key in optional_fields:
            try:
                v = _ALL_TYPED[optional_fields[key]](
                    value, argname=key, **kwargs)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif not allow_superfluous:
            errs.append(KeyError(key, n_("Superfluous key found.")))

    missing_mandatory = set(mandatory_fields).difference(retval)
    if missing_mandatory:
        for key in missing_mandatory:
            errs.append(KeyError(key, n_("Mandatory key missing.")))

    if errs:
        raise errs

    return retval


def _augment_dict_validator(
    validator: Callable[..., Any],
    augmentation: Mapping[str, Type[Any]],
    strict: bool = True,
) -> Callable[..., Any]:
    """Beef up a dict validator.

    This is for the case where you have two similar specs for a data set
    in form of a dict and already a validator for one of them, but some
    additional fields in the second spec.

    This can also be used as a decorator.

    :param augmentation: Syntax is the same as for
        :py:meth:`_examine_dictionary_fields`.
    :param strict: if ``True`` the additional arguments are mandatory
        otherwise they are optional.
    """

    @functools.wraps(validator)
    def new_validator(
        val: Any, argname: str = None, **kwargs: Any
    ) -> Dict[str, Any]:
        mandatory_fields = augmentation if strict else {}
        optional_fields = {} if strict else augmentation

        errs = ValidationSummary()
        ret: Dict[str, Any] = {}
        try:
            ret = _examine_dictionary_fields(
                val, mandatory_fields, optional_fields,
                **{"allow_superfluous": True, **kwargs})
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

        return ret

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
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> None:
    """Force a None.

    This is mostly for ensuring proper population of dicts.
    """
    if _convert:
        if isinstance(val, str) and not val:
            val = None
    if val is not None:
        raise ValidationSummary(ValueError(argname, n_("Must be empty.")))
    return None


@_add_typed_validator
def _any(
    val: Any, argname: str = None, **kwargs: Any
) -> Any:
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.
    """
    return val


@_add_typed_validator
def _int(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
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
    # disallow booleans as psycopg will try to send them as such and not ints
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValidationSummary(TypeError(argname, n_("Must be an integer.")))
    return val


@_add_typed_validator
def _non_negative_int(
    val: Any, argname: str = None, **kwargs: Any
) -> NonNegativeInt:
    val = _int(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Must not be negative.")))
    return NonNegativeInt(val)


@_add_typed_validator
def _positive_int(
    val: Any, argname: str = None, **kwargs: Any
) -> PositiveInt:
    val = _int(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be positive.")))
    return PositiveInt(val)


@_add_typed_validator
def _id(
    val: Any, argname: str = None, **kwargs: Any
) -> ID:
    """A numeric ID as in a database key.

    This is just a wrapper around `_positive_int`, to differentiate this
    semantically.
    """
    return ID(_positive_int(val, argname, **kwargs))


@_add_typed_validator
def _partial_import_id(
    val: Any, argname: str = None, **kwargs: Any
) -> PartialImportID:
    """A numeric id or a negative int as a placeholder."""
    val = _int(val, argname, **kwargs)
    if val == 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be zero.")))
    return PartialImportID(val)


@_add_typed_validator
def _float(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
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
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> decimal.Decimal:
    if _convert and isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise ValidationSummary(ValueError(argname, n_(
                "Invalid input for decimal number."))) from e
    if not isinstance(val, decimal.Decimal):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a decimal.Decimal.")))
    return val


@_add_typed_validator
def _non_negative_decimal(
    val: Any, argname: str = None, **kwargs: Any
) -> NonNegativeDecimal:
    val = _decimal(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return NonNegativeDecimal(val)


@_add_typed_validator
def _positive_decimal(
    val: Any, argname: str = None, **kwargs: Any
) -> PositiveDecimal:
    val = _decimal(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return PositiveDecimal(val)


@_add_typed_validator
def _str_type(
    val: Any, argname: str = None, *,
    zap: str = '', sieve: str = '', _convert: bool = True, **kwargs: Any
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
def _str(val: Any, argname: str = None, **kwargs: Any) -> str:
    """ Like :py:class:`_str_type` (parameters see there),
    but mustn't be empty (whitespace doesn't count).
    """
    val = _str_type(val, argname, **kwargs)
    if not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return val


@_add_typed_validator
def _bytes(
    val: Any, argname: str = None, *,
    _convert: bool = True, encoding: str = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
) -> Mapping[Any, Any]:
    """
    :param _convert: is ignored since no useful default conversion is available
    """
    if not isinstance(val, Mapping):
        raise ValidationSummary(TypeError(argname, n_("Must be a mapping.")))
    return val


@_add_typed_validator
def _iterable(
    val: Any, argname: str = None, **kwargs: Any
) -> Iterable[Any]:
    """
    :param _convert: is ignored since no useful default conversion is available
    """
    if not isinstance(val, Iterable):
        raise ValidationSummary(TypeError(argname, n_("Must be an iterable.")))
    return val


@_add_typed_validator
def _sequence(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> Sequence[Any]:
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
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> bool:
    # TODO why do we convert first if it may already be a subclass of bool?
    if _convert and val is not None:
        try:
            return bool(distutils.util.strtobool(val))
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
    val: Any, argname: str = None, **kwargs: Any
) -> EmptyDict:
    if val != {}:
        raise ValidationSummary(
            ValueError(argname, n_("Must be an empty dict.")))
    return EmptyDict(val)


@_add_typed_validator
def _empty_list(
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> EmptyList:
    if _convert:  # TODO why do we convert here but not for _empty_dict?
        val = list(_iterable(val, argname, _convert=_convert, **kwargs))
    if val != []:
        raise ValidationSummary(
            ValueError(argname, n_("Must be an empty list.")))
    return EmptyList(val)


@_add_typed_validator  # TODO use Union of Literal
def _realm(
    val: Any, argname: str = None, **kwargs: Any
) -> Realm:
    """A realm in the sense of the DB."""
    val = _str(val, argname, **kwargs)
    if val not in ("session", "core", "cde", "event", "ml", "assembly"):
        raise ValidationSummary(ValueError(argname, n_("Not a valid realm.")))
    return Realm(val)


@_add_typed_validator
def _cdedbid(
    val: Any, argname: str = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
) -> PrintableASCIIType:
    val = _str_type(val, argname, **kwargs)
    if re.search(r'^[ -~]*$', val) is None:
        raise ValidationSummary(ValueError(
            argname, n_("Must be printable ASCII.")))
    return PrintableASCIIType(val)


@_add_typed_validator
def _printable_ascii(
    val: Any, argname: str = None, **kwargs: Any
) -> PrintableASCII:
    """Like :py:func:`_printable_ascii_type` (parameters see there),
    but must not be empty (whitespace doesn't count).
    """
    val = _printable_ascii_type(val, argname, **kwargs)
    if not val:  # TODO leave strip here?
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return PrintableASCII(val)


@_add_typed_validator
def _alphanumeric(
    val: Any, argname: str = None, **kwargs: Any
) -> Alphanumeric:
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9]+$', val) is None:
        raise ValidationSummary(ValueError(
            argname, n_("Must be alphanumeric.")))
    return Alphanumeric(val)


@_add_typed_validator
def _csv_alphanumeric(
    val: Any, argname: str = None, **kwargs: Any
) -> CSVAlphanumeric:
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9]+(,[a-zA-Z0-9]+)*$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated alphanumeric.")))
    return CSVAlphanumeric(val)


@_add_typed_validator
def _identifier(
    val: Any, argname: str = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
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
        val: Any, argname: str = None, **kwargs: Any
) -> CSVIdentifier:
    val = _printable_ascii(val, argname, **kwargs)
    if re.search(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$', val) is None:
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated identifiers.")))
    return CSVIdentifier(val)


# TODO manual handling of @_add_typed_validator inside decorator or storage?
@_add_typed_validator
def _list_of(
    val: Any, type: Type[T],
    argname: str = None, *,
    _convert: bool = True, _allow_empty: bool = True, **kwargs: Any
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
            vals.append(_ALL_TYPED[type](
                v, argname, _convert=_convert, **kwargs))
        except ValidationSummary as e:
            errs.extend(e)
    if errs:
        raise errs

    if not _allow_empty and not vals:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))

    return vals


@_add_typed_validator
def _int_csv_list(
    val: Any, argname: str = None, **kwargs: Any
) -> IntCSVList:
    return IntCSVList(_list_of(val, int, argname, **kwargs))


@_add_typed_validator
def _cdedbid_csv_list(
    val: Any, argname: str = None, **kwargs: Any
) -> CdedbIDList:
    """This deals with strings containing multiple cdedbids,
    like when they are returned from cdedbSearchPerson.
    """
    return CdedbIDList(_list_of(val, CdedbID, argname, **kwargs))


@_add_typed_validator  # TODO split into Password and AdminPassword?
def _password_strength(
    val: Any, argname: str = None, *,
    admin: bool = False, inputs: List[str] = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
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
    'is_cde_realm': bool,
    'is_event_realm': bool,
    'is_ml_realm': bool,
    'is_assembly_realm': bool,
    'is_member': bool,
    'is_searchable': bool,
    'is_active': bool,
}


def _PERSONA_BASE_CREATION(): return {
    'username': Email,
    'notes': Optional[str],
    'is_cde_realm': bool,
    'is_event_realm': bool,
    'is_ml_realm': bool,
    'is_assembly_realm': bool,
    'is_member': bool,
    'is_searchable': bool,
    'is_active': bool,
    'display_name': str,
    'given_names': str,
    'family_name': str,
    'title': NoneType,
    'name_supplement': NoneType,
    'gender': NoneType,
    'birthday': NoneType,
    'telephone': NoneType,
    'mobile': NoneType,
    'address_supplement': NoneType,
    'address': NoneType,
    'postal_code': NoneType,
    'location': NoneType,
    'country': NoneType,
    'birth_name': NoneType,
    'address_supplement2': NoneType,
    'address2': NoneType,
    'postal_code2': NoneType,
    'location2': NoneType,
    'country2': NoneType,
    'weblink': NoneType,
    'specialisation': NoneType,
    'affiliation': NoneType,
    'timeline': NoneType,
    'interests': NoneType,
    'free_form': NoneType,
    'trial_member': NoneType,
    'decided_search': NoneType,
    'bub_search': NoneType,
    'foto': NoneType,
    'paper_expuls': NoneType,
}


def _PERSONA_CDE_CREATION(): return {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': _enum_genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[str],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'postal_code2': Optional[PrintableASCII],
    'location2': Optional[str],
    'country2': Optional[str],
    'weblink': Optional[str],
    'specialisation': Optional[str],
    'affiliation': Optional[str],
    'timeline': Optional[str],
    'interests': Optional[str],
    'free_form': Optional[str],
    'trial_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    # 'foto': Optional[str], # No foto -- this is another special
    'paper_expuls': bool,
}


def _PERSONA_EVENT_CREATION(): return {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': _enum_genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[str],
}


def _PERSONA_COMMON_FIELDS(): return {
    'username': Email,
    'notes': Optional[str],
    'is_meta_admin': bool,
    'is_core_admin': bool,
    'is_cde_admin': bool,
    'is_finance_admin': bool,
    'is_event_admin': bool,
    'is_ml_admin': bool,
    'is_assembly_admin': bool,
    'is_cdelokal_admin': bool,
    'is_cde_realm': bool,
    'is_event_realm': bool,
    'is_ml_realm': bool,
    'is_assembly_realm': bool,
    'is_member': bool,
    'is_searchable': bool,
    'is_archived': bool,
    'is_active': bool,
    'display_name': str,
    'given_names': str,
    'family_name': str,
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': _enum_genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[str],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'postal_code2': Optional[PrintableASCII],
    'location2': Optional[str],
    'country2': Optional[str],
    'weblink': Optional[str],
    'specialisation': Optional[str],
    'affiliation': Optional[str],
    'timeline': Optional[str],
    'interests': Optional[str],
    'free_form': Optional[str],
    'balance': NonNegativeDecimal,
    'trial_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    'foto': Optional[str],
    'paper_expuls': Optional[bool],
}


@_add_typed_validator
def _persona(
    val: Any, argname: str = "persona", *,
    creation: bool = False, transition: bool = False, **kwargs: Any
) -> Persona:
    """Check a persona data set.

    This is a bit tricky since attributes have different constraints
    according to which status a persona has. Since an all-encompassing
    solution would be quite tedious we expect status-bits only in case
    of creation and transition and apply restrictive tests in all other
    cases.

    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :param transition: If ``True`` test the data set on fitness for changing
      the realms of a persona.
    """
    val = _mapping(val, argname, **kwargs)

    if creation and transition:
        raise RuntimeError(
            n_("Only one of creation, transition may be specified."))

    if creation:
        temp = _examine_dictionary_fields(
            val, _PERSONA_TYPE_FIELDS, {}, allow_superfluous=True, **kwargs)
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
        optional_fields: TypeMapping = {}
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
        mandatory_fields = {'id': ID}
        for key, checkers in realm_checks.items():
            if val.get(key):
                mandatory_fields.update(checkers)
        optional_fields = {key: bool for key in realm_checks}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = _PERSONA_COMMON_FIELDS()
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    for suffix in ("", "2"):
        if val.get('postal_code' + suffix):
            try:
                postal_code = _german_postal_code(
                    val['postal_code' + suffix], 'postal_code' + suffix,
                    aux=val.get('country' + suffix), **kwargs)
                val['postal_code' + suffix] = postal_code
            except ValidationSummary as e:
                errs.extend(e)
    if errs:
        raise errs

    return Persona(val)


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
    val: Any, argname: str = None, *, _convert: bool = True, **kwargs: Any
) -> datetime.date:
    if _convert and isinstance(val, str) and len(val.strip()) >= 6:
        try:
            val = parse_date(val)
        except (ValueError, TypeError) as e:  # TODO TypeError should not occur
            raise ValidationSummary(ValueError(
                argname, n_("Invalid input for date."))) from e
    # always convert datetime to date as psycopg will try to commit them as such
    # and every call to now() returns a datetime instead of a date
    if isinstance(val, datetime.datetime):
        val = val.date()
    if not isinstance(val, datetime.date):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a datetime.date.")))
    return val


@_add_typed_validator
def _birthday(val: Any, argname: str = None, **kwargs: Any) -> Birthday:
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
    _convert: bool = True, default_date: datetime.date = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
) -> SingleDigitInt:
    """Like _int, but between +9 and -9."""
    val = _int(val, argname, **kwargs)
    if not -9 <= val <= 9:
        raise ValidationSummary(ValueError(
            argname, n_("More than one digit.")))
    return SingleDigitInt(val)


@_add_typed_validator
def _phone(
    val: Any, argname: str = None, **kwargs: Any
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
    aux: str = None, _ignore_warnings: bool = False, **kwargs: Any
) -> GermanPostalCode:
    """
    :param aux: Additional information. In this case the country belonging
        to the postal code.
    :param _ignore_warnings: If True, ignore invalid german postcodes.
    """
    val = _printable_ascii(
        val, argname, _ignore_warnings=_ignore_warnings, **kwargs)
    val = val.strip()  # TODO remove strip?
    # TODO change aux? Optional[str] -> str with default of "" or
    # "Deutschland"?
    if not aux or aux == "Deutschland":
        if val not in GERMAN_POSTAL_CODES and not _ignore_warnings:
            raise ValidationSummary(
                ValidationWarning(argname, n_("Invalid german postal code.")))
    return GermanPostalCode(val)


def _GENESIS_CASE_COMMON_FIELDS(): return {
    'username': Email,
    'given_names': str,
    'family_name': str,
    'realm': str,
    'notes': str,
}


def _GENESIS_CASE_OPTIONAL_FIELDS(): return {
    'case_status': _enum_genesisstati,
    'reviewer': ID,
}


def _GENESIS_CASE_ADDITIONAL_FIELDS(): return {
    'gender': _enum_genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': str,
    'postal_code': Optional[PrintableASCII],
    'location': str,
    'country': Optional[str],
    'birth_name': Optional[str],
    'attachment': str,
}


@_add_typed_validator
def _genesis_case(
    val: Any, argname: str = "genesis_case", *,
    creation: bool = False, **kwargs: Any
) -> GenesisCase:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    additional_fields: TypeMapping = {}
    if 'realm' in val:
        if val['realm'] not in REALM_SPECIFIC_GENESIS_FIELDS:
            raise ValidationSummary(ValueError('realm', n_(
                "This realm is not supported for genesis.")))
        else:
            additional_fields = {
                k: v for k, v in _GENESIS_CASE_ADDITIONAL_FIELDS().items()
                if k in REALM_SPECIFIC_GENESIS_FIELDS[val['realm']]}
    else:
        raise ValidationSummary(ValueError(n_("Must specify realm.")))

    if creation:
        mandatory_fields = dict(_GENESIS_CASE_COMMON_FIELDS(),
                                **additional_fields)
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_GENESIS_CASE_COMMON_FIELDS(),
                               **_GENESIS_CASE_OPTIONAL_FIELDS(),
                               **additional_fields)

    # allow_superflous=True will result in superfluous keys being removed.
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, allow_superfluous=True, **kwargs)

    if val.get('postal_code'):
        postal_code = _german_postal_code(
            val['postal_code'], 'postal_code', aux=val.get('country'), **kwargs)
        val['postal_code'] = postal_code

    return GenesisCase(val)


def _PRIVILEGE_CHANGE_COMMON_FIELDS(): return {
    'persona_id': ID,
    'submitted_by': ID,
    'status': _enum_privilegechangestati,
    'notes': str,
}


def _PRIVILEGE_CHANGE_OPTIONAL_FIELDS(): return {
    'is_meta_admin': Optional[bool],
    'is_core_admin': Optional[bool],
    'is_cde_admin': Optional[bool],
    'is_finance_admin': Optional[bool],
    'is_event_admin': Optional[bool],
    'is_ml_admin': Optional[bool],
    'is_assembly_admin': Optional[bool],
    'is_cdelokal_admin': Optional[bool],
}


@_add_typed_validator
def _privilege_change(
    val: Any, argname: str = "privilege_change", **kwargs: Any
) -> PrivilegeChange:

    val = _mapping(val, argname, **kwargs)

    val = _examine_dictionary_fields(
        val, _PRIVILEGE_CHANGE_COMMON_FIELDS(),
        _PRIVILEGE_CHANGE_OPTIONAL_FIELDS(), **kwargs)

    return PrivilegeChange(val)


# TODO also move these up?
@_add_typed_validator
def _input_file(
    val: Any, argname: str = None, **kwargs: Any
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
    encoding: str = "utf-8-sig", **kwargs: Any
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
    file_storage: bool = True, **kwargs: Any
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
    file_storage: bool = True, **kwargs: Any
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
    val: Any, argname: str = "pair", **kwargs: Any
) -> Tuple[int, int]:
    """Validate a pair of integers."""

    val: List[int] = _list_of(val, int, argname, **kwargs)

    try:
        a, b = val
    except ValueError as e:
        raise ValidationSummary(ValueError(
            argname, n_("Must contain exactly two elements."))) from e

    return (a, b)


@_add_typed_validator
def _period(
    val: Any, argname: str = "period", **kwargs: Any
) -> Period:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    optional_fields = {
        'billing_state': Optional[ID],
        'billing_done': datetime.datetime,
        'billing_count': NonNegativeInt,
        'ejection_state': Optional[ID],
        'ejection_done': datetime.datetime,
        'ejection_count': NonNegativeInt,
        'ejection_balance': NonNegativeDecimal,
        'balance_state': Optional[ID],
        'balance_done': datetime.datetime,
        'balance_trialmembers': NonNegativeInt,
        'balance_total': NonNegativeDecimal,
    }

    return Period(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


@_add_typed_validator
def _expuls(
        val: Any, argname: str = "expuls", **kwargs: Any
) -> ExPuls:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    optional_fields = {
        'addresscheck_state': Optional[ID],
        'addresscheck_done': datetime.datetime,
        'addresscheck_count': NonNegativeInt,
    }
    return ExPuls(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


def _LASTSCHRIFT_COMMON_FIELDS(): return {
    'amount': PositiveDecimal,
    'iban': IBAN,
    'account_owner': Optional[str],
    'account_address': Optional[str],
    'notes': Optional[str],
}


def _LASTSCHRIFT_OPTIONAL_FIELDS(): return {
    'granted_at': datetime.datetime,
    'revoked_at': Optional[datetime.datetime],
}


@_add_typed_validator
def _lastschrift(
    val: Any, argname: str = "lastschrift", *,
    creation: bool = False, **kwargs: Any
) -> Lastschrift:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)
    if creation:
        mandatory_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(), persona_id=ID)
        optional_fields = _LASTSCHRIFT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(),
                               **_LASTSCHRIFT_OPTIONAL_FIELDS())
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)
    return Lastschrift(val)


# TODO move above
@_add_typed_validator
def _iban(
    val: Any, argname: str = "iban", **kwargs: Any
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
    'amount': PositiveDecimal,
    'status': _enum_lastschrifttransactionstati,
    'issued_at': datetime.datetime,
    'processed_at': Optional[datetime.datetime],
    'tally': Optional[decimal.Decimal],
}


@_add_typed_validator
def _lastschrift_transaction(
    val: Any, argname: str = "lastschrift_transaction", *,
    creation: bool = False, **kwargs: Any
) -> LastschriftTransaction:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    # TODO make a unified approach for creation validation?
    """
    val = _mapping(val, argname, **kwargs)
    if creation:
        mandatory_fields = {
            'lastschrift_id': ID,
            'period_id': ID,
        }
        optional_fields = _LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS()
    else:
        raise ValidationSummary(ValueError(argname, n_(
            "Modification of lastschrift transactions not supported.")))
    return LastschriftTransaction(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


_SEPA_TRANSACTIONS_FIELDS = {
    'issued_at': datetime.datetime,
    'lastschrift_id': ID,
    'period_id': ID,
    'mandate_reference': str,
    'amount': PositiveDecimal,
    'iban': IBAN,
    'mandate_date': datetime.date,
    'account_owner': str,
    'unique_id': str,
    'subject': str,
    'type': str,
}
_SEPA_TRANSACTIONS_LIMITS = {
    'account_owner': 70,
    'subject': 140,
    'mandate_reference': 35,
    'unique_id': 35,
}


# TODO make use of _list_of?
@_add_typed_validator
def _sepa_transactions(
    val: Any, argname: str = "sepa_transactions", **kwargs: Any
) -> SepaTransactions:
    val = _iterable(val, argname, **kwargs)

    mandatory_fields = _SEPA_TRANSACTIONS_FIELDS
    ret = []
    errs = ValidationSummary()

    for entry in val:
        try:
            entry = _mapping(entry, argname, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        try:
            entry = _examine_dictionary_fields(
                entry, mandatory_fields, {}, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        for attribute, validator in _SEPA_TRANSACTIONS_FIELDS.items():
            if validator == _str:
                entry[attribute] = asciificator(entry[attribute])
            if attribute in _SEPA_TRANSACTIONS_LIMITS:
                if len(entry[attribute]
                       ) > _SEPA_TRANSACTIONS_LIMITS[attribute]:
                    errs.append(ValueError(attribute, n_("Too long.")))

        if entry['type'] not in ("OOFF", "FRST", "RCUR"):
            errs.append(ValueError('type', n_("Invalid constant.")))
        if errs:
            continue  # TODO is this not equivalent to break in this situation?
        ret.append(entry)

    if errs:
        raise errs

    return SepaTransactions(ret)


_SEPA_META_FIELDS = {
    'message_id': str,
    'total_sum': PositiveDecimal,
    'partial_sums': Mapping,
    'count': int,
    'sender': Mapping,
    'payment_date': datetime.date,
}
_SEPA_SENDER_FIELDS = {
    'name': str,
    'address': Iterable,
    'country': str,
    'iban': IBAN,
    'glaeubigerid': str,
}
_SEPA_META_LIMITS = {
    'message_id': 35,
    # 'name': 70, easier to check by hand
    # 'address': 70, has to be checked by hand
    'glaeubigerid': 35,
}


@_add_typed_validator
def _sepa_meta(
    val: Any, argname: str = "sepa_meta", **kwargs: Any
) -> SepaMeta:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = _SEPA_META_FIELDS
    val = _examine_dictionary_fields(
        val, mandatory_fields, {}, **kwargs)

    mandatory_fields = _SEPA_SENDER_FIELDS
    val['sender'] = _examine_dictionary_fields(
        val['sender'], mandatory_fields, {}, **kwargs)

    errs = ValidationSummary()
    for attribute, validator in _SEPA_META_FIELDS.items():
        if validator == str:
            val[attribute] = asciificator(val[attribute])
        if attribute in _SEPA_META_LIMITS:
            if len(val[attribute]) > _SEPA_META_LIMITS[attribute]:
                errs.append(ValueError(attribute, n_("Too long.")))

    if val['sender']['country'] != "DE":
        errs.append(ValueError('country', n_("Unsupported constant.")))
    if len(val['sender']['address']) != 2:
        errs.append(ValueError('address', n_("Exactly two lines required.")))
    val['sender']['address'] = tuple(
        map(asciificator, val['sender']['address']))

    for line in val['sender']['address']:
        if len(line) > 70:
            errs.append(ValueError('address', n_("Too long.")))

    for attribute, validator in _SEPA_SENDER_FIELDS.items():
        if validator == _str:
            val['sender'][attribute] = asciificator(val['sender'][attribute])
    if len(val['sender']['name']) > 70:
        errs.append(ValueError('name', n_("Too long.")))

    if errs:
        raise errs

    return SepaMeta(val)


@_add_typed_validator
def _safe_str(
    val: Any, argname: str = None, **kwargs: Any
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


@_add_typed_validator
def _meta_info(
    val: Any, keys: List[str], argname: str = "meta_info", **kwargs: Any
) -> MetaInfo:
    val = _mapping(val, argname, **kwargs)

    optional_fields = {key: Optional[str] for key in keys}
    val = _examine_dictionary_fields(
        val, {}, optional_fields, **kwargs)

    return MetaInfo(val)


def _INSTITUTION_COMMON_FIELDS(): return {
    'title': str,
    'shortname': str,
}


@_add_typed_validator
def _institution(
    val: Any, argname: str = "institution", *,
    creation: bool = False, **kwargs: Any
) -> Institution:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _INSTITUTION_COMMON_FIELDS()
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = _INSTITUTION_COMMON_FIELDS()
    return Institution(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _PAST_EVENT_COMMON_FIELDS(): return {
    'title': str,
    'shortname': str,
    'institution': ID,
    'tempus': datetime.date,
    'description': Optional[str],
}


def _PAST_EVENT_OPTIONAL_FIELDS(): return {
    'notes': Optional[str],
}


@_add_typed_validator
def _past_event(
    val: Any, argname: str = "past_event", *,
    creation: bool = False, **kwargs: Any
) -> PastEvent:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _PAST_EVENT_COMMON_FIELDS()
        optional_fields = _PAST_EVENT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_PAST_EVENT_COMMON_FIELDS(),
                               **_PAST_EVENT_OPTIONAL_FIELDS())
    return PastEvent(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _EVENT_COMMON_FIELDS(): return {
    'title': str,
    'institution': ID,
    'description': Optional[str],
    'shortname': Identifier,
}


def _EVENT_OPTIONAL_FIELDS(): return {
    'offline_lock': bool,
    'is_visible': bool,
    'is_course_list_visible': bool,
    'is_course_state_visible': bool,
    'use_additional_questionnaire': bool,
    'registration_start': Optional[datetime.datetime],
    'registration_soft_limit': Optional[datetime.datetime],
    'registration_hard_limit': Optional[datetime.datetime],
    'notes': Optional[str],
    'is_participant_list_visible': bool,
    'courses_in_participant_list': bool,
    'is_cancelled': bool,
    'is_archived': bool,
    'iban': Optional[IBAN],
    'nonmember_surcharge': NonNegativeDecimal,
    'orgas': Iterable,
    'mail_text': Optional[str],
    'parts': Mapping,
    'fields': Mapping,
    'fee_modifiers': Mapping,
    'registration_text': Optional[str],
    'orga_address': Optional[Email],
    'lodge_field': Optional[ID],
    'camping_mat_field': Optional[ID],
    'course_room_field': Optional[ID],
}


@_add_typed_validator
def _event(
    val: Any, argname: str = "event", *,
    creation: bool = False, **kwargs: Any
) -> Event:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _EVENT_COMMON_FIELDS()
        optional_fields = _EVENT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_EVENT_COMMON_FIELDS(),
                               **_EVENT_OPTIONAL_FIELDS())
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'registration_soft_limit' in val and 'registration_hard_limit' in val:
        if (val['registration_soft_limit']
                and val['registration_hard_limit']
                and (val['registration_soft_limit']
                     > val['registration_hard_limit'])):
            errs.append(ValueError("registration_soft_limit", n_(
                "Must be before or equal to hard limit.")))
        if val.get('registration_start') and (
                val['registration_soft_limit'] and
                val['registration_start'] > val['registration_soft_limit']
                or val['registration_hard_limit'] and
                val['registration_start'] > val['registration_hard_limit']):
            errs.append(ValueError("registration_start", n_(
                "Must be before hard and soft limit.")))

    if 'orgas' in val:
        orgas = set()
        for anid in val['orgas']:
            try:
                v = _id(anid, 'orgas', **kwargs)
                orgas.add(v)
            except ValidationSummary as e:
                errs.extend(e)
        val['orgas'] = orgas

    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            try:
                anid = _int(anid, 'parts', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:  # TODO maybe use continue instead of else or move into try block
                creation = (anid < 0)
                try:
                    part = _event_part_or_None(  # type: ignore
                        part, 'parts', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newparts[anid] = part
        val['parts'] = newparts

    if 'fields' in val:
        newfields = {}
        # TODO maybe replace all these loops with a helper function
        for anid, field in val['fields'].items():
            try:
                anid = _int(anid, 'fields', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                try:
                    field = _event_field_or_None(  # type: ignore
                        field, 'fields', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newfields[anid] = field
        val['fields'] = newfields

    if 'fee_modifiers' in val:
        new_modifiers = {}
        for anid, fee_modifier in val['fee_modifiers'].items():
            try:
                anid = _int(anid, 'fee_modifiers', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                try:
                    fee_modifier = _event_fee_modifier_or_None(  # type: ignore
                        fee_modifier, 'fee_modifiers', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    new_modifiers[anid] = fee_modifier

        msg = n_("Must not have multiple fee modifiers linked to the same"
                 " field in one event part.")

        e1: EventFeeModifier
        e2: EventFeeModifier
        for e1, e2 in itertools.combinations(
                filter(None, val['fee_modifiers'].values()), 2):
            if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:  # type: ignore
                if e1['part_id'] == e2['part_id']:  # type: ignore
                    errs.append(ValueError('fee_modifiers', msg))

    if errs:
        raise errs

    return Event(val)


_EVENT_PART_COMMON_FIELDS = {
    'title': str,
    'shortname': str,
    'part_begin': datetime.date,
    'part_end': datetime.date,
    'fee': NonNegativeDecimal,
    'waitlist_field': Optional[ID],
    'tracks': Mapping,
}


@_add_typed_validator
def _event_part(
    val: Any, argname: str = "event_part", *,
    creation: bool = False, **kwargs: Any
) -> EventPart:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _EVENT_PART_COMMON_FIELDS
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_PART_COMMON_FIELDS

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if ('part_begin' in val and 'part_end' in val and val['part_begin'] > val['part_end']):
        errs.append(ValueError("part_end", n_("Must be later than begin.")))

    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            try:
                anid = _int(anid, 'tracks', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                try:
                    if creation:
                        track = _event_track(
                            track, 'tracks', creation=True, **kwargs)
                    else:
                        track = _event_track_or_None(  # type: ignore
                            track, 'tracks', **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newtracks[anid] = track
        val['tracks'] = newtracks

    if errs:
        raise errs

    return EventPart(val)


_EVENT_TRACK_COMMON_FIELDS = {
    'title': str,
    'shortname': str,
    'num_choices': NonNegativeInt,
    'min_choices': NonNegativeInt,
    'sortkey': int,
}


@_add_typed_validator
def _event_track(
    val: Any, argname: str = "tracks", *,
    creation: bool = False, **kwargs: Any
) -> EventTrack:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _EVENT_TRACK_COMMON_FIELDS
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_TRACK_COMMON_FIELDS

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if ('num_choices' in val and 'min_choices' in val and val['min_choices'] > val['num_choices']):
        raise ValidationSummary(ValueError("min_choices", n_(
            "Must be less or equal than total Course Choices.")))

    return EventTrack(val)


def _EVENT_FIELD_COMMON_FIELDS(extra_suffix): return {
    'kind{}'.format(extra_suffix): _enum_fielddatatypes,
    'association{}'.format(extra_suffix): _enum_fieldassociations,
    'entries{}'.format(extra_suffix): Any,
}


@_add_typed_validator
def _event_field(
    val: Any, argname: str = "event_field", *,
    creation: bool = False, extra_suffix: str = "", **kwargs: Any
) -> EventField:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :param extra_suffix: Suffix appended to all keys. This is due to the
      necessity of the frontend to create unambiguous names.
    """
    val = _mapping(val, argname, **kwargs)

    field_name_key = "field_name{}".format(extra_suffix)
    if creation:
        spec = _EVENT_FIELD_COMMON_FIELDS(extra_suffix)
        spec[field_name_key] = RestrictiveIdentifier
        mandatory_fields = spec
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_FIELD_COMMON_FIELDS(extra_suffix)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    entries_key = "entries{}".format(extra_suffix)
    kind_key = "kind{}".format(extra_suffix)

    errs = ValidationSummary()
    if not val.get(entries_key, True):
        val[entries_key] = None
    if entries_key in val and val[entries_key] is not None:
        if isinstance(val[entries_key], str) and kwargs.get("_convert", True):
            val[entries_key] = tuple(tuple(y.strip() for y in x.split(';', 1))
                                     for x in val[entries_key].split('\n'))
        try:
            oldentries = _iterable(val[entries_key], entries_key, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            # TODO replace combine entries and seen_values into dict?
            seen_values: Set[str] = set()
            entries = []
            for idx, entry in enumerate(oldentries):
                try:
                    value, description = entry
                except (ValueError, TypeError):
                    errs.append(ValueError(entries_key, n_(
                        "Invalid entry in line %(line)s."), {'line': idx + 1}))
                else:
                    # Validate value according to type and use the opportunity
                    # to normalize the value by transforming it back to string
                    try:
                        value = _by_field_datatype(value, entries_key, kind=val.get(
                            kind_key, FieldDatatypes.str), **kwargs)
                        description = _str(description, entries_key, **kwargs)
                    except ValidationSummary as e:
                        errs.extend(e)
                    else:
                        if value in seen_values:
                            errs.append(ValueError(
                                entries_key, n_("Duplicate value.")))
                        else:
                            entries.append((value, description))
                            seen_values.add(value)
            val[entries_key] = entries

    if errs:
        raise errs

    return EventField(val)


def _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix): return {
    "modifier_name{}".format(extra_suffix): _restrictive_identifier,
    "amount{}".format(extra_suffix): _decimal,
    "part_id{}".format(extra_suffix): ID,
    "field_id{}".format(extra_suffix): ID,
}


@_add_typed_validator
def _event_fee_modifier(
    val: Any, argname: str = "fee_modifiers", *,
    creation: bool = False, extra_suffix: str = '', **kwargs: Any
) -> EventFeeModifier:

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix)
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    return EventFeeModifier(val)


def _PAST_COURSE_COMMON_FIELDS(): return {
    'nr': str,
    'title': str,
    'description': Optional[str],
}


@_add_typed_validator
def _past_course(
    val: Any, argname: str = "past_course", *,
    creation: bool = False, **kwargs: Any
) -> PastCourse:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    # TODO create decorator for converting val to mapping?
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_PAST_COURSE_COMMON_FIELDS(), pevent_id=ID)
        optional_fields: TypeMapping = {}
    else:
        # no pevent_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = _PAST_COURSE_COMMON_FIELDS()

    # TODO make these consistent (w or w/o intermediate assignment)
    return PastCourse(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _COURSE_COMMON_FIELDS(): return {
    'title': str,
    'description': Optional[str],
    'nr': str,
    'shortname': str,
    'instructors': Optional[str],
    'max_size': Optional[NonNegativeInt],
    'min_size': Optional[NonNegativeInt],
    'notes': Optional[str],
}


_COURSE_OPTIONAL_FIELDS = {
    'segments': Iterable,
    'active_segments': Iterable,
    'fields': Mapping,
}


@_add_typed_validator
def _course(
    val: Any, argname: str = "course", *,
    creation: bool = False, **kwargs: Any
) -> Course:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    # TODO where is creation actually set and can it be places inside kwargs?

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_COURSE_COMMON_FIELDS(), event_id=ID)
        optional_fields = _COURSE_OPTIONAL_FIELDS
        # TODO make dict(field, ...) vs {**fields, ...} consistent
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = dict(_COURSE_COMMON_FIELDS(),
                               **_COURSE_OPTIONAL_FIELDS)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'segments' in val:
        # TODO why use intermediate set?
        segments = set()
        for anid in val['segments']:
            # TODO replace these internal calls with calls to the public functions?
            try:
                v = _id(anid, 'segments', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                segments.add(v)
        val['segments'] = segments
    if 'active_segments' in val:
        active_segments = set()
        for anid in val['active_segments']:
            try:
                v = _id(anid, 'active_segments', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                active_segments.add(v)
        val['active_segments'] = active_segments
    if 'segments' in val and 'active_segments' in val:
        if not val['active_segments'] <= val['segments']:
            errs.append(ValueError('segments', n_(
                "Must be a superset of active segments.")))
    # the check of fields is delegated to _event_associated_fields

    if errs:
        raise errs

    return Course(val)


def _REGISTRATION_COMMON_FIELDS(): return {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': Optional[str],
    'parts': Mapping,
    'tracks': Mapping,
}


def _REGISTRATION_OPTIONAL_FIELDS(): return {
    'parental_agreement': bool,
    'real_persona_id': Optional[ID],
    'orga_notes': Optional[str],
    'payment': Optional[datetime.date],
    'amount_paid': NonNegativeDecimal,
    'checkin': Optional[datetime.datetime],
    'fields': Mapping
}
# TODO make trailing comma consistent


@_add_typed_validator
def _registration(
    val: Any, argname: str = "registration", *,
    creation: bool = False, **kwargs: Any
) -> Registration:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        # creation does not allow fields for sake of simplicity
        mandatory_fields = dict(_REGISTRATION_COMMON_FIELDS(),
                                persona_id=ID, event_id=ID)
        optional_fields = _REGISTRATION_OPTIONAL_FIELDS()
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = dict(
            _REGISTRATION_COMMON_FIELDS(),
            **_REGISTRATION_OPTIONAL_FIELDS())

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            try:
                anid = _id(anid, 'parts', **kwargs)
                part = _registration_part_or_None(  # type: ignore
                    part, 'parts', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newparts[anid] = part
        val['parts'] = newparts
    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            try:
                anid = _id(anid, 'tracks', **kwargs)
                track = _registration_track_or_None(  # type: ignore
                    track, 'tracks', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newtracks[anid] = track
        val['tracks'] = newtracks
    # the check of fields is delegated to _event_associated_fields

    # TODO check if raising early is possible (do we use all errors?)
    if errs:
        raise errs

    return Registration(val)


@_add_typed_validator
def _registration_part(
    val: Any, argname: str = "registration_part", **kwargs: Any
) -> RegistrationPart:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields = {
        'status': _enum_registrationpartstati,  # type: ignore
        'lodgement_id': Optional[ID],
        'is_camping_mat': bool,
    }
    return RegistrationPart(_examine_dictionary_fields(val, {}, optional_fields, **kwargs))


# TODO make type of kwargs to be bools only?
@_add_typed_validator
def _registration_track(
        val: Any, argname: str = "registration_track", **kwargs: Any
) -> RegistrationTrack:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields = {
        'course_id': Optional[ID],
        'course_instructor': Optional[ID],
        'choices': Iterable,
    }

    val = _examine_dictionary_fields(val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'choices' in val:
        newchoices = []  # TODO why sometimes set and sometimes list?
        for choice in val['choices']:
            try:
                choice = _id(choice, 'choices', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                break  # TODO why break here?
            else:
                newchoices.append(choice)
        val['choices'] = newchoices

    if errs:
        raise errs

    return RegistrationTrack(val)


@_add_typed_validator
def _event_associated_fields(
    val: Any, argname: str = "fields", *,
    fields: Dict[int, CdEDBObject], association: FieldAssociations, **kwargs: Any
) -> EventAssociatedFields:
    """Check fields associated to an event entity.

    This can be used for all different kinds of entities (currently
    registration, courses and lodgements) via the multiplexing in form of
    the ``association`` parameter.

    :param fields: definition of the event specific fields which are available
    """
    # TODO document association parameter?

    val = _mapping(val, argname, **kwargs)

    # TODO why is deepcopy used here
    raw = copy.deepcopy(val)
    datatypes: TypeMapping = {}
    for field in fields.values():
        if field['association'] == association:
            dt = _enum_fielddatatypes(  # type: ignore
                field['kind'], field['field_name'], **kwargs)
            datatypes[field['field_name']] = cast(Type[Any], eval(
                f"Optional[{dt.name}]",
                {
                    'Optional': Optional,  # type: ignore
                    'date': datetime.date,
                    'datetime': datetime.datetime
                }))
    optional_fields = {
        field['field_name']: datatypes[field['field_name']]
        for field in fields.values() if field['association'] == association
    }

    val = _examine_dictionary_fields(
        val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    lookup: Dict[str, int] = {v['field_name']: k for k, v in fields.items()}
    for field in val:
        field_id = lookup[field]
        if fields[field_id]['entries'] is not None and val[field] is not None:
            if not any(str(raw[field]) == x
                       for x, _ in fields[field_id]['entries']):
                errs.append(ValueError(
                    field, n_("Entry not in definition list.")))
    if errs:
        raise errs

    return EventAssociatedFields(val)


def _LODGEMENT_GROUP_FIELDS(): return {
    'title': str,
}


# TODO should this be an underscore in the argname?
@_add_typed_validator
def _lodgement_group(
    val: Any, argname: str = "lodgement group", *,
    creation: bool = False, **kwargs: Any
) -> LodgementGroup:
    """
    :param creation: If ``True`` test the data set for fitness for creation
        of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_LODGEMENT_GROUP_FIELDS(), event_id=ID)
        optional_fields: TypeMapping = {}
    else:
        # no event_id, since the associated event should be fixed.
        mandatory_fields = {'id': ID}
        optional_fields = _LODGEMENT_GROUP_FIELDS()

    return LodgementGroup(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _LODGEMENT_COMMON_FIELDS(): return {
    'title': str,
    'regular_capacity': NonNegativeInt,
    'camping_mat_capacity': NonNegativeInt,
    'notes': Optional[str],
    'group_id': Optional[ID],
}


_LODGEMENT_OPTIONAL_FIELDS = {
    'fields': Mapping,
}


@_add_typed_validator
def _lodgement(
    val: Any, argname: str = "lodgement", *,
    creation: bool = False, **kwargs: Any
) -> Lodgement:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_LODGEMENT_COMMON_FIELDS(), event_id=ID)
        optional_fields = _LODGEMENT_OPTIONAL_FIELDS
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = dict(_LODGEMENT_COMMON_FIELDS(),
                               **_LODGEMENT_OPTIONAL_FIELDS)

    # the check of fields is delegated to _event_associated_fields
    return Lodgement(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


# TODO is kind optional?
# TODO make argname non-optional
@_add_typed_validator
def _by_field_datatype(
    val: Any, argname: str = None, *, kind: FieldDatatypes, **kwargs: Any
) -> ByFieldDatatype:
    """
    :type kind: FieldDatatypes or int
    """
    kind = FieldDatatypes(kind)
    validator = getattr(current_module, "_{}".format(kind.name))
    val = validator(val, argname, **kwargs)

    if kind == FieldDatatypes.date or kind == FieldDatatypes.datetime:
        val = val.isoformat()
    else:
        val = str(val)

    return ByFieldDatatype(val)


# TODO change parameter order to make more consistent?
# TODO type fee_modifiers
@_add_typed_validator
def _questionnaire(
    val: Any, field_definitions: CdEDBObjectMap, fee_modifiers: CdEDBObjectMap,
    argname: str = "questionnaire",
    **kwargs: Any
) -> Questionnaire:
    """
    :type field_definitions: Dict[int, Dict]
    """

    val = _mapping(val, argname, **kwargs)

    errs = ValidationSummary()
    ret: Dict[int, List[CdEDBObject]] = {}
    fee_modifier_fields = {e['field_id'] for e in fee_modifiers.values()}
    for k, v in copy.deepcopy(val).items():
        try:
            k = _enum_questionnaireusages(k, argname, **kwargs)  # type: ignore
            v = _iterable(v, argname, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            ret[k] = []
            mandatory_fields = {
                'field_id': Optional[ID],
                'title': Optional[str],
                'info': Optional[str],
                'input_size': Optional[int],
                'readonly': Optional[bool],
                'default_value': Optional[str],
            }
            optional_fields = {
                'kind': _enum_questionnaireusages,  # type: ignore
            }
            for value in v:
                try:
                    value = _mapping(value, argname, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                    continue

                try:
                    value = _examine_dictionary_fields(
                        value, mandatory_fields, optional_fields, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                    continue

                if 'kind' in value:
                    if value['kind'] != k:
                        errs.append(ValueError('kind',
                                               n_("Incorrect kind for this part of the questionnaire")))
                else:
                    value['kind'] = k

                if value['field_id'] and value['default_value']:
                    field = field_definitions.get(value['field_id'], None)
                    if not field:
                        errs.append(KeyError('default_value', n_(
                            "Referenced field does not exist.")))
                        continue

                    try:
                        value['default_value'] = _by_field_datatype(
                            value['default_value'], "default_value",
                            kind=field.get('kind', FieldDatatypes.str), **kwargs)
                    except ValidationSummary as e:
                        errs.extend(e)

                field_id = value['field_id']
                if field_id and field_id in fee_modifier_fields:
                    if not k.allow_fee_modifier():
                        errs.append(ValueError('kind', n_("Inappropriate questionnaire usage for fee"
                                                          " modifier field.")))
                if value['readonly'] and not k.allow_readonly():
                    errs.append(ValueError('readonly', n_("Registration questionnaire rows may not be"
                                                          " readonly.")))
                ret[k].append(value)

    all_rows = itertools.chain.from_iterable(ret.values())
    for e1, e2 in itertools.combinations(all_rows, 2):
        if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:
            errs.append(ValueError('field_id', n_(
                "Must not duplicate field.")))

    if errs:
        raise errs

    return Questionnaire(ret)


# TODO move above
@_add_typed_validator
def _json(
    val: Any, argname: str = "json", *, _convert: bool = True, **kwargs: Any
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


@_add_typed_validator
def _serialized_event_upload(
    val: Any, argname: str = "serialized_event_upload", **kwargs: Any
) -> SerializedEventUpload:
    """Check an event data set for import after offline usage."""
    # TODO provide docstrings in more validators

    val = _input_file(val, argname, **kwargs)

    val = _json(val, argname, **kwargs)

    return SerializedEventUpload(_serialized_event(val, argname, **kwargs))


@_add_typed_validator
def _serialized_event(
    val: Any, argname: str = "serialized_event", **kwargs: Any
) -> SerializedEvent:
    """Check an event data set for import after offline usage."""
    # TODO why does this have the same docstring as the one above

    # First a basic check
    val = _mapping(val, argname, **kwargs)

    if 'kind' not in val or val['kind'] != "full":
        raise ValidationSummary(
            KeyError(argname, n_("Only full exports are supported.")))

    mandatory_fields = {
        'EVENT_SCHEMA_VERSION': Tuple[int, int],
        'kind': str,
        'id': ID,
        'timestamp': datetime.datetime,
        'event.events': Mapping,
        'event.event_parts': Mapping,
        'event.course_tracks': Mapping,
        'event.courses': Mapping,
        'event.course_segments': Mapping,
        'event.log': Mapping,
        'event.orgas': Mapping,
        'event.field_definitions': Mapping,
        'event.lodgement_groups': Mapping,
        'event.lodgements': Mapping,
        'event.registrations': Mapping,
        'event.registration_parts': Mapping,
        'event.registration_tracks': Mapping,
        'event.course_choices': Mapping,
        'event.questionnaire_rows': Mapping,
        'event.fee_modifiers': Mapping,
    }
    optional_fields = {
        'core.personas': Mapping,
    }
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if val['EVENT_SCHEMA_VERSION'] != EVENT_SCHEMA_VERSION:
        raise ValidationSummary(ValueError(
            argname, n_("Schema version mismatch.")))

    # Second a thorough investigation
    #
    # We reuse the existing validators, but have to augment them since the
    # data looks a bit different.
    # TODO replace the functions with types
    table_validators = {
        'event.events': _event,
        'event.event_parts': _augment_dict_validator(
            _event_part, {'id': ID, 'event_id': ID}),
        'event.course_tracks': _augment_dict_validator(
            _event_track, {'id': ID, 'part_id': ID}),
        'event.courses': _augment_dict_validator(
            _course, {'event_id': ID}),
        'event.course_segments': _augment_dict_validator(
            _empty_dict, {'id': ID, 'course_id': ID, 'track_id': ID,
                          'is_active': bool}),
        'event.log': _augment_dict_validator(
            _empty_dict, {'id': ID, 'ctime': datetime.datetime, 'code': int,
                          'submitted_by': ID, 'event_id': Optional[ID],
                          'persona_id': Optional[ID],
                          'change_note': Optional[str], }),
        'event.orgas': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID, 'persona_id': ID}),
        'event.field_definitions': _augment_dict_validator(
            _event_field, {'id': ID, 'event_id': ID,
                           'field_name': RestrictiveIdentifier}),
        'event.lodgement_groups': _augment_dict_validator(
            _lodgement_group, {'event_id': ID}),
        'event.lodgements': _augment_dict_validator(
            _lodgement, {'event_id': ID}),
        'event.registrations': _augment_dict_validator(
            _registration, {'event_id': ID, 'persona_id': ID,
                            'amount_owed': NonNegativeDecimal}),
        'event.registration_parts': _augment_dict_validator(
            _registration_part, {'id': ID, 'part_id': ID,
                                 'registration_id': ID}),
        'event.registration_tracks': _augment_dict_validator(
            _registration_track, {'id': ID, 'track_id': ID,
                                  'registration_id': ID}),
        'event.course_choices': _augment_dict_validator(
            _empty_dict, {'id': ID, 'course_id': ID, 'track_id': ID,
                          'registration_id': ID, 'rank': int}),
        'event.questionnaire_rows': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID, 'pos': int,
                          'field_id': Optional[ID], 'title': Optional[str],
                          'info': Optional[str], 'input_size': Optional[int],
                          'readonly': Optional[bool],
                          'kind': _enum_questionnaireusages,  # type: ignore
                          }),
        'event.fee_modifiers': _event_fee_modifier,
    }

    errs = ValidationSummary()
    for table, validator in table_validators.items():
        new_table = {}
        for key, entry in val[table].items():
            try:
                new_entry = validator(entry, table, **kwargs)  # type: ignore
                # _convert: bool = True to fix JSON key restriction
                new_key = _int(key, table, **{**kwargs, '_convert': True})
            except ValidationSummary as e:
                errs.extend(e)
            else:
                new_table[new_key] = new_entry
        val[table] = new_table

    if errs:
        raise errs

    # Third a consistency check
    if len(val['event.events']) != 1:
        errs.append(ValueError('event.events', n_(
            "Only a single event is supported.")))
    if (len(val['event.events'])
            and val['id'] != val['event.events'][val['id']]['id']):
        errs.append(ValueError('event.events', n_("Wrong event specified.")))

    for k, v in val.items():
        if k not in ('id', 'EVENT_SCHEMA_VERSION', 'timestamp', 'kind'):
            for event in v.values():
                if event.get('event_id') and event['event_id'] != val['id']:
                    errs.append(ValueError(k, n_("Mismatched event.")))

    if errs:
        raise errs

    return SerializedEvent(val)


@_add_typed_validator
def _serialized_partial_event_upload(
    val: Any, argname: str = "serialized_partial_event_upload", **kwargs: Any
) -> SerializedPartialEventUpload:
    """Check an event data set for delta import."""

    val = _input_file(val, argname, **kwargs)

    val = _json(val, argname, **kwargs)

    return SerializedPartialEventUpload(_serialized_partial_event(
        val, argname, **kwargs))


@_add_typed_validator
def _serialized_partial_event(
    val: Any, argname: str = "serialized_partial_event", **kwargs: Any
) -> SerializedPartialEvent:
    """Check an event data set for delta import."""

    # First a basic check
    val = _mapping(val, argname, **kwargs)

    if 'kind' not in val or val['kind'] != "partial":
        raise ValidationSummary(KeyError(argname, n_(
            "Only partial exports are supported.")))

    mandatory_fields = {
        'EVENT_SCHEMA_VERSION': Tuple[int, int],
        'kind': str,
        'id': ID,
        'timestamp': datetime.datetime,
    }
    optional_fields = {
        'courses': Mapping,
        'lodgement_groups': Mapping,
        'lodgements': Mapping,
        'registrations': Mapping,
    }

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if not((EVENT_SCHEMA_VERSION[0], 0) <= val['EVENT_SCHEMA_VERSION']
           <= EVENT_SCHEMA_VERSION):
        raise ValidationSummary(ValueError(
            argname, n_("Schema version mismatch.")))

    domain_validators = {
        'courses': Optional[PartialCourse],
        'lodgement_groups': Optional[PartialLodgementGroup],
        'lodgements': Optional[PartialLodgement],
        'registrations': Optional[PartialRegistration],
    }

    errs = ValidationSummary()
    for domain, type_ in domain_validators.items():
        if domain not in val:
            continue
        new_dict = {}
        for key, entry in val[domain].items():
            try:
                # fix JSON key restriction
                new_key = _int(key, domain, **{**kwargs, '_convert': True})
            except ValidationSummary as e:
                errs.extend(e)
                continue

            creation = (new_key < 0)
            try:
                new_entry = _ALL_TYPED[type_](
                    entry, domain, creation=creation, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                new_dict[new_key] = new_entry
        val[domain] = new_dict

    if errs:
        raise errs

    return SerializedPartialEvent(val)


def _PARTIAL_COURSE_COMMON_FIELDS(): return {
    'title': str,
    'description': Optional[str],
    'nr': Optional[str],
    'shortname': str,
    'instructors': Optional[str],
    'max_size': Optional[int],
    'min_size': Optional[int],
    'notes': Optional[str],
}


_PARTIAL_COURSE_OPTIONAL_FIELDS = {
    'segments': Mapping,
    'fields': Mapping,
}


@_add_typed_validator
def _partial_course(
    val: Any, argname: str = "course", *, creation: bool = False, **kwargs: Any
) -> PartialCourse:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _PARTIAL_COURSE_COMMON_FIELDS()
        optional_fields = _PARTIAL_COURSE_OPTIONAL_FIELDS
    else:
        mandatory_fields = {}
        optional_fields = dict(_PARTIAL_COURSE_COMMON_FIELDS(),
                               **_PARTIAL_COURSE_OPTIONAL_FIELDS)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'segments' in val:
        new_dict = {}
        for key, entry in val['segments'].items():
            try:
                new_key = _int(key, 'segments', **{**kwargs, '_convert': True})
                new_entry = _bool_or_None(  # type: ignore
                    entry, 'segments', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                new_dict[new_key] = new_entry
        val['segments'] = new_dict
    # the check of fields is delegated to _event_associated_fields

    if errs:
        raise errs

    return PartialCourse(val)


def _PARTIAL_LODGEMENT_GROUP_FIELDS(): return {
    'title': str,
}


# TODO difference between partial and non-partial lodgement groups?
@_add_typed_validator
def _partial_lodgement_group(
    val: Any, argname: str = "lodgement_group", *,
    creation: bool = False, **kwargs: Any
) -> PartialLodgementGroup:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _PARTIAL_LODGEMENT_GROUP_FIELDS()
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = _PARTIAL_LODGEMENT_GROUP_FIELDS()

    return PartialLodgementGroup(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _PARTIAL_LODGEMENT_COMMON_FIELDS(): return {
    'title': str,
    'regular_capacity': NonNegativeInt,
    'camping_mat_capacity': NonNegativeInt,
    'notes': Optional[str],
    'group_id': Optional[PartialImportID],
}


_PARTIAL_LODGEMENT_OPTIONAL_FIELDS = {
    'fields': Mapping,
}


@_add_typed_validator
def _partial_lodgement(
    val: Any, argname: str = "lodgement", *,
    creation: bool = False, **kwargs: Any
) -> PartialLodgement:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _PARTIAL_LODGEMENT_COMMON_FIELDS()
        optional_fields = _PARTIAL_LODGEMENT_OPTIONAL_FIELDS
    else:
        mandatory_fields = {}
        optional_fields = dict(_PARTIAL_LODGEMENT_COMMON_FIELDS(),
                               **_PARTIAL_LODGEMENT_OPTIONAL_FIELDS)

    # the check of fields is delegated to _event_associated_fields
    return PartialLodgement(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _PARTIAL_REGISTRATION_COMMON_FIELDS(): return {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': Optional[str],
    'parts': Mapping,
    'tracks': Mapping,
}


def _PARTIAL_REGISTRATION_OPTIONAL_FIELDS(): return {
    'parental_agreement': Optional[bool],
    'orga_notes': Optional[str],
    'payment': Optional[datetime.date],
    'amount_paid': NonNegativeDecimal,
    'amount_owed': NonNegativeDecimal,
    'checkin': Optional[datetime.datetime],
    'fields': Mapping,
}

# TODO Can we auto generate all these partial validators?


@_add_typed_validator
def _partial_registration(
    val: Any, argname: str = "registration", *,
    creation: bool = False, **kwargs: Any
) -> PartialRegistration:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        # creation does not allow fields for sake of simplicity
        mandatory_fields = dict(_PARTIAL_REGISTRATION_COMMON_FIELDS(),
                                persona_id=ID)
        optional_fields = _PARTIAL_REGISTRATION_OPTIONAL_FIELDS()
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {}
        optional_fields = dict(
            _PARTIAL_REGISTRATION_COMMON_FIELDS(),
            **_PARTIAL_REGISTRATION_OPTIONAL_FIELDS())

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'amount_owed' in val:
        del val['amount_owed']
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            try:
                anid = _id(anid, 'parts', **kwargs)
                part = _partial_registration_part(part, 'parts', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newparts[anid] = part
        val['parts'] = newparts
    if 'tracks' in val:
        newtracks = {}
        for anid, track in val['tracks'].items():
            try:
                anid = _id(anid, 'tracks', **kwargs)
                track = _partial_registration_track(track, 'tracks', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newtracks[anid] = track
        val['tracks'] = newtracks

    if errs:
        raise errs

    # the check of fields is delegated to _event_associated_fields
    return PartialRegistration(val)


@_add_typed_validator
def _partial_registration_part(
    val: Any, argname: str = "partial_registration_part", **kwargs: Any
) -> PartialRegistrationPart:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields = {
        'status': _enum_registrationpartstati,  # type: ignore
        'lodgement_id': Optional[PartialImportID],
        'is_camping_mat': bool,
    }

    return PartialRegistrationPart(_examine_dictionary_fields(
        val, {}, optional_fields, **kwargs))


@_add_typed_validator
def _partial_registration_track(
    val: Any, argname: str = "partial_registration_track", **kwargs: Any
) -> PartialRegistrationTrack:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields = {
        'course_id': Optional[PartialImportID],
        'course_instructor': Optional[PartialImportID],
        'choices': Iterable,
    }

    val = _examine_dictionary_fields(val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'choices' in val:
        newchoices = []
        for choice in val['choices']:
            try:
                # TODO why not use partial id validator above?
                choice = _partial_import_id(choice, 'choices', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                break  # TODO why break and not continues? - directly raise?
            else:
                newchoices.append(choice)
        val['choices'] = newchoices

    if errs:
        raise errs

    return PartialRegistrationTrack(val)


def _MAILINGLIST_COMMON_FIELDS(): return {
    'title': str,
    'local_part': EmailLocalPart,
    'domain': _enum_mailinglistdomain,  # type: ignore
    'description': Optional[str],
    'mod_policy': _enum_moderationpolicy,  # type: ignore
    'attachment_policy': _enum_attachmentpolicy,  # type: ignore
    'ml_type': _enum_mailinglisttypes,  # type: ignore
    'subject_prefix': Optional[str],
    'maxsize': Optional[ID],
    'is_active': bool,
    'notes': Optional[str],
}


def _MAILINGLIST_OPTIONAL_FIELDS(): return {
    'assembly_id': NoneType,
    'event_id': NoneType,
    'registration_stati': EmptyList,
}


_MAILINGLIST_READONLY_FIELDS = {
    'address',
    'domain_str',
    'ml_type_class',
}


@_add_typed_validator
def _mailinglist(
    val: Any, argname: str = "mailinglist", *,
    creation: bool = False, _allow_readonly: bool = False, **kwargs: Any
) -> Mailinglist:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    # TODO replace these with generic types
    mandatory_validation_fields = [('moderators', '[id]'), ]
    optional_validation_fields = [('whitelist', '[email]'), ]
    if "ml_type" not in val:
        raise ValidationSummary(ValueError("ml_type",
                                           "Must provide ml_type for setting mailinglist."))
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
        val = dict(copy.deepcopy(val))
        for key in _MAILINGLIST_READONLY_FIELDS:
            if key in val:
                del val[key]

    if creation:
        pass
    else:
        # The order is important here, so that mandatory fields take
        # precedence.
        optional_fields = dict(optional_fields, **mandatory_fields)
        mandatory_fields = {'id': ID}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if val and "moderators" in val and len(val["moderators"]) == 0:
        # TODO is this legitimate (postpone after other errors?)
        raise ValidationSummary(ValueError(
            "moderators", n_("Must not be empty.")))

    errs = ValidationSummary()
    for key, validator_str in iterable_fields:
        validator = getattr(current_module, validator_str)
        newarray = []
        if key in val:
            for x in val[key]:
                try:
                    v = validator(x, argname=key, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newarray.append(v)
            val[key] = newarray

    if "domain" in val:
        if "ml_type" not in val:
            errs.append(ValueError("domain", n_(
                "Must specify mailinglist type to change domain.")))
        else:
            atype = ml_type.get_type(val["ml_type"])
            if val["domain"].value not in atype.domains:
                errs.append(ValueError("domain", n_(
                    "Invalid domain for this mailinglist type.")))

    if errs:
        raise errs

    return Mailinglist(val)


_SUBSCRIPTION_ID_FIELDS: TypeMapping = {
    'mailinglist_id': ID,
    'persona_id': ID,
}


def _SUBSCRIPTION_STATE_FIELDS(): return {
    'subscription_state': _enum_subscriptionstates,  # type: ignore
}


_SUBSCRIPTION_ADDRESS_FIELDS = {
    'address': Email,
}

# TODO the enum does not exist anymore?


def _SUBSCRIPTION_REQUEST_RESOLUTION_FIELDS(): return {
    'resolution': _enum_subscriptionrequestresolutions,  # type: ignore
}


# TODO argname with space?
@_add_typed_validator
def _subscription_identifier(
    val: Any, argname: str = "subscription identifier", **kwargs: Any
) -> SubscriptionIdentifier:
    val = _mapping(val, argname, **kwargs)

    # TODO why is deepcopy mandatory?
    # TODO maybe make signature of examine dict to take a non-mutable mapping?
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)

    return SubscriptionIdentifier(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_state(
    val: Any, argname: str = "subscription state", **kwargs: Any
) -> SubscriptionState:
    val = _mapping(val, argname, **kwargs)

    # TODO instead of deepcopy simply do not mutate mandatory_fields
    # TODO or use function returning the dict everywhere instead
    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_STATE_FIELDS())

    return SubscriptionState(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_address(
    val: Any, argname: str = "subscription address", **kwargs: Any
) -> SubscriptionAddress:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_ADDRESS_FIELDS)

    return SubscriptionAddress(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_request_resolution(
    val: Any, argname: str = "subscription request resolution", **kwargs: Any
) -> SubscriptionRequestResolution:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = copy.deepcopy(_SUBSCRIPTION_ID_FIELDS)
    mandatory_fields.update(_SUBSCRIPTION_REQUEST_RESOLUTION_FIELDS())

    return SubscriptionRequestResolution(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


def _ASSEMBLY_COMMON_FIELDS(): return {
    'title': str,
    'description': Optional[str],
    'signup_end': datetime.datetime,
    'notes': Optional[str],
}


def _ASSEMBLY_OPTIONAL_FIELDS(): return {
    'is_active': bool,
    'mail_address': Optional[str],
    'presiders': Iterable
}


@_add_typed_validator
def _assembly(
    val: Any, argname: str = "assembly", *,
    creation: bool = False, **kwargs: Any
) -> Assembly:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = dict(_mapping(val, argname, **kwargs))

    if creation:
        mandatory_fields = _ASSEMBLY_COMMON_FIELDS()
        optional_fields = _ASSEMBLY_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_ASSEMBLY_COMMON_FIELDS(),
                               **_ASSEMBLY_OPTIONAL_FIELDS())

    errs = ValidationSummary()

    if 'presiders' in val:
        presiders = set()
        for anid in val['presiders']:
            try:
                presider = _id(anid, 'presiders', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                presiders.add(presider)
        val['presiders'] = presiders

    if errs:
        raise errs

    return Assembly(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


def _BALLOT_COMMON_FIELDS(): return {
    'title': str,
    'description': Optional[str],
    'vote_begin': datetime.datetime,
    'vote_end': datetime.datetime,
    'notes': Optional[str],
}


def _BALLOT_OPTIONAL_FIELDS(): return {
    'extended': Optional[bool],
    'vote_extension_end': Optional[datetime.datetime],
    'quorum': int,
    'votes': Optional[int],
    'use_bar': bool,
    'is_tallied': bool,
    'candidates': Mapping
}


@_add_typed_validator
def _ballot(
    val: Any, argname: str = "ballot", *,
    creation: bool = False, **kwargs: Any
) -> Ballot:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_BALLOT_COMMON_FIELDS(), assembly_id=ID)
        optional_fields = _BALLOT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(_BALLOT_COMMON_FIELDS(),
                               **_BALLOT_OPTIONAL_FIELDS())

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    # TODO why are all these nested?
    if 'vote_begin' in val:
        if val['vote_begin'] <= now():
            errs.append(ValueError(
                "vote_begin", n_("Mustn’t be in the past.")))
        if 'vote_end' in val:
            if val['vote_end'] <= val['vote_begin']:
                errs.append(ValueError("vote_end", n_(
                    "Mustn’t be before start of voting period.")))
            if 'vote_extension_end' in val and val['vote_extension_end']:
                if val['vote_extension_end'] <= val['vote_end']:
                    errs.append(ValueError("vote_extension_end", n_(
                        "Mustn’t be before end of voting period.")))

    if 'candidates' in val:
        newcandidates = {}
        for anid, candidate in val['candidates'].items():
            try:
                anid = _int(anid, 'candidates', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                creation = (anid < 0)
                try:
                    candidate = _ballot_candidate_or_None(  # type: ignore
                        candidate, 'candidates', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newcandidates[anid] = candidate
        val['candidates'] = newcandidates

    if ('quorum' in val) != ('vote_extension_end' in val):
        errs.extend([
            ValueError("vote_extension_end", n_(
                "Must be specified if quorum is given.")),
            ValueError("quorum", n_(
                "Must be specified if vote extension end is given."))
        ])

    if 'quorum' in val and 'vote_extension_end' in val:
        if not ((val['quorum'] != 0 and val['vote_extension_end'] is not None)
                or (val['quorum'] == 0 and val['vote_extension_end'] is None)):
            errs.extend([
                ValueError("vote_extension_end", n_(
                    "Inconsitent with quorum.")),
                ValueError("quorum", n_(
                    "Inconsitent with vote extension end."))
            ])

    if errs:
        raise errs

    return Ballot(val)


_BALLOT_CANDIDATE_COMMON_FIELDS = {
    'title': str,
    'shortname': Identifier,
}


@_add_typed_validator
def _ballot_candidate(
    val: Any, argname: str = "ballot_candidate", *,
    creation: bool = False, **kwargs: Any
) -> BallotCandidate:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _BALLOT_CANDIDATE_COMMON_FIELDS
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = _BALLOT_CANDIDATE_COMMON_FIELDS

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if val.get('shortname') == ASSEMBLY_BAR_SHORTNAME:
        raise ValidationSummary(ValueError(
            "shortname", n_("Mustn’t be the bar shortname.")))

    return BallotCandidate(val)


def _ASSEMBLY_ATTACHMENT_FIELDS(): return {
    'assembly_id': Optional[ID],
    'ballot_id': Optional[ID],
}


def _ASSEMBLY_ATTACHMENT_VERSION_FIELDS(): return {
    'title': str,
    'authors': Optional[str],
    'filename': str,
}


@_add_typed_validator
def _assembly_attachment(
    val: Any, argname: str = "assembly_attachment", *,
    creation: bool = False, **kwargs: Any
) -> AssemblyAttachment:
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = _ASSEMBLY_ATTACHMENT_VERSION_FIELDS()
        optional_fields = _ASSEMBLY_ATTACHMENT_FIELDS()
    else:
        mandatory_fields = dict(_ASSEMBLY_ATTACHMENT_FIELDS(), id=ID)
        optional_fields = {}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if val.get("assembly_id") and val.get("ballot_id"):
        errs.append(ValueError(argname, n_("Only one host allowed.")))
    if not val.get("assembly_id") and not val.get("ballot_id"):
        errs.append(ValueError(argname, n_("No host given.")))

    if errs:
        raise errs

    return AssemblyAttachment(val)


@_add_typed_validator
def _assembly_attachment_version(
    val: Any, argname: str = "assembly_attachment_version", *,
    creation: bool = False, **kwargs: Any
) -> AssemblyAttachmentVersion:
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(_ASSEMBLY_ATTACHMENT_VERSION_FIELDS(),
                                attachment_id=ID)
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'attachment_id': ID, 'version': ID}
        optional_fields = _ASSEMBLY_ATTACHMENT_VERSION_FIELDS()

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    return AssemblyAttachmentVersion(val)


# TODO replace ballot with CdEDBObject
@_add_typed_validator
def _vote(
    val: Any, argname: str = "vote",
    ballot: Mapping[str, Any] = None, **kwargs: Any
) -> Vote:
    """Validate a single voters intent.

    This is mostly made complicated by the fact that we offer to emulate
    ordinary voting instead of full preference voting.

    :param ballot: Ballot the vote was cast for.
    """
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()
    if not ballot:
        errs.append(RuntimeError(
            n_("Must specify ballot in order to validate vote.")))
        raise errs

    entries = tuple(y for x in val.split('>') for y in x.split('='))
    reference = set(e['shortname'] for e in ballot['candidates'].values())
    if ballot['use_bar'] or ballot['votes']:
        reference.add(ASSEMBLY_BAR_SHORTNAME)
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
        if (ASSEMBLY_BAR_SHORTNAME in first_group
                and first_group != [ASSEMBLY_BAR_SHORTNAME]):
            errs.append(ValueError(argname, n_("Misplaced bar.")))
        if errs:
            raise errs

    return Vote(val)


# TODO move above
@_add_typed_validator
def _regex(
    val: Any, argname: str = None, **kwargs: Any
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
    val: Any, argname: str = None, **kwargs: Any
) -> NonRegex:
    val = _str(val, argname, **kwargs)
    forbidden_chars = r'\*+?{}()[]|'
    msg = n_(r"Must not contain any forbidden characters"
             f" (which are {forbidden_chars} while .^$ are allowed).")
    if any(char in val for char in forbidden_chars):
        raise ValidationSummary(ValueError(argname, msg))
    return NonRegex(val)


@_add_typed_validator
def _query_input(
    val: Any, argname: str = None, *,
    spec: Mapping[str, str], allow_empty: bool = False,
    separator: str = ',', escape: str = '\\',
    **kwargs: Any
) -> QueryInput:
    """This is for the queries coming from the web.

    It is not usable with decorators since the spec is often only known at
    runtime. To alleviate this circumstance there is the
    :py:func:`cdedb.query.mangle_query_input` function to take care of the
    things the decorators normally do.

    This has to be careful to treat checkboxes and selects correctly
    (which are partly handled by an absence of data).

    :param spec: a query spec from :py:mod:`cdedb.query`
    :param allow_empty: Toggles whether no selected output fields is an error.
    :param separator: Defines separator for multi-value-inputs.
    :param escape: Defines escape character so that the input may contain a
      separator for multi-value-inputs.
    """

    val = _mapping(val, argname, **kwargs)

    fields_of_interest = []
    constraints = []
    order = []
    errs = ValidationSummary()
    for field, validator in spec.items():
        # First the selection of fields of interest
        try:
            selected = _bool(val.get("qsel_{}".format(
                field), "False"), field, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            selected = False
            # TODO why not continue/break here?

        if selected:
            fields_of_interest.append(field)

        # Second the constraints (filters)
        # Get operator
        try:
            operator = _enum_queryoperators_or_None(  # type: ignore
                val.get("qop_{}".format(field)), field, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if not operator:
            continue

        if operator not in VALID_QUERY_OPERATORS[validator]:
            errs.append(ValueError(
                field, n_("Invalid operator for this field.")))
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
                # TODO do not allow None/falsy
                try:
                    vv = getattr(current_module, "_{}_or_None".format(
                        validator))(v, field, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                    continue

                if operator in (QueryOperators.containsall,
                                QueryOperators.containssome,
                                QueryOperators.containsnone):
                    try:
                        vv = _non_regex(vv, field, **kwargs)
                    except ValidationSummary as e:
                        errs.extend(e)
                        continue

                assert vv  # TODO check this (i.e. the above todos)
                value.append(vv)

            if not value:
                continue

            if (operator in (QueryOperators.between, QueryOperators.outside)
                    and len(value) != 2):
                errs.append(ValueError(field, n_("Two endpoints required.")))
                continue

        elif operator in (QueryOperators.match, QueryOperators.unmatch):
            # TODO remove all _or_None in this validator!
            try:
                value = _non_regex_or_None(  # type: ignore
                    value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        elif operator in (QueryOperators.regex, QueryOperators.notregex):
            try:
                value = _regex_or_None(value, field, **kwargs)  # type: ignore
            except ValidationSummary as e:
                errs.extend(e)
                continue
        else:
            try:
                value = getattr(current_module, "_{}_or_None".format(
                    validator))(value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue

        if value is not None:
            constraints.append((field, operator, value))
        else:
            pass  # TODO raise error here?

    if not fields_of_interest and not allow_empty:
        errs.append(ValueError(argname, n_("Selection may not be empty.")))

    # Third the ordering
    for postfix in ("primary", "secondary", "tertiary"):
        if "qord_" + postfix not in val:
            continue

        try:
            value = _csv_identifier_or_None(  # type: ignore
                val["qord_" + postfix], "qord_" + postfix, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if not value:
            continue

        tmp = "qord_" + postfix + "_ascending"
        try:
            ascending = _bool(val.get(tmp, "True"), tmp, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        order.append((value, ascending))

    if errs:
        raise errs

    return QueryInput(
        Query(None, spec, fields_of_interest, constraints, order))  # type: ignore


# TODO ignore _ignore_warnings here too?
@_add_typed_validator
def _query(
    val: Any, argname: str = None, **kwargs: Any
) -> Query:
    """Check query object for consistency.

    This is a tad weird, since the specification against which we check
    is also provided by the query object. If we use an actual RPC
    mechanism queries must be serialized and this gets more interesting.
    """

    if not isinstance(val, Query):
        raise ValidationSummary(TypeError(argname, n_("Not a Query.")))

    errs = ValidationSummary()

    # scope
    # TODO why no convert here?
    _identifier(val.scope, "scope", **{**kwargs, '_convert': False})

    if not val.scope.startswith("qview_"):
        errs.append(ValueError("scope", n_("Must start with “qview_”.")))

    # spec
    for field, validator in val.spec.items():
        try:
            _csv_identifier(field, "spec", **{**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)

        try:
            _printable_ascii(validator, "spec", **
                             {**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)

    # fields_of_interest
    for field in val.fields_of_interest:
        try:
            _csv_identifier(field, "fields_of_interest", **
                            {**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)
    if not val.fields_of_interest:
        errs.append(ValueError("fields_of_interest", n_("Must not be empty.")))

    # constraints
    for idx, x in enumerate(val.constraints):
        try:
            field, operator, value = x
        except ValueError:
            msg = n_("Invalid constraint number %(index)s")
            errs.append(ValueError("constraints", msg, {"index": idx}))
            continue

        try:
            field = _csv_identifier(
                field, "constraints", **{**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)

        if field not in val.spec:
            errs.append(KeyError("constraints", n_("Invalid field.")))
            continue

        try:
            operator = _enum_queryoperators(  # type: ignore
                operator, "constraints/{}".format(field), **{**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if operator not in VALID_QUERY_OPERATORS[val.spec[field]]:
            errs.append(ValueError("constraints/{}".format(field),
                                   n_("Invalid operator.")))
            continue

        if operator in NO_VALUE_OPERATORS:
            value = None

        elif operator in MULTI_VALUE_OPERATORS:
            validator = getattr(current_module, "_{}".format(val.spec[field]))
            for v in value:
                try:
                    validator(v, "constraints/{}".format(field),
                              **{**kwargs, '_convert': False})
                except ValidationSummary as e:
                    errs.extend(e)
        else:
            try:
                getattr(current_module, "_{}".format(val.spec[field]))(
                    value, "constraints/{}".format(field), **{**kwargs, '_convert': False})
            except ValidationSummary as e:
                errs.extend(e)

    # order
    for idx, entry in enumerate(val.order):
        try:
            entry = _iterable(  # type: ignore
                entry, 'order', **{**kwargs, '_convert': False})
        except ValidationSummary as e:
            errs.extend(e)
            continue

        try:
            field, ascending = entry
        except ValueError:
            msg = n_("Invalid ordering condition number %(index)s")
            errs.append(ValueError("order", msg, {'index': idx}))
        else:
            try:
                _csv_identifier(field, "order", **
                                {**kwargs, '_convert': False})
                _bool(ascending, "order", **{**kwargs, '_convert': False})
            except ValidationSummary as e:
                errs.extend(e)

    if errs:
        raise errs

    # TODO why deepcopy?
    return copy.deepcopy(val)


E = TypeVar('E', bound=Enum)


def _enum_validator_maker(
    anenum: Type[E], name: str = None, internal: bool = False
) -> Callable[..., E]:
    """Automate validator creation for enums.

    Since this is pretty generic we do this all in one go.

    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    :param internal: If True the validator is not added to the module.
    """
    error_msg = n_("Invalid input for the enumeration %(enum)s")

    def the_validator(
        val: Any, argname: str = None, *,
        _convert: bool = True, **kwargs: Any
    ) -> E:
        if _convert and not isinstance(val, anenum):
            val = _int(val, argname=argname, _convert=_convert, **kwargs)

        if not isinstance(val, anenum):
            if isinstance(val, int):
                try:
                    val = anenum(val)
                except ValueError as e:
                    raise ValidationSummary(ValueError(
                        argname, error_msg, {'enum': anenum})) from e
            else:
                raise ValidationSummary(TypeError(
                    argname, n_("Must be a %(type)s."), {'type': anenum}))

        return val

    the_validator.__name__ = name or "_enum_{}".format(anenum.__name__.lower())

    if not internal:
        _add_typed_validator(the_validator, anenum)
        setattr(current_module, the_validator.__name__, the_validator)

    return the_validator


for oneenum in ALL_ENUMS:
    _enum_validator_maker(oneenum)


def _infinite_enum_validator_maker(anenum: Type[E], name: str = None) -> None:
    """Automate validator creation for infinity enums.

    Since this is pretty generic we do this all in one go.

    For further information about infinite enums see
    :py:func:`cdedb.common.infinite_enum`.

    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    """
    raw_validator = _enum_validator_maker(anenum, internal=True)
    error_msg = n_("Invalid input for the enumeration %(enum)s")

    def the_validator(
        val: Any, argname: str = None, *,
        _convert: bool = True, **kwargs: Any
    ) -> E:
        val_int: Optional[int]

        if isinstance(val, InfiniteEnum):
            val_enum = raw_validator(
                val.enum, argname=argname, _convert=_convert, **kwargs)

            if val.enum.value == INFINITE_ENUM_MAGIC_NUMBER:
                val_int = _non_negative_int(
                    val.int, argname=argname, _convert=_convert, **kwargs)
            else:
                val_int = None

        else:
            if _convert:
                val = _int(val, argname=argname, _convert=_convert, **kwargs)

                val_int = None
                if val < 0:
                    try:
                        val_enum = anenum(val)
                    except ValueError as e:
                        raise ValidationSummary(
                            ValueError(argname, error_msg, {'enum': anenum})) from e
                else:
                    val_enum = anenum(INFINITE_ENUM_MAGIC_NUMBER)
                    val_int = val
            else:
                raise ValidationSummary(TypeError(argname, n_(
                    "Must be a %(type)s."), {'type': anenum}))

        return InfiniteEnum(val_enum, val_int)  # type: ignore

    the_validator.__name__ = name or "_infinite_enum_{}".format(
        anenum.__name__.lower())
    _add_typed_validator(the_validator, anenum)
    setattr(current_module, the_validator.__name__, the_validator)


for oneenum in ALL_INFINITE_ENUMS:
    _infinite_enum_validator_maker(oneenum)


#
# Above is the real stuff
#

_create_validators(_ALL_TYPED.values())
