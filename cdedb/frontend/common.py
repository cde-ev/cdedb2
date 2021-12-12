#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic.
"""

import abc
import cgitb
import collections
import collections.abc
import copy
import csv
import datetime
import email
import email.charset
import email.encoders
import email.header
import email.mime
import email.mime.application
import email.mime.audio
import email.mime.image
import email.mime.multipart
import email.mime.text
import email.utils
import functools
import gettext
import io
import json
import logging
import pathlib
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
import threading
import typing
import urllib.error
import urllib.parse
import weakref
from email.mime.nonmultipart import MIMENonMultipart
from secrets import token_hex
from types import TracebackType
from typing import (
    IO, AbstractSet, Any, AnyStr, Callable, ClassVar, Collection, Dict, Iterable, List,
    Literal, Mapping, MutableMapping, NamedTuple, Optional, Protocol, Sequence, Tuple,
    Type, TypeVar, Union, cast, overload,
)

import icu
import jinja2
import mailmanclient.restobjects.held_message
import mailmanclient.restobjects.mailinglist
import markupsafe
import werkzeug
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.utils
import werkzeug.wrappers

import cdedb.database.constants as const
import cdedb.query as query_mod
import cdedb.validation as validate
import cdedb.validationtypes as vtypes
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.common import AbstractBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.common import (
    ADMIN_KEYS, ALL_MGMT_ADMIN_VIEWS, ALL_MOD_ADMIN_VIEWS, ANTI_CSRF_TOKEN_NAME,
    ANTI_CSRF_TOKEN_PAYLOAD, IGNORE_WARNINGS_NAME, PERSONA_DEFAULTS,
    REALM_SPECIFIC_GENESIS_FIELDS, CdEDBMultiDict, CdEDBObject, CustomJSONEncoder,
    EntitySorter, Error, Notification, NotificationType, PathLike, PrivilegeError,
    RequestState, Role, User, ValidationWarning, _tdelta, asciificator,
    decode_parameter, encode_parameter, format_country_code,
    get_localized_country_codes, glue, json_serialize, make_proxy, make_root_logger,
    merge_dicts, n_, now, roles_to_db_role, unwrap,
)
from cdedb.config import BasicConfig, Config, SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.devsamples import HELD_MESSAGE_SAMPLE
from cdedb.enums import ENUMS_DICT
from cdedb.filter import (
    JINJA_FILTERS, cdedbid_filter, enum_entries_filter, safe_filter, sanitize_None,
)
from cdedb.query import Query

_LOGGER = logging.getLogger(__name__)
_BASICCONF = BasicConfig()


S = TypeVar('S')
T = TypeVar('T')


class Response(werkzeug.wrappers.Response):
    """Wrapper around werkzeugs Response to handle displaynote cookie.

    This is a pretty thin wrapper, but essential so our magic cookie
    gets cleared and no stale notifications remain.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.delete_cookie("displaynote")


