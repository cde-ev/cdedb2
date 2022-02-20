-- This file specifies the ldap interfaces of the DB on database' side
-- This needs cdedb-tables.sql as prerequisite.

---
--- Create own ldap schema.
--- This is used for all tables and functions except those which are required
--- by back-sql ldap to exercise the actual bridge.
---

DROP SCHEMA IF EXISTS ldap CASCADE;
CREATE SCHEMA ldap;
GRANT ALL PRIVILEGES ON SCHEMA ldap TO cdb_admin;

---
--- ldap oc helper functions
--- ids of all our ldap object classes
---

CREATE FUNCTION ldap.oc_organization_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 1; $$;

CREATE FUNCTION ldap.oc_organizationalUnit_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 2; $$;

CREATE FUNCTION ldap.oc_person_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 3; $$;

CREATE FUNCTION ldap.oc_inetOrgPerson_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 10; $$;

CREATE FUNCTION ldap.oc_groupOfUniqueNames_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 20; $$;

---
--- ldap node helper functions
--- ids of hardcoded ldap tree nodes
---

CREATE FUNCTION ldap.node_cde_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 1; $$;

CREATE FUNCTION ldap.node_users_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 10; $$;

CREATE FUNCTION ldap.node_groups_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 11; $$;

CREATE FUNCTION ldap.node_dua_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 12; $$;

CREATE FUNCTION ldap.node_ml_subscribers_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 15; $$;

CREATE FUNCTION ldap.node_ml_moderators_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 16; $$;

CREATE FUNCTION ldap.node_event_orgas_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 17; $$;

CREATE FUNCTION ldap.node_assembly_presiders_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 18; $$;

CREATE FUNCTION ldap.node_static_group_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 19; $$;

CREATE FUNCTION ldap.node_static_group_is_active_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 20; $$;

CREATE FUNCTION ldap.node_static_group_is_member_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 21; $$;

CREATE FUNCTION ldap.node_static_group_is_searchable_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 22; $$;

CREATE FUNCTION ldap.node_static_group_is_ml_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 30; $$;

CREATE FUNCTION ldap.node_static_group_is_event_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 31; $$;

CREATE FUNCTION ldap.node_static_group_is_assembly_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 32; $$;

CREATE FUNCTION ldap.node_static_group_is_cde_realm_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 33; $$;

CREATE FUNCTION ldap.node_static_group_is_ml_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 40; $$;

CREATE FUNCTION ldap.node_static_group_is_event_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 41; $$;

CREATE FUNCTION ldap.node_static_group_is_assembly_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 42; $$;

CREATE FUNCTION ldap.node_static_group_is_cde_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 43; $$;

CREATE FUNCTION ldap.node_static_group_is_core_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 44; $$;

CREATE FUNCTION ldap.node_static_group_is_finance_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 45; $$;

CREATE FUNCTION ldap.node_static_group_is_cdelokal_admin_id()
  RETURNS int LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 46; $$;

