"""This contains most of the logic required to perform actions on subscriptions.

It is assumed that there are some users with additional privileges (possibly depending
on the subscription object in question). These privileged users are referred to as
"moderators".

Here, `SubscriptionActions` are the possible actions to transition from one
`SubscriptionState` to another. Every action will always lead to the same target state,
but multiple actions might lead to the same target state. An action might be allowed
from any current state or only from a subset of all states.

Some actions are only available to moderators. These actions are referred to as
"managing actions".

Some actions are meant to be performed automatically somewhat regularly. They are not
meant to be performed manually but rather as a reaction to some change of an external
condition, like a user losing the privilege to subscribe to a certain subscription
object. These actions are referred to as "cleanup actions".

Every user has a certain `SubscriptionPolicy` that defines their relation to any
particular object they could possibly be subscribed to. This determines what actions
they can perform themselves, but also what administrative actions others may perform
for them.
"""

import enum
from gettext import gettext as _
from typing import Dict, Optional, Set

from .exceptions import SubscriptionError, SubscriptionInfo


@enum.unique
class SubscriptionStates(enum.IntEnum):
    """All possible relations between a user and a subscription object.

    While some states are part of the core subscription machine and must be expected for
    the library to work properly, others are optional and can be deactivated without
    issue if the associated actions are not used.
    """
    #: The user is explicitly subscribed.
    #: Expecting this state is required.
    subscribed = 1
    #: The user is explicitly unsubscribed. This means they were subscribed at some
    #: point, but decided to unsubscribe later on.
    #: Expecting this state is required.
    unsubscribed = 2
    #: The user was explicitly subscribed, even though he would usually not be allowed
    #: as a subscriber.
    #: This state is optional.
    subscription_override = 10
    #: The user is not allowed to be subscribed, since they were administratively
    #: blocked.
    #: This state is optional.
    unsubscription_override = 11
    #: The user has requested a subscription to the object, awaiting administrative
    #: approval.
    #: This state is optional.
    pending = 20
    #: The user is subscribed by virtue of being part of some group.
    #: Expecting this state is required.
    implicit = 30

    def is_subscribed(self) -> bool:
        """Whether a user is actually subscribed.

        All complications of the state machine aside, this is what matters in the end:
        Whether a user is considered to be subscribed or not.
        """
        return self in self.subscribing_states()

    @classmethod
    def subscribing_states(cls) -> Set['SubscriptionStates']:
        """List of states which are considered subscribing."""
        return {cls.subscribed, cls.subscription_override, cls.implicit}

    @classmethod
    def cleanup_protected_states(cls) -> Set['SubscriptionStates']:
        """List of states which are not touched by `_do_cleanup`."""
        return _CLEANUP_PROTECTED_STATES


@enum.unique
class SubscriptionPolicy(enum.IntEnum):
    """Define the relation between a *potential* subscriber and a subscription object.

    This tells us what `SubscriptionsActions` may be performed on the user, including
    whether or not they may be subscribed at all.
    """
    #: User may subscribe themselves,
    subscribable = 1
    #: User may request subscription and needs approval to subscribe.
    moderated_opt_in = 2
    #: User may not subscribe by themselves, but can be administratively subscribed.
    invitation_only = 3
    #: Only implicit subscribers are allowed. If the user is neither implicit subscriber
    #: nor has subscription override, their subscription will be removed.
    implicits_only = 4
    #: User is not allowed to be subscribed except by subscription override.
    none = 5

    def is_implicit(self) -> bool:
        """Whether or not the user is only allowed to be subscribed implicitly."""
        return self == self.implicits_only

    def is_none(self) -> bool:
        """Whether or not the user is not allowed to be subscribed."""
        return self == self.none

    def may_subscribe(self) -> bool:
        """Whether or not a user may subscribe by themself."""
        return self == self.subscribable

    def may_request(self) -> bool:
        """Whether or not a user may request a subscription."""
        return self == self.moderated_opt_in

    @classmethod
    def addable_policies(cls) -> Set["SubscriptionPolicy"]:
        """Return a list of policies that allow the user to be added."""
        return {cls.subscribable, cls.moderated_opt_in, cls.invitation_only}

    def may_be_added(self) -> bool:
        """Whether or not a user may be subscribed by a moderator."""
        return self in self.addable_policies()


