"""subman – Powerful Python package to manage subscriptions"""

from .exceptions import SubscriptionError, SubscriptionInfo
from .machine import SubscriptionAction, SubscriptionPolicy, SubscriptionState
from .subman import SubscriptionManager

__all__ = ['SubscriptionAction', 'SubscriptionError', 'SubscriptionInfo',
           'SubscriptionState', 'SubscriptionPolicy', 'SubscriptionManager']
