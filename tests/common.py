#!/usr/bin/env python3
"""General testing utilities for CdEDB2 testsuite"""

import collections.abc
import copy
import datetime
import decimal
import email.message
import email.parser
import email.policy
import enum
import functools
import getpass
import gettext
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from typing import (
    Any, AnyStr, Callable, ClassVar, Dict, Iterable, List, Mapping, MutableMapping,
    NamedTuple, Optional, Pattern, Sequence, Set, Tuple, Type, TypeVar, Union, cast,
    no_type_check,
)

import PIL.Image
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
    ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS, CdEDBLog, CdEDBObject, CdEDBObjectMap,
    PathLike, PrivilegeError, RequestState, merge_dicts, nearly_now, now,
    roles_to_db_role,
)
from cdedb.config import SecretsConfig, TestConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.application import Application
from cdedb.frontend.common import AbstractFrontend, Worker, setup_translations
from cdedb.frontend.cron import CronFrontend
from cdedb.query import QueryOperators
from cdedb.script import Script

# TODO: use TypedDict to specify UserObject.
UserObject = Mapping[str, Any]
UserIdentifier = Union[UserObject, str, int]
LinkIdentifier = Union[MutableMapping[str, Any], str]

# This is to be used in place of `self.key` for anonymous requests. It makes mypy happy.
ANONYMOUS = cast(RequestState, None)


def create_mock_image(file_type: str = "png") -> bytes:
    """This returns a bytes object representing a picture of the given type.

    The picture will pass validation by the `profilepic` validator.
    """
    afile = io.BytesIO()
    image = PIL.Image.new('RGBA', (1000, 1000), color=(255, 0, 0))
    image.save(afile, file_type)
    afile.seek(0)
    return afile.read()


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


def _read_sample_data(filename: PathLike = "/cdedb2/tests/ancillary_files/"
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


_SAMPLE_DATA = _read_sample_data()

B = TypeVar("B", bound=AbstractBackend)


def _make_backend_shim(backend: B, internal: bool = False) -> B:
    """Wrap a backend to only expose functions with an access decorator.

    If we used an actual RPC mechanism, this would do some additional
    lifting to accomodate this.

    We need to use a function so we can cast the return value.
    We also need to use an inner class so we can provide __getattr__.

    This is similar to the normal make_proxy but encorporates a different
    wrapper.
    """
    # pylint: disable=protected-access

    sessionproxy = SessionBackend(backend.conf._configpath)
    secrets = SecretsConfig(backend.conf._configpath)
    connpool = connection_pool_factory(
        backend.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
        secrets, backend.conf["DB_PORT"])
    translations = setup_translations(backend.conf)

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
            sessionkey=sessionkey,
            apitoken=apitoken,
            user=user,
            request=None,  # type: ignore[arg-type]
            notifications=[],
            mapadapter=None,  # type: ignore[arg-type]
            requestargs=None,
            errors=[],
            values=None,
            begin=now(),
            lang="de",
            translations=translations,
        )
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
            # Special case for the `subman.SubscriptionManager`.
            if name == "subman":
                return attr
            if any([
                not getattr(attr, "access", False),
                getattr(attr, "internal", False) and not internal,
                not callable(attr)
            ]):
                raise PrivilegeError(f"Attribute {name} not public")

            @functools.wraps(attr)
            def wrapper(key: Optional[str], *args: Any, **kwargs: Any) -> Any:
                rs = setup_requeststate(key)
                try:
                    return attr(rs, *args, **kwargs)
                except FileNotFoundError as e:
                    raise RuntimeError("Did you forget to add a `@storage` decorator to"
                                       " the test?") from e

            return wrapper

        def __setattr__(self, key: str, value: Any) -> None:
            return setattr(backend, key, value)

    return cast(B, Proxy())


