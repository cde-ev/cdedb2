import abc
import collections
import dataclasses
import enum
from collections.abc import Collection, Mapping
from typing import Any, ClassVar, Self, cast

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, cast_field_value
from cdedb.common.sorting import Sortkey
from cdedb.config import Config
from cdedb.models.common import CdEDataclassMap, MetaFlag as Meta
from cdedb.models.event import Event, EventDataclass, EventFee, EventField

CONF = Config()


class QuestionnaireFrequency(enum.Enum):
    disallowed = enum.auto()
    optional = enum.auto()
    mandatory = enum.auto()

    def allows(self, num: int = 1) -> bool:
        if self == self.disallowed:
            return num == 0
        if self == self.mandatory:
            return num > 0
        return True


@dataclasses.dataclass
class QuestionnaireRow(EventDataclass, abc.ABC):
    id: vtypes.ID = dataclasses.field(
        init=False,
        default=vtypes.ID(-1),
        compare=False,
        repr=False,
        metadata=(Meta.exclude | Meta.asdict_exclude).as_dict,
    )
    event_id: vtypes.ID = dataclasses.field(
        metadata=(Meta.request_exclude | Meta.asdict_exclude).as_dict,
    )
    kind: const.QuestionnaireUsages
    pos: int

    questionnaire: "Questionnaire" = dataclasses.field(
        init=False,
        compare=False,
        repr=False,
        metadata=(Meta.exclude | Meta.asdict_exclude).as_dict,
    )

    role: const.QuestionnaireRowRole
    _role: ClassVar[const.QuestionnaireRowRole]
    _frequency: ClassVar[
        QuestionnaireFrequency | dict[const.QuestionnaireUsages, QuestionnaireFrequency]
    ]
    static: ClassVar[bool] = False

    @property
    def name(self) -> str:
        return self.__class__.__qualname__

    @classmethod
    def allowed_frequency(
        cls, kind: const.QuestionnaireUsages
    ) -> QuestionnaireFrequency:
        if isinstance(cls._frequency, QuestionnaireFrequency):
            return cls._frequency
        return cls._frequency.get(kind, QuestionnaireFrequency.disallowed)

    @classmethod
    @abc.abstractmethod
    def get_drow_html_classes(cls) -> list[str]: ...

    @classmethod
    @abc.abstractmethod
    def get_icon(cls) -> str: ...

    @staticmethod
    def get_class(
        role: const.QuestionnaireRowRole,
    ) -> type["QuestionnaireRow"]:
        for cls in (
            QuestionnaireRow.__subclasses__()
            + QuestionnaireMagicRow.__subclasses__()
            + QuestionnaireTextRowMeta.__subclasses__()
        ):
            if cls is QuestionnaireMagicRow or cls is QuestionnaireTextRowMeta:
                continue
            if cls._role == role:
                return cls
        raise KeyError(role)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "QuestionnaireRow":
        role = const.QuestionnaireRowRole(data["role"])
        return cls.get_class(role).from_database(data)

    def get_sortkey(self) -> Sortkey:
        return (
            self.kind,
            self.pos,
        )

    @classmethod
    def validation_fields(
        cls, *, creation: bool
    ) -> tuple[vtypes.MutableTypeMapping, vtypes.MutableTypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        # During questionnaire import the field id can be negative and the field can
        #  instead be identified by name. The validation still ensures that the field
        #  "exists", even if the id is negative during validation.
        optional["field_id"] = vtypes.PartialImportID | None
        optional["field_name"] = vtypes.RestrictiveIdentifier | None
        return mandatory, optional

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, QuestionnaireRow):
            return NotImplemented
        return self._lt_inner(other)


@dataclasses.dataclass
class QuestionnaireTextRowMeta(QuestionnaireRow):
    database_table = "event.questionnaire_text_rows"
    _frequency = QuestionnaireFrequency.optional
    static = True

    text: str | None
    title: str | None

    @classmethod
    def from_database(cls, data: CdEDBObject) -> Self:
        return super(QuestionnaireRow, cls).from_database(data)

    @classmethod
    def get_drow_html_classes(cls) -> list[str]:
        return ["shaded-info"]


@dataclasses.dataclass
class QuestionnaireTextRow(QuestionnaireTextRowMeta):
    _role = const.QuestionnaireRowRole.text

    text: str
    title: None = dataclasses.field(default=None, metadata=Meta.request_exclude.as_dict)

    @classmethod
    def get_icon(cls) -> str:
        return "bars"