---
--- serial id offset helper functions
--- To store multiple serial tables in a bigserial one, we simply shift the id
--- of each serial table by this value (maximum store of serial)
---
CREATE FUNCTION ldap.make_organization_entity_id(organization_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (1 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_dua_entity_id(dua_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (2 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_persona_entity_id(persona_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (3 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_static_group_entity_id(static_group_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (4 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_ml_subscribers_entity_id(mailinglist_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (5 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_ml_moderators_entity_id(mailinglist_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (6 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_event_orgas_entity_id(event_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (7 * 2^32 + $1 AS BIGINT); $$ ;

CREATE FUNCTION ldap.make_assembly_presiders_entity_id(assembly_id INT)
  RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CAST (8 * 2^32 + $1 AS BIGINT); $$ ;

---
--- create cn and dn
--- Some dns are used at multiple places. To ensure consistency, we define a
--- function for them here. Other dns are specified in 'ldap_entries'.
---

CREATE FUNCTION ldap.make_persona_dn(persona_id INT)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 'uid=' || $1 || ',ou=users,dc=cde-ev,dc=de'; $$ ;

-- create the owner address of a given mailinglist
-- since we save the domain of a mailinglist as int and map them in python, this is a bit hacky
CREATE FUNCTION ldap.make_ml_moderators_cn(address VARCHAR)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT REPLACE($1, '@', '-owner@'); $$ ;

CREATE FUNCTION ldap.make_event_orgas_cn(event_id INT)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 'orgas-' || $1; $$ ;

CREATE FUNCTION ldap.make_assembly_presider_cn(assembly_id INT)
  RETURNS varchar LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT 'presiders-' || $1; $$ ;

CREATE FUNCTION ldap.make_persona_display_name(display_name VARCHAR, given_names VARCHAR, family_name VARCHAR)
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
--- ldap helper tables
---

---
--- this add some helper tables to satisfy the requirements of the ldap back-sql
--- schema. Some of them add real new data which is required for middle-nodes in
--- the ldap there, others are just query views on existent data which is
--- scattered over multiple tables.
---

-- helper nodes to satisfy the ldap-tree conventions
CREATE TABLE ldap.organizations (
	id serial PRIMARY KEY,
	dn varchar NOT NULL,
	oc_map_id integer NOT NULL,  -- REFERENCES ldap_oc_mappings(id)
	parent bigint NOT NULL,  -- REFERENCES ldap_entries(id)
	-- maps ldap 'o' attribute
	display_name varchar NOT NULL,
	-- to be set in 'ldap_entry_objclasses'
	additional_object_class1 varchar DEFAULT NULL,
	additional_object_class2 varchar DEFAULT NULL
);

INSERT INTO ldap.organizations (id, dn, oc_map_id, parent, display_name, additional_object_class1, additional_object_class2) VALUES
    -- The overall organization
        (ldap.node_cde_id(),                            'dc=cde-ev,dc=de',                                      ldap.oc_organization_id(),          0,                                                                      'CdE e.V.',                     'dcObject',     'top'),
    -- All organizational units
        (ldap.node_users_id(),                          'ou=users,dc=cde-ev,dc=de',                             ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_cde_id()),       'Users',                        NULL,           NULL),
        (ldap.node_groups_id(),                         'ou=groups,dc=cde-ev,dc=de',                            ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_cde_id()),       'Groups',                       NULL,           NULL),
        (ldap.node_dua_id(),                            'ou=duas,dc=cde-ev,dc=de',                               ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_cde_id()),       'Directory System Agent',       NULL,           NULL),
    -- Additional organizational units holding group of groups
        (ldap.node_static_group_id(),                   'ou=status,ou=groups,dc=cde-ev,dc=de',                  ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_groups_id()),    'Status',                       NULL,           NULL),
        (ldap.node_ml_subscribers_group_id(),           'ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de',          ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_groups_id()),    'Mailinglists Subscribers',     NULL,           NULL),
        (ldap.node_ml_moderators_group_id(),            'ou=ml-moderators,ou=groups,dc=cde-ev,dc=de',           ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_groups_id()),    'Mailinglists Moderators',      NULL,           NULL),
        (ldap.node_event_orgas_group_id(),              'ou=event-orgas,ou=groups,dc=cde-ev,dc=de',             ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_groups_id()),    'Event Orgas',                  NULL,           NULL),
        (ldap.node_assembly_presiders_group_id(),       'ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de',      ldap.oc_organizationalUnit_id(),    ldap.make_organization_entity_id(ldap.node_groups_id()),    'Assembly Presiders',           NULL,           NULL);

-- ldap Directory System Users
CREATE TABLE ldap.duas (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
    password_hash varchar NOT NULL
);
GRANT ALL ON ldap.duas_id_seq TO cdb_admin;

-- static ldap groups operating only on core.personas
CREATE TABLE ldap.static_groups (
	id serial PRIMARY KEY,
	cn varchar NOT NULL,
	description varchar
);

INSERT INTO ldap.static_groups (id, cn, description) VALUES
    (ldap.node_static_group_is_active_id(),              'is_active',            'Aktive Nutzer.'),
    (ldap.node_static_group_is_member_id(),              'is_member',            'Nutzer, die aktuell Mitglied im CdE sind.'),
    (ldap.node_static_group_is_searchable_id(),          'is_searchable',        'Nutzer, die aktuell Mitglied im CdE und und in der Datenbank suchbar sind.'),
    (ldap.node_static_group_is_ml_realm_id(),            'is_ml_realm',          'Nutzer, die auf Mailinglisten stehen dürfen.'),
    (ldap.node_static_group_is_event_realm_id(),         'is_event_realm',       'Nutzer, die an Veranstaltungen teilnehmen dürfen.'),
    (ldap.node_static_group_is_assembly_realm_id(),      'is_assembly_realm',    'Nutzer, die an Versammlungen teilnehmen dürfen.'),
    (ldap.node_static_group_is_cde_realm_id(),           'is_cde_realm',         'Nutzer, die jemals Mitglied im CdE waren oder sind.'),
    (ldap.node_static_group_is_ml_admin_id(),            'is_ml_admin',          'Mailinglisten-Administratoren'),
    (ldap.node_static_group_is_event_admin_id(),         'is_event_admin',       'Veranstaltungs-Administratoren'),
    (ldap.node_static_group_is_assembly_admin_id(),      'is_assembly_admin',    'Versammlungs-Administratoren'),
    (ldap.node_static_group_is_cde_admin_id(),           'is_cde_admin',         'CdE-Administratoren'),
    (ldap.node_static_group_is_core_admin_id(),          'is_core_admin',        'Core-Administratoren'),
    (ldap.node_static_group_is_finance_admin_id(),       'is_finance_admin',     'Finanz-Administratoren'),
    (ldap.node_static_group_is_cdelokal_admin_id(),      'is_cdelokal_admin',    'CdELokal-Administratoren');

-- A view containing all ldap.groups and their unique attributes.
CREATE VIEW ldap.groups (id, cn, description) AS
    -- static groups
    (
        SELECT
           ldap.make_static_group_entity_id(id),
           cn,
           description
        FROM ldap.static_groups
    )
    -- mailinglists subscribers
    UNION (
        SELECT
           ldap.make_ml_subscribers_entity_id(id),
           -- This seems to be allowed, see
           -- https://datatracker.ietf.org/doc/html/rfc4512#section-2.3.2
           address AS cn,
           title || ' <' || address || '>' AS description
        FROM ml.mailinglists
    )
    -- mailinglists moderators
    UNION (
        SELECT
           ldap.make_ml_moderators_entity_id(id),
           -- This seems to be allowed, see
           -- https://datatracker.ietf.org/doc/html/rfc4512#section-2.3.2
           ldap.make_ml_moderators_cn(address) AS cn,
           title || ' <' || ldap.make_ml_moderators_cn(address) || '>' AS description
        FROM ml.mailinglists
    )
    -- event orgas
    UNION (
        SELECT
           ldap.make_event_orgas_entity_id(id),
           ldap.make_event_orgas_cn(id) AS cn,
           title || ' (' || shortname || ')' AS description
        FROM event.events
    )
    -- assembly presiders
    UNION (
        SELECT
           ldap.make_assembly_presiders_entity_id(id),
           ldap.make_assembly_presider_cn(id) AS cn,
           title || ' (' || shortname || ')' AS description
        FROM assembly.assemblies
    )
;

-- A view containing all members of all ldap.groups. Since each group can have
-- multiple members, we need an extra query view to track them.
-- This is also honored in 'ldap_attr_mapping'.
CREATE VIEW ldap.group_members (group_id, group_dn, member_id, member_dn) AS
    -- static groups
        -- is_active
        (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_active_id()) AS group_id,
              'cn=is_active,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_active
        )
        -- is_member
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_member_id()) AS group_id,
              'cn=is_member,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_member
        )
        -- is_searchable AND is_member
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_searchable_id()) AS group_id,
              'cn=is_searchable,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_member AND core.personas.is_searchable
        )
        -- is_ml_realm
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_ml_realm_id()) AS group_id,
              'cn=is_ml_realm,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_ml_realm
        )
        -- is_event_realm
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_event_realm_id()) AS group_id,
              'cn=is_event_realm,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_event_realm
        )
        -- is_assembly_realm
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_assembly_realm_id()) AS group_id,
              'cn=is_assembly_realm,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_assembly_realm
        )
        -- is_cde_realm
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_cde_realm_id()) AS group_id,
              'cn=is_cde_realm,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cde_realm
        )
        -- is_ml_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_ml_admin_id()) AS group_id,
              'cn=is_ml_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_ml_admin
        )
        -- is_event_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_event_admin_id()) AS group_id,
              'cn=is_event_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_event_admin
        )
        -- is_assembly_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_assembly_admin_id()) AS group_id,
              'cn=is_assembly_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_assembly_admin
        )
        -- is_cde_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_cde_admin_id()) AS group_id,
              'cn=is_cde_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cde_admin
        )
        -- is_core_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_core_admin_id()) AS group_id,
              'cn=is_core_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_core_admin
        )
        -- is_finance_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_finance_admin_id()) AS group_id,
              'cn=is_finance_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_finance_admin
        )
        -- is_cdelokal_admin
        UNION (
           SELECT
              ldap.make_static_group_entity_id(ldap.node_static_group_is_cdelokal_admin_id()) AS group_id,
              'cn=is_cdelokal_admin,ou=status,ou=groups,dc=cde-ev,dc=de' AS group_dn,
              core.personas.id AS member_id,
              ldap.make_persona_dn(core.personas.id) AS member_dn
           FROM core.personas
           WHERE core.personas.is_cdelokal_admin
        )
    -- mailinglists subscribers
    UNION (
        SELECT
           ldap.make_ml_subscribers_entity_id(mailinglist_id) AS group_id,
           'cn=' || address || ',ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de' AS group_dn,
           persona_id AS member_id,
           ldap.make_persona_dn(persona_id) AS member_dn
        FROM ml.subscription_states, ml.mailinglists
        WHERE ml.subscription_states.mailinglist_id = ml.mailinglists.id
        -- SubscriptionState.subscribed,
        -- SubscriptionState.unsubscription_override
        -- SubscriptionState.implicit
        AND subscription_state = ANY(ARRAY[1, 10, 30])
    )
    -- mailinglist moderators
    UNION (
        SELECT
           ldap.make_ml_moderators_entity_id(mailinglist_id) AS group_id,
           'cn=' || ldap.make_ml_moderators_cn(address) || ',ou=ml-moderators,ou=groups,dc=cde-ev,dc=de' AS group_dn,
           persona_id AS member_id,
           ldap.make_persona_dn(persona_id) AS member_dn
        FROM ml.moderators, ml.mailinglists
        WHERE ml.moderators.mailinglist_id = ml.mailinglists.id
    )
    -- event orgas
    UNION (
        SELECT
           ldap.make_event_orgas_entity_id(event_id) AS group_id,
           'cn=' || ldap.make_event_orgas_cn(event_id) || ',ou=event-orgas,ou=groups,dc=cde-ev,dc=de' AS group_dn,
           persona_id AS member_id,
           ldap.make_persona_dn(persona_id) AS member_dn
        FROM event.orgas
    )
    -- assembly presiders
    UNION (
        SELECT
           ldap.make_assembly_presiders_entity_id(assembly_id) AS group_id,
           'cn=' || ldap.make_assembly_presider_cn(assembly_id) || ',ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de' AS group_dn,
           persona_id AS member_id,
           ldap.make_persona_dn(persona_id) AS member_dn
        FROM assembly.presiders
    )
