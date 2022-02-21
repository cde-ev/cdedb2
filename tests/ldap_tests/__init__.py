#!/usr/bin/env python3
"""Module containing all tests for the CdEDB-LDAP interface."""

from typing import Dict, List, Set, Union

import ldap3
from ldap3 import ALL_ATTRIBUTES

from tests.common import USER_DICT, BasicTest


class TestLDAP(BasicTest):

    root_dn = 'dc=cde-ev,dc=de'
    test_dua_dn = f'cn=test,ou=duas,{root_dn}'
    test_dua_pw = 'secret'
    admin_dua_dn = f'cn=admin,ou=duas,{root_dn}'
    admin_dua_pw = 'secret'
    server: ldap3.Server

    # all duas except the admin dua
    DUAs = {
        f'cn=apache,ou=duas,{root_dn}': 'secret',
        f'cn=cloud,ou=duas,{root_dn}': 'secret',
        f'cn=cyberaka,ou=duas,{root_dn}': 'secret',
        f'cn=dokuwiki,ou=duas,{root_dn}': 'secret',
        f'cn=test,ou=duas,{root_dn}': 'secret',
    }

    # all users which have a password
    USERS = {
        f'uid={user["id"]},ou=users,dc=cde-ev,dc=de': user['password']
        for user in USER_DICT.values() if user['password']
    }

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.server = ldap3.Server(
            cls.conf['LDAP_HOST'], port=cls.conf['LDAP_PORT'], get_info=ldap3.ALL)

    def single_result_search(
        self, search_filter: str, expectation: Dict[str, List[str]], *,
        user: str = test_dua_dn, password: str = test_dua_pw,
        search_base: str = root_dn,
        attributes: Union[List[str], str] = ALL_ATTRIBUTES
    ) -> None:
        with ldap3.Connection(
            self.server, user=user, password=password, raise_exceptions=True
        ) as conn:
            conn.search(
                search_base=search_base,
                search_filter=search_filter,
                attributes=attributes
            )
            self.assertEqual(len(conn.entries), 1)
            result = conn.entries[0].entry_attributes_as_dict
            self.assertEqual(result, expectation)

    def no_result_search(
        self,
        search_filter: str, *,
        except_users: Set[str] = None,
        search_base: str = root_dn,
        attributes: Union[List[str], str] = ALL_ATTRIBUTES
    ) -> None:
        """Test that this search yields no results for all DUAs and all users.

        The 'except_users' argument may be used to exclude some users from this check.
        """
        users: Dict[str, str] = {**self.DUAs, **self.USERS}
        except_users = except_users or set()
        for user, password in users.items():
            identifier = user.split(sep=",", maxsplit=1)[0]
            with ldap3.Connection(
                self.server, user=user, password=password, raise_exceptions=True
            ) as conn:
                conn.search(
                    search_base=search_base,
                    search_filter=search_filter,
                    attributes=attributes
                )
                try:
                    # if the current user should access the entries, we check if he does
                    if identifier in except_users:
                        self.assertNotEqual(len(conn.entries), 0)
                    else:
                        self.assertEqual(len(conn.entries), 0)
                except AssertionError as e:
                    raise RuntimeError(
                        f"The above error occurred with user '{user}'") from e

    def test_anonymous_bind(self) -> None:
        conn = ldap3.Connection(self.server)
        self.assertTrue(conn.bind())
        self.assertEqual(conn.extend.standard.who_am_i(), None)

    def test_simple_password_bind(self) -> None:
        # try to bind to nonexistent dua
        conn = ldap3.Connection(
            self.server, user='cn=nonexistent,ou=duas,dc=cde-ev,dc=de',
            password=self.test_dua_pw)
        self.assertFalse(conn.bind())

        # try to bind to existent dua with wrong password
        conn = ldap3.Connection(self.server, user=self.test_dua_dn, password='wrongPW')
        self.assertFalse(conn.bind())

        # bind with a dua
        conn = ldap3.Connection(self.server, user=self.test_dua_dn,
                                password=self.test_dua_pw)
        self.assertTrue(conn.bind())
        self.assertEqual('dn:' + self.test_dua_dn, conn.extend.standard.who_am_i())
        self.assertTrue(conn.unbind())

        # try to bind to nonexistent user
        conn = ldap3.Connection(self.server, user='uid=0,ou=users,dc=cde-ev,dc=de',
                                password='secret')
        self.assertFalse(conn.bind())

        # try to bind to existend user with wrong password
        conn = ldap3.Connection(self.server, user='uid=1,ou=users,dc=cde-ev,dc=de',
                                password='wrongPW')
        self.assertFalse(conn.bind())

        # bind with a users
        conn = ldap3.Connection(self.server, user='uid=1,ou=users,dc=cde-ev,dc=de',
                                password='secret')
        self.assertTrue(conn.bind())
        self.assertEqual(
            'dn:' + 'uid=1,ou=users,dc=cde-ev,dc=de', conn.extend.standard.who_am_i())
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
        self.single_result_search(search_filter, expectation, attributes=attributes,
                                  user=user, password=password)

        # users may not access any group and their members
        # However, they are able to access their own group membership by the 'memberOf'
        # attribute
        attributes = ["memberOf"]
        expectation = {
            'memberOf': [
                # pylint: disable=line-too-long
                'cn=42-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=aktivenforum2000@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=all@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=announce@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=everyone-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=info@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_assembly_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cde_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cdelokal_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_core_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_event_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_finance_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_member,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_ml_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_searchable,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=kanonisch@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=klatsch@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=kongress@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=lokalgruppen-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=migration-owner@testmail.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=mitgestaltung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=moderatoren-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=orgas-2,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
                'cn=orgas-3,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
                'cn=participants@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=party50@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=party50-all-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=party50-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=platin@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=platin-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=werbung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=witz@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de'
            ]
        }
        self.single_result_search(search_filter, expectation, attributes=attributes,
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

    # TODO test encrypted connections (tls)

    def test_organization_entity(self) -> None:
        """Check if all attributes of the organization are correctly present."""
        expectation = {
            'objectClass': [
                'organization',
                'dcObject',
                'top'
            ],
            'o': ['CdE e.V.']
        }
        search_filter = "(objectClass=organization)"
        self.single_result_search(search_filter, expectation)

    def test_organizational_unit_entity(self) -> None:
        """Check if all attributes of an organizational unit are correctly present."""
        organizational_unit_o = "Users"
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
        self.single_result_search(search_filter, expectation)

    def test_user_entity(self) -> None:
        """Check if all attributes of an user are correctly present."""
        user_id = 1
        expectation: Dict[str, List[str]] = {
            'uid': ['1'],
            'mail': ['anton@example.cde'],

            'cn': ['Anton Armin A. Administrator'],
            'displayName': ['Anton Administrator'],
            'givenName': ['Anton Armin A.'],
            'sn': ['Administrator'],

            # there is no password returned, since passwords may not be retrived but
            # only used for binding
            'objectClass': ['inetOrgPerson'],
        }
        search_filter = (
            "(&"
            "(objectClass=inetOrgPerson)"
            f"(uid={user_id})"
            ")"
        )
        self.single_result_search(search_filter, expectation)

    def test_static_group_entity(self) -> None:
        """Check if all attributes of static groups are correctly present."""
        group_cn = "is_cdelokal_admin"
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        self.single_result_search(search_filter, expectation, user=self.admin_dua_dn,
                                  password=self.admin_dua_pw)

    def test_ml_subscriber_group_entity(self) -> None:
        """Check if all attributes of ml-subscriber groups are correctly present."""
        group_cn = "gutscheine@lists.cde-ev.de"
        search_base = "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de"
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_ml_moderator_group_entity(self) -> None:
        """Check if all attributes of ml-moderator groups are correctly present."""
        group_cn = "gutscheine-owner@lists.cde-ev.de"
        search_base = "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': ['gutscheine-owner@lists.cde-ev.de'],
            'description': ['Gutscheine <gutscheine-owner@lists.cde-ev.de>'],
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_event_orgas_group_entity(self) -> None:
        """Check if all attributes of event-orga groups are correctly present."""
        group_cn = "orgas-1"
        search_base = "ou=event-orgas,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': [group_cn],
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_assembly_presiders_group_entity(self) -> None:
        """Check if all attributes of assembly-presider groups are correctly present."""
        group_cn = "presiders-1"
        search_base = "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': [group_cn],
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_dua_entity(self) -> None:
        """Check if all attributes of DUAs are correctly present."""
        dua_cn = "test"
        expectation: Dict[str, List[str]] = {
            'cn': ['test'],
            'objectClass': ['person', 'simpleSecurityObject'],
            # there is no password returned, since passwords may not be retrived but
            # only used for binding
        }
        search_filter = (
            "(&"
            "(objectClass=person)"
            f"(cn={dua_cn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cn=test"})
        self.single_result_search(search_filter, expectation)

    def test_search_groups_of_user(self) -> None:
        # Garcia has status fields, is orga, subscriber and ml moderator
        user_id = 7
        expectation = {
            # pylint: disable=line-too-long
            # status
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_member,ou=status,ou=groups,dc=cde-ev,dc=de',
            # subscriber
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
            # moderator
            'cn=aka-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=test-gast-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=participants-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=wait-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            # orga
            'cn=orgas-1,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
            'cn=orgas-3,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
        }
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        with ldap3.Connection(
                self.server, user=self.admin_dua_dn, password=self.admin_dua_pw
        ) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names: Set[str] = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(result_names, expectation)

        # Kalif has status fields, is presider, subscriber and moderator
        user_id = 23
        expectation = {
            # pylint: disable=line-too-long
            # status
            'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            # subscriber
            'cn=kongress@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=opt@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=wal@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            # moderators
            'cn=kanonisch-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            # presider
            'cn=presiders-1,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
            'cn=presiders-3,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
        }
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        with ldap3.Connection(
            self.server, user=self.admin_dua_dn, password=self.admin_dua_pw
        ) as conn:
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
        self.no_result_search(search_filter, except_users={"cn=cloud"})
        # TODO use appropiate non-admin-dua here
        self.single_result_search(search_filter, expectation, attributes=attributes,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

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
        self.single_result_search(search_filter, expectation, attributes=attributes)

        # Second, test search by email
        search_filter = (
            "(&"
            "(objectClass=inetOrgPerson)"
            f"(mail={user_mail})"
            ")"
        )
        self.single_result_search(search_filter, expectation, attributes=attributes)
