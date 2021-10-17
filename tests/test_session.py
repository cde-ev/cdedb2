#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import secrets
from typing import List, NamedTuple, Sequence, Optional, cast

from cdedb.common import RequestState, User, now
from tests.common import (
    UserIdentifier, USER_DICT, BackendTest, MultiAppFrontendTest, execsql, get_user,
)

SessionEntry = NamedTuple(
    "SessionEntry", [("persona_id", int), ("is_active", bool), ("ip", str),
                     ("sessionkey", str), ("ctime", Optional[datetime.datetime]),
                     ("atime", Optional[datetime.datetime])])


def make_session_entry(persona_id: int, is_active: bool = True, ip: str = "127.0.0.1",
                       sessionkey: str = None, ctime: datetime.datetime = None,
                       atime: datetime.datetime = None) -> SessionEntry:
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


class TestMultiSessionFrontend(MultiAppFrontendTest):
    n = 3  # Needs to be at least 3 for the following test to work correctly.

    def _setup_multisessions(self, user: UserIdentifier, session_cookie: str
                             ) -> List[Optional[str]]:
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
                self.assertPresence(f"Von allen Geräten abmelden ({self.n - 1})")
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
