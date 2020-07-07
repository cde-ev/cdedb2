#!/usr/bin/env python3

import collections.abc
import datetime
import email.parser
import email.policy
import functools
import gettext
import inspect
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.parse
import json
import io
import PIL.Image
import time

from typing import TypeVar, cast, Dict, List

import pytz
import webtest

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.common import AbstractBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.session import SessionBackend
from cdedb.common import (
    ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS, PrivilegeError, RequestState, n_,
    roles_to_db_role, unwrap, PathLike, CdEDBObject, CdEDBObjectMap,
)
from cdedb.config import BasicConfig, SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.application import Application
from cdedb.frontend.cron import CronFrontend
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


def create_mock_image(file_type: str = "png") -> bytes:
    """This returns a bytes object representing a picture of the given type.

    The picture will pass validation by the `profilepic` validator.
    """
    afile = io.BytesIO()
    image = PIL.Image.new('RGBA', (1000, 1000), color=(255, 0, 0))
    image.save(afile, file_type)
    afile.seek(0)
    return afile.read()


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


def read_sample_data(filename: PathLike = "/cdedb2/test/ancillary_files/"
                                          "sample_data.json"
                     ) -> Dict[str, CdEDBObjectMap]:
    """Helper to turn the sample data from the JSON file into usable format."""
    with open(filename, "r", encoding="utf8") as f:
        sample_data: Dict[str, List[CdEDBObject]] = json.load(f)
    ret: Dict[str, CdEDBObjectMap] = {}
    for table, table_data in sample_data.items():
        data = {}
        _id = 1
        for e in table_data:
            _id = e.get('id', _id)
            assert _id not in data
            data[_id] = e
            _id += 1
        ret[table] = data
    return ret


B = TypeVar("B", bound=AbstractBackend)


def make_backend_shim(backend: B, internal=False) -> B:
    """Wrap a backend to only expose functions with an access decorator.

    If we used an actual RPC mechanism, this would do some additional
    lifting to accomodate this.

    We need to use a function so we can cast the return value.
    We also need to use an inner class so we can provide __getattr__.

    This is similar to the normal make_proxy but encorporates a different wrapper
    """

    sessionproxy = SessionBackend(backend.conf._configpath)
    secrets = SecretsConfig(backend.conf._configpath)
    connpool = connection_pool_factory(
        backend.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
        secrets, backend.conf["DB_PORT"])
    translator = gettext.translation(
        'cdedb', languages=('de',),
        localedir=str(backend.conf["REPOSITORY_PATH"] / 'i18n'))

    def setup_requeststate(key):
        sessionkey = None
        apitoken = None

        # we only use one slot to transport the key (for simplicity and
        # probably for historic reasons); the following lookup process
        # mimicks the one in frontend/application.py
        user = sessionproxy.lookuptoken(key, "127.0.0.0")
        if user.roles == {'anonymous'}:
            user = sessionproxy.lookupsession(key, "127.0.0.0")
            sessionkey = key
        else:
            apitoken = key

        rs = RequestState(
            sessionkey=sessionkey, apitoken=apitoken, user=user, request=None,
            response=None, notifications=[], mapadapter=None, requestargs=None,
            errors=[], values={}, lang="de", gettext=translator.gettext,
            ngettext=translator.ngettext, coders=None, begin=None)
        rs._conn = connpool[roles_to_db_role(rs.user.roles)]
        rs.conn = rs._conn
        if "event" in rs.user.roles and hasattr(backend, "orga_info"):
            rs.user.orga = backend.orga_info(rs, rs.user.persona_id)
        if "ml" in rs.user.roles and hasattr(backend, "moderator_info"):
            rs.user.moderator = backend.moderator_info(
                rs, rs.user.persona_id)
        return rs

    class Proxy():
        def __getattr__(self, name):
            attr = getattr(backend, name)
            if any([
                not getattr(attr, "access", False),
                getattr(attr, "internal", False) and not internal,
                not callable(attr)
            ]):
                raise PrivilegeError(
                    n_("Attribute %(name)s not public"), {"name": name})

            @functools.wraps(attr)
            def wrapper(key, *args, **kwargs):
                rs = setup_requeststate(key)
                return attr(rs, *args, **kwargs)

            return wrapper

    return cast(B, Proxy())


