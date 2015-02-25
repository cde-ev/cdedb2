#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic.
"""

import os
import os.path
import werkzeug
import werkzeug.exceptions
import werkzeug.datastructures
import werkzeug.utils
import functools
from cdedb.config import Config, SecretsConfig
from cdedb.common import (
    extract_realm, extract_roles, glue, ALL_ROLES, CommonUser, merge_dicts,
    compute_checkdigit)
from cdedb.query import VALID_QUERY_OPERATORS
import cdedb.validation as validate
import cdedb.database.constants as const
import jinja2
import json
import werkzeug.wrappers
import datetime
import pytz
import hashlib
import Pyro4
import logging
import io
import re
import subprocess

import urllib.parse
import smtplib
import email
import email.mime
import email.mime.text
import email.encoders
import email.header
import email.charset
import tempfile
import abc
from cdedb.internationalization import i18n_factory
from cdedb.serialization import deserialize
from cdedb.config import BasicConfig

_LOGGER = logging.getLogger(__name__)
_BASICCONF = BasicConfig()

#: Set of possible values for ``ntype`` in
#: :py:meth:`FrontendRequestState.notify`. Must conform to the regex
#: ``[a-z]+``.
NOTIFICATION_TYPES = {"success", "info", "question", "warning", "error"}

class ProxyShim:
    """Slim wrapper around a :py:class:`Pyro4.Proxy` to add some boiler plate
    to all proxy calls.
    """
    def __init__(self, proxy):
        """
        :type proxy: :py:class:`Pyro4.Proxy`
        """
        self._proxy = proxy
        self._attrs = {}

    def _wrapit(self, name):
        """
        :type name: str
        :rtype: callable
        """
        def proxy_fun(rs, *args, **kwargs):
            ## use context to automatically close the pyro object
            with self._proxy:
                attr = getattr(self._proxy, name)
                ## Invert our custom serialization.
                ##
                ## This is for backend -> frontend.
                return deserialize(attr(rs.sessionkey, *args, **kwargs))
        return proxy_fun

    def __getattr__(self, name):
        if name in {"_attrs", "_proxy"}:
            raise AttributeError()
        if not name.startswith('_'):
            if name not in self._attrs:
                self._attrs[name] = self._wrapit(name)
            return self._attrs[name]
        else:
            return getattr(self._proxy, name)

def connect_proxy(name):
    """
    :type name: str
    :rtype: :py:class:`Pyro4.Proxy`
    """
    ns = Pyro4.locateNS()
    uri = ns.lookup(name)
    proxy = Pyro4.Proxy(uri)
    return proxy

class FakeFrontendRequestState:
    """Mock version of :py:class:`FrontendRequestState` to be used before a
    real version is available. The basic requirement is, that the
    :py:class:`ProxyShim` can work with this imitation.
    """
    def __init__(self, sessionkey):
        """
        :type sessionkey: str or None
        """
        self.sessionkey = sessionkey

class FrontendRequestState:
    """Container for request info. Besides this the python frontend code should
    be state-less. This data structure enables several convenient
    semi-magic behaviours (magic enough to be nice, but non-magic enough
    to not be non-nice).
    """
    def __init__(self, sessionkey, user, request, response, notifications,
                 mapadapter, requestargs, urlmap, errors, values, lang, coders,
                 begin):
        """
        :type sessionkey: str or None
        :type user: :py:class:`FrontendUser`
        :type request: :py:class:`werkzeug.wrappers.Request`
        :type response: :py:class:`werkzeug.wrappers.Response` or None
        :type notifications: [(str, str)]
        :param notifications: messages to be displayed to the user, to be
          submitted by :py:meth:`notify`
        :type mapadapter: :py:class:`werkzeug.routing.MapAdapter`
        :param mapadapter: URL generator (specific for this request)
        :type requestargs: {str: object}
        :param requestargs: verbatim copy of the arguments contained in the URL
        :type urlmap: :py:class:`werkzeug.routing.Map`
        :param urlmap: abstract URL information
        :type errors: [(str, exception)]
        :param errors: validation errors, consisting of a pair of (parameter
          name, the actual error)
        :type values: {str: object}
        :param values: Parameter values extracted via :py:func:`REQUESTdata`
          and :py:func:`REQUESTdatadict` decorators, which allows automatically
          filling forms in. This will be a
          :py:class:`werkzeug.datastructures.MultiDict` to allow seamless
          integration with the werkzeug provided data.
        :type lang: str
        :param lang: language code for i18n, currently only 'de' is valid
        :type coders: {str: callable}
        :param coders: Functions for encoding and decoding parameters primed
          with secrets. This is hacky, but sadly necessary.
        :type begin: datetime.datetime
        :param begin: time where we started to process the request
        """
        self.sessionkey = sessionkey
        self.user = user
        self.request = request
        self.response = response
        self.notifications = notifications
        self.urls = mapadapter
        self.requestargs = requestargs
        self.urlmap = urlmap
        self.errors = errors
        if not isinstance(values, werkzeug.datastructures.MultiDict):
            values = werkzeug.datastructures.MultiDict(values)
        self.values = values
        self.lang = lang
        self._coders = coders
        self.begin = begin

    def notify(self, ntype, message):
        """Store a notification for later delivery to the user.

        :type ntype: str
        :param ntype: one of :py:data:`NOTIFICATION_TYPES`
        :type message: str
        """
        if ntype not in NOTIFICATION_TYPES:
            raise ValueError("Invalid notification type {} found".format(ntype))
        self.notifications.append((ntype, message))

class BaseApp(metaclass=abc.ABCMeta):
    """Additional base class under :py:class:`AbstractFrontend` which will be
    inherited by :py:class:`cdedb.frontend.application.Application`.
    """
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        self.decode_parameter = (
            lambda target, name, param:
            decode_parameter(secrets.URL_PARAMETER_SALT, target, name, param,
                             self.conf.URL_PARAMETER_TIMEOUT))
        self.encode_parameter = (
            lambda target, name, param:
            encode_parameter(secrets.URL_PARAMETER_SALT, target, name, param))

    def encode_notification(self, ntype, nmessage):
        """Wrapper around :py:meth:`encode_parameter` for notifications.

        The message format is A--B, with
        * A is the notification type, conforming to '[a-z]+'
        * B is the notification message

        :type ntype: str
        :type nmessage: str
        :rtype: str
        """
        message = "{}--{}".format(ntype, nmessage)
        return self.encode_parameter('_/notification', 'displaynote', message)

    def decode_notification(self, note):
        """Inverse wrapper to :py:meth:`encode_notification`.

        :type note: str
        :rtype: str
        """
        message = self.decode_parameter('_/notification', 'displaynote', note)
        if not message:
            return  None, None
        sep = message.index("--")
        return message[:sep], message[sep+2:]

    def redirect(self, rs, target, params=None):
        """Create a response which diverts the user. Special care has to be
        taken not to lose any notifications.

        :type rs: :py:class:`FrontendRequestState`
        :type target: str
        :type params: {str: object}
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
        if rs.errors and not rs.notifications:
            rs.notify("error", "Failed validation.")
        if rs.notifications:
            if 'displaynote' in params or len(rs.notifications) > 1:
                if not isinstance(params, werkzeug.datastructures.MultiDict):
                    params = werkzeug.datastructures.MultiDict(params)
                l = params.getlist('displaynote')
                for ntype, nmessage in rs.notifications:
                    l.append(self.encode_notification(ntype, nmessage))
                params.setlist('displaynote', l)
            else:
                ntype, nmessage = rs.notifications[0]
                params['displaynote'] = self.encode_notification(ntype,
                                                                 nmessage)
        url = cdedburl(rs, target, params)
        return basic_redirect(rs, url)

