import dataclasses
from typing import (
    TYPE_CHECKING, Any, Dict, List, Optional, Type, TypeVar, Union, get_args,
    get_origin,
)

import cdedb.common.validation.types as vtypes

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject

NoneType = type(None)
T = TypeVar("T")


# TODO add proper overloading to soothe mypy
def field(*, default=dataclasses.MISSING, default_factory=dataclasses.MISSING,
          init: bool = True, repr: bool = True, hash: Optional[bool] = None,
          compare: bool = True, to_database: bool = True, is_optional: bool = False
          ) -> Any:
    metadata = {
        "cdedb": {
            "is_optional": is_optional,
            "to_database": to_database,
        }
    }
    return dataclasses.field(
        default=default, default_factory=default_factory, init=init, repr=repr,
        compare=compare, hash=hash, metadata=metadata)


def get_validator(field: dataclasses.Field[T]) -> Type[T]:
    """The type which is used to determine the appropriate validator."""
    return field.type
    # if field.metadata is None or "cdedb" not in field.metadata:
    #     # TODO which way?
    #     raise RuntimeError
    #     # return field.type
    # if "validator" not in field.metadata["cdedb"]:
    #     raise RuntimeError
    # return field.metadata["cdedb"]["validator"]


def is_optional_type(type_: Type[T]) -> bool:
    return get_origin(type_) is Union and NoneType in get_args(type_)


def is_optional_field(field: dataclasses.Field[T]) -> bool:
    """Is this field an optional _validation_ field or not?"""
    if (field.metadata is None
            or "cdedb" not in field.metadata
            or "is_optional" not in field.metadata["cdedb"]):
        return is_optional_type(get_validator(field))
    return field.metadata["cdedb"]["is_optional"]


def is_to_database(field: dataclasses.Field[T]) -> bool:
    """Is this field saved as part of _this_ dataclass to the database?"""
    if (field.metadata is None
            or "cdedb" not in field.metadata
            or "to_database" not in field.metadata["cdedb"]):
        # TODO which way?
        # raise RuntimeError(field)
        return True
    return field.metadata["cdedb"]["to_database"]


def is_from_request(field: dataclasses.Field[T]) -> bool:
    """Is this field taken via @REQUEST(DATA) decorator?"""
    if (field.metadata is None
            or "cdedb" not in field.metadata
            or "from_request" not in field.metadata["cdedb"]):
        # TODO which way?
        # raise RuntimeError(field)
        return True
    return field.metadata["cdedb"]["from_request"]


@dataclasses.dataclass
class CdEDataclass:
    id: vtypes.ID = field()

    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of this entity to be saved to the database."""
        database_field_names = {field.name for field in dataclasses.fields(self)
                                if is_to_database(field)}
        return {key: value for key, value in vars(self).items()
                if key in database_field_names}

    @classmethod
    def validation_fields(cls, *, mandatory: bool = False, optional: bool = False) -> Dict[str, Type[T]]:
        fields: Dict[str, dataclasses.Field[T]] = {
            field.name: field for field in dataclasses.fields(cls)}
        ret: Dict[str, Type[T]] = {}
        if mandatory:
            ret.update({name: get_validator(field) for name, field in fields.items()
                        if not is_optional_field(field)})
        if optional:
            ret.update({name: get_validator(field) for name, field in fields.items()
                       if is_optional_field(field)})
        return ret

    @classmethod
    def request_fields(cls) -> List[str]:
        # TODO Think this over when tackling more complex objects. It is easier and more
        #  accessible to add than to remove things though.
        request_fields = cls.database_fields()
        request_fields.remove("id")
        return request_fields

    @classmethod
    def database_fields(cls) -> List[str]:
        return [field.name for field in dataclasses.fields(cls)
                if is_to_database(field)]
