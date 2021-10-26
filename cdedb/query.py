#!/usr/bin/env python3

"""Framework for complex queries.

This defines an abstraction for specifying queries. The basic use case
is the member search which has to be handled at three stages: templates,
frontend and backend. All of this should happen with a unified
framework, thus this module. This module is especially useful in setting
up an environment for passing a query from frontend to backend.
"""

import collections
import copy
import enum
import re
from typing import Any, Collection, Dict, Tuple

import cdedb.database.constants as const
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, EntitySorter, RequestState,
    get_localized_country_codes, n_, xsorted,
)
from cdedb.filter import enum_entries_filter, keydictsort_filter


@enum.unique
class QueryOperators(enum.IntEnum):
    """Enum for all possible operators on a query column."""
    empty = 1
    nonempty = 2
    equal = 3
    unequal = 4
    oneof = 5
    otherthan = 6
    equalornull = 7
    unequalornull = 8
    match = 10
    unmatch = 11
    regex = 12
    notregex = 13
    containsall = 14
    containsnone = 15
    containssome = 16
    fuzzy = 17
    less = 20
    lessequal = 21
    between = 22
    outside = 23
    greaterequal = 24
    greater = 25


_ops = QueryOperators
#: Only a subset of all possible operators is appropriate for each data
#: type. Order is important for UI purpose hence no sets.
VALID_QUERY_OPERATORS: Dict[str, Tuple[QueryOperators, ...]] = {
    "str": (_ops.match, _ops.unmatch, _ops.equal, _ops.unequal,
            _ops.equalornull, _ops.unequalornull, _ops.containsall,
            _ops.containsnone, _ops.containssome, _ops.oneof, _ops.otherthan,
            _ops.regex, _ops.notregex, _ops.fuzzy, _ops.empty, _ops.nonempty,
            _ops.greater, _ops.greaterequal, _ops.less, _ops.lessequal,
            _ops.between, _ops.outside),
    "id": (_ops.equal, _ops.unequal, _ops.equalornull, _ops.unequalornull,
           _ops.oneof, _ops.otherthan, _ops.empty, _ops.nonempty),
    "int": (_ops.equal, _ops.equalornull, _ops.unequal, _ops.unequalornull,
            _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal, _ops.between,
            _ops.outside, _ops.greaterequal, _ops.greater, _ops.empty,
            _ops.nonempty),
    "float": (_ops.less, _ops.between, _ops.outside, _ops.greater, _ops.empty,
              _ops.nonempty),
    "date": (_ops.equal, _ops.unequal, _ops.equalornull, _ops.unequalornull,
             _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal, _ops.between,
             _ops.outside, _ops.greaterequal, _ops.greater, _ops.empty,
             _ops.nonempty),
    "datetime": (_ops.equal, _ops.unequal, _ops.equalornull, _ops.unequalornull,
                 _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal,
                 _ops.between, _ops.outside, _ops.greaterequal, _ops.greater,
                 _ops.empty, _ops.nonempty),
    "bool": (_ops.equal, _ops.equalornull, _ops.empty, _ops.nonempty),
}

#: Some operators are useful if there is only a finite set of possible values.
#: The rest (which is missing here) is not useful in that case.
SELECTION_VALUE_OPERATORS = (_ops.empty, _ops.nonempty, _ops.equal,
                             _ops.unequal, _ops.equalornull,
                             _ops.unequalornull, _ops.oneof, _ops.otherthan)

#: Some operators expect several operands (that is a space delimited list of
#: operands) and thus need to be treated differently.
MULTI_VALUE_OPERATORS = {_ops.oneof, _ops.otherthan, _ops.containsall,
                         _ops.containsnone, _ops.containssome, _ops.between,
                         _ops.outside}

#: Some operators expect no operands need some special-casing.
NO_VALUE_OPERATORS = {_ops.empty, _ops.nonempty}


QueryConstraint = Tuple[str, QueryOperators, Any]
QueryOrder = Tuple[str, bool]


class QueryScope(enum.IntEnum):
    """Enum that contains the different kinds of generalized queries.

    This is used in conjunction with the `Query` class and bundles together a lot of
    constant and some dynamic things for the individual scopes.
    """
    persona = 1
    core_user = 2
    assembly_user = 3
    cde_user = 4
    event_user = 5
    ml_user = 6
    past_event_user = 7
    archived_persona = 10
    archived_core_user = 11
    archived_past_event_user = 12
    cde_member = 20
    registration = 30
    quick_registration = 31
    lodgement = 32
    event_course = 33
    past_event_course = 40

    def get_view(self) -> str:
        """Return the SQL FROM target associated with this scope.

        Supstitute for SQL views. We cannot use SQL views since they do not allow
        multiple columns with the same name, but each join brings in an id column.
        """
        default_view = ("core.personas LEFT OUTER JOIN past_event.participants"
                        " ON personas.id = participants.persona_id")
        return _QUERY_VIEWS.get(self, default_view)  # type: ignore[return-value]

    def get_primary_key(self, short: bool = False) -> str:
        """Return the primary key of the view associated with the scope.

        This should always be selected, to avoid any pathologies.
        """
        ret = PRIMARY_KEYS.get(self, "personas.id")
        if short:
            return ret.split(".", 1)[1]
        return ret

    def get_spec(self, *, event: CdEDBObject = None) -> Dict[str, str]:
        """Return the query spec for this scope.

        These may be enriched by ext-fields. Order is important for UI purposes.

        Note that for schema specified columns (like ``personas.id``) the schema
        part does not survive querying and needs to be stripped before output.

        :param event: For some scopes, the spec is dependent on specific event data.
            For these scopes (see `event_spec_map` below) this must be provided.
            The format should be like the return of `EventBackend.get_event()`.
        """
        event_spec_map = {
            QueryScope.registration: make_registration_query_spec,
            QueryScope.lodgement: make_lodgement_query_spec,
            QueryScope.event_course: make_course_query_spec,
        }
        if self in event_spec_map:
            if not event:
                raise ValueError(n_("Constructing the query spec for %(scope)s"
                                    " requires additional event information."),
                                 {"scope": self})
            return event_spec_map[self](event)

        return copy.deepcopy(_QUERY_SPECS[self])

    def supports_storing(self) -> bool:
        """Whether or not storing queries with this scope is supported."""
        return self in {QueryScope.registration, QueryScope.lodgement,
                        QueryScope.event_course}

    def get_target(self, *, redirect: bool = True) -> str:
        """For scopes that support storing, where to redirect to after storing."""
        if self == QueryScope.registration:
            realm, domain, target = "event", "registration", "registration_query"
        elif self == QueryScope.lodgement:
            realm, domain, target = "event", "lodgement", "lodgement_query"
        elif self == QueryScope.event_course:
            realm, domain, target = "event", "course", "course_query"
        else:
            realm, domain, target = "", "", ""
        return f"{realm if redirect else domain + '/'}/{target}"

    def mangle_query_input(self, rs: RequestState, defaults: CdEDBObject = None,
                           ) -> Dict[str, str]:
        """Helper to bundle the extraction of submitted form data for a query.

        This simply extracts all the values expected according to the spec of the
        scope, while taking care of the fact that empty values may be omitted.

        This does not do any validation however, to this needs to validated afterwards
        using the `vtypes.QueryInput` validator which will turn this into a
        `Query` object.

        :param defaults: Default values which appear like they have been submitted,
            if nothing has been submitted for this paramater.
        :returns: The raw data associated to the query described by the spec
            extracted from the request data saved in the request state.
        """
        defaults = defaults or {}
        params = {"scope": str(self)}
        if "query_name" in rs.request.values:
            rs.values["query_name"] = rs.request.values["query_name"]
            params["query_name"] = rs.values["query_name"]
        spec = self.get_spec(event=rs.ambience.get("event"))
        for field in spec:
            for prefix in ("qval_", "qsel_", "qop_"):
                name = prefix + field
                if name in rs.request.values:
                    params[name] = rs.values[name] = rs.request.values[name]
        for postfix in ("primary", "secondary", "tertiary"):
            name = "qord_" + postfix
            if name in rs.request.values:
                params[name] = rs.values[name] = rs.request.values[name]
            name = "qord_" + postfix + "_ascending"
            if name in rs.request.values:
                params[name] = rs.values[name] = rs.request.values[name]
        for key, value in defaults.items():
            if key not in params:
                params[key] = rs.values[key] = value
        return params


