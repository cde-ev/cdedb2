---
--- ldap oc helper functions
--- ids of all our ldap object classes
---

CREATE FUNCTION oc_organization_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 1; $$;

CREATE FUNCTION oc_organizationalUnit_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 2; $$;

CREATE FUNCTION oc_organizationalRole_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 3; $$;

CREATE FUNCTION oc_inetOrgPerson_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 10; $$;

CREATE FUNCTION oc_groupOfUniqueNames_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 20; $$;

---
--- ldap node helper functions
--- ids of hardcoded ldap tree nodes
---

CREATE FUNCTION node_cde_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 1; $$;

CREATE FUNCTION node_users_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 10; $$;

CREATE FUNCTION node_groups_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 11; $$;

CREATE FUNCTION node_dsa_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 12; $$;

CREATE FUNCTION node_mailinglist_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 15; $$;

CREATE FUNCTION node_static_group_is_active_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 20; $$;

CREATE FUNCTION node_static_group_is_member_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 21; $$;

CREATE FUNCTION node_static_group_is_searchable_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 22; $$;

CREATE FUNCTION node_static_group_is_ml_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 30; $$;

CREATE FUNCTION node_static_group_is_event_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 31; $$;

CREATE FUNCTION node_static_group_is_assembly_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 32; $$;

CREATE FUNCTION node_static_group_is_cde_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 33; $$;

CREATE FUNCTION node_static_group_is_ml_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 40; $$;

CREATE FUNCTION node_static_group_is_event_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 41; $$;

CREATE FUNCTION node_static_group_is_assembly_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 42; $$;

CREATE FUNCTION node_static_group_is_cde_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 43; $$;

CREATE FUNCTION node_static_group_is_core_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 44; $$;

CREATE FUNCTION node_static_group_is_finance_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 45; $$;

CREATE FUNCTION node_static_group_is_cdelokal_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 46; $$;

