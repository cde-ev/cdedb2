import dataclasses
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from subman.machine import SubscriptionPolicy

import cdedb.database.constants as const
from cdedb.common.fields import MAILINGLIST_FIELDS
from cdedb.ml_type_aux import get_type

if TYPE_CHECKING:
    from cdedb.common import CdEDBObject
    from cdedb.ml_type_aux import GeneralMailinglist

SubscriptionPolicyMap = Dict[int, SubscriptionPolicy]


# TODO move to a better place
@dataclasses.dataclass
class Mailinglist:
    # _: dataclasses.KW_ONLY
    id: int
    title: str
    local_part: str  # TODO restrict type
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
    registration_stati: List[const.RegistrationPartStati] = dataclasses.field(default_factory=list)

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

    def to_database(self) -> "CdEDBObject":
        """Generate a dict representation of the mailinglist to be saved to the db."""
        return {key: getattr(self, key) for key in MAILINGLIST_FIELDS}
