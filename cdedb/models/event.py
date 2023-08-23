"""Dataclass definitions for the event realm."""

import dataclasses
from typing import TYPE_CHECKING, Any, Optional

import cdedb.common.validation.types as vtypes
from cdedb.common import unwrap
from cdedb.common.query import QueryScope, QuerySpec, QuerySpecEntry
from cdedb.common.sorting import Sortkey
from cdedb.common.validation.types import TypeMapping
from cdedb.models.common import CdEDataclass

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.common import CdEDBObject  # pylint: disable=ungrouped-imports

@dataclasses.dataclass
class CustomQueryFilter(CdEDataclass):
    event_id: vtypes.ID
    scope: QueryScope
    title: str
    notes: Optional[str]
    field: str  # TODO: create a new more specific type? Probably unnecessary, because this is constrained by existing query fields anyway.

    database_table = "event.custom_query_filters"

    fixed_fields = ("event_id", "scope")

    @classmethod
    def validation_fields(cls, *, creation: bool) -> tuple[TypeMapping, TypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        for key in cls.fixed_fields:
            if key in optional:
                del optional[key]
        return mandatory, optional

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        data['scope'] = QueryScope(data['scope'])
        return cls(**data)  # TODO: use super instead.

    @property
    def split_fields(self) -> list[str]:
        return self.field.split(',')

    def add_to_spec(self, spec: QuerySpec, scope: QueryScope) -> None:
        if self.scope != scope:
            return
        split_fields = self.field.split(",")
        if any(f not in spec for f in split_fields):
            return
        types = {spec[f].type for f in split_fields}
        if len(types) != 1:
            return
        spec[self.field] = QuerySpecEntry(unwrap(types), self.title)

    def get_sortkey(self) -> Sortkey:
        return (self.event_id, self.scope, self.title)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.get_sortkey() < other.get_sortkey()
