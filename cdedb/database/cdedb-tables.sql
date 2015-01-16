-- This file specifies the tables in the database and has the users in
-- cdedb-users.sql as prerequisite, as well as cdedb-db.sql .

-- TODO: grant priveleges
-- TODO: create indices
-- TODO: think about ctime/mtime hack for evreg
-- TODO: tables: quota, lastschrift_*, finance_log, mailinglist_*, assembly_*, cdefiles_*

---
--- SCHEMA core
---

DROP SCHEMA IF EXISTS core;
CREATE SCHEMA core;
GRANT USAGE ON SCHEMA core TO cdb_anonymous;

CREATE TABLE core.personas (
        id                      serial PRIMARY KEY,
        -- an email address
        -- should be lower-cased
        -- may be NULL for archived members
        username                varchar UNIQUE,
        -- password hash as specified by passlib.hash.sha512_crypt
        -- not logged in changelog
        password_hash           varchar NOT NULL,
        -- name to use when adressing user/"Rufname"
        display_name            varchar NOT NULL,
        -- inactive accounts may not log in
        is_active               boolean NOT NULL DEFAULT True,
        -- nature of this entry
        -- see cdedb.database.constants.PersonaStati
        status                  integer NOT NULL,
        -- bitmask of possible privileges
        -- see cdedb.database.constants.PrivilegeBits
        db_privileges           integer NOT NULL DEFAULT 0,
        -- grant access to the CdE cloud (this is utilized via LDAP)
        cloud_account           boolean NOT NULL DEFAULT False
);
CREATE INDEX idx_personas_status ON core.personas(status);
GRANT SELECT ON core.personas TO cdb_anonymous;
GRANT UPDATE (username, password_hash, display_name) ON core.personas TO cdb_persona;
GRANT UPDATE (status) ON core.personas TO cdb_member;
GRANT INSERT, UPDATE ON core.personas TO cdb_admin;
GRANT SELECT, UPDATE ON core.personas_id_seq TO cdb_admin;

-- table for managing creation of new accounts by arbitrary request
CREATE TABLE core.genesis_cases (
        id                      bigserial PRIMARY KEY,
        -- creation time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
        username                varchar NOT NULL,
        full_name               varchar NOT NULL,
        -- status the persona is going to have initially
        persona_status          integer,
        -- user-supplied comment (short justification of request)
        -- may be amended during review
        notes                   varchar,
        -- A verification link is sent to the email address; upon
        -- verification an admittance email is sent to the responsible team
        --
        -- To prevent spam and enhance security every persona creation needs
        -- to be approved by moderators/administrators; upon addmittance an
        -- email is sent, that persona creation can proceed
        --
        -- enum tracking the progress
        -- see cdedb.database.constants.GenesisStati
        case_status             integer NOT NULL DEFAULT 0,
        -- After review we need a persistent and private url.
        secret                  varchar DEFAULT NULL,
        -- who moderated the request
        reviewer                integer REFERENCES core.personas(id)
);
GRANT SELECT, INSERT ON core.genesis_cases To cdb_anonymous;
GRANT SELECT, UPDATE ON core.genesis_cases_id_seq TO cdb_anonymous;
GRANT UPDATE (case_status) ON core.genesis_cases TO cdb_anonymous;
GRANT UPDATE ON core.genesis_cases TO cdb_admin;

-- this table serves as access log, so entries are never deleted
CREATE TABLE core.sessions (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        is_active               boolean NOT NULL DEFAULT True,
        -- login time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
        -- last access time
        atime                   timestamp WITH TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
        ip                      varchar NOT NULL,
        sessionkey              varchar NOT NULL UNIQUE
);
CREATE INDEX idx_sessions_persona_id ON core.sessions(persona_id);
CREATE INDEX idx_sessions_is_active ON core.sessions(is_active);
CREATE INDEX idx_sessions_ip ON core.sessions(ip);
GRANT SELECT, INSERT ON core.sessions TO cdb_anonymous;
GRANT SELECT, UPDATE ON core.sessions_id_seq TO cdb_anonymous;
GRANT UPDATE (is_active) ON core.sessions TO cdb_anonymous;
GRANT UPDATE (atime) ON core.sessions TO cdb_persona;

