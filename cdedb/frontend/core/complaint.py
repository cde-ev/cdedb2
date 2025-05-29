#!/usr/bin/env python3

import collections
import datetime
from typing import Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject,
    GenesisDecision,
    RequestState,
    get_mandatory_form_fields,
    merge_dicts,
    now,
)
from cdedb.common.fields import REALM_SPECIFIC_GENESIS_FIELDS
from cdedb.common.n_ import n_
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.common.validation.validate import (
    GENESIS_CASE_EXPOSED_FIELDS,
    PERSONA_COMMON_FIELDS,
)
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    access,
    check_validation as check,
    periodic,
)
from cdedb.frontend.core.base import CoreBaseFrontend

class CoreComplaintMixin(CoreBaseFrontend):

    @access("core_admin")
    def show_case(self, rs: RequestState, case_id: int) -> Response:
        raise werkzeug.exceptions.NotFound(n_("Endpoint not implemented."))

    @REQUESTdatadict(*ComplaintLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin")
    def view_case_log(self, rs: RequestState, data: CdEDBObject, download: bool
                      ) -> Response:
        """View activities."""
        return self.generic_view_log(
            rs, data, ComplaintLogFilter, self.complaintproxy.retrieve_log,
            download=download, template="complaint/view_case_log"
        )