class BasicTest(unittest.TestCase):
    """Provide some basic useful test functionalities."""
    needs_storage_marker = "_needs_storage"

    storage_dir: ClassVar[pathlib.Path]
    testfile_dir: ClassVar[pathlib.Path]
    configpath: ClassVar[str]
    conf: ClassVar[TestConfig]

    @classmethod
    def setUpClass(cls) -> None:
        cls.configpath = os.environ['CDEDB_TEST_CONFIGPATH']
        cls.conf = TestConfig(cls.configpath)
        cls.storage_dir = cls.conf['STORAGE_DIR']
        cls.testfile_dir = cls.storage_dir / "testfiles"

    def setUp(self) -> None:
        test_method = getattr(self, self._testMethodName)
        if getattr(test_method, self.needs_storage_marker, False):
            # get the user running the current process, so the access rights for the
            # storage directory are set correctly
            user = getpass.getuser()
            subprocess.run(
                ("make", "storage", f"STORAGE_DIR={self.storage_dir}",
                 f"DATA_USER={user}"),
                stdout=subprocess.DEVNULL, check=True, start_new_session=True)

    def tearDown(self) -> None:
        test_method = getattr(self, self._testMethodName)
        if getattr(test_method, self.needs_storage_marker, False):
            shutil.rmtree(self.storage_dir)

    @staticmethod
    def get_sample_data(table: str, ids: Iterable[int] = None,
                        keys: Iterable[str] = None) -> CdEDBObjectMap:
        """This mocks a select request against the sample data.

        "SELECT <keys> FROM <table> WHERE id = ANY(<ids>)"

        if `keys` is None:
        "SELECT * FROM <table> WHERE id = ANY(<ids>)"

        if `ids` is None:
        "SELECT <keys> FROM <table>"

        For some fields of some tables we perform a type conversion. These
        should be added as necessary to ease comparison against backend results.

        :returns: The result of the above "query" mapping id to entry.
        """
        def parse_datetime(s: Optional[str]) -> Optional[datetime.datetime]:
            # Magic placeholder that is replaced with the current time.
            if s is None:
                return None
            if s == "---now---":
                return nearly_now()
            return datetime.datetime.fromisoformat(s)

        if keys is None:
            try:
                keys = next(iter(_SAMPLE_DATA[table].values())).keys()
            except StopIteration:
                return {}
        if ids is None:
            ids = _SAMPLE_DATA[table].keys()
        # Turn Iterator into Collection and ensure consistent order.
        keys = tuple(keys)
        ret = {}
        for anid in ids:
            r = {}
            for k in keys:
                r[k] = copy.deepcopy(_SAMPLE_DATA[table][anid][k])
                if table == 'core.personas':
                    if k == 'balance' and r[k]:
                        r[k] = decimal.Decimal(r[k])
                    if k == 'birthday' and r[k]:
                        r[k] = datetime.date.fromisoformat(r[k])
                if k in {'ctime', 'atime', 'vote_begin', 'vote_end',
                         'vote_extension_end', 'signup_end'} and r[k]:
                    r[k] = parse_datetime(r[k])
            ret[anid] = r
        return ret

    def get_sample_datum(self, table: str, id_: int) -> CdEDBObject:
        return self.get_sample_data(table, [id_])[id_]


class CdEDBTest(BasicTest):
    """Reset the DB for every test."""
    longMessage = False
    _clean_data: ClassVar[str]
    _sample_data: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sample_data_dir = pathlib.Path("tests/ancillary_files")
        cls._clean_data = (sample_data_dir / "clean_data.sql").read_text()
        cls._sample_data = (sample_data_dir / "sample_data.sql").read_text()

    def setUp(self) -> None:
        with Script(
            persona_id=-1,
            dbuser="cdb",
            dbname=self.conf["CDB_DATABASE_NAME"],
            check_system_user=False,
        ).rs().conn as conn:
            conn.set_session(autocommit=True)
            with conn.cursor() as curr:
                curr.execute(self._clean_data)
                curr.execute(self._sample_data)

        super().setUp()


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
    translations: ClassVar[Mapping[str, gettext.NullTranslations]]
    user: UserObject
    key: RequestState

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
        cls.translations = setup_translations(cls.conf)

    def setUp(self) -> None:
        """Reset login state."""
        super().setUp()
        self.user = USER_DICT["anonymous"]
        self.key = ANONYMOUS

    def login(self, user: UserIdentifier, *, ip: str = "127.0.0.0") -> Optional[str]:
        user = get_user(user)
        if user["id"] is None:
            raise RuntimeError("Anonymous users not supported for backend tests."
                               " Pass `ANONYMOUS` in place of `self.key` instead.")
        self.key = cast(RequestState, self.core.login(
            ANONYMOUS, user['username'], user['password'], ip))
        if self.key:
            self.user = user
        else:
            self.user = USER_DICT["anonymous"]
        return self.key  # type: ignore

    def logout(self) -> None:
        self.core.logout(self.key)
        self.key = ANONYMOUS
        self.user = USER_DICT["anonymous"]

    def user_in(self, *identifiers: UserIdentifier) -> bool:
        """Check whether the current user is any of the given users."""
        users = {get_user(i)["id"] for i in identifiers}
        return self.user.get("id", -1) in users

    def assertLogEqual(self, log_expectation: Sequence[CdEDBObject], *,
                       realm: str = None,
                       log_retriever: Callable[..., CdEDBLog] = None,
                       **kwargs: Any) -> None:
        """Helper to compare a log expectation to the actual thing."""
        if realm and not log_retriever:
            log_retriever = getattr(self, realm).retrieve_log
        if log_retriever:
            _, log = log_retriever(self.key, **kwargs)
        else:
            raise ValueError("No method of log retrieval provided.")

        for real, exp in zip(log, log_expectation):
            if 'id' not in exp:
                del real['id']
            if 'ctime' not in exp:
                exp['ctime'] = nearly_now()
            if 'submitted_by' not in exp:
                exp['submitted_by'] = self.user['id']
            for k in ('event_id', 'assembly_id', 'mailinglist_id'):
                if k in kwargs and k not in exp:
                    exp[k] = kwargs[k]
            for k in ('persona_id', 'change_note'):
                if k not in exp:
                    exp[k] = None
            for k in ('total', 'delta', 'new_balance'):
                if exp.get(k):
                    exp[k] = decimal.Decimal(exp[k])
        self.assertEqual(log, tuple(log_expectation))

    @classmethod
    def initialize_raw_backend(cls, backendcls: Type[SessionBackend]
                               ) -> SessionBackend:
        return backendcls(configpath=cls.configpath)

    @classmethod
    def initialize_backend(cls, backendcls: Type[B]) -> B:
        return _make_backend_shim(backendcls(configpath=cls.configpath), internal=True)