# See `QueryScope.get_view().
_QUERY_VIEWS = {
    QueryScope.persona:
        "core.personas",
    QueryScope.cde_user:
        """core.personas
        LEFT OUTER JOIN past_event.participants
            ON personas.id = participants.persona_id
        LEFT OUTER JOIN (
            SELECT
                id, granted_at, revoked_at,
                revoked_at IS NULL AS active_lastschrift,
                amount, persona_id
            FROM cde.lastschrift
            WHERE (granted_at, persona_id) IN (
                SELECT MAX(granted_at) AS granted_at, persona_id
                FROM cde.lastschrift GROUP BY persona_id
            )
        ) AS lastschrift ON personas.id = lastschrift.persona_id
        """,
    QueryScope.archived_persona:
        "core.personas",
    QueryScope.registration:
        None,  # This will be generated on the fly.
    QueryScope.quick_registration:
        "core.personas INNER JOIN event.registrations"
        " ON personas.id = registrations.persona_id",
    QueryScope.lodgement:
        None,  # This will be generated on the fly.
    QueryScope.event_course:
        None,  # This will be generated on the fly.
    QueryScope.past_event_course:
        "past_event.courses LEFT OUTER JOIN past_event.events"
        " ON courses.pevent_id = events.id",
}

# See QueryScope.get_primary_key().
# This dict contains the special cases. For everything else use personas.id.
PRIMARY_KEYS = {
    QueryScope.registration: "reg.id",
    QueryScope.quick_registration: "registrations.id",
    QueryScope.lodgement: "lodgement.id",
    QueryScope.event_course: "course.id",
    QueryScope.past_event_course: "courses.id",
}

