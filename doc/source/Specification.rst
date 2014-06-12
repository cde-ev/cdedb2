Specification
=============

This page aggregates the thoughts about design specifications. This is
mostly a concentrate of emails sent by users. This is somewhat competing
with the design sections in the introduction, but those focus on the
developer perspective of things. All points should provide a source, so we
can ask questions in case of confusion.

Core realm
----------

* Explicit log out. (Sonja Kupfer, Jost Migenda)
* Try to be smart about the equality of @googlemail.com and
  @gmail.com. Note: This is probably infeasible. (Cornelia May)
* Allow single-sign-on. This probably means putting the account information
  (currently residing in the SQL-table core.personas) into an LDAP. (Dominik
  Brodowski)

CdE realm
---------

* Implement quota statistics, to monitor accesses. (Markus Oehme)
* Keep a trail of all changes to the member database and require approval
  for sensitive changes (that is to names and birth dates). (Markus Oehme,
  David Lorch)
* Implement a choice to allow BuB to view one's data. (Volker Brandt)
* Implement trial membership. This is granted to everybody who participated
  in an official academy for the first time and lasts for one
  semester. (David Lorch)

ML realm
--------

* Integrate special cases in a sane manner. That is CdE-all and
  Aktivenforum. (Markus Oehme)

Assembly realm
--------------

* Implement Condorcet voting. (Markus Oehme)

Event realm
-----------

* Allow flexible queries with powerful sorting on participants. Example:
  List all participants who chose a specific course sorted by
  first/second/third choice. Note: This may need reformulation to be
  feasible. (Sonja Kupfer)
* Make email generation configurable. Example: Does the registration of a
  new participant for an event cause an email to the organizers? (Cornelia
  May)
* Implement split events. (Jost Migenda)
* Store information for which course a participant is instructor (not only,
  that the participant is a course instructor). (Gabriel Guckenbiehl)
* Implement academy configuration in a sane manner. The legacy
  implementation is quite a mess with multiple configuration files for the
  same thing. Best case would be an online configurable variant (note: this
  is hard). (David Lorch)
* Allow query for participants coming from the same academy as a given
  participant. This is relevant for distribution of participants into
  rooms. (David Lorch)
* Archive academies after some time. Keep course descriptions and general
  information available, but delete superflous remainder. (David Lorch)
* Implement polling the course instructors for account information. This
  should allow easy interaction with the scripts of the accountant. (David
  Lorch)
* Allow sorting of lists by different criteria (given name, family name,
  etc.). Provide filters for minors (e.g. for name tag creation). (Gabriel
  Guckenbiehl)

General thoughts
----------------

* If there are numerical identifiers to be processed by a human, provide
  something more meaninful if sensible. Example: In the event organization,
  instead of only listing course numbers, provide short titles of the
  courses. (Simone Rupp)
* No session information in the URL, thus making it possible to share
  links. (Sonja Kupfer)
* User visible documentation where necessary. Antiexample: In the legacy
  event organization, you can select operators (=, >=, IS, ...) for queries
  which are not intuitive and not documented. (Sonja Kupfer)
* Make layout/CSS similar to homepage. (Cornelia May)
* Have finer grained privileges. (David Lorch)
* Some datamining would be cool. Examples may be questions like: age
  distribution/occupation of academy participants; time/academy distribution
  until leaving the CdE. (David Lorch)
* Allow archiving of accounts for the purpose of data economy. Retain only
  names, date of birth, email address, visited events and delete all
  other fields. (David Lorch)
