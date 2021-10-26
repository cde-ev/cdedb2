# TODO using doctest may be nice for the atomic validators
# TODO split in multiple files?
# TODO do not use underscore for protection but instead specify __all__
# TODO why sometimes function and sometimes .copy() for field templates?

"""User data input mangling.

We provide a set of functions testing arbitrary user provided data for
fitness. Those functions returning a mangled value also convert to more
appropriate python types (most input is given as strings which are
converted to e.g. :py:class:`datetime.datetime`).

We offer two variants:

* ``validate_check`` return a tuple ``(mangled_value, errors)``.
* ``validate_affirm`` on success return the mangled value,
    but if there is an error raise an exception.

The raw validator implementations are functions with signature
``(val, argname, **kwargs)`` of which many support the keyword arguments
``ignore_warnings``.
These functions are registered and than wrapped to generate the above variants.

They return the the validated and converted value
and raise a ``ValidationSummary`` when encountering errors.
Each exception summary contains a list of errors
which store the ``argname`` of the validator where the error occurred
as well as an explanation of what exactly is wrong.
A ``ValueError`` may also store a third argument.
This optional argument should be a ``Mapping[str, Any]``
describing substitutions of the error string to be done by i18n.

Validators may try to convert the value into the appropriate type.
For instance ``_int`` will try to convert the input into an int
which would be useful for string inputs especially.

The parameter ``ignore_warnings`` is present in some validators.
If ``True``, Errors of type ``ValidationWarning`` may be ignored instead of raised.
Think of this like a toggle to enable less strict validation of some constants
which might change externally like german postal codes.

Following a model of encapsulation, the entry points of the validation facillity
``validate_check`` and ``validation_assert`` should never be called directly.
Instead, we provide some convenient wrappers around them for frontend and backend:

* ``check_validation`` wraps ``validate_check`` in frontend.common
* ``affirm_validation`` wraps ``validation_assert`` in backend.common
* ``inspect_validation`` wraps ``validate_check`` in frontend.common and backend.common

Note that some of this functions may do some additional work,
f.e. ``check_validation`` registers all errors in the RequestState object.
"""

import copy
import distutils.util
import functools
import io
import itertools
import json
import logging
import math
import re
import string
import typing
from enum import Enum
from typing import (
    Callable, Iterable, Mapping, Optional, Protocol, Sequence, Set, Tuple, TypeVar,
    Union, cast, get_args, get_origin, get_type_hints, overload,
)

import magic
import phonenumbers
import PIL.Image
import pytz
import pytz.tzinfo
import werkzeug.datastructures
import zxcvbn

import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
from cdedb.common import (
    ASSEMBLY_BAR_SHORTNAME, EPSILON, EVENT_SCHEMA_VERSION, INFINITE_ENUM_MAGIC_NUMBER,
    REALM_SPECIFIC_GENESIS_FIELDS, CdEDBObjectMap, Error, InfiniteEnum, LineResolutions,
    ValidationWarning, asciificator, compute_checkdigit, extract_roles, n_, now,
    xsorted,
)
from cdedb.config import BasicConfig, Config
from cdedb.database.constants import FieldAssociations, FieldDatatypes
from cdedb.enums import ALL_ENUMS, ALL_INFINITE_ENUMS
from cdedb.query import (
    MULTI_VALUE_OPERATORS, NO_VALUE_OPERATORS, VALID_QUERY_OPERATORS, QueryOperators,
    QueryOrder, QueryScope,
)
from cdedb.validationdata import (
    COUNTRY_CODES, FREQUENCY_LISTS, GERMAN_POSTAL_CODES, IBAN_LENGTHS,
)
from cdedb.validationtypes import *  # pylint: disable=wildcard-import,unused-wildcard-import; # noqa: F403

_BASICCONF = BasicConfig()
_CONF = Config()
NoneType = type(None)

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)

T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


class ValidationSummary(ValueError, Sequence[Exception]):
    args: Tuple[Exception, ...]

    def __len__(self) -> int:
        return len(self.args)

    @overload
    def __getitem__(self, index: int) -> Exception: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Exception]: ...

    def __getitem__(
        self, index: Union[int, slice]
    ) -> Union[Exception, Sequence[Exception]]:
        return self.args[index]

    def extend(self, errors: Iterable[Exception]) -> None:
        self.args = self.args + tuple(errors)

    def append(self, error: Exception) -> None:
        self.args = self.args + (error,)


class ValidatorStorage(Dict[Type[Any], Callable[..., Any]]):
    def __setitem__(self, type_: Type[T], validator: Callable[..., T]) -> None:
        super().__setitem__(type_, validator)

    def __getitem__(self, type_: Type[T]) -> Callable[..., T]:
        if typing.get_origin(type_) is Union:
            inner_type, none_type = typing.get_args(type_)
            if none_type is not NoneType:
                raise KeyError("Complex unions not supported")
            validator = self[inner_type]
            return _allow_None(validator)  # type: ignore
        elif typing.get_origin(type_) is list:
            [inner_type] = typing.get_args(type_)
            return make_list_validator(inner_type)  # type: ignore
        # TODO more container types like tuple
        return super().__getitem__(type_)


_ALL_TYPED = ValidatorStorage()


def validate_assert(type_: Type[T], value: Any, ignore_warnings: bool,
                    **kwargs: Any) -> T:
    """Check if value is of type type_ – otherwise, raise an error.

    This should be used mostly in backend functions to check whether an input is
    appropriate.

    Note that this needs an explicit information whether warnings shall be ignored or
    not.
    """
    if "ignore_warnings" in kwargs:
        raise RuntimeError("Not allowed to set 'ignore_warnings' toggle.")
    try:
        return _ALL_TYPED[type_](value, ignore_warnings=ignore_warnings, **kwargs)
    except ValidationSummary as errs:
        old_format = [(e.args[0], e.__class__(*e.args[1:])) for e in errs]
        _LOGGER.debug(
            f"{old_format} for '{str(type_)}'"
            f" with input {value}, {kwargs}."
        )
        e = errs[0]
        e.args = ("{} ({})".format(e.args[1], e.args[0]),) + e.args[2:]
        raise e from errs  # pylint: disable=raising-bad-type


def validate_assert_optional(type_: Type[T], value: Any, ignore_warnings: bool,
                             **kwargs: Any) -> Optional[T]:
    """Wrapper to avoid a lot of type-ignore statements due to a mypy bug."""
    return validate_assert(Optional[type_], value, ignore_warnings, **kwargs)  # type: ignore


def validate_check(type_: Type[T], value: Any, ignore_warnings: bool,
                   field_prefix: str = "", field_postfix: str = "", **kwargs: Any
                   ) -> Tuple[Optional[T], List[Error]]:
    """Checks if value is of type type_.

    This is mostly used in the frontend to check if the given input is valid. To display
    validation errors for fields which name differs from the name of the attribute of
    the given value, one can specify a field_prefix and -postfix which will be appended
    at the field name. This is especially useful for 'process_dynamic_input'.

    Note that this needs an explicit information whether warnings shall be ignored or
    not.
    """
    if "ignore_warnings" in kwargs:
        raise RuntimeError("Not allowed to set 'ignore_warnings' as kwarg.")
    try:
        val = _ALL_TYPED[type_](value, ignore_warnings=ignore_warnings, **kwargs)
        return val, []
    except ValidationSummary as errs:
        old_format = [
            (
                (field_prefix + (e.args[0] or "") + field_postfix) or None,
                e.__class__(*e.args[1:])
            ) for e in errs
        ]
        _LOGGER.debug(
            f"{old_format} for '{str(type_)}'"
            f" with input {value}, {kwargs}."
        )
        return None, old_format


def validate_check_optional(
    type_: Type[T], value: Any, ignore_warnings: bool, **kwargs: Any
) -> Tuple[Optional[T], List[Error]]:
    """Wrapper to avoid a lot of type-ignore statements due to a mypy bug."""
    return validate_check(Optional[type_], value, ignore_warnings, **kwargs)  # type: ignore


def is_optional(type_: Type[T]) -> bool:
    return get_origin(type_) is Union and NoneType in get_args(type_)


def get_errors(errors: List[Error]) -> List[Error]:
    """Returns those errors which are not considered as warnings."""
    def is_error(e: Error) -> bool:
        _, exception = e
        return not isinstance(exception, ValidationWarning)
    return list(filter(is_error, errors))


def get_warnings(errors: List[Error]) -> List[Error]:
    """Returns those errors which are considered as warnings."""
    def is_warning(e: Error) -> bool:
        _, exception = e
        return isinstance(exception, ValidationWarning)
    return list(filter(is_warning, errors))


def _allow_None(fun: Callable[..., T]) -> Callable[..., Optional[T]]:
    """Wrap a validator to allow ``None`` as valid input.

    This causes falsy values to be mapped to ``None`` if there is an error.
    """

    @functools.wraps(fun)
    def new_fun(val: Any, *args: Any, **kwargs: Any) -> Optional[T]:
        if val is None:
            return None
        else:
            try:
                return fun(val, *args, **kwargs)
            except ValidationSummary:  # we need to catch everything
                if not val:
                    return None
                else:
                    raise

    new_fun.__name__ += "_or_None"

    return new_fun


def _add_typed_validator(fun: F, return_type: Type[Any] = None) -> F:
    """Mark a typed function for processing into validators."""
    # TODO get rid of dynamic return types for enum
    if not return_type:
        return_type = get_type_hints(fun)["return"]
    assert return_type
    if return_type in _ALL_TYPED:
        raise RuntimeError(f"Type {return_type} already registered")
    _ALL_TYPED[return_type] = fun

    return fun


