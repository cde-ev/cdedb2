User Experience Conventions
===========================

.. todo:: Add information on notification type semantics


Given Names, Legal Given Names & Nickname
------------------------------

For each person, the CdEDB allows to store three different forename fields: ``given_names``, ``legal_given_names`` and ``nickname``.
The ``legal_given_names`` contains the person's official forname(s) (which might be a "deadname" which is no longer used by the person),
whereas the ``given_names`` should be used to give the name, how the person wants to be usually called by others.
At last, the ``nickname`` is the name the person wants to use at CdE events.

The ``legal_given_names`` should only be used for legal documents, like invoices, donation recipies or direct debit authorization forms.
The ``nickname`` is only printed on the nametag of CdE events. Additionally, it is visible on the profile and is
displayed to Orgas in addition to the ``given_names``, to allow better recognition.
At every other occasion, the ``given_names`` are used to address or refer to a person.

To apply this logic in the web template and frontend code, there is the :func:`cdedb.frontend.common.make_persona_name` helper function
resp. the ``persona_name()`` macro in the ``util.tmpl`` template.


Buttons
-------

The styling of our buttons follows the semantics of the button.
This should make it more predictable what a given button does, without the use of overlong titles.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", and "MAY" in this document
follow the conventions of [RFC2119].

Colours & Icons
^^^^^^^^^^^^^^^

effective actions
    - "have a persistent effect"
    - are divided into four subtypes:

        #. constructive
            - SHOULD be dark blue (btn-primary)
            - the icon SHOULD be a checkmark
            - least one of both MUST be true

        #. rather destructive (e.g. archiving of event)
            - MUST be red (btn-danger)

        #. reference-destructive
            - SHOULD be reversible using the logs
            - MUST be red (btn-danger)
            - SHOULD have the minus icon

        #. really destructive (deletes data)
            - MUST be red (btn-danger)
            - SHOULD have the trash-alt or fire icon ("fire" escalation of "trash", deletes "larger" entities)

progressive actions
    - "lead to a page to make a persistent effect"

    - *if* something will be **edited**

        - SHOULD be yellow/orange (btn-warning)

    - *if* something is **created**

        - SHOULD be green (btn-success)

    - *if* button submits information to the **next step in a wizard**

        - SHOULD be dark blue (btn-primary)
        - SHOULD have the icon "chevron-right"

    - *exception*: when submitting a **search form**

        - SHOULD be dark blue (btn-primary)
        - SHOULD have the search icon

non actions (links)
    - "have no effect"
    - are dived into three subtypes:

        #. going higher (backwards)
            - SHOULD be light white (btn-default)
            - SHOULD have

                - fa-times icon (cancel = form reset)
                - chevron-left icon

        #. keeping page (e.g. Download buttons) or going to similar page
            - including dynamic changes to selected items
            - SHOULD be white (btn-default)

        #. going to similar page, while considering form inputs on local page (e.g. link to filtered list by selection)
            - SHOULD be light blue (btn-info)

        #. going deeper (forwards)
            - including links to documentation
            - SHOULD be light blue (btn-info)

    - MAY be dark blue if icon indicated read only (e.g. Show vote button upon secret entering)


Button Sizes
^^^^^^^^^^^^

* Buttons in the "action toolbar" below the heading MUST be btn-sm
* Buttons in "inline forms" SHOULD be btn-sm
* right-floated Buttons in lists SHOULD be btn-xs
* other Buttons should be normal-sized
