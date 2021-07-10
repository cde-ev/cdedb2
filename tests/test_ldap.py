#!/usr/bin/env python3

from typing import Dict, List, Set

import ldap3   # type: ignore
from ldap3.abstract.entry import Entry  # type: ignore

from tests.common import BasicTest


class TestLDAP(BasicTest):

    root_dn = f'dc=cde-ev,dc=de'
    test_dsa_dn = f'cn=test,ou=dsa,{root_dn}'
    test_dsa_pw = 'secret'
    server: ldap3.Server

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.server = ldap3.Server(
            cls.conf['LDAP_HOST'], port=cls.conf['LDAP_PORT'], get_info=ldap3.ALL)

    def single_result_search(self, search_filter: str, attributes: List[str],
                             expectation: Dict[str, List[str]], *,
                             user: str = test_dsa_dn, password: str = test_dsa_pw,
                             search_base: str = root_dn) -> None:
        with ldap3.Connection(self.server, user=user, password=password) as conn:
            conn.search(search_base=search_base, search_filter=search_filter,
                        attributes=attributes)
            self.assertEqual(len(conn.entries), 1)
            result = conn.entries[0].entry_attributes_as_dict
            self.assertEqual(result, expectation)

    def test_anonymous_bind(self) -> None:
        conn = ldap3.Connection(self.server)
        self.assertTrue(conn.bind())
        self.assertEqual(conn.extend.standard.who_am_i(), None)

    def test_simple_password_bind(self) -> None:
        # try to bind to nonexistent DSA
        conn = ldap3.Connection(self.server, user='cn=nonexistent,ou=dsa,dc=cde-ev,dc=de', password=self.test_dsa_pw)
        self.assertFalse(conn.bind())

        # try to bind to existent DSA with wrong password
        conn = ldap3.Connection(self.server, user=self.test_dsa_dn, password='wrongPW')
        self.assertFalse(conn.bind())

        # bind with a DSA
        conn = ldap3.Connection(self.server, user=self.test_dsa_dn, password=self.test_dsa_pw)
        self.assertTrue(conn.bind())
        self.assertEqual('dn:' + self.test_dsa_dn, conn.extend.standard.who_am_i())
        self.assertTrue(conn.unbind())

        # try to bind to nonexistent user
        conn = ldap3.Connection(self.server, user='uid=0,ou=users,dc=cde-ev,dc=de', password='secret')
        self.assertFalse(conn.bind())

        # try to bind to existend user with wrong password
        conn = ldap3.Connection(self.server, user='uid=1,ou=users,dc=cde-ev,dc=de', password='wrongPW')
        self.assertFalse(conn.bind())

        # bind with a users
        conn = ldap3.Connection(self.server, user='uid=1,ou=users,dc=cde-ev,dc=de', password='secret')
        self.assertTrue(conn.bind())
        self.assertEqual('dn:' + 'uid=1,ou=users,dc=cde-ev,dc=de', conn.extend.standard.who_am_i())
        self.assertTrue(conn.unbind())

    def test_anonymous_search(self) -> None:
        """Anonymous clients are only allowed to bind."""
        conn = ldap3.Connection(self.server)
        conn.bind()
        search_filter = "(objectClass=organization)"
        conn.search(search_base=self.root_dn, search_filter=search_filter)
        self.assertEqual(list(), conn.entries)

    def test_user_access(self) -> None:
        user_id = 1
        other_user_id = 2
        user = f"uid={user_id},ou=users,dc=cde-ev,dc=de"
        password = "secret"

        # users may access their own data
        attributes = ["objectclass", "cn"]
        expectation: Dict[str, List[str]] = {
            'cn': ['Anton Armin A. Administrator'],
            'objectClass': ['inetOrgPerson'],
        }
        search_filter = (
            "(&"
                "(objectClass=inetOrgPerson)"
                f"(uid={user_id})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  user=user, password=password)

        # users must not access other users data
        conn = ldap3.Connection(self.server, user=user, password=password)
        conn.bind()
        search_filter = (
            "(&"
                "(objectClass=inetOrgPerson)"
                f"(uid={other_user_id})"
            ")"
        )
        conn.search(search_base=self.root_dn, search_filter=search_filter)
        self.assertEqual(list(), conn.entries)

        # users may access any group and their members
        group_cn = 1
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        search_base = "ou=event-orgas,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': ['1'],
            'description': ['Große Testakademie 2222 (TestAka)'],
            'uniqueMember': [
                'uid=7,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames'],
        }

        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  search_base=search_base)

    # TODO test encrypted connections (tls)

    def test_organization_entity(self) -> None:
        """Check if all attributes of the organization are correctly present."""
        attributes = ["objectclass", "o"]
        expectation = {
            'objectClass': [
                'organization',
                'dcObject',
                'top'
            ],
            'o': ['CdE e.V.']
        }
        search_filter = "(objectClass=organization)"
        self.single_result_search(search_filter, attributes, expectation)

    def test_organizational_unit_entity(self) -> None:
        """Check if all attributes of an organizational unit are correctly present."""
        organizational_unit_o = "Users"
        attributes = ["objectclass", "o"]
        expectation = {
            'objectClass': ['organizationalUnit'],
            'o': ['Users']
        }
        search_filter = (
            "(&"
                "(objectClass=organizationalUnit)"
                f"(o={organizational_unit_o})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)

    def test_user_entity(self) -> None:
        """Check if all attributes of an user are correctly present."""
        user_id = 1
        attributes = ["objectclass", "cn", "givenName", "displayName", "mail", "uid", "userPassword"]
        expectation: Dict[str, List[str]] = {
            'uid': ['1'],
            'mail': ['anton@example.cde'],

            'cn': ['Anton Armin A. Administrator'],
            'displayName': ['Anton Administrator'],
            'givenName': ['Anton Armin A.'],

            # this is empty, since dsas may not retrieve the password, but only
            # authenticate against them
            'userPassword': [],
            'objectClass': ['inetOrgPerson'],
        }
        search_filter = (
            "(&"
            "(objectClass=inetOrgPerson)"
            f"(uid={user_id})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)

    def test_static_group_entity(self) -> None:
        """Check if all attributes of static groups are correctly present."""
        group_cn = "is_cdelokal_admin"
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        expectation = {
            'cn': ['is_cdelokal_admin'],
            'description': ['CdELokal-Administratoren'],
            'uniqueMember': [
                'uid=100,ou=users,dc=cde-ev,dc=de',
                'uid=1,ou=users,dc=cde-ev,dc=de',
                'uid=9,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames']
        }
        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)

    def test_ml_subscriber_group_entity(self) -> None:
        """Check if all attributes of ml-subscriber groups are correctly present."""
        group_cn = "gutscheine@lists.cde-ev.de"
        search_base = "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de"
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        expectation = {
            'cn': ['gutscheine@lists.cde-ev.de'],
            'description': ['Gutscheine <gutscheine@lists.cde-ev.de>'],
            'uniqueMember': [
                'uid=100,ou=users,dc=cde-ev,dc=de',
                'uid=11,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames'],
        }

        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  search_base=search_base)

    def test_ml_moderator_group_entity(self) -> None:
        """Check if all attributes of ml-moderator groups are correctly present."""
        group_cn = "gutscheine@lists.cde-ev.de"
        search_base = "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de"
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        expectation = {
            'cn': ['gutscheine@lists.cde-ev.de'],
            'description': ['Gutscheine <gutscheine@lists.cde-ev.de>'],
            'uniqueMember': [
                'uid=9,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames'],
        }

        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  search_base=search_base)

    def test_event_orgas_group_entity(self) -> None:
        """Check if all attributes of event-orga groups are correctly present."""
        group_cn = "1"
        search_base = "ou=event-orgas,ou=groups,dc=cde-ev,dc=de"
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        expectation = {
            'cn': ['1'],
            'description': ['Große Testakademie 2222 (TestAka)'],
            'uniqueMember': [
                'uid=7,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames'],
        }

        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  search_base=search_base)

    def test_assembly_presiders_group_entity(self) -> None:
        """Check if all attributes of assembly-presider groups are correctly present."""
        group_cn = "1"
        search_base = "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de"
        attributes = ["objectclass", "cn", "uniqueMember", "description"]
        expectation = {
            'cn': ['1'],
            'description': ['Internationaler Kongress (kongress)'],
            'uniqueMember': [
                'uid=23,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames'],
        }

        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation,
                                  search_base=search_base)

    def test_dsa_entity(self) -> None:
        """Check if all attributes of dsas are correctly present."""
        dsa_cn = "test"
        attributes = ["objectclass", "cn", "userPassword"]
        expectation: Dict[str, List[str]] = {
            'cn': ['test'],
            'objectClass': ['organizationalRole', 'simpleSecurityObject'],
            # this is empty, since dsas may not retrieve the password, but only
            # authenticate against them
            'userPassword': [],
        }
        search_filter = (
            "(&"
            "(objectClass=organizationalRole)"
            f"(cn={dsa_cn})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)

    def test_search_groups_of_user(self) -> None:
        # Garcia has status fields, is orga, subscriber and ml moderator
        user_id = 7
        expectation = {
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_member,ou=status,ou=groups,dc=cde-ev,dc=de',

            'cn=aka@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=all@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=announce@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=info@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=kanonisch@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=mitgestaltung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=participants@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=werbung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',

            'cn=aka@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=test-gast@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=participants@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=wait@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',

            'cn=1,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
            'cn=3,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
        }
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        with ldap3.Connection(self.server, user=self.test_dsa_dn, password=self.test_dsa_pw) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names: Set[str] = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(result_names, expectation)

        # Kalif has status fields, is presider, subscriber and moderator
        user_id = 23
        expectation = {
            'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',

            'cn=kongress@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=opt@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=wal@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',

            'cn=kanonisch@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',

            'cn=1,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
            'cn=3,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
        }
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        with ldap3.Connection(self.server, user=self.test_dsa_dn, password=self.test_dsa_pw) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(result_names, expectation)

    def test_search_attributes_of_groups_of_user(self) -> None:
        user_id = 10
        group_cn = "42@lists.cde-ev.de"
        attributes = ['objectclass', 'cn']
        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            f"(cn={group_cn})"
            ")"
        )
        expectation = {
            'cn': ['42@lists.cde-ev.de'],
            'objectClass': ['groupOfUniqueNames']
        }
        self.single_result_search(search_filter, attributes, expectation)

    def test_search_user_attributes(self) -> None:
        """Search a user by given attributes and return some of its attributes."""
        user_id = 9
        user_mail = "inga@example.cde"
        attributes = ["objectclass", "cn", "givenName", "mail", "uid"]
        expectation = {
            'uid': ['9'],
            'mail': ['inga@example.cde'],
            'cn': ['Inga Iota'],
            'givenName': ['Inga'],
            'objectClass': ['inetOrgPerson'],
        }

        # First, test search by uid
        search_filter = (
            "(&"
            "(objectClass=inetOrgPerson)"
            f"(uid={user_id})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)

        # Second, test search by email
        search_filter = (
            "(&"
            "(objectClass=inetOrgPerson)"
            f"(mail={user_mail})"
            ")"
        )
        self.single_result_search(search_filter, attributes, expectation)