@enum.unique
class SubscriptionActions(enum.IntEnum):
    """All possible actions a subscriber or moderator can take.

    You may choose to make only some of these available to your users or show some only
    under specific conditions.
    """
    subscribe = 1  #: A user subscribing themselves.
    unsubscribe = 2  #: A user removing their subscription.
    request_subscription = 10  #: Requesting subscription for moderated opt-in.
    cancel_request = 11  #: A user cancelling their subscription request.
    approve_request = 12  #: A moderator approving a subscription request.
    deny_request = 13  #: A moderator denying a subscription request.
    block_request = 14  #: A moderator denying a request and blocking the user.
    add_subscriber = 20  #: A moderator manually adding a subscriber.
    add_subscription_override = 21  #: A moderator adding a fixed subscription.
    add_unsubscription_override = 22  #: A moderator blocking a user.
    remove_subscriber = 30  #: A moderator manually removing a subscribed user.
    remove_subscription_override = 31  #: A moderator removing a fixed subscription.
    remove_unsubscription_override = 32  #: A moderator unblocking a user.
    reset = 40  #: A moderator removing the current state of a user.
    cleanup_subscription = 50  #: An automatic cleanup of users being explicitly subscribed.
    cleanup_implicit = 51  #: An automatic cleanup of users being implicitly subscribed.
    # TODO: Add action for adding an implicit subscriber.

    def get_target_state(self) -> Optional[SubscriptionStates]:
        """Get the target state associated with an action.

        This is unique for each action. If None, a user will have no relation with the
        subscription object after the action has been performed.
        """
        action_target_state_map = {
            self.subscribe: SubscriptionStates.subscribed,
            self.unsubscribe: SubscriptionStates.unsubscribed,
            self.request_subscription: SubscriptionStates.pending,
            self.cancel_request: None,
            self.approve_request: SubscriptionStates.subscribed,
            self.deny_request: None,
            self.block_request: SubscriptionStates.unsubscription_override,
            self.add_subscriber: SubscriptionStates.subscribed,
            self.add_subscription_override: SubscriptionStates.subscription_override,
            self.add_unsubscription_override: SubscriptionStates.unsubscription_override,
            self.remove_subscriber: SubscriptionStates.unsubscribed,
            self.remove_subscription_override: SubscriptionStates.subscribed,
            self.remove_unsubscription_override: SubscriptionStates.unsubscribed,
            self.reset: None,
            self.cleanup_subscription: None,
            self.cleanup_implicit: None,
        }
        return action_target_state_map[self]

    @staticmethod
    def get_error_matrix() -> "_ActionStateErrorMatrix":
        """This defines the logic of which state transitions are legal.

        SubscriptionErrors defined in this matrix will be raised by `apply_action`.
        """
        return _SUBSCRIPTION_ERROR_MATRIX

    @classmethod
    def unsubscribing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that unsubscribe a user.

        While cleanup actions may remove a user's subscription from an object, they are
        not considered unsubscribing, because won't be performed manually.
        """
        # TODO: include cleanup here.
        return {
            cls.unsubscribe,
            cls.remove_subscriber,
            cls.add_unsubscription_override,
        }

    def is_unsubscribing(self) -> bool:
        """Whether ot not an action unsubscribes a user."""
        return self in self.unsubscribing_actions()

    @classmethod
    def managing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that require additional privileges.

        These should only be made accessible to moderators.
        """
        return {
            cls.approve_request,
            cls.deny_request,
            cls.block_request,
            cls.add_subscriber,
            cls.add_subscription_override,
            cls.add_unsubscription_override,
            cls.remove_subscriber,
            cls.remove_subscription_override,
            cls.remove_unsubscription_override,
            cls.reset,
        }

    def is_managing(self) -> bool:
        """Whether or not an action requires additional privileges."""
        return self in self.managing_actions()

    @classmethod
    def cleanup_actions(cls) -> Set["SubscriptionActions"]:
        """All actions which are part of more involved cleanup procedures.

        These cannot be executed via `apply_action`, and should be executed via
        `do_cleanup` instead.
        """
        return {
            SubscriptionActions.cleanup_subscription,
            SubscriptionActions.cleanup_implicit,
        }

    def is_automatic(self) -> bool:
        """Whether or not an action may not be performed manually."""
        return self in self.cleanup_actions()


# TODO: make these `Mapping`s, so they are immutable? It might be useful to be able to
#  alter these.
_StateErrorMapping = Dict[Optional[SubscriptionStates], Optional[SubscriptionError]]
_ActionStateErrorMatrix = Dict[SubscriptionActions, _StateErrorMapping]

