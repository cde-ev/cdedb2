Developing
==========

In :ref:`sample-data` the available data sets are listed (mainly existing
accounts). Source controle is done via git. Upon login (VM or container) a
short summary of useful commands is displayed -- this is reproduced below.

.. literalinclude:: motd-vm.txt
   :caption: Command listing (VM-variant, container-variant slightly diverges)

Many useful actions are triggered via a ``Makefile``. Change the working
directory to the repository root and invoke ``make`` to see a list of
available options.

Performance
-----------

To increase performance it is very effective to do one of these two things,
but they can cause serious data loss. So they are only recommended when
working with test data.

* Replace ``cache=writethrough`` by ``cache=writeback`` or even
  ``cache=unsafe`` when running the VM.

* In the file `/etc/postgresql/15/main/postgresql.conf` in the VM set the
  following options in the ``WRITE AHEAD LOG`` section::

    fsync = off
    synchronous_commit = off
    full_page_writes = off

.. _configuring_i18n:

Configuring
-----------

In the ``i18n`` directory in the repository there are two helper scripts for git:
``git-diff-filter-po.sh`` and ``git-merge-po.sh``.

These scripts are enabled by default on the VM image.
As the Docker container however only mounts the local repository
you will have to configure these manually.
To enable these scripts add the following to the ``.git/config`` file::

    [diff "podiff"]
        textconv = i18n/git-diff-filter-po.sh
    [merge "pomerge"]
        name = Gettext merge driver
        driver = i18n/git-merge-po.sh %O %A %B

The first one is used when executing ``git diff`` on `.po` files.
It removes all lines starting with ``#:`` before comparing the files,
because they contain line numbers of every string usage
and those numbers are prone to change.

If you want to disable this temporarily you can run ``git diff --no-textconv``.
If you however want to disable this permanently
you can remove the following lines from your ``.git/config`` file::

    [diff "podiff"]
        textconv = i18n/git-diff-filter-po.sh

or add the following line to your ``.git/info/attributes`` file::

    *.po diff


The second one is a three-way merge driver for ``.po`` and ``.pot`` files,
hopefully making merging of these files easier.
If the merge fails you will have to look for ``#-#-#-#-#`` as conflict markers
instead of the usual git conflict markers.

If you want to disable this,
remove the following lines from your ``.git/config`` file::

    [merge "pomerge"]
        name = Gettext merge driver
        driver = i18n/git-merge-po.sh %O %A %B

or add the following line from your ``.git/info/attributes`` file::

    *.po merge

Running it
----------

Last step before startup is compiling the GNU gettext .mo files for i18n::

  make i18n-compile

Now, check if postgres and pgbouncer are running. Optionally you
can run the test suite first to see whether everything is ready::

  ./bin/check.py

Now start the apache and access ``https://localhost:10443/db/`` with a
browser.

Refreshing the running instance
-------------------------------

Changes to the code can be propagate as follows to the current instance. For
templates no action is necessary. For the python code the gunicorn server
should also automatically reload on changes. If anything jams the workers can
be restarted::

  sudo systemctl restart apache2 gunicorn

You can use the make target ``reload`` to easily re-compile i18n and trigger
the worker reload::

  make reload

For the database you should restart pgbouncer (which probably has some open
connections left) before doing ``make sample-data``.

Sample dev setup
----------------

Here is a description of the setup as provided by makefile in directory
``related/auto-build/runtime``. This is by no means a mandatory setup, but
hopefully useful for somebody. First an overview of the directory structure::

    /home/markus/cdedb2/
    ├── related
    │   ├── auto-build
    │   │   ├── runtime
    │   │   │   ├── Makefile
    │   │   │   ├── share
    │   │   │   ├── image.qcow2
    │   │   │   └── ...
    │   │   └── ...
    │   └── ...
    └── ...

Everything lives inside the directory ``/home/markus/cdedb2/`` which is a
clone of the git repository. Most development happens in this directory. Then
there is the VM image ``image.qcow2`` inside ``related/auto-build/runtime``
which is started by ``make start``. With ``make mount``
sshfs is used to mount the git repository inside the VM to the directory
``share/``. Finally by ``make ssh`` one can log into the VM.

The typical change is developed in ``cdedb2/`` and committed there. Then the
commit is transferred to the VM by issuing ``make sync-into-vm`` in the
``runtime/`` directory. Now the test suite is executed inside the VM and if
successful the change is pushed from ``cdedb2/`` to the server.
