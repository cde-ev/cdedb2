-- This file specifies the accounts in the database and should be pretty
-- stable.

-- drop everything to be sure
DROP DATABASE IF EXISTS :cdb_database_name;
DROP DATABASE IF EXISTS cdb;
DROP DATABASE IF EXISTS cdb_test;
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

-- cdb_core_admin has all rights in schema core
DROP ROLE IF EXISTS cdb_core_admin;
CREATE USER cdb_core_admin        PASSWORD '1a2o3e4u5i6d7h8t9n0s1a2o3e4u5i';

-- cdb_cde_admin has all rights in schema cde
DROP ROLE IF EXISTS cdb_cde_admin;
CREATE USER cdb_cde_admin       PASSWORD '1234567890aoeuidhtns1234567890';

-- cdb_event_admin has all rights  in schema event
DROP ROLE IF EXISTS cdb_event_admin;
CREATE USER cdb_event_admin     PASSWORD 'aoeuidhtnsaoeuidhtnsaoeuidhtns';

-- cdb_ml_admin has all rights in schema ml
DROP ROLE IF EXISTS cdb_ml_admin;
CREATE USER cdb_ml_admin        PASSWORD 'aoeuidhtns1234567890aoeuidhtns';

-- cdb_assembly_admin has all rights in schema assembly
DROP ROLE IF EXISTS cdb_assembly_admin;
CREATE USER cdb_assembly_admin  PASSWORD '0987654321snthdiueoa0987654321';

-- cdb_files_admin has all rights in schema files
DROP ROLE IF EXISTS cdb_files_admin;
CREATE USER cdb_files_admin     PASSWORD 'snthdiueoasnthdiueoasnthdiueoa';

-- cdb_i25p_admin has all rights in schema i25p
DROP ROLE IF EXISTS cdb_i25p_admin;
CREATE USER cdb_i25p_admin      PASSWORD 'snthdiueoa0987654321snthdiueoa';

-- cdb_admin has all rights
DROP ROLE IF EXISTS cdb_admin;
CREATE USER cdb_admin           PASSWORD '9876543210abcdefghijklmnopqrst';

GRANT cdb_anonymous TO cdb_persona;
GRANT cdb_persona TO cdb_member;
GRANT cdb_member TO cdb_core_admin;
GRANT cdb_member TO cdb_cde_admin;
GRANT cdb_member TO cdb_event_admin;
GRANT cdb_member TO cdb_ml_admin;
GRANT cdb_member TO cdb_assembly_admin;
GRANT cdb_member TO cdb_files_admin;
GRANT cdb_member TO cdb_i25p_admin;
GRANT cdb_core_admin TO cdb_admin;
GRANT cdb_cde_admin TO cdb_admin;
GRANT cdb_event_admin TO cdb_admin;
GRANT cdb_ml_admin TO cdb_admin;
GRANT cdb_assembly_admin TO cdb_admin;
GRANT cdb_files_admin TO cdb_admin;
GRANT cdb_i25p_admin TO cdb_admin;