def _examine_dictionary_fields(
    adict: Mapping[str, Any],
    mandatory_fields: TypeMapping,
    optional_fields: TypeMapping = None,
    *,
    argname: str = "",
    allow_superfluous: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Check more complex dictionaries.

    :param adict: the dictionary to check
    :param mandatory_fields: mandatory fields to be checked for.
      It should map keys to registered types.
      A missing key is an error in itself.
    :param optional_fields: Like :py:obj:`mandatory_fields`, but facultative.
    :param argname: If given, prepend this to the argname of the individual validations.
        This is useful, if you want to examine multiple dicts and tell the errors apart.
    :param allow_superfluous: If ``False`` keys which are neither in
      :py:obj:`mandatory_fields` nor in :py:obj:`optional_fields` are errors.
    """
    optional_fields = optional_fields or {}
    errs = ValidationSummary()
    retval: Dict[str, Any] = {}
    for key, value in adict.items():
        sub_argname = argname + "." + key if argname else key
        if key in mandatory_fields:
            try:
                v = _ALL_TYPED[mandatory_fields[key]](
                    value, argname=sub_argname, **kwargs)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif key in optional_fields:
            try:
                v = _ALL_TYPED[optional_fields[key]](
                    value, argname=sub_argname, **kwargs)
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif not allow_superfluous:
            errs.append(KeyError(sub_argname, n_("Superfluous key found.")))

    missing_mandatory = set(mandatory_fields).difference(adict)
    if missing_mandatory:
        for key in missing_mandatory:
            sub_argname = argname + "." + key if argname else key
            errs.append(KeyError(sub_argname, n_("Mandatory key missing.")))

    if errs:
        raise errs

    return retval


def _augment_dict_validator(
    validator: Callable[..., Any],
    augmentation: TypeMapping,
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
                **{"allow_superfluous": True, **kwargs})  # type: ignore[arg-type]
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

        if v is not None:
            ret.update(v)

        if errs:
            raise errs

        return ret

    return new_validator


def escaped_split(string: str, delim: str, escape: str = '\\') -> List[str]:
    """Helper function for advanced list splitting.

    Split the list at every delimiter, except if it is escaped (and
    allow the escape char to be escaped itself).

    Based on http://stackoverflow.com/a/18092547
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


def filter_none(data: Dict[str, Any]) -> Dict[str, Any]:
    """Helper function to remove NoneType values from dictionaies."""
    return {k: v for k, v in data.items() if v is not NoneType}

#
# Below is the real stuff
#


@_add_typed_validator
def _None(
    val: Any, argname: str = None, **kwargs: Any
) -> None:
    """Force a None.

    This is mostly for ensuring proper population of dicts.
    """
    if isinstance(val, str) and not val:
        val = None
    if val is not None:
        raise ValidationSummary(ValueError(argname, n_("Must be empty.")))


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
    val: Any, argname: str = None, **kwargs: Any
) -> int:
    if isinstance(val, (str, bool)):
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
    if not -2 ** 31 <= val < 2 ** 31:
        # Our postgres columns only support 32-bit integers.
        raise ValidationSummary(ValueError(argname, n_("Integer too large.")))
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
    val: Any, argname: str = None, **kwargs: Any
) -> float:
    try:
        val = float(val)
    except (ValueError, TypeError) as e:
        raise ValidationSummary(ValueError(
            argname, n_("Invalid input for float."))) from e
    if not isinstance(val, float):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a floating point number.")))
    if abs(val) >= 1e7:
        # we are using numeric(8,2) columns in postgres
        # which only support numbers up to this size
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a million.")))
    return val


@_add_typed_validator
def _decimal(
    val: Any, argname: str = None, *,
    large: bool = False, **kwargs: Any
) -> decimal.Decimal:
    if isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise ValidationSummary(ValueError(argname, n_(
                "Invalid input for decimal number."))) from e
    if not isinstance(val, decimal.Decimal):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a decimal.Decimal.")))
    if not large and abs(val) >= 1e7:
        # we are using numeric(8,2) columns in postgres
        # which only support numbers up to this size
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a million.")))
    if abs(val) >= 1e10:
        # we are using numeric(11,2) columns in postgres for summation columns
        # which only support numbers up to this size
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a billion.")))
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
def _non_negative_large_decimal(
    val: Any, argname: str = None, **kwargs: Any
) -> NonNegativeLargeDecimal:
    return NonNegativeLargeDecimal(
        _non_negative_decimal(val, argname, large=True, **kwargs))


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
    zap: str = '', sieve: str = '', **kwargs: Any
) -> StringType:
    """
    :param zap: delete all characters in this from the result
    :param sieve: allow only the characters in this into the result
    """
    if val is not None:
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
def _shortname(val: Any, argname: str = None, *,
               ignore_warnings: bool = False, **kwargs: Any) -> Shortname:
    """A string used as shortname with therefore limited length."""
    val = _str(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    if len(val) > _CONF["SHORTNAME_LENGTH"] and not ignore_warnings:
        raise ValidationSummary(
            ValidationWarning(argname, n_("Shortname is longer than %(len)s chars."),
                              {'len': str(_CONF["SHORTNAME_LENGTH"])}))
    return Shortname(val)


@_add_typed_validator
def _shortname_identifier(val: Any, argname: str = None, *,
                          ignore_warnings: bool = False,
                          **kwargs: Any) -> ShortnameIdentifier:
    """A string used as shortname and as programmatically accessible identifier."""
    val = _identifier(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    val = _shortname(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    return ShortnameIdentifier(val)


@_add_typed_validator
def _shortname_restrictive_identifier(
        val: Any, argname: str = None, *,
        ignore_warnings: bool = False,
        **kwargs: Any) -> ShortnameRestrictiveIdentifier:
    """A string used as shortname and as restrictive identifier"""
    val = _restrictive_identifier(val, argname, ignore_warnings=ignore_warnings,
                                  **kwargs)
    val = _shortname_identifier(val, argname, ignore_warnings=ignore_warnings,
                                **kwargs)
    return ShortnameRestrictiveIdentifier(val)


@_add_typed_validator
def _legacy_shortname(val: Any, argname: str = None, *,
                      ignore_warnings: bool = False, **kwargs: Any) -> LegacyShortname:
    """A string used as shortname, but with increased but still limited length."""
    val = _str(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    if len(val) > _CONF["LEGACY_SHORTNAME_LENGTH"] and not ignore_warnings:
        raise ValidationSummary(
            ValidationWarning(argname, n_("Shortname is longer than %(len)s chars."),
                              {'len': str(_CONF["LEGACY_SHORTNAME_LENGTH"])}))
    return LegacyShortname(val)


@_add_typed_validator
def _bytes(
    val: Any, argname: str = None, *,
    encoding: str = "utf-8", **kwargs: Any
) -> bytes:
    if isinstance(val, str):
        if not encoding:
            raise RuntimeError("Not encoding specified to convert str to bytes.")
        val = val.encode(encoding=encoding)
    else:
        try:
            val = bytes(val)
        except ValueError as e:
            raise ValidationSummary(
                ValueError(argname, n_("Cannot convert {val_type} to bytes."),
                           {'val_type': str(type(val))})) from e
    if not isinstance(val, bytes):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a bytes object.")))
    return val


@_add_typed_validator
def _mapping(
    val: Any, argname: str = None, **kwargs: Any
) -> Mapping:  # type: ignore # type parameters would break this (for now)
    if not isinstance(val, Mapping):
        raise ValidationSummary(TypeError(argname, n_("Must be a mapping.")))
    return val


@_add_typed_validator
def _iterable(
    val: Any, argname: str = None, **kwargs: Any
) -> Iterable:  # type: ignore # type parameters would break this (for now)
    if not isinstance(val, Iterable):
        raise ValidationSummary(TypeError(argname, n_("Must be an iterable.")))
    return val


@_add_typed_validator
def _sequence(
    val: Any, argname: str = None, **kwargs: Any
) -> Sequence:  # type: ignore # type parameters would break this (for now)
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
    val: Any, argname: str = None, **kwargs: Any
) -> bool:
    if val is None:
        raise ValidationSummary(TypeError(argname, n_("Must be a boolean.")))

    try:
        return bool(distutils.util.strtobool(val))
    except (AttributeError, ValueError):
        try:
            return bool(val)
        except (ValueError, TypeError) as e:
            raise ValidationSummary(ValueError(argname, n_(
                "Invalid input for boolean."))) from e


@_add_typed_validator
def _empty_dict(
    val: Any, argname: str = None, **kwargs: Any
) -> EmptyDict:
    # TODO why do we not convert here but do so for _empty_list?
    if val != {}:
        raise ValidationSummary(
            ValueError(argname, n_("Must be an empty dict.")))
    return EmptyDict(val)


@_add_typed_validator
def _empty_list(
    val: Any, argname: str = None, **kwargs: Any
) -> EmptyList:
    val = list(_iterable(val, argname, **kwargs))
    if val:
        raise ValidationSummary(ValueError(argname, n_("Must be an empty list.")))
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
    if not match:
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
    if not re.search(r'^[ -~]*$', val):
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
    if not re.search(r'^[a-zA-Z0-9]+$', val):
        raise ValidationSummary(ValueError(
            argname, n_("Must be alphanumeric.")))
    return Alphanumeric(val)


@_add_typed_validator
def _csv_alphanumeric(
    val: Any, argname: str = None, **kwargs: Any
) -> CSVAlphanumeric:
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9]+(,[a-zA-Z0-9]+)*$', val):
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
    if not re.search(r'^[a-zA-Z0-9_.-]+$', val):
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
    if not re.search(r'^[a-zA-Z0-9_]+$', val):
        raise ValidationSummary(ValueError(argname, n_(
            "Must be a restrictive identifier (only letters,"
            " numbers and underscore).")))
    return RestrictiveIdentifier(val)


@_add_typed_validator
def _csv_identifier(
        val: Any, argname: str = None, **kwargs: Any
) -> CSVIdentifier:
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$', val):
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated identifiers.")))
    return CSVIdentifier(val)


# TODO manual handling of @_add_typed_validator inside decorator or storage?
@_add_typed_validator
def _list_of(
    val: Any, atype: Type[T],
    argname: str = None,
    *,
    _parse_csv: bool = False,
    _allow_empty: bool = True,
    **kwargs: Any,
) -> List[T]:
    """
    Apply another validator to all entries of of a list.

    The input may be a comma-separated string.
    """
    if isinstance(val, str) and _parse_csv:
        # TODO use default separator from config here?
        # TODO use escaped_split?
        # Skip emtpy entries which can be produced by JavaScript.
        val = [v for v in val.split(",") if v]
    val = _iterable(val, argname, **kwargs)
    vals: List[T] = []
    errs = ValidationSummary()
    for v in val:
        try:
            vals.append(_ALL_TYPED[atype](v, argname, **kwargs))
        except ValidationSummary as e:
            errs.extend(e)
    if errs:
        raise errs

    if not _allow_empty and not vals:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))

    return vals


