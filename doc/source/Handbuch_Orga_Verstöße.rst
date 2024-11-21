Verstöße
========

Die Datenbank kann für viele Situation, die im Laufe der Organisation einer
Veranstaltung auftreten können -- aber eigentlich nicht sollen -- Hinweise, Warnungen
bzw. sogar Fehlermeldungen ausgeben.

In diesem Dokument werden die einzelnen Arten von Verstößen näher erläutert.


.. _MutuallyExclusiveParticipationCV:

Teilnahmeausschließlichkeit
---------------------------

Dieser Verstoß tritt nur auf, wenn mindestens eine Veranstaltungsteilgruppe des Typs
``Teilnahmeausschließlichkeit`` existiert.

Sofern eine Person bei mehr als einem Teil einer solchen Gruppe den Status
``Teilnehmer`` hat, wird ein Fehler angezeigt.
Sofern eine Person bei mehr als einem Teil einer solchen Gruppe anwesend ist
(Teilnehmer und/oder Gast), wird eine Warnung angezeigt.

Um den Verstoß zu beheben, sollte der Status der Person auf den entsprechenden
Veranstaltungsteilen angepasst werden.


.. _CourseChoiceSyncCV:

Kurswahlsynchronisierung
------------------------

Dieser Verstoß tritt nur auf, wenn mindestens eine Kursschienengruppe des Typs
``Kurswahlsynchronisierung`` existiert.

Dieser Verstoß tritt auf, wenn eine Person in einer solchen synchronisierten Gruppe
verschiedene Kurswahlen getätigt hat.

Das sollte in der Praxis nicht auftreten können, da bei jeder Änderung an einer
Anmeldung die Konsistenz der Wahlen geprüft wird. Sollte das doch passieren ist dies
ein schwerwiegender Fehler, der quasi jede weitere Bearbeitung von Kurses und
Anmeldungen verhindern dürfte. Falls das bei deiner Veranstaltung passiert wende dich
umgehend an das Datenbank-Team <cdedb@lists.cde-ev.de>.


.. _NoCourseAssignedCV:

Fehlende Kurseinteilungen
-------------------------

Dieser Verstoß tritt auf, wenn eine Person mit dem Status "Teilnehmer", die kein Orga
und nicht U10 ist, nicht in einen Kurs eingeteilt ist.

Um den Verstoß zu beheben, sollte die Person in einen Kurs eingeteilt werden oder ihr
Status angepasst werden.


.. _IncorrectCourseAssignedCV:

Fehlerhafte Kurseinteilungen
----------------------------

Dieser Verstoß tritt auf, wenn eine Person in einer Kursschiene in einen nicht
gewählten Kurs eingeteilt ist, oder nicht in den von ihr geleiteten Kurs, obwohl dieser
stattfindet.

Um den Verstoß zu beheben, sollte die Person in einen gewählten, bzw. den von ihr
geleiteten Kurs eingeteilt werden, ihre Kurswahlen angepasst werden oder der von ihr
geleiteter Kurs abgesagt werden.


.. _CancelledWithAttendeesCV:

Ausfallende Kurse mit Teilnehmenden
-----------------------------------

Dieser Verstoß tritt auf, wenn ein abgesagter Kurs noch über Kursteilnehmende verfügt.
Das gilt nicht für Personen, die nicht anwesend sind.

Um den Verstoß zu beheben, sollten die Personen in einen anderen Kurs eingeteilt werden,
ihr Status angepasst werden oder der Kurs als nicht abgesagt markiert werden.


.. _IncorrectNumAttendeesCV:

Kurse mit inkorrekter Teilnehmendenzahl
---------------------------------------

Dieser Verstoß tritt auf, wenn in einen Kurs zu wenige (aber mehr als 0) oder zu viele
Kursteilnehmende eingeteilt sind. Nicht anwesende Kursteilnehmende werden hierbei nicht
beachtet.

Um den Verstoß zu beheben, teile einige der Teilnehmenden in andere Kurse ein oder
passe die minimale und maximale Teilnehmendenzahl des Kurses an.