---
--- serial id offset helper functions
--- To store multiple serial tables in a bigserial one, we simply shift the id
--- of each serial table by this value (maximum store of serial)
---
CREATE FUNCTION make_organization_entity_id(organization_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 1 * 2^32 + $1; $$ ;

CREATE FUNCTION make_dsa_entity_id(dsa_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 2 * 2^32 + $1; $$ ;

CREATE FUNCTION make_persona_entity_id(persona_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 3 * 2^32 + $1; $$ ;

CREATE FUNCTION make_static_group_entity_id(static_group_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 4 * 2^32 + $1; $$ ;

CREATE FUNCTION make_mailinglist_entity_id(mailinglist_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 5 * 2^32 + $1; $$ ;

---
--- create dn
--- Some dn's are used at multiple places. To ensure consistency, we define a
--- function for them here. Other dn's are specified in 'ldap_entries'.
---

CREATE FUNCTION make_persona_dn(persona_id INT)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 'uid=' || $1 || ',ou=users,dc=cde-ev,dc=de'; $$ ;

-- This seems to be allowed, see
-- https://datatracker.ietf.org/doc/html/rfc4512#section-2.3.2
CREATE FUNCTION make_mailinglist_cn(mailinglist_address VARCHAR)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT $1 ; $$ ;

CREATE FUNCTION make_persona_display_name(display_name VARCHAR, given_names VARCHAR, family_name VARCHAR)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$
    SELECT (
        CASE WHEN
            (
                ( $1 <> '')
                    AND $2 LIKE '%' || $1 || '%'
            )
        THEN $1
        ELSE $2
        END
    )
    || ' ' || $3
    ;
$$;

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
	parent bigint NOT NULL,  -- REFERENCES ldap_entries(id)
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
        (node_users_id(), 'ou=users,dc=cde-ev,dc=de', oc_organizationalUnit_id(), make_organization_entity_id(node_cde_id()), 'Users', NULL),
        (node_groups_id(), 'ou=groups,dc=cde-ev,dc=de', oc_organizationalUnit_id(), make_organization_entity_id(node_cde_id()), 'Groups', NULL),
        (node_dsa_id(), 'ou=dsa,dc=cde-ev,dc=de', oc_organizationalUnit_id(), make_organization_entity_id(node_cde_id()), 'Directory System Agent', NULL),
    -- Additional organizational units holding group of groups
        (node_mailinglist_group_id(), 'ou=mailinglists,ou=groups,dc=cde-ev,dc=de', oc_organizationalUnit_id(), make_organization_entity_id(node_groups_id()), 'Mailinglists', NULL);

-- ldap Directory System Agents
DROP TABLE IF EXISTS ldap_agents;
CREATE TABLE ldap_agents (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
    password_hash varchar NOT NULL
);
GRANT ALL ON ldap_agents TO cdb_admin;

-- static ldap groups operating only on core.personas
DROP TABLE IF EXISTS ldap_static_groups;
CREATE TABLE ldap_static_groups (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
	description varchar
);
GRANT ALL ON ldap_static_groups TO cdb_admin;

INSERT INTO ldap_static_groups (id, cn, description) VALUES
    (node_static_group_is_active_id(), 'is_active', 'Aktive Nutzer.'),
    (node_static_group_is_member_id(), 'is_member', 'Nutzer, die aktuell Mitglied im CdE sind.'),
    (node_static_group_is_searchable_id(), 'is_searchable', 'Nutzer, die aktuell Mitglied im CdE und und in der Datenbank suchbar sind.'),
    (node_static_group_is_ml_realm_id(), 'is_ml_realm', 'Nutzer, die auf Mailinglisten stehen dürfen.'),
    (node_static_group_is_event_realm_id(), 'is_event_realm', 'Nutzer, die an Veranstaltungen teilnehmen dürfen.'),
    (node_static_group_is_assembly_realm_id(), 'is_assembly_realm', 'Nutzer, die an Versammlungen teilnehmen dürfen.'),
    (node_static_group_is_cde_realm_id(), 'is_cde_realm', 'Nutzer, die jemals Mitglied im CdE waren oder sind.'),
    (node_static_group_is_ml_admin_id(), 'is_ml_admin', 'Mailinglisten-Administratoren'),
    (node_static_group_is_event_admin_id(), 'is_event_admin', 'Veranstaltungs-Administratoren'),
    (node_static_group_is_assembly_admin_id(), 'is_assembly_admin', 'Versammlungs-Administratoren'),
    (node_static_group_is_cde_admin_id(), 'is_cde_admin', 'CdE-Administratoren'),
    (node_static_group_is_core_admin_id(), 'is_core_admin', 'Core-Administratoren'),
    (node_static_group_is_finance_admin_id(), 'is_finance_admin', 'Finanz-Administratoren'),
    (node_static_group_is_cdelokal_admin_id(), 'is_cdelokal_admin', 'CdELokal-Administratoren');

-- A view containing all ldap_groups and their unique attributes.
CREATE VIEW ldap_groups (id, cn, description) AS
    -- static groups
    (
        SELECT
           make_static_group_entity_id(id),
           cn,
           description
        FROM ldap_static_groups
    )
    -- mailinglists
    UNION (
        SELECT
           make_mailinglist_entity_id(id),
           make_mailinglist_cn(address) AS cn,
           title || ' <' || address || '>' AS description
        FROM ml.mailinglists
    )
;
GRANT ALL ON ldap_groups TO cdb_admin;

-- A view containing all members of all ldap_groups. Since each group can have
-- mulitple members, we need an extra query view to track them.
-- This is also honored in 'ldap_attr_mapping'.
CREATE VIEW ldap_group_members (group_id, member_dn) AS
    -- static groups
        -- is_active
        (
           SELECT
              make_static_group_entity_id(node_static_group_is_active_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_active
        )
        -- is_member
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_member_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_member
        )
        -- is_searchable AND is_member
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_searchable_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_member AND core.personas.is_searchable
        )
        -- is_ml_realm
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_ml_realm_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_ml_realm
        )
        -- is_event_realm
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_event_realm_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_event_realm
        )
        -- is_assembly_realm
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_assembly_realm_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_assembly_realm
        )
        -- is_cde_realm
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_cde_realm_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cde_realm
        )
        -- is_ml_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_ml_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_ml_admin
        )
        -- is_event_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_event_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_event_admin
        )
        -- is_assembly_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_assembly_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_assembly_admin
        )
        -- is_cde_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_cde_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cde_admin
        )
        -- is_core_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_core_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_core_admin
        )
        -- is_finance_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_finance_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_finance_admin
        )
        -- is_cdelokal_admin
        UNION (
           SELECT
              make_static_group_entity_id(node_static_group_is_cdelokal_admin_id()) AS group_id,
              make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cdelokal_admin
        )
    -- mailinglists
    UNION (
        SELECT
           make_mailinglist_entity_id(mailinglist_id) AS group_id,
           make_persona_dn(persona_id) AS member_dn
        FROM ml.subscription_states
        -- SubscriptionState.subscribed,
        -- SubscriptionState.unsubscription_override
        -- SubscriptionState.implicit
        WHERE subscription_state = ANY(ARRAY[1, 10, 30])
    )
