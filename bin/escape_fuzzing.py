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
from typing import List, NamedTuple, Optional, TYPE_CHECKING

import webtest

from cdedb.frontend.application import Application
from tests.common import check_test_setup

# Custorm type definitions.
ResponseData = NamedTuple("ResponseData", [("response", webtest.TestResponse),
                                           ("url", str), ("referer", Optional[str])])
CheckReturn = NamedTuple("CheckReturn", [("errors", List[str]),
                                         ("queue", List[ResponseData])])

###################
# Some constants. #
###################

# The injected payload to check for.
XSS_PAYLOAD = "<script>abcdef</script>"
# Evidence of the payload being excaped twice.
DOUBLE_ESCAPE = "&amp;lt;"
# URL parameters to ignore when checking for unique urls.
IGNORE_URL_PARAMS = {'confirm_id'}

# Keep track of runtime data.
visited_urls = set()
posted_urls = set()


def setup(dbname: str, storage_dir: str) -> webtest.TestApp:
    check_test_setup()
    with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
        f.write(f"import pathlib\n"
                f"STORAGE_DIR = pathlib.Path('{storage_dir}')\n"
                f"CDB_DATABASE_NAME = '{dbname}'")
        f.flush()
        return Application(f.name)


def main() -> int:
    outdir = pathlib.Path('./out')

    parser = argparse.ArgumentParser(
        description="Insert XSS payload into database, then traverse all sites to make"
                    " sure it is escaped properly.")

    parser.add_argument("--dbname", "-d")
    parser.add_argument("--storage-dir", "-s", default="/tmp/cdedb-store")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    app = setup(args.dbname, args.storage_dir)
    wt_app = webtest.TestApp(app, extra_environ={
        'REMOTE_ADDR': "127.0.0.0",
        'SERVER_PROTOCOL': "HTTP/1.1",
        'wsgi.url_scheme': 'https'})

    # Exclude some forms which do some undesired behaviour
    posted_urls.clear()
    posted_urls.update({
        '/core/logout', '/core/logout/all', '/core/locale',
        '/event/event/1/lock', '/event/event/2/lock', '/event/event/3/lock'})
    visited_urls.clear()

    # login as Anton and add the start page
    start_page = wt_app.get('/')
    login_form = start_page.forms['loginform']
    login_form['username'] = "anton@example.cde"
    login_form['password'] = "secret"
    start_page = login_form.submit().maybe_follow()

    # Setup response queue.
    if TYPE_CHECKING:
        response_queue: queue.Queue[ResponseData]
    response_queue = queue.Queue()
    response_queue.put(ResponseData(start_page, '/', None))

    errors = []
    start_time = time.time()
    while True:
        try:
            response_data = response_queue.get(False)
        except queue.Empty:
            break
        e, q = check(response_data, outdir=outdir, verbose=args.verbose)
        errors.extend(e)
        for rd in q:
            response_queue.put(rd)
    end_time = time.time()
    print(f"Found {len(errors)} errors in {end_time - start_time:.3f} seconds.")
    return len(errors)


def write_next_file(outdir: pathlib.Path, data: bytes) -> None:
    if outdir.exists():
        outfile = outdir / str(len(list(outdir.iterdir())))
        with open(outfile, "wb") as f:
            f.write(data)


def check(response_data: ResponseData, *, outdir: pathlib.Path, verbose: bool = False
          ) -> CheckReturn:
    ret = CheckReturn([], [])

    def log_error(s: str) -> None:
        if verbose:
            print(s)
        ret.errors.append(s)

    def fmt(e: Exception) -> str:
        """Helper to format overly long exceptions."""
        return str(e)[:90]

    response, url, referer = response_data

    if 'html' not in response.content_type:
        return ret

    if b"cgitb" in response.body:
        log_error(f"Found a cgitb error page while following {url}")
        return ret

    # Do checks
    if verbose:
        print(f"Checking {url} ...")
    if XSS_PAYLOAD in response.text:
        log_error(f"Found unescaped payload in {url}, reached from {referer}.")
        write_next_file(outdir, response.body)
    if DOUBLE_ESCAPE in response.text:
        log_error(f"Found double escaped '<' in {url}, reached from {referer}")
        write_next_file(outdir, response.body)

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
        ret.queue.append(ResponseData(new_response, target, url))

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
        ret.queue.append(ResponseData(new_response, form.action + " [P]", url))

        # Second try: Fill in the magic token into every form field
        for field in itertools.chain.from_iterable(form.fields.values()):
            if isinstance(field, (webtest.forms.Checkbox, webtest.forms.Radio,
                                  webtest.forms.File)):
                continue
            field.force_value(XSS_PAYLOAD)
        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            log_error(f"Got error when posting to {form.action} with payload: {fmt(e)}")
            continue
        ret.queue.append(ResponseData(new_response, form.action + " [P+token]", url))

    return ret


if __name__ == "__main__":
    main()