class MyTextTestResult(unittest.TextTestResult):
    """Subclasing the TestResult object to fix the CLI reporting."""

    def __init__(self, *args, **kwargs):
        super(MyTextTestResult, self).__init__(*args, **kwargs)
        self._subTestErrors = []
        self._subTestFailures = []
        self._subTestSkips = []

    def startTest(self, test):
        super(MyTextTestResult, self).startTest(test)
        self._subTestErrors = []
        self._subTestFailures = []
        self._subTestSkips = []

    def addSubTest(self, test, subtest, err):
        super(MyTextTestResult, self).addSubTest(test, subtest, err)
        if err is not None:
            if issubclass(err[0], subtest.failureException):
                errors = self._subTestFailures
            else:
                errors = self._subTestErrors
            errors.append(err)

    def stopTest(self, test):
        super(MyTextTestResult, self).stopTest(test)
        # Print a comprehensive list of failures and errors in subTests.
        output = []
        if self._subTestErrors:
            l = len(self._subTestErrors)
            if self.showAll:
                s = "ERROR" + ("({})".format(l) if l > 1 else "")
            else:
                s = "E" * l
            output.append(s)
        if self._subTestFailures:
            l = len(self._subTestFailures)
            if self.showAll:
                s = "FAIL" + ("({})".format(l) if l > 1 else "")
            else:
                s = "F" * l
            output.append(s)
        if self._subTestSkips:
            if self.showAll:
                s = "skipped {}".format(", ".join(
                    "{0!r}".format(r) for r in self._subTestSkips))
            else:
                s = "s" * len(self._subTestSkips)
            output.append(s)
        if output:
            if self.showAll:
                self.stream.writeln(", ".join(output))
            else:
                self.stream.write("".join(output))
                self.stream.flush()

    def addSkip(self, test, reason):
        # Purposely override the parents method, to not print the skip here.
        super(unittest.TextTestResult, self).addSkip(test, reason)
        self._subTestSkips.append(reason)


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

        cls.sample_data = read_sample_data()

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    @staticmethod
    def initialize_raw_backend(backendcls):
        return backendcls()

    @staticmethod
    def initialize_backend(backendcls):
        return make_backend_shim(
            BackendUsingTest.initialize_raw_backend(backendcls), internal=True)


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
        'family_name': "Meister",
    },
    "nina": {
        'id': 14,
        'DB-ID': "DB-14-0",
        'username': 'nina@example.cde',
        'password': "secret",
        'display_name': "Nina",
        'given_names': "Nina",
        'family_name': "Neubauer",
    },
    "olaf": {
        'id': 15,
        'DB-ID': "DB-15-9",
        'username': "olaf@example.cde",
        'password': "secret",
        'display_name': "Olaf",
        'given_names': "Olaf",
        'family_name': "Olafson",
    },
    "paul": {
        'id': 16,
        'DB-ID': "DB-16-7",
        'username': "paulchen@example.cde",
        'password': "secret",
        'display_name': "Paul",
        'given_names': "Paulchen",
        'family_name': "Panther",
    },
    "quintus": {
        'id': 17,
        'DB-ID': "DB-17-5",
        'username': "quintus@example.cde",
        'password': "secret",
        'display_name': "Quintus",
        'given_names': "Quintus",
        'family_name': "da Quirm",
    },
    "rowena": {
        'id': 18,
        'DB-ID': "DB-18-3",
        'username': "rowena@example.cde",
        'password': "secret",
        'display_name': "Rowena",
        'given_names': "Rowena",
        'family_name': "Ravenclaw",
    },
    "vera": {
        'id': 22,
        'DB-ID': "DB-22-1",
        'username': "vera@example.cde",
        'password': "secret",
        'display_name': "Vera",
        'given_names': "Vera",
        'family_name': "Verwaltung",
    },
    "werner": {
        'id': 23,
        'DB-ID': "DB-23-X",
        'username': "werner@example.cde",
        'password': "secret",
        'display_name': "Werner",
        'given_names': "Werner",
        'family_name': "Wahlleitung",
    },
    "annika": {
        'id': 27,
        'DB-ID': "DB-27-2",
        'username': "annika@example.cde",
        'password': "secret",
        'display_name': "Annika",
        'given_names': "Annika",
        'family_name': "Akademieteam",
    },
    "farin": {
        'id': 32,
        'DB-ID': "DB-32-9",
        'username': "farin@example.cde",
        'password': "secret",
        'display_name': "Farin",
        'given_names': "Farin",
        'family_name': "Finanzvorstand",
    },
    "akira": {
        'id': 100,
        'DB-ID': "DB-100-7",
        'username': "akira@example.cde",
        'password': "secret",
        'display_name': "Akira",
        'given_names': "Akira",
        'family_name': "Abukara",
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
                    if user is "anonymous":
                        kwargs['user'] = None
                        self.get('/')
                    else:
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
        app = Application()
        lang = "de"
        cls.gettext = app.translations[lang].gettext
        cls.app = webtest.TestApp(app, extra_environ={
            'REMOTE_ADDR': "127.0.0.0",
            'SERVER_PROTOCOL': "HTTP/1.1",
            'wsgi.url_scheme': 'https'})

        # set `do_scrap` to True to capture a snapshot of all visited pages
        cls.do_scrap = "SCRAP_ENCOUNTERED_PAGES" in os.environ
        if cls.do_scrap:
            # create a temporary directory and print it
            cls.scrap_path = tempfile.mkdtemp()
            print(cls.scrap_path, file=sys.stderr)

        cls.sample_data = read_sample_data()

    @classmethod
    def tearDownClass(cls):
        if cls.do_scrap:
            # make scrap_path directory and content publicly readable
            folder = pathlib.Path(cls.scrap_path)
            folder.chmod(0o0755)  # 0755/drwxr-xr-x
            for file in folder.iterdir():
                file.chmod(0o0644)  # 0644/-rw-r--r--

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.app.reset()
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(ALL_ADMIN_VIEWS))
        self.response = None  # type: webtest.TestResponse

    def basic_validate(self, verbose=False):
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('CdEDB – Fehler', texts[0])
            self.scrap()
        self.log_generation_time()

    def scrap(self):
        if self.do_scrap and self.response.status_int // 100 == 2:
            # path without host but with query string - capped at 64 chars
            url = urllib.parse.quote_plus(self.response.request.path_qs)[:64]
            with tempfile.NamedTemporaryFile(dir=self.scrap_path, suffix=url, delete=False) as f:
                # create a temporary file in scrap_path with url as a suffix
                # persisting after process completion and dump the response to it
                f.write(self.response.body)

    def log_generation_time(self, response=None):
        if response is None:
            response = self.response
        if _BASICCONF["TIMING_LOG"]:
            with open(_BASICCONF["TIMING_LOG"], 'a') as f:
                output = "{} {} {} {}\n".format(
                    response.request.path, response.request.method,
                    response.headers.get('X-Generation-Time'),
                    response.request.query_string)
                f.write(output)

    def get(self, *args, verbose=False, **kwargs):
        self.response: webtest.TestResponse = self.app.get(*args, **kwargs)
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
               verbose=False, value=None):
        method = form.method
        self.response = form.submit(button, value=value)
        self.follow()
        self.basic_validate(verbose=verbose)
        if method == "POST" and check_notification:
            # check that we acknowledged the POST with a notification
            success_str = "alert alert-success"
            target = self.response.text
            if verbose:
                self.assertIn(success_str, target)
            elif success_str not in target:
                raise AssertionError(
                    "Post request did not produce success notification.")

    def traverse(self, *links, verbose=False):
        for link in links:
            if 'index' not in link:
                link['index'] = 0
            try:
                self.response = self.response.click(**link, verbose=verbose)
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

    def get_content(self, div="content"):
        if self.response.content_type == "text/plain":
            return self.response.text
        tmp = self.response.lxml.xpath("//*[@id='{}']".format(div))
        if not tmp:
            raise AssertionError("Div not found.", div)
        content = tmp[0]
        return content.text_content()

    def assertCheckbox(self, status, id):
        tmp = self.response.html.find_all(id=id)
        if not tmp:
            raise AssertionError("Id not found.", id)
        if len(tmp) != 1:
            raise AssertionError("More or less then one hit.", id)
        checkbox = tmp[0]
        if "data-checked" not in checkbox.attrs:
            raise ValueError("Id doesnt belong to a checkbox", id)
        self.assertEqual(str(status), checkbox['data-checked'])

    def assertPresence(self, s, div="content", regex=False, exact=False):
        target = self.get_content(div)
        normalized = re.sub(r'\s+', ' ', target)
        if regex:
            self.assertTrue(re.search(s.strip(), normalized))
        elif exact:
            self.assertEqual(s.strip(), normalized.strip())
        else:
            self.assertIn(s.strip(), normalized)

    def assertNonPresence(self, s, div="content", check_div=True):
        if self.response.content_type == "text/plain":
            self.assertNotIn(s.strip(), self.response.text)
        else:
            try:
                content = self.response.lxml.xpath("//*[@id='{}']".format(div))[0]
                self.assertNotIn(s.strip(), content.text_content())
            except IndexError as e:
                if check_div:
                    raise
                else:
                    pass

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

    def log_pagination(self, title, logs):
        """Helper function to test the logic of the log pagination.

        This should be called from every frontend log, to ensure our pagination
        works. Logs must contain at least 9 log entries.

        :type title: str
        :param title: of the Log page, like "Userdata-Log"
        :type logs: [{id: LogCode}]
        :param logs: list of log entries mapped to their LogCode
        """
        # check the landing page
        f = self.response.forms['logshowform']
        total = len(logs)
        self._log_subroutine(title, logs, start=1,
                             end=total if total < 50 else 50)

        # check a combination of offset and length with 0th page
        length = total // 3
        if length % 2 == 0:
            length -= 1
        offset = 1

        f['length'] = length
        f['offset'] = offset
        self.submit(f)

        # starting at the 0th page, ...
        self.traverse({'linkid': 'pagination-0'})
        # we store the absolute values of start and end in an array, because
        # they must not change when we iterate in different ways
        starts = [1]
        ends = [length - offset - 1]

        # ... iterate over all pages:
        # - by using the 'next' button
        while ends[-1] < total:
            self._log_subroutine(title, logs, start=starts[-1], end=ends[-1])
            self.traverse({'linkid': 'pagination-next'})
            starts.append(ends[-1] + 1)
            ends.append(ends[-1] + length)
        self.assertNoLink(content='›')
        self._log_subroutine(title, logs, start=starts[-1], end=ends[-1])

        # - by using the 'previous' button
        for start, end in zip(starts[:0:-1], ends[:0:-1]):
            self._log_subroutine(title, logs, start=start, end=end)
            self.traverse({'linkid': 'pagination-previous'})
        self.assertNoLink(content='‹')
        self._log_subroutine(title, logs, start=starts[0], end=ends[0])

        # - by using the page number buttons
        for page, (start, end) in enumerate(zip(starts, ends)):
            self.traverse({'linkid': f'pagination-{page}'})
            self._log_subroutine(title, logs, start=start, end=end)
        self.assertNoLink(content='›')

        # check first-page button (result in offset = 0)
        self.traverse({'linkid': 'pagination-first'})
        self.assertNoLink(content='‹')
        self._log_subroutine(title, logs, start=1, end=length)

        # there must not be a 0th page, because length is a multiple of offset
        self.assertNonPresence("0", div='log-pagination')

        # check last-page button (results in offset = None)
        self.traverse({'linkid': 'pagination-last'})
        self.assertNoLink(content='›')
        self._log_subroutine(
            title, logs, start=length * ((total - 1) // length) + 1, end=total)

        # tidy up the form
        f["offset"] = None
        f["length"] = None
        self.submit(f)

    def _log_subroutine(self, title, all_logs, start, end):
        total = len(all_logs)
        self.assertTitle(f"{title} [{start}–{end} von {total}]")

        if end > total:
            end = total

        # adapt slicing to our count of log entries
        logs = all_logs[start-1:end]
        for index, log in enumerate(logs, start=1):
            log_id = unwrap(log.keys())
            log_code = unwrap(log)
            log_code_str = self.gettext(str(log_code))
            self.assertPresence(log_code_str, div=f"{index}-{log_id}")

    def check_sidebar(self, ins, out):
        """Helper function to check the (in)visibility of sidebar elements.

        Raise an error if an element is in the sidebar and not in ins.

        :type ins: [str]
        :param ins: elements which are in the sidebar
        :param out: elements which are not in the sidebar
        :return: None
        """
        sidebar = self.response.html.find(id="sidebar-navigation")
        present = {nav_point.get_text().strip()
                   for nav_point in sidebar.find_all("a")}
        for nav_point in ins:
            self.assertPresence(nav_point, div='sidebar-navigation')
            present -= {nav_point}
        for nav_point in out:
            self.assertNonPresence(nav_point, div='sidebar-navigation')
        if present:
            raise AssertionError(
                f"Unexpected sidebar elements '{present}' found.")

    def _click_admin_view_button(self, label, current_state=None):
        """
        Helper function for checking the disableable admin views

        This function searches one of the buttons in the adminviewstoggleform
        (by its label), optionally checks this button's state, and submits
        the form using this button's value to enable/disable the corresponding
        admin view(s).

        :param label: A regex used to find the correct admin view button
        :type label: str or re.Pattern
        :param current_state: If not None, the admin view button's active state
            is checked to be equal to this boolean
        :type current_state: bool or None
        :return: The button element to perform further checks
        :rtype: BeautifulSoup element
        """
        f = self.response.forms['adminviewstoggleform']
        button = self.response.html\
            .find(id="adminviewstoggleform")\
            .find(text=label)\
            .parent
        if current_state is not None:
            if current_state:
                self.assertIn("active", button['class'])
            else:
                self.assertNotIn("active", button['class'])
        self.submit(f, 'view_specifier', False, value=button['value'])
        return button

    def reload_and_check_form(self, form, link, max_tries: int = 42,
                              waittime: float = 0.1, fail: bool = True) -> None:
        """Helper to repeatedly reload a page until a certain form is present.

        This is mostly required for the "Semesterverwaltung".
        """
        count = 0
        while count < max_tries:
            time.sleep(waittime)
            self.traverse(link)
            if form in self.response.forms:
                break
            count += 1
        else:
            if fail:
                self.fail(f"Form {form} not found after {count} reloads.")


StoreTrace = collections.namedtuple("StoreTrace", ['cron', 'data'])
MailTrace = collections.namedtuple(
    "MailTrace", ['realm', 'template', 'args', 'kwargs'])


class CronBackendShim:
    def __init__(self, cron, proxy):
        self._cron = cron
        self._proxy = proxy

    def _wrapit(self, fun):
        @functools.wraps(fun)
        def new_fun(*args, **kwargs):
            rs = self._cron.make_request_state()
            return fun(rs, *args, **kwargs)
        return new_fun

    def __getattr__(self, name):
        if name in {"_proxy", "_cron"}:
            raise AttributeError()
        attr = getattr(self._proxy, name)
        return self._wrapit(attr)


class CronTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None
        self.stores = []

    @classmethod
    def setUpClass(cls):
        cls.cron = CronFrontend()
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