.. _LonelyAttendeesCV:

Einsame Kursteilnehmende
------------------------

Dieser Verstoß tritt auf, wenn in einem Kurs Teilnehmende, aber keine Kursleitenden
oder anders herum eingeteilt sind. Nicht anwesende Kursteilnehmende oder Kursleitende
werden hierbei nicht beachtet.

Um den Verstoß zu beheben, teile Teilnehmende bzw. Kursleitende in den Kurs ein oder
sage den Kurs ab.


.. _InconsistentPaymentCV:

Inkonsistenter Zahlungstatus
----------------------------

Dieser Verstoß tritt auf, wenn beim Eintragen der Zahlungsdaten einer Person etwas
schiefgelaufen ist, z.B. wenn sie einen negativen Betrag bezahlt hat oder kein
Bezahlungsdatum gesetzt ist.

Einen solchen Verstoß kann in aller Regel nur die Buchhaltung erzeugen und ebenso
beheben. Fallsdas bei deiner Veranstaltung auftritt, wende dich umgehend an die
Buchhaltung <buchhaltung@lists.cde-ev.de>.


.. _NotPaidCV:

Nicht bezahlter Beitrag
-----------------------

Dieser Verstoß tritt auf, wenn eine Person auf mindestens einem Veranstaltungsteil den
Status ``Teilnehmer`` hat, aber noch keinen Teilnahmebeitrag bezahlt hat
(dies aber tun muss).

Um den Verstoß zu beheben, erinnere die Person daran, ihren Beitrag zu überweisen,
ändere ihren Status oder passe ggf. den Teilnahmebeitrag der Person an.


.. _NegativeAmountOwedCV:

Negativer zu zahlender Betrag
-----------------------------

Dieser Verstoß tritt auf, wenn eine Person insgesamt einen negativen Beitrag zahlen
soll. In der Regel deutet dies darauf hin, dass bei der Konfiguration der
Teilnahmebeiträge etwas schief gelaufen ist.

Um den Verstoß zu beheben kontrolliere die für die Person aktiven Teilnahmebeiträge.
Falls du dir nicht sicher bist, wo das Problem liegt, melde dich gerne beim
Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _NegativeRemainingOwedCV:

Negativer übriger zu zahlender Betrag
-------------------------------------

Dieser Verstoß tritt auf, wenn eine Person einen höheren Beitrag bezahlt hat, als sie
es zum jetzigen Stand hätte tun müssen. In der Regel liegt das daran, dass die Person
sich von einem oder mehreren Veranstaltungsteilen abgemeldet hat, oder keinen Platz
erhalten hat. Es kommt aber auch vor, dass einzelne Personen versehentlich zu viel Geld
überweisen.

Um den Verstoß zu beheben, sollte eine Rückzahlung an die Person initiiert werden.
Über das genaue Verfahren hierzu sollte dein Finanzorga-Bescheid wissen.
Ansprechpartner für die Ausführung von Erstattungen und sonstige damit verbundene
Fragen ist das Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.


.. _RemainingOwedCV:

Übriger zu zahlender Betrag
---------------------------

Dieser Verstoß tritt auf, wenn eine Personen bereits einen Teil ihres Beitrages, aber
noch nicht den vollen Beitrag bezahlt hat. Oft liegt das daran, dass die Person sich
zu einem oder mehreren Veranstaltungsteilen nachgemeldet hat oder weil der
Teilnahmebeitrag in mehreren Raten bezahlt wird. Es kommt aber auch vor, dass
einzelne Personen versehentlich zu wenig Geld überweisen.

Um den Verstoß zu beheben, erinnere die Person daran den übrigen Beitrag zu bezahlen
oder passe ihren Status bzw. ggf. ihren Teilnahmebeitrag an. Ansprechpartner bei allen
Fragen rund um Teilnahmebeiträge ist das
Akademie-Finanz-Team <aka-finanzen@lists.cde-ev.de>.
