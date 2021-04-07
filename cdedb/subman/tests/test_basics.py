import enum
import unittest

from cdedb.subman import SubscriptionState


class SubmanTest(unittest.TestCase):
    """Collection of test cases for subman."""

    def test_subscription_state_enum(self) -> None:
        """Make sure the name-value pairs of the `SubcsriptionState` enum remain consistent."""
        self.assertTrue(issubclass(SubscriptionState, enum.IntEnum))
        try:
            enum.unique(SubscriptionState)
        except ValueError:
            self.fail("Enum contains duplicate values.")
        expectation = {
            "subscribed": 1,
            "unsubscribed": 2,
            "subscription_override": 10,
            "unsubscription_override": 11,
            "pending": 20,
            "implicit": 30,
            "none": 40,
        }
        name_value_map = {member.name: member.value for member in SubscriptionState}
        self.assertEqual(expectation, name_value_map)

    def test_cleanup_protection(self) -> None:
        """Make sure cleanup protection evaluates as expected."""
        self.assertEqual(SubscriptionState.cleanup_protected_states(),
                         {SubscriptionState.unsubscribed,
                          SubscriptionState.none,
                          SubscriptionState.subscription_override,
                          SubscriptionState.unsubscription_override,
                          SubscriptionState.pending})


if __name__ == "__main__":
    unittest.main()
