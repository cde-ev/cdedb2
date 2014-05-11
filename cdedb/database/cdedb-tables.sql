-- This file specifies the tables in the database and has the users in
-- cdedb-users.sql as prerequisite.

-- TODO: grant priveleges
-- TODO: create indices
-- TODO: think about ctime/mtime hack for evreg
-- TODO: tables: quota, lastschrift_*, finance_log, mailinglist_*, assembly_*, cdefiles_*
-- TODO: evreg-tables: busses, mitnahme-support
-- TODO: NOT NULL?? use it or leave it?

-- create the database
DROP DATABASE IF EXISTS :cdb_database_name;
CREATE DATABASE :cdb_database_name WITH OWNER = cdb TEMPLATE = template0 ENCODING = 'UTF8';

ALTER DATABASE :cdb_database_name SET datestyle TO 'ISO, YMD';

\connect :cdb_database_name cdb

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
        username                varchar NOT NULL UNIQUE,
        -- password hash as specified by passlib.hash.sha512_crypt
        -- not logged in changelog
        password_hash           varchar NOT NULL,
        -- name to use when adressing user/"Rufname"
        display_name            varchar NOT NULL,
        -- inactive accounts may not log in
        is_active               boolean NOT NULL DEFAULT True,
        -- nature of this entry
        -- 0 ... searchable CdE member
        -- 1 ... non-searchable CdE member
        -- 2 ... former CdE member
        -- 10 ... archived former CdE member
        -- 20 ... external event user
        -- 30 ... external assembly user
        --
        -- the different statuses have different additional data attached
        -- 0/1/2 ... a matching entry cde.member_data
        -- 10 ...  a matching entry cde.member_data which is mostly NULL (thus
        --         fulfilling fewer constraints and most queries will need to
        --         filter for status in (0, 1))
        --         archived members may not login, thus is_active must be False
        -- 20 ... a matching entry event.user_data
        -- 30 ... a matching entry assembly.user_data
        --
        -- Searchability (see statusses 0 and 1) means the user has given
        -- (at any point in time) permission for his data to be accessible
        -- to other users. This permission is revoked upon leaving the CdE
        -- and has to be granted again in case of reentry.
        status                  integer NOT NULL,
        -- bitmask of possible privileges
        -- if db_privileges == 0 no privileges are granted
        -- 1 ... global admin privileges (implies all other privileges granted here)
        -- 2 ... core_admin
        -- 4 ... cde_admin
        -- 8 ... event_admin
        -- 16 ... ml_admin
        -- 32 ... assembly_admin
        -- 64 ... files_admin
        -- 128 ... i25p_admin
        db_privileges           integer NOT NULL DEFAULT 0
);
CREATE INDEX idx_personas_status ON core.personas(status);
GRANT SELECT ON core.personas TO cdb_anonymous;
GRANT UPDATE (username, password_hash, display_name) ON core.personas TO cdb_persona;
GRANT INSERT, UPDATE ON core.personas TO cdb_core_admin;
GRANT SELECT, UPDATE ON core.personas_id_seq TO cdb_core_admin;

CREATE TABLE core.persona_creation_challenges (
        id                       bigserial PRIMARY KEY,
        -- creation time
        ctime                    timestamp with time zone NOT NULL DEFAULT now(),
        email                    varchar NOT NULL,
        -- status the persona is going to have initially
        persona_status           integer NOT NULL,
        -- user-supplied comment (short justification of request)
        -- may be amended during review
        notes                    varchar,
        -- A verification link is sent to the email address; upon
        -- verification an admittance email is sent to the responsible team
        --
        -- To prevent spam and enhance security every persona creation needs
        -- to be approved by moderators/administrators; upon addmittance an
        -- email is sent, that persona creation can proceed
        --
        -- enum tracking the progress
        -- 0 ... created, email unconfirmed
        -- 1 ... email confirmed, awaiting review
        -- 2 ... reviewed and approved, awaiting persona creation
        -- 3 ... finished (persona created, challenge archived)
        -- 10 ... reviewed and rejected (also a final state)
        challenge_status         integer NOT NULL DEFAULT 0
);
GRANT SELECT, INSERT ON core.persona_creation_challenges To cdb_anonymous;
GRANT SELECT, UPDATE ON core.persona_creation_challenges_id_seq TO cdb_anonymous;
GRANT UPDATE (challenge_status) ON core.persona_creation_challenges TO cdb_anonymous;
GRANT UPDATE ON core.persona_creation_challenges TO cdb_core_admin;

