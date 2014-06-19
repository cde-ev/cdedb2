Getting Started
===============

Prerequisites
-------------

We need some dependencies:

* python (at least 3.4)
* PostgreSQL
* Apache (with mod_wsgi)
* git
* openldap

Further we depend on a number of python packages:

* passlib
* psycopg2
* pyro4 (which depends on serpent)
* werkzeug
* dateutil
* jinja2
* python-ldap (support for py3 is currently unreleased)

At last there are some recommended dependencies:

* sphinx (for building the documentation)
* webtest (for tests)
* pgbouncer (otherwise database performance may be degraded)

Here are some oneliners for the lazy::

  # Gentoo
  emerge -avt >=dev-lang/python-3.4.0 dev-db/postgresql-server www-servers/apache dev-vcs/git net-nds/openldap dev-python/passlib dev-python/psycopg:2 dev-python/pyro:4 dev-python/werkzeug dev-python/python-dateutil dev-python/jinja =dev-python/python-ldap-9999 dev-python/sphinx dev-python/webtest dev-db/pgbouncer

Checkout the repository
-----------------------

Use git to clone the code::

  git clone ssh://gitolite@rcs.cde-ev.de:20008/cdedb2

For this to work you need to send an ssh public key to the administrators
(``admin@lists.cde-ev.de``) first, to be authorized for access to the
repository. Now you can build the documentation by issuing::

  make doc

If you are reading the excerpt version (``INSTALL.html``) you can now switch
to the real document.

Prepare environment
-------------------

Now we set up all auxillary stuff. First execute as user with enough
permissions and with running postgres::

  make sql

This will create the database users and tables. Now configure pgbouncer in
``/etc/pgbouncer.ini`` with the following::

  [databases]
  cdb =
  cdb_test =

  [pgbouncer]
  listen_addr = 127.0.0.1
  listen_port = 6432
  auth_type = md5
  auth_file = /etc/pgbouncer_users.txt
  pool_mode = session
  max_client_conn = 100
  default_pool_size = 20

Additionally place the file ``related/pgbouncer_users.txt`` into ``/etc``
for authentication (otherwise pgbouncer will refuse connections)::

  cp related/pgbouncer_users.txt /etc
  chown pgbouncer:root /etc/pgbouncer_users.txt
  chmod 600 /etc/pgbouncer_users.txt

This file may be regenerated with the ``mkauth.py`` tool from the pgbouncer
tar-ball.

Next up is LDAP. Edit the ``/etc/openldap/slapd.conf`` and enter the
following values (we will use a basic setup that omits fancy ``cn=config``
features)::

  include         /etc/openldap/schema/core.schema
  include         /etc/openldap/schema/cosine.schema
  include         /etc/openldap/schema/inetorgperson.schema
  include         /etc/openldap/schema/cdepersona.schema

  pidfile         /var/run/openldap/slapd.pid
  argsfile        /var/run/openldap/slapd.args

  database        hdb
  suffix          "dc=cde-ev,dc=de"
  rootdn          "cn=root,dc=cde-ev,dc=de"
  rootpw          s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0
  directory       /var/lib/openldap-data
  index           objectClass     eq
  index           cn      pres,sub,eq
  index           sn      pres,sub,eq
  index           uid     pres,sub,eq
  index           displayName     pres,sub,eq

You need to place a symlink to the custom cdepersona schema::

  ln -s /path/to/repo/cdedb/database/cdepersona.schema /etc/openldap/schema/cdepersona.schema

Now start the slapd daemon and issue the following in the repo::

  make ldap

Now we set up the Apache server, first with ``/etc/apache2/httpd.conf``::

  LoadModule wsgi_module modules/mod_wsgi.so
  ServerName localhost

and then with ``/etc/apache2/vhosts.d/00_default_ssl_vhost.conf``::

  WSGIDaemonProcess cdedb processes=4 threads=4
  WSGIScriptAlias /db /path/to/repo/wsgi/cdedb.wsgi

  <Directory /path/to/repo/wsgi>
  Require all granted
  </Directory>

  Alias /static /path/to/repo/static
  <Directory /path/to/repo/static/static>
  Require all granted
  </Directory>

note, that this is syntax for apache-2.4 (this differs from apache-2.2).

Configure the application
-------------------------

The details can be found in :py:mod:`cdedb.config`. The global configuration
can be done in ``cdedb/localconfig.py`` (a sample for this is provided at
``cdedb/localconfig.py.sample``, for development instances you are strongly
encouraged to copy this to ``cdedb/localconfig.py``). The configuration for
the frontend resides in ``/etc/cdedb-frontend-config.py``. The path to the
backend configuration is passed on the command line (if you use the make
recipes, then via the variable ``CONFIGPATH``).

Running it
----------

First start a ``pyro`` nameserver with::

  make pyro-nameserver

Second create the directory ``/run/cdedb`` (for this you possibly need
elevated privileges). This has to be writable by the user running the
backends and readable by the user running the frontend (here go the sockets
by default)::

  mkdir /run/cdedb
  chown <user>:<user> /run/cdedb

Check if apache, postgres, pgbouncer and slapd are running. Optionally you
can run the test suite first to see whether everything is ready::

  make check

Then spin up the backends (exemplary here for the core backend)::

  make run-core

Now start the apache and access ``https://localhost/db/`` with a
browser. Finally you can shutdown the backends with::

  make quit-all
