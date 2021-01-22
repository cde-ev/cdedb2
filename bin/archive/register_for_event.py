#!/usr/bin/env python3

"""
This Python script shall test if registration for an event in the new cdedb is successful, and if so, how much time it
took. The main idea is to use Selenium to emulate browser actions and then to performance-test page loading.
"""

import datetime
import logging
import multiprocessing as mp
import re
from optparse import OptionParser
from typing import Dict, List, Tuple, Union

import pandas as pd
import selenium.webdriver.support.ui as ui
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver


class RegistrationResult:
    success = False  # type: bool
    time_taken = 60 * 1000  # type: float
    benchmark = None  # type: TimeBenchmark


class TestConfiguration:
    db_url = ...  # type: str
    driver_path = None  # type: str


class RegistrationConfiguration:
    user_email = ...  # type: str
    user_password = ...  # type: str
    event_id = ...  # type: str
    dry_run = True


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

    driver_args = {'options': driver_options}
    if config.driver_path is not None:
        driver_args['executable_path'] = config.driver_path

    driver = webdriver.Chrome(**driver_args)

    ret = RegistrationResult()
    ret.success = False
    ret.time_taken = 3 * 60 * 1000

    # create time benchmark
    benchmark = TimeBenchmark()
    benchmark.start()

    # navigate to the DB
    driver.get(config.db_url)

    benchmark.checkpoint('load')
    # print("Loading took {} ms".format(to_milliseconds(benchmark.time_from_previous('load'))))

    driver.find_element_by_id('login_name').send_keys(registration.user_email)
    driver.find_element_by_id('login_password').send_keys(registration.user_password)
    driver.find_element_by_name('submitform').click()

    benchmark.checkpoint('login')
    # print("Login took {} ms".format(to_milliseconds(benchmark.time_from_previous('login'))))

    # now, check that we have successfully logged in
    try:
        name = driver.find_element_by_id('displayname')
        # print('Logged in as {}'.format(name.text.strip()))
    except NoSuchElementException:
        print("Error at login for {0}, after {1} ms".format(
            registration.user_email,
            to_milliseconds(benchmark.time_from_previous('login'))))
        ret.benchmark = benchmark
        return ret

    # go to the event page and then to registration (simulates some movement)
    driver.get("{0}/db/event/event/{1}/register".format(config.db_url, registration.event_id))
    benchmark.checkpoint('load_registration_page')

    # print("Registration page title is {}, URL: {}".format(driver.title, driver.current_url))
    # print("Registration page took {} ms".format(to_milliseconds(benchmark.time_from_previous('load_registration_page'))))

    ret.time_taken = to_milliseconds(benchmark.total_time_from_start())

    # try to register
    # The tricky part of registration is to find the course choice form and to fill it appropriately
    # Course choice is managed by select boxes of type "course_choice1_0"
    # hell yeah, this sounds a little complicated
    course_choice_re = r'(course_choice\d+_\d+)'
    course_choice = re.compile(course_choice_re, re.S)

    # page_process_time = page_processing_time(driver)
    # print("page processing ({1}) took: {0}".format(page_process_time, registration.user_email))

    course_choices = set(course_choice.findall(driver.page_source))
    # print("Have to fill {} course choice boxes with ids {}".format(len(course_choices), course_choices))
    blocks = set()
    choiceboxes = dict()
    for choicebox in course_choices:
        block = re.search(r'(\d+)_', choicebox).groups()[0]
        blocks.add(block)
        if not(block in choiceboxes):
            choiceboxes[block] = set()
        choiceboxes[block].add(choicebox)

    # print("{} blocks: {}".format(len(blocks), blocks))

    for block in blocks:
        # fill the relevant choice boxes
        for i, choicebox in enumerate(choiceboxes[block]):
            choicebox_element = ui.Select(driver.find_element_by_name(choicebox))
            choicebox_element.select_by_index(i)

    # assume everything is already selected
    # send form
    if not registration.dry_run:
        driver.find_element_by_name("submitform").click()
        benchmark.checkpoint("registration_done")

        # find the notification block
        try:
            # print("registration processing took: {}".format(page_processing_time(driver)))
            notification_area = driver.find_element_by_id("notifications")
            ok_sign = notification_area.find_element_by_class_name("check-circle")
            print("ok sign exists? {}".format(ok_sign))
            ret.success = True
        except NoSuchElementException:
            print("registration not successful for {}".format(registration.user_email))
        except AttributeError:
            print("registration page not loaded for {}".format(registration.user_email))
    else:
        ret.success = True

    ret.time_taken = to_milliseconds(benchmark.total_time_from_start())
    ret.benchmark = benchmark

    driver.close()

    return ret


