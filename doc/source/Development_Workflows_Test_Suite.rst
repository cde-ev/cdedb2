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


.. _running-tests:

Running tests
-------------

We provide a central script to run (parts of) our testsuite: ``bin/check.py``

Unittest
^^^^^^^^

You can pass an arbitrary amount of patterns to ``check.py``, which will then get matched
against the fully qualified test method name.
Such a full specifier looks like
``tests.test_frontend_event.TestEventFrontend.test_create_event``, but you can also pass
an unambiguous part of it, like e.g. just ``create_eve``, for convenience.
These parts of course can also specify complete test files, like ``test_backend_core``,
where unambiguous parts suffer too.

Pattern matching is performed by unittest, which uses ``fnmatch.fnmatchcase``
internally [#fnmatch]_.
If a pattern without an asterisk is passed it will be wrapped with one on both ends.

Code coverage
^^^^^^^^^^^^^

.. todo:: Implement coverage in ``bin/check.py`` script an document this here.

The coverage html reports for easier to inspection are accessible on the local dev
instance via Apache at `localhost:8443/coverage <https://localhost:8443/coverage>`_ for
docker and `localhost:20443/coverage <https://localhost:20443/coverage>`_ for the VM.

.. _xss-check:

XSS vulnerabilty check
^^^^^^^^^^^^^^^^^^^^^^

Our test suite also contains a little script which injects a customizable payload into
every database field and then checks that it is escaped correctly.
You can run this script by just invoking ``make xss-check`` or specify a custom
payload using the argparse entrypoint, e.g.::

    bin/check.py --xss-check --payload "<script>mycustompayload</script>"


Parallel testing
----------------

Our test suite is implemented using ``unittest``.
However, as a web application the CdEDB needs database access.
To mock the database and allow running multiple test "threads" in parallel, we create
four test databases, ``cdb_test_1`` to ``cdb_test_4``.

.. todo:: Implement a lock mechanism preventing multiple test runs using the same thread
    in parallel. Document this here.

    Implement parallel testing inside ``bin/check.py``.

To specify which thread should be used for a test run, you can either use the
``--thread-id`` option of the argparse entrypoint of ``bin/check.py``, or when using
``make``, just pass the thread id as environment variable directly via the command
line, as e.g.::

    THREADID=3 make xss-check

Every test ``Application`` stores log files and, if needed, some test files for up- and
downloading (e.g. assembly attachments) in a temporary directory living inside ``/tmp``,
whose structure is as follows::

    /tmp/
    `-- cdedb-test-<thread-id>
        |-- logs
        |   `-- [...]
        `-- storage
            `-- [subdirectories for attachments, fotos, files for uploading, exports, ...]

.. note::
    The majority of our tests do not need the test file storage. Thus, every test
    who needs it has to get the ``@storage`` decorator from ``tests.common`` for the
    storage directory to be created. After this test has finished, the directory will
    be deleted.


.. [#fnmatch] https://docs.python.org/3/library/unittest.html#unittest.TestLoader.testNamePatterns
