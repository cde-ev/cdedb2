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

from cdedb.common import glue

@enum.unique
class QueryOperators(enum.Enum):
    """Enum for all possible operators on a query column."""
    empty = 0
    nonempty = 1
    equal = 2
    oneof = 3
    similar = 4
    regex = 5
    containsall = 6
    less = 10
    lessequal = 11
    between = 12
    greaterequal = 13
    greater = 14

_ops = QueryOperators
#: Only a subset of all possible operators is appropriate for each data
#: type. Order is important for UI purpose hence no sets.
VALID_QUERY_OPERATORS = {
    "str": (_ops.similar, _ops.equal, _ops.containsall, _ops.oneof,
            _ops.regex, _ops.empty, _ops.nonempty),
    "int": (_ops.equal, _ops.oneof, _ops.less, _ops.lessequal, _ops.between,
            _ops.greaterequal, _ops.greater, _ops.empty, _ops.nonempty),
    "float": (_ops.less, _ops.between, _ops.greater, _ops.empty, _ops.nonempty),
    "date": (_ops.equal, _ops.oneof, _ops.less, _ops.lessequal, _ops.between,
             _ops.greaterequal, _ops.greater, _ops.empty, _ops.nonempty),
    "datetime": (
        _ops.equal, _ops.oneof, _ops.less, _ops.lessequal, _ops.between,
        _ops.greaterequal, _ops.greater, _ops.empty, _ops.nonempty),
    "bool": (_ops.equal, _ops.empty, _ops.nonempty),
}

#: Some operators expect several operands (that is a space delimited list of
#: operands) and thus need to be treated differently.
MULTI_VALUE_OPERATORS = {QueryOperators.oneof, QueryOperators.containsall,
                         QueryOperators.between}

#: Some operators expect no operands need some special-casing.
NO_VALUE_OPERATORS = {QueryOperators.empty, QueryOperators.nonempty}

class Query:
    """General purpose abstraction for an SQL query.

    This allows to make very flexible queries in a programmatic way. The
    basic use cases are the member search in the cde realm and the
    search page for event orgas. The latter is responsible for some
    design descisions, since we have to accomodate ext-fields and
    everything.
    """
    def __init__(self, scope, spec, fields_of_interest, constraints, order):
        """
        :type scope: str
        :param scope: target of FROM clause; key for :py:data:`QUERY_VIEWS`.
            We would like to use SQL views for this, but they are not flexible
            enough.
        :type fields_of_interest: [str]
        :param fields_of_interest: column names to be SELECTed.
        :type spec: {str: str}
        :param spec: Keys are field names and values are validator names. See
            :py:const:`QUERY_SPECS`.
        :type constraints: [(str, QueryOperators, obj)]
        :param constraints: clauses for WHERE
        :type order: [(str, bool)]
        :param order: First components are the column names to be used for
          ORDER BY and the second component toggles ascending sorting order.
        """
        self.scope = scope
        self.spec = spec
        self.fields_of_interest = fields_of_interest
        self.constraints = constraints
        self.order = order

    def __repr__(self):
        return glue(
            "Query(scope={}, fields_of_interest={}, constraints={}, order={},",
            "spec={})").format(self.scope, self.fields_of_interest,
                               self.constraints, self.order, self.spec)

