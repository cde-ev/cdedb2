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


import re
import sys
import functools
import collections.abc
import decimal
import datetime
import dateutil.parser
import copy
import string
import pytz
import werkzeug.datastructures
import magic
import PIL.Image
import io

from itertools import chain
current_module = sys.modules[__name__]

from cdedb.common import EPSILON
from cdedb.validationdata import (
    GERMAN_POSTAL_CODES, GERMAN_PHONE_CODES, ITU_CODES)
from cdedb.query import (
    Query, QueryOperators, VALID_QUERY_OPERATORS, MULTI_VALUE_OPERATORS,
    NO_VALUE_OPERATORS)
from cdedb.config import BasicConfig
_BASICCONF = BasicConfig()

_ALL = []
def _addvalidator(fun):
    """Mark a function for processing into validators.

    :type fun: callable
    """
    _ALL.append(fun)
    return fun

def _examine_dictionary_fields(adict, mandatory_fields, optional_fields=None,
                               *, strict=False, allow_superfluous=False,
                               _convert=True):
    """Check more complex dictionaries.

    :type adict: dict
    :param adict: a :py:class:`dict` to check
    :type mandatory_fields: {str : callable}
    :param mandatory_fields: The mandatory keys to be checked for in
      :py:obj:`adict`, the callable is a validator to check the corresponding
      value in :py:obj:`adict` for conformance. A missing key is an error in
      itself.
    :type optional_fields: {str : callable}
    :param optional_fields: Like :py:obj:`mandatory_fields`, but facultative.
    :type strict: bool
    :param strict: If ``True`` treat the optional fields as mandatory.
    :type allow_superfluous: bool
    :param allow_superfluous: If ``False`` keys which are neither in
      :py:obj:`mandatory_fields` nor in :py:obj:`optional_fields` are errors.
    :type _convert: bool
    :param _convert: If ``True`` do type conversions.
    """
    optional_fields = optional_fields or {}
    if strict:
        mandatory_fields = copy.deepcopy(mandatory_fields)
        mandatory_fields.update(optional_fields)
        optional_fields = {}
    errs = []
    retval = {}
    mandatory_fields_found = []
    for key, value in adict.items():
        if key in mandatory_fields:
            mandatory_fields_found.append(key)
            v, e = mandatory_fields[key](value, argname=key, _convert=_convert)
            errs.extend(e)
            retval[key] = v
        elif key in optional_fields:
            v, e = optional_fields[key](value, argname=key, _convert=_convert)
            errs.extend(e)
            retval[key] = v
        elif not allow_superfluous:
            errs.append((key, KeyError("Superfluous key found.")))
    if len(mandatory_fields) != len(mandatory_fields_found):
        missing = set(mandatory_fields) - set(mandatory_fields_found)
        for key in missing:
            errs.append((key, KeyError("Mandatory key missing.")))
    return retval, errs

##
## Below is the real stuff
##

