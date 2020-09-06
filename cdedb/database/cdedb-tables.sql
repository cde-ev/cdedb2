-- This file specifies the tables in the database and has the users in
-- cdedb-users.sql as prerequisite, as well as cdedb-db.sql .

---
--- SCHEMA core
---

DROP SCHEMA IF EXISTS core;
CREATE SCHEMA core;
GRANT USAGE ON SCHEMA core TO cdb_anonymous;

-- Store all user attributes, many attributes are only meaningful if the
-- persona has the access bit to the corresponding realm.
CREATE TABLE core.personas (
        --
        -- global attributes
        --
        id                      serial PRIMARY KEY,
        -- an email address (should be lower-cased)
        -- may be NULL (which is not nice, but dictated by reality, like expired addresses)
        username                varchar UNIQUE,
        -- password hash as specified by passlib.hash.sha512_crypt
        -- not logged in changelog
        password_hash           varchar NOT NULL,
        -- inactive accounts may not log in
        is_active               boolean NOT NULL DEFAULT True,
        -- administrative notes about this user
        notes                   varchar,

        -- global admin, grants all privileges
        is_meta_admin           boolean NOT NULL DEFAULT False,
        -- allows managing all users and general database configuration
        is_core_admin           boolean NOT NULL DEFAULT False,
        -- allows managing of cde users (members and former members) and
        -- other cde stuff (past events, direct debit)
        is_cde_admin            boolean NOT NULL DEFAULT False,
        is_finance_admin        boolean NOT NULL DEFAULT False,
        -- allows managing of events and event users
        is_event_admin          boolean NOT NULL DEFAULT False,
        -- allows managing of mailinglists and ml users
        is_ml_admin             boolean NOT NULL DEFAULT False,
        -- allows managing of assemblies and assembly users
        is_assembly_admin       boolean NOT NULL DEFAULT False,
        -- allows managing a subset of all mailinglists, those related to CdE Lokalgruppen
        is_cdelokal_admin       boolean NOT NULL DEFAULT False,
        -- allows usage of cde functionality
        is_cde_realm            boolean NOT NULL,
        -- allows usage of event functionality
        is_event_realm          boolean NOT NULL,
        -- allows usage of mailinglist functionality
        is_ml_realm             boolean NOT NULL,
        -- allows usage of assembly functionality
        is_assembly_realm       boolean NOT NULL,
        -- member status grants access to additional functionality
        is_member               boolean NOT NULL,
        -- searchability governs whether a persona may search for others
        --
        -- a persona is visible/may search
        -- iff is_searchable and is_member are both TRUE
        is_searchable           boolean NOT NULL DEFAULT False,
        -- signal a data set of a former member which was stripped of all
        -- non-essential attributes to implement data protection
        is_archived             boolean NOT NULL DEFAULT False,

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
        -- see cdedb.database.constants.Genders
        gender                  integer,
        CHECK((NOT is_cde_realm AND NOT is_event_realm) OR is_archived OR gender IS NOT NULL),
        -- may be NULL in historical cases; we try to minimize these occurences
        birthday                date,
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
        balance                 numeric(8,2) DEFAULT NULL,
        CHECK(NOT is_cde_realm OR balance IS NOT NULL),
        -- True if user decided (positive or negative) on searchability
        decided_search          boolean DEFAULT FALSE,
        CHECK(NOT is_cde_realm OR decided_search IS NOT NULL),
        -- True for trial members (first semester after the first official academy)
        trial_member            boolean,
        CHECK(NOT is_cde_realm OR trial_member IS NOT NULL),
        -- if True this member's data may be passed on to BuB
        bub_search              boolean DEFAULT FALSE,
        CHECK(NOT is_cde_realm OR bub_search IS NOT NULL),
        -- file name of image
        foto                    varchar DEFAULT NULL,
        -- wants to receive the exPuls in printed form
        paper_expuls            boolean DEFAULT TRUE,
        CHECK(NOT is_cde_realm OR paper_expuls IS NOT NULL),
        -- automatically managed attribute containing all above values as a
        -- string for fulltext search
        fulltext                varchar NOT NULL
);
CREATE INDEX idx_personas_username ON core.personas(username);
CREATE INDEX idx_personas_is_cde_realm ON core.personas(is_cde_realm);
CREATE INDEX idx_personas_is_event_realm ON core.personas(is_event_realm);
CREATE INDEX idx_personas_is_ml_realm ON core.personas(is_ml_realm);
CREATE INDEX idx_personas_is_assembly_realm ON core.personas(is_assembly_realm);
CREATE INDEX idx_personas_is_member ON core.personas(is_member);
CREATE INDEX idx_personas_is_searchable ON core.personas(is_searchable);
GRANT SELECT (id, username, password_hash, is_active, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin, is_event_admin, is_ml_admin, is_assembly_admin, is_cdelokal_admin, is_cde_realm, is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived) ON core.personas TO cdb_anonymous;
GRANT UPDATE (username, password_hash) ON core.personas TO cdb_persona;
GRANT SELECT, UPDATE (display_name, given_names, family_name, title, name_supplement, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, fulltext) ON core.personas TO cdb_persona;
GRANT SELECT, UPDATE ON core.personas TO cdb_member; -- TODO maybe restrict notes to cdb_admin
GRANT INSERT ON core.personas TO cdb_admin;
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
        attachment              varchar,
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
        reviewer                integer REFERENCES core.personas(id) DEFAULT NULL
);
CREATE INDEX idx_genesis_cases_case_status ON core.genesis_cases(case_status);
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
        -- justification supplied by the submitter
        notes                   varchar,
        -- persona who approved the change
        reviewer                integer REFERENCES core.personas(id) DEFAULT NULL
);
CREATE INDEX idx_privilege_changes_status ON core.privilege_changes(status);
GRANT SELECT, INSERT, UPDATE, DELETE ON core.privilege_changes TO cdb_admin;
GRANT SELECT, UPDATE ON core.privilege_changes_id_seq TO cdb_admin;

