"""Base definition of CdEDB models using dataclasses."""

import abc
import collections
import copy
import dataclasses
import functools
import inspect
import sys
import typing
from collections.abc import Collection
from dataclasses import dataclass
from enum import Flag, auto
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Self,
    cast,
    get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
from cdedb.common import (
    CdEDBObject,
    Error,
    get_mandatory_form_fields,
    get_mandatory_type,
    is_optional_type,
    json_serialize,
)
from cdedb.common.query import Query, QueryScope, QuerySpec
from cdedb.common.sorting import Sortkey, collate, xsorted
from cdedb.uncommon.intenum import CdEEnum, CdEIntEnum

if TYPE_CHECKING:
    from cdedb.database.query import DatabaseValue_s

# Should actually be a vtypes.ID instead of an int
type CdEDataclassMap[T] = dict[int, T]


def requestdict_field_spec(field: dataclasses.Field[Any]) -> Literal["str", "[str]"]:
    """The spec of this field, expected by the REQUESTdatadict extractor."""
    if get_origin(field.type) in {list, tuple, set}:
        if get_args(field.type) == (vtypes.PersonaID,):
            # For fields annotated as `list[vtypes.PersonaId]` we want to extract them
            #  as a CSV-string, rather than as a list from the multi dict.
            return "str"
        return "[str]"
    else:
        return "str"


class AbstractMetaData:
    """Boilerplate for metadata for CdEDataclass fields."""

    @classmethod
    def get_metadata_name(cls) -> str:
        return f"cdedb.{cls.__name__}"

    @property
    def as_dict(self) -> dict[str, Self]:
        """Hide boilerplate of turning the flag into a dict expected by `dataclasses.field`."""
        return {self.get_metadata_name(): self}


class AbstractFlag(AbstractMetaData, Flag):
    """Boilerplate for metadata flags for CdEDataclass fields."""

    @property
    def as_dict(self) -> dict[str, Self]:
        """Hide boilerplate of turning the flag into a dict expected by `dataclasses.field`."""
        return {self.get_metadata_name(): self}

    def in_field(self, field: dataclasses.Field[Any]) -> bool:
        """Hide boilerplate of extracting the flag information from `dataclasses.Field.metadata`."""
        return self in field.metadata.get(self.get_metadata_name(), self.__class__(0))


