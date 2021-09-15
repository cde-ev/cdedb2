CREATE UNIQUE INDEX lastschrift_unique_active ON cde.lastschrift (persona_id) WHERE revoked_at IS NOT NULL;
