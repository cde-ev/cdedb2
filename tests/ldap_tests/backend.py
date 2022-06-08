"""
To test the backend itself we need to use aiounittest, which is hard, so for now
this only tests some static backend methods.
"""
from typing import Any, ClassVar

import psycopg2.extras
from aiopg import create_pool
from ldaptor.protocols.ldap.distinguishedname import (
    DistinguishedName as DN, RelativeDistinguishedName as RDN,
)

from cdedb.ldap.backend import LDAPsqlBackend, classproperty
from tests.common import AsyncBasicTest, BasicTest


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

    def test_encrypt_verify_password(self) -> None:
        pw = "abcdefghij1234567890"
        hash = self.ldap_backend_class.encrypt_password(pw)
        self.assertNotEqual(pw, hash)
        self.assertTrue(self.ldap_backend_class.verify_password(pw, hash))

    def test_classproperties(self) -> None:
        classproperties = {
            "de_dn", "cde_dn", "duas_dn", "users_dn", "groups_dn", "status_groups_dn",
            "presider_groups_dn", "orga_groups_dn", "moderator_groups_dn", "root_dn",
            "subscriber_groups_dn", "anonymous_accessible_dns", "subschema_dn",
        }
        for name, attr in self.ldap_backend_class.__dict__.items():
            with self.subTest(name):
                if name in classproperties:
                    self.assertIsInstance(attr, classproperty)
                    getattr(self.ldap_backend_class, name)
                else:
                    self.assertNotIsInstance(attr, classproperty)

    def test_dn_value(self) -> None:
        dn_attr, dn_value = "cn", "cde-ev"
        dn = DN(f"{dn_attr}={dn_value}")
        self.assertEqual(self.ldap_backend_class._dn_value(dn, dn_attr), dn_value)

    def test_user_id(self) -> None:
        persona_id = 42
        dn = self.ldap_backend_class.user_dn(persona_id)
        self.assertEqual(self.ldap_backend_class.user_id(dn), persona_id)

    def test_anonymous_accessible_dns(self) -> None:
        expectation = [DN("cn=subschema")]
        dns = self.ldap_backend_class.anonymous_accessible_dns
        self.assertEqual(expectation, dns)

    def test_root_dn(self) -> None:
        expectation = DN("")
        dn = self.ldap_backend_class.root_dn
        self.assertEqual(expectation, dn)

    def test_subschema_dn(self) -> None:
        expectation = DN("cn=subschema")
        dn = self.ldap_backend_class.subschema_dn
        self.assertEqual(expectation, dn)

    def test_de_dn(self) -> None:
        expectation = DN("dc=de")
        dn = self.ldap_backend_class.de_dn
        self.assertEqual(expectation, dn)

    def test_cde_dn(self) -> None:
        expectation = DN("dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.cde_dn
        self.assertEqual(expectation, dn)

    def test_duas_dn(self) -> None:
        expectation = DN("ou=duas,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.duas_dn
        self.assertEqual(expectation, dn)

    def test_users_dn(self) -> None:
        expectation = DN("ou=users,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.users_dn
        self.assertEqual(expectation, dn)

    def test_groups_dn(self) -> None:
        expectation = DN("ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.groups_dn
        self.assertEqual(expectation, dn)

    def test_status_groups_dn(self) -> None:
        expectation = DN("ou=status,ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.status_groups_dn
        self.assertEqual(expectation, dn)

    def test_presider_groups_dn(self) -> None:
        expectation = DN("ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.presider_groups_dn
        self.assertEqual(expectation, dn)

    def test_orgas_groups_dn(self) -> None:
        expectation = DN("ou=event-orgas,ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.orga_groups_dn
        self.assertEqual(expectation, dn)

    def test_moderator_groups_dn(self) -> None:
        expectation = DN("ou=ml-moderators,ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.moderator_groups_dn
        self.assertEqual(expectation, dn)

    def test_subscriber_groups_dn(self) -> None:
        expectation = DN("ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de")
        dn = self.ldap_backend_class.subscriber_groups_dn
        self.assertEqual(expectation, dn)


class AsyncLDAPBackendTest(AsyncBasicTest):
    ldap: ClassVar[LDAPsqlBackend]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ldap = None  # type: ignore[assignment]

    async def asyncSetUp(self) -> None:
        if self.ldap is None:
            pool = await create_pool(  # type: ignore[unreachable]
                dbname=self.conf["CDB_DATABASE_NAME"],
                user="cdb_admin",
                password=self.secrets["CDB_DATABASE_ROLES"]["cdb_admin"],
                host=self.conf["DB_HOST"],
                port=self.conf["DB_PORT"],
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            self.__class__.ldap = LDAPsqlBackend(pool)

    async def test_list_duas(self) -> None:
        duas = await self.ldap.list_duas()
        for dua in duas:
            self.assertIsInstance(dua, RDN)
