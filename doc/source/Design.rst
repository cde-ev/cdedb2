General Design
==============

.. toctree::
   :maxdepth: 1
   :hidden:

   Design_Roles
   Design_WSGI
   Design_Datamodel
   Design_Database
   Design_Backend
   Design_Frontend
   Design_Template
   Design_UX_Conventions
   Design_Environment_Setup
   Design_Configuration
   Design_Logging
   Design_Validation
   Design_Internationalization
   Design_Testing

This WSGI-application has three main parts: frontend (python), backend
(python) and database (SQL). The communication between frontend and backend
is designed as if mediated by an RPC mechanism (for example
:py:mod:`Pyro4`) and between backend and database we use
:py:mod:`psycopg2`. Everything is split into several :doc:`realms <Realm>`
to separate orthogonal problems from each other like member register from
event organization. In the python code this is achieved by different classes
for each realm and in the SQL code we have different schemas for each realm.

The production instance on the CdE server is pretty similar to the
:doc:`VM image <Development_Environment_Setup_VM>` provided by the
auto-build. So take a look there to see how everything fits together.

The python code is state-less and thus easily parallelizable. This is
exploited in the frontend (where Apache does multithreading). All state is
kept in the database. For accountability we always keep a user's latest session
and a record of all sessions of the last 30 days. We only allow five active
sessions per account. These limits can be adjusted in the :doc:`Design_Configuration`.

The basic account is referred to as :doc:`persona <Design_Roles>`. Each
persona has access to a subset of the realms. Some attributes of an account
are only meaningful in some realms.

Additionally there are API access accounts which are referred to as
:doc:`API_Droids`. These do not have an associated session but instead authenticate
with a token.
