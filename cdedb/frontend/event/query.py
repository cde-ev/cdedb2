#!/usr/bin/env python3

"""
The `EventQueryMixin` subclasses the `EventBaseFrontend` and provides endpoints for
querying registrations, courses and lodgements.
"""
import collections
import itertools
import pprint
from typing import Any, Optional, Union

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import (
    CdEDBObject,
    RequestState,
    determine_age_class,
    merge_dicts,
    unwrap,
)
from cdedb.common.i18n import get_localized_country_codes
from cdedb.common.n_ import n_
from cdedb.common.query import (
    Query,
    QueryConstraint,
    QueryOperators,
    QueryScope,
    QuerySpec,
    QuerySpecEntry,
)
from cdedb.common.query.defaults import (
    generate_event_course_default_queries,
    generate_event_registration_default_queries,
)
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.filter import enum_entries_filter
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    access,
    check_validation as check,
    event_guard,
    inspect_validation as inspect,
    periodic,
    request_extractor,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.frontend.event.query_stats import (
    EventCourseStatistic,
    EventRegistrationInXChoiceGrouper,
    EventRegistrationPartStatistic,
    EventRegistrationTrackStatistic,
)


class EventQueryMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def stats(self, rs: RequestState, event_id: int) -> Response:
        """Present an overview of the basic stats."""
        event_parts = rs.ambience['event'].parts
        tracks = rs.ambience['event'].tracks
        stat_part_groups: dict[int, models.PartGroup] = {
            part_group_id: part_group
            for part_group_id, part_group in rs.ambience['event'].part_groups.items()
            if part_group.constraint_type == const.EventPartGroupType.Statistic
        }

        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        # Precompute age classes of participants for all registration parts.
        for reg in registrations.values():
            persona = personas[reg['persona_id']]
            reg['birthday'] = persona['birthday']
            for part_id, reg_part in reg['parts'].items():
                reg_part['age_class'] = determine_age_class(
                    reg['birthday'], event_parts[part_id].part_begin)

        per_part_statistics: dict[
            EventRegistrationPartStatistic, dict[str, dict[int, set[int]]]]
        per_part_statistics = collections.OrderedDict()
        for reg_stat in EventRegistrationPartStatistic:
            _parts: dict[int, set[int]] = {
                part_id: set(
                    reg['id'] for reg in registrations.values()
                    if reg_stat.test(rs.ambience['event'], reg, part_id))
                for part_id in event_parts
            }
            _part_groups: dict[int, set[int]] = {
                part_group.id: set().union(
                    *(_parts[part_id] for part_id in part_group.parts))
                for part_group in stat_part_groups.values()
            }
            per_part_statistics[reg_stat] = {
                'parts': _parts,
                'part_groups': _part_groups,
            }
        # Needed for formatting in template. We do it here since it's ugly in jinja
        # without list comprehension.
        per_part_max_indent = max(stat.indent for stat in per_part_statistics)

        per_track_statistics: dict[
            Union[EventRegistrationTrackStatistic, EventCourseStatistic],
            dict[str, dict[int, set[int]]]]
        per_track_statistics = collections.OrderedDict()
        grouper = None
        if tracks:
            for course_stat in EventCourseStatistic:
                _tracks: dict[int, set[int]] = {
                    track_id: set(
                        course['id'] for course in courses.values()
                        if course_stat.test(rs.ambience['event'], course, track_id))
                    for track_id in tracks
                }
                _parts = {
                    part.id: set().union(
                        *(_tracks[track_id] for track_id in part.tracks))
                    for part in event_parts.values()
                }
                _part_groups = {
                    part_group.id: set().union(
                        *(_parts[part_id] for part_id in part_group.parts))
                    for part_group in stat_part_groups.values()
                }
                per_track_statistics[course_stat] = {
                    'tracks': _tracks,
                    'parts': _parts,
                    'part_groups': _part_groups,
                }
            for reg_track_stat in EventRegistrationTrackStatistic:
                _tracks = {
                    track_id: set(
                        reg['id'] for reg in registrations.values()
                        if reg_track_stat.test(rs.ambience['event'], reg, track_id))
                    for track_id in tracks
                }
                _parts = {
                    part.id: set().union(
                        *(_tracks[track_id] for track_id in part.tracks))
                    for part in event_parts.values()
                }
                _part_groups = {
                    part_group.id: set().union(
                        *(_parts[part_id] for part_id in part_group.parts))
                    for part_group in stat_part_groups.values()
                }
                per_track_statistics[reg_track_stat] = {
                    'tracks': _tracks,
                    'parts': _parts,
                    'part_groups': _part_groups,
                }

            grouper = EventRegistrationInXChoiceGrouper(
                rs.ambience['event'], registrations)

        return self.render(rs, "query/stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_part_max_indent': per_part_max_indent,
            'per_track_statistics': per_track_statistics, 'grouper': grouper,
        })

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def registration_query(self, rs: RequestState, event_id: int,
                           download: Optional[str], is_search: bool,
                           ) -> Response:
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.new_get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.new_get_lodgements(rs, lodgement_ids)
        lodgement_groups = self.eventproxy.new_get_lodgement_groups(rs, event_id)
        scope = QueryScope.registration
        spec = scope.get_spec(event=rs.ambience['event'], courses=courses,
                              lodgements=lodgements, lodgement_groups=lodgement_groups)
        self._fix_query_choices(rs, spec)

        # mangle the input, so we can prefill the form
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = generate_event_registration_default_queries(
            rs.ambience['event'], spec)
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        choices_lists = {k: list(spec_entry.choices.items())
                         for k, spec_entry in spec.items()
                         if spec_entry.choices}

        params: dict[str, Any] = {
            'spec': spec, 'query': query, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            params["aggregates"] = unwrap(self.eventproxy.submit_general_query(
                rs, query, event_id=event_id, aggregate=True))
            return self._send_query_result(
                rs, download, "registration_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/registration_query", params)

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

        spec = query_scope.get_spec(event=rs.ambience['event'])
        query_input = query_scope.mangle_query_input(rs)
        query_input["is_search"] = "True"
        query: Optional[Query] = check(
            rs, vtypes.QueryInput, query_input, "query", spec=spec, allow_empty=False)
        if not rs.has_validation_errors() and query:
            query_id = self.eventproxy.store_event_query(
                rs, rs.ambience['event'].id, query)
            rs.notify_return_code(query_id)
            if query_id:
                query.query_id = query_id
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
                # noinspection PyUnresolvedReferences
                query_input = stored_query.serialize_to_url()
            code = self.eventproxy.delete_event_query(rs, query_id)
            rs.notify_return_code(code)
        if query_scope and query_scope.get_target():
            return self.redirect(rs, query_scope.get_target(), query_input)
        return self.redirect(rs, "event/show_event", query_input)

    @periodic("validate_stored_event_queries", 4 * 24)
    def validate_stored_event_queries(self, rs: RequestState, state: CdEDBObject,
                                      ) -> CdEDBObject:
        """Validate all stored event queries, to ensure nothing went wrong."""
        data = {}
        event_ids = self.eventproxy.list_events(rs, archived=False)
        for event_id in event_ids:
            data.update(self.eventproxy.get_invalid_stored_event_queries(rs, event_id))
        text = "Liebes Datenbankteam, einige gespeicherte Event-Queries sind ungültig:"
        if data:
            pdata = pprint.pformat(data)
            self.logger.warning(f"Invalid stored event queries: {pdata}")
            defect_addresses = self.coreproxy.list_email_states(
                rs, const.EmailStatus.defect_states())
            msg = self._create_mail(
                f"{text}\n{pdata}",
                {"To": ("cdedb@lists.cde-ev.de",),
                 "Subject": "Ungültige Event-Queries"},
                attachments=None, defect_addresses=defect_addresses)
            self._send_mail(msg)
        return state

    @staticmethod
    def retrieve_custom_filter_fields(rs: RequestState, spec: QuerySpec) -> set[str]:
        field_spec = {f"cf_{f}": bool for f in spec}
        return set(itertools.chain.from_iterable(
            k.removeprefix("cf_").split(",")
            for k, v in request_extractor(rs, field_spec).items()
            if v
        ))

    @access("event")
    @event_guard()
    @REQUESTdata("scope")
    def custom_filter_summary(self, rs: RequestState, event_id: int,
                              scope: Optional[QueryScope] = None) -> Response:
        rs.ignore_validation_errors()

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.new_get_courses(rs, course_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.new_get_lodgements(rs, lodgement_ids)
        lodgement_groups = self.eventproxy.new_get_lodgement_groups(rs, event_id)

        query_specs = {
            scope: scope.get_spec(
                event=rs.ambience['event'], courses=courses,
                lodgements=lodgements, lodgement_groups=lodgement_groups)
            for scope in [
                QueryScope.registration, QueryScope.event_course, QueryScope.lodgement,
            ]
        }
        return self.render(rs, "query/custom_filter_summary", {
            'query_specs': query_specs, 'scope': scope,
        })

    @access("event")
    @event_guard()
    def create_registration_filter(self, rs: RequestState, event_id: int) -> Response:
        return self.configure_custom_filter_form(rs, event_id, QueryScope.registration)

    @access("event")
    @event_guard()
    def create_course_filter(self, rs: RequestState, event_id: int) -> Response:
        return self.configure_custom_filter_form(rs, event_id, QueryScope.event_course)

    @access("event")
    @event_guard()
    def create_lodgement_filter(self, rs: RequestState, event_id: int) -> Response:
        return self.configure_custom_filter_form(rs, event_id, QueryScope.lodgement)

    def configure_custom_filter_form(self, rs: RequestState, event_id: int,
                                     scope: QueryScope) -> Response:
        spec = self.eventproxy.get_query_spec(rs, event_id, scope)
        fields_by_kind = collections.defaultdict(list)
        for field, field_spec in spec.items():
            fields_by_kind[field_spec.type].append(field)

        return self.render(rs, "query/configure_custom_filter", {
            'scope': scope, 'spec': spec, 'fields_by_kind': fields_by_kind,
        })

    @staticmethod
    def _validate_custom_filter_uniqueness(rs: RequestState, data: CdEDBObject,
                                           custom_filter_id: Optional[int]) -> None:
        if any(cf.title == data['title'] and cf.id != custom_filter_id
               for cf in rs.ambience['event'].custom_query_filters.values()):
            rs.append_validation_error(
                ('title', KeyError(n_("A filter with this title already exists."))))
        if any(cf.get_field_string() == data['fields'] and cf.id != custom_filter_id
               for cf in rs.ambience['event'].custom_query_filters.values()):
            rs.append_validation_error(
                ('field', KeyError(n_(
                    "A filter with this selection of fields already exists."))))

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdatadict(*models.CustomQueryFilter.requestdict_fields())
    def create_custom_filter(self, rs: RequestState, event_id: int, data: CdEDBObject,
                             ) -> Response:
        scope = check(rs, QueryScope, data['scope'])
        if rs.has_validation_errors() or not scope:
            rs.notify("error", "Invalid Scope.")
            return self.redirect(rs, "event/custom_filter_summary")
        spec = self.eventproxy.get_query_spec(rs, event_id, scope)

        data.update({
            'fields': self.retrieve_custom_filter_fields(rs, spec),
            'id': -1,
            'event_id': event_id,
        })
        data = check(rs, vtypes.CustomQueryFilter, data, creation=True, query_spec=spec)
        if data:
            self._validate_custom_filter_uniqueness(rs, data, custom_filter_id=None)
        if rs.has_validation_errors() or not data:
            return self.configure_custom_filter_form(rs, event_id, scope)
        custom_filter = models.CustomQueryFilter(**data)
        custom_filter.event = None  # type: ignore[assignment]
        code = self.eventproxy.add_custom_query_filter(rs, custom_filter)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/custom_filter_summary", {'scope': scope})

    @access("event")
    @event_guard()
    def change_custom_filter_form(self, rs: RequestState, event_id: int,
                                  custom_filter_id: int) -> Response:
        custom_filter = rs.ambience['custom_filter']

        values = custom_filter.to_database()
        del values['fields']
        values.update({
            f"cf_{f}": True for f in custom_filter.fields
        })
        merge_dicts(rs.values, values)

        return self.configure_custom_filter_form(rs, event_id, custom_filter.scope)

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdatadict(*models.CustomQueryFilter.requestdict_fields())
    def change_custom_filter(self, rs: RequestState, event_id: int,
                             custom_filter_id: int, data: CdEDBObject) -> Response:
        custom_filter = rs.ambience['custom_filter']
        spec = self.eventproxy.get_query_spec(rs, event_id, custom_filter.scope)

        data['fields'] = self.retrieve_custom_filter_fields(rs, spec)
        data['id'] = custom_filter_id
        del data['event_id']
        del data['scope']

        data = check(rs, vtypes.CustomQueryFilter, data, query_spec=spec)
        if data:
            self._validate_custom_filter_uniqueness(rs, data, custom_filter_id)
        if rs.has_validation_errors() or not data:
            return self.change_custom_filter_form(rs, event_id, custom_filter_id)

        code = self.eventproxy.change_custom_query_filter(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/custom_filter_summary", {
            'scope': custom_filter.scope,
        })

    @access("event", modi={"POST"})
    @event_guard()
    def delete_custom_filter(self, rs: RequestState, event_id: int,
                             custom_filter_id: int) -> Response:
        code = self.eventproxy.delete_custom_query_filter(rs, custom_filter_id)
        rs.notify_return_code(code)
        return self.redirect(rs, "event/custom_filter_summary", {
            'scope': rs.ambience['custom_filter'].scope,
        })

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def course_query(self, rs: RequestState, event_id: int,
                     download: Optional[str], is_search: bool,
                     ) -> Response:

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.new_get_courses(rs, course_ids.keys())
        scope = QueryScope.event_course
        spec = scope.get_spec(event=rs.ambience['event'], courses=courses)
        self._fix_query_choices(rs, spec)
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput, query_input,
                          "query", spec=spec, allow_empty=False)

        selection_default = ["course.nr", "course.shortname", "course.instructors"]
        for col in ("takes_place",):
            selection_default.extend(
                f"track{t_id}.{col}" for t_id in rs.ambience['event'].tracks)

        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries = generate_event_course_default_queries(
            rs.ambience['event'], spec)
        default_queries.update(stored_queries)

        choices_lists = {k: list(spec_entry.choices.items())
                         for k, spec_entry in spec.items()
                         if spec_entry.choices}

        params: dict[str, Any] = {
            'spec': spec, 'query': query, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            params["aggregates"] = unwrap(self.eventproxy.submit_general_query(
                rs, query, event_id=event_id, aggregate=True))
            return self._send_query_result(
                rs, download, "course_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/course_query", params)

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def lodgement_query(self, rs: RequestState, event_id: int,
                        download: Optional[str], is_search: bool,
                        ) -> Response:

        scope = QueryScope.lodgement
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.new_get_lodgements(rs, lodgement_ids)
        lodgement_groups = self.eventproxy.new_get_lodgement_groups(rs, event_id)
        spec = scope.get_spec(event=rs.ambience['event'], lodgements=lodgements,
                              lodgement_groups=lodgement_groups)
        self._fix_query_choices(rs, spec)
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)

        parts = rs.ambience['event'].parts
        selection_default = ["lodgement.title"] + [
            f"lodgement_fields.xfield_{field.field_name}"
            for field in rs.ambience['event'].fields.values()
            if field.association == const.FieldAssociations.lodgement]
        for col in ("regular_inhabitants",):
            selection_default += list(f"part{p_id}_{col}" for p_id in parts)

        default_queries = {}
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        choices_lists = {k: list(spec_entry.choices.items())
                         for k, spec_entry in spec.items()
                         if spec_entry.choices}

        params: CdEDBObject = {
            'spec': spec, 'query': query, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            params["aggregates"] = unwrap(self.eventproxy.submit_general_query(
                rs, query, event_id=event_id, aggregate=True))
            return self._send_query_result(
                rs, download, "lodgement_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/lodgement_query", params)

    @staticmethod
    def _fix_query_choices(rs: RequestState, spec: QuerySpec) -> None:
        # Add choices that could not be automatically applied before.
        for k, v in spec.items():
            if k.endswith("gender"):
                spec[k].choices = dict(enum_entries_filter(const.Genders, rs.gettext))
            if k.endswith(".status"):
                spec[k].choices = dict(enum_entries_filter(
                    const.RegistrationPartStati, rs.gettext))
            if k.endswith(("country", "country2")):
                spec[k].choices = dict(get_localized_country_codes(rs))

    def _send_query_result(self, rs: RequestState, download: Optional[str],
                           filename: str, scope: QueryScope, query: Query,
                           params: CdEDBObject) -> Response:
        if download:
            shortname = rs.ambience['event'].shortname
            return self.send_query_download(
                rs, params['result'], query, kind=download,
                filename=f"{shortname}_{filename}")
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

        search_additions: list[QueryConstraint] = []
        event = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin", "meta_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "orga_registration":
            if aux is None:
                return self.send_json(rs, {})
            event = self.eventproxy.get_event(rs, aux)
            if not self.is_admin(rs):
                if rs.user.persona_id not in event.orgas:
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

        terms: list[str] = []
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
                key = "username,family_name,given_names,display_name"
                search = [(key, QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = QueryScope.quick_registration.get_spec()
                spec[key] = QuerySpecEntry("str", "")
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
        counter: dict[str, int] = collections.defaultdict(int)
        for entry in data:
            counter[name(entry)] += 1
            if 'id' not in entry:
                entry['id'] = entry[QueryScope.quick_registration.get_primary_key()]

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