CREATE TABLE core.quota (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        qdate                   date NOT NULL DEFAULT current_date,
        queries                 integer NOT NULL DEFAULT 0
);
CREATE INDEX idx_quota_persona_id_qdate ON core.quota(qdate, persona_id);
GRANT SELECT, INSERT ON core.quota TO cdb_member;
GRANT SELECT, UPDATE ON core.quota_id_seq TO cdb_member;
GRANT UPDATE (queries) ON core.quota TO cdb_member;

-- log all changes made to the personal data of members (require approval)
--
-- this is in the core realm since the core backend has to be aware of the
-- changelog
CREATE TABLE core.changelog (
        id                      bigserial PRIMARY KEY,
        --
        -- information about the change
        --
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        reviewed_by             integer REFERENCES core.personas(id) DEFAULT NULL,
        cdate                   timestamp WITH TIME ZONE NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
        generation              integer NOT NULL,
        change_note             varchar,
        -- enum for progress of change
        -- see cdedb.database.constants.MemberChangeStati
        change_status           integer NOT NULL DEFAULT 0,
        --
        -- data fields
        --
        -- first those from personas directly
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        username                varchar,
        display_name            varchar,
        is_active               boolean,
        status                  integer,
        db_privileges           integer,
        cloud_account           boolean,
        -- now those frome member_data
        family_name             varchar NOT NULL,
        given_names             varchar NOT NULL,
        title                   varchar,
        name_supplement         varchar,
        gender                  integer NOT NULL,
        birthday                date NOT NULL,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        location                varchar,
        country                 varchar,
        notes                   varchar,
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
        balance                 numeric(8,2) NOT NULL,
        decided_search          boolean,
        trial_member            boolean,
        bub_search              boolean
);
CREATE INDEX idx_changelog_change_status ON core.changelog(change_status);
CREATE INDEX idx_changelog_persona_id ON core.changelog(persona_id);
GRANT SELECT (persona_id) ON core.changelog TO cdb_persona;
GRANT SELECT, INSERT ON core.changelog TO cdb_member;
GRANT SELECT, UPDATE ON core.changelog_id_seq TO cdb_member;
GRANT UPDATE (change_status) ON core.changelog TO cdb_member;
GRANT UPDATE (reviewed_by) ON core.changelog TO cdb_admin;

---
--- SCHEMA cde
---
DROP SCHEMA IF EXISTS cde;
CREATE SCHEMA cde;
GRANT USAGE ON SCHEMA cde TO cdb_member;

CREATE TABLE cde.member_data (
        persona_id              integer PRIMARY KEY REFERENCES core.personas(id),

        -- the data fields
        -- "Nachname"
        family_name             varchar NOT NULL,
        -- "Vornamen" (including middle names)
        given_names             varchar NOT NULL,
        -- in front of name
        title                   varchar DEFAULT NULL,
        -- after name
        name_supplement         varchar DEFAULT NULL,
        -- see cdedb.database.constants.Genders
        gender                  integer NOT NULL,
        birthday                date NOT NULL,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        -- probably a city
        location                varchar,
        country                 varchar,
        -- administrative notes about this user
        notes                   varchar,
        --
        -- here is the cut for event.user_data
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
        balance                 numeric(8,2) NOT NULL DEFAULT 0.00,
        -- True if user decided (positive or negative) on searchability
        decided_search          boolean NOT NULL DEFAULT FALSE,
        -- True for trial members (first semester after the first official academy)
        trial_member            boolean NOT NULL,
        -- if True this member's data may be passed on to BuB
        bub_search              boolean NOT NULL DEFAULT FALSE,
        -- file name of image
        -- not logged in the changelog
        foto                    varchar DEFAULT NULL,

        -- internal field for fulltext search
        -- this contains a concatenation of all other fields
        -- thus enabling fulltext search as substring search on this field
        -- it is automatically updated when a change is committed
        -- this is not logged in the changelog
        fulltext                varchar NOT NULL
);
GRANT SELECT ON cde.member_data TO cdb_member;
GRANT UPDATE ON cde.member_data TO cdb_member;
GRANT INSERT, UPDATE ON cde.member_data TO cdb_admin;

