"""This contains most of the logic required to perform actions on subscriptions.

Here, `SubscriptionActions` are the possible actions to transition from one
`SubscriptionState` to another. While each SubscriptionAction can usually start at
several initial state, it always has one unique target state.

Additionally, every user can have a certain `SubscriptionPolicy` with regard to each
particular object they could possibly be subscribed to. This determines, fore example,
if they may be subscribed to an object or may even subscribe themselves.

Finally, there are `SubscriptionLogCodes` you can use to log the events performed by
`SubscriptionActions`.
"""

import enum
from gettext import gettext as _
from typing import Dict, Optional, Set

from .exceptions import SubscriptionError, SubscriptionInfo


@enum.unique
class SubscriptionStates(enum.IntEnum):
    """Define the possible relations between users and subscription objects.

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
        Whether a user is considered to be subscribed or not."""
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

    This tells whether a given user may be subscribed to an object. In addition to
    the enum members, None is considered a `SubscriptionPolicy` as well and means that
    a user is not allowed to be subscribed.
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
    #: User is not allowed to be subscribed except by subscription overide.
    # None

    def is_implicit(self) -> bool:
        """Short-hand for policy == SubscriptionPolicy.implicits_only"""
        return self == SubscriptionPolicy.implicits_only


@enum.unique
class SubscriptionLogCodes(enum.IntEnum):
    """Available log codes for `SubscriptionAction` logging."""
    #: most actions leading to `SubscriptionStates.subscribed`
    subscribed = 1
    #: all actions leading to `SubscriptionStates.unsubscribed`
    unsubscribed = 2
    #: all actions leading to `SubscriptionStates.subscription_override`
    marked_override = 3
    #: most actions leading to `SubscriptionStates.unsubscription_override`
    marked_blocked = 4
    #: associated with removal via `do_cleanup`
    automatically_removed = 10
    #: all actions leading to `SubscriptionStates.subscription_requested`
    subscription_requested = 20
    #: log code of `SubscriptionActions.approve_request`,
    #: leading to`SubscriptionStates.subscribed`
    request_approved = 21
    #: log code of `SubscriptionActions.deny_request`
    request_denied = 22
    #: log code of `SubscriptionActions.cancel_request`
    request_cancelled = 23
    #: log code of `SubscriptionActions.block_request`,
    #: leading to `SubscriptionStates.unsubscription_override`
    request_blocked = 24
    #: log code of `SubscriptionActions.reset`
    reset = 30


@enum.unique
class SubscriptionActions(enum.IntEnum):
    """All possible actions a subscriber or moderator can take.

    You may choose to make not all of these available to your users or show some only
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

    def get_target_state(self) -> Optional[SubscriptionStates]:
        """Get the target state associated with an action.

        This is unique for each eaction. If None, a user has no relation with the
        object after the action has been performed.
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

    def get_log_code(self) -> SubscriptionLogCodes:
        """Get the log code associated with performing an action."""
        log_code_map = {
            self.subscribe: SubscriptionLogCodes.subscribed,
            self.unsubscribe: SubscriptionLogCodes.unsubscribed,
            self.request_subscription: SubscriptionLogCodes.subscription_requested,
            self.cancel_request: SubscriptionLogCodes.request_cancelled,
            self.approve_request: SubscriptionLogCodes.request_approved,
            self.deny_request: SubscriptionLogCodes.request_denied,
            self.block_request: SubscriptionLogCodes.request_blocked,
            self.add_subscriber: SubscriptionLogCodes.subscribed,
            self.add_subscription_override: SubscriptionLogCodes.marked_override,
            self.add_unsubscription_override: SubscriptionLogCodes.marked_blocked,
            self.remove_subscriber: SubscriptionLogCodes.unsubscribed,
            self.remove_subscription_override: SubscriptionLogCodes.subscribed,
            self.remove_unsubscription_override: SubscriptionLogCodes.unsubscribed,
            self.reset: SubscriptionLogCodes.reset,
            self.cleanup_subscription: SubscriptionLogCodes.automatically_removed,
            self.cleanup_implicit: SubscriptionLogCodes.automatically_removed,
        }
        return log_code_map[self]

    @staticmethod
    def get_error_matrix() -> "_ActionStateErrorMatrix":
        """This defines the logic of which state transitions are legal.

        SubscriptionErrors defined in this matrix will be raised by `apply_action`.
        """
        return _SUBSCRIPTION_ERROR_MATRIX

    @classmethod
    def unsubscribing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that unsubscribe a user.

        While cleanup_actions are removing a user from an object, we do not
        consider them unsubscribing, since they do not represent active unsubscriptions,
        but user removals due to outside conditions. For example, a user might no
        longer belong to a group for which a subscription is mandatory.
        """
        return {
            SubscriptionActions.unsubscribe,
            SubscriptionActions.remove_subscriber,
            SubscriptionActions.add_unsubscription_override,
        }

    def is_unsubscribing(self) -> bool:
        """Whether ot not an action unsubscribes a user."""
        return self in self.unsubscribing_actions()

    @classmethod
    def managing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that require additional privileges.

        These should only be made accessible to moderators or administrators of
        subscriptions.
        """
        return {
            SubscriptionActions.approve_request,
            SubscriptionActions.deny_request,
            SubscriptionActions.block_request,
            SubscriptionActions.add_subscriber,
            SubscriptionActions.add_subscription_override,
            SubscriptionActions.add_unsubscription_override,
            SubscriptionActions.remove_subscriber,
            SubscriptionActions.remove_subscription_override,
            SubscriptionActions.remove_unsubscription_override,
            SubscriptionActions.reset,
        }

    def is_managing(self) -> bool:
        """Whether or not an action requires additional privileges."""
        return self in self.managing_actions()

    @classmethod
    def cleanup_actions(cls) -> Set["SubscriptionActions"]:
        """All actions which are part of more involved cleanup procedures.

        These can not be executed via `apply_action`, but should be executed
        via `do_cleanup` instead, since they need some particularly special checks.
        """
        return {
            SubscriptionActions.cleanup_subscription,
            SubscriptionActions.cleanup_implicit,
        }

    def is_automatic(self) -> bool:
        """Whether or not an action requires additional privileges."""
        return self in self.cleanup_actions()


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
