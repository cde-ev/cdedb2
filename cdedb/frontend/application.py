#!/usr/bin/env python3

"""The WSGI-application to tie it all together."""

import json
import os
import pathlib
import types
from typing import Set

import jinja2
import psycopg2.extensions
import werkzeug
import werkzeug.exceptions
import werkzeug.routing
import werkzeug.wrappers

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.session import SessionBackend
from cdedb.common import (
    ADMIN_VIEWS_COOKIE_NAME, IGNORE_WARNINGS_NAME, CdEDBObject, PathLike,
    QuotaException, RequestState, User, glue, make_proxy, make_root_logger, n_, now,
    roles_to_db_role,
)
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.common import (
    JINJA_FILTERS, AbstractFrontend, BaseApp, FrontendEndpoint, Response,
    construct_redirect, datetime_filter, docurl, sanitize_None, setup_translations,
    staticurl,
)
from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.frontend.paths import CDEDB_PATHS


class Application(BaseApp):
    """This does state creation upon every request and then hands it on to the
    appropriate frontend."""

    def __init__(self, configpath: PathLike = None) -> None:
        super().__init__(configpath)
        self.coreproxy = make_proxy(CoreBackend(configpath))
        self.eventproxy = make_proxy(EventBackend(configpath))
        self.mlproxy = make_proxy(MlBackend(configpath))
        self.assemblyproxy = make_proxy(AssemblyBackend(configpath))
        # do not use a make_proxy since the only usage here is before the
        # RequestState exists
        self.sessionproxy = SessionBackend(configpath)
        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)
        # Set up a logger for all Worker instances.
        make_root_logger(
            "cdedb.frontend.worker", self.conf["WORKER_LOG"],
            self.conf["LOG_LEVEL"], syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
            secrets, self.conf["DB_PORT"])
        # Construct a reduced Jinja environment for rendering error pages.
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(self.conf["REPOSITORY_PATH"] / "cdedb/frontend/templates")),
            extensions=['jinja2.ext.i18n', 'jinja2.ext.do',
                        'jinja2.ext.loopcontrols'],
            finalize=sanitize_None, autoescape=True,
            auto_reload=self.conf["CDEDB_DEV"])
        self.jinja_env.globals.update({
            'now': now,
            'staticurl': staticurl,
            'docurl': docurl,
            'glue': glue,
        })
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.jinja_env.filters.update({'datetime': datetime_filter})
        self.jinja_env.policies['ext.i18n.trimmed'] = True  # type: ignore
        self.translations = setup_translations(self.conf)
        if pathlib.Path("/PRODUCTIONVM").is_file():  # pragma: no cover
            # Sanity checks for the live instance
            if self.conf["CDEDB_DEV"] or self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                raise RuntimeError(
                    n_("Refusing to start in debug/offline mode."))

    def make_error_page(self, error: werkzeug.exceptions.HTTPException,
                        request: werkzeug.wrappers.Request, user: User,
                        message: str = None) -> Response:
        """Helper to format an error page.

        This is similar to
        :py:meth:`cdedb.frontend.common.AbstractFrontend.fill_template`,
        but creates a Response instead of only a string. It also has a more
        minimalistic setup to work, even when normal application startup fails.

        :param message: An additional help string. If given, the default help
                     string for each HTTP code (below the error description) is
                     prepended by this string (or its translation).
        """
        # noinspection PyBroadException
        try:
            # We don't like werkzeug's default 404 description:
            if isinstance(error, werkzeug.exceptions.NotFound) \
                    and (error.description
                         is werkzeug.exceptions.NotFound.description):
                error.description = None  # type: ignore

            urls = self.urlmap.bind_to_environ(request.environ)

            def _cdedblink(endpoint: str, params: CdEDBObject = None) -> str:
                return urls.build(endpoint, params or {})

            begin = now()
            lang = self.get_locale(request)
            data = {
                'ambience': {},
                'cdedblink': _cdedblink,
                'errors': {},
                'generation_time': lambda: (now() - begin),
                'gettext': self.translations[lang].gettext,
                'ngettext': self.translations[lang].ngettext,
                'lang': lang,
                'notifications': tuple(),
                'user': user,
                'values': {},
                'error': error,
                'help': message,
            }
            t = self.jinja_env.get_template(str(pathlib.Path("web",
                                                             "error.tmpl")))
            html = t.render(**data)
            response = Response(html, mimetype='text/html', status=error.code)
            response.headers.add('X-Generation-Time', str(now() - begin))
            return response
        except Exception:
            self.logger.exception("Exception while rendering error page")
            return Response("HTTP {}: {}\n{}".format(error.code, error.name,
                                                     error.description),
                            status=error.code)

    @werkzeug.wrappers.Request.application
    def __call__(self, request: werkzeug.wrappers.Request) -> werkzeug.Response:
        # note time for performance measurement
        begin = now()
        user = User()
        try:
            sessionkey = request.cookies.get("sessionkey")
            apitoken = request.headers.get("X-CdEDB-API-Token")
            urls = self.urlmap.bind_to_environ(request.environ)

            if apitoken:
                sessionkey = None
                user = self.sessionproxy.lookuptoken(apitoken, request.remote_addr)
                # Error early to make debugging easier.
                if 'droid' not in user.roles:
                    raise werkzeug.exceptions.Forbidden(
                        "API token invalid.")
            else:
                user = self.sessionproxy.lookupsession(sessionkey, request.remote_addr)

                # Check for timed out / invalid sessionkey
                if sessionkey and not user.persona_id:
                    params = {
                        'wants': self.encode_parameter(
                            "core/index", "wants", request.url,
                            user.persona_id,
                            timeout=self.conf[
                                "UNCRITICAL_PARAMETER_TIMEOUT"])
                    }
                    ret = construct_redirect(
                        request, urls.build("core/index", params))
                    ret.delete_cookie("sessionkey")
                    # Having to mock a request state here is kind of ugly
                    # and depends on the implementation details of
                    # `encode_notification`. However all alternatives
                    # look even uglier.
                    fake_rs = types.SimpleNamespace()
                    fake_rs.user = user
                    notifications = json.dumps([
                        self.encode_notification(fake_rs,  # type: ignore
                                                 "error", n_("Session expired."))])
                    ret.set_cookie("displaynote", notifications)
                    return ret

            endpoint, args = urls.match()

            lang = self.get_locale(request)
            rs = RequestState(
                sessionkey=sessionkey, apitoken=apitoken, user=user,
                request=request, notifications=[], mapadapter=urls,
                requestargs=args, errors=[], values=None, begin=begin,
                lang=lang, translations=self.translations,
            )
            rs.values.update(args)
            component, action = endpoint.split('/')
            raw_notifications = rs.request.cookies.get("displaynote")
            if raw_notifications:
                # noinspection PyBroadException
                try:
                    notifications = json.loads(raw_notifications)
                    for note in notifications:
                        ntype, nmessage, nparams = (
                            self.decode_notification(rs, note))
                        if ntype:
                            assert nmessage is not None
                            assert nparams is not None
                            rs.notify(ntype, nmessage, nparams)
                        else:
                            self.logger.info(f"Invalid notification '{note}'")
                except Exception:
                    # Do nothing if we fail to handle a notification,
                    # they can be manipulated by the client side, so
                    # we can not assume anything.
                    self.logger.debug(f"Invalid raw notification '{raw_notifications}'")
            frontend: AbstractFrontend = getattr(self, component)
            handler: FrontendEndpoint = getattr(frontend, action)
            if request.method not in handler.modi:
                raise werkzeug.exceptions.MethodNotAllowed(
                    handler.modi,
                    "Unsupported request method {}.".format(
                        request.method))

            # Check anti CSRF token (if required by the endpoint)
            if handler.anti_csrf.check and 'droid' not in user.roles:
                error = frontend.check_anti_csrf(rs, action, handler.anti_csrf.name,
                                                 handler.anti_csrf.payload)
                if error is not None:
                    rs.csrf_alert = True
                    rs.extend_validation_errors(
                        ((handler.anti_csrf.name, ValueError(error)),))
                    rs.notify('error', error)

            # Decide whether the user wants to ignore ValidationWarnings
            rs.ignore_warnings = rs.request.values.get(IGNORE_WARNINGS_NAME, False)

            # Store database connection as private attribute.
            # It will be made accessible for the backends by the make_proxy.
            rs._conn = self.connpool[roles_to_db_role(user.roles)]

            # Insert orga and moderator status context
            orga: Set[int] = set()
            if "event" in user.roles:
                assert user.persona_id is not None
                orga = self.eventproxy.orga_info(rs, user.persona_id)
            moderator: Set[int] = set()
            if "ml" in user.roles:
                assert user.persona_id is not None
                moderator = self.mlproxy.moderator_info(
                    rs, user.persona_id)
            presider: Set[int] = set()
            if "assembly" in user.roles:
                assert user.persona_id is not None
                presider = self.assemblyproxy.presider_info(
                    rs, user.persona_id)
            user.orga = orga
            user.moderator = moderator
            user.presider = presider
            user.init_admin_views_from_cookie(
                request.cookies.get(ADMIN_VIEWS_COOKIE_NAME, ''))

            try:
                ret = handler(rs, **args)
                if rs.validation_appraised is False:
                    self.logger.error(
                        f"User {rs.user.persona_id} has evaded input validation"
                        f" with errors {rs.retrieve_validation_errors()}")
                    raise RuntimeError(f"Input validation forgotten: {handler}")
                return ret
            except QuotaException as e:
                # Handle this earlier, since it needs database access.
                # Beware that this means that quota violations will only be logged if
                # they happen through the frontend.
                self.coreproxy.log_quota_violation(rs)
                return self.make_error_page(
                    e, request, user,
                    n_("You reached the internal limit for user profile views. "
                       "This is a privacy feature to prevent users from cloning "
                       "the address database. Unfortunatetly, this may also yield "
                       "some false positive restrictions. Your limit will be "
                       "reset in the next days."))
            finally:
                # noinspection PyProtectedMember
                rs._conn.commit()
                # noinspection PyProtectedMember
                rs._conn.close()
        except werkzeug.routing.RequestRedirect as e:
            return e.get_response(request.environ)
        except werkzeug.exceptions.HTTPException as e:
            return self.make_error_page(e, request, user)
        except psycopg2.extensions.TransactionRollbackError as e:
            # Serialization error
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(str(e.args)),
                request, user,
                n_("A modification to the database could not be executed due "
                   "to simultaneous access. Please reload the page to try "
                   "again."))
        except Exception as e:
            self.logger.error(f">>>\n>>>\n>>>\n>>> Exception while serving"
                              f" {request.url} <<<\n<<<\n<<<\n<<<")
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")

            self.cgitb_log()

            # Raise exceptions when in TEST environment to let the test runner
            # catch them.
            if (
                self.conf["CDEDB_TEST"]
                or (self.conf["CDEDB_DEV"] and os.environ.get("INTERACTIVE_DEBUGGER"))
            ):
                raise

            # debug output if applicable
            if self.conf["CDEDB_DEV"]:
                return self.cgitb_html()

            # generic errors
            # TODO add original_error after upgrading to werkzeug 1.0
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(repr(e)), request, user)

    def get_locale(self, request: werkzeug.wrappers.Request) -> str:
        """
        Extract a locale from the request headers (cookie and/or
        Accept-Language)

        :return: Language code of the requested locale
        """
        if request.cookies.get('locale') in self.conf["I18N_LANGUAGES"]:
            return request.cookies['locale']

        return request.accept_languages.best_match(
            self.conf["I18N_LANGUAGES"], default="de")
