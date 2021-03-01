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
        return {SubscriptionStates.subscribed,
                SubscriptionStates.subscription_override,
                SubscriptionStates.implicit}

    @classmethod
    def cleanup_protected_states(cls) -> Set['SubscriptionStates']:
        sa = SubscriptionActions
        return {state for state in cls
                if sa.error_matrix()[sa.cleanup_subscription][state]}


@enum.unique
class SubscriptionPolicy(enum.IntEnum):
    """Regulate (un)subscriptions to mailinglists."""
    #: user may subscribe
    subscribable = 3
    #: user may subscribe, but only after approval
    moderated_opt_in = 4
    #: user may not subscribe by themselves
    invitation_only = 5
    #: only implicit subscribers allowed
    implicits_only = 6

    def is_implicit(self) -> bool:
        """Short-hand for
        policy == SubscriptionPolicy.implicits_only
        """
        return self == SubscriptionPolicy.implicits_only


@enum.unique
class SubscriptionLogCodes(enum.IntEnum):
    """Available log codes for action logging."""
    subscription_requested = 20  #: SubscriptionStates.subscription_requested
    subscribed = 21  #: SubscriptionStates.subscribed
    subscription_changed = 22  #: This is now used for address changes.
    unsubscribed = 23  #: SubscriptionStates.unsubscribed
    marked_override = 24  #: SubscriptionStates.subscription_override
    marked_blocked = 25  #: SubscriptionStates.unsubscription_override
    unsubscription_reset = 27  #:
    automatically_removed = 28  #:
    request_approved = 30  #:
    request_denied = 31  #:
    request_cancelled = 32  #:
    request_blocked = 33  #:


