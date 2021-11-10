#!/usr/bin/env python3

"""
The `EventFieldsMixin` subclasses the `EventBaseFrontend` and provides endpoints for
managing and using custom datafields.
"""

from collections import Counter
from typing import Any, Callable, Collection, Dict, List, Optional, Tuple, cast

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, CdEDBOptionalMap, EntitySorter, RequestState,
    merge_dicts, n_, unwrap, xsorted,
)
from cdedb.filter import safe_filter
from cdedb.frontend.common import (
    REQUESTdata, access, check_validation as check, event_guard, make_persona_name,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.query import Query, QueryOperators, QueryScope
from cdedb.validation import _EVENT_FIELD_ALL_FIELDS
from cdedb.validationtypes import VALIDATOR_LOOKUP

EntitySetter = Callable[[RequestState, Dict[str, Any]], int]


class EventFieldMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def field_summary_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        formatter = lambda k, v: (v if k != 'entries' or not v else
                                  '\n'.join(';'.join(line) for line in v))
        current = {
            "{}_{}".format(key, field_id): formatter(key, value)
            for field_id, field in rs.ambience['event']['fields'].items()
            for key, value in field.items() if key != 'id'}
        merge_dicts(rs.values, current)
        referenced = set()
        fee_modifiers = set()
        full_questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        for v in full_questionnaire.values():
            for row in v:
                if row['field_id']:
                    referenced.add(row['field_id'])
        if rs.ambience['event']['lodge_field']:
            referenced.add(rs.ambience['event']['lodge_field'])
        if rs.ambience['event']['camping_mat_field']:
            referenced.add(rs.ambience['event']['camping_mat_field'])
        if rs.ambience['event']['course_room_field']:
            referenced.add(rs.ambience['event']['course_room_field'])
        for mod in rs.ambience['event']['fee_modifiers'].values():
            referenced.add(mod['field_id'])
            fee_modifiers.add(mod['field_id'])
        for part in rs.ambience['event']['parts'].values():
            if part['waitlist_field']:
                referenced.add(part['waitlist_field'])
        return self.render(rs, "fields/field_summary", {
            'referenced': referenced, 'fee_modifiers': fee_modifiers})

    @staticmethod
    def process_field_input(rs: RequestState, fields: CdEDBObjectMap
                            ) -> CdEDBOptionalMap:
        """This handles input to configure the fields.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.
        """
        delete_flags = request_extractor(
            rs, {f"delete_{field_id}": bool for field_id in fields})
        deletes = {field_id for field_id in fields
                   if delete_flags['delete_{}'.format(field_id)]}
        ret: CdEDBOptionalMap = {}

        for field_id in fields:
            if field_id not in deletes:
                suffix = f"_{field_id}"
                params = _EVENT_FIELD_ALL_FIELDS(suffix)
                field_data: Optional[CdEDBObject] = request_extractor(rs, params)
                if rs.has_validation_errors():
                    continue
                field_data = check(
                    rs, vtypes.EventField, field_data, extra_suffix=suffix)
                if field_data:
                    ret[field_id] = {
                        k.removesuffix(suffix): field_data[k]
                        for k in params
                    }
        for field_id in deletes:
            ret[field_id] = None
        marker = 1

        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(rs, {f"create_-{marker}": bool}))
            if will_create:
                suffix = f"_{marker}"
                params = {
                    **_EVENT_FIELD_ALL_FIELDS(suffix),
                    'field_name': str
                }
                new_field: Optional[CdEDBObject] = request_extractor(rs, params)
                if rs.has_validation_errors():
                    marker += 1
                    break
                new_field = check(rs, vtypes.EventField, new_field, creation=True,
                                  extra_suffix=suffix)
                if new_field:
                    ret[-marker] = {
                        k.removesuffix(suffix): new_field[k]
                        for k in params
                    }
            else:
                break
            marker += 1

        def field_name(field_id: int, field: Optional[CdEDBObject]) -> str:
            """Helper to get the name of a (new or existing) field."""
            return (field['field_name'] if field and 'field_name' in field
                    else fields[field_id]['field_name'])
        count = Counter(field_name(f_id, field) for f_id, field in ret.items())
        for field_id, field in ret.items():
            if field and count.get(field_name(field_id, field), 0) > 1:
                rs.append_validation_error(
                    (f"field_name_{field_id}",
                     ValueError(n_("Field name not unique."))))
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("active_tab")
    def field_summary(self, rs: RequestState, event_id: int, active_tab: Optional[str]
                      ) -> Response:
        """Manipulate the fields of an event."""
        fields = self.process_field_input(rs, rs.ambience['event']['fields'])
        if rs.has_validation_errors():
            return self.field_summary_form(rs, event_id)
        for field_id, field in rs.ambience['event']['fields'].items():
            if fields.get(field_id) == field:
                # remove unchanged
                del fields[field_id]
        event = {
            'id': event_id,
            'fields': fields
        }
        code = self.eventproxy.set_event(rs, event)
        self.notify_return_code(rs, code)
        return self.redirect(
            rs, "event/field_summary_form", anchor=(
                ("tab:" + active_tab) if active_tab is not None else None))

    FIELD_REDIRECT = {
        const.FieldAssociations.registration: "event/registration_query",
        const.FieldAssociations.course: "event/course_query",
        const.FieldAssociations.lodgement: "event/lodgement_query",
    }

    def field_set_aux(self, rs: RequestState, event_id: int, field_id: Optional[int],
                      ids: Collection[int], kind: const.FieldAssociations) \
            -> Tuple[CdEDBObjectMap, List[int], Dict[int, str], Optional[CdEDBObject]]:
        """Process field set inputs.

        This function retrieves the data dependent on the given kind and returns it in
        a standardized way to be used in the generic field_set_* functions.

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
            if field_id not in rs.ambience['event']['fields']:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated event."))
            field = rs.ambience['event']['fields'][field_id]
            if field['association'] != kind:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        else:
            field = None

        return entities, ordered_ids, labels, field

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind")
    def field_set_select(self, rs: RequestState, event_id: int,
                         field_id: Optional[vtypes.ID],
                         ids: Optional[vtypes.IntCSVList],
                         kind: const.FieldAssociations) -> Response:
        """Select a field for manipulation across multiple entities."""
        if rs.has_validation_errors():
            return self.render(rs, "fields/field_set_select")
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        if field_id:
            return self.redirect(
                rs, "event/field_set_form", {
                    'ids': (','.join(str(i) for i in ids) if ids else None),
                    'field_id': field_id, 'kind': kind.value})
        _, ordered_ids, labels, _ = self.field_set_aux(rs, event_id, field_id, ids,
                                                       kind)
        fields = [(field['id'], field['title'])
                  for field in xsorted(rs.ambience['event']['fields'].values(),
                                       key=EntitySorter.event_field)
                  if field['association'] == kind]
        return self.render(
            rs, "fields/field_set_select", {
                'ids': (','.join(str(i) for i in ids) if ids else None),
                'ordered': ordered_ids, 'labels': labels, 'fields': fields,
                'kind': kind.value, 'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind", "change_note")
    def field_set_form(self, rs: RequestState, event_id: int, field_id: vtypes.ID,
                       ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
                       change_note: Optional[str] = None, internal: bool = False
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

        entities, ordered_ids, labels, field = self.field_set_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        values = {f"input{anid}": entity['fields'].get(field['field_name'])
                  for anid, entity in entities.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "fields/field_set", {
            'ids': (','.join(str(i) for i in ids) if ids else None),
            'entities': entities, 'labels': labels, 'ordered': ordered_ids,
            'kind': kind.value, 'change_note': change_note,
            'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind", "change_note")
    def field_set(self, rs: RequestState, event_id: int, field_id: vtypes.ID,
                  ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
                  change_note: Optional[str] = None) -> Response:
        """Modify a specific field on the given entities."""
        if rs.has_validation_errors():
            return self.field_set_form(  # type: ignore
                rs, event_id, kind=kind, change_note=change_note, internal=True)
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        entities, _, _, field = self.field_set_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        if kind == const.FieldAssociations.registration:
            if change_note:
                change_note = f"{field['field_name']} gesetzt: " + change_note
            else:
                change_note = f"{field['field_name']} gesetzt."
        elif change_note:
            rs.append_validation_error(
                (None, ValueError(n_("change_note only supported for registrations."))))

        data_params: vtypes.TypeMapping = {
            f"input{anid}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for anid in entities
        }
        data = request_extractor(rs, data_params)
        if rs.has_validation_errors():
            return self.field_set_form(  # type: ignore
                rs, event_id, kind=kind, internal=True)

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
        for anid, entity in entities.items():
            if data[f"input{anid}"] != entity['fields'].get(field['field_name']):
                new = {
                    'id': anid,
                    'fields': {field['field_name']: data[f"input{anid}"]}
                }
                if change_note:
                    code *= entity_setter(rs, new, change_note)  # type: ignore
                else:
                    code *= entity_setter(rs, new)
        self.notify_return_code(rs, code)

        if kind == const.FieldAssociations.registration:
            query = Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=rs.ambience['event']),
                ("persona.given_names", "persona.family_name", "persona.username",
                 "reg.id", f"reg_fields.xfield_{field['field_name']}"),
                (("reg.id", QueryOperators.oneof, entities),),
                (("persona.family_name", True), ("persona.given_names", True))
            )
        elif kind == const.FieldAssociations.course:
            query = Query(
                QueryScope.lodgement,
                QueryScope.lodgement.get_spec(event=rs.ambience['event']),
                ("course.nr", "course.shortname", "course.title", "course.id",
                 f"course_fields.xfield_{field['field_name']}"),
                (("course.id", QueryOperators.oneof, entities),),
                (("course.nr", True), ("course.shortname", True))
            )
        elif kind == const.FieldAssociations.lodgement:
            query = Query(
                QueryScope.lodgement,
                QueryScope.lodgement.get_spec(event=rs.ambience['event']),
                ("lodgement.title", "lodgement_group.title", "lodgement.id",
                 f"lodgement_fields.xfield_{field['field_name']}"),
                (("lodgement.id", QueryOperators.oneof, entities),),
                (("lodgement.title", True), ("lodgement.id", True))
            )
        else:
            # this can not happen, since kind was validated successfully
            raise NotImplementedError(f"Unknown kind {kind}.")

        redirect = self.FIELD_REDIRECT[kind]
        return self.redirect(rs, redirect, query.serialize())
