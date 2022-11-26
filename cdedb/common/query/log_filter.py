"""Provide a dataclass for validating and passing parameters for log filtering."""

import dataclasses
import datetime
import decimal
import enum
import typing
from typing import Any, Optional, Type, Union, cast

import cdedb.database.constants as const
from cdedb.common import CdEDBObject, diacritic_patterns
from cdedb.config import LazyConfig
from cdedb.database.query import DatabaseValue_s

_CONFIG = LazyConfig()
_DEFAULT_LOG_COLUMNS = (
    "id", "ctime", "code", "submitted_by", "persona_id", "change_note")


# Use this TypeAlias where both a LogFilter and a dict, that can be turned into a
# LogFilter by validation is acceptable.
LogFilterLike = Union["LogFilter", CdEDBObject]
LogFilterChangelogLike = Union["LogFilterChangelog", CdEDBObject]
LogFilterEntityLogLike = Union["LogFilterEntityLog", CdEDBObject]
LogFilterFinanceLogLike = Union["LogFilterFinanceLog", CdEDBObject]


class LogTable(enum.Enum):
    """Enum containing all the different log tables.

    Has a few helper methods providing additional data depending on the table.
    """
    core_log = "core.log"
    core_changelog = "core.changelog"
    cde_finance_log = "cde.finance_log"
    cde_log = "cde.log"
    past_event_log = "past_event.log"
    event_log = "event.log"
    assembly_log = "assembly.log"
    ml_log = "ml.log"

    def get_log_code_class(self) -> Type[enum.IntEnum]:
        """Map each log table to the corresponsing LogCode class."""
        return {
            self.core_log: const.CoreLogCodes,
            self.core_changelog: const.MemberChangeStati,
            self.cde_finance_log: const.FinanceLogCodes,
            self.cde_log: const.CdeLogCodes,
            self.past_event_log: const.PastEventLogCodes,
            self.event_log: const.EventLogCodes,
            self.assembly_log: const.AssemblyLogCodes,
            self.ml_log: const.MlLogCodes,
        }[cast(str, self)]

    def get_additional_columns(self) -> tuple[str, ...]:
        """Provide a list of non-default columns for every table."""
        return {
            self.core_changelog: ("reviewed_by", "generation", "automated_change",),
            self.cde_finance_log: ("delta", "new_balance", "members", "total",),
            self.past_event_log: ("pevent_id",),
            self.event_log: ("event_id",),
            self.ml_log: ("mailinglist_id",),
            self.assembly_log: ("assembly_id",),
        }.get(cast(str, self), ())

    def get_filter_class(self) -> "Type[LogFilter]":
        """Map log tables to appropriate filter class."""
        return {
            self.core_changelog: LogFilterChangelog,
            self.assembly_log: LogFilterEntityLog,
            self.event_log: LogFilterEntityLog,
            self.past_event_log: LogFilterEntityLog,
            self.ml_log: LogFilterEntityLog,
            self.cde_finance_log: LogFilterFinanceLog,
        }.get(cast(str, self), LogFilter)


# Some Types for storing range filters. Basically just two-element tuples of a common
# (optional) type.

OptionalDatetimeRange = typing.NamedTuple("OptionalDatetimeRange", [
    ("from_val", Optional[datetime.datetime]), ("to_val", Optional[datetime.datetime]),
])
OptionalDecimalRange = typing.NamedTuple("OptionalDecimalRange", [
    ("from_val", Optional[decimal.Decimal]), ("to_val", Optional[decimal.Decimal]),
])
OptionalIntRange = typing.NamedTuple("OptionalIntRange", [
    ("from_val", Optional[int]), ("to_val", Optional[int]),
])


