from cdedb.script import Script, make_backend, setup

assembly = make_backend("assembly", proxy=False)

USER_ID = -1
DRYRUN = False

rs = setup(persona_id=USER_ID, dbuser="cdb",
           dbname="cdb_test",
           dbpassword="987654321098765432109876543210")()


with Script(rs, dry_run=DRYRUN):
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
    SELECT attachments.id, attachments.ballot_id, ballots.assembly_id
    FROM assembly.attachments
    LEFT OUTER JOIN assembly.ballots ON attachments.ballot_id = ballots.id
    WHERE attachments.assembly_id IS NULL"""
    ballot_data = assembly.query_all(rs, q, ())
    q = "INSERT INTO assembly.attachment_ballot_links" \
        " (attachment_id, ballot_id) VALUES (%s, %s)"
    for e in ballot_data:
        print(f"Inserting: <attachment id={e['id']}> -> <ballot id={e['ballot_id']}>.")
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
