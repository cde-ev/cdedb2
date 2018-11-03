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
    n_, glue, QuotaException, PrivilegeError, now,
    roles_to_db_role, RequestState, User, extract_roles)
from cdedb.frontend.common import (
    BaseApp, construct_redirect, Response, sanitize_None, staticurl,
    docurl, JINJA_FILTERS)
from cdedb.config import SecretsConfig, Config
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.paths import CDEDB_PATHS
from cdedb.backend.session import SessionBackend

class Application(BaseApp):
    """This does state creation upon every request and then hands it on to the
    appropriate frontend."""
    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        ## do not use a ProxyShim since the only usage here is before the
        ## RequestState exists
        self.sessionproxy = SessionBackend(configpath)
        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)
        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.conf = Config(configpath)
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            secrets, self.conf.DB_PORT)
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(self.conf.REPOSITORY_PATH / "cdedb/frontend/templates")),
            extensions=('jinja2.ext.with_', 'jinja2.ext.i18n', 'jinja2.ext.do',
                        'jinja2.ext.loopcontrols', 'jinja2.ext.autoescape'),
            finalize=sanitize_None)
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.translations = {
            lang: gettext.translation(
                'cdedb', languages=(lang,),
                localedir=str(self.conf.REPOSITORY_PATH / 'i18n'))
            for lang in self.conf.I18N_LANGUAGES}
        if pathlib.Path("/DBVM").is_file():
            ## Sanity checks for the live instance
            if self.conf.CDEDB_DEV or self.conf.CDEDB_OFFLINE_DEPLOYMENT:
                raise RuntimeError(n_("Refusing to start in debug mode."))

    def make_error_page(self, error, request):
        """Helper to format an error page.

        This is similar to
        :py:meth:`cdedb.frontend.common.AbstractFrontend.fill_template`,
        but creates a Response instead of only a string.


        :type error: :py:class:`werkzeug.exceptions.HTTPException`
        :type request: :py:class:`werkzeug.wrappers.Request`
        :rtype: :py:class:`Response`
        """
        if error.code not in (403, 404):
            ## Only handle Forbidden and NotFound otherwise return a plain error
            return error
        urls = self.urlmap.bind_to_environ(request.environ)
        def _cdedblink(endpoint, params=None):
            return urls.build(endpoint, params or {})
        begin = now()
        lang = "de"
        data = {
            'ambience': {},
            'cdedblink': _cdedblink,
            'errors': {},
            'generation_time': lambda: (now() - begin),
            'glue': glue,
            'gettext': self.translations[lang].gettext,
            'ngettext': self.translations[lang].ngettext,
            'notifications': tuple(),
            'now': now,
            'staticurl': staticurl,
            'docurl': docurl,
            'user': User(),
            'values': {},
            'error': error,
        }
        t = self.jinja_env.get_template(str(pathlib.Path("web", "error.tmpl")))
        html = t.render(**data)
        response = Response(html, mimetype='text/html', status=error.code)
        response.headers.add('X-Generation-Time', str(now() - begin))
        return response

    @werkzeug.wrappers.Request.application
    def __call__(self, request):
        """
        :type request: :py:class:`werkzeug.wrappers.Request`
        """
        ## first try for handling exceptions
        try:
            #second try for logging exceptions
            try:
                ## note time for performance measurement
                begin = now()
                sessionkey = request.cookies.get("sessionkey")
                scriptkey = request.cookies.get("scriptkey")
                data = self.sessionproxy.lookupsession(sessionkey,
                                                       request.remote_addr)
                urls = self.urlmap.bind_to_environ(request.environ)
                endpoint, args = urls.match()
                if sessionkey and not data["persona_id"]:
                    params = {
                        'wants': self.encode_parameter(
                            "core/index", "wants", request.url),}
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
                rs = RequestState(
                    sessionkey, None, request, None, [], urls, args,
                    self.urlmap, [], {}, "de", self.translations["de"].gettext,
                    self.translations["de"].ngettext, coders, begin, scriptkey)
                rs.values.update(args)
                component, action = endpoint.split('/')
                raw_notifications = rs.request.cookies.get("displaynote")
                if raw_notifications:
                    try:
                        notifications = json.loads(raw_notifications)
                        for note in notifications:
                            ntype, nmessage, nparams = self.decode_notification(
                                note)
                            if ntype:
                                rs.notify(ntype, nmessage, nparams)
                            else:
                                self.logger.info(
                                    "Invalid notification '{}'".format(note))
                    except:
                        ## Do nothing if we fail to handle a notification,
                        ## they can be manipulated by the client side, so
                        ## we can not assume anything.
                        pass
                handler = getattr(getattr(self, component), action)
                if request.method not in handler.modi:
                    raise werkzeug.exceptions.MethodNotAllowed(
                        handler.modi,
                        "Unsupported request method {}.".format(request.method))
                vals = {k: data[k] for k in ('persona_id', 'username',
                                             'given_names', 'display_name',
                                             'family_name')}
                rs.user = User(roles=extract_roles(data), **vals)
                ## Store database connection as private attribute.
                ## It will be made accessible for the backends by the ProxyShim.
                rs._conn = self.connpool[roles_to_db_role(rs.user.roles)]
                ## Add realm specific infos (mostly to the user object)
                getattr(self, component).finalize_session(rs, self.connpool)
                for realm in getattr(handler, 'realm_usage', set()):
                    ## Add extra information for the cases where it's necessary
                    getattr(self, realm).finalize_session(rs, self.connpool,
                                                          auxilliary=True)
                try:
                    return handler(rs, **args)
                finally:
                    rs._conn.commit()
                    rs._conn.close()
            except werkzeug.exceptions.HTTPException:
                ## do not log these, since they are not interesting and
                ## reduce the signal to noise ratio
                raise
            except Exception as e:
                self.logger.error(glue(
                    ">>>\n>>>\n>>>\n>>> Exception while serving {}",
                    "<<<\n<<<\n<<<\n<<<").format(request.url))
                self.logger.exception("FIRST AS SIMPLE TRACEBACK")
                self.logger.error("SECOND TRY CGITB")
                self.logger.error(cgitb.text(sys.exc_info(), context=7))
                raise
        except PrivilegeError as e:
            ## Convert permission errors from the backend to 403
            return self.make_error_page(werkzeug.exceptions.Forbidden(e.args),
                                        request)
        except werkzeug.exceptions.HTTPException as e:
            return self.make_error_page(e, request)
        except psycopg2.extensions.TransactionRollbackError:
            ## Serialization error
            return construct_redirect(
                request, urls.build("core/error", {'kind': "database"}))
        except QuotaException:
            return construct_redirect(
                request, urls.build("core/error", {'kind': "quota"}))
        except Exception as e:
            ## debug output if applicable
            if self.conf.CDEDB_DEV or ('data' in locals()
                                       and data.get('db_privileges')
                                       and (data.get('db_privileges') % 2)):
                return Response(cgitb.html(sys.exc_info(), context=7),
                                mimetype="text/html")
            ## prevent infinite loop if the error pages are buggy
            if request.base_url.endswith("error"):
                raise
            ## generic errors
            return construct_redirect(
                request, urls.build("core/error", {'kind': "general",
                                                   'message': str(e)}))
