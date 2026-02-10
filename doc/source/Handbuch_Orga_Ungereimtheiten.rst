***************
Ungereimtheiten
***************

Die Datenbank kann für viele Situationen, die im Laufe der Organisation einer
Veranstaltung auftreten können -- aber eigentlich nicht sollen -- Hinweise, Warnungen
bzw. sogar Fehlermeldungen ausgeben. Übergreifend werden diese als Ungereimtheiten
bezeichnet.

Es existieren mehrere Stufen an Ungereimtheiten, welche einen Hinweis darauf geben, wie
schwerwiegend diese sind und wie schnell sich darum gekümmert werden sollte:

- Hinweis: Um eine solche Ungereimtheit sollte sich vermutlich irgendwann einmal
  gekümmert werden, aber das ist erst langfristig möglich oder erfordert die
  Beteiligung weiterer Personen. Einige Hinweise lassen sich auch nicht lösen und
  werden von ungewöhnlichen, aber korrekten Situationen ausgelöst.
- Warnung: Eine solche Ungereimtheit deutet darauf hin, dass die Ursache relativ bald
  behoben werden sollte, in Ausnahmefällen kann der entsprechende Zustand aber
  vorübergehend oder sogar vollständig korrekt sein.
- Fehler: Ein Zustand, der immer falsch ist und behoben werden muss, am besten
  innerhalb von wenigen Tagen.
- Kritisch: Ein Zustand der nicht existieren können sollte, außer durch einen
  Softwarefehler, korrumpierte Daten oder einen Fehler außerhalb der Macht des Orgateams.

In diesem Dokument werden die einzelnen Arten von Ungereimtheiten, auf die die
Datenbank hinweisen kann, näher erläutert.

Allgemeine Fehler
=================

.. _RegistrationLockedCV:

Gesperrte Anmeldung
-------------------

Diese Ungereimtheit bedeutet, dass die Anmeldung für deine Veranstaltung noch nicht freigeschaltet wurde.

Bevor die Anmeldung beginnen kann, muss das Akademieteam einige Dinge prüfen.
Wende dich hierzu an die für dich zuständige Orgateambetreuung, das Akademie-Finanz-Team,
die Minderjährigen-Koordination und/oder das Akademieteam.


.. _IncorrectIBANCV:

Falsche IBAN-Konfiguration
--------------------------

Diese Situation tritt auf, wenn für deine Veranstaltung das alte, nicht mehr verwendete, CdE-Konto
(Sozialbank) zur Zahlung der Teilnahmebeiträge eingestellt ist.

Sofern du dir nicht sehr sicher bist, dass dies kein Fehler ist, ändere das Konto auf das neue
CdE-Konto bei der Skatbank.


.. _InvalidExternalFeeCV:

Ungültige Externenbeitragskonfigurationen
-----------------------------------------

Diese Ungereimtheit tritt auf, wenn ein Externenzusatzbeitrag existiert, dessen Formel nicht ``is_member``
verwendet, oder wenn diese Variable in einem Teilnahmebeitrag eines anderen Typens verwendet wird.

``is_member`` ist ein spezieller Wert, der genau für die Berechnung von Externenzusatzbeiträgen verwendet wird.
Passe den Teilnahmebeitrag entsprechend an. Falls du dir unsicher bist, wie die Konfiguration aussehen sollte,
wende dich an das Akademie-Finanz-Team.


Fehler bei Anmeldungen
======================


.. _InconsistentPaymentCV:

Anmeldungen mit inkonsistentem Zahlungsstatus
---------------------------------------------

Diese Situation tritt auf, wenn beim Eintragen der Zahlungsdaten einer Person etwas
schiefgelaufen ist, z.B. wenn sie einen negativen Betrag bezahlt hat oder kein
Bezahlungsdatum gesetzt ist.

Ein solches Problem kann in aller Regel nur die Buchhaltung erzeugen und ebenso
beheben. Falls das bei deiner Veranstaltung auftritt, wende dich umgehend an die
Buchhaltung <buchhaltung@lists.cde-ev.de>.


.. _NotPaidCV:

Anmeldungen mit nicht bezahltem Beitrag
---------------------------------------

