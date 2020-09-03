Workflows
=========

This page aims to provide descriptions on how to do things.

.. todo:: Add information about PR&Issues (short with link to gitea), Test-Suite, Input validation,
          Autobuild ...

.. toctree::
   :maxdepth: 1

   Development_Workflows_Scripts
   Development_Workflows_Test_Suite

Contributing
------------

Contributions should mainly be done by opening pull requests in Gitea.

We currently do not have any continuous integration so please run the tests
manually by executing ``bin/check.sh``.


Internationalization
--------------------

We use GNU gettext in combination with the python babel library for
internationalization.

* Translatable strings have to be marked. In python you can do this in two ways:
    * using ``n_()``. This only marks the string for extraction into internationalization files,
      but does not translate it.
    * using ``rs.gettext()``. This marks the string, but also replaces it with the translation.

* You can also translate strings in templates, by wrapping them in either of the following. Both of these way replace the marked string with the appropriate translation.
    * the ``rs.gettext()`` function or it' common alias ``_()`` where appropriate.
    * the ``{% trans %}`` / ``{% endtrans %}`` environment.

* Marked strings are extracted via the ``make i18n-refresh`` command.

* The extracted strings need to be translated in the ``*.po`` files in the ``i18n``
  directory for each language.

* Ultimately pybabel needs to be compiled(``make i18n-compile``) and the apache restarted. This can both be done via one command: ``make reload``.

Be aware that messages that need to be translated, but do not appear explicitly in the code,
are listed in ``i18n_additional.py``. This applies especially human-readable descriptions of enum members.

Deployment
----------

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

  ::

     ./bin/push-stable.sh

* Log into the server. If no commits with deployment relevance exist, simply
  execute the cdedb-update.sh script::

    ssh cde-db2 # replace with your alias from your ssh config
    sudo cdedb-update.sh

  If commits with deployment relevance exist, the call to the script needs
  to be replaced by the commands inside the script interspersed with the
  server adjustments.
