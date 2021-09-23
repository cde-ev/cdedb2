Dokuteam Exporte
================

Das Dokuteam benötigt einige Informationen aus der Datenbank, um seiner Arbeit
nachgehen zu können. Um das Extrahieren dieser Informationen zu erleichtern,
gibt es mehrere Downloads pro Veranstaltung, die dem Dokuteam zur Verfügung
gestellt werden sollen.

Für die Exporte vor und nach einer Veranstaltung ist das Akademieteam als
konstanter Ansprechpartner für diese Exporte zuständig, auf der Akademie
sollen die Orgas die jeweiligen Exporte generieren.

Die Exporte sind teilweise fertige Dateien im Download-Bereich, teilweise
als Standardabfrage gespeichert in den Suchmasken. Letztere können einfach als
`.csv`-Datei heruntergeladen werden.

Vor der Akademie
----------------

Kursliste
    Sobald alle Kurse in der Datenbank eingetragen wurden und feststeht, welche
    Kurse zustande kommen, kann eine Liste dieser an das Dokuteam gegeben werden.
    Diese enthält Kursnummer, Kurskurzname und Kursname aller angelegten Kurse,
    die in mindestens einer Kursschiene stattfinden.

    Unter ``Veranstaltung/Kurse/Kurssuche`` die ``Dokuteam Kursliste`` Abfrage

Teilnehmerliste
    Sobald die Kurseinteilung in der Datenbank vorgenommen wurde, benötigt das
    Dokuteam eine Liste mit den Kursen jedes Teilnehmers.
    Diese enthält Vorname, Nachnamen und Kursnummern aller Teilnehmer eines
    Veranstaltungsteils und ist separat für jeden Veranstaltungsteil vorhanden.

    Unter ``Veranstaltung/Downloads`` die ``Dokuteam Teilnehmerliste`` Datei

Skriptinput Kursliste
    Um verschiedene Listen kurz vor der Akademie zu erstellen, benötigt das
    Dokuteam diese Input Datei.
    Sie enthält Kurzname und Name der Akademie sowie Kursnummer, Kurskurzname
    und Kurstitel jedes Kurses, der in mindestens einer Kursschiene stattfindet.

    Unter ``Veranstaltung/Downloads`` die ``Dokuteam Kursliste`` Datei

Auf der Akademie
----------------

Kursfoto
    Um die Kursfotobeschriftungen abgleichen zu können, benötigt das Dokuteam
    eine aktuelle Liste, wer in welchem Kurs ist und wer den Kurs leitet.
    Diese enthält Datenbank-ID, Vorname, Nachname, Kurs-Nummer und
    hält-seinen-kurs von jedem Teilnehmer der gesamten Akademie.

    Unter ``Veranstaltung/Anmeldungen`` die ``Dokuteam Kursfoto`` Abfrage

Dokuforge
    Um nach der Akademie die Dokus setzen zu können, brauchen die Teilnehmer,
    Dokubeauftragten und Kursleiter einen Dokuforge-Zugang. Dafür benötigt das
    Dokuteam Mailadresse und Kurs aller Teilnehmer.
    Diese Liste enthält Datenbank-ID, Vorname, Nachname, Kurs-Nummer, Mailadresse
    und hält-seinen-kurs von jedem Teilnehmer der gesamten Akademie, der darüber
    hinaus seine Zustimmung zur Weitergabe seiner Daten an die Teilnehmerliste
    gegeben hat.

    Unter ``Veranstaltungen/Anmeldungen`` die ``Dokuteam Dokuforge`` Abfrage

Nach der Akademie
-----------------

Addressabfrage
    Um die fertigen Dokus zustellen zu können, benötigt das Dokuteam die
    aktuelle Adresse der Teilnehmer.
    Diese Abfrage enthält Datenbank-ID, Vorname, Nachname, Adresszuatz,
    Straße+Hausnummer, PLZ, Ort und Land jedes Teilnehmers der Akademie.

    Unter ``Veranstaltungen/Anmeldungen`` die ``Dokuteam Addressexport`` Abfrage
