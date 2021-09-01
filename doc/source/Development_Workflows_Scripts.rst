Scripts
=======

For doing modifications to the live instance and it's data we provide a
collection of functionality in ``cdedb/script.py``.

A production script should have 3 sections for setup (imports, etc.),
configuration and doing the actual work.

.. highlight:: python

Setting up a script
-------------------

.. note:: The following code snippets are basic examples, in an actual script
          you might need completely different imports or even none at all.

The first thing that should be done are all the required imports and other
prerequisites like setting up backends using ``make_backend``. ::

    from pprint import pprint
    from cdedb.script import setup, make_backend, Script
    import cdedb.database.constants as const
    from cdedb.common import SubscriptionError, SubscriptionInfo

    ml = make_backend("ml")

Configuring a script
--------------------

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
If you do not need different ``RequestState``\s, you might want to call this
once to avoid mistakes down the line. ::

    rs = rs()

Doing the actual work
---------------------

Before starting the actual script, you might want to specify some constants or
variables to (re)use later. Then you should do the actual work inside a
`Script` context manager, providing the `RequestState` and the `DRY_RUN` flag.

At the end of your work you should provide some feedback about whether or not
the changes were successful and maybe a recap of the changes. ::

    mailinglist_id = 1
    ml_data = {...}
    relevant_states = {const.SubscriptionState.implicit}
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
                    rs(persona_id), const.SubscriptionAction.subscribe,
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
