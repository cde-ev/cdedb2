Genesis Requests
================

In addition to the admin-initiated workflows for user creation (including batch
admission of cde users), unprivileged users (most prominently, anonymous ones)
can initiate account creation for the realms ml, event and assembly.

Basic Workflow
--------------

On ``core/genesis/request``, each user can provide the data which will be required
to create a persona in a respective realms. Additionally, helpful auxiliary
information is provided, like a reason or an attachment confirming you are
eligible for cde membership. After submitting the form, the case is ``unconfirmed``
and an email is sent to the user to confirm their email address. Afterwards, the case
is set ``to_review``.

Any such case appears on ``core/genesis/list`` and can be modified by the relative
admins of the respective realms, to fix mistakes (potentially after communication with
the user) etc. For cde accounts, a past event and past course can
be provided here -- usually the one that made the account eligible for admission.

.. todo:: what happens when a request is finalized? Doppelgangers?
    ``approved``, ``successful``, ``existing_updated``, ``rejected``

Realm Transitions
-----------------

While persona realm transitions are quite restricted, genesis requests can transition
freely between the allowed realms. In this process, no data is removed even if it
is not applicable for the currently selected realms.
Therefore, it is persistent under idempotent realm transformations like
cde -> ml -> cde.

However, data which is not applicable to the selected realm are hidden in the frontend:
These are only seen at the genesis modification form (and hidden there with javascript).

Instead, it is ignored during the actual account creation.
