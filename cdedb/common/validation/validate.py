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
import collections.abc
import contextlib
import copy
import csv
import datetime
import decimal
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
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from types import TracebackType
from typing import (
    Any,
    Protocol,
    Self,
    cast,
    get_type_hints,
    overload,
)

import freezegun.api
import magic
import phonenumbers
import PIL.Image
import werkzeug.datastructures
import zxcvbn
from schulze_condorcet.util import as_vote_tuple, validate_votes
from typing_extensions import TypeForm

import cdedb.database.constants as const
import cdedb.fee_condition_parser.evaluation as fcp_evaluation
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
import cdedb.models.complaint as models_complaint
import cdedb.models.core as models_core
import cdedb.models.droid as models_droid
import cdedb.models.event as models_event
import cdedb.models.ml as models_ml
import cdedb.models.past_event as models_past_event
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
    get_mandatory_type,
    is_optional_type,
    normalize_field_entries,
    normalize_phone,
    now,
    parse_date,
    parse_datetime,
)
from cdedb.common.exceptions import ValidationWarning
from cdedb.common.n_ import n_
from cdedb.common.parse.util import Accounts
from cdedb.common.query import (
    MAX_QUERY_ORDERS,
    MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS,
    VALID_QUERY_OPERATORS,
    Query,
    QueryConstraint,
    QueryOperators,
    QueryOrder,
    QueryScope,
    QuerySpec,
)
from cdedb.common.query.log_filter import ALL_LOG_FILTERS, GenericLogFilter
from cdedb.common.roles import ADMIN_KEYS, extract_roles
from cdedb.common.sorting import xsorted
from cdedb.common.validation.data import COUNTRY_CODES, FREQUENCY_LISTS, IBAN_LENGTHS
from cdedb.common.validation.types import *  # noqa: F403
from cdedb.config import Config
from cdedb.database.constants import FieldAssociations, FieldDatatypes
from cdedb.enums import ALL_ENUMS, ALL_INFINITE_ENUMS
from cdedb.models.common import CdEDataclass, CdEDataclassMap
from cdedb.models.event import ReducedCheckinPeriod
from cdedb.uncommon.intenum import CdEIntEnum

NoneType = type(None)

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)
_CONFIG = Config()


class ValidationSummary(ValueError, Sequence[Exception]):
    args: tuple[Exception, ...]

    def __len__(self) -> int:
        return len(self.args)

    @overload
    def __getitem__(self, index: int) -> Exception: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Exception]: ...

    def __getitem__(self, index: int | slice) -> Exception | Sequence[Exception]:
        return self.args[index]

    def extend(self, errors: Iterable[Exception]) -> None:
        self.args += tuple(errors)

    def append(self, error: Exception) -> None:
        self.args += (error,)

    @contextlib.contextmanager
    def callback(
        self, callback: Callable[[Iterable[Exception]], Iterable[Exception]]
    ) -> Iterator[Self]:
        """
        Context manager that allows modifying the collected errors before appending them.
        """
        with self.__class__() as tmp:
            yield tmp
        self.extend(callback(tmp))

    @contextlib.contextmanager
    def as_argname(self, argname: str, replace: bool = False) -> Iterator[Self]:
        """
        Context manager that collects all validation errors raised inside under the given argname.

        :param replace: If True, do not append the originally raised errors.
            If False, the originally raised errors are also collected.
        """

        def callback(errors: Iterable[Exception]) -> list[Exception]:
            ret = [exc.__class__(argname, *exc.args[1:]) for exc in errors]
            if not replace:
                ret.extend(exc for exc in errors if exc.args[0] != argname)
            return ret

        with self.callback(callback):
            yield self

    @contextlib.contextmanager
    def modify_argname(self, *, prefix: str = "", suffix: str = "") -> Iterator[Self]:

        def callback(errors: Iterable[Exception]) -> list[Exception]:
            ret = [
                exc.__class__(prefix + exc.args[0] + suffix, *exc.args[1:])
                for exc in errors
            ]
            return ret

        with self.callback(callback):
            yield self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[Exception] | None,
        exc_val: Exception | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if isinstance(exc_val, self.__class__):
            self.extend(exc_val)
            return True
        return False


class ValidatorStorage[T](dict[TypeForm[T], Callable[..., T]]):
    def __setitem__(self, type_: TypeForm[T], validator: Callable[..., T]) -> None:
        super().__setitem__(type_, validator)

    def __getitem__(self, type_: TypeForm[T]) -> Callable[..., T]:
        origin = typing.get_origin(type_)
        if is_optional_type(type_):
            return cast(
                Callable[..., T],
                _allow_None(self[get_mandatory_type(type_)]),
            )
        elif origin is list or origin is collections.abc.Collection:
            [inner_type] = typing.get_args(type_)
            return cast(Callable[..., T], make_list_validator(inner_type))
        elif origin is set:
            [inner_type] = typing.get_args(type_)
            return cast(Callable[..., T], make_set_validator(inner_type))
        elif origin is tuple:
            args = typing.get_args(type_)
            if len(args) == 2:
                type_a, type_b = args
                if type_a is type_b:
                    return cast(Callable[..., T], make_pair_validator(type_a))
        elif origin is dict or origin is CdEDataclassMap:
            return cast(
                Callable[..., T], make_dict_validator(cast(type[dict[Any, Any]], type_))
            )
        elif isinstance(type_, typing.ForwardRef):
            model_namespaces = [  # type: ignore[unreachable]
                models_core,
                models_event,
                models_ml,
                models_droid,
                models_complaint,
            ]
            for model_namespace in model_namespaces:
                try:
                    return self[
                        type_._evaluate(
                            vars(model_namespace),
                            {},
                            recursive_guard=set(),
                        )
                    ]
                except NameError:
                    pass
            raise NameError(
                f"Failed to resolve forward Reference {type_} from model namespaces {model_namespaces}"
            )

        return super().__getitem__(type_)


_ALL_TYPED: ValidatorStorage[Any] = ValidatorStorage()


@overload
def validate_assert(
    type_: type[CdEDataclass], value: Any, ignore_warnings: bool, **kwargs: Any
) -> CdEDBObject: ...


@overload
def validate_assert[T](
    type_: TypeForm[T], value: Any, ignore_warnings: bool, **kwargs: Any
) -> T: ...


def validate_assert[T](
    type_: TypeForm[T] | type[CdEDataclass],
    value: Any,
    ignore_warnings: bool,
    **kwargs: Any,
) -> T | CdEDBObject:
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
            f"{old_format} for '{str(type_)}' with input {value!r}, {kwargs}."
        )
        e = errs[0]
        e.args = (f"{e.args[1]} ({e.args[0]})",) + e.args[2:]
        raise e from errs


@overload
def validate_check(
    type_: type[CdEDataclass],
    value: Any,
    ignore_warnings: bool,
    field_prefix: str = "",
    field_postfix: str = "",
    **kwargs: Any,
) -> tuple[CdEDBObject | None, list[Error]]: ...


@overload
def validate_check[T](
    type_: TypeForm[T],
    value: Any,
    ignore_warnings: bool,
    field_prefix: str = "",
    field_postfix: str = "",
    **kwargs: Any,
) -> tuple[T | None, list[Error]]: ...


def validate_check[T](
    type_: TypeForm[T] | type[CdEDataclass],
    value: Any,
    ignore_warnings: bool,
    field_prefix: str = "",
    field_postfix: str = "",
    **kwargs: Any,
) -> tuple[T | CdEDBObject | None, list[Error]]:
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
            )
            for e in errs
        ]
        _LOGGER.debug(
            f"{old_format} for '{str(type_)}' with input {value!r}, {kwargs}."
        )
        return None, old_format


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


def _allow_None[T](fun: Callable[..., T]) -> Callable[..., T | None]:
    """Wrap a validator to allow ``None`` as valid input.

    This causes falsy values to be mapped to ``None`` if there is an error.
    """

    @functools.wraps(fun)
    def new_fun(val: Any, *args: Any, **kwargs: Any) -> T | None:
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


def _add_typed_validator[F: Callable[..., Any]](
    fun: F, return_type: TypeForm[Any] | None = None
) -> F:
    """Mark a typed function for processing into validators."""
    # TODO get rid of dynamic return types for enum
    if not return_type:
        return_type = get_type_hints(fun)["return"]
    assert return_type
    if return_type in _ALL_TYPED:
        raise RuntimeError(f"Type {return_type} already registered")
    _ALL_TYPED[return_type] = fun

    return fun


def _create_dataclass_validator[
    F: Callable[..., Any],
    DC: CdEDataclass | GenericLogFilter,
](
    *types: type[DC], _prepare: Callable[..., CdEDBObject] | None = None, **kwargs_: Any
) -> Callable[[F], F]:
    """Takes a function and creates one validator per given dataclass.

    The new validator accepts a dict, checking that its keys conform to the
    respective dataclass definition and then calls the function.

    The function may perform further validations and must return a dict.
    If `creation=True`, the dict can be used to instantiate a valid dataclass
      (after adding an `id=-1`).
    """

    def the_decorator(fun: F) -> F:
        for type_ in types:

            def new_validator(
                val: Any,
                argname: str = type_.__qualname__,
                *,
                type__: type[DC] = type_,
                creation: bool = False,
                **kwargs: Any,
            ) -> CdEDBObject:
                if isinstance(val, (CdEDataclass, GenericLogFilter)):
                    val = val._to_validation()
                new_kwargs = {**kwargs_, **kwargs}
                new_kwargs["type_"] = type__
                val = _mapping(val, argname, **new_kwargs)
                if issubclass(type__, GenericLogFilter):
                    mandatory, optional = type__.validation_fields()
                elif issubclass(type__, CdEDataclass):
                    mandatory, optional = type__.validation_fields(creation=creation)
                else:
                    raise RuntimeError("Impossible.")
                if _prepare is not None:
                    val = _prepare(val, creation=creation, **new_kwargs)
                val = _examine_dictionary_fields(val, mandatory, optional, **new_kwargs)
                val = fun(val, argname, creation=creation, **new_kwargs)
                return val

            _add_typed_validator(new_validator, type_)

        return fun

    return the_decorator


