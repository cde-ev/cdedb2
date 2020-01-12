-- past_events
GRANT UPDATE ON past_event.institutions TO cdb_admin;
REVOKE UPDATE ON past_event.institutions FROM cdb_persona;

GRANT SELECT ON past_event.events to cdb_member;
GRANT UPDATE ON past_event.events TO cdb_admin;
REVOKE ALL PRIVILEGES ON past_event.events FROM cdb_persona;
GRANT SELECT (id, title, shortname, tempus) ON past_event.events TO cdb_persona;

GRANT SELECT, INSERT, DELETE ON past_event.log TO cdb_admin;
GRANT SELECT, UPDATE ON past_event.log_id_seq TO cdb_admin;
REVOKE ALL PRIVILEGES ON past_event.log FROM cdb_persona;
REVOKE ALL PRIVILEGES ON past_event.log_id_seq FROM cdb_persona;

-- cde
GRANT SELECT, INSERT ON cde.log TO cdb_admin;
GRANT SELECT, UPDATE ON cde.log_id_seq TO cdb_admin;

REVOKE ALL PRIVILEGES ON cde.log FROM cdb_persona;
REVOKE ALL PRIVILEGES ON cde.log_id_seq FROM cdb_persona;

-- event
GRANT INSERT, UPDATE, DELETE ON event.orgas TO cdb_admin;
GRANT SELECT, UPDATE ON event.orgas_id_seq TO cdb_admin;
REVOKE ALL PRIVILEGES ON event.orgas FROM cdb_persona;
REVOKE ALL PRIVILEGES ON event.orgas_id_seq FROM cdb_persona;

-- asembly
REVOKE ALL PRIVILEGES ON assembly.attendees FROM cdb_admin;
GRANT UPDATE (secret) ON assembly.attendees TO cdb_admin;

GRANT SELECT ON assembly.ballots TO cdb_member;
GRANT UPDATE (extended, is_tallied) ON assembly.ballots TO cdb_member;
GRANT SELECT ON assembly.candidates TO cdb_member;
GRANT SELECT, INSERT ON assembly.attendees TO cdb_member;
GRANT SELECT, UPDATE ON assembly.attendees_id_seq TO cdb_member;
GRANT SELECT, INSERT ON assembly.voter_register TO cdb_member;
GRANT UPDATE (has_voted) ON assembly.voter_register TO cdb_member;
GRANT DELETE ON assembly.voter_register TO cdb_admin;
GRANT SELECT, UPDATE ON assembly.voter_register_id_seq TO cdb_member;
GRANT SELECT, INSERT, UPDATE ON assembly.votes TO cdb_member;
GRANT SELECT, UPDATE ON assembly.votes_id_seq TO cdb_member;
GRANT SELECT ON assembly.attachments TO cdb_member;
GRANT INSERT ON assembly.log TO cdb_member;
GRANT SELECT, UPDATE ON assembly.log_id_seq TO cdb_member;

REVOKE ALL PRIVILEGES ON assembly.ballots FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.candidates FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.attendees FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.attendees_id_seq FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.voter_register FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.voter_register_id_seq FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.votes FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.votes_id_seq FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.attachments FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.log FROM cdb_persona;
REVOKE ALL PRIVILEGES ON assembly.log_id_seq FROM cdb_persona;
