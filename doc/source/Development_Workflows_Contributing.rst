Contributing
============

To get access to the repository, please have been logged in once via SSO
`in ForgeJo <https://tracker.cde-ev.de/gitea/user/login>`_
and contact us at cdedb ät lists.cde-ev.de.

.. note::
    Wir unterstützen sowohl Deutsch als auch Englisch als Konversationssprachen.

Issues
------

Questions and proposals should be filed as
`issues <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues>`_.
Here you can also pick stuff you are interested to implement (although for many
of them there may be nontrivial reasons why they haven't been so far).

Our Issues are labelled by priority, area in our code they primarily affect
and other useful information, such as pending discussion or specification
before implementation can start.

The ``tag/easy`` label is also an indicator for good first issues.

Pull Requests
-------------

Contributions should mainly be done by opening
`pull requests <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/pulls>`_
in ForgeJo.

We have an automated test suite that checks all pull requests. Please write a
new test or extend an existing test covering the changed code. For further
information take a look into :doc:`Development_Workflows_Test_Suite`.

If your contribution requires any additional dependencies or actions to be
taken upon being deployed (such as creating a new database table, column,
migrating some data, etc.), add a file in the ``related/deploy`` folder,
containing either a list of instructions or even better a list of commands,
that can directly be executed to achieve this. For examples, take a look in
the ``related/deploy`` folder and/or the ``cdedb/database/evolutions`` folder
and the doc page for evolution scripts (:doc:`Development_Workflows_Scripts`).
If there are changes in the python dependencies all you need to do is adjust
the ``pyproject.toml`` accordingly. If there are changes to other dependencies
you need to adjust the installation script(s) in ``related/auto-build/files``
and Dockerfile(s) ``related/docker`` in addition to the deploy notes/script.
