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
from typing import Any, Dict, Optional, Set

from cdedb.database.constants import MlLogCodes, SubscriptionStates


def n_(x: str) -> str:
    """Clone of `cdedb.common.n_` used for marking translatable strings."""
    return x


class SubscriptionError(RuntimeError):
    """
    Exception for signalling that an action trying to change a subscription
    failed.
    """
    def __init__(self, *args: Any, kind: str = "error") -> None:
        super(SubscriptionError, self).__init__(*args)
        if args:
            self.msg = args[0]
        else:
            self.msg = ""

        # Kind if only a single notification is shown
        self.kind = kind

        # Kind if multiple notifications are shown
        self.multikind = kind
        if self.multikind == "error":
            self.multikind = "warning"


class SubscriptionInfo(SubscriptionError):
    """Exception for SubscriptionErrors with kind info."""
    def __init__(self, *args: Any) -> None:
        super().__init__(*args, kind="info")


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
        }
        return target_state.get(self)

    def get_log_code(self) -> MlLogCodes:
        """Get the log code associated with performing an action."""
        log_code_map = {
            SubscriptionActions.subscribe:
                MlLogCodes.subscribed,
            SubscriptionActions.unsubscribe:
                MlLogCodes.unsubscribed,
            SubscriptionActions.request_subscription:
                MlLogCodes.subscription_requested,
            SubscriptionActions.cancel_request:
                MlLogCodes.request_cancelled,
            SubscriptionActions.approve_request:
                MlLogCodes.request_approved,
            SubscriptionActions.deny_request:
                MlLogCodes.request_denied,
            SubscriptionActions.block_request:
                MlLogCodes.request_blocked,
            SubscriptionActions.add_subscriber:
                MlLogCodes.subscribed,
            SubscriptionActions.add_subscription_override:
                MlLogCodes.marked_override,
            SubscriptionActions.add_unsubscription_override:
                MlLogCodes.marked_blocked,
            SubscriptionActions.remove_subscriber:
                MlLogCodes.unsubscribed,
            SubscriptionActions.remove_subscription_override:
                MlLogCodes.subscribed,
            SubscriptionActions.remove_unsubscription_override:
                MlLogCodes.unsubscribed,
            SubscriptionActions.reset_unsubscription:
                MlLogCodes.unsubscription_reset,
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
                ss.subscribed: info(n_("User already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(n_("User already subscribed.")),
                ss.unsubscription_override: error(n_(
                    "User has been blocked. You can use Advanced Management to"
                    " change this.")),
                ss.pending: error(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_subscriber: {
                ss.subscribed: None,
                ss.unsubscribed: info(n_("User already unsubscribed.")),
                ss.subscription_override: error(n_(
                    "User cannot be removed, because of moderator override. You"
                    " can use Advanced Management to change this.")),
                ss.unsubscription_override: info(n_("User already unsubscribed.")),
                ss.pending: error(n_("User has pending subscription request.")),
            },
            SubscriptionActions.add_subscription_override: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.subscription_override: info(n_("User is already force-subscribed.")),
                ss.unsubscription_override: None,
                ss.pending: error(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_subscription_override: {
                ss.subscribed: error(n_("User is not force-subscribed.")),
                ss.unsubscribed: error(n_("User is not force-subscribed.")),
                ss.subscription_override: None,
                ss.unsubscription_override: error(n_("User is not force-subscribed.")),
                ss.pending: error(n_("User is not force-subscribed.")),
            },
            SubscriptionActions.add_unsubscription_override: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.subscription_override: None,
                ss.unsubscription_override: info(n_("User has already been blocked.")),
                ss.pending: error(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_unsubscription_override: {
                ss.subscribed: error(n_("User is not force-unsubscribed.")),
                ss.unsubscribed: error(n_("User is not force-unsubscribed.")),
                ss.subscription_override: error(n_("User is not force-unsubscribed.")),
                ss.unsubscription_override: None,
                ss.pending: error(n_("User is not force-unsubscribed.")),
            },
            SubscriptionActions.subscribe: {
                ss.subscribed: info(n_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(n_("You are already subscribed.")),
                ss.unsubscription_override: error(
                    n_("Can not change subscription because you are blocked.")),
                ss.pending: None,
            },
            SubscriptionActions.request_subscription: {
                ss.subscribed: info(n_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: info(n_("You are already subscribed.")),
                ss.unsubscription_override: error(
                    n_("Can not request subscription because you are blocked.")),
                ss.pending: info(n_("You already requested subscription")),
            },
            SubscriptionActions.unsubscribe: {
                ss.subscribed: None,
                ss.unsubscribed: info(n_("You are already unsubscribed.")),
                # subscription_override should only block you from being unsubscribed
                # by the cronjob. A user is still able to unsubscribe manually.
                # (Unless the list is mandatory).
                ss.subscription_override: None,
                ss.unsubscription_override: info(n_("You are already unsubscribed.")),
                ss.pending: info(n_("You are already unsubscribed.")),
            },
            SubscriptionActions.cancel_request: {
                ss.subscribed: error(n_("No subscription requested.")),
                ss.unsubscribed: error(n_("No subscription requested.")),
                ss.subscription_override: error(n_("No subscription requested.")),
                ss.unsubscription_override: error(n_("No subscription requested.")),
                ss.pending: None,
            },
            SubscriptionActions.approve_request: {
                ss.subscribed: error(n_("Not a pending subscription request.")),
                ss.unsubscribed: error(n_("Not a pending subscription request.")),
                ss.subscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.unsubscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.pending: None,
            },
            SubscriptionActions.deny_request: {
                ss.subscribed: error(n_("Not a pending subscription request.")),
                ss.unsubscribed: error(n_("Not a pending subscription request.")),
                ss.subscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.unsubscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.pending: None,
            },
            SubscriptionActions.block_request: {
                ss.subscribed: error(n_("Not a pending subscription request.")),
                ss.unsubscribed: error(
                    n_("Not a pending subscription request.")),
                ss.subscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.unsubscription_override: error(
                    n_("Not a pending subscription request.")),
                ss.pending: None,
            },
            SubscriptionActions.reset_unsubscription: {
                ss.subscribed: error(n_("User is not unsubscribed.")),
                ss.unsubscribed: None,
                ss.subscription_override: error(n_("User is not unsubscribed.")),
                ss.unsubscription_override: error(n_(
                    "User has been blocked. You can use Advanced Management to"
                    " change this.")),
                ss.pending: error(n_("User is not unsubscribed.")),
            }
        }

        for row in matrix:
            # Implicit (un-)subscriptions behave identically.
            matrix[row][ss.implicit] = matrix[row][ss.subscribed]
            matrix[row][None] = matrix[row][ss.unsubscribed]
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
