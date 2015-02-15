Orga Hints
==========

This page aims to provide orgas with the necessary knowledge to successfully
use the DB for event organization.

Introduction
------------

After the event was created in the DB by the administrators you see several
links to customize your event. Most actions should be pretty straight
forward, the others should be explained here.

Every event consists of one or more parts. For events with only one part
this should introduce only minimal overhead. If your event has courses,
creating them will be one of the first steps.

When your event is ready, you start the registration. Note that without a
configured leagal form for minors no minors wil be able to register. The
registration is minimalistic and all additional information you want to
exchange or store about a registration is delegated to additional per event
fields which are managed through the normal event configuration. There you
can also configure a questionnaire to let the participants fill in these
fields. Note section :ref:`special_fields` about some fields with special
behaviour.

The registrations can be queried with a sophisticated mask which should
allow generation of pretty much any interesting data set. One exception are
course choices which have their own place.

.. _special_fields:

Special fields
--------------

Field names can be arbitrary, but there is one restriction: they should not
have the same name as a column used internally by the DB out of the
following list:
.. the list follows
address, address_supplement, birthday, checkin, country, course_id,
course_instructor, display_name, event_id, family_name, field_data,
foto_consent, gender, given_names, is_active, is_member, location,
lodgement_id, mixed_lodging, mobile, name_supplement, notes, orga_notes,
parental_agreement, payment, persona_id, postal_code, real_persona_id,
registration_id, status, telephone, title, username.

Now there are some fields which enable additional behaviour which could be
useful.

lodge
    This should be a string. It is intended to hold the lodgement wishes of
    the participants (e.g. with who they would like to be accomodated
    together).

may_reserve
    This should be a boolean. It is intended to signal willingness to sleep
    with sleeping pad and bag (and thus take a reserve space in a
    lodgement).

reserve_xxx
    This should be a boolean with one value per part and xxx should be
    replaced with the parts id number. It is intended to contain the
    information whether a participant is actually scheduled to take a
    reserve space in a lodgement.

Mailing lists
-------------

TODO

VM usage
--------

The usage of the VM is documented in its own section :ref:`vm`. Notes on the
offline usage can be found there too.
