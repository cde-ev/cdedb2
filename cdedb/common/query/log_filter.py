"""Provide a dataclass for validating and passing parameters for log filtering."""

import dataclasses
import datetime
import decimal
import enum  # pylint: disable=unused-import
from typing import ClassVar, Collection, Optional, Type

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, diacritic_patterns
from cdedb.common.validation.types import TypeMapping
from cdedb.config import LazyConfig
from cdedb.database.query import DatabaseValue_s
from cdedb.filter import cdedbid_filter
from cdedb.models.common import requestdict_field_spec

__all__ = [
    'GenericLogFilter', 'CoreLogFilter', 'CdELogFilter', 'ChangelogLogFilter',
    'FinanceLogFilter', 'AssemblyLogFilter', 'EventLogFilter', 'MlLogFilter',
    'PastEventLogFilter',
]

_CONFIG = LazyConfig()
_DEFAULT_LOG_COLUMNS = (
    "id", "ctime", "code", "submitted_by", "persona_id", "change_note",
)
_DEFAULT_PERSONA_COLUMNS = (
    "persona_id", "submitted_by",
)


@dataclasses.dataclass
class GenericLogFilter:
    """Dataclass to validate, pass and process filter parameters for querying a log.

    Everything except for the table should be optional.

    This can be created from a dict of parameters by the validation, using the type
    annotations to validate the parameters.
    """
    log_table: ClassVar[str]
    log_code_class: ClassVar["Type[enum.IntEnum]"]
    additional_columns: ClassVar[tuple[str, ...]] = ()
    additional_persona_columns: ClassVar[tuple[str, ...]] = ()

    # Pagination parameters.
    offset: Optional[int] = None  # How many entries to skip at the start.
    _offset: Optional[int] = dataclasses.field(default=None)  # Unmodified offset.
    length: int = 0  # How many entries to list. Set default in post_init.
    _length: int = dataclasses.field(default=0)  # Unmodified length.

    # Generic attributes available for all logs.
    codes: list[int] = dataclasses.field(default_factory=list)  # Log codes to filter.
    persona_id: Optional[int] = None  # ID of the affected user.
    submitted_by: Optional[int] = None  # ID of the active user.
    change_note: Optional[str] = None  # Additional notes.
    # Range for the log timestamp.
    ctime_from: Optional[datetime.datetime] = None
    ctime_to: Optional[datetime.datetime] = None

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

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        """Create a list of SQL conditions and the corresponding parameters."""
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
        if self.ctime_from:
            conditions.append("ctime >= %s")
            params.append(self.ctime_from)
        if self.ctime_to:
            conditions.append("ctime <= %s")
            params.append(self.ctime_to)

        return conditions, params

    def to_sql_condition(self) -> tuple[str, tuple[DatabaseValue_s, ...]]:
        """Return a SQL-string from the filter sttributes and a sequence of parameters.

        The string will be empty if no conditions exist.
        Otherwise it includes the WHERE.
        """
        conditions, params = self._get_sql_conditions()
        return f"WHERE {' AND '.join(conditions)}" if conditions else "", tuple(params)

    @classmethod
    def get_columns(cls) -> tuple[str, ...]:
        """Get a list of columns in the respective log table."""
        return _DEFAULT_LOG_COLUMNS + cls.additional_columns

    @classmethod
    def get_columns_str(cls) -> str:
        """Get a comma-separated list of columns to select from the log table."""
        return ", ".join(cls.get_columns())

    @classmethod
    def requestdict_fields(cls) -> list[tuple[str, str]]:
        """Determine which fields should be extracted from the request.

        For use with `REQUESTdatadict` or `request_dict_extractor`.
        """
        return [
            (field.name, requestdict_field_spec(field))
            for field in dataclasses.fields(cls)
            if field.name not in ("_offset", "_length")
        ]

    def to_validation(self) -> CdEDBObject:
        """Turn an instance of the dataclass into a dict, that can be validated.

        Because CdEDB-ID validation is not idempotent, we need to fix some data.
        """
        ret = dataclasses.asdict(self)
        for k in self.get_persona_columns():
            ret[k] = cdedbid_filter(ret[k])
        return ret

    @classmethod
    def validation_fields(cls) -> tuple[TypeMapping, TypeMapping]:
        """Create a specification for validating the dataclass.

        Returns two dicts, with mandatory and optional keys respectively.
        Some type annotations differ slightly from the validation type.
        """
        mandatory: TypeMapping = {'length': int}
        optional: TypeMapping = {
            field.name: field.type for field in dataclasses.fields(cls)
        }
        del optional['length']
        optional['codes'] = list[cls.log_code_class]  # type: ignore[name-defined]
        for k in cls.get_persona_columns():
            optional[k] = Optional[vtypes.CdedbID]  # type: ignore[assignment]
        return mandatory, optional

    @classmethod
    def get_persona_columns(cls) -> tuple[str, ...]:
        """Determine which filter attributes are persona ids."""
        return _DEFAULT_PERSONA_COLUMNS + cls.additional_persona_columns

    @classmethod
    def get_persona_ids(cls, log_entries: Collection[CdEDBObject]) -> set[int]:
        """Extract a set of all persona ids in the given log entries."""
        ret: set[int] = set()
        for k in cls.get_persona_columns():
            ret.update(e[k] for e in log_entries if e[k])
        return ret


@dataclasses.dataclass
class CoreLogFilter(GenericLogFilter):
    log_table = "core.log"
    log_code_class = const.CoreLogCodes


