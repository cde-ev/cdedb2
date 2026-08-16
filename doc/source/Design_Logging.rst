Logging
=======

We use pythons build-in ``logging`` library.
Therefore, we make use of the hierarchy based definition of loggers:
The root logger is configured in ``cdedb/logging.py`` by adding log handlers (see below) and
setting the log level (via config) and instantiated once in ``cdedb/__init__.py``.
Each module may then instantiate their own logger, using their python package name,
e.g. ``cdedb/backend/core.py`` would use ``cdedb.backend.core``, defaulting in their
configuration to the root logger.

In production (and development vm), we store our logs via ``journald``. To access them,
you can call::

  sudo journalctl --unit cdedb-app --unit cde-ldap --since=today

Its possible to filter the logs based on their log level / priority (info, warning ...)::

    sudo journalctl PRIORITY=info

Beside the fields specified in ``man systemd.journal-fields``, we enable filtering by the
name of the used database via ``CDB_DATABASE_NAME``. This is useful to distinguish output
of tests from regular ones. Take care that filtering via ``--unit cdedb-app`` as above
excludes all test outputs.

At last, its also possible to show only logs issued by the CdEDB python application itself,
while the ``--unit cdedb-app`` includes also related programs like fail2ban or gunicorn, with::

    sudo journalctl --identifier=cdedb

For further information, see ``man journalctl`` and take a look at ``cdedb/logging.py``.
See also :doc:`Development_FS-Overview`.

In the CI (and development docker containers), we simply print the logs to stdout, imitating
the information which would be available via ``journald`` in the vm.
See :ref:`development-environment-docker-logs` for further information.
