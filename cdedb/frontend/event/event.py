#!/usr/bin/env python3

"""
The `EventEventMixin` subclasses the `EventBaseFrontend` and provides endpoints for
managing an event itself, including event parts and course tracks.

This also includes all functionality directly avalable on the `show_event` page.
"""

import copy
import datetime
import json
from collections.abc import Collection
from typing import Literal, cast

import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.routing
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    DEFAULT_NUM_COURSE_CHOICES,
    CdEDBObject,
    RequestState,
    get_mandatory_form_fields,
    merge_dicts,
    now,
    unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.parse.util import Accounts
from cdedb.common.privileges import EventPrivileges
from cdedb.common.query import (
    Query,
    QueryConstraint,
    QueryOperators,
    QueryScope,
    QuerySpecEntry,
)
from cdedb.common.query.log_filter import EventLogFilter
from cdedb.common.sorting import xsorted
from cdedb.filter import cdedbid_filter, iban_filter
from cdedb.frontend.common import (
    Headers,
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    TransactionObserver,
    access,
    ack_delete,
    cdedburl,
    check_validation as check,
    drow_name,
    inspect_validation as inspect,
    periodic,
    process_dynamic_input,
)
from cdedb.frontend.event.base import EventBaseFrontend, event_guard
from cdedb.models.common import CdEDataclass
from cdedb.models.ml import (
    EventAssociatedMailinglist,
    EventOrgaMailinglist,
    Mailinglist,
)


