#!/usr/bin/env python3

"""
The `EventQueryMixin` subclasses the `EventBaseFrontend` and provides endpoints for
querying registrations, courses and lodgements.
"""

import collections
import copy
import datetime
import functools
import pprint
from typing import Callable, Collection, Dict, List, Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    AgeClasses, CdEDBObject, EntitySorter, RequestState, deduct_years,
    determine_age_class, n_, unwrap, xsorted,
)
from cdedb.frontend.common import (
    REQUESTdata, access, check_validation as check, event_guard,
    inspect_validation as inspect, periodic,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.query import (
    Query, QueryConstraint, QueryOperators, QueryOrder, QueryScope,
    make_course_query_aux, make_lodgement_query_aux, make_registration_query_aux,
)


class EventQueryMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def stats(self, rs: RequestState, event_id: int) -> Response:
        """Present an overview of the basic stats."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        stati = const.RegistrationPartStati
        get_age = lambda u, p: determine_age_class(
            u['birthday'],
            rs.ambience['event']['parts'][p['part_id']]['part_begin'])

        # Tests for participant/registration statistics.
        # `e` is the event, `r` is a registration, `p` is a registration_part.
        tests1 = collections.OrderedDict((
            ('pending', (lambda e, r, p: (
                    p['status'] == stati.applied))),
            (' payed', (lambda e, r, p: (
                    p['status'] == stati.applied
                    and r['payment']))),
            ('participant', (lambda e, r, p: (
                    p['status'] == stati.participant))),
            (' all minors', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p).is_minor())))),
            (' u16', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p)
                         == AgeClasses.u16)))),
            (' u14', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p)
                         == AgeClasses.u14)))),
            (' checked in', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and r['checkin']))),
            (' not checked in', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and not r['checkin']))),
            (' orgas', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and r['persona_id'] in e['orgas']))),
            ('waitlist', (lambda e, r, p: (
                    p['status'] == stati.waitlist))),
            ('guest', (lambda e, r, p: (
                    p['status'] == stati.guest))),
            ('total involved', (lambda e, r, p: (
                stati(p['status']).is_involved()))),
            (' not payed', (lambda e, r, p: (
                    stati(p['status']).is_involved()
                    and not r['payment']))),
            (' no parental agreement', (lambda e, r, p: (
                    stati(p['status']).is_involved()
                    and get_age(personas[r['persona_id']], p).is_minor()
                    and not r['parental_agreement']))),
            ('no lodgement', (lambda e, r, p: (
                    stati(p['status']).is_present()
                    and not p['lodgement_id']))),
            ('cancelled', (lambda e, r, p: (
                    p['status'] == stati.cancelled))),
            ('rejected', (lambda e, r, p: (
                    p['status'] == stati.rejected))),
            ('total', (lambda e, r, p: (
                    p['status'] != stati.not_applied))),
        ))
        per_part_statistics: Dict[str, Dict[int, int]] = collections.OrderedDict()
        for key, test1 in tests1.items():
            per_part_statistics[key] = {
                part_id: sum(
                    1 for r in registrations.values()
                    if test1(rs.ambience['event'], r, r['parts'][part_id]))
                for part_id in rs.ambience['event']['parts']}

        # Test for course statistics
        # `c` is a course, `t` is a track.
        tests2 = collections.OrderedDict((
            ('courses', lambda c, t: (
                    t in c['segments'])),
            ('cancelled courses', lambda c, t: (
                    t in c['segments']
                    and t not in c['active_segments'])),
        ))

        # Tests for course attendee statistics
        # `e` is the event, `r` is the registration, `p` is a event_part,
        # `t` is a track.
        tests3 = collections.OrderedDict((
            ('all instructors', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_instructor']))),
            ('instructors', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_id']
                    and t['course_id'] == t['course_instructor']))),
            ('attendees', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_id']
                    and t['course_id'] != t['course_instructor']))),
            ('no course', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and not t['course_id']
                    and r['persona_id'] not in e['orgas']))),))
        per_track_statistics: Dict[str, Dict[int, Optional[int]]]
        per_track_statistics = collections.OrderedDict()
        regs_in_choice_x: Dict[str, Dict[int, List[int]]] = collections.OrderedDict()
        if tracks:
            # Additional dynamic tests for course attendee statistics
            for i in range(max(t['num_choices'] for t in tracks.values())):
                key = rs.gettext('In {}. Choice').format(i + 1)
                checker = (
                    functools.partial(
                        lambda p, t, j: (
                            p['status'] == stati.participant
                            and t['course_id']
                            and len(t['choices']) > j
                            and (t['choices'][j] == t['course_id'])),
                        j=i))
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if checker(r['parts'][tracks[track_id]['part_id']],
                                   r['tracks'][track_id]))
                    if i < tracks[track_id]['num_choices'] else None
                    for track_id in tracks
                }

                # the ids are used later on for the query page
                regs_in_choice_x[key] = {
                    track_id: [
                        r['id'] for r in registrations.values()
                        if checker(r['parts'][tracks[track_id]['part_id']],
                                   r['tracks'][track_id])
                    ]
                    for track_id in tracks
                }

            for key, test2 in tests2.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for c in courses.values()
                        if test2(c, track_id))
                    for track_id in tracks}
            for key, test3 in tests3.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if test3(rs.ambience['event'], r,
                                r['parts'][tracks[track_id]['part_id']],
                                r['tracks'][track_id]))
                    for track_id in tracks}

        # The base query object to use for links to event/registration_query
        persona_order = ("persona.family_name", True), ("persona.given_names", True)
        base_registration_query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"],
            [],
            persona_order,
        )
        base_course_query = Query(
            QueryScope.event_course,
            QueryScope.event_course.get_spec(event=rs.ambience['event']),
            ["course.course_id"],
            [],
            (("course.nr", True),)
        )
        # Some reusable query filter definitions
        involved_filter = lambda p: (
            'part{}.status'.format(p['id']),
            QueryOperators.oneof,
            [x.value for x in stati if x.is_involved()],
        )
        participant_filter = lambda p: (
            'part{}.status'.format(p['id']),
            QueryOperators.equal,
            stati.participant.value,
        )
        QueryFilterGetter = Callable[
            [CdEDBObject, CdEDBObject, CdEDBObject], Collection[QueryConstraint]]
        # Query filters for all the registration statistics defined and calculated above
        # They are customized and inserted into the query on the fly by get_query().
        # `e` is the event, `p` is the event_part, `t` is the track.
        registration_query_filters: Dict[str, QueryFilterGetter] = {
            'pending': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.applied.value),),
            ' payed': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.applied.value),
                ("reg.payment", QueryOperators.nonempty, None),),
            'participant': lambda e, p, t: (participant_filter(p),),
            ' all minors': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 (deduct_years(p['part_begin'], 18)))),
            ' u18': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.between,
                 (deduct_years(p['part_begin'], 18)
                    + datetime.timedelta(days=1),
                  deduct_years(p['part_begin'], 16)),),),
            ' u16': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.between,
                 (deduct_years(p['part_begin'], 16)
                    + datetime.timedelta(days=1),
                  deduct_years(p['part_begin'], 14)),),),
            ' u14': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(p['part_begin'], 14)),),
            ' checked in': lambda e, p, t: (
                participant_filter(p),
                ("reg.checkin", QueryOperators.nonempty, None),),
            ' not checked in': lambda e, p, t: (
                participant_filter(p),
                ("reg.checkin", QueryOperators.empty, None),),
            ' orgas': lambda e, p, t: (
                participant_filter(p),
                ('persona.id', QueryOperators.oneof,
                 rs.ambience['event']['orgas']),),
            'waitlist': lambda e, p, t: (
                involved_filter(p),
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.waitlist.value),),
            'guest': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.guest.value),),
            'total involved': lambda e, p, t: (involved_filter(p),),
            ' not payed': lambda e, p, t: (
                involved_filter(p),
                ("reg.payment", QueryOperators.empty, None),),
            ' no parental agreement': lambda e, p, t: (
                involved_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(p['part_begin'], 18)),
                ("reg.parental_agreement", QueryOperators.equal, False),),
            'no lodgement': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.oneof,
                 [x.value for x in stati if x.is_present()]),
                ('lodgement{}.id'.format(p['id']),
                 QueryOperators.empty, None)),
            'cancelled': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.cancelled.value),),
            'rejected': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.rejected.value),),
            'total': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.unequal,
                 stati.not_applied.value),),

            'all instructors': lambda e, p, t: (
                participant_filter(p),
                ('course_instructor{}.id'.format(t['id']),
                 QueryOperators.nonempty, None),),
            'instructors': lambda e, p, t: (
                participant_filter(p),
                ('track{}.is_course_instructor'.format(t['id']),
                 QueryOperators.equal, True),),
            'attendees': lambda e, p, t: (
                participant_filter(p),
                (f'course{t["id"]}.id', QueryOperators.nonempty, None),
                (f'track{t["id"]}.is_course_instructor',
                 QueryOperators.equalornull, False),),
            'no course': lambda e, p, t: (
                participant_filter(p),
                ('course{}.id'.format(t['id']),
                 QueryOperators.empty, None),
                ('persona.id', QueryOperators.otherthan,
                 rs.ambience['event']['orgas']),)
        }
        for name, track_regs in regs_in_choice_x.items():
            registration_query_filters[name] = functools.partial(
                lambda e, p, t, t_r: (
                    ("reg.id", QueryOperators.oneof, t_r[t['id']]),
                ), t_r=track_regs
            )
        # Query filters for all the course statistics defined and calculated above.
        # They are customized and inserted into the query on the fly by get_query().
        # `e` is the event, `p` is the event_part, `t` is the track.
        course_query_filters: Dict[str, QueryFilterGetter] = {
            'courses': lambda e, p, t: (
                (f'track{t["id"]}.is_offered', QueryOperators.equal, True),),
            'cancelled courses': lambda e, p, t: (
                (f'track{t["id"]}.is_offered', QueryOperators.equal, True),
                (f'track{t["id"]}.takes_place', QueryOperators.equal, False),),
        }

        query_additional_fields: Dict[str, Collection[str]] = {
            ' payed': ('reg.payment',),
            ' all minors': ('persona.birthday',),
            ' u18': ('persona.birthday',),
            ' u16': ('persona.birthday',),
            ' u14': ('persona.birthday',),
            ' checked in': ('reg.checkin',),
            'waitlist': ('reg.payment', 'ctime.creation_time',),
            'total involved': ('part{part}.status',),
            ' not payed': ('part{part}.status',),
            ' no parental agreement': ('part{part}.status',),
            'no lodgement': ('part{part}.status',),
            'cancelled': ('reg.amount_paid',),
            'rejected': ('reg.amount_paid',),
            'total': ('part{part}.status',),

            'all instructors': ('track{track}.course_id',
                                'track{track}.course_instructor',),
            'instructors': ('track{track}.course_instructor',),
            'attendees': ('track{track}.course_id',),
            'courses': ('course.instructors',),
            'cancelled courses': ('course.instructors',),
        }
        for name, track_regs in regs_in_choice_x.items():
            query_additional_fields[name] = ('track{track}.course_id',)

        def waitlist_query_order(
            e: CdEDBObject, p: CdEDBObject, t: CdEDBObject
        ) -> List[QueryOrder]:
            order = [("reg.payment", True), ("ctime.creation_time", True)]
            if p["waitlist_field"]:
                field_name = e["fields"][p["waitlist_field"]]["field_name"]
                waitlist_field_position = (f'reg_fields.xfield_{field_name}', True)
                order.insert(0, waitlist_field_position)
            return order

        # overwrites the default query order
        QueryOrderGetter = Callable[
            [CdEDBObject, CdEDBObject, CdEDBObject], List[QueryOrder]]
        registration_query_order: Dict[str, QueryOrderGetter] = {
            'waitlist': waitlist_query_order,
            'all instructors': lambda e, p, t: (
                [(f"track{t['id']}.course_instructor", True), *persona_order]),
            'instructors': lambda e, p, t: (
                [(f"track{t['id']}.course_instructor", True), *persona_order]),
            'attendees': lambda e, p, t: (
                [(f"course{t['id']}.nr", True), *persona_order]),
        }
        for name, track_regs in regs_in_choice_x.items():
            registration_query_order[name] = functools.partial(
                lambda e, p, t, t_r: (
                    [(f"course{t['id']}.nr", True), *persona_order]
                ), t_r=track_regs
            )

        def get_query(category: str, part_id: int, track_id: int = None
                      ) -> Optional[Query]:
            if category in registration_query_filters:
                q = copy.deepcopy(base_registration_query)
                filters = registration_query_filters
            elif category in course_query_filters:
                q = copy.deepcopy(base_course_query)
                filters = course_query_filters
            else:
                return None
            e = rs.ambience['event']
            p = e['parts'][part_id]
            t = e['tracks'][track_id] if track_id else None
            for c in filters[category](e, p, t):
                q.constraints.append(c)
            if category in query_additional_fields:
                for f in query_additional_fields[category]:
                    q.fields_of_interest.append(f.format(track=track_id, part=part_id))
            if category in registration_query_order:
                q.order = registration_query_order[category](e, p, t)
            return q

        def get_query_page(category: str) -> Optional[str]:
            if category in registration_query_filters:
                return "event/registration_query"
            elif category in course_query_filters:
                return "event/course_query"
            return None

        return self.render(rs, "stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_track_statistics': per_track_statistics,
            'get_query': get_query, 'get_query_page': get_query_page})

    make_registration_query_aux = staticmethod(make_registration_query_aux)

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def registration_query(self, rs: RequestState, event_id: int,
                           download: Optional[str], is_search: bool,
                           ) -> Response:
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        scope = QueryScope.registration
        spec = scope.get_spec(event=rs.ambience["event"])
        # mangle the input, so we can prefill the form
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)
        choices, titles = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements, lodgement_groups,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = self.conf["DEFAULT_QUERIES_REGISTRATION"](
            rs.gettext, rs.ambience['event'], spec)
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "registration_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "registration/registration_query", params)

    @access("event", modi={"POST"}, anti_csrf_token_name="store_query")
    @event_guard()
    @REQUESTdata("query_name", "query_scope")
    def store_event_query(self, rs: RequestState, event_id: int, query_name: str,
                          query_scope: QueryScope) -> Response:
        """Store an event query."""
        if not query_scope or not query_scope.get_target():
            rs.ignore_validation_errors()
            return self.redirect(rs, "event/show_event")
        if rs.has_validation_errors() or not query_name:
            rs.notify("error", n_("Invalid query name."))

        spec = query_scope.get_spec(event=rs.ambience["event"])
        query_input = query_scope.mangle_query_input(rs)
        query_input["is_search"] = "True"
        query: Optional[Query] = check(
            rs, vtypes.QueryInput, query_input, "query", spec=spec, allow_empty=False)
        if not rs.has_validation_errors() and query:
            query_id = self.eventproxy.store_event_query(
                rs, rs.ambience["event"]["id"], query)
            self.notify_return_code(rs, query_id)
            if query_id:
                query.query_id = query_id
                del query_input["query_name"]
        return self.redirect(rs, query_scope.get_target(), query_input)

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdata("query_id", "query_scope")
    def delete_event_query(self, rs: RequestState, event_id: int,
                           query_id: int, query_scope: QueryScope) -> Response:
        """Delete a stored event query."""
        query_input = None
        if not rs.has_validation_errors():
            stored_query = unwrap(
                self.eventproxy.get_event_queries(rs, event_id, query_ids=(query_id,))
                or None)
            if stored_query:
                query_input = stored_query.serialize()
            code = self.eventproxy.delete_event_query(rs, query_id)
            self.notify_return_code(rs, code)
        if query_scope and query_scope.get_target():
            return self.redirect(rs, query_scope.get_target(), query_input)
        return self.redirect(rs, "event/show_event", query_input)

    @periodic("validate_stored_event_queries", 4 * 24)
    def validate_stored_event_queries(self, rs: RequestState, state: CdEDBObject
                                      ) -> CdEDBObject:
        """Validate all stored event queries, to ensure nothing went wrong."""
        data = {}
        event_ids = self.eventproxy.list_events(rs, archived=False)
        for event_id in event_ids:
            data.update(self.eventproxy.get_invalid_stored_event_queries(rs, event_id))
        text = "Liebes Datenbankteam, einige gespeicherte Event-Queries sind ungültig:"
        if data:
            pdata = pprint.pformat(data)
            self.logger.warning(f"Invalid stroed event queries: {pdata}")
            msg = self._create_mail(f"{text}\n{pdata}",
                                    {"To": ("cdedb@lists.cde-ev.de",),
                                     "Subject": "Ungültige Event-Queries"},
                                    attachments=None)
            self._send_mail(msg)
        return state

    make_course_query_aux = staticmethod(make_course_query_aux)

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def course_query(self, rs: RequestState, event_id: int,
                     download: Optional[str], is_search: bool,
                     ) -> Response:

        scope = QueryScope.event_course
        spec = scope.get_spec(event=rs.ambience['event'])
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput, query_input,
                          "query", spec=spec, allow_empty=False)

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        choices, titles = self.make_course_query_aux(
            rs, rs.ambience['event'], courses,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        tracks = rs.ambience['event']['tracks']
        selection_default = ["course.shortname", ]
        for col in ("is_offered", "takes_place", "attendees"):
            selection_default += list("track{}.{}".format(t_id, col)
                                      for t_id in tracks)
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries = self.conf["DEFAULT_QUERIES_COURSE"](
            rs.gettext, rs.ambience['event'], spec)
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "course_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "course/course_query", params)

    make_lodgement_query_aux = staticmethod(make_lodgement_query_aux)

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def lodgement_query(self, rs: RequestState, event_id: int,
                        download: Optional[str], is_search: bool,
                        ) -> Response:

        scope = QueryScope.lodgement
        spec = scope.get_spec(event=rs.ambience["event"])
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)

        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(
            rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(
            rs, lodgement_group_ids)
        choices, titles = self.make_lodgement_query_aux(
            rs, rs.ambience['event'], lodgements, lodgement_groups,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        parts = rs.ambience['event']['parts']
        selection_default = ["lodgement.title"] + [
            f"lodgement_fields.xfield_{field['field_name']}"
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement]
        for col in ("regular_inhabitants",):
            selection_default += list(f"part{p_id}_{col}" for p_id in parts)

        default_queries = {}
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "lodgement_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "lodgement/lodgement_query", params)

    def _send_query_result(self, rs: RequestState, download: Optional[str],
                           filename: str, scope: QueryScope, query: Query,
                           params: CdEDBObject) -> Response:
        if download:
            shortname = rs.ambience['event']['shortname']
            return self.send_query_download(
                rs, params['result'], query.fields_of_interest, kind=download,
                filename=f"{shortname}_{filename}",
                substitutions=params['choices'])
        else:
            return self.render(rs, scope.get_target(redirect=False), params)

    @access("event")
    @REQUESTdata("phrase", "kind", "aux")
    def select_registration(self, rs: RequestState, phrase: str,
                            kind: str, aux: Optional[vtypes.ID]) -> Response:
        """Provide data for inteligent input fields.

        This searches for registrations (and associated users) by name
        so they can be easily selected without entering their
        numerical ids. This is similar to the select_persona()
        functionality in the core realm.

        The kind parameter specifies the purpose of the query which
        decides the privilege level required and the basic search
        paramaters.

        Allowed kinds:

        - ``orga_registration``: Search for a registration as event orga

        The aux parameter allows to supply an additional id. This will
        probably be an event id in the overwhelming majority of cases.

        Required aux value based on the 'kind':

        * ``orga_registration``: Id of the event you are orga of
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})

        spec_additions: Dict[str, str] = {}
        search_additions: List[QueryConstraint] = []
        event = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin", "meta_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "orga_registration":
            if aux is None:
                return self.send_json(rs, {})
            event = self.eventproxy.get_event(rs, aux)
            if not self.is_admin(rs):
                if rs.user.persona_id not in event['orgas']:
                    raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        else:
            return self.send_json(rs, {})

        data = None

        anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            tmp = self.eventproxy.get_registrations(rs, (anid,))
            if tmp:
                reg = unwrap(tmp)
                if reg['event_id'] == aux:
                    data = [reg]

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf["NUM_PREVIEW_CHARS"]:
            return self.send_json(rs, {})

        terms: List[str] = []
        if data is None:
            terms = [t.strip() for t in phrase.split(' ') if t]
            valid = True
            for t in terms:
                _, errs = inspect(vtypes.NonRegex, t, argname="phrase")
                if errs:
                    valid = False
            if not valid:
                data = []
            else:
                search = [("username,family_name,given_names,display_name",
                           QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = QueryScope.quick_registration.get_spec()
                spec["username,family_name,given_names,display_name"] = "str"
                spec.update(spec_additions)
                query = Query(
                    QueryScope.quick_registration, spec,
                    ("registrations.id", "username", "family_name",
                     "given_names", "display_name"),
                    search, (("registrations.id", True),))
                data = list(self.eventproxy.submit_general_query(
                    rs, query, event_id=aux))

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            data = xsorted(data, key=lambda e: e['id'])[:num_preview_personas]

        def name(x: CdEDBObject) -> str:
            return "{} {}".format(x['given_names'], x['family_name'])

        # Check if name occurs multiple times to add email address in this case
        counter: Dict[str, int] = collections.defaultdict(int)
        for entry in data:
            counter[name(entry)] += 1

        # Generate return JSON list
        ret = []
        for entry in xsorted(data, key=EntitySorter.persona):
            result = {
                'id': entry['id'],
                'name': name(entry),
                'display_name': entry['display_name'],
            }
            # Email/username is only delivered if we have admins
            # rights, a search term with an @ (and more) matches the
            # mail address, or the mail address is required to
            # distinguish equally named users
            searched_email = any(
                '@' in t and len(t) > self.conf["NUM_PREVIEW_CHARS"]
                and entry['username'] and t in entry['username']
                for t in terms)
            if (counter[name(entry)] > 1 or searched_email or
                    self.is_admin(rs)):
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'registrations': ret})
