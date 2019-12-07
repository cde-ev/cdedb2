import re
import csv

import sys

from test.common import as_users, USER_DICT, FrontendTest
from cdedb.common import now
from cdedb.frontend.parse_statement import (
    get_event_name_pattern, MEMBERSHIP_FEE_FIELDS, EVENT_FEE_FIELDS,
    OTHER_TRANSACTION_FIELDS, ACCOUNT_FIELDS, STATEMENT_DB_ID_UNKNOWN,
    STATEMENT_FAMILY_NAME_UNKNOWN, STATEMENT_GIVEN_NAMES_UNKNOWN,
    Transaction, TransactionType, Accounts, STATEMENT_INPUT_DATEFORMAT,
    ConfidenceLevel, STATEMENT_CSV_FIELDS, STATEMENT_CSV_RESTKEY)
from cdedb.frontend.common import CustomCSVDialect
from datetime import datetime


class TestParseFrontend(FrontendTest):

    def test_reference(self):
        transaction = {
            "id": 0,
            "myAccNr": Accounts.Account0.value,
            "statementDate": now().strftime(STATEMENT_INPUT_DATEFORMAT),
            "amount": "5,00",
            "reference": "EREF+DB-1-9DB-2-7DB-43SVWZ+DB-2-7DB-35",
            "accHolder": "",
            "accHolder2": "",
            "IBAN": "",
            "BIC": "",
            "posting": "",
        }
        t = Transaction(transaction)
        expectation = {
            1: ConfidenceLevel.Low,
            2: ConfidenceLevel.Medium,
            3: ConfidenceLevel.Low,
            4: ConfidenceLevel.Null,
        }
        self.assertEqual(expectation, t._find_cdedbids(ConfidenceLevel.Full))

    def test_parse_statement_additional(self):
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

        pattern = re.compile(get_event_name_pattern(pseudo_winter),
                             flags=re.IGNORECASE)

        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/2223"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademie 2222/23"))
        self.assertTrue(pattern.search("Pseudo-WinterAkademieXYZ"))
        self.assertTrue(pattern.search("Pseudo winter -Aka"))
        self.assertTrue(pattern.search("pseudo\twinter\naka\n"))

        pattern = re.compile(get_event_name_pattern(test_pfingsten),
                             flags=re.IGNORECASE)
        self.assertTrue(pattern.search("PfingstAkademie 1234"))
        self.assertTrue(pattern.search("Pfingst Akademie 34"))

        pattern = re.compile(get_event_name_pattern(naka),
                             flags=re.IGNORECASE)

        self.assertTrue(pattern.search("NAka 2019"))
        self.assertTrue(pattern.search("N Akademie 19"))
        self.assertTrue(pattern.search("NachhaltigkeitsAka 2019"))
        self.assertTrue(pattern.search("nachhaltigkeitsakademie"))

        p = re.compile(get_event_name_pattern(velbert), flags=re.I)

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

    def check_dict(self, adict, **kwargs):
        for k, v in kwargs.items():
            if "_" not in k:
                assertion = ""
            else:
                assertion, key = k.split("_", 1)
            if assertion == "In":
                self.assertIn(v, adict[key])
            elif assertion == "NotIn":
                self.assertNotIn(v, adict[key])
            else:
                self.assertEqual(v, adict[k])

    @as_users("anton")
    def test_parse_statement(self, user):
        self.get("/cde/parse")
        self.assertTitle("Kontoauszug parsen")
        f = self.response.forms["statementform"]
        with open("/cdedb2/test/ancillary_files/statement.csv") as statementfile:
            f["statement"] = statementfile.read()
        self.submit(f, check_notification=False, verbose=True)

        self.assertTitle("Kontoauszug parsen")
        self.assertPresence("3 Transaktionen für event_fees gefunden.")
        self.assertPresence("2 Transaktionen für membership_fees gefunden.")
        self.assertPresence("7 Transaktionen für other_transactions gefunden.")
        self.assertPresence("12 Transaktionen für transactions gefunden.")

        save = self.response

        # check event_fees.csv
        f = save.forms["event_fees"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=EVENT_FEE_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            amount_export="584.49",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            date="28.12.2018",
            type_confidence="ConfidenceLevel.Full",
            member_confidence="ConfidenceLevel.Full",
            event_confidence="ConfidenceLevel.Full"
        )
        self.check_dict(
            result[1],
            amount_export="584.49",
            db_id="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            date="27.12.2018",
            type_confidence="ConfidenceLevel.High",
            member_confidence="ConfidenceLevel.High",
            event_confidence="ConfidenceLevel.High",
        )
        self.check_dict(
            result[2],
            amount_export="100.00",
            db_id="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            date="20.12.2018",
            type_confidence="ConfidenceLevel.Medium",
            member_confidence="ConfidenceLevel.Full",
            event_confidence="ConfidenceLevel.High",
        )

        # check Testakademie file
        f = save.forms["Große_Testakademie_2222"]
        self.submit(f, check_notification=False)
        # Should be equal to event_fees.csv
        self.assertEqual(list(csv.DictReader(self.response.text.split("\n"),
                                             fieldnames=EVENT_FEE_FIELDS,
                                             dialect=CustomCSVDialect)),
                         result)

        # check membership_fees.csv
        f = save.forms["membership_fees"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=MEMBERSHIP_FEE_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            amount_export="5.00",
            db_id="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            date="25.12.2018",
            NotIn_problems="not found in",
        )
        self.check_dict(
            result[1],
            amount_export="2.50",
            db_id="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            date="24.12.2018",
            In_problems="not found in",
        )

        # check other_transactions
        f = save.forms["other_transactions"]
        self.submit(f, check_notification=False)
        # This csv file has a fieldnames line.
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            account="8068900",
            amount_export="10.00",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            date="26.12.2018",
            category="Mitgliedsbeitrag",
            In_problems="not found in",
        )
        self.check_dict(
            result[1],
            account="8068900",
            amount_export="2.50",
            db_id=STATEMENT_DB_ID_UNKNOWN,
            family_name="",
            given_names="",
            date="23.12.2018",
            category="Mitgliedsbeitrag",
            In_problems="No DB-ID found.",
        )
        self.check_dict(
            result[2],
            account="8068900",
            amount_export="10.00",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            date="21.12.2018",
            In_reference="Mitgliedsbeitrag für Anton Armin A. Administrator "
                         "DB-1-9 und Bertalotta Beispiel DB-2.7",
            account_holder="Anton & Berta",
            category="Mitgliedsbeitrag",
            type_confidence="ConfidenceLevel.Full",
            In_problems="reference: Multiple (2) DB-IDs found in line 11!",
        )
        self.check_dict(
            result[3],
            account="8068901",
            amount_export="-18.54",
            date="31.12.2018",
            In_reference="Genutzte Freiposten",
            category="Sonstiges",
            type_confidence="ConfidenceLevel.Full",
            problems="",
        )
        self.check_dict(
            result[4],
            account="8068901",
            amount_export="-52.50",
            date="30.12.2018",
            reference="KONTOFUEHRUNGSGEBUEHREN",
            category="Sonstiges",
            type_confidence="ConfidenceLevel.Full",
            problems="",
        )
        self.check_dict(
            result[5],
            account="8068900",
            amount_export="50.00",
            db_id="",
            date="22.12.2018",
            category="Sonstiges",
            type_confidence="ConfidenceLevel.Full",
            problems="",
        )

        # check transactions files
        # check account 00
        f = save.forms["transactions_8068900"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=ACCOUNT_FIELDS,
                                     dialect=CustomCSVDialect))
        self.check_dict(
            result[0],
            date="26.12.2018",
            amount="10,00",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[1],
            date="25.12.2018",
            amount="5,00",
            db_id="DB-2-7",
            family_name="Beispiel",
            given_names="Bertålotta",
            category="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[2],
            date="24.12.2018",
            amount="2,50",
            db_id="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[3],
            date="23.12.2018",
            amount="2,50",
            db_id=STATEMENT_DB_ID_UNKNOWN,
            family_name="",
            given_names="",
            category="Mitgliedsbeitrag",
            account="8068900",
            reference="Mitgliedsbeitrag",
            account_holder="Daniel Dino",
        )
        self.check_dict(
            result[4],
            date="22.12.2018",
            amount="50,00",
            db_id="",
            family_name="",
            given_names="",
            category="Sonstiges",
            account="8068900",
            reference="Anton Armin A. Administrator DB-1-9 Spende",
        )
        self.check_dict(
            result[5],
            date="21.12.2018",
            amount="10,00",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category="Mitgliedsbeitrag",
            account="8068900",
        )
        self.check_dict(
            result[6],
            date="20.12.2018",
            amount="100,00",
            db_id="DB-5-1",
            family_name="Eventis",
            given_names="Emilia E.",
            category="TestAka",
            account="8068900",
        )

        # check account 01
        f = save.forms["transactions_8068901"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     fieldnames=ACCOUNT_FIELDS,
                                     dialect=CustomCSVDialect))

        self.check_dict(
            result[0],
            date="31.12.2018",
            amount="-18,54",
            db_id="",
            family_name="",
            given_names="",
            category="Sonstiges",
            account="8068901",
            In_reference="Genutzte Freiposten",
        )
        self.check_dict(
            result[1],
            date="30.12.2018",
            amount="-52,50",
            db_id="",
            family_name="",
            given_names="",
            category="Sonstiges",
            account="8068901",
            reference="KONTOFUEHRUNGSGEBUEHREN",
        )
        self.check_dict(
            result[2],
            date="29.12.2018",
            amount="-584,49",
            db_id=STATEMENT_DB_ID_UNKNOWN,
            family_name="",
            given_names="",
            category="TestAka",
            account="8068901",
            account_holder="Anton Administrator",
            In_reference="Kursleitererstattung Anton Armin A. Administrator",
        )
        self.check_dict(
            result[3],
            date="28.12.2018",
            amount="584,49",
            db_id="DB-1-9",
            family_name="Administrator",
            given_names="Anton Armin A.",
            category="TestAka",
            account="8068901",
        )
        self.check_dict(
            result[4],
            date="27.12.2018",
            amount="584,49",
            db_id="DB-7-8",
            family_name="Generalis",
            given_names="Garcia G.",
            category="TestAka",
            account="8068901",
        )
