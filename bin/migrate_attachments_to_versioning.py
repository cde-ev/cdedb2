#!/usr/bin/env python3

from cdedb.script import setup, make_backend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
from cdedb.common import unwrap, get_hash, now

# Configuration

# While this is True, make sure to not do any actual changes.
dry_run = True

rs = setup(persona_id=-1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")()

assembly = make_backend("assembly", proxy=False)


# Get to work
with Atomizer(rs):
    # First create the new table.
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
GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_admin;

GRANT UPDATE ON assembly.attachments TO cdb_admin;"""
    assembly.query_exec(rs, query, tuple())

    # Second retrieve the data for all current attachments.
    query = """SELECT * FROM assembly.attachments"""
    data = assembly.query_all(rs, query, tuple())

    # Third handle the current attachments.
    new_files = []
    if not data:
        print("No attachments found")
    for e in data:
        # Fourth try to find the original upload time from the log.
        ctime_query = ("SELECT ctime FROM assembly.log WHERE code = %s"
                       " AND change_note = %s ORDER BY ctime DESC LIMIT 1")
        ctime = assembly.query_one(
            rs, ctime_query, (const.AssemblyLogCodes.attachment_added,
                              e['title']))
        if ctime is None:
            ctime = now()
        else:
            ctime = unwrap(ctime)

        # Fifth try to find the attachment file.
        path = assembly.attachment_base_path / str(e['id'])
        new_path = assembly.attachment_base_path / (str(e['id']) + "_v1")
        if path.exists():
            with open(path, 'rb') as f:
                file_hash = get_hash(f.read())
            if new_path.exists():
                print(f"Destination file for {e['filename']} ({new_path})"
                      f" already exists.")
            else:
                new_files.append(new_path)
                if dry_run:
                    path.copy(new_path)
                    print(f"Found {e['filename']}.")
                else:
                    path.rename(new_path)
                    print(f"Renamed {e['filename']}.")
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
    if dry_run:
        for p in new_files:
            p.unlink()
        raise ValueError("Aborting dryrun without commiting changes.")
