#!/usr/bin/env python3
# author: Dimitri Scheftelowitsch
# coding: utf-8
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
import typing

"""
This script is designed for creating of LOTS AND LOTS of members

This is basically Step 1 of
"""

# Assume that we create 10K members over 200 academies. We might add some number of courses later to refine the model,
# but this is not that important for now.
num_members = 10
num_academies = 10
num_courses_per_academy = 25

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

    def make_course(course_id: int):
        course_format = '"{number}";"{title}";"{description}"'
        return course_format.format(number=course_id,
                                    title="course {}".format(course_id),
                                    description="Sample course {} description".format(course_id))

    courses = [make_course(course_id) for course_id in range(num_courses_per_academy)]
    driver.find_element_by_id("input-textarea-courses").send_keys("\n".join(courses))
    driver.find_element_by_name("submitform").click()


def create_user(driver: WebDriver, user_id: int) -> str:
    user_format = '"{academy}";"{course}";"{surname}";"{name}";"";"";"";"2";"";"{street}";"{zip}";"{city}";"Deutschland";"{phone}";"{mobile}";"{email}";"{birthday}"'
    return user_format.format(academy="ta{:03}".format(user_id % num_academies),
                              course="course {}".format(user_id % num_courses_per_academy),
                              surname="Testson",
                              name="Primarchus{}".format(user_id),
                              street="Im Test {}".format(user_id),
                              zip="44225",
                              city="Dortmund",
                              phone="030456790",
                              mobile="01635555555",
                              email="primarchus{}@example.cde".format(user_id),
                              birthday="2000-01-17")


if __name__ == "__main__":
    admin_username = "anton@example.cde"
    admin_password = "secret"

    driver_options = webdriver.ChromeOptions()
    driver_options.headless = False

    driver = webdriver.Chrome(options=driver_options, executable_path="/usr/lib64/chromium/chromedriver")
    driver.get(db_url)
    driver.find_element_by_id('login_name').send_keys(admin_username)
    driver.find_element_by_id('login_password').send_keys(admin_password)
    driver.find_element_by_name('submitform').click()

    # create former academies
    #create_academy(driver, 65536)
    for academy_id in range(num_academies):
        create_academy(driver, academy_id)

    driver.get("{}cde/admission".format(db_url))
    # do not send emails
    driver.find_element_by_id("input-checkbox-sendmail").click()
    driver.find_element_by_id("input-data").send_keys("\n".join([create_user(driver, user_id)
                                                                 for user_id in range(num_members)]))

    driver.find_element_by_name("submitform").click()