#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic."""

import os
import os.path
import werkzeug
import werkzeug.exceptions
import werkzeug.datastructures
import werkzeug.utils
import functools
from cdedb.config import Config, SecretsConfig
from cdedb.common import extract_realm, extract_global_privileges, glue
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
                ## This is backend -> frontend.
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
                 mapadapter, requestargs, urlmap, errors, values, lang, coders):
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
        :type requestargs: :py:class:`werkzeug.datastructures.MultiDict`
        :param requestargs: verbatim copy of the arguments contained in the URL
        :type urlmap: :py:class:`werkzeug.routing.Map`
        :param urlmap: abstract URL information
        :type errors: [(str, exception)]
        :param errors: validation errors, consisting of a pair of (parameter
          name, the actual error)
        :type values: {str : object}
        :param values: parameter values extracted via :py:func:`REQUESTdata`
          and :py:func:`REQUESTdatadict` decorators, which allows automatically
          filling forms in
        :type lang: str
        :param lang: language code for i18n, currently only 'de' is valid
        :type coders: {str : callable}
        :param coders: Functions for encoding and decoding parameters primed
          with secrets. This is hacky, but sadly necessary.
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
        self.values = values
        self.lang = lang
        self._coders = coders

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
        self.decode_parameter = lambda target, name, param: \
          decode_parameter(secrets.URL_PARAMETER_SALT, target, name, param,
                           self.conf.URL_PARAMETER_TIMEOUT)
        self.encode_parameter = lambda target, name, param: \
          encode_parameter(secrets.URL_PARAMETER_SALT, target, name, param)

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
        :type params: {str : object}
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
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
    return val.strftime(formatstr)

def datetime_filter(val, formatstr="%Y-%m-%d %H:%M (%Z)"):
    """Custom jinja filter to format ``datetime.datetime`` objects.

    :type val: datetime.datetime
    :rtype: str
    """
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
    digits = []
    tmp = val
    while tmp > 0:
        digits.append(tmp % 10)
        tmp = tmp // 10
    dsum = sum((i+1)*d for i, d in enumerate(digits))
    return "DB-{}-{}".format(val, chr(65 + (dsum % 11)))

def escape_filter(val):
    """Custom jinja filter to reconcile escaping with the finalize method
    (which suppresses all ``None`` values and thus mustn't be converted to
    strings first).

    :type val: obj or None
    :rtype: str or None
    """
    if val is None:
        return None
    else:
        return jinja2.escape(val)

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
    if val == const.Genders.female:
        return '♀'
    elif val == const.Genders.male:
        return '♂'
    else:
        return '⚧'

def numerus_filter(val, singular, plural):
    """Custom jinja filter to select singular or plural form.

    :type val: int
    :type singular: str
    :type plural: str
    :rtype: str
    """
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
    if unknown is None:
        unknown = female
    if val == const.Genders.female:
        return female
    elif val == const.Genders.male:
        return male
    else:
        return unknown

