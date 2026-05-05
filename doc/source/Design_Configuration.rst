Configuration
=============

The guiding spirit for development is that there are no hardcoded values anywhere in the codebase.
Instead, there is a central place, the ``Config``, holding all hardcoded values, which can then be
used in the actual code.
"Hardcoded values" means hereby literally anything, from passwords over the name of the database
to the default time zone or the storage directory.

The config is build hierarchically:
First, there are default values for each config variable in the file :mod:`cdedb.config.defaults`.
They can be overridden via custom config files. Any number of such config files can be given via
the environment variable ``CDEDB_CONFIGPATHS``, separated by ``:``. Earlier files take precedence.
Empty or non-existant files are ignored. If the environment variable is not set, overrides are loaded
from ``/etc/cdedb/config.py``.

To provide a second layer of protection, there is a separate Config class holding all critical
(mostly password) config options: the ``SecretsConfig``.
To overwrite this subset of config values (which is highly recommended!), let the
``SECRETS_CONFIGPATH`` config option to point to your custom secrets config file.
This file can then be further protected, for example by shrinking its access permissions on
the file system to a specific user which is running the application (conventionally named
``www-cde``).

Note that the specified files are only read once, at application start, any changes to these files
will only take effect after a restart or by explicitly clearing the config cache.

If you need to temporarily adjust config values, ``Config`` provides a ``with_override`` context manager
method, that can be used both to set different config paths or to explicitly override keys from either
``Config`` or ``SecretsConfig``.

Both ``Config`` and ``SecretsConfig`` are singletons, so instantiating them will always return
the exact same singular instance respectively. Thus any change made to the config via ``with_override``
immediately takes effect for every single config object anywhere, regardless of if it was instantiated
before or after the override.

Note that it is not possible to directly write to the config.
