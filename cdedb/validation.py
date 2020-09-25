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

import collections.abc
import copy
import datetime
import decimal
import functools
import io
import itertools
import json
import logging
import re
import string
import sys

import magic
import PIL.Image
import pytz
import werkzeug.datastructures
import zxcvbn

from typing import (
    Any, Union, Tuple, List, Optional
)

from cdedb.common import (
    n_, EPSILON, compute_checkdigit, now, extract_roles, asciificator,
    ASSEMBLY_BAR_SHORTNAME, InfiniteEnum, INFINITE_ENUM_MAGIC_NUMBER,
    REALM_SPECIFIC_GENESIS_FIELDS, EVENT_SCHEMA_VERSION,
    ValidationWarning, Error)
from cdedb.database.constants import FieldDatatypes, FieldAssociations
from cdedb.validationdata import (
    IBAN_LENGTHS, FREQUENCY_LISTS, GERMAN_POSTAL_CODES, GERMAN_PHONE_CODES,
    ITU_CODES)
from cdedb.query import (
    Query, QueryOperators, VALID_QUERY_OPERATORS, MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS)
from cdedb.config import BasicConfig
from cdedb.enums import ALL_ENUMS, ALL_INFINITE_ENUMS
import cdedb.ml_type_aux as ml_type

_BASICCONF = BasicConfig()

current_module = sys.modules[__name__]

zxcvbn.matching.add_frequency_lists(FREQUENCY_LISTS)

_LOGGER = logging.getLogger(__name__)

_ALL = []

def _addvalidator(fun):
    """Mark a function for processing into validators.

    :type fun: callable
    """
    _ALL.append(fun)
    return fun


