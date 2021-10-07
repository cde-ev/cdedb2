"""This updates an existing ldap server on the local maschine."""

import subprocess
import shutil
import pathlib

from util import LdapScript

# Setup
script = LdapScript(dbuser="cdb_admin")

# Do the work
print("Compile add-duas.sql file")
sql_path = script.render_save("add-duas.sql", encrypt=script.encrypt_password,
                              secrets=script._secrets)

print("Compile cdedb-ldap.ldif file")
# TODO set more values here dynamically form the config?
ldif_path = script.render_save("cdedb-ldap.ldif", config=script.config,
                               secrets=script._secrets)

if script.dry_run:
    print("Skip during dry run        -- Drop all existing and add new duas.")
    print("Skip during dry run        -- Remove existing cdedb-ldap.")
    print("Skip during dry run        -- Apply cdedb-ldap.ldif.")
else:
    if script.config["CDEDB_DEV"] or script.config["CDEDB_TEST"]:
        print("Skip in test and dev       -- Drop all existing and add new duas.")
        print("                              Are included in sample-data.")
    else:
        print("Drop all existing and add new duas.")
        with script._conn as conn:
            conn.set_session(autocommit=True)
            with conn.cursor() as curr:
                with sql_path.open() as f:
                    sql_input = f.read()
                curr.execute(sql_input)

    print("Remove existing cdedb-ldap")
    subprocess.run(["systemctl", "stop", "slapd"])
    sql_config = pathlib.Path("/etc/ldap/slapd.d/cn=config/olcDatabase={1}sql.ldif")
    ldap_dir = pathlib.Path("/var/lib/ldap")
    if sql_config.exists():
        sql_config.unlink()
    if ldap_dir.exists():
        shutil.rmtree(ldap_dir)
    subprocess.run(["systemctl", "start", "slapd"])

    print("\nApply cdedb-ldap.ldif:")
    subprocess.run([f"ldapmodify -Y EXTERNAL -H ldapi:/// -f {ldif_path}"], check=True,
                   shell=True, stderr=subprocess.DEVNULL)
