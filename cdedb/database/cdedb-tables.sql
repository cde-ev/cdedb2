-- This file specifies the tables in the database and has the users in
-- cdedb-users.sql as prerequisite, as well as cdedb-db.sql .

---
--- SCHEMA core
---

DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
GRANT USAGE ON SCHEMA core TO cdb_anonymous, cdb_ldap;

-- Store all user attributes, many attributes are only meaningful if the
-- persona has the access bit to the corresponding realm.
CREATE TABLE core.personas (
        --
        -- global attributes
        --
        id                      serial PRIMARY KEY,
        -- an email address (should be lower-cased)
        -- may be NULL precisely for archived users
        username                varchar UNIQUE,
        -- password hash as specified by passlib.hash.sha512_crypt
        -- not logged in changelog
        password_hash           varchar NOT NULL,
        -- inactive accounts may not log in
        is_active               boolean NOT NULL DEFAULT True,
        CONSTRAINT personas_active_archived
            CHECK (NOT (is_archived AND is_active)),
        -- administrative notes about this user
        notes                   varchar,

        -- global admin, grants all privileges
        is_meta_admin           boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_meta
            CHECK (NOT is_meta_admin OR is_cde_realm),
        -- allows managing all users and general database configuration
        is_core_admin           boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_core
            CHECK (NOT is_core_admin OR is_cde_realm),
        -- allows managing of cde users (members and former members) and
        -- other cde stuff (past events, direct debit)
        is_cde_admin            boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_cde
            CHECK (NOT is_cde_admin OR is_cde_realm),
        is_finance_admin        boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_finance
            CHECK (NOT is_finance_admin OR is_cde_admin),
        -- allows managing of events and event users
        is_event_admin          boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_event
            CHECK (NOT is_event_admin OR is_event_realm),
        -- allows managing of mailinglists and ml users
        is_ml_admin             boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_ml
            CHECK (NOT is_ml_admin OR is_ml_realm),
        -- allows managing of assemblies and assembly users
        is_assembly_admin       boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_assembly
            CHECK (NOT is_assembly_admin OR is_assembly_realm),
        -- allows managing a subset of all mailinglists, those related to CdE Lokalgruppen
        is_cdelokal_admin       boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_admin_cdelokal
            CHECK (NOT is_cdelokal_admin OR is_ml_realm),
        -- allows auditing, i.e. viewing of all logs
        is_auditor              boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_cde_auditor
            CHECK (NOT is_auditor OR is_cde_realm),
        -- allows usage of cde functionality
        is_cde_realm            boolean NOT NULL,
        CONSTRAINT personas_realm_cde_implicits
            CHECK (NOT is_cde_realm OR (is_event_realm AND is_assembly_realm)),
        -- allows usage of event functionality
        is_event_realm          boolean NOT NULL,
        CONSTRAINT personas_realm_event_implicits
            CHECK (NOT is_event_realm OR is_ml_realm),
        -- allows usage of mailinglist functionality
        is_ml_realm             boolean NOT NULL,
        -- allows usage of assembly functionality
        is_assembly_realm       boolean NOT NULL,
        CONSTRAINT personas_realm_assembly_implicits
            CHECK (NOT is_assembly_realm OR is_ml_realm),
        -- member status grants access to additional functionality
        is_member               boolean NOT NULL,
        CONSTRAINT personas_member_implicits
            CHECK (NOT is_member OR is_cde_realm),
        -- searchability governs whether a persona may search for others
        --
        -- a persona is visible/may search
        -- iff is_searchable and is_member are both TRUE
        is_searchable           boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_cde_searchable
            CHECK (NOT is_searchable OR is_cde_realm),
        -- signal a data set of a former member which was stripped of all
        -- non-essential attributes to implement data protection
        is_archived             boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_archived_username
            CHECK ((username IS NULL) = is_archived),
        CONSTRAINT personas_archived_member
            CHECK (NOT (is_member AND is_archived)),
        -- signal all remaining information about a user has been cleared.
        -- this can never be undone.
        is_purged               boolean NOT NULL DEFAULT False,
        CONSTRAINT personas_archived_purged
            CHECK (NOT is_purged OR is_archived),
        -- name to use when adressing user/"Rufname"
        display_name            varchar NOT NULL,
        -- "Vornamen" (including middle names)
        given_names             varchar NOT NULL,
        -- "Nachname"
        family_name             varchar NOT NULL,

        --
        -- event and cde attributes
        --
        -- in front of name
        title                   varchar DEFAULT NULL,
        -- after name
        name_supplement         varchar DEFAULT NULL,
        -- preferred pronouns (optional)
        pronouns                varchar DEFAULT NULL,
        pronouns_nametag        boolean NOT NULL DEFAULT FALSE,
        pronouns_profile        boolean NOT NULL DEFAULT FALSE,
        -- see cdedb.database.constants.Genders
        gender                  integer,
        CONSTRAINT personas_realm_gender
            CHECK((is_cde_realm OR is_event_realm) = (gender IS NOT NULL)),
        -- may be NULL in historical cases; we try to minimize these occurences
        birthday                date,
        CONSTRAINT personas_realm_birthday
            CHECK((is_cde_realm OR is_event_realm) = (birthday is NOT NULL)),
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        -- probably a city
        location                varchar,
        country                 varchar,

        --
        -- cde only attributes
        --
        birth_name              varchar DEFAULT NULL,
        address_supplement2     varchar,
        address2                varchar,
        postal_code2            varchar,
        -- probably a city
        location2               varchar,
        country2                varchar,
        -- homepage, blog, twitter, ...
        weblink                 varchar,
        -- Leistungskurse, Studienfach, ...
        specialisation          varchar,
        -- Schule, Universitaet, ...
        affiliation             varchar,
        -- Abiturjahrgang, Studienabschluss, ...
        timeline                varchar,
        -- Interessen, Hobbys, ...
        interests               varchar,
        -- anything else the member wants to tell
        free_form               varchar,
        balance                 numeric(8, 2) DEFAULT NULL,
        CONSTRAINT personas_cde_balance
            CHECK(is_cde_realm = (balance IS NOT NULL)),
        donation                numeric(8, 2) DEFAULT NULL,
        CONSTRAINT personas_cde_donation
            CHECK(is_cde_realm = (donation IS NOT NULL)),
        -- True if user decided (positive or negative) on searchability
        decided_search          boolean DEFAULT FALSE,
        CONSTRAINT personas_cde_decided_search
            CHECK(is_cde_realm = (decided_search IS NOT NULL)),
        -- True for trial members (first semester after the first official academy)
        trial_member            boolean,
        CONSTRAINT personas_cde_trial_member
            CHECK(is_cde_realm = (trial_member IS NOT NULL)),
        CONSTRAINT personas_trial_member_implicits
            CHECK(NOT trial_member OR is_member),
        honorary_member         boolean,
        CONSTRAINT personas_cde_honorary_member
            CHECK(is_cde_realm = (honorary_member IS NOT NULL)),
        CONSTRAINT personas_honorary_member_implicits
            CHECK(NOT honorary_member OR is_member),
        -- if True this member's data may be passed on to BuB
        bub_search              boolean DEFAULT FALSE,
        CONSTRAINT personas_cde_bub_search
            CHECK(is_cde_realm = (bub_search IS NOT NULL)),
        -- file name of image
        foto                    varchar DEFAULT NULL,
        -- wants to receive the exPuls in printed form
        paper_expuls            boolean DEFAULT TRUE,
        CONSTRAINT personas_cde_paper_expuls
            CHECK(is_cde_realm = (paper_expuls IS NOT NULL)),
        -- automatically managed attribute containing all above values as a
        -- string for fulltext search
        fulltext                varchar NOT NULL
);
CREATE INDEX personas_username_idx ON core.personas(username);
CREATE INDEX personas_is_cde_realm_idx ON core.personas(is_cde_realm);
CREATE INDEX personas_is_event_realm_idx ON core.personas(is_event_realm);
CREATE INDEX personas_is_ml_realm_idx ON core.personas(is_ml_realm);
CREATE INDEX personas_is_assembly_realm_idx ON core.personas(is_assembly_realm);
CREATE INDEX personas_is_member_idx ON core.personas(is_member);
CREATE INDEX personas_is_searchable_idx ON core.personas(is_searchable);
GRANT SELECT (id, username, password_hash, is_active, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin, is_event_admin, is_ml_admin, is_assembly_admin, is_cdelokal_admin, is_auditor, is_cde_realm, is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived, is_purged) ON core.personas TO cdb_anonymous, cdb_ldap;
GRANT SELECT (display_name, given_names, family_name, title, name_supplement) ON core.personas TO cdb_ldap;
-- required for _changelog_resolve_change_unsafe
GRANT SELECT ON core.personas TO cdb_persona;
GRANT UPDATE (display_name, given_names, family_name, title, name_supplement, pronouns, pronouns_nametag, pronouns_profile, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, fulltext, username, password_hash) ON core.personas TO cdb_persona;
GRANT UPDATE (birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, decided_search, bub_search, foto, paper_expuls, is_searchable, donation) ON core.personas TO cdb_member;
-- includes notes in addition to cdb_member
GRANT UPDATE, INSERT ON core.personas TO cdb_admin;
GRANT SELECT, UPDATE ON core.personas_id_seq TO cdb_admin;

