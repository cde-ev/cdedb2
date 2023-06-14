"""Fix subman enums to behave like our enums.

Splitting this off now necessitates some corrective action."""

from subman.machine import SubscriptionAction, SubscriptionPolicy, SubscriptionState

from cdedb.common.intenum import CdEIntEnum

SubscriptionAction.__str__ = CdEIntEnum.__str__
SubscriptionAction.__format__ = CdEIntEnum.__format__
SubscriptionPolicy.__str__ = CdEIntEnum.__str__
SubscriptionPolicy.__format__ = CdEIntEnum.__format__
SubscriptionState.__str__ = CdEIntEnum.__str__
SubscriptionState.__format__ = CdEIntEnum.__format__
