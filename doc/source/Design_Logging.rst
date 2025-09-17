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

  sudo journalctl --reverse --unit cdedb-app --unit cde-ldap

Its possible to filter the logs based on their log level / priority (info, warning ...),
and display more information like the file and loc where the log entry was produced.
For further information, see ``man journalctl`` and take a look at ``cdedb/logging.py``.
See also :doc:`Development_FS-Overview`.

In the CI (and development docker containers), we simply print the logs to stdout, imitating
the information which would be available via ``journald`` in the vm.
See :ref:`development-environment-docker-logs` for further information.
