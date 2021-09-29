#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import copy
import datetime
import decimal
import unittest
from typing import Any, Dict, Iterable, List, Mapping, Tuple, Type, Union

import pytz

import cdedb.database.constants as const
import cdedb.validation as validate
from cdedb.common import ValidationWarning
from cdedb.validationtypes import (
    IBAN, JSON, Email, GenesisCase, PasswordStrength, Persona, Phone, PrintableASCII,
    PrintableASCIIType, SafeStr, StringType, Vote
)


class TestValidation(unittest.TestCase):
    def do_validator_test(
        self,
        type_: Type[Any],
        spec: Iterable[Tuple[Any, Any, Union[Type[Exception], Exception, None]]],
        extraparams: Mapping[str, Any] = None
    ) -> None:
        extraparams = extraparams or {}
        for inval, retval, exception in spec:
            with self.subTest(inval=inval):
                if not exception:
                    self.assertEqual(
                        validate.validate_check(type_, inval, **extraparams),
                        (retval, []),
                    )
                    self.assertEqual(
                        validate.validate_assert(type_, inval, **extraparams),
                        retval,
                    )
                else:
                    self.assertEqual(
                        None,
                        validate.validate_check(type_, inval, **extraparams)[0],
                    )
                    self.assertNotEqual(
                        [],
                        validate.validate_check(type_, inval, **extraparams)[1],
                    )
                    exception_args = None
                    if isinstance(exception, Exception):
                        exception_args = exception.args
                        exception = type(exception)
                    with self.assertRaises(exception) as cm:
                        validate.validate_assert(type_, inval, **extraparams)
                    if exception_args:
                        self.assertEqual(cm.exception.args, exception_args)
                onepass = validate.validate_check(type_, inval, **extraparams)[0]
                twopass = validate.validate_check(type_, onepass, **extraparams)[0]
                self.assertEqual(onepass, twopass)

    def test_optional(self) -> None:
        self.assertEqual((12, []), validate.validate_check(int, 12))
        self.assertEqual(None, validate.validate_check(int, None)[0])
        self.assertLess(0, len(validate.validate_check(int, None)[1]))
        self.assertEqual(None, validate.validate_check(int, "garbage")[0])
        self.assertLess(0, len(validate.validate_check(int, "garbage")[1]))
        self.assertEqual((12, []), validate.validate_check(int, "12"))
        self.assertEqual((12, []), validate.validate_check_optional(int, 12))
        self.assertEqual((None, []), validate.validate_check_optional(int, None))
        self.assertEqual((12, []), validate.validate_check_optional(int, "12"))
        self.assertEqual(None, validate.validate_check_optional(int, "garbage")[0])
        self.assertLess(0, len(validate.validate_check_optional(int, "garbage")[1]))

        self.assertEqual(12, validate.validate_assert(int, 12))
        with self.assertRaises(TypeError):
            validate.validate_assert(int, None)
        with self.assertRaises(ValueError):
            validate.validate_assert(int, "garbage")
        self.assertEqual(12, validate.validate_assert(int, "12"))
        self.assertEqual(12, validate.validate_assert_optional(int, 12))
        self.assertEqual(None, validate.validate_assert_optional(int, None))
        self.assertEqual(12, validate.validate_assert_optional(int, "12"))
        with self.assertRaises(ValueError):
            validate.validate_assert_optional(int, "garbage")

    def test_int(self) -> None:
        self.do_validator_test(int, (
            (0, 0, None),
            (12, 12, None),
            (None, None, TypeError),
            ("-12", -12, None),
            ("12.3", None, ValueError),
            ("garbage", None, ValueError),
            (12.0, 12, None),
            (12.5, None, ValueError),
            (True, 1, None),
            (False, 0, None),
            (2147483647, 2147483647, None),
            (1e10, None, ValueError),
        ))

    def test_float(self) -> None:
        self.do_validator_test(float, (
            (0.0, 0.0, None),
            (12.3, 12.3, None),
            (None, None, ValueError),
            ("12", 12.0, None),
            ("-12.3", -12.3, None),
            ("garbage", None, ValueError),
            (12, 12.0, None),
            (9e6, 9e6, None),
            (1e7, None, ValueError),
        ))

    def test_decimal(self) -> None:
        self.do_validator_test(decimal.Decimal, (
            (decimal.Decimal(0), decimal.Decimal(0), None),
            (decimal.Decimal(12.3), decimal.Decimal(12.3), None),
            (None, None, TypeError),
            ("12", decimal.Decimal((0, (1, 2), 0)), None),
            ("-12.3", decimal.Decimal((1, (1, 2, 3), -1)), None),
            ("garbage", None, ValueError),
            (12, None, TypeError),
            (12.3, None, TypeError),
        ))

    def test_str_type(self) -> None:
        self.do_validator_test(StringType, (
            ("a string", "a string", None),
            ("with stuff äößł€ ", "with stuff äößł€ ", None),
            ("", "", None),
            (54, "54", None),
            ("multiple\r\nlines\rof\ntext", "multiple\nlines\nof\ntext", None),
        ))
        self.do_validator_test(StringType, (
            ("a string", "a stig", None),
        ), extraparams={'zap': 'rn'})
        self.do_validator_test(StringType, (
            ("a string", "a sti", None),
        ), extraparams={'sieve': ' aist'})

    def test_str(self) -> None:
        self.do_validator_test(str, (
            ("a string", "a string", None),
            ("string with stuff äößł€", "string with stuff äößł€", None),
            ("", "", ValueError),
            (54, "54", None),
            ("multiple\r\nlines\rof\ntext", "multiple\nlines\nof\ntext", None),
        ))

    def test_mapping(self) -> None:
        self.do_validator_test(Mapping, (
            ({"a": "dict"}, {"a": "dict"}, None),
            ("something else", "", TypeError),
        ))

    def test_bool(self) -> None:
        self.do_validator_test(bool, (
            (True, True, None),
            (False, False, None),
            ("a string", True, None),
            ("", False, None),
            ("True", True, None),
            ("False", False, None),
            (54, True, None),
        ))

    def test_printable_ascii_type(self) -> None:
        self.do_validator_test(PrintableASCIIType, (
            ("a string", "a string", None),
            ("string with stuff äößł€", None, ValueError),
            ("", "", None),
            (54, "54", None),
        ))

    def test_printable_ascii(self) -> None:
        self.do_validator_test(PrintableASCII, (
            ("a string", "a string", None),
            ("string with stuff äößł€", None, ValueError),
            ("", "", ValueError),
            (54, "54", None),
        ))

    def test_password_strength(self) -> None:
        self.do_validator_test(PasswordStrength, (
            ("Secure String 0#", "Secure String 0#", None),
            ("short", None, ValueError),
            ("insecure", None, ValueError),
            ("", "", ValueError),
        ))

    def test_email(self) -> None:
        self.do_validator_test(Email, (
            ("address@domain.tld", "address@domain.tld", None),
            ("eXtRaS_-4+@DomAin.tld", "extras_-4+@domain.tld", None),
            ("other@mailer.berlin", "other@mailer.berlin", None),
            ("äddress@domain.tld", None, ValueError),
            ("address@domain", None, ValueError),
            ("address_at_domain.tld", None, ValueError),
            ("a@ddress@domain.tld", None, ValueError),
        ))

    def test_persona_data(self) -> None:
        base_example = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "given_names": "Blübb",
            "family_name": "the First",
            "is_active": True,
            "is_ml_realm": False,
            "notes": None,
        }
        stripped_example = {"id": 42}
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        password_example = copy.deepcopy(base_example)
        password_example["password_hash"] = "something"
        value_example = copy.deepcopy(base_example)
        value_example["username"] = "garbage"
        self.do_validator_test(Persona, (
            (base_example, base_example, None),
            (stripped_example, stripped_example, None),
            (key_example, key_example, KeyError),
            (password_example, password_example, KeyError),
            (value_example, value_example, ValueError),
        ))

    def test_date(self) -> None:
        now = datetime.datetime.now()
        self.do_validator_test(datetime.date, (
            (now.date(), now.date(), None),
            (now, now.date(), None),
            ("2014-04-2", datetime.date(2014, 4, 2), None),
            ("01.02.2014", datetime.date(2014, 2, 1), None),
            ("2014-04-02T20:48:25.808240+00:00", datetime.date(2014, 4, 2), None),
            # the following fails with inconsistent exception type
            # TypeError on Gentoo
            # ValueError on Debian
            # ("more garbage", None, TypeError),
        ))

    def test_datetime(self) -> None:
        now = datetime.datetime.now()
        now_aware = datetime.datetime.now(pytz.utc)
        now_other = pytz.timezone('America/New_York').localize(now)
        self.do_validator_test(datetime.datetime, (
            (now, now, None),
            (now_aware, now_aware, None),
            (now_other, now_other, None),
            (now.date(), None, TypeError),
            ("2014-04-20",
             datetime.datetime(2014, 4, 19, 22, 0, 0,
                               tzinfo=pytz.utc), None),
            ("2014-04-02 21:53",
             datetime.datetime(2014, 4, 2, 19, 53, 0,
                               tzinfo=pytz.utc), None),
            ("01.02.2014 21:53",
             datetime.datetime(2014, 2, 1, 20, 53, 0,
                               tzinfo=pytz.utc), None),
            ("21:53", None, ValueError),
            ("2014-04-02T20:48:25.808240+00:00",
             datetime.datetime(2014, 4, 2, 20, 48, 25, 808240,
                               tzinfo=pytz.utc), None),
            ("2014-04-02T20:48:25.808240+03:00",
             datetime.datetime(2014, 4, 2, 17, 48, 25, 808240,
                               tzinfo=pytz.utc), None),
            # see above
            # ("more garbage", None, TypeError),
        ))
        self.do_validator_test(datetime.datetime, (
            (now, now, None),
            (now_aware, now_aware, None),
            (now_other, now_other, None),
            (now.date(), None, TypeError),
            ("2014-04-20",
             datetime.datetime(2014, 4, 19, 22, 0, 0,
                               tzinfo=pytz.utc), None),
            ("2014-04-20 21:53",
             datetime.datetime(2014, 4, 20, 19, 53, 0,
                               tzinfo=pytz.utc), None),
            ("01.02.2014 21:53",
             datetime.datetime(2014, 2, 1, 20, 53, 0,
                               tzinfo=pytz.utc), None),
            ("21:53",
             datetime.datetime(2000, 5, 23, 19, 53, 0,
                               tzinfo=pytz.utc), None),
            ("2014-04-20T20:48:25.808240+00:00",
             datetime.datetime(2014, 4, 20, 20, 48, 25, 808240,
                               tzinfo=pytz.utc), None),
            ("2014-04-20T20:48:25.808240+03:00",
             datetime.datetime(2014, 4, 20, 17, 48, 25, 808240,
                               tzinfo=pytz.utc), None),
            # see above
            # ("more garbage", None, TypeError),
        ), extraparams={'default_date': datetime.date(2000, 5, 23)})

    def test_phone(self) -> None:
        self.do_validator_test(Phone, (
            ("+49 (3641) 12345", "+49 (3641) 12345", None),
            ("0049364112345", "+49 (3641) 12345", None),
            ("03641/12345", "+49 (3641) 12345", None),
            ("+500 (1111) 54321", "+500 (1111) 54321", None),
            ("+500-1111/54321", "+500 (1111) 54321", None),
            ("+500/1111/54321", "+500 (1111) 54321", None),
            ("00500__1111__54321", "+500 (1111) 54321", None),
            ("+5001111-54321", "+500 (1111) 54321", None),
            ("00500111154321", "+500 111154321", None),
            ("+49 (36460) 12345", None, ValueError),
            ("12345", None, ValueError),
            ("+210 (12390) 12345", None, ValueError),
        ))

    def test_member_data(self) -> None:
        base_example: Dict[str, Any] = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "is_active": True,
            "is_cde_realm": True,
            "family_name": "Thør",
            "given_names": "Blubberwing",
            "title": "Sir",
            "name_supplement": "of Łord",
            "gender": 1,
            "birthday": datetime.date(1984, 5, 25),
            "telephone": "+49 (3641) 12345",
            "mobile": "+49 (175) 12345",
            "address_supplement": "unterm Schrank",
            "address": "Weg 23",
            "postal_code": "07743",
            "location": "Eine Stadt",
            "country": "DE",
            "notes": "A note",
            "birth_name": "Yggdrasil",
            "address_supplement2": "über der Treppe",
            "address2": "Straße 66",
            "postal_code2": "2XM 44",
            "location2": "Wolke",
            "country2": "VA",
            "weblink": "http://www.example.cde",
            "specialisation": "Blurb",
            "affiliation": "More blurb",
            "timeline": "Even more blurb",
            "interests": "Still more blurb",
            "free_form": "And yet another blurb",
            "balance": decimal.Decimal("10.77"),
            "decided_search": True,
            "trial_member": False,
            "bub_search": True,
        }
        stripped_example = {"id": 42}
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        value_example = copy.deepcopy(base_example)
        value_example["postal_code"] = "07742"
        convert_example = copy.deepcopy(base_example)
        convert_example["birthday"] = base_example["birthday"].isoformat()
        self.do_validator_test(Persona, (
            (base_example, base_example, None),
            (convert_example, base_example, None),
            (stripped_example, stripped_example, None),
            (key_example, key_example, KeyError),
            (value_example, value_example, ValidationWarning),
        ))

    def test_event_user_data(self) -> None:
        base_example: Dict[str, Any] = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "is_active": True,
            "is_event_realm": True,
            "is_cde_realm": False,
            "family_name": "Thør",
            "given_names": "Blubberwing",
            "title": "Sir",
            "name_supplement": "of Łord",
            "gender": 1,
            "birthday": datetime.date(1984, 5, 25),
            "telephone": "+49 (3641) 12345",
            "mobile": "+49 (175) 12345",
            "address_supplement": "unterm Schrank",
            "address": "Weg 23",
            "postal_code": "07743",
            "location": "Eine Stadt",
            "country": "DE",
            "notes": "A note",
        }
        stripped_example = {"id": 42}
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        value_example = copy.deepcopy(base_example)
        value_example["postal_code"] = "07742"
        convert_example = copy.deepcopy(base_example)
        convert_example["birthday"] = base_example["birthday"].isoformat()
        self.do_validator_test(Persona, (
            (base_example, base_example, None),
            (convert_example, base_example, None),
            (stripped_example, stripped_example, None),
            (key_example, None, KeyError),
            (value_example, None, ValidationWarning),
        ))

    def test_enum_validators(self) -> None:
        stati = const.RegistrationPartStati
        self.do_validator_test(const.RegistrationPartStati, (
            (stati.participant, stati.participant, None),
            (2, stati.participant, None),
            ("2", stati.participant, None),
            (-2, None, ValueError),
            ("alorecuh", None, ValueError),
        ))

    def test_vote(self) -> None:
        ballot: Dict[str, Any] = {
            'votes': None,
            'use_bar': True,
            'candidates': {
                1: {'shortname': 'A'},
                2: {'shortname': 'B'},
                3: {'shortname': 'C'},
                4: {'shortname': 'D'},
                5: {'shortname': 'E'},
            }
        }
        classical_ballot = copy.deepcopy(ballot)
        classical_ballot['votes'] = 2
        self.do_validator_test(Vote, (
            ("A>B>C=D>E>_bar_", "A>B>C=D>E>_bar_", None),
            ("_bar_=B>E=C=D>A", "_bar_=B>E=C=D>A", None),
            ("_bar_=B>F=C=D>A", None, KeyError),
            ("", None, ValueError),
            ("_bar_=B<E=C=D<A", None, KeyError),
            ("_bar_=B>E=C>A", None, KeyError),
            ("_bar_=B>E=C>A>F=D", None, KeyError),
            ("=>=>>=", None, KeyError),
        ), extraparams={'ballot': ballot})
        self.do_validator_test(Vote, (
            ("A=B>C=D=E=_bar_", "A=B>C=D=E=_bar_", None),
            ("A>B=C=D=E=_bar_", "A>B=C=D=E=_bar_", None),
            ("_bar_>A=B=C=D=E", "_bar_>A=B=C=D=E", None),
            ("_bar_=A=B=C=D=E", "_bar_=A=B=C=D=E", None),
            ("E=C>A=D=B=_bar_", "E=C>A=D=B=_bar_", None),
            ("A=B=C>_bar_>D=E", None, ValueError),
            ("A>B>_bar_=C=D=E", None, ValueError),
            ("A=_bar_>B=C=D=E", None, ValueError),
            ("A>_bar_>B=C=D>E", None, ValueError),
            ("_bar_>A=B=C=D>E", None, ValueError),
            ("A>B=C=D=E>_bar_", None, ValueError),
            ("E=C>A>_bar_=D=B", None, ValueError),
        ), extraparams={'ballot': classical_ballot})

    def test_iban(self) -> None:
        self.do_validator_test(IBAN, (
            ("DE75512108001245126199", "DE75512108001245126199", None),
            ("DE75 5121 0800 1245 1261 99", "DE75512108001245126199", None),
            ("IT60X0542811101000000123456", "IT60X0542811101000000123456", None),
            ("123", None, ValueError),  # Too short
            ("1234567890", None, ValueError),  # Missing Country Code
            ("DEFG1234567890", None, ValueError),  # Digits in checksum
            ("DE1234+-567890", None, ValueError),  # Invalid Characters
            ("XX75512108001245126199", None, ValueError),  # Wrong Country Code
            ("FR75512108001245126199", None, ValueError),  # Wrong length
            ("DE0651210800124512619", None, ValueError),  # Wrong length
            ("DE00512108001245126199", None, ValueError),  # Wrong Checksum
        ))

    def test_json(self) -> None:
        for input_, output, error in (
                ("42", 42, None),
                (b"42", 42, None),
                ('"42"', "42", None),
                (b'"42"', "42", None),
                ('{"foo": 1, "bar": "correct"}', {"foo": 1, "bar": "correct"}, None),
                (b'{"foo": 1, "bar": "correct"}', {"foo": 1, "bar": "correct"}, None),
                ("{'foo': 1, 'bar': 'correct'}", None, ValueError),
                (b"{'foo': 1, 'bar': 'correct'}", None, ValueError),
                ('{"open": 1', None, ValueError),
                (b'{"open": 1', None, ValueError),
                (b"\xff", None, ValueError)):
            with self.subTest(input=input_):
                result, errs = validate.validate_check(JSON, input_)
                self.assertEqual(output, result)
                if error is None:
                    self.assertFalse(errs)
                else:
                    for fieldname, e in errs:
                        self.assertIsInstance(e, error)

    def test_german_postal_code(self) -> None:
        for assertion in (Persona, GenesisCase):
            spec = (
                ({'id': 1, 'postal_code': "ABC", 'country': ""}, None, ValueError),
                ({'id': 1, 'postal_code': "ABC", 'country': None}, None, ValueError),
                ({'id': 1, 'postal_code': "ABC", 'country': "DE"}, None, ValueError),
                ({'id': 1, 'postal_code': "ABC"}, None, ValueError),
                ({'id': 1, 'postal_code': "11111"}, None, ValidationWarning),
                ({'id': 1, 'postal_code': "11111", 'country': "DE"},
                 None,
                 ValidationWarning),
                ({'id': 1, 'postal_code': "47239", 'country': "AQ"},
                 {'id': 1, 'postal_code': "47239", 'country': "AQ"},
                 None),
                ({'id': 1, 'postal_code': "47239", 'country': "DE"},
                 {'id': 1, 'postal_code': "47239", 'country': "DE"},
                 None),
                ({'id': 1, 'postal_code': "47239"},
                 {'id': 1, 'postal_code': "47239"},
                 None),
            )
            if assertion == GenesisCase:  # pylint: disable=comparison-with-callable
                for inv, outv, _ in spec:
                    inv['realm'] = "event"
                    if outv is not None:
                        outv['realm'] = "event"
            self.do_validator_test(assertion, spec, None)
            spec = (
                ({'id': 1, 'postal_code': "ABC", 'country': ""}, None, ValueError),
                ({'id': 1, 'postal_code': "ABC", 'country': None}, None, ValueError),
                ({'id': 1, 'postal_code': "ABCF", 'country': "DE"}, None, ValueError),
                ({'id': 1, 'postal_code': "ABC"}, None, ValueError),
                ({'id': 1, 'postal_code': "11111"},
                 {'id': 1, 'postal_code': "11111"},
                 None),
                ({'id': 1, 'postal_code': "11111", 'country': "DE"},
                 {'id': 1, 'postal_code': "11111", 'country': "DE"},
                 None),
                ({'id': 1, 'postal_code': "47239", 'country': "AQ"},
                 {'id': 1, 'postal_code': "47239", 'country': "AQ"},
                 None),
                ({'id': 1, 'postal_code': "47239", 'country': "DE"},
                 {'id': 1, 'postal_code': "47239", 'country': "DE"},
                 None),
                ({'id': 1, 'postal_code': "47239"},
                 {'id': 1, 'postal_code': "47239"},
                 None),
            )
            if assertion == GenesisCase:  # pylint: disable=comparison-with-callable
                for inv, outv, _ in spec:
                    inv['realm'] = "event"
                    if outv is not None:
                        outv['realm'] = "event"
            self.do_validator_test(assertion, spec, {'_ignore_warnings': True})

    def test_encoding(self) -> None:
        # Make sure decoding utf-8 as if it were utf-8-sig works.
        msg = "abc"
        self.assertEqual(msg, msg.encode('utf-8').decode('utf-8'))
        self.assertEqual(msg, msg.encode('utf-8').decode('utf-8-sig'))
        self.assertEqual("\ufeff" + msg, msg.encode('utf-8-sig').decode('utf-8'))
        self.assertEqual(msg, msg.encode('utf-8-sig').decode('utf-8-sig'))

    def test_safe_str(self) -> None:
        spec = [
            ("abc123 .,-+()/", "abc123 .,-+()/", None),
            ("", None, ValueError),
            (1, "1", None),
            ((1, 2, 3), "(1, 2, 3)", None),
            ("abc[]&def", None, ValueError(
                "Forbidden characters (%(chars)s). (None)", {"chars": "[]&"})),
        ]
        self.do_validator_test(SafeStr, spec)

    def test_generic_list(self) -> None:
        self.do_validator_test(List[int], [
            ([0, 1, 2, 3], [0, 1, 2, 3], None),
            ([0, 1.7, 2, 3], None, ValueError),
            ([0, "Test", 2, 3], None, ValueError),
            ([0, None, 2, 3], None, TypeError),
        ])
