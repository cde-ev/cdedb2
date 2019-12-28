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

            user = {
                'username': "garcia@example.cde",
                'password': "notthenormalpassword",
            }
            self.get('/')
            self.assertPresence(
                'Dies ist eine Offline-Instanz der CdE-Datenbank')
            self.login(user)
            self.traverse({'href': '/event/'},
                          {'href': '/event/1/show'})
            self.assertTitle("Große Testakademie 2222")
            self.assertPresence(
                'Die Veranstaltung befindet sich im Offline-Modus.')
            self.traverse({'href': 'event/event/1/registration/query'},
                          {'description': 'Alle Anmeldungen'})
            self.assertPresence('Ergebnis [4]')
            self.assertPresence('Inga')
        finally:
            subprocess.run(
                ["sed", "-i", "-e", "s/CDEDB_DEV = False/CDEDB_DEV = True/",
                 str(configpath)], check=True)
            subprocess.run(
                ["sed", "-i", "-e", "s/CDEDB_OFFLINE_DEPLOYMENT = True//",
                 str(configpath)], check=True)
            subprocess.run(["make", "reload"], check=True, cwd=base)
