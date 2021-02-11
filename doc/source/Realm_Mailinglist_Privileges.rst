Mailinglist Privileges
======================

The ml realm has some additional privilege entities due to the dependence on
and interaction with other realms. Besides the canonical roles of user and
admin, which are explained in more detail in :doc:`Design_Roles`, there
exists the moderator role that allows management of one
mailinglist akin to orga and presider.

From these we now derive two additional privilege levels:

Relevant Admins
    This is intended to allow other realm admins to manage
    mailinglists associated with their realm. As the ml realm is lowest in
    the implicit hierarchy of realms, every admin has access here.

    For example an event admin is a relevant admin for mailinglists
    associated to an event, like orga and partcipant mailinglists. A full list
    of relevant admins for each mailinglist type is given at
    :doc:`Realm_Mailinglist_Types`.

    This grants all privileges with regard to a specific mailinglist. ml
    admins are relevant admins for all mailinglists.

Privileged Moderators
    We start with the problem description. Due to the
    fact that the mailinglist machinery consumes data from other realms, the
    actor causing an action sometimes needs additional access rights in these
    other realms. A moderator can be privileged in certain constellations by
    having external (i.e. not ml) access rights.

    Main case is the manipulation of implicit mailinglists where the
    generation of the subscriber list needs additional access. For example,
    for privacy reasons, event mailinglists need orga-level access to generate
    their subscriber list. But a user could be promoted to be moderator of a
    specific mailinglist associated to the event without being orga. Currently
    the limitations of our architecture make it impossible for this
    user to change the subscriber list. This also affects manipulating
    individual subscriber states as they are validated against external
    information (like the participation status in an event) to determine if
    this subsriber is privileged to access that list. See also
    :doc:`Realm_Mailinglist_Management` for more information.

    However, unprivileged moderators can still moderate their mailinglists and
    modify its whitelist and moderators, as well as most of its configuration.

    Currently, we have the following cases:

    * **event associated lists**: needs to be orga of the event or event admin
    * **assembly associated lists**: needs to be participant of the assembly,
      member or assembly admin
