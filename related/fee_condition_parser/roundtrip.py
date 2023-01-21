from typing import Optional, Dict, Callable, List, Tuple

import pyparsing as pp


def serialize(result: pp.ParseResults, parenthesis_if_not: Optional[str] = None) -> str:
    functions = {
        'and': lambda x: f"{serialize(x[0], 'and')} and {serialize(x[1], 'and')}",
        'or': lambda x: f"{serialize(x[0], 'or')} or {serialize(x[1], 'or')}",
        'xor': lambda x: f"{serialize(x[0], 'xor')} xor {serialize(x[1], 'xor')}",
        'not': lambda x: f"not {serialize(x[0], '')}",
        'true': lambda x_: "true",
        'false': lambda x_: "false",
        'field': lambda x: f"field.{x[0]}",
        'part': lambda x: f"part.{x[0]}",
    }
    name = result.get_name()
    if name in ('and', 'or', 'xor') and parenthesis_if_not is not None and name != parenthesis_if_not:
        return f"({functions[name](result)})"
    else:
        return functions[name](result)


def visual_debug(result: pp.ParseResults, field_values: Dict[str, bool], part_values: Dict[str, bool],
                 parenthesis_if_not: Optional[str] = None, top_level: bool = True) -> (bool, str):
    functions: Dict[str, Callable[[List[Tuple[bool, str]]], Tuple[bool, str]]] = {
        'and': lambda sr: (sub_results[0][0] and sub_results[1][0], f"{sub_results[0][1]} <b>and</b> {sub_results[1][1]}"),
        'or': lambda sr: (sub_results[0][0] or sub_results[1][0], f"{sub_results[0][1]} <b>or</b> {sub_results[1][1]}"),
        'xor': lambda sr: (sub_results[0][0] != sub_results[1][0], f"{sub_results[0][1]} <b>xor</b> {sub_results[1][1]}"),
        'not': lambda sr: (not sub_results[0][0], f"<b>not</b> {sub_results[0][1]}"),
        'true': lambda sr: (True, "true"),
        'false': lambda sr: (False, "false"),
    }

    name = result.get_name()
    sub_parenthesis_if_not = name if name in ('and', 'or', 'xor') else '' if name == 'not' else None

    if name == "field":
        value, text = field_values[result[0]], f"field.{result[0]}"
    elif name == "part":
        value, text = field_values[result[0]], f"part.{result[0]}"
    else:
        sub_results = [visual_debug(token, field_values, part_values, sub_parenthesis_if_not, False)
                       for token in result]
        value, text = functions[name](sub_results)

    if name in ('and', 'or', 'xor'):
        if parenthesis_if_not is not None and name != parenthesis_if_not:
            return value, f"<span class=\"block {'true' if value else 'false'}\"><b>(</b>{text}<b>)</b></span>"
        elif top_level:
            return value, f"<span class=\"block {'true' if value else 'false'}\">{text}</span>"
        else:
            return value, text
    elif name in ('true', 'false', 'field', 'part'):
        return value, f"<span class=\"atom {'true' if value else 'false'}\">{text}</span>"
    elif name == 'not':
        return value, f"<span class=\"block {'true' if value else 'false'}\">{text}</span>"
    else:
        raise RuntimeError()
