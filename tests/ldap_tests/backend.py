"""
To test the backend itself we need to use aiounittest, which is hard, so for now
this only tests some static backend methods.
"""
from typing import Any, Union

from tests.common import BasicTest
from cdedb.ldap.backend import LDAPsqlBackend


class LDAPBackendTest(BasicTest):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ldap_backend_class = LDAPsqlBackend  # Instantiation needs an async object.

    def test_to_bytes(self) -> None:
        values: tuple[tuple[Any, Any], ...] = (
            ("123", b"123"),
            ("abcdef", b"abcdef"),
            ("äöü", "äöü".encode()),
            (123, b"123"),
            (["a", "b", "c"], [b"a", b"b", b"c"]),
            ({"abc": 123}, {b"abc": b"123"}),
            ([123, "abc", "äöü", [456, "def", "ßÄÖÜ"], {"ghi": -42, 2222: "jkl"}],
             [b"123", b"abc", "äöü".encode(), [b"456", b"def", "ßÄÖÜ".encode()],
              {b"ghi": b"-42", b"2222": b"jkl"}]),
        )

        for in_, out in values:
            with self.subTest(in_):
                self.assertEqual(out, self.ldap_backend_class._to_bytes(in_))
