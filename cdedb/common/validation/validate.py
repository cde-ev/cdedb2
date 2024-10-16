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
import base64
import collections
import copy
import csv
import dataclasses
import datetime
import decimal
import distutils.util
import enum
import functools
import io
import itertools
import json
import logging
import math
import pathlib
import re
import string
import typing
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from types import TracebackType, UnionType
from typing import (
    Any,
    Callable,
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

import magic
import phonenumbers
import PIL.Image
import werkzeug.datastructures
import zxcvbn
from schulze_condorcet.util import as_vote_tuple, validate_votes

import cdedb.database.constants as const
import cdedb.fee_condition_parser.evaluation as fcp_evaluation
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
import cdedb.models.core as models_core
import cdedb.models.droid as models_droid
import cdedb.models.event as models_event
import cdedb.models.ml as models_ml
from cdedb.common import (
    ASSEMBLY_BAR_SHORTNAME,
    EPSILON,
    EVENT_SCHEMA_VERSION,
    INFINITE_ENUM_MAGIC_NUMBER,
    CdEDBObject,
    CdEDBObjectMap,
    Error,
    InfiniteEnum,
    LineResolutions,
    asciificator,
    compute_checkdigit,
    now,
    parse_date,
    parse_datetime,
)
from cdedb.common.exceptions import ValidationWarning
from cdedb.common.fields import EVENT_FIELD_SPEC, REALM_SPECIFIC_GENESIS_FIELDS
from cdedb.common.n_ import n_
from cdedb.common.query import (
    MAX_QUERY_ORDERS,
    MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS,
    VALID_QUERY_OPERATORS,
    Query,
    QueryOperators,
    QueryOrder,
    QueryScope,
    QuerySpec,
)
from cdedb.common.query.log_filter import GenericLogFilter
from cdedb.common.roles import ADMIN_KEYS, extract_roles
from cdedb.common.sorting import xsorted
from cdedb.common.validation.data import COUNTRY_CODES, FREQUENCY_LISTS, IBAN_LENGTHS
from cdedb.common.validation.types import *  # pylint: disable=wildcard-import,unused-wildcard-import; # noqa: F403
from cdedb.config import LazyConfig
from cdedb.database.constants import FieldAssociations, FieldDatatypes
from cdedb.enums import ALL_ENUMS, ALL_INFINITE_ENUMS
from cdedb.models.common import CdEDataclass
from cdedb.uncommon.intenum import CdEIntEnum

NoneType = type(None)

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)
_CONFIG = LazyConfig()

T = TypeVar('T')
T_Co = TypeVar('T_Co', covariant=True)
F = TypeVar('F', bound=Callable[..., Any])
DC = TypeVar('DC', bound=Union[CdEDataclass, GenericLogFilter])


class ValidationSummary(ValueError, Sequence[Exception]):
    args: tuple[Exception, ...]

    def __len__(self) -> int:
        return len(self.args)

    @overload
    def __getitem__(self, index: int) -> Exception: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Exception]: ...

    def __getitem__(
        self, index: Union[int, slice],
    ) -> Union[Exception, Sequence[Exception]]:
        return self.args[index]

    def extend(self, errors: Iterable[Exception]) -> None:
        self.args = self.args + tuple(errors)

    def append(self, error: Exception) -> None:
        self.args = self.args + (error,)

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: Optional[type[Exception]],
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> bool:
        if isinstance(exc_val, self.__class__):
            self.extend(exc_val)
            return True
        return False


class ValidatorStorage(dict[type[Any], Callable[..., Any]]):
    def __setitem__(self, type_: type[T], validator: Callable[..., T]) -> None:
        super().__setitem__(type_, validator)

    def __getitem__(self, type_: type[T]) -> Callable[..., T]:
        origin = typing.get_origin(type_)
        if origin is Union or origin is UnionType:
            inner_type, none_type = typing.get_args(type_)
            if none_type is not NoneType:
                raise KeyError("Complex unions not supported")
            validator = self[inner_type]
            return _allow_None(validator)  # type: ignore[return-value]
        elif typing.get_origin(type_) is list:
            [inner_type] = typing.get_args(type_)
            return make_list_validator(inner_type)  # type: ignore[return-value]
        elif typing.get_origin(type_) is set:
            [inner_type] = typing.get_args(type_)
            return make_set_validator(inner_type)  # type: ignore[return-value]
        elif typing.get_origin(type_) is tuple:
            args = typing.get_args(type_)
            if len(args) == 2:
                type_a, type_b = args
                if type_a is type_b:
                    return cast(Callable[..., T], make_pair_validator(type_a))
        # TODO more container types like tuple
        return super().__getitem__(type_)


_ALL_TYPED = ValidatorStorage()

DATACLASS_TO_VALIDATORS: Mapping[type[Any], type[CdEDBObject]] = {
    models_ml.Mailinglist: Mailinglist,
    models_droid.OrgaToken: OrgaToken,
    GenericLogFilter: LogFilter,
    models_event.CustomQueryFilter: CustomQueryFilter,
    models_core.AnonymousMessageData: AnonymousMessage,
}


def _validate_dataclass_preprocess(type_: type[DC], value: Any,
                                   ) -> tuple[type[DC], type[CdEDBObject]]:
    # Keep subclassing intact if possible.
    if isinstance(value, type_):
        subtype = type(value)
    else:
        raise RuntimeError("Value is no instance of given type.")

    # Figure out the closest validator on the class hierarchy.
    if not dataclasses.is_dataclass(value):
        raise RuntimeError("Given value is not an instance of a dataclass.")
    for supertype in type_.mro():
        if supertype in DATACLASS_TO_VALIDATORS:
            validator = DATACLASS_TO_VALIDATORS[supertype]
            break
    else:
        raise RuntimeError("There is no validator mapped to this dataclass.")

    return subtype, validator


def _validate_dataclass_postprocess(subtype: type[DC], validated: CdEDBObject) -> DC:
    dataclass_keys = {field.name for field in dataclasses.fields(subtype)
                      if field.init}
    validated = {k: v for k, v in validated.items() if k in dataclass_keys}
    return cast(DC, subtype(**validated))


def validate_assert_dataclass(type_: type[DC], value: Any, ignore_warnings: bool,
                              **kwargs: Any) -> DC:
    """Wrapper of validate_assert that accepts dataclasses.

    Allows for subclasses, and figures out the appropriate superclass, for which
    a validator exists, dynamically."""
    subtype, validator = _validate_dataclass_preprocess(type_, value)
    if hasattr(value, 'to_validation'):
        val = value.to_validation()
    elif hasattr(value, 'as_dict'):
        val = value.as_dict()
    else:
        val = dataclasses.asdict(value)
    validated = validate_assert(
        validator, val, ignore_warnings=ignore_warnings, subtype=subtype, **kwargs)
    return _validate_dataclass_postprocess(subtype, validated)


def validate_assert(type_: type[T], value: Any, ignore_warnings: bool,
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
            f" with input {value}, {kwargs}.",
        )
        e = errs[0]
        e.args = (f"{e.args[1]} ({e.args[0]})",) + e.args[2:]
        raise e from errs  # pylint: disable=raising-bad-type


def validate_assert_optional(type_: type[T], value: Any, ignore_warnings: bool,
                             **kwargs: Any) -> Optional[T]:
    """Wrapper to avoid a lot of type-ignore statements due to a mypy bug."""
    return validate_assert(Optional[type_], value, ignore_warnings, **kwargs)  # type: ignore[arg-type]


def validate_check(type_: type[T], value: Any, ignore_warnings: bool,
                   field_prefix: str = "", field_postfix: str = "", **kwargs: Any,
                   ) -> tuple[Optional[T], list[Error]]:
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
                e.__class__(*e.args[1:]),
            ) for e in errs
        ]
        _LOGGER.debug(
            f"{old_format} for '{str(type_)}'"
            f" with input {value}, {kwargs}.",
        )
        return None, old_format


def validate_check_optional(
    type_: type[T], value: Any, ignore_warnings: bool, **kwargs: Any,
) -> tuple[Optional[T], list[Error]]:
    """Wrapper to avoid a lot of type-ignore statements due to a mypy bug."""
    return validate_check(Optional[type_], value, ignore_warnings, **kwargs)  # type: ignore[arg-type]


def is_optional(type_: type[T]) -> bool:
    return get_origin(type_) is Union and NoneType in get_args(type_)


def get_errors(errors: list[Error]) -> list[Error]:
    """Returns those errors which are not considered as warnings."""
    def is_error(e: Error) -> bool:
        _, exception = e
        return not isinstance(exception, ValidationWarning)
    return list(filter(is_error, errors))


def get_warnings(errors: list[Error]) -> list[Error]:
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


def _add_typed_validator(fun: F, return_type: Optional[type[Any]] = None) -> F:
    """Mark a typed function for processing into validators."""
    # TODO get rid of dynamic return types for enum
    if not return_type:
        return_type = get_type_hints(fun)["return"]
    assert return_type
    if return_type in _ALL_TYPED:
        raise RuntimeError(f"Type {return_type} already registered")
    _ALL_TYPED[return_type] = fun

    return fun


def _create_optional_mapping_validator(inner_type: type[Any], return_type: type[T], *,
                                       creation_only: bool = False) -> None:
    def the_validator(val: Any, argname: str = return_type.__qualname__, **kwargs: Any,
                      ) -> T:
        val = _mapping(val, argname)
        val = _optional_object_mapping_helper(
            val, inner_type, argname, creation_only=creation_only, **kwargs)
        return cast(T, val)
    _add_typed_validator(the_validator, return_type)


def _create_dataclass_validator(type_: type[DC], return_type: type[T],
                                ) -> Callable[[F], F]:
    def the_validator(val: Any, argname: str = type_.__qualname__, *,
                      creation: bool = False, **kwargs: Any) -> T:
        val = _mapping(val, argname, **kwargs)

        if issubclass(type_, GenericLogFilter):
            mandatory, optional = type_.validation_fields()
        elif issubclass(type_, CdEDataclass):
            mandatory, optional = type_.validation_fields(creation=creation)
        else:
            raise RuntimeError("Impossible.")

        val = _examine_dictionary_fields(val, mandatory, optional, **kwargs)

        return cast(T, val)

    _add_typed_validator(the_validator, return_type)

    def the_decorator(fun: F) -> F:
        del _ALL_TYPED[return_type]

        @functools.wraps(fun)
        def wrapper(val: Any, argname: str = type_.__qualname__, **kwargs: Any) -> T:
            val = the_validator(val, argname, **kwargs)
            val = fun(val, argname, **kwargs)
            return cast(T, val)

        _add_typed_validator(wrapper, return_type)
        return cast(F, wrapper)

    return the_decorator


def _examine_dictionary_fields(
    adict: Mapping[str, Any],
    mandatory_fields: TypeMapping,
    optional_fields: Optional[TypeMapping] = None,
    *,
    argname: str = "",
    allow_superfluous: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
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
    retval: dict[str, Any] = {}
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
        val: Any, argname: Optional[str] = None, **kwargs: Any,
    ) -> dict[str, Any]:
        mandatory_fields = augmentation if strict else {}
        optional_fields = {} if strict else augmentation

        errs = ValidationSummary()
        ret: dict[str, Any] = {}
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
        with errs:
            v = validator(tmp, argname=argname, **kwargs)

        if v is not None:
            ret.update(v)

        if errs:
            raise errs

        return ret

    return new_validator


