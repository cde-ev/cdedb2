Contributing
============

Contributions should mainly be done by opening pull requests in Gitea. To get
access to the repository, please
`click yourself an account <https://tracker.cde-ev.de/gitea/user/sign_up>`_
and contact us at cdedb ät lists.cde-ev.de.

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
