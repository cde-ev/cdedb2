"""This removes the ldap server on the local maschine."""

import subprocess

from util import LdapScript

# Setup
script = LdapScript()

# Do the work
if script.dry_run:
    print("Skip during dry run        -- Remove slapd")
else:
    print("Remove slapd")
    subprocess.run(["apt-get", "remove", "--purge", "-y", "slapd"],
                   stdout=subprocess.DEVNULL, check=True)
