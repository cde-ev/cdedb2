"""
Small validation library.

Validate Python-data-structures, especially dicts loaded from JSON.
Mainly written for simple_mailinglist.

Validation-schemas can be:

    - TYPE
    - (TYPE, SPEC...)
    - a list of alternative schemas

    TYPE:

    - a Python-type (e.g. str, int, float, bool, list, ...)
    - "FILE"
    - "DIR"
    - "EMAIL"
    - "<EMAIL>": email-address or "NAME <EMAIL>"
    - "URL"

    SPEC:

    - for Python-types:

      - min, max: min. and max. value, None=ignore
      - a list:   a list of alternative values
      - a schema: schema for each list-entry (only for type list)

    - for "FILE", "DIR": access-rights (os.R_OK, os.W_OK, os.X_OK, ...)

:Version:   0.1

:Requires:  Python >= 2.7 / 3.2 (TODO: check)

:Author:    Roland Koebler <rk@simple-is-better.org>
:Copyright: Roland Koebler
:License:   MIT/X11-like, see module-__license__

:VCS:       $Id$
"""
from __future__ import unicode_literals

import os

R_OK = os.R_OK
W_OK = os.W_OK
X_OK = os.X_OK
RW_OK = os.R_OK | os.W_OK
RX_OK = os.R_OK | os.X_OK
RWX_OK = os.R_OK | os.W_OK | os.X_OK

#=========================================

def validate_value(value, schema):
    """Validate a value according to a schema/format-definition.

    :Parameters:
        - value:  value to check
        - schema: value-format-definition / value-schema
    :Raises:
        ValueError if validation fails,
        IOError if files/directories cannot be accessed
    """
    # alternative schemas
    if isinstance(schema, list):
        errors = []
        for s in schema:
            try:
                validate_value(value, s)
                return
            except ValueError as err:
                errors.append(err)
        raise ValueError("must be one of: %s" % " / ".join(errors))

    # split into type + detailed spec
    if isinstance(schema, tuple):
        type_ = schema[0]
        spec = schema[1:]
    else:
        type_ = schema
        spec = None

    # check value
    if isinstance(type_, type):
        if not isinstance(value, type_):
            raise ValueError('must be a %s' % type_.__name__)
        if spec:
            # min, max
            if len(spec) == 2:
                if spec[0] is not None  and  value < spec[0]:
                    raise ValueError("must be >= %s" % spec[0])
                if spec[1] is not None  and  value > spec[1]:
                    raise ValueError("must be <= %s" % spec[1])
            # one of several defined values
            if isinstance(spec[0], (list, tuple)):
                if value not in spec[0]:
                    raise ValueError("must be one of %s" % ",".join(spec[0]))
        if type_ == list:
            for e in value:
                validate_value(e, spec)

    elif type_ == "FILE":
        if not isinstance(value, str):
            raise ValueError("must be a string.")
        if not os.path.exists(value):
            raise IOError("'%s' does not exist." % value)
        if not os.path.isfile(value):
            raise IOError("'%s' must be a file." % value)
        if spec:
            if not os.access(value, spec):
                raise IOError("'%s': permission denied." % value)

    elif type_ == "DIR":
        if not isinstance(value, str):
            raise ValueError("must be a string.")
        if not os.path.exists(value):
            raise IOError("'%s' does not exist." % value)
        if not os.path.isdir(value):
            raise IOError("'%s' must be a directory." % value)
        if spec:
            if not os.access(value, spec[0]):
                raise IOError("'%s': permission denied." % value)

    elif type_ == "EMAIL":
        if not isinstance(value, str):
            raise ValueError("must be a string.")
        # TODO
    elif type_ == "URL":
        if not isinstance(value, str):
            raise ValueError("must be a string.")
        # TODO

#-----------------------------------------

def validate_dict(d, schema):
    """Validate a dictionary.

    :Parameters:
        - d:      dictionary to check
        - schema: dictionary-format-definition ({KEY: schema, ...})
    :Raises:
        ValueError("key: ERRORMESSAGE") if the validation fails,
        IOError if files/directories cannot be accessed
    """
    for k in d:
        if k in schema:
            try:
                validate_value(d[k], schema[k])
            except ValueError as err:
                raise ValueError("%s: %s" % (k, err))
            except IOError as err:
                raise IOError("%s: %s" % (k, err))

#=========================================
