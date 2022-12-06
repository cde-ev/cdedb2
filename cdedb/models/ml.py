from dataclasses import InitVar, dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from subman.machine import SubscriptionPolicy

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common.n_ import n_
from cdedb.ml_type_aux import get_type
from cdedb.models.common import CdEDataclass, field

if TYPE_CHECKING:
    from cdedb.ml_type_aux import GeneralMailinglist

SubscriptionPolicyMap = Dict[int, SubscriptionPolicy]
CdEDBObject = Dict[str, Any]


@dataclass
class Mailinglist(CdEDataclass):
    title: str
    local_part: vtypes.EmailLocalPart
    domain: const.MailinglistDomain
    mod_policy: const.ModerationPolicy
    attachment_policy: const.AttachmentPolicy
    ml_type: const.MailinglistTypes
    is_active: bool

    moderators: List[vtypes.ID] = field(to_database=False)
    whitelist: List[vtypes.Email] = field(to_database=False, is_optional=True)

    description: Optional[str] = None
    subject_prefix: Optional[str] = None
    maxsize: Optional[vtypes.PositiveInt] = None
    notes: Optional[str] = None

    # some mailinglist types need additional fields
    assembly_id: Optional[vtypes.ID] = None
    event_id: Optional[vtypes.ID] = None
    registration_stati: List[const.RegistrationPartStati] = field(default_factory=list)

    @property
    def address(self) -> vtypes.Email:
        """Build the address of the Mailinglist.

        We know that this is a valid Email since it passed the validation.
        """
        return vtypes.Email(self.get_address(vars(self)))

    @classmethod
    def get_address(cls, data: CdEDBObject) -> str:
        """Create an address from the given proto-mailinglist dict.

        We can not ensure that the returned string is a valid Email, since we do not
        know if it would pass the respective validator.
        """
        domain = const.MailinglistDomain(data["domain"]).get_domain()
        return f"{data['local_part']}@{domain}"

    @property
    def domain_str(self) -> str:
        return self.domain.get_domain()

    # required to set ml_type_class during __post_init__
    _ml_type_class: InitVar[Type["GeneralMailinglist"]] = None

    @property
    def ml_type_class(self) -> Type["GeneralMailinglist"]:
        return self._ml_type_class  # type: ignore[attr-defined]

    def __post_init__(self, _ml_type_class: Type["GeneralMailinglist"]) -> None:
        self._ml_type_class = get_type(self.ml_type)  # type: ignore[attr-defined]