-- this table serves as access log, so entries are never deleted
CREATE TABLE core.sessions (
        id                      bigserial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        is_active               boolean NOT NULL DEFAULT True,
        -- login time
        ctime                   timestamp with time zone NOT NULL DEFAULT now(),
        -- last access time
        atime                   timestamp with time zone NOT NULL DEFAULT now(),
        ip                      varchar,
        -- FIXME should we hash this?
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
-- TODO index, grant

---
--- SCHEMA cde
---
DROP SCHEMA IF EXISTS cde;
CREATE SCHEMA cde;
GRANT USAGE ON SCHEMA cde TO cdb_member;

-- FIXME think about splitting off adresses
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
        -- 0 ... female
        -- 1 ... male
        -- 2 ... unknown
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
        -- not logged in changelog
        notes                   varchar,

        -- here is the cut for event.user_data

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
        balance                 numeric(8,2) NOT NULL DEFAULT 0,
	-- True if user decided (positive or negative) on searchability
	decided_search		boolean DEFAULT FALSE,
        -- file name of image
        -- not logged in chengelog
        foto                    varchar DEFAULT NULL,

        -- internal field for fulltext search
        -- this contains a concatenation of all other fields
        -- thus enabling fulltext search as substring search on this field
        -- it is automatically updated when a change is commited
        fulltext                varchar
);
GRANT SELECT ON cde.member_data TO cdb_member;
GRANT UPDATE ON cde.member_data TO cdb_member; -- TODO once the changelog functionality is implemented this has to be revisited
GRANT INSERT, UPDATE ON cde.member_data TO cdb_cde_admin;

-- log all changes made to the personal data of members (require approval)
--
-- username changes are special (i.e. no approval, but verification; may not
-- change at the same time as other things)
CREATE TABLE cde.changelog (
        id                      bigserial PRIMARY KEY,
        --
        -- information about the change
        --
        submitted_by            integer REFERENCES core.personas(id),
        reviewed_by             integer REFERENCES core.personas(id) DEFAULT NULL,
        cdate                   timestamp with time zone NOT NULL DEFAULT now(),
        -- enum for progress of change
        -- 0 ... review pending
        -- 1 ... commited
        -- 10 ... superseded
        -- 11 ... nacked
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
        -- now those frome member_data
        family_name             varchar NOT NULL,
        given_names             varchar NOT NULL,
        title                   varchar DEFAULT NULL,
        name_supplement         varchar DEFAULT NULL,
        gender                  integer NOT NULL,
        birthday                date NOT NULL,
        telephone               varchar,
        mobile                  varchar,
        address_supplement      varchar,
        address                 varchar,
        postal_code             varchar,
        location                varchar,
        country                 varchar,
        birth_name              varchar DEFAULT NULL,
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
        balance                 numeric(8,2) NOT NULL DEFAULT 0,
	decided_search		boolean
);
CREATE INDEX idx_changelog_change_status ON cde.changelog(change_status);
GRANT INSERT ON cde.changelog TO cdb_member;
GRANT SELECT, UPDATE ON cde.changelog_id_seq TO cdb_member;
GRANT UPDATE (reviewed_by, change_status) ON cde.changelog TO cdb_cde_admin;

