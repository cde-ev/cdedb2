#!/usr/bin/env python3
import copy
import datetime
import itertools
from collections.abc import Collection
from itertools import chain
from typing import Any

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.complaint as models
from cdedb.common import (
    CdEDBObject,
    RequestState,
    ValidationWarning,
    determine_age_class,
    merge_dicts,
    now,
)
from cdedb.common.exceptions import AdverseCompanionError
from cdedb.common.n_ import n_
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.common.query.log_filter import ComplaintLogFilter
from cdedb.common.sorting import xsorted
from cdedb.filter import cdedbid_filter
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    TransactionObserver,
    access,
    check_validation as check,
    extract_and_check_dataclass_validation as extract_and_check_dataclass,
    periodic,
    request_extractor,
)
from cdedb.frontend.core.base import CoreBaseFrontend

CASE_SEARCH_DEFAULTS = {
    'qop_cases.summary': QueryOperators.match,
    'qop_cases.is_grave': QueryOperators.equal,
    'qop_cases.kind': QueryOperators.oneof,
    'qop_status.is_confirmed': QueryOperators.equal,
    'qop_status.is_closed': QueryOperators.equal,
    # transpired after
    'qop_cases.end_date': QueryOperators.greaterornull,
    # transpired before
    'qop_cases.start_date': QueryOperators.lessornull,
    'qop_involved.persona_id': QueryOperators.equal,
    'qop_involved.involvement_type': QueryOperators.oneof,
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
            cases = unlocked_cases = None
        else:
            query_input: dict[str, Any] = scope.mangle_query_input(rs, defaults)
            # Manually mangle the last changed information
            if last_entry_after and last_entry_before:
                query_input['qop_status.last_entry'] = QueryOperators.between
                query_input['qval_status.last_entry'] = (
                    f"{last_entry_after},{last_entry_before}"
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
            elif count > len(cases):
                rs.notify(
                    "warning",
                    n_("%(count)s cases not shown."),
                    {"count": count - len(cases)},
                )
                persona_id = check(
                    rs,
                    vtypes.PersonaID,
                    query_input['qval_involved.persona_id'],
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

        return self.render(
            rs,
            "complaint/index",
            {
                'spec': spec,
                'cases': cases,
                'count': count,
                'unlocked_cases': unlocked_cases,
            },
        )

    def _get_case_data(
        self,
        rs: RequestState,
        case: models.Case,
        *,
        get_hidden_descriptions: bool,
        show_log_entries: bool,
        include_deleted: bool,
    ) -> CdEDBObject | None:
        if not case.is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if get_hidden_descriptions and not self.complaintproxy.is_unlocked(rs, case.id):
            rs.notify('error', n_("Need to unlock case first."))
            return None

        # Collect all entries to be displayed.
        log_entries: tuple[dict[str, Any], ...] = tuple()
        if show_log_entries:
            log_filter = ComplaintLogFilter(case_id=case.id)
            _, log_entries = self.complaintproxy.retrieve_log(rs, log_filter)
            log_entries = log_entries or tuple()
        all_entries = rs.ambience['case'].list_entries(
            log_entries, include_deleted=include_deleted
        )

        age_classes = {}
        for persona_id, persona in case.personas.items():
            if persona.is_event_realm and rs.ambience['case'].start_date:
                age_classes[persona_id] = determine_age_class(
                    self.coreproxy.get_event_user(rs, persona_id).birthday,
                    rs.ambience['case'].start_date,
                )

        # Collect descriptions separately as a privacy precaution
        descriptions = self.complaintproxy.get_visible_descriptions(
            rs, case.id, deleted=None if include_deleted else False
        )
        if get_hidden_descriptions:
            descriptions.update(
                self.complaintproxy.get_hidden_descriptions(rs, case.id)
            )

        return {
            'all_entries': all_entries,
            'descriptions': descriptions,
            'age_classes': age_classes,
        }

    @access("complaint_admin")
    @REQUESTdata("show_log_entries")
    def show_case(
        self, rs: RequestState, case_id: int, show_log_entries: bool = False
    ) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        is_unlocked = self.complaintproxy.is_unlocked(rs, case_id)

        case_data = self._get_case_data(
            rs,
            rs.ambience["case"],
            get_hidden_descriptions=bool(is_unlocked),
            show_log_entries=show_log_entries,
            include_deleted=False,
        )
        if case_data is None:  # pragma: no cover
            return self.redirect(rs, "core/show_case")

        related_cases = self.complaintproxy.get_related_cases(rs, case_id)

        return self.render(
            rs,
            "complaint/show_case",
            case_data
            | {
                'is_locked': not is_unlocked,
                'show_log_entries': show_log_entries,
                'related_cases': related_cases,
            },
        )

    @access("complaint_admin")
    def case_history(self, rs: RequestState, case_id: int) -> Response:
        """Show all entry versions for a case."""
        case_data = self._get_case_data(
            rs,
            rs.ambience["case"],
            get_hidden_descriptions=True,
            show_log_entries=True,
            include_deleted=True,
        )
        if case_data is None:
            return self.redirect(rs, "core/show_case")

        return self.render(rs, "complaint/case_history", case_data)

    @access("complaint_admin")
    def export_case(self, rs: RequestState, case_id: int) -> Response:
        case_data = self._get_case_data(
            rs,
            rs.ambience["case"],
            get_hidden_descriptions=True,
            show_log_entries=True,
            include_deleted=False,
        )
        if case_data is None:
            return self.redirect(rs, "core/show_case")

        export = self.fill_template(
            rs,
            "other",
            "complaint/case_export",
            case_data | {"case": rs.ambience["case"]},
        )

        return self.render(rs, "complaint/export_case", {"export": export})

    @access("complaint_admin")
    def create_case_form(self, rs: RequestState) -> Response:
        """Render form."""
        mandatory_fields = models.Case.mandatory_form_fields(creation=True)
        mandatory_fields |= {'timestamp', 'info'}
        return self.render(rs, "complaint/configure_case", {}, mandatory_fields)

    @staticmethod
    def _check_overlapping_sets[T](id_lists: dict[str, Collection[T]]) -> set[str]:
        """Return a set of all keys whos value overlaps with another value."""
        ret = set()
        for (name1, set1), (name2, set2) in itertools.combinations(id_lists.items(), 2):
            if set(set1) & set(set2):
                ret.add(name1)
                ret.add(name2)
        return ret

    @access("complaint_admin", modi={"POST"})
    @REQUESTdatadict(*models.Case.requestdict_fields(creation=True))
    @REQUESTdata("timestamp", "info")
    def create_case(
        self,
        rs: RequestState,
        data: dict[str, Any],
        timestamp: datetime.datetime,
        info: str,
    ) -> Response:
        involved_params = {
            f"{involvement_type.name}_ids": list[vtypes.PersonaID]
            for involvement_type in const.ComplaintInvolvementType
        }
        involved_data = request_extractor(rs, involved_params)

        if rs.has_validation_errors():
            return self.create_case_form(rs)
        if any(
            rs.user.persona_id in involved_ids
            for involved_ids in involved_data.values()
        ):
            rs.notify('error', n_("May not create case with own involvement."))
            return self.create_case_form(rs)

        for field in self._check_overlapping_sets(involved_data):
            rs.append_validation_error((
                field,
                ValueError(n_("May not be involved in multiple ways.")),
            ))

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
            for involvement_type in xsorted(const.ComplaintInvolvementType):
                if involved_ids := involved_data[f"{involvement_type.name}_ids"]:
                    ret *= self.complaintproxy.add_involved(
                        rs, new_case.id, involvement_type, involved_ids
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
        persona_ids: list[vtypes.PersonaID],
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if persona_ids:
            if rs.user.persona_id in persona_ids:
                rs.append_validation_error((
                    "persona_ids",
                    ValueError(n_("May not add own involvement.")),
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

        active_companions = rs.ambience['case'].get_companions(is_active=True)
        ex_companions_ids = set(persona_ids) & active_companions.keys()
        ex_companions = xsorted(
            rs.ambience['case'].personas[companion_id]
            for companion_id in ex_companions_ids
        )
        for companion in ex_companions:
            rs.notify(
                'warning',
                n_("%(companion)s was a companion and is now marked as withdrawn."),
                {'companion': companion.get_name()},
            )
            for persona_id in active_companions[companion.id]:
                self.complaintproxy.set_companion_withdrawn(
                    rs, case_id, persona_id, companion.id, is_withdrawn=True
                )

        # Preventing companions from becoming adverse is hard, so just try-except.
        try:
            ret = self.complaintproxy.add_involved(
                rs, case_id, involvement_type, persona_ids
            )
        except AdverseCompanionError:
            # Cannot treat this as a validation error, because of suppressed exception protection.
            rs.notify("error", n_("Some companions would become adverse."))
            return self.redirect(rs, "core/show_case")
        rs.notify_return_code(
            ret, info=n_("Some of these users were already involved.")
        )
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def remove_involved(
        self, rs: RequestState, case_id: int, involved_id: vtypes.InvolvedID
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        ret = self.complaintproxy.remove_involved(rs, case_id, [involved_id])
        rs.notify_return_code(ret, info=n_("This user was not involved."))
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def inform_involved(
        self, rs: RequestState, case_id: int, involved_id: vtypes.InvolvedID
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if involved_id not in rs.ambience['case'].involved:
            rs.notify("error", n_("This user is not involved."))
        else:
            ret = self.complaintproxy.set_involved_informed(
                rs, case_id, involved_id, True
            )
            rs.notify_return_code(
                ret, info=n_("This user was already marked as informed.")
            )
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin", modi={"POST"})
    def uninform_involved(
        self, rs: RequestState, case_id: int, involved_id: vtypes.InvolvedID
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if involved_id not in rs.ambience['case'].involved:
            rs.notify("error", n_("This user is not involved."))
        # elif check informed state
        else:
            ret = self.complaintproxy.set_involved_informed(
                rs, case_id, involved_id, False
            )
            rs.notify_return_code(
                ret, info=n_("This user was already marked as uninformed.")
            )
        return self.redirect(rs, "core/show_case")

    @access("complaint_admin")
    def manage_companions_form(
        self, rs: RequestState, case_id: int, involved_id: vtypes.InvolvedID
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        involved = rs.ambience['case'].involved[involved_id]
        return self.render(rs, "complaint/manage_companions", {"involved": involved})

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("companion_ids")
    def add_companions(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_ids: list[vtypes.PersonaID],
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if companion_ids:
            if set(companion_ids) & rs.ambience['case'].involved_persona_ids:
                rs.append_validation_error((
                    "companion_ids",
                    ValueError(n_("Companion may not be involved.")),
                ))
            if set(companion_ids) & rs.ambience['case'].adverse_companions(
                rs.ambience['case'].involved[involved_id].involvement_type
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
            return self.manage_companions_form(rs, case_id, involved_id)
        ret = self.complaintproxy.add_companions(
            rs, case_id, involved_id, companion_ids
        )
        rs.notify_return_code(
            ret, info=n_("Some of these users were already companions.")
        )
        return self.redirect(rs, "core/manage_companions_form")

    @access("complaint_admin", modi={"POST"})
    def remove_companion(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_id: vtypes.PersonaID,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        ret = self.complaintproxy.remove_companions(
            rs, case_id, involved_id, [companion_id]
        )
        rs.notify_return_code(ret, info=n_("This user was no companion."))
        return self.redirect(rs, "core/manage_companions_form")

    @access("complaint_admin", modi={"POST"})
    def withdraw_companion(
        self,
        rs: RequestState,
        case_id: int,
        involved_id: vtypes.InvolvedID,
        companion_id: vtypes.PersonaID,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if companion_id not in rs.ambience['case'].get_companions(is_active=True):
            rs.notify("error", n_("This user is no companion."))
        else:
            ret = self.complaintproxy.set_companion_withdrawn(
                rs, case_id, involved_id, companion_id, True
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
        involved_id: vtypes.InvolvedID,
        companion_id: vtypes.PersonaID,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        involved = rs.ambience['case'].involved[involved_id]
        if companion_id not in involved.get_companions(is_active=False):
            rs.notify("error", n_("This user is no withdrawn companion."))
        elif companion_id in rs.ambience['case'].involved_persona_ids:
            rs.notify("error", n_("Active companion may not be involved."))
        else:
            ret = self.complaintproxy.set_companion_withdrawn(
                rs, case_id, involved_id, companion_id, False
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
            models.ComplaintEntry.mandatory_form_fields(creation=True),
        )

    def _append_author_validation_warning(
        self, rs: RequestState, authors: Collection[int]
    ) -> None:
        """Warn to not misuse author field.

        This check is intentionally omitted on replacement, to not be too annoying"""
        if (
            set(authors) & rs.ambience['case'].involved_persona_ids
            and not rs.ignore_warnings
        ):
            msg = n_("Should not include involved people.")
            rs.append_validation_error(('authors', ValidationWarning(msg)))

    @access("complaint_admin", modi={"POST"})
    @REQUESTfile("attachment")
    @REQUESTdata("entry_type", "attachment_hash", "attachment_filename")
    def add_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_type: const.ComplaintEntryType,
        attachment: werkzeug.datastructures.FileStorage | None,
        attachment_hash: vtypes.Identifier | None,
        attachment_filename: str | None,
        parent_id: int | None = None,
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()

        if attachment or attachment_hash:
            rs.values["attachment_hash"], rs.values["attachment_filename"] = (
                self.locate_or_store_attachment(
                    rs,
                    self.complaintproxy.get_attachment_store(rs),
                    attachment,
                    attachment_hash,
                    attachment_filename,
                )
            )

        entry_data = (
            extract_and_check_dataclass(
                rs,
                models.ComplaintEntry,
                additional_data={'parent_id': parent_id},
                creation=True,
                entries=rs.ambience['case'].entries,
            )
            or {}
        )
        version_data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=True,
            entry_type=entry_type,
            additional_data={
                "attachment_hash": rs.values["attachment_hash"],
                "attachment_filename": rs.values["attachment_filename"],
            },
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

        return self.render(
            rs,
            "complaint/configure_entry",
            {'entry_type': rs.ambience['entry'].entry_type},
            models.ComplaintEntry.mandatory_form_fields(creation=False),
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTfile("attachment")
    @REQUESTdata("dreason", "attachment_hash", "attachment_filename")
    def replace_entry(
        self,
        rs: RequestState,
        case_id: int,
        entry_id: int,
        dreason: str,
        attachment: werkzeug.datastructures.FileStorage | None,
        attachment_hash: vtypes.Identifier | None,
        attachment_filename: str | None,
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()

        if attachment or attachment_hash:
            rs.values["attachment_hash"], rs.values["attachment_filename"] = (
                self.locate_or_store_attachment(
                    rs,
                    self.complaintproxy.get_attachment_store(rs),
                    attachment,
                    attachment_hash,
                    attachment_filename,
                )
            )

        data = extract_and_check_dataclass(
            rs,
            models.ComplaintEntryVersion,
            creation=False,
            entry_type=rs.ambience['entry'].entry_type,
            additional_data={
                "attachment_hash": rs.values["attachment_hash"],
                "attachment_filename": rs.values["attachment_filename"],
            },
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

        return self.render(
            rs,
            "complaint/remove_entry",
            {'description': description},
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

    @access("complaint_admin", modi={"POST"})
    def mark_entry_version_for_purge(
        self, rs: RequestState, case_id: int, entry_id: int, entry_version_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not self.complaintproxy.is_unlocked(rs, case_id):
            rs.notify('error', n_("Need to unlock case."))
            return self.redirect(rs, "core/show_case")
        # This is done before to ensure the mail is sent even in error scenarios
        delay = self.conf["COMPLAINT_ENTRY_VERSION_PURGE_DELAY"].days
        subject = f"Eintragsversion wird in {delay} Tagen unwiderruflich gelöscht"
        self.do_mail(
            rs,
            "complaint/entry_version_marked_for_purge",
            {'To': (self.conf['COMPLAINT_ADMIN_ADDRESS'],), 'Subject': subject},
            {'case_id': case_id, "entry_version_id": entry_version_id, 'delay': delay},
        )
        code = self.complaintproxy.mark_entry_version_for_purge(
            rs, entry_id, entry_version_id
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "core/case_history", anchor=f"entry{entry_id}")

    @access("complaint_admin", modi={"POST"})
    def unmark_entry_version_for_purge(
        self, rs: RequestState, case_id: int, entry_id: int, entry_version_id: int
    ) -> Response:
        if not rs.ambience['case'].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not self.complaintproxy.is_unlocked(rs, case_id):
            rs.notify('error', n_("Need to unlock case."))
            return self.redirect(rs, "core/show_case")
        code = self.complaintproxy.unmark_entry_version_for_purge(
            rs, entry_id, entry_version_id
        )
        rs.notify_return_code(code)
        subject = "Löschung von Eintragsversion wurde aufgehalten"
        self.do_mail(
            rs,
            "complaint/entry_version_unmarked_for_purge",
            {'To': (self.conf['COMPLAINT_ADMIN_ADDRESS'],), 'Subject': subject},
            {'case_id': case_id, "entry_version_id": entry_version_id},
        )
        return self.redirect(rs, "core/case_history", anchor=f"entry{entry_id}")

    @periodic("purge_complaint_entry_versions")
    def purge_complaint_entry_versions(
        self, rs: RequestState, state: CdEDBObject
    ) -> CdEDBObject:
        cutoff = now() - self.conf["COMPLAINT_ENTRY_VERSION_PURGE_DELAY"]
        marked_for_purge = self.complaintproxy.list_entry_versions_marked_for_purge(rs)

        purged = []
        pending = []
        for entry_version in marked_for_purge:
            if entry_version.marked_for_purge < cutoff:
                self.complaintproxy.purge_entry_version(
                    rs, entry_version.entry_id, entry_version.id
                )
                purged.append(entry_version.id)
            else:
                pending.append(entry_version.id)

        if pending:
            versions = ", ".join(map(str, pending))
            self.logger.info(
                f"{len(pending)} entry versions pending purge ({versions})."
            )
        if purged:
            versions = ", ".join(map(str, purged))
            self.logger.info(
                f"Purged {len(purged)} complaint entry versions ({versions})."
            )

        state = {"pending": pending, "purged": state.get("purged", []) + purged}

        return state

    @access("complaint_admin")
    def get_complaint_attachment(
        self, rs: RequestState, case_id: int, entry_id: int, version_idx: int
    ) -> Response:
        # the check that the entry belongs to the case is already done in
        # `reconnoitre_ambience`, which raises a "404 Not Found" in this case
        if not rs.ambience["case"].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not rs.ambience["entry_version"].attachment_hash:
            rs.notify("error", n_("Entry version has no attachment."))
            return self.redirect(rs, "core/show_case")
        if (
            rs.ambience["entry"].entry_type.is_hidden
            and not self.complaintproxy.is_unlocked(rs, case_id)
        ):  # fmt: skip
            rs.notify(
                "error",
                n_("Need to unlock case to access %(entry_link)s attachment."),
                {"entry_link": entry_link(rs, entry_id)},
            )
            return self.redirect(rs, "core/show_case")
        content = self.complaintproxy.retrieve_attachment(rs, entry_id, version_idx)
        if content is None:
            raise werkzeug.exceptions.NotFound(n_("File does not exist."))
        return self.send_file(
            rs,
            mimetype="application/pdf",
            data=content,
            filename=rs.ambience["entry_version"].attachment_filename,
        )

    @access("complaint_admin")
    def get_cached_complaint_attachment(
        self, rs: RequestState, case_id: int, attachment_hash: str
    ) -> Response:
        if not rs.ambience["case"].is_visible_for(rs.user):
            raise werkzeug.exceptions.Forbidden()
        if not self.complaintproxy.is_unlocked(rs, case_id):
            rs.notify(
                "error",
                n_("Need to unlock case to access attachment."),
            )
            return self.redirect(rs, "core/show_case")
        content = self.complaintproxy.get_attachment_store(rs).get(attachment_hash)
        if content is None:
            raise werkzeug.exceptions.NotFound(n_("File does not exist."))
        return self.send_file(rs, mimetype="application/pdf", data=content)

    @periodic("forget_complaint_attachments", period=16)
    def forget_attachments(self, rs: RequestState, store: CdEDBObject) -> CdEDBObject:
        """Periodically delete all attachments no longer referenced."""
        self.complaintproxy.get_attachment_store(rs).forget(
            rs, self.complaintproxy.get_attachment_usage
        )
        return store

    @access("complaint_admin", "complaint.enforcer")
    def measures(self, rs: RequestState) -> Response:
        """Search for active measures against a persona."""
        entries, descriptions = self.complaintproxy.get_measures(rs)
        author_ids = set(
            chain.from_iterable(
                # The entries are guaranteed to have an active version.
                # mypy doesn't know this.
                e.active_version.authors
                for e in entries.values()
                if e.active_version
            )
        )
        concerned_ids = {e.concerned_id for e in entries.values() if e.concerned_id}
        personas = self.coreproxy.get_personas(rs, author_ids | concerned_ids)
        params = {
            'entries': entries,
            'descriptions': descriptions,
            'personas': personas,
        }
        return self.render(rs, "complaint/measures", params)

    @access("persona")
    def show_user_measures(self, rs: RequestState, persona_id: int) -> Response:
        """View active measures against a persona."""
        if (
            not {"complaint_admin", "complaint.enforcer"} & rs.user.all_roles
            and persona_id != rs.user.persona_id
        ):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if (
            "complaint_admin" not in rs.user.roles
            and not self.coreproxy.is_relative_admin(rs, persona_id)
            and persona_id != rs.user.persona_id
        ):
            del rs.ambience['persona']['username']

        entries, descriptions = self.complaintproxy.get_user_measures(rs, persona_id)
        author_ids = set(
            chain.from_iterable(
                # The entries are guaranteed to have an active version.
                # mypy doesn't know this.
                e.active_version.authors
                for e in entries.values()
                if e.active_version
            )
        )
        authors = self.coreproxy.get_personas(rs, author_ids)
        params = {
            'entries': entries,
            'descriptions': descriptions,
            'authors': authors,
        }
        return self.render(rs, "complaint/show_user_measures", params)

    @access("complaint_admin", "complaint.enforcer", "complaint.monitor")
    def list_complaint_helpers(self, rs: RequestState) -> Response:
        """View list of enforcers and monitors."""
        enforcer_ids = self.complaintproxy.list_enforcers(rs)
        enforcers = self.coreproxy.get_personas(rs, enforcer_ids)
        return self.render(
            rs,
            "complaint/list_complaint_helpers",
            {
                "enforcers": enforcers,
            },
        )

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def add_enforcer(self, rs: RequestState, persona_id: vtypes.PersonaID) -> Response:
        """Grant enforcer privileges to a persona."""
        if rs.has_validation_errors():
            return self.list_complaint_helpers(rs)
        if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
            rs.append_validation_error((
                "persona_id",
                ValueError(n_("This user does not exist or is archived.")),
            ))
        if rs.has_validation_errors():
            return self.list_complaint_helpers(rs)

        ret = self.complaintproxy.add_enforcer(rs, persona_id)
        rs.notify_return_code(ret, info=n_("Nothing changed."))
        return self.redirect(rs, "core/list_complaint_helpers")

    @access("complaint_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def remove_enforcer(self, rs: RequestState, persona_id: vtypes.ID) -> Response:
        """Remove enforcer privileges of a persona."""
        if rs.has_validation_errors():
            return self.list_complaint_helpers(rs)
        if persona_id not in self.complaintproxy.list_enforcers(rs):
            rs.notify('error', n_("This user does not exist or is no enforcer."))
            return self.list_complaint_helpers(rs)

        ret = self.complaintproxy.remove_enforcer(rs, persona_id)
        rs.notify_return_code(ret, info=n_("Nothing changed."))
        return self.redirect(rs, "core/list_complaint_helpers")

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
