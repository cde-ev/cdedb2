#!/usr/bin/env python3
import cdedb.database.constants as const
from tests.common import (
    FrontendTest,
    as_users,
)


class TestComplaintFrontend(FrontendTest):

    @as_users("simon")
    def test_entity_case(self) -> None:
        self.traverse("Fallarchiv")
        self.assertTitle("Fallarchiv")

        # ##
        # ## 1. Check sample case: involved ##
        f = self.response.forms['complaintsearchform']
        self.submit(f)
        self.assertTitle("Fall 1")
        self.assertPresence("Zielpersonen", div='involved_target')
        self.assertPresence("Beispiel", div='involved_target')
        # Test informing
        self.assertNonPresence("informiert", div='involved_target')
        self.assertNotIn('uninforminvolvedform2', self.response.forms)
        f = self.response.forms['informinvolvedform2']
        self.submit(f)
        self.assertPresence("Beispiel (ist informiert)", div='involved_target')
        self.assertNotIn('informinvolvedform2', self.response.forms)
        f = self.response.forms['uninforminvolvedform2']
        self.submit(f)
        self.assertNonPresence("informiert", div='involved_target')

        self.assertPresence("Fallbegleitung: Charly Clown", div='involved_target')

        self.assertPresence("Betroffene", div='involved_affected')
        self.assertPresence("Daniel Dino (ist informiert)", div='involved_affected')
        self.assertPresence("Fallbegleitung: Garcia Generalis",
                            div='involved_affected')
        self.assertNonPresence(
            "Beschwerdeführer",
            div='involved_appellant',
            check_div=False
        )
        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-4-3"
        f['involvement_type'] = "ComplaintInvolvementType.appellant"
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Einige dieser Nutzer sind bereits anderweitig beteiligt.",
            div='addinvolvedform'
        )

        # TODO Ensure one can add withdrawn companions as involved, but can not reinstate them…
        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-1-9"
        f['involvement_type'] = "ComplaintInvolvementType.appellant"
        self.submit(f)
        self.assertPresence("Anton Administrator (ist informiert)",
                            div="involved_appellant")
        self.assertNonPresence("Fallbegleitung", div='involved_appellant')
        self.assertNotIn('informinvolvedform1', self.response.forms)
        self.assertNotIn('uninforminvolvedform1', self.response.forms)
        self.traverse({'href': 'involved/1/companions/change'})
        self.assertTitle("Fallbegleitung für Anton Administrator verwalten (Fall 1)")
        f = self.response.forms['addcompanionform']
        f['companion_ids'] = "DB-1-9"
        self.submit(f, check_notification=False, verbose=True)
        self.assertPresence("Fallbegleitung kann nicht selbst beteiligt sein.")
        f['companion_ids'] = "DB-4-3"
        self.submit(f, check_notification=False, verbose=True)
        self.assertPresence("Fallbegleitung kann nicht selbst beteiligt sein.")
        f = self.response.forms['addcompanionform']
        f['companion_ids'] = "DB-3-5"
        self.submit(f, check_notification=False)
        self.assertPresence("Fallbegleitung auf Gegenseite.")
        f = self.response.forms['addcompanionform']
        f['companion_ids'] = "DB-5-1,DB-9-4"
        self.submit(f)
        self.assertPresence("Emilia")
        self.assertPresence("Inga")
        self.assertNotIn('reinstatecompanionform9', self.response.forms)
        f = self.response.forms['withdrawcompanionform9']
        self.submit(f)
        self.assertNotIn('withdrawcompanionform9', self.response.forms)
        f = self.response.forms['reinstatecompanionform9']
        self.submit(f)
        f = self.response.forms['removecompanionform9']
        self.submit(f)
        self.assertNonPresence("Inga")
        self.traverse("Fall 1")
        self.assertPresence(
            "Fallbegleitung: Emilia Eventis",
            div='involved_appellant'
        )
        f = self.response.forms['removeinvolvedform1']
        self.submit(f)
        self.assertNonPresence(
            "Anton Administrator",
            div='involved_appellant',
            check_div=False
        )
        self.assertNonPresence("Emilia")

        # ##
        # ## 2. Check sample case: entries when locked ##
        self.assertNonPresence("Philosophiekurs")
        self.assertPresence("53 Zeichen. Erstellt am ", div='entry5')
        self.assertPresence(
            "Berta muss bei Anmeldung ein Einzelzimmer beantragen.",
            div='entry5'
        )
        self.assertNonPresence("Beteiligten hinzugefügt")
        self.traverse("Zeige Log-Einträge")
        self.assertPresence("Beteiligten hinzugefügt: Anton Administrator",
                            div='logentry1003')
        self.assertPresence("von Simon Struktur; Beschwerdeführer",
                            div='logentry1003')
        # self.assertPresence(date_filter(now().date(), lang="de"), div='logentry1001')
        self.assertNoLink('/core/complaint/case/1/history')

        # Entry creation and change
        self.assertNoLink("entry/4/replace")
        self.assertNoLink("entry/4/remove")
        self.assertNoLink("entry/2/replace")
        self.assertNoLink("entry/2/remove")
        self.traverse({'href': "entry/2/child/add"})
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.statement_received
        self.submit(f)
        # self.assertPresence("Aussage angekommen")
        self.traverse({'href': "entry/2/child/add"})
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.statement_cleared
        self.submit(f)
        # self.assertPresence("Aussage freigegeben")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-3-5"
        f['description'] = "Aussage darf verwendet werden, um \"einen ruhigen Schlaf im CdE\" zu fördern."
        self.submit(f)
        self.assertPresence("75 Zeichen.", div='entry1001')

        # Excursion part 1: Check measure is displayed in overview
        self.traverse("Maßnahmenübersicht")
        self.assertTitle("Maßnahmenübersicht")
        # self.assertPresence("Maßnahme gegen Berta Beispiel", div='entry6')
        self.assertPresence("von Charly Clown", div='entry6')
        self.assertPresence(
            "Berta muss bei Anmeldung ein Einzelzimmer beantragen.",
            div='entry6')
        self.traverse("Fall 1")

        # Entry revocation
        self.assertNoLink("entry/4/revoke")
        self.traverse({'href': "entry/5/revoke"})
        f = self.response.forms['configureentryform']
        self.submit(f, check_notification=False)
        self.assertValidationError('authors', "Darf nicht leer sein.")
        self.assertValidationError('description', " Muss eine Zeichenkette sein.")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = "Berta hat herausgefunden, dass sie nicht schnarcht, wenn sie eine Wäscheklammer auf der Nase trägt."
        pre_submit_response = self.response
        self.submit(f)
        self.assertPresence("99 Zeichen. Erstellt am ", div='entry1002')
        self.assertNonPresence("Wäscheklammer")
        self.assertNoLink("entry/4/revoke")
        self.assertNoLink("entry/1002/revoke")

        # Try revocation once more
        self.response = pre_submit_response
        self.submit(f, check_notification=False)
        self.assertNotification("Eintrag bereits widerrufen.", 'error')

        # Excursion part 2: Check measure is no longer displayed in overview
        saved_response = self.response
        self.traverse("Maßnahmenübersicht")
        self.assertNonPresence("Beispiel")
        self.assertNonPresence("von")
        self.response = saved_response

        # ##
        # ## 3. Check sample case: entries when unlocked ##
        # TODO unlock
        # self.assertNoLink("entry/2/remove")
        # self.assertNoLink("entry/4/remove")
        # self.traverse(
        #    {'href': "entry/4/revoke"},
        #    {'description': "Fall 1"},
        #    {'href': "entry/4/replace"},
        # )
        # TODO replace
        # TODO revoke 1002 and check, try revoking 1003
        # TODO Excursion part 3: Check revoked measure revocation leads to display
        # TODO Try deletion (twice) and adding child to deleted parent

        # ##
        # ## 4. Create new case and check ##
        self.traverse("Fallarchiv", "Fall anlegen")
        f = self.response.forms['configurecaseform']
        f['summary'] = "Die Texte von Schorsch Recklich verstören Menschen."
        f['kind'] = const.ComplaintKind.nonphysical_sexual_transgression
        f['start_date'] = "2222-01-02"
        f['end_date'] = "2222-01-06"
        f['appellant_id'] = "DB-19-1"
        f['is_affected'] = True
        f['timestamp'] = "2222-03-13"
        f['info'] = "Beschreibung folgt, zwischen Tür und Angel…"
        self.submit(f, check_notification=False)
        self.assertNotification(
            "Du darfst keinen Fall mit eigener Beteiligung erstellen.",
            'error',
        )
        f['appellant_id'] = "DB-1-9"
        self.submit(f)
        self.assertPresence("Zusammenfassung Die Texte von Schorsch")
        self.assertPresence("Art Sexuelle Belästigung")
        self.assertPresence("Startdatum 02.01.2222")
        self.assertPresence("Enddatum 06.01.2222")
        self.assertPresence("Anton", div='involved_affected')
        # self.assertPresence("generic_information", div='entry1003')
        self.assertPresence("43 Zeichen", div='entry1003')
        self.assertNonPresence("Tür und Angel")

        # ##
        # ## 5. Check case query ##
        self.traverse("Fallarchiv")
        f = self.response.forms['complaintsearchform']
        self.submit(f)
        self.assertPresence("2 Fälle gefunden")
        self.assertPresence("Fall 1 ist bestätigt", div='case1')
        self.assertNonPresence("schwerwiegend")
        self.assertNonPresence("abgeschlossen")
        self.assertPresence("Zielpersonen Zp: Bertå Beispiel", div='case1')
        self.assertPresence("Betroffene Bt: Daniel Dino", div='case1')
        self.assertPresence("Jemand schnarcht ganz furchtbar.", div='case1')
        self.assertPresence("Fall 1001", div='case1001')
        self.assertPresence("02.01.2222–06.01.2222", div='case1001')

        # Check that one may not search for own involevement
        f = self.response.forms['complaintsearchform']
        f['qval_involved.persona_id'] = "DB-19-1"
        self.submit(f, check_notification=False)
        self.assertValidationError(
            'qval_involved.persona_id',
            "Du darfst nicht nach eigener Beteiligung suchen."
        )

        # TODO Test last changed

        # Check date search
        f = self.response.forms['complaintsearchform']
        f['qval_involved.persona_id'] = ""
        f['qval_cases.start_date'] = "2222-01-05"
        self.submit(f)
        self.assertPresence("2 Fälle gefunden")

        f = self.response.forms['complaintsearchform']
        f['qval_cases.end_date'] = "2200-01-01"
        self.submit(f)
        self.assertPresence("2 Fälle gefunden")

        # Excursion: Change case
        self.traverse("Fall 1", "Bearbeiten")
        f = self.response.forms['configurecaseform']
        f['summary'] = str(f['summary']) + " Wirklich!"
        f['is_grave'] = True
        f['end_date'] = "2222-01-04"
        self.assertNonPresence("etroffen")
        self.assertNonPresence("Initiale Angaben")
        self.submit(f)

        self.traverse("Fallarchiv")
        f = self.response.forms['complaintsearchform']
        self.submit(f)
        self.assertPresence("ist schwerwiegend", div='case1')

        f = self.response.forms['complaintsearchform']
        f['qval_cases.end_date'] = "2222-01-05"
        self.submit(f)
        self.assertTitle("Fall 1001")

        # Excursion: Add entry without parent
        self.traverse("Eigenständigen Eintrag hinzufügen")
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.synthesis
        self.submit(f)
        # self.assertPresence("Synthese")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = "Hat sich nie wieder gemeldet."
        self.submit(f)
        self.assertPresence("29 Zeichen.", div='entry1004')
        self.assertNonPresence("Hat sich nie wieder gemeldet.")

        self.traverse("Fallarchiv")
        f = self.response.forms['complaintsearchform']
        self.submit(f)
        self.assertPresence("ist abgeschlossen", div='case1001')

        # ##
        # ## 6. Check protection ##
        with self.switch_user("anton"):
            self.traverse("Fallarchiv")
            f = self.response.forms['complaintsearchform']
            self.submit(f)
            self.assertTitle("Fallarchiv")
            self.assertNotification("1 Fälle nicht angezeigt.", 'warning')
            self.assertPresence("2 Fälle gefunden")
            self.assertNonPresence("Fall 1001")
            self.assertPresence("Fall 1", div='case1')

            # TODO test logged case

            def _test_forbidden(url: str) -> None:
                self.get(url, status=403)
                self.post(url, {}, status=403, evade_anti_csrf=True)

            self.get("/core/complaint/case/1001/show", status=403)
            self.get("/core/complaint/case/1001/history", status=403)
            self.get(
                "/core/complaint/case/1001/involved/1/companions/change", status=403
            )
            self.get(
                "/core/complaint/case/1001/involved/23/companions/change", status=403
            )

            urls = {
                "/core/complaint/case/1001/change",
                "/core/complaint/case/1001/entry/1003/remove",
                "/core/complaint/case/1001/entry/1003/revoke",
                "/core/complaint/case/1001/entry/add",
            }
            for url in urls:
                _test_forbidden(url)
