Setup a Docker container
========================

Here we describe how the Docker images provided inside the repository
may be used for development.

Prerequisites
-------------

To utilise the images you need to have Docker installed.
If you furthermore want to use the ``docker-compose.yaml`` file
(higly recommended) you also need ``docker-compose`` installed.
Theoretically the images and the compose file can also be run by podman
or similar OCI compatibel tools.
This however has not been tested yet.

The following commands assume that you are a member of the docker group
or have gained the proper permissions by other means like sudo.

Building the images
-------------------

Before starting any containers you have to build the corresponding images.
``docker-compose up`` will do this for you if they do not yet exist.
As the compose file is in a subdirectory you have to tell ``docker-compose``
where it has to look for it using the ``--file`` flag.
The flag needs to be places between ``docker-compose`` and the subcommand.
Another possibility is to simply change you working directory
to the parent directory of the compose file.
This applies to (almost) all subcommands.

Should you see the need to manually rebuild them you can do so using
``docker-compose build``.

Starting the containers
-----------------------

To start the containers you can simply run ``docker-copmpose up``.
This will let the containers run in the foreground and block your terminal.
If you wish to run the containers in a detached mode you can append a ``-d``.

Once the containers are running you can execute ``docker-compose ps``
to check if everything went well and all containers are still alive.
In this overview you are also able to see more information like port mappings.

To shutdown the containers you can either press CTRL+C
if you started the containers attached
or run ``docker-compose down`` otherwise.

Initializing the containers
---------------------------

Before you start using the containers you have to initialize a few things.
Most importantly this includes seeding the postgres database.
However if you have not yet run the ``i18n-compile`` and ``doc`` make targets
these should also be executed (from either inside or outside the container).
To do this you can run the following:

.. code-block:: console

    $ # navigate to the repository root
    $ make i18n-compile
    $ make doc
    $ sed -e 's|Path("/log/cdedb-|Path("/var/log/cdedb/|' \
        -e 's|Path("/log/cdedb.log|Path("/var/log/cdedb/global.log|' \
        related/auto-build/files/stage3/localconfig.py \
        > cdedb/localconfig.py
    $ cd related/docker
    $ docker-compose exec app sudo -u www-data make sql-seed-database

The ``make`` and ``sed`` commands could also have been executed
from inside the docker container
but this would have lead to them being owned by root.

.. todo:: Configure container to run commands unprivileged

Using the containers
--------------------

Normally the compose file is configured to automatically mount your code
at the correct directory inside the application container.
If you wish to execute commands inside a running container you can either
pass them one-by-one to exec like above
or start an interactive session by executing bash inside a container
(``docker-compose exec app bash``).
To run commands in the postgres container
you have to subtitute ``app`` with ``cdb``.

The web interface is exposed at `localhost:8443 <https://localhost:8443>`_.
Additionally ``adminer``
--- a tool which can be used to inspect the database ---
can be reached using `localhost:8080 <http://localhost:8080>`_.

Some development commands like ``pylint`` are however not installed
inside the containers to keep them light and should be run locally.
For more information refer to the ``docker``/``docker-compose`` documentation
or execute ``docker-compose help``.
