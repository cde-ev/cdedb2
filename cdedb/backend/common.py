#!/usr/bin/env python3

"""All the common infrastructure for the backend services.

The most important thing is :py:class:`AbstractBackend` which is the
template for all services.
"""

import os
import signal
import logging
from cdedb.database.connection import connection_pool_factory
from cdedb.database import DATABASE_ROLES
from cdedb.common import (
    glue, extract_realm, make_root_logger, extract_roles,
    ALL_ROLES, DB_ROLE_MAPPING, CommonUser)
from cdedb.query import QueryOperators, QUERY_VIEWS
from cdedb.config import Config, SecretsConfig
import abc
import cdedb.validation as validate
import functools
import copy
import inspect
import collections.abc
import enum

def singularize(singular_function_name, array_param_name="ids",
                singular_param_name="anid"):
    """This decorator marks a function for singularization.

    The function has to accept an array as parameter and return a dict
    indexed by this array. This array has either to be a keyword only
    parameter or the first positional parameter after the request
    state. Singularization creates a function which accepts a single
    element instead and transparently wraps in a list as well as
    unwrapping the returned dict.

    Singularization is performed at the same spot as publishing of the
    functions with @access decorator, that is in
    :py:class:`cdedb.backend.rpc.BackendServer` and
    :py:class:`AuthShim`.

    :type singular_function_name: str
    :param singular_function_name: name for the new singularized function
    :type array_param_name: str
    :type array_param_name: name of the parameter to singularize
    :type singular_param_name: str
    :type singular_param_name: new name of the singularized parameter
    """
    def wrap(fun):
        fun.singularization_hint = {
            'singular_function_name' : singular_function_name,
            'array_param_name' : array_param_name,
            'singular_param_name' : singular_param_name,
        }
        return fun
    return wrap

def do_singularization(fun):
    """Perform singularization on a function.

    This is the companion to the @singularize decorator.
    :type fun: callable
    :param fun: function with ``fun.singularization_hint`` attribute
    :rtype: callable
    :returns: singularized function
    """
    hint = fun.singularization_hint
    @functools.wraps(fun)
    def new_fun(rs, *args, **kwargs):
        if hint['singular_param_name'] in kwargs:
            param = kwargs.pop(hint['singular_param_name'])
            kwargs[hint['array_param_name']] = (param,)
        else:
            param = args[0]
            args = ((param,),) + args[1:]
        data = fun(rs, *args, **kwargs)
        return data[param]
    new_fun.__name__ = hint['singular_function_name']
    return new_fun

def access(role):
    """The @access decorator marks a function of a backend for publication via
    RPC.

    :type role: str
    :param role: required privilege level
    """
    def decorator(fun):
        fun.access_list = ALL_ROLES[role]
        return fun
    return decorator

def internal_access(role):
    """The @internal_access decorator marks a function of a backend for
    internal publication. It will be accessible via the :py:class:`AuthShim`.

    :type role: str
    :param role: required privilege level
    """
    def decorator(fun):
        fun.internal_access_list = ALL_ROLES[role]
        return fun
    return decorator

class BackendRequestState:
    """As the backends should be stateless most functions should as first
    argument accept a request state object.
    """
    def __init__(self, sessionkey, user, conn):
        """
        :type sessionkey: str
        :type user: :py:class:`BackendUser`
        :type conn: :py:class:`cdedb.database.connection.IrradiatedConnection`
        """
        self.sessionkey = sessionkey
        self.user = user
        self.conn = conn

