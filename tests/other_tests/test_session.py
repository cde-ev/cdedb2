#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import secrets
from collections.abc import Sequence
from typing import NamedTuple, Optional, cast

import cdedb.models.droid as model_droid
from cdedb.common import RequestState, User, nearly_now, now
from cdedb.common.exceptions import APITokenError
from tests.common import (
    USER_DICT, BackendTest, FrontendTest, MultiAppFrontendTest, UserIdentifier, execsql,
    get_user,
)


class SessionEntry(NamedTuple):
    persona_id: int
    is_active: bool
    ip: str
    sessionkey: str
    ctime: Optional[datetime.datetime]
    atime: Optional[datetime.datetime]


def make_session_entry(persona_id: int, is_active: bool = True, ip: str = "127.0.0.1",
                       sessionkey: Optional[str] = None,
                       ctime: Optional[datetime.datetime] = None,
                       atime: Optional[datetime.datetime] = None) -> SessionEntry:
    if sessionkey is None:
        sessionkey = secrets.token_hex()
    return SessionEntry(persona_id, is_active, ip, sessionkey, ctime, atime)


def insert_sessions_template(data: Sequence[SessionEntry]) -> str:
    values = ', '.join(
        f"({e.persona_id}, {e.is_active}, '{e.ip}', '{e.sessionkey}',"
        f" '{e.ctime if e.ctime else 'now()'}', '{e.atime if e.atime else 'now()'}')"
        for e in data)
    return (f"INSERT INTO core.sessions"
            f" (persona_id, is_active, ip, sessionkey, ctime, atime) VALUES {values}")


