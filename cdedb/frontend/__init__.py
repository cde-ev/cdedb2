#!/usr/bin/env python3

"""The frontend is a WSGI-application split into several components (along
the realms). The database interaction via the backends is negotiated
through :py:mod:`Pyro4` RPC calls. The bigger part of the logic will be
contained in here.

All output formatting should be handled by the :py:mod:`jinja2` templates.
"""
from cdedb.common import QuotaException, PrivilegeError
from cdedb.serialization import SERIALIZERS
import Pyro4.util
import psycopg2
import psycopg2.extensions
import serpent

## We register some custom exception classes so that they are handled
## correctly by pyro.

custom_exceptions = {
    "cdedb.common.QuotaException": QuotaException,
    "cdedb.common.PrivilegeError": PrivilegeError,
    "psycopg2.extensions.TransactionRollbackError":
        psycopg2.extensions.TransactionRollbackError,
    "psycopg2.ProgrammingError": psycopg2.ProgrammingError,
}

Pyro4.util.all_exceptions.update(custom_exceptions)

## pyro uses serpent as serializers and we want some additional comfort so
## we register some additional serializers, they are reversed in
## cdedb.validation
##
## This is for frontend -> backend.
for clazz in SERIALIZERS:
    serpent.register_class(clazz, SERIALIZERS[clazz])