class ListValidator(Protocol[T]):
    def __call__(self, val: Any, argname: str = None, **kargs: Any) -> List[T]:
        ...


def make_list_validator(type_: Type[T]) -> ListValidator[T]:

    @functools.wraps(_list_of)
    def list_validator(val: Any, argname: str = None, **kwargs: Any) -> List[T]:
        return _list_of(val, type_, argname, **kwargs)

    return list_validator


@_add_typed_validator
def _int_csv_list(
    val: Any, argname: str = None, **kwargs: Any
) -> IntCSVList:
    return IntCSVList(_list_of(val, int, argname, _parse_csv=True, **kwargs))


@_add_typed_validator
def _cdedbid_csv_list(
    val: Any, argname: str = None, **kwargs: Any
) -> CdedbIDList:
    """This deals with strings containing multiple cdedbids,
    like when they are returned from cdedbSearchPerson.
    """
    return CdedbIDList(_list_of(val, CdedbID, argname, _parse_csv=True, **kwargs))


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
    if not re.search(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$', val):
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
    if not re.search(r'^[a-z0-9._+-]+$', val):
        raise ValidationSummary(ValueError(
            argname, n_("Must be a valid email local part.")))
    return EmailLocalPart(val)


PERSONA_TYPE_FIELDS: TypeMapping = {
    'is_cde_realm': bool,
    'is_event_realm': bool,
    'is_ml_realm': bool,
    'is_assembly_realm': bool,
    'is_member': bool,
    'is_searchable': bool,
    'is_active': bool,
}

PERSONA_BASE_CREATION: Mapping[str, Any] = {
    'username': Email,
    'notes': Optional[str],
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

PERSONA_CDE_CREATION: Mapping[str, Any] = {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': const.Genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'postal_code2': Optional[PrintableASCII],
    'location2': Optional[str],
    'country2': Optional[Country],
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

PERSONA_EVENT_CREATION: Mapping[str, Any] = {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': const.Genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
}

PERSONA_FULL_ML_CREATION = {**PERSONA_BASE_CREATION}

PERSONA_FULL_ASSEMBLY_CREATION = {**PERSONA_BASE_CREATION}

PERSONA_FULL_EVENT_CREATION = {**PERSONA_BASE_CREATION, **PERSONA_EVENT_CREATION}

PERSONA_FULL_CDE_CREATION = {**PERSONA_BASE_CREATION, **PERSONA_CDE_CREATION,
                             'is_member': bool, 'is_searchable': bool}

PERSONA_COMMON_FIELDS: Mapping[str, Any] = {
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
    'is_purged': bool,
    'is_active': bool,
    'display_name': str,
    'given_names': str,
    'family_name': str,
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': const.Genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'postal_code2': Optional[PrintableASCII],
    'location2': Optional[str],
    'country2': Optional[Country],
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
            val, PERSONA_TYPE_FIELDS, {}, allow_superfluous=True, **kwargs)
        temp.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_purged': False,
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
        mandatory_fields: Dict[str, Any] = {**PERSONA_TYPE_FIELDS,
                                            **PERSONA_BASE_CREATION}
        if "cde" in roles:
            mandatory_fields.update(PERSONA_CDE_CREATION)
        if "event" in roles:
            mandatory_fields.update(PERSONA_EVENT_CREATION)
        # ml and assembly define no custom fields
    elif transition:
        realm_checks: Mapping[str, Mapping[str, Any]] = {
            'is_cde_realm': PERSONA_CDE_CREATION,
            'is_event_realm': PERSONA_EVENT_CREATION,
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
        optional_fields = PERSONA_COMMON_FIELDS
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    for suffix in ("", "2"):
        if val.get('postal_code' + suffix):
            try:
                postal_code = _german_postal_code(
                    val['postal_code' + suffix], 'postal_code' + suffix,
                    aux=val.get('country' + suffix, ""), **kwargs)
                val['postal_code' + suffix] = postal_code
            except ValidationSummary as e:
                errs.extend(e)
    if errs:
        raise errs

    return Persona(val)


@_add_typed_validator
def _batch_admission_entry(
    val: Any, argname: str = None, **kwargs: Any
) -> BatchAdmissionEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: Dict[str, Any] = {
        'resolution': LineResolutions,
        'doppelganger_id': Optional[int],
        'pevent_id': Optional[int],
        'pcourse_id': Optional[int],
        'is_instructor': bool,
        'is_orga': bool,
        'update_username': bool,
        'persona': Any,  # TODO This should be more strict
    }
    optional_fields: TypeMapping = {}
    return BatchAdmissionEntry(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


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
    val: Any, argname: str = None, **kwargs: Any
) -> datetime.date:
    if isinstance(val, str) and len(val.strip()) >= 6:
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
    if not val:
        val = datetime.date.min
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
        ret = datetime.datetime.fromisoformat(val)
    if ret.tzinfo is None:
        timezone: pytz.tzinfo.DstTzInfo = _BASICCONF["DEFAULT_TIMEZONE"]
        ret = timezone.localize(ret)
        assert ret is not None
    return ret.astimezone(pytz.utc)


@_add_typed_validator
def _datetime(
    val: Any, argname: str = None, *,
    default_date: datetime.date = None, **kwargs: Any
) -> datetime.datetime:
    """
    :param default_date: If the user-supplied value specifies only a time, this
      parameter allows to fill in the necessary date information to fill
      the gap.
    """
    if isinstance(val, str) and len(val.strip()) >= 5:
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
    val: Any, argname: str = None, *,  _ignore_warnings: bool = False, **kwargs: Any
) -> Phone:
    raw = _printable_ascii(val, argname, **kwargs, _ignore_warnings=_ignore_warnings)

    try:
        # default to german if no region is provided
        phone: phonenumbers.PhoneNumber = phonenumbers.parse(raw, region="DE")
    except phonenumbers.NumberParseException:
        msg = n_("Phone number can not be parsed.")
        raise ValidationSummary(ValueError(argname, msg))
    if not phonenumbers.is_valid_number(phone) and not _ignore_warnings:
        msg = n_("Phone number seems to be not valid.")
        raise ValidationSummary(ValidationWarning(argname, msg))

    # handle the phone number as normalized string internally
    phone_str = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)

    return phone_str


@_add_typed_validator
def _german_postal_code(
    val: Any, argname: str = None, *,
    aux: str = "", ignore_warnings: bool = False, **kwargs: Any
) -> GermanPostalCode:
    """
    :param aux: Additional information. In this case the country belonging
        to the postal code.
    :param ignore_warnings: If True, ignore invalid german postcodes.
    """
    val = _printable_ascii(
        val, argname, ignore_warnings=ignore_warnings, **kwargs)
    val = val.strip()
    if not aux or aux.strip() == "DE":
        msg = n_("Invalid german postal code.")
        if not (len(val) == 5 and val.isdigit()):
            raise ValidationSummary(ValueError(argname, msg))
        if val not in GERMAN_POSTAL_CODES and not ignore_warnings:
            raise ValidationSummary(ValidationWarning(argname, msg))
    return GermanPostalCode(val)


@_add_typed_validator
def _country(
    val: Any, argname: str = None, *, ignore_warnings: bool = False,
    **kwargs: Any
) -> Country:
    val = _ALL_TYPED[str](val, argname, ignore_warnings=ignore_warnings, **kwargs)
    # TODO be more strict and do not strip
    val = val.strip()
    if val not in COUNTRY_CODES:
        raise ValidationSummary(
            ValueError(argname, n_("Enter actual country name in English.")))
    return Country(val)


GENESIS_CASE_COMMON_FIELDS: TypeMapping = {
    'username': Email,
    'given_names': str,
    'family_name': str,
    'realm': str,
    'notes': str,
}

GENESIS_CASE_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'case_status': const.GenesisStati,
    'reviewer': ID,
    'pevent_id': Optional[ID],
    'pcourse_id': Optional[ID],
}

GENESIS_CASE_ADDITIONAL_FIELDS: Mapping[str, Any] = {
    'gender': const.Genders,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': str,
    'postal_code': Optional[PrintableASCII],
    'location': str,
    'country': Optional[Country],
    'birth_name': Optional[str],
    'attachment_hash': str,
}

GENESIS_CASE_EXPOSED_FIELDS = {**GENESIS_CASE_COMMON_FIELDS,
                               **GENESIS_CASE_ADDITIONAL_FIELDS,
                               'pevent_id': Optional[ID],
                               'pcourse_id': Optional[ID], }


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
                k: v for k, v in GENESIS_CASE_ADDITIONAL_FIELDS.items()
                if k in REALM_SPECIFIC_GENESIS_FIELDS[val['realm']]}
    else:
        raise ValidationSummary(ValueError(n_("Must specify realm.")))

    if creation:
        mandatory_fields = dict(GENESIS_CASE_COMMON_FIELDS,
                                **additional_fields)
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(GENESIS_CASE_COMMON_FIELDS,
                               **GENESIS_CASE_OPTIONAL_FIELDS,
                               **additional_fields)

    # allow_superflous=True will result in superfluous keys being removed.
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, allow_superfluous=True, **kwargs)

    if val.get('postal_code'):
        postal_code = _german_postal_code(
            val['postal_code'], 'postal_code', aux=val.get('country', ""), **kwargs)
        val['postal_code'] = postal_code

    return GenesisCase(val)


