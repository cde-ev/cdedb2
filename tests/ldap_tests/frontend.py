#!/usr/bin/env python3
"""Module containing all tests for the CdEDB-LDAP interface."""

import ssl
from typing import Dict, List, Optional, Set, Union

import ldap3
from ldap3 import ALL_ATTRIBUTES
from ldap3.core.tls import Tls

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
        "apache": f'cn=apache,ou=duas,{root_dn}',
        "cloud": f'cn=cloud,ou=duas,{root_dn}',
        "cyberaka": f'cn=cyberaka,ou=duas,{root_dn}',
        "dokuwiki": f'cn=dokuwiki,ou=duas,{root_dn}',
        "rqt": f'cn=rqt,ou=duas,{root_dn}',
        "test": f'cn=test,ou=duas,{root_dn}',
    }
    DUA_passwords = {
        "apache": "secret",
        "cloud": "secret",
        "cyberaka": "secret",
        "dokuwiki": "secret",
        "rqt": "secret",
        "test": "secret",
    }

    # all users which have a password
    USERS = {
        user: f'uid={value["id"]},ou=users,dc=cde-ev,dc=de'
        # take only non-archived users into account
        for user, value in USER_DICT.items() if value['username']
    }
    USER_passwords = {
        user: value['password']
        # take only non-archived users into account
        for user, value in USER_DICT.items() if value['username']
    }

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=cls.conf["LDAP_PEM_PATH"])
        cls.server = ldap3.Server(
            cls.conf['LDAP_HOST'], port=cls.conf['LDAP_PORT'], get_info=ldap3.ALL,
            use_ssl=True, tls=tls)

    def single_result_search(
        self, search_filter: str, raw_expectation: Dict[str, List[str]], *,
        user: str = test_dua_dn, password: str = test_dua_pw,
        search_base: str = root_dn,
        attributes: Union[List[str], str] = ALL_ATTRIBUTES,
        excluded_attributes: Optional[List[str]] = None,
    ) -> None:
        with ldap3.Connection(
            self.server, user=user, password=password, raise_exceptions=True
        ) as conn:
            conn.search(
                search_base=search_base,
                search_filter=search_filter,
                attributes=attributes
            )
            self.assertEqual(1, len(conn.entries), conn.entries)
            raw_result: Dict[str, List[str]] = conn.entries[0].entry_attributes_as_dict
            # Accordingly to RFC 4511, attributes and values of attributes are unordered
            result = {key: set(values) for key, values in raw_result.items()}
            expectation = {key: set(values) for key, values in raw_expectation.items()}
            if excluded_attributes:
                for attribute in excluded_attributes:
                    result.pop(attribute)
            self.assertEqual(expectation, result)

    def no_result_search(
        self,
        search_filter: str, *,
        except_users: Optional[Set[str]] = None,
        search_base: str = root_dn,
        attributes: Union[List[str], str] = ALL_ATTRIBUTES
    ) -> None:
        """Test that this search yields no results for all DUAs and all users.

        The 'except_users' argument may be used to exclude some users from this check.
        """
        users: Dict[str, str] = {**self.DUAs, **self.USERS}
        passwords: Dict[str, str] = {**self.DUA_passwords, **self.USER_passwords}
        except_users = except_users or set()
        for user in users:
            with self.subTest(user):
                with ldap3.Connection(
                    self.server, user=users[user], password=passwords[user],
                    raise_exceptions=True
                ) as conn:
                    conn.search(
                        search_base=search_base,
                        search_filter=search_filter,
                        attributes=attributes
                    )
                    # if the current user should access the entries, we check if he does
                    if user in except_users:
                        self.assertNotEqual(0, len(conn.entries), conn.entries)
                    else:
                        self.assertEqual(0, len(conn.entries), conn.entries)

    def test_anonymous_bind(self) -> None:
        conn = ldap3.Connection(self.server)
        self.assertTrue(conn.bind())
        # TODO not supported by ldaptor
        # self.assertEqual(conn.extend.standard.who_am_i(), None)

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
        # TODO not supported by ldaptor
        # self.assertEqual('dn:' + self.test_dua_dn, conn.extend.standard.who_am_i())
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
        # TODO not supported by ldaptor
        # self.assertEqual(
        #     'dn:' + 'uid=1,ou=users,dc=cde-ev,dc=de', conn.extend.standard.who_am_i())
        self.assertTrue(conn.unbind())

    def test_anonymous_compare(self) -> None:
        conn = ldap3.Connection(self.server)
        conn.bind()
        conn.compare("dc=de", "dc", "asdf")
        self.assertEqual("unwillingToPerform", conn.result["description"])

    def test_compare(self) -> None:
        user = "anton"
        user_dn = self.USERS[user]
        with ldap3.Connection(
            self.server, user=user_dn, password=self.USER_passwords[user],
            raise_exceptions=True
        ) as conn:
            conn.compare(user_dn, "sn", "Administrator")
            self.assertEqual("compareTrue", conn.result["description"])
            conn.compare(user_dn, "sn", "Beispiel")
            self.assertEqual("compareFalse", conn.result["description"])

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
        attributes = ["objectClass", "cn"]
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
                'cn=everyone-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=info@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_assembly_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cde_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
                'cn=is_cdelokal_admin,ou=status,ou=groups,dc=cde-ev,dc=de',
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
                'cn=moderatoren-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=orgas-2,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
                'cn=orgas-3,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
                'cn=participants@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=party50-all-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=party50-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=party50@aka.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=platin-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
                'cn=platin@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=werbung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=witz@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
                'cn=gu@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
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
                'dcObject',
                'organization',
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
            'ipaUniqueID': ['personas/1'],

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
        self.single_result_search(
            search_filter, expectation, excluded_attributes=["memberOf"])

    def test_static_group_entity(self) -> None:
        """Check if all attributes of static groups are correctly present."""
        group_cn = "is_cdelokal_admin"
        expectation = {
            'cn': ['is_cdelokal_admin'],
            'description': ['CdELokal-Administratoren'],
            'ipaUniqueID': ['status_groups/is_cdelokal_admin'],
            'uniqueMember': [
                'uid=1,ou=users,dc=cde-ev,dc=de',
                'uid=100,ou=users,dc=cde-ev,dc=de',
                'uid=38,ou=users,dc=cde-ev,dc=de'
            ],
            'objectClass': ['groupOfUniqueNames']
        }
        search_filter = (
            "(&"
            "(objectClass=groupOfUniqueNames)"
            f"(cn={group_cn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cloud", "apache"})
        self.single_result_search(search_filter, expectation, user=self.admin_dua_dn,
                                  password=self.admin_dua_pw)

    def test_ml_subscriber_group_entity(self) -> None:
        """Check if all attributes of ml-subscriber groups are correctly present."""
        group_cn = "gutscheine@lists.cde-ev.de"
        search_base = "ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': ['gutscheine@lists.cde-ev.de'],
            'description': ['Gutscheine <gutscheine@lists.cde-ev.de>'],
            'ipaUniqueID': ['mls/gutscheine@lists.cde-ev.de'],
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
        self.no_result_search(search_filter, except_users={"cloud", "apache", "rqt"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_ml_moderator_group_entity(self) -> None:
        """Check if all attributes of ml-moderator groups are correctly present."""
        group_cn = "gutscheine-owner@lists.cde-ev.de"
        search_base = "ou=ml-moderators,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': ['gutscheine-owner@lists.cde-ev.de'],
            'description': ['Gutscheine <gutscheine-owner@lists.cde-ev.de>'],
            'ipaUniqueID': ['ml_moderator_groups/gutscheine@lists.cde-ev.de'],
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
        self.no_result_search(search_filter, except_users={"cloud", "apache"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_event_orgas_group_entity(self) -> None:
        """Check if all attributes of event-orga groups are correctly present."""
        group_cn = "orgas-1"
        search_base = "ou=event-orgas,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': [group_cn],
            'description': ['Große Testakademie 2222 (TestAka)'],
            'ipaUniqueID': ['event_orga_groups/1'],
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
        self.no_result_search(search_filter, except_users={"cloud", "apache"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_assembly_presiders_group_entity(self) -> None:
        """Check if all attributes of assembly-presider groups are correctly present."""
        group_cn = "presiders-1"
        search_base = "ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de"
        expectation = {
            'cn': [group_cn],
            'description': ['Internationaler Kongress (kongress)'],
            'ipaUniqueID': ['assembly_presider_groups/1'],
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
        self.no_result_search(search_filter, except_users={"cloud", "apache"})
        self.single_result_search(search_filter, expectation, search_base=search_base,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_dua_entity(self) -> None:
        """Check if all attributes of DUAs are correctly present."""
        dua_cn = "test"
        expectation: Dict[str, List[str]] = {
            'cn': ['test'],
            'ipaUniqueID': ['duas/test'],
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
        self.no_result_search(search_filter, except_users={"test"})
        self.single_result_search(search_filter, expectation)

    def test_search_groups_of_user(self) -> None:
        # Garcia has status fields, is orga, subscriber and ml moderator
        user_id = 7
        expectation_status = {
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_member,ou=status,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_subscriber = {
            # pylint: disable=line-too-long
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
            'cn=gu@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_moderator = {
            # pylint: disable=line-too-long
            'cn=aka-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=test-gast-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=participants-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=wait-owner@aka.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_orga = {
            'cn=orgas-1,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
            'cn=orgas-3,ou=event-orgas,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_presider: Set[str] = set()
        expectation_all = {
            *expectation_status, *expectation_subscriber, *expectation_moderator,
            *expectation_orga, *expectation_presider}
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cloud", "apache", "rqt"})
        with ldap3.Connection(
                self.server, user=self.admin_dua_dn, password=self.admin_dua_pw
        ) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names: Set[str] = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(expectation_all, result_names)
        with ldap3.Connection(
                self.server, user=self.DUAs["rqt"], password=self.DUA_passwords["rqt"]
        ) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(expectation_subscriber, result_names)

        # Werner has status fields, is presider, subscriber and moderator
        user_id = 23
        expectation_status = {
            'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
            'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_subscriber = {
            # pylint: disable=line-too-long
            'cn=everyone@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=moderatoren@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=opt@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
            'cn=wal@lists.cde-ev.de,ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_moderator = {
            # pylint: disable=line-too-long
            'cn=kanonisch-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-leitung-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
            'cn=kongress-owner@lists.cde-ev.de,ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_orga: Set[str] = set()
        expectation_presider = {
            'cn=presiders-1,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
            'cn=presiders-3,ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',
        }
        expectation_all = {
            *expectation_status, *expectation_subscriber, *expectation_moderator,
            *expectation_orga, *expectation_presider}
        search_filter = (
            "(&"
                "(objectClass=groupOfUniqueNames)"
                f"(uniqueMember=uid={user_id},ou=users,{self.root_dn})"
            ")"
        )
        self.no_result_search(search_filter, except_users={"cloud", "apache", "rqt"})
        with ldap3.Connection(
            self.server, user=self.admin_dua_dn, password=self.admin_dua_pw
        ) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(expectation_all, result_names)
        with ldap3.Connection(
                self.server, user=self.DUAs["rqt"], password=self.DUA_passwords["rqt"]
        ) as conn:
            conn.search(search_base=self.root_dn, search_filter=search_filter)
            result_names = {entry.entry_dn for entry in conn.entries}
            self.assertEqual(expectation_subscriber, result_names)

    def test_search_attributes_of_groups_of_user(self) -> None:
        user_id = 10
        group_cn = "42@lists.cde-ev.de"
        attributes = ['objectClass', 'cn']
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
        self.no_result_search(search_filter, except_users={"cloud", "apache", "rqt"})
        # TODO use appropiate non-admin-dua here
        self.single_result_search(search_filter, expectation, attributes=attributes,
                                  user=self.admin_dua_dn, password=self.admin_dua_pw)

    def test_search_user_attributes(self) -> None:
        """Search a user by given attributes and return some of its attributes."""
        user_id = 9
        user_mail = "inga@example.cde"
        attributes = ["objectClass", "cn", "givenName", "mail", "uid"]
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
            "(objectclass=*)"
            f"(mail={user_mail})"
            ")"
        )
        self.single_result_search(search_filter, expectation, attributes=attributes)

    def test_search_pagination(self) -> None:
        """Test search with pagedResultsControl."""
        search_filter = (
            "(&"
            "(objectclass=inetOrgPerson)"
            ")"
        )

        with ldap3.Connection(
            self.server, user=self.test_dua_dn, password=self.test_dua_pw,
            raise_exceptions=True
        ) as conn:
            # first page
            conn.search(
                search_base=self.root_dn,
                search_filter=search_filter,
                paged_size=2,
                paged_cookie=None,
                attributes=["uid"],
            )
            self.assertEqual(2, len(conn.entries))
            self.assertEqual(['1'], conn.entries[0].entry_attributes_as_dict["uid"])
            self.assertEqual(['2'], conn.entries[1].entry_attributes_as_dict["uid"])

            # second page
            cookie = conn.result["controls"]["1.2.840.113556.1.4.319"]\
                ["value"]["cookie"]
            self.assertNotEqual(b"", cookie)
            conn.search(
                search_base=self.root_dn,
                search_filter=search_filter,
                paged_size=2,
                paged_cookie=cookie,
                attributes=["uid"],
            )
            self.assertEqual(2, len(conn.entries))
            self.assertEqual(['3'], conn.entries[0].entry_attributes_as_dict["uid"])
            self.assertEqual(['4'], conn.entries[1].entry_attributes_as_dict["uid"])

            # next try, with more results
            # first page
            conn.search(
                search_base=self.root_dn,
                search_filter=search_filter,
                paged_size=20,
                paged_cookie=None,
                attributes=["uid"],
            )
            self.assertEqual(20, len(conn.entries))

            # second and last page
            cookie = conn.result["controls"]["1.2.840.113556.1.4.319"]\
                ["value"]["cookie"]
            size = conn.result["controls"]["1.2.840.113556.1.4.319"]["value"]["size"]
            self.assertNotEqual(b"", cookie)
            self.assertLess(size, 40)
            conn.search(
                search_base=self.root_dn,
                search_filter=search_filter,
                paged_size=20,
                paged_cookie=cookie,
                attributes=["uid"],
            )
            self.assertLess(len(conn.entries), 20)
            cookie = conn.result["controls"]["1.2.840.113556.1.4.319"]\
                ["value"]["cookie"]
            self.assertEqual(b"", cookie)

    def test_caseinsensitive_attributes(self) -> None:
        user_id = 9
        attributes = ["objectClass", "cn", "givenName", "mail", "uid"]
        expectation = {
            'uid': ['9'],
            'mail': ['inga@example.cde'],
            'cn': ['Inga Iota'],
            'givenName': ['Inga'],
            'objectClass': ['inetOrgPerson'],
        }

        search_filter = (
            "(&"
            "(oBjeCtclASS=*)"
            f"(UID={user_id})"
            ")"
        )
        self.single_result_search(search_filter, expectation, attributes=attributes)
