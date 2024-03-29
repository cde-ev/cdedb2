Teilnahmebeiträge
=================

Für die automatische Berechnung von Teilnahmebeiträgen für Teilnehmende von
Veranstaltungen gibt es die Möglichkeit auch komplizierte Sachverhalte durch
boolsche Funktionen akkurat abzubilden.

Für viele Veranstaltungen ist dies kaum notwendig. Beim Erstellen der
Veranstaltung werden automatisch zwei Teilnahmebeiträge eingerichtet, in Folge
dessen müsst ihr als Orgas lediglich die Höhe des Teilnahmebeitrags und des
Externenzusatzbeitrags -- beides in Absprache mit dem Vorstand -- anpassen.

Sollte eure Veranstaltung jedoch über mehrere Veranstaltungsteile verfügen,
eine Möglichkeit zum freiwillgen Entrichten eines höheren Beitrages oder
eine vergünstigte Teilnahme für Orgas, Vortragende, Kinder etc. vorsehen,
könnt ihr zusätzliche Teilnahmebeiträge anlegen und diese mit selbst
definierten Datenfeldern verknüpfen. Diese Datenfelder solltet ihr dann auch
bei der Anmeldung abfragen.

Wie das alles funktioniert und was mit diesem System möglich ist erfahrt ihr hier.


Bedingte Teilnahmebeiträge
--------------------------

Teilnahmebeträge sind -- anders als früher -- nicht direkt mit Veranstaltungsteilen
verknüpft. Es gibt eine eigene Konfigurations- und Übersichtsseite für
Teilnahmebeiträge, erreichbar über den Knopf "Teilnahmebeiträge" in der
Navigationsleiste der Veranstaltung.

Für jeden Teilnahmebeitrag können hier Titel, Betrag, Bedingung und optional
Notizen konfiguriert werden. Die Bedingung ist eine boolsche Formeln, d.h. eine
Formel, die abhängig von den enthaltenen Variablen, entweder "wahr" oder "falsch"
ist. Falls das Ergebnis "wahr" ist, trifft die Formel zu und der entsprechende
Betrag wird zum Gesamtbetrag addiert. Für Vergünstigungen können negative Beträge
eingestellt werden.

Als Orgas könnt ihr unter "Anmeldung konfigurieren" -> "Anmeldungsvorschau" ansehen,
wie eure Anmeldung konfiguriert ist und erhaltet am Ende der Seite eine detaillierte
Live-Vorschau welche Teilnahmebeiträge bei der gerade eingestellten Anmeldung fällig
werden und warum. (Für diese Vorschau ist JavaScript notwendig).

Teilnehmende erhalten während der Anmeldung ebenfalls eine Live-Vorschau über den
finalen Teilnahmebeitrag, allerdings ohne die detaillierte Tabelle. Nach der Anmeldung
wird ihnen der Teilnahmebeitrag auf der "Meine Anmeldung"-Seite, sowie in der
automatisch nach Anmeldung versandten Mail angezeigt.

Beim Anlegen neuer Veranstaltungsteile wird automatisch ein einfacher
Teilnahmebeitrag für diesen Veranstaltungsteil angelegt, dieser kann ganz
normal angepasst werden.

Die Bedingung
-------------

Operatoren und Tokens
^^^^^^^^^^^^^^^^^^^^^

Die Formeln werden aus einer beliebigen Anzahl von Tokens aufgebaut, die
untereinander durch Operatoren verknüpft werden. Jedes Token ist entweder wahr
oder falsch, Vergleiche wie ``X > 3`` sind nicht möglich.

Trifft die gesamte Bedingung zu, wird der entsprechende Betrag, der auch negativ sein
kann, addiert.

Folgende Tokens stehen zur Verfügung, die in den Formeln verknüpft werden können:

* ``field.<Kurzname>``: Ist der Wert des entsprechenden Feldes wahr oder falsch?
* ``part.<Kurzname>``: Ist der Status für den Teil "Offen", "Teilnehmer" oder "Warteliste"?
* ``any_part``: Gilt ein entsprechender Status für mindestens einen Teil der Veranstaltung?
* ``all_parts``: Gilt ein entsprechender Status für alle Teile der Veranstaltung?
* ``is_member``: Ist die Person derzeit CdE-Mitglied?
* ``is_orga``: Ist die Person derzeit Orga der Veranstaltung?
* ``True``: immer wahr
* ``False``: immer falsch

Felder, die hier referenziert werden, dürfen nur im Anmeldungsfragebogen, nicht aber
im Zusätzlichen Fragebogen abgefragt werden.

Folgende Operatoren stehen zur Verfügung, um diese Tokens zu verknüpfen:

* ``not`` (verneint den rechtsstehenden Token)
* ``and`` (Sind beide verknüpfte Tokens wahr?)
* ``or`` (Ist mindestens einer der verknüpften Tokens wahr?)
* ``xor`` (Ist genau einer der verknüpften Tokens wahr?)

Die Operatoren sind in der Reihenfolge ihrer Präzedenz gelistet, d.h. ``not`` gilt
vor ``and``, ``and`` gilt vor ``or``, ``or`` vor ``xor``, etc.
Zusätzlich ist es möglich runde Klammern (``()``) zu verwenden um die
Auswertungsreihenfolge zu verändern.

Die Verwendung solcher Formeln sei im Folgenden anhand von Beispielen erläutert:

Beispiel 1 (einfache Veranstaltung)
-----------------------------------

Es gibt eine Akademie mit einem einzigen Teil, wo die Teilnahme 90 Euro kosten
soll. Nichtmitglieder müssen 8 Euro mehr zahlen, zudem kann ein
Solidarzusatzbeitrag von 9 Euro bezahlt werden. Orgas sollen nichts zahlen.

