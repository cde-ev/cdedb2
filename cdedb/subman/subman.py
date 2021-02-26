from gettext import gettext as _
from typing import Optional, Tuple
from typing_extensions import Literal

from .exceptions import SubscriptionError
from .machine import (
    SubscriptionActions, SubscriptionLogCodes, SubscriptionPolicy, SubscriptionStates,
)


def _do_transition(action: SubscriptionActions, old_state: Optional[SubscriptionStates]
                   ) -> Tuple[Optional[SubscriptionStates], SubscriptionLogCodes]:
    error_matrix = SubscriptionActions.error_matrix()

    # TODO: `if exception := error_matrix[action][old_state]`.
    exception: Optional[SubscriptionError] = error_matrix[action][old_state]
    if exception:
        raise exception

    return action.get_target_state(), action.get_log_code()


def _check_transition_requirements(*, action: SubscriptionActions,
                                   policy: Optional[SubscriptionPolicy],
                                   allow_unsub: bool = True,
                                   is_implied: bool = False) -> None:
    """Un-inlined code from `do_subscription_action`.

    This checks if a user may subscribe via the action triggered
    This does not check for the override states, as they are always allowed.
    """
    if action == SubscriptionActions.add_subscriber and (
            policy is None or policy.is_implicit()):
        raise SubscriptionError(_("User has no means to access this list."))
    # elif action == SubscriptionActions.cleanup_implicit and not (
    #        policy is None or policy.is_implicit()):
    #    raise SubscriptionError(_(
    #        "User should not be cleaned up since they are allowed subscribers."))
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


def apply_action(*, action: SubscriptionActions,
                 policy: Optional[SubscriptionPolicy],
                 allow_unsub: bool = True,
                 old_state: Optional[SubscriptionStates],
                 is_implied: bool = False
                 ) -> Tuple[Optional[SubscriptionStates], SubscriptionLogCodes]:
    # 1: Check list-dependent requirements for transition
    _check_transition_requirements(
        action=action, policy=policy, allow_unsub=allow_unsub, is_implied=is_implied)

    # 2: Check if current state allows transition
    return _do_transition(action, old_state)


def _do_cleanup(policy: Optional[SubscriptionPolicy],
                old_state: Optional[SubscriptionStates],
                is_implied: bool
                ) -> Tuple[Literal[None],
                     Literal[SubscriptionLogCodes.automatically_removed]]:
    # If user is not allowed as subscriber, remove them
    if policy is None:
        return _do_transition(SubscriptionActions.cleanup_subscription, old_state)  # type: ignore

    # If user is implicit subscriber and not implied, remove them.
    if not is_implied and policy.is_implicit():
        return _do_transition(SubscriptionActions.cleanup_implicit, old_state)  # type: ignore

    raise SubscriptionError(_("No cleanup necessary."))


def is_obsolete(policy: Optional[SubscriptionPolicy],
                old_state: Optional[SubscriptionStates],
                is_implied: bool
                ) -> bool:
    try:
        _do_cleanup(policy, old_state, is_implied)
        return True
    except SubscriptionError:
        return False
