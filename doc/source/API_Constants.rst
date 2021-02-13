Constants
=========

To represent some fixed set of available options internally, we usually use
enums internally. To store such data in the database, we represent it by
integers.

However, at some places in our interface, these integers are actually presented
to users without further processing. In particular, this is the case for the
event export described in detail at :doc:`Handbuch_Orga_Partieller-Import`
as well as for some advanced facilities for moderators and admins.

To help interpret these values, we provide the following list.

cdedb.database.constants
------------------------

.. automodule:: cdedb.database.constants
   :members:
