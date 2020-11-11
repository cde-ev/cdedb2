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

Before starting any containers you have to build the corresponding image.
``docker-compose`` will do this for you if they do not exist.

If you see the need to manually rebuild them you can do so using
``docker-compose build``.
As the compose file is in a subdirectory you have to tell ``docker-compose``
where it should look for it using ``--file`` flag.
Another possibility is to simply change you working directory to the compose file.

Starting the containers
-----------------------

To start the containers you can simply run ``docker-copmpose up``.
This will let the containers run in the foreground and block your terminal.
If you wish to run the containers in a detached mode you can append a ``-d``.

Once the containers are running you can execute ``docker-compose ps``
to check if everything went well and all containers are still alive.
In this overview you are also able to see more information like port mappings.

Initializing the containers
---------------------------

Before you start using the containers you have to initialize a few things.
Most importantly this includes seeding the postgres database.
However if you have not yet run the ``i18n-compile`` and ``doc`` make targets
these should also be executed (in the container).
To do this you can run the following:

.. code-block:: console

    $ make i18n-compile
    $ make doc
    $ cp related/auto-build/files/stage3/localconfig.py cdedb/
    $ cd related/docker
    $ docker-compose exec app sudo -u www-data make sql-seed-database

All off these command could also have been executed inside the docker folder
but this would have lead to them being owned by root.

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

Some development command like ``pylint`` are however not installed
inside the containers to keep them light and should be run locally.
Having said that the compose file also includes ``adminer``
which can be reached via port ``8080``
and can be used to inspect the database.
For more information refer to the ``docker``/``docker-compose`` documentation
or execute ``docker-compose help``.
