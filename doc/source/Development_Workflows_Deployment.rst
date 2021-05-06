Deployment
==========

.. todo:: Mention and cross-reference :doc:`Development_Workflows_Scripts`.

The stable branch tracks the revision deployed to the server. Use the
following steps to deploy a new revision.

* Locally set the stable branch to the desired revision::

    git checkout stable
    git merge master # or another branch or an explicit commit

* Run the push-stable.sh script. If any new commits with deployment
  relevance are present (marked by a line starting with "Deploy:" in the
  commit message) they will be displayed and there will be the option to
  abort the push. If no such commits are present the push simply
  proceeds. The script accepts the parameter "-d" which enables the dry-run
  mode where no actual push happens.
  The script also automatically creates a new release tag marked as "release/YYYY-MM-DD"
  and manually pushes to the "mirror" remote if it is set up.

  ::

     ./bin/push-stable.sh

* Log into the server. If no commits with deployment relevance exist, simply
  execute the cdedb-update.sh script::

    ssh cde-db2 # replace with your alias from your ssh config
    sudo cdedb-update.sh

  If commits with deployment relevance exist, the call to the script needs
  to be replaced by the commands inside the script interspersed with the
  server adjustments.

  .. note:: Database evolutions should be applied via the following
            invocation::

                sudo -u cdb psql -U cdb -d cdb -f evolution.sql
