from gettext import gettext as _
from typing import Optional, Tuple

from .exceptions import SubscriptionError
from .machine import SubscriptionActions, SubscriptionLogCodes, SubscriptionStates
from cdedb.database.constants import (
    MailinglistInteractionPolicy as SubscriptionPolicy
)

def do_transition(action: SubscriptionActions, old_state: Optional[SubscriptionStates]
                  ) -> Tuple[Optional[SubscriptionStates], SubscriptionLogCodes]:
    error_matrix = SubscriptionActions.error_matrix()

    # TODO: `if exception := error_matrix[action][old_state]`.
    exception: Optional[SubscriptionError] = error_matrix[action][old_state]
    if exception:
        raise exception

    return action.get_target_state(), action.get_log_code()

def check_transition_requirements(*, action: SubscriptionActions,
                                  policy: Optional[SubscriptionPolicy],
                                  allow_unsub: bool = True,
                                  is_implied: bool = False) -> None:
    """Un-inlined code from `do_subscription_action`.

    This checks if a user may subscribe via the action triggered
    This does not check for the override states, as they are always allowed.
    """
    if action == SubscriptionActions.add_subscriber and (
            not policy or policy.is_implicit()):
        raise SubscriptionError(_(
            "User has no means to access this list."))
    elif (action == SubscriptionActions.subscribe and
            policy != SubscriptionPolicy.subscribable):
        raise SubscriptionError(_("Can not subscribe."))
    elif action.is_unsubscribing() and not allow_unsub:
        raise SubscriptionError(_("Can not unsubscribe."))
    elif (action == SubscriptionActions.request_subscription and
          policy != SubscriptionPolicy.moderated_opt_in):
        raise SubscriptionError(_("Can not request subscription."))
    elif action == SubscriptionActions.reset_unsubscription and is_implied:
        raise SubscriptionError(_("Can not reset unsubscription."))
    # elif action == SubscriptionActions.reset_subscription and not is_implied:
    #     raise SubscriptionError(_("Can not reset subscription."))
