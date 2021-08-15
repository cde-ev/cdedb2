"""
Uninlined code of the event/lodgement_wishes_graph frontend endpoint

It is also used by event/download_lodgement_puzzle for creating the reverse
wishes heuristics.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Set, Dict, Optional, Tuple

import graphviz  # type: ignore

from cdedb.common import CdEDBObject, RequestState, CdEDBObjectMap, Notification, \
    inverse_diacritic_patterns, n_
from cdedb.database.constants import Genders, RegistrationPartStati
from cdedb.frontend.common import cdedburl, make_persona_name


@dataclass
class LodgementWish:
    """Representation of a detected edge of the lodgement wishes graph

    :ivar wishing: registration id of the wishing participant
    :ivar wished: registration id of the wished participant
    :ivar present_together: if True, the two participants will be present (i.e.
        Status is Pariticipant or Guest) together at at least one relevant part
        of the event. Otherwise they have only common event parts when
        considering the waitlist.
    :ivar bidirectional: If True, this edge should be considered as two
        symmetric edges, i.e. both participants wished each other mutually.
    :ivar negated: If True, the edge is an anti-wish, i.e. the wishing person
        wished to be *not* assigned to the same lodgement as the wished person.
    """
    wishing: int
    wished: int
    present_together: bool
    bidirectional: bool = False
    negated: bool = False


def detect_lodgement_wishes(registrations: CdEDBObjectMap,
                            personas: CdEDBObjectMap,
                            event: CdEDBObject,
                            restrict_part_id: Optional[int]) \
        -> Tuple[List[LodgementWish], List[Notification]]:
    """ Detect lodgement wish graph edges from all registrations' raw rooming
    preferences text.

    This function searches the rooming preferences field of all registrations
    for the names, email addresses and CdEDB ids of all other registrations and
    returns the detected concrete wishes as list of :class:`LodgementWish`
    objects. Bidirectional wishes are merged into one `LodgementWish` to
    simplify drawing a graph from the wishes.

    Only wishes that are allowed according to the gender mixing preferences of
    the participants are considered. Additionally, wishes between participants
    who will not participate at the same event part or are at least placed on
    the waitlist for a common event part are skipped. If a wish can only be
    fulfilled when considering the waitlist, the `present_together` flag of the
    respective `LodgementWish` object is set to false. Fully suppressed edges
    as well as ambiguous wishes are reported as problem notification.

    The wishes can optionally be restricted to a single event part. In this case
    (i.e. `restrict_part_id` is not None), only presence and waitlist of this
    specific part are considered when evaluating if a wish is applicable and if
    the participants are present together.

    :param registrations: All registrations of the event as returned by
        :meth:`cdedb.backend.event.EventBackend.get_registrations`
    :param personas: All personas referenced by any of the registrations.
        Required for checking genders.
    :param event: The event data as returned by
        :meth:`cdedb.backend.event.EventBackend.get_event`
    :param restrict_part_id: A part id of the event to filter wishes by presence
        and waitlist at/of this event part or None to consider all event parts.
    :return: The list of detected wish edges for the lodgement wishes graph and
        a list of localizable problem notification messages.
    """
    # Create a list of regex patterns, referencing the other personas, to search
    lookup_map: List[Tuple[re.Pattern[str], int]] = [
        (make_identifying_regex(personas[registration['persona_id']]),
         registration_id)
        for registration_id, registration in registrations.items()
    ]
    wish_field_name = event['fields'][event['lodge_field']]['field_name']
    wishes: Dict[Tuple[int, int], LodgementWish] = {}
    problems: List[Notification] = []
    # For each registration, analyze wishes
    for registration_id, registration in registrations.items():
        # Skip registrations with emtpy wishes field
        if not registration['fields'].get(wish_field_name):
            continue
        match_positions: List[Tuple[Tuple[int, int], int]] = []
        # Check each of the regex patterns against the wishes field
        for pattern, other_registration_id in lookup_map:
            # Self-wishes are not allowed
            if other_registration_id == registration_id:
                continue

            wishes_raw = registration['fields'].get(wish_field_name, '')
            match = pattern.search(wishes_raw)
            if match:
                other_registration = registrations[other_registration_id]

                # Report ambiguous matches
                ambiguous_match_ids = [
                    reg_id
                    for other_span, reg_id in match_positions
                    if (match.start() < other_span[1]
                        and other_span[0] < match.end())
                ]
                if ambiguous_match_ids:
                    problems.append((
                        'warning',
                        n_("Wish \"%(wish_text)s\" of %(from_name)s is "
                           "ambiguous: It may refer to %(other_name)s as well "
                           "as %(more_names)s."),
                        {'wish_text': match.group(),
                         'from_name': make_persona_name(
                             personas[registration['persona_id']]),
                         'other_name': make_persona_name(
                             personas[other_registration['persona_id']]),
                         'more_names': ", ".join(
                             make_persona_name(personas[registrations[reg_id]
                                                            ['persona_id']])
                             for reg_id in ambiguous_match_ids)}))
                match_positions.append((match.span(), registration_id))

                # TODO detect negated edges
                # Check if wish graph edge is already present in the reverse
                # direction
                reverse_edge = wishes.get((other_registration_id,
                                           registration_id))
                if reverse_edge:
                    reverse_edge.bidirectional = True
                else:
                    # if not, create the new wish object
                    # but first check, if the wish is allowed (considering
                    # genders) and
                    if not combination_allowed(registration, other_registration,
                                               personas):
                        problems.append((
                            'info',
                            n_("Suppressing unpermitted wish edge from "
                               "%(from_name)s to %(to_name)s."),
                            {'from_name': make_persona_name(
                                personas[registration['persona_id']]),
                             'to_name': make_persona_name(
                                personas[other_registration['persona_id']])}))
                        continue

                    # Skip whishes of people that don't (potentially) meet at
                    # the event
                    common_active_parts = (
                        parts_with_status(registration, ACTIVE_STATI)
                        & parts_with_status(other_registration, ACTIVE_STATI))
                    if not common_active_parts or (
                            restrict_part_id
                            and restrict_part_id not in common_active_parts):
                        problems.append((
                            'info',
                            n_("Suppressing wish edge from %(from_name)s to "
                               "%(to_name)s since they will not be present "
                               "together (even when considering the "
                               "waitlist)."),
                            {'from_name': make_persona_name(
                                personas[registration['persona_id']]),
                             'to_name': make_persona_name(
                                personas[other_registration['persona_id']])}))
                        continue

                    common_presence_parts = (
                        parts_with_status(registration, PRESENT_STATI)
                        & parts_with_status(other_registration, PRESENT_STATI))
                    wishes[(registration_id, other_registration_id)] = \
                        LodgementWish(
                            registration_id,
                            other_registration_id,
                            (bool(common_presence_parts)
                             if restrict_part_id is None
                             else restrict_part_id in common_presence_parts),
                            )

    return list(wishes.values()), problems


def make_identifying_regex(persona: CdEDBObject) -> re.Pattern[str]:
    """
    Create a Regex for finding different references to the given persona in
    other participant's rooming preferences text.
    """
    patterns = [
        inverse_diacritic_patterns(re.escape(f"{given_name} {persona['family_name']}"))
        for given_name in persona['given_names'].split()
    ]
    patterns.append(inverse_diacritic_patterns(re.escape(
        f"{persona['display_name']} {persona['family_name']}")))
    patterns.append(re.escape(f"DB-{persona['id']}"))
    patterns.append(re.escape(persona['username']))
    logging.getLogger("cdedb.frontend.event").warning("%s", patterns)
    return re.compile('|'.join(patterns))


PRESENT_STATI = {status for status in RegistrationPartStati
                 if status.is_present()}
ACTIVE_STATI = PRESENT_STATI | {RegistrationPartStati.waitlist}


def parts_with_status(registration: CdEDBObject,
                      status: Set[RegistrationPartStati]) -> Set[int]:
    """ Return a set of event part ids in which the given registration/
    participant has one of the given stati"""
    return {
        part_id
        for part_id, part in registration['parts'].items()
        if part['status'] in status
    }


def combination_allowed(registration1: CdEDBObject, registration2: CdEDBObject,
                        personas: CdEDBObjectMap) -> bool:
    """ Check if two participants are allowed to be assigned to the same
    lodgement based on their gender and gender preferences."""
    # TODO special rules for children <= 12 years
    return (gender_equality(personas[registration1['persona_id']]['gender'],
                            personas[registration2['persona_id']]['gender'])
            or (registration1['mixed_lodging']
                and registration2['mixed_lodging']))


def gender_equality(first: Genders, second: Genders) -> bool:
    """
    Partial equality relation for Genders: For simplicity, we consider
    `not_specified` and `other` to be equivalent to any Gender.
    """
    return (first == second
            or first in (Genders.not_specified, Genders.other)
            or second in (Genders.not_specified, Genders.other))


def create_lodgement_wishes_graph(
        rs: RequestState,
        registrations: CdEDBObjectMap, wishes: List[LodgementWish],
        lodgements: CdEDBObjectMap, event: CdEDBObject,
        personas: CdEDBObjectMap,
        filter_part_id: Optional[int], show_all: bool,
        cluster_by_lodgement_in_part: Optional[int]) -> graphviz.Digraph:
    """
    Plot the Lodgement Wishes Graph of the given event.

    :param registrations: All registrations of the event as returned by
        :meth:`cdedb.backend.event.EventBackend.get_registrations`
    :param wishes: The detected wish edges, as returned by
        :func:`detect_lodgement_wishes`
    :param lodgements: The lodgements of the event. Required for drawing the
        assigned lodgements as subgraphs when required.
    :param event: The event data as returned by
        :meth:`cdedb.backend.event.EventBackend.get_event`
    :param personas: All personas referenced by any of the registrations.
        Required for checking genders.
    :param filter_part_id: An event part id or None. If a part id is given,
        The displayed participants will be filtered by presence and waitlist
        at/of this event part. I.e. participants on the waitlist of this part
        will only be drawn with a dashed outline, independently from their
        presence at other event parts. Participants who only registered for
        other parts will not be shown at all.
    :param show_all: If false, only participants who are referenced by a wish
        edge, i.e. wished another participants ore have been wished (in the
        relevant part).
    :param cluster_by_lodgement_in_part: An event part id or None. If a part id
        is given, participants are clustered into subgraphs based on their
        assigned lodgment in that event part.
    :return: The fully constructed by not-yet rendered graph as a graphviz
        Digraph object. The graph can be rendered and layouted by calling
        `.pipe()` on the graph object which will run the graphviz program as a
        subprocess and return the resulting graphic file.
    """
    graph = graphviz.Digraph(
        engine=('fdp' if cluster_by_lodgement_in_part else 'neato'),
        graph_attr={'overlap': "false", 'splines': 'line', 'maxiter': "8000",
                    'sep': "+8", 'tooltip': " "},
        node_attr={'fontname': "sans-serif", 'style': "filled"})
    # Only the 'fdp' layout algorithm supports subgraphs, but 'neato' gives
    # slightly better layout results. Thus, we select the layout algorithm
    # dynamically based on the `cluster_by_lodgement_in_part` parameter.

    # Gather wishing and wished paticipants (required later if not show_all)
    referenced_registraion_ids: Set[int] = set()
    for wish in wishes:
        referenced_registraion_ids.add(wish.wished)
        referenced_registraion_ids.add(wish.wishing)

    # If clustering is enabled, create new graphs as lodgement clusters
    lodgement_clusters: Dict[int, graphviz.Digraph] = {}
    if cluster_by_lodgement_in_part:
        for lodgement_id, lodgement in lodgements.items():
            lodgement_clusters[lodgement_id] = graphviz.Digraph(
                name=f'cluster_{lodgement_id}',
                graph_attr={'label': lodgement['title'],
                            'URL': cdedburl(rs, 'event/show_lodgement',
                                            {'lodgement_id': lodgement_id})})

    # Add registrations as nodes to graph (or correct lodgement cluster)
    for registration_id, registration in registrations.items():
        # Only consider wishing or wished participants (unless show_all==True)
        if registration_id not in referenced_registraion_ids and not show_all:
            continue
        all_active_parts = parts_with_status(registration, ACTIVE_STATI)
        present_parts = parts_with_status(registration, PRESENT_STATI)
        # Only consider (potential) participants of selected part
        if (not all_active_parts
                or filter_part_id and filter_part_id not in all_active_parts):
            # This check is actually redundant as long as show_all==False,
            # since analyze_wishes() also considers the
            # part_id in edge.waitlist_together.
            continue
        # Select correct subgraph
        subgraph = graph
        if cluster_by_lodgement_in_part:
            lodgement_id = registration['parts']\
                .get(cluster_by_lodgement_in_part, {})\
                .get('lodgement_id')
            if lodgement_id:
                subgraph = lodgement_clusters[lodgement_id]
        # Create node
        is_present = (
            filter_part_id in present_parts if filter_part_id
            else bool(present_parts))
        wish_field_name = event['fields'][event['lodge_field']]['field_name']
        subgraph.node(
            str(registration['id']),
            make_node_label(registration, personas, event),
            tooltip=make_node_tooltip(rs, registration, personas, event),
            fillcolor=make_node_color(registration, personas, event),
            color=("black" if registration['fields'].get(wish_field_name)
                   else make_node_color(registration, personas, event)),
            style='filled' if is_present else 'dashed',
            penwidth="1" if is_present else "4",
            URL=cdedburl(rs, 'event/show_registration',
                         {'registration_id': registration_id}))

    # Add lodgement clusters as subgraphs
    for lodgement_cluster in lodgement_clusters.values():
        graph.subgraph(lodgement_cluster)

    # Add wishes as edges
    for wish in wishes:
        graph.edge(str(wish.wishing), str(wish.wished),
                   style='solid' if wish.present_together else 'dashed',
                   dir='both' if wish.bidirectional else 'forward',
                   weight=("1" if not wish.present_together or wish.negated
                           else ("9" if wish.bidirectional else "3")),
                   penwidth="1.5" if wish.bidirectional else "0.5",
                   tooltip=make_edge_tooltip(wish, registrations, personas),
                   color="black" if wish.present_together else "grey")

    return graph


def make_node_label(registration: CdEDBObject, personas: CdEDBObjectMap,
                    event: CdEDBObject) -> str:
    presence_parts = parts_with_status(registration, PRESENT_STATI)
    parts = ("\n({})".format(
                 ', '.join(event['parts'][p]['shortname']
                           for p in presence_parts))
             if len(event['parts']) > 1 and presence_parts
             else "")
    return make_persona_name(personas[registration['persona_id']]) + parts


def make_node_tooltip(rs: RequestState, registration: CdEDBObject,
                      personas: CdEDBObjectMap, event: CdEDBObject) -> str:
    parts = ""
    if len(event['parts']) > 1:
        parts = "\n"
        present_parts = parts_with_status(registration, PRESENT_STATI)
        parts += ', '.join(event['parts'][p]['title']
                           for p in present_parts)
        waitlist_parts = parts_with_status(registration,
                                           {RegistrationPartStati.waitlist})
        if waitlist_parts:
            if present_parts:
                parts += "  |  "
            parts += (rs.gettext("Waitlist: ")
                      + ', '.join(event['parts'][p]['title']
                                  for p in waitlist_parts))
    persona = personas[registration['persona_id']]
    return "{name}\n{email}{parts}\n\n{wishes}".format(
        name=make_persona_name(persona, given_and_display_names=True),
        email=persona['username'],
        parts=parts,
        wishes=registration['fields'].get(
            event['fields'][event['lodge_field']]['field_name'], ""),
    )


def make_edge_tooltip(edge: LodgementWish, registrations: CdEDBObjectMap,
                    personas: CdEDBObjectMap) -> str:
    return "{name1} {sign} {name2}".format(
        name1=make_persona_name(
            personas[registrations[edge.wishing]['persona_id']]),
        name2=make_persona_name(
            personas[registrations[edge.wished]['persona_id']]),
        sign="↔" if edge.bidirectional else "→"
    )


def make_node_color(registration: CdEDBObject, personas: CdEDBObjectMap,
                    event: CdEDBObject) -> str:
    age = get_age(personas[registration['persona_id']], event)
    if age <= 14.0:
        return "#ff87a0"
    elif age <= 16.0:
        return "#ff9a87"
    elif age <= 17.9726:
        return "#ffca87"
    elif age <= 18.0:
        return "#fdf36d"
    elif age <= 20.0:
        return "#bbf78c"
    elif age <= 22.0:
        return "#87ff8c"
    elif age <= 24.0:
        return "#87ffcf"
    elif age <= 28.0:
        return "#87f6ff"
    else:
        return "#87d0ff"


def get_age(persona: CdEDBObject, event: CdEDBObject) -> float:
    return float((event['begin'] - persona['birthday']).days) / 365
