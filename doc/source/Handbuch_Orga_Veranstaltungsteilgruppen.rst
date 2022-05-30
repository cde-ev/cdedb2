Veranstaltungsteilgruppen
=========================

Veranstaltungsteilgruppen bieten Orgas die Möglichkeit, eine beliebige Teilmenge
der Veranstaltungsteile ihrer Veranstaltung miteinander zu verknüpfen.
Je nach Typ der Gruppe hat dies verschiedene Effekte, darunter Warnmeldungen
unterschiedlicher Stärken, die bei Verstößen gegen Beschränkungen angezeigt
werden.

Die Stärke der Meldungen ist rein kosmetisch; "Warnungen" werden in gelb
angezeigt, "Fehler" in rot. Im wesentlichen hängt dies davon ab, für wie
wahrscheinlich ein tatsächlicher Fehler im Vergleich zu einem Ausnahmefall
eingestuft wird.

Eigenschaften
-------------

Eine Veranstaltungsteilgruppe besitzt die folgenden Felder:

* Titel
* Kurzname
* Notizen
* Typ
* Verknüpfte Veranstaltungsteile

Ähnlich wie bei Veranstaltungsteilen selbst werden Titel und Kurzname an
verschiedenen Stellen zur Identifikation der Gruppen angezeigt.
Es empfiehlt sich einen kurzen Kurznamen zu wählen, um das Layout dieser Seiten
nicht zu strapazieren.

Die Notizen werden nur auf der Übersichtsseite angezeigt.

Titel, Kurzname und Notizen können nach dem Erstellen der Teilgruppe beliebig
verändert werden. Typ und verknüpfte Veranstaltungsteile können nicht geändert
werden.

Aktuell können alle Typen von Gruppen beliebig hinzugefügt, entfernt und
geändert werden, auch wenn bereits Anmeldungen existieren.


Typ: Statistik
--------------

Veranstaltungsteilgruppen vom Typ "Statistik" sind die einfachste Form der
Veranstaltungsteilgruppen. Sie haben keinerlei direkten Effekt.

Stattdessen wird für jede entsprechende Gruppe eine Spalte in den Tabellen auf
der "Statistik"-Seite eingefügt, die die entsprechenden Veranstaltungsteile
und Kursschienen zusammenfasst, sofern es mehr als einen Veranstaltungsteil
bzw. mehr als eine Kursschiene in der Gruppe gibt.

Außerdem werden entsprechende Spalten in den Kurs-, Unterkunfts- und
Anmeldungssuchen eingefügt.
Diese Spalten entstehen durch Disjunktionen der entsprechenden Spalten der
einzelnen Veranstaltungsteile, bzw. Kursschienen und können ausschließlich zum
Filtern verwendet werden.

Beispiel
^^^^^^^^

Sei folgende Veranstaltung gegeben:

* WinterAkademie 3019/20
    * Veranstaltungsteile:
        * \1. Hälfte Oberwesel (O1, 27.12.3019 – 1.1.3020)
            * Teilnahmebeitrag 100 €
            * Kursschienen:
                * Vormittags (Kurs 1 O1)
                * Nachmittags (Kurs 2 O1)
        * \1. Hälfte Kaub (K1, 27.12.3019 – 1.1.3020)
            * Teilnahmebeitrag 120 €
            * Kursschienen:
                * Kurs (Kurs K1)
        * \2. Hälfte Oberwesel (O2, 1.1.3020 – 6.1.3020)
            * Teilnahmebeitrag 90 €
            * Kursschienen:
                * Kurs (Kurs O2)
        * \2. Hälfte Kaub (K2, 1.1.3020 – 6.1.3020)
            * Teilnahmebeitrag 110 €
            * Kursschienen:
                * Vormittags (Kurs 1 K2)
                * Nachmittags (Kurs 2 K2)
    * Veranstaltungsteilgruppen:
        * \1. Hälfte (1.H., Statistik)
            * O1
            * K1
        * \2. Hälfte (2.H., Statistik)
            * O2
            * K2
        * Kaub (KA, Statistik)
            * K1
            * K2
        * Oberwesel (OW, Statistik)
            * O1
            * O2
        * Alle (alle, Statistik)
            * O1
            * K1
            * O2
            * K2


Dann gibt es in der Anmeldungssuche eine Spalte "1.H.: Kurs".
Die Abfrage "1.H.; Kurs ist gleich 4. Akrobatik" liefert dann alle
Teilnehmenden, die in einer beliebigen Kursschiene der ersten Hälfte
(also Kurs 1 O1, Kurs 2 O1 oder Kurs K1) in den Kurs "4. Akrobatik"
eingeteilt sind.

Die vermeintlich gegenteilige Abfrage "1.H.: Kurs ist ungleich 4. Akrobatik"
liefert alle Teilnehmenden, die in einer beliebigen Kursschiene der ersten
Hälfte in einen anderen Kurs als "4. Akrobatik" eingeteilt sind.
Nicht gefunden werden z.B. Teilnehmende, die in gar keinen Kurs eingeteilt sind.

