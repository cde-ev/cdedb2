"""Mangle data before inserting and after retrieving it from the database."""

import collections.abc
import enum
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    # Lazy import saves many dependecies for standalone ldaptor mode
    import psycopg2.extras

    from cdedb.common import CdEDBObject


# mypy treats all imports from psycopg2 as `Any`, so we do not gain anything by
# overloading the definition.
def from_db_output(
    output: Optional["psycopg2.extras.RealDictRow"]
) -> Optional["CdEDBObject"]:
    """Convert a :py:class:`psycopg2.extras.RealDictRow` into a normal
    :py:class:`dict`. We only use the outputs as dictionaries and
    the psycopg variant has some rough edges (e.g. it does not survive
    serialization).

    Also this wrapper allows future global modifications to the
    outputs, if we want to add some.
    """
    if not output:
        return None
    return dict(output)


# mypy cannot really understand the intricacies of what this function does, so
# we keep this simple. instead of overloading the definition.
def to_db_input(obj: Any) -> Union[Any, list[Any]]:
    """Mangle data to make psycopg happy.

    Convert :py:class:`tuple`s (and all other iterables, but not strings
    or mappings) into :py:class:`list`s. This is necesary because
    psycopg will fail to insert a tuple into an 'ANY(%s)' clause -- only
    a list does the trick.

    Convert :py:class:`enum.IntEnum` (and all other enums) into
    their numeric value. Everywhere else these automagically work
    like integers, but here they have to be handled explicitly.
    """
    if (isinstance(obj, collections.abc.Iterable)
            and not isinstance(obj, (str, collections.abc.Mapping))):
        return [to_db_input(x) for x in obj]
    elif isinstance(obj, enum.Enum):
        return obj.value
    else:
        return obj