def _examine_dictionary_fields(
    adict: Mapping[str, Any],
    mandatory_fields: TypeMapping,
    optional_fields: TypeMapping | None = None,
    *,
    argname: str = "",
    allow_superfluous: bool = False,
    pass_superfluous: bool = False,
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
    :params pass_superfluous: If True, superfluous key are returned as is.
    """
    optional_fields = optional_fields or {}
    errs = ValidationSummary()
    retval: dict[str, Any] = {}
    for key, value in adict.items():
        sub_argname = argname + "." + key if argname else key
        if key in mandatory_fields:
            try:
                v = _ALL_TYPED[mandatory_fields[key]](
                    value, argname=sub_argname, **kwargs
                )
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
        elif key in optional_fields:
            try:
                v = _ALL_TYPED[optional_fields[key]](
                    value, argname=sub_argname, **kwargs
                )
                retval[key] = v
            except ValidationSummary as e:
                errs.extend(e)
            except KeyError as e:
                e.args += (key,)
                raise
        elif not allow_superfluous:
            errs.append(KeyError(sub_argname, n_("Superfluous key found.")))
        elif pass_superfluous:
            retval[key] = value

    missing_mandatory = set(mandatory_fields).difference(adict)
    if missing_mandatory:
        for key in missing_mandatory:
            sub_argname = argname + "." + key if argname else key
            errs.append(KeyError(sub_argname, n_("Mandatory key missing.")))

    if errs:
        raise errs

    return retval


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


def filter_none(data: Mapping[str, Any]) -> dict[str, Any]:
    """Helper function to remove NoneType values from dictionaies."""
    return {k: v for k, v in data.items() if v is not NoneType}


#
# Below is the real stuff
#


@_add_typed_validator
def _None(val: Any, argname: str | None = None, **kwargs: Any) -> None:
    """Force a None.

    This is mostly for ensuring proper population of dicts.
    """
    if isinstance(val, str) and not val:
        val = None
    if val is not None:
        raise ValidationSummary(ValueError(argname, n_("Must be empty.")))


_ALL_TYPED[None] = _None


@_add_typed_validator
def _any(val: Any, argname: str | None = None, **kwargs: Any) -> Any:
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.
    """
    return val


@_add_typed_validator
def _int(val: Any, argname: str | None = None, **kwargs: Any) -> int:
    if isinstance(val, (str, bool)):
        try:
            val = int(val)
        except ValueError as e:
            raise ValidationSummary(
                ValueError(argname, n_("Invalid input for integer."))
            ) from e
    elif isinstance(val, (float, decimal.Decimal)):
        if not math.isclose(val, int(val), abs_tol=EPSILON):
            raise ValidationSummary(ValueError(argname, n_("Precision loss.")))
        val = int(val)
    # disallow booleans as psycopg will try to send them as such and not ints
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValidationSummary(TypeError(argname, n_("Must be an integer.")))
    if not -(2**31) <= val < 2**31:
        # Our postgres columns only support 32-bit integers.
        raise ValidationSummary(ValueError(argname, n_("Integer too large.")))
    return val


@_add_typed_validator
def _non_negative_int(
    val: Any, argname: str | None = None, **kwargs: Any
) -> NonNegativeInt:
    val = _int(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be negative.")))
    return NonNegativeInt(val)


@_add_typed_validator
def _positive_int(val: Any, argname: str | None = None, **kwargs: Any) -> PositiveInt:
    val = _int(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be positive.")))
    return PositiveInt(val)


@_add_typed_validator
def _negative_int(val: Any, argname: str | None = None, **kwargs: Any) -> NegativeInt:
    val = _int(val, argname, **kwargs)
    if val >= 0:
        raise ValidationSummary(ValueError(argname, n_("Must be negative.")))
    return NegativeInt(val)


@_add_typed_validator
def _id(val: Any, argname: str | None = None, **kwargs: Any) -> ID:
    """A numeric ID as in a database key.

    This is just a wrapper around `_positive_int`, to differentiate this
    semantically.
    """
    if val is None or isinstance(val, str) and not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    val = _positive_int(val, argname, **kwargs)
    return ID(val)


_add_typed_validator(_id, InvolvedID)


@_add_typed_validator
def _partial_import_id(
    val: Any, argname: str | None = None, **kwargs: Any
) -> PartialImportID:
    """A numeric id or a negative int as a placeholder."""
    if val is None or isinstance(val, str) and not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    val = _int(val, argname, **kwargs)
    if val == 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be zero.")))
    return PartialImportID(val)


@_add_typed_validator
def _float(val: Any, argname: str | None = None, **kwargs: Any) -> float:
    try:
        val = float(val)
    except (ValueError, TypeError) as e:
        raise ValidationSummary(
            ValueError(argname, n_("Invalid input for float."))
        ) from e
    if not isinstance(val, float):
        raise ValidationSummary(
            TypeError(argname, n_("Must be a floating point number."))
        )
    if abs(val) >= 1e7:
        # we are using numeric(8,2) columns in postgres
        # which only support numbers up to this size
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a million."))
        )
    return val


@_add_typed_validator
def _non_negative_float(
    val: Any, argname: str | None = None, **kwargs: Any
) -> NonNegativeFloat:
    val = _float(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(argname, n_("Must not be negative.")))
    return NonNegativeFloat(val)


@_add_typed_validator
def _decimal(
    val: Any, argname: str | None = None, *, large: bool = False, **kwargs: Any
) -> decimal.Decimal:
    """decimal.Decimal fitting into a `numeric` postgres column.

    :param large: specifies whether `numeric(8, 2)` or `numeric(11, 2)` is used
    """
    if isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            raise ValidationSummary(
                ValueError(argname, n_("Invalid input for decimal number."))
            ) from e
    if not isinstance(val, decimal.Decimal):
        raise ValidationSummary(TypeError(argname, n_("Must be a decimal.Decimal.")))
    if not large and abs(val) >= 1e6:
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a million."))
        )
    if abs(val) >= 1e9:
        raise ValidationSummary(
            ValueError(argname, n_("Must be smaller than a billion."))
        )
    return val


@_add_typed_validator
def _non_negative_decimal(
    val: Any, argname: str | None = None, **kwargs: Any
) -> NonNegativeDecimal:
    val = _decimal(val, argname, **kwargs)
    if val < 0:
        raise ValidationSummary(ValueError(argname, n_("Transfer saldo is negative.")))
    return NonNegativeDecimal(val)


@_add_typed_validator
def _positive_decimal(
    val: Any, argname: str | None = None, **kwargs: Any
) -> PositiveDecimal:
    val = _decimal(val, argname, **kwargs)
    if val <= 0:
        raise ValidationSummary(ValueError(argname, n_("Transfer saldo is negative.")))
    return PositiveDecimal(val)


@_add_typed_validator
def _str_type(
    val: Any,
    argname: str | None = None,
    *,
    zap: str = '',
    sieve: str = '',
    limit_size: bool = True,
    unicode_normalize: bool = True,
    **kwargs: Any,
) -> StringType:
    """
    :param zap: delete all characters in this from the result
    :param sieve: allow only the characters in this into the result
    """
    if val is not None:
        try:
            val = str(val)
        except (ValueError, TypeError) as e:
            raise ValidationSummary(
                ValueError(argname, n_("Invalid input for string."))
            ) from e
    if not isinstance(val, str):
        raise ValidationSummary(TypeError(argname, n_("Must be a string.")))
    if zap:
        val = ''.join(c for c in val if c not in zap)
    if sieve:
        val = ''.join(c for c in val if c in sieve)
    if unicode_normalize:
        val = unicodedata.normalize('NFC', val)
    val = val.replace("\r\n", "\n").replace("\r", "\n")
    if limit_size and len(val) > 256000:
        raise ValidationSummary(ValueError(argname, n_("Longer than 256 kB.")))
    return StringType(val)


@_add_typed_validator
def _str(val: Any, argname: str | None = None, **kwargs: Any) -> str:
    """Like :py:class:`_str_type` (parameters see there),
    but mustn't be empty (whitespace doesn't count).
    """
    val = _str_type(val, argname, **kwargs)
    if not val:
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return val


def _whitespace_normalized_str(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@_add_typed_validator
def _url(val: Any, argname: str | None = None, **kwargs: Any) -> Url:
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
def _bytes(
    val: Any, argname: str | None = None, *, encoding: str = "utf-8", **kwargs: Any
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
                ValueError(
                    argname,
                    n_("Cannot convert {val_type} to bytes."),
                    {'val_type': str(type(val))},
                )
            ) from e
    if not isinstance(val, bytes):
        raise ValidationSummary(TypeError(argname, n_("Must be a bytes object.")))
    return val


@_add_typed_validator
def _mapping(val: Any, argname: str | None = None, **kwargs: Any) -> Mapping:  # type: ignore[type-arg] # type parameters would break this (for now)
    if not isinstance(val, Mapping):
        raise ValidationSummary(TypeError(argname, n_("Must be a mapping.")))
    return val


@_add_typed_validator
def _iterable(val: Any, argname: str | None = None, **kwargs: Any) -> Iterable:  # type: ignore[type-arg] # type parameters would break this (for now)
    if not isinstance(val, Iterable):
        raise ValidationSummary(TypeError(argname, n_("Must be an iterable.")))
    return val


@_add_typed_validator
def _sequence(val: Any, argname: str | None = None, **kwargs: Any) -> Sequence:  # type: ignore[type-arg] # type parameters would break this (for now)
    try:
        val = tuple(val)
    except (ValueError, TypeError) as e:  # TODO what raises ValueError
        raise ValidationSummary(
            ValueError(argname, n_("Invalid input for sequence."))
        ) from e
    if not isinstance(val, Sequence):
        raise ValidationSummary(TypeError(argname, n_("Must be a sequence.")))
    return val


@_add_typed_validator
def _bool(val: Any, argname: str | None = None, **kwargs: Any) -> bool:
    if val is None:
        raise ValidationSummary(TypeError(argname, n_("Must be a boolean.")))

    if isinstance(val, str):
        if val.lower() in {"y", "yes", "true", "on", "1", "j", "ja", "wahr"}:
            return True
        if val.lower() in {"n", "no", "false", "off", "0", "f", "nein", "falsch"}:
            return False
    try:
        return bool(val)
    except (ValueError, TypeError) as e:
        raise ValidationSummary(
            ValueError(argname, n_("Invalid input for boolean."))
        ) from e


@_add_typed_validator  # TODO use Union of Literal
def _realm(
    val: Any,
    argname: str | None = None,
    supports_genesis: bool = False,
    **kwargs: Any,
) -> Realm:
    """A realm in the sense of the DB."""
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()
    with errs:
        if val not in {"session", "core", "cde", "event", "ml", "assembly"}:
            raise ValidationSummary(ValueError(argname, n_("Not a valid realm.")))
        if supports_genesis and val not in models_core.GenesisCase.available_realms:
            raise ValidationSummary(
                ValueError(n_("This realm is not supported for genesis."))
            )
    if errs:
        raise errs
    return Realm(val)


@_add_typed_validator
def _persona_id(val: Any, argname: str | None = None, **kwargs: Any) -> PersonaID:
    if isinstance(val, int):
        return _ALL_TYPED[ID](val, argname, **kwargs)
    val = _str(val, argname, **kwargs).strip()
    match = re.search('^DB-(?P<value>[0-9]*)-(?P<checkdigit>[0-9X])$', val)
    if not match:
        raise ValidationSummary(ValueError(argname, n_("Wrong formatting.")))

    value = _id(match["value"], argname, **kwargs)
    if compute_checkdigit(value) != match["checkdigit"]:
        raise ValidationSummary(ValueError(argname, n_("Checksum failure.")))
    return PersonaID(ID(value))


@_add_typed_validator
def _printable_ascii_type(
    val: Any, argname: str | None = None, **kwargs: Any
) -> PrintableASCIIType:
    val = _str_type(val, argname, **kwargs)
    if not re.search(r'^[ -~]*$', val):
        raise ValidationSummary(ValueError(argname, n_("Must be printable ASCII.")))
    return PrintableASCIIType(val)


@_add_typed_validator
def _printable_ascii(
    val: Any, argname: str | None = None, **kwargs: Any
) -> PrintableASCII:
    """Like :py:func:`_printable_ascii_type` (parameters see there),
    but must not be empty (whitespace doesn't count).
    """
    val = _printable_ascii_type(val, argname, **kwargs)
    if not val:  # TODO leave strip here?
        raise ValidationSummary(ValueError(argname, n_("Must not be empty.")))
    return PrintableASCII(val)


@_add_typed_validator
def _identifier(val: Any, argname: str | None = None, **kwargs: Any) -> Identifier:
    """Identifiers encompass everything from file names to short names for
    events.
    """
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9_.-]+$', val):
        raise ValidationSummary(
            ValueError(
                argname,
                n_(
                    "Must be an identifier (only letters,"
                    " numbers, underscore, dot and hyphen)."
                ),
            )
        )
    return Identifier(val)


@_add_typed_validator
def _restrictive_identifier(
    val: Any, argname: str | None = None, **kwargs: Any
) -> RestrictiveIdentifier:
    """Restrictive identifiers are for situations, where normal identifiers
    are too lax.

    One example are sql column names.
    """
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9_]+$', val):
        raise ValidationSummary(
            ValueError(
                argname,
                n_(
                    "Must be a restrictive identifier (only letters,"
                    " numbers and underscore)."
                ),
            )
        )
    return RestrictiveIdentifier(val)


