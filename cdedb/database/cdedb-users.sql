-- This file specifies the accounts in the database and should be pretty stable

-- drop everything to be sure
DROP DATABASE IF EXISTS cdb WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_1 WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_2 WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_3 WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_4 WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_ldap WITH (FORCE);
DROP DATABASE IF EXISTS cdb_test_xss WITH (FORCE);
-- master user cdb -- do not use in code
DROP ROLE IF EXISTS cdb;
CREATE USER cdb                 PASSWORD '987654321098765432109876543210';

-- cdb_anonymous mostly does authentication (checking user existence/passwords)
DROP ROLE IF EXISTS cdb_anonymous;
CREATE USER cdb_anonymous       PASSWORD '012345678901234567890123456789';

-- cdb_persona has the rights of a logged in non-CdE user
DROP ROLE IF EXISTS cdb_persona;
CREATE USER cdb_persona         PASSWORD 'abcdefghijklmnopqrstuvwxyzabcd';

-- cdb_member has the rights of a CdE members
DROP ROLE IF EXISTS cdb_member;
CREATE USER cdb_member          PASSWORD 'zyxwvutsrqponmlkjihgfedcbazyxw';

-- cdb_admin has all rights
DROP ROLE IF EXISTS cdb_admin;
CREATE USER cdb_admin           PASSWORD '9876543210abcdefghijklmnopqrst';

-- cdb_ldap is used by ldaptor to perform SELECTs on the database.
-- therefore, it is outside of the privilege tier and directly below cdb
DROP ROLE IF EXISTS cdb_ldap;
CREATE USER cdb_ldap            PASSWORD '1234567890zyxwvutsrqponmlkjihg';

GRANT cdb_anonymous TO cdb_persona;
GRANT cdb_persona TO cdb_member;
GRANT cdb_member TO cdb_admin;
GRANT cdb_admin TO cdb;
GRANT cdb_ldap TO cdb;
