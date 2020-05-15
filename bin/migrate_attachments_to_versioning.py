#!/usr/bin/env python3

import sys
sys.path.insert(0, "/cdedb2/")
from cdedb.script import setup, make_backend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
from cdedb.common import unwrap, get_hash

# Configuration

rs = setup(persona_id=-1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")()

assembly = make_backend("assembly", proxy=False)

with Atomizer(rs):
    query = \
    """CREATE TABLE assembly.attachment_versions (
    id              bigserial PRIMARY KEY,
    attachment_id   integer references assembly.attachments(id),
    version         integer NOT NULL DEFAULT 1,
    title           varchar,
    authors         varchar,
    filename        varchar,
    ctime           timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
    dtime           timestamp WITH TIME ZONE DEFAULT NULL,
    file_hash       varchar NOT NULL
);
CREATE INDEX idx_attachment_versions_attachment_id ON assembly.attachment_versions(attachment_id);
CREATE UNIQUE INDEX idx_attachment_version_constraint ON assembly.attachment_versions(attachment_id, version);
GRANT SELECT ON assembly.attachment_versions TO cdb_member;
GRANT INSERT, DELETE, UPDATE on assembly.attachment_versions TO cdb_admin;
GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_admin;"""
    assembly.query_exec(rs, query, tuple())

    query = """SELECT * FROM assembly.attachments"""
    data = assembly.query_all(rs, query, tuple())

    ctime_query = ("SELECT ctime FROM assembly.log WHERE code = %s"
                   " AND additional_info = %s")
    for e in data:
        ctime = unwrap(assembly.query_one(
            rs, ctime_query, (const.AssemblyLogCodes.attachment_added,
                              e['title'])))
        path = assembly.attachment_base_path / str(e['id'])
        if path.exists():
            with open(path, 'rb') as f:
                file_hash = get_hash(f.read())
            path.rename(assembly.attachment_base_path / (str(e['id']) + "_v1"))
        else:
            file_hash = ""
            print(f"File for attachment {e['id']} ({e['title']}) not found.'")

        vdata = {
            "attachment_id": e['id'],
            "version": 1,
            "title": e['title'],
            "authors": None,
            "filename": e['filename'],
            "ctime": ctime,
            "dtime": None,
            "file_hash": file_hash
        }
        assembly.sql_insert(rs, "assembly.attachment_versions", vdata)

    query = ("ALTER TABLE assembly.attachments"
             " DROP COLUMN title, DROP COLUMN filename")
    assembly.query_exec(rs, query, tuple())
