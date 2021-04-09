import enum
import itertools
import unittest

from cdedb.subman import SubscriptionState, SubscriptionManager


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
        self.assertEqual(name_value_map, expectation)

    def test_cleanup_protection(self) -> None:
        """Make sure the default cleanup protection evaluates as expected."""
        subman = SubscriptionManager()
        expectation = {SubscriptionState.unsubscribed,
                       SubscriptionState.none,
                       SubscriptionState.subscription_override,
                       SubscriptionState.unsubscription_override,
                       SubscriptionState.pending}
        self.assertEqual(subman.cleanup_protected_states, expectation)

    def test_written_states(self) -> None:
        state_set = set(SubscriptionState)
        for n in range(len(state_set)):
            for unwritten in itertools.combinations(state_set, n + 1):
                subman = SubscriptionManager(unwritten_states=unwritten)
                self.assertEqual(subman.unwritten_states, set(unwritten))
                self.assertEqual(subman.written_states, state_set.difference(unwritten))


if __name__ == "__main__":
    unittest.main()
