#!/usr/bin/env python3

"""The WSGI-application to tie it all together."""

import cgitb
import gettext
import json
import pathlib
import sys
import types

import jinja2
import psycopg2.extensions
import werkzeug
import werkzeug.routing
import werkzeug.exceptions
import werkzeug.wrappers

from typing import (
    Dict, Callable, Optional, Set, Any
)

from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.common import (
    n_, glue, QuotaException, now, roles_to_db_role, RequestState, User,
    ANTI_CSRF_TOKEN_NAME, ANTI_CSRF_TOKEN_PAYLOAD, make_proxy,
    ADMIN_VIEWS_COOKIE_NAME, make_root_logger, PathLike
)
from cdedb.frontend.common import (
    BaseApp, construct_redirect, Response, sanitize_None, staticurl,
    docurl, JINJA_FILTERS)
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.paths import CDEDB_PATHS
from cdedb.backend.session import SessionBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend


class Application(BaseApp):
    """This does state creation upon every request and then hands it on to the
    appropriate frontend."""

    def __init__(self, configpath: PathLike = None) -> None:
        super().__init__(configpath)
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
        self.jinja_env.policies['ext.i18n.trimmed'] = True  # type: ignore
        self.translations = {
            lang: gettext.translation(
                'cdedb', languages=[lang],
                localedir=str(self.conf["REPOSITORY_PATH"] / 'i18n'))
            for lang in self.conf["I18N_LANGUAGES"]}
        if pathlib.Path("/PRODUCTIONVM").is_file():
            # Sanity checks for the live instance
            if self.conf["CDEDB_DEV"] or self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                raise RuntimeError(
                    n_("Refusing to start in debug/offline mode."))

    def make_error_page(self, error: werkzeug.exceptions.HTTPException,
                        request: werkzeug.wrappers.Request, message: str = None,
                        ) -> Response:
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

            def _cdedblink(endpoint, params=None):
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
                'user': User(),
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
        # first try for handling exceptions
        try:
            # second try for logging exceptions
            try:
                # note time for performance measurement
                begin = now()
                sessionkey = request.cookies.get("sessionkey")
                # TODO remove ml script key backwards compatibility code
                apitoken = (request.headers.get("X-CdEDB-API-Token")
                            or request.headers.get("MLSCRIPTKEY"))
                urls = self.urlmap.bind_to_environ(request.environ)
                endpoint, args = urls.match()
                if apitoken:
                    sessionkey = None
                    user = self.sessionproxy.lookuptoken(apitoken,
                                                         request.remote_addr)
                    # Error early to make debugging easier.
                    if 'droid' not in user.roles:
                        raise werkzeug.exceptions.Forbidden(
                            "API token invalid.")
                else:
                    user = self.sessionproxy.lookupsession(sessionkey,
                                                           request.remote_addr)

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
                            self.encode_notification(  # type: ignore
                                fake_rs, "error", n_("Session expired."))])
                        ret.set_cookie("displaynote", notifications)
                        return ret
                coders: Dict[str, Callable[..., Any]] = {
                    "encode_parameter": self.encode_parameter,
                    "decode_parameter": self.decode_parameter,
                    "encode_notification": self.encode_notification,
                    "decode_notification": self.decode_notification,
                }
                lang = self.get_locale(request)
                rs = RequestState(
                    sessionkey=sessionkey, apitoken=apitoken, user=user,
                    request=request, notifications=[], mapadapter=urls,
                    requestargs=args, errors=[], values=None, lang=lang,
                    gettext=self.translations[lang].gettext,
                    ngettext=self.translations[lang].ngettext,
                    coders=coders, begin=begin,
                    default_gettext=self.translations["en"].gettext,
                    default_ngettext=self.translations["en"].ngettext
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
                                self.logger.info(
                                    "Invalid notification '{}'".format(note))
                    except Exception:
                        # Do nothing if we fail to handle a notification,
                        # they can be manipulated by the client side, so
                        # we can not assume anything.
                        pass
                handler = getattr(getattr(self, component), action)
                if request.method not in handler.modi:
                    raise werkzeug.exceptions.MethodNotAllowed(
                        handler.modi,
                        "Unsupported request method {}.".format(
                            request.method))

                # Check anti CSRF token (if required by the endpoint)
                if handler.check_anti_csrf and 'droid' not in user.roles:
                    error = check_anti_csrf(rs, component, action)
                    if error is not None:
                        rs.csrf_alert = True
                        rs.extend_validation_errors(
                            ((ANTI_CSRF_TOKEN_NAME, ValueError(error)),))
                        rs.notify('error', error)

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
                presider = set()
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
                        raise RuntimeError("Input validation forgotten.")
                    return ret
                finally:
                    # noinspection PyProtectedMember
                    rs._conn.commit()
                    # noinspection PyProtectedMember
                    rs._conn.close()
            except werkzeug.exceptions.HTTPException:
                # do not log these, since they are not interesting and
                # reduce the signal to noise ratio
                raise
            except Exception:
                self.logger.error(glue(
                    ">>>\n>>>\n>>>\n>>> Exception while serving {}",
                    "<<<\n<<<\n<<<\n<<<").format(request.url))
                self.logger.exception("FIRST AS SIMPLE TRACEBACK")
                self.logger.error("SECOND TRY CGITB")
                # noinspection PyBroadException
                try:
                    self.logger.error(cgitb.text(sys.exc_info(), context=7))
                except Exception:
                    pass
                raise
        except werkzeug.routing.RequestRedirect as e:
            return e.get_response(request.environ)
        except werkzeug.exceptions.HTTPException as e:
            return self.make_error_page(e, request)
        except psycopg2.extensions.TransactionRollbackError as e:
            # Serialization error
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(str(e.args)),
                request,
                n_("A modification to the database could not be executed due "
                   "to simultaneous access. Please reload the page to try "
                   "again."))
        except QuotaException:
            return self.make_error_page(
                werkzeug.exceptions.Forbidden(
                    n_("Profile view quota reached.")),
                request,
                n_("You reached the internal limit for user profile views. "
                   "This is a privacy feature to prevent users from cloning "
                   "the address database. Unfortunatetly, this may also yield "
                   "some false positive restrictions. Your limit will be "
                   "reset in the next days."))
        except Exception as e:
            # Raise exceptions when in TEST environment to let the test runner
            # catch them.
            if self.conf["CDEDB_TEST"]:
                raise

            # debug output if applicable
            if self.conf["CDEDB_DEV"]:
                return Response(cgitb.html(sys.exc_info(), context=7),
                                mimetype="text/html", status=500)
            # generic errors
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(repr(e)),
                request)

    def get_locale(self, request: werkzeug.wrappers.Request) -> str:
        """
        Extract a locale from the request headers (cookie and/or
        Accept-Language)

        :return: Language code of the requested locale
        """
        if 'locale' in request.cookies \
                and request.cookies['locale'] in self.conf["I18N_LANGUAGES"]:
            return request.cookies['locale']

        if 'Accept-Language' in request.headers:
            for lang in request.headers['Accept-Language'].split(','):
                lang_code = lang.split('-')[0].split(';')[0].strip()
                if lang_code in self.conf["I18N_LANGUAGES"]:
                    return lang_code

        return 'de'


