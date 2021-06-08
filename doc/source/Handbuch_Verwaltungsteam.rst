Verwaltungsteam
===============

.. todo:: Referenz Genesis Requests, Referenz Past Events,
          Referenz relative admin of mailinglists

Massenaufnahme von Mitgliedern
------------------------------

Alle Teilnehmer einer DSA, DJA o.ä. bekommen vom CdE ein Halbjahr Probemitgliedschaft.
Um die neuen Datenbank Accounts nicht alle händisch über die normale
Accounterstellung anlegen zu müssen, gibt es die Möglichkeit, eine CSV Liste von
Datensätzen hochzuladen und daraus Accounts zu generieren.

Pro Zeile sollen dabei die Daten von genau einer Person angegeben. Die Daten
werden uns von BuB und JGW in folgendem Format zur Verfügung gestellt, das genau
so auch in das Eingabefeld kopiert werden kann::

  "Akademie";"Kurs";"Nachname";"Vorname(n)";"Titel";"Namenszusatz";"Geburtsname";"Geschlecht";"Adresszusatz";"Straße, Nr.";"Postleitzahl";"Ort";"Land";"Telefonnummer";"Mobilnummer";"E-Mail";"Geburtsdatum"

Die Anführungszeichen müssen dabei nur mitgeschrieben werden, wenn der Eintrag
ein Semikolon enthält.
Wenn eine Information zu einer Person nicht vorhanden ist, kann die entsprechende
Spalte auch leer bleiben: ``;;`` oder ``;"";``

Beim Klick auf *Validieren* wird für jede Zeile in der Dateneingabe eine zusätzliche
Eingabemaske generiert. Hier wird eine Kurzzusammenfassung des Datensatzes mit
allen Fehler und Warnungen, die bei der Validierung festgestellt wurden, angezeigt.
Darüber hinaus bietet das *Aktion* Dropdown verschiedene Möglichkeiten, wie im
weiteren Verlauf mit dem Datensatz verfahren werden soll.
Ein Klick auf die Zeilennummer lässt den Cursor zur entsprechenden Zeile der
Texteingabe springen.
Ein Klick auf ein Problem oder eine Warnung lässt den Cursor sogar in das
entsprechende Feld der entsprechenden Zeile springen.

Die Checkboxen "Orga" und "Kursleiter" markieren den Datensatz als Orga bzw Kursleiter
in der entsprechenden vergangenen Veranstaltung.

Die Datensätze können erst angelegt werden, wenn alle Probleme jedes Datensatzes
behoben sind, oder die Aktion des Datensatzes "Eintrag ignorieren" ist.

Aktionen
^^^^^^^^

Die Aktion legt für jeden Datensatz fest, wie im weiteren mit ihm verfahren werden
soll.

Account erstellen
    Legt einen neuen Account mit diesem Datensatz an. Diese Option sollte gewählt
    werden, wenn die Person bisher noch keinen Account in der Datenbank hat
    (insbesondere auch keinen Veranstaltungsaccount).

Eintrag ignorieren
    Überspringt den Datensatz. Warnungen und insbesondere Fehler werden für diesen
    Datensatz ignoriert.

Probemitgliedschaft erneuern
    Das setzt voraus, das eine zum Datensatz gehörende Person bereits in der
    Datenbank existiert (sogn. **Doppelgänger**) und dort den CdE-Realm besitzt.
    Es werden keine Daten aus dem Datensatz auf die bestehende Person übertragen.

Daten übernehmen
    Setzt vorraus, das eine zum Datensatz gehörende Person bereits in der
    Datenbank existiert (sogn. **Doppelgänger**). Bei dieser Person kann es sich
    auch explizit um einen Veranstaltungs- oder Mailinglistennutzer handeln.
    Die im Datensatz vorhandenen Daten werden auf die bestehende Person übertragen,
    müssen dafür aber den gewohnten "Änderungen prüfen" Prozess durchlaufen.


Probemitgliedschaft erneuern und Daten übernehmen
    Kombiniert die obigen Aktionen.


Doppelgänger
^^^^^^^^^^^^

Im Laufe der Validierung prüft die Datenbank, ob zum aktuellen Datensatz
ähnliche Personen bereits existieren. Ist das der Fall, wird eine Liste dieser
Accounts für den Datensatz angezeigt.

Wenn die gefundene Person und der aktuelle Datensatz tatsächlich die gleiche sind,
sollte sie hier ausgewählt werden und entsprechend eine der Aktionen
"Probemitgliedschaft erneuern", "Daten übernehmen" oder
"Probemitgliedschaft erneuern und Daten übernehmen" gewählt werden.

Ist die gefundene Person eine andere als die, die der aktuelle Datensatz beschreibt,
dann sollte sie auch nicht mit dieser zusammengeführt werden. Entsprechend sollte
die Aktion "Account erstellen" gewählt werden.
