LDAP
====

Current state of getting LDAP with the SQL-backend to run. The major
complication is that all sources (see :ref:`sec-ldap-references`) work with
the old-style slapd.conf mechanism whereas newer ldap has switched to the
new-style cn=config mechanism.

First we install odbc::

    sudo apt-get install unixodbc odbc-postgresql

And configure it via /etc/odbc.ini

.. literalinclude:: ../../ldap/templates/odbc.tmpl

The ``Driver`` must be as specified in /etc/odbcinst.ini (which should be
prefilled by the Debian package). To check odbc functionality we use the
following command::

    isql cdb

We need some additional info inside the SQL database. The ldap specific
additions reside in cdedb/database/cdedb-ldap.sql.
All data which is prefilled here is static and needed for ldap to work.
We use sql query views to 'insert' data from other existent tables in the needed
format into the ldap tables.
Currently, there is only one table (``ldap.duas``) which is filled with test
specific sample data.

We now configure the SQL-backend for LDAP via a corresponding LDIF file (as
is necessary according to the cn=config mechanism). Current state of the
content of our sql-ldap.ldif

.. literalinclude:: ../../sql-ldap.ldif

To apply the LDIF configuration file we issue the following command::

    sudo ldapmodify -Y EXTERNAL -H ldapi:/// -f /cdedb2/sql-ldap.ldif

Now, one can apply the database schemas as usual by calling::

    make sample-data

If the database schema is modified, ldaps ``slapd`` service needs to be stopped
before and restarted afterwards. This is done in all relevant make targets
automatically.

We can retrieve the data from LDAP with the following command::

    sudo ldapsearch  -Y EXTERNAL -H ldapi:/// -b "dc=cde-ev,dc=de"

which lists the contents of our LDAP-directory backed by the SQL-DB.

An alternative to ``ldapsearch`` should be ``slapcat`` like the following::

    sudo slapcat -n 2

However this gives the barely helpful error ``slapcat: database doesn't
support necessary operations.``.
This [StackOverflow Comment[(https://serverfault.com/a/584609) suggest that
``slapcat`` is not compatible with the ``sql-backend``.

Development
-----------

To access the ldap in a local vm, the respective port needs to be mapped to
localhost. Add something similar to this to your vm setup::

    hostfwd=tcp:127.0.0.1:20389-:389

To view and query the ldap tree, ``Apache Directory Studio`` is a handsome tool.

Troubleshooting
---------------

To receive more information from LDAP in case anything goes wrong the log
level can be increased with the following::

    sudo ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
    dn: cn=config
    changetype: modify
    replace: olcLogLevel
    olcLogLevel: -1
    EOF

To access the error log of slapd, use::

    sudo journalctl -ru slapd

To check the entries of the ldap database tables, use the psql console::

    sudo -u cdb psql

To access the root DN, use::

    sudo ldapsearch -H ldap:// -x -D "cn=admin,dc=cde-ev,dc=de" -b "" "+"

To view the current content of the cn=config DIT, user::

    sudo ldapsearch -H ldapi:// -Y EXTERNAL -b "cn=config" -LLL -Q | less

Sanity test for ldapsearch (this should produce no errors and return some
results)::

    sudo ldapsearch  -Y EXTERNAL -H ldapi:/// -b "dc=cde-ev,dc=de"


To drop all LDAP SQL databases the following workaround seems necessary
(using an LDIF file with a delete instruction errors with ``ldap_delete:
Server is unwilling to perform (53)``)::

    make ldap-reset-sql

To reset the whole ldap stuff, a purged reinstall should be done::

    make ldap-reset

After reinstalling, a ldap admin passwort has to be specified.

.. _sec-ldap-references:

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
* ``man slapd-sql``