-- table for managing creation of new accounts by arbitrary request
CREATE TABLE core.genesis_cases (
        id                      bigserial PRIMARY KEY,
        -- creation time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        -- user data
        username                varchar NOT NULL,
        given_names             varchar NOT NULL,
        family_name             varchar NOT NULL,
        birth_name              varchar,
        gender                  integer,
        birthday                date,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        location                varchar,
        country                 varchar,
        -- initial target realm, note that e.g. event implies is_event_realm and is_ml_realm
        realm                   varchar DEFAULT NULL,
        -- user-supplied comment (short justification of request)
        -- may be amended during review
        notes                   varchar,
        -- For some realms an attachment may be included. This column contains the filename,
        -- which is the hash of the file.
        attachment_hash         varchar,
        -- A verification link is sent to the email address; upon
        -- verification an admittance email is sent to the responsible team
        --
        -- To prevent spam and enhance security every persona creation needs
        -- to be approved by moderators/administrators; upon addmittance an
        -- email is sent, that persona creation was successful
        --
        -- enum tracking the progress
        -- see cdedb.database.constants.GenesisStati
        case_status             integer NOT NULL DEFAULT 0,
        -- who moderated the request
        reviewer                integer REFERENCES core.personas(id) DEFAULT NULL,
        -- the created or account merged into, if any
        persona_id              integer REFERENCES core.personas(id) DEFAULT NULL,
        -- past event and course to be added to the new user
        pevent_id               integer DEFAULT NULL, -- REFERENCES past_event.events(id)
        pcourse_id              integer DEFAULT NULL -- REFERENCES past_event.courses(id)

);
CREATE INDEX genesis_cases_case_status_idx ON core.genesis_cases(case_status);
GRANT SELECT, INSERT ON core.genesis_cases To cdb_anonymous;
GRANT SELECT, UPDATE ON core.genesis_cases_id_seq TO cdb_anonymous;
GRANT UPDATE (case_status) ON core.genesis_cases TO cdb_anonymous;
GRANT UPDATE, DELETE ON core.genesis_cases TO cdb_admin;

-- this table tracks pending privilege changes
CREATE TABLE core.privilege_changes (
        id                      bigserial PRIMARY KEY,
        -- creation time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        -- finalization time
        ftime                   TIMESTAMP WITH TIME ZONE DEFAULT NULL,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        -- enum
        -- see cdedb.database.constants.PrivilegeChangeStati
        status                  integer NOT NULL DEFAULT 0,
        -- changes to the admin bits. NULL is for no change.
        is_meta_admin           boolean DEFAULT NULL,
        is_core_admin           boolean DEFAULT NULL,
        is_cde_admin            boolean DEFAULT NULL,
        is_finance_admin        boolean DEFAULT NULL,
        is_event_admin          boolean DEFAULT NULL,
        is_ml_admin             boolean DEFAULT NULL,
        is_assembly_admin       boolean DEFAULT NULL,
        is_cdelokal_admin       boolean DEFAULT NULL,
        is_auditor              boolean DEFAULT NULL,
        -- justification supplied by the submitter
        notes                   varchar,
        -- persona who approved the change
        reviewer                integer REFERENCES core.personas(id) DEFAULT NULL
);
CREATE INDEX privilege_changes_status_idx ON core.privilege_changes(status);
GRANT SELECT, INSERT, UPDATE, DELETE ON core.privilege_changes TO cdb_admin;
GRANT SELECT, UPDATE ON core.privilege_changes_id_seq TO cdb_admin;

CREATE TABLE core.sessions (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        is_active               boolean NOT NULL DEFAULT True,
        -- login time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        -- last access time
        atime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        ip                      varchar NOT NULL,
        sessionkey              varchar NOT NULL UNIQUE
);
CREATE INDEX sessions_persona_id_is_active_idx ON core.sessions(persona_id, is_active);
CREATE INDEX sessions_is_active_atime_idx ON core.sessions(is_active, atime);
GRANT SELECT, INSERT ON core.sessions TO cdb_anonymous;
GRANT SELECT, UPDATE ON core.sessions_id_seq TO cdb_anonymous;
GRANT UPDATE (is_active) ON core.sessions TO cdb_anonymous;
GRANT UPDATE (atime) ON core.sessions TO cdb_persona;
GRANT DELETE ON core.sessions TO cdb_admin;

CREATE TABLE core.quota (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        qdate                   date NOT NULL DEFAULT current_date,
        queries                 integer NOT NULL DEFAULT 0,
        last_access_hash        varchar,
        UNIQUE (persona_id, qdate)
);
GRANT SELECT, INSERT ON core.quota TO cdb_member;
GRANT SELECT, UPDATE ON core.quota_id_seq TO cdb_member;
GRANT UPDATE (queries, last_access_hash) ON core.quota TO cdb_member;
GRANT DELETE ON core.quota TO cdb_admin;

-- This table is designed to hold just a single row. Additionally the
-- keys of the dict stored here, will be runtime configurable.
--
-- This is in the core schema to allow anonymous access.
CREATE TABLE core.meta_info (
        id                      serial PRIMARY KEY,
        -- variable store for things like names of persons on
        -- regularily changing posts
        info                    jsonb NOT NULL
);
GRANT SELECT ON core.meta_info TO cdb_anonymous;
GRANT UPDATE ON core.meta_info TO cdb_admin;

CREATE TABLE core.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CoreLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
-- TODO: Add additional indexes and/or expand the columns?
CREATE INDEX core_log_code_idx ON core.log(code);
CREATE INDEX core_log_persona_id_idx ON core.log(persona_id);
GRANT SELECT ON core.log TO cdb_member;
GRANT UPDATE (change_note), DELETE ON core.log TO cdb_admin;
GRANT INSERT ON core.log TO cdb_anonymous;
GRANT SELECT, UPDATE ON core.log_id_seq TO cdb_anonymous;