def _examine_dictionary_fields(adict, mandatory_fields, optional_fields=None,
                               *, allow_superfluous=False, _convert=True,
                               _ignore_warnings=False):
    """Check more complex dictionaries.

    :type adict: dict
    :param adict: a :py:class:`dict` to check
    :type mandatory_fields: {str: callable}
    :param mandatory_fields: The mandatory keys to be checked for in
      :py:obj:`adict`, the callable is a validator to check the corresponding
      value in :py:obj:`adict` for conformance. A missing key is an error in
      itself.
    :type optional_fields: {str: callable}
    :param optional_fields: Like :py:obj:`mandatory_fields`, but facultative.
    :type allow_superfluous: bool
    :param allow_superfluous: If ``False`` keys which are neither in
      :py:obj:`mandatory_fields` nor in :py:obj:`optional_fields` are errors.
    :type _convert: bool
    :param _convert: If ``True`` do type conversions.
    :type _ignore_warnings: bool
    :param _ignore_warnings: If ``True`` skip Errors
        of type ``ValidationWarning``.
    """
    optional_fields = optional_fields or {}
    errs = []
    retval = {}
    mandatory_fields_found = []
    for key, value in adict.items():
        if key in mandatory_fields:
            v, e = mandatory_fields[key](value, argname=key, _convert=_convert,
                                         _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                mandatory_fields_found.append(key)
                retval[key] = v
        elif key in optional_fields:
            v, e = optional_fields[key](value, argname=key, _convert=_convert,
                                        _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                retval[key] = v
        elif not allow_superfluous:
            errs.append((key, KeyError(n_("Superfluous key found."))))
    if len(mandatory_fields) != len(mandatory_fields_found):
        missing = set(mandatory_fields) - set(mandatory_fields_found)
        for key in missing:
            errs.append((key, KeyError(n_("Mandatory key missing."))))
        retval = None
    return retval, errs


def _augment_dict_validator(validator, augmentation, strict=True):
    """Beef up a dict validator.

    This is for the case where you have two similar specs for a data set
    in form of a dict and already a validator for one of them, but some
    additional fields in the second spec.

    This can also be used as a decorator.

    :type validator: callable
    :type augmentation: {str: callable}
    :param augmentation: Syntax is the same as for
      :py:meth:`_examine_dictionary_fields`.
    :type strict: bool
    :param strict: If True the additional arguments are mandatory otherwise they
      are optional.
    :rtype: callable
    """

    @functools.wraps(validator)
    def new_validator(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
        mandatory_fields = augmentation if strict else {}
        optional_fields = {} if strict else augmentation
        ret, errs = _examine_dictionary_fields(
            val, mandatory_fields, optional_fields, allow_superfluous=True,
            _convert=_convert, _ignore_warnings=_ignore_warnings)
        tmp = copy.deepcopy(val)
        for field in augmentation:
            if field in tmp:
                del tmp[field]
        v, e = validator(tmp, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
        errs.extend(e)
        if ret is not None and v is not None:
            ret.update(v)
        if errs:
            ret = None
        return ret, errs

    return new_validator


def escaped_split(s, delim, escape='\\'):
    """Helper function for anvanced list splitting.

    Split the list at every delimiter, except if it is escaped (and
    allow the escape char to be escaped itself).

    Basend on http://stackoverflow.com/a/18092547

    :type s: str
    :type delim: char
    :type escape: char
    :rtype: [str]
    """
    ret = []
    current = ''
    itr = iter(s)
    for ch in itr:
        if ch == escape:
            try:
                current += next(itr)
            except StopIteration:
                pass
        elif ch == delim:
            ret.append(current)
            current = ''
        else:
            current += ch
    ret.append(current)
    return ret


#
# Below is the real stuff
#

@_addvalidator
def _None(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """Force a None.

    This is mostly for ensuring proper population of dicts.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (object or None, [(str or None, exception)])
    """
    if _convert:
        if isinstance(val, str) and not val:
            val = None
    if val is None:
        return val, []
    return None, [(argname, ValueError(n_("Must be empty.")))]


@_addvalidator
def _any(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (object or None, [(str or None, exception)])
    """
    return val, []


@_addvalidator
def _int(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    if _convert:
        if isinstance(val, str) or isinstance(val, bool):
            try:
                val = int(val)
            except ValueError:
                return None, [(argname,
                               ValueError(n_("Invalid input for integer.")))]
        elif isinstance(val, float):
            if abs(val - int(val)) > EPSILON:
                return None, [(argname, ValueError(n_("Precision loss.")))]
            val = int(val)
    if not isinstance(val, int) or isinstance(val, bool):
        return None, [(argname, TypeError(n_("Must be an integer.")))]
    return val, []


@_addvalidator
def _non_negative_int(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, err = _int(val, argname, _convert=_convert,
                    _ignore_warnings=_ignore_warnings)
    if not err and val < 0:
        val = None
        err.append((argname, ValueError(n_("Must not be negative."))))
    return val, err


@_addvalidator
def _positive_int(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, errs = _int(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if not errs:
        if val <= 0:
            val = None
            errs.append((argname, ValueError(n_("Must be positive."))))
    return val, errs


@_addvalidator
def _id(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """A numeric ID as in a database key.

    This is just a wrapper around `_positive_int`, to differentiate this
    semantically.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    return _positive_int(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)


@_addvalidator
def _partial_import_id(val, argname=None, *, _convert=True,
                       _ignore_warnings=False):
    """A numeric id or a negative int as a placeholder."""
    val, errs = _int(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if not errs:
        if val == 0:
            val = None
            errs.append((argname, ValueError(n_("Must not be zero."))))
    return val, errs


@_addvalidator
def _float(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (float or None, [(str or None, exception)])
    """
    if _convert:
        try:
            val = float(val)
        except (ValueError, TypeError):
            return None, [(argname,
                           ValueError(n_("Invalid input for float.")))]
    if not isinstance(val, float):
        return None, [(argname,
                       TypeError(n_("Must be a floating point number.")))]
    return val, []


@_addvalidator
def _decimal(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (decimal.Decimal or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation):
            return None, [(
                argname, ValueError(n_("Invalid input for decimal number.")))]
    if not isinstance(val, decimal.Decimal):
        return None, [(argname, TypeError(n_("Must be a decimal.Decimal.")))]
    return val, []


@_addvalidator
def _non_negative_decimal(val, argname=None, *, _convert=True,
                          _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (decimal.Decimal or None, [(str or None, exception)])
    """
    val, err = _decimal(val, argname, _convert=_convert,
                        _ignore_warnings=_ignore_warnings)
    if not err and val < 0:
        val = None
        err.append((argname, ValueError(n_("Transfer saldo is negative."))))
    return val, err


@_addvalidator
def _positive_decimal(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (decimal.Decimal or None, [(str or None, exception)])
    """
    val, err = _decimal(val, argname, _convert=_convert,
                        _ignore_warnings=_ignore_warnings)
    if not err and val <= 0:
        val = None
        err.append((argname, ValueError(n_("Transfer saldo is negative."))))
    return val, err


@_addvalidator
def _str_type(val, argname=None, *, zap='', sieve='', _convert=True,
              _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type zap: str
    :param zap: delete all characters in this from the result
    :type sieve: str
    :param sieve: allow only the characters in this into the result
    :rtype: (str or None, [(str or None, exception)])
    """
    if _convert and val is not None:
        try:
            val = str(val)
        except (ValueError, TypeError):
            return None, [(argname,
                           ValueError(n_("Invalid input for string.")))]
    if not isinstance(val, str):
        return None, [(argname, TypeError(n_("Must be a string.")))]
    if zap:
        val = val.translate(str.maketrans("", "", zap))
    if sieve:
        val = ''.join(c for c in val if c in sieve)
    val = val.replace("\r\n", "\n").replace("\r", "\n")
    return val, []


@_addvalidator
def _str(val, argname=None, *, zap='', sieve='', _convert=True,
         _ignore_warnings=False):
    """ Like :py:class:`_str_type` (parameters see there), but mustn't be
    empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type zap: str
    :type sieve: str
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_type(val, argname, zap=zap, sieve=sieve, _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
    if val is not None and not val:
        errs.append((argname, ValueError(n_("Must not be empty."))))
    return val, errs


@_addvalidator
def _bytes(val: Any, argname: str = None, *, _convert: bool = True,
           _ignore_warnings: bool = False, encoding: str = None
           ) -> Tuple[Optional[bytes], List[Error]]:
    if _convert:
        if isinstance(val, str):
            if not encoding:
                raise RuntimeError(
                    "Not encoding specified to convert str to bytes.")
            val = bytes(val, encoding=encoding)
        else:
            try:
                val = bytes(val)
            except ValueError:
                return None, [(argname,
                               ValueError(n_("Cannot convert {val} to bytes."),
                                          {'val': val}))]
    if not isinstance(val, bytes):
        return None, [(argname, ValueError(n_("Must be a bytes object.")))]
    return val, []


@_addvalidator
def _mapping(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :param _convert: is ignored since no useful default conversion is available
    :rtype: (dict or None, [(str or None, exception)])
    """
    if not isinstance(val, collections.abc.Mapping):
        return None, [(argname, TypeError(n_("Must be a mapping.")))]
    return val, []


@_addvalidator
def _iterable(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :param _convert: is ignored since no useful default conversion is available
    :rtype: ([object] or None, [(str or None, exception)])
    """
    if not isinstance(val, collections.abc.Iterable):
        return None, [(argname, TypeError(n_("Must be an iterable.")))]
    return val, []


@_addvalidator
def _sequence(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: ([object] or None, [(str or None, exception)])
    """
    if _convert:
        try:
            val = tuple(val)
        except (ValueError, TypeError):
            return None, [(argname,
                           ValueError(n_("Invalid input for sequence.")))]
    if not isinstance(val, collections.abc.Sequence):
        return None, [(argname, TypeError(n_("Must be a sequence.")))]
    return val, []


@_addvalidator
def _bool(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (bool or None, [(str or None, exception)])
    """
    if _convert and val is not None:
        if val in ("True", "true", "yes", "y"):
            return True, []
        elif val in ("False", "false", "no", "n"):
            return False, []
        try:
            val = bool(val)
        except (ValueError, TypeError):
            return None, [(argname,
                           ValueError(n_("Invalid input for boolean.")))]
    if not isinstance(val, bool):
        return None, [(argname, TypeError(n_("Must be a boolean.")))]
    return val, []


@_addvalidator
def _empty_dict(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    if val != {}:
        return None, [(argname, ValueError(n_("Must be an empty dict.")))]
    return val, []


@_addvalidator
def _empty_list(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (list or None, [(str or None, expection)])
    """
    if _convert:
        val, errs = _iterable(val, argname, _convert=_convert,
                              _ignore_warnings=_ignore_warnings)
        if errs:
            return None, errs
        val = list(val)
    if val != []:
        return None, [(argname, ValueError(n_("Must be an empty list.")))]
    return val, []


@_addvalidator
def _realm(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """A realm in the sense of the DB.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if val not in ("session", "core", "cde", "event", "ml", "assembly"):
        val = None
        errs.append((argname, ValueError(n_("Not a valid realm."))))
    return val, errs


_CDEDBID = re.compile('^DB-([0-9]*)-([0-9X])$')


@_addvalidator
def _cdedbid(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mo = _CDEDBID.search(val.strip())
    if mo is None:
        return None, [(argname, ValueError(n_("Wrong formatting.")))]
    value = mo.group(1)
    checkdigit = mo.group(2)
    value, errs = _id(value, argname, _convert=True,
                      _ignore_warnings=_ignore_warnings)
    if not errs and compute_checkdigit(value) != checkdigit:
        errs.append((argname, ValueError(n_("Checksum failure."))))
    return value, errs


_PRINTABLE_ASCII = re.compile('^[ -~]*$')


@_addvalidator
def _printable_ascii_type(val, argname=None, *, _convert=True,
                          _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_type(val, argname, _convert=_convert,
                          _ignore_warnings=_ignore_warnings)
    if not errs and not _PRINTABLE_ASCII.search(val):
        errs.append((argname, ValueError(n_("Must be printable ASCII."))))
    return val, errs


@_addvalidator
def _printable_ascii(val, argname=None, *, _convert=True,
                     _ignore_warnings=False):
    """Like :py:func:`_printable_ascii_type` (parameters see there), but
    must not be empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii_type(val, argname, _convert=_convert,
                                      _ignore_warnings=_ignore_warnings)
    if val is not None and not val.strip():
        errs.append((argname, ValueError(n_("Must not be empty."))))
    return val, errs


_ALPHANUMERIC_REGEX = re.compile(r'^[a-zA-Z0-9]+$')


@_addvalidator
def _alphanumeric(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not _ALPHANUMERIC_REGEX.search(val):
        errs.append((argname, ValueError(n_("Must be alphanumeric."))))
    return val, errs


_CSV_ALPHANUMERIC_REGEX = re.compile(r'^[a-zA-Z0-9]+(,[a-zA-Z0-9]+)*$')


@_addvalidator
def _csv_alphanumeric(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not _CSV_ALPHANUMERIC_REGEX.search(val):
        errs.append((argname,
                     ValueError(n_("Must be comma separated alphanumeric."))))
    return val, errs


_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_.-]+$')


@_addvalidator
def _identifier(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """Identifiers encompass everything from file names to short names for
    events.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not _IDENTIFIER_REGEX.search(val):
        errs.append((argname, ValueError(n_(
            "Must be an identifier "
            "(only letters, numbers, underscore, dot and hyphen)."))))
    return val, errs


_RESTRICTIVE_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_]+$')


@_addvalidator
def _restrictive_identifier(val, argname=None, *, _convert=True,
                            _ignore_warnings=False):
    """Restrictive identifiers are for situations, where normal identifiers
    are too lax.

    One example are sql column names.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not _RESTRICTIVE_IDENTIFIER_REGEX.search(val):
        errs.append((argname, ValueError(n_(
            "Must be a restrictive identifier "
            "(only letters, numbers and underscore)."))))
    return val, errs


_CSV_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$')


@_addvalidator
def _csv_identifier(val, argname=None, *, _convert=True,
                    _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not _CSV_IDENTIFIER_REGEX.search(val):
        errs.append((argname,
                     ValueError(n_("Must be comma separated identifiers."))))
    return val, errs


def _list_of(val, validator, argname=None, *, _convert=True,
             _ignore_warnings=False, _allow_empty=True):
    """
    Apply another validator to all entries of of a list.

    With `_convert` being True, the input may be a comma-separated string.

    :type val: Any
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (list or None, [(str or None, exception)]
    """
    if _convert:
        if isinstance(val, str):
            # TODO use default separator from config here?
            # Skip emtpy entries which can be produced by JavaScript.
            val = [v for v in val.split(",") if v]
        val, errs = _iterable(val, argname, _convert=_convert,
                              _ignore_warnings=_ignore_warnings)
        if errs:
            return None, errs
        val = list(val)
    else:
        val, errs = _sequence(val, argname, _convert=_convert,
                              _ignore_warnings=_ignore_warnings)
        if errs:
            return None, errs
        val = list(val)
    vals = []
    errs = []
    for v in val:
        v, e = validator(v, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
        vals.append(v)
        errs.extend(e)
    if not _allow_empty:
        if not vals:
            return None, [(argname, ValueError(n_("Must not be empty.")))]
    return vals, errs


@_addvalidator
def _int_csv_list(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: ([int] or None, [(str or None, exception)])
    """
    return _list_of(val, _int, argname, _convert=_convert,
                    _ignore_warnings=_ignore_warnings)


@_addvalidator
def _cdedbid_csv_list(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """
    This deals with strings containing multiple cdedbids, like when they are
    returned from cdedbSearchPerson.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: ([int] or None, [(str or None, exception)])
    """
    return _list_of(val, _cdedbid, argname, _convert=_convert,
                    _ignore_warnings=False)


@_addvalidator
def _password_strength(val, argname=None, *, _convert=True, admin=False,
                       inputs=None, _ignore_warnings=False):
    """Implement a password policy.

    This has the strictly competing goals of security and usability.

    We are using zxcvbn for this task instead of any other solutions here,
    as it is the most popular solution to measure the actual entropy of a
    password and does not force character rules to the user that are not
    really improving password strength.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    inputs = inputs or []
    val, errors = _str(val, argname=argname, _convert=_convert,
                       _ignore_warnings=_ignore_warnings)
    if val:
        results = zxcvbn.zxcvbn(val, list(filter(None, inputs)))
        # if user is admin in any realm, require a score of 4. After
        # migration, everyone must change their password, so this is
        # actually enforced for admins of the old db. Afterwards,
        # meta admins are intended to do a password reset.
        if results['score'] < 2:
            feedback = [results['feedback']['warning']]
            feedback.extend(results['feedback']['suggestions'][0:2])
            for fb in filter(None, feedback):
                errors.append((argname, ValueError(fb)))
                if not errors:
                    errors.append(
                        (argname, ValueError(n_("Password too weak."))))
        if admin and results['score'] < 4:
            errors.append((argname, ValueError(n_("Password too weak for "
                                                  "admin account."))))

    return val, errors


_EMAIL_REGEX = re.compile(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$')


@_addvalidator
def _email(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """We accept only a subset of valid email addresses since implementing the
    full standard is horrendous. Also we normalize emails to lower case.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return None, errs
    # normalize email addresses to lower case
    val = val.strip().lower()
    if not _EMAIL_REGEX.search(val):
        errs.append((argname, ValueError(n_("Must be a valid email address."))))
    return val, errs


_EMAIL_LOCAL_PART_REGEX = re.compile(r'^[a-z0-9._+-]+$')


@_addvalidator
def _email_local_part(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """We accept only a subset of valid email addresses.
    Here we only care about the local part.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return None, errs
    # normalize to lower case
    val = val.strip().lower()
    if not _EMAIL_LOCAL_PART_REGEX.match(val):
        errs.append(
            (argname, ValueError(n_("Must be a valid email local part."))))
    return val, errs


_PERSONA_TYPE_FIELDS = {
    'is_cde_realm': _bool,
    'is_event_realm': _bool,
    'is_ml_realm': _bool,
    'is_assembly_realm': _bool,
    'is_member': _bool,
    'is_searchable': _bool,
    'is_active': _bool,
}
_PERSONA_BASE_CREATION = lambda: {
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
_PERSONA_CDE_CREATION = lambda: {
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
_PERSONA_EVENT_CREATION = lambda: {
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
_PERSONA_COMMON_FIELDS = lambda: {
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


def parse_date(val):
    """Make a string into a date.

    We only support a limited set of formats to avoid any surprises

    :type val: str
    :rtype: datetime.date
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


@_addvalidator
def _date(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (datetime.date or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str) and len(val.strip()) >= 6:
        try:
            val = parse_date(val)
        except (ValueError, TypeError):
            return None, [(argname, ValueError(n_("Invalid input for date.")))]
    if not isinstance(val, datetime.date):
        return None, [(argname, TypeError(n_("Must be a datetime.date.")))]
    if isinstance(val, datetime.datetime):
        # necessary, since isinstance(datetime.datetime.now(),
        # datetime.date) == True
        val = val.date()
    return val, []


@_addvalidator
def _birthday(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
        :type val: object
        :type argname: str or None
        :type _convert: bool
        :type _ignore_warnings: bool
        :rtype: (datetime.date or None, [(str or None, exception)])
    """
    val, errs = _date(val, argname=argname, _convert=_convert,
                      _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if now().date() < val:
        return None, [(argname, ValueError(
            n_("A birthday must be in the past.")))]
    return val, []


def parse_datetime(val, default_date=None):
    """Make a string into a datetime.

    We only support a limited set of formats to avoid any surprises

    :type val: str
    :type default_date: datetime.date or None
    :rtype: datetime.datetime
    """
    date_formats = ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%d.%m.%y")
    connectors = ("T", " ")
    time_formats = (
        "%H:%M:%S.%f%z", "%H:%M:%S%z", "%H:%M:%S.%f", "%H:%M:%S", "%H:%M")
    formats = itertools.chain(
        ("{}{}{}".format(d, c, t)
         for d in date_formats for c in connectors for t in time_formats),
        ("{} {}".format(t, d) for t in time_formats for d in date_formats))
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
        ret = _BASICCONF["DEFAULT_TIMEZONE"].localize(ret)
    return ret.astimezone(pytz.utc)


@_addvalidator
def _datetime(val, argname=None, *, _convert=True, default_date=None,
              _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type default_date: datetime.date or None
    :param default_date: If the user-supplied value specifies only a time, this
      parameter allows to fill in the necessary date information to fill
      the gap.
    :rtype: (datetime.datetime or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str) and len(val.strip()) >= 5:
        try:
            val = parse_datetime(val, default_date)
        except (ValueError, TypeError):
            return None, [(argname,
                           ValueError(n_("Invalid input for datetime.")))]
    if not isinstance(val, datetime.datetime):
        return None, [(argname, TypeError(n_("Must be a datetime.datetime.")))]
    return val, []


@_addvalidator
def _single_digit_int(val, argname=None, *, _convert=True,
                      _ignore_warnings=False):
    """Like _int, but between +9 and -9.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, errs = _int(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if val > 9 or val < -9:
        return None, [(argname, ValueError(n_("More than one digit.")))]
    return val, []


@_addvalidator
def _phone(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    orig = val.strip()
    val = ''.join(c for c in val if c in '+1234567890')
    if len(val) < 7:
        errs.append((argname, ValueError(n_("Too short."))))
        return None, errs

    # This is pretty horrible, but seems to be the best way ...
    # It works thanks to the test-suite ;)

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
            errs.append(
                (argname, ValueError(n_("Invalid international part."))))
        if retval == "+49" and not val.startswith("0"):
            val = "0" + val
    else:
        retval += "49"
    # now the national part
    if retval == "+49":
        # german stuff here
        if not val.startswith("0"):
            errs.append((argname, ValueError(n_("Invalid national part."))))
        else:
            val = val[1:]
        for length in range(1, 7):
            if val[:length] in GERMAN_PHONE_CODES:
                retval += " ({}) {}".format(val[:length], val[length:])
                if length + 2 >= len(val):
                    errs.append(
                        (argname, ValueError(n_("Invalid local part."))))
                break
        else:
            errs.append((argname, ValueError(n_("Invalid national part."))))
    else:
        index = 0
        try:
            index = orig.index(retval[1:]) + len(retval) - 1
        except ValueError:
            errs.append(
                (argname, ValueError(n_("Invalid international part."))))
        # this will terminate since we know that there are sufficient digits
        while not orig[index] in string.digits:
            index += 1
        rest = orig[index:]
        sep = ''.join(c for c in rest if c not in string.digits)
        try:
            national = rest[:rest.index(sep)]
            local = rest[rest.index(sep) + len(sep):]
            if not len(national) or not len(local):
                raise ValueError()
            retval += " ({}) {}".format(national, local)
        except ValueError:
            retval += " " + val
    return retval, errs


@_addvalidator
def _german_postal_code(val, argname=None, *, aux=None, _convert=True,
                        _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :type aux: str or None
    :param aux: Additional information. In this case the country belonging
        to the postal code.
    :type _ignore_warnings: bool
    :param _ignore_warnings: If True, ignore invalid german postcodes.
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert,
                                 _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    val = val.strip()
    if aux is None or aux == "" or aux == "Deutschland":
        if val not in GERMAN_POSTAL_CODES and not _ignore_warnings:
            errs.append(
                (argname, ValidationWarning(n_("Invalid german postal code."))))
    return val, errs


_GENESIS_CASE_COMMON_FIELDS = lambda: {
    'username': _email,
    'given_names': _str,
    'family_name': _str,
    'realm': _str,
    'notes': _str,
}
_GENESIS_CASE_OPTIONAL_FIELDS = lambda: {
    'case_status': _enum_genesisstati,
    'reviewer': _id,
}
_GENESIS_CASE_ADDITIONAL_FIELDS = lambda: {
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


_PRIVILEGE_CHANGE_COMMON_FIELDS = lambda: {
    'persona_id': _id,
    'submitted_by': _id,
    'status': _enum_privilegechangestati,
    'notes': _str,
}

_PRIVILEGE_CHANGE_OPTIONAL_FIELDS = lambda: {
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


@_addvalidator
def _bytes(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (bytes or None, [(str or None, exception)])
    """
    if not isinstance(val, bytes):
        return None, [(argname, TypeError(n_("Not a bytes object.")))]
    return val, []


@_addvalidator
def _input_file(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (bytes or None, [(str or None, exception)])
    """
    if not isinstance(val, werkzeug.datastructures.FileStorage):
        return None, [(argname, TypeError(n_("Not a FileStorage.")))]
    blob = val.read()
    if not blob:
        return None, [(argname, ValueError(n_("Empty FileStorage.")))]
    return blob, []


@_addvalidator
def _csvfile(val, argname=None, *, encoding="utf-8-sig", _convert=True,
             _ignore_warnings=False):
    """
    We default to 'utf-8-sig', since it behaves exactly like 'utf-8' if the
    file is 'utf-8' but it gets rid of the BOM if the file is 'utf-8-sig'.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)]
    """
    val, errs = _input_file(val, argname, _convert=_convert,
                            _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    mime = magic.from_buffer(val, mime=True)
    if mime not in ("text/csv", "text/plain"):
        errs.append((argname, ValueError(n_("Only text/csv allowed."))))
    if errs:
        return None, errs
    val, errs = _str(val.decode(encoding).strip(), argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    return val, errs


@_addvalidator
def _profilepic(val: Any, argname: str = None, *, _convert: bool = True,
                _ignore_warnings: bool = False, file_storage: bool = True
                ) -> Tuple[Optional[bytes], List[Error]]:
    """
    Validate a file for usage as a profile picture.

    Limit file size, resolution and ratio.

    :param file_storage: If `True` expect the input to be a
        `werkzeug.FileStorage`, otherwise expect a `bytes` object.
    """
    if file_storage:
        val, errs = _input_file(val, argname, _convert=_convert,
                                _ignore_warnings=_ignore_warnings)
    else:
        val, errs = _bytes(val, argname, _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if len(val) < 2 ** 10:
        errs.append((argname, ValueError(n_("Too small."))))
    if len(val) > 2 ** 17:
        errs.append((argname, ValueError(n_("Too big."))))
    mime = magic.from_buffer(val, mime=True)
    if mime not in ("image/jpeg", "image/jpg", "image/png"):
        errs.append((argname, ValueError(n_("Only jpg and png allowed."))))
    if errs:
        return None, errs
    image = PIL.Image.open(io.BytesIO(val))
    width, height = image.size
    if width / height < 0.9 or height / width < 0.9:
        errs.append((argname, ValueError(n_("Not square enough."))))
    if width * height < 5000:
        errs.append((argname, ValueError(n_("Resolution too small."))))
    return val, errs


@_addvalidator
def _pdffile(val: Any, argname: str = None, *, _convert: bool = True,
             _ignore_warnings: bool = False, file_storage: bool = True
             ) -> Tuple[Optional[bytes], List[Error]]:
    """Validate a file as a pdf.

    Limit the maximum file size.

    :param file_storage: If `True` expect the input to be a
        `werkzeug.FileStorage`, otherwise expect a `bytes` object.
    """
    if file_storage:
        val, errs = _input_file(val, argname, _convert=_convert,
                                _ignore_warnings=_ignore_warnings)
    else:
        val, errs = _bytes(val, argname, _convert=_convert,
                           _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if len(val) > 2 ** 23:  # Disallow files bigger than 8 MB.
        errs.append((argname, ValueError(n_("Filesize too large."))))
    mime = magic.from_buffer(val, mime=True)
    if mime != "application/pdf":
        errs.append((argname, ValueError(n_("Only pdf allowed."))))
    return val, errs


@_addvalidator
def _pair_of_int(val: Any, argname: str = None, *, _convert: bool = True,
                 _ignore_warnings: bool = False,
                 ) -> Tuple[Optional[Tuple[int, int]], List[Error]]:
    """Validate a pair of integers."""
    argname = argname or "pair"
    val, errs = _list_of(val, _int, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if len(val) != 2:
        errs.append((argname,
                     ValueError(n_("Must contain exactly two elements."))))
        return None, errs
    return tuple(val), errs


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


_LASTSCHRIFT_COMMON_FIELDS = lambda: {
    'amount': _positive_decimal,
    'iban': _iban,
    'account_owner': _str_or_None,
    'account_address': _str_or_None,
    'notes': _str_or_None,
}
_LASTSCHRIFT_OPTIONAL_FIELDS = lambda: {
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


@_addvalidator
def _iban(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    argname = argname or "iban"
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    val = val.upper().replace(' ', '')
    if len(val) < 5:
        errs.append((argname, ValueError(n_("Too short."))))
        return None, errs
    for char in val[:2]:
        if char not in string.ascii_uppercase:
            errs.append((argname,
                         ValueError(n_("Must start with country code."))))
    for char in val[2:4]:
        if char not in string.digits:
            errs.append((argname,
                         ValueError(n_("Must have digits for checksum."))))
    for char in val[4:]:
        if char not in string.digits + string.ascii_uppercase:
            errs.append((argname,
                         ValueError(n_("Invalid character in IBAN."))))
    if val[:2] not in IBAN_LENGTHS:
        errs.append((argname,
                     ValueError(n_("Unknown or unsupported Country Code."))))
    if not errs:
        if len(val) != IBAN_LENGTHS[val[:2]]:
            errs.append((argname, ValueError(
                n_("Invalid length %(len)s for Country Code %(code)s. "
                   "Expexted length %(exp)s."),
                {"len": len(val), "code": val[:2], "exp": IBAN_LENGTHS[val[:2]]}
            )))
        temp = val[4:] + val[:4]
        temp = ''.join(c if c in string.digits else str(ord(c) - 55)
                       for c in temp)
        if int(temp) % 97 != 1:
            errs.append((argname, ValueError(n_("Invalid checksum."))))
    return val, errs


_LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS = lambda: {
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


@_addvalidator
def _safe_str(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """This allows alpha-numeric, whitespace and known good others.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    ALLOWED = ".,-+()/"
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    for char in val:
        if not (char.isalnum() or char.isspace() or char in ALLOWED):
            errs.append((argname, ValueError(
                n_("Forbidden character (%(char)s)."), {'char': char})))
    if errs:
        return None, errs
    return val, errs


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


_INSTITUTION_COMMON_FIELDS = lambda: {
    'title': _str,
    'moniker': _str,
}


@_addvalidator
def _institution(val, argname=None, *, creation=False, _convert=True,
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
    argname = argname or "institution"
    val, errs = _mapping(val, argname, _convert=_convert,
                         _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _INSTITUTION_COMMON_FIELDS()
        optional_fields = {}
    else:
        mandatory_fields = {'id': _id}
        optional_fields = _INSTITUTION_COMMON_FIELDS()
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


_PAST_EVENT_COMMON_FIELDS = lambda: {
    'title': _str,
    'shortname': _str,
    'institution': _id,
    'tempus': _date,
    'description': _str_or_None,
}
_PAST_EVENT_OPTIONAL_FIELDS = lambda: {
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


_EVENT_COMMON_FIELDS = lambda: {
    'title': _str,
    'institution': _id,
    'description': _str_or_None,
    'shortname': _identifier,
}
_EVENT_OPTIONAL_FIELDS = lambda: {
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
                    creation=creation,_convert=_convert)
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


_EVENT_PART_COMMON_FIELDS = lambda: {
    'title': _str,
    'shortname': _str,
    'part_begin': _date,
    'part_end': _date,
    'fee': _non_negative_decimal,
    'waitlist_field': _id_or_None,
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
        mandatory_fields = _EVENT_PART_COMMON_FIELDS()
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_PART_COMMON_FIELDS()
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if ('part_begin' in val and 'part_end' in val
            and val['part_begin'] > val['part_end']):
        errs.append(("part_end",
                     ValueError(n_("Must be later than begin."))))
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


_EVENT_FIELD_COMMON_FIELDS = lambda extra_suffix: {
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


_EVENT_FEE_MODIFIER_COMMON_FIELDS = lambda extra_suffix: {
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


_PAST_COURSE_COMMON_FIELDS = lambda: {
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


_COURSE_COMMON_FIELDS = lambda: {
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


_REGISTRATION_COMMON_FIELDS = lambda: {
    'mixed_lodging': _bool,
    'list_consent': _bool,
    'notes': _str_or_None,
    'parts': _mapping,
    'tracks': _mapping,
}
_REGISTRATION_OPTIONAL_FIELDS = lambda: {
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


_LODGEMENT_GROUP_FIELDS = lambda: {
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


_LODGEMENT_COMMON_FIELDS = lambda: {
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
    if kind == FieldDatatypes.date:
        val = val.strftime('%Y-%m-%d')
    elif kind == FieldDatatypes.datetime:
        val = val.strftime('%Y-%m-%dT%H:%M:%S')
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


@_addvalidator
def _json(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """Deserialize a JSON payload.

    This is a bit different from many other validatiors in that it is not
    idempotent.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (dict or None, [(str or None, exception)])

    """
    argname = argname or "json"
    if not _convert:
        raise RuntimeError("This is a conversion by definition.")
    if isinstance(val, bytes):
        try:
            val = val.decode("utf-8")
        except UnicodeDecodeError:
            return None, [(argname, ValueError(n_("Invalid UTF-8 sequence.")))]
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    if not val:
        return None, [(argname, ValueError(n_("Must not be empty.")))]
    try:
        data = json.loads(val)
    except json.decoder.JSONDecodeError as e:
        msg = n_("Invalid JSON syntax (line %(line)s, col %(col)s).")
        return None, [(argname, ValueError(msg, {'line': e.lineno,
                                                 'col': e.colno}))]
    return data, []


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
                          'change_note': _str_or_None}),
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


_PARTIAL_COURSE_COMMON_FIELDS = lambda: {
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


_PARTIAL_LODGEMENT_GROUP_FIELDS = lambda: {
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


_PARTIAL_LODGEMENT_COMMON_FIELDS = lambda: {
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


_PARTIAL_REGISTRATION_COMMON_FIELDS = lambda: {
    'mixed_lodging': _bool,
    'list_consent': _bool,
    'notes': _str_or_None,
    'parts': _mapping,
    'tracks': _mapping,
}
_PARTIAL_REGISTRATION_OPTIONAL_FIELDS = lambda: {
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


_MAILINGLIST_COMMON_FIELDS = lambda: {
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
_MAILINGLIST_OPTIONAL_FIELDS = lambda: {
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
    mandatory_validation_fields = {('moderators', '[id]'),}
    optional_validation_fields = {('whitelist', '[email]'),}
    if "ml_type" not in val:
        return val, [("ml_type", ValueError(
            "Must provide ml_type for setting mailinglist."))]
    atype = ml_type.get_type(val["ml_type"])
    mandatory_validation_fields.update(atype.mandatory_validation_fields)
    optional_validation_fields.update(atype.optional_validation_fields)
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

_SUBSCRIPTION_STATE_FIELDS = lambda: {
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


_ASSEMBLY_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
    'signup_end': _datetime,
    'notes': _str_or_None,
}
_ASSEMBLY_OPTIONAL_FIELDS = lambda: {
    'is_active': _bool,
    'mail_address': _str_or_None,
    'presiders': _iterable,
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
    if 'presiders' in val:
        presiders = set()
        for anid in val['presiders']:
            v, e = _id(anid, 'presiders', _convert=_convert,
                       _ignore_warnings=_ignore_warnings)
            if e:
                errs.extend(e)
            else:
                presiders.add(v)
        val['presiders'] = presiders
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert,
        _ignore_warnings=_ignore_warnings)


_BALLOT_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
    'vote_begin': _datetime,
    'vote_end': _datetime,
    'notes': _str_or_None
}
_BALLOT_OPTIONAL_FIELDS = lambda: {
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
    'shortname': _identifier,
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
    if val.get('shortname') == ASSEMBLY_BAR_SHORTNAME:
        errs.append(("shortname", ValueError(n_("Mustn’t be the bar shortname."))))
    return val, errs


_ASSEMBLY_ATTACHMENT_FIELDS = lambda: {
    'assembly_id': _id_or_None,
    'ballot_id': _id_or_None,
}

_ASSEMBLY_ATTACHMENT_VERSION_FIELDS = lambda: {
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


@_addvalidator
def _vote(val, argname=None, ballot=None, *, _convert=True,
          _ignore_warnings=False):
    """Validate a single voters intent.

    This is mostly made complicated by the fact that we offer to emulate
    ordinary voting instead of full preference voting.

    :type val: object
    :type argname: str or None
    :type ballot: {str: object}
    :param ballot: Ballot the vote was cast for.
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    argname = argname or "vote"
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    entries = tuple(y for x in val.split('>') for y in x.split('='))
    reference = set(e['shortname'] for e in ballot['candidates'].values())
    if ballot['use_bar'] or ballot['votes']:
        reference.add(ASSEMBLY_BAR_SHORTNAME)
    if set(entries) - reference:
        errs.append((argname, KeyError(n_("Superfluous candidates."))))
    if reference - set(entries):
        errs.append((argname, KeyError(n_("Missing candidates."))))
    if errs:
        return None, errs
    if ballot['votes'] and '>' in val:
        # ordinary voting has more constraints
        # if no strictly greater we have a valid abstention
        groups = val.split('>')
        if len(groups) > 2:
            errs.append((argname, ValueError(n_("Too many levels."))))
        if len(groups[0].split('=')) > ballot['votes']:
            errs.append((argname, ValueError(n_("Too many votes."))))
        first_group = groups[0].split('=')
        if (ASSEMBLY_BAR_SHORTNAME in first_group
                and first_group != [ASSEMBLY_BAR_SHORTNAME]):
            errs.append((argname, ValueError(n_("Misplaced bar."))))
        if errs:
            return None, errs
    return val, errs


@_addvalidator
def _regex(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    try:
        re.compile(val)
    except re.error as exc:
        err = ValueError(n_("Invalid  regular expression (position %(pos)s)."),
                         {'pos': exc.pos})
        return None, [(argname, err)]
    return val, errs


@_addvalidator
def _non_regex(val, argname=None, *, _convert=True, _ignore_warnings=False):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type _ignore_warnings: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str(val, argname, _convert=_convert,
                     _ignore_warnings=_ignore_warnings)
    if errs:
        return val, errs
    forbidden_chars = r'\*+?{}()[]|'
    msg = n_(r"Must not contain any forbidden characters"
             r" (which are \*+?{}()[]| while .^$ are allowed).")
    if any(char in val for char in forbidden_chars):
        return None, [(argname, ValueError(msg))]
    return val, errs


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
        errs.append(("fields_of_interest", ValueError(n_("Must not be empty."))))
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
