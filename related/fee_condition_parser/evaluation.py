
from functools import partial
from typing import Callable, Dict, AbstractSet

import pyparsing as pp


def check(result: pp.ParseResults, field_names: AbstractSet[str], part_names: AbstractSet[str]):
    if result.get_name() == "field":
        if not result[0] in field_names:
            raise RuntimeError(f"Unknown field '{result[0]}'")
    elif result.get_name() == "part":
        if not result[0] in part_names:
            raise RuntimeError(f"Unknown part shortname '{result[0]}'")
    elif result.get_name() in ('and', 'or', 'xor'):
        check(result[0], field_names, part_names)
        check(result[1], field_names, part_names)
    elif result.get_name() == 'not':
        check(result[0], field_names, part_names)


def evaluate(result: pp.ParseResults, field_values: Dict[str, bool], part_values: Dict[str, bool]) -> bool:
    functions = {
        'and': lambda x: evaluate(x[0], field_values, part_values) and evaluate(x[1], field_values, part_values),
        'or': lambda x: evaluate(x[0], field_values, part_values) or evaluate(x[1], field_values, part_values),
        'xor': lambda x: evaluate(x[0], field_values, part_values) != evaluate(x[1], field_values, part_values),
        'not': lambda x: not evaluate(x[0], field_values, part_values),
        'true': lambda x_: True,
        'false': lambda x_: False,
        'field': lambda x: field_values[x[0]],
        'part': lambda x: part_values[x[0]],
    }
    # print(result.get_name())
    return functions[result.get_name()](result)


#: Tuple (evaluator, evaluate_args) for each result Group name.
_EVALUATOR_FUNCTIONS = {
    'and': (lambda x, y, f, p: x(f, p) and y(f, p), True),
    'or': (lambda x, y, f, p: x(f, p) or y(f, p), True),
    'xor': (lambda x, y, f, p: x(f, p) != y(f, p), True),
    'not': (lambda x, f, p: not x(f, p), True),
    'true': (lambda f, p: True, False),
    'false': (lambda f, p: False, False),
    'field': (lambda t, f, p: f[t], False),
    'part': (lambda t, f, p: p[t], False),
}


def create_evaluator(result: pp.ParseResults) -> Callable[[Dict[str, bool], Dict[str, bool]], bool]:
    # num_bound_args = _EVALUATOR_NARY[result.get_name()]
    evaluator, evaluate_args = _EVALUATOR_FUNCTIONS[result.get_name()]
    if evaluate_args:
        return partial(evaluator, *(create_evaluator(token) for token in result))
    else:
        return partial(evaluator, *result)

