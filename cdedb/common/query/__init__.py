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
import dataclasses
import datetime
import enum
import itertools
import re
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Callable, NamedTuple, Optional, cast

from typing_extensions import TypeAlias

import cdedb.database.constants as const
from cdedb.common import CdEDBObject, RequestState
from cdedb.common.n_ import n_
from cdedb.common.roles import ADMIN_KEYS
from cdedb.common.sorting import xsorted
from cdedb.config import LazyConfig
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    import cdedb.models.event as models


_CONFIG = LazyConfig()

# The maximal number of sorting criteria that can be used for queries
MAX_QUERY_ORDERS = 20

CourseMap: TypeAlias = "models.CdEDataclassMap[models.Course]"
LodgementMap: TypeAlias = "models.CdEDataclassMap[models.Lodgement]"
LodgementGroupMap: TypeAlias = "models.CdEDataclassMap[models.LodgementGroup]"


@enum.unique
class QueryOperators(CdEIntEnum):
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
VALID_QUERY_OPERATORS: dict[str, tuple[QueryOperators, ...]] = {
    "str": (_ops.match, _ops.unmatch, _ops.equal, _ops.unequal,
            _ops.equalornull, _ops.unequalornull, _ops.containsall,
            _ops.containsnone, _ops.containssome, _ops.oneof, _ops.otherthan,
            _ops.regex, _ops.notregex, _ops.fuzzy, _ops.empty, _ops.nonempty,
            _ops.greater, _ops.greaterequal, _ops.less, _ops.lessequal,
            _ops.between, _ops.outside),
    "int": (_ops.equal, _ops.equalornull, _ops.unequal, _ops.unequalornull,
            _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal, _ops.between,
            _ops.outside, _ops.greaterequal, _ops.greater, _ops.empty, _ops.nonempty),
    "float": (_ops.equal, _ops.equalornull, _ops.unequal, _ops.unequalornull,
              _ops.less, _ops.lessequal, _ops.between, _ops.outside, _ops.greaterequal,
              _ops.greater, _ops.empty, _ops.nonempty),
    "date": (_ops.equal, _ops.unequal, _ops.equalornull, _ops.unequalornull,
             _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal, _ops.between,
             _ops.outside, _ops.greaterequal, _ops.greater, _ops.empty, _ops.nonempty),
    "datetime": (_ops.equal, _ops.unequal, _ops.equalornull, _ops.unequalornull,
                 _ops.oneof, _ops.otherthan, _ops.less, _ops.lessequal,
                 _ops.between, _ops.outside, _ops.greaterequal, _ops.greater,
                 _ops.empty, _ops.nonempty),
    "bool": (_ops.equal, _ops.equalornull, _ops.empty, _ops.nonempty),
}
VALID_QUERY_OPERATORS["id"] = VALID_QUERY_OPERATORS["int"]

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
QueryConstraint = tuple[str, QueryOperators, Any]


class QueryConstraintType(NamedTuple):
    field: str
    op: QueryOperators
    value: Any


# A query order translate to an ORDER BY clause. The bool decides whether the sorting
# is ASC (i.e. True -> ASC, False -> DESC).
QueryOrder = tuple[str, bool]

QueryChoices = Mapping[Any, str]

QUERY_VALUE_SEPARATOR = ","


@dataclasses.dataclass
class QuerySpecEntry:
    type: str
    title_base: str
    title_prefix: str = ""
    title_params: dict[str, str] = dataclasses.field(default_factory=dict)
    choices: QueryChoices = dataclasses.field(default_factory=dict)
    translate_prefix: bool = True

    # Mask gettext so pybabel doesn't try to extract the f-string.
    def get_title(self, g: Callable[[str], str]) -> str:
        ret = g(self.title_base).format(**self.title_params)
        if self.title_prefix:
            if self.translate_prefix:
                ret = f"{g(self.title_prefix)}: {ret}"
            else:
                ret = f"{self.title_prefix}: {ret}"
        return ret


QuerySpec = dict[str, QuerySpecEntry]