class BaseApp(metaclass=abc.ABCMeta):
    """Additional base class under :py:class:`AbstractFrontend` which will be
    inherited by :py:class:`cdedb.frontend.application.Application`.
    """
    realm: ClassVar[str]

    def __init__(self, configpath: PathLike = None, *args: Any,  # pylint: disable=keyword-arg-before-vararg
                 **kwargs: Any) -> None:
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        # initialize logging
        if hasattr(self, 'realm') and self.realm:
            logger_name = "cdedb.frontend.{}".format(self.realm)
            logger_file = self.conf[f"{self.realm.upper()}_FRONTEND_LOG"]
        else:
            logger_name = "cdedb.frontend"
            logger_file = self.conf["FRONTEND_LOG"]
        make_root_logger(
            logger_name, logger_file, self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.logger = logging.getLogger(logger_name)  # logger are thread-safe!
        self.logger.debug(f"Instantiated {self} with configpath {configpath}.")
        # local variable to prevent closure over secrets
        url_parameter_salt = secrets["URL_PARAMETER_SALT"]
        self.decode_parameter = (
            lambda target, name, param, persona_id: decode_parameter(
                url_parameter_salt, target, name, param,
                persona_id))

        def local_encode(
                target: str, name: str, param: str, persona_id: Optional[int],
                timeout: Optional[_tdelta] = self.conf["PARAMETER_TIMEOUT"]
        ) -> str:
            return encode_parameter(url_parameter_salt, target, name,
                                    param, persona_id, timeout)

        self.encode_parameter = local_encode

    def cgitb_log(self) -> None:
        # noinspection PyBroadException
        try:
            self.logger.error(cgitb.text(sys.exc_info(), context=7))
        except Exception:
            # cgitb is very invasive when generating the stack trace, which might go
            # wrong.
            pass

    @staticmethod
    def cgitb_html() -> Response:
        return Response(cgitb.html(sys.exc_info(), context=7),
                        mimetype="text/html", status=500)

    def encode_notification(self, rs: RequestState, ntype: NotificationType,
                            nmessage: str, nparams: CdEDBObject = None) -> str:
        """Wrapper around :py:meth:`encode_parameter` for notifications.

        The message format is A--B--C--D, with

        * A is the notification type, conforming to '[a-z]+'
        * B is the length of the notification message
        * C is the notification message
        * D is the parameter dict to be substituted in the message
          (json-encoded).
        """
        nparams = nparams or {}
        message = "{}--{}--{}--{}".format(ntype, len(nmessage), nmessage,
                                          json_serialize(nparams))
        return self.encode_parameter(
            '_/notification', 'displaynote', message,
            persona_id=rs.user.persona_id,
            timeout=self.conf["UNCRITICAL_PARAMETER_TIMEOUT"])

    def decode_notification(self, rs: RequestState, note: str
                            ) -> Union[Notification, Tuple[None, None, None]]:
        """Inverse wrapper to :py:meth:`encode_notification`."""
        timeout, message = self.decode_parameter(
            '_/notification', 'displaynote', note, rs.user.persona_id)
        if not message:
            return None, None, None
        parts = message.split("--")
        ntype = parts[0]
        length = int(parts[1])
        remainder = "--".join(parts[2:])
        nmessage = remainder[:length]
        nparams = json.loads(remainder[length + 2:])
        return ntype, nmessage, nparams

    def redirect(self, rs: RequestState, target: str,
                 params: CdEDBObject = None, anchor: str = None
                 ) -> werkzeug.Response:
        """Create a response which diverts the user. Special care has to be
        taken not to lose any notifications.
        """
        params = params or {}
        if rs.retrieve_validation_errors() and not rs.notifications:
            rs.notify("error", n_("Failed validation."))
        url = cdedburl(rs, target, params, force_external=True)
        if anchor is not None:
            url += "#" + anchor
        ret = basic_redirect(rs, url)
        if rs.notifications:
            notifications = [self.encode_notification(rs, ntype, nmessage,
                                                      nparams)
                             for ntype, nmessage, nparams in rs.notifications]
            ret.set_cookie("displaynote", json_serialize(notifications))
        return ret

    def encode_anti_csrf_token(self, target: str,
                               token_name: str = ANTI_CSRF_TOKEN_NAME,
                               token_payload: str = ANTI_CSRF_TOKEN_PAYLOAD,
                               *, persona_id: int) -> str:
        return self.encode_parameter(target, token_name, token_payload, persona_id)


def raise_jinja(val: str) -> None:
    """Helper to point out programming errors in jinja.

    May not be used for handling of user input, user-errors or control flow.
    """
    raise RuntimeError(val)


# This needs acces to config, and cannot be moved to filter.py
def datetime_filter(val: Union[datetime.datetime, str, None],
                    formatstr: str = "%Y-%m-%d %H:%M (%Z)", lang: str = None,
                    passthrough: bool = False) -> Optional[str]:
    """Custom jinja filter to format ``datetime.datetime`` objects.

    :param formatstr: Formatting used, if no l10n happens.
    :param lang: If not None, then localize to the passed language.
    :param passthrough: If True return strings unmodified.
    """
    if val is None or val == '' or not isinstance(val, datetime.datetime):
        if passthrough and isinstance(val, str) and val:
            return val
        return None

    if val.tzinfo is not None:
        val = val.astimezone(_BASICCONF["DEFAULT_TIMEZONE"])
    else:
        _LOGGER.warning(f"Found naive datetime object {val}.")

    if lang:
        locale = icu.Locale(lang)
        datetime_formatter = icu.DateFormat.createDateTimeInstance(
            icu.DateFormat.MEDIUM, icu.DateFormat.MEDIUM, locale)
        zone = _BASICCONF["DEFAULT_TIMEZONE"].zone
        datetime_formatter.setTimeZone(icu.TimeZone.createTimeZone(zone))
        return datetime_formatter.format(val)
    else:
        return val.strftime(formatstr)


PeriodicMethod = Callable[[Any, RequestState, CdEDBObject], CdEDBObject]


class PeriodicJob(Protocol):
    cron: CdEDBObject

    def __call__(self, rs: RequestState, state: CdEDBObject) -> CdEDBObject: ...


def periodic(name: str, period: int = 1
             ) -> Callable[[PeriodicMethod], PeriodicJob]:
    """This decorator marks a function of a frontend for periodic execution.

    This just adds a flag and all of the actual work is done by the
    CronFrontend.

    :param name: the name of this job
    :param period: the interval in which to execute this job (e.g. period ==
      2 means every second invocation of the CronFrontend)
    """
    def decorator(fun: PeriodicMethod) -> PeriodicJob:
        fun = cast(PeriodicJob, fun)
        fun.cron = {
            'name': name,
            'period': period,
        }
        return fun

    return decorator


class AbstractFrontend(BaseApp, metaclass=abc.ABCMeta):
    """Common base class for all frontends."""
    #: to be overridden by children

    def __init__(self, configpath: PathLike = None, *args: Any,  # pylint: disable=keyword-arg-before-vararg
                 **kwargs: Any) -> None:
        super().__init__(configpath, *args, **kwargs)
        self.template_dir = pathlib.Path(self.conf["REPOSITORY_PATH"], "cdedb",
                                         "frontend", "templates")
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)),
            extensions=['jinja2.ext.i18n', 'jinja2.ext.do', 'jinja2.ext.loopcontrols'],
            finalize=sanitize_None, autoescape=True, auto_reload=self.conf["CDEDB_DEV"])
        self.jinja_env.policies['ext.i18n.trimmed'] = True  # type: ignore
        self.jinja_env.policies['json.dumps_kwargs']['cls'] = CustomJSONEncoder  # type: ignore
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.jinja_env.filters.update({'datetime': datetime_filter})
        self.jinja_env.globals.update({
            'now': now,
            'nbsp': "\u00A0",
            'query_mod': query_mod,
            'glue': glue,
            'enums': ENUMS_DICT,
            'raise': raise_jinja,
            'encode_parameter': self.encode_parameter,
            'encode_anti_csrf': self.encode_anti_csrf_token,
            'staticurl': functools.partial(staticurl,
                                           version=self.conf["GIT_COMMIT"][:8]),
            'docurl': docurl,
            "drow_name": drow_name,
            "drow_create": drow_create,
            "drow_delete": drow_delete,
            "drow_last_index": drow_last_index,
            'CDEDB_OFFLINE_DEPLOYMENT': self.conf["CDEDB_OFFLINE_DEPLOYMENT"],
            'CDEDB_DEV': self.conf["CDEDB_DEV"],
            'UNCRITICAL_PARAMETER_TIMEOUT': self.conf[
                "UNCRITICAL_PARAMETER_TIMEOUT"],
            'ANTI_CSRF_TOKEN_NAME': ANTI_CSRF_TOKEN_NAME,
            'ANTI_CSRF_TOKEN_PAYLOAD': ANTI_CSRF_TOKEN_PAYLOAD,
            'IGNORE_WARNINGS_NAME': IGNORE_WARNINGS_NAME,
            'GIT_COMMIT': self.conf["GIT_COMMIT"],
            'I18N_LANGUAGES': self.conf["I18N_LANGUAGES"],
            'I18N_ADVERTISED_LANGUAGES': self.conf["I18N_ADVERTISED_LANGUAGES"],
            'DEFAULT_COUNTRY': self.conf["DEFAULT_COUNTRY"],
            'ALL_MOD_ADMIN_VIEWS': ALL_MOD_ADMIN_VIEWS,
            'ALL_MGMT_ADMIN_VIEWS': ALL_MGMT_ADMIN_VIEWS,
            'EntitySorter': EntitySorter,
            'roles_allow_genesis_management':
                lambda roles: roles & ({'core_admin'} | set(
                    "{}_admin".format(realm)
                    for realm in REALM_SPECIFIC_GENESIS_FIELDS)),
            'unwrap': unwrap,
            'MANAGEMENT_ADDRESS': self.conf['MANAGEMENT_ADDRESS'],
        })
        self.jinja_env_tex = self.jinja_env.overlay(
            autoescape=False,
            block_start_string="<<%",
            block_end_string="%>>",
            variable_start_string="<<<",
            variable_end_string=">>>",
            comment_start_string="<<#",
            comment_end_string="#>>",
        )
        self.jinja_env_tex.filters.update({'persona_name': make_persona_name})
        self.jinja_env_mail = self.jinja_env.overlay(
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Always provide all backends -- they are cheap
        self.assemblyproxy = make_proxy(AssemblyBackend(configpath))
        self.cdeproxy = make_proxy(CdEBackend(configpath))
        self.coreproxy = make_proxy(CoreBackend(configpath))
        self.eventproxy = make_proxy(EventBackend(configpath))
        self.mlproxy = make_proxy(MlBackend(configpath))
        self.pasteventproxy = make_proxy(PastEventBackend(configpath))
        # Provide mailman access
        secrets = SecretsConfig(configpath)
        # local variables to prevent closure over secrets
        mailman_password = secrets["MAILMAN_PASSWORD"]
        mailman_basic_auth_password = secrets["MAILMAN_BASIC_AUTH_PASSWORD"]
        self.get_mailman = lambda: CdEMailmanClient(self.conf, mailman_password,
                                                    mailman_basic_auth_password)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    def fill_template(self, rs: RequestState, modus: str, templatename: str,
                      params: CdEDBObject) -> str:
        """Central function for generating output from a template. This
        makes several values always accessible to all templates.

        .. note:: We change the templating syntax for TeX templates since
                  jinjas default syntax is nasty for this.

        :param modus: Type of thing we want to generate; can be one of
          * web,
          * mail,
          * tex,
          * other.
        :param templatename: file name of template without extension
        """

        def _cdedblink(endpoint: str, params: CdEDBMultiDict = None,
                       magic_placeholders: Collection[str] = None) -> str:
            """We don't want to pass the whole request state to the
            template, hence this wrapper.

            :param magic_placeholders: parameter names to insert as magic
                                       placeholders in url
            """
            params = params or werkzeug.datastructures.MultiDict()
            return cdedburl(rs, endpoint, params,
                            force_external=(modus != "web"),
                            magic_placeholders=magic_placeholders)

        def _doclink(topic: str, anchor: str = "") -> str:
            """Create link to documentation in non-web templates.

            This should be used to avoid hardcoded links in our templates. To create
            links in web-templates, use docurl in combination with util.href instead.
            """
            if modus == "web":
                raise RuntimeError(n_("Must not be used in web templates."))
            return doclink(rs, label="", topic=topic, anchor=anchor, html=False)

        def _staticlink(path: str, version: str = "") -> str:
            """Create link to static files in non-web templates.

            This should be used to avoid hardcoded links in our templates. To create
            links in web-templates, use staticurl in combination with util.href instead.
            """
            if modus == "web":
                raise RuntimeError(n_("Must not be used in web templates."))
            return staticlink(rs, label="", path=path, version=version, html=False)

        def _show_user_link(user: User, persona_id: int, quote_me: bool = None,
                            event_id: int = None, ml_id: int = None) -> str:
            """Convenience method to create link to user data page.

            This is lengthy otherwise because of the parameter encoding
            and a pretty frequent operation so that it is beneficial to
            have this helper.
            """
            params = {
                'persona_id': persona_id,
                'confirm_id': self.encode_parameter(
                    "core/show_user", "confirm_id", str(persona_id),
                    persona_id=user.persona_id, timeout=None)}
            if quote_me:
                params['quote_me'] = True
            if event_id:
                params['event_id'] = event_id
            if ml_id:
                params['ml_id'] = ml_id
            return cdedburl(rs, 'core/show_user', params)

        def _is_warning(parameter_name: str) -> bool:
            """Determine if a given error is a warning.

            They can be suppressed by the user.
            """
            all_errors = rs.retrieve_validation_errors()
            return all(
                isinstance(kind, ValidationWarning)
                for param, kind in all_errors if param == parameter_name)

        def _has_warnings() -> bool:
            """Determine if there are any warnings among the errors."""
            return bool(validate.get_warnings(rs.retrieve_validation_errors()))

        def _make_backend_checker(rs: RequestState, backend: AbstractBackend,
                                  method_name: str) -> Callable[..., Any]:
            """Provide a checker from the backend(proxy) for the templates.

            This wraps a call to the given backend method, to not require
            access to the backend or the RequestState.
            """
            checker = getattr(backend, method_name)
            if callable(checker):
                return lambda *args, **kwargs: checker(rs, *args, **kwargs)
            else:
                raise AttributeError(n_("Given method is not callable."))

        errorsdict: Dict[Optional[str], List[Exception]] = {}
        for key, value in rs.retrieve_validation_errors():
            errorsdict.setdefault(key, []).append(value)

        # here come the always accessible things promised above
        data = {
            'COUNTRY_CODES': get_localized_country_codes(rs),
            'ambience': rs.ambience,
            'cdedblink': _cdedblink,
            'doclink': _doclink,
            'staticlink': _staticlink,
            'errors': errorsdict,
            'generation_time': lambda: (now() - rs.begin),
            'gettext': rs.gettext,
            'has_warnings': _has_warnings,
            'is_admin': self.is_admin(rs),
            'is_relevant_admin': _make_backend_checker(
                rs, self.mlproxy, method_name="is_relevant_admin"),
            'is_warning': _is_warning,
            'lang': rs.lang,
            'ngettext': rs.ngettext,
            'notifications': rs.notifications,
            'original_request': rs.request,
            'show_user_link': _show_user_link,
            'user': rs.user,
            'values': rs.values,
        }

        # check that default values are not overridden
        if set(data) & set(params):
            raise ValueError(
                n_("Default values cannot be overridden: %(keys)s"),
                {'keys': set(data) & set(params)})
        merge_dicts(data, params)

        if modus == "web":
            jinja_env = self.jinja_env
        elif modus == "mail":
            jinja_env = self.jinja_env_mail
        elif modus == "tex":
            jinja_env = self.jinja_env_tex
        elif modus == "other":
            jinja_env = self.jinja_env
        else:
            raise NotImplementedError(n_("Requested modus does not exists: %(modus)s"),
                                      {'modus': modus})
        tmpl = pathlib.Path(modus, self.realm, f"{templatename}.tmpl")
        # sadly, jinja does not catch nicely if the template exists, so we do this here
        if not (self.template_dir / tmpl).is_file():
            raise ValueError(n_("Template not found: %(file)s"), {'file': tmpl})
        t = jinja_env.get_template(str(tmpl))
        return t.render(**data)

    @staticmethod
    def send_csv_file(rs: RequestState, mimetype: str = 'text/csv',
                      filename: str = None, inline: bool = True, *,
                      path: Union[str, pathlib.Path] = None,
                      afile: IO[bytes] = None,
                      data: AnyStr = None) -> Response:
        """Wrapper around :py:meth:`send_file` for CSV files.

        This makes Excel happy by adding a BOM at the beginning of the
        file. All parameters (except for encoding) are as in the wrapped
        method.
        """
        if path is not None:
            path = pathlib.Path(path)
        return AbstractFrontend.send_file(
            rs, mimetype=mimetype, filename=filename, inline=inline, path=path,
            afile=afile, data=data, encoding='utf-8-sig')

    @staticmethod
    def send_file(rs: RequestState, mimetype: str = None, filename: str = None,
                  inline: bool = True, *, path: PathLike = None,
                  afile: IO[bytes] = None, data: AnyStr = None,
                  encoding: str = 'utf-8') -> Response:
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :param mimetype: If not None the mime type of the file to be sent.
        :param filename: If not None the default file name used if the user
          tries to save the file to disk
        :param inline: Set content disposition to force display in browser (if
          True) or to force a download box (if False).
        :param afile: should be opened in binary mode
        :param encoding: The character encoding to be uses, if `data` is given
          as str
        """
        if not path and not afile and not data:
            raise ValueError(n_("No input specified."))
        if (path and afile) or (path and data) or (afile and data):
            raise ValueError(n_("Ambiguous input."))

        payload: Union[Iterable[bytes], bytes]
        if path:
            f = pathlib.Path(path).open("rb")
            payload = werkzeug.wsgi.wrap_file(rs.request.environ, f)
        elif afile:
            payload = werkzeug.wsgi.wrap_file(rs.request.environ, afile)
        elif data:
            if isinstance(data, str):
                payload = data.encode(encoding)
            elif isinstance(data, bytes):
                payload = data
            else:
                raise ValueError(n_("Invalid input type."))
        else:
            raise RuntimeError(n_("Impossible."))

        extra_args = {}
        if mimetype is not None:
            extra_args['mimetype'] = mimetype
        headers = []
        disposition = "inline" if inline else "attachment"
        if filename is not None:
            disposition += '; filename="{}"'.format(filename)
        headers.append(('Content-Disposition', disposition))
        headers.append(('X-Generation-Time', str(now() - rs.begin)))
        return Response(payload, direct_passthrough=True, headers=headers, **extra_args)

    @staticmethod
    def send_json(rs: RequestState, data: Any) -> Response:
        """Slim helper to create json responses."""
        response = Response(json_serialize(data),
                            mimetype='application/json')
        response.headers.add('X-Generation-Time', str(now() - rs.begin))
        return response

    def send_query_download(self, rs: RequestState, result: Collection[CdEDBObject],
                            query: Query, kind: str, filename: str) -> Response:
        """Helper to send download of query result.

        :param kind: Can be either `'csv'` or `'json'`.
        :param filename: The extension will be added automatically depending on
            the kind specified.
        """
        fields: List[str] = sum(
            (csvfield.split(',') for csvfield in query.fields_of_interest), [])
        filename += f".{kind}"

        # Apply special handling to enums and country codes for downloads.
        for k, v in query.spec.items():
            if k.endswith("gender"):
                query.spec[k] = query.spec[k].replace_choices(
                    dict(enum_entries_filter(
                        const.Genders, lambda x: x.name, raw=True)))
            if k.endswith(".status"):
                query.spec[k] = query.spec[k].replace_choices(
                    dict(enum_entries_filter(
                        const.RegistrationPartStati, lambda x: x.name, raw=True)))
            if k.endswith(("country", "country2")):
                query.spec[k] = query.spec[k].replace_choices(
                    dict(get_localized_country_codes(rs, rs.default_lang)))
            if "xfield" in k:
                query.spec[k] = query.spec[k].replace_choices({})
        substitutions = {k: v.choices for k, v in query.spec.items() if v.choices}

        if kind == "csv":
            csv_data = csv_output(result, fields, substitutions=substitutions)
            return self.send_csv_file(
                rs, data=csv_data, inline=False, filename=filename)
        elif kind == "json":
            json_data = query_result_to_json(
                result, fields, substitutions=substitutions)
            return self.send_file(
                rs, data=json_data, inline=False, filename=filename)
        else:
            raise ValueError(
                n_("Unknown download kind {kind}."), {"kind": kind})

    def render(self, rs: RequestState, templatename: str,
               params: CdEDBObject = None) -> werkzeug.Response:
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTML responses.
        """
        params = params or {}
        # handy, should probably survive in a commented HTML portion
        if 'debugstring' not in params and self.conf["CDEDB_DEV"]:
            debugstring = (
                f"We have is_multithreaded={rs.request.is_multithread};"
                f" is_multiprocess={rs.request.is_multiprocess};"
                f" base_url={rs.request.base_url}; cookies={rs.request.cookies};"
                f" url={rs.request.url}; is_secure={rs.request.is_secure};"
                f" method={rs.request.method}; remote_addr={rs.request.remote_addr};"
                f" values={rs.values}; ambience={rs.ambience};"
                f" errors={rs.retrieve_validation_errors()}; time={now()}")

            _LOGGER.debug(debugstring)
            params['debugstring'] = debugstring
        if (errors := rs.retrieve_validation_errors()) and not rs.notifications:
            if all(isinstance(kind, ValidationWarning) for param, kind in errors):
                rs.notify("warning", n_("Input seems faulty. Please double-check if"
                                        " you really want to save it."))
            else:
                rs.notify("error", n_("Failed validation."))
        if self.conf["LOCKDOWN"]:
            rs.notify("info", n_("The database currently undergoes "
                                 "maintenance and is unavailable."))
        # A nonce to mark safe <script> tags in context of the CSP header
        csp_nonce = token_hex(12)
        params['csp_nonce'] = csp_nonce

        html = self.fill_template(rs, "web", templatename, params)
        response = Response(html, mimetype='text/html')
        response.headers.add('X-Generation-Time', str(now() - rs.begin))

        # Add CSP header to disallow scripts, styles, images and objects from
        # other domains. This is part of XSS mitigation
        csp_header_template = glue(
            "default-src 'self';",
            "script-src 'unsafe-inline' 'self' https: 'nonce-{}';",
            "style-src 'self' 'unsafe-inline';",
            "img-src *")
        response.headers.add('Content-Security-Policy',
                             csp_header_template.format(csp_nonce))
        return response

    # TODO use new typing feature to accurately define the following:
    # from typing import TypedDict
    # Attachment = TypedDict(
    #     "Attachment", {'path': PathLike, 'filename': str, 'mimetype': str,
    #                    'file': IO}, total=False)
    Attachment = Dict[str, str]

    def do_mail(self, rs: RequestState, templatename: str,
                headers: MutableMapping[str, Union[str, Collection[str]]],
                params: CdEDBObject = None,
                attachments: Collection[Attachment] = None) -> Optional[str]:
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        Some words about email trouble. Bounced mails go by default to a
        special address ``bounces@cde-ev.de``, which will be a list not
        managed via the DB. For mailinglists the return path will be a
        list specific bounce address which delivers the bounces to the
        moderators.

        :param headers: mandatory headers to supply are To and Subject
        :param attachments: Each dict describes one attachment. The possible
          keys are path (a ``str``), file (a file like), mimetype (a ``str``),
          filename (a ``str``).
        :returns: see :py:meth:`_send_mail` for details, we automatically
          store the path in ``rs``
        """
        params = params or {}
        params['headers'] = headers
        text = self.fill_template(rs, "mail", templatename, params)
        msg = self._create_mail(text, headers, attachments)
        ret = self._send_mail(msg)
        if ret:
            # This is mostly intended for the test suite.
            rs.notify("info", n_("Stored email to hard drive at %(path)s"),
                      {'path': ret})
        return ret

    def _create_mail(self, text: str,
                     headers: MutableMapping[str, Union[str, Collection[str]]],
                     attachments: Optional[Collection[Attachment]],
                     ) -> Union[email.message.Message,
                                email.mime.multipart.MIMEMultipart]:
        """Helper for actual email instantiation from a raw message."""
        defaults = {"From": self.conf["DEFAULT_SENDER"],
                    "Prefix": self.conf["DEFAULT_PREFIX"],
                    "Reply-To": self.conf["DEFAULT_REPLY_TO"],
                    "Return-Path": self.conf["DEFAULT_RETURN_PATH"],
                    "Cc": tuple(),
                    "Bcc": tuple(),
                    "domain": self.conf["MAIL_DOMAIN"],
                    }
        merge_dicts(headers, defaults)
        if headers["From"] == headers["Reply-To"]:
            del headers["Reply-To"]
        msg = email.mime.text.MIMEText(text)
        email.encoders.encode_quopri(msg)
        del msg['Content-Transfer-Encoding']
        msg['Content-Transfer-Encoding'] = 'quoted-printable'
        # we want quoted-printable, but without encoding all the spaces
        # however at the end of lines the standard requires spaces to be
        # encoded hence we have to be a bit careful (encoding is a pain!)
        # 'quoted-printable' ensures we only get str here:
        payload: str = msg.get_payload()
        payload = re.sub('=20(.)', r' \1', payload)
        # do this twice for adjacent encoded spaces
        payload = re.sub('=20(.)', r' \1', payload)
        msg.set_payload(payload)
        if attachments:
            container = email.mime.multipart.MIMEMultipart()
            container.attach(msg)
            for attachment in attachments:
                container.attach(self._create_attachment(attachment))
            # put the container in place as message to send
            msg = container  # type: ignore
        for header in ("To", "Cc", "Bcc"):
            nonempty = {x for x in headers[header] if x}
            if nonempty != set(headers[header]):
                self.logger.warning("Empty values zapped in email recipients.")
            if headers[header]:
                msg[header] = ", ".join(nonempty)
        for header in ("From", "Reply-To", "Return-Path"):
            msg[header] = headers[header]
        subject = headers["Prefix"] + " " + headers['Subject']  # type: ignore
        msg["Subject"] = subject
        msg["Message-ID"] = email.utils.make_msgid(
            domain=self.conf["MAIL_DOMAIN"])
        msg["Date"] = email.utils.format_datetime(now())
        return msg

    def generic_user_search(self, rs: RequestState, download: Optional[str],
                            is_search: bool, scope: query_mod.QueryScope,
                            default_scope: query_mod.QueryScope,
                            submit_general_query: Callable[[RequestState, Query],
                                                           Tuple[CdEDBObject, ...]], *,
                            endpoint: str = "user_search",
                            choices: Mapping[str, Mapping[Any, str]] = None,
                            query: Query = None) -> werkzeug.Response:
        """Perform user search.

        :param download: signals whether the output should be a file. It can either
            be "csv" or "json" for a corresponding file. Otherwise an ordinary HTML page
            is served.
        :param is_search: signals whether the page was requested by an actual
            query or just to display the search form.
        :param scope: The query scope of the search.
        :param default_scope: Use the default queries associated with this scope.
        :param endpoint: Name of the template family to use to render search. To be
            changed for archived user searches.
        :param choices: Mapping of replacements of primary keys by human-readable
            strings for select fields in the javascript query form.
        :param submit_general_query: The backend query function to use to retrieve the
            data in the end. Different backends apply different filters depending on
            `query.scope`, usually filtering out users with higher realms.
        :param query: if this is specified the query is executed instead. This is meant
            for calling this function programmatically.
        """
        spec = scope.get_spec()
        if query:
            query = check_validation(rs, vtypes.Query, query, "query")
            if query and query.scope != scope:
                raise ValueError(n_("Scope mismatch."))
        elif is_search:
            # mangle the input, so we can prefill the form
            query_input = scope.mangle_query_input(rs)
            query = check_validation(rs, vtypes.QueryInput, query_input, "query",
                                     spec=spec, allow_empty=False)
        default_queries = self.conf["DEFAULT_QUERIES"][default_scope]
        choices_lists = {}
        if choices is None:
            choices = {}
        for k, v in choices.items():
            choices_lists[k] = list(v.items())
            if query and k in query.spec:
                query.spec[k] = query.spec[k].replace_choices(v)
        params = {
            'spec': spec, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query, 'scope': scope,
            'ADMIN_KEYS': ADMIN_KEYS,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            result = submit_general_query(rs, query)
            params['result'] = result
            if download:
                return self.send_query_download(
                    rs, result, query, kind=download, filename=endpoint + "_result")
        else:
            rs.values['is_search'] = False
        return self.render(rs, endpoint, params)

    @staticmethod
    def _create_attachment(attachment: Attachment) -> MIMENonMultipart:
        """Helper instantiating an attachment via the email module.

        :param attachment: see :py:meth:`do_mail` for a description of keys
        """
        mimetype = attachment.get('mimetype') or 'application/octet-stream'
        maintype, subtype = mimetype.split('/', 1)
        if not attachment.get('file') and not attachment.get('path'):
            raise ValueError(n_("No input provided."))
        if attachment.get('file'):
            # noinspection PyUnresolvedReferences
            data = attachment['file'].read()  # type: ignore
        else:
            if maintype == "text":
                with open(attachment['path'], 'r') as ft:
                    data = ft.read()
            else:
                with open(attachment['path'], 'rb') as fb:
                    data = fb.read()
        # Only support common types
        factories = {
            'application': email.mime.application.MIMEApplication,
            'audio': email.mime.audio.MIMEAudio,
            'image': email.mime.image.MIMEImage,
            'text': email.mime.text.MIMEText,
        }
        ret = factories[maintype](data, _subtype=subtype)
        if attachment.get('filename'):
            ret.add_header('Content-Disposition', 'attachment',
                           filename=attachment['filename'])
        return ret

    def _send_mail(self, msg: email.message.Message) -> Optional[str]:
        """Helper for getting an email onto the wire.

        :returns: Name of the file the email was saved in -- however this
          happens only in development mode. This is intended for consumption
          by the test suite.
        """
        ret = None
        if not msg["To"] and not msg["Cc"] and not msg["Bcc"]:
            self.logger.warning("No recipients for mail. Dropping it.")
            return None
        if not self.conf["CDEDB_DEV"]:  # pragma: no cover
            s = smtplib.SMTP(self.conf["MAIL_HOST"])
            s.send_message(msg)
            s.quit()
        else:
            with tempfile.NamedTemporaryFile(mode='w', prefix="cdedb-mail-",
                                             suffix=".txt", delete=False) as f:
                f.write(str(msg))
                self.logger.debug(f"Stored mail to {f.name}.")
                ret = f.name
        self.logger.info(f"Sent email with subject '{msg['Subject']}' to '{msg['To']}'")
        return ret

    def redirect_show_user(self, rs: RequestState, persona_id: int,
                           quote_me: bool = None) -> werkzeug.Response:
        """Convenience function to redirect to a user detail page.

        The point is, that encoding the ``confirm_id`` parameter is
        somewhat lengthy and only necessary because of our paranoia.
        """
        cid = self.encode_parameter(
            "core/show_user", "confirm_id", str(persona_id),
            persona_id=rs.user.persona_id, timeout=None)
        params = {'confirm_id': cid, 'persona_id': persona_id}
        if quote_me is not None:
            params['quote_me'] = True
        return self.redirect(rs, 'core/show_user', params=params)

    @staticmethod
    def notify_return_code(rs: RequestState, code: Union[int, bool, None],
                           success: str = n_("Change committed."),
                           info: str = n_("Change pending."),
                           error: str = n_("Change failed.")) -> None:
        """Small helper to issue a notification based on a return code.

        We allow some flexibility in what type of return code we accept. It
        may be a boolean (with the obvious meanings), an integer (specifying
        the number of changed entries, and negative numbers for entries with
        pending review) or None (signalling failure to acquire something).

        :param success: Affirmative message for positive return codes.
        :param info: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            rs.notify("error", error)
        elif code is True or code > 0:
            rs.notify("success", success)
        elif code < 0:
            rs.notify("info", info)
        else:
            raise RuntimeError(n_("Impossible."))

    def safe_compile(self, rs: RequestState, target_file: str, cwd: PathLike,
                     runs: int, errormsg: Optional[str]) -> pathlib.Path:
        """Helper to compile latex documents in a safe way.

        This catches exepctions during compilation and displays a more helpful
        error message instead.

        :param target_file: name of the file to compile.
        :param cwd: Path of the target file.
        :param runs: number of times LaTeX is run (for references etc.)
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :returns: Path to the compiled pdf.
        """
        if target_file.endswith('.tex'):
            pdf_file = "{}.pdf".format(target_file[:-4])
        else:
            pdf_file = "{}.pdf".format(target_file)
        pdf_path = pathlib.Path(cwd, pdf_file)

        args = ("lualatex", "-interaction", "batchmode", target_file)
        self.logger.info(f"Invoking {args}")
        try:
            for _ in range(runs):
                subprocess.run(args, cwd=cwd, check=True,
                               stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            if pdf_path.exists():
                self.logger.debug(f"Deleting corrupted file {pdf_path}")
                pdf_path.unlink()
            self.logger.debug(f"Exception \"{e}\" caught and handled.")
            if self.conf["CDEDB_DEV"]:
                tstamp = round(now().timestamp())
                backup_path = "/tmp/cdedb-latex-error-{}.tex".format(tstamp)
                self.logger.info(f"Copying source file to {backup_path}")
                shutil.copy2(target_file, backup_path)
            errormsg = errormsg or n_(
                "LaTeX compilation failed. Try downloading the "
                "source files and compiling them manually.")
            rs.notify("error", errormsg)
        return pdf_path

    def latex_compile(self, rs: RequestState, data: str, runs: int = 2,
                      errormsg: str = None) -> Optional[bytes]:
        """Run LaTeX on the provided document.

        This takes care of the necessary temporary files.

        :param runs: number of times LaTeX is run (for references etc.)
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :returns: the compiled document as blob
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_file:
                tmp_file.write(data.encode('utf8'))
                tmp_file.flush()
                path = self.safe_compile(
                    rs, tmp_file.name, tmp_dir, runs=runs, errormsg=errormsg)
                if path.exists():
                    # noinspection PyTypeChecker
                    with open(path, 'rb') as pdf:
                        return pdf.read()
                else:
                    return None

    def serve_latex_document(self, rs: RequestState, data: str, filename: str,
                             runs: int = 2, errormsg: str = None
                             ) -> Optional[Response]:
        """Generate a response from a LaTeX document.

        This takes care of the necessary temporary files.

        :param data: the LaTeX document
        :param filename: name to serve the document as, without extension
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled pdf.
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        """
        if not runs:
            return self.send_file(
                rs, data=data, inline=False,
                filename="{}.tex".format(filename))
        else:
            pdf = self.latex_compile(rs, data, runs=runs, errormsg=errormsg)
            if not pdf:
                return None
            return self.send_file(
                rs, mimetype="application/pdf", data=pdf,
                filename="{}.pdf".format(filename))

    def serve_complex_latex_document(self, rs: RequestState,
                                     tmp_dir: Union[str, pathlib.Path],
                                     work_dir_name: str, tex_file_name: str,
                                     runs: int = 2, errormsg: str = None
                                     ) -> Optional[Response]:
        """Generate a response from a LaTeX document.

        In contrast to :py:meth:`serve_latex_document` this expects that the
        caller takes care of creating a temporary directory and doing the
        setup. Actually this is only usefull if the caller does some
        additional setup (like providing image files).

        Everything has to happen inside a working directory, so the layout
        is as follows::

            tmp_dir
            +------ work_dir
                    |------- tex_file.tex
                    +------- ...

        :param tmp_dir: path of temporary directory
        :param work_dir_name: name of working directory inside temporary
          directory.
        :param tex_file_name: name of the tex file (including extension),
          this will be used to derived the name to use when serving the
          compiled pdf file.
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled
          pdf. More specifically we serve a gzipped tar archive containing
          the working directory.
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        """
        if not runs:
            target = pathlib.Path(tmp_dir, work_dir_name)
            archive = shutil.make_archive(
                str(target), "gztar", base_dir=work_dir_name, root_dir=tmp_dir,
                logger=self.logger)
            if tex_file_name.endswith('.tex'):
                tex_file = "{}.tar.gz".format(tex_file_name[:-4])
            else:
                tex_file = "{}.tar.gz".format(tex_file_name)
            return self.send_file(
                rs, path=archive, inline=False,
                filename=tex_file)
        else:
            work_dir = pathlib.Path(tmp_dir, work_dir_name)
            if tex_file_name.endswith('.tex'):
                pdf_file = "{}.pdf".format(tex_file_name[:-4])
            else:
                pdf_file = "{}.pdf".format(tex_file_name)
            path = self.safe_compile(
                rs, tex_file_name, cwd=work_dir, runs=runs,
                errormsg=errormsg)
            if path.exists():
                return self.send_file(
                    rs, mimetype="application/pdf",
                    path=(work_dir / pdf_file),
                    filename=pdf_file)
            else:
                return None

    def check_anti_csrf(self, rs: RequestState, action: str,
                        token_name: str, token_payload: str) -> Optional[str]:
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
        :param token_name: The name of the anti CSRF token.
        :param token_payload: The expected payload of the anti CSRF token.
        :return: None if everything is ok, or an error message otherwise.
        """
        val = rs.request.values.get(token_name, "").strip()
        if not val:
            return n_("Anti CSRF token is required for this form.")
        # noinspection PyProtectedMember
        timeout, val = self.decode_parameter(
            f"{self.realm}/{action}", token_name, val, rs.user.persona_id)
        if not val:
            if timeout:
                return n_("Anti CSRF token expired. Please try again.")
            else:
                return n_("Anti CSRF token is forged.")
        if val != token_payload:
            return n_("Anti CSRF token is invalid.")
        return None


class AbstractUserFrontend(AbstractFrontend, metaclass=abc.ABCMeta):
    """Base class for all frontends which have their own user realm.

    This is basically every frontend with exception of 'core'.
    """

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    # @access("realm_admin")
    @abc.abstractmethod
    def create_user_form(self, rs: RequestState) -> werkzeug.Response:
        """Render form."""
        return self.render(rs, "create_user")

    # @access("realm_admin", modi={"POST"})
    # @REQUESTdatadict(...)
    @abc.abstractmethod
    def create_user(self, rs: RequestState, data: CdEDBObject) -> werkzeug.Response:
        """Create new user account."""
        merge_dicts(data, PERSONA_DEFAULTS)
        data = check_validation(rs, vtypes.Persona, data, creation=True)
        if data:
            exists = self.coreproxy.verify_existence(rs, data['username'])
            if exists:
                rs.extend_validation_errors(
                    (("username",
                      ValueError("User with this E-Mail exists already.")),))
        if rs.has_validation_errors() or not data:
            return self.create_user_form(rs)
        new_id = self.coreproxy.create_persona(rs, data)
        if new_id:
            success, message = self.coreproxy.make_reset_cookie(rs, data[
                'username'])
            email = self.encode_parameter(
                "core/do_password_reset_form", "email", data['username'],
                persona_id=None, timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            meta_info = self.coreproxy.get_meta_info(rs)
            self.do_mail(rs, "welcome",
                         {'To': (data['username'],),
                          'Subject': "CdEDB Account erstellt",
                          },
                         {'data': data,
                          'fee': self.conf["MEMBERSHIP_FEE"],
                          'email': email if success else "",
                          'cookie': message if success else "",
                          'meta_info': meta_info,
                          })

            self.notify_return_code(rs, new_id, success=n_("User created."))
            return self.redirect_show_user(rs, new_id)
        else:
            return self.create_user_form(rs)


class CdEMailmanClient(mailmanclient.Client):
    """Custom wrapper around mailmanclient.Client.

    This custom wrapper provides additional functionality needed in multiple frontends.
    Whenever access to the mailman server is needed, this class should be used.
    """
    def __init__(self, conf: Config, mailman_password: str,
                 mailman_basic_auth_password: str):
        """Automatically initializes a client with our custom parameters.

        :param conf: Usually, he config used where this class is instantiated.
        """
        self.conf = conf

        # Initialize base class
        url = f"http://{self.conf['MAILMAN_HOST']}/3.1"
        super().__init__(url, self.conf["MAILMAN_USER"], mailman_password)
        self.template_password = mailman_basic_auth_password

        # Initialize logger. This needs the base class initialization to be done.
        logger_name = "cdedb.frontend.mailmanclient"
        make_root_logger(
            logger_name, self.conf["MAILMAN_LOG"], self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.logger = logging.getLogger(logger_name)
        self.logger.debug(f"Instantiated {self} with configpath {conf._configpath}.")

    def get_list_safe(self, address: str) -> Optional[
            mailmanclient.restobjects.mailinglist.MailingList]:
        """Return list with standard error handling.

        In contrast to the original function, this does not raise if no list has been
        found, but returns None instead. This is particularly important since list
        creation and deletion are not synced immediately."""
        try:
            return self.get_list(address)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            else:
                raise

    def get_held_messages(self, dblist: CdEDBObject) -> Optional[
            List[mailmanclient.restobjects.held_message.HeldMessage]]:
        """Returns all held messages for mailman lists.

        If the list is not managed by mailman, this function returns None instead.
        """
        if self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or self.conf["CDEDB_DEV"]:
            self.logger.info("Skipping mailman query in dev/offline mode.")
            if self.conf["CDEDB_DEV"]:
                # Some diversity regarding moderation.
                if dblist['id'] % 2 == 0:
                    return HELD_MESSAGE_SAMPLE
                else:
                    return []
            return None
        else:
            mmlist = self.get_list_safe(dblist['address'])
            return mmlist.held if mmlist else None


# Type Aliases for the Worker class.
WorkerTarget = Callable[[RequestState], bool]
WorkerTasks = Union[WorkerTarget, Sequence[WorkerTarget]]


class WorkerTaskInfo(NamedTuple):
    task: WorkerTarget
    name: str
    doc: str


class Worker(threading.Thread):
    """Customization wrapper around ``threading.Thread``.

    This takes care of initializing a new (basically cloned) request
    state object, containing a separate database connection, so that
    concurrency is no concern.
    """

    # For details about this class variable dict see `Worker.create()`.
    active_workers: ClassVar[Dict[str, "weakref.ReferenceType[Worker]"]] = {}

    def __init__(self, conf: Config, tasks: WorkerTasks, rs: RequestState) -> None:
        """
        :param tasks: Every task will be called with the cloned request state as a
            single argument.
        """
        # noinspection PyProtectedMember
        rrs = RequestState(
            sessionkey=rs.sessionkey, apitoken=rs.apitoken, user=rs.user,
            request=rs.request, notifications=[], mapadapter=rs.urls,
            requestargs=rs.requestargs, errors=[], values=copy.deepcopy(rs.values),
            begin=rs.begin, lang=rs.lang, translations=rs.translations)
        # noinspection PyProtectedMember
        secrets = SecretsConfig(conf._configpath)
        connpool = connection_pool_factory(
            conf["CDB_DATABASE_NAME"], DATABASE_ROLES, secrets, conf["DB_PORT"])
        rrs._conn = connpool[roles_to_db_role(rs.user.roles)]
        logger = logging.getLogger("cdedb.frontend.worker")

        def get_doc(task: WorkerTarget) -> str:
            return task.__doc__.splitlines()[0] if task.__doc__ else ""

        if isinstance(tasks, Sequence):
            task_infos = [WorkerTaskInfo(t, t.__name__, get_doc(t)) for t in tasks]
        else:
            task_infos = [WorkerTaskInfo(tasks, tasks.__name__, get_doc(tasks))]

        def runner() -> None:
            """Implement the actual loop running the task inside the Thread."""
            if len(task_infos) > 1:
                task_queue = "\n".join(f"'{n}': {doc}" for _, n, doc in task_infos)
                logger.debug(f"Worker queue started:\n{task_queue}")
            p_id = rrs.user.persona_id if rrs.user else None
            username = rrs.user.username if rrs.user else None
            for i, task_info in enumerate(task_infos):
                logger.debug(
                    f"Task `{task_info.name}`{task_info.doc} started by user"
                    f" {p_id} ({username}).")
                count = 0
                while True:
                    try:
                        count += 1
                        if not task_info.task(rrs):
                            logger.debug(
                                f"Finished task `{task_info.name}` successfully"
                                f" after {count} iterations.")
                            break
                    except Exception as e:
                        logger.exception(
                            f"The following error occurred during the {count}th"
                            f" iteration of `{task_info.name}: {e}")
                        logger.debug(f"Task {task_info.name} aborted.")
                        remaining_tasks = task_infos[i+1:]
                        if remaining_tasks:
                            logger.error(
                                f"{len(remaining_tasks)} remaining tasks aborted:"
                                f" {', '.join(n for _, n, _ in remaining_tasks)}")
                        raise
            if len(task_infos) > 1:
                logger.debug(f"{len(task_infos)} tasks completed successfully.")

        super().__init__(target=runner, daemon=False)

    @classmethod
    def create(cls, rs: RequestState, name: str, tasks: "WorkerTasks",
               conf: Config, timeout: Optional[float] = 0.1) -> "Worker":
        """Create a new Worker, remember and start it.

        The state of the `cls.active_workers` dict is not shared between the threads of
        a multithreaded instance of the application. Thus it should not be relied upon
        for anything other than testing purposes.

        In order to not mess with garbage collection of finished workers, we only keep
        a weak reference to the instance. This means that the weakref object needs to
        be called. If it returns `None`, the referenced object has already been garbage
        collected. Otherwise it will return the `Worker` instance which can then be
        joined. Workers will automatically be garbaage collected once they finish
        execution unless a reference is specifically kept somewhere.

        Note the pattern of assigning the result of this call first, because otherwise
        there is a race condition between checking for truthyness and calling the
        `is_alive` method where the Worker could finish in the meantime.

        :param timeout: If this is not None, wait for the given number of seconds for
            the worker thread to finish.
        """
        if name in cls.active_workers:
            # Dereference the weakref.
            old_worker = cls.active_workers[name]()
            if old_worker and old_worker.is_alive():
                raise RuntimeError("Worker already active.")
        worker = cls(conf, tasks, rs)
        cls.active_workers[name] = weakref.ref(worker)
        worker.start()
        if timeout is not None:
            worker.join(timeout)
        return worker


def reconnoitre_ambience(obj: AbstractFrontend,
                         rs: RequestState) -> Dict[str, CdEDBObject]:
    """Provide automatic lookup of objects in a standard way.

    This creates an ambience dict providing objects for all ids passed
    as part of the URL path. The naming is not predetermined, but as a
    convention the object name should be the parameter named minus the
    '_id' suffix.
    """
    Scout = collections.namedtuple('Scout', ('getter', 'param_name',
                                             'object_name', 'dependencies'))

    def do_assert(x: bool) -> None:
        if not x:
            raise werkzeug.exceptions.BadRequest(
                rs.gettext("Inconsistent request."))

    scouts = (
        Scout(lambda anid: obj.coreproxy.get_persona(rs, anid), 'persona_id',
              'persona', ()),
        Scout(lambda anid: obj.coreproxy.get_privilege_change(rs, anid),
              'privilege_change_id', 'privilege_change', ()),
        Scout(lambda anid: obj.coreproxy.genesis_get_case(rs, anid),
              'genesis_case_id', 'genesis_case', ()),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift(rs, anid),
              'lastschrift_id', 'lastschrift', ()),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift_transaction(rs, anid),
              'transaction_id', 'transaction',
              ((lambda a: do_assert(a['transaction']['lastschrift_id']
                                    == a['lastschrift']['id'])),)),
        Scout(lambda anid: obj.pasteventproxy.get_institution(rs, anid),
              'institution_id', 'institution', ()),
        Scout(lambda anid: obj.eventproxy.get_event(rs, anid),
              'event_id', 'event', ()),
        Scout(lambda anid: obj.pasteventproxy.get_past_event(rs, anid),
              'pevent_id', 'pevent', ()),
        Scout(lambda anid: obj.eventproxy.get_course(rs, anid),
              'course_id', 'course',
              ((lambda a: do_assert(a['course']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.pasteventproxy.get_past_course(rs, anid),
              'pcourse_id', 'pcourse',
              ((lambda a: do_assert(a['pcourse']['pevent_id']
                                    == a['pevent']['id'])),)),
        Scout(None, 'part_id', None,
              ((lambda a: do_assert(rs.requestargs['part_id']
                                    in a['event']['parts'])),)),
        Scout(lambda anid: obj.eventproxy.get_registration(rs, anid),
              'registration_id', 'registration',
              ((lambda a: do_assert(a['registration']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_lodgement_group(rs, anid),
              'group_id', 'group',
              ((lambda a: do_assert(a['group']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_lodgement(rs, anid),
              'lodgement_id', 'lodgement',
              ((lambda a: do_assert(a['lodgement']['event_id']
                                    == a['event']['id'])),)),
        Scout(None, 'field_id', None,
              ((lambda a: do_assert(rs.requestargs['field_id']
                                    in a['event']['fields'])),)),
        Scout(lambda anid: obj.assemblyproxy.get_attachment(rs, anid),
              'attachment_id', 'attachment',
              ((lambda a: do_assert(a['attachment']['assembly_id']
                                    == rs.requestargs['assembly_id'])),)),
        Scout(lambda anid: obj.assemblyproxy.get_assembly(rs, anid),
              'assembly_id', 'assembly', ()),
        Scout(lambda anid: obj.assemblyproxy.get_ballot(rs, anid),
              'ballot_id', 'ballot',
              ((lambda a: do_assert(a['ballot']['assembly_id']
                                    == a['assembly']['id'])),)),
        Scout(None, 'candidate_id', None,
              ((lambda a: do_assert(rs.requestargs['candidate_id']
                                    in a['ballot']['candidates'])),)),
        Scout(lambda anid: obj.mlproxy.get_mailinglist(rs, anid),
              'mailinglist_id', 'mailinglist', ()),
    )
    scouts_dict = {s.param_name: s for s in scouts}
    ambience = {}
    for param, value in rs.requestargs.items():
        s = scouts_dict.get(param)
        if s and s.getter:
            try:
                ambience[s.object_name] = s.getter(value)
            except KeyError:
                raise werkzeug.exceptions.NotFound(
                    rs.gettext("Object {param}={value} not found").format(
                        param=param, value=value)) from None
            except PrivilegeError as e:
                if not obj.conf['CDEDB_DEV']:
                    msg = "Not privileged to view object {param}={value}: {exc}"
                    raise werkzeug.exceptions.Forbidden(
                        rs.gettext(msg).format(param=param, value=value, exc=str(e)))
                else:
                    raise
    for param, value in rs.requestargs.items():
        if param in scouts_dict:
            for consistency_checker in scouts_dict[param].dependencies:
                consistency_checker(ambience)
    return ambience


F = TypeVar('F', bound=Callable[..., Any])
AntiCSRFMarker = NamedTuple(
    "AntiCSRFMarker", (("check", bool), ("name", str), ("payload", str)))


class FrontendEndpoint(Protocol):
    access_list: AbstractSet[Role]
    anti_csrf: AntiCSRFMarker
    modi: AbstractSet[str]

    def __call__(self, rs: RequestState, *args: Any, **kwargs: Any
                 ) -> werkzeug.Response: ...


def access(*roles: Role, modi: AbstractSet[str] = frozenset(("GET", "HEAD")),
           check_anti_csrf: bool = None, anti_csrf_token_name: str = None,
           anti_csrf_token_payload: str = None) -> Callable[[F], F]:
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :param roles: privilege required (any of the passed)
    :param modi: HTTP methods allowed for this invocation
    :param check_anti_csrf: Control if the anti csrf check should be enabled
        on this endpoint. If not specified, it will be enabled, if "POST" is in
        the allowed methods.
    :param anti_csrf_token_name: If given, use this as the name of the anti csrf token.
        Otherwise a sensible default will be used.
    :param anti_csrf_token_payload: If given, use this as the payload of the anti csrf
        token. Otherwise a sensible default will be used.
    """
    access_list = set(roles)

    def decorator(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> werkzeug.Response:
            if rs.user.roles & access_list:
                rs.ambience = reconnoitre_ambience(obj, rs)
                return fun(obj, rs, *args, **kwargs)
            else:
                expects_persona = any('droid' not in role
                                      for role in access_list)
                if rs.user.roles == {"anonymous"} and expects_persona:
                    # Validation errors do not matter on session expiration,
                    # since we redirect to get anyway.
                    # In practice, this is mostly relevant for the anti csrf error.
                    rs.ignore_validation_errors()
                    params = {
                        'wants': obj.encode_parameter(
                            "core/index", "wants", rs.request.url,
                            persona_id=rs.user.persona_id,
                            timeout=obj.conf["UNCRITICAL_PARAMETER_TIMEOUT"])
                    }
                    ret = basic_redirect(rs, cdedburl(rs, "core/index", params))
                    # noinspection PyProtectedMember
                    notifications = json_serialize([
                        obj.encode_notification(
                            rs, "error", n_("You must login."))])
                    ret.set_cookie("displaynote", notifications)
                    return ret
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("Access denied to {realm}/{endpoint}.").format(
                        realm=obj.__class__.__name__, endpoint=fun.__name__))

        new_fun.access_list = access_list  # type: ignore[attr-defined]
        new_fun.modi = modi  # type: ignore[attr-defined]
        new_fun.anti_csrf = AntiCSRFMarker(  # type: ignore[attr-defined]
            check_anti_csrf if check_anti_csrf is not None
            else not modi <= {'GET', 'HEAD'} and "anonymous" not in roles,
            anti_csrf_token_name or ANTI_CSRF_TOKEN_NAME,
            anti_csrf_token_payload or ANTI_CSRF_TOKEN_PAYLOAD,
        )

        return cast(F, new_fun)

    return decorator


def cdedburl(rs: RequestState, endpoint: str,
             params: Union[CdEDBObject, CdEDBMultiDict] = None,
             force_external: bool = False,
             magic_placeholders: Collection[str] = None) -> str:
    """Construct an HTTP URL.

    :param endpoint: as defined in :py:data:`cdedb.frontend.paths.CDEDB_PATHS`
    :param magic_placeholders: These are parameter names which behave as if
      the following code would be executed::

          for i, name in enumerate(magic_placeholders):
              params[name] = "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i)

      The use case is that we want to generate string templates of URLs for
      consumption by Javascript code with the possibility of inserting some
      parameters at execution time.
    """
    params = params or {}
    # First handle magic placeholders, this is kind of a hack, but sadly
    # necessary
    if magic_placeholders:
        newparams = copy.deepcopy(params)
        for run in range(1, 10):
            for i, name in enumerate(magic_placeholders):
                # Generate a hopefully unique integer to replace
                newparams[name] = (
                        i * 10 ** (9 * run + 1)
                        + 123456789 * sum(10 ** (9 * j) for j in range(run)))
            attempt = cdedburl(rs, endpoint, newparams,
                               force_external=force_external)
            if any(attempt.count(str(newparams[name])) != 1
                   for name in magic_placeholders):
                continue
            else:
                for i, name in enumerate(magic_placeholders):
                    attempt = attempt.replace(
                        str(newparams[name]),
                        "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i))
                if any(attempt.count(
                        "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i)) != 1
                       for i in range(len(magic_placeholders))):
                    continue
                return attempt
        raise RuntimeError(n_("Magic URL parameter replacement failed."))
    # Second we come to the normal case
    allparams: CdEDBMultiDict = werkzeug.datastructures.MultiDict()
    for arg in rs.requestargs:
        if rs.urls.map.is_endpoint_expecting(endpoint, arg):
            allparams[arg] = rs.requestargs[arg]
    if isinstance(params, werkzeug.datastructures.MultiDict):
        for key in params:
            allparams.setlist(key, params.getlist(key))
    else:
        for key in params:
            allparams[key] = params[key]

    return rs.urls.build(endpoint, allparams, force_external=force_external)


def staticurl(path: str, version: str = "") -> str:
    """Construct an HTTP URL to a static resource (to be found in the static directory).

    We encapsulate this here so moving the directory around causes no pain.

    :param version: If not None, this string is appended to the URL as an URL
        parameter. This can be used to force Browsers to flush their caches on
        code updates.
    """
    ret = str(pathlib.PurePosixPath("/static", path))
    if version:
        ret += '?v=' + version
    return ret


@overload
def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: Literal[True] = True) -> markupsafe.Markup: ...


@overload
def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: Literal[False] = False) -> str: ...


def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: bool = True) -> Union[markupsafe.Markup, str]:
    """Create a link to a static resource.

    This can either create a basic html link or a fully qualified, static https link.

    .. note:: This will be overridden by _staticlink in templates, see fill_template.
    """
    link: Union[markupsafe.Markup, str]
    if html:
        return safe_filter(f'<a href="{staticurl(path, version=version)}">{label}</a>')
    else:
        host = rs.urls.get_host("")
        return f"https://{host}{staticurl(path, version=version)}"


def docurl(topic: str, anchor: str = "") -> str:
    """Construct an HTTP URL to a doc page."""
    ret = str(pathlib.PurePosixPath("/doc", topic + ".html"))
    if anchor:
        ret += "#" + anchor
    return ret


@overload
def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: Literal[True] = True) -> markupsafe.Markup: ...


@overload
def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: Literal[False] = False) -> str: ...


def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: bool = True) -> Union[markupsafe.Markup, str]:
    """Create a link to our documentation.

    This can either create a basic html link or a fully qualified, static https link.
    .. note:: This will be overridden by _doclink in templates, see fill_template.
    """
    link: Union[markupsafe.Markup, str]
    if html:
        return safe_filter(f'<a href="{docurl(topic, anchor=anchor)}">{label}</a>')
    else:
        host = rs.urls.get_host("")
        return f"https://{host}{docurl(topic, anchor=anchor)}"


# noinspection PyPep8Naming
def REQUESTdata(
    *spec: str, _hints: vtypes.TypeMapping = None, _postpone_validation: bool = False
) -> Callable[[F], F]:
    """Decorator to extract parameters from requests and validate them.

    This should always be used, so automatic form filling works as expected.
    The decorator should be the innermost one
    as it needs access to the original "__defaults__" attribute
    to correctly determine types (e.g. "foo: str = None" -> "Optional[str]").
    Alternatively "functools.wraps" can be invoked in a way
    which also updates this attribute if the signature allows this.

    :param spec: Names of the parameters to extract.
        The type of the parameter will be dynamically extracted
        from the type annotations of the decorated function.
        Permitted types are the ones registered in :py:mod:`cdedb.validation`.
        This includes all types from :py:mod:`cdedb.validationtypes`
        as well as some native python types (primitives, datetimes, decimals).
        Additonally the generic types ``Optional[T]`` and ``Collection[T]``
        are valid as a type.
        To extract an encoded parameter one may prepended the name of it
        with an octothorpe (``#``).
    :param _postpone_validation: Whether or not validation should be applied inside.
        This should be used rarely, but sometimes its necessary.
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            hints = _hints or typing.get_type_hints(fun)
            for item in spec:
                if item.startswith('#'):
                    name = item[1:]
                    encoded = True
                else:
                    name = item
                    encoded = False

                if name not in kwargs:

                    if typing.get_origin(hints[name]) is Union:
                        type_, _ = hints[name].__args__
                        optional = True
                    else:
                        type_ = hints[name]
                        optional = False

                    val = rs.request.values.get(name, "")

                    # TODO allow encoded collections?
                    if encoded and val:
                        # only decode if exists
                        # noinspection PyProtectedMember
                        timeout, val = obj.decode_parameter(
                            f"{obj.realm}/{fun.__name__}",
                            name, val, persona_id=rs.user.persona_id)
                        if timeout is True:
                            rs.notify("warning", n_("Link expired."))
                        if timeout is False:
                            rs.notify("warning", n_("Link invalid."))

                    if typing.get_origin(type_) is collections.abc.Collection:
                        type_ = unwrap(type_.__args__)
                        vals = tuple(rs.request.values.getlist(name))
                        if vals:
                            rs.values.setlist(name, vals)
                        else:
                            # TODO should also work normally
                            # We have to be careful, since empty lists are
                            # problematic for the werkzeug MultiDict
                            rs.values[name] = None
                        if _postpone_validation:
                            kwargs[name] = tuple(vals)
                        elif optional:
                            kwargs[name] = tuple(
                                check_validation_optional(rs, type_, val, name)
                                for val in vals
                            )
                        else:
                            kwargs[name] = tuple(
                                check_validation(rs, type_, val, name)
                                for val in vals
                            )
                    else:
                        rs.values[name] = val
                        if _postpone_validation:
                            kwargs[name] = val
                        elif optional:
                            kwargs[name] = check_validation_optional(
                                rs, type_, val, name)
                        else:
                            kwargs[name] = check_validation(
                                rs, type_, val, name)
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


# noinspection PyPep8Naming
def REQUESTdatadict(*proto_spec: Union[str, Tuple[str, str]]
                    ) -> Callable[[F], F]:
    """Similar to :py:meth:`REQUESTdata`, but doesn't hand down the
    parameters as keyword-arguments, instead packs them all into a dict and
    passes this as ``data`` parameter. This does not do validation since
    this is infeasible in practice.

    :param proto_spec: Similar to ``spec`` parameter :py:meth:`REQUESTdata`,
      but the only two allowed argument types are ``str`` and
      ``[str]``. Additionally the argument type may be omitted and a default
      of ``str`` is assumed.
    """
    spec = []
    for arg in proto_spec:
        if isinstance(arg, str):
            spec.append((arg, "str"))
        else:
            spec.append(arg)

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            data = {}
            for name, argtype in spec:
                if argtype == "str":
                    data[name] = rs.request.values.get(name, "")
                elif argtype == "[str]":
                    data[name] = tuple(rs.request.values.getlist(name))
                else:
                    raise ValueError(n_("Invalid argtype {t} found.").format(
                        t=repr(argtype)))
                rs.values[name] = data[name]
            return fun(obj, rs, *args, data=data, **kwargs)

        return cast(F, new_fun)

    return wrap


RequestConstraint = Tuple[Callable[[CdEDBObject], bool], Error]


def request_extractor(
        rs: RequestState, spec: vtypes.TypeMapping,
        constraints: Collection[RequestConstraint] = None,
        postpone_validation: bool = False) -> CdEDBObject:
    """Utility to apply REQUESTdata later than usual.

    This is intended to bu used, when the parameter list is not known before
    hand. Prime example are the event specific fields of event
    registrations, here the parameter list has to be constructed from data
    retrieved from the backend.

    Sometimes there are interdependencies between the individual
    attributes of the input. It would be best to have them caught by
    the original validators. However these are not easily usable in
    the flexible input setting this function is designed for. So
    instead of a complete rebuild of the validators we add the
    ``constraints`` parameter to perform these checks here. It is a
    list of callables that perform a check and associated errors that
    are reported if the check fails.

    :param spec: handed through to the decorator
    :param constraints: additional constraints that shoud produce
      validation errors
    :param postpone_validation: handed through to the decorator
    :returns: dict containing the requested values
    """
    @REQUESTdata(*spec, _hints=spec, _postpone_validation=postpone_validation)
    def fun(_: None, rs: RequestState, **kwargs: Any) -> CdEDBObject:
        if not rs.has_validation_errors():
            for checker, error in constraints or []:
                if not checker(kwargs):
                    rs.append_validation_error(error)
        return kwargs

    return fun(None, rs)


def request_dict_extractor(rs: RequestState,
                           args: Collection[str]) -> CdEDBObject:
    """Utility to apply REQUESTdatadict later than usual.

    Like :py:meth:`request_extractor`.

    :param args: handed through to the decorator
    :returns: dict containing the requested values
    """

    @REQUESTdatadict(*args)
    def fun(_: None, rs: RequestState, data: CdEDBObject) -> CdEDBObject:
        return data

    # This looks wrong. but is correct, as the `REQUESTdatadict` decorator
    # constructs the data parameter `fun` expects.
    return fun(None, rs)  # type: ignore


# noinspection PyPep8Naming
def REQUESTfile(*args: str) -> Callable[[F], F]:
    """Decorator to extract file uploads from requests.

    :param args: Names of file parameters.
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args2: Any,
                    **kwargs: Any) -> Any:
            for name in args:
                if name not in kwargs:
                    kwargs[name] = rs.request.files.get(name, None)
                rs.values[name] = kwargs[name]
            return fun(obj, rs, *args2, **kwargs)

        return cast(F, new_fun)

    return wrap


def event_guard(argname: str = "event_id",
                check_offline: bool = False) -> Callable[[F], F]:
    """This decorator checks the access with respect to a specific event. The
    event is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    The event has to be organized via the DB. Only orgas and privileged
    users are admitted. Additionally this can check for the offline
    lock, so that no modifications happen to locked events.

    :param argname: name of the keyword argument specifying the id
    :param check_offline: defaults to False
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if argname in kwargs:  # pylint: disable=consider-using-get
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.orga and not obj.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("This page can only be accessed by orgas."))
            if check_offline:
                is_locked = obj.eventproxy.is_offline_locked(rs, event_id=arg)
                if is_locked != obj.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                    raise werkzeug.exceptions.Forbidden(
                        rs.gettext("This event is locked for offline usage."))
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


def mailinglist_guard(argname: str = "mailinglist_id",
                      allow_moderators: bool = True,
                      requires_privilege: bool = False) -> Callable[[F], F]:
    """This decorator checks the access with respect to a specific
    mailinglist. The list is specified by id which has either to be a
    keyword parameter or the first positional parameter after the
    request state.

    If `allow_moderators` is True, moderators of the mailinglist are allowed,
    otherwise we require a relevant admin for the given mailinglist.

    :param argname: name of the keyword argument specifying the id
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if argname in kwargs:  # pylint: disable=consider-using-get
                arg = kwargs[argname]
            else:
                arg = args[0]
            if allow_moderators:
                if not obj.mlproxy.may_manage(rs, **{argname: arg}):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "This page can only be accessed by the mailinglist’s "
                        "moderators."))
                if requires_privilege and not obj.mlproxy.may_manage(
                        rs, mailinglist_id=arg, allow_restricted=False):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "You only have restricted moderator access and may not"
                        " change subscriptions."))
            else:
                if not obj.mlproxy.is_relevant_admin(rs, **{argname: arg}):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "This page can only be accessed by appropriate "
                        "admins."))
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


def assembly_guard(fun: F) -> F:
    """This decorator checks that the user has privileged access to an assembly.
    """

    @functools.wraps(fun)
    def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                **kwargs: Any) -> Any:
        if "assembly_id" in kwargs:  # pylint: disable=consider-using-get
            assembly_id = kwargs["assembly_id"]
        else:
            assembly_id = args[0]
        if not obj.assemblyproxy.is_presider(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(rs.gettext(
                "This page may only be accessed by the assembly's"
                " presiders or assembly admins."))
        return fun(obj, rs, *args, **kwargs)

    return cast(F, new_fun)


def check_validation(rs: RequestState, type_: Type[T], value: Any,
                     name: str = None, **kwargs: Any) -> Optional[T]:
    """Wrapper to call checks in :py:mod:`cdedb.validation`.

    This performs the check and appends all occurred errors to the RequestState.
    This also ignores warnings appropriately due to rs.ignore_warnings.

    :param type_: type to check for
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    """
    if name is not None:
        ret, errs = validate.validate_check(
            type_, value, ignore_warnings=rs.ignore_warnings, argname=name, **kwargs)
    else:
        ret, errs = validate.validate_check(
            type_, value, ignore_warnings=rs.ignore_warnings, **kwargs)
    rs.extend_validation_errors(errs)
    return ret


def check_validation_optional(rs: RequestState, type_: Type[T], value: Any,
                              name: str = None, **kwargs: Any) -> Optional[T]:
    """Wrapper to call checks in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.frontend.common.check_validation`
    but also allows optional/falsy values.

    This also ignores warnings appropriately due to rs.ignore_warnings.

    :param type_: type to check for
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    """
    if name is not None:
        ret, errs = validate.validate_check_optional(
            type_, value, ignore_warnings=rs.ignore_warnings, argname=name, **kwargs)
    else:
        ret, errs = validate.validate_check_optional(
            type_, value, ignore_warnings=rs.ignore_warnings, **kwargs)
    rs.extend_validation_errors(errs)
    return ret


def inspect_validation(
    type_: Type[T], value: Any, *, ignore_warnings: bool = False, **kwargs: Any
) -> Tuple[Optional[T], List[Error]]:
    """Convenient wrapper to call checks in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.frontend.common.check_validation` but returns
    all encountered errors instead of appending them to the RequestState.
    This should only be used if the error handling differs from the default handling.
    """
    return validate.validate_check(
        type_, value, ignore_warnings=ignore_warnings, **kwargs)


def inspect_validation_optional(
    type_: Type[T], value: Any, *, ignore_warnings: bool = False, **kwargs: Any
) -> Tuple[Optional[T], List[Error]]:
    """Convenient wrapper to call checks in :py:mod:`cdedb.validation`.

    This is similar to :func:`~cdedb.frontend.common.inspect_validation` but also allows
    optional/falsy values.
    """
    return validate.validate_check_optional(
        type_, value, ignore_warnings=ignore_warnings, **kwargs)


def basic_redirect(rs: RequestState, url: str) -> werkzeug.Response:
    """Convenience wrapper around :py:func:`construct_redirect`. This should
    be the main thing to use, however it is even more preferable to use
    :py:meth:`BaseApp.redirect`.
    """
    response = construct_redirect(rs.request, url)
    response.headers.add('X-Generation-Time', str(now() - rs.begin))
    return response


def construct_redirect(request: werkzeug.Request,
                       url: str) -> werkzeug.Response:
    """Construct an HTTP redirect. This should use the 303 status
    code. Unfortunately this code is not available for HTTP 1.0, so we fall
    back to an automatic refresh.
    """
    if request.environ['SERVER_PROTOCOL'] == "HTTP/1.0":
        # in case of HTTP 1.0 we cannot use the 303 code
        template = """<!DOCTYPE HTML>
<html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="1;url={url}">
        <title>Redirect</title>
    </head>
    <body>
        You should be redirected now.
        You can also access the target via <a href="{url}">this link</a>.
    </body>
</html>"""
        return Response(template.format(url=urllib.parse.quote(url)),
                        mimetype="text/html")
    else:
        ret = werkzeug.utils.redirect(url, 303)
        ret.delete_cookie("displaynote")
        return ret


def make_postal_address(rs: RequestState, persona: CdEDBObject) -> List[str]:
    """Prepare address info for formatting.

    Addresses have some specific formatting wishes, so we are flexible
    in that we represent an address to be printed as a list of strings
    each containing one line. The final formatting is now basically join
    on line breaks.
    """
    p = persona
    name = "{} {}".format(p['given_names'], p['family_name'])
    if p['title']:
        name = glue(p['title'], name)
    if p['name_supplement']:
        name = glue(name, p['name_supplement'])
    ret = [name]
    if p['address_supplement']:
        ret.append(p['address_supplement'])
    if p['address']:
        ret.append(p['address'])
    if p['postal_code'] or p['location']:
        ret.append("{} {}".format(p['postal_code'] or '',
                                  p['location'] or ''))
    if p['country']:
        ret.append(rs.translations["de"].gettext(format_country_code(p['country'])))
    return ret


def make_membership_fee_reference(persona: CdEDBObject) -> str:
    """Generate the desired reference for membership fee payment.

    This is the "Verwendungszweck".
    """
    return "Mitgliedsbeitrag {gn} {fn}, {cdedbid}".format(
        gn=asciificator(persona['given_names']),
        fn=asciificator(persona['family_name']),
        cdedbid=cdedbid_filter(persona['id']),
    )


def make_event_fee_reference(persona: CdEDBObject, event: CdEDBObject) -> str:
    """Generate the desired reference for event fee payment.

    This is the "Verwendungszweck".
    """
    return "Teilnahmebeitrag {event}, {gn} {fn}, {cdedbid}".format(
        event=asciificator(event['title']),
        gn=asciificator(persona['given_names']),
        fn=asciificator(persona['family_name']),
        cdedbid=cdedbid_filter(persona['id'])
    )


def make_persona_name(persona: CdEDBObject,
                      only_given_names: bool = False,
                      only_display_name: bool = False,
                      given_and_display_names: bool = False,
                      with_family_name: bool = True,
                      with_titles: bool = False) -> str:
    """Format the name of a given persona according to the display name specification

    This is the Python pendant of the `util.persona_name()` macro.
    For a full specification, which name variant should be used in which context, see
    the documentation page about "User Experience Conventions".
    """
    display_name: str = persona.get('display_name', "")
    given_names: str = persona['given_names']
    ret = []
    if with_titles and persona.get('title'):
        ret.append(persona['title'])
    if only_given_names:
        ret.append(given_names)
    elif only_display_name:
        ret.append(display_name)
    elif given_and_display_names:
        if not display_name or display_name == given_names:
            ret.append(given_names)
        else:
            ret.append(f"{given_names} ({display_name})")
    elif display_name and display_name in given_names:
        ret.append(display_name)
    else:
        ret.append(given_names)
    if with_family_name:
        ret.append(persona['family_name'])
    if with_titles and persona.get('name_supplement'):
        ret.append(persona['name_supplement'])
    return " ".join(ret)


def drow_name(field_name: str, entity_id: int, prefix: str = "") -> str:
    prefix = prefix + "_" if prefix else ""
    return f"{prefix}{field_name}_{entity_id}"


def drow_create(entity_id: int, prefix: str = "") -> str:
    return drow_name("create", entity_id, prefix)


def drow_delete(entity_id: int, prefix: str = "") -> str:
    return drow_name("delete", entity_id, prefix)


def drow_last_index(prefix: str = "") -> str:
    return f"{prefix}create_last_index"


# TODO maybe retrieve the spec from the type_?
def process_dynamic_input(
    rs: RequestState,
    type_: Type[T],
    existing: Collection[int],
    spec: vtypes.TypeMapping,
    *,
    additional: CdEDBObject = None,
    creation_spec: vtypes.TypeMapping = None,
    prefix: str = "",
) -> Dict[int, Optional[CdEDBObject]]:
    """Retrieve data from rs provided by 'dynamic_row_meta' macros.

    This takes a 'spec' of field_names mapped to their validation. Each field_name is
    prepended with the 'prefix' and appended with the entity_id in the form of
    "{prefix}{field_name}_{entity_id}" before being extracted from the RequestState.

    'process_dynamic_input' returns a data dict to update the database, which includes:
    - existing entries, mapped to their (validated) input fields (from spec)
    - existing entries, mapped to None (if they were marked to be deleted)
    - new entries, mapped to their (validated) input fields (from spec)

    This adds some additional keys to some entities of the return dict:
    - To each existing, not deleted entry: the 'id' of the entry.
    - To each new and each existing, not deleted entry: all entries of 'additional'

    Take care to check for validation_errors directly after calling this function!
    Since the validation facillity is used inside, a ValidationError inside an entry
    causes the entry to be set to None (similar to all deleted entries), which may have
    unwanted side-effects if you simply proceed.

    :param type_: validation_type of the entities
    :param existing: ids of already existent objects
    :param spec: name of input fields, mapped to their validation. This uses the same
        format as the `request_extractor`, but adds the 'prefix' to each key if present.
    :param additional: additional keys added to each output object
    :param creation_spec: alternative spec used for new entries. Defaults to spec.
    :param prefix: prefix in front of all concerned fields. Should be used when more
        then one dynamic input table is present on the same page.
    """
    additional = additional or dict()
    creation_spec = creation_spec or spec
    # this is the used prefix for the validation
    field_prefix = f"{prefix}_" if prefix else ""

    delete_spec = {drow_delete(anid, prefix): bool for anid in existing}
    delete_flags = request_extractor(rs, delete_spec)
    deletes = {anid for anid in existing if delete_flags[drow_delete(anid, prefix)]}
    non_deleted_existing = {anid for anid in existing if anid not in deletes}

    existing_data_spec: vtypes.TypeMapping = {
        drow_name(key, anid, prefix): value
        for anid in non_deleted_existing
        for key, value in spec.items()
    }
    # validation is postponed to a later point to use the validator for the whole object
    data = request_extractor(rs, existing_data_spec, postpone_validation=True)

    # build the return dict of all existing entries and check if they pass validation
    ret: Dict[int, Optional[CdEDBObject]] = {
        anid: {key: data[drow_name(key, anid, prefix)] for key in spec}
        for anid in non_deleted_existing
    }
    for anid in existing:
        if anid in deletes:
            ret[anid] = None
        else:
            entry = ret[anid]
            assert entry is not None
            if type_ is not vtypes.EventTrack:
                entry["id"] = anid
            entry.update(additional)
            # apply the promised validation
            ret[anid] = check_validation(rs, type_, entry, field_prefix=field_prefix,
                                         field_postfix=f"_{anid}")  # type: ignore

    # extract the new entries which shall be created
    marker = 1
    while marker < 2 ** 10:
        will_create = unwrap(
            request_extractor(rs, {drow_create(-marker, prefix): bool}))
        if will_create:
            params = {drow_name(key, -marker, prefix): value
                      for key, value in creation_spec.items()}
            data = request_extractor(rs, params, postpone_validation=True)
            entry = {
                key: data[drow_name(key, -marker, prefix)] for key in creation_spec}
            entry.update(additional)
            ret[-marker] = check_validation(
                rs, type_, entry, field_prefix=field_prefix,
                field_postfix=f"_{-marker}", creation=True)  # type: ignore
        else:
            break
        marker += 1
    rs.values[drow_last_index(prefix)] = marker - 1
    return ret


class CustomCSVDialect(csv.Dialect):
    delimiter = ';'
    quoting = csv.QUOTE_MINIMAL
    quotechar = '"'
    doublequote = True
    lineterminator = '\n'
    escapechar = None


def csv_output(data: Collection[CdEDBObject], fields: Sequence[str],
               writeheader: bool = True, replace_newlines: bool = False,
               substitutions: Mapping[str, Mapping[Any, Any]] = None) -> str:
    """Generate a csv representation of the passed data.

    :param writeheader: If False, no CSV-Header is written.
    :param replace_newlines: If True all line breaks are replaced by several
      spaces.
    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    """
    substitutions = substitutions or {}
    outfile = io.StringIO()
    writer = csv.DictWriter(
        outfile, fields, dialect=CustomCSVDialect())
    if writeheader:
        writer.writeheader()
    for original in data:
        row = {}
        for field in fields:
            value = original[field]
            if field in substitutions:
                value = substitutions[field].get(value, value)
            if replace_newlines and isinstance(value, str):
                value = value.replace('\n', 14 * ' ')
            row[field] = value
        writer.writerow(row)
    return outfile.getvalue()


def query_result_to_json(data: Collection[CdEDBObject], fields: Iterable[str],
                         substitutions: Mapping[
                             str, Mapping[Any, Any]] = None) -> str:
    """Generate a json representation of the passed data.

    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    """
    substitutions = substitutions or {}
    json_data = []
    for original in data:
        row = {}
        for field in fields:
            value = original[field]
            if field in substitutions:
                value = substitutions[field].get(value, value)
            row[field] = value
        json_data.append(row)
    return json_serialize(json_data)


def calculate_db_logparams(offset: Optional[int], length: int
                           ) -> Tuple[Optional[int], int]:
    """Modify the offset and length values used in the frontend to
    allow for guaranteed valid sql queries.
    """
    _offset = offset
    _length = length
    if _offset and _offset < 0:
        # Avoid non-positive lengths
        if -_offset < length:
            _length = _length + _offset
        _offset = 0

    return _offset, _length


def calculate_loglinks(rs: RequestState, total: int,
                       offset: Optional[int], length: int
                       ) -> Dict[str, Union[CdEDBMultiDict, List[CdEDBMultiDict]]]:
    """Calculate the target parameters for the links in the log pagination bar.

    :param total: The total count of log entries
    :param offset: The offset, preprocessed for negative offset values
    :param length: The requested length (not necessarily the shown length)
    """
    # The true offset does represent the acutal count of log entries before
    # the first shown entry. This is done magically, if no offset has been
    # given.
    if offset is None:
        trueoffset = length * ((total - 1) // length) if total != 0 else 0
    else:
        trueoffset = offset

    # Create values sets for the necessary links.
    def new_md() -> CdEDBMultiDict:
        return werkzeug.datastructures.MultiDict(rs.values)
    loglinks = {
        "first": new_md(),
        "previous": new_md(),
        "current": new_md(),
        "next": new_md(),
        "last": new_md(),
    }
    pre = [new_md() for x in range(3) if trueoffset - x * length > 0]
    post = [new_md() for x in range(3) if trueoffset + (x + 1) * length < total]

    # Fix the offset for each set of values.
    loglinks["first"]["offset"] = "0"
    loglinks["last"]["offset"] = ""
    for x, _ in enumerate(pre):
        pre[x]["offset"] = (trueoffset - (len(pre) - x) * length)
    loglinks["previous"]["offset"] = trueoffset - length
    for x, _ in enumerate(post):
        post[x]["offset"] = trueoffset + (x + 1) * length
    loglinks["next"]["offset"] = trueoffset + length
    loglinks["current"]["offset"] = trueoffset

    # piece everything together
    ret: Dict[str, Union[CdEDBMultiDict, List[CdEDBMultiDict]]]
    ret = dict(**loglinks, **{"pre-current": pre, "post-current": post})
    return ret


class TransactionObserver:
    """Helper to watch over a non-atomic transaction.

    This is a substitute for the Atomizer which is not available in the
    frontend. We are not able to guarantee atomic transactions, but we can
    detect failed transactions and generate error notifications.

    This should only be used in cases where a failure is deemed sufficiently
    unlikely.
    """

    def __init__(self, rs: RequestState, frontend: AbstractFrontend, name: str):
        self.rs = rs
        self.frontend = frontend
        self.name = name

    def __enter__(self) -> "TransactionObserver":
        return self

    def __exit__(self, atype: Optional[Type[Exception]],
                 value: Optional[Exception],
                 tb: Optional[TracebackType]) -> Literal[False]:
        if value:
            self.frontend.do_mail(
                self.rs, "transaction_error",
                {
                    'To': (self.frontend.conf['MANAGEMENT_ADDRESS'],
                           self.frontend.conf['TROUBLESHOOTING_ADDRESS']),
                    'Subject': "Transaktionsfehler",
                },
                {
                    'now': now(),
                    'name': self.name,
                    'atype': atype,
                    'value': value,
                    'tb': tb,
                })
        return False


def setup_translations(conf: Config) -> Mapping[str, gettext.NullTranslations]:
    """Helper to setup a mapping of languages to gettext translation objects."""
    return {
        lang: gettext.translation('cdedb', languages=[lang],
                                  localedir=conf["REPOSITORY_PATH"] / 'i18n')
        for lang in conf["I18N_LANGUAGES"]
    }
