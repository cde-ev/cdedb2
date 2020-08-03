ALTER SEQUENCE IF EXISTS core.meta_info_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.cron_store_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.personas_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.changelog_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.privilege_changes_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.genesis_cases_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.sessions_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.quota_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS core.log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS cde.lastschrift_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS cde.lastschrift_transactions_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS cde.finance_log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS cde.log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS past_event.institutions_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS past_event.events_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS past_event.courses_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS past_event.participants_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS past_event.log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.events_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.event_parts_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.course_tracks_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.orgas_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.field_definitions_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.fee_modifiers_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.questionnaire_rows_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.courses_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.course_segments_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.lodgement_groups_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.lodgements_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.registrations_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.registration_parts_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.registration_tracks_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.course_choices_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS event.log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.assemblies_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.attendees_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.ballots_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.candidates_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.attachments_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.attachment_versions_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.votes_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.voter_register_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS assembly.log_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.mailinglists_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.moderators_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.whitelist_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.subscription_states_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.subscription_addresses_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS ml.log_id_seq RESTART WITH 1;
INSERT INTO core.meta_info (id, info) VALUES (1, '{
    "Vorstand": "Anton und Berta",
    "CdE_Konto_BIC": "BFSWDE33XXX",
    "CdE_Konto_IBAN": "DE26370205000008068900",
    "CdE_Konto_Inhaber": "CdE e.V.",
    "CdE_Konto_Institut": "Bank f\u00fcr Sozialwirtschaft",
    "Finanzvorstand_Ort": "Utopia",
    "banner_after_login": "*Dies ist eine Testversion der Datenbank, alles wird gel\u00f6scht werden!*",
    "banner_before_login": "Das Passwort ist secret!",
    "banner_genesis": "Bei Problemen mit der Accountanfrage wendet Euch bitte an die Verwaltung.",
    "cde_misc": null,
    "Finanzvorstand_Name": "Bert\u00e5lotta Beispiel",
    "Finanzvorstand_Vorname": "Bert\u00e5lotta",
    "Finanzvorstand_Adresse_Zeile2": "bei Spielmanns",
    "Finanzvorstand_Adresse_Zeile3": "Im Garten 77",
    "Finanzvorstand_Adresse_Zeile4": "34576 Utopia",
    "Finanzvorstand_Adresse_Einzeiler": "Bert\u00e5lotta Beispiel, bei Spielmanns, Im Garten 77, 34576 Utopia"
}');
INSERT INTO core.personas (id, postal_code, is_assembly_realm, birth_name, postal_code2, is_archived, foto, decided_search, is_event_admin, is_core_admin, family_name, affiliation, fulltext, is_finance_admin, username, balance, birthday, is_ml_admin, name_supplement, is_cde_admin, weblink, is_member, is_searchable, telephone, password_hash, address_supplement, location, is_assembly_admin, notes, location2, mobile, interests, bub_search, address_supplement2, paper_expuls, is_event_realm, timeline, display_name, is_active, free_form, is_meta_admin, is_ml_realm, country, specialisation, address2, address, country2, gender, is_cde_realm, trial_member, given_names, title) VALUES (1, '03205', true, NULL, '22335', false, NULL, true, true, true, 'Administrator', NULL, '1 anton@example.cde Anton Anton Armin A. Administrator 1991-03-30 +49 (234) 98765 Auf der Düne 42 03205 Musterstadt Unter dem Hügel 23 22335 Hintertupfingen', true, 'anton@example.cde', '17.50', '1991-03-30', true, NULL, true, NULL, true, true, '+49 (234) 98765', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Musterstadt', true, NULL, 'Hintertupfingen', NULL, NULL, true, NULL, true, true, NULL, 'Anton', true, NULL, true, true, NULL, NULL, 'Unter dem Hügel 23', 'Auf der Düne 42', NULL, 2, true, false, 'Anton Armin A.', NULL),
(2, '34576', true, 'Gemeinser', '8XA 45-$', false, 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', true, false, false, 'Beispiel', 'Jedermann', '2 Dr. berta@example.cde Bertå Bertålotta Beispiel Gemeinser MdB 1981-02-11 +49 (5432) 987654321 0163/123456789 bei Spielmanns Im Garten 77 34576 Utopia Strange Road 9 3/4 8XA 45-$ Foreign City Far Away https://www.bundestag.cde Alles
Und noch mehr Jedermann Überall Immer Jede Menge Gefasel  
Gut verteilt  
Über mehrere Zeilen', false, 'berta@example.cde', '12.50', '1981-02-11', false, 'MdB', false, 'https://www.bundestag.cde', true, true, '+49 (5432) 987654321', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'bei Spielmanns', 'Utopia', false, 'Beispielhaft, Besser, Baum.', 'Foreign City', '0163/123456789', 'Immer', true, NULL, true, true, 'Überall', 'Bertå', true, 'Jede Menge Gefasel  
Gut verteilt  
Über mehrere Zeilen', false, true, NULL, 'Alles
Und noch mehr', 'Strange Road 9 3/4', 'Im Garten 77', 'Far Away', 1, true, false, 'Bertålotta', 'Dr.'),
(3, '22969', true, NULL, NULL, false, NULL, true, false, false, 'Clown', NULL, '3 charly@example.cde Charly Charly C. Clown 1984-05-13 Am Zelt 1 22969 Zirkusstadt Ich bin ein "Künstler"; im weiteren Sinne.', false, 'charly@example.cde', '1.00', '1984-05-13', false, NULL, false, NULL, true, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Zirkusstadt', false, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Charly', true, 'Ich bin ein "Künstler"; im weiteren Sinne.', false, true, NULL, NULL, NULL, 'Am Zelt 1', NULL, 10, true, true, 'Charly C.', NULL),
(4, '76543', true, NULL, NULL, false, NULL, false, false, false, 'Dino', NULL, '4 daniel@example.cde Daniel Daniel D. Dino 1963-02-19 Am Denkmal 91 76543 Atlantis', false, 'daniel@example.cde', '0.00', '1963-02-19', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Atlantis', false, NULL, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Daniel', true, NULL, false, true, NULL, NULL, NULL, 'Am Denkmal 91', NULL, 2, true, false, 'Daniel D.', NULL),
(5, '56767', false, NULL, NULL, false, NULL, NULL, false, false, 'Eventis', NULL, '5 emilia@example.cde Emilia Emilia E. Eventis 2012-06-02 +49 (5432) 555666777 01577/314159 Hohle Gasse 13 56767 Wolkenkuckuksheim Deutschland', false, 'emilia@example.cde', NULL, '2012-06-02', false, NULL, false, NULL, false, false, '+49 (5432) 555666777', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Wolkenkuckuksheim', false, 'War früher mal berühmt, hat deswegen ihren Nachnamen geändert.', NULL, '01577/314159', NULL, NULL, NULL, NULL, true, NULL, 'Emilia', true, NULL, false, true, 'Deutschland', NULL, NULL, 'Hohle Gasse 13', NULL, 1, false, NULL, 'Emilia E.', NULL),
(6, '64354', true, NULL, NULL, false, NULL, true, true, false, 'Findus', NULL, '6 ferdinand@example.cde Ferdinand Ferdinand F. Findus 1988-01-01 Am Rathaus 1 64354 Burokratia', true, 'ferdinand@example.cde', '22.20', '1988-01-01', true, NULL, true, NULL, true, true, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Burokratia', true, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Ferdinand', true, NULL, false, true, NULL, NULL, NULL, 'Am Rathaus 1', NULL, 2, true, false, 'Ferdinand F.', NULL),
(7, '88484', true, NULL, NULL, false, NULL, false, false, false, 'Generalis', NULL, '7 garcia@example.cde Garcia Garcia G. Generalis 1978-12-12 Bei der Wüste 39 88484 Weltstadt', false, 'garcia@example.cde', '3.30', '1978-12-12', false, NULL, false, NULL, true, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Weltstadt', false, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Garcia', true, NULL, false, true, NULL, NULL, NULL, 'Bei der Wüste 39', NULL, 1, true, false, 'Garcia G.', NULL),
(8, NULL, false, 'Κόλαση', NULL, true, NULL, false, false, false, 'Hell', NULL, '8 Hades Hades Hell Κόλαση 1977-11-10', false, NULL, NULL, '1977-11-10', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, false, NULL, NULL, false, NULL, 'Hades', false, NULL, false, false, NULL, NULL, NULL, NULL, NULL, NULL, false, false, 'Hades', NULL),
(9, '10999', true, NULL, NULL, false, NULL, true, false, false, 'Iota', NULL, '9 inga@example.cde Inga Inga Iota 2222-01-01 0163/456897 Zwergstraße 1 10999 Liliput # Inga

Kleines Inhaltsverzeichnis

[TOC]

## Auslandsjahr

Ich war ein Jahr in Südafrika. Dort habe ich viele Dinge besucht.

  - den Nationalpark
  - verschiedene Städte

  1. Johannisburg
  2. Cape Town

## Literatur

Ich lese gerne

  - Vampirroman,
  - Wächter-Romane (nicht den >>Wachturm<<, das ist eine ganz schräge Zeitschrift von ziemlich dubiosen Typen),
  - Ikea-Anleitungen.

## Musik

Es gibt ganz viel schreckliche *Popmusik* und so viel bessere **klassische Musik**, beispielsweise ``Bach`` und ``Beethoven`` sind vorne dabei [^1].

## Programmieren

Mein Lieblingsprogramm:

    int main ( int argc, char *argv[] ) {
        printf("Hello World\n");
        return 0;
    }

Und hier gleich noch mal:

~~~~~~~~~~~~~~~~~~.c
int main ( int argc, char *argv[] ) {
    printf("Hello World\n");
    return 0;
}
~~~~~~~~~~~~~~~~~~

Aber alles, was etwas mit einem Buch aus Abschnitt `Literatur` zu tun hat ist auch gut.

## Referenzen

Der CdE ist voll cool und hat eine Homepage <http://www.cde-ev.de>{: .btn .btn-xs .btn-warning }. Dort kann man auch jederzeit gerne eine Akademie organisieren [^2]. Außerdem gibt es verschiedene Teams, die den Verein am laufen halten

Admin-Team
:  Kümmert sich um den Server für die Datenbank

Datenbank-Team
:  Entwickelt die Datenbank

Doku-Team
:  Druckt zu jeder Akademie ein Buch

<script>evil();</script>

-- --- ...  "" ''

[^1]: Über die Qualitäten von ``Mozart`` kann man streiten.
[^2]: Orga sein hat viele tolle Vorteile:

    - entscheide über die Schokoladensorten
    - suche Dir Dein Lieblingshaus aus
    - werde von allen Teilnehmern angehimmelt
    - lasse Dich bestechen

*[CdE]: Club der Ehemaligen', false, 'inga@example.cde', '5.00', '2222-01-01', false, NULL, false, NULL, true, true, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Liliput', false, NULL, NULL, '0163/456897', NULL, true, NULL, true, true, NULL, 'Inga', true, '# Inga

Kleines Inhaltsverzeichnis

[TOC]

## Auslandsjahr

Ich war ein Jahr in Südafrika. Dort habe ich viele Dinge besucht.

  - den Nationalpark
  - verschiedene Städte

  1. Johannisburg
  2. Cape Town

## Literatur

Ich lese gerne

  - Vampirroman,
  - Wächter-Romane (nicht den >>Wachturm<<, das ist eine ganz schräge Zeitschrift von ziemlich dubiosen Typen),
  - Ikea-Anleitungen.

## Musik

Es gibt ganz viel schreckliche *Popmusik* und so viel bessere **klassische Musik**, beispielsweise ``Bach`` und ``Beethoven`` sind vorne dabei [^1].

## Programmieren

Mein Lieblingsprogramm:

    int main ( int argc, char *argv[] ) {
        printf("Hello World\n");
        return 0;
    }

Und hier gleich noch mal:

~~~~~~~~~~~~~~~~~~.c
int main ( int argc, char *argv[] ) {
    printf("Hello World\n");
    return 0;
}
~~~~~~~~~~~~~~~~~~

Aber alles, was etwas mit einem Buch aus Abschnitt `Literatur` zu tun hat ist auch gut.

## Referenzen

Der CdE ist voll cool und hat eine Homepage <http://www.cde-ev.de>{: .btn .btn-xs .btn-warning }. Dort kann man auch jederzeit gerne eine Akademie organisieren [^2]. Außerdem gibt es verschiedene Teams, die den Verein am laufen halten

Admin-Team
:  Kümmert sich um den Server für die Datenbank

Datenbank-Team
:  Entwickelt die Datenbank

Doku-Team
:  Druckt zu jeder Akademie ein Buch

<script>evil();</script>

-- --- ...  "" ''

[^1]: Über die Qualitäten von ``Mozart`` kann man streiten.
[^2]: Orga sein hat viele tolle Vorteile:

    - entscheide über die Schokoladensorten
    - suche Dir Dein Lieblingshaus aus
    - werde von allen Teilnehmern angehimmelt
    - lasse Dich bestechen

*[CdE]: Club der Ehemaligen', false, true, NULL, NULL, NULL, 'Zwergstraße 1', NULL, 1, true, true, 'Inga', NULL),
(10, NULL, false, NULL, NULL, false, NULL, NULL, false, false, 'Jalapeño', NULL, '10 janis@example.cde Janis Janis Jalapeño', false, 'janis@example.cde', NULL, NULL, false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, 'sharp tongue', NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Janis', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Janis', NULL),
(11, NULL, true, NULL, NULL, false, NULL, NULL, false, false, 'Karabatschi', NULL, '11 kalif@example.cde Kalif Kalif ibn al-Ḥasan Karabatschi', false, 'kalif@example.cde', NULL, NULL, false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, 'represents our foreign friends', NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Kalif', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Kalif ibn al-Ḥasan', NULL),
(12, NULL, true, NULL, NULL, false, NULL, true, false, false, 'Lost', NULL, '12 Lisa Lisa Lost', false, NULL, '50.00', NULL, false, NULL, false, NULL, true, true, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Lisa', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 1, true, true, 'Lisa', NULL),
(13, NULL, true, NULL, NULL, false, NULL, true, false, false, 'Meister', NULL, '13 martin@example.cde Martin Martin Meister 2019-07-10', false, 'martin@example.cde', '25.00', '2019-07-10', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Martin', true, NULL, true, true, NULL, NULL, NULL, NULL, NULL, 2, true, false, 'Martin', NULL),
(14, NULL, false, NULL, NULL, false, NULL, NULL, false, false, 'Neubauer', NULL, '14 nina@example.cde Nina Nina Neubauer 2020-03-12', false, 'nina@example.cde', NULL, '2020-03-12', true, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Nina', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 1, false, NULL, 'Nina', NULL),
(15, NULL, true, NULL, NULL, false, NULL, true, false, false, 'Olafson', NULL, '15 Prof. olaf@example.cde Olaf Olaf Olafson 1979-07-06', false, 'olaf@example.cde', '50.12', '1979-07-06', false, NULL, true, NULL, true, true, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, 'Aktuell deaktiviert weil er seine Admin-Rechte missbraucht, um Benutzer in ihrem Profil zu Rickrollen.', NULL, NULL, NULL, false, NULL, true, true, NULL, 'Olaf', false, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 2, true, false, 'Olaf', 'Prof.'),
(16, NULL, true, NULL, NULL, false, NULL, true, false, true, 'Panther', NULL, '16 paulchen@example.cde Paul Paulchen Panther 1963-12-19 California Street 1 Burbank California, USA Painting. Pre movie 1963, Oscar 1964 Well, pink. Think Pink!', false, 'paulchen@example.cde', '10.75', '1963-12-19', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Burbank', false, NULL, NULL, NULL, 'Well, pink.', false, NULL, true, true, 'Pre movie 1963, Oscar 1964', 'Paul', true, 'Think Pink!', false, true, 'California, USA', 'Painting.', NULL, 'California Street 1', NULL, 2, true, false, 'Paulchen', NULL),
(17, NULL, true, NULL, NULL, false, NULL, true, false, false, 'da Quirm', NULL, '17 Prof. Dr. quintus@example.cde Quintus Quintus da Quirm 1955-05-05 Oberster Stock, zweite Tür links Straße Schlauer Kunsthandwerker 42 Ankh-Morpork Scheibenwelt  Absolvent der Alchemisten-, Architekten- und Uhrmachergilde 1965, Ehrenmitglied der meisten anderen  Quasi alles.', false, 'quintus@example.cde', '5.55', '1955-05-05', false, NULL, true, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Oberster Stock, zweite Tür links', 'Ankh-Morpork', false, NULL, NULL, NULL, 'Quasi alles.', false, NULL, true, true, 'Absolvent der Alchemisten-, Architekten- und Uhrmachergilde 1965, Ehrenmitglied der meisten anderen ', 'Quintus', true, NULL, false, true, 'Scheibenwelt', '', NULL, 'Straße Schlauer Kunsthandwerker 42', NULL, 2, true, false, 'Quintus', 'Prof. Dr.'),
(18, 'EH44 6PX', true, NULL, NULL, false, NULL, true, false, false, 'Ravenclaw', NULL, '18 Lady rowena@example.cde Rowena Rowena Ravenclaw 932-08-31 Glen House EH44 6PX Innerleithen Scotland ', false, 'rowena@example.cde', NULL, '932-08-31', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Innerleithen', false, NULL, NULL, NULL, NULL, false, NULL, NULL, true, NULL, 'Rowena', true, NULL, false, true, 'Scotland', '', NULL, 'Glen House', NULL, 1, false, false, 'Rowena', 'Lady'),
(22, NULL, true, NULL, NULL, false, NULL, true, false, true, 'Verwaltung', NULL, '22 vera@example.cde Vera Vera Verwaltung 1989-11-09', false, 'vera@example.cde', '26.77', '1989-11-09', false, NULL, true, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Vera', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 1, true, false, 'Vera', NULL),
(23, NULL, true, NULL, NULL, false, NULL, true, false, false, 'Wahlleitung', NULL, '23 Dr. med. werner@example.cde Werner Werner Wahlleitung 2001-09-11', false, 'werner@example.cde', '10.04', '2001-09-11', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, true, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Werner', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 2, true, false, 'Werner', 'Dr. med.'),
(27, NULL, true, NULL, NULL, false, NULL, true, true, false, 'Akademieteam', NULL, '27 annika@example.cde Annika Annika Akademieteam 1966-04-17', false, 'annika@example.cde', '417.00', '1966-04-17', false, NULL, false, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, false, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Annika', true, NULL, false, true, NULL, NULL, NULL, NULL, NULL, 1, true, false, 'Annika', NULL),
(32, NULL, true, NULL, NULL, false, NULL, true, true, true, 'Finanzvorstand', NULL, '32 farin@example.cde Farin Farin Finanzvorstand 1963-10-27 Ich Fahr in Urlaub!', true, 'farin@example.cde', '56.00', '1963-10-27', true, NULL, true, NULL, false, false, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, NULL, true, NULL, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Farin', true, 'Ich Fahr in Urlaub!', false, true, NULL, NULL, NULL, NULL, NULL, 2, true, false, 'Farin', NULL),
(100, NULL, true, NULL, NULL, false, NULL, true, true, true, 'Abukara', NULL, '100 akira@example.cde Akira Akira Abukara 2019-12-28 +81 (314) 159263 Kasumigaseki 1-3-2 Tokyo Japan', true, 'akira@example.cde', '3.14', '2019-12-28', true, NULL, true, NULL, true, true, '+81 (314) 159263', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', NULL, 'Tokyo', true, NULL, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Akira', true, NULL, true, true, 'Japan', NULL, NULL, 'Kasumigaseki 1-3-2', NULL, 10, true, false, 'Akira', NULL);
INSERT INTO core.changelog (id, postal_code, is_assembly_realm, birth_name, postal_code2, is_archived, foto, change_status, is_event_admin, is_core_admin, family_name, affiliation, decided_search, is_finance_admin, username, persona_id, balance, birthday, is_ml_admin, name_supplement, is_cde_admin, weblink, is_member, reviewed_by, ctime, is_searchable, telephone, address_supplement, location, submitted_by, notes, is_assembly_admin, generation, location2, mobile, interests, bub_search, address_supplement2, paper_expuls, is_event_realm, timeline, display_name, is_active, free_form, is_meta_admin, is_ml_realm, country, change_note, address2, specialisation, address, country2, gender, is_cde_realm, trial_member, given_names, title) VALUES (1, '03205', true, NULL, '22335', false, NULL, 2, true, true, 'Administrator', NULL, true, true, 'anton@example.cde', 1, '17.50', '1991-03-30', true, NULL, true, NULL, true, NULL, now(), true, '+49 (234) 98765', NULL, 'Musterstadt', 1, NULL, true, 1, 'Hintertupfingen', NULL, NULL, true, NULL, true, true, NULL, 'Anton', true, NULL, true, true, NULL, 'Init.', 'Unter dem Hügel 23', NULL, 'Auf der Düne 42', NULL, 2, true, false, 'Anton Armin A.', NULL),
(2, '34576', true, 'Gemeinser', '8XA 45-$', false, 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', 2, false, false, 'Beispiel', 'Jedermann', true, false, 'berta@example.cde', 2, '12.50', '1981-02-11', false, 'MdB', false, 'https://www.bundestag.cde', true, NULL, now(), true, '+49 (5432) 987654321', 'bei Spielmanns', 'Utopia', 2, 'Beispielhaft, Besser, Baum.', false, 1, 'Foreign City', '0163/123456789', 'Immer', true, NULL, true, true, 'Überall', 'Bertå', true, 'Jede Menge Gefasel  
Gut verteilt  
Über mehrere Zeilen', false, true, NULL, 'Init.', 'Strange Road 9 3/4', 'Alles
Und noch mehr', 'Im Garten 77', 'Far Away', 1, true, false, 'Bertålotta', 'Dr.'),
(3, '22969', true, NULL, NULL, false, NULL, 2, false, false, 'Clown', NULL, true, false, 'charly@example.cde', 3, '1.00', '1984-05-13', false, NULL, false, NULL, true, NULL, now(), false, NULL, NULL, 'Zirkusstadt', 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Charly', true, 'Ich bin ein "Künstler"; im weiteren Sinne.', false, true, NULL, 'Init.', NULL, NULL, 'Am Zelt 1', NULL, 10, true, true, 'Charly C.', NULL),
(4, '76543', true, NULL, NULL, false, NULL, 2, false, false, 'Dino', NULL, false, false, 'daniel@example.cde', 4, '0.00', '1963-02-19', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, 'Atlantis', 1, NULL, false, 1, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Daniel', true, NULL, false, true, NULL, 'Init.', NULL, NULL, 'Am Denkmal 91', NULL, 2, true, false, 'Daniel D.', NULL),
(5, '56767', false, NULL, NULL, false, NULL, 2, false, false, 'Eventis', NULL, NULL, false, 'emilia@example.cde', 5, NULL, '2012-06-02', false, NULL, false, NULL, false, NULL, now(), false, '+49 (5432) 555666777', NULL, 'Wolkenkuckuksheim', 1, 'War früher mal berühmt, hat deswegen ihren Nachnamen geändert.', false, 1, NULL, '01577/314159', NULL, NULL, NULL, NULL, true, NULL, 'Emilia', true, NULL, false, true, 'Deutschland', 'Init.', NULL, NULL, 'Hohle Gasse 13', NULL, 1, false, NULL, 'Emilia E.', NULL),
(6, '64354', true, NULL, NULL, false, NULL, 2, true, false, 'Findus', NULL, true, true, 'ferdinand@example.cde', 6, '22.20', '1988-01-01', true, NULL, true, NULL, true, NULL, now(), true, NULL, NULL, 'Burokratia', 1, NULL, true, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Ferdinand', true, NULL, false, true, NULL, 'Init.', NULL, NULL, 'Am Rathaus 1', NULL, 2, true, false, 'Ferdinand F.', NULL),
(7, '88484', true, NULL, NULL, false, NULL, 2, false, false, 'Generalis', NULL, false, false, 'garcia@example.cde', 7, '3.30', '1978-12-12', false, NULL, false, NULL, true, NULL, now(), false, NULL, NULL, 'Weltstadt', 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Garcia', true, NULL, false, true, NULL, 'Init.', NULL, NULL, 'Bei der Wüste 39', NULL, 1, true, false, 'Garcia G.', NULL),
(8, NULL, false, 'Κόλαση', NULL, true, NULL, 2, false, false, 'Hell', NULL, false, false, NULL, 8, NULL, '1977-11-10', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, NULL, false, NULL, 'Hades', false, NULL, false, false, NULL, 'Init.', NULL, NULL, NULL, NULL, NULL, false, false, 'Hades', NULL),
(9, '10999', true, NULL, NULL, false, NULL, 2, false, false, 'Iota', NULL, true, false, 'inga@example.cde', 9, '5.00', '2222-01-01', false, NULL, false, NULL, true, NULL, now(), true, NULL, NULL, 'Liliput', 1, NULL, false, 1, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Inga', true, '# Inga

Kleines Inhaltsverzeichnis

[TOC]

## Auslandsjahr

Ich war ein Jahr in Südafrika. Dort habe ich viele Dinge besucht.

  - den Nationalpark
  - verschiedene Städte

  1. Johannisburg
  2. Cape Town

## Literatur

Ich lese gerne

  - Vampirroman,
  - Wächter-Romane (nicht den >>Wachturm<<, das ist eine ganz schräge Zeitschrift von ziemlich dubiosen Typen),
  - Ikea-Anleitungen.

## Musik

Es gibt ganz viel schreckliche *Popmusik* und so viel bessere **klassische Musik**, beispielsweise ``Bach`` und ``Beethoven`` sind vorne dabei [^1].

## Programmieren

Mein Lieblingsprogramm:

    int main ( int argc, char *argv[] ) {
        printf("Hello World\n");
        return 0;
    }

Und hier gleich noch mal:

~~~~~~~~~~~~~~~~~~.c
int main ( int argc, char *argv[] ) {
    printf("Hello World\n");
    return 0;
}
~~~~~~~~~~~~~~~~~~

Aber alles, was etwas mit einem Buch aus Abschnitt `Literatur` zu tun hat ist auch gut.

## Referenzen

Der CdE ist voll cool und hat eine Homepage <http://www.cde-ev.de>{: .btn .btn-xs .btn-warning }. Dort kann man auch jederzeit gerne eine Akademie organisieren [^2]. Außerdem gibt es verschiedene Teams, die den Verein am laufen halten

Admin-Team
:  Kümmert sich um den Server für die Datenbank

Datenbank-Team
:  Entwickelt die Datenbank

Doku-Team
:  Druckt zu jeder Akademie ein Buch

<script>evil();</script>

-- --- ...  "" ''

[^1]: Über die Qualitäten von ``Mozart`` kann man streiten.
[^2]: Orga sein hat viele tolle Vorteile:

    - entscheide über die Schokoladensorten
    - suche Dir Dein Lieblingshaus aus
    - werde von allen Teilnehmern angehimmelt
    - lasse Dich bestechen

*[CdE]: Club der Ehemaligen', false, true, NULL, 'Init.', NULL, NULL, 'Zwergstraße 1', NULL, 1, true, true, 'Inga', NULL),
(10, NULL, false, NULL, NULL, false, NULL, 2, false, false, 'Jalapeño', NULL, NULL, false, 'janis@example.cde', 10, NULL, NULL, false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 1, 'sharp tongue', false, 1, NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Janis', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, NULL, false, NULL, 'Janis', NULL),
(11, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Karabatschi', NULL, NULL, false, 'kalif@example.cde', 11, NULL, NULL, false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 1, 'represents our foreign friends', false, 1, NULL, NULL, NULL, NULL, NULL, NULL, false, NULL, 'Kalif', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, NULL, false, NULL, 'Kalif ibn al-Ḥasan', NULL),
(12, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Lost', NULL, true, false, NULL, 12, '50.00', NULL, false, NULL, false, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Lisa', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 1, true, true, 'Lisa', NULL),
(13, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Meister', NULL, true, false, 'martin@example.cde', 13, '25.00', '2019-07-10', false, NULL, false, NULL, true, NULL, now(), false, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Martin', true, NULL, true, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 2, true, false, 'Martin', NULL),
(14, NULL, false, NULL, NULL, false, NULL, 2, false, false, 'Neubauer', NULL, NULL, false, 'nina@example.cde', 14, NULL, NULL, true, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, NULL, NULL, NULL, true, NULL, 'Nina', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 1, false, NULL, 'Nina', NULL),
(15, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Olafson', NULL, true, false, 'olaf@example.cde', 15, '50.12', '1979-07-06', false, NULL, true, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Olaf', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 2, true, false, 'Olaf', 'Prof.'),
(16, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Olaf', NULL, true, false, 'olaf@example.cde', 15, '50.12', '1979-07-06', false, NULL, true, NULL, true, NULL, now(), true, NULL, NULL, NULL, 6, 'Aktuell deaktiviert weil er seine Admin-Rechte missbraucht, um Benutzer in ihrem Profil zu Rickrollen.', false, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Olaf', false, NULL, false, true, NULL, 'Deaktiviert, weil er seine Admin-Privilegien missbraucht.', NULL, NULL, NULL, NULL, 2, true, false, 'Olafson', 'Prof.'),
(17, NULL, true, NULL, NULL, false, NULL, 2, false, true, 'Verwaltung', NULL, true, false, 'vera@example.cde', 22, '26.77', '1989-11-09', false, NULL, true, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Vera', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 1, true, false, 'Vera', NULL),
(18, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Wahlleitung', NULL, true, false, 'werner@example.cde', 23, '10.04', '2001-09-11', false, NULL, false, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, true, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Werner', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 2, true, false, 'Werner', 'Dr. med.'),
(19, NULL, true, NULL, NULL, false, NULL, 2, true, false, 'Akademieteam', NULL, true, false, 'annika@example.cde', 27, '417.00', '1966-04-17', false, NULL, false, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Annika', true, NULL, false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 1, true, false, 'Annika', NULL),
(20, NULL, true, NULL, NULL, false, NULL, 2, true, true, 'Finanzvorstand', NULL, true, true, 'farin@example.cde', 32, '56.00', '1963-10-27', true, NULL, true, NULL, true, NULL, now(), true, NULL, NULL, NULL, 1, NULL, true, 1, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Farin', true, 'Ich Fahr in Urlaub!', false, true, NULL, 'Init.', NULL, NULL, NULL, NULL, 2, true, false, 'Farin', NULL),
(21, NULL, true, NULL, NULL, false, NULL, 2, true, true, 'Abukara', NULL, true, true, 'akira@example.cde', 100, '3.14', '2019-12-28', true, NULL, true, NULL, true, NULL, now(), true, '+81 (314) 159263', NULL, 'Tokyo', 1, NULL, true, 1, NULL, NULL, NULL, true, NULL, true, true, NULL, 'Akira', true, NULL, true, true, 'Japan', 'Init.', NULL, NULL, 'Kasumigaseki 1-3-2', NULL, 10, true, false, 'Akira', NULL),
(22, NULL, true, NULL, NULL, false, NULL, 2, false, true, 'Panther', NULL, true, false, 'paulchen@example.cde', 16, '0.75', '1963-12-19', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, 'Burbank', 1, NULL, false, 1, NULL, NULL, 'Well, pink.', false, NULL, true, true, 'Pre movie 1963, Oscar 1964', 'Paul', true, 'Think Pink!', false, true, 'California, USA', 'Init.', NULL, 'Painting.', 'California Street 1', NULL, 2, true, false, 'Paulchen', NULL),
(23, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'da Quirm', NULL, true, false, 'quintus@example.cde', 17, '5.55', '1955-05-05', false, NULL, true, NULL, true, NULL, now(), false, NULL, 'Oberster Stock, zweite Tür links', 'Ankh-Morpork', 1, NULL, false, 1, NULL, NULL, 'Quasi alles.', false, NULL, true, true, 'Absolvent der Alchemisten-, Architekten- und Uhrmachergilde 1965, Ehrenmitglied der meisten anderen ', 'Quintus', true, NULL, false, true, 'Scheibenwelt', 'Init.', NULL, '', 'Straße Schlauer Kunsthandwerker 42', NULL, 2, true, false, 'Quintus', 'Prof. Dr.'),
(24, 'EH44 6PX', true, NULL, NULL, false, NULL, 2, false, false, 'Ravenclaw', NULL, true, false, 'rowena@example.cde', 18, NULL, '932-08-31', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, 'Innerleithen', 1, NULL, false, 1, NULL, NULL, NULL, false, NULL, NULL, true, NULL, 'Rowena', true, NULL, false, true, 'Scotland', 'Init.', NULL, '', 'Glen House', NULL, 1, false, false, 'Rowena', 'Lady'),
(25, NULL, true, NULL, NULL, false, NULL, 2, false, true, 'Verwaltung', NULL, true, false, 'vera@example.cde', 22, '26.77', '1989-11-09', false, NULL, true, NULL, false, NULL, now(), false, NULL, NULL, NULL, 100, NULL, false, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Vera', true, NULL, false, true, NULL, 'Zu Testzwecken Mitgliedschaft und Suchbarkeit entzogen.', NULL, NULL, NULL, NULL, 1, true, false, 'Vera', NULL),
(26, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Wahlleitung', NULL, true, false, 'werner@example.cde', 23, '10.04', '2001-09-11', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 100, NULL, true, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Werner', true, NULL, false, true, NULL, 'Zu Testzwecken Mitgliedschaft und Suchbarkeit entzogen.', NULL, NULL, NULL, NULL, 2, true, false, 'Werner', 'Dr. med.'),
(27, NULL, true, NULL, NULL, false, NULL, 2, true, false, 'Akademieteam', NULL, true, false, 'annika@example.cde', 27, '417.00', '1966-04-17', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 100, NULL, false, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Annika', true, NULL, false, true, NULL, 'Zu Testzwecken Mitgliedschaft und Suchbarkeit entzogen.', NULL, NULL, NULL, NULL, 1, true, false, 'Annika', NULL),
(28, NULL, true, NULL, NULL, false, NULL, 2, true, true, 'Finanzvorstand', NULL, true, true, 'farin@example.cde', 32, '56.00', '1963-10-27', true, NULL, true, NULL, false, NULL, now(), false, NULL, NULL, NULL, 100, NULL, true, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Farin', true, 'Ich Fahr in Urlaub!', false, true, NULL, 'Zu Testzwecken Mitgliedschaft und Suchbarkeit entzogen.', NULL, NULL, NULL, NULL, 2, true, false, 'Farin', NULL),
(29, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'Meister', NULL, true, false, 'martin@example.cde', 13, '25.00', '2019-07-10', false, NULL, false, NULL, false, NULL, now(), false, NULL, NULL, NULL, 100, NULL, false, 2, NULL, NULL, NULL, false, NULL, true, true, NULL, 'Martin', true, NULL, true, true, NULL, 'Zu Testzwecken Mitgliedschaft entzogen.', NULL, NULL, NULL, NULL, 2, true, false, 'Martin', NULL),
(30, NULL, true, NULL, NULL, false, NULL, 2, false, false, 'da Quirm', NULL, true, false, 'quintus@example.cde', 17, '5.55', '1955-05-05', false, NULL, true, NULL, false, NULL, now(), false, NULL, 'Oberster Stock, zweite Tür links', 'Ankh-Morpork', 100, NULL, false, 2, NULL, NULL, 'Quasi alles.', false, NULL, true, true, 'Absolvent der Alchemisten-, Architekten- und Uhrmachergilde 1965, Ehrenmitglied der meisten anderen ', 'Quintus', true, NULL, false, true, 'Scheibenwelt', 'Zu Testzwecken Mitgliedschaft entzogen.', NULL, '', 'Straße Schlauer Kunsthandwerker 42', NULL, 2, true, false, 'Quintus', 'Prof. Dr.');
INSERT INTO cde.org_period (ejection_state, id, balance_state, ejection_done, billing_state, balance_total, balance_trialmembers, ejection_balance, balance_done, ejection_count, billing_done) VALUES (NULL, 41, NULL, '2000-01-12T10:11:11.111111+00:00', NULL, '0.00', 0, '0.00', '2000-01-13T10:11:11.111111+00:00', 0, '2000-01-11T10:11:11.111111+00:00'),
(NULL, 42, NULL, now(), NULL, '0.00', 0, '0.00', now(), 0, now()),
(NULL, 43, NULL, NULL, NULL, '0.00', 0, '0.00', NULL, 0, NULL);
INSERT INTO cde.expuls_period (id, addresscheck_done, addresscheck_state) VALUES (41, now(), NULL),
(42, NULL, NULL);
INSERT INTO cde.lastschrift (revoked_at, submitted_by, id, iban, account_owner, notes, account_address, amount, persona_id, granted_at) VALUES ('2001-02-22T20:22:22.222222+00:00', 1, 1, 'DE26370205000008068900', NULL, NULL, NULL, '32.00', 2, '2000-02-22T20:22:22.222222+00:00'),
(NULL, 1, 2, 'DE12500105170648489890', 'Dagobert Anatidae', 'reicher Onkel', 'Im Geldspeicher 1', '42.23', 2, '2002-02-22T20:22:22.222222+00:00');
INSERT INTO cde.lastschrift_transactions (submitted_by, id, lastschrift_id, issued_at, amount, processed_at, period_id, tally, status) VALUES (1, 1, 1, '2000-03-21T22:00:00+00:00', '32.00', '2012-03-22T20:22:22.222222+00:00', 41, '0.00', 12),
(1, 2, 1, '2000-03-22T22:00:00+00:00', '32.00', '2012-03-23T20:22:22.222222+00:00', 41, '-4.50', 11),
(1, 3, 2, '2012-02-21T22:00:00+00:00', '42.23', '2012-02-22T20:22:22.222222+00:00', 41, '42.23', 10);
INSERT INTO cde.finance_log (submitted_by, id, members, delta, additional_info, code, ctime, new_balance, persona_id, total) VALUES (1, 1, 7, NULL, '-4.50€', 32, now(), NULL, 2, '106.50'),
(1, 2, 7, '5.00', '42.23€', 31, now(), '12.50', 2, '111.50');
INSERT INTO past_event.institutions (id, moniker, title) VALUES (1, 'CdE', 'Club der Ehemaligen'),
(2, 'DdE', 'Disco des Ehemaligen');
INSERT INTO past_event.events (id, institution, notes, description, tempus, shortname, title) VALUES (1, 1, 'Mediensammlung
:    <https://pa14:secret@example.cde/pa14/>', 'Great event!', '2014-05-25', 'pa14', 'PfingstAkademie 2014'),
(2, 2, NULL, NULL, '2019-07-26', 'gebi', 'Geburtstagsfete'),
(3, 1, NULL, NULL, '2010-12-31', 'Kotz', 'KotzAkademie 2010');
INSERT INTO past_event.courses (id, description, pevent_id, nr, title) VALUES (1, 'Ringelpiez mit anfassen.', 1, '1a', 'Swish -- und alles ist gut'),
(2, 'Hier werden die Reime getanzt.', 1, 'Ω', 'Goethe zum Anfassen');
INSERT INTO past_event.participants (id, pevent_id, is_orga, pcourse_id, persona_id, is_instructor) VALUES (1, 1, false, 1, 2, true),
(2, 1, false, NULL, 3, false),
(3, 1, false, 2, 5, false),
(4, 1, true, 2, 6, false),
(5, 1, false, 2, 100, false);
INSERT INTO event.events (id, iban, description, is_archived, is_cancelled, use_additional_questionnaire, registration_text, courses_in_participant_list, mail_text, orga_address, is_visible, registration_soft_limit, is_participant_list_visible, notes, institution, registration_start, registration_hard_limit, nonmember_surcharge, is_course_list_visible, is_course_state_visible, shortname, offline_lock, title) VALUES (1, 'DE26370205000008068900', 'Everybody come!', false, false, false, NULL, false, 'Wir verwenden ein neues Kristallkugel-basiertes Kurszuteilungssystem; bis wir das ordentlich ans Laufen gebracht haben, müsst ihr leider etwas auf die Teilnehmerliste warten.', 'aka@example.cde', true, '2200-10-30T00:00:00+00:00', false, 'Todoliste ... just kidding ;)', 1, '2000-10-30T00:00:00+00:00', '2221-10-30T00:00:00+00:00', '5.00', true, false, 'TestAka', false, 'Große Testakademie 2222'),
(2, 'DE26370205000008068900', 'Let''s have a party!', false, false, false, NULL, false, '', '', false, '2049-12-31T00:00:00+00:00', false, 'Wird anstrengend …', 1, '2049-12-01T00:00:00+00:00', '2049-12-31T00:00:00+00:00', '2.00', true, false, 'Party50', false, 'CdE-Party 2050');
INSERT INTO event.event_parts (id, part_end, title, fee, part_begin, shortname, event_id) VALUES (1, '2222-02-02', 'Warmup', '10.50', '2222-02-02', 'Wu', 1),
(2, '2222-11-11', 'Erste Hälfte', '123.00', '2222-11-01', '1.H.', 1),
(3, '2222-11-30', 'Zweite Hälfte', '450.99', '2222-11-11', '2.H.', 1),
(4, '2050-01-15', 'Party', '15.00', '2050-01-15', 'Party', 2);
INSERT INTO event.course_tracks (part_id, id, sortkey, num_choices, shortname, title, min_choices) VALUES (2, 1, 1, 4, 'Morgenkreis', 'Morgenkreis (Erste Hälfte)', 4),
(2, 2, 2, 1, 'Kaffee', 'Kaffeekränzchen (Erste Hälfte)', 1),
(3, 3, 3, 3, 'Sitzung', 'Arbeitssitzung (Zweite Hälfte)', 2);
INSERT INTO event.orgas (persona_id, id, event_id) VALUES (7, 1, 1),
(1, 2, 2),
(2, 3, 2),
(100, 4, 2);
INSERT INTO event.field_definitions (id, entries, field_name, kind, association, event_id) VALUES (1, NULL, 'brings_balls', 2, 1, 1),
(2, ARRAY[ARRAY['pedes','by feet'],ARRAY['car','own car available'],ARRAY['etc','anything else']], 'transportation', 1, 1, 1),
(3, NULL, 'lodge', 1, 1, 1),
(4, NULL, 'may_reserve', 2, 1, 1),
(5, NULL, 'room', 1, 2, 1),
(6, ARRAY[ARRAY['high','lots of radiation'],ARRAY['medium','elevated level of radiation'],ARRAY['low','some radiation'],ARRAY['none','no radiation']], 'contamination', 1, 3, 1),
(7, NULL, 'is_child', 2, 1, 1);
INSERT INTO event.fee_modifiers (part_id, field_id, id, amount, modifier_name) VALUES (1, 7, 1, '-5.00', 'is_child'),
(2, 7, 2, '-12.00', 'is_child'),
(3, 7, 3, '-19.00', 'is_child');
INSERT INTO event.questionnaire_rows (field_id, pos, event_id, readonly, info, kind, default_value, input_size, title) VALUES (7, 0, 1, NULL, NULL, 1, NULL, NULL, 'Ich bin unter 13 Jahre alt.'),
(NULL, 0, 1, NULL, 'mit Text darunter', 2, NULL, NULL, 'Unterüberschrift'),
(1, 1, 1, false, 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.', 2, 'True', NULL, 'Bälle'),
(NULL, 2, 1, NULL, 'nur etwas Text', 2, NULL, NULL, NULL),
(NULL, 3, 1, NULL, NULL, 2, NULL, NULL, 'Weitere Überschrift'),
(2, 4, 1, false, NULL, 2, 'etc', NULL, 'Vehikel'),
(3, 5, 1, false, NULL, 2, NULL, 3, 'Hauswunsch');
INSERT INTO event.courses (id, notes, description, max_size, title, min_size, nr, instructors, fields, shortname, event_id) VALUES (1, 'Promotionen in Mathematik und Ethik für Teilnehmer notwendig.', 'Wir werden die Bäume drücken.', 10, 'Planetenretten für Anfänger', 2, 'α', 'ToFi & Co', '{"room": "Wald"}', 'Heldentum', 1),
(2, 'Kursleiter hat Sekt angefordert.', 'Inklusive Post, Backwaren und frühzeitigem Ableben.', 20, 'Lustigsein für Fortgeschrittene', 10, 'β', 'Bernd Lucke', '{"room": "Theater"}', 'Kabarett', 1),
(3, NULL, 'mit hoher Leistung.', 14, 'Kurzer Kurs', 5, 'γ', 'Heinrich und Thomas Mann', '{"room": "Seminarraum 42"}', 'Kurz', 1),
(4, NULL, 'mit hohem Umsatz.', NULL, 'Langer Kurs', NULL, 'δ', 'Stephen Hawking und Richard Feynman', '{"room": "Seminarraum 23"}', 'Lang', 1),
(5, NULL, 'damit wir Auswahl haben', NULL, 'Backup-Kurs', NULL, 'ε', 'TBA', '{"room": "Nirwana"}', 'Backup', 1);
INSERT INTO event.course_segments (id, track_id, course_id, is_active) VALUES (1, 1, 1, true),
(2, 3, 1, true),
(3, 1, 2, true),
(4, 2, 2, false),
(5, 3, 2, true),
(6, 2, 3, true),
(7, 1, 4, true),
(8, 2, 4, true),
(9, 3, 4, true),
(10, 1, 5, true),
(11, 2, 5, true),
(12, 3, 5, false);
INSERT INTO event.lodgement_groups (id, moniker, event_id) VALUES (1, 'Haupthaus', 1),
(2, 'AußenWohnGruppe', 1);
INSERT INTO event.lodgements (id, notes, moniker, group_id, fields, camping_mat_capacity, regular_capacity, event_id) VALUES (1, NULL, 'Warme Stube', 2, '{"contamination": "high"}', 1, 5, 1),
(2, 'Dafür mit Frischluft.', 'Kalte Kammer', 1, '{"contamination": "none"}', 2, 10, 1),
(3, 'Nur für Notfälle.', 'Kellerverlies', NULL, '{"contamination": "low"}', 100, 0, 1),
(4, NULL, 'Einzelzelle', 1, '{"contamination": "high"}', 0, 1, 1);
INSERT INTO event.registrations (checkin, id, notes, real_persona_id, payment, mixed_lodging, parental_agreement, orga_notes, amount_owed, list_consent, fields, amount_paid, persona_id, event_id) VALUES (NULL, 1, NULL, NULL, NULL, true, true, NULL, '573.99', true, '{
    "lodge": "Die \u00fcblichen Verd\u00e4chtigen :)",
    "is_child": false
}', '0.00', 1, 1),
(NULL, 2, 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett', NULL, '2014-02-02', true, true, 'Unbedingt in die Einzelzelle.', '589.49', true, '{
    "brings_balls": true,
    "transportation": "pedes",
    "is_child": false
}', '0.00', 5, 1),
(NULL, 3, NULL, NULL, '2014-03-03', true, true, NULL, '584.49', false, '{
    "transportation": "car",
    "is_child": false
}', '0.00', 7, 1),
(NULL, 4, NULL, NULL, '2014-04-04', false, false, NULL, '431.99', false, '{
    "may_reserve": true,
    "brings_balls": false,
    "transportation": "etc",
    "is_child": true
}', '0.00', 9, 1),
(NULL, 5, NULL, NULL, NULL, false, true, NULL, '584.49', true, '{
    "transportation": "pedes",
    "is_child": false
}', '0.00', 100, 1),
(NULL, 6, NULL, NULL, NULL, true, true, NULL, '10.50', true, '{
    "transportation": "pedes",
    "is_child": false
}', '0.00', 2, 1);
INSERT INTO event.registration_parts (part_id, id, lodgement_id, registration_id, is_camping_mat, status) VALUES (1, 1, NULL, 1, false,  -1),
(2, 2, NULL, 1, false, 1),
(3, 3, 1, 1, false, 2),
(1, 4, NULL, 2, false, 3),
(2, 5, 4, 2, false, 4),
(3, 6, 4, 2, false, 2),
(1, 7, 2, 3, false, 2),
(2, 8, NULL, 3, false, 2),
(3, 9, 2, 3, false, 2),
(1, 10, NULL, 4, false, 6),
(2, 11, NULL, 4, false, 5),
(3, 12, 2, 4, true, 2),
(1, 13, 4, 5, false, 2),
(2, 14, 4, 5, false, 2),
(3, 15, 1, 5, false, 2),
(1, 16, NULL, 6, false, 2),
(2, 17, NULL, 6, false,  -1),
(3, 18, NULL, 6, false,  -1);
INSERT INTO event.registration_tracks (id, course_id, registration_id, track_id, course_instructor) VALUES (1, NULL, 1, 1, NULL),
(2, NULL, 1, 2, NULL),
(3, NULL, 1, 3, NULL),
(4, NULL, 2, 1, NULL),
(5, NULL, 2, 2, NULL),
(6, 1, 2, 3, 1),
(7, NULL, 3, 1, NULL),
(8, 2, 3, 2, NULL),
(9, NULL, 3, 3, NULL),
(10, NULL, 4, 1, NULL),
(11, NULL, 4, 2, NULL),
(12, 1, 4, 3, NULL),
(13, NULL, 5, 1, NULL),
(14, 2, 5, 2, NULL),
(15, 1, 5, 3, NULL),
(16, NULL, 6, 1, NULL),
(17, NULL, 6, 2, NULL),
(18, NULL, 6, 3, NULL);
INSERT INTO event.course_choices (id, course_id, registration_id, track_id, rank) VALUES (1, 1, 1, 1, 0),
(2, 3, 1, 1, 1),
(3, 4, 1, 1, 2),
(4, 2, 1, 1, 3),
(5, 2, 1, 2, 0),
(6, 1, 1, 3, 0),
(7, 4, 1, 3, 1),
(8, 5, 2, 1, 0),
(9, 4, 2, 1, 1),
(10, 2, 2, 1, 2),
(11, 1, 2, 1, 3),
(12, 3, 2, 2, 0),
(13, 4, 2, 3, 0),
(14, 2, 2, 3, 1),
(15, 4, 3, 1, 0),
(16, 2, 3, 1, 1),
(17, 1, 3, 1, 2),
(18, 5, 3, 1, 3),
(19, 2, 3, 2, 0),
(20, 2, 3, 3, 0),
(21, 4, 3, 3, 1),
(22, 2, 4, 1, 0),
(23, 1, 4, 1, 1),
(24, 4, 4, 1, 2),
(25, 5, 4, 1, 3),
(26, 4, 4, 2, 0),
(27, 1, 4, 3, 0),
(28, 2, 4, 3, 1),
(29, 1, 5, 1, 0),
(30, 5, 5, 1, 1),
(31, 4, 5, 1, 2),
(32, 2, 5, 1, 3),
(33, 2, 5, 2, 0),
(34, 1, 5, 3, 0),
(35, 4, 5, 3, 1);
INSERT INTO event.log (submitted_by, id, additional_info, code, ctime, persona_id, event_id) VALUES (1, 1, NULL, 50, '2014-01-01T01:04:05+00:00', 1, 1),
(5, 2, NULL, 50, '2014-01-01T02:05:06+00:00', 5, 1),
(7, 3, NULL, 50, '2014-01-01T03:06:07+00:00', 7, 1),
(9, 4, NULL, 50, '2014-01-01T04:07:08+00:00', 9, 1);
INSERT INTO assembly.assemblies (signup_end, mail_address, id, notes, description, title, is_active) VALUES ('2111-11-11T00:00:00+00:00', 'kongress@example.cde', 1, NULL, 'Proletarier aller Länder vereinigt Euch!', 'Internationaler Kongress', true),
('2020-02-22T00:00:00+00:00', NULL, 2, NULL, 'Wenigstens darauf können wir uns einigen.', 'Kanonische Beispielversammlung', false),
('2222-02-22T00:00:00+00:00', NULL, 3, NULL, 'Zum Aufbewahren von ganz viel Akten und Papier.', 'Archiv-Sammlung', true);
INSERT INTO assembly.attendees (persona_id, id, assembly_id, secret) VALUES (1, 1, 1, 'aoeuidhtns'),
(2, 2, 1, 'snthdiueoa'),
(9, 3, 1, 'asonetuhid'),
(11, 4, 1, 'bxronkxeud'),
(23, 5, 1, 'esfawernae'),
(100, 6, 1, 'sefnasdfiw'),
(18, 7, 2, 'asdgeargsd');
INSERT INTO assembly.ballots (id, notes, extended, description, quorum, use_bar, assembly_id, vote_extension_end, votes, is_tallied, vote_end, title, vote_begin) VALUES (1, NULL, true, 'Nach dem Leben, dem Universum und dem ganzen Rest.', 2, true, 1, now(), NULL, false, '2002-02-23T20:22:22.222222+00:00', 'Antwort auf die letzte aller Fragen', '2002-02-22T20:22:22.222222+00:00'),
(2, 'Nochmal alle auf diese wichtige Entscheidung hinweisen.', NULL, 'Ulitmativ letzte Entscheidung', 0, false, 1, NULL, NULL, false, '2222-02-03T20:22:22.222222+00:00', 'Farbe des Logos', '2222-02-02T20:22:22.222222+00:00'),
(3, NULL, NULL, 'total objektiv', 0, true, 1, NULL, 1, false, '2222-02-11T20:22:22.222222+00:00', 'Bester Hof', '2000-02-10T20:22:22.222222+00:00'),
(4, NULL, NULL, 'denkt an die Frutaner', 0, true, 1, NULL, 2, false, '2222-01-01T20:22:22.222222+00:00', 'Akademie-Nachtisch', now()),
(5, NULL, NULL, NULL, 0, false, 1, NULL, NULL, false, '2222-01-01T20:22:22.222222+00:00', 'Lieblingszahl', now()),
(6, NULL, false, NULL, 0, false, 3, NULL, 1, false, '2000-02-01T22:00:00+00:00', 'Test-Abstimmung – bitte ignorieren', '1999-12-31T22:00:00+00:00'),
(7, NULL, NULL, 'Er hat wahrlich gute Arbeit geleistet!', 0, false, 2, NULL, 1, false, '2015-03-20T23:00:00+00:00', 'Entlastung des Vorstands', '2010-11-11T22:00:00+00:00'),
(8, NULL, true, 'Was für ein Logo soll der CdE bekommen?', 100000, true, 2, '1999-09-05T23:00:00+00:00', 1, false, '1000-01-01T23:00:00+00:00', 'Eine damals wichtige Frage', '900-09-29T22:00:00+00:00'),
(9, NULL, false, NULL, 0, true, 2, NULL, 2, false, '2020-03-09T23:00:00+00:00', 'Wahl des Finanzvorstands', '2019-04-04T22:00:00+00:00'),
(10, NULL, true, 'Ein Punkt mit vielen Meinungen.', 4444, false, 2, '2016-07-31T23:00:00+00:00', NULL, false, '2015-10-04T23:00:00+00:00', 'Wie soll der CdE mit seinem Vermögen umgehen?', '2014-11-20T22:00:00+00:00'),
(11, NULL, false, 'Wir müssen dringend die neuen Regeln umsetzen. Wollen wir den Anhang annehmen?', 0, false, 1, NULL, 1, false, '2200-12-01T23:00:10+00:00', 'Antrag zur DSGVO 2.0', '2020-01-30T22:00:00+00:00'),
(12, NULL, NULL, 'Welches Wappentier soll der CdE tragen?', 4, false, 1, '2101-08-24T23:00:00+00:00', 1, false, '2100-11-19T23:00:00+00:00', 'Eine aktuell wichtige Frage', '2001-03-14T22:00:00+00:00'),
(13, NULL, NULL, 'Wir haben mehr als einen Kandidaten!', 0, true, 1, NULL, NULL, false, '2040-12-26T23:00:00+00:00', 'Wahl des Innenvorstand', '2020-02-14T22:00:00+00:00'),
(14, NULL, NULL, NULL, 3333, false, 1, '2100-03-16T23:00:00+00:00', NULL, false, '2090-07-19T23:00:00+00:00', 'Wie sollen Akademien sich in Zukunft finanzieren', '2019-04-10T22:00:00+00:00'),
(15, NULL, NULL, 'Wir konnten uns einfach nicht einigen.', 2000, false, 1, '2222-07-28T23:00:00+00:00', NULL, false, '2019-12-13T23:00:00+00:00', 'Welche Sprache ist die Beste?', '2018-08-03T22:00:00+00:00'),
(16, NULL, NULL, NULL, 0, false, 3, NULL, NULL, false, '2222-02-22T00:01+00:00', 'Ganz wichtige Wahl', '2222-02-22T00:00+00:00');
INSERT INTO assembly.candidates (id, moniker, ballot_id, description) VALUES (2, '1', 1, 'Ich'),
(3, '2', 1, '23'),
(4, '3', 1, '42'),
(5, '4', 1, 'Philosophie'),
(6, 'rot', 2, 'Rot'),
(7, 'gelb', 2, 'Gelb'),
(8, 'gruen', 2, 'Grün'),
(9, 'blau', 2, 'Blau'),
(10, 'Li', 3, 'Lischert'),
(11, 'St', 3, 'Steinsgebiss'),
(12, 'Fi', 3, 'Fichte'),
(13, 'Bu', 3, 'Buchwald'),
(14, 'Lo', 3, 'Löscher'),
(15, 'Go', 3, 'Goldborn'),
(17, 'W', 4, 'Wackelpudding'),
(18, 'S', 4, 'Salat'),
(19, 'E', 4, 'Eis'),
(20, 'J', 4, 'Joghurt'),
(21, 'N', 4, 'Nichts'),
(23, 'e', 5, 'e'),
(24, 'pi', 5, 'pi'),
(25, 'i', 5, 'i'),
(26, '1', 5, '1'),
(27, '0', 5, '0'),
(28, 'Ja', 11, 'Ja'),
(29, 'Nein', 11, 'Nein'),
(30, 'a', 12, 'Löwe'),
(31, 'b', 12, 'Adler'),
(32, 'c', 12, 'Dachs'),
(33, 'd', 12, 'Schlange'),
(34, 'Anton', 13, 'Anton A. Administrator'),
(35, 'Berta', 13, 'Bertalotta Beispiel'),
(36, 'Akira', 13, 'Akira Abukara'),
(37, 'Steuern', 14, 'Durch eine erhobene Steuer auf Tee und Schokolade'),
(38, 'Spenden', 14, 'Durch Spendenbeiträge'),
(39, 'BMBF', 14, 'Durch Infiltration des BMBF'),
(40, 'Sindarin', 15, 'Sindarin (Elbisch, Herr der Ringe)'),
(41, 'Khuzdul', 15, 'Khuzdul (Zwergisch, Herr der Ringe)'),
(42, 'Esperanto', 15, 'Esperanto (Kunstsprache, Erde)'),
(43, 'Klingonisch', 15, 'Klingonisch (Klingonen, Star Trek)'),
(44, 'Ja', 7, 'Ja'),
(45, 'Nein', 7, 'Nein'),
(46, 'Gluehbirne', 8, 'Eine Glühbirne mit Schriftzug'),
(47, 'Wappen', 8, 'Die vier Wappentiere, die den Schriftzug CdE umringen'),
(48, 'Baum', 8, 'Ein Baum mit Blättern und Grün!'),
(49, 'Farin', 9, 'Farin Finanzvorstand'),
(50, 'Inga', 9, 'Inga Iota'),
(51, 'Olaf', 9, 'Olaf Olafson'),
(52, 'Aktien', 10, 'Investieren in Aktien und Fonds.'),
(53, 'Eisenberg', 10, 'Wir kaufen den Eisenberg!'),
(54, 'Akademien', 10, 'Kostenlose Akademien für alle.');
INSERT INTO assembly.attachments (assembly_id, id, ballot_id) VALUES (3, 1, NULL),
(3, 2, NULL),
(NULL, 3, 16);
INSERT INTO assembly.attachment_versions (attachment_id, dtime, authors, filename, file_hash, version, ctime, title) VALUES (1, NULL, 'Farin', 'rechen.pdf', 'abc', 1, now(), 'Rechenschaftsbericht'),
(2, NULL, 'Berta', 'kasse.pdf', 'bcd', 1, now(), 'Kassenprüferbericht'),
(2, now(), NULL, NULL, 'del', 2, now(), NULL),
(2, NULL, 'Garcia', 'kasse.pdf', 'cde', 3, now(), 'Kassenprüferbericht 2'),
(3, NULL, 'Wahlleitung', 'kandidaten.pdf', 'xyz', 1, now(), 'Liste der Kanditaten');
INSERT INTO assembly.votes (id, hash, salt, ballot_id, vote) VALUES (1, 'a3bf0788f1eaa85f5ca979d2ba963b7c60bce02c49ac1c0dfe5d06d5b3950d69c55752df5d963b8de770d353bf795ca07060f7578456b19e18028249bcf51195', 'rxt3x/jnl', 1, '2>3>_bar_>1=4'),
(2, 'f99ade4db2d724c6ae887cffc099c5758927358c99d65aac43e3ce61d212effad5bfbb68e69d6f2669f42d58c74e1fa3f2149a92c7172f2bb9d0e487478e5bb7', 'et3[uh{kr', 1, '3>2=4>_bar_>1'),
(3, '65ab33a95a367ff3dd07d19ecb9de1311dd3cee5525bae5c7ba6ff46587e79e964e14a246211748f3beb406506b3aa926a66ff5754a69d4c340c98a0f3f5d69d', 'krcqm"xdv', 1, '_bar_>4>3>2>1'),
(4, '9d59b3a4a6a9eca9613ef2e0710117a8e240e9197f20f2b970288dd93fd6347d657d265033f915c7fa44043315c4a8b834951c4f4e6fc46ea59a795c02af93e7', 'klw3xjq8s', 1, '1>2=3=4>_bar_'),
(5, '314776ac07ffdd56a53112ae5f5113fb356b82b19f3a43754695aa41bf8e120c0346b45e43d0a0114e2bbc7756e7f34ce41f784000c010570d71e90a5c2ab1f1', 'lkn/4kvj9', 3, 'Lo>Li=St=Fi=Bu=Go=_bar_'),
(6, '1b92235ea46875b7fa0c902377f642f80a07646e8ef7528c058e246aa74a9ee34b24b5dcbc52340d04c643b89e035e556b43a84a0332785954b310a30ae49981', 'le4sk502j', 7, 'Nein>Ja=_bar_'),
(7, 'eb0eead9670397754d99a53af7ec56e94a5b44144aa2974f5ecd172f434f742b9f51783d9c4e4d2ae016d9fae1be9425621fe2bb91dfbb541ba9cccd34c92b3f', 'ikejsoe8p', 8, 'Wappen>_bar_=Gluehbirne=Baum'),
(8, '24a751056614ea223b1af4099d228ee943a3d33507c13fe746a3e6811b78188495ab6015bc9deda17ecb79ced8189ca6bb91e96d17d263bd713997fb4ecb9a88', 'l9tmeid73', 9, 'Farin=Inga>_bar_=Olaf'),
(9, 'ec21445bdd06f5a62a59add324b1f7743a00e9e60f9d546f45199e96a3706af603b114069f3dbbecdd53ab4765522f1eea1bca410a3a91aec48ac97a2b2baddc', '8ci4wof73', 10, 'Eisenberg>Akademien>Aktien');
INSERT INTO assembly.voter_register (persona_id, id, has_voted, ballot_id) VALUES (1, 1, true, 1),
(1, 2, false, 2),
(1, 3, false, 3),
(1, 4, false, 4),
(1, 5, false, 5),
(2, 6, true, 1),
(2, 7, false, 2),
(2, 8, true, 3),
(2, 9, false, 4),
(2, 10, false, 5),
(9, 11, true, 1),
(9, 12, false, 2),
(9, 13, false, 3),
(9, 14, false, 4),
(9, 15, false, 5),
(11, 16, true, 1),
(11, 17, false, 2),
(11, 18, false, 3),
(11, 19, false, 4),
(11, 20, false, 5),
(23, 21, false, 1),
(23, 22, false, 2),
(23, 23, false, 3),
(23, 24, false, 4),
(23, 25, false, 5),
(100, 26, false, 1),
(100, 27, false, 2),
(100, 28, false, 3),
(100, 29, false, 4),
(100, 30, false, 5),
(1, 31, false, 11),
(1, 32, false, 12),
(1, 33, false, 13),
(1, 34, false, 14),
(2, 35, false, 11),
(2, 36, false, 12),
(2, 37, false, 13),
(2, 38, false, 14),
(9, 39, false, 11),
(9, 40, false, 12),
(9, 41, false, 13),
(9, 42, false, 14),
(11, 43, false, 11),
(11, 44, false, 12),
(11, 45, false, 13),
(11, 46, false, 14),
(23, 47, false, 11),
(23, 48, false, 12),
(23, 49, false, 13),
(23, 50, false, 14),
(100, 51, false, 11),
(100, 52, false, 12),
(100, 53, false, 13),
(100, 54, false, 14),
(1, 55, false, 15),
(2, 56, false, 15),
(9, 57, false, 15),
(11, 58, false, 15),
(23, 59, false, 15),
(100, 60, false, 15),
(18, 61, true, 7),
(18, 62, true, 8),
(18, 63, true, 9),
(18, 64, true, 10);
INSERT INTO ml.mailinglists (id, subject_prefix, local_part, maxsize, notes, description, registration_stati, ml_type, event_id, address, assembly_id, mod_policy, gateway, attachment_policy, domain, title, is_active) VALUES (1, 'Hört, hört', 'announce', NULL, NULL, NULL, '{}', 1, NULL, 'announce@lists.cde-ev.de', NULL, 3, NULL, 3, 1, 'Verkündungen', true),
(2, 'werbung', 'werbung', NULL, NULL, 'Wir werden auch gut bezahlt dafür', '{}', 2, NULL, 'werbung@lists.cde-ev.de', NULL, 3, NULL, 1, 1, 'Werbung', true),
(3, 'witz', 'witz', 2048, NULL, 'Einer geht noch ...', '{}', 40, NULL, 'witz@lists.cde-ev.de', NULL, 2, NULL, 2, 1, 'Witz des Tages', true),
(4, 'klatsch', 'klatsch', NULL, NULL, NULL, '{}', 4, NULL, 'klatsch@lists.cde-ev.de', NULL, 1, NULL, 1, 1, 'Klatsch und Tratsch', true),
(5, 'kampf', 'kongress', 1024, NULL, NULL, '{}', 30, NULL, 'kongress@lists.cde-ev.de', 1, 2, NULL, 2, 1, 'Sozialistischer Kampfbrief', true),
(6, 'aktivenforum', 'aktivenforum2000', 1024, NULL, NULL, '{}', 3, NULL, 'aktivenforum2000@lists.cde-ev.de', NULL, 2, NULL, 2, 1, 'Aktivenforum 2000', false),
(7, 'aktivenforum', 'aktivenforum', 1024, NULL, NULL, '{}', 3, NULL, 'aktivenforum@lists.cde-ev.de', NULL, 2, NULL, 2, 1, 'Aktivenforum 2001', true),
(8, 'orga', 'aka', NULL, NULL, NULL, '{}', 21, 1, 'aka@aka.cde-ev.de', NULL, 1, NULL, 1, 2, 'Orga-Liste', true),
(9, 'aka', 'participants', NULL, NULL, NULL, ARRAY[2,4], 20, 1, 'participants@aka.cde-ev.de', NULL, 2, NULL, 1, 2, 'Teilnehmer-Liste', true),
(10, 'wait', 'wait', NULL, NULL, NULL, ARRAY[3], 20, 1, 'wait@aka.cde-ev.de', NULL, 3, NULL, 1, 2, 'Warte-Liste', true),
(11, 'talk', 'opt', NULL, NULL, NULL, '{}', 31, NULL, 'opt@lists.cde-ev.de', NULL, 1, NULL, 1, 1, 'Kampfbrief-Kommentare', true),
(51, 'all', 'all', NULL, 'Auf keinen Fall löschen!', 'Für alle CdEler.', '{}', 1, NULL, 'all@lists.cde-ev.de', NULL, 3, NULL, 1, 1, 'CdE-All', true),
(52, 'info', 'info', NULL, 'Immer dieser Spam hier...', 'Hier werden Veranstaltungsankündigungen etc. verschickt.', '{}', 2, NULL, 'info@lists.cde-ev.de', NULL, 3, NULL, 2, 1, 'CdE-Info', true),
(53, 'mitg.', 'mitgestaltung', NULL, NULL, 'Wir haben uns jetzt umbenannt.', '{}', 3, NULL, 'mitgestaltung@lists.cde-ev.de', NULL, 2, NULL, 1, 1, 'Mitgestaltungsforum', true),
(54, 'gutschein', 'gutscheine', NULL, 'Offizielle Position: Das ist keine Vetternwirtschaft!', 'Die bekommt nicht jeder!', '{}', 4, NULL, 'gutscheine@lists.cde-ev.de', NULL, 1, NULL, 1, 1, 'Gutscheine', true),
(55, 'platin', 'platin', NULL, 'Gut, das ich Admin bin.', 'Hier kommt nicht jeder rein.', '{}', 5, NULL, 'platin@lists.cde-ev.de', NULL, 2, NULL, 1, 1, 'Platin-Lounge', true),
(56, 'bau', 'bau', NULL, NULL, 'denn ein Eisenberg ist nicht genug!', '{}', 10, NULL, 'bau@lists.cde-ev.de', NULL, 1, NULL, 1, 1, 'Feriendorf Bau', true),
(57, 'psst', 'geheim', NULL, 'Sollten wir im Auge behalten, könnten zur Bedrohung werden - gut, das wir mitlesen.', '... uns gibt es gar nicht!', '{}', 11, NULL, 'geheim@lists.cde-ev.de', NULL, 3, NULL, 1, 1, 'Geheimbund', true),
(58, 'special', 'test-gast', NULL, NULL, '... für unsere besonderen Gäste.', ARRAY[4], 20, 1, 'test-gast@aka.cde-ev.de', NULL, 1, NULL, 3, 2, 'Testakademie 2222, Gäste', true),
(59, 'Party50', 'party50', 1024, NULL, 'Bitte wende dich bei Fragen oder Problemen, die mit unserer Veranstaltung zusammenhängen, über diese Liste an uns.', '{}', 21, 2, 'party50@aka.cde-ev.de', NULL, 1, NULL, 1, 2, 'CdE-Party 2050 Orgateam', true),
(60, 'Party50', 'party50-all', 1024, NULL, 'Dieser Liste kannst du nur beitreten, indem du dich zu unserer [Veranstaltung anmeldest](/db/event/event/2/register) und den Status *Teilnehmer* erhälst. Auf dieser Liste stehen alle Teilnehmer unserer Veranstaltung; sie kann im Vorfeld zum Austausch untereinander genutzt werden.', ARRAY[2], 20, 2, 'party50-all@aka.cde-ev.de', NULL, 2, NULL, 2, 2, 'CdE-Party 2050 Teilnehmer', true),
(61, 'kanonisch', 'kanonisch', NULL, 'Badum tzz.', 'Wir schießen auch auf Spatzen.', '{}', 30, NULL, 'kanonisch@lists.cde-ev.de', 2, 2, NULL, 2, 1, 'Kanonische Beispielversammlung', true),
(62, 'wal', 'wal', NULL, NULL, 'Helft beim der Wal-zählung!', '{}', 31, NULL, 'wal@lists.cde-ev.de', NULL, 1, NULL, 1, 1, 'Walergebnisse', true),
(63, 'dsa', 'dsa', NULL, NULL, 'Hier ist jeder willkommen.', '{}', 40, NULL, 'dsa@lists.cde-ev.de', NULL, 1, NULL, 3, 1, 'DSA-Liste', true),
(64, '42', '42', NULL, '42', 'und der ganze Rest.', '{}', 50, NULL, '42@lists.cde-ev.de', NULL, 2, NULL, 1, 1, 'Das Leben, das Universum ...', true),
(65, 'hogwarts', 'hogwarts', NULL, 'gegründet von DA', 'Kommt doch einfach mal zum wöchentlichen Treff nach Hogsmead.', '{}', 60, NULL, 'hogwarts@cdelokal.cde-ev.de', NULL, 2, NULL, 1, 4, 'Hogwarts', true);
INSERT INTO ml.moderators (persona_id, id, mailinglist_id) VALUES (2, 1, 1),
(10, 2, 2),
(2, 3, 3),
(3, 4, 3),
(10, 5, 3),
(2, 6, 4),
(100, 7, 4),
(2, 8, 5),
(7, 9, 5),
(2, 10, 6),
(2, 11, 7),
(10, 12, 7),
(7, 13, 8),
(7, 14, 9),
(7, 15, 10),
(3, 17, 52),
(2, 18, 53),
(4, 19, 53),
(9, 20, 54),
(1, 21, 55),
(100, 22, 55),
(2, 23, 56),
(11, 24, 56),
(12, 25, 57),
(7, 26, 58),
(1, 27, 59),
(2, 28, 59),
(100, 29, 59),
(1, 30, 60),
(2, 31, 60),
(100, 32, 60),
(11, 33, 61),
(15, 34, 62),
(10, 35, 63),
(1, 36, 64),
(2, 37, 64),
(5, 38, 65),
(27, 39, 51),
(27, 40, 59);
INSERT INTO ml.whitelist (id, mailinglist_id, address) VALUES (1, 2, 'honeypot@example.cde'),
(2, 6, 'aliens@example.cde'),
(3, 6, 'drwho@example.cde'),
(4, 7, 'aliens@example.cde'),
(5, 7, 'drwho@example.cde'),
(6, 7, 'captiankirk@example.cde'),
(7, 54, 'dagobert@example.cde'),
(8, 55, 'v.brandt@example.cde'),
(9, 64, 'dent@example.cde'),
(10, 64, 'prefect@example.cde'),
(11, 65, 'sproud@example.cde'),
(12, 65, 'hagrid@example.cde');
INSERT INTO ml.subscription_states (persona_id, id, mailinglist_id, subscription_state) VALUES (1, 1, 1, 30),
(2, 2, 1, 30),
(3, 3, 1, 1),
(6, 4, 1, 30),
(7, 5, 1, 30),
(9, 6, 1, 30),
(12, 7, 1, 30),
(13, 8, 1, 2),
(15, 9, 1, 30),
(22, 10, 1, 2),
(23, 11, 1, 2),
(27, 12, 1, 2),
(32, 13, 1, 2),
(100, 14, 1, 30),
(1, 15, 2, 30),
(2, 16, 2, 30),
(3, 17, 2, 30),
(6, 18, 2, 2),
(7, 19, 2, 30),
(9, 20, 2, 30),
(12, 21, 2, 30),
(13, 22, 2, 2),
(15, 23, 2, 30),
(22, 24, 2, 2),
(23, 25, 2, 2),
(27, 26, 2, 2),
(32, 27, 2, 2),
(100, 28, 2, 30),
(1, 29, 3, 1),
(2, 30, 3, 2),
(10, 31, 3, 1),
(1, 32, 4, 1),
(2, 33, 4, 1),
(3, 34, 4, 1),
(7, 35, 4, 11),
(100, 36, 4, 1),
(1, 37, 5, 30),
(2, 38, 5, 30),
(3, 39, 5, 10),
(9, 40, 5, 11),
(11, 41, 5, 30),
(14, 42, 5, 10),
(23, 43, 5, 30),
(100, 44, 5, 10),
(1, 45, 6, 1),
(2, 46, 6, 1),
(1, 47, 7, 2),
(3, 48, 7, 1),
(6, 49, 7, 20),
(7, 50, 8, 30),
(1, 51, 9, 30),
(5, 52, 9, 2),
(7, 53, 9, 1),
(9, 54, 9, 30),
(100, 55, 9, 30),
(5, 56, 10, 30),
(3, 57, 11, 1),
(4, 58, 11, 2),
(9, 59, 11, 11),
(11, 60, 11, 1),
(23, 61, 11, 1),
(100, 62, 11, 11),
(32, 63, 51, 2),
(1, 64, 51, 30),
(2, 65, 51, 30),
(3, 66, 51, 30),
(100, 67, 51, 30),
(6, 68, 51, 30),
(7, 69, 51, 30),
(9, 70, 51, 30),
(12, 71, 51, 30),
(13, 72, 51, 2),
(15, 73, 51, 30),
(22, 74, 51, 2),
(23, 75, 51, 2),
(27, 76, 51, 2),
(32, 77, 52, 2),
(1, 78, 52, 30),
(2, 79, 52, 30),
(3, 80, 52, 30),
(100, 81, 52, 30),
(6, 82, 52, 30),
(7, 83, 52, 30),
(9, 84, 52, 30),
(12, 85, 52, 30),
(13, 86, 52, 2),
(15, 87, 52, 30),
(22, 88, 52, 2),
(23, 89, 52, 2),
(27, 90, 52, 2),
(1, 91, 53, 1),
(2, 92, 53, 1),
(7, 93, 53, 1),
(9, 94, 53, 1),
(3, 95, 54, 11),
(11, 96, 54, 10),
(100, 97, 54, 1),
(2, 98, 54, 20),
(7, 99, 54, 11),
(100, 100, 55, 1),
(1, 101, 55, 1),
(23, 102, 55, 2),
(27, 103, 55, 2),
(22, 104, 55, 2),
(32, 105, 55, 11),
(11, 106, 55, 10),
(7, 107, 56, 20),
(9, 108, 56, 1),
(12, 109, 57, 1),
(5, 110, 58, 30),
(1, 111, 59, 30),
(2, 112, 59, 30),
(100, 113, 59, 30),
(23, 114, 62, 1),
(11, 115, 62, 1),
(4, 116, 62, 1),
(2, 117, 63, 1),
(9, 118, 63, 1),
(6, 119, 63, 1),
(13, 120, 63, 1),
(11, 121, 63, 1),
(3, 122, 64, 1),
(10, 123, 64, 1),
(9, 124, 64, 1),
(10, 125, 65, 1),
(14, 126, 65, 1),
(1, 127, 65, 11),
(100, 128, 65, 11),
(17, 129, 52, 2),
(17, 130, 51, 2),
(17, 131, 2, 2),
(17, 132, 1, 2),
(2, 133, 9, 30),
(16, 134, 1, 2),
(16, 135, 2, 2),
(16, 136, 51, 2),
(16, 137, 52, 2),
(18, 138, 61, 30);
INSERT INTO ml.subscription_addresses (persona_id, id, mailinglist_id, address) VALUES (10, 1, 3, 'janis-spam@example.cde'),
(1, 2, 3, 'new-anton@example.cde'),
(6, 3, 4, 'ferdinand-unterhaltung@example.cde');
UPDATE event.events SET lodge_field = 3 WHERE id = 1;
UPDATE event.events SET course_room_field = 2 WHERE id = 1;
UPDATE event.events SET camping_mat_field = 4 WHERE id = 1;
SELECT setval('core.meta_info_id_seq', 1000);
SELECT setval('core.cron_store_id_seq', 1000);
SELECT setval('core.personas_id_seq', 1000);
SELECT setval('core.changelog_id_seq', 1000);
SELECT setval('core.privilege_changes_id_seq', 1000);
SELECT setval('core.genesis_cases_id_seq', 1000);
SELECT setval('core.sessions_id_seq', 1000);
SELECT setval('core.quota_id_seq', 1000);
SELECT setval('core.log_id_seq', 1000);
SELECT setval('cde.lastschrift_id_seq', 1000);
SELECT setval('cde.lastschrift_transactions_id_seq', 1000);
SELECT setval('cde.finance_log_id_seq', 1000);
SELECT setval('cde.log_id_seq', 1000);
SELECT setval('past_event.institutions_id_seq', 1000);
SELECT setval('past_event.events_id_seq', 1000);
SELECT setval('past_event.courses_id_seq', 1000);
SELECT setval('past_event.participants_id_seq', 1000);
SELECT setval('past_event.log_id_seq', 1000);
SELECT setval('event.events_id_seq', 1000);
SELECT setval('event.event_parts_id_seq', 1000);
SELECT setval('event.course_tracks_id_seq', 1000);
SELECT setval('event.orgas_id_seq', 1000);
SELECT setval('event.field_definitions_id_seq', 1000);
SELECT setval('event.fee_modifiers_id_seq', 1000);
SELECT setval('event.questionnaire_rows_id_seq', 1000);
SELECT setval('event.courses_id_seq', 1000);
SELECT setval('event.course_segments_id_seq', 1000);
SELECT setval('event.lodgement_groups_id_seq', 1000);
SELECT setval('event.lodgements_id_seq', 1000);
SELECT setval('event.registrations_id_seq', 1000);
SELECT setval('event.registration_parts_id_seq', 1000);
SELECT setval('event.registration_tracks_id_seq', 1000);
SELECT setval('event.course_choices_id_seq', 1000);
SELECT setval('event.log_id_seq', 1000);
SELECT setval('assembly.assemblies_id_seq', 1000);
SELECT setval('assembly.attendees_id_seq', 1000);
SELECT setval('assembly.ballots_id_seq', 1000);
SELECT setval('assembly.candidates_id_seq', 1000);
SELECT setval('assembly.attachments_id_seq', 1000);
SELECT setval('assembly.attachment_versions_id_seq', 1000);
SELECT setval('assembly.votes_id_seq', 1000);
SELECT setval('assembly.voter_register_id_seq', 1000);
SELECT setval('assembly.log_id_seq', 1000);
SELECT setval('ml.mailinglists_id_seq', 1000);
SELECT setval('ml.moderators_id_seq', 1000);
SELECT setval('ml.whitelist_id_seq', 1000);
SELECT setval('ml.subscription_states_id_seq', 1000);
SELECT setval('ml.subscription_addresses_id_seq', 1000);
SELECT setval('ml.log_id_seq', 1000);