@_add_typed_validator
def _csv_identifier(
    val: Any, argname: str | None = None, **kwargs: Any
) -> CSVIdentifier:
    val = _printable_ascii(val, argname, **kwargs)
    if not re.search(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$', val):
        raise ValidationSummary(
            ValueError(argname, n_("Must be comma separated identifiers."))
        )
    return CSVIdentifier(val)


@_add_typed_validator
def _token_string(val: Any, argname: str | None = None, **kwargs: Any) -> TokenString:
    val = _str(val, argname, **kwargs)
    if re.search(r'[\s()]', val):
        raise ValidationSummary(
            ValueError(argname, n_("Must not contain whitespace or parentheses."))
        )
    return TokenString(val)


@_add_typed_validator
def _base64(val: Any, argname: str | None = None, **kwargs: Any) -> Base64:
    val = _ALL_TYPED[str](val, argname, **kwargs)
    try:
        _ = base64.b64decode(val, b"-_", validate=True)
    except ValueError:
        raise ValidationSummary(
            ValueError(argname, n_("Invalid Base64 string."))
        ) from None

    return Base64(val)


@_create_dataclass_validator(models_core.AnonymousMessageData)
def _anonymous_message(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


# TODO manual handling of @_add_typed_validator inside decorator or storage?
@_add_typed_validator
def _list_of[T](
    val: Any,
    atype: type[T],
    argname: str | None = None,
    *,
    _allow_empty: bool = True,
    **kwargs: Any,
) -> list[T]:
    """
    Apply another validator to all entries of of a list.

    The input may be a comma-separated string.
    """
    if isinstance(val, str):
        # TODO use default separator from config here?
        # TODO use escaped_split?
        # Skip empty entries which can be produced by JavaScript.
        val = [v for v in val.split(",") if v]
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


class ListValidator[T](Protocol):
    def __call__(
        self, val: Any, argname: str | None = None, **kargs: Any
    ) -> list[T]: ...


def make_list_validator[T](type_: type[T]) -> ListValidator[T]:
    @functools.wraps(_list_of)
    def list_validator(val: Any, argname: str | None = None, **kwargs: Any) -> list[T]:
        return _list_of(val, type_, argname, **kwargs)

    return list_validator


class PairValidator[T](Protocol):
    def __call__(
        self, val: Any, argname: str | None = None, **kargs: Any
    ) -> tuple[T, T]: ...


def make_pair_validator[T](type_: type[T]) -> PairValidator[T]:
    @functools.wraps(_range)
    def pair_validator(
        val: Any, argname: str | None = None, **kwargs: Any
    ) -> tuple[T, T]:
        return _range(val, type_, argname, **kwargs)

    return pair_validator


class DictValidator[K, V](Protocol):
    def __call__(
        self, val: Any, argname: str | None = None, **kwargs: Any
    ) -> dict[K, V]: ...


def make_dict_validator[K, V](type_: type[dict[K, V]]) -> DictValidator[K, V]:
    """
    Given a type `dict[K, V]` create a validator to validate the keys of a mapping as K and the values as V.
    """

    if typing.get_origin(type_) is CdEDataclassMap:
        key_type, value_type = int, typing.get_args(type_)[0]
    else:
        key_type, value_type = typing.get_args(type_)

    def dict_validator(
        val: Any, argname: str | None = None, *, enumerate_: bool = False, **kwargs: Any
    ) -> dict[K, V]:
        val = _mapping(val, argname, **kwargs)

        errs = ValidationSummary()
        new_val = {}
        for i, (key_val, val_val) in enumerate(val.items()):
            key_argname = f"{argname or ''}.key"
            val_argname = f"{argname or ''}.value"
            if enumerate_:
                key_argname += str(i)
                val_argname += str(i)
            with errs.as_argname(key_argname):
                key_val = _ALL_TYPED[key_type](key_val, key_argname, **kwargs)
            with errs.as_argname(val_argname):
                val_val = _ALL_TYPED[value_type](val_val, val_argname, **kwargs)
            new_val[key_val] = val_val

        if errs:
            raise errs

        return new_val

    return dict_validator


def _set_of[T](
    val: Any, atype: type[T], argname: str | None = None, **kwargs: Any
) -> set[T]:
    list_type = list[atype]  # type: ignore[valid-type]
    return {v for v in _ALL_TYPED[list_type](val, argname, **kwargs)}


class SetValidator[T](Protocol):
    def __call__(
        self, val: Any, argname: str | None = None, **kwargs: Any
    ) -> set[T]: ...


def make_set_validator[T](type_: type[T]) -> SetValidator[T]:
    @functools.wraps(_set_of)
    def set_validator(val: Any, argname: str | None = None, **kwargs: Any) -> set[T]:
        return _set_of(val, type_, argname, **kwargs)

    return set_validator


@_add_typed_validator  # TODO split into Password and AdminPassword?
def _password_strength(
    val: Any,
    argname: str | None = None,
    *,
    admin: bool = False,
    inputs: list[str] | None = None,
    **kwargs: Any,
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
        errors.append(ValueError(argname, n_("Password too weak for admin account.")))

    if errors:
        raise errors

    return PasswordStrength(val)


@_add_typed_validator
def _api_token_string(
    val: Any, argname: str = "api_token_string", **kwargs: Any
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


@_create_dataclass_validator(models_droid.OrgaToken)
def _orga_token(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    errs = ValidationSummary()

    timestamp = now()
    if 'etime' in val:
        if val['etime'] and val['etime'] <= timestamp:
            with errs:
                raise ValidationSummary(
                    ValueError('etime', n_("Expiration time must be in the future."))
                )

    if errs:
        raise errs

    return val


@_add_typed_validator
def _email(val: Any, argname: str | None = None, **kwargs: Any) -> Email:
    """We accept only a subset of valid email addresses since implementing the
    full standard is horrendous. Also we normalize emails to lower case.
    """
    val = _printable_ascii(val, argname, **kwargs)
    # strip address and normalize to lower case
    val = val.strip().lower()
    if not re.search(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$', val):
        raise ValidationSummary(
            ValueError(argname, n_("Must be a valid email address."))
        )
    return Email(val)


@_add_typed_validator
def _email_local_part(
    val: Any, argname: str | None = None, **kwargs: Any
) -> EmailLocalPart:
    """We accept only a subset of valid email addresses.
    Here we only care about the local part.
    """
    val = _printable_ascii(val, argname, **kwargs)
    # strip address and normalize to lower case
    val = val.strip().lower()
    if not re.search(r'^[a-z0-9._+-]+$', val):
        raise ValidationSummary(
            ValueError(argname, n_("Must be a valid email local part."))
        )
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

PERSONA_BASE_CREATION: TypeMapping = {
    'username': Email,
    'notes': str | None,
    'nickname': NoneType,
    'given_names': str,
    'legal_given_names': str | None,
    'show_legal_given_names': bool,
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
    'title': str | None,
    'name_supplement': str | None,
    'show_legal_given_names': bool,
    'gender': const.Genders,
    'pronouns': str | None,
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Phone | None,
    'mobile': Phone | None,
    'address_supplement': str | None,
    'address': str | None,
    'show_address': bool,
    'postal_code': PrintableASCII | None,
    'location': str | None,
    'country': Country | None,
    'birth_name': str | None,
    'address_supplement2': str | None,
    'address2': str | None,
    'show_address2': bool,
    'postal_code2': PrintableASCII | None,
    'location2': str | None,
    'country2': Country | None,
    'weblink': str | None,
    'specialisation': str | None,
    'affiliation': str | None,
    'timeline': str | None,
    'interests': str | None,
    'free_form': str | None,
    'trial_member': bool,
    'honorary_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    # 'foto': str | None, # No foto -- this is another special
    'paper_expuls': bool,
    'donation': NonNegativeDecimal,
}

PERSONA_EVENT_CREATION: Mapping[str, Any] = {
    'title': str | None,
    'name_supplement': str | None,
    'gender': const.Genders,
    'pronouns': str | None,
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Phone | None,
    'mobile': Phone | None,
    'address_supplement': str | None,
    'address': str | None,
    'postal_code': PrintableASCII | None,
    'location': str | None,
    'country': Country | None,
}

PERSONA_FULL_CREATION: Mapping[str, Mapping[str, Any]] = {
    'ml': {**PERSONA_BASE_CREATION},
    'assembly': {**PERSONA_BASE_CREATION},
    'event': {**PERSONA_BASE_CREATION, **PERSONA_EVENT_CREATION},
    'cde': {
        **PERSONA_BASE_CREATION,
        **PERSONA_CDE_CREATION,
        'is_member': bool,
        'is_searchable': bool,
    },
}

PERSONA_COMMON_FIELDS: Mapping[str, Any] = {
    'username': Email,
    'notes': str | None,
    'is_meta_admin': bool,
    'is_core_admin': bool,
    'is_cde_admin': bool,
    'is_finance_admin': bool,
    'is_event_admin': bool,
    'is_ml_admin': bool,
    'is_assembly_admin': bool,
    'is_cdelokal_admin': bool,
    'is_complaint_admin': bool,
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
    'nickname': str | None,
    'given_names': str,
    'legal_given_names': str | None,
    'show_legal_given_names': bool,
    'family_name': str,
    'title': str | None,
    'name_supplement': str | None,
    'gender': const.Genders,
    'pronouns': str | None,
    'pronouns_nametag': bool,
    'pronouns_profile': bool,
    'birthday': Birthday,
    'telephone': Phone | None,
    'mobile': Phone | None,
    'address_supplement': str | None,
    'address': str | None,
    'show_address': bool,
    'postal_code': PrintableASCII | None,
    'location': str | None,
    'country': Country | None,
    'birth_name': str | None,
    'address_supplement2': str | None,
    'address2': str | None,
    'show_address2': bool,
    'postal_code2': PrintableASCII | None,
    'location2': str | None,
    'country2': Country | None,
    'weblink': str | None,
    'specialisation': str | None,
    'affiliation': str | None,
    'timeline': str | None,
    'interests': str | None,
    'free_form': str | None,
    'balance': NonNegativeDecimal,
    'donation': NonNegativeDecimal,
    'trial_member': bool,
    'honorary_member': bool,
    'decided_search': bool,
    'bub_search': bool,
    'foto': str | None,
    'paper_expuls': bool | None,
}


# TODO refactor to use the dataclass
# TODO get rid of all the persona dicts above
@_add_typed_validator
def _persona(
    val: Any,
    argname: str = "persona",
    *,
    creation: bool = False,
    transition: bool = False,
    ignore_warnings: bool = False,
    **kwargs: Any,
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
    val = _mapping(val, argname, ignore_warnings=ignore_warnings, **kwargs)

    if creation and transition:
        raise RuntimeError(n_("Only one of creation, transition may be specified."))

    if creation:
        temp = _examine_dictionary_fields(
            val,
            PERSONA_TYPE_FIELDS,
            {},
            allow_superfluous=True,
            ignore_warnings=ignore_warnings,
            **kwargs,
        )
        temp.update({'is_archived': False, 'is_purged': False})
        temp.update({k: False for k in ADMIN_KEYS})
        roles = extract_roles(temp)
        optional_fields: TypeMapping = {}
        mandatory_fields: dict[str, Any] = {
            **PERSONA_TYPE_FIELDS,
            **PERSONA_BASE_CREATION,
        }
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
            optional_fields |= {"is_member": bool}
    else:
        mandatory_fields = {'id': ID}
        optional_fields = PERSONA_COMMON_FIELDS
    val = _examine_dictionary_fields(
        val,
        mandatory_fields,
        optional_fields,
        ignore_warnings=ignore_warnings,
        **kwargs,
    )

    errs = ValidationSummary()
    if "is_member" in val and "trial_member" in val:
        if val["trial_member"] and not val["is_member"]:
            errs.append(
                ValueError("trial_member", n_("Trial membership requires membership."))
            )
    if "is_member" in val and "honorary_member" in val:
        if val["honorary_member"] and not val["is_member"]:
            errs.append(
                ValueError(
                    "honorary_member", n_("Honorary membership requires membership.")
                )
            )
    if "nickname" in val and "given_names" in val:
        if val["nickname"] == val["given_names"] and not ignore_warnings:
            errs.append(
                ValidationWarning(
                    "nickname",
                    n_("Nickname is equal to given names and should be removed."),
                )
            )
    if "legal_given_names" in val and "given_names" in val:
        if val["legal_given_names"] == val["given_names"] and not ignore_warnings:
            errs.append(
                ValidationWarning(
                    "legal_given_names",
                    n_(
                        "Legal given names are equal to given names and should be removed."
                    ),
                )
            )
    if "birth_name" in val and "family_name" in val:
        if val["birth_name"] == val["family_name"] and not ignore_warnings:
            errs.append(
                ValidationWarning(
                    "birth_name",
                    n_("Birth name is equal to family name and should be removed."),
                )
            )
    if supplement := val.get("name_supplement"):
        name_keys = ["given_names", "family_name", "legal_given_names", "nickname"]
        if any(val.get(key) and val[key] in supplement for key in name_keys):
            msg = n_("Should not contain (parts of) your name.")
            if not ignore_warnings:
                errs.append(ValidationWarning("name_supplement", msg))
    for suffix in ("", "2"):
        if val.get('postal_code' + suffix):
            with errs:
                postal_code = _german_postal_code(
                    val['postal_code' + suffix],
                    'postal_code' + suffix,
                    aux=val.get('country' + suffix, ""),
                    ignore_warnings=ignore_warnings,
                    **kwargs,
                )
                val['postal_code' + suffix] = postal_code
    if errs:
        raise errs

    return Persona(val)


@_add_typed_validator
def _batch_admission_entry(
    val: Any, argname: str | None = None, **kwargs: Any
) -> BatchAdmissionEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: dict[str, Any] = {
        'resolution': LineResolutions,
        'doppelganger_id': int | None,
        'pevent_id': int | None,
        'pcourse_id': int | None,
        'is_instructor': bool,
        'is_orga': bool,
        'update_username': bool,
        'persona': Any,  # TODO This should be more strict
    }
    optional_fields: TypeMapping = {}
    return BatchAdmissionEntry(
        _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)
    )


# TODO move this above _persona stuff?
@_add_typed_validator
def _date(val: Any, argname: str | None = None, **kwargs: Any) -> datetime.date:
    if isinstance(val, str) and len(val.strip()) >= 6:
        try:
            val = parse_date(val)
        except (ValueError, TypeError) as e:  # TODO TypeError should not occur
            raise ValidationSummary(
                ValueError(argname, n_("Invalid input for date."))
            ) from e
    # always convert datetime to date as psycopg will try to commit them as such
    # and every call to now() returns a datetime instead of a date
    if isinstance(val, datetime.datetime):
        val = val.date()
    if not isinstance(val, datetime.date):
        raise ValidationSummary(TypeError(argname, n_("Must be a datetime.date.")))
    return val


@_add_typed_validator
def _birthday(val: Any, argname: str | None = None, **kwargs: Any) -> Birthday:
    if not val:
        val = datetime.date.min
    val = _date(val, argname=argname, **kwargs)
    if now().date() < val:
        raise ValidationSummary(
            ValueError(argname, n_("A birthday must be in the past."))
        )
    return Birthday(val)


@_add_typed_validator
def _datetime(
    val: Any,
    argname: str | None = None,
    *,
    default_date: datetime.date | None = None,
    **kwargs: Any,
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
            raise ValidationSummary(
                ValueError(argname, n_("Invalid input for datetime."))
            ) from e
    if not isinstance(val, datetime.datetime):
        raise ValidationSummary(TypeError(argname, n_("Must be a datetime.datetime.")))
    if val.tzinfo is None:
        raise ValidationSummary(TypeError(argname, n_("Must be timezone aware.")))
    return val


# freezegun patches datetime objects so this allows the validator retrieval to still work.
_add_typed_validator(_date, freezegun.api.FakeDate)
_add_typed_validator(_datetime, freezegun.api.FakeDatetime)


@_add_typed_validator
def _timedelta(
    val: Any, argname: str | None = None, **kwargs: Any
) -> datetime.timedelta:
    """For simplicity, do not attempt to coerce this."""
    if not isinstance(val, datetime.timedelta):
        raise ValidationSummary(TypeError(argname, n_("Must be a datetime.timedelta.")))
    return val


@_add_typed_validator
def _single_digit_int(
    val: Any, argname: str | None = None, **kwargs: Any
) -> SingleDigitInt:
    """Like _int, but between +9 and -9."""
    val = _int(val, argname, **kwargs)
    if not -9 <= val <= 9:
        raise ValidationSummary(ValueError(argname, n_("More than one digit.")))
    return SingleDigitInt(val)


@_add_typed_validator
def _phone(
    val: Any,
    argname: str | None = None,
    *,
    ignore_warnings: bool = False,
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
        elif npe.error_type in {npe.TOO_SHORT_AFTER_IDD, npe.TOO_SHORT_NSN}:
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
    phone_str = normalize_phone(phone)

    return Phone(phone_str)


_GERMAN_POSTAL_CODES: set[str] = set()


@_add_typed_validator
def _german_postal_code(
    val: Any,
    argname: str | None = None,
    *,
    aux: str = "",
    ignore_warnings: bool = False,
    **kwargs: Any,
) -> GermanPostalCode:
    """
    :param aux: Additional information. In this case the country belonging
        to the postal code.
    :param ignore_warnings: If True, ignore invalid german postcodes.
    """
    val = _printable_ascii(val, argname, ignore_warnings=ignore_warnings, **kwargs)
    val = val.strip()
    if not aux or aux.strip() == "DE":
        msg = n_("Invalid german postal code.")
        if not (len(val) == 5 and val.isdigit()):
            raise ValidationSummary(ValueError(argname, msg))
        if not _GERMAN_POSTAL_CODES:
            repo_path: pathlib.Path = _CONFIG['REPOSITORY_PATH']
            _GERMAN_POSTAL_CODES.update(
                e['plz']
                for e in csv.DictReader(
                    (repo_path / "tests" / "ancillary_files" / "plz.csv")
                    .read_text()
                    .splitlines(),
                    delimiter=',',
                )
            )
        if val not in _GERMAN_POSTAL_CODES and not ignore_warnings:
            raise ValidationSummary(ValidationWarning(argname, msg))
    return GermanPostalCode(val)


@_add_typed_validator
def _country(
    val: Any,
    argname: str | None = None,
    *,
    ignore_warnings: bool = False,
    **kwargs: Any,
) -> Country:
    val = _ALL_TYPED[str](val, argname, ignore_warnings=ignore_warnings, **kwargs)
    # TODO be more strict and do not strip
    val = val.strip()
    if val not in COUNTRY_CODES:
        raise ValidationSummary(
            ValueError(argname, n_("Enter actual country name in English."))
        )
    return Country(val)


@_create_dataclass_validator(
    models_core.GenesisCaseMl, models_core.GenesisCaseEvent, models_core.GenesisCaseCdE
)
def _genesis_case(
    val: Any,
    argname: str = "genesis_case",
    *,
    ignore_warnings: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    errs = ValidationSummary()

    with errs:
        if val.get('postal_code'):
            postal_code = _german_postal_code(
                val['postal_code'],
                'postal_code',
                aux=val.get('country', ""),
                ignore_warnings=ignore_warnings,
                **kwargs,
            )
            val['postal_code'] = postal_code

        if birthday := val.get('birthday'):
            if (now().date() - birthday) < datetime.timedelta(days=365):
                if not ignore_warnings:
                    raise ValidationSummary(
                        ValidationWarning(
                            'birthday',
                            n_(
                                "Birthday was less than a year ago."
                                " Please check the birth year."
                            ),
                        )
                    )

    if errs:
        raise errs

    return val


PRIVILEGE_CHANGE_COMMON_FIELDS: TypeMapping = {
    'persona_id': ID,
    'submitted_by': ID,
    'status': const.PrivilegeChangeStati,
    'notes': str,
}

PRIVILEGE_CHANGE_OPTIONAL_FIELDS: TypeMapping = {k: bool | None for k in ADMIN_KEYS}


@_add_typed_validator
def _privilege_change(
    val: Any, argname: str = "privilege_change", **kwargs: Any
) -> PrivilegeChange:
    val = _mapping(val, argname, **kwargs)

    val = _examine_dictionary_fields(
        val, PRIVILEGE_CHANGE_COMMON_FIELDS, PRIVILEGE_CHANGE_OPTIONAL_FIELDS, **kwargs
    )

    return PrivilegeChange(val)


# TODO also move these up?
@_add_typed_validator
def _input_file(val: Any, argname: str | None = None, **kwargs: Any) -> InputFile:
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
    val: Any,
    argname: str | None = None,
    *,
    encoding: str = "utf-8-sig",
    **kwargs: Any,
) -> CSVFile:
    """
    Validate a CSV file.

    We default to 'utf-8-sig', since it behaves exactly like 'utf-8' if the
    file is 'utf-8' but it gets rid of the BOM if the file is 'utf-8-sig'.
    """
    val = _input_file(val, argname, **kwargs)
    mime = magic.from_buffer(val, mime=True)
    if mime not in {"text/csv", "text/plain", "application/csv"}:
        raise ValidationSummary(ValueError(argname, n_("Only text/csv allowed.")))
    val = _str(val.decode(encoding).strip(), argname, **kwargs)
    return CSVFile(val)


@_add_typed_validator
def _profilepic(
    val: Any, argname: str | None = None, *, file_storage: bool = True, **kwargs: Any
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
    if len(val) < 2**10:
        errs.append(ValueError(argname, n_("Too small.")))
    if len(val) > 2**17:
        errs.append(ValueError(argname, n_("Too big.")))

    mime = magic.from_buffer(val, mime=True)
    if mime not in {"image/jpeg", "image/jpg", "image/png"}:
        errs.append(ValueError(argname, n_("Only jpg and png allowed.")))
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
    val: Any, argname: str | None = None, *, file_storage: bool = True, **kwargs: Any
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
    if len(val) > 2**23:  # Disallow files bigger than 8 MB.
        errs.append(ValueError(argname, n_("Filesize too large.")))
    mime = magic.from_buffer(val, mime=True)
    if mime != "application/pdf":
        errs.append(ValueError(argname, n_("Only pdf allowed.")))

    if errs:
        raise errs

    return PDFFile(val)


@_add_typed_validator
def _pair_of_int(val: Any, argname: str = "pair", **kwargs: Any) -> tuple[int, int]:
    """Validate a pair of integers."""

    val = _list_of(val, int, argname, **kwargs)

    try:
        a, b = val
    except ValueError as e:
        raise ValidationSummary(
            ValueError(argname, n_("Must contain exactly two elements."))
        ) from e

    # noinspection PyRedundantParentheses
    return (a, b)


@_add_typed_validator
def _period(val: Any, argname: str = "period", **kwargs: Any) -> Period:
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
        'state': ID | None,
        'done': datetime.datetime,
        'count': NonNegativeInt,
        'trialmembers': NonNegativeInt,
        'total': NonNegativeDecimal,
        'balance': NonNegativeDecimal,
        'exmembers': NonNegativeDecimal,
    }

    optional_fields = {
        f"{pre}_{suf}": type_map[suf]
        for pre, suffixes in prefix_map.items()
        for suf in suffixes
    }

    return Period(
        _examine_dictionary_fields(val, {'id': ID}, optional_fields, **kwargs)
    )


@_add_typed_validator
def _expuls(val: Any, argname: str = "expuls", **kwargs: Any) -> ExPuls:
    val = _mapping(val, argname, **kwargs)

    # TODO make these public?
    optional_fields: TypeMapping = {
        'addresscheck_state': ID | None,
        'addresscheck_done': datetime.datetime,
        'addresscheck_count': NonNegativeInt,
    }
    return ExPuls(
        _examine_dictionary_fields(val, {'id': ID}, optional_fields, **kwargs)
    )


LASTSCHRIFT_COMMON_FIELDS: Mapping[str, Any] = {
    'iban': IBAN,
    'account_owner': str | None,
    'account_address': str | None,
    'notes': str | None,
}

LASTSCHRIFT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'granted_at': datetime.datetime,
    'revoked_at': datetime.datetime | None,
}


@_add_typed_validator
def _lastschrift(
    val: Any, argname: str = "lastschrift", *, creation: bool = False, **kwargs: Any
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
        optional_fields = {**LASTSCHRIFT_COMMON_FIELDS, **LASTSCHRIFT_OPTIONAL_FIELDS}
    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)
    return Lastschrift(val)


@_add_typed_validator
def _money_transfer_entry(
    val: Any,
    argname: str = "money_transfer_entry",
    *,
    event_only: bool = False,
    **kwargs: Any,
) -> MoneyTransferEntry:
    val = _mapping(val, argname, **kwargs)
    mandatory_fields: TypeMapping = {
        'persona_id': int,
        'registration_id': int if event_only else int | None,
        'amount': decimal.Decimal,
        'date': datetime.date,
    }
    return MoneyTransferEntry(
        _examine_dictionary_fields(val, mandatory_fields, {}, **kwargs)
    )


# TODO move above
@_add_typed_validator
def _iban(val: Any, argname: str = "iban", **kwargs: Any) -> IBAN:
    val = _str(val, argname, **kwargs).upper().replace(' ', '')
    errs = ValidationSummary()

    if len(val) < 5:
        errs.append(ValueError(argname, n_("Too short.")))
        raise errs

    country_code, check_digits, bban = val[:2], val[2:4], val[4:]

    for char in country_code:
        if char not in string.ascii_uppercase:
            errs.append(ValueError(argname, n_("Must start with country code.")))
    for char in check_digits:
        if char not in string.digits:
            errs.append(ValueError(argname, n_("Must have digits for checksum.")))
    for char in bban:
        if char not in string.digits + string.ascii_uppercase:
            errs.append(ValueError(argname, n_("Invalid character in IBAN.")))
    if country_code not in IBAN_LENGTHS:
        errs.append(ValueError(argname, n_("Unknown or unsupported Country Code.")))

    if not errs:
        if len(val) != IBAN_LENGTHS[country_code]:
            errs.append(
                ValueError(
                    argname,
                    n_(
                        "Invalid length %(len)s for Country Code %(code)s."
                        " Expexted length %(exp)s."
                    ),
                    {
                        "len": len(val),
                        "code": country_code,
                        "exp": IBAN_LENGTHS[country_code],
                    },
                )
            )
        temp = ''.join(
            c if c in string.digits else str(10 + ord(c) - ord('A'))
            for c in bban + country_code + check_digits
        )
        if int(temp) % 97 != 1:
            errs.append(ValueError(argname, n_("Invalid checksum.")))

    if errs:
        raise errs

    return IBAN(val)


SEPA_TRANSACTIONS_FIELDS: TypeMapping = {
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
            entry = _examine_dictionary_fields(entry, mandatory_fields, {}, **kwargs)
        except ValidationSummary as e:
            errs.extend(e)
            continue

        for attribute, validator in SEPA_TRANSACTIONS_FIELDS.items():
            if validator is _str:
                entry[attribute] = asciificator(entry[attribute])
            if attribute in SEPA_TRANSACTIONS_LIMITS:
                if len(entry[attribute]) > SEPA_TRANSACTIONS_LIMITS[attribute]:
                    errs.append(ValueError(attribute, n_("Too long.")))

        if entry['type'] not in {"OOFF", "FRST", "RCUR"}:
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
    'original_glaeubigerid': str | None,
}

SEPA_META_LIMITS: Mapping[str, int] = {
    'message_id': 35,
    # 'name': 70, easier to check by hand
    # 'address': 70, has to be checked by hand
    'glaeubigerid': 35,
    'original_glaeubigerid': 35,
}


@_add_typed_validator
def _sepa_meta(val: Any, argname: str = "sepa_meta", **kwargs: Any) -> SepaMeta:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = {**SEPA_META_FIELDS}
    val = _examine_dictionary_fields(val, mandatory_fields, {}, **kwargs)

    mandatory_fields = {**SEPA_SENDER_FIELDS}
    val['sender'] = _examine_dictionary_fields(
        val['sender'], mandatory_fields, {}, **kwargs
    )

    errs = ValidationSummary()
    for attribute, validator in SEPA_META_FIELDS.items():
        if validator is str:
            val[attribute] = asciificator(val[attribute])
        if attribute in SEPA_META_LIMITS:
            if val[attribute] and len(val[attribute]) > SEPA_META_LIMITS[attribute]:
                errs.append(ValueError(attribute, n_("Too long.")))

    if val['sender']['country'] != "DE":
        errs.append(ValueError('country', n_("Unsupported constant.")))
    if len(val['sender']['address']) != 2:
        errs.append(ValueError('address', n_("Exactly two lines required.")))
    val['sender']['address'] = tuple(map(asciificator, val['sender']['address']))

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


@_create_dataclass_validator(models_core.MetaInfo)
def _meta_info(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


@_create_dataclass_validator(models_past_event.PastEvent)
def _past_event(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


def _optional_object_mapping_helper[T](
    val_dict: Mapping[Any, Any],
    atype: TypeForm[T],
    argname: str,
    creation_only: bool,
    **kwargs: Any,
) -> Mapping[int, T | None]:
    """Helper to validate a `CdEDBOptionalMap` of a given type.

    The map may contain positive or negative IDs. Positive IDs may be either None,
    indicating an existing object should be deleted, or a partial dataset containing
    changes to an existing object. Negative IDs should contain a full dataset for
    creation of a new object.

    :param creation_only: If True, only allow negative IDs.
    """
    ret: dict[int, T | None] = {}
    errs = ValidationSummary()
    # remove id_ from kwargs to make nested calls to this helper possible
    kwargs = dict(kwargs)
    if "id_" in kwargs:
        del kwargs["id_"]
    for anid, val in val_dict.items():
        with errs:
            anid = _ALL_TYPED[PartialImportID](anid, argname, **kwargs)
            creation = anid < 0
            if creation_only and not creation:
                raise ValidationSummary(
                    ValueError(argname, n_("Only creation allowed."))
                )
            type_ = cast(TypeForm[T], atype if creation else atype | None)
            ret[anid] = _ALL_TYPED[type_](
                val, argname, creation=creation, id_=anid, **kwargs
            )

    if errs:
        raise errs
    return ret


@_create_dataclass_validator(models_event.Event)
def _event(
    val: Any, argname: str = "event", *, creation: bool = False, **kwargs: Any
) -> CdEDBObject:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """
    if creation:
        kwargs['event'] = None

    errs = ValidationSummary()

    configuration_keys: set[str] = set().union(
        *map(
            dict.keys,  # type: ignore[arg-type]
            models_event._EventConfigurationMixin.validation_fields(creation=creation),
        )
    )
    configuration_fields = {k: v for k, v in val.items() if k in configuration_keys}
    if configuration_fields:
        with errs:
            configuration_fields = _ALL_TYPED[models_event._EventConfigurationMixin](
                configuration_fields, creation=creation, **kwargs
            )
            val.update(configuration_fields)

    if 'parts' in val:
        with errs:
            val['parts'] = _optional_object_mapping_helper(
                val['parts'],
                models_event.EventPart,
                'parts',
                creation_only=creation,
                **kwargs,
            )

    if 'fields' in val:
        with errs:
            val['fields'] = _optional_object_mapping_helper(
                val['fields'],
                models_event.EventField,
                'fields',
                creation_only=creation,
                **kwargs,
            )

    if 'lodgement_groups' in val:
        with errs:
            val['lodgement_groups'] = _optional_object_mapping_helper(
                val['lodgement_groups'],
                models_event.LodgementGroup,
                'lodgement_groups',
                creation_only=creation,
                nested_creation=creation,
                **kwargs,
            )

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.EventPart)
def _event_part(
    val: CdEDBObject,
    argname: str = "event_part",
    *,
    event: models_event.Event | None,
    creation: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()
    part_begin = val.get("part_begin")
    part_end = val.get("part_end")
    if creation is False and event:
        part_begin = part_begin or event.parts[kwargs["id_"]].part_begin
        part_end = part_end or event.parts[kwargs["id_"]].part_end
    if part_begin and part_end and part_begin > part_end:
        errs.append(ValueError("part_end", n_("Must be later than begin.")))

    if 'tracks' in val:
        with errs:
            val['tracks'] = _optional_object_mapping_helper(
                val['tracks'],
                models_event.CourseTrack,
                'tracks',
                creation_only=creation,
                event=event,
                **kwargs,
            )

    if waitlist_field_id := val.get("waitlist_field_id"):
        if not event or waitlist_field_id not in event.fields:
            errs.append(KeyError("waitlist_field_id", n_("Unknown waitlist field.")))
        else:
            waitlist_field = event.fields[waitlist_field_id]
            if not models_event.EventFieldSpec.field_accepts_association(
                models_event.EventPart, "waitlist", waitlist_field.association
            ):
                errs.append(
                    ValueError(
                        "waitlist_field_id",
                        n_("Waitlist field must be a registration field."),
                    )
                )
            if not models_event.EventFieldSpec.field_accepts_kind(
                models_event.EventPart, "waitlist", waitlist_field.kind
            ):
                errs.append(
                    ValueError(
                        "waitlist_field_id",
                        n_("Waitlist field must have type 'Integer'."),
                    )
                )

    if camping_mat_field_id := val.get("camping_mat_field_id"):
        if not event or camping_mat_field_id not in event.fields:
            errs.append(
                KeyError("camping_mat_field_id", n_("Unknown camping mat field."))
            )
        else:
            camping_mat_field = event.fields[camping_mat_field_id]
            if not models_event.EventFieldSpec.field_accepts_association(
                models_event.EventPart, "camping_mat", camping_mat_field.association
            ):
                errs.append(
                    ValueError(
                        "camping_mat_field_id",
                        n_("Camping mat field must be a registration field."),
                    )
                )
            if not models_event.EventFieldSpec.field_accepts_kind(
                models_event.EventPart, "camping_mat", camping_mat_field.kind
            ):
                errs.append(
                    ValueError(
                        "camping_mat_field_id",
                        n_("Camping mat field must have type 'Yes/No'."),
                    )
                )

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.PartGroup)
def _event_part_group(
    val: CdEDBObject,
    argname: str = "part_group",
    *,
    event: models_event.Event,
    creation: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()
    if val.get("part_ids") and not val["part_ids"] <= event.parts.keys():
        errs.append(ValueError("part_ids", n_("Unknown part.")))

    old_title = set()
    old_shortname = set()
    if creation is False:
        part_group = event.part_groups.get(val["id"])
        if part_group:
            old_title = {part_group.title}
            old_shortname = {part_group.shortname}

    if val.get("title") in {pg.title for pg in event.part_groups.values()} - old_title:
        errs.append(
            ValueError('title', n_("A part group with this name already exists."))
        )
    existing = {pg.shortname for pg in event.part_groups.values()}
    if val.get('shortname') in existing - old_shortname:
        errs.append(
            ValueError('shortname', n_("A part group with this name already exists."))
        )

    shortname = val.get("shortname") or event.part_groups[val["id"]].shortname
    constraint_type = (
        val.get("constraint_type") or event.part_groups[val["id"]].constraint_type
    )
    if constraint_type == const.EventPartGroupType.mailinglist_link:
        with errs:
            val["shortname"] = _ALL_TYPED[EmailLocalPart](
                shortname, "shortname", **kwargs
            )

    if errs:
        raise errs
    return val


@_create_dataclass_validator(models_event.CourseTrack)
def _event_track(
    val: Any,
    argname: str = "tracks",
    *,
    event: models_event.Event,
    creation: bool = False,
    id_: int,
    **kwargs: Any,
) -> CdEDBObject:
    if creation:
        min_choices = val["min_choices"]
        num_choices = val["num_choices"]
    else:
        track = event.tracks[id_]
        min_choices = val.get("min_choices", track.min_choices)
        num_choices = val.get("num_choices", track.num_choices)

    errs = ValidationSummary()

    if min_choices > num_choices:
        errs.append(
            ValueError(
                "min_choices", n_("Must be less or equal than total Course Choices.")
            )
        )

    if course_room_field_id := val.get("course_room_field_id"):
        if not event or course_room_field_id not in event.fields:
            errs.append(
                KeyError("course_room_field_id", n_("Unknown course room field."))
            )
        else:
            course_room_field = event.fields[course_room_field_id]
            if not models_event.EventFieldSpec.field_accepts_association(
                models_event.CourseTrack, "course_room", course_room_field.association
            ):
                errs.append(
                    ValueError(
                        "course_room_field_id",
                        n_("Course room field must be a course field."),
                    )
                )
            if not models_event.EventFieldSpec.field_accepts_kind(
                models_event.CourseTrack, "course_room", course_room_field.kind
            ):
                errs.append(
                    ValueError(
                        "course_room_field_id",
                        n_("Course room field mut have type 'Text'."),
                    )
                )

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.TrackGroup)
def _event_track_group(
    val: CdEDBObject,
    argname: str = "track_group",
    *,
    event: models_event.Event,
    creation: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()
    if creation:
        if "track_ids" not in val or not val["track_ids"]:
            errs.append(ValueError('track_ids', n_("Must not be empty.")))
        elif not val["track_ids"] <= event.tracks.keys():
            errs.append(ValueError("track_ids", n_("Unknown track.")))
        elif val["constraint_type"].is_sync():
            if any(
                tg.constraint_type.is_sync() and set(tg.tracks) & val["track_ids"]
                for tg in event.track_groups.values()
            ):
                errs.append(
                    ValueError(
                        "track_ids",
                        n_(
                            "Cannot have more than one course choice sync track group per track."
                        ),
                    )
                )
            track_choice_configs = set(
                (event.tracks[track_id].num_choices, event.tracks[track_id].min_choices)
                for track_id in val["track_ids"]
            )
            if len(track_choice_configs) != 1:
                errs.append(
                    ValueError(
                        "track_ids",
                        n_(
                            "Tracks of a course choice sync track group must have the same"
                            " number of choices."
                        ),
                    )
                )

    old_title = set()
    old_shortname = set()
    if creation is False:
        track_group = event.track_groups.get(val["id"])
        if track_group:
            old_title = {track_group.title}
            old_shortname = {track_group.shortname}

    if val.get("title") in {tg.title for tg in event.track_groups.values()} - old_title:
        errs.append(
            ValueError('title', n_("A track group with this name already exists."))
        )
    existing = {tg.shortname for tg in event.track_groups.values()}
    if val.get('shortname') in existing - old_shortname:
        errs.append(
            ValueError('shortname', n_("A track group with this name already exists."))
        )

    if errs:
        raise errs
    return val


def _prepare_event_field(
    val: CdEDBObject,
    *,
    field_name: str | None = None,
    creation: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    val = dict(val)

    if field_name is not None:
        val["field_name"] = field_name
    if creation:
        if not val.get("title"):
            val["title"] = val.get("field_name")

    return val


@_create_dataclass_validator(models_event.EventField, _prepare=_prepare_event_field)
def _event_field_dataclass(
    val: CdEDBObject,
    argname: str,
    *,
    event: models_event.Event,
    creation: bool = False,
    id_: int,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()

    if creation:
        kind = val.get("kind")
    else:
        kind = val.get("kind", event.fields[id_].kind)
    assert kind is not None

    if entries := val.get("entries"):
        if isinstance(entries, str):
            try:
                entries = list(
                    (split[0].strip(), split[1].strip())
                    for line in entries.splitlines()
                    if line.strip() and (split := line.split(";", 1))
                )
            except (ValueError, IndexError) as e:
                raise ValidationSummary(
                    ValueError("entries", n_("Value not well-formed."))
                ) from e
        raw_length = len(entries)
        if isinstance(entries, Sequence):
            try:
                entries = dict(entries)
            except ValueError as e:
                raise ValidationSummary(
                    ValueError("entries", n_("Could not convert sequence to dict."))
                ) from e

        with errs.as_argname("entries"):
            new_entries = _ALL_TYPED[dict[ByFieldDatatype, str]](
                entries, "entries", kind=kind, enumerate_=True, **kwargs
            )
            new_entries = normalize_field_entries(new_entries, kind)

            if new_entries is None or len(new_entries) != raw_length:
                errs.append(ValueError("entries", n_("Duplicate value(s).")))

            val["entries"] = new_entries
    else:
        val["entries"] = None

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.EventFee)
def _event_fee(
    val: Any,
    argname: str,
    *,
    current: models_event.EventFee | None,
    event: models_event.Event,
    personalized: bool | None = None,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()
    if current is not None and personalized is None:
        personalized = current.amount is None or current.condition is None

    if personalized is not None:
        if personalized:
            if val.get('amount') is not None:
                errs.append(
                    ValueError('amount', n_("Cannot set amount for personalized fee."))
                )
            if val.get('condition') is not None:
                errs.append(
                    ValueError(
                        'condition', n_("Cannot set condition for personalized fee.")
                    )
                )
        else:
            if 'amount' in val and val['amount'] is None:
                errs.append(
                    ValueError('amount', n_("Cannot unset amount for conditional fee."))
                )
            if 'condition' in val and val['condition'] is None:
                errs.append(
                    ValueError(
                        'condition', n_("Cannot unset condition for conditional fee.")
                    )
                )
    elif (val['amount'] is None) != (val['condition'] is None):
        for k in ('amount', 'condition'):
            errs.append(
                ValueError(k, n_("Cannot have amount without condition or vice versa."))
            )

    if "title" in val:
        val["title"] = _whitespace_normalized_str(val["title"])

        titles = {fee.title: fee.id for fee in event.fees.values()}

        err = ValueError("title", n_("Duplicate title."))
        if current is None:
            if val["title"] in titles:
                errs.append(err)
        elif titles.get(val["title"], current.id) != current.id:
            errs.append(err)

    if errs:
        raise errs

    return val


@_add_typed_validator
def _event_fee_condition(
    val: Any,
    argname: str = "event_fee_condition",
    *,
    event: models_event.Event,
    all_questionnaires: models_event.questionnaire.QuestionnaireContainer,
    **kwargs: Any,
) -> EventFeeCondition:
    val = _str(val, argname, **kwargs)

    field_usage = all_questionnaires.field_usage()
    field_names = {
        f.field_name
        for f in event.registration_fields.values()
        if f.kind == const.FieldDatatypes.bool
        and field_usage.get(
            f.id, const.QuestionnaireUsages.registration
        ).allow_fee_condition()
    }
    part_names = {p.shortname for p in event.parts.values()}

    try:
        parse_result = fcp_parsing.parse(val)
        fcp_evaluation.check(parse_result, field_names, part_names)
    except Exception as e:
        raise ValidationSummary(ValueError(argname, e.args[-1])) from e

    return EventFeeCondition(fcp_roundtrip.serialize(parse_result))


@_create_dataclass_validator(models_past_event.PastCourse)
def _past_course(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


@_create_dataclass_validator(
    models_event.Course, association=const.FieldAssociations.course
)
def _course(
    val: CdEDBObject,
    argname: str = "course",
    *,
    creation: bool = False,
    event: models_event.Event,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()

    if not event.tracks:
        errs.append(ValueError("event_id", n_("Event without tracks forbids courses.")))

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.CourseSegment)
def _course_segment(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


REGISTRATION_COMMON_FIELDS: Mapping[str, Any] = {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': str | None,
    'parts': Mapping,
    'tracks': Mapping,
}

REGISTRATION_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'parental_agreement': bool,
    'real_persona_id': ID | None,
    'orga_notes': str | None,
    'fields': Mapping,
}


@_add_typed_validator
def _registration(
    val: Any, argname: str = "registration", *, creation: bool = False, **kwargs: Any
) -> Registration:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(REGISTRATION_COMMON_FIELDS, persona_id=ID, event_id=ID)
        optional_fields = {**REGISTRATION_OPTIONAL_FIELDS}
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {'id': ID}
        optional_fields = {**REGISTRATION_COMMON_FIELDS, **REGISTRATION_OPTIONAL_FIELDS}

    # The check of fields is performed later via EventAssociatedFields.
    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    if 'parts' in val:
        newparts: dict[int, RegistrationPart | None] = {}
        for anid, part in val['parts'].items():
            try:
                anid = _id(anid, 'parts', **kwargs)
                part = _ALL_TYPED[RegistrationPart | None](part, 'parts', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newparts[anid] = part
        val['parts'] = newparts
    if 'tracks' in val:
        newtracks: dict[int, RegistrationTrack | None] = {}
        for anid, track in val['tracks'].items():
            try:
                anid = _id(anid, 'tracks', **kwargs)
                track = _ALL_TYPED[RegistrationTrack | None](track, 'tracks', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newtracks[anid] = track
        val['tracks'] = newtracks

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
        'lodgement_id': ID | None,
        'is_camping_mat': bool,
    }
    return RegistrationPart(
        _examine_dictionary_fields(val, {}, optional_fields, **kwargs)
    )


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
        'course_id': ID | None,
        'course_instructor': ID | None,
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
    val: Any,
    argname: str = "fields",
    *,
    event: models_event.Event,
    association: FieldAssociations,
    **kwargs: Any,
) -> EventAssociatedFields:
    """Check fields associated to an event entity.

    This can be used for all different kinds of entities (currently
    registration, courses and lodgements) via the multiplexing in form of
    the ``association`` parameter.

    :param fields: definition of the event specific fields which are available
    """

    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        str(field.field_name): field.get_validator()
        for field in event.fields.values()
        if field.association == association
    }

    val = _examine_dictionary_fields(val, {}, optional_fields, **kwargs)

    errs = ValidationSummary()
    lookup: dict[str, int] = {v.field_name: k for k, v in event.fields.items()}
    for field_name, value in val.items():
        field_id = lookup[field_name]
        entries = event.fields[field_id].entries
        if entries is not None and value is not None:
            if value not in entries:
                errs.append(ValueError(field_name, n_("Entry not in definition list.")))
    if errs:
        raise errs

    return EventAssociatedFields(val)


@_create_dataclass_validator(models_event.LodgementGroup)
def _lodgement_group(
    val: CdEDBObject,
    argname: str = "lodgement_group",
    *,
    creation: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    return val


@_create_dataclass_validator(
    models_event.Lodgement, association=const.FieldAssociations.lodgement
)
def _lodgement(
    val: CdEDBObject,
    argname: str = "lodgement",
    *,
    creation: bool = False,
    event: models_event.Event,
    groups: models_event.CdEDataclassMap[models_event.LodgementGroup],
    create_new_group: bool = False,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()

    if create_new_group:
        if (
            "group_id" not in val
            or val["group_id"] != models_event.LODGEMENT_GROUP_PLACEHOLDER_ID
        ):
            errs.append(
                ValueError(
                    "group_id", n_("Invalid placeholder for new lodgement group.")
                )
            )
    elif "group_id" in val and val["group_id"] not in groups:
        errs.append(
            ValueError("group_id", n_("Unknown lodgement group for this event."))
        )

    if errs:
        raise errs

    return val


@_add_typed_validator
def _by_field_datatype(
    val: Any,
    argname: str,
    *,
    kind: FieldDatatypes,
    **kwargs: Any,
) -> ByFieldDatatype:
    if val is None or val == "":  # noqa: PLC1901
        return ByFieldDatatype(None)

    kind = FieldDatatypes(kind)
    val = _ALL_TYPED[models_event.EventField._get_validator(kind)](
        val, argname, **kwargs
    )

    return ByFieldDatatype(val)


@_create_dataclass_validator(
    models_event.questionnaire.QuestionnaireTextRow,
    models_event.questionnaire.QuestionnaireHeadingRow,
    models_event.questionnaire.QuestionnairePanelRow,
)
def _questionnaire_text_row(
    val: CdEDBObject, argname: str = "", **kwargs: Any
) -> CdEDBObject:
    return val


@_create_dataclass_validator(models_event.questionnaire.QuestionnaireFieldRow)
def _questionnaire_field_row(
    val: CdEDBObject,
    argname: str = "",
    *,
    available_fields: CdEDataclassMap[models_event.EventField],
    **kwargs: Any,
) -> CdEDBObject:

    errs = ValidationSummary()
    kind = const.QuestionnaireUsages(val["kind"])

    # The questionnaire import allows specifying fields by name instead of id.
    #  This method is not used elsewhere.
    fields_by_name = {f.field_name: f.id for f in available_fields.values()}

    if field_name := val.get("field_name"):
        val["field_id"] = fields_by_name.get(field_name)
        if not val["field_id"]:
            errs.append(
                KeyError(
                    'field_name',
                    n_("Unknown field name: '%(field_name)s'."),
                    {"field_name": field_name},
                )
            )
    if "field_id" not in val:
        val["field_id"] = None

    if field_id := val.get("field_id"):
        if not (field := available_fields.get(field_id)):
            errs.append(KeyError('field_id', n_("Invalid field.")))
        if val.get('default_value') and field:
            val['default_value'] = _by_field_datatype(
                val['default_value'],
                "default_value",
                kind=field.kind,
                **kwargs,
            )
            # TODO: check field entries.
    else:
        errs.append(ValueError("field_id", "Must not be empty."))
        # remove default value without a linked field
        if val.get('default_value'):
            val['default_value'] = None

    if val.get('readonly') and not kind.allow_readonly():
        # TODO: more generic error message?
        msg = n_("Registration questionnaire rows may not be readonly.")
        errs.append(ValueError('readonly', msg))

    if errs:
        raise errs

    return val


@_create_dataclass_validator(
    models_event.questionnaire.CourseChoices,
    models_event.questionnaire.PartSelection,
    models_event.questionnaire.FeePreview,
    models_event.questionnaire.ListConsent,
    models_event.questionnaire.MixedLodging,
    models_event.questionnaire.FotoNotice,
    models_event.questionnaire.RegistrationNotes,
    models_event.questionnaire.TableOfContents,
    models_event.questionnaire.MyData,
)
def _questionnaire_magic_row(
    val: CdEDBObject,
    argname: str = "",
    *,
    available_magic_roles: set[const.QuestionnaireRowRole],
    **kwargs: Any,
) -> CdEDBObject:

    errs = ValidationSummary()
    role: const.QuestionnaireRowRole = val["role"]

    if role not in available_magic_roles:
        errs.append(KeyError("role", n_("Invalid magic role.")))

    if errs:
        raise errs

    return val


@_create_dataclass_validator(
    models_event.questionnaire.QuestionnaireRow,  # type: ignore[type-abstract]
    allow_superfluous=True,
    pass_superfluous=True,
)
def _questionnaire_row(
    val: CdEDBObject,
    argname: str = "",
    *,
    allow_superfluous: bool,
    pass_superfluous: bool,
    **kwargs: Any,
) -> CdEDBObject:
    tmp = _examine_dictionary_fields(
        val,
        {"role": const.QuestionnaireRowRole},
        allow_superfluous=True,
        **kwargs,
    )
    cls = models_event.questionnaire.QuestionnaireRow.get_class(tmp["role"])
    return _ALL_TYPED[cls](val, **kwargs)


@_add_typed_validator
def _questionnaire(
    val: Any,
    argname: str = "questionnaire",
    *,
    kind: const.QuestionnaireUsages,
    all_questionnaires: models_event.questionnaire.QuestionnaireContainer,
    **kwargs: Any,
) -> Questionnaire:
    val = _ALL_TYPED[list[dict[str, Any]]](val, argname, **kwargs)

    event = all_questionnaires.event
    available_fields = all_questionnaires.get_available_fields(kind)
    available_magic_roles = all_questionnaires.get_available_magic_roles(kind)

    # Map list position to "id" to display errors at the correct place in the frontend.
    pos_to_id = {}

    errs = ValidationSummary()
    ret: list[CdEDBObject] = []
    for i, row in enumerate(val):
        with errs.modify_argname(suffix=f"_{row.get('id', i)}"):
            # See 'pos_to_id' above.
            if "id" in row:
                pos_to_id[i] = row.pop("id")

            row["kind"] = kind
            row["pos"] = i
            row = _ALL_TYPED[models_event.questionnaire.QuestionnaireRow](
                row,
                available_fields=available_fields,
                available_magic_roles=available_magic_roles,
            )
            ret.append(row)

    for e1, e2 in itertools.combinations(ret, 2):
        if e1.get('field_id') is not None and e1.get('field_id') == e2.get('field_id'):
            msg = n_("Must not duplicate field: '%(field_name)s'")
            params = {'field_name': event.fields[e1['field_id']].field_name}
            errs.extend([
                ValueError(
                    f'field_id_{pos_to_id.get(e1["pos"], e1["pos"])}', msg, params
                ),
                ValueError(
                    f'field_id_{pos_to_id.get(e2["pos"], e2["pos"])}', msg, params
                ),
            ])

    magic_role_counts = collections.Counter(row["role"] for row in ret if "role" in row)

    for magic_role in const.QuestionnaireRowRole:
        count = magic_role_counts[magic_role]
        role_class = magic_role.get_class()
        allowed_frequency = role_class.allowed_frequency(kind)
        if count == 0 and not allowed_frequency.allows(count):
            # count > 0 already checked.
            errs.append(
                ValueError(
                    argname,
                    n_("Missing role: '%(magic_role)s'."),
                    {"magic_role": role_class.__name__},
                ),
            )
        if count > 1 and not role_class.static:
            for pos, row in enumerate(ret):
                if row["role"] == magic_role:
                    # If we have ids, adjust the error argname.
                    idx = pos_to_id.get(pos, pos)
                    errs.append(
                        ValueError(
                            f"role_{idx}",
                            n_("Must not duplicate this role: '%(magic_role)s'."),
                            {"magic_role": role_class.__name__},
                        ),
                    )

    if errs:
        raise errs

    return Questionnaire(ret)


# TODO move above
@_add_typed_validator
def _json(val: Any, argname: str = "json", **kwargs: Any) -> JSON:
    """Deserialize a JSON payload.

    This is a bit different from many other validatiors in that it is not
    idempotent.
    """
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8")  # TODO remove encoding argument?
        except UnicodeDecodeError as e:
            raise ValidationSummary(
                ValueError(argname, n_("Invalid UTF-8 sequence."))
            ) from e
    val = _str(val, argname, **kwargs, limit_size=False)
    try:
        data = json.loads(val)
    except json.decoder.JSONDecodeError as e:
        msg = n_("Invalid JSON syntax (line %(line)s, col %(col)s).")
        raise ValidationSummary(
            ValueError(argname, msg, {'line': e.lineno, 'col': e.colno})
        ) from e
    return JSON(data)


@_add_typed_validator
def _serialized_partial_event_upload(
    val: Any, argname: str = "serialized_partial_event_upload", **kwargs: Any
) -> SerializedPartialEventUpload:
    """Check an event data set for delta import."""
    val = _input_file(val, argname, **kwargs)
    val = _json(val, argname, **kwargs)

    return SerializedPartialEventUpload(
        _serialized_partial_event(val, argname, **kwargs)
    )


@_add_typed_validator
def _serialized_partial_event(
    val: Any, argname: str = "serialized_partial_event", **kwargs: Any
) -> SerializedPartialEvent:
    """Check an event data set for delta import."""
    # First a basic check
    val = _mapping(val, argname, **kwargs)

    if 'kind' not in val or val['kind'] != "partial":
        raise ValidationSummary(
            KeyError(argname, n_("Only partial exports are supported."))
        )

    mandatory_fields: TypeMapping = {
        'EVENT_SCHEMA_VERSION': tuple[int, int],
        'kind': str,
        'id': ID,
    }
    optional_fields: TypeMapping = {
        'event': Mapping,  # ignored, but allowed to be present.
        'courses': Mapping,
        'lodgement_groups': Mapping,
        'lodgements': Mapping,
        'registrations': Mapping,
        'summary': str,
        'timestamp': datetime.datetime,
    }

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    if not (
        (EVENT_SCHEMA_VERSION[0], 0)
        <= val['EVENT_SCHEMA_VERSION']
        <= EVENT_SCHEMA_VERSION
    ):
        raise ValidationSummary(ValueError(argname, n_("Schema version mismatch.")))

    domain_validators: TypeMapping = {
        'courses': PartialCourse | None,
        'lodgement_groups': PartialLodgementGroup | None,
        'lodgements': PartialLodgement | None,
        'registrations': PartialRegistration | None,
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
                    entry, domain, creation=creation, **kwargs
                )
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
    'description': str | None,
    'nr': str | None,
    'shortname': str,
    'instructors': str | None,
    'max_size': int | None,
    'min_size': int | None,
    'notes': str | None,
    'is_visible': bool | None,
}

PARTIAL_COURSE_OPTIONAL_FIELDS: TypeMapping = {
    'segments': Mapping,
    'fields': EventAssociatedFields,
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
        optional_fields = {
            **PARTIAL_COURSE_COMMON_FIELDS,
            **PARTIAL_COURSE_OPTIONAL_FIELDS,
        }

    # The check of fields is delegated to EventAssociatedFields.
    val = _examine_dictionary_fields(
        val,
        mandatory_fields,
        optional_fields,
        **dict(kwargs, association=const.FieldAssociations.course),
    )

    errs = ValidationSummary()
    if 'segments' in val:
        new_dict = {}
        for key, entry in val['segments'].items():
            try:
                new_key = _int(key, 'segments', **kwargs)
                new_entry: bool | None = _ALL_TYPED[bool | None](
                    entry, 'segments', **kwargs
                )
            except ValidationSummary as e:
                errs.extend(e)
            else:
                new_dict[new_key] = new_entry
        val['segments'] = new_dict

    if errs:
        raise errs

    return PartialCourse(val)


PARTIAL_LODGEMENT_GROUP_FIELDS: TypeMapping = {'title': str}


# TODO difference between partial and non-partial lodgement groups?
@_add_typed_validator
def _partial_lodgement_group(
    val: Any, argname: str = "lodgement_group", *, creation: bool = False, **kwargs: Any
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

    return PartialLodgementGroup(
        _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)
    )


PARTIAL_LODGEMENT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'regular_capacity': NonNegativeInt,
    'camping_mat_capacity': NonNegativeInt,
    'notes': str | None,
    'group_id': PartialImportID | None,
}

PARTIAL_LODGEMENT_OPTIONAL_FIELDS: TypeMapping = {'fields': EventAssociatedFields}


@_add_typed_validator
def _partial_lodgement(
    val: Any, argname: str = "lodgement", *, creation: bool = False, **kwargs: Any
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
        optional_fields = {
            **PARTIAL_LODGEMENT_COMMON_FIELDS,
            **PARTIAL_LODGEMENT_OPTIONAL_FIELDS,
        }

    # The check of fields is delegated to EventAssociatedFields.
    val = _examine_dictionary_fields(
        val,
        mandatory_fields,
        optional_fields,
        **dict(kwargs, association=const.FieldAssociations.lodgement),
    )

    return PartialLodgement(val)


PARTIAL_REGISTRATION_COMMON_FIELDS: Mapping[str, Any] = {
    'mixed_lodging': bool,
    'list_consent': bool,
    'notes': str | None,
    'parts': Mapping,
    'tracks': Mapping,
}

PARTIAL_REGISTRATION_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'parental_agreement': bool | None,
    'orga_notes': str | None,
    'fields': EventAssociatedFields,
    'personalized_fees': Mapping,
    'checkin_periods': list[ReducedCheckinPeriod],
}

# May be present, but will be ignored:
PARTIAL_REGISTRATION_IGNORED_FIELDS = {
    # Ignored to ensure consistent bookkeeping:
    'amount_paid',
    'payment',
    'is_member',
    # Ignored because they are calculated, derived or external values:
    'amount_owed',
    'amount_owed_by_kind',
    'amount_owed_by_category',
    'amount_owed_by_budget',
    'persona',
    'ctime',
    'mtime',
}

# TODO Can we auto generate all these partial validators?


@_add_typed_validator
def _partial_registration(
    val: Any, argname: str = "registration", *, creation: bool = False, **kwargs: Any
) -> PartialRegistration:
    """
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    """

    val = _mapping(val, argname, **kwargs)

    if creation:
        mandatory_fields = dict(PARTIAL_REGISTRATION_COMMON_FIELDS, persona_id=ID)
        optional_fields = {
            **PARTIAL_REGISTRATION_OPTIONAL_FIELDS,
            **{key: Any for key in PARTIAL_REGISTRATION_IGNORED_FIELDS},
        }
    else:
        # no event_id/persona_id, since associations should be fixed
        mandatory_fields = {}
        optional_fields = {
            **PARTIAL_REGISTRATION_COMMON_FIELDS,
            **PARTIAL_REGISTRATION_OPTIONAL_FIELDS,
            **{key: Any for key in PARTIAL_REGISTRATION_IGNORED_FIELDS},
        }

    # The check of fields is delegated to EventAssociatedFields.
    val = _examine_dictionary_fields(
        val,
        mandatory_fields,
        optional_fields,
        **dict(kwargs, association=const.FieldAssociations.registration),
    )

    errs = ValidationSummary()
    for key in PARTIAL_REGISTRATION_IGNORED_FIELDS:
        if key in val:
            del val[key]
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
        newfees: dict[int, decimal.Decimal | None] = {}
        for fee_id, amount in val['personalized_fees'].items():
            try:
                fee_id = _id(fee_id, 'personalized_fees', **kwargs)
                amount = _ALL_TYPED[decimal.Decimal | None](
                    amount, 'personalized_fees', **kwargs
                )
            except ValidationSummary as e:
                errs.extend(e)
            else:
                newfees[fee_id] = amount
        val['personalized_fees'] = newfees
    if 'checkin_periods' in val:
        new_checkin_periods: list[ReducedCheckinPeriod] = []
        for period in val['checkin_periods']:
            try:
                period = _partial_registration_checkin_period(period, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                new_checkin_periods.append(period)
        # Now sort the list and check whether it is consistent.
        new_checkin_periods = xsorted(new_checkin_periods, key=lambda x: x.checkin_time)

        try:
            is_consistent = all(
                p.checkin_time < p.checkout_time < next_p.checkin_time  # type: ignore[operator]
                for p, next_p in zip(new_checkin_periods, new_checkin_periods[1:])
            )
        except TypeError:
            # checkout_time == None for non-final checkin period
            errs.append(
                ValueError(
                    n_("Checkout time may only be empty for latest checkin period.")
                )
            )
        else:
            if not is_consistent:
                errs.append(ValueError(n_("Inconsistent sequence of checkin periods.")))
            else:
                val['checkin_periods'] = new_checkin_periods

    if errs:
        raise errs

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
        'lodgement_id': PartialImportID | None,
        'is_camping_mat': bool,
    }

    return PartialRegistrationPart(
        _examine_dictionary_fields(val, {}, optional_fields, **kwargs)
    )


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
        'course_id': PartialImportID | None,
        'course_instructor': PartialImportID | None,
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
def _partial_registration_checkin_period(
    val: Any, argname: str = "partial_registration_checkin_period", **kwargs: Any
) -> ReducedCheckinPeriod:
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.
    """

    if isinstance(val, ReducedCheckinPeriod):
        if val.checkout_time and val.checkin_time >= val.checkout_time:
            raise ValueError(n_("Checkout must be after checkin."))
        return val

    val = _mapping(val, argname, **kwargs)

    mandatory_fields: TypeMapping = {
        'checkin_time': datetime.datetime,
        'checkout_time': datetime.datetime | None,
    }

    val = _examine_dictionary_fields(val, mandatory_fields, {}, **kwargs)

    if val['checkout_time'] and val['checkin_time'] >= val['checkout_time']:
        raise ValueError(n_("Checkout must be after checkin."))

    return ReducedCheckinPeriod(**PartialRegistrationCheckinPeriod(val))


@_add_typed_validator
def _serialized_event_questionnaire_upload(
    val: Any, argname: str = "serialized_event_questionnaire_upload", **kwargs: Any
) -> SerializedEventQuestionnaireUpload:
    val = _input_file(val, argname, **kwargs)
    val = _json(val, argname, **kwargs)
    return SerializedEventQuestionnaireUpload(
        _serialized_event_questionnaire(val, argname, **kwargs)
    )


# TODO: adjust or drop:


@_add_typed_validator
def _serialized_event_questionnaire(
    val: Any,
    argname: str = "serialized_event_questionnaire",
    *,
    all_questionnaires: models_event.questionnaire.QuestionnaireContainer,
    extend_questionnaire: bool,
    skip_existing_fields: bool,
    **kwargs: Any,
) -> SerializedEventQuestionnaire:  # pragma: no cover
    val = _mapping(val, argname, **kwargs)

    optional_fields: TypeMapping = {
        'fields': dict[str, dict[str, Any]],
        'questionnaire': dict[const.QuestionnaireUsages, list[dict[str, Any]]],
    }
    val = _examine_dictionary_fields(val, {}, optional_fields, **kwargs)

    all_questionnaires = copy.deepcopy(all_questionnaires)
    fields_by_name = {f.field_name: f for f in all_questionnaires.event.fields.values()}

    errs = ValidationSummary()
    if 'fields' in val:
        newfields: CdEDBObjectMap = {}
        for i, (field_name, field_data) in enumerate(val['fields'].items()):
            field_argname = f"fields[{field_name}]"
            field_data["field_name"] = field_name
            if field_name in fields_by_name:
                if not skip_existing_fields:
                    errs.append(
                        KeyError(
                            field_argname, n_("A field with this name already exists.")
                        )
                    )
                continue
            with errs:
                field_data = _ALL_TYPED[models_event.EventField](
                    field_data,
                    field_argname,
                    creation=True,
                    event=all_questionnaires.event,
                    id_=-(i + 1),
                    **kwargs,
                )
                newfields[-(i + 1)] = field_data
        val['fields'] = newfields

        all_questionnaires.event.fields |= {
            f_id: models_event.EventField.get_class(f["association"])(
                id=ID(f_id), event_id=all_questionnaires.event.id, **f
            )
            for f_id, f in newfields.items()
        }
        fields_by_name = {
            f.field_name: f for f in all_questionnaires.event.fields.values()
        }
    else:
        val['fields'] = {}

    if 'questionnaire' in val:
        new_questionnaires = {}
        for kind, rows in val['questionnaire'].items():
            if extend_questionnaire:
                new_questionnaires[kind] = all_questionnaires[kind].as_dicts() + rows
            else:
                new_questionnaires[kind] = rows
            with errs.modify_argname(prefix=f"questionnaire[{kind.name}]."):
                new_questionnaires[kind] = _ALL_TYPED[Questionnaire](
                    new_questionnaires[kind],
                    kind=kind,
                    all_questionnaires=all_questionnaires,
                )
                all_questionnaires[kind] = models_event.questionnaire.Questionnaire(
                    (
                        models_event.questionnaire.QuestionnaireRow.get_class(
                            row["role"]
                        )(
                            event_id=all_questionnaires.event.id,
                            **{k: v for k, v in row.items() if k != "field_name"},
                        )
                        for row in new_questionnaires[kind]
                    ),
                    kind=kind,
                )
        for kind, existing in all_questionnaires.items():
            if kind not in new_questionnaires:
                new_questionnaires[kind] = existing.as_dicts()
        val['questionnaire'] = new_questionnaires
    else:
        val['questionnaire'] = {}

    if errs:
        raise errs

    return SerializedEventQuestionnaire(val)


@_create_dataclass_validator(models_event._EventConfigurationMixin)  # type: ignore[type-abstract]
def _serialized_event_configuration(
    val: Any,
    argname: str,
    *,
    creation: bool = False,
    event: models_event.Event | None,
    **kwargs: Any,
) -> CdEDBObject:
    current = event
    errs = ValidationSummary()

    # Check IBAN to be valid
    valid_ibans = Accounts.get_event_accounts()
    if val.get('iban') and val['iban'] not in valid_ibans:
        with errs:
            raise ValidationSummary(
                ValueError("iban", n_("Must be a registered event IBAN."))
            )

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
            raise ValidationSummary(
                ValueError(
                    "registration_start", n_("Must be before hard and soft limit.")
                )
            )
    if soft and hard and soft > hard:
        with errs:
            raise ValidationSummary(
                ValueError(
                    "registration_soft_limit", "Must be before or equal to hard limit."
                )
            )

    # Check field association
    if lodge_field := val.get('lodge_field_id'):
        if not current or lodge_field not in current.fields:
            errs.append(KeyError("lodge_field_id", n_("Unknown lodge field.")))
        else:
            field = current.fields[lodge_field]
            if not models_event.EventFieldSpec.field_accepts_association(
                models_event.Event, "lodge", field.association
            ):
                errs.append(
                    ValueError(
                        "lodge_field_id",
                        n_("Lodge field must be a registration field."),
                    )
                )
            if not models_event.EventFieldSpec.field_accepts_kind(
                models_event.Event, "lodge", field.kind
            ):
                errs.append(
                    ValueError(
                        "lodge_field_id", n_("Lodge field must have type 'Text'.")
                    )
                )
    if reimbursement_field := val.get('reimbursement_iban_field_id'):
        if not current or reimbursement_field not in current.fields:
            errs.append(
                KeyError(
                    "reimbursement_iban_field_id",
                    n_("Unknown reimbursement IBAN field."),
                )
            )
        else:
            field = current.fields[reimbursement_field]
            if not models_event.EventFieldSpec.field_accepts_association(
                models_event.Event, "reimbursement_iban", field.association
            ):
                errs.append(
                    ValueError(
                        "reimbursement_iban_field_id",
                        n_("Reimbursement IBAN field must be a registration field."),
                    )
                )
            if not models_event.EventFieldSpec.field_accepts_kind(
                models_event.Event, "reimbursement_iban", field.kind
            ):
                errs.append(
                    ValueError(
                        "reimbursement_iban_field_id",
                        n_("Reimbursement IBAN field must have type 'IBAN'."),
                    )
                )

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event._EventFreetextMixin)  # type: ignore[type-abstract]
def _serialized_event_freetexts(val: Any, argname: str, **kwargs: Any) -> CdEDBObject:
    return val


@_create_dataclass_validator(*models_ml.ML_TYPE_MAP_INV.keys())
def _mailinglist(
    val: CdEDBObject, *args: Any, type_: models_ml.MLType, **kwargs: Any
) -> CdEDBObject:
    errs = ValidationSummary()

    if "moderators" in val and not val["moderators"]:
        errs.append(ValueError("moderators", n_("Must not be empty.")))

    if "domain" not in val:
        errs.append(
            ValueError("domain", "Must specify domain for setting mailinglist.")
        )
    elif val["domain"].value not in type_.available_domains:
        errs.append(
            ValueError("domain", n_("Invalid domain for this mailinglist type."))
        )

    if not val.get('event_id'):
        if val.get('event_part_group_id'):
            errs.append(
                ValueError(
                    "event_id", n_("Cannot have event part group without event.")
                )
            )

    if errs:
        raise errs

    return val


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

    return SubscriptionIdentifier(
        _examine_dictionary_fields(val, mandatory_fields, **kwargs)
    )


@_add_typed_validator
def _subscription_dataset(
    val: Any, argname: str = "subscription_dataset", **kwargs: Any
) -> SubscriptionDataset:
    val = _mapping(val, argname, **kwargs)

    # TODO instead of deepcopy simply do not mutate mandatory_fields
    # TODO or use function returning the dict everywhere instead
    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}
    mandatory_fields.update(SUBSCRIPTION_STATE_FIELDS)

    return SubscriptionDataset(
        _examine_dictionary_fields(val, mandatory_fields, **kwargs)
    )


@_add_typed_validator
def _subscription_address(
    val: Any, argname: str = "subscription address", **kwargs: Any
) -> SubscriptionAddress:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = {**SUBSCRIPTION_ID_FIELDS}
    mandatory_fields.update(SUBSCRIPTION_ADDRESS_FIELDS)

    return SubscriptionAddress(
        _examine_dictionary_fields(val, mandatory_fields, **kwargs)
    )


ASSEMBLY_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    # Assembly shortnames do not actually need to be that short.
    'shortname': Identifier,
    'description': str | None,
    'signup_end': datetime.datetime,
    'notes': str | None,
}

ASSEMBLY_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'is_active': bool,
    'presider_address': Email | None,
    'presiders': Iterable,
}


@_add_typed_validator
def _assembly(
    val: Any, argname: str = "assembly", *, creation: bool = False, **kwargs: Any
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

    return Assembly(
        _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)
    )


BALLOT_COMMON_FIELDS: Mapping[str, Any] = {
    'title': str,
    'description': str | None,
    'vote_begin': datetime.datetime,
    'vote_end': datetime.datetime,
    'notes': str | None,
    'use_bar': bool,
}

BALLOT_EXPOSED_OPTIONAL_FIELDS: Mapping[str, Any] = {
    'vote_extension_end': datetime.datetime | None,
    'abs_quorum': int,
    'rel_quorum': int,
    'votes': PositiveInt | None,
}

BALLOT_EXPOSED_FIELDS = {**BALLOT_COMMON_FIELDS, **BALLOT_EXPOSED_OPTIONAL_FIELDS}

BALLOT_OPTIONAL_FIELDS: Mapping[str, Any] = {
    **BALLOT_EXPOSED_OPTIONAL_FIELDS,
    'extended': bool | None,
    'is_tallied': bool,
    'candidates': Mapping,
    'linked_attachments': list[ID | None] | None,
}


@_add_typed_validator
def _ballot(
    val: Any, argname: str = "ballot", *, creation: bool = False, **kwargs: Any
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

    val = _examine_dictionary_fields(val, mandatory_fields, optional_fields, **kwargs)

    errs = ValidationSummary()
    # TODO why are all these nested?
    if 'vote_begin' in val:
        if val['vote_begin'] <= now():
            errs.append(ValueError("vote_begin", n_("Mustn’t be in the past.")))
        if 'vote_end' in val:
            if val['vote_end'] <= val['vote_begin']:
                errs.append(
                    ValueError(
                        "vote_end", n_("Mustn’t be before start of voting period.")
                    )
                )
            if 'vote_extension_end' in val and val['vote_extension_end']:
                if val['vote_extension_end'] <= val['vote_end']:
                    errs.append(
                        ValueError(
                            "vote_extension_end",
                            n_("Mustn’t be before end of voting period."),
                        )
                    )

    if 'candidates' in val:
        newcandidates: dict[int, BallotCandidate | None] = {}
        for anid, candidate in val['candidates'].items():
            try:
                anid = _int(anid, 'candidates', **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
            else:
                creation = anid < 0
                try:
                    candidate = _ALL_TYPED[BallotCandidate | None](
                        candidate, 'candidates', creation=creation, **kwargs
                    )
                except ValidationSummary as e:
                    errs.extend(e)
                else:
                    newcandidates[anid] = candidate
        titles = [
            candidate["title"] for candidate in newcandidates.values() if candidate
        ]
        shortnames = [
            candidate["shortname"] for candidate in newcandidates.values() if candidate
        ]
        if len(titles) != len(set(titles)):
            errs.append(ValueError("candidates.title", n_("Duplicate title.")))
        if len(shortnames) != len(set(shortnames)):
            errs.append(ValueError("candidates.shortname", n_("Duplicate shortname.")))
        val['candidates'] = newcandidates

    if val.get('abs_quorum') and val.get('rel_quorum'):
        msg = n_("Must not specify both absolute and relative quorum.")
        errs.extend([ValueError('abs_quorum', msg), ValueError('rel_quorum', msg)])

    quorum = val.get('abs_quorum')
    if 'rel_quorum' in val and not quorum:
        quorum = val['rel_quorum']
        if not 0 <= quorum <= 100:
            errs.append(
                ValueError(
                    "abs_quorum", n_("Relative quorum must be between 0 and 100.")
                )
            )

    vote_extension_error = ValueError(
        "vote_extension_end", n_("Must be specified if quorum is given.")
    )

    quorum_msg = n_("Must specify a quorum if vote extension end is given.")
    quorum_errors = [
        ValueError("abs_quorum", quorum_msg),
        ValueError("rel_quorum", quorum_msg),
    ]

    # The first part of each condition ensures that either both of extension end and
    # quorum are given or none of them, while the second part of the condition checks
    # whether the values are compatible if both are present.
    if (
        ('vote_extension_end' in val and quorum is None)
        or (val.get('vote_extension_end') and not quorum)
    ):  # fmt: skip
        # Quorum key missing and vote extension end key given
        # or trivial quorum given, but non-empty extension end provided
        errs.extend(quorum_errors)
    elif (
        (quorum is not None and 'vote_extension_end' not in val)
        or (quorum and not val.get('vote_extension_end'))
    ):  # fmt: skip
        # Extension end key missing and quorum key given
        # or empty extension end, but non-trivial quorum provided
        errs.append(vote_extension_error)

    if errs:
        raise errs

    return Ballot(val)


BALLOT_CANDIDATE_COMMON_FIELDS: TypeMapping = {
    'title': str,
    'shortname': RestrictiveIdentifier,
}


@_add_typed_validator
def _ballot_candidate(
    val: Any,
    argname: str = "ballot_candidate",
    *,
    creation: bool = False,
    ignore_warnings: bool = False,
    **kwargs: Any,
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

    val = _examine_dictionary_fields(
        val,
        mandatory_fields,
        optional_fields,
        ignore_warnings=ignore_warnings,
        **kwargs,
    )

    errs = ValidationSummary()
    if val.get('shortname') == ASSEMBLY_BAR_SHORTNAME:
        errs.append(ValueError("shortname", n_("Mustn’t be the bar shortname.")))
    if "title" in val:
        val["title"] = _whitespace_normalized_str(val["title"])

    if errs:
        raise errs

    return BallotCandidate(val)


ASSEMBLY_ATTACHMENT_FIELDS: Mapping[str, Any] = {'assembly_id': ID}


ASSEMBLY_ATTACHMENT_VERSION_FIELDS: Mapping[str, Any] = {
    'title': str,
    'authors': str | None,
    'filename': str,
    'changenotes': str | None,
    'file_hash': str,
}


@_add_typed_validator
def _assembly_attachment(
    val: Any, argname: str = "assembly_attachment", **kwargs: Any
) -> AssemblyAttachment:
    val = _mapping(val, argname, **kwargs)

    mandatory_fields = dict(
        ASSEMBLY_ATTACHMENT_VERSION_FIELDS, **ASSEMBLY_ATTACHMENT_FIELDS
    )

    val = _examine_dictionary_fields(val, mandatory_fields, **kwargs)

    return AssemblyAttachment(val)


@_add_typed_validator
def _assembly_attachment_version(
    val: Any,
    argname: str = "assembly_attachment_version",
    creation: bool = False,
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
    val: Any, argname: str = "vote", ballot: CdEDBObject | None = None, **kwargs: Any
) -> Vote:
    """Validate a single voters intent.

    This is mostly made complicated by the fact that we offer to emulate
    ordinary voting instead of full preference voting.

    :param ballot: Ballot the vote was cast for.
    """
    val = _str(val, argname, **kwargs)
    errs = ValidationSummary()
    if not ballot:
        errs.append(RuntimeError(n_("Must specify ballot in order to validate vote.")))
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
        if ASSEMBLY_BAR_SHORTNAME in voted and voted != (ASSEMBLY_BAR_SHORTNAME,):
            errs.append(ValueError(argname, n_("Misplaced bar.")))
        if errs:
            raise errs

    return Vote(val)


# TODO move above
@_add_typed_validator
def _regex(val: Any, argname: str | None = None, **kwargs: Any) -> Regex:
    val = _str(val, argname, **kwargs)
    try:
        re.compile(val)
    except re.error as e:
        # TODO maybe provide more precise feedback?
        raise ValidationSummary(
            ValueError(
                argname,
                n_("Invalid  regular expression (position %(pos)s)."),
                {'pos': e.pos},
            )
        )
        # TODO wait for mypy to ship updated typeshed
    return Regex(val)


@_add_typed_validator
def _non_regex(val: Any, argname: str | None = None, **kwargs: Any) -> NonRegex:
    val = _str(val, argname, **kwargs)
    forbidden_chars = r'\*+?{}()[]|'
    msg = n_(
        "Must not contain any forbidden characters"
        " (which are %(forbidden_chars)s while .^$ are allowed)."
    )
    if any(char in val for char in forbidden_chars):
        raise ValidationSummary(
            ValueError(argname, msg, {"forbidden_chars": forbidden_chars})
        )
    return NonRegex(val)


@_create_dataclass_validator(models_event.CustomQueryFilter)
def _custom_query_filter(
    val: Any,
    argname: str = "custom_query_filter",
    *,
    creation: bool = False,
    query_spec: QuerySpec,
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()

    if len(val['fields']) < 2:
        with errs:
            raise ValidationSummary(
                ValueError('field', n_("Combine a minimum of two fields."))
            )
    if any(field not in query_spec for field in val['fields']):
        with errs:
            raise ValidationSummary(
                KeyError(
                    'field',
                    n_("Unknown field(s): %(fields)s."),
                    {'fields': ", ".join(val['fields'] - set(query_spec))},
                )
            )
    elif len({query_spec[f].type for f in val['fields']}) != 1:
        with errs:
            raise ValidationSummary(TypeError('field', n_("Incompatible field types.")))

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_event.StoredEventQuery)
def _stored_query(
    val: CdEDBObject,
    argname: str,
    *,
    creation: bool = False,
    spec: QuerySpec,
    **kwargs: Any,
) -> CdEDBObject:
    val["serialized_query"] = val["serialized_query"].serialize()
    return val


@_add_typed_validator
def _query_input(
    val: Any,
    argname: str | None = None,
    *,
    spec: QuerySpec,
    allow_empty: bool = False,
    separator: str = ',',
    escape: str = '\\',
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
    query_id: ID | None = None
    if val.get("query_id"):
        query_id = _ALL_TYPED[ID](val["query_id"], "query_id", **kwargs)
    fields_of_interest = []
    constraints: list[QueryConstraint] = []
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
            operator: QueryOperators | None = _ALL_TYPED[QueryOperators | None](
                val.get(f"qop_{field}"), field, **kwargs
            )
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if not operator:
            continue

        if operator not in VALID_QUERY_OPERATORS[validator]:
            errs.append(ValueError(field, n_("Invalid operator for this field.")))
            continue

        if operator in NO_VALUE_OPERATORS:
            constraints.append((field, operator, None))
            continue

        # Get value
        value = val.get(f"qval_{field}")
        if not value:
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
                type_ = cast(TypeForm[Any], QUERY_INPUT_VALIDATORS[validator] | None)
                try:
                    vv: Any = _ALL_TYPED[type_](v, field, passthrough=True, **kwargs)
                except ValidationSummary as e:
                    errs.extend(e)
                    continue

                if operator in {
                    QueryOperators.containsall,
                    QueryOperators.containssome,
                    QueryOperators.containsnone,
                }:
                    try:
                        vv = _non_regex(vv, field, **kwargs)
                    except ValidationSummary as e:
                        errs.extend(e)
                        continue

                assert vv is not None
                value.append(vv)

            if not value:
                continue

            if (
                operator in {QueryOperators.between, QueryOperators.outside}
                and len(value) != 2
            ):
                errs.append(ValueError(field, n_("Two endpoints required.")))
                continue

        elif operator in {QueryOperators.match, QueryOperators.unmatch}:
            # TODO remove all _or_None in this validator!
            try:
                value = _ALL_TYPED[NonRegex | None](value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        elif operator in {QueryOperators.regex, QueryOperators.notregex}:
            try:
                value = _ALL_TYPED[Regex | None](value, field, **kwargs)
            except ValidationSummary as e:
                errs.extend(e)
                continue
        else:
            type_ = cast(TypeForm[Any], QUERY_INPUT_VALIDATORS[validator] | None)
            try:
                value = _ALL_TYPED[type_](value, field, passthrough=True, **kwargs)
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
            entry: CSVIdentifier | None = _ALL_TYPED[CSVIdentifier | None](
                val[f"qord_{postfix}"], f"qord_{postfix}", **kwargs
            )
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

    return QueryInput(
        Query(scope, dict(spec), fields_of_interest, constraints, order, name, query_id)
    )


# TODO ignore ignore_warnings here too?
@_add_typed_validator
def _query(val: Any, argname: str | None = None, **kwargs: Any) -> Query:
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
                operator, f"constraints/{field}", **kwargs
            )
        except ValidationSummary as e:
            errs.extend(e)
            continue

        if operator not in VALID_QUERY_OPERATORS[val.spec[field].type]:
            errs.append(ValueError(f"constraints/{field}", n_("Invalid operator.")))
            continue

        type_ = cast(TypeForm[Any], QUERY_INPUT_VALIDATORS[val.spec[field].type] | None)
        if operator in NO_VALUE_OPERATORS:
            value = None

        elif operator in MULTI_VALUE_OPERATORS:
            for v in value:
                with errs:
                    _ALL_TYPED[type_](
                        v, f"constraints/{field}", passthrough=True, **kwargs
                    )
        else:
            try:
                _ALL_TYPED[type_](
                    value, f"constraints/{field}", passthrough=True, **kwargs
                )
            except ValidationSummary as e:
                errs.extend(e)

    # order
    for idx, entry in enumerate(val.order):
        try:
            # TODO use generic tuple here once implemented
            entry = _ALL_TYPED[Iterable](entry, 'order', **kwargs)
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


def _range[T](
    val: Any, type_: type[T], argname: str | None = None, **kwargs: Any
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

    from_val, to_val = new_val
    return (from_val, to_val)


@_create_dataclass_validator(*ALL_LOG_FILTERS)
def _log_filter(
    val: CdEDBObject, *args: Any, type_: type[GenericLogFilter], **kwargs: Any
) -> GenericLogFilter:
    return type_(**val)


@_create_dataclass_validator(models_complaint.Case)
def _case(val: CdEDBObject, *args: Any, **kwargs: Any) -> CdEDBObject:
    return val


@_create_dataclass_validator(models_complaint.ComplaintEntry)
def _complaint_entry(
    val: Any,
    argname: str,
    *,
    entries: dict[int, models_complaint.ComplaintEntry],
    **kwargs: Any,
) -> CdEDBObject:
    errs = ValidationSummary()
    entry_type: const.ComplaintEntryType = val['entry_type']

    # Validate concerned_id dependent on entry_type
    type_ = PersonaID if entry_type.has_concerned else NoneType
    with errs:
        val['concerned_id'] = _ALL_TYPED[type_](
            val.get('concerned_id'), 'concerned_id', **kwargs
        )

    # Validate parent_id dependent on entry_type
    type_ = ID if entry_type in entry_type.all_children() else NoneType
    with errs:
        val['parent_id'] = _ALL_TYPED[type_](
            val.get('parent_id'), 'parent_id', **kwargs
        )

    if val.get('parent_id'):
        if val['parent_id'] not in entries:
            errs.append(KeyError("parent_id", n_("Unknown parent entry.")))
        elif entry_type not in entries[val['parent_id']].entry_type.possible_children:
            errs.append(ValueError("parent_id", n_("Invalid parent type.")))

    if errs:
        raise errs

    return val


@_create_dataclass_validator(models_complaint.ComplaintEntryVersion)
def _complaint_entry_version(
    val: Any, argname: str, entry_type: const.ComplaintEntryType | None, **kwargs: Any
) -> CdEDBObject:
    errs = ValidationSummary()
    if not entry_type:
        raise ValidationSummary(
            ValueError("entry_type", "Must provide entry_type for setting entry.")
        )

    # Validate concerned_id dependent on entry_type
    validator = _str if entry_type.has_description else _None
    with errs:
        val['description'] = validator(val.get('description'), 'description', **kwargs)

    if val.get('authors'):
        # Remove any duplicates
        val['authors'] = list(set(val['authors']))
    else:
        errs.append(ValueError('authors', n_("Must not be empty.")))

    if not entry_type.is_measure:
        with errs:
            val['etime'] = _ALL_TYPED[NoneType](val.get('etime'), 'etime', **kwargs)

    attachment_keys = ("attachment_hash", "attachment_title", "attachment_filename")
    if not entry_type.allows_attachment:
        for key in attachment_keys:
            with errs:
                val[key] = _ALL_TYPED[NoneType](val.get(key), key, **kwargs)
    elif (
        any(val.get(key) for key in attachment_keys)
        and not all(val.get(key) for key in attachment_keys)
    ):  # fmt: skip
        errs.extend(
            ValueError(key, n_("Incomplete attachment."))
            for key in attachment_keys
            if not val.get(key)
        )
        if not val.get("attachment_hash"):
            errs.append(ValueError("attachment", n_("Incomplete attachment.")))

    if val.get('etime') and val['etime'] <= val['timestamp']:
        errs.append(ValueError('etime', n_("Must be after timestamp.")))

    if errs:
        raise errs

    return val


def _enum_validator_maker[E: enum.Enum](
    anenum: type[E], name: str | None = None, internal: bool = False
) -> Callable[..., E]:
    """Automate validator creation for enums.

    Since this is pretty generic we do this all in one go.

    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    :param internal: If True the validator is not added to the module.
    """
    error_msg = n_("Invalid input for the enumeration '%(enum)s'.")

    def the_validator(val: Any, argname: str | None = None, **kwargs: Any) -> E:
        if isinstance(val, anenum):
            return val

        if isinstance(val, str):
            # first, try to convert if the enum member is given as "class.member"
            try:
                enum_name, enum_val = val.split(".", 1)
                if enum_name == anenum.__name__:
                    return anenum[enum_val]
            except (KeyError, ValueError):
                pass

            # second, try to treat the string as the value:
            try:
                return anenum(val)
            except ValueError:
                pass

        # third, try to convert if the enum member is given as str(int)
        try:
            val = _int(val, argname=argname, **kwargs)
            return anenum(val)
        except (ValidationSummary, ValueError) as e:
            raise ValidationSummary(
                ValueError(argname, error_msg, {'enum': anenum.__name__})
            ) from e

    the_validator.__name__ = name or f"_enum_{anenum.__name__.lower()}"

    if not internal:
        _add_typed_validator(the_validator, anenum)

    return the_validator


for oneenum in ALL_ENUMS:
    _enum_validator_maker(oneenum)


@_add_typed_validator
def _db_subscription_state(
    val: Any, argname: str | None = None, **kwargs: Any
) -> DatabaseSubscriptionState:
    """Validates whether a subscription state is written into the database."""
    val = _ALL_TYPED[const.SubscriptionState](val, argname, **kwargs)
    if val == const.SubscriptionState.none:
        raise ValidationSummary(
            ValueError(
                argname, n_("SubscriptionState.none is not written into the database.")
            )
        )
    return DatabaseSubscriptionState(val)


def _infinite_enum_validator_maker[IE: CdEIntEnum](
    anenum: type[IE], name: str | None = None
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
        val: Any, argname: str | None = None, **kwargs: Any
    ) -> InfiniteEnum[IE]:
        val_int: int | None

        if isinstance(val, InfiniteEnum):
            val_enum = raw_validator(val.enum, argname=argname, **kwargs)

            if val.enum.value == INFINITE_ENUM_MAGIC_NUMBER:
                val_int = _non_negative_int(val.int, argname=argname, **kwargs)
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
                        ValueError(argname, error_msg, {'enum': anenum})
                    ) from e
            else:
                val_enum = anenum(INFINITE_ENUM_MAGIC_NUMBER)
                val_int = val

        return InfiniteEnum[anenum](val_enum, val_int)  # type: ignore[valid-type]

    the_validator.__name__ = name or f"_infinite_enum_{anenum.__name__.lower()}"
    _add_typed_validator(the_validator, InfiniteEnum[anenum])  # type: ignore[valid-type]


for oneenum in ALL_INFINITE_ENUMS:
    _infinite_enum_validator_maker(oneenum)
