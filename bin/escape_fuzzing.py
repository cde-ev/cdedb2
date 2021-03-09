#!/usr/bin/env python3

"""
This script tries to verify successful XSS mitigation, i.e. HTML escaping.

First, load manually the special sample data, which contains the magic
token "<script>abcdef</script>" in every user definable string:

    make sample-data-test
    sudo -u cdb psql -U cdb -d cdb_test -f tests/ancillary_files/clean_data.sql
    sudo -u cdb psql -U cdb -d cdb_test
        -f tests/ancillary_files/sample_data_escaping.sql

This script logs in as Anton (our testing meta admin account) and traverses all
links and forms it can find. In every response it checks for the magic string
being present without escaping and for double escaped '<' characters. We also
submit every form with the magic token entered into every form field to check if
it is returned unescaped (allowing reflected XSS).

Please note, that this will still not catch any vulnerabilities, since it does
not visits any page in any possible state with any possible request data. For
example the following things not taken into account:
  * locked events
  * form submits with some valid data and only some values set to to the payload

To avoid confusion by the error output of the cdedb, you may want to execute
this script, as follows:

   python3 -m bin.escape_fuzzing 2>/dev/null
"""
import argparse
import itertools
import pathlib
import queue
import tempfile
import time
from typing import NamedTuple, Optional, TYPE_CHECKING

import webtest

from cdedb.config import BasicConfig
from cdedb.frontend.application import Application
from tests.common import check_test_setup

_BASICCONF = BasicConfig()

outdir = pathlib.Path('./out')

parser = argparse.ArgumentParser(
    description="Insert XSS payload into database, then traverse all sites to make"
                " sure it is escaped properly.")

parser.add_argument("--dbname", "-d")
parser.add_argument("--verbose", "-v", action="store_true")

args = parser.parse_args()


def setup(dbname: str) -> webtest.TestApp:
    check_test_setup()
    config = {"CDB_DATABASE_NAME": dbname}
    with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
        for k, v in config.items():
            f.write(f"{k} = {v!r}\n")
        f.flush()
        return Application(f.name)


app = setup(args.dbname)
wt_app = webtest.TestApp(app, extra_environ={
    'REMOTE_ADDR': "127.0.0.0",
    'SERVER_PROTOCOL': "HTTP/1.1",
    'wsgi.url_scheme': 'https'})

visited_urls = set()
posted_urls = set()
ResponseData = NamedTuple("ResponseData", [("response", webtest.TestResponse),
                                           ("url", str), ("referer", Optional[str])])
if TYPE_CHECKING:
    response_queue: queue.Queue[ResponseData]
response_queue = queue.Queue()

# URL parameters to ignore when checking for unique urls
IGNORE_URL_PARAMS = ('confirm_id',)

# exclude some forms which do some undesired behaviour
posted_urls.add('/core/logout')
posted_urls.add('/core/logout/all')
posted_urls.add('/core/locale')
posted_urls.add('/event/event/1/lock')
posted_urls.add('/event/event/2/lock')
posted_urls.add('/event/event/3/lock')

# login as Anton and add the start page
start_page = wt_app.get('/')
login_form = start_page.forms['loginform']
login_form['username'] = "anton@example.cde"
login_form['password'] = "secret"
start_page = login_form.submit()
start_page = start_page.maybe_follow()
response_queue.put(ResponseData(start_page, '/', None))

errors = []

payload = "<script>abcdef</script>"
double_escape = "&amp;lt;"


def log_error(s: str) -> None:
    print(s)
    errors.append(s)


def fmt(e: Exception) -> str:
    """Helper to format overly long exceptions."""
    return str(e)[:90]


start_time = time.time()
while True:
    try:
        response, url, referer = response_queue.get(False)
    except queue.Empty:
        break

    if 'html' not in response.content_type:
        continue

    if b"cgitb" in response.body:
        log_error(f"Found a cgitb error page while following {url}")
        continue

    # Do checks
    if args.verbose:
        print(f"Checking {url} ...")
    if payload in response.text:
        log_error(f"Found unescaped payload in {url}, reached from {referer}.")
        if outdir.exists():
            outfile = outdir / str(len(list(outdir.iterdir())))
            with open(outfile, 'wb') as out:
                out.write(response.body)
    if double_escape in response.text:
        log_error(f"Found double escaped '<' in {url}, reached from {referer}")
        if outdir.exists():
            outfile = outdir / str(len(list(outdir.iterdir())))
            with open(outfile, 'wb') as out:
                out.write(response.body)

    # Follow all links to unvisited page urls
    for link_element in response.html.find_all('a'):
        if 'href' not in link_element.attrs:
            continue
        target = str(link_element.attrs['href'])
        if target.startswith(('http://', 'https://', 'mailto:', 'tel:', '/doc/',
                              '/static/')):
            continue
        if target.startswith('/db'):
            target = target[3:]
        target = target.split('#')[0]

        # Strip ambiguous parameters from the url to check if it has already
        # been visited
        tmp = target.split('?', maxsplit=1)
        if len(tmp) == 1:
            unique_target = tmp[0]
        else:
            unique_target = tmp[0] + "?" + "&".join(
                p for p in tmp[1].split('&')
                if p.split('=')[0] not in IGNORE_URL_PARAMS)

        if not target or unique_target in visited_urls:
            continue

        try:
            new_response = response.goto(target)
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            log_error(f"Got error when following {target} from {url}: {fmt(e)}")
            continue
        visited_urls.add(unique_target)
        response_queue.put(ResponseData(new_response, target, url))

    # Submit all forms to unvisited action urls
    for form in response.forms.values():
        if form.action in posted_urls:
            continue

        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            log_error(f"Got error when posting to {form.action}: {fmt(e)}")
            continue
        posted_urls.add(form.action)
        response_queue.put(ResponseData(new_response, form.action + " [P]", url), True)

        # Second try: Fill in the magic token into every form field
        for field in itertools.chain.from_iterable(form.fields.values()):
            if isinstance(field, (webtest.forms.Checkbox, webtest.forms.Radio,
                                  webtest.forms.File)):
                continue
            field.force_value(payload)
        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            log_error(f"Got error when posting to {form.action} with payload: {fmt(e)}")
            continue
        response_queue.put(ResponseData(new_response, form.action + " [P+token]", url))

end_time = time.time()
print(f"Found {len(errors)} errors in {end_time - start_time:.3f} seconds.")
