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
* Make addresses of Vorstand in templates configurable via web
  interface. (Jost Migenda)

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
  new participant for an event cause an email to the orgas? (Cornelia
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

Verwaltung
----------

This section is from direct correspondence with the Verwaltung.

* Searches involving diacritics are somewhat spurious in v1.
* Country values should be a drop down selection in the frontend.
* There exist incomplete datasets (like missing birthday), we have to handle
  them somehow.
* Pages with questionable/unknow use in v1:

  * Fehlerhafte Daten
  * Zugriffsstatistik
  * Login-Fehler -- might be to help answering "I couldn't log in emails",
    but unfit for that purpose.
  * Statistik -- the Vorstand regularly asks for statistics on new members,
    which are not available here.
* Page 'Aktivitätsübersicht' of v1 can be used to access most of the
  day-to-day relevant functionality.
* History (i.e. the changelog) should be migrated, as it is deemed useful.
* The notes entry of a member dataset should contain roughly one line per
  change made to the dataset. This way the history is easily understandable.
* Implementation of trial membership with an extra bit not controversial.
* For mailinglists the responsibilities have to be decided; only one group
  shold be responsible for maintaining them.
* Confirming member dataset changes should offer the possibility/link to go
  to the next unconfirmed change.
* The exPuls usually has two issues per year. One in early autumn after the
  DSA academies are finished and new members have entered. The second at the
  beginning of the year for opening of Pfingst-/Sommerakademie registration.
* The page 'Downloads' in v1 is superseeded by the search functionality in
  v2.
* The form for adding a single member is very seldomly used, because it
  misses the three checkboxes for sending a welcoming email etc.
* The mask for adding multiple members is pretty sophisticated. TODO add
  more specifics after admission phase 2015.
* Bouncing emails currently land at verwaltung@cde-ev.de -- it's somewhat
  questionable whether this is the corret place. (And there seem to be a lot
  of them.)
* The page 'Veranstaltungsdownloads' in v1 is currently used solely for the
  MultiAka. It can be replaced by the possibility to query for multiple
  events at once in the search.
* Adding past events needs some kind of batch interface.

Vorstand
--------

TODO discuss assembly realm

Finanzvorstand
--------------

TODO discuss finance stuff

Notes from DB-KüA on PA15
-------------------------

* automatically mail Vorstand/Akademieteam a copy of minor forms
* mailinglist component was intended to simplify lists local groups

  * allow to automatically unsubscribe no-longer-members
  * vague idea: detect new potential subscribers by city
  * meta-list recieving all mail going to local lists
* telephone and address syntax is a hard problem (currently done by hand;
  maybe not feasibl to automatize)
* wish-list: allow multiple email addresses and postal addresses
* profile pictures should be verified by Verwaltung
