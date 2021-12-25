BEGIN;
    ----------
    -- core --
    ----------

    -- Add columns to session indexes.
    DROP INDEX core.idx_sessions_persona_id;
    CREATE INDEX sessions_persona_id_is_active_idx ON core.sessions(persona_id, is_active);
    DROP INDEX core.idx_sessions_is_active;
    CREATE INDEX sessions_is_active_atime_idx ON core.sessions(is_active, atime);

    -- Add persona_id + generation key to changelog.
    ALTER TABLE core.changelog ADD UNIQUE (persona_id, generation);

    -- Switch order of quota index to allow index scan when deleting all entries for a persona.
    DROP INDEX core.idx_quota_persona_id_qdate;
    ALTER TABLE core.quota ADD UNIQUE (persona_id, qdate);

    -- Add unique constraint to past event institutions.
    ALTER TABLE past_event.institutions ADD UNIQUE (shortname);

    ---------
    -- cde --
    ---------

    ----------------
    -- past_event --
    ----------------

    -- Add index for institutions of past events.
    CREATE INDEX past_events_institution_idx ON past_event.events(institution);

    -- Turn unique index into unique constraint for part event participants. This replaces the index on persona_id.
    DROP INDEX past_event.idx_participants_persona_id;
    ALTER TABLE past_event.participants ADD CONSTRAINT participants_persona_id_pevent_id_pcourse_id_key UNIQUE USING INDEX idx_participants_constraint;

    -----------
    -- event --
    -----------

    -- Add partial index for waitlist fields to event.event_parts.
    CREATE INDEX event_parts_partial_waitlist_field_idx ON event.event_parts(waitlist_field) WHERE waitlist_field IS NOT NULL;

    -- Turn unique field name index into constraint on event.field_definitions.
    ALTER TABLE event.field_definitions ADD CONSTRAINT field_definitions_event_id_field_name_key UNIQUE USING INDEX idx_field_definitions_event_id;

    -- Turn unique indexes into constraints on event.fee_modifiers.
    ALTER TABLE event.fee_modifiers ADD CONSTRAINT fee_modifiers_part_id_modifier_name_key UNIQUE USING INDEX idx_fee_modifiers_part_id;
    ALTER TABLE event.fee_modifiers ADD CONSTRAINT fee_modifiers_part_id_field_id_key UNIQUE USING INDEX idx_fee_modifiers_field_id;

    -- Add unqique constraint to event.course_segments.
    ALTER TABLE event.course_segments ADD UNIQUE (track_id, course_id);

    -- Remove superfluous index and rename constraint.
    DROP INDEX event.idx_orgas_persona_id;
    ALTER TABLE event.orgas RENAME CONSTRAINT event_unique_orgas TO orgas_persona_id_event_id_key;

    -- Replace existing unique index with unique constraints.
    DROP INDEX event.idx_course_choices_constraint;
    ALTER TABLE event.course_choices ADD UNIQUE (registration_id, track_id, course_id);
    ALTER TABLE event.course_choices ADD UNIQUE (registration_id, track_id, rank);
    -- Add additional index.
    CREATE INDEX ON event.course_choices(track_id, rank);

    -- Add additional unique constraint.
    ALTER TABLE event.registration_parts ADD UNIQUE (part_id, registration_id);

    -- Replace unqiue registrations index with unique constraint and drop duperfluous index.
    DROP INDEX event.idx_registrations_constraint;
    DROP INDEX event.idx_registrations_persona_id;
    ALTER TABLE event.registrations ADD UNIQUE (persona_id, event_id);

    -- Add unique constraint, drop superfluous index, add additional index.
    DROP INDEX event.idx_registration_tracks_registration_id;
    ALTER TABLE event.registration_tracks ADD UNIQUE (registration_id, track_id);
    CREATE INDEX ON event.registration_tracks(track_id);

    -- Drop superfluous index, rename constraint.
    DROP INDEX event.idx_stored_queries_event_id;
    ALTER TABLE event.stored_queries RENAME CONSTRAINT event_unique_query TO stored_queries_event_id_query_name_key;
    --------------
    -- assembly --
    --------------

    -- Replace existing unique index with unique constraint.
    DROP INDEX assembly.idx_attachment_ballot_links_constraint;
    ALTER TABLE assembly.attachment_ballot_links ADD UNIQUE (attachment_id, ballot_id);
    -- Create additional index.
    CREATE INDEX ON assembly.attachment_ballot_links(ballot_id);

    -- Replace existing unique index with unique constraint.
    DROP INDEX assembly.idx_attachment_version_constraint;
    ALTER TABLE assembly.attachment_versions ADD UNIQUE (attachment_id, version_nr);
    -- Drop superfluous index.
    DROP INDEX assembly.idx_attachment_versions_attachment_id;

    -- Replace existing unique index with unique constraint.
    DROP INDEX assembly.idx_attendee_constraint;
    ALTER TABLE assembly.attendees ADD UNIQUE (persona_id, assembly_id);
    -- Create additional index.
    CREATE INDEX ON assembly.attendees (assembly_id);

    -- Redefine unique constraint to switch column order and drop duplicate unique index.
    ALTER TABLE assembly.presiders DROP CONSTRAINT assembly_unique_presiders;
    DROP INDEX assembly.idx_assembly_presiders_constraint;
    ALTER TABLE assembly.presiders ADD UNIQUE (persona_id, assembly_id);
    -- Drop superfluous index and create addtional index.
    DROP INDEX assembly.idx_assembly_presiders_persona_id;
    CREATE INDEX ON assembly.presiders(assembly_id);

    -- Replace existing unique index with unique constraint.
    DROP INDEX assembly.idx_voter_constraint;
    ALTER TABLE assembly.voter_register ADD UNIQUE (persona_id, ballot_id);
    -- Create additional index.
    CREATE INDEX ON assembly.voter_register(ballot_id);

    --------
    -- ml --
    --------

    -- Rename existing unique constraint, drop superfluous index.
    DROP INDEX ml.idx_moderators_persona_id;
    ALTER TABLE ml.moderators RENAME CONSTRAINT mailinglist_unique_moderators TO moderators_persona_id_mailinglist_id_key;

    -- Replace existing unique index with unique constraint.
    DROP INDEX ml.idx_subscription_address_constraint;
    ALTER TABLE ml.subscription_addresses ADD UNIQUE (persona_id, mailinglist_id);
    -- Create additional index.
    CREATE INDEX ON ml.subscription_addresses(mailinglist_id);

    -- Replace existing unique index with unique constraint.
    DROP INDEX ml.idx_subscription_constraint;
    ALTER TABLE ml.subscription_states ADD UNIQUE (persona_id, mailinglist_id);
    -- Create additional index.
    CREATE INDEX ON ml.subscription_states(mailinglist_id);

    -- Redefine existing unique constraint to switch column order, drop superfluous index.
    DROP INDEX ml.idx_whitelist_mailinglist_id;
    ALTER TABLE ml.whitelist DROP CONSTRAINT mailinglist_unique_whitelist;
    ALTER TABLE ml.whitelist ADD UNIQUE (mailinglist_id, address);

    --------------------
    -- rename indexes --
    --------------------

    -- Give this one a more meaningful name.
    ALTER INDEX cde.lastschrift_unique_active RENAME TO lastschrift_partial_unique_active_idx;

    -- Switch index naming convention to postfix `_idx` instead of prefixing `idx_`.
    ALTER INDEX core.idx_personas_username RENAME TO personas_username_idx;
    ALTER INDEX core.idx_personas_is_cde_realm RENAME TO personas_is_cde_realm_idx;
    ALTER INDEX core.idx_personas_is_event_realm RENAME TO personas_is_event_realm_idx;
    ALTER INDEX core.idx_personas_is_ml_realm RENAME TO personas_is_ml_realm_idx;
    ALTER INDEX core.idx_personas_is_assembly_realm RENAME TO personas_is_assembly_realm_idx;
    ALTER INDEX core.idx_personas_is_member RENAME TO personas_is_member_idx;
    ALTER INDEX core.idx_personas_is_searchable RENAME TO personas_is_searchable_idx;
    ALTER INDEX core.idx_genesis_cases_case_status RENAME TO genesis_cases_case_status_idx;
    ALTER INDEX core.idx_privilege_changes_status RENAME TO privilege_changes_status_idx;
    ALTER INDEX core.idx_core_log_code RENAME TO core_log_code_idx;
    ALTER INDEX core.idx_core_log_persona_id RENAME TO core_log_persona_id_idx;
    ALTER INDEX core.idx_changelog_code RENAME TO changelog_code_idx;
    ALTER INDEX core.idx_changelog_persona_id RENAME TO changelog_persona_id_idx;
    ALTER INDEX cde.idx_lastschrift_persona_id RENAME TO lastschrift_persona_id_idx;
    ALTER INDEX cde.idx_cde_lastschrift_transactions_lastschrift_id RENAME TO cde_lastschrift_transactions_lastschrift_id_idx;
    ALTER INDEX cde.idx_cde_finance_log_code RENAME TO cde_finance_log_code_idx;
    ALTER INDEX cde.idx_cde_finance_log_persona_id RENAME TO cde_finance_log_persona_id_idx;
    ALTER INDEX cde.idx_cde_log_code RENAME TO cde_log_code_idx;
    ALTER INDEX cde.idx_cde_log_persona_id RENAME TO cde_log_persona_id_idx;
    ALTER INDEX past_event.idx_courses_pevent_id RENAME TO courses_pevent_id_idx;
    ALTER INDEX past_event.idx_participants_event_id RENAME TO participants_pevent_id_idx;
    ALTER INDEX past_event.idx_participants_course_id RENAME TO participants_pcourse_id_idx;
    ALTER INDEX past_event.idx_past_event_log_code RENAME TO past_event_log_code_idx;
    ALTER INDEX past_event.idx_past_event_log_event_id RENAME TO past_event_log_event_id_idx;
    ALTER INDEX event.idx_event_parts_event_id RENAME TO event_parts_event_id_idx;
    ALTER INDEX event.idx_course_tracks_part_id RENAME TO course_tracks_part_id_idx;
    ALTER INDEX event.idx_courses_event_id RENAME TO courses_event_id_idx;
    ALTER INDEX event.idx_course_segments_course_id RENAME TO course_segments_course_id_idx;
    ALTER INDEX event.idx_lodgements_event_id RENAME TO lodgements_event_id_idx;
    ALTER INDEX event.ids_lodgement_groups_event_id RENAME TO lodgement_groups_event_id_idx;
    ALTER INDEX event.idx_registrations_event_id RENAME TO registrations_event_id_idx;
    ALTER INDEX event.idx_registration_parts_registration_id RENAME TO registration_parts_registration_id_idx;
    ALTER INDEX event.idx_questionnaire_rows_event_id RENAME TO questionnaire_rows_event_id_idx;
    ALTER INDEX event.idx_orgas_event_id RENAME TO orgas_event_id_idx;
    ALTER INDEX event.idx_event_log_code RENAME TO event_log_code_idx;
    ALTER INDEX event.idx_event_log_event_id RENAME TO event_log_event_id_idx;
    ALTER INDEX assembly.idx_ballots_assembly_id RENAME TO ballots_assembly_id_idx;
    ALTER INDEX assembly.idx_votes_ballot_id RENAME TO votes_ballot_id_idx;
    ALTER INDEX assembly.idx_attachments_assembly_id RENAME TO attachments_assembly_id_idx;
    ALTER INDEX assembly.idx_assembly_log_code RENAME TO assembly_log_code_idx;
    ALTER INDEX assembly.idx_assembly_log_assembly_id RENAME TO assembly_log_assembly_id_idx;
    ALTER INDEX ml.idx_moderators_mailinglist_id RENAME TO moderators_mailinglist_id_idx;
    ALTER INDEX ml.idx_ml_log_code RENAME TO ml_log_code_idx;
    ALTER INDEX ml.idx_ml_log_mailinglist_id RENAME TO ml_log_mailinglist_id_idx;
COMMIT;
