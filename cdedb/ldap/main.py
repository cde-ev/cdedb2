
import asyncio
import logging
import signal

# Install Twisted's asyncio-compatibility reactor.
# It's important to do this before importing other things
from twisted.internet import asyncioreactor
asyncioreactor.install(asyncio.get_event_loop())

import psycopg2.extras
from aiopg import create_pool
from ldaptor.interfaces import IConnectedLDAPEntry
from ldaptor.protocols.ldap.ldapserver import LDAPServer
import twisted.python.log
from twisted.internet.protocol import ServerFactory, Factory
from twisted.python.components import registerAdapter

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry

from twisted.internet import reactor
assert isinstance(reactor, asyncioreactor.AsyncioSelectorReactor)

logger = logging.getLogger(__name__)


class LDAPServerFactory(Factory):
    protocol = LDAPServer

    def __init__(self, backend):
        self.root = RootEntry(backend)


async def main():
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
        factory = LDAPServerFactory(backend)
        factory.protocol = LDAPServer
        factory.debug = True
        # Tell twisted, how to transform the factory into an IConnectedLDAPEntry
        registerAdapter(lambda x: x.root, LDAPServerFactory, IConnectedLDAPEntry)

        # Create Server
        logger.info("Opening LDAP server ...")
        reactor.listenTCP(20389, factory)
        reactor.startRunning()

        # Wait for shutdown via Signal handler and event
        shutdown = asyncio.Event()
        asyncio.get_event_loop().add_signal_handler(signal.SIGINT, shutdown.set)
        logger.warning("Startup completed")
        await shutdown.wait()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.get_event_loop().run_until_complete(main())