def sanitize_None(data):
    """Helper to let jinja convert all ``None`` into empty strings for display
    purposes; thus we needn't be careful in this regard. (This is
    coherent with our policy that NULL and the empty string on SQL level
    shall have the same meaning).

    :type data: object
    :rtype: object
    """
    if data is None:
        return ""
    else:
        return data

def date_filter(val, formatstr="%Y-%m-%d"):
    """Custom jinja filter to format ``datetime.date`` objects.

    :type val: datetime.date
    :rtype: str
    """
    if val is None:
        return None
    return val.strftime(formatstr)

def datetime_filter(val, formatstr="%Y-%m-%d %H:%M (%Z)"):
    """Custom jinja filter to format ``datetime.datetime`` objects.

    :type val: datetime.datetime
    :rtype: str
    """
    if val is None:
        return None
    if val.tzinfo is not None:
        val = val.astimezone(_BASICCONF.DEFAULT_TIMEZONE)
    else:
        _LOGGER.warning("Found naive datetime object {}.".format(val))
    return val.strftime(formatstr)

def cdedbid_filter(val):
    """Custom jinja filter to format persona ids with a check digit. Every user
    visible id should be formatted with this filter. The check digit is
    one of the letters between 'A' and 'K' to make a clear distinction
    between the numeric id and the check digit.

    :type val: int
    :rtype: str
    """
    if val is None:
        return None
    return "DB-{}-{}".format(val, compute_checkdigit(val))

def escape_filter(val):
    """Custom jinja filter to reconcile escaping with the finalize method
    (which suppresses all ``None`` values and thus mustn't be converted to
    strings first).

    .. note:: Actually this returns a jinja specific 'safe string' which
      will remain safe when operated on. This means for example that the
      linebreaks filter has to make the string unsafe again, before it can
      work.

    :type val: obj or None
    :rtype: str or None
    """
    if val is None:
        return None
    else:
        return jinja2.escape(val)

LATEX_ESCAPE_REGEX = (
    (re.compile(r'\\'), r'\\textbackslash'),
    (re.compile(r'([{}_#%&$])'), r'\\\1'),
    (re.compile(r'~'), r'\~{}'),
    (re.compile(r'\^'), r'\^{}'),
    (re.compile(r'"'), r"''"),
)
def tex_escape_filter(val):
    """Custom jinja filter for escaping LaTeX-relevant charakters.

    :type val: obj or None
    :rtype: str or None
    """
    if val is None:
        return None
    else:
        val = str(val)
        for pattern, replacement in LATEX_ESCAPE_REGEX:
            val = pattern.sub(replacement, val)
        return val

