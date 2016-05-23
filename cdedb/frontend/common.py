#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic.
"""

import abc
import collections
import copy
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
import functools
import hashlib
import io
import json
import logging
import os
import os.path
import re
import smtplib
import subprocess
import tempfile
import threading
import urllib.parse

import docutils.core
import jinja2
import werkzeug
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.utils
import werkzeug.wrappers

from cdedb.internationalization import i18n_factory
from cdedb.config import BasicConfig, Config, SecretsConfig
from cdedb.common import (
    glue, merge_dicts, compute_checkdigit, now, asciificator, roles_to_db_role,
    RequestState)
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.query import VALID_QUERY_OPERATORS
import cdedb.validation as validate
import cdedb.database.constants as const

_LOGGER = logging.getLogger(__name__)
_BASICCONF = BasicConfig()

class Response(werkzeug.wrappers.Response):
    """Wrapper around werkzeugs Response to handle displaynote cookie.

    This is a pretty thin wrapper, but essential so our magic cookie
    gets cleared and no stale notifications remain.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delete_cookie("displaynote")

class BaseApp(metaclass=abc.ABCMeta):
    """Additional base class under :py:class:`AbstractFrontend` which will be
    inherited by :py:class:`cdedb.frontend.application.Application`.
    """
    logger = logging.getLogger(__name__)

    def __init__(self, configpath, *args, **kwargs):
        """
        :type configpath: str
        """
        super().__init__(*args, **kwargs)
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        self.decode_parameter = (
            lambda target, name, param:
            decode_parameter(secrets.URL_PARAMETER_SALT, target, name, param))
        def my_encode(target, name, param,
                      timeout=self.conf.ONLINE_PARAMETER_TIMEOUT):
            return encode_parameter(secrets.URL_PARAMETER_SALT, target, name,
                                    param, timeout=timeout)
        self.encode_parameter = my_encode

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

        :type rs: :py:class:`RequestState`
        :type target: str
        :type params: {str: object}
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
        if rs.errors and not rs.notifications:
            rs.notify("error", "Failed validation.")
        url = cdedburl(rs, target, params)
        ret = basic_redirect(rs, url)
        if rs.notifications:
            notifications = [self.encode_notification(ntype, nmessage)
                             for ntype, nmessage in rs.notifications]
            ret.set_cookie("displaynote", json.dumps(notifications))
        return ret

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

def money_filter(val, currency="€"):
    """Custom jinja filter to format ``decimal.Decimal`` objects.

    This is for values representing monetary amounts.

    :type val: decimal.Decimal
    :rtype: str
    """
    if val is None:
        return None
    return "{:.2f}{}".format(val, currency)

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

    :type val: object or None
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

    :type val: object or None
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

    :type val: object
    :type alist: [object]
    :rtype: bool
    """
    return str(val) in (str(x) for x in alist)

def querytoparams_filter(val):
    """Custom jinja filter to convert query into a parameter dict
    which can be used to create a URL of the query.

    This could probably be done in jinja, but this would be pretty
    painful.

    :type val: :py:class:`cdedb.query.Query`
    :rtype: {str: object}
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
    params['is_search'] = True
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

def rst_filter(val):
    """Custom jinja filter to convert rst to html.

    :type val: str
    :rtype: str
    """
    if val is None:
        return None
    defaults = {'file_insertion_enabled': 0,
                'raw_enabled': 0,
                'id_prefix': "CDEDB_RST_"}
    ret = docutils.core.publish_parts(val, writer_name='html',
                                      settings_overrides=defaults)
    return ret['html_body']

def xdictsort_filter(value, attribute):
    """Allow sorting by an arbitrary attribute of the value.

    Jinja only provides sorting by key or entire value. Also Jinja does
    not allow comprehensions or lambdas, hence we have to use this.

    This obviously only works if the values allow access by key.

    :type value: {object: dict}
    :rtype: [(object, dict)]
    """
    return sorted(value.items(), key=lambda item: item[1].get(attribute))

