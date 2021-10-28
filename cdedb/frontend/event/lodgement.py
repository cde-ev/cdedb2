#!/usr/bin/env python3

"""The `EventLodgementMixin` subclasses the `EventBaseFrontend` and provides endpoints
for managings lodgements, lodgement groups and lodgements' inhabitants."""

import itertools
from collections import OrderedDict
from typing import Collection, Dict, List, NamedTuple, Optional, Tuple

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, EntitySorter, LodgementsSortkeys, RequestState,
    Sortkey, merge_dicts, n_, xsorted,
)
from cdedb.filter import keydictsort_filter
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, check_validation as check, drow_name,
    event_guard, process_dynamic_input, request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.frontend.event.lodgement_wishes import (
    create_lodgement_wishes_graph, detect_lodgement_wishes,
)
from cdedb.validation import LODGEMENT_COMMON_FIELDS
from cdedb.validationtypes import VALIDATOR_LOOKUP

LodgementProblem = NamedTuple(
    "LodgementProblem", [("description", str), ("lodgement_id", int),
                         ("part_id", int), ("reg_ids", Collection[int]),
                         ("severeness", int)])


class EventLodgementMxin(EventBaseFrontend):
    @staticmethod
    def check_lodgement_problems(
            event: CdEDBObject, lodgements: CdEDBObjectMap,
            registrations: CdEDBObjectMap, personas: CdEDBObjectMap,
            inhabitants: Dict[Tuple[int, int], Collection[int]]
    ) -> List[LodgementProblem]:
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        :returns: problems as five-tuples of (problem description, lodgement
          id, part id, affected registrations, severeness).
        """
        ret: List[LodgementProblem] = []

        # first some un-inlined code pieces (otherwise nesting is a bitch)
        def _mixed(group: Collection[int]) -> bool:
            """Un-inlined check whether both genders are present."""
            return any({personas[registrations[a]['persona_id']]['gender'],
                        personas[registrations[b]['persona_id']]['gender']} ==
                       {const.Genders.male, const.Genders.female}
                       for a, b in itertools.combinations(group, 2))

        def _mixing_problem(lodgement_id: int, part_id: int
                            ) -> LodgementProblem:
            """Un-inlined code to generate an entry for mixing problems."""
            return LodgementProblem(
                n_("Mixed lodgement with non-mixing participants."),
                lodgement_id, part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if not registrations[reg_id]['mixed_lodging']),
                3)

        def _camping_mat(group: Collection[int], part_id: int) -> int:
            """Un-inlined code to count the number of registrations assigned
            to a lodgement as camping_mat lodgers."""
            return sum(
                registrations[reg_id]['parts'][part_id]['is_camping_mat']
                for reg_id in group)

        def _camping_mat_problem(lodgement_id: int, part_id: int
                                 ) -> LodgementProblem:
            """Un-inlined code to generate an entry for camping_mat problems."""
            return LodgementProblem(
                n_("Too many camping mats used."), lodgement_id,
                part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if registrations[reg_id]['parts'][part_id]['is_camping_mat']),
                1)

        # now the actual work
        for lodgement_id in lodgements:
            for part_id in event['parts']:
                group = inhabitants[(lodgement_id, part_id)]
                lodgement = lodgements[lodgement_id]
                num_camping_mat = _camping_mat(group, part_id)
                if len(group) > (lodgement['regular_capacity'] +
                                 lodgement['camping_mat_capacity']):
                    ret.append(LodgementProblem(
                        n_("Overful lodgement."), lodgement_id, part_id,
                        tuple(), 2))
                elif lodgement['regular_capacity'] < (len(group) -
                                                      num_camping_mat):
                    ret.append(LodgementProblem(
                        n_("Too few camping mats used."), lodgement_id,
                        part_id, tuple(), 2))
                if num_camping_mat > lodgement['camping_mat_capacity']:
                    ret.append(_camping_mat_problem(lodgement_id, part_id))
                if _mixed(group) and any(
                        not registrations[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                complex_gender_people = tuple(
                    reg_id for reg_id in group
                    if (personas[registrations[reg_id]['persona_id']]['gender']
                        in (const.Genders.other, const.Genders.not_specified)))
                if complex_gender_people:
                    ret.append(LodgementProblem(
                        n_("Non-Binary Participant."), lodgement_id, part_id,
                        complex_gender_people, 1))
        return ret

    @access("event")
    @event_guard()
    @REQUESTdata("sort_part_id", "sortkey", "reverse")
    def lodgements(self, rs: RequestState, event_id: int,
                   sort_part_id: vtypes.ID = None, sortkey: LodgementsSortkeys = None,
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
            rs, tuple(e['persona_id'] for e in registrations.values()),
            event_id)

        # All inhabitants (regular and camping_mat) of all lodgements and
        # all parts
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id")
        regular_inhabitant_nums = {
            k: sum(1 for r in v
                   if not registrations[r]['parts'][k[1]]['is_camping_mat'])
            for k, v in inhabitants.items()}
        camping_mat_inhabitant_nums = {
            k: sum(1 for r in v
                   if registrations[r]['parts'][k[1]]['is_camping_mat'])
            for k, v in inhabitants.items()}
        problems = self.check_lodgement_problems(
            rs.ambience['event'], lodgements, registrations, personas,
            inhabitants)
        problems_condensed = {}

        # Calculate regular_inhabitant_sum and camping_mat_inhabitant_sum
        # per part
        regular_inhabitant_sum = {}
        camping_mat_inhabitant_sum = {}
        for part_id in parts:
            regular_lodgement_sum = 0
            camping_mat_lodgement_sum = 0
            for lodgement_id in lodgement_ids:
                regular_lodgement_sum += regular_inhabitant_nums[
                    (lodgement_id, part_id)]
                camping_mat_lodgement_sum += camping_mat_inhabitant_nums[
                    (lodgement_id, part_id)]
            regular_inhabitant_sum[part_id] = regular_lodgement_sum
            camping_mat_inhabitant_sum[part_id] = camping_mat_lodgement_sum

        # Calculate sum of lodgement regular and camping mat capacities
        regular_sum = 0
        camping_mat_sum = 0
        for lodgement in lodgements.values():
            regular_sum += lodgement['regular_capacity']
            camping_mat_sum += lodgement['camping_mat_capacity']

        # Calculate problems_condensed (worst problem)
        for lodgement_id, part_id in itertools.product(
                lodgement_ids, parts.keys()):
            problems_here = [p for p in problems
                             if p[1] == lodgement_id and p[2] == part_id]
            problems_condensed[(lodgement_id, part_id)] = (
                max(p[4] for p in problems_here) if problems_here else 0,
                "; ".join(rs.gettext(p[0]) for p in problems_here),)

        # Calculate groups
        grouped_lodgements = {
            group_id: {
                lodgement_id: lodgement
                for lodgement_id, lodgement
                in keydictsort_filter(lodgements, EntitySorter.lodgement)
                if lodgement['group_id'] == group_id
            }
            for group_id, group
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) +
                [(None, None)])  # type: ignore
        }

        # Calculate group_regular_inhabitants_sum,
        #           group_camping_mat_inhabitants_sum,
        #           group_regular_sum and group_camping_mat_sum
        group_regular_inhabitants_sum = {
            (group_id, part_id):
                sum(regular_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_camping_mat_inhabitants_sum = {
            (group_id, part_id):
                sum(camping_mat_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_regular_sum = {
            group_id: sum(lodgement['regular_capacity']
                          for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}
        group_camping_mat_sum = {
            group_id: sum(lodgement['camping_mat_capacity']
                          for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}

        def sort_lodgement(lodgement_tuple: Tuple[int, CdEDBObject],
                           group_id: int) -> Sortkey:
            anid, lodgement = lodgement_tuple
            lodgement_group = grouped_lodgements[group_id]
            primary_sort: Sortkey
            if sortkey is None:
                primary_sort = ()
            elif sortkey.is_used_sorting():
                if sort_part_id not in parts.keys():
                    raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
                assert sort_part_id is not None
                regular = regular_inhabitant_nums[(anid, sort_part_id)]
                camping_mat = camping_mat_inhabitant_nums[(anid, sort_part_id)]
                primary_sort = (
                    regular if sortkey == LodgementsSortkeys.used_regular
                    else camping_mat,)
            elif sortkey.is_total_sorting():
                regular = (lodgement_group[anid]['regular_capacity']
                           if anid in lodgement_group else 0)
                camping_mat = (lodgement_group[anid]['camping_mat_capacity']
                               if anid in lodgement_group else 0)
                primary_sort = (
                    regular if sortkey == LodgementsSortkeys.total_regular
                    else camping_mat,)
            elif sortkey == LodgementsSortkeys.title:
                primary_sort = (lodgement["title"],)
            else:
                primary_sort = ()
            secondary_sort = EntitySorter.lodgement(lodgement)
            return primary_sort + secondary_sort

        # now sort the lodgements inside their group
        sorted_grouped_lodgements = OrderedDict([
            (group_id, OrderedDict([
                (lodgement_id, lodgement)
                for lodgement_id, lodgement
                in xsorted(lodgements.items(), reverse=reverse,
                           key=lambda e: sort_lodgement(e, group_id))  # pylint: disable=cell-var-from-loop
                if lodgement['group_id'] == group_id
            ]))
            for group_id, group
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) +
                [(None, None)])  # type: ignore
        ])

        return self.render(rs, "lodgements", {
            'groups': groups,
            'grouped_lodgements': sorted_grouped_lodgements,
            'regular_inhabitants': regular_inhabitant_nums,
            'regular_inhabitants_sum': regular_inhabitant_sum,
            'group_regular_inhabitants_sum': group_regular_inhabitants_sum,
            'camping_mat_inhabitants': camping_mat_inhabitant_nums,
            'camping_mat_inhabitants_sum': camping_mat_inhabitant_sum,
            'group_camping_mat_inhabitants_sum':
                group_camping_mat_inhabitants_sum,
            'group_regular_sum': group_regular_sum,
            'group_camping_mat_sum': group_camping_mat_sum,
            'regular_sum': regular_sum,
            'camping_mat_sum': camping_mat_sum,
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

        return self.render(rs, "lodgement_group_summary", {
            'sorted_group_ids': sorted_group_ids
        })

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lodgement_group_summary(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Manipulate groups of lodgements."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        spec = {'title': str}
        groups = process_dynamic_input(rs, vtypes.LodgementGroup, group_ids.keys(),
                                       spec, additional={'event_id': event_id})

        if rs.has_validation_errors():
            return self.lodgement_group_summary_form(rs, event_id)

        code = 1
        for group_id, group in groups.items():
            if group is None:
                code *= self.eventproxy.delete_lodgement_group(
                    rs, group_id, cascade=("lodgements",))
            elif group_id < 0:
                code *= self.eventproxy.create_lodgement_group(rs, group)
            else:
                del group['event_id']
                code *= self.eventproxy.rcw_lodgement_group(rs, group)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/lodgement_group_summary")

    @access("event")
    @event_guard()
    def show_lodgement(self, rs: RequestState, event_id: int,
                       lodgement_id: int) -> Response:
        """Display details of one lodgement."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in (self.eventproxy.get_registrations(rs, registration_ids)
                         .items())
            if any(part['lodgement_id'] == lodgement_id
                   for part in v['parts'].values())}
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()),
            event_id)
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)

        problems = self.check_lodgement_problems(
            rs.ambience['event'], {lodgement_id: rs.ambience['lodgement']},
            registrations, personas, inhabitants)

        if not any(reg_ids for reg_ids in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        return self.render(rs, "show_lodgement", {
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,
            'groups': groups,
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
        return self.render(rs, "lodgement_wishes_graph_form",
                           {'problems': problems})

    @access("event")
    @event_guard()
    @REQUESTdata('all_participants', 'part_id', 'show_lodgements')
    def lodgement_wishes_graph(self, rs: RequestState, event_id: int,
                               all_participants: bool, part_id: Optional[int],
                               show_lodgements: bool) -> Response:
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/lodgement_wishes_graph_form')
        event = rs.ambience['event']

        if not event['lodge_field']:
            rs.notify('error', n_("Lodgement wishes graph is only available if "
                                  "the Field for Rooming Preferences is set in "
                                  "event configuration."))
            return self.redirect(rs, 'event/lodgement_wishes_graph_form')
        if show_lodgements and not part_id:
            rs.notify('error', n_("Lodgement clusters can only be displayed if "
                                  "the graph is restricted to a specific "
                                  "part."))
            return self.redirect(rs, 'event/lodgement_wishes_graph_form')

        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)

        wishes, _problems = detect_lodgement_wishes(
            registrations, personas, event, part_id)
        graph = create_lodgement_wishes_graph(
            rs, registrations, wishes, lodgements, event, personas, part_id,
            all_participants, part_id if show_lodgements else None)
        data: bytes = graph.pipe('svg')
        return self.send_file(rs, "image/svg+xml", data=data)

    @access("event")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs: RequestState, event_id: int
                              ) -> Response:
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        return self.render(rs, "create_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*LODGEMENT_COMMON_FIELDS)
    def create_lodgement(self, rs: RequestState, event_id: int,
                         data: CdEDBObject) -> Response:
        """Add a new lodgement."""
        data['event_id'] = event_id
        field_params: vtypes.TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]  # noqa: F821
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, vtypes.Lodgement, data, creation=True)
        if rs.has_validation_errors():
            return self.create_lodgement_form(rs, event_id)
        assert data is not None

        new_id = self.eventproxy.create_lodgement(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event")
    @event_guard(check_offline=True)
    def change_lodgement_form(self, rs: RequestState, event_id: int,
                              lodgement_id: int) -> Response:
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['lodgement']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['lodgement'], field_values)
        return self.render(rs, "change_lodgement", {'groups': groups})

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
            f"fields.{field['field_name']}": Optional[  # type: ignore
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
        self.notify_return_code(rs, code)
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
        code = self.eventproxy.delete_lodgement(
            rs, lodgement_id, cascade={"inhabitants"})
        self.notify_return_code(rs, code)
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
                (registration_id
                 for registration_id in registrations
                 if _check_without_lodgement(registration_id, part_id)),
                key=lambda anid: EntitySorter.persona(
                    personas[registrations[anid]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }

        # Generate data to be encoded to json and used by the
        # cdedbSearchParticipant() javascript function
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
                  'current': registration['parts'][part_id]['lodgement_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_lodgement(registration_id, part_id)],
                key=lambda x: (
                    x['current'] is not None,
                    EntitySorter.persona(
                        personas[registrations[x['id']]['persona_id']]))
            )
            for part_id in rs.ambience['event']['parts']
        }
        lodgement_names = self.eventproxy.list_lodgements(rs, event_id)
        other_lodgements = {
            anid: name for anid, name in lodgement_names.items() if anid != lodgement_id
        }
        return self.render(rs, "manage_inhabitants", {
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
        code = 1
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
                code *= self.eventproxy.set_registration(rs, new_reg, change_note)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def swap_inhabitants(self, rs: RequestState, event_id: int,
                         lodgement_id: int) -> Response:
        """Swap inhabitants of two lodgements of the same part."""
        params: vtypes.TypeMapping = {
            f"swap_with_{part_id}": Optional[vtypes.ID]  # type: ignore
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
        for new_reg in new_regs.values():
            code *= self.eventproxy.set_registration(rs, new_reg, change_note)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")