-- log all changes made to the personal data of members (require approval)
CREATE TABLE core.changelog (
        id                      bigserial PRIMARY KEY,
        --
        -- information about the change
        --
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        reviewed_by             integer REFERENCES core.personas(id) DEFAULT NULL,
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        generation              integer NOT NULL,
        change_note             varchar,
        -- Flag for whether this was an automated change.
        automated_change        boolean NOT NULL DEFAULT FALSE,
        -- enum for progress of change
        -- see cdedb.database.constants.PersonaChangeStati
        code                    integer NOT NULL DEFAULT 0,
        --
        -- data fields
        --
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        UNIQUE (persona_id, generation),
        username                varchar,
        is_active               boolean,
        notes                   varchar,
        is_meta_admin           boolean,
        is_core_admin           boolean,
        is_cde_admin            boolean,
        is_finance_admin        boolean,
        is_event_admin          boolean,
        is_ml_admin             boolean,
        is_assembly_admin       boolean,
        is_cdelokal_admin       boolean,
        is_auditor              boolean,
        is_cde_realm            boolean,
        is_event_realm          boolean,
        is_ml_realm             boolean,
        is_assembly_realm       boolean,
        is_member               boolean,
        is_searchable           boolean,
        is_archived             boolean,
        is_purged               boolean,
        display_name            varchar,
        given_names             varchar,
        family_name             varchar,
        title                   varchar,
        name_supplement         varchar,
        gender                  integer,
        pronouns                varchar DEFAULT NULL,
        pronouns_nametag        boolean NOT NULL DEFAULT FALSE,
        pronouns_profile        boolean NOT NULL DEFAULT FALSE,
        birthday                date,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        location                varchar,
        country                 varchar,
        birth_name              varchar,
        address_supplement2     varchar,
        address2                varchar,
        postal_code2            varchar,
        location2               varchar,
        country2                varchar,
        weblink                 varchar,
        specialisation          varchar,
        affiliation             varchar,
        timeline                varchar,
        interests               varchar,
        free_form               varchar,
        balance                 numeric(8, 2),
        donation                numeric(8, 2),
        decided_search          boolean,
        trial_member            boolean,
        honorary_member         boolean,
        bub_search              boolean,
        foto                    varchar,
        paper_expuls            boolean
);
CREATE INDEX changelog_code_idx ON core.changelog(code);
CREATE INDEX changelog_persona_id_idx ON core.changelog(persona_id);
CREATE UNIQUE INDEX changelog_persona_id_pending ON core.changelog(persona_id) WHERE code = 1;
-- SELECT can not be easily restricted here due to change displacement logic
GRANT SELECT, INSERT ON core.changelog TO cdb_persona;
GRANT SELECT, UPDATE ON core.changelog_id_seq TO cdb_persona;
GRANT UPDATE (code) ON core.changelog TO cdb_persona;
GRANT UPDATE (reviewed_by) ON core.changelog TO cdb_admin;
GRANT DELETE ON core.changelog TO cdb_admin;

CREATE TABLE  core.email_states (
        id                      serial PRIMARY KEY,
        address                 varchar NOT NULL UNIQUE,
        -- see cdedb.database.constants.EmailStatus
        status                  integer NOT NULL,
        notes                   varchar
);
GRANT SELECT, DELETE on core.defect_addresses TO cdb_persona;
GRANT INSERT, UPDATE (notes) ON core.defect_addresses TO cdb_admin;

CREATE TABLE core.cron_store (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL UNIQUE,
        store                   jsonb NOT NULL
);
GRANT SELECT, UPDATE ON core.cron_store_id_seq TO cdb_admin;
GRANT INSERT, SELECT, UPDATE ON core.cron_store TO cdb_admin;

CREATE TABLE core.locks (
        id                      serial PRIMARY KEY,
        -- see cdedb.database.constants.LockType
        handle                  integer NOT NULL UNIQUE,
        atime                   timestamp WITH TIME ZONE DEFAULT now()
);
GRANT SELECT, UPDATE ON core.locks_id_seq TO cdb_admin;
GRANT INSERT, SELECT, DELETE, UPDATE ON core.locks TO cdb_admin;

CREATE TABLE core.anonymous_messages (
        id                      serial PRIMARY KEY,
        message_id              varchar NOT NULL UNIQUE,
        recipient               varchar NOT NULL,
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        encrypted_data          varchar NOT NULL
);
CREATE INDEX anonymous_messages_message_id_idx ON core.anonymous_messages(message_id);
GRANT SELECT, UPDATE(message_id, encrypted_data), INSERT ON core.anonymous_messages TO cdb_persona;
GRANT SELECT, UPDATE ON core.anonymous_messages_id_seq TO cdb_persona;

---
--- SCHEMA cde
---
DROP SCHEMA IF EXISTS cde CASCADE;
CREATE SCHEMA cde;
GRANT USAGE ON SCHEMA cde TO cdb_member;

