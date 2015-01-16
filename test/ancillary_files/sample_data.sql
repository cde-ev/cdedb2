--
-- personas
--
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES
    (1, 'anton@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Anton', True, 0, 1, True),
    (2, 'berta@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Bertå', True, 0, 0, True),
    (3, 'charly@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Charly', True, 1, 0, True),
    (4, 'daniel@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Daniel', False, 2, 0, False),
    (5, 'emilia@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Emilia', True, 20, 0, False),
    (6, 'ferdinand@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Ferdinand', True, 0, 254, True),
    (7, 'garcia@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Garcia', True, 1, 0, True),
    (8, NULL, '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Hades', False, 10, 0, False),
    (9, 'inga@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Inga', True, 0, 0, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext, foto) VALUES
    (1, 'Administrator', 'Anton Armin A.', NULL, NULL, 1, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True, 'anton@example.cde  Anton Armin A. Anton Administrator   1991-03-30 +49 (234) 98765  Auf der Düne 42  03205 Musterstadt  Unter dem Hügel 23  22335 Hintertupfingen', NULL),
    (2, 'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True, E'berta@example.cde Dr. Bertålotta Bertå Beispiel Gemeinser MdB 1981-02-11 +49 (5432) 987654321 0163/123456789 Im Garten 77 bei Spielmanns 34576 Utopia  Strange Road 9 3/4  8XA 45-$ Foreign City Far Away https://www.bundestag.cde Alles\nUnd noch mehr Jedermann Überall Immer Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9'),
    (3, 'Clown', 'Charly C.', NULL, NULL, 2, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, True, True, False, 'charly@example.cde  Charly C. Charly Clown   1984-05-13   Am Zelt 1  2345 Zirkusstadt', NULL),
    (4, 'Dino', 'Daniel D.', NULL, NULL, 1, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True, 'daniel@example.cde  Daniel D. Daniel Dino   1963-02-19   Am Denkmal 91  76543 Atlantis', NULL),
    (6, 'Findus', 'Ferdinand F.', NULL, NULL, 1, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64358', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False, 'ferdinand@example.cde  Ferdinand F. Ferdinand Findus   1988-01-01   Am Rathaus 1  64358 Burokratia', NULL),
    (7, 'Generalis', 'Garcia G.', NULL, NULL, 0, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False, 'garcia@example.cde  Garcia G. Garcia Generalis   1978-12-12   Bei der Wüste 39  8888 Weltstadt', NULL),
    (8, 'Hell', 'Hades', NULL, NULL, 1, date '1977-11-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'Κόλαση', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0.0, False, False, False, '', NULL),
    (9, 'Iota', 'Inga', NULL, NULL, 0, date '2015-01-01', NULL, '0163/456897', NULL, 'Zwergstraße 1', '1111', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, True, True, True, 'inga@example.cde Inga Iota 2015-01-01 Zwergstraße 1 1111 Liliput', NULL);
INSERT INTO event.user_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes) VALUES
    (5, 'Eventis', 'Emilia E.', NULL, NULL, 0, date '2012-06-02', '+49 (5432) 555666777', NULL, NULL, 'Hohle Gasse 13', '56767', 'Wolkenkuckuksheim', 'Deutschland', NULL);
INSERT INTO core.changelog (submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES
    (1, NULL, now(), 1, 'Init.', 1, 1, 'anton@example.cde', 'Anton', True, 0, 1, True,'Administrator', 'Anton Armin A.', NULL, NULL, 1, date '1991-03-30', '+49 (234) 98765', NULL, NULL, 'Auf der Düne 42', '03205', 'Musterstadt', NULL, NULL, NULL, NULL, 'Unter dem Hügel 23', '22335', 'Hintertupfingen', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True),
    (2, NULL, now(), 1, 'Init.', 1, 2, 'berta@example.cde', 'Bertå', True, 0, 0, True, 'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', NULL, NULL, 'Gemeinser', NULL, 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True),
    (1, NULL, now(), 1, 'Init.', 1, 3, 'charly@example.cde', 'Charly', True, 1, 0, True, 'Clown', 'Charly C.', NULL, NULL, 2, date '1984-05-13', NULL, NULL, NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, True, True, False),
    (1, NULL, now(), 1, 'Init.', 1, 4, 'daniel@example.cde', 'Daniel', False, 2, 0, False, 'Dino', 'Daniel D.', NULL, NULL, 1, date '1963-02-19', NULL, NULL, NULL, 'Am Denkmal 91', '76543', 'Atlantis', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, False, False, True),
    (1, NULL, now(), 1, 'Init.', 1, 6, 'ferdinand@example.cde', 'Ferdinand', True, 0, 254, True, 'Findus', 'Ferdinand F.', NULL, NULL, 1, date '1988-01-01', NULL, NULL, NULL, 'Am Rathaus 1', '64358', 'Burokratia', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 22.2, True, False, False),
    (1, NULL, now(), 1, 'Init.', 1, 7, 'garcia@example.cde', 'Garcia', True, 1, 0, True, 'Generalis', 'Garcia G.', NULL, NULL, 0, date '1978-12-12', NULL, NULL, NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 3.3, False, False, False),
    (1, NULL, now(), 1, 'Init.', 1, 9, 'inga@example.cde', 'Inga', True, 1, 0, True, 'Iota', 'Inga', NULL, NULL, 0, date '2015-01-01', NULL, NULL, NULL, 'Zwergstraße 1', '1111', 'Liliput', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, True, True, True);

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
INSERT INTO event.events (id, title, organizer, description, shortname, registration_start, registration_soft_limit, registration_hard_limit, notes, offline_lock) VALUES
    (1, 'Große Testakademie 2222', 'CdE', 'Everybody come!', 'TestAka', date '2000-10-30', date '2200-10-30', date '2220-10-30', 'Todoliste ... just kidding ;)', False);
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
    (2, 1, 'transportation', 'str', '{{"pedes", "by feet"}, {"car", "own car available"}, {"etc", "anything else"}}');
INSERT INTO event.lodgements (id, event_id, moniker, capacity, reserve, notes) VALUES
    (1, 1, 'Warme Stube', 5, 1, NULL),
    (2, 1, 'Kalte Kammer', 10, 2, 'Dafür mit Frischluft.'),
    (3, 1, 'Kellerverlies', 0, 100, 'Nur für Notfälle.'),
    (4, 1, 'Einzelzelle', 1, 0, NULL);
INSERT INTO event.registrations (id, persona_id, event_id, orga_notes, payment, parental_agreement, mixed_lodging, checkin, foto_consent, field_data) VALUES
    (1, 1, 1, NULL, NULL, NULL, True, NULL, True, '{"registration_id": 1}'::jsonb),
    (2, 5, 1, 'Unbedingt in die Einzelzelle.', date '2014-02-02', NULL, True, NULL, True, '{"registration_id": 2, "brings_balls": true, "transportation": "pedes"}'::jsonb),
    (3, 7, 1, NULL, date '2014-03-03', NULL, True, NULL, True, '{"registration_id": 3, "transportation": "car"}'::jsonb),
    (4, 9, 1, NULL, date '2014-04-04', NULL, False, NULL, True, '{"registration_id": 4, "brings_balls": false, "transportation": "etc"}'::jsonb);
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
INSERT INTO event.questionnaire_rows (event_id, field_id, pos, title, info, readonly) VALUES
    (1, NULL, 0, 'Unterüberschrift', 'mit Text darunter', NULL),
    (1, 1, 1, 'Bälle', 'Du bringst genug Bälle mit um einen ganzen Kurs abzuwerfen.', False),
    (1, NULL, 2, NULL, 'nur etwas Text', NULL),
    (1, NULL, 3, 'Weitere Überschrift', NULL, NULL),
    (1, 2, 4, 'Vehikel', NULL, False);

--
-- fix serials (we want to have total control over some ids so we reference
-- the correct things)
--
SELECT setval('core.personas_id_seq', 9);
SELECT setval('past_event.events_id_seq', 1);
SELECT setval('past_event.courses_id_seq', 1);
SELECT setval('event.events_id_seq', 1);
SELECT setval('event.event_parts_id_seq', 3);
SELECT setval('event.courses_id_seq', 5);
SELECT setval('event.field_definitions_id_seq', 2);
SELECT setval('event.lodgements_id_seq', 4);
SELECT setval('event.registrations_id_seq', 4);
