Mailinglist Management
======================

We use a fairly complex state schema to manage mailinglist subscription states
internally. These states are only incompletely displayed to moderators and
admins using the management page, however a raw CSV file can be downloaded
showing the actual internal states.

.. figure:: SubscriptionStates.png
    :width: 60 %
    :alt: Subscription state schema
    :align: center
    :figclass: align-center

    This graphic was created using `Draw.io <https://draw.io>`_.
    To edit it, upload the SubscriptionStates.png file there.

We are using a total of seven distinct states, which allow a consistent and
useful subscription management, even if the mailinglist configuration changes.
These states are modeled in a way that external factors only determine which
state transitions may be done, but never to which state a given transition leads
to. Notably, not the state transitions, but the state obtained by a transition
determines the log codes. The only exemption to this rule is the decision of
subscription requests, which is using specific log codes.

There is a strict separation between transitions done by users and by moderators;
they are using different frontend endpoints which are accessed by different
interfaces. This way, even moderators and admins can request subscriptions to
lists they can manage, while they can only subscribe directly using the
management interface. Analogous, they can only subscribe to invitation only
lists using the management interface.

To maintain the correct states, we use a cron job running every 15 minutes to
take care of automatic state transitions. In contrast to user induced changes,
the changes done by the cron job are not logged.

In the CdEDBv2, we distinct between subscribing and other states, where users
listed in subscribing states receive list emails. For subscribers, there is no
visible distinction between the different subscribing states. Subscribing states
are:

Explicit Subscribed
    Users, which have been actively subscribed to a mailinglist, either by
    themselves or by a moderator, are saved as explicitly subscribed.
    If these users have no more means to access a list, for example because they
    lost membership, or because they no longer attend an event, they are removed
    from the mailinglist.
    Mailinglists without special membership implicators only have explicit
    subscribers.

Subscribe Override
    Subscribe Overrides are a special kind of explicit subscriptions, which are
    kept even if the user should not be able to access a list anymore. However,
    except for mandatory lists, they do not prevent a user from unsubscribing
    themselves.
    The list of Subscribe Overrides can be accessed by moderators via the
    management interface.

Implicit Subscribed
    Users, which are subscribed to a mailinglist, because it is opt-out or
    linked to an event or assembly, are listed as implicit subscribers. If they
    lose the automatic implicator that subscribes them to the list, they are
    removed even if they would still be able to access it.
    Implicit subscribers are stored in the database explicitly. This ensures the
    subscriber list displayed is always identical to the list of users emails
    are actually sent to.

Other states are:

None
    This is the standard state for users having no relationship to a list
    whatsoever, because they never were listed on it or lost access to it.
    This state is the only one not explicitly saved in the database.

Explicit Unsubscribed
    Users, which have specified they do not want to receive emails from a
    specifc mailinglist anymore. This decision is permanent, until manually
    reverted by them or a moderator. Even if they lose access to a list and
    regain it later on, they will not be receiving emails from it.
    However, if they are explicitly subscribed again, they do not receive
    special treatment.

Unsubscribe Override
    Unsubscribe Overrides are a special kind of explicit unsubscriptions, which
    can not be removed by the affected user. Except for mandatory lists, they
    can be used to block a specific user from any kind of subscription or
    subscription request and are displayed to a user when accessing the
    mailinglist information page.
    The list of Subscribe Overrides can be accessed by moderator via the
    management interface.

Waiting for moderation
    This is a special case only existing for mailinglists with moderated opt-in
    subscription policy for a group of users. These users are displayed on a
    specific list to moderators, so they can decide if they want to approve or
    deny their request. It is also possible to block further request by this
    user.

The only case, where a list configuration change explicitly changes subscription
states (Explicit and implicit subscriptions can still be removed if the
configuration change makes them lose their means of access!) is a conversion to
a mandatory list. In this case, all explicit unsubscriptions, including
Unsubscribe Overrides, are deleted.

Email adresses for specific mailinglists are saved separate from the
subscription state to make them persistent over all states.
