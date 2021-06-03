LDAP
====

Current state of getting LDAP with the SQL-backend to run. The major
complication is that all sources (see :ref:`sec-ldap-references`) work with
the old-style slapd.conf mechanism whereas newer ldap has switched to the
new-style cn=config mechanism.

First we install odbc::

    apt-get install unixodbc odbc-postgresql

And configure it via /etc/odbc.ini::

    [cdb]
    Description         = cdb connector for OpenLDAP's back-sql
    Driver              = PostgreSQL Unicode
    Trace               = No
    Database            = cdb
    Servername          = localhost
    UserName            = cdb_admin
    Password            = 9876543210abcdefghijklmnopqrst
    Port                = 5432
    ReadOnly            = No
    RowVersioning       = No
    ShowSystemTables    = No
    ShowOidColumn       = No
    FakeOidIndex        = No
    ConnSettings        =

The ``Driver`` must be as specified in /etc/odbcinst.ini (which should be
prefilled by the Debian package). To check odbc functionality we use the
following command::

    isql cdb

We need some additional info inside the SQL database. Here the necessary
additions to cdedb/database/cdedb-tables.sql::

    ---
    --- ldap stuff (in public schema)
    --- this is taken with minimal modifications from
    --- servers/slapd/back-sql/rdbms_depend/pgsql/backsql_create.sql
    --- in the openldap sources
    ---

    DROP TABLE IF EXISTS ldap_oc_mappings;
    CREATE TABLE ldap_oc_mappings (
           id bigserial PRIMARY KEY,
           name varchar(64) NOT NULL,
           keytbl varchar(64) NOT NULL,
           keycol varchar(64) NOT NULL,
           create_proc varchar(255),
           delete_proc varchar(255),
           expect_return int NOT NULL
    );
    GRANT ALL ON ldap_oc_mappings TO cdb_admin;

    DROP TABLE IF EXISTS ldap_attr_mappings;
    CREATE TABLE ldap_attr_mappings (
           id bigserial PRIMARY KEY,
           oc_map_id integer NOT NULL REFERENCES ldap_oc_mappings(id),
           name varchar(255) NOT NULL,
           sel_expr varchar(255) NOT NULL,
           sel_expr_u varchar(255),
           from_tbls varchar(255) NOT NULL,
           join_where varchar(255),
           add_proc varchar(255),
           delete_proc varchar(255),
           param_order int NOT NULL,
           expect_return int NOT NULL
    );
    GRANT ALL ON ldap_attr_mappings TO cdb_admin;

    DROP TABLE IF EXISTS ldap_entries;
    CREATE TABLE ldap_entries (
           id bigserial PRIMARY KEY,
           dn varchar(255) NOT NULL,
           oc_map_id integer NOT NULL REFERENCES ldap_oc_mappings(id),
           parent int NOT NULL,
           keyval int NOT NULL
    );
    CREATE UNIQUE INDEX idx_ldap_entries_oc_map_id_keyval ON ldap_entries(oc_map_id, keyval);
    CREATE UNIQUE INDEX idx_ldap_entries_dn ON ldap_entries(dn);
    GRANT ALL ON ldap_entries TO cdb_admin;

    DROP TABLE IF EXISTS ldap_entry_objclasses;
    CREATE TABLE ldap_entry_objclasses (
           entry_id integer NOT NULL REFERENCES ldap_entries(id),
           oc_name varchar(64)
    );
    GRANT ALL ON ldap_entry_objclasses TO cdb_admin;

    -- Helper table to make relations work (this will probably be replaced)

    DROP TABLE IF EXISTS ldap_organizations;
    CREATE TABLE ldap_organizations (
           id serial PRIMARY KEY,
           moniker varchar NOT NULL
    );
    GRANT ALL ON ldap_organizations TO cdb_admin;

We now configure the SQL-backend for LDAP via a corresponding LDIF file (as
is necessary according to the cn=config mechanism). Current state of the
content of our sql-ldap.ldif

.. literalinclude:: ../../sql-ldap.ldif

To apply the LDIF configuration file we issue the following command::

    ldapmodify -Y EXTERNAL -H ldapi:/// -f /cdedb2/sql-ldap.ldif

To access the root DN, use::

    ldapsearch -H ldap:// -x -D "cn=admin,dc=cdedb,dc=virtual" -w sicher -s base -b "" "+"

