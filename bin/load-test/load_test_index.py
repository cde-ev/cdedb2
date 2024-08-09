#!/usr/bin/env python3

import collections
import random
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
    if hasattr(context['local'], 'persona'):
        return context['local'].persona
    persona, _ = manipulate_context('persona', lambda x: x+1)
    context['local'].persona = persona
    return persona


class SimpleUser(locust.HttpUser):
    def login(self):
        while True:
            username = f"email{getpersona():010}@example.cde"
            response = self.client.post(
                "/db/core/login", {"username": username, "password":"secret"})
            if response.status_code // 100 == 2 and 'loginform' not in response.text:
                dolog(f'Logged in as {username}')
                break
            time.sleep(1)

    def on_start(self):
        dolog('Starting')
        self.client.verify = False  # disable SSL verification
        self.login()

    @locust.task
    def my_profile(self):
        with self.client.get("/db/core/self/show", catch_response=True) as response:
            if f"Stadt{getpersona():010}" not in response.text:
                dolog('Failed response:')
                dolog(response.text)
                if 'loginform' in response.text:
                    dolog('Logged out.')
                    self.login()
                response.failure("Invalid response")


if __name__ == "__main__":
    locust.run_single_user(SimpleUser)
