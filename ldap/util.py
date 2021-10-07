#!/usr/bin/env python3

"""This file provides some boilerplate to create, update and remove the CdEDB-LDAP.

The "Script" part is a slimmed version of cdedb.script.py. To keep the dependencies
(mostly for docker) very low, we use this instead of the original one. This also adds
some small tricks to handle the docker setting appropriately, since the docker ldap
runs in another container than the cdedb.
"""
import getpass
from passlib.hash import sha512_crypt
import pathlib
from typing import Any

import jinja2

from cdedb.script import Script


class LdapScript(Script):
    def __init__(self, *args: Any, check_system_user: bool = True, **kwargs: Any):
        if getpass.getuser() != "root":
            raise RuntimeError("Must be run as user root.")
        super().__init__(*args, check_system_user=False, **kwargs)

        # Setup some special stuff for ldap
        self.template_dir = self.config["REPOSITORY_PATH"] / "ldap/templates"
        self.output_dir = self.config["REPOSITORY_PATH"] / "ldap/output"
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)))

        if not self.output_dir.exists():
            self.output_dir.mkdir()

    def _connect(self, *args: Any, **kwargs: Any) -> None:
        """Don't actually connect if run in via docker."""
        if pathlib.Path("/CONTAINER").is_file():
            return None
        super()._connect(*args, **kwargs)

    def render_save(self, name: str, **kwargs) -> pathlib.Path:
        """Render a given template with the specified args and save it in self.output"""
        basename, ending = name.split(".")
        template = self.env.get_template(f"{basename}.tmpl")
        out = template.render(kwargs)
        path = self.output_dir / f"{basename}.{ending}"
        with open(path, mode="w") as f:
            f.write(out)
        return path

    @staticmethod
    def encrypt_password(password: str) -> str:
        """Reimplementation of `CoreBackend.encrypt_password`."""
        return sha512_crypt.hash(password)