@dataclasses.dataclass
class LogFilter:
    """Dataclass to validate, pass and process filter parameters for querying a log.

    Everything except for the table should be optional.

    This can be created from a dict of parameters by the validation, using the type
    annotations to validate the parameters.
    """
    # The log that is being retrieved.
    table: LogTable

    # Pagination parameters.
    offset: Optional[int] = None
    _offset: Optional[int] = dataclasses.field(default=None)  # Unmodified offset.
    length: int = 0  # Set default in post_init.
    _length: int = dataclasses.field(default=0)  # Unmodified length.

    # Generic attributes available for all logs.
    codes: list[int] = dataclasses.field(default_factory=list)
    persona_id: Optional[int] = None
    submitted_by: Optional[int] = None
    change_note: Optional[str] = None
    ctime: tuple[Optional[datetime.datetime],
                 Optional[datetime.datetime]] = (None, None)

    def __post_init__(self) -> None:
        """Do a little processing on the data.

         Use setattr workaround because of frozen dataclass.
         """
        if not self.length:
            self.length = _CONFIG['DEFAULT_LOG_LENGTH']
        # Remember original length and offset for pagination.
        self._length = self.length
        self._offset = self.offset
        # Fix offset and length to ensure valid SQL.
        if self.offset and self.offset < 0:
            # Avoid non-positive lengths
            if -self.offset < self.length:
                self.length = self.length + self.offset
            self.offset = 0

    def get(self, name: str, default: Any) -> Any:
        """Emulate dict access."""
        return self.__dict__.get(name, default)

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        """Create a SQL condition string from parameters.

        The condition string is empty if there is no filter condition. Otherwise it
        includes the "WHERE".

        Returns the condition string and a tuple of parameters used in that condition.
        """
        conditions = []
        params: list[DatabaseValue_s] = []
        if self.codes:
            conditions.append("code = ANY(%s)")
            params.append(self.codes)
        if self.persona_id:
            conditions.append("persona_id = %s")
            params.append(self.persona_id)
        if self.submitted_by:
            conditions.append("submitted_by = %s")
            params.append(self.submitted_by)
        if self.change_note:
            conditions.append("change_note ~* %s")
            params.append(diacritic_patterns(self.change_note))
        if self.ctime:
            ctime_from, ctime_to = self.ctime
            if ctime_from:
                conditions.append("ctime >= %s")
                params.append(ctime_from)
            if ctime_to:
                conditions.append("ctime <= %s")
                params.append(ctime_to)

        return conditions, params

    def to_sql_condition(self) -> tuple[str, tuple[DatabaseValue_s, ...]]:
        conditions, params = self._get_sql_conditions()
        return f"WHERE {' AND '.join(conditions)}" if conditions else "", tuple(params)

    def get_columns(self) -> str:
        """Get a comma-separated list of columns to select from the log table."""
        return ", ".join(_DEFAULT_LOG_COLUMNS + self.table.get_additional_columns())


@dataclasses.dataclass
class LogFilterChangelog(LogFilter):
    # changelog only
    reviewed_by: Optional[int] = None

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        # Special column for core.changelog
        if self.table == LogTable.core_changelog:
            if self.reviewed_by:
                conditions.append("reviewed_by = %s")
                params.append(self.reviewed_by)

        return conditions, params


@dataclasses.dataclass
class LogFilterEntityLog(LogFilter):
    # assembly, event, past_event, ml
    entity_ids: list[int] = dataclasses.field(default_factory=list)

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.table == LogTable.assembly_log:
            if self.entity_ids:
                conditions.append("assembly_id = ANY(%s)")
                params.append(self.entity_ids)
        elif self.table == LogTable.event_log:
            if self.entity_ids:
                conditions.append("event_id = ANY(%s)")
                params.append(self.entity_ids)
        elif self.table == LogTable.ml_log:
            if self.entity_ids:
                conditions.append("mailinglist_id = ANY(%s)")
                params.append(self.entity_ids)
        elif self.table == LogTable.past_event_log:
            if self.entity_ids:
                conditions.append("pevent_id = ANY(%s)")
                params.append(self.entity_ids)

        return conditions, params


@dataclasses.dataclass
class LogFilterFinanceLog(LogFilter):
    # finance only
    delta: tuple[Optional[decimal.Decimal], Optional[decimal.Decimal]] = (None, None)
    new_balance: tuple[Optional[decimal.Decimal],
                       Optional[decimal.Decimal]] = (None, None)
    total: tuple[Optional[decimal.Decimal], Optional[decimal.Decimal]] = (None, None)
    members: tuple[Optional[int], Optional[int]] = (None, None)

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.table == LogTable.cde_finance_log:
            if self.delta:
                delta_from, delta_to = self.delta
                if delta_from:
                    conditions.append("delta >= %s")
                    params.append(delta_from)
                if delta_to:
                    conditions.append("delta <= %s")
                    params.append(delta_to)
            if self.new_balance:
                new_balance_from, new_balance_to = self.new_balance
                if new_balance_from:
                    conditions.append("new_balance >= %s")
                    params.append(new_balance_from)
                if new_balance_to:
                    conditions.append("new_balance <= %s")
                    params.append(new_balance_to)
            if self.total:
                total_from, total_to = self.total
                if total_from:
                    conditions.append("total >= %s")
                    params.append(total_from)
                if total_to:
                    conditions.append("total <= %s")
                    params.append(total_to)
            if self.members:
                members_from, members_to = self.members
                if members_from:
                    conditions.append("members >= %s")
                    params.append(members_from)
                if members_to:
                    conditions.append("members <= %s")
                    params.append(members_to)

        return conditions, params
