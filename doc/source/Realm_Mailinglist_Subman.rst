Subman
======

Subman uses a fairly complex state schema to manage subscription states
internally. Its behavior can be configured using the ``SubscriptionManager``,
which is also the main interface of the library.

.. figure:: SubscriptionStates.png
    :width: 70 %
    :alt: Subscription state schema
    :align: center
    :figclass: align-center

    This graphic was created using `Draw.io <https://draw.io>`_.
    To edit it, upload the SubscriptionState.png file there.

Subman uses a total of seven distinct states, which allow a consistent and
useful subscription management, even if the condition for list membership change.
Of these, four states are so-called core states, without which the software can not
function properly, while the other states are optional.

Every transition between these states is modeled by a corresponding ``SubscriptionAction``,
which are shown as arrows in the graph. While most subscription actions act on multiple
states, there is always a unique target state associated with each action.

Subman includes a distinction between action which require additional privileges
(possibly depending on the list in question). These privileged users are referred to as
"moderators". Actions restricted to moderators are referred to as "managing actions".

In addition to the manual actions which can be performed, it is required to
regularly perform cleanup actions to react to changes in implicators.
This actually does not make use of the ``SubscriptionAction`` enum, but makes use of
its own internal state transitioning logic given in
``SubscriptionManager._apply_cleanup()``.

In subman, we differentiate between subscribing (shown in green in the graph)
and non-subscribing states (shown in red), where users
listed in subscribing states are considered to be subscribed in the usual sense.
For subscribers, there is no visible distinction between the different
subscribing states intended.

List of states
--------------
Subscribing states are:

Explicitly Subscribed (Core)
    Users, which have been actively subscribed to a list, either by
    themselves or by a moderator, are saved as explicitly subscribed.
    If these users have no more means to access a list, for example because they
    lost club membership, or because they no longer attend an event, they are removed
    from the list.
    Lists without special membership implicators only have explicit subscribers.

Subscription Override (Optional)
    Subscription Overrides are a special kind of explicit subscriptions, which are
    kept even if the user should not be able to access a list. However,
    if a list allows unsubscribing in general, they do not prevent a user from
    unsubscribing themselves.
    The list of Subscription Overrides should be accessible for moderators.

Implicitly Subscribed (Core)
    Users, which are subscribed to a list, because they meet some condition,
    are listed as implicit subscribers. Typical examples are lists having all
    members or all attendees of an event or assembly as implicit subscribers. If users
    lose the automatic implicator that subscribes them to the list, they are
    removed even if they would still be able to access it.

    It is optional to store implicit subscribers explicitly. Otherwise, they have to
    be calculated at runtime.

Non-subscribing states are:

Implicitly Unsubscribed (Core)
    This is the standard state for users having no relationship to a list
    whatsoever, because they never were listed on it or lost access to it.

    It is optional to store this state explicitly.

.. _Explicitly_Unsubscribed:

Explicitly Unsubscribed (Core)
    Users, who have stated to not want to receive information from a
    specific list anymore. This decision is permanent, until manually
    reverted by them or a moderator. Even if they lose access to a list, this
    information is kept. Thus, if they regain access later on, these users
    will not be receiving information from it.
    However, if they are explicitly subscribed again, they do not receive
    special treatment.

    Due to this fact, users tend to get "stuck" in this case, since it is not
    cleaned up automatically. For example, every user who has been manually
    removed from a list by a moderator, will stay here forever without
    further intervention. While the state transitions are designed with this
    in mind, making no difference between manual actions on explicitly and
    implicitly unsubscribed users, it is still possible for moderators to
    cleanup explicit unsubscriptions to implicit subscriptions.

    To not obstruct the design of the state schema, this should only be used
    to cleanup test cases or to prepare for the use of tools which might be
    obstructed by explicit unsubscriptions.

Unsubscription Override (Optional)
    Unsubscription Overrides are a special kind of explicit unsubscriptions, which
    can not be removed by the affected user. Except for mandatory lists, they
    can be used to block a specific user from any kind of subscription or
    subscription request.
    The list of Unsubscription Overrides should be accessible for moderators.

Request Pending (Optional)
    This is a special case only existing for mailinglists with moderated opt-in
    subscription policy for a group of users.
    Users with pending subscription requests are displayed on a
    specific list to moderators, so they can decide if they want to approve or
    deny their request. It is also possible to block further requests by this
    user.

When changing the ``SubscriptionPolicy`` associated to a certain list, subman
can handle updating its subscribers automatically. However, if the list is set
to ``allow_unsub = False``, all users with explicit unsubscriptions,
including Unsubscription Overrides, need to be cleaned up during the transition.
If subman detects this has not been done, it will raise an error.

Usage example
-------------

Internationalization
--------------------
Like the CdEDBv2, subman is internationalized using GNU gettext. By adding
translations for the respective strings, users of the library can customize error
messages to their heart's content.
