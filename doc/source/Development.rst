Development
===========

.. toctree::
   :maxdepth: 1
   :hidden:

   Development_Environment
   Development_FS-Overview
   Development_Workflows
   Development_Tooling
   Development_Principles
   Development_Typical-Request

Here you can find every information regarding development of the DBv2.
Do you want to participate in active development? Please contact us at
cdedb ät lists.cde-ev.de.

.. todo:: split this up and move it to the right places

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
* The file ``/PRODUCTIONVM`` is used to mark the live server instance. There
  are some sanity checks to prevent a big catastrophe. Similarily
  ``/OFFLINEVM`` is used for offline deployments at events.