def json_filter(val):
    """Custom jinja filter to create json representation of objects. This is
    intended to allow embedding of values into generated javascript code.

    The result of this method does not need to be escaped -- more so if
    escaped, the javascript execution will probably fail.
    """
    return json.dumps(val)

def gender_filter(val):
    """Custom jinja filter to convert gender constants to something printable.

    :type val: int
    :rtype: str
    """
    if val is None:
        return None
    if val == const.Genders.female:
        return '♀'
    elif val == const.Genders.male:
        return '♂'
    else:
        return '⚧'

def enum_filter(val, enum):
    """Custom jinja filter to convert enums to something printable.

    This exists mainly because of the possibility of None values.

    :type val: int
    :rtype: str
    """
    if val is None:
        return None
    return str(enum(val))

def numerus_filter(val, singular, plural):
    """Custom jinja filter to select singular or plural form.

    :type val: int
    :type singular: str
    :type plural: str
    :rtype: str
    """
    if val is None:
        return None
    if val == 1:
        return singular
    else:
        return plural

def genus_filter(val, female, male, unknown=None):
    """Custom jinja filter to select gendered form of a string.

    :type val: int
    :type female: str
    :type male: str
    :type unknown: str
    :rtype: str
    """
    if val is None:
        return None
    if unknown is None:
        unknown = female
    if val == const.Genders.female:
        return female
    elif val == const.Genders.male:
        return male
    else:
        return unknown

def stringIn_filter(val, alist):
    """Custom jinja filter to test if a value is in a list, but requiring
    equality only on string representation.

    This has to be an explicit filter becaus jinja does not support list
    comprehension.

    :type val: obj
    :type alist: [obj]
    :rtype: bool
    """
    return str(val) in (str(x) for x in alist)

def querytoparams_filter(val):
    """Custom jinja filter to convert query into a parameter dict
    which can be used to create a URL of the query.

    This could probably be done in jinja, but this would be pretty
    painful.

    :type val: :py:class:`cdedb.query.Query`
    :rtype: {str: obj}
    """
    params = {}
    for field in val.fields_of_interest:
        params['qsel_{}'.format(field)] = True
    for field, op, value in val.constraints:
        params['qop_{}'.format(field)] = op.value
        params['qval_{}'.format(field)] = value
    for entry, postfix in zip(val.order,
                              ("primary", "secondary", "tertiary")):
        field, ascending = entry
        params['qord_{}'.format(postfix)] = field
        params['qord_{}_ascending'.format(postfix)] = ascending
    return params

def linebreaks_filter(val, replacement="<br>"):
    """Custom jinja filter to convert line breaks to <br>.

    :type val: str
    :rtype: str
    """
    if val is None:
        return None
    ## because val is probably a jinja specific 'safe string'
    val = str(val)
    return val.replace('\n', replacement)

