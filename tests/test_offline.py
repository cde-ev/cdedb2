#!/usr/bin/env python3

import pathlib
import shutil
import subprocess
import sys

import webtest

from cdedb.common import ADMIN_VIEWS_COOKIE_NAME, ALL_ADMIN_VIEWS
from cdedb.frontend.application import Application
from tests.common import FrontendTest


class TestOffline(FrontendTest):
    def test_offline_vm(self) -> None:
        base = pathlib.Path(__file__).parent.parent
        user = {
            'username': "garcia@example.cde",
            'password': "notthenormalpassword",
        }
        existing_config = base / "cdedb/localconfig.py"
        config_backup = base / "cdedb/localconfig.copy"
        if existing_config.exists():
            shutil.copyfile(
                existing_config, config_backup)
        subprocess.run(
            ['bin/execute_sql_script.py', '-U', 'cdb', '-d', 'cdb_test',
             '-f', 'tests/ancillary_files/clean_data.sql'],
            cwd=base, check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run(
                ['bin/make_offline_vm.py', '--test', '--no-extra-packages',
                 'tests/ancillary_files/event_export.json'],
                cwd=base, check=True, stdout=subprocess.DEVNULL)
            # Reset web test app for changed configuration
            try:
                del sys.modules['cdedb.localconfig']
            except AttributeError:
                pass
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
            self.assertTitle('Anton Armin A. Administrator bearbeiten')
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
                'CDEDB_EXPORT_EVENT_VERSION',
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
            if config_backup.exists():
                shutil.move(str(config_backup), existing_config)
            else:
                subprocess.run(
                    ["cp", "related/auto-build/files/stage3/localconfig.py",
                     "cdedb/localconfig.py"], check=True)
            subprocess.run(["sudo", "rm", "-f", "/OFFLINEVM"], check=True)
            subprocess.run(
                ["make", "reload"], check=True, cwd=base,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
