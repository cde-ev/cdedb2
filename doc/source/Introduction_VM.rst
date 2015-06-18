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
<https://ssl.cde-ev.de/cdedb2/images/>`_. You need the following credentials
to access the link.

* Username: ``cdedb``
* Password: ``tie4aech7A``

Running
-------

If ``cdedb.qcow2`` is the downloaded image, then the VM can be started with
QEMU via the following command (note that the name of the binary may differ
from ``kvm``, also note that ``cache=writethrough`` may be replaced by
``cache=writeback`` for increased performance at the risk of data loss)::

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

* sshfs (this is probably the most comfortable option for development)::

    sshfs cdedb@localhost:/cdedb2/ /path/to/mountpoint/ -p 20022

Developing
----------

In :ref:`sample-data` the available data sets are listed (mainly existing
accounts). Source controle is done via git. Upon login with ssh a short
summary of useful commands is displayed -- this is reproduced below.

.. literalinclude:: motd.txt

Offline Usage
-------------

.. TODO:: HOWTO