# See QueryScope.get_spec().
_QUERY_SPECS = {
    QueryScope.persona:  # query for a persona without past event infos
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("is_active", "bool"),
            ("is_ml_realm", "bool"),
            ("is_event_realm", "bool"),
            ("is_assembly_realm", "bool"),
            ("is_cde_realm", "bool"),
            ("is_member", "bool"),
            ("is_searchable", "bool"),
            ("is_ml_admin", "bool"),
            ("is_event_admin", "bool"),
            ("is_assembly_admin", "bool"),
            ("is_cde_admin", "bool"),
            ("is_core_admin", "bool"),
            ("is_meta_admin", "bool"),
            ("notes", "str"),
            ("fulltext", "str"),
        ]),
    QueryScope.core_user:  # query for a general user including past event infos
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("is_active", "bool"),
            ("is_ml_realm", "bool"),
            ("is_assembly_realm", "bool"),
            ("is_event_realm", "bool"),
            ("is_cde_realm", "bool"),
            ("is_member", "bool"),
            ("is_searchable", "bool"),
            ("is_ml_admin", "bool"),
            ("is_event_admin", "bool"),
            ("is_assembly_admin", "bool"),
            ("is_cde_admin", "bool"),
            ("is_core_admin", "bool"),
            ("is_meta_admin", "bool"),
            ("is_ml_admin,is_event_admin,is_assembly_admin,is_cde_admin,"
             "is_core_admin,is_meta_admin", "bool"),
            ("pevent_id", "id"),
            ("notes", "str"),
            ("fulltext", "str"),
        ]),
    QueryScope.cde_user:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("title", "str"),
            ("name_supplement", "str"),
            ("birth_name", "str"),
            ("gender", "int"),
            ("birthday", "date"),
            ("telephone", "str"),
            ("mobile", "str"),
            ("address", "str"),
            ("address_supplement", "str"),
            ("postal_code", "str"),
            ("location", "str"),
            ("country", "str"),
            ("address2", "str"),
            ("address_supplement2", "str"),
            ("postal_code2", "str"),
            ("location2", "str"),
            ("country2", "str"),
            ("is_active", "bool"),
            ("is_member", "bool"),
            ("trial_member", "bool"),
            ("paper_expuls", "bool"),
            ("is_searchable", "bool"),
            ("decided_search", "bool"),
            ("balance", "float"),
            ("is_ml_admin", "bool"),
            ("is_event_admin", "bool"),
            ("is_assembly_admin", "bool"),
            ("is_cde_admin", "bool"),
            ("is_core_admin", "bool"),
            ("is_meta_admin", "bool"),
            ("weblink", "str"),
            ("specialisation", "str"),
            ("affiliation", "str"),
            ("timeline", "str"),
            ("interests", "str"),
            ("free_form", "str"),
            ("pevent_id", "id"),
            ("pcourse_id", "id"),
            ("notes", "str"),
            ("fulltext", "str"),
            ("lastschrift.granted_at", "datetime"),
            ("lastschrift.revoked_at", "datetime"),
            ("lastschrift.active_lastschrift", "bool"),
            ("lastschrift.amount", "float"),
        ]),
    QueryScope.event_user:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("title", "str"),
            ("name_supplement", "str"),
            ("gender", "int"),
            ("birthday", "date"),
            ("telephone", "str"),
            ("mobile", "str"),
            ("address", "str"),
            ("address_supplement", "str"),
            ("postal_code", "str"),
            ("location", "str"),
            ("country", "str"),
            ("is_active", "bool"),
            ("is_cde_realm", "bool"),
            ("is_member", "bool"),
            ("is_searchable", "bool"),
            ("is_event_admin", "bool"),
            ("is_ml_admin", "bool"),
            ("notes", "str"),
            ("fulltext", "str"),
        ]),
    QueryScope.past_event_user:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("title", "str"),
            ("name_supplement", "str"),
            ("birthday", "date"),
            ("telephone", "str"),
            ("mobile", "str"),
            ("address", "str"),
            ("address_supplement", "str"),
            ("postal_code", "str"),
            ("location", "str"),
            ("country", "str"),
            ("pevent_id", "id"),
            ("pcourse_id", "id"),
        ]),
    QueryScope.archived_persona:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("display_name", "str"),
            ("notes", "str"),
        ]),
    QueryScope.archived_core_user:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("display_name", "str"),
            ("birth_name", "str"),
            ("gender", "int"),
            ("birthday", "date"),
            ("pevent_id", "id"),
            ("notes", "str"),
            ("is_ml_realm", "bool"),
            ("is_event_realm", "bool"),
            ("is_assembly_realm", "bool"),
            ("is_cde_realm", "bool"),
        ]),
    QueryScope.archived_past_event_user:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("display_name", "str"),
            ("birth_name", "str"),
            ("gender", "int"),
            ("birthday", "date"),
            ("pevent_id", "id"),
            ("notes", "str"),
        ]),
    QueryScope.cde_member:
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names,display_name", "str"),
            ("family_name,birth_name", "str"),
            ("username", "str"),
            ("address,address_supplement,address2,address_supplement2", "str"),
            ("postal_code,postal_code2", "str"),
            ("telephone,mobile", "str"),
            ("location,location2", "str"),
            ("country,country2", "str"),
            ("weblink,specialisation,affiliation,timeline,interests,free_form",
             "str"),
            ("pevent_id", "id"),
            ("pcourse_id", "id"),
            ("fulltext", "str"),
        ]),
    QueryScope.quick_registration:
        collections.OrderedDict([
            ("registrations.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("title", "str"),
            ("name_supplement", "str"),
        ]),
    QueryScope.past_event_course:
        collections.OrderedDict([
            ("courses.id", "id"),
            ("courses.pcourse_id", "id"),
            ("courses.pevent_id", "id"),
            ("courses.nr", "str"),
            ("courses.title", "str"),
            ("courses.description", "str"),
            ("events.title", "str"),
            ("events.tempus", "date")
        ]),
}
_QUERY_SPECS[QueryScope.ml_user] = _QUERY_SPECS[QueryScope.persona]
_QUERY_SPECS[QueryScope.assembly_user] = _QUERY_SPECS[QueryScope.persona]


class QueryResultEntryFormat(enum.Enum):
    """Simple enumeration to tell the template how to format a query result entry."""
    other = -1
    persona = 1
    username = 2
    event_course = 10
    event_lodgement = 11
    date = 20
    datetime = 21
    bool = 22


class Query:
    """General purpose abstraction for an SQL query.

    This allows to make very flexible queries in a programmatic way. The
    basic use cases are the member search in the cde realm and the
    search page for event orgas. The latter is responsible for some
    design descisions, since we have to accomodate ext-fields and
    everything.
    """

    def __init__(self, scope: QueryScope, spec: CdEDBObject,
                 fields_of_interest: Collection[str],
                 constraints: Collection[QueryConstraint],
                 order: Collection[QueryOrder],
                 name: str = None, query_id: int = None,
                 ):
        """
        :param scope: target of FROM clause; key for :py:data:`QUERY_VIEWS`.
            We would like to use SQL views for this, but they are not flexible
            enough.
        :param fields_of_interest: column names to be SELECTed.
        :param spec: Keys are field names and values are validator names. See
            :py:const:`QUERY_SPECS`.
        :param constraints: clauses for WHERE, they are concatenated with AND
            and each comma in the first component causes an OR
        :param order: First components are the column names to be used for
            ORDER BY and the second component toggles ascending sorting order.
        :param query_id: If the Query was retrieved from the database, this should be
            the id of the entry in the corresponding table.
        """
        self.scope = scope
        self.spec = spec
        self.fields_of_interest = list(fields_of_interest)
        self.constraints = list(constraints)
        self.order = list(order)
        self.name = name
        self.query_id = query_id

    def __repr__(self) -> str:
        return (f"Query(scope={self.scope},"
                f" fields_of_interest={self.fields_of_interest},"
                f" constraints={self.constraints}, order={self.order},"
                f" spec={self.spec})")

    def fix_custom_columns(self) -> None:
        """Custom columns may contain upper case, this wraps them in qoutes."""
        self.fields_of_interest = [
            ",".join(
                ".".join(atom if atom.islower() else '"{}"'.format(atom)
                         for atom in moniker.split("."))
                for moniker in column.split(","))
            for column in self.fields_of_interest]
        self.constraints = [
            (",".join(
                ".".join(atom if atom.islower() else '"{}"'.format(atom)
                         for atom in moniker.split("."))
                for moniker in column.split(",")),
             operator, value)
            for column, operator, value in self.constraints
        ]
        self.order = [
            (".".join(atom if atom.islower() else '"{}"'.format(atom)
                      for atom in entry.split(".")),
             ascending)
            for entry, ascending in self.order]
        # Fix our fix
        changed_fields = set()
        for column in self.fields_of_interest:
            for moniker in column.split(","):
                if '"' in moniker:
                    changed_fields.add(moniker)
        for column, _, _ in self.constraints:
            for moniker in column.split(","):
                if '"' in moniker:
                    changed_fields.add(moniker)
        for moniker, _ in self.order:
            if '"' in moniker:
                changed_fields.add(moniker)
        for field in changed_fields:
            self.spec[field] = self.spec[field.replace('"', '')]
            del self.spec[field.replace('"', '')]

    def serialize(self) -> CdEDBObject:
        """
        Serialize a query into a dict.

        The format is compatible with QueryInput and search params
        """
        params: CdEDBObject = {}
        for field in self.fields_of_interest:
            params['qsel_{}'.format(field)] = True
        for field, op, value in self.constraints:
            params['qop_{}'.format(field)] = op.value
            if (isinstance(value, collections.Iterable)
                    and not isinstance(value, str)):
                # TODO: Get separator from central place
                #  (also used in validation._query_input)
                params['qval_{}'.format(field)] = ','.join(str(x) for x in value)
            else:
                params['qval_{}'.format(field)] = value
        for entry, postfix in zip(self.order, ("primary", "secondary", "tertiary")):
            field, ascending = entry
            params['qord_{}'.format(postfix)] = field
            params['qord_{}_ascending'.format(postfix)] = ascending
        params['is_search'] = True
        params['scope'] = str(self.scope)
        params['query_name'] = self.name
        return params

    def get_field_format_spec(self, field: str) -> QueryResultEntryFormat:
        if self.spec[field] == "date":
            return QueryResultEntryFormat.date
        if self.spec[field] == "datetime":
            return QueryResultEntryFormat.datetime
        if self.spec[field] == "bool":
            return QueryResultEntryFormat.bool
        if self.scope == QueryScope.registration:
            if field == "persona.id":
                return QueryResultEntryFormat.persona
            if field == "persona.username":
                return QueryResultEntryFormat.username
            if re.match(r"track\d+\.course_(id|instructor)", field):
                return QueryResultEntryFormat.event_course
            if re.match(r"course_choices\d+\.rank\d+", field):
                return QueryResultEntryFormat.event_course
            if re.match(r"part\d+\.lodgement_id", field):
                return QueryResultEntryFormat.event_lodgement
        elif self.scope == QueryScope.event_course:
            if field == "course.course_id":
                # TODO: This is already linked. Do we need this?
                return QueryResultEntryFormat.event_course
        elif self.scope == QueryScope.lodgement:
            if field == "lodgement.lodgement_id":
                # TODO: This is already linked. Do we need this?
                return QueryResultEntryFormat.event_lodgement
        elif field == "personas.id":
            return QueryResultEntryFormat.persona
        elif field == "username":
            return QueryResultEntryFormat.username
        return QueryResultEntryFormat.other


