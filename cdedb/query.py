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
import itertools
import re
from typing import (
    Any, Callable, Collection, Dict, List, Mapping, NamedTuple, Optional, Tuple, Union,
)

import cdedb.database.constants as const
from cdedb.common import (
    ADMIN_KEYS, CdEDBObject, CdEDBObjectMap, EntitySorter, RequestState, n_, xsorted,
)
from cdedb.filter import keydictsort_filter


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


# A query constraint translates to (part of) a WHERE clause. All constraints are
# conjugated.
QueryConstraint = Tuple[str, QueryOperators, Any]
# A query order translate to an ORDER BY clause. The bool decides whether the sorting
# is ASC (i.e. True -> ASC, False -> DESC).
QueryOrder = Tuple[str, bool]

QueryChoices = Mapping[Union[int, str, enum.Enum], str]


class QuerySpecEntry(NamedTuple):
    type: str
    title_base: str
    title_prefix: str = ""
    title_params: Dict[str, str] = {}
    choices: QueryChoices = {}

    def get_title(self, gettext: Callable[[str], str]) -> str:
        ret_prefix = gettext(f"{self.title_prefix}: ") if self.title_prefix else ""
        ret_title = gettext(self.title_base).format(**self.title_params)
        return ret_prefix + ret_title

    def replace_choices(self, choices: QueryChoices) -> "QuerySpecEntry":
        return self.__class__(
            type=self.type,
            title_base=self.title_base,
            title_prefix=self.title_prefix,
            title_params=self.title_params,
            choices=choices,
        )


