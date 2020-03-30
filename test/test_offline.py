#!/usr/bin/env python3

import pathlib
import subprocess

import webtest

from cdedb.frontend.application import Application
from test.common import FrontendTest


class TestOffline(FrontendTest):
    def test_offline_vm(self):
        base = pathlib.Path(__file__).parent.parent
        configpath = self.app.app.conf._configpath
        user = {
            'username': "garcia@example.cde",
            'password': "notthenormalpassword",
        }
        subprocess.run(
            ['sudo', '-u', 'cdb', 'psql', '-U', 'cdb', '-d', 'cdb_test',
             '-f', 'test/ancillary_files/clean_data.sql'],
            cwd=base, check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            subprocess.run(
                ['bin/make_offline_vm.py', '--test',
                 'test/ancillary_files/event_export.json'],
                cwd=base, check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            # Reset web test app for changed configuration
            new_app = Application(configpath)
            self.app = webtest.TestApp(new_app, extra_environ={
                'REMOTE_ADDR': "127.0.0.0",
                'SERVER_PROTOCOL': "HTTP/1.1",
                'wsgi.url_scheme': 'https'})
            self.app.reset()

            # Test that it's running
            self.get('/')
            self.assertPresence(
                'Dies ist eine Offline-Instanz der CdE-Datenbank')
            self.login(user)

            # Basic event functionality
            self.traverse({'href': '/event/'},
                          {'href': '/event/1/show'})
            self.assertTitle("Große Testakademie 2222")
            self.assertPresence(
                'Die Veranstaltung befindet sich im Offline-Modus.')
            self.traverse({'href': 'event/event/1/registration/query'},
                          {'description': 'Alle Anmeldungen'})
            self.assertPresence('6', 'query-results')
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

            # Additional tests can be added here.
            # Due to the expensive setup of this test these should not
            # be split out.
        finally:
            subprocess.run(["git", "checkout", str(configpath)], check=True)
            subprocess.run(["sudo", "rm", "-f", "/OFFLINEVM"], check=True)
            subprocess.run(
                ["make", "reload"], check=True, cwd=base,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
