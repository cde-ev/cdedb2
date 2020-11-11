#!/usr/bin/env python3

import collections.abc
import datetime
import email.parser
import email.message
import email.policy
import enum
import functools
import gettext
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import json
import io
import PIL.Image
import time
import copy
import decimal

from types import TracebackType
from typing import (
    TypeVar, cast, Dict, List, Optional, Type, Callable, AnyStr, Set, Union,
    NamedTuple, MutableMapping, Any, no_type_check, Iterable, Tuple, TextIO, ClassVar,
    Collection, Sequence
)

import pytz
import webtest
import webtest.utils

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
    roles_to_db_role, PathLike, CdEDBObject, CdEDBObjectMap, now,
)
from cdedb.config import BasicConfig, SecretsConfig, Config
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.application import Application
from cdedb.frontend.cron import CronFrontend
from cdedb.frontend.common import AbstractFrontend
from cdedb.query import QueryOperators

_BASICCONF = BasicConfig()


def check_test_setup() -> None:
    """Raise a RuntimeError if the vm is ill-equipped for performing tests."""
    if pathlib.Path("/OFFLINEVM").exists():
        raise RuntimeError("Cannot run tests in an Offline-VM.")
    if pathlib.Path("/PRODUCTIONVM").exists():
        raise RuntimeError("Cannot run tests in Production-VM.")
    if not os.environ.get('CDEDB_TEST'):
        raise RuntimeError("Not configured for test (CDEDB_TEST unset).")


class NearlyNow(datetime.datetime):
    """This is something, that equals an automatically generated timestamp.

    Since automatically generated timestamp are not totally predictible,
    we use this to avoid nasty work arounds.
    """

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, datetime.datetime):
            delta = self - other
            return (datetime.timedelta(minutes=10) > delta
                    > datetime.timedelta(minutes=-10))
        return False

    def __ne__(self, other: Any) -> bool:
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


def nearly_now() -> NearlyNow:
    """Create a NearlyNow."""
    now = datetime.datetime.now(pytz.utc)
    return NearlyNow(
        year=now.year, month=now.month, day=now.day, hour=now.hour,
        minute=now.minute, second=now.second, tzinfo=pytz.utc)


T = TypeVar("T")


