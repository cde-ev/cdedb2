import enum
from cdedb.database.constants import SubscriptionStates, MlLogCodes


def n_(x):
    """Clone of `cdedb.common.n_` used for marking translatable strings."""
    return x


class SubscriptionError(RuntimeError):
    """
    Exception for signalling that an action trying to change a subscription
    failed.
    """
    def __init__(self, *args, kind="error", **kwargs):
        super().__init__(*args, **kwargs)
        if args:
            self.msg = args[0]
        else:
            self.msg = ""
        self.kind = kind
    pass


class SubscriptionWarning(SubscriptionError):
    """Exception for SubscriptionErrors with kind warning."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, kind="warning", **kwargs)


class SubscriptionInfo(SubscriptionError):
    """Exception for SubscriptionErrors with kind info."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, kind="info", **kwargs)


@enum.unique
class SubscriptionActions(enum.IntEnum):
    """All possible actions a subscriber or moderator can take."""
    subscribe = 1  #:
    unsubscribe = 2  #:
    request_subscription = 10  #:
    cancel_request = 11  #:
    approve_request = 12  #:
    deny_request = 13  #:
    block_request = 14  #:
    add_subscriber = 20  #:
    add_mod_subscriber = 21  #:
    add_mod_unsubscriber = 22  #:
    remove_subscriber = 30  #:
    remove_mod_subscriber = 31  #:
    remove_mod_unsubscriber = 32  #:

    def get_target_state(self):
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
                SubscriptionStates.mod_unsubscribed,
            SubscriptionActions.add_subscriber:
                SubscriptionStates.subscribed,
            SubscriptionActions.add_mod_subscriber:
                SubscriptionStates.mod_subscribed,
            SubscriptionActions.add_mod_unsubscriber:
                SubscriptionStates.mod_unsubscribed,
            SubscriptionActions.remove_subscriber:
                SubscriptionStates.unsubscribed,
            SubscriptionActions.remove_mod_subscriber:
                SubscriptionStates.subscribed,
            SubscriptionActions.remove_mod_unsubscriber:
                SubscriptionStates.unsubscribed
        }
        return target_state.get(self)

    def get_log_code(self):
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
            SubscriptionActions.add_mod_subscriber:
                MlLogCodes.marked_override,
            SubscriptionActions.add_mod_unsubscriber:
                MlLogCodes.marked_blocked,
            SubscriptionActions.remove_subscriber:
                MlLogCodes.unsubscribed,
            SubscriptionActions.remove_mod_subscriber:
                MlLogCodes.subscribed,
            SubscriptionActions.remove_mod_unsubscriber:
                MlLogCodes.unsubscribed,
        }
        return log_code_map.get(self)

    @staticmethod
    def error_matrix():
        ss = SubscriptionStates
        error = SubscriptionError
        warning = SubscriptionWarning
        info = SubscriptionInfo

        matrix = {
            SubscriptionActions.add_subscriber: {
                ss.subscribed: info(n_("User already subscribed.")),
                ss.unsubscribed: None,
                ss.mod_subscribed: info(n_("User already subscribed.")),
                ss.mod_unsubscribed: warning(n_(
                    "User has been blocked. You can use Advanced Management to"
                    " change this.")),
                ss.pending: warning(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_subscriber: {
                ss.subscribed: None,
                ss.unsubscribed: info(n_("User already unsubscribed.")),
                ss.mod_subscribed: warning(n_(
                    "User cannot be removed, because of moderator override. You"
                    " can use Advanced Management to change this.")),
                ss.mod_unsubscribed: info(n_("User already unsubscribed.")),
                ss.pending: warning(n_("User has pending subscription request.")),
            },
            SubscriptionActions.add_mod_subscriber: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.mod_subscribed: None,
                ss.mod_unsubscribed: None,
                ss.pending: warning(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_mod_subscriber: {
                ss.subscribed: error(n_("User is not force-subscribed.")),
                ss.unsubscribed: error(n_("User is not force-subscribed.")),
                ss.mod_subscribed: None,
                ss.mod_unsubscribed: error(n_("User is not force-subscribed.")),
                ss.pending: error(n_("User is not force-subscribed.")),
            },
            SubscriptionActions.add_mod_unsubscriber: {
                ss.subscribed: None,
                ss.unsubscribed: None,
                ss.mod_subscribed: None,
                ss.mod_unsubscribed: None,
                ss.pending: warning(n_("User has pending subscription request.")),
            },
            SubscriptionActions.remove_mod_unsubscriber: {
                ss.subscribed: error(n_("User is not force-unsubscribed.")),
                ss.unsubscribed: error(n_("User is not force-unsubscribed.")),
                ss.mod_subscribed: error(n_("User is not force-unsubscribed.")),
                ss.mod_unsubscribed: None,
                ss.pending: error(n_("User is not force-unsubscribed.")),
            },
            SubscriptionActions.subscribe: {
                ss.subscribed: info(n_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.mod_subscribed: info(n_("You are already subscribed.")),
                ss.mod_unsubscribed: error(
                    n_("Can not change subscription because you are blocked.")),
                ss.pending: None,
            },
            SubscriptionActions.request_subscription: {
                ss.subscribed: info(n_("You are already subscribed.")),
                ss.unsubscribed: None,
                ss.mod_subscribed: info(n_("You are already subscribed.")),
                ss.mod_unsubscribed: error(
                    n_("Can not change subscription because you are blocked.")),
                ss.pending: info(n_("You already requested subscription")),
            },
            SubscriptionActions.unsubscribe: {
                ss.subscribed: None,
                ss.unsubscribed: info(n_("You are already unsubscribed.")),
                ss.mod_subscribed: None,  # This is on purpose.
                ss.mod_unsubscribed: info(n_("You are already unsubscribed.")),
                ss.pending: info(n_("You are already unsubscribed.")),
            },
            SubscriptionActions.cancel_request: {
                ss.subscribed: info(n_("No subscription requested.")),
                ss.unsubscribed: info(n_("No subscription requested.")),
                ss.mod_subscribed: info(n_("No subscription requested.")),
                ss.mod_unsubscribed: info(n_("No subscription requested.")),
                ss.pending: None,
            },
            SubscriptionActions.approve_request: {
                ss.subscribed: error(n_("Not a pending subscription request.")),
                ss.unsubscribed: error(n_("Not a pending subscription request.")),
                ss.mod_subscribed: error(n_("Not a pending subscription request.")),
                ss.mod_unsubscribed: error(n_("Not a pending subscription request.")),
                ss.pending: None,
            },
            SubscriptionActions.deny_request: {},
            SubscriptionActions.block_request: {},
        }
        matrix[SubscriptionActions.deny_request] =\
            matrix[SubscriptionActions.approve_request]
        matrix[SubscriptionActions.block_request] =\
            matrix[SubscriptionActions.approve_request]

        for row in matrix.keys():
            matrix[row][ss.implicit] = matrix[row][ss.subscribed]
            matrix[row][None] = matrix[row][ss.unsubscribed]
        return matrix

    @classmethod
    def unsubscribing_actions(cls):
        return {
            SubscriptionActions.unsubscribe,
            SubscriptionActions.remove_subscriber,
            SubscriptionActions.add_mod_unsubscriber,
        }

    def is_unsubscribing(self):
        return self in self.unsubscribing_actions()

    @classmethod
    def managing_actions(cls):
        return {
            SubscriptionActions.approve_request,
            SubscriptionActions.deny_request,
            SubscriptionActions.block_request,
            SubscriptionActions.add_subscriber,
            SubscriptionActions.add_mod_subscriber,
            SubscriptionActions.add_mod_unsubscriber,
            SubscriptionActions.remove_subscriber,
            SubscriptionActions.remove_mod_subscriber,
            SubscriptionActions.remove_mod_unsubscriber
        }

    def is_managing(self):
        return self in self.managing_actions()