CREATE TABLE cde.semester (
        -- The historically recommended method to determine the semester
        -- is which exPuls is the _next_ one to be sent out.
        -- normally, a semester would end on -07-01 or -01-01 of a year.
        -- This means:  end_year = 1993 + int(next_expuls / 2)
        --              end_month = 1 + int(next_expuls % 2)*6
        --              end_day = 1
        next_expuls             integer PRIMARY KEY,
        -- has the billing mail already been sent? If so, up to which ID (it
        -- is done incrementally)
        billingmail             integer REFERENCES core.personas(id),
        billingmail_done        timestamp with time zone DEFAULT NULL,
        -- have those who haven't paid been ejected? If so, up to which ID
        -- (it is done incrementally)
        ejection                integer REFERENCES core.personas(id),
        ejection_done           timestamp with time zone DEFAULT NULL,
        -- has the address check mail already been sent? If so, up to which
        -- ID (it is done incrementally)
        addrcheckmail           integer REFERENCES core.personas(id),
        addrcheck_done          timestamp with time zone DEFAULT NULL,
        -- has the balance already been adjusted? If so, up to which ID?
        -- (it is done incrementally)
        balanceupdate           integer REFERENCES core.personas(id),
        balance_done            timestamp with time zone DEFAULT NULL,
        -- has the member journal been sent?
        sendjournal_done        timestamp with time zone DEFAULT NULL

-- TODO review this whole piece and decide what is usefull
);

---
--- SCHEMA event
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
        -- 0 ... female
        -- 1 ... male
        -- 2 ... unknown
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
GRANT INSERT ON event.user_data TO cdb_event_admin;

CREATE TABLE event.event_type (
        id                      serial PRIMARY KEY,
        -- Schueler/Junior/Pfingst/Sommer/WinterAkademie, Segeln, NMUN, ...
        moniker                 varchar,
        -- DSA,  JGW, DJA, CdE, BASF, ...
        organizer               varchar
);
CREATE INDEX idx_event_type_organizer ON event.event_type(organizer);

CREATE TABLE event.events (
        id                      serial PRIMARY KEY,
        shortname               varchar NOT NULL UNIQUE,
        longname                varchar NOT NULL UNIQUE,
        type_id                 integer NOT NULL REFERENCES event.event_type(id),
        -- True if coordinated via CdEDB
        -- if so, there has to exist a corresponding entry in event.event_data
        is_db                   boolean NOT NULL DEFAULT False
);
CREATE INDEX idx_events_type_id ON event.events(type_id);
CREATE INDEX idx_events_is_db ON event.events(is_db);

CREATE TABLE event.event_data (
        event_id                integer PRIMARY KEY REFERENCES event.events(id),
        registration_start      date NOT NULL,
        -- official end of registration
        registration_soft_limit date NOT NULL,
        -- actual end of registration, in between participants are automatically warned about registering late
        registration_hard_limit date NOT NULL,
        has_courses             boolean NOT NULL,
        notes                   varchar,
        orga_email              varchar NOT NULL,
        description             varchar

-- TODO u18url, zusatzinfo, writeprotect
);

CREATE TABLE event.event_parts (
        id                      serial PRIMARY KEY,
        event_id                integer REFERENCES event.events(id),
        -- we implicitly assume, that parts are non-overlapping
        part_begin              date NOT NULL,
        part_end                date NOT NULL,
        -- fees are cummulative
        fee                     numeric(8,2) NOT NULL
);

CREATE TABLE event.courses (
        id                      serial PRIMARY KEY,
        event_id                integer NOT NULL REFERENCES event.events(id),
        nr                      integer,
        title                   varchar NOT NULL
        -- if this course belongs to an event with is_db == True then there
        -- has to be a corresponding entry in event.course_data
);
CREATE INDEX idx_courses_event_id ON event.courses(event_id);
CREATE INDEX idx_courses_nr ON event.courses(nr);