To view the current content of the cn=config DIT, user::

    sudo ldapsearch -H ldapi:// -Y EXTERNAL -b "cn=config" -LLL -Q | less

Now we insert some sample data to test the LDAP-SQL integration (here in a
repsesentation as Python dict as used in ``bin/create_sample_data_sql.py``)::

    {
        'ldap_organizations': [
            {
                'id': 1,
                'moniker': 'CdE',
            },
        ],
        'ldap_oc_mappings': [
            {
                'id': 1,
                'name': 'inetOrgPerson',
                'keytbl': 'core.personas',
                'keycol': 'id',
                'create_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'expect_return': 0,
            },
            {
                'id': 2,
                'name': 'organization',
                'keytbl': 'ldap_organizations',
                'keycol': 'id',
                'create_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'expect_return': 0,
            },
        ],
        'ldap_attr_mappings': [
            {
                'id': 1,
                'oc_map_id': 1,
                'name': 'cn',
                'sel_expr': 'personas.username',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 2,
                'oc_map_id': 1,
                'name': 'givenName',
                'sel_expr': 'personas.given_names',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': 'UPDATE core.personas SET given_names=? WHERE username=?',
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 3,
                'oc_map_id': 1,
                'name': 'sn',
                'sel_expr': 'personas.family_name',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': 'UPDATE core.personas SET family_name=? WHERE username=?',
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 4,
                'oc_map_id': 1,
                'name': 'userPassword',
                'sel_expr': 'personas.password_hash',
                'from_tbls': 'core.personas',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
            {
                'id': 5,
                'oc_map_id': 2,
                'name': 'o',
                'sel_expr': 'ldap_organizations.moniker',
                'from_tbls': 'ldap_organizations',
                'join_where': None,
                'add_proc': "SELECT 'TODO'",
                'delete_proc': "SELECT 'TODO'",
                'param_order': 3,
                'expect_return': 0,
            },
        ],
        'ldap_entries': [
            {
                'id': 1,
                'dn': 'dc=cde-ev,dc=de',
                'oc_map_id': 2,
                'parent': 0,
                'keyval': 1,
            },
            {
                'id': 2,
                'dn': 'cn=anton@example.cde,dc=cde-ev,dc=de',
                'oc_map_id': 1,
                'parent': 1,
                'keyval': 1,
            },
        ],
        'ldap_entry_objclasses': [
            {
                'entry_id': 1,
                'oc_name': 'dcObject',
            },
        ],
    }

Now we should be able to retrieve the data from LDAP with the following command::

    slapcat -n 2

However this gives the barely helpful error ``slapcat: database doesn't
support necessary operations.`` and the debugging invokation ``slapcat -n
2 -d -1`` also does not reveal more (besides that most things seem to have
worked).

Troubleshooting
---------------

To receive more information from LDAP in case anything goes wrong the log
level can be increased with the following::

ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=config
changetype: modify
replace: olcLogLevel
olcLogLevel: -1
EOF

To drop all LDAP SQL databases the following workaround seems necessary
(using an LDIF file with a delete instruction errors with ``ldap_delete:
Server is unwilling to perform (53)``)::

    systemctl stop slapd.service
    rm /etc/ldap/slapd.d/cn\=config/*Database*sql*
    systemctl start slapd.service

To reset the whole ldap stuff, a purged reinstall should be done::

    apt remove --purge slapd
    apt install slapd

After reinstalling, a ldap admin passwort has to be specified.
.. _sec-ldap-references:

-----

Bind to rootDN with ldapsearch::

    ldapsearch -H ldap:// -x -D "cn=admin,dc=cdedb,dc=virtual" -W


References
----------

* https://github.com/peppelinux/django-slapd-sql
* https://linux.die.net/man/5/slapd-sql
* http://www.flatmtn.com/article/setting-ldap-back-sql.html
* https://www.openldap.org/faq/data/cache/978.html
* https://www.digitalocean.com/community/tutorials/how-to-use-ldif-files-to-make-changes-to-an-openldap-system
* https://serverfault.com/questions/725887/how-do-i-add-an-openldap-contrib-module-with-cn-config-layout-to-ubuntu
* http://www.zytrax.com/books/ldap/ch6/slapd-config.html
* https://www.digitalocean.com/community/tutorials/how-to-configure-openldap-and-perform-administrative-ldap-tasks
* https://stackoverflow.com/questions/30898397/creating-second-database-domain-in-openldap
