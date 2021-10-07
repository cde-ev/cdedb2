"""This creates an initial ldap server on the local maschine."""

import subprocess
import shutil
import jinja2
import pathlib

from util import Script

# Setup
script = Script(check_system_user=False)

TEMPLATE_DIR = script.config["REPOSITORY_PATH"] / "ldap/templates"
OUTPUT_DIR = script.config["REPOSITORY_PATH"] / "ldap/output"

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)))


def render_save(name: str, **kwargs) -> pathlib.Path:
    basename, ending = name.split(".")
    template = ENV.get_template(f"{basename}.tmpl")
    out = template.render(kwargs)
    path = OUTPUT_DIR / f"{basename}.{ending}"
    with open(path, mode="w") as f:
        f.write(out)
    return path


# Do the work
print("Compile odbc.ini file")
# TODO what about the password, servername and port here?
odbc_path = render_save("odbc.ini", secrets=script._secrets)

print("Compile slapd-debconf.txt")
debconf_path = render_save("slapd-debconf.txt", secrets=script._secrets)

print("Compile custom config-ldap.ldif")
# TODO set more values here dynamically form the config?
ldif_path = render_save("config-ldap.ldif", config=script.config, secrets=script._secrets)

if script.dry_run:
    print("Skip during dry run        -- Update apt")
    print("Skip during dry run        -- Install unixodbc and odbc-postgresql package")
    print("Skip during dry run        -- Copy odbc.ini file at /etc/odbc.ini")
    print("Skip during dry run        -- Apply slapd-debconf.txt")
    print("Skip during dry run        -- Install slapd")
    print("Skip during dry run        -- Remove predefined mdb")
    print("Skip during dry run        -- Apply config-ldap.ldif")
else:
    print("Update apt")
    subprocess.run(["apt-get", "update"], stdout=subprocess.DEVNULL, check=True)

    print("Install unixodbc and odbc-postgresql package")
    subprocess.run(["apt-get", "install", "-y", "unixodbc", "odbc-postgresql"],
                   stdout=subprocess.DEVNULL, check=True)

    print("Copy odbc.ini file at /etc/odbc.ini")
    shutil.copy(odbc_path, "/etc/odbc.ini")

    print("Apply slapd-debconf.txt")
    subprocess.run(["debconf-set-selections", f"{debconf_path}"], check=True)

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

    print("\nApply config-ldap.ldif:")
    subprocess.run([f"ldapmodify -Y EXTERNAL -H ldapi:/// -f {ldif_path}"], check=True,
                   shell=True, stderr=subprocess.DEVNULL)