class AbstractBackend(metaclass=abc.ABCMeta):
    """Basic template for all backend services.

    Note the method :py:meth:`establish` which is used by
    :py:mod:`cdedb.backend.rpc` to do authentification. Children classes
    have to override some things: first :py:attr:`realm` identifies the
    component; furthermore there are some abstract methods which specify
    realm-specific behaviour (with a default implementation which is
    sufficient for some cases).
    """
    #: abstract str to be specified by children
    realm = None

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        self.conf = Config(configpath)
        ## initialize logging
        make_root_logger(
            "cdedb.backend", getattr(self.conf, "{}_BACKEND_LOG".format(
                self.realm.upper())), self.conf.LOG_LEVEL,
            syslog_level=self.conf.SYSLOG_LEVEL,
            console_log_level=self.conf.CONSOLE_LOG_LEVEL)
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            SecretsConfig(configpath))
        ## logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.{}".format(self.realm))
        self.logger.info("Instantiated {} with configpath {}.".format(
            self, configpath))

    @abc.abstractmethod
    def establish(self, sessionkey, method, allow_internal=False):
        """Do the initialization for an RPC connection.

        :type sessionkey: str
        :param sessionkey: used for authorization and converted into a
          :py:class:`BackendRequestState`
        :type method: str
        :param method: name of the method to be invoked via RPC
        :type allow_internal: bool
        :param allow_internal: ``True`` for permitting
          @internal_access. This is currently only used for testing.
        :rtype: :py:class:`BackendRequestState` or None
        """
        persona_id = None
        if sessionkey:
            query = glue("SELECT persona_id FROM core.sessions",
                         "WHERE sessionkey = %s AND is_active = True")
            with self.connpool["cdb_anonymous"] as conn:
                with conn.cursor() as cur:
                    self.execute_db_query(cur, query, (sessionkey,))
                    if cur.rowcount == 1:
                        persona_id = cur.fetchone()["persona_id"]
                    else:
                        self.logger.info("Got invalid session key '{}'.".format(
                            sessionkey))
        user = BackendUser()
        if persona_id:
            ## no update to core.sessions(atime) here
            ## these happen only in the frontend and on logout
            ## the backend can generally be less paranoid about sessions
            query = glue("SELECT status, db_privileges, is_active",
                         "FROM core.personas WHERE id = %s")
            with self.connpool["cdb_anonymous"] as conn:
                with conn.cursor() as cur:
                    self.execute_db_query(cur, query, (persona_id,))
                    data = self._sanitize_db_output(cur.fetchone())
            if data["is_active"]:
                realm = extract_realm(data["status"])
                roles = extract_roles(data["db_privileges"], data["status"])
                user = BackendUser(persona_id=persona_id, roles=roles,
                                   realm=realm)
            else:
                self.logger.warning("Found inactive user {}".format(persona_id))
        try:
            access_list = getattr(self, method).access_list
        except AttributeError:
            if allow_internal:
                access_list = getattr(self, method).internal_access_list
            else:
                raise
        if user.roles & access_list:
            ret = BackendRequestState(sessionkey, user,
                                      self.connpool[self.db_role(user.roles)])
            return ret
        else:
            return None

    @staticmethod
    def db_role(roles):
        """Convert a set of application level roles into a database level role.

        :type roles: {str}
        :rtype: str
        """
        for role in DB_ROLE_MAPPING:
            if role in roles:
                return DB_ROLE_MAPPING[role]

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.

        :type rs: :py:class:`BackendRequestState`
        :rtype: bool
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    @staticmethod
    def _sanitize_db_output(output):
        """Convert a :py:class:`psycopg2.extras.RealDictRow` into a normal
        :py:class:`dict`. We only use the outputs as dictionaries and
        the psycopg variant has some rough edges (e.g. it does not survive
        serialization).

        Also this wrapper allows future global modifications to the
        outputs, if we want to add some.

        :type output: :py:class:`psycopg2.extras.RealDictRow`
        :rtype: {str : object}
        """
        if not output:
            return None
        return dict(output)

    @staticmethod
    def _sanitize_db_input(obj):
        """Mangle data to make psycopg happy.

        Convert :py:class:`tuple`s (and all other iterables) into
        :py:class:`list`s. This is necesary because psycopg will fail to
        insert a tuple into an 'ANY(%s)' clause -- only a list does the
        trick.

        Convert :py:class:`enum.IntEnum` (and all other enums) into
        their numeric value. Everywhere else these automagically work
        like integers, but here they have to be handled explicitly.

        :type obj: object
        :rtype: object but not tuple or IntEnum
        """
        if isinstance(obj, collections.abc.Iterable) \
          and not isinstance(obj, str):
            return [AbstractBackend._sanitize_db_input(x) for x in obj]
        elif isinstance(obj, enum.Enum):
            return obj.value
        else:
            return obj

    def execute_db_query(self, cur, query, params):
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`_sanitize_tuple`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.

        :type cur: :py:class:`psycopg2.extensions.cursor`
        :type query: str
        :type params: [object]
        :rtype: None
        """
        sanitized_params = tuple(self._sanitize_db_input(p) for p in params)
        self.logger.debug("Execute PostgreSQL query {}.".format(cur.mogrify(
            query, sanitized_params)))
        cur.execute(query, sanitized_params)

    def query_exec(self, rs, query, params):
        """Execute a query in a safe way (inside a transaction).

        :type rs: :py:class:`BackendRequestState`
        :type query: str
        :type params: [object]
        :rtype: int
        :returns: number of affected rows
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return cur.rowcount

    def query_one(self, rs, query, params):
        """Execute a query in a safe way (inside a transaction).

        :type rs: :py:class:`BackendRequestState`
        :type query: str
        :type params: [object]
        :rtype: {str : object} or None
        :returns: First result of query or None if there is none
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return self._sanitize_db_output(cur.fetchone())

    def query_all(self, rs, query, params):
        """Execute a query in a safe way (inside a transaction).

        :type rs: :py:class:`BackendRequestState`
        :type query: str
        :type params: [object]
        :rtype: [{str : object}]
        :returns: all results of query
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return tuple(
                    self._sanitize_db_output(x) for x in cur.fetchall())

    @staticmethod
    def diacritic_patterns(string):
        """Replace letters with a pattern matching expressions, so that ommitting
        diacritics in the query input is possible.

        This is intended for use with the sql SIMILAR TO clause.

        :type string: str
        :rtype: str
        """
        ## if fragile special chars are present do nothing
        ## all special chars: '_%|*+?{}()[]'
        special_chars = '|*+?{}()[]'
        for char in special_chars:
            if char in string:
                return string
        ## some of the diacritics in use according to wikipedia
        umlaut_map = (
            ("ae", "(ae|[äæ])"),
            ("oe", "(oe|[öøœ])"),
            ("ue", "(ue|ü)"),
            ("ss", "(ss|ß)"),
            ("a", "[aàáâãäåą]"),
            ("c", "[cçčć]"),
            ("e", "[eèéêëę]"),
            ("i", "[iìíîï]"),
            ("l", "[lł]"),
            ("n", "[nñń]"),
            ("o", "[oòóôõöøő]"),
            ("u", "[uùúûüű]"),
            ("y", "[yýÿ]"),
            ("z", "[zźż]"),
        )
        for normal, replacement in umlaut_map:
            string = string.replace(normal, replacement)
        return string

    def general_query(self, rs, query, distinct=True):
        """Perform a DB query described by a :py:class:`cdedb.query.Query`
        object.

        :type rs: :py:class:`BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :type distinct: bool
        :param distinct: whether only unique rows should be returned
        :rtype: [{str : object}]
        :returns: all results of the query
        """
        self.logger.debug("Performing general query {}.".format(query))
        select = ", ".join(column for field in query.fields_of_interest
                           for column in field.split(','))
        q = "SELECT {} {} FROM {}".format("DISTINCT" if distinct else "",
                                          select, QUERY_VIEWS[query.scope])
        params = []
        constraints = []
        for field, operator, value in query.constraints:
            lowercase = (query.spec[field] == "str")
            if lowercase:
                ## the following should be used with operators which are allowed
                ## for str as well as for other types
                sql_param_str = "lower({})"
                caser = lambda x: x.lower()
            else:
                sql_param_str = "{}"
                caser = lambda x: x
            columns = field.split(',')
            if operator == QueryOperators.empty:
                phrase = "( {0} IS NULL OR {0} = '' )"
            elif operator == QueryOperators.nonempty:
                phrase = "( {0} IS NOT NULL AND {0} <> '' )"
            elif operator == QueryOperators.equal:
                phrase = "{} = %s".format(sql_param_str)
                params.extend((caser(value),)*len(columns))
            elif operator == QueryOperators.oneof:
                phrase = "{} = ANY(%s)".format(sql_param_str)
                params.extend((tuple(caser(x) for x in value),)*len(columns))
            elif operator == QueryOperators.similar:
                phrase = "lower({}) SIMILAR TO %s"
                value = "%{}%".format(self.diacritic_patterns(value.lower()))
                params.extend((value,)*len(columns))
            elif operator == QueryOperators.regex:
                phrase = "{} ~* %s"
                params.extend((value,)*len(columns))
            elif operator == QueryOperators.containsall:
                values = tuple("%{}%".format(self.diacritic_patterns(x.lower()))
                               for x in value)
                subphrase = "lower({0}) SIMILAR TO %s"
                phrase = "( {} )".format(" ) AND ( ".join(
                    subphrase for _ in range(len(values))))
                params.extend(values*len(columns))
            elif operator == QueryOperators.less:
                phrase = "{} < %s"
                params.extend((value,)*len(columns))
            elif operator == QueryOperators.lessequal:
                phrase = "{} <= %s"
                params.extend((value,)*len(columns))
            elif operator == QueryOperators.between:
                phrase = "(%s <= {0} AND {0} <= %s)"
                params.extend((value[0], value[1])*len(columns))
            elif operator == QueryOperators.greaterequal:
                phrase = "{} >= %s"
                params.extend((value,)*len(columns))
            elif operator == QueryOperators.greater:
                phrase = "{} > %s"
                params.extend((value,)*len(columns))
            else:
                raise RuntimeError("Impossible.")
            constraints.append(" OR ".join(phrase.format(c) for c in columns))
        if constraints:
            q = glue(q, "WHERE", "({})".format(" ) AND ( ".join(constraints)))
        if query.order:
            q = glue(q, "ORDER BY",
                     ", ".join(entry.split(',')[0] for entry in query.order))
        return self.query_all(rs, q, params)

