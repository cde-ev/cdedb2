# pylint: disable=line-too-long,missing-module-docstring
from typing import Dict

import pyparsing as pp


def rename(result: pp.ParseResults, field_name_updates: Dict[str, str], part_shortname_updates: Dict[str, str]) -> None:
    name = result.get_name()
    if name == 'field':
        if result[0] in field_name_updates:
            result[0] = field_name_updates[result[0]]
    elif name == 'part':
        if result[0] in part_shortname_updates:
            result[0] = part_shortname_updates[result[0]]
    else:
        for token in result:
            rename(token, field_name_updates, part_shortname_updates)
