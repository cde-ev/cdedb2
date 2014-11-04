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

@enum.unique
class QueryOperators(enum.Enum):
    """Enum for all possible operators on a query column."""
    null = 0
    notnull = 1
    equal = 2
    oneof = 3
    similar = 4
    similaroneof = 5
    regex = 6
    containsall = 7
    less = 10
    lessequal = 11
    between = 12
    greaterequal = 13
    greater = 14

@enum.unique
class QueryScopes(enum.Enum):
    """This encodes which tables are to be queried.

    Since we mistrust our inputs in general this information cannot be
    stored as string in a :py:class:`Query` object. Thus we use this
    which is mapped (think a dict) to the correct string describing the
    target of the sql FROM clause.
    """
    user = 0
    member = 1
    registration = 2

_ops = QueryOperators
#: Only a subset of all possible operators is appropriate for each data
#: type. Order is important for UI purpose hence no sets.
VALID_QUERY_OPERATORS = {
    "str" : (_ops.similar, _ops.equal, _ops.similaroneof, _ops.containsall,
             _ops.oneof, _ops.regex, _ops.null, _ops.notnull),
    "int" : (_ops.equal, _ops.oneof, _ops.less, _ops.lessequal, _ops.between,
             _ops.greaterequal, _ops.greater, _ops.null, _ops.notnull),
    "float" : (_ops.less, _ops.between, _ops.greater, _ops.null, _ops.notnull),
    "date" : (_ops.equal, _ops.oneof, _ops.less, _ops.lessequal, _ops.between,
              _ops.greaterequal, _ops.greater, _ops.null, _ops.notnull),
    "bool" : (_ops.equal, _ops.null, _ops.notnull),
}

#: Some operators expect several operands (that is a space delimited list of
#: operands) and thus needs to be treated differently.
MULTI_VALUE_OPERATORS = {QueryOperators.oneof, QueryOperators.similaroneof,
                         QueryOperators.containsall, QueryOperators.between}

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
        :type scope: QueryScopes
        :type fields_of_interest: [str]
        :param fields_of_interest: The column names to be SELECTed.
        :type spec: {str : str}
        :param spec: Keys are field names and values are validator names. See
            :py:const:`QUERY_SPECS`.
        :type constraints: [(str, QueryOperators, obj)]
        :param constraints: clauses for WHERE
        :type order: [str]
        :param order: column names to be used for ORDER BY
        """
        self.scope = scope
        self.spec = spec
        self.fields_of_interest = fields_of_interest
        self.constraints = constraints
        self.order = order

#: Available query templates. These may be enriched by ext-fields.
QUERY_SPECS = {
    "cde-member-search" :
    collections.OrderedDict([
        ("fulltext", "str"),
        ("family_name,birth_name", "str"),
        ("given_names,display_name", "str"),
        ("username", "str"),
        ("address,address_supplement,address2,address_supplement2", "str"),
        ("postal_code,postal_code2", "str"),
        ("location,location2", "str"),
        ("country,country2", "str"),
        ("weblink,specialisation,affiliation,timeline,interests,free_form",
         "str"),
        ("event_id", "int"),
        ("course_id", "int"),
        ])
}

def mangle_query_input(rs, spec):
    """This is to be used in conjunction with the ``query_input`` validator,
    which is exceptional since it is not used via a decorator. To take
    care of the differences this function exists.

    :type rs: :py:class:`cdedb.frontend.common.FrontendRequestState`
    :type spec: {str : str}
    :param spec: one of :py:data:`QUERY_SPECS`
    :rtype: {str : str}
    :returns: The raw data associated to the query described by the spec
        extracted from the request data saved in the request state.
    """
    params = {}
    for field in spec:
        for prefix in ("qval_", "qsel_", "qop_"):
            name = prefix + field
            params[name] = rs.values[name] = rs.request.values.get(name, "")
    for postfix in ("primary", "secondary", "tertiary"):
        name = "qord_" + postfix
        params[name] = rs.values[name] = rs.request.values.get(name, "")
    return params

def serialize_query(query):
    """This is the inverse of the ``serialized_query`` validator.

    This has to be called manually and could be automated with a bit of
    pyro-magic, but since this is the only thing that needs special
    serialization in the frontend -> backend direction we keep it simple
    for now.

    :type query: :py:class:`Query`
    :rtype: {str : object}
    """
    return {
        "scope" : query.scope.value,
        "spec" : dict(query.spec), # convert OrderedDict to dict for serpent
        "fields_of_interest" : query.fields_of_interest,
        "constraints" : tuple((field, operator.value, obj)
                              for field, operator, obj in query.constraints),
        "order" : query.order,
    }
