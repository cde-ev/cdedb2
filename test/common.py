#!/usr/bin/env python3

import collections.abc
import datetime
import email.parser
import email.policy
import functools
import gettext
import inspect
import pathlib
import pytz
import re
import unittest
import subprocess
import types
import webtest

from cdedb.config import BasicConfig, SecretsConfig
from cdedb.frontend.application import Application
from cdedb.frontend.cron import CronFrontend
from cdedb.common import (
    ProxyShim, RequestState, roles_to_db_role, PrivilegeError, glue)
from cdedb.backend.core import CoreBackend
from cdedb.backend.session import SessionBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.query import QueryOperators

_BASICCONF = BasicConfig()


class NearlyNow(datetime.datetime):
    """This is something, that equals an automatically generated timestamp.

    Since automatically generated timestamp are not totally predictible,
    we use this to avoid nasty work arounds.
    """
    def __eq__(self, other):
        if isinstance(other, datetime.datetime):
            delta = self - other
            return (delta < datetime.timedelta(minutes=10)
                    and delta > datetime.timedelta(minutes=-10))
        return False

    def __ne__(self, other):
        return not self.__eq__(other)


def nearly_now():
    """Create a NearlyNow."""
    now = datetime.datetime.now(pytz.utc)
    return NearlyNow(
        year=now.year, month=now.month, day=now.day, hour=now.hour,
        minute=now.minute, second=now.second, tzinfo=pytz.utc)


def json_keys_to_int(obj):
    """Convert dict keys to integers if possible.

    This is a restriction of the JSON format allowing only string keys.
    :type obj: object
    :rtype obj: object
    """
    if isinstance(obj, collections.abc.Mapping):
        ret = {}
        for key, val in obj.items():
            try:
                key = int(key)
            except (ValueError, TypeError):
                pass
            ret[key] = json_keys_to_int(val)
    elif isinstance(obj, collections.abc.Sequence):
        if isinstance(obj, str):
            ret = obj
        else:
            ret = [json_keys_to_int(e) for e in obj]
    else:
        ret = obj
    return ret


class BackendShim(ProxyShim):
    def __init__(self, backend, *args, **kwargs):
        super().__init__(backend, *args, **kwargs)
        self.sessionproxy = SessionBackend(backend.conf._configpath)
        secrets = SecretsConfig(backend.conf._configpath)
        self.connpool = connection_pool_factory(
            backend.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            secrets, backend.conf.DB_PORT)
        self.validate_scriptkey = lambda k: k == secrets.ML_SCRIPT_KEY
        self.translator = gettext.translation(
            'cdedb', languages=('de',),
            localedir=str(backend.conf.REPOSITORY_PATH / 'i18n'))

    def _setup_requeststate(self, key):
        rs = RequestState(
            key, None, None, None, [], None, None,
            [], {}, "de", self.translator.gettext,
            self.translator.ngettext, None, None, key)
        rs.user = self.sessionproxy.lookupsession(key, "127.0.0.0")
        rs._conn = self.connpool[roles_to_db_role(rs.user.roles)]
        if self.validate_scriptkey(key):
            rs.user.roles.add("ml_script")
            rs._conn = self.connpool["cdb_persona"]
        rs.conn = rs._conn
        if "event" in rs.user.roles and hasattr(self._backend, "orga_info"):
            rs.user.orga = self._backend.orga_info(rs, rs.user.persona_id)
        if "ml" in rs.user.roles and hasattr(self._backend, "moderator_info"):
            rs.user.moderator = self._backend.moderator_info(
                rs, rs.user.persona_id)
        return rs

    def _wrapit(self, fun):
        """
        :type fun: callable
        """
        try:
            access_list = fun.access_list
        except AttributeError:
            if self._internal:
                access_list = fun.internal_access_list
            else:
                raise

        @functools.wraps(fun)
        def new_fun(key, *args, **kwargs):
            rs = self._setup_requeststate(key)
            if rs.user.roles & access_list:
                return fun(rs, *args, **kwargs)
            else:
                raise PrivilegeError("Not in access list.")
        return new_fun


