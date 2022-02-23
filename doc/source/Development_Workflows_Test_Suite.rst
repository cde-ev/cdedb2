Test Suite
==========

This page describes the technical details reagrding the test suite.
To get a high-level overview of our testing philosophy,
take a look at :doc:`Design_Testing` instead.

.. _sample-data:

Sample Data
-----------

The sample data lives in ``tests/ancillary_files/sample_data.json``. You can fill
the database with the sample data by calling ``make sample-data`` in the directory
``/cdedb2``. This will create a ``sample_data.sql`` file, drop the current
database state and at last repopulate the database with the sample data. Now,
you can use the DB as you would use it online, log in with the users described
below.

If you want to extend the sample data, you may simply change the ``sample_data.json``
file. Be aware that changing existing and sometimes also adding new sample data
can have side effects on some tests, so you should run the whole test suite
afterwards to check that no test breaks.

As an alternative to fill the ``sample_data.json`` file manually, we provide
a script to dump the current database state into a JSON file. This can be
very helpfull if you want to add a huge amount of new sample data, which
sometimes comes with dependencies between different SQL-tables and can be quite
frustrating to be done manually. We also provide a make target for this purpose,
simply call ``make sample-data-dump`` inside ``/cdedb2``.

Users
^^^^^

There is a default data set for the development it contains some users
(according to the table below).

======================= ========= ========== ================================================
User                    ID        Password   Notes
======================= ========= ========== ================================================
anton@example.cde       DB-1-9    secret     admin with all privileges
berta@example.cde       DB-2-7    secret     canonical example member, moderator of lists
charly@example.cde      DB-3-5    secret     member, but not searchable
daniel@example.cde      DB-4-3    secret     former member (but not disabled)
emilia@example.cde      DB-5-1    secret     event user
ferdinand@example.cde   DB-6-X    secret     admin in all realms, but not globally
garcia@example.cde      DB-7-8    secret     orga of an event
hades                   DB-8-6    secret     archived member
inga@example.cde        DB-9-4    secret     minor member and cdelokal admin
janis@example.cde       DB-10-8   secret     mailinglist user
kalif@example.cde       DB-11-6   secret     assembly user
lisa                    DB-12-4   secret     member with whacked data
martin@example.cde      DB-13-2   secret     second meta admin to confirm privilege changes
nina@example.cde        DB 14-0   secret     mailinglist admin and event user
olaf@example.cde        DB-15-9   secret     a disabled user (and member and CdE admin)
paulchen@axample.cde    DB-16-7   secret     core admin and cde user
quintus@example.cde     DB-17-5   secret     cde admin and not searchable member
rowena@example.cde      DB-18-3   secret     assembly and event but not cde user
vera@example.cde        DB-22-1   secret     former member, corresponding to Verwaltungsteam
werner@example.cde      DB-23-X   secret     former member, corresponding to Versammlungsleitung (presider)
annika@example.cde      DB-27-2   secret     former member, corresponding to Akademieteam
farin@example.cde       DB-32-9   secret     former member, corresponding to Finanzvorstand
katarina@example.cde    DB-37-X   secret     auditor (Kassenprüfer)
viktor@example.cde      DB-48-5   secret     assembly admin
akira@example.cde       DB-100-7  secret     equal to Anton - to test sorting
======================= ========= ========== ================================================


Secrets
^^^^^^^

Every attendee at an assembly got a personal secret to verify their votes afterwards.
If an assembly is concluded, all secrets are deleted from the database.
Here, we kept the secrets of those users of the sample data.

======== ================== ==========
Assembly User               Secret
======== ================== ==========
2        Rowena             asdgeargsd
======== ================== ==========

LDAP
^^^^

We expose some information about our users via ldap. This contains some general
information like name and mail address, and group privileges of the user in particular.
The data is directly retrieved from the sql tables of the CdEDB and therefore
needs no syncing.

To locally test our ldap integration, we add some ldap agents to the CdEDB
sample data. They can be used to connect to and retrieve data from the ldap system.
To test the permissions of the live duas properly, we also add them in our
sample-data.

