Configuration
=============

The guiding spirit for development is that there are no hardcoded values anywhere in the codebase.
Instead, there is a central place, the ``Config``, holding all hardcoded values, which can then be
used in the actual code.
"Hardcoded values" means hereby literally anything, from passwords over the name of the database
to the default time zone or the log directory.

The config is build hierarchically:
First, there are default values for each config variable in the file :mod:`cdedb_setup.config`.
They can be overwritten by specifying the path to a custom config file via the environment
variable ``CDEDB_CONFIGPATH``.

To provide a second layer of protection, there is a separate Config class holding all critical
(mostly password) config options: the ``SecretsConfig``.
To overwrite this subset of config values (which is highly recommended!), let the
``SECRETS_CONFIGPATH`` config option point to your custom secrets config file.
This file can then be further protected, for example by shrink its access permissions on
the file system to a specific user which is running the application (conventionally named
``www-data``).

Both, ``Config`` and ``SecretsConfig``, take config options from a custom file without a default
value in :mod:`cdedb_setup.config` not into account. However, there are cases where it would be
desirable to add values to the config objects which are not used in the actual codebase, f.e.
if they are needed inside the test-suite. To honor such usecases, there is the class
``TestConfig`` inheriting from ``Config``, allowing to set arbitrary values inside the overwrite
files.
