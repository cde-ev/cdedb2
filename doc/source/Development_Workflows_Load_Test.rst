Load Testing
============

This page describes the details of performing a load test on a database
instance.

Prerequisites
-------------

The load testing utilizes `Locust <https://locust.io/>`_ which needs to be
installed on the host generating the load.

The VM processing the load needs to be prepared with additional sample data as
follows::

    make sample-data ; sudo -u www-cde bin/insert_huge_data.py -f 200 -v

.. note:: This step will take a considerable amount of time (think an hour).

Running
-------

To do an interactive load test run Locust as follows::

    locust -f bin/load-test/load_test_<variant>.py

Then point a browser at http://localhost:8089 to view the Locust frontend.

To run Locust from the command line something like the following is a sensible
command::

    locust -f bin/load-test/load_test_<variant>.py -H https://localhost:10443/ -u 30 -r 10 -t 300s --headless --csv /tmp/locust-output

Interpretation
--------------

Please note that benchmarking is a kind of black magic and the resulting
numbers need careful interpretation to yield sensible information. The most
reliable component is the relative performance between different
configuration options.
