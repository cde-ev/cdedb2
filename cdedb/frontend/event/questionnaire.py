#!/usr/bin/env python3

"""
The `EventQuestionnaireMixin` subclasses the `EventBaseFrontend` and provides endpoints
for configuring and filling in the different kinds of questionnaires offered for an
event.
"""

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    DefaultReturnCode,
    RequestState,
    get_hash,
    json_serialize,
    merge_dicts,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.privileges import EventPrivileges, is_event_access_limited
from cdedb.frontend.common import (
    REQUESTdata,
    access,
    check_validation as check,
    process_dynamic_input,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend, event_guard


class EventQuestionnaireMixin(EventBaseFrontend):
    @access("event")
    @event_guard(EventPrivileges.basic_read)
    def configure_registration_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        return self.configure_questionnaire_form(
            rs,
            event_id,
            const.QuestionnaireUsages.registration,
        )

    @access("event")
    @event_guard(EventPrivileges.basic_read)
    def configure_additional_questionnaire_form(
        self, rs: RequestState, event_id: int
    ) -> Response:
        """Render form."""
        return self.configure_questionnaire_form(
            rs,
            event_id,
            const.QuestionnaireUsages.additional,
        )

    def _prepare_questionnaire_form(
        self, rs: RequestState, event_id: int, kind: const.QuestionnaireUsages
    ) -> tuple[models.QuestionnaireContainer, models.Questionnaire, str]:
        """Helper to retrieve some data for questionnaire configuration."""
        full_questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)
        questionnaire = full_questionnaire[kind]
        current = {
            f"{key}_{i}": value
            for i, entry in enumerate(questionnaire)
            for key, value in entry.as_dict().items()
        }
        merge_dicts(rs.values, current)

        checksum = get_hash(json_serialize(questionnaire).encode())

        return (full_questionnaire, questionnaire, checksum)

    def configure_questionnaire_form(
        self, rs: RequestState, event_id: int, kind: const.QuestionnaireUsages
    ) -> Response:
        full_questionnaire, questionnaire, checksum = self._prepare_questionnaire_form(
            rs, event_id, kind
        )
        return self.render(
            rs,
            "questionnaire/configure_questionnaire",
            {
                "questionnaire": questionnaire,
                "checksum": checksum,
                "registration_fields": full_questionnaire.get_available_fields(kind),
                "kind": kind,
            },
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    def configure_registration(self, rs: RequestState, event_id: int) -> Response:
        """Manipulate the questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.registration
        code = self._set_questionnaire(rs, event_id, kind)
        if code <= 0:
            return self.configure_registration_form(rs, event_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/configure_registration_form")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    def configure_additional_questionnaire(
        self, rs: RequestState, event_id: int
    ) -> Response:
        """Manipulate the additional questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.additional
        code = self._set_questionnaire(rs, event_id, kind)
        if code <= 0:
            return self.configure_additional_questionnaire_form(rs, event_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/configure_additional_questionnaire_form")

    def _set_questionnaire(
        self, rs: RequestState, event_id: int, kind: const.QuestionnaireUsages
    ) -> DefaultReturnCode:
        """Deduplicated code to set questionnaire rows of one kind."""
        checksum = request_extractor(rs, {"checksum": str | None})["checksum"]
        all_questionnaires, questionnaire, old_checksum = (
            self._prepare_questionnaire_form(rs, event_id, kind)
        )

        new_questionnaire = process_dynamic_input(
            rs,
            models.QuestionnaireRow,
            existing=list(range(len(questionnaire))),
            spec=dict(models.QuestionnaireRow.requestdict_fields(creation=False)),
            creation_spec=dict(
                models.QuestionnaireRow.requestdict_fields(creation=True)
            ),
            skip_validation=True,
        )
        new_questionnaire = check(
            rs,
            vtypes.Questionnaire,
            list(filter(None, new_questionnaire.values())),
            kind=kind,
            event=rs.ambience["event"],
            all_questionnaires=all_questionnaires,
        )

        if rs.has_validation_errors() or new_questionnaire is None:
            return 0

        if checksum != old_checksum:
            rs.notify(
                "warning",
                n_(
                    "The configuration changed in the meantime. Saving your changes will"
                    " override those changes. Submit form again to proceed."
                ),
            )
            return -1

        return self.eventproxy.set_questionnaire(rs, event_id, kind, new_questionnaire)

    @access("event")
    @REQUESTdata("preview")
    def additional_questionnaire_form(
        self,
        rs: RequestState,
        event_id: int,
        preview: bool = False,
        internal: bool = False,
    ) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, "event/show_event")
        add_questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)[
            const.QuestionnaireUsages.additional
        ]
        wish_data = {}  # type: ignore[var-annotated]
        if not preview:
            registration_id = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id
            )
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
                f"fields.{key}": val for key, val in registration['fields'].items()
            }
            merge_dicts(rs.values, values)
            if field := rs.ambience['event'].lodge_field:
                if any(row.field_id == field.id for row in add_questionnaire):
                    wish_data = self._get_user_lodgement_wishes(rs, event_id) or {}  # type: ignore[assignment]
        else:
            if not self.is_privileged(rs, EventPrivileges.basic_read):
                raise werkzeug.exceptions.Forbidden(n_("Must be orga to use preview."))
            if not rs.ambience['event'].use_additional_questionnaire:
                rs.notify("info", n_("Questionnaire is not enabled yet."))
        return self.render(
            rs,
            "questionnaire/additional_questionnaire",
            {
                'add_questionnaire': add_questionnaire,
                'preview': preview,
                'lodgement_wishes': wish_data,
            },
        )

    @access("event", modi={"POST"})
    def additional_questionnaire(self, rs: RequestState, event_id: int) -> Response:
        """Fill in additional fields.

        Save data submitted in the additional questionnaire.
        Note that questionnaire rows may also be present during registration.
        """
        # Ignore validation errors in case there is a csrf error and a redirect below.
        rs.ignore_validation_errors()
        registration_id = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id
        )
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(registration_id.keys())
        if not rs.ambience['event'].use_additional_questionnaire:
            rs.notify("error", n_("Questionnaire disabled."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']) or is_event_access_limited(event_id):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        data = self.extract_questionnaire_fields(
            rs, const.QuestionnaireUsages.additional
        )
        if rs.has_validation_errors():
            return self.additional_questionnaire_form(rs, event_id, internal=True)

        change_note = "Fragebogen durch Teilnehmer bearbeitet."
        code = self.eventproxy.set_registration(
            rs, {'id': registration_id, 'fields': data}, change_note, orga_input=False
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "event/additional_questionnaire_form")

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("kind")
    def reorder_questionnaire_form(
        self, rs: RequestState, event_id: int, kind: const.QuestionnaireUsages
    ) -> Response:
        """Render form."""
        if rs.has_validation_errors():
            if any(field == 'kind' for field, _ in rs.retrieve_validation_errors()):
                rs.notify("error", n_("Unknown questionnaire kind."))
                return self.redirect(rs, "event/show_event")
            else:
                # we want to render the errors from reorder_questionnaire on this page,
                # so we only redirect to another page if 'kind' does not pass validation
                pass
        questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)[kind]
        redirects = {
            const.QuestionnaireUsages.registration: "event/configure_registration",
            const.QuestionnaireUsages.additional: "event/configure_additional_questionnaire",
        }
        if not questionnaire:
            rs.notify("info", n_("No questionnaire rows of this kind found."))
            return self.redirect(rs, redirects[kind])
        return self.render(
            rs,
            "questionnaire/reorder_questionnaire",
            {'questionnaire': questionnaire, 'kind': kind, 'redirect': redirects[kind]},
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("order", "kind")
    def reorder_questionnaire(
        self,
        rs: RequestState,
        event_id: int,
        kind: const.QuestionnaireUsages,
        order: vtypes.IntCSVList,
    ) -> Response:
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)[
            kind
        ].as_dicts()

        if not set(order) == set(range(len(questionnaire))):
            rs.append_validation_error((
                "order",
                ValueError(n_("Every row must occur exactly once.")),
            ))
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        new_questionnaire = [questionnaire[i] for i in order]
        code = self.eventproxy.set_questionnaire(rs, event_id, kind, new_questionnaire)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/reorder_questionnaire_form", {'kind': kind})
