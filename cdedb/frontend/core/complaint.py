#!/usr/bin/env python3

import collections
import copy
import datetime
import itertools
from collections.abc import Collection
from typing import Any, Optional, Sequence, cast

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
from cdedb.common.query import QueryOperators, QueryScope, QuerySpecEntry
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.filter import cdedbid_filter
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

CASE_SEARCH_DEFAULTS = {
    'qsel_cases.summary': True,
    'qop_cases.summary': QueryOperators.match,
    'qsel_cases.is_grave': True,
    'qop_cases.is_grave': QueryOperators.equal,
    'qsel_cases.kind': True,
    'qop_cases.kind': QueryOperators.equal,
    'qop_involved.persona_id': QueryOperators.equal,
    'qop_involved.involvement_type': QueryOperators.equal,
    'qop_involved.is_informed': QueryOperators.equal,
    'qop_companion.companion_persona_id': QueryOperators.equal,
    'qop_companion.is_withdrawn': QueryOperators.equal,
}


class CoreComplaintMixin(CoreBaseFrontend):
    @access("complaint_admin")
    @REQUESTdata("is_search")
    def complaint_index(self, rs: RequestState, is_search: bool) -> Response:
        rs.ignore_validation_errors()
        defaults = copy.deepcopy(CASE_SEARCH_DEFAULTS)
        scope = QueryScope.complaint_case
        spec = scope.get_spec()

        result: Optional[Sequence[CdEDBObject]] = None
        count = 0
        invisible_cases = 0

        if not is_search:
            cases = personas = unlocked_cases = None
        else:
            # our query facility does not allow + signs, thus special-case it here
            query = check(
                rs,
                vtypes.QueryInput,
                scope.mangle_query_input(rs, defaults),
                "query",
                spec=spec,
                separator=" ",
            )
            if rs.has_validation_errors():
                return self.complaint_index(rs, is_search=False)
            query.fields_of_interest = ['cases.id', 'access.is_unlocked']
            result = self.complaintproxy.submit_general_query(rs, query)
            count = len(result)
            if count == 1:
                case_id = result[0][query.scope.get_primary_key()]
                return self.redirect(rs, "core/show_case", {'case_id': case_id})
            else:
                case_ids = [e['cases.id'] for e in result]
                unlocked_cases = {
                    e['cases.id'] for e in result if e['access.is_unlocked']
                }
                cases = self.complaintproxy.get_cases(rs, case_ids)

                # Exclude invisible cases
                cases = {
                    case_id: case
                    for case_id, case in cases.items()
                    if case.is_visible_for(rs.user)
                }
                if count > len(cases):
                    rs.notify(
                        "warning",
                        n_("%(count)s cases not shown."),
                        {"count": count - len(cases)},
                    )
                    # TODO Send email to complaint admins

                persona_ids = []
                for case in cases.values():
                    persona_ids.extend(case.all_involved.keys())
                personas = self.coreproxy.get_personas(rs, persona_ids)

        return self.render(
            rs,
            "complaint/index",
            {
                'spec': spec,
                'cases': cases,
                'count': count,
                'personas': personas,
                'unlocked_cases': unlocked_cases,
            },
        )

    @access("complaint_admin")
    @REQUESTdata("show_log_entries")
    def show_case(
        self, rs: RequestState, case_id: int, show_log_entries: bool = False
    ) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        # Collect all entries to be displayed.
        log_entries = tuple()
        if show_log_entries:
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
                'show_log_entries': show_log_entries,
            },
        )

    @access("complaint_admin")
    def case_history(self, rs: RequestState, case_id: int) -> Response:
        """Show all entry versions for a case."""
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not self.complaintproxy.is_unlocked(rs, case_id):
            rs.notify('error', n_("Need to unlock case first."))
            return self.redirect(rs, "core/show_case", {'case_id': case_id})

        log_filter = ComplaintLogFilter(case_id=case_id)
        _, log_entries = self.complaintproxy.retrieve_log(rs, log_filter)
        log_entries = log_entries or tuple()
        all_entries = rs.ambience['case'].list_entries(
            log_entries, include_deleted=True
        )
        descriptions = self.complaintproxy.get_all_descriptions(rs, case_id)
        # Collect all persona data which may be displayed.
        persona_ids = rs.ambience['case'].get_persona_ids(log_entries)
        personas = self.coreproxy.get_personas(rs, persona_ids)

        return self.render(
            rs,
            "complaint/case_history",
            {
                'descriptions': descriptions,
                'all_entries': all_entries,
                'personas': personas,
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
        if rs.user.persona_id in set(affected_ids) | set(target_ids) | {appellant_id}:
            rs.notify('error', n_("May not create case with own involvement."))
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if rs.user.persona_id in persona_ids:
            rs.notify('error', n_("May not add own involvement."))
            return self.create_case_form(rs)
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if persona_id not in rs.ambience['case'].all_involved:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is not involved.")),
            ))
        if persona_id in rs.ambience['case'].informed_involved:
            rs.notify('info', n_("This user is already marked as uninformed."))
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if persona_id not in rs.ambience['case'].informed_involved:
            rs.notify('info', n_("This user is already marked as uninformed."))
            return self.redirect(rs, "core/show_case", {'case_id': case_id})
        if persona_id not in rs.ambience['case'].all_involved:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is not involved.")),
            ))
        # elif check informed state
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.set_involved_informed(rs, case_id, persona_id, False)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", {'case_id': case_id})

    @access("complaint_admin")
    def manage_companions_form(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        companion_ids = rs.ambience['case'].companions_by_involved.get(persona_id)
        companions = (
            self.coreproxy.get_personas(rs, companion_ids) if companion_ids else {}
        )
        involved = self.coreproxy.get_persona(rs, persona_id)
        return self.render(
            rs,
            "complaint/manage_companions",
            {
                'involved': involved,
                'companions': companions,
            },
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("companion_ids")
    def add_companions(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_ids: vtypes.CdedbIDList,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if set(companion_ids) & rs.ambience['case'].companions.keys():
            rs.notify('info', n_("Some of these users were already companions."))
        if persona_id in companion_ids:
            rs.append_validation_error((
                "companion_ids",
                ValueError(n_("User may not be their own companion.")),
            ))
        if not self.coreproxy.verify_ids(rs, companion_ids, is_archived=None):
            rs.append_validation_error((
                "companion_ids",
                ValueError(n_("Some of these users do not exist.")),
            ))
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.add_companions(rs, case_id, persona_id, companion_ids)
        rs.notify_return_code(ret)
        return self.redirect(
            rs,
            "core/manage_companions_form",
            {'case_id': case_id, 'persona_id': persona_id},
        )

    @access("complaint_admin", modi={"POST"})
    def remove_companion(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_id: int,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if companion_id not in rs.ambience['case'].companions:
            rs.notify("info", "This user is no companion.")
            return self.redirect(
                rs,
                "core/manage_companions_form",
                {'case_id': case_id, 'persona_id': persona_id},
            )
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.remove_companions(
            rs, case_id, persona_id, [companion_id]
        )
        rs.notify_return_code(ret)
        return self.redirect(
            rs,
            "core/manage_companions_form",
            {'case_id': case_id, 'persona_id': persona_id},
        )

    @access("complaint_admin", modi={"POST"})
    def withdraw_companion(
        self, rs: RequestState, case_id: int, persona_id: int, companion_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if companion_id not in rs.ambience['case'].companions:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is no companion.")),
            ))
        if companion_id in rs.ambience['case'].withdrawn_companions:
            rs.notify('info', n_("This companion is already marked as withdrawn."))
            return self.redirect(rs, "core/show_case", {'case_id': case_id})
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.set_companion_withdrawn(
            rs, case_id, persona_id, companion_id, True
        )
        rs.notify_return_code(ret)
        return self.redirect(
            rs,
            "core/manage_companions_form",
            {'case_id': case_id, 'persona_id': persona_id},
        )

    @access("complaint_admin", modi={"POST"})
    def reinstate_companion(
        self,
        rs: RequestState,
        case_id: int,
        persona_id: int,
        companion_id: int,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        if companion_id not in rs.ambience['case'].companions:
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user is no companion.")),
            ))
        if companion_id not in rs.ambience['case'].withdrawn_companions:
            rs.notify('info', n_("This companion is already marked as active."))
            return self.redirect(
                rs,
                "core/manage_companions_form",
                {'case_id': case_id, 'persona_id': persona_id},
            )
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        ret = self.complaintproxy.set_companion_withdrawn(
            rs, case_id, persona_id, companion_id, False
        )
        rs.notify_return_code(ret)
        return self.redirect(
            rs,
            "core/manage_companions_form",
            {'case_id': case_id, 'persona_id': persona_id},
        )

    @access("complaint_admin")
    def change_case_form(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        merge_dicts(rs.values, rs.ambience['case'].as_dict())
        return self.render(rs, "complaint/configure_case")

    @access("complaint_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=False))
    def change_case(
        self, rs: RequestState, case_id: int, data: dict[str, Any]
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.change_case_form(rs, case_id)
        ret = self.complaintproxy.set_case(rs, case_id, data)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def unlock_case(self, rs: RequestState, case_id: int) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        rs.ignore_validation_errors()
        et = const.ComplaintEntryType
        if parent_id:
            parent = rs.ambience['case'].entries[parent_id]
            available_types = parent.entry_type.possible_children - {
                et.revocation_explanation
            }
            if not parent.active_version:
                rs.notify('info', n_("Can not add child for deleted parent."))
                return self.redirect(rs, "core/show_case")
        else:
            available_types = set(et) - et.all_children()
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
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
        if parent_id := entry_data.get('parent_id'):
            if not rs.ambience['case'].entries[parent_id].active_version:
                rs.notify('info', n_("Can not add child for deleted parent."))
                return self.redirect(rs, "core/show_case")
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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
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
        # Rerender the input as CSV of DB-IDs
        authors: list[str] = list(
            map(
                lambda x: cdedbid_filter(x) if isinstance(x, int) else x,
                rs.values.getlist('authors'),
            )
        )
        rs.values['authors'] = ", ".join(authors)

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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=False,
            entry_type=rs.ambience['entry'].entry_type,
        )
        if rs.has_validation_errors() or not data:
            return self.replace_entry_form(rs, case_id, entry_id)
        if not rs.ambience['entry'].active_version:
            rs.notify('error', n_("Can not replace deleted entry."))
            self.redirect(rs, "core/show_case", {'case_id': case_id})
        ret = self.complaintproxy.replace_entry_version(rs, entry_id, data, dreason)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))

    @access("complaint_admin")
    def revoke_entry_form(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        rs.ignore_validation_errors()
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")
        return self.render(
            rs,
            "complaint/configure_entry",
            {'entry_type': const.ComplaintEntryType.revocation_explanation},
        )

    @access("complaint_admin", modi={"POST"})
    def revoke_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")
        version_data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=True,
            entry_type=const.ComplaintEntryType.revocation_explanation,
        )
        if rs.has_validation_errors() or not version_data:
            return self.revoke_entry_form(rs, case_id, entry_id)
        new_entry_id = self.complaintproxy.revoke_entry(rs, entry_id, version_data)
        rs.notify_return_code(new_entry_id)
        return self.redirect(rs, "core/show_case", anchor="entry" + str(new_entry_id))

    @access("complaint_admin")
    def remove_entry_form(
        self, rs: RequestState, case_id: int, entry_id: int
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")
        if rs.ambience['entry'].active_children:
            rs.notify('error', n_("Entry has active children."))
            return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))

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

        concerned = None
        if concerned_id := rs.ambience['entry'].concerned_id:
            concerned = self.coreproxy.get_persona(rs, concerned_id)

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
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.remove_entry_form(rs, case_id, entry_id)
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already deleted."))
            return self.redirect(rs, "core/show_case")
        if rs.ambience['entry'].active_children:
            rs.notify('error', n_("Entry has active children."))
            return self.redirect(rs, "core/show_case", anchor="entry" + str(entry_id))
        ret = self.complaintproxy.delete_entry(rs, entry_id, dreason)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", "complaint.enforcer")
    def measures(self, rs: RequestState) -> Response:
        """Search for active measures against a persona."""
        return self.render(rs, "complaint/measures")

    @access("complaint_admin", "complaint.enforcer")
    def show_user_measures(self, rs: RequestState, persona_id: int) -> Response:
        """View active measures against a persona."""
        measures = self.complaintproxy.get_measures(rs, persona_id)
        return self.render(rs, "complaint/show_user_measures", {'measures': measures})

    @access("complaint_admin", "complaint.enforcer", "complaint.monitor")
    def list_complaint_helpers(self, rs: RequestState) -> Response:
        """View list of enforcers and monitors."""
        return self.render(rs, "complaint/list_complaint_helpers")

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
