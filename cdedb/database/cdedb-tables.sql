-- This file specifies the tables in the database and has the users in
-- cdedb-users.sql as prerequisite, as well as cdedb-db.sql .

---
--- SCHEMA core
---

DROP SCHEMA IF EXISTS core;
CREATE SCHEMA core;
GRANT USAGE ON SCHEMA core TO cdb_anonymous;

CREATE TABLE core.personas (
        id                      serial PRIMARY KEY,
        -- an email address (should be lower-cased)
        -- may be NULL (which is not nice, but dictated by reality, like expired addresses)
        username                varchar UNIQUE,
        -- password hash as specified by passlib.hash.sha512_crypt
        -- not logged in changelog
        password_hash           varchar NOT NULL,
        -- name to use when adressing user/"Rufname"
        display_name            varchar NOT NULL,
        -- "Vornamen" (including middle names)
        given_names             varchar NOT NULL,
        -- "Nachname"
        family_name             varchar NOT NULL,
        -- inactive accounts may not log in
        is_active               boolean NOT NULL DEFAULT True,
        -- nature of this entry
        -- see cdedb.database.constants.PersonaStati
        status                  integer NOT NULL,
        -- bitmask of possible privileges
        -- see cdedb.database.constants.PrivilegeBits
        db_privileges           integer NOT NULL DEFAULT 0,
        -- grant access to the CdE cloud (this is utilized via LDAP)
        cloud_account           boolean NOT NULL DEFAULT False,
        -- administrative notes about this user
        notes                   varchar
);
CREATE INDEX idx_personas_status ON core.personas(status);
CREATE INDEX idx_personas_username ON core.personas(username);
GRANT SELECT ON core.personas TO cdb_anonymous;
GRANT UPDATE (username, password_hash, display_name, given_names, family_name) ON core.personas TO cdb_persona;
GRANT UPDATE (status) ON core.personas TO cdb_member;
GRANT INSERT, UPDATE ON core.personas TO cdb_admin;
GRANT SELECT, UPDATE ON core.personas_id_seq TO cdb_admin;

-- table for managing creation of new accounts by arbitrary request
CREATE TABLE core.genesis_cases (
        id                      bigserial PRIMARY KEY,
        -- creation time
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        username                varchar NOT NULL,
        given_names             varchar NOT NULL,
        family_name             varchar NOT NULL,
        -- status the persona is going to have initially
        persona_status          integer DEFAULT NULL,
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
        reviewer                integer REFERENCES core.personas(id) DEFAULT NULL
);
CREATE INDEX idx_genesis_cases_case_status ON core.genesis_cases(case_status);
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

CREATE TABLE core.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CoreLogCodes
        code                    integer NOT NULL,
        submitted_by            integer REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_core_log_code ON core.log(code);
CREATE INDEX idx_core_log_persona_id ON core.log(persona_id);
GRANT SELECT ON core.log TO cdb_admin;
GRANT INSERT ON core.log TO cdb_anonymous;
GRANT SELECT, UPDATE ON core.log_id_seq TO cdb_anonymous;

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
        ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
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
        birthday                date,
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
        -- in front of name
        title                   varchar DEFAULT NULL,
        -- after name
        name_supplement         varchar DEFAULT NULL,
        -- see cdedb.database.constants.Genders
        gender                  integer NOT NULL,
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

CREATE TABLE cde.org_period (
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
        -- has the balance already been adjusted? If so, up to which ID
        -- (it is done incrementally)
        balance_state           integer REFERENCES core.personas(id),
        balance_done            timestamp WITH TIME ZONE DEFAULT NULL
);
GRANT SELECT, INSERT, UPDATE ON cde.org_period TO cdb_admin;

CREATE TABLE cde.expuls_period (
        -- historically this was the same as cde.org_period(id)
        id                      integer PRIMARY KEY,
        -- has the address check mail already been sent? If so, up to which
        -- ID (it is done incrementally)
        addresscheck_state      integer REFERENCES core.personas(id),
        addresscheck_done       timestamp WITH TIME ZONE DEFAULT NULL
);
GRANT SELECT, INSERT, UPDATE ON cde.expuls_period TO cdb_admin;

