#!/usr/bin/env python3

import locust


class TrivialUser(locust.HttpUser):
    def on_start(self):
        self.client.verify = False  # disable SSL verification

    @locust.task
    def landing_page(self):
        self.client.get("/db/")


if __name__ == "__main__":
    locust.run_single_user(TrivialUser)
