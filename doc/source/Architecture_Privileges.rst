.. _privileges:

Privileges
==========

Each persona can have the following privileges:

* access to a specific realm (cde, event, ml, assembly)
* admin privileges in a realm (core, cde, event, ml, assembly)
* meta admin
* finance admin
* membership
* searchability

Note that some of the combinations are not very useful and may thus be
untested (for example by default access to the cde realm is linked to access
to all other realms). Former members are those with cde realm but not
membership privileges.

Each droid can have the following privileges:

* per droid identity privilege
* infrastructure toggle

In the database they are mapped onto four tiers

* anonymous,
* persona,
* member,
* admin.

These privileges controle what actions the user may call and are determined
by the core.personas table. These are enforced throughout the python code
via the ``@access`` decorator.

Additionally there may be finer grained privileges which are encoded in
various tables which are checked locally in the relevant pieces of code. The
following additional privileges are there.

* orga of an event
* moderator of a mailing list