;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ldap TO cdb_admin;



---
--- ldap tables for back-sql (in public schema)
---

---
--- this is taken with minimal modifications from
--- servers/slapd/back-sql/rdbms_depend/pgsql/backsql_create.sql
--- in the openldap sources
---

-- Maps ldap object classes to sql tables.
-- Back-sql requires this to be a 1:1 relation. If we store the same ldap object
-- in multiple sql tables (f.e. groupOfUniqueNames), we have to create a helper
-- Query View to collect them all together.
DROP TABLE IF EXISTS ldap_oc_mappings CASCADE;
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
    (ldap.oc_organization_id(),             'organization',         'ldap.organizations',   'id',   'SELECT ''TODO''',  'SELECT ''TODO''',  0),
    (ldap.oc_inetOrgPerson_id(),            'inetOrgPerson',        'core.personas',        'id',   'SELECT ''TODO''',  'SELECT ''TODO''',  0),
    (ldap.oc_organizationalUnit_id(),       'organizationalUnit',   'ldap.organizations',   'id',   'SELECT ''TODO''',  'SELECT ''TODO''',  0),
    -- TODO This is temporary, since there is no standard objectclass for duas...
    (ldap.oc_person_id(),                   'person',               'ldap.duas',            'id',   'SELECT ''TODO''',  'SELECT ''TODO''',  0),
    (ldap.oc_groupOfUniqueNames_id(),       'groupOfUniqueNames',   'ldap.groups',          'id',   'SELECT ''TODO''',  'SELECT ''TODO''',  0);


