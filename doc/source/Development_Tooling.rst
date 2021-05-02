Tooling
=======

The development environment is described in :doc:`Development_Environment`,
however the CdEDB also has several specialised utility scripts, which can be
found in the ``bin`` subdirectory.

* ``analyze_timing.py``: Check performance by utilizing the test suite.
* ``count_wikipedia_german.py``: Generate word lists from large text corpora
  (used for password strength estimation).
* ``create_sample_data_json.py``: Generate a json file from the current database
  state, currently in the ``tests`` directory. Take a look into the
  :doc:`Development_Workflows_Test_Suite` for more details.
* ``create_sample_data_sql.py``: Generate a SQL file from an input JSON file,
  currently in the ``tests`` directory. Take a look into the
  :doc:`Development_Workflows_Test_Suite` for more details.
* ``escape_fuzzing.py``: Do a brute-force attempt to find an XSS vulnerability.
  (It is recommended to execute this using ``tests/check.py``, see :ref:`xss-check`.)
* ``evolution-trial.sh``: Check a set of database evolutions for fitness.
* ``extract_msgstr.py``: Prepare i18n-data for spell-checking.
* ``isolated-evolution.sh``: Launch a one-time use container for testing a
  set of database evolutions (like ``evolution-trial.sh``, but more thorough).
* ``isolated-test.sh``: Launch a one-time use container running the test suite.

The entrypoint to our testing facilities is ``check.py`` in the ``tests`` subdirectory,
take a look at :ref:`running-tests` for more details.
