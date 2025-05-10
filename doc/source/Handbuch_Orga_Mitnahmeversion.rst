Mitnahmeversion
===============

Die Datenbank kann als Offline-Instanz mittels einer virtuellen Maschine
genutzt werden. Dafür wird das gleiche Setup wie für die Entwicklungs-VM
genutzt, beschrieben unter :doc:`Development_Environment_Setup_VM`.

.. attention:: Achtung, der in der Vergangenheit unterstützte vollständige
               Re-Import aus einer Offline-Instanz existiert nicht mehr.
               Ein paar weitere Details hierzu findet ihr ganz unten auf dieser Seite.

Aufsetzen
---------

Zunächst müsst ihr eine lokale Instanz der CdEDB aufsetzen. Folgt dazu den
Anweisungen unter :doc:`Development_Environment_Setup_VM`.

Als nächstes müsst ihr eure Veranstaltung aus der Datenbank exportieren.
Dazu ladet ihr auf der "Downloads"-Seite den "Export der Veranstaltung" herunter.

.. attention:: Sperrt eure Veranstaltung, wenn ihr eine Offline-Instanz nutzen wollt!
               Ansonsten werdet ihr Probleme auf Grund von abweichenden Datensätzen bekommen.

Ihr könnt natürlich auch zu Testzwecken einen Export erstellen und eine
Offline-Instanz aufsetzen, ohne die Veranstaltung zu sperren.
Außerdem können prinzipiell beliebig viele Mitnahmeversionen erstellt werden.

Kopiert nun die erhaltene JSON-Datei in eure VM und führt das
Initialisierungsskript für die Offline-Instanz aus::

  /cdedb2/bin/make_offline_vm.py path/to/export.json


.. attention:: Das Ausführen des Skripts wird alle Daten, die bis dahin innerhalb
               der VM angelegt wurden, löschen.

Das Skript fragt euch ob ihr bei dieser Gelegenheit optional zusätzliche Schriftarten
installieren möchtet. Dies kann von Nutzen sein, wenn ihr mit der Offline-Instanz den
Template-Renderer verwenden möchtet. Die Installation lässt sich im Zweifel auch
problemlos später nachholen.

Jetzt könnt ihr die VM zur offline-Arbeit benutzen. Ihr könnt einfach unter
`https://localhost:20443/db/ <https://localhost:20443/db/>`_ per Browser
darauf zugreifen (eventuel müsst ihr ``localhost:20443`` entsprechend
der Konfiguration eurer VM anpassen).

Da die Offline-Instanz über ein selbst-signierters SSL-Zertifikat verfügt werdet ihr
einen Hinweis sehen, dass die Verbindung nicht sicher ist. Ihr könnt diesen
ausnahmsweise(!) ignorieren oder eine Ausnahme für dieses Zertifikat hinzufügen.

Aus Sicherheitsgründen enthält die offline VM nicht eure richtigen Login-Daten.
Jeder kann sich mit seiner normalen E-Mail Adresse und dem Passwort ``secret``
anmelden (in Wahrheit funktioniert jedes Passwort, aber es hat sich als einfacher
gezeigt, den Leuten zu erzählen das sie ein spezifisches benutzen sollen).

Neue Anmeldungen in der Offline-Instanz hinzufügen
--------------------------------------------------

Die Offline-Instanz kann neue Anmeldungen entgegennehmen. Nutzt dafür die
folgenden Schritte.

1. Nutzer in Offline-Instanz anlegen

   Es ist in aller Regel nötig einen Account für die neue Anmeldung anzulegen,
   auch wenn die Person in der Online-Datenbank bereits einen Account besitzt.

   Dies geht unter "Veranstaltungen" > "Nutzer verwalten" > "Nutzer
   anlegen". Erfasst bei Personen die noch keinen Account in der
   Online-Instanz hat am besten gleich alle notwendigen Daten, damit
   dies später nicht für Verzögerungen sorgt.
2. Anmeldung hinzufügen

   Im Punkt "Anmeldungen" eurer Akademie gibt es dafür den Button
   "Teilnehmer hinzufügen"

Re-Import in die Online-Instanz
-------------------------------

Der vollständige Re-Import der Daten aus eurer Offline-Instanz in die Online-Instanz
wurde abgeschafft. Ihr könnt die meisten Dinge (Neue oder geänderte Anmeldungen,
Kurse und Unterkünfte, sowie Kurs- und Zimmereinteilungen) aber über den partiellen
Import in die Online-Instanz laden.

Mehr Infos zum partiellen Import findet ihr unter :doc:`Handbuch_Orga_Partieller-Import`.
