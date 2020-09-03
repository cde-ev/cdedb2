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
               Ansonsten können Änderungen, die danach online von den TN gemacht
               werden, verloren gehen.

Ihr könnt natürlich auch zu Testzwecken einen Export erstellen und eine
Offline-Version aufsetzen, ohne die Veranstaltung zu sperren.
Außerdem können prinzipiell beliebig viele Mitnahmeversionen erstellt werden.


Kopiert nun die erhaltene JSON-Datei in eure VM und führt das
Initialisierungsskript für die Offline-VM aus::

  /cdedb2/bin/make_offline_vm.py path/to/export.json


.. todo:: translate

Note that this deletes all data inside the VM before importing the
event.

Now the VM is ready to be used for offline deployment. Access it via
browser. For security reasons the VM does not contain your real login
password. Everyone can log in with their normal username (i.e. their email
address) and the fixed password ``secret`` (actually any password will do,
but I find it easier to tell everybody to use a specific one).

After the event you export the data from the offline instance the same way
you exported the online instance, receiving a JSON-file with the data of the
offline instance. This file you upload into the online instance thereby
unlocking the event via the corresponding button on the event overview
page. This overwrites all data of your event in the online instance with
data from the offline VM (potentially deleting things).

.. note:: You can test the offline deployment to see whether there are any
   pitfalls. Simply do not lock the online instance. You have to dispose of
   your trial offline instance of course.

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
