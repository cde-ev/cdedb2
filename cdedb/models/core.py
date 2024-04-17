"""Dataclass definitions of core realm."""

import dataclasses
from typing import Collection, Optional

import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject
from cdedb.database.constants import EmailDefectStatus
from cdedb.models.common import CdEDataclass, CdEDataclassMap


@dataclasses.dataclass
class DefectAddress(CdEDataclass):
    address: vtypes.Email
    status: EmailDefectStatus
    notes: Optional[str] = None
    # This persona has this address as username.
    user_id: Optional[vtypes.ID] = None
    # This persona has this address as explicit mail address for at least one ml.
    subscriber_id: Optional[vtypes.ID] = None
    # The mailinglists where this address is used as explicit address.
    ml_ids: set[vtypes.ID] = dataclasses.field(default_factory=set)

    database_table = "core.defect_addresses"

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "DefectAddress":
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