@no_type_check
def json_keys_to_int(obj: T) -> T:
    """Convert dict keys to integers if possible.

    This is a restriction of the JSON format allowing only string keys.
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
        data: CdEDBObjectMap = {}
        _id = 1
        for e in table_data:
            _id = e.get('id', _id)
            assert _id not in data
            e['id'] = _id
            data[_id] = e
            _id += 1
        ret[table] = data
    return ret


B = TypeVar("B", bound=AbstractBackend)


def make_backend_shim(backend: B, internal: bool = False) -> B:
    """Wrap a backend to only expose functions with an access decorator.

    If we used an actual RPC mechanism, this would do some additional
    lifting to accomodate this.

    We need to use a function so we can cast the return value.
    We also need to use an inner class so we can provide __getattr__.

    This is similar to the normal make_proxy but encorporates a different
    wrapper.
    """

    sessionproxy = SessionBackend(backend.conf._configpath)
    secrets = SecretsConfig(backend.conf._configpath)
    connpool = connection_pool_factory(
        backend.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
        secrets, backend.conf["DB_PORT"])
    translator = gettext.translation(
        'cdedb', languages=['de'],
        localedir=str(backend.conf["REPOSITORY_PATH"] / 'i18n'))

    def setup_requeststate(key: Optional[str], ip: str = "127.0.0.0"
                           ) -> RequestState:
        """
        Turn a provided sessionkey or apitoken into a RequestState object.

        This is used to wrap backend calls from the test suite, so we do not
        have to handle the RequestState in the tests.
        """
        sessionkey = None
        apitoken = None

        # we only use one slot to transport the key (for simplicity and
        # probably for historic reasons); the following lookup process
        # mimicks the one in frontend/application.py
        user = sessionproxy.lookuptoken(key, ip)
        if user.roles == {'anonymous'}:
            user = sessionproxy.lookupsession(key, ip)
            sessionkey = key
        else:
            apitoken = key

        rs = RequestState(
            sessionkey=sessionkey, apitoken=apitoken, user=user,
            request=None, notifications=[], mapadapter=None,  # type: ignore
            requestargs=None, errors=[], values=None, lang="de",
            gettext=translator.gettext, ngettext=translator.ngettext,
            coders=None, begin=now())
        rs._conn = connpool[roles_to_db_role(rs.user.roles)]
        rs.conn = rs._conn
        if "event" in rs.user.roles and hasattr(backend, "orga_info"):
            rs.user.orga = backend.orga_info(  # type: ignore
                rs, rs.user.persona_id)
        if "ml" in rs.user.roles and hasattr(backend, "moderator_info"):
            rs.user.moderator = backend.moderator_info(  # type: ignore
                rs, rs.user.persona_id)
        if "assembly" in rs.user.roles and hasattr(backend, "presider_info"):
            rs.user.presider = backend.presider_info(  # type: ignore
                rs, rs.user.persona_id)
        return rs

    class Proxy:
        """
        Wrap calls to the backend in a access check and provide a RequestState.
        """

        def __getattr__(self, name: str) -> Callable[..., Any]:
            attr = getattr(backend, name)
            if any([
                not getattr(attr, "access", False),
                getattr(attr, "internal", False) and not internal,
                not callable(attr)
            ]):
                raise PrivilegeError(
                    n_("Attribute %(name)s not public"), {"name": name})

            @functools.wraps(attr)
            def wrapper(key: str, *args: Any, **kwargs: Any) -> Any:
                rs = setup_requeststate(key)
                return attr(rs, *args, **kwargs)

            return wrapper

        def __setattr__(self, key: str, value: Any) -> None:
            return setattr(backend, key, value)

    return cast(B, Proxy())


ExceptionInfo = Union[
    Tuple[Type[BaseException], BaseException, TracebackType],
    Tuple[None, None, None], None]


class MyTextTestResult(unittest.TextTestResult):
    """Subclass the TextTestResult object to fix the CLI reporting.

    We keep track of the errors, failures and skips occurring in SubTests,
    and print a summary at the end of the TestCase itself.
    """

    def __init__(self, stream: TextIO, descriptions: bool, verbosity: int) -> None:
        self.showAll: bool
        self.stream: TextIO
        super().__init__(stream, descriptions, verbosity)
        self._subTestErrors: List[ExceptionInfo] = []
        self._subTestFailures: List[ExceptionInfo] = []
        self._subTestSkips: List[str] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._subTestErrors = []
        self._subTestFailures = []
        self._subTestSkips = []

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase,
                   err: Optional[ExceptionInfo]) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None and err[0] is not None:
            if issubclass(err[0], subtest.failureException):
                errors = self._subTestFailures
            else:
                errors = self._subTestErrors
            errors.append(err)

    def stopTest(self, test: unittest.TestCase) -> None:
        super().stopTest(test)
        # Print a comprehensive list of failures and errors in subTests.
        output = []
        if self._subTestErrors:
            length = len(self._subTestErrors)
            if self.showAll:
                s = "ERROR" + (f"({length})" if length > 1 else "")
            else:
                s = "E" * length
            output.append(s)
        if self._subTestFailures:
            length = len(self._subTestFailures)
            if self.showAll:
                s = "FAIL" + (f"({length})" if length > 1 else "")
            else:
                s = "F" * length
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
                self.stream.writeln(", ".join(output))  # type: ignore
            else:
                self.stream.write("".join(output))
                self.stream.flush()

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        # Purposely override the parents method, to not print the skip here.
        super(unittest.TextTestResult, self).addSkip(test, reason)
        self._subTestSkips.append(reason)


class CdEDBTest(unittest.TestCase):
    """Provide some basic useful test functionalities."""
    testfile_dir = pathlib.Path("/tmp/cdedb-store/testfiles")
    _clean_sample_data: ClassVar[Dict[str, CdEDBObjectMap]]
    conf: ClassVar[Config]

    @classmethod
    def setUpClass(cls) -> None:
        # Keep a clean copy of sample data that should not be messed with.
        cls._clean_sample_data = read_sample_data()
        cls.conf = Config()

    def setUp(self) -> None:
        subprocess.check_call(("make", "sample-data-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        # Provide a fresh copy of clean sample data.
        self.sample_data = copy.deepcopy(self._clean_sample_data)

    def get_sample_data(self, table: str, ids: Iterable[int],
                        keys: Iterable[str]) -> CdEDBObjectMap:
        """This mocks a select request against the sample data.

        "SELECT <keys> FROM <table> WHERE id = ANY(<ids>)"

        For some fields of some tables we perform a type conversion. These
        should be added as necessary to ease comparison against backend results.

        :returns: The result of the above "query" mapping id to entry.
        """
        def parse_datetime(s: str) -> datetime.datetime:
            # Magic placeholder that is replaced with the current time.
            if s == "---now---":
                return nearly_now()
            return datetime.datetime.fromisoformat(s)

        # Turn Iterator into Collection and ensure consistent order.
        keys = tuple(keys)
        ret = {}
        for anid in ids:
            if keys:
                r = {}
                for k in keys:
                    r[k] = copy.deepcopy(self.sample_data[table][anid][k])
                    if table == 'core.personas':
                        if k == 'balance':
                            r[k] = decimal.Decimal(r[k])
                        if k == 'birthday':
                            r[k] = datetime.date.fromisoformat(r[k])
                    elif table == 'core.changelog':
                        if k == 'ctime':
                            r[k] = parse_datetime(r[k])
                ret[anid] = r
            else:
                ret[anid] = copy.deepcopy(self.sample_data[table][anid])
        return ret


UserIdentifier = Union[CdEDBObject, str]


class BackendTest(CdEDBTest):
    """
    Base class for a TestCase that uses some backends. Needs to be subclassed.
    """
    maxDiff = None
    session: ClassVar[SessionBackend]
    core: ClassVar[CoreBackend]
    cde: ClassVar[CdEBackend]
    event: ClassVar[EventBackend]
    pastevent: ClassVar[PastEventBackend]
    ml: ClassVar[MlBackend]
    assembly: ClassVar[AssemblyBackend]
    key: Optional[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.session = cls.initialize_raw_backend(SessionBackend)
        cls.core = cls.initialize_backend(CoreBackend)
        cls.cde = cls.initialize_backend(CdEBackend)
        cls.event = cls.initialize_backend(EventBackend)
        cls.pastevent = cls.initialize_backend(PastEventBackend)
        cls.ml = cls.initialize_backend(MlBackend)
        cls.assembly = cls.initialize_backend(AssemblyBackend)
        # Workaround to make orga info available for calls into the MLBackend.
        cls.ml.orga_info = lambda rs, persona_id: cls.event.orga_info(  # type: ignore
            rs.sessionkey, persona_id)

    def setUp(self) -> None:
        """Reset login state."""
        super().setUp()
        self.key = None

    def login(self, user: UserIdentifier, *, ip: str = "127.0.0.0") -> Optional[str]:
        if isinstance(user, str):
            user = USER_DICT[user]
        assert isinstance(user, dict)
        self.key = self.core.login(
            None, user['username'], user['password'], ip)  # type: ignore
        return self.key

    @staticmethod
    def initialize_raw_backend(backendcls: Type[SessionBackend]
                               ) -> SessionBackend:
        return backendcls()

    @classmethod
    def initialize_backend(cls, backendcls: Type[B]) -> B:
        return make_backend_shim(backendcls(), internal=True)


# A reference of the most important attributes for all users. This is used for
# logging in and the `as_user` decorator.
# Make sure not to alter this during testing.
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
    "viktor": {
        'id': 48,
        'DB-ID': "DB-48-5",
        'username': "viktor@example.cde",
        'password': "secret",
        'display_name': "Viktor",
        'given_names': "Viktor",
        'family_name': "Versammlungsadmin",
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


F = TypeVar("F", bound=Callable[..., Any])


def as_users(*users: str) -> Callable[[F], F]:
    """Decorate a test to run it as the specified user(s)."""
    def wrapper(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(self: Union[BackendTest, FrontendTest], *args: Any, **kwargs: Any
                    ) -> None:
            for i, user in enumerate(users):
                with self.subTest(user=user):
                    if i > 0:
                        self.setUp()
                    if user is "anonymous":
                        if not isinstance(self, FrontendTest):
                            raise RuntimeError(
                                "Anonymous testing not supported for backend tests."
                                " Use `key=None` instead.")
                        kwargs['user'] = None
                        self.get('/')
                    else:
                        kwargs['user'] = USER_DICT[user]
                        self.login(USER_DICT[user])
                    fun(self, *args, **kwargs)
        return cast(F, new_fun)
    return wrapper


def admin_views(*views: str) -> Callable[[F], F]:
    """Decorate a test to set different initial admin views."""
    def decorator(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(self: FrontendTest, *args: Any, **kwargs: Any) -> Any:
            self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(views))
            return fun(self, *args, **kwargs)
        return cast(F, new_fun)
    return decorator


def prepsql(sql: AnyStr) -> Callable[[F], F]:
    """Decorate a test to run some arbitrary SQL-code beforehand."""
    def decorator(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(*args: Any, **kwargs: Any) -> Any:
            execsql(sql)
            return fun(*args, **kwargs)
        return cast(F, new_fun)
    return decorator


def execsql(sql: AnyStr) -> None:
    """Execute arbitrary SQL-code on the test database."""
    path = pathlib.Path("/tmp/test-cdedb-sql-commands.sql")
    psql = ("/cdedb2/bin/execute_sql_script.py",
            "--dbuser", "cdb", "--dbname", "cdb_test")
    null = subprocess.DEVNULL
    mode = "w"
    if isinstance(sql, bytes):
        mode = "wb"
    with open(path, mode) as f:
        f.write(sql)
    subprocess.check_call(psql + (str(path),), stdout=null)


class FrontendTest(BackendTest):
    """
    Base class for frontend tests.

    The `setUpClass` provides a new application. The language of the
    application can be overridden via the `lang` class attribute.

    All webpages encountered during testing can be saved to a temporary
    directory by specifying `SCRAP_ENCOUNTERED_PAGES` as environment variable.
    """
    lang = "de"
    app: ClassVar[webtest.TestApp]
    gettext: ClassVar[Callable[[str], str]]
    do_scrap: ClassVar[bool]
    scrap_path: ClassVar[str]
    response: webtest.TestResponse
    app_extra_environ = {
        'REMOTE_ADDR': "127.0.0.0",
        'SERVER_PROTOCOL': "HTTP/1.1",
        'wsgi.url_scheme': 'https'}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        app = Application()
        cls.gettext = app.translations[cls.lang].gettext
        cls.app = webtest.TestApp(app, extra_environ=cls.app_extra_environ)

        # set `do_scrap` to True to capture a snapshot of all visited pages
        cls.do_scrap = "SCRAP_ENCOUNTERED_PAGES" in os.environ
        if cls.do_scrap:
            # create a temporary directory and print it
            cls.scrap_path = tempfile.mkdtemp()
            print(cls.scrap_path, file=sys.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        if cls.do_scrap:
            # make scrap_path directory and content publicly readable
            folder = pathlib.Path(cls.scrap_path)
            folder.chmod(0o0755)  # 0755/drwxr-xr-x
            for file in folder.iterdir():
                file.chmod(0o0644)  # 0644/-rw-r--r--

    def setUp(self) -> None:
        """Reset web application."""
        super().setUp()
        self.app.reset()
        # Make sure all available admin views are enabled.
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(ALL_ADMIN_VIEWS))
        self.response = None

    def basic_validate(self, verbose: bool = False) -> None:
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('CdEDB – Fehler', texts[0])
            self.scrap()
        self.log_generation_time()

    def scrap(self) -> None:
        if self.do_scrap and self.response.status_int // 100 == 2:
            # path without host but with query string - capped at 64 chars
            url = urllib.parse.quote_plus(self.response.request.path_qs)[:64]
            with tempfile.NamedTemporaryFile(dir=self.scrap_path, suffix=url,
                                             delete=False) as f:
                # create a temporary file in scrap_path with url as a suffix
                # persisting after process completion and dump the response.
                f.write(self.response.body)

    def log_generation_time(self, response: webtest.TestResponse = None) -> None:
        if response is None:
            response = self.response
        if _BASICCONF["TIMING_LOG"]:
            with open(_BASICCONF["TIMING_LOG"], 'a') as f:
                output = "{} {} {} {}\n".format(
                    response.request.path, response.request.method,
                    response.headers.get('X-Generation-Time'),
                    response.request.query_string)
                f.write(output)

    def get(self, url: str, *args: Any, verbose: bool = False, **kwargs: Any) -> None:
        """Navigate directly to a given URL using GET."""
        self.response: webtest.TestResponse = self.app.get(
            url, *args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def follow(self, **kwargs: Any) -> None:
        """Follow a redirect if one occurrs."""
        oldresponse = self.response
        self.response = self.response.maybe_follow(**kwargs)
        if self.response != oldresponse:
            self.log_generation_time(oldresponse)

    def post(self, url: str, *args: Any, verbose: bool = False, **kwargs: Any) -> None:
        """Directly send a POST-request.

        Note that most of our POST-handlers require a CSRF-token."""
        self.response = self.app.post(url, *args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def submit(self, form: webtest.Form, button: str = "submitform",
               check_notification: bool = True, verbose: bool = False,
               value: bool = None) -> None:
        """Submit a form.

        If the form has multiple submit buttons, they can be differentiated
        using the `button` and `value` parameters.

        :param check_notification: If True and this is a POST-request, check
            that the submission produces a notification indicating success.
        :param verbose: If True, offer additional debug output.
        :param button: The name of the button to use.
        :param value: The value of the button to use.
        """
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

    def traverse(self, *links: Union[MutableMapping[str, Any], str],
                 verbose: bool = False) -> None:
        """Follow a sequence of links, described by their kwargs.

        A link can also be just a string, in which case that string is assumed
        to be the `description` of the link.

        A link should usually contain some of the following descriptors:

            * `description`:
                * The (visible) content inside the link. Uses RegEx matching.
            * `href`:
                * The target of the link. Uses RegEx matching.
            * `linkid`:
                * The `id` attribute of the link. Uses RegEx matching.
            * 'index':
                * Example: `index=2` uses the third matching link.

        :param verbose: If True, display additional debug information.
        """
        for link in links:
            if isinstance(link, str):
                link = {'description': link}
            if 'index' not in link:
                link['index'] = 0
            try:
                self.response = self.response.click(**link, verbose=verbose)
            except IndexError as e:
                e.args += ('Error during traversal of {}'.format(link),)
                raise
            self.follow()
            self.basic_validate(verbose=verbose)

    def login(self, user: UserIdentifier, *, ip: str = "", verbose: bool = False
              ) -> Optional[str]:
        """Log in as the given user.

        :param verbose: If True display additional debug information.
        """
        if isinstance(user, str):
            user = USER_DICT[user]
        self.get("/", verbose=verbose)
        f = self.response.forms['loginform']
        f['username'] = user['username']
        f['password'] = user['password']
        self.submit(f, check_notification=False, verbose=verbose)
        self.key = self.app.cookies.get('sessionkey', None)
        return self.key

    def logout(self, verbose: bool = False) -> None:
        """Log out. Raises a KeyError if not currently logged in.

        :param verbose: If True display additional debug information.
        """
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False, verbose=verbose)
        self.key = None

    def admin_view_profile(self, user: str, check: bool = True,
                           verbose: bool = False) -> None:
        """Shortcut to use the admin quicksearch to navigate to a user profile.

        This fails if the logged in user is not a `core_admin` or has the
        `core_user` admin view disabled.

        :param check: If True check that the Profile was reached.
        :param verbose: If True display additional debug information.
        """
        u = USER_DICT[user]
        self.traverse({'href': '^/$'}, verbose=verbose)
        f = self.response.forms['adminshowuserform']
        f['phrase'] = u["DB-ID"]
        self.submit(f)
        if check:
            self.assertTitle("{} {}".format(u['given_names'],
                                            u['family_name']))

    def realm_admin_view_profile(self, user: str, realm: str,
                                 check: bool = True, verbose: bool = False
                                 ) -> None:
        """Shortcut to a user profile using realm-based usersearch.

        This fails if the logged in user is not an admin of the given realm
        or has that admin view disabled.

        :param check: If True check that the Profile was reached.
        :param verbose: If True display additional debug information.
        """
        u = USER_DICT[user]
        self.traverse({'href': '/{}/$'.format(realm)},
                      {'href': '/{}/search/user'.format(realm)},
                      verbose=verbose)
        id_field = 'personas.id'
        f = self.response.forms['queryform']
        f['qsel_' + id_field].checked = True
        f['qop_' + id_field] = QueryOperators.equal.value
        f['qval_' + id_field] = u["id"]
        self.submit(f, verbose=verbose)
        self.traverse({'description': 'Profil'}, verbose=verbose)
        if check:
            self.assertTitle("{} {}".format(u['given_names'],
                                            u['family_name']))

    def fetch_mail(self) -> List[email.message.EmailMessage]:
        """
        Get the content of mails that were sent, using the E-Mail-notification.
        """
        elements = self.response.lxml.xpath(
            "//div[@class='alert alert-info']/span/text()")

        def _extract_path(s: str) -> str:
            regex = r"E-Mail als (.*) auf der Festplatte gespeichert."
            result = re.match(regex, s)
            if not result:
                raise RuntimeError(
                    f"Failed to extract debug email path from {s!r}.")
            return result.group(1)
        mails = [_extract_path(x)
                 for x in elements if x.startswith("E-Mail als ")]
        ret = []
        for path in mails:
            with open(path) as f:
                raw = f.read()
                parser = email.parser.Parser(policy=email.policy.default)
                msg = cast(email.message.EmailMessage, parser.parsestr(raw))
                ret.append(msg)
        return ret

    @staticmethod
    def fetch_link(msg: email.message.EmailMessage, num: int = 1) -> Optional[str]:
        ret = None
        body = msg.get_body()
        assert isinstance(body, email.message.EmailMessage)
        for line in body.get_content().splitlines():
            if line.startswith('[{}] '.format(num)):
                ret = line.split(maxsplit=1)[-1]
        return ret

    def assertTitle(self, title: str) -> None:
        """
        Assert that the tilte of the current page equals the given string.

        The actual title has a prefix, which is checked automatically.
        """
        components = tuple(x.strip() for x in self.response.lxml.xpath(
            '/html/head/title/text()'))
        self.assertEqual("CdEDB –", components[0][:7])
        normalized = re.sub(r'\s+', ' ', components[0][7:].strip())
        self.assertEqual(title.strip(), normalized)

    def get_content(self, div: str = "content") -> str:
        """Retrieve the content of the (first) element with the given id."""
        if self.response.content_type == "text/plain":
            return self.response.text
        tmp = self.response.lxml.xpath("//*[@id='{}']".format(div))
        if not tmp:
            raise AssertionError("Div not found.", div)
        content = tmp[0]
        return content.text_content()

    def assertCheckbox(self, status: bool, anid: str) -> None:
        """Assert that the checkbox with the given id is checked (or not)."""
        tmp = self.response.html.find_all(id=anid)
        if not tmp:
            raise AssertionError("Id not found.", id)
        if len(tmp) != 1:
            raise AssertionError("More or less then one hit.", anid)
        checkbox = tmp[0]
        if "data-checked" not in checkbox.attrs:
            raise ValueError("Id doesnt belong to a checkbox", anid)
        self.assertEqual(str(status), checkbox['data-checked'])

    def assertPresence(self, s: str, *, div: str = "content", regex: bool = False,
                       exact: bool = False) -> None:
        """Assert that a string is present in the element with the given id.

        The checked content is whitespace-normalized before comparison.

        :param regex: If True, do a RegEx match of the given string.
        :param exact: If True, require an exact match.
        """
        target = self.get_content(div)
        normalized = re.sub(r'\s+', ' ', target)
        if regex:
            self.assertTrue(re.search(s.strip(), normalized))
        elif exact:
            self.assertEqual(s.strip(), normalized.strip())
        else:
            self.assertIn(s.strip(), normalized)

    def assertNonPresence(self, s: str, *, div: str = "content",
                          check_div: bool = True) -> None:
        """Assert that a string is not present in the element with the given id.

        :param check_div: If True, this assertion fails if the div is not found.
        """
        if self.response.content_type == "text/plain":
            self.assertNotIn(s.strip(), self.response.text)
        else:
            try:
                content = self.response.lxml.xpath(f"//*[@id='{div}']")[0]
            except IndexError as e:
                if check_div:
                    raise AssertionError(
                        f"Specified div {div!r} not found.") from None
                else:
                    pass
            else:
                self.assertNotIn(s.strip(), content.text_content())

    def assertLogin(self, name: str) -> None:
        """Assert that a user is logged in by checking their display name."""
        span = self.response.lxml.xpath("//span[@id='displayname']")[0]
        self.assertEqual(name.strip(), span.text_content().strip())

    def assertValidationError(
            self, fieldname: str, message: str = "", index: int = None,
            notification: Optional[str] = "Validierung fehlgeschlagen") -> None:
        """
        Check for a specific form input field to be highlighted as .has-error
        and a specific error message to be shown near the field. Also check that an
        .alert-danger notification (with the given text) is indicating validation
        failure.

        :param fieldname: The field's 'name' attribute
        :param index: If more than one field with the given name exists,
            specify which one should be checked.
        :param message: The expected error message displayed below the input
        :param notification: The expected notification displayed at the top of the page
            This can be a regex. If this is None, skip the notification check.
        :raise AssertionError: If field is not found, field is not within
            .has-error container or error message is not found
        """
        if notification is not None:
            self.assertIn("alert alert-danger", self.response.text)
            self.assertPresence(notification, div="notifications",
                                regex=True)

        nodes = self.response.lxml.xpath(
            '(//input|//select|//textarea)[@name="{}"]'.format(fieldname))
        f = fieldname
        if index is None:
            if len(nodes) == 1:
                node = nodes[0]
            elif len(nodes) == 0:
                raise AssertionError(f"No input with name {f!r} found.")
            else:
                raise AssertionError(f"More than one input with name {f!r}"
                                     f" found. Need to specify index.")
        else:
            try:
                node = nodes[index]
            except IndexError:
                raise AssertionError(f"Input with name {f!r} and index {index}"
                                     f" not found. {len(nodes)} inputs with"
                                     f" name {f!r} found.") from None

        # From https://devhints.io/xpath#class-check
        container = node.xpath(
            "ancestor::*[contains(concat(' ',normalize-space(@class),' '),"
            "' has-error ')]")
        if not container:
            raise AssertionError(
                f"Input with name {f!r} is not contained in an .has-error box")
        msg = f"Expected error message not found near input with name {f!r}."
        self.assertIn(message, container[0].text_content(), msg)

    def assertNoLink(self, href_pattern: str = None, tag: str = 'a',
                     href_attr: str = 'href', content: str = None,
                     verbose: bool = False) -> None:
        """Assert that no tag that matches specific criteria is found. Possible
        criteria include:

        * The tags href_attr matches the href_pattern (regex)
        * The tags content matches the content (regex)

        This is a ripoff of webtest.response._find_element, which is used by
        traverse internally.
        """
        href_pat = webtest.utils.make_pattern(href_pattern)
        content_pat = webtest.utils.make_pattern(content)

        def printlog(s: str) -> None:
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

    def log_pagination(self, title: str, logs: List[Tuple[int, enum.IntEnum]]) -> None:
        """Helper function to test the logic of the log pagination.

        This should be called from every frontend log, to ensure our pagination
        works. Logs must contain at least 9 log entries.

        :param title: of the Log page, like "Userdata-Log"
        :param logs: list of log entries mapped to their LogCode
        """
        # check the landing page
        f = self.response.forms['logshowform']
        total = len(logs)
        self._log_subroutine(title, logs, start=1,
                             end=total if total < 50 else 50)
        # check if the log page numbers are proper (no 0th page, no last+1 page)
        self.assertNonPresence("", div="pagination-0", check_div=False)
        self.assertNonPresence("", check_div=False,
                               div=f"pagination-{str(total // 50 + 2)}")
        # check translations
        self.assertNonPresence("LogCodes")

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

    def _log_subroutine(self, title: str, all_logs: List[Tuple[int, enum.IntEnum]],
                        start: int, end: int) -> None:
        total = len(all_logs)
        self.assertTitle(f"{title} [{start}–{end} von {total}]")

        if end > total:
            end = total

        # adapt slicing to our count of log entries
        logs = all_logs[start-1:end]
        for index, log_entry in enumerate(logs, start=1):
            log_id, log_code = log_entry
            log_code_str = self.gettext(str(log_code))  # type: ignore
            self.assertPresence(log_code_str, div=f"{index}-{log_id}")

    def check_sidebar(self, ins: Collection[str], out: Collection[str]) -> None:
        """Helper function to check the (in)visibility of sidebar elements.

        Raise an error if an element is in the sidebar and not in ins.

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

    def _click_admin_view_button(self, label: str, current_state: bool = None) -> None:
        """
        Helper function for checking the disableable admin views

        This function searches one of the buttons in the adminviewstoggleform
        (by its label), optionally checks this button's state, and submits
        the form using this button's value to enable/disable the corresponding
        admin view(s).

        :param label: A regex used to find the correct admin view button.
            May also be a regex pattern.
        :param current_state: If not None, the admin view button's active state
            is checked to be equal to this boolean.
        :return: The button element to perform further checks.
            Is actually of type `bs4.BeautifulSoup`.
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

    def reload_and_check_form(self, form: webtest.Form, link: Union[CdEDBObject, str],
                              max_tries: int = 42, waittime: float = 0.1,
                              fail: bool = True) -> None:
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


class MultiAppFrontendTest(FrontendTest):
    """Subclass for testing multiple frontend instances simultaniously."""
    n: int = 2  # The number of instances that should be created.
    current_app: int  # Which instance is currently active 0 <= x < n
    apps: List[webtest.TestApp]
    responses: List[webtest.TestResponse]

    @classmethod
    def setUpClass(cls) -> None:
        """Create n new apps, overwrite cls.app with a reference."""
        super().setUpClass()
        cls.apps = [webtest.TestApp(Application(),
                                    extra_environ=cls.app_extra_environ)
                    for _ in range(cls.n)]
        # The super().setUpClass overwrites the property, so reset it here.
        cls.app = property(fget=cls.get_app, fset=cls.set_app)
        cls.responses = [None for _ in range(cls.n)]
        cls.current_app = 0

    def setUp(self) -> None:
        """Reset all apps and responses and the current app index."""
        self.responses = [None for _ in range(self.n)]
        super().setUp()
        for app in self.apps:
            app.reset()
            app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(ALL_ADMIN_VIEWS))
        self.current_app = 0

    def get_response(self) -> webtest.TestResponse:
        return self.responses[self.current_app]

    def set_response(self, value: webtest.TestResponse) -> None:
        self.responses[self.current_app] = value

    response = property(fget=get_response, fset=set_response)

    def get_app(self) -> webtest.TestApp:
        return self.apps[self.current_app]

    def set_app(self, value: webtest.TestApp) -> None:
        self.apps[self.current_app] = value

    app = property(fget=get_app, fset=set_app)

    def switch_app(self, i: int) -> None:
        """Switch to a different index.

        Sets the app and response with the specified index as active.
        All methods of the super class only interact with the active app and
        response.
        """
        if not 0 <= i < self.n:
            raise ValueError(f"Invalid index. Must be between 0 and {self.n}.")
        self.current_app = i


StoreTrace = NamedTuple("StoreTrace", [('cron', str), ('data', CdEDBObject)])
MailTrace = NamedTuple("MailTrace", [('realm', str), ('template', str),
                                     ('args', Sequence[Any]),
                                     ('kwargs', Dict[str, Any])])


def make_cron_backend_proxy(cron: CronFrontend, backend: B) -> B:
    class CronBackendProxy:
        def __getattr__(self, name: str) -> Callable[..., Any]:
            attr = getattr(backend, name)

            @functools.wraps(attr)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                rs = cron.make_request_state()
                return attr(rs, *args, **kwargs)
            return wrapper

    return cast(B, CronBackendProxy())


class CronTest(unittest.TestCase):
    _all_periodics: Set[str]
    _run_periodics: Set[str]
    cron: ClassVar[CronFrontend]
    core: ClassVar[CoreBackend]
    cde: ClassVar[CdEBackend]
    event: ClassVar[EventBackend]
    pastevent: ClassVar[PastEventBackend]
    assembly: ClassVar[AssemblyBackend]
    ml: ClassVar[MlBackend]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.stores: List[StoreTrace] = []
        self.mails: List[MailTrace] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls.cron = CronFrontend()
        cls.core = make_cron_backend_proxy(cls.cron, cls.cron.core.coreproxy)
        cls.cde = make_cron_backend_proxy(cls.cron, cls.cron.core.cdeproxy)
        cls.event = make_cron_backend_proxy(cls.cron, cls.cron.core.eventproxy)
        cls.assembly = make_cron_backend_proxy(
            cls.cron, cls.cron.core.assemblyproxy)
        cls.ml = make_cron_backend_proxy(cls.cron, cls.cron.core.mlproxy)
        cls._all_periodics = {
            job.cron['name']
            for frontend in (cls.cron.core, cls.cron.cde, cls.cron.event,
                             cls.cron.assembly, cls.cron.ml)
            for job in cls.cron.find_periodics(frontend)
        }
        cls._run_periodics = set()

    @classmethod
    def tearDownClass(cls) -> None:
        if (any(job not in cls._run_periodics for job in cls._all_periodics)
                and not os.environ.get('CDEDB_TEST_SINGULAR')):
            raise AssertionError(f"The following cron-periodics never ran:"
                                 f" {cls._all_periodics - cls._run_periodics}")

    def setUp(self) -> None:
        subprocess.check_call(("make", "sql-test-shallow"),
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        self.stores = []
        self.mails = []

        def store_decorator(fun: F) -> F:
            @functools.wraps(fun)
            def store_wrapper(rs: RequestState, name: str,
                              data: CdEDBObject) -> CdEDBObject:
                self.stores.append(StoreTrace(name, data))
                return fun(rs, name, data)
            return cast(F, store_wrapper)

        setattr(self.cron.core, "set_cron_store", store_decorator(
            self.cron.core.set_cron_store))

        def mail_decorator(front: AbstractFrontend) -> Callable[[F], F]:
            def the_decorator(fun: F) -> F:
                @functools.wraps(fun)
                def mail_wrapper(rs: RequestState, name: str,
                                 *args: Any, **kwargs: Any) -> Optional[str]:
                    self.mails.append(
                        MailTrace(front.realm, name, args, kwargs))
                    return fun(rs, name, *args, **kwargs)
                return cast(F, mail_wrapper)
            return the_decorator

        for frontend in (self.cron.core, self.cron.cde, self.cron.event,
                         self.cron.assembly, self.cron.ml):
            setattr(frontend, "do_mail", mail_decorator(
                frontend)(frontend.do_mail))

    def execute(self, *args: Any, check_stores: bool = True) -> None:
        if not args:
            raise ValueError("Must specify jobs to run.")
        self._run_periodics.update(args)
        self.cron.execute(args)
        if check_stores:
            expectation = set(args) | {"_base"}
            self.assertEqual(expectation, set(s.cron for s in self.stores))
