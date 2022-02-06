import asyncio
import sys

from twisted.internet import asyncioreactor

asyncioreactor.install()

import psycopg2.extras
from aiopg import create_pool
from ldaptor.interfaces import IConnectedLDAPEntry
from twisted.application import service
from twisted.internet import reactor
from twisted.internet.defer import Deferred, ensureDeferred
from twisted.python import log
from twisted.python.components import registerAdapter

from cdedb.config import Config, SecretsConfig
from cdedb.ldap.backend import LDAPsqlBackend
from cdedb.ldap.entry import RootEntry
from cdedb.ldap.server import LDAPServerFactory

if __name__ == "__main__":
    # show logging info
    log.startLogging(sys.stderr)

    async def run_twisted(reactor):
        port = 20389
        backend = await Deferred.fromFuture(asyncio.ensure_future(start_backend(reactor)))
        root = RootEntry(backend=backend)
        registerAdapter(lambda x: x.root, LDAPServerFactory, IConnectedLDAPEntry)
        factory = LDAPServerFactory(root)
        factory.debug = True
        application = service.Application("ldaptor-server")
        myService = service.IServiceCollection(application)
        reactor.listenTCP(port, factory)


    async def start_backend(reactor):
        conf = Config()
        secrets = SecretsConfig()
        pool = await create_pool(
            dbname=conf["CDB_DATABASE_NAME"],
            user="cdb_admin",
            password=secrets["CDB_DATABASE_ROLES"]["cdb_admin"],
            host=conf["DB_HOST"],
            port=conf["DB_PORT"],
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return LDAPsqlBackend(pool)


    ensureDeferred(run_twisted(reactor))
    reactor.run()
