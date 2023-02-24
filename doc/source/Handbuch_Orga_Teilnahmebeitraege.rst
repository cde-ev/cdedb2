Konfiguration von Teilnahmebeiträgen
====================================

Die Teilnahmebeträge, die Teilnehmende von Veranstaltungen entrichten müssen,
sind nicht direkt mit den Veranstaltungsteilen verknüpft, sondern werden über
eine eigene Seite konfiguriert.

Dort können diverse Bedingungen festgelegt werden, unter denen dann bestimmte
Beträge auf den Gesamtbeitrag aufgeschlagen oder davon abgezogen werden sollen.
Hierfür können diverse boolesche Informationen (Ja/Nein) miteinbezogen werden.

Die Teilnehmenden erhalten bevor und nachdem sie ihre Anmeldung abschicken den
für die gültigen Betrag angezeigt; er findet sich auch in der Mail, die sie nach
ihrer Anmeldung erhalten.

Darüber hinaus ist es beim Anlegen von Veranstaltungen und Veranstaltungsteilen
möglich, direkt Teilnahmebeträge anzugeben, zu denen dann entsprechende
Bedingungen erstellt werden.

Operatoren und Tokens
---------------------

Die Formeln werden aus einer beliebigen Anzahl von Tokens aufgebaut, die
untereinander durch Operatoren verknüpft werden. Trifft die Bedingung zu, die
als Formel angegeben ist, wird der entsprechende Betrag, der auch negativ sein
kann, addiert.

Folgende Tokens stehen zur Verfügung, die in den Formeln verknüpft werden können:

* ``True``: immer wahr
* ``False``: immer falsch
* ``field.<Kurzname>``: Ist der Wert des entsprechenden Feldes wahr oder falsch?
* ``part.<Kurzname>``: Ist der Status für den Teil "Offen", "Teilnehmer" oder "Warteliste"?
* ``any_part``: Gilt ein entsprechender Status für mindestens einen Teil der Veranstaltung?
* ``all_parts``: Gilt ein entsprechender Status für alle Teile der Veranstaltung?
* ``is_member``: Ist die Person derzeit CdE-Mitglied?
* ``is_orga``: Ist die Person derzeit Orga der Veranstaltung?

Felder, die hier referenziert werden, dürfen nur im Anmeldungsfragebogen, nicht aber
im Zusätzlichen Fragebogen abgefragt werden.

Folgende Operatoren stehen zur Verfügung, um diese Tokens zu verknüpfen:

* ``not`` (verneint den rechtsstehenden Token)
* ``and`` (Sind beide verknüpfte Tokens wahr?)
* ``or`` (Ist mindestens einer der verknüpften Tokens wahr?)
* ``xor`` (Ist genau einer der verknüpften Tokens wahr?)

Die Verwendung solcher Formeln sei hier anhand eines Beispiels erläutert:

Beispiel 1
----------

Es gibt eine Akademie mit einem einzigen Teil, wo die Teilnahme 90 Euro kosten
soll. Nichtmitglieder müssen 8 Euro mehr zahlen, zudem kann ein
Solidarzusatzbeitrag von 9 Euro bezahlt werden. Orgas sollen nichts zahlen.

* ``part.aka AND NOT is_orga`` => 90 Euro
* ``any_part AND NOT is_member`` => 8 Euro
* ``part.aka AND field.solidarity`` => 9 Euro

die entsprechenden :doc:`Handbuch_Orga_Datenfelder` vom Typ ``Anmeldungsfeld`` müssen zuvor angelegt werden:

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

Beispiel 2
----------

Es gibt eine SommerAkademie mit drei Teilen. Die Teilnahme am mittleren Teil
ostet 230 Euro, während die beiden anderen Teile 215 Euro kosten.

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
* ``any_part field.doku`` => 10 Euro


Die entsprechenden :doc:`Handbuch_Orga_Datenfelder` vom Typ ``Anmeldungsfeld``
müssen zuvor angelegt werden:

1. * Feldname: "one_part"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

2. * Feldname: "not_all_parts"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

3. * Feldname: "doku"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

4. * Feldname: "solidarity"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

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
