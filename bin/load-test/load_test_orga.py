#!/usr/bin/env python3

import collections
import random
import uuid
import threading
import time

import locust


context = {
    'persona': 0,
    'local': threading.local(),
    'lock': threading.Lock()
}

NUM_EVENTS = 100
NUM_ORGAS = 10
INITIAL_ORGA_OFFSET = 200
INTER_EVENT_OFFSET = 110
ORGAS = {
    INITIAL_ORGA_OFFSET + INTER_EVENT_OFFSET*event + orga: event
    for event in range(NUM_EVENTS)
    for orga in range(NUM_ORGAS)
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


def getorga():
    if hasattr(context['local'], 'persona'):
        return context['local'].persona
    _, persona = manipulate_context(
        'persona', lambda x: min(o for o in ORGAS if o > x))
    context['local'].persona = persona
    return persona


def getevent_id(orga):
    return 1001 + ORGAS[orga]


def gettrack(orga, track):
    return ORGAS[orga]*2 + track


def getpart_id(orga, part):
    return 1001 + ORGAS[orga]*2 + part


def gettrack_id(orga, track):
    return 1001 + ORGAS[orga]*2 + track


class OrgaUser(locust.HttpUser):
    def login(self):
        while True:
            username = f"email{getorga():010}@example.cde"
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
    def event_stats(self):
        with self.client.get(f"/db/event/event/{getevent_id(getorga())}/stats",
                             catch_response=True) as response:
            if f"Schiene{gettrack(getorga(), 0):010}" not in response.text:
                dolog('Failed response:')
                dolog(response.text)
                if 'loginform' in response.text:
                    dolog('Logged out.')
                    self.login()
                response.failure("Invalid response")
        query_url = (
            f"/db/event/event/{getevent_id(getorga())}/registration/query"
            f"?is_search=True&qsel_persona.given_names=True"
            f"&qsel_persona.family_name=True"
            f"&qsel_part{getpart_id(getorga(), 0)}.status=True"
            f"&qsel_course{gettrack_id(getorga(), 0)}.title=True"
            f"&qsel_reg_fields.xfield_is_child=True"
            f"&qord_0=reg.id&qord_0_ascending=True"
            f"&query_scope=QueryScope.registration&submitform=True"
        )
        with self.client.get(query_url, catch_response=True) as response:
            if "Ergebnis [100]" not in response.text:
                dolog('Failed response:')
                dolog(response.text)
                if 'loginform' in response.text:
                    dolog('Logged out.')
                    self.login()
                response.failure("Invalid response")


if __name__ == "__main__":
    locust.run_single_user(OrgaUser)