class AbstractFrontend(BaseApp, metaclass=abc.ABCMeta):
    """Common base class for all frontends."""
    i18n = i18n_factory()
    #: to be overridden by children
    realm = None
    ## logger are thread-safe!
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.join(
                self.conf.REPOSITORY_PATH, "cdedb/frontend/templates")),
            extensions=['jinja2.ext.with_'],
            finalize=sanitize_None)
        filters = {
            'date': date_filter,
            'datetime': datetime_filter,
            'cdedbid': cdedbid_filter,
            'escape': escape_filter,
            'e': escape_filter,
            'gender': gender_filter,
            'json': json_filter,
            'stringIn': stringIn_filter,
            'querytoparams': querytoparams_filter,
            'numerus': numerus_filter,
            'genus': genus_filter,
            'linebreaks': linebreaks_filter,
            'enum': enum_filter,
            'tex_escape': tex_escape_filter,
            'te': tex_escape_filter,
        }
        self.jinja_env.filters.update(filters)

    @abc.abstractmethod
    def finalize_session(self, rs, sessiondata):
        """Create a :py:class:`FrontendUser` instance for this request. This is
        realm dependent and may add supplementary information (e.g. list of
        events which are organized by this persona).

        This will be called by
        :py:class:`cdedb.frontend.application.Application` and is thus
        part of the interface.

        :type rs: :py:class:`FakeFrontendRequestState`
        :type sessiondata: {str: object}
        :param sessiondata: values from the ``core.personas`` table in the
          database
        :rtype: :py:class:`FrontendUser`
        """
        realm = extract_realm(sessiondata["status"])
        roles = extract_roles(sessiondata["db_privileges"],
                              sessiondata["status"])
        return FrontendUser(
            persona_id=sessiondata['persona_id'], roles=roles, realm=realm,
            username=sessiondata['username'],
            display_name=sessiondata['display_name'])

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.

        :type rs: :py:class:`FrontendRequestState`
        :rtype: bool
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    def fill_template(self, rs, modus, templatename, params):
        """Central function for generating output from a template. This
        makes several values always accessible to all templates.

        .. note:: We change the templating syntax for TeX templates since
                  jinjas default syntax is nasty for this.

        :type rs: :py:class:`FrontendRequestState`
        :type modus: str
        :param modus: type of thing we want to generate (currently 'web' or
          'mail')
        :type templatename: str
        :param templatename: file name of template without extension
        :type params: {str: object}
        :rtype: str
        """
        def _cdedblink(endpoint, params=None):
            """We don't want to pass the whole request state to the
            template, hence this wrapper.

            :type endpoint: str
            :type params: {str: object}
            :rtype: str
            """
            params = params or {}
            return cdedburl(rs, endpoint, params)

        def _show_user_link(persona_id):
            """Convenience method to create link to user data page.

            This is lengthy otherwise because of the parameter encoding
            and a pretty frequent operation so that it is beneficial to
            have this helper.

            :type persona_id: int
            :rtype: str
            """
            return cdedburl(rs, 'core/show_user', params={
                'persona_id': persona_id,
                'confirm_id': self.encode_parameter("core/show_user",
                                                    "confirm_id", persona_id)})
        default_selections = {
            'gender': tuple((k, v, None) for k, v in
                            self.enum_choice(rs, const.Genders).items()),
        }
        errorsdict = {}
        for key, value in rs.errors:
            errorsdict.setdefault(key, []).append(value)
        ## here come the always accessible things promised above
        data = {'user': rs.user,
                'notifications': rs.notifications,
                'errors': errorsdict,
                'values': rs.values,
                'cdedblink': _cdedblink,
                'show_user_link': _show_user_link,
                'staticurl': staticurl,
                'encode_parameter': self.encode_parameter,
                'is_admin': self.is_admin(rs),
                'VALID_QUERY_OPERATORS': VALID_QUERY_OPERATORS,
                'default_selections': default_selections,
                'i18n': lambda string: self.i18n(string, rs.lang),
                'const': const,
                'glue': glue,
                'generation_time': lambda: (datetime.datetime.now(pytz.utc)
                                            - rs.begin),}
        ## check that default values are not overridden
        assert(not(set(data) & set(params)))
        merge_dicts(data, params)
        if modus == "tex":
            jinja_env = self.jinja_env.overlay(
                block_start_string="<<%",
                block_end_string="%>>",
                variable_start_string="<<<",
                variable_end_string=">>>",
                comment_start_string="<<#",
                comment_end_string="#>>",
            )
        else:
            jinja_env = self.jinja_env
        t = jinja_env.get_template(os.path.join(
            modus, rs.lang, self.realm, "{}.tmpl".format(templatename)))
        return t.render(**data)

    @staticmethod
    def send_file(rs, mimetype=None, filename=None, *, path=None, afile=None,
                  data=None):
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`FrontendRequestState`
        :type mimetype: str or None
        :param mimetype: If not None the mime type of the file to be sent.
        :type filename: str or None
        :param filename: If not None the default file name used if the user
          tries to save the file to disk
        :type path: str
        :type afile: file like
        :param afile: should be opened in binary mode
        :type data: str or bytes
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        if not path and not afile and not data:
            raise RuntimeError("No input specified.")
        if (path and afile) or (path and data) or (afile and data):
            raise RuntimeError("Ambiguous input.")
        if path and not os.path.isfile(path):
            return werkzeug.exceptions.NotFound()
        if path:
            afile = open(path, 'rb')
        elif data is not None:
            afile = io.BytesIO()
            if isinstance(data, str):
                afile.write(data.encode('utf-8'))
            else:
                afile.write(data)
            afile.seek(0)
        f = werkzeug.wsgi.wrap_file(rs.request.environ, afile)
        extra_args = {}
        if mimetype is not None:
            extra_args['mimetype'] = mimetype
        headers = []
        if filename is not None:
            ## Alternative is content disposition 'attachment', which forces
            ## a download box -- we don't want that.
            headers.append(('Content-Disposition',
                            'inline; filename="{}"'.format(filename)))
        headers.append(('X-Generation-Time', str(
            datetime.datetime.now(pytz.utc) - rs.begin)))
        return werkzeug.wrappers.Response(
            f, direct_passthrough=True, headers=headers, **extra_args)

    def render(self, rs, templatename, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTML responses.

        :type rs: :py:class:`FrontendRequestState`
        :type templatename: str
        :type params: {str: object}
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
        ## handy, should probably survive in a commented HTML portion
        if 'debugstring' not in params:
            debugstring = glue(
                "We have is_multithreaded={}; is_multiprocess={};",
                "base_url={} ; cookies={} ; url={} ; is_secure={} ;",
                "method={} ; remote_addr={} ; values={}").format(
                    rs.request.is_multithread, rs.request.is_multiprocess,
                    rs.request.base_url, rs.request.cookies, rs.request.url,
                    rs.request.is_secure, rs.request.method,
                    rs.request.remote_addr, rs.request.values)
            params['debugstring'] = debugstring
        if rs.errors and not rs.notifications:
            rs.notify("error", "Failed validation.")
        html = self.fill_template(rs, "web", templatename, params)
        if "<pre>" not in html:
            ## eliminate empty lines, since they don't matter
            html = "\n".join(line for line in html.split('\n') if line.strip())
        rs.response = werkzeug.wrappers.Response(html, mimetype='text/html')
        rs.response.headers.add('X-Generation-Time', str(
            datetime.datetime.now(pytz.utc) - rs.begin))
        return rs.response

    def do_mail(self, rs, templatename, headers, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        :type rs: :py:class:`FrontendRequestState`
        :type templatename: str
        :type headers: {str: str}
        :param headers: mandatory headers to supply are To and Subject
        :type params: {str: object}
        :rtype: str or None
        :returns: see :py:meth:`_send_mail` for details, we automatically
          store the path in ``rs``
        """
        params = params or {}
        params['headers'] = headers
        text = self.fill_template(rs, "mail", templatename, params)
        ## do i18n here, so _create_mail needs to know less context
        headers['Subject'] = self.i18n(headers['Subject'], rs.lang)
        msg = self._create_mail(text, headers)
        ret = self._send_mail(msg)
        if ret:
            ## This is mostly intended for the test suite.
            rs.notify("info", "Stored email to hard drive at {}".format(ret))
        return ret

    def _create_mail(self, text, headers):
        """Helper for actual email instantiation from a raw message.

        :type text: str
        :type headers: {str: str}
        :rtype: :py:class:`email.message.Message`
        """
        defaults = {"From": self.conf.DEFAULT_SENDER,
                    "Reply-To": self.conf.DEFAULT_REPLY_TO,
                    "Cc": tuple(),
                    "Bcc": tuple(),
                    "domain": self.conf.MAIL_DOMAIN,}
        merge_dicts(headers, defaults)
        msg = email.mime.text.MIMEText(text)
        email.encoders.encode_quopri(msg)
        del msg['Content-Transfer-Encoding']
        msg['Content-Transfer-Encoding'] = 'quoted-printable'
        ## we want quoted-printable, but without encoding spaces and without
        ## linewrapping (encoding is a pain!)
        payload = msg.get_payload()
        payload = payload.replace('=20', ' ')
        payload = payload.replace('=\n', '')
        msg.set_payload(payload)
        for header in ("To", "Cc", "Bcc"):
            if headers[header]:
                msg[header] = ", ".join(headers[header])
        for header in ("From", "Reply-To", "Subject"):
            msg[header] = headers[header]
        msg["Message-ID"] = email.utils.make_msgid(domain=self.conf.MAIL_DOMAIN)
        msg["Date"] = datetime.datetime.now(pytz.utc).strftime(
            "%Y-%m-%d %H:%M:%S%z")
        return msg

    def _send_mail(self, msg):
        """Helper for getting an email onto the wire.

        :type msg: :py:class:`email.message.Message`
        :rtype: str or None
        :returns: Name of the file the email was saved in -- however this
          happens only in development mode. This is intended for consumption
          by the test suite.
        """
        ret = None
        if not self.conf.CDEDB_DEV:
            s = smtplib.SMTP(self.conf.MAIL_HOST)
            s.send_message(msg)
            s.quit()
        else:
            with tempfile.NamedTemporaryFile(mode='w', prefix="cdedb-mail-",
                                             suffix=".txt", delete=False) as f:
                f.write(str(msg))
                self.logger.debug("Stored mail to {}.".format(f.name))
                ret = f.name
        self.logger.info("Sent email with subject '{}' to '{}'".format(
            msg['Subject'], msg['To']))
        return ret

    def redirect_show_user(self, rs, persona_id):
        """Convenience function to redirect to a user detail page.

        The point is, that encoding the ``confirm_id`` parameter is
        somewhat lengthy and only necessary because of our paranoia.

        :type rs: :py:class:`FrontendRequestState`
        :type persona_id: int
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        cid = self.encode_parameter("{}/show_user".format(self.realm),
                                    "confirm_id", persona_id)
        params = {'confirm_id': cid, 'persona_id': persona_id}
        return self.redirect(rs, '{}/show_user'.format(self.realm),
                             params=params)

    @classmethod
    def enum_choice(cls, rs, anenum):
        """Convert an enum into a dict suitable for consumption by the template
        code (this will turn into an HTML select in the end).

        :type rs: :py:class:`FrontendRequestState`
        :type anenum: :py:class:`enum.Enum`
        :rtype: {int: str}
        """
        return {case.value: cls.i18n(str(case), rs.lang)
                for case in anenum}

    @staticmethod
    def notify_return_code(rs, code, success="Change committed.",
                           pending="Change pending.", error="Change failed."):
        """Small helper to issue a notification based on a return code.

        We allow some flexibility in what type of return code we accept. It
        may be a boolean (with the obvious meanings), an integer (specifying
        the number of changed entries, and negative numbers for entries with
        pending review) or None (signalling failure to acquire something).

        :type rs: :py:class:`FrontendRequestState`
        :type success: str
        :type code: int or bool or None
        :param success: Affirmative message for positive return codes.
        :param pending: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            rs.notify("error", error)
        elif code == True or code > 0:
            rs.notify("success", success)
        elif code < 0:
            rs.notify("info", pending)
        else:
            raise RuntimeError("Impossible.")

    def latex_compile(self, data, runs=2):
        """Run LaTeX on the provided document.

        This takes care of the necessary temporary files.

        :type data: str
        :type runs: int
        :param runs: number of times LaTeX is run (for references etc.)
        :rtype: bytes
        :returns: the compiled document as blob
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_file:
                tmp_file.write(data.encode('utf8'))
                tmp_file.flush()
                args = ("pdflatex", "-interaction", "batchmode", tmp_file.name)
                for _ in range(runs):
                    self.logger.info("Invoking {}".format(args))
                    subprocess.check_call(args, stdout=subprocess.DEVNULL,
                                          cwd=tmp_dir)
                with open("{}.pdf".format(tmp_file.name), 'rb') as pdf:
                    return pdf.read()

    def serve_latex_document(self, rs, data, filename, runs=2):
        """Generate a response from a LaTeX document.

        This takes care of the necessary temporary files.

        :type rs: :py:class:`FrontendRequestState`
        :type data: str
        :param data: the LaTeX document
        :type filename: str
        :param filename: name to serve the document as, without extension
        :type runs: int
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled pdf.
        :rtype: werkzeug.Response
        """
        if not runs:
            return self.send_file(
                rs, data=data,
                filename=self.i18n("{}.tex".format(filename), rs.lang))
        else:
            pdf_data = self.latex_compile(data, runs=runs)
            return self.send_file(
                rs, mimetype="application/pdf", data=pdf_data,
                filename=self.i18n("{}.pdf".format(filename), rs.lang))

    def serve_complex_latex_document(self, rs, tmp_dir, work_dir_name,
                                     tex_file_name, runs=2):
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

        :type rs: :py:class:`FrontendRequestState`
        :type tmp_dir: str
        :param tmp_dir: path of temporary directory
        :type work_dir_name: str
        :param work_dir_name: name of working directory inside temporary
          directory.
        :type tex_file_name: str
        :param tex_file_name: name of the tex file (including extension),
          this will be used to derived the name to use when serving the
          compiled pdf file.
        :type runs: int
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled
          pdf. More specifically we serve a gzipped tar archive containing
          the working directory.
        :rtype: werkzeug.Response
        """
        if not runs:
            target = os.path.join(
                tmp_dir, "{}.tar.gz".format(work_dir_name))
            args = ("tar", "-vczf", target, work_dir_name)
            self.logger.info("Invoking {}".format(args))
            subprocess.check_call(args, stdout=subprocess.DEVNULL,
                                  cwd=tmp_dir)
            return self.send_file(
                rs, path=target,
                filename="{}.tar.gz".format(work_dir_name))
        else:
            work_dir = os.path.join(tmp_dir, work_dir_name)
            if tex_file_name.endswith('.tex'):
                pdf_file = "{}.pdf".format(tex_file_name[:-4])
            else:
                pdf_file = "{}.pdf".format(tex_file_name)
            args = ("pdflatex", "-interaction", "batchmode",
                    os.path.join(work_dir, tex_file_name))
            for _ in range(runs):
                self.logger.info("Invoking {}".format(args))
                subprocess.check_call(args, stdout=subprocess.DEVNULL,
                                      cwd=work_dir)
            return self.send_file(
                rs, mimetype="application/pdf",
                path=os.path.join(work_dir, pdf_file),
                filename=self.i18n(pdf_file, rs.lang))

class FrontendUser(CommonUser):
    """Container for a persona in the frontend."""
    def __init__(self, display_name="", username="", **kwargs):
        """
        :type display_name: str or None
        :type username: str or None
        """
        super().__init__(**kwargs)
        self.username = username
        self.display_name = display_name

def access(role, modi=None):
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :type role: str
    :param role: least level of privileges required
    :type modi: {str}
    :param modi: HTTP methods allowed for this invocation
    """
    modi = modi or {"GET", "HEAD"}
    access_list = ALL_ROLES[role]
    def decorator(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if rs.user.roles & access_list:
                return fun(obj, rs, *args, **kwargs)
            else:
                if rs.user.roles == {"anonymous"}:
                    params = {
                        'wants': rs._coders['encode_parameter'](
                            "core/index", "wants", rs.request.url),
                        'displaynote': rs._coders['encode_notification'](
                            "error", "You must login.")
                        }
                    return basic_redirect(rs, cdedburl(rs, "core/index",
                                                       params))
                raise werkzeug.exceptions.Forbidden(
                    "Access denied to {}/{}.".format(obj, fun.__name__))
        new_fun.access_list = access_list
        new_fun.modi = modi
        return new_fun
    return decorator

def cdedburl(rs, endpoint, params=None):
    """Construct an HTTP URL.

    :type rs: :py:class:`FrontendRequestState`
    :type endpoint: str
    :param endpoint: as defined in :py:data:`cdedb.frontend.paths.CDEDB_PATHS`
    :type params: {str: object}
    :rtype: str
    """
    params = params or {}
    allparams = werkzeug.datastructures.MultiDict()
    for arg in rs.requestargs:
        if rs.urlmap.is_endpoint_expecting(endpoint, arg):
            allparams[arg] = rs.requestargs[arg]
    if isinstance(params, werkzeug.datastructures.MultiDict):
        for key in params:
            allparams.setlist(key, params.getlist(key))
    else:
        for key in params:
            allparams[key] = params[key]
    return rs.urls.build(endpoint, allparams)

def staticurl(path):
    """Construct an HTTP URL to a static resource (to be found in the static
    directory). We encapsulate this here so moving the directory around
    causes no pain.

    :type path: str
    :rtype: str
    """
    return os.path.join("/static", path)

def REQUESTdata(*spec):
    """Decorator to extract parameters from requests and validate them. This
    should always be used, so automatic form filling works as expected.

    This strips surrounding whitespace. If this is undesired at some
    point in the future we have to add an override here.

    :type spec: [(str, str)]
    :param spec: Specification of parameters to extract. The
      first value of a tuple is the name of the parameter to look out
      for. The second value of each tuple denotes the sort of parameter to
      extract, valid values are all validators from
      :py:mod:`cdedb.validation` vanilla, enclosed in square brackets or
      with a leading hash, the square brackets are for HTML elements which
      submit multiple values for the same parameter (e.g. <select>) which
      are extracted as lists and the hash signals an encoded parameter,
      which needs to be decoded first.
    """
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            for name, argtype in spec:
                if name not in kwargs:
                    if argtype.startswith('[') and argtype.endswith(']'):
                        vals = tuple(val.strip()
                                     for val in rs.request.values.getlist(name))
                        rs.values.setlist(name, vals)
                        kwargs[name] = tuple(
                            check_validation(rs, argtype[1:-1], val, name)
                            for val in vals)
                    else:
                        val = rs.request.values.get(name, "").strip()
                        rs.values[name] = val
                        if argtype.startswith('#'):
                            argtype = argtype[1:]
                            if val:
                                ## only decode if exists
                                val = rs._coders['decode_parameter'](
                                    "{}/{}".format(obj.realm, fun.__name__),
                                    name, val)
                        kwargs[name] = check_validation(rs, argtype, val, name)
            return fun(obj, rs, *args, **kwargs)
        return new_fun
    return wrap

def REQUESTdatadict(*proto_spec):
    """Similar to :py:meth:`REQUESTdata`, but doesn't hand down the
    parameters as keyword-arguments, instead packs them all into a dict and
    passes this as ``data`` parameter. This does not do validation since
    this is infeasible in practice.

    This strips surrounding whitespace. If this is undesired at some
    point in the future we have to add an override here.

    :type proto_spec: [str or (str, str)]
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
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            data = {}
            for name, argtype in spec:
                if argtype == "str":
                    data[name] = rs.request.values.get(name, "").strip()
                elif argtype == "[str]":
                    data[name] = tuple(
                        val.strip() for val in rs.request.values.getlist(name))
                else:
                    raise ValueError("Invalid argtype {} found.".format(
                        argtype))
                rs.values[name] = data[name]
            return fun(obj, rs, *args, data=data, **kwargs)
        return new_fun
    return wrap

def request_data_extractor(rs, args):
    """Utility to apply REQUESTdata later than usual.

    This is intended to bu used, when the parameter list is not known before
    hand. Prime example are the event specific fields of event
    registrations, here the parameter list has to be constructed from data
    retrieved from the backend.

    :type rs: :py:class:`FrontendRequestState`
    :type args: [(str, str)]
    :param args: handed through to the decorator
    :rtype: {str: object}
    :returns: dict containing the requested values
    """
    @REQUESTdata(*args)
    def fun(_, rs, **kwargs):
        return kwargs
    return fun(None, rs)

def request_data_dict_extractor(rs, args):
    """Utility to apply REQUESTdatadict later than usual.

    Like :py:meth:`request_data_extractor`.

    :type rs: :py:class:`FrontendRequestState`
    :type args: [(str, str)]
    :param args: handed through to the decorator
    :rtype: {str: object}
    :returns: dict containing the requested values
    """
    @REQUESTdatadict(*args)
    def fun(_, rs, data):
        return data
    return fun(None, rs)

def REQUESTfile(*args):
    """Decorator to extract file uploads from requests.

    :type args: [str]
    :param args: Names of file parameters.
    """
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args2, **kwargs):
            for name in args:
                if name not in kwargs:
                    kwargs[name] = rs.request.files.get(name, None)
                rs.values[name] = kwargs[name]
            return fun(obj, rs, *args2, **kwargs)
        return new_fun
    return wrap

def persona_dataset_guard(argname="persona_id", realms=tuple(),
                          disallow_archived=True):
    """This decorator checks the access with respect to a specific persona. The
    persona is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    Only the persona itself or a privileged user is
    admitted. Additionally the realm of the persona may be verified and
    archived member datasets may be excluded.

    An example use case is the page for changing user details.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    :type realms: [str] or None
    :param realms: If not None the realm of the persona is checked. The
      realm of the persona has to be in this list (if the list is empty
      the realm of the current frontend is checked against).
    :type disallow_archived: bool
    :param disallow_archived: defaults to True
    """
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg != rs.user.persona_id and not obj.is_admin(rs):
                return werkzeug.exceptions.Forbidden()
            if realms is not None:
                therealms = realms or (obj.realm,)
                status = obj.coreproxy.get_data_one(rs, arg)['status']
                if (extract_realm(status) not in therealms
                        or (disallow_archived and status ==
                            const.PersonaStati.archived_member)):
                    return werkzeug.exceptions.NotFound()
            return fun(obj, rs, *args, **kwargs)
        return new_fun
    return wrap

def event_guard(argname="event_id", check_offline=False):
    """This decorator checks the access with respect to a specific event. The
    event is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    The event has to be organized via the DB. Only orgas and privileged
    users are admitted. Additionally this can check for the offline
    lock, so that no modifications happen to locked events.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    :type check_offline: bool
    :param check_offline: defaults to False
    """
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.orga and not obj.is_admin(rs):
                return werkzeug.exceptions.Forbidden()
            if check_offline:
                is_locked = obj.eventproxy.is_offline_locked(rs, event_id=arg)
                if is_locked != obj.conf.CDEDB_OFFLINE_DEPLOYMENT:
                    return werkzeug.exceptions.Forbidden()
            return fun(obj, rs, *args, **kwargs)
        return new_fun
    return wrap

def mailinglist_guard(argname="mailinglist_id"):
    """This decorator checks the access with respect to a specific
    mailinglist. The list is specified by id which has either to be a
    keyword parameter or the first positional parameter after the
    request state. Only moderators and privileged users are admitted.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    """
    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.moderator and not obj.is_admin(rs):
                return werkzeug.exceptions.Forbidden()
            return fun(obj, rs, *args, **kwargs)
        return new_fun
    return wrap

def encode_parameter(salt, target, name, param):
    """Crypographically secure a parameter. This allows two things:

    * trust user submitted data (which we beforehand gave to the user in
      signed form and which he is echoing back at us); this is used for
      example to preserve notifications during redirecting a POST-request,
      and
    * verify the origin of the data (since only we have the key for
      signing), this is convenient since we are mostly state-less (except
      the SQL layer) and thus the user can obtain a small amount of state
      where necessary; this is for example used by the password reset path
      to generate a short-lived reset link to be sent via mail, without
      storing a challenge in the database.

    All ingredients used here are necessary for security. The timestamp
    guarantees a short lifespan via the decoding function.

    The message format is A--B--C, where

    * A is 128 chars sha512 checksum of 'X--Y--Z--B--C' where X == salt, Y
      == target, Z == name
    * B is 24 chars timestamp of format '%Y-%m-%d %H:%M:%S%z'
    * C is an arbitrary amount chars of payload

    :type salt: str
    :param salt: secret used for signing the parameter
    :type target: str
    :param target: The endpoint the parameter is designated for. If this is
      omitted, there are nasty replay attacks.
    :type name: str
    :param name: name of parameter, same security implications as ``target``
    :type param: str
    :rtype: str
    """
    myhash = hashlib.sha512()
    now = datetime.datetime.now(pytz.utc)
    message = "{}--{}".format(now.strftime("%Y-%m-%d %H:%M:%S%z"), param)
    tohash = "{}--{}--{}--{}".format(salt, target, name, message)
    myhash.update(tohash.encode("utf-8"))
    return "{}--{}".format(myhash.hexdigest(), message)

def decode_parameter(salt, target, name, param, timeout):
    """Inverse of :py:func:`encode_parameter`. See there for
    documentation. Note the ``timeout`` parameter.

    :type salt: str
    :type target: str
    :type name: str
    :type param: str
    :type timeout: :py:class:`datetime.timedelta`
    :rtype: str or None
    :returns: decoded message, ``None`` if decoding or verification fails
    """
    myhash = hashlib.sha512()
    mac, message = param[0:128], param[130:]
    tohash = "{}--{}--{}--{}".format(salt, target, name, message)
    myhash.update(tohash.encode("utf-8"))
    if myhash.hexdigest() != mac:
        _LOGGER.debug("Hash mismatch ({} != {}) for {}".format(
            myhash.hexdigest(), mac, tohash))
        return None
    timestamp = datetime.datetime.strptime(message[:24], "%Y-%m-%d %H:%M:%S%z")
    if timestamp + timeout <= datetime.datetime.now(pytz.utc):
        _LOGGER.debug("Expired protected parameter {}".format(tohash))
        return None
    return message[26:]

def check_validation(rs, assertion, value, name=None, **kwargs):
    """Helper to perform parameter sanitization.

    :type rs: :py:class:`FrontendRequestState`
    :type assertion: str
    :param assertion: name of validation routine to call
    :type value: object
    :type name: str or None
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    :rtype: (object or None, [(str, Exception)])
    """
    checker = getattr(validate, "check_{}".format(assertion))
    if name is not None:
        ret, errs = checker(value, name, **kwargs)
    else:
        ret, errs = checker(value, **kwargs)
    rs.errors.extend(errs)
    return ret

def basic_redirect(rs, url):
    """Convenience wrapper around :py:func:`construct_redirect`. This should be
    the main thing to use.

    :type rs: :py:class:`FrontendRequestState`
    :type url: str
    :rtype: :py:class:`werkzeug.wrappers.Response`
    """
    rs.response = construct_redirect(rs.request, url)
    rs.response.headers.add('X-Generation-Time', str(
        datetime.datetime.now(pytz.utc) - rs.begin))
    return rs.response

def construct_redirect(request, url):
    """Construct an HTTP redirect. This should use the 303 status
    code. Unfortunately this code is not available for HTTP 1.0, so we fall
    back to an automatic refresh.

    :type request: :py:class:`werkzeug.wrappers.Request`
    :type url: str
    :rtype: :py:class:`werkzeug.wrappers.Response`
    """
    if request.environ['SERVER_PROTOCOL'] == "HTTP/1.0":
        ## in case of HTTP 1.0 we cannot use the 303 code
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
        return werkzeug.wrappers.Response(
            template.format(url=urllib.parse.quote(url)), mimetype="text/html")
    else:
        return werkzeug.utils.redirect(url, 303)
