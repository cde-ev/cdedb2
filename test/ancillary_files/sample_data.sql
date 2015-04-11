--
-- personas
--
INSERT INTO core.personas (id, username, display_name, given_names, family_name, is_active, status, db_privileges, cloud_account, notes, password_hash) VALUES
    (1, 'anton@example.cde', 'Anton', 'Anton Armin A.', 'Administrator', True, 0, 1, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (2, 'berta@example.cde', 'Bertå', 'Bertålotta', 'Beispiel', True, 0, 0, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (3, 'charly@example.cde', 'Charly', 'Charly C.', 'Clown', True, 1, 0, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (4, 'daniel@example.cde', 'Daniel', 'Daniel D.', 'Dino', False, 2, 0, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (5, 'emilia@example.cde', 'Emilia', 'Emilia E.', 'Eventis', True, 20, 0, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (6, 'ferdinand@example.cde', 'Ferdinand', 'Ferdinand F.', 'Findus', True, 0, 254, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (7, 'garcia@example.cde', 'Garcia', 'Garcia G.', 'Generalis', True, 1, 0, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (8, NULL, 'Hades', 'Hades', 'Hell', False, 10, 0, False, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (9, 'inga@example.cde', 'Inga', 'Inga', 'Iota', True, 0, 0, True, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (10, 'janis@example.cde', 'Janis', 'Janis', 'Jalapeño', True, 40, 0, False, 'sharp tongue', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/'),
    (11, 'kalif@example.cde', 'Kalif', 'Kalif ibn al-Ḥasan', 'Karabatschi', True, 30, 0, False, 'represents our foreign friends', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/');
INSERT INTO cde.member_data (persona_id, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext, foto) VALUES
    (1, NULL, NULL, 1, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True, 'anton@example.cde  Anton Armin A. Anton Administrator   1991-03-30 +49 (234) 98765  Auf der Düne 42  03205 Musterstadt  Unter dem Hügel 23  22335 Hintertupfingen', NULL),
    (2, 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True, E'berta@example.cde Dr. Bertålotta Bertå Beispiel Gemeinser MdB 1981-02-11 +49 (5432) 987654321 0163/123456789 Im Garten 77 bei Spielmanns 34576 Utopia  Strange Road 9 3/4  8XA 45-$ Foreign City Far Away https://www.bundestag.cde Alles\nUnd noch mehr Jedermann Überall Immer Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9'),
    (3, NULL, NULL, 2, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, True, True, False, 'charly@example.cde  Charly C. Charly Clown   1984-05-13   Am Zelt 1  2345 Zirkusstadt', NULL),
    (4, NULL, NULL, 1, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True, 'daniel@example.cde  Daniel D. Daniel Dino   1963-02-19   Am Denkmal 91  76543 Atlantis', NULL),
    (6, NULL, NULL, 1, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64358', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False, 'ferdinand@example.cde  Ferdinand F. Ferdinand Findus   1988-01-01   Am Rathaus 1  64358 Burokratia', NULL),
    (7, NULL, NULL, 0, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False, 'garcia@example.cde  Garcia G. Garcia Generalis   1978-12-12   Bei der Wüste 39  8888 Weltstadt', NULL),
    (8, NULL, NULL, 1, date '1977-11-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Κόλαση', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0.0, False, False, False, '', NULL),
    (9, NULL, NULL, 0, date '2222-01-01', NULL, '0163/456897', NULL, 'Zwergstraße 1', '1111', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, True, True, True, 'inga@example.cde Inga Iota 2222-01-01 Zwergstraße 1 1111 Liliput', NULL);
INSERT INTO event.user_data (persona_id, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country) VALUES
    (5, NULL, NULL, 0, date '2012-06-02', '+49 (5432) 555666777', NULL, NULL, 'Hohle Gasse 13', '56767', 'Wolkenkuckuksheim', 'Deutschland');
INSERT INTO core.changelog (submitted_by, reviewed_by, ctime, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES
    (1, NULL, now(), 1, 'Init.', 1, 1, 'anton@example.cde', 'Anton', True, 0, 1, True,'Administrator', 'Anton Armin A.', NULL, NULL, 1, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True),
    (2, NULL, now(), 1, 'Init.', 1, 2, 'berta@example.cde', 'Bertå', True, 0, 0, True, 'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True),
    (1, NULL, now(), 1, 'Init.', 1, 3, 'charly@example.cde', 'Charly', True, 1, 0, True, 'Clown', 'Charly C.', NULL, NULL, 2, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, True, True, False),
    (1, NULL, now(), 1, 'Init.', 1, 4, 'daniel@example.cde', 'Daniel', False, 2, 0, False, 'Dino', 'Daniel D.', NULL, NULL, 1, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True),
    (1, NULL, now(), 1, 'Init.', 1, 6, 'ferdinand@example.cde', 'Ferdinand', True, 0, 254, True, 'Findus', 'Ferdinand F.', NULL, NULL, 1, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64358', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False),
    (1, NULL, now(), 1, 'Init.', 1, 7, 'garcia@example.cde', 'Garcia', True, 1, 0, True, 'Generalis', 'Garcia G.', NULL, NULL, 0, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False),
    (1, NULL, now(), 1, 'Init.', 1, 9, 'inga@example.cde', 'Inga', True, 1, 0, True, 'Iota', 'Inga', NULL, NULL, 0, date '2222-01-01', NULL, NULL, NULL, 'Zwergstraße 1', '1111', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, True, True, True);

--
-- past_events
--
INSERT INTO past_event.events (id, title, organizer, description) VALUES
    (1, 'PfingstAkademie 2014', 'CdE', 'Great event!');
INSERT INTO past_event.courses (id, event_id, title, description) VALUES
    (1, 1, 'Swish -- und alles ist gut', 'Ringelpiez mit anfassen.');
INSERT INTO past_event.participants (persona_id, event_id, course_id, is_instructor, is_orga) VALUES
    (2, 1, 1, True, False);
--
-- events
--
INSERT INTO event.events (id, title, organizer, description, shortname, registration_start, registration_soft_limit, registration_hard_limit, iban, notes, offline_lock) VALUES
    (1, 'Große Testakademie 2222', 'CdE', 'Everybody come!', 'TestAka', date '2000-10-30', date '2200-10-30', date '2220-10-30', 'DE96 3702 0500 0008 0689 01', 'Todoliste ... just kidding ;)', False);
INSERT INTO event.event_parts (id, event_id, title, part_begin, part_end, fee) VALUES
    (1, 1, 'Warmup', date '2222-2-2', date '2222-2-2', 10.50),
    (2, 1, 'Erste Hälfte', date '2222-11-01', date '2222-11-11', 123.00),
    (3, 1, 'Zweite Hälfte', date '2222-11-11', date '2222-11-30', 450.99);
INSERT INTO event.courses (id, event_id, title, description, nr, shortname, instructors, notes) VALUES
    (1, 1, 'Planetenretten für Anfänger', 'Wir werden die Bäume drücken.', 'α', 'Heldentum', 'ToFi & Co', 'Promotionen in Mathematik und Ethik für Teilnehmer notwendig.'),
    (2, 1, 'Lustigsein für Fortgeschrittene', 'Inklusive Post, Backwaren und frühzeitigem Ableben.', 'β', 'Kabarett', 'Bernd Lucke', 'Kursleiter hat Sekt angefordert.'),
    (3, 1, 'Kurzer Kurs', 'mit hoher Leistung.', 'γ', 'Kurz', 'Heinrich und Thomas Mann', NULL),
    (4, 1, 'Langer Kurs', 'mit hohem Umsatz.', 'δ', 'Lang', 'Stephen Hawking und Richard Feynman', NULL),
    (5, 1, 'Backup-Kurs', 'damit wir Auswahl haben', 'ε', 'Backup', 'TBA', NULL);
INSERT INTO event.course_parts (course_id, part_id) VALUES
    (1, 1),
    (1, 3),
    (2, 2),
    (2, 3),
    (3, 2),
    (4, 1),
    (4, 2),
    (4, 3),
    (5, 1),
    (5, 2),
    (5, 3);
INSERT INTO event.orgas (persona_id, event_id) VALUES
    (7, 1);
INSERT INTO event.field_definitions (id, event_id, field_name, kind, entries) VALUES
    (1, 1, 'brings_balls', 'bool', NULL),
    (2, 1, 'transportation', 'str', '{{"pedes", "by feet"}, {"car", "own car available"}, {"etc", "anything else"}}'),
    (3, 1, 'lodge', 'str', NULL),
    (4, 1, 'may_reserve', 'bool', NULL),
    (5, 1, 'reserve_1', 'bool', NULL),
    (6, 1, 'reserve_2', 'bool', NULL),
    (7, 1, 'reserve_3', 'bool', NULL);
INSERT INTO event.lodgements (id, event_id, moniker, capacity, reserve, notes) VALUES
    (1, 1, 'Warme Stube', 5, 1, NULL),
    (2, 1, 'Kalte Kammer', 10, 2, 'Dafür mit Frischluft.'),
    (3, 1, 'Kellerverlies', 0, 100, 'Nur für Notfälle.'),
    (4, 1, 'Einzelzelle', 1, 0, NULL);
INSERT INTO event.registrations (id, persona_id, event_id, notes, orga_notes, payment, parental_agreement, mixed_lodging, checkin, foto_consent, field_data) VALUES
    (1, 1, 1, NULL, NULL, NULL, NULL, True, NULL, True, '{"registration_id": 1, "lodge": "Die üblichen Verdächtigen :)"}'::jsonb),
    (2, 5, 1, 'Extrawünsche: Meerblick, Weckdienst und Frühstück am Bett', 'Unbedingt in die Einzelzelle.', date '2014-02-02', NULL, True, NULL, True, '{"registration_id": 2, "brings_balls": true, "transportation": "pedes"}'::jsonb),
    (3, 7, 1, NULL, NULL, date '2014-03-03', NULL, True, NULL, True, '{"registration_id": 3, "transportation": "car"}'::jsonb),
    (4, 9, 1, NULL, NULL, date '2014-04-04', NULL, False, NULL, True, '{"registration_id": 4, "brings_balls": false, "transportation": "etc", "may_reserve": true}'::jsonb);
INSERT INTO event.registration_parts (registration_id, part_id, course_id, status, lodgement_id, course_instructor) VALUES
    (1, 1, NULL, -1, NULL, NULL),
    (1, 2, NULL, 0, NULL, NULL),
    (1, 3, NULL, 1, 1, NULL),
    (2, 1, NULL, 2, NULL, NULL),
    (2, 2, NULL, 3, 4, NULL),
    (2, 3,       1, 1, 4, 1),
    (3, 1, NULL, 1, 2, NULL),
    (3, 2, 2,    1, NULL, NULL),
    (3, 3, NULL, 1, 2, NULL),
    (4, 1, NULL, 5, NULL, NULL),
    (4, 2, NULL, 4, NULL, NULL),
    (4, 3, 1,    1, 2, NULL);
INSERT INTO event.course_choices (registration_id, part_id, course_id, rank) VALUES
    (1, 2, 2, 0),
    (1, 2, 3, 1),
    (1, 2, 4, 2),
    (1, 3, 1, 0),
    (1, 3, 4, 1),
    (1, 3, 5, 2),
    (2, 1, 5, 0),
    (2, 1, 4, 1),
    (2, 1, 1, 2),
    (2, 2, 3, 0),
    (2, 2, 4, 1),
    (2, 2, 2, 2),
    (2, 3, 4, 0),
    (2, 3, 2, 1),
    (2, 3, 1, 2),
    (3, 1, 4, 0),
    (3, 1, 1, 1),
    (3, 1, 5, 2),
    (3, 2, 2, 0),
    (3, 2, 3, 1),
    (3, 2, 4, 2),
    (3, 3, 2, 0),
    (3, 3, 4, 1),
    (3, 3, 1, 2),
    (4, 1, 1, 0),
    (4, 1, 4, 1),
    (4, 1, 5, 2),
    (4, 2, 4, 0),
    (4, 2, 2, 1),
    (4, 2, 3, 2),
    (4, 3, 1, 0),
    (4, 3, 2, 1),
    (4, 3, 4, 2);
INSERT INTO event.questionnaire_rows (event_id, field_id, pos, title, info, input_size, readonly) VALUES
    (1, NULL, 0, 'Unterüberschrift', 'mit Text darunter', NULL, NULL),
    (1, 1, 1, 'Bälle', 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.', NULL, False),
    (1, NULL, 2, NULL, 'nur etwas Text', NULL, NULL),
    (1, NULL, 3, 'Weitere Überschrift', NULL, NULL, NULL),
    (1, 2, 4, 'Vehikel', NULL, NULL, False),
    (1, 3, 5, 'Hauswunsch', NULL, 3, False);

--
-- assembly
--
INSERT INTO assembly.assemblies (id, title, description, signup_end) VALUES
    (1, 'Internationaler Kongress', 'Proletarier aller Länder vereinigt Euch!', date '2111-11-11');

INSERT INTO assembly.ballots (id, assembly_id, title, description, vote_begin, vote_end, vote_extension_end, extended, bar, quorum, votes, is_tallied, notes) VALUES
    (1, 1, 'Antwort auf die letzte aller Fragen', 'Nach dem Leben, dem Universum und dem ganzen Rest.', timestamp with time zone '2002-02-22 22:22:22.222222+02', timestamp with time zone '2002-02-23 22:22:22.222222+02', now(), True, NULL, 2, NULL, False, NULL),
    (2, 1, 'Farbe des Logos', 'Ulitmativ letzte Entscheidung', timestamp with time zone '2222-02-02 22:22:22.222222+02', timestamp with time zone '2222-02-03 22:22:22.222222+02', NULL, NULL, NULL, 0, NULL, False, 'Nochmal alle auf diese wichtige Entscheidung hinweisen.'),
    (3, 1, 'Bester Hof', 'total objektiv', timestamp with time zone '2000-02-10 22:22:22.222222+02', timestamp with time zone '2222-02-11 22:22:22.222222+02', NULL, NULL, NULL, 0, 1, False, NULL),
    (4, 1, 'Akademie-Nachtisch', 'denkt an die Frutaner', now(), timestamp with time zone '2222-01-01 22:22:22.222222+02', NULL, NULL, NULL, 0, 2, False, NULL);

INSERT INTO assembly.candidates (id, ballot_id, description, moniker) VALUES
    (1, 1, 'None of the above', '0'),
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
    (16, 3, 'Keine der Optionen', '0'),
    (17, 4, 'Wackelpudding', 'W'),
    (18, 4, 'Salat', 'S'),
    (19, 4, 'Eis', 'E'),
    (20, 4, 'Joghurt', 'J'),
    (21, 4, 'Nichts', 'N'),
    (22, 4, 'Etwas anderes', 'bar');

UPDATE assembly.ballots SET bar = 1 WHERE id = 1;
UPDATE assembly.ballots SET bar = 16 WHERE id = 3;
UPDATE assembly.ballots SET bar = 22 WHERE id = 4;

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
    (2, 1, True),
    (2, 2, False),
    (2, 3, True),
    (2, 4, False),
    (9, 1, True),
    (9, 2, False),
    (9, 3, False),
    (9, 4, False),
    (11, 1, True),
    (11, 2, False),
    (11, 3, False),
    (11, 4, False);

INSERT INTO assembly.votes (ballot_id, vote, salt, hash) VALUES
    (1, '2>3>0>1=4', 'rxt3x\jnl', 'eebbb299075feffbb3fe8c620a2a2e116ec1ba2daacf430bc3201180c32942d3001111d0ab14eb969126e9e616eff0fa12869a9609127cbbd65e3cf8532a9f9e'),
    (1, '3>2=4>0>1', 'et3[uh''kr', '97155c8534388cbb191e6b2bd706f1739a2bbc6dcef363a026afc3e50e9df226adc2acfe289a280fefba2c2207571f9c6b32f729bdfbadee80ac597099b6eee4'),
    (1, '0>4>3>2>1', 'krcqm"xdv', '1b95f13b1819746d948e698ff38bf0ea85bc15ba9e8356e925f6a9f1c2d9810b1b851790de2ecf212b4a8906d39bff04da1817912d641afa4dd2732708aeaaeb'),
    (1, '1>2=3=4>0', 'klw3xjq8s', 'e5f5550c78eaee20d53741b5f361803b756494f69e1a251a942e5e8afae6e58ea7c5307ec2fa8c94c5c6b1e77c6bb71f79d8a30d7e7c3d8e00d9b8697c2133eb'),
    (3, 'Lo>0>Li=St=Fi=Bu=Go', 'lkn\4kvj9', 'f214d18f53bc0efc70632a24ec89e8265b4196651cc534c25d149d58659683678925d17af25d895f9b0402efac92c940551534408899071d9cd1eb2a87c18fab');

--
-- ml
--
INSERT INTO ml.mailinglists (id, title, address, description, sub_policy, mod_policy, attachment_policy, audience, subject_prefix, maxsize, is_active, gateway, event_id, registration_stati, assembly_id) VALUES
    (1, 'Verkündungen', 'announce@example.cde', NULL, 0, 2, 2, ARRAY[0, 1], '[Hört, hört]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (2, 'Werbung', 'werbung@example.cde', 'Wir werden auch gut bezahlt dafür', 1, 2, 0, ARRAY[0, 1, 2, 40], '[werbung]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (3, 'Witz des Tages', 'witz@example.cde', 'Einer geht noch ...', 2, 1, 1, ARRAY[0, 1, 2, 40], '[witz]', 2048, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (4, 'Klatsch und Tratsch', 'klatsch@example.cde', NULL, 3, 0, 0, ARRAY[0, 1, 2, 40], '[klatsch]', NULL, True, NULL, NULL, ARRAY[]::integer[], NULL),
    (5, 'Sozialistischer Kampfbrief', 'kongress@example.cde', NULL, 4, 1, 1, ARRAY[0, 1, 30], '[kampf]', 1024, True, NULL, NULL, ARRAY[]::integer[], 1),
    (6, 'Aktivenforum 2000', 'aktivenforum@example.cde', NULL, 4, 1, 1, ARRAY[0, 1], '[aktivenforum]', 1024, False, NULL, NULL, ARRAY[]::integer[], NULL),
    (7, 'Aktivenforum 2001', 'aktivenforum@example.cde', NULL, 4, 1, 1, ARRAY[0, 1], '[aktivenforum]', 1024, True, 6, NULL, ARRAY[]::integer[], NULL),
    (8, 'Orga-Liste', 'aka@example.cde', NULL, 4, 0, 0, ARRAY[0, 1, 2, 20], '[orga]', NULL, True, NULL, 1, ARRAY[]::integer[], NULL),
    (9, 'Teilnehmer-Liste', 'participants@example.cde', NULL, 4, 1, 0, ARRAY[0, 1, 2, 20], '[aka]', NULL, True, NULL, 1, ARRAY[1, 3], NULL),
    (10, 'Warte-Liste', 'wait@example.cde', NULL, 4, 2, 0, ARRAY[0, 1, 2, 20], '[wait]', NULL, True, NULL, 1, ARRAY[2], NULL);

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
-- fix serials (we want to have total control over some ids so we reference
-- the correct things)
--
SELECT setval('core.personas_id_seq', 11);
SELECT setval('past_event.events_id_seq', 1);
SELECT setval('past_event.courses_id_seq', 1);
SELECT setval('event.events_id_seq', 1);
SELECT setval('event.event_parts_id_seq', 3);
SELECT setval('event.courses_id_seq', 5);
SELECT setval('event.field_definitions_id_seq', 7);
SELECT setval('event.lodgements_id_seq', 4);
SELECT setval('event.registrations_id_seq', 4);
SELECT setval('ml.mailinglists_id_seq', 10);
SELECT setval('assembly.assemblies_id_seq', 1);
SELECT setval('assembly.ballots_id_seq', 4);
SELECT setval('assembly.candidates_id_seq', 22);
--
-- fix more serials (otherwise the test suite gets messed up)
--
SELECT setval('assembly.attachments_id_seq', 1);
