-- List of tables
SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema != 'pg_catalog' AND table_schema != 'information_schema' ORDER BY table_schema, table_name;
-- List of columns
SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default, numeric_precision, numeric_scale FROM information_schema.columns WHERE table_schema != 'pg_catalog' AND table_schema != 'information_schema' ORDER BY table_schema, table_name, column_name;
-- List of table privileges
SELECT table_schema, table_name, privilege_type, grantee FROM information_schema.table_privileges WHERE grantor = 'cdb' AND grantee != 'cdb' ORDER BY table_schema, table_name, privilege_type;
-- List of column privileges
SELECT table_schema, table_name, column_name, privilege_type, grantee FROM information_schema.column_privileges WHERE grantor = 'cdb' AND grantee != 'cdb' ORDER BY table_schema, table_name, column_name, privilege_type;
-- List of general usage privileges
SELECT object_schema, object_name, object_type, grantee FROM information_schema.usage_privileges WHERE grantor = 'cdb' ORDER BY object_schema, object_name;
-- List of table constraints
-- SELECT table_shema, table_name, constraint_name, constraint_type FROM information_schema.table_constraints ORDER BY table_schema, table_name , constraint_name;
-- List of indexes
SELECT schemaname, tablename, indexname, indexdef FROM pg_catalog.pg_indexes ORDER BY schemaname, tablename, indexname;