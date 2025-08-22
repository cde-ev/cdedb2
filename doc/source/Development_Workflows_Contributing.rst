Contributing
============

Contributions should mainly be done by opening pull requests in Gitea. To get
access to the repository, please
`click yourself an account <https://tracker.cde-ev.de/gitea/user/sign_up>`_
and contact us at cdedb ät lists.cde-ev.de.
Contributions should mainly be done by opening
`pull requests <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/pulls>`_
in ForgeJo. Questions and proposals should be filed as
`issues <https://tracker.cde-ev.de/gitea/cdedb/cdedb2/issues>`_, where
you can also pick ones you are interested to implement (although for many
of them there may be nontrivial reasons why the haven't been so far).

.. note::
    Wir unterstützen sowohl Deutsch als auch Englisch als Konversationssprachen.

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
