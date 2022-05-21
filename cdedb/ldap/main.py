import asyncio
import logging

# Install Twisted's asyncio-compatibility reactor.
# It's important to do this before importing other things
from twisted.internet import asyncioreactor

asyncioreactor.install()

import psycopg2.extras
import twisted.python.log
from aiopg import create_pool
from ldaptor.interfaces import IConnectedLDAPEntry
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

    logger.debug("Waiting for aiopg connection pool ...")
    async with create_pool(
            dbname=conf["CDB_DATABASE_NAME"],
            user="cdb_admin",
            password=secrets["CDB_DATABASE_ROLES"]["cdb_admin"],
            host=conf["DB_HOST"],
            port=conf["DB_PORT"],
            cursor_factory=psycopg2.extras.RealDictCursor,
    ) as pool:
        logger.debug("Got aiopg connection pool.")
        backend = LDAPsqlBackend(pool)
        factory = CdEDBLDAPServerFactory(backend)
        factory.debug = True
        # Tell twisted, how to transform the factory into an IConnectedLDAPEntry
        registerAdapter(lambda x: x.root, CdEDBLDAPServerFactory, IConnectedLDAPEntry)

        # Create Server
        logger.info("Opening LDAP server ...")
        reactor.listenTCP(conf["LDAP_PORT"], factory)  # type: ignore[attr-defined]
        reactor.startRunning()  # type: ignore[attr-defined]


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
