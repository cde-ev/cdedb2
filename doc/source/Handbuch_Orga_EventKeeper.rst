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
partiellen Export der Veranstaltung enthält. Einzige Abweichung ist, dass der
``timestamp`` aus dem Export entfernt wird.

In dieses Repositorium werden einmal pro halbe Stunde Snapshots vorgenommen,
sofern eine Änderung stattgefunden hat. Darüber hinaus
werden vor und nach größeren Änderungen weitere Snapshots vorgenommen.
Dadurch lassen sich diese Änderungen im Nachhinein über das Git nachvollziehen.

Weitere Snapshots werden angelegt vor und nach:

* Löschung eines Teilnehmers, eines Kurses oder einer Unterkunft
* Änderung oder Löschung von Datenfeldern
* Multi-Edit
* partiellem Import
* Entsperrung einer Veranstaltung

Zudem gibt es einen Snapshot nach Änderung des Datenbankschemas für Veranstaltungen.

Der Snapshot vor einer Änderung wird nur vorgenommen, wenn der partielle Export sich
seit dem letzten Snapshot verändert hat. Im Gegensatz dazu werden Snapshots nach
Änderungen immer vorgenommen, selbst wenn der partielle Export durch die Änderung nicht
verändert wurde.

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
der Zugangsdaten für die Datenbank zugegriffen werden. Es kann mittels ``git clone``
heruntergeladen und später mit ``git pull`` aktualisiert werden.::

    git clone https://db.cde-ev.de/git/event_keeper/<event_id>/.git/

Dies vereinfacht auch das Beziehen eines aktuellen partiellen Exports zur Verwendung in
externen Tools, das nun rein über die Kommandozeile geschehen kann.
Das Repositorium ist schreibgeschützt; ``git push`` hat somit keinen Effekt.

Nach dem Abschluss aller Organisationstätigkeiten müssen lokale Kopien des EventKeepers
gelöscht werden.
