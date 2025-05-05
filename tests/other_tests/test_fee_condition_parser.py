import unittest
from datetime import date
from typing import Any

import pyparsing as pp

from cdedb.fee_condition_parser.evaluation import check, evaluate
from cdedb.fee_condition_parser.modifying import rename
from cdedb.fee_condition_parser.parsing import create_parser
from cdedb.fee_condition_parser.roundtrip import serialize


class ConditionParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = create_parser()

    FIELDS = {
        '1': True,
        'not': False,
        'long_field_name': True,
    }
    PARTS = {
        'part1': True,
        'part2-3': False,
        'not': False,
        'part{}': True,
        '🗷': False,
    }

    OTHER_VALUES = {
        'is_orga': True,
        'is_member': False,
        'any_part': True,
        'all_parts': False,
    }

    DATE = date(2023, 10, 1)
    BIRTHDAY = date(1990, 1, 1)

    CASES = [
        # Atoms
        (True, "True"),
        (True, "TRUE"),
        (True, "true"),
        (False, "False"),
        (False, "FALSE"),
        (False, "false"),
        # and, or, xor
        (False, "false And false"),
        (False, "true and false"),
        (False, "false and true"),
        (True, "true AND true"),
        (False, "false or false"),
        (True, "false Or true"),
        (True, "true OR false"),
        (True, "true OR true"),
        (False, "false Xor false"),
        (True, "false xOr true"),
        (True, "true XOR false"),
        (False, "true xor true"),
        # not
        (True, "not false"),
        (False, "NOT true"),
        # operator precedence
        (True, "False and False or True"),
        (True, "True or False and False"),
        (True, "False and False xor True"),
        (True, "True xor False and False"),
        (True, "True or False xor True"),
        (True, "True xor False or True"),
        (False, "not True and False"),
        (True, "not True xor True"),
        (True, "not False or True"),
        (False, "False or not True and False"),
        (True, "True and not True or True"),
        # parenthesis
        (False, "False and (False or True)"),
        (False, "(True or False) and False"),
        (False, "False and (False xor True)"),
        (False, "(True xor False) and False"),
        (False, "(True or False) xor True"),
        (False, "True xor (False or True)"),
        (True, "not (True and False)"),
        (True, "False or not (True and False)"),
        (False, "True and not (True or True)"),
        # more parenthesis
        (False, "(False and (False or True))"),
        (False, "(False and ((False or True)))"),
        (False, "((False) and (False or (True)))"),
        # parts
        (True, "part.part1"),
        (False, "part.part2-3"),
        (False, "part.not"),
        (True, "part.part{}"),
        (False, "part.🗷"),
        (True, "(part.part{})"),
        (True, "part.part{} and true"),
        (True, "true and part.part{}"),
        (False, "part.not xor not part.part{}"),
        # fields
        (True, "field.1"),
        (False, "field.not"),
        (True, "field.long_field_name"),
        (True, "(field.1)"),
        (True, "not field.not"),
        (False, "field.long_field_name and field.not"),
        # age
        (True, "U99"),
        (True, "u99"),
        (True, "U34"),
        (False, "U33"),
        (True, "U34 and not U33"),
        (False, "U40 and not U35"),
        (True, "field.1 and U34"),
        (False, "field.1 and U33"),
    ]

    AGE_SPECIAL_CASES: list[dict[str, Any]] = [
        dict(
            formula="U18",
            expectedResult=True,
            date=date(2025, 10, 9),
            birthday=date(2007, 10, 10),
        ),
        dict(
            formula="U18",
            expectedResult=False,
            date=date(2025, 10, 10),
            birthday=date(2007, 10, 10),
        ),
    ]

    def test_parse_evaluate_check(self) -> None:
        for expectedResult, formula in self.CASES:
            with self.subTest(formula=formula):
                parse_result = self.parser.parse_string(formula, parse_all=True)[0]
                check(parse_result, self.FIELDS.keys(), self.PARTS.keys())
                evaluation_result = evaluate(
                    parse_result,
                    data=dict(
                        field_values=self.FIELDS,
                        part_values=self.PARTS,
                        other_values=self.OTHER_VALUES,
                        reference_date=self.DATE,
                        birthday=self.BIRTHDAY,
                    ),
                )
                self.assertIs(evaluation_result, expectedResult)

    def test_age_special_cases(self) -> None:
        for case in self.AGE_SPECIAL_CASES:
            with self.subTest(formula=case['formula']):
                parse_result = self.parser.parse_string(case['formula'], parse_all=True)[0]
                check(parse_result, self.FIELDS.keys(), self.PARTS.keys())
                evaluation_result = evaluate(
                    parse_result,
                    data=dict(
                        field_values=self.FIELDS,
                        part_values=self.PARTS,
                        other_values=self.OTHER_VALUES,
                        reference_date=case['date'],
                        birthday=case['birthday'],
                    ),
                )
                self.assertIs(evaluation_result, case['expectedResult'])

    def test_roundtrip(self) -> None:
        for expectedResult, formula in self.CASES:
            with self.subTest(formula=formula):
                parse_result = self.parser.parse_string(formula, parse_all=True)[0]
                serialized = serialize(parse_result)
                # Test that serialization is stable (re-parse + re-serialize + check string equality)
                parse_result2 = self.parser.parse_string(serialized, parse_all=True)[0]
                serialized2 = serialize(parse_result2)
                self.assertEqual(serialized, serialized2)

                # Test that re-parsed formula still gives expected result
                evaluation_result = evaluate(
                    parse_result2,
                    data=dict(
                        field_values=self.FIELDS,
                        part_values=self.PARTS,
                        other_values=self.OTHER_VALUES,
                        reference_date=self.DATE,
                        birthday=self.BIRTHDAY,
                    ),
                )
                self.assertIs(evaluation_result, expectedResult)

    def test_roundtrip2(self) -> None:
        CASES2 = [
            ("PART.x and Part.y and       part.z", "part.x and part.y and part.z"),
            ("PART.x or (Part.y or part.z)", "part.x or part.y or part.z"),
            ("fieLd.x and Part.x or \nFIELD.y", "(field.x and part.x) or field.y"),
            ("(field.x and (true) or not false)", "(field.x and true) or not false"),
            ("not ((((true))) xor false)", "not (true xor false)"),
        ]
        for formula, expectedSerialized in CASES2:
            with self.subTest(formula=formula):
                parse_result = self.parser.parse_string(formula, parse_all=True)[0]
                serialized = serialize(parse_result)
                self.assertEqual(expectedSerialized, serialized)

    def test_check_errors(self) -> None:
        CASES3 = [
            ("part.part{-} and true", "Unknown part shortname(s): 'part{-}'"),
            ("part.not xor not part.{}", "Unknown part shortname(s): '{}'"),
            ("not ((field._))", "Unknown field(s): '_'"),
            ("part.long_field_name and field.not", "Unknown part shortname(s): 'long_field_name'"),
        ]
        for formula, expected_exception in CASES3:
            with self.subTest(formula=formula):
                parse_result = self.parser.parse_string(formula, parse_all=True)[0]
                with self.assertRaises(RuntimeError) as ctx:
                    check(parse_result, self.FIELDS.keys(), self.PARTS.keys())
                self.assertIn(expected_exception, str(ctx.exception))


class ErrorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = create_parser()

    CASES = [
        ("F", "Expected expression, found 'F'"),
        ("True and T", "Expected expression, found 'T'"),
        ("true a false", ""),  # current exception: "Expected end of text, found 'a'". Can we do better?
        ("not", "Expected expression, found end of text"),
        ("()", "Expected expression, found ')'"),
        ("field.", "Expected field name, found end of text"),
        ("field.x and field.", "Expected field name, found end of text"),
        ("field. and field.x", "Expected field name, found ' '"),
        ("part.", "Expected part shortname, found end of text"),
        ("part.x and part.", "Expected part shortname, found end of text"),
        ("(part.x and part.)", "Expected part shortname, found ')'"),
        ("part. and part.x", "Expected part shortname, found ' '"),
        ("(part.x and part.y", "Expected ')', found end of text"),
        ("(part.x and (True)", "Expected ')', found end of text"),
    ]

    def test_parse_errors(self) -> None:
        for formula, expected_exception in self.CASES:
            with self.subTest(formula=formula):
                with self.assertRaises(pp.ParseBaseException) as ctx:
                    self.parser.parse_string(formula, parse_all=True)
                self.assertIn(expected_exception, str(ctx.exception))


class ModificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = create_parser()

    def test_rename(self) -> None:
        formula = "(field.x and part.🗷) or not (field.___ xor true)"
        rename_fields = {'x': '___', '___': 'x'}
        rename_parts = {'🗷': 'foo'}
        expected_result = "(field.___ and part.foo) or not (field.x xor true)"

        result = self.parser.parse_string(formula, parse_all=True)[0]
        rename(result, rename_fields, rename_parts)
        serialized = serialize(result)
        self.assertEqual(expected_result, serialized)