-- this table serves as access log, so entries are never deleted
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
CREATE INDEX idx_sessions_persona_id ON core.sessions(persona_id);
CREATE INDEX idx_sessions_is_active ON core.sessions(is_active);
GRANT SELECT, INSERT ON core.sessions TO cdb_anonymous;
GRANT SELECT, UPDATE ON core.sessions_id_seq TO cdb_anonymous;
GRANT UPDATE (is_active) ON core.sessions TO cdb_anonymous;
GRANT UPDATE (atime) ON core.sessions TO cdb_persona;
GRANT DELETE ON core.sessions TO cdb_admin;

CREATE TABLE core.quota (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        qdate                   date NOT NULL DEFAULT current_date,
        queries                 integer NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_quota_persona_id_qdate ON core.quota(qdate, persona_id);
GRANT SELECT, INSERT ON core.quota TO cdb_member;
GRANT SELECT, UPDATE ON core.quota_id_seq TO cdb_member;
GRANT UPDATE (queries) ON core.quota TO cdb_member;
GRANT DELETE ON core.quota TO cdb_admin;

-- This table is designed to hold just a single row. Additionally the
-- keys of the dict stored here, will be runtime configurable.
--
-- This is in the core schema to allow anonymous access.
CREATE TABLE core.meta_info
(
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
CREATE INDEX idx_core_log_code ON core.log(code);
CREATE INDEX idx_core_log_persona_id ON core.log(persona_id);
GRANT SELECT, DELETE ON core.log TO cdb_admin;
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
        -- enum for progress of change
        -- see cdedb.database.constants.MemberChangeStati
        code                    integer NOT NULL DEFAULT 0,
        --
        -- data fields
        --
        persona_id              integer NOT NULL REFERENCES core.personas(id),
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
        is_cde_realm            boolean,
        is_event_realm          boolean,
        is_ml_realm             boolean,
        is_assembly_realm       boolean,
        is_member               boolean,
        is_searchable           boolean,
        is_archived             boolean,
        display_name            varchar,
        given_names             varchar,
        family_name             varchar,
        title                   varchar,
        name_supplement         varchar,
        gender                  integer,
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
        decided_search          boolean,
        trial_member            boolean,
        bub_search              boolean,
        foto                    varchar,
        paper_expuls            boolean
);
CREATE INDEX idx_changelog_code ON core.changelog(code);
CREATE INDEX idx_changelog_persona_id ON core.changelog(persona_id);
GRANT SELECT, INSERT ON core.changelog TO cdb_persona;
GRANT SELECT, UPDATE ON core.changelog_id_seq TO cdb_persona;
GRANT UPDATE (code) ON core.changelog TO cdb_persona;
GRANT UPDATE (reviewed_by) ON core.changelog TO cdb_admin;
GRANT DELETE ON core.changelog TO cdb_admin;

CREATE TABLE core.cron_store
(
        id                      serial PRIMARY KEY,
        moniker                 varchar NOT NULL UNIQUE,
        store                   jsonb NOT NULL
);
GRANT SELECT, UPDATE ON core.cron_store_id_seq TO cdb_admin;
GRANT INSERT, SELECT, UPDATE ON core.cron_store TO cdb_admin;

---
--- SCHEMA cde
---
DROP SCHEMA IF EXISTS cde;
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
        -- has the balance already been adjusted? If so, up to which ID
        -- (it is done incrementally)
        balance_state           integer REFERENCES core.personas(id),
        balance_done            timestamp WITH TIME ZONE DEFAULT NULL,
        balance_trialmembers    integer NOT NULL DEFAULT 0,
        balance_total           numeric(8, 2) NOT NULL DEFAULT 0,
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
        amount                  numeric(7,2) NOT NULL,
        iban                    varchar NOT NULL,
        -- if different from the paying member
        account_owner           varchar,
        account_address         varchar,
        -- validity
        granted_at              timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        revoked_at              timestamp WITH TIME ZONE DEFAULT NULL,
        notes                   varchar
);
CREATE INDEX idx_lastschrift_persona_id ON cde.lastschrift(persona_id);
GRANT SELECT ON cde.lastschrift TO cdb_member;
GRANT UPDATE, INSERT, DELETE ON cde.lastschrift TO cdb_admin;
GRANT SELECT, UPDATE ON cde.lastschrift_id_seq TO cdb_admin;

