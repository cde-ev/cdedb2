"""Base definition of CdEDB models using dataclasses."""
import dataclasses
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING, Any, ClassVar, List, Literal, Tuple, Type, TypeVar, Union, get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes
from cdedb.common.validation.types import TypeMapping

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject

NoneType = type(None)
T = TypeVar("T")


def is_optional_type(type_: Type[T]) -> bool:
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
    id: vtypes.ProtoID

    database_table: ClassVar[str]

    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of this entity to be saved to the database."""
        data = {key: value for key, value in vars(self).items()
                if key in self.database_fields()}
        # during creation the id is unknown
        if self.in_creation:
            del data["id"]
        return data

    @property
    def in_creation(self) -> bool:
        """This dataset will be used to create a new entity."""
        return self.id < 0

    @classmethod
    def validation_fields(cls, *, creation: bool) -> Tuple[TypeMapping, TypeMapping]:
        """Map the field names to the type of the fields to validate this entity.

        This returns two TypeMapping tuples, for mandatory and optional validation
        fields, respectively. Each TypeMapping maps the name of the field to its type.
        """
        fields = {field.name: field for field in dataclasses.fields(cls)}
        # always special case the id, see below
        del fields["id"]
        mandatory = {name: field.type for name, field in fields.items()
                     if not is_optional_type(field.type)}
        optional = {name: field.type for name, field in fields.items()
                    if is_optional_type(field.type)}
        if creation:
            mandatory["id"] = vtypes.CreationID
        else:
            optional.update(mandatory)
            mandatory = {"id": vtypes.ID}
        return mandatory, optional

    @classmethod
    def requestdict_fields(cls) -> List[Tuple[str, Literal["str", "[str]"]]]:
        """Determine which fields of this entity are extracted via @REQUESTdatadict.

        This uses the database_fields by default, but may be overwritten if needed.
        """
        field_names = set(cls.database_fields())
        field_names.remove("id")
        fields = [field for field in dataclasses.fields(cls)
                  if field.name in field_names]
        return [(field.name, requestdict_field_spec(field)) for field in fields]

    @classmethod
    def database_fields(cls) -> List[str]:
        """List all fields of this entity which are saved to the database."""
        return [field.name for field in dataclasses.fields(cls)]