PRIVILEGE_CHANGE_COMMON_FIELDS: TypeMapping = {
    'persona_id': ID,
    'submitted_by': ID,
    'status': const.PrivilegeChangeStati,
    'notes': str,
}

PRIVILEGE_CHANGE_OPTIONAL_FIELDS: Mapping[str, Any] = {
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
        val, PRIVILEGE_CHANGE_COMMON_FIELDS,
        PRIVILEGE_CHANGE_OPTIONAL_FIELDS, **kwargs)

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
    Validate a CSV file.

    We default to 'utf-8-sig', since it behaves exactly like 'utf-8' if the
    file is 'utf-8' but it gets rid of the BOM if the file is 'utf-8-sig'.
    """
    val = _input_file(val, argname, **kwargs)
    mime = magic.from_buffer(val, mime=True)
    if mime not in ("text/csv", "text/plain", "application/csv"):
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
        `werkzeug.datastructures.FileStorage`, otherwise expect a `bytes`
        object.
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
        `werkzeug.datastructures.FileStorage`, otherwise expect a `bytes`
        object.
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

    # noinspection PyRedundantParentheses
    return (a, b)


@_add_typed_validator
def _period(
    val: Any, argname: str = "period", **kwargs: Any
) -> Period:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    prefix_map = {
        'billing': ('state', 'done', 'count'),
        'ejection': ('state', 'done', 'count', 'balance'),
        'balance': ('state', 'done', 'trialmembers', 'total'),
        'archival_notification': ('state', 'done', 'count'),
        'archival': ('state', 'done', 'count'),
    }
    type_map: TypeMapping = {
        'state': Optional[ID],  # type: ignore
        'done': datetime.datetime, 'count': NonNegativeInt,
        'trialmembers': NonNegativeInt, 'total': NonNegativeDecimal,
        'balance': NonNegativeDecimal,
    }

    optional_fields = {
        f"{pre}_{suf}": type_map[suf]
        for pre, suffixes in prefix_map.items() for suf in suffixes
    }

    return Period(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


@_add_typed_validator
def _expuls(
        val: Any, argname: str = "expuls", **kwargs: Any
) -> ExPuls:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    optional_fields: TypeMapping = {
        'addresscheck_state': Optional[ID],  # type: ignore
        'addresscheck_done': datetime.datetime,
        'addresscheck_count': NonNegativeInt,
    }
    return ExPuls(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


LASTSCHRIFT_COMMON_FIELDS: Mapping[str, Any] = {
    'amount': PositiveDecimal,
    'iban': IBAN,
    'account_owner': Optional[str],
    'account_address': Optional[str],
    'notes': Optional[str],
}

LASTSCHRIFT_OPTIONAL_FIELDS: Mapping[str, Any] = {
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
        mandatory_fields = dict(LASTSCHRIFT_COMMON_FIELDS, persona_id=ID)
        optional_fields = {**LASTSCHRIFT_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**LASTSCHRIFT_COMMON_FIELDS,
                           **LASTSCHRIFT_OPTIONAL_FIELDS}
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)
    return Lastschrift(val)


@_add_typed_validator
def _money_transfer_entry(val: Any, argname: str = "money_transfer_entry",
                       **kwargs: Any) -> MoneyTransferEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: Dict[str, Any] = {
        'persona_id': int,
        'amount': decimal.Decimal,
        'note': Optional[str],
    }
    optional_fields: TypeMapping = {}
    return MoneyTransferEntry(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


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


LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'amount': PositiveDecimal,
    'status': const.LastschriftTransactionStati,
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
        optional_fields = {**LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS}
    else:
        raise ValidationSummary(ValueError(argname, n_(
            "Modification of lastschrift transactions not supported.")))
    return LastschriftTransaction(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


@_add_typed_validator
def _lastschrift_transaction_entry(
        val: Any, argname: str = "lastschrift_transaction_entry",
        **kwargs: Any) -> LastschriftTransactionEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: Dict[str, Any] = {
        'transaction_id': int,
        'tally': Optional[decimal.Decimal],
        'status': const.LastschriftTransactionStati,
    }
    optional_fields: TypeMapping = {}
    return LastschriftTransactionEntry(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


SEPA_TRANSACTIONS_FIELDS: TypeMapping = {
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

SEPA_TRANSACTIONS_LIMITS: Mapping[str, int] = {
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

    mandatory_fields = {**SEPA_TRANSACTIONS_FIELDS}
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

        for attribute, validator in SEPA_TRANSACTIONS_FIELDS.items():
            if validator is _str:
                entry[attribute] = asciificator(entry[attribute])
            if attribute in SEPA_TRANSACTIONS_LIMITS:
                if len(entry[attribute]
                       ) > SEPA_TRANSACTIONS_LIMITS[attribute]:
                    errs.append(ValueError(attribute, n_("Too long.")))

        if entry['type'] not in ("OOFF", "FRST", "RCUR"):
            errs.append(ValueError('type', n_("Invalid constant.")))
        if errs:
            continue  # TODO is this not equivalent to break in this situation?
        ret.append(entry)

    if errs:
        raise errs

    return SepaTransactions(ret)


SEPA_META_FIELDS: TypeMapping = {
    'message_id': str,
    'total_sum': PositiveDecimal,
    'partial_sums': Mapping,
    'count': int,
    'sender': Mapping,
    'payment_date': datetime.date,
}

SEPA_SENDER_FIELDS: TypeMapping = {
    'name': str,
    'address': Iterable,
    'country': str,
    'iban': IBAN,
    'glaeubigerid': str,
}

SEPA_META_LIMITS: Mapping[str, int] = {
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

    mandatory_fields = {**SEPA_META_FIELDS}
    val = _examine_dictionary_fields(
        val, mandatory_fields, {}, **kwargs)

    mandatory_fields = {**SEPA_SENDER_FIELDS}
    val['sender'] = _examine_dictionary_fields(
        val['sender'], mandatory_fields, {}, **kwargs)

    errs = ValidationSummary()
    for attribute, validator in SEPA_META_FIELDS.items():
        if validator == str:
            val[attribute] = asciificator(val[attribute])
        if attribute in SEPA_META_LIMITS:
            if len(val[attribute]) > SEPA_META_LIMITS[attribute]:
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

    for attribute, validator in SEPA_SENDER_FIELDS.items():
        if validator is _str:
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
    allowed_chars = ".,-+()/"
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()

    forbidden_chars = "".join(xsorted({
        c for c in val  # pylint: disable=not-an-iterable
        if not (c.isalnum() or c.isspace() or c in allowed_chars)
    }))
    if forbidden_chars:
        errs.append(ValueError(argname, n_(
            "Forbidden characters (%(chars)s)."), {'chars': forbidden_chars}))
    if errs:
        raise errs

    return SafeStr(val)


@_add_typed_validator
def _meta_info(
    val: Any, keys: List[str], argname: str = "meta_info", **kwargs: Any
) -> MetaInfo:
    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        key: Optional[str]  # type: ignore
        for key in keys
    }
    val = _examine_dictionary_fields(
        val, {}, optional_fields, **kwargs)

    return MetaInfo(val)


INSTITUTION_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
}


@_add_typed_validator
def _institution(
    val: Any, argname: str = "institution", *,
    creation: bool = False, **kwargs: Any
) -> Institution:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = {**INSTITUTION_COMMON_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**INSTITUTION_COMMON_FIELDS}
    return Institution(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


PAST_EVENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'shortname': Shortname,
    'institution': ID,
    'tempus': datetime.date,
    'description': Optional[str],
}

PAST_EVENT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'participant_info': Optional[str],
}


PAST_EVENT_FIELDS = {**PAST_EVENT_COMMON_FIELDS, **PAST_EVENT_OPTIONAL_FIELDS}


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
        mandatory_fields = {**PAST_EVENT_COMMON_FIELDS}
        optional_fields = {**PAST_EVENT_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**PAST_EVENT_COMMON_FIELDS, **PAST_EVENT_OPTIONAL_FIELDS}
    return PastEvent(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


EVENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'institution': ID,
    'description': Optional[str],
    'shortname': ShortnameIdentifier,
}

EVENT_EXPOSED_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'is_visible': bool,
    'is_course_list_visible': bool,
    'is_course_state_visible': bool,
    'use_additional_questionnaire': bool,
    'registration_start': Optional[datetime.datetime],
    'registration_soft_limit': Optional[datetime.datetime],
    'registration_hard_limit': Optional[datetime.datetime],
    'notes': Optional[str],
    'is_participant_list_visible': bool,
    'is_course_assignment_visible': bool,
    'is_cancelled': bool,
    'iban': Optional[IBAN],
    'nonmember_surcharge': NonNegativeDecimal,
    'mail_text': Optional[str],
    'registration_text': Optional[str],
    'orga_address': Optional[Email],
    'participant_info': Optional[str],
    'lodge_field': Optional[ID],
    'camping_mat_field': Optional[ID],
    'course_room_field': Optional[ID],
}

EVENT_EXPOSED_FIELDS = {**EVENT_COMMON_FIELDS, **EVENT_EXPOSED_OPTIONAL_FIELDS}


EVENT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    **EVENT_EXPOSED_OPTIONAL_FIELDS,
    'offline_lock': bool,
    'is_archived': bool,
    'orgas': Iterable,
    'parts': Mapping,
    'fields': Mapping,
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
        mandatory_fields = {**EVENT_COMMON_FIELDS}
        optional_fields = {**EVENT_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**EVENT_COMMON_FIELDS, **EVENT_OPTIONAL_FIELDS}
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
                    part = _ALL_TYPED[Optional[EventPart]](  # type: ignore
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
                    field = _ALL_TYPED[Optional[EventField]](  # type: ignore
                        field, 'fields', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newfields[anid] = field
        val['fields'] = newfields

    if errs:
        raise errs

    return Event(val)


EVENT_PART_CREATION_MANDATORY_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
    'part_begin': datetime.date,
    'part_end': datetime.date,
    'fee': NonNegativeDecimal,
    'waitlist_field': Optional[ID],  # type: ignore
}

EVENT_PART_CREATION_OPTIONAL_FIELDS: TypeMapping = {
    'tracks': Mapping,
    'fee_modifiers': Mapping,
}

EVENT_PART_COMMON_FIELDS: TypeMapping = {
    **EVENT_PART_CREATION_MANDATORY_FIELDS,
    **EVENT_PART_CREATION_OPTIONAL_FIELDS
}

EVENT_PART_OPTIONAL_FIELDS: TypeMapping = {
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

    mandatory_fields: TypeMapping
    optional_fields: TypeMapping

    if creation:
        mandatory_fields = {**EVENT_PART_CREATION_MANDATORY_FIELDS}
        optional_fields = {**EVENT_PART_CREATION_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {}
        optional_fields = {**EVENT_PART_COMMON_FIELDS, **EVENT_PART_OPTIONAL_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if ('part_begin' in val and 'part_end' in val
            and val['part_begin'] > val['part_end']):
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
                        track = _ALL_TYPED[EventTrack](
                            track, 'tracks', creation=True, **kwargs)
                    else:
                        track = _ALL_TYPED[Optional[EventTrack]](  # type: ignore
                            track, 'tracks', **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newtracks[anid] = track
        val['tracks'] = newtracks

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
                    fee_modifier = _ALL_TYPED[
                        Optional[EventFeeModifier]  # type: ignore
                    ](
                        fee_modifier, 'fee_modifiers', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    new_modifiers[anid] = fee_modifier

        msg = n_("Must not have multiple fee modifiers linked to the same"
                 " field in one event part.")

        aniter: Iterable[Tuple[EventFeeModifier, EventFeeModifier]]
        aniter = itertools.combinations(
            [fm for fm in val['fee_modifiers'].values() if fm], 2)
        for e1, e2 in aniter:
            if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:
                errs.append(ValueError('fee_modifiers', msg))

    if errs:
        raise errs

    return EventPart(val)


EVENT_TRACK_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
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
        mandatory_fields = {**EVENT_TRACK_COMMON_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**EVENT_TRACK_COMMON_FIELDS}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if ('num_choices' in val and 'min_choices' in val
            and val['min_choices'] > val['num_choices']):
        raise ValidationSummary(ValueError("min_choices", n_(
            "Must be less or equal than total Course Choices.")))

    return EventTrack(val)


def _EVENT_FIELD_COMMON_FIELDS(extra_suffix: str) -> TypeMapping:
    return {
        'kind{}'.format(extra_suffix): const.FieldDatatypes,
        'association{}'.format(extra_suffix): const.FieldAssociations,
        'entries{}'.format(extra_suffix): Any,  # type: ignore
    }


def _EVENT_FIELD_OPTIONAL_FIELDS(extra_suffix: str) -> TypeMapping:
    return {
        f'checkin{extra_suffix}': bool,
    }


@_add_typed_validator
def _event_field(
    val: Any, argname: str = "event_field", *, field_name: str = None,
    creation: bool = False, extra_suffix: str = "", **kwargs: Any
) -> EventField:
    """
    :param field_name: If given, set the field name of the field to this.
        This is handy for creating new fields during the questionnaire import,
        where the field name serves as the key and thus is not part of the dict itself.
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :param extra_suffix: Suffix appended to all keys. This is due to the
      necessity of the frontend to create unambiguous names.
    """
    val = _mapping(val, argname, **kwargs)

    field_name_key = "field_name{}".format(extra_suffix)
    if field_name is not None:
        val = dict(val)
        val[field_name_key] = field_name
    if creation:
        spec = {**_EVENT_FIELD_COMMON_FIELDS(extra_suffix),
                field_name_key: RestrictiveIdentifier}
        mandatory_fields = spec
        optional_fields: TypeMapping = _EVENT_FIELD_OPTIONAL_FIELDS(extra_suffix)
    else:
        mandatory_fields = {}
        optional_fields = dict(_EVENT_FIELD_COMMON_FIELDS(extra_suffix),
                               **_EVENT_FIELD_OPTIONAL_FIELDS(extra_suffix))

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, argname=argname, **kwargs)

    entries_key = "entries{}".format(extra_suffix)
    kind_key = "kind{}".format(extra_suffix)

    errs = ValidationSummary()
    if not val.get(entries_key, True):
        val[entries_key] = None
    if entries_key in val and val[entries_key] is not None:
        if isinstance(val[entries_key], str):
            val[entries_key] = list(list(y.strip() for y in x.split(';', 1))
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
                            entries.append([value, description])
                            seen_values.add(value)
            val[entries_key] = entries

    if errs:
        raise errs

    return EventField(val)


def _EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix: str) -> TypeMapping:
    return {
        "modifier_name{}".format(extra_suffix): RestrictiveIdentifier,
        "amount{}".format(extra_suffix): decimal.Decimal,
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
        optional_fields: TypeMapping = {'id': ID}
    else:
        mandatory_fields = {}
        optional_fields = dict(_EVENT_FEE_MODIFIER_COMMON_FIELDS(extra_suffix), id=ID)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    return EventFeeModifier(val)


PAST_COURSE_COMMON_FIELDS: Mapping[str, Any] = {
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
        mandatory_fields = dict(PAST_COURSE_COMMON_FIELDS, pevent_id=ID)
        optional_fields: TypeMapping = {}
    else:
        # no pevent_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = {**PAST_COURSE_COMMON_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    return PastCourse(val)


COURSE_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'description': Optional[str],
    'nr': str,
    'shortname': LegacyShortname,
    'instructors': Optional[str],
    'max_size': Optional[NonNegativeInt],
    'min_size': Optional[NonNegativeInt],
    'notes': Optional[str],
}

COURSE_OPTIONAL_FIELDS: TypeMapping = {
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
        mandatory_fields = dict(COURSE_COMMON_FIELDS, event_id=ID)
        optional_fields = {**COURSE_OPTIONAL_FIELDS}
        # TODO make dict(field, ...) vs {**fields, ...} consistent
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = {**COURSE_COMMON_FIELDS, **COURSE_OPTIONAL_FIELDS}

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


REGISTRATION_COMMON_FIELDS: Mapping[str, Any] = {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': Optional[str],
    'parts': Mapping,
    'tracks': Mapping,
}

REGISTRATION_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'parental_agreement': bool,
    'real_persona_id': Optional[ID],
    'orga_notes': Optional[str],
    'payment': Optional[datetime.date],
    'amount_paid': NonNegativeDecimal,
    'checkin': Optional[datetime.datetime],
    'fields': Mapping,
}


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
        mandatory_fields = dict(REGISTRATION_COMMON_FIELDS,
                                persona_id=ID, event_id=ID)
        optional_fields = {**REGISTRATION_OPTIONAL_FIELDS}
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = {**REGISTRATION_COMMON_FIELDS, **REGISTRATION_OPTIONAL_FIELDS}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'parts' in val:
        newparts = {}
        for anid, part in val['parts'].items():
            try:
                anid = _id(anid, 'parts', **kwargs)
                part = _ALL_TYPED[Optional[RegistrationPart]](  # type: ignore
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
                track = _ALL_TYPED[Optional[RegistrationTrack]](  # type: ignore
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

    optional_fields: TypeMapping = {
        'status': const.RegistrationPartStati,
        'lodgement_id': Optional[ID],  # type: ignore
        'is_camping_mat': bool,
    }
    return RegistrationPart(_examine_dictionary_fields(
        val, {}, optional_fields, **kwargs))


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

    optional_fields: TypeMapping = {
        'course_id': Optional[ID],  # type: ignore
        'course_instructor': Optional[ID],  # type: ignore
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
    datatypes: Dict[str, Type[Any]] = {}
    for field in fields.values():
        if field['association'] == association:
            dt = _ALL_TYPED[const.FieldDatatypes](
                field['kind'], field['field_name'], **kwargs)
            datatypes[field['field_name']] = cast(Type[Any], eval(  # pylint: disable=eval-used
                f"Optional[{dt.name}]",
                {
                    'Optional': Optional,
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


@_add_typed_validator
def _fee_booking_entry(val: Any, argname: str = "fee_booking_entry",
                       **kwargs: Any) -> FeeBookingEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: Dict[str, Any] = {
        'registration_id': int,
        'date': Optional[datetime.date],
        'original_date': datetime.date,
        'amount': decimal.Decimal,
    }
    optional_fields: TypeMapping = {}
    return FeeBookingEntry(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


LODGEMENT_GROUP_FIELDS: TypeMapping = {
    'title': str,
}


@_add_typed_validator
def _lodgement_group(
    val: Any, argname: str = "lodgement_group", *,
    creation: bool = False, **kwargs: Any
) -> LodgementGroup:
    """
    :param creation: If ``True`` test the data set for fitness for creation
        of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(LODGEMENT_GROUP_FIELDS, event_id=ID)
        optional_fields: TypeMapping = {}
    else:
        # no event_id, since the associated event should be fixed.
        mandatory_fields = {'id': ID}
        optional_fields = dict(LODGEMENT_GROUP_FIELDS, event_id=ID)

    return LodgementGroup(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


LODGEMENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'regular_capacity': NonNegativeInt,
    'camping_mat_capacity': NonNegativeInt,
    'notes': Optional[str],
    'group_id': Optional[ID],
}

