UPDATE core.changelog SET automated_change = TRUE
WHERE (change_note = 'Land auf Ländercode umgestellt.'
       AND ctime >= '2021-03-20 09:42:43' AND ctime < '2021-03-20 09:42:44');