def escaped_split(string: str, delim: str, escape: str = '\\') -> list[str]:
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


def filter_none(data: dict[str, Any]) -> dict[str, Any]:
    """Helper function to remove NoneType values from dictionaies."""
    return {k: v for k, v in data.items() if v is not NoneType}

#
# Below is the real stuff
#


@_add_typed_validator
def _None(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Any:
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.
    """
    return val


@_add_typed_validator
def _int(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NonNegativeInt:
    val = _int(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Must not be negative.")))
    return NonNegativeInt(val)


@_add_typed_validator
def _positive_int(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> PositiveInt:
    val = _int(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be positive.")))
    return PositiveInt(val)


@_add_typed_validator
def _negative_int(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NegativeInt:
    val = _int(val, argname, **kwargs)
    if val >= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be negative.")))
    return NegativeInt(val)


@_add_typed_validator
def _non_zero_int(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NonZeroInt:
    val = _int(val, argname, **kwargs)
    if val == 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be zero.")))
    return NonZeroInt(val)


@_add_typed_validator
def _id(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> ID:
    """A numeric ID as in a database key.

    This is just a wrapper around `_positive_int`, to differentiate this
    semantically.
    """
    if val is None or isinstance(val, str) and not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    val = _positive_int(val, argname, **kwargs)
    return ID(_proto_id(val, argname, **kwargs))


@_add_typed_validator
def _creation_id(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> CreationID:
    """ID of an object which is currently under creation.

    This is just a wrapper around `_negative_int`, to differentiate this
    semantically.
    """
    if val is None or isinstance(val, str) and not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    val = _negative_int(val, argname, **kwargs)
    return CreationID(_proto_id(val, argname, **kwargs))


@_add_typed_validator
def _proto_id(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> ProtoID:
    """An object with a proto-id may already exist or is currently under creation.

    This implies that the id may either be positive or negative, but must not be zero.
    """
    if val is None or isinstance(val, str) and not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return ProtoID(_non_zero_int(val, argname, **kwargs))


@_add_typed_validator
def _partial_import_id(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> PartialImportID:
    """A numeric id or a negative int as a placeholder."""
    val = _int(val, argname, **kwargs)
    if val == 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be zero.")))
    return PartialImportID(val)


@_add_typed_validator
def _float(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
def _non_negative_float(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NonNegativeFloat:
    val = _float(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Must not be negative.")))
    return NonNegativeFloat(val)


@_add_typed_validator
def _decimal(
    val: Any, argname: Optional[str] = None, *, large: bool = False, **kwargs: Any,
) -> decimal.Decimal:
    """decimal.Decimal fitting into a `numeric` postgres column.

    :param large: specifies whether `numeric(8, 2)` or `numeric(11, 2)` is used
    """
    if isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise ValidationSummary(ValueError(argname, n_(
                "Invalid input for decimal number."))) from e
    if not isinstance(val, decimal.Decimal):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a decimal.Decimal.")))
    if not large and abs(val) >= 1e6:
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a million.")))
    if abs(val) >= 1e9:
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a billion.")))
    return val


@_add_typed_validator
def _non_negative_decimal(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NonNegativeDecimal:
    val = _decimal(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return NonNegativeDecimal(val)


@_add_typed_validator
def _non_negative_large_decimal(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> NonNegativeLargeDecimal:
    return NonNegativeLargeDecimal(
        _non_negative_decimal(val, argname, large=True, **kwargs))


@_add_typed_validator
def _positive_decimal(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> PositiveDecimal:
    val = _decimal(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(
            argname, n_("Transfer saldo is negative.")))
    return PositiveDecimal(val)


@_add_typed_validator
def _str_type(
    val: Any, argname: Optional[str] = None, *,
    zap: str = '', sieve: str = '', **kwargs: Any,
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
def _str(val: Any, argname: Optional[str] = None, **kwargs: Any) -> str:
    """ Like :py:class:`_str_type` (parameters see there),
    but mustn't be empty (whitespace doesn't count).
    """
    val = _str_type(val, argname, **kwargs)
    if not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return val


@_add_typed_validator
def _url(val: Any, argname: Optional[str] = None, **kwargs: Any) -> Url:
    """A string which is a valid url.

    We can not guarantee that the URL is actually valid, since the respective RFCs
    are not strictly respected. See also
    https://docs.python.org/3/library/urllib.parse.html#url-parsing-security
    """
    val = _str(val, argname, **kwargs)
    url = urllib.parse.urlparse(val)
    if not all([url.scheme, url.netloc, url.path]):
        raise ValidationSummary(ValueError(argname, n_("Malformed URL.")))
    return Url(urllib.parse.urlunparse(url))


@_add_typed_validator
def _shortname(val: Any, argname: Optional[str] = None, *,
               ignore_warnings: bool = False, **kwargs: Any) -> Shortname:
    """A string used as shortname with therefore limited length."""
    val = _str(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    if len(val) > _CONFIG["SHORTNAME_LENGTH"] and not ignore_warnings:
        raise ValidationSummary(
            ValidationWarning(argname, n_("Shortname is longer than %(len)s chars."),
                              {'len': str(_CONFIG["SHORTNAME_LENGTH"])}))
    return Shortname(val)


@_add_typed_validator
def _shortname_identifier(val: Any, argname: Optional[str] = None, *,
                          ignore_warnings: bool = False,
                          **kwargs: Any) -> ShortnameIdentifier:
    """A string used as shortname and as programmatically accessible identifier."""
    val = _identifier(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    val = _shortname(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    return ShortnameIdentifier(val)


@_add_typed_validator
def _shortname_restrictive_identifier(
        val: Any, argname: Optional[str] = None, *,
        ignore_warnings: bool = False,
        **kwargs: Any) -> ShortnameRestrictiveIdentifier:
    """A string used as shortname and as restrictive identifier"""
    val = _restrictive_identifier(val, argname, ignore_warnings=ignore_warnings,
                                  **kwargs)
    val = _shortname_identifier(val, argname, ignore_warnings=ignore_warnings,
                                **kwargs)
    return ShortnameRestrictiveIdentifier(val)


@_add_typed_validator
def _legacy_shortname(val: Any, argname: Optional[str] = None, *,
                      ignore_warnings: bool = False, **kwargs: Any) -> LegacyShortname:
    """A string used as shortname, but with increased but still limited length."""
    val = _str(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    if len(val) > _CONFIG["LEGACY_SHORTNAME_LENGTH"] and not ignore_warnings:
        raise ValidationSummary(
            ValidationWarning(argname, n_("Shortname is longer than %(len)s chars."),
                              {'len': str(_CONFIG["LEGACY_SHORTNAME_LENGTH"])}))
    return LegacyShortname(val)


@_add_typed_validator
def _bytes(
    val: Any, argname: Optional[str] = None, *,
    encoding: str = "utf-8", **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Mapping:  # type: ignore[type-arg] # type parameters would break this (for now)
    if not isinstance(val, Mapping):
        raise ValidationSummary(TypeError(argname, n_("Must be a mapping.")))
    return val


@_add_typed_validator
def _iterable(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Iterable:  # type: ignore[type-arg] # type parameters would break this (for now)
    if not isinstance(val, Iterable):
        raise ValidationSummary(TypeError(argname, n_("Must be an iterable.")))
    return val


@_add_typed_validator
def _sequence(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Sequence:  # type: ignore[type-arg] # type parameters would break this (for now)
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> EmptyDict:
    # TODO why do we not convert here but do so for _empty_list?
    if val != {}:
        raise ValidationSummary(
            ValueError(argname, n_("Must be an empty dict.")))
    return EmptyDict(val)


@_add_typed_validator
def _empty_list(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> EmptyList:
    val = list(_iterable(val, argname, **kwargs))
    if val:
        raise ValidationSummary(ValueError(argname, n_("Must be an empty list.")))
    return EmptyList(val)


@_add_typed_validator  # TODO use Union of Literal
def _realm(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Realm:
    """A realm in the sense of the DB."""
    val = _str(val, argname, **kwargs)
    if val not in ("session", "core", "cde", "event", "ml", "assembly"):
        raise ValidationSummary(ValueError(argname, n_("Not a valid realm.")))
    return Realm(val)


@_add_typed_validator
def _cdedbid(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> PrintableASCIIType:
    val = _str_type(val, argname, **kwargs)
    if not re.search(r'^[ -~]*$', val):
        raise ValidationSummary(ValueError(
            argname, n_("Must be printable ASCII.")))
    return PrintableASCIIType(val)


@_add_typed_validator
def _printable_ascii(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> PrintableASCII:
    """Like :py:func:`_printable_ascii_type` (parameters see there),
    but must not be empty (whitespace doesn't count).
    """
    val = _printable_ascii_type(val, argname, **kwargs)
    if not val:  # TODO leave strip here?
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return PrintableASCII(val)


@_add_typed_validator
def _identifier(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
        val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> CSVIdentifier:
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$', val):
        raise ValidationSummary(ValueError(argname, n_(
            "Must be comma separated identifiers.")))
    return CSVIdentifier(val)


@_add_typed_validator
def _token_string(
        val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> TokenString:
    val = _str(val, argname, **kwargs)
    if re.search(r'[\s()]', val):
        raise ValidationSummary(ValueError(argname, n_(
            "Must not contain whitespace or parentheses.")))
    return TokenString(val)


@_add_typed_validator
def _base64(
        val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Base64:

    val = _ALL_TYPED[str](val, argname, **kwargs)
    try:
        _ = base64.b64decode(val, b"-_", validate=True)
    except ValueError:
        raise ValidationSummary(ValueError(argname, n_(
            "Invalid Base64 string."))) from None

    return Base64(val)


@_add_typed_validator
def _anonymous_mesage(
        val: Any, argname: str = models_core.AnonymousMessageData.__qualname__,
        creation: bool = False, **kwargs: Any,
) -> AnonymousMessage:
    val = _mapping(val, argname, **kwargs)

    mandatory, optional = models_core.AnonymousMessageData.validation_fields(
        creation=creation)
    val = _examine_dictionary_fields(val, mandatory, optional, **kwargs)

    return AnonymousMessage(val)


# TODO manual handling of @_add_typed_validator inside decorator or storage?
@_add_typed_validator
def _list_of(
    val: Any, atype: type[T],
    argname: Optional[str] = None,
    *,
    _parse_csv: bool = False,
    _allow_empty: bool = True,
    **kwargs: Any,
) -> list[T]:
    """
    Apply another validator to all entries of of a list.

    The input may be a comma-separated string.
    """
    if isinstance(val, str) and _parse_csv:
        # TODO use default separator from config here?
        # TODO use escaped_split?
        # Skip emtpy entries which can be produced by JavaScript.
        val = [v for v in val.split(",") if v]
    # TODO raise ValueError if val is string and _parse_csv is False?
    val = _iterable(val, argname, **kwargs)
    vals: list[T] = []
    errs = ValidationSummary()
    for v in val:
        with errs:
            vals.append(_ALL_TYPED[atype](v, argname, **kwargs))
    if errs:
        raise errs

    if not _allow_empty and not vals:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))

    return vals


class ListValidator(Protocol[T]):
    def __call__(self, val: Any, argname: Optional[str] = None, **kargs: Any,
                 ) -> list[T]:
        ...


def make_list_validator(type_: type[T]) -> ListValidator[T]:

    @functools.wraps(_list_of)
    def list_validator(val: Any, argname: Optional[str] = None, **kwargs: Any,
                       ) -> list[T]:
        return _list_of(val, type_, argname, **kwargs)

    return list_validator


class PairValidator(Protocol[T_Co]):
    def __call__(self, val: Any, argname: Optional[str] = None, **kargs: Any,
                 ) -> tuple[T_Co, T_Co]:
        ...


def make_pair_validator(type_: type[T]) -> PairValidator[T]:

    @functools.wraps(_range)
    def pair_validator(val: Any, argname: Optional[str] = None, **kwargs: Any,
                       ) -> tuple[T, T]:
        return _range(val, type_, argname, **kwargs)

    return pair_validator


def _set_of(
    val: Any, atype: type[T], argname: Optional[str] = None, **kwargs: Any,
) -> set[T]:
    # TODO maybe disallow strings here (see also _list_of)
    val = _iterable(val, argname=argname, **kwargs)
    return {_ALL_TYPED[atype](v, argname, **kwargs) for v in val}


class SetValidator(Protocol[T]):
    def __call__(self, val: Any, argname: Optional[str] = None, **kwargs: Any,
                 ) -> set[T]:
        ...


def make_set_validator(type_: type[T]) -> SetValidator[T]:

    @functools.wraps(_set_of)
    def set_validator(val: Any, argname: Optional[str] = None, **kwargs: Any) -> set[T]:
        return _set_of(val, type_, argname, **kwargs)

    return set_validator


@_add_typed_validator
def _int_csv_list(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> IntCSVList:
    return IntCSVList(_list_of(val, int, argname, _parse_csv=True, **kwargs))


@_add_typed_validator
def _cdedbid_csv_list(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> CdedbIDList:
    """This deals with strings containing multiple cdedbids,
    like when they are returned from cdedbSearchPerson.
    """
    return CdedbIDList(_list_of(val, CdedbID, argname, _parse_csv=True, **kwargs))


@_add_typed_validator  # TODO split into Password and AdminPassword?
def _password_strength(
    val: Any, argname: Optional[str] = None, *,
    admin: bool = False, inputs: Optional[list[str]] = None, **kwargs: Any,
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

    results = cast(CdEDBObject, zxcvbn.zxcvbn(val, list(filter(None, inputs))))
    # if user is admin in any realm, require a score of 4. After
    # migration, everyone must change their password, so this is
    # actually enforced for admins of the old db. Afterwards,
    # meta admins are intended to do a password reset.
    if results['score'] < 2:
        feedback: list[str] = [results['feedback']['warning']]
        feedback.extend(results['feedback']['suggestions'][:2])
        for fb in filter(None, feedback):
            errors.append(ValueError(argname, fb))
        if not errors:
            # generate custom feedback
            _LOGGER.warning("No zxcvbn output feedback found.")
            errors.append(ValueError(argname, n_("Password too weak.")))

    if admin and results['score'] < 4:
        # TODO also include zxcvbn feedback here?
        errors.append(ValueError(argname, n_(
            "Password too weak for admin account.")))

    if errors:
        raise errors

    return PasswordStrength(val)


@_add_typed_validator
def _api_token_string(
        val: Any, argname: str = "api_token_string", **kwargs: Any,
) -> APITokenString:
    """Check if a string has the correct format to be a valid api token.

    Split the token into the droid name and the secret.
    """
    val = _printable_ascii(val, argname, **kwargs)
    try:
        droid_name, secret = models_droid.APIToken.parse_token_string(val)
        return APITokenString((droid_name, secret))
    except ValueError as e:
        raise ValidationSummary(ValueError(argname, *e.args)) from e


@_add_typed_validator
def _orga_token(
        val: Any, argname: str = "orga_token", *, creation: bool = False,
        **kwargs: Any,
) -> OrgaToken:
    val = _mapping(val, argname, **kwargs)

    mandatory, optional = models_droid.OrgaToken.validation_fields(creation=creation)
    val = _examine_dictionary_fields(
        val, mandatory, optional, **kwargs)

    errs = ValidationSummary()

    timestamp = now()
    if 'etime' in val:
        if val['etime'] and val['etime'] <= timestamp:
            with errs:
                raise ValidationSummary(ValueError(
                    'etime', n_("Expiration time must be in the future.")))

    if errs:
        raise errs

    return OrgaToken(val)


@_add_typed_validator
def _email(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> Email:
    """We accept only a subset of valid email addresses since implementing the
    full standard is horrendous. Also we normalize emails to lower case.
    """
    val = _printable_ascii(val, argname, **kwargs)
    # strip address and normalize to lower case
    val = val.strip().lower()
    if not re.search(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$', val):
        raise ValidationSummary(ValueError(
            argname, n_("Must be a valid email address.")))
    return Email(val)


@_add_typed_validator
def _email_local_part(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    'pronouns': NoneType,
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': NoneType,
    'telephone': NoneType,
    'mobile': NoneType,
    'address_supplement': NoneType,
    'address': NoneType,
    'show_address': bool,
    'postal_code': NoneType,
    'location': NoneType,
    'country': NoneType,
    'birth_name': NoneType,
    'address_supplement2': NoneType,
    'address2': NoneType,
    'show_address2': bool,
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
    'honorary_member': NoneType,
    'decided_search': NoneType,
    'bub_search': NoneType,
    'foto': NoneType,
    'paper_expuls': NoneType,
    'donation': NoneType,
}

PERSONA_CDE_CREATION: Mapping[str, Any] = {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': const.Genders,
    'pronouns': Optional[str],
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'show_address': bool,
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'show_address2': bool,
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
    'honorary_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    # 'foto': Optional[str], # No foto -- this is another special
    'paper_expuls': bool,
    'donation': NonNegativeDecimal,
}

PERSONA_EVENT_CREATION: Mapping[str, Any] = {
    'title': Optional[str],
    'name_supplement': Optional[str],
    'gender': const.Genders,
    'pronouns': Optional[str],
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
}

PERSONA_FULL_CREATION: Mapping[str, dict[str, Any]] = {
    'ml': {**PERSONA_BASE_CREATION},
    'assembly': {**PERSONA_BASE_CREATION},
    'event': {**PERSONA_BASE_CREATION, **PERSONA_EVENT_CREATION},
    'cde': {**PERSONA_BASE_CREATION, **PERSONA_CDE_CREATION,
            'is_member': bool, 'is_searchable': bool},
}

PERSONA_COMMON_FIELDS: dict[str, Any] = {
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
    'is_auditor': bool,
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
    'pronouns': Optional[str],
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Optional[Phone],
    'mobile': Optional[Phone],
    'address_supplement': Optional[str],
    'address': Optional[str],
    'show_address': bool,
    'postal_code': Optional[PrintableASCII],
    'location': Optional[str],
    'country': Optional[Country],
    'birth_name': Optional[str],
    'address_supplement2': Optional[str],
    'address2': Optional[str],
    'show_address2': bool,
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
    'donation': NonNegativeDecimal,
    'trial_member': bool,
    'honorary_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    'foto': Optional[str],
    'paper_expuls': Optional[bool],
}


@_add_typed_validator
def _persona(
    val: Any, argname: str = "persona", *,
    creation: bool = False, transition: bool = False, **kwargs: Any,
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
        temp.update({'is_archived': False, 'is_purged': False})
        temp.update({k: False for k in ADMIN_KEYS})
        roles = extract_roles(temp)
        optional_fields: TypeMapping = {}
        mandatory_fields: dict[str, Any] = {**PERSONA_TYPE_FIELDS,
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
        # promoting to cde realm may be used to grant a trial membership.
        #  since trial member implies is_member, we need to allow the latter here
        if val.get("is_cde_realm"):
            optional_fields["is_member"] = bool
    else:
        mandatory_fields = {'id': ID}
        optional_fields = PERSONA_COMMON_FIELDS
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if "is_member" in val and "trial_member" in val:
        if val["trial_member"] and not val["is_member"]:
            errs.append(ValueError("trial_member", n_(
                "Trial membership requires membership.")))
    if "is_member" in val and "honorary_member" in val:
        if val["honorary_member"] and not val["is_member"]:
            errs.append(ValueError("honorary_member", n_(
                "Honorary membership requires membership.")))
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> BatchAdmissionEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: dict[str, Any] = {
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


# TODO move this above _persona stuff?
@_add_typed_validator
def _date(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
def _birthday(val: Any, argname: Optional[str] = None, **kwargs: Any) -> Birthday:
    if not val:
        val = datetime.date.min
    val = _date(val, argname=argname, **kwargs)
    if now().date() < val:
        raise ValidationSummary(ValueError(
            argname, n_("A birthday must be in the past.")))
    return Birthday(val)


@_add_typed_validator
def _datetime(
    val: Any, argname: Optional[str] = None, *,
    default_date: Optional[datetime.date] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> SingleDigitInt:
    """Like _int, but between +9 and -9."""
    val = _int(val, argname, **kwargs)
    if not -9 <= val <= 9:
        raise ValidationSummary(ValueError(
            argname, n_("More than one digit.")))
    return SingleDigitInt(val)


@_add_typed_validator
def _phone(
    val: Any, argname: Optional[str] = None, *, ignore_warnings: bool = False,
    **kwargs: Any,
) -> Phone:
    raw = _printable_ascii(val, argname, **kwargs, ignore_warnings=ignore_warnings)

    try:
        # default to german if no region is provided
        phone: phonenumbers.PhoneNumber = phonenumbers.parse(raw, region="DE")
    except phonenumbers.NumberParseException as npe:
        # error types taken from comments in source code of NumberParseException
        if npe.error_type == npe.INVALID_COUNTRY_CODE:
            msg = n_("Invalid country code")
        elif npe.error_type == npe.NOT_A_NUMBER:
            msg = n_("This is not a phone number.")
        elif npe.error_type in (npe.TOO_SHORT_AFTER_IDD, npe.TOO_SHORT_NSN):
            msg = n_("Phone number too short")
        elif npe.error_type == npe.TOO_LONG:
            msg = n_("Phone number too long")
        else:  # should never happen
            msg = n_("Phone number can not be parsed.")
        raise ValidationSummary(ValueError(argname, msg)) from None
    if not phonenumbers.is_valid_number(phone) and not ignore_warnings:
        msg = n_("Phone number seems to be not valid.")
        raise ValidationSummary(ValidationWarning(argname, msg))

    # handle the phone number as normalized string internally
    phone_str = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)

    return Phone(phone_str)


_GERMAN_POSTAL_CODES: set[str] = set()


@_add_typed_validator
def _german_postal_code(
    val: Any, argname: Optional[str] = None, *,
    aux: str = "", ignore_warnings: bool = False, **kwargs: Any,
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
        if not _GERMAN_POSTAL_CODES:
            repo_path: pathlib.Path = _CONFIG['REPOSITORY_PATH']
            _GERMAN_POSTAL_CODES.update(
                e['plz'] for e in csv.DictReader(
                    (
                        repo_path / "tests" / "ancillary_files" / "plz.csv"
                    ).read_text().splitlines(),
                    delimiter=',',
                )
            )
        if val not in _GERMAN_POSTAL_CODES and not ignore_warnings:
            raise ValidationSummary(ValidationWarning(argname, msg))
    return GermanPostalCode(val)


@_add_typed_validator
def _country(
    val: Any, argname: Optional[str] = None, *, ignore_warnings: bool = False,
    **kwargs: Any,
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
    'persona_id': Optional[ID],
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
                               'pcourse_id': Optional[ID]}


@_add_typed_validator
def _genesis_case(
    val: Any, argname: str = "genesis_case", *,
    creation: bool = False, ignore_warnings: bool = False, **kwargs: Any,
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
        raise ValidationSummary(ValueError('realm', n_("Must specify realm.")))

    if creation:
        mandatory_fields = dict(GENESIS_CASE_COMMON_FIELDS,
                                **additional_fields)
        # Birth name is not allowed on creation to avoid mistakes
        if 'birth_name' in mandatory_fields:
            del mandatory_fields['birth_name']
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = dict(GENESIS_CASE_COMMON_FIELDS,
                               **GENESIS_CASE_OPTIONAL_FIELDS,
                               **additional_fields)

    # allow_superflous=True will result in superfluous keys being removed.
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, allow_superfluous=True, **kwargs)

    errs = ValidationSummary()

    with errs:
        if val.get('postal_code'):
            postal_code = _german_postal_code(
                val['postal_code'], 'postal_code', aux=val.get('country', ""),
                ignore_warnings=ignore_warnings, **kwargs)
            val['postal_code'] = postal_code

        if birthday := val.get('birthday'):
            if (now().date() - birthday) < datetime.timedelta(days=365):
                if not ignore_warnings:
                    raise ValidationSummary(ValidationWarning(
                        'birthday',
                        n_("Birthday was less than a year ago."
                           " Please check the birth year."),
                    ))

    if errs:
        raise errs

    return GenesisCase(val)


PRIVILEGE_CHANGE_COMMON_FIELDS: TypeMapping = {
    'persona_id': ID,
    'submitted_by': ID,
    'status': const.PrivilegeChangeStati,
    'notes': str,
}

PRIVILEGE_CHANGE_OPTIONAL_FIELDS: TypeMapping = {
    k: Optional[bool] for k in ADMIN_KEYS  # type: ignore[misc]
}


@_add_typed_validator
def _privilege_change(
    val: Any, argname: str = "privilege_change", **kwargs: Any,
) -> PrivilegeChange:

    val = _mapping(val, argname, **kwargs)

    val = _examine_dictionary_fields(
        val, PRIVILEGE_CHANGE_COMMON_FIELDS,
        PRIVILEGE_CHANGE_OPTIONAL_FIELDS, **kwargs)

    return PrivilegeChange(val)


# TODO also move these up?
@_add_typed_validator
def _input_file(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, *,
    encoding: str = "utf-8-sig", **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, *,
    file_storage: bool = True, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, *,
    file_storage: bool = True, **kwargs: Any,
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
    val: Any, argname: str = "pair", **kwargs: Any,
) -> tuple[int, int]:
    """Validate a pair of integers."""

    val: list[int] = _list_of(val, int, argname, **kwargs)

    try:
        a, b = val  # pylint: disable=unbalanced-tuple-unpacking
    except ValueError as e:
        raise ValidationSummary(ValueError(
            argname, n_("Must contain exactly two elements."))) from e

    # noinspection PyRedundantParentheses
    return (a, b)


@_add_typed_validator
def _period(
    val: Any, argname: str = "period", **kwargs: Any,
) -> Period:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    prefix_map = {
        'billing': ('state', 'done', 'count'),
        'ejection': ('state', 'done', 'count', 'balance'),
        'exmember': ('state', 'done', 'balance', 'count'),
        'balance': ('state', 'done', 'trialmembers', 'total'),
        'archival_notification': ('state', 'done', 'count'),
        'archival': ('state', 'done', 'count'),
    }
    type_map: TypeMapping = {
        'state': Optional[ID],  # type: ignore[dict-item]
        'done': datetime.datetime, 'count': NonNegativeInt,
        'trialmembers': NonNegativeInt, 'total': NonNegativeDecimal,
        'balance': NonNegativeDecimal, 'exmembers': NonNegativeDecimal,
    }

    optional_fields = {
        f"{pre}_{suf}": type_map[suf]
        for pre, suffixes in prefix_map.items() for suf in suffixes
    }

    return Period(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


@_add_typed_validator
def _expuls(
        val: Any, argname: str = "expuls", **kwargs: Any,
) -> ExPuls:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    optional_fields: TypeMapping = {
        'addresscheck_state': Optional[ID],  # type: ignore[dict-item]
        'addresscheck_done': datetime.datetime,
        'addresscheck_count': NonNegativeInt,
    }
    return ExPuls(_examine_dictionary_fields(
        val, {'id': ID}, optional_fields, **kwargs))


LASTSCHRIFT_COMMON_FIELDS: Mapping[str, Any] = {
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
    creation: bool = False, **kwargs: Any,
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
    mandatory_fields: TypeMapping = {
        'persona_id': int,
        'registration_id': Optional[int],  # type: ignore[dict-item]
        'amount': decimal.Decimal,
        'date': datetime.date,
    }
    return MoneyTransferEntry(_examine_dictionary_fields(
        val, mandatory_fields, {}, **kwargs))


# TODO move above
@_add_typed_validator
def _iban(
    val: Any, argname: str = "iban", **kwargs: Any,
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
                 "exp": IBAN_LENGTHS[country_code]},
            ))
        temp = ''.join(c if c in string.digits else str(10 + ord(c) - ord('A'))
                       for c in bban + country_code + check_digits)
        if int(temp) % 97 != 1:
            errs.append(ValueError(argname, n_("Invalid checksum.")))

    if errs:
        raise errs

    return IBAN(val)


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
    val: Any, argname: str = "sepa_transactions", **kwargs: Any,
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
                if len(entry[attribute],
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
    val: Any, argname: str = "sepa_meta", **kwargs: Any,
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
        if validator is str:
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, keys: list[str], argname: str = "meta_info", **kwargs: Any,
) -> MetaInfo:
    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        key: Optional[str]  # type: ignore[misc]
        for key in keys
    }
    val = _examine_dictionary_fields(
        val, {}, optional_fields, **kwargs)

    return MetaInfo(val)


PAST_EVENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'shortname': Shortname,
    'institution': const.PastInstitutions,
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
    creation: bool = False, **kwargs: Any,
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
    'institution': const.PastInstitutions,
    'description': Optional[str],
    # Event shortnames do not actually need to be that short.
    'shortname': Identifier,
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
    'field_definition_notes': Optional[str],
    'is_participant_list_visible': bool,
    'is_course_assignment_visible': bool,
    'is_cancelled': bool,
    'iban': Optional[IBAN],
    'mail_text': Optional[str],
    'registration_text': Optional[str],
    'orga_address': Optional[Email],
    'participant_info': Optional[str],
    'lodge_field_id': Optional[ID],
    'website_url': Optional[Url],
    'notify_on_registration': const.NotifyOnRegistration,
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

EVENT_CREATION_OPTIONAL_FIELDS: TypeMapping = {
    'lodgement_groups': Mapping,
    'fees': Mapping,
}


def _optional_object_mapping_helper(
    val_dict: Mapping[Any, Any], atype: type[T], argname: str,
    creation_only: bool, **kwargs: Any,
) -> Mapping[int, Optional[T]]:
    """Helper to validate a `CdEDBOptionalMap` of a given type.

    The map may contain positive or negative IDs. Positive IDs may be either None,
    indicating an existing object should be deleted, or a partial dataset containing
    changes to an existing object. Negative IDs should contain a full dataset for
    creation of a new object.

    :param creation_only: If True, only allow negative IDs.
    """
    ret = {}
    errs = ValidationSummary()
    for anid, val in val_dict.items():
        with errs:
            anid = _ALL_TYPED[PartialImportID](anid, argname, **kwargs)
            creation = anid < 0
            if creation_only and not creation:
                raise ValidationSummary(ValueError(
                    argname, n_("Only creation allowed.")))
            if creation:
                val = _ALL_TYPED[atype](
                    val, argname, creation=creation, id_=anid, **kwargs)
            else:
                val = _ALL_TYPED[Optional[atype]](  # type: ignore[index]
                    val, argname, creation=creation, id_=anid, **kwargs)
            ret[anid] = val

    if errs:
        raise errs
    return ret


@_add_typed_validator
def _event(
    val: Any, argname: str = "event", *,
    creation: bool = False, **kwargs: Any,
) -> Event:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = {**EVENT_COMMON_FIELDS}
        optional_fields = {**EVENT_OPTIONAL_FIELDS, **EVENT_CREATION_OPTIONAL_FIELDS}
    else:
        mandatory_fields = {}
        optional_fields = {'id': ID, **EVENT_COMMON_FIELDS, **EVENT_OPTIONAL_FIELDS}
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()

    configuration_fields = {k: v for k, v in val.items() if k in EVENT_EXPOSED_FIELDS}
    if configuration_fields:
        if creation:
            kwargs['current'] = None
        with errs:
            configuration_fields = _ALL_TYPED[SerializedEventConfiguration](
                configuration_fields, argname, creation=creation, **kwargs)
            val.update(configuration_fields)

    if 'orgas' in val:
        orgas = set()
        for anid in val['orgas']:
            with errs:
                v = _id(anid, 'orgas', **kwargs)
                orgas.add(v)
        val['orgas'] = orgas

    if 'parts' in val:
        with errs:
            val['parts'] = _optional_object_mapping_helper(
                val['parts'], EventPart, 'parts', creation_only=creation, **kwargs)

    if 'fields' in val:
        with errs:
            val['fields'] = _optional_object_mapping_helper(
                val['fields'], EventField, 'fields', creation_only=creation, **kwargs)

    if 'lodgement_groups' in val:
        with errs:
            val['lodgement_groups'] = _optional_object_mapping_helper(
                val['lodgement_groups'], LodgementGroup, 'lodgement_groups',
                creation_only=creation, nested_creation=creation, **kwargs)

    if 'fees' in val:
        with errs:
            val['fees'] = _optional_object_mapping_helper(
                val['fees'], EventFee, 'fees', creation_only=creation, event=val,
                questionnaire={}, **kwargs)

    if errs:
        raise errs

    return Event(val)


EVENT_PART_CREATION_MANDATORY_FIELDS: TypeMapping = {
    'title': str,
    'shortname': TokenString,
    'part_begin': datetime.date,
    'part_end': datetime.date,
}

EVENT_PART_CREATION_OPTIONAL_FIELDS: TypeMapping = {
    'waitlist_field_id': Optional[ID],  # type: ignore[dict-item]
    'camping_mat_field_id': Optional[ID],  # type: ignore[dict-item]
    'tracks': Mapping,
}

EVENT_PART_COMMON_FIELDS: TypeMapping = {
    **EVENT_PART_CREATION_MANDATORY_FIELDS,
    **EVENT_PART_CREATION_OPTIONAL_FIELDS,
}

EVENT_PART_OPTIONAL_FIELDS: TypeMapping = {
}


@_add_typed_validator
def _event_part(
    val: Any, argname: str = "event_part", *,
    creation: bool = False, **kwargs: Any,
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
                creation = anid < 0
                try:
                    if creation:
                        track = _ALL_TYPED[EventTrack](
                            track, 'tracks', creation=True, **kwargs)
                    else:
                        track = _ALL_TYPED[Optional[EventTrack]](  # type: ignore[index]
                            track, 'tracks', **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newtracks[anid] = track
        val['tracks'] = newtracks

    if errs:
        raise errs

    return EventPart(val)


EVENT_PART_GROUP_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
    'constraint_type': const.EventPartGroupType,
    'notes': Optional[str],  # type: ignore[dict-item]
    'part_ids': list[ID],
}


@_add_typed_validator
def _event_part_group(
    val: Any, argname: str = "part_group", *,
    creation: bool = False, **kwargs: Any,
) -> EventPartGroup:
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = {**EVENT_PART_GROUP_COMMON_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = {**EVENT_PART_GROUP_COMMON_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    return EventPartGroup(val)


_create_optional_mapping_validator(EventPartGroup, EventPartGroupSetter)


EVENT_TRACK_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
    'num_choices': NonNegativeInt,
    'min_choices': NonNegativeInt,
    'sortkey': int,
    'course_room_field_id': Optional[ID],  # type: ignore[dict-item]
}


@_add_typed_validator
def _event_track(
    val: Any, argname: str = "tracks", *,
    creation: bool = False, **kwargs: Any,
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
        mandatory_fields = {}
        optional_fields = {**EVENT_TRACK_COMMON_FIELDS}

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if ('num_choices' in val and 'min_choices' in val
            and val['min_choices'] > val['num_choices']):
        raise ValidationSummary(ValueError("min_choices", n_(
            "Must be less or equal than total Course Choices.")))

    return EventTrack(val)


EVENT_TRACK_GROUP_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': Shortname,
    'constraint_type': const.CourseTrackGroupType,
    'notes': Optional[str],  # type: ignore[dict-item]
    'track_ids': list[ID],
    'sortkey': int,
}


@_add_typed_validator
def _event_track_group(
    val: Any, argname: str = "track_group", *,
    creation: bool = False, **kwargs: Any,
) -> EventTrackGroup:
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = {**EVENT_TRACK_GROUP_COMMON_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {}
        optional_fields = {**EVENT_TRACK_GROUP_COMMON_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    if 'track_ids' in val:
        if not val['track_ids']:
            raise ValidationSummary(
                ValueError('track_ids', n_("Must not be empty.")))

    return EventTrackGroup(val)


_create_optional_mapping_validator(EventTrackGroup, EventTrackGroupSetter)


@_add_typed_validator
def _event_field(
    val: Any, argname: str = "event_field", *, field_name: Optional[str] = None,
    creation: bool = False, **kwargs: Any,
) -> EventField:
    """
    :param field_name: If given, set the field name of the field to this.
        This is handy for creating new fields during the questionnaire import,
        where the field name serves as the key and thus is not part of the dict itself.
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    val = _mapping(val, argname, **kwargs)
    val = dict(val)

    if field_name is not None:
        val["field_name"] = field_name
    if creation:
        if not val.get("title"):
            val["title"] = val.get("field_name")

    mandatory_fields, optional_fields = models_event.EventField.validation_fields(
        creation=creation)

    if 'entries' in optional_fields:
        optional_fields['entries'] = Any  # type: ignore[assignment]

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if not val.get("entries", True):
        val["entries"] = None
    if "entries" in val and val["entries"] is not None:
        if isinstance(val["entries"], str):
            val["entries"] = dict(
                [y.strip() for y in x.split(';', 1)] for x in val["entries"].split('\n')
            )
        elif isinstance(val['entries'], list):
            with errs:
                try:
                    val['entries'] = dict(val['entries'])
                except ValueError as e:
                    raise ValidationSummary(ValueError(
                        'entries', n_("Could not convert to mapping."))) from e
        try:
            oldentries = _mapping(val['entries'], 'entries', **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            entries = {}
            for idx, entry in enumerate(oldentries.items()):
                value, description = entry
                # Validate value according to type and use the opportunity
                # to normalize the value by transforming it back to string
                try:
                    value = _by_field_datatype(value, "entries", kind=val.get(
                        "kind", FieldDatatypes.str), **kwargs)
                    description = _str(description, "entries", **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    if value in entries:
                        errs.append(ValueError("entries", n_("Duplicate value.")))
                    else:
                        entries[value] = description
            val["entries"] = entries

    if errs:
        raise errs

    return EventField(val)


_create_optional_mapping_validator(EventFee, EventFeeSetter)


@_create_dataclass_validator(models_event.EventFee, EventFee)
def _event_fee(
        val: Any, argname: str, *,
        id_: ProtoID,
        event: CdEDBObject,
        personalized: Optional[bool] = None,
        **kwargs: Any,
) -> EventFee:
    errs = ValidationSummary()
    current = event['fees'].get(id_)
    if current is not None and personalized is None:
        personalized = (current['amount'] is None or current['condition'] is None)

    if personalized is not None:
        if personalized:
            if val.get('amount') is not None:
                errs.append(ValueError(
                    'amount', n_("Cannot set amount for personalized fee.")))
            if val.get('condition') is not None:
                errs.append(ValueError(
                    'condition', n_("Cannot set condition for personalized fee.")))
        else:
            if 'amount' in val and val['amount'] is None:
                errs.append(ValueError(
                    'amount', n_("Cannot unset amount for conditional fee.")))
            if 'condition' in val and val['condition'] is None:
                errs.append(ValueError(
                    'condition', n_("Cannot unset condition for conditional fee.")))
    else:
        if (val['amount'] is None) != (val['condition'] is None):
            for k in ('amount', 'condition'):
                errs.append(ValueError(
                    k, n_("Cannot have amount without condition or vice versa.")))
    if errs:
        raise errs

    return cast(EventFee, val)


@_add_typed_validator
def _event_fee_condition(
    val: Any, argname: str = "event_fee_condition", *,
    event: CdEDBObject,
    questionnaire: dict[const.QuestionnaireUsages, list[CdEDBObject]],
    **kwargs: Any,
) -> EventFeeCondition:

    val = _str(val, argname, **kwargs)

    additional_questionnaire_fields = {
        row['field_id'] for row in questionnaire.get(
            const.QuestionnaireUsages.additional, [])
        if row['field_id']
    }
    field_names = {
        f['field_name'] for f in event.get('fields', {}).values()
        if f['association'] == const.FieldAssociations.registration
           and f['kind'] == const.FieldDatatypes.bool
           and f.get('id') not in additional_questionnaire_fields
    }
    part_names = {p['shortname'] for p in event['parts'].values()}

    try:
        parse_result = fcp_parsing.parse(val)
        fcp_evaluation.check(parse_result, field_names, part_names)
    except Exception as e:
        raise ValidationSummary(ValueError(argname, e.args[-1])) from e

    return EventFeeCondition(fcp_roundtrip.serialize(parse_result))


PAST_COURSE_COMMON_FIELDS: Mapping[str, Any] = {
    'nr': str,
    'title': str,
    'description': Optional[str],
}


@_add_typed_validator
def _past_course(
    val: Any, argname: str = "past_course", *,
    creation: bool = False, **kwargs: Any,
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
    'is_visible': bool,
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
    creation: bool = False, **kwargs: Any,
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
    'checkin': Optional[datetime.datetime],
    'fields': Mapping,
}


@_add_typed_validator
def _registration(
    val: Any, argname: str = "registration", *,
    creation: bool = False, **kwargs: Any,
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
                part = _ALL_TYPED[Optional[RegistrationPart]](  # type: ignore[index]
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
                track = _ALL_TYPED[Optional[RegistrationTrack]](  # type: ignore[index]
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
    val: Any, argname: str = "registration_part", **kwargs: Any,
) -> RegistrationPart:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'status': const.RegistrationPartStati,
        'lodgement_id': Optional[ID],  # type: ignore[dict-item]
        'is_camping_mat': bool,
    }
    return RegistrationPart(_examine_dictionary_fields(
        val, {}, optional_fields, **kwargs))


# TODO make type of kwargs to be bools only?
@_add_typed_validator
def _registration_track(
        val: Any, argname: str = "registration_track", **kwargs: Any,
) -> RegistrationTrack:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'course_id': Optional[ID],  # type: ignore[dict-item]
        'course_instructor': Optional[ID],  # type: ignore[dict-item]
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
    fields: dict[int, models_event.EventField],
    association: FieldAssociations, **kwargs: Any,
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
    datatypes = {
        const.FieldDatatypes.str: Optional[str],
        const.FieldDatatypes.bool: Optional[bool],
        const.FieldDatatypes.int: Optional[int],
        const.FieldDatatypes.float: Optional[float],
        const.FieldDatatypes.date: Optional[datetime.date],
        const.FieldDatatypes.datetime: Optional[datetime.datetime],
        const.FieldDatatypes.non_negative_int: Optional[NonNegativeInt],
        const.FieldDatatypes.non_negative_float: Optional[NonNegativeFloat],
        const.FieldDatatypes.phone: Optional[str],
    }
    optional_fields: TypeMapping = {
        str(field.field_name): datatypes[field.kind]  # type: ignore[misc]
        for field in fields.values() if field.association == association
    }

    val = _examine_dictionary_fields(
        val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    lookup: dict[str, int] = {v.field_name: k for k, v in fields.items()}
    for field in val:  # pylint: disable=consider-using-dict-items
        field_id = lookup[field]
        entries = fields[field_id].entries
        if entries is not None and val[field] is not None:
            if not any(str(raw[field]) == x for x, _ in entries.items()):
                errs.append(ValueError(
                    field, n_("Entry not in definition list.")))
    if errs:
        raise errs

    return EventAssociatedFields(val)


@_add_typed_validator
def _fee_booking_entry(val: Any, argname: str = "fee_booking_entry",
                       **kwargs: Any) -> FeeBookingEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: dict[str, Any] = {
        'registration_id': int,
        'date': datetime.date,
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
    creation: bool = False, nested_creation: bool = False, **kwargs: Any,
) -> LodgementGroup:
    """
    :param creation: If ``True`` test the data set for fitness for creation
        of a new entity.
    :param nested_creation: If ``True`` do not require an event_id for creation,
        because the event is being created at the same time as the group.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(LODGEMENT_GROUP_FIELDS)
        if not nested_creation:
            mandatory_fields['event_id'] = ID
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
    'group_id': ID,
}

LODGEMENT_OPTIONAL_FIELDS: TypeMapping = {
    'fields': Mapping,
}


@_add_typed_validator
def _lodgement(
    val: Any, argname: str = "lodgement", *,
    creation: bool = False, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, *, kind: FieldDatatypes, **kwargs: Any,
) -> ByFieldDatatype:
    kind = FieldDatatypes(kind)
    # using Any seems fine, otherwise this would need a big Union
    val: Any = _ALL_TYPED[
        Optional[VALIDATOR_LOOKUP[kind.name]]  # type: ignore[index]
    ](val, argname, **kwargs)

    if kind in {FieldDatatypes.date, FieldDatatypes.datetime}:
        val = val.isoformat()
    else:
        val = str(val)

    return ByFieldDatatype(val)


QUESTIONNAIRE_ROW_MANDATORY_FIELDS: TypeMapping = {
    'title': Optional[str],  # type: ignore[dict-item]
    'info': Optional[str],  # type: ignore[dict-item]
    'input_size': Optional[int],  # type: ignore[dict-item]
    'readonly': Optional[bool],  # type: ignore[dict-item]
    'default_value': Optional[str],  # type: ignore[dict-item]
}


def _questionnaire_row(
    val: Any, argname: str = "questionnaire_row", *,
    field_definitions: CdEDBObjectMap,
    fees_by_field: Mapping[int, set[int]],
    kind: Optional[const.QuestionnaireUsages] = None,
    **kwargs: Any,
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
    if kind:
        if 'kind' in value:
            if value['kind'] != kind:
                msg = n_("Incorrect kind for this part of the questionnaire")
                errs.append(ValueError(argname_prefix + 'kind', msg))
        else:
            value['kind'] = kind
    elif 'kind' in value:
        kind = value['kind']
    else:
        errs.append(ValueError(argname_prefix + 'kind', n_("No kind specified.")))
        raise errs
    assert kind is not None

    field_definitions = {
        field_id: field for field_id, field in field_definitions.items()
        if field['association'] == const.FieldAssociations.registration
           and (kind.allow_fee_condition() or not fees_by_field.get(field_id))
    }
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
            raise ValidationSummary(KeyError(
                argname_prefix + 'default_value', n_("Invalid field.")))
        if value['default_value']:
            value['default_value'] = _by_field_datatype(
                value['default_value'], "default_value",
                kind=field.get('kind', FieldDatatypes.str), **kwargs)

    field_id = value['field_id']
    value['readonly'] = bool(value['readonly']) if field_id else None
    if value['readonly'] and not kind.allow_readonly():
        msg = n_("Registration questionnaire rows may not be readonly.")
        errs.append(ValueError(argname_prefix + 'readonly', msg))

    if errs:
        raise errs

    return QuestionnaireRow(value)


@_add_typed_validator
def _questionnaire(
    val: Any, argname: str = "questionnaire", *,
    field_definitions: CdEDBObjectMap,
    fees_by_field: Mapping[int, set[int]],
    **kwargs: Any,
) -> Questionnaire:

    val = _mapping(val, argname, **kwargs)

    errs = ValidationSummary()
    ret: dict[int, list[QuestionnaireRow]] = {}
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
                        value, row_argname, field_definitions=field_definitions,
                        fees_by_field=fees_by_field, kind=k, **kwargs)
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
    val: Any, argname: str = "json", **kwargs: Any,
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
    val: Any, argname: str = "serialized_event_upload", **kwargs: Any,
) -> SerializedEventUpload:
    """Check an event data set for import after offline usage."""
    # TODO provide docstrings in more validators

    val = _input_file(val, argname, **kwargs)

    val = _json(val, argname, **kwargs)

    return SerializedEventUpload(_serialized_event(val, argname, **kwargs))


@_add_typed_validator
def _serialized_event(
    val: Any, argname: str = "serialized_event", **kwargs: Any,
) -> SerializedEvent:
    """Check an event data set for import after offline usage."""
    # TODO why does this have the same docstring as the one above

    # First a basic check
    val = _mapping(val, argname, **kwargs)

    if 'kind' not in val or val['kind'] != "full":
        raise ValidationSummary(
            KeyError(argname, n_("Only full exports are supported.")))

    mandatory_fields: TypeMapping = {
        'EVENT_SCHEMA_VERSION': tuple[int, int],
        'kind': str,
        'id': ID,
        'timestamp': datetime.datetime,
    }
    mandatory_tables: TypeMapping = {
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
        'event.event_fees': Mapping,
        'event.personalized_fees': Mapping,
        'event.stored_queries': Mapping,
    }
    optional_tables: TypeMapping = {
        'core.personas': Mapping,
        'event.part_groups': Mapping,
        'event.part_group_parts': Mapping,
        'event.track_groups': Mapping,
        'event.track_group_tracks': Mapping,
        models_droid.OrgaToken.database_table: Mapping,
    }
    val = _examine_dictionary_fields(
        val, dict(collections.ChainMap(mandatory_fields, mandatory_tables)),
        optional_tables, **kwargs)

    if val['EVENT_SCHEMA_VERSION'] != EVENT_SCHEMA_VERSION:
        raise ValidationSummary(ValueError(
            argname, n_("Schema version mismatch.")))

    # Second a thorough investigation
    #
    # We reuse the existing validators, but have to augment them since the
    # data looks a bit different.
    # TODO replace the functions with types
    table_validators: Mapping[str, Callable[..., Any]] = {
        'event.events': functools.partial(
            _event, current={}, skip_field_validation=True),
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
                          'submitted_by': ID, 'event_id': Optional[ID],  # type: ignore[dict-item]
                          'persona_id': Optional[ID],  # type: ignore[dict-item]
                          'change_note': Optional[str]}),  # type: ignore[dict-item]
        'event.orgas': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID, 'persona_id': ID}),
        'event.field_definitions': _augment_dict_validator(
            _event_field, {'id': ID, 'event_id': ID, 'title': str,
                           'field_name': RestrictiveIdentifier,
                           'association': const.FieldAssociations}),
        'event.lodgement_groups': _augment_dict_validator(
            _lodgement_group, {'event_id': ID}),
        'event.lodgements': _augment_dict_validator(
            _lodgement, {'event_id': ID}),
        'event.registrations': _augment_dict_validator(
            _registration, {'event_id': ID, 'persona_id': ID,
                            'is_member': bool,
                            'amount_owed': NonNegativeDecimal,
                            # allow amount_paid and payment for better UX, we check
                            # inside the import that they have not changed
                            'amount_paid': NonNegativeDecimal,
                            'payment': Optional[datetime.date]}),   # type: ignore[dict-item]
        'event.registration_parts': _augment_dict_validator(
            _registration_part, {'id': ID, 'part_id': ID,
                                 'registration_id': ID}),
        'event.registration_tracks': _augment_dict_validator(
            _registration_track, {'id': ID, 'track_id': ID,
                                  'registration_id': ID}),
        'event.course_choices': _augment_dict_validator(
            _empty_dict, {'id': ID, 'course_id': ID, 'track_id': ID,
                          'registration_id': ID, 'rank': int}),
        # Is it easier to throw away broken ones at the end of the import.
        'event.questionnaire_rows': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID, 'title': Optional[str],  # type: ignore[dict-item]
                          'info': Optional[str], 'input_size': Optional[str],  # type: ignore[dict-item]
                          'readonly': Optional[bool], 'default_value': Optional[str],  # type: ignore[dict-item]
                          'field_id': Optional[ID], 'kind': const.QuestionnaireUsages,  # type: ignore[dict-item]
                          'pos': int}),
        'event.event_fees': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID,
                          'kind': const.EventFeeType, 'title': str,
                          'notes': Optional[str],  # type: ignore[dict-item]
                          'condition': Optional[str],  # type: ignore[dict-item]
                          'amount': Optional[decimal.Decimal],  # type: ignore[dict-item]
                          }),
        'event.personalized_fees': _augment_dict_validator(
            _empty_dict, {'id': ID, 'fee_id': ID, 'registration_id': ID,
                          'amount': decimal.Decimal}),
        'event.stored_queries': _augment_dict_validator(
            _empty_dict, {'id': ID, 'event_id': ID, 'query_name': str,
                          'scope': QueryScope, 'serialized_query': Mapping}),
    }
    optional_table_validators: Mapping[str, Callable[..., Any]] = {
        'event.part_groups': _augment_dict_validator(
            _event_part_group, {'id': ID, 'event_id': ID}),
        'event.part_group_parts': _augment_dict_validator(
            _empty_dict, {'id': ID, 'part_group_id': ID, 'part_id': ID}),
        'event.track_groups': _augment_dict_validator(
            _event_track_group, {'id': ID, 'event_id': ID}),
        'event.track_group_tracks': _augment_dict_validator(
            _empty_dict, {'id': ID, 'track_group_id': ID, 'track_id': ID}),
        # Ignore models_droid.OrgaToken. Do not validate and do not import.
    }

    new_val = {k: val[k] for k in mandatory_fields}

    errs = ValidationSummary()
    for table, validator in table_validators.items():
        new_table = {}
        for key, entry in val[table].items():
            with errs:
                new_entry = validator(entry, argname=table, **kwargs)
                new_key = _int(key, argname=table, **kwargs)
                new_table[new_key] = new_entry
        new_val[table] = new_table

    for table, validator in optional_table_validators.items():
        if table not in val:
            continue
        new_table = {}
        for key, entry in val[table].items():
            with errs:
                new_entry = validator(entry, argname=table, **kwargs)
                new_key = _int(key, argname=table, **kwargs)
                new_table[new_key] = new_entry
        new_val[table] = new_table

    if errs:
        raise errs

    # Third a consistency check
    if len(new_val['event.events']) != 1:
        errs.append(ValueError('event.events', n_(
            "Only a single event is supported.")))
    event_id = new_val['id']
    if new_val['event.events'] and event_id != new_val['event.events'][event_id]['id']:
        errs.append(ValueError('event.events', n_("Wrong event specified.")))

    for table, entity_dict in new_val.items():
        if table not in ('id', 'EVENT_SCHEMA_VERSION', 'timestamp', 'kind'):
            for entity in entity_dict.values():
                if entity.get('event_id') and entity['event_id'] != event_id:
                    errs.append(ValueError(table, n_("Mismatched event.")))

    if errs:
        raise errs

    return SerializedEvent(new_val)


@_add_typed_validator
def _serialized_partial_event_upload(
    val: Any, argname: str = "serialized_partial_event_upload", **kwargs: Any,
) -> SerializedPartialEventUpload:
    """Check an event data set for delta import."""

    val = _input_file(val, argname, **kwargs)

    val = _json(val, argname, **kwargs)

    return SerializedPartialEventUpload(_serialized_partial_event(
        val, argname, **kwargs))


@_add_typed_validator
def _serialized_partial_event(
    val: Any, argname: str = "serialized_partial_event", **kwargs: Any,
) -> SerializedPartialEvent:
    """Check an event data set for delta import."""

    # First a basic check
    val = _mapping(val, argname, **kwargs)

    if 'kind' not in val or val['kind'] != "partial":
        raise ValidationSummary(KeyError(argname, n_(
            "Only partial exports are supported.")))

    mandatory_fields: TypeMapping = {
        'EVENT_SCHEMA_VERSION': tuple[int, int],
        'kind': str,
        'id': ID,
        'timestamp': datetime.datetime,
    }
    optional_fields: TypeMapping = {
        'courses': Mapping,
        'lodgement_groups': Mapping,
        'lodgements': Mapping,
        'registrations': Mapping,
        'summary': str,
    }

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    if not ((EVENT_SCHEMA_VERSION[0], 0) <= val['EVENT_SCHEMA_VERSION']
            <= EVENT_SCHEMA_VERSION):
        raise ValidationSummary(ValueError(
            argname, n_("Schema version mismatch.")))

    domain_validators: TypeMapping = {
        'courses': Optional[PartialCourse],  # type: ignore[dict-item]
        'lodgement_groups': Optional[PartialLodgementGroup],  # type: ignore[dict-item]
        'lodgements': Optional[PartialLodgement],  # type: ignore[dict-item]
        'registrations': Optional[PartialRegistration],  # type: ignore[dict-item]
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

            creation = new_key < 0
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
    'is_visible': Optional[bool],
}

PARTIAL_COURSE_OPTIONAL_FIELDS: TypeMapping = {
    'segments': Mapping,
    'fields': Mapping,
}


@_add_typed_validator
def _partial_course(
    val: Any, argname: str = "course", *, creation: bool = False, **kwargs: Any,
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
                new_entry: Optional[bool] = _ALL_TYPED[Optional[bool]](  # type: ignore[index]
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
    creation: bool = False, **kwargs: Any,
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
    creation: bool = False, **kwargs: Any,
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
    'checkin': Optional[datetime.datetime],
    'fields': Mapping,
    'personalized_fees': Mapping,
}

# TODO Can we auto generate all these partial validators?


@_add_typed_validator
def _partial_registration(
    val: Any, argname: str = "registration", *,
    creation: bool = False, **kwargs: Any,
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
    if 'personalized_fees' in val:
        newfees = {}
        for fee_id, amount in val['personalized_fees'].items():
            try:
                fee_id = _id(fee_id, 'personalized_fees', **kwargs)
                amount = _ALL_TYPED[Optional[decimal.Decimal]](  # type: ignore[index]
                    amount, 'personalized_fees', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newfees[fee_id] = amount
        val['personalized_fees'] = newfees

    if errs:
        raise errs

    # the check of fields is delegated to _event_associated_fields
    return PartialRegistration(val)


@_add_typed_validator
def _partial_registration_part(
    val: Any, argname: str = "partial_registration_part", **kwargs: Any,
) -> PartialRegistrationPart:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'status': const.RegistrationPartStati,
        'lodgement_id': Optional[PartialImportID],  # type: ignore[dict-item]
        'is_camping_mat': bool,
    }

    return PartialRegistrationPart(_examine_dictionary_fields(
        val, {}, optional_fields, **kwargs))


@_add_typed_validator
def _partial_registration_track(
    val: Any, argname: str = "partial_registration_track", **kwargs: Any,
) -> PartialRegistrationTrack:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'course_id': Optional[PartialImportID],  # type: ignore[dict-item]
        'course_instructor': Optional[PartialImportID],  # type: ignore[dict-item]
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
    field_definitions: CdEDBObjectMap, fees_by_field: dict[int, set[int]],
    questionnaire: dict[const.QuestionnaireUsages, list[QuestionnaireRow]],
    extend_questionnaire: bool, skip_existing_fields: bool,
    **kwargs: Any,
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
            new_questionnaire = _ALL_TYPED[Questionnaire](
                val['questionnaire'], field_definitions=field_definitions,
                fees_by_field=fees_by_field, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
        else:
            if extend_questionnaire:
                tmp = {
                    kind: questionnaire.get(kind, []) + new_questionnaire.get(kind, [])
                    for kind in const.QuestionnaireUsages
                }
                try:
                    new_questionnaire = _ALL_TYPED[Questionnaire](
                        tmp, field_definitions=field_definitions,
                        fees_by_field=fees_by_field, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)

            val['questionnaire'] = new_questionnaire
    else:
        val['questionnaire'] = {}

    if errs:
        raise errs

    return SerializedEventQuestionnaire(val)


@_add_typed_validator
def _serialized_event_configuration(
    val: Any, argname: str = "serialized_event_configuration", *,
    creation: bool = False,
    current: Optional[models_event.Event],
    skip_field_validation: bool = False,
    **kwargs: Any,
) -> SerializedEventConfiguration:

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(**EVENT_COMMON_FIELDS)
        optional_fields = dict(**EVENT_EXPOSED_OPTIONAL_FIELDS)
    else:
        mandatory_fields = {}
        optional_fields = dict(**EVENT_EXPOSED_FIELDS)

    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()

    # Check IBAN to be valid
    valid_ibans = {v[0] for v in _CONFIG['EVENT_BANK_ACCOUNTS']}
    if val.get('iban') and val['iban'] not in valid_ibans:
        with errs:
            raise ValidationSummary(ValueError(
                "iban", n_("Must be a registered event IBAN.")))

    # Check registration time compatibility.
    start = val.get('registration_start')
    soft = val.get('registration_soft_limit')
    hard = val.get('registration_hard_limit')
    if current:
        start = start or current.registration_start
        soft = soft or current.registration_soft_limit
        hard = hard or current.registration_hard_limit
    if start and (soft and start > soft or hard and start > hard):
        with errs:
            raise ValidationSummary(ValueError(
                "registration_start", n_("Must be before hard and soft limit.")))
    if soft and hard and soft > hard:
        with errs:
            raise ValidationSummary(ValueError(
                "registration_soft_limit", "Must be before or equal to hard limit."))

    # Check field association
    if not skip_field_validation and current:
        if lodge_field := val.get('lodge_field_id'):
            if lodge_field not in current.fields:
                with errs:
                    raise ValidationSummary(KeyError(
                        "lodge_field_id", n_("Unknown lodge field.")))
            else:
                field = current.fields[lodge_field]
                legal_associations, legal_kinds = EVENT_FIELD_SPEC['lodge_field']
                if field.association not in legal_associations:
                    with errs:
                        raise ValidationSummary(ValueError(
                            "lodge_field_id",
                            n_("Lodge field must be a registration field.")))
                if field.kind not in legal_kinds:
                    with errs:
                        raise ValidationSummary(ValueError(
                            "lodge_field_id",
                            n_("Lodge field must have type 'string'.")))

    if errs:
        raise errs

    return SerializedEventConfiguration(val)


@_add_typed_validator
def _mailinglist(
    val: Any, argname: str = "mailinglist", *, creation: bool = False,
    subtype: models_ml.MLType = models_ml.Mailinglist, **kwargs: Any,
) -> Mailinglist:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :param subtype: Mandatory parameter to check for suitability for the given subtype.
    """

    val = _mapping(val, argname, **kwargs)

    if subtype == models_ml.Mailinglist:
        raise ValidationSummary(ValueError(
            "ml_type", "Must provide ml_type for setting mailinglist."))

    mandatory_fields, optional_fields = subtype.validation_fields(creation=creation)
    val = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()

    if val and "moderators" in val and not val["moderators"]:
        errs.append(ValueError("moderators", n_("Must not be empty.")))
    if "domain" not in val:
        errs.append(ValueError(
            "domain", "Must specify domain for setting mailinglist."))
    else:
        if val["domain"].value not in subtype.available_domains:
            errs.append(ValueError("domain", n_(
                "Invalid domain for this mailinglist type.")))

    if not val.get('event_id'):
        if val.get('event_part_group_id'):
            errs.append(ValueError("event_id", n_(
                "Cannot have event part group without event.")))

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
    val: Any, argname: str = "subscription_identifier", **kwargs: Any,
) -> SubscriptionIdentifier:
    val = _mapping(val, argname, **kwargs)

    # TODO why is deepcopy mandatory?
    # TODO maybe make signature of examine dict to take a non-mutable mapping?
    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}

    return SubscriptionIdentifier(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


@_add_typed_validator
def _subscription_dataset(
    val: Any, argname: str = "subscription_dataset", **kwargs: Any,
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
    val: Any, argname: str = "subscription address", **kwargs: Any,
) -> SubscriptionAddress:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}
    mandatory_fields.update(SUBSCRIPTION_ADDRESS_FIELDS)

    return SubscriptionAddress(_examine_dictionary_fields(
        val, mandatory_fields, **kwargs))


ASSEMBLY_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    # Assembly shortnames do not actually need to be that short.
    'shortname': Identifier,
    'description': Optional[str],
    'signup_end': datetime.datetime,
    'notes': Optional[str],
}

ASSEMBLY_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'is_active': bool,
    'presider_address': Optional[Email],
    'presiders': Iterable,
}


@_add_typed_validator
def _assembly(
    val: Any, argname: str = "assembly", *,
    creation: bool = False, **kwargs: Any,
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
    'use_bar': bool,
}

BALLOT_EXPOSED_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'vote_extension_end': Optional[datetime.datetime],
    'abs_quorum': int,
    'rel_quorum': int,
    'votes': Optional[PositiveInt],
}

