Configuration
=============

The guiding spirit for development is that there are no hardcoded values anywhere in the codebase.
Instead, there is a central place, the ``Config``, holding all hardcoded values, which can then be
used in the actual code.
"Hardcoded values" means hereby literally anything, from passwords over the name of the database
to the default time zone or the log directory.

The config is build hierarchically:
First, there are default values for each config variable in the file :mod:`cdedb.config`.
They can be overwritten by specifying the path to a custom config file via the environment
variable ``CDEDB_CONFIGPATH``. [#apacheconfig]_

To provide a second layer of protection, there is a separate Config class holding all critical
(mostly password) config options: the ``SecretsConfig``.
To overwrite this subset of config values (which is highly recommended!), let the
``SECRETS_CONFIGPATH`` config option point to your custom secrets config file.
This file can then be further protected, for example by shrinking its access permissions on
the file system to a specific user which is running the application (conventionally named
``www-cde``).

Both ``Config`` and ``SecretsConfig`` take config options from a custom file without a default
value in :mod:`cdedb.config` not into account. However, there are cases where it would be
desirable to add values to the config objects which are not used in the actual codebase, f.e.
if they are needed inside the test-suite. To honor such usecases, there is the class
``TestConfig`` inheriting from ``Config``, allowing to set arbitrary values inside the overwrite
files.

All config objects can in principle be instantiated anywhere in the codebase. If they are
available otherwise (f.e. as instance attribute), using them is preferred over instantiation.
As a direct consequence of this design principle, the config is read-only and can not be
changed at runtime.

It should be avoided in general, but sometimes a Config object needs to live in the
global namespace of a module. If this is the case, importing from this module would
cause the Config object to be initialized, which is an unwanted side effect that
must not happen during import (f.e. importing from this module and setting the
config path environment variable later on will fail).
To circumvent this, a ``LazyConfig`` object may be used – it behaves identical
to a ``Config`` object, beside the initialization happens not on instantiation, but on
first access.

.. [#apacheconfig] For the subtleties of the Apache Configuration, see :doc:`Design_WSGI`.
