"""Base definition of CdEDB models using dataclasses."""
import abc
import copy
import dataclasses
from collections.abc import Collection
from dataclasses import dataclass
from enum import Flag, auto
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    TypeVar,
    cast,
    get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
from cdedb.common import CdEDBObject, get_mandatory_form_fields, is_optional_type
from cdedb.common.sorting import Sortkey, collate, xsorted
from cdedb.uncommon.intenum import CdEEnum, CdEIntEnum

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.database.query import (
        DatabaseValue_s,
    )

T = TypeVar("T")
# Should actually be a vtypes.ProtoID instead of an int
CdEDataclassMap = dict[int, T]


def requestdict_field_spec(field: dataclasses.Field[Any]) -> Literal["str", "[str]"]:
    """The spec of this field, expected by the REQUESTdatadict extractor."""
    # TODO whats about tuples, sets etc?
    if get_origin(field.type) is list:
        return "[str]"
    else:
        return "str"


class MetaFlag(Flag):
    """Flags representing metadata of CdEDataclass fields."""

    none = 0

    # validation

    # TODO is is currently also used in request_fields
    creation_exclude = auto()
    """Omit this field from `cls.validation_fields(creation=False)`.\\
    Can be used to make a field immutable."""
    # TODO is is currently also used in request_fields
    update_exclude = auto()
    """Omit this field from `cls.validation_fields(creation=True)`.\\
    Can be used to make use of SQL default values."""
    validation_exclude = creation_exclude | update_exclude
    """Omit this field from `cls.validation_fields()`.\\
    Can be used for fields that are magically inserted elsewhere."""
    creation_optional = auto()
    """Make this field optional in `cls.validation_fields(creation=True)`.\\
    Can be used to make use of SQL default values, while also allowing overrides."""

    # request

    creation_request_exclude = auto()
    """Omit this field from `cls.requestdict_fields(creation=False)`.\\
    """
    update_request_exclude = auto()
    """Omit this field from `cls.requestdict_fields(creation=True)`.\\
    """
    request_exclude = creation_request_exclude | update_request_exclude
    """Exclude the field from `cls.requestdict_fields()`.\\
    Can be used for fields that are not submitted via form, but taken from URL."""

    # database

    database_exclude = auto()
    """Exclude the field from `cls.database_fields()`, which excludes it from
    being written to or read from the database.\\
    Can be used for fields that are specifically calculated or magically inserted."""

    database_include = auto()
    """Include the field in `cls.database_fields()` even if it would otherwise not be.\\
    Can be used to select fields with type list or set from the database."""

    # asdict

    # TODO is this necessary? the stated purpose should be achieved via validation_exclude
    asdict_exclude = auto()
    """If True, exclude the field from `self.asdict()`.\\
    Can be used to avoid read-only fields being validated."""