class QueryScope(CdEIntEnum):
    """Enum that contains the different kinds of generalized queries.

    This is used in conjunction with the `Query` class and bundles together a lot of
    constant and some dynamic things for the individual scopes.
    """
    realm: str
    includes_archived: bool

    def __new__(cls, value: int, realm: str = "core", includes_archived: bool = False,
                ) -> "QueryScope":
        """Custom creation method for this enum.

        Achieves that value and realm of new members can be written using tuple
        syntax. Realm defaults to "core".
        """
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.realm = realm
        obj.includes_archived = includes_archived
        return obj

    persona = 1
    core_user = 2
    assembly_user = 3, "assembly"
    cde_user = 4, "cde"
    event_user = 5, "event"
    ml_user = 6, "ml"
    past_event_user = 7, "cde"
    archived_persona = 10
    all_core_users = 11, "core", True
    all_assembly_users = 12, "assembly", True
    all_cde_users = 13, "cde", True
    all_event_users = 14, "event", True
    all_ml_users = 15, "ml", True
    cde_member = 20, "cde"
    registration = 30, "event"
    quick_registration = 31, "event"
    lodgement = 32, "event"
    event_course = 33, "event"
    past_event_course = 40, "cde"

    def get_view(self) -> str:
        """Return the SQL FROM target associated with this scope.

        Supstitute for SQL views. We cannot use SQL views since they do not allow
        multiple columns with the same name, but each join brings in an id column.
        """
        return _QUERY_VIEWS.get(self, "core.personas")

    def get_primary_key(self, short: bool = False) -> str:
        """Return the primary key of the view associated with the scope.

        This should always be selected, to avoid any pathologies.
        """
        ret = PRIMARY_KEYS.get(self, "personas.id")
        if short:
            return ret.split(".", 1)[1]
        return ret

    def get_spec(self, *, event: Optional["models.Event"] = None, courses: Optional[CourseMap] = None,
                 lodgements: Optional[LodgementMap] = None,
                 lodgement_groups: Optional[LodgementGroupMap] = None,
                 ) -> QuerySpec:
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
        prefix = ""
        if self == QueryScope.registration:
            prefix, target = "query", "registration_query"
        elif self == QueryScope.lodgement:
            prefix, target = "query", "lodgement_query"
        elif self == QueryScope.event_course:
            prefix, target = "query", "course_query"
        elif self in {QueryScope.event_user, QueryScope.all_event_users}:
            prefix, target = "user", "user_search"
        elif self in {QueryScope.assembly_user, QueryScope.all_assembly_users}:
            prefix, target = "base", "user_search"
        elif self in {QueryScope.core_user, QueryScope.all_core_users,
                      QueryScope.cde_user, QueryScope.all_cde_users,
                      QueryScope.ml_user, QueryScope.all_ml_users}:
            target = "user_search"
        else:
            prefix, target = "", ""
        if redirect and self.realm:
            return f"{self.realm}/{target}"
        elif prefix:
            return f"{prefix}/{target}"
        return target

    def mangle_query_input(self, rs: RequestState, defaults: Optional[CdEDBObject] = None,
                           ) -> dict[str, str]:
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
        for postfix in range(MAX_QUERY_ORDERS):
            name = f"qord_{postfix}"
            if name in rs.request.values:
                params[name] = rs.values[name] = rs.request.values[name]
                name = f"qord_{postfix}_ascending"
                if name in rs.request.values:
                    params[name] = rs.values[name] = rs.request.values[name]
        for key, value in defaults.items():
            if key not in params:
                params[key] = rs.values[key] = value
        return params


