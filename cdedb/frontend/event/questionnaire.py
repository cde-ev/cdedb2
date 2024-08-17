#!/usr/bin/env python3

"""
The `EventQuestionnaireMixin` subclasses the `EventBaseFrontend` and provides endpoints
for configuring and filling in the different kinds of questionnaires offered for an
event.
"""

import itertools
from collections.abc import Collection
from typing import Callable, Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    CdEDBObject, DefaultReturnCode, Error, RequestState, merge_dicts, unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.sorting import mixed_existence_sorter
from cdedb.common.validation.validate import QUESTIONNAIRE_ROW_MANDATORY_FIELDS
from cdedb.frontend.common import (
    RequestConstraint, REQUESTdata, access, check_validation_optional as check_optional,
    event_guard, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend


class EventQuestionnaireMixin(EventBaseFrontend):
    @access("event")
    @event_guard(check_offline=True)
    def configure_registration_form(self, rs: RequestState, event_id: int,
                                    ) -> Response:
        """Render form."""
        reg_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.registration)
        return self.render(rs, "questionnaire/configure_registration",
                           {'reg_questionnaire': reg_questionnaire,
                            'registration_fields': reg_fields})

    @access("event")
    @event_guard(check_offline=True)
    def configure_additional_questionnaire_form(self, rs: RequestState,
                                                event_id: int) -> Response:
        """Render form."""
        add_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.additional)
        return self.render(rs, "questionnaire/configure_additional_questionnaire", {
            'add_questionnaire': add_questionnaire,
            'registration_fields': reg_fields})

    def _prepare_questionnaire_form(
            self, rs: RequestState, event_id: int, kind: const.QuestionnaireUsages,
    ) -> tuple[list[CdEDBObject], models.CdEDataclassMap[models.EventField]]:
        """Helper to retrieve some data for questionnaire configuration."""
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        fees_by_field = self.eventproxy.get_event_fees_per_entity(rs, event_id).fields
        current = {
            f"{key}_{i}": value
            for i, entry in enumerate(questionnaire)
            for key, value in entry.items()}
        merge_dicts(rs.values, current)
        registration_fields = {
            k: v for k, v in rs.ambience['event'].fields.items()
            if v.association == const.FieldAssociations.registration
               and (kind.allow_fee_condition() or not fees_by_field[k])
        }
        return questionnaire, registration_fields

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def configure_registration(self, rs: RequestState, event_id: int,
                               ) -> Response:
        """Manipulate the questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.registration
        code = self._set_questionnaire(rs, event_id, kind)
        if rs.has_validation_errors() or code is None:
            return self.configure_registration_form(rs, event_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/configure_registration_form")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def configure_additional_questionnaire(self, rs: RequestState,
                                           event_id: int) -> Response:
        """Manipulate the additional questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.additional
        code = self._set_questionnaire(rs, event_id, kind)
        if rs.has_validation_errors() or code is None:
            return self.configure_additional_questionnaire_form(rs, event_id)
        rs.notify_return_code(code)
        return self.redirect(
            rs, "event/configure_additional_questionnaire_form")

    def _set_questionnaire(self, rs: RequestState, event_id: int,
                           kind: const.QuestionnaireUsages,
                           ) -> Optional[DefaultReturnCode]:
        """Deduplicated code to set questionnaire rows of one kind."""
        other_kinds = set(const.QuestionnaireUsages) - {kind}
        other_questionnaire = self.eventproxy.get_questionnaire(
            rs, event_id, kinds=other_kinds)
        other_used_fields = {e['field_id'] for v in other_questionnaire.values()
                             for e in v if e['field_id']}

        old_questionnaire, registration_fields = self._prepare_questionnaire_form(
            rs, event_id, kind)

        new_questionnaire = self.process_questionnaire_input(
            rs, len(old_questionnaire), registration_fields, kind,
            other_used_fields)
        if rs.has_validation_errors():
            return None
        code = self.eventproxy.set_questionnaire(
            rs, event_id, new_questionnaire)
        return code

    @access("event")
    @REQUESTdata("preview")
    def additional_questionnaire_form(self, rs: RequestState, event_id: int,
                                      preview: bool = False,
                                      internal: bool = False) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, "event/show_event")
        add_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.additional,)))
        wish_data = {}
        if not preview:
            registration_id = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id)
            if not registration_id:
                rs.notify("warning", n_("Not registered for event."))
                return self.redirect(rs, "event/show_event")
            registration_id = unwrap(registration_id.keys())
            registration = self.eventproxy.get_registration(rs, registration_id)
            if not rs.ambience['event'].use_additional_questionnaire:
                rs.notify("warning", n_("Questionnaire disabled."))
                return self.redirect(rs, "event/registration_status")
            if self.is_locked(rs.ambience['event']):
                rs.notify("info", n_("Event locked."))
            values = {
                f"fields.{key}": val
                for key, val in registration['fields'].items()
            }
            merge_dicts(rs.values, values)
            if field := rs.ambience['event'].lodge_field:
                if any(row['field_id'] == field.id for row in add_questionnaire):
                    wish_data = self._get_user_lodgement_wishes(rs, event_id)
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(n_("Must be Orga to use preview."))
            if not rs.ambience['event'].use_additional_questionnaire:
                rs.notify("info", n_("Questionnaire is not enabled yet."))
        return self.render(rs, "questionnaire/additional_questionnaire", {
            'add_questionnaire': add_questionnaire,
            'preview': preview,
            'lodgement_wishes': wish_data,
        })

    @access("event", modi={"POST"})
    def additional_questionnaire(self, rs: RequestState, event_id: int,
                                 ) -> Response:
        """Fill in additional fields.

        Save data submitted in the additional questionnaire.
        Note that questionnaire rows may also be present during registration.
        """
        # Ignore validation errors in case there is a csrf error and a redirect below.
        rs.ignore_validation_errors()
        registration_id = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(registration_id.keys())
        if not rs.ambience['event'].use_additional_questionnaire:
            rs.notify("error", n_("Questionnaire disabled."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        params = self._questionnaire_params(rs, const.QuestionnaireUsages.additional)
        data = {
            key.removeprefix("fields."): val
            for key, val in request_extractor(rs, params).items()
        }
        if rs.has_validation_errors():
            return self.additional_questionnaire_form(rs, event_id, internal=True)

        change_note = "Fragebogen durch Teilnehmer bearbeitet."
        code = self.eventproxy.set_registration(
            rs, {'id': registration_id, 'fields': data}, change_note, orga_input=False)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/additional_questionnaire_form")

    @staticmethod
    def process_questionnaire_input(
            rs: RequestState, num: int,
            reg_fields: models.CdEDataclassMap[models.EventField],
            kind: const.QuestionnaireUsages, other_used_fields: Collection[int],
    ) -> dict[const.QuestionnaireUsages, list[CdEDBObject]]:
        """This handles input to configure questionnaires.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :param num: number of rows to expect
        :param reg_fields: Available fields
        :param kind: For which kind of questionnaire are these rows?
        """
        del_flags = request_extractor(rs, {f"delete_{i}": bool for i in range(num)})
        deletes = {i for i in range(num) if del_flags[f'delete_{i}']}
        spec: vtypes.TypeMapping = dict(QUESTIONNAIRE_ROW_MANDATORY_FIELDS,
                                        field_id=Optional[vtypes.ID])  # type: ignore[arg-type]
        marker = 1
        while marker < 2 ** 10:
            if not unwrap(request_extractor(rs, {f"create_-{marker}": bool})):
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        indices = (set(range(num)) | {-i for i in range(1, marker)}) - deletes

        field_key = lambda anid: f"field_id_{anid}"
        readonly_key = lambda anid: f"readonly_{anid}"
        default_value_key = lambda anid: f"default_value_{anid}"

        def duplicate_constraint(idx1: int, idx2: int,
                                 ) -> Optional[RequestConstraint]:
            if idx1 == idx2:
                return None
            key1 = field_key(idx1)
            key2 = field_key(idx2)
            msg = n_("Must not duplicate field.")
            return (lambda d: (not d[key1] or d[key1] != d[key2]),
                    (key1, ValueError(msg)))

        def valid_field_constraint(idx: int) -> RequestConstraint:
            key = field_key(idx)
            return (lambda d: not d[key] or d[key] in reg_fields,
                    (key, ValueError(n_("Invalid field."))))

        def readonly_kind_constraint(idx: int) -> RequestConstraint:
            key = readonly_key(idx)
            msg = n_("Registration questionnaire rows may not be readonly.")
            return (lambda d: (not d[key] or kind.allow_readonly()),
                    (key, ValueError(msg)))

        def duplicate_kind_constraint(idx: int) -> RequestConstraint:
            key = field_key(idx)
            msg = n_("This field is already in use in another questionnaire.")
            return (lambda d: d[key] not in other_used_fields,
                    (key, ValueError(msg)))

        constraints: list[tuple[Callable[[CdEDBObject], bool], Error]]
        constraints = list(filter(
            None, (duplicate_constraint(idx1, idx2)
                   for idx1 in indices for idx2 in indices)))
        constraints += list(itertools.chain.from_iterable(
            (valid_field_constraint(idx),
             readonly_kind_constraint(idx),
             duplicate_kind_constraint(idx))
            for idx in indices))

        params: vtypes.TypeMapping = {
            f"{key}_{i}": value for i in indices for key, value in spec.items()}
        data = request_extractor(rs, params, constraints)
        for idx in indices:
            dv_key = default_value_key(idx)
            field_id = data[field_key(idx)]
            if data[dv_key] is None or field_id is None:
                data[dv_key] = None
                continue
            data[dv_key] = check_optional(
                rs, vtypes.ByFieldDatatype,
                data[dv_key], dv_key, kind=reg_fields[field_id].kind)
        questionnaire = {
            kind: list(
                {key: data[f"{key}_{i}"] for key in spec}
                for i in mixed_existence_sorter(indices))}
        return questionnaire

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("kind")
    def reorder_questionnaire_form(self, rs: RequestState, event_id: int,
                                   kind: const.QuestionnaireUsages) -> Response:
        """Render form."""
        if rs.has_validation_errors():
            if any(field == 'kind' for field, _ in rs.retrieve_validation_errors()):
                rs.notify("error", n_("Unknown questionnaire kind."))
                return self.redirect(rs, "event/show_event")
            else:
                # we want to render the errors from reorder_questionnaire on this page,
                # so we only redirect to another page if 'kind' does not pass validation
                pass
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        redirects = {
            const.QuestionnaireUsages.registration:
                "event/configure_registration",
            const.QuestionnaireUsages.additional:
                "event/configure_additional_questionnaire",
        }
        if not questionnaire:
            rs.notify("info", n_("No questionnaire rows of this kind found."))
            return self.redirect(rs, redirects[kind])
        return self.render(rs, "questionnaire/reorder_questionnaire", {
            'questionnaire': questionnaire, 'kind': kind, 'redirect': redirects[kind]})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("order", "kind")
    def reorder_questionnaire(self, rs: RequestState, event_id: int,
                              kind: const.QuestionnaireUsages,
                              order: vtypes.IntCSVList) -> Response:
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))

        if not set(order) == set(range(len(questionnaire))):
            rs.append_validation_error(
                ("order", ValueError(n_("Every row must occur exactly once."))))
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        new_questionnaire = [questionnaire[i] for i in order]
        code = self.eventproxy.set_questionnaire(rs, event_id,
                                                 {kind: new_questionnaire})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/reorder_questionnaire_form", {'kind': kind})
