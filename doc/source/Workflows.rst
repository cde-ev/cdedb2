Workflows
=========

This page aims to provide descriptions on how to do things.

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


Scripts
-------

For doing modifications to the live instance and it's data we provide a
collection of functionality in :ref:`autodoc-script-module`.

A production script should have 3 sections for setup (imports, etc.),
configuration and doing the actual work.

Setting up a script
^^^^^^^^^^^^^^^^^^^

.. highlight:: python

.. note::
   The following code snippets are basic examples, in an actual script
   you might need completely different imports or even none at all.

The first thing that should be done when setting up a script is ensuring that
the `cdedb` modules are accessible: ::

    import sys
    sys.path.insert(0, "/cdedb2")

After that should come the rest of the required imports and other
prerequisites like setting up backends using ``make_backend``. ::

    from pprint import pprint
    from cdedb.script import setup, make_backend, Script
    import cdedb.database.constants as const
    from cdedb.common import SubscriptionError, SubscriptionInfo

    ml = make_backend("ml")

Configuring a script
^^^^^^^^^^^^^^^^^^^^

In this section should come the bits that might need to be adjusted when
actually running the script against the production environment. ::

    rs = setup(persona_id=-1, dbuser="cdb_admin",
        dbpassword="9876543210abcdefghijklmnopqrst")
    DRY_RUN = True
    SHOW_ERROR_DETAILS = True

The ``persona_id``, ``dbuser`` and ``dbpassword`` arguments will have to be
adjusted later. You should also provide a flag for running the script in dry
run mode, i.e. without actually commiting any changes made.

``setup`` returns a ``RequestState`` factory, which you can call with a
persona id, to get a fake ``RequestState`` for that user. If called without
an argument this will default to the ``persona_id`` passed to ``setup``.
If you do not need different ``RequestState``s, you might want to call this
once to avoid mistakes down the line. ::

    rs = rs()

Doing the actual work
^^^^^^^^^^^^^^^^^^^^^

Before starting the actual script, you might want to specify some constants or
variables to (re)use later. Then you should do the actual work inside a
`Script` context manager, providing the `RequestState` and the `DRY_RUN` flag.

At the end of your work you should provide some feedback about whether or not
the changes were successful and maybe a recap of the changes. ::

    mailinglist_id = 1
    ml_data = {...}
    relevant_states = {const.SubscriptionStates.implicit}
    successes = set()
    errors = {}
    infos = {}
    with Script(rs(), dry_run=DRY_RUN):
        subscribers = ml.get_subscription_states(
            rs(), mailinglist_id, relevant_states)
        new_ml_id = ml.create_malinglist(rs(), ml_data)
        for persona_id in subscribers:
            try:
                code = ml.do_subscription_action(
                    rs(persona_id), const.SubscriptionActions.subscribe,
                    new_ml_id)
            except SubscriptionInfo as e:
                infos[persona_id] = e
            except SubscriptionError as e:
                errors[persona_id] = e
            else:
                if code:
                    successes.add(persona_id)
                else:
                    errors[persona_id] = None

        assert len(subscribers) = len(infos) + len(errors) + len(successes)
        print(f"{len(successes)} of {len(subscribers)} successfully added.")
        if errors or infos:
            print(f"Encountered {len(infos)} infos and {len(errors)} errors.")
            if SHOW_ERROR_DETAILS:
                print("Infos:")
                pprint(infos)
                print("Errors:")
                pprint(errors)

The `Script` context manager is a subclass of `cdedb.connection.Atomizer`. If
the `dry_run` parameter is True or an Exception occurred all changes will
be rolled back, otherwise they will be committed.

Make sure the output gives a good sense of whether everything went well so
the deployer can then decide whether to run the script in not-dry_run mode.