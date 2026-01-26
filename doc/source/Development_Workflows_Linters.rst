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

- run ``make`` on your host machine (needs ``uv`` available on the path):
    - program ``make``

    - arguments ``autoformat``

- run ``make`` in the docker container:
    - command: ``docker``

    - arguments ``compose --file related/docker/docker-compose.yaml exec -u cdedb app make autoformat``

You can also try to run this inside a local vm using ``ssh``.

For all dev setups the same, set the following options:

- output paths to refresh: ``$FilePath$``
  (This is important because it makes PyCharm apply the changes only to the current file.)

- working directory: ``$ProjectFileDir$``

- You can specify a preferred output format for the ruff output via environment variable like this: ``RUFF_OUTPUT_FORMAT=<foo>``
  Available formats are listed below. Currently only "concise" and "pylint" result in clickable links leading to the location
  of the error.

- concise (our default)::

    cdedb/frontend/event/query.py:69:60: RUF100 [*] Unused blanket `noqa` directive
    Found 1 error.
    [*] 1 fixable with the `--fix` option.

- pylint::

    cdedb/frontend/event/query.py:69: [RUF100] Unused blanket `noqa` directive

- grouped::

    cdedb/frontend/event/query.py:
      69:60 RUF100 [*] Unused blanket `noqa` directive

    Found 1 error.
    [*] 1 fixable with the `--fix` option.

- full::

    RUF100 [*] Unused blanket `noqa` directive
      --> cdedb/frontend/event/query.py:69:60
       |
    67 |         event_parts = rs.ambience['event'].parts
    68 |         tracks = rs.ambience['event'].tracks
    69 |         stat_part_groups: dict[int, models.PartGroup] = {  # noqa
       |                                                            ^^^^^^
    70 |             part_group_id: part_group
    71 |             for part_group_id, part_group in rs.ambience['event'].part_groups.items()
       |
    help: Remove unused `noqa` directive
    66 |         """Present an overview of the basic stats."""
    67 |         event_parts = rs.ambience['event'].parts
    68 |         tracks = rs.ambience['event'].tracks
       -         stat_part_groups: dict[int, models.PartGroup] = {  # noqa
    69 +         stat_part_groups: dict[int, models.PartGroup] = {
    70 |             part_group_id: part_group
    71 |             for part_group_id, part_group in rs.ambience['event'].part_groups.items()
    72 |             if part_group.constraint_type == const.EventPartGroupType.Statistic

    Found 1 error.
    [*] 1 fixable with the `--fix` option.


.. note:

    If you are using a vm and mounting the working directory via ``sshfs``, consider
    setting the environment variable ``UV_PROJECT_ENVIRONMENT`` to a directory outside
    of the project directory to improve performance.

    Note that this will cause uv to create a new virtual environment at that location
    with all necessary dependencies, which might not be desired.
