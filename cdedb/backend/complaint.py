#!/usr/bin/env python3
import datetime
from collections.abc import Collection
from typing import Any, Optional, Protocol

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import (
    AbstractBackend,
    Silencer,
    access,
    affirm_dataclass,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    affirm_validation_optional as affirm_optional,
    singularize,
)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    RequestState,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryScope
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer


class ComplaintBackend(AbstractBackend):
    realm = "complaint"

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        # Temporary for now
        return "core_admin" in rs.user.roles
        # return super().is_admin(rs)

    @access("core_admin")
    def case_log(self, rs: RequestState, code: const.ComplaintLogCodes,
                 case_id: Optional[int], persona_id: Optional[int] = None,
                 change_note: Optional[str] = None) -> int:
        """Make an entry in the log for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "case_id": case_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "complaint.log", data)

    @access("core_admin")
    def retrieve_log(self, rs: RequestState, log_filter: ComplaintLogFilter,
                          ) -> CdEDBLog:
        """Get recorded activity for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(ComplaintLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)




