#!/usr/bin/env python3

import collections
import random
import re
import uuid
import threading
import time

import locust

context = {
    'persona': 1,
    'local': threading.local(),
    'lock': threading.Lock()
}


def dolog(s):
    if not hasattr(context['local'], 'uuid'):
        random.seed()
        context['local'].uuid = uuid.uuid4()
    with open(f'/tmp/locust-{context["local"].uuid}.log', 'a') as f:
        f.write(s + '\n')


def manipulate_context(attr, fun):
    with context['lock']:
        old = context[attr]
        new = context[attr] = fun(old)
    return old, new


def getpersona():
    persona, _ = manipulate_context('persona', lambda x: x+1)
    return persona


class RegisteringUser(locust.HttpUser):
    def login(self):
        if self.persona is None:
            self.persona = getpersona()
        while True:
            username = f"email{self.persona:010}@example.cde"
            response = self.client.post(
                "/db/core/login", {"username": username, "password":"secret"})
            if response.status_code // 100 == 2 and 'loginform' not in response.text:
                dolog(f'Logged in as {username}')
                break
            time.sleep(1)

    def on_start(self):
        dolog('Starting')
        self.client.verify = False  # disable SSL verification
        self.persona = None

    @locust.task
    def register_one(self):
        self.login()
        with self.client.get("/db/event/event/1001/register",
                             catch_response=True) as response:
            if mo := re.search(r'name="_anti_csrf" value="([^"]*)"', response.text):
                token = mo.groups(1)
            else:
                # This will happen especially if this test ran previously and
                # some of the accounts are already registered
                dolog(f'Failed CSRF lookup for {self.persona}')
                self.persona = None
                return

        parameters = {
            'parts': 1001,
            'track1001.course_choice_0': 1001,
            'track1001.course_choice_1': 1002,
            'track1001.course_choice_2': 1003,
            'reg.list_consent': 'True',
            'reg.mixed_lodging': 'True',
            '_anti_csrf': token,
        }
        with self.client.post("/db/event/event/1001/register", parameters,
                              catch_response=True) as response:
            if f"Bitte fülle jetzt den" not in response.text:
                dolog('Failed response:')
                dolog(response.text)
                if 'loginform' in response.text:
                    dolog('Logged out.')
                    self.login()
                response.failure("Invalid response")
            else:
                dolog(f'Successfully registered {self.persona}')
                self.persona = None


if __name__ == "__main__":
    locust.run_single_user(RegisteringUser)
