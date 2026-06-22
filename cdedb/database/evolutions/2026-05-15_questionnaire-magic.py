#! /usr/bin/env python3

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.script import Script

s = Script(dbuser='cdb')
rs = s.rs()

event_backend = s.make_event_backend(proxy=False)

table_query = """
    CREATE TABLE event.questionnaire_text_rows (
            id                      bigserial PRIMARY KEY,
            event_id                integer NOT NULL REFERENCES event.events(id),
            -- The specific qeustionnaire variant where this row will be used. See cdedb.constants.QuestionnaireUsages.
            kind                    integer NOT NULL,
            -- The position at which this element is shown in the questionnaire.
            pos                     integer NOT NULL,
            role                    integer NOT NULL,
            -- A customized heading for this element.
            title                   varchar,
            -- Additional formatted text that is displayed below the heading if any.
            text                    varchar
    );
    CREATE INDEX questionnaire_text_rows_event_id_kind_idx ON event.questionnaire_text_rows(event_id, kind);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_text_rows TO cdb_persona;
    GRANT SELECT, UPDATE ON event.questionnaire_text_rows_id_seq TO cdb_persona;

    CREATE TABLE event.questionnaire_field_rows (
            id                      bigserial PRIMARY KEY,
            event_id                integer NOT NULL REFERENCES event.events(id),
            -- The specific qeustionnaire variant where this row will be used. See cdedb.constants.QuestionnaireUsages.
            kind                    integer NOT NULL,
            -- The position at which this element is shown in the questionnaire.
            pos                     integer NOT NULL,
            role                    integer NOT NULL,
            -- A customized label for this element.
            label                   varchar,
            -- Additional information that is displayed below the field input.
            info                    varchar,
            -- These fields determine what variant of content is rendered via this row.
            -- Only one of these may be set. If none are set this row simply displays a heading and some text.
            -- If field id is set, display input for the linked field.
            field_id                integer REFERENCES event.field_definitions(id),
            -- If set, the value for the linked field can no longer be changed.
            readonly                boolean NOT NULL DEFAULT FALSE,
            -- If set, a value that is prefilled into the form if there is no stored value.
            default_value           varchar
    );
    CREATE INDEX questionnaire_field_rows_event_id_kind_idx ON event.questionnaire_field_rows(event_id, kind);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_field_rows TO cdb_persona;
    GRANT SELECT, UPDATE ON event.questionnaire_field_rows_id_seq TO cdb_persona;

    CREATE TABLE event.questionnaire_magic_rows (
            id                      bigserial PRIMARY KEY,
            event_id                integer NOT NULL REFERENCES event.events(id),
            -- The specific qeustionnaire variant where this row will be used. See cdedb.constants.QuestionnaireUsages.
            kind                    integer NOT NULL,
            -- The position at which this element is shown in the questionnaire.
            pos                     integer NOT NULL,
            -- The role that this magic row serves. See cdedb.constants.QuestionnaireRowRole.
            role                    integer NOT NULL
    );
    CREATE INDEX questionnaire_magic_rows_event_id_kind_idx ON event.questionnaire_magic_rows(event_id, kind);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.questionnaire_magic_rows TO cdb_persona;
    GRANT SELECT, UPDATE ON event.questionnaire_magic_rows_id_seq TO cdb_persona;
"""

migration_query_text = """
    INSERT INTO event.questionnaire_text_rows (event_id, kind, pos, role, title, text) (
        SELECT
            event_id, kind, pos, 1, title, info
        FROM
            event.questionnaire_rows
        WHERE
            field_id IS NULL
    );
"""

migration_query_fields = """
    INSERT INTO event.questionnaire_field_rows (event_id, kind, pos, role, field_id, label, info, default_value) (
        SELECT
            event_id, kind, pos, 5, field_id, title, info, default_value
        FROM
            event.questionnaire_rows
        WHERE
            field_id IS NOT NULL
    );
"""


with s:
    print("Creating tables...")

    event_backend.query_exec(rs, table_query, ())

    print("Migrating existing text and field rows...")

    num = event_backend.query_exec(rs, migration_query_text, ())
    print(f"Migrated {num} text rows.")

    num = event_backend.query_exec(rs, migration_query_fields, ())
    print(f"Migrated {num} field rows.")

    print("Inserting default magic rows for every event...")
    print()

    for event_id, event in sorted(
        event_backend.get_events(rs, event_backend.list_events(rs)).items()
    ):
        print(f"{event.title}", end=" ", flush=True)
        if not event.tracks:
            print("(no courses)", end=" ", flush=True)

        all_questionnaires = event_backend.get_all_questionnaires(rs, event.id)

        new_additional_questionnaire = []
        for row in all_questionnaires[const.QuestionnaireUsages.additional].as_dicts():
            if row['role'] in {
                const.QuestionnaireRowRole.text,
                const.QuestionnaireRowRole.heading,
            }:
                if row.get('title'):
                    new_additional_questionnaire.append({
                        'role': const.QuestionnaireRowRole.heading,
                        'title': row['title'],
                    })
                if row.get('text'):
                    new_additional_questionnaire.append({
                        'role': const.QuestionnaireRowRole.text,
                        'text': row['text'],
                    })
            else:
                new_additional_questionnaire.append(row)

        event_backend.set_questionnaire(
            rs,
            event.id,
            const.QuestionnaireUsages.additional,
            new_additional_questionnaire,
        )

        default_questionnaire = models.questionnaire.make_default_questionnaire(event)[
            const.QuestionnaireUsages.registration
        ]
        new_reg_questionnaire = []
        for row in (
            default_questionnaire[:-1]
            + all_questionnaires[const.QuestionnaireUsages.registration].as_dicts()
            + default_questionnaire[-1:]
        ):
            if row['role'] in {
                const.QuestionnaireRowRole.text,
                const.QuestionnaireRowRole.heading,
            }:
                if row.get('title'):
                    new_reg_questionnaire.append({
                        'role': const.QuestionnaireRowRole.heading,
                        'title': row['title'],
                    })
                if row.get('text'):
                    new_reg_questionnaire.append({
                        'role': const.QuestionnaireRowRole.text,
                        'text': row['text'],
                    })
            else:
                new_reg_questionnaire.append(row)

        event_backend.set_questionnaire(
            rs, event.id, const.QuestionnaireUsages.registration, new_reg_questionnaire
        )

        print("done")
