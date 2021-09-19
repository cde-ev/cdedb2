Fragebogenimport
================

Die CdEDB bietet für Veranstaltungen eine Möglichkeit Abfragen für den Fragebogen,
die Anmeldung sowie selbst definierte Datenfelder zu importieren.

Die Konfiguration der Anmeldung und die Konfiguration des Fragebogens unterscheiden
sich nur sehr wenig und werden daher hier beide als "Fragebogen" bezeichnet.

Dadurch ist es möglich eine vorgefertigte Abfrage für die eigene Veranstaltung
einzurichten, z.B. findet sich im Akademieleitfaden eine vorgefertigte Konfiguration
für eine Kleidungsbestellung der Akademieteilnehmer.

Weitere Optionen
----------------

Beim Import gibt es zwei zusätzliche Konfigurationsoptionen "Fragebogen erweitern" und
"Bereits existierende Datenfelder überspringen".

Ist der Haken bei "Fragebogen erweitern" _nicht_ gesetzt, wird der existierende
Fragebogen durch den zu importierenden Fragebogen ersetzt. Ist der Haken hingegen
gesetzt bleibt der bestehende Fragebogen erhalten und die Elemente aus dem Import
werden hinten an den existierenden Fragebogen angehängt.

Es darf bei jeder Veranstaltung nur ein Datenfeld mit demselben Namen geben. Existiert
bereits ein Datenfeld mit dem gewünschten Namen kann das neue nicht angelegt werden.
Diese Restriktion gilt auch beim Import, daher schlägt der Import standardmäßig fehl,
wenn ein Feld importiert werden soll, das bereits existiert. Ist dies der Fall sollte
sorgfältig geprüft werden, dass das existierende Feld sich wirklich so verhält wie das
Feld das importiert werden soll. Durch das Setzen des Hakens bei
"Bereits existierende Datenfelder überspringen" werden Felder, die bereits existieren
beim Import einfach ignoriert. Achtung: Es findet kein Vergleich der Felder statt und
es ist möglich, dass das alte Feld in der entsprechenden Abfrage dann nicht so
funktioniert wie gedacht.


Die Import-Datei
----------------

Bei der Import-Datei handelt es sich um eine JSON-Datei, in einem ähnlichen Format wie
der partielle Export. Die Import-Datei darf nur die folgenden Felder enthalten. Es
müssen nicht alle Felder enthalten sein, aber eine leere Datei kann nicht importiert
werden. ::

  {
      "questionnaire": {
          <questionnaire kind stringified>: [
              {
                  <questionnaire row attribute>: <associated value>
              }
          ]
      }
      "fields": {
          <field name>: {
              <field attribute>: <associated value>
          }
      }
  }


Fragebogen
----------

``<questionnaire kind stringified>`` kann dabei entweder
``"QuestionnaireUsages.additional"`` oder ``"1"`` für den zusätzlichen Fragebogen sein,
bzw. ``"QuestionnaireUsages.registration"`` oder ``"2"`` für den Anmeldungs-Fragebogen
sein.

Wenn nur eine der Fragebogenarten angegeben ist, z.B. nur der Anmeldungsfragebogen, wird
der andere nicht verändert, auch nicht wenn der Haken bei "Fragebogen ergänzen" nicht
gesetzt ist. Durch Entfernen des Hakens und das Spezifizieren einer leeren Liste lässt
sich der bestehende Fragebogen löschen.

Die Attribute einer ``questionnaire row`` sind:

* title (str)
* info (str)
* input_size (int)
* readonly (bool)
* default_value (str, int)
* field_name (str)

Das Attribut ``field_name`` darf auf ein bereits vor dem Import existierendes oder ein
in der gleichen Datei importiertes Feld verweisen.


Datenfelder
-----------

Die Attribute eines ``field`` sind:

* kind (str, int)
* association (str, int)
* entries (str[][2] oder null)

Der Wert in ``kind`` muss zu einem der folgenden Datentypen umgewandelt werden können.
Dabei sind jeweils sowohl die str- als auch die int-Darstellung die in den Klammern
stehen erlaubt:

* Text ("FieldDatatypes.str", 1)
* Ja/Nein ("FieldDatatypes.bool", 2)
* Ganzzahl ("FieldDatatypes.int", 3)
* Kommazahl ("FieldDatatypes.float", 4)
* Datum ("FieldDatatypes.date", 5)
* Datum mit Uhrzeit ("FieldDatatypes.datetime", 6)

Der Wert in ``association`` muss einer der folgenden Zuordnungen umgewandelt werden:

* Anmeldungsfeld ("FieldAssociations.registration", 1)
* Kursfeld ("FieldAssociations.course", 2)
* Unterkunftsfeld ("FieldAssociations.lodgement", 3)


Beispiel
--------

Das folgende Beispiel legt eine beispielhafte Konfiguration für eine Abfrage von
Akademiekleidungsbestellungen an.

.. literalinclude:: ../../tests/ancillary_files/questionnaire_import.json
    :language: json
