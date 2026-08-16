#!/usr/bin/env python3

from types import SimpleNamespace

from bin.insert_huge_data import perform

from tests.common import FrontendTest, storage


class TestHugeData(FrontendTest):
    @storage
    def test_huge_data_script(self) -> None:
        user = {
            'username': "Email0000000000@example.cde",
            'password': "secret",
        }

        args = SimpleNamespace(
            personas=1,
            events=1,
            assemblies=1,
            pastevents=1,
            mailinglists=1,
            factor=1,
            verbose=False,
            quick=True,
        )
        perform(args)  # type: ignore[arg-type]

        self.login(user)
