#!/usr/bin/env python3

import datetime
import functools
import gettext
import inspect
import pathlib
import pytz
import re
import unittest
import subprocess
import sys
import time
import webtest

from cdedb.config import BasicConfig, SecretsConfig
from cdedb.frontend.application import Application
from cdedb.common import (
    do_singularization, ProxyShim, extract_roles, RequestState, User,
    roles_to_db_role, PrivilegeError, open_utf8)
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
    return NearlyNow(year=now.year, month=now.month, day=now.day, hour=now.hour,
                     minute=now.minute, second=now.second, tzinfo=pytz.utc)

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
        data = self.sessionproxy.lookupsession(key, "127.0.0.0")
        rs = RequestState(
            key, None, None, None, [], None, None,
            None, [], {}, "de", self.translator.gettext,
            self.translator.ngettext, None, None, key)
        vals = {k: data[k] for k in ('persona_id', 'username', 'given_names',
                                     'display_name', 'family_name')}
        rs.user = User(roles=extract_roles(data), **vals)
        rs._conn = self.connpool[roles_to_db_role(rs.user.roles)]
        if self.validate_scriptkey(key):
            rs.user.roles.add("ml_script")
            rs._conn = self.connpool["cdb_persona"]
        rs.conn = rs._conn
        if "event" in rs.user.roles and hasattr(self._backend, "orga_info"):
            rs.user.orga = self._backend.orga_info(rs, rs.user.persona_id)
        if "ml" in rs.user.roles and hasattr(self._backend, "moderator_info"):
            rs.user.moderator = self._backend.moderator_info(rs, rs.user.persona_id)
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
                setattr(cls, backend, cls.initialize_raw_backend(classes[backend]))
            else:
                setattr(cls, backend, cls.initialize_backend(classes[backend]))

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @staticmethod
    def initialize_raw_backend(backendcls):
        return backendcls(_BASICCONF.REPOSITORY_PATH / _BASICCONF.TESTCONFIG_PATH)

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
        self.key = self.core.login(None, user['username'], user['password'], ip)
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

class FrontendTest(unittest.TestCase):
    lock_file = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

    @classmethod
    def setUpClass(cls):
        app = Application(_BASICCONF.REPOSITORY_PATH / _BASICCONF.TESTCONFIG_PATH)
        cls.app = webtest.TestApp(app, extra_environ={
            'REMOTE_ADDR': "127.0.0.0",
            'SERVER_PROTOCOL': "HTTP/1.1",
            'wsgi.url_scheme': 'https'})

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.app.reset()
        self.response = None

    def basic_validate(self):
        if b"cgitb" in self.response.body:
            # This is a manual implementation of assertNotIn() to make the test output less verbose on failure.
            raise AssertionError("Found 'cgitb' in response body. A Python Exception seems to have occured.")
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('CdEDB – Fehler', texts[0])
        self.log_generation_time()

    def log_generation_time(self, response=None):
        if response is None:
            response = self.response
        if _BASICCONF.TIMING_LOG:
            with open_utf8(_BASICCONF.TIMING_LOG, 'a') as f:
                output = "{} {} {} {}\n".format(
                    response.request.path, response.request.method,
                    response.headers.get('X-Generation-Time'),
                    response.request.query_string)
                f.write(output)

    def get(self, *args, **kwargs):
        self.response = self.app.get(*args, **kwargs)
        self.basic_validate()

    def follow(self, **kwargs):
        oldresponse = self.response
        self.response = self.response.maybe_follow(**kwargs)
        if self.response != oldresponse:
            self.log_generation_time(oldresponse)

    def post(self, *args, **kwargs):
        self.response = self.app.post(*args, **kwargs)
        self.follow()
        self.basic_validate()

    def submit(self, form, button="submitform", check_notification=True):
        method = form.method
        self.response = form.submit(button)
        self.follow()
        self.basic_validate()
        if method == "POST" and check_notification:
            ## check that we acknowledged the POST with a notification
            self.assertIn("alert alert-success", self.response.text)

    def traverse(self, *links):
        for link in links:
            if 'index' not in link:
                link['index'] = 0
            self.response = self.response.click(**link)
            self.follow()
            self.basic_validate()

    def login(self, user):
        self.get("/")
        f = self.response.forms['loginform']
        f['username'] = user['username']
        f['password'] = user['password']
        self.submit(f, check_notification=False)

    def logout(self):
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False)

    def admin_view_profile(self, user, check=True):
        u = USER_DICT[user]
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = u["DB-ID"]
        self.submit(f)
        if check:
            self.assertTitle("{} {}".format(u['given_names'], u['family_name']))

    def realm_admin_view_profile(self, user, realm):
        u = USER_DICT[user]
        self.traverse({'href': '/{}/$'.format(realm)},
                      {'href': '/{}/search/user'.format(realm)})
        id_field = 'personas.id' if realm == 'event' else 'id'
        f = self.response.forms['queryform']
        f['qsel_' + id_field].checked = True
        f['qop_' + id_field] = QueryOperators.equal.value
        f['qval_' + id_field] = u["id"]
        self.submit(f)
        self.traverse({'description': 'Profil'})

    def fetch_mail(self):
        elements = self.response.lxml.xpath("//div[@class='alert alert-info']/span/text()")
        def _extract_path(s):
            regex = r"E-Mail als (.*) auf der Festplatte gespeichert."
            ret = re.match(regex, s).group(1)
            return ret
        mails = [_extract_path(x) for x in elements if x.startswith("E-Mail als ")]
        ret = []
        for path in mails:
            with open_utf8(path) as f:
                ret.append(f.read())
        return ret

    def assertTitle(self, title):
        components = tuple(x.strip() for x in self.response.lxml.xpath('/html/head/title/text()'))
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
