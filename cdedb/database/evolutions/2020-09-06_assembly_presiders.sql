-- Add table for assembly presiders.
-- Alter some access privigeles to allow modification by non-admins.
BEGIN;
    CREATE TABLE assembly.presiders (
        id              serial PRIMARY KEY,
        assembly_id     integer NOT NULL REFERENCES assembly.assemblies(id),
        persona_id      integer NOT NULL REFERENCES core.personas(id)
    );
    CREATE INDEX idx_assembly_presiders_assembly_id ON assembly.presiders(assembly_id);
    CREATE INDEX idx_assembly_presiders_persona_id ON assembly.presiders(persona_id);
    CREATE UNIQUE INDEX idx_assembly_presiders_constraint ON assembly.presiders(assembly_id, persona_id);
    GRANT SELECT ON assembly.presiders TO cdb_persona;
    GRANT INSERT, DELETE ON assembly.presiders TO cdb_admin;
    GRANT SELECT, UPDATE ON assembly.presiders_id_seq TO cdb_admin;

    GRANT UPDATE ON assembly.assemblies TO cdb_member;
    GRANT INSERT, UPDATE, DELETE ON assembly.ballots TO cdb_member;
    GRANT SELECT, UPDATE ON assembly.ballots_id_seq TO cdb_member;
    GRANT INSERT, UPDATE, DELETE ON assembly.candidates TO cdb_member;
    GRANT SELECT, UPDATE ON assembly.candidates_id_seq TO cdb_member;
    GRANT DELETE ON assembly.voter_register TO cdb_member;
    GRANT SELECT, UPDATE, INSERT, DELETE ON assembly.attachments TO cdb_member;
    GRANT SELECT, UPDATE ON assembly.attachments_id_seq TO cdb_member;
    GRANT SELECT, INSERT, DELETE, UPDATE on assembly.attachment_versions TO cdb_member;
    GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_member;
    GRANT SELECT on assembly.log TO cdb_member;
COMMIT;
