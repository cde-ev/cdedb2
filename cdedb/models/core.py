"""Dataclass definitions of core realm."""

import dataclasses
from typing import Any, Optional

import cdedb.common.validation.types as vtypes
from cdedb.models.common import CdEDataclass

CdEDBObject = dict[str, Any]


@dataclasses.dataclass
class DefectAddress(CdEDataclass):
    address: vtypes.Email
    notes: Optional[str] = None
    # This persona has this address as username.
    user_id: Optional[vtypes.ID] = None
    # This persona has this address as explicit mail address for at least one ml.
    subscriber_id: Optional[dict[vtypes.ID, set[vtypes.ID]]] = None
    # The mailinglists where this address is used as explicit address.
    ml_ids: set[vtypes.ID] = dataclasses.field(default_factory=set)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "DefectAddress":
        data["id"] = None
        if "ml_ids" in data:
            data["ml_ids"] = set(data["ml_ids"])
        return super().from_database(data)

    @property
    def persona_ids(self) -> set[vtypes.ID]:
        """All persona ids associated with this defect address."""
        ret = set()
        if self.user_id:
            ret.add(self.user_id)
        if self.subscriber_id:
            ret.add(self.subscriber_id)
        return ret