Diese Situation tritt auf, wenn eine Person auf mindestens einem Veranstaltungsteil den
Status ``Teilnehmer`` hat, aber noch keinen Teilnahmebeitrag bezahlt hat
(dies aber tun muss).

Um die Ursache zu beheben, erinnere die Person daran, ihren Beitrag zu überweisen,
ändere ihren Status oder passe ggf. den Teilnahmebeitrag der Person an.


.. _ZeroAmountOwedCV:

Anmeldungen ohne zu zahlendem Beitrag
-------------------------------------

Diese Situation tritt auf, wenn eine Person keinen Teilnahmebeitrag bezahlen muss,
obwohl Teilnahmebeiträge konfiguriert wurden, außer die Person ist Orga.
In der Regel deutet dies darauf hin, dass bei der Konfiguration der
Teilnahmebeiträge etwas schief gelaufen ist.

Um der Ursache auf den Grund zu gehen, kontrolliere die für die Person aktiven
Teilnahmebeiträge. Falls du dir nicht sicher bist, wo das Problem liegt, melde dich
gerne beim Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _NegativeAmountOwedCV:

Anmeldungen mit negativem zu zahlenden Beitrag
----------------------------------------------

Diese Situation tritt auf, wenn eine Person insgesamt einen negativen Beitrag zahlen
soll. In der Regel deutet dies darauf hin, dass bei der Konfiguration der
Teilnahmebeiträge oder dem Eintragen von Erstattungen etwas schief gelaufen ist.

Um die Ursache zu bestimmen, kontrolliere die für die Person aktiven Teilnahmebeiträge.
Falls du dir nicht sicher bist, wo das Problem liegt, melde dich gerne beim
Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _NegativeRemainingOwedCV:

Anmeldungen mit negativem übrigen zu zahlenden Beitrag
------------------------------------------------------

Diese Situation tritt auf, wenn eine Person einen höheren Beitrag bezahlt hat, als sie
es zum jetzigen Stand hätte tun müssen. In der Regel liegt das daran, dass die Person
sich von einem oder mehreren Veranstaltungsteilen abgemeldet hat, oder keinen Platz
erhalten hat. Es kommt aber auch vor, dass einzelne Personen versehentlich zu viel Geld
überweisen. Auch eingetragene aber noch nicht durchgeführte (KL-)Erstattungen können der
Grund sein.

Um die Ursache zu beheben, sollte eine Rückzahlung an die Person initiiert werden.
Über das genaue Verfahren hierzu sollte dein Finanzorga Bescheid wissen.
Ansprechpartner für die Ausführung von Erstattungen und sonstige damit verbundene
Fragen ist das Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _RemainingOwedCV:

Anmeldungen mit Übrigem zu zahlenden Beitrag
--------------------------------------------

Diese Situation tritt auf, wenn eine Personen bereits einen Teil ihres Beitrages, aber
noch nicht den vollen Beitrag bezahlt hat. Oft liegt das daran, dass die Person sich
zu einem oder mehreren Veranstaltungsteilen nachgemeldet hat oder weil der
Teilnahmebeitrag in mehreren Raten bezahlt wird. Es kommt aber auch vor, dass
einzelne Personen versehentlich zu wenig Geld überweisen.

Um die Ursache zu beheben, erinnere die Person daran den übrigen Beitrag zu bezahlen
oder passe ihren Status bzw. ggf. ihren Teilnahmebeitrag an. Ansprechpartner bei allen
Fragen rund um Teilnahmebeiträge ist das
Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _AbsentCheckedinCV:

Eingecheckte Abwesende
----------------------

Diese Situation tritt auf, wenn eine Person während eines Veranstaltungsteils
eingecheckt ist, deren Status weder Teilnehmer noch Gast ist, bzw. sie zum Ende der
Veranstaltung nicht ausgecheckt wurde.

Um die Ursache zu beheben, passe entweder den Status der Person entsprechend an oder
trage ggf. einen Checkout ein, der vor dem entsprechenden Veranstaltungsteil liegt.


.. _PresentNeverCheckedinCV:

Uneingecheckte Teilnehmende
---------------------------

Diese Situation tritt auf, wenn Personen am zweiten Tag eines Veranstaltungsteils,
an dem sie teilnehmen, noch nicht eingecheckt sind.

