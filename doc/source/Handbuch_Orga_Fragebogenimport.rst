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

Der Haken "Fragebogen erweitern" steuert, ob der importierte Fragebogen an einen
möglicherweise bereits existierenden Fragebogen angehängt werden soll, oder ob er
ihn gänzlich ersetzen soll. Mehr Details hier:
:ref:`handbuch-fragebogenimport-fragebogen`

Der Haken "Bereits existierende Datenfelder überspringen" steuert, ob es bei einem
Import von Feldern, die (namentlich) bereits existieren zu einem Fehler kommen soll
oder ob diese Felder beim Import übersprungen werden sollen. Mehr Details hier:
:ref:`handbuch-fragebogenimport-datenfelder`


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


.. _handbuch-fragebogenimport-fragebogen:

Fragebogen
----------

Für ``<questionnaire kind stringified>`` gibt es folende Optionen. Es kann jeweils
entweder die ausgeschriebene Bezeichnung oder der Zahlenwert (als string) verwendet
werden. Da JSON keine Zahlen als Schlüssel für Mappings erlaubt ist es nicht möglich
die Zahl als Zahl für den Schlüssel zu verwenden.

* Eine Abfrage im "zusätzlichen Fragebogen", der nach der Anmeldung freigeschaltet werden
  kann. ("QuestionnaireUsages.additional", "1")
* Eine Abfrage direkt bei der Anmeldung ("QuestionnaireUsages.registration", "2")

Wenn nur eine der Fragebogenarten angegeben ist, z.B. nur der Anmeldungsfragebogen, wird
der andere nicht verändert, auch nicht wenn der Haken bei "Fragebogen ergänzen" nicht
gesetzt ist. Durch Entfernen des Hakens und das Spezifizieren einer leeren Liste lässt
sich der bestehende Fragebogen löschen.

Die Attribute einer ``questionnaire row`` sind:

* title (str)
* info (str)
* input_size (int)
* readonly (bool)
* default_value (str, int oder null)
* field_name (str)

Das Attribut ``field_name`` darf auf ein bereits vor dem Import existierendes oder ein
in der gleichen Datei importiertes Feld verweisen.

Die Definition einer Abfrage nach den Essgewohnheiten der Teilnehmenden könnte z.B. so
aussehen. Diese Abfrage wird erst nach der Anmeldung im zusätzlichen Fragebogen
angezeigt. ::

  "questionnaire": {
      "QuestionnaireUsages.additional": [
          {
              "title": "Essen",
              "info": "Bitte gib hier an, wie Du Dich auf der Akademie ernähren möchtest.",
              "input_size": 0,
              "readonly": false,
              "default_value": null,
              "field_name": "Verpflegung"
          }
      ]
  }

.. _handbuch-fragebogenimport-datenfelder:

Datenfelder
-----------

Die Attribute eines ``field`` sind:

* kind (str oder int)
* association (str oder int)
* entries (str[][2] oder null)

Hinzu kommt der ``field_name``, ein restriktiver Bezeichner (keine Umlaute und nur
einige ausgewählte Sonderzeichen), der als Schlüssel vor dem Eintrag mit den anderen
Attributen steht. Der Name muss pro Veranstaltung einzigartig sein und der Import eines
Feldes mit einem Namen, welcher für diese Veranstaltung berreits vergeben ist führt zu
einem Fehler.

Dieser Fehler kann mit dem Haken "Bereits existierende Felder überspringen" zwar
unterdrückt werden, jedoch ist dies mit Vorsicht zu genießen, da das existierende Feld
anders definiert sein kann als das zu importierende, was wiederum zu Fehlern führen
kann. Soll bspw. ein Feld "Verpflegung" importiert werden, welches den Datentyp Text hat
und im Fragebogen mit einem ``default_value`` von "Vegetarisch" belegt werden soll,
aber es existiert bereits ein Ganzzahl-Feld "Verpflegung", dann schlägt der Import
trotzdem fehl, da der angegebene Vorgabewert für die Abfrage im Fragebogen nicht zum
Datentyp des verknüpften Feldes passt.


Der Wert in ``kind`` muss zu einem der folgenden Datentypen umgewandelt werden können.
Dabei sind jeweils sowohl die str- als auch die int-Darstellung die in den Klammern
stehen erlaubt:

* Text ("FieldDatatypes.str", 1)
* Ja/Nein ("FieldDatatypes.bool", 2)
* Ganzzahl ("FieldDatatypes.int", 3)
* Kommazahl ("FieldDatatypes.float", 4)
* Datum ("FieldDatatypes.date", 5)
* Datum mit Uhrzeit ("FieldDatatypes.datetime", 6)

Der Wert in ``association`` muss zu einer der folgenden Zuordnungen umgewandelt werden:

* Anmeldungsfeld ("FieldAssociations.registration", 1)
* Kursfeld ("FieldAssociations.course", 2)
* Unterkunftsfeld ("FieldAssociations.lodgement", 3)

Für ``entries`` kann entweder ``null`` angegeben werden, dann gibt es keine
Auswhlmöglichkeiten, sondern der Wert kann frei gewählt werden, oder es kann eine Liste
von Optionen angegeben werden. Dafür muss eine Liste von beliebig vielen Listen, die
selbst genau zwei Elemente haben angegeben werden. Das jeweils erste Element muss einem
zulässigen Wert für das jeweilige Datenfeld entsprechen, z.B. einem Datum beim Datentyp
"Datum". Der jeweils zweite Wert ist ein Text, welcher dem Benutzer beim Ausfüllen des
Feldes in einem Drop-Down-Menü für diese Option angezeigt werden soll.

So führt z.B. folgende Felddefinition dazu, dass unter dem Namen "Verpflegung" für jede
Anmeldung festgelegt werden kann ob die Person sich vegetarisch, vegan oder mit
Fleisch ernähren soll.
Dabei wird für Vegatarier die Zahl 1, Veganer die Zahl 2 und Fleischesser die Zahl 3
gespeichert. (Dieses Beispiel ist nicht notwendigerweise sinnvoll, sprechende Werte
zu wählen ist üblicherweise sinnvoller). ::

  "Verpflegung": {
      "kind": "FieldDatatypes.int",
      "association": "FieldAssociations.registration",
      "entries": [
          [1, "Ich möchte mich vegetarisch ernähren."],
          [2, "Ich möchte mich vegan ernähren."],
          [3, "Ich möchte Fleisch essen."]
      ]


Beispiel
--------

Das folgende Beispiel legt eine beispielhafte Konfiguration für eine Abfrage von
Akademiekleidungsbestellungen an.

.. literalinclude:: ../../tests/ancillary_files/questionnaire_import.json
    :language: json
