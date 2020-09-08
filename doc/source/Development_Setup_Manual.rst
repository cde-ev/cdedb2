Manual Setup
============

This describes the steps necessary to get the project running on a
machine.

.. note:: This is somewhat complicated and it is advised to use the virtual
    machine in most cases. Instructions for obtaining and using the image can be
    found at :doc:`Development_Setup`.

Below may be some Gentoo-specific bits, for
Debian-specific stuff look at the setup scripts in ``related/auto-build``.

Prerequisites
-------------

We need some dependencies:

* python (at least 3.6)
* PostgreSQL (at least 9.4, for jsonb)
* Apache (with mod_wsgi)
* git
* openldap
* texlive (incl. luatex; for generating pdf documents)

Further we depend on a number of python packages:

* passlib
* psycopg2 (at least 2.5.4, for jsonb support)
* werkzeug (at least 0.14, for same-site flag for setcookie)
* dateutil (only needed for dev script, namely analyze_timing.py)
* babel
* docutils
* jinja2
* markdown
* bleach
* pytz
* python-magic
* python-imaging-library (more specifically pillow)
* zxcvbn
* icu
* mailmanclient

At last there are some recommended dependencies:

* sphinx (for building the documentation)
* guzzle-sphinx-theme (a documentation theme)
* webtest (for tests, at least 2.0.17 for handling of multiple elements with the same name)
* lxml (the python module; used in the test suite)
* pgbouncer (otherwise database performance may be degraded)
* fail2ban (for preventing brute-force attacks)
* pylint (for code analysis)
* requests (the python module; used in some scripts)

Checkout the repository
-----------------------

Use git to clone the code::

  git clone ssh://gitea@tracker.cde-ev.de:20009/cdedb/cdedb2.git

For this to work you need to create an account on the tracker website which
has then to be granted access to the cdedb repository (send a mail to the db
list ``cdedb@lists.cde-ev.de``). All commands below assume, that you are in
the root directory of the repository. Now you can build the documentation by
issuing::

  make doc

Prepare environment
-------------------

Now we set up all auxiliary stuff. We assume, that postgres is configured
for peer authentication (i.e. the system user xy has access to the postgres
user xy). First execute as user with enough permissions (that is the ability
to run ``sudo -u postgres ...`` and ``sudo -u cdb ...``) and with running
postgres::

  make sql

This will create the database users and tables. Now configure pgbouncer in
``pgbouncer.ini`` (in ``/etc``) with the following::

  [databases]
  cdb =
  cdb_test =

  [pgbouncer]
  logfile = /var/log/postgresql/pgbouncer.log
  pidfile = /var/run/postgresql/pgbouncer.pid
  unix_socket_dir = /run/postgresql
  listen_addr = 127.0.0.1
  listen_port = 6432
  auth_type = md5
  auth_file = /etc/pgbouncer_users.txt
  pool_mode = session
  server_reset_query = DISCARD ALL
  max_client_conn = 100
  default_pool_size = 20

Additionally place copy file ``related/pgbouncer_users.txt`` to
``/etc/pgbouncer_users.txt`` for authentication (otherwise pgbouncer will
refuse connections)::

  cp related/pgbouncer_users.txt /etc
  chown pgbouncer:root /etc/pgbouncer_users.txt
  chmod 600 /etc/pgbouncer_users.txt

This file may be regenerated with the ``mkauth.py`` tool from the pgbouncer
tar-ball.

Now we set up the Apache server, first add the following lines to
``/etc/apache2/httpd.conf``::

  LoadModule wsgi_module modules/mod_wsgi.so
  ServerName localhost

and then insert the following close to the end of
``/etc/apache2/vhosts.d/00_default_ssl_vhost.conf``::

  WSGIDaemonProcess cdedb processes=4 threads=4
  WSGIScriptAlias /db /path/to/repo/wsgi/cdedb.wsgi

  <Directory /path/to/repo/wsgi>
  Require all granted
  </Directory>

  Alias /static /path/to/repo/static
  <Directory /path/to/repo/static/static>
  Require all granted
  </Directory>

note, that this is syntax for apache-2.4 (which differs from apache-2.2).

Finally we need to create the directory for uploaded data (where
``www-data`` is the user running Apache)::

  mkdir /var/lib/cdedb/
  chown www-data:www-data /var/lib/cdedb/

.. note:: For optimal experience you should run ``make storage-test`` and
  copy the resulting uploaded data from ``/tmp/cdedb-store`` to
  ``/var/lib/cdedb`` and make it owned by the apache user.

Configure the application
-------------------------

The details can be found in :py:mod:`cdedb.config`. The global configuration
can be done in ``cdedb/localconfig.py`` (a sample for this is provided at
``cdedb/localconfig.py.sample``, for development instances you are strongly
encouraged to copy this file to ``cdedb/localconfig.py``). The configuration
for the application resides in ``/etc/cdedb-application-config.py``.

Running it
----------

Last step before startup is compiling the GNU gettext .mo files for i18n::

  make i18n-compile

Now, check if postgres, pgbouncer and slapd are running. Optionally you
can run the test suite first to see whether everything is ready::

  make check

Now start the apache and access ``https://localhost/db/`` with a
browser.

Refreshing the running instance
-------------------------------

Changes to the code can be propagate as follows to the current instance. For
templates no action is necessary. For the python code updating the mtime of
the wsgi file resets the apache workers::

  sudo systemctl restart apache2

You can use the make target reload to re-compile i18n and trigger the worker
reload::

  make reload

For the database you should restart pgbouncer (which probably has some open
connections left) before doing a ``make sample-data``.
