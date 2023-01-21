
import pyparsing as pp

# Created according to https://stackoverflow.com/a/37903645/10315508
_ALL_UNICODE_WHITESPACE = '\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006' \
                          '\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'


def create_parser() -> pp.ParserElement:
    # variables and bool literals
    operator_part_name = pp.CharsNotIn(_ALL_UNICODE_WHITESPACE + "()[]").set_name("part shortname")
    operator_field_name = pp.Word(pp.alphanums + "_").set_name("field name")

    operator_field = pp.Group(pp.Combine(pp.Suppress(pp.CaselessKeyword("field") + '.') - operator_field_name))\
        .set_results_name("field")
    operator_part = pp.Group(pp.Combine(pp.Suppress(pp.CaselessKeyword("part") + '.') - operator_part_name))\
        .set_results_name("part")
    operator_true = pp.Group(pp.CaselessKeyword("true").suppress()).setResultsName("true")
    operator_false = pp.Group(pp.CaselessKeyword("false").suppress()).setResultsName("false")

    operator_bool_atom = (operator_field | operator_part | operator_true | operator_false)\
        .set_name("field, part, true or false")

    # full expressions (forward declaration) and parenthesized expressions
    operator_or = pp.Forward().set_name("expression")

    operator_parenthesis = (
        (pp.Suppress("(") - operator_or - pp.Suppress(")"))
        | operator_bool_atom
    )

    # Operators (right-chainable) in order of precendence
    operator_not = pp.Forward()
    operator_not << (
        pp.Group(
            pp.CaselessKeyword("not").suppress() - operator_not
        ).set_results_name("not")
        | operator_parenthesis
    ).set_name("expression")

    operator_and = pp.Forward()
    operator_and << (
        pp.Group(
            operator_not + pp.CaselessKeyword("and").suppress() - operator_and
        ).set_results_name("and")
        # Comment in to allow implicit 'and' for two consecutive expressions
        # | pp.Group(
        #     operator_not + pp.OneOrMore(~pp.one_of("and or xor") + operator_and)
        # ).set_results_name("and")
        | operator_not
    ).set_name("expression")

    operator_xor = pp.Forward()
    operator_xor << (
        pp.Group(
            operator_and + pp.CaselessKeyword("xor").suppress() - operator_xor
        ).set_results_name("xor")
        | operator_and
    ).set_name("expression")

    operator_or << (  # type: ignore[operator]
        pp.Group(
            operator_xor + pp.CaselessKeyword("or").suppress() - operator_or
        ).set_results_name("or")
        | operator_xor
    ).set_name("expression")

    return operator_or