class MetaFlag(AbstractFlag):
    """Flags representing metadata of CdEDataclass fields."""

    none = 0
    """Named 'no flags' flag."""

    # validation

    validate_creation_exclude = auto()
    """Omit this field from `cls.validation_fields(creation=True)`.
    Can be used to make use of SQL default values."""
    validate_update_exclude = auto()
    """Omit this field from `cls.validation_fields(creation=False)`.
    Can be used to make a field immutable."""
    validate_include = auto()
    """Include this field in `cls.validation_fields()`.
    Can be used if the field would otherwise be automatically excluded, like
    a field containing another dataclass."""
    validate_exclude = validate_creation_exclude | validate_update_exclude
    """Omit this field from `cls.validation_fields()`.
    Can be used for fields that are magically inserted elsewhere."""
    validate_creation_optional = auto()
    """Make this field optional in `cls.validation_fields(creation=True)`.
    Can be used to make use of SQL default values, while also allowing overrides."""
    validate_update_mandatory = auto()
    """Make this field mandatory in `cls.validation_fields(creation=False)`.
    By default, all fields here are optional."""
    validate_creation_skip = auto()
    """Validate this field as `Any` in `cls.validation_fields(creation=True)`.
    Can be used for fields that are validated manually."""
    validate_update_skip = auto()
    """Validate this field as `Any` in `cls.validation_fields(creation=False)`.
    Can be used for fields that are validated manually."""
    validate_skip = validate_creation_skip | validate_update_skip
    """Validate this field as `Any` in `cls.validation_fields(creation=None)`.
    Can be used for fields that are validated manually."""

    # request

    request_creation_exclude = auto()
    """Omit this field from `cls.requestdict_fields(creation=True)`."""
    request_update_exclude = auto()
    """Omit this field from `cls.requestdict_fields(creation=False)`."""
    request_exclude = request_creation_exclude | request_update_exclude
    """Exclude the field from `cls.requestdict_fields()`.
    Can be used for fields that are not submitted via form, but taken from URL."""
    request_include = auto()
    """Include the field in `cls.requestdict_fields()` even if it would otherwise not be."""

    # validation + request

    input_creation_exclude = validate_creation_exclude | request_creation_exclude
    """Omit this field from request extraction and validation during entity creation."""
    input_update_exclude = validate_update_exclude | request_update_exclude
    """Omit this field from request extraction and validation during entity updates."""
    input_exclude = validate_exclude | request_exclude
    """Omit this field from request extraction and validation."""

    # database

    to_database_exclude = auto()
    """Exclude this field from being written to the database via `cls.to_database()`."""
    database_exclude = auto()
    """Exclude the field from `cls.database_fields()`, which excludes it from
    being written to or read from the database.
    Can be used for fields that are specifically calculated or magically inserted."""
    database_include = auto()
    """Include the field in `cls.database_fields()` even if it would otherwise not be.
    Can be used to select fields with type list or set from the database."""

    # request + database

    io_exclude = request_exclude | database_exclude
    """Omit this field from request extraction and being written to or read from the
    database."""

    # validation + request + database

    exclude = validate_exclude | request_exclude | database_exclude
    """Exclude this field from validation, request and database."""

    # asdict

    asdict_exclude = auto()
    """Exclude this field from `self.asdict()`. Useful for dicts nested in other dicts,
    making referential ids superfluous."""
    asdict_include = auto()
    """Include the field to `self.asdict()`, even if it would otherwise not be."""

    @functools.lru_cache
    @staticmethod
    def _all_cdedataclass_subclasses_names() -> set[str]:
        ret = set()
        subclasses = {cls for cls in CdEDataclass.__subclasses__()}
        while subclasses:
            cls = subclasses.pop()
            subclasses.update(cls.__subclasses__())
            ret.add(cls.__name__)
        return ret

    @staticmethod
    def is_excluded(type_: Any) -> bool:
        """Reveal if a field is excluded from all functions due to its type.

        We exclude all subclasses of CdEDataclass. Sadly, this is a somewhat
        lengthy and a bit ugly check, since we need to compare the name of
        the classes due to Forward References.
        """
        origin = typing.get_origin(type_)
        if is_optional_type(type_):
            type_ = typing.get_args(type_)[0]
        if origin in {list, set}:
            [type_] = typing.get_args(type_)
        # like dict[_, type_]
        if origin is dict:
            _, type_ = typing.get_args(type_)
        if origin is CdEDataclassMap:
            type_ = typing.get_args(type_)[0]
        # like "type_"
        if isinstance(type_, typing.ForwardRef):
            type_ = type_.__forward_arg__
        if inspect.isclass(type_):
            type_ = type_.__name__
        return type_ in MetaFlag._all_cdedataclass_subclasses_names()


