Frontend Design
===============

.. todo:: Add information on abstract stuff, input handling


.. _cron-jobs:

Cron jobs
---------

All tasks which are designed to be executed regularly in an automated way, like e.g.
syncing with the malinglist software or cleaning up the database, are represented by
a frontend function decorated with the ``@periodic`` decorator.
This decorator sets an additional ``cron`` attribute on the function, that is a dict
containing an identifier and the interval (measured in executions of the cron frontend,
see below) in which to run that job.

Every periodic function is given the ``RequestState`` and a dict conventionally named
``store``. This store is to be saved in the database between the single runs, thus the
function should return an updated version of it. The function should also take care of
proper initialisation of the store if it is empty, as that is the case if there was no
execution of the task before.

The entrypoint which issues the execution of such periodical functions described above
is the ``CronFrontend`` found in :py:mod:`cdedb.frontend.cron`. It expects an execution
period of 15 minutes, and can be invoked using the ``cron_execute.py`` script for
convenience.
