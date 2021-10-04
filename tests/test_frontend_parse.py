#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import csv
import re
from datetime import datetime
from typing import Any

import webtest

import cdedb.frontend.parse_statement as parse
from cdedb.common import Accounts, CdEDBObject, now
from cdedb.frontend.common import CustomCSVDialect
from tests.common import FrontendTest, as_users, storage


class TestParseFrontend(FrontendTest):
    def csv_submit(self, form: webtest.Form, button: str = "", value: str = None
                   ) -> None:
        super().submit(form, button=button, value=value, check_notification=False)
        try:
            self.assertEqual(self.response.text[0], "\ufeff")
        except AssertionError:
            self.assertPresence("Erfolg", div="notifications")
        self.response.text = self.response.text[1:]

    def test_reference(self) -> None:
        raw_transaction = {
            "id": 0,
            "myAccNr": parse.Accounts.Account0.value,
            "statementDate": now().strftime(parse.STATEMENT_INPUT_DATEFORMAT),
            "amount": "5,00",
            "reference": "EREF+DB-1-9DB-2-7DB-43SVWZ+DB-2-7DB-35",
            "accHolder": "",
            "accHolder2": "",
            "IBAN": "",
            "BIC": "",
            "posting": "",
        }
        t = parse.Transaction.from_csv(raw_transaction)
        expectation = {
            1: parse.ConfidenceLevel.Low,
            2: parse.ConfidenceLevel.Medium,
            3: parse.ConfidenceLevel.Low,
            4: parse.ConfidenceLevel.Null,
        }
        self.assertEqual(expectation, t._find_cdedbids(parse.ConfidenceLevel.Full))  # pylint: disable=protected-access

    def test_parse_statement_additional(self) -> None:
        pseudo_winter = {"title": "CdE Pseudo-WinterAkademie",
                         "begin": datetime(2222, 12, 27),
                         "end": datetime(2223, 1, 6)}
        test_pfingsten = {"title": "CdE Pfingstakademie",
                          "begin": datetime(1234, 5, 20),
                          "end": datetime(1234, 5, 23)}
        naka = {"title": "NachhaltigkeitsAkademie 2019",
                "begin": datetime(2019, 3, 23),
                "end": datetime(2019, 3, 30)}
        velbert = {"title": "JuniorAkademie NRW - Nachtreffen Velbert 2019",
                   "begin": datetime(2019, 11, 15),
                   "end": datetime(2019, 11, 17)}

        pattern = re.compile(parse.get_event_name_pattern(pseudo_winter),
                             flags=re.IGNORECASE)

        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/2223"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/23"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademieXYZ"))
        self.assertTrue(pattern.search("Pseudo winter -Aka"))
        self.assertTrue(pattern.search("pseudo\twinter\naka\n"))

        pattern = re.compile(parse.get_event_name_pattern(test_pfingsten),
                             flags=re.IGNORECASE)
        self.assertTrue(pattern.search("PfingstAkademie 1234"))
        self.assertTrue(pattern.search("Pfingst Akademie 34"))

        pattern = re.compile(parse.get_event_name_pattern(naka),
                             flags=re.IGNORECASE)

        self.assertTrue(pattern.search("NAka 2019"))
        self.assertTrue(pattern.search("N Akademie 19"))
        self.assertTrue(pattern.search("NachhaltigkeitsAka 2019"))
        self.assertTrue(pattern.search("nachhaltigkeitsakademie"))

        p = re.compile(parse.get_event_name_pattern(velbert), flags=re.I)

        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 19"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW-Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("NRW - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie - Nachtreffen Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Velbert 2019"))
        self.assertTrue(p.search("JuniorAkademie NRW - Nachtreffen  2019"))
        self.assertTrue(p.search("JuniorAkademie 2019"))
        self.assertTrue(p.search("NRW 2019"))
        self.assertTrue(p.search("Nachtreffen 2019"))
        self.assertTrue(p.search("Velbert 2019"))
        self.assertTrue(p.search("JUNIORAKADDEMIENRW - NACHTREFFEN VELBERT2019"))
        self.assertTrue(p.search("JUNIOR A.AKADEMIE NRW NACHTREFF VELBERT 2019"))

    def check_dict(self, adict: CdEDBObject, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if "_" not in k:
                assertion, key = "", ""
            else:
                assertion, key = k.split("_", 1)
            if assertion == "In":
                self.assertIn(v, adict[key])
            elif assertion == "NotIn":
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
        self.assertPresence("1 Transaktionen mit Warnungen", div="has_warning_summary")
        self.assertPresence("9 fehlerfreie Transaktionen", div="has_none_summary")

        f = self.response.forms["parsedownloadform"]

        # Fix Transactions with errors.

        # Fix line 6:
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction6_errors")
        self.assertPresence(
            "given_names: (Anton Armin A.) nicht in (DB-1-9;DB-1-9) gefunden.",
            div="transaction6_warnings")
        self.assertPresence(
            "family_name: (Administrator) nicht in (DB-1-9;DB-1-9) gefunden.",
            div="transaction6_warnings")
        self.assertEqual(f["cdedbid6"].value, "DB-1-9")
        f["persona_id_confirm6"].checked = True

        # Fix line 9:
        self.assertPresence("cdedbid: Braucht Mitgliedszuordnung.",
                            div="transaction9_errors")
        self.assertEqual(f["account_holder9"].value, "Daniel Dino")
        f["cdedbid9"] = "DB-4-3"

        # Fix line 11:
        self.assertPresence("reference: Mehrere (2) DB-IDs in Zeile 11 gefunden.",
                            div="transaction11_errors")
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction11_errors")
        self.assertEqual(f["account_holder11"].value, "Anton & Berta")
        self.assertEqual(f["cdedbid11"].value, "DB-1-9")
        f["persona_id_confirm11"].checked = True

        # Check transactions with warnings.

        # Line 8:
        self.assertPresence(
            "given_names: (Garcia G.) nicht in (DB-7-8, Garci G."
            " Generalis;DB-6-8) gefunden.", div="transaction8_warnings")

        self.submit(f, button="validate", check_notification=False)

        self.assertTitle("Kontoauszug parsen")
        self.assertPresence("1 Transaktionen mit Fehlern", div="has_error_summary")
        self.assertNonPresence("Transaktionen mit Warnungen")
        self.assertPresence("12 fehlerfreie Transaktionen", div="has_none_summary")

        # Check new error:

        # Line 9:
        self.assertPresence("cdedbid: Unsicher über Mitgliedszuordnung.",
                            div="transaction9_errors")
        self.assertEqual(f["cdedbid9"].value, "DB-4-3")
        f["persona_id_confirm9"].checked = True

        self.submit(f, button="validate", check_notification=False)

        self.assertTitle("Kontoauszug parsen")
        self.assertNonPresence("Transaktionen mit Fehlern")
        self.assertNonPresence("Transaktionen mit Warnungen")
        self.assertPresence("13 fehlerfreie Transaktionen", div="has_none_summary")

        save = self.response
        f = save.forms["parsedownloadform"]

        # check Testakademie csv.

        # Make sure to use the correct submit button.
        self.csv_submit(f, button="event", value="1")
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.EVENT_EXPORT_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            amount="584.49",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            statement_date="28.12.2018",
            transaction_type_confidence_str="ConfidenceLevel.Full",
            persona_id_confidence_str="ConfidenceLevel.Full",
            event_id_confidence_str="ConfidenceLevel.Full",
        )
        self.check_dict(
            result[1],
            amount="584.49",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            statement_date="27.12.2018",
            transaction_type_confidence_str="ConfidenceLevel.Full",
            persona_id_confidence_str="ConfidenceLevel.High",
            event_id_confidence_str="ConfidenceLevel.High",
        )
        self.check_dict(
            result[2],
            amount="100.00",
            cdedbid="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            statement_date="20.12.2018",
            transaction_type_confidence_str="ConfidenceLevel.Full",
            persona_id_confidence_str="ConfidenceLevel.Full",
            event_id_confidence_str="ConfidenceLevel.High",
        )

        # check membership_fees.csv
        self.csv_submit(f, button="membership", value="membership")
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.MEMBERSHIP_EXPORT_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            amount="10.00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            statement_date="26.12.2018",
        )
        self.check_dict(
            result[1],
            amount="5.00",
            cdedbid="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            statement_date="25.12.2018",
        )
        self.check_dict(
            result[2],
            amount="2.50",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            statement_date="24.12.2018",
        )

        # check transactions files
        # check account 00
        self.csv_submit(f, button="excel", value=str(Accounts.Account0))
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.EXCEL_EXPORT_FIELDS,
                                     dialect=CustomCSVDialect))
        self.check_dict(
            result[0],
            statement_date="26.12.2018",
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[1],
            statement_date="25.12.2018",
            amount_german="5,00",
            cdedbid="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            category_old="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[2],
            statement_date="24.12.2018",
            amount_german="2,50",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category_old="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[3],
            statement_date="23.12.2018",
            amount_german="2,50",
            cdedbid="DB-4-3",
            family_name="Dino",
            given_names="Daniel D.",
            category_old="Mitgliedsbeitrag",
            account="8068900",
            reference="Mitgliedsbeitrag",
            account_holder="Daniel Dino",
        )
        self.check_dict(
            result[4],
            statement_date="22.12.2018",
            amount_german="50,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Spende",
            account="8068900",
            reference="Anton Armin A. Administrator DB-1-9 Spende",
        )
        self.check_dict(
            result[5],
            statement_date="21.12.2018",
            amount_german="10,00",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[6],
            statement_date="20.12.2018",
            amount_german="100,00",
            cdedbid="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            category_old="TestAka",
            account="8068900",
        )
        self.check_dict(
            result[7],
            statement_date="19.12.2018",
            amount_german="1.234,50",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Spende",
            account="8068900",
        )

        # check account 01
        self.csv_submit(f, button="excel", value=str(Accounts.Account1))
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=parse.EXCEL_EXPORT_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            statement_date="31.12.2018",
            amount_german="-18,54",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Sonstiges",
            account="8068901",
            In_reference="Genutzte Freiposten",
        )
        self.check_dict(
            result[1],
            statement_date="30.12.2018",
            amount_german="-52,50",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="Sonstiges",
            account="8068901",
            reference="KONTOFUEHRUNGSGEBUEHREN",
        )
        self.check_dict(
            result[2],
            statement_date="29.12.2018",
            amount_german="-584,49",
            cdedbid="",
            family_name="",
            given_names="",
            category_old="TestAka",
            account="8068901",
            account_holder="Anton Administrator",
            In_reference="Kursleitererstattung Anton Armin A. Administrator",
        )
        self.check_dict(
            result[3],
            statement_date="28.12.2018",
            amount_german="584,49",
            cdedbid="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category_old="TestAka",
            account="8068901",
        )
        self.check_dict(
            result[4],
            statement_date="27.12.2018",
            amount_german="584,49",
            cdedbid="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category_old="TestAka",
            account="8068901",
        )