class BackendUsingTest(unittest.TestCase):
    used_backends = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

    @classmethod
    def setUpClass(cls):
        classes = {
            "core": CoreBackend,
            "session": SessionBackend,
            "cde": CdEBackend,
            "event": EventBackend,
            "pastevent": PastEventBackend,
            "ml": MlBackend,
            "assembly": AssemblyBackend,
        }
        for backend in cls.used_backends:
            if backend == "session":
                setattr(cls, backend,
                        cls.initialize_raw_backend(classes[backend]))
            else:
                setattr(cls, backend, cls.initialize_backend(classes[backend]))

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    @staticmethod
    def initialize_raw_backend(backendcls):
        return backendcls(_BASICCONF.REPOSITORY_PATH
                          / _BASICCONF.TESTCONFIG_PATH)

    @staticmethod
    def initialize_backend(backendcls):
        return BackendShim(BackendUsingTest.initialize_raw_backend(backendcls),
                           internal=True)


class BackendTest(BackendUsingTest):
    used_backends = ("core",)

    def setUp(self):
        super().setUp()
        self.key = None

    def login(self, user, ip="127.0.0.0"):
        self.key = self.core.login(None, user['username'], user['password'],
                                   ip)
        return self.key


USER_DICT = {
    "anton": {
        'id': 1,
        'DB-ID': "DB-1-9",
        'username': "anton@example.cde",
        'password': "secret",
        'display_name': "Anton",
        'given_names': "Anton Armin A.",
        'family_name': "Administrator",
    },
    "berta": {
        'id': 2,
        'DB-ID': "DB-2-7",
        'username': "berta@example.cde",
        'password': "secret",
        'display_name': "Bertå",
        'given_names': "Bertålotta",
        'family_name': "Beispiel",
    },
    "charly": {
        'id': 3,
        'DB-ID': "DB-3-5",
        'username': "charly@example.cde",
        'password': "secret",
        'display_name': "Charly",
        'given_names': "Charly C.",
        'family_name': "Clown",
    },
    "daniel": {
        'id': 4,
        'DB-ID': "DB-4-3",
        'username': "daniel@example.cde",
        'password': "secret",
        'display_name': "Daniel",
        'given_names': "Daniel D.",
        'family_name': "Dino",
    },
    "emilia": {
        'id': 5,
        'DB-ID': "DB-5-1",
        'username': "emilia@example.cde",
        'password': "secret",
        'display_name': "Emilia",
        'given_names': "Emilia E.",
        'family_name': "Eventis",
    },
    "ferdinand": {
        'id': 6,
        'DB-ID': "DB-6-X",
        'username': "ferdinand@example.cde",
        'password': "secret",
        'display_name': "Ferdinand",
        'given_names': "Ferdinand F.",
        'family_name': "Findus",
    },
    "garcia": {
        'id': 7,
        'DB-ID': "DB-7-8",
        'username': "garcia@example.cde",
        'password': "secret",
        'display_name': "Garcia",
        'given_names': "Garcia G.",
        'family_name': "Generalis",
    },
    "hades": {
        'id': 8,
        'DB-ID': "DB-8-6",
        'username': None,
        'password': "secret",
        'display_name': None,
        'given_names': "Hades",
        'family_name': "Hell",
    },
    "inga": {
        'id': 9,
        'DB-ID': "DB-9-4",
        'username': "inga@example.cde",
        'password': "secret",
        'display_name': "Inga",
        'given_names': "Inga",
        'family_name': "Iota",
    },
    "janis": {
        'id': 10,
        'DB-ID': "DB-10-8",
        'username': "janis@example.cde",
        'password': "secret",
        'display_name': "Janis",
        'given_names': "Janis",
        'family_name': "Jalapeño",
    },
    "kalif": {
        'id': 11,
        'DB-ID': "DB-11-6",
        'username': "kalif@example.cde",
        'password': "secret",
        'display_name': "Kalif",
        'given_names': "Kalif ibn al-Ḥasan",
        'family_name': "Karabatschi",
    },
    "lisa": {
        'id': 12,
        'DB-ID': "DB-12-4",
        'username': None,
        'password': "secret",
        'display_name': "Lisa",
        'given_names': "Lisa",
        'family_name': "Lost",
    },
    "martin": {
        'id': 13,
        'DB-ID': "DB-13-2",
        'username': "martin@example.cde",
        'password': "secret",
        'display_name': "Martin",
        'given_names': "Martin",
        "family_name": "Meister",
    },
    "nina": {
        'id': 14,
        'DB-ID': "DB-14-0",
        'username': 'nina@example.cde',
        'password': "secret",
        'display_name': "nina",
        'given_names': "nina",
        'family_name': "Neubauer",
    },
    "olaf": {
        'id': 15,
        'DB-ID': "DB-15-9",
        'username': "olaf@example.cde",
        'password': "secret",
        'display_name': "Olaf",
        'given_names': "Olaf",
        "family_name": "Olafson",
    },
}


