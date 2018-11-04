#!/usr/bin/env python3

import ldap3

url = "ldap://localhost"
user = "cn=root,dc=cde-ev,dc=de"
password = "s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0"

ldap_server = ldap3.Server(url)
with ldap3.Connection(ldap_server, user=user, password=password) as ldap_conn:
    print(ldap_conn.search(
        search_base="ou=personas-test,dc=cde-ev,dc=de",
        search_scope=ldap3.LEVEL,
        search_filter='(|(uid=1)(uid=2))',
        attributes=['dn', 'cn', 'displayName', 'mail']))
    print(ldap_conn.entries)
    e = ldap_conn.entries[0]