class BackendUser(CommonUser):
    """Container for a persona in the backend."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

def affirm_validation(assertion, value):
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    :type assertion: str
    :type value: object
    :rtype: object
    """
    checker = getattr(validate, "assert_{}".format(assertion))
    return checker(value)

def affirm_array_validation(assertion, values):
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for an array.

    :type assertion: str
    :type values: [object]
    :rtype: [object]
    """
    checker = getattr(validate, "assert_{}".format(assertion))
    return tuple(checker(value) for value in values)

def make_RPCDaemon(backend, socket_address, access_log=None):
    """Wrapper around :py:func:`cdedb.backend.rpc.create_RPCDaemon` which is
    necessary to set up the environment for :py:mod:`Pyro4` before it is
    imported.

    :type backend: :py:class:`AbstractBackend`
    :type socket_address: str
    :type access_log: str or None
    :rtype: :py:class:`Pyro4.core.Daemon`
    """
    if access_log:
        os.environ['PYRO_LOGFILE'] = access_log
        if backend.conf.LOG_LEVEL <= logging.DEBUG:
            os.environ['PYRO_LOGLEVEL'] = "DEBUG"
        else:
            os.environ['PYRO_LOGLEVEL'] = "INFO"
    from cdedb.backend.rpc import create_RPCDaemon
    return create_RPCDaemon(backend, socket_address, bool(access_log))

def run_RPCDaemon(daemon, pidfile=None):
    """Helper to run :py:meth:`Pyro4.core.Daemon.requestLoop`. This provides a
    handler for doing a clean shutdown on SIGTERM and creates a state file
    to get the server pid.

    :type daemon: :py:class:`Pyro4.core.Daemon`
    :type pidfile: str or None
    """
    running = [True]
    def handler(signum, frame): ## signature because of interface compatability
        if running:
            running.pop()
    signal.signal(signal.SIGTERM, handler)
    if pidfile:
        with open(pidfile, 'w') as f:
            f.write(str(os.getpid()))
    try:
        with daemon:
            daemon.requestLoop(lambda: running)
    finally:
        if pidfile:
            os.remove(pidfile)

class AuthShim:
    """Mediate calls between different backend components. This emulates an
    RPC call without most of the overhead of actually doing an RPC call.
    """
    def __init__(self, backend):
        """
        :type backend: :py:class:`AbstractBackend`
        """
        self._backend = backend
        self._funs = {}
        funs = inspect.getmembers(backend, predicate=inspect.isroutine)
        for name, fun in funs:
            if hasattr(fun, "access_list") or hasattr(fun,
                                                      "internal_access_list"):
                self._funs[name] = self._wrapit(fun)
                if hasattr(fun, "singularization_hint"):
                    hint = fun.singularization_hint
                    self._funs[hint['singular_function_name']] = self._wrapit(
                        do_singularization(fun))
                    setattr(backend, hint['singular_function_name'],
                            do_singularization(fun))

    def _wrapit(self, fun):
        """
        :type fun: callable
        """
        try:
            access_list = fun.internal_access_list
        except AttributeError:
            access_list = fun.access_list
        @functools.wraps(fun)
        def new_fun(rs, *args, **kwargs):
            if rs.user.roles & access_list:
                return fun(rs, *args, **kwargs)
            else:
                raise RuntimeError("Permission denied")
        return new_fun

    def __getattr__(self, name):
        if name in {"_funs", "_backend"}:
            raise AttributeError()
        try:
            return self._funs[name]
        except KeyError as e:
            raise AttributeError from e

def create_fulltext(data):
    """Helper to mangle data all data into a single string.

    :type data: {str : object}
    :param data: one member data set to convert into a string for fulltext
      search
    :rtype: str
    """
    attrs = (
        "username", "title", "given_names", "display_name",
        "family_name", "birth_name", "name_supplement", "birthday",
        "telephone", "mobile", "address", "address_supplement",
        "postal_code", "location", "country", "address2",
        "address_supplement2", "postal_code2", "location2", "country2",
        "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form")
    def _sanitize(val):
        if val is None:
            return ""
        else:
            return str(val)
    vals = (_sanitize(data[x]) for x in attrs)
    return " ".join(vals)
