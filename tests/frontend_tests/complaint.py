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
from cdedb.filter import iban_filter
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

        ### 2. Check sample case: entries ###
        self.assertNonPresence("Philosophiekurs")

        ### 3. Check sample data: history ###

        ### 4. Create new case and check ###

        ### 5. Check case query ###
