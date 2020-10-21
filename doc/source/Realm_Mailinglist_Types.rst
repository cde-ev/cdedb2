Mailinglist Types
=================

To catch all required use cases while reducing the probability of configuration
errors and providing a useful sorting order, the code defines different
mailinglist types. This allows us to support even complex use cases if required,
while not overloading the interface. Furthermore, additional admin roles
are allowed to manage mailinglists depending on their type. More information
about implicit subscriptions is provided in the
:doc:`Realm_Mailinglist_Management` section.

Currently, we are using the following types:

Member Mailinglists (implicit)
    Mailinglists that are listing all CdE members as implicit subscribers by
    default. Other users are not allowed to subscribe.

    * visible to: CdE members
    * additional admins: None for Mandatory, cde for Opt-out
    * sortkey: cde

    The following subtypes are supported:

    * Mandatory
    * Opt-out

Member Mailinglists (explicit)
    Mailinglists for CdE members. Other users are not allowed to subscribe.

    * visible to: CdE members
    * additional admins: cde
    * sortkey: cde

    The following subtypes are supported:

    * Opt-in
    * Moderated Opt-in
    * Invitation only

Team Mailinglists
    Mailinglists that are used for coordination of public teams. In contrast to
    member mailinglists, they are visible to all users. Only CdE users are
    allowed to subscribe.

    * visible to: all users
    * additional admins: cde
    * sortkey: team

    The following subtypes are supported:

    * Moderated Opt-in
    * Invitation only

Event Mailinglists
    Mailinglists that contain users having a given status for at least one
    part of a given event as implicit subscribers. Other users are not allowed
    to subscribe.

    If an event list is not linked to an event, it behaves as an invitation
    only list for all users.

    * visible to: event users
    * additional admins: event
    * sortkey: event

Orga Mailinglists
    Mailinglists that contain the orga team of a specified event as implicit
    subscribers. Other users are not allowed to subscribe.

    If an orga list is not linked to an event, it behaves as an invitation
    only list for all users.

    * visible to: event users
    * additional admins: event
    * sortkey: event

Assembly Mailinglists
    Mailinglist that contain users participating on a given assembly. Other
    users are not allowed to subscibe.

    * visible to: assembly users
    * additional admins: assembly
    * sortkey: assembly

Assembly user Mailinglists
    Mailinglists for assembly users. Other users are not allowed to subscibe.

    * visible to: assembly users
    * additional admins: assembly
    * sortkey: assembly

    The following subtypes are supported:

    * Opt-in

General Mailinglists
    Mailinglists for any users.

    * visible to: all users
    * additional admins: None
    * sortkey: other

    The following subtypes are supported:

    * Opt-in

Semi-public Mailinglists
    Mailinglists that are Opt-in for CdE members, but have Moderated Opt-in
    for other users.

    * visible to: all users
    * additional admins: None
    * sortkey: other

CdElokal Mailinglists
    Semi-public mailinglists with a special sortkey.

    * visible to: all users
    * additional admins: cdelokal
    * sortkey: cdelokal