# See `QueryScope.get_view().
_QUERY_VIEWS = {
    QueryScope.cde_user: (_CDE_USER_VIEW := """core.personas
        LEFT OUTER JOIN past_event.participants
            ON personas.id = participants.persona_id
        LEFT OUTER JOIN (
            SELECT
                id, granted_at, revoked_at,
                revoked_at IS NULL AS active_lastschrift,
                persona_id
            FROM cde.lastschrift
            WHERE (granted_at, persona_id) IN (
                SELECT MAX(granted_at) AS granted_at, persona_id
                FROM cde.lastschrift GROUP BY persona_id
            )
        ) AS lastschrift ON personas.id = lastschrift.persona_id
        """),
    QueryScope.all_cde_users: _CDE_USER_VIEW,
    QueryScope.cde_member: (_PERSONAS_PAST_EVENT_VIEW := """core.personas
        LEFT OUTER JOIN past_event.participants
            ON personas.id = participants.persona_id
        """),
    QueryScope.past_event_user: _PERSONAS_PAST_EVENT_VIEW,
    QueryScope.core_user: _PERSONAS_PAST_EVENT_VIEW,
    QueryScope.all_core_users: _PERSONAS_PAST_EVENT_VIEW,
    QueryScope.quick_registration:
        """core.personas
        INNER JOIN event.registrations
            ON personas.id = registrations.persona_id
        """,
    QueryScope.registration: "",  # This will be generated on the fly.
    QueryScope.lodgement: "",  # This will be generated on the fly.
    QueryScope.event_course: "",  # This will be generated on the fly.
    QueryScope.past_event_course:
        """past_event.courses
        LEFT OUTER JOIN past_event.events
            ON courses.pevent_id = events.id
        """,
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
    # The most basic view on a persona.
    QueryScope.persona:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_archived": QuerySpecEntry("bool", n_("Archived Account")),
            "notes": QuerySpecEntry("str", n_("Admin Notes")),
            "fulltext": QuerySpecEntry("str", n_("Fulltext")),
        },
    # More complete view of a persona. Includes most event-realm things, but not all
    #  cde-realm things.
    QueryScope.core_user:
        {
            "personas.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "birth_name": QuerySpecEntry("str", n_("Birth Name")),
            "gender": QuerySpecEntry("int", n_("Gender")),
            "pronouns": QuerySpecEntry("str", n_("Pronouns")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "telephone": QuerySpecEntry("str", n_("Phone")),
            "mobile": QuerySpecEntry("str", n_("Mobile Phone")),
            "address": QuerySpecEntry("str", n_("Address")),
            "address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
            "postal_code": QuerySpecEntry("str", n_("ZIP")),
            "location": QuerySpecEntry("str", n_("City")),
            "country": QuerySpecEntry("str", n_("Country")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_ml_realm": QuerySpecEntry("bool", n_("Mailinglists"), n_("Realm")),
            "is_event_realm": QuerySpecEntry("bool", n_("Events"), n_("Realm")),
            "is_assembly_realm": QuerySpecEntry("bool", n_("Assemblies"), n_("Realm")),
            "is_cde_realm": QuerySpecEntry("bool", n_("cde_realm"), n_("Realm")),
            "is_member": QuerySpecEntry("bool", n_("CdE-Member")),
            "is_searchable": QuerySpecEntry("bool", n_("Searchable")),
            "is_archived": QuerySpecEntry("bool", n_("Archived Account")),
            **{
                k: QuerySpecEntry("bool", k, n_("Admin"))
                for k in ADMIN_KEYS
            },
            ",".join(ADMIN_KEYS): QuerySpecEntry("bool", n_("Any"), n_("Admin")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "notes": QuerySpecEntry("str", n_("Admin Notes")),
            "fulltext": QuerySpecEntry("str", n_("Fulltext")),
        },
    # The most complete view on a persona. Most is only available for cde-realm users.
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
            "pronouns": QuerySpecEntry("str", n_("Pronouns")),
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
            "donation": QuerySpecEntry("float", n_("Annual Donation")),
            "is_archived": QuerySpecEntry("bool", n_("Archived Account")),
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
            "notes": QuerySpecEntry("str", n_("Admin Notes")),
        },
    # Basic view of an event-realm user.
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
            "pronouns": QuerySpecEntry("str", n_("Pronouns")),
            "birthday": QuerySpecEntry("date", n_("Birthday")),
            "telephone": QuerySpecEntry("str", n_("Phone")),
            "mobile": QuerySpecEntry("str", n_("Mobile Phone")),
            "address": QuerySpecEntry("str", n_("Address")),
            "address_supplement": QuerySpecEntry("str", n_("Address Supplement")),
            "postal_code": QuerySpecEntry("str", n_("ZIP")),
            "location": QuerySpecEntry("str", n_("City")),
            "country": QuerySpecEntry("str", n_("Country")),
            "is_active": QuerySpecEntry("bool", n_("Active Account")),
            "is_archived": QuerySpecEntry("bool", n_("Archived Account")),
            "is_member": QuerySpecEntry("bool", n_("CdE-Member")),
            "is_searchable": QuerySpecEntry("bool", n_("Searchable")),
            **{
                k: QuerySpecEntry("bool", k, n_("Admin"))
                for k in ADMIN_KEYS
            },
            ",".join(ADMIN_KEYS): QuerySpecEntry("bool", n_("Any"), n_("Admin")),
            "pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "pcourse_id": QuerySpecEntry("id", n_("Past Course")),
            "notes": QuerySpecEntry("str", n_("Admin Notes")),
        },
    # Special view of a cde member for the member search.
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
    # Special view on a `event.regisrations` entry for registration quicksearch.
    QueryScope.quick_registration:
        {
            "registrations.id": QuerySpecEntry("id", n_("ID")),
            "given_names": QuerySpecEntry("str", n_("Given Names")),
            "family_name": QuerySpecEntry("str", n_("Family Name")),
            "username": QuerySpecEntry("str", n_("E-Mail")),
            "display_name": QuerySpecEntry("str", n_("Known as (Forename)")),
            "title": QuerySpecEntry("str", n_("Title_[[of a persona]]")),
            "name_supplement": QuerySpecEntry("str", n_("Name Affix")),
        },
    # Special view on `past_event.courses` and `past_event.events` for course search.
    QueryScope.past_event_course:
        {
            "courses.id": QuerySpecEntry("id", n_("course ID")),
            "courses.pcourse_id": QuerySpecEntry("id", n_("course")),
            "courses.pevent_id": QuerySpecEntry("id", n_("Past Event")),
            "courses.nr": QuerySpecEntry("str", n_("course nr")),
            "courses.title": QuerySpecEntry("str", n_("course title")),
            "courses.description": QuerySpecEntry("str", n_("course description")),
            "events.title": QuerySpecEntry(
                "str", n_("Title_[[name of an entity]]"), n_("Past Event")),
            "events.tempus": QuerySpecEntry(
                "date", n_("Cutoff date"), n_("Past Event")),
        },
}

