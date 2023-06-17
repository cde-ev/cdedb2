#!/usr/bin/env python3

"""All the common infrastructure for the backend services.

The most important thing is :py:class:`AbstractBackend` which is the
template for all services.
"""

import abc
import cgitb
import copy
import functools
import logging
import sys
import uuid
from types import TracebackType
from typing import (
    Any, Callable, ClassVar, Dict, Iterable, List, Literal, Mapping, Optional, Set,
    Tuple, Type, TypeVar, Union, cast, overload,
)

import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras
from passlib.hash import sha512_crypt

import cdedb.common.validation.validate as validate
from cdedb.common import (
    CdEDBLog, CdEDBObject, CdEDBObjectMap, DefaultReturnCode, Error, RequestState, Role,
    diacritic_patterns, glue, make_proxy, setup_logger, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators
from cdedb.common.query.log_filter import GenericLogFilter
from cdedb.common.sorting import LOCALE
from cdedb.common.validation.validate import parse_date, parse_datetime
from cdedb.config import Config
from cdedb.database.connection import Atomizer
from cdedb.database.constants import FieldDatatypes, LockType
from cdedb.database.query import DatabaseValue, SqlQueryBackend

F = TypeVar('F', bound=Callable[..., Any])
LF = TypeVar('LF', bound=GenericLogFilter)
T = TypeVar('T')
S = TypeVar('S')


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
                    n_("%(user_roles)s is disjoint from %(roles)s"
                       " for method %(method)s."),
                    {"user_roles": rs.user.roles, "roles": roles,
                     "method": function.__name__}
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


class AbstractBackend(SqlQueryBackend, metaclass=abc.ABCMeta):
    """Basic template for all backend services.

    Children classes have to override some things: first :py:attr:`realm`
    identifies the component; furthermore there are some abstract methods
    which specify realm-specific behaviour (with a default implementation
    which is sufficient for some cases).
    """
    #: abstract str to be specified by children
    realm: ClassVar[str]

    def __init__(self) -> None:
        self.conf = Config()
        # initialize logging
        setup_logger(
            "cdedb.backend",
            self.conf["LOG_DIR"] / "cdedb-backend.log",
            self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        setup_logger(
            f"cdedb.backend.{self.realm}",
            self.conf["LOG_DIR"] / f"cdedb-backend-{self.realm}.log",
            self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        # logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.{}".format(self.realm))
        self.logger.debug(
            f"Instantiated {self} with configpath {self.conf._configpath}.")
        # make the logger available to the query mixin
        super().__init__(self.logger)
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
            self.core = make_proxy(CoreBackend(), internal=True)

    affirm_atomized_context = staticmethod(_affirm_atomized_context)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        """We abstract away the admin privilege.

        Maybe this can be beefed up to check for orgas and moderators too,
        but for now it only checks the admin role.
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

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
                      distinct: bool = True, view: str = None, aggregate: bool = False
                      ) -> Tuple[CdEDBObject, ...]:
        """Perform a DB query described by a :py:class:`cdedb.query.Query`
        object.

        :param distinct: whether only unique rows should be returned
        :param view: Override parameter to specify the target of the FROM
          clause. This is necessary for event stuff and should be used seldom.
        :param aggregate: Perform an aggregation query instead.
        :returns: all results of the query
        """
        query.fix_custom_columns()
        self.logger.debug(f"Performing general query {query} (aggregate={aggregate}).")

        fields = {column: column.replace('"', '') for field in query.fields_of_interest
                  for column in field.split(",")}
        if aggregate:
            agg = {}
            for field, field_as in fields.items():
                agg[f"COUNT(*) FILTER (WHERE {field} IS NULL)"] = f"null.{field_as}"
                if query.spec[field].type in ("int", "float"):
                    agg[f"SUM({field})"] = f"sum.{field_as}"
                    agg[f"MIN({field})"] = f"min.{field_as}"
                    agg[f"MAX({field})"] = f"max.{field_as}"
                    agg[f"AVG({field})"] = f"avg.{field_as}"
                    agg[f"STDDEV_SAMP({field})"] = f"stddev.{field_as}"
                elif query.spec[field].type == "bool":
                    agg[f"SUM({field}::int)"] = f"sum.{field_as}"
                elif query.spec[field].type in ("date", "datetime"):
                    agg[f"MIN({field})"] = f"min.{field_as}"
                    agg[f"MAX({field})"] = f"max.{field_as}"
                    # TODO add avg for dates
            select = ", ".join(f'{k} AS "{v}"' for k, v in agg.items())
            query.order = []
        else:
            select = ", ".join(f'{k} AS "{v}"' for k, v in fields.items())
            select += ', ' + query.scope.get_primary_key()
        q, params = self._construct_query(query, select, distinct=distinct, view=view)
        data = self.query_all(rs, q, params)

        if aggregate:
            # we know that all keys are unique, so we put them in a single dict
            datum = {k: v for datum in data for k, v in datum.items()}
            # store if the respective aggregation function has an interesting value
            datum.update(
                {agg: any(datum.get(f"{agg}.{field_as}") is not None for field_as in fields.values())
                 for agg in ['null', 'sum', 'min', 'max', 'avg', 'stddev']})
            data = (datum, )

        return data

    @staticmethod
    def _construct_query(query: Query, select: str, distinct: bool,
                         view: Optional[str]) -> Tuple[str, List[DatabaseValue]]:
        if query.order:
            # Collate compatible to COLLATOR in python
            orders = []
            for entry, _ in query.order:
                if query.spec[entry].type == 'str':
                    orders.append(f'{entry.split(",")[0]} COLLATE "{LOCALE}"')
                else:
                    orders.append(entry.split(',')[0])
            select += ", " + ", ".join(orders)
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
        return q, params

    def generic_retrieve_log(self, rs: RequestState, log_filter: GenericLogFilter
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
        """
        length = log_filter.length or 0
        offset = log_filter.offset
        log_code = log_filter.log_code_class

        condition, params = log_filter.to_sql_condition()
        columns = log_filter.get_columns_str()

        # The first query determines the absolute number of logs existing
        # matching the given criteria
        query = f"SELECT COUNT(*) AS count FROM {log_filter.log_table} {condition}"
        total: int = unwrap(self.query_one(rs, query, params)) or 0
        if offset and offset > total:
            # Why you do this
            return total, tuple()
        elif offset is None and total > length:
            offset = length * ((total - 1) // length)

        # Now, query the actual information
        query = f"""
            SELECT {columns} FROM {log_filter.log_table} {condition}
            ORDER BY id LIMIT {length} {f' OFFSET {offset}' if offset else ''}
        """

        data = self.query_all(rs, query, params)
        for e in data:
            e['code'] = log_code(e['code'])
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


class DatabaseLock:
    """A synchronization directive backed by the postgres database.

    This uses a dedicated table in the database to ensure exclusive access
    to the represented resources. This is intended as a context manager.

    Care has to be taken that the caller must check whether the acquisition
    of the lock was successful. The code should look like::

        with DatabaseLock(rs, LockType.something) as lock:
            if lock:
                # use resource
            else:
                # handle lock contetion

    Note that this may not be called in an atomized context. Simply call it
    outside the Atomizer.

    This currently does not provide a way to block on the lock until it is
    available.

    """
    xid: Optional[str]

    def __init__(self, rs: RequestState, *locks: LockType):
        self.rs = rs
        self.locks = locks
        self.id = uuid.uuid4()

    def __enter__(self) -> Optional["DatabaseLock"]:
        query = ("SELECT handle FROM core.locks WHERE handle = ANY(%s)"
                 " FOR NO KEY UPDATE NOWAIT")
        params = [lock.value for lock in self.locks]
        was_locking_successful = True

        if self.rs._conn.is_contaminated:
            raise RuntimeError("Lock not possible in atomized context.")

        self.xid = self.rs._conn.xid(42, "cdedb_database_lock", str(self.id))
        if self.rs._conn.status != psycopg2.extensions.STATUS_READY:
            raise RuntimeError("Connection not ready!")
        try:
            self.rs._conn.tpc_begin(self.xid)
            cur = self.rs._conn.cursor()
            cur.execute(query, (params,))
            self.rs._conn.tpc_prepare()
        except psycopg2.errors.LockNotAvailable:
            # No lock was acquired, abort
            self.rs._conn.tpc_rollback()
            self.xid = None
            was_locking_successful = False
        except Exception:
            self.rs._conn.tpc_rollback()
            self.xid = None
            raise
        finally:
            if self.rs._conn.status == psycopg2.extensions.STATUS_PREPARED:
                # Expunge information about prepared transaction to make
                # connection available for further use
                self.rs._conn.reset()
            elif self.xid:
                raise RuntimeError("Transaction exists, but status is not prepared.")

        return self if was_locking_successful else None

    def __exit__(self, atype: Type[Exception], value: Exception,
                 tb: TracebackType) -> Literal[False]:
        if self.rs._conn.status == psycopg2.extensions.STATUS_IN_TRANSACTION:
            # We are not atomized so a commit is always possible
            self.rs._conn.commit()
        if self.rs._conn.status != psycopg2.extensions.STATUS_READY:
            raise RuntimeError(f"Connection not ready but {self.rs._conn.status}!")
        if self.xid:
            # release the lock only when actually having acquired it
            self.rs._conn.tpc_commit(self.xid)
        return False


def affirm_validation(assertion: Type[T], value: Any, **kwargs: Any) -> T:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    ValidationWarnings are used to hint the user to re-think about a given valid entry.
    The user may decide that the given entry is fine by ignoring the warning.
    Therefore, the frontend has to handle ValidationWarnings properly, while the backend
    must **ignore** them always to reduce redundancy between frontend and backend.
    """
    return validate.validate_assert(assertion, value, ignore_warnings=True, **kwargs)


def affirm_dataclass(assertion: Type[T], value: Any, **kwargs: Any) -> T:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.backend.common.affirm_validation`
    but used for dataclass objects.
    """
    return validate.validate_assert_dataclass(
        assertion, value, ignore_warnings=True, **kwargs)


def affirm_validation_optional(
    assertion: Type[T], value: Any, **kwargs: Any
) -> Optional[T]:
    """Wrapper to call asserts in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.backend.common.affirm_validation`
    but also allows optional/falsy values.
    """
    return validate.validate_assert_optional(
        Optional[assertion], value, ignore_warnings=True, **kwargs)  # type: ignore[arg-type]


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


def verify_password(password: str, password_hash: str) -> bool:
    """Central function, so that the actual implementation may be easily
    changed.
    """
    return sha512_crypt.verify(password, password_hash)


def encrypt_password(password: str) -> str:
    """We currently use passlib for password protection."""
    return sha512_crypt.hash(password)


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