CREATE TABLE cde.semester (
        -- historically this was determined by the exPuls number
        -- the formula is id = 2*(year - 1993) + ((month - 1) // 6)
        id                      integer PRIMARY KEY,
        -- has the billing mail already been sent? If so, up to which ID (it
        -- is done incrementally)
        billing_state           integer REFERENCES core.personas(id),
        billing_done            timestamp WITH TIME ZONE DEFAULT NULL,
        -- have those who haven't paid been ejected? If so, up to which ID
        -- (it is done incrementally)
        ejection_state          integer REFERENCES core.personas(id),
        ejection_done           timestamp WITH TIME ZONE DEFAULT NULL,
        -- has the balance already been adjusted? If so, up to which ID?
        -- (it is done incrementally)
        balance_state           integer REFERENCES core.personas(id),
        balance_done            timestamp WITH TIME ZONE DEFAULT NULL
);

CREATE TABLE cde.expuls (
        id                      integer PRIMARY KEY,
        -- has the address check mail already been sent? If so, up to which
        -- ID (it is done incrementally)
        addresscheck_state      integer REFERENCES core.personas(id),
        addresscheck_done       timestamp WITH TIME ZONE DEFAULT NULL
);

---
--- SCHEMA event
---
--- Later on you will find the schema past_event for concluded events.
---
DROP SCHEMA IF EXISTS event;
CREATE SCHEMA event;
GRANT USAGE ON SCHEMA event TO cdb_persona;

-- this is a partial copy of cde.member_data with the irrelevant fields ommited
-- thus it is possible to upgrade an external user account to a member account
CREATE TABLE event.user_data (
        persona_id              integer PRIMARY KEY REFERENCES core.personas(id),

        -- the data fields
        family_name             varchar NOT NULL,
        given_names             varchar NOT NULL,
        -- in front of name
        title                   varchar DEFAULT NULL,
        -- after name
        name_supplement         varchar DEFAULT NULL,
        -- see cdedb.database.constants.Genders
        gender                  integer NOT NULL,
        birthday                date NOT NULL,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        -- probably a city
        location                varchar,
        country                 varchar,
        -- administrative notes about this user
        notes                   varchar
);
GRANT SELECT, UPDATE ON event.user_data TO cdb_persona;
GRANT INSERT ON event.user_data TO cdb_admin;

CREATE TABLE event.events (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL UNIQUE,
        -- BuB,  JGW, CdE, ...
        organizer               varchar NOT NULL,
        description             varchar,
        --
        -- cut for past_event.events
        --
        shortname               varchar NOT NULL,
        registration_start      date,
        -- official end of registration
        registration_soft_limit date,
        -- actual end of registration, in between participants are
        -- automatically warned about registering late
        registration_hard_limit date,
        use_questionnaire       boolean NOT NULL DEFAULT False,
        notes                   varchar,
        offline_lock            boolean NOT NULL DEFAULT False
);
GRANT SELECT, UPDATE ON event.events TO cdb_persona;
GRANT INSERT ON event.events TO cdb_admin;
GRANT SELECT, UPDATE ON event.events_id_seq TO cdb_admin;

CREATE TABLE event.event_parts (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL,
        -- we implicitly assume, that parts are non-overlapping
        part_begin              date NOT NULL,
        part_end                date NOT NULL,
        -- fees are cummulative
        fee                     numeric(8,2) NOT NULL
);
CREATE INDEX idx_event_parts_event_id ON event.event_parts(event_id);
GRANT INSERT, SELECT, UPDATE, DELETE ON event.event_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.event_parts_id_seq TO cdb_persona;

CREATE TABLE event.courses (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        title                   varchar NOT NULL,
        description             varchar,
        --
        -- cut for past_event.courses
        --
        nr                      varchar,
        shortname               varchar NOT NULL,
        -- string containing all course-instructors
        instructors             varchar,
        notes                   varchar
);
GRANT SELECT, INSERT, UPDATE ON event.courses TO cdb_persona;
GRANT SELECT, UPDATE ON event.courses_id_seq TO cdb_persona;

-- not an array inside event.course_data since no ELEMENT REFERENCES in postgres
CREATE TABLE event.course_parts (
        id                      serial PRIMARY KEY,
        course_id               integer NOT NULL REFERENCES event.courses(id),
        part_id                 integer NOT NULL REFERENCES event.event_parts(id)
);
CREATE INDEX idx_course_parts_course_id ON event.course_parts(course_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.course_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.course_parts_id_seq TO cdb_persona;

CREATE TABLE event.orgas (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id)
);
CREATE INDEX idx_orgas_persona_id ON event.orgas(persona_id);
CREATE INDEX idx_orgas_event_id ON event.orgas(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.orgas TO cdb_persona;
GRANT SELECT, UPDATE ON event.orgas_id_seq TO cdb_persona;

CREATE TABLE event.field_definitions (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        field_name              varchar NOT NULL,
        -- anything allowed as type in a query spec
        kind                    varchar NOT NULL,
        -- the following array describes the available selections
        -- first entry of each tuple is the value, second entry the description
        -- the whole thing may be NULL, if the field does not enforce a
        -- particular selection and is free-form instead
        entries                 varchar[][2]
);
CREATE INDEX idx_field_definitions_event_id ON event.field_definitions(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.field_definitions TO cdb_persona;
GRANT SELECT, UPDATE ON event.field_definitions_id_seq TO cdb_persona;

CREATE TABLE event.lodgements (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        moniker                 varchar NOT NULL,
        capacity                integer NOT NULL,
        -- number of people which can be accommodated with reduced comfort
        reserve                 integer NOT NULL DEFAULT 0,
        notes                   varchar
);
CREATE INDEX idx_lodgements_event_id ON event.lodgements(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.lodgements TO cdb_persona;
GRANT SELECT, UPDATE ON event.lodgements_id_seq TO cdb_persona;

CREATE TABLE event.registrations (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id),

        orga_notes              varchar,
        payment                 date,
        -- parental consent for minors (NULL if not (yet) given, e.g. non-minors)
        parental_agreement      boolean,
        mixed_lodging           boolean,
        checkin                 timestamp WITH TIME ZONE,
        -- foto consent (documentation, password protected gallery)
        foto_consent            boolean DEFAULT NULL,

        -- only basic data should be defined here and everything else will
        -- be handeled via additional fields
        field_data              jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_registrations_persona_id ON event.registrations(persona_id);
CREATE INDEX idx_registrations_event_id ON event.registrations(event_id);
GRANT SELECT, INSERT, UPDATE ON event.registrations TO cdb_persona;
GRANT SELECT, UPDATE ON event.registrations_id_seq TO cdb_persona;

CREATE TABLE event.registration_parts (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        course_id               integer REFERENCES event.courses(id),
        -- enum for status of this registration part
        -- see cdedb.database.constants.RegistrationPartStati
        status                  integer NOT NULL DEFAULT 0,
        lodgement_id            integer REFERENCES event.lodgements(id),
        -- this is NULL if not an instructor
        course_instructor       integer REFERENCES event.courses(id)
);
CREATE INDEX idx_registration_parts_registration_id ON event.registration_parts(registration_id);
GRANT SELECT, INSERT, UPDATE ON event.registration_parts TO cdb_persona;
GRANT SELECT, UPDATE ON event.registration_parts_id_seq TO cdb_persona;

CREATE TABLE event.course_choices (
        id                      bigserial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        course_id               integer NOT NULL REFERENCES event.courses(id),
        rank                    integer NOT NULL
);
CREATE UNIQUE INDEX idx_course_choices_constraint ON event.course_choices(registration_id, part_id, course_id);
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
        readonly                boolean
);
CREATE INDEX idx_questionnaire_rows_event_id ON event.questionnaire_rows(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_rows TO cdb_persona;
GRANT SELECT, UPDATE ON event.questionnaire_rows_id_seq TO cdb_persona;

---
--- SCHEMA past_event
---
--- This is a variation of the schema event which concerns itself with
--- concluded events.
---
DROP SCHEMA IF EXISTS past_event;
CREATE SCHEMA past_event;
GRANT USAGE ON SCHEMA past_event TO cdb_persona;

CREATE TABLE past_event.events (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL UNIQUE,
        -- BuB,  JGW, CdE, ...
        organizer               varchar NOT NULL,
        description             varchar
);
GRANT SELECT, UPDATE ON past_event.events TO cdb_persona;
GRANT INSERT ON past_event.events TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.events_id_seq TO cdb_admin;

CREATE TABLE past_event.courses (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES past_event.events(id),
        title                   varchar NOT NULL,
        description             varchar
);
CREATE INDEX idx_past_courses_event_id ON past_event.courses(event_id); -- change name to avoid collision
GRANT SELECT, INSERT, UPDATE ON past_event.courses TO cdb_persona;
GRANT DELETE ON past_event.courses TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.courses_id_seq TO cdb_persona;

CREATE TABLE past_event.participants (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES past_event.events(id),
        course_id               integer REFERENCES past_event.courses(id),
        is_instructor           boolean NOT NULL,
        is_orga                 boolean NOT NULL
);
CREATE INDEX idx_participants_persona_id ON past_event.participants(persona_id);
CREATE INDEX idx_participants_event_id ON past_event.participants(event_id);
CREATE INDEX idx_participants_course_id ON past_event.participants(course_id);
CREATE UNIQUE INDEX idx_participants_constraint ON past_event.participants(persona_id, event_id, course_id);
GRANT SELECT ON past_event.participants TO cdb_persona;
GRANT INSERT, UPDATE, DELETE ON past_event.participants TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.participants_id_seq TO cdb_admin;

---
--- SCHEMA ml
---
DROP SCHEMA IF EXISTS ml;
CREATE SCHEMA ml;

CREATE TABLE ml.user_data (
        persona_id              integer PRIMARY KEY REFERENCES core.personas(id),
        full_name               varchar NOT NULL,
        -- administrative notes about this user
        notes                   varchar
);

CREATE TABLE ml.mailinglists (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        address                 varchar NOT NULL,
        -- see cdedb.database.constants.SubscriptionPolicy
        sub_policy              integer NOT NULL,
        -- see cdedb.database.constants.ModerationPolicy
        mod_policy              integer NOT NULL,
        subject_prefix          varchar
        -- TODO add event awareness
);

CREATE TABLE ml.subscriptions (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        address                 varchar,
        is_subscribed           boolean
);

CREATE TABLE ml.whitelist (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        address                 varchar NOT NULL
);

CREATE TABLE ml.moderators (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id)
);

-- TODO implement

---
--- SCHEMA assembly
---
DROP SCHEMA IF EXISTS assembly;
CREATE SCHEMA assembly;

CREATE TABLE assembly.user_data (
        persona_id              integer PRIMARY KEY REFERENCES core.personas(id),
        full_name               varchar NOT NULL,
        -- who does this person represent
        organisation            varchar NOT NULL,
        -- administrative notes about this user
        notes                   varchar
);

CREATE TABLE assembly.assemblies (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL
        -- TODO maybe some dates?
);

CREATE TABLE assembly.decisions (
        id                      serial PRIMARY KEY,
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        title                   varchar NOT NULL,
        description             varchar
);

CREATE TABLE assembly.voting_secrets (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        secret                  varchar
);

CREATE TABLE assembly.votes (
        id                      serial PRIMARY KEY,
        decision_id             integer NOT NULL REFERENCES assembly.decisions(id),
        vote                    varchar,
        hash                    varchar
);

-- TODO implement

---
--- SCHEMA files
---
DROP SCHEMA IF EXISTS files;
CREATE SCHEMA files;

-- TODO implement