def check_anti_csrf(rs: RequestState, component: str, action: str
                    ) -> Optional[str]:
    """
    A helper function to check the anti CSRF token

    The anti CSRF token is a signed userid, added as hidden input to most
    forms, used to mitigate Cross Site Request Forgery (CSRF) attacks. It is
    checked before calling the handler function, if the handler function is
    marked to be protected against CSRF attacks, which is the default for
    all POST endpoints.

    The anti CSRF token should be created using the util.anti_csrf_token
    template macro.

    :param action: The name of the endpoint, checked by 'decode_parameter'
    :param component: The name of the realm, checked by 'decode_parameter'
    :return: None if everything is ok, or an error message otherwise.
    """
    val = rs.request.values.get(ANTI_CSRF_TOKEN_NAME, "").strip()
    if not val:
        return n_("Anti CSRF token is required for this form.")
    # noinspection PyProtectedMember
    timeout, val = rs._coders['decode_parameter'](
        "{}/{}".format(component, action), ANTI_CSRF_TOKEN_NAME, val,
        rs.user.persona_id)
    if not val:
        if timeout:
            return n_("Anti CSRF token expired. Please try again.")
        else:
            return n_("Anti CSRF token is forged.")
    if val != ANTI_CSRF_TOKEN_PAYLOAD:
        return n_("Anti CSRF token is invalid.")
    return None
