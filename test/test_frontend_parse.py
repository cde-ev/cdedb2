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
                                     delimiter=";",
                                     fieldnames=EVENT_FEE_FIELDS))

        self.assertEqual("584.49", result[0]["amount_export"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["family_name"])
        self.assertEqual("Anton Armin A.", result[0]["given_names"])
        self.assertEqual("28.12.2018", result[0]["date"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["type_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["member_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[0]["event_confidence"])

        self.assertEqual("584.49", result[1]["amount_export"])
        self.assertEqual("DB-7-8", result[1]["db_id"])
        self.assertEqual("Generalis", result[1]["family_name"])
        self.assertEqual("Garcia G.", result[1]["given_names"])
        self.assertEqual("27.12.2018", result[1]["date"])
        self.assertEqual("ConfidenceLevel.High", result[1]["type_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[1]["member_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[1]["event_confidence"])

        self.assertEqual("100.00", result[2]["amount_export"])
        self.assertEqual("DB-5-1", result[2]["db_id"])
        self.assertEqual("Eventis", result[2]["family_name"])
        self.assertEqual("Emilia E.", result[2]["given_names"])
        self.assertEqual("20.12.2018", result[2]["date"])
        self.assertEqual("ConfidenceLevel.Medium", result[2]["type_confidence"])
        self.assertEqual("ConfidenceLevel.Full", result[2]["member_confidence"])
        self.assertEqual("ConfidenceLevel.High", result[2]["event_confidence"])

        # check Testakademie file
        f = save.forms["Große_Testakademie_2222"]
        self.submit(f, check_notification=False)
        # Should be equal to event_fees.csv
        self.assertEqual(list(csv.DictReader(self.response.text.split("\n"),
                                             delimiter=";",
                                             fieldnames=EVENT_FEE_FIELDS)),
                         result)

        # check membership_fees.csv
        f = save.forms["membership_fees"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=MEMBERSHIP_FEE_FIELDS))

        self.assertEqual("DB-2-7", result[0]["db_id"])
        self.assertEqual("Beispiel", result[0]["family_name"])
        self.assertEqual("Bertålotta", result[0]["given_names"])
        self.assertEqual("5.00", result[0]["amount_export"])
        self.assertEqual("25.12.2018", result[0]["date"])
        self.assertNotIn("not found in", result[0]["problems"])

        self.assertEqual("DB-7-8", result[1]["db_id"])
        self.assertEqual("Generalis", result[1]["family_name"])
        self.assertEqual("Garcia G.", result[1]["given_names"])
        self.assertEqual("2.50", result[1]["amount_export"])
        self.assertEqual("24.12.2018", result[1]["date"])
        self.assertIn("not found in", result[1]["problems"])

        # check other_transactions
        f = save.forms["other_transactions"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";"))

        self.assertEqual("8068900", result[0]["account"])
        self.assertEqual("26.12.2018", result[0]["date"])
        self.assertEqual("10.00", result[0]["amount_export"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["family_name"])
        self.assertEqual("Anton Armin A.", result[0]["given_names"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertIn("not found in", result[0]["problems"])

        self.assertEqual("8068900", result[1]["account"])
        self.assertEqual("23.12.2018", result[1]["date"])
        self.assertEqual("2.50", result[1]["amount_export"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[1]["db_id"])
        self.assertEqual(STATEMENT_FAMILY_NAME_UNKNOWN,
                         result[1]["family_name"])
        self.assertEqual(STATEMENT_GIVEN_NAMES_UNKNOWN,
                         result[1]["given_names"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertIn("No DB-ID found.", result[1]["problems"])

        self.assertEqual("8068900", result[2]["account"])
        self.assertEqual("21.12.2018", result[2]["date"])
        self.assertEqual("10.00", result[2]["amount_export"])
        self.assertEqual("Mitgliedsbeitrag für Anton Armin A. Administrator "
                         "DB-1-9 und Bertalotta Beispiel DB-2.7",
                         result[2]["reference"])
        self.assertEqual("Anton & Berta", result[2]["account_holder"])
        self.assertEqual("Mitgliedsbeitrag", result[2]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[2]["type_confidence"])
        self.assertIn("reference: Multiple (2) DB-IDs found in line 11!",
                      result[2]["problems"])

        self.assertEqual("8068901", result[3]["account"])
        self.assertEqual("31.12.2018", result[3]["date"])
        self.assertEqual("-18.54", result[3]["amount_export"])
        self.assertIn("Genutzte Freiposten", result[3]["reference"])
        self.assertEqual("", result[3]["account_holder"])
        self.assertEqual("Sonstiges", result[3]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[3]["type_confidence"])
        self.assertEqual("", result[3]["problems"])

        self.assertEqual("8068901", result[4]["account"])
        self.assertEqual("30.12.2018", result[4]["date"])
        self.assertEqual("-52.50", result[4]["amount_export"])
        self.assertEqual("KONTOFUEHRUNGSGEBUEHREN", result[4]["reference"])
        self.assertEqual("", result[4]["account_holder"])
        self.assertEqual("Sonstiges", result[4]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[4]["type_confidence"])
        self.assertEqual("", result[4]["problems"])

        self.assertEqual("8068900", result[5]["account"])
        self.assertEqual("22.12.2018", result[5]["date"])
        self.assertEqual("50.00", result[5]["amount_export"])
        self.assertEqual("Anton Armin A. Administrator DB-1-9 Spende",
                         result[5]["reference"])
        self.assertEqual("Anton", result[5]["account_holder"])
        self.assertEqual("Sonstiges", result[5]["category"])
        self.assertEqual("ConfidenceLevel.Full", result[5]["type_confidence"])
        self.assertEqual("", result[5]["problems"])

        # check transactions files
        # check account 00
        f = save.forms["transactions_8068900"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=ACCOUNT_FIELDS))

        self.assertEqual("26.12.2018", result[0]["date"])
        self.assertEqual("10,00", result[0]["amount"])
        self.assertEqual("DB-1-9", result[0]["db_id"])
        self.assertEqual("Administrator", result[0]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[0]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[0]["category"])
        self.assertEqual("8068900", result[0]["account"])

        self.assertEqual("25.12.2018", result[1]["date"])
        self.assertEqual("5,00", result[1]["amount"])
        self.assertEqual("DB-2-7", result[1]["db_id"])
        self.assertEqual("Beispiel", result[1]["name_or_holder"])
        self.assertEqual("Bertålotta", result[1]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[1]["category"])
        self.assertEqual("8068900", result[1]["account"])

        self.assertEqual("24.12.2018", result[2]["date"])
        self.assertEqual("2,50", result[2]["amount"])
        self.assertEqual("DB-7-8", result[2]["db_id"])
        self.assertEqual("Generalis", result[2]["name_or_holder"])
        self.assertEqual("Garcia G.", result[2]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[2]["category"])
        self.assertEqual("8068900", result[2]["account"])

        self.assertEqual("23.12.2018", result[3]["date"])
        self.assertEqual("2,50", result[3]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[3]["db_id"])
        self.assertEqual("Daniel Dino", result[3]["name_or_holder"])
        self.assertEqual("Mitgliedsbeitrag", result[3]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[3]["category"])
        self.assertEqual("8068900", result[3]["account"])

        self.assertEqual("22.12.2018", result[4]["date"])
        self.assertEqual("50,00", result[4]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[4]["db_id"])
        self.assertEqual("Anton", result[4]["name_or_holder"])
        self.assertEqual("Anton Armin A. Administrator DB-1-9 Spende",
                         result[4]["name_or_ref"])
        self.assertEqual("Sonstiges", result[4]["category"])
        self.assertEqual("8068900", result[4]["account"])

        self.assertEqual("21.12.2018", result[5]["date"])
        self.assertEqual("10,00", result[5]["amount"])
        self.assertEqual("DB-1-9", result[5]["db_id"])
        self.assertEqual("Administrator", result[5]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[5]["name_or_ref"])
        self.assertEqual("Mitgliedsbeitrag", result[5]["category"])
        self.assertEqual("8068900", result[5]["account"])

        self.assertEqual("20.12.2018", result[6]["date"])
        self.assertEqual("100,00", result[6]["amount"])
        self.assertEqual("DB-5-1", result[6]["db_id"])
        self.assertEqual("Eventis", result[6]["name_or_holder"])
        self.assertEqual("Emilia E.", result[6]["name_or_ref"])
        self.assertEqual("TestAka", result[6]["category"])
        self.assertEqual("8068900", result[6]["account"])

        # check account 01
        f = save.forms["transactions_8068901"]
        self.submit(f, check_notification=False)
        result = list(csv.DictReader(self.response.text.split("\n"),
                                     delimiter=";",
                                     fieldnames=ACCOUNT_FIELDS))

        self.assertEqual("31.12.2018", result[0]["date"])
        self.assertEqual("-18,54", result[0]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[0]["db_id"])
        self.assertEqual("", result[0]["name_or_holder"])
        self.assertIn("Genutzte Freiposten", result[0]["name_or_ref"])
        self.assertEqual("Sonstiges", result[0]["category"])
        self.assertEqual("8068901", result[0]["account"])

        self.assertEqual("30.12.2018", result[1]["date"])
        self.assertEqual("-52,50", result[1]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[1]["db_id"])
        self.assertEqual("", result[1]["name_or_holder"])
        self.assertEqual("KONTOFUEHRUNGSGEBUEHREN", result[1]["name_or_ref"])
        self.assertEqual("Sonstiges", result[1]["category"])
        self.assertEqual("8068901", result[1]["account"])

        self.assertEqual("29.12.2018", result[2]["date"])
        self.assertEqual("-584,49", result[2]["amount"])
        self.assertEqual(STATEMENT_DB_ID_UNKNOWN, result[2]["db_id"])
        self.assertEqual("Anton Administrator", result[2]["name_or_holder"])
        self.assertEqual("Kursleitererstattung Anton Armin A. Administrator "
                         "Große Testakademie 2222", result[2]["name_or_ref"])
        self.assertEqual("TestAka", result[2]["category"])
        self.assertEqual("8068901", result[2]["account"])

        self.assertEqual("28.12.2018", result[3]["date"])
        self.assertEqual("584,49", result[3]["amount"])
        self.assertEqual("DB-1-9", result[3]["db_id"])
        self.assertEqual("Administrator", result[3]["name_or_holder"])
        self.assertEqual("Anton Armin A.", result[3]["name_or_ref"])
        self.assertEqual("TestAka", result[3]["category"])
        self.assertEqual("8068901", result[3]["account"])

        self.assertEqual("27.12.2018", result[4]["date"])
        self.assertEqual("584,49", result[4]["amount"])
        self.assertEqual("DB-7-8", result[4]["db_id"])
        self.assertEqual("Generalis", result[4]["name_or_holder"])
        self.assertEqual("Garcia G.", result[4]["name_or_ref"])
        self.assertEqual("TestAka", result[4]["category"])
        self.assertEqual("8068901", result[4]["account"])