CREATE TABLE cde.lastschrift_transactions
(
        id                      serial PRIMARY KEY,
        submitted_by            integer REFERENCES core.personas(id) NOT NULL,
        lastschrift_id          integer REFERENCES cde.lastschrift(id) NOT NULL,
        period_id               integer REFERENCES cde.org_period(id) NOT NULL,
        status                  integer NOT NULL,
        amount                  numeric(7,2) NOT NULL,
        issued_at               timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        processed_at            timestamp WITH TIME ZONE DEFAULT NULL,
        -- positive for money we got and negative if bounced with fee
        tally                   numeric(7,2) DEFAULT NULL
);
CREATE INDEX idx_cde_lastschrift_transactions_lastschrift_id ON cde.lastschrift_transactions(lastschrift_id);
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
        delta                   numeric(7,2),
        new_balance             numeric(7,2),
        change_note             varchar,
        -- checksums
        -- number of members (SELECT COUNT(*) FROM core.personas WHERE status = ...)
        members                 integer NOT NULL,
        -- sum of all balances (SELECT SUM(balance) FROM core.personas)
        total                   numeric(10,2) NOT NULL
);
CREATE INDEX idx_cde_finance_log_code ON cde.finance_log(code);
CREATE INDEX idx_cde_finance_log_persona_id ON cde.finance_log(persona_id);
GRANT SELECT, INSERT ON cde.finance_log TO cdb_member;
GRANT SELECT, UPDATE ON cde.finance_log_id_seq TO cdb_member;

CREATE TABLE cde.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CdeLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX idx_cde_log_code ON cde.log(code);
CREATE INDEX idx_cde_log_persona_id ON cde.log(persona_id);
GRANT SELECT, INSERT, DELETE ON cde.log TO cdb_admin;
GRANT SELECT, UPDATE ON cde.log_id_seq TO cdb_admin;

---
--- SCHEMA past_event
---
--- This is a variation of the schema event (to be found below) which
--- concerns itself with concluded events.
---
DROP SCHEMA IF EXISTS past_event;
CREATE SCHEMA past_event;
GRANT USAGE ON SCHEMA past_event TO cdb_persona;

CREATE TABLE past_event.institutions (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        moniker                 varchar NOT NULL
);
GRANT SELECT ON past_event.institutions TO cdb_persona;
GRANT INSERT, UPDATE, DELETE ON past_event.institutions TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.institutions_id_seq TO cdb_admin;

