Orga API
========

The Orga API provides programmatic access to the data of an event.
In the future it may also allow directly creating, changing and deleting entities
like courses and registrations.

In order to use this API a secret Token must be created and provided in the
HTTP-Header of every request.

.. warning:: The Orga API is currently in beta. Some specifics may change and as of now
    the creation and management of tokens for the API is limited and not available
    via the frontend.

Available Endpoints
-------------------

All orga droid endpoints are located in the same URL-schema:

``/event/event/<event_id>/droid/<endpoint>``.

Partial Export
++++++++++++++

An orga droid may fetch a partial export of its event under ``droid/partial``.
This is a read-only operation.

The partial export is a JSON file of the same format one may download via the
regular frontend.
