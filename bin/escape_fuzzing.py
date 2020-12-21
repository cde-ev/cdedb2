#!/usr/bin/env python3

"""
This script tries to verify successful XSS mitigation, i.e. HTML escaping.

First, load manually the special sample data, which contains the magic
token "<script>abcdef</script>" in every user definable string:

    make sample-data-test
    sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/clean_data.sql
    sudo -u cdb psql -U cdb -d cdb_test -f test/ancillary_files/sample_data_escaping.sql

This script logs in as Anton (our testing meta admin account) and traverses all
links and forms it can find. In every response it checks for the magic string
being present without escaping and for double escaped '<' characters. We also
submit every form with the magic token entered into every form field to check if
it is returned unescaped (allowing reflected XSS).

Please note, that this will still not catch any vulnerabilities, since it does
not visits any page in any possible state with any possible request data. For
example the following things not taken into account:
  * locked events
  * form submits with some valid data and only some values set to to the
    marker string

To avoid confusion by the error output of the cdedb, you may want to execute
this script, as follows:

   python3 -m bin.escape_fuzzing 2>/dev/null
"""
import itertools
import logging
import os
import pathlib
import queue

import webtest

os.environ['CDEDB_TEST'] = "True"

from cdedb.config import BasicConfig
from cdedb.frontend.application import Application

_BASICCONF = BasicConfig()

outdir = pathlib.Path('./out')

app = Application()
wt_app = webtest.TestApp(app, extra_environ={
    'REMOTE_ADDR': "127.0.0.0",
    'SERVER_PROTOCOL': "HTTP/1.1",
    'wsgi.url_scheme': 'https'})

visited_urls = set()
posted_urls = set()
response_queue = queue.Queue()

# URL parameters to ignore when checking for unique urls
IGNORE_URL_PARAMS = ('confirm_id',)

# exclude some forms which do some undesired behaviour
posted_urls.add('/core/logout')
posted_urls.add('/core/locale')
posted_urls.add('/event/event/1/lock')
posted_urls.add('/event/event/2/lock')

# login as Anton and add the start page
start_page = wt_app.get('/')
login_form = start_page.forms['loginform']
login_form['username'] = "anton@example.cde"
login_form['password'] = "secret"
start_page = login_form.submit()
start_page = start_page.maybe_follow()
response_queue.put((start_page, '/', None))


while True:
    try:
        response, url, referer = response_queue.get(False)
    except queue.Empty:
        break

    if 'html' not in response.content_type:
        continue

    if b"cgitb" in response.body:
        print("Found a cgitb error page while following {}".format(url))
        continue

    # Do checks
    # print("Checking {} ...".format(url))
    if "<script>abcdef" in response.text:
        print(">>> Found unescaped marker <script> in {}, reached from {}"
              .format(url, referer))
        if outdir.exists():
            outfile = outdir / str(len(list(outdir.iterdir())))
            with open(outfile, 'wb') as f:
                f.write(response.body)
    if "&amp;lt;" in response.text:
        print(">>> Found double escaped '<' in {}, reached from {}"
              .format(url, referer))
        if outdir.exists():
            outfile = outdir / str(len(list(outdir.iterdir())))
            with open(outfile, 'wb') as f:
                f.write(response.body)

    # Follow all links to unvisited page urls
    for link_element in response.html.find_all('a'):
        if 'href' not in link_element.attrs:
            continue
        target = str(link_element.attrs['href'])
        if target.startswith(('http://', 'https://', 'mailto:', '/doc/')):
            continue
        target = target.split('#')[0]

        # Strip ambiguous parameters from the url to check if it has already
        # been visited
        l = target.split('?', maxsplit=1)
        if len(l) == 1:
            unique_target = l[0]
        else:
            unique_target = l[0] + "?" + "&".join(
                p for p in l[1].split('&')
                if p.split('=')[0] not in IGNORE_URL_PARAMS)

        if not target or unique_target in visited_urls:
            continue

        try:
            new_response = response.goto(target)
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            print("Got error when following {}: {}".format(target, str(e)[:70]))
            continue
        visited_urls.add(unique_target)
        response_queue.put((new_response, target, url), True)

    # Submit all forms to unvisited action urls
    for form in response.forms.values():
        if form.action in posted_urls:
            continue

        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            print("Got error when posting to {}: {}"
                  .format(form.action, str(e)[:70]))
            continue
        posted_urls.add(form.action)
        response_queue.put((new_response, form.action + " [P]", url), True)

        # Second try: Fill in the magic token into every form field
        for field in itertools.chain.from_iterable(form.fields.values()):
            if isinstance(field, (webtest.forms.Checkbox, webtest.forms.Radio,
                                  webtest.forms.File)):
                continue
            field.force_value("<script>abcdef</script>")
        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            print("Got error when posting to {} with marker data: {}"
                  .format(form.action, str(e)[:70]))
            continue
        response_queue.put((new_response, form.action + " [P+token]", url),
                           True)
