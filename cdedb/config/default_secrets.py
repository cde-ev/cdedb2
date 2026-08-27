# database users
CDB_DATABASE_ROLES = {
    "nobody": "nobody",  # use only to set up internal details like sample-data!
    "cdb_anonymous": "012345678901234567890123456789",
    "cdb_persona": "abcdefghijklmnopqrstuvwxyzabcd",
    "cdb_member": "zyxwvutsrqponmlkjihgfedcbazyxw",
    "cdb_admin": "9876543210abcdefghijklmnopqrst",
    "cdb_ldap": "1234567890zyxwvutsrqponmlkjihg",
    "cdb": "987654321098765432109876543210",  # only used for testsuite
}

# salting value used for verifying sensitve url parameters
URL_PARAMETER_SALT = "aoeuidhtns9KT6AOR2kNjq2zO"

# salting value used for verifying password reset authorization
RESET_SALT = "aoeuidhtns9KT6AOR2kNjq2zO"

# encrypt complaint descriptions with this secret to prevent accidental retrieval/leaks.
COMPLAINT_SECRET = b'gy81i7pj8-0WkTweXbUxBykgA38V2aSEOoPizqXWVGg='

# mailman REST API password
MAILMAN_PASSWORD = "secret"

# password for mailman to retrieve templates
MAILMAN_BASIC_AUTH_PASSWORD = "secret"

# fixed tokens for API access
API_TOKENS = {
    # resolve API for CyberAka
    "resolve": "a1o2e3u4i5d6h7t8n9s0",
    # zero-config partial export in offline mode
    "quick_partial_export": "y1f2i3d4x5b6",
}

# ldap related stuff
LDAP_DUA_PW = {
    # special dua without access restrictions
    "admin": "secret",
    "apache": "secret",
    "keycloak": "secret",
    "test": "secret",
}
