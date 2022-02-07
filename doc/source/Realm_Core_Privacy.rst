Privacy Control
===============

In der CdE-Datenbank werden eine Menge personenbezogene Daten gesammelt und
gespeichert. Im folgenden soll geklärt werden, wer Zugriff und Einsicht in diese
Daten hat. Dabei wird es vor allem um die im Profil gespeicherten Daten gehen.


Welche Daten werden im Profil gespeichert?
------------------------------------------

Grundsätzlich gibt es folgende Datenfelder, die im Profil einer Person angezeigt
werden können:

* Name,
* Geburstname,
* Geburtsdatum,
* Geschlecht,
* CdEDB-ID,
* Account aktiv,
* Bereiche,
* Admin-Privilegien,
* Admin-Notizen,
* Guthaben, bzw Lastschrift
* Sichtbarkeit,
* E-Mail,
* Telefon,
* Mitgliedschaft
* Mobiltelefon,
* WWW,
* Adresse,
* Zweitadresse,
* Fachgebiet,
* Schule, Uni, …,
* Jahrgang, Matrikel, …,
* Interessen,
* Sonstiges,
* Vergangene Veranstaltungen

Diese lassen sich in die Folgenden Kategorien einteilen (Mehrfachnennung
möglich):

* Grundlegend
    * Name,
    * CdEDB-ID
* Administrativ
    * Account aktiv,
    * Bereiche,
    * Admin-Privilegien,
    * Admin-Notizen
    * E-Mail
* Veranstaltungsbezogen
    * Geburtsdatum,
    * Geschlecht,
    * E-Mail
    * Telefon,
    * Mobiltelefon,
    * Adresse
* Mitglieder
    * Geburtsname,
    * Geburtsdatum,
    * E-Mail
    * Telefon,
    * Mobiltelefon,
    * WWW,
    * Adresse,
    * Zweitadresse,
    * Fachgebiet,
    * Schule, Uni, …,
    * Jahrgang, Matrikel, …,
    * Interessen,
    * Sonstiges,
    * Verg. Veranstaltungen
* CdE Admin
    * Geschlecht,
    * Mitgliedschaft,
    * Guthaben,
    * Sichtbarkeit

Darüber hinaus gibt es die sogenannte ``Änderungshistorie`` eines Benutzers.
In dieser werden die Änderungen an einem Benutzerprofil gespeichert.
Diese ist lediglich Core-Admins zugänglich.


Welche Arten von Benutzern gibt es?
-----------------------------------

Es gibt folgende Arten von Benutzern:

* Aktive Benutzer:
    Alle Benutzer, die nicht deaktiviert oder archiviert sind.
* Deaktivierte Benutzer:
    Haben das Recht entzogen bekommen, sich in die Datenbank einzuloggen.
    Ansonsten verhalten sie sich äquivalent zu Benutzern.
* Archivierte Benutzer:
    Haben keine Rechte mehr in der Datenbank. Beim Archivieren eines
    Accounts werden weitestgehend alle Daten dieses Benutzers gelöscht.
    Erhalten bleiben Name, Geschlecht, Geburtsdatum, Verg. Veranstaltungen
    (soweit vorhanden) sowie Accounttyp. Sie können sich nicht mehr
    einloggen *und* können nicht mehr von anderen Benutzern (ausgenommen
    Core-Admins und Admins im zugeordneten Bereich) aufgerufen werden.

Zudem müssen wir im Datenschutz Kontext folgende Kriterien an Benutzer
unterscheiden:

* Kriterien, die **den Benutzer** berechtigen können, Daten einzusehen:

  * Bereiche, in denen der Benutzer Admin Rechte besitzt
  * ist der Benutzer Orga einer Veranstaltung?
  * ist der Benutzer Moderator einer Mailingliste?
  * ist der Benutzer Mitglied *und* Suchbar?
  * ist der Benutzer nicht deaktiviert?

* Kriterien, die **andere Nutzer** berechtigen können, Daten des Benutzers einzusehen:

  * Bereiche, die dieser Benutzer besitzt
  * ist der Benutzer Teilnehmer einer Veranstaltung?
  * ist der Benutzer Abonent einer Mailingliste?
  * ist der Benutzer Mitglied *und* Suchbar?
  * ist der Benutzer nicht archiviert?


Welche Arten von Admins gibt es?
--------------------------------

In der folgenden Betrachtung wird der Core Admin ausgeklammert, da dieser
**vollständigen** Zugriff auf **jeden** Benutzer hat.

Jeder der Bereiche Mailinglisten, Versammlungen, Veranstaltungen und CdE besitzt
eine Admin Rolle. Jedoch darf immer nur die "höchste" Admin Rolle (der sogn.
"relative Admin") einen (nicht archivierten) Benutzer auch tatsächlich einsehen.
Dieser wird an der Gesamtmenge an Bereichen festgemacht, die ein Benutzer
besitzt (das maximale Element der Bereiche):

* Mailinglisten:
    Besitzt ein Benutzer nur den Mailinglisten Bereich, ist dies der
    Mailinglisten Admin
* Veranstaltungen und Versammlungen:
    Hier sind Veranstaltungen und Versammlungen beide maximal: Besitzt ein
    Benutzer also Mailinglisten und (Veranstaltungen oder / und Versammlungs)
    Bereich, dürfen Veranstaltungs oder Versammlungsadmin bzw beide diesen
    Benutzer einsehen.
* CdE:
    Besitzt ein Benutzer den CdE Bereich, ist automatisch nur der CdE-Admin
    relativer Admin.

Alle User mit Admin Rechten sind unter ``Core/Administratorenübersicht``
aufgelistet.




Wer darf nun was sehen?
-----------------------

