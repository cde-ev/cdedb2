#!/usr/bin/env python3

from typing import Collection, Dict, NewType, Tuple

import cdedb.subman as subman
from cdedb.subman.machine import SubscriptionAction, SubscriptionPolicy, SubscriptionState

# Some object representing a potential list subscriber
Persona = NewType("Persona", object)
# Some object representing a list of subscribers, a subscription object.
# Is expected to have an `allow_unsub` attribute.
ML = NewType("ML", object)

class PrivilegeError(RuntimeError):
    """Exception for signalling missing privileges."""

class ListManager:
    def __init__(self) -> None:
        self.subman = subman.SubscriptionManager()

    def may_manage(self, ml: ML) -> bool: ...

    def get_subscription_policy(self, persona: Persona, ml: ML) -> SubscriptionPolicy:
        ...

    def get_implicit_subscribers(self, ml: ML) -> Collection[Persona]: ...

    def get_subscription_states(self, ml: ML, states: Collection[SubscriptionState],
                                 ) -> Dict[Persona, SubscriptionState]: ...

    def get_subscription(self, persona: Persona, ml: ML) -> SubscriptionState: ...

    def _set_subscriptions(self, data: Collection[Tuple[Persona, ML, SubscriptionState]]
                           ) -> None: ...

    def do_subscription_action(self, action: SubscriptionAction, persona: Persona,
                               ml: ML) -> None:
        """Provide a single entry point for all subscription actions."""
        # Managing actions can only be done by moderators. Other options always
        # change your own subscription state.
        if action.is_managing():
            if not self.may_manage(ml):
                raise PrivilegeError()

        old_state = self.get_subscription(persona, ml)
        new_state = self.subman.apply_action(
            action=action,
            policy=self.get_subscription_policy(persona, ml),
            allow_unsub=ml.allow_unsub,  # type: ignore
            old_state=old_state)

        # Write the transition
        self._set_subscriptions([(persona, ml, new_state)])

    def write_subscription_states(self, ml: ML) -> None:
        """This takes care of writing implicit subscriptions to the db.

        This also checks the integrity of existing subscriptions.
        """
        # States we may not touch.
        protected_states = (self.subman.written_states
                            & self.subman.cleanup_protected_states)
        # States we may touch: non-special subscriptions.
        old_subscriber_states = (self.subman.written_states
                                 - self.subman.cleanup_protected_states)

        if not self.may_manage(ml):
            raise PrivilegeError()

        old_subscribers = self.get_subscription_states(ml, states=old_subscriber_states)
        new_implicits = self.get_implicit_subscribers(ml)

        # Check whether current subscribers may stay subscribed.
        # This is the case if they are still implicit subscribers of
        # the list or if `get_subscription_policy` says so.
        delete = []
        for persona in old_subscribers:
            policy = self.get_subscription_policy(persona, ml)
            state = old_subscribers[persona]
            if self.subman.is_obsolete(policy=policy, old_state=state,
                                       is_implied=persona in new_implicits):
                datum =  persona, ml, SubscriptionState.none
                delete.append(datum)

        # Remove those who may not stay subscribed.
        if delete:
            self._set_subscriptions(delete)

        # Check whether any implicit subscribers need to be written.
        # This is the case if they are not already old subscribers and
        # they don't have a protected subscription.
        protected = self.get_subscription_states(ml, states=protected_states)
        write = set(new_implicits) - set(old_subscribers) - set(protected)

        # Set implicit subscriptions.
        data = [(persona, ml, SubscriptionState.implicit) for persona in write]
        if data:
            self._set_subscriptions(data)
