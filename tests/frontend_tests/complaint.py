#!/usr/bin/env python3
import datetime
import random
import re
import urllib.parse
from typing import Optional, Union

import webtest

import cdedb.database.constants as const
import cdedb.models.core as models_core
import cdedb.models.droid as model_droid
from cdedb.common import (
    IGNORE_WARNINGS_NAME,
    CdEDBObject,
    GenesisDecision,
    PrivilegeError,
    get_hash,
    make_persona_name,
    now,
)
from cdedb.common.exceptions import CryptographyError
from cdedb.common.query import QueryOperators
from cdedb.common.query.log_filter import ChangelogLogFilter
from cdedb.common.roles import ADMIN_VIEWS_COOKIE_NAME
from cdedb.filter import iban_filter, date_filter
from tests.common import (
    USER_DICT,
    FrontendTest,
    UserIdentifier,
    UserObject,
    as_users,
    execsql,
    get_user,
    prepsql,
)


class TestComplaintFrontend(FrontendTest):

    @as_users("simon")
    def test_entity_case(self) -> None:
        self.traverse("Fallarchiv")
        self.assertTitle("Fallarchiv")


        ### 1. Check sample case: involved ###
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


        ### 2. Check sample case: entries ###
        # when locked
        self.assertNonPresence("Philosophiekurs")
        self.assertPresence(f"53 Zeichen. Erstellt am ", div='entry5')
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
        self.submit(f)
        self.assertPresence(f"99 Zeichen. Erstellt am ", div='entry1002')
        self.assertNonPresence("Wäscheklammer")
        self.assertNoLink("entry/4/revoke")
        self.assertNoLink("entry/1002/revoke")

        # when unlocked
        # TODO unlock
        # self.assertNoLink("entry/2/remove")
        # self.assertNoLink("entry/4/remove")
        # self.traverse(
        #    {'href': "entry/4/revoke"},
        #    {'description': "Fall 1"},
        #    {'href': "entry/4/replace"},
        # )
        # TODO replace
        # TODO revoke 1002 and check
        # Try deletion

        ### 4. Create new case and check ###
        self.traverse("Fallarchiv", "Fall anlegen")
        f = self.response.forms['configurecaseform']
        f['summary'] = "Die Texte von Schorsch Recklich verstören Menschen."
        f['kind'] = const.ComplaintKind.nonphysical_sexual_transgression
        f['start_date'] = "2222-01-03"
        f['end_date'] = "2222-01-06"
        f['appellant_id'] = "DB-1-5"
        f['is_affected'] = True
        f['timestamp'] = "2222-03-13"
        f['info'] = "Beschreibung folgt, zwischen Tür und Angel…"
        self.submit(f)

        ### 5. Check case query ###
        # TODO Test date search in particular
