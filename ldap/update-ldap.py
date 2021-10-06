"""This updates an existing ldap server on the local maschine."""

import subprocess
import shutil
import pathlib
import jinja2

from cdedb.script import Script

# Setup
script = Script(dbuser="cdb_admin", check_system_user=False)
core = script.make_backend("core", proxy=False)

TEMPLATE_DIR = script.config["REPOSITORY_PATH"] / "ldap/templates"
OUTPUT_DIR = script.config["REPOSITORY_PATH"] / "ldap/output"

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)))


# Do the work

print("Drop all existing and add new Duas in the database schema\n")
template = ENV.get_template("add-duas.tmpl")
out = template.render(encrypt=core.encrypt_password, secrets=script._secrets)
sql_file: pathlib.Path = OUTPUT_DIR / "add-duas.sql"
with open(sql_file, mode="w") as f:
    f.write(out)

with script._conn as conn:
    conn.set_session(autocommit=True)
    with conn.cursor() as curr:
        with sql_file.open() as f:
            sql_input = f.read()
        curr.execute(sql_input)

print("Remove existing cdedb-ldap\n")
subprocess.run(["systemctl", "stop", "slapd"])
sql_config = pathlib.Path("/etc/ldap/slapd.d/cn=config/olcDatabase={1}sql.ldif")
ldap_dir = pathlib.Path("/var/lib/ldap")
if sql_config.exists():
    sql_config.unlink()
if ldap_dir.exists():
    shutil.rmtree(ldap_dir)
subprocess.run(["systemctl", "start", "slapd"])

print("Compile our custom ldap database template and apply it:\n")
template = ENV.get_template("cdedb-ldap.tmpl")
# TODO set more values here dynamically form the config?
out = template.render(config=script.config, secrets=script._secrets)
ldif_file: pathlib.Path = OUTPUT_DIR / "cdedb-ldap.ldif"
with open(ldif_file, mode="w") as f:
    f.write(out)
subprocess.run([f"ldapmodify -Y EXTERNAL -H ldapi:/// -f {ldif_file}"], check=True,
               shell=True)
