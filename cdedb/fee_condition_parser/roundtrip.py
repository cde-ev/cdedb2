import pyparsing as pp

from .evaluation import EvaluationData, evaluate


def serialize(result: pp.ParseResults, *, part_substitutions: dict[str, str] | None = None) -> str:
    """Public serialization interface, to get a normalized condition string.

    :param part_substitutions: Replace each part name in the dict with it's value.
    """
    return _serialize(result, outer_operator=None, ps=part_substitutions or {})


def _serialize(result: pp.ParseResults, outer_operator: str | None, ps: dict[str, str]) -> str:
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
        'age': lambda x: f"U{x[0]}",
    }
    name = result.get_name()
    if name in {'and', 'or', 'xor'} and outer_operator is not None and name != outer_operator:
        return f"({functions[name](result)})"
    else:
        return functions[name](result)


def visual_debug(
        result: pp.ParseResults,
        *,
        data: EvaluationData,
        outer_operator: str | None = None,
        top_level: bool = True,
        condition_only: bool = False,
) -> str:
    name = result.get_name()
    operator = name if name in {'and', 'or', 'xor'} else ('' if name == 'not' else None)

    if name == "field":
        text = f"field.{result[0]}"
    elif name == "part":
        text = f"part.{result[0]}"
    elif name == "age":
        text = f"U{result[0]}"
    elif name in {"bool"}:
        text = str(result[0])
    elif name in {"false", "true"}:
        text = name
    else:
        sub_results = [
            visual_debug(
                token, data=data, outer_operator=operator, top_level=False,
                condition_only=condition_only,
            )
            for token in result
        ]
        if name in {"and", "or", "xor"}:
            text = f"{sub_results[0]} <b>{name}</b> {sub_results[1]}"
        elif name == "not":
            text = f"<b>not</b> {sub_results[0]}"
        else:
            raise RuntimeError()  # pragma: no cover

    value = None if condition_only else evaluate(result, data)

    status = 'neutral' if value is None else 'true' if value else 'false'

    if name in {'and', 'or', 'xor'}:
        if outer_operator is not None and name != outer_operator:
            return f'<span class="block {status}"><b>(</b>{text}<b>)</b></span>'
        elif top_level:
            return f'<span class="block {status}">{text}</span>'
        else:
            return text
    elif name == 'not':
        return f'<span class="block {status}">{text}</span>'
    elif name in {'true', 'false', 'field', 'part', 'bool', 'age'}:
        class_ = f"atom {status}" if value is not None else ""
        return f'<span class="{class_}">{text}</span>'
    else:
        raise RuntimeError()  # pragma: no cover
