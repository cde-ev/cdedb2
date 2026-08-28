BEGIN;
    UPDATE core.genesis_cases SET realm = 1 WHERE realm = 'cde';
    UPDATE core.genesis_cases SET realm = 2 WHERE realm = 'event';
    UPDATE core.genesis_cases SET realm = 4 WHERE realm = 'ml';
    ALTER TABLE core.genesis_cases ALTER COLUMN realm TYPE INTEGER USING realm::integer;
    ALTER TABLE core.genesis_cases ALTER COLUMN realm SET NOT NULL;
COMMIT;
