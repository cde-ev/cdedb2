"""This contains most of the logic required to perform actions on subscriptions.

Here, `SubscriptionAction`s are the possible actions to transition from one
`SubscriptionState` to another. Every action will always lead to the same target state,
but there might be multiple actions leading to the same target state.
An action might be allowed from any current state or only from a subset of all states.

It is assumed that there are some users with additional privileges (possibly depending
on the subscription object in question). These privileged users are referred to as
"moderators". Actions restricted to moderators are referred to as "managing actions".

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
from typing import Mapping, Optional, Set

from .exceptions import SubscriptionError, SubscriptionInfo


@enum.unique
class SubscriptionState(enum.IntEnum):
    """All possible relations between a user and a subscription object.

    While some states are part of the core subscription machine and must be supported
    for the library to work properly, others are optional and can be deactivated without
    issue if the associated actions are also not used.
    """
    #: The user is explicitly subscribed.
    #: This state is required.
    subscribed = 1
    #: The user is explicitly unsubscribed. This means they were subscribed at some
    #: point, but decided to unsubscribe later on.
    #: This state is required.
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
    #: This state is required.
    implicit = 30
    #: The user has no relation to the subscription object whatsoever. You might want
    #: to avoid actually writing relations with this state to the database if you have
    #: loads of users and subscription objects that have no relation.
    #: This state is required.
    none = 40

    def is_subscribed(self) -> bool:
        """Whether a user is actually subscribed.

        All complications of the state machine aside, this is what matters in the end:
        Whether a user is considered to be subscribed or not.
        """
        return self in self.subscribing_states()

    @classmethod
    def subscribing_states(cls) -> Set['SubscriptionState']:
        """List of states which are considered subscribing."""
        return {cls.subscribed, cls.subscription_override, cls.implicit}

    @classmethod
    def cleanup_protected_states(cls) -> Set['SubscriptionState']:
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
class SubscriptionAction(enum.IntEnum):
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
    #: An automatic cleanup of users being subscribed (explicitly or implicitly).
    cleanup_subscription = 50
    cleanup_implicit = 51  #: An automatic cleanup of users being implicitly subscribed.
    # TODO: Add action for adding an implicit subscriber.

    def get_target_state(self) -> SubscriptionState:
        """Get the target state associated with an action.

        This is unique for each action. If None, a user will have no relation with the
        subscription object after the action has been performed.
        """
        action_target_state_map = {
            self.subscribe: SubscriptionState.subscribed,
            self.unsubscribe: SubscriptionState.unsubscribed,
            self.request_subscription: SubscriptionState.pending,
            self.cancel_request: SubscriptionState.none,
            self.approve_request: SubscriptionState.subscribed,
            self.deny_request: SubscriptionState.none,
            self.block_request: SubscriptionState.unsubscription_override,
            self.add_subscriber: SubscriptionState.subscribed,
            self.add_subscription_override: SubscriptionState.subscription_override,
            self.add_unsubscription_override: SubscriptionState.unsubscription_override,
            self.remove_subscriber: SubscriptionState.unsubscribed,
            self.remove_subscription_override: SubscriptionState.subscribed,
            self.remove_unsubscription_override: SubscriptionState.unsubscribed,
            self.reset: SubscriptionState.none,
            self.cleanup_subscription: SubscriptionState.none,
            self.cleanup_implicit: SubscriptionState.none,
        }
        return action_target_state_map[self]

    def get_error(self, state: SubscriptionState) -> Optional[SubscriptionError]:
        """Determine whether this action is allowed for the current state.

        :returns: `None` if the action is allowed, a `SubscriptionError` to be raised
            otherwise.
        """
        return _SUBSCRIPTION_ERROR_MATRIX[self][state]

    @classmethod
    def unsubscribing_actions(cls) -> Set["SubscriptionAction"]:
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
    def managing_actions(cls) -> Set["SubscriptionAction"]:
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
    def cleanup_actions(cls) -> Set["SubscriptionAction"]:
        """All actions which are part of more involved cleanup procedures.

        These cannot be executed via `apply_action`, and should be executed via
        `do_cleanup` instead.
        """
        return {
            SubscriptionAction.cleanup_subscription,
            SubscriptionAction.cleanup_implicit,
        }

    def is_automatic(self) -> bool:
        """Whether or not an action may not be performed manually."""
        return self in self.cleanup_actions()


# TODO: make these `Mapping`s, so they are immutable? It might be useful to be able to
#  alter these.
_StateErrorMapping = Mapping[SubscriptionState, Optional[SubscriptionError]]
_ActionStateErrorMatrix = Mapping[SubscriptionAction, _StateErrorMapping]

# Errors are identical for all actions handling a subscription request.
_SUBSCRIPTION_REQUEST_ERROR_MAPPING: _StateErrorMapping = {
    SubscriptionState.subscribed: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionState.unsubscribed: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionState.subscription_override: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionState.unsubscription_override: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionState.pending: None,
    SubscriptionState.implicit: SubscriptionError(_(
        "Not a pending subscription request.")),
    SubscriptionState.none: SubscriptionError(_("Not a pending subscription request.")),
}
_SUBSCRIPTION_ERROR_MATRIX: _ActionStateErrorMatrix = {
    SubscriptionAction.add_subscriber: {
        SubscriptionState.subscribed: SubscriptionInfo(_("User already subscribed.")),
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: SubscriptionInfo(_(
            "User already subscribed.")),
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "User has been blocked. Remove override before subscribe.")),
        SubscriptionState.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionState.implicit: SubscriptionInfo(_("User already subscribed.")),
        SubscriptionState.none: None
    },
    SubscriptionAction.remove_subscriber: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: SubscriptionInfo(_(
            "User already unsubscribed.")),
        SubscriptionState.subscription_override: SubscriptionError(_(
            "User cannot be removed. Remove override to change this.")),
        SubscriptionState.unsubscription_override: SubscriptionInfo(_(
            "User already unsubscribed.")),
        SubscriptionState.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: SubscriptionInfo(_("User already unsubscribed.")),
    },
    SubscriptionAction.add_subscription_override: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: SubscriptionInfo(_(
            "User is already force-subscribed.")),
        SubscriptionState.unsubscription_override: None,
        SubscriptionState.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: None,
    },
    SubscriptionAction.remove_subscription_override: {
        SubscriptionState.subscribed: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionState.unsubscribed: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionState.subscription_override: None,
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionState.pending: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionState.implicit: SubscriptionError(_(
            "User is not force-subscribed.")),
        SubscriptionState.none: SubscriptionError(_("User is not force-subscribed.")),
    },
    SubscriptionAction.add_unsubscription_override: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: None,
        SubscriptionState.unsubscription_override: SubscriptionInfo(_(
            "User has already been blocked.")),
        SubscriptionState.pending: SubscriptionError(_(
            "User has pending subscription request.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: None,
    },
    SubscriptionAction.remove_unsubscription_override: {
        SubscriptionState.subscribed: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionState.unsubscribed: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionState.subscription_override: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionState.unsubscription_override: None,
        SubscriptionState.pending: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionState.implicit: SubscriptionError(_(
            "User is not force-unsubscribed.")),
        SubscriptionState.none: SubscriptionError(_("User is not force-unsubscribed.")),
    },
    SubscriptionAction.subscribe: {
        SubscriptionState.subscribed: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionState.unsubscription_override: SubscriptionError(
            _("Can not change subscription because you are blocked.")),
        SubscriptionState.pending: None,
        SubscriptionState.implicit: SubscriptionInfo(_("You are already subscribed.")),
        SubscriptionState.none: None,
    },
    SubscriptionAction.request_subscription: {
        SubscriptionState.subscribed: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "Can not request subscription because you are blocked.")),
        SubscriptionState.pending: SubscriptionInfo(_(
            "You already requested subscription")),
        SubscriptionState.implicit: SubscriptionInfo(_(
            "You are already subscribed.")),
        SubscriptionState.none: None,
    },
    SubscriptionAction.unsubscribe: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        # subscription_override should only block you from being unsubscribed
        # automatically. A user is still able to unsubscribe manually.
        # (Unless the list is mandatory).
        SubscriptionState.subscription_override: None,
        SubscriptionState.unsubscription_override: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        SubscriptionState.pending: SubscriptionInfo(_(
            "You are already unsubscribed.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: SubscriptionInfo(_("You are already unsubscribed.")),
    },
    SubscriptionAction.reset: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: None,
        SubscriptionState.subscription_override: SubscriptionError(_(
            "User is in override state. Remove them before reset.")),
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "User is in override state. Remove them before reset.")),
        SubscriptionState.pending: SubscriptionError(_("User is not unsubscribed.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: None,
    },
    SubscriptionAction.cleanup_subscription: {
        SubscriptionState.subscribed: None,
        SubscriptionState.unsubscribed: SubscriptionError(_(
            "Unsubscriptions are protected against automatic cleanup.")),
        SubscriptionState.subscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionState.pending: SubscriptionError(_(
            "Pending requests are protected against automatic cleanup.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: SubscriptionInfo(_("Subscription already cleaned up.")),
    },
    SubscriptionAction.cleanup_implicit: {
        SubscriptionState.subscribed: SubscriptionError(_(
            "Subscriptions are protected against automatic implicit cleanup.")),
        SubscriptionState.unsubscribed: SubscriptionError(_(
            "Unsubscriptions are protected against automatic cleanup.")),
        SubscriptionState.subscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionState.unsubscription_override: SubscriptionError(_(
            "Overrides are protected against automatic cleanup.")),
        SubscriptionState.pending: SubscriptionError(_(
            "Pending requests are protected against automatic cleanup.")),
        SubscriptionState.implicit: None,
        SubscriptionState.none: SubscriptionInfo(_("Subscription already cleaned up.")),
    },
    SubscriptionAction.approve_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionAction.block_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionAction.deny_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
    SubscriptionAction.cancel_request: _SUBSCRIPTION_REQUEST_ERROR_MAPPING,
}

_CLEANUP_PROTECTED_STATES = {
    state for state in SubscriptionState
    if SubscriptionAction.cleanup_subscription.get_error(state)
}
