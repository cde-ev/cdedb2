import abc
import dataclasses
from typing import Any, ClassVar, cast

from typing_extensions import TypeForm

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.event as models


@dataclasses.dataclass
class BuiltinQuestionnaireBlock(abc.ABC):
    enum_member: ClassVar[const.QuestionnaireBuiltinElement]
    valid_kinds: ClassVar[set[const.QuestionnaireUsages]]
    readonly: ClassVar[bool] = False

    event: models.Event
    aux: None

    @staticmethod
    def get_class(
        enum_member: const.QuestionnaireBuiltinElement,
    ) -> type["BuiltinQuestionnaireBlock"]:
        for cls in BuiltinQuestionnaireBlock.__subclasses__():
            if cls.enum_member == enum_member:
                return cls
        raise KeyError

    @classmethod
    def get_aux_type(cls) -> TypeForm[Any]:
        print(cls)
        for field in dataclasses.fields(cls):
            if field.name == "aux":
                if field.type is None:
                    return type(None)
                return cast(TypeForm[Any], field.type)
        return None

    @property
    def name(self) -> str:
        return self.__class__.__qualname__

    @abc.abstractmethod
    def is_valid_aux(self) -> bool: ...


@dataclasses.dataclass
class CourseChoices(BuiltinQuestionnaireBlock):
    enum_member = const.QuestionnaireBuiltinElement.course_choices
    valid_kinds = {const.QuestionnaireUsages.registration}

    aux: vtypes.ID | None  # type: ignore[assignment]

    def is_valid_aux(self) -> bool:
        if self.aux is None:
            return False
        return self.aux in self.event.tracks


@dataclasses.dataclass
class FeePreview(BuiltinQuestionnaireBlock):
    enum_member = const.QuestionnaireBuiltinElement.fee_preview
    valid_kinds = {
        const.QuestionnaireUsages.registration,
        const.QuestionnaireUsages.additional,
    }
    readonly = True

    def is_valid_aux(self) -> bool:
        return self.aux is None