Wir gehen anhand der Eigenschaften eines Benutzers durch, welche Felder dieser
auf den Profilen anderer Benutzer sehen darf.

* Deaktivierte oder Archivierte Benutzer
    Diese haben beide nicht das Recht, sich in die Datenbank einzuloggen, können
    dementsprechend auch keine anderen Benutzer einsehen. Zudem können
    archivierte Benutzer auch nicht von anderen Benutzern (ausgenommen Core
    Admins) gesehen werden. Deaktivierte Nutzer dagegen verhalten sich für
    andere wie ein äquivalenter aktiver Benutzer.

      * Deaktiviert: Niemanden
      * Archiviert: Niemanden, kann von niemandem (außer Core Admin) gesehen
        werden

* Grundlegend
    Jeder aktive Benutzer kann die grundlegenden Informationen über jeden
    nicht-archivierten Nutzer sehen. Damit diese nicht systematisch ausgelesen werden
    können, ist der Zugriff auf ein Profil generell mit einem Encode-Parameter
    im Link zu einem Profil geschützt.

      * Jeder aktive Benutzer: "Grundlegend"

* Orgas und Moderatoren
    Ist der Benutzer bei einer Veranstaltung registriert bzw auf einer
    Mailingliste eingeschrieben, haben die jeweiligen Orgas bzw Moderatoren
    Zugriff auf folgende Kategorien:

      * Orgas: "Veranstaltungsbezogen"
      * Moderatoren: Das Feld "E-Mail"

    Veranstaltungs-Admins haben vollen Zugriff auf alle Veranstaltungen, als
    wären sie Orgas. Mailinglisten-Admins haben vollen Zugriff auf alle
    Mailinglisten, als wären sie Moderatoren.

    Darüber hinaus haben einige Admins vollen Zugriff auf alle ihnen
    zugeordneten Mailinglisten. Für Veranstaltungs-, bzw. Versammlungs-Admins
    sind dies alle Veranstaltungs-, bzw. Versammlungs-Mailinglisten.
    Für CdE-Admins sind dies allgemeine Mitglieder-Mailinglisten wie cde-info
    sowie alle Teamlisten. CdE-Lokal-Admins haben Zugriff auf alle
    CdE-Lokal-Mailinglisten.

* relative Admins
    Jeder Benutzer darf von seinem relativen Admin(s) eingesehen werden. Diese
    haben dabei Zugriff auf die Kategorien "Administrativ" sowie

      * Veranstaltungs Admin: "Veranstaltungsbezogen"
      * CdE Admin: "Mitglieder" und "CdE Admin"

    Darüber hinaus existiert die Rolle des Meta-Admins. Dieser allein hat das
    Recht, Admin Rechte zu vergeben und zu entziehen. Dazu hat er bei **ALLEN**
    Nutzern Zugriff auf:

      * Meta Admin: "Administrativ"

* Mitglieder
    Mitglieder sind Benutzer, die den CdE-Bereich besitzen und darüber hinaus
    das Attribut "Mitglied" haben (≙ ihren Mitgliedsbeitrag für das laufende
    Semester bezahlt haben). Darüber hinaus können sie der Datenschutzerklärung
    zustimmen. Tuen Sie dies, erhalten sie weiterhin das Attribut "Suchbar".
    Mitglieder, die diese beiden Attribute besitzen, erhalten erweiterten
    Zugriff auf andere Mitglieder, die ebenfalls diese beiden Attribute besitzen.
    Der Zugriff ist durch ein tägliches Limit von maximal 42 Zugriffen auf
    fremde Profile beschränkt.

      * Mitglied *und* Suchbar: "Mitglieder"

* Man selbst
    Jeder aktive Benutzer hat fast vollständigen Zugriff auf sein eigenes Profil.
    Außgenommen hiervon sind die Admin-Notizen und die ``Änderungshistorie``.
    Deaktivierte und archivierte Benutzer können Ihr eigenes Profil nicht sehen,
    da sie sich nicht einloggen können.

      * Man selbst: Alle Felder des eigenen Profils, ausgenommen Admin-Notizen

* Core Admins
    Der Core Admin hat **vollen** Zugriff auf **alle** (aktiven, deaktiverten
    und archiverten) Benutzer.

      * Core Admin: Alle Felder auf allen Profilen


Technische Details zu den Profilseiten
--------------------------------------

In diesem Abschnitt werden die technischen Maßnahmen zum Schutz der
Benutzerprofile erläutert.

Verlinkung
^^^^^^^^^^

Die Profilseiten sind jeweils mit einem zufälligen Link versehen. Dies
bedeutet, dass der Link nicht geraten werden kann, selbst wenn der
Betrachter die interne ID eines Profils kennt, sondern von der DB
herausgegeben werden muss. Insbesondere ist es also nicht möglich, einfach
alle Links ohne Hilfe der DB zu generieren.

Die DB stellt an einigen Stellen diese Links im Rahmen ihrer ganz normalen
Funktionalität zur Verfügung. Es gibt aber nur eine einzige Stelle an der
diese für normale Nutzer in großer Zahl generierbar sind: die
Mitgliedersuche.

Die Mitgliedersuche schränkt einerseits die Anzahl der angezeigten Treffer
ein und erlaubt andererseits keine sehr unspezifischen Anfragen (etwa alle
Namen die ein "e" enthalten). Dadurch wird die systematische Generierung der
Links erschwert.

Quota
^^^^^

Außerdem nehmen wir an, dass jede Person nur eine überschaubare Anzahl an
Profilen pro Zeitintervall betrachten möchte. Daher gibt es eine Quota, die
verhindert, dass mehr Zugriffe erfolgen. Dies ist der wesentliche technische
Schutzmechanismus, der verhindert, dass jemand die Profildaten aus der DB
extrahiert.
