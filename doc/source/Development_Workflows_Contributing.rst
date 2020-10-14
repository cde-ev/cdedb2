Contributing
============

Contributions should mainly be done by opening pull requests in Gitea. To get
access to the repository, please
`click yourself an account <https://tracker.cde-ev.de/gitea/user/sign_up>`_
and contact us at cdedb ät lists.cde-ev.de.

We currently do not have any continuous integration. However, its is good style
to write new or exstent existing tests to cover the new introduced code.
Please take a look into :doc:`Development_Workflows_Test_Suite`.

If you add new dependencies or change something inside the database, left an
*Deployment Hint*: Simply add a commit starting with ``Deploy:`` and describe
what to change in the live instance.
It is good style to write an evolution script if you change the database schema.
Please take a look into :doc:`Development_Workflows_Scripts` and mention the
script name in the *Deployment Hint*.