def make_registration_query_spec(event: CdEDBObject) -> Dict[str, str]:
    """Helper to generate ``QueryScope.registration``'s spec.

    Since each event has dynamic columns for parts and extra fields we
    have amend the query spec on the fly.
    """

    tracks = event['tracks']
    spec = collections.OrderedDict([
        ("reg.id", "id"),
        ("persona.id", "id"),
        ("persona.given_names", "str"),
        ("persona.family_name", "str"),
        ("persona.username", "str"),
        ("persona.is_member", "bool"),
        ("persona.display_name", "str"),
        ("persona.title", "str"),
        ("persona.name_supplement", "str"),
        ("persona.gender", "int"),
        ("persona.birthday", "date"),
        ("persona.telephone", "str"),
        ("persona.mobile", "str"),
        ("persona.address", "str"),
        ("persona.address_supplement", "str"),
        ("persona.postal_code", "str"),
        ("persona.location", "str"),
        ("persona.country", "str"),
        ("reg.payment", "date"),
        ("reg.amount_paid", "float"),
        ("reg.amount_owed", "float"),
        ("reg.parental_agreement", "bool"),
        ("reg.mixed_lodging", "bool"),
        ("reg.list_consent", "bool"),
        ("reg.notes", "str"),
        ("reg.orga_notes", "str"),
        ("reg.checkin", "datetime"),
        ("ctime.creation_time", "datetime"),
        ("mtime.modification_time", "datetime"),
    ])
    # note that spec is an ordered dict and we should respect the order
    for part_id, part in keydictsort_filter(event['parts'],
                                            EntitySorter.event_part):
        spec["part{0}.status".format(part_id)] = "int"
        spec["part{0}.is_camping_mat".format(part_id)] = "bool"
        spec["part{0}.lodgement_id".format(part_id)] = "id"
        spec["lodgement{0}.id".format(part_id)] = "id"
        spec["lodgement{0}.group_id".format(part_id)] = "id"
        spec["lodgement{0}.title".format(part_id)] = "str"
        spec["lodgement{0}.notes".format(part_id)] = "str"
        for f in xsorted(event['fields'].values(),
                            key=EntitySorter.event_field):
            if f['association'] == const.FieldAssociations.lodgement:
                temp = "lodgement{0}.xfield_{1}"
                kind = const.FieldDatatypes(f['kind']).name
                spec[temp.format(part_id, f['field_name'])] = kind
        spec["lodgement_group{0}.id".format(part_id)] = "id"
        spec["lodgement_group{0}.title".format(part_id)] = "str"
        ordered_tracks = keydictsort_filter(
            part['tracks'], EntitySorter.course_track)
        for track_id, track in ordered_tracks:
            spec["track{0}.is_course_instructor".format(track_id)] = "bool"
            spec["track{0}.course_id".format(track_id)] = "int"
            spec["track{0}.course_instructor".format(track_id)] = "int"
            for temp in ("course", "course_instructor",):
                spec["{1}{0}.id".format(track_id, temp)] = "id"
                spec["{1}{0}.nr".format(track_id, temp)] = "str"
                spec["{1}{0}.title".format(track_id, temp)] = "str"
                spec["{1}{0}.shortname".format(track_id, temp)] = "str"
                spec["{1}{0}.notes".format(track_id, temp)] = "str"
                for f in xsorted(event['fields'].values(),
                                 key=EntitySorter.event_field):
                    if f['association'] == const.FieldAssociations.course:
                        key = f"{temp}{track_id}.xfield_{f['field_name']}"
                        kind = const.FieldDatatypes(f['kind']).name
                        spec[key] = kind
            for i in range(track['num_choices']):
                spec[f"course_choices{track_id}.rank{i}"] = "int"
            if track['num_choices'] > 1:
                spec[",".join(f"course_choices{track_id}.rank{i}"
                                for i in range(track['num_choices']))] = "int"
    if len(event['parts']) > 1:
        spec[",".join("part{0}.status".format(part_id)
                        for part_id in event['parts'])] = "int"
        spec[",".join("part{0}.is_camping_mat".format(part_id)
                        for part_id in event['parts'])] = "bool"
        spec[",".join("part{0}.lodgement_id".format(part_id)
                        for part_id in event['parts'])] = "id"
        spec[",".join("lodgement{0}.id".format(part_id)
                        for part_id in event['parts'])] = "id"
        spec[",".join("lodgement{0}.group_id".format(part_id)
                        for part_id in event['parts'])] = "id"
        spec[",".join("lodgement{0}.title".format(part_id)
                        for part_id in event['parts'])] = "str"
        spec[",".join("lodgement{0}.notes".format(part_id)
                        for part_id in event['parts'])] = "str"
        spec[",".join("lodgement_group{0}.id".format(part_id)
                        for part_id in event['parts'])] = "id"
        spec[",".join("lodgement_group{0}.title".format(part_id)
                        for part_id in event['parts'])] = "str"
        for f in xsorted(event['fields'].values(),
                            key=EntitySorter.event_field):
            if f['association'] == const.FieldAssociations.lodgement:
                key = ",".join(
                    "lodgement{0}.xfield_{1}".format(
                        part_id, f['field_name'])
                    for part_id in event['parts'])
                kind = const.FieldDatatypes(f['kind']).name
                spec[key] = kind
    if len(tracks) > 1:
        spec[",".join("track{0}.is_course_instructor".format(track_id)
                        for track_id in tracks)] = "bool"
        spec[",".join("track{0}.course_id".format(track_id)
                        for track_id in tracks)] = "bool"
        spec[",".join("track{0}.course_instructor".format(track_id)
                        for track_id in tracks)] = "int"
        for temp in ("course", "course_instructor",):
            spec[",".join(f"{temp}{track_id}.id" for track_id in tracks)] = "id"
            spec[",".join(f"{temp}{track_id}.nr" for track_id in tracks)] = "str"
            spec[",".join(f"{temp}{track_id}.title" for track_id in tracks)] = "str"
            spec[",".join(f"{temp}{track_id}.shortname" for track_id in tracks)] = "str"
            spec[",".join(f"{temp}{track_id}.notes" for track_id in tracks)] = "str"
            for f in xsorted(event['fields'].values(), key=EntitySorter.event_field):
                if f['association'] == const.FieldAssociations.course:
                    key = ",".join(f"{temp}{track_id}.xfield_{f['field_name']}"
                                   for track_id in tracks)
                    kind = const.FieldDatatypes(f['kind']).name
                    spec[key] = kind
        if sum(track['num_choices'] for track in tracks.values()) > 1:
            spec[",".join(f"course_choices{track_id}.rank{i}"
                          for track_id, track in tracks.items()
                          for i in range(track['num_choices']))] = "int"
    for f in xsorted(event['fields'].values(), key=EntitySorter.event_field):
        if f['association'] == const.FieldAssociations.registration:
            kind = const.FieldDatatypes(f['kind']).name
            spec["reg_fields.xfield_{}".format(f['field_name'])] = kind
    return spec


