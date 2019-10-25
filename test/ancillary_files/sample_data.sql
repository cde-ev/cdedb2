--
-- fix some serials (otherwise the test suite gets messed up)
--
ALTER SEQUENCE core.genesis_cases_id_seq RESTART WITH 1;
ALTER SEQUENCE assembly.attachments_id_seq RESTART WITH 1;
ALTER SEQUENCE cde.lastschrift_transactions_id_seq RESTART WITH 1;
ALTER SEQUENCE event.course_choices_id_seq RESTART WITH 1;
ALTER SEQUENCE event.course_segments_id_seq RESTART WITH 1;
ALTER SEQUENCE event.questionnaire_rows_id_seq RESTART WITH 1;
ALTER SEQUENCE event.registration_parts_id_seq RESTART WITH 1;
ALTER SEQUENCE event.registration_tracks_id_seq RESTART WITH 1;
ALTER SEQUENCE event.log_id_seq RESTART WITH 1;
ALTER SEQUENCE event.orgas_id_seq RESTART WITH 1;

--
-- personas
--
INSERT INTO core.personas (id, username, is_active, notes, display_name, given_names, family_name, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin, is_event_admin, is_ml_admin, is_assembly_admin, is_cde_realm, is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, foto, password_hash, fulltext) VALUES
    (1, 'anton@example.cde', True, NULL, 'Anton', 'Anton Armin A.', 'Administrator', True, True, True, True, True, True, True, True, True, True, True, True, True, False, NULL, NULL, 2, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'anton@example.cde  Anton Armin A. Anton Administrator   1991-03-30 +49 (234) 98765  Auf der Düne 42  03205 Musterstadt  Unter dem Hügel 23  22335 Hintertupfingen'),
    (2, 'berta@example.cde', True, NULL, 'Bertå', 'Bertålotta', 'Beispiel', False, False, False, False, False, False, False, True, True, True, True, True, True, False, 'Dr.', 'MdB', 1, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen', 12.5, True, False, True, 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', E'berta@example.cde Dr. Bertålotta Bertå Beispiel Gemeinser MdB 1981-02-11 +49 (5432) 987654321 0163/123456789 Im Garten 77 bei Spielmanns 34576 Utopia  Strange Road 9 3/4  8XA 45-$ Foreign City Far Away https://www.bundestag.cde Alles\nUnd noch mehr Jedermann Überall Immer Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen'),
    (3, 'charly@example.cde', True, NULL, 'Charly', 'Charly C.', 'Clown', False, False, False, False, False, False, False, True, True, True, True, True, False, False, NULL, NULL, 10, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '22969', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Ich bin ein "Künstler"; im weiteren Sinne.', 1, True, True, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'charly@example.cde  Charly C. Charly Clown   1984-05-13   Am Zelt 1  2345 Zirkusstadt'),
    (4, 'daniel@example.cde', True, NULL, 'Daniel', 'Daniel D.', 'Dino', False, False, False, False, False, False, False, True, True, True, True, False, False, False, NULL, NULL, 2, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'daniel@example.cde  Daniel D. Daniel Dino   1963-02-19   Am Denkmal 91  76543 Atlantis'),
    (5, 'emilia@example.cde', True, NULL, 'Emilia', 'Emilia E.', 'Eventis', False, False, False, False, False,  False, False, False, True, True, False, False, False, False, NULL, NULL, 1, date '2012-06-02', '+49 (5432) 555666777', NULL, NULL, 'Hohle Gasse 13', '56767', 'Wolkenkuckuksheim', 'Deutschland', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'emilia@example.cde Emilia Emilia E. Eventis 2012-06-02 +49 (5432) 555666777 Hohle Gasse 13 56767 Wolkenkuckuksheim Deutschland'),
    (6, 'ferdinand@example.cde', True, NULL, 'Ferdinand', 'Ferdinand F.', 'Findus', False, False, True, True, True, True, True, True, True, True, True, True, True, False, NULL, NULL, 2, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64354', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'ferdinand@example.cde  Ferdinand F. Ferdinand Findus   1988-01-01   Am Rathaus 1  64358 Burokratia'),
    (7, 'garcia@example.cde', True, NULL, 'Garcia', 'Garcia G.', 'Generalis', False, False, False, False, False, False, False, True, True, True, True, True, False, False, NULL, NULL, 1, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '88484', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'garcia@example.cde Garcia Garcia G. Generalis 1978-12-12 Bei der Wüste 39 8888 Weltstadt'),
    (8, NULL, False, NULL, 'Hades', 'Hades', 'Hell', False, False, False, False, False, False, False, False, False, False, False, False, False, True, NULL, NULL, NULL, date '1977-11-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Κόλαση', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, False, False, False,  NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Hades Hades Hell Κόλαση 1977-11-10'),
    (9, 'inga@example.cde', True, NULL,  'Inga', 'Inga', 'Iota', False, False, False, False, False, False, False, True, True, True, True, True, True, False, NULL, NULL, 1, date '2222-01-01', NULL, '0163/456897', NULL, 'Zwergstraße 1', '10999', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, E'# Inga\n\nKleines Inhaltsverzeichnis\n\n[TOC]\n\n## Auslandsjahr\n\nIch war ein Jahr in Südafrika. Dort habe ich viele Dinge besucht.\n\n  - den Nationalpark\n  - verschiedene Städte\n\n  1. Johannisburg\n  2. Cape Town\n\n## Literatur\n\nIch lese gerne\n\n  - Vampirroman,\n  - Wächter-Romane (nicht den >>Wachturm<<, das ist eine ganz schräge Zeitschrift von ziemlich dubiosen Typen),\n  - Ikea-Anleitungen.\n\n## Musik\n\nEs gibt ganz viel schreckliche *Popmusik* und so viel bessere **klassische Musik**, beispielsweise ``Bach`` und ``Beethoven`` sind vorne dabei [^1].\n\n## Programmieren\n\nMein Lieblingsprogramm:\n\n    int main ( int argc, char *argv[] ) {\n        printf("Hello World\\n");\n        return 0;\n    }\n\nUnd hier gleich noch mal:\n\n~~~~~~~~~~~~~~~~~~.c\nint main ( int argc, char *argv[] ) {\n    printf("Hello World\\n");\n    return 0;\n}\n~~~~~~~~~~~~~~~~~~\n\nAber alles, was etwas mit einem Buch aus Abschnitt `Literatur` zu tun hat ist auch gut.\n\n## Referenzen\n\nDer CdE ist voll cool und hat eine Homepage <http://www.cde-ev.de>{: .btn .btn-xs .btn-warning }. Dort kann man auch jederzeit gerne eine Akademie organisieren [^2]. Außerdem gibt es verschiedene Teams, die den Verein am laufen halten\n\nAdmin-Team\n:  Kümmert sich um den Server für die Datenbank\n\nDatenbank-Team\n:  Entwickelt die Datenbank\n\nDoku-Team\n:  Druckt zu jeder Akademie ein Buch\n\n<script>evil();</script>\n\n-- --- ...  "" ''''\n\n[^1]: Über die Qualitäten von ``Mozart`` kann man streiten.\n[^2]: Orga sein hat viele tolle Vorteile:\n\n    - entscheide über die Schokoladensorten\n    - suche Dir Dein Lieblingshaus aus\n    - werde von allen Teilnehmern angehimmelt\n    - lasse Dich bestechen\n\n*[CdE]: Club der Ehemaligen', 5, True, True, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'inga@example.cde Inga Iota 2222-01-01 Zwergstraße 1 1111 Liliput'),
    (10, 'janis@example.cde', True, 'sharp tongue', 'Janis', 'Janis', 'Jalapeño', False, False, False, False, False, False, False, False, False, True, False, False, False, False, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,  NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', E'janis@example.cde Janis Janis Jalapeño'),
    (11, 'kalif@example.cde', True, 'represents our foreign friends', 'Kalif', 'Kalif ibn al-Ḥasan', 'Karabatschi', False, False, False, False, False, False, False, False, False, True, True, False, False, False, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,  NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'kalif@example.cde Kalif Kalif ibn al-Ḥasan Karabatschi'),
    (12, NULL, True, NULL, 'Lisa', 'Lisa', 'Lost', False, False, False, False, False, False, False, True, True, True, True, True, True, False, NULL, NULL, 1, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 50, True, True, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Lisa Lost Lisa'),
    (13, 'martin@example.cde', True, NULL, 'Martin', 'Martin', 'Meister', True, False, False, False, False, False, False, True, True, True, True, True, False, False, NULL, NULL, 2, '2019-07-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 25, True, False, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'martin@example.cde Martin Meister 2019-07-10'),
    (15, 'olaf@example.cde', False, 'Aktuell deaktiviert weil er seine Admin-Rechte missbraucht, um Benutzer in ihrem Profil zu Rickrollen.', 'Olaf', 'Olaf', 'Olafson', False, False, True, False, False, False, False, True, True, True, True, True, True, False, 'Prof.', NULL, 2, '1979-07-06', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 50.12, True, False, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'olaf@example.cde Olaf Olafson 1979-07-06');
INSERT INTO core.changelog (submitted_by, reviewed_by, ctime, generation, change_note, change_status, persona_id, username, is_active, notes, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin, is_event_admin, is_ml_admin, is_assembly_admin, is_cde_realm, is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived, display_name, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, foto) VALUES
    (1, NULL, now(), 1, 'Init.', 2, 1, 'anton@example.cde', True, NULL, True, True, True, True, True, True, True, True, True, True, True, True, True, False, 'Anton', 'Administrator', 'Anton Armin A.', NULL, NULL, 2, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True, NULL),
    (2, NULL, now(), 1, 'Init.', 2, 2, 'berta@example.cde', True, NULL, False, False, False, False, False, False, False, True, True, True, True, True, True, False, 'Bertå',  'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 1, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel  \nGut verteilt  \nÜber mehrere Zeilen', 12.5, True, False, True, 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9'),
    (1, NULL, now(), 1, 'Init.', 2, 3, 'charly@example.cde', True, NULL, False, False, False, False, False, False, False, True, True, True, True, True, False, False, 'Charly',  'Clown', 'Charly C.', NULL, NULL, 10, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '22969', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Ich bin ein "Künstler"; im weiteren Sinne.', 1, True, True, False, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 4, 'daniel@example.cde', True, NULL, False, False, False, False, False, False, False, True, True, True, True, False, False, False, 'Daniel',  'Dino', 'Daniel D.', NULL, NULL, 2, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 5, 'emilia@example.cde', True, NULL, False, False, False, False, False, False, False, False, True, True, False, False, False, False, 'Emilia', 'Eventis', 'Emilia E.', NULL, NULL, 1, date '2012-06-02', '+49 (5432) 555666777', NULL, NULL, 'Hohle Gasse 13', '56767', 'Wolkenkuckuksheim', 'Deutschland', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 6, 'ferdinand@example.cde', True, NULL, False, False, True, True, True, True, True, True, True, True, True, True, True, False, 'Ferdinand',  'Findus', 'Ferdinand F.', NULL, NULL, 2, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64354', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 7, 'garcia@example.cde', True, NULL, False, False, False, False, False, False, False, True, True, True, True, True, False, False, 'Garcia',  'Generalis', 'Garcia G.', NULL, NULL, 1, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '88484', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 8, NULL, False, NULL, False, False, False, False, False, False, False, False, False, False, False, False, False, True, 'Hades',  'Hell', 'Hades', NULL, NULL, NULL, date '1977-11-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Κόλαση', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, False, False, False, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 9, 'inga@example.cde', True, NULL, False, False, False, False, False, False, False, True, True, True, True, True, True, False, 'Inga',  'Iota', 'Inga', NULL, NULL, 1, date '2222-01-01', NULL, NULL, NULL, 'Zwergstraße 1', '10999', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, E'# Inga\n\nKleines Inhaltsverzeichnis\n\n[TOC]\n\n## Auslandsjahr\n\nIch war ein Jahr in Südafrika. Dort habe ich viele Dinge besucht.\n\n  - den Nationalpark\n  - verschiedene Städte\n\n  1. Johannisburg\n  2. Cape Town\n\n## Literatur\n\nIch lese gerne\n\n  - Vampirroman,\n  - Wächter-Romane (nicht den >>Wachturm<<, das ist eine ganz schräge Zeitschrift von ziemlich dubiosen Typen),\n  - Ikea-Anleitungen.\n\n## Musik\n\nEs gibt ganz viel schreckliche *Popmusik* und so viel bessere **klassische Musik**, beispielsweise ``Bach`` und ``Beethoven`` sind vorne dabei [^1].\n\n## Programmieren\n\nMein Lieblingsprogramm:\n\n    int main ( int argc, char *argv[] ) {\n        printf("Hello World\\n");\n        return 0;\n    }\n\nUnd hier gleich noch mal:\n\n~~~~~~~~~~~~~~~~~~.c\nint main ( int argc, char *argv[] ) {\n    printf("Hello World\\n");\n    return 0;\n}\n~~~~~~~~~~~~~~~~~~\n\nAber alles, was etwas mit einem Buch aus Abschnitt `Literatur` zu tun hat ist auch gut.\n\n## Referenzen\n\nDer CdE ist voll cool und hat eine Homepage <http://www.cde-ev.de>{: .btn .btn-xs .btn-warning }. Dort kann man auch jederzeit gerne eine Akademie organisieren [^2]. Außerdem gibt es verschiedene Teams, die den Verein am laufen halten\n\nAdmin-Team\n:  Kümmert sich um den Server für die Datenbank\n\nDatenbank-Team\n:  Entwickelt die Datenbank\n\nDoku-Team\n:  Druckt zu jeder Akademie ein Buch\n\n<script>evil();</script>\n\n-- --- ...  "" ''\n\n[^1]: Über die Qualitäten von ``Mozart`` kann man streiten.\n[^2]: Orga sein hat viele tolle Vorteile:\n\n    - entscheide über die Schokoladensorten\n    - suche Dir Dein Lieblingshaus aus\n    - werde von allen Teilnehmern angehimmelt\n    - lasse Dich bestechen\n\n*[CdE]: Club der Ehemaligen', 5, True, True, True, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 10, 'janis@example.cde', True, 'sharp tongue', False, False, False, False, False, False, False, False, False, True, False, False, False, False, 'Janis', 'Jalapeño', 'Janis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 11, 'kalif@example.cde', True, 'represents our foreign friends', False, False, False, False, False, False, False, False, False, True, True, False, False, False, 'Kalif', 'Karabatschi', 'Kalif ibn al-Ḥasan', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 12, NULL, True, NULL, False, False, False, False, False, False, False, True, True, True, True, True, True, False, 'Lisa', 'Lost', 'Lisa', NULL, NULL, 1, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 50, True, True, True, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 13, 'martin@example.cde', True, NULL, True, False, False, False, False, False, False, True, True, True, True, True, False, False, 'Martin', 'Meister', 'Martin', NULL, NULL, 2, '2019-07-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 25, True, False, False, NULL),
    (1, NULL, now(), 1, 'Init.', 2, 15, 'olaf@example.cde', True, NULL, False, False, True, False, False, False, False, True, True, True, True, True, True, False, 'Olaf', 'Olaf', 'Olafson', 'Prof.', NULL, 2, '1979-07-06', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 50.12, True, False, False, NULL),
    (6, NULL, now(), 2, 'Deaktiviert, weil er seine Admin-Privilegien missbraucht.', 2, 15, 'olaf@example.cde', False, 'Aktuell deaktiviert weil er seine Admin-Rechte missbraucht, um Benutzer in ihrem Profil zu Rickrollen.', False, False, True, False, False, False, False, True, True, True, True, True, True, False, 'Olaf', 'Olaf', 'Olafson', 'Prof.', NULL, 2, '1979-07-06', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 50.12, True, False, False, NULL);
INSERT INTO core.meta_info (info) VALUES
    ('{"Finanzvorstand_Vorname": "Bertålotta",
       "Finanzvorstand_Name": "Bertålotta Beispiel",
       "Finanzvorstand_Adresse_Einzeiler": "Bertålotta Beispiel, bei Spielmanns, Im Garten 77, 34576 Utopia",
       "Finanzvorstand_Adresse_Zeile2": "bei Spielmanns",
       "Finanzvorstand_Adresse_Zeile3": "Im Garten 77",
       "Finanzvorstand_Adresse_Zeile4": "34576 Utopia",
       "Finanzvorstand_Ort": "Utopia",
       "CdE_Konto_Inhaber": "CdE e.V.",
       "CdE_Konto_IBAN": "DE26370205000008068900",
       "CdE_Konto_BIC": "BFSWDE33XXX",
       "CdE_Konto_Institut": "Bank für Sozialwirtschaft",
       "banner_before_login": "Das Passwort ist secret!",
       "Vorstand": "Anton und Berta",
       "banner_after_login": "*Dies ist eine Testversion der Datenbank, alles wird gelöscht werden!*"}'::jsonb);

--
-- cde
--
INSERT INTO cde.org_period (id, billing_state, billing_done, ejection_state, ejection_done, balance_state, balance_done) VALUES
    (41, NULL, timestamp with time zone '2000-01-11 11:11:11.111111+01', NULL, timestamp with time zone '2000-01-12 11:11:11.111111+01', NULL, timestamp with time zone '2000-01-13 11:11:11.111111+01'),
    (42, NULL, now(), NULL, now(), NULL, now()),
    (43, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO cde.expuls_period (id, addresscheck_state, addresscheck_done) VALUES
    (41, NULL, now()),
    (42, NULL, NULL);
INSERT INTO cde.lastschrift (id, submitted_by, persona_id, amount, iban, account_owner, account_address, granted_at, revoked_at, notes) VALUES
    (1, 1, 2, 32.00, 'DE26370205000008068900', NULL, NULL, timestamp with time zone '2000-02-22 22:22:22.222222+02', timestamp with time zone '2001-02-22 22:22:22.222222+02', NULL),
    (2, 1, 2, 42.23, 'DE12500105170648489890', 'Dagobert Anatidae', 'Im Geldspeicher 1', timestamp with time zone '2002-02-22 22:22:22.222222+02', NULL, 'reicher Onkel');
INSERT INTO cde.lastschrift_transactions (submitted_by, lastschrift_id, period_id, status, amount, issued_at, processed_at, tally) VALUES
    (1, 1, 41, 12, 32.00, timestamp with time zone '2000-03-22 00:00:00+02', timestamp with time zone '2012-03-22 22:22:22.222222+02', 0.00),
    (1, 1, 41, 11, 32.00, timestamp with time zone '2000-03-23 00:00:00+02', timestamp with time zone '2012-03-23 22:22:22.222222+02', -4.50),
    (1, 2, 41, 10, 42.23, timestamp with time zone '2012-02-22 00:00:00+02', timestamp with time zone '2012-02-22 22:22:22.222222+02', 42.23);
INSERT INTO cde.finance_log (code, submitted_by, persona_id, delta, new_balance, additional_info, members, total) VALUES
    (32, 1, 2, NULL, NULL, '-4.50€', 7, 106.5),
    (31, 1, 2, 5.0, 12.5, '42.23€', 7, 111.5);

--
-- past_events
--
INSERT INTO past_event.institutions(id, title, moniker) VALUES
    (1, 'Club der Ehemaligen', 'CdE');
INSERT INTO past_event.events (id, title, shortname, institution, tempus, description) VALUES
    (1, 'PfingstAkademie 2014', 'pa14', 1, date '2014-05-25', 'Great event!');
INSERT INTO past_event.courses (id, pevent_id, nr, title, description) VALUES
    (1, 1, '1a', 'Swish -- und alles ist gut', 'Ringelpiez mit anfassen.'),
    (2, 1, 'Ω', 'Goethe zum Anfassen', 'Hier werden die Reime getanzt.');
INSERT INTO past_event.participants (persona_id, pevent_id, pcourse_id, is_instructor, is_orga) VALUES
    (2, 1, 1, True, False),
    (5, 1, 2, False, False);

--
-- events
--
INSERT INTO event.events (id, title, institution, description, shortname, registration_start, registration_soft_limit, registration_hard_limit, is_visible, is_course_list_visible, courses_in_participant_list, iban, orga_address, mail_text, notes, offline_lock, lodge_field, reserve_field, course_room_field) VALUES
    (1, 'Große Testakademie 2222', 1, 'Everybody come!', 'TestAka', timestamp with time zone '2000-10-30 01:00:00+01', timestamp with time zone '2200-10-30 01:00:00+01', timestamp with time zone '2221-10-30 01:00:00+01', True, True, False, 'DE96370205000008068901', 'aka@example.cde', 'Wir verwenden ein neues Kristallkugel-basiertes Kurszuteilungssystem; bis wir das ordentlich ans Laufen gebracht haben, müsst ihr leider etwas auf die Teilnehmerliste warten.', 'Todoliste ... just kidding ;)', False, NULL, NULL, NULL),
    (2, 'CdE-Party 2050', 1, 'Let''s have a party!', 'Party50', timestamp with time zone '2049-12-01 01:00:00+01', timestamp with time zone '2049-12-31 01:00:00+01', timestamp with time zone '2049-12-31 01:00:00+01', False, True, False, 'DE96370205000008068901', '', '', 'Wird anstrengend …', False, NULL, NULL, NULL);
INSERT INTO event.event_parts (id, event_id, title, shortname, part_begin, part_end, fee) VALUES
    (1, 1, 'Warmup', 'Wu', date '2222-2-2', date '2222-2-2', 10.50),
    (2, 1, 'Erste Hälfte', '1.H.', date '2222-11-01', date '2222-11-11', 123.00),
    (3, 1, 'Zweite Hälfte', '2.H.', date '2222-11-11', date '2222-11-30', 450.99),
    (4, 2, 'Party', 'Party', date '2050-01-15', date '2050-01-15', 15.00);
INSERT INTO event.course_tracks (id, part_id, title, shortname, num_choices, min_choices, sortkey) VALUES
    (1, 2, 'Morgenkreis (Erste Hälfte)', 'Morgenkreis', 4, 4, 1),
    (2, 2, 'Kaffeekränzchen (Erste Hälfte)', 'Kaffee', 1, 1, 2),
    (3, 3, 'Arbeitssitzung (Zweite Hälfte)', 'Sitzung', 3, 2, 3);
INSERT INTO event.field_definitions (id, event_id, field_name, kind, association, entries) VALUES
    (1, 1, 'brings_balls', 2, 1, NULL),
    (2, 1, 'transportation', 1, 1, '{{"pedes", "by feet"}, {"car", "own car available"}, {"etc", "anything else"}}'),
    (3, 1, 'lodge', 1, 1, NULL),
    (4, 1, 'may_reserve', 2, 1, NULL),
    (5, 1, 'room', 1, 2, NULL),
    (6, 1, 'contamination', 1, 3, '{{"high", "lots of radiation"}, {"medium", "elevated level of radiation"}, {"low", "some radiation"}, {"none", "no radiation"}}');
UPDATE event.events SET lodge_field = 3, reserve_field = 4, course_room_field = 2 WHERE id = 1;
INSERT INTO event.courses (id, event_id, title, description, nr, shortname, instructors, max_size, min_size, notes, fields) VALUES
    (1, 1, 'Planetenretten für Anfänger', 'Wir werden die Bäume drücken.', 'α', 'Heldentum', 'ToFi & Co', 10, 3, 'Promotionen in Mathematik und Ethik für Teilnehmer notwendig.', '{"room": "Wald"}'::jsonb),
    (2, 1, 'Lustigsein für Fortgeschrittene', 'Inklusive Post, Backwaren und frühzeitigem Ableben.', 'β', 'Kabarett', 'Bernd Lucke', 20, 10, 'Kursleiter hat Sekt angefordert.', '{"room": "Theater"}'::jsonb),
    (3, 1, 'Kurzer Kurs', 'mit hoher Leistung.', 'γ', 'Kurz', 'Heinrich und Thomas Mann', 14, 5, NULL, '{"room": "Seminarraum 42"}'::jsonb),
    (4, 1, 'Langer Kurs', 'mit hohem Umsatz.', 'δ', 'Lang', 'Stephen Hawking und Richard Feynman', NULL, NULL, NULL, '{"room": "Seminarraum 23"}'::jsonb),
    (5, 1, 'Backup-Kurs', 'damit wir Auswahl haben', 'ε', 'Backup', 'TBA', NULL, NULL, NULL, '{"room": "Nirwana"}'::jsonb);
INSERT INTO event.course_segments (course_id, track_id, is_active) VALUES
    (1, 1, True),
    (1, 3, True),
    (2, 1, True),
    (2, 2, False),
    (2, 3, True),
    (3, 2, True),
    (4, 1, True),
    (4, 2, True),
    (4, 3, True),
    (5, 1, True),
    (5, 2, True),
    (5, 3, False);
INSERT INTO event.orgas (persona_id, event_id) VALUES
    (7, 1),
    (1, 2),
    (2, 2);
INSERT INTO event.lodgements (id, event_id, moniker, capacity, reserve, notes, fields) VALUES
    (1, 1, 'Warme Stube', 5, 1, NULL, '{"contamination": "high"}'::jsonb),
    (2, 1, 'Kalte Kammer', 10, 2, 'Dafür mit Frischluft.', '{"contamination": "none"}'::jsonb),
    (3, 1, 'Kellerverlies', 0, 100, 'Nur für Notfälle.', '{"contamination": "low"}'::jsonb),
    (4, 1, 'Einzelzelle', 1, 0, NULL, '{"contamination": "high"}'::jsonb);
INSERT INTO event.registrations (id, persona_id, event_id, notes, orga_notes, payment, parental_agreement, mixed_lodging, checkin, list_consent, fields) VALUES
    (1, 1, 1, NULL, NULL, NULL, True, True, NULL, True, '{"lodge": "Die üblichen Verdächtigen :)"}'::jsonb),
    (2, 5, 1, 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett', 'Unbedingt in die Einzelzelle.', date '2014-02-02', True, True, NULL, True, '{"brings_balls": true, "transportation": "pedes"}'::jsonb),
    (3, 7, 1, NULL, NULL, date '2014-03-03', True, True, NULL, False, '{"transportation": "car"}'::jsonb),
    (4, 9, 1, NULL, NULL, date '2014-04-04', False, False, NULL, False, '{"brings_balls": false, "transportation": "etc", "may_reserve": true}'::jsonb);
INSERT INTO event.registration_parts (registration_id, part_id, status, lodgement_id, is_reserve) VALUES
    (1, 1, -1, NULL, False),
    (1, 2, 1, NULL, False),
    (1, 3, 2, 1, False),
    (2, 1, 3, NULL, False),
    (2, 2, 4, 4, False),
    (2, 3, 2, 4, False),
    (3, 1, 2, 2, False),
    (3, 2, 2, NULL, False),
    (3, 3, 2, 2, False),
    (4, 1, 6, NULL, False),
    (4, 2, 5, NULL, False),
    (4, 3, 2, 2, True);
INSERT INTO event.registration_tracks (registration_id, track_id, course_id, course_instructor) VALUES
    (1, 1, NULL, NULL),
    (1, 2, NULL, NULL),
    (1, 3, NULL, NULL),
    (2, 1, NULL, NULL),
    (2, 2, NULL, NULL),
    (2, 3, 1, 1),
    (3, 1, NULL, NULL),
    (3, 2, 2, NULL),
    (3, 3, NULL, NULL),
    (4, 1, NULL, NULL),
    (4, 2, NULL, NULL),
    (4, 3, 1, NULL);
INSERT INTO event.course_choices (registration_id, track_id, course_id, rank) VALUES
    (1, 1, 1, 0),
    (1, 1, 3, 1),
    (1, 1, 4, 2),
    (1, 1, 2, 3),
    (1, 2, 2, 0),
    (1, 3, 1, 0),
    (1, 3, 4, 1),
    (2, 1, 5, 0),
    (2, 1, 4, 1),
    (2, 1, 2, 2),
    (2, 1, 1, 3),
    (2, 2, 3, 0),
    (2, 3, 4, 0),
    (2, 3, 2, 1),
    (3, 1, 4, 0),
    (3, 1, 2, 1),
    (3, 1, 1, 2),
    (3, 1, 5, 3),
    (3, 2, 2, 0),
    (3, 3, 2, 0),
    (3, 3, 4, 1),
    (4, 1, 2, 0),
    (4, 1, 1, 1),
    (4, 1, 4, 2),
    (4, 1, 5, 3),
    (4, 2, 4, 0),
    (4, 3, 1, 0),
    (4, 3, 2, 1);
INSERT INTO event.questionnaire_rows (event_id, field_id, pos, title, info, input_size, readonly, default_value) VALUES
    (1, NULL, 0, 'Unterüberschrift', 'mit Text darunter', NULL, NULL, NULL),
    (1, 1, 1, 'Bälle', 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.', NULL, False, 'True'),
    (1, NULL, 2, NULL, 'nur etwas Text', NULL, NULL, NULL),
    (1, NULL, 3, 'Weitere Überschrift', NULL, NULL, NULL, NULL),
    (1, 2, 4, 'Vehikel', NULL, NULL, False, 'etc'),
    (1, 3, 5, 'Hauswunsch', NULL, 3, False, NULL);
INSERT INTO event.log (ctime, code, submitted_by, event_id, persona_id, additional_info) VALUES
    (timestamp with time zone '2014-01-01 03:04:05+02', 50, 1, 1, 1, NULL),
    (timestamp with time zone '2014-01-01 04:05:06+02', 50, 5, 1, 5, NULL),
    (timestamp with time zone '2014-01-01 05:06:07+02', 50, 7, 1, 7, NULL),
    (timestamp with time zone '2014-01-01 06:07:08+02', 50, 9, 1, 9, NULL);

--
-- assembly
--
INSERT INTO assembly.assemblies (id, title, description, mail_address, signup_end) VALUES
    (1, 'Internationaler Kongress', 'Proletarier aller Länder vereinigt Euch!', 'kongress@example.cde', date '2111-11-11');

INSERT INTO assembly.ballots (id, assembly_id, title, description, vote_begin, vote_end, vote_extension_end, extended, use_bar, quorum, votes, is_tallied, notes) VALUES
    (1, 1, 'Antwort auf die letzte aller Fragen', 'Nach dem Leben, dem Universum und dem ganzen Rest.', timestamp with time zone '2002-02-22 22:22:22.222222+02', timestamp with time zone '2002-02-23 22:22:22.222222+02', now(), True, True, 2, NULL, False, NULL),
    (2, 1, 'Farbe des Logos', 'Ulitmativ letzte Entscheidung', timestamp with time zone '2222-02-02 22:22:22.222222+02', timestamp with time zone '2222-02-03 22:22:22.222222+02', NULL, NULL, False, 0, NULL, False, 'Nochmal alle auf diese wichtige Entscheidung hinweisen.'),
    (3, 1, 'Bester Hof', 'total objektiv', timestamp with time zone '2000-02-10 22:22:22.222222+02', timestamp with time zone '2222-02-11 22:22:22.222222+02', NULL, NULL, True, 0, 1, False, NULL),
    (4, 1, 'Akademie-Nachtisch', 'denkt an die Frutaner', now(), timestamp with time zone '2222-01-01 22:22:22.222222+02', NULL, NULL, True, 0, 2, False, NULL),
    (5, 1, 'Lieblingszahl', NULL, now(), timestamp with time zone '2222-01-01 22:22:22.222222+02', NULL, NULL, False, 0, NULL, False, NULL);

INSERT INTO assembly.candidates (id, ballot_id, description, moniker) VALUES
    (2, 1, 'Ich', '1'),
    (3, 1, '23', '2'),
    (4, 1, '42', '3'),
    (5, 1, 'Philosophie', '4'),
    (6, 2, 'Rot', 'rot'),
    (7, 2, 'Gelb', 'gelb'),
    (8, 2, 'Grün', 'gruen'),
    (9, 2, 'Blau', 'blau'),
    (10, 3, 'Lischert', 'Li'),
    (11, 3, 'Steinsgebiss', 'St'),
    (12, 3, 'Fichte', 'Fi'),
    (13, 3, 'Buchwald', 'Bu'),
    (14, 3, 'Löscher', 'Lo'),
    (15, 3, 'Goldborn', 'Go'),
    (17, 4, 'Wackelpudding', 'W'),
    (18, 4, 'Salat', 'S'),
    (19, 4, 'Eis', 'E'),
    (20, 4, 'Joghurt', 'J'),
    (21, 4, 'Nichts', 'N'),
    (23, 5, 'e', 'e'),
    (24, 5, 'pi', 'pi'),
    (25, 5, 'i', 'i'),
    (26, 5, '1', '1'),
    (27, 5, '0', '0');

INSERT INTO assembly.attendees (assembly_id, persona_id, secret) VALUES
    (1, 1, 'aoeuidhtns'),
    (1, 2, 'snthdiueoa'),
    (1, 9, 'asonetuhid'),
    (1, 11, 'bxronkxeud');

INSERT INTO assembly.voter_register (persona_id, ballot_id, has_voted) VALUES
    (1, 1, True),
    (1, 2, False),
    (1, 3, False),
    (1, 4, False),
    (1, 5, False),
    (2, 1, True),
    (2, 2, False),
    (2, 3, True),
    (2, 4, False),
    (2, 5, False),
    (9, 1, True),
    (9, 2, False),
    (9, 3, False),
    (9, 4, False),
    (9, 5, False),
    (11, 1, True),
    (11, 2, False),
    (11, 3, False),
    (11, 4, False),
    (11, 5, False);

INSERT INTO assembly.votes (ballot_id, vote, salt, hash) VALUES
    (1, '2>3>_bar_>1=4', 'rxt3x/jnl', 'a3bf0788f1eaa85f5ca979d2ba963b7c60bce02c49ac1c0dfe5d06d5b3950d69c55752df5d963b8de770d353bf795ca07060f7578456b19e18028249bcf51195'),
    (1, '3>2=4>_bar_>1', 'et3[uh{kr', 'f99ade4db2d724c6ae887cffc099c5758927358c99d65aac43e3ce61d212effad5bfbb68e69d6f2669f42d58c74e1fa3f2149a92c7172f2bb9d0e487478e5bb7'),
    (1, '_bar_>4>3>2>1', 'krcqm"xdv', '65ab33a95a367ff3dd07d19ecb9de1311dd3cee5525bae5c7ba6ff46587e79e964e14a246211748f3beb406506b3aa926a66ff5754a69d4c340c98a0f3f5d69d'),
    (1, '1>2=3=4>_bar_', 'klw3xjq8s', '9d59b3a4a6a9eca9613ef2e0710117a8e240e9197f20f2b970288dd93fd6347d657d265033f915c7fa44043315c4a8b834951c4f4e6fc46ea59a795c02af93e7'),
    (3, 'Lo>Li=St=Fi=Bu=Go=_bar_', 'lkn/4kvj9', '314776ac07ffdd56a53112ae5f5113fb356b82b19f3a43754695aa41bf8e120c0346b45e43d0a0114e2bbc7756e7f34ce41f784000c010570d71e90a5c2ab1f1');

--
-- ml
--
INSERT INTO ml.mailinglists (id, title, address, description, sub_policy, mod_policy, attachment_policy, audience_policy, subject_prefix, maxsize, is_active, gateway, event_id, registration_stati, assembly_id) VALUES
    (1, 'Verkündungen', 'announce@example.cde', NULL, 1, 3, 3, 5, '[Hört, hört]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (2, 'Werbung', 'werbung@example.cde', 'Wir werden auch gut bezahlt dafür', 2, 3, 1, 1, '[werbung]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (3, 'Witz des Tages', 'witz@example.cde', 'Einer geht noch ...', 3, 2, 2, 1, '[witz]', 2048, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (4, 'Klatsch und Tratsch', 'klatsch@example.cde', NULL, 4, 1, 1, 1, '[klatsch]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (5, 'Sozialistischer Kampfbrief', 'kongress@example.cde', NULL, 5, 2, 2, 2, '[kampf]', 1024, True, NULL, NULL, ARRAY[]::integer[], 1),
    (6, 'Aktivenforum 2000', 'aktivenforum2000@example.cde', NULL, 5, 2, 2, 5, '[aktivenforum]', 1024, False, NULL, NULL, ARRAY[]::integer[], NULL),
    (7, 'Aktivenforum 2001', 'aktivenforum@example.cde', NULL, 5, 2, 2, 5, '[aktivenforum]', 1024, True, 6, NULL, ARRAY[]::integer[], NULL),
    (8, 'Orga-Liste', 'aka@example.cde', NULL, 5, 1, 1, 3, '[orga]', NULL, True, NULL, 1, ARRAY[]::integer[], NULL),
    (9, 'Teilnehmer-Liste', 'participants@example.cde', NULL, 5, 2, 1, 3, '[aka]', NULL, True, NULL, 1, ARRAY[2, 4], NULL),
    (10, 'Warte-Liste', 'wait@example.cde', NULL, 5, 3, 1, 3, '[wait]', NULL, True, NULL, 1, ARRAY[3], NULL);

INSERT INTO ml.subscription_states (mailinglist_id, persona_id, address, is_subscribed) VALUES
    (1, 3, NULL, False),
    (2, 6, NULL, False),
    (3, 1, NULL, True),
    (3, 2, NULL, False),
    (3, 10, 'janis-spam@example.cde', True),
    (4, 1, NULL, True),
    (4, 2, NULL, True),
    (4, 6, 'ferdinand-unterhaltung@example.cde', True),
    (4, 10, NULL, True),
    (6, 1, NULL, True),
    (6, 2, NULL, True),
    (7, 2, NULL, True),
    (7, 3, NULL, True);

INSERT INTO ml.whitelist (mailinglist_id, address) VALUES
    (2, 'honeypot@example.cde'),
    (6, 'aliens@example.cde'),
    (6, 'drwho@example.cde'),
    (7, 'aliens@example.cde'),
    (7, 'drwho@example.cde'),
    (7, 'captiankirk@example.cde');

INSERT INTO ml.moderators (mailinglist_id, persona_id) VALUES
    (1, 2),
    (2, 10),
    (3, 2),
    (3, 3),
    (3, 10),
    (4, 2),
    (5, 2),
    (6, 2),
    (7, 2),
    (7, 10),
    (8, 7),
    (9, 7),
    (10, 7);

--
-- fix serials (we gave explicit ids since want to have total control over
-- them so we reference the correct things in the test suite)
--
SELECT setval('core.personas_id_seq', 15);
SELECT setval('cde.lastschrift_id_seq', 2);
SELECT setval('past_event.events_id_seq', 1);
SELECT setval('past_event.courses_id_seq', 2);
SELECT setval('past_event.institutions_id_seq', 1);
SELECT setval('event.events_id_seq', 2);
SELECT setval('event.event_parts_id_seq', 4);
SELECT setval('event.course_tracks_id_seq', 3);
SELECT setval('event.courses_id_seq', 5);
SELECT setval('event.field_definitions_id_seq', 6);
SELECT setval('event.lodgements_id_seq', 4);
SELECT setval('event.registrations_id_seq', 4);
SELECT setval('event.log_id_seq', 4);
SELECT setval('ml.mailinglists_id_seq', 10);
SELECT setval('assembly.assemblies_id_seq', 1);
SELECT setval('assembly.ballots_id_seq', 5);
SELECT setval('assembly.candidates_id_seq', 27);