def querytoparams_filter(val):
    """Custom jinja filter to convert query into a parameter dict
    which can be used to create a URL of the query.

    This could probably be done in jinja, but this would be pretty
    painful.

    :type val: :py:class:`cdedb.query.Query`
    :rtype: {str : obj}
    """
    params = {}
    for field in val.fields_of_interest:
        params['qsel_{}'.format(field)] = True
    for field, op, value in val.constraints:
        params['qop_{}'.format(field)] = op.value
        params['qval_{}'.format(field)] = value
    for field, postfix in zip(val.order,
                              ("primary", "secondary", "tertiary")):
        params['qord_{}'.format(postfix)] = field
    return params

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
            'date' : date_filter,
            'datetime' : datetime_filter,
            'cdedbid' : cdedbid_filter,
            'escape' : escape_filter,
            'e' : escape_filter,
            'gender' : gender_filter,
            'json' : json_filter,
            'querytoparams' : querytoparams_filter,
            'numerus' : numerus_filter,
            'genus' : genus_filter,
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
        :type sessiondata: {str : object}
        :param sessiondata: values from the ``core.personas`` table in the
          database
        :rtype: :py:class:`FrontendUser`
        """
        realm = extract_realm(sessiondata["status"])
        roles = ["anonymous"]
        global_privs = extract_global_privileges(sessiondata['db_privileges'],
                                                 sessiondata['status'])
        if "persona" in global_privs:
            roles.append("persona")
        if realm == self.realm:
            roles.append("user")
        for role in ("member", "{}_admin".format(self.realm), "admin"):
            if role in global_privs:
                roles.append(role)
        role = roles[-1]
        if sessiondata["status"] in const.MEMBER_STATI:
            is_member = True
        else:
            is_member = False
        if sessiondata["status"] in const.SEARCHMEMBER_STATI:
            is_searchable = True
        else:
            is_searchable = False
        return FrontendUser(
            sessiondata['persona_id'], role, sessiondata['display_name'],
            sessiondata['username'], is_member, is_searchable, realm)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.

        :type rs: :py:class:`FrontendRequestState`
        :rtype: bool
        """
        return rs.user.role in ("{}_admin".format(cls.realm), "admin")

    def allowed(self, rs, method):
        """Called by the ``@access`` decorator to verify authorization.

        :type rs: :py:class:`FrontendRequestState`
        :type method: str
        :rtype: bool
        """
        try:
            return rs.user.role in getattr(self, method).access_list
        except AttributeError:
            return False

    def fill_template(self, rs, modus, templatename, params):
        """Central function for generating output from a template. This does
        makes several values always accessible to the templates.

        :type rs: :py:class:`FrontendRequestState`
        :type modus: str
        :param modus: type of thing we want to generate (currently 'web' or
          'mail')
        :type templatename: str
        :param templatename: file name of template without extension
        :type params: {str : object}
        :rtype: str
        """
        def _cdedblink(endpoint, params=None):
            """We don't want to pass the whole request state to the
            template, hence this wrapper.

            :type endpoint: str
            :type params: {str : object}
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
                'persona_id' : persona_id,
                'confirm_id' : self.encode_parameter("core/show_user",
                                                     "confirm_id", persona_id)})
        default_selections = {
            'gender' : tuple((k, v) for k, v in
                             self.enum_choice(rs, const.Genders).items()),
        }
        errorsdict = {}
        for key, value in rs.errors:
            errorsdict.setdefault(key, []).append(value)
        ## here come the always accessible things promised above
        data = {'user' : rs.user,
                'notifications' : rs.notifications,
                'errors' : errorsdict,
                'values' : rs.values,
                'cdedblink' : _cdedblink,
                'show_user_link' : _show_user_link,
                'staticurl' : staticurl,
                'encode_parameter' : self.encode_parameter,
                'is_admin' : self.is_admin(rs),
                'VALID_QUERY_OPERATORS' : VALID_QUERY_OPERATORS,
                'default_selections' : default_selections,
                'i18n' : lambda string: self.i18n(string, rs.lang),}
        data.update(params)
        t = self.jinja_env.get_template(os.path.join(
            modus, rs.lang, self.realm, "{}.tmpl".format(templatename)))
        return t.render(**data)

    def send_file(self, rs, path=None, afile=None, data=None):
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`FrontendRequestState`
        :type path: str
        :type afile: file like
        :param afile: should be opened in binary mode
        :type data: str
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
            afile.write(data.encode('utf-8'))
            afile.seek(0)
        f = werkzeug.wsgi.wrap_file(rs.request.environ, afile)
        # TODO maybe add mime type
        return werkzeug.wrappers.Response(f, direct_passthrough=True)

    def render(self, rs, templatename, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTTP responses.

        :type rs: :py:class:`FrontendRequestState`
        :type templatename: str
        :type params: {str : object}
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
        html = self.fill_template(rs, "web", templatename, params)
        if "<pre>" not in html:
            ## eliminate empty lines, since they don't matter
            html = "\n".join(line for line in html.split('\n') if line.strip())
        rs.response = werkzeug.wrappers.Response(html, mimetype='text/html')
        return rs.response

    def do_mail(self, rs, templatename, headers, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        :type rs: :py:class:`FrontendRequestState`
        :type templatename: str
        :type headers: {str : str}
        :param headers: mandatory headers to supply are To and Subject
        :type params: {str : object}
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
.
        :type text: str
        :type headers: {str : str}
        :rtype: :py:class:`email.message.Message`
        """
        defaults = {"From" : self.conf.DEFAULT_SENDER,
                    "Reply-To" : self.conf.DEFAULT_REPLY_TO,
                    "Cc" : tuple(),
                    "Bcc" : tuple(),
                    "domain" : self.conf.MAIL_DOMAIN,}
        defaults.update(headers)
        headers = defaults
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
        params = {'confirm_id' : self.encode_parameter(
            "{}/show_user".format(self.realm), "confirm_id", persona_id),
            'persona_id' : persona_id}
        return self.redirect(rs, '{}/show_user'.format(self.realm),
                             params=params)

    def enum_choice(self, rs, anenum):
        """Convert an enum into a dict suitable for consumption by the template
        code (this will turn into an HTML select in the end).

        :type rs: :py:class:`FrontendRequestState`
        :type anenum: :py:class:`enum.Enum`
        :rtype: {str : str}
        """
        return {str(case.value) : self.i18n(str(case), rs.lang)
                for case in anenum}

