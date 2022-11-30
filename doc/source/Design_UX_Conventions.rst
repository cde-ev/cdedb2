User Experience Conventions
===========================

.. todo:: Add information on notification type semantics


Given Names & Display Name
------------------------------

For each person, the CdEDB allows to store two different forename fields: ``given_names`` and ``display_name`` ("Known as", german: "Rufname").
The former is meant to contain the person's "official" forename(s), whereas the ``display_name`` should be used to give the name, how the person wants to be called by others.
This may be the full given names, only a part of the given names or a completely different nickname.

Due to these possibilities, it is not trivial, where/when to use which of these two fields.
The following shall give a guideline on this topic, based on our discussion on `Issue #2005 <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues/2005#issuecomment-28855>`_.
To apply this logic in the web template and frontend code, there is the :func:`cdedb.frontend.common.make_persona_name` helper function resp. the ``persona_name()`` macro in the ``util.tmpl`` template.

* | *if* a person is addressed in a legal context (including postal addresses)
  | *then* use only the given names: "{given_names} {family_name}"
  | examples: letter address fields, assembly attendee list
  | → ``util.persona_name(persona, only_given_names=True)``
* | *else if* a user is directly addressed
  | *then* use only the display name
  | examples: salutation in a event participation letter, login info in the main navigation bar
  | → ``util.persona_name(persona, only_display_name=True, with_family_name=False)``
* | *else if* a person's name is presented to other users *and* the display name shall be emphasized
  | *then*

  * | *if* the display name is part of the given names (or equal)
    | *then* only show the display name
  * | *else* show the display name and the given names (typically: "{display_name}\\n{given_names} {family_name}")

  example: paper nametags for events

* | *else if* a person's name is presented to other users and we explicitly want to display all their names (as on a business card)
  | *then*

  * | *if* the display name is equal to the given names
    | *then* only show the given names
  * | *else if* the display name is part of the given names
    | *then* only show the given names, but emphasise the display name within the given names (e.g. via italic font)
  * | *else* show the given names and the display name in parentheses: "{given_names} ({display_name"}) {family_name}"

  | example: user profile page, orga realm (if not in lists)
  | → ``util.persona_name(persona, given_and_display_names=True, with_titles=True)``
* | *else*

  * | *if* the display name is part of the given names (or equal)
    | *then* only show the display name
  * | *else* only show the given names

  | example: event participation lists, email "To" headers, mailinglist subscriber lists
  | → ``util.persona_name(persona)``


Buttons
-------

The styling of our buttons follows the semantics of the button.
This should make it more predictable what a given button does, without the use of overlong titles.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", and "MAY" in this document
follow the conventions of [RFC2119].

Colours & Icons
^^^^^^^^^^^^^^^

- effective actions

    - "have a persistent effect"
    - are divided into four subtypes:

        - constructive

            - SHOULD be dark blue (btn-primary)
            - the icon SHOULD be a checkmark
            - least one of both MUST be true

        - rather destructive (e.g. archiving of event)

            - MUST be red (btn-danger)

        - reference-destructive

            - SHOULD have the minus icon

        - really destructive (deletes data)

            - MUST be red (btn-danger)
            - SHOULD have the trash-alt or fire icon ("fire" escalation of "trash", deletes "larger" entities)

- progressive actions

    - "lead to a page to make a persistent effect"
    - if something will be edited

        - SHOULD be yellow/orange (btn-warning)

    - if something is created

        - SHOULD be green (btn-success)

    - exception: when submitting a search form

        - SHOULD be dark blue (btn-primary)
        - SHOULD have the search icon

    - if button submits information to the next step in a wizard, the icon "chevron-right" SHOULD be used

- non actions (links)

    - "have no effect"
    - are dived into three subtypes:

        - going higher (backwards)

            - SHOULD be light white (btn-default)
            - SHOULD have

                - fa-times icon (cancel = form reset)
                - chevron-left icon

        - keeping page (e.g. Download buttons) or going to similar page

            - including dynamic changes to selected items
            - SHOULD be white (btn-default)

        - going to similar page, while considering form inputs on local page (e.g. link to filtered list by selection)

            - SHOULD be light blue (btn-info)

        - going deeper (forwards)

            - including links to documentation
            - SHOULD be light blue (btn-info)

    - may be dark blue if icon indicated read only


Button Sizes
^^^^^^^^^^^^

* Buttons in the "action toolbar" below the heading MUST be btn-sm
* Buttons in "inline forms" SHOULD be btn-sm
* right-floated Buttons in lists SHOULD be btn-xs
* other Buttons should be normal-sized
