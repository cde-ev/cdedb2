Testing
=======

To ensure our code keeps working properly, all code written should be tested.
Due to practicality reasons, we restrict ourselves to automatically testing
the logic (Python, Jinja, JavaScript) and test the design (CSS) manually.

For backend and other basic testing, we are just calling the functions we want
to test directly, while for frontend testing, we are using webtest to emulate
a webserver. Here, we use German as default locale, so be wary for test
failures when touching translations. Additionally playwright is used for
testing with real browser engines which allows checking the JavaScript.

How to write a good integration test
------------------------------------
This aims at providing a brief list of points one should take into account
while writing integration tests (often incorrectly called unit tests).

* Make creative use of the different ``unittest.TestCase.assert*`` functions.
  In contrast, plain ``assert`` statements should only be used for mypy to
  have failure reporting work as intended.
* Failure cases are important. Always test that validation errors are handled
  correctly, especially in the frontend.
* Test with the least privileged user possible. If there is reason to believe
  code might behave differently for other users, add them as well, otherwise
  omit them to save runtime.
  Since logging in and out during a test is possible, it is possible to switch
  privileges during a test. This is e.g. useful to test logging.
* If you write a regression test, always check that your test actually fails
  if the fix is not in place. Otherwise, it is worthless.
* Join related tests together, if possible. For example, go through the whole
  lifecycle of simple entities. This reduces the total runtime of the tests.
* Avoid raw IDs. They are hard to recognize. Use terms like
  ``USER_DICT["inga"]["id"]`` or ``const.EventLogCodes.event_changed`` instead.
  The ``self.user_in`` function simplifies this for users since it accepts full
  user objects (``USER_DICT["inga"]``), user ids (``9``) or names (``"inga"``).
  Beware that for filling in a webtest form field with an enum, you need to use
  the ``.value`` attribute.
* Do not imitate the existing ``test_log`` tests. Those represent an
  anti-pattern. Instead, test the presence of log entries together with their
  generation. For backend tests, copying ``pprint`` output is helpful
  to compile an expectation. For frontend tests, it usually suffices to check
  that ``id``, ``code`` and potentially ``change_note`` are a match.
* The ``@prepsql`` decorator may be used to perform some sql queries to the
  database before the actual test. Needs to be speficied after ``@as_users``
  to work correctly.
* Remember to add the ``@storage`` decorator when accessing storage.
  Otherwise, your test will fail.

If you require as much time to write a unit test as you needed to write the
original functionality, you are doing it right.

For frontend tests, additionally take into account the following points:

* Get familiar with the ``FrontendTest`` class inside ``tests/common.py``.
  There, many helpers are defined which simplify common testing tasks.
* If you check whether things are present, be precise. Specify as precise as
  possible where a string should be, and make it as long as possible.
* If you check whether things are **not** present, be vague. Do not specify
  where a string should be, and make it as short as possible.
* It is possible to access the backend directly inside frontend tests, but this
  should usually be avoided. However, it is acceptable if you really want to
  check if data has been written to the database correctly if there is no
  simple frontend way to do so.
* If you would like to test something, but you do not know how, it is usually
  possible. Look into ``tests/common.py``, into webtest internals, or ask
  people. Writing additional helpers can be quite tedious, but is usually
  worth it in the long run. ``assertNoLink`` and ``assertValidationError``
  are some examples.

Coverage
--------
In general, we aim at 100 % test coverage for our Python code. This means that
ideally, not only every statement, but also every control structure branch
should be tested.

However, not every statement should in fact be tested. As a rule of thumb:
If something is expected to potentially happen in practice, it should be tested,
if strucuturally possible. (We will not start messing with subprocess calls
manipulating the system to test some failsaves, for example.)

This means the following should not be covered:

* Logical consistency checks, usually in the backend, either due to
  programmatic logic or due to database consistency.
* Validation as ``Optional[str]`` in frontend endpoints – it is impossible
  to fail this as an incoming request.

On the other hand, just because something is hard or annoying to test, or
requiring mocking, it would not warrant an exception. Nevertheless, it is
always a trade-off between cost and use: Just because you can imagine a wild
way to anyway perform a test, this does not mean you should do it.

Regarding statement coverage, we are at about 90 % and aim to increase this
amount in the future. Starting in the end of 2021, we have a mid-term goal to
significantly increase this number. Achieving at least 95 % should be
possible without reaching vanishing benefit.

To run coverage checks, take a look at the :ref:`coverage`.
