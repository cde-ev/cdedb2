#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import functools
from typing import Callable

from playwright.sync_api import expect, sync_playwright

from tests.common import BrowserTest, storage


def make_page(*args, headless: bool = True) -> Callable:
    """Decorator to handle playwright setup.

    This injects a `Page` object usable for testing.

    :param headless: Use headless browser to execute test.
    """
    if len(args) == 1 and callable(args[0]):
        func = args[0]

        @functools.wraps(func)
        def new_func(self, *fargs, **fkwargs):
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

    def mp(func: Callable) -> Callable:
        return make_page(func, headless=headless)
    return mp


class TestBrowser(BrowserTest):
    @storage
    @make_page
    def test_pw_vote(self, page) -> None:
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
        page.locator("#vote-cand_23").click()
        page.locator("#vote_spacer_2").click()
        page.locator("#vote-cand_26").click()
        page.locator("#vote_spacer_0").click()
        page.locator("#vote-cand_27").click()
        page.locator("#vote_spacer_4").click()
        page.locator("#vote-cand_24").click()
        page.locator("#vote_stage_5").click()
        page.get_by_role("button", name="Abstimmen").click()
        page.wait_for_url("http://localhost:5000/assembly/assembly/1/ballot/5/show")
        page.get_by_role("tab", name="Text-basierte Abstimmung").click()
        expect(page.get_by_label("Präferenzliste")).to_have_value('1=pi>i>e>0')
