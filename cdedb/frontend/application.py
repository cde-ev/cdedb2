#!/usr/bin/env python3

"""The WSGI-application to tie it all together."""

import cgitb
import gettext
import json
import pathlib
import sys

import jinja2
import psycopg2.extensions
import werkzeug
import werkzeug.routing
import werkzeug.exceptions
import werkzeug.wrappers

from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.common import (
    n_, glue, QuotaException, now, roles_to_db_role, RequestState, User,
    ANTI_CSRF_TOKEN_NAME, ProxyShim)
from cdedb.frontend.common import (
    BaseApp, construct_redirect, Response, sanitize_None, staticurl,
    docurl, JINJA_FILTERS, check_validation)
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.paths import CDEDB_PATHS
from cdedb.backend.session import SessionBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend


class Application(BaseApp):
    """This does state creation upon every request and then hands it on to the
    appropriate frontend."""

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.mlproxy = ProxyShim(MlBackend(configpath))
        # do not use a ProxyShim since the only usage here is before the
        # RequestState exists
        self.sessionproxy = SessionBackend(configpath)
        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)
        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            secrets, self.conf.DB_PORT)
        self.validate_mlscriptkey = lambda k: k == secrets.ML_SCRIPT_KEY
        # Construct a reduced Jinja environment for rendering error pages.
        # TODO With buster we can activate the trimming of the trans env
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(self.conf.REPOSITORY_PATH / "cdedb/frontend/templates")),
            extensions=('jinja2.ext.with_', 'jinja2.ext.i18n', 'jinja2.ext.do',
                        'jinja2.ext.loopcontrols', 'jinja2.ext.autoescape'),
            finalize=sanitize_None, autoescape=True,
            auto_reload=self.conf.CDEDB_DEV)
        self.jinja_env.globals.update({
            'now': now,
            'staticurl': staticurl,
            'docurl': docurl,
            'glue': glue,
        })
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.translations = {
            lang: gettext.translation(
                'cdedb', languages=(lang,),
                localedir=str(self.conf.REPOSITORY_PATH / 'i18n'))
            for lang in self.conf.I18N_LANGUAGES}
        if pathlib.Path("/PRODUCTIONVM").is_file():
            # Sanity checks for the live instance
            if self.conf.CDEDB_DEV or self.conf.CDEDB_OFFLINE_DEPLOYMENT:
                raise RuntimeError(
                    n_("Refusing to start in debug/offline mode."))

    def make_error_page(self, error, request, message=None):
        """Helper to format an error page.

        This is similar to
        :py:meth:`cdedb.frontend.common.AbstractFrontend.fill_template`,
        but creates a Response instead of only a string. It also has a more
        minimalistic setup to work, even when normal application startup fails.

        :type error: :py:class:`werkzeug.exceptions.HTTPException`
        :type request: :py:class:`werkzeug.wrappers.Request`
        :param message: An additional help string. If given, the default help
                     string for each HTTP code (below the error description) is
                     prepended by this string (or its translation).
        :type message: str
        :rtype: :py:class:`Response`
        """
        try:
            # We don't like werkzeug's default 404 description:
            if isinstance(error, werkzeug.exceptions.NotFound) \
                    and (error.description
                         is werkzeug.exceptions.NotFound.description):
                error.description = None

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
    def __call__(self, request):
        """
        :type request: :py:class:`werkzeug.wrappers.Request`
        """
        # first try for handling exceptions
        try:
            # second try for logging exceptions
            try:
                # note time for performance measurement
                begin = now()
                sessionkey = request.cookies.get("sessionkey")
                urls = self.urlmap.bind_to_environ(request.environ)
                endpoint, args = urls.match()
                mlscriptkey = request.headers.get("MLSCRIPTKEY")
                user = self.sessionproxy.lookupsession(sessionkey,
                                                       request.remote_addr)
                if self.validate_mlscriptkey(mlscriptkey):
                    # Special case the access of the mailing list software
                    # since it's not tied to an actual persona. Note that
                    # this is not affected by the LOCKDOWN configuration.
                    user.roles.add("ml_script")

                # Check for timed out / invalid sessionkey
                if sessionkey and not user.persona_id:
                    params = {
                        'wants': self.encode_parameter(
                            "core/index", "wants", request.url,
                            timeout=self.conf.UNCRITICAL_PARAMETER_TIMEOUT),
                    }
                    ret = construct_redirect(request,
                                             urls.build("core/index", params))
                    ret.delete_cookie("sessionkey")
                    notifications = json.dumps([self.encode_notification(
                        "error", n_("Session expired."))])
                    ret.set_cookie("displaynote", notifications)
                    return ret
                coders = {
                    "encode_parameter": self.encode_parameter,
                    "decode_parameter": self.decode_parameter,
                    "encode_notification": self.encode_notification,
                    "decode_notification": self.decode_notification,
                }
                lang = self.get_locale(request)
                rs = RequestState(
                    sessionkey=sessionkey, user=user, request=request,
                    response=None, notifications=[], mapadapter=urls,
                    requestargs=args, errors=[], values={}, lang=lang,
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
                    try:
                        notifications = json.loads(raw_notifications)
                        for note in notifications:
                            ntype, nmessage, nparams = (
                                self.decode_notification(note))
                            if ntype:
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
                if handler.check_anti_csrf:
                    okay, error = check_anti_csrf(rs, component, action)
                    if not okay:
                        rs.csrf_alert = True
                        rs.errors.append((ANTI_CSRF_TOKEN_NAME,
                                          ValueError(error)))
                        rs.notify('error', error)

                # Store database connection as private attribute.
                # It will be made accessible for the backends by the ProxyShim.
                rs._conn = self.connpool[roles_to_db_role(user.roles)]

                # Insert orga and moderator status context
                orga = []
                if "event" in user.roles:
                    orga = self.eventproxy.orga_info(rs, user.persona_id)
                moderator = []
                if "ml" in user.roles:
                    moderator = self.mlproxy.moderator_info(rs,
                                                            user.persona_id)
                user.orga = orga
                user.moderator = moderator

                try:
                    return handler(rs, **args)
                finally:
                    rs._conn.commit()
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
                self.logger.error(cgitb.text(sys.exc_info(), context=7))
                raise
        except werkzeug.routing.RequestRedirect as e:
            return e.get_response(request.environ)
        except werkzeug.exceptions.HTTPException as e:
            return self.make_error_page(e, request)
        except psycopg2.extensions.TransactionRollbackError as e:
            # Serialization error
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(e.args),
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
            if self.conf.CDEDB_TEST:
                raise

            # debug output if applicable
            if self.conf.CDEDB_DEV:
                return Response(cgitb.html(sys.exc_info(), context=7),
                                mimetype="text/html", status=500)
            # generic errors
            return self.make_error_page(
                werkzeug.exceptions.InternalServerError(repr(e)),
                request)

    def get_locale(self, request):
        """
        Extract a locale from the request headers (cookie and/or
        Accept-Language)

        :return: Language code of the requested locale
        :rtype: str
        """
        if 'locale' in request.cookies \
                and request.cookies['locale'] in self.conf.I18N_LANGUAGES:
            return request.cookies['locale']

        if 'Accept-Language' in request.headers:
            for lang in request.headers['Accept-Language'].split(','):
                lang_code = lang.split('-')[0].split(';')[0].strip()
                if lang_code in self.conf.I18N_LANGUAGES:
                    return lang_code

        return 'de'


def check_anti_csrf(rs, component, action):
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
    :type component: str
    :param component: The name of the realm, checked by 'decode_parameter'
    :type action: str
    :rtype: (bool, str)
    :return: The status of the CSRF token (True if okay, False if not) and the
         error pertaining to it)
    """
    val = rs.request.values.get(ANTI_CSRF_TOKEN_NAME, "").strip()
    if not val:
        return False, n_("Anti CSRF token is required for this form.")
    timeout, val = rs._coders['decode_parameter'](
        "{}/{}".format(component, action), ANTI_CSRF_TOKEN_NAME, val)
    if not val:
        if timeout:
            return False, n_("Anti CSRF token expired. Please try again.")
        else:
            return False, n_("Anti CSRF token is forged.")
    val = check_validation(rs, 'id', val, ANTI_CSRF_TOKEN_NAME)
    if not val:
        return False, n_("Anti CSRF token is no valid user id.")
    if val != rs.user.persona_id:
        return False, n_("Anti CSRF token is forged.")
    return True, None