CREATE TABLE cde.lastschrift (
        -- meta data
        id                      serial PRIMARY KEY,
        submitted_by            integer REFERENCES core.personas(id) NOT NULL,
        -- actual data
        persona_id              integer REFERENCES core.personas(id) NOT NULL,
        amount                  numeric(7,2),
        -- upper limit for donations to DSA
        max_dsa                 numeric(2,2) DEFAULT 0.4,
        iban                    varchar,
        -- if different from the paying member
        account_owner           varchar,
        account_address         varchar,
        -- validity
        granted_at              timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        revoked_at              timestamp WITH TIME ZONE DEFAULT NULL,
        notes                   varchar
);
CREATE INDEX idx_lastschrift_persona_id ON cde.lastschrift(persona_id);
GRANT SELECT, UPDATE ON cde.lastschrift TO cdb_member;
GRANT INSERT ON cde.lastschrift TO cdb_admin;
GRANT SELECT, UPDATE ON cde.lastschrift_id_seq TO cdb_admin;

CREATE TABLE cde.lastschrift_transaction
(
        id                      serial PRIMARY KEY,
        submitted_by            integer REFERENCES core.personas(id) NOT NULL,
        lastschrift_id          integer REFERENCES cde.lastschrift(id) NOT NULL,
        period_id               integer REFERENCES cde.org_period(id) NOT NULL,
        issued_at               timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        processed_at            timestamp WITH TIME ZONE DEFAULT NULL,
        -- positive for money we got and negative if bounced with fee
        tally                   numeric(7,2) DEFAULT NULL
);
CREATE INDEX idx_cde_lastschrift_transaction_lastschrift_id ON cde.lastschrift_transaction(lastschrift_id);
GRANT SELECT, UPDATE, INSERT ON cde.lastschrift_transaction TO cdb_admin;
GRANT SELECT, UPDATE ON cde.lastschrift_transaction_id_seq TO cdb_admin;

CREATE TABLE cde.finance_log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.CdeFinanceLogCodes
        code                    integer NOT NULL,
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        delta                   numeric(7,2),
        new_balance             numeric(7,2),
        additional_info         varchar,
        -- checksums
        -- number of members (SELECT COUNT(*) FROM core.personas WHERE status = ...)
        members                 integer NOT NULL,
        -- sum of all balances (SELECT SUM(balance) FROM cde.member_data)
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
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_cde_log_code ON cde.log(code);
CREATE INDEX idx_cde_log_persona_id ON cde.log(persona_id);
GRANT SELECT, INSERT ON cde.log TO cdb_persona;
GRANT SELECT, UPDATE ON cde.log_id_seq TO cdb_persona;

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
        country                 varchar
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
        iban                    varchar,
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
CREATE INDEX idx_courses_event_id ON event.courses(event_id);
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
        -- parental consent for minors (NULL if not (yet) given, e.g. non-minors)
        parental_agreement      boolean DEFAULT NULL,
        mixed_lodging           boolean,
        checkin                 timestamp WITH TIME ZONE DEFAULT NULL,
        -- foto consent (documentation, password protected gallery)
        foto_consent            boolean,

        -- only basic data should be defined here and everything else will
        -- be handeled via additional fields
        field_data              jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_registrations_persona_id ON event.registrations(persona_id);
CREATE INDEX idx_registrations_event_id ON event.registrations(event_id);
CREATE UNIQUE INDEX idx_registrations_constraint ON event.registrations(persona_id, event_id);
GRANT SELECT, INSERT, UPDATE ON event.registrations TO cdb_persona;
GRANT SELECT, UPDATE ON event.registrations_id_seq TO cdb_persona;

