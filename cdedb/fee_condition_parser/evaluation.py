import dataclasses
from functools import partial
from typing import AbstractSet, Callable, Dict, Tuple

import pyparsing as pp


@dataclasses.dataclass
class ReferencedNames:
    field_names: set[str] = dataclasses.field(default_factory=set)
    part_names: set[str] = dataclasses.field(default_factory=set)

    def update(self, other: "ReferencedNames") -> None:
        self.field_names.update(other.field_names)
        self.part_names.update(other.part_names)

    def __add__(self, other: "ReferencedNames") -> "ReferencedNames":
        return self.__class__(self.field_names | other.field_names, self.part_names | other.part_names)


def check(result: pp.ParseResults, field_names: AbstractSet[str], part_names: AbstractSet[str]) -> None:
    rn = get_referenced_names(result)
    msgs = []
    if not rn.field_names <= field_names:
        msgs.append(f"Unknown field(s): {', '.join(repr(x) for x in sorted(rn.field_names - field_names))}.")
    if not rn.part_names <= part_names:
        msgs.append(f"Unknown part shortname(s): {', '.join(repr(x) for x in sorted(rn.part_names - part_names))}.")
    if msgs:
        raise RuntimeError(" ".join(msgs))


def get_referenced_names(result: pp.ParseResults) -> ReferencedNames:
    referenced_names = ReferencedNames()
    if result.get_name() == "field":
        referenced_names.field_names.add(result[0])
    elif result.get_name() == "part":
        referenced_names.part_names.add(result[0])
    elif result.get_name() in ('and', 'or', 'xor'):
        referenced_names.update(get_referenced_names(result[0]))
        referenced_names.update(get_referenced_names(result[1]))
    elif result.get_name() == 'not':
        referenced_names.update(get_referenced_names(result[0]))
    return referenced_names


def evaluate(result: pp.ParseResults, field_values: Dict[str, bool], part_values: Dict[str, bool],
             other_values: Dict[str, bool]) -> bool:
    functions = {
        'and': lambda x: evaluate(x[0], field_values, part_values, other_values) and evaluate(x[1], field_values, part_values, other_values),
        'or': lambda x: evaluate(x[0], field_values, part_values, other_values) or evaluate(x[1], field_values, part_values, other_values),
        'xor': lambda x: evaluate(x[0], field_values, part_values, other_values) != evaluate(x[1], field_values, part_values, other_values),
        'not': lambda x: not evaluate(x[0], field_values, part_values, other_values),
        'true': lambda x_: True,
        'false': lambda x_: False,
        'field': lambda x: field_values[x[0]],
        'part': lambda x: part_values[x[0]],
        'bool': lambda x: other_values[x[0]],
    }
    # print(result.get_name())
    return functions[result.get_name()](result)


#: Tuple (evaluator, evaluate_args) for each result Group name.
_EVALUATOR_FUNCTIONS: Dict[str, Tuple[Callable[..., bool], bool]] = {
    'and': (lambda x, y, f, p, o: x(f, p, o) and y(f, p, o), True),
    'or': (lambda x, y, f, p, o: x(f, p, o) or y(f, p, o), True),
    'xor': (lambda x, y, f, p, o: x(f, p, o) != y(f, p, o), True),
    'not': (lambda x, f, p, o: not x(f, p, o), True),
    'true': (lambda f, p, o: True, False),
    'false': (lambda f, p,o : False, False),
    'field': (lambda t, f, p, o: f[t], False),
    'part': (lambda t, f, p, o: p[t], False),
    'bool': (lambda t, f, p, o: o[t], False),
}


def create_evaluator(result: pp.ParseResults) -> Callable[[Dict[str, bool], Dict[str, bool]], bool]:
    # num_bound_args = _EVALUATOR_NARY[result.get_name()]
    evaluator, evaluate_args = _EVALUATOR_FUNCTIONS[result.get_name()]
    if evaluate_args:
        return partial(evaluator, *(create_evaluator(token) for token in result))
    else:
        return partial(evaluator, *result)
