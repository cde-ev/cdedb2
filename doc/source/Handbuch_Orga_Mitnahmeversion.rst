Mitnahmeversion
===============

Die Datenbank kann als Offline-Version mittels einer virtuellen Maschine
genutzt werden. Die allgemeine Dokumentation zur Benutzung der virtuellen
Maschine ist unter :doc:`Development_Setup` zu finden.

Aufsetzen
---------

Zunächst müsst ihr eine lokale Instanz der CdEDB aufsetzen. Folgt dazu den
ersten sechs Abschnitten unter :doc:`Development_Setup`.

Als nächstes müsst ihr eure Veranstaltung aus der Datenbank exportieren. Dies
könnt ihr auf der Übersichtsseite eurer Veranstaltung tun.

.. attention:: Sperrt eure Veranstaltung, bevor ihr sie exportiert!
               Alle Änderungen, die nach dem Export von euch oder den TN
               durchgeführt werden, gehen beim späteren re-import in die Online
               Version verloren.

Ihr könnt natürlich auch zu Testzwecken einen Export erstellen und eine
Offline-Version aufsetzen, ohne die Veranstaltung zu sperren.
Außerdem können prinzipiell beliebig viele Mitnahmeversionen erstellt werden.

Kopiert nun die erhaltene JSON-Datei in eure VM und führt das
Initialisierungsskript für die Offline-VM aus::

  /cdedb2/bin/make_offline_vm.py path/to/export.json


.. attention:: Das Ausführen des Skripts wird alle Daten, die bis dahin innerhalb
               der VM angelegt wurden, löschen.

Jetzt könnt ihr die VM zur offline-Arbeit benutzen. Ihr könnt einfach unter
`https://localhost:20443/db/ <https://localhost:20443/db/>`_ per Browser
darauf zugreifen (eventuel müsst ihr ``localhost:20443`` entsprechend
der Konfiguration eurer VM anpassen).
Aus Sicherheitsgründen enthält die offline VM nicht eure richtigen Login-Daten.
Jeder kann sich mit seiner normalen E-Mail Adresse und dem Passwort ``secret``
anmelden (in Wahrheit funktioniert jedes Passwort, aber es hat sich als einfacher
gezeigt, den Leuten zu erzählen das sie ein spezifisches benutzen sollen).

Neue Anmeldungen in der Offline-VM hinzufügen
---------------------------------------------

Die Offline-VM kann neue Anmeldungen entgegennehmen. Nutzt dafür die
folgenden Schritte.

1. Nutzer in Offline-VM anlegen

   Es ist nötig einen Account für die neue Anmeldung anzulegen, auch wenn die
   Person in der Online-Datenbank bereits einen Account besitzt.

   Dies geht unter "Veranstaltungen" > "Nutzer verwalten" > "Nutzer
   anlegen". Erfasst bei Personen die noch keinen Account in der
   Online-Instanz hat am besten gleich alle notwendigen Daten, damit
   dies später nicht für Verzögerungen sorgt.
2. Anmeldung hinzufügen

   Im Punkt "Anmeldungen" eurer Akademie gibt es dafür den Button
   "Teilnehmer hinzufügen"

Dies war der halbwegs offensichtliche Teil. Allerdings ist jetzt vor
dem entsperren der Online-Instanz noch etwas Nacharbeit nötig.

1. Nutzer in Online-Instanz anlegen

   Dieser Schritt ist nur notwendig, wenn der neue Nutzer in der
   Online-Instanz noch nicht existiert.

   Schreibt dazu dem Akademieteam eine Email mit den neuen Daten,
   dieses legt den Nutzer dann für euch an und teilt euch dann die ID
   des neuen Accounts mit.
2. IDs synchronisieren

   Damit die Anmeldung zugeordnet werden kann müsst in der Offline-VM
   die Anmeldung bearbeiten und in das Feld "Online CdEDB-ID" die ID
   des bereits existierenden oder vorherigen Schritt angelegten
   Accounts eintragen.
3. Online-Instanz entsperren

   Nun funktioniert das Entsperren der Online-Instanz mit dem üblichen
   Workflow.

Re-Import in die Online-Instanz
-------------------------------

Solltet ihr in der Offline-VM neue Anmeldungen angelegt haben, so müsst ihr
zunächst die oben beschriebenen Vorbereitungen treffen.

Ist dies erledigt, könnt ihr die Daten aus der Offline-VM wieder in die Online
Datenbank importieren. Dazu laded ihr (wie beim erstellen der offline VM) von
der Veranstaltungsübersichtsseite der **Offline-VM** den Export herunter.
Diese JSON-Datei könnt ihr nun wieder in der **Online-Instanz** auf der
Startseite eurer Veranstaltung hochladen.

After the event you export the data from the offline instance the same way
you exported the online instance, receiving a JSON-file with the data of the
offline instance. This file you upload into the online instance thereby
unlocking the event via the corresponding button on the event overview
page. This overwrites all data of your event in the online instance with
data from the offline VM (potentially deleting things).

.. attention:: Das Hochladen des Offline-VM exports überschreibt alle Daten
               eurer Veranstaltung in der Online-Instanz. Dabei gehen alle
               Änderungen, die nach dem Export aus der Online-Instanz getätigt
               wurden, verloren.
