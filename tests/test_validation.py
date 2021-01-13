#!/usr/bin/env python3

import copy
import datetime
import decimal
import unittest

import pytz

import cdedb.database.constants as const
import cdedb.validation as validate
from cdedb.common import ValidationWarning


class TestValidation(unittest.TestCase):
    def do_validator_test(self, name, spec, extraparams=None):
        extraparams = extraparams or {}
        for inval, retval, exception, verifies in spec:
            with self.subTest(inval=inval):
                if not exception:
                    self.assertEqual((retval, []),
                                     getattr(validate, "check" + name)(
                                         inval, **extraparams))
                    self.assertEqual(retval,
                                     getattr(validate, "assert" + name)(
                                         inval, **extraparams))
                else:
                    self.assertEqual(None,
                                     getattr(validate, "check" + name)(
                                         inval, **extraparams)[0])
                    self.assertLess(0,
                                    len(getattr(validate, "check" + name)(
                                        inval, **extraparams)[1]))
                    exception_args = None
                    if isinstance(exception, Exception):
                        exception_args = exception.args
                        exception = type(exception)
                    with self.assertRaises(exception) as cm:
                        getattr(validate, "assert" +
                                name)(inval, **extraparams)
                    if exception_args:
                        self.assertEqual(cm.exception.args, exception_args)
                if verifies:
                    self.assertTrue(getattr(validate, "is" + name)(
                        inval, **extraparams))
                else:
                    self.assertFalse(getattr(validate, "is" + name)(
                        inval, **extraparams))
                onepass = getattr(validate, "check" + name)(
                    inval, **extraparams)[0]
                twopass = getattr(validate, "check" + name)(
                    onepass, **extraparams)[0]
                self.assertEqual(onepass, twopass)

    def test_or_None(self) -> None:
        self.assertTrue(validate.is_int(12))
        self.assertFalse(validate.is_int(None))
        self.assertFalse(validate.is_int("12"))
        self.assertFalse(validate.is_int("garbage"))
        self.assertTrue(validate.is_int_or_None(12))
        self.assertTrue(validate.is_int_or_None(None))
        self.assertFalse(validate.is_int_or_None("12"))
        self.assertFalse(validate.is_int_or_None("garbage"))

        self.assertEqual((12, []), validate.check_int(12))
        self.assertEqual(None, validate.check_int(None)[0])
        self.assertLess(0, len(validate.check_int(None)[1]))
        self.assertEqual(None, validate.check_int("garbage")[0])
        self.assertLess(0, len(validate.check_int("garbage")[1]))
        self.assertEqual((12, []), validate.check_int("12"))
        self.assertEqual((12, []), validate.check_int_or_None(12))
        self.assertEqual((None, []), validate.check_int_or_None(None))
        self.assertEqual((12, []), validate.check_int_or_None("12"))
        self.assertEqual(None, validate.check_int_or_None("garbage")[0])
        self.assertLess(0, len(validate.check_int_or_None("garbage")[1]))

        self.assertEqual(12, validate.assert_int(12))
        with self.assertRaises(TypeError):
            validate.assert_int(None)
        with self.assertRaises(ValueError):
            validate.assert_int("garbage")
        self.assertEqual(12, validate.assert_int("12"))
        self.assertEqual(12, validate.assert_int_or_None(12))
        self.assertEqual(None, validate.assert_int_or_None(None))
        self.assertEqual(12, validate.assert_int_or_None("12"))
        with self.assertRaises(ValueError):
            validate.assert_int_or_None("garbage")

    def test_int(self) -> None:
        self.do_validator_test("_int", (
            (0, 0, None, True),
            (12, 12, None, True),
            (None, None, TypeError, False),
            ("-12", -12, None, False),
            ("12.3", None, ValueError, False),
            ("garbage", None, ValueError, False),
            (12.0, 12, None, False),
            (12.5, None, ValueError, False),
            (True, 1, None, False),
            (False, 0, None, False),
            (2147483647, 2147483647, None, True),
            (1e10, None, ValueError, False),
        ))

    def test_bool_int(self) -> None:
        self.do_validator_test("_int", (
            (True, None, TypeError, False),
            (False, None, TypeError, False),
        ), {"_convert": False})

    def test_float(self) -> None:
        self.do_validator_test("_float", (
            (0.0, 0.0, None, True),
            (12.3, 12.3, None, True),
            (None, None, ValueError, False),
            ("12", 12.0, None, False),
            ("-12.3", -12.3, None, False),
            ("garbage", None, ValueError, False),
            (12, 12.0, None, False),
            (9e6, 9e6, None, True),
            (1e7, None, ValueError, False),
        ))

    def test_decimal(self) -> None:
        self.do_validator_test("_decimal", (
            (decimal.Decimal(0), decimal.Decimal(0), None, True),
            (decimal.Decimal(12.3), decimal.Decimal(12.3), None, True),
            (None, None, TypeError, False),
            ("12", decimal.Decimal((0, (1, 2), 0)), None, False),
            ("-12.3", decimal.Decimal((1, (1, 2, 3), -1)), None, False),
            ("garbage", None, ValueError, False),
            (12, None, TypeError, False),
            (12.3, None, TypeError, False),
        ))

    def test_str_type(self) -> None:
        self.do_validator_test("_str_type", (
            ("a string", "a string", None, True),
            ("with stuff äößł€ ", "with stuff äößł€ ", None, True),
            ("", "", None, True),
            (54, "54", None, False),
            ("multiple\r\nlines\rof\ntext", "multiple\nlines\nof\ntext", None, True),
        ))
        self.do_validator_test("_str_type", (
            ("a string", "a stig", None, True),
        ), extraparams={'zap': 'rn'})
        self.do_validator_test("_str_type", (
            ("a string", "a sti", None, True),
        ), extraparams={'sieve': ' aist'})

    def test_str(self) -> None:
        self.do_validator_test("_str", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", "string with stuff äößł€", None, True),
            ("", "", ValueError, False),
            (54, "54", None, False),
            ("multiple\r\nlines\rof\ntext", "multiple\nlines\nof\ntext", None, True),
        ))

    def test_mapping(self) -> None:
        self.do_validator_test("_mapping", (
            ({"a": "dict"}, {"a": "dict"}, None, True),
            ("something else", "", TypeError, False),
        ))

    def test_bool(self) -> None:
        self.do_validator_test("_bool", (
            (True, True, None, True),
            (False, False, None, True),
            ("a string", True, None, False),
            ("", False, None, False),
            ("True", True, None, False),
            ("False", False, None, False),
            (54, True, None, False),
        ))

    def test_printable_ascii_type(self) -> None:
        self.do_validator_test("_printable_ascii_type", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", None, ValueError, False),
            ("", "", None, True),
            (54, "54", None, False),
        ))

    def test_printable_ascii(self) -> None:
        self.do_validator_test("_printable_ascii", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", None, ValueError, False),
            ("", "", ValueError, False),
            (54, "54", None, False),
        ))

    def test_password_strength(self) -> None:
        self.do_validator_test("_password_strength", (
            ("Secure String 0#", "Secure String 0#", None, True),
            ("short", None, ValueError, False),
            ("insecure", None, ValueError, False),
            ("", "", ValueError, False),
        ))

    def test_email(self) -> None:
        self.do_validator_test("_email", (
            ("address@domain.tld", "address@domain.tld", None, True),
            ("eXtRaS_-4+@DomAin.tld", "extras_-4+@domain.tld", None, True),
            ("other@mailer.berlin", "other@mailer.berlin", None, True),
            ("äddress@domain.tld", None, ValueError, False),
            ("address@domain", None, ValueError, False),
            ("address_at_domain.tld", None, ValueError, False),
            ("a@ddress@domain.tld", None, ValueError, False),
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
        self.do_validator_test("_persona", (
            (base_example, base_example, None, True),
            (stripped_example, stripped_example, None, True),
            (key_example, key_example, KeyError, False),
            (password_example, password_example, KeyError, False),
            (value_example, value_example, ValueError, False),
        ))

    def test_date(self) -> None:
        now = datetime.datetime.now()
        self.do_validator_test("_date", (
            (now.date(), now.date(), None, True),
            (now, now.date(), None, True),
            ("2014-04-2", datetime.date(2014, 4, 2), None, False),
            ("01.02.2014", datetime.date(2014, 2, 1), None, False),
            ("2014-04-02T20:48:25.808240+00:00",
             datetime.date(2014, 4, 2), None, False),
            # the following fails with inconsistent exception type
            # TypeError on Gentoo
            # ValueError on Debian
            # ("more garbage", None, TypeError, False),
        ))

    def test_datetime(self) -> None:
        now = datetime.datetime.now()
        now_aware = datetime.datetime.now(pytz.utc)
        now_other = pytz.timezone('America/New_York').localize(now)
        self.do_validator_test("_datetime", (
            (now, now, None, True),
            (now_aware, now_aware, None, True),
            (now_other, now_other, None, True),
            (now.date(), None, TypeError, False),
            ("2014-04-20",
             datetime.datetime(2014, 4, 19, 22, 0, 0,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-02 21:53",
             datetime.datetime(2014, 4, 2, 19, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("01.02.2014 21:53",
             datetime.datetime(2014, 2, 1, 20, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("21:53", None, ValueError, False),
            ("2014-04-02T20:48:25.808240+00:00",
             datetime.datetime(2014, 4, 2, 20, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-02T20:48:25.808240+03:00",
             datetime.datetime(2014, 4, 2, 17, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            # see above
            # ("more garbage", None, TypeError, False),
        ))
        self.do_validator_test("_datetime", (
            (now, now, None, True),
            (now_aware, now_aware, None, True),
            (now_other, now_other, None, True),
            (now.date(), None, TypeError, False),
            ("2014-04-20",
             datetime.datetime(2014, 4, 19, 22, 0, 0,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-20 21:53",
             datetime.datetime(2014, 4, 20, 19, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("01.02.2014 21:53",
             datetime.datetime(2014, 2, 1, 20, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("21:53",
             datetime.datetime(2000, 5, 23, 19, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-20T20:48:25.808240+00:00",
             datetime.datetime(2014, 4, 20, 20, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-20T20:48:25.808240+03:00",
             datetime.datetime(2014, 4, 20, 17, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            # see above
            # ("more garbage", None, TypeError, False),
        ), extraparams={'default_date': datetime.date(2000, 5, 23)})

    def test_phone(self) -> None:
        self.do_validator_test("_phone", (
            ("+49 (3641) 12345", "+49 (3641) 12345", None, True),
            ("0049364112345", "+49 (3641) 12345", None, True),
            ("03641/12345", "+49 (3641) 12345", None, True),
            ("+500 (1111) 54321", "+500 (1111) 54321", None, True),
            ("+500-1111/54321", "+500 (1111) 54321", None, True),
            ("+500/1111/54321", "+500 (1111) 54321", None, True),
            ("00500__1111__54321", "+500 (1111) 54321", None, True),
            ("+5001111-54321", "+500 (1111) 54321", None, True),
            ("00500111154321", "+500 111154321", None, True),
            ("+49 (36460) 12345", None, ValueError, False),
            ("12345", None, ValueError, False),
            ("+210 (12390) 12345", None, ValueError, False),
        ))

    def test_member_data(self) -> None:
        base_example = {
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
            "country": "Deutschland",
            "notes": "A note",
            "birth_name": "Yggdrasil",
            "address_supplement2": "über der Treppe",
            "address2": "Straße 66",
            "postal_code2": "2XM 44",
            "location2": "Wolke",
            "country2": "Fantasien",
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
        self.do_validator_test("_persona", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, None, True),
            (key_example, key_example, KeyError, False),
            (value_example, value_example, ValidationWarning, False),
        ))

    def test_event_user_data(self) -> None:
        base_example = {
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
            "country": "Deutschland",
            "notes": "A note",
        }
        stripped_example = {"id": 42}
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        value_example = copy.deepcopy(base_example)
        value_example["postal_code"] = "07742"
        convert_example = copy.deepcopy(base_example)
        convert_example["birthday"] = base_example["birthday"].isoformat()
        self.do_validator_test("_persona", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, None, True),
            (key_example, None, KeyError, False),
            (value_example, None, ValidationWarning, False),
        ))

    def test_enum_validators(self) -> None:
        stati = const.AudiencePolicy
        self.do_validator_test("_enum_audiencepolicy", (
            (stati.require_cde, stati.require_cde, None, True),
            (4, stati.require_cde, None, True),
            ("4", stati.require_cde, None, False),
            (str(stati.require_cde), stati.require_cde, None, False),
            (-1, None, ValueError, False),
            ("alorecuh", None, ValueError, False),
        ))
        stati = const.RegistrationPartStati
        self.do_validator_test("_enum_registrationpartstati", (
            (stati.participant, stati.participant, None, True),
            (2, stati.participant, None, True),
            ("2", stati.participant, None, False),
            (-2, None, ValueError, False),
            ("alorecuh", None, ValueError, False),
        ))

    def test_vote(self) -> None:
        ballot = {
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
        self.do_validator_test("_vote", (
            ("A>B>C=D>E>_bar_", "A>B>C=D>E>_bar_", None, True),
            ("_bar_=B>E=C=D>A", "_bar_=B>E=C=D>A", None, True),
            ("_bar_=B>F=C=D>A", None, KeyError, False),
            ("", None, ValueError, False),
            ("_bar_=B<E=C=D<A", None, KeyError, False),
            ("_bar_=B>E=C>A", None, KeyError, False),
            ("_bar_=B>E=C>A>F=D", None, KeyError, False),
            ("=>=>>=", None, KeyError, False),
        ), extraparams={'ballot': ballot})
        self.do_validator_test("_vote", (
            ("A=B>C=D=E=_bar_", "A=B>C=D=E=_bar_", None, True),
            ("A>B=C=D=E=_bar_", "A>B=C=D=E=_bar_", None, True),
            ("_bar_>A=B=C=D=E", "_bar_>A=B=C=D=E", None, True),
            ("_bar_=A=B=C=D=E", "_bar_=A=B=C=D=E", None, True),
            ("E=C>A=D=B=_bar_", "E=C>A=D=B=_bar_", None, True),
            ("A=B=C>_bar_>D=E", None, ValueError, False),
            ("A>B>_bar_=C=D=E", None, ValueError, False),
            ("A=_bar_>B=C=D=E", None, ValueError, False),
            ("A>_bar_>B=C=D>E", None, ValueError, False),
            ("_bar_>A=B=C=D>E", None, ValueError, False),
            ("A>B=C=D=E>_bar_", None, ValueError, False),
            ("E=C>A>_bar_=D=B",  None, ValueError, False),
        ), extraparams={'ballot': classical_ballot})

    def test_iban(self) -> None:
        self.do_validator_test("_iban", (
            ("DE75512108001245126199", "DE75512108001245126199", None, True),
            ("DE75 5121 0800 1245 1261 99", "DE75512108001245126199", None, True),
            ("IT60X0542811101000000123456",
             "IT60X0542811101000000123456", None, True),
            ("123", None, ValueError, False),  # Too short
            ("1234567890", None, ValueError, False),  # Missing Country Code
            ("DEFG1234567890", None, ValueError, False),  # Digits in checksum
            ("DE1234+-567890", None, ValueError, False),  # Invalid Characters
            ("XX75512108001245126199", None,
             ValueError, False),  # Wrong Country Code
            ("FR75512108001245126199", None, ValueError, False),  # Wrong length
            ("DE0651210800124512619", None, ValueError, False),  # Wrong length
            ("DE00512108001245126199", None, ValueError, False),  # Wrong Checksum
        ))

    def test_json(self) -> None:
        for input, output, error in (
                ("42", 42, None),
                (b"42", 42, None),
                ('"42"', "42", None),
                (b'"42"', "42", None),
                ('{"foo": 1, "bar": "correct"}', {
                 "foo": 1, "bar": "correct"}, None),
                (b'{"foo": 1, "bar": "correct"}', {
                 "foo": 1, "bar": "correct"}, None),
                ("{'foo': 1, 'bar': 'correct'}", None, ValueError),
                (b"{'foo': 1, 'bar': 'correct'}", None, ValueError),
                ('{"open": 1', None, ValueError),
                (b'{"open": 1', None, ValueError),
                (b"\xff", None, ValueError)):
            with self.subTest(input=input):
                result, errs = validate.check_json(input, _convert=True)
                self.assertEqual(output, result)
                if error is None:
                    self.assertFalse(errs)
                else:
                    for fieldname, e in errs:
                        self.assertIsInstance(e, error)

    def test_german_postal_code(self) -> None:
        for assertion in ("_persona", "_genesis_case"):
            spec = (
                ({'id': 1, 'postal_code': "ABC", 'country': ""},
                 None,
                 ValidationWarning, False),
                ({'id': 1, 'postal_code': "ABC", 'country': None},
                 None,
                 ValidationWarning, False),
                ({'id': 1, 'postal_code': "ABC", 'country': "Deutschland"},
                 None,
                 ValidationWarning, False),
                ({'id': 1, 'postal_code': "ABC"}, None,
                 ValidationWarning, False),
                ({'id': 1, 'postal_code': "47239", 'country': ""},
                 {'id': 1, 'postal_code': "47239", 'country': None},
                 None, False),
                ({'id': 1, 'postal_code': "47239", 'country': None},
                 {'id': 1, 'postal_code': "47239", 'country': None},
                 None, True),
                ({'id': 1, 'postal_code': "47239", 'country': "Deutschland"},
                 {'id': 1, 'postal_code': "47239", 'country': "Deutschland"},
                 None, True),
                ({'id': 1, 'postal_code': "47239"},
                 {'id': 1, 'postal_code': "47239"},
                 None, True),
            )
            if assertion == "_genesis_case":
                for inv, outv, _, _ in spec:
                    inv['realm'] = "event"
                    if outv is not None:
                        outv['realm'] = "event"
            self.do_validator_test(assertion, spec, None)
            spec = (
                ({'id': 1, 'postal_code': "ABC", 'country': ""},
                 {'id': 1, 'postal_code': "ABC", 'country': None},
                 None, False),
                ({'id': 1, 'postal_code': "ABC", 'country': None},
                 {'id': 1, 'postal_code': "ABC", 'country': None},
                 None, True),
                ({'id': 1, 'postal_code': "ABC", 'country': "Deutschland"},
                 {'id': 1, 'postal_code': "ABC", 'country': "Deutschland"},
                 None, True),
                ({'id': 1, 'postal_code': "ABC"},
                 {'id': 1, 'postal_code': "ABC"},
                 None, True),
                ({'id': 1, 'postal_code': "47239", 'country': None},
                 {'id': 1, 'postal_code': "47239", 'country': None},
                 None, True),
                ({'id': 1, 'postal_code': "47239", 'country': ""},
                 {'id': 1, 'postal_code': "47239", 'country': None},
                 None, False),
                ({'id': 1, 'postal_code': "47239", 'country': "Deutschland"},
                 {'id': 1, 'postal_code': "47239", 'country': "Deutschland"},
                 None, True),
                ({'id': 1, 'postal_code': "47239"},
                 {'id': 1, 'postal_code': "47239"},
                 None, True),
            )
            if assertion == "_genesis_case":
                for inv, outv, _, _ in spec:
                    inv['realm'] = "event"
                    if outv is not None:
                        outv['realm'] = "event"
            self.do_validator_test(assertion, spec, {'_ignore_warnings': True})

    def test_encoding(self) -> None:
        # Make sure decoding utf-8 as if it were utf-8-sig works.
        msg = "abc"
        self.assertEqual(msg, msg.encode('utf-8').decode('utf-8'))
        self.assertEqual(msg, msg.encode('utf-8').decode('utf-8-sig'))
        self.assertEqual(
            "\ufeff" + msg, msg.encode('utf-8-sig').decode('utf-8'))
        self.assertEqual(msg, msg.encode('utf-8-sig').decode('utf-8-sig'))

    def test_safe_str(self) -> None:
        spec = [
            ("abc123 .,-+()/", "abc123 .,-+()/", None, True),
            ("", None, ValueError, False),
            (1, "1", None, False),
            ((1, 2, 3), "(1, 2, 3)", None, False),
            ("abc[]&def", None, ValueError(
                "Forbidden characters (%(chars)s). (None)", {"chars": "&[]"}), False),
        ]
        self.do_validator_test("_safe_str", spec)
