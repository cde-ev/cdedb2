#!/usr/bin/env python3
# pylint: disable=missing-module-docstring
import os
import shutil
import subprocess

import webtest

from cdedb.common import ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS
from cdedb.frontend.application import Application
from cdedb.setup.config import get_configpath
from tests.common import FrontendTest


class TestOffline(FrontendTest):
    def test_offline_vm(self) -> None:
        repopath = self.conf["REPOSITORY_PATH"]
        user = {
            'username': "garcia@example.cde",
            'password': "notthenormalpassword",
        }

        # save the current config, so we can reset if after the test ends
        existing_config = get_configpath()
        config_backup = existing_config.parent / f"{existing_config.name}.copy"
        shutil.copyfile(existing_config, config_backup)

        try:
            # give the environment (especially the current CDEDB_CONFIGPATH) to the
            # subprocess. Since the test configpaths use imports from test, we append
            # the whole repo to the PYTHONPATH so they are found.
            env = {**os.environ.copy(), "PYTHONPATH": str(repopath)}
            subprocess.run(
                [repopath / 'bin/make_offline_vm.py', '--test', '--no-extra-packages',
                 repopath / 'tests/ancillary_files/event_export.json'],
                check=True, env=env)
            # Reset web test app for changed configuration
            new_app = Application()
            self.app = webtest.TestApp(  # type: ignore
                new_app, extra_environ=self.app_extra_environ)
            self.app.reset()
            self.app.set_cookie(ADMIN_VIEWS_COOKIE_NAME,
                                ",".join(ALL_ADMIN_VIEWS))

            # Test that it's running
            self.get('/')
            self.assertPresence('Dies ist eine Offline-Instanz der CdE-Datenbank',
                                div='static-notifications')
            self.login(user)

            # Basic event functionality
            self.traverse({'href': '/event/'},
                          {'href': '/event/1/show'})
            self.assertTitle("Große Testakademie 2222")
            self.assertPresence(
                'Die Veranstaltung befindet sich im Offline-Modus.')
            self.traverse({'href': 'event/event/1/registration/query'},
                          {'description': 'Alle Anmeldungen'})
            self.assertPresence('6', div='query-results')
            self.assertPresence('Inga')

            # Test edit of profile
            self.traverse({'href': 'event/event/1/registration/query'},
                          {'description': 'Alle Anmeldungen'},
                          {'href': 'event/event/1/registration/1/show'},
                          {'href': 'core/persona/1/show'},
                          {'href': 'core/persona/1/adminchange'})
            self.assertTitle('Anton Administrator bearbeiten')
            f = self.response.forms['changedataform']
            f['display_name'] = "Zelda"
            f['birthday'] = "3.4.1933"
            self.submit(f)
            self.assertPresence("Zelda")
            self.assertTitle("Anton Armin A. Administrator")
            self.assertPresence("03.04.1933")

            # Test quick partial export
            self.logout()
            self.get(
                '/event/offline/partial',
                headers={'X-CdEDB-API-token': 'y1f2i3d4x5b6'})
            self.assertEqual(self.response.json["message"], "success")
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
            self.assertEqual(set(self.response.json["export"]), expectation)

            # Additional tests can be added here.
            # Due to the expensive setup of this test these should not
            # be split out.
        finally:
            # restore the original config
            shutil.move(str(config_backup), existing_config)

            # remove the file signaling that we are inside an offline vm
            subprocess.run(["sudo", "rm", "-f", "/OFFLINEVM"], check=True)
