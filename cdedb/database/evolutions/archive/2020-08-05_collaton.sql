-- Create a collation to filter strings properly.
-- Could also be hard-wired into the table rows, but setting manually with
-- each query seems to be more robust.
CREATE COLLATION "de-u-kn-true" (provider = icu, locale = 'de-u-kn-true');