-- Map ldap object class attributes to sql queries to extract them.
DROP TABLE IF EXISTS ldap_attr_mappings CASCADE;
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
        (ldap.oc_organization_id(),         'o',                'ldap.organizations.display_name',                                                                                      'ldap.organizations',                   NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of organizationalUnits
        (ldap.oc_organizationalUnit_id(),   'o',                'ldap.organizations.display_name',                                                                                      'ldap.organizations',                   NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of duas
        (ldap.oc_person_id(),               'cn',               'ldap.duas.cn',                                                                                                         'ldap.duas',                            NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_person_id(),               'userPassword',     '''{CRYPT}'' || ldap.duas.password_hash',                                                                               'ldap.duas',                            NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of inetOrgPerson
    -- Naming was chosen accordingly to the following RFC:
    -- https://datatracker.ietf.org/doc/html/rfc2798 (defining inetOrgPerson)
    -- https://datatracker.ietf.org/doc/html/rfc4519 (defining attributes)
        -- mandatory
        (ldap.oc_inetOrgPerson_id(),        'cn',               $$ personas.given_names || ' ' || personas.family_name $$,                                                              'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        -- mandatory
        (ldap.oc_inetOrgPerson_id(),        'sn',               'personas.family_name',                                                                                                 'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_inetOrgPerson_id(),        'displayName',      'ldap.make_persona_display_name(core.personas.display_name, core.personas.given_names, core.personas.family_name)',     'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_inetOrgPerson_id(),        'givenName',        'personas.given_names',                                                                                                 'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_inetOrgPerson_id(),        'mail',             'personas.username',                                                                                                    'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        -- this seems to be interpreted as string and therefore needs to be casted to a VARCHAR
        (ldap.oc_inetOrgPerson_id(),        'uid',              'CAST (personas.id as VARCHAR)',                                                                                        'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_inetOrgPerson_id(),        'userPassword',     '''{CRYPT}'' || personas.password_hash',                                                                                'core.personas',                        NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_inetOrgPerson_id(),        'memberOf',         'ldap.group_members.group_dn',                                                                                          'ldap.group_members, core.personas',    'core.personas.id = ldap.group_members.member_id',  'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
    -- Attributes of groupOfUniqueNames
        (ldap.oc_groupOfUniqueNames_id(),   'cn',               'ldap.groups.cn',                                                                                                       'ldap.groups',                          NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_groupOfUniqueNames_id(),   'description',      'ldap.groups.description',                                                                                              'ldap.groups',                          NULL,                                               'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0),
        (ldap.oc_groupOfUniqueNames_id(),   'uniqueMember',     'ldap.group_members.member_dn',                                                                                         'ldap.group_members, ldap.groups',      'ldap.groups.id = ldap.group_members.group_id',     'SELECT ''TODO''', 'SELECT ''TODO''', 3, 0);

-- 'Stores' the real ldap entries.
-- This is a SQL View collecting all entries which shall be inserted in ldap
-- togehter. Keyval is the primary identifier specified in 'ldap_oc_mappings'
-- for the given ldap object class
DROP VIEW IF EXISTS ldap_entries CASCADE;
CREATE VIEW ldap_entries (id, dn, oc_map_id, parent, keyval) AS
    -- organizations and organizationalUnits
    (
        SELECT
           ldap.make_organization_entity_id(id),
           dn,
           oc_map_id,
           parent,
           id AS keyval
        FROM ldap.organizations
    )
    -- Directory System Agents
    UNION (
        SELECT
           ldap.make_dua_entity_id(id),
           'cn=' || cn || ',ou=duas,dc=cde-ev,dc=de' AS dn,
           ldap.oc_person_id() AS oc_map_id,
           ldap.make_organization_entity_id(ldap.node_dua_id()) AS parent,
           id as keyval
        FROM ldap.duas
    )
    -- personas
    UNION (
        SELECT
           ldap.make_persona_entity_id(id),
           -- the DB-ID is really static
           ldap.make_persona_dn(id) AS dn,
           ldap.oc_inetOrgPerson_id() AS oc_map_id,
           ldap.make_organization_entity_id(ldap.node_users_id()) AS parent,
           id as keyval
        FROM core.personas
    )
    -- groups
        -- static
        UNION (
            SELECT
               ldap.make_static_group_entity_id(id),
               'cn=' || cn || ',ou=status,ou=groups,dc=cde-ev,dc=de' AS dn,
               ldap.oc_groupOfUniqueNames_id() AS oc_map_id,
               ldap.make_organization_entity_id(ldap.node_static_group_id()) AS parent,
               ldap.make_static_group_entity_id(id) as keyval
            FROM ldap.static_groups
        )
        -- mailinglists subscribers
        UNION (
            SELECT
               ldap.make_ml_subscribers_entity_id(id),
               'cn=' || address || ',ou=ml-subscribers,ou=groups,dc=cde-ev,dc=de' AS dn,
               ldap.oc_groupOfUniqueNames_id() AS oc_map_id,
               ldap.make_organization_entity_id(ldap.node_ml_subscribers_group_id()) AS parent,
               ldap.make_ml_subscribers_entity_id(id) as keyval
            FROM ml.mailinglists
        )
        -- mailinglists moderators
        UNION (
            SELECT
               ldap.make_ml_moderators_entity_id(id),
               'cn=' || ldap.make_ml_moderators_cn(address) || ',ou=ml-moderators,ou=groups,dc=cde-ev,dc=de' AS dn,
               ldap.oc_groupOfUniqueNames_id() AS oc_map_id,
               ldap.make_organization_entity_id(ldap.node_ml_moderators_group_id()) AS parent,
               ldap.make_ml_moderators_entity_id(id) as keyval
            FROM ml.mailinglists
        )
        -- event orgas
        UNION (
            SELECT
               ldap.make_event_orgas_entity_id(id),
               'cn=' || ldap.make_event_orgas_cn(id) || ',ou=event-orgas,ou=groups,dc=cde-ev,dc=de' AS dn,
               ldap.oc_groupOfUniqueNames_id() AS oc_map_id,
               ldap.make_organization_entity_id(ldap.node_event_orgas_group_id()) AS parent,
               ldap.make_event_orgas_entity_id(id) as keyval
            FROM event.events
        )
        -- assembly presiders
        UNION (
            SELECT
               ldap.make_assembly_presiders_entity_id(id),
               'cn=' || ldap.make_assembly_presider_cn(id) || ',ou=assembly-presiders,ou=groups,dc=cde-ev,dc=de' AS dn,
               ldap.oc_groupOfUniqueNames_id() AS oc_map_id,
               ldap.make_organization_entity_id(ldap.node_assembly_presiders_group_id()) AS parent,
               ldap.make_assembly_presiders_entity_id(id) as keyval
            FROM assembly.assemblies
        )
;
GRANT ALL ON ldap_entries TO cdb_admin;

-- Add additional ldap object classes to an entry with 'entry_id' in
-- 'ldap_entries'.
DROP VIEW IF EXISTS ldap_entry_objclasses CASCADE;
CREATE VIEW ldap_entry_objclasses (entry_id, oc_name) AS
    -- organizations part 1
    (
        SELECT
           ldap.make_organization_entity_id(id) AS entry_id,
           additional_object_class1 AS oc_name
        FROM ldap.organizations
        WHERE additional_object_class1 IS NOT NULL
    )
    -- organizations part 2
    UNION (
        SELECT
           ldap.make_organization_entity_id(id) AS entry_id,
           additional_object_class2 AS oc_name
        FROM ldap.organizations
        WHERE additional_object_class2 IS NOT NULL
    )
    -- Directory System Agents
    UNION (
        SELECT
           ldap.make_dua_entity_id(id) AS entry_id,
           'simpleSecurityObject' AS oc_name
        FROM ldap.duas
    )
;
GRANT ALL ON ldap_entry_objclasses TO cdb_admin;

-- create previously impossible references
ALTER TABLE ldap.organizations ADD FOREIGN KEY (oc_map_id) REFERENCES ldap_oc_mappings(id);
-- this SHOULD be a reference. However, one can not create foreign keys on query views...
-- ALTER TABLE ldap.organizations ADD FOREIGN KEY (parent) REFERENCES ldap_entries(id);
