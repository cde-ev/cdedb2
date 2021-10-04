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

The first thing that should be done is importing everything that might me needed.
Lastly you should import the ``Script`` class from the ``cdedb.script`` module.
Usually you wont need to import anything else from there. ::

    from pprint import pprint
    from cdedb.common import SubscriptionError, SubscriptionInfo
    import cdedb.database.constants as const

    from cdedb.script import Script

Configuring a script
--------------------

In this section should come everything that you might want to configure about the
script. Note that ``persona_id``, ``dry_run`` and ``configpath`` can be set
via environment variables if left out. ::

    script = Script(dbuser="cdb_admin", configpath="/etc/cdedb-application-config.py")
    SHOW_ERROR_DETAILS = True

The created ``Script`` object has a ``.rs()`` method, that will return a
``RequestState`` for the default user. The return is cached, to there is no actual
difference between calling ``script.rs()`` every time or storing it into a local
variable other than ease of use. The method optionally takes a ``persona_id`` parameter,
which when given will create a new request state for that user instead of the default
user. Note that the resulting request state will always have all privileges regardless
of the persona id. ::

    rs = script.rs()
    user_rs = script.rs(persona_id=42)

The ``Script`` object also provides a ``make_backend`` method, that will create a new
instance of the specified backend. If called using ``proxy=False`` you will get a raw
backend, which allows you to access non-published methods like ``query_exec``. Otherwise
you will get a proxy wrapping the created backend. ::

    mlproxy = script.make_backend("ml")
    core = script.make_backend("core", proxy=False)



Doing the actual work
---------------------

Before starting the actual script, you might want to specify some constants or
variables to (re)use later. Then you should do the actual work inside the context of a
transaction. The ``Script`` class can be used as a context manager to achieve this.
If the ``Script`` was created with ``dry_run=True`` (the default), all changes made
within this transaction will be rolled back at the end.
At the end of your work you should provide some feedback about whether or not
the changes were successful and maybe a recap of the changes, so that the deployed can
decice whether or not to run the script in not-dry_run mode. ::

    mailinglist_id = 1
    ml_data = {...}
    relevant_states = {const.SubscriptionState.implicit}
    successes = set()
    errors = {}
    infos = {}
    with script:
        subscribers = ml.get_subscription_states(
            script.rs(), mailinglist_id, relevant_states)
        new_ml_id = ml.create_malinglist(script.rs(), ml_data)
        for persona_id in subscribers:
            try:
                code = ml.do_subscription_action(
                    script.rs(persona_id), const.SubscriptionAction.subscribe,
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

Using the ``Script`` as a context manager gives you a convenience wrapper around the
``ScriptAtomizer`` class, which is a subclass of `cdedb.connection.Atomizer`.


Setting environment variables.
------------------------------

When running the script, most parameters can be set via environment variables. Note
that this needs to happen after switching the executing user to ``www-data``. ::

    sudo -u www-data SCRIPT_PERSONA_ID=1 SCRIPT_DRY_RUN="" SCRIPT_CONFIGPATH="/etc/cdedb-application-config.py" python3 bin/some_script.py

Note that in order to deactivate dry run mode, the ``SCRIPT_DRY_RUN`` environment
variable needs to be falsy, so the only viable option is setting it to an empty string.
