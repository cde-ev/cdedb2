Wartelistenverwaltung
=====================

Um die Organisation einer Warteliste eurer Veranstaltung zu erleichtern, bietet
die Datenbank eine Möglichkeit, die Reihenfolge der Personen auf der Warteliste
zu speichern und die Warteliste den Orgas (und den Personen ihren Platz darauf)
anzuzeigen.

Warteliste einrichten
---------------------

Zunächst müsst ihr ein :doc:`Handbuch_Orga_Datenfelder` anlegen, in dem der
Platz auf der Warteliste für jede Anmeldung gespeichert werden kann.
Das Feld muss den Typ ``Anmeldungsfeld`` und den Datentyp ``Zahl`` besitzen.

Nach Anlegen des Feldes müsst ihr das Datenfeld zur Wartelistenverwaltung
zuweisen. Dies geschieht auf der **Veranstaltungsteile** Seite.
Es kann für jeden Veranstaltungsteil ein eigenes Feld spezifiziert werden, in
dem die Wartelistenposition der Anmeldung für diesen Teil gespeichert wird
(natürlich kann auch, falls das in eurem Fall sinnvoll ist, immer das gleiche
oder gar kein Feld angegeben werden).

.. hint:: Sobald ein Wartelistenfeld für einen Veranstaltungsteil angegeben wurde,
          sehen die Teilnehmer ihre Position auf der Warteliste. Das Zuweisen
          des Datenfeldes als Wartelistenfeld kann auch zu einem beliebigen
          späteren Zeitpunkt vorgenommen werden.

Warteliste füllen
-----------------

Nachdem ein Datenfeld angelegt und der Wartelistenverwaltung zugewiesen wurde,
könnt ihr es mit Inhalt füllen.
Ihr könnt für jede Anmeldung eine Position auf der Warteliste eintragen. Dabei
ist es egal, ob die Anmeldung tatsächlich gerade den Status *Warteliste* hat.

Die **Position** einer Anmeldung auf der Warteliste wird wie folgt berechnet:
Alle Anmeldungen mit Status *Warteliste* werden aufsteigend nach dem Inhalt
des Wartelistenfeldes sortiert. Die Position einer Anmeldung in dieser Auflistung
ist ihre Position auf der Warteliste.

Dies hat mehrere Vorteile:

* Die Nummerierung muss bei keinem bestimmten Wert beginnen.
* Die Nummern im Datenfeld müssen nicht fortlaufend sein, es zählt nur die
  relative Reihenfolge.
  Damit können etwa Anmeldungen in die Warteliste "eingeschoben" werden, ohne
  bei allen nachfolgenden Anmeldungen die Zahl um eins zu erhöhen.
* Nach dem Nachrücken einer Anmeldung von der Warteliste muss der Inhalt des
  Datenfeldes dieser Anmeldung nicht geändert werden.

Es gibt für jeden Veranstaltungsteil eine Standardabfrage zur Wartelistensortierung,
diese findet ihr auf der **Anmeldungen** Seite.
Ist kein Wartelistenfeld für einen Veranstaltungsteil gesetzt, sortiert diese
Abfrage die Warteliste nach Anmeldezeitpunkt.

.. hint:: Die Platzierung auf der Warteliste startet bei 1, nicht bei 0.
