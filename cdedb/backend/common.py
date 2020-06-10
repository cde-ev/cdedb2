#!/usr/bin/env python3

"""All the common infrastructure for the backend services.

The most important thing is :py:class:`AbstractBackend` which is the
template for all services.
"""

import abc
import collections.abc
import copy
import enum
import functools
import logging
from datetime import datetime
import psycopg2.extras
import psycopg2.extensions
from typing import (
    Any, Callable, TypeVar, Iterable, Tuple, Set, List, Collection,
    Optional, Sequence, cast, overload, Mapping
)

import cdedb.validation as validate
from cdedb.common import (
    PrivilegeError, PsycoJson, diacritic_patterns, glue, make_proxy,
    make_root_logger, n_, unwrap, RequestState, Role, Realm, PathLike,
    CdEDBObject, CdEDBObjectMap,
)
from cdedb.query import Query
from cdedb.config import Config
from cdedb.database.connection import Atomizer
from cdedb.database.constants import FieldDatatypes
from cdedb.query import QUERY_PRIMARIES, QUERY_VIEWS, QueryOperators
from cdedb.validation import parse_date, parse_datetime

F = TypeVar('F', bound=Callable[..., Any])
G = TypeVar('G', bound=Callable[..., Any])
T = TypeVar('T')
S = TypeVar('S')


def singularize(function: F,
                array_param_name: str = "ids",
                singular_param_name: str = "anid",
                passthrough: bool = False) -> G:
    """This takes a function and returns a singularized version.

    The function has to accept an array as a parameter and return a dict
    indexed by this array. This array has either to be a keyword only
    parameter or the first positional parameter after the request state.
    Singularization creates a function which accepts a single element instead
    and transparently wraps in a list as well as unwrapping the returned dict.

    :param array_param_name: name of the parameter to singularize
    :param singular_param_name: new name of the singularized parameter
    :param passthrough: Whether or not the return value should be passed through
        directly. If this is false, the output is assumed to be a dict with the
        singular param as a key.
    """

    @functools.wraps(function)
    def singularized(self, rs: RequestState, *args: Any, **kwargs: Any) -> Any:
        if singular_param_name in kwargs:
            param = kwargs.pop(singular_param_name)
            kwargs[array_param_name] = (param,)
        else:
            param = args[0]
            args = ((param,),) + args[1:]
        data = function(self, rs, *args, **kwargs)
        if passthrough:
            return data
        else:
            return data[param]

    return singularized


def batchify(function: F,
             array_param_name: str = "data",
             singular_param_name: str = "data") -> G:
    """This takes a function and returns a batchified version.

    The function has to accept an a singular parameter.
    The singular parameter has either to be a keyword only parameter
    or the first positional parameter after the request state.
    Batchification creates a function which accepts an array instead
    and loops over this array wrapping everything in a database transaction.
    It returns an array of all return values.

    :param array_param_name: new name of the batchified parameter
    :param singular_param_name: name of the parameter to batchify
    """

    @functools.wraps(function)
    def batchified(self, rs: RequestState, *args: Any, **kwargs: Any) -> List:
        ret = []
        with Atomizer(rs):
            if array_param_name in kwargs:
                param = kwargs.pop(array_param_name)
                for datum in param:
                    new_kwargs = copy.deepcopy(kwargs)
                    new_kwargs[singular_param_name] = datum
                    ret.append(function(self, rs, *args, **new_kwargs))
            else:
                param = args[0]
                for datum in param:
                    new_args = (datum,) + args[1:]
                    ret.append(function(self, rs, *new_args, **kwargs))
        return ret

    return batchified


def access(*roles: Role) -> Callable[[F], F]:
    """The @access decorator marks a function of a backend for publication.

    Think of this as an RPC interface, only published functions are
    accessible (and only by users with the necessary roles).

    Any of the specfied roles suffices. To require more than one role, you can
    chain two decorators together.
    """

    def decorator(function: F) -> F:

        @functools.wraps(function)
        def wrapper(self, rs: RequestState, *args: Any, **kwargs: Any) -> Any:
            if rs.user.roles.isdisjoint(roles):
                raise PrivilegeError(
                    n_("%(user_roles)s is disjoint from %(roles)s"),
                    {"user_roles": rs.user.roles, "roles": roles}
                )
            return function(self, rs, *args, **kwargs)

        wrapper.access = True
        return cast(F, wrapper)

    return decorator