CREATE TABLE event.registration_parts (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id),
        part_id                 integer NOT NULL REFERENCES event.event_parts(id),
        course_id               integer REFERENCES event.courses(id) DEFAULT NULL,
        -- enum for status of this registration part
        -- see cdedb.database.constants.RegistrationPartStati
        status                  integer NOT NULL,
        lodgement_id            integer REFERENCES event.lodgements(id) DEFAULT NULL,
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
        input_size              integer,
        readonly                boolean
);
CREATE INDEX idx_questionnaire_rows_event_id ON event.questionnaire_rows(event_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_rows TO cdb_persona;
GRANT SELECT, UPDATE ON event.questionnaire_rows_id_seq TO cdb_persona;

CREATE TABLE event.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.EventLogCodes
        code                    integer NOT NULL,
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        event_id                integer REFERENCES event.events(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_event_log_code ON event.log(code);
CREATE INDEX idx_event_log_event_id ON event.log(event_id);
GRANT SELECT, INSERT ON event.log TO cdb_persona;
GRANT SELECT, UPDATE ON event.log_id_seq TO cdb_persona;

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
-- name not according to pattern to avoid collision
CREATE INDEX idx_past_courses_event_id ON past_event.courses(event_id);
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

CREATE TABLE past_event.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.PastEventLogCodes
        code                    integer NOT NULL,
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        event_id                integer REFERENCES past_event.events(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_past_event_log_code ON past_event.log(code);
CREATE INDEX idx_past_event_log_event_id ON past_event.log(event_id);
GRANT SELECT, INSERT ON past_event.log TO cdb_persona;
GRANT SELECT, UPDATE ON past_event.log_id_seq TO cdb_persona;

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
        -- after which time are you not allowed to sign up any more
        signup_end              timestamp WITH TIME ZONE NOT NULL,
        -- concluded assemblies get deactivated and all related secrets are
        -- purged
        is_active               boolean DEFAULT True,
        notes                   varchar
);
GRANT SELECT ON assembly.assemblies TO cdb_persona;
GRANT INSERT, UPDATE ON assembly.assemblies TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.assemblies_id_seq TO cdb_admin;

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
        -- Special option which means "options below this are not acceptable
        -- as outcome to me". For electing a person an alternative title may
        -- be "reopen nominations".
        --
        -- This is a bit complicated since a bar references a candidate
        -- references a ballot. But this seems to be the least ugly way to
        -- do it.
        bar                     integer DEFAULT NULL, -- REFERENCES assembly.candidates(id),
        -- number of submitted votes necessary to not trigger extension
        quorum                  integer NOT NULL DEFAULT 0,
        -- number of votes per ballot
        --
        -- NULL means arbitrary preference list
        -- n > 0 means, that the list must be of the form
        --       a_1=a_2=...=a_m>0>b_1=b_2=...=b_l
        --       with m non-negative and at most n, and where '0' is the
        --       bar's moniker (which must be non-NULL) or of the form
        --       0=a_1=a_2=...=a_m=b_1=b_2=...=b_l
        --       to signal an abstention.
        votes                   integer DEFAULT NULL,
        -- True after creation of the result summary file
        is_tallied              boolean DEFAULT False,
        notes                   varchar
);
CREATE INDEX idx_ballots_assembly_id ON assembly.ballots(assembly_id);
GRANT SELECT ON assembly.ballots TO cdb_persona;
GRANT UPDATE (extended, is_tallied) ON assembly.ballots TO cdb_persona;
GRANT INSERT, UPDATE, DELETE ON assembly.ballots TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.ballots_id_seq TO cdb_admin;

CREATE TABLE assembly.candidates (
        id                      serial PRIMARY KEY,
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        description             varchar NOT NULL,
        moniker                 varchar NOT NULL
);
CREATE UNIQUE INDEX idx_moniker_constraint ON assembly.candidates(ballot_id, moniker);
GRANT SELECT ON assembly.candidates TO cdb_persona;
GRANT INSERT, UPDATE, DELETE ON assembly.candidates TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.candidates_id_seq TO cdb_admin;

-- create previously impossible reference
ALTER TABLE assembly.ballots ADD FOREIGN KEY (bar) REFERENCES assembly.candidates(id);

CREATE TABLE assembly.attendees (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        assembly_id             integer NOT NULL REFERENCES assembly.assemblies(id),
        secret                  varchar
);
CREATE UNIQUE INDEX idx_attendee_constraint ON assembly.attendees(persona_id, assembly_id);
GRANT SELECT, INSERT, UPDATE ON assembly.attendees TO cdb_persona;
GRANT SELECT, UPDATE ON assembly.attendees_id_seq TO cdb_persona;

-- register who did already vote for what
CREATE TABLE assembly.voter_register (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id),
        has_voted               boolean DEFAULT False NOT NULL
);
CREATE UNIQUE INDEX idx_voter_constraint ON assembly.voter_register(persona_id, ballot_id);
GRANT SELECT, INSERT ON assembly.voter_register TO cdb_persona;
GRANT UPDATE (has_voted) ON assembly.voter_register TO cdb_persona;
GRANT DELETE ON assembly.voter_register TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.voter_register_id_seq TO cdb_persona;

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
GRANT SELECT, INSERT, UPDATE ON assembly.votes TO cdb_persona;
GRANT SELECT, UPDATE ON assembly.votes_id_seq TO cdb_persona;

