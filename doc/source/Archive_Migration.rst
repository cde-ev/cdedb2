Migration
=========

This file describes the migration plan from DB version 1 to version 2, so
that we hopefully detect possible bumps beforehand. After the migration this
is probably only of historical value.

Basic plan
----------

After all preparations are completed, look for a nice weekend at a time
which meets the following criteria:

* no membership fee actions are under way,
* no events are actively managed in the DB,
* no assemblies are taking place.

The following months should fulfill all wishes:

* February,
* September,
* October.

The migration is scheduled for the weekend of 2019-03-01 to 2019-03-03.

Then we tidy up the v1 instance with the following steps:

* resolve all outstanding member dataset changes.

Now we take the v1 instance offline and make an SQL dump. We now feed the
data into the prepared v2 instance (according to the plan outlined below)
and take it online. Now it's time to test if anything major has gone wrong
due to reality being different from the testing environment, if so we take
the v2 instance offline and v1 online again. If not we restrict login in the
v1 instance to privileged accounts and put it online under a new URL, so
that it may be consulted for reference.

Detailed plan by realm
----------------------

This is divided by realm and lists the migration strategy for functionality
and date.  Regarding functionality only changed pieces are mentioned.

Core
^^^^

This incorporates functionality which was duplicated in v1 between cde and
event components.

Functionality
"""""""""""""

* The IDs have a continue unsing the old format to ensure backwards compatability.

Data
""""

Use SQL-script. This should preserve all member IDs. However everybody will
have to reset their password.

CdE
^^^

Functionality
"""""""""""""

* There should be little change here except for some goodies (like profile
  foto).
* The `max_dsa` parameter of Lastschrifts was removed.

Data
""""

Use SQL-script.

Event
^^^^^

Functionality
"""""""""""""

* Registration formular and mail are less flexible. This is offset by gains
  in the questionnaire.
* Housegroups are gone. As are statistics about vegetarians. Use custom
  queries instead.
* The mtime triggers are gone. Replaced by the logging facility.
* Bus stuff is gone. Use fields.

Data
""""

No migration for events organized via DB. Past events are migrated in a
mostly automatic way via SQL script -- the catch being, that they gained a
``tempus`` column for ordering; this is prefilled with something mostly
working, any errors should be easy to fix.

Mailinglists
^^^^^^^^^^^^

Functionality
"""""""""""""

* Only accounts can be subscribed, no (anonymous) email adresses. Solution:
  create accounts.

Data
""""

Use SQL-script.

Assembly
^^^^^^^^

Functionality
"""""""""""""

* Handling of files changed.

Data
""""

Old assemblies are migrated in a summary form. This means they are
essentially preserved, but with only one vote per ballot transporting the
entire result (hence we lose the vote count). And there are no attendance
lists.

Files
^^^^^

Functionality
"""""""""""""

Moved to the assembly realm.

Data
""""

Manual migration, half an hour tops.

I25+
^^^^

Functionality
"""""""""""""

Moved to cde realm.

