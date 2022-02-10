EventKeeper
===========

EventKeeper (nach ``etckeeper``) ist eine Git-basierte Versionierung von Veranstaltungen
auf Basis des partiellen Exports.

.. warning::
  EventKeeper befindet sich noch in der Testphase. Insbesondere der Tatsache, dass
  in allen hier aufgeführten Szenarien tatsächlich Commits durchgeführt werden, sollte
  nicht allzu viel Vertrauen entgegengebracht werden.

Architektur
-----------
Zu jeder Veranstaltung existiert ein Git-Repositorium, das als einzige Datei den
partiellen Export der Veranstaltung enthält. In dieses Repositorium werden einmal pro
Stunde Snapshots vorgenommen, sofern eine Änderung stattgefunden hat. Darüber hinaus
werden vor und teils nach größeren Änderungen manuelle Snapshots vorgenommen.
Dadurch lassen sich diese Änderungen im Nachhinein über das Git nachvollziehen.

Manuelle Snapshots werden angelegt:

* Vor der Löschung eines Teilnehmers, eines Kurses oder einer Unterkunft
* Vor Änderung oder Löschung von Datenfeldern
* Vor und nach Multi-Edit
* Vor und nach einem partiellen Import
* Vor und nach Entsperrung einer Veranstaltung
* Nach einer Änderung des Datenbankschemas für Veranstaltungen

Dabei wird jeweils der letzte Snapshot, der zu einer Änderung gehört, auch dann
gespeichert, wenn sich der partielle Export dadurch nicht verändert hat, um eine
Trennung der Aktion von anderen Änderungen im ähnlichen Zeitraum zu ermöglichen.

Mit der Archivierung oder Löschung einer Veranstaltung wird auch sein EventKeeper
gelöscht. Dadurch soll diversen Fristen zur Löschung personenbezogener Daten
Rechnung getragen werden.

Diese Architektur zeichnet sich insbesondere dadurch aus, dass sie diverse
datenbanktheoretische Komplexitäten umschifft, die eine Versionierung in der
Datenbank mit sich bringen würde. Darüber hinaus besteht über den
:doc:`Partiellen Import <Handbuch_Orga_Partieller-Import>` eine einfache Möglichkeit,
eine alte Version der Veranstaltung aus dem EventKeeper in weiten Teilen
wiederherzustellen.

Verwendung und Zugriff
----------------------
Auf das Git kann durch Orgas und Veranstaltungs-Administrationen einfach mithilfe
der Zugangsdaten für die Datenbank und ``git pull`` zugegriffen werden.::

    git pull https://db2.cde-ev.de/git/event_keeper/<event_id>/

Dies vereinfach auch das Beziehen eines aktuellen partiellen Exports zur Verwendung in
externen Tools, das nun rein über die Kommandozeile geschenen kann.
Ein partieller Import über ``git push`` kann hingegen nicht durchgeführt werden.
