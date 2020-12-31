Moderatoren
===========

Viele Mailinglisten, die mit dem CdE assoziert sind, lassen sich direkt über das
Mailinglisten Interface der Datenbank bearbeiten. Große Ausnahmen hiervon sind
die dsa-Liste und Lokalgruppenmailinglisten (aktuell wird am Umzug letzterer
in die DB gearbeitet).

Abonnenten verwalten
--------------------

Alle Notwendigen Informationen hierzu findet ihr direkt auf den Seiten
``Verwaltung`` und ``Erweiterte Verwaltung`` eurer Mailingliste.
Wenn ihr wissen wollt, wie das Datenmodell hinter der Abbonenntenverwaltung
aussieht, schaut euch am Besten die :doc:`Realm_Mailinglist_Management` Seite an.

Nachrichtenmoderation
---------------------

Die Mailinglisten des CdE werden von verschiedener Listensoftware verwaltet
(mit dem Plan das zu vereinheitlichen). Wenn eine eine Nachricht für eine
Liste zu moderieren ist, so bekomment ihr als Moderatoren eine Email in der
steht wie die Moderation erfolgt. Entweder via Webinterface in der DB oder
per Antwort auf die Email.

Privilegierte Moderatoren
-------------------------

Bei manchen Mailinglisten braucht es zusätzliche Berechtigungen in der Datenbank,
um deren Abbonenten verwalten zu können.
Aktuell betrifft das die folgenden Fälle:

* **Veranstaltungslisten**: Zusätzlich Orga der Veranstaltung oder Veranstaltungsadmin
* **Versammlungslisten**: Zusätzlich Teilnehmer der Versammlung, aktives Mitglied oder
  Versammlungsadmin

Näheres zum Problem könnt ihr unter :doc:`Realm_Mailinglist_Privileges` nachlesen.
