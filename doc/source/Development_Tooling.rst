Tooling
=======

The development environment is described in :doc:`Development_Setup`,
however the CdEDB also has several specialised utility scripts, which can be
found in the ``bin`` subdirectory.

* ``analyze_timing.py``: Check performance by utilizing the test suite.
* ``check.sh``: Run the test suite.
* ``count_wikipedia_german.py``: Generate word lists from large text corpora
  (used for password strength estimation).
* ``escape_fuzzing.py``: Do a brute-force attempt to find an XSS vulnerability.
* ``evolution-trial.sh``: Check a set of database evolutions for fitness.
* ``extract_msgstr.py``: Prepare i18n-data for spell-checking.
* ``isolated-evolution.sh``: Launch a one-time use container for testing a
  set of database evolutions (like ``evolution-trial.sh``, but more thorough).
* ``isolated-test.sh``: Launch a one-time use container running the test suite.
* ``singlecheck.sh``: Run specific tests in the test suite.
