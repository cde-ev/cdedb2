#!/usr/bin/env python3

"""
The `EventQuestionnaireMixin` subclasses the `EventBaseFrontend` and provides endpoints
for configuring and filling in the different kinds of questionnaires offered for an
event.
"""

import abc
import decimal
from types import SimpleNamespace as sn
from typing import TYPE_CHECKING, cast

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.backend.event.registration import ComplexRegistrationFee
from cdedb.common import (
    CdEDBObject,
    RequestState,
    get_hash,
    json_serialize,
    merge_dicts,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.privileges import EventPrivileges, is_event_access_limited
from cdedb.common.roles import Roles
from cdedb.common.sorting import mixed_existence_sorter
from cdedb.frontend.common import (
    REQUESTdata,
    access,
    check_validation as check,
    drow_basename,
    drow_create,
    drow_delete,
    drow_last_index,
    drow_name,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend, event_guard

if TYPE_CHECKING:
    from cdedb.frontend.event.registration import RegisterParams


class EventQuestionnaireMixin(EventBaseFrontend):
    def _prepare_questionnaire_form(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> tuple[models.questionnaire.QuestionnaireContainer, str]:
        """Helper to retrieve some data for questionnaire configuration."""
        all_questionnaires = self.eventproxy.get_all_questionnaires(rs, event_id)
        current = {
            drow_name(key, i, kind.name): value
            for kind, questionnaire in all_questionnaires.items()
            for i, entry in enumerate(questionnaire)
            for key, value in entry.as_dict().items()
        }
        merge_dicts(rs.values, current)
        # Determine the max of previously submitted rows and current rows.
        for kind in const.QuestionnaireUsages:
            max_index = 0
            while drow_name("role", max_index, kind.name) in rs.values:
                max_index += 1
            rs.values[drow_basename("current", kind.name)] = max_index

        checksum = get_hash(json_serialize(all_questionnaires).encode())

        return (all_questionnaires, checksum)

    @access(Roles.event)
    @event_guard(EventPrivileges.basic_read)
    def configure_questionnaire_form(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        kind: const.QuestionnaireUsages | None = None,
    ) -> Response:
        all_questionnaires, checksum = self._prepare_questionnaire_form(rs, event_id)

        # This preselects the previously active tab.
        if kind:
            rs.values["nav_tab_active"] = f"#tab_{kind.name}"

        spec_per_role = {
            role: dict(role.get_class().requestdict_fields(creation=True))
            for role in const.QuestionnaireRowRole
        }
        get_roles_with_field = lambda key: [
            role for role, spec in spec_per_role.items() if key in spec
        ]
        drow_classes_by_role = {
            str(kind): kind.get_class().get_drow_html_classes()
            for kind in const.QuestionnaireRowRole
        }
        return self.render(
            rs,
            "questionnaire/configure_questionnaire",
            {
                "all_questionnaires": all_questionnaires,
                "checksum": checksum,
                "drow_classes_by_role": drow_classes_by_role,
                "all_drow_classes": set().union(*drow_classes_by_role.values()),
                "get_roles_with_field": get_roles_with_field,
            },
        )

    def _extract_questionnaire_row(
        self, rs: RequestState, drow_id: int, kind: const.QuestionnaireUsages
    ) -> CdEDBObject | None:

        if unwrap(request_extractor(rs, {drow_delete(drow_id, kind.name): bool})):
            return None
        qrrn = const.QuestionnaireRowRole | None
        role: qrrn = unwrap(
            request_extractor(
                rs,
                {drow_name("role", drow_id, kind.name): (qrrn)},
            )
        )
        if not role:
            return None
        cls = role.get_class()
        spec = cls.requestdict_fields(creation=True)
        data = request_extractor(
            rs,
            {drow_name(key, drow_id, kind.name): val for key, val in spec},  # type: ignore[misc]
            postpone_validation=True,
        )
        # Pass 'drow_id' as 'id' to correctly map validation errors.
        return {key: data[drow_name(key, drow_id, kind.name)] for key, _ in spec} | {
            "id": drow_id
        }

    @access(Roles.event, modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("submitted_kind", "checksum")
    def configure_questionnaire(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        submitted_kind: const.QuestionnaireUsages,
        checksum: str | None,
    ) -> Response:
        """Set questionnaires (of all kinds at once)."""
        all_questionnaires, old_checksum = self._prepare_questionnaire_form(
            rs, event_id
        )
        if rs.has_validation_errors():
            return self.configure_questionnaire_form(rs, event_id, kind=submitted_kind)

        new_all_questionnaires = {}
        for kind in const.QuestionnaireUsages:
            questionnaire = all_questionnaires[kind]

            new_questionnaire = []
            marker = 0
            while True:
                key = drow_name("role", marker, kind.name)
                if unwrap(request_extractor(rs, {key: bool})):
                    if row := self._extract_questionnaire_row(rs, marker, kind):
                        new_questionnaire.append(row)
                else:
                    # The request_extractor check leaves an entry in the values that
                    #  we do not want.
                    rs.values.pop(key, None)
                    if marker >= len(questionnaire):
                        break
                marker += 1

            marker = 1
            while marker < 2**10:
                if unwrap(
                    request_extractor(rs, {drow_create(-marker, kind.name): bool})
                ):
                    if row := self._extract_questionnaire_row(rs, -marker, kind):
                        new_questionnaire.append(row)
                    marker += 1
                else:
                    break
            rs.values[drow_last_index(kind.name)] = marker - 1

            tmp = {int(row["pos"]): row for row in new_questionnaire}
            new_all_questionnaires[kind] = [
                tmp[pos] for pos in mixed_existence_sorter(tmp)
            ]

        new_all_questionnaires = check(
            rs,
            vtypes.AllQuestionnaires,
            new_all_questionnaires,
            all_questionnaires=all_questionnaires,
        )

        if rs.has_validation_errors() or new_all_questionnaires is None:
            return self.configure_questionnaire_form(rs, event_id, kind=submitted_kind)

        if checksum != old_checksum:
            rs.notify(
                "warning",
                n_(
                    "The configuration changed in the meantime. Saving your changes will"
                    " override those changes. Submit form again to proceed."
                ),
            )
            return self.configure_questionnaire_form(rs, event_id, kind=submitted_kind)

        code = self.eventproxy.set_questionnaires(rs, event_id, new_all_questionnaires)
        rs.notify_return_code(code)
        return self.redirect(
            rs,
            "event/configure_questionnaire_form",
            anchor=f"tab_{submitted_kind.name}",
        )

    @abc.abstractmethod
    def get_register_params(self, rs: RequestState) -> "RegisterParams": ...

    @access(Roles.event)
    @REQUESTdata("preview")
    def additional_questionnaire_form(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        preview: bool = False,
        internal: bool = False,
    ) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, "event/show_event")
        kind = const.QuestionnaireUsages.additional
        add_questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)[kind]
        wish_data = None
        reg_params = self.get_register_params(rs)
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
                if field.id in add_questionnaire.get_field_ids():
                    wish_data = self._get_user_lodgement_wishes(rs, event_id)
        else:
            if not self.is_privileged(rs, EventPrivileges.basic_read):
                raise werkzeug.exceptions.Forbidden(n_("Must be orga to use preview."))
            if not rs.ambience['event'].use_additional_questionnaire:
                rs.notify("info", n_("Questionnaire is not enabled yet."))
        return self.render(
            rs,
            "questionnaire/additional_questionnaire",
            {
                "questionnaire": add_questionnaire,
                "kind": kind,
                "preview": preview,
                "lodgement_wishes": wish_data or {},
                **reg_params,
            },
        )

    @access(Roles.event, modi={"POST"})
    def additional_questionnaire(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> Response:
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

        change_note = "Fragebogen durch Teilnehmer:in bearbeitet."
        code = self.eventproxy.set_registration(
            rs, {'id': registration_id, 'fields': data}, change_note, orga_input=False
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "event/additional_questionnaire_form")

    @access(Roles.event)
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("kind")
    def reorder_questionnaire_form(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        kind: const.QuestionnaireUsages | None = None,
    ) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        # This preselects the previously active tab.
        if kind:
            rs.values["nav_tab_active"] = f"#tab_{kind.name}"

        all_questionnaires = self.eventproxy.get_all_questionnaires(rs, event_id)

        # Fake fee for the fee preview mockup.
        fake_complex_fee = ComplexRegistrationFee(
            fees=[
                (
                    cast(models.EventFee, sn(id=-1, kind=const.EventFeeType.common)),
                    decimal.Decimal(200),
                ),
                (
                    cast(
                        models.EventFee,
                        sn(id=-2, kind=const.EventFeeType.solidary_reduction),
                    ),
                    decimal.Decimal(-50),
                ),
            ],
            visual_debug={},
        )
        return self.render(
            rs,
            "questionnaire/reorder_questionnaire",
            {
                'all_questionnaires': all_questionnaires,
                'fake_complex_fee': fake_complex_fee,
                **self.get_course_choice_params(rs, event_id),
            },
        )

    @access(Roles.event, modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("submitted_kind")
    def reorder_questionnaire(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        submitted_kind: const.QuestionnaireUsages,
    ) -> Response:
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=submitted_kind)

        all_questionnaires = self.eventproxy.get_all_questionnaires(
            rs, event_id
        ).as_dict()

        new_all_questionnaires = {}
        for kind in const.QuestionnaireUsages:
            key = drow_basename("order", kind.name)
            order = request_extractor(rs, {key: list[int]})[key]
            expected = set(range(len(all_questionnaires[kind])))

            if order is not None:
                if set(order) != expected or len(order) != len(expected):
                    rs.append_validation_error((
                        key,
                        ValueError(n_("Every row must occur exactly once.")),
                    ))
                else:
                    new_all_questionnaires[kind] = [
                        all_questionnaires[kind][i] for i in order
                    ]

        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id)

        code = self.eventproxy.set_questionnaires(rs, event_id, new_all_questionnaires)
        rs.notify_return_code(code)
        return self.redirect(
            rs,
            "event/reorder_questionnaire_form",
            anchor=f"tab_{submitted_kind.name}",
        )
