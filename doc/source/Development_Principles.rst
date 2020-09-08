Programming Principles
======================

.. todo:: Add guidelines for variable naming conventions, code style
          (sql, python, jinja2, javascript), code encapsulation

Coding Guidelines
-----------------

.. todo:: split up in sql, python, jinja, javascript

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
* Use type checking with mypy where feasible.
* Only use asserts for static type checking purposes (i.e. making mypy aware
  of invariants we already know to be true). Note that asserts may be
  disabled at runtime.
