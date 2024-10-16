#!/usr/bin/env python3
"""General testing utilities for CdEDB2 testsuite"""

import collections.abc
import contextlib
import copy
import datetime
import decimal
import email.message
import email.parser
import email.policy
import functools
import gettext
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator, Iterable, Mapping, MutableMapping, Sequence
from re import Pattern
from typing import (
    Any,
    Callable,
    ClassVar,
    NamedTuple,
    Optional,
    TypeVar,
    Union,
    cast,
    no_type_check,
)

import PIL.Image
import webtest
import webtest.utils
from psycopg2.extras import RealDictCursor

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.common import AbstractBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.session import SessionBackend
from cdedb.cli.dev.json2sql import insert_postal_code_locations, json2sql, json2sql_join
from cdedb.cli.storage import (
    create_storage,
    populate_sample_event_keepers,
    populate_storage,
)
from cdedb.cli.util import execute_sql_script
from cdedb.common import (
    ANTI_CSRF_TOKEN_NAME,
    ANTI_CSRF_TOKEN_PAYLOAD,
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    PathLike,
    RequestState,
    merge_dicts,
    nearly_now,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.query import QueryOperators
from cdedb.common.query.log_filter import (
    AssemblyLogFilter,
    CdELogFilter,
    ChangelogLogFilter,
    CoreLogFilter,
    EventLogFilter,
    FinanceLogFilter,
    GenericLogFilter,
    MlLogFilter,
    PastEventLogFilter,
)
from cdedb.common.roles import (
    ADMIN_VIEWS_COOKIE_NAME,
    ALL_ADMIN_VIEWS,
    roles_to_db_role,
)
from cdedb.config import SecretsConfig, TestConfig, get_configpath, set_configpath
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.application import Application
from cdedb.frontend.common import (
    AbstractFrontend,
    Worker,
    make_persona_name,
    setup_translations,
)
from cdedb.frontend.cron import CronFrontend
from cdedb.frontend.paths import CDEDB_PATHS
from cdedb.models.droid import APIToken, resolve_droid_name
from cdedb.script import Script
from cdedb.uncommon.intenum import CdEIntEnum

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
                                           "sample_data.json",
                      ) -> dict[str, CdEDBObjectMap]:
    """Helper to turn the sample data from the JSON file into usable format."""
    with open(filename, encoding="utf8") as f:
        sample_data: dict[str, list[CdEDBObject]] = json.load(f)
    ret: dict[str, CdEDBObjectMap] = {}
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

    sessionproxy = SessionBackend()
    secrets = SecretsConfig()
    connpool = connection_pool_factory(
        backend.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
        secrets, backend.conf["DB_HOST"], backend.conf["DB_PORT"])
    translations = setup_translations(backend.conf)

    def setup_requeststate(key: Optional[str], ip: str = "127.0.0.0",
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
        if key and APIToken.token_string_pattern.fullmatch(key):
            user = sessionproxy.lookuptoken(key, ip)
            apitoken = key
        else:
            user = sessionproxy.lookupsession(key, ip)
            sessionkey = key

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
            rs.user.orga = backend.orga_info(
                rs, rs.user.persona_id)
        if "ml" in rs.user.roles and hasattr(backend, "moderator_info"):
            rs.user.moderator = backend.moderator_info(
                rs, rs.user.persona_id)
        if "assembly" in rs.user.roles and hasattr(backend, "presider_info"):
            rs.user.presider = backend.presider_info(
                rs, rs.user.persona_id)
        return rs

    class Proxy:
        """
        Wrap calls to the backend in a access check and provide a RequestState.
        """

        def __getattr__(self, name: str) -> Callable[..., Any]:
            attr = getattr(backend, name)
            # Special case for the `subman.SubscriptionManager`
            if name == "subman":
                return attr  # TODO: coverage
            if name == "_event_keeper":
                return attr
            if any([
                not getattr(attr, "access", False),
                getattr(attr, "internal", False) and not internal,
                not callable(attr),
            ]):
                raise PrivilegeError(f"Attribute {name} not public")  # pragma: no cover

            @functools.wraps(attr)
            def wrapper(key: Optional[str], *args: Any, **kwargs: Any) -> Any:
                rs = setup_requeststate(key)
                try:
                    return attr(rs, *args, **kwargs)
                except FileNotFoundError as e:
                    raise RuntimeError(  # pragma: no cover
                        "Did you forget to add a `@storage` decorator to the test?",
                    ) from e

            return wrapper

        def __setattr__(self, key: str, value: Any) -> None:
            return setattr(backend, key, value)

        def get_rs(self, key: str) -> RequestState:
            return setup_requeststate(key)

    return cast(B, Proxy())


class BasicTest(unittest.TestCase):
    """Provide some basic useful test functionalities."""
    needs_storage_marker = "_needs_storage"
    needs_event_keeper_marker = "_needs_event_keeper"

    storage_dir: ClassVar[pathlib.Path]
    testfile_dir: ClassVar[pathlib.Path]
    configpath: ClassVar[pathlib.Path]
    _orig_configpath: ClassVar[pathlib.Path]
    conf: ClassVar[TestConfig]
    secrets: ClassVar[SecretsConfig]

    @classmethod
    def setUpClass(cls) -> None:
        configpath = get_configpath()
        cls.configpath = configpath
        # save the configpath in an extra variable to reset it after each test
        cls._orig_configpath = configpath
        cls.conf = TestConfig()
        cls.secrets = SecretsConfig()
        cls.storage_dir = cls.conf['STORAGE_DIR']
        cls.testfile_dir = cls.storage_dir / "testfiles"

    def setUp(self) -> None:
        test_method = getattr(self, self._testMethodName)
        if getattr(test_method, self.needs_storage_marker, False):
            create_storage(self.conf)
            populate_storage(self.conf)
        if getattr(test_method, self.needs_event_keeper_marker, False):
            populate_sample_event_keepers(self.conf)

    def tearDown(self) -> None:
        test_method = getattr(self, self._testMethodName)
        if getattr(test_method, self.needs_storage_marker, False):
            shutil.rmtree(self.storage_dir)
        # reset the configpath after each test. This prevents interference between tests
        # playing around with this.
        set_configpath(self._orig_configpath)

    @staticmethod
    def get_sample_data(table: str, ids: Optional[Iterable[int]] = None,
                        keys: Optional[Iterable[str]] = None) -> CdEDBObjectMap:
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
        def parse_datetime(s: str) -> datetime.datetime:
            # Magic placeholder that is replaced with the current time.
            if s == "---now---":
                return nearly_now()
            return datetime.datetime.fromisoformat(s)

        def parse_date(s: str) -> datetime.date:
            if s == "---now---":
                return nearly_now().date()
            return datetime.date.fromisoformat(s)

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
                    if k == 'donation' and r[k]:
                        r[k] = decimal.Decimal(r[k])
                    if k == 'birthday' and r[k]:
                        r[k] = parse_date(r[k])
                if k in {'transaction_date'} and r[k]:
                    r[k] = parse_date(r[k])
                if k in {'ctime', 'atime', 'vote_begin', 'vote_end',
                         'vote_extension_end', 'signup_end'} and r[k]:
                    r[k] = parse_datetime(r[k])
            ret[anid] = r
        return ret

    def get_sample_datum(self, table: str, id_: int) -> CdEDBObject:
        return self.get_sample_data(table, [id_])[id_]


class AsyncBasicTest(unittest.IsolatedAsyncioTestCase, BasicTest):
    pass


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

        # compile the sample data
        json_file = "/cdedb2/tests/ancillary_files/sample_data.json"
        with open(json_file, encoding="utf8") as f:
            data: dict[str, list[CdEDBObject]] = json.load(f)

        with cls.database_cursor() as cur:
            cls._sample_data = json2sql_join(cur, json2sql(data))

            cur.execute('SELECT COUNT(*) FROM core.postal_code_locations')
            if not unwrap(cur.fetchone()):
                cur.execute(*insert_postal_code_locations())

    @classmethod
    @contextlib.contextmanager
    def database_cursor(cls) -> Generator[RealDictCursor, None, None]:
        with Script(
            persona_id=-1,
            dbuser="cdb",
            check_system_user=False,
        ).rs().conn as conn:
            conn.set_session(autocommit=True)
            with conn.cursor() as cur:
                yield cur

    def setUp(self) -> None:
        with self.database_cursor() as cur:
            cur.execute(self._clean_data)
            cur.execute(self._sample_data)

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
        # Workaround to make orga and presider info available for calls into MLBackend.
        cls.ml.orga_info = lambda rs, persona_id: cls.event.orga_info(  # type: ignore[attr-defined] # pylint: disable=attribute-defined-outside-init
            rs.sessionkey, persona_id)
        cls.ml.presider_info = lambda rs, persona_id: cls.assembly.presider_info(  # type: ignore[attr-defined] # pylint: disable=attribute-defined-outside-init
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
            raise RuntimeError("Anonymous users not supported for backend tests."  # pragma: no cover  # noqa: E501
                               " Pass `ANONYMOUS` in place of `self.key` instead.")
        self.key = cast(RequestState, self.core.login(
            ANONYMOUS, user['username'], user['password'], ip))
        if self.key:
            self.user = user
        else:
            self.user = USER_DICT["anonymous"]
        return self.key  # type: ignore[return-value]

    def logout(self, *, allow_anonymous: bool = False) -> None:
        """Log out.

        :param allow_anonymous: If False, this will throw an error if the current user
            is anonymous..
        """
        if self.user_in("anonymous"):  # pragma: no cover
            if not allow_anonymous:
                raise self.failureException("Already logged out.")
        self.core.logout(self.key)
        self.key = ANONYMOUS
        self.user = USER_DICT["anonymous"]

    @contextlib.contextmanager
    def switch_user(self, new_user: UserIdentifier) -> Generator[None, None, None]:
        """This method can be used as a context manager to temporarily switch users."""
        old_user = self.user
        self.logout(allow_anonymous=True)
        self.login(new_user)
        yield
        self.logout(allow_anonymous=True)
        self.login(old_user)

    def user_in(self, *identifiers: UserIdentifier) -> bool:
        """Check whether the current user is any of the given users."""
        users = {get_user(i)["id"] for i in identifiers}
        return self.user.get("id", -1) in users

    def assertLogEqual(self, log_expectation: Sequence[CdEDBObject], realm: str,
                       **kwargs: Any) -> None:
        """Helper to compare a log expectation to the actual thing."""
        logs: dict[str, tuple[Callable[..., CdEDBLog], type[GenericLogFilter]]] = {
            'core': (self.core.retrieve_log, CoreLogFilter),
            'changelog': (self.core.retrieve_changelog_meta, ChangelogLogFilter),
            'cde': (self.cde.retrieve_cde_log, CdELogFilter),
            'finance': (self.cde.retrieve_finance_log, FinanceLogFilter),
            'assembly': (self.assembly.retrieve_log, AssemblyLogFilter),
            'event': (self.event.retrieve_log, EventLogFilter),
            'ml': (self.ml.retrieve_log, MlLogFilter),
            'past_event': (self.pastevent.retrieve_past_log, PastEventLogFilter),
        }
        log_retriever, log_filter_class = logs[realm]
        _, log = log_retriever(self.key, log_filter_class(**kwargs))

        for real, exp in zip(log, log_expectation):
            if 'id' not in exp:
                exp['id'] = real['id']
            if 'ctime' not in exp:
                exp['ctime'] = nearly_now()
            if 'submitted_by' not in exp:
                exp['submitted_by'] = self.user['id']
            for k in ('event_id', 'assembly_id', 'mailinglist_id'):
                if k in kwargs and 'entity_ids' not in exp:
                    exp[k] = kwargs[k]
            for k in ('persona_id', 'change_note'):
                if k not in exp:
                    exp[k] = None
            for k in ('droid_id', 'delta', 'new_balance', 'transaction_date'):
                if k not in exp and k in real:
                    exp[k] = None
            for k in ('total', 'delta', 'new_balance', 'member_total'):
                if exp.get(k):
                    exp[k] = decimal.Decimal(exp[k])
            if real['change_note']:
                real['change_note'] = real['change_note'].replace("\xa0", " ")
        self.assertEqual(log, tuple(log_expectation))

    @classmethod
    def initialize_raw_backend(cls, backendcls: type[SessionBackend],
                               ) -> SessionBackend:
        return backendcls()

    @classmethod
    def initialize_backend(cls, backendcls: type[B]) -> B:
        return _make_backend_shim(backendcls(), internal=True)


class BrowserTest(CdEDBTest):
    """
    Base class for a TestCase that uses a real browser.

    We instantiate a real (development) server for this usecase as a bare WSGI
    application won't do the trick.
    """
    serverProcess: subprocess.Popen[bytes] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.serverProcess = subprocess.Popen(
            ['python3', '-m', 'cdedb', 'dev', 'serve', '--test'],
            stderr=subprocess.DEVNULL)
        for _ in range(42):
            try:
                response = urllib.request.urlopen("http://localhost:5000/",
                                                  timeout=.1)
                if response.status == 200:
                    break
            except urllib.error.URLError:
                time.sleep(.1)
            except socket.timeout:
                time.sleep(.1)
        else:
            raise RuntimeError('Test server failed to start.')  # pragma: no cover

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.serverProcess:
            cls.serverProcess.terminate()
            cls.serverProcess.wait(2)
            cls.serverProcess.kill()
            cls.serverProcess.wait()
            cls.serverProcess = None
        super().tearDownClass()


# A reference of the most important attributes for all users. This is used for
# logging in and the `as_user` decorator.
# Make sure not to alter this during testing.
USER_DICT: dict[str, UserObject] = {
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
    "ludwig": {
        'id': 38,
        'DB-ID': "DB-38-8",
        'username': "ludwig@example.cde",
        'password': "secret",
        'diplay_name': "Ludwig",
        'given_names': "Ludwig",
        'family_name': "Lokus",
        'default_name_format': "Ludwig Lokus",
    },
    "petra": {
        'id': 42,
        'DB-ID': "DB-42-6",
        'username': "petra@example.cde",
        'password': "secret",
        'display_name': "Petra",
        'given_names': "Petra",
        'family_name': "Philanthrop",
        'default_name_format': "Petra Philanthrop",
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
        def new_fun(self: Union[BackendTest, FrontendTest], *args: Any, **kwargs: Any,
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


def prepsql(sql: str) -> Callable[[F], F]:
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


def event_keeper(fun: F) -> F:
    """Decorate a test which needs an event keeper setup."""
    setattr(fun, BasicTest.needs_event_keeper_marker, True)
    return storage(fun)


def execsql(sql: str) -> None:
    """Execute arbitrary SQL-code on the test database."""
    execute_sql_script(TestConfig(), SecretsConfig(), sql)


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
    gettext: "staticmethod[[str], str]"
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
        app = Application()
        cls.gettext = staticmethod(app.translations[cls.lang].gettext)
        cls.app = webtest.TestApp(app, extra_environ=cls.app_extra_environ)

        # set `do_scrap` to True to capture a snapshot of all visited pages
        # TODO move this in the TestConfig?
        cls.do_scrap = 'CDEDB_TEST_DUMP_DIR' in os.environ
        if cls.do_scrap:  # pragma: no cover
            # create a parent directory for all dumps
            dump_root = pathlib.Path(os.environ['CDEDB_TEST_DUMP_DIR'])
            dump_root.mkdir(exist_ok=True)
            # create a temporary directory and print it
            cls.scrap_path = tempfile.mkdtemp(dir=dump_root, prefix=f'{cls.__name__}.')
            print(f'\n\n{cls.scrap_path}\n', file=sys.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        if cls.do_scrap:  # pragma: no cover
            # make scrap_path directory and content publicly readable
            folder = pathlib.Path(cls.scrap_path)
            folder.chmod(0o0755)  # 0755/drwxr-xr-x
            for file in folder.iterdir():
                file.chmod(0o0644)  # 0644/-rw-r--r--

    def setUp(self, *, prepsql: Optional[str] = None) -> None:
        """Reset web application.

        :param prepsql: Similar to the @prepsql decorator this executes a raw
                        SQL command on the test database.
        """
        super().setUp()
        self.app.reset()
        # Make sure all available admin views are enabled.
        self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(ALL_ADMIN_VIEWS))
        if prepsql:
            execsql(prepsql)
        self.response = None

    def basic_validate(self, verbose: bool = False) -> None:
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('CdEDB – Fehler', texts[0])
            self._scrap()
        self._log_generation_time()

    def _scrap(self) -> None:
        if self.do_scrap and self.response.status_int // 100 == 2:  # pragma: no cover
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

    def _log_generation_time(self, response: Optional[webtest.TestResponse] = None,
                             ) -> None:
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

    def post(self, url: str, params: dict[str, Any], *args: Any, verbose: bool = False,
             evade_anti_csrf: bool = True, csrf_token_name: str = ANTI_CSRF_TOKEN_NAME,
             csrf_token_payload: str = ANTI_CSRF_TOKEN_PAYLOAD, **kwargs: Any) -> None:
        """Directly send a POST-request.

        Note that most of our POST-handlers require an Anti-CSRF token,
        which is forged here by default.

        :param params: This is a restriction of self.app.post, but enforces a general
            style and simplifies processing here.
        :param evade_anti_csrf: Do CSRF, forging the Anti-CSRF token.
        """
        if evade_anti_csrf:
            urlmap = CDEDB_PATHS
            urls = urlmap.bind(self.app_extra_environ["HTTP_HOST"])
            endpoint, _ = urls.match(url, method="POST")  # pylint: disable=unpacking-non-sequence
            params[csrf_token_name] = self.app.app.encode_anti_csrf_token(
                endpoint, csrf_token_name, csrf_token_payload,
                persona_id=self.user['id'])
        self.response = self.app.post(url, params, *args, **kwargs)
        self.follow()
        self.basic_validate(verbose=verbose)

    def submit(self, form: webtest.Form, button: str = "", *,
               check_notification: bool = True, check_button_attrs: bool = False,
               verbose: bool = False, value: Optional[str] = None) -> None:
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
                "Cannot specify button value without specifying button name.")  # pragma: no cover  # noqa: E501
        self.response = form.submit(button, value=value)
        self.follow()
        self.basic_validate(verbose=verbose)
        if method == "POST" and check_notification:
            # check that we acknowledged the POST with a notification
            self.assertNotification(ntype='success',
                                    msg=("No success notification found in"
                                         + self.response.text if verbose else None))

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
                e.args += (f'Error during traversal of {link}',)
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
        return self.key  # type: ignore[return-value]

    def logout(self, verbose: bool = False, *, allow_anonymous: bool = False) -> None:  # pylint: disable=arguments-differ
        """Log out.

        :param verbose: If True display additional debug information.
        :param allow_anonymous: If False, this will throw an error if the current user
            is anonymous..
        """
        if self.user_in("anonymous"):  # pragma: no cover
            if not allow_anonymous:
                raise self.failureException("Already logged out.")
        else:
            f = self.response.forms['logoutform']
            self.submit(f, check_notification=False, verbose=verbose)
        self.key = ANONYMOUS
        self.user = USER_DICT["anonymous"]

    @contextlib.contextmanager
    def switch_user(self, new_user: UserIdentifier) -> Generator[None, None, None]:
        """context manager to temporarily switch users - frontend variant

        This restores the original response after the original user logged in again"""
        saved_response = self.response
        with super().switch_user(new_user):
            yield
        self.response = saved_response

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
                                 check: bool = True, verbose: bool = False,
                                 ) -> None:
        """Shortcut to a user profile using realm-based usersearch.

        This fails if the logged in user is not an admin of the given realm
        or has that admin view disabled.

        :param check: If True check that the Profile was reached.
        :param verbose: If True display additional debug information.
        """
        u = USER_DICT[user]
        self.traverse({'href': f'/{realm}/$'},
                      {'href': f'/{realm}/search/user'},
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

    def _fetch_mail(self) -> list[email.message.EmailMessage]:
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
        raise ValueError(f"Link [{num}] not found in mail [{index}].")  # pragma: no cover  # noqa: E501

    def fetch_orga_token(self) -> tuple[int, str]:
        new_token = self.response.lxml.xpath("//pre[@id='neworgatoken']/text()")[0]
        droid_name, secret = APIToken.parse_token_string(new_token)
        _droid_class, token_id = resolve_droid_name(droid_name)
        return cast(int, token_id), secret

    def assertTitle(self, title: str, exact: bool = True) -> None:
        """
        Assert that the tilte of the current page equals the given string.

        The actual title has a prefix, which is checked automatically.
        :param exact: If False, presence as substring suffices.
        """
        components = tuple(x.strip() for x in self.response.lxml.xpath(
            '/html/head/title/text()'))
        self.assertEqual("CdEDB –", components[0][:7])
        normalized = re.sub(r'\s+', ' ', components[0][7:].strip())
        if exact:
            self.assertEqual(title.strip(), normalized)
        else:
            self.assertIn(title.strip(), normalized)

    def get_content(self, div: str = "content") -> str:
        """Retrieve the content of the (first) element with the given id."""
        if self.response.content_type == "text/plain":
            return self.response.text
        tmp = self.response.lxml.xpath(f"//*[@id='{div}']")
        if not tmp:
            self.fail(f"Div '{div}' not found.")
        content = tmp[0]
        return content.text_content()

    def assertDivNotExists(self, div: str) -> None:
        """Assert that the given id is not used by any element on the page.

        This element is not required to be a div.
        """
        if not self.response.content_type == "text/html":
            self.fail("No valid html document.")
        if self.response.lxml.xpath(f"//*[@id='{div}']"):
            self.fail(f"Element with id {div} found")

    def assertInputHasAttr(self, input_field: webtest.forms.Field, attr: str) -> None:
        """Assert that the form input has a specific HTML DOM attribute.

        This is no big logic, but should make this slightly internal feature of webtest
        more easy to use.
        """
        self.assertIn(attr, input_field.attrs)

    def assertHasClass(self, div: str, html_class: str) -> None:
        tmp = self.response.lxml.xpath(f"//*[@id='{div}']")
        if not tmp:
            self.fail(f"Div '{div}' not found.")
        classes = tmp[0].classes
        self.assertIn(html_class, classes, f"{html_class} not in {list(classes)}.")

    def assertCheckbox(self, status: bool, anid: str) -> None:
        """Assert that the checkbox with the given id is checked (or not)."""
        tmp = (self.response.html.find_all(id=anid)
               or self.response.html.find_all(attrs={'name': anid}))
        if not tmp:
            self.fail(f"ID '{anid}' not found.")
        if len(tmp) != 1:
            self.fail(f"More or less then one hit ({len(tmp)}) for div '{anid}'.")
        checkbox = tmp[0]
        if "data-checked" in checkbox.attrs:
            self.assertEqual(str(status), checkbox['data-checked'])
        elif "type" in checkbox.attrs:
            self.assertEqual("checkbox", checkbox['type'])
            self.assertEqual(status, checkbox.get('checked') == 'checked')
        else:
            self.fail(f"ID '{anid}' doesn't belong to a checkbox: {checkbox!r}")

    def assertPresence(self, s: str, *, div: str = "content", regex: bool = False,
                       exact: bool = False, msg: Optional[str] = None) -> None:
        """Assert that a string is present in the element with the given id.

        The checked content is whitespace-normalized before comparison.

        :param regex: If True, do a RegEx match of the given string.
        :param exact: If True, require an exact match.
        """
        target = self.get_content(div)
        normalized = re.sub(r'\s+', ' ', target)
        if regex:
            self.assertTrue(re.search(s.strip(), normalized), msg=msg)
        elif exact:
            self.assertEqual(s.strip(), normalized.strip(), msg=msg)
        else:
            self.assertIn(s.strip(), normalized, msg=msg)

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
            tmp = self.response.lxml.xpath(f"//*[@id='{div}']")
            if tmp:
                self.assertNotIn(s.strip(), tmp[0].text_content())
            elif check_div:
                self.fail(f"Specified div {div!r} not found.")

    def assertTextContainedInElement(self, search_text: str, element_tag: str,
                                     div: str = "content") -> None:
        """
        Assert that `search_text` is present and is contained in a specific HTML tag.

        The requested tag may be the direct container of the `search_text` or any
        parent. Each occurance of the `search_text` must be contained in a matching tag.

        Usage Example::

            # Check if the Name "Anton" is present but crossed out via an <s> tag
            self.assertTextContainedInElement("Anton", "s")

        :param element_tag: Expected HTML element tag name of one of the ancestors of
            the text occurance.
        :param div: HTML id of the outer container element to search for `search_text`
        """
        elements_with_searchtext = self.response.lxml.xpath(
            f'//*[@id="{div}"]//*[text()[contains(.,"{search_text}")]]')
        if len(elements_with_searchtext) == 0:
            self.fail(f"No HTML element found, containing the text '{search_text}'")
        num_searched_elements_with_matching_ancestor = sum(
            1
            for element in elements_with_searchtext
            if len(element.xpath(f'./ancestor-or-self::{element_tag}')) > 0
        )
        if num_searched_elements_with_matching_ancestor < len(elements_with_searchtext):
            if len(elements_with_searchtext) == 1:
                self.fail(
                    f"Text '{search_text}' found, but not contained in a"
                    f" <{element_tag}>")
            else:
                self.fail(
                    f"Text '{search_text}' found {len(elements_with_searchtext)} times,"
                    f" but only {num_searched_elements_with_matching_ancestor}"
                    f" of them are contained in a <{element_tag}>")

    def assertTextContainedInNthElement(self, search_text: str, element_tag: str,
                                        n: int, div: str = "content") -> None:
        """
        Assert that `search_text` is contained in an n-th sibling `tag` HTML element

        The element may be the direct container of the `search_text` or any parent.
        For each occurance of the `search_text`, the closest parent of tag name
        `element_tag` must be the n-th sibling in its parent (starting at 0). Negative n
        can be used to specify the n-th-last element.

        Usage Example::

            # Check if the Name "Anton" is in the last <li> list item of a list
            self.assertTextContainedInElement("Anton", "li", -1)

        :param element_tag: HTML element tag name of one of the ancestors of the text
            occurance, which is checked for its position among its siblings.
        :param n: Required position of the matching ancestor among its siblings.
            Positive numbers count from the beginning of the parent (starting at 0),
            negative numbers count from the end of the parent element (starting at -1).
        :param div: HTML id of the outer container element to search for `search_text`
        """
        elements_with_searchtext = self.response.lxml.xpath(
            f'//*[@id="{div}"]//*[text()[contains(.,"{search_text}")]]')
        if len(elements_with_searchtext) == 0:
            self.fail(f"No HTML element containing the text '{search_text}' found")
        for element_with_searchtext in elements_with_searchtext:
            matching_ancestors = element_with_searchtext.xpath(
                f'./ancestor-or-self::{element_tag}[1]')
            if len(matching_ancestors) == 0:
                self.fail(f"Text '{search_text}' found, but at least one occurance is "
                          f"not in a <{element_tag}>")
            closest_matching_ancestor = matching_ancestors[0]
            if n < 0:
                following_siblings = len(
                    closest_matching_ancestor.xpath('./following-sibling::*'))
                actual_n = -1 - following_siblings
                if actual_n != n:
                    self.fail(f"Text '{search_text}' found, but at least one occurance "
                              f"is in {actual_n}th sibling <{element_tag}> "
                              f"(expected {n})")
            else:
                preceding_siblings = len(
                    closest_matching_ancestor.xpath('./preceding-sibling::*'))
                actual_n = preceding_siblings
                if actual_n != n:
                    self.fail(f"Text '{search_text}' found, but at least one occurance "
                              f"is in {actual_n}th sibling <{element_tag}> "
                              f"(expected {n})")

    def getFullTextOfElementWithText(self, search_text: str, element_tag: str, div: str,
                                     ) -> str:
        """Returns the plain text content of the element containing `search_text`.

        Fails if the search_text is found in more than one HTML element.

        The requested tag may be the direct container of the `search_text` or any
        parent.

        :param element_tag: Expected HTML element tag name of one of the ancestors of
            the text occurance.
        :param div: HTML id of the outer container element to search for `search_text`
        """
        matching_elements = self.response.lxml.xpath(
                f'//*[@id="{div}"]//{element_tag}[contains(.,"{search_text}")]')
        if len(matching_elements) == 0:
            self.fail(f"Text '{search_text}' not found")
        elif len(matching_elements) > 1:
            self.fail(f"Text '{search_text}' found in {len(matching_elements)} "
                      "(more than one) elements")
        return ''.join(matching_elements[0].itertext())

    def assertNotification(self, ntext: Optional[str] = None,
                           ntype: Optional[str] = None, *, static: bool = False,
                           msg: Optional[str] = None) -> None:
        """Check for a notification containing `ntext` under all `ntype` notifications.

        :param ntext: Substring to be present in the notification's message.
            If not given, only check for notification type.
        :param ntype: type of notification. Can be any of bootstraps possible alert
            contextes or 'error', which will expect a 'danger' alert.
        :param static: whether to search for a static notification
        :param msg: Custom message on assertion failure.
        """
        if ntype == 'error':  # allow this for convenience
            ntype = 'danger'

        div = 'static-notifications' if static else 'notifications'
        alert_type_class = f" alert-{ntype}" if ntype is not None else ""
        # source: https://devhints.io/xpath#string-functions
        notifications = self.response.lxml.xpath(
                f"//div[@id='{div}']/div[starts-with(@class,'alert{alert_type_class}')]"
                "/span[@class='notificationMessage']")
        self.assertTrue(notifications,
                        msg=(f"No{alert_type_class} notification found."
                             if msg is None else msg))
        if ntext is not None:
            # joining them this way is useful for meaningful failure message
            all_texts = " | ".join(n.text_content().strip() for n in notifications)
            self.assertIn(ntext, all_texts, msg=msg)

    def assertLogin(self, name: str) -> None:
        """Assert that a user is logged in by checking their display name."""
        span = self.response.lxml.xpath("//span[@id='displayname']")[0]
        self.assertEqual(name.strip(), span.text_content().strip())

    def assertValidationError(
            self, fieldname: str, message: str = "", index: Optional[int] = None,
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
            If this is None, skip the notification check.
        :raise AssertionError: If field is not found, field is not within
            .has-error container or error message is not found
        """
        self._assertValidationComplaint(
            kind="error", fieldname=fieldname, message=message, index=index,
            notification=notification)

    def assertValidationWarning(
            self, fieldname: str, message: str = "", index: Optional[int] = None,
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
            If this is None, skip the notification check.
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
            self.assertNotification(notification, alert_type)

        nodes = self.response.lxml.xpath(
            f'(//input|//select|//textarea)[@name="{fieldname}"]')
        f = fieldname
        if index is None:
            if len(nodes) == 1:
                node = nodes[0]
            elif not nodes:  # pragma: no cover
                self.fail(f"No input with name {f!r} found.")
            else:  # pragma: no cover
                self.fail(f"More than one input with name {f!r} found."
                          f" Need to specify index.")
        else:
            try:
                node = nodes[index]
            except IndexError:  # pragma: no cover
                raise self.failureException(
                    f"Input with name {f!r} and index {index} not found."
                    f" {len(nodes)} inputs with name {f!r} found.") from None

        # From https://devhints.io/xpath#class-check
        container = node.xpath(
            "ancestor::*[contains(concat(' ',normalize-space(@class),' '),"
            f"' has-{kind} ')]")
        if not container:
            self.fail(f"Input with name {f!r} is not contained in an .has-{kind} box.")
        normalized = re.sub(r'\s+', ' ', container[0].text_content())
        errmsg = (f"Expected error message not found near input with name {f!r}:\n"
                  f"{normalized}")
        self.assertIn(message, normalized, errmsg)

    def assertNoLink(self, href_pattern: Optional[Union[str, Pattern[str]]] = None,
                     tag: str = 'a', href_attr: str = 'href',
                     content: Optional[str] = None, verbose: bool = False) -> None:
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
                print(s)  # pragma: no cover

        for element in self.response.html.find_all(tag):
            el_html = str(element)
            el_content = element.decode_contents()
            printlog(f"Element: {el_html!r}")
            if not element.get(href_attr):
                printlog(f"  Skipped: no {href_attr!r} attribute")
                continue
            if href_pat and not href_pat(element[href_attr]):
                printlog("  Skipped: doesn't match href")
                continue
            if content_pat and not content_pat(el_content):
                printlog("  Skipped: doesn't match description")
                continue
            printlog("  Link found")  # pragma: no cover
            self.fail(
                f"Tag '{tag}' with {href_attr} == {element[href_attr]}"
                f" and content '{el_content}' has been found.")

    def assertLogEqual(self, log_expectation: Sequence[CdEDBObject], realm: str,
                       **kwargs: Any) -> None:
        saved_response = self.response

        # Check raw log.
        super().assertLogEqual(log_expectation, realm=realm, **kwargs)

        persona_ids = [p_id for e in log_expectation if (p_id := e['persona_id'])]
        personas = self.core.get_personas(self.key, persona_ids)
        entity_key = "mailinglist_id" if realm == "ml" else f"{realm}_id"
        entity_ids = [e_id for e in log_expectation if (e_id := e.get(entity_key))]
        specific_log = False
        if realm == "event":
            entities = {event_id: event.to_database() for event_id, event
                        in self.event.get_events(self.key, entity_ids).items()}
            if event_id := kwargs.get('event_id'):
                specific_log = True
                self.get(f"/event/event/{event_id}/log")
            else:
                self.get("/event/log")
        elif realm == "assembly":  # TODO: coverage
            entities = self.assembly.get_assemblies(self.key, entity_ids)
            if assembly_id := kwargs.get('assembly_id'):
                specific_log = True
                self.get(f"/assembly/assembly/{assembly_id}/log")
            else:
                self.get("/assembly/log")
        elif realm == "ml":
            entities = {ml_id: ml.to_database() for ml_id, ml
                        in self.ml.get_mailinglists(self.key, entity_ids).items()}
            if ml_id := kwargs.get('mailinglist_id'):  # TODO: coverage
                self.get(f"/ml/mailinglist/{ml_id}/log")
                specific_log = True
            else:
                self.get("/ml/log")
        elif realm == "finance":
            self.get("/cde/finances")
            entities = {}
        elif realm == "changelog":
            self.get("/core/changelog/view")
            entities = {}
        else:
            self.get(f"/{realm}/log")
            entities = {}

        # Retrieve frontend log.
        f = self.response.forms['logshowform']
        for field_name in f.fields:
            if v := kwargs.get(field_name):
                f[field_name] = v
        f['length'] = len(log_expectation)
        self.submit(f)

        # Check frontend log.
        for i, entry in enumerate(log_expectation, start=1):
            log_id = entry['id']
            self.assertPresence(entry['change_note'] or "", div=f"{i}-{log_id}")
            self.assertPresence(self.gettext(str(entry['code'])), div=f"{i}-{log_id}")
            if entry['persona_id']:
                name = make_persona_name(personas[entry['persona_id']])
                self.assertPresence(name, div=f"{i}-{log_id}")
            if (entity_id := entry.get(entity_key)) and not specific_log:
                self.assertPresence(entities[entity_id]['title'], div=f"{i}-{log_id}")

        self.response = saved_response

    def log_pagination(self, title: str, logs: tuple[tuple[int, CdEIntEnum], ...],
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

        # Check csv export
        save = self.response
        self.response = f.submit("download", value="csv")
        self.assertIn('id;ctime;code;change_note;', self.response.text)
        self.assertIn('persona_id;persona_id_family_name;persona_id_given_names;',
                      self.response.text)
        self.assertIn('submitted_by;submitted_by_family_name;submitted_by_given_names',
                      self.response.text)
        self.response = save

    def _log_subroutine(self, title: str,
                        all_logs: tuple[tuple[int, CdEIntEnum], ...],
                        start: int, end: int) -> None:
        total = len(all_logs)
        self.assertTitle(f"{title} [{start}–{end} von {total}]")

        if end > total:
            end = total

        # adapt slicing to our count of log entries
        logs = all_logs[start-1:end]
        for index, log_entry in enumerate(logs, start=1):
            log_id, log_code = log_entry
            log_code_str = self.gettext(str(log_code))
            self.assertPresence(log_code_str, div=f"{index}-{log_id}")

    def check_sidebar(self, ins: set[str], out: set[str]) -> None:
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
            self.fail(f"Unexpected sidebar elements '{present}' found.")

    def check_create_archive_user(self, realm: str, data: Optional[CdEDBObject] = None,
                                  ) -> None:
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
        self.traverse("Nutzer verwalten")
        self.assertTitle("utzerverwaltung", exact=False)
        f = self.response.forms['queryform']
        f['qop_is_archived'] = ""
        f['qop_given_names'] = QueryOperators.match.value
        f['qval_given_names'] = 'Zelda'
        self.submit(f)
        self.assertTitle("utzerverwaltung", exact=False)
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
                                 current_state: Optional[bool] = None) -> None:
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
            raise KeyError(f"Admin view toggle with label {label!r} not found.")  # pragma: no cover  # noqa: E501
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
    apps: list[webtest.TestApp]
    responses: list[webtest.TestResponse]

    @classmethod
    def setUpClass(cls) -> None:
        """Create n new apps, overwrite cls.app with a reference."""
        super().setUpClass()
        cls.apps = [
            webtest.TestApp(
                Application(),
                extra_environ=cls.app_extra_environ,
            )
            for _ in range(cls.n)
        ]
        # The super().setUpClass overwrites the property, so reset it here.
        cls.app = property(fget=cls.get_app, fset=cls.set_app)
        cls.responses = [None for _ in range(cls.n)]
        cls.current_app = 0

    def setUp(self, *args: Optional[str], **kwargs: Optional[str]) -> None:
        """Reset all apps and responses and the current app index."""
        self.responses = [None for _ in range(self.n)]
        super().setUp(*args, **kwargs)
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

    def set_app(self, value: webtest.TestApp) -> None:  # pragma: no cover
        self.apps[self.current_app] = value

    app = property(fget=get_app, fset=set_app)

    def switch_app(self, i: int) -> None:
        """Switch to a different index.

        Sets the app and response with the specified index as active.
        All methods of the super class only interact with the active app and
        response.
        """
        if not 0 <= i < self.n:
            raise ValueError(f"Invalid index. Must be between 0 and {self.n}.")  # pragma: no cover  # noqa: E501
        self.current_app = i


class StoreTrace(NamedTuple):
    cron: str
    data: CdEDBObject


class MailTrace(NamedTuple):
    realm: str
    template: str
    args: Sequence[Any]
    kwargs: dict[str, Any]


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
    _remaining_periodics: set[str]
    _remaining_tests: set[str]
    stores: list[StoreTrace]
    mails: list[MailTrace]
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
        cls.cron = CronFrontend()
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
            raise cls.failureException(
                f"The following cron-periodics never ran: {cls._remaining_periodics}")

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
            raise ValueError("Must specify jobs to run.")  # pragma: no cover
        self._remaining_periodics.difference_update(args)
        self.cron.execute(args)
        if check_stores:
            expectation = set(args) | {"_base"}
            self.assertEqual(expectation, set(s.cron for s in self.stores))