def as_users(*users):
    def wrapper(fun):
        @functools.wraps(fun)
        def new_fun(self, *args, **kwargs):
            for i, user in enumerate(users):
                with self.subTest(user=user):
                    if i > 0:
                        self.setUp()
                    kwargs['user'] = USER_DICT[user]
                    self.login(USER_DICT[user])
                    fun(self, *args, **kwargs)
        return new_fun
    return wrapper


def prepsql(sql):
    def decorator(fun):
        @functools.wraps(fun)
        def new_fun(*args, **kwargs):
            execsql(sql)
            return fun(*args, **kwargs)
        return new_fun
    return decorator


def execsql(sql):
    path = pathlib.Path("/tmp/test-cdedb-sql-commands.sql")
    chmod = ("chmod", "0644")
    psql = ("sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", "cdb_test", "-f")
    null = subprocess.DEVNULL
    with open(path, "w") as f:
        f.write(sql)
    subprocess.check_call(chmod + (str(path),), stdout=null)
    subprocess.check_call(psql + (str(path),), stdout=null)


class FrontendTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

    @classmethod
    def setUpClass(cls):
        app = Application(_BASICCONF.REPOSITORY_PATH
                          / _BASICCONF.TESTCONFIG_PATH)
        cls.app = webtest.TestApp(app, extra_environ={
            'REMOTE_ADDR': "127.0.0.0",
            'SERVER_PROTOCOL': "HTTP/1.1",
            'wsgi.url_scheme': 'https'})

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.app.reset()
        self.response = None  # type: webtest.TestResponse

    def basic_validate(self, verbose=False):
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('CdEDB – Fehler', texts[0])
        self.log_generation_time()

    def log_generation_time(self, response=None):
        if response is None:
            response = self.response
        if _BASICCONF.TIMING_LOG:
            with open(_BASICCONF.TIMING_LOG, 'a') as f:
                output = "{} {} {} {}\n".format(
                    response.request.path, response.request.method,
                    response.headers.get('X-Generation-Time'),
                    response.request.query_string)
                f.write(output)

    def get(self, *args, verbose=False, **kwargs):
        self.response = self.app.get(*args, **kwargs)
        self.basic_validate(verbose=verbose)

    def follow(self, **kwargs):
        oldresponse = self.response
        self.response = self.response.maybe_follow(**kwargs)
        if self.response != oldresponse:
            self.log_generation_time(oldresponse)

    def post(self, *args, verbose=False, **kwargs):
        self.response = self.app.post(*args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def submit(self, form, button="submitform", check_notification=True,
               verbose=False):
        method = form.method
        self.response = form.submit(button)
        self.follow()
        self.basic_validate(verbose=verbose)
        if method == "POST" and check_notification:
            # check that we acknowledged the POST with a notification
            self.assertIn("alert alert-success", self.response.text)

    def traverse(self, *links, verbose=False):
        for link in links:
            if 'index' not in link:
                link['index'] = 0
            try:
                self.response = self.response.click(**link)
            except IndexError as e:
                e.args += ('Error during traversal of {}'.format(link),)
                raise
            self.follow()
            self.basic_validate(verbose=verbose)

    def login(self, user, verbose=False):
        self.get("/", verbose=verbose)
        f = self.response.forms['loginform']
        f['username'] = user['username']
        f['password'] = user['password']
        self.submit(f, check_notification=False, verbose=verbose)

    def logout(self, verbose=False):
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False, verbose=verbose)

    def admin_view_profile(self, user, check=True, verbose=False):
        u = USER_DICT[user]
        self.traverse({'href': '^/$'}, verbose=verbose)
        f = self.response.forms['adminshowuserform']
        f['phrase'] = u["DB-ID"]
        self.submit(f)
        if check:
            self.assertTitle("{} {}".format(u['given_names'],
                                            u['family_name']))

    def realm_admin_view_profile(self, user, realm, verbose=False):
        u = USER_DICT[user]
        self.traverse({'href': '/{}/$'.format(realm)},
                      {'href': '/{}/search/user'.format(realm)},
                      verbose=verbose)
        id_field = 'personas.id' if realm in {'event', 'cde'} else 'id'
        f = self.response.forms['queryform']
        f['qsel_' + id_field].checked = True
        f['qop_' + id_field] = QueryOperators.equal.value
        f['qval_' + id_field] = u["id"]
        self.submit(f, verbose=verbose)
        self.traverse({'description': 'Profil'}, verbose=verbose)

    def fetch_mail(self):
        elements = self.response.lxml.xpath(
            "//div[@class='alert alert-info']/span/text()")

        def _extract_path(s):
            regex = r"E-Mail als (.*) auf der Festplatte gespeichert."
            ret = re.match(regex, s).group(1)
            return ret
        mails = [_extract_path(x)
                 for x in elements if x.startswith("E-Mail als ")]
        ret = []
        for path in mails:
            with open(path) as f:
                raw = f.read()
                parser = email.parser.Parser(policy=email.policy.default)
                msg = parser.parsestr(raw)
                ret.append(msg)
        return ret

    @staticmethod
    def fetch_link(msg, num=1):
        ret = None
        for line in msg.get_body().get_content().splitlines():
            if line.startswith('[{}] '.format(num)):
                ret = line.split(maxsplit=1)[-1]
        return ret

    def assertTitle(self, title):
        components = tuple(x.strip() for x in self.response.lxml.xpath(
            '/html/head/title/text()'))
        self.assertEqual("CdEDB –", components[0][:7])
        normalized = re.sub(r'\s+', ' ', components[0][7:].strip())
        self.assertEqual(title.strip(), normalized)

    def assertPresence(self, s, div="content", regex=False):
        if self.response.content_type == "text/plain":
            target = self.response.text
        else:
            content = self.response.lxml.xpath("//*[@id='{}']".format(div))[0]
            target = content.text_content()
        normalized = re.sub(r'\s+', ' ', target)
        if regex:
            self.assertTrue(re.search(s.strip(), normalized))
        else:
            self.assertIn(s.strip(), normalized)

    def assertNonPresence(self, s, div="content"):
        if self.response.content_type == "text/plain":
            self.assertNotIn(s.strip(), self.response.text)
        else:
            content = self.response.lxml.xpath("//*[@id='{}']".format(div))[0]
            self.assertNotIn(s.strip(), content.text_content())

    def assertLogin(self, name):
        span = self.response.lxml.xpath("//span[@id='displayname']")[0]
        self.assertEqual(name.strip(), span.text_content().strip())

    def assertValidationError(self, fieldname, message=""):
        """
        Check for a specific form input field to be highlighted as .has-error
        and a specific error message to be shown near the field.

        :param fieldname: The field's 'name' attribute
        :param message: The expected error message
        :raise AssertionError: If field is not found, field is not within
            .has-error container or error message is not found
        """
        node = self.response.lxml.xpath(
            '(//input|//select|//textarea)[@name="{}"]'.format(fieldname))
        if len(node) != 1:
            raise AssertionError("input with name \"{}\" not found"
                                 .format(fieldname))
        # From https://devhints.io/xpath#class-check
        container = node[0].xpath(
            "ancestor::*[contains(concat(' ',normalize-space(@class),' '),"
            "' has-error ')]")
        if not container:
            raise AssertionError(
                "input with name \"{}\" is not contained in an .has-error box"
                .format(fieldname))
        self.assertIn(message, container[0].text_content(),
                      "Expected error message not found near input with name "
                      "\"{}\""
                      .format(fieldname))

    def assertNoLink(self, href_pattern=None, tag='a', href_attr='href',
                     content=None, verbose=False):
        """Assert that no tag that matches specific criteria is found. Possible
        criteria include:

        * The tags href_attr matches the href_pattern (regex)
        * The tags content matches the content (regex)

        This is a ripoff of webtest.response._find_element, which is used by
        traverse internally.
        """
        href_pat = webtest.utils.make_pattern(href_pattern)
        content_pat = webtest.utils.make_pattern(content)

        def printlog(s):
            if verbose:
                print(s)

        for element in self.response.html.find_all(tag):
            el_html = str(element)
            el_content = element.decode_contents()
            printlog('Element: %r' % el_html)
            if not element.get(href_attr):
                printlog('  Skipped: no %s attribute' % href_attr)
                continue
            if href_pat and not href_pat(element[href_attr]):
                printlog("  Skipped: doesn't match href")
                continue
            if content_pat and not content_pat(el_content):
                printlog("  Skipped: doesn't match description")
                continue
            printlog("  Link found")
            raise AssertionError(
                "{} tag with {} == {} and content \"{}\" has been found."
                .format(tag, href_attr, element[href_attr], el_content))