BALLOT_EXPOSED_FIELDS = {**BALLOT_COMMON_FIELDS, **BALLOT_EXPOSED_OPTIONAL_FIELDS}

BALLOT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    **BALLOT_EXPOSED_OPTIONAL_FIELDS,
    'extended': Optional[bool],
    'is_tallied': bool,
    'candidates': Mapping,
    'linked_attachments': Optional[list[Optional[ID]]],
}


@_add_typed_validator
def _ballot(
    val: Any, argname: str = "ballot", *,
    creation: bool = False, **kwargs: Any,
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
                creation = anid < 0
                try:
                    candidate = _ALL_TYPED[Optional[BallotCandidate]](  # type: ignore[index]
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

    # The first part of each condition ensures that either both of extension end and
    # quorum are given or none of them, while the second part of the condition checks
    # whether the values are compatible if both are present.
    if ('vote_extension_end' in val and quorum is None
            or val.get('vote_extension_end') and not quorum):
        # Quorum key missing and vote extension end key given
        # or trivial quorum given, but non-empty extension end provided
        errs.extend(quorum_errors)
    elif (quorum is not None and 'vote_extension_end' not in val
            or quorum and not val.get('vote_extension_end')):
        # Extension end key missing and quorum key given
        # or empty extension end, but non-trivial quorum provided
        errs.append(vote_extension_error)

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
    creation: bool = False, ignore_warnings: bool = False, **kwargs: Any,
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
        mandatory_fields = {}
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
    'file_hash': str,
}


@_add_typed_validator
def _assembly_attachment(
    val: Any, argname: str = "assembly_attachment", **kwargs: Any,
) -> AssemblyAttachment:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = dict(ASSEMBLY_ATTACHMENT_VERSION_FIELDS,
                            **ASSEMBLY_ATTACHMENT_FIELDS)

    val = _examine_dictionary_fields(val, mandatory_fields, **kwargs)

    return AssemblyAttachment(val)


@_add_typed_validator
def _assembly_attachment_version(
    val: Any, argname: str = "assembly_attachment_version", creation: bool = False,
    **kwargs: Any,
) -> AssemblyAttachmentVersion:
    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = {'attachment_id': ID, **ASSEMBLY_ATTACHMENT_VERSION_FIELDS}
        optional_fields: TypeMapping = {}
    else:
        mandatory_fields = {'attachment_id': ID, 'version_nr': ID}
        optional_fields = {**ASSEMBLY_ATTACHMENT_VERSION_FIELDS}

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    return AssemblyAttachmentVersion(val)


@_add_typed_validator
def _vote(
    val: Any, argname: str = "vote",
    ballot: Optional[CdEDBObject] = None, **kwargs: Any,
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

    candidates = [e['shortname'] for e in ballot['candidates'].values()]
    if ballot['use_bar'] or ballot['votes']:
        candidates.append(ASSEMBLY_BAR_SHORTNAME)

    # Check that the vote passes schulze_condorcet requirements
    try:
        [val] = validate_votes([val], candidates)
    except ValueError as e:
        raise ValidationSummary(ValueError(argname, *e.args)) from e

    # votes for classical voting have more constraints
    # votes without '>' are valid abstentions
    if ballot['votes'] and '>' in val:
        vote_tuple = as_vote_tuple(val)
        if len(vote_tuple) > 2:
            errs.append(ValueError(argname, n_("Too many levels.")))
        voted = vote_tuple[0]
        if len(voted) > ballot['votes']:
            errs.append(ValueError(argname, n_("Too many votes.")))
        if ASSEMBLY_BAR_SHORTNAME in voted and voted != (ASSEMBLY_BAR_SHORTNAME, ):
            errs.append(ValueError(argname, n_("Misplaced bar.")))
        if errs:
            raise errs

    return Vote(val)


# TODO move above
@_add_typed_validator
def _regex(
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
def _custom_query_filter(
        val: Any, argname: str = "custom_query_filter", *, creation: bool = False,
        query_spec: QuerySpec, **kwargs: Any,
) -> CustomQueryFilter:
    val = _mapping(val, argname, **kwargs)

    if (fields := val.get('fields')) and isinstance(fields, str):
        val = dict(val)
        val['fields'] = set(fields.split(","))

    mandatory, optional = models_event.CustomQueryFilter.validation_fields(
        creation=creation)
    val = _examine_dictionary_fields(val, mandatory, optional, **kwargs)

    errs = ValidationSummary()

    if len(val['fields']) < 2:
        with errs:
            raise ValidationSummary(ValueError('field', n_(
                "Combine a minimum of two fields.")))
    if any(field not in query_spec for field in val['fields']):
        with errs:
            raise ValidationSummary(KeyError('field', n_(
                "Unknown field(s): %(fields)s."), {
                'fields': ", ".join(val['fields'] - set(query_spec)),
            }))
    elif len({query_spec[f].type for f in val['fields']}) != 1:
        with errs:
            raise ValidationSummary(TypeError('field', n_(
                "Incompatible field types.")))

    val['fields'] = models_event.CustomQueryFilter._get_field_string(val['fields'])  # pylint: disable=protected-access

    if errs:
        raise errs

    return CustomQueryFilter(val)


@_add_typed_validator
def _query_input(
    val: Any, argname: Optional[str] = None, *,
    spec: QuerySpec, allow_empty: bool = False,
    separator: str = ',', escape: str = '\\',
    **kwargs: Any,
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
    order: list[QueryOrder] = []
    errs = ValidationSummary()

    for field, spec_entry in spec.items():
        validator = spec_entry.type
        # First the selection of fields of interest
        try:
            selected = _bool(val.get(f"qsel_{field}", "False"), field, **kwargs)
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
                Optional[QueryOperators]  # type: ignore[index]
            ](
                val.get(f"qop_{field}"), field, **kwargs)
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
        value = val.get(f"qval_{field}")
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
                # TODO do not allow None
                try:
                    vv: Any = _ALL_TYPED[
                        Optional[VALIDATOR_LOOKUP[validator]]  # type: ignore[index]
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

                assert vv is not None
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
                value = _ALL_TYPED[Optional[NonRegex]](  # type: ignore[index]
                    value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        elif operator in (QueryOperators.regex, QueryOperators.notregex):
            try:
                value = _ALL_TYPED[Optional[Regex]](  # type: ignore[index]
                    value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        else:
            try:
                value = _ALL_TYPED[
                    Optional[VALIDATOR_LOOKUP[validator]]  # type: ignore[index]
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
    for postfix in range(MAX_QUERY_ORDERS):
        if f"qord_{postfix}" not in val:
            continue

        try:
            entry: Optional[CSVIdentifier] = _ALL_TYPED[
                Optional[CSVIdentifier]  # type: ignore[index]
            ](val[f"qord_{postfix}"], f"qord_{postfix}", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if not entry or entry not in spec:
            continue

        tmp = f"qord_{postfix}_ascending"
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
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
    _ALL_TYPED[Optional[str]](  # type: ignore[index]
        val.name, "name", **kwargs)

    # spec
    for field, spec_entry in val.spec.items():
        with errs:
            _csv_identifier(field, "spec", **kwargs)

        with errs:
            _printable_ascii(spec_entry.type, "spec", **kwargs)

    # fields_of_interest
    for field in val.fields_of_interest:
        with errs:
            _csv_identifier(field, "fields_of_interest", **kwargs)
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

        with errs:
            field = _csv_identifier(field, "constraints", **kwargs)

        if field not in val.spec:
            errs.append(KeyError("constraints", n_("Invalid field.")))
            continue

        try:
            operator = _ALL_TYPED[QueryOperators](
                operator, f"constraints/{field}", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if operator not in VALID_QUERY_OPERATORS[val.spec[field].type]:
            errs.append(ValueError(f"constraints/{field}", n_("Invalid operator.")))
            continue

        if operator in NO_VALUE_OPERATORS:
            value = None

        elif operator in MULTI_VALUE_OPERATORS:
            validator: Callable[..., Any] = _ALL_TYPED[
                Optional[VALIDATOR_LOOKUP[val.spec[field].type]]]  # type: ignore[index]
            for v in value:
                with errs:
                    validator(v, f"constraints/{field}", **kwargs)
        else:
            try:
                _ALL_TYPED[
                    Optional[VALIDATOR_LOOKUP[val.spec[field].type]]  # type: ignore[index]
                ](
                    value,
                    f"constraints/{field}",
                    **kwargs,
                )
            except ValidationSummary as e:
                errs.extend(e)

    # order
    for idx, entry in enumerate(val.order):
        try:
            # TODO use generic tuple here once implemented
            entry = _ALL_TYPED[Iterable](entry, 'order', **kwargs)  # type: ignore[assignment, type-abstract]
        except ValidationSummary as e:
            errs.extend(e)
            continue

        try:
            field, ascending = entry
        except ValueError:
            msg = n_("Invalid ordering condition number %(index)s")
            errs.append(ValueError("order", msg, {'index': idx}))
            continue

        try:
            field = _csv_identifier(field, "order", **kwargs)
            ascending = _bool(ascending, "order", **kwargs)
        except ValidationSummary as e:
            errs.extend(e)

        if field not in val.spec:
            errs.append(KeyError("order", n_("Invalid field.")))
            continue

    if errs:
        raise errs

    # TODO why deepcopy?
    return copy.deepcopy(val)


def _range(
    val: Any, type_: type[T], argname: Optional[str] = None, **kwargs: Any,
) -> tuple[T, T]:
    """Validate val to be a tuple of exactly two values of the given type.

    Used to specify a range to filter for.
    """
    val = _sequence(val, argname, **kwargs)

    if not len(val) == 2:
        raise ValidationSummary(ValueError(n_("Must contain exactly two elements.")))

    errs = ValidationSummary()
    new_val = []
    for v in val:
        with errs:
            new_val.append(_ALL_TYPED[type_](v, argname, **kwargs))

    if errs:
        raise errs

    from_val, to_val = new_val  # pylint: disable=unbalanced-tuple-unpacking
    return (from_val, to_val)


@_add_typed_validator
def _log_filter(
    val: Any, argname: Optional[str] = None,
    *, subtype: type[GenericLogFilter],
    **kwargs: Any,
) -> LogFilter:

    if isinstance(val, GenericLogFilter):
        val = val.to_validation()
    val = dict(_mapping(val, argname, **kwargs))

    if not val.get('length'):
        val['length'] = _CONFIG['DEFAULT_LOG_LENGTH']

    mandatory, optional = subtype.validation_fields()
    val = _examine_dictionary_fields(val, mandatory, optional)

    return LogFilter(val)


E = TypeVar('E', bound=enum.Enum)


def _enum_validator_maker(
    anenum: type[E], name: Optional[str] = None, internal: bool = False,
) -> Callable[..., E]:
    """Automate validator creation for enums.

    Since this is pretty generic we do this all in one go.

    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    :param internal: If True the validator is not added to the module.
    """
    error_msg = n_("Invalid input for the enumeration %(enum)s")

    def the_validator(
        val: Any, argname: Optional[str] = None,
        **kwargs: Any,
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
    val: Any, argname: Optional[str] = None, **kwargs: Any,
) -> DatabaseSubscriptionState:
    """Validates whether a subscription state is written into the database."""
    val = _ALL_TYPED[const.SubscriptionState](val, argname, **kwargs)
    if val == const.SubscriptionState.none:
        raise ValidationSummary(ValueError(
            argname, n_("SubscriptionState.none is not written into the database.")))
    return DatabaseSubscriptionState(val)


IE = TypeVar("IE", bound=CdEIntEnum)


def _infinite_enum_validator_maker(anenum: type[IE], name: Optional[str] = None,
                                   ) -> None:
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
        val: Any, argname: Optional[str] = None,
        **kwargs: Any,
    ) -> InfiniteEnum[IE]:
        val_int: Optional[int]

        if isinstance(val, InfiniteEnum):
            val_enum = raw_validator(
                val.enum, argname=argname, **kwargs)

            if val.enum.value == INFINITE_ENUM_MAGIC_NUMBER:
                val_int = _non_negative_int(
                    val.int, argname=argname, **kwargs)
            else:
                val_int = 0

        else:
            val = _int(val, argname=argname, **kwargs)
            assert isinstance(val, int)

            if val < 0:
                val_int = 0
                try:
                    val_enum = anenum(val)
                except ValueError as e:
                    raise ValidationSummary(
                        ValueError(argname, error_msg, {'enum': anenum})) from e
            else:
                val_enum = anenum(INFINITE_ENUM_MAGIC_NUMBER)
                val_int = val

        return InfiniteEnum[anenum](val_enum, val_int)  # type: ignore[valid-type]

    the_validator.__name__ = name or f"_infinite_enum_{anenum.__name__.lower()}"
    _add_typed_validator(the_validator, InfiniteEnum[anenum])  # type: ignore[valid-type]


for oneenum in ALL_INFINITE_ENUMS:
    _infinite_enum_validator_maker(oneenum)
