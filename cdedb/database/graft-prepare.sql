-- Create special users
CREATE USER cdb_old PASSWORD '12345678909876543210123456789';
CREATE USER cdb_graft PASSWORD '12345678909876543210123456789';
GRANT cdb TO cdb_graft;

-- Bestow special privileges
GRANT UPDATE ON core.log TO cdb_graft;
GRANT UPDATE ON core.changelog TO cdb_graft;
GRANT UPDATE ON cde.finance_log TO cdb_graft;
-- GRANT UPDATE ON past_event.log TO cdb_graft;
-- GRANT UPDATE ON event.log TO cdb_graft;
-- GRANT UPDATE ON assembly.log TO cdb_graft;
-- GRANT UPDATE ON ml.log TO cdb_graft;

-- Create database for old data
DROP DATABASE IF EXISTS cdedbxy;
CREATE DATABASE cdedbxy WITH OWNER = cdb_old TEMPLATE = template0 ENCODING = 'UTF8';
ALTER DATABASE cdedbxy SET datestyle TO 'ISO, YMD';