# TODO specify return type as OrderedDict.
def make_registration_query_aux(
    rs: RequestState, event: CdEDBObject, courses: CdEDBObjectMap,
    lodgements: CdEDBObjectMap, lodgement_groups: CdEDBObjectMap,
    fixed_gettext: bool = False
) -> Tuple[Dict[str, Dict[int, str]], Dict[str, str]]:
    """Un-inlined code to prepare input for template.
    :param fixed_gettext: whether or not to use a fixed translation
        function. True means static, False means localized.
    :returns: Choices for select inputs and titles for columns.
    """
    tracks = event['tracks']

    if fixed_gettext:
        gettext = rs.default_gettext
        enum_gettext = lambda x: x.name
    else:
        gettext = rs.gettext
        enum_gettext = rs.gettext

    course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
    course_choices = collections.OrderedDict(
        (c_id, course_identifier(c))
        for c_id, c in keydictsort_filter(courses, EntitySorter.course))
    lodge_identifier = lambda l: l["title"]
    lodgement_choices = collections.OrderedDict(
        (l_id, lodge_identifier(l))
        for l_id, l in keydictsort_filter(lodgements,
                                          EntitySorter.lodgement))
    lodgement_group_identifier = lambda g: g["title"]
    lodgement_group_choices = collections.OrderedDict(
        (g_id, lodgement_group_identifier(g))
        for g_id, g in keydictsort_filter(lodgement_groups,
                                          EntitySorter.lodgement_group))
    # First we construct the choices
    choices: Dict[str, Dict[Any, str]] = {
        # Genders enum
        'persona.gender': collections.OrderedDict(
            enum_entries_filter(
                const.Genders, enum_gettext, raw=fixed_gettext)),
        'persona.country': collections.OrderedDict(get_localized_country_codes(rs)),
    }

    # Precompute some choices
    reg_part_stati_choices = collections.OrderedDict(
        enum_entries_filter(
            const.RegistrationPartStati, enum_gettext, raw=fixed_gettext))
    lodge_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.lodgement
        }
    course_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.course
        }
    reg_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.registration
        }

    for part_id in event['parts']:
        choices.update({
            # RegistrationPartStati enum
            "part{0}.status".format(part_id): reg_part_stati_choices,
            # Lodgement choices for the JS selector
            "part{0}.lodgement_id".format(part_id): lodgement_choices,
            "lodgement{0}.group_id".format(part_id): lodgement_group_choices,
        })
        if not fixed_gettext:
            # Lodgement fields value -> description
            choices.update({
                f"lodgement{part_id}.xfield_{field['field_name']}":
                    collections.OrderedDict(field['entries'])
                for field in lodge_fields.values() if field['entries']
            })
    for track_id, track in tracks.items():
        choices.update({
            # Course choices for the JS selector
            "track{0}.course_id".format(track_id): course_choices,
            "track{0}.course_instructor".format(track_id): course_choices,
        })
        for i in range(track['num_choices']):
            choices[f"course_choices{track_id}.rank{i}"] = course_choices
        if track['num_choices'] > 1:
            choices[",".join(
                f"course_choices{track_id}.rank{i}"
                for i in range(track['num_choices']))] = course_choices
        if not fixed_gettext:
            # Course fields value -> description
            for temp in ("course", "course_instructor"):
                for field in course_fields.values():
                    key = f"{temp}{track_id}.xfield_{field['field_name']}"
                    if field['entries']:
                        choices[key] = collections.OrderedDict(field['entries'])
    if len(event['parts']) > 1:
        choices.update({
            # RegistrationPartStati enum
            ",".join(f"part{part_id}.status" for part_id in event['parts']):
                reg_part_stati_choices,
            ",".join(f"part{part_id}.lodgement_id" for part_id in event['parts']):
                lodgement_choices,
            ",".join(f"lodgement{part_id}.group_id" for part_id in event['parts']):
                lodgement_group_choices,
        })
    if len(tracks) > 1:
        choices[",".join(f"course_choices{track_id}.rank{i}"
                for track_id, track in tracks.items()
                for i in range(track['num_choices']))] = course_choices
    if not fixed_gettext:
        # Registration fields value -> description
        choices.update({
            "reg_fields.xfield_{}".format(field['field_name']):
                collections.OrderedDict(field['entries'])
            for field in reg_fields.values() if field['entries']
        })

    # Second we construct the titles
    titles: Dict[str, str] = {
        "reg_fields.xfield_{}".format(field['field_name']):
            field['field_name']
        for field in reg_fields.values()
    }
    for track_id, track in tracks.items():
        if len(tracks) > 1:
            prefix = "{shortname}: ".format(shortname=track['shortname'])
        else:
            prefix = ""
        titles.update({
            "track{0}.is_course_instructor".format(track_id):
                prefix + gettext("instructs their course"),
            "track{0}.course_id".format(track_id):
                prefix + gettext("course"),
            "track{0}.course_instructor".format(track_id):
                prefix + gettext("instructed course"),
            "course{0}.id".format(track_id):
                prefix + gettext("course ID"),
            "course{0}.nr".format(track_id):
                prefix + gettext("course nr"),
            "course{0}.title".format(track_id):
                prefix + gettext("course title"),
            "course{0}.shortname".format(track_id):
                prefix + gettext("course shortname"),
            "course{0}.notes".format(track_id):
                prefix + gettext("course notes"),
            "course_instructor{0}.id".format(track_id):
                prefix + gettext("instructed course ID"),
            "course_instructor{0}.nr".format(track_id):
                prefix + gettext("instructed course nr"),
            "course_instructor{0}.title".format(track_id):
                prefix + gettext("instructed course title"),
            "course_instructor{0}.shortname".format(track_id):
                prefix + gettext("instructed course shortname"),
            "course_instructor{0}.notes".format(track_id):
                prefix + gettext("instructed courese notes"),
        })
        titles.update({
            f"course{track_id}.xfield_{field['field_name']}":
                prefix + gettext("course {field}").format(field=field['field_name'])
            for field in course_fields.values()
        })
        titles.update({
            f"course_instructor{track_id}.xfield_{field['field_name']}":
                prefix + gettext("instructed course {field}").format(
                    field=field['field_name'])
            for field in course_fields.values()
        })
        for i in range(track['num_choices']):
            titles[f"course_choices{track_id}.rank{i}"] = \
                prefix + gettext("%s. Choice") % (i + 1)
        if track['num_choices'] > 1:
            titles[",".join(f"course_choices{track_id}.rank{i}"
                            for i in range(track['num_choices']))] = \
                prefix + gettext("Any Choice")
    if len(event['tracks']) > 1:
        prefix = gettext("any track: ")
        titles.update({
            ",".join(f"track{track_id}.is_course_instructor" for track_id in tracks):
                prefix + gettext("instructs their course"),
            ",".join(f"track{track_id}.course_id" for track_id in tracks):
                prefix + gettext("course"),
            ",".join(f"track{track_id}.course_instructor" for track_id in tracks):
                prefix + gettext("instructed course"),
            ",".join(f"course{track_id}.id" for track_id in tracks):
                prefix + gettext("course ID"),
            ",".join(f"course{track_id}.nr" for track_id in tracks):
                prefix + gettext("course nr"),
            ",".join(f"course{track_id}.title" for track_id in tracks):
                prefix + gettext("course title"),
            ",".join(f"course{track_id}.shortname" for track_id in tracks):
                prefix + gettext("course shortname"),
            ",".join(f"course{track_id}.notes" for track_id in tracks):
                prefix + gettext("course notes"),
            ",".join(f"course_instructor{track_id}.id" for track_id in tracks):
                prefix + gettext("instructed course ID"),
            ",".join(f"course_instructor{track_id}.nr" for track_id in tracks):
                prefix + gettext("instructed course nr"),
            ",".join(f"course_instructor{track_id}.title" for track_id in tracks):
                prefix + gettext("instructed course title"),
            ",".join(f"course_instructor{track_id}.shortname" for track_id in tracks):
                prefix + gettext("instructed course shortname"),
            ",".join(f"course_instructor{track_id}.notes" for track_id in tracks):
                prefix + gettext("instructed course notes"),
        })
        key = "course{0}.xfield_{1}"
        titles.update({
            ",".join(key.format(track_id, field['field_name'])
                     for track_id in tracks):
                gettext("any track: course {field}").format(
                    field=field['field_name'])
            for field in course_fields.values()
        })
        key = "course_instructor{0}.xfield_{1}"
        titles.update({
            ",".join(key.format(track_id, field['field_name'])
                     for track_id in tracks):
                gettext("any track: instructed course {field}").format(
                    field=field['field_name'])
            for field in course_fields.values()
        })
        key = ",".join(f"course_choices{track_id}.rank{i}"
                       for track_id, track in tracks.items()
                       for i in range(track['num_choices']))
        titles[key] = gettext("any track: Any Choice")
    for part_id, part in event['parts'].items():
        if len(event['parts']) > 1:
            prefix = "{shortname}: ".format(shortname=part['shortname'])
        else:
            prefix = ""
        titles.update({
            "part{0}.status".format(part_id):
                prefix + gettext("registration status"),
            "part{0}.is_camping_mat".format(part_id):
                prefix + gettext("camping mat user"),
            "part{0}.lodgement_id".format(part_id):
                prefix + gettext("lodgement"),
            "lodgement{0}.id".format(part_id):
                prefix + gettext("lodgement ID"),
            "lodgement{0}.group_id".format(part_id):
                prefix + gettext("lodgement group"),
            "lodgement{0}.title".format(part_id):
                prefix + gettext("lodgement title"),
            "lodgement{0}.notes".format(part_id):
                prefix + gettext("lodgement notes"),
            "lodgement_group{0}.id".format(part_id):
                prefix + gettext("lodgement group ID"),
            "lodgement_group{0}.title".format(part_id):
                prefix + gettext("lodgement group title"),
        })
        titles.update({
            f"lodgement{part_id}.xfield_{field['field_name']}":
                prefix + gettext("lodgement {field}").format(field=field['field_name'])
            for field in lodge_fields.values()
        })
    if len(event['parts']) > 1:
        prefix = gettext("any part: ")
        titles.update({
            ",".join(f"part{part_id}.status" for part_id in event['parts']):
                prefix + gettext("registration status"),
            ",".join(f"part{part_id}.is_camping_mat" for part_id in event['parts']):
                prefix + gettext("camping mat user"),
            ",".join(f"part{part_id}.lodgement_id" for part_id in event['parts']):
                prefix + gettext("lodgement"),
            ",".join(f"lodgement{part_id}.id" for part_id in event['parts']):
                prefix + gettext("lodgement ID"),
            ",".join(f"lodgement{part_id}.group_id" for part_id in event['parts']):
                prefix + gettext("lodgement group"),
            ",".join(f"lodgement{part_id}.title" for part_id in event['parts']):
                prefix + gettext("lodgement title"),
            ",".join(f"lodgement{part_id}.notes" for part_id in event['parts']):
                prefix + gettext("lodgement notes"),
            ",".join(f"lodgement_group{part_id}.id" for part_id in event['parts']):
                prefix + gettext("lodgement group ID"),
            ",".join(f"lodgement_group{part_id}.title" for part_id in event['parts']):
                prefix + gettext("lodgement group title"),
        })
        titles.update({
            ",".join(f"lodgement{part_id}.xfield_{field['field_name']}"
                     for part_id in event['parts']):
                prefix + gettext("lodgement {field}").format(field=field['field_name'])
            for field in lodge_fields.values()
        })
    return choices, titles


