"""This contains the exceptions used for control flow at subscription management."""

from typing import Any


class SubscriptionError(Exception):
    """
    Signals that a `SubscriptionAction` has failed.

    `SubscriptionError` and its subclasses are Exceptions expected to occur in
    subscription management. They are supposed to be caught and presented to the user
    triggering the respective action.
    """
    def __init__(self, *args: Any, kind: str = "error") -> None:
        super().__init__(*args)
        if args:
            self.msg = args[0]
        else:
            self.msg = ""
        self.kind = kind


class SubscriptionInfo(SubscriptionError):
    """Exception for SubscriptionErrors with kind info.

    `SubscriptionInfo` is raised if a certain action could not be performend, but the
    state present is identical to the desired state nevertheless. In this case, you may
    decide to drop the extension silently or present it anyway, according to your
    perference.
    """
    def __init__(self, *args: Any) -> None:
        super().__init__(*args, kind="info")
