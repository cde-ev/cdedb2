"""Base definition of CdEDB models using dataclasses."""
import abc
import copy
import dataclasses
from collections.abc import Collection
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Optional,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject
from cdedb.common.sorting import Sortkey, collate
from cdedb.common.validation.types import TypeMapping
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.database.query import (  # pylint: disable=ungrouped-imports
        DatabaseValue_s,
    )

NoneType = type(None)
T = TypeVar("T")
# Should actually be a vtypes.ProtoID instead of an int
CdEDataclassMap = dict[int, T]


def is_optional_type(type_: type[T]) -> bool:
    return get_origin(type_) is Union and NoneType in get_args(type_)


def requestdict_field_spec(field: dataclasses.Field[Any]) -> Literal["str", "[str]"]:
    """The spec of this field, expected by the REQUESTdatadict extractor."""
    # TODO whats about tuples, sets etc?
    if get_origin(field.type) is list:
        return "[str]"
    else:
        return "str"


@dataclass
class CdEDataclass:
    """

    The behavior of some of the default methods of this parent class can be modified by
    setting metadata on dataclass fields:

    - 'validation_exclude':
        If True, alway omit this field from `cls.validation_fields()`.
        Can be used for fields that are magically inserted elsewhere.
    - 'creation_exclude':
        If True, omit this field from `cls.validation_fields(creation=True)`.
        Can be used to make use of SQL default values.
    - 'update_exclude':
        If True, omit this field from `cls.validation_fields(creation=False)`.
        Can be used to make a field immutable.
    - 'creation_optional':
        If True, make this field optional in `cls.validation_fields(creation=True)`.
        Can be used to make use of SQL default values, while also allowing overrides.
    - 'request_exclude':
        If True, exclude the field from `cls.requestdict_fields()`.
        Can be used for fields that are not submitted via form, but taken from URL.
    - 'database_exclude':
        If True, exclude the field from `cls.database_fields()`, which excludes it from
        being written to or read from the database.
        Can be used for fields that are specifically calculated or magically inserted
        elsewhere.
    - 'database_include':
        If True, include the field in `cls.database_fields()` even if it would
        otherwise not be.
        Can be used to select fields with type list or set from the database.
    - 'asdict_exclude':
        If True, exclude the field from `self.asdict()`.
        Can be used to avoid read-only fields being validated.
    """
    id: vtypes.ProtoID

    database_table: ClassVar[str]
    entity_key: ClassVar[str] = "id"

    def to_database(self) -> CdEDBObject:
        """Generate a dict representation of this entity to be saved to the database."""
        database_fields = self.database_fields()
        values = vars(self)

        # Exclude fields marked as init=False.
        data = {
            field.name: values[field.name]
            for field in dataclasses.fields(self)
            if field.name in database_fields and field.init
        }

        # during creation the id is unknown
        if self.in_creation:
            del data["id"]
        return data

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        for field in dataclasses.fields(cls):
            # Convert enum fields into enum members.
            if isinstance(field.type, type) and issubclass(field.type, CdEIntEnum):
                if field.name in data:
                    data[field.name] = field.type(data[field.name])
            # Convert list[enum] fields into enum members.
            if get_origin(field.type) is list:
                if len(get_args(field.type)) == 1:
                    inner_type = get_args(field.type)[0]
                    if isinstance(inner_type, type):
                        if issubclass(inner_type, CdEIntEnum):
                            data[field.name] = list(
                                inner_type(x) for x in data[field.name])
        return cls(**data)

    @classmethod
    def many_from_database(cls, list_of_data: Collection[CdEDBObject],
                           ) -> CdEDataclassMap["Self"]:
        return {
            obj.id: obj for obj in map(cls.from_database, list_of_data)
        }

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: Optional[str] = None,
                         ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT {','.join(cls.database_fields())}
            FROM {cls.database_table}
            WHERE {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    @property
    def in_creation(self) -> bool:
        """This dataset will be used to create a new entity."""
        return self.id < 0

    @classmethod
    def validation_fields(cls, *, creation: bool) -> tuple[TypeMapping, TypeMapping]:
        """Map the field names to the type of the fields to validate this entity.

        This returns two TypeMapping tuples, for mandatory and optional validation
        fields, respectively. Each TypeMapping maps the name of the field to its type.
        """
        mandatory: TypeMapping = {}
        optional: TypeMapping = {}
        for field in dataclasses.fields(cls):
            if field.metadata.get('validation_exclude'):
                continue
            if creation:
                if field.metadata.get('creation_exclude'):
                    continue
                if field.metadata.get('creation_optional'):
                    optional[field.name] = field.type
                    continue
                if field.name == 'id':
                    mandatory[field.name] = vtypes.CreationID
                # Fields with init=False are optional, so that objects retrieved from
                #  the database can pass validation.
                elif is_optional_type(field.type) or not field.init:
                    optional[field.name] = field.type
                else:
                    mandatory[field.name] = field.type
            else:
                if field.metadata.get('update_exclude'):
                    continue
                if field.name == 'id':
                    mandatory[field.name] = vtypes.ID
                else:
                    optional[field.name] = field.type
        return mandatory, optional

    @classmethod
    def requestdict_fields(cls) -> list[tuple[str, Literal["str", "[str]"]]]:
        """Determine which fields of this entity are extracted via @REQUESTdatadict.

        This uses the database_fields by default, but may be overwritten if needed.
        """
        field_names = set(cls.database_fields())
        field_names.remove("id")
        fields = [
            field for field in dataclasses.fields(cls)
            if field.name in field_names
               and field.init
               and not field.metadata.get('request_exclude')
        ]
        return [(field.name, requestdict_field_spec(field)) for field in fields]

    @classmethod
    def database_fields(cls) -> list[str]:
        """List all fields of this entity which are saved to the database."""
        return [
            field.name for field in dataclasses.fields(cls)
            if field.init
               and get_origin(field.type) is not dict
               and get_origin(field.type) is not set
               and not field.metadata.get('database_exclude')
            or field.metadata.get('database_include')
        ]

    def as_dict(self) -> dict[str, Any]:
        """Return the fields of a dataclass instance as a new dictionary mapping
        field names to field values.

        This is an almost 1:1 copy of dataclasses.asdict. However, we need to exclude
        the backward references to avoid infinite recursion, so we need to dig into
        the implementation details here...
        """
        return self._asdict_inner(self, dict)

    def _asdict_inner(self, obj: Any,  # type: ignore[no-untyped-def]
                      dict_factory: Any):
        if dataclasses._is_dataclass_instance(obj):  # type: ignore[attr-defined] # pylint: disable=protected-access
            result = []
            for f in dataclasses.fields(obj):
                #######################################################
                # the following two lines are the only differences to #
                # dataclasses._as_dict_inner                          #
                #######################################################
                if not self._include_in_dict(f):
                    continue
                value = self._asdict_inner(getattr(obj, f.name), dict_factory)
                result.append((f.name, value))
            return dict_factory(result)
        elif isinstance(obj, tuple) and hasattr(obj, '_fields'):
            # obj is a namedtuple.  Recurse into it, but the returned
            # object is another namedtuple of the same type.  This is
            # similar to how other list- or tuple-derived classes are
            # treated (see below), but we just need to create them
            # differently because a namedtuple's __init__ needs to be
            # called differently (see bpo-34363).

            # I'm not using namedtuple's _asdict()
            # method, because:
            # - it does not recurse in to the namedtuple fields and
            #   convert them to dicts (using dict_factory).
            # - I don't actually want to return a dict here.  The main
            #   use case here is json.dumps, and it handles converting
            #   namedtuples to lists.  Admittedly we're losing some
            #   information here when we produce a json list instead of a
            #   dict.  Note that if we returned dicts here instead of
            #   namedtuples, we could no longer call asdict() on a data
            #   structure where a namedtuple was used as a dict key.

            return type(obj)(*[self._asdict_inner(v, dict_factory) for v in obj])
        elif isinstance(obj, (list, tuple)):
            # Assume we can create an object of this type by passing in a
            # generator (which is not true for namedtuples, handled
            # above).
            return type(obj)(self._asdict_inner(v, dict_factory) for v in obj)
        elif isinstance(obj, dict):
            return type(obj)((self._asdict_inner(k, dict_factory),
                              self._asdict_inner(v, dict_factory))
                             for k, v in obj.items())
        else:
            return copy.deepcopy(obj)

    @staticmethod
    def _include_in_dict(field: dataclasses.Field[Any]) -> bool:
        """Should this field be part of the dict representation of this object?"""
        if field.metadata.get('asdict_exclude'):
            return False
        # TODO: do not use the repr for this.
        return field.repr

    @abc.abstractmethod
    def get_sortkey(self) -> Sortkey:
        ...

    def _lt_inner(self, other: "CdEDataclass") -> bool:
        # Ensure natural sort. See xsorted for details.
        self_sort = self.get_sortkey() + (self.id,)
        other_sort = other.get_sortkey() + (other.id,)
        return tuple(map(collate, self_sort)) < tuple(map(collate, other_sort))

    def __lt__(self, other: "CdEDataclass") -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented

        return self._lt_inner(other)
