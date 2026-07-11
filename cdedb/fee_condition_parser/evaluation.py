import dataclasses
from collections.abc import Set as AbstractSet
from datetime import date
from typing import TypedDict, cast

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
        referenced_names.field_names.add(cast(str, result[0]))
    elif result.get_name() == "part":
        referenced_names.part_names.add(cast(str, result[0]))
    elif result.get_name() in {'and', 'or', 'xor'}:
        referenced_names.update(get_referenced_names(cast(pp.ParseResults, result[0])))
        referenced_names.update(get_referenced_names(cast(pp.ParseResults, result[1])))
    elif result.get_name() == 'not':
        referenced_names.update(get_referenced_names(cast(pp.ParseResults, result[0])))
    return referenced_names


class EvaluationData(TypedDict):
    field_values: dict[str, bool]
    part_values: dict[str, bool]
    other_values: dict[str, bool]
    reference_date: date
    birthday: date


def is_below_age(data: EvaluationData, age: int) -> bool:
    reference_date, birthday = data['reference_date'], data['birthday']
    years = reference_date.year - birthday.year

    if (reference_date.month, reference_date.day) < (birthday.month, birthday.day):
        years -= 1

    return years < age


def evaluate(result: pp.ParseResults, data: EvaluationData) -> bool:
    functions = {
        'and': lambda x: evaluate(x[0], data) and evaluate(x[1], data),
        'or': lambda x: evaluate(x[0], data) or evaluate(x[1], data),
        'xor': lambda x: evaluate(x[0], data) != evaluate(x[1], data),
        'not': lambda x: not evaluate(x[0], data),
        'true': lambda x_: True,
        'false': lambda x_: False,
        'field': lambda x: data['field_values'][x[0]],
        'age': lambda x: is_below_age(data, int(x[0])),
        'part': lambda x: data['part_values'][x[0]],
        'bool': lambda x: data['other_values'][x[0]],
    }
    # print(result.get_name())
    return functions[str(result.get_name())](result)