def make_course_query_spec(event: CdEDBObject) -> Dict[str, str]:
    """Helper to generate ``QueryScope.event_course``'s spec.

    Since each event has custom course fields we have to amend the query
    spec on the fly.
    """
    tracks = event['tracks']
    course_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.course
    }

    # This is an OrderedDict, so order should be respected.
    spec = collections.OrderedDict([
                    ("course.id", "id"),
                    ("course.course_id", "id"),
                    ("course.nr", "str"),
                    ("course.title", "str"),
                    ("course.description", "str"),
                    ("course.shortname", "str"),
                    ("course.instructors", "str"),
                    ("course.min_size", "int"),
                    ("course.max_size", "int"),
                    ("course.notes", "str"),
                    # This will be augmented with additional fields in the fly.
                ])

    for track_id, track in tracks.items():
        spec["track{0}.is_offered".format(track_id)] = "bool"
        spec["track{0}.takes_place".format(track_id)] = "bool"
        spec["track{0}.attendees".format(track_id)] = "int"
        spec["track{0}.instructors".format(track_id)] = "int"
        for rank in range(track['num_choices']):
            spec["track{0}.num_choices{1}".format(track_id, rank)] = "int"

    if len(tracks) > 1:
        spec[",".join(f"track{track_id}.is_offered" for track_id in tracks)] = "bool"
        spec[",".join(f"track{track_id}.takes_place" for track_id in tracks)] = "bool"
        spec[",".join(f"track{track_id}.attendees" for track_id in tracks)] = "int"
        spec[",".join(f"track{track_id}.instructors" for track_id in tracks)] = "int"

    spec.update({
        f"course_fields.xfield_{field['field_name']}":
            const.FieldDatatypes(field['kind']).name
        for field in course_fields.values()
    })

    return spec


