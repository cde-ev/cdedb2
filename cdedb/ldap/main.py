"""Entrypoint for ldaptor."""

# pylint: disable=wrong-import-position,ungrouped-imports

import asyncio
import logging

# Install Twisted's asyncio-compatibility reactor.
# It's important to do this before importing other things
from twisted.internet import asyncioreactor

asyncioreactor.install()

import twisted.python.log
from ldaptor.interfaces import IConnectedLDAPEntry
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from twisted.internet import reactor
from twisted.python.components import registerAdapter

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.server import CdEDBLDAPServerFactory

assert isinstance(reactor, asyncioreactor.AsyncioSelectorReactor)

logger = logging.getLogger(__name__)


async def main() -> None:
    conf = Config()
    secrets = SecretsConfig()

    # twisted logging config
    observer = twisted.python.log.PythonLoggingObserver()
    observer.start()

    logger.debug("Waiting for database connection ...")
    conn_params = dict(
        dbname=conf["CDB_DATABASE_NAME"],
        user="cdb_ldap",
        password=secrets["CDB_DATABASE_ROLES"]["cdb_ldap"],
        host=conf["DB_HOST"],
        port=conf["DB_PORT"],
    )
    conn_info = " ".join([f"{k}={v}" for k, v in conn_params.items()])
    conn_kwargs = {"row_factory": dict_row}
    pool = AsyncConnectionPool(conn_info, min_size=1, max_size=10, kwargs=conn_kwargs)
    await pool.open(wait=True)
    logger.debug("Got database connection.")
    backend = LDAPsqlBackend(pool)
    factory = CdEDBLDAPServerFactory(backend, debug=True)
    # Tell twisted, how to transform the factory into an IConnectedLDAPEntry
    registerAdapter(lambda x: x.root, CdEDBLDAPServerFactory, IConnectedLDAPEntry)

    # Create Server
    logger.info("Opening LDAP server ...")
    reactor.listenTCP(conf["LDAP_PORT"], factory)  # type: ignore[attr-defined]
    reactor.startRunning()  # type: ignore[attr-defined]
    logger.warning("Startup completed")


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
