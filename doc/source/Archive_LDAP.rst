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
additions to cdedb/database/cdedb-tables.sql (untested)::

    ---
    --- ldap stuff (in public schema)
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

    -- helper (TODO cleanup)

    DROP TABLE IF EXISTS ldap_organizations;
    CREATE TABLE ldap_organizations (
           id serial PRIMARY KEY,
           moniker varchar NOT NULL
    );
    GRANT ALL ON ldap_organizations TO cdb_admin;

We now configure the SQL-backend for LDAP via a corresponding LDIF file (as
is necessary according to the cn=config mechanism). Current state of the
content of our sql-ldap.ldif::

    # load sql-backend module
    dn: cn=module{0},cn=config
    changetype: modify
    add: olcModuleLoad
    olcModuleLoad: back_sql

    # backend definition
    dn: olcBackend={1}sql,cn=config
    changetype: add
    objectClass: olcBackendConfig
    olcBackend: {1}sql

    # database definitions
    dn: olcDatabase=sql,cn=config
    changetype: add
    objectClass: olcDatabaseConfig
    objectClass: olcSqlConfig
    olcDatabase: sql
    olcSuffix: dc=cde-ev,dc=de
    olcRootDN: cn=admin,dc=cdedb,dc=virtual
    olcRootPW: secret
    # remaining configuration options from slapd.conf without a cn=config equivalent I did find
    #
    # dbname		PostgreSQL
    # dbuser		postgres
    # dbpasswd	postgres
    # insentry_stmt	"insert into ldap_entries (id,dn,oc_map_id,parent,keyval) values ((select max(id)+1 from ldap_entries),?,?,?,?)"
    # upper_func	"upper"
    # strcast_func	"text"
    # concat_pattern	"?||?"
    # has_ldapinfo_dn_ru	no

To apply the LDIF configuration file we issue the following command::

    ldapmodify -Y EXTERNAL -H ldapi:/// -f /cdedb2/sql-ldap.ldif

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

.. _sec-ldap-references:

References
----------

* https://github.com/peppelinux/django-slapd-sql
* https://linux.die.net/man/5/slapd-sql
* http://www.flatmtn.com/article/setting-ldap-back-sql.html
* https://www.openldap.org/faq/data/cache/978.html
* https://www.digitalocean.com/community/tutorials/how-to-use-ldif-files-to-make-changes-to-an-openldap-system
* https://serverfault.com/questions/725887/how-do-i-add-an-openldap-contrib-module-with-cn-config-layout-to-ubuntu
