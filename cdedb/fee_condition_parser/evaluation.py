
import dataclasses
from collections.abc import Set as AbstractSet
from datetime import date
from functools import partial
from typing import Callable

import pyparsing as pp


@dataclasses.dataclass
class ReferencedNames:
    field_names: set[str] = dataclasses.field(default_factory=set)
    part_names: set[str] = dataclasses.field(default_factory=set)

    def update(self, other: "ReferencedNames") -> None:
        self.field_names.update(other.field_names)
        self.part_names.update(other.part_names)


def check(result: pp.ParseResults, field_names: AbstractSet[str], part_names: AbstractSet[str]) -> None:
    rn = get_referenced_names(result)
    msgs = []
    if not rn.field_names <= field_names:
        msgs.append(f"Unknown field(s): {', '.join(repr(x) for x in sorted(rn.field_names - field_names))}.")
    if not rn.part_names <= part_names:
        msgs.append(f"Unknown part shortname(s): {', '.join(repr(x) for x in sorted(rn.part_names - part_names))}.")
    if msgs:
        raise RuntimeError(" ".join(msgs))


def get_referenced_names(result: pp.ParseResults | None) -> ReferencedNames:
    referenced_names = ReferencedNames()
    if result is None:
        return referenced_names
    if result.get_name() == "field":
        referenced_names.field_names.add(result[0])
    elif result.get_name() == "part":
        referenced_names.part_names.add(result[0])
    elif result.get_name() in {'and', 'or', 'xor'}:
        referenced_names.update(get_referenced_names(result[0]))
        referenced_names.update(get_referenced_names(result[1]))
    elif result.get_name() == 'not':
        referenced_names.update(get_referenced_names(result[0]))
    return referenced_names


def evaluate(result: pp.ParseResults, field_values: dict[str, bool], part_values: dict[str, bool],
             other_values: dict[str, bool], reference_date: date, birthday: date) -> bool:
    functions = {
        'and': lambda x: evaluate(x[0], field_values, part_values, other_values) and evaluate(x[1], field_values, part_values, other_values),
        'or': lambda x: evaluate(x[0], field_values, part_values, other_values) or evaluate(x[1], field_values, part_values, other_values),
        'xor': lambda x: evaluate(x[0], field_values, part_values, other_values) != evaluate(x[1], field_values, part_values, other_values),
        'not': lambda x: not evaluate(x[0], field_values, part_values, other_values),
        'true': lambda x_: True,
        'false': lambda x_: False,
        'field': lambda x: field_values[x[0]],
        'age': lambda x: (reference_date - birthday).days // 365 < int(x[0]), 
        'part': lambda x: part_values[x[0]],
        'bool': lambda x: other_values[x[0]],
    }
    # print(result.get_name())
    return functions[result.get_name()](result)
