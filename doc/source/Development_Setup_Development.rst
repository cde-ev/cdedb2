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

* In the file `/etc/postgresql/11/main/postgresql.conf` in the VM set the
  following options in the ``WRITE AHEAD LOG`` section::

    fsync = off
    synchronous_commit = off
    full_page_writes = off


Configuring
-----------

In the `/cdedb2/i18n/` directory in the VM there are two helper scripts for git,
that are enabled by default: `git-diff-filter-po.sh` and `git-merge-po.sh`.

The first one is used when executing ``git diff`` on `.po` and `.pot` files.
It removes all lines starting with ``#`` before comparing the files, because
these lines contain line numbers of every string usage and those numbers are
prone to change.

If you want to disable this, remove the following lines from your
``.git/config`` file::

	[diff "podiff"]
		textconv = i18n/git-diff-filter-po.sh

and the following lines from your ``.git/info/attributes`` file::

	*.po diff=podiff
	*.pot diff=podiff

Or you can run ``git diff --no-textconv`` to temporarily disable this.


The second one is a three-way merge driver for `.po` and `.pot` files, hopefully
making merging of these files easier. The merge will fail if there are duplicate
msgids in either of the files to be merged.

If you want to disable this, remove the following lines from your
``.git/config`` file::

	[merge "pomerge"]
		name = Gettext merge driver
		driver = i18n/get-merge-po.sh %O %A %B

and the following lines from your ``.git/info/attributes`` file::

	*.po merge=pemerge
	*.pot merge=pomerge

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