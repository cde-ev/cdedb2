#!/usr/bin/env python3
# pylint: disable=undefined-variable
## we do some setattrs which confuse pylint

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
argname, *, _convert, **kwargs)`` which are wrapped into the three variants
above. They return the tuple ``(mangled_value, errors)``, where
``errors`` is a list containing tuples ``(argname, exception)``.
"""

import collections.abc
import copy
import datetime
import dateutil.parser
import decimal
import functools
import io
import logging
import magic
import PIL.Image
import pytz
import re
import string
import sys
import werkzeug.datastructures

from cdedb.common import EPSILON, compute_checkdigit, now, extract_roles
from cdedb.serialization import deserialize
from cdedb.validationdata import (
    GERMAN_POSTAL_CODES, GERMAN_PHONE_CODES, ITU_CODES)
from cdedb.query import (
    Query, QueryOperators, VALID_QUERY_OPERATORS, MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS)
from cdedb.config import BasicConfig
from cdedb.enums import ALL_ENUMS
_BASICCONF = BasicConfig()

current_module = sys.modules[__name__]

_LOGGER = logging.getLogger(__name__)

_ALL = []
def _addvalidator(fun):
    """Mark a function for processing into validators.

    Add an inversion of our custom serialization. This is for the
    direction of frontend -> backend.

    :type fun: callable
    """
    _ALL.append(fun)
    @functools.wraps(fun)
    def new_fun(*args, **kwargs):
        args = tuple(deserialize(arg) for arg in args)
        kwargs = {key: deserialize(value) for key, value in kwargs.items()}
        return fun(*args, **kwargs)
    return new_fun

def _examine_dictionary_fields(adict, mandatory_fields, optional_fields=None,
                               *, allow_superfluous=False, _convert=True):
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
    """
    optional_fields = optional_fields or {}
    errs = []
    retval = {}
    mandatory_fields_found = []
    for key, value in adict.items():
        if key in mandatory_fields:
            v, e = mandatory_fields[key](value, argname=key, _convert=_convert)
            if e:
                errs.extend(e)
            else:
                mandatory_fields_found.append(key)
                retval[key] = v
        elif key in optional_fields:
            v, e = optional_fields[key](value, argname=key, _convert=_convert)
            if e:
                errs.extend(e)
            else:
                retval[key] = v
        elif not allow_superfluous:
            errs.append((key, KeyError("Superfluous key found.")))
    if len(mandatory_fields) != len(mandatory_fields_found):
        missing = set(mandatory_fields) - set(mandatory_fields_found)
        for key in missing:
            errs.append((key, KeyError("Mandatory key missing.")))
        retval = None
    return retval, errs

##
## Below is the real stuff
##

@_addvalidator
def _None(val, argname=None, *, _convert=True):
    """Force a None.

    This is mostly for ensuring proper population of dicts.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (object or None, [(str or None, exception)])
    """
    if val is None:
        return val, []
    return None, [(argname, ValueError("Must be None."))]

@_addvalidator
def _any(val, argname=None, *, _convert=True):
    """Dummy to allow arbitrary things.

    This is mostly for deferring checks to a later point if they require
    more logic than should be encoded in a validator.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (object or None, [(str or None, exception)])
    """
    return val, []

