#!/usr/bin/env python3
import copy
import datetime
from itertools import chain
from typing import Any, Optional

import werkzeug.exceptions
from markupsafe import Markup
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    RequestState,
    ValidationWarning,
    determine_age_class,
    make_persona_name,
    merge_dicts,
)
from cdedb.common.n_ import n_
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.filter import cdedbid_filter
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    TransactionObserver,
    access,
    check_validation as check,
    extract_and_check_dataclass_validation as extract_and_check_dataclass,
)
from cdedb.frontend.core.base import CoreBaseFrontend

CASE_SEARCH_DEFAULTS = {
    'qop_cases.summary': QueryOperators.match,
    'qop_cases.is_grave': QueryOperators.equal,
    'qop_cases.kind': QueryOperators.equal,
    'qop_status.is_confirmed': QueryOperators.equal,
    'qop_status.is_closed': QueryOperators.equal,
    # transpired after
    'qop_cases.end_date': QueryOperators.greaterornull,
    # transpired before
    'qop_cases.start_date': QueryOperators.lessornull,
    'qop_involved.persona_id': QueryOperators.equal,
    'qop_involved.involved_type': QueryOperators.equal,
    'qop_involved.is_informed': QueryOperators.equal,
    'qop_companion.companion_persona_id': QueryOperators.equal,
    'qop_companion.is_withdrawn': QueryOperators.equal,
}


def entry_link(rs: RequestState, entry_id: int) -> str:
    # Unfortunately redirecting kills this link :(
    # return safe_filter(f'<a href="#entry{entry_id}">{rs.gettext("Entry")}</a>')
    return rs.gettext("Entry")