LODGEMENT_OPTIONAL_FIELDS: TypeMapping = {
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
        mandatory_fields = dict(LODGEMENT_COMMON_FIELDS, event_id=ID)
        optional_fields = {**LODGEMENT_OPTIONAL_FIELDS}
    else:
        # no event_id, since the associated event should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = {**LODGEMENT_COMMON_FIELDS, **LODGEMENT_OPTIONAL_FIELDS}

    # the check of fields is delegated to _event_associated_fields
    return Lodgement(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


# TODO is kind optional?
# TODO make argname non-optional
@_add_typed_validator
def _by_field_datatype(
    val: Any, argname: str = None, *, kind: FieldDatatypes, **kwargs: Any
) -> ByFieldDatatype:
    kind = FieldDatatypes(kind)
    # using Any seems fine, otherwise this would need a big Union
    val: Any = _ALL_TYPED[
        Optional[VALIDATOR_LOOKUP[kind.name]]  # type: ignore
    ](val, argname, **kwargs)

    if kind in {FieldDatatypes.date, FieldDatatypes.datetime}:
        val = val.isoformat()
    else:
        val = str(val)

    return ByFieldDatatype(val)


QUESTIONNAIRE_ROW_MANDATORY_FIELDS: TypeMapping = {
    'title': Optional[str],  # type: ignore
    'info': Optional[str],  # type: ignore
    'input_size': Optional[int],  # type: ignore
    'readonly': Optional[bool],  # type: ignore
    'default_value': Optional[str],  # type: ignore
}


def _questionnaire_row(
    val: Any, field_definitions: CdEDBObjectMap, fee_modifier_fields: Set[int],
    kind: const.QuestionnaireUsages, argname: str = "questionnaire_row", **kwargs: Any,
) -> QuestionnaireRow:

    argname_prefix = argname + "." if argname else ""
    value = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'field_id': Optional[ID],  # type: ignore[dict-item]
        'field_name': Optional[RestrictiveIdentifier],  # type: ignore[dict-item]
        'kind': const.QuestionnaireUsages,
        'pos': int,
    }

    value = _examine_dictionary_fields(
        value, QUESTIONNAIRE_ROW_MANDATORY_FIELDS, optional_fields,
        argname=argname, **kwargs)

    errs = ValidationSummary()
    if 'kind' in value:
        if value['kind'] != kind:
            msg = n_("Incorrect kind for this part of the questionnaire")
            errs.append(ValueError(argname_prefix + 'kind', msg))
    else:
        value['kind'] = kind

    fields_by_name = {f['field_name']: f for f in field_definitions.values()}
    if 'field_name' in value:
        if not value['field_name']:
            del value['field_name']
        elif value.get('field_id'):
            msg = n_("Cannot specify both field id and field name.")
            errs.append(ValueError(argname_prefix + 'field_id', msg))
            errs.append(ValueError(argname_prefix + 'field_name', msg))
        else:
            if value['field_name'] not in fields_by_name:
                errs.append(KeyError(
                    argname_prefix + 'field_name',
                    n_("No field with name '%(name)s' exists."),
                    {"name": value['field_name']}))
            else:
                value['field_id'] = fields_by_name[value['field_name']].get('id')
                if value['field_id']:
                    del value['field_name']
    if 'field_id' not in value:
        value['field_id'] = None

    if value['field_id']:
        field = field_definitions.get(value['field_id'], None)
        if not field:
            raise ValidationSummary(
                KeyError(argname_prefix + 'default_value',
                         n_("Referenced field does not exist.")))
        if value['default_value']:
            value['default_value'] = _by_field_datatype(
                value['default_value'], "default_value",
                kind=field.get('kind', FieldDatatypes.str), **kwargs)

    field_id = value['field_id']
    value['readonly'] = bool(value['readonly']) if field_id else None
    if field_id and field_id in fee_modifier_fields:
        if not kind.allow_fee_modifier():
            msg = n_("Inappropriate questionnaire usage for fee modifier field.")
            errs.append(ValueError(argname_prefix + 'kind', msg))
    if value['readonly'] and not kind.allow_readonly():
        msg = n_("Registration questionnaire rows may not be readonly.")
        errs.append(ValueError(argname_prefix + 'readonly', msg))

    if errs:
        raise errs

    return QuestionnaireRow(value)


# TODO change parameter order to make more consistent?
# TODO type fee_modifiers
@_add_typed_validator
def _questionnaire(
    val: Any, field_definitions: CdEDBObjectMap, fee_modifiers: CdEDBObjectMap,
    argname: str = "questionnaire",
    **kwargs: Any
) -> Questionnaire:

    val = _mapping(val, argname, **kwargs)

    errs = ValidationSummary()
    ret: Dict[int, List[QuestionnaireRow]] = {}
    fee_modifier_fields = {e['field_id'] for e in fee_modifiers.values()}
    for k, v in copy.deepcopy(val).items():
        try:
            k = _ALL_TYPED[const.QuestionnaireUsages](k, argname, **kwargs)
            v = _iterable(v, argname, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            ret[k] = []
            for i, value in enumerate(v):
                row_argname = argname + f"[{k.name}][{i+1}]"
                try:
                    value = _questionnaire_row(
                        value, field_definitions, fee_modifier_fields,
                        kind=k, argname=row_argname, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                    continue
                value['pos'] = i+1
                ret[k].append(value)

    all_rows = itertools.chain.from_iterable(ret.values())
    for e1, e2 in itertools.combinations(all_rows, 2):
        if e1['field_id'] is not None and e1['field_id'] == e2['field_id']:
            errs.append(ValueError(
                'field_id', n_("Must not duplicate field ('%(field_name)s')."),
                {'field_name': field_definitions[e1['field_id']]['field_name']}))

    if errs:
        raise errs

    return Questionnaire(ret)


# TODO move above
@_add_typed_validator
def _json(
    val: Any, argname: str = "json", **kwargs: Any
) -> JSON:
    """Deserialize a JSON payload.

    This is a bit different from many other validatiors in that it is not
    idempotent.
    """
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8")  # TODO remove encoding argument?
        except UnicodeDecodeError as e:
            raise ValidationSummary(ValueError(
                argname, n_("Invalid UTF-8 sequence."))) from e
    val = _str(val, argname, **kwargs)
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

    mandatory_fields: TypeMapping = {
        'EVENT_SCHEMA_VERSION': Tuple[int, int],  # type: ignore
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
    table_validators: Mapping[str, Callable[..., Any]] = {
        'event.events': _event,
        'event.event_parts': _augment_dict_validator(
            _event_part, {'id': ID, 'event_id': ID}),
        'event.course_tracks': _augment_dict_validator(
            _event_track, {'part_id': ID}),
        'event.courses': _augment_dict_validator(
            _course, {'event_id': ID}),
        'event.course_segments': _augment_dict_validator(
            _empty_dict, {'id': ID, 'course_id': ID, 'track_id': ID,
                          'is_active': bool}),
        'event.log': _augment_dict_validator(
            _empty_dict, {'id': ID, 'ctime': datetime.datetime, 'code': int,
                          'submitted_by': ID, 'event_id': Optional[ID],  # type: ignore
                          'persona_id': Optional[ID],  # type: ignore
                          'change_note': Optional[str], }),  # type: ignore
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
            _empty_dict, {
                'id': ID, 'event_id': ID, 'pos': int,
                'field_id': Optional[ID], 'title': Optional[str],  # type: ignore
                'info': Optional[str], 'input_size': Optional[int],  # type: ignore
                'readonly': Optional[bool],  # type: ignore
                'kind': const.QuestionnaireUsages,
            }),
        'event.fee_modifiers': _augment_dict_validator(
            _event_fee_modifier, {'id': ID, 'part_id': ID}),
    }

    errs = ValidationSummary()
    for table, validator in table_validators.items():
        new_table = {}
        for key, entry in val[table].items():
            try:
                new_entry = validator(entry, table, **kwargs)
                new_key = _int(key, table, **kwargs)
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
    if val['event.events'] and val['id'] != val['event.events'][val['id']]['id']:
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

    mandatory_fields: TypeMapping = {
        'EVENT_SCHEMA_VERSION': Tuple[int, int],  # type: ignore
        'kind': str,
        'id': ID,
        'timestamp': datetime.datetime,
    }
    optional_fields = {
        'courses': Mapping,
        'lodgement_groups': Mapping,
        'lodgements': Mapping,
        'registrations': Mapping,
        'summary': str,
    }

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if not((EVENT_SCHEMA_VERSION[0], 0) <= val['EVENT_SCHEMA_VERSION']
           <= EVENT_SCHEMA_VERSION):
        raise ValidationSummary(ValueError(
            argname, n_("Schema version mismatch.")))

    domain_validators: TypeMapping = {
        'courses': Optional[PartialCourse],  # type: ignore
        'lodgement_groups': Optional[PartialLodgementGroup],  # type: ignore
        'lodgements': Optional[PartialLodgement],  # type: ignore
        'registrations': Optional[PartialRegistration],  # type: ignore
    }

    errs = ValidationSummary()
    for domain, type_ in domain_validators.items():
        if domain not in val:
            continue
        new_dict = {}
        for key, entry in val[domain].items():
            try:
                # fix JSON key restriction
                new_key = _int(key, domain, **kwargs)
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


PARTIAL_COURSE_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'description': Optional[str],
    'nr': Optional[str],
    'shortname': LegacyShortname,
    'instructors': Optional[str],
    'max_size': Optional[int],
    'min_size': Optional[int],
    'notes': Optional[str],
}

PARTIAL_COURSE_OPTIONAL_FIELDS: TypeMapping = {
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
        mandatory_fields = {**PARTIAL_COURSE_COMMON_FIELDS}
        optional_fields = {**PARTIAL_COURSE_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {}
        optional_fields = {**PARTIAL_COURSE_COMMON_FIELDS,
                           **PARTIAL_COURSE_OPTIONAL_FIELDS}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'segments' in val:
        new_dict = {}
        for key, entry in val['segments'].items():
            try:
                new_key = _int(key, 'segments', **kwargs)
                new_entry = _ALL_TYPED[Optional[bool]](  # type: ignore
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


PARTIAL_LODGEMENT_GROUP_FIELDS: TypeMapping = {
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
        mandatory_fields = {**PARTIAL_LODGEMENT_GROUP_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = {**PARTIAL_LODGEMENT_GROUP_FIELDS}

    return PartialLodgementGroup(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


PARTIAL_LODGEMENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'regular_capacity': NonNegativeInt,
    'camping_mat_capacity': NonNegativeInt,
    'notes': Optional[str],
    'group_id': Optional[PartialImportID],
}

PARTIAL_LODGEMENT_OPTIONAL_FIELDS: TypeMapping = {
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
        mandatory_fields = {**PARTIAL_LODGEMENT_COMMON_FIELDS}
        optional_fields = {**PARTIAL_LODGEMENT_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {}
        optional_fields = {**PARTIAL_LODGEMENT_COMMON_FIELDS,
                           **PARTIAL_LODGEMENT_OPTIONAL_FIELDS}

    # the check of fields is delegated to _event_associated_fields
    return PartialLodgement(_examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs))


PARTIAL_REGISTRATION_COMMON_FIELDS: Mapping[str, Any] = {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': Optional[str],
    'parts': Mapping,
    'tracks': Mapping,
}

PARTIAL_REGISTRATION_OPTIONAL_FIELDS: Mapping[str, Any] = {
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
        mandatory_fields = dict(PARTIAL_REGISTRATION_COMMON_FIELDS, persona_id=ID)
        optional_fields = {**PARTIAL_REGISTRATION_OPTIONAL_FIELDS}
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {}
        optional_fields = {**PARTIAL_REGISTRATION_COMMON_FIELDS,
                           **PARTIAL_REGISTRATION_OPTIONAL_FIELDS}

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

    optional_fields: TypeMapping = {
        'status': const.RegistrationPartStati,
        'lodgement_id': Optional[PartialImportID],  # type: ignore
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

    optional_fields: TypeMapping = {
        'course_id': Optional[PartialImportID],  # type: ignore
        'course_instructor': Optional[PartialImportID],  # type: ignore
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


@_add_typed_validator
def _serialized_event_questionnaire_upload(
    val: Any, argname: str = "serialized_event_questionnaire_upload", **kwargs: Any,
) -> SerializedEventQuestionnaireUpload:

    val = _input_file(val, argname, **kwargs)
    val = _json(val, argname, **kwargs)
    return SerializedEventQuestionnaireUpload(
        _serialized_event_questionnaire(val, argname, **kwargs))  # pylint: disable=missing-kwoa # noqa


@_add_typed_validator
def _serialized_event_questionnaire(
    val: Any, argname: str = "serialized_event_questionnaire", *,
    field_definitions: CdEDBObjectMap, fee_modifiers: CdEDBObjectMap,
    questionnaire: Dict[const.QuestionnaireUsages, List[QuestionnaireRow]],
    extend_questionnaire: bool, skip_existing_fields: bool,
    **kwargs: Any
) -> SerializedEventQuestionnaire:

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'fields': Mapping,
        'questionnaire': Mapping,
    }
    val = _examine_dictionary_fields(val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    field_definitions = copy.deepcopy(field_definitions)
    fields_by_name = {f['field_name']: f for f in field_definitions.values()}
    if 'fields' in val:
        newfields = {}
        for i, (field_name, field) in enumerate(val['fields'].items()):
            field_argname = f"fields[{i+1}]"
            try:
                field_name = _str(field_name, field_argname, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                if field_name in fields_by_name:
                    if not skip_existing_fields:
                        errs.append(KeyError(
                            field_argname,
                            n_("A field with this name already exists"
                               " ('%(field_name)s')."),
                            {'field_name': field_name}))
                    continue
                try:
                    field = _ALL_TYPED[EventField](
                        field, field_argname, creation=True, field_name=field_name,
                        **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newfields[-(i + 1)] = field
        val['fields'] = newfields
        field_definitions.update(newfields)
    else:
        val['fields'] = {}

    if 'questionnaire' in val:
        try:
            new_questionnaire = _questionnaire(
                val['questionnaire'], field_definitions, fee_modifiers, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            if extend_questionnaire:
                tmp = {
                    kind: questionnaire.get(kind, []) + new_questionnaire.get(kind, [])
                    for kind in const.QuestionnaireUsages
                }
                try:
                    new_questionnaire = _questionnaire(
                        tmp, field_definitions, fee_modifiers, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)

            val['questionnaire'] = new_questionnaire
    else:
        val['questionnaire'] = {}

    if errs:
        raise errs

    return SerializedEventQuestionnaire(val)


MAILINGLIST_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'local_part': EmailLocalPart,
    'domain': const.MailinglistDomain,
    'description': Optional[str],
    'mod_policy': const.ModerationPolicy,
    'attachment_policy': const.AttachmentPolicy,
    'ml_type': const.MailinglistTypes,
    'subject_prefix': Optional[str],
    'maxsize': Optional[ID],
    'is_active': bool,
    'notes': Optional[str],
}

MAILINGLIST_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'assembly_id': NoneType,
    'event_id': NoneType,
    'registration_stati': EmptyList,
}

ALL_MAILINGLIST_FIELDS = (MAILINGLIST_COMMON_FIELDS.keys() |
                          ml_type.ADDITIONAL_TYPE_FIELDS.items())

MAILINGLIST_READONLY_FIELDS = {
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
    mandatory_validation_fields: TypeMapping = {'moderators': List[ID]}
    optional_validation_fields: TypeMapping = {'whitelist': List[Email]}
    if "ml_type" not in val:
        raise ValidationSummary(ValueError(
            "ml_type", "Must provide ml_type for setting mailinglist."))
    atype = ml_type.get_type(val["ml_type"])
    mandatory_validation_fields.update(  # type: ignore
        atype.mandatory_validation_fields)
    optional_validation_fields.update(  # type: ignore
        atype.optional_validation_fields)
    mandatory_fields = {**MAILINGLIST_COMMON_FIELDS}
    optional_fields = {**MAILINGLIST_OPTIONAL_FIELDS}

    # iterable_fields = []
    for source, target in ((mandatory_validation_fields, mandatory_fields),
                           (optional_validation_fields, optional_fields)):
        for key, validator in source.items():
            target[key] = validator
    # Optionally remove readonly attributes, take care to keep the original.
    if _allow_readonly:
        val = dict(copy.deepcopy(val))
        for key in MAILINGLIST_READONLY_FIELDS:
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

    if val and "moderators" in val and not val["moderators"]:
        # TODO is this legitimate (postpone after other errors?)
        raise ValidationSummary(ValueError(
            "moderators", n_("Must not be empty.")))

    errs = ValidationSummary()

    if "domain" not in val:
        errs.append(ValueError(
            "domain", "Must specify domain for setting mailinglist."))
    else:
        atype = ml_type.get_type(val["ml_type"])
        if val["domain"].value not in atype.domains:
            errs.append(ValueError("domain", n_(
                "Invalid domain for this mailinglist type.")))

    if errs:
        raise errs

    return Mailinglist(val)


SUBSCRIPTION_ID_FIELDS: TypeMapping = {
    'mailinglist_id': ID,
    'persona_id': ID,
}

SUBSCRIPTION_STATE_FIELDS: TypeMapping = {
    'subscription_state': const.SubscriptionState,
}

SUBSCRIPTION_ADDRESS_FIELDS: TypeMapping = {
    'address': Email,
}


@_add_typed_validator
def _subscription_identifier(
    val: Any, argname: str = "subscription_identifier", **kwargs: Any
) -> SubscriptionIdentifier:
    val = _mapping(val, argname, **kwargs)

    # TODO why is deepcopy mandatory?
    # TODO maybe make signature of examine dict to take a non-mutable mapping?
    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}

    return SubscriptionIdentifier(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_dataset(
    val: Any, argname: str = "subscription_dataset", **kwargs: Any
) -> SubscriptionDataset:
    val = _mapping(val, argname, **kwargs)

    # TODO instead of deepcopy simply do not mutate mandatory_fields
    # TODO or use function returning the dict everywhere instead
    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}
    mandatory_fields.update(SUBSCRIPTION_STATE_FIELDS)

    return SubscriptionDataset(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_address(
    val: Any, argname: str = "subscription address", **kwargs: Any
) -> SubscriptionAddress:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}
    mandatory_fields.update(SUBSCRIPTION_ADDRESS_FIELDS)

    return SubscriptionAddress(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


ASSEMBLY_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'shortname': ShortnameIdentifier,
    'description': Optional[str],
    'signup_end': datetime.datetime,
    'notes': Optional[str],
}

ASSEMBLY_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'is_active': bool,
    'presider_address': Optional[Email],
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
        mandatory_fields = {**ASSEMBLY_COMMON_FIELDS}
        optional_fields = {**ASSEMBLY_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**ASSEMBLY_COMMON_FIELDS, **ASSEMBLY_OPTIONAL_FIELDS}

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


BALLOT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'description': Optional[str],
    'vote_begin': datetime.datetime,
    'vote_end': datetime.datetime,
    'notes': Optional[str],
}

BALLOT_EXPOSED_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'vote_extension_end': Optional[datetime.datetime],
    'abs_quorum': int,
    'rel_quorum': int,
    'votes': Optional[PositiveInt],
    'use_bar': bool,
}

BALLOT_EXPOSED_FIELDS = {**BALLOT_COMMON_FIELDS, **BALLOT_EXPOSED_OPTIONAL_FIELDS}

BALLOT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    **BALLOT_EXPOSED_OPTIONAL_FIELDS,
    'extended': Optional[bool],
    'is_tallied': bool,
    'candidates': Mapping,
    'linked_attachments': Optional[List[Optional[ID]]]
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
        mandatory_fields = dict(BALLOT_COMMON_FIELDS, assembly_id=ID)
        optional_fields = {**BALLOT_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**BALLOT_COMMON_FIELDS, **BALLOT_OPTIONAL_FIELDS}

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
                    candidate = _ALL_TYPED[Optional[BallotCandidate]](  # type: ignore
                        candidate, 'candidates', creation=creation, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newcandidates[anid] = candidate
        val['candidates'] = newcandidates

    if val.get('abs_quorum') and val.get('rel_quorum'):
        msg = n_("Must not specify both absolute and relative quorum.")
        errs.extend([
            ValueError('abs_quorum', msg),
            ValueError('rel_quorum', msg),
        ])

    quorum = val.get('abs_quorum')
    if 'rel_quorum' in val and not quorum:
        quorum = val['rel_quorum']
        if not 0 <= quorum <= 100:
            errs.append(ValueError("abs_quorum", n_(
                "Relative quorum must be between 0 and 100.")))

    vote_extension_error = ValueError("vote_extension_end", n_(
        "Must be specified if quorum is given."))

    quorum_msg = n_("Must specify a quorum if vote extension end is given.")
    quorum_errors = [
        ValueError("abs_quorum", quorum_msg),
        ValueError("rel_quorum", quorum_msg),
    ]

    if (quorum is None) == ('vote_extension_end' in val):
        # only one of quorum and extension end is given
        if quorum is None:
            errs.extend(quorum_errors)
        else:
            errs.append(vote_extension_error)
        # at least one error occured
        raise errs

    # TODO this and the above could be merged
    if 'vote_extension_end' in val:
        # quorum can not be None at this point
        if val['vote_extension_end'] is None and quorum:
            # No extension end, but quorum
            errs.append(vote_extension_error)
        elif val['vote_extension_end'] and not quorum:
            # No quorum, but extension end
            errs.extend(quorum_errors)

    if errs:
        raise errs

    return Ballot(val)


BALLOT_CANDIDATE_COMMON_FIELDS: TypeMapping = {
    'title': LegacyShortname,
    'shortname': ShortnameIdentifier,
}


@_add_typed_validator
def _ballot_candidate(
    val: Any, argname: str = "ballot_candidate", *,
    creation: bool = False, ignore_warnings: bool = False, **kwargs: Any
) -> BallotCandidate:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, ignore_warnings=ignore_warnings, **kwargs)

    if creation:
        mandatory_fields = {**BALLOT_CANDIDATE_COMMON_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = {**BALLOT_CANDIDATE_COMMON_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                     ignore_warnings=ignore_warnings, **kwargs)

    errs = ValidationSummary()
    if val.get('shortname') == ASSEMBLY_BAR_SHORTNAME:
        errs.append(ValueError("shortname", n_("Mustn’t be the bar shortname.")))

    if errs:
        raise errs

    return BallotCandidate(val)


ASSEMBLY_ATTACHMENT_FIELDS: Mapping[str, Any] = {
    'assembly_id': ID,
}


ASSEMBLY_ATTACHMENT_VERSION_FIELDS: Mapping[str, Any] = {
    'title': str,
    'authors': Optional[str],
    'filename': str,
}


@_add_typed_validator
def _assembly_attachment(
    val: Any, argname: str = "assembly_attachment", **kwargs: Any
) -> AssemblyAttachment:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = dict(ASSEMBLY_ATTACHMENT_VERSION_FIELDS,
                            **ASSEMBLY_ATTACHMENT_FIELDS)

    val = _examine_dictionary_fields(val, mandatory_fields, **kwargs)

    return AssemblyAttachment(val)


@_add_typed_validator
def _assembly_attachment_version(
    val: Any, argname: str = "assembly_attachment_version", **kwargs: Any
) -> AssemblyAttachmentVersion:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = dict(ASSEMBLY_ATTACHMENT_VERSION_FIELDS, attachment_id=ID)
    optional_fields: TypeMapping = {}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    return AssemblyAttachmentVersion(val)


@_add_typed_validator
def _vote(
    val: Any, argname: str = "vote",
    ballot: CdEDBObject = None, **kwargs: Any
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
        raise ValidationSummary(  # pylint: disable=raise-missing-from
            ValueError(argname,
                       n_("Invalid  regular expression (position %(pos)s)."),
                       {'pos': e.pos}))
        # TODO wait for mypy to ship updated typeshed
    return Regex(val)


@_add_typed_validator
def _non_regex(
    val: Any, argname: str = None, **kwargs: Any
) -> NonRegex:
    val = _str(val, argname, **kwargs)
    forbidden_chars = r'\*+?{}()[]|'
    msg = n_("Must not contain any forbidden characters"
             " (which are %(forbidden_chars)s while .^$ are allowed).")
    if any(char in val for char in forbidden_chars):
        raise ValidationSummary(
            ValueError(argname, msg, {"forbidden_chars": forbidden_chars}))
    return NonRegex(val)


@_add_typed_validator
def _query_input(
    val: Any, argname: str = None, *,
    spec: Mapping[str, str], allow_empty: bool = False,
    separator: str = ',', escape: str = '\\',
    **kwargs: Any
) -> QueryInput:
    """This is for the queries coming from the web and the database.

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

    scope = _ALL_TYPED[QueryScope](val["scope"], "scope", **kwargs)
    name = ""
    if val.get("query_name"):
        name = _ALL_TYPED[str](val["query_name"], "query_name", **kwargs)
    query_id: Optional[ID] = None
    if val.get("query_id"):
        query_id = _ALL_TYPED[ID](val["query_id"], "query_id", **kwargs)
    fields_of_interest = []
    constraints = []
    order: List[QueryOrder] = []
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
            operator: Optional[QueryOperators] = _ALL_TYPED[
                Optional[QueryOperators]  # type: ignore
            ](
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
            # filter out empty strings
            values = filter(None, values)
            value = []
            for v in values:
                # Validate every single value
                # TODO do not allow None/falsy
                try:
                    vv: Any = _ALL_TYPED[
                        Optional[VALIDATOR_LOOKUP[validator]]  # type: ignore
                    ](
                        v, field, **kwargs)
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
                value = _ALL_TYPED[Optional[NonRegex]](  # type: ignore
                    value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        elif operator in (QueryOperators.regex, QueryOperators.notregex):
            try:
                value = _ALL_TYPED[Optional[Regex]](  # type: ignore
                    value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        else:
            try:
                value = _ALL_TYPED[
                    Optional[VALIDATOR_LOOKUP[validator]]  # type: ignore
                ](
                    value, field, **kwargs)
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
            entry: Optional[CSVIdentifier] = _ALL_TYPED[
                Optional[CSVIdentifier]  # type: ignore
            ](val["qord_" + postfix], "qord_" + postfix, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if not entry or entry not in spec:
            continue

        tmp = "qord_" + postfix + "_ascending"
        try:
            ascending = _ALL_TYPED[bool](val.get(tmp, "True"), tmp, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        order.append((entry, ascending))

    if errs:
        raise errs

    return QueryInput(Query(
        scope, dict(spec), fields_of_interest, constraints, order, name, query_id))


# TODO ignore ignore_warnings here too?
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

    # scope and name
    _ALL_TYPED[QueryScope](val.scope, "scope", **kwargs)
    _ALL_TYPED[Optional[str]](  # type: ignore
        val.name, "name", **kwargs)

    # spec
    for field, validator in val.spec.items():
        try:
            _csv_identifier(field, "spec", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

        try:
            _printable_ascii(validator, "spec", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

    # fields_of_interest
    for field in val.fields_of_interest:
        try:
            _csv_identifier(field, "fields_of_interest", **kwargs)
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
            field = _csv_identifier(field, "constraints", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

        if field not in val.spec:
            errs.append(KeyError("constraints", n_("Invalid field.")))
            continue

        try:
            operator = _ALL_TYPED[QueryOperators](
                operator, "constraints/{}".format(field), **kwargs)
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
            validator = _ALL_TYPED[
                Optional[VALIDATOR_LOOKUP[val.spec[field]]]]  # type: ignore
            for v in value:
                try:
                    validator(v, "constraints/{}".format(field), **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
        else:
            try:
                _ALL_TYPED[
                    Optional[VALIDATOR_LOOKUP[val.spec[field]]]  # type: ignore
                ](
                    value,
                    "constraints/{}".format(field),
                    **kwargs
                )
            except ValidationSummary as e:
                errs.extend(e)

    # order
    for idx, entry in enumerate(val.order):
        try:
            # TODO use generic tuple here once implemented
            entry = _ALL_TYPED[Iterable](  # type: ignore
                entry, 'order', **kwargs)
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
                _csv_identifier(field, "order", **kwargs)
                _bool(ascending, "order", **kwargs)
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
        val: Any, argname: str = None,
        **kwargs: Any
    ) -> E:
        if isinstance(val, anenum):
            return val

        # first, try to convert if the enum member is given as "class.member"
        if isinstance(val, str):
            try:
                enum_name, enum_val = val.split(".", 1)
                if enum_name == anenum.__name__:
                    return anenum[enum_val]
            except (KeyError, ValueError):
                pass

        # second, try to convert if the enum member is given as str(int)
        try:
            val = _int(val, argname=argname, **kwargs)
            return anenum(val)
        except (ValidationSummary, ValueError) as e:
            raise ValidationSummary(ValueError(
                argname, error_msg, {'enum': anenum})) from e

    the_validator.__name__ = name or f"_enum_{anenum.__name__.lower()}"

    if not internal:
        _add_typed_validator(the_validator, anenum)

    return the_validator


for oneenum in ALL_ENUMS:
    _enum_validator_maker(oneenum)


@_add_typed_validator
def _db_subscription_state(
    val: Any, argname: str = None, **kwargs: Any
) -> DatabaseSubscriptionState:
    """Validates whether a subscription state is written into the database."""
    val = _ALL_TYPED[const.SubscriptionState](val, argname, **kwargs)
    if val == const.SubscriptionState.none:
        raise ValidationSummary(ValueError(
            argname, n_("SubscriptionState.none is not written into the database.")))
    return DatabaseSubscriptionState(val)


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
        val: Any, argname: str = None,
        **kwargs: Any
    ) -> E:
        val_int: Optional[int]

        if isinstance(val, InfiniteEnum):
            val_enum = raw_validator(
                val.enum, argname=argname, **kwargs)

            if val.enum.value == INFINITE_ENUM_MAGIC_NUMBER:
                val_int = _non_negative_int(
                    val.int, argname=argname, **kwargs)
            else:
                val_int = None

        else:
            val = _int(val, argname=argname, **kwargs)

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

        return InfiniteEnum[anenum](val_enum, val_int)  # type: ignore

    the_validator.__name__ = name or f"_infinite_enum_{anenum.__name__.lower()}"
    _add_typed_validator(the_validator, InfiniteEnum[anenum])  # type: ignore


for oneenum in ALL_INFINITE_ENUMS:
    _infinite_enum_validator_maker(oneenum)
