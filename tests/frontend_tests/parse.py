#!/usr/bin/env python3
# pylint: disable=missing-module-docstring
import collections
import csv
import datetime
import decimal
import types
import unittest.mock
from typing import Any, Optional, cast

import webtest

import cdedb.frontend.cde.parse_statement as parse
import cdedb.models.event as models_event
from cdedb.backend.event import EventBackend
from cdedb.common import Accounts, CdEDBObject, now
from cdedb.frontend.common import CustomCSVDialect
from tests.common import FrontendTest, as_users, storage


class TestParseFrontend(FrontendTest):
    def csv_submit(self, form: webtest.Form, button: str = "",
                   value: Optional[str] = None) -> None:
        super().submit(form, button=button, value=value, check_notification=False)
        self.assertEqual(self.response.text[0], "\ufeff")
        self.response.text = self.response.text[1:]

    @staticmethod
    def get_transaction_with_reference(reference: str) -> parse.Transaction:
        transaction_data: CdEDBObject = collections.defaultdict(str)
        transaction_data.update({
            "reference": reference,
        })
        return parse.Transaction(transaction_data)

    def test_find_cdedbids(self) -> None:
        # pylint: disable=protected-access
        cl = parse.ConfidenceLevel
        t = self.get_transaction_with_reference("DB-2-7 DB-35")
        # All confidence values are reduced by two, because multiple ids were found.
        expectation = {
            2: parse.ConfidenceLevel.Medium,  # good match.
            3: parse.ConfidenceLevel.Low,  # close match.
        }
        self.assertEqual(expectation, t._find_cdedbids())  # pylint: disable=protected-access

        t = self.get_transaction_with_reference("DB-1000-6")
        self.assertEqual({1000: cl.Full}, t._find_cdedbids())
        t = self.get_transaction_with_reference("DB/1000 6 DB-100-7")
        self.assertEqual({1000: cl.Low, 100: cl.Medium}, t._find_cdedbids())

    def test_parse_statement_additional(self) -> None:

        pseudo_winter = cast(models_event.Event, types.SimpleNamespace(**{
            "title": "CdE Pseudo-WinterAkademie",
            "shortname": "pwinter222223",
            "begin": datetime.date(2222, 12, 27),
            "end": datetime.date(2223, 1, 6)}))
        test_pfingsten = cast(models_event.Event, types.SimpleNamespace(**{
            "title": "Pfingstakademie 1234",
            "shortname": "pa1234",
            "begin": datetime.date(1234, 5, 20),
            "end": datetime.date(1234, 5, 23)}))
        naka = cast(models_event.Event, types.SimpleNamespace(**{
            "title": "NachhaltigkeitsAkademie",
            "shortname": "naka",
            "begin": now().date(),
            "end": now().date()}))
        velbert = cast(models_event.Event, types.SimpleNamespace(**{
            "title": "JuniorAkademie NRW – Nachtreffen Velbert 2019",
            "shortname": "velbert19",
            "begin": datetime.date(2019, 11, 15),
            "end": datetime.date(2019, 11, 17)}))

        def match(event: models_event.Event, reference: str,
                  expected_confidence: Optional[parse.ConfidenceLevel]) -> None:
            fake_transaction = cast(
                parse.Transaction,
                types.SimpleNamespace(
                    reference=reference,
                    compile_pattern=parse.Transaction.compile_pattern,
                ))
            match = parse.Transaction._match_one_event(fake_transaction, event)  # pylint: disable=protected-access
            if expected_confidence is None:
                self.assertIsNone(match)
            else:
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(expected_confidence, match.confidence)

        cl = parse.ConfidenceLevel

        match(pseudo_winter, "pwinter222223", cl.Full)
        match(pseudo_winter, "pwinter2222232425", cl.High)
        match(pseudo_winter, "CdE Pseudo-WinterAkademie", cl.Full)
        match(pseudo_winter, "CdE Pseudo-WinterAkademie 2222/2223", cl.Full)
        match(pseudo_winter, "CdE Pseudo-WinterAkademie2222", cl.High)

        match(test_pfingsten, "pa1234", cl.Medium)
        match(test_pfingsten, "PfingstAkademie 1234", cl.Medium)
        match(test_pfingsten, "PfingstAkademie 123456", cl.Low)

        match(naka, "naka", cl.Full)
        match(naka, "NAKA", cl.Full)
        match(naka, "CdE NachhaltigkeitsAkademie", cl.Full)
        match(naka, "CdE NachhaltigkeitsAkademie(n)", cl.Full)

        match(velbert, "velbert19", cl.Medium)
        match(velbert, "JuniorAkademie NRW Nachtreffen Velbert 2019", cl.Medium)
        match(velbert, "JuniorAkademie NRW – Nachtreffen Velbert 2019", cl.Medium)
        match(velbert, "JuniorAkademie NRW   Nachtreffen Velbert 2019", cl.Medium)
        match(velbert, "JuniorAkademie NRW - Nachtreffen Velbert 2019", None)
        match(velbert, "Velbert 2019", None)

    def test_fee_matching(self) -> None:
        # Match TestAka via reference, but Party via amount.
        amount = decimal.Decimal("3.50")
        data: CdEDBObject = collections.defaultdict(lambda: None)
        data.update({
            'reference': "TestAka",
            'errors': [],
            'warnings': [],
            'amount': amount,
            'event': None,
        })
        transaction = parse.Transaction(data)
        transaction.persona = {'id': 1}
        event_backend = self.initialize_backend(EventBackend)
        event_backend.list_amounts_owed = unittest.mock.MagicMock(  # type: ignore[method-assign]
            return_value={2: amount})
        transaction._match_event(rs=self.key, event_backend=event_backend)  # pylint: disable=protected-access

        # Check that reference match is better.
        self.assertIsNotNone(transaction.event)
        assert transaction.event is not None
        self.assertEqual(parse.ConfidenceLevel.Medium, transaction.event_confidence)
        self.assertEqual("Große Testakademie 2222", transaction.event.title)

        # Check that "match only by amount" warning is not present.
        self.assertEqual([], transaction.warnings)
        self.assertEqual([], transaction.errors)

    def check_dict(self, adict: CdEDBObject, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if "_" not in k:
                assertion, key = "", ""
            else:
                assertion, key = k.split("_", 1)
            if assertion == "In":
                self.assertIn(v, adict[key])
            elif assertion == "NotIn":  # pragma: no cover
                self.assertNotIn(v, adict[key])
            else:
                self.assertEqual(v, adict[k])

    @storage
    @as_users("farin")
    def test_parse_statement(self) -> None:
        self.get("/cde/parse")
        self.assertTitle("Kontoauszug parsen")
        f = self.response.forms["statementform"]
        with open(self.testfile_dir / "statement.csv", mode="rb") as statementfile:
            f["statement_file"] = webtest.Upload(
                "statement.csv", statementfile.read(), "text/csv")
        self.submit(f, check_notification=False, verbose=True)

        self.assertTitle("Kontoauszug parsen")
        self.assertPresence("3 Transaktionen mit Fehlern", div="has_error_summary")
        self.assertPresence("2 Transaktionen mit Warnungen", div="has_warning_summary")
        self.assertPresence("9 fehlerfreie Transaktionen", div="has_none_summary")

        f = self.response.forms["parsedownloadform"]

        # Fix Transactions with errors.

        # Check line 5:
        self.assertPresence("event: Veranstaltung Große Testakademie 2222 nur über"
                            " zu zahlenden Betrag zugeordnet.",
                            div="transaction5_warnings")

        # Fix line 6:
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction6_errors")
        self.assertPresence(
            "given_names: Anton Armin A. nicht im Verwendungszweck gefunden.",
            div="transaction6_warnings")
        self.assertPresence(
            "family_name: Administrator nicht im Verwendungszweck gefunden.",
            div="transaction6_warnings")
        self.assertEqual(f["cdedbid6"].value, "DB-1-9")
        f["persona_confirm6"].checked = True

        # Fix line 9:
        self.assertPresence("cdedbid: Braucht Mitgliedszuordnung.",
                            div="transaction9_errors")
        self.assertEqual(f["account_holder9"].value, "Daniel Dino")
        f["cdedbid9"] = "DB-4-3"

        # Fix line 11:
        self.assertPresence("persona: Mehr als eine DB-ID gefunden: (DB-1-9, DB-2-7)",
                            div="transaction11_warnings")
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction11_errors")
        self.assertEqual(f["account_holder11"].value, "Anton & Berta")
        self.assertEqual(f["cdedbid11"].value, "DB-1-9")
        f["persona_confirm11"].checked = True

        # Check transactions with warnings.

        # Line 8:
        self.assertPresence(
            "given_names: Garcia G. nicht im Verwendungszweck gefunden.",
            div="transaction8_warnings")

        self.submit(f, button="validate", check_notification=False)

        self.assertTitle("Kontoauszug parsen")
        self.assertPresence("1 Transaktionen mit Fehlern", div="has_error_summary")
        self.assertNonPresence("Transaktionen mit Warnungen")
        self.assertPresence("13 fehlerfreie Transaktionen", div="has_none_summary")

        # Check new error:

        # Line 9:
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction9_errors")
        self.assertEqual(f["cdedbid9"].value, "DB-4-3")
        f["persona_confirm9"].checked = True

        self.submit(f, button="validate", check_notification=False)

        self.assertTitle("Kontoauszug parsen")
        self.assertNonPresence("Transaktionen mit Fehlern")
        self.assertNonPresence("Transaktionen mit Warnungen")
        self.assertPresence("14 fehlerfreie Transaktionen", div="has_none_summary")

        save = self.response
        f = save.forms["parsedownloadform"]

        # check Testakademie csv.

        # Make sure to use the correct submit button.
        self.csv_submit(f, button="db_import")
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.ExportFields.db_import,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            amount_german="-584,49",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            transaction_date="29.12.2018",
            category_old="TestAka",
        )
        self.check_dict(
            result[1],
            amount_german="353,99",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            transaction_date="28.12.2018",
            category_old="TestAka",
        )
        self.check_dict(
            result[2],
            amount_german="504,48",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            transaction_date="27.12.2018",
            category_old="TestAka",
        )
        self.check_dict(
            result[3],
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            transaction_date="26.12.2018",
            category_old="Mitgliedsbeitrag",
        )
        self.check_dict(
            result[4],
            amount_german="5,00",
            cdedbid="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            transaction_date="25.12.2018",
            category_old="Mitgliedsbeitrag",
        )
        self.check_dict(
            result[5],
            amount_german="2,50",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            transaction_date="24.12.2018",
            category_old="Mitgliedsbeitrag",
        )
        self.check_dict(
            result[6],
            amount_german="2,50",
            cdedbid="DB-4-3",
            family_name="Dino",
            given_names="Daniel D.",
            transaction_date="23.12.2018",
            category_old="Mitgliedsbeitrag",
        )
        self.check_dict(
            result[7],
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            transaction_date="21.12.2018",
            category_old="Mitgliedsbeitrag",
        )
        self.check_dict(
            result[8],
            amount_german="466,49",
            cdedbid="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            transaction_date="20.12.2018",
            category_old="TestAka",
        )

        # check transactions files
        # check account 00
        self.csv_submit(f, button="excel", value=str(Accounts.Account0))
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.ExportFields.excel,
                                     dialect=CustomCSVDialect))
        self.check_dict(
            result[0],
            transaction_date="26.12.2018",
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Mitgliedsbeitrag",
            account_nr="8068900",
        )
        self.check_dict(
            result[1],
            transaction_date="25.12.2018",
            amount_german="5,00",
            cdedbid="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            category_old="Mitgliedsbeitrag",
            account_nr="8068900",
        )
        self.check_dict(
            result[2],
            transaction_date="24.12.2018",
            amount_german="2,50",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category_old="Mitgliedsbeitrag",
            account_nr="8068900",
        )
        self.check_dict(
            result[3],
            transaction_date="23.12.2018",
            amount_german="2,50",
            cdedbid="DB-4-3",
            family_name="Dino",
            given_names="Daniel D.",
            category_old="Mitgliedsbeitrag",
            account_nr="8068900",
            reference="Mitgliedsbeitrag",
            account_holder="Daniel Dino",
        )
        self.check_dict(
            result[4],
            transaction_date="22.12.2018",
            amount_german="50,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Sonstiges",
            account_nr="8068900",
            reference="Anton Administrator DB-1-9 Spende",
        )
        self.check_dict(
            result[5],
            transaction_date="21.12.2018",
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Mitgliedsbeitrag",
            account_nr="8068900",
        )
        self.check_dict(
            result[6],
            transaction_date="20.12.2018",
            amount_german="466,49",
            cdedbid="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            category_old="TestAka",
            account_nr="8068900",
        )
        self.check_dict(
            result[7],
            transaction_date="19.12.2018",
            amount_german="1234,50",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Sonstiges",
            account_nr="8068900",
        )

        # check account 01
        self.csv_submit(f, button="excel", value=str(Accounts.Account1))
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.ExportFields.excel,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            transaction_date="31.12.2018",
            amount_german="-18,54",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Sonstiges",
            account_nr="8068901",
            In_reference="Genutzte Freiposten",
        )
        self.check_dict(
            result[1],
            transaction_date="30.12.2018",
            amount_german="-52,50",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Sonstiges",
            account_nr="8068901",
            reference="KONTOFUEHRUNGSGEBUEHREN",
        )
        self.check_dict(
            result[2],
            transaction_date="29.12.2018",
            amount_german="-584,49",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="TestAka",
            account_nr="8068901",
            account_holder="Anton Administrator",
            In_reference="KL-Erstattung TestAka, Anton Armin A. Administrator (DB-1-9)",
        )
        self.check_dict(
            result[3],
            transaction_date="28.12.2018",
            amount_german="353,99",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="TestAka",
            account_nr="8068901",
        )
        self.check_dict(
            result[4],
            transaction_date="27.12.2018",
            amount_german="504,48",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category_old="TestAka",
            account_nr="8068901",
        )
