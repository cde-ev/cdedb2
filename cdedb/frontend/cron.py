#!/usr/bin/env python3

"""Services for executing periodic jobs.

This expects a period of 15 minutes.
"""

import gettext
import inspect
import pathlib
from typing import Collection, Iterator

from cdedb.common import ALL_ROLES, PathLike, RequestState, User, n_, now
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.frontend.assembly import AssemblyFrontend
from cdedb.frontend.cde import CdEFrontend
from cdedb.frontend.common import AbstractFrontend, BaseApp, PeriodicJob
from cdedb.frontend.core import CoreFrontend
from cdedb.frontend.event import EventFrontend
from cdedb.frontend.ml import MlFrontend
from cdedb.frontend.paths import CDEDB_PATHS


class CronFrontend(BaseApp):
    """This takes care of actually doing the periodic work."""
    realm = "cron"

    def __init__(self, configpath: PathLike = None) -> None:
        super().__init__(configpath)

        self.urlmap = CDEDB_PATHS
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
            secrets, self.conf["DB_PORT"])
        self.translations = {
            lang: gettext.translation(
                'cdedb', languages=[lang],
                localedir=str(self.conf["REPOSITORY_PATH"] / 'i18n'))
            for lang in self.conf["I18N_LANGUAGES"]}
        if pathlib.Path("/PRODUCTIONVM").is_file():
            # Sanity checks for the live instance
            if self.conf["CDEDB_DEV"] or self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                raise RuntimeError(
                    n_("Refusing to start in debug/offline mode."))

        self.core = CoreFrontend(configpath)
        self.cde = CdEFrontend(configpath)
        self.event = EventFrontend(configpath)
        self.assembly = AssemblyFrontend(configpath)
        self.ml = MlFrontend(configpath)

    def make_request_state(self) -> RequestState:
        roles = ALL_ROLES
        user = User(roles=roles, persona_id=None)
        lang = "en"
        urls = self.urlmap.bind("db.cde-ev.de", script_name="/db/",
                                url_scheme="https")
        # This is not a real request, so we can go without some of these.
        rs = RequestState(
            sessionkey=None, apitoken=None, user=user, request=None,  # type: ignore
            notifications=[], mapadapter=urls, requestargs={}, errors=[],
            values=None, lang=lang, begin=None,
            gettext=self.translations[lang].gettext,
            ngettext=self.translations[lang].ngettext)
        rs._conn = self.connpool['cdb_admin']  # pylint: disable=protected-access
        return rs

    def execute(self, jobs: Collection[str] = None) -> bool:
        """
        :param jobs: If jobs is given execute only these jobs.
        """
        rs = self.make_request_state()
        base_state = self.core.get_cron_store(rs, "_base")
        if not base_state:
            base_state = {
                'tstamp': 0,
                'period': -1,
            }
        if (not self.conf["CDEDB_DEV"]
                and base_state['tstamp'] + 10*60 > now().timestamp()):
            print("Last execution at {} skipping this round.".format(
                base_state['tstamp']))
            return False
        base_state['tstamp'] = now().timestamp()
        base_state['period'] += 1

        try:
            for frontend in (self.core, self.cde, self.event, self.assembly,
                             self.ml):
                for hook in self.find_periodics(frontend):
                    if jobs and hook.cron['name'] not in jobs:
                        continue
                    if (base_state['period'] % hook.cron['period'] == 0
                            or self.conf["CDEDB_DEV"]):
                        rs.begin = now()
                        state = self.core.get_cron_store(rs, hook.cron['name'])
                        self.logger.info(f"Starting execution of {hook.cron['name']}:")
                        # noinspection PyBroadException
                        try:
                            tmp = hook(rs, state)
                        except Exception:
                            self.logger.error(
                                f">>>\n>>>\n>>>\n>>> Exception while executing"
                                f" {hook.cron['name']} <<<\n<<<\n<<<\n<<<")
                            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
                            self.logger.error("SECOND TRY CGITB")
                            self.cgitb_log()
                            if self.conf["CDEDB_TEST"]:
                                raise
                        else:
                            self.core.set_cron_store(rs, hook.cron['name'], tmp)
                        finally:
                            time_taken = now() - rs.begin
                            self.logger.info(
                                f"Finished execution of {hook.cron['name']}."
                                f" Time taken: {time_taken}.")
        finally:
            self.core.set_cron_store(rs, "_base", base_state)
        return True

    @staticmethod
    def find_periodics(frontend: AbstractFrontend) -> Iterator[PeriodicJob]:
        for _, func in inspect.getmembers(frontend, inspect.ismethod):
            if hasattr(func, "cron"):
                yield func
