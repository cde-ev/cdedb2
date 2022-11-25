#!/usr/bin/env python3
# pylint: disable=missing-module-docstring,no-self-use

import functools
from typing import Callable

from playwright.sync_api import Page, expect, sync_playwright

from tests.common import BrowserTest, event_keeper, storage


def make_page(*args, headless: bool = True,  # type: ignore[no-untyped-def]
              timeout: float = 5000) -> Callable:  # type: ignore[type-arg]
    """Decorator to handle playwright setup.

    This injects a `Page` object usable for testing.

    :param headless: Use headless browser to execute test.
    :param timeout: Default timeout in milliseconds.
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
                    page.set_default_timeout(timeout)
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
    def test_js_interactive_vote(self, page: Page) -> None:
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

    @make_page
    def test_js_selectize_persona(self, page: Page) -> None:
        """Search for a persona via the admin showuser functionality."""
        page.goto("http://localhost:5000/")
        page.get_by_label("E-Mail").fill("anton@example.cde")
        page.get_by_label("Passwort").fill("secret")
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url("http://localhost:5000/")

        page.get_by_role("button", name="Benutzer-Administration").click()
        page.wait_for_url("http://localhost:5000/")
        page.locator(".selectize-input").click()
        page.get_by_placeholder("CdEDB-ID, Name oder E-Mail").type("emi")
        page.get_by_text("Emilia E. EventisDB-5-1 • emilia@example.cde").click()
        page.wait_for_url("http://localhost:5000/core/persona/5/show?*")

        expect(page.locator("#content--admin-notes")).to_have_text(
            ("War früher mal berühmt, hat deswegen ihren Nachnamen geändert."))

    @event_keeper
    @make_page
    def test_js_dynamicrow(self, page: Page) -> None:
        """Configure custom event fields.

        Test addition and deletion and deletion of a not-yet-added field.
        """
        page.goto("http://localhost:5000/")
        page.get_by_label("E-Mail").fill("anton@example.cde")
        page.get_by_label("Passwort").fill("secret")
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url("http://localhost:5000/")

        page.get_by_role("link", name="Veranstaltungen").click()
        page.wait_for_url("http://localhost:5000/event/")
        page.get_by_role("link", name="Große Testakademie 2222").click()
        page.wait_for_url("http://localhost:5000/event/event/1/show")
        page.get_by_role("button", name="Orga-Schaltflächen").click()
        page.wait_for_url("http://localhost:5000/event/event/1/show")
        page.get_by_role("link", name="Datenfelder konfigurieren").click()
        page.wait_for_url("http://localhost:5000/event/event/1/field/summary")

        page.get_by_role("button", name="Feld hinzufügen").click()
        page.locator('input[name="title_-1"]').click()
        page.locator('input[name="title_-1"]').fill("Favorit")
        page.locator('input[name="field_name_-1"]').click()
        page.locator('input[name="field_name_-1"]').fill("favorit")

        page.locator("#dynamicrow-delete-button-0").click()

        page.get_by_role("button", name="Feld hinzufügen").click()
        page.locator('input[name="title_-2"]').click()
        page.locator('input[name="title_-2"]').fill("Lieblingsheld")
        page.locator('input[name="field_name_-2"]').click()
        page.locator('input[name="field_name_-2"]').fill("held")

        page.locator("#dynamicrow-delete-button-8").click()

        page.get_by_role("button", name="Speichern").click()
        page.wait_for_url("http://localhost:5000/event/event/1/field/summary")

        expect(page.locator('input[name="title_1001"]')).to_have_value('Lieblingsheld')
        expect(page.locator('input[name="field_name_1001"]')).to_have_value('held')
        expect(page.locator('#content')).not_to_contain_text('Favorit')
        expect(page.locator('#content')).not_to_contain_text('favorit')
        expect(page.locator('#content')).not_to_contain_text('Anzahl Großbuchstaben')
        expect(page.locator('#content')).not_to_contain_text('anzahl_GROSSBUCHSTABEN')

    @make_page
    def test_js_user_management_search(self, page: Page) -> None:
        """Search for members via the admin user search in the member area.

        Also try for deletion of some elements.
        """
        page.goto("http://localhost:5000/")
        page.get_by_label("E-Mail").fill("anton@example.cde")
        page.get_by_label("Passwort").fill("secret")
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url("http://localhost:5000/")

        page.get_by_role("link", name="Mitglieder").click()
        page.wait_for_url("http://localhost:5000/cde/")
        page.get_by_role("button", name="Benutzer-Administration").click()
        page.wait_for_url("http://localhost:5000/cde/")
        page.get_by_role("link", name="Nutzer verwalten").click()
        page.wait_for_url("http://localhost:5000/cde/search/user")

        page.get_by_placeholder("– Filter hinzufügen –").click()
        page.locator(".selectize-input").first.click()

        page.locator("#tab_qf_js").get_by_text("Vorname(n)").first.click()
        page.get_by_role("textbox", name="Vergleichswert").click()
        page.get_by_role("textbox", name="Vergleichswert").fill("o")
        page.locator(".selectize-input").first.click()
        page.locator("#tab_qf_js").get_by_text("Namenszusatz").click()
        page.locator("li:has-text(\"Namenszusatz passt zu\")").get_by_role(
            "button", name="").click()
        page.locator(".col-sm-6 > .input-group > .selectize-control"
                     " > .selectize-input").first.click()
        page.locator("#tab_qf_js").get_by_text("Geschlecht").nth(1).click()
        page.locator("span:has-text(\"Nachname\")").get_by_role(
            "button", name="").click()
        page.locator(".row > div:nth-child(2) > .input-group > .selectize-control"
                     " > .selectize-input").click()
        page.locator("#tab_qf_js").get_by_text("E-Mail").nth(2).click()
        page.get_by_role("button", name="Suche").click()

        page.wait_for_url("http://localhost:5000/cde/search/user?*")

        expect(page.locator('#content')).to_contain_text('Ergebnis [4]')
        expect(page.locator('#content')).to_contain_text('olaf@example.cde')
        expect(page.locator('#content')).to_contain_text('männlich')
        expect(page.locator('#content')).not_to_contain_text('Olafson')


    @make_page
    def test_js_registration_search(self, page: Page) -> None:
        """Search for registrations of an event.

        Also try for deletion of some elements of the search mask.
        """
        page.goto("http://localhost:5000/")
        page.get_by_label("E-Mail").fill("anton@example.cde")
        page.get_by_label("Passwort").fill("secret")
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url("http://localhost:5000/")

        page.get_by_role("link", name="Veranstaltungen").click()
        page.wait_for_url("http://localhost:5000/event/")
        page.get_by_role("link", name="Große Testakademie 2222").click()
        page.wait_for_url("http://localhost:5000/event/event/1/show")
        page.get_by_role("button", name="Orga-Schaltflächen").click()
        page.wait_for_url("http://localhost:5000/event/event/1/show")
        page.get_by_role("link", name="Anmeldungen").click()
        page.wait_for_url("http://localhost:5000/event/event/1/registration/query")

        page.locator("#tab_qf_js div:has-text(\"Filter hinzufügen\") div"
                     ).nth(1).click()
        page.locator("#tab_qf_js").get_by_text("Vorname(n)").first.click()
        page.locator(".selectize-input").first.click()
        page.locator("#tab_qf_js").get_by_text("Nachname").first.click()
        page.locator("li:has-text(\"Nachname passt zu\")").get_by_role(
            "textbox", name="Vergleichswert").click()
        page.locator("li:has-text(\"Nachname passt zu\")").get_by_role(
            "textbox", name="Vergleichswert").fill("e")
        page.locator("li:has-text(\"Vorname(n) passt zu\")").get_by_role(
            "button", name="").click()
        page.locator(".col-sm-6 > .input-group > .selectize-control"
                     " > .selectize-input").first.click()
        page.locator("#tab_qf_js").get_by_text("brings_balls").nth(1).click()
        page.locator("#tab_qf_js").get_by_text("Bereits bezahlter Betrag"
                                               ).nth(1).click()
        page.locator(".row > div:nth-child(2) > .input-group > .selectize-control"
                     " > .selectize-input").click()
        page.locator("#tab_qf_js").get_by_text("PLZ").nth(2).click()
        page.locator("span:has-text(\"E-Mail\")").get_by_role(
            "button", name="").click()
        page.get_by_role("button", name="Suche").click()

        page.wait_for_url("http://localhost:5000/event/event/1/registration/query?*")

        expect(page.locator('#content')).to_contain_text('Ergebnis [3]')
        expect(page.locator('#content')).to_contain_text('Emilia')
        expect(page.locator('#content')).to_contain_text('0.00')
        expect(page.locator('#content')).not_to_contain_text('emilia@example.cde')
