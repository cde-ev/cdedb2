BEGIN;
    UPDATE core.changelog SET automated_change = TRUE
    WHERE (
            change_note = 'Land auf Ländercode umgestellt.'
            AND ctime >= '2021-03-20 09:42:34' AND ctime <= '2021-03-20 09:42:35'
        );
    UPDATE core.changelog SET automated_change = TRUE
    WHERE (
            change_note = 'Initiale Aktivierung nach Migration'
            AND ctime >= '2019-03-14 19:45:38' AND ctime <= '2019-03-14 19:50:38'
        );
    UPDATE core.changelog SET automated_change = TRUE
    WHERE (
            change_note = 'Repariere Rufnamen die bei der Migration falsch initialisiert wurden.'
            AND ctime >= '2019-03-07 17:46:30' AND ctime <= '2019-03-07 17:46:36'
        );
    UPDATE core.changelog SET automated_change = TRUE
    WHERE (
            change_note = 'E-Mail-Adresse geändert.'
            AND ctime >= '2019-03-05 19:40:13' AND ctime <= '2019-03-05 19:40:46'
        );
COMMIT;