class EventEventMixin(EventBaseFrontend):
    @access("anonymous")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        current_event_list = self.eventproxy.list_events(
            rs, current=True, archived=False
        )
        other_event_list = self.eventproxy.list_events(
            rs, current=False, archived=False
        )

        events_registration: dict[int, bool | None] = {}
        events_payment_pending: dict[int, bool] = {}
        if "event" in rs.user.roles:
            for event_id in current_event_list:
                events_registration[event_id], events_payment_pending[event_id] = (
                    self.eventproxy.get_registration_payment_info(rs, event_id)
                )

        current_events = [
            event
            for event in self.eventproxy.get_events(rs, current_event_list).values()
            if event.is_visible_for(
                rs.user,
                is_registered=bool(events_registration.get(event.id)),
                privileged=False,
            )
        ]
        other_events = [
            event
            for event in self.eventproxy.get_events(rs, other_event_list).values()
            if event.is_visible_for(
                rs.user,
                is_registered=bool(events_registration.get(event.id, False)),
                privileged=False,
            )
        ]
        orga_events = [
            event
            for event in self.eventproxy.get_events(rs, rs.user.orga).values()
            if event.is_current_for_orga()
        ]
        caretaker_events = [
            event
            for event in self.eventproxy.get_events(rs, rs.user.caretaker).values()
            if event.is_current_for_orga()
        ]

        return self.render(
            rs,
            "event/index",
            {
                'current_events': current_events,
                'orga_events': orga_events,
                'caretaker_events': caretaker_events,
                'other_events': other_events,
                'events_registration': events_registration,
                'events_payment_pending': events_payment_pending,
            },
        )

    @access("anonymous")
    def list_events(self, rs: RequestState) -> Response:
        """List all events organized via DB."""
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)

        events_registrations: dict[vtypes.ID, int] = {}
        if self.is_admin(rs) or 'event_helper' in rs.user.realm_roles.get('event', {}):
            for event in events.values():
                regs = self.eventproxy.list_registrations(rs, event.id)
                events_registrations[event.id] = len(regs)

        def querylink(event_id: vtypes.EventID) -> str:
            query = Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=events[event_id]),
                ("persona.given_names", "persona.family_name"),
                (),
                (("persona.family_name", True), ("persona.given_names", True)),
            )
            params = query.serialize_to_url()
            params['event_id'] = event_id
            return cdedburl(rs, 'event/registration_query', params)

        return self.render(
            rs,
            "event/list_events",
            {
                'events': events,
                'events_registrations': events_registrations,
                'querylink': querylink,
            },
        )

    @access("anonymous")
    def show_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Display event organized via DB."""
        params: CdEDBObject = {}
        is_registered = False
        if "event" in rs.user.roles:
            params['orgas'] = self.coreproxy.get_personas(
                rs, rs.ambience['event'].orgas
            )
            params['caretakers'] = self.coreproxy.get_personas(
                rs, rs.ambience['event'].caretakers
            )
            is_registered = bool(
                self.eventproxy.list_registrations(rs, event_id, rs.user.persona_id)
            )
        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs, rs.ambience['event'])
            params['participant_list'] = self.mlproxy.verify_existence(
                rs, ml_data.address
            )
        if self.is_privileged(rs, EventPrivileges.basic_read):
            params['minor_form_present'] = self.eventproxy.has_minor_form(rs, event_id)
        if self.is_privileged(rs, EventPrivileges.all_read):
            params['constraint_violations'] = self.get_constraint_violations(
                rs,
                rs.ambience['event'],
                registration_id=None,
                course_id=None,
                lodgement_id=None,
            )
        elif not rs.ambience['event'].is_visible_for(
            rs.user, is_registered, privileged=True
        ):
            raise werkzeug.exceptions.Forbidden(n_("The event is not published yet."))
        return self.render(rs, "event/show_event", params)

    @access("event")
    @REQUESTdata("event_id", "endpoint", "args")
    def redirect_event(
        self, rs: RequestState, event_id: vtypes.EventID, endpoint: str, args: str
    ) -> Response:
        original_params = json.loads(args.replace("'", '"')) if args else {}
        original_event_id = original_params.get("event_id")
        params: CdEDBObject = original_params
        if rs.has_validation_errors() or not event_id:
            rs.notify("error", rs.gettext("Unknown event."))
            default_endpoint = "event/list_events"
        else:
            default_endpoint = "event/show_event"
            if not original_event_id:
                # If coming from no event, override original endpoint.
                endpoint = default_endpoint
            if original_event_id != event_id:
                # If going to a (different) event, drop subentity params.

                # If we have a registration id try to find a registration for the
                #  same persona for the new event.
                new_reg_id = None
                if reg_id := params.get("registration_id"):
                    reg = self.eventproxy.get_registration(rs, reg_id)
                    persona_id = reg["persona_id"]
                    new_reg_id = self.eventproxy.get_registration_id(
                        rs, persona_id=persona_id, event_id=event_id
                    )

                params = {"event_id": event_id}
                if new_reg_id:
                    params["registration_id"] = new_reg_id
        try:
            return self.redirect(rs, endpoint or default_endpoint, params)
        except werkzeug.routing.exceptions.BuildError:
            if not rs.notifications:
                rs.notify("info", n_("Could not redirect to entity page."))
            return self.redirect(rs, default_endpoint, params)

    @access("event")
    @event_guard(EventPrivileges.basic_read)
    def change_event_form(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['event'].as_dict())

        fields = self._valid_event_part_fields(
            models.Event, fields=rs.ambience['event'].fields
        )
        accounts = [
            (str(account), f"{iban_filter(account.value)} ({account.get_bank()})")
            for account in Accounts.get_event_accounts()
        ]
        return self.render(
            rs,
            "event/change_event",
            {
                'accounts': accounts,
                'fields': fields,
            },
            models.Event.mandatory_form_fields(creation=False),
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(
        *models._EventConfigurationMixin.requestdict_fields(creation=False)
    )
    def change_event(
        self, rs: RequestState, event_id: vtypes.EventID, data: CdEDBObject
    ) -> Response:
        """Modify an event organized via DB."""
        data = check(
            rs,
            cast(type[CdEDataclass], models._EventConfigurationMixin),  # abstract model
            data,
            event=rs.ambience['event'],
        )
        if (
            data
            and data['shortname']
            and data['shortname'] != rs.ambience['event'].shortname
            and self.eventproxy.verify_shortname_existence(rs, data['shortname'])
        ):
            rs.append_validation_error(
                (
                    'shortname',
                    ValueError(
                        n_("Shortname already in use for another event."),
                    ),
                ),
            )
        if rs.has_validation_errors():
            return self.change_event_form(rs, event_id)
        assert data is not None

        code = self.eventproxy.set_event(rs, event_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    @event_guard(EventPrivileges.basic_read)
    @REQUESTdata("edit")
    def show_free_texts(
        self, rs: RequestState, event_id: vtypes.EventID, edit: str | None
    ) -> Response:
        rs.ignore_validation_errors()
        return self.render(rs, "event/show_free_texts", {'edit': edit})

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.free_texts_write)
    @REQUESTdata("free_text_key", "free_text_value")
    def change_free_text(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        free_text_key: str,
        free_text_value: str | None,
    ) -> Response:
        change_notes_by_key = {
            "description": "Beschreibung geändert.",
            "notes": "Orga-Notizen geändert.",
            "registration_status_text": 'Freitext "Meine Anmeldung" geändert.',
            "mail_text": 'Freitext "Anmeldebestätigung" geändert.',
            "participant_info": "Teilnehmenden-Infos geändert.",
            "field_definition_notes": "Notizen zu Datenfeldern geändert.",
            "questionnaire_notes": "Notizen zu Fragebögen geändert.",
        }
        if (
            rs.has_validation_errors() or free_text_key not in change_notes_by_key
        ):  # pragma: no cover
            # No way to tell where we came from.
            rs.notify("error", n_("Invalid free text key."))
            return self.redirect(rs, "event/show_free_texts")
        update = {
            free_text_key: free_text_value,
        }
        code = self.eventproxy.set_event_free_texts(
            rs, event_id, update, change_notes_by_key[free_text_key]
        )
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_free_texts")

    @access("event")
    def get_minor_form(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Retrieve minor form."""
        is_registered = bool(
            self.eventproxy.list_registrations(rs, event_id, rs.user.persona_id)
        )
        if not rs.ambience['event'].is_visible_for(
            rs.user, is_registered, privileged=True
        ):
            raise werkzeug.exceptions.Forbidden(n_("The event is not published yet."))
        path = self.eventproxy.get_minor_form_path(rs, event_id)
        return self.send_file(
            rs,
            path=path,
            mimetype="application/pdf",
            filename=f"Elternbrief CdE {rs.ambience['event'].shortname}.pdf",
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTfile("minor_form")
    @REQUESTdata("delete")
    @ack_delete(omit_error=True, passthrough=True)
    def change_minor_form(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        minor_form: werkzeug.datastructures.FileStorage,
        delete: bool,
        ack_delete: bool,
    ) -> Response:
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check(rs, vtypes.PDFFile | None, minor_form, "minor_form")
        if not minor_form and not delete:
            rs.append_validation_error((
                "minor_form",
                ValueError(n_("Must not be empty.")),
            ))
        if not minor_form and delete and not ack_delete:
            rs.append_validation_error((
                "ack_delete",
                ValueError(n_("Must be checked.")),
            ))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.change_minor_form(rs, event_id, minor_form)
        rs.notify_return_code(
            code,
            success=n_("Minor form updated."),
            info=n_("Minor form has been removed."),
            error=n_("Nothing to remove."),
        )
        return self.redirect(rs, "event/show_event")

    @access("event")
    def list_event_helpers(self, rs: RequestState) -> Response:
        event_helper_ids = self.eventproxy.get_event_helpers(rs)
        event_helpers = self.coreproxy.get_personas(rs, event_helper_ids)
        return self.render(
            rs, 'event/list_event_helpers', {'event_helpers': event_helpers}
        )

    @access("event_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def add_event_helper(
        self, rs: RequestState, persona_id: vtypes.PersonaID
    ) -> Response:
        """Make an additional persona become event helper."""
        if rs.has_validation_errors():
            # Shortcircuit if we have got no workable cdedbid
            return self.list_event_helpers(rs)
        try:
            self.eventproxy.validate_event_persona_ids(rs, {persona_id})
        except ValueError as e:
            rs.append_validation_error(('persona_id', e))
        if rs.has_validation_errors():
            return self.list_event_helpers(rs)
        code = self.eventproxy.add_event_helpers(rs, {persona_id})
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/list_event_helpers")

    @access("event_admin", modi={"POST"})
    @REQUESTdata("persona_id")
    def remove_event_helper(
        self, rs: RequestState, persona_id: vtypes.PersonaID
    ) -> Response:
        """Remove a persona as event helper.

        This is only available for admins.
        """
        if rs.has_validation_errors():
            return self.list_event_helpers(rs)
        code = self.eventproxy.remove_event_helper(rs, persona_id)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/list_event_helpers")

    @access("event")
    @event_guard(
        EventPrivileges.orgas_change,
        EventPrivileges.caretakers_change,
        EventPrivileges.basic_write,
    )
    def manage_roles(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        params = {}
        for role in ("orgas", "caretakers", "checkin_helpers"):
            params[role] = self.coreproxy.get_personas(
                rs, getattr(rs.ambience['event'], role)
            )
        return self.render(rs, 'event/manage_roles', params)

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.orgas_change)
    @REQUESTdata("orga_ids")
    def add_orgas(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        orga_ids: list[vtypes.PersonaID],
    ) -> Response:
        return self._add_event_roles(rs, event_id, orga_ids, role='orga')

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.caretakers_change)
    @REQUESTdata("caretaker_ids")
    def add_caretakers(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        caretaker_ids: list[vtypes.PersonaID],
    ) -> Response:
        return self._add_event_roles(rs, event_id, caretaker_ids, role='caretaker')

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("checkin_helper_ids")
    def add_checkin_helpers(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        checkin_helper_ids: list[vtypes.PersonaID],
    ) -> Response:
        return self._add_event_roles(
            rs, event_id, checkin_helper_ids, role='checkin_helper'
        )

    def _add_event_roles(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        persona_ids: list[vtypes.PersonaID],
        role: Literal["orga", "caretaker", "checkin_helper"],
    ) -> Response:
        # Check privileges
        if role == 'caretaker':
            if not self.is_privileged(rs, EventPrivileges.caretakers_change):
                raise werkzeug.exceptions.Forbidden()
        elif role == 'orga':
            if not self.is_privileged(rs, EventPrivileges.orgas_change):
                raise werkzeug.exceptions.Forbidden()
        elif role == 'checkin_helper':
            if not self.is_privileged(rs, EventPrivileges.basic_write):
                raise werkzeug.exceptions.Forbidden()
        else:
            raise RuntimeError(n_("Impossible."))

        if rs.has_validation_errors():
            # Shortcircuit if we have got no workable ids.
            return self.manage_roles(rs, event_id)
        try:
            self.eventproxy.validate_event_persona_ids(rs, persona_ids)
        except ValueError as e:
            rs.append_validation_error((f"{role}_ids", e))
        if rs.has_validation_errors():
            return self.manage_roles(rs, event_id)

        persona_ids = set(persona_ids) - getattr(rs.ambience['event'], f"{role}s")
        code = self.eventproxy.add_event_roles(rs, event_id, persona_ids, role)

        if not persona_ids:
            rs.notify("info", n_("Action had no effect."))
        else:
            rs.notify_return_code(code)

        if code and persona_ids and role != 'checkin_helper':
            personas = self.coreproxy.get_personas(rs, persona_ids)
            if role == 'caretaker':
                role_str = "Betreuer"
            else:
                role_str = "Orgas"
            subject = f"{len(persona_ids)} {role_str} hinzugefügt ({rs.ambience['event'].shortname})"
            to = [self.conf["EVENT_ADMIN_ADDRESS"]]
            if rs.ambience['event'].orga_address:
                to.append(rs.ambience['event'].orga_address)
            self.do_mail(
                rs,
                "orgas_added",
                {'To': to, 'Subject': subject},
                {
                    'personas': personas,
                    'event': rs.ambience['event'],
                    'role_str': role_str,
                },
            )
        return self.redirect(rs, "event/manage_roles")

    @periodic("cleanup_event_checkin_helpers", period=4)
    def cleanup_event_checkin_helpers(
        self, rs: RequestState, state: CdEDBObject
    ) -> CdEDBObject:
        events = self.eventproxy.get_events(rs, self.eventproxy.list_events(rs))

        cutoff = now() - self.conf["EVENT_CHECKIN_HELPER_DURATION"]
        count = 0
        for event in events.values():
            for checkin_helper_id in event.checkin_helpers:
                log_filer = EventLogFilter(
                    codes=[const.EventLogCodes.checkin_helper_added],
                    persona_id=checkin_helper_id,
                    event_id=event.id,
                )
                _, log_entries = self.eventproxy.retrieve_log(rs, log_filer)
                if not log_entries:
                    self.logger.error(
                        f"Event '{event.shortname}' has a checkin helper"
                        f" ({cdedbid_filter(checkin_helper_id)}) with no ctime."
                    )
                elif log_entries[-1]["ctime"] < cutoff:
                    count += self.eventproxy.remove_event_role(
                        rs, event.id, checkin_helper_id, 'checkin_helper'
                    )
        if count > 0:
            self.logger.info(f"Removed {count} checkin helpers.")
        return state

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.orgas_change)
    @REQUESTdata("orga_id")
    @ack_delete()
    def remove_orga(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        orga_id: vtypes.PersonaID,
    ) -> Response:
        """Remove a persona as orga of an event.

        This is only available for admins and caretakers.
        This can drop your own orga role.
        """
        if rs.has_validation_errors():
            return self.manage_roles(rs, event_id)
        code = self.eventproxy.remove_event_role(rs, event_id, orga_id, 'orga')
        rs.notify_return_code(code, info=n_("Action had no effect."))
        if code:
            orga = self.coreproxy.get_persona(rs, orga_id)
            subject = f"Orga entfernt ({rs.ambience['event'].shortname})"
            to = [self.conf["EVENT_ADMIN_ADDRESS"]]
            if rs.ambience['event'].orga_address:
                to.append(rs.ambience['event'].orga_address)
            self.do_mail(
                rs,
                "orga_removed",
                {'To': to, 'Subject': subject},
                {
                    'orga': orga,
                    'event': rs.ambience['event'],
                    'as_caretaker': False,
                },
            )
        return self.redirect(rs, "event/manage_roles")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.caretakers_change)
    @REQUESTdata("caretaker_id")
    @ack_delete()
    def remove_caretaker(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        caretaker_id: vtypes.PersonaID,
    ) -> Response:
        """Remove a persona as caretaker of an event.

        This is only available for admins. This can drop your own caretaker role.
        """
        if rs.has_validation_errors():
            return self.manage_roles(rs, event_id)
        code = self.eventproxy.remove_event_role(
            rs, event_id, caretaker_id, 'caretaker'
        )
        rs.notify_return_code(code, info=n_("Action had no effect."))
        if code:
            orga = self.coreproxy.get_persona(rs, caretaker_id)
            subject = f"Betreuer entfernt ({rs.ambience['event'].shortname})"
            to = [self.conf["EVENT_ADMIN_ADDRESS"]]
            if rs.ambience['event'].orga_address:
                to.append(rs.ambience['event'].orga_address)
            self.do_mail(
                rs,
                "orga_removed",
                {'To': to, 'Subject': subject},
                {
                    'orga': orga,
                    'event': rs.ambience['event'],
                    'as_caretaker': True,
                },
            )
        return self.redirect(rs, "event/manage_roles")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("checkin_helper_id")
    @ack_delete()
    def remove_checkin_helper(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        checkin_helper_id: vtypes.PersonaID,
    ) -> Response:
        """Remove a persona as checkin helper of an event.

        This is only available for admins. This can drop your own caretaker role.
        """
        if rs.has_validation_errors():
            return self.manage_roles(rs, event_id)
        code = self.eventproxy.remove_event_role(
            rs, event_id, checkin_helper_id, 'checkin_helper'
        )
        rs.notify_return_code(code, info=n_("Action had no effect."))
        return self.redirect(rs, "event/manage_roles")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("orgalist", "part_group_id")
    def create_event_mailinglist(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        orgalist: bool = False,
        part_group_id: int | None = None,
    ) -> Response:
        """Create a default mailinglist for the event."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not rs.ambience['event'].orgas:
            rs.notify('error', n_("Must have orgas in order to create a mailinglist."))
            return self.redirect(rs, "event/show_event")

        ml_data = self._get_mailinglist_setter(
            rs,
            rs.ambience['event'],
            orgalist=orgalist,
            part_group_id=part_group_id,
        )
        if not self.mlproxy.verify_existence(rs, ml_data.address):
            code = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (
                n_("Orga mailinglist created.")
                if orgalist
                else n_("Participant mailinglist created.")
            )
            rs.notify_return_code(code, success=msg)
            if code and orgalist:
                self.eventproxy.set_event(
                    rs, event_id, {'orga_address': ml_data.address}
                )
        else:
            rs.notify(
                "info",
                n_("Mailinglist %(address)s already exists."),
                {'address': ml_data.address},
            )
        if part_group_id:
            return self.redirect(rs, "event/group_summary")
        return self.redirect(rs, "event/show_event")

    def _deletion_blocked_parts(
        self, rs: RequestState, event: models.Event
    ) -> set[int]:
        """Returns all part_ids from parts of a given event which must not be deleted.

        Extracts all parts of the given event from the database and checks if there are
        blockers preventing their deletion.

        :returns: All part_ids whose deletion is blocked.
        """
        blocked_parts: set[int] = set()
        if len(rs.ambience['event'].parts) == 1:
            blocked_parts.add(unwrap(rs.ambience['event'].parts.keys()))
        course_ids = self.eventproxy.list_courses(rs, event.id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        # referenced tracks block part deletion
        for course in courses.values():
            for track_id in course.segments:
                blocked_parts.add(rs.ambience['event'].tracks[track_id].part_id)
        part_fees = models.EventFee.get_fees_per_entity(event).parts
        for part_id, fees in part_fees.items():
            if fees:
                blocked_parts.add(part_id)
        return blocked_parts

    def _deletion_blocked_tracks(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> set[int]:
        """Returns all track_ids from tracks of a given event which must not be deleted.

        Extracts all tracks of the given event from the database and checks if there are
        blockers preventing their deletion.

        :returns: All track_ids whose deletion is blocked.
        """
        blocked_tracks: set[int] = set()
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        for course in courses.values():
            blocked_tracks.update(course.segments)
        for tg in rs.ambience['event'].track_groups.values():
            blocked_tracks.update(tg.tracks)
        return blocked_tracks

    @access("event")
    @event_guard(EventPrivileges.basic_read)
    def part_summary(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Display a comprehensive overview of all parts of a given event."""
        referenced_parts = self._deletion_blocked_parts(rs, rs.ambience["event"])
        may_change_part_ids = self.is_privileged(
            rs, EventPrivileges.basic_write
        ) and not self.eventproxy.has_registrations(rs, event_id)

        return self.render(
            rs,
            "event/part_summary",
            {
                'referenced_parts': referenced_parts,
                'may_change_part_ids': may_change_part_ids,
            },
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @ack_delete()
    def delete_part(
        self, rs: RequestState, event_id: vtypes.EventID, part_id: int
    ) -> Response:
        """Delete a given part."""
        if rs.has_validation_errors():
            return self.part_summary(rs, event_id)
        if self.eventproxy.has_registrations(rs, event_id):
            rs.notify("error", n_("Registrations exist, cannot delete event parts."))
            return self.part_summary(rs, event_id)
        if part_id in self._deletion_blocked_parts(rs, rs.ambience["event"]):
            rs.notify("error", n_("This part can not be deleted."))
            return self.part_summary(rs, event_id)

        code = self.eventproxy.set_event(rs, event_id, {'parts': {part_id: None}})
        rs.notify_return_code(code)

        return self.redirect(rs, "event/part_summary")

    @staticmethod
    def _valid_event_part_fields(
        *entities: type[models.EventDataclass],
        fields: models.CdEDataclassMap[models.EventField],
    ) -> dict[str, list[models.EventField]]:
        ret = {}
        for entity in entities:
            for field_name, field_spec in models.EventFieldSpec.get_specs(
                entity
            ).items():
                ret[field_name] = [
                    field for field in fields.values() if field_spec.accepts(field)
                ]
        return ret

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def add_part_form(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        if rs.ambience['event'].is_balanced:
            rs.notify("error", n_("Event is balanced. May not create new part."))
            return self.redirect(rs, "event/part_summary")
        if self.eventproxy.has_registrations(rs, event_id):
            rs.notify("error", n_("Registrations exist, no part creation possible."))
            return self.redirect(rs, "event/show_event")
        fields = self._valid_event_part_fields(
            models.EventPart, models.CourseTrack, fields=rs.ambience['event'].fields
        )
        mandatory_fields = models.EventPart.mandatory_form_fields(creation=True)
        return self.render(
            rs,
            "event/add_part",
            {
                'fields': fields,
                'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES,
            },
            mandatory_fields=mandatory_fields,
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("fee")
    @REQUESTdatadict(*models.EventPart.requestdict_fields(creation=True))
    def add_part(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        data: CdEDBObject,
        fee: vtypes.NonNegativeDecimal,
    ) -> Response:
        if rs.ambience['event'].is_balanced:
            rs.ignore_validation_errors()
            rs.notify("error", n_("Event is balanced. May not create new part."))
            return self.redirect(rs, "event/part_summary")
        if self.eventproxy.has_registrations(rs, event_id):
            raise ValueError(n_("Registrations exist, no part creation possible."))

        data = check(
            rs, models.EventPart, data, creation=True, event=rs.ambience["event"]
        )
        if rs.has_validation_errors():
            return self.add_part_form(rs, event_id)
        assert data is not None

        recipients = []
        if rs.ambience['event'].orga_address:
            recipients.append(rs.ambience['event'].orga_address)
        with TransactionObserver(rs, self, "create_part", recipients=recipients):
            code = self.eventproxy.set_event(rs, event_id, {'parts': {-1: data}})
            if code:
                new_fee = {
                    'kind': const.EventFeeType.common,
                    'title': data['title'],
                    'notes': "Automatisch erstellt.",
                    'amount': fee,
                    'condition': f"part.{data['shortname']}",
                }
                self.eventproxy.create_event_fee(rs, event_id, new_fee)
        rs.notify_return_code(code)

        return self.redirect(rs, "event/part_summary")

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def change_part_form(
        self, rs: RequestState, event_id: vtypes.EventID, part_id: int
    ) -> Response:
        part = rs.ambience['event'].parts[part_id]

        sorted_track_ids = [e.id for e in xsorted(part.tracks.values())]

        current = part.as_dict()
        del current['tracks']

        # Select the first track by id for every sync track group, disable altering
        #  choices for all others.
        sync_groups = set()
        readonly_synced_tracks = set()
        for track_id, track in xsorted(part.tracks.items()):
            for k, _ in models.CourseTrack.requestdict_fields(creation=None):
                name = drow_name(k, entity_id=track_id, prefix="track")
                current[name] = track.as_dict()[k]
            for tg_id, tg in track.track_groups.items():
                if tg.constraint_type.is_sync():
                    if tg_id in sync_groups:
                        readonly_synced_tracks.add(track_id)
                    else:
                        sync_groups.add(tg_id)
        merge_dicts(rs.values, current)

        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        referenced_tracks = self._deletion_blocked_tracks(rs, event_id)

        fields = self._valid_event_part_fields(
            models.EventPart, models.CourseTrack, fields=rs.ambience['event'].fields
        )
        mandatory_fields = models.EventPart.mandatory_form_fields(
            creation=False
        ) | models.CourseTrack.mandatory_form_fields(creation=False)
        return self.render(
            rs,
            "event/change_part",
            {
                'part_id': part_id,
                'sorted_track_ids': sorted_track_ids,
                'fields': fields,
                'referenced_tracks': referenced_tracks,
                'has_registrations': has_registrations,
                'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES,
                'readonly_synced_tracks': readonly_synced_tracks,
            },
            mandatory_fields=mandatory_fields,
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(*models.EventPart.requestdict_fields(creation=False))
    def change_part(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        part_id: int,
        data: CdEDBObject,
    ) -> Response:
        """Change one part, including the associated tracks and fee modifiers."""
        data = check(rs, models.EventPart, data, event=rs.ambience["event"])
        if rs.has_validation_errors():
            return self.change_part_form(rs, event_id, part_id)
        assert data is not None
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        #
        # process the dynamic track input
        #
        track_existing = rs.ambience['event'].parts[part_id].tracks
        track_data = process_dynamic_input(
            rs,
            models.CourseTrack,
            track_existing,
            spec=dict(models.CourseTrack.requestdict_fields(creation=False)),
            creation_spec=dict(models.CourseTrack.requestdict_fields(creation=True)),
            additional_validation={"event": rs.ambience["event"]},
            prefix="track",
        )

        if rs.has_validation_errors():
            return self.change_part_form(rs, event_id, part_id)

        deleted_tracks = {anid for anid in track_data if track_data[anid] is None}
        new_tracks = {anid for anid in track_data if anid < 0}
        if deleted_tracks and has_registrations:
            raise ValueError(n_("Registrations exist, no track deletion possible."))
        if deleted_tracks & self._deletion_blocked_tracks(rs, event_id):
            raise ValueError(n_("Some tracks can not be deleted."))
        if new_tracks and has_registrations:
            raise ValueError(n_("Registrations exist, no track creation possible."))

        data['tracks'] = track_data
        part_data = {part_id: data}

        # For every sync track group take the first track by id and propagate it's
        #  number of choices to all tracks in that group.
        sync_groups = set()

        for track_id, track in xsorted(track_data.items()):
            # Only existing tracks are relevant, new ones are not part of a group.
            if track and track_id in track_existing:
                for tg_id, tg in track_existing[track_id].track_groups.items():
                    if tg.constraint_type.is_sync() and tg_id not in sync_groups:
                        sync_groups.add(tg_id)
                        for t_id in tg.tracks:
                            p_id = rs.ambience['event'].tracks[t_id].part_id
                            if p_id not in part_data:
                                part_data[p_id] = {'tracks': {}}
                            if t_id not in part_data[p_id]['tracks']:
                                part_data[p_id]['tracks'][t_id] = {}
                            part_data[p_id]['tracks'][t_id].update({
                                'num_choices': track['num_choices'],
                                'min_choices': track['min_choices'],
                            })

        code = self.eventproxy.set_event(rs, event_id, {'parts': part_data})
        rs.notify_return_code(code)

        return self.redirect(rs, "event/part_summary")

    @staticmethod
    def _get_payment_query_base(
        event: models.Event,
        constraints: Collection[QueryConstraint],
        fee: models.EventFee | None = None,
        kind: (
            const.EventFeeType | const.EventFeeCategory | const.EventFeeBudget | None
        ) = None,
    ) -> Query:
        if isinstance(kind, const.EventFeeType):
            kind_field = f"amount_owed.kind_{kind.name}"
        elif isinstance(kind, const.EventFeeCategory):
            kind_field = f"amount_owed.category_{kind.name}"
        elif isinstance(kind, const.EventFeeBudget):
            kind_field = f"amount_owed.budget_{kind.name}"
        else:
            kind_field = None
        return Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=[
                "persona.id",
                "persona.given_names",
                "persona.family_name",
                "persona.username",
                "reg.payment",
                "reg.remaining_owed",
                "reg.amount_owed",
                "reg.amount_paid",
            ]
            + ([f"fee{fee.id}.amount"] if fee else [])
            + ([kind_field] if kind_field else [])
            + (
                [f"reg_fields.xfield_{event.reimbursement_iban_field.field_name}"]
                if event.reimbursement_iban_field
                else []
            ),
            constraints=constraints,
            order=[
                ("persona.family_name", True),
                ("persona.given_names", True),
            ],
        )

    def _get_payment_query(
        self,
        event: models.Event,
        ids: Collection[int],
        fee_id: int | None,
        kind: const.EventFeeType | const.EventFeeCategory | const.EventFeeBudget | None,
    ) -> Query:
        fee = event.fees.get(fee_id or 0)
        if fee and fee.is_personalized():
            constraints: list[QueryConstraint] = [
                (f"fee{fee.id}.amount", QueryOperators.nonempty, None),
            ]
        elif ids:
            constraints = [
                ("reg.id", QueryOperators.oneof, ids),
            ]
        else:
            # Avoid selecting all registrations.
            constraints = [
                ("reg.id", QueryOperators.empty, None),
            ]
        return self._get_payment_query_base(event, constraints, fee, kind)

    @access("event")
    # TODO Be more lenient here (for finance_admins and auditors)
    @event_guard(EventPrivileges.registrations_stats)
    def fee_summary(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Show a summary of all event fees."""
        fee_stats = self.eventproxy.get_fee_stats(rs, event_id)
        violations = self.get_constraint_violations(rs, rs.ambience['event'])

        return self.render(
            rs,
            "event/fee/fee_summary",
            {
                'fee_stats': fee_stats,
                'violations': violations['violations'],
                'get_query': lambda ids, fee_id, kind: self._get_payment_query(
                    rs.ambience['event'],
                    ids,
                    fee_id,
                    kind,
                ),
            },
        )

    @access("event")
    @event_guard(EventPrivileges.registrations_stats)
    def fee_stats(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Show stats for existing fees."""
        fee_stats = self.eventproxy.get_fee_stats(rs, event_id)

        incomplete_paid = self._get_payment_query_base(
            rs.ambience['event'],
            [
                ("reg.remaining_owed", QueryOperators.greater, 0.00),
                ("reg.amount_paid", QueryOperators.unequal, 0),
            ],
        )
        not_paid = self._get_payment_query_base(
            rs.ambience['event'],
            [
                ("reg.remaining_owed", QueryOperators.greater, 0.00),
                ("reg.amount_paid", QueryOperators.equal, 0),
            ],
        )
        surplus = self._get_payment_query_base(
            rs.ambience['event'],
            [
                ("reg.remaining_owed", QueryOperators.less, 0.00),
            ],
        )

        return self.render(
            rs,
            "event/fee/fee_stats",
            {
                'fee_stats': fee_stats,
                'incomplete_paid': incomplete_paid,
                'not_paid': not_paid,
                'surplus': surplus,
                'get_query': lambda ids, fee_id, kind: self._get_payment_query(
                    rs.ambience['event'],
                    ids,
                    fee_id,
                    kind,
                ),
            },
        )

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdata("personalized")
    def configure_fee_form(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        personalized: bool,
        fee_id: int | None = None,
    ) -> Response:
        """Render form to change or create one event fee."""
        rs.ignore_validation_errors()
        if rs.ambience['event'].is_balanced:
            rs.notify(
                "error", n_("Event is balanced. May not change fee configuration.")
            )
            return self.redirect(rs, "event/fee_summary")
        creation = True
        if fee_id:
            creation = False
            if fee_id not in rs.ambience['event'].fees:
                rs.notify("error", n_("Unknown fee."))
                return self.redirect(rs, "event/fee_summary")
            else:
                merge_dicts(rs.values, rs.ambience['fee'].as_dict())
                personalized = rs.ambience['fee'].is_personalized()
        mandatory_fields = models.EventFee.mandatory_form_fields(creation=creation)
        if not personalized:
            mandatory_fields |= {'amount', 'condition'}
        return self.render(
            rs,
            "event/fee/configure_fee",
            {
                'personalized': personalized,
            },
            mandatory_fields=mandatory_fields,
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write | EventPrivileges.registrations_write)
    @REQUESTdata("personalized")
    @REQUESTdatadict(*models.EventFee.requestdict_fields(creation=None))
    def configure_fee(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        data: CdEDBObject,
        personalized: bool,
        fee_id: vtypes.ID | None = None,
    ) -> Response:
        """Submit changes to or creation of one event fee."""
        if rs.ambience['event'].is_balanced:
            rs.ignore_validation_errors()
            rs.notify(
                "error", n_("Event is balanced. May not change fee configuration.")
            )
            return self.redirect(rs, "event/fee_summary")
        fee_data = check(
            rs,
            models.EventFee,
            data,
            event=rs.ambience['event'],
            all_questionnaires=self.eventproxy.get_all_questionnaires(rs, event_id),
            current=rs.ambience['event'].fees.get(fee_id or -1),
            personalized=personalized,
        )
        if rs.has_validation_errors() or not fee_data:
            return self.render(rs, "event/fee/configure_fee")
        if fee_id:
            code = self.eventproxy.change_event_fee(rs, fee_id, fee_data)
        else:
            code = self.eventproxy.create_event_fee(rs, event_id, fee_data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/fee_summary")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write | EventPrivileges.registrations_write)
    def delete_fee(
        self, rs: RequestState, event_id: vtypes.EventID, fee_id: vtypes.ID
    ) -> Response:
        """Delete one event fee."""
        if rs.ambience['event'].is_balanced:
            rs.notify(
                "error", n_("Event is balanced. May not change fee configuration.")
            )
            return self.redirect(rs, "event/fee_summary")
        if fee_id not in rs.ambience['event'].fees:
            rs.notify("error", n_("Unknown fee."))
            return self.redirect(rs, "event/fee_summary")
        code = self.eventproxy.delete_event_fee(rs, fee_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/fee_summary")

    @access("event")
    @event_guard(EventPrivileges.basic_read)
    def group_summary(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        non_existing_mailinglists = {
            part_group.id
            for part_group in rs.ambience['event'].part_groups.values()
            if part_group.constraint_type == const.EventPartGroupType.mailinglist_link
            and not self.mlproxy.verify_existence(
                rs,
                self._get_mailinglist_setter(
                    rs,
                    rs.ambience['event'],
                    part_group_id=part_group.id,
                ).address,
            )
        }
        return self.render(
            rs,
            "event/group_summary",
            {
                'non_existing_mailinglists': non_existing_mailinglists,
            },
        )

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def add_part_group_form(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> Response:
        return self.render(
            rs,
            "event/configure_part_group",
            {},
            models.PartGroup.mandatory_form_fields(creation=True),
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(*models.PartGroup.requestdict_fields(creation=True))
    def add_part_group(
        self, rs: RequestState, event_id: vtypes.EventID, data: CdEDBObject
    ) -> Response:
        data = check(
            rs, models.PartGroup, data, creation=True, event=rs.ambience["event"]
        )
        if rs.has_validation_errors():
            return self.add_part_group_form(rs, event_id)
        assert data is not None
        code = self.eventproxy.add_part_group(rs, event_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def change_part_group_form(
        self, rs: RequestState, event_id: vtypes.EventID, part_group_id: int
    ) -> Response:
        merge_dicts(rs.values, rs.ambience['part_group'].as_dict())
        # add this to autofill the values correctly (they are readonly anyway)
        merge_dicts(rs.values, {"part_ids": rs.ambience['part_group'].parts.keys()})
        return self.render(
            rs,
            "event/configure_part_group",
            {},
            models.PartGroup.mandatory_form_fields(creation=False),
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(*models.PartGroup.requestdict_fields(creation=False))
    def change_part_group(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        part_group_id: vtypes.ID,
        data: CdEDBObject,
    ) -> Response:
        data["id"] = part_group_id
        data = check(rs, models.PartGroup, data, event=rs.ambience["event"])
        if rs.has_validation_errors():
            return self.change_part_group_form(rs, event_id, part_group_id)
        assert data is not None
        code = self.eventproxy.change_part_group(rs, part_group_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    def delete_part_group(
        self, rs: RequestState, event_id: vtypes.EventID, part_group_id: vtypes.ID
    ) -> Response:
        if rs.has_validation_errors():
            return self.group_summary(rs, event_id)  # pragma: no cover
        code = self.eventproxy.delete_part_group(rs, part_group_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def add_track_group_form(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> Response:
        return self.render(
            rs,
            "event/configure_track_group",
            {},
            models.TrackGroup.mandatory_form_fields(creation=True),
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(*models.TrackGroup.requestdict_fields(creation=True))
    def add_track_group(
        self, rs: RequestState, event_id: vtypes.EventID, data: CdEDBObject
    ) -> Response:
        data = check(
            rs, models.TrackGroup, data, creation=True, event=rs.ambience['event']
        )
        if rs.has_validation_errors():
            return self.add_track_group_form(rs, event_id)
        assert data is not None
        if data[
            "constraint_type"
        ].is_sync() and not self.eventproxy.may_create_ccs_group(rs, data["track_ids"]):
            rs.append_validation_error((
                "track_ids",
                ValueError(
                    n_(
                        "Cannot create CCS group due to incompatible existing course choices."
                    )
                ),
            ))
        if rs.has_validation_errors():
            return self.add_track_group_form(rs, event_id)
        code = self.eventproxy.add_track_group(rs, event_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard(EventPrivileges.basic_write)
    def change_track_group_form(
        self, rs: RequestState, event_id: vtypes.EventID, track_group_id: vtypes.ID
    ) -> Response:
        merge_dicts(rs.values, rs.ambience['track_group'].as_dict())
        # add this to autofill the values correctly (they are readonly anyway)
        merge_dicts(rs.values, {"track_ids": rs.ambience['track_group'].tracks.keys()})
        return self.render(
            rs,
            "event/configure_track_group",
            {},
            models.TrackGroup.mandatory_form_fields(creation=False),
        )

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @REQUESTdatadict(*models.TrackGroup.requestdict_fields(creation=False))
    def change_track_group(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        track_group_id: vtypes.ID,
        data: CdEDBObject,
    ) -> Response:
        data["id"] = track_group_id
        data = check(rs, models.TrackGroup, data, event=rs.ambience["event"])
        if rs.has_validation_errors():
            return self.change_track_group_form(rs, event_id, track_group_id)
        assert data is not None
        code = self.eventproxy.change_track_group(rs, track_group_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.basic_write)
    @ack_delete()
    def delete_track_group(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        track_group_id: vtypes.ID,
    ) -> Response:
        if rs.has_validation_errors():
            return self.group_summary(rs, event_id)  # pragma: no cover
        code = self.eventproxy.delete_track_group(rs, track_group_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @periodic("mail_orgateam_reminders", period=4 * 24)  # once per day
    def mail_orgateam_reminders(
        self, rs: RequestState, store: CdEDBObject
    ) -> CdEDBObject:
        """Send halftime and past event mails to orgateams."""
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)

        def is_halftime(part: models.EventPart) -> bool:
            begin: datetime.date = part.part_begin
            end: datetime.date = part.part_end
            duration = end - begin
            one_day = datetime.timedelta(days=1)
            return begin + duration / 2 <= now().date() < begin + duration / 2 + one_day

        def is_over(part: models.EventPart) -> bool:
            end: datetime.date = part.part_end
            one_day = datetime.timedelta(days=1)
            return end + one_day <= now().date()

        for event_id, event in events.items():
            # take care, since integer keys are serialized to strings!
            if str(event_id) not in store:
                store[str(event_id)] = {}
            if store[str(event_id)].get("did_past_event_reminder"):
                continue
            if not event.orga_address:
                continue

            headers: Headers = {
                "To": (event.orga_address,),
                "Reply-To": self.conf["EVENT_ADMIN_ADDRESS"],
            }
            # send halftime mail (up to one per part)
            if any(is_halftime(part) for part in event.parts.values()):
                headers["Subject"] = (
                    "Halbzeit! Was ihr vor Ende der Akademie nicht vergessen solltet"
                )
                self.do_mail(rs, "halftime_reminder", headers)
            # send past event mail (one per event)
            elif all(is_over(part) for part in event.parts.values()):
                headers["Subject"] = "Wichtige Nach-Aka-Checkliste vom Akademieteam"
                params = {"rechenschafts_deadline": now() + datetime.timedelta(days=90)}
                self.do_mail(rs, "past_event_reminder", headers, params=params)
                store[str(event_id)]["did_past_event_reminder"] = True
        return store

    @staticmethod
    def _get_mailinglist_setter(
        rs: RequestState,
        event: models.Event,
        *,
        orgalist: bool = False,
        part_group_id: int | None = None,
    ) -> Mailinglist:
        """
        Return a dataclass object to create a mailinglist for this event.

        Exactly one of orgalist and part_group_id may be given.

        If orgalist is True, the created list will be an EventOrgaMailinglist.
        Otherwise it will be an EventAssociatedMailinglist (participant mailinglist).
        If part_group_id is given, the list will be limited to that part group.
        """
        if orgalist:
            descr = (
                "Bitte wende Dich bei Fragen oder Problemen, die mit"
                " unserer Veranstaltung zusammenhängen, über diese Liste"
                " an uns."
            )
            orga_ml_data = EventOrgaMailinglist(
                id=vtypes.ID(-1),
                title=f"{event.title} Orgateam",
                local_part=vtypes.EmailLocalPart(f"{event.shortname.lower()}-orga"),
                domain=const.MailinglistDomain.aka,
                description=descr,
                mod_policy=const.ModerationPolicy.unmoderated,
                attachment_policy=const.AttachmentPolicy.allow,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=event.shortname,
                maxsize=EventOrgaMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                event_id=vtypes.EventID(vtypes.ID(event.id)),
                notes=None,
                moderators=event.orgas,
                whitelist=set(),
            )
            return orga_ml_data
        else:
            if part_group_id:
                title = (
                    f"{event.title} Teilnehmende"
                    f" ({event.part_groups[part_group_id].title})"
                )
                local_part = (
                    f"{event.shortname.lower()}"
                    f"-{event.part_groups[part_group_id].shortname.lower()}"
                    f"-all"
                )
                subject_prefix = (
                    f"{event.shortname}-{event.part_groups[part_group_id].shortname}"
                )
            else:
                title = f"{event.title} Teilnehmende"
                local_part = f"{event.shortname.lower()}-all"
                subject_prefix = event.shortname
            link = cdedburl(rs, "event/register", {'event_id': event.id})
            descr = (
                f"Dieser Liste kannst Du nur beitreten, indem Du Dich zu "
                f"unserer [Veranstaltung anmeldest]({link}) und den Status "
                f"*Teilnehmend* erhälst. Auf dieser Liste stehen alle "
                f"Teilnehmenden unserer Veranstaltung; sie kann im Vorfeld "
                f"zum Austausch untereinander genutzt werden."
            )
            participant_ml_data = EventAssociatedMailinglist(
                id=vtypes.ID(-1),
                title=title,
                local_part=vtypes.EmailLocalPart(local_part.replace(" ", "")),
                domain=const.MailinglistDomain.aka,
                description=descr,
                mod_policy=const.ModerationPolicy.non_subscribers,
                attachment_policy=const.AttachmentPolicy.pdf_only,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=subject_prefix,
                maxsize=EventAssociatedMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                event_id=event.id,
                event_part_group_id=cast(vtypes.ID | None, part_group_id),
                registration_stati=[const.RegistrationPartStati.participant],
                notes=None,
                moderators=event.orgas,
                whitelist=set(),
            )
            return participant_ml_data

    @access("event_admin")
    def create_event_form(self, rs: RequestState) -> Response:
        """Render form."""
        accounts = [
            (str(account), f"{iban_filter(account.value)} ({account.get_bank()})")
            for account in Accounts.get_event_accounts()
        ]
        mandatory_fields = models.Event.mandatory_form_fields(
            creation=True
        ) | get_mandatory_form_fields(self.create_event)
        return self.render(
            rs,
            "event/create_event",
            {'accounts': accounts},
            mandatory_fields=mandatory_fields,
        )

    @access("event_admin", modi={"POST"})
    @REQUESTdata(
        "part_begin",
        "part_end",
        "orga_ids",
        "caretaker_ids",
        "create_track",
        "fee",
        "nonmember_surcharge",
        "create_orga_list",
        "create_participant_list",
    )
    @REQUESTdatadict(*models.Event.requestdict_fields(creation=True), "description")
    def create_event(
        self,
        rs: RequestState,
        part_begin: datetime.date,
        part_end: datetime.date,
        orga_ids: list[vtypes.PersonaID],
        caretaker_ids: list[vtypes.PersonaID],
        fee: vtypes.NonNegativeDecimal,
        nonmember_surcharge: vtypes.NonNegativeDecimal,
        create_track: bool,
        create_orga_list: bool,
        create_participant_list: bool,
        data: CdEDBObject,
    ) -> Response:
        """Create a new event, organized via DB."""
        # multi part events will have to edit this later on
        data.update({
            'orgas': orga_ids,
            'caretakers': caretaker_ids,
            'notify_on_registration': const.NotifyOnRegistration.never,
            'parts': {
                -1: {
                    'title': data['title'],
                    'shortname': data['shortname'],
                    'part_begin': part_begin,
                    'part_end': part_end,
                    'waitlist_field_id': None,
                    'camping_mat_field_id': None,
                    'tracks': (
                        {
                            -1: {
                                'title': data['title'],
                                'shortname': data['shortname'],
                                'num_choices': DEFAULT_NUM_COURSE_CHOICES,
                                'min_choices': DEFAULT_NUM_COURSE_CHOICES,
                                'sortkey': 0,
                                'course_room_field_id': None,
                            },
                        }
                        if create_track
                        else {}
                    ),
                },
            },
        })
        fee_data = [
            {
                'kind': const.EventFeeType.common,
                'title': data['title'],
                'notes': "Automatisch erstellt.",
                'amount': fee,
                'condition': f"part.{data['shortname']}",
            },
            {
                'kind': const.EventFeeType.external,
                'title': "Externenzusatzbeitrag",
                'notes': "Automatisch erstellt.",
                'amount': nonmember_surcharge,
                'condition': "any_part and not is_member and not age.U12",
            },
        ]
        if (
            data
            and data['shortname']
            and self.eventproxy.verify_shortname_existence(rs, data['shortname'])
        ):
            rs.append_validation_error(
                (
                    'shortname',
                    ValueError(
                        n_("Shortname already in use for another event."),
                    ),
                ),
            )
        data = check(rs, models.Event, data, creation=True)
        if orga_ids:
            try:
                self.eventproxy.validate_event_persona_ids(rs, orga_ids)
            except ValueError as e:
                rs.append_validation_error(("orga_ids", e))
        if caretaker_ids:
            try:
                self.eventproxy.validate_event_persona_ids(rs, caretaker_ids)
            except ValueError as e:
                rs.append_validation_error(("caretaker_ids", e))
        if not orga_ids and (create_orga_list or create_participant_list):
            # mailinglists require moderators
            rs.append_validation_error(
                (
                    "orga_ids",
                    ValueError(
                        n_("Must not be empty in order to create a mailinglist."),
                    ),
                ),
            )
        if rs.has_validation_errors():
            return self.create_event_form(rs)
        assert data is not None

        with TransactionObserver(
            rs, self, "create_event", recipients=[self.conf["EVENT_ADMIN_ADDRESS"]]
        ):
            new_id = self.eventproxy.create_event(rs, data)
            data["id"] = new_id
            event = self.eventproxy.get_event(rs, new_id)
            for fee_ in fee_data:
                self.eventproxy.create_event_fee(rs, new_id, fee_)

            for kind, qst in models.questionnaire.make_default_questionnaire(
                event
            ).items():
                self.eventproxy.set_questionnaire(rs, event.id, kind, qst)

            if create_orga_list:
                orga_ml_data = self._get_mailinglist_setter(rs, event, orgalist=True)
                if self.mlproxy.verify_existence(rs, orga_ml_data.address):
                    rs.notify(
                        "info",
                        n_("Mailinglist %(address)s already exists."),
                        {'address': orga_ml_data.address},
                    )
                else:
                    code = self.mlproxy.create_mailinglist(rs, orga_ml_data)
                    rs.notify_return_code(code, success=n_("Orga mailinglist created."))
                code = self.eventproxy.set_event(
                    rs,
                    new_id,
                    {"orga_address": orga_ml_data.address},
                    change_note="Mailadresse der Orgas gesetzt.",
                )
                rs.notify_return_code(code)
            if create_participant_list:
                participant_ml_data = self._get_mailinglist_setter(rs, event)
                if not self.mlproxy.verify_existence(rs, participant_ml_data.address):
                    code = self.mlproxy.create_mailinglist(rs, participant_ml_data)
                    rs.notify_return_code(
                        code, success=n_("Participant mailinglist created.")
                    )
                else:
                    rs.notify(
                        "info",
                        n_("Mailinglist %(address)s already exists."),
                        {'address': participant_ml_data.address},
                    )
        rs.notify_return_code(new_id, success=n_("Event created."))
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.lock)
    def lock_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Lock an event."""
        if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
            rs.notify("error", n_("Cannot lock offline instance."))
        elif rs.ambience['event'].is_locked:
            rs.notify("warning", n_("Event already locked."))
        else:
            code = self.eventproxy.lock_event(rs, event_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.lock)
    def unlock_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Unlock an event."""
        if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
            rs.notify("error", n_("Cannot unlock offline instance."))
        elif not rs.ambience['event'].is_locked:
            rs.notify("warning", n_("Event isn't locked."))
        else:
            code = self.eventproxy.unlock_event(rs, event_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(EventPrivileges.conclude)
    @REQUESTdata("ack_archive", "create_past_event")
    def archive_event(
        self,
        rs: RequestState,
        event_id: vtypes.EventID,
        ack_archive: bool,
        create_past_event: bool,
    ) -> Response:
        """Archive an event and optionally create a past event.

        This is at the boundary between event and cde frontend, since
        the past-event stuff generally resides in the cde realm.
        """
        if rs.ambience['event'].is_archived:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Event already archived."))
            return self.redirect(rs, "event/show_event")
        if not ack_archive:
            rs.append_validation_error((
                "ack_archive",
                ValueError(n_("Must be checked.")),
            ))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if (
            not rs.ambience['event'].is_cancelled
            and rs.ambience['event'].end >= now().date()
        ):
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        if create_past_event:
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            registrations = self.eventproxy.get_registrations(rs, registration_ids)
            if not any(
                rpart['status'] == const.RegistrationPartStati.participant
                for reg in registrations.values()
                for rpart in reg['parts'].values()
            ):
                rs.notify("error", n_("No event parts have any participants."))
                return self.redirect(rs, "event/show_event")

        new_ids = self.pasteventproxy.archive_event(
            rs, event_id, create_past_event=create_past_event
        )
        if new_ids:
            self.do_mail(
                rs,
                "event_archived",
                {
                    "To": [
                        self.conf["EVENT_ADMIN_ADDRESS"],
                        self.conf["MANAGEMENT_ADDRESS"],
                    ],
                    "Subject": "Veranstaltung archiviert.",
                },
            )

        # Lock all questionnaire entries
        aq = const.QuestionnaireUsages.additional
        questionnaire = self.eventproxy.get_all_questionnaires(rs, event_id)[aq]
        for entry in questionnaire.field_rows:
            entry.readonly = True
        self.eventproxy.set_questionnaire(rs, event_id, aq, questionnaire.as_dicts())

        # Delete non-pseudonymized event keeper only after internal work has been
        # concluded successfully

        # Deleting event keeper here is too early for now.
        # self.eventproxy.event_keeper_drop(rs, event_id)

        rs.notify("success", n_("Event archived."))
        if new_ids is None:
            return self.redirect(rs, "event/show_event")
        elif len(new_ids) == 1:
            rs.notify("info", n_("Created past event."))
            return self.redirect(
                rs, "cde/show_past_event", {'pevent_id': unwrap(new_ids)}
            )
        else:
            rs.notify("info", n_("Created multiple past events."))
            return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(EventPrivileges.delete)
    @ack_delete()
    def delete_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Remove an event."""
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if rs.ambience['event'].end >= now().date():
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        blockers = self.eventproxy.delete_event_blockers(rs, event_id)
        cascade = {
            "registrations", "courses", "lodgement_groups", "lodgements",
            "field_definitions", "course_tracks", "event_parts", "event_fees",
            "orgas", "caretakers", "checkin_helpers", "questionnaire_text_rows",
            "questionnaire_field_rows", "questionnaire_magic_rows", "stored_queries",
            "log", "mailinglists", "part_groups", "orga_tokens", "custom_query_filters",
        }  # fmt: skip

        code = self.eventproxy.delete_event(rs, event_id, cascade & blockers.keys())
        if not code:
            return self.show_event(rs, event_id)
        else:
            rs.notify("success", n_("Event deleted."))
            return self.redirect(rs, "event/index")

    @access("finance_admin", modi={"POST"})
    @event_guard(EventPrivileges.balance)
    def balance_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Balance an event."""
        if rs.ambience['event'].is_balanced:
            rs.notify("warning", n_("Event already balanced."))
        else:
            code = self.eventproxy.balance_event(rs, event_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("finance_admin", modi={"POST"})
    @event_guard(EventPrivileges.balance)
    def unbalance_event(self, rs: RequestState, event_id: vtypes.EventID) -> Response:
        """Unbalance an event."""
        if not rs.ambience['event'].is_balanced:
            rs.notify("warning", n_("Event isn't balanced."))
        else:
            code = self.eventproxy.unbalance_event(rs, event_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.approve_registration)
    def approve_registration(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> Response:
        if rs.ambience['event'].is_registration_approved:
            rs.notify("warning", n_("Registration already approved."))
        else:
            code = self.eventproxy.approve_registration(rs, event_id)
            rs.notify_return_code(code)
            to = [event_admin_address := self.conf["EVENT_ADMIN_ADDRESS"]]
            if orga_adress := rs.ambience['event'].orga_address:
                to.append(orga_adress)
            self.do_mail(
                rs,
                "registration_approved",
                {
                    "To": to,
                    "Subject": "Anmeldung freigeschaltet",
                    "Reply-To": event_admin_address,
                },
                {"approve": True},
            )
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard(EventPrivileges.approve_registration)
    def unapprove_registration(
        self, rs: RequestState, event_id: vtypes.EventID
    ) -> Response:
        if not rs.ambience['event'].is_registration_approved:
            rs.notify("warning", n_("Registration already unapproved."))
        else:
            code = self.eventproxy.unapprove_registration(rs, event_id)
            rs.notify_return_code(code)
            to = [event_admin_address := self.conf["EVENT_ADMIN_ADDRESS"]]
            if orga_adress := rs.ambience['event'].orga_address:
                to.append(orga_adress)
            self.do_mail(
                rs,
                "registration_approved",
                {
                    "To": to,
                    "Subject": "Anmeldung gesperrt",
                    "Reply-To": event_admin_address,
                },
                {"approve": False},
            )
        return self.redirect(rs, "event/show_event")

    @access("event")
    @event_guard(EventPrivileges.registrations_read, EventPrivileges.checkin)
    @REQUESTdata("phrase")
    def quick_show_registration(
        self, rs: RequestState, event_id: vtypes.EventID, phrase: str
    ) -> Response:
        """Allow orgas to quickly retrieve a registration.

        The search phrase may be anything: a numeric id or a string
        matching the data set.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        persona_id, errs = inspect(vtypes.PersonaID, phrase, argname="phrase")
        if not errs:
            reg_ids = self.eventproxy.list_registrations(
                rs, event_id, persona_id=persona_id
            )
            if reg_ids:
                reg_id = unwrap(reg_ids.keys())
                return self.redirect(
                    rs, "event/show_registration", {'registration_id': reg_id}
                )

        reg_id, errs = inspect(vtypes.RegistrationID, phrase, argname="phrase")
        if not errs:
            assert reg_id is not None
            reg = self.eventproxy.get_registration(rs, reg_id)
            if reg:
                if reg['event_id'] == event_id:
                    return self.redirect(
                        rs, "event/show_registration", {'registration_id': reg['id']}
                    )

        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        valid = True
        for t in terms:
            _, errs = inspect(vtypes.NonRegex, t, argname="phrase")
            if errs:
                valid = False
        if not valid:
            rs.notify("warning", n_("Active characters found in search."))
            return self.show_event(rs, event_id)

        key = "username,family_name,given_names,nickname,legal_given_names"
        search = [(key, QueryOperators.match, t) for t in terms]
        spec = QueryScope.quick_registration.get_spec()
        spec[key] = QuerySpecEntry("str", "")
        query = Query(
            QueryScope.quick_registration,
            spec,
            (
                "registrations.id",
                "username",
                "family_name",
                "given_names",
                "nickname",
                "legal_given_names",
            ),
            search,
            (("registrations.id", True),),
        )
        result = self.eventproxy.submit_general_query(rs, query, event_id=event_id)
        if len(result) == 1:
            return self.redirect(
                rs,
                "event/show_registration",
                {'registration_id': result[0][query.scope.get_primary_key()]},
            )
        elif result:
            # TODO make this accessible
            pass
        # TODO what does the remainder of this function? How should we include nickname
        #  and legal_given_names here?
        base_query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=rs.ambience['event']),
            [
                "reg.id",
                "persona.given_names",
                "persona.family_name",
                "persona.username",
            ],
            [],
            (("persona.family_name", True), ("persona.given_names", True)),
        )
        regex = "({})".format("|".join(terms))
        given_names_constraint = ('persona.given_names', QueryOperators.regex, regex)
        family_name_constraint = ('persona.family_name', QueryOperators.regex, regex)

        for effective in (
            [given_names_constraint, family_name_constraint],
            [given_names_constraint],
            [family_name_constraint],
        ):
            query = copy.deepcopy(base_query)
            query.constraints.extend(effective)
            result = self.eventproxy.submit_general_query(rs, query, event_id=event_id)
            if len(result) == 1:
                return self.redirect(
                    rs,
                    "event/show_registration",
                    {'registration_id': result[0][query.scope.get_primary_key()]},
                )
            elif result:
                if self.is_privileged(rs, EventPrivileges.registrations_read):
                    params = query.serialize_to_url()
                    return self.redirect(rs, "event/registration_query", params)
                else:
                    rs.notify("warning", n_("Multiple registrations found."))
                    return self.show_event(rs, event_id)
        rs.notify("warning", n_("No registration found."))
        return self.show_event(rs, event_id)
