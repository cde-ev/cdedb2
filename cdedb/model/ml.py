from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from subman.machine import SubscriptionPolicy

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.ml_type_aux import get_type
from cdedb.model.common import CdEDataclass, metadata

if TYPE_CHECKING:
    from cdedb.ml_type_aux import GeneralMailinglist

SubscriptionPolicyMap = Dict[int, SubscriptionPolicy]


# TODO move to a better place
@dataclass
class Mailinglist(CdEDataclass):
    id: int = field(metadata=metadata(vtypes.ID))
    title: str = field(metadata=metadata(str))
    local_part: str = field(metadata=metadata(vtypes.EmailLocalPart))
    domain: const.MailinglistDomain
    mod_policy: const.ModerationPolicy
    attachment_policy: const.AttachmentPolicy
    ml_type: const.MailinglistTypes
    is_active: bool

    moderators: List[int]
    whitelist: List[str]  # TODO: restrict type

    description: Optional[str] = None
    subject_prefix: Optional[str] = None
    maxsize: Optional[int] = None  # TODO: restrict type
    notes: Optional[str] = None

    # some mailinglist types need additional fields
    assembly_id: Optional[int] = None
    event_id: Optional[int] = None
    registration_stati: List[const.RegistrationPartStati] = field(default_factory=list)

    @property
    def address(self) -> str:
        return f"{self.local_part}@{self.domain.get_domain()}"

    @property
    def domain_str(self) -> str:
        return self.domain.get_domain()

    # required to set ml_type_class during __post_init__
    _ml_type_class: InitVar[Type["GeneralMailinglist"]] = None

    @property
    def ml_type_class(self) -> Type["GeneralMailinglist"]:
        return self._ml_type_class  # type: ignore

    def __post_init__(self, _ml_type_class: Type["GeneralMailinglist"]) -> None:
        self._ml_type_class = get_type(self.ml_type)  # type: ignore