Um die Ursache zu beheben, markiere die Person entweder als abgemeldet, wenn sie nicht
mehr kommt, oder warte, bis sie angekommen ist, und checke sie anschließend ein.


.. _MissingMinorFormCV:

Fehlende Einverständniserklärung
--------------------------------

Diese Situation tritt auf, wenn für minderjährige Teilnehmende einen Monat vor Beginn
der Veranstaltung noch keine elterliche Einverständniserklärung vorliegt.

Um die Ursache zu beheben, trage die angekommene Einverständniserklärung in der
Datenbank ein, bzw. erinnere die Minderjährigen daran, dass sie diese einreichen müssen.


.. _IllegalMixedLodgingCV:

Unzulässige gemischte Unterbringung
-----------------------------------

Diese Situation tritt auf, wenn eine minderjährige Person (U16, Ü10) einer gemischten
Unterbringung zugestimmt hat. Üblicherweise tritt dies nur bei manuellem Eingriff durch
Orgas auf.

Um die Ursache zu beheben, bearbeite die Anmeldung und entferne den Haken für
"Gemischte Unterbringung". Beachte allerdings, dass eine gemischt untergebrachte
minderjährige Person ebenfalls einen Warnung auslöst.


Fehler bei Veranstaltungsteilen
===============================


.. _IncorrectCampingMatAssignmentCV:

Unzulässige Isomatteneinteilung
-------------------------------

Diese Situation tritt auf, wenn ein Isomattenbereitschaftsfeld konfiguriert ist und eine
anwesende Person auf einer Isomatte eingeteilt ist, die dem nicht zugestimmt hat.

Um die Ursache zu beheben, entferne die Isomatteneinteilung oder ändere die
Isomattenbereitschaft der Person.


.. _NoLodgementCV:

Fehlende Unterkunftseinteilung
------------------------------

Diese Situation tritt auf, wenn eine anwesende Person eine Woche vor Beginn der
Veranstaltung noch keine Unterkunft hat. Tritt nicht auf, wenn für die Veranstaltung
keine Unterkünfte existieren.

Um die Ursache zu beheben, teile die Person in eine Unterkunft ein.


.. _IncorrectNumInhabitantsCV:

Unterkünfte mit inkorrekter Bewohnerzahl
----------------------------------------

Diese Situation tritt auf, wenn in einer Unterkunft zu viele Bewohner und/oder
Isomattenschläfer eingeteilt sind. Die Datenbank kann nicht unterscheiden, falls diese
Einteilung auf Grund von Gästen und/oder frühzeitig/später an/abreisenden Personen
dennoch korrekt ist.

Um die Ursache zu beheben, teile einige der Bewohner in eine andere Unterkunft ein,
teile einige auf Isomatten ein und/oder passe die Kapazität der Unterkunft an.


.. _IllegalMixedLodgementCV:

Unzulässige gemischte Unterkunft
--------------------------------

Diese Situation tritt auf, wenn in einer gemischten Unterkunft inkompatible Personen
eingeteilt sind. Inkompatibel sind insbesondere Personen, die nicht einer gemischten
Unterbringung zugestimmt haben, bzw. Minderjährige unter 16 Jahren (aber über 10
Jahren).

Um die Ursache zu beheben, teile einige der Bewohner in eine andere Unterkunft ein.


Fehler bei Kursen
=================


.. _NoCourseAssignedCV:

Fehlende Kurseinteilungen
-------------------------

Diese Situation tritt auf, wenn eine Person mit dem Status ``Teilnehmer``, die kein Orga
und nicht U10 ist, nicht in einen Kurs eingeteilt ist.

Um die Ursache Verstoß zu beheben, sollte die Person in einen Kurs eingeteilt werden
oder ihr Status angepasst werden.


.. _IncorrectCourseAssignedCV:

Fehlerhafte Kurseinteilungen
----------------------------

Diese Situation tritt auf, wenn eine Person in einer Kursschiene in einen nicht
gewählten Kurs eingeteilt ist, oder nicht in den von ihr geleiteten Kurs, obwohl dieser
stattfindet.

Um die Ursache zu beheben, sollte die Person in einen gewählten, bzw. den von ihr
geleiteten Kurs eingeteilt werden, ihre Kurswahlen angepasst werden oder der von ihr
geleitete Kurs abgesagt werden.


