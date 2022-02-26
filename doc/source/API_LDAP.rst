LDAP
====

We expose some (readonly) information about our users via LDAP.
This information is meant to be used by other CdE-brewed and third-party-tools
living in the CdE ecosystem to

- authenticate and
- authorize users

To achieve the latter, we heavily build upon ldap groups to determine the access
level of a given user.
For the sake of simplicity, the information provided by LDAP is read-only.
To modify user attributes or group membership, the CdEDB shall be used directly.


LDAP Tree
---------

Our LDAP Tree looks as follows::

    dc=cde-ev,dc=de
    ├── ou=duas
    │   ├── cn=test
    │   └── ...
    ├── ou=groups
    │   ├── ou=assembly-presiders
    │   │   ├── cn=1
    │   │   └── ...
    │   ├── ou=event-orgas
    │   │   ├── cn=1
    │   │   └── ...
    │   ├── ou=ml-moderators
    │   │   ├── cn=42@lists.cde-ev.de
    │   │   └── ...
    │   ├── ou=ml-subscribers
    │   │   ├── cn=42@lists.cde-ev.de
    │   │   └── ...
    │   └── ou=status
    │       ├── cn=is_active
    │       ├── cn=is_assembly_admin
    │       ├── cn=is_assembly_realm
    │       ├── cn=is_cde_admin
    │       ├── cn=is_cde_realm
    │       ├── cn=is_cdelokal_admin
    │       ├── cn=is_core_admin
    │       ├── cn=is_event_admin
    │       ├── cn=is_event_realm
    │       ├── cn=is_finance_admin
    │       ├── cn=is_member
    │       ├── cn=is_ml_admin
    │       ├── cn=is_ml_realm
    │       └── cn=is_searchable
    └── ou=users
        ├── uid=1
        └── ...


LDAP Entities
-------------

Groups
^^^^^^

A group represent a collection of users. They are used to represent some
attributes (status attributes like ``is_active``, mailinglist subscriptions etc)
of users in an LDAP-fashion.

Each group implements the ``groupOfUniqueNames`` objectclass and has the
following attributes:

- ``cn`` ID for events and assemblies; list address for mailinglists;
  some bools of ``core.personas``
- ``description`` follows the pattern "``title`` (``shortname``)" for events,
  assemblies and mailinglist.
- ``uniqueMember`` the DN of one group member

Users
^^^^^

An LDAP user represents an user account of the CdEDB. Each user implements the
``inetOrgPerson`` objectclass and has the following attributes:

- ``cn`` their full name: "``given_names`` ``family_name``"
- ``displayName`` the full name which should be used to address this user,
  constructed via the same logic used in the CdEDB, including a family name.
- ``givenName`` the first name of the user (CdEDBs ``given_names``).
- ``sn`` the last name of the user (CdEDBs ``family_name``).
- ``mail`` the users mail address. This may also be used as login username,
  since the CdEDB enforces uniqueness here.
- ``uid`` the CdEDB-ID without letters or checksum.
- ``userPassword`` the password this user has set in the CdEDB.
- ``memberOf`` listing all dns of the groups this user is a member of.

DirectoryUserAgents
^^^^^^^^^^^^^^^^^^^

To access the LDAP with a third-party tool, the tool needs to authenticate
itself against the LDAP.

Sadly, there are great differences: Some tools use a static user from within the
LDAP to retrieve their data, others use the credentials of the user they are
currently serving, some do a mixture of both.
In general, we advise to use the second method (use the user credentials) to
retrieve data from LDAP.

However, to grant compatibility, each tool which **requires** an own LDAP user
get an own entry inside ``ou=duas``. Sadly, there is no common specification
of duas with a common accepted objectclass.
Therefore, we (ab)use the ``person`` objectclass for them, containing the
following attributes:

- ``cn`` a name which must be unique for each dua
- ``userPassword`` the password they use to bind against LDAP


Security Restrictions
---------------------

The following restrictions were applied to protect the data inside the LDAP
against unprivileged access:

- Users may only access exactly their own data.
- Duas can access every user data, exept for their group memberships. Group
  access is only provided to some duas manually.
- Password hashes can not be retrieved from LDAP, only authentication inside
  LDAP is allowed.