# TODO specify return type as OrderedDict.
def make_course_query_aux(rs: RequestState, event: CdEDBObject,
                          courses: CdEDBObjectMap,
                          fixed_gettext: bool = False
                          ) -> Tuple[Dict[str, Dict[int, str]],
                                     Dict[str, str]]:
    """Un-inlined code to prepare input for template.

    :param fixed_gettext: whether or not to use a fixed translation
        function. True means static, False means localized.
    :returns: Choices for select inputs and titles for columns.
    """

    tracks = event['tracks']
    gettext = rs.default_gettext if fixed_gettext else rs.gettext

    # Construct choices.
    course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
    course_choices = collections.OrderedDict(
        xsorted((c["id"], course_identifier(c)) for c in courses.values()))
    choices: Dict[str, Dict[int, str]] = {
        "course.course_id": course_choices
    }
    course_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.course
        }
    if not fixed_gettext:
        # Course fields value -> description
        choices.update({
            "course_fields.xfield_{0}".format(field['field_name']):
                collections.OrderedDict(field['entries'])
            for field in course_fields.values() if field['entries']
        })

    # Construct titles.
    titles: Dict[str, str] = {
        "course.id": gettext("course id"),
        "course.course_id": gettext("course"),
        "course.nr": gettext("course nr"),
        "course.title": gettext("course title"),
        "course.description": gettext("course description"),
        "course.shortname": gettext("course shortname"),
        "course.instructors": gettext("course instructors"),
        "course.min_size": gettext("course min size"),
        "course.max_size": gettext("course max size"),
        "course.notes": gettext("course notes"),
    }

    for track_id, track in tracks.items():
        if len(tracks) > 1:
            prefix = "{shortname}: ".format(shortname=track['shortname'])
        else:
            prefix = ""
        titles.update({
            "track{0}.takes_place".format(track_id):
                prefix + gettext("takes place"),
            "track{0}.is_offered".format(track_id):
                prefix + gettext("is offered"),
            "track{0}.attendees".format(track_id):
                prefix + gettext("attendees"),
            "track{0}.instructors".format(track_id):
                prefix + gettext("instructors"),
        })
        for rank in range(track['num_choices']):
            titles.update({
                "track{0}.num_choices{1}".format(track_id, rank):
                    prefix + gettext("{}. choices").format(
                        rank+1),
            })
    if len(tracks) > 1:
        prefix = gettext("any track: ")
        titles.update({
            ",".join(f"track{track_id}.takes_place" for track_id in tracks):
                prefix + gettext("takes place"),
            ",".join(f"track{track_id}.is_offered" for track_id in tracks):
                prefix + gettext("is offered"),
            ",".join(f"track{track_id}.attendees" for track_id in tracks):
                prefix + gettext("attendees"),
            ",".join(f"track{track_id}.instructors" for track_id in tracks):
                prefix + gettext("instructors")
        })

    titles.update({
        f"course_fields.xfield_{field['field_name']}": field['field_name']
        for field in course_fields.values()
    })

    return choices, titles


