# pylint: disable=line-too-long,missing-module-docstring
from typing import Callable, Dict, List, Optional, Tuple

import pyparsing as pp


def serialize(result: pp.ParseResults, *, part_substitutions: Dict[str, str] = None) -> str:
    """Public serialization interface, to get a normalized condition string.

    :param part_substitutions: Replace each part name in the dict with it's value.
    """
    return _serialize(result, outer_operator=None, ps=part_substitutions or {})


def _serialize(result: pp.ParseResults, outer_operator: Optional[str], ps: Dict[str, str]) -> str:
    """Internal recursive normalizer.

    :param outer_operator: If given, put parentheses around current operation, if
        it is not this operator. Pass the name of the current operator to the recursive
        call for it's operands. For example `AND(a, AND(b, c))` is normalized to
        'a AND b AND c', while `AND(a, OR(b, c))` is normalized to 'a AND (b OR c)`,
        because the AND-operand `OR(b, c)` is not also a AND-operation.
    :param: ps: A dict of part substitutions. Substitute part names for these values.
    """
    functions = {
        'and': lambda x: f"{_serialize(x[0], 'and', ps)} and {_serialize(x[1], 'and', ps)}",
        'or': lambda x: f"{_serialize(x[0], 'or', ps)} or {_serialize(x[1], 'or', ps)}",
        'xor': lambda x: f"{_serialize(x[0], 'xor', ps)} xor {_serialize(x[1], 'xor', ps)}",
        'not': lambda x: f"not {_serialize(x[0], '', ps)}",
        'true': lambda x_: "true",
        'false': lambda x_: "false",
        'field': lambda x: f"field.{x[0]}",
        'part': lambda x: f"part.{ps.get(x[0], x[0])}",
        'bool': lambda x: f"{x[0]}",
    }
    name = result.get_name()
    if name in ('and', 'or', 'xor') and outer_operator is not None and name != outer_operator:
        return f"({functions[name](result)})"
    else:
        return functions[name](result)


def visual_debug(result: pp.ParseResults, field_values: Dict[str, bool], part_values: Dict[str, bool],
                 other_values: Dict[str, bool], outer_operator: Optional[str] = None, top_level: bool = True
                 ) -> Tuple[bool, str]:
    functions: Dict[str, Callable[[List[Tuple[bool, str]]], Tuple[bool, str]]] = {
        'and': lambda sr: (sub_results[0][0] and sub_results[1][0], f"{sub_results[0][1]} <b>and</b> {sub_results[1][1]}"),
        'or': lambda sr: (sub_results[0][0] or sub_results[1][0], f"{sub_results[0][1]} <b>or</b> {sub_results[1][1]}"),
        'xor': lambda sr: (sub_results[0][0] != sub_results[1][0], f"{sub_results[0][1]} <b>xor</b> {sub_results[1][1]}"),
        'not': lambda sr: (not sub_results[0][0], f"<b>not</b> {sub_results[0][1]}"),
        'true': lambda sr: (True, "true"),
        'false': lambda sr: (False, "false"),
    }

    name = result.get_name()
    operator = name if name in ('and', 'or', 'xor') else ('' if name == 'not' else None)

    if name == "field":
        value, text = field_values[result[0]], f"field.{result[0]}"
    elif name == "part":
        value, text = part_values[result[0]], f"part.{result[0]}"
    elif name == "bool":
        value, text = other_values[result[0]], f"{result[0]}"
    else:
        sub_results = [visual_debug(token, field_values, part_values, other_values, operator, False)
                       for token in result]
        value, text = functions[name](sub_results)

    if name in ('and', 'or', 'xor'):
        if outer_operator is not None and name != outer_operator:
            return value, f"<span class=\"block {'true' if value else 'false'}\"><b>(</b>{text}<b>)</b></span>"
        elif top_level:
            return value, f"<span class=\"block {'true' if value else 'false'}\">{text}</span>"
        else:
            return value, text
    elif name in ('true', 'false', 'field', 'part', 'bool'):
        return value, f"<span class=\"atom {'true' if value else 'false'}\">{text}</span>"
    elif name == 'not':
        return value, f"<span class=\"block {'true' if value else 'false'}\">{text}</span>"
    else:
        raise RuntimeError()
