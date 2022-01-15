"""Use this to repopulate the ldap duas table in the database.

The passwords should be overridden in productions secret config.
"""

from cdedb.backend.core import CoreBackend
from cdedb.script import Script

script = Script(dbuser="cdb_admin")

encrypt = CoreBackend.encrypt_password
sql_input = f"""
BEGIN;
    DELETE FROM ldap.duas;
    INSERT INTO ldap.duas (cn, password_hash) VALUES
        ('admin',      '{encrypt(script._secrets["LDAP_DUA_PW"]["admin"])}'),
        ('apache',     '{encrypt(script._secrets["LDAP_DUA_PW"]["apache"])}'),
        ('cloud',      '{encrypt(script._secrets["LDAP_DUA_PW"]["cloud"])}'),
        ('cyberaka',   '{encrypt(script._secrets["LDAP_DUA_PW"]["cyberaka"])}'),
        ('dokuwiki',   '{encrypt(script._secrets["LDAP_DUA_PW"]["dokuwiki"])}');
COMMIT;
"""

with script._conn as conn:
    conn.set_session(autocommit=True)
    with conn.cursor() as curr:
        curr.execute(sql_input)