class AbstractFrontend(BaseApp, metaclass=abc.ABCMeta):
    """Common base class for all frontends."""
    i18n = i18n_factory()
    #: to be overridden by children
    realm = None
    ## logger are thread-safe!
    logger = logging.getLogger(__name__)

    def __init__(self, configpath, *args, **kwargs):
        """
        :type configpath: str
        """
        super().__init__(configpath, *args, **kwargs)
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.join(
                self.conf.REPOSITORY_PATH, "cdedb/frontend/templates")),
            extensions=['jinja2.ext.with_'],
            finalize=sanitize_None)
        filters = {
            'date': date_filter,
            'datetime': datetime_filter,
            'money': money_filter,
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
            'rst': rst_filter,
            'enum': enum_filter,
            'xdictsort': xdictsort_filter,
            'tex_escape': tex_escape_filter,
            'te': tex_escape_filter,
        }
        self.jinja_env.filters.update(filters)

    @abc.abstractmethod
    def finalize_session(self, rs):
        """Allow realm specific tweaking of the session.

        This is intended to add orga and moderator infos in the event
        and ml realm respectively.

        This will be called by
        :py:class:`cdedb.frontend.application.Application` and is thus
        part of the interface.

        :type rs: :py:class:`RequestState`
        :rtype: None
        """
        return

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.

        :type rs: :py:class:`RequestState`
        :rtype: bool
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    def fill_template(self, rs, modus, templatename, params):
        """Central function for generating output from a template. This
        makes several values always accessible to all templates.

        .. note:: We change the templating syntax for TeX templates since
                  jinjas default syntax is nasty for this.

        :type rs: :py:class:`RequestState`
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

        def _show_user_link(persona_id, realm=None):
            """Convenience method to create link to user data page.

            This is lengthy otherwise because of the parameter encoding
            and a pretty frequent operation so that it is beneficial to
            have this helper.

            :type persona_id: int
            :type realm: str or None
            :param realm: If given this is the target realm for the show user
              page.
            :rtype: str
            """
            realm = realm or self.realm
            return cdedburl(rs, '{}/show_user'.format(realm), params={
                'persona_id': persona_id,
                'confirm_id': self.encode_parameter(
                    "{}/show_user".format(realm),
                    "confirm_id", persona_id, timeout=None)},)
        default_selections = {
            'gender': tuple((k, v, None) for k, v in
                            self.enum_choice(rs, const.Genders).items()),
        }
        errorsdict = {}
        for key, value in rs.errors:
            errorsdict.setdefault(key, []).append(value)
        ## here come the always accessible things promised above
        data = {
            'ambience': rs.ambience,
            'cdedblink': _cdedblink,
            'const': const,
            'default_selections': default_selections,
            'encode_parameter': self.encode_parameter,
            'errors': errorsdict,
            'generation_time': lambda: (now() - rs.begin),
            'glue': glue,
            'i18n': lambda string: self.i18n(string, rs.lang),
            'is_admin': self.is_admin(rs),
            'notifications': rs.notifications,
            'now': now,
            'show_user_link': _show_user_link,
            'staticurl': staticurl,
            'user': rs.user,
            'values': rs.values,
            'VALID_QUERY_OPERATORS': VALID_QUERY_OPERATORS,
            'CDEDB_OFFLINE_DEPLOYMENT': self.conf.CDEDB_OFFLINE_DEPLOYMENT,
        }
        ## check that default values are not overridden
        assert(not set(data) & set(params))
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
    def send_file(rs, mimetype=None, filename=None, inline=True, *,
                  path=None, afile=None, data=None):
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`RequestState`
        :type mimetype: str or None
        :param mimetype: If not None the mime type of the file to be sent.
        :type filename: str or None
        :param filename: If not None the default file name used if the user
          tries to save the file to disk
        :type inline: bool
        :param inline: Set content disposition to force display in browser (if
          True) or to force a download box (if False).
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
            # TODO Can we use a with context here or maybe close explicitly?
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
        disposition = "inline" if inline else "attachment"
        if filename is not None:
            disposition += '; filename="{}"'.format(filename)
        headers.append(('Content-Disposition', disposition))
        headers.append(('X-Generation-Time', str(now() - rs.begin)))
        return Response(f, direct_passthrough=True, headers=headers,
                        **extra_args)

    def render(self, rs, templatename, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTML responses.

        :type rs: :py:class:`RequestState`
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
                "method={} ; remote_addr={} ; values={}, ambience={}").format(
                    rs.request.is_multithread, rs.request.is_multiprocess,
                    rs.request.base_url, rs.request.cookies, rs.request.url,
                    rs.request.is_secure, rs.request.method,
                    rs.request.remote_addr, rs.request.values, rs.ambience)
            params['debugstring'] = debugstring
        if rs.errors and not rs.notifications:
            rs.notify("error", "Failed validation.")
        html = self.fill_template(rs, "web", templatename, params)
        if "<pre>" not in html:
            ## eliminate empty lines, since they don't matter
            html = "\n".join(line for line in html.split('\n') if line.strip())
        rs.response = Response(html, mimetype='text/html')
        rs.response.headers.add('X-Generation-Time', str(now() - rs.begin))
        return rs.response

    def do_mail(self, rs, templatename, headers, params=None, attachments=None):
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        Some words about email trouble. Bounced mails go by default to a
        special address ``bounces@cde-ev.de``, which will be a list not
        managed via the DB. For mailinglists the return path will be a
        list specific bounce address which delivers the bounces to the
        moderators.

        :type rs: :py:class:`RequestState`
        :type templatename: str
        :type headers: {str: str}
        :param headers: mandatory headers to supply are To and Subject
        :type params: {str: object}
        :type attachments: [{str: object}] or None
        :param attachments: Each dict describes one attachment. The possible
          keys are path (a ``str``), file (a file like), mimetype (a ``str``),
          filename (a ``str``).
        :rtype: str or None
        :returns: see :py:meth:`_send_mail` for details, we automatically
          store the path in ``rs``
        """
        params = params or {}
        params['headers'] = headers
        text = self.fill_template(rs, "mail", templatename, params)
        ## do i18n here, so _create_mail needs to know less context
        headers['Subject'] = self.i18n(headers['Subject'], rs.lang)
        msg = self._create_mail(text, headers, attachments)
        ret = self._send_mail(msg)
        if ret:
            ## This is mostly intended for the test suite.
            rs.notify("info", "Stored email to hard drive at {}".format(ret))
        return ret

    def _create_mail(self, text, headers, attachments):
        """Helper for actual email instantiation from a raw message.

        :type text: str
        :type headers: {str: str}
        :type attachments: [{str: object}] or None
        :rtype: :py:class:`email.message.Message`
        """
        defaults = {"From": self.conf.DEFAULT_SENDER,
                    "Reply-To": self.conf.DEFAULT_REPLY_TO,
                    "Return-Path": self.conf.DEFAULT_RETURN_PATH,
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
        if attachments:
            container = email.mime.multipart.MIMEMultipart()
            container.attach(msg)
            for attachment in attachments:
                container.attach(self._create_attachment(attachment))
            ## put the container in place as message to send
            msg = container
        for header in ("To", "Cc", "Bcc"):
            nonempty = {x for x in headers[header] if x}
            if nonempty != set(headers[header]):
                self.logger.warning("Empty values zapped in email recipients.")
            if headers[header]:
                msg[header] = ", ".join(nonempty)
        for header in ("From", "Reply-To", "Subject", "Return-Path"):
            msg[header] = headers[header]
        msg["Message-ID"] = email.utils.make_msgid(domain=self.conf.MAIL_DOMAIN)
        msg["Date"] = now().strftime("%Y-%m-%d %H:%M:%S%z")
        return msg

    @staticmethod
    def _create_attachment(attachment):
        """Helper instantiating an attachment via the email module.

        :type attachment: {str: object}
        :param attachment: see :py:meth:`do_mail` for a description of keys
        :rtype: :py:class:`email.message.Message`
        """
        mimetype = attachment.get('mimetype') or 'application/octet-stream'
        maintype, subtype = mimetype.split('/', 1)
        if attachment.get('file'):
            afile = attachment['file']
        else:
            # TODO use a with context?
            if maintype == "text":
                afile = open(attachment['path'])
            else:
                afile = open(attachment['path'], 'rb')
        ## Only support common types
        factories = {
            'application': email.mime.application.MIMEApplication,
            'audio': email.mime.audio.MIMEAudio,
            'image': email.mime.image.MIMEImage,
            'text': email.mime.text.MIMEText,
        }
        ret = factories[maintype](afile.read(), _subtype=subtype)
        if not attachment.get('file'):
            afile.close()
        if attachment.get('filename'):
            ret.add_header('Content-Disposition', 'attachment',
                           filename=attachment['filename'])
        return ret

    def _send_mail(self, msg):
        """Helper for getting an email onto the wire.

        :type msg: :py:class:`email.message.Message`
        :rtype: str or None
        :returns: Name of the file the email was saved in -- however this
          happens only in development mode. This is intended for consumption
          by the test suite.
        """
        ret = None
        if not msg["To"] and not msg["Cc"] and not msg["Bcc"]:
            self.logger.warning("No recipients for mail. Dropping it.")
            return None
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

    def redirect_show_user(self, rs, persona_id, realm=None):
        """Convenience function to redirect to a user detail page.

        The point is, that encoding the ``confirm_id`` parameter is
        somewhat lengthy and only necessary because of our paranoia.

        :type rs: :py:class:`RequestState`
        :type persona_id: int
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        realm = realm or self.realm
        cid = self.encode_parameter("{}/show_user".format(realm),
                                    "confirm_id", persona_id,
                                    timeout=None)
        params = {'confirm_id': cid, 'persona_id': persona_id}
        return self.redirect(rs, '{}/show_user'.format(realm),
                             params=params)

    @classmethod
    def enum_choice(cls, rs, anenum):
        """Convert an enum into a dict suitable for consumption by the template
        code (this will turn into an HTML select in the end).

        :type rs: :py:class:`RequestState`
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

        :type rs: :py:class:`RequestState`
        :type success: str
        :type code: int or bool or None
        :param success: Affirmative message for positive return codes.
        :param pending: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            rs.notify("error", error)
        elif code is True or code > 0:
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

        :type rs: :py:class:`RequestState`
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
                rs, data=data, inline=False,
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

        :type rs: :py:class:`RequestState`
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
                rs, path=target, inline=False,
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

class Worker(threading.Thread):
    """Customization wrapper around ``threading.Thread``.

    This takes care of initializing a new (basically cloned) request
    state object, containing a separate database connection, so that
    concurrency is no concern.
    """

    def __init__(self, conf, task, rs, *args, **kwargs):
        """
        :type confpath: :py:class:`cdedb.Config`
        :type realm: str
        :type task: callable
        :param task: Will be called with exactly one argument (the cloned
          request state) until it returns something falsy.
        :type rs: :py:class:`RequestState`
        """
        rrs = RequestState(
            rs.sessionkey, rs.user, rs.request, None, [], rs.urls,
            rs.requestargs, rs.urlmap, [], copy.deepcopy(rs.values),
            rs.lang, rs._coders, rs.begin)
        secrets = SecretsConfig(conf._configpath)
        connpool = connection_pool_factory(
            conf.CDB_DATABASE_NAME, DATABASE_ROLES, secrets)
        rrs._conn = connpool[roles_to_db_role(rs.user.roles)]
        def runner():
            """Implements the actual loop running the task inside the Thread."""
            while task(rrs):
                pass
        super().__init__(target=runner, daemon=False, *args, **kwargs)

def reconnoitre_ambience(obj, rs):
    """Provide automatic lookup of objects in a standard way.

    This creates an ambience dict providing objects for all ids passed
    as part of the URL path. The naming is not predetermined, but as a
    convention the object name should be the parameter named minus the
    '_id' suffix.

    :type obj: :py:class:`AbstractFrontend`
    :type rs: :py:class:`RequestState`
    :rtype: {str: object}
    """
    Scout = collections.namedtuple('Scout', ('getter', 'param_name',
                                             'object_name', 'dependencies'))
    t = tuple()
    def myAssert(x):
        if not x:
            raise werkzeug.exceptions.BadRequest("Inconsistent request.")
    def attachment_check(a):
        if a['attachment']['ballot_id']:
            return a['attachment']['ballot_id'] == rs.requestargs['ballot_id']
        else:
            return (a['attachment']['assembly_id']
                    == rs.requestargs['assembly_id'])
    scouts = (
        Scout(lambda anid: obj.coreproxy.get_persona(rs, anid), 'persona_id',
              'persona', t),
        # no case_id for genesis cases since they are special and cause
        # PrivilegeErrors
        Scout(lambda anid: obj.cdeproxy.get_lastschrift_one(rs, anid),
              'lastschrift_id', 'lastschrift', t),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift_transaction(rs, anid),
              'transaction_id', 'transaction',
              ((lambda a: myAssert(a['transaction']['lastschrift_id']
                                   == a['lastschrift']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_institution(rs, anid),
              'institution_id', 'institution', t),
        Scout(lambda anid: obj.eventproxy.get_event_data_one(rs, anid),
              'event_id', 'event', t),
        Scout(lambda anid: obj.eventproxy.get_past_event_data_one(rs, anid),
              'pevent_id', 'pevent', t),
        Scout(lambda anid: obj.eventproxy.get_course_data_one(rs, anid),
              'course_id', 'course',
              ((lambda a: myAssert(a['course']['event_id']
                                   == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_past_course_data_one(rs, anid),
              'pcourse_id', 'pcourse',
              ((lambda a: myAssert(a['pcourse']['pevent_id']
                                   == a['pevent']['id'])),)),
        Scout(None, 'part_id', None,
              ((lambda a: myAssert(rs.requestargs['part_id']
                                   in a['event']['parts'])),)),
        Scout(lambda anid: obj.eventproxy.get_registration(rs, anid),
              'registration_id', 'registration',
              ((lambda a: myAssert(a['registration']['event_id']
                                   == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_lodgement(rs, anid),
              'lodgement_id', 'lodgement',
              ((lambda a: myAssert(a['lodgement']['event_id']
                                   == a['event']['id'])),)),
        Scout(None, 'field_id', None,
              ((lambda a: myAssert(rs.requestargs['field_id']
                                   in a['event']['fields'])),)),
        Scout(lambda anid: obj.assemblyproxy.get_attachment(rs, anid),
              'attachment_id', 'attachment', (attachment_check,)),
        Scout(lambda anid: obj.assemblyproxy.get_assembly_data_one(rs, anid),
              'assembly_id', 'assembly', t),
        Scout(lambda anid: obj.assemblyproxy.get_ballot(rs, anid),
              'ballot_id', 'ballot',
              ((lambda a: myAssert(a['ballot']['assembly_id']
                                   == a['assembly']['id'])),)),
        Scout(None, 'candidate_id', None,
              ((lambda a: myAssert(rs.requestargs['candidate_id']
                                   in a['ballot']['candidates'])),)),
        Scout(lambda anid: obj.mlproxy.get_mailinglist(rs, anid),
              'mailinglist_id', 'mailinglist', t),
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
                    "Object {}={} not found".format(param, value))
    for param, value in rs.requestargs.items():
        if param in scouts_dict:
            for consistency_checker in scouts_dict[param].dependencies:
                consistency_checker(ambience)
    return ambience

def access(*roles, modi=None):
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :type roles: [str]
    :param roles: privilege required (any of the passed)
    :type modi: {str}
    :param modi: HTTP methods allowed for this invocation
    """
    modi = modi or {"GET", "HEAD"}
    access_list = set(roles)
    def decorator(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if rs.user.roles & access_list:
                rs.ambience = reconnoitre_ambience(obj, rs)
                return fun(obj, rs, *args, **kwargs)
            else:
                if rs.user.roles == {"anonymous"}:
                    params = {
                        'wants': rs._coders['encode_parameter'](
                            "core/index", "wants", rs.request.url),
                        }
                    ret = basic_redirect(rs, cdedburl(rs, "core/index", params))
                    notifications = json.dumps([
                        rs._coders['encode_notification']("error",
                                                          "You must login.")])
                    ret.set_cookie("displaynote", notifications)
                    return ret
                raise werkzeug.exceptions.Forbidden(
                    "Access denied to {}/{}.".format(obj, fun.__name__))
        new_fun.access_list = access_list
        new_fun.modi = modi
        return new_fun
    return decorator

def cdedburl(rs, endpoint, params=None):
    """Construct an HTTP URL.

    :type rs: :py:class:`RequestState`
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
                        if vals:
                            rs.values.setlist(name, vals)
                        else:
                            ## We have to be careful, since empty lists are
                            ## problematic for the werkzeug MultiDict
                            rs.values[name] = None
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

    :type rs: :py:class:`RequestState`
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

    :type rs: :py:class:`RequestState`
    :type args: [(str, str)]
    :param args: handed through to the decorator
    :rtype: {str: object}
    :returns: dict containing the requested values
    """
    @REQUESTdatadict(*args)
    def fun(_, rs, data):
        return data
    ## This looks wrong. but is correct.
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

def encode_parameter(salt, target, name, param,
                     timeout=datetime.timedelta(seconds=60)):
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
    * B is 24 chars timestamp of format '%Y-%m-%d %H:%M:%S%z' or 24 dots
      describing when the parameter expires (and the latter meaning never)
    * C is an arbitrary amount chars of payload

    :type salt: str
    :param salt: secret used for signing the parameter
    :type target: str
    :param target: The endpoint the parameter is designated for. If this is
      omitted, there are nasty replay attacks.
    :type name: str
    :param name: name of parameter, same security implications as ``target``
    :type param: str
    :param timeout: time until parameter expires, if this is None, the
      parameter never expires
    :type timeout: datetime.timedelta or None
    :rtype: str
    """
    myhash = hashlib.sha512()
    if timeout is None:
        timestamp = 24 * '.'
    else:
        ttl = now() + timeout
        timestamp = ttl.strftime("%Y-%m-%d %H:%M:%S%z")
    message = "{}--{}".format(timestamp, param)
    tohash = "{}--{}--{}--{}".format(salt, target, name, message)
    myhash.update(tohash.encode("utf-8"))
    return "{}--{}".format(myhash.hexdigest(), message)

def decode_parameter(salt, target, name, param):
    """Inverse of :py:func:`encode_parameter`. See there for
    documentation.

    :type salt: str
    :type target: str
    :type name: str
    :type param: str
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
    timestamp = message[:24]
    if timestamp == 24 * '.':
        pass
    else:
        ttl = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S%z")
        if ttl <= now():
            _LOGGER.debug("Expired protected parameter {}".format(tohash))
            return None
    return message[26:]

def check_validation(rs, assertion, value, name=None, **kwargs):
    """Helper to perform parameter sanitization.

    :type rs: :py:class:`RequestState`
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
    """Convenience wrapper around :py:func:`construct_redirect`. This should
    be the main thing to use, however it is even more preferable to use
    :py:meth:`BaseApp.redirect`.

    :type rs: :py:class:`RequestState`
    :type url: str
    :rtype: :py:class:`werkzeug.wrappers.Response`
    """
    rs.response = construct_redirect(rs.request, url)
    rs.response.headers.add('X-Generation-Time', str(now() - rs.begin))
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
        return Response(template.format(url=urllib.parse.quote(url)),
                        mimetype="text/html")
    else:
        ret = werkzeug.utils.redirect(url, 303)
        ret.delete_cookie("displaynote")
        return ret

def make_postal_address(persona_data):
    """Prepare address info for formatting.

    Addresses have some specific formatting wishes, so we are flexible
    in that we represent an address to be printed as a list of strings
    each containing one line. The final formatting is now basically join
    on line breaks.

    :type persona_data: {str: object}
    :rtype: [str]
    """
    pd = persona_data
    name = "{} {}".format(pd['given_names'], pd['family_name'])
    if pd['title']:
        name = glue(pd['title'], name)
    if pd['name_supplement']:
        name = glue(name, pd['name_supplement'])
    ret = [name]
    if pd['address_supplement']:
        ret.append(pd['address_supplement'])
    if pd['address']:
        ret.append(pd['address'])
    if pd['postal_code'] or pd['location']:
        ret.append("{} {}".format(pd['postal_code'] or '',
                                  pd['location'] or ''))
    if pd['country']:
        ret.append(pd['country'])
    return ret

def make_transaction_subject(persona):
    """Generate a string for users to put on a payment.

    This is the "Verwendungszweck".

    :type persona: {str: object}
    :rtype: str
    """
    return "{}, {}, {}".format(cdedbid_filter(persona['id']),
                               asciificator(persona['family_name']),
                               asciificator(persona['given_names']))
