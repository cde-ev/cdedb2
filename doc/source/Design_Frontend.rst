Frontend Design
===============

Frontend endpoints are invoked depending on the URL requested by the client as mapped to
in ``cdedb/frontend/paths.py``. Each endpoint is a python function responsible for
aggregating the requested information from the :doc:`backend <Design_Backend>` and
returning a rendered :doc:`template <Design_Template>` or redirect.

.. todo:: Add information on abstract stuff

.. seealso::
    A rough overview about the general control flow upon a request can be found in the
    development chapter at :doc:`Development_Typical-Request`.


Input handling
--------------

For retrieving user input from POST-requests, there are the ``REQUEST*`` decorators in
:py:mod:`cdedb.frontend.common`, furthermore the ``request_extractor`` functions for
some rare use cases where it is not known at the beginning which data is needed.
In general, you should always provide feedback on user input, which basically means
every POST action should cause a meaningful notification. The notification mostly tells
about success or failure of input :doc:`validation <Design_Validation>`.
Remember to check successful validation before doing any processing, since the backend
raises errors on invalid data.


.. _cron-jobs:

Cron jobs
---------

All tasks which are designed to be executed regularly in an automated way, like syncing
with the malinglist software or cleaning up the database, are represented by a frontend
function with the ``@periodic`` decorator.
This decorator sets an additional ``cron`` attribute on the function, that is a dict
containing an identifier and the interval (measured in executions of the cron frontend,
see below) in which to run that job.

Every periodic function is given the ``RequestState`` and a dict conventionally named
``store`` as parameters. This store is to be saved in the database between the single
runs, thus the function should return an updated version of it. The function should also
take care of proper initialisation of the store if it is empty, as that is the case if
there was no execution of the task before.

To take care of the stores and actually run the tasks, we have the ``CronFrontend``
found in :py:mod:`cdedb.frontend.cron`, whose ``execute`` function sets up a basic
``RequestState``, searches for periodic functions and executes them. This should be done
every 15 minutes and can be run using the ``cron_execute.py`` script for convenience.