@dataclass
class CdEDataclass:
    """Base class of all CdEDB dataclasses.

    The behavior of some of the default methods can be modified by setting metadata on
    dataclass fields via `metadata=MetaFlag.flag.as_dict`.
    """

    # for ephemeral instances, this is actually negative despite its annotation
    id: vtypes.ID = dataclasses.field(
        metadata=(
            MetaFlag.input_creation_exclude
            | MetaFlag.request_exclude
            | MetaFlag.validate_update_mandatory
        ).as_dict
    )

    database_table: ClassVar[str]
    entity_key: ClassVar[str] = "id"

    @classmethod
    def dataclass_fields(cls) -> tuple[dataclasses.Field[Any], ...]:
        """Determine the fields of this class.

        Should be overwritten if multiple dataclasses are nested in each other.
        Then, also from_database needs to be adjusted.
        """
        return dataclasses.fields(cls)

    def to_database(self) -> CdEDBObject:
        """Generate a dict representation of this entity to be saved to the database."""
        database_fields = self.database_fields()
        values = vars(self)

        data = {
            field.name: values[field.name]
            for field in self.dataclass_fields()
            if field.name in database_fields
            and not MetaFlag.to_database_exclude.in_field(field)
        }

        # Storing an ephemeral object to database corresponds to its creation. In this
        # case, the entity has no valid id, with the new id returned by sql_insert.
        if self.is_ephemeral:
            data.pop("id", None)
        return data

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        for field in cls.dataclass_fields():
            # Convert some values after extracting them from the database.
            type_ = field.type
            name = field.name
            # deduplicate conversion of optional and non-optional types
            if is_optional_type(type_):
                type_ = get_args(type_)[0]

            # Convert basic types.
            if isinstance(type_, type):
                # Convert enum fields into enum members.
                if issubclass(type_, (CdEEnum, CdEIntEnum)):
                    if data.get(name) is not None:
                        data[name] = type_(data[name])

            # Convert literal types.
            if get_origin(type_) == Literal:
                if len(set(get_args(type_))) == 1:
                    data[name] = get_args(type_)[0]

            # Convert array types.
            for array_type in {list, tuple, set}:
                if get_origin(type_) is array_type:
                    # No data, so nothing to convert.
                    if data.get(name) is None:
                        continue
                    data[name] = array_type(data[name])
                    # Check if we can convert the elements of the array.
                    if len(set(get_args(type_)) - {Ellipsis}) == 1 and isinstance(
                        (inner_type := get_args(type_)[0]), type
                    ):
                        # Convert list/set/tuple[enum] fields into enum members.
                        if issubclass(inner_type, (CdEEnum, CdEIntEnum)):
                            data[name] = array_type(inner_type(x) for x in data[name])
        return cls(**data)

    @classmethod
    def many_from_database(
        cls, list_of_data: Collection[CdEDBObject], sort: bool = True
    ) -> CdEDataclassMap["Self"]:
        sorter = xsorted if sort else list
        return {obj.id: obj for obj in sorter(map(cls.from_database, list_of_data))}

    @classmethod
    def many_from_database_list(
        cls, list_of_data: Collection[CdEDBObject]
    ) -> list["Self"]:
        return xsorted(map(cls.from_database, list_of_data))

    @classmethod
    def get_select_query(
        cls, entities: Collection[int], entity_key: str | None = None
    ) -> tuple[str, tuple["DatabaseValue_s", ...]]:
        query = f"""
            SELECT {','.join(cls.database_fields())}
            FROM {cls.database_table}
            WHERE {entity_key or cls.entity_key} = ANY(%s)
        """
        params = (entities,)
        return query, params

    @property
    def is_ephemeral(self) -> bool:
        """This dataset does not correspond to a entity stored in the database.

        For instance, it may be used to represent an entity to be created.
        Note that the id property is annotated as a positive integer. This is true for
        regular dataclass instances, which are retrieved from the database, but not true
        for ephemeral ones, which do not represent such data.

        Therefore, we exclude the id field in `to_database` and `_to_validation`.
        """
        return self.id < 0

    @classmethod
    def validation_fields(
        cls, *, creation: bool
    ) -> tuple[vtypes.MutableTypeMapping, vtypes.MutableTypeMapping]:
        """Map the field names to the type of the fields to validate this entity.

        This returns two TypeMapping tuples, for mandatory and optional validation
        fields, respectively. Each TypeMapping maps the name of the field to its type.
        """
        mandatory: vtypes.MutableTypeMapping = {}
        optional: vtypes.MutableTypeMapping = {}
        for field in cls.dataclass_fields():
            field_type = cast(type[Any], field.type)
            if (
                not creation and MetaFlag.validate_update_skip.in_field(field)
                or (creation and MetaFlag.validate_creation_skip.in_field(field))
            ):  # fmt: skip
                field_type = Any
            if state := cls._is_validation_field_mandatory(field, creation=creation):
                mandatory[field.name] = get_mandatory_type(field_type)
            elif state is None:
                continue
            else:
                optional[field.name] = field_type
        return mandatory, optional

    @classmethod
    def _is_validation_field_mandatory(
        cls, field: dataclasses.Field[Any], creation: bool
    ) -> bool | None:
        """Uninlined code to determine a fields validation status.

        Returns 'true' if the field is mandatory, 'false' if the field is optional,
        and 'None' if the field is excluded from validation.
        """
        if MetaFlag.is_excluded(field.type) and not MetaFlag.validate_include.in_field(field):  # fmt: skip
            return None
        if creation:
            if MetaFlag.validate_creation_exclude.in_field(field):
                return None
            elif MetaFlag.validate_creation_optional.in_field(field):
                return False
            elif (
                is_optional_type(field.type)
                # Fields with a default are optional at creation.
                or field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            ):
                return False
            else:
                return True
        else:  # noqa: PLR5501
            if MetaFlag.validate_update_exclude.in_field(field):
                return None
            elif MetaFlag.validate_update_mandatory.in_field(field):
                return True
            else:
                return False

    def _to_validation(self) -> CdEDBObject:
        """Generate a dict representation of this entity to be validated."""
        mandatory, optional = self.validation_fields(creation=self.is_ephemeral)
        values = vars(self)

        # include optional fields only if they are present
        data = {
            field.name: values[field.name]
            for field in self.dataclass_fields()
            if (
                field.name in mandatory
                or (field.name in optional and field.name in values)
            )
        }

        # during creation etc. the entity has no id, it is only a placeholder
        if self.is_ephemeral:
            data.pop("id", None)
        return data

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
        cls, *, creation: bool | None
    ) -> list[tuple[str, Literal["str", "[str]"]]]:
        """Determine which fields of this entity are extracted via @REQUESTdatadict.

        :param creation: If not None, possibly exclude some fields..
        """
        fields = []
        for field in cls.dataclass_fields():
            if not MetaFlag.request_include.in_field(field):
                if MetaFlag.is_excluded(field.type):
                    continue
                if MetaFlag.request_exclude.in_field(field):
                    continue
                if creation is True:
                    if MetaFlag.request_creation_exclude.in_field(field):
                        continue
                if creation is False:
                    if MetaFlag.request_update_exclude.in_field(field):
                        continue
            fields.append((field.name, requestdict_field_spec(field)))
        return fields

    @classmethod
    def database_fields(cls) -> list[str]:
        """List all fields of this entity which are saved to the database."""
        return [
            field.name
            for field in cls.dataclass_fields()
            if (
                (
                    not MetaFlag.is_excluded(field.type)
                    and not MetaFlag.database_exclude.in_field(field)
                )
                or MetaFlag.database_include.in_field(field)
            )
        ]

    def as_dict(self) -> dict[str, Any]:
        """Return the fields of a dataclass instance as a new dictionary mapping
        field names to field values.

        This is an almost 1:1 copy of dataclasses.asdict. However, we need to exclude
        the backward references to avoid infinite recursion, so we need to dig into
        the implementation details here...
        """
        return self._asdict_inner(self, dict)

    def _asdict_inner(  # type: ignore[no-untyped-def]
        self, obj: Any, dict_factory: Any
    ):
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
                             for k, v in obj.items())  # fmt: skip
        else:
            return copy.deepcopy(obj)

    @staticmethod
    def _include_in_dict(field: dataclasses.Field[Any]) -> bool:
        """Should this field be part of the dict representation of this object?"""
        return (
            MetaFlag.asdict_include.in_field(field)
            or not MetaFlag.is_excluded(field.type)
        ) and not MetaFlag.asdict_exclude.in_field(field)

    @abc.abstractmethod
    def get_sortkey(self) -> Sortkey: ...

    def _lt_inner(self, other: "CdEDataclass") -> bool:
        # Ensure natural sort. See xsorted for details.
        self_sort = self.get_sortkey() + (self.id,)
        other_sort = other.get_sortkey() + (other.id,)
        return tuple(map(collate, self_sort)) < tuple(map(collate, other_sort))

    def __lt__(self, other: "CdEDataclass") -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented

        return self._lt_inner(other)