SubscriptionErrorMatrix = Dict["SubscriptionActions",
                               Dict[Optional[SubscriptionStates],
                                    Optional[SubscriptionError]]]


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
    remove_subscription_override = 31  #: A mod removing a fixed subscription.
    remove_unsubscription_override = 32  #: A moderator unblocking a user.
    #: A moderator removing the relation
    #: of an unsubscribed user to the mailinglist.
    reset_unsubscription = 40
    cleanup_subscription = 50
    cleanup_implicit = 51

    def get_target_state(self) -> Optional[SubscriptionStates]:
        """Get the target state associated with an action."""
        target_state = {
            SubscriptionActions.subscribe:
                SubscriptionStates.subscribed,
            SubscriptionActions.unsubscribe:
                SubscriptionStates.unsubscribed,
            SubscriptionActions.request_subscription:
                SubscriptionStates.pending,
            SubscriptionActions.cancel_request:
                None,
            SubscriptionActions.approve_request:
                SubscriptionStates.subscribed,
            SubscriptionActions.deny_request:
                None,
            SubscriptionActions.block_request:
                SubscriptionStates.unsubscription_override,
            SubscriptionActions.add_subscriber:
                SubscriptionStates.subscribed,
            SubscriptionActions.add_subscription_override:
                SubscriptionStates.subscription_override,
            SubscriptionActions.add_unsubscription_override:
                SubscriptionStates.unsubscription_override,
            SubscriptionActions.remove_subscriber:
                SubscriptionStates.unsubscribed,
            SubscriptionActions.remove_subscription_override:
                SubscriptionStates.subscribed,
            SubscriptionActions.remove_unsubscription_override:
                SubscriptionStates.unsubscribed,
            SubscriptionActions.reset_unsubscription:
                None,
            SubscriptionActions.cleanup_subscription:
                None,
            SubscriptionActions.cleanup_implicit:
                None
        }
        return target_state.get(self)

    def get_log_code(self) -> SubscriptionLogCodes:
        """Get the log code associated with performing an action."""
        log_code_map = {
            SubscriptionActions.subscribe:
                SubscriptionLogCodes.subscribed,
            SubscriptionActions.unsubscribe:
                SubscriptionLogCodes.unsubscribed,
            SubscriptionActions.request_subscription:
                SubscriptionLogCodes.subscription_requested,
            SubscriptionActions.cancel_request:
                SubscriptionLogCodes.request_cancelled,
            SubscriptionActions.approve_request:
                SubscriptionLogCodes.request_approved,
            SubscriptionActions.deny_request:
                SubscriptionLogCodes.request_denied,
            SubscriptionActions.block_request:
                SubscriptionLogCodes.request_blocked,
            SubscriptionActions.add_subscriber:
                SubscriptionLogCodes.subscribed,
            SubscriptionActions.add_subscription_override:
                SubscriptionLogCodes.marked_override,
            SubscriptionActions.add_unsubscription_override:
                SubscriptionLogCodes.marked_blocked,
            SubscriptionActions.remove_subscriber:
                SubscriptionLogCodes.unsubscribed,
            SubscriptionActions.remove_subscription_override:
                SubscriptionLogCodes.subscribed,
            SubscriptionActions.remove_unsubscription_override:
                SubscriptionLogCodes.unsubscribed,
            SubscriptionActions.reset_unsubscription:
                SubscriptionLogCodes.unsubscription_reset,
            SubscriptionActions.cleanup_subscription:
                SubscriptionLogCodes.automatically_removed,
            SubscriptionActions.cleanup_implicit:
                SubscriptionLogCodes.automatically_removed,
        }
        return log_code_map[self]

    @staticmethod
    def error_matrix() -> SubscriptionErrorMatrix:
        """This defines the logic of which state transitions are legal.

        SubscriptionErrors defined in this matrix will be raised by the backend.
        """
        ss = SubscriptionStates
        error = SubscriptionError
        info = SubscriptionInfo

        matrix: SubscriptionErrorMatrix = {
            SubscriptionActions.add_subscriber: {
                ss.subscribed: info(_("User already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(_("User already subscribed.")),
                ss.unsubscription_override: error(_(
                    "User has been blocked. Remove override before reset.")),
                ss.pending: error(_("User has pending subscription request.")),
                ss.implicit: info(_("User already subscribed.")),
                None: None
            },
            SubscriptionActions.remove_subscriber: {
                ss.subscribed: None,
                ss.unsubscribed: info(_("User already unsubscribed.")),
                ss.subscription_override: error(_(
                    "User cannot be removed, Remove override to change this.")),
                ss.unsubscription_override: info(_("User already unsubscribed.")),
                ss.pending: error(_("User has pending subscription request.")),
                ss.implicit: None,
                None: info(_("User already unsubscribed.")),
            },
            SubscriptionActions.add_subscription_override: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.subscription_override: info(_("User is already force-subscribed.")),
                ss.unsubscription_override: None,
                ss.pending: error(_("User has pending subscription request.")),
                ss.implicit: None,
                None: None,
            },
            SubscriptionActions.remove_subscription_override: {
                ss.subscribed: error(_("User is not force-subscribed.")),
                ss.unsubscribed: error(_("User is not force-subscribed.")),
                ss.subscription_override: None,
                ss.unsubscription_override: error(_("User is not force-subscribed.")),
                ss.pending: error(_("User is not force-subscribed.")),
                ss.implicit: error(_("User is not force-subscribed.")),
                None: error(_("User is not force-subscribed.")),
            },
            SubscriptionActions.add_unsubscription_override: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.subscription_override: None,
                ss.unsubscription_override: info(_("User has already been blocked.")),
                ss.pending: error(_("User has pending subscription request.")),
                ss.implicit: None,
                None: None,
            },
            SubscriptionActions.remove_unsubscription_override: {
                ss.subscribed: error(_("User is not force-unsubscribed.")),
                ss.unsubscribed: error(_("User is not force-unsubscribed.")),
                ss.subscription_override: error(_("User is not force-unsubscribed.")),
                ss.unsubscription_override: None,
                ss.pending: error(_("User is not force-unsubscribed.")),
                ss.implicit: error(_("User is not force-unsubscribed.")),
                None: error(_("User is not force-unsubscribed.")),
            },
            SubscriptionActions.subscribe: {
                ss.subscribed: info(_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(_("You are already subscribed.")),
                ss.unsubscription_override: error(
                    _("Can not change subscription because you are blocked.")),
                ss.pending: None,
                ss.implicit: info(_("You are already subscribed.")),
                None: None,
            },
            SubscriptionActions.request_subscription: {
                ss.subscribed: info(_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(_("You are already subscribed.")),
                ss.unsubscription_override: error(
                    _("Can not request subscription because you are blocked.")),
                ss.pending: info(_("You already requested subscription")),
                ss.implicit: info(_("You are already subscribed.")),
                None: None,
            },
            SubscriptionActions.unsubscribe: {
                ss.subscribed: None,
                ss.unsubscribed: info(_("You are already unsubscribed.")),
                # subscription_override should only block you from being unsubscribed
                # automatically. A user is still able to unsubscribe manually.
                # (Unless the list is mandatory).
                ss.subscription_override: None,
                ss.unsubscription_override: info(_("You are already unsubscribed.")),
                ss.pending: info(_("You are already unsubscribed.")),
                ss.implicit: None,
                None: info(_("You are already unsubscribed.")),
            },
            SubscriptionActions.approve_request: {
                ss.subscribed: error(_("Not a pending subscription request.")),
                ss.unsubscribed: error(_("Not a pending subscription request.")),
                ss.subscription_override: error(
                    _("Not a pending subscription request.")),
                ss.unsubscription_override: error(
                    _("Not a pending subscription request.")),
                ss.pending: None,
                ss.implicit: error(_("Not a pending subscription request.")),
                None: error(_("Not a pending subscription request.")),
            },
            SubscriptionActions.reset_unsubscription: {
                ss.subscribed: error(_("User is not unsubscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: error(_(
                    "User is in override state. Remove them before reset.")),
                ss.unsubscription_override: error(_(
                    "User is in override state. Remove them before reset.")),
                ss.pending: error(_("User is not unsubscribed.")),
                ss.implicit: error(_("User is not unsubscribed.")),
                None: None,
            },
            SubscriptionActions.cleanup_subscription: {
                ss.subscribed: None,
                ss.unsubscribed: error(_(
                    "Unsubscriptions are protected against automatic cleanup.")),
                ss.subscription_override: error(_(
                    "Overrides are protected against automatic cleanup.")),
                ss.unsubscription_override: error(_(
                    "Overrides are protected against automatic cleanup.")),
                ss.pending: error(_(
                    "Pending requests are protected against automatic cleanup.")),
                ss.implicit: None,
                None: info(_("Subscription already cleaned up.")),
            },
            SubscriptionActions.cleanup_implicit: {
                ss.subscribed:  error(_(
                    "Subscriptions are protected against automatic implicit cleanup.")),
                ss.unsubscribed: error(_(
                    "Unsubscriptions are protected against automatic cleanup.")),
                ss.subscription_override: error(_(
                    "Overrides are protected against automatic cleanup.")),
                ss.unsubscription_override: error(_(
                    "Overrides are protected against automatic cleanup.")),
                ss.pending: error(_(
                    "Pending requests are protected against automatic cleanup.")),
                ss.implicit: None,
                None: info(_("Subscription already cleaned up.")),
            },
        }

        matrix[SubscriptionActions.deny_request] = matrix[SubscriptionActions.approve_request]
        matrix[SubscriptionActions.cancel_request] = matrix[SubscriptionActions.approve_request]
        matrix[SubscriptionActions.block_request] = matrix[SubscriptionActions.approve_request]

        return matrix

    @classmethod
    def unsubscribing_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that unsubscribe a user from a mailinglist."""
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
            SubscriptionActions.reset_unsubscription,
        }

    def is_managing(self) -> bool:
        """Whether or not an action requires additional privileges."""
        return self in self.managing_actions()

    @classmethod
    def automatic_actions(cls) -> Set["SubscriptionActions"]:
        """All actions that require additional privileges."""
        return {
            SubscriptionActions.cleanup_subscription,
            SubscriptionActions.cleanup_implicit,
        }

    def is_automatic(self) -> bool:
        """Whether or not an action requires additional privileges."""
        return self in self.automatic_actions()