def make_lodgement_query_spec(event: CdEDBObject) -> Dict[str, str]:
    parts = event["parts"]
    lodgement_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.lodgement
    }

    # This is an OrderedDcit, so order should be respected.
    spec = collections.OrderedDict([
                    ("lodgement.id", "id"),
                    ("lodgement.lodgement_id", "id"),
                    ("lodgement.title", "str"),
                    ("lodgement.regular_capacity", "int"),
                    ("lodgement.camping_mat_capacity", "int"),
                    ("lodgement.notes", "str"),
                    ("lodgement.group_id", "int"),
                    ("lodgement_group.title", "int"),
                    # This will be augmented with additional fields in the fly.
                ])

    for part_id, part in parts.items():
        spec[f"part{part_id}.regular_inhabitants"] = "int"
        spec[f"part{part_id}.camping_mat_inhabitants"] = "int"
        spec[f"part{part_id}.total_inhabitants"] = "int"
        spec[f"part{part_id}.group_regular_inhabitants"] = "int"
        spec[f"part{part_id}.group_camping_mat_inhabitants"] = "int"
        spec[f"part{part_id}.group_total_inhabitants"] = "int"

    if len(parts) > 1:
        spec[",".join(f"part{part_id}.regular_inhabitants"
                      for part_id in parts)] = "int"
        spec[",".join(f"part{part_id}.camping_mat_inhabitants"
                      for part_id in parts)] = "int"
        spec[",".join(f"part{part_id}.total_inhabitants"
                      for part_id in parts)] = "int"
        spec[",".join(f"part{part_id}.group_regular_inhabitants"
                      for part_id in parts)] = "int"
        spec[",".join(f"part{part_id}.group_camping_mat_inhabitants"
                      for part_id in parts)] = "int"
        spec[",".join(f"part{part_id}.group_total_inhabitants"
                      for part_id in parts)] = "int"

    spec.update({
        f"lodgement_fields.xfield_{field['field_name']}":
            const.FieldDatatypes(field['kind']).name
        for field in lodgement_fields.values()
    })

    return spec


def make_lodgement_query_aux(rs: RequestState, event: CdEDBObject,
                             lodgements: CdEDBObjectMap,
                             lodgement_groups: CdEDBObjectMap,
                             fixed_gettext: bool = False
                             ) -> Tuple[Dict[str, Dict[int, str]],
                                        Dict[str, str]]:
    """Un-inlined code to prepare input for template.

    :param fixed_gettext: whether or not to use a fixed translation
        function. True means static, False means localized.
    :returns: Choices for select inputs and titles for columns.
    """

    parts = event['parts']
    gettext = rs.default_gettext if fixed_gettext else rs.gettext

    # Construct choices.
    lodgement_choices = collections.OrderedDict(
        (l_id, l['title'])
        for l_id, l in keydictsort_filter(lodgements,
                                          EntitySorter.lodgement))
    lodgement_group_choices = collections.OrderedDict({-1: gettext(n_("--no group--"))})
    lodgement_group_choices.update(
        [(lg_id, lg['title']) for lg_id, lg in keydictsort_filter(
            lodgement_groups, EntitySorter.lodgement_group)])
    choices: Dict[str, Dict[int, str]] = {
        "lodgement.lodgement_id": lodgement_choices,
        "lodgement_group.id": lodgement_group_choices,
    }
    lodgement_fields = {
        field_id: field for field_id, field in event['fields'].items()
        if field['association'] == const.FieldAssociations.lodgement
    }
    if not fixed_gettext:
        # Lodgement fields value -> description
        choices.update({
            f"lodgement_fields.xfield_{field['field_name']}":
                collections.OrderedDict(field['entries'])
            for field in lodgement_fields.values() if field['entries']
        })

    # Construct titles.
    titles: Dict[str, str] = {
        "lodgement.id": gettext(n_("Lodgement ID")),
        "lodgement.lodgement_id": gettext(n_("Lodgement")),
        "lodgement.title": gettext(n_("Title_[[name of an entity]]")),
        "lodgement.regular_capacity": gettext(n_("Regular Capacity")),
        "lodgement.camping_mat_capacity":
            gettext(n_("Camping Mat Capacity")),
        "lodgement.notes": gettext(n_("Lodgement Notes")),
        "lodgement.group_id": gettext(n_("Lodgement Group ID")),
        "lodgement_group.tmp_id": gettext(n_("Lodgement Group")),
        "lodgement_group.title": gettext(n_("Lodgement Group Title")),
        "lodgement_group.regular_capacity":
            gettext(n_("Lodgement Group Regular Capacity")),
        "lodgement_group.camping_mat_capacity":
            gettext(n_("Lodgement Group Camping Mat Capacity")),
    }

    for part_id, part in parts.items():
        if len(parts) > 1:
            prefix = f"{part['shortname']}: "
        else:
            prefix = ""
        titles.update({
            f"part{part_id}.regular_inhabitants":
                prefix + gettext(n_("Regular Inhabitants")),
            f"part{part_id}.camping_mat_inhabitants":
                prefix + gettext(n_("Reserve Inhabitants")),
            f"part{part_id}.total_inhabitants":
                prefix + gettext(n_("Total Inhabitants")),
            f"part{part_id}.group_regular_inhabitants":
                prefix + gettext(n_("Group Regular Inhabitants")),
            f"part{part_id}.group_camping_mat_inhabitants":
                prefix + gettext(n_("Group Reserve Inhabitants")),
            f"part{part_id}.group_total_inhabitants":
                prefix + gettext(n_("Group Total Inhabitants")),
        })

    if len(parts) > 1:
        prefix = gettext("any part: ")
        titles.update({
            ",".join(f"part{part_id}.regular_inhabitants" for part_id in parts):
                prefix + gettext(n_("Regular Inhabitants")),
            ",".join(f"part{part_id}.camping_mat_inhabitants" for part_id in parts):
                prefix + gettext(n_("Reserve Inhabitants")),
            ",".join(f"part{part_id}.total_inhabitants" for part_id in parts):
                prefix + gettext(n_("Total Inhabitants")),
            ",".join(f"part{part_id}.group_regular_inhabitants" for part_id in parts):
                prefix + gettext(n_("Group Regular Inhabitants")),
            ",".join(f"part{part_id}.group_camping_mat_inhabitants"
                     for part_id in parts):
                prefix + gettext(n_("Group Reserve Inhabitants")),
            ",".join(f"part{part_id}.group_total_inhabitants" for part_id in parts):
                prefix + gettext(n_("Group Total Inhabitants")),
        })

    titles.update({
        f"lodgement_fields.xfield_{field['field_name']}": field['field_name']
        for field in lodgement_fields.values()
    })

    return choices, titles