# Errors are identical for all actions handling a subscription request.
_SUBSCRIPTION_REQUEST_ERROR_MAPPING: _StateErrorMapping = {
    SubscriptionStates.subscribed: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionStates.unsubscribed: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionStates.subscription_override: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionStates.unsubscription_override: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionStates.pending: None,
    SubscriptionStates.implicit: SubscriptionError(_(
        "Not a pending subscription request.")),
    None: SubscriptionError(_("Not a pending subscription request.")),
}
_SUBSCRIPTION_ERROR_MATRIX: _ActionStateErrorMatrix = {
    SubscriptionActions.add_subscriber: {
        SubscriptionStates.subscribed: SubscriptionInfo(_("User already subscribed.")),
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: SubscriptionInfo(_(
            "User already subscribed.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "User has been blocked. Remove override before subscribe.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionStates.implicit: SubscriptionInfo(_("User already subscribed.")),
        None: None
    },
    SubscriptionActions.remove_subscriber: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: SubscriptionInfo(_(
            "User already unsubscribed.")),
        SubscriptionStates.subscription_override: SubscriptionError(_(
            "User cannot be removed. Remove override to change this.")),
        SubscriptionStates.unsubscription_override: SubscriptionInfo(_(
            "User already unsubscribed.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionStates.implicit: None,
        None: SubscriptionInfo(_("User already unsubscribed.")),
    },
    SubscriptionActions.add_subscription_override: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: SubscriptionInfo(_(
            "User is already force-subscribed.")),
        SubscriptionStates.unsubscription_override: None,
        SubscriptionStates.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionStates.implicit: None,
        None: None,
    },
    SubscriptionActions.remove_subscription_override: {
        SubscriptionStates.subscribed: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionStates.unsubscribed: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionStates.subscription_override: None,
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionStates.implicit: SubscriptionError(_(
            "User is not force-subscribed.")),
        None: SubscriptionError(_("User is not force-subscribed.")),
    },
    SubscriptionActions.add_unsubscription_override: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: None,
        SubscriptionStates.unsubscription_override: SubscriptionInfo(_(
            "User has already been blocked.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionStates.implicit: None,
        None: None,
    },
    SubscriptionActions.remove_unsubscription_override: {
        SubscriptionStates.subscribed: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionStates.unsubscribed: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionStates.subscription_override: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionStates.unsubscription_override: None,
        SubscriptionStates.pending: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionStates.implicit: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        None: SubscriptionError(_("User is not force-unsubscribed.")),
    },
    SubscriptionActions.subscribe: {
        SubscriptionStates.subscribed: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(
            _("Can not change subscription because you are blocked.")),
        SubscriptionStates.pending: None,
        SubscriptionStates.implicit: SubscriptionInfo(_("You are already subscribed.")),
        None: None,
    },
    SubscriptionActions.request_subscription: {
        SubscriptionStates.subscribed: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "Can not request subscription because you are blocked.")),
        SubscriptionStates.pending: SubscriptionInfo(_(
            "You already requested subscription")),
        SubscriptionStates.implicit: SubscriptionInfo(_(
            "You are already subscribed.")),
        None: None,
    },
    SubscriptionActions.unsubscribe: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        # subscription_override should only block you from being unsubscribed
        # automatically. A user is still able to unsubscribe manually.
        # (Unless the list is mandatory).
        SubscriptionStates.subscription_override: None,
        SubscriptionStates.unsubscription_override: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        SubscriptionStates.pending: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        SubscriptionStates.implicit: None,
        None: SubscriptionInfo(_("You are already unsubscribed.")),
    },
    SubscriptionActions.reset: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: None,
        SubscriptionStates.subscription_override: SubscriptionError(_(
            "User is in override state. Remove them before reset.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "User is in override state. Remove them before reset.")),
        SubscriptionStates.pending: SubscriptionError(_("User is not unsubscribed.")),
        SubscriptionStates.implicit: None,
        None: None,
    },
    SubscriptionActions.cleanup_subscription: {
        SubscriptionStates.subscribed: None,
        SubscriptionStates.unsubscribed: SubscriptionError(_(
            "Unsubscriptions are protected against automatic cleanup.")),
        SubscriptionStates.subscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "Pending requests are protected against automatic cleanup.")),
        SubscriptionStates.implicit: None,
        None: SubscriptionInfo(_("Subscription already cleaned up.")),
    },
    SubscriptionActions.cleanup_implicit: {
        SubscriptionStates.subscribed: SubscriptionError(_(
            "Subscriptions are protected against automatic implicit cleanup.")),
        SubscriptionStates.unsubscribed: SubscriptionError(_(
            "Unsubscriptions are protected against automatic cleanup.")),
        SubscriptionStates.subscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionStates.unsubscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionStates.pending: SubscriptionError(_(
            "Pending requests are protected against automatic cleanup.")),
        SubscriptionStates.implicit: None,
        None: SubscriptionInfo(_("Subscription already cleaned up.")),
    },
    SubscriptionActions.approve_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionActions.block_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionActions.deny_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionActions.cancel_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
}

_CLEANUP_PROTECTED_STATES = {state for state in SubscriptionStates
                             if SubscriptionActions.get_error_matrix()[
                                 SubscriptionActions.cleanup_subscription][state]}
