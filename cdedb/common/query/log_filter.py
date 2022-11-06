import dataclasses
import datetime
import decimal
import enum
from typing import Iterator, Optional, Type, cast

import cdedb.database.constants as const
from cdedb.common import diacritic_patterns
from cdedb.config import LazyConfig
from cdedb.database.query import DatabaseValue_s

_CONFIG = LazyConfig()


class LogTable(enum.Enum):
    core_log = "core.log"
    core_changelog = "core.changelog"
    cde_finance_log = "cde.finance_log"
    cde_log = "cde.log"
    past_event_log = "past_event.log"
    event_log = "event.log"
    assembly_log = "assembly.log"
    ml_log = "ml.log"

    def get_log_code_class(self) -> Type[enum.IntEnum]:
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
        return {
            self.core_changelog: ("reviewed_by", "generation",),
            self.cde_finance_log: ("delta", "new_balance", "members", "total",),
            self.past_event_log: ("pevent_id",),
            self.event_log: ("event_id",),
            self.ml_log: ("mailinglist_id",),
            self.assembly_log: ("assembly_id",),
        }.get(cast(str, self), ())


@dataclasses.dataclass(frozen=True)
class OptionalDatetimeRange:
    val_from: Optional[datetime.datetime] = dataclasses.field(default=None)
    val_to: Optional[datetime.datetime] = dataclasses.field(default=None)

    def __bool__(self) -> bool:
        """Truthy if any of the values is truthy"""
        return any(self)

    def __iter__(self) -> Iterator[Optional[datetime.datetime]]:
        """Enable Tuple unpacking."""
        return iter((self.val_from, self.val_to))


@dataclasses.dataclass(frozen=True)
class OptionalIntRange:
    val_from: Optional[int] = dataclasses.field(default=None)
    val_to: Optional[int] = dataclasses.field(default=None)

    def __bool__(self) -> bool:
        """Truthy if any of the values is truthy"""
        return any(self)

    def __iter__(self) -> Iterator[Optional[int]]:
        """Enable Tuple unpacking."""
        return iter((self.val_from, self.val_to))


@dataclasses.dataclass(frozen=True)
class OptionalDecimalRange:
    val_from: Optional[decimal.Decimal] = dataclasses.field(default=None)
    val_to: Optional[decimal.Decimal] = dataclasses.field(default=None)

    def __bool__(self) -> bool:
        """Truthy if any of the values is truthy"""
        return any(self)

    def __iter__(self) -> Iterator[Optional[decimal.Decimal]]:
        """Enable Tuple unpacking."""
        return iter((self.val_from, self.val_to))


@dataclasses.dataclass(frozen=True)
class LogFilter:
    # The log that is being retrieved.
    table: LogTable
    # Generic attributes available for all logs.
    codes: list[int] = dataclasses.field(default_factory=list)
    offset: Optional[int] = dataclasses.field(default=None)
    length: int = dataclasses.field(default=0)  # Set default in post_init.
    persona_id: Optional[int] = dataclasses.field(default=None)
    submitted_by: Optional[int] = dataclasses.field(default=None)
    change_note: Optional[str] = dataclasses.field(default=None)
    ctime: OptionalDatetimeRange = dataclasses.field(
        default_factory=OptionalDatetimeRange)
    # changelog only
    reviewed_by: Optional[int] = dataclasses.field(default=None)
    # event and ml only
    entity_ids: list[int] = dataclasses.field(default_factory=list)
    # finance only
    delta: OptionalDecimalRange = dataclasses.field(
        default_factory=OptionalDecimalRange)
    new_balance: OptionalDecimalRange = dataclasses.field(
        default_factory=OptionalDecimalRange)
    total: OptionalDecimalRange = dataclasses.field(
        default_factory=OptionalDecimalRange)
    members: OptionalIntRange = dataclasses.field(
        default_factory=OptionalIntRange)

    def __post_init__(self) -> None:
        """Modify offset and length values used in the frontend to ensure valid SQL."""
        if not self.length:
            object.__setattr__(self, 'length', _CONFIG['DEFAULT_LOG_LENGTH'])
        if self.offset and self.offset < 0:
            # Avoid non-positive lengths
            if -self.offset < self.length:
                object.__setattr__(self, 'length', self.length + self.offset)
            object.__setattr__(self, 'offset', 0)

    def to_sql(self) -> tuple[str, tuple[DatabaseValue_s, ...]]:
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

        # Special column for core.changelog
        if self.table == LogTable.core_changelog:
            if self.reviewed_by:
                conditions.append("reviewed_by = %s")
                params.append(self.reviewed_by)
        elif self.table == LogTable.assembly_log:
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
        elif self.table == LogTable.cde_finance_log:
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

        return f"WHERE {' AND '.join(conditions)}" if conditions else "", tuple(params)
