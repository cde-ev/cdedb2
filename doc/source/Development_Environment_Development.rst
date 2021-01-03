Developing
==========

In :ref:`sample-data` the available data sets are listed (mainly existing
accounts). Source controle is done via git. Upon login with ssh a short
summary of useful commands is displayed -- this is reproduced below.

.. literalinclude:: motd.txt

Performance
-----------

To increase performance it is very effective to do one of these two things,
but they can cause serious data loss. So they are only recommended when
working with test data.

* Replace ``cache=writethrough`` by ``cache=writeback`` or even
  ``cache=unsafe`` when running the VM.

* In the file `/etc/postgresql/12/main/postgresql.conf` in the VM set the
  following options in the ``WRITE AHEAD LOG`` section::

    fsync = off
    synchronous_commit = off
    full_page_writes = off


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
		driver = i18n/get-merge-po.sh %O %A %B

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

	*.po	diff


The second one is a three-way merge driver for ``.po`` and ``.pot`` files,
hopefully making merging of these files easier.
If the merge fails you will have to look for ``#-#-#-#-#`` as conflict markers
instead of the usual ``>>>>>>>``, ``=======`` and ``<<<<<<<`` git normally uses.

If you want to disable this,
remove the following lines from your ``.git/config`` file::

	[merge "pomerge"]
		name = Gettext merge driver
		driver = i18n/get-merge-po.sh %O %A %B

or add the following line from your ``.git/info/attributes`` file::

	*.po	merge

Sample dev setup
----------------

Here is a description of my setup hopefully aiding new devs in
setup. This is by no means a mandatory setup. First an overview of the
directory structure::

  /home/markus/DB/
  ├── cdedb2/
  │   └── ...
  ├── vm-repo/
  │   └── ...
  ├── image.qcow2
  ├── run-vm.sh
  └── ssh-vm.sh

Everything lives inside the directory ``/home/markus/DB/`` where
``cdedb2/`` is a clone of the git repository. Most development happens
in this directory. Then there is the VM image ``image.qcow2`` which is
started by the script ``run-vm.sh``. This script additionally uses
sshfs to mount the git repository inside the VM to the directory
``vm-repo/``. Finally the script ``ssh-vm.sh`` logs into the VM.

The typical change is developed in ``cdedb2/`` and committed
there. Then the commit is transferred to the VM by issuing the command
``git pull ../cdedb2/`` inside the ``vm-repo/`` directory. Now the
test suite is executed inside the VM and if successful the change is
pushed from ``cdedb2/`` to the server.
