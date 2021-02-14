Test Suite
==========

.. todo:: Explanation of our testing principles, sample data, special test functions etc

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


Running test
------------

We provide two scripts to run tests.
These are ``bin/check.sh`` and ``bin/singlecheck.sh``.

The first script will run all tests if called without arguments.
It also accepts a filename (without ``.py`` ending and an optional ``test_`` prefix)
and will then run all tests from that file.

The ``singlecheck.py`` script allows one to run all tests matching a pattern.
You can pass an arbitrary amount of patterns to ``singlecheck.sh``
which will then get matched against the fully qualified test method name.
Such a specifier looks like ``tests.test_frontend_event.TestEventFrontend.test_create_event``.

Pattern matching is performed using ``fnmatch.fnmatchcase``.
If a pattern without an asterisk is passed it will be wrapped with one on both ends.
