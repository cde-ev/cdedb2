#!/usr/bin/env python3

"""The `EventLodgementMixin` subclasses the `EventBaseFrontend` and provides endpoints
for managings lodgements, lodgement groups and lodgements' inhabitants."""

import dataclasses
import itertools
from typing import Collection, Dict, List, Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.event.lodgement import LodgementInhabitants
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, LodgementsSortkeys, RequestState, make_persona_name,
    merge_dicts, unwrap,
)
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.sorting import EntitySorter, Sortkey, xsorted
from cdedb.common.validation.types import VALIDATOR_LOOKUP
from cdedb.common.validation.validate import LODGEMENT_COMMON_FIELDS
from cdedb.filter import keydictsort_filter
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, check_validation as check, drow_name,
    event_guard, process_dynamic_input, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.frontend.event.lodgement_wishes import (
    create_lodgement_wishes_graph, detect_lodgement_wishes,
)


@dataclasses.dataclass(frozen=True)
class LodgementProblem:
    description: str
    lodgement_id: int
    part_id: int
    reg_ids: Collection[int]
    severeness: int
    camping_mat: Optional[bool] = None


class EventLodgementMixin(EventBaseFrontend):
    @classmethod
    def check_lodgement_problems(
            cls, event: CdEDBObject, lodgements: CdEDBObjectMap,
            registrations: CdEDBObjectMap, personas: CdEDBObjectMap,
            all_inhabitants: Dict[int, Dict[int, LodgementInhabitants]]
    ) -> List[LodgementProblem]:
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        :returns: problems as five-tuples of (problem description, lodgement
          id, part id, affected registrations, severeness).
        """
        ret: List[LodgementProblem] = []
        camping_mat_field_names = cls._get_camping_mat_field_names(event)

        # first some un-inlined code pieces (otherwise nesting is a bitch)
        def _mixed(group: Collection[int]) -> bool:
            """Un-inlined check whether both genders are present.

            This ignores non-binary people.
            """
            return set(
                personas[registrations[reg_id]['persona_id']]['gender']
                for reg_id in group
            ) >= {const.Genders.male, const.Genders.female}

        complex_genders = {const.Genders.other, const.Genders.not_specified}
        # now the actual work
        for lodgement_id in lodgements:
            for part_id in event['parts']:
                lodgement = lodgements[lodgement_id]
                inhabitants = all_inhabitants[lodgement_id][part_id]
                reg, cm = inhabitants
                if len(reg) + len(cm) > (lodgement['regular_capacity']
                                         + lodgement['camping_mat_capacity']):
                    ret.append(LodgementProblem(
                        n_("Overful lodgement."),
                        lodgement_id, part_id, tuple(), 2))
                elif len(reg) > lodgement['regular_capacity']:
                    ret.append(LodgementProblem(
                        n_("Too few camping mats used."),
                        lodgement_id, part_id, tuple(), 2))
                if len(cm) > lodgement['camping_mat_capacity']:
                    ret.append(LodgementProblem(
                        n_("Too many camping mats used."),
                        lodgement_id, part_id, cm, 1))
                if camping_mat_field_names:
                    for reg_id in cm:
                        unhappy_campers = set()
                        if not registrations[reg_id]['fields'].get(
                                camping_mat_field_names[part_id]):
                            unhappy_campers.add(reg_id)
                        ret.append(LodgementProblem(
                            n_("Participants assigned to sleep on, but may not sleep"
                               " on a camping mat."),
                            lodgement_id, part_id, unhappy_campers, 1, True))
                non_mixed_lodging_people = tuple(
                    reg_id for reg_id in reg + cm
                    if not registrations[reg_id]['mixed_lodging'])
                if _mixed(reg + cm) and non_mixed_lodging_people:
                    ret.append(LodgementProblem(
                        n_("Mixed lodgement with non-mixing participants."),
                        lodgement_id, part_id, non_mixed_lodging_people, 3))
                complex_gender_people = tuple(
                    reg_id for reg_id in reg + cm
                    if (personas[registrations[reg_id]['persona_id']]['gender']
                        in complex_genders))
                if complex_gender_people:
                    ret.append(LodgementProblem(
                        n_("Non-Binary Participant."),
                        lodgement_id, part_id, complex_gender_people, 1))
        return ret

    @access("event")
    @event_guard()
    @REQUESTdata("sort_part_id", "sortkey", "reverse")
    def lodgements(self, rs: RequestState, event_id: int,
                   sort_part_id: Optional[vtypes.ID] = None,
                   sortkey: Optional[LodgementsSortkeys] = None,
                   reverse: bool = False) -> Response:
        """Overview of the lodgements of an event.

        This also displays some issues where possibly errors occured.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "event/lodgements")
        parts = rs.ambience['event']['parts']
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)

        # Get inhabitants per lodgement, part and status.
        inhabitants = self.eventproxy.get_grouped_inhabitants(rs, event_id)

        # Sum inhabitants per group, part and status.
        inhabitants_per_group = {
            group_id: {
                part_id: sum(
                    (inhabitants[lodgement_id][part_id]
                     for lodgement_id in group['lodgement_ids']),
                    start=LodgementInhabitants()
                )
                for part_id in parts
            }
            for group_id, group in groups.items()
        }

        # Sum inhabitants per part and status.
        total_inhabitants = {
            part_id: sum(
                (inhabitants_per_group[group_id][part_id] for group_id in groups),
                start=LodgementInhabitants()
            )
            for part_id in parts
        }
        # Calculate sum of lodgement regular and camping mat capacities
        total_reg_capacity = sum(g['regular_capacity'] for g in groups.values())
        total_cm_capacity = sum(g['camping_mat_capacity'] for g in groups.values())

        # Calculate problems_condensed (worst problem)
        problems = self.check_lodgement_problems(
            rs.ambience['event'], lodgements, registrations, personas, inhabitants)
        problems_condensed = {}
        for lodgement_id, part_id in itertools.product(lodgement_ids, parts.keys()):
            problems_here_rg = [p for p in problems
                                if p.lodgement_id == lodgement_id
                                and p.part_id == part_id
                                and p.camping_mat is not True]
            problems_here_cm = [p for p in problems
                                if p.lodgement_id == lodgement_id
                                and p.part_id == part_id
                                and p.camping_mat is not False]
            problems_condensed[(lodgement_id, part_id, False)] = (
                max(p.severeness for p in problems_here_rg) if problems_here_rg else 0,
                "; ".join(rs.gettext(p.description) for p in problems_here_rg),)
            problems_condensed[(lodgement_id, part_id, True)] = (
                max(p.severeness for p in problems_here_cm) if problems_here_cm else 0,
                "; ".join(rs.gettext(p.description) for p in problems_here_cm),)

        def sort_lodgement(lodgement: CdEDBObject) -> Sortkey:
            primary_sort: Sortkey
            if sortkey is None:
                primary_sort = ()
            elif sortkey.is_used_sorting():
                if sort_part_id not in parts.keys():
                    raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
                assert sort_part_id is not None
                if sortkey == LodgementsSortkeys.used_regular:
                    num = len(inhabitants[lodgement['id']][sort_part_id].regular)
                else:
                    num = len(inhabitants[lodgement['id']][sort_part_id].camping_mat)
                primary_sort = (num,)
            elif sortkey.is_total_sorting():
                lodgement_group = groups[lodgement['group_id']]
                if sortkey == LodgementsSortkeys.total_regular:
                    num = lodgement_group['regular_capacity']
                else:
                    num = lodgement_group['camping_mat_capacity']
                primary_sort = (num,)
            elif sortkey == LodgementsSortkeys.title:
                primary_sort = (lodgement["title"],)
            else:
                primary_sort = ()
            secondary_sort = EntitySorter.lodgement(lodgement)
            return primary_sort + secondary_sort

        # now sort the lodgements inside their group
        grouped_lodgements = {
            group_id: dict(keydictsort_filter(
                {
                    lodgement_id: lodgements[lodgement_id]
                    for lodgement_id in group['lodgement_ids']
                },
                sortkey=sort_lodgement, reverse=reverse,
            ))
            for group_id, group in keydictsort_filter(
                groups, EntitySorter.lodgement_group)
        }
        sorted_parts = keydictsort_filter(parts, EntitySorter.event_part)

        return self.render(rs, "lodgement/lodgements", {
            'sorted_event_parts': sorted_parts,
            'groups': groups,
            'grouped_lodgements': grouped_lodgements,
            'inhabitants': inhabitants,
            'inhabitants_per_group': inhabitants_per_group,
            'total_inhabitants': total_inhabitants,
            'total_regular_capacity': total_reg_capacity,
            'total_camping_mat_capacity': total_cm_capacity,
            'problems': problems_condensed,
            'last_sortkey': sortkey,
            'last_sort_part_id': sort_part_id,
            'last_reverse': reverse,
        })

    @access("event")
    @event_guard(check_offline=True)
    def lodgement_group_summary_form(self, rs: RequestState, event_id: int
                                     ) -> Response:
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        sorted_group_ids = [
            e["id"] for e in xsorted(groups.values(), key=EntitySorter.lodgement_group)]

        current = {
            drow_name(field_name=key, entity_id=group_id): value
            for group_id, group in groups.items()
            for key, value in group.items() if key != 'id'}
        merge_dicts(rs.values, current)

        return self.render(rs, "lodgement/lodgement_group_summary", {
            'sorted_group_ids': sorted_group_ids, 'groups': groups,
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lodgement_group_summary(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Manipulate groups of lodgements."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        spec: vtypes.TypeMapping = {'title': str}
        groups = process_dynamic_input(rs, vtypes.LodgementGroup, group_ids.keys(),
                                       spec, additional={'event_id': event_id})

        if rs.has_validation_errors():
            return self.lodgement_group_summary_form(rs, event_id)

        code = 1
        for group_id, group in groups.items():
            if group is None:
                code *= self.eventproxy.delete_lodgement_group(rs, group_id)
            elif group_id < 0:
                code *= self.eventproxy.create_lodgement_group(rs, group)
            else:
                del group['event_id']
                code *= self.eventproxy.rcw_lodgement_group(rs, group)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/lodgement_group_summary")

    @access("event")
    @event_guard()
    def show_lodgement(self, rs: RequestState, event_id: int,
                       lodgement_id: int) -> Response:
        """Display details of one lodgement."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        raw_inhabitants = self.eventproxy.get_grouped_inhabitants(
            rs, event_id, lodgement_ids=(lodgement_id,))
        inhabitants = {
            part_id: raw_inhabitants[lodgement_id][part_id].all
            for part_id in rs.ambience['event']['parts']
        }
        registrations = self.eventproxy.get_registrations(
            rs, tuple(itertools.chain.from_iterable(inhabitants.values())))
        personas = self.coreproxy.get_event_users(
            rs, [r['persona_id'] for r in registrations.values()], event_id=event_id)

        camping_mat_field_names = self._get_camping_mat_field_names(
            rs.ambience['event'])

        problems = self.check_lodgement_problems(
            rs.ambience['event'], {lodgement_id: rs.ambience['lodgement']},
            registrations, personas, raw_inhabitants)

        if not any(reg_ids for reg_ids in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        def make_inhabitants_query(part_id: int) -> Query:
            return Query(
                QueryScope.registration,
                QueryScope.registration.get_spec(event=rs.ambience['event']),
                fields_of_interest=[
                    'persona.given_names', 'persona.family_name',
                    f'part{part_id}.lodgement_id', f'part{part_id}.is_camping_mat',
                ],
                constraints=[
                    (f'part{part_id}.lodgement_id', QueryOperators.equal, lodgement_id),
                ],
                order=[
                    ('persona.family_name', True),
                    ('persona.given_names', True),
                ]
            )

        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id).keys()
        lodgement_groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        for lodge in lodgements.values():
            lodge['group_title'] = lodgement_groups.get(lodge['group_id'])
        sorted_ids = xsorted(
            lodgement_ids,
            key=lambda id_: EntitySorter.lodgement_by_group(lodgements[id_]))
        i = sorted_ids.index(lodgement_id)

        prev_lodge = lodgements[sorted_ids[i - 1]] if i > 0 else None
        next_lodge = lodgements[sorted_ids[i + 1]] if i + 1 < len(sorted_ids) else None

        return self.render(rs, "lodgement/show_lodgement", {
            'groups': groups, 'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,
            'make_inhabitants_query': make_inhabitants_query,
            'camping_mat_field_names': camping_mat_field_names,
            'prev_lodgement': prev_lodge, 'next_lodgement': next_lodge,
        })

    @access("event")
    @event_guard()
    def lodgement_wishes_graph_form(self, rs: RequestState, event_id: int
                                    ) -> Response:
        event = rs.ambience['event']
        if event['lodge_field']:
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            registrations = self.eventproxy.get_registrations(rs, registration_ids)
            personas = self.coreproxy.get_event_users(rs, tuple(
                reg['persona_id'] for reg in registrations.values()), event_id)

            _wishes, problems = detect_lodgement_wishes(
                registrations, personas, event, restrict_part_id=None)
        else:
            problems = []
        lodgement_groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        return self.render(rs, "lodgement/lodgement_wishes_graph_form",
                           {'problems': problems, 'lodgement_groups': lodgement_groups})

    @access("event")
    @event_guard()
    @REQUESTdata('all_participants', 'part_id', 'show_lodgements',
                 'show_lodgement_groups', 'show_full_assigned_edges')
    def lodgement_wishes_graph(
            self, rs: RequestState, event_id: int, all_participants: bool,
            part_id: Optional[int], show_lodgements: bool, show_lodgement_groups: bool,
            show_full_assigned_edges: bool
    ) -> Response:
        if rs.has_validation_errors():
            return self.lodgement_wishes_graph_form(rs, event_id)
        event = rs.ambience['event']

        if not event['lodge_field']:
            rs.notify('error', n_("Lodgement wishes graph is only available if "
                                  "the Field for Rooming Preferences is set in "
                                  "event configuration."))
            return self.lodgement_wishes_graph_form(rs, event_id)

        msg = n_("Clusters can only be displayed if the graph is restricted to a"
                 " specific part.")
        if show_lodgements and not part_id:
            rs.append_validation_error(("show_lodgements", ValueError(msg)))
        if show_lodgement_groups and not part_id:
            rs.append_validation_error(("show_lodgement_groups", ValueError(msg)))
        if not show_full_assigned_edges and not part_id:
            rs.append_validation_error(("show_full_assigned_edges", ValueError(
                n_("Edges between participants who are both assigned to a lodgement can"
                   " only be hidden if the graph is restricted to a specific part."))))
        if rs.has_validation_errors():
            return self.lodgement_wishes_graph_form(rs, event_id)

        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)

        wishes, _problems = detect_lodgement_wishes(
            registrations, personas, event, part_id)
        graph = create_lodgement_wishes_graph(
            rs, registrations, wishes, lodgements, lodgement_groups, event, personas,
            filter_part_id=part_id, show_all=all_participants, cluster_part_id=part_id,
            cluster_by_lodgement=show_lodgements,
            cluster_by_lodgement_group=show_lodgement_groups,
            show_full_assigned_edges=show_full_assigned_edges)
        data: bytes = graph.pipe('svg')
        return self.send_file(rs, "image/svg+xml", data=data)

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("group_id")
    def create_lodgement_form(self, rs: RequestState, event_id: int,
                              group_id: Optional[int] = None) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        if len(groups) == 1:
            group_id = unwrap(groups.keys())
        if group_id:
            rs.values['group_id'] = group_id
        return self.render(rs, "lodgement/create_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("new_group_title")
    @REQUESTdatadict(*LODGEMENT_COMMON_FIELDS)
    def create_lodgement(self, rs: RequestState, event_id: int, data: CdEDBObject,
                         new_group_title: Optional[str]) -> Response:
        """Add a new lodgement."""
        data['event_id'] = event_id
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore[misc]
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }

        # Check if a new group should be created.
        create_new_group = False
        if not data.get('group_id') and new_group_title:
            create_new_group = True
            data['group_id'] = 1  # Placeholder id for validation.

        data = check(rs, vtypes.Lodgement, data, creation=True)
        if rs.has_validation_errors():
            return self.create_lodgement_form(rs, event_id)
        assert data is not None

        # Create the new group.
        if create_new_group:
            new_group_data = {'title': new_group_title, 'event_id': event_id}
            new_group_data = check(
                rs, vtypes.LodgementGroup, new_group_data, creation=True)
            if rs.has_validation_errors() or not new_group_data:
                return self.create_lodgement_form(rs, event_id)
            data['group_id'] = self.eventproxy.create_lodgement_group(
                rs, new_group_data)

        new_id = self.eventproxy.create_lodgement(rs, data)
        rs.notify_return_code(new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event")
    @event_guard(check_offline=True)
    def change_lodgement_form(self, rs: RequestState, event_id: int,
                              lodgement_id: int) -> Response:
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        field_values = {
            f"fields.{field_name}": value
            for field_name, value in rs.ambience['lodgement']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['lodgement'], field_values)
        return self.render(rs, "lodgement/change_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*LODGEMENT_COMMON_FIELDS)
    def change_lodgement(self, rs: RequestState, event_id: int,
                         lodgement_id: int, data: CdEDBObject) -> Response:
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        data['id'] = lodgement_id
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore[misc]
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, vtypes.Lodgement, data)
        if rs.has_validation_errors():
            return self.change_lodgement_form(rs, event_id, lodgement_id)
        assert data is not None

        code = self.eventproxy.set_lodgement(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_lodgement(self, rs: RequestState, event_id: int,
                         lodgement_id: int, ack_delete: bool) -> Response:
        """Remove a lodgement."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_lodgement(rs, event_id, lodgement_id)

        lodgement_title = rs.ambience['lodgement']['title']
        pre_msg = f"Snapshot vor Löschen von Unterkunft {lodgement_title}."
        post_msg = f"Lösche Unterkunft {lodgement_title}."
        self.eventproxy.event_keeper_commit(rs, event_id, pre_msg)
        code = self.eventproxy.delete_lodgement(
            rs, lodgement_id, cascade={"inhabitants"})
        self.eventproxy.event_keeper_commit(rs, event_id, post_msg, after_change=True)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/lodgements")

    @access("event")
    @event_guard(check_offline=True)
    def manage_inhabitants_form(self, rs: RequestState, event_id: int,
                                lodgement_id: int) -> Response:
        """Render form."""
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)
        for part_id in rs.ambience['event']['parts']:
            merge_dicts(rs.values, {
                'is_camping_mat_{}_{}'.format(part_id, registration_id):
                    registrations[registration_id]['parts'][part_id][
                        'is_camping_mat']
                for registration_id in inhabitants[(lodgement_id, part_id)]
            })

        def _check_without_lodgement(registration_id: int, part_id: int) -> bool:
            """Un-inlined check for registration without lodgement."""
            part = registrations[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(part['status']).is_present()
                    and not part['lodgement_id'])

        without_lodgement = {
            part_id: xsorted(
                (
                    (registration_id, make_persona_name(
                        personas[registrations[registration_id]['persona_id']]))
                    for registration_id in registrations
                    if _check_without_lodgement(registration_id, part_id)
                ),
                key=lambda tpl: EntitySorter.persona(
                    personas[registrations[tpl[0]]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }

        # Generate data to be encoded to json and used by the
        # cdedbMultiSelect() javascript function
        def _check_not_this_lodgement(registration_id: int, part_id: int) -> bool:
            """Un-inlined check for registration with different lodgement."""
            part = registrations[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(part['status']).is_present()
                    and part['lodgement_id'] != lodgement_id)

        selectize_data = {
            part_id: xsorted(
                [{'name': (personas[registration['persona_id']]['given_names']
                           + " " + personas[registration['persona_id']]
                           ['family_name']),
                  'group_id': registration['parts'][part_id]['lodgement_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_lodgement(registration_id, part_id)],
                key=lambda x: (
                    x['group_id'] is not None,
                    EntitySorter.persona(
                        personas[registrations[x['id']]['persona_id']]))
            )
            for part_id in rs.ambience['event']['parts']
        }
        lodgement_names = self.eventproxy.list_lodgements(rs, event_id)
        other_lodgements = {
            anid: name for anid, name in lodgement_names.items() if anid != lodgement_id
        }
        return self.render(rs, "lodgement/manage_inhabitants", {
            'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants,
            'without_lodgement': without_lodgement,
            'selectize_data': selectize_data,
            'lodgement_names': lodgement_names,
            'other_lodgements': other_lodgements})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs: RequestState, event_id: int,
                           lodgement_id: int) -> Response:
        """Alter who is assigned to a lodgement.

        This tries to be a bit smart and write only changed state.
        """
        # Get all registrations and current inhabitants
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        current_inhabitants = {
            part_id: [reg_id for reg_id, registration in registrations.items()
                      if registration['parts'][part_id]['lodgement_id']
                      == lodgement_id]
            for part_id in rs.ambience['event']['parts']}
        # Parse request data
        params: vtypes.TypeMapping = {
            **{
                f"new_{part_id}": Collection[Optional[vtypes.ID]]
                for part_id in rs.ambience['event']['parts']
            },
            **{
                f"delete_{part_id}_{reg_id}": bool
                for part_id in rs.ambience['event']['parts']
                for reg_id in current_inhabitants[part_id]
            },
            **{
                f"is_camping_mat_{part_id}_{reg_id}": bool
                for part_id in rs.ambience['event']['parts']
                for reg_id in current_inhabitants[part_id]
            }
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        # Iterate all registrations to find changed ones
        reg_data = []
        change_note = f"Bewohner von {rs.ambience['lodgement']['title']} geändert."
        for reg_id, reg in registrations.items():
            new_reg: CdEDBObject = {
                'id': reg_id,
                'parts': {},
            }
            # Check if registration is new inhabitant or deleted inhabitant
            # in any part
            for part_id in rs.ambience['event']['parts']:
                new_inhabitant = (reg_id in data[f"new_{part_id}"])
                deleted_inhabitant = data.get(
                    "delete_{}_{}".format(part_id, reg_id), False)
                is_camping_mat = reg['parts'][part_id]['is_camping_mat']
                changed_inhabitant = (
                        reg_id in current_inhabitants[part_id]
                        and data.get(f"is_camping_mat_{part_id}_{reg_id}",
                                     False) != is_camping_mat)
                if new_inhabitant or deleted_inhabitant:
                    new_reg['parts'][part_id] = {
                        'lodgement_id': lodgement_id if new_inhabitant else None
                    }
                elif changed_inhabitant:
                    new_reg['parts'][part_id] = {
                        'is_camping_mat': data.get(
                            f"is_camping_mat_{part_id}_{reg_id}",
                            False)
                    }
            if new_reg['parts']:
                reg_data.append(new_reg)

        code = self.eventproxy.set_registrations(rs, reg_data, change_note)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def swap_inhabitants(self, rs: RequestState, event_id: int,
                         lodgement_id: int) -> Response:
        """Swap inhabitants of two lodgements of the same part."""
        params: vtypes.TypeMapping = {
            f"swap_with_{part_id}": Optional[vtypes.ID]  # type: ignore[misc]
            for part_id in rs.ambience['event']['parts']
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)

        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        inhabitants = self.calculate_groups(
            lodgements.keys(), rs.ambience['event'], registrations, key="lodgement_id")

        new_regs: CdEDBObjectMap = {}
        change_notes = []
        for part_id in rs.ambience['event']['parts']:
            if data[f"swap_with_{part_id}"]:
                swap_lodgement_id: int = data[f"swap_with_{part_id}"]
                current_inhabitants = inhabitants[(lodgement_id, part_id)]
                swap_inhabitants = inhabitants[(swap_lodgement_id, part_id)]
                new_reg: CdEDBObject
                for reg_id in current_inhabitants:
                    new_reg = new_regs.get(reg_id, {'id': reg_id, 'parts': dict()})
                    new_reg['parts'][part_id] = {'lodgement_id': swap_lodgement_id}
                    new_regs[reg_id] = new_reg
                for reg_id in swap_inhabitants:
                    new_reg = new_regs.get(reg_id, {'id': reg_id, 'parts': dict()})
                    new_reg['parts'][part_id] = {'lodgement_id': lodgement_id}
                    new_regs[reg_id] = new_reg
                change_notes.append(
                    f"Bewohner von {lodgements[lodgement_id]} und"
                    f" {lodgements[swap_lodgement_id]} für"
                    f" {rs.ambience['event']['parts'][part_id]['title']} getauscht")

        code = 1
        change_note = ", ".join(change_notes) + "."
        code = self.eventproxy.set_registrations(rs, new_regs.values(), change_note)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event")
    @event_guard(check_offline=True)
    def move_lodgements_form(self, rs: RequestState, event_id: int, group_id: int
                             ) -> Response:
        """Move lodgements from one group to another or delete them with the group."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgements_in_group = self.eventproxy.list_lodgements(rs, event_id, group_id)
        return self.render(rs, "lodgement/move_lodgements", {
            'groups': groups, 'lodgements_in_group': lodgements_in_group,
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("lodgement_ids", "target_group_id", "delete_group")
    def move_lodgements(self, rs: RequestState, event_id: int, group_id: int,
                        lodgement_ids: Collection[int], target_group_id: Optional[int],
                        delete_group: bool) -> Response:
        """Move lodgements from one group to another or delete them with the group."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgements_in_group = self.eventproxy.list_lodgements(rs, event_id, group_id)
        if rs.has_validation_errors():
            return self.move_lodgements_form(rs, event_id, group_id)
        if target_group_id:
            if target_group_id not in groups or target_group_id == group_id:
                rs.append_validation_error(
                    ('target_group_id', KeyError(n_("Invalid lodgement group."))))
        if not target_group_id and not delete_group:
            rs.notify("info", n_("Nothing to do."))
            return self.redirect(rs, "event/lodgements")
        if set(lodgement_ids) != set(lodgements_in_group):
            rs.notify("error", n_("Lodgements in this group changed in the meantime."))
            return self.move_lodgements_form(rs, event_id, group_id)
        if rs.has_validation_errors():
            return self.move_lodgements_form(rs, event_id, group_id)

        code = self.eventproxy.move_lodgements(
            rs, group_id, target_group_id, delete_group)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/lodgements")
