Role Model
==========

Personas
--------

Each persona can have the following privileges:

* being a persona (in contrast to anonymous access)
* access to a specific realm (cde, event, ml, assembly)
* admin privileges in a realm (core, cde, event, ml, assembly)
* meta admin
* finance admin
* cdelokal admin
* membership
* searchability

Note that some of the combinations are not very useful and may thus be
untested (for example by default access to the cde realm is linked to access
to all other realms). Former members are those with cde realm but not
membership privileges.

These privileges control what actions the user may call and are determined
by the core.personas table. These are enforced throughout the python code
via the ``@access`` decorator.

Additionally there may be finer grained privileges which are encoded in
various tables which are checked locally in the relevant pieces of code. The
following additional privileges are

* orga of an event
* moderator of a mailinglist

Due to complex inter-realm dependencies, mailinglist privileges have some caveats
which are explained further at :doc:`Realm_Mailinglist_Privileges`.

.. todo:: Weiterführende Referenz auf Realm_Core_Personas

Droids
------

Each droid can have the following privileges:

* being a droid (in contrast to anonymous access)
* per droid identity privilege
* infrastructure toggle (making them exempt from lockdown)

More to droids at :doc:`API_Droids`.


Database
--------

In the database everything is mapped onto four tiers

* anonymous,
* persona,
* member,
* admin.

More to database at :doc:`Design_Database`.