# A reference of the most important attributes for all users. This is used for
# logging in and the `as_user` decorator.
# Make sure not to alter this during testing.
USER_DICT: Dict[str, UserObject] = {
    "anton": {
        'id': 1,
        'DB-ID': "DB-1-9",
        'username': "anton@example.cde",
        'password': "secret",
        'display_name': "Anton",
        'given_names': "Anton Armin A.",
        'family_name': "Administrator",
        'default_name_format': "Anton Administrator",
    },
    "berta": {
        'id': 2,
        'DB-ID': "DB-2-7",
        'username': "berta@example.cde",
        'password': "secret",
        'display_name': "Bertå",
        'given_names': "Bertålotta",
        'family_name': "Beispiel",
        'default_name_format': "Bertå Beispiel",
    },
    "charly": {
        'id': 3,
        'DB-ID': "DB-3-5",
        'username': "charly@example.cde",
        'password': "secret",
        'display_name': "Charly",
        'given_names': "Charly C.",
        'family_name': "Clown",
        'default_name_format': "Charly Clown",
    },
    "daniel": {
        'id': 4,
        'DB-ID': "DB-4-3",
        'username': "daniel@example.cde",
        'password': "secret",
        'display_name': "Daniel",
        'given_names': "Daniel D.",
        'family_name': "Dino",
        'default_name_format': "Daniel Dino",
    },
    "emilia": {
        'id': 5,
        'DB-ID': "DB-5-1",
        'username': "emilia@example.cde",
        'password': "secret",
        'display_name': "Emmy",
        'given_names': "Emilia E.",
        'family_name': "Eventis",
        'default_name_format': "Emilia E. Eventis",
    },
    "ferdinand": {
        'id': 6,
        'DB-ID': "DB-6-X",
        'username': "ferdinand@example.cde",
        'password': "secret",
        'display_name': "Ferdinand",
        'given_names': "Ferdinand F.",
        'family_name': "Findus",
        'default_name_format': "Ferdinand Findus",
    },
    "garcia": {
        'id': 7,
        'DB-ID': "DB-7-8",
        'username': "garcia@example.cde",
        'password': "secret",
        'display_name': "Garcia",
        'given_names': "Garcia G.",
        'family_name': "Generalis",
        'default_name_format': "Garcia Generalis",
    },
    "hades": {
        'id': 8,
        'DB-ID': "DB-8-6",
        'username': None,
        'password': "secret",
        'display_name': None,
        'given_names': "Hades",
        'family_name': "Hell",
        'default_name_format': "Hades Hell",
    },
    "inga": {
        'id': 9,
        'DB-ID': "DB-9-4",
        'username': "inga@example.cde",
        'password': "secret",
        'display_name': "Inga",
        'given_names': "Inga",
        'family_name': "Iota",
        'default_name_format': "Inga Iota",
    },
    "janis": {
        'id': 10,
        'DB-ID': "DB-10-8",
        'username': "janis@example.cde",
        'password': "secret",
        'display_name': "Janis",
        'given_names': "Janis",
        'family_name': "Jalapeño",
        'default_name_format': "Janis Jalapeño",
    },
    "kalif": {
        'id': 11,
        'DB-ID': "DB-11-6",
        'username': "kalif@example.cde",
        'password': "secret",
        'display_name': "Kalif",
        'given_names': "Kalif ibn al-Ḥasan",
        'family_name': "Karabatschi",
        'default_name_format': "Kalif Karabatschi",
    },
    "lisa": {
        'id': 12,
        'DB-ID': "DB-12-4",
        'username': None,
        'password': "secret",
        'display_name': "Lisa",
        'given_names': "Lisa",
        'family_name': "Lost",
        'default_name_format': "Lisa Lost",
    },
    "martin": {
        'id': 13,
        'DB-ID': "DB-13-2",
        'username': "martin@example.cde",
        'password': "secret",
        'display_name': "Martin",
        'given_names': "Martin",
        'family_name': "Meister",
        'default_name_format': "Martin Meister",
    },
    "nina": {
        'id': 14,
        'DB-ID': "DB-14-0",
        'username': 'nina@example.cde',
        'password': "secret",
        'display_name': "Nina",
        'given_names': "Nina",
        'family_name': "Neubauer",
        'default_name_format': "Nina Neubauer",
    },
    "olaf": {
        'id': 15,
        'DB-ID': "DB-15-9",
        'username': "olaf@example.cde",
        'password': "secret",
        'display_name': "Olaf",
        'given_names': "Olaf",
        'family_name': "Olafson",
        'default_name_format': "Olaf Olafson",
    },
    "paul": {
        'id': 16,
        'DB-ID': "DB-16-7",
        'username': "paulchen@example.cde",
        'password': "secret",
        'display_name': "Paul",
        'given_names': "Paulchen",
        'family_name': "Panther",
        'default_name_format': "Paul Panther",
    },
    "quintus": {
        'id': 17,
        'DB-ID': "DB-17-5",
        'username': "quintus@example.cde",
        'password': "secret",
        'display_name': "Quintus",
        'given_names': "Quintus",
        'family_name': "da Quirm",
        'default_name_format': "Quintus da Quirm",
    },
    "rowena": {
        'id': 18,
        'DB-ID': "DB-18-3",
        'username': "rowena@example.cde",
        'password': "secret",
        'display_name': "Rowena",
        'given_names': "Rowena",
        'family_name': "Ravenclaw",
        'default_name_format': "Rowena Ravenclaw",
    },
    "vera": {
        'id': 22,
        'DB-ID': "DB-22-1",
        'username': "vera@example.cde",
        'password': "secret",
        'display_name': "Vera",
        'given_names': "Vera",
        'family_name': "Verwaltung",
        'default_name_format': "Vera Verwaltung",
    },
    "werner": {
        'id': 23,
        'DB-ID': "DB-23-X",
        'username': "werner@example.cde",
        'password': "secret",
        'display_name': "Werner",
        'given_names': "Werner",
        'family_name': "Wahlleitung",
        'default_name_format': "Werner Wahlleitung",
    },
    "annika": {
        'id': 27,
        'DB-ID': "DB-27-2",
        'username': "annika@example.cde",
        'password': "secret",
        'display_name': "Annika",
        'given_names': "Annika",
        'family_name': "Akademieteam",
        'default_name_format': "Annika Akademieteam",
    },
    "farin": {
        'id': 32,
        'DB-ID': "DB-32-9",
        'username': "farin@example.cde",
        'password': "secret",
        'display_name': "Farin",
        'given_names': "Farin",
        'family_name': "Finanzvorstand",
        'default_name_format': "Farin Finanzvorstand",
    },
    "katarina": {
        'id': 37,
        'DB-ID': "DB-37-X",
        'username': "katarina@example.cde",
        'password': "secret",
        'diplay_name': "Katarina",
        'given_names': "Katarina",
        'family_name': "Kassenprüfer",
        'default_name_format': "Katarina Kassenprüfer",
    },
    "viktor": {
        'id': 48,
        'DB-ID': "DB-48-5",
        'username': "viktor@example.cde",
        'password': "secret",
        'display_name': "Viktor",
        'given_names': "Viktor",
        'family_name': "Versammlungsadmin",
        'default_name_format': "Viktor Versammlungsadmin",
    },
    "akira": {
        'id': 100,
        'DB-ID': "DB-100-7",
        'username': "akira@example.cde",
        'password': "secret",
        'display_name': "Akira",
        'given_names': "Akira",
        'family_name': "Abukara",
        'default_name_format': "Akira Abukara",
    },
    "anonymous": {
        'id': None,
        'DB-ID': None,
        'username': None,
        'password': None,
        'display_name': None,
        'given_names': None,
        'family_name': None,
    },
}
_PERSONA_ID_TO_USER = {user["id"]: user for user in USER_DICT.values()}


