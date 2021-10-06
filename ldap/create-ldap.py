"""This creates an initial ldap server on the local maschine."""

import subprocess
import shutil
import jinja2
import pathlib

from cdedb.script import Script

# Setup
script = Script(check_system_user=False)

TEMPLATE_DIR = script.config["REPOSITORY_PATH"] / "ldap/templates"
OUTPUT_DIR = script.config["REPOSITORY_PATH"] / "ldap/output"

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)))


# Do the work
print("Update apt")
subprocess.run(["apt-get", "update"], stdout=subprocess.DEVNULL, check=True)

print("Install unixodbc and odbc-postgresql package")
subprocess.run(["apt-get", "install", "-y", "unixodbc", "odbc-postgresql"],
               stdout=subprocess.DEVNULL, check=True)

print("Add odbc.ini file")
# TODO what about the password, servername and port here?
shutil.copy("/cdedb2/related/auto-build/files/stage2/odbc.ini", "/etc/odbc.ini")

print("Compile debconf template and apply it")
template = ENV.get_template("slapd-debconf.tmpl")
out = template.render(secrets=script._secrets)
with open(OUTPUT_DIR / "slapd-debconf.txt", mode="w") as f:
    f.write(out)
subprocess.run(["debconf-set-selections", f"{OUTPUT_DIR / 'slapd-debconf.txt'}"],
               check=True)

print("Install slapd")
subprocess.run(["apt-get", "install", "-y", "slapd"], stdout=subprocess.DEVNULL,
               check=True)

print("Remove predefined mdb")
subprocess.run(["systemctl", "stop", "slapd"])
mdb_config = pathlib.Path("/etc/ldap/slapd.d/cn=config/olcDatabase={1}mdb.ldif")
ldap_dir = pathlib.Path("/var/lib/ldap")
if mdb_config.exists():
    mdb_config.unlink()
if ldap_dir.exists():
    shutil.rmtree(ldap_dir)
subprocess.run(["systemctl", "start", "slapd"])

print("\n\nCompile our custom ldap configuration template and apply it:\n")
template = ENV.get_template("config-ldap.tmpl")
# TODO set more values here dynamically form the config?
out = template.render(config=script.config, secrets=script._secrets)
ldif_file: pathlib.Path = OUTPUT_DIR / "config-ldap.ldif"
with open(ldif_file, mode="w") as f:
    f.write(out)
subprocess.run([f"ldapmodify -Y EXTERNAL -H ldapi:/// -f {ldif_file}"], check=True,
               shell=True)
