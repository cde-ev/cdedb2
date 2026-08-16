Filesystem Overview
===================

.. todo:: Explain our filesystem hierarchy

Code
----

Logs
----

Detailed information about our logging infrastructure are available at :doc:`Design_Logging`.
Especially, cdedb related logs are stored in ``journald`` and may be accessed via ``journalctl``,
including the ``gunicorn`` logs.

Apache saves its logs under ``/var/log/apache2``.
The log most relevant for debugging is ``ssl_error.log``.
It contains not only errors from apache itself
but also unhandled exceptions thrown from the cdedb application.