StoreTrace = collections.namedtuple("StoreTrace", ['cron', 'data'])
MailTrace = collections.namedtuple(
    "MailTrace", ['realm', 'template', 'args', 'kwargs'])


class CronBackendShim:
    def __init__(self, cron, proxy, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cron = cron
        self._proxy = proxy

        self._funs = {}
        for name, fun in proxy._funs.items():
            self._funs[name] = self._wrapit(fun)

    def _wrapit(self, fun):
        @functools.wraps(fun)
        def new_fun(*args, **kwargs):
            rs = self._cron.make_request_state()
            return fun(rs, *args, **kwargs)
        return new_fun

    def __getattr__(self, name):
        if name in {"_funs", "_proxy", "_cron"}:
            raise AttributeError()
        try:
            return self._funs[name]
        except KeyError as e:
            raise AttributeError from e


class CronTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None
        self.stores = []

    @classmethod
    def setUpClass(cls):
        cls.cron = CronFrontend(_BASICCONF.REPOSITORY_PATH
                                / _BASICCONF.TESTCONFIG_PATH)
        cls.core = CronBackendShim(cls.cron, cls.cron.core.coreproxy)
        cls.cde = CronBackendShim(cls.cron, cls.cron.core.cdeproxy)
        cls.event = CronBackendShim(cls.cron, cls.cron.core.eventproxy)
        cls.assembly = CronBackendShim(cls.cron, cls.cron.core.assemblyproxy)
        cls.ml = CronBackendShim(cls.cron, cls.cron.core.mlproxy)

    def setUp(self):
        subprocess.check_call(("make", "sql-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.stores = []
        self.mails = []

        original_store = self.cron.core.set_cron_store

        @functools.wraps(self.cron.core.set_cron_store)
        def new_store(self_, rs, name, data):
            self.stores.append(StoreTrace(name, data))
            return original_store(rs, name, data)

        self.cron.core.set_cron_store = types.MethodType(new_store,
                                                         self.cron.core)

        for frontend in (self.cron.core, self.cron.cde, self.cron.event,
                         self.cron.assembly, self.cron.ml):
            original_do_mail = frontend.do_mail

            def latebindinghack(original_fun=original_do_mail, front=frontend):
                @functools.wraps(original_fun)
                def new_do_mail(self_, rs, name, *args, **kwargs):
                    self.mails.append(MailTrace(front.realm, name, args,
                                                kwargs))
                    return original_fun(rs, name, *args, **kwargs)
                return new_do_mail

            frontend.do_mail = types.MethodType(latebindinghack(), frontend)

    def execute(self, *args, check_stores=True):
        if not args:
            raise ValueError("Must specify jobs to run.")
        self.cron.execute(args)
        if check_stores:
            expectation = set(args) | {"_base"}
            self.assertEqual(expectation, set(s.cron for s in self.stores))
