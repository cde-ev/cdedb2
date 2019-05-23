#!/usr/bin/env python3

"""Services for executing periodic jobs.

This expects a period of 15 minutes.
"""

import cgitb
import gettext
import inspect
import pathlib
import sys

from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.common import n_, glue, now, RequestState, User
from cdedb.frontend.common import BaseApp
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.paths import CDEDB_PATHS


class CronFrontend(BaseApp):
    """This takes care of actually doing the periodic work."""
    realm = "cron"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)

        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            secrets, self.conf.DB_PORT)
        self.translations = {
            lang: gettext.translation(
                'cdedb', languages=(lang,),
                localedir=str(self.conf.REPOSITORY_PATH / 'i18n'))
            for lang in self.conf.I18N_LANGUAGES}
        if pathlib.Path("/DBVM").is_file():
            # Sanity checks for the live instance
            if self.conf.CDEDB_DEV or self.conf.CDEDB_OFFLINE_DEPLOYMENT:
                raise RuntimeError(n_("Refusing to start in debug mode."))

        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)

    def make_request_state(self):
        roles = {
            "anonymous", "persona", "cde", "event", "ml", "assembly",
            "member", "searchable",
            "cde_admin", "event_admin", "ml_admin", "assembly_admin",
            "core_admin",
            "admin",
        }
        user = User(roles=roles, persona_id=None, username=None,
                    given_names=None, display_name=None, family_name=None)
        lang = "en"
        coders = {
            "encode_parameter": self.encode_parameter,
            "decode_parameter": self.decode_parameter,
            "encode_notification": self.encode_notification,
            "decode_notification": self.decode_notification,
        }
        urls = self.urlmap.bind("db.cde-ev.de/db", url_scheme='https')
        rs = RequestState(
            None, user, None, None, [], urls, {},
            [], {}, lang,
            self.translations[lang].gettext,
            self.translations[lang].ngettext, coders, None,
            None)
        rs._conn = self.connpool['cdb_admin']
        return rs

    def execute(self, jobs=None):
        """
        :param jobs: If jobs is given execute only these jobs.
        :type jobs: [str]
        """
        rs = self.make_request_state()
        base_state = self.core.get_cron_store(rs, "_base")
        if not base_state:
            base_state = {
                'tstamp': 0,
                'period': -1,
            }
        if base_state['tstamp'] + 10*60 > now().timestamp():
            print("Last execution at {} skipping this round.".format(
                base_state['tstamp']))
            return False
        base_state['tstamp'] = now().timestamp()
        base_state['period'] += 1

        banner = glue(">>>\n>>>\n>>>\n>>> Exception while executing {}",
                      "<<<\n<<<\n<<<\n<<<")
        try:
            for frontend in (self.core, self.cde, self.event, self.assembly,
                             self.ml):
                for hook in self.find_periodics(frontend):
                    if jobs and hook.cron['name'] not in jobs:
                        continue
                    if base_state['period'] % hook.cron['period'] == 0:
                        rs.begin = now()
                        state = self.core.get_cron_store(rs, hook.cron['name'])
                        try:
                            tmp = hook(rs, state)
                        except Exception:
                            self.logger.error(banner.format(hook.cron['name']))
                            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
                            self.logger.error("SECOND TRY CGITB")
                            self.logger.error(cgitb.text(sys.exc_info(),
                                                         context=7))
                        else:
                            self.core.set_cron_store(rs, hook.cron['name'],
                                                     tmp)
        finally:
            self.core.set_cron_store(rs, "_base", base_state)
        return True

    @staticmethod
    def find_periodics(frontend):
        for name, func in inspect.getmembers(frontend, inspect.ismethod):
            if hasattr(func, "cron"):
                yield func
