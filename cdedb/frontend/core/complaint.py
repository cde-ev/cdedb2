#!/usr/bin/env python3

import collections
import datetime
from typing import Any, Collection, Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
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
    TransactionObserver,
    access,
    check_validation as check,
    periodic,
)
from cdedb.frontend.core.base import CoreBaseFrontend


class CoreComplaintMixin(CoreBaseFrontend):

    @access("core_admin")
    def show_case(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        return self.render(rs, "complaint/show_case", {})

    @access("core_admin")
    def create_case_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "configure_case", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=True))
    @REQUESTdata("involved", "info")
    def create_case(self, rs: RequestState, data: dict[str, Any],
                    involved: Collection[int], info: str) -> Response:
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        with TransactionObserver(rs, self, "create_complaint_case"):
            new_id = self.complaintproxy.create_case(rs, data)
            # Add involvees to the case
            # Add first entry with info as text
        rs.notify_return_code(new_id)
        return self.redirect(rs, "complaint/show_case", {
            'case_id': new_id})

    @access("core_admin")
    def change_case_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "change_case", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=False))
    def change_case(self, rs: RequestState, data: dict[str, Any]) -> Response:
        if rs.has_validation_errors():
            return self.change_case_form(rs)
        ret = self.complaintproxy.set_case(rs, data)
        rs.notify_return_code(ret)
        return self.redirect(rs, "complaint/show_case")

    @access("core_admin")
    def add_entry_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "complaint/configure_entry", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.ComplaintEntry.requestdict_fields(creation=True))
    def add_entry(self, rs: RequestState, data: dict[str, Any]) -> Response:
        if rs.has_validation_errors():
            return self.add_entry_form(rs)
        entry = self.complaintproxy.add_entry(rs, data)
        rs.notify_return_code(1)
        return self.redirect(rs, "complaint/show_case", {'entry': entry})

    @access("core_admin")
    def replace_entry_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "complaint/configure_entry", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.ComplaintEntry.requestdict_fields(creation=False))
    def replace_entry(self, rs: RequestState, data: dict[str, Any]) -> Response:
        if rs.has_validation_errors():
            return self.replace_entry_form(rs)
        entry = self.complaintproxy.replace_entry(rs, data)
        rs.notify_return_code(1)
        return self.redirect(rs, "complaint/show_case", {'entry': entry})

    @access("core_admin", modi={"POST"})
    @REQUESTdata("entry_id")
    def remove_entry(self, rs: RequestState, entry_id: int) -> Response:
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        entry = self.complaintproxy.delete_entry(rs, entry_id)
        rs.notify_return_code(1)
        return self.redirect(rs, "complaint/show_case", {'entry': entry})

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
