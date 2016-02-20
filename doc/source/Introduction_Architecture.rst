Architecture
============

Design
------

This WSGI-application has three main parts: frontend (python), backend
(python) and database (SQL). The communication between frontend and backend
is designed as if mediated by an RPC mechanism (for example
:py:mod:`Pyro4`) and between backend and database we use
:py:mod:`psycopg2`. Everything is split into several realms (see below)
to separate orthogonal problems from each other like member register from
event organization. In the python code this is achieved by different classes
for each realm and in the SQL code we have different schemas for each realm.

The python code is state-less and thus easily parallelizable. This is
exploited in the frontend (where Apache does multithreading). All state is
kept in the database. For accountability we keep a record of all sessions
and only allow one active session per user or per IP.

The basic account is referred to as persona. Each persona has access to a
subset of the realms. Some attributes of an account are only meaningful in
some realms.

Realms
------

The realms group functionality into semantic units. There are four major
realms which have frontend, backend.

* cde -- CdE specific section
* event -- events like academies
* ml -- mailing lists
* assembly -- annual CdE assemblies

Then there are some more specialised realms.

* core -- basic infrastructure, servicing all realms
* session -- backend only, used for resolving session keys stored in cookies

.. _privileges:

Privileges
----------

Each persona can have the following privileges:

* access to a specific realm (cde, event, ml, assembly)
* admin privileges in a realm (core, cde, event, ml, assembly)
* super admin
* membership
* searchability

Note that some of the combinations are not very useful and my thus be
untested (for example by default access to the cde realm is linked to access
to all other realms). Former members are those with cde realm but not
membership privileges.

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