#: Available query templates. These may be enriched by ext-fields. Order is
#: important for UI purposes, hence the ordered dicts.
#:
#: .. note:: For schema specified columns (like ``personas.id``)
#:           the schema part does not survive querying and needs to be stripped
#:           before output.
QUERY_SPECS = {
    "qview_cde_member" :
    collections.OrderedDict([
        ("family_name,birth_name,given_names,display_name,username,address,address_supplement,address2,address_supplement2,postal_code,postal_code2,location,location2,country,country2,weblink,specialisation,affiliation,timeline,interests,free_form", "str"), # replacement for fulltext FIXME does not really work (see general_query)
        ("family_name,birth_name", "str"),
        ("given_names,display_name", "str"),
        ("username", "str"),
        ("address,address_supplement,address2,address_supplement2", "str"),
        ("postal_code,postal_code2", "str"),
        ("location,location2", "str"),
        ("country,country2", "str"),
        ("weblink,specialisation,affiliation,timeline,interests,free_form",
         "str"),
        ("pevent_id", "int"),
        ("pcourse_id", "int"),
        ]),
    "qview_cde_user" :
    collections.OrderedDict([
        # ("fulltext", "str"), FIXME reintroduce
        ("personas.id", "int"),
        ("username", "str"),
        ("is_admin", "bool"),
        ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"),
        ("is_event_admin", "bool"),
        ("is_ml_admin", "bool"),
        ("is_assembly_admin", "bool"),
        ("is_cde_realm", "bool"),
        ("is_event_realm", "bool"),
        ("is_ml_realm", "bool"),
        ("is_assembly_realm", "bool"),
        ("is_member", "bool"),
        ("is_searchable", "bool"),
        ("is_active", "bool"),
        ("is_archived", "bool"),
        ("cloud_account", "bool"),
        ("family_name", "str"),
        ("birth_name", "str"),
        ("given_names", "str"),
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
        ("address2", "str"),
        ("address_supplement2", "str"),
        ("postal_code2", "str"),
        ("location2", "str"),
        ("country2", "str"),
        ("weblink", "str"),
        ("specialisation", "str"),
        ("affiliation", "str"),
        ("timeline", "str"),
        ("interests", "str"),
        ("free_form", "str"),
        ("event_id", "int"),
        ("course_id", "int"),
        ("balance", "float"),
        ("decided_search", "bool"),
        ("trial_member", "bool"),
        ("bub_search", "bool"),
        ("notes", "str"),
        ]),
    "qview_cde_archived_user" :
    collections.OrderedDict([
        ("personas.id", "int"),
        ("family_name", "str"),
        ("birth_name", "str"),
        ("given_names", "str"),
        ("display_name", "str"),
        ("gender", "int"),
        ("birthday", "date"),
        ("pevent_id", "int"),
        ("pcourse_id", "int"),
        ("notes", "str"),
        ]),
    "qview_event_user" :
    collections.OrderedDict([
        ("personas.id", "int"),
        ("username", "str"),
        ("is_admin", "bool"),
        ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"),
        ("is_event_admin", "bool"),
        ("is_ml_admin", "bool"),
        ("is_assembly_admin", "bool"),
        ("is_cde_realm", "bool"),
        ("is_event_realm", "bool"),
        ("is_ml_realm", "bool"),
        ("is_assembly_realm", "bool"),
        ("is_member", "bool"),
        ("is_searchable", "bool"),
        ("is_active", "bool"),
        ("is_archived", "bool"),
        ("cloud_account", "bool"),
        ("family_name", "str"),
        ("given_names", "str"),
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
        ("pevent_id", "int"),
        ("pcourse_id", "int"),
        ("notes", "str"),
        ]),
    "qview_registration" :
    collections.OrderedDict([
        ("reg.id", "int"),
        ("reg.notes", "str"),
        ("reg.orga_notes", "str"),
        ("reg.payment", "date"),
        ("reg.parental_agreement", "bool"),
        ("reg.mixed_lodging", "bool"),
        ("reg.checkin", "datetime"),
        ("reg.foto_consent", "bool"),
        ("persona.is_member", "bool"),
        ("persona.username", "str"),
        ("persona.family_name", "str"),
        ("persona.given_names", "str"),
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
        ## This will be augmented with additional fields on the fly.
        ]),
    "qview_generic_user" :
    collections.OrderedDict([
        ("id", "int"),
        ("username", "str"),
        ("is_admin", "bool"),
        ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"),
        ("is_event_admin", "bool"),
        ("is_ml_admin", "bool"),
        ("is_assembly_admin", "bool"),
        ("is_cde_realm", "bool"),
        ("is_event_realm", "bool"),
        ("is_ml_realm", "bool"),
        ("is_assembly_realm", "bool"),
        ("is_member", "bool"),
        ("is_searchable", "bool"),
        ("is_active", "bool"),
        ("is_archived", "bool"),
        ("cloud_account", "bool"),
        ("family_name", "str"),
        ("given_names", "str"),
        ("display_name", "str"),
        ("notes", "str"),
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
    "qview_cde_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_cde_archived_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_event_user": glue(
        "core.personas",
        "LEFT OUTER JOIN past_event.participants",
        "ON personas.id = participants.persona_id"),
    "qview_registration": None, ## dummy -- value will be generated on the fly
    "qview_generic_user": "core.personas",
}

def mangle_query_input(rs, spec):
    """This is to be used in conjunction with the ``query_input`` validator,
    which is exceptional since it is not used via a decorator. To take
    care of the differences this function exists.

    This has to be careful to treat checkboxes and selects correctly
    (which are partly handled by an absence of data).

    :type rs: :py:class:`cdedb.frontend.common.FrontendRequestState`
    :type spec: {str: str}
    :param spec: one of :py:data:`QUERY_SPECS`
    :rtype: {str: str}
    :returns: The raw data associated to the query described by the spec
        extracted from the request data saved in the request state.
    """
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
    return params
