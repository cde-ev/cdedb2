#!/usr/bin/env python3

"""The WSGI-application to tie it all together."""

import werkzeug
import cgitb
import sys
from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.common import glue, make_root_logger, QuotaException, PrivilegeError
from cdedb.frontend.common import (
    FrontendRequestState, BaseApp, construct_redirect, connect_proxy,
    FakeFrontendRequestState)
from cdedb.config import SecretsConfig
from cdedb.frontend.paths import CDEDB_PATHS
from cdedb.serialization import deserialize
import werkzeug.routing
import werkzeug.exceptions
import werkzeug.wrappers
import psycopg2.extensions
import datetime
import json
import pytz

class Application(BaseApp):
    """This does state creation upon every request and then hands it on to the
    appropriate frontend."""
    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        ## initialize logging
        make_root_logger("cdedb.frontend", self.conf.FRONTEND_LOG,
                         self.conf.LOG_LEVEL,
                         syslog_level=self.conf.SYSLOG_LEVEL,
                         console_log_level=self.conf.CONSOLE_LOG_LEVEL)
        ## do not use a ProxyShim since the only usage here is before the
        ## RequestState exists
        self.sessionproxy = connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("session"))
        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)
        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.session_lookup_key = secrets.SESSION_LOOKUP_KEY


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
                begin = datetime.datetime.now(pytz.utc)
                sessionkey = request.cookies.get("sessionkey")
                ## we have to do the work the ProxyShim normally does
                with self.sessionproxy:
                    data = deserialize(self.sessionproxy.lookupsession(
                        self.session_lookup_key, sessionkey,
                        request.remote_addr))
                urls = self.urlmap.bind_to_environ(request.environ)
                endpoint, args = urls.match()
                if sessionkey and not data["persona_id"]:
                    params = {
                        'wants': self.encode_parameter(
                            "core/index", "wants", request.url),}
                    ret = construct_redirect(request,
                                             urls.build("core/index", params))
                    ret.delete_cookie("sessionkey")
                    notificationss = json.dumps([self.encode_notification(
                        "error", "Session expired.")])
                    ret.set_cookie("displaynote", notificationss)
                    return ret
                coders = {
                    "encode_parameter": self.encode_parameter,
                    "decode_parameter": self.decode_parameter,
                    "encode_notification": self.encode_notification,
                    "decode_notification": self.decode_notification,
                }
                rs = FrontendRequestState(sessionkey, None, request, None,
                                          [], urls, args, self.urlmap,
                                          [], {}, "de", coders, begin)
                rs.values.update(args)
                component, action = endpoint.split('/')
                raw_notifications = rs.request.cookies.get("displaynote")
                if raw_notifications:
                     try:
                         notifications = json.loads(raw_notifications)
                         for note in notifications:
                             ntype, nmessage = self.decode_notification(note)
                             if ntype:
                                 rs.notify(ntype, nmessage)
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
                rs.user = getattr(self, component).finalize_session(
                    FakeFrontendRequestState(sessionkey), data)
                return handler(rs, **args)
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
                if hasattr(e, '_pyroTraceback'):
                    self.logger.error("THIRD NESTED PYRO TRACEBACK")
                    self.logger.error("".join(e._pyroTraceback))
                raise
        except PrivilegeError as e:
            ## Convert permission errors from the backend to 503
            return werkzeug.exceptions.Forbidden(e.args)
        except werkzeug.exceptions.HTTPException as e:
            return e
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
                return werkzeug.wrappers.Response(
                    cgitb.html(sys.exc_info(), context=7), mimetype="text/html")
            ## prevent infinite loop if the error pages are buggy
            if request.base_url.endswith("error"):
                raise
            ## generic errors
            return construct_redirect(request,
                                      urls.build("core/error",
                                                 {'kind': "general"}))
