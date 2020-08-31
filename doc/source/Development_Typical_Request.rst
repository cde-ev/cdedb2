A typical request
=================

What happens during a typical request? Here is a concrete example.
Hopefully this helps the reader to understand which technologies
are used and how they work together. We will gloss over some details to
arrive at the big picture without too many detours, so be prepared to find
some more intricacies if you look closer.

We will take as an example the request::

  https://db2.cde-ev.de/db/cde/past/event/42/show

It is received by the Apache Web Server on the CdEDB virtual machine running
on the CdE server. Apache then delegates this to the WSGI application
:py:class:`cdedb.frontend.Application` found in
``cdedb/frontend/application.py``. The URL is matched against the available
patterns in ``cdedb/frontend/paths.py`` and the result is the endpoint
``cde/show_past_event``. This contains a realm (``cde``) and an action
(``show_past_event``). Now a :py:class:`cdedb.common.RequestState` object is
constructed; it contains the session information for the current
request. Most notably it contains a :py:class:`cdedb.common.User` object
describing the person doing the request (enabling us for example to check
whether she is authorized to access the URL). This request state object is
handed around encapsulating all state of the session, the other parts of the
python code are state-less (except for the actual SQL-database queries of
course). Another important attribute of the request state object is the
``ambience`` dict, which contains informations about the objects referenced
by id in the URL path. In this case it has an entry ``pevent`` containing
the data of the concluded event with id 42.

We have frontends for each realm, in this case the
:py:class:`cdedb.frontend.cde.CdEFrontend` from
``cdedb/frontend/cde.py``. The method corresponding to the action is called,
that is :py:meth:`cdedb.frontend.cde.CdEFrontend.show_past_event`. This
function is annotated with the :py:func:`cdedb.frontend.common.access`
decorated which in this case triggers a check whether the accessing user has
privileges to view ``cde`` content (this corresponds to the boolean
``is_cde_realm`` in the database entry of the user in the table
``core.personas``, more on this later). Only things annotated with this
decorator are accessible, anything else is private. Now the frontend
function acquires the data to be displayed from the backends. We exemplary
take the call to
:py:meth:`cdedb.backend.pastevent.PastEventBackend.list_past_courses` from
the :py:class:`cdedb.backend.pastevent.PastEventBackend` in
``cdedb/backend/past_event.py``. Note that the backend is present as a proxy
attribute ``pasteventproxy`` in the frontend. The idea is that it should
mostly be possible to replace the direct call of a method of the backend
object by a remote procedure call over the network, with the backend
residing on an entirely different computer. This separation forces a clean
design, but not actually doing network transparency has some
development/maintenance upsides (like allowing atomic transactions with the
:py:class:`cdedb.database.connection.Atomizer` in the frontend).

The backends are responsible for accessing the actual PostgreSQL database,
which stores all state. The
:py:meth:`cdedb.backend.pastevent.PastEventBackend.list_past_courses` method
first does some validation (the frontend function we looked at did not have
any inputs requiring validation, but if you look at a frontend function
receiving inputs via the :py:func:`cdedb.frontend.common.REQUESTdata`
decorator you will see those arguments validated too). In this case the
parameter ``pevent_id`` is checked with the validation function
:py:func:`cdedb.validation._id` from ``cdedb/validation.py`` (which by some
magic is actually accessed as :py:func:`cdedb.validation.affirm_id`). It
proceeds to extract the list of courses of a concluded event from the table
``past_event.courses`` with help of the method
:py:meth:`cdedb.backend.common.AbstractBackend.sql_select`, which
essentially formulates an SQL query and submits it to the PostgreSQL
server. The database layout is stored in
``cdedb/database/cdedb-tables.sql``, where each schema roughly corresponds
to one realm.

Returning to the frontend we skip over most of the logic in
:py:meth:`cdedb.frontend.cde.CdEFrontend.show_past_event` and come to the
final call to :py:meth:`cdedb.frontend.common.AbstractFrontend.render` which
takes all the data from the backend and creates a nice HTML page. For this
it uses the template
``cdedb/frontend/templates/web/de/cde/show_past_event.tmpl``. The templates
utilize the :py:mod:`jinja2` syntax. The finished page is then returned to
the Apache server which delivers it to the user.