class TestSessionBackend(BackendTest):
    used_backends = ("core", "session")

    def test_sessionlookup(self) -> None:
        user = self.session.lookupsession("random key", "127.0.0.0")
        self.assertIsNone(user.persona_id)
        self.assertEqual({"anonymous"}, user.roles)
        key = self.login(USER_DICT["anton"])
        user = self.session.lookupsession(key, "127.0.0.0")
        self.assertIsInstance(user, User)
        self.assertEqual(USER_DICT["anton"]['id'], user.persona_id)

    def test_tokenlookup(self) -> None:
        persona_sessionkey = cast(RequestState, self.core.login(
            self.key, USER_DICT['anton']['username'],
            USER_DICT['anton']['password'], '127.0.0.0'))

        # pylint: disable=protected-access
        # Invalid apitoken.
        with self.assertRaisesRegex(APITokenError, "Malformed API token."):
            self.session.lookuptoken("random token", "127.0.0.0")

        # "resolve" droid api token.
        resolve_secret = self.secrets['API_TOKENS']['resolve']
        resolve_token = model_droid.ResolveToken.get_token_string(resolve_secret)

        user = self.session.lookuptoken(resolve_token, "127.0.1.0")
        self.assertIsNone(user.persona_id)
        self.assertIs(model_droid.ResolveToken, user.droid_class)
        self.assertIsNone(user.droid_token_id)
        self.assertEqual(
            {"anonymous", "droid", "droid_resolve", "droid_infra"}, user.roles)

        # "resolve" droid api token with invalid secret.
        invalid_resolve_token = model_droid.ResolveToken.get_token_string("abc")

        with self.assertRaisesRegex(APITokenError, "Invalid API token."):
            self.session.lookuptoken(invalid_resolve_token, "127.0.1.1")

        # "quick_partial_export" droid.
        qpe_secret = self.secrets['API_TOKENS']['quick_partial_export']
        qpe_token = model_droid.QuickPartialExportToken.get_token_string(qpe_secret)

        user = self.session.lookuptoken(qpe_token, "127.0.1.2")
        self.assertIsNone(user.persona_id)
        self.assertIs(model_droid.QuickPartialExportToken, user.droid_class)
        self.assertIsNone(user.droid_token_id)
        self.assertEqual(
            {"anonymous", "droid", "droid_quick_partial_export"}, user.roles)

        # "quick_partial_export" with invalid secret.
        invalid_qpe_token = model_droid.QuickPartialExportToken.get_token_string("abc")

        with self.assertRaisesRegex(APITokenError, "Invalid API token."):
            self.session.lookuptoken(invalid_qpe_token, "127.0.1.3")

        # event specific orga droid.
        orga_token_secret = "0123456789abcdeffedcba9876543210" * 2
        orgatoken = model_droid.OrgaToken._get_token_string(
            model_droid.OrgaToken._get_droid_name(1), orga_token_secret)

        self.assertIsNone(self.event.get_orga_token(persona_sessionkey, 1).atime)

        user = self.session.lookuptoken(orgatoken, "127.0.2.0")
        self.assertIsNone(user.persona_id)
        self.assertIs(model_droid.OrgaToken, user.droid_class)
        self.assertEqual(1, user.droid_token_id)
        self.assertIn(1, user.orga)
        self.assertEqual({"anonymous", "droid", "droid_orga"}, user.roles)

        last_valid_access = self.event.get_orga_token(persona_sessionkey, 1).atime
        self.assertEqual(nearly_now(), last_valid_access)

        # orga droid with invalid secret.
        invalid_orgatoken = model_droid.OrgaToken._get_token_string(
            model_droid.OrgaToken._get_droid_name(1), "abc")
        with self.assertRaisesRegex(APITokenError, "Invalid .+ token."):
            self.session.lookuptoken(invalid_orgatoken, "127.0.2.1")

        # Expire token and try again.
        execsql("UPDATE event.orga_apitokens SET etime = now()")
        with self.assertRaisesRegex(APITokenError, r"This .+ token has expired."):
            self.session.lookuptoken(orgatoken, "127.0.2.2")

        # Revoke token and try again.
        execsql("UPDATE event.orga_apitokens SET rtime = now(), secret_hash = NULL")
        with self.assertRaisesRegex(
                APITokenError, "This .+ token has been revoked."):
            self.session.lookuptoken(orgatoken, "127.0.2.3")

        self.assertEqual(
            last_valid_access, self.event.get_orga_token(persona_sessionkey, 1).atime)

    def test_ip_mismatch(self) -> None:
        key = self.login(USER_DICT["anton"], ip="1.2.3.4")
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertIsInstance(user, User)
        self.assertTrue(user.persona_id)
        user = self.session.lookupsession(key, "4.3.2.1")
        self.assertEqual(None, user.persona_id)
        user = self.session.lookupsession(key, "1.2.3.4")
        self.assertEqual(None, user.persona_id)

    def test_multiple_sessions(self) -> None:
        # Logging out only works with the ip "127.0.0.0", which is the
        # default value from `setup_requeststate`.
        ips = ["127.0.0.0", "4.3.2.1", "127.0.0.0"]
        keys = []
        users = []
        for ip in ips:
            keys.append(self.login(USER_DICT["anton"], ip=ip))
            users.append(self.session.lookupsession(keys[-1], ip))
            self.assertIsInstance(users[-1], User)
            self.assertTrue(users[-1].persona_id)
        for i, user in enumerate(users[:-1]):
            self.assertNotEqual({"anonymous"}, user.roles)
            self.assertNotEqual(user, users[i+1])
            self.assertEqual(user.__dict__, users[i+1].__dict__)

        # Terminate a single session.
        self.core.logout(cast(RequestState, keys[0]))
        # Check termination.
        self.assertEqual(
            {"anonymous"},
            self.session.lookupsession(keys[0], ips[0]).roles)
        # Check that other sessions are untouched.
        for i in (1, 2):
            self.assertEqual(
                users[i].__dict__,
                self.session.lookupsession(keys[i], ips[i]).__dict__)

        # Terminate all sessions.
        self.core.logout(cast(RequestState, keys[2]), other_sessions=True)
        # Check that all sessions have been terminated.
        for i in (0, 1, 2):
            self.assertEqual(
                {"anonymous"},
                self.session.lookupsession(keys[i], ips[i]).roles)

    def test_max_active_sessions(self) -> None:
        user_data = USER_DICT["anton"]
        ip = "1.2.3.4"
        # Create and check the maximum number of allowed sessions.
        keys = [self.login(user_data, ip=ip)
                for _ in range(self.conf["MAX_ACTIVE_SESSIONS"])]
        for i, key in enumerate(keys):
            with self.subTest(i=i, key=key):
                user = self.session.lookupsession(key, ip=ip)
                self.assertEqual(user.persona_id, user_data['id'])
                self.assertLess({"anonymous"}, user.roles)
        # Create another session and check it.
        keys.append(self.login(user_data, ip=ip))
        user = self.session.lookupsession(keys[-1], ip=ip)
        self.assertEqual(user.persona_id, user_data['id'])
        self.assertLess({"anonymous"}, user.roles)
        # Check that the oldest session has now been terminated.
        user = self.session.lookupsession(keys[0], ip=ip)
        self.assertIsNone(user.persona_id)
        self.assertEqual({"anonymous"}, user.roles)

    def test_logout_everywhere(self) -> None:
        ip = "1.2.3.4."

        # Create some sessions for some different users.
        keys = {u: self.login(u, ip=ip) for u in USER_DICT
                if u not in {"hades", "lisa", "olaf", "anonymous"}}
        for u, key in keys.items():
            with self.subTest(user=u, key=key):
                user = self.session.lookupsession(key, ip)
                self.assertEqual(user.persona_id, USER_DICT[u]["id"])
                self.assertLess({"anonymous"}, user.roles)

        # Create a new session and do a "logout everywhere" with it.
        logout_user = "anton"
        # This will only work with this specific ip:
        key = self.login(logout_user, ip="127.0.0.0")
        self.core.logout(cast(RequestState, key), other_sessions=True)

        # Check that the other sessions (from other users) are still active.
        for u, key in keys.items():
            with self.subTest(user=u, key=key):
                user = self.session.lookupsession(key, ip)
                if u == logout_user:
                    self.assertIsNone(user.persona_id)
                    self.assertEqual({"anonymous"}, user.roles)
                else:
                    self.assertEqual(user.persona_id, USER_DICT[u]["id"])
                    self.assertLess({"anonymous"}, user.roles)

    def test_old_sessions(self) -> None:
        old_time = now() - datetime.timedelta(days=50)
        delta = datetime.timedelta(minutes=1)
        entries = [
            make_session_entry(1, ctime=old_time, atime=old_time),
            make_session_entry(1, ctime=old_time + delta, atime=old_time + delta),
            make_session_entry(1, ctime=old_time + 2*delta, atime=old_time + 2*delta),
            make_session_entry(2, ctime=old_time, atime=old_time),
            make_session_entry(2, ctime=old_time + delta, atime=old_time + delta),
            make_session_entry(3, ctime=old_time, atime=old_time),
            make_session_entry(3, ctime=old_time + delta, atime=old_time + delta)]
        unique_personas = len(set(e.persona_id for e in entries))
        execsql(insert_sessions_template(entries))

        user = USER_DICT["anton"]
        key = self.login(user)
        self.login("vera")
        self.assertEqual(len(entries) - unique_personas,
                         self.core.deactivate_old_sessions(self.key))
        self.assertEqual(0, self.core.deactivate_old_sessions(self.key))
        self.assertEqual(len(entries) - unique_personas,
                         self.core.clean_session_log(self.key))
        self.assertEqual(0, self.core.clean_session_log(self.key))

        u = self.session.lookupsession(key, "127.0.0.0")
        self.assertEqual(u.persona_id, user["id"])