CREATE TABLE cde.org_period (
        -- historically this was determined by the exPuls number
        -- the formula is id = 2*(year - 1993) + ((month - 1) // 6)
        id                      integer PRIMARY KEY,
        -- has the billing mail already been sent? If so, up to which ID (it
        -- is done incrementally)
        billing_state           integer REFERENCES core.personas(id),
        billing_done            timestamp WITH TIME ZONE DEFAULT NULL,
        billing_count           integer NOT NULL DEFAULT 0,
        -- have those who haven't paid been ejected? If so, up to which ID
        -- (it is done incrementally)
        ejection_state          integer REFERENCES core.personas(id),
        ejection_done           timestamp WITH TIME ZONE DEFAULT NULL,
        ejection_count          integer NOT NULL DEFAULT 0,
        ejection_balance        numeric(8, 2) NOT NULL DEFAULT 0,
        exmember_balance        numeric(11, 2) NOT NULL DEFAULT 0,
        exmember_count          integer NOT NULL DEFAULT 0,
        exmember_state          integer REFERENCES core.personas(id),
        exmember_done           timestamp WITH TIME ZONE DEFAULT NULL,
        -- has the balance already been adjusted? If so, up to which ID
        -- (it is done incrementally)
        balance_state           integer REFERENCES core.personas(id),
        balance_done            timestamp WITH TIME ZONE DEFAULT NULL,
        balance_trialmembers    integer NOT NULL DEFAULT 0,
        balance_total           numeric(11, 2) NOT NULL DEFAULT 0,
        -- keep track of automated archival progress and stats.
        archival_notification_state     integer REFERENCES core.personas(id),
        archival_notification_done      timestamp WITH TIME ZONE DEFAULT NULL,
        archival_notification_count     integer NOT NULL DEFAULT 0,
        archival_state          integer REFERENCES core.personas(id),
        archival_done           timestamp WITH TIME ZONE DEFAULT NULL,
        archival_count          integer NOT NULL DEFAULT 0,
        -- keep track of when the semester was advanced.
        semester_done           timestamp WITH TIME ZONE DEFAULT NULL
);
GRANT SELECT ON cde.org_period TO cdb_persona;
GRANT INSERT, UPDATE ON cde.org_period TO cdb_admin;

CREATE TABLE cde.expuls_period (
        -- historically this was the same as cde.org_period(id)
        id                      integer PRIMARY KEY,
        -- has the address check mail already been sent? If so, up to which
        -- ID (it is done incrementally)
        addresscheck_state      integer REFERENCES core.personas(id),
        addresscheck_done       timestamp WITH TIME ZONE DEFAULT NULL,
        addresscheck_count      integer NOT NULL DEFAULT 0,
        expuls_done             timestamp WITH TIME ZONE DEFAULT NULL
);
GRANT SELECT, INSERT, UPDATE ON cde.expuls_period TO cdb_admin;

CREATE TABLE cde.lastschrift (
        -- meta data
        id                      serial PRIMARY KEY,
        submitted_by            integer REFERENCES core.personas(id) NOT NULL,
        -- actual data
        persona_id              integer REFERENCES core.personas(id) NOT NULL,
        iban                    varchar NOT NULL,
        -- if different from the paying member
        account_owner           varchar,
        account_address         varchar,
        -- validity
        granted_at              timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        revoked_at              timestamp WITH TIME ZONE DEFAULT NULL,
        -- we used different lastschrift subscription forms over the years
        revision                integer NOT NULL DEFAULT 2,
        -- administrative comments
        notes                   varchar
);
CREATE INDEX lastschrift_persona_id_idx ON cde.lastschrift(persona_id);
GRANT SELECT ON cde.lastschrift TO cdb_member;
GRANT UPDATE, INSERT, DELETE ON cde.lastschrift TO cdb_admin;
GRANT SELECT, UPDATE ON cde.lastschrift_id_seq TO cdb_admin;
CREATE UNIQUE INDEX lastschrift_partial_unique_active_idx ON cde.lastschrift (persona_id) WHERE revoked_at IS NULL;

CREATE TABLE cde.lastschrift_transactions (
        id                      serial PRIMARY KEY,
        submitted_by            integer REFERENCES core.personas(id) NOT NULL,
        lastschrift_id          integer REFERENCES cde.lastschrift(id) NOT NULL,
        period_id               integer REFERENCES cde.org_period(id) NOT NULL,
        status                  integer NOT NULL,
        amount                  numeric(8, 2) NOT NULL,
        issued_at               timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        payment_date            date DEFAULT NULL,
        processed_at            timestamp WITH TIME ZONE DEFAULT NULL,
        -- positive for money we got and negative if bounced with fee
        tally                   numeric(8, 2) DEFAULT NULL
);
CREATE INDEX cde_lastschrift_transactions_lastschrift_id_idx ON cde.lastschrift_transactions(lastschrift_id);
GRANT SELECT ON cde.lastschrift_transactions TO cdb_member;
GRANT UPDATE, INSERT, DELETE ON cde.lastschrift_transactions TO cdb_admin;
GRANT SELECT, UPDATE ON cde.lastschrift_transactions_id_seq TO cdb_admin;

CREATE TABLE cde.finance_log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CdeFinanceLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        delta                   numeric(8, 2),
        new_balance             numeric(8, 2),
        change_note             varchar,
        transaction_date        date,
        -- checksums
        -- number of members (SELECT COUNT(*) FROM core.personas WHERE status = ...)
        members                 integer NOT NULL,
        -- sum of all member balances (SELECT SUM(balance) FROM core.personas WHERE is_member = True)
        member_total            numeric(11, 2) NOT NULL,
        -- sum of all member balances (SELECT SUM(balance) FROM core.personas)
        total                   numeric(11, 2) NOT NULL
);
CREATE INDEX cde_finance_log_code_idx ON cde.finance_log(code);
CREATE INDEX cde_finance_log_persona_id_idx ON cde.finance_log(persona_id);
GRANT SELECT, INSERT ON cde.finance_log TO cdb_member;
GRANT SELECT, UPDATE ON cde.finance_log_id_seq TO cdb_member;
-- In contrast to other logs, UPDATE and DELETE are not possible for cdb_admin to ensure integrity.

CREATE TABLE cde.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CdeLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        -- At the moment, there are no persona-specific data in this log.
        -- If one reconsiders this, archive_persona needs to be adjusted.
        -- Still, the standard log table format is maintained.
        CONSTRAINT cde_log_anonymous CHECK (persona_id is NULL),
        change_note             varchar
);
CREATE INDEX cde_log_code_idx ON cde.log(code);
CREATE INDEX cde_log_persona_id_idx ON cde.log(persona_id);
GRANT SELECT ON cde.log TO cdb_member;
-- These are global state changes on the semester change, which shall never be deleted.
GRANT INSERT ON cde.log TO cdb_admin;
GRANT SELECT, UPDATE ON cde.log_id_seq TO cdb_admin;

---
--- SCHEMA past_event
---
--- This is a variation of the schema event (to be found below) which
--- concerns itself with concluded events.
---
DROP SCHEMA IF EXISTS past_event CASCADE;
CREATE SCHEMA past_event;
GRANT USAGE ON SCHEMA past_event TO cdb_persona;

CREATE TABLE past_event.events (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        -- BuB,  JGW, CdE, ...
        institution             integer NOT NULL,
        description             varchar,
        -- any day of the event, used for ordering and determining the first
        -- event a persona participated in
        --
        -- Note, that this is not present in event.events.
        tempus                  date NOT NULL,
        -- Information only visible to participants.
        participant_info        varchar
);
CREATE INDEX past_events_institution_idx ON past_event.events(institution);
GRANT SELECT (id, title, shortname, tempus) ON past_event.events TO cdb_persona;
GRANT SELECT ON past_event.events to cdb_member;
GRANT UPDATE, DELETE, INSERT ON past_event.events TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.events_id_seq TO cdb_admin;

CREATE TABLE past_event.courses (
        id                      serial PRIMARY KEY,
        pevent_id               integer NOT NULL REFERENCES past_event.events(id),
        nr                      varchar,
        title                   varchar NOT NULL,
        description             varchar
);
CREATE INDEX courses_pevent_id_idx ON past_event.courses(pevent_id);
GRANT SELECT, INSERT, UPDATE ON past_event.courses TO cdb_persona;
GRANT DELETE ON past_event.courses TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.courses_id_seq TO cdb_persona;

-- create previously impossible reference
ALTER TABLE core.genesis_cases ADD FOREIGN KEY (pevent_id) REFERENCES past_event.events(id);
ALTER TABLE core.genesis_cases ADD FOREIGN KEY (pcourse_id) REFERENCES past_event.courses(id);

CREATE TABLE past_event.participants (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        pevent_id               integer NOT NULL REFERENCES past_event.events(id),
        pcourse_id              integer REFERENCES past_event.courses(id),
        is_instructor           boolean NOT NULL,
        is_orga                 boolean NOT NULL,
        UNIQUE (persona_id, pevent_id, pcourse_id)
);
CREATE INDEX participants_pevent_id_idx ON past_event.participants(pevent_id);
CREATE INDEX participants_pcourse_id_idx ON past_event.participants(pcourse_id);
GRANT SELECT ON past_event.participants TO cdb_persona;
GRANT INSERT, UPDATE, DELETE ON past_event.participants TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.participants_id_seq TO cdb_admin;

