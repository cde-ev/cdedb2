User Experience Conventions
===========================

.. todo:: Add information on notification type semantics

.. todo:: Add information on button color semantics


Given Names and & Display Name
------------------------------

For each person, the CdEDB allows to store two different forename fields: ``given_names`` and ``display_name`` ("Known as", german: "Rufname").
The former is meant to contain the person's "official" forename(s), whereas the ``display_name`` should be used to give the name, how the person wants to be called by others.
This may be the full given names, only a part of the given names or a completely different nickname.

Due to these possibilities, it is not trivial, where/when to use which of these two fields.
The following shall give a guideline on this topic, based on our discussion on `Issue #2005 <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues/2005#issuecomment-28855>`_.

* | *if* a person is addressed in a legal context (including postal addresses)
  | *then* use only the given names: "{given_names} {family_name}"
  | examples: letter address fields, assembly attendee list
  | (TODO macro?)
* | *else if* a user is directly addressed
  | *then* use only the display name
  | examples: salutation in a event participation letter, login info in the main navigation bar
* | *else if* a person's name is presented to other users *and* the display name shall be emphasized
  | *then*

  * | *if* the display name is part of the given names (or equal)
    | *then* only show the display name
  * | *else* show the display name and the given names (typically: "{display_name}\\n{given_names} {family_name}")

  example: paper nametags for events

* | *else if* a person's name is presented to other users and we don't have space for given names and display name or we don't can or want to do complex formatting
  | *then*

  * | *if* the display name is part of the given names (or equal)
    | *then* only show the display name
  * | *else* only show the given names

  | example: event participation lists, email "To" headers, mailinglist subscriber lists
  | (TODO macro?)
* | *else*

  * | *if* the display name is equal to the given names
    | *then* only show the given names
  * | *else if* the display name is part of the given names
    | *then* only show the given names, but emphasise the display name within the given names (e.g. via italic font)
  * | *else* show the given names and the display name in parentheses: "{given_names} ({display_name"}) {family_name}"

  | example: user profile page, orga realm (where not in lists)
  | (TODO macro)
