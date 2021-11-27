#!/usr/bin/env python3

"""All the common infrastructure for the backend services.

The most important thing is :py:class:`AbstractBackend` which is the
template for all services.
"""

import abc
import cgitb
import collections.abc
import copy
import datetime
import enum
import functools
import logging
import sys
from types import TracebackType
from typing import (
    Any, Callable, ClassVar, Collection, Dict, Iterable, List, Literal, Mapping,
    Optional, Sequence, Set, Tuple, Type, TypeVar, Union, cast, overload,
)

import psycopg2.extensions
import psycopg2.extras

import cdedb.validation as validate
import cdedb.validationtypes as vtypes
from cdedb.common import (
    LOCALE, CdEDBLog, CdEDBObject, CdEDBObjectMap, DefaultReturnCode, Error, PathLike,
    PrivilegeError, PsycoJson, RequestState, Role, diacritic_patterns, glue, make_proxy,
    make_root_logger, n_, unwrap,
)
from cdedb.config import Config
from cdedb.database.connection import Atomizer
from cdedb.database.constants import FieldDatatypes
from cdedb.query import Query, QueryOperators
from cdedb.validation import parse_date, parse_datetime

F = TypeVar('F', bound=Callable[..., Any])
T = TypeVar('T')
S = TypeVar('S')

# The following are meant to be used for type hinting the sql backend methods.
# DatabaseValue is for any singular value that should be written into the database or
# compared to something already stored.
DatabaseValue = Union[int, str, enum.IntEnum, float, datetime.date, datetime.datetime,
                      None]
# DatabaseValue_s is either a singular value or a collection of such values, e.g. to be
# used with an "ANY(%s)" like comparison.
DatabaseValue_s = Union[DatabaseValue, Collection[DatabaseValue]]
# EntityKey is the value of an identifier, most often an id, given to retrieve or
# delete the corresponding entity from the database.
EntityKey = Union[int, str]
# EntityKeys is a collection of identifiers, i.e. ids, given for retrieval or deletion
# of the corresponding entities. Note that we do not use string identifiers for this.
EntityKeys = Collection[int]


@overload
def singularize(function: Callable[..., Mapping[Any, T]],
                array_param_name: str = "",
                singular_param_name: str = ""
                ) -> Callable[..., T]: ...


@overload
def singularize(function: Callable[..., T], array_param_name: str = "",
                singular_param_name: str = "",
                passthrough: Literal[True] = True) -> Callable[..., T]: ...


def singularize(function: Callable[..., Union[T, Mapping[Any, T]]],
                array_param_name: str = "ids",
                singular_param_name: str = "anid",
                passthrough: bool = False) -> Callable[..., T]:
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
    # pylint: disable=used-before-assignment
    @functools.wraps(function)
    def singularized(self: AbstractBackend, rs: RequestState, *args: Any,
                     **kwargs: Any) -> T:
        if singular_param_name in kwargs:
            param = kwargs.pop(singular_param_name)
            kwargs[array_param_name] = (param,)
        else:
            param = args[0]
            args = ((param,),) + args[1:]
        data = function(self, rs, *args, **kwargs)
        if passthrough:
            return cast(T, data)
        else:
            return cast(Mapping[Any, T], data)[param]

    return singularized


def batchify(function: Callable[..., T],
             array_param_name: str = "data",
             singular_param_name: str = "data") -> Callable[..., List[T]]:
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
    def batchified(self: AbstractBackend, rs: RequestState, *args: Any,
                   **kwargs: Any) -> List[T]:
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


