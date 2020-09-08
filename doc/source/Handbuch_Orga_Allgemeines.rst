Einführung
==========

.. todo:: Refactor

Hier findet ihr allgemeine Hinweise um mittels der Datenbank eine
Veranstaltung zu organisieren.

Einleitung
----------

Die Veranstaltung wird von den Administratoren (Akademieteam) angelegt und
kann danach weitestgehend über das Webinterface konfiguriert werden.

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
könnt!) ihr selber über sogenannte Datenfelder mittels des sogenannten
Fragebogens erfassen. Zuerst werden die Datenfelder über die entsperchende
Konfigurationsseite der Veranstaltung angelegt und über die
Fragebogen-Konfigurationsseite diesem hinzugefügt.

Zur Verwaltung der Anmeldungen gibt es eine recht ausgefuchste Abfragemaske,
mit der so ziemlich jede denkbare Anfrage zufriedenstellend beantwortet
werden können sollte. Eine Ausnahme sind die Kurswahlen, für die es eine
Extraseite gibt.

.. hint:: Weiter Informationen zur Organisation von Veranstaltungen findet ihr im
          `Akademieleitfaden <https://wiki.cde-ev.de/dokuwiki/doku.php?id=akademieleitfaden:allgemeines:technik:db>`_.

Mailingliste
------------

TODO


Template-Renderer
-----------------

Die Mitnahmeversion enthält standardmäßig den
`Template Renderer <https://tracker.cde-ev.de/gitea/orgas/cde_template_renderer_v3>`_
mit dem ihr verschiedenste Dokumente mittels LaTeX aus den
Veranstaltungsdaten erstellen könnt. Für die allgemeine Benutzung des
Template Renderers schaut bei obigem Link nach.

In der Mitnahmeversion findet ihr den Template Renderer im Verzeichnis
``/home/cdedb/cde_template_renderer_v3/``. Es gibt außerdem noch zwei kleine
Arbeitserleichterungen. Das Skript
``/home/cdedb/refresh_template_renderer_data.py`` erneuert den partiellen
Export mit dem der Template Renderer arbeitet mit frischen Daten aus der
lokalen DB der VM. Die fertigen PDF-Dateien könnt ihr dann unter
`https://localhost:20443/render/ <https://localhost:20443/render/>`_
abrufen; dabei müsst ihr möglicherweise ``localhost:20443`` entsprechend
der Konfiguration eurer VM anpassen.

Email-Templates
---------------

Die Templates für die Emails, die von der Datenbank verschickt werden
können auf
:ref:`der Seite mit den Email-Templates <email-templates-for-realm-event>`
eingesehen werden.
