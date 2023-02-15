"""Base definition of CdEDB models using dataclasses."""

from dataclasses import dataclass, fields
from typing import (
    TYPE_CHECKING, List, Tuple, Type, TypeVar, Union, get_args, get_origin,
)

import cdedb.common.validation.types as vtypes
from cdedb.common.validation.types import TypeMapping

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject

NoneType = type(None)
T = TypeVar("T")


def is_optional_type(type_: Type[T]) -> bool:
    return get_origin(type_) is Union and NoneType in get_args(type_)


@dataclass
class CdEDataclass:
    id: vtypes.ProtoID

    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of this entity to be saved to the database."""
        data = {key: value for key, value in vars(self).items()
                if key in self.database_fields()}
        # during creation the id is unknown
        if self.is_created:
            del data["id"]
        return data

    @property
    def is_created(self) -> bool:
        """This dataset will be used to create a new entity."""
        return self.id < 0

    @classmethod
    def validation_fields(cls, *, creation: bool) -> Tuple[TypeMapping, TypeMapping]:
        """Map the field names to the type of the fields to validate this entity.

        This returns two TypeMapping tuples, for mandatory and optional validation
        fields, respectively. Each TypeMapping maps the name of the field to its type.
        """
        all_fields = {field.name: field for field in fields(cls)}
        # always special case the id, see below
        del all_fields["id"]
        mandatory = {name: field.type for name, field in all_fields.items()
                     if not is_optional_type(field.type)}
        optional = {name: field.type for name, field in all_fields.items()
                    if is_optional_type(field.type)}
        if creation:
            mandatory["id"] = vtypes.CreationID
        else:
            optional.update(mandatory)
            mandatory = {"id": vtypes.ID}
        return mandatory, optional

    # @classmethod
    # def request_fields(cls) -> List[str]:
        # TODO Think this over when tackling more complex objects. It is easier and more
        #  accessible to add than to remove things though.
        # request_fields = cls.database_fields()
        # request_fields.remove("id")
        # return request_fields

    @classmethod
    def requestdict_fields(cls) -> List[Tuple[str, str]]:
        """Determine which fields of this entity are extracted via @REQUESTdatadict.

        This uses the database_fields by default, but may be overwritten if needed.
        """
        request_field_names = set(cls.database_fields())
        request_field_names.remove("id")
        request_fields = [field for field in fields(cls)
                          if field.name in request_field_names]
        # TODO whats about tuples, sets etc?
        return [(field.name, "[str]") if get_origin(field.type) is list
                else (field.name, "str") for field in request_fields]

    @classmethod
    def database_fields(cls) -> List[str]:
        """List all fields of this entity which are saved to the database."""
        return [field.name for field in fields(cls)]
