---
--- ldap oc helper functions
--- ids of all our ldap object classes
---

CREATE FUNCTION oc_organization_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 1';

CREATE FUNCTION oc_organizationalUnit_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 2';

CREATE FUNCTION oc_organizationalRole_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 3';

CREATE FUNCTION oc_inetOrgPerson_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 10';

---
--- ldap node helper functions
--- ids of hardcoded ldap tree nodes
---

CREATE FUNCTION node_cde_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 1';

CREATE FUNCTION node_users_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 10';

CREATE FUNCTION node_groups_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 11';

CREATE FUNCTION node_dsa_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 12';

---
--- serial id offset helper functions
--- To store multiple serial tables in a bigserial one, we simply shift the id
--- of each serial table by this value (maximum store of serial)
---
CREATE FUNCTION make_organization_entity_id(organization_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
-- TODO this is not independent of the chosen offset
$$ SELECT $1; $$ ;

CREATE FUNCTION make_dsa_entity_id(dsa_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST(1 AS BIGINT)<<32 + $1; $$ ;

CREATE FUNCTION make_persona_entity_id(persona_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST(2 AS BIGINT)<<32 + $1; $$ ;

CREATE FUNCTION make_static_group_entity_id(static_group_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST(3 AS BIGINT)<<32 + $1; $$ ;

---
--- ldap helper tables (in public schema)
--- this add some helper tables to satisfy the requirements of the ldap back-sql
--- schema. Some of them add real new data which is required for middle-nodes in
--- the ldap there, others are just query views on existent data which is
--- scattered over multiple tables.
---

-- helper nodes to satisfy the ldap-tree conventions
DROP TABLE IF EXISTS ldap_organizations;
CREATE TABLE ldap_organizations (
	id serial PRIMARY KEY,
	dn varchar NOT NULL,
	oc_map_id integer NOT NULL,  -- REFERENCES ldap_oc_mappings(id)
	parent integer NOT NULL,  -- REFERENCES ldap_entries(id)
	-- maps ldap 'o' attribute
	display_name varchar NOT NULL,
	-- to be set in 'ldap_entry_objclasses'
	additional_object_class varchar DEFAULT NULL
);
GRANT ALL ON ldap_organizations TO cdb_admin;

INSERT INTO ldap_organizations (id, dn, oc_map_id, parent, display_name, additional_object_class) VALUES
    -- The overall organization
    (node_cde_id(), 'dc=cde-ev,dc=de', oc_organization_id(), 0, 'CdE e.V.', 'dcObject'),
    -- All organizational units
    (node_users_id(), 'ou=users,dc=cde-ev,dc=de', oc_organizationalUnit_id(), node_cde_id(), 'Users', NULL),
    (node_groups_id(), 'ou=groups,dc=cde-ev,dc=de', oc_organizationalUnit_id(), node_cde_id(), 'Groups', NULL),
    (node_dsa_id(), 'ou=dsa,dc=cde-ev,dc=de', oc_organizationalUnit_id(), node_cde_id(), 'Directory System Agent', NULL);

-- ldap Directory System Agents
DROP TABLE IF EXISTS ldap_agents;
CREATE TABLE ldap_agents (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
    password_hash varchar NOT NULL
);
GRANT ALL ON ldap_agents TO cdb_admin;

---
--- ldap tables for back-sql (in public schema)
--- this is taken with minimal modifications from
--- servers/slapd/back-sql/rdbms_depend/pgsql/backsql_create.sql
--- in the openldap sources
---

-- Maps ldap object classes to sql tables.
-- Back-sql requires this to be a 1:1 relation. If we store the same ldap object
-- in multiple sql tables (f.e. groupOfUniqueNames), we have to create a helper
-- Query View to collect them all together.
DROP TABLE IF EXISTS ldap_oc_mappings;
CREATE TABLE ldap_oc_mappings (
	id bigserial PRIMARY KEY,
	name varchar(64) NOT NULL,
	-- Table containing all sql entities of this ldap object class.
	-- This is used as 'WHERE keytbl.keycol=ldap_entries.keyval' in queries by
	-- the ldap backend.
	keytbl varchar(64) NOT NULL,
	keycol varchar(64) NOT NULL,
	create_proc varchar(255),
	delete_proc varchar(255),
	expect_return int NOT NULL
);
GRANT ALL ON ldap_oc_mappings TO cdb_admin;

INSERT INTO ldap_oc_mappings (id, name, keytbl, keycol, create_proc, delete_proc, expect_return) VALUES
    (oc_organization_id(), 'organization', 'ldap_organizations', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0),
    (oc_inetOrgPerson_id(), 'inetOrgPerson', 'core.personas', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0),
    (oc_organizationalUnit_id(), 'organizationalUnit', 'ldap_organizations', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0),
    (oc_organizationalRole_id(), 'organizationalRole', 'ldap_agents', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0);


-- Map ldap object class attributes to sql queries to extract them.
DROP TABLE IF EXISTS ldap_attr_mappings;
CREATE TABLE ldap_attr_mappings (
	id bigserial PRIMARY KEY,
	oc_map_id integer NOT NULL REFERENCES ldap_oc_mappings(id),
	name varchar(255) NOT NULL,
	-- this should be a varchar(255). However, we have queries that are longer...
	sel_expr varchar NOT NULL,
	sel_expr_u varchar(255),
	from_tbls varchar(255) NOT NULL,
	join_where varchar(255),
	add_proc varchar(255),
	delete_proc varchar(255),
	param_order int NOT NULL,
	expect_return int NOT NULL
);
GRANT ALL ON ldap_attr_mappings TO cdb_admin;

INSERT INTO ldap_attr_mappings (oc_map_id, name, sel_expr, from_tbls, join_where, add_proc, delete_proc, param_order, expect_return) VALUES
    -- Attributes of organizations
    (oc_organization_id(), 'o', 'ldap_organizations.display_name', 'ldap_organizations', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of organizationalUnits
    (oc_organizationalUnit_id(), 'o', 'ldap_organizations.display_name', 'ldap_organizations', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of agents
    (oc_organizationalRole_id(), 'cn', 'ldap_agents.cn', 'ldap_agents', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    (oc_organizationalRole_id(), 'userPassword', '''{CRYPT}'' || ldap_agents.password_hash', 'ldap_agents', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of inetOrgPerson
    -- Naming was chosen accordingly to the following RFC:
    -- https://datatracker.ietf.org/doc/html/rfc2798 (defining inetOrgPerson)
    -- https://datatracker.ietf.org/doc/html/rfc4519 (defining attributes)
    -- mandatory
    (oc_inetOrgPerson_id(), 'cn', 'personas.given_names || '' '' || personas.family_name', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- mandatory
    (oc_inetOrgPerson_id(), 'sn', 'personas.family_name', 'ldap_organizations', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    (oc_inetOrgPerson_id(), 'displayName',
        '(
            (
                CASE WHEN ((personas.display_name <> '''') AND personas.given_names LIKE ''%'' || personas.display_name || ''%'')
                THEN personas.display_name
                ELSE personas.given_names
                END
            )
            || '' '' || personas.family_name
        )',
     'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    (oc_inetOrgPerson_id(), 'givenName', 'personas.given_names', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    (oc_inetOrgPerson_id(), 'mail', 'personas.username', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- used as distinguish identifier
    (oc_inetOrgPerson_id(), 'uid', 'personas.id', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    (oc_inetOrgPerson_id(), 'userPassword', '''{CRYPT}'' || personas.password_hash', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0);

-- 'Stores' the real ldap entries.
-- This is a SQL View collecting all entries which shall be inserted in ldap
-- togehter. Keyval is the primary identifier specified in 'ldap_oc_mappings'
-- for the given ldap object class
CREATE VIEW ldap_entries (id, dn, oc_map_id, parent, keyval) AS
    -- organizations and organizationalUnits
    (
        SELECT
           make_organization_entity_id(id),
           dn,
           oc_map_id,
           parent,
           id AS keyval
        FROM ldap_organizations
    )
    -- Directory System Agents
    UNION (
        SELECT
           make_dsa_entity_id(id),
           'cn=' || cn || ',ou=dsa,dc=cde-ev,dc=de' AS dn,
           oc_organizationalRole_id() AS oc_map_id,
           node_dsa_id() AS parent,
           id as keyval
        FROM ldap_agents
    )
    -- personas
    UNION (
        SELECT
           make_persona_entity_id(id),
           -- the DB-ID is really static
           'uid=' || id || ',ou=users,dc=cde-ev,dc=de' AS dn,
           oc_inetOrgPerson_id() AS oc_map_id,
           node_users_id() AS parent,
           id as keyval
        FROM core.personas
    )
;
GRANT ALL ON ldap_entries TO cdb_admin;

-- Add additional ldap object classes to an entry with 'entry_id' in
-- 'ldap_entries'.
CREATE VIEW ldap_entry_objclasses (entry_id, oc_name) AS
    -- organizations
    (
        SELECT
           id AS entry_id,
           additional_object_class AS oc_name
        FROM ldap_organizations
        WHERE additional_object_class IS NOT NULL
    )
    -- Directory System Agents
    UNION (
        SELECT
           make_dsa_entity_id(id) AS entry_id,
           'simpleSecurityObject' AS oc_name
        FROM ldap_agents
    )
;
GRANT ALL ON ldap_entry_objclasses TO cdb_admin;

-- create previously impossible references
ALTER TABLE ldap_organizations ADD FOREIGN KEY (oc_map_id) REFERENCES ldap_oc_mappings(id);
-- this SHOULD be a reference. However, one can not create foreign keys on query views...
-- ALTER TABLE ldap_organizations ADD FOREIGN KEY (parent) REFERENCES ldap_entries(id);