class TestSessionFrontend(FrontendTest):
    def test_2285(self) -> None:
        self.login("anton")
        self.traverse("Veranstaltungen", "Große Testakademie 2222", "Kurse",
                      "Kurs hinzufügen")
        f = self.response.forms['configurecourseform']
        f['nr'] = "1"
        f['title'] = "Test"
        f['shortname'] = "test"
        self.submit(f)
        # Delete sessionkey and submit again.
        self.app.reset()
        try:
            self.submit(f, check_notification=False)
        except RuntimeError:  # pragma: no cover
            self.fail("Input validation not checked when submitting csrf-protected"
                      " form withput sessionkey.")


class TestMultiSessionFrontend(MultiAppFrontendTest):
    n = 3  # Needs to be at least 3 for the following test to work correctly.

    def _setup_multisessions(self, user: UserIdentifier, session_cookie: str,
                             ) -> list[Optional[str]]:
        user = get_user(user)
        self.assertGreaterEqual(self.n, 3, "This test will only work correctly"
                                           " with 3 or more apps.")
        # Set up multiple sessions.
        keys = []
        for i in range(self.n):
            self.switch_app(i)
            self.login(user)
            keys.append(self.app.cookies[session_cookie])
            # Check that we are correctly logged in.
            self.get("/core/self/show")
            self.assertTitle(user['default_name_format'])
            self.assertNotIn('loginform', self.response.forms)
        self.assertEqual(len(set(keys)), len(keys))

        return keys

    def test_logout_all(self) -> None:
        user = USER_DICT["anton"]
        session_cookie = "sessionkey"
        self._setup_multisessions(user, session_cookie)

        # Terminate session 0.
        self.switch_app(0)
        self.logout()
        self.get("/core/self/show")
        self.assertTitle("CdE-Datenbank")
        self.assertIn('loginform', self.response.forms)
        # Check that other sessions are still active.
        for i in range(1, self.n):
            self.switch_app(i)
            with self.subTest(app_index=i):
                self.get("/core/self/show")
                self.assertTitle(user['default_name_format'])
                self.assertPresence(f"Von allen ({self.n - 1}) Geräten abmelden")
                self.assertNotIn('loginform', self.response.forms)

        # Now terminate all sessions and check that they are all inactive.
        self.switch_app(self.n - 1)
        f = self.response.forms['logoutallform']
        self.submit(f)
        self.assertPresence(f"{self.n - 1} Sitzung(en) beendet.",
                            div="notifications")
        for i in range(self.n):
            self.switch_app(i)
            with self.subTest(app_index=i):
                self.get("/core/self/show")
                self.assertTitle("CdE-Datenbank")
                self.assertIn('loginform', self.response.forms)

    def test_change_password(self) -> None:
        user = USER_DICT["inga"]
        session_cookie = "sessionkey"
        self._setup_multisessions(user, session_cookie)

        # Change password in session 0
        self.switch_app(0)
        new_password = 'krce84#(=kNO3xb'
        self.traverse({'description': user['display_name']},
                      {'description': 'Passwort ändern'})
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)

        # Check that no other sessions are still active.
        for i in range(1, self.n):
            self.switch_app(i)
            with self.subTest(app_index=i):
                self.get("/core/self/show")
                self.assertTitle("CdE-Datenbank")
                self.assertIn('loginform', self.response.forms)

    def test_basics(self) -> None:
        self.login(USER_DICT["anton"])
        self.switch_app(1)
        self.login(USER_DICT["berta"])
        self.switch_app(0)
        self.assertLogin(USER_DICT["anton"]["display_name"])
        self.switch_app(1)
        self.assertLogin(USER_DICT["berta"]["display_name"])
        self.logout()
        self.assertIn('loginform', self.response.forms)
        self.switch_app(0)
        self.assertLogin(USER_DICT["anton"]["display_name"])