@dataclasses.dataclass
class StoredQuery(CdEDataclass):
    id: vtypes.ID = dataclasses.field(metadata=MetaFlag.input_creation_exclude.as_dict)

    query_name: str

    scope: QueryScope = dataclasses.field(metadata=MetaFlag.request_exclude.as_dict)
    serialized_query: vtypes.QueryInput = dataclasses.field(
        metadata=MetaFlag.request_exclude.as_dict
    )
    errors: list["Error"] = dataclasses.field(
        default_factory=list,
        compare=False,
        repr=False,
        metadata=MetaFlag.exclude.as_dict,
    )

    query_group: str | None = None

    @property
    def user_created(self) -> bool:
        return bool(self.id and self.id > 0)

    def _get_spec(self) -> QuerySpec:
        return self.scope.get_spec()

    @functools.cached_property
    def query(self) -> Query | None:
        spec = self._get_spec()
        from cdedb.common.validation.validate import validate_check  # noqa: PLC0415

        query, errs = validate_check(
            vtypes.QueryInput,
            self.serialized_query,
            ignore_warnings=True,
            spec=spec,
        )
        if not query:
            self.errors = errs
            return None
        query.query_id = self.id
        return query

    def serialize_to_url(self) -> CdEDBObject:
        ret: CdEDBObject = {}
        if self.query:
            ret |= self.query.serialize_to_url()
        if self.user_created:
            ret |= {"query_name": self.query_name, "query_group": self.query_group}
        return ret

    def query_by_name(self) -> tuple[str, CdEDBObject]:
        if self.scope in {
            QueryScope.registration,
            QueryScope.lodgement,
            QueryScope.event_course,
        }:
            return "event/event_query_by_name", {"query_name": self.query_name}
        else:
            return "core/query_by_name", {
                "query_name": self.query_name,
                "scope": self.scope,
            }

    def to_database(self) -> CdEDBObject:
        ret = super().to_database()
        ret["serialized_query"] = json_serialize(self.serialized_query)
        return ret

    def get_sortkey(self) -> Sortkey:
        return (
            self.query_group or chr(sys.maxunicode),  # Sort empty group last.
            self.query_name,
        )

    @classmethod
    def group_queries(cls, queries: list[Self]) -> dict[str, list[Self]]:
        ret = collections.defaultdict(list)
        for q in xsorted(queries):
            ret[q.query_group or ""].append(q)
        return ret