* ``part.aka AND NOT is_orga`` => 90 Euro
* ``any_part AND NOT is_member`` => 8 Euro
* ``part.aka AND field.solidarity`` => 9 Euro

die entsprechenden :doc:`eigenen Datenfelder <Handbuch_Orga_Datenfelder>` vom Typ ``Anmeldungsfeld`` müssen zuvor angelegt werden:

1. * Feldname: "solidarity"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

Zudem müssen noch Einträge im Anmeldungsfragebogen angelegt werden, damit
die Teilnehmenden bei der Anmeldung angeben können was auf sie zutrifft. Das
geht unter "Anmeldung konfigurieren":

1. * Titel: "Ich möchte den Solidarzusatzbeitrag bezahlen."
   * Abfrage: "solidarity"
   * Text: "Du kannst freiwillig 9 Euro pro Teil mehr zahlen um zukünftige Veranstaltungen zu unterstützen."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

Beispiel 2 (mehrteilige Veranstaltung)
--------------------------------------

Es gibt eine SommerAkademie mit drei Teilen. Die Teilnahme am mittleren Teil
kostet 230 Euro, während die beiden anderen Teile 215 Euro kosten.

* ``part.A1 OR part.A2 OR part.A3`` => 215 Euro
* ``part.A2`` => 15 Euro

Darüber hinaus wird für die Erstellung einer Anmeldung eine Bearbeitungsgebühr
in Höhe von 5 Euro erhoben.

* ``True`` => 5 Euro

Die Teilnehmenden sollen angeben können, dass sie nur zu einem der Teile oder
nicht zu allen Teilen, für die sie sich angemeldet haben, kommen.

* ``((part.A1 AND part.A2) OR (part.A2 AND part.A3) OR (part.A3 AND part.A1)) AND NOT field.one_part`` => 215 Euro
* ``part.A1 AND part.A2 AND part.A3 AND NOT field.not_all_parts``  => 215 Euro

Hier ist anzumerken, dass diese Formeln fehlertolerant sind: Sie werten auch
dann richtig aus, wenn die Person sowieso nur für die entsprechende Zahl an
Teilen angemeldet ist.

Kinder unter 13 Jahren kosten beim Feriendorf weniger, daher müssen sie
15 Euro weniger bezahlen.

* ``(part.A1 OR part.A2 OR part.A3) AND field.is_child`` => -15 Euro
* ``((part.A1 AND part.A2) OR (part.A2 AND part.A3) OR (part.A3 AND part.A1))``
  ``AND NOT field.one_part AND field.is_child`` => -15 Euro
* ``part.A1 AND part.A2 AND part.A3 AND NOT field.not_all_parts AND field.is_child`` => -15 Euro

Finanziell besser situierte Teilnehmende sollen die Möglichkeit bekommen,
mit einem "Solidarzusatzbeitrag" in Höhe von 9 Euro pro Teil den Verein und
zukünftige Veranstaltungen zu unterstützen.

* ``part.A1 AND field.solidarity`` => 9 Euro
* ``part.A2 AND field.solidarity`` => 9 Euro
* ``part.A3 AND field.solidarity`` => 9 Euro

Nicht-Mitglieder müssen einen Zusatzbeitrag in Höhe des Mitgliedsbeitrags
errichten, wenn sie teilnehmen möchten.
Wer eine Doku möchte, muss 10 Euro extra zahlen.

* ``any_part AND NOT is_member`` => 8 Euro
* ``any_part AND field.doku`` => 10 Euro


Die entsprechenden :doc:`eigenen Datenfelder <Handbuch_Orga_Datenfelder>` vom Typ ``Anmeldungsfeld``
müssen zuvor angelegt werden:

1. * Feldname: "one_part"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

2. * Feldname: "not_all_parts"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

3. * Feldname: "doku"
   * Datentyp: "Ja/Nein"
   * Optionen: "True;Ich möchte eine gedruckte Doku haben (10 Euro) *(neue Zeile)* False;Ich verzichte auf die gedruckte Doku"

4. * Feldname: "solidarity"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

Anmerkung: Durch die Vorgabe von Optionen wird die Abfrage bei der Anmeldung als
Dropdown mit insgesamt drei Einträgen (leer, wahr oder falsch) dargestellt.
Sofern nicht in der Konfiguration anders eingestellt (siehe unten), ist die leere
Option vorausgewählt. Es ist nicht möglich, die Anmeldung abzuschicken, ohne hier
etwas auszuwählen, daher eignet sich diese Variante dazu die Teilnehmenden zu
zwingen eine Entscheidung zu treffen.

Zudem müssen noch Einträge im Anmeldungsfragebogen angelegt werden, damit
die Teilnehmenden bei der Anmeldung angeben können was auf sie zutrifft. Das
geht unter "Anmeldung konfigurieren":

1. * Titel: "Ich möchte nur an einem der Teile, für die ich mich angemeldet habe, teilnehmen."
   * Abfrage: "one_part"
   * Text: *(keiner)*
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

2. * Titel: "Ich möchte nicht an allen Teilen, für die ich mich angemeldet habe, teilnehmen."
   * Abfrage: "not_all_parts"
   * Text: *(keiner)*
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

3. * Titel: "Ich bin unter 13 Jahre alt."
   * Abfrage: "is_child"
   * Text: "Kinder zahlen pro Teil 15 Euro weniger"
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

4. * Titel: "Ich möchte den Solidarzusatzbeitrag bezahlen."
   * Abfrage: "solidarity"
   * Text: "Du kannst freiwillig 9 Euro pro Teil mehr zahlen um zukünftige Veranstaltungen zu unterstützen."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

Speichern und fertig! Während der Anmeldung bekommen alle Teilnehmenden nun die
entsprechenden vier Checkboxen angezeigt.
