Deployment
==========

The stable branch tracks the revision deployed to the server. Use the
following steps to deploy a new revision.

* Locally set the stable branch to the desired revision::

    git fetch
    git checkout stable
    git merge origin/master # or another branch or an explicit commit

* Run the ``bin/push-stable.sh`` script.
  If any new files have been added to the ``related/deploy`` folder, their names will
  be displayed and you will be prompted whether to proceed with the push.
  (The same goes for commit messages containing a line starting with "Deploy:".)
  The script also accepts the parameter "-d" which enables the dry-run
  mode where no actual push happens.
  The script also automatically creates a new release tag marked as "release/YYYY-MM-DD"
  and pushes to the stable branch of the ``mirror`` remote if it is set up.

  ::

     ./bin/push-stable.sh

* Log into the server. If no commits with deployment relevance exist, simply
  execute the cdedb-update.sh script::

    ssh cde-db2 # replace with your alias from your ssh config
    sudo cdedb-update.sh

  Note that to connect to the database in interactive mode, or to run a script,
  you need to enter interactive sudo mode first to be able to emulate other users.

  If commits with deployment relevance exist, the necessary alterations should be
  applied after running the update script once. Afterwards you should restart the
  apache again, using the `cdedb-restart.sh` script::

    ssh cde-db2
    sudo -i
    cdedb-update.sh
    sudo -u cdb psql -U cdb -d cdb -f evolution.sql
    sudo -u www-cde -g www-data SCRIPT_CONFIGPATH="/etc/cdedb/config.py" SCRIPT_PERSONA_ID=X SCRIPT_DRY_RUN="" python3 bin/some_script.py
    cdedb-restart.sh

* Send update information to the Aktivenforum. These should include a short summary of
  the relevant changes, including information for whom this is most relevant (i.e.
  "@Orgas" for most changes to the event realm), aswell as the shortlog of all the
  changes. The update information should include everything since the last update
  information, which might not be the same as everything since the last release.

  ::

    git shortlog release/X..stable
