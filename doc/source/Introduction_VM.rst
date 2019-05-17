.. _vm:

Using the VM image
==================

Here we describe how the VM image provided by the auto-build may be used for
development and offline usage (i.e. at events).

Prerequisites
-------------

To run the image you need the Qemu/KVM or VirtualBox software for
virtualization. Furthermore some software is recommended for working with
the running image: ssh for shell access and sshfs for mounting the
repository in the VM into your local file system.

Download
--------

The vm-images can be downloaded from `the CdE server
<https://ssl.cde-ev.de/cdedb2/images/>`_. The access credentials can be
found on `the tracker
<https://tracker.cde-ev.de/gitea/cdedb/cdedb2/wiki/Home>`_.

Running
-------

If ``cdedb.qcow2`` is the downloaded image, then the VM can be started with
QEMU via the following command (note that the name of the binary may differ
from ``kvm``)::

  kvm -m 1G -enable-kvm -net nic,model=virtio -net user,hostfwd=tcp:127.0.0.1:20022-:22,hostfwd=tcp:127.0.0.1:20443-:443 -drive file=cdedb.qcow2,if=virtio,cache=writethrough

If ``cdedb.vdi`` is the downloaded image, then the VM can be run with
VirtualBox via the GUI.

Accessing
---------

Once the VM is up and running you can access it in the following ways. The
password for the ``cdedb`` user (used for access via ssh etc.) is
``akademie``.

* web: Open https://localhost:20443/ in a browser of your choice.
* ssh::

    ssh -p 20022 cdedb@localhost

* scp (note that there are two possible directions)::

    scp -P 20022 /path/to/source cdedb@localhost:/path/to/destination
    scp -P 20022 cdedb@localhost:/path/to/source /path/to/destination

* sshfs (this is probably the most comfortable option for development,
  and only necessary for development not for usage during an event)::

    sshfs cdedb@localhost:/cdedb2/ /path/to/mountpoint/ -p 20022

For ease of use it may be advisable to put these commands into script
files. Additionally it helps to put your ssh public key into the (new)
file ``/home/cdedb2/.ssh/authorized_keys`` to suppress password queries.

Developing
----------

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

* In the file `/etc/postgresql/9.6/main/postgresql.conf` in the VM set the
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

.. _event-offline-usage:

Offline Usage
-------------

The following assumes that you successfully set up the VM (i.e. what
is covered in the first four sections of this document until the
development specific bits start).

Making the VM suitable for offline usage during an event now involves
the following steps.

First you have to export the event from the online instance thereby
locking the online instance disabling further changes. For this point
your browser at the event overview page and hit the corresponding
button. This will download a JSON-file containing the data of the
event. Store it safely.

Now copy this file via ``scp`` into the VM and run the offline
initialization script inside the VM::

  /cdedb2/bin/make_offline_vm.py path/to/export.json

Note that this deletes all data inside the VM before importing the
event.

Now the VM is ready to be used for offline deployment. Access it via
browser. For security reasons the VM does not contain your real login
password. Everyone can log in with their normal username (i.e. their
email address) and the password ``secret``.

After the event you export the data from the offline instance the same
way you exported the online instance, receiving a JSON-file with the
data of the offline instance. This file you upload into the online
instance thereby unlocking the event. This overwrites all data of your
event in the online instance with data from the offline VM
(potentially deleting things).

You can test the lock/unlock procedure by unlocking the online
instance directly after locking it by uploading the file you just
downloaded. This has no effect since the event data is replaced by
itself.
