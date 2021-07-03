---
--- ldap oc helper functions
--- ids of all our ldap object classes
---

CREATE FUNCTION oc_organization_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 1';

CREATE FUNCTION oc_organizationalUnit_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 3';

CREATE FUNCTION oc_organizationalRole_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 4';

CREATE FUNCTION oc_inetOrgPerson_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 2';

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
CREATE FUNCTION id_offset()
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
'SELECT 2^32';

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

-- Map ldap object class attributes to sql queries to extract them.
DROP TABLE IF EXISTS ldap_attr_mappings;
CREATE TABLE ldap_attr_mappings (
	id bigserial PRIMARY KEY,
	oc_map_id integer NOT NULL REFERENCES ldap_oc_mappings(id),
	name varchar(255) NOT NULL,
	sel_expr varchar(255) NOT NULL,
	sel_expr_u varchar(255),
	from_tbls varchar(255) NOT NULL,
	join_where varchar(255),
	add_proc varchar(255),
	delete_proc varchar(255),
	param_order int NOT NULL,
	expect_return int NOT NULL
);
GRANT ALL ON ldap_attr_mappings TO cdb_admin;

-- 'Stores' the real ldap entries.
-- This is a SQL View collecting all entries which shall be inserted in ldap
-- togehter. Keyval is the primary identifier specified in 'ldap_oc_mappings'
-- for the given ldap object class
CREATE VIEW ldap_entries (id, dn, oc_map_id, parent, keyval) AS
    -- organizations and organizationalUnits
    (
        SELECT
           id,
           dn,
           oc_map_id,
           parent,
           id AS keyval
        FROM ldap_organizations
    )
    -- Directory System Agents
    UNION (
        SELECT
           id + id_offset(),
           'cn=' || cn || ',ou=dsa,dc=cde-ev,dc=de' AS dn,
           oc_organizationalRole_id() AS oc_map_id,
           node_dsa_id() AS parent,
           id as keyval
        FROM ldap_agents
    )
    -- personas
    UNION (
        SELECT
           id + 2*id_offset(),
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
           id + id_offset() AS entry_id,
           'simpleSecurityObject' AS oc_name
        FROM ldap_agents
    )
;
GRANT ALL ON ldap_entry_objclasses TO cdb_admin;

-- create previously impossible references
ALTER TABLE ldap_organizations ADD FOREIGN KEY (oc_map_id) REFERENCES ldap_oc_mappings(id);
-- this SHOULD be a reference. However, one can not create foreign keys on query views...
-- ALTER TABLE ldap_organizations ADD FOREIGN KEY (parent) REFERENCES ldap_entries(id);
