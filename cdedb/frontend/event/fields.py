#!/usr/bin/env python3

"""
The `EventFieldsMixin` subclasses the `EventBaseFrontend` and provides endpoints for
managing and using custom datafields.
"""

from collections import Counter
from collections.abc import Collection
from typing import Any, Callable, Optional, cast

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    CdEDBObject,
    CdEDBObjectMap,
    RequestState,
    build_msg,
    make_persona_name,
    merge_dicts,
)
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.types import VALIDATOR_LOOKUP
from cdedb.filter import safe_filter
from cdedb.frontend.common import (
    REQUESTdata,
    access,
    drow_name,
    event_guard,
    process_dynamic_input,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend

EntitySetter = Callable[[RequestState, dict[str, Any]], int]


class EventFieldMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def field_summary_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        formatter = lambda k, v: (v if k != 'entries' or not v else
                                  '\n'.join(f'{value};{description}'
                                            for value, description in v.items()))
        current = {
            f"{key}_{field_id}": formatter(key, value)
            for field_id, field in rs.ambience['event'].fields.items()
            for key, value in field.as_dict().items() if key != 'id'
        }
        merge_dicts(rs.values, current)
        event_fees_per_field = self.eventproxy.get_event_fees_per_entity(
            rs, event_id).fields
        locked = {
            field_id
            for field_id, fee_ids in event_fees_per_field.items() if fee_ids
        }
        referenced = set()
        full_questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        for v in full_questionnaire.values():
            for row in v:
                if row['field_id']:
                    referenced.add(row['field_id'])
        if rs.ambience['event'].lodge_field:
            referenced.add(rs.ambience['event'].lodge_field.id)
        for part in rs.ambience['event'].parts.values():
            if part.waitlist_field:
                referenced.add(part.waitlist_field.id)
            if part.camping_mat_field:
                referenced.add(part.camping_mat_field.id)
        for track in rs.ambience['event'].tracks.values():
            if track.course_room_field:
                referenced.add(track.course_room_field.id)
        return self.render(rs, "fields/field_summary", {
            'referenced': referenced, 'locked': locked})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("active_tab")
    def field_summary(self, rs: RequestState, event_id: int, active_tab: Optional[str],
                      ) -> Response:
        """Manipulate the fields of an event."""
        mandatory, optional = models.EventField.validation_fields(creation=False)
        spec = dict(mandatory) | dict(optional)
        creation_mandatory, creation_optional = models.EventField.validation_fields(
            creation=True)
        creation_spec = dict(creation_mandatory) | dict(creation_optional)
        existing_fields = rs.ambience['event'].fields.keys()
        fields = process_dynamic_input(
            rs, vtypes.EventField, existing_fields, spec, creation_spec=creation_spec)

        def field_name(field_id: int, field: Optional[CdEDBObject]) -> str:
            """Helper to get the name of a (new or existing) field."""
            return (field['field_name'] if field and 'field_name' in field
                    else rs.ambience['event'].fields[field_id].field_name)

        count = Counter(
            field_name(f_id, field) for f_id, field in fields.items() if field)
        for field_id, field in fields.items():
            if field and count.get(field_name(field_id, field), 0) > 1:
                rs.append_validation_error(
                    (drow_name("field_name", field_id),
                     ValueError(n_("Field name not unique."))))

        if rs.has_validation_errors():
            return self.field_summary_form(rs, event_id)
        for field_id, field in rs.ambience['event'].fields.items():
            if fields.get(field_id) == field:
                # remove unchanged
                del fields[field_id]
        self.eventproxy.event_keeper_commit(
            rs, event_id, "Snapshot vor Datenfeld-Änderungen.")
        code = self.eventproxy.set_event(rs, event_id, {'fields': fields})
        self.eventproxy.event_keeper_commit(
            rs, event_id, "Ändere Datenfelder.", after_change=True)
        rs.notify_return_code(code)
        return self.redirect(
            rs, "event/field_summary_form", anchor=(
                ("tab:" + active_tab) if active_tab is not None else None))

    FIELD_REDIRECT = {
        const.FieldAssociations.registration: "event/registration_query",
        const.FieldAssociations.course: "event/course_query",
        const.FieldAssociations.lodgement: "event/lodgement_query",
    }

    def field_multiset_aux(
            self, rs: RequestState, event_id: int, field_id: Optional[int],
            ids: Collection[int], kind: const.FieldAssociations,
    ) -> tuple[CdEDBObjectMap, list[int], dict[int, str], Optional[models.EventField]]:
        """Process field set inputs.

        This function retrieves the data dependent on the given kind and returns it in
        a standardized way to be used in the generic field_multiset_* functions.

        :param ids: ids of the entities where the field should be modified.
        :param kind: specifies the entity: registration, course or lodgement

        :returns: A tuple of values, containing
            * entities: corresponding to the given ids (registrations, courses,
                lodgements)
            * ordered_ids: given ids, sorted by the corresponding EntitySorter
            * labels: name of the entities which will be displayed in the template
            * field: the event field which will be changed, None if no field_id was
                given
        """
        if kind == const.FieldAssociations.registration:
            if not ids:
                ids = self.eventproxy.list_registrations(rs, event_id)
            entities = self.eventproxy.get_registrations(rs, ids)
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in entities.values()))
            labels = {
                reg_id: make_persona_name(personas[entity['persona_id']])
                for reg_id, entity in entities.items()}
            ordered_ids = xsorted(
                entities.keys(), key=lambda anid: EntitySorter.persona(
                    personas[entities[anid]['persona_id']]))
        elif kind == const.FieldAssociations.course:
            if not ids:
                ids = self.eventproxy.list_courses(rs, event_id)
            entities = self.eventproxy.get_courses(rs, ids)
            labels = {course_id: f"{course['nr']} {course['shortname']}"
                      for course_id, course in entities.items()}
            ordered_ids = xsorted(
                entities.keys(), key=lambda anid: EntitySorter.course(entities[anid]))
        elif kind == const.FieldAssociations.lodgement:
            if not ids:
                ids = self.eventproxy.list_lodgements(rs, event_id)
            entities = self.eventproxy.get_lodgements(rs, ids)
            group_ids = {lodgement['group_id'] for lodgement in entities.values()
                         if lodgement['group_id'] is not None}
            groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
            labels = {
                lodg_id: f"{lodg['title']}" if lodg['group_id'] is None
                         else safe_filter(f"{lodg['title']}, <em>"
                                          f"{groups[lodg['group_id']]['title']}</em>")
                for lodg_id, lodg in entities.items()}
            ordered_ids = xsorted(
                entities.keys(),
                key=lambda anid: EntitySorter.lodgement(entities[anid]))
        else:
            # this should not happen, since we check before for validation errors
            raise NotImplementedError(f"Unknown kind {kind}")

        if field_id:
            if field_id not in rs.ambience['event'].fields:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated event."))
            field = rs.ambience['event'].fields[field_id]
            if field.association != kind:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        else:
            field = None

        return entities, ordered_ids, labels, field

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind")
    def field_multiset_select(
            self, rs: RequestState, event_id: int, field_id: Optional[vtypes.ID],
            ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
    ) -> Response:
        """Select a field for manipulation across multiple entities."""
        if rs.has_validation_errors():
            # If the kind is invalid, we do not know where to redirect to.
            # This should never happen without HTML manipulation, anyway.
            return self.redirect(rs, "event/show_event")
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        if field_id:
            return self.redirect(
                rs, "event/field_multiset_form", {
                    'ids': (','.join(str(i) for i in ids) if ids else None),
                    'field_id': field_id, 'kind': kind.value})
        _, ordered_ids, labels, _ = self.field_multiset_aux(rs, event_id, field_id, ids,
                                                       kind)
        fields = [(field.id, field.title)
                  for field in xsorted(rs.ambience['event'].fields.values())
                  if field.association == kind]
        return self.render(
            rs, "fields/field_multiset_select", {
                'ids': (','.join(str(i) for i in ids) if ids else None),
                'ordered': ordered_ids, 'labels': labels, 'fields': fields,
                'kind': kind.value, 'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind", "change_note")
    def field_multiset_form(
            self, rs: RequestState, event_id: int, field_id: vtypes.ID,
            ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
            change_note: Optional[str] = None, internal: bool = False,
    ) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            redirect = self.FIELD_REDIRECT.get(kind, "event/show_event")
            return self.redirect(rs, redirect)
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        entities, ordered_ids, labels, field = self.field_multiset_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        values = {f"input{anid}": entity['fields'].get(field.field_name)
                  for anid, entity in entities.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "fields/field_multiset", {
            'ids': (','.join(str(i) for i in ids) if ids else None),
            'entities': entities, 'labels': labels, 'ordered': ordered_ids,
            'kind': kind.value, 'change_note': change_note,
            'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind", "change_note")
    def field_multiset(
            self, rs: RequestState, event_id: int, field_id: vtypes.ID,
            ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
            change_note: Optional[str] = None,
    ) -> Response:
        """Modify a specific field on the given entities."""
        if rs.has_validation_errors():
            return self.field_multiset_form(
                rs, event_id, field_id=field_id, ids=ids, kind=kind,
                change_note=change_note, internal=True)
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        entities, _, _, field = self.field_multiset_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        msg = ""
        if kind == const.FieldAssociations.registration:
            msg = build_msg(f"{field.field_name} gesetzt", change_note)
        elif change_note:
            rs.append_validation_error(
                (None, ValueError(n_("change_note only supported for registrations."))))

        data_params: vtypes.TypeMapping = {
            f"input{anid}": Optional[  # type: ignore[misc]
                VALIDATOR_LOOKUP[const.FieldDatatypes(field.kind).name]]
            for anid in entities
        }
        data = request_extractor(rs, data_params)
        if rs.has_validation_errors():
            return self.field_multiset_form(
                rs, event_id, field_id=field_id, ids=ids, kind=kind,
                change_note=change_note, internal=True)

        if kind == const.FieldAssociations.registration:
            entity_setter: EntitySetter = self.eventproxy.set_registration
        elif kind == const.FieldAssociations.course:
            entity_setter = self.eventproxy.set_course
        elif kind == const.FieldAssociations.lodgement:
            entity_setter = self.eventproxy.set_lodgement
        else:
            # this can not happen, since kind was validated successfully
            raise NotImplementedError(f"Unknown kind {kind}.")

        code = 1
        pre_msg = build_msg(
            f"Snapshot vor Setzen von Feld {field.field_name}", change_note)
        post_msg = build_msg(f"Setze Feld {field.field_name}", change_note)
        self.eventproxy.event_keeper_commit(rs, event_id, pre_msg)
        for anid, entity in entities.items():
            if data[f"input{anid}"] != entity['fields'].get(field.field_name):
                new = {
                    'id': anid,
                    'fields': {field.field_name: data[f"input{anid}"]},
                }
                if msg:
                    code *= entity_setter(rs, new, msg)  # type: ignore[call-arg]
                else:
                    code *= entity_setter(rs, new)
        self.eventproxy.event_keeper_commit(rs, event_id, post_msg, after_change=True)
        rs.notify_return_code(code)

        if kind == const.FieldAssociations.registration:
            query = Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=rs.ambience['event']),
                ("persona.given_names", "persona.family_name", "persona.username",
                 "reg.id", f"reg_fields.xfield_{field.field_name}"),
                (("reg.id", QueryOperators.oneof, entities),),
                (("persona.family_name", True), ("persona.given_names", True)),
            )
        elif kind == const.FieldAssociations.course:
            query = Query(
                QueryScope.lodgement,
                QueryScope.lodgement.get_spec(event=rs.ambience['event']),
                ("course.nr", "course.shortname", "course.title", "course.id",
                 f"course_fields.xfield_{field.field_name}"),
                (("course.id", QueryOperators.oneof, entities),),
                (("course.nr", True), ("course.shortname", True)),
            )
        elif kind == const.FieldAssociations.lodgement:
            query = Query(
                QueryScope.lodgement,
                QueryScope.lodgement.get_spec(event=rs.ambience['event']),
                ("lodgement.title", "lodgement_group.title", "lodgement.id",
                 f"lodgement_fields.xfield_{field.field_name}"),
                (("lodgement.id", QueryOperators.oneof, entities),),
                (("lodgement.title", True), ("lodgement.id", True)),
            )
        else:
            # this can not happen, since kind was validated successfully
            raise NotImplementedError(f"Unknown kind {kind}.")

        redirect = self.FIELD_REDIRECT[kind]
        return self.redirect(rs, redirect, query.serialize_to_url())
