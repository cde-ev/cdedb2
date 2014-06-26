#!/usr/bin/env python3

import ldap

url = "ldap://localhost"
user = "cn=root,dc=cde-ev,dc=de"
password = "s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0"

ldap_con = ldap.initialize(url)
ldap_con.simple_bind_s(user, password)
print(ldap_con.search_s(
    "ou=personas-test,dc=cde-ev,dc=de", ldap.SCOPE_ONELEVEL,
    filterstr='(|(uid=1)(uid=2))',
    attrlist=['cn', 'displayName', 'mail', 'cloudAccount']))
