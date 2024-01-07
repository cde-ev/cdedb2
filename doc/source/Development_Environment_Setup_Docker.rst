Setup a Docker container
========================

Here we describe how the Docker images provided inside the repository
may be used for development.

Prerequisites
-------------

To utilise the images you need to have Docker installed. Furthermore the use
of ``docker compose`` (which is a separate plugin) is advised for ease of
use.  Theoretically the images and the compose file can also be run by podman
or similar OCI compatibel tools.

The following commands assume that you are a member of the docker group
or have gained the proper permissions by other means like sudo.

Variants
--------

There are two variants of the Docker environment, configured via separate
compose files. These are as follows.

- ``related/docker/docker-compose-run.yaml`` for simply running the CdEDB; this
  does not provide additional functionality to keep the environment lean
- ``related/docker/docker-compose-dev.yaml`` is a superset of the previous and
  provides additional functionality for developing the CdEDB especially also
  from inside the container (e.g. installing reasonable editors)

Building the images
-------------------

Before starting any containers you have to build the corresponding images.
``docker compose up`` will do this for you if they do not yet exist.
As the compose file is in a subdirectory you have to tell ``docker compose``
where it has to look for it using the ``--file`` flag.
The flag needs to be places between ``docker compose`` and the subcommand.
Another possibility is to simply change you working directory
to the parent directory of the compose file.
This applies to (almost) all subcommands.

Should you see the need to manually rebuild them you can do so using
``docker compose build``.

.. note:: To build the dev-container you will first need to build the non-dev
          variant as the dependency is not publicly resolvable.

Starting the containers
-----------------------

To start the containers you can simply run ``docker compose up``.
This will let the containers run in the foreground and block your terminal.
If you wish to run the containers in a detached mode you can append a ``-d``.
The LDAP container depends on a properly seeded database. This is already
honored during the default setup process and needs no further manual
intervention.

Once the containers are running you can execute ``docker compose ps``
to check if everything went well and all containers are still alive.
In this overview you are also able to see more information like port mappings.

To shutdown the containers you can either press CTRL+C
if you started the containers attached
or run ``docker compose down`` otherwise.

Initializing the containers
---------------------------

.. note::

    This is not required anymore if you preserve the original entrypoint.
    If you however still want to create the sample-data manually etc.
    you are free to use this section as a guide.
    Note that all active sessions have to be stopped for the sample-data target to work.
    In particular you have to stop the LDAP container.

Before you start using the containers you have to initialize a few things.
Most importantly this includes seeding the postgres database.
However if you have not run the ``i18n-compile`` and ``doc`` make targets yet,
you should also call them to ensure everything is available.
To do this you can run the following:

.. code-block:: console

    $ # navigate to the repository root
    $ make i18n-compile
    $ make doc
    $ docker compose --file related/docker/docker-compose.yaml exec app python3 -m cdedb dev apply-sample-data

.. warning::

    Currently it is advised to run make targets which generate files
    from the host to ensure proper permissions on the files.
    You may also experiment with executing them from within the containers
    when running as another user however this is somewhat complicated.
    Properly mapping the container user to the host user is a future TODO.


Using the containers
--------------------

Normally the compose file is configured to automatically mount your code
at the correct directory inside the application container.
If you wish to execute commands inside a running container you can either
pass them one-by-one to ``exec`` like above
or start an interactive session by executing bash inside a container
(``docker compose exec app bash``).
To run commands in the postgres container
you have to substitute ``app`` with ``cdb``.

The web interface is exposed at `localhost:8443 <https://localhost:8443>`_.
Additionally ``adminer``
--- a tool which can be used to inspect the database ---
can be reached using `localhost:8080 <http://localhost:8080>`_.
The ldap server listens at `localhost:8389 <https://localhost:8389>`_.

Some development commands like ``pylint`` are however not installed
inside the containers to keep them light and should be run locally.
For more information refer to the ``docker``/``docker compose`` documentation
or execute ``docker compose help``.


Resetting the containers
------------------------

The containers store their state in multiple volumes.
You can list these using ``docker volume ls``.
When starting the containers using ``docker compose`` they get a proper name
which is generated from the name set in the ``docker-compose.yaml`` file
and the parent folder of that file.

The volumes used should therefore be named:

* ``docker_cert``: Stores the dynamic self-signed certificate for apache.
* ``docker_config``: Stores the config and secret-config files.
* ``docker_database``: Attached to the postgres container and stores the database.
* ``docker_files``: Attached to the app container and stores uploaded attachements and similar files.
* ``docker_ldap``: Stores the dynamic self-signed certificate for ldap.

You can delete these volumes using ``docker volume rm VOLUME``.
This can however only be done when the containers are not running.
Execute ``docker compose down`` to properly stop the containers.
To remove all volumes you can simply run ``docker compose down --volumes``.

If you changed the entrypoint shell scripts or the docker files themselves, you
need to rebuild the containers via ``docker compose build``.
