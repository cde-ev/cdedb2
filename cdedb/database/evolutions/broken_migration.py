from cdedb.script import make_backend, setup, Script

core = make_backend("core", proxy=False)
DRY_RUN = True

rs = setup(persona_id=-1, dbuser="cdb",
           dbname="cdb",
           dbpassword="987654321098765432109876543210")()

with Script(rs, dry_run=DRY_RUN):
    print("Renaming given_names to given_name.")
    core.query_exec(
        rs, "ALTER TABLE core.personas RENAME COLUMN given_names TO given_name", ())