;
GRANT ALL ON ldap_group_members TO cdb_admin;


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
    (oc_organizationalRole_id(), 'organizationalRole', 'ldap_agents', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0),
    (oc_groupOfUniqueNames_id(), 'groupOfUniqueNames', 'ldap_groups', 'id', 'SELECT ''TODO''', 'SELECT ''TODO''', 0);


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
        (oc_inetOrgPerson_id(), 'cn', $$ personas.given_names || ' ' || personas.family_name $$, 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        -- mandatory
        (oc_inetOrgPerson_id(), 'sn', 'personas.family_name', 'ldap_organizations', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_inetOrgPerson_id(), 'displayName', 'make_persona_display_name(core.personas.display_name, core.personas.given_names, core.personas.family_name)', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_inetOrgPerson_id(), 'givenName', 'personas.given_names', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_inetOrgPerson_id(), 'mail', 'personas.username', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        -- this seems to be interpreted as string and therefore needs to be casted to a VARCHAR
        (oc_inetOrgPerson_id(), 'uid', 'CAST (personas.id as VARCHAR)', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_inetOrgPerson_id(), 'userPassword', '''{CRYPT}'' || personas.password_hash', 'core.personas', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of groupOfUniqueNames
        (oc_groupOfUniqueNames_id(), 'cn', 'ldap_groups.cn', 'ldap_groups', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_groupOfUniqueNames_id(), 'description', 'ldap_groups.description', 'ldap_groups', NULL, 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (oc_groupOfUniqueNames_id(), 'uniqueMember', 'ldap_group_members.member_dn', 'ldap_group_members, ldap_groups', 'ldap_groups.id = ldap_group_members.group_id', 'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0);

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
           make_organization_entity_id(node_dsa_id()) AS parent,
           id as keyval
        FROM ldap_agents
    )
    -- personas
    UNION (
        SELECT
           make_persona_entity_id(id),
           -- the DB-ID is really static
           make_persona_dn(id) AS dn,
           oc_inetOrgPerson_id() AS oc_map_id,
           make_organization_entity_id(node_users_id()) AS parent,
           id as keyval
        FROM core.personas
    )
    -- groups
        -- static
        UNION (
            SELECT
               make_static_group_entity_id(id),
               'cn=' || cn || ',ou=groups,dc=cde-ev,dc=de' AS dn,
               oc_groupOfUniqueNames_id() AS oc_map_id,
               make_organization_entity_id(node_groups_id()) AS parent,
               make_static_group_entity_id(id) as keyval
            FROM ldap_static_groups
        )
        -- mailinglists
        UNION (
            SELECT
               make_mailinglist_entity_id(id),
               'cn=' || make_mailinglist_cn(address) || ',ou=mailinglists,ou=groups,dc=cde-ev,dc=de' AS dn,
               oc_groupOfUniqueNames_id() AS oc_map_id,
               make_organization_entity_id(node_mailinglist_group_id()) AS parent,
               make_mailinglist_entity_id(id) as keyval
            FROM ml.mailinglists
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
