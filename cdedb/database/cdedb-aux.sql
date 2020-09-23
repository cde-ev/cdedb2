-- This file specifies auxiliary object local to a database
-- e.g. extensions and collations

DROP EXTENSION IF EXISTS pg_trgm;
CREATE EXTENSION pg_trgm;
DROP COLLATION IF EXISTS "de-u-kn-true";
CREATE COLLATION "de-u-kn-true" (provider = icu, locale = 'de-u-kn-true');
