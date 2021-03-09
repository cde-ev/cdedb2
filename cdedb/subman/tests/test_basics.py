import enum
import unittest

from cdedb.subman import SubscriptionStates


class BackwardsCompatibilityTest(unittest.TestCase):
    """Collection of test cases to protect against non-backwords-compatible changes."""

    def test_subscription_state_enum(self) -> None:
        """Make sure the name-value pairs of the `SubcsriptionState` enum remain consistent."""
        self.assertTrue(issubclass(SubscriptionStates, enum.IntEnum))
        try:
            enum.unique(SubscriptionStates)
        except ValueError:
            self.fail("Enum contains duplicate values.")
        expectation = {
            "subscribed": 1,
            "unsubscribed": 2,
            "subscription_override": 10,
            "unsubscription_override": 11,
            "pending": 20,
            "implicit": 30,
        }
        name_value_map = {member.name: member.value for member in SubscriptionStates}
        self.assertEqual(expectation, name_value_map)


if __name__ == "__main__":
    unittest.main()
