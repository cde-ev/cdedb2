"""This contains the exceptions used for control flow at subscription management."""

from typing import Any


class SubscriptionError(Exception):
    """Exception signaling that a `SubscriptionAction` has failed.

    `SubscriptionError` and its subclasses are exceptions expected to occur in
    subscription management. They are supposed to be caught and presented to the user
    triggering the respective action.
    """
    def __init__(self, *args: Any, kind: str = "error") -> None:
        super().__init__(*args)
        if args:
            self.msg = str(args[0])
        else:
            self.msg = ""
        self.kind = kind


class SubscriptionInfo(SubscriptionError):
    """Exception for SubscriptionErrors with kind info.

    `SubscriptionInfo` is raised if an action could not be performed, but the current
    state is identical to the desired state nevertheless. This exception can be
    silently dropped or presented to the user anyway, depending on preference.
    """
    def __init__(self, *args: Any) -> None:
        super().__init__(*args, kind="info")
