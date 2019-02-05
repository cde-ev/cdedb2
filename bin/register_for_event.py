#!/usr/bin/env python3

"""
This Python script shall test if registration for an event in the new cdedb is successful, and if so, how much time it
took. The main idea is to use Selenium to emulate browser actions and then to performance-test page loading.
"""

from selenium import webdriver
import selenium.webdriver.support.ui as ui
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver
from optparse import OptionParser
from typing import List, Dict
import datetime
import abc
import logging
import re


class RegistrationResult:
    success = False  # type: bool
    time_taken = 60 * 1000  # type: float


class TestConfiguration:
    db_url = ...  # type: str
    driver_path = ...  # type: str


class RegistrationConfiguration:
    user_email = ...  # type: str
    user_password = ...  # type: str
    event_id = ...  # type: str


class TimeBenchmark:
    checkpoints = None  # type: Dict[str, datetime.datetime]
    checkpoint_ids = None  # type: Dict[str, int]
    checkpoint_names = None  # type: List[str]

    def __init__(self):
        self.checkpoints = dict()
        self.checkpoint_ids = dict()
        self.checkpoint_names = list()

    def start(self) -> None:
        self.checkpoint('start')

    def checkpoint(self, name: str) -> None:
        if name in self.checkpoints:
            raise ValueError('Checkpoint name already defined')

        self.checkpoint_ids[name] = len(self.checkpoint_names)
        self.checkpoint_names.append(name)
        self.checkpoints[name] = datetime.datetime.utcnow()

    def time_from_start(self, name: str) -> datetime.timedelta:
        return self.checkpoints[name] - self.checkpoints[self.checkpoint_names[0]]

    def time_from_previous(self, name: str) -> datetime.timedelta:
        current_id = self.checkpoint_ids[name]
        assert current_id > 0
        return self.checkpoints[name] - self.checkpoints[self.checkpoint_names[current_id - 1]]

    def total_time_from_start(self) -> datetime.timedelta:
        return datetime.datetime.utcnow() - self.checkpoints[self.checkpoint_names[0]]


def to_milliseconds(dt: datetime.timedelta) -> float:
    return (dt.days * 24 * 60 + dt.seconds) * 1000 + dt.microseconds / 1000


def page_processing_time(driver: WebDriver):
    time_taken_re = r"time taken: (\d:\d+:\d+\.\d+)"  # (\d+:\d+:\d+\.\d+)"  # 0:00:00.058722
    time_taken = re.compile(time_taken_re, re.S)
    matches = time_taken.search(driver.page_source)
    return matches.groups()[0]


def register_for_event(registration: RegistrationConfiguration, config: TestConfiguration) \
        -> RegistrationResult:
    # create Chrome driver
    driver_options = webdriver.ChromeOptions()
    driver_options.headless = True

    driver = webdriver.Chrome(options=driver_options, executable_path=config.driver_path)

    # create time benchmark
    benchmark = TimeBenchmark()
    benchmark.start()

    # navigate to the DB
    driver.get(config.db_url)

    benchmark.checkpoint('load')
    print("Loading took {} ms".format(to_milliseconds(benchmark.time_from_previous('load'))))

    driver.find_element_by_id('login_name').send_keys(registration.user_email)
    driver.find_element_by_id('login_password').send_keys(registration.user_password)
    driver.find_element_by_name('submitform').click()

    benchmark.checkpoint('login')
    print("Login took {} ms".format(to_milliseconds(benchmark.time_from_previous('login'))))

    # now, check that we have successfully logged in
    name = driver.find_element_by_id('displayname')
    print('Logged in as {}'.format(name.text.strip()))

    ret = RegistrationResult()
    ret.success = False
    ret.time_taken = 3 * 60 * 1000

    # go to the event page and then to registration (simulates some movement)
    driver.get("{0}/db/event/event/{1}/register".format(config.db_url, registration.event_id))
    benchmark.checkpoint('load_registration_page')

    print("Registration page title is {}, URL: {}".format(driver.title, driver.current_url))
    print("Registration page took {} ms".format(to_milliseconds(benchmark.time_from_previous('load_registration_page'))))

    ret.time_taken = to_milliseconds(benchmark.total_time_from_start())

    # try to register
    # The tricky part of registration is to find the course choice form and to fill it appropriately
    # Course choice is managed by select boxes of type "course_choice1_0"
    # hell yeah, this sounds a little complicated
    course_choice_re = r'(course_choice\d+_\d+)'
    course_choice = re.compile(course_choice_re, re.S)

    page_process_time = page_processing_time(driver)
    print("page processing took: {}".format(page_process_time))

    course_choices = set(course_choice.findall(driver.page_source))
    print("Have to fill {} course choice boxes with ids {}".format(len(course_choices), course_choices))
    blocks = set()
    choiceboxes = dict()
    for choicebox in course_choices:
        block = re.search(r'(\d+)_', choicebox).groups()[0]
        blocks.add(block)
        if not(block in choiceboxes):
            choiceboxes[block] = set()
        choiceboxes[block].add(choicebox)

    print("{} blocks: {}".format(len(blocks), blocks))

    for block in blocks:
        # fill the relevant choice boxes
        for i, choicebox in enumerate(choiceboxes[block]):
            choicebox_element = ui.Select(driver.find_element_by_name(choicebox))
            choicebox_element.select_by_index(i)

    # assume everything is already selected
    # express consent
    driver.find_element_by_id("input-checkbox-foto_consent").click()
    # send form
    driver.find_element_by_name("submitform").click()
    benchmark.checkpoint("registration_done")
    print("registration processing took: {}".format(page_processing_time(driver)))

    # find the notification block
    try:
        notification_area = driver.find_element_by_id("notifications")
        ok_sign = notification_area.find_element_by_class_name("glyphicon-ok-sign")
        print("ok sign exists? {}".format(ok_sign))
        ret.success = True
    except NoSuchElementException:
        print("registration not successful")
        pass
    ret.time_taken = to_milliseconds(benchmark.total_time_from_start())

    return ret


if __name__ == "__main__":
    # parse arguments
    option_parser = OptionParser()
    option_parser.add_option('-i', '--event-id', dest='event_id', help="The ID of the event we want to register to")
    option_parser.add_option('-e', '--user-email', dest='user_email', help="The e-mail address of the DB user")
    option_parser.add_option('-p', '--user_password', dest='user_password', help="The password of the DB user")
    option_parser.add_option('-u', '--db-url', dest='db_url', help="The URL of the database installation")
    option_parser.add_option('-x', '--executable-path', dest='driver', help="The URL of the database installation")

    logging.log(logging.INFO, "Application started")

    (options, args) = option_parser.parse_args()
    registration_config = RegistrationConfiguration()
    registration_config.user_email = options.user_email
    registration_config.user_password = options.user_password
    registration_config.event_id = options.event_id

    test_config = TestConfiguration()
    test_config.db_url = options.db_url
    test_config.driver_path = options.driver

    data_point = register_for_event(registration_config, test_config)
    print("Took {} ms".format(data_point.time_taken))
