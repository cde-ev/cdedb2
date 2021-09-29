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
    ├── ou=dua
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


LDAP Attributes
---------------

Each tool accessing the ldap server has an own ``ou=dsa`` entry to authenticate
against LDAP.
Each **dsa** (DirectorySystemAgent) has the following attributes:

- ``cn`` a name which must be unique for each dsa
- ``userPassword`` the password they use to bind against LDAP

Each **group** has the following attributes:

- ``cn`` ID for events and assemblies; list address for mailinglists;
  some bools of ``core.personas``
- ``description`` follows the pattern "``title`` (``shortname``)" for events,
  assemblies and mailinglist.
- ``uniqueMember`` the DN of one group member

Each **user** has the following attributes:

- ``cn`` their full name: "``given_names`` ``family_name``"
- ``displayName`` the full name which should be used to address this user.
- ``givenName`` the first name of the user.
- ``mail`` the users mail address. This may also be used as login username,
  since the CdEDB enforces uniqueness here.
- ``uid`` the CdEDB-ID.
- ``userPassword`` the password this user has set in the CdEDB.