# ml and assembly users contain very little data, so the basic view suffices.
_QUERY_SPECS[QueryScope.ml_user] = _QUERY_SPECS[QueryScope.persona]
_QUERY_SPECS[QueryScope.assembly_user] = _QUERY_SPECS[QueryScope.persona]

# Past event users are event users plus implicit event users, viewed as event users.
_QUERY_SPECS[QueryScope.past_event_user] = _QUERY_SPECS[QueryScope.event_user]

# The all_<realm>_users scopes should offer the same view, with different constraints.
_QUERY_SPECS[QueryScope.all_core_users] = _QUERY_SPECS[QueryScope.core_user]
_QUERY_SPECS[QueryScope.all_assembly_users] = _QUERY_SPECS[QueryScope.assembly_user]
_QUERY_SPECS[QueryScope.all_cde_users] = _QUERY_SPECS[QueryScope.cde_user]
_QUERY_SPECS[QueryScope.all_event_users] = _QUERY_SPECS[QueryScope.event_user]
_QUERY_SPECS[QueryScope.all_ml_users] = _QUERY_SPECS[QueryScope.ml_user]


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

    def __init__(self, scope: QueryScope, spec: QuerySpec,
                 fields_of_interest: Collection[str],
                 constraints: Collection[QueryConstraint],
                 order: Sequence[QueryOrder],
                 name: Optional[str] = None, query_id: Optional[int] = None,
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
        self.spec = dict(spec)
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
                ".".join(atom if atom.islower() else f'"{atom}"'
                         for atom in moniker.split("."))
                for moniker in column.split(","))
            for column in self.fields_of_interest]
        self.constraints = [
            (",".join(
                ".".join(atom if atom.islower() else f'"{atom}"'
                         for atom in moniker.split("."))
                for moniker in column.split(",")),
             operator, value)
            for column, operator, value in self.constraints
        ]
        self.order = [
            (".".join(atom if atom.islower() else f'"{atom}"'
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

    def serialize(self, timezone_aware: bool) -> CdEDBObject:
        """
        Serialize a query into a dict.

        This is used for both storing queries in the database (in which case
        `timezone_aware` should be True) and for turning a query object into a URL
        linking to a query page (in which case `timezone_aware` should be False.

        The format is compatible with QueryInput and search params.

        :param timezone_aware: If True, serialize datetimes to timezone aware format.
        Otherwise convert to default timezone, so that it will be parsed correctly.
        This is necessary because the HTML standard for `datetime-local` doesn't allow
        timezone information, while `datetime` is not well supported in browsers.
        """
        def serialize_value(val: Any) -> str:
            """Serialize datetimes to the default timezone then stringify w/o timezone.

            A datetime input without tzinfo will be set to the default timezone,
            therefore the result when reparsing will be identical.
            """
            if isinstance(val, datetime.datetime):
                if not timezone_aware:
                    formatcode = "%Y-%m-%dT%H:%M:%S"
                    if val.microsecond:
                        formatcode += ".%f"
                    return val.astimezone(
                        _CONFIG['DEFAULT_TIMEZONE']).strftime(formatcode)
                return val.isoformat()
            return str(val)

        params: CdEDBObject = {}
        for field in self.fields_of_interest:
            params[f'qsel_{field}'] = True
        for field, op, value in self.constraints:
            params[f'qop_{field}'] = op.value
            if (isinstance(value, collections.abc.Iterable)
                    and not isinstance(value, str)):
                params[f'qval_{field}'] = QUERY_VALUE_SEPARATOR.join(
                    serialize_value(x) for x in value)
            else:
                params[f'qval_{field}'] = serialize_value(value)
        for entry, postfix in zip(self.order, range(MAX_QUERY_ORDERS)):
            field, ascending = entry
            params[f'qord_{postfix}'] = field
            params[f'qord_{postfix}_ascending'] = ascending
        params['is_search'] = True
        params['scope'] = str(self.scope)
        params['query_name'] = self.name
        return params

    def serialize_to_url(self) -> CdEDBObject:
        """Helper to serialize the Query for use in an URL or to fill a form."""
        return self.serialize(timezone_aware=False)

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


def _sort_event_fields(fields: "models.CdEDataclassMap[models.EventField]",
                       ) -> dict[const.FieldAssociations, list["models.EventField"]]:
    """Helper to sort event fields and group them by association."""
    sorted_fields: dict[const.FieldAssociations, list["models.EventField"]] = {
        association: []
        for association in const.FieldAssociations
    }
    for field in xsorted(fields.values()):
        sorted_fields[field.association].append(field)
    return sorted_fields


def _combine_specs(spec_map: dict[int, QuerySpec], entity_ids: Collection[int],
                   prefix: str, translate_prefix: bool = False) -> QuerySpec:
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
            translate_prefix=translate_prefix,
        )
    return ret


def _get_course_choices(courses: Optional[CourseMap]) -> QueryChoices:
    if courses is None:
        return {}
    return dict((c.id, f"{c.nr} {c.shortname}") for c in xsorted(courses.values()))


def _get_lodgement_choices(lodgements: Optional[LodgementMap]) -> QueryChoices:
    if lodgements is None:
        return {}
    return dict((lodge.id, lodge.title) for lodge in xsorted(lodgements.values()))


def _get_lodgement_group_choices(lodgement_groups: Optional[LodgementGroupMap],
                                 ) -> QueryChoices:
    if lodgement_groups is None:
        return {}
    return dict((g.id, g.title) for g in xsorted(lodgement_groups.values()))


def make_registration_query_spec(event: "models.Event", courses: Optional[CourseMap] = None,
                                 lodgements: Optional[LodgementMap] = None,
                                 lodgement_groups: Optional[LodgementGroupMap] = None,
                                 ) -> QuerySpec:
    """Helper to generate ``QueryScope.registration``'s spec.

    Since each event has dynamic columns for parts and extra fields we
    have amend the query spec on the fly.
    """

    sorted_fields = _sort_event_fields(event.fields)
    field_choices = {
        field.field_name: field.entries or {}
        for field in event.fields.values()
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
        "persona.pronouns": QuerySpecEntry("str", n_("Pronouns")),
        "persona.pronouns_nametag": QuerySpecEntry("bool", n_("Pronouns on Nametag")),
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
        "reg.remaining_owed": QuerySpecEntry("float", n_("Remaining Owed")),
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

    def get_part_spec(part: "models.EventPart") -> QuerySpec:
        prefix = "" if len(event.parts) <= 1 else part.shortname
        return {
            # Choices for the status will be manually set.
            f"part{part.id}.status": QuerySpecEntry(
                "int", n_("registration status"), prefix, choices=None),  # type: ignore[arg-type]
            f"part{part.id}.is_camping_mat": QuerySpecEntry(
                "bool", n_("camping mat user"), prefix),
            f"part{part.id}.lodgement_id": QuerySpecEntry(
                "id", n_("lodgement"), prefix, choices=lodgement_choices),
            f"lodgement{part.id}.id": QuerySpecEntry("id", n_("lodgement ID"), prefix),
            f"lodgement{part.id}.group_id": QuerySpecEntry(
                "id", n_("lodgement group"), prefix, choices=lodgement_group_choices),
            f"lodgement{part.id}.title": QuerySpecEntry(
                "str", n_("lodgement title"), prefix),
            f"lodgement{part.id}.notes": QuerySpecEntry(
                "str", n_("lodgement notes"), prefix),
            **{
                f"lodgement{part.id}.xfield_{f.field_name}": QuerySpecEntry(
                    f.kind.name, n_("lodgement {field}"), prefix,
                    {'field': f.field_name})
                for f in sorted_fields[const.FieldAssociations.lodgement]
            },
            f"lodgement_group{part.id}.id": QuerySpecEntry(
                "id", n_("lodgement group ID"), prefix),
            f"lodgement_group{part.id}.title": QuerySpecEntry(
                "str", n_("lodgement group title"), prefix),
        }

    def get_track_spec(track: "models.CourseTrack") -> QuerySpec:
        track_id = track.id
        prefix = "" if len(event.tracks) <= 1 else track.shortname
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
                f"course{track_id}.xfield_{f.field_name}": QuerySpecEntry(
                    f.kind.name, n_("course {field}"), prefix,
                    {'field': f.field_name}, choices=field_choices[f.field_name],
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
                f"course_instructor{track_id}.xfield_{f.field_name}": QuerySpecEntry(
                    f.kind.name, n_("instructed course {field}"), prefix,
                    {'field': f.field_name}, choices=field_choices[f.field_name],
                )
                for f in sorted_fields[const.FieldAssociations.course]
            },
        }

    def get_course_choice_spec(cco: "models.CourseChoiceObject") -> QuerySpec:
        prefix = "" if len(event.tracks) <= 1 else cco.shortname
        reference_track = cco.reference_track if cco.is_complex() else cco
        ret = {
            f"course_choices{reference_track.id}.rank{i}": QuerySpecEntry(
                "id", n_("{rank}. Choice"), prefix, {'rank': str(i + 1)},
                choices=course_choices,
            )
            for i in range(cco.num_choices)
        }

        # If there are course choices for the track, add an entry for any choice.
        if key := ",".join(ret.keys()):
            # Don't overwrite a potential existing spec.
            #  This happens if there is exactly one choice.
            if key not in ret:
                ret[key] = QuerySpecEntry(
                    "id", n_("Any Choice"), prefix, choices=course_choices)

        return ret

    # Presort part specs, so we can iterate over them in order.
    part_specs = {
        int(part.id): get_part_spec(part)
        for part in xsorted(event.parts.values())
    }
    track_specs = {
        int(track.id): get_track_spec(track)
        for track in xsorted(event.tracks.values())
    }
    course_choice_specs = {
        int(track.id): get_course_choice_spec(track)
        for track in xsorted(event.tracks.values())
    }

    # Add entries for individual parts and tracks in those parts.
    for part_id, part_spec in part_specs.items():
        part = event.parts[part_id]
        spec.update(part_spec)

        # Add entries for individual tracks.
        for track in xsorted(part.tracks.values()):
            spec.update(track_specs[track.id])

            # Skip course choice filters if track is synced.
            if any(tg.constraint_type == const.CourseTrackGroupType.course_choice_sync
                   for tg in track.track_groups.values()):
                continue
            spec.update(course_choice_specs[track.id])

        # Add Entries for all tracks in this part.
        spec.update(_combine_specs(
            track_specs, part.tracks, prefix=part.shortname))
        spec.update(_combine_specs(
            course_choice_specs, part.tracks, prefix=part.shortname))

    # Add entries for groups of parts and tracks in those parts.
    sorted_part_groups = [pg.as_dict() for pg in xsorted(event.part_groups.values())]
    sorted_part_groups.append({'parts': event.parts, 'shortname': None})
    for part_group in sorted_part_groups:
        if constraint := part_group.get('constraint_type'):
            if constraint != const.EventPartGroupType.Statistic:
                continue
        part_ids = part_group['parts'].keys()
        prefix = part_group['shortname']
        spec.update(_combine_specs(
            part_specs, part_ids, prefix=prefix or n_("any part"),
            translate_prefix=not prefix))
        # Add entries for track combinations.
        track_ids = tuple(itertools.chain.from_iterable(
            event.parts[part_id].tracks.keys() for part_id in part_ids))
        spec.update(_combine_specs(
            track_specs, track_ids, prefix=prefix or n_("any track"),
            translate_prefix=not prefix))
        spec.update(_combine_specs(
            course_choice_specs, track_ids, prefix=prefix or n_("any track"),
            translate_prefix=not prefix))

    # Add entries for track groups.
    for track_group in xsorted(event.track_groups.values()):
        if track_group.constraint_type != const.CourseTrackGroupType.course_choice_sync:
            continue  # type: ignore[unreachable]

        spec.update(get_course_choice_spec(
            cast("models.SyncTrackGroup", track_group)))

    spec.update({
        f"reg_fields.xfield_{f.field_name}": QuerySpecEntry(
            f.kind.name, f.title, choices=field_choices[f.field_name])
        for f in sorted_fields[const.FieldAssociations.registration]
    })
    return spec


def make_course_query_spec(event: "models.Event", courses: Optional[CourseMap] = None,
                           lodgements: Optional[LodgementMap] = None,
                           lodgement_groups: Optional[LodgementGroupMap] = None,
                           ) -> QuerySpec:
    """Helper to generate ``QueryScope.event_course``'s spec.

    Since each event has custom course fields and an arbitrary number
    of course tracks we have to extend this spec on the fly.
    """
    sorted_tracks = xsorted(event.tracks.values())
    sorted_course_fields = _sort_event_fields(event.fields)[
        const.FieldAssociations.course]
    field_choices = {
        field.field_name: dict(field.entries) if field.entries else {}
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

    def get_track_spec(track: "models.CourseTrack") -> QuerySpec:
        prefix = "" if len(event.tracks) <= 1 else track.shortname
        return {
            f"track{track.id}.is_offered": QuerySpecEntry(
                "bool", n_("is offered"), prefix),
            f"track{track.id}.takes_place": QuerySpecEntry(
                "bool", n_("takes place"), prefix),
            f"track{track.id}.is_cancelled": QuerySpecEntry(
                "bool", n_("is cancelled"), prefix),
            f"track{track.id}.attendees": QuerySpecEntry(
                "int", n_("attendee count"), prefix),
            f"track{track.id}.attendees_and_guests": QuerySpecEntry(
                "int", n_("attendee count (incl. guests)"), prefix),
            f"track{track.id}.instructors": QuerySpecEntry(
                "int", n_("instructor count"), prefix),
            f"track{track.id}.assigned_instructors": QuerySpecEntry(
                "int", n_("assigned instructor count"), prefix),
            f"track{track.id}.potential_instructors": QuerySpecEntry(
                "int", n_("potential instructor count (incl. open)"), prefix),
        }

    def get_course_choice_spec(track: "models.CourseTrack") -> QuerySpec:
        prefix = "" if len(event.tracks) <= 1 else track.shortname
        return {
            f"track{track.id}.num_choices{i}": QuerySpecEntry(
                "int", n_("{rank}. choices"), prefix, {'rank': str(i + 1)})
            for i in range(track.num_choices)
        }

    track_specs = {
        int(track.id): get_track_spec(track)
        for track in sorted_tracks
    }
    course_choice_specs = {
        int(track.id): get_course_choice_spec(track)
        for track in sorted_tracks
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
                prefix = ("" if len(event.tracks) <= 1
                          else event.tracks[track_id].shortname)
                spec[key] = QuerySpecEntry("id", n_("Any Choice"), prefix)
        spec.update(course_choice_spec)

    # Add entries for groups of tracks.
    sorted_parts = xsorted(event.parts.values())
    sorted_part_groups = xsorted(event.part_groups.values())
    track_groups: tuple[CdEDBObject, ...] = (
        {'track_ids': event.tracks.keys(), 'shortname': None},
        *(
            {'track_ids': part.tracks.keys(), 'shortname': part.shortname}
            for part in sorted_parts
        ),
        *(
            {
                'track_ids': tuple(itertools.chain.from_iterable(
                    part.tracks.keys()
                    for part in part_group.parts.values()
                )),
                'shortname': part_group.shortname,
            }
            for part_group in sorted_part_groups
        ),
    )
    for track_group in track_groups:
        track_ids = track_group['track_ids']
        prefix = track_group['shortname']
        spec.update(_combine_specs(
            track_specs, track_ids, prefix or n_("any track"),
            translate_prefix=not prefix))
        spec.update(_combine_specs(
            course_choice_specs, track_ids, prefix or n_("any track"),
            translate_prefix=not prefix))

    spec.update({
        f"course_fields.xfield_{field.field_name}": QuerySpecEntry(
            field.kind.name, field.title,
            choices=field_choices[field.field_name])
        for field in sorted_course_fields
    })

    return spec


def make_lodgement_query_spec(event: "models.Event", courses: Optional[CourseMap] = None,
                              lodgements: Optional[LodgementMap] = None,
                              lodgement_groups: Optional[LodgementGroupMap] = None,
                              ) -> QuerySpec:
    """Helper to generate ``QueryScope.lodgement``'s spec.

    Since each event has custom lodgement fields and an arbitrary number
    of event parts, we have to expand this spec on the fly.
    """
    sorted_parts = xsorted(event.parts.values())
    sorted_lodgement_fields = _sort_event_fields(event.fields)[
        const.FieldAssociations.lodgement]
    field_choices = {
        field.field_name: dict(field.entries) if field.entries else {}
        for field in sorted_lodgement_fields
    }
    lodgement_choices = _get_lodgement_choices(lodgements)
    lodgement_group_choices = _get_lodgement_group_choices(lodgement_groups)

    spec = {
        "lodgement.id": QuerySpecEntry("id", n_("lodgement ID")),
        "lodgement.lodgement_id": QuerySpecEntry(
            "id", n_("lodgement"), choices=lodgement_choices),
        "lodgement.title": QuerySpecEntry("str", n_("Title_[[name of an entity]]")),
        "lodgement.regular_capacity": QuerySpecEntry("int", n_("Regular Capacity")),
        "lodgement.camping_mat_capacity": QuerySpecEntry(
            "int", n_("Camping Mat Capacity")),
        "lodgement.total_capacity": QuerySpecEntry("int", n_("Total Capacity")),
        "lodgement.notes": QuerySpecEntry("str", n_("Lodgement Notes")),
        "lodgement.group_id": QuerySpecEntry(
            "int", n_("Lodgement Group"), choices=lodgement_group_choices),
        "lodgement_group.id": QuerySpecEntry("int", n_("Lodgement Group ID")),
        "lodgement_group.title": QuerySpecEntry("str", n_("Lodgement Group Title")),
        # This will be augmented with additional fields in the fly.
    }

    def get_part_spec(part: "models.EventPart") -> QuerySpec:
        prefix = "" if len(event.parts) <= 1 else part.shortname
        return {
            f"part{part.id}.regular_inhabitants": QuerySpecEntry(
                "int", n_("Regular Inhabitants"), prefix),
            f"part{part.id}.camping_mat_inhabitants": QuerySpecEntry(
                "int", n_("Camping Mat Inhabitants"), prefix),
            f"part{part.id}.total_inhabitants": QuerySpecEntry(
                "int", n_("Total Inhabitants"), prefix),
            f"part{part.id}.regular_remaining": QuerySpecEntry(
                "int", n_("Regular Remaining"), prefix),
            f"part{part.id}.camping_mat_remaining": QuerySpecEntry(
                "int", n_("Camping Mat Remaining"), prefix),
            f"part{part.id}.total_remaining": QuerySpecEntry(
                "int", n_("Total Remaining"), prefix),
            f"part{part.id}.group_regular_inhabitants": QuerySpecEntry(
                "int", n_("Group Regular Inhabitants"), prefix),
            f"part{part.id}.group_camping_mat_inhabitants": QuerySpecEntry(
                "int", n_("Group Camping Mat Inhabitants"), prefix),
            f"part{part.id}.group_total_inhabitants": QuerySpecEntry(
                "int", n_("Group Total Inhabitants"), prefix),
        }

    # Presort part specs so we can iterate over them in order.
    part_specs = {int(part.id): get_part_spec(part) for part in sorted_parts}

    # Add entries for individual parts.
    for part_id, part_spec in part_specs.items():
        spec.update(part_spec)

    # Add entries for groups of parts.
    sorted_part_groups = [pg.as_dict() for pg in xsorted(event.part_groups.values())]
    sorted_part_groups.append({'parts': event.parts, 'shortname': None})
    for part_group in sorted_part_groups:
        part_ids = part_group['parts'].keys()
        prefix = part_group['shortname']
        spec.update(_combine_specs(
            part_specs, part_ids, prefix=prefix or n_("any part"),
            translate_prefix=not prefix))

    spec.update({
        f"lodgement_fields.xfield_{f.field_name}": QuerySpecEntry(
            f.kind.name, f.title, choices=field_choices[f.field_name])
        for f in sorted_lodgement_fields
    })

    return spec
