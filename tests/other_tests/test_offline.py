#!/usr/bin/env python3
import pathlib
import subprocess
import tempfile

import webtest
from bin.make_offline_vm import work

import cdedb.models.droid as model_droid
from cdedb.cli.database import connect
from cdedb.common.roles import ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS
from cdedb.config import SecretsConfig
from cdedb.frontend.application import Application
from tests.common import FrontendTest, storage


class TestOffline(FrontendTest):
    @storage
    def test_offline_vm(self) -> None:
        repopath = self.conf["REPOSITORY_PATH"]
        user = {
            'username': "garcia@example.cde",
            'password': "notthenormalpassword",
        }

        # write the original config in a temporary config file
        config = tempfile.NamedTemporaryFile(
            "w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        )
        with self.conf.with_overrides(
            config_paths=[pathlib.Path(config.name)] + self.conf.get_config_paths()
        ):
            # purge the content of the database
            purge_database = repopath / 'tests' / 'ancillary_files' / 'clean_data.sql'
            with connect(self.conf, SecretsConfig()) as conn:
                with conn.cursor() as curr:
                    curr.execute(purge_database.read_text())

            try:
                work(
                    repopath / "tests" / "ancillary_files" / "event_export.json",
                    conf=self.conf,
                    is_interactive=False,
                    no_extra_packages=True,
                )

                # Reset web test app for changed configuration
                new_app = Application()
                self.__class__.app = webtest.TestApp(
                    new_app, extra_environ=self.app_extra_environ
                )
                self.app.reset()
                self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME, ",".join(ALL_ADMIN_VIEWS))

                # Test that it's running
                self.get('/')
                self.assertPresence(
                    'Dies ist eine Offline-Instanz der CdE-Datenbank',
                    div='static-notifications',
                )
                self.login(user)

                # Basic event functionality
                self.traverse(
                    "Veranstaltungen",
                    "Große Testakademie 2222",
                    "Anmeldungen",
                    "Alle Anmeldungen",
                )
                self.assertPresence('6', div='query-results')
                self.assertPresence('Inga')

                # Test edit of profile
                self.traverse(
                    {'href': 'event/event/1/registration/query'},
                    {'description': 'Alle Anmeldungen'},
                    {'href': 'event/event/1/registration/1/show'},
                    {'href': 'core/persona/1/show'},
                    {'href': 'core/persona/1/adminchange'},
                )
                self.assertTitle('Anton Administrator bearbeiten')
                f = self.response.forms['changedataform']
                f['nickname'] = "Zelda"
                f['birthday'] = "3.4.1933"
                self.submit(f)
                self.assertPresence("Zelda")
                self.assertTitle("Anton Administrator")
                self.assertPresence("03.04.1933")

                # Test quick partial export
                self.logout()
                self.get(
                    '/event/offline/partial',
                    headers={
                        model_droid.APIToken.request_header_key: model_droid.QuickPartialExportToken.get_token_string(
                            self.secrets['API_TOKENS']['quick_partial_export']
                        ),
                    },
                )
                expectation = {
                    'EVENT_SCHEMA_VERSION',
                    'kind',
                    'timestamp',
                    'id',
                    'event',
                    'lodgement_groups',
                    'lodgements',
                    'courses',
                    'registrations',
                }
                self.assertEqual(set(self.response.json), expectation)
                self.login(user)

                # Test event keeper works properly, by triggering a manual commit
                self.get('/event/event/1/field/setselect?kind=1')
                self.assertTitle("Datenfeld auswählen (Große Testakademie 2222)")
                f = self.response.forms['selectfieldform']
                f['field_id'] = 3
                self.submit(f)
                self.assertTitle("Datenfeld lodge setzen (Große Testakademie 2222)")
                f = self.response.forms['fieldform']
                f['fields.lodge1'] = (
                    "Ich will auf jeden Fall mit Anton A. auf ein Zimmer!"
                )
                f['change_note'] = "EventKeeper test commit."
                self.submit(f)

                # Additional tests can be added here.
                # Due to the expensive setup of this test these should not
                # be split out.
            finally:
                # remove the temporary config
                pathlib.Path(config.name).unlink()

                # remove the file signaling that we are inside an offline vm
                subprocess.run(["sudo", "rm", "-f", "/OFFLINEVM"], check=True)
