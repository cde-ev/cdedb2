Environment Setup
=================

Before the application can be started, there are some preparations necessary. Beside cloning
the repository, installing the required packages and configuring third party tools (like
pgbouncer or apache2), there are the following additional points:

* adjusting the :doc:`Design_Configuration`
* creating the PostgreSQL database
* creating the file storage
* creating the log directory

To do this in a convenient way, there is the :mod:`cdedb_setup` module. It consumes most
necessary information from the Config (and the given overrides) and performs the setup
process in several python functions.

Additionally, it provides a command line interface, so the functions can be used during
scripting or setup via terminal. All available targets are shown after executing::

  python3 -m cdedb_setup

Make sure to add the :mod:`cdedb_setup` module to the python path before.

A step-by-step guide through the setup is provided at :doc:`Development_Environment_Manual`.
For using one of the prebuild environments, take a look at :doc:`Development_Environment_Setup_VM`
and :doc:`Development_Environment_Setup_Docker`, respectively.
