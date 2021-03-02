"""This keeps a lot of the business logic for ml subscriptions together.

These are be imported in `cdedb:common.py` and should be imported from there.

`SubscriptionError` and it's subclasses are Exceptions expected to occurr in
    the ml backend when handling subscriptions. They are cought in the frontend
    and depending on the kind parameter different kinds of notifications are
    displayed.

`SubscriptionsActions` define the possible actions users, moderators and/or
    admins may take to change the subscriptions of other users or themselves.

    Every actions has exactly one intended target state (see
    `cdedb.database.constants:SubscriptionsStates`) and exactly one log code.

    In the `error_matrix` the consequences of performing a specific action
    while being in a specific previous state are defined. `None` signifies
    that the action is legal, otherwise a `SubscriptionError` (or a subclass)
    is given, which is raised by the ml backend.

    Some of these actions have additional properties, like being a
    'unsubscribing action' or a 'managing action'. These are used to determine
    the necessary privileges and/or legality for that action.
"""

import enum
from gettext import gettext as _
from typing import Dict, Optional, Set

from .exceptions import SubscriptionError, SubscriptionInfo


@enum.unique
class SubscriptionStates(enum.IntEnum):
    """Define the possible relations between user and mailinglist."""
    #: The user is explicitly subscribed.
    subscribed = 1
    #: The user is explicitly unsubscribed (usually from an Opt-Out list).
    unsubscribed = 2
    #: The user was explicitly added by a moderator.
    subscription_override = 10
    #: The user was explicitly removed/blocked by a moderator.
    unsubscription_override = 11
    #: The user has requested a subscription to the mailinglist.
    pending = 20
    #: The user is subscribed by virtue of being part of some group.
    implicit = 30

    def is_subscribed(self) -> bool:
        return self in self.subscribing_states()

    @classmethod
    def subscribing_states(cls) -> Set['SubscriptionStates']:
        return {cls.subscribed, cls.subscription_override, cls.implicit}

    @classmethod
    def cleanup_protected_states(cls) -> Set['SubscriptionStates']:
        return _CLEANUP_PROTECTED_STATES


@enum.unique
class SubscriptionPolicy(enum.IntEnum):
    """Regulate (un)subscriptions to mailinglists."""
    #: user may subscribe
    subscribable = 1
    #: user may subscribe, but only after approval
    moderated_opt_in = 2
    #: user may not subscribe by themselves
    invitation_only = 3
    #: only implicit subscribers allowed
    implicits_only = 4

    def is_implicit(self) -> bool:
        """Short-hand for policy == SubscriptionPolicy.implicits_only"""
        return self == SubscriptionPolicy.implicits_only


@enum.unique
class SubscriptionLogCodes(enum.IntEnum):
    """Available log codes for action logging."""
    subscribed = 1  #: SubscriptionStates.subscribed
    unsubscribed = 2  #: SubscriptionStates.unsubscribed
    marked_override = 3  #: SubscriptionStates.subscription_override
    marked_blocked = 4  #: SubscriptionStates.unsubscription_override
    automatically_removed = 10  #:
    subscription_requested = 20  #: SubscriptionStates.subscription_requested
    request_approved = 21  #:
    request_denied = 22  #:
    request_cancelled = 23  #:
    request_blocked = 24  #:
    reset = 30  #:


@enum.unique
class SubscriptionActions(enum.IntEnum):
    """All possible actions a subscriber or moderator can take."""
    subscribe = 1  #: A user subscribing themselves to a mailinglist.
    unsubscribe = 2  #: A user removing their subscription to a mailinglit.
    request_subscription = 10  #: Requesting subscription to a mod-opt-in list.
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
    #: A moderator removing the relation
    #: of an unsubscribed user to the mailinglist.
    reset = 40
    cleanup_subscription = 50
    cleanup_implicit = 51

    def get_target_state(self) -> Optional[SubscriptionStates]:
        """Get the target state associated with an action."""
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

        SubscriptionErrors defined in this matrix will be raised by the backend.
        """
        return _SUBSCRIPTION_ERROR_MATRIX

    @classmethod
    def unsubscribing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that unsubscribe a user from a mailinglist.

        While cleanup_actions are removing a user from a mailinglist, we do not
        consider them unsubscribing, since they do not represent active unsubscriptions,
        but user removals due to outside conditions. For example, a user might no
        longer belong to a group for which a user is mandatory."""
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
        """All actions that require additional privileges."""
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

        These can not be executed via `subman.apply_action`, but should be executed
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
