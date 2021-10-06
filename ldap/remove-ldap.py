"""This removes the ldap server on the local maschine."""

import subprocess

# Do the work
print("Remove slapd")
subprocess.run(["apt-get", "remove", "--purge", "-y", "slapd"],
               stdout=subprocess.DEVNULL, check=True)
