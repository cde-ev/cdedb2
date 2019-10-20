Readme
======

This section provides practical knowledge for development.

Coding Guidelines
-----------------

Here is a list of best practices to follow, so the code stays nice.

* Use only spaces for indentation.
* The database access is encapsulated as follows::

    with connection as conn:
        with conn.cursor as cur():
            ...

  This guarantees, that no transaction are left dangling and in case of
  error does a rollback. If these contexts are nested (e.g. through function
  calls) use the :py:class:`cdedb.database.connection.Atomizer`.
* All functions with an ``@access`` decorator may only use the
  session-specific database connections/resources. All uses of elevated
  privileges must be encapsulated into their own functions.
* Always use named constants (mostly from cdedb.database.constants) for
  numeric constants. Generally avoid hard-coded values.
* Document stuff, but avoid redundant spam -- less is sometimes
  more. Especially avoid annotating 'bar(foo)' with "bars a foo" (think of
  it like playing Tabu).
* Exactly those HTTP-requests which change data must be POST-requests. Upon
  a POST a redirect should happen so that refresh (F5) works without
  surprises.
* The HTML should degrade nicely if Javascript is not available.
* No numeric id (like persona_id) may be zero.
* If possible test core.personas.status always against lists like
  cdedb.database.constants.SEARCHMEMBER_STATI and not against the direct
  values like cdedb.database.constants.PersonaStati.searchmember.
* As general pattern: return tuple ``(bool, str)`` where the bool signals
  success, and the str is the either error message or return value
* The test-suite should visit all functionality at least once.
* If a change requires manual intervention on the server note this in the
  commit message on a line starting with ``Deploy:``.

.. _sample-data:

Sample Data
-----------

There is a default data set for the development it contains some users
(according to the table below).

  ======================= ========== ================================================ =========
   User                    Password   Notes                                            ID
  ======================= ========== ================================================ =========
   anton@example.cde       secret     admin with all privileges                        DB-1-9
   berta@example.cde       secret     canonical example member, moderator of lists     DB-2-7
   charly@example.cde      secret     member, but not searchable                       DB-3-5
   daniel@example.cde      secret     former member (but not disabled)                 DB-4-3
   emilia@example.cde      secret     event user                                       DB-5-1
   ferdinand@example.cde   secret     admin in all realms, but not globally            DB-6-X
   garcia@example.cde      secret     orga of an event                                 DB-7-8
   hades                   secret     archived member                                  DB-8-6
   inga@example.cde        secret     minor member                                     DB-9-4
   janis@example.cde       secret     mailinglist user                                 DB-10-8
   kalif@example.cde       secret     assembly user                                    DB-11-6
   lisa                    secret     member with whacked data                         DB-12-4
   martin@example.cde      secret     second meta admin to confirm privilege changes   DB-13-2
   olaf@example.cde        secret     a disabled user (and member and CdE admin)       DB-15-9
  ======================= ========== ================================================ =========

Random Thoughts
---------------

This is a bit of a mess, but better to note something down here, than forget
it right away.

* Authentication between backends is done via the AuthShim class.
* Validation should mostly be done by trying and catching.
* NULL vs. empty string should make no difference in the database (i.e. both
  cases should be treated equally). Nevertheless empty strings should be
  killed in python code -- but all Nones are converted to empty strings just
  before being handed to the templates.
* Use encode_parameter/decode_parameter to authenticate actions. This
  removes the need for storing challenges in the database.
* Strings to internationalize should have periods at the end where
  applicable (so all error messages should have them).
* Behaviour should be defined once.
* Values should be configurable and not be hard coded
* Use tuples instead of lists where feasible.
* Unittests where sensible, high level testing otherwise.
* Use fail2ban for preventing brute force.
* All time stamps must have a time zone associated to them. For everything
  used internally this time zone has to be UTC.
* If a check for membership is done (``if foo in bar``) use a ``set`` as
  data structure if possible, this does not apply for iterating (``for foo
  in bar``).
* Non-specific parameters should be given as keyword arguments. That is
  values like ``True``, ``False``, ``None`` where it's pretty hard to guess
  what they do. Antipattern would be a call like ``do_something(True, False,
  None, True)``.
* HTML pages with a big form for data entry should have no links which
  redirect and cause the entered data to be lost.
* Email addresses are lower-cased. (This has to be taken into account during
  migration!)
* We should always provide feedback to the user if an action was
  successful. Basically this means, that in the frontend every POST action
  should cause a notification.
* Most templates should be rendered at exactly one point. That means that if
  other methods which want to redisplay the content need to call this
  point. Hence the rendering point must be able to cope with user input (as
  in data which failed to validate, but should not be discarded).
* Generally use a line length limit of 80 columns, except for templates,
  where 120 columns seems appropriate.
* If a function is documented to return a default return code this means,
  that it returns a positive number on success, zero if there was an error
  and a negative number if the change is waiting for further actions
  (i.e. review). Especially many functions return the number of affected
  rows in the database, thus if no rows are affected an error is signalled.
* Backend functions to expunge data are separated into two classes. First
  those named remove_foo are always feasible. Second those name delete_foo
  are dependent on the foo not being referenced anywhere. They may provide a
  cascade parameter which allows to automatically remove all references.
* The file ``/DBVM`` is used to mark the live server instance. There are
  some sanity checks to prevent a big catastrophe.
