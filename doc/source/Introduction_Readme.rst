Readme
======

This section provides practical knowlegde for development.

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
  calls) use the :py:class:`cdedb.backend.common.Atomizer`.
* All functions with an ``@access`` decorator may only use the
  session-specific database connections/resources. All uses of elevated
  priviliges must be encapsulated into their own functions.
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
  values like cdedb.database.constants.PersonaStati.search_member.
* As general pattern: return tuple ``(bool, str)`` where the bool signals
  succes, and the str is the either error message or return value
* The test-suite should visit all functionality at least once.

.. _sample-data:

Sample Data
-----------

There is a default data set for the development it contains some users
(according to the table below).

  ======================= ========== =======================================
   User                    Password   Notes
  ======================= ========== =======================================
   anton@example.cde       secret     admin with all privileges
   berta@example.cde       secret     canonical example member
   charly@example.cde      secret     member, but not searchable
   daniel@example.cde      secret     former member
   emilia@example.cde      secret     event user
   ferdinand@example.cde   secret     admin in all realms, but not globally
   garcia@example.cde      secret     orga of an event
  ======================= ========== =======================================

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
* Strings to internationalize should have peridos at the end where
  applicable (so all error messages should have them).
* Behaviour should be defined once.
* Values should be configurable and not be hard coded
* Use tuples instead of lists where feasible.
* unittests were sensible, high level testing otherwise.
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
