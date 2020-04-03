Design
======

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

Additionally there are API access accounts which are referred to as
droids. These do not have an associated session but instead authenticate
with a token send via header.
