Droids
======

Users accessing an API are called droids. They are distinct from persona
accounts which belong to specific human beings and may belong to an entity
(like an event, assembly, etc.).

Droids must transmit their specific **secret** with every request in the
http header. The key of that header is defined globally in
:py:attr:`cdedb.models.droid.APIToken.request_header_key`.

.. automodule:: cdedb.models.droid

.. autoclass:: cdedb.models.droid.APIToken
    :members:
    :member-order: bysource

.. autoclass:: cdedb.models.droid.StaticAPIToken
    :show-inheritance:
    :members: name

.. autoclass:: cdedb.models.droid.DynamicAPIToken
    :show-inheritance:
    :members: name, title, notes, etime, ctime, rtime, atime, fixed_fields
    :member-order: bysource

Currently two static APIs exist:

.. autoclass:: cdedb.models.droid.ResolveToken
    :show-inheritance:
    :members: name

.. autoclass:: cdedb.models.droid.QuickPartialExportToken
    :show-inheritance:
    :members: name

Currently one dynamic API exists:

.. autoclass:: cdedb.models.droid.OrgaToken
    :members: name, event_id, fixed_fields, database_table
    :member-order: bysource
