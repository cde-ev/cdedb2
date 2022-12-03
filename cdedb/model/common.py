import dataclasses
from typing import TYPE_CHECKING, Any, Dict, Type

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject


def metadata(validator: Type, *, to_database: bool = True) -> Dict[str, Any]:
    return {
        "cdedb": {
            "validator": validator,
            "to_database": to_database,
        }
    }


def get_validator(field: dataclasses.Field) -> Type:
    if field.metadata is None or "cdedb" not in field.metadata:
        # TODO which way?
        raise RuntimeError
        # return field.type
    if "validator" not in field.metadata["cdedb"]:
        raise RuntimeError
    return field.metadata["cdedb"]["validator"]


def to_database(field: dataclasses.Field) -> bool:
    if field.metadata is None or "cdedb" not in field.metadata:
        # TODO which way?
        raise RuntimeError
        # return True
    if "to_database" not in field.metadata["cdedb"]:
        raise RuntimeError
    return field.metadata["cdedb"]["to_database"]



@dataclasses.dataclass
class CdEDataclass:
    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of this entity to be saved to the database."""
        fields = dataclasses.fields(self)
        return {field.name: getattr(self, field.name)
                for field in fields if to_database(field)}
