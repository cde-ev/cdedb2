Tooling
=======

The development environment is described in :doc:`Development_Environment`,
however the CdEDB also has several specialised utility scripts, which can be
found in the ``bin`` subdirectory.

* ``analyze_timing.py``: Check performance by utilizing the test suite.
* ``check.py``: The entrypoint to our testing facilities, take a look at
  :ref:`running-tests` for more details.
* ``count_wikipedia_german.py``: Generate word lists from large text corpora
  (used for password strength estimation).
* ``create_sample_data_json.py``: Generate a json file from the current database
  state. Take a look into the :doc:`Development_Workflows_Test_Suite` for more details.
* ``create_sample_data_sql.py``: Generate a SQL file from an input JSON file. Take a
  look into the :doc:`Development_Workflows_Test_Suite` for more details.
* ``escape_fuzzing.py``: Do a brute-force attempt to find an XSS vulnerability.
  It is recommended to execute this using ``check.py``, see :ref:`xss-check`.
* ``evolution-trial.sh``: Check a set of database evolutions for fitness.
* ``extract_msgstr.py``: Prepare i18n-data for spell-checking.
* ``isolated-evolution.sh``: Launch a one-time use container for testing a
  set of database evolutions (like ``evolution-trial.sh``, but more thorough).
* ``isolated-test.sh``: Launch a one-time use container running the test suite.

There is also a development server running at port 5000
which bypasses Apache and provides an interactive traceback explorer
including a console in which expressions can be evaluated in the respective namespace.

To access the ldap server from a local vm, it is currently necessary to manually switch
from TLS to plain TCP connections by removing the ``ssl`` parameter during server
creation in ldap/main.py: Tools like ldapsearch (from ``ldap-utils`` package) or
ApacheDirectoryStudio seems to do not work properly if the certificate name differs
from the hostname which is used to access the ldap server.
If those tools are used *within* the vm, everything works fine.

It is also reasonable to increase the debug level in ldap/main.py from WARNING to DEBUG.
