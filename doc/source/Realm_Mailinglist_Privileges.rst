Mailinglist Privileges
======================

The ml realm has some additional privilege entities due to the dependence on
and interaction with other realms. Besides the canonical roles of user and
admin, there exists the moderator role that allows management of one
mailinglist akin to orga and presider.

From these we now derive two additional privilege levels:

- relevant admins: This is intended to allow other realm admins which are
  higher in the realm hierachy to manage mailinglists associated with their
  realm (remember that e.g. event realm implies ml realm).

  For example an event admin is a relevant admin for mailinglists
  associated to an event like the orga mailinglist.

  This grants all privileges with regard to a specific mailinglist and ml
  admins are relevant admins for all mailinglists.

- privileged moderators: We start with the problem description. Due to the
  fact that the mailinglist machinery consumes data from other realms the
  actor causing an action sometimes needs additional access rights in these
  other realms. A moderator can be privileged in certain constellations by
  having external (i.e. not ml) access rights.

  Main example is the manipulation of implicit mailinglists where the
  generation of the subscriber list needs additional access. For example
  event associated mailinglists need orga-level access to generate their
  subscriber list. But a participant could be promoted to be moderator of a
  specific mailinglist associated to the event without being orga. Currently
  the limitations of our architecture make it impossible for this
  participant to change the subscriber list.



.. todo:: Orgas have not automatically moderators right for mailinglists
   associated to their event? Is this correct?

.. todo:: Mention Interaction policies? These define also access rights.
