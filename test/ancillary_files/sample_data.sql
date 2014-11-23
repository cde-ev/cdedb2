--
-- personas
--
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (1, 'anton@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Anton', True, 0, 1, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (1, 'Administrator', 'Anton Armin A.', '', '', 1, date '1991-03-30', '+49 (234) 98765', '', '', 'Auf der Düne 42', '03205', 'Musterstadt', '', '', NULL, '', 'Unter dem Hügel 23', '22335', 'Hintertupfingen', '', NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True, 'anton@example.cde  Anton Armin A. Anton Administrator   1991-03-30 +49 (234) 98765  Auf der Düne 42  03205 Musterstadt  Unter dem Hügel 23  22335 Hintertupfingen');
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (1, 1, NULL, now(), 1, 'Init.', 1, 1, 'anton@example.cde', 'Anton', True, 0, 1, True,'Administrator', 'Anton Armin A.', '', '', 1, date '1991-03-30', '+49 (234) 98765', '', '', 'Auf der Düne 42', '03205', 'Musterstadt', '', '', NULL, '', 'Unter dem Hügel 23', '22335', 'Hintertupfingen', '', NULL, NULL, NULL, NULL, NULL, NULL, 17.5, True, False, True);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (2, 'berta@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Bertå', True, 0, 0, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext, foto) VALUES (2, 'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', '', '', 'Gemeinser', '', 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True, E'berta@example.cde Dr. Bertålotta Bertå Beispiel Gemeinser MdB 1981-02-11 +49 (5432) 987654321 0163/123456789 Im Garten 77 bei Spielmanns 34576 Utopia  Strange Road 9 3/4  8XA 45-$ Foreign City Far Away https://www.bundestag.cde Alles\nUnd noch mehr Jedermann Überall Immer Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 'e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9');
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (2, 2, NULL, now(), 1, 'Init.', 1, 2, 'berta@example.cde', 'Bertå', True, 0, 0, True, 'Beispiel', 'Bertålotta', 'Dr.', 'MdB', 0, date '1981-02-11', '+49 (5432) 987654321', '0163/123456789', 'bei Spielmanns', 'Im Garten 77', '34576', 'Utopia', '', '', 'Gemeinser', '', 'Strange Road 9 3/4', '8XA 45-$', 'Foreign City', 'Far Away', 'https://www.bundestag.cde', E'Alles\nUnd noch mehr', 'Jedermann', 'Überall', 'Immer', E'Jede Menge Gefasel \nGut verteilt\nÜber mehrere Zeilen', 12.5, True, False, True);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (3, 'charly@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Charly', True, 1, 0, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (3, 'Clown', 'Charly C.', '', '', 2, date '1984-05-13', '', '', NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 1, True, True, False, 'charly@example.cde  Charly C. Charly Clown   1984-05-13   Am Zelt 1  2345 Zirkusstadt');
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (3, 1, NULL, now(), 1, 'Init.', 1, 3, 'charly@example.cde', 'Charly', True, 1, 0, True, 'Clown', 'Charly C.', '', '', 2, date '1984-05-13', '', '', NULL, 'Am Zelt 1', '2345', 'Zirkusstadt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 1, True, True, False);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (4, 'daniel@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Daniel', False, 2, 0, False);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (4, 'Dino', 'Daniel D.', '', '', 1, date '1963-02-19', '', '', NULL, 'Am Denkmal 91', '76543', 'Atlantis', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 0, False, False, True, 'daniel@example.cde  Daniel D. Daniel Dino   1963-02-19   Am Denkmal 91  76543 Atlantis');
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (4, 1, NULL, now(), 1, 'Init.', 1, 4, 'daniel@example.cde', 'Daniel', False, 2, 0, False, 'Dino', 'Daniel D.', '', '', 1, date '1963-02-19', '', '', NULL, 'Am Denkmal 91', '76543', 'Atlantis', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 0, False, False, True);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (5, 'emilia@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Emilia', True, 20, 0, False);
INSERT INTO event.user_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes) VALUES (5, 'Eventis', 'Emilia E.', '', '', 0, date '2012-06-02', '+49 (5432) 555666777', '', NULL, 'Hohle Gasse 13', '56767', 'Wolkenkuckuksheim', 'Deutschland', '');
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (6, 'ferdinand@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Ferdinand', True, 0, 254, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (6, 'Findus', 'Ferdinand F.', '', '', 1, date '1988-01-01', '', '', NULL, 'Am Rathaus 1', '64358', 'Burokratia', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 22.2, True, False, False, 'ferdinand@example.cde  Ferdinand F. Ferdinand Findus   1988-01-01   Am Rathaus 1  64358 Burokratia');
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (5, 1, NULL, now(), 1, 'Init.', 1, 6, 'ferdinand@example.cde', 'Ferdinand', True, 0, 254, True, 'Findus', 'Ferdinand F.', '', '', 1, date '1988-01-01', '', '', NULL, 'Am Rathaus 1', '64358', 'Burokratia', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 22.2, True, False, False);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (7, 'garcia@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Garcia', True, 1, 0, True);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (7, 'Generalis', 'Garcia G.', '', '', 0, date '1978-12-12', '', '', NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 3.3, False, False, False, 'garcia@example.cde  Garcia G. Garcia Generalis   1978-12-12   Bei der Wüste 39  8888 Weltstadt'); -- will be Orga
INSERT INTO cde.changelog (id, submitted_by, reviewed_by, cdate, generation, change_note, change_status, persona_id, username, display_name, is_active, status, db_privileges, cloud_account, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search) VALUES (6, 1, NULL, now(), 1, 'Init.', 1, 7, 'garcia@example.cde', 'Garcia', True, 1, 0, True, 'Generalis', 'Garcia G.', '', '', 0, date '1978-12-12', '', '', NULL, 'Bei der Wüste 39', '8888', 'Weltstadt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 3.3, False, False, False);
INSERT INTO core.personas (id, username, password_hash, display_name, is_active, status, db_privileges, cloud_account) VALUES (8, 'hades@example.cde', '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', 'Hades', False, 10, 0, False);
INSERT INTO cde.member_data (persona_id, family_name, given_names, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, notes, birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, balance, decided_search, trial_member, bub_search, fulltext) VALUES (8, 'Hell', 'Hades', NULL, NULL, 1, date '1977-11-10', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '', 'Κόλαση', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0.0, False, False, False, '');
--
-- events
--
INSERT INTO event.event_types (id, moniker, organizer) VALUES (1, 'PfingstAkademie', 'CdE e.V.');
INSERT INTO event.events (id, shortname, title, type_id, description, is_db) VALUES (1, 'PA2014', 'PfingstAkademie 2014', 1, '', False);
INSERT INTO event.courses (id, event_id, nr, title, description) VALUES (1, 1, 1, 'Swish -- und alles ist gut', '');
INSERT INTO event.participants (id, persona_id, event_id, course_id, is_instructor, is_orga) VALUES (1, 2, 1, 1, True, False);
--
-- fix serials
--
SELECT setval('cde.changelog_id_seq', 6);