class CoreComplaintMixin(CoreBaseFrontend):
    @access("complaint_admin")
    @REQUESTdata("is_search", "last_entry_after", "last_entry_before")
    def complaint_index(
        self,
        rs: RequestState,
        is_search: bool,
        last_entry_after: datetime.datetime | None = None,
        last_entry_before: datetime.datetime | None = None,
    ) -> Response:
        rs.ignore_validation_errors()
        defaults = copy.deepcopy(CASE_SEARCH_DEFAULTS)
        scope = QueryScope.complaint_case
        spec = scope.get_spec()

        if not is_search:
            count = 0
            cases = personas = unlocked_cases = None
        else:
            query_input: dict[str, Any] = scope.mangle_query_input(rs, defaults)
            # Manually mangle the last changed information
            if last_entry_after and last_entry_before:
                query_input['qop_status.last_entry'] = QueryOperators.between
                query_input['qval_status.last_entry'] = (
                    f"{last_entry_after};{last_entry_before}"
                )
            elif last_entry_after:
                query_input['qop_status.last_entry'] = QueryOperators.greater
                query_input['qval_status.last_entry'] = last_entry_after
            elif last_entry_before:
                query_input['qop_status.last_entry'] = QueryOperators.less
                query_input['qval_status.last_entry'] = last_entry_before

            query = check(
                rs,
                vtypes.QueryInput,
                query_input,
                "query",
                spec=spec,
                allow_empty=True,
                separator=";",
            )

            if query:
                # Disallow empty search to encourage restrictive search
                if not query.constraints:
                    rs.notify('error', n_("Need to fill out at least one field."))
                    return self.complaint_index(rs, is_search=False)
                # Disallow search for own persona id
                for field, _, value in query.constraints:
                    if field == 'involved.persona_id' and value == rs.user.persona_id:
                        rs.append_validation_error((
                            'qval_involved.persona_id',
                            ValueError(n_("May not search for own involvement.")),
                        ))
                        # Change this for continue once there are multiple such checks
                        break

            if rs.has_validation_errors():
                return self.complaint_index(rs, is_search=False)
            assert query is not None
            query.fields_of_interest = [
                'cases.id',
                'status.is_unlocked',
            ]
            result = self.complaintproxy.submit_general_query(rs, query)
            count = len(result)

            case_ids = [e['cases.id'] for e in result]
            unlocked_cases = {e['cases.id'] for e in result if e['status.is_unlocked']}
            _cases = self.complaintproxy.get_cases(rs, case_ids)

            # Exclude invisible cases
            cases = {
                case_id: case
                for case_id, case in _cases.items()
                if case.is_visible_for(rs.user)
            }
            if count == len(cases) == 1:
                case_id = result[0][query.scope.get_primary_key()]
                return self.redirect(rs, "core/show_case", {'case_id': case_id})
            else:
                if count > len(cases):
                    rs.notify(
                        "warning",
                        n_("%(count)s cases not shown."),
                        {"count": count - len(cases)},
                    )
                    persona_id = check(
                        rs,
                        vtypes.CdedbID,
                        query_input['qval_involved.persona_id'],
                        passthrough=True,
                    )
                    rs.ignore_validation_errors()
                    if persona_id:
                        # This is a compromise between alertness and not spamming
                        # the log too much: We log only if the requestee has identified
                        # some involved people in their cases.
                        for concealed_case_id in _cases.keys() - cases.keys():
                            self.complaintproxy.complaint_log_case_detected(
                                rs, case_id=concealed_case_id, persona_id=persona_id
                            )

                persona_ids: set[int] = set()
                for case in cases.values():
                    persona_ids.update(case.all_involved.keys())
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
        log_entries: tuple[dict[str, Any], ...] = tuple()
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
        descriptions = self.complaintproxy.get_visible_descriptions(rs, case_id)
        if self.complaintproxy.is_unlocked(rs, case_id):
            is_locked = False
            descriptions.update(
                self.complaintproxy.get_hidden_descriptions(rs, case_id)
            )

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
            return self.redirect(rs, "core/show_case")

        log_filter = ComplaintLogFilter(case_id=case_id)
        _, log_entries = self.complaintproxy.retrieve_log(rs, log_filter)
        log_entries = log_entries or tuple()
        all_entries = rs.ambience['case'].list_entries(
            log_entries, include_deleted=True
        )
        descriptions = self.complaintproxy.get_hidden_descriptions(rs, case_id)
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
        mandatory_fields = models.Case.mandatory_form_fields(creation=True)
        mandatory_fields |= {'timestamp', 'info'}
        return self.render(rs, "complaint/configure_case", {}, mandatory_fields)

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
        if rs.has_validation_errors():
            return self.create_case_form(rs)
        if rs.user.persona_id in set(affected_ids) | set(target_ids) | {appellant_id}:  # type: ignore[arg-type]
            rs.notify('error', n_("May not create case with own involvement."))
            return self.create_case_form(rs)

        error = ValueError(n_("May not be involved in multiple ways."))
        if affected_ids and appellant_id in affected_ids:
            rs.append_validation_error(('appellant_id', error))
            rs.append_validation_error(('affected_ids', error))
        if target_ids and appellant_id in target_ids:
            rs.append_validation_error(('appellant_id', error))
            rs.append_validation_error(('target_ids', error))
        if affected_ids and target_ids and set(affected_ids) & set(target_ids):
            rs.append_validation_error(('affected_ids', error))
            rs.append_validation_error(('target_ids', error))
        if rs.has_validation_errors():
            return self.create_case_form(rs)

        with TransactionObserver(rs, self, "create_complaint_case"):
            new_case = self.complaintproxy.create_case(rs, data)
            entry_data = {
                'entry_type': const.ComplaintEntryType.generic_information,
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
                    rs, new_case.id, t.affected, [appellant_id], is_informed=True
                )
            else:
                ret *= self.complaintproxy.add_involved(
                    rs, new_case.id, t.appellant, [appellant_id]
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
        return self.redirect(rs, "core/show_case", {"case_id": new_case.id})

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
        if persona_ids:
            if rs.user.persona_id in persona_ids:
                rs.append_validation_error((
                    "persona_ids",
                    ValueError(n_("May not add own involvement.")),
                ))
            if any(
                set(persona_ids) & involved
                for inv_type, involved in rs.ambience['case'].involved.items()
                if inv_type != involvement_type
            ):
                rs.append_validation_error((
                    "persona_ids",
                    ValueError(
                        n_("Some of these users are already involved otherwise.")
                    ),
                ))

            if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=None):
                rs.append_validation_error((
                    "persona_ids",
                    ValueError(n_("Some of these users do not exist.")),
                ))
        elif persona_ids is not None:
            rs.append_validation_error((
                "persona_ids",
                ValueError(n_("Must not be empty.")),
            ))
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)

        active_companions = rs.ambience['case'].active_companions
        ex_companions_ids = set(persona_ids) & active_companions.keys()
        ex_companions = self.coreproxy.get_personas(rs, ex_companions_ids)
        for companion_id, companion in ex_companions.items():
            rs.notify(
                'warning',
                n_("%(companion)s was a companion and is now marked as withdrawn."),
                {'companion': make_persona_name(companion)},
            )
            for persona_id in active_companions[companion_id]:
                self.complaintproxy.set_companion_withdrawn(
                    rs, case_id, persona_id, companion_id, is_withdrawn=True
                )

        ret = self.complaintproxy.add_involved(
            rs, case_id, involvement_type, persona_ids
        )
        rs.notify_return_code(
            ret, info=n_("Some of these users were already involved.")
        )
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def remove_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        ret = self.complaintproxy.remove_involved(rs, case_id, [persona_id])
        rs.notify_return_code(ret, info=n_("This user was not involved."))
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def inform_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if persona_id not in rs.ambience['case'].all_involved:
            rs.notify("error", n_("This user is not involved."))
        else:
            ret = self.complaintproxy.set_involved_informed(
                rs, case_id, persona_id, True
            )
            rs.notify_return_code(
                ret, info=n_("This user was already marked as uninformed.")
            )
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def uninform_involved(
        self, rs: RequestState, case_id: int, persona_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if persona_id not in rs.ambience['case'].all_involved:
            rs.notify("error", n_("This user is not involved."))
        # elif check informed state
        else:
            ret = self.complaintproxy.set_involved_informed(
                rs, case_id, persona_id, False
            )
            rs.notify_return_code(
                ret, info=n_("This user was already marked as uninformed.")
            )
        return self.redirect(rs, "core/show_case")

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
        if companion_ids:
            if companion_ids & rs.ambience['case'].all_involved.keys():
                rs.append_validation_error((
                    "companion_ids",
                    ValueError(n_("Companion may not be involved.")),
                ))
            if set(companion_ids) & rs.ambience['case'].adverse_companions(
                rs.ambience['case'].all_involved[persona_id]
            ):
                rs.append_validation_error((
                    "companion_ids",
                    ValueError(n_("Companion to the opposing party.")),
                ))
            if not self.coreproxy.verify_ids(rs, companion_ids, is_archived=None):
                rs.append_validation_error((
                    "companion_ids",
                    ValueError(n_("Some of these users do not exist.")),
                ))
        elif companion_ids is not None:
            rs.append_validation_error((
                "companion_ids",
                ValueError(n_("Must not be empty.")),
            ))
        if rs.has_validation_errors():
            return self.manage_companions_form(rs, case_id, persona_id)
        ret = self.complaintproxy.add_companions(rs, case_id, persona_id, companion_ids)
        rs.notify_return_code(
            ret, info=n_("Some of these users were already companions.")
        )
        return self.redirect(rs, "core/manage_companions_form")

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
        ret = self.complaintproxy.remove_companions(
            rs, case_id, persona_id, [companion_id]
        )
        rs.notify_return_code(ret, info=n_("This user was no companion."))
        return self.redirect(rs, "core/manage_companions_form")

    @access("complaint_admin", modi={"POST"})
    def withdraw_companion(
        self, rs: RequestState, case_id: int, persona_id: int, companion_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if companion_id not in rs.ambience['case'].companions:
            rs.notify("error", n_("This user is no companion."))
        else:
            ret = self.complaintproxy.set_companion_withdrawn(
                rs, case_id, persona_id, companion_id, True
            )
            rs.notify_return_code(
                ret, info=n_("This companion was already marked as withdrawn.")
            )
        return self.redirect(rs, "core/manage_companions_form")

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
        if companion_id not in rs.ambience['case'].companions:
            rs.notify("error", n_("This user is no companion."))
        elif companion_id in rs.ambience['case'].all_involved.keys():
            rs.notify("error", n_("Active companion may not be involved."))
        else:
            ret = self.complaintproxy.set_companion_withdrawn(
                rs, case_id, persona_id, companion_id, False
            )
            rs.notify_return_code(
                ret, info=n_("This companion was already marked as active.")
            )
        return self.redirect(rs, "core/manage_companions_form")

    @access("complaint_admin")
    def change_case_form(self, rs: RequestState, case_id: int) -> Response:
        """Render form."""
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        merge_dicts(rs.values, rs.ambience['case'].as_dict())
        mandatory_fields = models.Case.mandatory_form_fields(creation=False)
        return self.render(rs, "complaint/configure_case", {}, mandatory_fields)

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
    @REQUESTdata("reason", "show_log_entries")
    def unlock_case(
        self, rs: RequestState, case_id: int, reason: str, show_log_entries: bool
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        code = self.complaintproxy.unlock_case(rs, case_id, reason)
        rs.notify_return_code(code, success=n_("Case unlocked."))
        return self.redirect(
            rs, "core/show_case", {"show_log_entries": show_log_entries}
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("show_log_entries")
    def lock_case(
        self, rs: RequestState, case_id: int, show_log_entries: bool
    ) -> Response:
        if rs.has_validation_errors():
            return self.show_case(rs, case_id)
        code = self.complaintproxy.lock_case(rs, case_id)
        rs.notify_return_code(code, success=n_("Case locked."))
        return self.redirect(
            rs, "core/show_case", {"show_log_entries": show_log_entries}
        )

    def _get_entry_personas(
        self, rs: RequestState, entry: models.ComplaintEntry
    ) -> CdEDBObjectMap:
        """Get any personas associated to a given entry."""
        persona_ids: set[int] = set()
        if entry.active_version:
            persona_ids.update(entry.active_version.authors)
            persona_ids.add(entry.active_version.submitted_by)
        if entry.concerned_id:
            persona_ids.add(entry.concerned_id)
        return self.coreproxy.get_personas(rs, persona_ids)

    @access("complaint_admin")
    @REQUESTdata("entry_type")
    def add_entry_form(
        self,
        rs: RequestState,
        case_id: int,
        entry_type: const.ComplaintEntryType | None,
        parent_id: int | None = None,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        """Render form."""
        # The check that the entry belongs to the case is already done in
        #  `reconnoitre_ambience`, which raises a "404 Not Found" in this case.
        rs.ignore_validation_errors()
        et = const.ComplaintEntryType
        if parent_id:
            parent = rs.ambience['entry']
            if not parent.active_version:
                rs.notify('error', n_("Can not add child for deleted parent."))
                return self.redirect(rs, "core/show_case")
            available_types = parent.entry_type.possible_children - {
                et.revocation_explanation
            }
            personas = self._get_entry_personas(rs, parent)
        else:
            available_types = set(et) - et.all_children()
            personas = {}
        return self.render(
            rs,
            "complaint/configure_entry",
            {
                'entry_type': entry_type,
                'parent_id': parent_id,
                'available_types': available_types,
                'personas': personas,
            },
            models.ComplaintEntry.mandatory_form_fields(creation=True),
        )

    def _append_author_validation_warning(
        self, rs: RequestState, authors: set[int]
    ) -> None:
        """Warn to not misuse author field.

        This check is intentionally omitted on replacement, to not be too annoying"""
        if authors & rs.ambience['case'].all_involved.keys() and not rs.ignore_warnings:
            msg = n_("Should not include involved people.")
            rs.append_validation_error(('authors', ValidationWarning(msg)))

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("entry_type")
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_type: const.ComplaintEntryType,
        parent_id: int | None = None,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        entry_data = (
            extract_and_check_dataclass(
                rs,
                models.ComplaintEntry,
                additional_data={'parent_id': parent_id},
                creation=True,
                entries=rs.ambience['case'].entries,
                passthrough=True,
            )
            or {}
        )
        version_data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=True,
            entry_type=entry_type,
        )
        if version_data:
            self._append_author_validation_warning(rs, version_data.get('authors', {}))

        if rs.has_validation_errors() or not entry_data or not version_data:
            return self.add_entry_form(
                rs,
                case_id,
                entry_type=entry_type,
                parent_id=parent_id,
            )
        if parent_id := entry_data.get('parent_id'):
            if not rs.ambience['case'].entries[parent_id].active_version:
                rs.notify('error', n_("Can not add child for deleted parent."))
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
        internal: bool = False,
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not rs.ambience['entry'].active_version:
            rs.notify(
                'error',
                n_("Can not replace deleted %(entry_link)s."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")
        if (
            rs.ambience['entry'].entry_type.is_hidden
            and not self.complaintproxy.is_unlocked(rs, case_id)
            and not internal
        ):  # fmt: skip
            rs.notify(
                'error',
                n_("Need to unlock case before replacing %(entry_link)s."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")

        version_id = rs.ambience['entry'].active_version.id
        if rs.ambience['entry'].entry_type.has_description and not internal:
            if rs.ambience['entry'].entry_type.is_hidden:
                description = self.complaintproxy.get_hidden_descriptions(rs, case_id)[
                    version_id
                ]
            else:
                description = self.complaintproxy.get_visible_descriptions(rs, case_id)[
                    version_id
                ]
            rs.values['description'] = description

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
            models.ComplaintEntry.mandatory_form_fields(creation=False),
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
            return self.replace_entry_form(rs, case_id, entry_id, internal=True)
        if not rs.ambience['entry'].active_version:
            rs.notify(
                'error',
                n_("Cannot replace deleted %(entry_link)s."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            anchor = ""
        else:
            ret = self.complaintproxy.replace_entry_version(rs, entry_id, data, dreason)
            rs.notify_return_code(ret)
            anchor = f"entry{entry_id}"
        return self.redirect(rs, "core/show_case", anchor=anchor)

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
        entry = rs.ambience['entry']
        if not entry.active_version:
            rs.notify('error', n_("Entry already removed."))
            return self.redirect(rs, "core/show_case")
        if (
            entry.parent
            and entry.parent.entry_type
            == const.ComplaintEntryType.revocation_explanation
        ):
            rs.notify('error', n_("Cannot chain revoke."))
            return self.redirect(rs, "core/show_case")
        if entry.is_revoked:
            rs.notify(
                'info',
                n_("%(entry_link)s already revoked."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")

        return self.render(
            rs,
            "complaint/configure_entry",
            {
                'entry_type': const.ComplaintEntryType.revocation_explanation,
                'is_revocation': True,
                'personas': self._get_entry_personas(rs, entry),
            },
            models.ComplaintEntry.mandatory_form_fields(creation=False),
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
        version_data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=True,
            entry_type=const.ComplaintEntryType.revocation_explanation,
        )
        if version_data:
            self._append_author_validation_warning(rs, version_data.get('authors', {}))
        if rs.has_validation_errors() or not version_data:
            return self.revoke_entry_form(rs, case_id, entry_id)
        if not rs.ambience['entry'].active_version:
            rs.notify('error', n_("Entry already removed."))
            return self.redirect(rs, "core/show_case")
        if (
            rs.ambience['entry'].parent
            and rs.ambience['entry'].parent.entry_type
            == const.ComplaintEntryType.revocation_explanation
        ):
            rs.notify('error', n_("Cannot chain revoke."))
            return self.redirect(rs, "core/show_case")
        if rs.ambience['entry'].is_revoked:
            rs.notify(
                'error',
                n_("%(entry_link)s already revoked."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")
        new_entry_id = self.complaintproxy.revoke_entry(rs, entry_id, version_data)
        rs.notify_return_code(new_entry_id)
        return self.redirect(rs, "core/show_case", anchor=f"entry{entry_id}")

    @access("complaint_admin")
    def remove_entry_form(
        self, rs: RequestState, case_id: int, entry_id: int, internal: bool = False
    ) -> Response:
        """Render form."""
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not rs.ambience['entry'].active_version:
            rs.notify('info', n_("Entry already removed."))
            return self.redirect(rs, "core/show_case")
        if rs.ambience['entry'].active_children:
            rs.notify(
                'error',
                n_("%(entry_link)s has active children."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")

        description = None
        if (
            rs.ambience['entry'].entry_type.is_hidden
            and not self.complaintproxy.is_unlocked(rs, case_id)
            and not internal
        ):
            rs.notify(
                'error',
                n_("Need to unlock case before removing %(entry_link)s."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")

        version_id = rs.ambience['entry'].active_version.id
        if rs.ambience['entry'].entry_type.has_description and not internal:
            if rs.ambience['entry'].entry_type.is_hidden:
                description = self.complaintproxy.get_hidden_descriptions(rs, case_id)[
                    version_id
                ]
            else:
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
            {"dreason"},
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("dreason")
    def remove_entry(
        self, rs: RequestState, case_id: int, entry_id: int, dreason: str
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if rs.has_validation_errors():
            return self.remove_entry_form(rs, case_id, entry_id, internal=True)
        if not rs.ambience['entry'].active_version:
            rs.notify('error', n_("Entry already removed."))
            return self.redirect(rs, "core/show_case")
        if rs.ambience['entry'].active_children:
            rs.notify(
                'error',
                n_("%(entry_link)s has active children."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")
        ret = self.complaintproxy.delete_entry(rs, entry_id, dreason)
        rs.notify_return_code(ret)
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", "complaint.enforcer")
    def measures(self, rs: RequestState) -> Response:
        """Search for active measures against a persona."""
        measure_ids = self.complaintproxy.list_measures(rs)
        measures, descriptions, entries = self.complaintproxy.get_measures(
            rs, measure_ids
        )
        author_ids = set(chain.from_iterable(e.authors for e in measures.values()))
        concerned_ids = {e['concerned_id'] for e in entries.values()}
        personas = self.coreproxy.get_personas(rs, author_ids | concerned_ids)
        params = {
            'measures': measures,
            'descriptions': descriptions,
            'entries': entries,
            'personas': personas,
        }
        return self.render(rs, "complaint/measures", params)

    @access("complaint_admin", "complaint.enforcer")
    def show_user_measures(self, rs: RequestState, persona_id: int) -> Response:
        """View active measures against a persona."""
        measure_ids = self.complaintproxy.list_user_measures(
            rs, persona_id, is_active=None
        )
        measures, descriptions, entries = self.complaintproxy.get_measures(
            rs, measure_ids
        )
        author_ids = set(chain.from_iterable(e.authors for e in measures.values()))
        authors = self.coreproxy.get_personas(rs, author_ids)
        params = {
            'measures': measures,
            'descriptions': descriptions,
            'entries': entries,
            'authors': authors,
        }
        return self.render(rs, "complaint/show_user_measures", params)

    # @access("complaint_admin", "complaint.enforcer", "complaint.monitor")
    # def list_complaint_helpers(self, rs: RequestState) -> Response:
    #    """View list of enforcers and monitors."""
    #    return self.render(rs, "complaint/list_complaint_helpers")

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