CREATE TABLE event.course_data (
        course_id               integer PRIMARY KEY REFERENCES event.courses(id),
        shortname               varchar,
        -- string containing all course-instructors
        instructors             varchar,
        description             varchar,
        notes                   varchar
);

CREATE TABLE event.course_parts (
        id                      serial PRIMARY KEY,
        course_id               integer REFERENCES event.courses(id),
        part_id                 integer REFERENCES event.event_parts(id)
);

CREATE TABLE event.orgas (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id)
);
CREATE INDEX idx_orgas_persona_id ON event.orgas(persona_id);
CREATE INDEX idx_orgas_event_id ON event.orgas(event_id);

-- this table captures participation of concluded events and is not used for
-- coordinating current events (for the latter look at event.registrations)
CREATE TABLE event.participants (
        id                       serial PRIMARY KEY,
        persona_id               integer NOT NULL REFERENCES core.personas(id),
        event_id                 integer NOT NULL REFERENCES event.events(id),
        course_id                integer REFERENCES event.courses(id),
        is_instructor            boolean NOT NULL,
        is_orga                  boolean NOT NULL -- TODO delete this?
);
CREATE INDEX idx_participants_persona_id ON event.participants(persona_id);
CREATE INDEX idx_participants_event_id ON event.participants(event_id);
CREATE INDEX idx_participants_course_id ON event.participants(course_id);

-- this table for for organizing a current or future event, participation of
-- past events is tracked via event.participants
CREATE TABLE event.registrations (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id),

        orga_notes              varchar,
        payment                 date,
        -- parental consent for minors (NULL if not (yet) given, e.g. non-minors)
        parental_agreement      date,
        checkin                 timestamp with time zone,
        -- true if participant would take a reserve space in a lodgment
        would_overfill          boolean DEFAULT False,
        -- foto consent (documentation, password protected gallery)
        foto_consent            boolean DEFAULT NULL

        -- only the basic fields should be defined and everything else will
        -- be handeled via ext_fields

        -- TODO departure_bus_id
);
CREATE INDEX idx_registrations_persona_id ON event.registrations(persona_id);
CREATE INDEX idx_registrations_event_id ON event.registrations(event_id);
CREATE INDEX idx_registrations_status ON event.registrations(status);
CREATE INDEX idx_registrations_payment ON event.registrations(payment);

CREATE TABLE event.registration_parts (
        id                      serial PRIMARY KEY,
        registration_id         integer REFERENCES event.registrations(id),
        part_id                 integer REFERENCES event.part_data(id),
        -- enum for status of this registration part
        -- -1 ... not applied
        -- 0 ... applied
        -- 1 ... admitted
        -- 2 ... on hold (waiting list)
        -- 3 ... guest
        -- 4 ... canceled
        -- 5 ... rejected
        status                  integer NOT NULL DEFAULT 0,

        logdment_id             integer REFERENCES event.lodgments(id)
        -- TODO course choices, course instructor
);

CREATE TABLE event.lodgments (
        id                       serial PRIMARY KEY,
        event_id                 integer REFERENCES event.events(id),
        title                    varchar,
        capacity                 integer,
        -- number of people which can be accommodated with reduced comfort
        reserve                  integer DEFAULT 0,
        notes                    varchar
);

CREATE TABLE event.extfield_definitions (
        id                      serial PRIMARY KEY,
        event_id                integer REFERENCES event.events(id),
        field_name              varchar,
        -- anything understood by cdedb.validation and serializable as string
        kind                    varchar
);

CREATE TABLE event.extfield_data (
        id                      serial PRIMARY KEY,
        registration_id         integer REFERENCES event.registrations(id),
        field_name              varchar,
        field_value             varchar
);

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

-- TODO implement

---
--- SCHEMA files
---
DROP SCHEMA IF EXISTS files;
CREATE SCHEMA files;

-- TODO implement

---
--- SCHEMA i25p
---
DROP SCHEMA IF EXISTS i25p;
CREATE SCHEMA i25p;

-- TODO implement