@_addvalidator
def _int(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
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
def _str_type(val, argname=None, *, strip=False, zap='', sieve='',
              _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strip: bool
    :param strip: Mangle with :py:func:`str.strip`.
    :type zap: str
    :param zap: delete all characters in this from the result
    :type sieve: str
    :param sieve: allow only the characters in this into the result
    """
    if _convert and val is not None:
        try:
            val = str(val)
        except (ValueError, TypeError) as e:
            return None, [(argname, e)]
    if not isinstance(val, str):
        return None, [(argname, TypeError("Must be a string."))]
    if strip:
        val = val.strip()
    if zap:
        val = val.translate(str.maketrans("", "", zap))
    if sieve:
        val = ''.join(c for c in val if c in sieve)
    return val, []


@_addvalidator
def _str(val, argname=None, *, strip=False, zap='', sieve='',
         _convert=True):
    """ Like :py:class:`_str_type` (parameters see there), but mustn't be
    empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strip: bool
    :type zap: str
    :type sieve: str
    """
    val, errs = _str_type(val, argname, strip=strip, zap=zap, sieve=sieve,
                          _convert=_convert)
    if val is not None and not val.strip():
        errs.append((argname, ValueError("Mustn't be empty.")))
    return val, errs

@_addvalidator
def _dict(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :param _convert: is ignored since no useful default conversion is available
    """
    if not isinstance(val, dict):
        return None, [(argname, TypeError("Must be a dict."))]
    return val, []

@_addvalidator
def _bool(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
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

_PRINTABLE_ASCII = re.compile('^[ -~]*$')
@_addvalidator
def _printable_ascii_type(val, argname=None, *, strip=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strip: bool
    :param strip: Mangle with :py:func:`str.strip`.
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _str_type(val, argname, strip=strip, _convert=_convert)
    if not errs and not _PRINTABLE_ASCII.search(val):
        errs.append((argname, ValueError("Must be printable ASCII.")))
    return val, errs

@_addvalidator
def _printable_ascii(val, argname=None, *, strip=False, _convert=True):
    """Like :py:func:`_printable_ascii_type` (parameters see there), but
    mustn't be empty (whitespace doesn't count).

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strip: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii_type(val, argname, strip=strip, _convert=_convert)
    if val is not None and not val.strip():
        errs.append((argname, ValueError("Mustn't be empty.")))
    return val, errs

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
    val, errs = _printable_ascii(val, argname, strip=True, _convert=_convert)
    if errs:
        return None, errs
    ## normalize email addresses to lower case
    val = val.lower()
    if not _EMAIL_REGEX.search(val):
        errs.append((argname, ValueError("Must be a valid email address.")))
    return val, errs

_PERSONA_MANDATORY_FIELDS = {'id' : _int}
_PERSONA_OPTIONAL_FIELDS = {
    'username' : _email,
    'display_name' : _str,
    'is_active' : _bool,
    'status' : _int,
    'db_privileges' : _int,
    'cloud_account' : _bool,
}
@_addvalidator
def _persona_data(val, argname=None, *, strict=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strict: bool
    :param strict: If ``True`` allow only complete data sets.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "persona_data"
    val, errs = _dict(val, argname, _convert=_convert)
    if errs:
        return val, errs
    return _examine_dictionary_fields(
        val, _PERSONA_MANDATORY_FIELDS, _PERSONA_OPTIONAL_FIELDS,
        strict=strict, _convert=_convert)

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
    val1 = dateutil.parser.parse(val.strip(), dayfirst=True,
                                 default=default1).date()
    val2 = dateutil.parser.parse(val.strip(), dayfirst=True,
                                 default=default2).date()
    if val1.year == 1 and val2.year == 2:
        raise ValueError("Year missing.")
    if val1.month == 1 and val2.month == 2:
        raise ValueError("Month missing.")
    if val1.day == 1 and val2.day == 2:
        raise ValueError("Day missing.")
    return dateutil.parser.parse(val.strip(), dayfirst=True).date()

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
    val1 = dateutil.parser.parse(val.strip(), dayfirst=True, default=default1)
    val2 = dateutil.parser.parse(val.strip(), dayfirst=True, default=default2)
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
        dd = datetime.datetime.now(pytz.utc)
    default = datetime.datetime(dd.year, dd.month, dd.day)
    ret = dateutil.parser.parse(val.strip(), dayfirst=True, default=default)
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
def _phone(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (str or None, [(str or None, exception)])
    """
    val, errs = _printable_ascii(val, argname, strip=True, _convert=_convert)
    if errs:
        return val, errs
    orig = val
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
    val, errs = _printable_ascii(val, argname, strip=True, _convert=_convert)
    if val not in GERMAN_POSTAL_CODES:
        errs.append((argname, ValueError("Invalid german postal code.")))
    return val, errs

@_addvalidator
def _member_data(val, argname=None, *, strict=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strict: bool
    :param strict: If ``True`` allow only complete data sets.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "member_data"
    val, errs = _dict(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _PERSONA_MANDATORY_FIELDS
    optional_fields = dict(chain(_PERSONA_OPTIONAL_FIELDS.items(), {
        'family_name' : _str,
        'given_names' : _str,
        'title' : _str_or_None,
        'name_supplement' : _str_or_None,
        'gender' : _int,
        'birthday' : _date,
        'telephone' : _phone_or_None,
        'mobile' : _phone_or_None,
        'address_supplement' : _str_or_None,
        'address' : _str_or_None,
        'postal_code' : _printable_ascii_or_None,
        'location' : _str_or_None,
        'country' : _str_or_None,
        'notes' : _str_or_None,
        'birth_name' : _str_or_None,
        'address_supplement2' : _str_or_None,
        'address2' : _str_or_None,
        'postal_code2' : _printable_ascii_or_None,
        'location2' : _str_or_None,
        'country2' : _str_or_None,
        'weblink' : _str_or_None,
        'specialisation' : _str_or_None,
        'affiliation' : _str_or_None,
        'timeline' : _str_or_None,
        'interests' : _str_or_None,
        'free_form' : _str_or_None,
        'balance' : _decimal,
        'decided_search' : _bool,
        'trial_member' : _bool,
        'bub_search' : _bool,
    }.items()))
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, strict=strict,
        _convert=_convert)
    if errs:
        return val, errs
    for suffix in ("", "2"):
        ## Only validate if keys are present to allow partial data. However
        ## we require a complete address to be submitted, otherwise the
        ## validation may be tricked.
        if any(val.get(key + suffix) for key in \
               ('address_supplement', 'address', 'postal_code', 'location',
                'country')):
            if not val.get('country' + suffix) \
              or val.get('country' + suffix) == "Deutschland":
                for key in ('address', 'postal_code', 'location'):
                    if not val.get(key + suffix):
                        errs.append((key+suffix, ValueError("Missing entry.")))
                if val.get('postal_code' + suffix):
                    postal_code, e = _german_postal_code(
                        val['postal_code' + suffix], 'postal_code' + suffix,
                        _convert=_convert)
                    val['postal_code' + suffix] = postal_code
                    errs.extend(e)
            else:
                for key in ('address', 'location'):
                    if not val.get(key + suffix):
                        errs.append((key+suffix, ValueError("Missing entry.")))
    return val, errs

@_addvalidator
def _event_user_data(val, argname=None, *, strict=False, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :type strict: bool
    :param strict: If ``True`` allow only complete data sets.
    :rtype: (dict or None, [(str or None, exception)])
    """
    argname = argname or "event_user_data"
    val, errs = _dict(val, argname, _convert=_convert)
    if errs:
        return val, errs
    mandatory_fields = _PERSONA_MANDATORY_FIELDS
    optional_fields = dict(chain(_PERSONA_OPTIONAL_FIELDS.items(), {
        'family_name' : _str,
        'given_names' : _str,
        'title' : _str_or_None,
        'name_supplement' : _str_or_None,
        'gender' : _int,
        'birthday' : _date,
        'telephone' : _phone_or_None,
        'mobile' : _phone_or_None,
        'address_supplement' : _str_or_None,
        'address' : _str_or_None,
        'postal_code' : _printable_ascii_or_None,
        'location' : _str_or_None,
        'country' : _str_or_None,
        'notes' : _str_or_None,
    }.items()))
    val, errs = _examine_dictionary_fields(
        val, mandatory_fields, optional_fields, strict=strict,
        _convert=_convert)
    if errs:
        return val, errs
    if any(val.get(key) for key in ('address_supplement', 'address',
                                    'postal_code', 'location', 'country')):
        if not val.get('country') or val.get('country') == "Deutschland":
            for key in ('address', 'postal_code', 'location'):
                if not val.get(key):
                    errs.append((key, ValueError("Missing entry.")))
            if val.get('postal_code'):
                postal_code, e = _german_postal_code(
                    val['postal_code'], 'postal_code', _convert=_convert)
                val['postal_code'] = postal_code
                errs.extend(e)
        else:
            for key in ('address', 'location'):
                if not val.get(key):
                    errs.append((key, ValueError("Missing entry.")))
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
        errs.append((argname, "Too small."))
    if len(blob) > 100000:
        errs.append((argname, "Too big."))
    mime = magic.from_buffer(blob, mime=True)
    mime = mime.decode() ## python-magic is naughty and returns bytes
    if mime not in ("image/jgp", "image/png"):
        errs.append((argname, "Only jpg and png allowed."))
    if errs:
        return None, errs
    image = PIL.Image.open(io.BytesIO(blob))
    width, height = image.size
    if width / height < 0.9 or height / width < 0.9:
        errs.append((argname, "Not square enough."))
    if width * height < 5000:
        errs.append((argname, "Resolution too small."))
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
    """Identifiers encompass everything from file names over sql column
    names to short names for events.

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
        errs.append((argname, e))
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
    val, errs = _dict(val, argname, _convert=_convert)
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
        operator, e = _query_operator_or_None(val.get("qop_{}".format(field)),
                                              field, _convert=_convert)
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
        if value:
            if value in fields_of_interest:
                order.append(value)
            else:
                errs.append(("qord_" + postfix, KeyError("Must be selected.")))
    if errs:
        return None, errs
    return Query(None, spec, fields_of_interest, constraints, order), errs

@_addvalidator
def _query_operator(val, argname=None, *, _convert=True):
    """
    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`cdedb.query.QueryOperators` or None,
        [(str or None, exception)])
    """
    val, errs = _int(val, argname, _convert=_convert)
    if errs:
        return val, errs
    try:
        val = QueryOperators(val)
    except ValueError as e:
        errs.append((argname, e))
        return None, errs
    return val, errs

@_addvalidator
def _serialized_query(val, argname=None, *, _convert=True):
    """This is for the queries from frontend to backend.

    :type val: object
    :type argname: str or None
    :type _convert: bool
    :rtype: (:py:class:`cdedb.query.Query` or None, [(str or None, exception)])
    """
    val, errs = _dict(val, argname, _convert=_convert)
    if errs:
        return val, errs
    if set(val) != {"scope", "spec", "fields_of_interest", "constraints",
                    "order"}:
        return None, [(argname, ValueError("Wrong keys."))]
    ## scope
    scope, e = _identifier(val['scope'], "scope", _convert=_convert)
    errs.extend(e)
    if not scope.startswith("qview_"):
        errs.append(("scope", ValueError("Must start with 'qview_'.")))
    ## spec
    spec_val, e = _dict(val['spec'], "spec", _convert=_convert)
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
    if not isinstance(val['fields_of_interest'], collections.abc.Iterable):
        errs.append(("fields_of_interest", TypeError("Must be iterable.")))
    else:
        for field in val['fields_of_interest']:
            field, e = _csv_identifier(field, "fields_of_interest", _convert=_convert)
            fields_of_interest.append(field)
            errs.extend(e)
    if not fields_of_interest:
        errs.append(("fields_of_interest", ValueError("Mustn't be empty.")))
    ## constraints
    constraints = []
    if not isinstance(val['constraints'], collections.abc.Iterable):
        errs.append(("constraints", TypeError("Must be iterable.")))
    else:
        for x in val['constraints']:
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
            operator, e = _int(operator, "constraints/{}".format(field),
                               _convert=_convert)
            errs.extend(e)
            try:
                operator = QueryOperators(operator)
            except ValueError as e:
                errs.append(("constraints", e))
                continue
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
    if not isinstance(val['order'], collections.abc.Iterable):
        errs.append(("order", TypeError("Must be iterable.")))
    else:
        for field in val['order']:
            field, e = _csv_identifier(field, "order", _convert=_convert)
            order.append(field)
            errs.extend(e)
    if errs:
        return None, errs
    else:
        return Query(scope, spec, fields_of_interest, constraints, order), errs

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
            raise errs[0][1]
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
