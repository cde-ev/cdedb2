#!/usr/bin/env python3
# author: Dimitri Scheftelowitsch
# coding: utf-8
import typing
from optparse import OptionParser

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webdriver import WebDriver

"""
This script is designed for creating of LOTS AND LOTS of members

This is basically Step 1 of load testing
"""

# Assume that we create 10K members over 200 academies. We might add some number of courses later to refine the model,
# but this is not that important for now.
num_members = 10000
num_academies = 100
num_courses_per_academy = 25
num_academies_per_member = 20

# A global db_url (yes, that is ugly, but for now ot should work, right?
db_url = "https://localhost:20443/db/"


def create_academy(driver: WebDriver, academy_id: int):
    driver.get("{}cde/past/event/create".format(db_url))
    driver.find_element_by_id("input-text-title").send_keys("Testakademie {}".format(academy_id))
    driver.find_element_by_id("input-text-shortname").send_keys("ta{:03}".format(academy_id))
    driver.find_element_by_id("input-textarea-description").send_keys("Eine Akademie, die lediglich zu Testzwecken angelegt wurde")
    date_field = driver.find_element_by_id("input-text-tempus")
    date_field.click()
    date_field.send_keys("17062006")

    def make_course(course_id: int) -> str:
        course_format = '"{number}";"{title}";"{description}"'
        return course_format.format(number=course_id,
                                    title="course {:03}".format(course_id),
                                    description="Sample course {} description".format(course_id))

    courses = [make_course(course_id) for course_id in range(num_courses_per_academy)]
    driver.find_element_by_id("input-textarea-courses").send_keys("\n".join(courses))
    driver.find_element_by_name("submitform").click()


def create_academy_sql(academy_id: int) -> str:
    event_request = "INSERT INTO past_event.events" \
                    "(title, shortname, institution, description, tempus) " \
                    "VALUES" \
                    "('{title}', '{shortname}', 1, '{description}', '2006-06-17');"
    course_request = "INSERT INTO past_event.courses" \
                     "(pevent_id, nr, title, description) " \
                     "VALUES" \
                     "({academy_sql_id}, '{number}', '{title}', '{description}');"

    formatted_courses = [course_request.format(academy_sql_id=academy_id+1,
                                               number=i,
                                               title="course {:03}".format(i),
                                               description="Description {}".format(i))
                         for i in range(num_courses_per_academy)]
    formatted_event = event_request.format(title="Testakademie {}".format(academy_id),
                                           shortname="ta{:03}".format(academy_id),
                                           description="Eine Akademie, um sie alle zu vereinen")
    sql = "{event}\n{courses}".format(event=formatted_event,
                                      courses="\n".join(formatted_courses))
    return sql


def user_email(user_id: int) -> str:
    return "steve{}@example.cde".format(user_id)


def create_user(driver: WebDriver, user_id: int) -> str:
    user_format = '"{academy}";"{course}";"{surname}";"{name}";"";"";"";"2";"";"{street}";"{zip}";"{city}";"Deutschland";"{phone}";"{mobile}";"{email}";"{birthday}"'
    return user_format.format(academy="ta{:03}".format(user_id % num_academies),
                              course="course {:03}".format(user_id % num_courses_per_academy),
                              surname="Testson",
                              name="Steve {}".format(user_id),
                              street="Im Test {}".format(user_id),
                              zip="44225",
                              city="Dortmund",
                              phone="030456790",
                              mobile="01635555555",
                              email=user_email(user_id),
                              birthday="2000-01-17")


def create_user_sql(user_id: int) -> str:
    pass


if __name__ == "__main__":
    option_parser = OptionParser()
    option_parser.add_option('-e', '--events', action='store_true', dest='generate_events',
                             help="Whether to generate events")
    option_parser.add_option('-q', '--events-sql', action='store_true', dest='generate_events_sql',
                             help="Whether to generate event SQL requests")
    option_parser.add_option('-u', '--users', action='store_true', dest='generate_users',
                             help="Whether to generate users")
    option_parser.add_option('-a', '--add-users', action='store_true', dest='add_users',
                             help="Whether to add users to events")
    (options, args) = option_parser.parse_args()

    admin_username = "anton@example.cde"
    admin_password = "secret"

    if options.generate_events_sql:
        print("\n".join([create_academy_sql(i) for i in range(num_academies)]))

    driver_options = webdriver.ChromeOptions()
    driver_options.headless = False

    driver = webdriver.Chrome(options=driver_options)
    driver.get(db_url)
    driver.find_element_by_id('login_name').send_keys(admin_username)
    driver.find_element_by_id('login_password').send_keys(admin_password)
    driver.find_element_by_name('submitform').click()

    #raise Exception
    # create former academies
    if options.generate_events:
        for academy_id in range(num_academies):
            create_academy(driver, academy_id)

    if options.generate_users:
        safe_input_length = 20
        slice_beginnings = range(0, num_members, safe_input_length)
        full_user_range = range(num_members)

        for slice_beginning in slice_beginnings:
            safe_range = full_user_range[slice_beginning:slice_beginning+safe_input_length]
            user_data = "\n".join([create_user(driver, user_id) for user_id in safe_range])

            driver.get("{}cde/admission".format(db_url))
            # do not send emails
            driver.find_element_by_id("input-checkbox-sendmail").click()
            # driver.find_element_by_id("input-data").send_keys(user_data)
            input_field = driver.find_element_by_id("input-data")
            driver.execute_script("arguments[0].value = arguments[1].toString()", input_field, user_data)

            driver.find_element_by_name("submitform").click()

            button = driver.find_element_by_name("submitform")
            ActionChains(driver).move_to_element(button).click(button).perform()

    # now add each participant to an academy. We assume that this test will happen on a pristine DB, hence, let's
    # look what the event IDs are.

    if options.add_users:
        def get_test_academy_db_id(id: int) -> int:
            return id + 2

        for member in range(num_members):
            start_academy = member % num_academies + 1
            end_academy = start_academy + num_academies_per_member
            for academy in range(start_academy, end_academy):
                academy_id = get_test_academy_db_id(academy % num_academies)
                driver.get("{url}cde/past/event/{id}/show".format(url=db_url, id=academy_id))
                driver.find_element_by_id("input-add-participant-selectized").send_keys(user_email(member))
                driver.find_element_by_name("submitform").click()
