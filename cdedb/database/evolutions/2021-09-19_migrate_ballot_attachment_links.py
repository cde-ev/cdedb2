from cdedb.script import Script

# Setup

script = Script(dbuser="cdb")
rs = script.rs()
assembly = script.make_backend("assembly", proxy=False)

with script:
    print("Adding NOT NULL constraint to `assembly.attachment_versions.attachment_id`.")
    assembly.query_exec(rs, "ALTER TABLE assembly.attachment_versions ALTER COLUMN"
                            " attachment_id SET NOT NULL", ())

    print("Renaming column `version` to `version_nr`.")
    assembly.query_exec(rs, "ALTER TABLE assembly.attachment_versions RENAME COLUMN"
                            " version TO version_nr", ())

    print("Create new ballot links table.")
    q = """
CREATE TABLE assembly.attachment_ballot_links (
        id                      bigserial PRIMARY KEY,
        attachment_id           integer NOT NULL REFERENCES assembly.attachments(id),
        ballot_id               integer NOT NULL REFERENCES assembly.ballots(id)
);
CREATE UNIQUE INDEX idx_attachment_ballot_links_constraint
    ON assembly.attachment_ballot_links(attachment_id, ballot_id);
GRANT SELECT, INSERT, DELETE, UPDATE ON assembly.attachment_ballot_links TO cdb_member;
GRANT SELECT, UPDATE ON assembly.attachment_ballot_links_id_seq TO cdb_member;"""
    assembly.query_exec(rs, q, ())

    print("Retrieve old ballot links:")
    q = """
    SELECT attachments.id, attachments.ballot_id,
        attachments.assembly_id AS old_assembly_id, ballots.assembly_id
    FROM assembly.attachments
    LEFT OUTER JOIN assembly.ballots ON attachments.ballot_id = ballots.id"""
    ballot_data = assembly.query_all(rs, q, ())
    q = "INSERT INTO assembly.attachment_ballot_links" \
        " (attachment_id, ballot_id) VALUES (%s, %s)"
    for e in ballot_data:
        if e['old_assembly_id']:
            if e['ballot_id']:
                raise ValueError(
                    f"Attachment ({e['id']}) was linked to both assembly and ballot!")
            print(f"Keeping: <attachment id={e['id']}> ->"
                  f" <assembly id={e['old_assembly_id']}>")

        if e['ballot_id']:
            print(f"Inserting: <attachment id={e['id']}> ->"
                  f" <ballot id={e['ballot_id']}>.")
            assembly.query_exec(rs, q, (e['id'], e['ballot_id']))

            print(f"Inserting: <attachment id={e['id']}> ->"
                  f" <assembly id={e['assembly_id']}>.")
            assembly.query_exec(
                rs, "UPDATE assembly.attachments SET assembly_id = %s WHERE id = %s",
                (e['assembly_id'], e['id']))

    print("Dropping column `assembly.attachments.ballot_id`.")
    assembly.query_exec(
        rs, "ALTER TABLE assembly.attachments DROP COLUMN ballot_id", ())
    print("Adding NOT NULL constraint on `assembly.sttachments.assembly_id`.")
    assembly.query_exec(
        rs, "ALTER TABLE assembly.attachments ALTER COLUMN assembly_id SET NOT NULL",
        ())