============= ============== =====================================
CN            Password       Notes
============= ============== =====================================
admin         secret         olcRootDN
apache        secret
cloud         secret
cyberaka      secret
dokuwiki      secret
test          secret         does not exist in live instance
============= ============== =====================================

.. _running-tests:

Running tests
-------------

To allow simultaneous development and testing on the same machine without
interference between the development and test process, we strictly separate the
stateful parts (in particular sql database, file storage directory and logs) of development
and test instance.

.. note::
    The majority of our tests do not need the file storage. Since the setup is costly, every test
    who needs it has to get the ``@storage`` decorator from ``tests.common`` for the
    storage directory to be created. After this test has finished, the directory will
    be deleted.

To achieve this, we use the same mechanisms as for development (or production)
environments. This even allows running multiple test instances in parallel!
Each instance of the test suite gains its own configuration file in ``tests/config/``,
which extends the existent default configuration from ``cdedb/config.py``.
This configuration may (in contrast to ``cdedb/localconfig.py``, which is not
taken into account for test instances) include additional keys which are not
present in the default configuration, if they are needed during the test process.
The setup process uses the Makefile and overwrites the default values of the
make variables with the values specified in the config file.

To prepare and run the testsuite, we provide a central script: ``bin/check.py``
You can pass some pattern to run only specific tests, or use the command line
arguments to run only specific parts of the test suite. For detailed information
run::

    bin/check.py --help

In the following, we will explain the pattern matching mechanism and shortly
introduce each part of the test suite.

Pattern matching
^^^^^^^^^^^^^^^^

You can pass an arbitrary amount of patterns to ``check.py``, which will then get matched
against the fully qualified test method name.
Such a full specifier looks like
``tests.frontend_tests.event.TestEventFrontend.test_create_event``, but you can also pass
an unambiguous part of it, like e.g. just ``create_eve``, for convenience.
These parts of course can also specify complete test files, like ``backend_tests.core``,
where unambiguous parts suffer too.

Pattern matching is performed by unittest, which uses ``fnmatch.fnmatchcase``
internally [#fnmatch]_.
If a pattern without an asterisk is passed it will be wrapped with one on both ends.

Application tests
^^^^^^^^^^^^^^^^^

This is the main part of our test suite, providing tests for the CdEDB WSGI application,
including the frontend tests (``tests/frontend_tests``), backend tests (``tests/backend_tests``),
database tests and tests for the gluing parts (like validation, all in ``tests/other_tests``).

To decrease runtime, we split this tests in our CI in three parts, using the
configuration present in ``tests/config/test_1.py`` to ``tests/config/test_4.py``.
To avoid test clashes when different parts use the same configuration, we use
a simple locking mechanism with lockfiles inside ``/tmp`` and let the test script
choose a free test configuration automatically.

LDAP tests
^^^^^^^^^^

This includes all tests of our LDAP interface. This is a bit more tricky, since
it additionally involves the ldap server, which is not able to serve the same
ldap tree for different databases (the development and the test instance)
simultaneously. So, we decided to let our ldap server serve the test database
only during test runs. This avoids resetting the development instance each
time the ldap tests are run, but also prevents accessing the development ldap
tree during test runs. This may be fixed in the future.

Inside the tests, we mock a ldap client querying our ldap server and check if
the results satisfy our expectations. The configuration for this part of the
testsuite is present in ``tests/config/test_ldap.py``.

.. _xss-check:

XSS tests
^^^^^^^^^

To prevent XSS mitigation, we test if our code performs proper HTML escaping
on user input. For this, we use the ``bin/escape_fuzzing.py`` script to inject
a payload containing HTML tags inside the database and check if they are
escaped properly during serving.

The configuration for this part of the testsuite is present in ``tests/config/test_xss.py``.

.. _coverage:

Code coverage
^^^^^^^^^^^^^

The coverage html reports for easier inspection are accessible on the local dev
instance via Apache at `localhost:8443/coverage <https://localhost:8443/coverage>`_ for
docker and `localhost:20443/coverage <https://localhost:20443/coverage>`_ for the VM.


.. [#fnmatch] https://docs.python.org/3/library/unittest.html#unittest.TestLoader.testNamePatterns
