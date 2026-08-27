#! /usr/bin/env -S uv run
import subprocess
import sys

old, new = sys.argv[1:3]

shortlog = subprocess.check_output(["git", "shortlog", f"{old}..{new}"]).decode("utf-8")

print(f"""
# Wesentliche Änderungen

# Commit-Übersicht

[GitHub (öffentlich)](https://github.com/cde-ev/cdedb2/compare/{old}...{new})
[CdE-ForgeJo (Zugriff auf Anfrage)](https://tracker.cde-ev.de/cdedb/cdedb2/compare/{old}...{new})

# Shortlog

[details="Shortlog"]
```
{shortlog}
```
[/details]
""".strip())
