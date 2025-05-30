#!/usr/bin/env python3

import collections
import datetime
from collections.abc import Collection
from typing import Any, Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import (
    CdEDBObject,
    GenesisDecision,
    RequestState,
    determine_age_class,
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
    def complaint_index(self, rs: RequestState) -> Response:
        return self.render(rs, "complaint/index", {})

    @access("core_admin")
    def show_case(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        persona_ids = rs.ambience['case'].get_persona_ids()
        personas = self.coreproxy.get_personas(rs, persona_ids)
        age_classes = {}
        for persona_id, persona in personas.items():
            if persona['is_event_realm'] and rs.ambience['case'].start_date:
                age_classes[persona_id] = determine_age_class(
                    self.coreproxy.get_event_user(rs, persona_id)['birthday'],
                    rs.ambience['case'].start_date,
                )
        descriptions = self.complaintproxy.get_visible_descriptions(rs, case_id)
        log_filter = ComplaintLogFilter(case_id=case_id)
        log_entries = self.complaintproxy.retrieve_log(rs, log_filter)
        # events = rs.ambience['case'].list_events(log_entries)
        return self.render(
            rs,
            "complaint/show_case",
            {
                'personas': personas,
                'descriptions': descriptions,
                'age_classes': age_classes,
                'log_entries': log_entries,
            },
        )

    @access("core_admin")
    def create_case_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "complaint/configure_case", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=True))
    @REQUESTdata("appellant_id", "is_affected", "affected_ids", "target_ids", "info")
    def create_case(
        self,
        rs: RequestState,
        data: dict[str, Any],
        appellant_id: int,
        is_affected: bool,
        affected_ids: Optional[Collection[int]],
        target_ids: Optional[Collection[int]],
        info: str,
    ) -> Response:
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        with TransactionObserver(rs, self, "create_complaint_case"):
            new_case = self.complaintproxy.create_case(rs, data)
            # Add involvees to the case
            # Add first entry with info as text
        rs.notify_return_code(bool(new_case))
        return self.redirect(rs, "complaint/show_case", {'case_id': new_case.id})

    @access("core_admin")
    def change_case_form(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['case'].as_dict())
        return self.render(rs, "complaint/configure_case", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=False))
    def change_case(
        self, rs: RequestState, case_id: int, data: dict[str, Any]
    ) -> Response:
        if rs.has_validation_errors():
            return self.change_case_form(rs, case_id)
        ret = self.complaintproxy.set_case(rs, case_id, data)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @access("core_admin", modi={"POST"})
    def unlock_case(self, rs: RequestState, case_id: int) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        persona_ids = rs.ambience['case'].get_persona_ids()
        personas = self.coreproxy.get_personas(rs, persona_ids)
        descriptions = self.complaintproxy.unlock_case(rs, case_id)
        rs.notify_return_code(1)
        # Do maybe not redirect here?
        return self.render(
            rs,
            "complaint/show_case",
            {'personas': personas, 'descriptions': descriptions},
        )

    @access("core_admin")
    @REQUESTdata("entry_type", "parent_id")
    def add_entry_form(
        self,
        rs: RequestState,
        case_id: int,
        entry_type: Optional[const.ComplaintEntryType],
        parent_id: Optional[int],
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if parent_id:
            parent = rs.ambience['case'].entries[parent_id]
            available_types = parent.entry_type.possible_children
        else:
            et = const.ComplaintEntryType
            available_types = set(et) - et.get_root_map().keys()
        return self.render(
            rs,
            "complaint/configure_entry",
            {
                'entry_type': entry_type,
                'parent_id': parent_id,
                'available_types': available_types,
            },
        )

    @access("core_admin", modi={"POST"})
    @REQUESTdatadict(*models.ComplaintEntry.requestdict_fields(creation=True))
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
        data: dict[str, Any],
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if rs.has_validation_errors():
            # TODO Deal with validation errors here?
            return self.add_entry_form(rs, case_id, entry_type=data.get('entry_type'),
                                       parent_id=data.get('parent_id'))
        # TODO Solve this somehow
        entry_data = version_data = data
        entry = self.complaintproxy.add_entry(rs, case_id, entry_data, version_data)
        rs.notify_return_code(bool(entry))
        return self.redirect(rs, "core/show_case", {'entry': entry})

    @access("core_admin")
    def replace_entry_form(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        rs.ignore_validation_errors()
        personas = {}
        if rs.ambience['entry'].concerned_id:
            personas = self.coreproxy.get_personas(rs, {rs.ambience['entry'].concerned_id})
        return self.render(
            rs,
            "complaint/configure_entry",
            {'entry_type': rs.ambience['entry'].entry_type, 'personas': personas},
        )

    @access("core_admin", modi={"POST"})
    @REQUESTdata("dreason")
    @REQUESTdatadict(*models.ComplaintEntry.requestdict_fields(creation=False))
    def replace_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
        data: dict[str, Any],
        dreason: str | None,
    ) -> Response:
        if rs.has_validation_errors():
            return self.replace_entry_form(rs, case_id, data['id'])
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        entry = self.complaintproxy.replace_entry_version(rs, data['id'], data, dreason)
        rs.notify_return_code(1)
        return self.redirect(rs, "core/show_case", {'entry': entry})

    @access("core_admin")
    def remove_entry_form(
        self, rs: RequestState, case_id: int, entry_id: int
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        return self.render(rs, "complaint/remove_entry", {})

    @access("core_admin", modi={"POST"})
    @REQUESTdata("entry_id", "dreason")
    def remove_entry(
        self, rs: RequestState, case_id: int, entry_id: int, dreason: str | None
    ) -> Response:
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        ret = self.complaintproxy.delete_entry(rs, entry_id)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", {})

    @REQUESTdatadict(*ComplaintLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("core_admin")
    def view_complaint_log(
        self, rs: RequestState, data: CdEDBObject, download: bool
    ) -> Response:
        """View activities."""
        return self.generic_view_log(
            rs,
            data,
            ComplaintLogFilter,
            self.complaintproxy.retrieve_log,
            download=download,
            template="complaint/view_complaint_log",
        )
