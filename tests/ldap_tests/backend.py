"""
To test the backend itself we need to use aiounittest, which is hard, so for now
this only tests some static backend methods.
"""
from typing import Any

from ldaptor.protocols.ldap.distinguishedname import DistinguishedName as DN

from tests.common import BasicTest
from cdedb.ldap.backend import LDAPsqlBackend


class LDAPBackendTest(BasicTest):
    ldap_backend_class = LDAPsqlBackend

    def test_to_bytes(self) -> None:
        values: tuple[tuple[Any, Any], ...] = (
            ("123", b"123"),
            ("abcdef", b"abcdef"),
            ("äöü", "äöü".encode()),
            ("äöü", b"\xc3\xa4\xc3\xb6\xc3\xbc"),
            (123, b"123"),
            (b"1234", b"1234"),
            (None, b""),
            (DN("cn=xyz"), b"cn=xyz"),
            (DN("cn=äöü"), "cn=äöü".encode()),
            (["a", "b", "c"], [b"a", b"b", b"c"]),
            ({"abc": 123}, {b"abc": b"123"}),
            ([123, "abc", "äöü", [456, "def", "ßÄÖÜ"], {"ghi": -42, 2222: "jkl"}],
             [b"123", b"abc", "äöü".encode(), [b"456", b"def", "ßÄÖÜ".encode()],
              {b"ghi": b"-42", b"2222": b"jkl"}]),
        )

        for in_, out in values:
            with self.subTest(in_):
                self.assertEqual(out, self.ldap_backend_class._to_bytes(in_))
