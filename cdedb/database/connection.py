#!/usr/bin/env python3

"""This module provides our python interface to the database.

Note the class :py:class:`Atomizer` which takes care of creating atomic
contexts for database transactions across arbitrary backend logic.

This should be the only module which makes subsistantial use of psycopg.
"""

import logging

import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
from psycopg2.extensions import ISOLATION_LEVEL_SERIALIZABLE as SERIALIZABLE

from cdedb.config import BasicConfig
_BASICCONF = BasicConfig()

_LOGGER = logging.getLogger(__name__)

def _create_connection(dbname, dbuser, password, port,
                       isolation_level=SERIALIZABLE):
    """This creates a wrapper around :py:class:`psycopg2.extensions.connection`
    and correctly initializes the database connection.

    :type dbname: str
    :type dbuser: str
    :type password: str
    :type port: int
    :param isolation_level: Isolation level of database connection, a
        constant coming from :py:mod:`psycopg2.extensions`. This should be used
        very sparingly!
    :type isolation_level: int
    :rtype: :py:class:`IrradiatedConnection`
    :returns: open database connection
    """
    conn = psycopg2.connect(
        "dbname={} user={} password={} port={}".format(
            dbname, dbuser, password, port),
        connection_factory=IrradiatedConnection,
        cursor_factory=psycopg2.extras.RealDictCursor)
    conn.set_client_encoding("UTF8")
    conn.set_session(isolation_level)
    _LOGGER.debug("Created connection to {} as {}".format(dbname, dbuser))
    return conn

def connection_pool_factory(dbname, roles, secrets,
                            isolation_level=SERIALIZABLE):
    """This returns a dict-like object which has database roles as keys and
    database connections as values (which are created on the fly).

    Database connections are a costly good (in memory terms), so it is
    wise to create them only when necessary. Since this is costly in
    itself (in time terms) it is advisable to use connection pooling
    (e.g. pgbouncer). Additionally this approach offers thread-safety
    since connetions created at runtime are not shared between threads.

    The first implementation of this interface was a caching connection
    factory, which used crazy amounts of resources.

    :type dbname: str
    :param roles: roles for which database connections shall be available
    :type roles: [str]
    :param secrets: container for db passwords
    :type secrets: :py:class:`cdedb.config.SecretsConfig`
    :param isolation_level: Isolation level of database connection, a
        constant coming from :py:mod:`psycopg2.extensions`. This should be used
        very sparingly!
    :type isolation_level: int
    :returns: dict-like object with semantics {str :
                :py:class:`IrradiatedConnection`}
    """
    class InstantConnectionPool:
        """Dict-like for providing database connections."""
        def __init__(self, roles):
            self.roles = roles

        def __getitem__(self, role):
            if not role in self.roles:
                raise ValueError("role {} not available".format(role))
            return _create_connection(
                dbname, role, secrets.CDB_DATABASE_ROLES[role],
                _BASICCONF.DB_PORT, isolation_level)

        def __delitem__(self, key):
            raise NotImplementedError("Not available for instant pool")

        def __len__(self):
            raise NotImplementedError("Not available for instant pool")

        def __setitem__(self, key, val):
            raise NotImplementedError("Not available for instant pool")

    _LOGGER.info("Initialised instant connection pool for roles {}".format(
        roles))
    return InstantConnectionPool(roles)

class Atomizer:
    """Helper to create atomic transactions.

    The backend stores the database connection in the
    :py:attr:`cdedb.common.RequestState.conn` attribute. This
    connection is then used for all queries in this request, utilizing
    ``with`` contexts to control transactions. However if several of
    these contexts are nested for the same connection, the (regular)
    termination of the innermost context will commit the
    transaction. This is surprising for the outer contexts which then do
    not work as intended.

    To mitigate this problem this class can be used. The pattern is as
    follows::

        with Atomizer(rs) as conn:
            with conn.cursor as cur():
                ## do stuff with nested contexts

    Every database connection is of type
    :py:class:`IrradiatedConnection` (a child of
    :py:class:`psycopg2.extensions.connection`) which keeps track of the
    nested contexts and only commits the transaction once the outermost
    context is left. This does not pose a problem for the inner contexts
    since their actions are still atomic.

    For the error case we must be careful not to catch exceptions in
    between nested contexts, otherwise we may miss to trigger a
    transaction rollback. This is in line with failing loudly if
    something goes wrong. We detect suppressed exceptions and complain
    about them, however they are still a bad idea.
    """
    def __init__(self, rs):
        """
        :type rs: :py:class:`cdedb.common.RequestState`
        """
        self.rs = rs

    def __enter__(self):
        self.rs._conn.contaminate()
        return self.rs._conn.__enter__()

    def __exit__(self, atype, value, tb):
        self.rs._conn.decontaminate()
        return self.rs._conn.__exit__(atype, value, tb)

class IrradiatedConnection(psycopg2.extensions.connection):
    """Minimally modified version of :py:class:`psycopg2.extensions.connection`
    to facilitate :py:class:`Atomizer`.

    This is a context object which can be used with the ``with``
    statement as it is derived from
    :py:class:`psycopg2.extensions.connection`.

    See :py:class:`Atomizer` for the documentation.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._radiation_level = 0
        ## keep a copy of any exception we encounter
        self._saved_etype = None
        self._saved_evalue = None
        self._saved_tb = None

    def __enter__(self):
        if self._radiation_level:
            return self
        else:
            if self.status != psycopg2.extensions.STATUS_READY:
                raise RuntimeError("Connection in use!")
            ## clear saved exception
            self._saved_etype = None
            self._saved_evalue = None
            self._saved_tb = None
            return super().__enter__()

    def __exit__(self, etype, evalue, tb):
        if self._radiation_level:
            ## grab any exception
            self._saved_etype = etype or self._saved_etype
            self._saved_evalue = evalue or self._saved_evalue
            self._saved_tb = tb or self._saved_tb
            return None
        else:
            if not etype and self._saved_etype:
                ## we encountered an exception but it was suppressed
                ## somewhere -- this is bad, because it breaks the
                ## with-contexts.

                ## first we rollback the transaction
                super().__exit__(self._saved_etype, self._saved_evalue,
                                 self._saved_tb)
                ## second we raise an exception to complain
                raise RuntimeError("Suppressed exception detected")
            return super().__exit__(etype, evalue, tb)

    def contaminate(self):
        """Increase recursion by one."""
        self._radiation_level += 1

    def decontaminate(self):
        """Reduce recursion by one."""
        if self._radiation_level <= 0:
            raise RuntimeError("No contamination!")
        self._radiation_level -= 1

    @property
    def is_contaminated(self):
        """Test for usage af an Atomizer higher up the in the stack.

        :rtype: bool
        """
        return bool(self._radiation_level)
