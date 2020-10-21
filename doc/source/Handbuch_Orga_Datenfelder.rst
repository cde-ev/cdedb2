Eigene Datenfelder
==================

Die Datenbank bietet euch die Möglichkeit, eigene Datenfelder anzulegen.
Da die Arbeitsweise und die zu erfassenden Daten stark von Veranstaltung
und Orgateam abhängen, ist das ein extrem mächtiges Werkzeug, um eure eigenen
Workflows in der Datenbank abzubilden.

Konzept
-------

Es gibt drei **Typen** von eigenen Datenfeldern:

* ``Anmeldungsfelder``
* ``Kursfelder``
* ``Unterkunftsfelder``

Der Typ gibt jeweils an, zu welchem Entitätentyp der Datenbank das Feld gehört
(nämlich Anmeldung, Kurs und Unterkunft). Wenn ihr etwa ein Datenfeld *Raum* vom
Typ ``Kursfeld`` erstellt, erhält jeder Kurs einen Speicherplatz (*Raum*), in den
etwa der Ort an dem er stattfindet eingetragen werden kann.

Weiterhin besitzt jedes Feld einen **Datentyp**:

* ``Text``
* ``Ja/Nein``
* ``Zahl``
* ``Dezimalzahl``
* ``Datum``
* ``Datum mit Uhrzeit``

Der Datentyp legt das Format der Daten fest, die in ihm gespeichert werden können.
So kann etwa ein Feld mit Datentyp ``Zahl`` nur Ganzzahlen enthalten, aber keine
Dezimalzahlen oder Buchstaben.

Zuletzt kann ein Feld noch **Optionen** besitzen. Sind Optionen gegeben, kann
im Feld nur eine dieser Optionen ausgewählt und gespeichert werden. Sind dagegen
keine Optionen gegeben, kann im Feld alles gespeichert werden, was sein Datentyp
zulässt. Natürlich müssen auch die Optionen den Datentyp des Feldes respektieren.

Gebrauch
--------

Es gibt verschiedene Möglichkeiten, um Datenfelder zu benutzen:

**Von Orgas füllen lassen**

    Die naheliegenste Möglichkeit ist, das Datenfeld als zusätzliches
    Informationsfeld zu benutzen, das ihr selber befüllt. Dabei könnt ihr über
    die Suchmasken und den Knopf ``Datefeld setzen`` für mehrer eurer
    Suchergebnisse ein Datenfeld setzen (das vermeidet einige Klicks)
    (aktuell für Anmeldungen möglich).
    So könnt ihr etwa für jedes Haus in Kirchheim speichern, auf welchem Hof es
    liegt, oder das Material, das ein Kurs benötigt, in der Datenbank tracken.

**Anmeldung & Fragebogen**

    Die Datenbank bietet euch auch die Möglichkeit, Datenfelder vom Typ ``Anmeldung``
    entweder sofort bei der Anmeldung oder später im sogenannten *Fragebogen* von
    euren Teilnehmern selbst ausfüllen zu lassen.
    Entscheidender Unterschied ist, dass Datenfelder in der Anmeldung
    **obligatorisch** und im Fragebogen **fakultativ** sind.
    So könntet ihr etwa erfassen, wer Akademiekleidung bestellen möchte oder
    einen hohen Schlafbedarf hat.


**Datenbank interne Tools**

    Es gibt ein paar Funktionalitäten, die in die Datenbank integriert sind und
    zu deren Benutzung diese ein Datenfeld benötigen, aus dem sie ihre
    Informationen ziehen können. Hierzu zählt etwa das *Feld für Hauswünsche*,
    das ihr auf der Konfigurationsseite spezifizieren könnt. Der Inhalt dieses
    Feldes wird dann in einem downloadbaren Bastelsatz zur Zimmereinteilung
    bereitgestellt.
    Ebenso funktioniert die Verwaltung der Warteliste über die Datenbank, indem
    ein Feld zugewiesen wird, in dem die Position der Anmeldung auf der
    Warteliste gespeichert wird.

Alle diese Fälle können (und sollten) auch miteinander kombiniert werden.
So ist es etwa Sinnvoll, das Feld für die Hauswünsche direkt bei Anmeldung
abzufragen und dann der Datenbank mitzuteilen, damit diese direkt im Bastelsatz
zur Zimmereinteilung zur Verfügung stehen.
Ebenso ist es ratsam, die Wartelistenposition einer Anmeldung von euch Orgas
eintragen zu lassen und dann der Datenbank bekannt zu machen, damit diese für
euch eine stets aktuelle Warteliste bereitstellen kann.
