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
* Veranstatlungsbezogen
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


Welche Arten von Benutzern gibt es?
-----------------------------------

Es gibt folgende Arten von Benutzern:

* Aktive Benutzer:
    Alle Benutzer, die nicht deaktiviert oder archiviert sind.
* Deaktivierte Benutzer:
    Haben das Recht entzogen bekommen, sich in die Datenbank einzuloggen.
    Ansonsten verhalten sie sich äquivalent zu Benutzern.
* Archivierte Benutzer:
    Haben das Recht entzogen bekommen, sich einzuloggen, *und* können nicht
    mehr von anderen Benutzern (ausgenommen Core Admins) aufgerufen werden.

Zudem müssen wir im Datenschutz Kontext folgende Kriterien an Benutzer
unterscheiden:

* Kriterien, die **den Benutzer** berechtigen, Daten einzusehen:

  * Bereiche, in denen der Benutzer Admin Rechte besitzt
  * Orga einer Veranstaltung
  * Moderator einer Mailingliste
  * ist der Benutzer Mitglied *und* Suchbar?
  * ist der Benutzer deaktiviert?

* Kriterien, die **andere Benutzer** berechtigen, Daten des Nutzers einzusehen:

  * Bereiche, die dieser Benutzer besitzt
  * ist der Benutzer Mitglied *und* Suchbar?
  * ist der Benutzer archiviert?


Welche Arten von Admins gibt es?
--------------------------------

In der folgenden Betrachtung wird der Core Admin ausgeklammert, da dieser
**vollständigen** Zugriff auf **jeden** Benutzer hat.

Jeder der Bereiche Mailinglisten, Versammlungen, Veranstaltungen und CdE besitzt
eine Admin Rolle. Jedoch darf immer nur die "höchste" Admin Rolle (der sogn.
"relative Admin") einen (nicht archivierten) Benutzer auch tatsächlich einsehen.
Dies wird an der Gesamtmenge an Bereichen festgemacht, die ein Benutzer besitz
(das maximale Element der Bereiche):

* Mailinglisten:
    Besitzt ein Benutzer nur den Mailinglisten Bereich, ist dies der
    Mailinglisten Admin
* Veranstaltungen und Versammlungen:
    Hier sind Veranstaltungen und Versammlungen beide maximal: Besitz ein
    Benutzer also Mailinglisten und (Veranstaltungen oder / und Versammlungs)
    Bereich, dürfen Veranstaltungs oder Versammlungsadmin bzw beide diesen
    Benutzer einsehen.
* CdE:
    Besitz ein Benutzer den CdE Bereich, ist automatisch nur der CdE-Admin
    relativer Admin.




Wer darf nun was sehen?
-----------------------

Fangen wir von unten an, und gehen systematisch die Berechtigungen nach oben.

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
    Jeder aktive Benutzer kann die grundlegenden Informationen über jeden nicht-
    archivierten Nutzer sehen. Damit diese nicht systematisch ausgelesen werden
    können, ist der Zugriff auf ein Profil generell mit einem Encode-Parameter
    im Link zu einem Profil geschützt.

      * Jeder aktive Benutzer: "Grundlegend"

* Orgas und Moderatoren
    Ist der Benutzer bei einer Veranstaltung registriert bzw auf einer
    Mailingliste eingeschrieben, haben die jeweiligen Orgas bzw Moderatoren
    Zugriff auf folgenden Kategorien:

      * Orgas: "Veranstaltungsbezogen"
      * Moderatoren: Das Feld "E-Mail"

* relative Admins
    Jeder Benutzer darf von seinem relativen Admin(s) eingesehen werden. Diese
    haben dabei Zugriff auf die Kategorien "Administrativ" sowie

      * Veranstaltungs Admin: "Veranstaltungsbezogen"
      * CdE Admin: "Mitglieder" und "CdE Admin"

    Darüber hinaus existiert die Rolle des Meta-Admins. Dieser alleine hat das
    Recht, Admin Rechte zu vergeben und zu entziehen. Dazu hat er bei **ALLEN**
    Nutzern folgenden Zugriff:

      * Meta Admin: Die Felder "Bereiche" und "Admin-Privilegien"

* Mitglieder
    Mitglieder sind Benutzer, die den CdE-Bereich besitzen und darüber hinaus
    das Attribut "Mitglied" haben (=^ ihren Mitgliedsbeitrag für das laufende
    Semester bezahlt haben). Darüber hinaus können sie der Datenschutzerklärung
    zustimmen. Tuen Sie dies, erhalten sie weiterhin das Attribut "Suchbar".
    Mitglieder, die diese beiden Attribute besitzen, erhalten erweiterten
    Zugriff auf andere Mitglieder, die ebenfalls diese beiden Attribute besitzen.
    Der Zugriff ist durch ein tägliches Limit von maximal #TODO Limit
    referenzieren # Zugriffen auf fremde Profile beschränkt.

      * Mitglied *und* Suchbar: "Mitglieder"

* Man selbst
    Jeder aktive Benutzer hat vollen Zugriff auf sein eigenes Profil.
    Deaktivierte und archivierte Benutzer sind hiervon natürlich ausgenommen,
    da sie sich nicht einloggen können.

      * Man selbst: Alle Felder auf dem eigenen Profil

* Core Admins
    Der Core Admin hat **vollen** Zugriff auf **alle** (aktiven, deaktiverten
    und archiverten) Benutzer.

      * Core Admin: Alle Felder auf allen Profilen
