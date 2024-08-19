#!/usr/bin/env python3

"""
The `EventEventMixin` subclasses the `EventBaseFrontend` and provides endpoints for
managing an event itself, including event parts and course tracks.

This also includes all functionality directly avalable on the `show_event` page.
"""

import copy
import datetime
import re
from collections import OrderedDict
from collections.abc import Collection
from typing import Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    DEFAULT_NUM_COURSE_CHOICES, CdEDBObject, RequestState, merge_dicts, now, unwrap,
)
from cdedb.common.fields import EVENT_FIELD_SPEC
from cdedb.common.n_ import n_
from cdedb.common.query import (
    Query, QueryConstraint, QueryOperators, QueryScope, QuerySpecEntry,
)
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.validate import (
    EVENT_EXPOSED_FIELDS, EVENT_PART_COMMON_FIELDS,
    EVENT_PART_CREATION_MANDATORY_FIELDS, EVENT_PART_CREATION_OPTIONAL_FIELDS,
    EVENT_PART_GROUP_COMMON_FIELDS, EVENT_TRACK_COMMON_FIELDS,
    EVENT_TRACK_GROUP_COMMON_FIELDS,
)
from cdedb.frontend.common import (
    Headers, REQUESTdata, REQUESTdatadict, REQUESTfile, access, cdedburl,
    check_validation as check, check_validation_optional as check_optional, drow_name,
    event_guard, inspect_validation as inspect, periodic, process_dynamic_input,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.models.ml import (
    EventAssociatedMailinglist, EventOrgaMailinglist, Mailinglist,
)


class EventEventMixin(EventBaseFrontend):
    @access("anonymous")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        open_event_list = self.eventproxy.list_events(
            rs, visible=True, current=True, archived=False)
        other_event_list = self.eventproxy.list_events(
            rs, visible=True, current=False, archived=False)
        open_events = self.eventproxy.get_events(rs, open_event_list)
        other_events = self.eventproxy.get_events(
            rs, set(other_event_list) - set(rs.user.orga))
        orga_events = self.eventproxy.get_events(rs, rs.user.orga)

        events_registration: dict[int, Optional[bool]] = {}
        events_payment_pending: dict[int, bool] = {}
        if "event" in rs.user.roles:
            for event_id, event in open_events.items():
                events_registration[event_id], events_payment_pending[event_id] = (
                    self.eventproxy.get_registration_payment_info(rs, event_id))

        return self.render(rs, "event/index", {
            'open_events': open_events, 'orga_events': orga_events,
            'other_events': other_events, 'events_registration': events_registration,
            'events_payment_pending': events_payment_pending})

    @access("anonymous")
    def list_events(self, rs: RequestState) -> Response:
        """List all events organized via DB."""
        event_ids = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, event_ids)

        events_registrations: dict[vtypes.ProtoID, int] = {}
        if self.is_admin(rs):
            for event in events.values():
                regs = self.eventproxy.list_registrations(rs, event.id)
                events_registrations[event.id] = len(regs)

        def querylink(event_id: int) -> str:
            query = Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=events[event_id]),
                ("persona.given_names", "persona.family_name"),
                (),
                (("persona.family_name", True), ("persona.given_names", True)))
            params = query.serialize_to_url()
            params['event_id'] = event_id
            return cdedburl(rs, 'event/registration_query', params)

        return self.render(rs, "event/list_events",
            {'events': events, 'events_registrations': events_registrations,
             'querylink': querylink})

    @access("anonymous")
    def show_event(self, rs: RequestState, event_id: int) -> Response:
        """Display event organized via DB."""
        params: CdEDBObject = {}
        if "event" in rs.user.roles:
            params['orgas'] = OrderedDict(
                (e['id'], e) for e in xsorted(
                    self.coreproxy.get_personas(
                        rs, rs.ambience['event'].orgas).values(),
                    key=EntitySorter.persona))
        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs, rs.ambience['event'].as_dict())
            params['participant_list'] = self.mlproxy.verify_existence(
                rs, ml_data.address)
        if event_id in rs.user.orga or self.is_admin(rs):
            params['minor_form_present'] = self.eventproxy.has_minor_form(rs, event_id)
            constraint_violations = self.get_constraint_violations(
                rs, event_id, registration_id=None, course_id=None)
            params['mep_violations'] = constraint_violations['mep_violations']
            params['mec_violations'] = constraint_violations['mec_violations']
            params['ccs_violations'] = constraint_violations['ccs_violations']
            params['violation_severity'] = constraint_violations['max_severity']
        elif not rs.ambience['event'].is_visible:
            raise werkzeug.exceptions.Forbidden(n_("The event is not published yet."))
        return self.render(rs, "event/show_event", params)

    @access("finance_admin")
    @REQUESTdata("phrase")
    def select_event(self, rs: RequestState, phrase: str) -> Response:
        """API for intelligent input field.

        This allows the user to choose an event by entering (parts of) the title
        or the shortname.

        Meant for use during parse_statement.

        Since this only returns basic event information it has little privacy
        implications.
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})
        atoms = [re.compile(re.escape(atom), flags=re.I) for atom in phrase.split()]
        if not atoms:
            return self.send_json(rs, {})

        events = self.eventproxy.get_events(rs, self.eventproxy.list_events(rs))

        def _match(event: models.Event) -> bool:
            return all(
                atom_pattern.search(event.shortname) or atom_pattern.search(event.title)
                for atom_pattern in atoms
            )

        return self.send_json(rs, {
            'events': [
                {
                    'title': event.title,
                    'shortname': event.shortname,
                    'id': event.id,
                }
                for event in xsorted(events.values())
                if _match(event)
            ],
        })

    @access("event")
    @event_guard()
    def change_event_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['event'].as_dict())

        sorted_fields = xsorted(rs.ambience['event'].fields.values())
        lodge_fields = [
            (field.id, field.field_name) for field in sorted_fields
            if field.association == const.FieldAssociations.registration
            and field.kind == const.FieldDatatypes.str
        ]
        return self.render(rs, "event/change_event", {
            'accounts': self.conf["EVENT_BANK_ACCOUNTS"],
            'lodge_fields': lodge_fields})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*EVENT_EXPOSED_FIELDS)
    def change_event(self, rs: RequestState, event_id: int, data: CdEDBObject,
                     ) -> Response:
        """Modify an event organized via DB."""
        data = check(rs, vtypes.Event, data, current=rs.ambience['event'])
        if (data and data['shortname']
                and data['shortname'] != rs.ambience['event'].shortname
                and self.eventproxy.verify_shortname_existence(rs, data['shortname'])):
            rs.append_validation_error(
                ('shortname', ValueError(
                    n_("Shortname already in use for another event."),
                )),
            )
        if rs.has_validation_errors():
            return self.change_event_form(rs, event_id)
        assert data is not None

        code = self.eventproxy.set_event(rs, event_id, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    def get_minor_form(self, rs: RequestState, event_id: int) -> Response:
        """Retrieve minor form."""
        if not (rs.ambience['event'].is_visible
                or event_id in rs.user.orga
                or self.is_admin(rs)):
            raise werkzeug.exceptions.Forbidden(n_("The event is not published yet."))
        path = self.eventproxy.get_minor_form_path(rs, event_id)
        return self.send_file(
            rs, path=path, mimetype="application/pdf",
            filename=f"Elternbrief CdE {rs.ambience['event'].shortname}.pdf")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("minor_form")
    @REQUESTdata("delete")
    def change_minor_form(self, rs: RequestState, event_id: int,
                          minor_form: werkzeug.datastructures.FileStorage, delete: bool,
                          ) -> Response:
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check_optional(
            rs, vtypes.PDFFile, minor_form, "minor_form")
        if not minor_form and not delete:
            rs.append_validation_error(
                ("minor_form", ValueError(n_("Must not be empty."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.change_minor_form(rs, event_id, minor_form)
        rs.notify_return_code(code, success=n_("Minor form updated."),
                                info=n_("Minor form has been removed."),
                                error=n_("Nothing to remove."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("orga_id")
    def add_orga(self, rs: RequestState, event_id: int, orga_id: vtypes.CdedbID,
                 ) -> Response:
        """Make an additional persona become orga."""
        if rs.has_validation_errors():
            # Shortcircuit if we have got no workable cdedbid
            return self.show_event(rs, event_id)
        if not self.coreproxy.verify_id(rs, orga_id, is_archived=False):
            rs.append_validation_error(
                ('orga_id',
                 ValueError(n_("This user does not exist or is archived."))))
        if not self.coreproxy.verify_persona(rs, orga_id, {"event"}):
            rs.append_validation_error(
                ('orga_id', ValueError(n_("This user is not an event user."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.add_event_orgas(rs, event_id, {orga_id})
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("orga_id")
    def remove_orga(self, rs: RequestState, event_id: int, orga_id: vtypes.ID,
                    ) -> Response:
        """Remove a persona as orga of an event.

        This is only available for admins. This can drop your own orga role.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.remove_event_orga(rs, event_id, orga_id)
        rs.notify_return_code(code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("orgalist")
    def create_event_mailinglist(self, rs: RequestState, event_id: int,
                                 orgalist: bool = False) -> Response:
        """Create a default mailinglist for the event."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not rs.ambience['event'].orgas:
            rs.notify('error',
                      n_("Must have orgas in order to create a mailinglist."))
            return self.redirect(rs, "event/show_event")

        ml_data = self._get_mailinglist_setter(
            rs, rs.ambience['event'].as_dict(), orgalist)
        if not self.mlproxy.verify_existence(rs, ml_data.address):
            code = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Orga mailinglist created.") if orgalist
                   else n_("Participant mailinglist created."))
            rs.notify_return_code(code, success=msg)
            if code and orgalist:
                self.eventproxy.set_event(
                    rs, event_id, {'orga_address': ml_data.address})
        else:
            rs.notify("info", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_data.address})
        return self.redirect(rs, "event/show_event")

    def _deletion_blocked_parts(self, rs: RequestState, event_id: int) -> set[int]:
        """Returns all part_ids from parts of a given event which must not be deleted.

        Extracts all parts of the given event from the database and checks if there are
        blockers preventing their deletion.

        :returns: All part_ids whose deletion is blocked.
        """
        blocked_parts: set[int] = set()
        if len(rs.ambience['event'].parts) == 1:
            blocked_parts.add(unwrap(rs.ambience['event'].parts.keys()))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        # referenced tracks block part deletion
        for course in courses.values():
            for track_id in course['segments']:
                blocked_parts.add(rs.ambience['event'].tracks[track_id].part_id)
        part_fees = self.eventproxy.get_event_fees_per_entity(rs, event_id).parts
        for part_id, fees in part_fees.items():
            if fees:
                blocked_parts.add(part_id)
        return blocked_parts

    def _deletion_blocked_tracks(self, rs: RequestState, event_id: int) -> set[int]:
        """Returns all track_ids from tracks of a given event which must not be deleted.

        Extracts all tracks of the given event from the database and checks if there are
        blockers preventing their deletion.

        :returns: All track_ids whose deletion is blocked.
        """
        blocked_tracks: set[int] = set()
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        for course in courses.values():
            blocked_tracks.update(course['segments'])
        for tg in rs.ambience['event'].track_groups.values():
            blocked_tracks.update(tg.tracks)
        return blocked_tracks

    @access("event")
    @event_guard()
    def part_summary(self, rs: RequestState, event_id: int) -> Response:
        """Display a comprehensive overview of all parts of a given event."""
        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        referenced_parts = self._deletion_blocked_parts(rs, event_id)

        return self.render(rs, "event/part_summary", {
            'referenced_parts': referenced_parts,
            'has_registrations': has_registrations})

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdata("ack_delete")
    def delete_part(self, rs: RequestState, event_id: int, part_id: int,
                    ack_delete: bool) -> Response:
        """Delete a given part."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.part_summary(rs, event_id)
        if self.eventproxy.has_registrations(rs, event_id):
            rs.notify("error", n_("Registrations exist, no deletion."))
            return self.part_summary(rs, event_id)
        if part_id in self._deletion_blocked_parts(rs, event_id):
            rs.notify("error", n_("This part can not be deleted."))
            return self.part_summary(rs, event_id)

        code = self.eventproxy.set_event(rs, event_id, {'parts': {part_id: None}})
        rs.notify_return_code(code)

        return self.redirect(rs, "event/part_summary")

    @staticmethod
    def _valid_event_part_fields(
            fields: models.CdEDataclassMap[models.EventField],
    ) -> dict[str, list[tuple[vtypes.ProtoID, vtypes.RestrictiveIdentifier]]]:
        sorted_fields = xsorted(fields.values())
        fields = {}
        for field in ('waitlist', 'camping_mat', 'course_room'):
            legal_datatypes, legal_assocs = EVENT_FIELD_SPEC[field]
            fields[f"{field}_field_id"] = [
                (field.id, field.field_name) for field in sorted_fields
                if field.association in legal_assocs
                   and field.kind in legal_datatypes
            ]
        return fields

    @access("event")
    @event_guard()
    def add_part_form(self, rs: RequestState, event_id: int) -> Response:
        if self.eventproxy.has_registrations(rs, event_id):
            rs.notify("error", n_("Registrations exist, no part creation possible."))
            return self.redirect(rs, "event/show_event")
        fields = self._valid_event_part_fields(rs.ambience['event'].fields)
        return self.render(rs, "event/add_part", {
            'fields': fields, 'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES})

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdata("fee")
    @REQUESTdatadict(*EVENT_PART_CREATION_MANDATORY_FIELDS,
                     *(set(EVENT_PART_CREATION_OPTIONAL_FIELDS) - {'tracks'}))
    def add_part(self, rs: RequestState, event_id: int, data: CdEDBObject,
                 fee: vtypes.NonNegativeDecimal) -> Response:
        if self.eventproxy.has_registrations(rs, event_id):
            raise ValueError(n_("Registrations exist, no part creation possible."))

        data = check(rs, vtypes.EventPart, data)
        if rs.has_validation_errors():
            return self.add_part_form(rs, event_id)
        assert data is not None

        # check non-static dependencies
        fields = self._valid_event_part_fields(rs.ambience['event'].fields)
        for key in ('waitlist_field_id', 'camping_mat_field_id'):
            field_ids = [field[0] for field in fields[key]]
            if data[key] and data[key] not in field_ids:
                rs.append_validation_error((key, ValueError(
                    n_("Linked to non-fitting field."))))
        if rs.has_validation_errors():
            return self.add_part_form(rs, event_id)

        code = self.eventproxy.set_event(rs, event_id, {'parts': {-1: data}})
        if code:
            new_fee = {
                'kind': const.EventFeeType.common,
                'title': data['title'],
                'notes': "Automatisch erstellt.",
                'amount': fee,
                'condition': f"part.{data['shortname']}",
            }
            self.eventproxy.set_event_fees(rs, event_id, {-1: new_fee})
        rs.notify_return_code(code)

        return self.redirect(rs, "event/part_summary")

    @access("event")
    @event_guard()
    def change_part_form(self, rs: RequestState, event_id: int, part_id: int,
                         ) -> Response:
        part = rs.ambience['event'].parts[part_id]

        sorted_track_ids = [e.id for e in xsorted(part.tracks.values())]

        current = part.as_dict()
        del current['id']
        del current['tracks']

        # Select the first track by id for every sync track group, disable altering
        #  choices for all others.
        sync_groups = set()
        readonly_synced_tracks = set()
        for track_id, track in xsorted(part.tracks.items()):
            for k in EVENT_TRACK_COMMON_FIELDS:
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

        fields = self._valid_event_part_fields(rs.ambience['event'].fields)
        return self.render(rs, "event/change_part", {
            'part_id': part_id,
            'sorted_track_ids': sorted_track_ids,
            'fields': fields,
            'referenced_tracks': referenced_tracks,
            'has_registrations': has_registrations,
            'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES,
            'readonly_synced_tracks': readonly_synced_tracks,
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*EVENT_PART_COMMON_FIELDS)
    def change_part(self, rs: RequestState, event_id: int, part_id: int,
                    data: CdEDBObject) -> Response:
        """Change one part, including the associated tracks and fee modifiers."""
        # this will be added at the end after processing the dynamic input and will only
        # yield false validation errors
        del data['tracks']
        data = check(rs, vtypes.EventPart, data)
        if rs.has_validation_errors():
            return self.change_part_form(rs, event_id, part_id)
        assert data is not None
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        #
        # Check part specific stuff which can not be checked statically
        #
        fields = self._valid_event_part_fields(rs.ambience['event'].fields)
        for key in ('waitlist_field_id', 'camping_mat_field_id'):
            field_ids = [field[0] for field in fields[key]]
            if data[key] and data[key] not in field_ids:
                rs.append_validation_error((key, ValueError(
                    n_("Linked to non-fitting field."))))

        #
        # process the dynamic track input
        #
        track_existing = rs.ambience['event'].parts[part_id].tracks
        track_spec = EVENT_TRACK_COMMON_FIELDS
        track_data = process_dynamic_input(
            rs, vtypes.EventTrack, track_existing, track_spec, prefix="track")

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
            for key in ('course_room_field_id',):
                field_ids = [field[0] for field in fields[key]]
                if track and track[key] and track[key] not in field_ids:
                    rs.append_validation_error((key, ValueError(
                        n_("Linked to non-fitting field."))))
            # Only existing tracks are relevant, new ones are not part of a group.
            if track and track_id in track_existing:
                for tg_id, tg in track_existing[track_id].track_groups.items():
                    if tg.constraint_type.is_sync() and tg_id not in sync_groups:
                        sync_groups.add(tg_id)
                        for t_id in tg.tracks:
                            p_id = rs.ambience['event'].tracks[t_id].part_id
                            if p_id not in part_data:
                                part_data[p_id] = vtypes.EventPart({'tracks': {}})
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
            event: models.Event, constraints: Collection[QueryConstraint],
            fee: Optional[models.EventFee] = None,
    ) -> Query:
        return Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=[
                "persona.id", "persona.given_names", "persona.family_name",
                "persona.username",
                "reg.payment", "reg.remaining_owed", "reg.amount_owed",
                "reg.amount_paid",
            ] + ([f"fee{fee.id}.amount"] if fee else []),
            constraints=constraints,
            order=[
                ("persona.family_name", True),
                ("persona.given_names", True),
            ],
        )

    def _get_payment_query(
            self, event: models.Event, ids: Collection[int], fee_id: Optional[int],
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
        return self._get_payment_query_base(event, constraints, fee)

    @access("event")
    @event_guard()
    def fee_summary(self, rs: RequestState, event_id: int) -> Response:
        """Show a summary of all event fees."""
        fee_stats = self.eventproxy.get_fee_stats(rs, event_id)

        return self.render(rs, "event/fee/fee_summary", {
            'fee_stats': fee_stats,
            'get_query':
                lambda ids, fee_id: self._get_payment_query(
                    rs.ambience['event'], ids, fee_id,
                ),
        })

    @access("event")
    @event_guard()
    def fee_stats(self, rs: RequestState, event_id: int) -> Response:
        """Show stats for existing fees."""
        fee_stats = self.eventproxy.get_fee_stats(rs, event_id)

        incomplete_paid = self._get_payment_query_base(rs.ambience['event'], [
            ("reg.remaining_owed", QueryOperators.greater, 0.00),
            ("reg.amount_paid", QueryOperators.unequal, 0),
        ])
        not_paid = self._get_payment_query_base(rs.ambience['event'], [
            ("reg.remaining_owed", QueryOperators.greater, 0.00),
            ("reg.amount_paid", QueryOperators.equal, 0),
        ])
        surplus = self._get_payment_query_base(rs.ambience['event'], [
            ("reg.remaining_owed", QueryOperators.less, 0.00),
        ])

        return self.render(rs, "event/fee/fee_stats", {
            'fee_stats': fee_stats, 'incomplete_paid': incomplete_paid,
            'not_paid': not_paid, 'surplus': surplus,
            'get_query':
                lambda ids, fee_id: self._get_payment_query(
                    rs.ambience['event'], ids, fee_id,
                ),
        })

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("personalized")
    def configure_fee_form(self, rs: RequestState, event_id: int, personalized: bool,
                           fee_id: Optional[int] = None) -> Response:
        """Render form to change or create one event fee."""
        rs.ignore_validation_errors()
        if fee_id:
            if fee_id not in rs.ambience['event'].fees:
                rs.notify("error", n_("Unknown fee."))
                return self.redirect(rs, "event/fee_summary")
            else:
                merge_dicts(rs.values, rs.ambience['fee'].as_dict())
                personalized = rs.ambience['fee'].is_personalized()
        return self.render(
            rs, "event/fee/configure_fee",
            {
                'personalized': personalized,
            },
        )

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("personalized")
    @REQUESTdatadict(*models.EventFee.requestdict_fields())
    def configure_fee(self, rs: RequestState, event_id: int, data: CdEDBObject,
                      personalized: bool, fee_id: Optional[int] = None) -> Response:
        """Submit changes to or creation of one event fee."""
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        fee_data = check(
            rs, vtypes.EventFee, data, creation=fee_id is None, id_=fee_id or -1,
            event=rs.ambience['event'].as_dict(), questionnaire=questionnaire,
            personalized=personalized,
        )
        if rs.has_validation_errors() or not fee_data:
            return self.render(rs, "event/fee/configure_fee")
        code = self.eventproxy.set_event_fees(rs, event_id, {fee_id or -1: fee_data})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/fee_summary")

    @access("event", modi={"POST"})
    @event_guard()
    def delete_fee(self, rs: RequestState, event_id: int, fee_id: int) -> Response:
        """Delete one event fee."""
        if fee_id not in rs.ambience['event'].fees:
            rs.notify("error", n_("Unknown fee."))
            return self.redirect(rs, "event/fee_summary")
        code = self.eventproxy.set_event_fees(rs, event_id, {fee_id: None})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/fee_summary")

    @access("event")
    @event_guard()
    def group_summary(self, rs: RequestState, event_id: int) -> Response:
        return self.render(rs, "event/group_summary")

    @access("event")
    @event_guard()
    def add_part_group_form(self, rs: RequestState, event_id: int) -> Response:
        return self.render(rs, "event/configure_part_group")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata(*EVENT_PART_GROUP_COMMON_FIELDS)
    def add_part_group(self, rs: RequestState, event_id: int, title: str,
                       shortname: str, notes: Optional[str],
                       constraint_type: const.EventPartGroupType,
                       part_ids: Collection[int]) -> Response:
        if part_ids and not set(part_ids) <= rs.ambience['event'].parts.keys():
            rs.append_validation_error(("part_ids", ValueError(n_("Unknown part."))))
        data = {
            'title': title,
            'shortname': shortname,
            'notes': notes,
            'constraint_type': constraint_type,
            'part_ids': part_ids,
        }
        existing = {pg.title for pg in rs.ambience['event'].part_groups.values()}
        if data['title'] in existing:
            rs.append_validation_error(('title', ValueError(n_(
                "A part group with this name already exists."))))
        existing = {pg.shortname for pg in rs.ambience['event'].part_groups.values()}
        if data['shortname'] in existing:
            rs.append_validation_error(('shortname', ValueError(n_(
                "A part group with this name already exists."))))
        data = check(rs, vtypes.EventPartGroup, data)
        if rs.has_validation_errors():
            return self.add_part_group_form(rs, event_id)
        code = self.eventproxy.set_part_groups(rs, event_id, {-1: data})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard()
    def change_part_group_form(self, rs: RequestState, event_id: int,
                               part_group_id: int) -> Response:
        merge_dicts(rs.values, rs.ambience['part_group'].as_dict())
        # add this to autofill the values correctly (they are readonly anyway)
        merge_dicts(rs.values, {"part_ids": rs.ambience['part_group'].parts.keys()})
        return self.render(rs, "event/configure_part_group")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("title", "shortname", "notes")
    def change_part_group(self, rs: RequestState, event_id: int,
                          part_group_id: int, title: str, shortname: str,
                          notes: Optional[str]) -> Response:
        data: CdEDBObject = {
            'title': title,
            'shortname': shortname,
            'notes': notes,
        }
        existing = {pg.title for pg in rs.ambience['event'].part_groups.values()}
        if data['title'] in existing - {rs.ambience['part_group'].title}:
            rs.append_validation_error(('title', ValueError(n_(
                "A part group with this name already exists."))))
        existing = {pg.shortname for pg in rs.ambience['event'].part_groups.values()}
        if data['shortname'] in existing - {rs.ambience['part_group'].shortname}:
            rs.append_validation_error(('shortname', ValueError(n_(
                "A part group with this name already exists."))))
        data = check(rs, vtypes.EventPartGroup, data)
        if rs.has_validation_errors():
            return self.change_part_group_form(rs, event_id, part_group_id)
        code = self.eventproxy.set_part_groups(rs, event_id, {part_group_id: data})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def delete_part_group(self, rs: RequestState, event_id: int,
                          part_group_id: int) -> Response:
        if rs.has_validation_errors():
            return self.group_summary(rs, event_id)  # pragma: no cover
        code = self.eventproxy.set_part_groups(rs, event_id, {part_group_id: None})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard()
    def add_track_group_form(self, rs: RequestState, event_id: int) -> Response:
        return self.render(rs, "event/configure_track_group")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata(*EVENT_TRACK_GROUP_COMMON_FIELDS)
    def add_track_group(self, rs: RequestState, event_id: int, title: str,
                       shortname: str, notes: Optional[str], sortkey: int,
                       constraint_type: const.CourseTrackGroupType,
                       track_ids: Collection[int]) -> Response:
        if track_ids and not set(track_ids) <= rs.ambience['event'].tracks.keys():
            rs.append_validation_error(("track_ids", ValueError(n_("Unknown track."))))
        data = {
            'title': title,
            'shortname': shortname,
            'notes': notes,
            'constraint_type': constraint_type,
            'sortkey': sortkey,
            'track_ids': track_ids,
        }
        existing = {tg.title for tg in rs.ambience['event'].track_groups.values()}
        if data['title'] in existing:
            rs.append_validation_error(('title', ValueError(n_(
                "A track group with this name already exists."))))
        existing = {tg.shortname for tg in rs.ambience['event'].track_groups.values()}
        if data['shortname'] in existing:
            rs.append_validation_error(('shortname', ValueError(n_(
                "A track group with this name already exists."))))
        data = check(rs, vtypes.EventTrackGroup, data)
        if rs.has_validation_errors():
            return self.add_track_group_form(rs, event_id)
        event = rs.ambience['event']
        tracks = event.tracks
        if constraint_type.is_sync():
            track_ids = set(track_ids)
            if any(tg.constraint_type.is_sync() and set(tg.tracks) & track_ids
                   for tg in event.track_groups.values()):
                rs.append_validation_error((
                    "track_ids",
                    ValueError(n_("Cannot have more than one course choice sync"
                                  " track group per track.")),
                ))
            if not len(set(
                    (tracks[track_id].num_choices, tracks[track_id].min_choices)
                    for track_id in track_ids),
            ) == 1:
                rs.append_validation_error((
                    "track_ids", ValueError(n_("Incompatible tracks.")),
                ))
            if not self.eventproxy.may_create_ccs_group(rs, track_ids):
                rs.append_validation_error((
                    "track_ids", ValueError(n_("Cannot create CCS group due to"
                                               " incompatible choices."))))
            if rs.has_validation_errors():
                return self.add_track_group_form(rs, event_id)
        code = self.eventproxy.set_track_groups(rs, event_id, {-1: data})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event")
    @event_guard()
    def change_track_group_form(self, rs: RequestState, event_id: int,
                                track_group_id: int) -> Response:
        merge_dicts(rs.values, rs.ambience['track_group'].as_dict())
        # add this to autofill the values correctly (they are readonly anyway)
        merge_dicts(rs.values, {"track_ids": rs.ambience['track_group'].tracks.keys()})
        return self.render(rs, "event/configure_track_group")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("title", "shortname", "notes", "sortkey")
    def change_track_group(self, rs: RequestState, event_id: int,
                          track_group_id: int, title: str, shortname: str,
                          notes: Optional[str], sortkey: int) -> Response:
        data: CdEDBObject = {
            'title': title,
            'shortname': shortname,
            'notes': notes,
            'sortkey': sortkey,
        }
        existing = {tg.title for tg in rs.ambience['event'].track_groups.values()}
        if data['title'] in existing - {rs.ambience['track_group'].title}:
            rs.append_validation_error(('title', ValueError(n_(
                "A track group with this name already exists."))))
        existing = {tg.shortname for tg in rs.ambience['event'].track_groups.values()}
        if data['shortname'] in existing - {rs.ambience['track_group'].shortname}:
            rs.append_validation_error(('shortname', ValueError(n_(
                "A track group with this name already exists."))))
        data = check(rs, vtypes.EventTrackGroup, data)
        if rs.has_validation_errors():
            return self.change_track_group_form(rs, event_id, track_group_id)
        code = self.eventproxy.set_track_groups(rs, event_id, {track_group_id: data})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_track_group(self, rs: RequestState, event_id: int, track_group_id: int,
                           ack_delete: bool) -> Response:
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.group_summary(rs, event_id)  # pragma: no cover
        code = self.eventproxy.set_track_groups(rs, event_id, {track_group_id: None})
        rs.notify_return_code(code)
        return self.redirect(rs, "event/group_summary")

    @periodic("mail_orgateam_reminders", period=4*24)  # once per day
    def mail_orgateam_reminders(self, rs: RequestState, store: CdEDBObject,
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
                "Reply-To": "akademien@lists.cde-ev.de",
            }
            # send halftime mail (up to one per part)
            if any(is_halftime(part) for part in event.parts.values()):
                headers["Subject"] = ("Halbzeit! Was ihr vor Ende der Akademie nicht"
                                      " vergessen solltet")
                self.do_mail(rs, "halftime_reminder", headers)
            # send past event mail (one per event)
            elif all(is_over(part) for part in event.parts.values()):
                headers["Subject"] = "Wichtige Nach-Aka-Checkliste vom Akademieteam"
                params = {"rechenschafts_deadline": now() + datetime.timedelta(days=90)}
                self.do_mail(rs, "past_event_reminder", headers, params=params)
                store[str(event_id)]["did_past_event_reminder"] = True
        return store

    @staticmethod
    def _get_mailinglist_setter(rs: RequestState, event: CdEDBObject,
                                orgalist: bool = False) -> Mailinglist:
        if orgalist:
            descr = ("Bitte wende Dich bei Fragen oder Problemen, die mit"
                     " unserer Veranstaltung zusammenhängen, über diese Liste"
                     " an uns.")
            orga_ml_data = EventOrgaMailinglist(
                id=vtypes.CreationID(vtypes.ProtoID(-1)),
                title=f"{event['title']} Orgateam",
                local_part=vtypes.EmailLocalPart(f"{event['shortname'].lower()}-orga"),
                domain=const.MailinglistDomain.aka,
                description=descr,
                mod_policy=const.ModerationPolicy.unmoderated,
                attachment_policy=const.AttachmentPolicy.allow,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=event['shortname'],
                maxsize=EventOrgaMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                event_id=event['id'],
                notes=None,
                moderators=event['orgas'],
                whitelist=set(),
            )
            return orga_ml_data
        else:
            link = cdedburl(rs, "event/register", {'event_id': event["id"]})
            descr = (f"Dieser Liste kannst Du nur beitreten, indem Du Dich zu "
                     f"unserer [Veranstaltung anmeldest]({link}) und den Status "
                     f"*Teilnehmer* erhälst. Auf dieser Liste stehen alle "
                     f"Teilnehmer unserer Veranstaltung; sie kann im Vorfeld "
                     f"zum Austausch untereinander genutzt werden.")
            participant_ml_data = EventAssociatedMailinglist(
                id=vtypes.CreationID(vtypes.ProtoID(-1)),
                title=f"{event['title']} Teilnehmer",
                local_part=vtypes.EmailLocalPart(f"{event['shortname'].lower()}-all"),
                domain=const.MailinglistDomain.aka,
                description=descr,
                mod_policy=const.ModerationPolicy.non_subscribers,
                attachment_policy=const.AttachmentPolicy.pdf_only,
                convert_html=True,
                roster_visibility=const.MailinglistRosterVisibility.none,
                subject_prefix=event['shortname'],
                maxsize=EventAssociatedMailinglist.maxsize_default,
                additional_footer=None,
                is_active=True,
                event_id=event["id"],
                registration_stati=[const.RegistrationPartStati.participant],
                notes=None,
                moderators=event['orgas'],
                whitelist=set(),
            )
            return participant_ml_data

    @access("event_admin")
    def create_event_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "event/create_event",
                           {'accounts': self.conf["EVENT_BANK_ACCOUNTS"]})

    @access("event_admin", modi={"POST"})
    @REQUESTdata("part_begin", "part_end", "orga_ids", "create_track",
                 "fee", "nonmember_surcharge",
                 "create_orga_list", "create_participant_list")
    @REQUESTdatadict(*EVENT_EXPOSED_FIELDS)
    def create_event(self, rs: RequestState, part_begin: datetime.date,
                     part_end: datetime.date, orga_ids: vtypes.CdedbIDList,
                     fee: vtypes.NonNegativeDecimal,
                     nonmember_surcharge: vtypes.NonNegativeDecimal,
                     create_track: bool, create_orga_list: bool,
                     create_participant_list: bool, data: CdEDBObject,
                     ) -> Response:
        """Create a new event, organized via DB."""
        # multi part events will have to edit this later on
        data.update({
            'orgas': orga_ids,
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
                        } if create_track else {}
                    ),
                },
            },
            'fees': {
                -1: {
                    'kind': const.EventFeeType.common,
                    'title': data['title'],
                    'notes': "Automatisch erstellt.",
                    'amount': fee,
                    'condition': f"part.{data['shortname']}",
                },
                -2: {
                    'kind': const.EventFeeType.external,
                    'title': "Externenzusatzbeitrag",
                    'notes': "Automatisch erstellt",
                    'amount': nonmember_surcharge,
                    'condition': "any_part and not is_member",
                },
            },
        })
        if (data and data['shortname']
                and self.eventproxy.verify_shortname_existence(rs, data['shortname'])):
            rs.append_validation_error(
                ('shortname', ValueError(
                    n_("Shortname already in use for another event."),
                )),
            )
        data = check(rs, vtypes.Event, data, creation=True)
        if orga_ids:
            if not self.coreproxy.verify_ids(rs, orga_ids, is_archived=False):
                rs.append_validation_error(
                    ('orga_ids', ValueError(
                        n_("Some of these users do not exist or are archived."),
                    )),
                )
            if not self.coreproxy.verify_personas(rs, orga_ids, {"event"}):
                rs.append_validation_error(
                    ('orga_ids', ValueError(
                        n_("Some of these users are not event users."),
                    )),
                )
        else:
            if create_orga_list or create_participant_list:
                # mailinglists require moderators
                rs.append_validation_error(
                    ("orga_ids", ValueError(
                        n_("Must not be empty in order to create a mailinglist."),
                    )),
                )
        if rs.has_validation_errors():
            return self.create_event_form(rs)
        assert data is not None

        new_id = self.eventproxy.create_event(rs, data)
        data["id"] = new_id

        if create_orga_list:
            orga_ml_data = self._get_mailinglist_setter(rs, data, orgalist=True)
            if self.mlproxy.verify_existence(rs, orga_ml_data.address):
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': orga_ml_data.address})
            else:
                code = self.mlproxy.create_mailinglist(rs, orga_ml_data)
                rs.notify_return_code(code, success=n_("Orga mailinglist created."))
            code = self.eventproxy.set_event(
                rs, new_id, {"orga_address": orga_ml_data.address},
                change_note="Mailadresse der Orgas gesetzt.")
            rs.notify_return_code(code)
        if create_participant_list:
            participant_ml_data = self._get_mailinglist_setter(rs, data)
            if not self.mlproxy.verify_existence(rs, participant_ml_data.address):
                code = self.mlproxy.create_mailinglist(rs, participant_ml_data)
                rs.notify_return_code(code,
                                      success=n_("Participant mailinglist created."))
            else:
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': participant_ml_data.address})
        rs.notify_return_code(new_id, success=n_("Event created."))
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs: RequestState, event_id: int) -> Response:
        """Lock an event for offline usage."""
        if not rs.has_validation_errors():
            code = self.eventproxy.lock_event(rs, event_id)
            rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTfile("json")
    def unlock_event(self, rs: RequestState, event_id: int,
                     json: werkzeug.datastructures.FileStorage) -> Response:
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        # for the sake of simplicity, we ignore all ValidationWarnings here.
        # Since the data is incorporated from an offline instance, they were already
        # considered to be reasonable.
        rs.ignore_warnings = True

        data = check(rs, vtypes.SerializedEventUpload, json)
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        assert data is not None
        if event_id != data['id']:
            rs.notify("error", n_("Data from wrong event."))
            return self.show_event(rs, event_id)
        # Check for unmigrated personas
        current = self.eventproxy.export_event(rs, event_id)
        claimed = {e['persona_id'] for e in data['event.registrations'].values()
                   if not e['real_persona_id']}
        if claimed - set(current['core.personas']):
            rs.notify("error", n_("There exist unmigrated personas."))
            return self.show_event(rs, event_id)

        code = self.eventproxy.unlock_import_event(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_archive", "create_past_event")
    def archive_event(self, rs: RequestState, event_id: int, ack_archive: bool,
                      create_past_event: bool) -> Response:
        """Archive an event and optionally create a past event.

        This is at the boundary between event and cde frontend, since
        the past-event stuff generally resides in the cde realm.
        """
        if rs.ambience['event'].is_archived:
            rs.ignore_validation_errors()
            rs.notify("warning", n_("Event already archived."))
            return self.redirect(rs, "event/show_event")
        if not ack_archive:
            rs.append_validation_error(
                ("ack_archive", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if (not rs.ambience['event'].is_cancelled and
                rs.ambience['event'].end >= now().date()):
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        if create_past_event:
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            registrations = self.eventproxy.get_registrations(rs, registration_ids)
            if not any(rpart['status'] == const.RegistrationPartStati.participant
                       for reg in registrations.values()
                       for rpart in reg['parts'].values()):
                rs.notify("error", n_("No event parts have any participants."))
                return self.redirect(rs, "event/show_event")

        new_ids, message = self.pasteventproxy.archive_event(
            rs, event_id, create_past_event=create_past_event)

        if message:
            rs.notify("error", message)
            return self.redirect(rs, "event/show_event")

        # Lock all questionnaire entries
        aq = const.QuestionnaireUsages.additional
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id, [aq])[aq]
        for entry in questionnaire:
            entry['readonly'] = True
        self.eventproxy.set_questionnaire(rs, event_id, {aq: questionnaire})

        # Delete non-pseudonymized event keeper only after internal work has been
        # concluded successfully

        # Deleting event keeper here is too early for now.
        # self.eventproxy.event_keeper_drop(rs, event_id)

        rs.notify("success", n_("Event archived."))
        if new_ids is None:
            return self.redirect(rs, "event/show_event")
        elif len(new_ids) == 1:
            rs.notify("info", n_("Created past event."))
            return self.redirect(rs, "cde/show_past_event",
                                 {'pevent_id': unwrap(new_ids)})
        else:
            rs.notify("info", n_("Created multiple past events."))
            return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_event(self, rs: RequestState, event_id: int, ack_delete: bool,
                     ) -> Response:
        """Remove an event."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if rs.ambience['event'].end >= now().date():
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        blockers = self.eventproxy.delete_event_blockers(rs, event_id)
        cascade = {
            "registrations", "courses", "lodgement_groups", "lodgements",
            "field_definitions", "course_tracks", "event_parts", "event_fees",
            "orgas", "questionnaire", "stored_queries", "log", "mailinglists",
            "part_groups", "orga_tokens", "custom_query_filters",
        }

        code = self.eventproxy.delete_event(rs, event_id, cascade & blockers.keys())
        if not code:
            return self.show_event(rs, event_id)
        else:
            rs.notify("success", n_("Event deleted."))
            return self.redirect(rs, "event/index")

    @access("event")
    @event_guard()
    @REQUESTdata("phrase")
    def quick_show_registration(self, rs: RequestState, event_id: int,
                                phrase: str) -> Response:
        """Allow orgas to quickly retrieve a registration.

        The search phrase may be anything: a numeric id or a string
        matching the data set.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        anid, errs = inspect(vtypes.CdedbID, phrase, argname="phrase")
        if not errs:
            reg_ids = self.eventproxy.list_registrations(
                rs, event_id, persona_id=anid)
            if reg_ids:
                reg_id = unwrap(reg_ids.keys())
                return self.redirect(rs, "event/show_registration",
                                     {'registration_id': reg_id})

        anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            regs = self.eventproxy.get_registrations(rs, (anid,))
            if regs:
                reg = unwrap(regs)
                if reg['event_id'] == event_id:
                    return self.redirect(rs, "event/show_registration",
                                         {'registration_id': reg['id']})

        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        valid = True
        for t in terms:
            _, errs = inspect(vtypes.NonRegex, t, argname="phrase")
            if errs:
                valid = False
        if not valid:
            rs.notify("warning", n_("Active characters found in search."))
            return self.show_event(rs, event_id)

        key = "username,family_name,given_names,display_name"
        search = [(key, QueryOperators.match, t) for t in terms]
        spec = QueryScope.quick_registration.get_spec()
        spec[key] = QuerySpecEntry("str", "")
        query = Query(
            QueryScope.quick_registration, spec,
            ("registrations.id", "username", "family_name",
             "given_names", "display_name"),
            search, (("registrations.id", True),))
        result = self.eventproxy.submit_general_query(
            rs, query, event_id=event_id)
        if len(result) == 1:
            return self.redirect(rs, "event/show_registration",
                                 {'registration_id': result[0]['id']})
        elif result:
            # TODO make this accessible
            pass
        base_query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"],
            [],
            (("persona.family_name", True), ("persona.given_names", True)),
        )
        regex = "({})".format("|".join(terms))
        given_names_constraint = (
            'persona.given_names', QueryOperators.regex, regex)
        family_name_constraint = (
            'persona.family_name', QueryOperators.regex, regex)

        for effective in ([given_names_constraint, family_name_constraint],
                          [given_names_constraint],
                          [family_name_constraint]):
            query = copy.deepcopy(base_query)
            query.constraints.extend(effective)
            result = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            if len(result) == 1:
                return self.redirect(rs, "event/show_registration",
                                     {'registration_id': result[0]['id']})
            elif result:
                params = query.serialize_to_url()
                return self.redirect(rs, "event/registration_query", params)
        rs.notify("warning", n_("No registration found."))
        return self.show_event(rs, event_id)
