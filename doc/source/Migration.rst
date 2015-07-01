Migration
=========

This file describes the migration plan from DB version 1 to version 2, so
that we hopefully detect possible bumps beforehand. After the migration this
is probably only of historical value.

Basic plan
----------

After all preparations are completed, look for a nice weekend at a time
which meets the following criteria:

* no membership fee actions are under way,
* no events are actively managed in the DB,
* no assemblies are taking place.

The following months should fulfill all wishes:

* February,
* September,
* October.

Then we tidy up the v1 instance with the following steps:

* resolve all outstanding member dataset changes.

Now we take the v1 instance offline and make an SQL dump. We now feed the
data into the prepared v2 instance (according to the plan outlined below)
and take it online. Now it's time to test if anything major has gone wrong
due to reality being different from the testing environment, if so we take
the v2 instance offline and v1 online again. If not we restrict login in the
v1 instance to privileged accounts and put it online under a new URL, so
that it may be consulted for reference.

Detailed plan by realm
----------------------

This is divided by realm and lists the migration strategy for functionality
and date.  Regarding functionality only changed pieces are mentioned.

Core
^^^^

This incorporates functionality which was duplicated in v1 between cde and
event components.

Functionality
"""""""""""""

* The IDs have a new format to distinguish them from the old ones (the check
  digit is a letter now).

Data
""""

Use SQL-script. This should preserve all member IDs. However everybody will
have to reset their password.

CdE
^^^

Functionality
"""""""""""""

* TODO

Data
""""

Use SQL-script.

Event
^^^^^

Functionality
"""""""""""""

* Registration formular and mail are less flexible. This is offset by gains
  in the questionnaire.
* Housegroups are gone. As are statistics about vegetarians. Use custom
  queries instead.
* The mtime triggers are gone. Replaced by the logging facility.
* Bus stuff is gone. Use fields.
* TODO: UEberweisungen

Data
""""

No migration for events organized via DB. Past events are migrated in a
semi-automatic way via SQL script -- the catch being, that they gained a
``tempus`` column for ordering; however since this needs only to be acurate
within a month or so it should be easy to fill in.

Mailinglists
^^^^^^^^^^^^

Functionality
"""""""""""""

* Only accounts can be subscribed, no (anonymous) email adresses. Solution:
  create accounts.

Data
""""

Manual migration (assisted by SQL dump). This should be done in 1--2 hours
(faster than engineering a more sophisticated solution).

Assembly
^^^^^^^^

Functionality
"""""""""""""

TODO

Data
""""

No migration.

Files
^^^^^

Functionality
"""""""""""""

Moved to the assembly realm.

Data
""""

Manual migration, half an hour tops.

I25+
^^^^

Functionality
"""""""""""""

Moved to cde realm.

Data
""""

See cde realm.