def internal(function: F) -> F:
    """Mark a function of a backend for internal publication.

    It will be accessible via the :py:class:`cdedb.common.make_proxy` in
    internal mode.
    """

    function.internal = True
    return function


class AbstractBackend(metaclass=abc.ABCMeta):
    """Basic template for all backend services.

    Children classes have to override some things: first :py:attr:`realm`
    identifies the component; furthermore there are some abstract methods
    which specify realm-specific behaviour (with a default implementation
    which is sufficient for some cases).
    """
    #: abstract str to be specified by children
    realm = None

    def __init__(self, configpath: PathLike, is_core: bool = False) -> None:
        """
        :param is_core: If not, we add instantiate a core backend for usage
          by this backend.
        """
        self.conf = Config(configpath)
        # initialize logging
        make_root_logger(
            "cdedb.backend", self.conf["BACKEND_LOG"], self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        make_root_logger(
            "cdedb.backend.{}".format(self.realm),
            self.conf[f"{self.realm.upper()}_BACKEND_LOG"],
            self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        # logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.{}".format(self.realm))
        self.logger.info("Instantiated {} with configpath {}.".format(
            self, configpath))
        # Everybody needs access to the core backend
        if is_core:
            self.core = self  # type: CoreBackend
        else:
            # Import here since we otherwise have a cyclic import.
            # I don't see how we can get out of this ...
            from cdedb.backend.core import CoreBackend
            self.core = make_proxy(CoreBackend(configpath), internal=True)

    def affirm_realm(self, rs: RequestState, ids: Collection[int],
                     realms: Set[Realm] = None) -> None:
        """Check that all personas corresponding to the ids are in the
        appropriate realm.

        :param realms: Set of realms to check for. By default this is
          the set containing only the realm of this class.
        """
        realms = realms or {self.realm}
        actual_realms = self.core.get_realms_multi(rs, ids)
        if any(not x >= realms for x in actual_realms.values()):
            raise ValueError(n_("Wrong realm for personas."))
        return

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        """We abstract away the admin privilege.

        Maybe this can be beefed up to check for orgas and moderators too,
        but for now it only checks the admin role.
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    @staticmethod
    def _sanitize_db_output(output: Optional[psycopg2.extras.RealDictRow]
                            ) -> Optional[CdEDBObject]:
        """Convert a :py:class:`psycopg2.extras.RealDictRow` into a normal
        :py:class:`dict`. We only use the outputs as dictionaries and
        the psycopg variant has some rough edges (e.g. it does not survive
        serialization).

        Also this wrapper allows future global modifications to the
        outputs, if we want to add some.
        """
        if not output:
            return None
        return dict(output)

    @staticmethod
    @overload
    def _sanitize_db_input(obj: Mapping[S, T]) -> Mapping[S, T]:
        pass

    @staticmethod
    @overload
    def _sanitize_db_input(obj: str) -> str:
        pass

    @staticmethod
    @overload
    def _sanitize_db_input(obj: Iterable[T]) -> List[T]:
        pass

    @staticmethod
    @overload
    def _sanitize_db_input(obj: enum.Enum) -> int:
        pass

    @staticmethod
    @overload
    def _sanitize_db_input(obj: T) -> T:
        pass

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
        """
        if (isinstance(obj, collections.abc.Iterable)
                and not isinstance(obj, (str, collections.abc.Mapping))):
            return [AbstractBackend._sanitize_db_input(x) for x in obj]
        elif isinstance(obj, enum.Enum):
            return obj.value
        else:
            return obj

    @staticmethod
    def affirm_atomized_context(rs: RequestState) -> None:
        """Make sure that we are operating in a atomized transaction."""

        if not rs.conn.is_contaminated:
            raise RuntimeError(n_("No contamination!"))

    def execute_db_query(self, cur: psycopg2.extensions.cursor, query: str,
                         params: Sequence) -> None:
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`_sanitize_db_input`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.
        """
        sanitized_params = tuple(self._sanitize_db_input(p) for p in params)
        self.logger.debug("Execute PostgreSQL query {}.".format(cur.mogrify(
            query, sanitized_params)))
        cur.execute(query, sanitized_params)

    def query_exec(self, rs: RequestState, query: str, params: Sequence) -> int:
        """Execute a query in a safe way (inside a transaction)."""
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return cur.rowcount

    def query_one(self, rs: RequestState, query: str, params: Sequence
                  ) -> Optional[CdEDBObject]:
        """Execute a query in a safe way (inside a transaction).

        :returns: First result of query or None if there is none
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return self._sanitize_db_output(cur.fetchone())

    def query_all(self, rs: RequestState, query: str, params: Sequence
                  ) -> Tuple[CdEDBObject, ...]:
        """Execute a query in a safe way (inside a transaction).

        :returns: all results of query
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return tuple(
                    self._sanitize_db_output(x) for x in cur.fetchall())

    def sql_insert(self, rs: RequestState, table: str, data: CdEDBObject,
                   entity_key: str = "id") -> int:
        """Generic SQL insertion query.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: id of inserted row
        """
        keys = tuple(key for key in data)
        query = (f"INSERT INTO {table} ({', '.join(keys)}) VALUES"
                 f" ({', '.join(('%s',) * len(keys))}) RETURNING {entity_key}")
        params = tuple(data[key] for key in keys)
        return unwrap(self.query_one(rs, query, params))

    def sql_insert_many(self, rs: RequestState, table: str,
                        data: Sequence[CdEDBObject]) -> int:
        """Generic SQL query to insert multiple datasets with the same keys.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of inserted rows
        """
        if not data:
            return 0
        keys = tuple(data[0].keys())
        key_set = set(keys)
        params = []
        for entry in data:
            if entry.keys() != key_set:
                raise ValueError(n_("Dict keys do not match."))
            params.extend(entry[k] for k in keys)
        # Create len(data) many row placeholders for len(keys) many values.
        value_list = ", ".join(("({})".format(", ".join(("%s",) * len(keys))),)
                               * len(data))
        query = f"INSERT INTO {table} ({', '.join(keys)}) VALUES {value_list}"
        return self.query_exec(rs, query, params)

    def sql_select(self, rs: RequestState, table: str, columns: Sequence[str],
                   entities: Collection, entity_key: str = "id"
                   ) -> Tuple[CdEDBObject, ...]:
        """Generic SQL select query.

        This is one of a set of functions which provides formatting and
        execution of SQL queries. These are for the most common types of
        queries and apply in the majority of cases. They are
        intentionally simplistic and free of feature creep to make them
        unambiguous. In a minority case of a query which is not covered
        here the formatting and execution are left as an exercise to the
        reader. ;)
        """
        query = (f"SELECT {', '.join(columns)} FROM {table}"
                 f" WHERE {entity_key} = ANY(%s)")
        return self.query_all(rs, query, (entities,))

    def sql_select_one(self, rs: RequestState, table: str,
                       columns: Sequence[str], entity: Any,
                       entity_key: str = "id") -> Optional[CdEDBObject]:
        """Generic SQL select query for one row.

        See :py:meth:`sql_select` for thoughts on this.
        """
        query = (f"SELECT {', '.join(columns)} FROM {table}"
                 f" WHERE {entity_key} = %s")
        return self.query_one(rs, query, (entity,))

    def sql_update(self, rs: RequestState, table: str, data: CdEDBObject,
                   entity_key: str = "id") -> int:
        """Generic SQL update query.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        keys = tuple(key for key in data if key != entity_key)
        if not keys:
            # no input is an automatic success
            return 1
        query = (f"UPDATE {table} SET ({', '.join(keys)}) ="
                 f" ROW({', '.join(('%s',) * len(keys))})"
                 f" WHERE {entity_key} = %s")
        params = tuple(data[key] for key in keys) + (data[entity_key],)
        return self.query_exec(rs, query, params)

    def sql_json_inplace_update(self, rs: RequestState, table: str,
                                data: CdEDBObject, entity_key: str = "id"
                                ) -> int:
        """Generic SQL update query for JSON fields storing a dict.

        This leaves missing keys unmodified.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        keys = tuple(key for key in data if key != entity_key)
        if not keys:
            # no input is an automatic success
            return 1
        commands = ", ".join("{key} = {key} || %s".format(key=key)
                             for key in keys)
        query = f"UPDATE {table} SET {commands} WHERE {entity_key} = %s"
        params = tuple(PsycoJson(data[key]) for key in keys)
        params += (data[entity_key],)
        return self.query_exec(rs, query, params)

    def sql_delete(self, rs: RequestState, table: str, entities: Collection,
                   entity_key: str = "id") -> int:
        """Generic SQL deletion query.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = ANY(%s)"
        return self.query_exec(rs, query, (entities,))

    def sql_delete_one(self, rs: RequestState, table: str, entity: Any,
                       entity_key: str = "id"):
        """Generic SQL deletion query for a single row.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = %s"
        return self.query_exec(rs, query, (entity,))

    def general_query(self, rs: RequestState, query: Query,
                      distinct: bool = True, view: str = None
                      ) -> Tuple[CdEDBObject, ...]:
        """Perform a DB query described by a :py:class:`cdedb.query.Query`
        object.

        :param distinct: whether only unique rows should be returned
        :param view: Override parameter to specify the target of the FROM
          clause. This is necessary for event stuff and should be used seldom.
        :returns: all results of the query
        """
        query.fix_custom_columns()
        self.logger.debug("Performing general query {}.".format(query))
        select = ", ".join('{} AS "{}"'.format(column, column.replace('"', ''))
                           for field in query.fields_of_interest
                           for column in field.split(','))
        if query.order:
            orders = ", ".join(entry.split(',')[0] for entry, _ in query.order)
            select = glue(select, ',', orders)
        select = glue(select, ',', QUERY_PRIMARIES[query.scope])
        view = view or QUERY_VIEWS[query.scope]
        q = "SELECT {} {} FROM {}".format("DISTINCT" if distinct else "",
                                          select, view)
        params = []
        constraints = []
        _ops = QueryOperators
        for field, operator, value in query.constraints:
            lowercase = (query.spec[field] == "str")
            if lowercase:
                # the following should be used with operators which are allowed
                # for str as well as for other types
                sql_param_str = "lower({0})"
                caser = lambda x: x.lower()
            else:
                sql_param_str = "{0}"
                caser = lambda x: x
            columns = field.split(',')
            # Treat containsall and friends special since they want to find
            # each value in any column, without caring that the columns are
            # the same. All other operators want to find one column
            # fulfilling their constraint.
            if operator in (_ops.containsall, _ops.containsnone,
                            _ops.containssome):
                values = tuple(diacritic_patterns(x) for x in value)
                subphrase = "{0} ~* %s"
                phrase = "( ( {} ) )".format(" ) OR ( ".join(
                    subphrase.format(c) for c in columns))
                for v in values:
                    params.extend([v] * len(columns))
                connector = " AND " if operator == _ops.containsall else " OR "
                constraint = connector.join(phrase for _ in range(len(values)))
                if operator == _ops.containsnone:
                    constraint = "NOT ( {} )".format(constraint)
                constraints.append(constraint)
                continue  # skip constraints.append below
            if operator == _ops.empty:
                if query.spec[field] == "str":
                    phrase = "( {0} IS NULL OR {0} = '' )"
                else:
                    phrase = "( {0} IS NULL )"
            elif operator == _ops.nonempty:
                if query.spec[field] == "str":
                    phrase = "( {0} IS NOT NULL AND {0} <> '' )"
                else:
                    phrase = "( {0} IS NOT NULL )"
            elif operator in (_ops.equal, _ops.unequal, _ops.equalornull,
                              _ops.unequalornull):
                if operator in (_ops.equal, _ops.equalornull):
                    phrase = "( {0} = %s"
                else:
                    phrase = "( {0} != %s"
                params.extend((caser(value),) * len(columns))
                if operator in (_ops.equalornull, _ops.unequalornull):
                    if query.spec[field] == "str":
                        phrase += " OR {0} IS NULL OR {0} = '' )"
                    else:
                        phrase += " OR {0} IS NULL )"
                else:
                    phrase += " )"
                phrase = phrase.format(sql_param_str)
            elif operator in (_ops.oneof, _ops.otherthan):
                if operator == _ops.oneof:
                    phrase = "{0} = ANY(%s)".format(sql_param_str)
                else:
                    phrase = "NOT({0} = ANY(%s))".format(sql_param_str)
                params.extend((tuple(caser(x) for x in value),) * len(columns))
            elif operator in (_ops.match, _ops.unmatch):
                if operator == _ops.match:
                    phrase = "{} ~* %s"
                else:
                    phrase = "{} !~* %s"
                params.extend((diacritic_patterns(value),) * len(columns))
            elif operator in (_ops.regex, _ops.notregex):
                if operator == _ops.regex:
                    phrase = "{} ~ %s"
                else:
                    phrase = "{} !~ %s"
                params.extend((value,) * len(columns))
            elif operator == _ops.fuzzy:
                phrase = "similarity({}, %s) > 0.5"
                params.extend((value,) * len(columns))
            elif operator == _ops.less:
                phrase = "{} < %s"
                params.extend((value,) * len(columns))
            elif operator == _ops.lessequal:
                phrase = "{} <= %s"
                params.extend((value,) * len(columns))
            elif operator in (_ops.between, _ops.outside):
                if operator == _ops.between:
                    phrase = "(%s <= {0} AND {0} <= %s)"
                else:
                    phrase = "(%s >= {0} OR {0} >= %s)"
                params.extend((value[0], value[1]) * len(columns))
            elif operator == _ops.greaterequal:
                phrase = "{} >= %s"
                params.extend((value,) * len(columns))
            elif operator == _ops.greater:
                phrase = "{} > %s"
                params.extend((value,) * len(columns))
            else:
                raise RuntimeError(n_("Impossible."))
            constraints.append(" OR ".join(phrase.format(c) for c in columns))
        if constraints:
            q = glue(q, "WHERE", "({})".format(" ) AND ( ".join(constraints)))
        if query.order:
            q = glue(q, "ORDER BY",
                     ", ".join("{} {}".format(entry.split(',')[0],
                                              "ASC" if ascending else "DESC")
                               for entry, ascending in query.order))
        return self.query_all(rs, q, params)

    def generic_retrieve_log(self, rs: RequestState, code_validator: str,
                             entity_name: str, table: str,
                             codes: Collection[int] = None,
                             entity_ids: Collection = None,
                             offset: int = None, length: int = None,
                             additional_columns: Collection[str] = None,
                             persona_id: int = None, submitted_by: int = None,
                             additional_info: str = None,
                             time_start: datetime = None,
                             time_stop: datetime = None
                             ) -> Tuple[int, Tuple[CdEDBObject, ...]]:
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

        :param code_validator: e.g. "enum_mllogcodes"
        :param entity_name: e.g. "event" or "mailinglist"
        :param table: e.g. "ml.log" or "event.log"
        :param offset: How many entries to skip at the start.
        :param length: How many entries to list.
        :param additional_columns: Extra values to retrieve.
        :param persona_id: Filter for persona_id column.
        :param submitted_by: Filter for submitted_by column.
        :param additional_info: Filter for additional_info column
        :param time_start: lower bound for ctime columns
        :param time_stop: upper bound for ctime column
        """
        codes = affirm_set_validation(code_validator, codes, allow_None=True)
        entity_ids = affirm_set_validation("id", entity_ids, allow_None=True)
        offset = affirm_validation("non_negative_int_or_None", offset)
        length = affirm_validation("positive_int_or_None", length)
        additional_columns = affirm_set_validation(
            "restrictive_identifier", additional_columns, allow_None=True)
        persona_id = affirm_validation("id_or_None", persona_id)
        submitted_by = affirm_validation("id_or_None", submitted_by)
        additional_info = affirm_validation("regex_or_None", additional_info)
        time_start = affirm_validation("datetime_or_None", time_start)
        time_stop = affirm_validation("datetime_or_None", time_stop)

        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        additional_columns = additional_columns or tuple()

        # First, define the common WHERE filter clauses
        conditions = []
        params = []
        if codes:
            conditions.append("code = ANY(%s)")
            params.append(codes)
        if entity_ids:
            conditions.append("{}_id = ANY(%s)".format(entity_name))
            params.append(entity_ids)
        if persona_id:
            conditions.append("persona_id = %s")
            params.append(persona_id)
        if submitted_by:
            conditions.append("submitted_by = %s")
            params.append(submitted_by)
        if additional_info:
            conditions.append("additional_info ~* %s")
            params.append(diacritic_patterns(additional_info))
        if time_start and time_stop:
            conditions.append("%s <= ctime AND ctime <= %s")
            params.extend((time_start, time_stop))
        elif time_start:
            conditions.append("%s <= ctime")
            params.append(time_start)
        elif time_stop:
            conditions.append("ctime <= %s")
            params.append(time_stop)

        if conditions:
            condition = "WHERE {}".format(" AND ".join(conditions))
        else:
            condition = ""

        # The first query determines the absolute number of logs existing
        # matching the given criteria
        query = f"SELECT COUNT(*) AS count FROM {table} {condition}"
        total = unwrap(self.query_one(rs, query, params))
        if offset and offset > total:
            # Why you do this
            return total, tuple()
        elif offset is None and total > length:
            offset = length * ((total - 1) // length)

        extra_columns = ", ".join(additional_columns)
        if extra_columns:
            extra_columns = ", " + extra_columns

        # Now, query the actual information
        query = (f"SELECT id, ctime, code, submitted_by, {entity_name}_id,"
                 f" persona_id, additional_info {extra_columns} FROM {table}"
                 f" {condition} ORDER BY id LIMIT {length}")
        if offset is not None:
            query = glue(query, "OFFSET {}".format(offset))

        return total, self.query_all(rs, query, params)


class Silencer:
    """Helper to temporarily dissable logging.

    This is intended to be used as a context::

        with Silencer(rs):
            # do lots of stuff
        # log what you did

    Note that the logs which were silenced should always be substituted with
    a different higher level log message.
    """

    def __init__(self, rs: RequestState):
        self.rs = rs

    def __enter__(self):
        self.rs.is_quiet = True

    def __exit__(self, atype, value, tb):
        self.rs.is_quiet = False


def affirm_validation(assertion: str, value: T,
                      **kwargs: Any) -> Optional[T]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`."""
    checker = getattr(validate, "assert_{}".format(assertion))
    return checker(value, **kwargs)


# Ignore the parameter name allow_None
# noinspection PyPep8Naming
def affirm_array_validation(assertion: str, values: Iterable[T],
                            allow_None: bool = False,
                            **kwargs: Any) -> Optional[Tuple[T, ...]]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for an array.

    :param allow_None: Since we don't have the luxury of an automatic
      '_or_None' variant like with other validators we have this parameter.
    """
    if allow_None and values is None:
        return None
    checker: Callable[[T, ...], T] = getattr(
        validate, "assert_{}".format(assertion))
    return tuple(checker(value, **kwargs) for value in values)


# Ignore the parameter name allow_None
# noinspection PyPep8Naming
def affirm_set_validation(assertion: str, values: Iterable[T],
                          allow_None: bool = False,
                          **kwargs: Any) -> Optional[Set[T]]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for a set.

    :param allow_None: Since we don't have the luxury of an automatic
      '_or_None' variant like with other validators we have this parameter.
    """
    if allow_None and values is None:
        return None
    checker: Callable[[T, ...], T] = getattr(
        validate, "assert_{}".format(assertion))
    return {checker(value, **kwargs) for value in values}


def cast_fields(data: CdEDBObject, spec: CdEDBObjectMap) -> CdEDBObject:
    """Helper to deserialize json fields.

    We serialize some classes as strings and need to undo this upon
    retrieval from the database.
    """
    spec = {v['field_name']: v['kind'] for v in spec.values()}
    casters = {
        FieldDatatypes.int: lambda x: x,
        FieldDatatypes.str: lambda x: x,
        FieldDatatypes.float: lambda x: x,
        FieldDatatypes.date: parse_date,
        FieldDatatypes.datetime: parse_datetime,
        FieldDatatypes.bool: lambda x: x,
    }

    def _do_cast(key, val):
        if val is None:
            return None
        if key in spec:
            return casters[spec[key]](val)
        return val

    return {key: _do_cast(key, val) for key, val in data.items()}


#: Translate between validator names and sql data types.
#:
#: This is utilized during handling jsonb columns.
PYTHON_TO_SQL_MAP = {
    "int": "integer",
    "str": "varchar",
    "float": "double precision",
    "date": "date",
    "datetime": "timestamp with time zone",
    "bool": "boolean",
}
