#!/usr/bin/env python3

"""
This script tries to verify successful XSS mitigation, i.e. HTML escaping.

It has some requirements, most importantly the storage directory to be
existing and the environment variable CDEDB_TEST to be truthy. Thus, it is not
recommended to run it directly, but invoke it via `make xss-check` or
`bin/check.py --xss-check`. See also the documentation.

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
"""
import argparse
import itertools
import os
import pathlib
import queue
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Collection, List, NamedTuple, Optional, Set

import webtest
from bin.test_runner_helpers import check_test_setup

from cdedb.frontend.application import Application

# Custom type definitions.
ResponseData = NamedTuple("ResponseData", [("response", webtest.TestResponse),
                                           ("url", str), ("referer", Optional[str])])
CheckReturn = NamedTuple("CheckReturn", [("errors", List[str]),
                                         ("queue", List[ResponseData])])

# Keep track of runtime data.
visited_urls: Set[str] = set()
posted_urls: Set[str] = set()


def setup(dbname: str, storage_dir: str) -> webtest.TestApp:
    """Prepare the application."""
    check_test_setup()
    with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
        f.write(f"import pathlib\n"
                f"STORAGE_DIR = pathlib.Path('{storage_dir}')\n"
                f"CDB_DATABASE_NAME = '{dbname}'")
        f.flush()
        os.environ["CDEDB_CONFIGPATH"] = f.name
        return Application()


def main() -> int:
    """Iterate over all visible page links and check them for the xss payload."""
    parser = argparse.ArgumentParser(
        description="Insert XSS payload into database, then traverse all sites to make"
                    " sure it is escaped properly.")

    general = parser.add_argument_group("General options")
    general.add_argument("--dbname", "-d")
    general.add_argument("--storage-dir", "-s", default="/tmp/cdedb-store")
    general.add_argument("--outdir", "-o", default="./out")

    config = parser.add_argument_group("Ccnfiguration")
    config.add_argument("--verbose", "-v", action="store_true")
    config.add_argument("--payload", "-p", default="<script>abcdef</script>")
    config.add_argument("--secondary", "-sp", nargs='*',
                        default=["&amp;lt;", "&amp;gt;"])

    args = parser.parse_args()

    app = setup(args.dbname, args.storage_dir)
    wt_app = webtest.TestApp(app, extra_environ={
        'REMOTE_ADDR': "127.0.0.0",
        'SERVER_PROTOCOL': "HTTP/1.1",
        'wsgi.url_scheme': 'https'})
    outdir = pathlib.Path(args.outdir)
    if not outdir.exists():
        print(f"Target directory {outdir!r} doesn't exist."
              f" Nothing will be written to file.")

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
        e, q = check(response_data, outdir=outdir, verbose=args.verbose,
                     payload=args.payload, secondary_payloads=args.secondary)
        errors.extend(e)
        for rd in q:
            response_queue.put(rd)
    end_time = time.time()
    print(f"Found {len(errors)} errors in {end_time - start_time:.3f} seconds.")
    if errors:
        write_next_file(outdir, "\n".join(errors).encode(), filename="summary")
    return len(errors)


def write_next_file(outdir: Optional[pathlib.Path], data: bytes, filename: str = None
                    ) -> None:
    """Write data to the next available numbered file in the target directory."""
    if outdir and outdir.exists():
        if filename is None:
            filename = str(len(list(outdir.iterdir())))
        outfile = outdir / filename
        with open(outfile, "wb") as f:
            f.write(data)


def check(response_data: ResponseData, *, payload: str,
          secondary_payloads: Collection[str] = (), outdir: pathlib.Path = None,
          verbose: bool = False) -> CheckReturn:
    """Check a single response for presence of the payload.

    :param payload: The payload that we try to inject everywhere we can. For optimal
        coverage, you should prepare the database beforehand in such a way, that the
        same payload has already been injecetd into every possible column.
    :param secondary_payloads: If given, also check that all these strings are not
        present anywhere, but do not try to inject this. This is useful to check that
        the injected payload is excaped only once.
    :param outdir: If given, write encountered errors into subsequent files inside this
        directory.
    :param verbose: If True, print encountered errors to console.

    :returns: A tuple of two lists, with the first containing string represantations
        of encountered errors error strings and the second containing new response data
        to check later.
    """
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
    if payload in response.text:
        log_error(f"Found unescaped payload in {url}, reached from {referer}.")
        write_next_file(outdir, response.body)
    for secondary_payload in secondary_payloads:
        if secondary_payload in response.text:
            log_error(f"Found secondary payload in {url}, reached from {referer}")
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
                if p.split('=')[0] not in {'confirm_id'})

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
            field.force_value(payload)
        try:
            new_response = form.submit()
            new_response = new_response.maybe_follow()
        except webtest.app.AppError as e:
            log_error(f"Got error when posting to {form.action} with payload: {fmt(e)}")
            continue
        ret.queue.append(ResponseData(new_response, form.action + " [P+token]", url))

    return ret


if __name__ == "__main__":
    ret = main()
    sys.exit(ret)
