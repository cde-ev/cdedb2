"""
To test the backend itself we need to use aiounittest, which is hard, so for now
this only tests some static backend methods.

Equality assertions should be done as `self.assertEqual(expectation, result)`, where
result is the return of the function to be tested, and expectation is a literal or
computed value, that the tested function should return,
e.g. `self.assertEqual("123", str(123))`.
"""
import asyncio
from typing import Any

import psycopg.rows
from ldaptor.protocols.ldap.distinguishedname import DistinguishedName as DN
from ldaptor.protocols.pureber import ber2int, int2ber
from psycopg import AsyncConnection

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
            (123, int2ber(123)),
            (0x7c, b"\x7c"),
            (0x12345, b"\x01\x23\x45"),
            (0x12345, int2ber(0x12345)),
            (0xedcba, b"\x0e\xdc\xba"),
            (0xedcba, int2ber(0xedcba)),
            (0xfedcba, b"\00\xfe\xdc\xba"),
            (0xfedcba, int2ber(0xfedcba)),
            (2 ** 16, b"\x01\x00\x00"),
            (2 ** 16, int2ber(2 ** 16)),
            (b"1234", b"1234"),
            (None, b""),
            (DN("cn=xyz"), b"cn=xyz"),
            (DN("cn=äöü"), "cn=äöü".encode()),
            (["a", "b", "c"], [b"a", b"b", b"c"]),
            ({"abc": 123}, {b"abc": int2ber(123)}),
            ([123, "abc", "äöü", [456, "def", "ßÄÖÜ"], {"ghi": -42, 2222: "jkl"}],
             [int2ber(123), b"abc", "äöü".encode(),
              [int2ber(456), b"def", "ßÄÖÜ".encode()],
              {b"ghi": int2ber(-42), int2ber(2222): b"jkl"}]),
        )

        for in_, out in values:
            with self.subTest(in_):
                self.assertEqual(out, self.ldap_backend_class._to_bytes(in_))  # pylint: disable=protected-access

    def test_int2ber(self) -> None:
        values = [123, -123, 232423, 0, -1112423]
        for value in values:
            with self.subTest(value):
                self.assertEqual(value, ber2int(int2ber(value)))

    def test_encrypt_verify_password(self) -> None:
        pw = "abcdefghij1234567890"
        pw_hash = self.ldap_backend_class.encrypt_password(pw)
        self.assertNotEqual(pw, pw_hash)
        self.assertTrue(self.ldap_backend_class.verify_password(pw, pw_hash))
        self.assertFalse(self.ldap_backend_class.verify_password("wrong", pw_hash))

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
        self.assertEqual(dn_value, self.ldap_backend_class._dn_value(dn, dn_attr))  # pylint: disable=protected-access

    def test_anonymous_accessible_dns(self) -> None:
        expectation = [DN("cn=subschema")]
        self.assertEqual(expectation, self.ldap_backend_class.anonymous_accessible_dns)

    def test_root_dn(self) -> None:
        expectation = DN("")
        self.assertEqual(expectation, self.ldap_backend_class.root_dn)

    def test_subschema_dn(self) -> None:
        expectation = DN("cn=subschema")
        self.assertEqual(expectation, self.ldap_backend_class.subschema_dn)

    def test_de_dn(self) -> None:
        expectation = DN("dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.de_dn)

    def test_cde_dn(self) -> None:
        expectation = DN("dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.cde_dn)

    def test_duas_dn(self) -> None:
        expectation = DN("ou=duas,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.duas_dn)

    def test_dua_dn(self) -> None:
        name = "admin"
        expectation = DN(f"cn={name},ou=duas,dc=cde-ev,dc=de")
        self.assertEqual(name, self.ldap_backend_class.dua_cn(name))
        dn = self.ldap_backend_class.dua_dn(name)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_dua_dn(dn))
        self.assertEqual(name, self.ldap_backend_class.dua_name(dn))

    def test_users_dn(self) -> None:
        expectation = DN("ou=users,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.users_dn)

    def test_user_dn(self) -> None:
        persona_id = 42
        expectation = DN(f"uid={persona_id},ou=users,dc=cde-ev,dc=de")
        self.assertEqual(f"{persona_id}", self.ldap_backend_class.user_uid(persona_id))
        dn = self.ldap_backend_class.user_dn(persona_id)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_user_dn(dn))
        self.assertEqual(persona_id, self.ldap_backend_class.user_id(dn))

    def test_groups_dn(self) -> None:
        expectation = DN("ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.groups_dn)

    def test_status_groups_dn(self) -> None:
        expectation = DN("ou=status,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.status_groups_dn)

    def test_status_group_dn(self) -> None:
        name = "is_member"
        expectation = DN(f"cn={name},ou=status,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(name, self.ldap_backend_class.status_group_cn(name))
        dn = self.ldap_backend_class.status_group_dn(name)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_status_group_dn(dn))
        self.assertEqual(name, self.ldap_backend_class.status_group_name(dn))

    def test_presider_groups_dn(self) -> None:
        expectation = DN("ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.presider_groups_dn)

    def test_presider_group_dn(self) -> None:
        assembly_id = 5
        expectation = DN(f"cn=presiders-{assembly_id},ou=assembly-presiders,ou=groups,"
                         f"dc=cde-ev,dc=de")
        self.assertEqual(f"presiders-{assembly_id}",
                         self.ldap_backend_class.presider_group_cn(assembly_id))
        dn = self.ldap_backend_class.presider_group_dn(assembly_id)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_presider_group_dn(dn))
        self.assertEqual(assembly_id, self.ldap_backend_class.presider_group_id(dn))

    def test_orgas_groups_dn(self) -> None:
        expectation = DN("ou=event-orgas,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.orga_groups_dn)

    def test_orga_group_dn(self) -> None:
        event_id = 100
        expectation = DN(
            f"cn=orgas-{event_id},ou=event-orgas,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(f"orgas-{event_id}",
                         self.ldap_backend_class.orga_group_cn(event_id))
        dn = self.ldap_backend_class.orga_group_dn(event_id)
        self.assertEqual(dn, expectation)
        self.assertTrue(self.ldap_backend_class.is_orga_group_dn(dn))
        self.assertEqual(self.ldap_backend_class.orga_group_id(dn), event_id)

    def test_moderator_groups_dn(self) -> None:
        expectation = DN("ou=ml-moderators,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.moderator_groups_dn)

    def test_moderator_group_dn(self) -> None:
        address = "test@lists.cde-ev.de"
        owner_address = "test-owner@lists.cde-ev.de"
        expectation = DN(
            f"cn={owner_address},ou=ml-moderators,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(
            owner_address, self.ldap_backend_class.moderator_group_cn(address))
        dn = self.ldap_backend_class.moderator_group_dn(address)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_moderator_group_dn(dn))
        self.assertFalse(self.ldap_backend_class.is_subscriber_group_dn(dn))
        self.assertEqual(address, self.ldap_backend_class.moderator_group_address(dn))

    def test_subscriber_groups_dn(self) -> None:
        expectation = DN("ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(expectation, self.ldap_backend_class.subscriber_groups_dn)

    def test_subscriber_group_dn(self) -> None:
        address = "test@lists.cde-ev.de"
        expectation = DN(f"cn={address},ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de")
        self.assertEqual(address, self.ldap_backend_class.subscriber_group_cn(address))
        dn = self.ldap_backend_class.subscriber_group_dn(address)
        self.assertEqual(expectation, dn)
        self.assertTrue(self.ldap_backend_class.is_subscriber_group_dn(dn))
        self.assertFalse(self.ldap_backend_class.is_moderator_group_dn(dn))
        self.assertEqual(address, self.ldap_backend_class.subscriber_group_address(dn))


class AsyncLDAPBackendTest(AsyncBasicTest):
    ldap: LDAPsqlBackend

    async def asyncSetUp(self) -> None:
        """Since each test has it's own event loop, we need to create a database
        connection each time.

        This is somewhat expensive and asyncio complains when in debugmode, so we
        disable debugmode for the database connection creation.
        """
        asyncio.get_running_loop().set_debug(False)
        conn_params = dict(
            dbname=self.conf["CDB_DATABASE_NAME"],
            user="cdb_admin",
            password=self.secrets["CDB_DATABASE_ROLES"]["cdb_admin"],
            host=self.conf["DB_HOST"],
            port=self.conf["DB_PORT"],
        )
        conn_info = " ".join([f"{k}={v}" for k, v in conn_params.items()])
        conn = await AsyncConnection.connect(
            conn_info, row_factory=psycopg.rows.dict_row)
        asyncio.get_running_loop().set_debug(True)
        self.ldap = LDAPsqlBackend(conn)

    async def test_duas(self) -> None:
        dua_dns = await self.ldap.list_duas()
        for dua in dua_dns:
            self.assertIsInstance(dua, DN)
        duas = await self.ldap.get_duas(dua_dns)

    async def test_users(self) -> None:
        persona_ids = {1, 3, 10}
        user_dns = await self.ldap.list_users()
        for user in user_dns:
            self.assertIsInstance(user, DN)
        users = await self.ldap.get_users(user_dns)
        users_data = await self.ldap.get_users_data(persona_ids)
        user_groups = await self.ldap.get_users_groups(persona_ids)

    async def test_get_status_groups(self) -> None:
        status_group_dns = await self.ldap.list_status_groups()
        for status_group in status_group_dns:
            self.assertIsInstance(status_group, DN)
        status_groups = await self.ldap.get_status_groups(status_group_dns)

    async def test_assembly_presiders(self) -> None:
        assembly_ids = {1, 2}
        presider_group_dns = await self.ldap.list_assembly_presider_groups()
        for presider in presider_group_dns:
            self.assertIsInstance(presider, DN)
        presider_groups = await self.ldap.get_assembly_presider_groups(
            presider_group_dns)
        presiders = await self.ldap.get_presiders(assembly_ids)
        assemblies = await self.ldap.get_assemblies(assembly_ids)

    async def test_orgas(self) -> None:
        event_ids = {1, 2, 3, 4}
        orga_group_dns = await self.ldap.list_event_orga_groups()
        for orga in orga_group_dns:
            self.assertIsInstance(orga, DN)
        orga_groups = await self.ldap.get_event_orga_groups(orga_group_dns)
        orgas = await self.ldap.get_orgas(event_ids)
        events = await self.ldap.get_events(event_ids)
