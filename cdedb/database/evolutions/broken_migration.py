from cdedb.script import Script, make_backend, setup

rs = setup(persona_id=-1, dbuser="cdb", dbpassword="987654321098765432109876543210",
           dbname="cdb_test")()

core = make_backend("core", proxy=False)

with Script(rs, dry_run=False):
    core.query_exec(rs, "ALTER TABLE core.personas RENAME family_name TO last_name", ())
    core.query_all(rs, "SELECT last_name FROM core.personas", ())
