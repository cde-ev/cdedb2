"""This file provides the central functionality of the subman library.

To manage subscriptions of arbitrary objects, for example mailinglists, journals,
,notifications, or magazines the logic one would like to use in a non-trivial
situation is a bit complicated and does not really depend on precise use case.
For more general comments see the documentation.

Specifically, you require the following functions from this library:
* `apply_action` to apply arbitrary `SubscriptionActions` manually
* `is_obsolete` to cleanup outdated subscriptions from your database

To fully use the power of this library, you additionally need to implement two further
functions:
* a function actually regularly collecting a list of implicit subscriptions and writing
  them directly to the database, so that the subscription machine may act on them.
* a function regularly calling is_obsolete to cleanup all subscribers of a list not in
  a cleanup_protected state. This function may be temporarily turned off for a given
  object without issue.
"""

from gettext import gettext as _
from typing import Optional, Tuple
from typing_extensions import Literal

from .exceptions import SubscriptionError
from .machine import (
    SubscriptionActions, SubscriptionLogCodes, SubscriptionPolicy, SubscriptionStates,
)


def _check_state_requirements(action: SubscriptionActions,
                              old_state: Optional[SubscriptionStates]) -> None:
    """This checks if the given action is allowed to be performed from the given state.

    This check is the heart of the subscription state machine, since it considers the
    actual state transition. If the given state does not allow the transition via the
    given action, a SubscriptionError is raised.

    Keep in mind that different actions may lead to the same target state, but only one
    of them may be appropriate to use from the current state.
    """

    error_matrix = SubscriptionActions.get_error_matrix()
    # TODO: `if exception := error_matrix[action][old_state]`.
    exception: Optional[SubscriptionError] = error_matrix[action][old_state]
    if exception:
        raise exception


def _check_policy_requirements(action: SubscriptionActions,
                               policy: Optional[SubscriptionPolicy]) -> None:
    """This checks if the given action is allowed by the given SubscriptionPolicy.

    The policy should depend only on the affected user, not on the performing user.

    If the policy does not allow the action, a SubscriptionError is raised.

    :param policy: The SubsscriptionPolicy. If not given, the user is not privileged
        to be subscribed to this action.
    """
    if action == SubscriptionActions.add_subscriber and (
            policy is None or policy.is_implicit()):
        raise SubscriptionError(_("User has no means to access this list."))
    elif (action == SubscriptionActions.subscribe and
            policy != SubscriptionPolicy.subscribable):
        raise SubscriptionError(_("Can not subscribe."))
    elif (action == SubscriptionActions.request_subscription and
          policy != SubscriptionPolicy.moderated_opt_in):
        raise SubscriptionError(_("Can not request subscription."))


def apply_action(action: SubscriptionActions, *,
                 policy: Optional[SubscriptionPolicy],
                 old_state: Optional[SubscriptionStates],
                 allow_unsub: bool = True,
                 is_privileged: bool = True,
                 ) -> Tuple[Optional[SubscriptionStates], SubscriptionLogCodes]:
    """Apply a SubscriptionAction to a SubscriptionState according to a SubscriptionPolicy.

    This is the main interface for performing subscription actions. To decide if the
    action is allowed to be performed, a series of checks are performed.

    :param action: The SubscriptionAction to be performed in the end if all goes well.
        Determines the target state of the trnsition.
    :param policy: The SubscriptionPolicy describing the allowed interactions between
        the affected user and the affected subscription object.
    :param old_state: The current state of the relation between the affected user and
        the affected subscription object.
    :param allow_unsub: If this is not True, prevent the user from becoming unsubscribed.
        We recommend only using the policies SubscriptionPolicy.implicits_only and
        None for objects using this feature.
        Warning: This feature is not compatible with users with old_state in
        {SubscriptionStates.unsubscribed, SubscriptionStates.unsubscription_override}
        regarding the respective object.
    :param is_privileged: If this is not True, disallow managing actions.
    """
    # 1: Do basic sanity checks this library is used appropriately.
    if action in SubscriptionActions.cleanup_actions():
        raise RuntimeError(_("Use is_obsolete to perform cleanup actions."))
    # TODO: why? This does not really help us.
    if allow_unsub and old_state in {SubscriptionStates.unsubscribed,
                                     SubscriptionStates.unsubscription_override}:
        raise RuntimeError(_("allow_unsub is incompatible with explicitly unsubscribed"
                             " states."))

    # 2: Check list-dependent requirements for transition.
    _check_policy_requirements(action=action, policy=policy)
    if action.is_unsubscribing() and not allow_unsub:
        raise SubscriptionError(_("Can not unsubscribe."))

    # 3: Check if current state allows transition.
    _check_state_requirements(action, old_state)

    # 4: Return target state and log code associated with the action.
    return action.get_target_state(), action.get_log_code()


def _apply_cleanup(policy: Optional[SubscriptionPolicy],
                   old_state: Optional[SubscriptionStates],
                   is_implied: bool
                   ) -> Tuple[Literal[None],
                              Literal[SubscriptionLogCodes.automatically_removed]]:
    """Analogue of apply_action for cleanup of subscribers.

    This interface is exposed mainly for show to make the transition understandable by
    analogy to apply_action. Since this is dependant on the fact whether a subscriber
    would be implied as a subscriber of the respective object, it can not be done with
    the exact same formalism as apply_action.

    This is guaranteed to only touch states not in
    SubscriptionStates.cleanup_protected_states().

    Parameters are documented at is_obsolete.
    """
    # If user is not allowed as subscriber, remove them
    if policy is None:
        _check_state_requirements(SubscriptionActions.cleanup_subscription, old_state)
        return None, SubscriptionLogCodes.automatically_removed

    # If user is implicit subscriber and not implied, remove them.
    if not is_implied and policy.is_implicit():
        _check_state_requirements(SubscriptionActions.cleanup_implicit, old_state)
        return None, SubscriptionLogCodes.automatically_removed

    raise SubscriptionError(_("No cleanup necessary."))


def is_obsolete(policy: Optional[SubscriptionPolicy],
                old_state: Optional[SubscriptionStates],
                is_implied: bool
                ) -> bool:
    """Returns whether a subscriber should be cleaned up from an object.

    This can be called as part of an automatic cleanup procedure to check if a
    subscriber should be removed from a subscription object.

    :param policy: The SubscriptionPolicy applying to the object for the user an action
        is performed on.
    :param old_state: The current SubscriptionState of the user.
    :param is_implied: Whether the user is currently implied as a subscriber of the
        respective object.
    """
    try:
        _apply_cleanup(policy, old_state, is_implied)
        return True
    except SubscriptionError:
        return False
