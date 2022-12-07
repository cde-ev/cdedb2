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
    id: vtypes.ID

    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of this entity to be saved to the database."""
        return {key: value for key, value in vars(self).items()
                if key in self.database_fields()}

    @classmethod
    def validation_fields(cls, *, creation: bool) -> Tuple[TypeMapping, TypeMapping]:
        all_fields = {field.name: field for field in fields(cls)}
        # always special case the id, see below
        del all_fields["id"]
        mandatory = {name: field.type for name, field in all_fields.items()
                     if not is_optional_type(field.type)}
        optional = {name: field.type for name, field in all_fields.items()
                    if is_optional_type(field.type)}
        if not creation:
            optional.update(mandatory)
            mandatory = {"id": vtypes.ID}
        return mandatory, optional

    @classmethod
    def request_fields(cls) -> List[str]:
        # TODO Think this over when tackling more complex objects. It is easier and more
        #  accessible to add than to remove things though.
        request_fields = cls.database_fields()
        request_fields.remove("id")
        return request_fields

    @classmethod
    def requestdict_fields(cls) -> List[Tuple[str, str]]:
        # Normally, the type of @REQUESTdata fields is inferred from the type annotation
        # of the respective frontend function.
        # In contrast, the types of @REQUESTdatadict are either "str" or "[str]" and not
        # inferred, default is "str".
        # So, we need to pass the information if a variable is of list type explicitly.
        # However, passing explicit types for @REQUESTdata will overwrite the type
        # annotation which feels undesired.
        # TODO this is not nice
        request_field_names = cls.database_fields()
        request_field_names.remove("id")
        request_fields = [field for field in fields(cls)
                          if field.name in request_field_names]
        # TODO whats about tuples, sets etc?
        return [(field.name, "[str]") if get_origin(field.type) is list
                else (field.name, "str") for field in request_fields]

    @classmethod
    def database_fields(cls) -> List[str]:
        return [field.name for field in fields(cls)]