CREATE TABLE assembly.attachments (
       id                       serial PRIMARY KEY,
       -- Each attachment may only be attached to one thing (either an
       -- assembly or a ballot).
       assembly_id              integer REFERENCES assembly.assemblies(id),
       ballot_id                integer REFERENCES assembly.ballots(id),
       title                    varchar NOT NULL,
       filename                 varchar NOT NULL
);
CREATE INDEX idx_attachments_assembly_id ON assembly.attachments(assembly_id);
CREATE INDEX idx_attachments_ballot_id ON assembly.attachments(ballot_id);
GRANT SELECT ON assembly.attachments TO cdb_persona;
GRANT INSERT, DELETE ON assembly.attachments TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.attachments_id_seq TO cdb_admin;

CREATE TABLE assembly.log (
        id                      bigserial PRIMARY KEY,
        ctime                   timestamp WITH TIME ZONE DEFAULT now(),
        -- see cdedb.database.constants.AssembyLogCodes
        code                    integer NOT NULL,
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        assembly_id             integer REFERENCES assembly.assemblies(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_assembly_log_code ON assembly.log(code);
CREATE INDEX idx_assembly_log_assembly_id ON assembly.log(assembly_id);
GRANT SELECT ON assembly.log TO cdb_admin;
GRANT INSERT ON assembly.log TO cdb_persona;
GRANT SELECT, UPDATE ON assembly.log_id_seq TO cdb_persona;

---
--- SCHEMA ml
---
DROP SCHEMA IF EXISTS ml;
CREATE SCHEMA ml;
GRANT USAGE ON SCHEMA ml TO cdb_persona;

CREATE TABLE ml.mailinglists (
        id                      serial PRIMARY KEY,
        title                   varchar NOT NULL,
        address                 varchar NOT NULL,
        description             varchar,
        -- see cdedb.database.constants.SubscriptionPolicy
        sub_policy              integer NOT NULL,
        -- see cdedb.database.constants.ModerationPolicy
        mod_policy              integer NOT NULL,
        -- see cdedb.database.constants.AttachmentPolicy
        attachment_policy      integer NOT NULL,
        -- list of PersonaStati
        audience                integer[] NOT NULL,
        subject_prefix          varchar,
        -- in kB
        maxsize                 integer,
        is_active               boolean NOT NULL,
        notes                   varchar,
        -- Define a list X as gateway for this list, that is everybody
        -- subscribed to X may subscribe to this list (only usefull with a
        -- restrictive subscription policy).
        --
        -- Main use case is the Aktivenforums list.
        gateway                 integer REFERENCES ml.mailinglists(id),
        -- event awareness
        -- event_id is not NULL if associated to an event
        event_id                integer REFERENCES event.events(id),
        -- which stati to address
        -- (cf. cdedb.database.constants.RegistrationPartStati)
        -- this may be empty, in which case this is an orga list
        registration_stati      integer[] NOT NULL,
        -- assembly awareness
        -- assembly_id is not NULL if associated to an assembly
        assembly_id             integer REFERENCES assembly.assemblies(id)
);
GRANT SELECT, UPDATE ON ml.mailinglists TO cdb_persona;
GRANT INSERT, DELETE ON ml.mailinglists TO cdb_admin;
GRANT SELECT, UPDATE ON ml.mailinglists_id_seq TO cdb_admin;

CREATE TABLE ml.subscription_states (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        address                 varchar,
        is_subscribed           boolean
);
CREATE UNIQUE INDEX idx_subscription_constraint ON ml.subscription_states(mailinglist_id, persona_id);
GRANT SELECT, INSERT, UPDATE ON ml.subscription_states TO cdb_persona;
GRANT DELETE ON ml.subscription_states TO cdb_admin;
GRANT SELECT, UPDATE ON ml.subscription_states_id_seq TO cdb_persona;

CREATE TABLE ml.subscription_requests (
        id                      serial PRIMARY KEY,
        mailinglist_id          integer NOT NULL REFERENCES ml.mailinglists(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON ml.subscription_requests TO cdb_persona;
GRANT SELECT, UPDATE ON ml.subscription_requests_id_seq TO cdb_persona;

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
        submitted_by            integer NOT NULL REFERENCES core.personas(id),
        mailinglist_id          integer REFERENCES ml.mailinglists(id),
        -- affected user
        persona_id              integer REFERENCES core.personas(id),
        additional_info         varchar
);
CREATE INDEX idx_ml_log_code ON ml.log(code);
CREATE INDEX idx_ml_log_mailinglist_id ON ml.log(mailinglist_id);
GRANT SELECT, INSERT ON ml.log TO cdb_persona;
GRANT DELETE ON ml.log TO cdb_admin;
GRANT SELECT, UPDATE ON ml.log_id_seq TO cdb_persona;
