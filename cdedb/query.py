#!/usr/bin/env python3

"""Framework for complex queries.

This defines an abstraction for specifying queries. The basic use case
is the member search which has to be handled at three stages: templates,
frontend and backend. All of this should happen with a unified
framework, thus this module. This module is especially useful in setting
up an environment for passing a query from frontend to backend.
"""

import collections
import enum
from typing import TYPE_CHECKING, Any, Collection, Dict, Tuple

from cdedb.common import CdEDBObject, RequestState, glue


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


class Query:
    """General purpose abstraction for an SQL query.

    This allows to make very flexible queries in a programmatic way. The
    basic use cases are the member search in the cde realm and the
    search page for event orgas. The latter is responsible for some
    design descisions, since we have to accomodate ext-fields and
    everything.
    """

    def __init__(self, scope: str, spec: CdEDBObject,
                 fields_of_interest: Collection[str],
                 constraints: Collection[QueryConstraint],
                 order: Collection[QueryOrder], name: str = None):
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
        """
        self.scope = scope
        self.spec = spec
        self.fields_of_interest = list(fields_of_interest)
        self.constraints = list(constraints)
        self.order = list(order)
        self.name = name

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


#: Available query templates. These may be enriched by ext-fields. Order is
#: important for UI purposes, hence the ordered dicts.
#:
#: .. note:: For schema specified columns (like ``personas.id``)
#:           the schema part does not survive querying and needs to be stripped
#:           before output.
if TYPE_CHECKING:
    QUERY_SPECS: Dict[
        str, collections.OrderedDict[str, str]  # pylint: disable=unsubscriptable-object
    ]
QUERY_SPECS = {
    "qview_cde_member":
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
            ("weblink,specialisation,affiliation,timeline,interests,free_form", "str"),
            ("pevent_id", "id"),
            ("pcourse_id", "id"),
            ("fulltext", "str"),
        ]),
    "qview_cde_user":
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
    "qview_archived_core_user":
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
    "qview_archived_past_event_user":
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
    "qview_archived_persona":
        collections.OrderedDict([
            ("personas.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("display_name", "str"),
            ("notes", "str"),
        ]),
    "qview_past_event_user":
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
    "qview_event_user":
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
    "qview_registration":
        collections.OrderedDict([
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
            # This will be augmented with additional fields on the fly.
        ]),
    "qview_quick_registration":
        collections.OrderedDict([
            ("registrations.id", "id"),
            ("given_names", "str"),
            ("family_name", "str"),
            ("username", "str"),
            ("display_name", "str"),
            ("title", "str"),
            ("name_supplement", "str"),
        ]),
    "qview_event_course":
        collections.OrderedDict([
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
        ]),
    "qview_event_lodgement":
        collections.OrderedDict([
            ("lodgement.id", "id"),
            ("lodgement.lodgement_id", "id"),
            ("lodgement.title", "str"),
            ("lodgement.regular_capacity", "int"),
            ("lodgement.camping_mat_capacity", "int"),
            ("lodgement.notes", "str"),
            ("lodgement.group_id", "int"),
            ("lodgement_group.title", "int"),
            # This will be augmented with additional fields in the fly.
        ]),
    "qview_pevent_course":
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
    "qview_core_user":  # query for a general user including past event infos
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
    "qview_persona":  # query for a persona without past event infos
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
}

#: Supstitute for SQL views, this is the target of the FROM clause of the
#: respective query. We cannot use SQL views since they do not allow multiple
#: columns with the same name, but each join brings in an id column.
QUERY_VIEWS = {
    "qview_cde_member": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_cde_user": """core.personas
    LEFT OUTER JOIN past_event.participants ON personas.id = participants.persona_id
    LEFT OUTER JOIN (
        SELECT
            id, granted_at, revoked_at, revoked_at IS NOT NULL AS active_lastschrift,
            amount, persona_id
        FROM cde.lastschrift
        WHERE (granted_at, persona_id) IN (
            SELECT MAX(granted_at) AS granted_at, persona_id
            FROM cde.lastschrift GROUP BY persona_id
        )
    ) AS lastschrift ON personas.id = lastschrift.persona_id
    """,
    "qview_past_event_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_event_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_registration": None,  # dummy -- value will be generated on the fly
    "qview_quick_registration": glue(
        "core.personas",
        "INNER JOIN event.registrations",
        "ON personas.id = registrations.persona_id"),
    "qview_pevent_course": glue(
        "past_event.courses",
        "LEFT OUTER JOIN past_event.events",
        "ON courses.pevent_id = events.id"),
    "qview_core_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_persona": "core.personas",
    "qview_archived_core_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_archived_past_event_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_archived_persona": "core.personas",
}

#: This is the primary key for the query and allows access to the
#: corresponding data set. We always select this key to avoid any
#: pathologies.
QUERY_PRIMARIES = {
    "qview_cde_member": "personas.id",
    "qview_cde_user": "personas.id",
    "qview_past_event_user": "personas.id",
    "qview_event_user": "personas.id",
    "qview_registration": "reg.id",
    "qview_quick_registration": "registrations.id",
    "qview_event_course": "course.id",
    "qview_event_lodgement": "lodgement.id",
    "qview_pevent_course": "courses.id",
    "qview_core_user": "personas.id",
    "qview_persona": "id",
    "qview_archived_core_user": "personas.id",
    "qview_archived_past_event_user": "personas.id",
    "qview_archived_persona": "id",
}


def mangle_query_input(rs: RequestState, spec: Dict[str, str],
                       defaults: CdEDBObject = None) -> Dict[str, str]:
    """This is to be used in conjunction with the ``query_input`` validator,
    which is exceptional since it is not used via a decorator. To take
    care of the differences this function exists.

    This has to be careful to treat checkboxes and selects correctly
    (which are partly handled by an absence of data).

    :param spec: one of :py:data:`QUERY_SPECS`
    :param defaults: Default values which appear like they have been submitted,
      if nothing has been submitted for this paramater.
    :returns: The raw data associated to the query described by the spec
        extracted from the request data saved in the request state.
    """
    defaults = defaults or {}
    params = {}
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
