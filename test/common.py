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
import pytz
import re
import unittest
import subprocess
import tempfile
import types
import webtest
import urllib.parse

from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.session import SessionBackend
from cdedb.common import (PrivilegeError, ProxyShim, RequestState, glue,
                          roles_to_db_role, ALL_ADMIN_VIEWS,
                          ADMIN_VIEWS_COOKIE_NAME)
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
        self.validate_mlscriptkey = lambda k: k == secrets.ML_SCRIPT_KEY
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
        if self.validate_mlscriptkey(key):
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
        'url': '/core/persona/1/show?confirm_id=e473ed4768eb86ca72d2f25b4c39820f955333998ebab46ae7515d605aad99337165bca54b79ddbac55c969fa29e7c864f40b5925ab0828242dd460a5ad9296e--........................--1',
    },
    "berta": {
        'id': 2,
        'DB-ID': "DB-2-7",
        'username': "berta@example.cde",
        'password': "secret",
        'display_name': "Bertå",
        'given_names': "Bertålotta",
        'family_name': "Beispiel",
        'url': '/core/persona/2/show?confirm_id=3e95048cf6ddb0e7f52c3763e8d526c8aa0a40fe76e6e25119c0d151f280e43aef945a7fe1c639e4bc8cee5bb2e1bb8d31b5fb143593452c8799d3888da42ab4--........................--2',
    },
    "charly": {
        'id': 3,
        'DB-ID': "DB-3-5",
        'username': "charly@example.cde",
        'password': "secret",
        'display_name': "Charly",
        'given_names': "Charly C.",
        'family_name': "Clown",
        'url': '/core/persona/3/show?confirm_id=68a0f06c859a7043918078d335e4c30de57e443bd0df7e4db4f00146b826a8a5a5b41d90a76fb1796a4ce27853351f67677b33ac5abd10fb6aa0e3ec43fb3522--........................--3',
    },
    "daniel": {
        'id': 4,
        'DB-ID': "DB-4-3",
        'username': "daniel@example.cde",
        'password': "secret",
        'display_name': "Daniel",
        'given_names': "Daniel D.",
        'family_name': "Dino",
        'url': '/core/persona/4/show?confirm_id=eb44903b67e6d24ab7b83d4894a936e69d901b0d2ff422316df0389fbdd2b172779eef5e73c763fe087653736e9ef259c25c3282eb01a63ee47b034da6d5deb9--........................--4',
    },
    "emilia": {
        'id': 5,
        'DB-ID': "DB-5-1",
        'username': "emilia@example.cde",
        'password': "secret",
        'display_name': "Emilia",
        'given_names': "Emilia E.",
        'family_name': "Eventis",
        'url': '/core/persona/5/show?confirm_id=2dca2e7caff601a6ff6fcfb416bb0e858b9a5b2fb163d06c3896848d9da767e214d53783c851a22dfacebe96f1092b40b3073291c9bb4698ca12131a807d3b12--........................--5',
    },
    "ferdinand": {
        'id': 6,
        'DB-ID': "DB-6-X",
        'username': "ferdinand@example.cde",
        'password': "secret",
        'display_name': "Ferdinand",
        'given_names': "Ferdinand F.",
        'family_name': "Findus",
        'url': '/core/persona/6/show?confirm_id=e1c873304f28662bfbb4cca239e46afa4345f531c4b1de5254bea21459f9214d186656d051644f011c86605d2cd56c41b9a4b3cd1e94a1f75bb03b15b079575a--........................--6',
    },
    "garcia": {
        'id': 7,
        'DB-ID': "DB-7-8",
        'username': "garcia@example.cde",
        'password': "secret",
        'display_name': "Garcia",
        'given_names': "Garcia G.",
        'family_name': "Generalis",
        'url': '/core/persona/7/show?confirm_id=0dc9fd23f3680f7da0dd58637f36aa464c778174dc3b429c62efa357ea3dc238492377b370e95e9a9cbb2a9d594ab86cf5384d75dfb1828d33d3c38f2b337526--........................--7',
    },
    "hades": {
        'id': 8,
        'DB-ID': "DB-8-6",
        'username': None,
        'password': "secret",
        'display_name': None,
        'given_names': "Hades",
        'family_name': "Hell",
        'url': '/core/persona/8/show?confirm_id=d8a2fe52388652f2f6567668d8bbd53d3a502c4246dcbfe21476093e70c389d812c0c794e76ac77ebec36b98eafe957d533595708c8ac3ff5bd08f551c08d613--........................--8',
    },
    "inga": {
        'id': 9,
        'DB-ID': "DB-9-4",
        'username': "inga@example.cde",
        'password': "secret",
        'display_name': "Inga",
        'given_names': "Inga",
        'family_name': "Iota",
        'url': '/core/persona/9/show?confirm_id=c6fdba0e5972459120e7a6959b66500cf6cdddeb98d6cc4d32e008de598f9b7259b60d6c837ec6f437f5d0e1e66f4ae5c0d6b77c6d54257c858200b0aaf2b827--........................--9',
    },
    "janis": {
        'id': 10,
        'DB-ID': "DB-10-8",
        'username': "janis@example.cde",
        'password': "secret",
        'display_name': "Janis",
        'given_names': "Janis",
        'family_name': "Jalapeño",
        'url': '/core/persona/10/show?confirm_id=a83fda0f360d7c721d691f5de0756847de2b978215e640030b0d4a9fff81731ecce5bdb592b08010845805233f6ab1c19c8428ce0f115dfc52a33a4898d2651d--........................--10',
    },
    "kalif": {
        'id': 11,
        'DB-ID': "DB-11-6",
        'username': "kalif@example.cde",
        'password': "secret",
        'display_name': "Kalif",
        'given_names': "Kalif ibn al-Ḥasan",
        'family_name': "Karabatschi",
        'url': '/core/persona/11/show?confirm_id=63659c73d3726ca05f2921e4cbf653b93f7d64c257bed6a7ff1a3c7e0ab316255ae1ab2b43cc0f8d4d1ebb34f93d687ec35c6e6a0255a32ba3f05bcd22c51836--........................--11',
    },
    "lisa": {
        'id': 12,
        'DB-ID': "DB-12-4",
        'username': None,
        'password': "secret",
        'display_name': "Lisa",
        'given_names': "Lisa",
        'family_name': "Lost",
        'url': '/core/persona/12/show?confirm_id=6f79cd8bd417975952b50e1f76818f028e181f0f27e4ba02f521d28084370c14adbb9648aac73d1c3fd39aad7e261f9ea3db6ef6aac3cc2d6843541dc8ed3dd7--........................--12',
    },
    "martin": {
        'id': 13,
        'DB-ID': "DB-13-2",
        'username': "martin@example.cde",
        'password': "secret",
        'display_name': "Martin",
        'given_names': "Martin",
        'family_name': "Meister",
        'url': '/core/persona/13/show?confirm_id=92997c0b746b3b1af469ffe2e66d46fec3be496f5837fafc36585068a0ea88a6ad698611b7e90352f5fbad24e50266ba22daf2b89f041e6b29058a49b0c6d5a0--........................--13',
    },
    "nina": {
        'id': 14,
        'DB-ID': "DB-14-0",
        'username': 'nina@example.cde',
        'password': "secret",
        'display_name': "Nina",
        'given_names': "Nina",
        'family_name': "Neubauer",
        'url': '/core/persona/14/show?confirm_id=ecb8159a33dfbbece4739f19d54e82730fea0c05310c7420340cd1a1700d27811f8593952099e15c8ffffd049892fe2b88428dc99f14b5f34ba2610d81d5ba58--........................--14',
    },
    "olaf": {
        'id': 15,
        'DB-ID': "DB-15-9",
        'username': "olaf@example.cde",
        'password': "secret",
        'display_name': "Olaf",
        'given_names': "Olaf",
        'family_name': "Olafson",
        'url': '/core/persona/15/show?confirm_id=eafa312e68323aed7f782c56213a1d16bca7db362d7114d78f1f248246d2c1c052bda0caf2cce7c713b372ee5ad769acac977da3d0b9781a2ce44686233422d8--........................--15',
    },
    "paul": {
        'id': 16,
        'DB-ID': "DB-16-7",
        'username': "paulchen@example.cde",
        'password': "secret",
        'display_name': "Paul",
        'given_names': "Paulchen",
        'family_name': "Panther",
        'url': '/core/persona/16/show?confirm_id=c8ecaaddad592ce35885688fc04f2a2528a37f7f11c70004367747f3d2c717a559b56596f3a2133354cebe5f28aaaec6d314d54b2f111a3e66146965456518fb--........................--16',
    },
    "quintus": {
        'id': 17,
        'DB-ID': "DB-17-5",
        'username': "quintus@example.cde",
        'password': "secret",
        'display_name': "Quintus",
        'given_names': "Quintus",
        'family_name': "da Quirm",
        'url': '/core/persona/17/show?confirm_id=251bf5e54f8c188eb4ad6397ce45f4d0ccedad0e3df8fc5a303df7e4f2da0ac68d00b40c688fda4dc6d8785515af66661baa1c51529a6664b5e2e2c90b3fd379--........................--17',
    },
    "rowena": {
        'id': 18,
        'DB-ID': "DB-18-3",
        'username': "rowena@example.cde",
        'password': "secret",
        'display_name': "Rowena",
        'given_names': "Rowena",
        'family_name': "Ravenclaw",
        'url': '/core/persona/18/show?confirm_id=b3f4087f9de6a856126280429844518e4199d37426e6dfdcd01f2c3d19d7dd92ac4506148a7467ccabdac29bc3aef38f260c861868c41eab1f4bacd2f67f8b3a--........................--18',
    },
    "vera": {
        'id': 22,
        'DB-ID': "DB-22-1",
        'username': "vera@example.cde",
        'password': "secret",
        'display_name': "Vera",
        'given_names': "Vera",
        'family_name': "Verwaltung",
        'url': '/core/persona/22/show?confirm_id=e5f45f87cc90d3b757759a5338cfff429073cc9c764e476ede103f46e6566165d0d37fb9502f11008ff6be704fc2d470bfe99ef82d64556f2826246ab90a3b7a--........................--22',
    },
    "werner": {
        'id': 23,
        'DB-ID': "DB-23-X",
        'username': "werner@example.cde",
        'password': "secret",
        'display_name': "Werner",
        'given_names': "Werner",
        'family_name': "Wahlleitung",
        'url': '/core/persona/23/show?confirm_id=eddec5b8de0e99312c0703c4e79974e25ef7736f2da7d7f5d750258543022eb0bc2f56801108c9db77bd2797f4820981f84d882001823391abc408f78b7b6cd4--........................--23',
    },
    "annika": {
        'id': 27,
        'DB-ID': "DB-27-2",
        'username': "annika@example.cde",
        'password': "secret",
        'display_name': "Annika",
        'given_names': "Annika",
        'family_name': "Akademieteam",
        'url': '/core/persona/27/show?confirm_id=a901d4e174592bee3de675413c5a10e578f04205ec2fe9a4527238f2502a2ea3f4202237eddd06dfc10dd05b17338a9afd4afec2735f1e888b36df5352c19c3b--........................--27',
    },
    "farin": {
        'id': 32,
        'DB-ID': "DB-32-9",
        'username': "farin@example.cde",
        'password': "secret",
        'display_name': "Farin",
        'given_names': "Farin",
        'family_name': "Finanzvorstand",
        'url': '/core/persona/32/show?confirm_id=fded21fb67399bdf3d7d091ade52be13663d8be45f444fc3a94488fccf8fc3980a1f5a5a83dc2a4967563f8d733cd740939b544e7c1042880429a7109a21343e--........................--32',
    },
    "akira": {
        'id': 100,
        'DB-ID': "DB-100-7",
        'username': "akira@example.cde",
        'password': "secret",
        'display_name': "Akira",
        'given_names': "Akira",
        'family_name': "Abukara",
        'url': '/core/persona/100/show?confirm_id=4d5235e5867d9d5fc4e0e472609ca4b7417c5c9b80b0e5de0c2aa976e09a0eab3e82f10eac65615ea4678dcc2f0853af4f45df1699814ff07fecb3305ec22c0d--........................--100',
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

        # set `do_scrap` to True to capture a snapshot of all visited pages
        cls.do_scrap = "SCRAP_ENCOUNTERED_PAGES" in os.environ
        if cls.do_scrap:
            # create a temporary directory and print it
            cls.scrap_path = tempfile.mkdtemp()
            print(cls.scrap_path)

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
