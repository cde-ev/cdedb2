#!/usr/bin/env python3

"""All the common infrastructure for the backend services.

The most important thing is :py:class:`AbstractBackend` which is the
template for all services.
"""

import abc
import collections.abc
import enum
import logging

from cdedb.common import (
    glue, make_root_logger, ProxyShim, unwrap)
from cdedb.query import QueryOperators, QUERY_VIEWS
from cdedb.config import Config
import cdedb.validation as validate

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
    :py:class:`cdedb.common.ProxyShim`.

    :type singular_function_name: str
    :param singular_function_name: name for the new singularized function
    :type array_param_name: str
    :type array_param_name: name of the parameter to singularize
    :type singular_param_name: str
    :type singular_param_name: new name of the singularized parameter
    """
    def wrap(fun):
        fun.singularization_hint = {
            'singular_function_name': singular_function_name,
            'array_param_name': array_param_name,
            'singular_param_name': singular_param_name,
        }
        return fun
    return wrap

def batchify(batch_function_name, array_param_name="data",
             singular_param_name="data"):
    """This decorator marks a function for batchification.

    The function has to accept an a singular parameter. The singular
    parameter has either to be a keyword only parameter or the first
    positional parameter after the request state. Batchification creates a
    function which accepts an array instead and loops over this array
    wrapping everything in a database transaction. It returns an array of
    all return values.

    Batchification is performed at the same spot as publishing of the
    functions with @access decorator, that is in
    :py:class:`cdedb.common.ProxyShim`.

    :type batch_function_name: str
    :param batch_function_name: name for the new batchified function
    :type array_param_name: str
    :type array_param_name: new name of the batchified parameter
    :type singular_param_name: str
    :type singular_param_name: name of the parameter to batchify
    """
    def wrap(fun):
        fun.batchification_hint = {
            'batch_function_name': batch_function_name,
            'array_param_name': array_param_name,
            'singular_param_name': singular_param_name,
        }
        return fun
    return wrap

def access(*roles):
    """The @access decorator marks a function of a backend for publication.

    Think of this as an RPC interface, only published functions are
    accessible (and only by users with the necessary roles).

    :type roles: [str]
    :param roles: required privilege level (any of)
    """
    def decorator(fun):
        fun.access_list = set(roles)
        return fun
    return decorator

def internal_access(*roles):
    """Mark a function of a backend for internal publication.

    It will be accessible via the :py:class:`cdedb.common.ProxyShim` in
    internal mode.

    :type roles: [str]
    :param roles: required privilege level (any of)
    """
    def decorator(fun):
        fun.internal_access_list = set(roles)
        return fun
    return decorator

class AbstractBackend(metaclass=abc.ABCMeta):
    """Basic template for all backend services.

    Children classes have to override some things: first :py:attr:`realm`
    identifies the component; furthermore there are some abstract methods
    which specify realm-specific behaviour (with a default implementation
    which is sufficient for some cases).
    """
    #: abstract str to be specified by children
    realm = None

    def __init__(self, configpath, is_core=False):
        """
        :type configpath: str
        :type is_core: bool
        :param is_core: If not, we add instantiate a core backend for usage
          by this backend.
        """
        self.conf = Config(configpath)
        ## initialize logging
        make_root_logger(
            "cdedb.backend", getattr(self.conf, "{}_BACKEND_LOG".format(
                self.realm.upper())), self.conf.LOG_LEVEL,
            syslog_level=self.conf.SYSLOG_LEVEL,
            console_log_level=self.conf.CONSOLE_LOG_LEVEL)
        ## logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.{}".format(self.realm))
        self.logger.info("Instantiated {} with configpath {}.".format(
            self, configpath))
        ## Everybody needs access to the core backend
        if is_core:
            self.core = self
        else:
            ## Import here since we otherwise have a cyclic import.
            ## I don't see how we can get out of this ...
            from cdedb.backend.core import CoreBackend
            self.core = ProxyShim(CoreBackend(configpath), internal=True)

    def affirm_realm(self, rs, ids, realms=None):
        """Check that all personas corresponding to the ids are in the
        appropriate realm.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :type realms: {str}
        :param realms: Set of realms to check for. By default this is
          the set containing only the realm of this class.
        """
        realms = realms or {self.realm}
        actual_realms = self.core.get_realms_multi(rs, ids)
        if any(not x >= realms for x in actual_realms.values()):
            raise ValueError("Wrong realm for personas.")
        return

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """We abstract away the admin privilege.

        Maybe this can be beefed up to check for orgas and moderators too,
        but for now it only checks the admin role.

        :type rs: :py:class:`BackendRequestState`
        :rtype: bool
        """
        return bool({"{}_admin".format(cls.realm), "admin"} & rs.user.roles)

    @staticmethod
    def _sanitize_db_output(output):
        """Convert a :py:class:`psycopg2.extras.RealDictRow` into a normal
        :py:class:`dict`. We only use the outputs as dictionaries and
        the psycopg variant has some rough edges (e.g. it does not survive
        serialization).

        Also this wrapper allows future global modifications to the
        outputs, if we want to add some.

        :type output: :py:class:`psycopg2.extras.RealDictRow`
        :rtype: {str: object}
        """
        if not output:
            return None
        return dict(output)

    @staticmethod
    def _sanitize_db_input(obj):
        """Mangle data to make psycopg happy.

        Convert :py:class:`tuple`s (and all other iterables, but not strings
        or mappings) into :py:class:`list`s. This is necesary because
        psycopg will fail to insert a tuple into an 'ANY(%s)' clause -- only
        a list does the trick.

        Convert :py:class:`enum.IntEnum` (and all other enums) into
        their numeric value. Everywhere else these automagically work
        like integers, but here they have to be handled explicitly.

        :type obj: object
        :rtype: object but not tuple or IntEnum
        """
        if (isinstance(obj, collections.abc.Iterable)
                and not isinstance(obj, (str, collections.abc.Mapping))):
            return [AbstractBackend._sanitize_db_input(x) for x in obj]
        elif isinstance(obj, enum.Enum):
            return obj.value
        else:
            return obj

    def execute_db_query(self, cur, query, params):
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`_sanitize_db_input`. However in nearly all cases you want to
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
        :rtype: {str: object} or None
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
        :rtype: [{str: object}]
        :returns: all results of query
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return tuple(
                    self._sanitize_db_output(x) for x in cur.fetchall())

    def sql_insert(self, rs, table, data, entity_key="id"):
        """Generic SQL insertion query.

        See :py:meth:`sql_select` for thoughts on this.

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type data: {str: object}
        :type entity_key: str
        :rtype: int
        :returns: id of inserted row
        """
        keys = tuple(key for key in data)
        query = glue("INSERT INTO {table} ({keys}) VALUES ({placeholders})",
                     "RETURNING {entity_key}")
        query = query.format(
            table=table, keys=", ".join(keys),
            placeholders=", ".join(("%s",) * len(keys)), entity_key=entity_key)
        params = tuple(data[key] for key in keys)
        return unwrap(self.query_one(rs, query, params))

    def sql_select(self, rs, table, columns, entities, entity_key="id"):
        """Generic SQL select query.

        This is one of a set of functions which provides formatting and
        execution of SQL queries. These are for the most common types of
        queries and apply in the majority of cases. They are
        intentionally simplistic and free of feature creep to make them
        unambiguous. In a minority case of a query which is not covered
        here the formatting and execution are left as an exercise to the
        reader. ;)

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type columns: [str]
        :type entities: [int]
        :type entity_key: str
        :rtype: [{str: object}]
        """
        query = "SELECT {columns} FROM {table} WHERE {entity_key} = ANY(%s)"
        query = query.format(table=table, columns=", ".join(columns),
                             entity_key=entity_key)
        return self.query_all(rs, query, (entities,))

    def sql_select_one(self, rs, table, columns, entity, entity_key="id"):
        """Generic SQL select query for one row.

        See :py:meth:`sql_select` for thoughts on this.

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type columns: [str]
        :type entity: int
        :type entity_key: str
        :rtype: {str: object}
        """
        query = "SELECT {columns} FROM {table} WHERE {entity_key} = %s"
        query = query.format(table=table, columns=", ".join(columns),
                             entity_key=entity_key)
        return self.query_one(rs, query, (entity,))

    def sql_update(self, rs, table, data, entity_key="id"):
        """Generic SQL update query.

        See :py:meth:`sql_select` for thoughts on this.

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type data: {str: object}
        :type entity_key: str
        :rtype: int
        :returns: number of affected rows
        """
        keys = tuple(key for key in data if key != entity_key)
        if not keys:
            ## no input is an automatic success
            return 1
        query = glue("UPDATE {table} SET ({keys}) = ({placeholders})",
                     "WHERE {entity_key} = %s")
        query = query.format(
            table=table, keys=", ".join(keys),
            placeholders=", ".join(("%s",) * len(keys)), entity_key=entity_key)
        params = tuple(data[key] for key in keys) + (data[entity_key],)
        return self.query_exec(rs, query, params)

    def sql_delete(self, rs, table, entities, entity_key="id"):
        """Generic SQL deletion query.

        See :py:meth:`sql_select` for thoughts on this.

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type entities: [int]
        :type entity_key: str
        :rtype: int
        :returns: number of affected rows
        """
        query = "DELETE FROM {table} WHERE {entity_key} = ANY(%s)"
        query = query.format(table=table, entity_key=entity_key)
        return self.query_exec(rs, query, (entities,))

    def sql_delete_one(self, rs, table, entity, entity_key="id"):
        """Generic SQL deletion query for a single row.

        See :py:meth:`sql_select` for thoughts on this.

        :type rs: :py:class:`BackendRequestState`
        :type table: str
        :type entity: int
        :type entity_key: str
        :rtype: int
        :returns: number of affected rows
        """
        query = "DELETE FROM {table} WHERE {entity_key} = %s"
        query = query.format(table=table, entity_key=entity_key)
        return self.query_exec(rs, query, (entity,))

    @staticmethod
    def diacritic_patterns(string):
        """Replace letters with a pattern matching expressions, so that
        ommitting diacritics in the query input is possible.

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

    def general_query(self, rs, query, distinct=True, view=None):
        """Perform a DB query described by a :py:class:`cdedb.query.Query`
        object.

        :type rs: :py:class:`BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :type distinct: bool
        :param distinct: whether only unique rows should be returned
        :type view: str or None
        :param view: Override parameter to specify the target of the FROM
          clause. This is necessary for event stuff and should be used seldom.
        :rtype: [{str: object}]
        :returns: all results of the query
        """
        self.logger.debug("Performing general query {}.".format(query))
        select = ", ".join(column for field in query.fields_of_interest
                           for column in field.split(','))
        view = view or QUERY_VIEWS[query.scope]
        q = "SELECT {} {} FROM {}".format("DISTINCT" if distinct else "",
                                          select, view)
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
            ## Treat containsall special since it wants to find each value in
            ## any column, without caring that the columns are the same. All
            ## other operators want to find one column fulfilling their
            ## constraint.
            if operator == QueryOperators.containsall:
                values = tuple("%{}%".format(self.diacritic_patterns(x.lower()))
                               for x in value)
                subphrase = "lower({0}) SIMILAR TO %s"
                phrase = "( ( {} ) )".format(" ) OR ( ".join(
                    subphrase.format(c) for c in columns))
                for v in values:
                    params.extend([v]*len(columns))
                constraints.append(" AND ".join(phrase
                                                for _ in range(len(values))))
                continue ## skip constraints.append below
            if operator == QueryOperators.empty:
                phrase = "( {0} IS NULL OR {0} = '' )"
            elif operator == QueryOperators.nonempty:
                if query.spec[field] == "str":
                    phrase = "( {0} IS NOT NULL AND {0} <> '' )"
                else:
                    phrase = "( {0} IS NOT NULL )"
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
                     ", ".join("{} {}".format(entry.split(',')[0],
                                              "ASC" if ascending else "DESC")
                               for entry, ascending in query.order))
        return self.query_all(rs, q, params)

    def generic_retrieve_log(self, rs, code_validator, entity_name, table,
                             codes=None, entity_id=None, start=None, stop=None,
                             additional_columns=None):
        """Get recorded activity.

        Each realm has it's own log as well as potentially additional
        special purpose logs. This method fetches entries in a generic
        way. It allows to filter the entries for specific
        codes or a specific entity (think event or mailinglist).

        This does not do authentication, which has to be done by the
        caller. However it does validation which thus may be omitted by the
        caller.

        This is separate from the changelog for member data (which keeps
        a lot more information to be able to reconstruct the entire
        history).

        However this handles the finance_log for financial transactions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code_validator: str
        :param code_validator: e.g. "enum_mllogcodes"
        :type entity_name: str
        :param entity_name: e.g. "event" or "mailinglist"
        :type table: str
        :param table: e.g. "ml.log" or "event.log"
        :type code_validator: str
        :param code_validator: e.g. "enum_mllogcodes"
        :type codes: [int] or None
        :type entity_id: int or None
        :type start: int or None
        :param start: How many entries to skip at the start.
        :type stop: int or None
        :param stop: At which entry to halt, in sum you get ``stop-start``
          entries (works like python sequence slices).
        :type additional_columns: [str] or None
        :param additional_columns: Extra values to retrieve.
        :rtype: [{str: object}]
        """
        codes = affirm_array_validation(code_validator, codes, allow_None=True)
        entity_id = affirm_validation("id_or_None", entity_id)
        start = affirm_validation("int_or_None", start)
        stop = affirm_validation("int_or_None", stop)
        additional_columns = affirm_array_validation(
            "restrictive_identifier", additional_columns, allow_None=True)
        start = start or 0
        additional_columns = additional_columns or tuple()
        if stop:
            stop = max(start, stop)
        query = glue(
            "SELECT ctime, code, submitted_by, {entity}_id, persona_id,",
            "additional_info {extra_columns} FROM {table} {condition}",
            "ORDER BY id DESC")
        if stop:
            query = glue(query, "LIMIT {}".format(stop-start))
        if start:
            query = glue(query, "OFFSET {}".format(start))
        extra_columns = ", ".join(additional_columns)
        if extra_columns:
            extra_columns = ", " + extra_columns
        connector = "WHERE"
        condition = ""
        params = []
        if codes:
            connector = "AND"
            condition = glue(condition, "WHERE code = ANY(%s)")
            params.append(codes)
        if entity_id:
            condition = glue(
                condition, "{} {}_id = %s").format(connector, entity_name)
            params.append(entity_id)
        query = query.format(entity=entity_name, extra_columns=extra_columns,
                             table=table, condition=condition)
        return self.query_all(rs, query, params)

def affirm_validation(assertion, value, **kwargs):
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    :type assertion: str
    :type value: object
    :rtype: object
    """
    checker = getattr(validate, "assert_{}".format(assertion))
    return checker(value, **kwargs)

def affirm_array_validation(assertion, values, allow_None=False, **kwargs):
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for an array.

    :type assertion: str
    :type allow_None: bool
    :param allow_None: Since we don't have the luxury of an automatic
      '_or_None' variant like with other validators we have this parameter.
    :type values: [object] (or None)
    :rtype: [object]
    """
    if allow_None and values is None:
        return None
    checker = getattr(validate, "assert_{}".format(assertion))
    return tuple(checker(value, **kwargs) for value in values)

#: Translate between validator names and sql data types.
#:
#: This is utilized during handling jsonb columns.
PYTHON_TO_SQL_MAP = {
    "int": "integer",
    "str": "varchar",
    "float": "double precision",
    "date": "date",
    "datetime": "timestamp",
    "bool": "boolean",
}
