#!/usr/bin/env python3

import unittest
import sys
import subprocess
import inspect
import functools
import os
import time
import os.path
import webtest
from cdedb.config import BasicConfig
from cdedb.frontend.application import Application
from cdedb.backend.common import do_singularization
from cdedb.backend.core import CoreBackend
from cdedb.backend.session import SessionBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.event import EventBackend

_BASICCONF = BasicConfig()

class BackendShim:
    def __init__(self, backend):
        self._backend = backend
        self._funs = {}
        funs = inspect.getmembers(backend, predicate=inspect.isroutine)
        for name, fun in funs:
            if hasattr(fun, "access_list") or hasattr(fun, "internal_access_list"):
                self._funs[name] = self._wrapit(fun)
                if hasattr(fun, "singularization_hint"):
                    hint = fun.singularization_hint
                    self._funs[hint['singular_function_name']] = self._wrapit(
                        do_singularization(fun))
                    setattr(self._backend, hint['singular_function_name'],
                            do_singularization(fun))

    def _wrapit(self, fun):
        @functools.wraps(fun)
        def new_fun(key, *args, **kwargs):
            rs = self._backend.establish(key, fun.__name__, allow_internal=True)
            if rs:
                return getattr(self._backend, fun.__name__)(rs, *args, **kwargs)
            else:
                raise RuntimeError("Permission denied")
        return new_fun

    def __getattr__(self, name):
        if name in {"_funs", "_backend"}:
            raise AttributeError()
        return self._funs[name]

class BackendUsingTest(unittest.TestCase):
    used_backends = None

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        classes = {
            "core": CoreBackend,
            "session": SessionBackend,
            "cde": CdEBackend,
            "event": EventBackend,
            # TODO add more backends when they become available
        }
        for backend in self.used_backends:
            setattr(self, backend, self.initialize_backend(classes[backend]))

    def initialize_raw_backend(self, backendcls):
        return backendcls(os.path.join(_BASICCONF.REPOSITORY_PATH,
                                       _BASICCONF.TESTCONFIG_PATH))

    def initialize_backend(self, backendcls):
        return BackendShim(self.initialize_raw_backend(backendcls))

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
        'username': "anton@example.cde",
        'password': "secret",
        'display_name': "Anton",
        'given_names': "Anton Armin A.",
        'family_name': "Administrator",
    },
    "berta": {
        'id': 2,
        'username': "berta@example.cde",
        'password': "secret",
        'display_name': "Bertå",
        'given_names': "Bertålotta",
        'family_name': "Beispiel",
    },
    "charly": {
        'id': 3,
        'username': "charly@example.cde",
        'password': "secret",
        'display_name': "Charly",
        'given_names': "Charly C.",
        'family_name': "Clown",
    },
    "daniel": {
        'id': 4,
        'username': "daniel@example.cde",
        'password': "secret",
        'display_name': "Daniel",
        'given_names': "Daniel D.",
        'family_name': "Dino",
    },
    "emilia": {
        'id': 5,
        'username': "emilia@example.cde",
        'password': "secret",
        'display_name': "Emilia",
        'given_names': "Emilia E.",
        'family_name': "Eventis",
    },
    "ferdinand": {
        'id': 6,
        'username': "ferdinand@example.cde",
        'password': "secret",
        'display_name': "Ferdinand",
        'given_names': "Ferdinand F.",
        'family_name': "Findus",
    },
    "garcia": {
        'id': 7,
        'username': "garcia@example.cde",
        'password': "secret",
        'display_name': "Garcia",
        'given_names': "Garcia G.",
        'family_name': "Generalis",
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

    @classmethod
    def setUpClass(cls):
        env = os.putenv("CONFIGPATH", os.path.join(_BASICCONF.REPOSITORY_PATH, _BASICCONF.TESTCONFIG_PATH))
        subprocess.Popen(("make", "run-core"), stdout=subprocess.DEVNULL)
        subprocess.Popen(("make", "run-session"), stdout=subprocess.DEVNULL)
        subprocess.Popen(("make", "run-cde"), stdout=subprocess.DEVNULL)
        subprocess.Popen(("make", "run-event"), stdout=subprocess.DEVNULL)
        ## wait until the backend servers appear
        pid_files = ('/run/cdedb/test-coreserver.pid',
                     '/run/cdedb/test-cdeserver.pid',
                     '/run/cdedb/test-sessionserver.pid',
                     '/run/cdedb/test-eventserver.pid')
        tries = 0
        while tries < 10**4:
            found = []
            for pid_file in pid_files:
                try:
                    with open(pid_file) as f:
                        found.append(f.read())
                except FileNotFoundError:
                    found.append(False)
            if all(found):
                break
            time.sleep(0.01)
        else:
            raise RuntimeError("Backends did not appear.")
        app = Application(os.path.join(_BASICCONF.REPOSITORY_PATH, _BASICCONF.TESTCONFIG_PATH))
        cls.app = webtest.TestApp(app, extra_environ={'REMOTE_ADDR': "127.0.0.0", 'SERVER_PROTOCOL': "HTTP/1.1"})

    @classmethod
    def tearDownClass(cls):
        subprocess.check_call(("make", "quit-test-backends"), stdout=subprocess.DEVNULL)

    def setUp(self):
        subprocess.check_call(("make", "sample-data-test-shallow"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.app.reset()
        self.response = None

    def basic_validate(self):
        self.assertNotIn(b"cgitb", self.response.body)
        if self.response.content_type == "text/html":
            texts = self.response.lxml.xpath('/html/head/title/text()')
            self.assertNotEqual(0, len(texts))
            self.assertNotEqual('Fehler', texts[0])

    def get(self, *args, **kwargs):
        self.response = self.app.get(*args, **kwargs)
        self.basic_validate()

    def follow(self):
        self.response = self.response.maybe_follow()

    def post(self, *args, **kwargs):
        self.response = self.app.post(*args, **kwargs)
        self.follow()
        self.basic_validate()

    def submit(self, form, button="submitform"):
        self.response = form.submit(button)
        self.follow()
        self.basic_validate()

    def traverse(self, *links):
        for link in links:
            self.response = self.response.click(**link)
            self.follow()
            self.basic_validate()

    def login(self, user):
        self.get("/")
        f = self.response.forms['loginform']
        f['username'] = user['username']
        f['password'] = user['password']
        self.submit(f)

    def logout(self):
        f = self.response.forms['logoutform']
        self.submit(f)

    def fetch_mail(self):
        elements = self.response.lxml.xpath("//div[@class='notification infoNotification']/span/text()")
        mails = [x[30:] for x in elements if x.startswith("Stored email to hard drive at ")]
        ret = []
        for path in mails:
            with open(path) as f:
                ret.append(f.read())
        return ret

    def assertTitle(self, title):
        self.assertEqual(title, self.response.lxml.xpath('//h1/text()')[0])
