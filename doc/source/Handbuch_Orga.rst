Orgas
=====

.. toctree::
   :maxdepth: 1
   :hidden:

   Handbuch_Orga_Datenfelder
   Handbuch_Orga_Beitragsmodifikator
   Handbuch_Orga_Warteliste
   Handbuch_Orga_Mitnahmeversion
   Handbuch_Orga_Template-Renderer
   Handbuch_Orga_Partieller-Import
   Handbuch_Orga_Fragebogenimport
   Handbuch_Orga_EventKeeper

.. hint:: Weiter Informationen zur Organisation von Veranstaltungen findet ihr im
          `Akademieleitfaden <https://wiki.cde-ev.de/dokuwiki/doku.php?id=akademieleitfaden:allgemeines:technik:db>`_.

.. todo:: Referenz Datenmodell von Veranstaltungsteilen, Kursschienen und Datenfeldern,
          Referenz Überweisungen eintragen, Referenz Kurszuteilungsmagie, Mailingliste

Eure Veranstaltung wird von den Administratoren (das :doc:`Handbuch_Akademieteam`)
angelegt und kann danach von euch weitestgehend über das Webinterface konfiguriert
werden.

Jede Veranstaltung besteht aus einem oder mehreren Teilen. Auch wenn eure
Veranstaltung ungeteilt ist, benötigt die DB einen (einzigen) expliziten
Veranstaltungsteil, was aber nur minimalen Zusatzaufwand verursachen sollte.

Eine Veranstaltung kann Kurse haben. Um Kurse anzulegen müsst ihr vorher
eine oder mehrere Kursschienen anlegen und jeweils einem Veranstaltungsteil
zuordnen. Sobald ihr das getan habt, ist eure Veranstaltung eine
Veranstaltung mit Kursen und es wird beispielsweise in der Anmeldung
automatisch eine Kurswahl abgefragt.

Sobald die Veranstaltung bereit ist, könnt ihr die Anmeldung
starten. Beachtet, dass ohne ein konfiguriertes Minderjährigenformular eine
Anmeldung nur für Volljährige möglich ist. Die Anmeldemaske fragt nur die
minimal notwendigen Daten ab, alle zusätzlichen Informationen müsst (und
könnt!) ihr selber über sogenannte Datenfelder erfassen, die ihr direkt bei der
Anmeldung oder im Nachhinein per sogenanntem Fragebogen ausfüllen lassen könnt.

Zur Verwaltung der Anmeldungen gibt es eine recht ausgefuchste Abfragemaske,
mit der so ziemlich jede denkbare Anfrage zufriedenstellend beantwortet
werden können sollte. Ähnliche Seiten gibt es auch für alles rund um Kurse
und Unterkünfte.

Beachtet, das das **Dokuteam** euch vor, nach und vor allem während eurer
Veranstaltung kontaktieren wird, um Daten aus der Datenbank zu erhalten, die
für die Erstellung der Doku benötigt werden.
Genaueres hierzu findet ihr unter :doc:`Handbuch_Akademieteam_Dokuteam`.
