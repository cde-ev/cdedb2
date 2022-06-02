WSGI Application
================

.. todo:: add information on application, URL routing

Configuration
-------------

Some general remarks about the configuration can be read in :doc:`Design_Configuration`.
However, Apache does not propagate environment variables properly.
Therefore, the WSGI application **takes only the default config path into account
and ignored the CDEDB_CONFIGPATH environment variable**.