QuerySpec = Dict[str, QuerySpecEntry]


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

    def get_spec(self, *, event: CdEDBObject = None, courses: CdEDBObjectMap = None,
                 lodgements: CdEDBObjectMap = None,
                 lodgement_groups: CdEDBObjectMap = None) -> QuerySpec:
        """Return the query spec for this scope.

        These may be enriched by ext-fields. Order is important for UI purposes.

        Note that for schema specified columns (like ``personas.id``) the schema
        part does not survive querying and needs to be stripped before output.

        :param event: For some scopes, the spec is dependent on specific event data.
            For these scopes (see `event_spec_map` below) this must be provided.
            The format should be like the return of `EventBackend.get_event()`.
        :param courses: Same as `event`.
        :param lodgements: Same as `event`.
        :param lodgement_groups: Same as `event`.
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
            return event_spec_map[self](event, courses, lodgements, lodgement_groups)

        return copy.deepcopy(_QUERY_SPECS[self])

    def supports_storing(self) -> bool:
        """Whether or not storing queries with this scope is supported."""
        return self in {QueryScope.registration, QueryScope.lodgement,
                        QueryScope.event_course}

    def get_target(self, *, redirect: bool = True) -> str:
        """For scopes that support storing, where to redirect to after storing."""
        if self == QueryScope.registration:
            realm, target = "event", "registration_query"
        elif self == QueryScope.lodgement:
            realm, target = "event", "lodgement_query"
        elif self == QueryScope.event_course:
            realm, target = "event", "course_query"
        else:
            realm, target = "", ""
        return f"{realm if redirect else 'query'}/{target}"

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
    QueryScope.persona:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "gender": QuerySpecEntry("int", n_("Gender")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_ml_realm": QuerySpecEntry("bool", n_("Mailinglists"), n_("Realm")),
            "is_event_realm": QuerySpecEntry("bool", n_("Events"), n_("Realm")),
            "is_assembly_realm": QuerySpecEntry("bool", n_("Assemblies"), n_("Realm")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "is_member": QuerySpecEntry("bool", n_("CdE-Member")),
            "is_searchable": QuerySpecEntry("bool", n_("Searchable")),
            **{
                k: QuerySpecEntry("bool", k, n_("Admin"))
                for k in ADMIN_KEYS
            },
            ",".join(ADMIN_KEYS): QuerySpecEntry("bool", n_("Any"), n_("Admin")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
            "fulltext": QuerySpecEntry("str", n_("Fulltext")),
        },
    QueryScope.cde_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
            "name_supplement": QuerySpecEntry("str", n_("Name Affix")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "gender": QuerySpecEntry("int", n_("Gender")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "telephone": QuerySpecEntry("str", n_("Phone")),
            "mobile": QuerySpecEntry("str", n_("Mobile Phone")),
            "address": QuerySpecEntry("str", n_("Address")),
            "address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
            "postal_code": QuerySpecEntry("str", n_("ZIP")),
            "location": QuerySpecEntry("str", n_("City")),
            "country": QuerySpecEntry("str", n_("Country")),
            "address2": QuerySpecEntry("str", n_("Address (2)")),
            "address_supplement2": QuerySpecEntry("str", n_("Address Supplement (2)")),
            "postal_code2": QuerySpecEntry("str", n_("ZIP (2)")),
            "location2": QuerySpecEntry("str", n_("City (2)")),
            "country2": QuerySpecEntry("str", n_("Country (2)")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_member": QuerySpecEntry("bool", n_("CdE-Member")),
            "trial_member": QuerySpecEntry("bool", n_("Trial Member")),
            "paper_expuls": QuerySpecEntry("bool", n_("Printed exPuls")),
            "is_searchable": QuerySpecEntry("bool", n_("Searchable")),
            "decided_search": QuerySpecEntry("bool", n_("Searchability Decided")),
            "balance": QuerySpecEntry("float", n_("Membership-Fee Balance")),
            **{
                k: QuerySpecEntry("bool", k, n_("Admin"))
                for k in ADMIN_KEYS
            },
            ",".join(ADMIN_KEYS): QuerySpecEntry("bool", n_("Any"), n_("Admin")),
            "weblink": QuerySpecEntry("str", n_("WWW")),
            "specialisation": QuerySpecEntry("str", n_("Specialisation")),
            "affiliation": QuerySpecEntry("str", n_("School, University, …")),
            "timeline": QuerySpecEntry("str", n_("Year(s) of Graduation")),
            "interests": QuerySpecEntry("str", n_("Interests")),
            "free_form": QuerySpecEntry("str", n_("Miscellaneous")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "lastschrift.granted_at": QuerySpecEntry(
                "datetime", n_("Lastschrift Granted")),
            "lastschrift.revoked_at": QuerySpecEntry(
                "datetime", n_("Lastschrift Revoked")),
            "lastschrift.active_lastschrift": QuerySpecEntry(
                "bool", n_("Active Lastschrift")),
            "lastschrift.amount": QuerySpecEntry("float", n_("Lastschrift Amount")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.event_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
            "name_supplement": QuerySpecEntry("str", n_("Name Affix")),
            "gender": QuerySpecEntry("int", n_("Gender")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "telephone": QuerySpecEntry("str", n_("Phone")),
            "mobile": QuerySpecEntry("str", n_("Mobile Phone")),
            "address": QuerySpecEntry("str", n_("Address")),
            "address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
            "postal_code": QuerySpecEntry("str", n_("ZIP")),
            "location": QuerySpecEntry("str", n_("City")),
            "country": QuerySpecEntry("str", n_("Country")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_member": QuerySpecEntry("bool", n_("CdE-Member")),
            "is_searchable": QuerySpecEntry("bool", n_("Searchable")),
            **{
                k: QuerySpecEntry("bool", k, n_("Admin"))
                for k in ADMIN_KEYS
            },
            ",".join(ADMIN_KEYS): QuerySpecEntry("bool", n_("Any"), n_("Admin")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.past_event_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
            "name_supplement": QuerySpecEntry("str", n_("Name Affix")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "telephone": QuerySpecEntry("str", n_("Phone")),
            "mobile": QuerySpecEntry("str", n_("Mobile Phone")),
            "address": QuerySpecEntry("str", n_("Address")),
            "address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
            "postal_code": QuerySpecEntry("str", n_("ZIP")),
            "location": QuerySpecEntry("str", n_("City")),
            "country": QuerySpecEntry("str", n_("Country")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.archived_persona:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "gender": QuerySpecEntry("int", n_("Gender")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "is_ml_realm": QuerySpecEntry("bool", n_("Mailinglists"), n_("Realm")),
            "is_event_realm": QuerySpecEntry("bool", n_("Events"), n_("Realm")),
            "is_assembly_realm": QuerySpecEntry("bool", n_("Assemblies"), n_("Realm")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.archived_core_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "is_ml_realm": QuerySpecEntry("bool", n_("Mailinglists"), n_("Realm")),
            "is_event_realm": QuerySpecEntry("bool", n_("Events"), n_("Realm")),
            "is_assembly_realm": QuerySpecEntry("bool", n_("Assemblies"), n_("Realm")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.archived_past_event_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "notes": QuerySpecEntry("str", n_("Admin-Notes")),
        },
    QueryScope.cde_member:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names,display_name": QuerySpecEntry("str", n_("Given Names")),
            "family_name,birth_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "address,address_supplement,address2,address_supplement2":
                QuerySpecEntry("str", n_("Address")),
            "postal_code,postal_code2": QuerySpecEntry("str", n_("ZIP")),
            "location,location2": QuerySpecEntry("str", n_("City")),
            "country,country2": QuerySpecEntry("str", n_("Country")),
            "telephone,mobile": QuerySpecEntry("str", n_("Phone")),
            "weblink,specialisation,affiliation,timeline,interests,free_form":
                QuerySpecEntry("str", n_("Interests")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "fulltext": QuerySpecEntry("str", n_("Fulltext")),
        },
    QueryScope.quick_registration:
        {
            "registrations.id": QuerySpecEntry("id", n_("registration ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
            "name_supplement": QuerySpecEntry("str", n_("Name Affix")),
        },
    QueryScope.past_event_course:
        {
            "courses.id": QuerySpecEntry("id", n_("course ID")),
            "courses.pcourse_id": QuerySpecEntry("id", n_("course")),
            "courses.pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "courses.nr": QuerySpecEntry("str", n_("course nr")),
            "courses.title": QuerySpecEntry("str", n_("course title")),
            "courses.description": QuerySpecEntry("str", n_("course description")),
            "events.title": QuerySpecEntry(
                "str", n_("Title_[[name of an entity]"), n_("Past Event")),
            "events.tempus": QuerySpecEntry("date", n_("tempus"), n_("Past Event")),
        },
}
_QUERY_SPECS[QueryScope.core_user] = _QUERY_SPECS[QueryScope.persona]
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
        if self.spec[field].type == "date":
            return QueryResultEntryFormat.date
        if self.spec[field].type == "datetime":
            return QueryResultEntryFormat.datetime
        if self.spec[field].type == "bool":
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


def _sort_event_fields(fields: CdEDBObjectMap
                       ) -> Dict[const.FieldAssociations, List[CdEDBObject]]:
    """Helper to sort event fields and group them by association."""
    sorted_fields: Dict[const.FieldAssociations, List[CdEDBObject]] = {
        association: [] for association in const.FieldAssociations}
    for field in xsorted(fields.values(), key=EntitySorter.event_field):
        sorted_fields[field['association']].append(field)
    return sorted_fields


def _combine_specs(spec_map: Dict[int, QuerySpec], entity_ids: Collection[int],
                   prefix: str) -> QuerySpec:
    """Helper to create combined spec entries for specified entities.

    Entries are grouped by their position in the individual spec. Thus the individual
    specs need to be ordered in the same way. They need not have the same length.
    If the spec for one entity is shorter, that entity will simple be ignored when
    creating the combinations.
    """
    ret: QuerySpec = {}
    entity_ids = xsorted(entity_ids)
    if len(entity_ids) <= 1:
        return ret

    # Choose the "longest" spec to serve as a reference.
    reference_spec = max(spec_map.values(), key=len)

    # Create a two dimensional grid of spec keys. First dimension are the given entites,
    # second dimension are the keys.
    all_keys = tuple(tuple(spec_map[id_].keys()) for id_ in entity_ids)
    for i, k in enumerate(reference_spec):
        # Exclude keys that are not present in all specs.
        relevant_keys = tuple(keys[i] for keys in all_keys if len(keys) > i)
        # Do not combine entries consisting of only one key.
        if len(relevant_keys) <= 1:
            continue
        key = ",".join(relevant_keys)
        entry = reference_spec[k]
        ret[key] = QuerySpecEntry(
            type=entry.type, title_base=entry.title_base, title_prefix=prefix,
            title_params=entry.title_params, choices=entry.choices,
        )
    return ret


def _get_course_choices(courses: Optional[CdEDBObjectMap]) -> QueryChoices:
    if courses is None:
        return {}
    course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
    return dict((c_id, course_identifier(c))
                for c_id, c in keydictsort_filter(courses, EntitySorter.course))


def _get_lodgement_choices(lodgements: Optional[CdEDBObjectMap]) -> QueryChoices:
    if lodgements is None:
        return {}
    lodge_identifier = lambda l: l["title"]
    return dict(
        (l_id, lodge_identifier(l))
        for l_id, l in keydictsort_filter(lodgements, EntitySorter.lodgement))


def _get_lodgement_group_choices(lodgement_groups: Optional[CdEDBObjectMap]
                                 ) -> QueryChoices:
    if lodgement_groups is None:
        return {}
    lodgement_group_identifier = lambda g: g["title"]
    return dict(
        (g_id, lodgement_group_identifier(g))
        for g_id, g in keydictsort_filter(
            lodgement_groups, EntitySorter.lodgement_group))


def make_registration_query_spec(event: CdEDBObject, courses: CdEDBObjectMap = None,
                                 lodgements: CdEDBObjectMap = None,
                                 lodgement_groups: CdEDBObjectMap = None) -> QuerySpec:
    """Helper to generate ``QueryScope.registration``'s spec.

    Since each event has dynamic columns for parts and extra fields we
    have amend the query spec on the fly.
    """

    sorted_fields = _sort_event_fields(event['fields'])
    field_choices = {
        field['field_name']: dict(field['entries']) if field['entries'] else {}
        for field in event['fields'].values()
    }
    course_choices = _get_course_choices(courses)
    lodgement_choices = _get_lodgement_choices(lodgements)
    lodgement_group_choices = _get_lodgement_group_choices(lodgement_groups)
    spec: QuerySpec = {
        "reg.id": QuerySpecEntry("id", n_("ID")),
        "persona.id": QuerySpecEntry("id", n_("CdEDB-ID")),
        "persona.given_names": QuerySpecEntry("str", n_("Given Names")),
        "persona.family_name": QuerySpecEntry("str", n_("Family Name")),
        "persona.username": QuerySpecEntry("str", n_("E-Mail")),
        "persona.is_member": QuerySpecEntry("bool", n_("CdE-Member")),
        "persona.display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
        "persona.title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
        "persona.name_supplement": QuerySpecEntry("str", n_("Name Affix")),
        # Choices for the gender will be manually set when displaying the result.
        "persona.gender": QuerySpecEntry("int", n_("Gender"), choices=None),  # type: ignore[arg-type]
        "persona.birthday": QuerySpecEntry("date", n_("Birthday")),
        "persona.telephone": QuerySpecEntry("str", n_("Phone")),
        "persona.mobile": QuerySpecEntry("str", n_("Mobile Phone")),
        "persona.address": QuerySpecEntry("str", n_("Address")),
        "persona.address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
        "persona.postal_code": QuerySpecEntry("str", n_("ZIP")),
        "persona.location": QuerySpecEntry("str", n_("City")),
        # Choices for the country will be manually set when displaying the result.
        "persona.country": QuerySpecEntry("id", n_("Country"), choices=None),  # type: ignore[arg-type]
        "reg.payment": QuerySpecEntry("date", n_("Payment")),
        "reg.amount_paid": QuerySpecEntry("float", n_("Amount Paid")),
        "reg.amount_owed": QuerySpecEntry("float", n_("Amount Owed")),
        "reg.parental_agreement": QuerySpecEntry("bool", n_("Parental Consent")),
        "reg.mixed_lodging": QuerySpecEntry("bool", n_("Mixed Lodging")),
        "reg.list_consent": QuerySpecEntry("bool", n_("Participant List Consent")),
        "reg.notes": QuerySpecEntry("str", n_("Notes")),
        "reg.orga_notes": QuerySpecEntry("str", n_("Orga-Notes")),
        "reg.checkin": QuerySpecEntry("datetime", n_("Checkin")),
        "ctime.creation_time": QuerySpecEntry("datetime", n_("Registration Time")),
        "mtime.modification_time":
            QuerySpecEntry("datetime", n_("Last Modification Time")),
    }

    def get_part_spec(part: CdEDBObject) -> QuerySpec:
        part_id = part['id']
        prefix = "" if len(event['parts']) <= 1 else f"{part['shortname']}: "
        return {
            # Choices for the status will be manually set.
            f"part{part_id}.status": QuerySpecEntry(
                "int", n_("registration status"), prefix, choices=None),  # type: ignore[arg-type]
            f"part{part_id}.is_camping_mat": QuerySpecEntry(
                "bool", n_("camping mat user"), prefix),
            f"part{part_id}.lodgement_id": QuerySpecEntry(
                "id", n_("lodgement"), prefix, choices=lodgement_choices),
            f"lodgement{part_id}.id": QuerySpecEntry("id", n_("lodgement ID"), prefix),
            f"lodgement{part_id}.group_id": QuerySpecEntry(
                "id", n_("lodgement group"), prefix, choices=lodgement_group_choices),
            f"lodgement{part_id}.title": QuerySpecEntry(
                "str", n_("lodgement title"), prefix),
            f"lodgement{part_id}.notes": QuerySpecEntry(
                "str", n_("lodgement notes"), prefix),
            **{
                f"lodgement{part_id}.xfield_{f['field_name']}": QuerySpecEntry(
                    f['kind'].name, n_("lodgement {field}"), prefix,
                    {'field': f['field_name']})
                for f in sorted_fields[const.FieldAssociations.lodgement]
            },
            f"lodgement_group{part_id}.id": QuerySpecEntry(
                "id", n_("lodgement group ID"), prefix),
            f"lodgement_group{part_id}.title": QuerySpecEntry(
                "str", n_("lodgement group title"), prefix),
        }

    def get_track_spec(track: CdEDBObject) -> QuerySpec:
        track_id = track['id']
        prefix = "" if len(event['tracks']) <= 1 else f"{track['shortname']}: "
        return {
            f"track{track_id}.is_course_instructor": QuerySpecEntry(
                "bool", n_("instructs their course"), prefix),
            f"track{track_id}.course_id": QuerySpecEntry(
                "id", n_("course"), prefix, choices=course_choices),
            f"track{track_id}.course_instructor": QuerySpecEntry(
                "id", n_("instructed course"), prefix, choices=course_choices),
            f"course{track_id}.id": QuerySpecEntry("id", n_("course ID"), prefix),
            f"course{track_id}.nr": QuerySpecEntry("str", n_("course nr"), prefix),
            f"course{track_id}.title": QuerySpecEntry(
                "str", n_("course title"), prefix),
            f"course{track_id}.shortname": QuerySpecEntry(
                "str", n_("course shortname"), prefix),
            f"course{track_id}.notes": QuerySpecEntry(
                "str", n_("course notes"), prefix),
            **{
                f"course{track_id}.xfield_{f['field_name']}": QuerySpecEntry(
                    f['kind'].name, n_("course {field}"), prefix,
                    {'field': f['field_name']}, choices=field_choices[f['field_name']],
                )
                for f in sorted_fields[const.FieldAssociations.course]
            },
            f"course_instructor{track_id}.id": QuerySpecEntry(
                "id", n_("instructed course ID"), prefix),
            f"course_instructor{track_id}.nr": QuerySpecEntry(
                "str", n_("instructed course nr"), prefix),
            f"course_instructor{track_id}.title": QuerySpecEntry(
                "str", n_("instructed course title"), prefix),
            f"course_instructor{track_id}.shortname": QuerySpecEntry(
                "str", n_("instructed course shortname"), prefix),
            f"course_instructor{track_id}.notes": QuerySpecEntry(
                "str", n_("instructed course notes"), prefix),
            **{
                f"course_instructor{track_id}.xfield_{f['field_name']}": QuerySpecEntry(
                    f['kind'].name, n_("instructed course {field}"), prefix,
                    {'field': f['field_name']}, choices=field_choices[f['field_name']],
                )
                for f in sorted_fields[const.FieldAssociations.course]
            },
        }

    def get_course_choice_spec(track: CdEDBObject) -> QuerySpec:
        track_id = track['id']
        prefix = "" if len(event['tracks']) <= 1 else f"{track['shortname']}: "
        return {
            f"course_choices{track_id}.rank{i}": QuerySpecEntry(
                "id", n_("{rank}. Choice"), prefix, {'rank': str(i + 1)},
                choices=course_choices,
            )
            for i in range(track['num_choices'])
        }

    # Presort part specs, so we can iterate over them in order.
    part_specs = {
        part_id: get_part_spec(part)
        for part_id, part in keydictsort_filter(event['parts'], EntitySorter.event_part)
    }
    track_specs = {
        track_id: get_track_spec(track)
        for track_id, track in keydictsort_filter(
            event['tracks'], EntitySorter.course_track)
    }
    course_choice_specs = {
        track_id: get_course_choice_spec(track)
        for track_id, track in keydictsort_filter(
            event['tracks'], EntitySorter.course_track)
    }

    # Add entries for individual parts and tracks in those parts.
    for part_id, part_spec in part_specs.items():
        part = event['parts'][part_id]
        spec.update(part_spec)

        # Add entries for individual tracks.
        for track_id, track in keydictsort_filter(part['tracks'],
                                                  EntitySorter.course_track):
            spec.update(track_specs[track_id])

            course_choice_spec = course_choice_specs[track_id]
            # If there are course choices for the track, add an entry for any choice.
            if key := ",".join(course_choice_spec.keys()):
                # Don't overwrite a potential existing spec.
                # This happens if there is exactly one choice.
                if key not in course_choice_spec:
                    prefix = "" if len(event['tracks']) <= 1 else track['shortname']
                    spec[key] = QuerySpecEntry(
                        "id", n_("Any Choice"), prefix, choices=course_choices)
            spec.update(course_choice_spec)

        # Add Entries for all tracks in this part.
        spec.update(_combine_specs(
            track_specs, part['tracks'], prefix=part['shortname']))
        spec.update(_combine_specs(
            course_choice_specs, part['tracks'], prefix=part['shortname']))

    # Add entries for groups of parts and tracks in those parts.
    part_groups = (
        event['parts'].keys(),
    )
    for part_ids in part_groups:
        spec.update(_combine_specs(part_specs, part_ids, prefix=n_("any part")))
        # Add entries for track combinations.
        track_ids = tuple(itertools.chain.from_iterable(
            event['parts'][part_id]['tracks'].keys() for part_id in part_ids))
        spec.update(_combine_specs(
            track_specs, track_ids, prefix=n_("any track")))
        spec.update(_combine_specs(
            course_choice_specs, track_ids, prefix=n_("any track")))

    spec.update({
        f"reg_fields.xfield_{f['field_name']}": QuerySpecEntry(
            f['kind'].name, f['field_name'], choices=field_choices[f['field_name']])
        for f in sorted_fields[const.FieldAssociations.registration]
    })
    return spec


def make_course_query_spec(event: CdEDBObject, courses: CdEDBObjectMap = None,
                           lodgements: CdEDBObjectMap = None,
                           lodgement_groups: CdEDBObjectMap = None) -> QuerySpec:
    """Helper to generate ``QueryScope.event_course``'s spec.

    Since each event has custom course fields and an arbitrary number
    of course tracks we have to extend this spec on the fly.
    """
    sorted_tracks = keydictsort_filter(event['tracks'], EntitySorter.course_track)
    sorted_course_fields = _sort_event_fields(event['fields'])[
        const.FieldAssociations.course]
    field_choices = {
        field['field_name']: dict(field['entries']) if field['entries'] else {}
        for field in sorted_course_fields
    }

    course_choices = _get_course_choices(courses)

    spec = {
        "course.id": QuerySpecEntry("id", n_("course id")),
        "course.course_id": QuerySpecEntry("id", n_("course"), choices=course_choices),
        "course.nr": QuerySpecEntry("str", n_("course nr")),
        "course.title": QuerySpecEntry("str", n_("course title")),
        "course.description": QuerySpecEntry("str", n_("course description")),
        "course.shortname": QuerySpecEntry("str", n_("course shortname")),
        "course.instructors": QuerySpecEntry("str", n_("course instructors")),
        "course.min_size": QuerySpecEntry("int", n_("course min size")),
        "course.max_size": QuerySpecEntry("int", n_("course max size")),
        "course.notes": QuerySpecEntry("str", n_("course notes")),
        # This will be augmented with additional fields in the fly.
    }

    def get_track_spec(track: CdEDBObject) -> QuerySpec:
        track_id = track['id']
        prefix = "" if len(event['tracks']) <= 1 else f"{track['shortname']}: "
        return {
            f"track{track_id}.is_offered": QuerySpecEntry(
                "bool", n_("is offered"), prefix),
            f"track{track_id}.takes_place": QuerySpecEntry(
                "bool", n_("takes place"), prefix),
            f"track{track_id}.attendees": QuerySpecEntry(
                "int", n_("attendees"), prefix),
            f"track{track_id}.instructors": QuerySpecEntry(
                "int", n_("instructors"), prefix),
        }

    def get_course_choice_spec(track: CdEDBObject) -> QuerySpec:
        track_id = track['id']
        prefix = "" if len(event['tracks']) <= 1 else f"{track['shortname']}: "
        return {
            f"track{track_id}.num_choices{i}": QuerySpecEntry(
                "int", n_("{rank}. choices"), prefix, {'rank': str(i + 1)})
            for i in range(track['num_choices'])
        }

    track_specs = {
        track_id: get_track_spec(track)
        for track_id, track in sorted_tracks
    }
    course_choice_specs = {
        track_id: get_course_choice_spec(track)
        for track_id, track in sorted_tracks
    }
    # Add entries for individual tracks.
    for track_id, track_spec in track_specs.items():
        spec.update(track_spec)

        course_choice_spec = course_choice_specs[track_id]
        # If there are course choices for the track, add an entry for any choice.
        if key := ",".join(course_choice_spec.keys()):
            # Don't overwrite a potential existing spec.
            # This happens if there is exactly one choice.
            if key not in course_choice_spec:
                prefix = ("" if len(event['tracks']) <= 1
                          else event['tracks'][track_id]['shortname'])
                spec[key] = QuerySpecEntry("id", n_("Any Choice"), prefix)
        spec.update(course_choice_spec)

    # Add entries for groups of tracks.
    track_groups = (
        {'track_ids': event['tracks'].keys(), 'title': n_("any track")},
        *(
            {'track_ids': part['tracks'].keys(), 'title': part['shortname']}
            for part in event['parts'].values()
        ),
    )
    for track_group in track_groups:
        track_ids = track_group['track_ids']
        prefix = f"{track_group['title']}: "
        spec.update(_combine_specs(track_specs, track_ids, prefix))
        spec.update(_combine_specs(course_choice_specs, track_ids, prefix))

    spec.update({
        f"course_fields.xfield_{field['field_name']}": QuerySpecEntry(
            field['kind'].name, field['field_name'],
            choices=field_choices[field['field_name']])
        for field in sorted_course_fields
    })

    return spec


def make_lodgement_query_spec(event: CdEDBObject, courses: CdEDBObjectMap = None,
                              lodgements: CdEDBObjectMap = None,
                              lodgement_groups: CdEDBObjectMap = None) -> QuerySpec:
    """Helper to generate ``QueryScope.lodgement``'s spec.

    Since each event has custom lodgement fields and an arbitrary number
    of event parts, we have to expand this spec on the fly.
    """
    sorted_parts = keydictsort_filter(event['parts'], EntitySorter.event_part)
    sorted_lodgement_fields = _sort_event_fields(event['fields'])[
        const.FieldAssociations.lodgement]
    field_choices = {
        field['field_name']: dict(field['entries']) if field['entries'] else {}
        for field in sorted_lodgement_fields
    }
    lodgement_choices = _get_lodgement_choices(lodgements)
    lodgement_group_choices = _get_lodgement_group_choices(lodgement_groups)

    spec = {
        "lodgement.id": QuerySpecEntry("id", n_("lodgement ID")),
        "lodgement.lodgement_id": QuerySpecEntry(
            "id", n_("ldogement"), choices=lodgement_choices),
        "lodgement.title": QuerySpecEntry("str", n_("Title_[[name of an entity]]")),
        "lodgement.regular_capacity": QuerySpecEntry("int", n_("Regular Capacity")),
        "lodgement.camping_mat_capacity": QuerySpecEntry(
            "int", n_("Camping Mat Capacity")),
        "lodgement.notes": QuerySpecEntry("str", n_("Lodgement Notes")),
        "lodgement.group_id": QuerySpecEntry(
            "int", n_("Lodgement Group"), choices=lodgement_group_choices),
        "lodgement_group.id": QuerySpecEntry("int", n_("Lodgement Group ID")),
        "lodgement_group.title": QuerySpecEntry("int", n_("Lodgement Group Title")),
        # This will be augmented with additional fields in the fly.
    }

    def get_part_spec(part: CdEDBObject) -> QuerySpec:
        part_id = part['id']
        prefix = "" if len(event['parts']) <= 1 else f"{part['shortname']}: "
        return {
            f"part{part_id}.regular_inhabitants": QuerySpecEntry(
                "int", n_("Regular Inhabitants"), prefix),
            f"part{part_id}.camping_mat_inhabitants": QuerySpecEntry(
                "int", n_("Camping Mat Inhabitants"), prefix),
            f"part{part_id}.total_inhabitants": QuerySpecEntry(
                "int", n_("Total Inhabitants"), prefix),
            f"part{part_id}.group_regular_inhabitants": QuerySpecEntry(
                "int", n_("Group Regular Inhabitants"), prefix),
            f"part{part_id}.group_camping_mat_inhabitants": QuerySpecEntry(
                "int", n_("Group Camping Mat Inhabitants"), prefix),
            f"part{part_id}.group_total_inhabitants": QuerySpecEntry(
                "int", n_("Group Total Inhabitants"), prefix),
        }

    # Presort part specs so we can iterate over them in order.
    part_specs = {
        part_id: get_part_spec(part)
        for part_id, part in sorted_parts
    }

    # Add entries for individual parts.
    for part_id, part_spec in part_specs.items():
        spec.update(part_spec)

    # Add entries for groups of parts.
    part_groups = (
        event['parts'].keys(),
    )
    for part_ids in part_groups:
        spec.update(_combine_specs(part_specs, part_ids, prefix=n_("any part")))

    spec.update({
        f"lodgement_fields.xfield_{f['field_name']}": QuerySpecEntry(
            f['kind'].name, f['field_name'], choices=field_choices[f['field_name']])
        for f in sorted_lodgement_fields
    })

    return spec