CREATE TABLE past_event.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.PastEventLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        pevent_id               integer REFERENCES past_event.events(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX past_event_log_code_idx ON past_event.log(code);
CREATE INDEX past_event_log_event_id_idx ON past_event.log(pevent_id);
GRANT SELECT ON past_event.log TO cdb_member;
GRANT INSERT, UPDATE (change_note), DELETE ON past_event.log TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.log_id_seq TO cdb_admin;

---
--- SCHEMA event
---
--- Later on you will find the schema past_event for concluded events.
---
DROP SCHEMA IF EXISTS event CASCADE;
CREATE SCHEMA event;
GRANT USAGE ON SCHEMA event TO cdb_persona, cdb_anonymous, cdb_ldap;

CREATE TABLE event.events (
        id                           serial PRIMARY KEY,
        title                        varchar NOT NULL,
        shortname                    varchar UNIQUE NOT NULL,
        -- BuB,  JGW, CdE, ...
        institution                  integer NOT NULL,
        description                  varchar,
        --
        -- cut for past_event.events (modulo column tempus)
        --
        -- URL of event specific page at the CdE homepage
        website_url                  varchar,
        registration_start           timestamp WITH TIME ZONE,
        -- official end of registration
        registration_soft_limit      timestamp WITH TIME ZONE,
        -- actual end of registration, in between participants are
        -- automatically warned about registering late
        registration_hard_limit      timestamp WITH TIME ZONE,
        iban                         varchar,
        orga_address                 varchar,
        registration_text            varchar,
        mail_text                    varchar,
        -- the next one is only visible to participants
        participant_info            varchar,
        use_additional_questionnaire boolean NOT NULL DEFAULT False,
        -- orga remarks
        notes                        varchar,
        field_definition_notes       varchar,
        offline_lock                 boolean NOT NULL DEFAULT False,
        is_visible                   boolean NOT NULL DEFAULT False, -- this is purely cosmetical
        is_course_list_visible       boolean NOT NULL DEFAULT False, -- this is purely cosmetical
        -- show cancelled courses in course list and restrict registration to active courses
        is_course_state_visible      boolean NOT NULL DEFAULT False,
        is_participant_list_visible  boolean NOT NULL DEFAULT False,
        is_course_assignment_visible boolean NOT NULL DEFAULT False,
        is_archived                  boolean NOT NULL DEFAULT False,
        is_cancelled                 boolean NOT NULL DEFAULT False,
        -- reference to special purpose custom data fields
        lodge_field_id               integer DEFAULT NULL -- REFERENCES event.field_definitions(id)
        -- The references above are not yet possible, but will be added later on.
);
-- TODO: ADD indexes for is_visible, is_archived, etc.?
GRANT SELECT (id, title, shortname) ON event.events TO cdb_ldap;
GRANT SELECT, UPDATE ON event.events TO cdb_persona;
GRANT INSERT, DELETE ON event.events TO cdb_admin;
GRANT SELECT, UPDATE ON event.events_id_seq TO cdb_admin;
GRANT SELECT ON event.events to cdb_anonymous;

CREATE TABLE event.event_fees (
        id                           serial PRIMARY KEY,
        event_id                     integer NOT NULL REFERENCES event.events (id),
        -- see cdedb.database.constants.EventFeeType
        kind                         integer NOT NULL DEFAULT 1,
        title                        varchar NOT NULL,
        amount                       numeric(8, 2) NOT NULL,
        condition                    varchar NOT NULL,
        notes                        varchar
);
GRANT INSERT, SELECT, UPDATE, DELETE ON event.event_fees TO cdb_persona;
GRANT SELECT, UPDATE on event.event_fees_id_seq TO cdb_persona;
GRANT SELECT on event.event_fees TO cdb_anonymous;

CREATE TABLE event.event_parts (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE,
        part_begin              date NOT NULL,
        part_end                date NOT NULL,
        -- reference to custom data field for waitlist management
        waitlist_field_id       integer DEFAULT NULL, -- REFERENCES event.field_definitions(id)
        camping_mat_field_id    integer DEFAULT NULL -- REFERENCES event.field_definitions(id)
        -- The references above are not yet possible, but will be added later on.
);
CREATE INDEX event_parts_event_id_idx ON event.event_parts(event_id);
CREATE INDEX event_parts_partial_waitlist_field_id_idx ON event.event_parts(waitlist_field_id) WHERE waitlist_field_id IS NOT NULL;
GRANT INSERT, SELECT, UPDATE, DELETE ON event.event_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.event_parts_id_seq TO cdb_persona;
GRANT SELECT ON event.event_parts TO cdb_anonymous;

CREATE TABLE event.part_groups (
        id                      serial PRIMARY KEY,
        event_id                integer REFERENCES event.events(id) NOT NULL,
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        notes                   varchar,
        constraint_type         integer NOT NULL,
        UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE,
        UNIQUE (event_id, title) DEFERRABLE INITIALLY IMMEDIATE
);
GRANT INSERT, SELECT, DELETE ON event.part_groups TO cdb_persona;
GRANT UPDATE (title, shortname, notes) ON event.part_groups TO cdb_persona;
GRANT SELECT, UPDATE ON event.part_groups_id_seq TO cdb_persona;
GRANT SELECT ON event.part_groups TO cdb_anonymous;

CREATE TABLE event.part_group_parts (
        id                      serial PRIMARY KEY,
        part_group_id           integer REFERENCES event.part_groups(id),
        part_id                 integer REFERENCES event.event_parts(id),
        UNIQUE (part_id, part_group_id) DEFERRABLE INITIALLY IMMEDIATE
);
GRANT INSERT, SELECT, DELETE ON event.part_group_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.part_group_parts_id_seq TO cdb_persona;
GRANT SELECT ON event.part_group_parts TO cdb_anonymous;

-- each course can take place in an arbitrary number of tracks
CREATE TABLE event.course_tracks (
        id                      serial PRIMARY KEY,
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        num_choices             integer NOT NULL,
        min_choices             integer NOT NULL, -- required number of distinct course choices
        sortkey                 integer NOT NULL,
        course_room_field_id    integer DEFAULT NULL  -- REFERENCES event.field_definitions(id)
        -- The references above are not yet possible, but will be added later on.
);
CREATE INDEX course_tracks_part_id_idx ON event.course_tracks(part_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_tracks TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_tracks_id_seq TO cdb_persona;
GRANT SELECT ON event.course_tracks TO cdb_anonymous;

CREATE TABLE event.track_groups (
        id                      serial PRIMARY KEY,
        event_id                integer REFERENCES event.events(id) NOT NULL,
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        notes                   varchar,
        constraint_type         integer NOT NULL,
        sortkey                 integer NOT NULL,
        UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE,
        UNIQUE (event_id, title) DEFERRABLE INITIALLY IMMEDIATE
);
GRANT INSERT, SELECT, DELETE ON event.track_groups TO cdb_persona;
GRANT UPDATE (title, shortname, notes, sortkey) ON event.track_groups TO cdb_persona;
GRANT SELECT, UPDATE ON event.track_groups_id_seq TO cdb_persona;
GRANT SELECT ON event.track_groups TO cdb_anonymous;

CREATE TABLE event.track_group_tracks (
        id                      serial PRIMARY KEY,
        track_group_id          integer REFERENCES event.track_groups(id) NOT NULL,
        track_id                integer REFERENCES event.course_tracks(id) NOT NULL,
        UNIQUE (track_id, track_group_id) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX track_group_tracks_track_group_id_idx ON event.track_group_tracks(track_group_id);
GRANT INSERT, SELECT, DELETE ON event.track_group_tracks TO cdb_persona;
GRANT SELECT, UPDATE ON event.track_group_tracks_id_seq TO cdb_persona;
GRANT SELECT ON event.track_group_tracks TO cdb_anonymous;

CREATE TABLE event.field_definitions (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        -- the field_name is an identifier and may not be changed.
        field_name              varchar NOT NULL,
        -- the title is displayed to the user, may contain any string and can be changed.
        title                   varchar NOT NULL,
        sortkey                 integer NOT NULL DEFAULT 0,
        -- anything allowed as type in a query spec, see cdedb.database.constants.FieldDatatypes
        kind                    integer NOT NULL,
        -- see cdedb.database.constants.FieldAssociations
        association             integer NOT NULL,
        -- whether or not to display this field during checkin.
        checkin                 boolean NOT NULL DEFAULT FALSE,
        -- the following array describes the available selections
        -- first entry of each tuple is the value, second entry the description
        -- the whole thing may be NULL, if the field does not enforce a
        -- particular selection and is free-form instead
        entries                 varchar[][2],
        -- make event/name combinations unique to avoid surprises
        UNIQUE (event_id, field_name)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.field_definitions TO cdb_persona;
GRANT SELECT, UPDATE ON event.field_definitions_id_seq TO cdb_persona;
GRANT SELECT ON event.field_definitions TO cdb_anonymous;

-- create previously impossible reference
ALTER TABLE event.events ADD FOREIGN KEY (lodge_field_id) REFERENCES event.field_definitions(id);
ALTER TABLE event.event_parts ADD FOREIGN KEY (waitlist_field_id) REFERENCES event.field_definitions(id);
ALTER TABLE event.event_parts ADD FOREIGN KEY (camping_mat_field_id) REFERENCES event.field_definitions(id);
ALTER TABLE event.course_tracks ADD FOREIGN KEY (course_room_field_id) REFERENCES event.field_definitions(id);

CREATE TABLE event.courses (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        nr                      varchar,
        title                   varchar NOT NULL,
        description             varchar,
        --
        -- cut for past_event.courses
        --
        shortname               varchar NOT NULL,
        -- string containing all course-instructors
        instructors             varchar,
        min_size                integer,
        max_size                integer,
        -- orga remarks
        notes                   varchar,
        -- additional data, customized by each orga team
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX courses_event_id_idx ON event.courses(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.courses TO cdb_persona;
GRANT SELECT, UPDATE ON event.courses_id_seq TO cdb_persona;
GRANT SELECT ON event.courses TO cdb_anonymous;

-- not an array inside event.courses since no ELEMENT REFERENCES in postgres
CREATE TABLE event.course_segments (
        id                      serial PRIMARY KEY,
        course_id               integer NOT NULL REFERENCES event.courses(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        is_active               boolean NOT NULL DEFAULT True,
        UNIQUE (track_id, course_id)
);
CREATE INDEX course_segments_course_id_idx ON event.course_segments(course_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_segments TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_segments_id_seq TO cdb_persona;
GRANT SELECT ON event.course_segments TO cdb_anonymous;

CREATE TABLE event.orgas (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id),
        UNIQUE (persona_id, event_id)
);
CREATE INDEX orgas_event_id_idx ON event.orgas(event_id);
GRANT INSERT, UPDATE, DELETE ON event.orgas TO cdb_admin;
GRANT SELECT, UPDATE ON event.orgas_id_seq TO cdb_admin;
GRANT SELECT ON event.orgas TO cdb_anonymous, cdb_ldap;

CREATE TABLE event.orga_apitokens (
        id                      serial PRIMARY KEY,
        -- Event which this token grants access to.
        event_id                integer NOT NULL REFERENCES event.events(id),
        -- The api tokens consists of two parts. The id and a secret that will be compared to the stored hash.
        -- Upon revocation the stored hash is deleted.
        secret_hash             varchar,
        -- Creation, expiration, revocation and last access time of the token.
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        etime                   timestamp WITH TIME ZONE NOT NULL,
        rtime                   timestamp WITH TIME ZONE,
        atime                   timestamp WITH TIME ZONE,
        -- Descriptive title and addional notes about the token.
        title                   varchar NOT NULL,
        notes                   varchar
);
CREATE INDEX orga_apitokens_event_id_idx ON event.orga_apitokens(event_id);
GRANT SELECT ON event.orga_apitokens TO cdb_anonymous;
GRANT UPDATE (atime) ON event.orga_apitokens TO cdb_anonymous;
GRANT SELECT, INSERT, DELETE ON event.orga_apitokens TO cdb_persona;
GRANT UPDATE (secret_hash, rtime, title, notes) ON event.orga_apitokens TO cdb_persona;
GRANT SELECT, UPDATE ON event.orga_apitokens_id_seq TO cdb_persona;

CREATE TABLE event.lodgement_groups (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL
);
CREATE INDEX lodgement_groups_event_id_idx ON event.lodgement_groups(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.lodgement_groups TO cdb_persona;
GRANT SELECT, UPDATE ON event.lodgement_groups_id_seq TO cdb_persona;

CREATE TABLE event.lodgements (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL,
        regular_capacity        integer NOT NULL,
        -- number of people which can be accommodated with reduced comfort
        camping_mat_capacity    integer NOT NULL DEFAULT 0,
        -- orga remarks
        notes                   varchar,
        group_id                integer NOT NULL REFERENCES event.lodgement_groups(id),
        -- additional data, customized by each orga team
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX lodgements_event_id_idx ON event.lodgements(event_id);
-- TODO: Index on group_id.
GRANT SELECT, INSERT, UPDATE, DELETE ON event.lodgements TO cdb_persona;
GRANT SELECT, UPDATE ON event.lodgements_id_seq TO cdb_persona;

CREATE TABLE event.registrations (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        -- to be used by offline deployments
        --
        -- There we have to create new personas for everybody registering
        -- offline, which will not be imported into the online database, but
        -- have to be mapped to an existing persona.
        real_persona_id         integer DEFAULT NULL,
        event_id                integer NOT NULL REFERENCES event.events(id),

        -- participant freeform info
        notes                   varchar,
        -- orga remarks
        orga_notes              varchar DEFAULT NULL,
        is_member               boolean NOT NULL,
        payment                 date DEFAULT NULL,
        amount_paid             numeric(8, 2) NOT NULL DEFAULT 0,
        amount_owed             numeric(8, 2) NOT NULL DEFAULT 0,
        -- parental consent for minors (defaults to True for non-minors)
        parental_agreement      boolean NOT NULL DEFAULT False,
        mixed_lodging           boolean NOT NULL,
        checkin                 timestamp WITH TIME ZONE DEFAULT NULL,
        -- consent to information being included in participant list send to all participants.
        list_consent            boolean NOT NULL,

        -- only basic data should be defined here and everything else will
        -- be handeled via additional fields
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE (persona_id, event_id)
);
CREATE INDEX registrations_event_id_idx ON event.registrations(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.registrations TO cdb_persona;
GRANT SELECT, UPDATE ON event.registrations_id_seq TO cdb_persona;

CREATE TABLE event.registration_parts (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        -- enum for status of this registration part
        -- see cdedb.database.constants.RegistrationPartStati
        status                  integer NOT NULL,
        lodgement_id            integer REFERENCES event.lodgements(id) DEFAULT NULL,
        is_camping_mat          boolean NOT NULL DEFAULT False,
        UNIQUE (part_id, registration_id)
);
CREATE INDEX registration_parts_registration_id_idx ON event.registration_parts(registration_id);
-- TODO: Index on lodgement_id?
GRANT SELECT, INSERT, UPDATE, DELETE ON event.registration_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.registration_parts_id_seq TO cdb_persona;

CREATE TABLE event.registration_tracks (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        course_id               integer REFERENCES event.courses(id),
        -- this is NULL if not an instructor
        course_instructor       integer REFERENCES event.courses(id),
        UNIQUE (registration_id, track_id)
);
CREATE INDEX registration_tracks_track_id_idx ON event.registration_tracks(track_id);
-- TODO: Indexes for course_id and course_instructor?
GRANT SELECT, INSERT, UPDATE, DELETE ON event.registration_tracks TO cdb_persona;
GRANT SELECT, UPDATE ON event.registration_tracks_id_seq TO cdb_persona;

CREATE TABLE event.course_choices (
        id                      bigserial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        course_id               integer NOT NULL REFERENCES event.courses(id),
        rank                    integer NOT NULL,
        UNIQUE (registration_id, track_id, course_id),
        UNIQUE (registration_id, track_id, rank)
);
CREATE INDEX course_choices_track_id_rank_idx ON event.course_choices(track_id, rank);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_choices TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_choices_id_seq TO cdb_persona;

CREATE TABLE event.questionnaire_rows (
        id                      bigserial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        -- This is NULL for text-only entries.
        field_id                integer REFERENCES event.field_definitions(id),
        pos                     integer NOT NULL,
        title                   varchar,
        info                    varchar,
        input_size              integer,
        -- This must be NULL exactly for text-only entries.
        readonly                boolean,
        CONSTRAINT questionnaire_row_readonly_field
            CHECK ((field_id IS NULL) = (readonly IS NULL)),
        default_value           varchar,
        -- Where the row will be used (registration, questionnaire). See cdedb.constants.QuestionnaireUsages.
        kind                    integer NOT NULL
);
CREATE INDEX questionnaire_rows_event_id_idx ON event.questionnaire_rows(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_rows TO cdb_persona;
GRANT SELECT, UPDATE ON event.questionnaire_rows_id_seq TO cdb_persona;

CREATE TABLE event.stored_queries (
        id                      bigserial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events,
        query_name              varchar NOT NULL,
        -- See cdedb.common.query.QueryScope:
        scope                   integer NOT NULL,
        serialized_query        jsonb NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE(event_id, query_name)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.stored_queries TO cdb_persona;
GRANT SELECT, UPDATE ON event.stored_queries_id_seq TO cdb_persona;

CREATE TABLE event.custom_query_filters (
        id                      bigserial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events,
        -- See cdedb.common.query.QueryScope:
        scope                   integer NOT NULL,
        fields                  varchar NOT NULL,
        title                   varchar NOT NULL,
        notes                   varchar,
        UNIQUE (event_id, title),
        UNIQUE (event_id, fields)
);
GRANT SELECT ON event.custom_query_filters TO cdb_anonymous;
GRANT INSERT, UPDATE, DELETE ON event.custom_query_filters TO cdb_persona;
GRANT SELECT, UPDATE ON event.custom_query_filters_id_seq TO cdb_persona;

CREATE TABLE event.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.EventLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        droid_id                integer REFERENCES event.orga_apitokens(id),
        CONSTRAINT event_log_submitted_by_droid
            CHECK (submitted_by is NULL or droid_id is NULL),
        event_id                integer REFERENCES event.events(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX event_log_code_idx ON event.log(code);
CREATE INDEX event_log_event_id_idx ON event.log(event_id);
GRANT SELECT, INSERT ON event.log TO cdb_persona;
GRANT SELECT, UPDATE ON event.log_id_seq TO cdb_persona;
GRANT UPDATE (change_note), DELETE ON event.log TO cdb_admin;

---
--- SCHEMA assembly
---
DROP SCHEMA IF EXISTS assembly CASCADE;
CREATE SCHEMA assembly;
GRANT USAGE ON SCHEMA assembly TO cdb_persona, cdb_ldap;

CREATE TABLE assembly.assemblies (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        description             varchar,
        presider_address        varchar,
        -- after which time are you not allowed to sign up any more
        signup_end              timestamp WITH TIME ZONE NOT NULL,
        -- concluded assemblies get deactivated and all related secrets are
        -- purged
        is_active               boolean NOT NULL DEFAULT True,
        -- administrative comments
        notes                   varchar
);
GRANT SELECT ON assembly.assemblies TO cdb_persona;
GRANT SELECT (id, title, shortname) ON assembly.assemblies TO cdb_ldap;
GRANT INSERT, DELETE ON assembly.assemblies TO cdb_admin;
GRANT UPDATE ON assembly.assemblies TO cdb_member;
GRANT SELECT, UPDATE ON assembly.assemblies_id_seq TO cdb_admin;

CREATE TABLE assembly.presiders (
        id                      serial PRIMARY KEY,
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        UNIQUE(persona_id, assembly_id)
);
CREATE INDEX ON assembly.presiders(assembly_id);
GRANT SELECT ON assembly.presiders TO cdb_persona, cdb_ldap;
GRANT INSERT, DELETE ON assembly.presiders TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.presiders_id_seq TO cdb_admin;

CREATE TABLE assembly.ballots (
        id                      serial PRIMARY KEY,
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        title                   varchar NOT NULL,
        description             varchar,
        vote_begin              timestamp WITH TIME ZONE NOT NULL,
        -- normal end, at this point in time the quorum is checked
        vote_end                timestamp WITH TIME ZONE NOT NULL,
        -- if the quorum is not met the time is extended
        vote_extension_end      timestamp WITH TIME ZONE,
        -- keep track of wether the quorum was missed
        -- NULL as long as normal voting has not ended
        extended                boolean DEFAULT NULL,
        -- Enable a special candidate option which means "options below this
        -- are not acceptable as outcome to me". For electing a person an
        -- alternative title may be "reopen nominations".
        --
        -- It will not be listed in the assembly.candidates table, but added
        -- on the fly. Its shortname will be "_bar_".
        use_bar                 boolean NOT NULL,
        -- number of submitted votes necessary to not trigger extension.
        -- quorum is the actual value, but will be calculated from abs_quorum or
        -- rel_quorum until regular voting ends. After that it is saved to quorum.
        abs_quorum              integer NOT NULL DEFAULT 0,
        rel_quorum              integer NOT NULL DEFAULT 0,
        quorum                  integer,
        -- number of votes per ballot
        --
        -- NULL means arbitrary preference list
        -- n > 0 means, that the list must be of one of the following forms
        --     * a_1=a_2=...=a_m>b_1=b_2=...=b_l
        --       with m non-negative and at most n, if the bar is used it
        --       must be one of the b_i
        --     * o_1=o_2=...=o_l
        --       to encode abstention
        --     * _bar_>o_1=o_2=...=o_l
        --       to encode disapproval of all candidates (only if the bar is used)
        votes                   integer DEFAULT NULL,
        -- True after creation of the result summary file
        is_tallied              boolean NOT NULL DEFAULT False,
        -- administrative comments
        notes                   varchar,
        -- comment to be added after the ballot has finished
        comment                 varchar
);
CREATE INDEX ballots_assembly_id_idx ON assembly.ballots(assembly_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON assembly.ballots TO cdb_member;
GRANT SELECT, UPDATE ON assembly.ballots_id_seq TO cdb_member;

CREATE TABLE assembly.candidates (
        id                      serial PRIMARY KEY,
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        CONSTRAINT candidate_shortname_constraint UNIQUE (ballot_id, shortname) DEFERRABLE INITIALLY IMMEDIATE
);
GRANT SELECT ON assembly.candidates TO cdb_member;
GRANT INSERT, UPDATE, DELETE ON assembly.candidates TO cdb_member;
GRANT SELECT, UPDATE ON assembly.candidates_id_seq TO cdb_member;

CREATE TABLE assembly.attendees (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        secret                  varchar,
        UNIQUE (persona_id, assembly_id)
);
CREATE INDEX attendees_assembly_id_idx ON assembly.attendees(assembly_id);
GRANT SELECT, INSERT ON assembly.attendees TO cdb_member;
GRANT UPDATE (secret) ON assembly.attendees TO cdb_admin;
GRANT DELETE ON assembly.attendees TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.attendees_id_seq TO cdb_member;

-- register who did already vote for what
CREATE TABLE assembly.voter_register (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        has_voted               boolean NOT NULL DEFAULT False,
        UNIQUE (persona_id, ballot_id)
);
CREATE INDEX voter_register_ballot_id_idx ON assembly.voter_register(ballot_id);
GRANT SELECT, INSERT, DELETE ON assembly.voter_register TO cdb_member;
GRANT UPDATE (has_voted) ON assembly.voter_register TO cdb_member;
GRANT SELECT, UPDATE ON assembly.voter_register_id_seq TO cdb_member;

CREATE TABLE assembly.votes (
        id                      serial PRIMARY KEY,
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        -- The vote is of the form '2>3=1>0>4' where the pieces between the
        -- relation symbols are the corresponding shortnames from
        -- assembly.candidates.
        vote                    varchar NOT NULL,
        salt                    varchar NOT NULL,
        -- This is the SHA512 of the concatenation of salt, voting secret and vote.
        hash                    varchar NOT NULL
);
CREATE INDEX votes_ballot_id_idx ON assembly.votes(ballot_id);
GRANT SELECT, INSERT, UPDATE ON assembly.votes TO cdb_member;
GRANT SELECT, UPDATE ON assembly.votes_id_seq TO cdb_member;

CREATE TABLE assembly.attachments (
       -- This serves as a common reference point for attachment versions, but does
       -- not contain any actual data other than the linked assembly.
       id                       serial PRIMARY KEY,
       assembly_id              integer NOT NULL REFERENCES assembly.assemblies(id)
);
CREATE INDEX attachments_assembly_id_idx ON assembly.attachments(assembly_id);
GRANT SELECT, UPDATE, INSERT, DELETE ON assembly.attachments TO cdb_member;
GRANT SELECT, UPDATE ON assembly.attachments_id_seq TO cdb_member;

CREATE TABLE assembly.attachment_versions (
        id                      bigserial PRIMARY KEY,
        attachment_id           integer NOT NULL REFERENCES assembly.attachments(id),
        version_nr              integer NOT NULL DEFAULT 1,
        title                   varchar,
        authors                 varchar,
        filename                varchar,
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        dtime                   timestamp WITH TIME ZONE DEFAULT NULL,
        -- Store the hash of the file for comparison and proof.
        file_hash               varchar NOT NULL,
        UNIQUE (attachment_id, version_nr)
);
GRANT SELECT, INSERT, DELETE ON assembly.attachment_versions TO cdb_member;
GRANT UPDATE (title, authors, filename, dtime) ON assembly.attachment_versions TO cdb_member;
GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_member;

CREATE TABLE assembly.attachment_ballot_links (
        id                      bigserial PRIMARY KEY,
        attachment_id           integer NOT NULL REFERENCES assembly.attachments(id),
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        UNIQUE (attachment_id, ballot_id)
);
CREATE INDEX attachment_ballot_links_ballot_id_idx ON assembly.attachment_ballot_links(ballot_id);
GRANT SELECT, INSERT, DELETE, UPDATE ON assembly.attachment_ballot_links TO cdb_member;
GRANT SELECT, UPDATE ON assembly.attachment_ballot_links_id_seq TO cdb_member;

CREATE TABLE assembly.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.AssemblyLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        assembly_id             integer REFERENCES assembly.assemblies(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX assembly_log_code_idx ON assembly.log(code);
CREATE INDEX assembly_log_assembly_id_idx ON assembly.log(assembly_id);
GRANT UPDATE (change_note), DELETE ON assembly.log TO cdb_admin;
GRANT SELECT, INSERT ON assembly.log TO cdb_member;
GRANT SELECT, UPDATE ON assembly.log_id_seq TO cdb_member;

---
--- SCHEMA ml
---
DROP SCHEMA IF EXISTS ml CASCADE;
CREATE SCHEMA ml;
GRANT USAGE ON SCHEMA ml TO cdb_persona, cdb_ldap;

CREATE TABLE ml.mailinglists (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        -- explicitly store the address for simplicity.
        address                 varchar UNIQUE NOT NULL,
        local_part              varchar NOT NULL,
        -- see cdedb.database.constants.MailinglistDomain
        domain                  integer NOT NULL,
        CONSTRAINT mailinglists_unique_address
            UNIQUE(domain, local_part),
        description             varchar,
        -- see cdedb.database.constants.ModerationPolicy
        mod_policy              integer NOT NULL,
        -- see cdedb.database.constants.AttachmentPolicy
        attachment_policy       integer NOT NULL,
        convert_html            boolean NOT NULL DEFAULT TRUE,
        -- see cdedb.database.constants.MailinglistTypes
        ml_type                 integer NOT NULL,
        -- see cdedb.database.constants.MailinglistRosterVisibility
        roster_visibility       integer NOT NULL,
        subject_prefix          varchar,
        -- in kB
        maxsize                 integer,
        is_active               boolean NOT NULL,
        -- administrative comments
        notes                   varchar,
        additional_footer       varchar,
        -- mailinglist awareness
        -- gateway is not NULL if associated to another mailinglist
        gateway                 integer REFERENCES ml.mailinglists(id),
        -- event awareness
        -- event_id is not NULL if associated to an event
        event_id                integer REFERENCES event.events(id),
        -- which stati to address
        -- (cf. cdedb.database.constants.RegistrationPartStati)
        -- this may be empty, in which case this is an orga list
        registration_stati      integer[] NOT NULL DEFAULT array[]::integer[],
        -- assembly awareness
        -- assembly_id is not NULL if associated to an assembly
        assembly_id             integer REFERENCES assembly.assemblies(id)
);
GRANT SELECT (id, address, title) ON ml.mailinglists TO cdb_ldap;
GRANT SELECT, UPDATE ON ml.mailinglists TO cdb_persona;
GRANT INSERT, DELETE ON ml.mailinglists TO cdb_admin;
GRANT SELECT, UPDATE ON ml.mailinglists_id_seq TO cdb_admin;
-- TODO add assembly_id and event_id indexes.

-- Record mailinglist membership information.
--
-- In general there are three ways to become a member of a mailinglist:
--   * explicit subscription,
--   * the list is not additive (i.e. opt_out) and being part of the audience,
--   * the list is linked to an event or assembly where one participates.
--
-- However in every case the is_subscribed boolean below is authorative. And
-- only if there is no explicit entry then the implicit criterions (number 2
-- and 3 above) are evaluated.
CREATE TABLE ml.subscription_states (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        subscription_state      integer NOT NULL,
        UNIQUE (persona_id, mailinglist_id)
);
CREATE INDEX subscription_states_mailinglist_id_idx ON ml.subscription_states(mailinglist_id);
GRANT SELECT ON ml.subscription_states TO cdb_ldap;
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_states TO cdb_persona;
GRANT SELECT, UPDATE ON ml.subscription_states_id_seq TO cdb_persona;

CREATE TABLE ml.subscription_addresses (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        address                 varchar NOT NULL,
        UNIQUE (persona_id, mailinglist_id),
        UNIQUE (address, mailinglist_id)
);
CREATE INDEX subscription_addresses_mailinglist_id_idx ON ml.subscription_addresses(mailinglist_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_addresses TO cdb_persona;
GRANT SELECT, UPDATE ON ml.subscription_addresses_id_seq TO cdb_persona;

CREATE TABLE ml.whitelist (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        address                 varchar NOT NULL,
        UNIQUE (mailinglist_id, address)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.whitelist TO cdb_persona;
GRANT SELECT, UPDATE ON ml.whitelist_id_seq TO cdb_persona;

CREATE TABLE ml.moderators (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        UNIQUE (persona_id, mailinglist_id)
);
CREATE INDEX moderators_mailinglist_id_idx ON ml.moderators(mailinglist_id);
GRANT SELECT ON ml.moderators TO cdb_ldap;
GRANT SELECT, UPDATE, INSERT, DELETE ON ml.moderators TO cdb_persona;
GRANT SELECT, UPDATE ON ml.moderators_id_seq TO cdb_persona;

CREATE TABLE ml.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.MlLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        mailinglist_id          integer REFERENCES ml.mailinglists(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX ml_log_code_idx ON ml.log(code);
CREATE INDEX ml_log_mailinglist_id_idx ON ml.log(mailinglist_id);
GRANT SELECT, INSERT ON ml.log TO cdb_persona;
GRANT UPDATE (change_note), DELETE ON ml.log TO cdb_admin;
GRANT SELECT, UPDATE ON ml.log_id_seq TO cdb_persona;