@_addvalidator
def _int(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    if _convert:
        if isinstance(val, str):
            try:
                val = int(val)
            except ValueError as e:
                return None, [(argname, e)]
        elif isinstance(val, float):
            if abs(val - int(val)) > EPSILON:
                return None, [(argname, ValueError("Precision loss."))]
            val = int(val)
    if not isinstance(val, int):
        return None, [(argname, TypeError("Must be an integer."))]
    return val, []

@_addvalidator
def _float(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (float or None, [(str or None, exception)])
    """
    if _convert:
        try:
            val = float(val)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, float):
        return None, [(argname, TypeError("Must be a floating point number."))]
    return val, []

@_addvalidator
def _decimal(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (decimal.Decimal or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str):
        try:
            val = decimal.Decimal(val)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            return None, [(argname, e)]
    if not isinstance(val, decimal.Decimal):
        return None, [(argname, TypeError("Must be a decimal.Decimal."))]
    return val, []

@_addvalidator
def _str_type(val, argname=None, *, zap='', sieve='', _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type zap: str
    :param zap: delete all characters in this from the result
    :type sieve: str
    :param sieve: allow only the characters in this into the result
    :rtype: (str or None, [(str or None, exception)])
    """
    if _convert and val is not None:
        try:
            val = str(val)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, str):
        return None, [(argname, TypeError("Must be a string."))]
    if zap:
        val = val.translate(str.maketrans("", "", zap))
    if sieve:
        val = ''.join(c for c in val if c in sieve)
    return val, []


@_addvalidator
def _str(val, argname=None, *, zap='', sieve='', _convert=True):
    """ Like :py:class:`_str_type` (parameters see there), but mustn't be
    empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type zap: str
    :type sieve: str
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_type(val, argname, zap=zap, sieve=sieve, _convert=_convert)
    if val is not None and not val.strip():
        errs.append((argname, ValueError("Mustn't be empty.")))
    return val, errs

@_addvalidator
def _mapping(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :param _convert: is ignored since no useful default conversion is available
    :rtype: (dict or None, [(str or None, exception)])
    """
    if not isinstance(val, collections.abc.Mapping):
        return None, [(argname, TypeError("Must be a mapping."))]
    return val, []

@_addvalidator
def _iterable(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :param _convert: is ignored since no useful default conversion is available
    :rtype: ([object] or None, [(str or None, exception)])
    """
    if not isinstance(val, collections.abc.Iterable):
        return None, [(argname, TypeError("Must be an iterable."))]
    return val, []

@_addvalidator
def _bool(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (bool or None, [(str or None, exception)])
    """
    if _convert and val is not None:
        if val in ("True", "true", "yes", "y"):
            return True, []
        elif val in ("False", "false", "no", "n"):
            return False, []
        try:
            val = bool(val)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, bool):
        return None, [(argname, TypeError("Must be a boolean."))]
    return val, []

_CDEDBID = re.compile('^DB-([0-9]*)-([A-K])$')
@_addvalidator
def _cdedbid(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, errs = _str(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mo = _CDEDBID.search(val)
    if mo is None:
        return None, [(argname, ValueError("Wrong formatting."))]
    value = mo.group(1)
    checkdigit = mo.group(2)
    value, errs = _int(value, argname, _convert=True)
    if not errs and compute_checkdigit(value) != checkdigit:
        errs.append((argname, ValueError("Checksum failure.")))
    return value, errs

_PRINTABLE_ASCII = re.compile('^[ -~]*$')
@_addvalidator
def _printable_ascii_type(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_type(val, argname, _convert=_convert)
    if not errs and not _PRINTABLE_ASCII.search(val):
        errs.append((argname, ValueError("Must be printable ASCII.")))
    return val, errs

@_addvalidator
def _printable_ascii(val, argname=None, *, _convert=True):
    """Like :py:func:`_printable_ascii_type` (parameters see there), but
    mustn't be empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii_type(val, argname, _convert=_convert)
    if val is not None and not val.strip():
        errs.append((argname, ValueError("Mustn't be empty.")))
    return val, errs

_ALPHANUMERIC_REGEX = re.compile(r'^[a-zA-Z0-9]+$')
@_addvalidator
def _alphanumeric(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if not _ALPHANUMERIC_REGEX.search(val):
        errs.append((argname, ValueError("Must be alphanumeric.")))
    return val, errs

_CSV_ALPHANUMERIC_REGEX = re.compile(r'^[a-zA-Z0-9]+(,[a-zA-Z0-9]+)*$')
@_addvalidator
def _csv_alphanumeric(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if not _CSV_ALPHANUMERIC_REGEX.search(val):
        errs.append((argname,
                     ValueError("Must be comma separated alphanumeric.")))
    return val, errs

_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_.-]+$')
@_addvalidator
def _identifier(val, argname=None, *, _convert=True):
    """Identifiers encompass everything from file names to short names for
    events.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if not _IDENTIFIER_REGEX.search(val):
        errs.append((argname, ValueError("Must be an identifier.")))
    return val, errs

_RESTRICTIVE_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_]+$')
@_addvalidator
def _restrictive_identifier(val, argname=None, *, _convert=True):
    """Restrictive identifiers are for situations, where normal identifiers
    are too lax.

    One example are sql column names.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if not _RESTRICTIVE_IDENTIFIER_REGEX.search(val):
        errs.append((argname, ValueError("Must be a restrictiveidentifier.")))
    return val, errs

_CSV_IDENTIFIER_REGEX = re.compile(r'^[a-zA-Z0-9_.-]+(,[a-zA-Z0-9_.-]+)*$')
@_addvalidator
def _csv_identifier(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if not _CSV_IDENTIFIER_REGEX.search(val):
        errs.append((argname,
                     ValueError("Must be comma separated identifiers.")))
    return val, errs

@_addvalidator
def _int_csv_list(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: ([int] or None, [(str or None, exception)])
    """
    if _convert:
        if isinstance(val, str):
            vals = val.split(",")
            val = []
            for entry in vals:
                if not entry:
                    ## skip empty entries which can be produced by Javscript
                    continue
                entry, errs = _int(entry, argname, _convert=_convert)
                if errs:
                    return val, errs
                val.append(entry)
    if not isinstance(val, collections.abc.Sequence):
        return None, [(argname, TypeError("Must be sequence."))]
    for entry in val:
        if not isinstance(entry, int):
            return None, [(argname, TypeError("Must contain integers."))]
    return val, []

@_addvalidator
def _password_strength(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errors = _str(val, argname=argname, _convert=_convert)
    if val:
        if len(val) < 8:
            errors.append((argname,
                           ValueError("Must be at least 8 characters.")))
        if not any(c in "abcdefghijklmnopqrstuvwxyz" for c in val):
            errors.append((argname,
                           ValueError("Must contain a lower case letter.")))
        if not any(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in val):
            errors.append((argname,
                           ValueError("Must contain a upper case letter.")))
        if not any(c in "0123456789" for c in val):
            errors.append((argname, ValueError("Must contain a digit.")))
    return val, errors

_EMAIL_REGEX = re.compile(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$')
@_addvalidator
def _email(val, argname=None, *, _convert=True):
    """We accept only a subset of valid email addresses since implementing the
    full standard is horrendous. Also we normalize emails to lower case.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return None, errs
    ## normalize email addresses to lower case
    val = val.strip().lower()
    if not _EMAIL_REGEX.search(val):
        errs.append((argname, ValueError("Must be a valid email address.")))
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
    'cloud_account': _bool,
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
}
_PERSONA_CDE_CREATION = lambda: {
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _date,
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
    'foto': _str_or_None,
}
_PERSONA_EVENT_CREATION = lambda: {
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _date,
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
    'is_admin': _bool,
    'is_core_admin': _bool,
    'is_cde_admin': _bool,
    'is_event_admin': _bool,
    'is_ml_admin': _bool,
    'is_assembly_admin': _bool,
    'is_cde_realm': _bool,
    'is_event_realm': _bool,
    'is_ml_realm': _bool,
    'is_assembly_realm': _bool,
    'is_member': _bool,
    'is_searchable': _bool,
    'cloud_account': _bool,
    'is_archived': _bool,
    'is_active': _bool,
    'display_name': _str,
    'given_names': _str,
    'family_name': _str,
    'title': _str_or_None,
    'name_supplement': _str_or_None,
    'gender': _enum_genders,
    'birthday': _date,
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
    'balance': _decimal,
    'trial_member': _bool,
    'decided_search': _bool,
    'bub_search': _bool,
    'foto': _str_or_None,
}
@_addvalidator
def _persona(val, argname=None, *, creation=False, transition=False,
             _convert=True):
    """Check a persona data set.

    This is a bit tricky since attributes have different constraints
    according to which status a persona has. Since an all-encompassing
    solution would be quite tedious we expect status-bits only in case
    of creation and transition and apply restrictive tests in all other
    cases.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :type transition: bool
    :param transition: If ``True`` test the data set on fitness for changing
      the realms of a persona.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "persona"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation and transition:
        raise RuntimeError("Only one of creation, transition may be specified.")
    if creation:
        temp, errs = _examine_dictionary_fields(
            val, _PERSONA_TYPE_FIELDS, {}, allow_superfluous=True,
            _convert=_convert)
        if errs:
            return temp, errs
        temp.update({
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        roles = extract_roles(temp)
        optional_fields = {}
        mandatory_fields = copy.deepcopy(_PERSONA_BASE_CREATION())
        if "cde" in roles:
            mandatory_fields.update(_PERSONA_CDE_CREATION())
        if "event" in roles:
            mandatory_fields.update(_PERSONA_EVENT_CREATION())
        ## ml and assembly define no custom fields
    elif transition:
        realm_checks = {
            'is_cde_realm': _PERSONA_CDE_CREATION,
            'is_event_realm': _PERSONA_EVENT_CREATION,
            'is_ml_realm': {},
            'is_assembly_realm': {},
        }
        mandatory_fields = {}
        for key, checkers in realm_checks.items():
            if val.get(key):
                mandatory_fields.update(checkers)
        optional_fields = {key: _bool for key in realm_checks}
    else:
        mandatory_fields = {'id': _int}
        optional_fields = _PERSONA_COMMON_FIELDS()
    val, errs =  _examine_dictionary_fields(val, mandatory_fields,
                                            optional_fields, _convert=_convert)
    if errs:
        return val, errs
    for suffix in ("", "2"):
        if ((not val.get('country' + suffix)
             or val.get('country' + suffix) == "Deutschland")
             and val.get('postal_code' + suffix)):
            postal_code, e = _german_postal_code(
                val['postal_code' + suffix], 'postal_code' + suffix,
                _convert=_convert)
            val['postal_code' + suffix] = postal_code
            errs.extend(e)
    return val, errs

def _parse_date(val):
    """Wrapper around :py:meth:`dateutil.parser.parse` for sanity checks.

    By default :py:mod:`dateutil` substitutes todays values if anything
    is missing from the input. We want no auto-magic defaults so we
    check whether this behaviour happens and raise an exeption if so.

    :type val: str
    :rtype: datetime.date
    """
    default1 = datetime.datetime(1, 1, 1)
    default2 = datetime.datetime(2, 2, 2)
    val1 = dateutil.parser.parse(val, dayfirst=True, default=default1).date()
    val2 = dateutil.parser.parse(val, dayfirst=True, default=default2).date()
    if val1.year == 1 and val2.year == 2:
        raise ValueError("Year missing.")
    if val1.month == 1 and val2.month == 2:
        raise ValueError("Month missing.")
    if val1.day == 1 and val2.day == 2:
        raise ValueError("Day missing.")
    return dateutil.parser.parse(val, dayfirst=True).date()

@_addvalidator
def _date(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (datetime.date or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str) and len(val.strip()) >= 6:
        try:
            val = _parse_date(val)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, datetime.date):
        return None, [(argname, TypeError("Must be a datetime.date."))]
    if isinstance(val, datetime.datetime):
        ## necessary, since isinstance(datetime.datetime.now(),
        ## datetime.date) == True
        val = val.date()
    return val, []

def _parse_datetime(val, default_date=None):
    """Wrapper around :py:meth:`dateutil.parser.parse` for sanity checks.

    By default :py:mod:`dateutil` substitutes values from now if anything
    is missing from the input. We want no auto-magic defaults so we
    check whether this behaviour happens and raise an exeption if so.

    :type val: str
    :type default_date: datetime.date or None
    :rtype: datetime.datetime
    """
    default1 = datetime.datetime(1, 1, 1, 1, 1)
    default2 = datetime.datetime(2, 2, 2, 2, 2)
    val1 = dateutil.parser.parse(val, dayfirst=True, default=default1)
    val2 = dateutil.parser.parse(val, dayfirst=True, default=default2)
    if not default_date and val1.year == 1 and val2.year == 2:
        raise ValueError("Year missing.")
    if not default_date and val1.month == 1 and val2.month == 2:
        raise ValueError("Month missing.")
    if not default_date and val1.day == 1 and val2.day == 2:
        raise ValueError("Day missing.")
    if val1.hour == 1 and val2.hour == 2:
        raise ValueError("Hours missing.")
    if val1.minute == 1 and val2.minute == 2:
        raise ValueError("Minutes missing.")
    if default_date:
        dd = default_date
    else:
        dd = now()
    default = datetime.datetime(dd.year, dd.month, dd.day)
    ret = dateutil.parser.parse(val, dayfirst=True, default=default)
    if ret.tzinfo is None:
        ret = _BASICCONF.DEFAULT_TIMEZONE.localize(ret)
    return ret.astimezone(pytz.utc)

@_addvalidator
def _datetime(val, argname=None, *, _convert=True, default_date=None):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type default_date: datetime.date or None
    :param default_date: If the user-supplied value specifies only a time, this
      parameter allows to fill in the necessary date information to fill
      the gap.
    :rtype: (datetime.datetime or None, [(str or None, exception)])
    """
    if _convert and isinstance(val, str) and len(val.strip()) >= 5:
        try:
            val = _parse_datetime(val, default_date)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, datetime.datetime):
        return None, [(argname, TypeError("Must be a datetime.datetime."))]
    return val, []

@_addvalidator
def _single_digit_int(val, argname=None, *, _convert=True):
    """Like _int, but between +9 and -9.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (int or None, [(str or None, exception)])
    """
    val, errs = _int(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if val > 9 or val < -9:
        return None, [(argname, ValueError("More than one digit."))]
    return val, []

@_addvalidator
def _phone(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    orig = val.strip()
    val = ''.join(c for c in val if c in '+1234567890')
    if len(val) < 7:
        errs.append((argname, ValueError("Too short.")))
        return None, errs

    ## This is pretty horrible, but seems to be the best way ...
    ## It works thanks to the test-suite ;)

    retval = "+"
    ## first the international part
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
            errs.append((argname, ValueError("Invalid international part.")))
        if retval == "+49" and not val.startswith("0"):
            val = "0" + val
    else:
        retval += "49"
    ## now the national part
    if retval == "+49":
        ## german stuff here
        if not val.startswith("0"):
            errs.append((argname, ValueError("Invalid national part.")))
        else:
            val = val[1:]
        for length in range(1, 7):
            if val[:length] in GERMAN_PHONE_CODES:
                retval += " ({}) {}".format(val[:length], val[length:])
                if length + 2 >= len(val):
                    errs.append((argname, ValueError("Invalid local part.")))
                break
        else:
            errs.append((argname, ValueError("Invalid national part.")))
    else:
        index = 0
        try:
            index = orig.index(retval[1:]) + len(retval) - 1
        except ValueError:
            errs.append((argname, ValueError("Invalid international part.")))
        ## this will terminate since we know that there are sufficient digits
        while not orig[index] in string.digits:
            index += 1
        rest = orig[index:]
        sep = ''.join(c for c in rest if c not in string.digits)
        try:
            national = rest[:rest.index(sep)]
            local = rest[rest.index(sep)+len(sep):]
            if not len(national) or not len(local):
                raise ValueError()
            retval += " ({}) {}".format(national, local)
        except ValueError:
            retval += " " + val
    return retval, errs

@_addvalidator
def _german_postal_code(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, _convert=_convert)
    if errs:
        return val, errs
    val = val.strip()
    if val not in GERMAN_POSTAL_CODES:
        errs.append((argname, ValueError("Invalid german postal code.")))
    return val, errs

_GENESIS_CASE_COMMON_FIELDS = lambda: {
    'username': _email,
    'given_names': _str,
    'family_name': _str,
    'realm': _str,
    'notes': _str,
}
_GENESIS_CASE_OPTIONAL_FIELDS = lambda: {
    'realm': _str,
    'case_status': _enum_genesisstati,
    'secret': _str,
    'reviewer': _int,
}
@_addvalidator
def _genesis_case(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "genesis_case"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _GENESIS_CASE_COMMON_FIELDS()
        optional_fields = _GENESIS_CASE_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _int,}
        optional_fields = dict(_GENESIS_CASE_COMMON_FIELDS(),
                               **_GENESIS_CASE_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if ('realm' in val
            and val['realm'] not in ("cde", "event", "ml", "assembly")):
        errs.append(('realm', ValueError("Invalid target realm.")))
    return val, errs

@_addvalidator
def _input_file(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`werkzeug.datastructures.FileStorage` or None,
        [(str or None, exception)])
    """
    if not isinstance(val, werkzeug.datastructures.FileStorage):
        return None, [(argname, TypeError("Not a FileStorage."))]
    return val, []

@_addvalidator
def _profilepic(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`werkzeug.datastructures.FileStorage` or None,
        [(str or None, exception)])
    """
    val, errs = _input_file(val, argname, _convert=_convert)
    if errs:
        return val, errs
    blob = val.read()
    val.seek(0)
    if len(blob) < 1000:
        errs.append((argname, ValueError("Too small.")))
    if len(blob) > 100000:
        errs.append((argname, ValueError("Too big.")))
    mime = magic.from_buffer(blob, mime=True)
    mime = mime.decode() ## python-magic is naughty and returns bytes
    if mime not in ("image/jgp", "image/png"):
        errs.append((argname, ValueError("Only jpg and png allowed.")))
    if errs:
        return None, errs
    image = PIL.Image.open(io.BytesIO(blob))
    width, height = image.size
    if width / height < 0.9 or height / width < 0.9:
        errs.append((argname, ValueError("Not square enough.")))
    if width * height < 5000:
        errs.append((argname, ValueError("Resolution too small.")))
    return val, errs

@_addvalidator
def _pdffile(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`werkzeug.datastructures.FileStorage` or None,
        [(str or None, exception)])
    """
    val, errs = _input_file(val, argname, _convert=_convert)
    if errs:
        return val, errs
    blob = val.read()
    val.seek(0)
    mime = magic.from_buffer(blob, mime=True)
    mime = mime.decode() ## python-magic is naughty and returns bytes
    if mime != "application/pdf":
        errs.append((argname, ValueError("Only pdf allowed.")))
    return val, errs


_LASTSCHRIFT_COMMON_FIELDS = lambda: {
    'amount': _decimal,
    'iban': _str,
    'account_owner': _str_or_None,
    'account_address': _str_or_None,
    'notes': _str_or_None,
}
_LASTSCHRIFT_OPTIONAL_FIELDS = lambda: {
    'max_dsa': _decimal,
    'granted_at': _datetime,
    'revoked_at': _datetime_or_None,
}
@_addvalidator
def _lastschrift_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lastschrift_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(), persona_id=_int)
        optional_fields = _LASTSCHRIFT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _int}
        optional_fields = dict(_LASTSCHRIFT_COMMON_FIELDS(),
                               **_LASTSCHRIFT_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    return val, errs

_LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS = lambda: {
    'amount': _decimal,
    'status': _int,
    'issued_at': _datetime,
    'processed_at': _datetime_or_None,
    'tally': _decimal_or_None,
}
@_addvalidator
def _lastschrift_transaction(val, argname=None, *, creation=False,
                             _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lastschrift_transaction"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = {
            'lastschrift_id': _int,
            'period_id': _int,
        }
        optional_fields = _LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _int}
        optional_fields = dict(_LASTSCHRIFT_TRANSACTION_COMMON_FIELDS,
                               **_LASTSCHRIFT_TRANSACTION_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    return val, errs

def asciificator(s):
    """Pacify a string.

    Replace or omit all characters outside a known good set. This is to
    be used if your use case does not tolerate any fancy characters
    (like SEPA files).

    :type s: str
    :rtype: str
    """
    umlaut_map = {
        "ä": "ae", "æ": "ae",
        "ö": "oe", "ø": "oe", "œ": "oe",
        "ü": "ue",
        "ß": "ss",
        "à": "a", "á": "a", "â": "a", "ã": "a", "ä": "a", "å": "a", "ą": "a",
        "ç": "c", "č": "c", "ć": "c",
        "è": "e", "é": "e", "ê": "e", "ë": "e", "ę": "e",
        "ì": "i", "í": "i", "î": "i", "ï": "i",
        "ł": "l",
        "ñ": "n", "ń": "n",
        "ò": "o", "ó": "o", "ô": "o", "õ": "o", "ö": "o", "ø": "o", "ő": "o",
        "ù": "u", "ú": "u", "û": "u", "ü": "u", "ű": "u",
        "ý": "y", "ÿ": "y",
        "ź": "z", "z": "z",
    }
    ret = ""
    for char in s:
        if char in umlaut_map:
            ret += umlaut_map[char]
        elif char in (string.ascii_letters + string.digits + " /-?:().,+"):
            ret += char
        else:
            ret += ' '
    return ret

_SEPA_DATA_FIELDS = {
    'issued_at': _datetime,
    'lastschrift_id': _int,
    'period_id': _int,
    'mandate_reference': _str,
    'amount': _decimal,
    'iban': _str,
    'mandate_date': _date,
    'account_owner': _str,
    'unique_id': _str,
    'subject': _str,
    'type': _str,
}
_SEPA_DATA_LIMITS = {
    'account_owner': 70,
    'subject': 140,
    'mandate_reference': 35,
    'unique_id': 35,
}
@_addvalidator
def _sepa_data(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (tuple or None, [(str or None, exception)])
    """
    argname = argname or "sepa_data"
    val, errs = _iterable(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_DATA_FIELDS
    optional_fields = {}
    ret = []
    for entry in val:
        entry, e = _mapping(entry, argname, _convert=_convert)
        if e:
            errs.extend(e)
            continue
        entry, e = _examine_dictionary_fields(
            entry, mandatory_fields, optional_fields, _convert=_convert)
        if e:
            errs.extend(e)
            continue
        for attribute, validator in _SEPA_DATA_FIELDS.items():
            if validator == _str:
                entry[attribute] = asciificator(entry[attribute])
            if attribute in _SEPA_DATA_LIMITS:
                if len(entry[attribute]) > _SEPA_DATA_LIMITS[attribute]:
                    errs.append((attribute, ValueError("Too long.")))
        if entry['type'] not in ("OOFF", "FRST", "RCUR"):
            errs.append(('type', ValueError("Invalid constant.")))
        if errs:
            continue
        ret.append(entry)
    return ret, errs

_SEPA_META_FIELDS = {
    'message_id': _str,
    'total_sum': _decimal,
    'partial_sums': _mapping,
    'count': _int,
    'sender': _mapping,
    'payment_date': _date,
}
_SEPA_SENDER_FIELDS = {
    'name': _str,
    'address': _iterable,
    'country': _str,
    'iban': _str,
    'glaeubigerid': _str,
}
_SEPA_META_LIMITS = {
    'message_id': 35,
    ## 'name': 70, easier to check by hand
    ## 'address': 70, has to be checked by hand
    'glaeubigerid': 35,
}
@_addvalidator
def _sepa_meta(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "sepa_meta"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_META_FIELDS
    optional_fields = {}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _SEPA_SENDER_FIELDS
    val['sender'], errs = _examine_dictionary_fields(
        val['sender'], mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    for attribute, validator in _SEPA_META_FIELDS.items():
        if validator == _str:
            val[attribute] = asciificator(val[attribute])
        if attribute in _SEPA_META_LIMITS:
            if len(val[attribute]) > _SEPA_META_LIMITS[attribute]:
                errs.append((attribute, ValueError("Too long.")))
    if val['sender']['country'] != "DE":
        errs.append(('country', ValueError("Unsupported constant.")))
    if len(val['sender']['address']) != 2:
        errs.append(('address', ValueError("Exactly two lines required.")))
    val['sender']['address'] = tuple(asciificator(x)
                                     for x in val['sender']['address'])
    for line in val['sender']['address']:
        if len(line) > 70:
            errs.append(('address', ValueError("Too long.")))
    for attribute, validator in _SEPA_SENDER_FIELDS.items():
        if validator == _str:
            val['sender'][attribute] = asciificator(val['sender'][attribute])
    if len(val['sender']['name']) > 70:
        errs.append(('name', ValueError("Too long.")))
    if errs:
        return None, errs
    return val, errs

@_addvalidator
def _safe_str(val, argname=None, *, _convert=True):
    """This allows alpha-numeric, whitespace and known good others.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    ALLOWED = ".,-+()/"
    val, errs = _str(val, argname, _convert=_convert)
    if errs:
        return val, errs
    for char in val:
        if not (char.isalnum() or char.isspace() or char in ALLOWED):
            errs.append((argname,
                         ValueError("Forbidden character ({}).".format(char))))
    if errs:
        return None, errs
    return val, errs

@_addvalidator
def _cde_meta_info(val, keys, argname=None, *, _convert=True):
    """
    :type val: object
    :type keys: [str]
    :type argname: str or None
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "cde_meta_info"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = {}
    optional_fields = {key: _safe_str for key in keys}
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    return val, errs

_PAST_EVENT_COMMON_FIELDS = lambda: {
    'title': _str,
    'organizer': _str,
    'tempus': _date,
    'description': _str_or_None,
}
@_addvalidator
def _past_event_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "past_event_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _PAST_EVENT_COMMON_FIELDS()
        optional_fields = {}
    else:
        mandatory_fields = {'id': _int,}
        optional_fields = _PAST_EVENT_COMMON_FIELDS()
    return _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                      _convert=_convert)

_EVENT_COMMON_FIELDS = lambda: {
    'title': _str,
    'organizer': _str,
    'description': _str_or_None,
    'shortname': _identifier,
    'registration_start': _date_or_None,
    'registration_soft_limit': _date_or_None,
    'registration_hard_limit': _date_or_None,
    'iban': _str_or_None,
    'use_questionnaire': _bool,
    'notes': _str_or_None,
}
_EVENT_OPTIONAL_FIELDS = {
    'offline_lock': _bool,
    'orgas': _any,
    'parts': _any,
    'fields': _any,
}
@_addvalidator
def _event_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_COMMON_FIELDS()
        optional_fields = _EVENT_OPTIONAL_FIELDS
    else:
        mandatory_fields = {'id': _int}
        optional_fields = dict(_EVENT_COMMON_FIELDS(),
                               **_EVENT_OPTIONAL_FIELDS)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if 'orgas' in val:
        oldorgas, e = _iterable(val['orgas'], "orgas", _convert=_convert)
        if e:
            errs.extend(e)
        else:
            orgas = set()
            for anid in oldorgas:
                v, e = _int(anid, 'orgas', _convert=_convert)
                if e:
                    errs.extend(e)
                else:
                    orgas.add(v)
            val['orgas'] = orgas
    if 'parts' in val:
        oldparts, e = _mapping(val['parts'], 'parts', _convert=_convert)
        if e:
            errs.extend(e)
        else:
            newparts = {}
            for anid, partdata in oldparts.items():
                anid, e = _int(anid, 'parts', _convert=_convert)
                if e:
                    errs.extend(e)
                else:
                    creation = (anid < 0)
                    partdata, ee = _event_part_data_or_None(
                        partdata, 'parts', creation=creation,
                        _convert=_convert)
                    if ee:
                        errs.extend(ee)
                    else:
                        newparts[anid] = partdata
            val['parts'] = newparts
    if 'fields' in val:
        oldfields, e = _mapping(val['fields'], 'fields', _convert=_convert)
        if e:
            errs.extend(e)
        else:
            newfields = {}
            for anid, fielddata in oldfields.items():
                anid, e = _int(anid, 'fields', _convert=_convert)
                if e:
                    errs.extend(e)
                else:
                    creation = (anid < 0)
                    fielddata, ee = _event_field_data_or_None(
                        fielddata, 'fields', creation=creation,
                        _convert=_convert)
                    if ee:
                        errs.extend(ee)
                    else:
                        newfields[anid] = fielddata
            val['fields'] = newfields
    return val, errs

_EVENT_PART_COMMON_FIELDS = {
    'title': _str,
    'part_begin': _date,
    'part_end': _date,
    'fee': _decimal,
}
@_addvalidator
def _event_part_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_part_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _EVENT_PART_COMMON_FIELDS
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_PART_COMMON_FIELDS
    return _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                      _convert=_convert)

_EVENT_FIELD_COMMON_FIELDS = {
    'kind': _str,
    'entries': _any,
}
@_addvalidator
def _event_field_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_field_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_EVENT_FIELD_COMMON_FIELDS,
                                field_name=_restrictive_identifier)
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _EVENT_FIELD_COMMON_FIELDS
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if not val.get('entries', True):
        val['entries'] = None
    if 'entries' in val and val['entries'] is not None:
        if isinstance(val['entries'], str) and _convert:
            val['entries'] = tuple(tuple(y.strip() for y in x.split(';', 1))
                                   for x in val['entries'].split('\n'))
        oldentries, e = _iterable(val['entries'], "entries", _convert=_convert)
        seen_values = set()
        if e:
            errs.extend(e)
        else:
            entries = []
            for entry in oldentries:
                try:
                    value, description = entry
                except (ValueError, TypeError) as e:
                    errs.append(("entries", e))
                else:
                    value, e = _str(value, "entries", _convert=_convert)
                    description, ee = _str(description, "entries",
                                           _convert=_convert)
                    if value in seen_values:
                        e.append(("entries", ValueError("Duplicate value.")))
                    if e or ee:
                        errs.extend(e)
                        errs.extend(ee)
                    else:
                        entries.append((value, description))
                        seen_values.add(value)
            val['entries'] = entries
    return val, errs

_PAST_COURSE_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
}
@_addvalidator
def _past_course_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "past_course_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_PAST_COURSE_COMMON_FIELDS(), pevent_id=_int)
        optional_fields = {}
    else:
        ## no pevent_id, since the associated event should be fixed
        mandatory_fields = {'id': _int}
        optional_fields = _PAST_COURSE_COMMON_FIELDS()
    return _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                      _convert=_convert)

_COURSE_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
    'nr': _str_or_None,
    'shortname': _str,
    'instructors': _str_or_None,
    'notes': _str_or_None,
}
_COURSE_OPTIONAL_FIELDS = {
    'parts': _any,
}
@_addvalidator
def _course_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "course_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_COURSE_COMMON_FIELDS(), event_id=_int)
        optional_fields = _COURSE_OPTIONAL_FIELDS
    else:
        ## no event_id, since the associated event should be fixed
        mandatory_fields = {'id': _int}
        optional_fields = dict(_COURSE_COMMON_FIELDS(),
                               **_COURSE_OPTIONAL_FIELDS)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if 'parts' in val:
        oldparts, e = _iterable(val['parts'], 'parts', _convert=_convert)
        if e:
            errs.extend(e)
        else:
            parts = set()
            for anid in oldparts:
                v, e = _int(anid, 'parts', _convert=_convert)
                if e:
                    errs.extend(e)
                else:
                    parts.add(v)
            val['parts'] = parts
    return val, errs

_REGISTRATION_COMMON_FIELDS = lambda: {
    'mixed_lodging': _bool,
    'foto_consent': _bool,
    'notes': _str_or_None,
    'parts': _any,
}
_REGISTRATION_OPTIONAL_FIELDS = lambda: {
    'parental_agreement': _bool_or_None,
    'real_persona_id': _int_or_None,
    'choices': _any,
    'orga_notes': _str_or_None,
    'payment': _date_or_None,
    'checkin': _datetime_or_None,
}
@_addvalidator
def _registration_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration_data"

    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        ## creation does not allow field_data for sake of simplicity
        mandatory_fields = dict(_REGISTRATION_COMMON_FIELDS(),
                                persona_id=_int, event_id=_int)
        optional_fields = _REGISTRATION_OPTIONAL_FIELDS()
    else:
        ## no event_id/persona_id, since associations should be fixed
        mandatory_fields = {'id': _int}
        optional_fields = dict(_REGISTRATION_COMMON_FIELDS(),
                               field_data=_any,
                               **_REGISTRATION_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if 'parts' in val:
        oldparts, e = _mapping(val['parts'], 'parts', _convert=_convert)
        if e:
            errs.extend(e)
        else:
            newparts = {}
            for anid, part in oldparts.items():
                anid, e = _int(anid, 'parts', _convert=_convert)
                part, ee = _registration_part_data_or_None(part, 'parts',
                                                           _convert=_convert)
                if e or ee:
                    errs.extend(e)
                    errs.extend(ee)
                else:
                    newparts[anid] = part
            val['parts'] = newparts
    if 'choices' in val:
        oldchoices, e = _mapping(val['choices'], 'choices', _convert=_convert)
        if e:
            errs.extend(e)
        else:
            newchoices = {}
            for part_id, choice_list in oldchoices.items():
                part_id, e = _int(part_id, 'choices', _convert=_convert)
                choice_list, ee = _iterable(choice_list, 'choices',
                                            _convert=_convert)
                if e or ee:
                    errs.extend(e)
                    errs.extend(ee)
                else:
                    new_list = []
                    for choice in choice_list:
                        choice, e = _int(choice, 'choices', _convert=_convert)
                        if e:
                            errs.extend(e)
                            break
                        else:
                            new_list.append(choice)
                    else:
                        newchoices[part_id] = new_list
            val['choices'] = newchoices
    ## the check of field_data is delegated to _registration_field_data
    return val, errs

@_addvalidator
def _registration_part_data(val, argname=None, *, _convert=True):
    """This validator has only optional fields. Normally we would have an
    creation parameter and make stuff mandatory depending on that. But
    from the data at hand it is impossible to decide when the creation
    case is applicable.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "registration_part_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    optional_fields = {
        'course_id': _int_or_None,
        'status': _enum_registrationpartstati,
        'lodgement_id': _int_or_None,
        'course_instructor': _int_or_None
    }
    return _examine_dictionary_fields(val, {}, optional_fields,
                                      _convert=_convert)

@_addvalidator
def _registration_field_data(val, argname=None, fields=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type fields: {int: dict}
    :param fields: definition of the event specific fields which are available
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "field_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    optional_fields = {
        field['field_name']: getattr(current_module,
                                     "_{}_or_None".format(field['kind']))
        for field in fields.values()
    }
    val, errs = _examine_dictionary_fields(val, {}, optional_fields,
                                           _convert=_convert)
    if errs:
        return val, errs
    for field in val:
        field_id = next(anid for anid, entry in fields.items()
                        if entry['field_name'] == field)
        if fields[field_id]['entries'] is not None:
            if val[field] not in (x for x, _ in fields[field_id]['entries']):
                errs.append((field, ValueError("Entry in definition list.")))
    return val, errs

_LODGEMENT_COMMON_FIELDS = lambda: {
    'moniker': _str,
    'capacity': _int,
    'reserve': _int,
    'notes': _str_or_None
}
@_addvalidator
def _lodgement_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "lodgement_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_LODGEMENT_COMMON_FIELDS(), event_id=_int)
        optional_fields = {}
    else:
        ## no event_id, since the associated event should be fixed
        mandatory_fields = {'id': _int}
        optional_fields = _LODGEMENT_COMMON_FIELDS()
    return _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                      _convert=_convert)

@_addvalidator
def _questionnaire_data(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: ([dict] or None, [(str or None, exception)])
    """
    argname = argname or "questionnaire_data"
    val, errs = _iterable(val, argname, _convert=_convert)
    if errs:
        return val, errs
    ret = []
    for value in val:
        value, e = _mapping(value, argname, _convert=_convert)
        if e:
            errs.extend(e)
        else:
            mandatory_fields = {
                'field_id': _int_or_None,
                'title': _str_or_None,
                'info': _str_or_None,
                'input_size': _int_or_None,
                'readonly': _bool_or_None,
            }
            value, e = _examine_dictionary_fields(
                value, mandatory_fields, {}, _convert=_convert)
            if e:
                errs.extend(e)
            else:
                ret.append(value)
    return ret, errs


_MAILINGLIST_COMMON_FIELDS = lambda: {
    'title': _str,
    'address': _email,
    'description': _str_or_None,
    'sub_policy': _enum_subscriptionpolicy,
    'mod_policy': _enum_moderationpolicy,
    'attachment_policy': _enum_attachmentpolicy,
    'audience_policy': _enum_audiencepolicy,
    'subject_prefix': _str_or_None,
    'maxsize': _int_or_None,
    'is_active': _bool,
    'gateway': _int_or_None,
    'event_id': _int_or_None,
    'registration_stati': _any,
    'assembly_id': _int_or_None,
    'notes': _str_or_None,
}
_MAILINGLIST_OPTIONAL_FIELDS = {
    'moderators': _any,
    'whitelist': _any,
}
@_addvalidator
def _mailinglist_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "mailinglist_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _MAILINGLIST_COMMON_FIELDS()
        optional_fields = _MAILINGLIST_OPTIONAL_FIELDS
    else:
        mandatory_fields = {'id': _int}
        optional_fields = dict(_MAILINGLIST_COMMON_FIELDS(),
                               **_MAILINGLIST_OPTIONAL_FIELDS)
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    for key, validator in (('registration_stati', _enum_registrationpartstati),
                           ('moderators', _int), ('whitelist', _email)):
        if key in val:
            oldarray, e = _iterable(val[key], key, _convert=_convert)
            if e:
                errs.extend(e)
            else:
                newarray = []
                for anid in oldarray:
                    v, e = validator(anid, key, _convert=_convert)
                    if e:
                        errs.extend(e)
                    else:
                        newarray.append(v)
                val[key] = newarray
    return val, errs

_ASSEMBLY_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
    'signup_end': _datetime,
    'notes': _str_or_None,
}
_ASSEMBLY_OPTIONAL_FIELDS = {
    'is_active': _bool,
}
@_addvalidator
def _assembly_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "assembly_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _ASSEMBLY_COMMON_FIELDS()
        optional_fields = _ASSEMBLY_OPTIONAL_FIELDS
    else:
        mandatory_fields = {'id': _int,}
        optional_fields = dict(_ASSEMBLY_COMMON_FIELDS(),
                               **_ASSEMBLY_OPTIONAL_FIELDS)
    return _examine_dictionary_fields(val, mandatory_fields, optional_fields,
                                      _convert=_convert)

_BALLOT_COMMON_FIELDS = lambda: {
    'title': _str,
    'description': _str_or_None,
    'vote_begin': _datetime,
    'vote_end': _datetime,
    'vote_extension_end': _datetime_or_None,
    'notes': _str_or_None
}
_BALLOT_OPTIONAL_FIELDS = lambda: {
    'extended': _bool_or_None,
    'quorum': _int,
    'votes': _int_or_None,
    'bar': _int_or_None,
    'is_tallied': _bool,
    'candidates': _any
}
@_addvalidator
def _ballot_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "ballot_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = dict(_BALLOT_COMMON_FIELDS(), assembly_id=_int)
        optional_fields = _BALLOT_OPTIONAL_FIELDS()
    else:
        mandatory_fields = {'id': _int}
        optional_fields = dict(_BALLOT_COMMON_FIELDS(),
                               **_BALLOT_OPTIONAL_FIELDS())
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if 'candidates' in val:
        oldcandidates, e = _mapping(val['candidates'], 'candidates',
                                    _convert=_convert)
        if e:
            errs.extend(e)
        else:
            newcandidates = {}
            for anid, candidate in oldcandidates.items():
                anid, e = _int(anid, 'candidates', _convert=_convert)
                if e:
                    errs.extend(e)
                else:
                    creation = (anid < 0)
                    candidate, ee = _ballot_candidate_data_or_None(
                        candidate, 'candidates', creation=creation,
                        _convert=_convert)
                    if ee:
                        errs.extend(ee)
                    else:
                        newcandidates[anid] = candidate
            val['candidates'] = newcandidates
    return val, errs

_BALLOT_CANDIDATE_COMMON_FIELDS = {
    'description': _str,
    'moniker': _identifier,
}
@_addvalidator
def _ballot_candidate_data(val, argname=None, *, creation=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type creation: bool
    :param creation: If ``True`` test the data set on fitness for creation
      of a new entity.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "ballot_candidate_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if creation:
        mandatory_fields = _BALLOT_CANDIDATE_COMMON_FIELDS
        optional_fields = {}
    else:
        mandatory_fields = {}
        optional_fields = _BALLOT_CANDIDATE_COMMON_FIELDS
    return _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)

_ASSEMBLY_ATTACHMENT_COMMON_FIELDS = {
    "title": _str,
    "filename": _identifier,
}
_ASSEMBLY_ATTACHMENT_OPTIONAL_FIELDS = {
    "assembly_id": _int,
    "ballot_id": _int,
}
@_addvalidator
def _assembly_attachment_data(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "assembly_attachment_data"
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _ASSEMBLY_ATTACHMENT_COMMON_FIELDS
    optional_fields = _ASSEMBLY_ATTACHMENT_OPTIONAL_FIELDS
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, _convert=_convert)
    if errs:
        return val, errs
    if "assembly_id" in val and "ballot_id" in val:
        errs.append((argname, ValueError("Only one host allowed.")))
    if "assembly_id" not in val and "ballot_id" not in val:
        errs.append((argname, ValueError("No host given.")))
    if errs:
        return None, errs
    return val, errs

@_addvalidator
def _vote(val, argname=None, ballot=None, *, _convert=True):
    """Validate a single voters intent.

    This is mostly made complicated by the fact that we offer to emulate
    ordinary voting instead of full preference voting.

    :type val: object
    :type argname: str or None
    :type ballot: {str: object}
    :param ballot: Ballot the vote was cast for.
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    argname = argname or "vote"
    val, errs = _str(val, argname, _convert=_convert)
    if errs:
        return val, errs
    entries = tuple(y for x in val.split('>') for y in x.split('='))
    reference = set(e['moniker'] for e in ballot['candidates'].values())
    if set(entries) - reference:
        errs.append((argname, KeyError("Superfluous candidates.")))
    if reference - set(entries):
        errs.append((argname, KeyError("Missing candidates.")))
    if errs:
        return None, errs
    if ballot['votes'] and '>' in val:
        ## ordinary voting has more constraints
        ## if no strictly greater we have a valid abstention
        bar = ballot['candidates'][ballot['bar']]['moniker']
        num = entries.index(bar)
        if num > ballot['votes']:
            errs.append((argname, ValueError("Too many votes.")))
        groups = val.split('>')
        if len(groups) > 3:
            errs.append((argname, ValueError("Too many levels.")))
        elif len(groups) == 3:
            if groups[1] != bar:
                errs.append((argname, ValueError("Misplaced bar.")))
        elif len(groups) == 2:
            if bar not in groups:
                errs.append((argname, ValueError("Non-sharp bar.")))
        else:
            raise RuntimeError("Impossible.")
        if errs:
            return None, errs
    return val, errs

@_addvalidator
def _regex(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_or_None(val, argname, _convert=_convert)
    if errs:
        return val, errs
    try:
        re.compile(val)
    # TODO Is there something more specific we can catch? This is bad style.
    except Exception as e:
        return None, [(argname, e)]
    return val, errs

@_addvalidator
def _query_input(val, argname=None, *, spec=None, allow_empty=False,
                 _convert=True):
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
    :rtype: (:py:class:`cdedb.query.Query` or None, [(str or None, exception)])
    """
    if spec is None:
        raise RuntimeError("Query must be specified.")
    val, errs = _mapping(val, argname, _convert=_convert)
    fields_of_interest = []
    constraints = []
    order = []
    SEPERATOR = ' '
    for field, validator in spec.items():
        ## First the selection
        selected, e = _bool(val.get("qsel_{}".format(field), "False"), field,
                            _convert=_convert)
        errs.extend(e)
        if selected:
            fields_of_interest.append(field)
        ## Second the constraints
        operator, e = _enum_queryoperators_or_None(
            val.get("qop_{}".format(field)), field, _convert=_convert)
        errs.extend(e)
        if e or not operator:
            continue
        if operator not in VALID_QUERY_OPERATORS[validator]:
            errs.append((field, ValueError("Invalid operator.")))
            continue
        if operator in NO_VALUE_OPERATORS:
            constraints.append((field, operator, None))
            continue
        value = val.get("qval_{}".format(field))
        if value is None or value == "":
            ## No value supplied means no constraint
            continue
        if operator in MULTI_VALUE_OPERATORS:
            values = value.split(SEPERATOR)
            value = []
            for v in values:
                vv, e = getattr(current_module,
                                "_{}_or_None".format(validator))(
                                    v, field, _convert=_convert)
                errs.extend(e)
                if e or not vv:
                    continue
                value.append(vv)
            if not value:
                continue
            if operator == QueryOperators.between and len(value) != 2:
                errs.append((field, ValueError("Two endpoints required.")))
                continue
        elif operator == QueryOperators.regex:
            value, e = _regex_or_None(value, field, _convert=_convert)
            errs.extend(e)
            if e or not value:
                continue
        else:
            value, e = getattr(current_module, "_{}_or_None".format(validator))(
                value, field, _convert=_convert)
            errs.extend(e)
            if e:
                continue
        if value is not None:
            constraints.append((field, operator, value))
    if not fields_of_interest and not allow_empty:
        errs.append((argname, ValueError("Selection may not be empty.")))
    ## Third the ordering
    for postfix in ("primary", "secondary", "tertiary"):
        if "qord_" + postfix not in val:
            continue
        value, e = _csv_identifier_or_None(val["qord_" + postfix],
                                           "qord_" + postfix, _convert=_convert)
        errs.extend(e)
        tmp = "qord_" + postfix + "_ascending"
        ascending, e = _bool(val.get(tmp, "True"), tmp, _convert=_convert)
        errs.extend(e)
        if value:
            if value in fields_of_interest:
                order.append((value, ascending))
            else:
                errs.append(("qord_" + postfix, KeyError("Must be selected.")))
    if errs:
        return None, errs
    return Query(None, spec, fields_of_interest, constraints, order), errs

@_addvalidator
def _serialized_query(val, argname=None, *, _convert=True):
    """This is for the queries from frontend to backend.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`cdedb.query.Query` or None, [(str or None, exception)])
    """
    val, errs = _mapping(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if set(val) != {"scope", "spec", "fields_of_interest", "constraints",
                    "order"}:
        return None, [(argname, ValueError("Wrong keys."))]
    ## scope
    scope, e = _identifier(val['scope'], "scope", _convert=_convert)
    errs.extend(e)
    if scope and not scope.startswith("qview_"):
        errs.append(("scope", ValueError("Must start with 'qview_'.")))
    ## spec
    spec_val, e = _mapping(val['spec'], "spec", _convert=_convert)
    errs.extend(e)
    if errs:
        return None, errs
    spec = {}
    for field, validator in spec_val.items():
        field, e = _csv_identifier(field, "spec", _convert=_convert)
        errs.extend(e)
        validator, e = _printable_ascii(validator, "spec", _convert=_convert)
        errs.extend(e)
        spec[field] = validator
    ## fields_of_interest
    fields_of_interest = []
    oldfields, e = _iterable(val['fields_of_interest'], 'fields_of_interest',
                             _convert=_convert)
    if e:
        errs.extend(e)
    else:
        for field in oldfields:
            field, e = _csv_identifier(field, "fields_of_interest",
                                       _convert=_convert)
            fields_of_interest.append(field)
            errs.extend(e)
    if not fields_of_interest:
        errs.append(("fields_of_interest", ValueError("Mustn't be empty.")))
    ## constraints
    constraints = []
    oldconstraints, e = _iterable(val['constraints'], 'constraints',
                                  _convert=_convert)
    if e:
        errs.extend(e)
    else:
        for x in oldconstraints:
            try:
                field, operator, value = x
            except ValueError as e:
                errs.append(("constraints", e))
                continue
            field, e = _csv_identifier(field, "constraints", _convert=_convert)
            errs.extend(e)
            if field not in spec:
                errs.append(("constraints", KeyError("Invalid field.")))
                continue
            operator, e = _enum_queryoperators(
                operator, "constraints/{}".format(field), _convert=_convert)
            errs.extend(e)
            if operator not in VALID_QUERY_OPERATORS[spec[field]]:
                errs.append(("constraints/{}".format(field),
                             ValueError("Invalid operator.")))
                continue
            if operator in NO_VALUE_OPERATORS:
                value = None
            elif operator in MULTI_VALUE_OPERATORS:
                tmp = []
                validator = getattr(current_module, "_{}".format(spec[field]))
                for v in value:
                    v, e = validator(v, "constraints/{}".format(field),
                                     _convert=_convert)
                    tmp.append(v)
                    errs.extend(e)
                value = tmp
            else:
                value, e = getattr(current_module, "_{}".format(spec[field]))(
                    value, "constraints/{}".format(field), _convert=_convert)
            errs.extend(e)
            constraints.append((field, operator, value))
    ## order
    order = []
    oldorder, e = _iterable(val['order'], 'order', _convert=_convert)
    if e:
        errs.extend(e)
    else:
        for entry in oldorder:
            entry, e = _iterable(entry, 'order', _convert=_convert)
            errs.extend(e)
            if e:
                continue
            try:
                field, ascending = entry
            except ValueError as e:
                errs.append(('order', e))
            else:
                field, e = _csv_identifier(field, "order", _convert=_convert)
                ascending, ee = _bool(ascending, "order", _convert=_convert)
                order.append((field, ascending))
                errs.extend(e)
                errs.extend(ee)
    if errs:
        return None, errs
    else:
        return Query(scope, spec, fields_of_interest, constraints, order), errs

def _enum_validator_maker(anenum, name=None):
    """Automate validator creation for enums.

    Since this is pretty generic we do this all in one go.

    :type anenum: enum
    :type name: str or None
    :param name: If given determines the name of the validator, otherwise the
      name is inferred from the name of the enum.
    """
    def the_validator(val, argname=None, *, _convert=True):
        """
        :type val: object
        :type argname: str or None
        :type _convert: bool
        :rtype: (enum or None, [(str or None, exception)])
        """
        val, errs = _int(val, argname=argname, _convert=_convert)
        if errs:
            return val, errs
        try:
            val = anenum(val)
        except ValueError as e:
            return None, [(argname, e)]
        return val, errs

    the_validator.__name__ = name or "_enum_{}".format(anenum.__name__.lower())
    _addvalidator(the_validator)
    setattr(current_module, the_validator.__name__, the_validator)

for oneenum in ALL_ENUMS:
    _enum_validator_maker(oneenum)

##
## Above is the real stuff
##

def _create_assert_valid(fun):
    """
    :type fun: callable
    """
    @functools.wraps(fun)
    def new_fun(*args, **kwargs):
        val, errs = fun(*args, **kwargs)
        if errs:
            e = errs[0][1]
            e.args = ("{} ({})".format(e.args[0], errs[0][0]),) + e.args[1:]
            raise e
        return val
    return new_fun

def _create_is_valid(fun):
    """
    :type fun: callable
    """
    @functools.wraps(fun)
    def new_fun(*args, **kwargs):
        kwargs['_convert'] = False
        _, errs = fun(*args, **kwargs)
        return not errs
    return new_fun

def _create_check_valid(fun):
    """
    :type fun: callable
    """
    @functools.wraps(fun)
    def new_fun(*args, **kwargs):
        val, errs = fun(*args, **kwargs)
        if errs:
            _LOGGER.debug("VALIDATION ERROR for '{}' with input {}, {}.".format(
                fun.__name__, args, kwargs))
            return None, errs
        return  val, errs
    return new_fun

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
            except: ## we need to catch everything
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