class FrontendUser:
    """Container for representing a persona."""
    def __init__(self, persona_id=None,
                 role="anonymous", display_name="", username="",
                 is_member=False, is_searchable=False, realm=None, orga=None,
                 moderator=None):
        """
        :type persona_id: int
        :type role: str
        :type display_name: str
        :type username: str
        :type is_member: bool :type is_searchable: bool
        :type realm: str
        :type orga: [int] or None
        :param orga: list of event ids this persona is organizing (this is
          optional and only provided in the event realm)
        :type moderator: [int] or None
        :param orga: list of mailing list ids this persona is moderating (this
          is optional and only provided in the ml realm)
        """
        self.persona_id = persona_id
        self.role = role
        orga = orga or set()
        self.orga = set(orga)
        moderator = moderator or set()
        self.moderator = set(moderator)
        self.display_name = display_name
        self.username = username
        self.is_member = is_member
        self.is_searchable = is_searchable
        self.realm = realm

def access_decorator_generator(possibleroles):
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :type possibleroles: [str]
    :param possibleroles: ordered list of privilege levels
    :rtype: decorator
    """
    def decorator(role, modi=None):
        """
        :type role: str
        :param role: least level of privileges required
        :type modi: {str}
        :param modi: HTTP methods allowed for this invocation
        """
        modi = modi or {"GET", "HEAD"}
        def wrap(fun):
            @functools.wraps(fun)
            def new_fun(obj, rs, *args, **kwargs):
                if obj.allowed(rs, fun.__name__):
                    return fun(obj, rs, *args, **kwargs)
                else:
                    if rs.user.role == "anonymous":
                        params = {
                            'wants' : rs._coders['encode_parameter'](
                                "core/index", "wants", rs.request.url),
                            'displaynote' : rs._coders['encode_notification'](
                                "error", "You must login.")
                            }
                        return basic_redirect(rs, cdedburl(rs, "core/index",
                                                           params))
                    raise werkzeug.exceptions.Forbidden(
                        "Access denied to {}/{}.".format(obj, fun.__name__))
            new_fun.access_list = set(possibleroles[possibleroles.index(role):])
            new_fun.modi = modi
            return new_fun
        return wrap
    return decorator

def cdedburl(rs, endpoint, params=None):
    """Construct an HTTP URL.

    :type rs: :py:class:`FrontendRequestState`
    :type endpoint: str
    :param endpoint: as defined in :py:data:`cdedb.frontend.paths.CDEDB_PATHS`
    :type params: {str : object}
    :rtype: str
    """
    params = params or {}
    allparams = {}
    for arg in rs.requestargs:
        if rs.urlmap.is_endpoint_expecting(endpoint, arg):
            allparams[arg] = rs.requestargs[arg]
    ## be careful and not use allparams.update since params may be a
    ## werkzeug.datastructures.MultiDict which produces unwanted lists in
    ## this context
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
                        vals = rs.request.values.getlist(name)
                        rs.values[name] = vals
                        kwargs[name] = tuple(
                            check_validation(rs, argtype[1:-1], val, name)
                            for val in vals)
                    else:
                        val = rs.request.values.get(name, "")
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
                    data[name] = rs.request.values.get(name, "")
                elif argtype == "[str]":
                    data[name] = rs.request.values.getlist(name)
                else:
                    raise ValueError("Invalid argtype {} found.".format(
                        argtype))
                rs.values[name] = data[name]
            return fun(obj, rs, *args, data=data, **kwargs)
        return new_fun
    return wrap

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

def persona_dataset_guard(argname="persona_id", realms=tuple()):
    """This decorator checks the access with respect to a specific persona. The
    persona is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    Only the persona itself or a privileged user is
    admitted. Additionally the realm of the persona may be verified.

    An example use case is the page for changing user details.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    :type realms: [str] or None
    :param realms: If not None the realm of the persona is checked. The
      realm of the persona has to be in this list (if the list is empty
      the realm of the current frontend is checked against).
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
                if obj.coreproxy.get_realm(rs, arg) not in therealms:
                    return werkzeug.exceptions.NotFound()
            return fun(obj, rs, *args, **kwargs)
        return new_fun
    return wrap

def encode_parameter(salt, target, name, param):
    """Crypographically secure a parameter. This allows two things:

    * trust user submitted data (which we beforehand gave to the user in
      signed form and which he is echoing back at us); this is used for
      example to preserve notifications during redirecting a POST-request, and
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
