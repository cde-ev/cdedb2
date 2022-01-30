Partieller Import
=================

Dieses Dokument erklärt die partielle Importfunktionalität zur Manipulation
von Veranstaltungen. Da diese recht mächtig ist und somit auch das Potential
besitzt Dinge kaputt zu machen, sollte sie erst benutzt werden, nachdem
diese Seite komplett verstanden wurde.

Grundlegende Funktionsweise
---------------------------

Als Orga wünscht man sich manchmal, dass die Datenbank doch Aufgabe X
übernehmen könnte (bspw. Management der Warteliste), es aber für diese
durchaus programmierbare Arbeit keine Implementation gibt. Für genau diesen
Fall gibt es den partiellen Import. Dieser erlaubt es die Datenmanipulation
mit einem eigenen Skript durchzuführen und die Änderungen dann in die
Datenbank zu importieren.

Der prinzipielle Ablauf ist wie folgt.

1. Auf der Downloads-Seite lädt man einen partiellen Export herunter, der
   den aktuellen Stand der Veranstaltung bereitstellt.
2. Mit einem eigenen Skript erstellt man nun eine JSON Datei, die die
   gewünschten Änderungen codiert.
3. Diese wird dann schlussendlich über die Seite "partieller Import" wieder
   in die Datenbank zurückgespielt. Dies ist ein zweistufiger Prozess, bei
   dem zuerst die durch den Import verursachten Änderungen ermittelt und zur
   Überprüfung angezeigt werden und erst im zweiten Schritt nach einer
   Bestätigung durchgeführt werden.

Dabei können mit dem partiellen Import genau Anmeldungen, Kurse und
Unterkünfte manipuliert werden. Dementsprechend können die fundamentalen
Attribute einer Veranstaltung wie Anmeldungsbeginn, Veranstaltungsteile,
Kursschienen, Datenfelder und Fragebogen nicht bearbeitet werden.

Die Import-Datei
----------------

Bei der Import-Datei handelt es sich um eine JSON-Datei, die im gleichen
Format ist wie der partielle Export minus einige unveränderliche Felder. Im
Wesentlichen enthält der Export die folgenden Elemente::

  {
      "EVENT_SCHEMA_VERSION": [<numeric id>, <numeric id>],
      "id": <numeric event id>,
      "kind": "partial",
      "timestamp": <ISO 8601 encoded timestamp>,
      "summary": <String summarizing your changes>,
      "courses": {<numeric course id stringified>:
                      <dict with course properties>},
      "event": {<event attribute>: <associated value>},
      "lodgement_groups": {<numeric lodgement group id stringified>:
                               <dict with lodgement group properties>},
      "lodgements": {<numeric lodgement id stringified>:
                         <dict with lodgement properties>},
      "registrations": {<numeric registration id stringified>:
                            <dict with registration properties>},
  }

Dabei gibt ``EVENT_SCHEMA_VERSION`` das verwendete Format an um
Inkonsistenzen zu vermeiden, diese muss mit der aktuellen Version kompatibel
sein (siehe :ref:`handbuch-partieller-import-versionierung`) und kann dem
Export entnommen werden. Ebenso wird für das restliche Schema auf den Export
verwiesen.

Der Schlüssel ``event``, sowie der Schlüssel ``persona`` der in jeder
Anmeldung vorhanden ist, dürfen beim Import nicht vorkommen. Sie stellen
Informationen zur Verfügung, die durch den partiellen Import nicht verändert
werden können.

Prinzipiell sind alle Elemente außer ``EVENT_SCHEMA_VERSION``, ``id``
``kind`` und ``timestamp`` optional, können also weggelassen werden. Es ist
sogar explizit empfehlenswert nur die für die gewünschte Änderung nötigen
Informationen einzutragen um nicht in Konflikt mit möglicherweise
gleichzeitig stattfindenden manuellen Änderungen anderer Orgas zu
kommen. Das einzige was sich nicht granular ändern lässt sind die
Kurswünsche, hier ersetzt die übermittelte Liste immer die kompletten
Kurswünsche.

Die Angabe einer ``summary`` ist optional, wird jedoch empfohlen. Sie wird
im Log als Anmerkung zum Logeintrag des Partiellen Imports hinterlegt.
Darüber hinaus erhalten Anmeldungen, die durch den Partiellen Import
bearbeitet wurden, automatisch diese Lognachricht.

Die möglichen Operationen sind wie folgt.

* Aktualisierungen: Um einen Wert zu ändern, schreibt man an die gewünschte
  Stelle den neuen Wert.
* Erstellung: Um einen neuen Eintrag anzulegen (bspw. eine neue Unterkunft)
  wird diese mit einer negativen ID hinzugefügt.
* Löschen: Um einen Eintrag zu löschen wird der entsprechenden ID der Wert
  ``null`` zugewiesen.

Ein Beispiel mit allen möglichen Operationen findet sich am Ende
:ref:`handbuch-partieller-import-beispiel`.

Hinweise
--------

* Ein server-seitig nur schwer abzufangender Fehler ist, wenn eine
  Import-Datei, die die Erstellung von Einträgen enthält, mehrfach
  hochgeladen wird. Dies wird versucht zu detektieren, kann aber nicht mit
  Sicherheit abgefangen werden.

  In allen anderen Fällen sollte das mehrmalige Hochladen weitestgehend
  harmlos sein.
* Die für die Erstellung von Einträgen angegebenen negativen IDs können
  als Referenzen benutzt werden, z.B. um neu erstellte Unterkünfte direkt
  mit Bewohnern zu versehen.
