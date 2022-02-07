Elektronisches Wahlverfahren
============================

.. This is linked to in the ballot tally emails, so it should stay German.


Hier wird das elektronische Wahlverfahren, das für die Abstimmungen in der
CdE-Datenbank verwendet wird, erklärt.

Einleitung
----------

Elektronische Wahlen stellen ein bis heute ungelöstes Problem dar, da bei
allen bekannten Implementierungen manche wünschenswerte Eigenschaften einer
klassischen Wahl verloren gehen. Zum Glück sind wir nur ein Hobby-Verein,
sodass wir keine existentiellen Fragen zu entscheiden haben und dies recht
entspannt sehen können.

Ablauf
------

Mit der Teilnahme an der Versammlung erstellt die Datenbank für jeden ein
persönliches Geheimnis (eine zufällige Zeichenkette), das im folgenden
benutzt wird um die Wahl kryptographisch abzusichern. Das System ist
prinzipiell so ausgelegt, dass das Geheimnis niemals dem Server bekannt sein
müsste, aus Bedienbarkeitsgründen wird es aber auf dem Server
gespeichert. Das Geheimnis wird dann per Mail zugestellt.

Die Stimmabgabe erfolgt via Webinterface. Die Stimme wird dann auf dem
Server gespeichert, wobei die Zuordnung der Stimme zur Person nur unter
Kenntnis des Geheimnisses möglich ist.

Sobald die Abstimmung beendet ist, erstellt die Datenbank eine
Ergebnisdatei, die die gesamten Informationen zur Abstimmung enthält. Diese
Datei sowie das reine Ergebnis sind dann auf der Abstimmungsseite in der DB
verfügbar. Außerdem wird die Ergebnisdatei direkt nach der Erstellung auf
eine spezielle [Bekanntmachungsliste]_ veröffentlicht. Dadurch
wird ein Commitment erzeugt, sodass das Ergebnis nicht nachträglich
manipuliert werden kann.

Zur Verifikation der Ergebnisdatei gibt es außerdem zwei Pythonskripte:

* mit dem [Stimmverifizierungsskript]_ kann überprüft werden, ob die eigene
  Stimme korrekt in der Ergebnisdatei verzeichnet wurde. Hierfür wird das
  anfangs per Mail übermittelte Geheimnis benötigt, um die Zuordnung
  herstellen zu können.
* mit dem [Ergebnisverifizierungsskript]_ kann überprüft werden, welchen
  Wahlausgang die in der Ergebnisdatei verzeichneten Stimmen ergeben.

Beide Skripte benötigen als einzige Abhängigkeit Python 3.

.. [Bekanntmachungsliste] https://db.cde-ev.de/db/ml/mailinglist/91/show
.. [Stimmverifizierungsskript] https://db.cde-ev.de/static/verify_vote.py
.. [Ergebnisverifizierungsskript] https://db.cde-ev.de/db/assembly/verify_result.pyz

   Hierbei handelt es sich um eine Zipapp, dies ist ein Pythonprogramm in
   einem Ziparchiv. Das Ziparchiv bündelt eine Abhängigkeit (das Paket
   schulze_condorcet), sodass diese nicht installiert werden muss.

   .. note:: Diese Datei benutzt exotischere Features der Zip-Spezifikation
             weshalb es bei manchen Archivprogrammen zu Problemen beim Lesen
             der Datei kommt. Die Ausführbarkeit mittels Python ist davon
             nicht beeinträchtigt.

             Die eigentliche Skriptdatei kann als [Skriptrohfassung]_
             heruntergeladen werden. Ist das Paket schulze_condorcet
             installiert, so funktionieren beide Varianten identisch.

.. [Skriptrohfassung] https://db.cde-ev.de/static/verify_result.py
