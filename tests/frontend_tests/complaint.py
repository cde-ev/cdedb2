#!/usr/bin/env python3
import datetime

import cdedb.database.constants as const
from cdedb.common.query.log_filter import ComplaintLogFilter
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
        self.assertPresence("Fallbegleitung: Garcia Generalis", div='involved_affected')
        self.assertNonPresence(
            "Beschwerdeführer", div='involved_appellant', check_div=False
        )
        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-4-3"
        f['involvement_type'] = str(const.ComplaintInvolvementType.appellant)
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Einige dieser Nutzer sind bereits anderweitig beteiligt.",
            div='addinvolvedform',
        )

        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-1-9"
        f['involvement_type'] = str(const.ComplaintInvolvementType.appellant)
        self.submit(f)
        self.assertPresence(
            "Anton Administrator (ist informiert)", div="involved_appellant"
        )
        self.assertNonPresence("Fallbegleitung", div='involved_appellant')
        self.assertNotIn('informinvolvedform1', self.response.forms)
        self.assertNotIn('uninforminvolvedform1', self.response.forms)
        self.traverse({'href': 'involved/1/companions/change'})
        self.assertTitle("Fallbegleitung für Anton Administrator verwalten (Fall 1)")
        f = self.response.forms['addcompanionform']
        f['companion_ids'] = "DB-1-9"
        self.submit(f, check_notification=False)
        self.assertPresence("Fallbegleitung kann nicht selbst beteiligt sein.")
        f['companion_ids'] = "DB-4-3"
        self.submit(f, check_notification=False)
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
        self.assertPresence("Fallbegleitung: Emilia Eventis", div='involved_appellant')
        f = self.response.forms['removeinvolvedform1']
        self.submit(f)
        self.assertNonPresence(
            "Anton Administrator", div='involved_appellant', check_div=False
        )
        self.assertNonPresence("Emilia")

        # Ensure one can add withdrawn companions as involved, but can not reinstate them…
        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-7-8"
        f['involvement_type'] = str(const.ComplaintInvolvementType.withheld)
        self.submit(f)
        self.assertNotification(
            "Garcia Generalis war Fallbegleitung und ist nun als zurückgezogen",
            'warning',
        )
        self.traverse({'href': 'involved/4/companions/change'})
        f = self.response.forms['reinstatecompanionform7']
        self.submit(f, check_notification=False)
        self.assertNotification(
            "Aktive Fallbegleitung kann nicht selbst beteiligt sein.", 'error'
        )
        self.traverse("Fall 1")

        # Check there are no related cases
        self.assertPresence("Zusammenhängende Fälle")
        self.assertPresence("Es gibt keine hiermit zusammenhängenden Fälle.")
        self.assertNonPresence("Überlappend")

        # ##
        # ## 2. Check sample case: entries when locked ##
        self.assertNonPresence("Philosophiekurs")
        self.assertPresence("53 Zeichen. Erstellt am ", div='entry5')
        self.assertPresence(
            "Berta muss bei Anmeldung ein Einzelzimmer beantragen.", div='entry5'
        )
        self.assertNonPresence("Beteiligten hinzugefügt")
        self.traverse("Zeige Log-Einträge")
        self.assertPresence(
            "Beteiligten hinzugefügt: Anton Administrator", div='logentry1003'
        )
        self.assertPresence("von Simon Struktur; Beschwerdeführer", div='logentry1003')
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
        self.assertPresence("Aussage empfangen")
        self.traverse({'href': "entry/2/child/add"})
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.statement_cleared
        self.submit(f)
        self.assertPresence("Aussage freigegeben")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-2-7"
        f['description'] = (
            "Aussage darf verwendet werden, um \"einen ruhigen Schlaf im CdE\" zu fördern."
        )
        self.submit(f, check_notification=False)
        self.assertValidationWarning('authors')
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-3-5"
        self.submit(f)
        self.assertPresence("75 Zeichen.", div='entry1001')
        self.assertNonPresence("Versionen", div='entry1001')

        # Excursion part 1: Check measure is displayed in overview
        self.traverse("Maßnahmenübersicht")
        self.assertTitle("Maßnahmenübersicht")
        self.assertPresence("Maßnahme gegen Bertå Beispiel", div='entry6')
        self.assertPresence("von Charly Clown", div='entry6')
        self.assertPresence(
            "Berta muss bei Anmeldung ein Einzelzimmer beantragen.", div='entry6'
        )
        self.traverse("Fall 1")

        # Entry revocation
        self.assertNoLink("entry/4/revoke")
        self.traverse({'href': "entry/5/revoke"})
        f = self.response.forms['configureentryform']
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('authors', "Darf nicht leer sein.")
        self.assertValidationError('description', " Muss eine Zeichenkette sein.")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = (
            "Berta hat herausgefunden, dass sie nicht schnarcht, wenn sie eine Wäscheklammer auf der Nase trägt."
        )
        pre_submit_response = self.response
        self.submit(f)
        self.assertPresence("Maßnahme: widerrufen", div='entry1002')
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
        self.assertPresence("Derzeit sind keine Maßnahmen in Kraft.")
        self.assertNonPresence("Beispiel")
        self.assertNonPresence("von")
        self.response = saved_response

        # ##
        # ## 3. Check sample case: entries when unlocked ##
        f = self.response.forms['unlockcaseform']
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('reason', "Darf nicht leer sein.")
        f = self.response.forms['unlockcaseform']
        f['reason'] = "Ich bin halt leider viel zu neugierig."
        self.submit(f)
        self.assertNoLink("entry/2/remove")
        self.assertNoLink("entry/4/remove")
        self.traverse(
            {'href': "entry/4/revoke"},
            {'description': "Fall 1"},
            {'href': "entry/4/replace"},
        )
        f = self.response.forms['configureentryform']
        f['description'] = "Berta wird ab jetzt immer ein Schnarchzimmer zu beantragen."
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('dreason', "Darf nicht leer sein.")
        f['dreason'] = "Ist fairer."
        self.submit(f)
        self.assertPresence("59 Zeichen. 2 vorherige Versionen.", div='entry4')
        self.assertPresence("zuletzt geändert", div='entry4')
        self.assertPresence("Schnarchzimmer", div='entry4')

        # Revoke recovation
        self.traverse({'href': "entry/1002/revoke"})
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = "Hat leider nicht geklappt…"
        self.submit(f)
        self.assertNoLink("entry/1003/revoke")
        self.get("/core/complaint/case/1/entry/1003/revoke")
        self.follow()
        self.assertTitle("Fall 1")
        msg = "Widerruf eines Widerrufs kann nicht widerrufen werden."
        self.assertNotification(msg, 'error')
        self.post("/core/complaint/case/1/entry/1003/revoke", {}, evade_anti_csrf=True)
        self.follow()
        self.assertTitle("Fall 1")
        self.assertNotification(msg, 'error')

        # Excursion part 3: Check revoked measure revocation leads to display
        self.traverse("Maßnahmenübersicht")
        self.assertTitle("Maßnahmenübersicht")
        self.assertPresence("Maßnahme gegen Bertå Beispiel", div='entry6')
        self.traverse("Fall 1")

        # Remove entry
        self.traverse({'href': "entry/1003/remove"})
        f = self.response.forms['removeentryform']
        f['dreason'] = "War ein Versehen."
        self.submit(f)
        self.assertNonPresence("Widerruf: widerrufen")
        self.get("/core/complaint/case/1/entry/1003/remove")
        self.follow()
        self.assertTitle("Fall 1")
        msg = "Eintrag ist bereits entfernt."
        self.assertNotification(msg, 'info')
        self.get("/core/complaint/case/1/show")
        self.post(
            "/core/complaint/case/1/entry/1003/remove",
            {'dreason': "Piep."},
            evade_anti_csrf=True,
        )
        self.follow()
        self.assertTitle("Fall 1")
        self.assertNotification(msg, 'error')

        # Excursion part 4: Check revocation deletion leads to display
        saved_response = self.response
        self.traverse("Maßnahmenübersicht")
        self.assertTitle("Maßnahmenübersicht")
        self.assertNonPresence("Beispiel")
        self.response = saved_response

        # Case history
        self.traverse("Eintragshistorie zeigen")
        self.assertPresence("unterzeichnet am 28.05.2025, freigegeben", div='entry2')
        self.assertPresence("Version 1 von Charly Clown. 80 Zeichen.", div='entry4')
        self.assertPresence("Ersetzt am ", div='entry4')
        self.assertNonPresence("Gelöscht am ", div='entry4')
        self.assertPresence("Anton Administrator: Ungünstige Wortwahl", div='entry4')
        self.assertPresence("lang und breit", div='entry4')
        self.assertPresence("Version 2 von Charly Clown. 77 Zeichen.", div='entry4')
        self.assertPresence("Version 3 von Charly Clown. 59 Zeichen.", div='entry4')
        self.assertPresence("Schnarchzimmer", div='entry4')
        self.assertPresence("Widerruf: widerrufen", div='entry1003')
        self.assertPresence("Version 1 von Simon Struktur. 26 Zeichen.")
        self.assertPresence("Gelöscht am", div='entry1003')
        self.assertNonPresence("Ersetzt am", div='entry1003')
        self.assertNoLink("/entry/")
        self.assertPresence(
            "Beteiligten hinzugefügt: Daniel Dino von Anton Administrator; Betroffene",
            div='logentry2',
        )
        self.assertPresence(
            "Fallbegleitung zurückgezogen: Garcia Generalis (für Daniel Dino)",
            div='logentry1012',
        )

        # Lock case
        self.traverse("Fall 1")
        f = self.response.forms['lockcaseform']
        self.submit(f)
        self.assertNonPresence("Philosophie")

        # ##
        # ## 4. Create new case and check ##
        self.traverse("Fallarchiv", "Fall anlegen")
        f = self.response.forms['configurecaseform']
        f['summary'] = "Die Texte von Schorsch Recklich verstören Menschen."
        f['kind'] = const.ComplaintKind.nonphysical_sexual_transgression
        f['start_date'] = "2222-01-02"
        f['end_date'] = "2222-01-06"
        f['appellant_id'] = "DB-19-1"
        f['target_ids'] = "DB-10-8"
        f['is_affected'] = True
        f['timestamp'] = "2222-03-13"
        f['info'] = "Beschreibung folgt, zwischen Tür und Angel…"
        self.submit(f, check_notification=False)
        self.assertNotification(
            "Du darfst keinen Fall mit eigener Beteiligung erstellen.",
            'error',
        )
        f = self.response.forms['configurecaseform']
        f['appellant_id'] = "DB-10-8"
        self.submit(f, check_notification=False)
        self.assertValidationError('target_ids')
        self.assertValidationError('appellant_id')
        with self.assertRaises(AssertionError):
            self.assertValidationError('affected_ids')
        f = self.response.forms['configurecaseform']
        f['appellant_id'] = "DB-1-9"
        self.submit(f)
        self.assertPresence("Zusammenfassung Die Texte von Schorsch")
        self.assertPresence("Art Sexuelle Belästigung")
        self.assertPresence("Startdatum 02.01.2222")
        self.assertPresence("Enddatum 06.01.2222")
        self.assertPresence("Anton", div='involved_affected')
        self.assertPresence("Information", div='entry1004')
        self.assertPresence("43 Zeichen", div='entry1004')
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
            "Du darfst nicht nach eigener Beteiligung suchen.",
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
        f['summary'] = f['summary'].value + " Wirklich!"
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

        # Excursion: Add entries without parent
        # without concerned_id
        self.traverse("Eigenständigen Eintrag hinzufügen")
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.synthesis
        self.submit(f)
        self.assertPresence("Synthese")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = "Hat sich nie wieder gemeldet."
        self.submit(f)
        self.assertPresence("29 Zeichen.", div='entry1005')
        self.assertNonPresence("Hat sich nie wieder gemeldet.")
        # with concerned_id
        self.traverse("Eigenständigen Eintrag hinzufügen")
        f = self.response.forms['selectentrytypeform']
        f['entry_type'] = const.ComplaintEntryType.provisional_statement_given
        self.submit(f)
        self.assertPresence("Vorläufige Aussage getätigt")
        f = self.response.forms['configureentryform']
        f['authors'] = "DB-19-1"
        f['description'] = "Ich will auch was sagen!"
        self.submit(f, check_notification=False, check_mandatory_filled=False)
        self.assertValidationError('concerned_id')
        f['concerned_id'] = "DB-6-X"
        self.submit(f, verbose=True)
        self.assertPresence("24 Zeichen", div='entry1006')
        self.assertNonPresence("Ich will auch was sagen!")

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

            f = self.response.forms['complaintsearchform']
            f['qval_involved.persona_id'] = "DB-10-8"
            self.submit(f)
            self.assertNotification("1 Fälle nicht angezeigt.", 'warning')
            f['qval_involved.involved_type'] = (
                const.ComplaintInvolvementType.target.value
            )
            self.submit(f)
            self.assertNonPresence("nnicht angezeigt", div='notifications')

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
                "/core/complaint/case/1001/entry/1004/remove",
                "/core/complaint/case/1001/entry/1004/revoke",
                "/core/complaint/case/1001/entry/add",
            }
            for url in urls:
                _test_forbidden(url)

        # ##
        # ## 7. Test logging ##
        log_expectation = (
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.involved_informed,
                'persona_id': 2,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.involved_uninformed,
                'persona_id': 2,
            },
            {
                'case_id': 1,
                'change_note': 'Beschwerdeführer',
                'code': const.ComplaintLogCodes.involved_added,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.involved_informed,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_added,
                'companion_id': 5,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_added,
                'companion_id': 9,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_withdrawn,
                'companion_id': 9,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_reinstated,
                'companion_id': 9,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_removed,
                'companion_id': 9,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'change_note': 'Beschwerdeführer',
                'code': const.ComplaintLogCodes.involved_removed,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_removed,
                'companion_id': 5,
                'persona_id': 1,
            },
            {
                'case_id': 1,
                'code': const.ComplaintLogCodes.companion_withdrawn,
                'companion_id': 7,
                'persona_id': 4,
            },
            {
                'case_id': 1,
                'change_note': 'Versteckt vor',
                'code': const.ComplaintLogCodes.involved_added,
                'persona_id': 7,
            },
            {
                'case_id': 1,
                'change_note': 'Ich bin halt leider viel zu neugierig.',
                'code': const.ComplaintLogCodes.case_unlocked,
            },
            {
                'case_id': 1001,
                'code': const.ComplaintLogCodes.case_created,
            },
            {
                'case_id': 1001,
                'change_note': 'Betroffene',
                'code': const.ComplaintLogCodes.involved_added,
                'persona_id': 1,
            },
            {
                'case_id': 1001,
                'code': const.ComplaintLogCodes.involved_informed,
                'persona_id': 1,
            },
            {
                'case_id': 1001,
                'change_note': 'Zielpersonen',
                'code': const.ComplaintLogCodes.involved_added,
                'persona_id': 10,
            },
            {
                'case_id': 1,
                'change_note': 'Ist jetzt schwerwiegend.',
                'code': const.ComplaintLogCodes.case_changed_grave,
            },
            {
                'case_id': 1,
                'change_note': 'Jemand schnarcht ganz furchtbar. -> Jemand schnarcht ganz furchtbar. Wirklich!',
                'code': const.ComplaintLogCodes.case_changed_summary,
            },
            {
                'case_id': 1,
                'change_note': 'Hinzugefügt (04.01.2222)',
                'code': const.ComplaintLogCodes.case_changed_end_date,
            },
            {
                'case_id': 1001,
                'code': const.ComplaintLogCodes.concealed_case_detected,
                'persona_id': 10,
                'submitted_by': 1,
            },
            {
                'case_id': 1001,
                'code': const.ComplaintLogCodes.concealed_case_detected,
                'persona_id': 10,
                'submitted_by': 1,
            },
        )

        self.assertLogEqual(log_expectation, realm='complaint', offset=6)

        # ##
        # ## 8. Test related cases
        self.get("/core/complaint/case/1001/show")
        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-4-3"
        f['involvement_type'] = str(const.ComplaintInvolvementType.appellant)
        self.submit(f)
        self.assertPresence(
            "Fall 1 ist bestätigt ist schwerwiegend"
            " (28.05.2025–04.01.2222): Jemand schnarcht ganz furchtbar. Wirklich!"
            " Überlappende Beteiligte: Daniel Dino (Betroffene Bt)",
            div='related-cases',
            exact=True,
        )
        self.assertNonPresence("1001", div='related-cases')

        def _assertHidden() -> None:
            self.get("/core/complaint/case/1/show")
            self.assertPresence(
                "Fall 1001: Warnung Wegen eigener Beteiligung"
                " oder möglicher Befangenheit nicht angezeigt.",
                div='related-cases',
                exact=True,
            )

        with self.switch_user("anton"):
            _assertHidden()

        f = self.response.forms['addinvolvedform']
        f['persona_ids'] = "DB-2-7"
        f['involvement_type'] = str(const.ComplaintInvolvementType.target)
        self.submit(f)
        self.assertPresence(
            "Fall 1 eng zusammenhängend ist bestätigt ist schwerwiegend"
            " (28.05.2025–04.01.2222): Jemand schnarcht ganz furchtbar. Wirklich!"
            " Überlappende Beteiligte:"
            " Daniel Dino (Betroffene Bt), Bertå Beispiel (Zielpersonen Zp)",
            div='related-cases',
            exact=True,
        )

        with self.switch_user("anton"):
            _assertHidden()
