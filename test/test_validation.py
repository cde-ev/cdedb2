#!/usr/bin/env python3

import unittest
from test.common import BackendTest
import cdedb.validation as validate
import decimal
import copy
import datetime
import pytz

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
                    with self.assertRaises(exception):
                        getattr(validate, "assert" + name)(inval, **extraparams)
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

    def test_or_None(self):
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

    def test_int(self):
        self.do_validator_test("_int", (
            (0, 0, None, True),
            (12, 12, None, True),
            (None, None, TypeError, False),
            ("-12", -12, None, False),
            ("12.3", None, ValueError, False),
            ("garbage", None, ValueError, False),
            (12.0, 12, None, False),
            (12.5, None, ValueError, False),
            ))

    def test_float(self):
        self.do_validator_test("_float", (
            (0.0, 0.0, None, True),
            (12.3, 12.3, None, True),
            (None, None, TypeError, False),
            ("12", 12.0, None, False),
            ("-12.3", -12.3, None, False),
            ("garbage", None, ValueError, False),
            (12, 12.0, None, False),
            ))

    def test_decimal(self):
        self.do_validator_test("_decimal", (
            (decimal.Decimal(0), decimal.Decimal(0), None, True),
            (decimal.Decimal(12.3), decimal.Decimal(12.3), None, True),
            (None, None, TypeError, False),
            ("12", decimal.Decimal((0, (1, 2), 0)), None, False),
            ("-12.3", decimal.Decimal((1, (1, 2, 3), -1)), None, False),
            ("garbage", None, decimal.InvalidOperation, False),
            (12, None, TypeError, False),
            (12.3, None, TypeError, False),
            ))

    def test_str_type(self):
        self.do_validator_test("_str_type", (
            ("a string", "a string", None, True),
            ("with stuff äößł€ ", "with stuff äößł€ ", None, True),
            ("", "", None, True),
            (54, "54", None, False),
            ))
        self.do_validator_test("_str_type", (
            ("a string", "a stig", None, True),
            ), extraparams={'zap': 'rn'})
        self.do_validator_test("_str_type", (
            ("a string", "a sti", None, True),
            ), extraparams={'sieve': ' aist'})

    def test_str(self):
        self.do_validator_test("_str", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", "string with stuff äößł€", None, True),
            ("", "", ValueError, False),
            (54, "54", None, False),
            ))

    def test_mapping(self):
        self.do_validator_test("_mapping", (
            ({"a": "dict"}, {"a": "dict"}, None, True),
            ("something else", "", TypeError, False),
            ))

    def test_bool(self):
        self.do_validator_test("_bool", (
            (True, True, None, True),
            (False, False, None, True),
            ("a string", True, None, False),
            ("", False, None, False),
            ("True", True, None, False),
            ("False", False, None, False),
            (54, True, None, False),
            ))

    def test_printable_ascii_type(self):
        self.do_validator_test("_printable_ascii_type", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", None, ValueError, False),
            ("", "", None, True),
            (54, "54", None, False),
            ))

    def test_printable_ascii(self):
        self.do_validator_test("_printable_ascii", (
            ("a string", "a string", None, True),
            ("string with stuff äößł€", None, ValueError, False),
            ("", "", ValueError, False),
            (54, "54", None, False),
            ))

    def test_password_strength(self):
        self.do_validator_test("_password_strength", (
            ("Secure String 0#", "Secure String 0#", None, True),
            ("short", None, ValueError, False),
            ("insecure", None, ValueError, False),
            ("", "", ValueError, False),
            ))

    def test_email(self):
        self.do_validator_test("_email", (
            ("address@domain.tld", "address@domain.tld", None, True),
            ("eXtRaS_-4+@DomAin.tld", "extras_-4+@domain.tld", None, True),
            ("other@mailer.berlin", "other@mailer.berlin", None, True),
            ("äddress@domain.tld", None, ValueError, False),
            ("address@domain", None, ValueError, False),
            ("address_at_domain.tld", None, ValueError, False),
            ("a@ddress@domain.tld", None, ValueError, False),
            ))

    def test_persona_data(self):
        base_example = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "is_active": True,
            "status": 0,
            "db_privileges": 2,
            "cloud_account": True,
            }
        stripped_example = { "id": 42 }
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        password_example = copy.deepcopy(base_example)
        password_example["password_hash"] = "something"
        value_example = copy.deepcopy(base_example)
        value_example["username"] = "garbage"
        self.do_validator_test("_persona_data", (
            (base_example, base_example, None, True),
            (stripped_example, stripped_example, None, True),
            (key_example, key_example, KeyError, False),
            (password_example, password_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ))
        self.do_validator_test("_persona_data", (
            (base_example, base_example, None, True),
            (stripped_example, stripped_example, KeyError, False),
            (key_example, key_example, KeyError, False),
            (password_example, password_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ), extraparams={'strict': True})

    def test_date(self):
        now = datetime.datetime.now()
        self.do_validator_test("_date", (
            (now.date(), now.date(), None, True),
            (now, now.date(), None, True),
            ("2014-04-20", datetime.date(2014, 4, 20), None, False),
            ("01.02.2014", datetime.date(2014, 2, 1), None, False),
            ("2014-04-20T20:48:25.808240+00:00",
             datetime.date(2014, 4, 20), None, False),
            ## the following fails with inconsistent exception type
            ## TypeError on Gentoo
            ## ValueError on Debian
            # ("more garbage", None, TypeError, False),
            ))

    def test_datetime(self):
        now = datetime.datetime.now()
        now_aware = datetime.datetime.now(pytz.utc)
        now_other = pytz.timezone('America/New_York').localize(now)
        self.do_validator_test("_datetime", (
            (now, now, None, True),
            (now_aware, now_aware, None, True),
            (now_other, now_other, None, True),
            (now.date(), None, TypeError, False),
            ("2014-04-20", None, ValueError, False),
            ("2014-04-20 21:53",
             datetime.datetime(2014, 4, 20, 19, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("01.02.2014 21:53",
             datetime.datetime(2014, 2, 1, 20, 53, 0,
                               tzinfo=pytz.utc), None, False),
            ("21:53", None, ValueError, False),
            ("2014-04-20T20:48:25.808240+00:00",
             datetime.datetime(2014, 4, 20, 20, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            ("2014-04-20T20:48:25.808240+03:00",
             datetime.datetime(2014, 4, 20, 17, 48, 25, 808240,
                               tzinfo=pytz.utc), None, False),
            ## see above
            # ("more garbage", None, TypeError, False),
            ))
        self.do_validator_test("_datetime", (
            (now, now, None, True),
            (now_aware, now_aware, None, True),
            (now_other, now_other, None, True),
            (now.date(), None, TypeError, False),
            ("2014-04-20", None, ValueError, False),
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
            ## see above
            # ("more garbage", None, TypeError, False),
            ), extraparams={'default_date': datetime.date(2000, 5, 23)})


    def test_phone(self):
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

    def test_germane_postal_code(self):
        self.do_validator_test("_german_postal_code", (
            ("07743", "07743", None, True),
            ("07742", None, ValueError, False),
            ))

    def test_member_data(self):
        base_example = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "is_active": True,
            "status": 0,
            "db_privileges": 2,
            "cloud_account": True,
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
        stripped_example = { "id": 42 }
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        value_example = copy.deepcopy(base_example)
        value_example["postal_code"] = "07742"
        convert_example = copy.deepcopy(base_example)
        convert_example["birthday"] = base_example["birthday"].isoformat()
        self.do_validator_test("_member_data", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, None, True),
            (key_example, key_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ))
        self.do_validator_test("_member_data", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, KeyError, False),
            (key_example, key_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ), extraparams={'strict': True})

    def test_event_user_data(self):
        base_example = {
            "id": 42,
            "username": "address@domain.tld",
            "display_name": "Blübb the First",
            "is_active": True,
            "status": 0,
            "db_privileges": 2,
            "cloud_account": False,
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
        stripped_example = { "id": 42 }
        key_example = copy.deepcopy(base_example)
        key_example["wrong_key"] = None
        value_example = copy.deepcopy(base_example)
        value_example["postal_code"] = "07742"
        convert_example = copy.deepcopy(base_example)
        convert_example["birthday"] = base_example["birthday"].isoformat()
        self.do_validator_test("_event_user_data", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, None, True),
            (key_example, key_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ))
        self.do_validator_test("_event_user_data", (
            (base_example, base_example, None, True),
            (convert_example, base_example, None, False),
            (stripped_example, stripped_example, KeyError, False),
            (key_example, key_example, KeyError, False),
            (value_example, value_example, ValueError, False),
            ), extraparams={'strict': True})