def read_conditional_write_composer(
        reader: Callable[..., Any], writer: Callable[..., int],
        id_param_name: str = "anid", datum_param_name: str = "data",
        id_key_name: str = "id",) -> Callable[..., int]:
    """This takes two functions and returns a combined version.

    The overall semantics are similar to the writer. However the write is
    elided if the reader returns a value equal to the object to be written
    (i.e. there is no change).

    :param id_param_name: Name of the reader argument specifying the object
        id.
    :param datum_param_name: Name of the writer argument specifying the
        object value.
    :param id_key_name: Key associated to the id in the object value
        dictionary.
    """

    @functools.wraps(writer)
    def composed(self: AbstractBackend, rs: RequestState, *args: Any,
                 **kwargs: Any) -> DefaultReturnCode:
        ret = 1
        reader_kwargs = kwargs.copy()
        reader_args = args[:]
        if datum_param_name in reader_kwargs:
            data = reader_kwargs.pop(datum_param_name)
            reader_kwargs[id_param_name] = data[id_key_name]
        else:
            data = reader_args[0]
            reader_args = (data[id_key_name],) + reader_args[1:]
        with Atomizer(rs):
            current = reader(self, rs, *reader_args, **reader_kwargs)
            if {k: v for k, v in current.items() if k in data} != data:
                ret = writer(self, rs, *args, **kwargs)
        return ret

    return composed


