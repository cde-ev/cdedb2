#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import os
import subprocess

from tests.common import FrontendTest, storage


class TestHugeData(FrontendTest):
    @storage
    def test_huge_data_script(self) -> None:
        repopath = self.conf["REPOSITORY_PATH"]
        user = {
            'username': "Email0000000000@example.cde",
            'password': "secret",
        }
        # give the environment (especially the current CDEDB_CONFIGPATH) to the
        # subprocess. Since the test configpaths use imports from test, we append
        # the whole repo to the PYTHONPATH so they are found.
        env = {**os.environ.copy(), "PYTHONPATH": str(repopath)}
        subprocess.run([repopath / 'bin/insert_huge_data.py', '--quick'],
                       check=True, env=env)
        self.login(user)