Die "gegenteilige" Abfrage "1.H.: Kurs ist leer oder ungleich 4. Akrobatik"
liefert alle Teilnehmenden, die in einer beliebigen Kursschiene der ersten
Hälfte **nicht** in den Kurs "4. Akrobatik" eingeteilt sind.

Über die Schnittmengen dieser drei Abfragen können keine allgemeinen Aussagen
getroffen werden.

Durch die Veranstaltungsteilgruppe "Alle" gibt es keine zusätzliche Spalte in
der Suche, da es die entsprechende Spalte immer bereits automatisch gibt.
Die Spalte auf der Statistikseite exisitert ohne die Veranstaltungsteilgruppe
allerdings nicht.


Typ: Teilnahmeausschließlichkeit
--------------------------------

Mit Veranstaltungsteilgruppen vom Typ "Teilnahmeausschließlichkeit" kann
modelliert werden, dass nur eine Teilnahme an maximal einem der vernknüpften
Veranstaltungsteile vorgesehen ist, bspw. weil diese gleichzeitig an
verschiedenen Orten stattfinden.

Für Teilnehmende die gegen diese Beschränkung verstoßen werden an geeigneten
Stellen Warnmeldungen angezeigt.

Potentielle Teilnehmende können sich trotz der Teilnahmeausschließlichkeit
für mehrere Veranstaltungsteile der gleichen Gruppe anmelden.
Da aber niemand an beiden Veranstaltungsteilen tatsächlich teilnehmen kann,
ist es nicht notwendig den Teilnahmebeitrag für beide Teile zu entrichten.
Durch die Teilnahmeausschließlichkeitsbeschränkung wird als Teilnahmebeitrag
stattdessen der maximale zu zahlende Beitrag berechnet.

Im obigen Beispiel könnte man folgende weitere Veranstaltungsteilgruppen
hinzufügen:

* Teilnahme 1. Hälfte (TN 1.H., Teilnahmeausschließlichkeit)
    * O1
    * K1
* Teilnahme 2. Hälfte (TN 2.H., Teilnahmeausschließlichkeit)
    * O2
    * K2

Dadurch wird für Teilnehmende, deren Status in O1 und K1 "Teilnehmer" ist,
eine Meldung der Stufe "Fehler" angezeigt.
Für Teilnehmende, die an mehreren Veranstaltungsteilen anwesend sind, z.B.
"Teilnehmer" in K1 und "Gast" in O1 oder "Gast" in O2 und K2, wird eine Meldung
der Stufe "Warnung" angezeigt.

Auf der Veranstaltungsübersichtsseite wird für Orgas die Gesamtanzahl der
Meldungen angezeigt. Auf der Seite "Verstöße gegen Beschränkungen" werden die
Meldungen für alle Anmeldungen angezeigt. Auf der Übersichtsseite einer
einzelnen Anmeldung werden die Warnungen für diese Anmeldung angezeigt,
sofern vorhanden.

Die Meldungen sind rein kosmetisch und haben keinerlei weiteren Effekt.

Meldet sich Person T für die Veranstaltungsteile O1 und K2 an, zahlt T ganz
normal die Teilnahmebeiträge von O1 und K2, also 100 € + 110 € = 210 €.
Meldet T sich hingegen für O1, K1 und K2 an, muss T stattdessen
120 € + 110 € = 230 € bezahlen, da dies der maximale Teilnahmebeitrag ist,
falls T einen Platz auf K1 und K2 erhält. Nimmt T stattdessen nur an O1 und K2
teil, muss T später eine Erstattung für die Differenz (20 €) erhalten.


Typ: Kursauschließlichkeit
--------------------------

Mit Veranstaltungsteilgruppen vom Typ "Kursausschließlichkeit" lässt sich
modellieren, dass Kurse nur in maximal den Kursschienen eines verknüpften
Veranstaltungsteils stattfinden sollen, bspw. weil diese gleichzeitig an
verschiedenen Orten stattfinden.

Der primäre Anwendungsfall ist für Kurse, die in mehreren Kurschienen angeboten
werden, aber nur in einer davon stattfinden sollen.

Kurse die in mehreren dieser Kursschienen angeboten werden, aber nur in einer
davon stattfinden, produzieren keine Meldung.
Kurse die in mehreren dieser Kursschienen stattfinden erhalten eine Meldung
der Stufe "Warnung".

Auf der Veranstaltungsübersichtsseite wird für Orgas die Gesamtanzahl der
Meldungen angezeigt. Auf der Seite "Verstöße gegen Beschränkungen" werden die
Meldungen für alle Kurse angezeigt. Auf der Übersichtsseite eines einzelnen
Kurses werden die Meldungen für diesen Kurs angezeigt, sofern vorhanden.

Die Meldungen sind rein kosmetisch und haben keinerlei weiteren Effekt.