.. _CancelledWithAttendeesCV:

Ausfallende Kurse mit Teilnehmenden
-----------------------------------

Diese Situation tritt auf, wenn ein abgesagter Kurs noch über Kursteilnehmende verfügt.
Das gilt nicht für Personen, die nicht anwesend sind.

Um die Ursache zu beheben, sollten die Personen in einen anderen Kurs eingeteilt werden,
ihr Status angepasst werden oder der Kurs als abgesagt markiert werden.


.. _IncorrectNumAttendeesCV:

Kurse mit inkorrekter Teilnehmendenzahl
---------------------------------------

Diese Situation tritt auf, wenn in einen Kurs zu wenige (aber mehr als 0) oder zu viele
Kursteilnehmende eingeteilt sind. Nicht anwesende Kursteilnehmende werden hierbei nicht
beachtet.

Um die Ursache zu beheben, teile einige der Teilnehmenden in andere Kurse ein oder
passe die minimale und maximale Teilnehmendenzahl des Kurses an.


.. _LonelyAttendeesCV:

Kurse mit einsamen Kursteilnehmenden
------------------------------------

Diese Situation tritt auf, wenn in einem Kurs Teilnehmende, aber keine Kursleitenden
oder anders herum eingeteilt sind. Nicht anwesende Kursteilnehmende oder Kursleitende
werden hierbei nicht beachtet.

Um die Ursache zu beheben, teile Teilnehmende bzw. Kursleitende in den Kurs ein oder
sage den Kurs ab.


.. _HiddenCourseCV:

Versteckte Kurse
----------------

Diese Situation tritt auf, wenn es versteckte Kurse gibt, aber die Anmeldung offen ist
oder in wenigen Tagen beginnen soll.
**Achtung:** Versteckte Kurse können bei der Anmeldung trotzdem gewählt werden!

Um die Ursache zu beheben, zeige die versteckten Kurse in der Kursliste an oder lösche
sie.


Fehler bei Veranstaltungsteil- oder Kursschienengruppen
=======================================================


.. _MutuallyExclusiveParticipationCV:

Verstöße gegen Teilnahmeausschließlichkeit
------------------------------------------

Dieser Verstoß tritt nur auf, wenn mindestens eine Veranstaltungsteilgruppe des Typs
``Teilnahmeausschließlichkeit`` existiert.

Sofern eine Person bei mehr als einem Teil einer solchen Gruppe den Status
``Teilnehmer`` hat, wird ein Fehler angezeigt.
Sofern eine Person bei mehr als einem Teil einer solchen Gruppe anwesend ist
(Teilnehmer und/oder Gast), wird eine Warnung angezeigt.

Um die Ursache zu beheben, sollte der Status der Person auf den entsprechenden
Veranstaltungsteilen angepasst werden.


.. _CourseChoiceSyncCV:

Verstöße gegen Kurswahlsynchronisierung
---------------------------------------

Dieser Verstoß tritt nur auf, wenn mindestens eine Kursschienengruppe des Typs
``Kurswahlsynchronisierung`` existiert.

Dieser Verstoß tritt auf, wenn eine Person in einer solchen synchronisierten Gruppe
verschiedene Kurswahlen getätigt hat.

Das sollte in der Praxis nicht auftreten können, da bei jeder Änderung an einer
Anmeldung die Konsistenz der Wahlen geprüft wird. Sollte das doch passieren ist dies
ein schwerwiegender Fehler, der quasi jede weitere Bearbeitung von Kurses und
Anmeldungen verhindern dürfte. Falls das bei deiner Veranstaltung passiert, wende dich
umgehend an das Datenbank-Team <cdedb@lists.cde-ev.de>.


.. _MutuallyExclusiveCoursesCV:

Verstöße gegen Kursausschließlichkeit
-------------------------------------

Dieser Verstoß tritt nur auf, wenn mindestens eine Kursschienengruppe des Typs
``Kursausschließlichkeit`` existiert.

Sofern ein Kurs in mehr als einer Schiene einer solchen Gruppe stattfindet,
wird ein Fehler angezeigt.

Um den Verstoß zu beheben, lasse den Kurs nur in einer solchen Kursschiene stattfinden,
oder entferne die entsprechende Kursschienengruppe.
