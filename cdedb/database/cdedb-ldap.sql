---
--- ldap stuff (in public schema)
--- this is taken with minimal modifications from
--- servers/slapd/back-sql/rdbms_depend/pgsql/backsql_create.sql
--- in the openldap sources
---

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

-- Helper table to make relations work

DROP TABLE IF EXISTS ldap_organizations;
CREATE TABLE ldap_organizations (
	id serial PRIMARY KEY,
	dn varchar NOT NULL,
	oc_map_id integer NOT NULL REFERENCES ldap_oc_mappings(id),
	-- ist das eine Referenz auf die ID des entsprechenden ldap_entries?
	parent integer NOT NULL,
	-- maps ldap 'o' attribute
	display_name varchar NOT NULL,
	additional_object_class varchar DEFAULT NULL
);
GRANT ALL ON ldap_organizations TO cdb_admin;

-- corresponds to Directory System Agents
DROP TABLE IF EXISTS ldap_agents;
CREATE TABLE ldap_agents (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
    password_hash varchar NOT NULL
);
GRANT ALL ON ldap_agents TO cdb_admin;

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

CREATE VIEW ldap_entries (id, dn, oc_map_id, parent, keyval) AS
    WITH const AS (
        SELECT
            2^32 AS id_offset,

            2 AS persona_oc_id,
            4 AS organizational_role_oc_id,

            10 AS persona_parent,
            12 AS organizational_role_parent
    )
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
           id + const.id_offset,
           'cn=' || cn || ',ou=dsa,dc=cde-ev,dc=de' AS dn,
           const.organizational_role_oc_id AS oc_map_id,
           const.organizational_role_parent AS parent,
           id as keyval
        FROM ldap_agents, const
    )
    -- personas
    UNION (
        SELECT
           id + 2*const.id_offset,
           -- the DB-ID is really static
           'uid=' || id || ',ou=users,dc=cde-ev,dc=de' AS dn,
           const.persona_oc_id AS oc_map_id,
           const.persona_parent AS parent,
           id as keyval
        FROM core.personas, const
    )
;
GRANT ALL ON ldap_entries TO cdb_admin;

CREATE VIEW ldap_entry_objclasses (entry_id, oc_name) AS
    WITH const AS (
        SELECT
            2^32 AS id_offset
    )
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
           id + const.id_offset AS entry_id,
           'simpleSecurityObject' AS oc_name
        FROM ldap_agents, const
    )
;
GRANT ALL ON ldap_entry_objclasses TO cdb_admin;