@dataclasses.dataclass(kw_only=True)
class QuestionnaireHeadingRow(QuestionnaireTextRowMeta):
    _role = const.QuestionnaireRowRole.heading

    text: None = dataclasses.field(default=None, metadata=Meta.request_exclude.as_dict)
    title: str

    @classmethod
    def get_icon(cls) -> str:
        return "align-left"


@dataclasses.dataclass
class QuestionnaireFieldRow(QuestionnaireRow):
    database_table = "event.questionnaire_field_rows"
    _role = const.QuestionnaireRowRole.event_field
    _frequency = QuestionnaireFrequency.optional
    static = True

    field_id: vtypes.ID
    field: EventField = dataclasses.field(
        init=False,
        default=cast(EventField, None),
        repr=False,
        compare=False,
        metadata=(Meta.exclude | Meta.asdict_exclude).as_dict,
    )
    label: str | None
    info: str | None

    readonly: bool = False
    default_value: Any = None  # TODO: ByDatafieldKind maybe some union?

    @classmethod
    def get_icon(cls) -> str:
        return "pen-to-square"

    def get_label(self) -> str:
        return self.label or self.field.title

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        event: Event = data.pop("event")
        ret = super(QuestionnaireRow, cls).from_database(data)
        ret.field = event.fields[ret.field_id]

        # Deserialize the stored string into the datatype of the field if able.
        ret.default_value = cast_field_value(ret.default_value, ret.field.kind)
        # Special case for datetimes: Convert them to the default timezone so
        #  they can be submitted again even without the timezone.
        #  This is required for use with 'datetime-local' inputs.
        if ret.field.kind == const.FieldDatatypes.datetime:
            if ret.default_value:
                ret.default_value = ret.default_value.astimezone(
                    CONF["DEFAULT_TIMEZONE"]
                )

        return ret

    @classmethod
    def get_drow_html_classes(cls) -> list[str]:
        return []


@dataclasses.dataclass
class QuestionnaireMagicRow(QuestionnaireRow):
    database_table = "event.questionnaire_magic_rows"

    @classmethod
    def get_icon(cls) -> str:
        return "wand-magic-sparkles"

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "QuestionnaireMagicRow":
        role = const.QuestionnaireRowRole(data["role"])
        return cast(
            QuestionnaireMagicRow,
            super(QuestionnaireRow, role.get_class()).from_database(data),
        )

    @classmethod
    def get_drow_html_classes(cls) -> list[str]:
        return ["shaded-magic"]


@dataclasses.dataclass
class CourseChoices(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.course_choices
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory
    }

    @classmethod
    def get_icon(cls) -> str:
        return "book"


@dataclasses.dataclass
class PartSelection(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.part_selection
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory
    }

    @classmethod
    def get_icon(cls) -> str:
        return "clock"


@dataclasses.dataclass
class FeePreview(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.fee_preview
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory,
    }
    static = True

    @classmethod
    def get_icon(cls) -> str:
        return "coins"


@dataclasses.dataclass
class ListConsent(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.list_consent
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory,
    }

    @classmethod
    def get_icon(cls) -> str:
        return "address-card"


@dataclasses.dataclass
class MixedLodging(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.mixed_lodging
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory,
    }

    @classmethod
    def get_icon(cls) -> str:
        return "venus-mars"


@dataclasses.dataclass
class FotoNotice(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.foto_notice
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory,
    }
    static = True

    @classmethod
    def get_icon(cls) -> str:
        return "images"


@dataclasses.dataclass
class RegistrationNotes(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.registration_notes
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.optional,
    }


