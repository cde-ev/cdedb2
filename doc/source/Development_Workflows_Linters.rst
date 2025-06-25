Linting and Type Checking
=========================

We use `ruff <https://docs.astral.sh/ruff/>`_ for linting our codebase
and `mypy <https://mypy.readthedocs.io/>`_  for type checking.

Autoformatter
-------------

Formatting and running our linter is bundled in the ``make autoformat`` command.
It is recommended to enable a file watcher in your IDE to automatically
run this command on change.


PyCharm
~~~~~~~

In Pycharm, this is possible via the `File Watchers` plugin, using the following
configuration. Depending on your :doc:`Development_Environment` there are
different ways to invoke ``make``:

- run ``make`` on your host machine (needs ``ruff`` available in the python path):
    - program ``make``

    - arguments ``autoformat``

- run ``make`` in the docker container:
    - command: ``docker``

    - arguments ``compose --file related/docker/docker-compose.yaml exec -u cdedb app make autoformat``

For all dev setups the same, set the following options:

- output paths to refresh: ``$FilePath$``
  (This is important because it makes PyCharm apply the changes only to the current file.)

- working directory: ``$ProjectFileDir$``