CREATE TABLE past_event.events (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        -- BuB,  JGW, CdE, ...
        institution             integer NOT NULL REFERENCES past_event.institutions(id),
        description             varchar,
        -- any day of the event, used for ordering and determining the first
        -- event a persona participated in
        --
        -- Note, that this is not present in event.events.
        tempus                  date NOT NULL,
        -- Information only visible to participants.
        notes                   varchar
);
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
CREATE INDEX idx_courses_pevent_id ON past_event.courses(pevent_id);
GRANT SELECT, INSERT, UPDATE ON past_event.courses TO cdb_persona;
GRANT DELETE ON past_event.courses TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.courses_id_seq TO cdb_persona;

CREATE TABLE past_event.participants (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        pevent_id               integer NOT NULL REFERENCES past_event.events(id),
        pcourse_id              integer REFERENCES past_event.courses(id),
        is_instructor           boolean NOT NULL,
        is_orga                 boolean NOT NULL
);
CREATE INDEX idx_participants_persona_id ON past_event.participants(persona_id);
CREATE INDEX idx_participants_event_id ON past_event.participants(pevent_id);
CREATE INDEX idx_participants_course_id ON past_event.participants(pcourse_id);
CREATE UNIQUE INDEX idx_participants_constraint ON past_event.participants(persona_id, pevent_id, pcourse_id);
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
CREATE INDEX idx_past_event_log_code ON past_event.log(code);
CREATE INDEX idx_past_event_log_event_id ON past_event.log(pevent_id);
GRANT SELECT, INSERT, DELETE ON past_event.log TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.log_id_seq TO cdb_admin;

---
--- SCHEMA event
---
--- Later on you will find the schema past_event for concluded events.
---
DROP SCHEMA IF EXISTS event;
CREATE SCHEMA event;
GRANT USAGE ON SCHEMA event TO cdb_persona, cdb_anonymous;

CREATE TABLE event.events (
        id                          serial PRIMARY KEY,
        title                       varchar NOT NULL,
        shortname                   varchar NOT NULL,
        -- BuB,  JGW, CdE, ...
        institution                 integer NOT NULL REFERENCES past_event.institutions(id),
        description                 varchar,
        --
        -- cut for past_event.events (modulo column tempus)
        --
        registration_start          timestamp WITH TIME ZONE,
        -- official end of registration
        registration_soft_limit     timestamp WITH TIME ZONE,
        -- actual end of registration, in between participants are
        -- automatically warned about registering late
        registration_hard_limit     timestamp WITH TIME ZONE,
        iban                        varchar,
        nonmember_surcharge         numeric(8,2) NOT NULL,
        orga_address                varchar,
        registration_text           varchar,
        mail_text                   varchar,
        use_additional_questionnaire    boolean NOT NULL DEFAULT False,
        notes                       varchar,
        offline_lock                boolean NOT NULL DEFAULT False,
        is_visible                  boolean NOT NULL DEFAULT False, -- this is purely cosmetical
        is_course_list_visible      boolean NOT NULL DEFAULT False, -- this is purely cosmetical
        -- show cancelled courses in course list and restrict registration to active courses
        is_course_state_visible     boolean NOT NULL DEFAULT False,
        is_participant_list_visible boolean NOT NULL DEFAULT False,
        courses_in_participant_list boolean NOT NULL DEFAULT False,
        is_archived                 boolean NOT NULL DEFAULT False,
        is_cancelled                boolean NOT NULL DEFAULT False,
        -- reference to special purpose custom data fields
        lodge_field                 integer DEFAULT NULL, -- REFERENCES event.field_definitions(id)
        camping_mat_field           integer DEFAULT NULL, -- REFERENCES event.field_definitions(id)
        course_room_field           integer DEFAULT NULL -- REFERENCES event.field_definitions(id)
        -- The references above are not yet possible, but will be added later on.
);
GRANT SELECT, UPDATE ON event.events TO cdb_persona;
GRANT INSERT, DELETE ON event.events TO cdb_admin;
GRANT SELECT, UPDATE ON event.events_id_seq TO cdb_admin;
GRANT SELECT ON event.events to cdb_anonymous;

CREATE TABLE event.event_parts (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        -- we implicitly assume, that parts are non-overlapping
        part_begin              date NOT NULL,
        part_end                date NOT NULL,
        -- fees are cummulative
        fee                     numeric(8,2) NOT NULL,
        -- reference to custom data field for waitlist management
        waitlist_field          integer DEFAULT NULL -- REFERENCES event.field_definitions(id)
);
CREATE INDEX idx_event_parts_event_id ON event.event_parts(event_id);
GRANT INSERT, SELECT, UPDATE, DELETE ON event.event_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.event_parts_id_seq TO cdb_persona;
GRANT SELECT ON event.event_parts TO cdb_anonymous;