@dataclasses.dataclass
class TableOfContents(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.table_of_contents
    _frequency = QuestionnaireFrequency.optional
    static = True

    @classmethod
    def get_icon(cls) -> str:
        return "list"


@dataclasses.dataclass
class MyData(QuestionnaireMagicRow):
    _role = const.QuestionnaireRowRole.my_data
    _frequency = {
        const.QuestionnaireUsages.registration: QuestionnaireFrequency.mandatory,
    }
    static = True

    @classmethod
    def get_icon(cls) -> str:
        return "user"


class Questionnaire(list[QuestionnaireRow]):
    kind: const.QuestionnaireUsages
    all_questionnaires: "QuestionnaireContainer"

    def __init__(self, *args: Any, kind: const.QuestionnaireUsages) -> None:
        super().__init__(*args)
        self.kind = kind

    def as_dicts(self) -> list[CdEDBObject]:
        return [row.as_dict() for row in self]

    @property
    def field_rows(self) -> list[QuestionnaireFieldRow]:
        return [row for row in self if isinstance(row, QuestionnaireFieldRow)]

    @property
    def text_rows(self) -> list[QuestionnaireTextRowMeta]:
        return [row for row in self if isinstance(row, QuestionnaireTextRowMeta)]

    def get_field_ids(self) -> set[int]:
        return {row.field_id for row in self if isinstance(row, QuestionnaireFieldRow)}

    def allows_field(self, field: EventField, has_fees: bool) -> bool:
        """
        Determines whether the given field is allowed for this questionnaire kind.

        :param has_fees: True if the given field is used in a conditional fee, which
            is incompatible with some questionnaire kinds.
        """
        if not field.association == const.FieldAssociations.registration:
            return False
        if not self.kind.allow_fee_condition() and has_fees:
            return False
        return True

    def get_role_counts(self) -> collections.Counter[const.QuestionnaireRowRole]:
        return collections.Counter(row.role for row in self)

    def allows_magic_role(self, magic_role: const.QuestionnaireRowRole) -> bool:
        magic_role_class = magic_role.get_class()
        frequency = magic_role_class.allowed_frequency(self.kind)
        return frequency.allows()


class QuestionnaireContainer(dict[const.QuestionnaireUsages, Questionnaire]):
    event: Event

    @classmethod
    def from_database(cls, data: Collection["CdEDBObject"], event: Event) -> "Self":
        ret = cls()
        ret.event = event
        for row in QuestionnaireRow.many_from_database_list(data):
            ret[row.kind].append(row)
            ret[row.kind].all_questionnaires = ret
            row.questionnaire = ret[row.kind]
        return ret

    def __missing__(self, kind: const.QuestionnaireUsages) -> Questionnaire:
        """Ensures that all kinds can be accessed, even if they are empty."""
        self[kind] = Questionnaire(kind=kind)
        return self[kind]

    def as_dict(
        self, full: bool = False
    ) -> dict[const.QuestionnaireUsages, list[CdEDBObject]]:
        kinds = const.QuestionnaireUsages if full else self.keys()
        return {kind: self[kind].as_dicts() for kind in kinds}

    def field_usage(self) -> Mapping[int, const.QuestionnaireUsages]:
        """Map field ids to the questionnaire kind they are used in."""
        # These dicts are disjunct therfore the chainmap is just a big union.
        return collections.ChainMap(
            *(
                {field_id: kind}
                for kind, q in self.items()
                for field_id in q.get_field_ids()
            )
        )

    def get_available_fields(
        self, kind: const.QuestionnaireUsages
    ) -> CdEDataclassMap[EventField]:
        """Return all fields available for use in a questionnaire of the given kind."""
        field_usage = self.field_usage()
        fees_by_field = EventFee.get_fees_per_entity(self.event).fields
        return {
            field.id: field
            for field in self.event.fields.values()
            if self[kind].allows_field(
                field=field, has_fees=bool(fees_by_field[field.id])
            )
            and field_usage.get(field.id, kind) == kind
        }

    def get_available_magic_roles(
        self, kind: const.QuestionnaireUsages
    ) -> list[const.QuestionnaireRowRole]:
        """Return all builtins available for use in a questionnaire of the given kind."""
        return [
            magic_role
            for magic_role in const.QuestionnaireRowRole
            if self[kind].allows_magic_role(magic_role)
        ]


def make_default_questionnaire(
    event: Event,
) -> dict[const.QuestionnaireUsages, list[CdEDBObject]]:
    reg_quest: list[const.QuestionnaireRowRole | str] = [
        "Meine Daten",
        const.QuestionnaireRowRole.my_data,
        "Anmeldung",
        const.QuestionnaireRowRole.part_selection,
        const.QuestionnaireRowRole.fee_preview,
    ]
    if event.tracks:
        reg_quest.append("Kurswahlen")
    reg_quest.extend([
        const.QuestionnaireRowRole.course_choices,
        "Weitere Angaben",
        const.QuestionnaireRowRole.list_consent,
        const.QuestionnaireRowRole.mixed_lodging,
        const.QuestionnaireRowRole.foto_notice,
        const.QuestionnaireRowRole.registration_notes,
        const.QuestionnaireRowRole.fee_preview,
    ])

    return {
        const.QuestionnaireUsages.registration: [
            {"role": const.QuestionnaireRowRole.heading, "title": x}
            if isinstance(x, str)
            else {"role": x}
            for x in reg_quest
        ],
    }
