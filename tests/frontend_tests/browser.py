#!/usr/bin/env python3
# pylint: disable=missing-module-docstring,no-self-use

import functools
from typing import Callable

from playwright.sync_api import Page, expect, sync_playwright

from tests.common import BrowserTest, storage


def make_page(*args, headless: bool = True  # type: ignore[no-untyped-def]
              ) -> Callable:  # type: ignore[type-arg]
    """Decorator to handle playwright setup.

    This injects a `Page` object usable for testing.

    :param headless: Use headless browser to execute test.
    """
    if len(args) == 1 and callable(args[0]):
        func = args[0]

        @functools.wraps(func)
        def new_func(self, *fargs, **fkwargs):  # type: ignore[no-untyped-def]
            if 'page' in fkwargs:
                raise ValueError('Argument `page` already present.')
            with sync_playwright() as pw:
                # FIXME webkit fails to log in mysteriously
                # FIXME firefox fails to deterministically reproduce result
                for name in ['chromium']:
                    browser = getattr(pw, name).launch(headless=headless)
                    page = browser.new_page(locale='de-DE')
                    fkwargs['page'] = page
                    with self.subTest(browser=name):
                        func(self, *fargs, **fkwargs)
                    browser.close()
        return new_func

    if len(args) > 0:
        raise ValueError('Unexpected positional argument.')

    def mp(func: Callable) -> Callable:  # type: ignore[type-arg]
        return make_page(func, headless=headless)
    return mp


class TestBrowser(BrowserTest):
    """Full simulation tests.

    Each test should contain a short description so it can be reproduced
    without reverse engineering the code.

    To start a test generation session execute
    playwright codegen https://localhost --ignore-https-errors
    in a shell in a graphical environment. The result has to be postprocessed
    by replacing `https://localhost/db/` with `http://localhost:5000/`.
    """
    @storage
    @make_page
    def test_pw_interactive_vote(self, page: Page) -> None:
        """Cast a vote with the interactive voting facility.

        Ensure that all modalities are covered (add a tier at the end / in the
        middle, move a candidate into an existing tier, empty a tier, ...).
        """
        page.goto("http://localhost:5000/")
        page.get_by_label("E-Mail").fill("anton@example.cde")
        page.get_by_label("Passwort").fill("secret")
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url("http://localhost:5000/")
        page.get_by_role("link", name="Versammlungen").click()
        page.wait_for_url("http://localhost:5000/assembly/")
        page.get_by_role("link", name="Internationaler Kongress").click()
        page.wait_for_url("http://localhost:5000/assembly/assembly/1/show")
        page.get_by_role("link", name="Abstimmungen").click()
        page.wait_for_url("http://localhost:5000/assembly/assembly/1/ballot/list")
        page.get_by_role("link", name="Lieblingszahl").click()
        page.wait_for_url("http://localhost:5000/assembly/assembly/1/ballot/5/show")
        page.get_by_role("tab", name="Interaktive Abstimmung").click()

        page.locator("#vote-cand_25").click()
        page.locator("#vote_spacer_0").click()
        page.locator("#vote-cand_23").click()
        page.locator("#vote_spacer_4").click()
        page.locator("#vote-cand_26").click()
        page.locator("#vote_spacer_2").click()
        page.locator("#vote-cand_24").click()
        page.locator("#vote_stage_5").click()
        page.locator("#vote-cand_27").click()
        page.locator("#vote_stage_3").click()
        page.locator("#vote-cand_26").click()
        page.locator("#vote_spacer_4").click()

        page.get_by_role("button", name="Abstimmen").click()
        page.wait_for_url("http://localhost:5000/assembly/assembly/1/ballot/5/show")
        page.get_by_role("tab", name="Text-basierte Abstimmung").click()
        expect(page.get_by_label("Präferenzliste")).to_have_value('i=0>1>e=pi')