-- each course can take place in an arbitrary number of tracks
CREATE TABLE event.course_tracks (
        id                      serial PRIMARY KEY,
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        title                   varchar NOT NULL,
        shortname               varchar NOT NULL,
        num_choices             integer NOT NULL,
        min_choices             integer NOT NULL, -- required number of distinct course choices
        sortkey                 integer NOT NULL
);
CREATE INDEX idx_course_tracks_part_id ON event.course_tracks(part_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_tracks TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_tracks_id_seq TO cdb_persona;
GRANT SELECT ON event.course_tracks TO cdb_anonymous;

CREATE TABLE event.field_definitions (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        field_name              varchar NOT NULL,
        -- anything allowed as type in a query spec, see cdedb.database.constants.FieldDatatypes
        kind                    integer NOT NULL,
        -- see cdedb.database.constants.FieldAssociations
        association             integer NOT NULL,
        -- the following array describes the available selections
        -- first entry of each tuple is the value, second entry the description
        -- the whole thing may be NULL, if the field does not enforce a
        -- particular selection and is free-form instead
        entries                 varchar[][2]
);
-- make event/name combinations unique to avoid surprises
CREATE UNIQUE INDEX idx_field_definitions_event_id ON event.field_definitions(event_id, field_name);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.field_definitions TO cdb_persona;
GRANT SELECT, UPDATE ON event.field_definitions_id_seq TO cdb_persona;
GRANT SELECT ON event.field_definitions TO cdb_anonymous;

-- create previously impossible reference
ALTER TABLE event.events ADD FOREIGN KEY (lodge_field) REFERENCES event.field_definitions(id);
ALTER TABLE event.events ADD FOREIGN KEY (camping_mat_field) REFERENCES event.field_definitions(id);
ALTER TABLE event.events ADD FOREIGN KEY (course_room_field) REFERENCES event.field_definitions(id);
ALTER TABLE event.event_parts ADD FOREIGN KEY (waitlist_field) REFERENCES event.field_definitions(id);

CREATE TABLE event.fee_modifiers (
        id                      serial PRIMARY KEY,
        -- the event part this modifier is available in.
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        modifier_name           varchar NOT NULL,
        -- the amount to modify the fee by. Can be negative.
        amount                  decimal(8,2) NOT NULL,
        -- in which field do we save the information whether the modifier has been selected:
        field_id                integer NOT NULL REFERENCES event.field_definitions(id)
);
CREATE UNIQUE INDEX idx_fee_modifiers_part_id ON event.fee_modifiers(part_id, modifier_name);
CREATE UNIQUE INDEX idx_fee_modifiers_field_id ON event.fee_modifiers(part_id, field_id);
GRANT INSERT, UPDATE, DELETE ON event.fee_modifiers TO cdb_persona;
GRANT SELECT ON event.fee_modifiers TO cdb_anonymous;
GRANT SELECT, UPDATE ON event.fee_modifiers_id_seq TO cdb_persona;

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
        notes                   varchar,
        -- additional data, customized by each orga team
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_courses_event_id ON event.courses(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.courses TO cdb_persona;
GRANT SELECT, UPDATE ON event.courses_id_seq TO cdb_persona;
GRANT SELECT ON event.courses TO cdb_anonymous;

-- not an array inside event.courses since no ELEMENT REFERENCES in postgres
CREATE TABLE event.course_segments (
        id                      serial PRIMARY KEY,
        course_id               integer NOT NULL REFERENCES event.courses(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        is_active               boolean NOT NULL DEFAULT True
);
CREATE INDEX idx_course_segments_course_id ON event.course_segments(course_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_segments TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_segments_id_seq TO cdb_persona;
GRANT SELECT ON event.course_segments TO cdb_anonymous;

CREATE TABLE event.orgas (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id)
);
CREATE INDEX idx_orgas_persona_id ON event.orgas(persona_id);
CREATE INDEX idx_orgas_event_id ON event.orgas(event_id);
GRANT INSERT, UPDATE, DELETE ON event.orgas TO cdb_admin;
GRANT SELECT, UPDATE ON event.orgas_id_seq TO cdb_admin;
GRANT SELECT ON event.orgas TO cdb_anonymous;

CREATE TABLE event.lodgement_groups (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        moniker                 varchar NOT NULL
);
CREATE INDEX ids_lodgement_groups_event_id ON event.lodgement_groups(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.lodgement_groups TO cdb_persona;
GRANT SELECT, UPDATE ON event.lodgement_groups_id_seq TO cdb_persona;

CREATE TABLE event.lodgements (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        moniker                 varchar NOT NULL,
        regular_capacity        integer NOT NULL,
        -- number of people which can be accommodated with reduced comfort
        camping_mat_capacity    integer NOT NULL DEFAULT 0,
        notes                   varchar,
        group_id                integer REFERENCES event.lodgement_groups(id),
        -- additional data, customized by each orga team
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_lodgements_event_id ON event.lodgements(event_id);
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

        notes                   varchar,
        orga_notes              varchar DEFAULT NULL,
        payment                 date DEFAULT NULL,
        amount_paid             numeric(7,2) NOT NULL DEFAULT 0,
        amount_owed             numeric(7,2) NOT NULL DEFAULT 0,
        -- parental consent for minors (defaults to True for non-minors)
        parental_agreement      boolean NOT NULL DEFAULT False,
        mixed_lodging           boolean NOT NULL,
        checkin                 timestamp WITH TIME ZONE DEFAULT NULL,
        -- consent to information being included in participant list send to all participants.
        list_consent            boolean NOT NULL,

        -- only basic data should be defined here and everything else will
        -- be handeled via additional fields
        fields                  jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_registrations_persona_id ON event.registrations(persona_id);
CREATE INDEX idx_registrations_event_id ON event.registrations(event_id);
CREATE UNIQUE INDEX idx_registrations_constraint ON event.registrations(persona_id, event_id);
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
        is_camping_mat          boolean NOT NULL DEFAULT False
);
CREATE INDEX idx_registration_parts_registration_id ON event.registration_parts(registration_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.registration_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.registration_parts_id_seq TO cdb_persona;

CREATE TABLE event.registration_tracks (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        course_id               integer REFERENCES event.courses(id),
        -- this is NULL if not an instructor
        course_instructor       integer REFERENCES event.courses(id)
);
CREATE INDEX idx_registration_tracks_registration_id ON event.registration_tracks(registration_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.registration_tracks TO cdb_persona;
GRANT SELECT, UPDATE ON event.registration_tracks_id_seq TO cdb_persona;

CREATE TABLE event.course_choices (
        id                      bigserial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        track_id                integer NOT NULL REFERENCES event.course_tracks(id),
        course_id               integer NOT NULL REFERENCES event.courses(id),
        rank                    integer NOT NULL
);
CREATE UNIQUE INDEX idx_course_choices_constraint ON event.course_choices(registration_id, track_id, course_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_choices TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_choices_id_seq TO cdb_persona;

CREATE TABLE event.questionnaire_rows (
        id                      bigserial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        -- may be NULL for text
        field_id                integer REFERENCES event.field_definitions(id),
        pos                     integer NOT NULL,
        title                   varchar,
        info                    varchar,
        input_size              integer,
        -- may be NULL for text
        readonly                boolean,
        default_value           varchar,
        -- Where the row will be used (registration, questionnaire). See cdedb.constants.QuestionnaireUsages.
        kind                    integer NOT NULL
);
CREATE INDEX idx_questionnaire_rows_event_id ON event.questionnaire_rows(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_rows TO cdb_persona;
GRANT SELECT, UPDATE ON event.questionnaire_rows_id_seq TO cdb_persona;

CREATE TABLE event.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.EventLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        event_id                integer REFERENCES event.events(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX idx_event_log_code ON event.log(code);
CREATE INDEX idx_event_log_event_id ON event.log(event_id);
GRANT SELECT, INSERT ON event.log TO cdb_persona;
GRANT SELECT, UPDATE ON event.log_id_seq TO cdb_persona;
GRANT DELETE ON event.log TO cdb_admin;

---
--- SCHEMA assembly
---
DROP SCHEMA IF EXISTS assembly;
CREATE SCHEMA assembly;
GRANT USAGE ON SCHEMA assembly TO cdb_persona;

CREATE TABLE assembly.assemblies (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        description             varchar,
        mail_address            varchar,
        -- after which time are you not allowed to sign up any more
        signup_end              timestamp WITH TIME ZONE NOT NULL,
        -- concluded assemblies get deactivated and all related secrets are
        -- purged
        is_active               boolean NOT NULL DEFAULT True,
        notes                   varchar
);
GRANT SELECT ON assembly.assemblies TO cdb_persona;
GRANT INSERT, DELETE ON assembly.assemblies TO cdb_admin;
GRANT UPDATE ON assembly.assemblies TO cdb_member;
GRANT SELECT, UPDATE ON assembly.assemblies_id_seq TO cdb_admin;

CREATE TABLE assembly.presiders (
        id                      serial PRIMARY KEY,
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id)
);
CREATE INDEX idx_assembly_presiders_assembly_id ON assembly.presiders(assembly_id);
CREATE INDEX idx_assembly_presiders_persona_id ON assembly.presiders(persona_id);
CREATE UNIQUE INDEX idx_assembly_presiders_constraint ON assembly.presiders(assembly_id, persona_id);
GRANT SELECT ON assembly.presiders TO cdb_persona;
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
        -- on the fly. Its moniker will be "_bar_".
        use_bar                 boolean NOT NULL,
        -- number of submitted votes necessary to not trigger extension
        quorum                  integer NOT NULL DEFAULT 0,
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
        notes                   varchar
);
CREATE INDEX idx_ballots_assembly_id ON assembly.ballots(assembly_id);
GRANT SELECT ON assembly.ballots TO cdb_member;
GRANT UPDATE (extended, is_tallied) ON assembly.ballots TO cdb_member;
GRANT INSERT, UPDATE, DELETE ON assembly.ballots TO cdb_member;
GRANT SELECT, UPDATE ON assembly.ballots_id_seq TO cdb_member;

CREATE TABLE assembly.candidates (
        id                      serial PRIMARY KEY,
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        description             varchar NOT NULL,
        moniker                 varchar NOT NULL
);
CREATE UNIQUE INDEX idx_moniker_constraint ON assembly.candidates(ballot_id, moniker);
GRANT SELECT ON assembly.candidates TO cdb_member;
GRANT INSERT, UPDATE, DELETE ON assembly.candidates TO cdb_member;
GRANT SELECT, UPDATE ON assembly.candidates_id_seq TO cdb_member;

CREATE TABLE assembly.attendees (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        secret                  varchar
);
CREATE UNIQUE INDEX idx_attendee_constraint ON assembly.attendees(persona_id, assembly_id);
GRANT SELECT, INSERT ON assembly.attendees TO cdb_member;
GRANT UPDATE (secret) ON assembly.attendees TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.attendees_id_seq TO cdb_member;

-- register who did already vote for what
CREATE TABLE assembly.voter_register (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        has_voted               boolean NOT NULL DEFAULT False
);
CREATE UNIQUE INDEX idx_voter_constraint ON assembly.voter_register(persona_id, ballot_id);
GRANT SELECT, INSERT, DELETE ON assembly.voter_register TO cdb_member;
GRANT UPDATE (has_voted) ON assembly.voter_register TO cdb_member;
GRANT SELECT, UPDATE ON assembly.voter_register_id_seq TO cdb_member;

CREATE TABLE assembly.votes (
        id                      serial PRIMARY KEY,
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        -- The vote is of the form '2>3=1>0>4' where the pieces between the
        -- relation symbols are the corresponding monikers from
        -- assembly.candidates.
        vote                    varchar NOT NULL,
        salt                    varchar NOT NULL,
        -- This is the SHA512 of the concatenation of salt, voting secret and vote.
        hash                    varchar NOT NULL
);
CREATE INDEX idx_votes_ballot_id ON assembly.votes(ballot_id);
GRANT SELECT, INSERT, UPDATE ON assembly.votes TO cdb_member;
GRANT SELECT, UPDATE ON assembly.votes_id_seq TO cdb_member;

CREATE TABLE assembly.attachments (
       id                       serial PRIMARY KEY,
       -- Each attachment may only be attached to one thing (either an
       -- assembly or a ballot).
       assembly_id              integer REFERENCES assembly.assemblies(id),
       ballot_id                integer REFERENCES assembly.ballots(id)
);
CREATE INDEX idx_attachments_assembly_id ON assembly.attachments(assembly_id);
CREATE INDEX idx_attachments_ballot_id ON assembly.attachments(ballot_id);
GRANT SELECT, UPDATE, INSERT, DELETE ON assembly.attachments TO cdb_member;
GRANT SELECT, UPDATE ON assembly.attachments_id_seq TO cdb_member;

CREATE TABLE assembly.attachment_versions (
        id                      bigserial PRIMARY KEY,
        attachment_id           integer REFERENCES assembly.attachments(id),
        version                 integer NOT NULL DEFAULT 1,
        title                   varchar,
        authors                 varchar,
        filename                varchar,
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        dtime                   timestamp WITH TIME ZONE DEFAULT NULL,
        -- Store the hash of the file for comparison and proof.
        file_hash               varchar NOT NULL
);
CREATE INDEX idx_attachment_versions_attachment_id ON assembly.attachment_versions(attachment_id);
CREATE UNIQUE INDEX idx_attachment_version_constraint ON assembly.attachment_versions(attachment_id, version);
GRANT SELECT, INSERT, DELETE, UPDATE on assembly.attachment_versions TO cdb_member;
GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_member;

CREATE TABLE assembly.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.AssembyLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        assembly_id             integer REFERENCES assembly.assemblies(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        change_note             varchar
);
CREATE INDEX idx_assembly_log_code ON assembly.log(code);
CREATE INDEX idx_assembly_log_assembly_id ON assembly.log(assembly_id);
GRANT SELECT, DELETE ON assembly.log TO cdb_admin;
GRANT INSERT ON assembly.log TO cdb_member;
GRANT SELECT, UPDATE ON assembly.log_id_seq TO cdb_member;

---
--- SCHEMA ml
---
DROP SCHEMA IF EXISTS ml;
CREATE SCHEMA ml;
GRANT USAGE ON SCHEMA ml TO cdb_persona;

CREATE TABLE ml.mailinglists (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        -- explicitly store the address for simplicity.
        address                 varchar UNIQUE NOT NULL,
        local_part              varchar NOT NULL,
        -- see cdedb.database.constants.MailinglistDomains
        domain                  integer NOT NULL,
        unique(local_part, domain),
        description             varchar,
        -- see cdedb.database.constants.ModerationPolicy
        mod_policy              integer NOT NULL,
        -- see cdedb.database.constants.AttachmentPolicy
        attachment_policy       integer NOT NULL,
        -- see cdedb.database.constants.MailinglistTypes
        ml_type                 integer NOT NULL,
        subject_prefix          varchar,
        -- in kB
        maxsize                 integer,
        is_active               boolean NOT NULL,
        notes                   varchar,
        -- Define a list X as gateway for this list, that is everybody
        -- subscribed to X may subscribe to this list (only useful with a
        -- restrictive subscription policy).
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
GRANT SELECT, UPDATE ON ml.mailinglists TO cdb_persona;
GRANT INSERT, DELETE ON ml.mailinglists TO cdb_admin;
GRANT SELECT, UPDATE ON ml.mailinglists_id_seq TO cdb_admin;

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
        subscription_state      integer NOT NULL
);
CREATE UNIQUE INDEX idx_subscription_constraint ON ml.subscription_states(mailinglist_id, persona_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_states TO cdb_persona;
GRANT SELECT, UPDATE ON ml.subscription_states_id_seq TO cdb_persona;

CREATE TABLE ml.subscription_addresses (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        address                 varchar NOT NULL
);
CREATE UNIQUE INDEX idx_subscription_address_constraint ON ml.subscription_addresses(mailinglist_id, persona_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_addresses TO cdb_persona;
GRANT SELECT, UPDATE ON ml.subscription_addresses_id_seq TO cdb_persona;

CREATE TABLE ml.whitelist (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        address                 varchar NOT NULL
);
CREATE INDEX idx_whitelist_mailinglist_id ON ml.whitelist(mailinglist_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.whitelist TO cdb_persona;
GRANT SELECT, UPDATE ON ml.whitelist_id_seq TO cdb_persona;

CREATE TABLE ml.moderators (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id)
);
CREATE INDEX idx_moderators_mailinglist_id ON ml.moderators(mailinglist_id);
CREATE INDEX idx_moderators_persona_id ON ml.moderators(persona_id);
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
CREATE INDEX idx_ml_log_code ON ml.log(code);
CREATE INDEX idx_ml_log_mailinglist_id ON ml.log(mailinglist_id);
GRANT SELECT, INSERT ON ml.log TO cdb_persona;
GRANT DELETE ON ml.log TO cdb_admin;
GRANT SELECT, UPDATE ON ml.log_id_seq TO cdb_persona;