def access(*roles: Role) -> Callable[[F], F]:
    """The @access decorator marks a function of a backend for publication.

    Think of this as an RPC interface, only published functions are
    accessible (and only by users with the necessary roles).

    Any of the specfied roles suffices. To require more than one role, you can
    chain two decorators together.
    """

    def decorator(function: F) -> F:

        @functools.wraps(function)
        def wrapper(self: AbstractBackend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if rs.user.roles.isdisjoint(roles):
                raise PrivilegeError(
                    n_("%(user_roles)s is disjoint from %(roles)s"),
                    {"user_roles": rs.user.roles, "roles": roles}
                )
            return function(self, rs, *args, **kwargs)

        wrapper.access = True  # type: ignore[attr-defined]
        return cast(F, wrapper)

    return decorator


def internal(function: F) -> F:
    """Mark a function of a backend for internal publication.

    It will be accessible via the :py:class:`cdedb.common.make_proxy` in
    internal mode.
    """

    function.internal = True  # type: ignore[attr-defined]
    return function


def _affirm_atomized_context(rs: RequestState) -> None:
    """Make sure that we are operating in a atomized transaction."""

    if not rs.conn.is_contaminated:
        raise RuntimeError(n_("No contamination!"))


class AbstractBackend(metaclass=abc.ABCMeta):
    """Basic template for all backend services.

    Children classes have to override some things: first :py:attr:`realm`
    identifies the component; furthermore there are some abstract methods
    which specify realm-specific behaviour (with a default implementation
    which is sufficient for some cases).
    """
    #: abstract str to be specified by children
    realm: ClassVar[str]

    def __init__(self, configpath: PathLike = None) -> None:
        self.conf = Config(configpath)
        # initialize logging
        make_root_logger(
            "cdedb.backend",
            self.conf["LOG_DIR"] / "cdedb-backend.log",
            self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        make_root_logger(
            f"cdedb.backend.{self.realm}",
            self.conf["LOG_DIR"] / f"cdedb-backend-{self.realm}.log",
            self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        # logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.{}".format(self.realm))
        self.logger.debug(f"Instantiated {self} with configpath {configpath}.")
        # Everybody needs access to the core backend
        # Import here since we otherwise have a cyclic import.
        # I don't see how we can get out of this ...
        from cdedb.backend.core import (  # pylint: disable=import-outside-toplevel
            CoreBackend,
        )
        self.core: CoreBackend
        if isinstance(self, CoreBackend):
            # self.core = cast('CoreBackend', self)
            self.core = make_proxy(self, internal=True)
        else:
            self.core = make_proxy(CoreBackend(configpath), internal=True)

    affirm_atomized_context = staticmethod(_affirm_atomized_context)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        """We abstract away the admin privilege.

        Maybe this can be beefed up to check for orgas and moderators too,
        but for now it only checks the admin role.
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    # mypy treats all imports from psycopg2 as `Any`, so we do not gain anything by
    # overloading the definition.
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

    # mypy cannot really understand the intricacies of what this function does, so
    # we keep this simple. instead of overloading the definition.
    @staticmethod
    def _sanitize_db_input(obj: Any) -> Union[Any, List[Any]]:
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

    def execute_db_query(self, cur: psycopg2.extensions.cursor, query: str,
                         params: Sequence[DatabaseValue_s]) -> None:
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`_sanitize_db_input`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.
        """
        sanitized_params = tuple(
            self._sanitize_db_input(p) for p in params)
        self.logger.debug(f"Execute PostgreSQL query"
                          f" {cur.mogrify(query, sanitized_params)}.")
        cur.execute(query, sanitized_params)

    def query_exec(self, rs: RequestState, query: str,
                   params: Sequence[DatabaseValue_s]) -> int:
        """Execute a query in a safe way (inside a transaction)."""
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return cur.rowcount

    def query_one(self, rs: RequestState, query: str, params: Sequence[DatabaseValue_s]
                  ) -> Optional[CdEDBObject]:
        """Execute a query in a safe way (inside a transaction).

        :returns: First result of query or None if there is none
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return self._sanitize_db_output(cur.fetchone())

    def query_all(self, rs: RequestState, query: str, params: Sequence[DatabaseValue_s]
                  ) -> Tuple[CdEDBObject, ...]:
        """Execute a query in a safe way (inside a transaction).

        :returns: all results of query
        """
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(cur, query, params)
                return tuple(
                    cast(CdEDBObject, self._sanitize_db_output(x))
                    for x in cur.fetchall())

    def sql_insert(self, rs: RequestState, table: str, data: CdEDBObject,
                   entity_key: str = "id", drop_on_conflict: bool = False) -> int:
        """Generic SQL insertion query.

        See :py:meth:`sql_select` for thoughts on this.

        :param drop_on_conflict: Whether to do nothing if conflicting with a constraint
        :returns: id of inserted row
        """
        keys = tuple(key for key in data)
        query = (f"INSERT INTO {table} ({', '.join(keys)}) VALUES"
                 f" ({', '.join(('%s',) * len(keys))})")
        if drop_on_conflict:
            query += " ON CONFLICT DO NOTHING"
        query += f" RETURNING {entity_key}"
        params = tuple(data[key] for key in keys)
        return unwrap(self.query_one(rs, query, params)) or 0

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
        params: List[DatabaseValue] = []
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
                   entities: EntityKeys, *, entity_key: str = "id"
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
                 f" WHERE {entity_key} = ANY(%s) ORDER BY {entity_key}")
        return self.query_all(rs, query, (entities,))

    def sql_select_one(self, rs: RequestState, table: str, columns: Sequence[str],
                       entity: EntityKey, entity_key: str = "id"
                       ) -> Optional[CdEDBObject]:
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

    def sql_delete(self, rs: RequestState, table: str, entities: EntityKeys,
                   entity_key: str = "id") -> int:
        """Generic SQL deletion query.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = ANY(%s)"
        return self.query_exec(rs, query, (entities,))

    def sql_delete_one(self, rs: RequestState, table: str, entity: EntityKey,
                       entity_key: str = "id") -> int:
        """Generic SQL deletion query for a single row.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = %s"
        return self.query_exec(rs, query, (entity,))

    def cgitb_log(self) -> None:
        """Log the current exception.

        This uses the standard logger and formats the exception with cgitb.
        We take special care to contain any exceptions as cgitb is prone to
        produce them with its prying fingers.
        """
        # noinspection PyBroadException
        try:
            self.logger.error(cgitb.text(sys.exc_info(), context=7))
        except Exception:
            # cgitb is very invasive when generating the stack trace, which might go
            # wrong.
            pass

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
        self.logger.debug(f"Performing general query {query}.")
        select = ", ".join('{} AS "{}"'.format(column, column.replace('"', ''))
                           for field in query.fields_of_interest
                           for column in field.split(','))
        if query.order:
            # Collate compatible to COLLATOR in python
            orders = []
            for entry, _ in query.order:
                if query.spec[entry].type == 'str':
                    orders.append(f'{entry.split(",")[0]} COLLATE "{LOCALE}"')
                else:
                    orders.append(entry.split(',')[0])
            select += ", " + ", ".join(orders)
        select += ', ' + query.scope.get_primary_key()
        view = view or query.scope.get_view()
        q = f"SELECT {'DISTINCT' if distinct else ''} {select} FROM {view}"
        params: List[DatabaseValue] = []
        constraints = []
        _ops = QueryOperators
        for field, operator, value in query.constraints:
            lowercase = (query.spec[field].type == "str")
            if lowercase:
                # the following should be used with operators which are allowed
                # for str as well as for other types
                sql_param_str = "lower({0})"

                def caser(x: T) -> T:
                    return x.lower()  # type: ignore[attr-defined]
            else:
                sql_param_str = "{0}"

                def caser(x: T) -> T:
                    return x
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
                params.extend((tuple(caser(x) for x in value),) * len(columns))  # type: ignore[arg-type]
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
            # Collate compatible to COLLATOR in python
            orders = []
            for entry, ascending in query.order:
                if query.spec[entry].type == 'str':
                    orders.append(
                        f'{entry.split(",")[0]} COLLATE "{LOCALE}" '
                        f'{"ASC" if ascending else "DESC"}')
                else:
                    orders.append(
                        f'{entry.split(",")[0]} '
                        f'{"ASC" if ascending else "DESC"}')
            q = glue(q, "ORDER BY", ", ".join(orders))
        return self.query_all(rs, q, params)

    def generic_retrieve_log(self, rs: RequestState, code_validator: Type[T],
                             entity_name: str, table: str,
                             codes: Collection[int] = None,
                             entity_ids: Collection[int] = None,
                             offset: int = None, length: int = None,
                             additional_columns: Collection[str] = None,
                             persona_id: int = None,
                             submitted_by: int = None,
                             reviewed_by: int = None,
                             change_note: str = None,
                             time_start: datetime.datetime = None,
                             time_stop: datetime.datetime = None
                             ) -> CdEDBLog:
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
        :param reviewed_by: Filter for reviewed_by column.
            Only for core.changelog.
        :param change_note: Filter for change_note column
        :param time_start: lower bound for ctime columns
        :param time_stop: upper bound for ctime column
        """
        assert issubclass(code_validator, enum.IntEnum)
        codes = affirm_set_validation(code_validator, codes or set())
        entity_ids = affirm_set_validation(vtypes.ID, entity_ids or set())
        offset: Optional[int] = affirm_validation_optional(
            vtypes.NonNegativeInt, offset)
        length: Optional[int] = affirm_validation_optional(vtypes.PositiveInt, length)
        additional_columns = affirm_set_validation(
            vtypes.RestrictiveIdentifier, additional_columns or set())
        persona_id = affirm_validation_optional(vtypes.ID, persona_id)
        submitted_by = affirm_validation_optional(vtypes.ID, submitted_by)
        reviewed_by = affirm_validation_optional(vtypes.ID, reviewed_by)
        change_note = affirm_validation_optional(vtypes.Regex, change_note)
        time_start = affirm_validation_optional(datetime.datetime, time_start)
        time_stop = affirm_validation_optional(datetime.datetime, time_stop)

        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        additional_columns: List[str] = list(additional_columns or [])

        # First, define the common WHERE filter clauses
        conditions = []
        params: List[DatabaseValue_s] = []
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
        if change_note:
            conditions.append("change_note ~* %s")
            params.append(diacritic_patterns(change_note))
        if time_start and time_stop:
            conditions.append("%s <= ctime AND ctime <= %s")
            params.extend((time_start, time_stop))
        elif time_start:
            conditions.append("%s <= ctime")
            params.append(time_start)
        elif time_stop:
            conditions.append("ctime <= %s")
            params.append(time_stop)

        # Special column for core.changelog
        if table == "core.changelog":
            additional_columns += ["reviewed_by", "generation"]
            if reviewed_by:
                conditions.append("reviewed_by = %s")
                params.append(reviewed_by)
        elif reviewed_by:
            raise ValueError(
                "reviewed_by column only defined for changelog.")

        if conditions:
            condition = "WHERE {}".format(" AND ".join(conditions))
        else:
            condition = ""

        # The first query determines the absolute number of logs existing
        # matching the given criteria
        query = f"SELECT COUNT(*) AS count FROM {table} {condition}"
        total: int = unwrap(self.query_one(rs, query, params)) or 0
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
                 f" persona_id, change_note {extra_columns} FROM {table}"
                 f" {condition} ORDER BY id LIMIT {length}")
        if offset is not None:
            query = glue(query, "OFFSET {}".format(offset))

        data = self.query_all(rs, query, params)
        for e in data:
            e['code'] = code_validator(e['code'])
        return total, data


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

    def __enter__(self) -> None:
        if self.rs.is_quiet:
            raise RuntimeError("Already silenced. Reentrant use is unsupported.")
        self.rs.is_quiet = True
        _affirm_atomized_context(self.rs)

    def __exit__(self, atype: Type[Exception], value: Exception,
                 tb: TracebackType) -> None:
        self.rs.is_quiet = False


def affirm_validation(assertion: Type[T], value: Any, **kwargs: Any) -> T:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    ValidationWarnings are used to hint the user to re-think about a given valid entry.
    The user may decide that the given entry is fine by ignoring the warning.
    Therefore, the frontend has to handle ValidationWarnings properly, while the backend
    must **ignore** them always to reduce redundancy between frontend and backend.
    """
    return validate.validate_assert(assertion, value, ignore_warnings=True, **kwargs)


def affirm_validation_optional(
    assertion: Type[T], value: Any, **kwargs: Any
) -> Optional[T]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.backend.common.affirm_validation`
    but also allows optional/falsy values.
    """
    return validate.validate_assert_optional(
        Optional[assertion], value, ignore_warnings=True, **kwargs)  # type: ignore


def affirm_array_validation(
    assertion: Type[T], values: Iterable[Any], **kwargs: Any
) -> Tuple[T, ...]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for an array."""
    return tuple(
        affirm_validation(assertion, value, **kwargs)
        for value in values
    )


def affirm_set_validation(
    assertion: Type[T], values: Iterable[T], **kwargs: Any
) -> Set[T]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation` for a set."""
    return set(
        affirm_validation(assertion, value, **kwargs)
        for value in values
    )


def inspect_validation(
    type_: Type[T], value: Any, *, ignore_warnings: bool = True, **kwargs: Any
) -> Tuple[Optional[T], List[Error]]:
    """Convenient wrapper to call checks in :py:mod:`cdedb.validation`.

    This should only be used if the error handling must be done in the backend to
    retrieve the errors and not raising them (like affirm would do).
    """
    return validate.validate_check(
        type_, value, ignore_warnings=ignore_warnings, **kwargs)


def cast_fields(data: CdEDBObject, fields: CdEDBObjectMap) -> CdEDBObject:
    """Helper to deserialize json fields.

    We serialize some classes as strings and need to undo this upon
    retrieval from the database.
    """
    spec: Dict[str, FieldDatatypes]
    spec = {v['field_name']: v['kind'] for v in fields.values()}
    casters: Dict[FieldDatatypes, Callable[[Any], Any]] = {
        FieldDatatypes.int: lambda x: x,
        FieldDatatypes.str: lambda x: x,
        FieldDatatypes.float: lambda x: x,
        FieldDatatypes.date: parse_date,
        FieldDatatypes.datetime: parse_datetime,
        FieldDatatypes.bool: lambda x: x,
    }

    def _do_cast(key: str, val: Any) -> Any:
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
    FieldDatatypes.int: "integer",
    FieldDatatypes.str: "varchar",
    FieldDatatypes.float: "double precision",
    FieldDatatypes.date: "date",
    FieldDatatypes.datetime: "timestamp with time zone",
    FieldDatatypes.bool: "boolean",
}
