#!/usr/bin/env python3

import collections
import datetime
from collections.abc import Collection
from typing import Any, Optional, cast

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import (
    CdEDBObject,
    RequestState,
    determine_age_class,
    merge_dicts,
    now,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    TransactionObserver,
    access,
    check_validation as check,
    extract_and_check_dataclass_validation as extract_and_check_dataclass,
    periodic,
    request_dict_extractor,
    request_extractor,
)
from cdedb.frontend.core.base import CoreBaseFrontend


class CoreComplaintMixin(CoreBaseFrontend):
    @access("complaint_admin")
    def complaint_index(self, rs: RequestState) -> Response:
        return self.render(rs, "complaint/index", {})

    @access("complaint_admin")
    def show_case(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        # Collect all entries to be displayed.
        log_filter = ComplaintLogFilter(case_id=case_id)
        _, log_entries = self.complaintproxy.retrieve_log(rs, log_filter)
        log_entries = log_entries or tuple()
        all_entries = rs.ambience['case'].list_entries(log_entries)

        # Collect all persona data which may be displayed.
        persona_ids = rs.ambience['case'].get_persona_ids(log_entries)
        personas = self.coreproxy.get_personas(rs, persona_ids)
        age_classes = {}
        for persona_id, persona in personas.items():
            if persona['is_event_realm'] and rs.ambience['case'].start_date:
                age_classes[persona_id] = determine_age_class(
                    self.coreproxy.get_event_user(rs, persona_id)['birthday'],
                    rs.ambience['case'].start_date,
                )

        # Collect descriptions separately as a privacy precaution
        is_locked = True
        if self.complaintproxy.is_unlocked(rs, case_id):
            is_locked = False
            descriptions = self.complaintproxy.unlock_case(rs, case_id)
        else:
            descriptions = self.complaintproxy.get_visible_descriptions(rs, case_id)

        return self.render(
            rs,
            "complaint/show_case",
            {
                'personas': personas,
                'descriptions': descriptions,
                'age_classes': age_classes,
                'all_entries': all_entries,
                'is_locked': is_locked,
            },
        )

    @access("complaint_admin")
    def create_case_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "complaint/configure_case", {})

    @access("complaint_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=True))
    @REQUESTdata(
        "appellant_id", "is_affected", "affected_ids", "target_ids", "timestamp", "info"
    )
    def create_case(
        self,
        rs: RequestState,
        data: dict[str, Any],
        appellant_id: vtypes.CdedbID,
        is_affected: bool,
        affected_ids: Optional[vtypes.CdedbIDList],
        target_ids: Optional[vtypes.CdedbIDList],
        timestamp: datetime.datetime,
        info: str,
    ) -> Response:
        # TODO validation
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        with TransactionObserver(rs, self, "create_complaint_case"):
            new_case = self.complaintproxy.create_case(rs, data)
            entry_data = {
                'entry_type': const.ComplaintEntryType.initial_information,
            }
            version_data = {
                'timestamp': timestamp,
                'authors': {rs.user.persona_id},
                'description': info,
            }
            ret = self.complaintproxy.add_entry(
                rs, new_case.id, entry_data, version_data
            )
            t = const.ComplaintInvolvementType
            if is_affected:
                ret *= self.complaintproxy.add_involved(
                    rs, new_case.id, t.appellant, [appellant_id]
                )
            else:
                ret *= self.complaintproxy.add_involved(
                    rs,
                    new_case.id,
                    t.affected,
                    [appellant_id],
                    is_informed=True,
                )
            if affected_ids:
                ret *= self.complaintproxy.add_involved(
                    rs, new_case.id, t.affected, affected_ids
                )
            if target_ids:
                ret *= self.complaintproxy.add_involved(
                    rs, new_case.id, t.target, target_ids
                )
        rs.notify_return_code(ret * bool(new_case))
        return self.redirect(rs, "core/show_case", {'case_id': new_case.id})

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("involvement_type", "persona_ids")
    def add_involved(
        self,
        rs: RequestState,
        case_id: int,
        involvement_type: const.ComplaintInvolvementType,
        persona_ids: vtypes.CdedbIDList,
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if set(persona_ids) & rs.ambience['case'].all_involved.keys():
            rs.notify('info', n_("Some of these users were already involved."))
        if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=None):
            rs.append_validation_error((
                "persona_ids",
                ValueError(n_("Some of these users do not exist.")),
            ))
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.add_involved(
            rs, case_id, involvement_type, persona_ids
        )
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin", modi={"POST"})
    def remove_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if persona_id not in rs.ambience['case'].all_involved.keys():
            rs.notify("info", "This user is not involved.")
            return self.redirect(rs, "core/show_case", {'case_id': case_id})
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.remove_involved(rs, case_id, [persona_id])
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin", modi={"POST"})
    def inform_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if persona_id not in rs.ambience['case'].all_involved:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is not involved.")),
            ))
        if persona_id in rs.ambience['case'].informed_involved:
            rs.notify('info', n_("This user is already marked as uninformed.."))
            return self.redirect(rs, "core/show_case", {'case_id': case_id})
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.set_involved_informed(rs, case_id, persona_id, True)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin", modi={"POST"})
    def uninform_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if persona_id not in rs.ambience['case'].informed_involved:
            rs.notify('info', n_("This user is already marked as uninformed.."))
            return self.redirect(rs, "core/show_case", {'case_id': case_id})
        if persona_id not in rs.ambience['case'].all_involved:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is not involved.")),
            ))
        # elif check informed state
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        else:
            self.complaintproxy.set_involved_informed(rs, case_id, persona_id, False)
            return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin")
    def manage_companions_form(
        self, rs: RequestState, case_id: int, involved_id: int
    ) -> Response:
        return self.render(rs, "complaint/manage_companions")

    @access("complaint_admin")
    def change_case_form(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['case'].as_dict())
        return self.render(rs, "complaint/configure_case")

    @access("complaint_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=False))
    def change_case(
        self, rs: RequestState, case_id: int, data: dict[str, Any]
    ) -> Response:
        if rs.has_validation_errors():
            return self.change_case_form(rs, case_id)
        ret = self.complaintproxy.set_case(rs, case_id, data)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def unlock_case(self, rs: RequestState, case_id: int) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        _ = self.complaintproxy.unlock_case(rs, case_id)
        rs.notify_return_code(1, success=n_("Case unlocked."))
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin", modi={"POST"})
    def lock_case(self, rs: RequestState, case_id: int) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        code = self.complaintproxy.lock_case(rs, case_id)
        rs.notify_return_code(code, success=n_("Case locked."))
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin")
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
        rs.ignore_validation_errors()
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

    @access("complaint_admin", modi={"POST"})
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        entry_data = (
            extract_and_check_dataclass(rs, models.ComplaintEntry, creation=True) or {}
        )
        version_data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=True,
            entry_type=entry_data.get('entry_type'),
        )
        if rs.has_validation_errors() or not entry_data or not version_data:
            return self.add_entry_form(
                rs,
                case_id,
                entry_type=entry_data.get('entry_type') if entry_data else None,
                parent_id=entry_data.get('parent_id') if entry_data else None,
            )
        entry_id = self.complaintproxy.add_entry(rs, case_id, entry_data, version_data)
        rs.notify_return_code(entry_id)
        return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))

    @access("complaint_admin")
    def replace_entry_form(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if (
            rs.ambience['entry'].entry_type.is_hidden
            and not self.complaintproxy.is_unlocked(rs, case_id)
        ):  # fmt: skip
            rs.notify('error', n_("Need to unlock case before replacing entry."))
            return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))
        rs.ignore_validation_errors()
        if not rs.ambience['entry'].active_version:
            rs.notify('error', n_("Can not replace deleted entry."))
            self.redirect(rs, "core/show_case", {'case_id': case_id})
        assert rs.ambience['entry'].active_version is not None
        merge_dicts(
            rs.values,
            rs.ambience['entry'].active_version.as_dict(),
        )
        personas = {}
        if rs.ambience['entry'].concerned_id:
            personas = self.coreproxy.get_personas(
                rs, {rs.ambience['entry'].concerned_id}
            )
        return self.render(
            rs,
            "complaint/configure_entry",
            {'entry_type': rs.ambience['entry'].entry_type, 'personas': personas},
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("dreason")
    def replace_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
        dreason: str,
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=False,
            entry_type=rs.ambience['entry'].entry_type,
        )
        if rs.has_validation_errors() or not data:
            return self.replace_entry_form(rs, case_id, entry_id)
        ret = self.complaintproxy.replace_entry_version(rs, entry_id, data, dreason)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))

    @access("complaint_admin")
    def remove_entry_form(
        self, rs: RequestState, case_id: int, entry_id: int
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")

        version_id = rs.ambience['entry'].active_version.id
        description = None
        if rs.ambience['entry'].entry_type.is_hidden:
            if not self.complaintproxy.is_unlocked(rs, case_id):
                msg = n_("Need to unlock case before removing entry.")
                rs.notify('error', msg)
                return self.redirect(
                    rs, "core/show_case", anchor="entry" + str(entry_id)
                )
            else:
                description = self.complaintproxy.unlock_case(rs, case_id)[version_id]
        elif rs.ambience['entry'].entry_type.has_description:
            description = self.complaintproxy.get_visible_descriptions(rs, case_id)[
                version_id
            ]
        concerned = self.coreproxy.get_persona(rs, rs.ambience['entry'].concerned_id)
        authors = self.coreproxy.get_personas(
            rs, rs.ambience['entry'].active_version.authors
        ).values()
        return self.render(
            rs,
            "complaint/remove_entry",
            {'authors': authors, 'concerned': concerned, 'description': description},
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("entry_id", "dreason")
    def remove_entry(
        self, rs: RequestState, case_id: int, entry_id: int, dreason: str
    ) -> Response:
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")
        ret = self.complaintproxy.delete_entry(rs, entry_id, dreason)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @REQUESTdatadict(*ComplaintLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("complaint_admin")
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