@dataclass
class CdEDataclass:
    """Base class of all CdEDB dataclasses.

    The behavior of some of the default methods can be modified by setting metadata on
    dataclass fields via `metadata={"cdedb": MetaFlag.flag}`.
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
            if isinstance(field.type, type):
                if issubclass(field.type, (CdEEnum, CdEIntEnum)):
                    if field.name in data:
                        data[field.name] = field.type(data[field.name])

            # Convert optional enum fields into enum members.
            if is_optional_type(field.type):
                if len(get_args(field.type)) == 2:
                    inner_type = get_args(field.type)[0]
                    if isinstance(inner_type, type):
                        if issubclass(inner_type, (CdEEnum, CdEIntEnum)):
                            if data.get(field.name) is not None:
                                data[field.name] = inner_type(data[field.name])

            # Convert list[enum] fields into enum members.
            if get_origin(field.type) is list:
                if len(get_args(field.type)) == 1:
                    inner_type = get_args(field.type)[0]
                    if isinstance(inner_type, type):
                        if issubclass(inner_type, (CdEEnum, CdEIntEnum)):
                            data[field.name] = list(
                                inner_type(x) for x in data[field.name])
        return cls(**data)

    @classmethod
    def many_from_database(cls, list_of_data: Collection[CdEDBObject],
                           ) -> CdEDataclassMap["Self"]:
        return {
            obj.id: obj for obj in xsorted(map(cls.from_database, list_of_data))
        }

    @classmethod
    def get_select_query(cls, entities: Collection[int],
                         entity_key: str | None = None,
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
    def validation_fields(
            cls, *, creation: bool,
    ) -> tuple[vtypes.MutableTypeMapping, vtypes.MutableTypeMapping]:
        """Map the field names to the type of the fields to validate this entity.

        This returns two TypeMapping tuples, for mandatory and optional validation
        fields, respectively. Each TypeMapping maps the name of the field to its type.
        """
        mandatory: vtypes.MutableTypeMapping = {}
        optional: vtypes.MutableTypeMapping = {}
        for field in dataclasses.fields(cls):
            field.type = cast(type[Any], field.type)
            if MetaFlag.validation_exclude in field.metadata.get('cdedb', MetaFlag.none):
                continue
            if creation:
                if MetaFlag.creation_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
                if MetaFlag.creation_optional in field.metadata.get('cdedb', MetaFlag.none):
                    optional[field.name] = field.type
                    continue
                if field.name == 'id':
                    mandatory[field.name] = vtypes.CreationID
                elif (
                        is_optional_type(field.type)
                        # Fields with init=False are optional, so that objects
                        #  retrieved from the database can pass validation.
                        or not field.init
                        # Fields with a default are optional at creation.
                        or field.default is not dataclasses.MISSING
                        or field.default_factory is not dataclasses.MISSING
                ):
                    optional[field.name] = field.type
                else:
                    mandatory[field.name] = field.type
            else:
                if MetaFlag.update_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
                if field.name == 'id':
                    mandatory[field.name] = vtypes.ID
                else:
                    optional[field.name] = field.type
        return mandatory, optional

    @classmethod
    def mandatory_form_fields(cls, *, creation: bool) -> set[str]:
        """Determine fields where user needs to enter something.

        We cannot use `validation_fields` for this - that also has a distinction of
        mandatory and optional fields, but with different semantics. Mandatory there
        means that the value needs to be given for validating this object, but it may be
        `None`. `None` (or the empty string) is not considered a valid input for the
        fields returned by this function.
        """
        return get_mandatory_form_fields(*cls.validation_fields(creation=creation))

    @classmethod
    def requestdict_fields(
            cls, *, creation: bool | None,
    ) -> list[tuple[str, Literal["str", "[str]"]]]:
        """Determine which fields of this entity are extracted via @REQUESTdatadict.

        This uses the database_fields by default, but may be overwritten if needed.

        :param creation: If not None, possibly exclude some fields..
        """
        field_names = set(cls.database_fields())
        field_names.discard("id")
        fields = []
        for field in dataclasses.fields(cls):
            if field.name not in field_names:
                continue
            if MetaFlag.request_exclude in field.metadata.get('cdedb', MetaFlag.none):
                continue
            if not field.init:
                continue
            if creation is True:
                if MetaFlag.creation_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
                if MetaFlag.creation_request_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
            if creation is False:
                if MetaFlag.update_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
                if MetaFlag.update_request_exclude in field.metadata.get('cdedb', MetaFlag.none):
                    continue
            fields.append((field.name, requestdict_field_spec(field)))
        return fields

    @classmethod
    def database_fields(cls) -> list[str]:
        """List all fields of this entity which are saved to the database."""
        return [
            field.name for field in dataclasses.fields(cls)
            if field.init
               and get_origin(field.type) is not dict
               and get_origin(field.type) is not set
               and MetaFlag.database_exclude not in field.metadata.get('cdedb', MetaFlag.none)
            or MetaFlag.database_include in field.metadata.get('cdedb', MetaFlag.none)
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
        if dataclasses._is_dataclass_instance(obj):  # type: ignore[attr-defined]
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
        if MetaFlag.asdict_exclude in field.metadata.get('cdedb', MetaFlag.none):
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
