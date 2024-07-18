-- Changes column name to be more accurate and easier to handle
ALTER TABLE core.genesis_cases RENAME COLUMN attachment TO attachment_hash;
