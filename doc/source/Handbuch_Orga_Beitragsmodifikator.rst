Variable Teilnehmerbeiträge (Beitragsmodifikatoren)
===================================================

Für Situationen in denen die Teilnehmer unterschiedlich hohe Teilnehmerbeiträge
bezahlen sollen, gibt es die sog. **Betragsmodifikatoren**.

Jeder Beitragsmodifikator ist mit einem Veranstaltungsteil verbunden, gibt es
mehrere Veranstaltungsteile, müssen ggf. mehrere Beitragsmodifikatoren angelegt
werden.

Ein Beitragsmodifikator wird abhängig von einem Datenfeld mit Typ ``Anmeldungsfeld``
und Datentyp ``Ja/Nein`` automatisch auf den zu zahlenden Teilnahmebeitrag addiert.
Er kann sowohl positiv als auch negativ sein.

Das Einstellen von Beitragsmodifikatoren sei hier anhand von zwei Beispielen
erläutert:

Beispiel 1
----------

Für eine PfingstAkademie sollen reguläre Teilnehmer 90 Euro Beitrag bezahlen.
Kinder unter 13 Jahren kosten beim Feriendorf weniger, daher müssen sie
15 Euro weniger bezahlen. Finanziell besser situierte Teilnehmer sollen die
Möglichkeit bekommen, mit einem "Solidarzusatzbeitrag" in Höhe von 9 Euro den
Verein und zukünftige Veranstaltungen zu unterstützen.

Zunächst müssen dafür zwei :doc:`Handbuch_Orga_Datenfelder` vom Typ
``Anmeldungsfeld`` angelegt werden:

1. * Feldname: "is_child"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

2. * Feldname: "solidarity"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

Anschließend können unter "Veranstaltungsteile" bei dem entsprechenden
Veranstaltungsteil (In diesem Beispiel gibt es nur einen
Veranstaltungsteil) zwei neue Beitragsmodifikatoren angelegt werden.

1. * Veranstaltungsteil: "PfingstAka"
   * Kurzname: "Pfingsten"
   * Beginn: YYYY-MM-DD
   * Ende: YYYY-MM-DD
   * Teilnehmerbeitrag: "90.00"

2. * Beitragsmodifikator: "is_child"
   * Betrag: "-15.00"
   * Verbundenes Feld: "is_child"

3. * Beitragsmodifikator: "solidarity"
   * Betrag: "9.00"
   * Verbundenes Feld: "solidarity"

Zuletzt müssen noch Einträge im Anmeldungsfragebogen angelegt werden, damit
die Teilnehmer bei der Anmeldung angeben können was auf sie zutrifft. Das
geht unter "Anmeldung konfigurieren":

1. * Titel: "Ich bin unter 13 Jahre alt."
   * Abfrage: "is_child"
   * Test: "Kinder zahlen 15 Euro weniger."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

2. * Titel: "Ich möchte den Solidarzusatzbeitrag bezahlen."
   * Abfrage: "solidarity"
   * Test: "Du kannst freiwillig 9 Euro mehr zahlen um zukünftige Veranstaltungen zu unterstützen."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

Speichern und fertig! Während der Anmeldung bekommen alle Teilnehmer nun zwei
Checkboxen angezeigt, wo sie jeweils auswählen können, dass sie unter 13 Jahre
alt sind oder den Solidarzuschlag zahlen wollen. Der gesamte Teilnahmebeitrag
wird automatisch entsprechend berechnet.

Beispiel 2
----------

Bei einer WinterAkademie mit zwei Hälften soll es auf beiden Hälften die Option
geben einen "Solidarzusatzbeitrag" von 8 Euro zu bezahlen. Außerdem können
Teilnehmer der zweiten Hälfte für einen Zusatzbeitrag von 40 Euro als
Silvestergast einen Tag früher anreisen.

Zunächst müssen dafür wieder zwei :doc:`Handbuch_Orga_Datenfelder` vom Typ
``Anmeldungsfeld`` angelegt werden:

1. * Feldname: "solidarity"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

2. * Feldname: "silvester"
   * Datentyp: "Ja/Nein"
   * Optionen: *(Feld leer lassen)*

Unter "Veranstaltungsteile" müssen diesmal zwei Veranstaltungsteile angelegt
werden und insgesamt drei Beitragsmodifikatoren:

1. * Veranstaltungsteil: "Erste Hälfte"
   * Kurzname: "1. H"
   * Beginn: YYYY-MM-DD
   * Ende: YYYY-MM-DD
   * Teilnehmerbeitrag: "231.00"

2. * Beitragsmodifikator: "solidarity"
   * Betrag: "8.00"
   * Verbundenes Feld: "solidarity"

3. * Veranstaltungsteil: "Zweite Hälfte"
   * Kurzname: "2. H"
   * Beginn: YYYY-MM-DD
   * Ende: YYYY-MM-DD
   * Teilnehmerbeitrag: "227.00"

4. * Beitragsmodifikator: "solidarity"
   * Betrag: "8.00"
   * Verbundenes Feld: "solidarity"

5. * Beitragsmodifikator: "silvester"
   * Betrag: "40.00"
   * Verbundenes Feld: "silvester"

*Man beachte, dass zwei Beitragsmodifikatoren mit demselben Feld verknüpft
wurden. Das geht nur, wenn die Modifikatoren mit verschiedenen
Veranstaltungsteilen verknüpft sind.*

Zuletzt müssen unter "Anmeldung konfigurieren" noch Einträge im
Anmeldungsfragebogen angelegt werden, damit die Teilnehmer bei der Anmeldung
angeben können, was auf sie zutrifft:

1. * Titel: "Ich möchte den Solidarzusatzbeitrag bezahlen."
   * Abfrage: "solidarity"
   * Test: "Du kannst freiwillig 8 Euro pro Hälfte mehr zahlen um zukünftige Veranstaltungen zu unterstützen."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein

2. * Titel: "Ich möchte schon Silvester als Gast dabei sein."
   * Abfrage: "silvester"
   * Test: "Bitte wähle diese Option nur dann, wenn Du __nicht__ zur ersten Hälfte kommst."
   * Vorgabewert: *(Feld leer lassen)*
   * Schreibgeschützt: Nein