def register_steve(input_args: Tuple[int, RegistrationConfiguration, TestConfiguration]) -> RegistrationResult:
    steve_id, reg_config, test_config = input_args
    reg_config.user_password = "secret"
    reg_config.user_email = "steve{}@example.cde".format(steve_id)

    return register_for_event(reg_config, test_config)


def try_register_steves(reg_config: RegistrationConfiguration, test_config: TestConfiguration,
                        num_of_steves: int, num_processes: int) -> pd.DataFrame:

    def to_dict(data: RegistrationResult) -> Dict[str, Union[float, bool]]:
        result = {
            'total': data.time_taken,
            'success': data.success
        }

        for name in data.benchmark.checkpoint_names:
            if name != 'start':
                result[name] = to_milliseconds(data.benchmark.time_from_previous(name))

        return result

    tracker = TimeBenchmark()
    tracker.start()

    with mp.Pool(num_processes) as p:
        input_data = map(lambda steve_id: (steve_id, reg_config, test_config), range(num_of_steves))
        data = p.map(register_steve, input_data)

        tracker.checkpoint("done")
        milliseconds = to_milliseconds(tracker.time_from_previous("done"))
        rps = num_of_steves / (milliseconds / 1000.0)

        print("Served {registrations} registration requests in {time} ms, averaging {rps} rps".format(
            registrations=num_of_steves,
            time=milliseconds,
            rps=rps))
        return pd.DataFrame(list(map(to_dict, data)))


if __name__ == "__main__":
    # parse arguments
    option_parser = OptionParser()
    option_parser.add_option('-i', '--event-id', dest='event_id', help="The ID of the event we want to register to")
    option_parser.add_option('-e', '--user-email', dest='user_email', help="The e-mail address of the DB user")
    option_parser.add_option('-p', '--user_password', dest='user_password', help="The password of the DB user")
    option_parser.add_option('-u', '--db-url', dest='db_url', help="The URL of the database installation")
    option_parser.add_option('-x', '--executable-path', dest='driver', help="The URL of the database installation")
    option_parser.add_option('-f', '--force', action='store_true', dest='force', help="Register for real")
    option_parser.add_option('-m', '--mass-registration', dest='mass_registration',
                             help='Number of users to simulate')
    option_parser.add_option('-t', '--threads', dest='threads',
                             help='Number of threads to use')

    logging.log(logging.INFO, "Application started")

    (options, args) = option_parser.parse_args()
    test_config = TestConfiguration()
    test_config.db_url = options.db_url
    if options.driver is not None:
        test_config.driver_path = options.driver

    registration_config = RegistrationConfiguration()
    registration_config.event_id = options.event_id
    registration_config.dry_run = not options.force

    if options.mass_registration is not None:
        data_frame = try_register_steves(registration_config, test_config,
                                         int(options.mass_registration), int(options.threads))
        data_frame.to_csv("registration.csv")
    else:
        registration_config.user_email = options.user_email
        registration_config.user_password = options.user_password

        data_point = register_for_event(registration_config, test_config)
        print("Took {} ms".format(data_point.time_taken))