@dataclasses.dataclass
class CdELogFilter(GenericLogFilter):
    log_table = "cde.log"
    log_code_class = const.CdeLogCodes


@dataclasses.dataclass
class ChangelogLogFilter(GenericLogFilter):
    log_table = "core.changelog"
    log_code_class = const.PersonaChangeStati
    additional_columns = ("reviewed_by", "generation", "automated_change",)
    additional_persona_columns = ("reviewed_by",)

    reviewed_by: Optional[int] = None  # ID of the reviewer.

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.reviewed_by:
            conditions.append("reviewed_by = %s")
            params.append(self.reviewed_by)

        return conditions, params


@dataclasses.dataclass
class AssemblyLogFilter(GenericLogFilter):
    log_table = "assembly.log"
    log_code_class = const.AssemblyLogCodes
    additional_columns = ("assembly_id",)

    assembly_id: Optional[int] = None
    _assembly_ids: list[int] = dataclasses.field(default_factory=list)

    def assembly_ids(self) -> list[int]:
        if self.assembly_id:
            return [self.assembly_id]
        return self._assembly_ids

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.assembly_ids():
            conditions.append("assembly_id = ANY(%s)")
            params.append(self.assembly_ids())

        return conditions, params


@dataclasses.dataclass
class EventLogFilter(GenericLogFilter):
    log_table = "event.log"
    log_code_class = const.EventLogCodes
    additional_columns = ("event_id", "droid_id")

    event_id: Optional[int] = None
    _event_ids: list[int] = dataclasses.field(default_factory=list)
    droid_id: Optional[int] = None

    def event_ids(self) -> list[int]:
        if self.event_id:
            return [self.event_id]
        return self._event_ids

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.event_ids():
            conditions.append("event_id = ANY(%s)")
            params.append(self.event_ids())
        if self.droid_id:
            conditions.append("droid_id = %s")
            params.append(self.droid_id)

        return conditions, params


@dataclasses.dataclass
class MlLogFilter(GenericLogFilter):
    log_table = "ml.log"
    log_code_class = const.MlLogCodes
    additional_columns = ("mailinglist_id",)

    mailinglist_id: Optional[int] = None
    _mailinglist_ids: list[int] = dataclasses.field(default_factory=list)

    def mailinglist_ids(self) -> list[int]:
        if self.mailinglist_id:
            return [self.mailinglist_id]
        return self._mailinglist_ids

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.mailinglist_ids():
            conditions.append("mailinglist_id = ANY(%s)")
            params.append(self.mailinglist_ids())

        return conditions, params


@dataclasses.dataclass
class PastEventLogFilter(GenericLogFilter):
    log_table = "past_event.log"
    log_code_class = const.PastEventLogCodes
    additional_columns = ("pevent_id",)

    pevent_id: Optional[int] = None
    _pevent_ids: list[int] = dataclasses.field(default_factory=list)

    def pevent_ids(self) -> list[int]:
        if self.pevent_id:
            return [self.pevent_id]
        return self._pevent_ids

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.pevent_ids():
            conditions.append("pevent_id = ANY(%s)")
            params.append(self.pevent_ids())

        return conditions, params


@dataclasses.dataclass
class FinanceLogFilter(GenericLogFilter):
    log_table = "cde.finance_log"
    log_code_class = const.FinanceLogCodes
    additional_columns = (
        "delta", "new_balance", "transaction_date", "members", "total",
    )

    delta_from: Optional[decimal.Decimal] = None
    delta_to: Optional[decimal.Decimal] = None

    new_balance_from: Optional[decimal.Decimal] = None
    new_balance_to: Optional[decimal.Decimal] = None

    transaction_date_from: Optional[datetime.date] = None
    transaction_date_to: Optional[datetime.date] = None

    total_from: Optional[decimal.Decimal] = None
    total_to: Optional[decimal.Decimal] = None

    members_from: Optional[int] = None
    members_to: Optional[int] = None

    def _get_sql_conditions(self) -> tuple[list[str], list[DatabaseValue_s]]:
        conditions, params = super()._get_sql_conditions()

        if self.delta_from:
            conditions.append("delta >= %s")
            params.append(self.delta_from)
        if self.delta_to:
            conditions.append("delta <= %s")
            params.append(self.delta_to)

        if self.new_balance_from:
            conditions.append("new_balance >= %s")
            params.append(self.new_balance_from)
        if self.new_balance_to:
            conditions.append("new_balance <= %s")
            params.append(self.new_balance_to)

        if self.transaction_date_from:
            conditions.append("transaction_date >= %s")
            params.append(self.transaction_date_from)
        if self.transaction_date_to:
            conditions.append("transaction_date <= %s")
            params.append(self.transaction_date_to)

        if self.total_from:
            conditions.append("total >= %s")
            params.append(self.total_from)
        if self.total_to:
            conditions.append("total <= %s")
            params.append(self.total_to)

        if self.members_from:
            conditions.append("members >= %s")
            params.append(self.members_from)
        if self.members_to:
            conditions.append("members <= %s")
            params.append(self.members_to)

        return conditions, params


ALL_LOG_FILTERS: tuple[Type[GenericLogFilter], ...] = (
    CoreLogFilter,
    CdELogFilter,
    ChangelogLogFilter,
    FinanceLogFilter,
    AssemblyLogFilter,
    EventLogFilter,
    MlLogFilter,
    PastEventLogFilter,
)
