Using the VM image
==================

.. toctree::
   :maxdepth: 1
   :hidden:

   Development_Setup_Manual

.. todo:: "unrelateten" Development Bezug verschieben?

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

  kvm -m 1G -enable-kvm -device virtio-rng-pci -net nic,model=virtio -net user,hostfwd=tcp:127.0.0.1:20022-:22,hostfwd=tcp:127.0.0.1:20443-:443 -drive file=cdedb.qcow2,if=virtio,cache=writethrough

If ``cdedb.vdi`` is the downloaded image, then the VM can be run with
VirtualBox via the GUI. Thereby, choose the unpacked ``cdedb.vi`` image as hard
disk. Furthermore, you would like to set some port forwarding (which is included
in the kvm command).

If you dont know how to do this, take a look at the first point in
:ref:`accessing-vm-windows`. Note that there are two existing port forwarding, one
for ``20022`` and one for ``20443``.

Accessing -- Linux
------------------

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

.. _accessing-vm-windows:

Accessing -- Windows
--------------------

Das Ansprechen der VM ist unter Windows etwas komplizierter als unter Linux.
Im Folgenden werden die Arbeitsschritte einmal für VirtualBox durchgegangen.
Das Passwort für den Nutzer ``cdedb`` der VM ist ``akademie``.

* Web: Im VirtualBox Manager, bearbeite die VM

    * Netzwerkadapter / Adapter1: Angeschlossen an ``NAT``
    * Erweitert / Port-Weiterleitung: Neue Regel::

        Protokoll:TCP, Host-ID:127.0.0.1, Host-Port:20443, Gast-Port:223

  Jetzt lässt sich die VM unter https://localhost:20443/ im Browser ansprechen.

* ssh

    * VirtualBox Manager / Datei / Host-only Netzwerk-Manager / Erzeuge::

        NAME, IPv4:192.168.56.1/24, DHCP-Server:enable

    * Im VirtualBox Manager, bearbeite die VM / Netzwerkadapter / Adapter 2::

        Angeschlossen an:Hostonly-Adapter, Name:NAME

    * Starte die VM, melde dich an

        * ``id a`` sollte einen Eintrag ``enp0s8`` oder ähnlich zeigen, der leer ist::

            sudo nano /etc/network/interfaces

        * Am Ende der Datei hinzufügen::

            auto enp0s8
            iface enp0s8 inet static
            address 192.168.56.10
            netmask 255.255.255.0

  Jetzt sollte die VM über die CMD erreichbar sein::

    ssh.exe cdedb@192.168.56.10

* mounten: Dies ist nur für die aktive Entwicklung relevant, nicht für die Offline-VM.
  Hierfür gibt es keine Windows eigene Lösung. So funktionierts trotzdem

    * Führe die Schritte unter ``ssh`` aus.
    * Installiere https://github.com/billziss-gh/sshfs-win -- mindestens
      ``SSHFS-Win 3.5 BETA``
    * Navigiere zum Desktop im Explorer / Rechtsklick ``Dieser Pc`` / Netzlaufwerk verbinden... ::

        \\sshfs.r\cdedb@192.168.56.10\cdedb2

  Nun sollte die VM als Netzlaufwerk eingehängt worden sein.

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
