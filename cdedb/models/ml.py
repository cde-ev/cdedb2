from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from subman.machine import SubscriptionPolicy

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.ml_type_aux import get_type
from cdedb.models.common import CdEDataclass

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

    moderators: List[vtypes.ID]
    whitelist: List[vtypes.Email]

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

    @property
    def ml_type_class(self) -> Type["GeneralMailinglist"]:
        return get_type(self.ml_type)

    @classmethod
    def database_fields(cls) -> List[str]:
        return [field.name for field in fields(cls)
                if field.name not in {"moderators", "whitelist"}]
