"""This file provides the central functionality of the subman library.

To manage subscriptions of arbitrary objects, for example mailinglists, journals,
notifications, or magazines the logic one would like to use in a non-trivial
situation is a bit complicated and does not really depend on precise use case.
For more general comments see the documentation.

Specifically, you require the following functions from this library:
* `apply_action` to apply an arbitrary `SubscriptionAction` manually
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
from typing import AbstractSet, Collection, Optional

from .exceptions import SubscriptionError
from .machine import (
    SubscriptionAction, SubscriptionPolicy, SubscriptionState,
    ActionStateErrorMatrix, SUBSCRIPTION_ERROR_MATRIX,
)


StateColl = Collection[SubscriptionState]
StateSet = AbstractSet[SubscriptionState]


class SubscriptionManager:
    cleanup_protected_states: StateSet = {
        SubscriptionState.unsubscribed,
        SubscriptionState.none,
        SubscriptionState.subscription_override,
        SubscriptionState.unsubscription_override,
        SubscriptionState.pending
    }

    def __init__(
        self, *,
        error_matrix: ActionStateErrorMatrix = SUBSCRIPTION_ERROR_MATRIX,
        unwritten_states: Optional[StateColl] = None,
    ) -> None:
        """
        Create an instance of a `SubscriptionManager`.

        :param error_matrix: You may provide an alternative matrix defining the
            relations between actions and states.
        :param unwritten_states: Provide this if you want to keep track of a subset of
            all `SubscriptionState`s, that should not be written to your database.
        """
        self.error_matrix = error_matrix
        self.unwritten_states: StateSet = set(unwritten_states or ())
        if (self.unwritten_states &
                {SubscriptionState.subscribed, SubscriptionState.unsubscribed}):
            raise ValueError(_("Explicit core actions must be written."))

    @property
    def written_states(self) -> StateSet:
        """Return all states that should be written.

        I.e. the complement of `self.unwritten_states`.
        """
        return set(SubscriptionState) - self.unwritten_states

    def _get_error(self,
                   action: SubscriptionAction,
                   state: SubscriptionState,
                   ) -> Optional[SubscriptionError]:
        """Determine whether the given action is allowed for the given state.

        :returns: `None` if the action is allowed, a `SubscriptionError` to be raised
            otherwiese.
        """
        return self.error_matrix[action][state]

    def _check_state_requirements(self,
                                  action: SubscriptionAction,
                                  old_state: SubscriptionState) -> None:
        """This checks if the given action is allowed to be performed from the given state.

        This check is the heart of the subscription state machine, since it considers the
        actual state transition. If the given state does not allow the transition via the
        given action, a SubscriptionError is raised.

        Keep in mind that different actions may lead to the same target state, but only one
        of them may be appropriate to use from the current state.
        """

        # TODO: `if exception := self.get_error(action, old_state)`.
        exception = self._get_error(action, old_state)
        if exception:
            raise exception

    @staticmethod
    def _check_policy_requirements(action: SubscriptionAction,
                                   policy: SubscriptionPolicy) -> None:
        """This checks if the given action is allowed by the given SubscriptionPolicy.

        The policy should depend only on the affected user, not on the performing user.

        If the policy does not allow the action, a SubscriptionError is raised.
        """
        if (action == SubscriptionAction.add_subscriber
                and not policy.allows_subscription()):
            raise SubscriptionError(_("User has no means to access this list."))
        if action == SubscriptionAction.subscribe and not policy.may_subscribe():
            raise SubscriptionError(_("Can not subscribe."))
        if action == SubscriptionAction.request_subscription and not policy.may_request():
            raise SubscriptionError(_("Can not request subscription."))

    def apply_action(self,
                     action: SubscriptionAction, *,
                     policy: SubscriptionPolicy,
                     old_state: SubscriptionState,
                     allow_unsub: bool = True,
                     is_privileged: bool = True,
                     ) -> SubscriptionState:
        """Apply a SubscriptionAction to a SubscriptionState according to a SubscriptionPolicy.

        This is the main interface for performing subscription actions. To decide if the
        action is allowed to be performed, a series of checks are performed.

        :param action: The SubscriptionAction to be performed in the end if all goes well.
            Determines the target state of the transition.
        :param policy: The SubscriptionPolicy describing the allowed interactions between
            the affected user and the affected subscription object.
        :param old_state: The current state of the relation between the affected user and
            the affected subscription object.
        :param allow_unsub: If this is not True, prevent the user from becoming unsubscribed.
            We recommend only using the policies SubscriptionPolicy.implicits_only and
            None for objects using this feature.
            Warning: This feature is not compatible with users with old_state in
            {SubscriptionState.unsubscribed, SubscriptionState.unsubscription_override}
            regarding the respective object.
        :param is_privileged: If this is not True, disallow managing actions.
        """
        # 1: Do basic sanity checks this library is used appropriately.
        if not allow_unsub and old_state in {SubscriptionState.unsubscribed,
                                             SubscriptionState.unsubscription_override}:
            raise RuntimeError(
                _("allow_unsub is incompatible with explicitly unsubscribed states."))

        # 2: Check list-dependent requirements for transition.
        self._check_policy_requirements(action=action, policy=policy)
        if action.is_unsubscribing() and not allow_unsub:
            raise SubscriptionError(_("Can not unsubscribe."))
        if action.is_managing() and not is_privileged:
            raise SubscriptionError(_("Not privileged."))

        # 3: Check if current state allows transition.
        self._check_state_requirements(action, old_state)

        # 4: Return target state and log code associated with the action.
        return action.get_target_state()

    def _apply_cleanup(self,
                       policy: SubscriptionPolicy,
                       old_state: SubscriptionState,
                       is_implied: bool
                       ) -> SubscriptionState:
        """Analogue of apply_action for cleanup of subscribers.

        This function is meant to update saved data regarding subscriptions if
        exterior circumstances have changed. This is relevant for subscriptions if
        written to the database, independent of being explicit or implicit.

        This interface is exposed mainly to make the transition understandable by
        analogy to apply_action. Since this is dependant on the fact whether a subscriber
        would be implied as a subscriber of the respective object, it can not be done
        with the exact same formalism as apply_action.

        This is guaranteed to only touch states not in
        SubscriptionManager.cleanup_protected_states().

        Parameters are documented at is_obsolete.
        """
        # pylint: disable=superfluous-parens
        if old_state in (self.unwritten_states | self.cleanup_protected_states):
            raise SubscriptionError(_("No cleanup necessary."))

        if old_state.is_subscribed() and policy.is_none():
            # If user is not allowed as subscriber, remove them.
            return SubscriptionState.none
        elif (old_state == SubscriptionState.implicit and not is_implied
              and policy.is_implicit()):
            # If user is implicit subscriber and not implied, remove them.
            # This conditional is only relevant if implicit subscribers are written.
            return SubscriptionState.none
        else:
            raise SubscriptionError(_("No cleanup necessary."))

    def is_obsolete(self,
                    policy: SubscriptionPolicy,
                    old_state: SubscriptionState,
                    is_implied: bool
                    ) -> bool:
        """Returns whether a subscriber should be cleaned up from an object.

        This can be called as part of an automatic cleanup procedure to check if a
        subscriber should be removed from a subscription object.

        :param policy: The SubscriptionPolicy describing the allowed interactions between
            the affected user and the affected subscription object.
        :param old_state: The current state of the relation between the affected user and
            the affected subscription object.
        :param is_implied: Whether the user is currently implied as a subscriber of the
            respective object. Note that the user may still have a current state other than
            implicit, even if they are implied, for example if they opted out of an
            automatic subscription.
        """
        try:
            self._apply_cleanup(policy, old_state, is_implied)
            return True
        except SubscriptionError:
            return False