* Bei der Erstellung von Einträgen müssen die meisten Attribute angegeben
  werden. Da es hier auch kein Konfliktpotential mit gleichzeitigen
  Änderungen gibt, empfiehlt es sich einfach alle anzugeben (möglicherweise
  mit Ausnahme der benutzerdefinierten Felder, da diese immer optional
  sind).

  Außerdem ist es bei der Erstellung einer Anmeldungen erforderlich die
  zugehörige Person mit dem Attribut ``persona_id`` anzugeben.
* Sowohl Export als auch Import verwenden für einige Felder wie das
  Geschlecht der Teilnehmer oder den Teilnahmestatus Ganzzahlen, um
  verschiedene Werte darzustellen. Wie diese Ganzzahlen auf die
  entsprechenden Werte abbilden, ist unter :doc:`API_Constants` zu finden.

.. _handbuch-partieller-import-versionierung:

Versionierung
-------------

Der Schlüssel ``EVENT_SCHEMA_VERSION`` ist ein Tupel aus zwei
Integern. Diese werden lexikographisch geordnet, es gilt also::

  (6, 17) < (7, 14) < (7, 19) < (8, 12) < (13, 5)

wobei größere Tupel für neuere Schemaversionen stehen. Die zweite Komponente
wird erhöht, falls eine Änderung vorwärtskompatibel bezüglich des partiellen
Exports und Imports ist. Genauer gesagt können dabei die folgenden
Schemaveränderungen passieren.

* Hinzufügen einer optionalen Spalte (entweder nullbar oder mit Standardwert)
* Hinzufügen einer neuen Tabelle

Wesentlicher Fall ist ein externes Werkzeug, das mit Schemaversion (x, y)
arbeitet, wobei die DB auf Schemaversion (x, y+z) aktualisiert hat. In
diesem Fall kann das Werkzeug einen Export der Version (x, y+z) lesen indem
es die neuen Objekte ignoriert. Außerdem wird die DB einen partiellen Import
mit Schemaversion (x, y) akzeptieren, da die enthaltenen Änderungen
weiterhin gültig sind.

.. _handbuch-partieller-import-beispiel:

Beispiel
--------

Das folgende Beispiel bearbeitet, löscht und erschafft jeweils einen Eintrag
aus jeder der Kategorien Kurs, Unterkunft und Anmeldung. Außerdem wird eine
neue Unterkunftgruppe angelegt. Die verwendeten
nutzerdefinierten Felder müssen vorher definiert sein.

.. literalinclude:: ../../tests/ancillary_files/partial_event_import.json
    :language: json

Changelog
---------

Hier sind die Änderungen gelistet, die in den jeweiligen Inkrementierungen der
Export-Version neu eingeführt wurden. Für jede Version ist angegeben, ob die
Version für den partiellen Import strikt abwärtskompatibel sind oder nicht.

* Version (15, 5): Veranstaltungsteilgruppen sind nun im vollen und im partiellen Export
  enthalten. Sie können derzeit __nicht__ importiert werden und werden, falls vorhanden,
  beim Import ignoriert.
* Version (15, 4): Der gesamte Fragebogen ist jetzt unter ``questionnaire`` im
  partiellen Export enthalten.
* Version (15, 3): Hinzufügen von ``fee_modifiers`` pro Part. Alte Versionsnummer
  entfernt.
* Version (15, 2): Hinzufügen des Feldes ``participant_info`` für die Teilnehmer-Infos.
* Version (15, 1): Umbenennung von ``courses_in_participant_list`` zu
  ``is_course_assignment_visible``.
* Version (14, 1): Umbenennung von ``moniker``. Infolge dessen wurden zwei
  Spalten des ``event``-Schemas umbenannt.
* Version (13, 2): Hinzufügen einer Feldreferenz pro Part, in dem ein Datenfeld
  zum Verwalten einer Warteliste hinterlegt werden kann.
* Version (13, 1): Umstellung von CDEDB_EXPORT_EVENT_VERSION auf
  EVENT_SCHEMA_VERSION.
* Version 12: Umbenennen von ``reserve`` zu ``camping_mat``. Infolge dessen
  wurden drei Spalten des ``event`` Schemas umbenannt.
* Version 11: Für Anmeldungen wird gespeichert, wie viel ein Teilnehmer bezahlen
  soll. Der Fragebogen wurde aufgeteilt in einen Anmeldungs-Teil, der direkt bei
  der eigentlichen Anmeldung abgefragt wird und einen zusätzlichen Teil, der
  dem bisherigen Fragebogen entspricht. Für Veranstaltungsteile können nun
  Beitragsmodifikatoren angelegt werden.
* Version 10 (abwärtskompatibel): Es wird ein Flag ``is_cancelled`` je Event
  eingeführt, mit dem die Absage von Veranstaltungen gekennzeichnet werden
  kann.
* Version 9 (abwärtskompatibel): Es wird eine Dezimalzahl
  ``additional_external_fee`` je Event eingeführt, die den Zusatzbeitrag für
  Externe ergänzt.
* Version 8: Es wird eine Dezimalzahl ``amount_paid`` eingeführt, die
  dokumentiert, wie groß der bereits bezahlte Beitrag ist.
* Version 7: Die Semantik der Kursgrößen wird dahingehend angepasst, dass die
  Kursleiter nicht mehr in die Kursgrößen mit einbezogen werden.
* Version 6: …
