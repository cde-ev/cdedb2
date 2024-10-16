#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import multiprocessing
import threading
import unittest

from cdedb.backend.common import DatabaseLock
from cdedb.backend.core import CoreBackend
from cdedb.common import RequestState, User, make_proxy, now
from cdedb.common.exceptions import PrivilegeError
from cdedb.config import Config, SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.database.constants import LockType
from cdedb.frontend.common import setup_translations


# TODO: coverage seems to not pick this up correctly,
#  even with concurrency set to multiprocessing and/or thread.
def database_lock_job(
        first: threading.Semaphore, second: threading.Semaphore,
        control: threading.Semaphore,
        signal: "multiprocessing.Queue[int]") -> bool:  # pragma: no cover
    """See test_database_lock below.

    This needs to be top-level as we want to pickle it for multiprocessing.
    """
    config = Config()
    secrets = SecretsConfig()
    connpool = connection_pool_factory(
        config["CDB_DATABASE_NAME"], DATABASE_ROLES,
        secrets, config["DB_HOST"], config["DB_PORT"])
    translations = setup_translations(config)

    def setup_requeststate() -> RequestState:
        """Provide an entirely fake request state."""
        rs = RequestState(
            sessionkey=None,
            apitoken=None,
            user=User(),
            request=None,  # type: ignore[arg-type]
            notifications=[],
            mapadapter=None,  # type: ignore[arg-type]
            requestargs=None,
            errors=[],
            values=None,
            begin=now(),
            lang="de",
            translations=translations,
        )
        # We want to use this in the frontend, so we need to peek
        rs._conn = connpool['cdb_admin']  # pylint: disable=protected-access
        rs.conn = None  # type: ignore[assignment]
        return rs

    rs = setup_requeststate()

    with first:
        signal.put(1)
        with control:
            pass
        with DatabaseLock(rs, LockType.mailman) as lock:
            if lock:
                with second:
                    return True
            else:
                return False


class TestBackendCommon(unittest.TestCase):
    def test_make_proxy(self) -> None:
        backend = CoreBackend()
        proxy = make_proxy(backend)
        self.assertTrue(callable(proxy.get_persona))
        self.assertTrue(callable(proxy.login))
        self.assertTrue(callable(proxy.verify_personas))
        with self.assertRaises(PrivilegeError):
            # pylint: disable=pointless-statement
            proxy.verify_password  # exception in __getitem__

    def test_database_lock(self) -> None:
        manager: multiprocessing.managers.SyncManager
        with multiprocessing.Manager() as manager:
            semaphoreA = manager.Semaphore()
            semaphoreB = manager.Semaphore()
            control = manager.Semaphore()
            backchannel = manager.Queue()
            parameters = [(semaphoreA, semaphoreB, control, backchannel),
                          (semaphoreB, semaphoreA, control, backchannel)]

            control.acquire()
            with multiprocessing.Pool(2) as pool:
                result_async = pool.starmap_async(database_lock_job, parameters,
                                                  chunksize=1)
                readycount = 0
                while readycount < 2:
                    readycount += backchannel.get()
                control.release()
                result = result_async.get()

            self.assertIn(tuple(result), {(True, False), (False, True)})
