#!/usr/bin/env python3

"""Provide a generic interface to query the database.

This is used by :py:class:`AbstractBackend` to access the database.
"""

import datetime
import decimal
import enum
import logging
from collections.abc import Collection, Sequence
from typing import Optional, Union, cast

import psycopg2.extensions
import psycopg2.extras

from cdedb.common import CdEDBObject, DefaultReturnCode, PsycoJson, unwrap
from cdedb.database.connection import ConnectionContainer, n_
from cdedb.database.conversions import from_db_output, to_db_input
from cdedb.models.common import CdEDataclass

# The following are meant to be used for type hinting the sql backend methods.
# DatabaseValue is for any singular value that should be written into the database or
# compared to something already stored.
DatabaseValue = Union[int, str, enum.IntEnum, float, datetime.date, datetime.datetime,
                      decimal.Decimal, None, PsycoJson]
# DatabaseValue_s is either a singular value or a collection of such values, e.g. to be
# used with an "ANY(%s)" like comparison.
DatabaseValue_s = Union[DatabaseValue, Collection[DatabaseValue]]
# EntityKey is the value of an identifier, most often an id, given to retrieve or
# delete the corresponding entity from the database.
EntityKey = Union[int, str]
# EntityKeys is a collection of identifiers, i.e. ids, given for retrieval or deletion
# of the corresponding entities. Note that we do not use string identifiers for this.
EntityKeys = Collection[int]


class SqlQueryBackend:
    """Python backend to access the SQL database layer.

    This provides some methods to query the database. Beside the low-level query_*
    functions, this contains also some more elevate functions named sql_* to perform
    common and simple sql queries.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def execute_db_query(self, cur: psycopg2.extensions.cursor, query: str,
                         params: Sequence[DatabaseValue_s]) -> None:
        """Perform a database query. This low-level wrapper should be used
        for all explicit database queries, mostly because it invokes
        :py:meth:`to_db_input`. However in nearly all cases you want to
        call one of :py:meth:`query_exec`, :py:meth:`query_one`,
        :py:meth:`query_all` which utilize a transaction to do the query. If
        this is not called inside a transaction context (probably created by
        a ``with`` block) it is unsafe!

        This doesn't return anything, but has a side-effect on ``cur``.
        """
        sanitized_params = tuple(to_db_input(p) for p in params)
        self.logger.debug(f"Execute PostgreSQL query"
                          f" {cur.mogrify(query, sanitized_params).decode()}.")
        cur.execute(query, sanitized_params)

    def query_exec(self, container: ConnectionContainer, query: str,
                   params: Sequence[DatabaseValue_s]) -> int:
        """Execute a query in a safe way (inside a transaction)."""
        with container.conn as conn:
            with conn.cursor() as cur:
                assert isinstance(cur, psycopg2.extras.RealDictCursor)
                self.execute_db_query(cur, query, params)
                return cur.rowcount

    def query_one(self, container: ConnectionContainer, query: str,
                  params: Sequence[DatabaseValue_s]) -> Optional[CdEDBObject]:
        """Execute a query in a safe way (inside a transaction).

        :returns: First result of query or None if there is none
        """
        with container.conn as conn:
            with conn.cursor() as cur:
                assert isinstance(cur, psycopg2.extras.RealDictCursor)
                self.execute_db_query(cur, query, params)
                return from_db_output(cur.fetchone())

    def query_all(self, container: ConnectionContainer, query: str,
                  params: Sequence[DatabaseValue_s]) -> tuple[CdEDBObject, ...]:
        """Execute a query in a safe way (inside a transaction).

        :returns: all results of query
        """
        with container.conn as conn:
            with conn.cursor() as cur:
                assert isinstance(cur, psycopg2.extras.RealDictCursor)
                self.execute_db_query(cur, query, params)
                return tuple(
                    cast(CdEDBObject, from_db_output(x))
                    for x in cur.fetchall())

    def sql_insert(self, container: ConnectionContainer, table: str, data: CdEDBObject,
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
        return unwrap(self.query_one(container, query, params)) or 0

    def sql_insert_many(self, container: ConnectionContainer, table: str,
                        data: Sequence[CdEDBObject]) -> int:
        """Generic SQL query to insert multiple datasets with the same keys.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of inserted rows
        """
        if not data:
            return 0
        keys = tuple(data[0].keys())
        key_set = set(keys)
        params: list[DatabaseValue] = []
        for entry in data:
            if entry.keys() != key_set:
                raise ValueError(n_("Dict keys do not match."))
            params.extend(entry[k] for k in keys)
        # Create len(data) many row placeholders for len(keys) many values.
        value_list = ", ".join(("({})".format(", ".join(("%s",) * len(keys))),)
                               * len(data))
        query = f"INSERT INTO {table} ({', '.join(keys)}) VALUES {value_list}"
        return self.query_exec(container, query, params)

    def sql_insert_dataclass(self, container: ConnectionContainer, datum: CdEDataclass,
                             ) -> int:
        return self.sql_insert(container, datum.database_table, datum.to_database())

    def sql_select(self, container: ConnectionContainer, table: str,
                   columns: Sequence[str], entities: EntityKeys, *,
                   entity_key: str = "id") -> tuple[CdEDBObject, ...]:
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
        return self.query_all(container, query, (entities,))

    def sql_select_one(self, container: ConnectionContainer, table: str,
                       columns: Sequence[str], entity: EntityKey,
                       entity_key: str = "id") -> Optional[CdEDBObject]:
        """Generic SQL select query for one row.

        See :py:meth:`sql_select` for thoughts on this.
        """
        query = (f"SELECT {', '.join(columns)} FROM {table}"
                 f" WHERE {entity_key} = %s")
        return self.query_one(container, query, (entity,))

    def sql_update(self, container: ConnectionContainer, table: str, data: CdEDBObject,
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
        return self.query_exec(container, query, params)

    def sql_json_inplace_update(self, container: ConnectionContainer, table: str,
                                data: CdEDBObject, entity_key: str = "id",
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
        commands = ", ".join(f"{key} = {key} || %s"
                             for key in keys)
        query = f"UPDATE {table} SET {commands} WHERE {entity_key} = %s"
        params = tuple(PsycoJson(data[key]) for key in keys)
        params += (data[entity_key],)
        return self.query_exec(container, query, params)

    def sql_delete(self, container: ConnectionContainer, table: str,
                   entities: EntityKeys, entity_key: str = "id") -> int:
        """Generic SQL deletion query.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = ANY(%s)"
        return self.query_exec(container, query, (entities,))

    def sql_delete_one(self, container: ConnectionContainer, table: str,
                       entity: EntityKey, entity_key: str = "id") -> int:
        """Generic SQL deletion query for a single row.

        See :py:meth:`sql_select` for thoughts on this.

        :returns: number of affected rows
        """
        query = f"DELETE FROM {table} WHERE {entity_key} = %s"
        return self.query_exec(container, query, (entity,))

    def sql_defer_constraints(self, container: ConnectionContainer, *constraints: str,
                              ) -> DefaultReturnCode:
        """Helper for deferring the given constraints for the current transaction."""
        query = f"SET CONSTRAINTS {', '.join(constraints)} DEFERRED"
        return self.query_exec(container, query, ())
