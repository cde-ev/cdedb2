Development Environment
=======================

.. toctree::
   :maxdepth: 1
   :hidden:

   Development_Environment_Setup_VM
   Development_Environment_Setup_Docker
   Development_Environment_Development

The initial step is to clone the `CdEDB repository
<https://tracker.cde-ev.de/gitea/cdedb/cdedb2.git>`_ with ``git``. To get
access, please `create an account
<https://tracker.cde-ev.de/gitea/user/sign_up>`_ and contact us at cdedb ät
lists.cde-ev.de.

There are two environments provided:

* A prebuilt VM-image usable for development as well as offline usage. See
  :doc:`Development_Environment_Setup_VM`.
* A Docker container which provides the usual container (dis-)advantages. See
  :doc:`Development_Environment_Setup_Docker`.

Once set up for developing, take a look at
:doc:`Development_Environment_Development` for instructions on how to use the
environment.

For details about the internals of the environment please look in the
directories ``related/auto-build`` and ``related/docker``.

Quickstart
----------

.. note:: The following section does omit many details and options for a
          more comprehensive account follow the links above.

VM
~~~

Change working directory to ``related/auto-build/runtime``. Download a
qcow2-image `according to the wiki
<https://tracker.cde-ev.de/gitea/cdedb/cdedb2/wiki/Home>`_. Invoke ``make`` to
see a list of possible actions (actual commands can be found in the
``Makefile``). You probably want to ``make start`` the VM.

Docker
~~~~~~

Change working directory to ``related/docker``. Invoke ``make`` to see a list
of possible actions (actual commands can be found in the ``Makefile``). You
probably want to ``make build`` an image and then ``make start`` it.

