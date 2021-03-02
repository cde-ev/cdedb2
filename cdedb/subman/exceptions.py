from typing import Any


class SubscriptionError(Exception):
    """
    Exception for signalling that an action trying to change a subscription failed.
    """
    def __init__(self, *args: Any, kind: str = "error") -> None:
        super().__init__(*args)
        if args:
            self.msg = args[0]
        else:
            self.msg = ""

        # Kind if only a single notification is shown
        self.kind = kind


class SubscriptionInfo(SubscriptionError):
    """Exception for SubscriptionErrors with kind info."""
    def __init__(self, *args: Any) -> None:
        super().__init__(*args, kind="info")