Data
""""

See cde realm.

Step-by-step plan
-----------------

1. Make everything ready as described above.
2. Prepare the v2 VM (install/configure system packages).
3. Stop the mailserver (alternatively: make mailinglists static, that is
   independent of db).
4. Stop v1 and make an SQL dump.
5. Deploy a change to v1 making only accessible to admins (and invalidate
   all sessions).
6. Restart v1 and move it to https://db1.cde-ev.de.
7. Import dump into v2 (see below).
8. Move v2 to https://db.cde-ev.de and initialize it. Start it in lockdown
   mode (i.e. only admins may log in).
9. Adapt mailinglist scripts to v2 and restart mailserver
10. After a period of inspection by admins the lockdown is lifted or we
    revert back to v1.

Longterm steps:

1. Migrate to new mailinglist software.
2. Migrate all lists to new mailinglist software (obsoleting ezml).
3. Migrate mailinglist server to postfix.

Implementation Details
----------------------

Before everything else ensure, that the trial migration workaround in
modify_password in cdedb/backend/core.py is disabled.

First export the data on the old database server::

    sudo -u postgres pg_dump cdedbxy > /tmp/cdedbv1.sql

Now manually fix the dump for erroneous double quotes and strange line
breaks in course titles. Here is a preliminary list of affected courses::

  _               title                 |                     title
  --------------------------------------+--------------------------------------------------------------------------------------
  Multinationale Akademie Zakopane 2009 | XHTML oder Wie mache ich Websites""
  WinterAkademie 2013                   | Fisch schwimmt, Vogel fliegt - Mensch läuft""
  Multinationale Akademie Latky 2016    | Seminar, Workshops, Mitmachkurs""
  WinterAkademie 2018                   | Verrückte Zauber"würfel""
  Braunschweig 1991 - 2                 | „C'est facile, c'est pas cher et ça peut rapporter gros"\n4"
  Semmering 2012                        | » Von 0 auf 100 in 3,7 Sekunden – oder warum Technik nicht langweilig sein muss«\n11"


Copy the dump to the new database server and import it into a separate
postgres database::

    sed -i -e 's/ TO cdedb[a-z_]*/ TO cdb_old/' cdedbv1.sql
    sed -i -e 's/^REVOKE .*//' cdedbv1.sql
    sudo -u postgres psql -c "CREATE USER cdb_old PASSWORD '987654321098765432109876543210';"
    sudo -u postgres psql -c "CREATE DATABASE cdedbxy WITH OWNER = cdb_old TEMPLATE = template0 ENCODING = 'UTF8';"
    sudo -u postgres psql -c "ALTER DATABASE cdedbxy SET datestyle TO 'ISO, YMD';"
    sudo -u postgres psql -d cdedbxy -f cdedbv1.sql

Now we reset the working copy of the new database::

    sudo -u postgres psql -U postgres -f /cdedb2/cdedb/database/cdedb-users.sql
    sudo -u postgres psql -U postgres -f /cdedb2/cdedb/database/cdedb-db.sql -v cdb_database_name=cdb
    sudo -u postgres psql -U postgres -d cdb -f /cdedb2/cdedb/database/cdedb-tables.sql

We can now execute the migration script (it might be a good idea to turn of
fsync in the postgres configuration before running this)::

    time sudo -u www-data PYTHONPATH="/cdedb2:${PYTHONPATH}" /cdedb2/bin/migrate_execute.py > /tmp/conversion.log

Take note of the output and double-check any suspicious cases. One more
manual step has to be done -- initialize the meta info table::

    sudo -u postgres psql -d cdb -c "INSERT INTO core.meta_info (info) VALUES ('{\"Finanzvorstand_Vorname\": \"\", \"Finanzvorstand_Name\": \"\", \"Finanzvorstand_Adresse_Einzeiler\": \"\", \"Finanzvorstand_Adresse_Zeile2\": \"\", \"Finanzvorstand_Adresse_Zeile3\": \"\", \"Finanzvorstand_Adresse_Zeile4\": \"\", \"Finanzvorstand_Ort\": \"\", \"CdE_Konto_Inhaber\": \"\", \"CdE_Konto_IBAN\": \"\", \"CdE_Konto_BIC\": \"\", \"CdE_Konto_Institut\": \"\", \"banner_before_login\": \"\", \"Vorstand\": \"\", \"banner_after_login\": \"\"}'::jsonb);"

Finally we dispose of the old dataset::

    sudo -u postgres psql -c "DROP DATABASE cdedbxy;"
    sudo -u postgres psql -c "DROP USER cdb_old;"


Manual fixes
------------

Some things still need to be mixed manually after migration. this includes:

* Limit `cde-all` and `cde-info` lists to members only.
* Add the quick-hack for downloadable files.
* Touch `/DBVM` to mark the live instance.
