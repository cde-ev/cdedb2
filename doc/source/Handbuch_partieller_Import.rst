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
      "CDEDB_EXPORT_EVENT_VERSION": <numeric id>,
      "id": <numeric event id>,
      "kind": "partial",
      "timestamp": <ISO 8601 encoded timestamp>,
      "courses": {<numeric course id stringified>:
                      <dict with course properties>}
      "event": {<event attribute>: <associated value>}
      "lodgements": {<numeric lodgement id stringified>:
                         <dict with lodgement properties>}
      "registrations": {<numeric registration id stringified>:
                            <dict with registration properties>}
  }

Dabei gibt ``CDEDB_EXPORT_EVENT_VERSION`` das verwendete Format an um
Inkonsistenzen zu vermeiden, diese muss der aktuellen Version entsprechen
und kann dem Export entnommen werden. Ebenso wird für das restliche Schema
auf den Export verwiesen.

Der Schlüssel ``event``, sowie der Schlüssel ``persona`` der in jeder
Anmeldung vorhanden ist, dürfen beim Import nicht vorkommen. Sie stellen
Informationen zur Verfügung, die durch den partiellen Import nicht verändert
werden können.

Prinzipiell sind alle Elemente außer ``CDEDB_EXPORT_EVENT_VERSION``, ``id``
``kind`` und ``timestamp`` optional, können also weggelassen werden. Es ist
sogar explizit empfehlenswert nur die für die gewünschte Änderung nötigen
Informationen einzutragen um nicht in Konflikt mit möglicherweise
gleichzeitig stattfindenden manuellen Änderungen anderer Orgas zu
kommen. Das einzige was sich nicht granular ändern lässt sind die
Kurswünsche, hier ersetzt die übermittelte Liste immer die kompletten
Kurswünsche.

Die möglichen Operationen sind wie folgt.

* Aktualisierungen: Um einen Wert zu ändern, schreibt man an die gewünschte
  Stelle den neuen Wert.
* Erstellung: Um einen neuen Eintrag anzulegen (bspw. eine neue Unterkunft)
  wird diese mit einer negativen ID hinzugefügt.
* Löschen: Um einen Eintrag zu löschen wird der entsprechenden ID der Wert
  ``null`` zugewiesen.

Ein Beispiel mit allen möglichen Operationen findet sich am Ende
:ref:`handbuch_partieller_import_beispiel`.

Hinweise
--------

* Ein server-seitig nur schwer abzufangender Fehler ist, wenn eine
  Import-Datei, die die Erstellung von Einträgen enthält mehrfach
  hochgeladen wird. Dies wird versucht zu detektieren, kann aber nicht mit
  Sicherheit abgefangen werden.

  In allen anderen Fällen sollte das mehrmalige Hochladen weitestgehend
  harmlos sein.
* Der partielle Import macht keine Garantien über die Reihenfolge in der die
  Änderungen ausgeführt werden. Es sollte also keine Abhängigkeiten
  innerhalb eines Imports geben.
* Es ist nicht möglich die für die Erstellung von Einträgen angegebenen
  negativen IDs als Referenzen zu benutzen. Nicht nur wegen des
  vorhergehenden Punkts, sondern ganz allgemein.
* Bei der Erstellung von Einträgen müssen die meisten Attribute angegeben
  werden. Da es hier auch kein Konfliktpotential mit gleichzeitigen
  Änderungen gibt, empfiehlt es sich einfach alle anzugeben (möglicherweise
  mit Ausnahme der benutzerdefinierten Felder, da diese immer optional
  sind).

  Außerdem ist es bei der Erstellung einer Anmeldungen erforderlich die
  zugehörige Person mit dem Attribut ``persona_id`` anzugeben.

.. _handbuch_partieller_import_beispiel:
Beispiel
--------

Das folgende Beispiel bearbeitet, löscht und erschafft jeweils einen Eintrag
aus jeder der Kategorien Kurs, Unterkunft und Anmeldung. Die verwendeten
nutzerdefinierten Felder müssen vorher definiert sein.

::

    {
        "CDEDB_EXPORT_EVENT_VERSION": 3,
        "id": 1,
        "kind": "partial",
        "timestamp": "2018-10-21T20:18:43.414427+00:00",
        "courses": {
            "1": {
                "instructors": "Adams und Heinlein"
            },
            "2": null,
            "-1": {
                "segments": {
                    "1": false,
                    "3": true
                },
                "instructors": "The Flash",
                "title": "Blitzkurs",
                "min_size": null,
                "fields": {
                    "room": "Wintergarten"
                },
                "max_size": null,
                "notes": null,
                "shortname": "Blitz",
                "nr": "\u03b6",
                "description": "Ein Lichtstrahl traf uns"
            }
        },
        "lodgements": {
            "1": {
                "fields": {
                    "contamination": "medium"
                }
            },
            "2": null,
            "-1": {
                "reserve": 2,
                "capacity": 12,
                "fields": {
                    "contamination": "none"
                },
                "moniker": "Geheimkabinett",
                "notes": "Einfach den unsichtbaren Schildern folgen."
            }
        },
        "registrations": {
            "1": {
                "orga_notes": "Neueste Geruechte hier einfuegen",
                "tracks": {
                    "1": {
                        "choices": [1, 4, 2]
                    }
                }
            },
            "2": null,
            "-1": {
                "fields": {
                    "lodge": "egal"
                },
                "mixed_lodging": true,
                "orga_notes": null,
                "parts": {
                    "3": {
                        "lodgement_id": 1,
                        "status": 2,
                        "is_reserve": false
                    },
                    "2": {
                        "lodgement_id": null,
                        "status": 1,
                        "is_reserve": false
                    },
                    "1": {
                        "lodgement_id": null,
                        "status": -1,
                        "is_reserve": false
                    }
                },
                "checkin": null,
                "payment": null,
                "list_consent": true,
                "persona_id": 2,
                "notes": null,
                "parental_agreement": true,
                "tracks": {
                    "3": {
                        "course_id": null,
                        "course_instructor": null,
                        "choices": [1, 4, 5]
                    },
                    "2": {
                        "course_id": null,
                        "course_instructor": null,
                        "choices": [5, 4]
                    },
                    "1": {
                        "course_id": null,
                        "course_instructor": null,
                        "choices": [1, 4]
                    }
                }
            }
        }
    }


