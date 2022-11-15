Kursschienengruppen
===================

Kursschienengruppen bieten Orgas die Möglichkeit, eine (fast) beliebige Teilmenge
der Kursschienen ihrer Veranstaltung miteinander zu verknüpfen.
Je nach Typ der Gruppe hat dies verschiedene Effekte.

Siehe auch :doc:`Handbuch_Orga_Veranstaltungsteilgruppen`.

Eigenschaften
-------------

Eine Kursschienengruppe besitzt die folgenden Felder

* Titel
* Kurzname
* Notizen
* Sortierung
* Typ
* Verknüpfte Kursschienen

Ähnlich wie bei Kursschienen selbst weden Titel und Kurzname an verschiedenen Stellen
zur Identifikation der Gruppen angezeigt. Es empfielt sich einen nicht allzu
langen Kurznamen zu wählen, um das Layout dieser Seiten nicht zu strapazieren.

Die Notizen werden nur auf der Übersichtsseite angezeigt.

Das Feld Sortierung ist eine Zahl und wird für die Sortierung von
Kursschienengruppen untereinander, aber auch gemeinsam mit einzelnen Kursschienen
verwendet. Gruppen bzw. Schienen mit niedrigerem Sortierungswert werden zuerst
angezeigt.

Titel, Kurzname, Notizen und Sortierung können nach dem Erstellen der Gruppe beliebig
geändert werden. Typ und verknüpfte Kursschienen können nicht geändert werden.

Aktuell können alle Typen von Gruppen zwar auch dann noch hinzugefügt, entfernt und
geändert werden, wenn bereits Anmeldungen existieren, jedoch kann die Existenz von
(inkompatiblen) Kurswahlen das Erstellen von Kurswahlsynchronisierungsgruppen
verhindern.


Typ: Kurswahlsynchronisierung (CCS)
-----------------------------------

Kursschienengruppen vom Typ "Kurswahlsynchronisierung", im folgenden
CCS (course choice sync), haben einschneidende Effekte auf die Anmeldung von
Teilnehmenden, sowie auf das händische Erstellen oder Bearbeiten von Anmeldungen
durch das Orgateam.

Sie dienen dazu, um eine gemeinsame Kurswahl über mehrere Kursschienen durchzuführen,
Ein typischer Anwendungsfall wäre dazu bspw. eine Akademie mit mehreren Standorten,
bei der die Verteilung der Teilnehmer auf die Standorte durch die Kurswahl geschehen soll.
Die Standortpräferenz der Teilnehmenden wird somit durch die Kurswahl zum Ausdruck
gebracht.

Kursschienen können nur dann durch eine CCS-Gruppe mitenander verknüpft werden,
wenn sie alle dieselbe Konfiguration bezüglich minimal erforderlicher und maximal
möglicher Anzahl Kurswahlen haben. Wenn eine CCS-Gruppe bereits besteht, führt eine
Änderung dieser Konfiguration bei einer Kursschiene der Gruppe zur selben Änderung
an allen anderen Schienen der Gruppe.

Bei der Anmeldung bzw. der Erstellung und Bearbeitung von Anmeldungen durch das
Orgateam werden für die synchronisierten Kursschienen  keine Felder für Kurswahlen
und "Ich leite Kurs X" angezeigt. Stattdessen werden diese kombiniert für die
gesamte Gruppe angezeigt.

Die Kurswahlen, die so für eine CCS-Gruppe getätigt werden, werden im Hintergrund
automatisch auf alle vernküpften Kursschienen übertragen, so als hätte die Person
in jeder dieser Schienen exakt dieselbe Kurswahl getroffen. Dabei können innerhalb
einer Gruppe alle Kurse gewählt werden – es sei denn die Person nimmt an keinem
Veranstaltungsteil teil, auf dem der Kurs in irgendeiner Schiene angeboten wird.

Dies sorgt insbesondere dafür, dass in den einzelnen Kursschienen Kurswahlen für
Kurse existieren, die dort eigentlich gar nicht angeboten werden.

**Achtung: Das Löschen einer CCS-Gruppe ist jederzeit möglich, aber das Erstellen
nur dann, wenn noch keine Kurswahlen für die Schiene vorliegen.**

Jede Kursschiene kann maximal in einer CCS-Gruppe sein.