def get_user(user: UserIdentifier) -> UserObject:
    if isinstance(user, str):
        user = USER_DICT[user]
    elif isinstance(user, int):
        user = _PERSONA_ID_TO_USER[user]
    return user


F = TypeVar("F", bound=Callable[..., Any])


def as_users(*users: UserIdentifier) -> Callable[[Callable[..., None]],
                                                 Callable[..., None]]:
    """Decorate a test to run it as the specified user(s)."""
    def wrapper(fun: Callable[..., None]) -> Callable[..., None]:
        @functools.wraps(fun)
        def new_fun(self: Union[BackendTest, FrontendTest], *args: Any, **kwargs: Any
                    ) -> None:
            for i, user in enumerate(users):
                with self.subTest(user=user):
                    if i > 0:
                        self.setUp()
                    self.login(user)
                    fun(self, *args, **kwargs)
        return new_fun
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


def storage(fun: F) -> F:
    """Decorate a test which needs some of the test files on the local drive."""
    setattr(fun, BasicTest.needs_storage_marker, True)
    return fun


def execsql(sql: AnyStr) -> None:
    """Execute arbitrary SQL-code on the test database."""
    conf = TestConfig(os.environ['CDEDB_TEST_CONFIGPATH'])
    psql = ("/cdedb2/bin/execute_sql_script.py",
            "--username", "cdb", "--dbname", conf["CDB_DATABASE_NAME"])
    mode = 'wb' if isinstance(sql, bytes) else 'w'
    with tempfile.NamedTemporaryFile(mode=mode, suffix='.sql') as sql_file:
        sql_file.write(sql)
        sql_file.flush()
        subprocess.run(psql + ("--file", sql_file.name), stdout=subprocess.DEVNULL,
                       start_new_session=True, check=True)


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
        'HTTP_HOST': "localhost",
        'SERVER_PROTOCOL': "HTTP/1.1",
        'wsgi.url_scheme': 'https'}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        app = Application(cls.configpath)
        cls.gettext = app.translations[cls.lang].gettext
        cls.app = webtest.TestApp(app, extra_environ=cls.app_extra_environ)

        # set `do_scrap` to True to capture a snapshot of all visited pages
        cls.do_scrap = 'CDEDB_TEST_DUMP_DIR' in os.environ
        if cls.do_scrap:
            # create a parent directory for all dumps
            dump_root = pathlib.Path(os.environ['CDEDB_TEST_DUMP_DIR'])
            dump_root.mkdir(exist_ok=True)
            # create a temporary directory and print it
            cls.scrap_path = tempfile.mkdtemp(dir=dump_root, prefix=f'{cls.__name__}.')
            print(f'\n\n{cls.scrap_path}\n', file=sys.stderr)

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
            self._scrap()
        self._log_generation_time()

    def _scrap(self) -> None:
        if self.do_scrap and self.response.status_int // 100 == 2:
            # path without host but with query string - capped at 64 chars
            # To enhance readability, we mark most chars as safe. All special chars are
            # allowed in linux file paths, but sadly windows is more restrictive...
            url = urllib.parse.quote(
                self.response.request.path_qs, safe='/;@&=+$,~')[:64]
            # since / chars are forbidden in file paths, we replace them by _
            url = url.replace('/', '_')
            # create a temporary file in scrap_path with url as a prefix
            # persisting after process completion and dump the response.
            with tempfile.NamedTemporaryFile(dir=self.scrap_path, prefix=f'{url}.',
                                             delete=False) as f:
                f.write(self.response.body)

    def _log_generation_time(self, response: webtest.TestResponse = None) -> None:
        if response is None:
            response = self.response
        # record performance information during test runs
        with open(self.conf["LOG_DIR"] / "cdedb-timing.log", 'a') as f:
            output = "{} {} {} {}\n".format(
                response.request.path, response.request.method,
                response.headers.get('X-Generation-Time'),
                response.request.query_string)
            f.write(output)

    def get(self, url: str, *args: Any, verbose: bool = False, **kwargs: Any) -> None:
        """Navigate directly to a given URL using GET."""
        self.response: webtest.TestResponse = self.app.get(url, *args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def follow(self, **kwargs: Any) -> None:
        """Follow a redirect if one occurrs."""
        oldresponse = self.response
        self.response = self.response.maybe_follow(**kwargs)
        if self.response != oldresponse:
            self._log_generation_time(oldresponse)

    def assertRedirect(self, url: str, *args: Any, target_url: str,
                       verbose: bool = False, **kwargs: Any) -> webtest.TestResponse:
        """Checck that a GET-request to the url returns a redirect to the target url."""
        response: webtest.TestResponse = self.app.get(url, *args, **kwargs)
        self.assertLessEqual(300, response.status_int)
        self.assertGreater(400, response.status_int)
        self.assertIn("You should be redirected", response)
        self.assertIn(target_url, response)
        return response

    def post(self, url: str, *args: Any, verbose: bool = False, **kwargs: Any) -> None:
        """Directly send a POST-request.

        Note that most of our POST-handlers require a CSRF-token."""
        self.response = self.app.post(url, *args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def submit(self, form: webtest.Form, button: str = "", *,
               check_notification: bool = True, check_button_attrs: bool = False,
               verbose: bool = False, value: str = None) -> None:
        """Submit a form.

        If the form has multiple submit buttons, they can be differentiated
        using the `button` and `value` parameters.

        :param check_notification: If True and this is a POST-request, check
            that the submission produces a notification indicating success.
        :param check_button_attrs: If True and button is given, check whether the
            button specifies a different form action and/or method.
        :param verbose: If True, offer additional debug output.
        :param button: The name of the button to use.
        :param value: The value of the button to use.
        """
        # This is a workaround for the fact, that webtest does not care about the
        # `formaction` and `formmethod` atributes on submit buttons.
        if check_button_attrs and button:
            tmp_button: webtest.forms.Submit = form[button]
            if "formaction" in tmp_button.attrs:
                form.action = tmp_button.attrs["formaction"]
            if "formmethod" in tmp_button.attrs:
                form.method = tmp_button.attrs["formmethod"]
        method = form.method
        if value and not button:
            raise ValueError(
                "Cannot specify button value without specifying button name.")
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

    def traverse(self, *links: LinkIdentifier, verbose: bool = False) -> None:
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

    def login(self, user: UserIdentifier, *,  # pylint: disable=arguments-differ
              ip: str = "", verbose: bool = False) -> Optional[str]:
        """Log in as the given user.

        :param verbose: If True display additional debug information.
        """
        user = get_user(user)
        self.user = user
        self.get("/", verbose=verbose)
        if not self.user_in("anonymous"):
            f = self.response.forms['loginform']
            f['username'] = user['username']
            f['password'] = user['password']
            self.submit(f, check_notification=False, verbose=verbose)
        self.key = self.app.cookies.get('sessionkey', None)
        if not self.key:
            self.user = USER_DICT["anonymous"]
        return self.key  # type: ignore

    def logout(self, verbose: bool = False) -> None:  # pylint: disable=arguments-differ
        """Log out. Raises a KeyError if not currently logged in.

        :param verbose: If True display additional debug information.
        """
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False, verbose=verbose)
        self.key = ANONYMOUS
        self.user = USER_DICT["anonymous"]

    def admin_view_profile(self, user: UserIdentifier, check: bool = True,
                           verbose: bool = False) -> None:
        """Shortcut to use the admin quicksearch to navigate to a user profile.

        This fails if the logged in user is not a `core_admin` or has the
        `core_user` admin view disabled.

        :param check: If True check that the Profile was reached.
        :param verbose: If True display additional debug information.
        """
        u = get_user(user)
        self.traverse({'href': '^/$'}, verbose=verbose)
        f = self.response.forms['adminshowuserform']
        f['phrase'] = u["DB-ID"]
        self.submit(f)
        if check:
            self.assertTitle(u['default_name_format'])

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
            self.assertTitle(u['default_name_format'])

    def _fetch_mail(self) -> List[email.message.EmailMessage]:
        """
        Get the content of mails that were sent, using the E-Mail-notification.
        """
        elements = self.response.lxml.xpath(
            "//div[@class='alert alert-info']/span/text()")

        def _extract_path(s: str) -> Optional[str]:
            regex = r"E-Mail als (.*) auf der Festplatte gespeichert."
            result = re.match(regex, s.strip())
            if not result:
                return None
            return result.group(1)

        mails = list(filter(None, (map(_extract_path, elements))))
        ret = []
        for path in mails:
            with open(path) as f:
                raw = f.read()
                parser = email.parser.Parser(policy=email.policy.default)
                msg = cast(email.message.EmailMessage, parser.parsestr(raw))
                ret.append(msg)
        return ret

    def fetch_mail_content(self, index: int = 0) -> str:
        mail = self._fetch_mail()[index]
        body = mail.get_body()
        assert isinstance(body, email.message.EmailMessage)
        return body.get_content()

    def fetch_link(self, index: int = 0, num: int = 1) -> str:
        """Extract the <num>th link out of the <index>th mail just sent."""
        for line in self.fetch_mail_content(index).splitlines():
            if line.startswith(f'[{num}] '):
                return line.split(maxsplit=1)[-1]
        raise ValueError(f"Link [{num}] not found in mail [{index}].")

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

    def assertDivNotExists(self, div: str) -> None:
        """Assert that the given id is not used by any element on the page.

        This element is not required to be a div.
        """
        if not self.response.content_type == "text/html":
            self.fail("No valid html document.")
        if self.response.lxml.xpath("//*[@id='{}']".format(div)):
            self.fail("Element with id {} found".format(div))

    def assertCheckbox(self, status: bool, anid: str) -> None:
        """Assert that the checkbox with the given id is checked (or not)."""
        tmp = (self.response.html.find_all(id=anid)
               or self.response.html.find_all(attrs={'name': anid}))
        if not tmp:
            raise AssertionError("Id not found.", anid)
        if len(tmp) != 1:
            raise AssertionError("More or less then one hit.", anid)
        checkbox = tmp[0]
        if "data-checked" in checkbox.attrs:
            self.assertEqual(str(status), checkbox['data-checked'])
        elif "type" in checkbox.attrs:
            self.assertEqual("checkbox", checkbox['type'])
            self.assertEqual(status, checkbox.get('checked') == 'checked')
        else:
            raise ValueError("Id doesnt belong to a checkbox", anid)

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

    def assertNonPresence(self, s: Optional[str], *, div: str = "content",
                          check_div: bool = True) -> None:
        """Assert that a string is not present in the element with the given id.

        :param check_div: If True, this assertion fails if the div is not found.
        """
        if s is None:
            # Allow short-circuiting via dict.get()
            return
        if self.response.content_type == "text/plain":
            self.assertNotIn(s.strip(), self.response.text)
        else:
            try:
                content = self.response.lxml.xpath(f"//*[@id='{div}']")[0]
            except IndexError:
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
        self._assertValidationComplaint(
            kind="error", fieldname=fieldname, message=message, index=index,
            notification=notification)

    def assertValidationWarning(
            self, fieldname: str, message: str = "", index: int = None,
            notification: Optional[str] = "Eingaben scheinen fehlerhaft") -> None:
        """
        Check for a specific form input field to be highlighted as .has-warning
        and a specific warning message to be shown near the field. Also check that an
        .alert-warning notification (with the given text) is indicating validation
        warning.

        :param fieldname: The field's 'name' attribute
        :param index: If more than one field with the given name exists,
            specify which one should be checked.
        :param message: The expected warning message displayed below the input
        :param notification: The expected notification displayed at the top of the page
            This can be a regex. If this is None, skip the notification check.
        :raise AssertionError: If field is not found, field is not within
            .has-warning container or error message is not found
        """
        self._assertValidationComplaint(
            kind="warning", fieldname=fieldname, message=message, index=index,
            notification=notification)

    def _assertValidationComplaint(
            self, kind: str, fieldname: str, message: str, index: Optional[int],
            notification: Optional[str]) -> None:
        """Common helper for assertValidationError and assertValidationWarning."""
        if kind == "error":
            alert_type = "danger"
        elif kind == "warning":
            alert_type = "warning"
        else:
            raise NotImplementedError

        if notification is not None:
            self.assertIn(f"alert alert-{alert_type}", self.response.text,
                          f"No Notification of type {kind!r} found.")
            self.assertPresence(notification, div="notifications", regex=True)

        nodes = self.response.lxml.xpath(
            f'(//input|//select|//textarea)[@name="{fieldname}"]')
        f = fieldname
        if index is None:
            if len(nodes) == 1:
                node = nodes[0]
            elif not nodes:
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
            f"' has-{kind} ')]")
        if not container:
            raise AssertionError(
                f"Input with name {f!r} is not contained in an .has-{kind} box")
        msg = f"Expected error message not found near input with name {f!r}."
        self.assertIn(message, container[0].text_content(), msg)

    def assertNoLink(self, href_pattern: Union[str, Pattern[str]] = None,
                     tag: str = 'a', href_attr: str = 'href', content: str = None,
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

    def log_pagination(self, title: str, logs: Tuple[Tuple[int, enum.IntEnum], ...]
                       ) -> None:
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
        self.assertNonPresence("", check_div=False, div="pagination-0")
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

        # check multi-checkbox selections
        f = self.response.forms['logshowform']
        # use internal value property as I don't see a way to get the
        # checkbox value otherwise
        codes = [field._value for field in f.fields['codes']]  # pylint: disable=protected-access
        f['codes'] = codes
        self.assertGreater(len(codes), 1)
        self.submit(f)
        self.traverse({'linkid': 'pagination-first'})
        f = self.response.forms['logshowform']
        for field in f.fields['codes']:
            self.assertTrue(field.checked)

    def _log_subroutine(self, title: str,
                        all_logs: Tuple[Tuple[int, enum.IntEnum], ...],
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

    def check_sidebar(self, ins: Set[str], out: Set[str]) -> None:
        """Helper function to check the (in)visibility of sidebar elements.

        Raise an error if an element is in the sidebar and not in ins or
        if an element is in the sidebar and in out.

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

    def check_create_archive_user(self, realm: str, data: CdEDBObject = None) -> None:
        """Basic check for the user creation and archival functionality of each realm.

        :param data: realm-dependent data to use for the persona to be created
        """
        if data is None:
            data = {}

        def _check_deleted_data() -> None:
            assert data is not None
            self.assertNonPresence(data['username'])
            self.assertNonPresence(data.get('location'))
            self.assertNonPresence(data.get('address'))
            self.assertNonPresence(data.get('postal_code'))
            self.assertNonPresence(data.get('telephone'))
            self.assertNonPresence(data.get('country'))

        self.traverse({'href': '/' + realm + '/$'},
                      {'href': '/search/user'},
                      {'href': '/user/create'})
        merge_dicts(data, {
            "username": 'zelda@example.cde',
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "display_name": 'Zelda',
            "notes": "some fancy talk",
        })
        f = self.response.forms['newuserform']
        if f.get('country', default=None):
            self.assertEqual(f['country'].value, self.conf["DEFAULT_COUNTRY"])
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        for key, value in data.items():
            if key not in {'birthday', 'telephone', 'mobile', 'country', 'country2',
                           'gender'}:
                # Omit values with heavy formatting in the frontend here
                self.assertPresence(value)
        # Now test archival
        # 1. Archive user
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        _check_deleted_data()
        # 2. Find user via archived search
        self.traverse({'href': '/' + realm + '/$'})
        self.traverse({'description': 'Archivsuche'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qop_given_names'] = QueryOperators.match.value
        f['qval_given_names'] = 'Zelda'
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]", div='query-results')
        self.assertPresence("Zeruda", div='query-result')
        self.traverse({'description': 'Profil', 'href': '/core/persona/1001/show'})
        # 3: Dearchive user
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        self.traverse({'description': "Account wiederherstellen"})
        f = self.response.forms['dearchivepersonaform']
        self.submit(f, check_notification=False)
        self.assertValidationError('new_username', "Darf nicht leer sein.")
        f = self.response.forms['dearchivepersonaform']
        f['new_username'] = "zeruda@example.cde"
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence('zeruda@example.cde')
        _check_deleted_data()

    def _click_admin_view_button(self, label: Union[str, Pattern[str]],
                                 current_state: bool = None) -> None:
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
        if isinstance(label, str):
            label = re.compile(label)
        f = self.response.forms['adminviewstoggleform']
        button = self.response.html.find(id="adminviewstoggleform").find(text=label)
        if not button:
            raise KeyError(f"Admin view toggle with label {label!r} not found.")
        button = button.parent
        if current_state is not None:
            if current_state:
                self.assertIn("active", button['class'])
            else:
                self.assertNotIn("active", button['class'])
        self.submit(f, button='view_specifier', check_button_attrs=False,
                    value=button['value'])
        return button

    def join_worker_thread(self, worker_name: str, link: LinkIdentifier, *,
                           realm: str = "cde", timeout: float = 2) -> None:
        """Wait for the specified Worker thread to finish.

        :param realm: specify to which realm the Worker belongs. Currently only the
            CdEFrontend uses Workers.
        :param timeout: pecificy a maximum wait time for the thread to end. In our
            testing environment Worker threads should not take longer than a couple
            seconds.
        """
        ref = Worker.active_workers[worker_name]
        worker = ref()
        if worker:
            worker.join(timeout)
            if worker.is_alive():
                self.fail(f"Worker {realm}/{worker_name} still active after {timeout}"
                          f" seconds.")
        self.traverse(link)


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
        cls.apps = [
            webtest.TestApp(
                Application(cls.configpath),
                extra_environ=cls.app_extra_environ,
            )
            for _ in range(cls.n)
        ]
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
            def wrapper(rs: RequestState, *args: Any, **kwargs: Any) -> Any:
                rs = cron.make_request_state()
                return attr(rs, *args, **kwargs)
            return wrapper

    return cast(B, CronBackendProxy())


class CronTest(CdEDBTest):
    _remaining_periodics: Set[str]
    _remaining_tests: Set[str]
    stores: List[StoreTrace]
    mails: List[MailTrace]
    cron: ClassVar[CronFrontend]
    core: ClassVar[CoreBackend]
    cde: ClassVar[CdEBackend]
    event: ClassVar[EventBackend]
    pastevent: ClassVar[PastEventBackend]
    assembly: ClassVar[AssemblyBackend]
    ml: ClassVar[MlBackend]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.cron = CronFrontend(configpath=cls.configpath)
        cls.core = make_cron_backend_proxy(cls.cron, cls.cron.core.coreproxy)
        cls.cde = make_cron_backend_proxy(cls.cron, cls.cron.core.cdeproxy)
        cls.event = make_cron_backend_proxy(cls.cron, cls.cron.core.eventproxy)
        cls.assembly = make_cron_backend_proxy(cls.cron, cls.cron.core.assemblyproxy)
        cls.ml = make_cron_backend_proxy(cls.cron, cls.cron.core.mlproxy)
        cls._remaining_periodics = {
            job.cron['name']
            for frontend in (cls.cron.core, cls.cron.cde, cls.cron.event,
                             cls.cron.assembly, cls.cron.ml)
            for job in cls.cron.find_periodics(frontend)
        }
        cls._remaining_tests = {x for x in dir(cls) if x.startswith("test_")}

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        if not cls._remaining_tests and cls._remaining_periodics:
            raise AssertionError(f"The following cron-periodics never ran:"
                                 f" {cls._remaining_periodics}")

    def setUp(self) -> None:
        super().setUp()

        self._remaining_tests.remove(self._testMethodName)
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
                    self.mails.append(MailTrace(front.realm, name, args, kwargs))
                    return fun(rs, name, *args, **kwargs)
                return cast(F, mail_wrapper)
            return the_decorator

        for frontend in (self.cron.core, self.cron.cde, self.cron.event,
                         self.cron.assembly, self.cron.ml):
            setattr(frontend, "do_mail", mail_decorator(frontend)(frontend.do_mail))

    def execute(self, *args: Any, check_stores: bool = True) -> None:
        if not args:
            raise ValueError("Must specify jobs to run.")
        self._remaining_periodics.difference_update(args)
        self.cron.execute(args)
        if check_stores:
            expectation = set(args) | {"_base"}
            self.assertEqual(expectation, set(s.cron for s in self.stores))
